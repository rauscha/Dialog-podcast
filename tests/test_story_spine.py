import json
import generate_podcast as gp

GOOD_SPINE = {
    "logline": "How a feud over the nature of the mind split a city.",
    "newcomer_promise": "You'll be able to explain why Vienna 1900 still matters.",
    "segments": [
        {
            "id": "S1",
            "anchor": "Freud pacing his study at Berggasse 19, 1895.",
            "stakes": "Nobody yet agreed the unconscious was real.",
            "names_to_define": [
                {"name": "Berggasse 19", "one_line": "Freud's apartment and office in Vienna"}
            ],
            "comprehension_target": "What Freud was claiming and why it was radical.",
            "host_angle": "Caspar doubts it's science — AFTER the claim is laid out.",
            "carrier": "JUNO",
            "surrogate": "CASPAR",
        }
    ],
    "open_loops": [],
}


def test_validator_accepts_good_spine():
    ok, errors = gp._validate_story_spine(GOOD_SPINE)
    assert ok, errors
    assert errors == []


def test_validator_flags_missing_top_level():
    bad = dict(GOOD_SPINE)
    del bad["logline"]
    ok, errors = gp._validate_story_spine(bad)
    assert not ok
    assert any("logline" in e for e in errors)


def test_validator_flags_missing_segment_field():
    bad = {**GOOD_SPINE, "segments": [{"id": "S1"}]}
    ok, errors = gp._validate_story_spine(bad)
    assert not ok
    assert any("anchor" in e for e in errors)


def test_validator_allows_missing_open_loops():
    no_loops = {k: v for k, v in GOOD_SPINE.items() if k != "open_loops"}
    ok, errors = gp._validate_story_spine(no_loops)
    assert ok, errors


def test_build_story_spine_happy_path(fake_client):
    fake_client.queue(json.dumps(GOOD_SPINE))
    cfg = dict(gp.DEFAULTS)
    spine = gp._build_story_spine(
        "Vienna 1900", cfg, fake_client,
        thesis="memo", guest_plan="no guest",
        research_package={"readable_brief": "brief"},
    )
    assert spine is not None
    assert spine["segments"][0]["id"] == "S1"


def test_build_story_spine_disabled_returns_none():
    cfg = {**gp.DEFAULTS, "use_story_spine": False}
    spine = gp._build_story_spine("x", cfg, None, "t", "g", {})
    assert spine is None


def test_build_story_spine_invalid_json_returns_none(fake_client):
    fake_client.queue("not json at all")
    cfg = dict(gp.DEFAULTS)
    spine = gp._build_story_spine("x", cfg, fake_client, "t", "g", {"readable_brief": "b"})
    assert spine is None


def test_build_story_spine_skips_digest_without_calling_llm(fake_client):
    # Digest episodes carry their own structural_plan; the spine must NOT run,
    # and must short-circuit BEFORE any LLM call. fake_client has no queued
    # responses, so any LLM call would raise — asserting calls == [] proves the
    # digest gate fired before the client was touched.
    cfg = {**gp.DEFAULTS, "episode_type": "digest"}
    spine = gp._build_story_spine("x", cfg, fake_client, "t", "g", {"readable_brief": "b"})
    assert spine is None
    assert fake_client.calls == []
