# Next steps

The running list. Sourced from `reviews/2026-05-30-deep-review.md` and updated each session. Top of file is what's nearest.

## In-flight: P1-C — Sonic footnotes (full ship)

User chose "full ship" on 2026-05-30. Broken into 4 backend phases + an optional Phase 1.5.

- [x] **Phase 1** — NASA backend + skeleton + splice wiring. Committed `4664f29`.
- [ ] **Phase 1.5** — LLM timestamp picker. Reads a NASA episode's description and picks a sensible cue moment instead of the fixed 5-sec offset. Conditional on a real Phase 1 episode sounding bad.
- [ ] **Phase 2** — Wikimedia Commons backend. MediaWiki API category listing + per-file `extmetadata` license parsing. Covers `commons_morse_code`, `commons_metronome`, `commons_tuning_fork`.
- [ ] **Phase 3** — Internet Archive backend. `advancedsearch.php` + `licenseurl`/`rights` parsing. Covers `internet_archive_public_domain`.
- [ ] **Phase 4** — Freesound backend. Requires `FREESOUND_API_KEY` in `.env` (user signs up at freesound.org/help/developers/). Covers `freesound_cc0_field_recording`.
- [ ] **Phase 5 — clip + cue co-mixing.** ← **ACTIVE PRIORITY** (2026-05-30; user wants YouTube clips AND cues in the same episode). Currently the two are mutually exclusive: the gate at `generate_podcast.py:3298` skips cues whenever `use_clips=true`.
  - **Why it's not trivial:** clips and cues use two different insertion rulers. Clips slot in by text-marker position (`<<<CLIP_CUE>>>`) and `assemble_with_clips` (`clip_mixer.py:317`) TTS's multi-turn *chunks* at a time. Cues slot in by *turn index* via the footnote splice in `_tts_two_host` (`generate_podcast.py:2645`). A cue's "after turn 8" has no meaning inside a clip chunk that starts at turn 5.
  - **Design:** unify on the turn-index ruler. (1) Map each clip cue to the turn it follows. (2) Build the episode as one per-turn audio list (cue path already does this). (3) One splice pass inserts both clips and cues after the right turns. (4) Collision rule when both land after the same turn (suggest clip-then-cue).
  - **Rights:** keep `use_clips` default `false` in `config.json`; make clips a per-run opt-in (`$env:USE_CLIPS="true"`) that now coexists with cues, so the published feed stays clean.
  - Key files: `clip_mixer.py` (`assemble_with_clips` ~317, `process_clips` ~386), `generate_podcast.py` (`_tts_two_host` ~2593 / splice ~2645, orchestration + skip gate ~3280–3354, `_make_tts_fn` ~2989).

> Note (2026-05-30): the "clips vanished from my last episode" report was **not a bug** — clips are off by config (`use_clips: false`, deliberate since `888bb6f` for YouTube-copyright reasons). Last episode ran clean with cues. Phase 5 is the path to having both.

## P1 — remaining items (from deep review)

- [ ] **D — Break Cedar/Marin turn symmetry.** Add an interruption / overlap pass to the dialogue script step. One Sonnet call, prompt-only change.
- [ ] **E — Parallelize TTS and yt-dlp clip downloads.** `concurrent.futures.ThreadPoolExecutor` around the per-turn TTS loop and the clip downloads. **Biggest wall-clock win in the deep review.**
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
