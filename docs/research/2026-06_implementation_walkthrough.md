# Implementation Walkthrough — Translating the Scoping Review into Code

*Authored 2026-06-05. Companion to `2026-06_state_of_the_art_ai_podcasts.md`. This turns
that review's **Section 7 shortlist** into a concrete, ordered build plan: what to change, in
which file/function, in what order, with acceptance criteria.*

> **This is a work order, not a scope doc.** Every task below is grounded in the *current*
> code (line refs were accurate as of commit `39c0eeb`; re-grep before editing). Crucially,
> **several shortlist items are already partly or fully built** — those are called out so we
> don't redo finished work. The net new surface area is smaller than Section 7 implies.

---

## 0. What's already done (so we don't rebuild it)

A code audit on 2026-06-05 found the pipeline is further along than the scoping review assumed:

| Shortlist item | Reality in code | Implication |
|---|---|---|
| #1 two-pass loudnorm | **Per-turn** normalization is *already two-pass + `linear=true`** (`_normalize_turn_loudness`, ~L2952). Only the **final master** is single-pass blind (`_master_audio`, ~L3028). | Item #1 is a *delta*, not new. |
| #1 EQ / mastering chain | highpass(60)→lowpass(18k)→loudnorm already exists in `_master_audio`. | De-esser is the only missing band stage. |
| #1 consistent sample rate/bitrate | Already uniform 44.1k / 192k / 2ch across turns, concat, master, clips, music. | Only the 48k bump (optional) remains. |
| #4 rewriter/polish | **Two passes already exist**: anti-cliché (`_ANTI_CLICHE_SYSTEM`, L622) + performance (`_PERFORMANCE_SYSTEM`, L801). | Only the *anti-slop critic* is missing. |
| #5 persona character-bible | **Already built and persisted**: structured Juno/Caspar personas (core/strengths/blind_spots/speech_habits/avoid, L260–327) loaded from `host_memory.json`, updated per episode (`_MEMORY_UPDATE_SYSTEM`). | Item #5 is ~80% done; only vocabulary lexicons + enforced disagreement remain. |
| #6 beat sheet | Beat sheet **exists as guidance** (`_BEAT_SHEET_SYSTEM`, L533) threaded into every downstream prompt. | Per-beat *generation + gate + checkpoint* is the new part. |

**Genuinely missing** (the real work): final-master two-pass, de-esser, concat crossfades,
per-clip loudness match, disfluency/backchannel pass, variable speaker-aware gaps + edge trim,
overlaid backchannels, anti-slop critic, per-turn emotion threading, beat-gate + checkpoint,
Q&A-round generation, regenerate-until-grounded loop, and the shared-context TTS swap.

---

## 1. Ordering rationale

Ordered by impact-to-effort **and** dependency. Five phases:

```
Phase A  Audio-engineering finish        ← do first; pure ffmpeg, instantly audible, low risk
Phase B  Cheap realism (timing + speech) ← shares code with A's concat path; coordinate
Phase C  Editorial quality               ← LLM-prompt work; independent of A/B
Phase D  Architecture (quality-over-speed)← bigger; enables the "overnight quality" goal
Phase E  Big lever: shared-context TTS    ← realism ceiling; GPU/paid; do last, behind a flag
```

**Coordination note:** Phase A3 (crossfades) and Phase B2 (variable gaps + edge trim) both
edit the same three helpers — `_make_silence` (~L2884), `_interleave_silence` (~L2917),
`_ffmpeg_concat` (~L2849). Land A fully, then do B2 as one focused edit to that join logic so
the two don't thrash the same functions twice.

---

## Phase A — Audio-engineering finish (Section 7 item #1)

*Biggest quality jump for least work. All ffmpeg; no LLM calls. Each is independently
shippable and A/B-testable with the `audio-scope` skill.*

