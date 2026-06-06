# Session hand-off — 2026-06-06 (machine: desktop / RTX 4080)

## STATE (read this first)

- Branch: `main`, clean, synced with `origin/main` ✅
- One worktree only — nothing stranded.

Quiet, productive session. No feature code shipped beyond one bug-fix; the main output is a
**planning document**. The state-of-the-art scoping review (merged by a cloud agent overnight)
now has a concrete **implementation walkthrough** — that's the thing to act on next. The
ElevenLabs quota that blocked yesterday's test run is **back** (a scheduled AI digest published
successfully this morning), so audio generation works again.

## Done this session

- **Fixed a silent-failure bug** (`39c0eeb`). A test run hit the ElevenLabs character-quota wall
  → every TTS turn 401'd, but per-turn exception catching let the pipeline report "Done! exit 0"
  and write a 28-second voiceless episode into `feed.xml`. `_tts_two_host` now raises (non-zero
  exit, skips publish) when the turn failure ratio exceeds `cfg["tts_max_fail_ratio"]` (default
  0.2). New default added. **Verified by inspection/compile; not yet seen firing live.**
- **Authored the implementation walkthrough** (`3ece28a`): `docs/research/2026-06_implementation_walkthrough.md`.
  Turns the scoping review's Section 7 shortlist into 5 ordered, code-grounded phases
  (A audio → B timing/speech → C editorial → D beat-gate architecture → E shared-context TTS),
  each with file/function refs + acceptance criteria. A code audit found several items already
  built (per-turn two-pass loudnorm, persona bible, rewriter passes) — plan targets the *deltas*.
- **Committed orphaned digest state** (`716cfe9`): the scheduled 2026-06-06 "Signal in the Scan"
  episode (`4249675`, auto-published) left `digests/ai_ledger.json` + `host_memory.json`
  uncommitted; folded them in so the covered-DOI gate carries forward.

## Next up

1. **Build Phase A of the walkthrough — audio-engineering finish.** Pure ffmpeg, low risk,
   instantly audible, and *not blocked by anything*. A1 two-pass final master + retarget
   −14 LUFS/−1.0 dBTP; A2 de-esser; A3 concat crossfades; A4 per-clip loudnorm in `clip_mixer.py`.
   Verify with `ffprobe`/`loudnorm summary` + the `audio-scope` skill. **Recommended first sprint.**
2. **Then Phase B1** — thread prior-turn emotion into TTS instructions (`_build_tts_instructions`).
   ~30-min quick win.
3. **Still owed: verify the untested overnight features** (closing callback + sonic-footnote
   Phase 1.5). Quota's back, so a real run is now possible — but pick a topic that draws a
   **NASA-backed** cue (space/physics), since a Freesound-only cue will drop (Phase 4 unimpl).

## Watch out for

- **The fail-loud guard hasn't fired live yet.** First real total-TTS-failure will confirm it
  (it'll now abort with non-zero exit instead of publishing silence). Working as designed by
  inspection, but untested end-to-end.
- **Work-dir cleanup is re-enabled** (since 2026-06-04). Intermediate artifacts (`script.txt`,
  turn mp3s, cue downloads) are deleted on success — so you can't inspect a callback/cue script
  after the fact. If debugging a specific run, set a skip-cleanup path or comment `shutil.rmtree`
  (`generate_podcast.py` ~L4342) for that run.
- **A scheduled digest task is live** and will keep publishing on its weekday cadence — expect
  occasional auto-commits like `4249675` to appear on `origin/main` between sessions. Pull before
  starting work. (It also tends to leave `ai_ledger.json`/`host_memory.json` uncommitted — worth
  checking whether `git_publish` should be staging those too; minor follow-up.)
- **Phase A3 (crossfades) and Phase B2 (variable gaps) touch the same concat helpers** — the
  walkthrough says land A fully before B2 to avoid thrashing the same functions twice.
