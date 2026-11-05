from pathlib import Path

import tts_engines as te


def test_tag_only_for_tag_models():
    assert te.elevenlabs_audio_tag("warm, curious", "eleven_v4") == "[warm, curious] "
    assert te.elevenlabs_audio_tag("warm, curious", "eleven_v3") == "[warm, curious] "
    assert te.elevenlabs_audio_tag("warm, curious", "eleven_turbo_v2") == ""
    assert te.elevenlabs_audio_tag("", "eleven_v4") == ""


def test_tag_uses_plain_words():
    assert te.elevenlabs_audio_tag("half-laughing", "eleven_v4") == "[half laughing] "


def test_v4_request_carries_tag(tmp_path: Path, monkeypatch):
    sent = []

    class _Resp:
        content = b"ID3"

        def raise_for_status(self):
            pass

    def fake_post(url, json, headers, timeout):
        sent.append(json)
        return _Resp()

    monkeypatch.setenv("ELEVENLABS_API_KEY", "test")
    monkeypatch.setattr(te.req_lib, "post", fake_post)
    route = {"provider": "elevenlabs", "voice_id": "v", "model": "eleven_v4"}
    te.synthesize_tts(text="Hello there.", output_path=tmp_path / "t.mp3",
                      route=route, cfg={}, audio_tag="dry, measured")
    assert sent[0]["model_id"] == "eleven_v4"
    assert sent[0]["text"] == "[dry, measured] Hello there."
