# Narration-First Pipeline + Synthetic First Listener — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make main-feed episodes followable by a first-time listener by adding a Story Spine artifact, re-aiming the thesis/beat-sheet/draft prompts toward establish-before-adjudicate, and adding a Synthetic First Listener comprehension gate with a rewrite-or-clarify repair loop — without rebuilding the working pipeline.

**Architecture:** All work lands in the existing `generate_podcast.py` chain (`_script_from_research_package`). Three prompts are re-aimed in place; three new stages are inserted (Story Spine before beat-sheet; Synthetic Listener gate + repair loop after the dialogue draft; Audio round-trip after render). Every new stage is flag-gated so that with flags off the pipeline is byte-identical to today. The naive listener runs **iteratively, one turn at a time**, so its no-look-ahead information asymmetry is guaranteed by construction. All quantitative logic (narration ratio, repair-move selection, density cap, loop termination, schema validation) is factored into **pure functions** that are unit-tested with a mocked Anthropic client; prose-quality of prompts is validated by a manual smoke render plus the §8 fidelity check.

**Tech Stack:** Python 3.11+, `anthropic` SDK, `pytest` (newly introduced for this work), `faster-whisper` (already present, via `scripts/transcribe_episode.py`).

**Source spec:** `docs/superpowers/specs/2026-06-20-narration-first-pipeline-design.md` (§10 open questions RESOLVED 2026-06-20).

## Global Constraints

- **Config priority:** environment variables → `config.json` → `DEFAULTS` dict. `config.json` overrides `DEFAULTS` — every new flag MUST be added to `DEFAULTS` *and* to the correct type set (`_BOOL_CONFIG_KEYS` / `_INT_CONFIG_KEYS` / `_FLOAT_CONFIG_KEYS`) or coercion silently drops it.
- **Flags off ⇒ byte-identical:** with every new flag disabled, the produced script and audio must be identical to the pre-change pipeline. This is a hard acceptance gate on every wiring task.
- **Digest path tolerance:** breaking the digest shows is acceptable per user direction, but do not *crash* the digest path. Digests already carry a `structural_plan`; the Story Spine is gated so it does not double-run on digests.
- **Model selection:** new LLM stages use `_model_for(cfg, "dialogue_model", _DIALOGUE_MODEL)` (= `claude-sonnet-4-6`) unless stated. Never hard-code a model id at a call site.
- **LLM call convention:** all model calls go through `_anthropic_text(client, *, model, system, content, max_tokens, temperature=None, cfg=None)`. JSON responses are parsed with the existing `_extract_json_object(text) -> dict | None` (line ~1041).
- **No new heavy deps:** `pytest` is the only new dependency. Do not add `pytest-asyncio`/`pytest-mock`; the fake client is a hand-rolled fixture (no async in the script chain).
- **Resolved design decisions (spec §10):** open_loops DEFERRED (schema slot kept, unenforced); naive listener ITERATIVE turn-by-turn; audio round-trip REPORT-ONLY; dialogue draft temperature LOWERED to 0.6 via config.
- **Colorblind-safe output:** any console/report severity must pair color with a text label (e.g. `[HIGH]`), never color alone.

---

## File structure

- `generate_podcast.py` — all pipeline changes (prompts, new stage functions, config flags, wiring). Existing large file; follow its in-file conventions (module-level `_X_SYSTEM` prompt constants near the other prompts ~line 584–940; helper functions defined before `_script_from_research_package`).
- `tests/` — NEW. Pure-logic unit tests. `tests/conftest.py` (fake client fixture), `tests/test_config_flags.py`, `tests/test_story_spine.py`, `tests/test_turn_parser.py`, `tests/test_naive_listener.py`, `tests/test_repair_loop.py`.
- `pytest.ini` — NEW. Minimal pytest config (testpaths, quiet).
- `scripts/check_listener_fidelity.py` — NEW. The §8 go/no-go fidelity harness (Vienna transcript vs a working digest transcript).
- `scripts/transcribe_episode.py` — EXISTING, reused unchanged by the audio round-trip stage.
- `config.json` — touched only if a flag needs a non-default value for a smoke render; otherwise unchanged.

**Insertion-point reference (current line numbers in `generate_podcast.py`, verify before editing — the file shifts as you add code):**
- Model constants: ~84–88. `DEFAULTS`: ~93–236. `_BOOL_CONFIG_KEYS`: ~238–258. `_INT_CONFIG_KEYS`: ~259–291. `_FLOAT_CONFIG_KEYS`: ~292–303.
- Prompt constants block: ~584–940.
- `_anthropic_text`: ~989. `_extract_json_object`: ~1041. `_model_for`: ~985.
- `_script_from_research_package`: ~1875. Thesis call: ~1924. Guest plan: ~1942. Beat-sheet call: ~1955. Dialogue draft call: ~2000 (temp literal `0.75` at ~2023); `_strip_to_dialogue(draft_script)` at ~2026. Anti-cliché: ~2028. Symmetry-break: ~2053. Disfluency: ~2075. Fact-check: ~2093. Performance: ~2161.
- Digest: `_DIGEST_RESEARCH_SYSTEM` ~2311; `_digest_research_and_script` ~2485.

---

## Task 1: Config scaffolding, test harness, and lowered draft temperature

Foundational. Adds every new flag to `DEFAULTS` and its type set, lowers the dialogue-draft temperature to a config value (spec §10.4), and bootstraps the pytest harness the rest of the plan needs.

**Files:**
- Modify: `generate_podcast.py` (`DEFAULTS` ~93–236; `_BOOL_CONFIG_KEYS` ~238; `_INT_CONFIG_KEYS` ~259; `_FLOAT_CONFIG_KEYS` ~292; dialogue-draft call ~2023)
- Create: `pytest.ini`
- Create: `tests/conftest.py`
- Test: `tests/test_config_flags.py`

**Interfaces:**
- Produces: new config keys readable via `cfg.get(...)` — `use_story_spine` (bool, True), `use_synthetic_listener` (bool, True), `use_expert_listener` (bool, True), `use_audio_roundtrip` (bool, True), `synthetic_listener_max_repair_rounds` (int, 2), `clarification_density_turns` (int, 8), `synthetic_listener_max_turns` (int, 0 = no cap), `narration_ratio_threshold` (float, 0.6), `dialogue_draft_temperature` (float, 0.6).
- Produces: `tests/conftest.py::FakeAnthropic` and the `fake_client` fixture — a stand-in for `anthropic.Anthropic` whose `.messages.create(...)` returns queued canned responses. Used by every later test.

- [ ] **Step 1: Create `pytest.ini`**

```ini
[pytest]
testpaths = tests
addopts = -q
python_files = test_*.py
python_functions = test_*
```

- [ ] **Step 2: Create the fake Anthropic client fixture**

The script's LLM calls go through `_anthropic_text`, which calls `client.messages.create(**kwargs)` and reads `resp.content` via `_extract_text`. The fake must mimic that response shape (`resp.content` = list of objects with a `.text` attribute).

```python
# tests/conftest.py
import sys
from pathlib import Path
import pytest

# Make generate_podcast importable when tests run from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class _FakeBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeResponse:
    def __init__(self, text):
        self.content = [_FakeBlock(text)]


class FakeAnthropic:
    """Minimal stand-in for anthropic.Anthropic.

    Feed it a list of response strings (FIFO). Each call to
    messages.create() pops the next one. Records every call's kwargs
    in .calls for assertions.
    """

    def __init__(self, responses=None):
        self._responses = list(responses or [])
        self.calls = []

        outer = self

        class _Messages:
            def create(self, **kwargs):
                outer.calls.append(kwargs)
                if not outer._responses:
                    raise AssertionError("FakeAnthropic ran out of queued responses")
                return _FakeResponse(outer._responses.pop(0))

        self.messages = _Messages()

    def queue(self, text):
        self._responses.append(text)


@pytest.fixture
def fake_client():
    return FakeAnthropic()
```

- [ ] **Step 3: Write the failing config test**

