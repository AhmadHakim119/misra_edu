"""Explicit task providers. Local inference uses a loopback OpenAI-compatible server."""
import base64
import io
import json
import os
from time import perf_counter
from urllib.parse import urlparse
import urllib.request

from PIL import Image
from services.free_model_gateway import FreeCompletion, complete_free
from services.gemini_client import DEFAULT_MODEL, generate as gemini_generate
from services.openrouter_client import OpenRouterError

PROFILE_SUPPORT_VERSION = 2


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
    profile = active_profile() or local_profile()
    request = urllib.request.Request(profile['local_base_url'] + path,
        data=json.dumps(body).encode('utf-8') if body is not None else None,
        headers={'Content-Type': 'application/json'}, method='POST' if body is not None else 'GET')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    with opener.open(request, timeout=timeout) as response:
        data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise ValueError('Local response exceeds the allowed size.')
        return json.loads(data)


def _ollama_completion(contents, model):
    from services.inference_profiles import active_profile, LOCAL_PROFILE, TEXT_ONLY_IMAGE_ERROR
    profile = active_profile()
    items = [contents] if isinstance(contents, str) else list(contents)
    if any(not isinstance(item, str) for item in items):
        raise ValueError(TEXT_ONLY_IMAGE_ERROR)
    prompt = '\n'.join(items)
    # A conservative UTF-8 byte bound leaves output and message overhead room.
    # Reject oversized inputs rather than silently truncating the approved evidence.
    if len(prompt.encode('utf-8')) > profile['context_tokens'] - profile['max_output_tokens'] - 1024:
        raise ValueError('This grading package exceeds the local context budget. Use a configured model with sufficient context; the evidence was not truncated.')
    body = {'model': model, 'messages': [{'role': 'user', 'content': prompt}],
        'format': 'json', 'stream': False, 'think': False,
        'options': {'temperature': 0, 'seed': 42, 'num_ctx': profile['context_tokens'],
                    'num_predict': profile['max_output_tokens']}}
    started = perf_counter()
    try:
        payload = _ollama_json('/api/chat', body=body, timeout=180)
        message = payload.get('message', {})
        text = message.get('content')
        if (payload.get('model') != model or payload.get('done') is not True
                or payload.get('done_reason') != 'stop' or message.get('tool_calls')
                or not isinstance(text, str) or not text.strip()):
            raise ValueError('Incomplete or mismatched local response.')
    except Exception:
        raise OpenRouterError('Local Qwen could not complete the request. Check Ollama and retry; no hosted fallback was attempted.') from None
    return FreeCompletion(text, {'provider': 'local', 'model': model, 'inference_profile': LOCAL_PROFILE,
        'transport': 'ollama', 'image_count': 0, 'latency_ms': round((perf_counter()-started)*1000),
        'reported_cost_usd': None, 'prompt_tokens': payload.get('prompt_eval_count'),
        'completion_tokens': payload.get('eval_count'), 'context_tokens': profile['context_tokens']})


def verification_enabled():
    from services.inference_profiles import active_profile
    profile = active_profile()
    return bool(profile['verification_enabled']) if profile else os.getenv('VERIFICATION_ENABLED', 'true').lower() == 'true'


def _local_completion(contents, model, *, profile=None):
    endpoint = (profile['local_base_url'] + '/v1' if profile else
                os.getenv('LOCAL_AI_BASE_URL', 'http://127.0.0.1:11434/v1').rstrip('/'))
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
            buffer = io.BytesIO(); item.convert('RGB').save(buffer, format='PNG')
            total_bytes += buffer.tell()
            if count > 30 or buffer.tell() > 16*1024*1024 or total_bytes > 32*1024*1024:
                raise ValueError('Inference images exceed the configured evidence limits.')
            parts.append({'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode('ascii')}})
        else:
            raise ValueError('Unsupported inference input.')
    if count and not profile and os.getenv('LOCAL_AI_VISION', 'false').lower() != 'true':
        raise ValueError('Set LOCAL_AI_VISION=true only for an installed vision model. Images cannot be dropped.')
    body = {'model': model, 'messages': [{'role':'user', 'content':parts}],
            'temperature':0, 'max_tokens':8192, 'stream':False, 'response_format':{'type':'json_object'}}
    request = urllib.request.Request(endpoint+'/chat/completions', data=json.dumps(body).encode(),
                                     headers={'Content-Type':'application/json'}, method='POST')
    started = perf_counter()
    try:
        if profile:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
            with opener.open(request, timeout=120) as response:
                data = response.read(2 * 1024 * 1024 + 1)
            if len(data) > 2 * 1024 * 1024:
                raise ValueError('Local response exceeds the allowed size.')
            payload = json.loads(data)
        else:
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = json.load(response)
        choice = payload['choices'][0]
        if choice.get('finish_reason') not in {'stop', 'end_turn'}:
            raise ValueError('Incomplete response')
        text = choice['message']['content']
        if not isinstance(text,str) or not text.strip() or payload.get('model',model) != model:
            raise ValueError('Invalid response')
        if profile and (payload.get('model') != model or choice['message'].get('tool_calls')):
            raise ValueError('Local response used an unexpected model or tool call.')
    except Exception:
        raise OpenRouterError('Local model failed or returned an incomplete response; no fallback was attempted.') from None
    usage = payload.get('usage') if isinstance(payload.get('usage'),dict) else {}
    return FreeCompletion(text, {'provider':'local', 'model':model, 'image_count':count,
        'latency_ms':round((perf_counter()-started)*1000), 'reported_cost_usd':None,
        'prompt_tokens':usage.get('prompt_tokens'), 'completion_tokens':usage.get('completion_tokens'),
        **({'inference_profile': profile['id'], 'transport': 'ollama_openai'} if profile else {})})


def complete(contents, task='grading', json_mode=True):
    config = configuration(task)
    if config['provider'] == 'openrouter_free':
        return complete_free(contents, model=config['model'])
    if config['provider'] == 'local':
        from services.inference_profiles import VISION_PROFILE, active_profile
        profile = active_profile()
        if profile and profile['id'] == VISION_PROFILE and task in {'grading', 'verification'}:
            return _local_completion(contents, config['model'], profile=profile)
        if profile:
            return _ollama_completion(contents, config['model'])
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
        # Reading setup page images is explicitly part of the Gemini OCR role.
        return complete(items, task='ocr', json_mode=json_mode).text
    return complete(items, task='setup', json_mode=json_mode).text
