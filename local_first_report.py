#!/usr/bin/env python3
"""Print a local-first readiness report for the Asynchronous pipeline."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from secret_env import load_secret_env


DEFAULTS = {
    "research_model": "claude-opus-4-5",
    "dialogue_model": "claude-sonnet-4-6",
    "fact_check_model": "claude-sonnet-4-6",
    "learning_path_model": "claude-sonnet-4-6",
    "music_prompt_model": "claude-haiku-4-5-20251001",
    "tts_provider": "openai",
    "tts_routes": {},
    "use_music": True,
    "use_clips": False,
    "use_audio_mastering": True,
    "local_llm_base_url": "http://127.0.0.1:11434",
    "local_llm_think": False,
}


def _load_config(repo_root: Path) -> dict[str, Any]:
    cfg = dict(DEFAULTS)
    cfg_path = repo_root / "config.json"
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict):
                cfg.update(data)
        except json.JSONDecodeError:
            pass
    for key in list(cfg):
        env_val = os.environ.get(key.upper())
        if env_val is not None:
            if key == "tts_routes":
                try:
                    cfg[key] = json.loads(env_val) if env_val.strip() else {}
                except json.JSONDecodeError:
                    cfg[key] = {}
            else:
                cfg[key] = env_val
    return cfg


def _has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _is_local_model(model: Any) -> bool:
    text = str(model or "").lower()
    return text.startswith(("local:", "ollama:", "lmstudio:", "lm-studio:", "openai-compatible:"))


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"", "0", "false", "no", "off"}


def _local_service_status(base_url: str) -> str:
    base = str(base_url or "").rstrip("/")
    if not base:
        return "not configured"
    candidates = [f"{base}/api/tags"]
    if base.endswith("/v1"):
        candidates = [f"{base}/models"]
    for url in candidates:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if 200 <= response.status < 300:
                    return f"reachable ({url})"
        except (OSError, urllib.error.URLError, TimeoutError):
            continue
    return f"not reachable ({base})"


def _tts_routes(cfg: dict[str, Any]) -> dict[str, Any]:
    routes = cfg.get("tts_routes")
    if isinstance(routes, dict):
        return routes
    if isinstance(routes, str) and routes.strip():
        try:
            parsed = json.loads(routes)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _tts_locality(cfg: dict[str, Any]) -> tuple[str, str]:
    routes = _tts_routes(cfg)
    providers = {str(cfg.get("tts_provider") or "openai").lower()}
    for route in routes.values():
        if isinstance(route, dict) and route.get("provider"):
            providers.add(str(route["provider"]).lower())
    localish = {"command"}
    cloud = {"openai", "elevenlabs"}
    if providers <= localish:
        return "local", ", ".join(sorted(providers))
    if providers & localish and providers & cloud:
        return "mixed", ", ".join(sorted(providers))
    return "cloud", ", ".join(sorted(providers))


def main() -> int:
    repo_root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(".").resolve()
    load_secret_env(repo_root)
    cfg = _load_config(repo_root)
    tts_status, tts_detail = _tts_locality(cfg)
    model_rows = [
        ("Research", cfg.get("research_model"), "cloud tool-use required for current web search"),
        ("Dialogue/script", cfg.get("dialogue_model"), "safe local candidate"),
        ("Fact-check", cfg.get("fact_check_model"), "cloud recommended when web search is enabled"),
        ("Learning path", cfg.get("learning_path_model"), "safe local candidate after prompt tuning"),
        ("Music prompt", cfg.get("music_prompt_model"), "tiny call; local-capable but low savings"),
    ]
    local_model_count = sum(1 for _name, model, _note in model_rows if _is_local_model(model))

    print("# Local-First Readiness Report")
    print()
    print(f"Repo: `{repo_root}`")
    print()
    print("## Current Routing")
    print()
    print("| Stage | Route | Locality | Note |")
    print("|---|---:|---|---|")
    for name, model, note in model_rows:
        locality = "local" if _is_local_model(model) else "cloud"
        print(f"| {name} | `{model}` | {locality} | {note} |")
    print(f"| TTS | `{tts_detail}` | {tts_status} | per-speaker routes are supported |")
    print(
        f"| Music | `{cfg.get('music_model', 'facebook/musicgen-small')}` | "
        f"{'local' if _as_bool(cfg.get('use_music', True)) else 'off'} | MusicGen/numpy runs locally |"
    )
    print(
        f"| Audio mastering | ffmpeg | "
        f"{'local' if _as_bool(cfg.get('use_audio_mastering', True)) else 'off'} | local encode/loudness pipeline |"
    )
    print()
    print("## Machine Checks")
    print()
    print("| Capability | Status |")
    print("|---|---|")
    for binary in ("ffmpeg", "ffprobe", "git"):
        print(f"| `{binary}` | {'found' if shutil.which(binary) else 'missing'} |")
    for module in ("torch", "audiocraft", "numpy", "scipy", "requests", "anthropic", "openai"):
        print(f"| Python `{module}` | {'found' if _has_module(module) else 'missing'} |")
    print(f"| Local LLM service | {_local_service_status(str(cfg.get('local_llm_base_url')))} |")
    print(f"| OpenAI key | {'set' if os.environ.get('OPENAI_API_KEY') else 'missing'} |")
    print(f"| ElevenLabs key | {'set' if os.environ.get('ELEVENLABS_API_KEY') else 'missing'} |")
    print(f"| Anthropic key | {'set' if os.environ.get('ANTHROPIC_API_KEY') else 'missing'} |")
    print()
    print("## Practical Ceiling")
    print()
    if local_model_count:
        print("- Some text stages are already routed to local models.")
    else:
        print("- Text generation is currently cloud-routed.")
    if "not reachable" in _local_service_status(str(cfg.get("local_llm_base_url"))):
        print("- Ollama/local LLM service is not reachable yet. See `docs/OLLAMA_LOCAL_SERVICE.md`.")
    print("- With the current code, the safest cheap/high-quality split is local TTS, music, mastering, and optional local drafting passes while keeping research and web fact-checking on Claude.")
    print("- A fully local run is possible only for episodes that do not need live web search, but quality and factual freshness will drop unless you provide a local retrieval corpus.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
