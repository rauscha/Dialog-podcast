import generate_podcast as gp


def test_new_flags_have_defaults():
    d = gp.DEFAULTS
    assert d["use_story_spine"] is True
    assert d["use_synthetic_listener"] is True
    assert d["use_expert_listener"] is True
    assert d["use_audio_roundtrip"] is True
    assert d["synthetic_listener_max_repair_rounds"] == 2
    assert d["clarification_density_turns"] == 8
    assert d["synthetic_listener_max_turns"] == 0
    assert d["narration_ratio_threshold"] == 0.35  # recalibrated 2026-06-21 from 0.6
    assert d["dialogue_draft_temperature"] == 0.6


def test_new_flags_registered_in_type_sets():
    for k in ("use_story_spine", "use_synthetic_listener",
              "use_expert_listener", "use_audio_roundtrip"):
        assert k in gp._BOOL_CONFIG_KEYS
    for k in ("synthetic_listener_max_repair_rounds",
              "clarification_density_turns", "synthetic_listener_max_turns"):
        assert k in gp._INT_CONFIG_KEYS
    for k in ("narration_ratio_threshold", "dialogue_draft_temperature"):
        assert k in gp._FLOAT_CONFIG_KEYS


def test_string_coercion_round_trips():
    # config.json / env values arrive as strings; _coerce_config_value must
    # turn them into the right Python type.
    assert gp._coerce_config_value("use_story_spine", "false") is False
    assert gp._coerce_config_value("clarification_density_turns", "10") == 10
    assert gp._coerce_config_value("dialogue_draft_temperature", "0.55") == 0.55
