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


def configuration(task):
    inherited = os.getenv('GRADING_PROVIDER', os.getenv('MISRA_AI_PROVIDER', 'gemini')) if task == 'verification' else os.getenv('MISRA_AI_PROVIDER', 'gemini')
    provider = os.getenv(f'{task.upper()}_PROVIDER', inherited)
    model = os.getenv(f'{task.upper()}_MODEL')
    if not model:
        model = (os.getenv('LOCAL_AI_MODEL', '') if provider == 'local' else
                 os.getenv('OPENROUTER_GRADING_MODEL', 'nvidia/nemotron-3-super-120b-a12b:free')
                 if provider == 'openrouter_free' else DEFAULT_MODEL)
    return {'provider': provider, 'model': model}


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
            buffer = io.BytesIO(); item.convert('RGB').save(buffer, format='PNG')
            total_bytes += buffer.tell()
            if count > 30 or buffer.tell() > 16*1024*1024 or total_bytes > 32*1024*1024:
                raise ValueError('Inference images exceed the configured evidence limits.')
            parts.append({'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode('ascii')}})
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


def complete(contents, task='grading', json_mode=True):
    config = configuration(task)
    if config['provider'] == 'openrouter_free':
        return complete_free(contents, model=config['model'])
    if config['provider'] == 'local':
        return _local_completion(contents, config['model'])
    if config['provider'] == 'gemini':
        return FreeCompletion(gemini_generate(contents, model=config['model'], json_mode=json_mode), config)
    raise ValueError(f'Unsupported {task} provider. Select gemini, openrouter_free or local.')


def generate_ocr(contents, json_mode=False, **kwargs):
    return complete(contents, task='ocr', json_mode=json_mode).text


def generate_setup(contents, json_mode=False, **kwargs):
    return complete(contents, task='setup', json_mode=json_mode).text