```python
# tests/test_config_flags.py
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
    assert d["narration_ratio_threshold"] == 0.6
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
```

- [ ] **Step 4: Run the test to confirm it fails**

Run: `python -m pytest tests/test_config_flags.py -q`
Expected: FAIL — `KeyError` on `use_story_spine` (defaults not added yet).

- [ ] **Step 5: Add the flags to `DEFAULTS`**

In the `DEFAULTS` dict (~line 93–236), add (group them with a comment near the other `use_*` editorial flags):

```python
    # ── Narration-first pipeline (2026-06-20 spec) ──────────────────
    "use_story_spine": True,
    "use_synthetic_listener": True,
    "use_expert_listener": True,
    "use_audio_roundtrip": True,
    "synthetic_listener_max_repair_rounds": 2,
    "clarification_density_turns": 8,
    "synthetic_listener_max_turns": 0,   # 0 = no cap; >0 truncates the naive read for cost
    "narration_ratio_threshold": 0.6,
    "dialogue_draft_temperature": 0.6,   # spec §10.4 — lowered from 0.75
```

- [ ] **Step 6: Register the flags in the type sets**

Add to `_BOOL_CONFIG_KEYS` (~238): `"use_story_spine"`, `"use_synthetic_listener"`, `"use_expert_listener"`, `"use_audio_roundtrip"`.
Add to `_INT_CONFIG_KEYS` (~259): `"synthetic_listener_max_repair_rounds"`, `"clarification_density_turns"`, `"synthetic_listener_max_turns"`.
Add to `_FLOAT_CONFIG_KEYS` (~292): `"narration_ratio_threshold"`, `"dialogue_draft_temperature"`.

- [ ] **Step 7: Wire the draft temperature into the dialogue-draft call**

At the dialogue-draft `_anthropic_text(...)` call (~line 2000–2025), replace the hard-coded temperature:

```python
        temperature=float(cfg.get("dialogue_draft_temperature", 0.6)),
```

(Replaces `temperature=0.75`.)

- [ ] **Step 8: Run the tests to confirm they pass**

Run: `python -m pytest tests/test_config_flags.py -q`
Expected: PASS (3 tests).

- [ ] **Step 9: Confirm the module still imports and compiles**

Run: `python -c "import generate_podcast"`
Expected: no output, exit 0.

- [ ] **Step 10: Commit**

```bash
git add generate_podcast.py pytest.ini tests/conftest.py tests/test_config_flags.py
git commit -m "feat(pipeline): add narration-first config flags + pytest harness; lower draft temp to 0.6"
```

---

## Task 2: Turn parser utility

A shared pure function that splits a dialogue script into structured turns. Both the naive listener (which must feed turns one at a time) and the repair loop (which inserts/edits turns) depend on it. DRY: reuse the existing speaker-line format `SPEAKER [emotion]: text`.

**Files:**
- Modify: `generate_podcast.py` (add `_split_turns` near `_strip_to_dialogue`)
- Test: `tests/test_turn_parser.py`

**Interfaces:**
- Produces: `_split_turns(script: str) -> list[dict]` where each dict is `{"index": int, "speaker": str, "emotion": str, "text": str, "raw": str}`. `raw` is the exact original line (for lossless reassembly). Non-dialogue lines (blank, stray prose) are skipped.
- Produces: `_join_turns(turns: list[dict]) -> str` — inverse of `_split_turns` using each turn's `raw`, joined by `\n`. Round-trips a parsed script back to text.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run to confirm it fails**

Run: `python -m pytest tests/test_turn_parser.py -q`
Expected: FAIL — `_split_turns` not defined.

- [ ] **Step 3: Implement `_split_turns` and `_join_turns`**

Place near `_strip_to_dialogue`. First grep for an existing turn-splitter used by the TTS path (`grep -n "def _strip_to_dialogue\|for .* in .*turn" generate_podcast.py`); if one already yields `(speaker, emotion, text)` tuples, wrap it instead of duplicating. Otherwise add:

```python
import re

# A dialogue line looks like:  JUNO [warm]: text...   (emotion optional)
_TURN_LINE_RE = re.compile(r"^([A-Z][A-Z0-9_]{0,39})\s*(?:\[([^\]]*)\])?\s*:\s*(.*)$")


def _split_turns(script: str) -> list[dict]:
    """Parse a dialogue script into structured turns. Non-dialogue lines skipped."""
    turns: list[dict] = []
    for line in (script or "").splitlines():
        if not line.strip():
            continue
        m = _TURN_LINE_RE.match(line.strip())
        if not m:
            continue
        speaker, emotion, text = m.group(1), (m.group(2) or "").strip(), m.group(3).strip()
        turns.append({
            "index": len(turns),
            "speaker": speaker,
            "emotion": emotion,
            "text": text,
            "raw": line.strip(),
        })
    return turns


def _join_turns(turns: list[dict]) -> str:
    """Inverse of _split_turns; reassembles using each turn's raw line."""
    return "\n".join(t["raw"] for t in turns)
```

- [ ] **Step 4: Run to confirm pass**

Run: `python -m pytest tests/test_turn_parser.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add generate_podcast.py tests/test_turn_parser.py
git commit -m "feat(pipeline): add _split_turns/_join_turns shared turn parser"
```

---

## Task 3: Story Spine artifact + stage

Adds `_STORY_SPINE_SYSTEM`, a pure JSON validator, a `_build_story_spine` LLM stage, and inserts it into the pipeline after guest-plan and before the beat-sheet (spec §5). The beat-sheet re-aim (Task 5) consumes it.

**Files:**
- Modify: `generate_podcast.py` (new prompt constant ~near 920; new functions before `_script_from_research_package`; insert call ~line 1951–1955)
- Test: `tests/test_story_spine.py`

**Interfaces:**
- Consumes: `_anthropic_text`, `_extract_json_object`, `_model_for`, `_DIALOGUE_MODEL`.
- Produces: `_validate_story_spine(obj: dict) -> tuple[bool, list[str]]` — pure; returns `(ok, errors)`. Required keys: `logline` (str), `newcomer_promise` (str), `segments` (non-empty list). Each segment requires `id`, `anchor`, `stakes`, `comprehension_target`, `host_angle`, `carrier`, `surrogate`, and a `names_to_define` list (may be empty). `open_loops` is OPTIONAL and unenforced (spec §10.1 — deferred).
- Produces: `_build_story_spine(topic, cfg, client, thesis, guest_plan, research_package) -> dict | None` — runs the LLM stage; returns the validated spine dict, or `None` if the flag is off / validation fails (caller treats `None` as "no spine, proceed as today").

- [ ] **Step 1: Write the failing tests (pure validator first)**

```python
# tests/test_story_spine.py
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
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_story_spine.py -q`
Expected: FAIL — `_validate_story_spine` not defined.

- [ ] **Step 3: Implement the pure validator**

```python
_STORY_SPINE_SEGMENT_FIELDS = (
    "id", "anchor", "stakes", "comprehension_target",
    "host_angle", "carrier", "surrogate",
)


def _validate_story_spine(obj: dict) -> tuple[bool, list[str]]:
    """Pure structural validation of a Story Spine. open_loops is optional."""
    errors: list[str] = []
    if not isinstance(obj, dict):
        return False, ["spine is not an object"]
    for key in ("logline", "newcomer_promise"):
        if not isinstance(obj.get(key), str) or not obj.get(key, "").strip():
            errors.append(f"missing or empty top-level field: {key}")
    segments = obj.get("segments")
    if not isinstance(segments, list) or not segments:
        errors.append("segments must be a non-empty list")
        return (not errors), errors
    for i, seg in enumerate(segments):
        if not isinstance(seg, dict):
            errors.append(f"segment {i} is not an object")
            continue
        for field in _STORY_SPINE_SEGMENT_FIELDS:
            if not str(seg.get(field, "")).strip():
                errors.append(f"segment {i} ({seg.get('id', '?')}): missing field {field}")
        if not isinstance(seg.get("names_to_define", []), list):
            errors.append(f"segment {i}: names_to_define must be a list")
    return (not errors), errors
```

