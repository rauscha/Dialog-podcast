# Session hand-off — 2026-05-30 (machine: laptop)

## STATE (read this first)
- Branch: `main`, working tree clean. Local is ahead of `origin/main` by 1–2 commits at hand-off time (this handoff commit + Phase 1 commit `4664f29`). Push attempt happens at the end of this skill; if it lands you'll see `Already up to date.` on pick-up.
- Where things stand: P0/P0-B items from the deep review are all closed. P1-C (sonic footnotes ship-or-kill) was decided as **full ship** and Phase 1 of four backend phases shipped — NASA cues actually splice into audio now. Phases 2-4 are queued for fresh sessions.

## Done this session
- Pushed last session's `.gitattributes` commit (`0c1b3f1`) to origin/main.
- Confirmed Telegram token rotation is NOT urgent: git history is clean, blast radius is bot-impersonation only. Stays queued; surface when at the tower.
- Built and committed **sonic footnotes Phase 1** (`4664f29`):
  - new `sonic_footnote_mixer.py` (NASA backend + Sonnet placement pass + ffmpeg HTTP-range trim)
  - `_tts_two_host` extended to splice cue audio between turn MP3s at planned indices
  - `generate_podcast.py` main wired to call `prepare_footnotes` before audio assembly; manifest gets real attributions

## Next up
1. **Phase 2 — Wikimedia Commons backend** (fresh session recommended; different API domain). Covers `commons_morse_code`, `commons_metronome`, `commons_tuning_fork`. MediaWiki API category listing + extmetadata license parsing.
2. **Test Phase 1 against a real episode** before committing more code: run `python generate_podcast.py "fm synthesis"` (or similar) and listen. Cue quality may be poor (see Watch-outs); if so, Phase 1.5 (LLM timestamp picker) should jump ahead of Phase 2.
3. **P1-D — break Cedar/Marin turn symmetry** (interruption pass; one Sonnet call, prompt-only).
4. **P1-E** — parallelize TTS + clip downloads (biggest wall-clock win in the deep review).
5. Remainder of P1: F (prompt caching), G (proactive Telegram completion notification), H (pin requirements + pip-audit), I (drop partial ElevenLabs voice IDs from public JSON), J (set Anthropic + OpenAI $10/day caps — user-side).

See `NEXT-STEPS.md` for the running list including Phase 3/4 of footnotes and P2 items.

## Watch out for
- **`use_sonic_footnotes` defaults to True** — the next real generation will hit the new code path. If it breaks, the fix is `$env:USE_SONIC_FOOTNOTES = "false"` in the shell before running.
- **NASA cue quality is "first 5 seconds of a NASA podcast that matched the search"** — architecturally correct but sonically meh. Phase 1.5 = LLM reads episode description to pick a real timestamp. If you listen to a Phase 1 episode and the cues feel random, jump 1.5 ahead of Phase 2.
- **Clip + footnote co-mixing is not yet supported.** With `use_clips=True` (off by default), footnotes are silently deferred for that run with a manifest warning.
- **Speaker filter in `_enumerate_turns`** accepts any `[A-Z][A-Z ]+` label; it does NOT mirror `_known_speaker_labels`' cfg-aware filter. Fine for Cedar/Marin two-host eps; revisit if guest hosts cause turn-index drift.
- Pre-commit hook is portable now but still per-clone — on the desktop, run `bash scripts/install-hooks.sh` once.
- Telegram token rotation still queued (not urgent — git is clean).
- Work-dir cleanup re-enable lands in 7 days (2026-06-06) — uncomment the `shutil.rmtree` in `generate_podcast.py`.
