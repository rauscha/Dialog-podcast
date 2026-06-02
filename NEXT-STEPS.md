# Next steps

The running list. Sourced from `reviews/2026-05-30-deep-review.md` and updated each session. Top of file is what's nearest.

## In-flight: Asynchronous Rounds — weekly journal digests (NEW top priority, 2026-05-31)

Plan approved + **Phase 1 shipped** this session. Full plan: `C:\Users\andre\.claude\plans\idempotent-strolling-riddle.md`. Three weekly auto-generated digest shows for the commute — **MFM Rounds**, **The Fetal Frontier**, **Signal in the Scan** — same Juno/Caspar hosts, 3 separate RSS feeds. Citation-free ranking (LLM importance + age-normalized Altmetric + journal quartile + evidence level), rolling ~6-month window, per-show DOI ledger to gate already-covered papers.

- [x] **Phase 1 — ranking engine + dry-run CLI.** Shipped `58d0a67`. `digest_sources/ranker/shows/ledger.py` + `digests.json` + `assets/sjr_2024.csv` + `--digest-dry-run <show>`. Validated live across all 3 shows; soft-failure + copyright firewall tested. Re-run any time: `python generate_podcast.py --digest-dry-run mfm` (or `fetal` / `ai`).
- [x] **Phase 2 — digest episode type + research branch (2026-06-01).** Shipped: `_script_from_research_package` extraction (the shared post-research pipeline), `_digest_research_and_script` (cloud research model, NO tools, paraphrase-only — copyright firewall preserved), `cfg["digest_articles"]` branch in `research_and_script`, `_run_with_cfg` + `run_digest`, `--digest <show>` CLI. Web fact-check is **off** for digests by design (curated source set is the truth, no fresh abstract pulls). Smoke-tested live: MFM Rounds digest produced a clean 11-min peer-level episode ("When Aspirin Delays Rather Than Prevents") with headline-then-rounds structure, paraphrased findings, DOIs in show notes — script in `episodes/20260601_190410_mfm_rounds_-_week_of_2026_06_02_work/script.txt`.
- [x] **Phase 3 — multi-feed publishing (2026-06-01).** Shipped: `update_rss(feed_meta=...)` honors per-show channel metadata + filename; `git_publish(feed_filename=...)`; `run_digest` builds `feed_meta` from `digests.json` (display_name, description, author, category, cover_image) via new helper `_feed_meta_from_show`; `digest_ledger.record_episode` writes covered DOIs + PMIDs + episode_url after a successful publish; cover art generated locally with SDXL on the 4080 (`scripts/gen_covers.py`, FLUX-schnell deferred — repo is HF-gated). Smoke `--digest mfm` shipped a fresh peer-level episode ("Screening Chronic Hypertension Before Aspirin," 10:01) to `feed-mfm.xml` with `feed.xml` untouched; ledger persists all 5 DOIs so the next MFM run skips them. Bonus: RSS description preamble leak fixed (defensive `_strip_to_dialogue` + topic fallback in `update_rss`).
- [ ] **Phase 3.5 — small polish (optional, do before Phase 4).** Nested `<itunes:category>` (e.g. Science→Medicine) instead of flat top-level; tighten `_strip_to_dialogue` regex to disallow spaces in speaker labels (defense in depth); regenerate covers if the SDXL ones (`cover-{mfm,fetal,ai}.jpg`) feel too generic — re-roll seeds or pivot to FLUX with HF auth (`huggingface-cli login` + accept FLUX terms).
- [ ] **Phase 4 — scheduling + on-demand.** `run_all_due_digests` + `--digest-all`; per-show weekday gating + `last_run`; `run_digests.ps1` + one daily Windows Task Scheduler task; bot `/digest`, `/digest` list, `/digest_preview`.
- **Tuning knobs surfaced in Phase 1** (optional; revisit while doing Phase 2):
  - Ranking is **LLM-dominant on fresh papers** (Altmetric is empty <6 wk old, so its weight renormalizes onto the LLM). Invest in the LLM prompt over weight-fiddling. Weights: LLM .46 / Altmetric .24 / quartile .18 / evidence .12.
  - `DISCOVER_LIMIT=80` sorted by date ⇒ effectively "freshest ~80," not the full 6 months (fine for a weekly run). Raise if you want to rank deeper.
  - Quartile CSV is a **curated 12-journal table** (SCImago hard-blocks scripted downloads, 403). Drop the official SCImago export into `assets/sjr_*.csv` and it supersedes automatically (newest filename wins).