### A1. Upgrade the final master to two-pass `loudnorm` + retarget to streaming
- **File / fn:** `generate_podcast.py` → `_master_audio` (~L3028–3091).
- **Change:** Mirror the existing two-pass pattern from `_normalize_turn_loudness` (~L2952):
  pass 1 measures (`print_format=json` → `measured_I/TP/LRA/thresh/offset`), pass 2 re-encodes
  with measured values + `linear=true`. Replace the current single blind `loudnorm`.
- **Retarget:** Move defaults from `-16 LUFS / -1.5 TP` to **`-14 LUFS / -1.0 dBTP`** (Spotify/
  YouTube standard; review §5b). Change `audio_loudness_i` → `-14.0`, `audio_true_peak` → `-1.0`
  in `DEFAULTS` (~L181–182). Keep them config-overridable (Apple-faithful `-16` stays available).
- **Acceptance:** `ffmpeg -i out.mp3 -af loudnorm=print_format=summary -f null -` reports
  measured I within **±0.5 LU of −14** and true peak **≤ −1.0 dBTP**. Dialogue dynamics not
  audibly squashed (because `linear=true` applies one constant gain).
- **Effort:** S. **Risk:** Low (pattern already proven per-turn).

### A2. Add a de-esser to the mastering chain
- **File / fn:** `_master_audio`, in the filter list builder (~L3040–3051).
- **Change:** Insert a de-ess stage **before** loudnorm. ffmpeg has `deesser` (and `adeesser`
  in newer builds); fallback is a narrow dynamic dip ~5–9 kHz. Order becomes
  `highpass → lowpass → deesser → loudnorm`. Gate behind new config `audio_deesser` (default
  `true`) + `audio_deesser_freq` (default `~6500`).
- **Acceptance:** Sibilant "s"/"sh" energy reduced (visible in `audio-scope` spectrogram 5–9 kHz
  band) without lisping; null-test a sibilant-heavy line before/after.
- **Effort:** S. **Risk:** Low–med (verify which de-ess filter the bundled ffmpeg build has;
  the installed build is `N-121464` — confirm `deesser` availability, else use the EQ fallback).

### A3. Micro-crossfade at every concat join
- **File / fn:** `_ffmpeg_concat` (~L2849–2881) — currently the `-f concat` demuxer (hard cut).
- **Change:** Replace hard concat with chained `acrossfade` (~**10 ms** between speech turns,
  **2–5 s** for music↔speech bookends). Either build an `acrossfade` filter graph, or keep the
  demuxer for same-type joins and apply `acrossfade` only at segment boundaries. New config
  `concat_crossfade_ms` (default `10`), `music_crossfade_sec` (default `2.5`).
- **Acceptance:** No audible click/pop at turn seams (inspect waveform discontinuities in
  `audio-scope`); music transitions are smooth, not abrupt.
- **Effort:** M (filter-graph plumbing). **Risk:** Med — `acrossfade` *overlaps* clips, so it
  slightly shortens total duration; account for it and don't double-apply with B2's gaps.

### A4. Loudness-match every inserted clip
- **File / fn:** `clip_mixer.py` → `extract_clip` (~L181–264) and/or `assemble_with_clips`
  (~L317–381). Clips are currently cut with edge fades but **no loudnorm**.
- **Change:** Run a two-pass `loudnorm` on each clip to the **program target** (−14 LUFS) right
  after the trim, before interleaving. Reuse a shared helper (factor the two-pass logic out of
  `_normalize_turn_loudness` into a module-level `two_pass_loudnorm(in, out, cfg)` that both
  files import).
- **Acceptance:** A loud YouTube clip and a quiet one both sit within **±1 LU** of the dialogue
  bed; no volume jump when a clip starts/ends.
- **Effort:** S–M. **Risk:** Low. **Bonus:** the shared helper de-duplicates the loudnorm code.

### A5. (Optional) Standardize 48 kHz internal, 128 kbps export
- **Change:** Bump `audio_sample_rate` 44100 → **48000** for all *intermediate* stages; export
  final at **128 kbps mono** (or 192 stereo when music-heavy) per review §5b. Touch the same
  `-ar`/`-ac`/`-b:a` sites the audit listed (turns L3012–3013, concat L2873–2874, master
  L3067/3073, clips `clip_mixer.py` L237–238, `music_gen.py` L74/L104).
