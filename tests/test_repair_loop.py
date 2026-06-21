import generate_podcast as gp


def test_select_skip_for_low_severity():
    brk = {"turn": 5, "type": "undefined_name", "severity": "low"}
    assert gp._select_repair_move(brk, [], dict(gp.DEFAULTS)) == "skip"


def test_select_rewrite_for_undefined_name():
    brk = {"turn": 5, "type": "undefined_name", "severity": "high"}
    assert gp._select_repair_move(brk, [], dict(gp.DEFAULTS)) == "rewrite"


def test_select_clarify_for_meaty_gap():
    brk = {"turn": 12, "type": "no_stakes", "severity": "high"}
    assert gp._select_repair_move(brk, [], dict(gp.DEFAULTS)) == "clarify"


def test_density_cap_downgrades_clarify_to_rewrite():
    cfg = dict(gp.DEFAULTS)  # clarification_density_turns = 8
    brk = {"turn": 12, "type": "no_stakes", "severity": "high"}
    # A clarify was already inserted at turn 6 → within 8 turns of 12 → downgrade.
    assert gp._select_repair_move(brk, [6], cfg) == "rewrite"
    # But a clarify far away (turn 1) does not block.
    assert gp._select_repair_move(brk, [1], cfg) == "clarify"


def test_repair_loop_terminates_when_already_clean(monkeypatch):
    cfg = dict(gp.DEFAULTS)
    clean = {"naive": {"breaks": [], "followed_overall": True, "first_bounce_turn": None, "per_turn": []},
             "narration_vs_banter": {"ratio": 0.9, "threshold": 0.6, "pass": True,
                                     "render_beats": 9, "react_only_beats": 1}}
    monkeypatch.setattr(gp, "_run_naive_listener", lambda s, c, cl: clean)
    monkeypatch.setattr(gp, "_run_expert_listener", lambda s, c, cl: {"hollow_spots": [], "errors": []})
    out, trace = gp._run_repair_loop("JUNO [x]: hi", cfg, None)
    assert out == "JUNO [x]: hi"
    assert trace["narration_vs_banter"]["pass"] is True


def test_repair_loop_respects_max_rounds(monkeypatch):
    cfg = {**gp.DEFAULTS, "synthetic_listener_max_repair_rounds": 2}
    failing = {"naive": {"breaks": [{"turn": 0, "type": "no_stakes", "severity": "high",
                                     "detail": "lost"}],
                         "followed_overall": False, "first_bounce_turn": 0, "per_turn": []},
               "narration_vs_banter": {"ratio": 0.1, "threshold": 0.6, "pass": False,
                                       "render_beats": 0, "react_only_beats": 1}}
    calls = {"n": 0}
    def _always_failing(s, c, cl):
        calls["n"] += 1
        return failing
    monkeypatch.setattr(gp, "_run_naive_listener", _always_failing)
    monkeypatch.setattr(gp, "_run_expert_listener", lambda s, c, cl: {"hollow_spots": [], "errors": []})
    monkeypatch.setattr(gp, "_apply_repair", lambda turns, b, m, c, cl: turns)  # no-op repair
    out, trace = gp._run_repair_loop("JUNO [x]: hi", cfg, None)
    # initial gate + 2 rounds of re-gate = 3 naive calls; never infinite.
    assert calls["n"] == 3
    assert trace["narration_vs_banter"]["pass"] is False
