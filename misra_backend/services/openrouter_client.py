"""Small OpenRouter client for isolated model comparisons.

This module does not select models, alter grades, or log request content.
Callers must use an explicit model slug and decide what data may be sent.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from time import perf_counter


API_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterError(RuntimeError):
    """A provider request failed without exposing its body or credentials."""


@dataclass(frozen=True)
class OpenRouterCompletion:
    text: str
    returned_model: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int


def complete_json(
    *,
    model: str,
    prompt: str,
    api_key: str | None = None,
    timeout_seconds: int = 90,
) -> OpenRouterCompletion:
    if not model.endswith(":free"):
        raise ValueError("Experiment models must use an explicit :free slug.")
    key = api_key or os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise ValueError("OPENROUTER_API_KEY is missing.")
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "reasoning": {"enabled": False},
        "temperature": 0,
        "max_tokens": 2200,
    }).encode("utf-8")
    request = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "X-Title": "MISRA-EDU synthetic model experiment",
        },
        method="POST",
    )
    started = perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        # Provider bodies can echo prompts or other private content.
        raise OpenRouterError(f"OpenRouter returned HTTP {error.code}.") from None
    except (urllib.error.URLError, TimeoutError) as error:
        raise OpenRouterError(f"OpenRouter connection failed: {type(error).__name__}.") from None
    except (ValueError, UnicodeDecodeError):
        raise OpenRouterError("OpenRouter returned invalid response JSON.") from None

    try:
        choice = payload["choices"][0]
        message = choice["message"]
        content = message["content"]
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        if not isinstance(content, str) or not content.strip():
            raise ValueError("empty completion")
    except (KeyError, IndexError, TypeError, ValueError):
        finish_reason = (payload.get("choices") or [{}])[0].get("finish_reason", "unknown")
        if finish_reason not in {"stop", "length", "content_filter", "unknown"}:
            finish_reason = "other"
        raise OpenRouterError(
            f"OpenRouter returned no usable text completion (finish_reason={finish_reason})."
        ) from None

    usage = payload.get("usage") or {}
    return OpenRouterCompletion(
        text=content,
        returned_model=payload.get("model"),
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
        latency_ms=round((perf_counter() - started) * 1000),
    )
