#!/usr/bin/env python3
"""Load local secret environment files without exposing values."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable


_KNOWN_ENV_KEYS = {
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "ELEVENLABS_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_ALLOWED_USERS",
    "TELEGRAM_ALLOWED_CHATS",
    "PODCAST_REPO_PATH",
    "GITHUB_TOKEN",
    "GH_TOKEN",
}


def _label_to_key(label: str) -> str | None:
    normalized = re.sub(r"[^A-Z0-9]+", "_", label.upper()).strip("_")
    if normalized in _KNOWN_ENV_KEYS:
        return normalized
    compact = normalized.replace("_", "")
    if "ANTHROPIC" in compact or "CLAUDE" in compact:
        return "ANTHROPIC_API_KEY"
    if "OPENAI" in compact:
        return "OPENAI_API_KEY"
    if "ELEVEN" in compact or "11LAB" in compact:
        return "ELEVENLABS_API_KEY"
    if "TELEGRAM" in compact or ("BOT" in compact and "TOKEN" in compact):
        return "TELEGRAM_BOT_TOKEN"
    return None


def _guess_key_from_value(value: str) -> str | None:
    stripped = value.strip()
    if stripped.startswith("sk-ant-"):
        return "ANTHROPIC_API_KEY"
    if stripped.startswith("sk-"):
        return "OPENAI_API_KEY"
    if re.fullmatch(r"\d+:[A-Za-z0-9_-]{20,}", stripped):
        return "TELEGRAM_BOT_TOKEN"
    return None


def _set_env(key: str, value: str, *, override: bool) -> None:
    if not key or not value:
        return
    if override or not os.environ.get(key):
        os.environ[key] = value


def load_secret_env(
    repo_root: Path | str = Path("."),
    *,
    filenames: Iterable[str] = (".env", "APIS.txt"),
    override: bool = False,
) -> None:
    root = Path(repo_root)
    for filename in filenames:
        path = root / filename
        if not path.exists():
            continue
        pending_key: str | None = None
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except OSError:
            continue
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            if "=" in line:
                key_text, value = line.split("=", 1)
                key = _label_to_key(key_text.strip())
                if key:
                    _set_env(key, value.strip().strip('"').strip("'"), override=override)
                    pending_key = None
                    continue

            guessed = _guess_key_from_value(line)
            if guessed:
                _set_env(guessed, line, override=override)
                pending_key = None
                continue

            if pending_key:
                _set_env(pending_key, line.strip('"').strip("'"), override=override)
                pending_key = None
                continue

            pending_key = _label_to_key(line)