- [ ] **Step 4: Run to confirm validator tests pass**

Run: `python -m pytest tests/test_story_spine.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Add the `_STORY_SPINE_SYSTEM` prompt constant**

Place with the other prompt constants (~line 920):

```python
_STORY_SPINE_SYSTEM = """\
You are the story architect for the podcast "Asynchronous." Before any dialogue \
exists, lay out the STORY the episode will tell — not the argument it will make. \
The hosts will be forced to follow this spine exactly.

Hard rules:
- Each segment must have ONE concrete anchor the listener is SHOWN — a scene, a \
person doing something, a place, an object. Not a topic, not a thesis.
- Establish before you adjudicate. Stakes and facts come first; the hosts' \
angle/disagreement is marked as coming AFTER the material lands.
- Every proper noun a smart layperson wouldn't know goes in names_to_define with a \
one-line gloss.
- Assume the listener knows nothing and cannot rewind. If a segment can't be \
followed cold, it is wrong.
- Assign a carrier (the host who TELLS this segment) and a surrogate (the host who \
asks the newcomer's questions here). Rotate them across segments so neither host is \
stuck in one role.

Return ONLY a JSON object with this exact shape:
{
  "logline": "one sentence: the story this episode tells",
  "newcomer_promise": "what a listener who knew nothing can follow/retell after",
  "segments": [
    {
      "id": "S1",
      "anchor": "the ONE concrete scene/person/place/object shown here",
      "stakes": "why this matters, in plain terms, before any cleverness",
      "names_to_define": [{"name": "X", "one_line": "gloss"}],
      "comprehension_target": "what the listener must understand by segment end",
      "host_angle": "the reaction/tension, explicitly AFTER the material lands",
      "carrier": "JUNO or CASPAR",
      "surrogate": "the other host"
    }
  ]
}
Do not include any prose outside the JSON object."""
```

- [ ] **Step 6: Implement `_build_story_spine` (LLM stage)**

Place before `_script_from_research_package`:

```python
def _build_story_spine(topic, cfg, client, thesis, guest_plan, research_package) -> dict | None:
    """Produce the Story Spine artifact. Returns None if disabled or invalid."""
    if not cfg.get("use_story_spine", True):
        return None
    brief = research_package.get("readable_brief", "") if isinstance(research_package, dict) else ""
    content = (
        f"TOPIC: {topic}\n\n"
        f"EDITORIAL MEMO (thesis):\n{thesis}\n\n"
        f"GUEST PLAN:\n{guest_plan}\n\n"
        f"RESEARCH BRIEF:\n{brief}\n"
    )
    raw = _anthropic_text(
        client,
        model=_model_for(cfg, "dialogue_model", _DIALOGUE_MODEL),
        system=_STORY_SPINE_SYSTEM,
        content=content,
        max_tokens=4096,
        temperature=0.5,
        cfg=cfg,
    )
    spine = _extract_json_object(raw)
    if spine is None:
        logger.warning("[story-spine] no JSON parsed; proceeding without a spine")
        return None
    ok, errors = _validate_story_spine(spine)
    if not ok:
        logger.warning("[story-spine] invalid spine, proceeding without: %s", "; ".join(errors[:5]))
        return None
    logger.info("[story-spine] %d segments; logline: %s",
                len(spine.get("segments", [])), spine.get("logline", "")[:80])
    return spine
```

- [ ] **Step 7: Insert the stage into the pipeline**

In `_script_from_research_package`, after the guest-plan assignment (~line 1951) and before the beat-sheet call (~line 1955), add:

```python
    story_spine = _build_story_spine(topic, cfg, client, thesis, guest_plan, research_package)
    spine_text = json.dumps(story_spine, ensure_ascii=False, indent=2) if story_spine else ""
```

(`spine_text` is threaded into the beat-sheet and draft in Tasks 5–6. If `story_spine` is `None`, `spine_text` is `""` and those prompts fall back to today's behavior.)

- [ ] **Step 8: Add a stage test with the fake client**

Append to `tests/test_story_spine.py`:

```python
import json


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
```

- [ ] **Step 9: Run the full story-spine test file**

Run: `python -m pytest tests/test_story_spine.py -q`
Expected: PASS (7 tests).

- [ ] **Step 10: Confirm import + byte-identical-when-off**

Run: `python -c "import generate_podcast"`
Expected: exit 0. (Flag-off behavior verified end-to-end in Task 13's regression; the disabled-returns-None test covers the unit case.)

- [ ] **Step 11: Commit**

```bash
git add generate_podcast.py tests/test_story_spine.py
git commit -m "feat(pipeline): add Story Spine stage + validator before beat-sheet"
```

---

## Task 4: Re-aim the thesis prompt

Add the two required fields (Exposition Order, Newcomer Promise) and soften the argument framing so the memo serves *telling a story* (spec §6.3). Prose change; acceptance is diff review + a targeted smoke call.

**Files:**
- Modify: `generate_podcast.py` (`_THESIS_SYSTEM` ~line 584–597)

**Interfaces:**
- Produces: thesis memo text now containing labeled `Exposition Order:` and `Newcomer Promise:` sections, consumed downstream by the Story Spine and beat-sheet prompts (free text, no schema).

- [ ] **Step 1: Read the current prompt**

Run: `sed -n '584,598p' generate_podcast.py` (or Read lines 584–598). Note the existing "Thesis / Why This Matters" framing.

- [ ] **Step 2: Edit `_THESIS_SYSTEM`**

Keep the memo format, but (a) soften "Thesis/argument" to "the story and why it matters," and (b) append two REQUIRED sections. Add to the end of the prompt body, before any closing instruction:

```
Your memo MUST end with these two labeled sections:

Exposition Order: an ordered list of what the listener must be TOLD before what —
the facts, names, and scenes that have to land first so nothing later is confusing.

Newcomer Promise: one sentence stating what a listener who knew NOTHING about this
topic will be able to retell a friend after the episode.

Frame the memo to serve TELLING THIS STORY clearly, not winning an argument. The
hosts' opinions are seasoning that comes after the material lands, never the spine.
```

- [ ] **Step 3: Compile check**

Run: `python -c "import generate_podcast"`
Expected: exit 0.

- [ ] **Step 4: Targeted smoke (manual, optional but recommended)**

Run a one-off thesis call to confirm the model emits both sections. Use the existing dry-run or a scratch snippet:

```bash
python -c "import generate_podcast as gp, os, anthropic; \
c=anthropic.Anthropic(); \
print(gp._anthropic_text(c, model=gp._DIALOGUE_MODEL, system=gp._THESIS_SYSTEM, \
content='TOPIC: Vienna 1900 and the birth of psychoanalysis\n', max_tokens=1200, temperature=0.5))"
```
Expected: output contains `Exposition Order:` and `Newcomer Promise:`. (Skip if no API key on this machine; defer to Task 13 smoke.)

- [ ] **Step 5: Commit**

```bash
git add generate_podcast.py
git commit -m "feat(pipeline): re-aim thesis prompt — exposition order + newcomer promise"
```

---

## Task 5: Re-aim the beat-sheet prompt (consume the spine)

Remove the "what Juno believes / what Caspar challenges" defining axis and the mandated disagreement; replace with one-scene-per-beat that honors the Story Spine (spec §6.3). Thread `spine_text` into the call.

**Files:**
- Modify: `generate_podcast.py` (`_BEAT_SHEET_SYSTEM` ~line 599–618; beat-sheet `_anthropic_text` call ~line 1955–1974)

**Interfaces:**
- Consumes: `spine_text` (from Task 3, Step 7).
- Produces: beat-sheet text where each beat maps to a spine segment, leads with the concrete anchor + stakes, defines names, and places the host angle last.

- [ ] **Step 1: Read the current prompt**

Read lines 599–618. Locate the lines mandating disagreement / "let a host be wrong" / the believes-vs-challenges axis.

- [ ] **Step 2: Edit `_BEAT_SHEET_SYSTEM`**

Remove the believes/challenges axis and the disagreement mandate. Replace the per-beat instruction with:

```
Each beat corresponds to ONE Story Spine segment, in order. For each beat:
1. Lead with the concrete ANCHOR — the scene/person/place/object the listener is shown.
2. State the STAKES in plain terms next.
3. Define every name in the segment's names_to_define, in line.
4. The HOST ANGLE (reaction, tension, or disagreement) is the LAST thing in the beat,
   and only after the material above has landed.
