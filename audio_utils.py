#!/usr/bin/env python3
"""audio_utils.py — shared ffmpeg loudness helpers.

Pure-stdlib, no project imports, so both ``generate_podcast.py`` and
``clip_mixer.py`` can use these without any circular-dependency risk. The single
source of truth for two-pass EBU R128 loudness normalization, which previously
lived inline in ``_normalize_turn_loudness`` and was duplicated nowhere else
(clips and the final master were not leveled). Centralizing it lets the per-turn
path, the final master, and inserted clips all hit the same program target.
"""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_LOUDNORM_KEYS = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")


def parse_loudnorm_json(stderr: str) -> dict | None:
    """Pull the measurement JSON that ffmpeg's loudnorm prints to stderr."""
    try:
        end = stderr.rindex("}")
        start = stderr.rindex("{", 0, end)
        data = json.loads(stderr[start : end + 1])
    except (ValueError, json.JSONDecodeError):
        return None
    if not all(key in data for key in _LOUDNORM_KEYS):
        return None
    return {key: data[key] for key in _LOUDNORM_KEYS}


def deesser_filter(freq_hz: float, sample_rate: int, intensity: float) -> str:
    """Build an ffmpeg ``deesser`` filter string.

    ffmpeg's ``deesser`` takes a *normalized* frequency ``f`` in 0..1 (fraction
    of Nyquist), not Hz — so convert. ``i`` (intensity) defaults to 0 in ffmpeg
    (a no-op), hence we always pass a positive value. Frequency is clamped just
    inside the open (0, 1) interval to stay valid at any sample rate.
    """
    nyquist = max(1.0, float(sample_rate) / 2.0)
    f_norm = min(0.999, max(0.001, float(freq_hz) / nyquist))
    i_val = min(1.0, max(0.0, float(intensity)))
    return f"deesser=i={i_val:.3f}:f={f_norm:.4f}"


def two_pass_loudnorm(
    in_path,
    out_path,
    *,
    target_i: float = -14.0,
    target_tp: float = -1.0,
    target_lra: float = 11.0,
    sample_rate: int = 44100,
    channels: int = 2,
    bitrate: str = "192k",
    pre_filters: list[str] | None = None,
    measure_timeout: int = 120,
    encode_timeout: int = 900,
) -> dict:
    """Two-pass EBU R128 loudness normalization with constant (linear) gain.

    Pass 1 measures the (optionally pre-filtered) signal; pass 2 re-encodes with
    those measured values plus ``linear=true`` so one constant gain is applied
    and natural dynamics are preserved. ``pre_filters`` (e.g. highpass, lowpass,
    deesser) are applied *before* loudnorm in the same chain for both passes, so
    the measurement reflects the post-filter signal. Falls back to single-pass
    if measurement is unavailable, skips near-silent input untouched, and never
    raises — audio leveling must never abort an episode.

    Works in place when ``in_path == out_path`` (writes a temp sibling first,
    then atomically replaces). Returns
    ``{"ok": bool, "mode": "two_pass"|"single_pass"|"skipped"|"failed",
       "measured": dict|None}``.
    """
    in_path = Path(in_path)
    out_path = Path(out_path)
    if not in_path.exists():
        return {"ok": False, "mode": "failed", "measured": None}

    pre = list(pre_filters or [])
    base = f"loudnorm=I={target_i}:TP={target_tp}:LRA={target_lra}"

    # Pass 1 — measure.
    measure_chain = ",".join(pre + [base + ":print_format=json"])
    measured: dict | None = None
    try:
        probe = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-nostats", "-i", str(in_path),
                "-af", measure_chain, "-f", "null", "-",
            ],
            capture_output=True, text=True, timeout=measure_timeout,
        )
        measured = parse_loudnorm_json(probe.stderr)
    except (subprocess.SubprocessError, OSError):
        measured = None

    if measured is not None:
        try:
            input_i = float(measured["input_i"])
        except (TypeError, ValueError):
            input_i = float("-inf")
        if not (input_i > -70.0):
            # near-silent / unmeasurable: leave the input as recorded
            return {"ok": False, "mode": "skipped", "measured": measured}
        loud = (
            f"{base}:measured_I={measured['input_i']}"
            f":measured_TP={measured['input_tp']}"
            f":measured_LRA={measured['input_lra']}"
            f":measured_thresh={measured['input_thresh']}"
            f":offset={measured['target_offset']}"
            ":linear=true:print_format=summary"
        )
        mode = "two_pass"
    else:
        loud = base + ":print_format=summary"
        mode = "single_pass"

    af = ",".join(pre + [loud])
    tmp = out_path.with_name(f"{out_path.stem}_ln_tmp{out_path.suffix}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(in_path), "-vn", "-af", af,
                "-ar", str(int(sample_rate)), "-ac", str(int(channels)),
                "-c:a", "libmp3lame", "-b:a", str(bitrate), str(tmp),
            ],
            capture_output=True, text=True, timeout=encode_timeout,
        )
        if result.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
            tmp.replace(out_path)
            return {"ok": True, "mode": mode, "measured": measured}
        logger.debug(
            "two_pass_loudnorm ffmpeg rc=%s: %s",
            result.returncode, result.stderr[:300],
        )
        tmp.unlink(missing_ok=True)
        return {"ok": False, "mode": "failed", "measured": measured}
    except (subprocess.SubprocessError, OSError) as exc:
        logger.debug("two_pass_loudnorm error: %s", exc)
        tmp.unlink(missing_ok=True)
        return {"ok": False, "mode": "failed", "measured": measured}
