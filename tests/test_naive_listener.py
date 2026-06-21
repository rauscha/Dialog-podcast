import json
import generate_podcast as gp


def test_narration_ratio_basic():
    per_turn = [
        {"turn": 0, "delivered_new_material": True},
        {"turn": 1, "delivered_new_material": True},
        {"turn": 2, "delivered_new_material": False},
        {"turn": 3, "delivered_new_material": False},
        {"turn": 4, "delivered_new_material": False},
    ]
    r = gp._compute_narration_ratio(per_turn, threshold=0.6)
    assert r["render_beats"] == 2
    assert r["react_only_beats"] == 3
    assert abs(r["ratio"] - 0.4) < 1e-9
    assert r["pass"] is False


def test_narration_ratio_passes_threshold():
    per_turn = [{"turn": i, "delivered_new_material": i < 7} for i in range(10)]
    r = gp._compute_narration_ratio(per_turn, threshold=0.6)
    assert r["ratio"] == 0.7
    assert r["pass"] is True


def test_narration_ratio_empty():
    r = gp._compute_narration_ratio([], threshold=0.6)
    assert r["ratio"] == 0.0
    assert r["pass"] is False


def test_run_naive_listener_aggregates_and_is_asymmetric(fake_client):
    script = (
        "JUNO [warm]: Vienna in 1900 was arguing with itself.\n"
        "CASPAR [curious]: About Schorske?\n"
        "JUNO [flat]: Right, exactly."
    )
    # Turn 0: new material. Turn 1: undefined name 'Schorske'. Turn 2: react-only.
    fake_client.queue(json.dumps({"delivered_new_material": True, "confusion": None,
                                  "engaged": True}))
    fake_client.queue(json.dumps({"delivered_new_material": False,
                                  "confusion": "who is Schorske?",
                                  "type": "undefined_name", "severity": "high",
                                  "engaged": False}))
    fake_client.queue(json.dumps({"delivered_new_material": False, "confusion": None,
                                  "engaged": False}))
    cfg = dict(gp.DEFAULTS)
    trace = gp._run_naive_listener(script, cfg, fake_client)

    assert len(trace["naive"]["per_turn"]) == 3
    assert trace["naive"]["breaks"][0]["turn"] == 1
    assert trace["naive"]["breaks"][0]["severity"] == "high"
    assert trace["naive"]["first_bounce_turn"] == 1
    assert trace["narration_vs_banter"]["render_beats"] == 1

    # Asymmetry: the turn-1 call must NOT contain turn-2 text.
    turn1_call = fake_client.calls[1]
    sent = turn1_call["messages"][0]["content"]
    assert "exactly" not in sent  # turn 2's words never leaked into turn 1
    assert "Vienna" in sent        # but the prior turn did


def test_run_expert_listener_parses(fake_client):
    fake_client.queue(json.dumps({
        "hollow_spots": [{"turn": 9, "detail": "six names listed, none rendered"}],
        "errors": [],
    }))
    cfg = dict(gp.DEFAULTS)
    out = gp._run_expert_listener("JUNO [x]: words", cfg, fake_client)
    assert out["hollow_spots"][0]["turn"] == 9
    assert out["errors"] == []


def test_run_expert_listener_disabled():
    cfg = {**gp.DEFAULTS, "use_expert_listener": False}
    out = gp._run_expert_listener("JUNO [x]: words", cfg, None)
    assert out == {"hollow_spots": [], "errors": []}