- **Acceptance:** `ffprobe` shows 48 kHz on every intermediate; final export matches chosen
  spec; no resample artifacts.
- **Effort:** S but touches many call sites. **Risk:** Low. **Verdict:** Nice-to-have; defer
  unless we're already in these files. 44.1k is fine for speech.

---

## Phase B — Cheap realism: timing + speech (items #2, #3, and the #6 emotion-thread sub-point)

### B1. Thread prior-turn emotion into TTS instructions  *(do this first — tiny, high ROI)*
- **File / fn:** `generate_podcast.py` → `_build_tts_instructions` (~L2832) and its caller loop
  in `_tts_two_host` (~L3369–3376).
- **Current:** each turn's `instructions` is built from *its own* tag only; prosody hard-resets
  every call (gpt-4o-mini-tts has no cross-turn context — review §4d).
- **Change:** Pass the **prior turn's emotion tag** into `_build_tts_instructions` and prepend a
  continuity clause, e.g. *"Continuing from a [prior tag] line, now shift to [this tag]."* Note
  the loop currently parallelizes via `executor.map` (~L3399) but iterates `turns` in order, so
  prior-tag lookup is just `turns[i-1]` at work-item build time (L3369) — **compute it before
  the thread pool**, don't try to read it inside the worker.
- **Acceptance:** Listening A/B — emotional transitions feel less "stitched"; a calm→excited
  jump has a perceptible ramp rather than a hard reset.
- **Effort:** S. **Risk:** Low.

### B2. Edge-silence trim + variable, speaker-aware inter-turn gaps
- **File / fn:** `_tts_two_host` splice section (~L3422–3439), `_make_silence` (~L2884),
  `_interleave_silence` (~L2917).
- **Current:** a single fixed silence (`turn_silence_ms`, default 180) is inserted between
  *every* pair of turns; no edge trimming.
- **Change:**
  1. **Trim** leading/trailing near-silence from each turn mp3 (`silenceremove` filter) so gaps
     are deterministic, not "TTS tail + fixed gap."
  2. **Variable gaps:** ~**150–250 ms** for fast exchanges, ~**400–700 ms** at topic/beat shifts
     (review §4c). Derive "topic shift" from the beat sheet boundaries already available, or a
     simple heuristic (speaker stays same / question→answer = short; new beat = long). New config
     `gap_fast_ms`, `gap_shift_ms`.
- **Acceptance:** Measured silence between turns matches the intended class (±30 ms); rapid
  back-and-forth feels tighter; section changes breathe.
- **Effort:** M. **Risk:** Med — coordinate with A3 so crossfade overlap + inserted gap don't
  fight. Decide one ruler: **trim → insert gap → (optional tiny crossfade only at the gap edges)**.

### B3. Script-level disfluency / backchannel pass
- **File / fn:** new prompt constant `_DISFLUENCY_SYSTEM` (place near `_ANTI_CLICHE_SYSTEM`,
  L622) + a new stage in the pipeline between symmetry-break (~L1936) and fact-check (~L1955).
  *(Place it before fact-check so corrections still apply to the final wording.)*
- **Change:** Light touch — inject occasional "um/uh," false starts, and **short backchannel
  turns** ("mm-hmm," "right," "oh, interesting") for the *listening* host. Enforce the timing
  rule from review §4c: **filler → pause → connector** ("so…"), and place fillers *before*
  complex/important words, never mid-stride. Cap density (e.g. ≤1 disfluency per ~6 turns) to
  avoid the "tic" failure mode. Skip for **digest** episodes (consultant-rounds register must
  stay clean — same gate `episode_type=="digest"` used by symmetry-break).
- **Acceptance:** Read the diff: fillers land before key words with a pause/connector, not
  sprinkled randomly; backchannels are their own short turns; digest output unchanged.
- **Effort:** M. **Risk:** Med — overdoing it sounds *more* fake (review §4c). Start conservative;
  tune density. This is the script-side half of NotebookLM's "sprinkle umms" finding (review §0).

