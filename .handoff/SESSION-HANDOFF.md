# Session hand-off — 2026-06-22 (machine: desktop)

## STATE (read this first)
- **Branch:** `main`, clean working tree, **synced** — `origin/main = origin/feat = local main = local feat = 7b55968`. Nothing stranded; only one worktree (the main one).
- **Where things stand:** The **narration-first pipeline (C0)** is fully built, reviewed, accepted, merged to `main`, and **live**. All 13 plan tasks shipped subagent-driven (per-task + final whole-branch review → "ready to merge"). Test suite **31/31** (repo now has real `tests/` infra — it had none). The Vienna acceptance render passed and published; the recalibration, fast-follows, and a Story-Spine truncation fix all landed. The single most useful next action is a **re-render with the spine** (it truncated on the acceptance run; the fix is in but unexercised).

## Done this session
- Executed all 13 tasks of `docs/superpowers/plans/2026-06-20-narration-first-pipeline.md`: Story Spine, re-aimed thesis/beat-sheet/draft prompts, Synthetic First Listener gate (iterative no-look-ahead) + expert ear + narration ratio, bounded repair loop, audio round-trip QA, digest gating, fidelity harness. All flag-gated; flags-off keeps structural output byte-identical (draft temp 0.75→0.6 is the one intentional non-identity).
- **Recalibrated the fidelity instrument from live data:** the narration ratio is a noisy/**inverted** good-vs-broken signal (good digests 0.31–0.54; a name-droppy broken script scored 0.64). Go/no-go now gates on **listener bounce + high-sev break count** (ratio advisory); `narration_ratio_threshold` 0.6→0.35; committed cleanup-proof fixtures in `tests/fixtures/`.
- **Final-review fast-follows** (`8e19304`): repair loop applies highest-turn-first (fixes intra-round index-drift + its expert twin), aligned a stale 0.6 literal, added a never-raises test for the audio round-trip.
- **Fixed a real bug the render exposed** (`0b93b8c`): Story Spine silently truncated at `max_tokens=4096` (a full spine ~3.7k tokens sits at the edge) → raised to 8192, verified.
- **Vienna acceptance render PASSED** and published ("The Couch That Left Vienna", feed.xml). Audio round-trip on the rendered audio: **0 HIGH-severity breaks**. Ran *without* the spine (truncation) → quality is a **lower bound** from re-aimed-prompts + gate alone.
- Merged `feat/narration-first-pipeline` → `main` (ff, `12d9fa4`→`7b55968`), pushed both branches.

## Next up
1. **Re-render an episode WITH the spine** now that the `max_tokens` fix is in — exercises the full spine-driven pipeline (the shipped quality is a lower bound). Re-run Vienna or a new topic. **Use `--no-guest`** (no `OPENAI_API_KEY` in `.env`; `guest_cross_provider` uses OpenAI voices → a booked guest crashes TTS).
2. **Persist `listener_trace`** to a sidecar (currently only logged → lost to the now-active work-dir cleanup).
3. **Delete the redundant remote `feat` branch** (`git push origin --delete feat/narration-first-pipeline`) — it now mirrors `main`. Needs an explicit OK (remote delete).
4. Triage deferred Minor findings (full list: `.superpowers/sdd/progress.md`).

## Watch out for
- **The work-dir cleanup is ACTIVE now** (`shutil.rmtree`, line ~5387) — `episodes/*_work/` is deleted post-run. The script survives as a `.script.txt` sidecar, but `listener_trace` does not. The original Vienna script was lost this way (why the fidelity fixtures are committed, not referenced).
- **Scheduled digests fire on whatever branch is checked out at 05:00.** A Monday MFM digest ran on the feature branch this session, committed itself, and auto-pushed `feat`. It's the legit weekly episode (published fine on the new gated code), but **switch back to `main` at end of session** to avoid this.
- **Two `audio-scope-*` dirs stay untracked on purpose** — never commit them.
- Pre-existing pending decisions remain in `.handoff/PENDING-DECISIONS.md` (sonic-footnote ear-check; anti-slop linter gate-vs-warn) — unrelated to C0, still open.
- The narration ratio is now understood to be weak — don't trust it as a standalone quality gate; the gate's bounce/high-sev signals are the reliable ones.
