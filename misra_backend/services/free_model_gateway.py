"""Pinned free research calls and bounded routing for server-configured inference."""
import base64
from dataclasses import dataclass
from io import BytesIO
import json
import logging
import math
import os
import re
from time import perf_counter, sleep
import urllib.error
import urllib.request

from PIL import Image
from services.openrouter_client import OpenRouterError

CATALOG_URL = "https://openrouter.ai/api/v1/models"
COMPLETION_URL = "https://openrouter.ai/api/v1/chat/completions"
_TRANSIENT_CODES = frozenset({500, 502, 503, 504})
_MODEL_UNAVAILABLE_CODES = _TRANSIENT_CODES | {404, 408, 429}
_RETRY_DELAYS = (2, 4)
DEFAULT_FREE_MODEL = 'nvidia/nemotron-3.5-super-vl:free'
_FREE_FALLBACKS = (DEFAULT_FREE_MODEL, 'google/gemma-4-26b-a4b-it:free', 'google/gemma-4-31b-it:free')
_FREE_MODEL_ID = re.compile(r'[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*:free')
_PAID_FALLBACKS = ('google/gemma-4-26b-a4b-it', 'deepseek/deepseek-v4.1-flash')
# OpenRouter expects token prices in USD per million, and image/request prices per item.
_FREE_CAPS = {'prompt': 0, 'completion': 0, 'image': 0, 'request': 0}
_PAID_CAPS = {**_FREE_CAPS, 'prompt': .20, 'completion': .70}
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FreeCompletion:
    text: str
    metadata: dict


class RoutedInferenceError(OpenRouterError):
    """The server's model attempts are exhausted or routing cannot proceed."""


class _ModelUnavailable(OpenRouterError):
    """A different compatible model may be able to serve the same request."""

    def __init__(self, message, *, status=None, free_quota=False):
        super().__init__(message)
        self.status = status
        self.free_quota = free_quota


def _free_quota_reached(detail):
    if not isinstance(detail, dict):
        return False
    metadata = detail.get('metadata')
    source = str(metadata.get('limit_source', '')) if isinstance(metadata, dict) else ''
    message = str(detail.get('message', '')).lower()
    return source.startswith('openrouter_free_tier_') or message.startswith('rate limit exceeded: free-models-per-')


def _http_free_quota_reached(error):
    try:
        payload = json.loads(error.read(4096))
        return isinstance(payload, dict) and _free_quota_reached(payload.get('error'))
    except (ValueError, OSError, AttributeError):
        return False


def paid_fallback_enabled():
    return os.getenv('OPENROUTER_ALLOW_PAID_FALLBACK', 'false').lower() == 'true'


def _wait_for_transient_retry(code, attempt):
    # Retry this request only. Auth, credits, quotas, invalid output and other
    # failures still stop here; the durable job owns recovery after exhaustion.
    if code not in _TRANSIENT_CODES or attempt >= len(_RETRY_DELAYS):
        return False
    delay = _RETRY_DELAYS[attempt]
    logger.warning("Free provider temporary error %s; retrying the same request in %s seconds (attempt %s of %s).",
                   code, delay, attempt + 2, len(_RETRY_DELAYS) + 1)
    sleep(delay)
    return True


def _read_json(request, timeout, *, routed=False):
    for attempt in range(len(_RETRY_DELAYS) + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as error:
            code = error.code
            free_quota = routed and code == 429 and _http_free_quota_reached(error)
            error.close()
            if routed and code in _MODEL_UNAVAILABLE_CODES:
                raise _ModelUnavailable(f'OpenRouter returned HTTP {code}.', status=code, free_quota=free_quota) from None
            if not routed and _wait_for_transient_retry(code, attempt):
                continue
            if routed:
                raise RoutedInferenceError(f'OpenRouter returned HTTP {code}.') from None
            raise OpenRouterError(f"Free provider returned HTTP {code}; no paid fallback was attempted.") from None
        except (urllib.error.URLError, TimeoutError):
            if routed:
                raise _ModelUnavailable('OpenRouter could not complete the connection.') from None
            raise OpenRouterError("Free provider connection unavailable; no grade was saved.") from None
        except (ValueError, UnicodeDecodeError):
            if routed:
                raise _ModelUnavailable('OpenRouter returned invalid response JSON.') from None
            raise OpenRouterError("Free provider returned invalid response JSON.") from None
        if not isinstance(payload, dict):
            if routed:
                raise _ModelUnavailable('OpenRouter returned an invalid response shape.')
            raise OpenRouterError("Free provider returned an invalid response shape.")
        if payload.get("error"):
            error = payload['error']
            code = error.get('code') if isinstance(error, dict) else None
            safe_code = code if type(code) is int else "unknown"
            if routed and safe_code in _MODEL_UNAVAILABLE_CODES:
                raise _ModelUnavailable(f'OpenRouter returned error {safe_code}.', status=safe_code,
                                        free_quota=safe_code == 429 and _free_quota_reached(error)) from None
            if not routed and _wait_for_transient_retry(safe_code, attempt):
                continue
            if routed:
                raise RoutedInferenceError(f'OpenRouter returned error {safe_code}.') from None
            raise OpenRouterError(f"Free provider returned error {safe_code}; no grade was saved.")
        return payload


def _prepare_contents(contents):
    parts, image_count, image_bytes = [], 0, 0
    for item in [contents] if isinstance(contents, str) else contents:
        if isinstance(item, str):
            parts.append({"type":"text", "text":item})
        elif isinstance(item, Image.Image):
            image_count += 1
            if image_count > 30:
                raise ValueError("Too many reference/student images for one free-model request. Narrow the approved reference scope.")
            buffer = BytesIO()
            item.convert("RGB").save(buffer, format="PNG")
            if buffer.tell() > 16 * 1024 * 1024:
                raise ValueError("A page image exceeds the inference limit. Review image size without cropping away student work.")
            image_bytes += buffer.tell()
            if image_bytes > 32 * 1024 * 1024:
                raise ValueError("Combined images exceed the inference limit. Narrow the reference scope without excluding student work.")
            parts.append({"type":"image_url", "image_url":{"url":"data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")}})
        else:
            raise ValueError("Unsupported model input; no provider request was made.")
    return parts, image_count


