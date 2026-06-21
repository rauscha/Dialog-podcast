"""Tests for _audio_roundtrip_check — publish-path invariants.

The critical invariant: _audio_roundtrip_check NEVER propagates an exception
to the caller, even when the naive read raises internally.  It also short-
circuits immediately when use_audio_roundtrip is False.
"""
import sys
import types
from pathlib import Path

import pytest

import generate_podcast as gp


def test_flag_off_returns_ran_false_immediately():
    """With use_audio_roundtrip=False the function must return ran=False
    without touching any external dependency."""
    cfg = {**gp.DEFAULTS, "use_audio_roundtrip": False}
    result = gp._audio_roundtrip_check("nonexistent.mp3", cfg, client=None)
    assert result["ran"] is False


def test_naive_read_raises_returns_ran_false_never_propagates(
    monkeypatch, tmp_path
):
    """Transcription succeeds, but naive listener raises — must return
    ran=False and must NOT propagate the exception (publish-path invariant)."""
    cfg = {**gp.DEFAULTS, "use_audio_roundtrip": True}

    # Create a dummy audio file so Path(audio_path).with_suffix() resolves cleanly.
    audio_path = tmp_path / "episode.mp3"
    audio_path.write_bytes(b"FAKE")

    expected_txt = str(audio_path.with_suffix(".transcript.txt"))

    # Monkeypatch scripts.transcribe_episode.main to write a tiny transcript
    # and return exit-code 0 (transcription succeeds).
    def _fake_transcribe(argv):
        Path(expected_txt).write_text(
            "Turn 1: Hello world\nTurn 2: Goodbye world\n",
            encoding="utf-8",
        )
        return 0

    fake_module = types.ModuleType("scripts.transcribe_episode")
    fake_module.main = _fake_transcribe

    # Inject the fake module so the lazy import inside _audio_roundtrip_check finds it.
    monkeypatch.setitem(sys.modules, "scripts.transcribe_episode", fake_module)

    # The naive listener raises — this is what we're guarding against.
    monkeypatch.setattr(
        gp,
        "_run_naive_listener",
        lambda pseudo, cfg, client: (_ for _ in ()).throw(
            RuntimeError("simulated naive listener crash")
        ),
    )

    # Must not raise, and must return ran=False.
    result = gp._audio_roundtrip_check(str(audio_path), cfg, client=None)
    assert result["ran"] is False
    assert result["breaks"] == []
