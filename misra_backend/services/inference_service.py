"""Explicit task providers with loopback adapters for local inference."""
import base64
import asyncio
import io
import json
import os
import re
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
import urllib.request

from PIL import Image
from services.free_model_gateway import FreeCompletion, complete_free
from services.gemini_client import DEFAULT_MODEL, generate as gemini_generate
from services.openrouter_client import OpenRouterError

PROFILE_SUPPORT_VERSION = 6


class LocalInferenceError(OpenRouterError):
    """Safe error returned to instructors and classified as a terminal attempt."""


class LocalInferenceInputError(ValueError):
    """Local inference cannot accept the approved evidence for this request."""


def _cuda_runner_failed(error):
    if not isinstance(error, HTTPError) or error.code != 500:
        return False
    try:
        detail = json.loads(error.read(4096)).get('error', '')
        return isinstance(detail, str) and bool(re.search(
            r'CUDA error|runner.*(?:0xc0000409|3221226505)|server process has terminated:.*0xc0000409',
            detail, re.IGNORECASE))
    except (ValueError, AttributeError, OSError):
        return False
    finally:
        error.close()


def configuration(task):
    from services.inference_profiles import active_profile
    profile = active_profile()
    if profile and task in profile['tasks']:
        return dict(profile['tasks'][task])
    inherited = os.getenv('GRADING_PROVIDER', os.getenv('MISRA_AI_PROVIDER', 'gemini')) if task == 'verification' else os.getenv('MISRA_AI_PROVIDER', 'gemini')
    provider = os.getenv(f'{task.upper()}_PROVIDER', inherited)
    model = os.getenv(f'{task.upper()}_MODEL')
    if not model:
        model = (os.getenv('LOCAL_AI_MODEL', '') if provider == 'local' else
                 os.getenv('OPENROUTER_GRADING_MODEL', 'nvidia/nemotron-3-super-120b-a12b:free')
                 if provider == 'openrouter_free' else DEFAULT_MODEL)
    return {'provider': provider, 'model': model}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('Local inference redirects are not allowed.')


def _ollama_json(path, *, body=None, timeout=3):
    """No proxy, redirects or unbounded responses for local evidence transport."""
    from services.inference_profiles import active_profile, local_profile
    from services.grading_control import grading_checkpoint
    profile = active_profile() or local_profile()
    if path == '/api/chat' and grading_checkpoint.get():
        return asyncio.run(_cancellable_ollama_chat(profile['local_base_url'] + path, body, timeout))
    request = urllib.request.Request(profile['local_base_url'] + path,
        data=json.dumps(body).encode('utf-8') if body is not None else None,
        headers={'Content-Type': 'application/json'}, method='POST' if body is not None else 'GET')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    with opener.open(request, timeout=timeout) as response:
        data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise ValueError('Local response exceeds the allowed size.')
        return json.loads(data)


async def _cancellable_ollama_chat(url, body, timeout, *, check_interval=.75):
    """Cancel the local HTTP request even while Ollama is loading or evaluating."""
    import httpx
    from services.grading_control import check_grading_active

    async def receive():
        try:
            async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=timeout) as client:
                async with client.stream('POST', url, json=body) as response:
                    limit = 4096 if response.is_error else 2 * 1024 * 1024
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(data) + len(chunk) > limit:
                            raise ValueError('Local response exceeds the allowed size.')
                        data.extend(chunk)
                    if response.is_error or response.is_redirect:
                        raise HTTPError(url, response.status_code, response.reason_phrase, {}, io.BytesIO(data))
                    return json.loads(data)
        except httpx.TimeoutException as error:
            raise TimeoutError() from error
        except httpx.RequestError as error:
            raise OSError('Local inference connection failed.') from error

    check_grading_active()
    request = asyncio.create_task(receive())
    try:
        while not (await asyncio.wait((request,), timeout=check_interval))[0]:
            check_grading_active()
        check_grading_active()
        return request.result()
    finally:
        if not request.done():
            request.cancel()
        await asyncio.gather(request, return_exceptions=True)


def _encode_local_image(item, count, total_bytes):
    with io.BytesIO() as buffer:
        item.convert('RGB').save(buffer, format='PNG')
        total_bytes += buffer.tell()
        if count > 30 or buffer.tell() > 16*1024*1024 or total_bytes > 32*1024*1024:
            raise LocalInferenceInputError('Inference images exceed the configured evidence limits.')
        return base64.b64encode(buffer.getvalue()).decode('ascii'), total_bytes