### B4. Overlaid backchannels (true overlap, not concatenation)  *(stretch)*
- **File / fn:** `_tts_two_host` splice (~L3409–3440).
- **Change:** Render backchannel turns from B3 as **tiny separate TTS files** and *overlay* them
  with ffmpeg `amix`/`adelay`, ducked ~6–10 dB, starting ~80–150 ms **before** the speaker
  finishes — instead of inserting them as sequential turns. Em-dash interruptions (already
  produced by `_SYMMETRY_BREAK_SYSTEM`, L655) become *physical* overlaps here.
- **Acceptance:** A "mm-hmm" audibly overlaps the tail of the other host's line; level sits
  under the main voice; no clipping (check true peak).
- **Effort:** L. **Risk:** Med–high (mixing graph complexity). **Verdict:** Do only after B1–B3
  prove out; this is where concatenative pipelines start to genuinely resemble shared-context.

---

## Phase C — Editorial quality (items #4 remainder, #5 remainder)

### C1. Anti-slop critic + gate
- **File / fn:** new `_ANTI_SLOP_CRITIC_SYSTEM` constant; new stage after the rewriter passes.
  Today the only "critic" is a 6-item `phrase_blacklist` (L319–326) + metrics that **report but
  don't gate** (`_quality_metrics`, ~L1315–1345).
- **Change:** Add a critic that scores the draft on the failure modes from review §2b
  ("Measuring AI Slop"): **uniform sentence length, over-structure, jargon density, vagueness,
  sycophancy** — and *rewards* variability (fragments, tangents, callbacks). Make it **gating**:
  if score < threshold, trigger one targeted re-rewrite (feed the critic's specific notes back
  into `_ANTI_CLICHE_SYSTEM`). Cap at 1–2 iterations to bound cost/time.
