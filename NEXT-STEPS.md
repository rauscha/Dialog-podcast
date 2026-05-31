# Next steps

The running list. Sourced from `reviews/2026-05-30-deep-review.md` and updated each session. Top of file is what's nearest.

## Decision (2026-05-30): clips OFF, cues are the keeper

User decided to **leave YouTube clips off** (`use_clips: false` stays the default and we're not building co-mixing for now). Reasons:
- Auto-selected clips were low quality — wrong sections of the source video, wrong text.
- Music clips didn't *flow* — making them flow in/out is editorial taste work, best left to a human editor for now.
- They were frequently extraneous.
- Rights are non-trivial but were the *secondary* concern.

**Cues (sonic footnotes) are the focus.** Their job is narrower and better suited to automation: **punctuate and separate** at section breaks. No "wrong 15 seconds" failure mode.

Phase 5 (clip + cue co-mixing) is **parked, not deleted** — design preserved at the bottom of this file if it's ever revived.

## In-flight: P1-C — Sonic footnotes (cues)

User chose "full ship" on 2026-05-30. NASA backend (Phase 1) is in; remaining phases below.

- [x] **Phase 1** — NASA backend + skeleton + splice wiring. Committed `4664f29`.
- [x] **Test a Phase 1 cue episode** — done 2026-05-30 (desktop). Shipped *"The Sauce That Won a Competition"* (deep_dive + forced guest, BBQ competitions), now LIVE on the feed (`d52f6f6`). **AWAITING the user's LISTEN verdict** — that decides Phase 1.5 vs Phase 2. Structural findings below.
  - Planner proposed 2 cues; **only 1 inserted.** The 2nd (`commons_morse_code`) needs the Wikimedia backend (Phase 2, unbuilt) and **dropped silently** — no warning/error.
  - The inserted NASA cue (`nasa_apollo_countdown`) fell back to query `'Apollo 11'` and grabbed 4s of an **unrelated NASA podcast** (`Ep393_Crew-11`), not a countdown; placed **after turn 0** (before hosts finish the open). → strong structural case for Phase 1.5.
  - Guest path worked on paper: Dr. Evelyn Cross (voice *nova*, 8 turns). Confirm by ear.
- [ ] **Phase 1.5** — LLM timestamp picker + smarter source selection. Reads a NASA episode's description and picks a sensible cue moment instead of the fixed 5-sec offset, and stops grabbing semantically-unrelated audio on fallback. **PROMOTED — the test episode's cue was both mis-sourced and oddly placed.** Cue quality is the whole game.
- [ ] **Phase 2** — Wikimedia Commons backend. MediaWiki API category listing + per-file `extmetadata` license parsing. Covers `commons_morse_code`, `commons_metronome`, `commons_tuning_fork`.
- [ ] **Phase 3** — Internet Archive backend. `advancedsearch.php` + `licenseurl`/`rights` parsing. Covers `internet_archive_public_domain`.
- [ ] **Phase 4** — Freesound backend. Requires `FREESOUND_API_KEY` in `.env` (user signs up at freesound.org/help/developers/). Covers `freesound_cc0_field_recording`.

## Cue quality & editorial polish (the keepers from the co-mixing discussion)

These apply to cues alone and are where the "make it feel intentional" wins live:

- [ ] **Surface dropped cues (new, from 2026-05-30 test).** A planned cue whose backend isn't built (e.g. `commons_morse_code` → Wikimedia) currently vanishes with no warning and no manifest note. Log a warning and record the skip in the manifest. Cheap; do regardless of the Phase 1.5 call.
- [ ] **Fix NASA fallback source quality (new, from 2026-05-30 test).** `nasa_apollo_countdown` fell back to a keyword query and pulled a random NASA *podcast* clip (`Ep393_Crew-11`), not a countdown — the "wrong N seconds" failure mode cues were supposed to avoid. Overlaps with Phase 1.5; honor catalog semantics or fail closed (silence) instead of grabbing unrelated audio.
- [ ] **Consolidate turn enumeration (step zero).** Cue *planning* (`_place_cues` → `_enumerate_turns` in `sonic_footnote_mixer.py`) and cue *splicing* (`_tts_two_host` → `_parse_dialogue_turns` in `generate_podcast.py`) count turns with two different functions. They can disagree (the footnote one ignores the cfg-aware speaker filter), causing off-by-one placement. Collapse to one shared enumeration before doing more placement work.
- [ ] **Restraint / interruption budget.** Cap cues per episode, enforce a minimum gap between them, and bias placement toward genuine section breaks. Directly counters the "frequently extraneous" problem. Fewer, better.
- [ ] **Transition flow.** Tune fades and per-segment level-matching at the cue↔dialogue seams so a cue reads as intentional punctuation, not a bolted-on clip.
- [ ] **Dry-run timeline.** A mode that prints the planned episode turn-by-turn with `[CUE]` markers *before* any TTS or network calls — cheap iteration on placement without generating a full episode.

## P1 — remaining items (from deep review)

- [ ] **D — Break Cedar/Marin turn symmetry.** Add an interruption / overlap pass to the dialogue script step. One Sonnet call, prompt-only change.
- [ ] **E — Parallelize TTS and yt-dlp clip downloads.** `concurrent.futures.ThreadPoolExecutor` around the per-turn TTS loop (clip downloads moot while clips are off). **Biggest wall-clock win in the deep review.**
- [ ] **F — `cache_control: ephemeral` on long static system prompts.** Anthropic SDK. Apply to the four named system prompts + the research-brief block + host-memory bible block.
- [ ] **G — Proactive Telegram completion notification.** Single outbound message when generation finishes, with website link + elapsed time.
- [ ] **H — Pin `requirements.txt`, run `pip-audit`.** Floating lower bounds today; pin exact and write down baseline date + result.
- [ ] **I — Stop leaking partial ElevenLabs voice IDs** in public companion JSON. Replace with a human label ("Cedar — warm alto") in `_public_tts_route()`.
- [ ] **J — Set $10/day Anthropic + OpenAI spend caps.** User-side action in respective billing consoles.

## P0/P0-B — closed

- [x] **A — Verify no real Telegram token in git history.** Git history verified clean 2026-05-30. Rotation is hygiene, not urgent.
- [x] **B — A11y: non-color cue for active chapter.** Shipped `eb12edb` 2026-05-30.

## Hygiene / recurring

- [ ] **Re-enable work-dir cleanup on 2026-06-06.** Uncomment `shutil.rmtree(work_dir)` in `generate_podcast.py`.
- [ ] **Telegram token rotation** (BotFather `/revoke @AsynchronousPodBot`). Not urgent; surface when at the tower.
- [ ] **On laptop checkout**: `bash scripts/install-hooks.sh` to install pre-commit secret-scan hook (per-clone).

## P2 / nice-to-have queue (from deep review §4)

These are real but second-order. Pull from here when P1 is closer to done.

- Per-user rate limit in the Telegram bot.
- Topic sanitization for git commit messages (static template, not f-string interpolation).
- Delete or guard the archived email-webhook code.
- ffprobe timeout in `clip_mixer.py:273` (one-line fix).
- CLI topic-length cap matching the Telegram bot's `MAX_TOPIC_LEN=500`.
- Verify MusicGen model is cached between intro and outro generation.
- `/queue` ETA display in the Telegram bot.
- Website loading state during initial `fetch(feedUrl)`.
- Microcopy capitalization consistency on the website.
- Snap spacing to a strict 4 px grid.
- Source-weaving rewrite pass (push named citations into dialogue).

## Flourishes (deep review §5 — when you have an evening)

- **Closing callback** — last 60 seconds of each ep references a prior episode's idea using `host_memory.json`. Highest leverage per effort.
- **Reading-room companion** — per-episode annotated reading list under a "Going Deeper" tab. Haiku pass, ~$0.001/ep.
- **Generative chapter art** — one small abstract illustration per chapter. ~$0.02/ep via FLUX-schnell.

## Parked: Phase 5 — clip + cue co-mixing (not pursuing for now)

Shelved 2026-05-30 (see decision at top). Design kept in case clips are ever revisited:
- Clips and cues use two different insertion rulers — clips by text-marker position (`<<<CLIP_CUE>>>`, `assemble_with_clips` in `clip_mixer.py:317`, TTS'ing multi-turn chunks), cues by turn index (`_tts_two_host` splice, `generate_podcast.py:2645`). A cue's "after turn 8" is meaningless inside a clip chunk starting at turn 5.
- Merge approach: unify on the turn-index ruler — map each clip cue to the turn it follows, build one per-turn audio list, one splice pass inserts both, with a collision rule (clip-then-cue) when both land after the same turn.
- The cue-skip gate that makes them mutually exclusive lives at `generate_podcast.py:3298`.
- If revived, decide rights stance first (published feed = cues only, clips private-only was the leaning) and consider cue-as-rights-safe-fallback for a missing clip.