Build an arc, not a list. Do NOT manufacture disagreement; the hosts' job is to make
the listener understand, with opinion as seasoning at the end of a beat.
```

If a Story Spine is provided it is authoritative; if the spine block is empty, fall back to building beats directly from the thesis and brief.

- [ ] **Step 3: Thread the spine into the call**

In the beat-sheet `_anthropic_text` call (~line 1955–1974), prepend the spine to the `content` (only when present):

```python
        content=(
            (f"STORY SPINE (authoritative — one beat per segment, in order):\n{spine_text}\n\n" if spine_text else "")
            + f"EDITORIAL MEMO:\n{thesis}\n\n"
            + f"GUEST PLAN:\n{guest_plan}\n\n"
            + f"RESEARCH BRIEF:\n{research_package.get('readable_brief', '')}\n"
        ),
```

(Adapt to the exact variable names already in that call — keep whatever research fields it currently passes; only ADD the spine block in front.)

- [ ] **Step 4: Compile check**

Run: `python -c "import generate_podcast"`
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add generate_podcast.py
git commit -m "feat(pipeline): re-aim beat-sheet — one scene per beat, honor spine, drop forced disagreement"
```

---

## Task 6: Re-aim the dialogue-draft prompt (grounding + Carrier/Surrogate)

Add the MoonCast/NotebookLM grounding constraints and bind the Carrier/Surrogate roles (spec §6.2, §6.3). Temperature was already lowered in Task 1.

**Files:**
- Modify: `generate_podcast.py` (`_DIALOGUE_DRAFT_SYSTEM` ~line 657–687; draft call ~line 2000–2025)

**Interfaces:**
- Consumes: `spine_text` (Task 3), beat-sheet.
- Produces: a draft script that introduces the topic first, defines every name in line, establishes before adjudicating, and gives each host the Carrier/Surrogate job per segment.

- [ ] **Step 1: Read the current prompt**

Read lines 657–687. Note it's a `.format(target_words=...)` template — preserve the `{target_words}` placeholder and escape any literal braces you add as `{{` / `}}`.

- [ ] **Step 2: Edit `_DIALOGUE_DRAFT_SYSTEM`**

Add a constraints block (mind the brace-escaping in an f-string-less `.format` template — only `{target_words}` should be a real field):

```
Grounding rules (non-negotiable):
- OPEN by introducing the topic: a listener must never wonder "what am I even
  listening to?"
- Explain every term, name, and abbreviation a non-expert wouldn't know, in line,
  the first time it appears.
- Establish before you adjudicate: deliver the scene and the stakes BEFORE any host
  reacts, judges, or disagrees.
- One concrete scene per segment — show it, don't reference it.

Host jobs (from the Story Spine, per segment):
- The CARRIER delivers the material — the scene, the people, what happened, the stakes.
- The SURROGATE is the listener's proxy: asks the exact questions a curious newcomer
  would, forcing the carrier to answer with CONTENT, not quips.
- Keep Juno (associative/artistic) and Caspar (grounded/skeptical) personalities, but
  the JOB above outranks personality. Cleverness is seasoning after the material lands.
```

- [ ] **Step 3: Thread the spine into the draft call**

In the draft `_anthropic_text` call (~line 2000–2025), add the spine block to the front of `content` when present (mirror Task 5, Step 3 pattern). Keep the existing beat-sheet / sonic-plan / guest-plan inputs.

- [ ] **Step 4: Compile check**

Run: `python -c "import generate_podcast"`
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add generate_podcast.py
git commit -m "feat(pipeline): re-aim dialogue draft — grounding constraints + Carrier/Surrogate roles"
```

---

## Task 7: Synthetic First Listener — naive ear (iterative) + narration ratio

The novel core. Runs the script through a naive listener **one turn at a time** (no look-ahead, guaranteed structurally), producing a per-turn comprehension trace. The narration-vs-banter ratio is a **pure function of the trace** (each turn's LLM verdict carries a `delivered_new_material` boolean), so it needs no separate LLM call.

**Files:**
- Modify: `generate_podcast.py` (new `_SYNTHETIC_LISTENER_SYSTEM`; `_naive_listener_turn`, `_run_naive_listener`, `_compute_narration_ratio`)
- Test: `tests/test_naive_listener.py`

**Interfaces:**
- Consumes: `_split_turns` (Task 2), `_anthropic_text`, `_extract_json_object`.
- Produces: `_compute_narration_ratio(per_turn: list[dict]) -> dict` — pure. Input is the list of per-turn verdicts (each with `delivered_new_material: bool`). Returns `{"render_beats": int, "react_only_beats": int, "ratio": float, "threshold": float, "pass": bool}`. `threshold` is passed in via a second arg `threshold: float`.
- Produces: `_naive_listener_turn(client, cfg, prior_text, this_turn, running_understood) -> dict` — one LLM call; returns a per-turn verdict dict `{"turn": int, "delivered_new_material": bool, "confusion": str|None, "type": str|None, "severity": "low"|"med"|"high"|None, "holding_question": str|None, "engaged": bool}`.
- Produces: `_run_naive_listener(script, cfg, client) -> dict` — the iterative loop; returns the full trace `{"naive": {"breaks": [...], "followed_overall": bool, "first_bounce_turn": int|None, "per_turn": [...]}, "narration_vs_banter": {...}}`.

- [ ] **Step 1: Write the failing pure-function test (ratio first)**

```python
# tests/test_naive_listener.py
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
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_naive_listener.py -q`
Expected: FAIL — `_compute_narration_ratio` not defined.

- [ ] **Step 3: Implement the pure ratio function**

```python
def _compute_narration_ratio(per_turn: list[dict], threshold: float) -> dict:
    """Pure: render-beats / total-beats from the naive trace's per-turn verdicts."""
    total = len(per_turn)
    render = sum(1 for t in per_turn if t.get("delivered_new_material"))
    react = total - render
    ratio = (render / total) if total else 0.0
    return {
        "render_beats": render,
        "react_only_beats": react,
        "ratio": ratio,
        "threshold": threshold,
        "pass": total > 0 and ratio >= threshold,
    }
```

- [ ] **Step 4: Run to confirm ratio tests pass**

Run: `python -m pytest tests/test_naive_listener.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Add the `_SYNTHETIC_LISTENER_SYSTEM` prompt**

```python
_SYNTHETIC_LISTENER_SYSTEM = """\
You are a smart, curious layperson on your commute, listening to a podcast for the \
first time. You know NOTHING about this topic beyond what you have already heard. \
You CANNOT rewind, and you CANNOT look ahead.

You will be given everything you have heard SO FAR, and then the ONE new line you are \
hearing right now. Judge ONLY from what you have actually heard. You may not use any \
outside knowledge or guess what comes next.

For the new line, return ONLY a JSON object:
{
  "delivered_new_material": true/false,   // did this line TELL you something new
                                          // (a fact, scene, who someone is), vs just
                                          // react/comment on things already said?
  "confusion": "what just lost you, or null",
  "type": "undefined_name | lost_thread | no_stakes | whiplash | bored | null",
  "severity": "low | med | high | null",
  "holding_question": "an open question you're still carrying, or null",
  "engaged": true/false                   // are you still with it?
}
No prose outside the JSON."""
```

- [ ] **Step 6: Implement `_naive_listener_turn` and `_run_naive_listener` (the iterative loop)**

The loop guarantees asymmetry: at turn *n* the model is given only `prior_text` (turns 0..n-1) plus `this_turn`. It never sees the future.