def _catalog(timeout):
    entries = _read_json(CATALOG_URL, min(timeout, 20)).get('data')
    if not isinstance(entries, list):
        raise OpenRouterError("Free model catalog is unavailable.")
    return {m['id']: m for m in entries if isinstance(m, dict) and isinstance(m.get('id'), str)}


def _prices_fit(entry, caps):
    pricing = entry.get('pricing')
    if not isinstance(pricing, dict) or not {'prompt', 'completion'} <= pricing.keys():
        return False
    # Catalog token prices are per token. Any unrecognized nonzero fee is excluded.
    limits = {**caps, 'prompt': caps['prompt']/1_000_000, 'completion': caps['completion']/1_000_000,
              'input_cache_read': caps['prompt']/1_000_000, 'input_cache_write': caps['prompt']/1_000_000}
    try:
        return all(0 <= float(price) <= limits.get(field, 0) for field, price in pricing.items())
    except (TypeError, ValueError):
        return False


def _modalities(entry, name):
    architecture = entry.get('architecture')
    modalities = architecture.get(name) if isinstance(architecture, dict) else None
    return modalities if isinstance(modalities, list) else []


def _accepts_request(entry, image_count):
    inputs = _modalities(entry, 'input_modalities')
    return 'text' in inputs and (not image_count or 'image' in inputs)


