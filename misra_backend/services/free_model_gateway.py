"""Explicit free-only inference. No paid routing, plugins, or model fallbacks."""
import base64
from dataclasses import dataclass
from io import BytesIO
import json
import math
import os
from time import perf_counter
import urllib.error
import urllib.request

from PIL import Image
from services.openrouter_client import OpenRouterError

CATALOG_URL = "https://openrouter.ai/api/v1/models"
COMPLETION_URL = "https://openrouter.ai/api/v1/chat/completions"


@dataclass(frozen=True)
class FreeCompletion:
    text: str
    metadata: dict


def _read_json(request, timeout):
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        raise OpenRouterError(f"Free provider returned HTTP {error.code}; no paid fallback was attempted.") from None
    except (urllib.error.URLError, TimeoutError):
        raise OpenRouterError("Free provider connection unavailable; no grade was saved.") from None
    except (ValueError, UnicodeDecodeError):
        raise OpenRouterError("Free provider returned invalid response JSON.") from None
    if not isinstance(payload, dict):
        raise OpenRouterError("Free provider returned an invalid response shape.")
    if payload.get("error"):
        code = payload["error"].get("code") if isinstance(payload["error"], dict) else None
        safe_code = code if type(code) is int else "unknown"
        raise OpenRouterError(f"Free provider returned error {safe_code}; no grade was saved.")
    return payload


def complete_free(contents, *, model=None, api_key=None, timeout=60):
    model = model or os.getenv("OPENROUTER_GRADING_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")
    if not model.endswith(":free") or model.startswith("openrouter/"):
        raise ValueError("Select one explicit :free model; automatic or paid model routing is prohibited.")
    key = api_key or os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise ValueError("OPENROUTER_API_KEY is missing. No provider request was made.")
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
    catalog = _read_json(CATALOG_URL, min(timeout, 20))
    entries = catalog.get("data")
    if not isinstance(entries, list):
        raise OpenRouterError("Free model catalog is unavailable.")
    entry = next((m for m in entries if isinstance(m, dict) and m.get("id") == model), None)
    if not entry:
        raise OpenRouterError("Selected free model is not in the current catalog. Choose another explicit free model.")
    pricing = entry.get("pricing") or {}
    if not isinstance(pricing, dict):
        raise OpenRouterError("Free model pricing could not be verified.")
    for name in ("prompt", "completion"):
        if name not in pricing:
            raise OpenRouterError("Free model pricing could not be verified.")
    try:
        costs = [float(value) for value in pricing.values()]
    except (TypeError, ValueError):
        raise OpenRouterError("Free model pricing could not be verified.") from None
    if any(not math.isfinite(cost) or cost != 0 for cost in costs):
        raise OpenRouterError("Selected endpoint is not verified zero-priced. No inference request was made.")
    if image_count and "image" not in (entry.get("architecture") or {}).get("input_modalities", []):
        raise ValueError("The selected free model does not accept images. Select a free vision model; text-only fallback is prohibited.")
    body = {"model":model, "messages":[{"role":"user", "content":parts}], "max_tokens":4000,
        "temperature":0, "reasoning":{"enabled":False},
        "provider":{"allow_fallbacks":False, "max_price":{"prompt":0, "completion":0}}}
    if "response_format" in entry.get("supported_parameters", []):
        body["response_format"] = {"type":"json_object"}
    request = urllib.request.Request(COMPLETION_URL, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Authorization":f"Bearer {key}", "Content-Type":"application/json", "X-Title":"MISRA free-only assessment"})
    started = perf_counter()
    payload = _read_json(request, timeout)
    try:
        choice = payload["choices"][0]
        if choice.get("finish_reason") == "length":
            raise OpenRouterError("Free model response was truncated; no grade was saved.")
        content = choice["message"]["content"]
        if isinstance(content, list):
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        if not isinstance(content, str) or not content.strip():
            raise ValueError()
    except (KeyError, IndexError, TypeError, ValueError):
        raise OpenRouterError("Free model returned no usable completion; no grade was saved.") from None
    content = content.strip()
    if content.startswith("```json\n") and content.endswith("\n```"):
        content = content[8:-4].strip()
    usage = payload.get("usage") or {}
    if not isinstance(usage,dict):
        raise OpenRouterError("Provider usage metadata was invalid.")
    returned_model = payload.get("model") or model
    if not isinstance(returned_model,str) or returned_model not in {model,model.removesuffix(":free")}:
        raise OpenRouterError("Provider returned a different model. No grade was saved.")
    if usage.get("cost") is not None:
        try:
            cost = float(usage["cost"])
        except (TypeError, ValueError):
            raise OpenRouterError("Provider cost metadata was invalid.") from None
        if not math.isfinite(cost) or cost != 0:
            raise OpenRouterError("Provider reported nonzero cost for a free-only request. Stop and investigate.")
    return FreeCompletion(content, {"provider":"openrouter_free", "requested_model":model,
        "model":returned_model, "prompt_tokens":usage.get("prompt_tokens"),
        "completion_tokens":usage.get("completion_tokens"), "reported_cost_usd":usage.get("cost"),
        "latency_ms":round((perf_counter() - started) * 1000), "image_count":image_count})
