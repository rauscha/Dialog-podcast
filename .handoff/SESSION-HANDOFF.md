# Session hand-off — 2026-05-30 (machine: laptop)

## STATE (read this first)
- Branch: `main`, working tree clean, synced with `origin/main` (no unpushed code).
- This was a **diagnostic session, no code changed.** The output is a finding + a plan, both written down (here + `NEXT-STEPS.md`).
- Headline finding: the "YouTube clips disappeared from my last episode" was **not a bug.** Clips are off by config (`use_clips: false`) and have been since commit `888bb6f` — deliberately, for the YouTube-copyright reason the consultant flagged. The last episode (chiptune, 2026-05-29) ran clean (zero warnings) and spliced its 2 sonic cues fine. Nothing stripped the clips; they were never enabled.
- User's goal: have YouTube clips AND sonic-footnote cues in the same episode. That requires **Phase 5 (co-mixing)**, which is now the bumped-up priority (ahead of footnote Phase 2). User chose "build co-mixing" and then called hand-off, so the build itself is **not started** — fresh session recommended.

## Done this session
- Diagnosed the missing-clips question (see above). Confirmed via `config.json` (`use_clips: false`), git history (`888bb6f` set it false; only the initial commit had it true), and the last episode's `episode_manifest.json` (`clips: []`, `warnings: []`, 2 cues present).
- Traced both audio splice engines end-to-end and designed Phase 5. Wrote the design into `NEXT-STEPS.md` under the Phase 5 bullet.

## Next up
1. **Phase 5 — clip + cue co-mixing** (fresh session; the build wasn't started). Full design is in `NEXT-STEPS.md`. Short version: clips and cues currently use two different rulers — clips slot in by text-marker position (`<<<CLIP_CUE>>>`) and TTS multi-turn chunks; cues slot in by turn index. Unify on the turn-index ruler and do one splice pass that inserts both. Then make per-run `$env:USE_CLIPS="true"` work alongside cues while keeping the published default `false`.
2. **Then test Phase 1 + clips on one real episode and listen** — `$env:USE_CLIPS="true"; python generate_podcast.py "fm synthesis"`. Was deferred from last session; do it once co-mixing lands so you hear both at once.
3. Footnote **Phase 2 (Wikimedia Commons)** drops to third — it was #1 before, now behind the user's clip goal.
4. P1-D (break Cedar/Marin turn symmetry), P1-E (parallelize TTS/clips) as before.

## Watch out for
- **The cue-skip gate is intentional**, at `generate_podcast.py:3298` — it skips cues whenever `use_clips` is true (with a manifest warning). Phase 5 removes this gate; don't be surprised it's there.
- **Two different insertion rulers** is the core difficulty (text-marker position vs turn index). Naively threading footnotes into the clip path breaks because `assemble_with_clips` TTS's multi-turn chunks, so global turn indices don't survive inside a chunk. The fix is to unify on the per-turn list, not to thread one into the other.
- **Collision rule needed:** when a clip and a cue both land after the same turn, pick an order (suggest clip-then-cue) so the splice is deterministic.
- **Rights:** keep `use_clips` default `false` in `config.json` for published runs. Co-mixing should make clips a per-run opt-in, not flip the default.
- Key files for the build: `clip_mixer.py` (`assemble_with_clips`, ~line 317; `process_clips`, ~386) and `generate_podcast.py` (`_tts_two_host` footnote splice, ~2645; the orchestration + skip gate, ~3280–3354; `_make_tts_fn`, ~2989).
- Standing carryovers (unchanged): work-dir cleanup re-enable on 2026-06-06; Telegram token rotation (not urgent, git clean); `bash scripts/install-hooks.sh` per-clone on the desktop; `use_sonic_footnotes` defaults True.
