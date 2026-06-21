# tests/test_turn_parser.py
import generate_podcast as gp

SCRIPT = """JUNO [warm]: Vienna in 1900 was a city arguing with itself.
CASPAR [curious]: Arguing how?
JUNO [thoughtful]: About what a mind even is."""


def test_split_turns_basic():
    turns = gp._split_turns(SCRIPT)
    assert len(turns) == 3
    assert turns[0]["speaker"] == "JUNO"
    assert turns[0]["emotion"] == "warm"
    assert turns[0]["text"].startswith("Vienna in 1900")
    assert turns[1]["speaker"] == "CASPAR"
    assert turns[2]["index"] == 2


def test_split_turns_skips_non_dialogue():
    messy = "\n\nNot a turn line.\n" + SCRIPT + "\n\n"
    turns = gp._split_turns(messy)
    assert len(turns) == 3
    assert all(t["speaker"] in ("JUNO", "CASPAR") for t in turns)


def test_join_turns_round_trips():
    turns = gp._split_turns(SCRIPT)
    assert gp._join_turns(turns) == SCRIPT


def test_split_turns_lossless_with_indentation():
    # A script where one turn line has leading whitespace; the round-trip must be exact.
    indented = (
        "JUNO [warm]: First line.\n"
        "  CASPAR [curious]: indented line.\n"
        "JUNO [thoughtful]: Last line."
    )
    turns = gp._split_turns(indented)
    # Semantic fields are derived from the stripped match — no leading spaces in text.
    assert turns[1]["speaker"] == "CASPAR"
    assert turns[1]["text"] == "indented line."
    assert turns[1]["emotion"] == "curious"
    # raw preserves the original unstripped line for lossless reassembly.
    assert turns[1]["raw"] == "  CASPAR [curious]: indented line."
    # Full round-trip must be exact.
    assert gp._join_turns(gp._split_turns(indented)) == indented


def test_split_turns_empty_and_none():
    assert gp._split_turns("") == []
    assert gp._split_turns(None) == []