def _ollama_completion(contents, model, *, vision=False, response_schema=None, json_mode=True):
    from services.inference_profiles import active_profile, TEXT_ONLY_IMAGE_ERROR, use_vision_cpu, vision_cpu_only
    profile = active_profile()
    items = [contents] if isinstance(contents, str) else list(contents)
    text_parts = []
    images = []
    total_bytes = 0
    for item in items:
        if isinstance(item, str):
            text_parts.append(item)
        elif vision and isinstance(item, Image.Image):
            encoded, total_bytes = _encode_local_image(item, len(images) + 1, total_bytes)
            images.append(encoded)
        elif vision:
            raise LocalInferenceInputError('Unsupported inference input.')
        else:
            raise LocalInferenceInputError(TEXT_ONLY_IMAGE_ERROR)
    prompt = '\n'.join(text_parts)
    prompt_bytes = len(prompt.encode('utf-8'))
    # The text-only path retains its byte guard. Vision uses Ollama's token
    # budget with truncation disabled for the combined text and image input.
    if not vision and prompt_bytes > profile['context_tokens'] - profile['max_output_tokens'] - 1024:
        raise LocalInferenceInputError('This grading package exceeds the local context budget. Use a configured model with sufficient context; the evidence was not truncated.')
    context_tokens = profile['context_tokens']
    if vision and len(images) <= 1 and prompt_bytes <= 20 * 1024:
        # Smaller single-page requests need less KV-cache memory on local GPUs.
        # Truncation is disabled below, so oversized inputs fail intact.
        context_tokens = min(context_tokens, 16384)
    message = {'role': 'user', 'content': prompt}
    if images:
        message['images'] = images
    body = {'model': model, 'messages': [message], 'stream': False, 'think': False,
        'options': {'temperature': 0, 'seed': 42, 'num_ctx': context_tokens,
                    'num_predict': profile['max_output_tokens']}}
    if response_schema is not None or json_mode:
        body['format'] = response_schema if response_schema is not None else 'json'
    if vision:
        body.update(truncate=False, shift=False)
        if vision_cpu_only():
            body['options']['num_gpu'] = 0
    started = perf_counter()
    from services.grading_control import check_grading_active
    try:
        try:
            payload = _ollama_json('/api/chat', body=body, timeout=900 if vision else 180)
        except HTTPError as error:
            gpu_failed = _cuda_runner_failed(error)
            if not vision or vision_cpu_only() or not gpu_failed:
                raise
            check_grading_active()
            use_vision_cpu()
            body = {**body, 'options': {**body['options'], 'num_gpu': 0}}
            payload = _ollama_json('/api/chat', body=body, timeout=900)
    except HTTPError as error:
        error.close()
        reason = (f'Model {model} is unavailable. Check the installed models in Ollama.' if error.code == 404
                  else f'Ollama returned HTTP {error.code}. Check the local Ollama server log.')
        if vision and vision_cpu_only():
            reason = 'Ollama could not complete the CPU attempt after the vision GPU runner failed. Check the local Ollama server log.'
        raise LocalInferenceError(reason) from None
    except TimeoutError:
        raise LocalInferenceError('Ollama timed out. Check local model performance before retrying.') from None
    except (OSError, URLError):
        raise LocalInferenceError('Cannot reach Ollama. Start the local Ollama server and check the selected models before retrying.') from None
    except (ValueError, TypeError):
        raise LocalInferenceError('Ollama returned an unreadable response. Check the local Ollama server log.') from None
    message = payload.get('message') if isinstance(payload, dict) else None
    text = message.get('content') if isinstance(message, dict) else None
    if isinstance(payload, dict) and payload.get('done_reason') == 'length':
        raise LocalInferenceError('Ollama reached the output limit before finishing. The incomplete response was rejected.')
    if (not isinstance(payload, dict) or payload.get('model') != model or payload.get('done') is not True
            or payload.get('done_reason') != 'stop' or not isinstance(message, dict) or message.get('tool_calls')
            or not isinstance(text, str) or not text.strip()):
        raise LocalInferenceError('Ollama returned an incomplete or mismatched response. Check the local Ollama server log.')
    return FreeCompletion(text, {'provider': 'local', 'model': model,
        'inference_profile': profile['id'],
        'cpu_vision': vision and vision_cpu_only(),
        'transport': 'ollama', 'image_count': len(images), 'latency_ms': round((perf_counter()-started)*1000),
        'reported_cost_usd': None, 'prompt_tokens': payload.get('prompt_eval_count'),
        'completion_tokens': payload.get('eval_count'), 'context_tokens': context_tokens})