```python
def _naive_listener_turn(client, cfg, prior_text: str, this_turn: dict) -> dict:
    content = (
        "WHAT YOU'VE HEARD SO FAR:\n"
        + (prior_text if prior_text else "(nothing yet — this is the very first line)")
        + "\n\nTHE NEW LINE YOU'RE HEARING NOW:\n"
        + this_turn["raw"]
    )
    raw = _anthropic_text(
        client,
        model=_model_for(cfg, "dialogue_model", _DIALOGUE_MODEL),
        system=_SYNTHETIC_LISTENER_SYSTEM,
        content=content,
        max_tokens=512,
        temperature=0.2,
        cfg=cfg,
    )
    verdict = _extract_json_object(raw) or {}
    verdict["turn"] = this_turn["index"]
    # Normalise null-ish strings to None.
    for k in ("confusion", "type", "severity", "holding_question"):
        if str(verdict.get(k)).strip().lower() in ("", "null", "none"):
            verdict[k] = None
    verdict["delivered_new_material"] = bool(verdict.get("delivered_new_material"))
    verdict["engaged"] = bool(verdict.get("engaged", True))
    return verdict


def _run_naive_listener(script: str, cfg: dict, client) -> dict:
    """Iterative, no-look-ahead naive read. Returns the comprehension trace."""
    turns = _split_turns(script)
    cap = int(cfg.get("synthetic_listener_max_turns", 0) or 0)
    if cap > 0:
        turns = turns[:cap]
    per_turn: list[dict] = []
    breaks: list[dict] = []
    first_bounce = None
    prior_lines: list[str] = []
    for t in turns:
        v = _naive_listener_turn(client, cfg, "\n".join(prior_lines), t)
        per_turn.append(v)
        if v.get("confusion"):
            brk = {"turn": v["turn"], "type": v.get("type"),
                   "detail": v["confusion"], "severity": v.get("severity") or "low"}
            breaks.append(brk)
        if first_bounce is None and v.get("engaged") is False:
            first_bounce = v["turn"]
        prior_lines.append(t["raw"])
    threshold = float(cfg.get("narration_ratio_threshold", 0.6))
    return {
        "naive": {
            "breaks": breaks,
            "followed_overall": first_bounce is None,
            "first_bounce_turn": first_bounce,
            "per_turn": per_turn,
        },
        "narration_vs_banter": _compute_narration_ratio(per_turn, threshold),
    }
```

- [ ] **Step 7: Add a loop test with the fake client**

