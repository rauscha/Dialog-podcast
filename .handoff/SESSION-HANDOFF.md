# Session hand-off — 2026-05-30 (machine: laptop)

## STATE (read this first)
- Branch: `main`, working tree clean, synced with `origin/main` (no unpushed code).
- This was a **diagnostic + decision session, no code changed.** Output is a finding and a direction, both on disk (here + `NEXT-STEPS.md`).
- **Decision: clips stay OFF; cues are the focus.** Started by investigating "YouTube clips vanished from my last episode" — that was **not a bug** (clips are off by config, `use_clips: false`, deliberate since `888bb6f`; last episode ran clean with 2 cues). Explored clip+cue co-mixing (Phase 5), then the user decided **not** to pursue clips: auto-selected clips were low quality (wrong sections/text), music clips didn't flow (editorial/human work), and were often extraneous; rights non-trivial but secondary. **Cues (sonic footnotes) win — their job is to punctuate and separate.**
- Phase 5 (co-mixing) is **parked, not deleted** (design preserved at the bottom of `NEXT-STEPS.md`).

## Done this session
- Diagnosed the missing-clips question: off by config, not a regression. Confirmed via `config.json`, git history (`888bb6f`), and the last episode's `episode_manifest.json` (`clips: []`, `warnings: []`, 2 cues present).
- Made the clips-off / cues-focus decision and rewrote `NEXT-STEPS.md` around it: cue phases promoted, a new "Cue quality & editorial polish" section added, Phase 5 moved to a parked section.

## Next up
1. **Test a Phase 1 cue episode and LISTEN.** `python generate_podcast.py "fm synthesis"` (clips off by default — no env var). The NASA cues haven't actually been heard yet; this decides what's next.
2. **Phase 1.5 (LLM cue-moment picker)** if the cues feel random — cue quality is now the whole game. Otherwise **Phase 2 (Wikimedia Commons backend)**.
3. **Cue editorial polish (the keepers):** consolidate turn enumeration (step zero — real latent off-by-one bug), interruption budget/restraint, transition-flow fades/levels, dry-run `[CUE]` timeline. See the "Cue quality & editorial polish" section in `NEXT-STEPS.md`.
4. P1-D (turn symmetry), P1-E (parallelize TTS) as before.

## Watch out for
- **Don't build clips / Phase 5** — explicitly shelved this session. `NEXT-STEPS.md` no longer lists it as a priority; the parked design is at the very bottom.
- **Turn-enumeration mismatch is a real latent bug**, independent of clips: cue planning uses `_enumerate_turns` (`sonic_footnote_mixer.py`) while cue splicing uses `_parse_dialogue_turns` (`generate_podcast.py`); they can disagree on what "turn N" is. Fix before more placement work.
- Key cue files: `sonic_footnote_mixer.py` (`prepare_footnotes`, `_place_cues`), `generate_podcast.py` (`_plan_sonic_footnotes` ~1291, `_tts_two_host` splice ~2645, orchestration ~3280–3354).
- Standing carryovers (unchanged): work-dir cleanup re-enable on 2026-06-06; Telegram token rotation (not urgent, git clean); `bash scripts/install-hooks.sh` per-clone on the desktop; `use_sonic_footnotes` defaults True.
- Cosmetic: an earlier pushed commit (`2baddfc`) has a mangled message (stray `@`/backticks) from a shell-syntax slip; content is fine, left as-is rather than force-pushing `main`.
