#!/usr/bin/env python3
"""transcribe_episode.py — quick faster-whisper transcript for editorial review.

Not part of the pipeline. Used to recover a listenable transcript of an already-
published episode when the work-dir script was cleaned up. Output is timestamped
plain text (no diarization) — enough to read for flow + AI-tell review.

    python scripts/transcribe_episode.py <audio.mp3> [out.txt]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path


def _fmt(t: float) -> str:
    m, s = divmod(int(t), 60)
    return f"{m:02d}:{s:02d}"


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    audio = Path(argv[1])
    out = Path(argv[2]) if len(argv) > 2 else audio.with_suffix(".transcript.txt")

    from faster_whisper import WhisperModel

    # Prefer GPU; fall back to CPU if the CUDA/cuDNN runtime isn't wired up.
    model = None
    for device, compute in (("cuda", "float16"), ("cpu", "int8")):
        try:
            print(f"[load] WhisperModel large-v3 on {device}/{compute} ...", flush=True)
            model = WhisperModel("large-v3", device=device, compute_type=compute)
            break
        except Exception as e:  # noqa: BLE001
            print(f"[load] {device} failed: {e}", flush=True)
    if model is None:
        print("[fatal] could not load a Whisper model", flush=True)
        return 1

    t0 = time.time()
    segments, info = model.transcribe(str(audio), vad_filter=True, beam_size=5)
    print(f"[run] language={info.language} ({info.language_probability:.2f}), "
          f"duration={info.duration:.0f}s — transcribing ...", flush=True)

    lines: list[str] = []
    for seg in segments:
        line = f"[{_fmt(seg.start)}] {seg.text.strip()}"
        lines.append(line)
        print(line, flush=True)

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n[done] {len(lines)} segments in {time.time()-t0:.0f}s -> {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
