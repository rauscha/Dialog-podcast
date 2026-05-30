#!/usr/bin/env python3
"""Modular text-to-speech engines for Asynchronous.

The generator decides who is speaking and which route they should use. This
module only knows how to synthesize one text chunk through a named provider.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    from openai import OpenAI as OpenAIClient

    HAS_OPENAI = True
except ImportError:
    OpenAIClient = None  # type: ignore[assignment]
    HAS_OPENAI = False

try:
    import requests as req_lib

    HAS_REQUESTS = True
except ImportError:
    req_lib = None  # type: ignore[assignment]
    HAS_REQUESTS = False

SUPPORTED_TTS_PROVIDERS = {"openai", "elevenlabs", "command"}


def clean_for_tts(text: str) -> str:
    text = re.sub(r"^#+\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", text)
    text = re.sub(r"`[^`]+`", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^\s*[-*]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text(text: str, max_chars: int = 4000) -> list[str]:
    """Split text at sentence boundaries; hard-split sentences exceeding max_chars."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    current = ""

    for sentence in sentences:
        if len(sentence) > max_chars:
            if current.strip():
                chunks.append(current.strip())
                current = ""
            words = sentence.split()
            part = ""
            for word in words:
                if len(part) + len(word) + 1 > max_chars:
                    if part.strip():
                        chunks.append(part.strip())
                    part = word
                else:
                    part = (part + " " + word).strip() if part else word
            if part.strip():
                chunks.append(part.strip())
        elif len(current) + len(sentence) + 1 > max_chars:
            if current.strip():
                chunks.append(current.strip())
            current = sentence
        else:
            current = (current + " " + sentence).strip() if current else sentence

    if current.strip():
        chunks.append(current.strip())
    return chunks or [text]


def audio_bitrate_value(cfg: dict[str, Any]) -> str:
    bitrate = str(cfg.get("audio_bitrate") or "192k").strip().lower()
    if not re.fullmatch(r"\d+[km]?", bitrate):
        raise ValueError("audio_bitrate must look like 192k, 256k, or 2m")
    return bitrate


def ffmpeg_concat_configured(parts: list[Path], output: Path, cfg: dict[str, Any]) -> None:
    existing = [Path(part) for part in parts if Path(part).exists()]
    if not existing:
        raise ValueError("No audio segments to concatenate")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as list_file:
        list_file.write("\n".join(f"file '{part.resolve()}'" for part in existing))
        list_path = Path(list_file.name)

    try:
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-ar",
            str(int(cfg.get("audio_sample_rate", 44100))),
            "-ac",
            str(int(cfg.get("audio_channels", 2))),
            "-c:a",
            "libmp3lame",
            "-b:a",
            audio_bitrate_value(cfg),
            str(output),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg concat failed: {result.stderr[:500]}")
    finally:
        list_path.unlink(missing_ok=True)


def synthesize_tts(
    *,
    text: str,
    output_path: Path,
    route: dict[str, Any],
    cfg: dict[str, Any],
    instructions: str = "",
) -> Path:
    provider = str(route.get("provider") or cfg.get("tts_provider") or "openai").lower()
    if provider == "openai":
        return synthesize_openai(
            text=text,
            output_path=output_path,
            route=route,
            cfg=cfg,
            instructions=instructions,
        )
    if provider == "elevenlabs":
        return synthesize_elevenlabs(
            text=text,
            output_path=output_path,
            route=route,
            cfg=cfg,
        )
    if provider == "command":
        return synthesize_command(
            text=text,
            output_path=output_path,
            route=route,
            cfg=cfg,
            instructions=instructions,
        )
    raise ValueError(
        f"Unsupported TTS provider {provider!r}; expected one of {sorted(SUPPORTED_TTS_PROVIDERS)}"
    )


def synthesize_openai(
    *,
    text: str,
    output_path: Path,
    route: dict[str, Any],
    cfg: dict[str, Any],
    instructions: str = "",
) -> Path:
    if not HAS_OPENAI or OpenAIClient is None:
        raise ImportError("openai package not installed.")
    api_key_env = str(route.get("api_key_env") or "OPENAI_API_KEY")
    api_key = os.environ.get(api_key_env, "")
    if not api_key:
        raise ValueError(f"{api_key_env} is not set.")

    client = OpenAIClient(api_key=api_key)
    output_path = output_path.with_suffix(".mp3")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    model = str(route.get("model") or cfg.get("tts_model") or "gpt-4o-mini-tts")
    voice = str(route.get("voice") or route.get("voice_id") or "").strip()
    if not voice:
        raise ValueError("OpenAI TTS route is missing a voice.")
    use_instructions = (
        bool(cfg.get("use_emotive_tts", True))
        and bool(instructions)
        and bool(route.get("supports_instructions", model == "gpt-4o-mini-tts"))
    )

    chunks = chunk_text(clean_for_tts(text), max_chars=int(route.get("max_chars", 4000)))
    chunk_paths: list[Path] = []
    for idx, chunk in enumerate(chunks):
        if not chunk.strip():
            continue
        kwargs: dict[str, Any] = {"model": model, "voice": voice, "input": chunk}
        if use_instructions:
            kwargs["instructions"] = instructions
        try:
            response = client.audio.speech.create(**kwargs)
        except Exception as exc:
            if use_instructions and "instructions" in str(exc).lower():
                logger.warning("OpenAI TTS instructions rejected; retrying without them")
                kwargs.pop("instructions", None)
                response = client.audio.speech.create(**kwargs)
            else:
                raise
        chunk_path = output_path.with_stem(f"{output_path.stem}_openai_{idx}")
        response.stream_to_file(str(chunk_path))
        chunk_paths.append(chunk_path)

    if not chunk_paths:
        raise RuntimeError(f"No OpenAI audio generated for text starting: {text[:60]!r}")
    if len(chunk_paths) == 1:
        chunk_paths[0].replace(output_path)
    else:
        ffmpeg_concat_configured(chunk_paths, output_path, cfg)
        for path in chunk_paths:
            path.unlink(missing_ok=True)
    return output_path