def verification_enabled():
    from services.inference_profiles import active_profile
    profile = active_profile()
    return bool(profile['verification_enabled']) if profile else os.getenv('VERIFICATION_ENABLED', 'true').lower() == 'true'


def _local_completion(contents, model):
    endpoint = os.getenv('LOCAL_AI_BASE_URL', 'http://127.0.0.1:11434/v1').rstrip('/')
    url = urlparse(endpoint)
    if url.scheme not in {'http', 'https'} or url.hostname not in {'localhost', '127.0.0.1', '::1'} or url.username or url.password or url.query or url.fragment:
        raise ValueError('LOCAL_AI_BASE_URL must name a loopback inference server.')
    if not model:
        raise ValueError('Set LOCAL_AI_MODEL to an installed model before using local inference.')
    parts = []
    count = total_bytes = 0
    for item in [contents] if isinstance(contents, str) else contents:
        if isinstance(item, str):
            parts.append({'type': 'text', 'text': item})
        elif isinstance(item, Image.Image):
            count += 1
            encoded, total_bytes = _encode_local_image(item, count, total_bytes)
            parts.append({'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + encoded}})
        else:
            raise ValueError('Unsupported inference input.')
    if count and os.getenv('LOCAL_AI_VISION', 'false').lower() != 'true':
        raise ValueError('Set LOCAL_AI_VISION=true only for an installed vision model. Images cannot be dropped.')
    body = {'model': model, 'messages': [{'role':'user', 'content':parts}],
            'temperature':0, 'max_tokens':8192, 'stream':False, 'response_format':{'type':'json_object'}}
    request = urllib.request.Request(endpoint+'/chat/completions', data=json.dumps(body).encode(),
                                     headers={'Content-Type':'application/json'}, method='POST')
    started = perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.load(response)
        choice = payload['choices'][0]
        if choice.get('finish_reason') not in {'stop', 'end_turn'}:
            raise ValueError('Incomplete response')
        text = choice['message']['content']
        if not isinstance(text,str) or not text.strip() or payload.get('model',model) != model:
            raise ValueError('Invalid response')
    except Exception:
        raise OpenRouterError('Local model failed or returned an incomplete response; no fallback was attempted.') from None
    usage = payload.get('usage') if isinstance(payload.get('usage'),dict) else {}
    return FreeCompletion(text, {'provider':'local', 'model':model, 'image_count':count,
        'latency_ms':round((perf_counter()-started)*1000), 'reported_cost_usd':None,
        'prompt_tokens':usage.get('prompt_tokens'), 'completion_tokens':usage.get('completion_tokens')})


def complete(contents, task='grading', json_mode=True, *, response_schema: dict | None = None):
    from services.grading_control import check_grading_active
    check_grading_active()
    result = _complete(contents, task, json_mode, response_schema)
    check_grading_active()
    return result


def _complete(contents, task, json_mode, response_schema):
    config = configuration(task)
    if config['provider'] == 'openrouter_free':
        return complete_free(contents, model=config['model'])
    if config['provider'] == 'local':
        from services.inference_profiles import FULL_LOCAL_PROFILE, VISION_MODEL, active_profile
        profile = active_profile()
        if profile:
            if profile['id'] == FULL_LOCAL_PROFILE and task in {'grading', 'verification'} and not isinstance(contents, str):
                contents = list(contents)
                if any(isinstance(item, Image.Image) for item in contents):
                    config = profile['tasks']['vision_grading']
            vision = config['model'] == VISION_MODEL
            return _ollama_completion(contents, config['model'], vision=vision,
                response_schema=response_schema if vision else None, json_mode=json_mode if task=='ocr' else True)
        return _local_completion(contents, config['model'])
    if config['provider'] == 'gemini':
        return FreeCompletion(gemini_generate(contents, model=config['model'], json_mode=json_mode), config)
    raise ValueError(f'Unsupported {task} provider. Select gemini, openrouter_free or local.')


def generate_ocr(contents, json_mode=False, **kwargs):
    return complete(contents, task='ocr', json_mode=json_mode).text


def generate_setup(contents, json_mode=False, **kwargs):
    from services.inference_profiles import active_profile
    profile = active_profile()
    items = [contents] if isinstance(contents, str) else list(contents)
    if profile and profile['setup_images_use_ocr'] and any(isinstance(item, Image.Image) for item in items):
        # Reading setup page images uses the selected page-reading model.
        return complete(items, task='ocr', json_mode=json_mode).text
    return complete(items, task='setup', json_mode=json_mode).text
