# Session hand-off — 2026-06-20 (machine: laptop)

## STATE (read this first)
- Branch: `main`, clean and **pushed** (synced — desktop can pull immediately).
- This was a **design session** for the C0 prompt surgery. Outcome: a full,
  research-grounded redesign spec is on disk and committed —
  **`docs/superpowers/specs/2026-06-20-narration-first-pipeline-design.md`** — **read that next, it's the payload.**
- **The big correction:** the diagnosis doc was wrong that "there's no beat-sheet step."
  The pipeline already implements nearly the entire script chain (thesis → beat-sheet →
  guest-plan → draft → anti-cliché → symmetry → disfluency → fact-check → callback →
  performance). The failure is **mis-aimed prompts + a missing substance gate**, not
  missing stages. So the work is RE-AIM, not rebuild.
- **Decision made:** salvage the existing chain (it's field-validated), take the fuller
  swing (Option B). Do NOT rebuild from zero. The digest shows are the in-house proof
  that the same plumbing produces followable output when given a structural spine.
- Two `audio-scope-*` dirs remain untracked **on purpose** — never commit them.

## Done this session
- **Landscape review** (deep-research workflow, 22 sources, 25 claims adversarially
  verified). Key confirmed findings: multi-stage chains are the field standard (our arch
  is sound); the narration-vs-banter fix is upstream grounding constraints in the prompt
  (MoonCast/NotebookLM); **compliance ≠ substance** (PodBench: 96.6 instruction-following
  vs 63.3 content quality — a style chain can pass every stage and stay hollow); engagement
  lives in the script weighted to substance (45) > narrative (30) > naturalness (25), so our
  disfluency/symmetry investment polishes the cheapest dimension. Full report archived in
  the session transcript (workflow `wf_b6ea3cf7-312`).
- **Wrote the design spec** (committed `3f6b028`). Narration-first redesign: keep ~70%,
  re-aim 3 prompts (thesis/beat-sheet/draft for establish-before-adjudicate + define-every-name +
  one-scene-per-segment), add 3 stages — **Story Spine** (first-class artifact, generalizes the
  digest's `structural_plan`), **Synthetic First Listener** comprehension gate, **audio round-trip** QA.
- **The novel idea — the Synthetic First Listener ("rewindless ear").** Every field evaluator
  judges the script *with the source in hand*, so it can never feel lost — structurally blind to
  newcomer confusion. We exploit information asymmetry: feed a naive-layperson agent the script
  one turn at a time, no look-ahead, no research; it emits a per-turn comprehension trace (where a
  name was undefined, where it lost the thread, where it checked out). Plus an expert ear for
  hollowness, plus a narration-vs-banter ratio metric.
- **User's key refinement (the heart of §6.5):** when the trace flags a gap, the repair step
  CHOOSES — rewrite the line inline, OR have the **listener-surrogate host directly ask the carrier
  to clarify**, turning the fake listener's confusion into real on-show back-and-forth. Balance
  rules prevent "what's that?/it's X" Q&A slop.

## Next up
1. **🔴 Answer the 4 open questions in spec §10** (curiosity-gap open_loops now or later?;
   naive listener single-call vs iterative loop?; audio round-trip report-only vs gate?;
   lower draft temp from 0.75?). My leanings are in §10's parenthetical and in the session.
   These gate the implementation plan.
2. **Then: `writing-plans`** to turn the spec into an ordered implementation plan.
   **Recommend a FRESH session** — this one is heavy (large reads + research report + spec).
   The spec on disk is the durable handoff; a fresh session needs only it.
3. Implement in spec order of leverage: Story Spine → re-aim upstream prompts →
   Synthetic Listener gate + repair loop → demote tic passes → audio round-trip.
4. Regression target: re-run the pipeline on the Vienna topic; naive trace must clear the
   §4 success criteria (zero unresolved breaks in first 3 min, ≤2 across the episode).

## Watch out for
- **Spec §10 open questions are unanswered** — don't start writing-plans until they're decided;
  several implementation choices depend on them.
- **Don't add more tic passes** (disfluency/symmetry/backchannel) — research says that's the
  lowest-weighted dimension (25 pts). They get DEMOTED (run after the gate), not extended.
- **Digests:** user OK'd breaking them ("I can rebuild"). Plan converges both feeds on the
  Story Spine. Don't contort to preserve the digest overlay if it fights the spine.
- **Synthetic-listener fidelity is the go/no-go** (spec §8): before trusting the gate, confirm it
  *reports* the known Vienna breaks and *passes* a working digest. If it can't tell them apart,
  fix the asymmetry instruction first.
- **`config.json` overrides DEFAULTS** — new flags (`use_story_spine`, `use_synthetic_listener`,
  `narration_ratio_threshold`, etc.) must be checked there if they "aren't taking."
- Standing TODO (unchanged): rotate the leaked `@AsynchronousPodBot` Telegram token via BotFather
  `/revoke` when next at the home machine; git history verified clean.
- Two audio-scope dirs untracked on purpose — never commit.
