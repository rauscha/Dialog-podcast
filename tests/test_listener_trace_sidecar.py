# tests/test_listener_trace_sidecar.py
"""The Synthetic First Listener trace is otherwise only logged, so the now-active
work-dir cleanup loses it. _write_listener_trace_sidecar persists it next to the
audio as a JSON sidecar (mirroring the .script.txt sidecar) so the fidelity review
can inspect comprehension-gate output after the fact and it syncs across machines.
"""
import json

import generate_podcast as gp


def test_writes_sidecar_next_to_audio(tmp_path):
    audio = tmp_path / "20260624_202201_some_episode.mp3"
    trace = {
        "rounds": 2,
        "residual_ratio": 0.42,
        "turns": [
            {"index": 0, "confused": False, "note": ""},
            {"index": 1, "confused": True, "note": "who is Marta?"},
        ],
    }
    out = gp._write_listener_trace_sidecar(audio, trace)

    assert out == tmp_path / "20260624_202201_some_episode.listener_trace.json"
    assert out.exists()
    # Round-trips to the same object.
    assert json.loads(out.read_text(encoding="utf-8")) == trace


def test_empty_or_missing_trace_writes_nothing(tmp_path):
    audio = tmp_path / "ep.mp3"
    assert gp._write_listener_trace_sidecar(audio, {}) is None
    assert gp._write_listener_trace_sidecar(audio, None) is None
    assert not (tmp_path / "ep.listener_trace.json").exists()
