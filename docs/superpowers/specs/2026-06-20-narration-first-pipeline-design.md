# Design — Narration-first pipeline + the Synthetic First Listener

**Date:** 2026-06-20
**Status:** Draft for review (brainstorming → spec). Supersedes the C0 framing in `NEXT-STEPS.md` and the "add a beat-sheet step" prescription in `.handoff/EDITORIAL-DIAGNOSIS-vienna.md` (a beat-sheet step already exists — see Background).
**Author of failure being fixed:** the "commentary track for a documentary never made" — hosts argue *about* material the listener is never told.

---

## 1. Problem

Episodes on the main feed (e.g. the Vienna episode) are unfollowable for a smart layperson: names are dropped not rendered, arguments precede the facts they're about, every beat is a punchline with no setup. Full diagnosis: `.handoff/EDITORIAL-DIAGNOSIS-vienna.md`.

This is a **generation** failure, not a script-editing failure, and not a missing-stage failure.

## 2. What the research established (landscape review, 2026-06-20)

Cited findings (workflow `wf_b6ea3cf7-312`; full report archived in the session transcript). Headlines:

1. **Multi-stage script chains are the field standard.** NotebookLM: outline → revised outline → draft → critique → revision. MoonCast (arXiv 2503.14345): brief → script, *because* one-pass generation "results in ill-suited and vague scripts." **Our chain-of-edits architecture is sound and field-aligned — keep it.**
2. **The narration-vs-banter fix is upstream, in the prompt.** MoonCast forces "explain any terms/concepts/methods that may confuse readers unfamiliar with the field, covering all abbreviations and entity names" + "Opening: Introduce the topic." NotebookLM targets an "efficiency-valuing listener persona" and "starting with topic overviews — you're never left wondering, 'What am I even listening to?'" **Our beat-sheet/draft enforce none of this. Gap #1.**
3. **Compliance ≠ substance (PodBench, arXiv 2601.14903).** Across 34 LLMs, "high instruction-following does not guarantee high content substance." Claude-4.5-Sonnet: 96.6 instruction-following / 63.3 content quality — a 33-pt gap. A style-edit chain can pass every stage and stay hollow. **We have no substance gate. Gap #2.**
4. **Engagement lives in the script, weighted toward substance.** PodBench rubric (on script text, pre-TTS): Content Substance 45 > Narrative Engagement 30 > Conversational Naturalness 25. Our recent investment (disfluency/symmetry/backchannel) polishes the lowest-weighted 25.
5. **Audio frontier is whole-conversation shared-context TTS** (VibeVoice, FireRedTTS-2, Higgs Audio 2) vs our per-turn stitching — but script-layer leverage dominates; per-line emotion tagging is a legitimate commercial approach, not a defect. Out of scope for this work (tracked separately as Phase E).

## 3. Background — what already exists (so we re-aim, not rebuild)

`generate_podcast.py::_script_from_research_package` already runs:
`research → thesis (_THESIS_SYSTEM) → guest-plan (_GUEST_PLANNER_SYSTEM) → beat-sheet (_BEAT_SHEET_SYSTEM) → [sonic plan] → dialogue draft (_DIALOGUE_DRAFT_SYSTEM) → anti-cliché (_ANTI_CLICHE_SYSTEM) → symmetry-break (_SYMMETRY_BREAK_SYSTEM) → disfluency (_DISFLUENCY_SYSTEM) → fact-check (_FACT_CHECK_SYSTEM) → closing callback → performance (_PERFORMANCE_SYSTEM) → memory update`.

**Crucial in-house evidence:** the **digest** shows are followable and run on the *same plumbing*. The difference is the digest path carries a mandatory structural spine (`_DIGEST_RESEARCH_SYSTEM` produces `structural_plan` with a `headline_arc`: clinical question → design → effect → caveat → what-changes) and an "establish first / form-first / walk through, not a hook" rule. **Same pipes, better spec, good result.** This design generalizes the digest's spine to the narrative feed.

The current main-feed stages are **mis-aimed**: `_THESIS_SYSTEM` produces an *argument* ("Thesis / Why This Matters"); `_BEAT_SHEET_SYSTEM` defines each beat by "what Juno believes / what Caspar challenges" and **mandates disagreement.** The architecture literally encodes "two clever people adjudicating."

## 4. Goals / non-goals

**Goals**
- A first-time listener who knows nothing about the topic can follow the whole episode without rewinding. (The "wife test," made measurable.)
- Every name/term is defined before or as it is invoked; every segment shows one concrete scene before any host reacts to it.
- Followability becomes an **instrument** we can run before publish, not an anecdote.

