#!/usr/bin/env python3
"""music_gen.py — Generative intro/outro music via Meta's MusicGen (audiocraft).

Falls back to a numpy/scipy ambient pad when audiocraft is not installed.
"""

import logging
import subprocess
import wave as _wave_mod
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from audiocraft.models import MusicGen
    import torchaudio
    import torch
    HAS_AUDIOCRAFT = True
except ImportError:
    HAS_AUDIOCRAFT = False

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

# Fastest available Claude model — prompt generation is a 10-word task
_HAIKU_MODEL = "claude-haiku-4-5-20251001"


def generate_music(
    prompt: str,
    duration_sec: int,
    output_path: Path,
    model_name: str = "facebook/musicgen-small",
    fade_sec: float = 2.0,
) -> Path:
    """Generate music from a text prompt, apply fades, and save as MP3.

    audiocraft caches the model after the first get_pretrained call,
    so repeated calls on the same model_name are fast.
    """
    model = MusicGen.get_pretrained(model_name)
    model.set_generation_params(duration=duration_sec)

    wav = model.generate([prompt])  # shape: [batch=1, channels, samples]

    sample_rate = model.sample_rate
    fade_samples = int(fade_sec * sample_rate)

    if fade_samples > 0 and wav.shape[-1] > fade_samples * 2:
        fade_in = torch.linspace(0.0, 1.0, fade_samples, device=wav.device)
        wav[..., :fade_samples] *= fade_in
        fade_out = torch.linspace(1.0, 0.0, fade_samples, device=wav.device)
        wav[..., -fade_samples:] *= fade_out

    wav_path = output_path.with_suffix(".wav")
    wav_path.parent.mkdir(parents=True, exist_ok=True)

    # Remove batch dimension before saving: [channels, samples]
    torchaudio.save(str(wav_path), wav.squeeze(0).cpu(), sample_rate)

    mp3_path = output_path.with_suffix(".mp3")
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(wav_path), "-b:a", "128k", str(mp3_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg WAV→MP3 conversion failed: {result.stderr[:300]}")
    finally:
        # Always remove the intermediate WAV, even if ffmpeg is not installed or fails
        wav_path.unlink(missing_ok=True)

    return mp3_path


def generate_music_numpy(
    duration_sec: int,
    output_path: Path,
    fade_sec: float = 2.0,
) -> Path:
    """Generate a simple ambient pad using numpy — no GPU or audiocraft required.

    Layered Cmaj7 sine waves + slow LFO tremolo + optional scipy low-pass filter,
    written as a stereo 44100 Hz WAV then converted to MP3 via ffmpeg.
    """
    if not HAS_NUMPY:
        raise ImportError("numpy is required for the music fallback path")

    sample_rate = 44100
    n_samples = int(sample_rate * duration_sec)
    t = np.linspace(0, duration_sec, n_samples, endpoint=False)

    # Cmaj7 chord: C4, E4, G4, B4
    freqs = [261.63, 329.63, 392.00, 493.88]
    wave = np.zeros(n_samples, dtype=np.float64)
    for f in freqs:
        wave += np.sin(2 * np.pi * f * t) * (0.25 / len(freqs))

    # Slow LFO tremolo for warmth (0.15 Hz)
    wave *= 0.85 + 0.15 * np.sin(2 * np.pi * 0.15 * t)

    # Soft low-pass filter via scipy if available
    try:
        from scipy.signal import butter, lfilter
        b, a = butter(4, 1200.0 / (sample_rate / 2.0), btype="low")
        wave = lfilter(b, a, wave)
    except ImportError:
        pass

    # Fades
    fade_samples = int(fade_sec * sample_rate)
    if fade_samples > 0 and n_samples > fade_samples * 2:
        wave[:fade_samples] *= np.linspace(0.0, 1.0, fade_samples)
        wave[-fade_samples:] *= np.linspace(1.0, 0.0, fade_samples)

    pcm = (np.clip(wave, -1.0, 1.0) * 32767).astype(np.int16)
    stereo = np.column_stack([pcm, pcm])

    wav_path = output_path.with_suffix(".wav")
    wav_path.parent.mkdir(parents=True, exist_ok=True)

    with _wave_mod.open(str(wav_path), "w") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(stereo.tobytes())

    mp3_path = output_path.with_suffix(".mp3")
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(wav_path), "-b:a", "128k", str(mp3_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg WAV→MP3 conversion failed: {result.stderr[:300]}")
    finally:
        wav_path.unlink(missing_ok=True)

    return mp3_path


def get_music_prompt(topic: str, anthropic_client) -> str:
    """Ask Claude Haiku for a concise MusicGen-compatible prompt for the episode topic."""
    resp = anthropic_client.messages.create(
        model=_HAIKU_MODEL,
        max_tokens=64,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Write a 10-15 word music generation prompt for a podcast episode about: {topic}\n"
                    "The music should feel curious, warm, and slightly cinematic — like Radiolab's theme.\n"
                    "Reply with ONLY the music description, no explanation, no quotes."
                ),
            }
        ],
    )
    return resp.content[0].text.strip()


def generate_intro_outro(
    cfg: dict,
    topic: str,
    work_dir: Path,
    anthropic_client,
) -> tuple:
    """Generate intro and outro music clips for the episode.

    Tries MusicGen (audiocraft) first; falls back to the numpy ambient pad when
    audiocraft is not installed. Returns (intro_path, outro_path) or (None, None).
    Cedar is credited as the composer of the show's theme music.
    """
    if not HAS_AUDIOCRAFT and not HAS_NUMPY:
        logger.warning("Neither audiocraft nor numpy installed — skipping music generation")
        return None, None

    try:
        work_dir.mkdir(parents=True, exist_ok=True)

        duration = int(cfg.get("music_duration_sec", 12))
        fade_sec = float(cfg.get("music_fade_sec", 2.0))

        if HAS_AUDIOCRAFT:
            try:
                prompt = get_music_prompt(topic, anthropic_client)
                logger.info(f"Music prompt (MusicGen): {prompt!r}")
                model_name = cfg.get("music_model", "facebook/musicgen-small")
                intro_path = generate_music(
                    prompt=prompt,
                    duration_sec=duration,
                    output_path=work_dir / "intro_music.mp3",
                    model_name=model_name,
                    fade_sec=fade_sec,
                )
                outro_path = generate_music(
                    prompt=prompt,
                    duration_sec=duration,
                    output_path=work_dir / "outro_music.mp3",
                    model_name=model_name,
                    fade_sec=fade_sec * 2.0,
                )
                logger.info(f"Intro music generated: {intro_path}")
                logger.info(f"Outro music generated: {outro_path}")
                return intro_path, outro_path
            except Exception as exc:
                if HAS_NUMPY:
                    logger.warning(
                        f"MusicGen failed ({type(exc).__name__}: {exc!s:.120}) "
                        "— falling back to numpy ambient pad"
                    )
                else:
                    raise

        logger.info("audiocraft unavailable — using numpy ambient pad for music")
        intro_path = generate_music_numpy(
            duration_sec=duration,
            output_path=work_dir / "intro_music.mp3",
            fade_sec=fade_sec,
        )
        # Outro uses 2x fade duration for a more natural fade-to-silence ending
        outro_path = generate_music_numpy(
            duration_sec=duration,
            output_path=work_dir / "outro_music.mp3",
            fade_sec=fade_sec * 2.0,
        )

        logger.info(f"Intro music generated: {intro_path}")
        logger.info(f"Outro music generated: {outro_path}")
        return intro_path, outro_path

    except Exception as exc:
        logger.exception(f"Music generation failed: {exc}")
        return None, None