- **Acceptance:** Sentence-length variance increases vs. baseline; blacklist hits → 0; a
  deliberately "sloppy" test draft is caught and rewritten. Critic must **penalize**, not just
  praise (the review's explicit warning: a generic "make it better" critic *rewards* slop).
- **Effort:** M. **Risk:** Med — must avoid the slop-rewarding trap; bake the penalties into the
  rubric explicitly.

### C2. Persona vocabulary lexicons + enforced disagreement  *(small — bible already exists)*
- **File / fn:** extend the existing persona dicts (L260–327) and the dialogue/anti-cliché
  prompts that consume them.
- **Change:** Add a **distinct lexicon** per host (signature words/constructions Juno vs. Caspar
  reach for) and a hard instruction to stage **at least one substantive respectful disagreement**
  per episode (review §3 anti-boredom heuristic; the relationship dynamics at L306–316 already
  gesture at this — make it mandatory and checkable). Optionally seed a reusable **cold-open
  template + recurring-segment** scaffold.
- **Acceptance:** Hosts are distinguishable on the page by word choice alone; every non-digest
  episode contains a genuine disagreement that resolves with both keeping part of their view.
- **Effort:** S. **Risk:** Low (mostly prompt text on top of existing structure).

---

## Phase D — Architecture: quality-over-speed (items #6, #7, #8)

*This phase delivers the "overnight / quality-over-speed" goal explicitly. Bigger, but it's
where the reference architectures (`evandempsey/podcast-llm`, `neuralnoise`, the comedy-podcast
verifier-gate Show HN) point.*

### D1. Beat-based generation + verifier gate + checkpoint/resume
- **Current:** beat sheet exists (`_BEAT_SHEET_SYSTEM`, L533) but the episode is drafted as one
  monolithic call (~L1882); no per-beat gate, no resume.
- **Change:** Generate the episode as **N grounded beats**, each written then **verified before
  the next** (facts grounded in the research package + no cliché/blacklist phrases + per-character
  voice consistency) — the comedy-podcast pattern (review §2c). Persist each accepted beat to the
  work dir so a crashed/queued run can **resume** (mirror the digest dry-run's incremental
  pattern). Thread prior-turn emotion (B1) across beat boundaries too.
- **Acceptance:** Each beat passes its gate before audio renders; killing the process mid-run and
  re-running resumes from the last accepted beat; final coherence ≥ monolithic baseline (spot-check).
- **Effort:** L. **Risk:** Med–high (largest refactor of the script stage). Sequence the gate as
  fact + cliché + voice, reusing C1's critic for the cliché/voice checks.

### D2. Per-outline-section Q&A-round generation
- **Change:** For longer episodes, generate each beat as **interviewer→expert Q&A rounds**
  (Juno asks → Caspar answers, ~2 rounds), then a rewriter pass folds rounds into natural
  dialogue (`evandempsey/podcast-llm` shape, review §2a). Maps cleanly onto the existing
  curious/expert dyad.
- **Acceptance:** Longer episodes hold coherence better than single-shot draft; depth per beat
  increases without rambling.
- **Effort:** L. **Risk:** Med. **Dependency:** Build on D1's beat loop.

### D3. Regenerate-until-grounded fact-check
- **Current:** fact-check is a **single** corrective pass (`_FACT_CHECK_SYSTEM`, L729, called once
  ~L1986).
- **Change:** Wrap it in a **loop**: after correction, run a grounding check (each claim supported
  by the research package / web result); regenerate unsupported statements until grounded or a max
  iteration cap (review §1, Citation-Enhanced Generation). Keep the copyright-firewall behavior for
  digests (no fresh pulls — package is truth).
- **Acceptance:** On a seeded draft with an unsupported claim, the loop flags and fixes it; caps
  at N iterations; digest path still never web-fetches.
- **Effort:** M. **Risk:** Med (cost/latency — bound the loop).

---

## Phase E — Big lever: shared-context dialogue render (item #9)

*The realism ceiling. Do last, behind a flag, without ripping out the current per-turn path.*

- **Current:** per-turn TTS, prosody resets each line (review §4a — the core asymmetry).
- **Change:** Add a new TTS route that renders the **whole dialogue jointly** so cross-host
  reactions/prosody are generated together. Two paths:
  - **Hosted:** ElevenLabs **v3 Text-to-Dialogue** (inline `[interrupting]`/`[laughs]` tags,
    em-dash overlaps) — fits the existing ElevenLabs integration + key, but watch the quota wall
    that just bit us (and v3 is credit-heavier).
  - **Self-hosted on the RTX 4080:** **Dia** (Apache-2.0, consumer-GPU, `[S1]/[S2]` + nonverbals),
    Higgs Audio v2, or MoonCast. Overlap-capable: Dia / DialoSpeech / Higgs / v3 — **not** VibeVoice.
- **Integration point:** new provider in `tts_engines` + a `_tts_route`/`tts_provider` value;
  gate behind config so per-turn stays the default/fallback. Most of Phases B/C/D become moot for
  realism *if* this lands — but they're cheaper, ship sooner, and remain the fallback path.
- **Acceptance:** Hosts audibly react to each other (backchannels/overlaps emerge from the model,
  not ffmpeg); blind A/B preference over the per-turn render; fallback to per-turn on failure.
- **Effort:** XL. **Risk:** High (new dependency, GPU memory, output-format wrangling). **Verdict:**
  Prototype Dia on the 4080 as a spike before committing; it's the only item that needs a real
  model evaluation, not just code.

---

## Suggested first sprint

If picking up cold, do **Phase A in full** (A1→A4; A5 optional) — it's a few hours of ffmpeg
work, instantly audible, low risk, and verifiable with the `audio-scope` skill — then **B1**
(emotion threading, ~30 min) as a quick win. That's the highest realized quality per hour and
touches no LLM-stage logic. Everything after is incremental and independently shippable.

**Verification harness:** every Phase A/B task is checkable with `ffprobe`/`loudnorm summary`
and the `audio-scope` spectrogram skill — wire those into the acceptance step rather than relying
on subjective listening alone. (And note: a real end-to-end run is currently gated on the
ElevenLabs quota top-up — see NEXT-STEPS.)