**Non-goals**
- No change to TTS engines, audio mastering, RSS/publish (Phases A/B stay).
- No shared-context TTS migration (separate future Phase E).
- Not optimizing for latency/cost — "Asynchronous" tolerates a slow pipeline. Quality first.

**Success criteria**
- Re-running the pipeline on the Vienna topic produces a script where the Synthetic First Listener's naive persona reports zero unresolved comprehension breaks in the first 3 minutes and ≤2 across the episode.
- The narration-vs-banter ratio (defined in §6.4) clears threshold.
- Digests still produce (or are deliberately rebuilt on the new spine).

## 5. Architecture — the new stage graph

```
research
  → thesis            (RE-AIM: add exposition order + newcomer-followability target)
  → guest-plan        (keep)
  → STORY SPINE       (NEW: first-class artifact; generalizes digest structural_plan)
  → beat-sheet        (RE-AIM: each beat = one concrete scene; honors spine + host roles)
  → dialogue draft    (RE-AIM: grounded; Carrier/Surrogate roles; establish-before-adjudicate)
  → SYNTHETIC FIRST LISTENER GATE  (NEW: rewindless naive ear + expert ear → comprehension trace)
        ↳ REPAIR LOOP (NEW: per gap, rewrite OR surrogate-asks-to-clarify) → re-run gate (bounded)
  → fact-check        (keep)
  → anti-cliché       (keep)
  → [symmetry-break, disfluency]   (DEMOTE: run AFTER the gate; stop investing)
  → closing callback  (keep)
  → performance       (keep)
  → TTS → loudnorm → publish        (keep)
  → AUDIO ROUND-TRIP (NEW, post-render QA: Whisper transcript → naive ear → flag comprehension deaths)
```

**Keep (≈70%):** research, guest-plan, fact-check, anti-cliché, callback, performance, all audio/publish.
**Re-aim (3 prompts):** thesis, beat-sheet, draft.
**Add (3 stages):** Story Spine, Synthetic First Listener gate + repair loop, Audio round-trip.
**Demote:** symmetry-break + disfluency — moved after the gate; no further investment.

## 6. Component specs

### 6.1 Story Spine (NEW artifact)

Produced after thesis + guest-plan, before beat-sheet. JSON, consumed by every downstream stage. Schema:

```json
{
  "logline": "one sentence: the story this episode tells (not the argument it makes)",
  "newcomer_promise": "what a listener who knew nothing will be able to follow/retell after",
  "segments": [
    {
      "id": "S1",
      "anchor": "the ONE concrete scene/person/place/object shown here (not referenced)",
      "stakes": "why this matters, in plain terms, before any cleverness",
      "names_to_define": [
        {"name": "Carl Schorske", "one_line": "the historian whose 1981 book framed the debate"}
      ],
      "comprehension_target": "what the listener must understand by the end of this segment",
      "host_angle": "the reaction / tension / disagreement — explicitly AFTER the material lands",
      "carrier": "JUNO | CASPAR  (who tells this segment)",
      "surrogate": "the other host (who asks the newcomer questions here)"
    }
  ],
  "open_loops": [
    {"question": "planted question", "paid_off_in": "S4"}
  ]
}
```

Notes:
- `open_loops` is a light nod to curiosity-gap architecture (a runner-up idea) — optional, low cost, lets the spine plant a question and track its payoff. Can be deferred if it complicates.
- `carrier`/`surrogate` rotate across segments so neither host is stuck in one role.

**Producing prompt (new `_STORY_SPINE_SYSTEM`, draft):**