## Voice quality — RESOLVED (2026-05-31)

Provider decision made and shipped (`a806a2c` + this session): **ElevenLabs hosts** (Juno + Caspar) + **Cartesia guests** with cross-provider rotation; **Fish Audio dropped**; OpenAI demoted. Per-turn loudness normalization added so cross-provider voices sit at one level. All **13 active voice IDs validated** (`validate_voices.py`). The old "listen to 3 comparison MP3s" task is done; `episodes/tts_comparison/*.mp3` can be deleted whenever.
- [ ] Optional: ship one real published episode on the ElevenLabs/Cartesia stack to confirm end-to-end (the Phase 2 digest test episode will also exercise this).

## Bugs found (address opportunistically)

- [x] **RSS `<description>` preamble leak — fixed in Phase 3 (2026-06-01).** `update_rss` now defensively calls `_strip_to_dialogue(episode["script"])` before slicing the 500-char preview, and falls back to the episode topic (with a warning log) if no SPEAKER line is found. The leaked entry in `feed.xml` from 2026-05-07 remains historical; future episodes are safe.
- [ ] **I — Stop leaking partial ElevenLabs voice IDs** in the public companion JSON. Replace with a human label ("Juno — warm alto") in `_public_tts_route()`. Now live since the hosts run on ElevenLabs.

## In-flight: P1-C — Sonic footnotes (cues)

User chose "full ship" 2026-05-30. NASA backend (Phase 1) in; remaining phases below. (Voice quality, which had jumped ahead of this, is now resolved.)

- [x] **Phase 1** — NASA backend + skeleton + splice wiring. Committed `4664f29`.
- [x] **Phase 1 cue episode + verdict (2026-05-31).** Cue was a complete miss (4 s of unrelated NASA podcast intro). Guest voice barely distinguishable but beats made sense. The bigger issue (stilted OpenAI voices) is now fixed.
- [ ] **Phase 1.5** — LLM timestamp picker + smarter source selection; stop grabbing semantically-unrelated audio on fallback. Wins over Phase 2.
- [ ] **Phase 2** — Wikimedia Commons backend (MediaWiki API + `extmetadata` license parsing). Covers `commons_morse_code`, `commons_metronome`, `commons_tuning_fork`.
- [ ] **Phase 3** — Internet Archive backend (`advancedsearch.php` + `licenseurl`/`rights`). Covers `internet_archive_public_domain`.
- [ ] **Phase 4** — Freesound backend (needs `FREESOUND_API_KEY`). Covers `freesound_cc0_field_recording`.

## Cue quality & editorial polish

- [ ] **Surface dropped cues.** A planned cue whose backend isn't built (e.g. `commons_morse_code`) currently vanishes silently. Log a warning + record the skip in the manifest. Cheap; do regardless of the Phase 1.5 call.
- [ ] **Fix NASA fallback source quality.** `nasa_apollo_countdown` fell back to a keyword query and pulled a random NASA *podcast* clip. Honor catalog semantics or **fail closed to silence** instead of grabbing unrelated audio.
- [ ] **Consolidate turn enumeration (step zero).** Cue *planning* (`_place_cues` → `_enumerate_turns` in `sonic_footnote_mixer.py`) and cue *splicing* (`_tts_two_host` → `_parse_dialogue_turns` in `generate_podcast.py`) count turns with two different functions and can disagree (off-by-one placement). Collapse to one shared enumeration first.
- [ ] **Restraint / interruption budget.** Cap cues per episode, enforce a minimum gap, bias toward genuine section breaks. Fewer, better.
- [ ] **Transition flow.** Tune fades + per-segment level-matching at cue↔dialogue seams.
- [ ] **Dry-run timeline.** Print the planned episode turn-by-turn with `[CUE]` markers before any TTS/network — cheap placement iteration. (The digest dry-run is a sibling pattern worth mirroring here.)

