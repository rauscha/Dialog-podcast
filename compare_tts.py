#!/usr/bin/env python3
"""TTS comparison driver — OpenAI vs ElevenLabs vs Cartesia.

Renders the SAME short Juno/Caspar script through each provider so you can
A/B/C the voice quality back-to-back. No research, no script generation, no
music, no git push. Just the MP3s side-by-side.

Outputs to `episodes/tts_comparison/{openai,elevenlabs,cartesia}.mp3`.

Voice IDs are read from config.json — set `elevenlabs_voice_id_a/_b` and
`cartesia_voice_id_a/_b` before running, or override by env (handy for trying
candidate voices without editing config):
    JUNO_OPENAI_VOICE, CASPAR_OPENAI_VOICE
    JUNO_ELEVENLABS_VOICE, CASPAR_ELEVENLABS_VOICE
    JUNO_CARTESIA_VOICE, CASPAR_CARTESIA_VOICE

A provider is skipped (with a clear message) if its key or voices are missing,
so you can iterate one provider at a time.

Usage:
    python compare_tts.py                       # all available
    python compare_tts.py cartesia              # just one
    python compare_tts.py elevenlabs cartesia   # subset
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _load_dotenv(path: Path = Path(".env")) -> None:
    """Minimal .env loader so the script is runnable without sourcing first.

    Does NOT overwrite already-set env vars (existing process env wins).
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()

import tts_engines  # noqa: E402 — env must be loaded first

# ---------------------------------------------------------------------------
# The canned script — short, varied, hits emotion + a name + a number.
# Each tuple: (speaker_label, emotion_tag, text).
# ---------------------------------------------------------------------------
SCRIPT: list[tuple[str, str, str]] = [
    (
        "JUNO",
        "warm, curious",
        "So I want to start with a number that genuinely stopped me cold. "
        "In 1977, the Voyager Golden Record was launched with 116 images, "
        "55 greetings, and one song by Chuck Berry.",
    ),
    (
        "CASPAR",
        "amused, dry",
        "And that's the part everyone remembers — Johnny B. Goode flying out "
        "of the solar system at seventeen kilometers per second. But the "
        "selection committee almost cut it. Carl Sagan had to fight for it.",
    ),
    (
        "JUNO",
        "delighted",
        "Wait, why? Was it the lyrics?",
    ),
    (
        "CASPAR",
        "thoughtful",
        "Partly. Some members thought rock and roll was, quote, 'adolescent.' "
        "Sagan's response was that adolescence is one of the more interesting "
        "things humans do, and we shouldn't hide it from anyone listening.",
    ),
    (
        "JUNO",
        "quiet, reflective",
        "There's something kind of beautiful about that. The first thing an "
        "alien civilization might hear from us — we picked the music we were "
        "slightly embarrassed by.",
    ),
    (
        "CASPAR",
        "agreeing",
        "Right. And it's still going. Voyager 1 crossed into interstellar "
        "space in 2012. That record is the longest-running radio broadcast "
        "in human history, and nobody's listening.",
    ),
]


def _load_cfg() -> dict:
    cfg_path = Path("config.json")
    if not cfg_path.exists():
        return {}
    return json.loads(cfg_path.read_text(encoding="utf-8"))