> You are the story architect for "Asynchronous." Before any dialogue exists, lay out the *story the episode will tell* — not the argument it will make. The hosts will be forced to follow this spine exactly.
> Hard rules:
> - Each segment must have ONE concrete anchor the listener is *shown* — a scene, a person doing something, a place, an object. Not a topic, not a thesis.
> - Establish before you adjudicate. Stakes and facts come first; the hosts' angle/disagreement is marked as coming *after* the material lands.
> - Every proper noun a listener wouldn't know goes in `names_to_define` with a one-line gloss.
> - Assume the listener knows nothing and cannot rewind. If a segment can't be followed cold, it is wrong.
> - Assign a carrier (tells it) and a surrogate (asks the newcomer's questions) per segment; rotate them.
> Return only the JSON object in the given schema.

### 6.2 Host roles — Carrier + Surrogate

The diagnosis's core fix: hosts currently have no narrative job but to react. Per segment:
- **Carrier** delivers the material — the scene, the people, what happened, what's at stake.
- **Surrogate** is the listener's proxy — asks the exact questions a curious newcomer would, forcing the carrier to answer with *content*, not quips.
- Personalities (Juno = associative/artistic; Caspar = grounded/skeptical) are unchanged. Only the **job** changes. Cleverness and affectionate disagreement become *seasoning after the material lands*, never the spine.
- Roles are carried in the spine and threaded into the beat-sheet and draft prompts.

### 6.3 Re-aimed upstream prompts (deltas — finalized at implementation)

- **`_THESIS_SYSTEM`**: keep the memo, add two required fields — *Exposition Order* (what must be told before what) and *Newcomer Promise* (what a layperson can retell after). Soften the "Thesis/argument" framing so the memo serves *telling a story*, not *winning an argument*.
- **`_BEAT_SHEET_SYSTEM`**: **remove** "what Juno believes / what Caspar challenges" as the beat's defining axis and **remove** the mandate for "one affectionate disagreement / let a host be wrong." **Replace** with: each beat = one spine segment; lead with the concrete anchor + stakes; define names; the host angle is explicitly the *last* thing in the beat. Keep "build an arc, not a list."
- **`_DIALOGUE_DRAFT_SYSTEM`**: add the MoonCast/NotebookLM grounding constraints verbatim in spirit — "introduce the topic first; explain every term/name/abbreviation a non-expert wouldn't know, in line; establish before you adjudicate; one concrete scene per segment." Bind Carrier/Surrogate roles. Consider lowering draft temperature from 0.75 (it currently rewards free-association).

### 6.4 Synthetic First Listener gate (NEW — the rewindless ear)

The novel core. Rationale: every existing field evaluator judges the script *holistically, with the source in hand* — so it can never feel lost and is structurally blind to the newcomer-confusion failure. We exploit **information asymmetry.**

**Naive-listener protocol:**
- Agent persona: "a smart, curious layperson who knows nothing about this topic — on a commute, cannot rewind."
- It is given **only the script, fed one turn at a time**, and is **forbidden the research package and any look-ahead.**
- After each turn it updates a running state and emits, per turn: `understood` (what's now clear), `holding_question` (open question it's carrying), `confusion` (what just lost it, e.g. an undefined name), `engaged` (still-with-it boolean + one-line why).
- Implementation (**RESOLVED §10.2: iterative turn-by-turn loop**): the agent is fed the script one turn at a time and only ever sees turns `1..n` when emitting its state for turn `n` — no-look-ahead is guaranteed by construction, not by an instruction it could violate. The §8 fidelity check validates the gate reports real confusion. (Single-call simulation was considered and dropped.)

**Expert-listener protocol (Extension 2):**
- Persona: a domain expert. Catches *hollowness* and error ("this reacts to material it never delivered," "this is name-dropping, not content").
- Runs on the full script (expert *may* know the field). Its findings route to **deepen/rewrite**, never to a clarifying question.

**Outputs — the comprehension trace:**
```json
{
  "naive": {
    "breaks": [
      {"turn": 14, "type": "undefined_name|lost_thread|no_stakes|whiplash|bored",
       "detail": "used 'Schorske' with no idea who that is",
       "severity": "low|med|high"}
    ],
    "followed_overall": true,
    "first_bounce_turn": null
  },
  "expert": {
    "hollow_spots": [{"turn": 9, "detail": "six names listed, none rendered"}],
    "errors": []
  },
  "narration_vs_banter": {
    "render_beats": 7, "react_only_beats": 11, "ratio": 0.39, "threshold": 0.6, "pass": false
  }
}
```
- **narration_vs_banter ratio** = render-beats / total-beats. A beat "renders" if it delivers material a newcomer didn't have; it "reacts only" if it just comments. Threshold (start 0.6) is the explicit anti-commentary-track metric.

**New prompt `_SYNTHETIC_LISTENER_SYSTEM`** (naive) + `_EXPERT_LISTENER_SYSTEM`. Drafted at implementation; the asymmetry instruction is the load-bearing part.

### 6.5 Repair loop (NEW — rewrite OR diegetic clarification)

For each naive-trace break, choose a repair move:

- **(a) Rewrite (inline):** carrier folds a short appositive/definition into the existing line. **Default for:** a single undefined name/term, a small local gap — anything a ≤8-word gloss fixes. Avoids Q&A ping-pong.
- **(b) Diegetic clarification:** insert a **surrogate turn** voicing the exact question the naive listener had ("wait — back up, what was actually at stake here?"), and a carrier turn answering. **Use for:** meaty/conceptual gaps, "I lost why this matters," anything a curious person would genuinely want drawn out. This is the user's key insight — the fake listener's confusion becomes the real surrogate's line, generating exposition *as back-and-forth*.

**Balance rules (to prevent "what's that?/it's X" slop):**
- Prefer (a) for small/local; reserve (b) for high-value gaps.
- Density cap on (b): at most ~1 clarifying exchange per N turns (start N≈8), like the disfluency pass.
- Expert `hollow_spots` → always deepen/rewrite, never a clarifying question.
- High-severity naive breaks must be repaired; low-severity may be left.

**Loop control:** repair → re-run the naive gate → repeat until pass or `max_repair_rounds` (start 2). Latency is acceptable. If still failing after max rounds, **do not publish silently** — log the residual trace and surface it (mirrors the `tts_max_fail_ratio` abort pattern).

### 6.6 Audio round-trip (NEW — post-render QA, Extension 1)

After TTS render, transcribe the actual audio with the existing `scripts/transcribe_episode.py` (faster-whisper), then run the **naive listener on the transcript**. Catches comprehension deaths the TTS introduces — e.g. the literal "Vindobona → Winderbohne" from the Vienna render. Report-only at first (a published-episode health check); escalate to a pre-publish gate later if it proves reliable. (Whisper loop-artifact noise — see hand-off — must be filtered or tolerated.)

### 6.7 Demoted passes & digest path

- **symmetry-break + disfluency:** move to *after* the gate so they can't launder a hollow script into sounding polished; keep flag-gated; no further feature work.
- **Digests:** the new Story Spine is the digest's `structural_plan` generalized, so the digest path should adapt cleanly. Per user direction, breaking digests is acceptable; intent is to converge both feeds on the spine and rebuild the digest overlay on top of it if needed.

## 7. Config flags (additions)

`use_story_spine` (default on), `use_synthetic_listener` (on), `synthetic_listener_max_repair_rounds` (2), `narration_ratio_threshold` (0.6), `clarification_density_turns` (8), `use_expert_listener` (on), `use_audio_roundtrip` (on, report-only), `dialogue_draft_temperature` (0.6 — **RESOLVED §10.4**, lowered from 0.75; config-tunable for A/B). All overridable via `config.json` (note: config overrides DEFAULTS — see CLAUDE.md).

## 8. Testing / acceptance

- **Vienna regression:** re-run the pipeline on the Vienna topic; naive trace must clear §4 success criteria; compare spine-driven script against the published transcript.
- **Unit:** spine schema validation; narration-ratio computation; repair-move selection (small gap → rewrite; conceptual gap → clarification); density cap; loop termination.
- **Synthetic-listener fidelity check:** feed it a deliberately broken script (the Vienna transcript) and confirm it *reports* the known breaks; feed it a known-good script (a working digest) and confirm it passes. If it can't distinguish them, the asymmetry instruction needs work before the gate is trusted.
- **Compile/import clean; flags off ⇒ byte-identical to pre-change pipeline.**

## 9. Risks & mitigations

- **Q&A ping-pong slop** from over-using diegetic clarification → balance rules + density cap (§6.5); anti-cliché pass still runs after.
- **Synthetic listener "cheats"** (uses knowledge it shouldn't) → fidelity check (§8); fall back to iterative turn-by-turn loop if single-call leaks future knowledge.
- **Gate false-positives** stalling the loop → bounded `max_repair_rounds`, then surface-don't-block.
- **Cost/latency blow-up** → acceptable by design; still cap repair rounds and dual-persona calls.
- **Digest regression** → accepted risk per user; converge on spine.

## 10. Open questions for reviewer — RESOLVED 2026-06-20

1. `open_loops` / curiosity-gap tracking in the spine — **DEFER.** Keep the JSON slot
   (nullable, unenforced); do not produce or consume it on the first pass. Adding it later
   is non-breaking. Rationale: keep the first implementation lean; the load-bearing
   instruments are the spine, the naive gate, and the narration ratio.
2. Naive listener — **ITERATIVE from the start.** Feed the script one turn at a time
   (turns 1..n only); no-look-ahead is guaranteed *structurally*, not by an instruction the
   model can quietly violate. Justified by the project's cost-tolerance ("Asynchronous").
   The §8 fidelity check still runs as a correctness test of the gate, not as an
   escalation trigger. (Single-call simulation is dropped, not deferred.)
3. Audio round-trip — **REPORT-ONLY now.** Ship as a post-render health check; structure
   the output so graduation to a pre-publish gate is possible later. A gate here would force
   costly re-renders, and TTS mispronunciations are better fixed at the pronunciation layer.
4. Draft temperature — **LOWER to ~0.6 via config.** Directly reduces the free-association
   that drives the commentary-track failure; config-driven so Vienna can be A/B-rendered at
   both temps and reverted in one line. The gate remains the backstop for residual drift.