## P1 — remaining items (from deep review)

- [ ] **D — Break Juno/Caspar turn symmetry.** Interruption/overlap pass in the dialogue step. One Sonnet call, prompt-only.
- [ ] **E — Parallelize per-turn TTS.** `ThreadPoolExecutor` around the per-turn TTS loop. Biggest wall-clock win in the deep review. (Clip downloads moot while clips are off.)
- [ ] **F — `cache_control: ephemeral`** on long static system prompts (four named prompts + research-brief block + host-memory bible). Anthropic SDK.
- [ ] **G — Proactive Telegram completion notification** (single message with link + elapsed time).
- [ ] **H — Pin `requirements.txt`, run `pip-audit`** (floating lower bounds today).
- [ ] **J — $10/day Anthropic + OpenAI spend caps** (user-side billing consoles).

## P0/P0-B — closed

- [x] **A — Verify no real Telegram token in git history.** Verified clean 2026-05-30.
- [x] **B — A11y: non-color cue for active chapter.** Shipped `eb12edb`.

## Hygiene / recurring

- [ ] **Re-enable work-dir cleanup on 2026-06-06.** Uncomment `shutil.rmtree(work_dir)` in `generate_podcast.py`.
- [ ] **Telegram token rotation** (BotFather `/revoke @AsynchronousPodBot`). Not urgent; git clean.
- [ ] **On laptop checkout**: add `NCBI_EMAIL` (and optional `NCBI_API_KEY`) to `.env` for digests; `ELEVENLABS_API_KEY` + `CARTESIA_API_KEY` needed for audio (Fish key no longer used); `bash scripts/install-hooks.sh` for the per-clone pre-commit secret hook.

## P2 / nice-to-have queue (from deep review §4)

Pull from here when P1 is closer to done.
- Per-user rate limit in the Telegram bot.
- Topic sanitization for git commit messages (static template, not f-string).
- Delete or guard the archived email-webhook code.
- ffprobe timeout in `clip_mixer.py:273` (one-line fix).
- CLI topic-length cap matching the bot's `MAX_TOPIC_LEN=500`.
- Verify MusicGen model is cached between intro and outro.
- `/queue` ETA display in the bot.
- Website loading state during initial `fetch(feedUrl)`.
- Microcopy capitalization consistency; snap spacing to a 4 px grid.
- Source-weaving rewrite pass (push named citations into dialogue).

## Flourishes (deep review §5 — when you have an evening)

- **Closing callback** — last 60 s references a prior episode via `host_memory.json`. Highest leverage per effort.
- **Reading-room companion** — per-episode annotated reading list under a "Going Deeper" tab. (The digest source cards are a natural fit here.)
- **Generative chapter art** — one small abstract illustration per chapter (~$0.02/ep via FLUX-schnell).

## Parked: Phase 5 — clip + cue co-mixing (not pursuing for now)

Shelved 2026-05-30. Design kept in case clips are ever revisited:
- Clips and cues use two different insertion rulers — clips by text-marker position (`<<<CLIP_CUE>>>`, `assemble_with_clips` in `clip_mixer.py:317`), cues by turn index (`_tts_two_host` splice). A cue's "after turn 8" is meaningless inside a clip chunk starting at turn 5.
- Merge approach: unify on the turn-index ruler; one splice pass inserts both with a collision rule (clip-then-cue) when both land after the same turn. Skip-gate at `generate_podcast.py:3298`.
- If revived, decide rights stance first (published feed = cues only was the leaning).