def synthesize_elevenlabs(
    *,
    text: str,
    output_path: Path,
    route: dict[str, Any],
    cfg: dict[str, Any],
) -> Path:
    if not HAS_REQUESTS or req_lib is None:
        raise ImportError("requests package not installed.")
    api_key_env = str(route.get("api_key_env") or "ELEVENLABS_API_KEY")
    api_key = os.environ.get(api_key_env, "")
    if not api_key:
        raise ValueError(f"{api_key_env} is not set.")
    voice_id = str(route.get("voice_id") or route.get("voice") or "").strip()
    if not voice_id:
        raise ValueError("ElevenLabs TTS route is missing voice_id.")

    output_path = output_path.with_suffix(".mp3")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    chunks = chunk_text(clean_for_tts(text), max_chars=int(route.get("max_chars", 4500)))
    model_id = str(route.get("model") or cfg.get("elevenlabs_model") or "eleven_turbo_v2")
    voice_settings = route.get("voice_settings")
    if not isinstance(voice_settings, dict):
        voice_settings = {
            "stability": float(route.get("stability", cfg.get("elevenlabs_stability", 0.5))),
            "similarity_boost": float(
                route.get(
                    "similarity_boost",
                    cfg.get("elevenlabs_similarity_boost", 0.75),
                )
            ),
        }
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {"xi-api-key": api_key, "Content-Type": "application/json"}
    chunk_paths: list[Path] = []

    for idx, chunk in enumerate(chunks):
        if not chunk.strip():
            continue
        payload = {
            "text": chunk,
            "model_id": model_id,
            "voice_settings": voice_settings,
        }
        response = req_lib.post(
            url,
            json=payload,
            headers=headers,
            timeout=int(route.get("timeout_sec", cfg.get("tts_request_timeout_sec", 180))),
        )
        response.raise_for_status()
        chunk_path = output_path.with_stem(f"{output_path.stem}_elevenlabs_{idx}")
        chunk_path.write_bytes(response.content)
        chunk_paths.append(chunk_path)

    if not chunk_paths:
        raise RuntimeError("No ElevenLabs audio generated")
    if len(chunk_paths) == 1:
        chunk_paths[0].replace(output_path)
    else:
        ffmpeg_concat_configured(chunk_paths, output_path, cfg)
        for path in chunk_paths:
            path.unlink(missing_ok=True)
    return output_path


def synthesize_command(
    *,
    text: str,
    output_path: Path,
    route: dict[str, Any],
    cfg: dict[str, Any],
    instructions: str = "",
) -> Path:
    command = route.get("command") or cfg.get("tts_command")
    if isinstance(command, str):
        command_parts = shlex.split(command, posix=os.name != "nt")
    elif isinstance(command, list):
        command_parts = [str(part) for part in command]
    else:
        raise ValueError("Command TTS route must provide a command string or list.")
    if not command_parts:
        raise ValueError("Command TTS route command is empty.")

    output_path = output_path.with_suffix(str(route.get("extension") or ".mp3"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    text_path = output_path.with_suffix(".txt")
    text_path.write_text(clean_for_tts(text), encoding="utf-8")
    metadata = {
        "voice": route.get("voice") or route.get("voice_id") or "",
        "model": route.get("model") or "",
        "instructions": instructions,
        "provider": "command",
    }
    metadata_path = output_path.with_suffix(".tts.json")
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    replacements = {
        "text_path": str(text_path),
        "output_path": str(output_path),
        "voice": str(metadata["voice"]),
        "model": str(metadata["model"]),
        "metadata_path": str(metadata_path),
    }
    cmd = [part.format(**replacements) for part in command_parts]
    cwd = route.get("cwd") or cfg.get("tts_command_cwd") or None
    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=int(route.get("timeout_sec", cfg.get("tts_command_timeout_sec", 600))),
    )
    if result.returncode != 0:
        raise RuntimeError(f"Command TTS failed: {result.stderr[:800]}")
    if not output_path.exists():
        raise RuntimeError(f"Command TTS did not create output file: {output_path}")
    text_path.unlink(missing_ok=True)
    metadata_path.unlink(missing_ok=True)
    return output_path