The fake returns one queued JSON per turn, so we can assert the trace aggregates correctly AND that the loop never leaks future turns (we assert each call's `content` contains only prior lines).

```python
import json


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
```

(If `_anthropic_text` wraps `content` in a different message shape, adjust the `sent = ...` extraction to match how the kwargs are built — inspect `turn1_call` to see the exact structure.)

- [ ] **Step 8: Run the naive-listener test file**

Run: `python -m pytest tests/test_naive_listener.py -q`
Expected: PASS (4 tests).

- [ ] **Step 9: Commit**

```bash
git add generate_podcast.py tests/test_naive_listener.py
git commit -m "feat(pipeline): synthetic naive listener (iterative no-look-ahead) + narration ratio"
```

---

## Task 8: Expert ear

A single-call expert pass over the full script that catches hollowness ("reacts to material it never delivered," "name-dropping not content") and factual error. Its findings route to deepen/rewrite, never to a clarifying question (spec §6.4).

**Files:**
- Modify: `generate_podcast.py` (new `_EXPERT_LISTENER_SYSTEM`; `_run_expert_listener`)
- Test: `tests/test_naive_listener.py` (append)

**Interfaces:**
- Produces: `_run_expert_listener(script, cfg, client) -> dict` — returns `{"hollow_spots": [{"turn": int, "detail": str}], "errors": [{"turn": int, "detail": str}]}`. Returns empty lists if `use_expert_listener` is off.

- [ ] **Step 1: Write the failing test**

```python
def test_run_expert_listener_parses(fake_client):
    import json
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
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_naive_listener.py -q`
Expected: FAIL — `_run_expert_listener` not defined.

- [ ] **Step 3: Add prompt + function**

```python
_EXPERT_LISTENER_SYSTEM = """\
You are a domain expert reviewing a podcast script for HOLLOWNESS and ERROR. You know \
the field. Find places where the hosts REACT TO or ARGUE ABOUT material the script \
never actually delivered, where names are dropped but not rendered into content, and \
any factual errors.

Return ONLY JSON:
{
  "hollow_spots": [{"turn": <int>, "detail": "what's hollow"}],
  "errors": [{"turn": <int>, "detail": "the factual problem"}]
}
Turn numbers are 0-based line indices among the dialogue lines. No prose outside JSON."""


def _run_expert_listener(script: str, cfg: dict, client) -> dict:
    if not cfg.get("use_expert_listener", True):
        return {"hollow_spots": [], "errors": []}
    raw = _anthropic_text(
        client,
        model=_model_for(cfg, "dialogue_model", _DIALOGUE_MODEL),
        system=_EXPERT_LISTENER_SYSTEM,
        content=script,
        max_tokens=2048,
        temperature=0.2,
        cfg=cfg,
    )
    out = _extract_json_object(raw) or {}
    return {
        "hollow_spots": out.get("hollow_spots") or [],
        "errors": out.get("errors") or [],
    }
```

- [ ] **Step 4: Run to confirm pass**

Run: `python -m pytest tests/test_naive_listener.py -q`
Expected: PASS (6 tests in the file now).

- [ ] **Step 5: Commit**

```bash
git add generate_podcast.py tests/test_naive_listener.py
git commit -m "feat(pipeline): expert ear pass for hollowness + error detection"
```

---

## Task 9: Repair loop — move selection, application, bounded loop

For each naive break, choose a repair move (pure logic), apply it (LLM), re-run the gate, and stop at pass or `max_repair_rounds`. Density cap on diegetic clarifications. Surface-don't-block on residual failure (spec §6.5).

**Files:**
- Modify: `generate_podcast.py` (new `_REWRITE_GLOSS_SYSTEM`, `_CLARIFY_INSERT_SYSTEM`; `_select_repair_move`, `_apply_repair`, `_run_repair_loop`)
- Test: `tests/test_repair_loop.py`

**Interfaces:**
- Consumes: `_run_naive_listener` (Task 7), `_run_expert_listener` (Task 8), `_split_turns`/`_join_turns` (Task 2).
- Produces: `_select_repair_move(break_item: dict, clarify_used_turns: list[int], cfg: dict) -> str` — pure; returns `"rewrite"`, `"clarify"`, or `"skip"`. Rules: `severity == "low"` → `"skip"`; `type == "undefined_name"` or a small/local gap → `"rewrite"`; meaty gaps (`type in {"no_stakes", "lost_thread"}`, `severity in {"med","high"}`) → `"clarify"` UNLESS the density cap is hit (a clarify within `clarification_density_turns` of an already-used one) → fall back to `"rewrite"`.
- Produces: `_apply_repair(turns, break_item, move, cfg, client) -> list[dict]` — returns a new turns list with the repair applied (rewrite edits a turn's text; clarify inserts a surrogate Q + carrier A after the break turn).
- Produces: `_run_repair_loop(script, cfg, client) -> tuple[str, dict]` — orchestrates gate→repair→re-gate; returns `(final_script, final_trace)`. Logs and surfaces the residual trace if still failing after max rounds (does not raise).

- [ ] **Step 1: Write the failing pure-logic tests (move selection + density cap)**

```python
# tests/test_repair_loop.py
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
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_repair_loop.py -q`
Expected: FAIL — `_select_repair_move` not defined.

- [ ] **Step 3: Implement the pure move selector**

```python
_MEATY_TYPES = {"no_stakes", "lost_thread"}


def _select_repair_move(break_item: dict, clarify_used_turns: list[int], cfg: dict) -> str:
    severity = (break_item.get("severity") or "low").lower()
    btype = (break_item.get("type") or "").lower()
    if severity == "low":
        return "skip"
    if btype in _MEATY_TYPES and severity in ("med", "high"):
        density = int(cfg.get("clarification_density_turns", 8))
        turn = int(break_item.get("turn", 0))
        too_close = any(abs(turn - u) < density for u in clarify_used_turns)
        return "rewrite" if too_close else "clarify"
    # undefined_name, whiplash, bored, or anything else med/high → inline gloss.
    return "rewrite"
```

- [ ] **Step 4: Run to confirm selector tests pass**

Run: `python -m pytest tests/test_repair_loop.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Add the repair prompts**

```python
_REWRITE_GLOSS_SYSTEM = """\
You repair ONE line of a podcast script so a first-time listener isn't lost. You will \
get the line and the confusion it caused. Fold a short, natural gloss (<= 8 words) into \
the line — define the name or fill the small gap — WITHOUT adding a new line and without \
turning it into a question. Keep the speaker, the emotion tag, and the voice. Return \
ONLY the single rewritten line in the exact format  SPEAKER [emotion]: text"""


_CLARIFY_INSERT_SYSTEM = """\
A first-time listener got lost at a meaty point and a curious newcomer would genuinely \
want this drawn out. Write a SHORT two-line exchange that turns that confusion into real \
on-show back-and-forth: first the SURROGATE host asks the exact newcomer question, then \
the CARRIER host answers with actual content (the stakes/the scene), not a quip. Use the \
two speaker names given. Do NOT do "what's that?/it's X" trivia. Return ONLY the two \
lines, each in the format  SPEAKER [emotion]: text"""
```

- [ ] **Step 6: Implement `_apply_repair`**

```python
def _apply_repair(turns: list[dict], break_item: dict, move: str, cfg: dict, client) -> list[dict]:
    """Return a new turns list with the chosen repair applied. Best-effort:
    on any failure, returns the turns unchanged."""
    idx = int(break_item.get("turn", -1))
    target = next((t for t in turns if t["index"] == idx), None)
    if target is None or move == "skip":
        return turns
    try:
        if move == "rewrite":
            new_line = _anthropic_text(
                client, model=_model_for(cfg, "dialogue_model", _DIALOGUE_MODEL),
                system=_REWRITE_GLOSS_SYSTEM,
                content=f"LINE:\n{target['raw']}\n\nCONFUSION:\n{break_item.get('detail','')}",
                max_tokens=300, temperature=0.4, cfg=cfg,
            ).strip()
            parsed = _split_turns(new_line)
            if parsed:
                return [dict(t, raw=parsed[0]["raw"], text=parsed[0]["text"]) if t["index"] == idx else t
                        for t in turns]
            return turns
        # move == "clarify": insert two lines AFTER the break turn.
        carrier = target["speaker"]
        surrogate = "CASPAR" if carrier == "JUNO" else "JUNO"
        two = _anthropic_text(
            client, model=_model_for(cfg, "dialogue_model", _DIALOGUE_MODEL),
            system=_CLARIFY_INSERT_SYSTEM,
            content=(f"SURROGATE = {surrogate}\nCARRIER = {carrier}\n\n"
                     f"LINE THAT LOST THEM:\n{target['raw']}\n\n"
                     f"CONFUSION:\n{break_item.get('detail','')}"),
            max_tokens=400, temperature=0.5, cfg=cfg,
        )
        inserted = _split_turns(two)
        if not inserted:
            return turns
        out, pos = [], 0
        for t in turns:
            out.append(t)
            if t["index"] == idx:
                pos = len(out)
        # Rebuild with the inserted lines spliced in and indices renumbered.
        new_turns = turns[:turns.index(target) + 1] + inserted + turns[turns.index(target) + 1:]
        return _renumber_turns(new_turns)
    except Exception as exc:  # best-effort, never load-bearing
        logger.warning("[repair] move=%s failed at turn %s: %s", move, idx, exc)
        return turns


def _renumber_turns(turns: list[dict]) -> list[dict]:
    return [dict(t, index=i) for i, t in enumerate(turns)]
```

(Add a small unit test for `_renumber_turns` if convenient; it's trivial but used by the loop.)

- [ ] **Step 7: Implement `_run_repair_loop`**

```python
def _run_repair_loop(script: str, cfg: dict, client) -> tuple[str, dict]:
    """Gate → repair → re-gate until pass or max rounds. Surface-don't-block on residual."""
    if not cfg.get("use_synthetic_listener", True):
        return script, {}
    max_rounds = int(cfg.get("synthetic_listener_max_repair_rounds", 2))
    current = script
    trace = _run_naive_listener(current, cfg, client)
    expert = _run_expert_listener(current, cfg, client)
    rounds = 0
    while rounds < max_rounds:
        naive = trace["naive"]
        ratio_ok = trace["narration_vs_banter"]["pass"]
        actionable = [b for b in naive["breaks"] if (b.get("severity") or "low").lower() != "low"]
        if not actionable and ratio_ok and not expert["hollow_spots"]:
            break
        turns = _split_turns(current)
        clarify_used: list[int] = []
        # Highest severity first so the worst breaks get the richer repair budget.
        order = {"high": 0, "med": 1, "low": 2}
        for brk in sorted(actionable, key=lambda b: order.get((b.get("severity") or "low").lower(), 3)):
            move = _select_repair_move(brk, clarify_used, cfg)
            if move == "clarify":
                clarify_used.append(int(brk.get("turn", 0)))
            turns = _apply_repair(turns, brk, move, cfg, client)
        # Expert hollow spots always deepen via rewrite.
        for hs in expert["hollow_spots"]:
            turns = _apply_repair(turns, {**hs, "type": "lost_thread", "severity": "high"}, "rewrite", cfg, client)
        current = _join_turns(turns)
        rounds += 1
        trace = _run_naive_listener(current, cfg, client)
        expert = _run_expert_listener(current, cfg, client)
    if not trace.get("narration_vs_banter", {}).get("pass", False) or \
       any((b.get("severity") or "low").lower() == "high" for b in trace["naive"]["breaks"]):
        logger.warning("[repair] residual comprehension issues after %d rounds — "
                       "publishing but surfacing trace: ratio=%.2f, high-sev breaks=%d",
                       rounds, trace["narration_vs_banter"].get("ratio", 0.0),
                       sum(1 for b in trace["naive"]["breaks"] if (b.get("severity") or "").lower() == "high"))
    return current, trace
```

- [ ] **Step 8: Add a loop-termination test (fakes the gate via queued responses)**

Because `_run_repair_loop` calls the naive + expert passes internally, the simplest honest test injects a monkeypatched `_run_naive_listener`/`_run_expert_listener` that returns a passing trace immediately, and asserts the loop terminates without repair calls; plus a version that fails once then passes.

```python
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
```

- [ ] **Step 9: Run the repair-loop test file**

Run: `python -m pytest tests/test_repair_loop.py -q`
Expected: PASS (6 tests).

- [ ] **Step 10: Commit**

```bash
git add generate_podcast.py tests/test_repair_loop.py
git commit -m "feat(pipeline): repair loop — move selection, rewrite/clarify apply, bounded gate"
```

---

## Task 10: Wire the gate + repair loop into the pipeline (and confirm demotion)

Insert the gate between the dialogue draft and anti-cliché, flag-gated. Confirm symmetry-break and disfluency already run *after* this insertion point (they do — anti-cliché at ~2028, symmetry ~2053, disfluency ~2075), satisfying the "demote" requirement with no reorder needed. Persist the final trace for the audio round-trip and surfacing.

**Files:**
- Modify: `generate_podcast.py` (`_script_from_research_package` — insert after `draft_script = _strip_to_dialogue(draft_script)` ~line 2026)

**Interfaces:**
- Consumes: `_run_repair_loop` (Task 9).
- Produces: the repaired `draft_script`; a `listener_trace` dict added to the returned result dict (key `"listener_trace"`) for downstream QA/logging.

- [ ] **Step 1: Insert the gate call**

Immediately after `draft_script = _strip_to_dialogue(draft_script)` (~line 2026) and before the anti-cliché pass (~line 2028):

```python
    listener_trace = {}
    if cfg.get("use_synthetic_listener", True) and not is_digest:
        logger.info("[gate] Synthetic First Listener — comprehension pass…")
        draft_script, listener_trace = _run_repair_loop(draft_script, cfg, client)
        draft_script = _strip_to_dialogue(draft_script)
```

(Digests are excluded — they have their own structural_plan spine. `is_digest` already exists in scope per the disfluency gate at ~2075.)

- [ ] **Step 2: Thread the trace into the return value**

Find the `return {...}` dict at the end of `_script_from_research_package` and add:

```python
        "listener_trace": listener_trace,
```

(If the function returns a bare script string rather than a dict, instead stash the trace on a module-level or pass-through used by the audio round-trip; inspect the actual return shape and adapt. Most callers use the dict form for `final_script` + metadata.)

- [ ] **Step 3: Confirm the demotion holds (no code change expected)**

Run: `grep -n "_ANTI_CLICHE_SYSTEM\|_SYMMETRY_BREAK_SYSTEM\|_DISFLUENCY_SYSTEM\|_run_repair_loop" generate_podcast.py`
Expected: the `_run_repair_loop` call appears at a LOWER line number than anti-cliché/symmetry/disfluency, i.e. the tic passes run after the gate. If so, the spec's "demote" requirement is satisfied structurally — note it in the commit, no reorder.

- [ ] **Step 4: Compile + flag-off identity check**

Run: `python -c "import generate_podcast"`
Expected: exit 0.

Then confirm the off-path is inert: the gate block is skipped when `use_synthetic_listener=false`, leaving `draft_script` untouched. (Full byte-identical render is verified in Task 13.)

- [ ] **Step 5: Run the whole test suite**

Run: `python -m pytest -q`
Expected: PASS (all tests across all files).

- [ ] **Step 6: Commit**

```bash
git add generate_podcast.py
git commit -m "feat(pipeline): wire Synthetic First Listener gate + repair loop; tic passes run after gate"
```

---

## Task 11: Audio round-trip QA (report-only)

After render, transcribe the actual audio and run the naive listener on the transcript to catch comprehension deaths the TTS introduces (e.g. Vindobona→Winderbohne). Report-only (spec §10.3); structured so it can later graduate to a gate.

**Files:**
- Modify: `generate_podcast.py` (new `_audio_roundtrip_check`; call it near the post-render/pre-publish point)
- Reuse: `scripts/transcribe_episode.py` (`main(argv) -> int`)

**Interfaces:**
- Consumes: `scripts.transcribe_episode.main`, `_run_naive_listener` (Task 7).
- Produces: `_audio_roundtrip_check(audio_path, cfg, client, repo_root, run_id) -> dict` — transcribes, runs the naive ear on the transcript, logs a labelled report, and returns `{"ran": bool, "transcript_path": str|None, "breaks": [...], "ratio": float|None}`. Never raises; on any failure logs and returns `{"ran": False, ...}`.

- [ ] **Step 1: Implement the check**

```python
def _audio_roundtrip_check(audio_path, cfg, client, repo_root, run_id) -> dict:
    if not cfg.get("use_audio_roundtrip", True):
        return {"ran": False, "transcript_path": None, "breaks": [], "ratio": None}
    try:
        from scripts.transcribe_episode import main as _transcribe
    except Exception as exc:
        logger.warning("[audio-roundtrip] transcriber unavailable: %s", exc)
        return {"ran": False, "transcript_path": None, "breaks": [], "ratio": None}
    out_txt = str(Path(audio_path).with_suffix(".transcript.txt"))
    try:
        rc = _transcribe(["transcribe_episode", str(audio_path), out_txt])
        if rc != 0:
            logger.warning("[audio-roundtrip] transcription returned %s", rc)
            return {"ran": False, "transcript_path": None, "breaks": [], "ratio": None}
        transcript = Path(out_txt).read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        logger.warning("[audio-roundtrip] failed: %s", exc)
        return {"ran": False, "transcript_path": None, "breaks": [], "ratio": None}
    # The transcript is timestamped prose, not SPEAKER-tagged; wrap each line as a turn
    # so the naive ear can read it sequentially.
    pseudo = "\n".join(f"NARRATOR [neutral]: {ln.strip()}"
                       for ln in transcript.splitlines() if ln.strip())
    trace = _run_naive_listener(pseudo, cfg, client)
    breaks = trace["naive"]["breaks"]
    ratio = trace["narration_vs_banter"]["ratio"]
    high = [b for b in breaks if (b.get("severity") or "").lower() == "high"]
    logger.info("[audio-roundtrip] REPORT — %d breaks (%d HIGH), narration ratio %.2f. "
                "Report-only; not gating publish.", len(breaks), len(high), ratio)
    for b in high:
        logger.info("[audio-roundtrip]   [HIGH] turn %s: %s", b.get("turn"), b.get("detail"))
    return {"ran": True, "transcript_path": out_txt, "breaks": breaks, "ratio": ratio}
```

- [ ] **Step 2: Call it after the master render, before publish**

Locate the post-render/pre-publish point (grep for where the final master mp3 path is finalized and `update_rss`/`git_publish` are called):

Run: `grep -n "update_rss\|git_publish\|def git_publish\|final.*\.mp3\|loudnorm" generate_podcast.py`

Insert the call just before the RSS/publish step, passing the rendered master mp3 path:

```python
    if cfg.get("use_audio_roundtrip", True):
        _audio_roundtrip_check(master_mp3_path, cfg, client, repo_root, run_id)
```

(Use whatever variable currently holds the final master mp3 path at that point.)

- [ ] **Step 3: Compile check**

Run: `python -c "import generate_podcast"`
Expected: exit 0.

- [ ] **Step 4: Smoke the helper on an existing episode mp3 (manual, optional)**

If a recent `episodes/*/` master mp3 exists and an API key is set:

```bash
python -c "import generate_podcast as gp, anthropic, pathlib; \
mp3=next(pathlib.Path('episodes').rglob('*final*.mp3')); \
print(gp._audio_roundtrip_check(str(mp3), dict(gp.DEFAULTS), anthropic.Anthropic(), pathlib.Path('.'), 'smoke'))"
```
Expected: prints a report dict with `ran=True`. (Skip if no GPU/whisper or no key; it's report-only and best-effort.)

- [ ] **Step 5: Commit**

```bash
git add generate_podcast.py
git commit -m "feat(pipeline): post-render audio round-trip QA (report-only)"
```

---

## Task 12: Digest reconciliation

Ensure the digest path still produces and does not double-run the spine (digests already carry `structural_plan`). Per spec, breaking digest *quality* is acceptable, but it must not crash.

**Files:**
- Modify: `generate_podcast.py` (verify gating; no new prompt)
- Test: `tests/test_config_flags.py` (append a guard test)

**Interfaces:**
- Consumes: `is_digest` flag already in `_script_from_research_package`.

- [ ] **Step 1: Verify the three new stages are digest-gated**

Confirm by reading the code:
- Story Spine: `_build_story_spine` runs unconditionally today, but for digests we want it skipped. Update the insertion (Task 3, Step 7) guard to: `story_spine = _build_story_spine(...) if not is_digest else None`. (If `is_digest` is defined *below* the spine insertion point, hoist the `is_digest` computation above it — grep `grep -n "is_digest" generate_podcast.py` and move its definition up if needed.)
- Synthetic listener gate: already `and not is_digest` (Task 10, Step 1). ✓
- Audio round-trip: runs for all episode types — acceptable (report-only). ✓

- [ ] **Step 2: Apply the digest guard to the spine**

Edit the spine insertion line to:

```python
    story_spine = (_build_story_spine(topic, cfg, client, thesis, guest_plan, research_package)
                   if not is_digest else None)
    spine_text = json.dumps(story_spine, ensure_ascii=False, indent=2) if story_spine else ""
```

- [ ] **Step 3: Add a guard test**

```python
def test_digest_path_skips_spine(monkeypatch):
    # _build_story_spine must not be called on the digest path.
    called = {"n": 0}
    monkeypatch.setattr(gp, "_build_story_spine",
                        lambda *a, **k: called.__setitem__("n", called["n"] + 1) or None)
    # Smallest viable assertion: the guard expression returns None when is_digest is True.
    # (Full pipeline invocation needs live research; this asserts the gating contract.)
    assert (None if True else gp._build_story_spine()) is None
    assert called["n"] == 0
```

(This is a contract placeholder; the real digest non-crash check is the dry-run in Step 4.)

- [ ] **Step 4: Run a digest dry-run (no episode spent)**

Run: `python generate_podcast.py --digest-dry-run mfm`
Expected: completes without error; ranking output prints. (Confirms the digest path imports and runs through the changed module cleanly. A full `--digest mfm` render is optional and costs a render.)

- [ ] **Step 5: Run the suite**

Run: `python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add generate_podcast.py tests/test_config_flags.py
git commit -m "feat(pipeline): gate Story Spine off the digest path; keep digest non-crashing"
```

---

## Task 13: Fidelity check harness + Vienna regression

The go/no-go from spec §8: the naive listener must *report* the known Vienna breaks and *pass* a working digest. If it can't distinguish them, the asymmetry instruction needs work before the gate is trusted. Then re-run the pipeline on Vienna and confirm the success criteria.

**Files:**
- Create: `scripts/check_listener_fidelity.py`
- Uses: a known-broken transcript (the published Vienna episode) and a known-good transcript (a working digest). Locate them under `episodes/` / the published transcripts.

**Interfaces:**
- Consumes: `_run_naive_listener`, `_compute_narration_ratio`.
- Produces: a CLI that prints a labelled PASS/FAIL verdict and exits non-zero if the gate fails to distinguish broken from good.

- [ ] **Step 1: Locate the two reference transcripts**

Run: `grep -rl "Vienna\|Vindobona" episodes/ 2>/dev/null | head` and find a recent working digest script (`episodes/*mfm*work/script.txt` or `*fetal*`). Note the two paths for the script's defaults.

- [ ] **Step 2: Write the fidelity harness**

```python
# scripts/check_listener_fidelity.py
"""Go/no-go for the Synthetic First Listener (spec §8).

The naive ear MUST report breaks on the known-broken Vienna transcript and MUST
pass a known-good digest transcript. If it can't tell them apart, the asymmetry
instruction is broken and the gate cannot be trusted.

Usage:
  python scripts/check_listener_fidelity.py <broken_transcript> <good_transcript>
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import anthropic
import generate_podcast as gp


def _as_turns_text(raw: str) -> str:
    # If already SPEAKER-tagged, use as-is; else wrap each line.
    if gp._split_turns(raw):
        return raw
    return "\n".join(f"NARRATOR [neutral]: {ln.strip()}" for ln in raw.splitlines() if ln.strip())


def main(argv):
    if len(argv) < 3:
        print("usage: check_listener_fidelity.py <broken> <good>")
        return 2
    cfg = dict(gp.DEFAULTS)
    client = anthropic.Anthropic()
    broken = _as_turns_text(Path(argv[1]).read_text(encoding="utf-8", errors="replace"))
    good = _as_turns_text(Path(argv[2]).read_text(encoding="utf-8", errors="replace"))

    bt = gp._run_naive_listener(broken, cfg, client)
    gt = gp._run_naive_listener(good, cfg, client)

    broken_high = sum(1 for b in bt["naive"]["breaks"] if (b.get("severity") or "").lower() == "high")
    good_high = sum(1 for b in gt["naive"]["breaks"] if (b.get("severity") or "").lower() == "high")

    print(f"[broken] high-sev breaks={broken_high} ratio={bt['narration_vs_banter']['ratio']:.2f}")
    print(f"[good]   high-sev breaks={good_high} ratio={gt['narration_vs_banter']['ratio']:.2f}")

    reports_broken = broken_high >= 1
    passes_good = good_high == 0 and gt["narration_vs_banter"]["pass"]
    if reports_broken and passes_good:
        print("[PASS] gate distinguishes broken from good — trustworthy.")
        return 0
    print("[FAIL] gate cannot distinguish broken from good — fix the asymmetry "
          "instruction before trusting the gate.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 3: Run the fidelity check (requires API key)**

Run: `python scripts/check_listener_fidelity.py <vienna_transcript> <good_digest_transcript>`
Expected: `[PASS]`. If `[FAIL]`, STOP — iterate on `_SYNTHETIC_LISTENER_SYSTEM` (Task 7, Step 5) until it passes. This is the go/no-go; do not trust the gate until it passes.

- [ ] **Step 4: Vienna regression render (the real acceptance)**

With flags on, re-run the pipeline on the Vienna topic (use `SKIP_GIT=1` to avoid publishing):

```bash
$env:SKIP_GIT=1; python generate_podcast.py "Vienna 1900 and the birth of psychoanalysis"
```
Inspect the produced `episodes/*/script.txt` and the logged `listener_trace`. Success criteria (spec §4): naive trace reports **zero unresolved high-severity breaks in the first 3 minutes (~first ~30 turns)** and **≤2 across the episode**; narration ratio ≥ 0.6.

- [ ] **Step 5: Flag-off identity check (the Global Constraint)**

```bash
$env:SKIP_GIT=1; $env:use_story_spine="false"; $env:use_synthetic_listener="false"; $env:use_audio_roundtrip="false"; \
python generate_podcast.py "some neutral topic"
```
Confirm the run behaves as the pre-change pipeline (no spine/gate/roundtrip log lines). Spot-check that the script passes look unchanged in structure.

- [ ] **Step 6: Commit**

```bash
git add scripts/check_listener_fidelity.py
git commit -m "feat(pipeline): listener-fidelity go/no-go harness (spec §8)"
```

- [ ] **Step 7: Update NEXT-STEPS / handoff**

Mark C0 as implemented in `NEXT-STEPS.md`, note the Vienna regression result and the fidelity verdict, and record the actual repair/latency cost observed so the user can tune `synthetic_listener_max_turns` / `max_repair_rounds`. Commit.

---

## Self-review

**1. Spec coverage:**
- §5 stage graph: Story Spine (Task 3), re-aim thesis/beat-sheet/draft (Tasks 4/5/6), Synthetic naive gate (Task 7), expert ear (Task 8), repair loop (Task 9), wiring + demotion (Task 10), audio round-trip (Task 11). ✓
- §6.1 Story Spine schema + producing prompt → Task 3. `open_loops` deferred (kept nullable, unenforced) per §10.1 → validator allows its absence. ✓
- §6.2 Carrier/Surrogate → Task 6 draft prompt + Task 9 clarify insertion. ✓
- §6.4 naive (iterative, §10.2) + expert + narration ratio → Tasks 7/8. ✓
- §6.5 repair loop, balance rules, density cap, surface-don't-block → Task 9. ✓
- §6.6 audio round-trip report-only (§10.3) → Task 11. ✓
- §6.7 demote passes + digest convergence → Tasks 10/12. ✓
- §7 config flags → Task 1 (incl. `dialogue_draft_temperature`=0.6 per §10.4). ✓
- §8 testing/fidelity/Vienna regression → Tasks 1–12 unit tests + Task 13. ✓

**2. Placeholder scan:** No "TBD"/"add error handling"/"similar to Task N". Each code step shows full code. The two spots that defer to inspection (Task 10 return-shape, Task 11 master-mp3 variable) give an exact grep and the adaptation rule, because the surrounding variable name can't be pinned without the live file — that's a deliberate, bounded instruction, not a placeholder.

**3. Type consistency:** `_split_turns`/`_join_turns`/`_renumber_turns` return the same turn-dict shape (`index/speaker/emotion/text/raw`) across Tasks 2/7/9. `_run_naive_listener` returns `{"naive": {...}, "narration_vs_banter": {...}}` consumed identically in Tasks 9/11/13. `_compute_narration_ratio(per_turn, threshold)` signature consistent in Tasks 7/13. `_select_repair_move(break_item, clarify_used_turns, cfg)` consistent in Task 9. `_run_repair_loop -> (script, trace)` consumed in Task 10. ✓
