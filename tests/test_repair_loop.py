import generate_podcast as gp

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_trace():
    return {
        "naive": {
            "breaks": [],
            "followed_overall": True,
            "first_bounce_turn": None,
            "per_turn": [],
        },
        "narration_vs_banter": {
            "ratio": 0.9,
            "threshold": 0.35,
            "pass": True,
            "render_beats": 9,
            "react_only_beats": 1,
        },
    }


def _failing_trace(breaks):
    return {
        "naive": {
            "breaks": breaks,
            "followed_overall": False,
            "first_bounce_turn": breaks[0]["turn"] if breaks else None,
            "per_turn": [],
        },
        "narration_vs_banter": {
            "ratio": 0.1,
            "threshold": 0.35,
            "pass": True,  # ratio passes; only breaks fail
            "render_beats": 0,
            "react_only_beats": 1,
        },
    }


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


def test_repair_applies_highest_turn_first(monkeypatch):
    """Pass 2 of the repair loop must apply repairs in descending turn order.

    Setup: three actionable breaks at turns 2, 9, 5 (severity-order puts them
    as 9, 5, 2 by "high">"med">"low" — but that is NOT descending turn order).
    An expert hollow_spot lands at turn 7.  Expected apply order: 9, 7, 5, 2.

    The test monkeypatches _apply_repair to record each call's break turn and
    return turns unchanged, then asserts the recorded sequence is descending.
    """
    cfg = {**gp.DEFAULTS, "synthetic_listener_max_repair_rounds": 2}

    # Three breaks at non-monotonic turns; severity order ≠ turn order.
    breaks = [
        {"turn": 2, "type": "no_stakes", "severity": "high", "detail": "d"},
        {"turn": 9, "type": "no_stakes", "severity": "med",  "detail": "d"},
        {"turn": 5, "type": "no_stakes", "severity": "high", "detail": "d"},
    ]
    failing = _failing_trace(breaks)

    # _run_naive_listener: fail once, then clean.
    naive_calls = {"n": 0}
    def _naive(s, c, cl):
        naive_calls["n"] += 1
        if naive_calls["n"] == 1:
            return failing
        return _clean_trace()

    # Expert listener returns a hollow_spot at turn 7 on the first (only) repair round.
    expert_calls = {"n": 0}
    def _expert(s, c, cl):
        expert_calls["n"] += 1
        if expert_calls["n"] == 1:
            return {"hollow_spots": [{"turn": 7, "detail": "hs"}], "errors": []}
        return {"hollow_spots": [], "errors": []}

    # Record the turn of each _apply_repair call; return turns unchanged.
    applied_turns: list[int] = []
    def _fake_apply(turns, brk, move, cfg, cl):
        applied_turns.append(int(brk.get("turn", 0)))
        return turns

    monkeypatch.setattr(gp, "_run_naive_listener", _naive)
    monkeypatch.setattr(gp, "_run_expert_listener", _expert)
    monkeypatch.setattr(gp, "_apply_repair", _fake_apply)

    script = "JUNO [x]: hi\nCASPAR [y]: hello"
    gp._run_repair_loop(script, cfg, None)

    # Must have applied exactly 4 repairs (3 breaks + 1 expert spot).
    assert len(applied_turns) == 4, f"expected 4 repairs, got {applied_turns}"
    # Must be strictly descending (highest-turn first).
    assert applied_turns == sorted(applied_turns, reverse=True), (
        f"apply order was not descending: {applied_turns}"
    )
    # Confirm the exact expected sequence.
    assert applied_turns == [9, 7, 5, 2], f"unexpected order: {applied_turns}"
