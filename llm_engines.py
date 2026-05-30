#!/usr/bin/env python3
"""Local text-generation adapters for long-running offline-friendly stages."""

from __future__ import annotations

import json
import os
from typing import Any
import urllib.error
import urllib.request

try:
    import requests as req_lib

    HAS_REQUESTS = True
except ImportError:
    req_lib = None  # type: ignore[assignment]
    HAS_REQUESTS = False


LOCAL_MODEL_PREFIXES = (
    "local:",
    "ollama:",
    "lmstudio:",
    "lm-studio:",
    "openai-compatible:",
)


def is_local_model(model: str) -> bool:
    model_text = str(model or "").strip().lower()
    return model_text.startswith(LOCAL_MODEL_PREFIXES)


def _parse_model_spec(model: str, cfg: dict[str, Any]) -> tuple[str, str]:
    model_text = str(model or "").strip()
    lowered = model_text.lower()
    if lowered.startswith("ollama:"):
        return "ollama", model_text.split(":", 1)[1].strip()
    if lowered.startswith(("lmstudio:", "lm-studio:", "openai-compatible:")):
        return "openai_compatible", model_text.split(":", 1)[1].strip()
    if lowered.startswith("local:"):
        provider = str(cfg.get("local_llm_provider") or "ollama").strip().lower()
        provider = provider.replace("-", "_")
        return provider, model_text.split(":", 1)[1].strip()
    raise ValueError(f"Model {model!r} is not a local model spec.")


def _bool_cfg(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _post_json(
    url: str,
    *,
    payload: dict[str, Any],
    timeout: int,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    if HAS_REQUESTS and req_lib is not None:
        response = req_lib.post(
            url,
            json=payload,
            headers=request_headers,
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()

    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            parsed = json.loads(body) if body else {}
            return parsed if isinstance(parsed, dict) else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Local LLM HTTP {exc.code} from {url}: {detail}") from exc


def generate_text(
    *,
    model: str,
    system: str,
    content: str,
    max_tokens: int,
    cfg: dict[str, Any],
    temperature: float | None = None,
) -> str:
    provider, model_name = _parse_model_spec(model, cfg)
    if not model_name:
        raise ValueError(f"Local model spec {model!r} is missing the model name.")
    if provider == "ollama":
        return generate_ollama(
            model=model_name,
            system=system,
            content=content,
            max_tokens=max_tokens,
            cfg=cfg,
            temperature=temperature,
        )
    if provider in {"openai_compatible", "openai-compatible", "lmstudio", "lm_studio"}:
        return generate_openai_compatible(
            model=model_name,
            system=system,
            content=content,
            max_tokens=max_tokens,
            cfg=cfg,
            temperature=temperature,
        )
    raise ValueError(
        f"Unsupported local_llm_provider {provider!r}; expected ollama or openai_compatible."
    )


def generate_ollama(
    *,
    model: str,
    system: str,
    content: str,
    max_tokens: int,
    cfg: dict[str, Any],
    temperature: float | None,
) -> str:
    base_url = str(
        cfg.get("local_llm_base_url")
        or os.environ.get("LOCAL_LLM_BASE_URL")
        or "http://127.0.0.1:11434"
    ).rstrip("/")
    timeout = int(cfg.get("local_llm_timeout_sec") or 3600)
    options: dict[str, Any] = {"num_predict": int(max_tokens)}
    if cfg.get("local_llm_num_ctx"):
        options["num_ctx"] = int(cfg["local_llm_num_ctx"])
    if temperature is not None:
        options["temperature"] = float(temperature)

    payload: dict[str, Any] = {
        "model": model,
        "stream": False,
        "think": _bool_cfg(cfg.get("local_llm_think"), default=False),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ],
        "options": options,
    }
    if cfg.get("local_llm_keep_alive"):
        payload["keep_alive"] = str(cfg["local_llm_keep_alive"])

    data = _post_json(f"{base_url}/api/chat", payload=payload, timeout=timeout)
    message = data.get("message") if isinstance(data, dict) else None
    if isinstance(message, dict):
        text = str(message.get("content") or "").strip()
        if text:
            return text
    raise RuntimeError(f"Ollama returned no message content for model {model!r}.")


def generate_openai_compatible(
    *,
    model: str,
    system: str,
    content: str,
    max_tokens: int,
    cfg: dict[str, Any],
    temperature: float | None,
) -> str:
    base_url = str(
        cfg.get("local_llm_base_url")
        or os.environ.get("LOCAL_LLM_BASE_URL")
        or "http://127.0.0.1:1234/v1"
    ).rstrip("/")
    if not base_url.endswith("/v1"):
        base_url = f"{base_url}/v1"
    timeout = int(cfg.get("local_llm_timeout_sec") or 3600)
    headers = {"Content-Type": "application/json"}
    api_key_env = str(cfg.get("local_llm_api_key_env") or "LOCAL_LLM_API_KEY")
    api_key = os.environ.get(api_key_env, "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": int(max_tokens),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ],
    }
    if temperature is not None:
        payload["temperature"] = float(temperature)
    data = _post_json(
        f"{base_url}/chat/completions",
        payload=payload,
        headers=headers,
        timeout=timeout,
    )
    choices = data.get("choices") if isinstance(data, dict) else None
    if choices and isinstance(choices, list):
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(message, dict):
            text = str(message.get("content") or "").strip()
            if text:
                return text
    raise RuntimeError(f"OpenAI-compatible endpoint returned no content for model {model!r}.")