def _send_completion(body, key, timeout, *, routed):
    request = urllib.request.Request(COMPLETION_URL, data=json.dumps(body).encode('utf-8'), method='POST',
        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json', 'X-Title': 'MISRA assessment'})
    return _read_json(request, timeout, routed=True) if routed else _read_json(request, timeout)


def _complete_model(parts, image_count, model, entry, key, timeout, *, routed=False, paid=False, response_schema=None):
    body = {"model":model, "messages":[{"role":"user", "content":parts}], "max_tokens":4000,
        "temperature":0, "reasoning":{"enabled":False},
        "provider":{"allow_fallbacks":False, "max_price":{"prompt":0, "completion":0}}}
    parameters = entry.get('supported_parameters') or []
    if 'response_format' in parameters:
        body["response_format"] = {"type":"json_object"}
    if routed:
        body['provider'] = {'allow_fallbacks': True, 'max_price': _PAID_CAPS if paid else _FREE_CAPS}
        if 'reasoning' not in parameters:
            body.pop('reasoning')
        if paid:
            body['provider']['sort'] = 'price'
        if response_schema and 'structured_outputs' in parameters:
            body['response_format'] = {'type': 'json_schema', 'json_schema': {'name': 'misra_response', 'schema': response_schema}}
    started = perf_counter()
    try:
        payload = _send_completion(body, key, timeout, routed=routed)
    except _ModelUnavailable as error:
        if not routed or error.status != 404 or 'response_format' not in body:
            raise
        # OpenRouter can prefer a different subset of endpoints for formatted requests.
        # Retry only the no-endpoint case, keeping the message, images and price limits.
        from services.grading_control import check_grading_active
        check_grading_active()
        body.pop('response_format')
        payload = _send_completion(body, key, timeout, routed=True)
    try:
        choice = payload["choices"][0]
        if choice.get('finish_reason') != 'stop' or choice['message'].get('tool_calls'):
            raise _ModelUnavailable('OpenRouter model returned an incomplete response.')
        content = choice["message"]["content"]
        if isinstance(content, list):
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        if not isinstance(content, str) or not content.strip():
            raise ValueError()
    except (AttributeError, KeyError, IndexError, TypeError, ValueError):
        raise _ModelUnavailable('OpenRouter model returned no usable completion.') from None
    content = content.strip()
    if content.startswith("```json\n") and content.endswith("\n```"):
        content = content[8:-4].strip()
    usage = payload.get("usage") or {}
    if not isinstance(usage,dict):
        raise OpenRouterError("Provider usage metadata was invalid.")
    returned_model = payload.get('model') if routed else payload.get('model') or model
    if not isinstance(returned_model,str) or returned_model not in {model,model.removesuffix(":free")}:
        raise OpenRouterError("Provider returned a different model. No grade was saved.")
    if usage.get("cost") is not None:
        try:
            cost = float(usage["cost"])
        except (TypeError, ValueError):
            raise OpenRouterError("Provider cost metadata was invalid.") from None
        if not math.isfinite(cost) or cost < 0 or (not paid and cost != 0):
            raise OpenRouterError("Provider reported nonzero cost for a free-only request. Stop and investigate.")
    return FreeCompletion(content, {"provider":"openrouter_paid" if paid else "openrouter_free", "requested_model":model,
        "model":returned_model, "prompt_tokens":usage.get("prompt_tokens"),
        "completion_tokens":usage.get("completion_tokens"), "reported_cost_usd":usage.get("cost"),
        "latency_ms":round((perf_counter() - started) * 1000), "image_count":image_count})


def complete_free(contents, *, model=None, api_key=None, timeout=60):
    model = model or os.getenv('OPENROUTER_GRADING_MODEL', DEFAULT_FREE_MODEL)
    if not model.endswith(':free') or model.startswith('openrouter/'):
        raise ValueError('Select one explicit :free model; automatic or paid model routing is prohibited.')
    key = api_key or os.getenv('OPENROUTER_API_KEY')
    if not key:
        raise ValueError('OPENROUTER_API_KEY is missing. No provider request was made.')
    parts, image_count = _prepare_contents(contents)
    entry = _catalog(timeout).get(model)
    if not entry or not _prices_fit(entry, _FREE_CAPS):
        raise OpenRouterError('Selected endpoint is not verified zero-priced. No inference request was made.')
    if image_count and 'image' not in _modalities(entry, 'input_modalities'):
        raise ValueError('The selected free model does not accept images. Select a free vision model; text-only fallback is prohibited.')
    return _complete_model(parts, image_count, model, entry, key, timeout)


def complete_routed(contents, *, model, response_schema=None, exclude_models=(), timeout=60):
    from services.grading_control import check_grading_active
    key = os.getenv('OPENROUTER_API_KEY')
    if not key:
        raise RoutedInferenceError('OPENROUTER_API_KEY is missing.')
    if not model.endswith(':free') or model.startswith('openrouter/'):
        raise RoutedInferenceError('Server configuration requires an explicit :free primary model.')
    try:
        parts, image_count = _prepare_contents(contents)
        entries = _catalog(timeout)
    except ValueError as error:
        raise RoutedInferenceError(str(error)) from None
    except OpenRouterError:
        raise RoutedInferenceError('OpenRouter catalog is unavailable. Retry when it is reachable.') from None

    preferred = dict.fromkeys((model, *_FREE_FALLBACKS))
    extra_free = sorted(name for name, entry in entries.items()
        if name not in preferred and name not in exclude_models and _FREE_MODEL_ID.fullmatch(name)
        and not name.startswith('openrouter/') and 'text' in _modalities(entry, 'output_modalities')
        and _accepts_request(entry, image_count) and _prices_fit(entry, _FREE_CAPS))[:2]
    paid_models = _PAID_FALLBACKS if paid_fallback_enabled() else ()
    candidates = (*preferred, *extra_free, *paid_models)
    attempted = []
    failures = []
    free_quota = False
    for candidate in candidates:
        paid = candidate in paid_models
        if candidate in exclude_models or (free_quota and not paid):
            continue
        entry = entries.get(candidate)
        if not entry or not _accepts_request(entry, image_count) or not _prices_fit(entry, _PAID_CAPS if paid else _FREE_CAPS):
            continue
        check_grading_active()
        attempted.append(candidate)
        try:
            result = _complete_model(parts, image_count, candidate, entry, key, timeout,
                                     routed=True, paid=paid, response_schema=response_schema)
        except _ModelUnavailable as error:
            free_quota |= error.free_quota and not paid
            failures.append(f'HTTP {error.status}' if error.status else 'no usable response')
            logger.info('OpenRouter model %s unavailable: %s', candidate, error)
            continue
        except OpenRouterError as error:
            raise RoutedInferenceError(str(error)) from None
        return FreeCompletion(result.text, {**result.metadata, 'configured_model': model, 'attempted_models': attempted})
    evidence = ' for image + text' if image_count else ''
    if free_quota and not paid_models:
        reason = 'The OpenRouter account reached its shared free-model limit. Paid fallback is disabled.'
    elif failures:
        reason = f'OpenRouter tried {len(attempted)} models ({", ".join(failures)}).'
        if free_quota:
            reason += ' The OpenRouter account reached its shared free-model limit.'
    else:
        reason = 'The catalog had no remaining compatible model within the configured price limits.'
    raise RoutedInferenceError(f'No eligible OpenRouter model completed this request{evidence}. {reason}')