def _build_route(provider: str, label: str, cfg: dict) -> dict | None:
    """Return a TTS route dict for the given provider/label, or None if missing."""
    if provider == "openai":
        voice = (
            os.environ.get(f"{label}_OPENAI_VOICE")
            or (cfg.get("host_a_voice") if label == "JUNO" else cfg.get("host_b_voice"))
            or ("marin" if label == "JUNO" else "cedar")
        )
        return {
            "provider": "openai",
            "voice": voice,
            "model": cfg.get("tts_model") or "gpt-4o-mini-tts",
            "supports_instructions": True,
        }
    if provider == "elevenlabs":
        voice_id = os.environ.get(f"{label}_ELEVENLABS_VOICE") or (
            cfg.get("elevenlabs_voice_id_a") if label == "JUNO"
            else cfg.get("elevenlabs_voice_id_b")
        )
        if not voice_id:
            return None
        return {
            "provider": "elevenlabs",
            "voice_id": voice_id,
            "model": cfg.get("elevenlabs_model") or "eleven_turbo_v2",
            "stability": float(cfg.get("elevenlabs_stability", 0.5)),
            "similarity_boost": float(cfg.get("elevenlabs_similarity_boost", 0.75)),
        }
    if provider == "cartesia":
        voice_id = os.environ.get(f"{label}_CARTESIA_VOICE") or (
            cfg.get("cartesia_voice_id_a") if label == "JUNO"
            else cfg.get("cartesia_voice_id_b")
        )
        if not voice_id:
            return None
        return {
            "provider": "cartesia",
            "voice_id": voice_id,
            "model": cfg.get("cartesia_model") or "sonic-3.5",
            "version": cfg.get("cartesia_version") or "2026-03-01",
            "sample_rate": int(cfg.get("cartesia_sample_rate", 44100)),
            "bit_rate": int(cfg.get("cartesia_bit_rate", 192000)),
            "language": cfg.get("cartesia_language") or "en",
            "speed": float(cfg.get("cartesia_speed", 1.0)),
        }
    raise ValueError(f"unknown provider: {provider}")


_KEY_ENVS = {
    "openai": "OPENAI_API_KEY",
    "elevenlabs": "ELEVENLABS_API_KEY",
    "cartesia": "CARTESIA_API_KEY",
}


def _missing_prereqs(provider: str, cfg: dict) -> list[str]:
    missing: list[str] = []
    key_env = _KEY_ENVS[provider]
    if not os.environ.get(key_env):
        missing.append(f"env {key_env}")
    for label in ("JUNO", "CASPAR"):
        if _build_route(provider, label, cfg) is None:
            missing.append(f"{label} voice id")
    return missing


def render_provider(
    provider: str,
    cfg: dict,
    out_dir: Path,
    work_dir: Path,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    final = out_dir / f"{provider}.mp3"

    turn_paths: list[Path] = []
    for idx, (label, emotion, text) in enumerate(SCRIPT):
        route = _build_route(provider, label, cfg)
        if route is None:
            raise RuntimeError(f"{provider}: no route for {label}")
        turn_out = work_dir / f"{provider}_turn_{idx:02d}_{label.lower()}.mp3"
        instructions = (
            f"Speak as {label.title()} with a {emotion} tone." if emotion else ""
        )
        print(f"  [{provider}] turn {idx + 1}/{len(SCRIPT)} {label} ({len(text)} chars)")
        tts_engines.synthesize_tts(
            text=text,
            output_path=turn_out,
            route=route,
            cfg=cfg,
            instructions=instructions,
        )
        turn_paths.append(turn_out)

    tts_engines.ffmpeg_concat_configured(turn_paths, final, cfg)
    return final


def main() -> int:
    cfg = _load_cfg()
    requested = [a.lower() for a in sys.argv[1:]] or [
        "openai",
        "elevenlabs",
        "cartesia",
    ]
    unknown = [p for p in requested if p not in _KEY_ENVS]
    if unknown:
        print(f"Unknown provider(s): {unknown}. Valid: {list(_KEY_ENVS)}")
        return 2

    out_dir = Path("episodes/tts_comparison")
    work_dir = out_dir / "_work"
    print(f"Output dir: {out_dir.resolve()}")
    print(f"Script: {len(SCRIPT)} turns, "
          f"{sum(len(t) for _, _, t in SCRIPT)} chars total")

    results: dict[str, str] = {}
    for provider in requested:
        print(f"\n=== {provider} ===")
        missing = _missing_prereqs(provider, cfg)
        if missing:
            msg = f"skipped — missing: {', '.join(missing)}"
            print(f"  {msg}")
            results[provider] = msg
            continue
        try:
            final = render_provider(provider, cfg, out_dir, work_dir)
            results[provider] = f"OK -> {final}"
            print(f"  OK -> {final}")
        except Exception as exc:  # noqa: BLE001 — top-level driver, log + continue
            results[provider] = f"FAILED: {exc}"
            print(f"  FAILED: {exc}")

    print("\n=== Summary ===")
    for provider, status in results.items():
        print(f"  {provider:12s} {status}")
    return 0 if all(s.startswith("OK") for s in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
