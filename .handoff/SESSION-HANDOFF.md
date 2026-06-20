# Session hand-off — 2026-06-20 (machine: laptop)

## STATE (read this first)
- Branch: `main`, clean and **pushed** (synced — desktop can pull immediately).
- This was a **planning session** that turned the C0 redesign spec into an executable
  implementation plan. The payload is on disk:
  **`docs/superpowers/plans/2026-06-20-narration-first-pipeline.md`** — **read that next.**
  It's a 13-task TDD plan; with the spec, it's a complete durable handoff (a fresh
  session needs only those two files).
- The 4 open questions in spec §10 are **RESOLVED** and baked into both the spec and the
  plan. No decisions are pending for C0.
- Two `audio-scope-*` dirs remain untracked **on purpose** — never commit them.

## Done this session
- **Answered spec §10's 4 open questions** and recorded them in the spec (§10 + the
  in-body sections that referenced them, so the doc is internally consistent):
  - Q1 `open_loops` / curiosity-gap → **DEFER** (keep nullable schema slot, don't produce/consume yet).
  - Q2 naive listener → **ITERATIVE turn-by-turn** (feed turns 1..n only; no-look-ahead
    guaranteed *structurally*, not by a prompt instruction the model could violate).
  - Q3 audio round-trip → **REPORT-ONLY** (post-render health check; a gate would force costly re-renders).
  - Q4 draft temperature → **LOWER 0.75 → 0.6 via config** (`dialogue_draft_temperature`), gate as backstop.
- **Wrote the implementation plan** (`writing-plans`, committed `1872367`). 13 ordered TDD
  tasks. Two structural decisions worth knowing:
  - **Story Spine inserts BEFORE the beat-sheet** (a code-survey subagent initially
    suggested after; the spec is authoritative — the beat-sheet must *consume* the spine).
  - **All quantitative logic factored into PURE functions** (narration ratio, repair-move
    selection, density cap, loop termination, schema validation) so it gets real pytest
    unit tests with a hand-rolled fake Anthropic client. The repo had **zero** test infra;
    Task 1 stands up `pytest.ini` + `tests/conftest.py`. LLM stages get mocked-client
    plumbing tests + a manual smoke/fidelity check (the only honest way to TDD a live-API pipeline).
- Surveyed the real pipeline code (via an Explore subagent) so every task references exact
  function names, signatures, and insertion line numbers in `generate_podcast.py`.

## Next up
1. **Execute the plan** — `docs/superpowers/plans/2026-06-20-narration-first-pipeline.md`.
   **Subagent-driven execution recommended** (fresh subagent per task + review between).
   **Recommend a FRESH session** to execute — this one is heavy (pick-up + full spec read +
   code survey + plan authoring).
2. Task order is leverage-first: 1 config+harness+draft-temp → 2 turn parser → 3 Story Spine
   → 4-6 re-aim thesis/beat-sheet/draft → 7-9 naive/expert/repair loop → 10 wire the gate →
   11 audio round-trip → 12 digest non-crash → 13 §8 fidelity go/no-go + Vienna regression.
3. **Run the verification steps on the DESKTOP:** Tasks 4, 11, 13 need a live Anthropic API
   key, and Task 11's audio round-trip wants the GPU/whisper path. The laptop can do the
   pure-logic tasks (1-3, 5-10 unit tests) but the smoke renders + fidelity check want the desktop.

## Watch out for
- **Task 13 is the go/no-go.** Before trusting the gate, the fidelity harness must *report*
  the known Vienna breaks AND *pass* a working digest transcript. If it can't tell them
  apart, fix the asymmetry instruction in `_SYNTHETIC_LISTENER_SYSTEM` (Task 7) before
  relying on the gate. Don't skip this.
- **Cost/latency of the iterative naive ear:** one LLM call per turn (~78 turns) × up to
  2 repair rounds ≈ a few hundred calls per episode. Acceptable by design ("Asynchronous"),
  but the plan adds `synthetic_listener_max_turns` (0 = no cap) and `max_repair_rounds` (2)
  knobs — tune them after seeing the real cost on the first Vienna render.
- **Two plan steps defer to live-file inspection** (Task 10 return-shape of
  `_script_from_research_package`; Task 11 the master-mp3 variable name) — each gives an
  exact grep + the adaptation rule. These are bounded, not placeholders; just confirm the
  variable names when you get there.
- **`config.json` overrides DEFAULTS** — the new flags (`use_story_spine`,
  `use_synthetic_listener`, `narration_ratio_threshold`, `dialogue_draft_temperature`, etc.)
  must be checked there if they "aren't taking."
- **Flags-off must stay byte-identical** — a hard acceptance gate on every wiring task
  (10, 11) and verified in Task 13 Step 5.
- **Older pending items still open** (not C0): `.handoff/PENDING-DECISIONS.md` — re-enable
  sonic footnotes (needs an ear-check render) + wire `anti_slop.py` (gate vs warn). Lower
  priority than C0.
- Standing TODO (unchanged): rotate the leaked `@AsynchronousPodBot` Telegram token via
  BotFather `/revoke` when next at the home machine; git history verified clean.
- Two audio-scope dirs untracked on purpose — never commit.
