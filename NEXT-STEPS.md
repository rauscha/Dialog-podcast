# Next steps

The running list. Sourced from `reviews/2026-05-30-deep-review.md` and updated each session. Top of file is what's nearest.

## In-flight: Asynchronous Rounds — weekly journal digests (NEW top priority, 2026-05-31)

Plan approved + **Phase 1 shipped** this session. Full plan: `C:\Users\andre\.claude\plans\idempotent-strolling-riddle.md`. Three weekly auto-generated digest shows for the commute — **MFM Rounds**, **The Fetal Frontier**, **Signal in the Scan** — same Juno/Caspar hosts, 3 separate RSS feeds. Citation-free ranking (LLM importance + age-normalized Altmetric + journal quartile + evidence level), rolling ~6-month window, per-show DOI ledger to gate already-covered papers.

- [x] **Phase 1 — ranking engine + dry-run CLI.** Shipped `58d0a67`. `digest_sources/ranker/shows/ledger.py` + `digests.json` + `assets/sjr_2024.csv` + `--digest-dry-run <show>`. Validated live across all 3 shows; soft-failure + copyright firewall tested. Re-run any time: `python generate_podcast.py --digest-dry-run mfm` (or `fetal` / `ai`).
- [x] **Phase 2 — digest episode type + research branch (2026-06-01).** Shipped: `_script_from_research_package` extraction (the shared post-research pipeline), `_digest_research_and_script` (cloud research model, NO tools, paraphrase-only — copyright firewall preserved), `cfg["digest_articles"]` branch in `research_and_script`, `_run_with_cfg` + `run_digest`, `--digest <show>` CLI. Web fact-check is **off** for digests by design (curated source set is the truth, no fresh abstract pulls). Smoke-tested live: MFM Rounds digest produced a clean 11-min peer-level episode ("When Aspirin Delays Rather Than Prevents") with headline-then-rounds structure, paraphrased findings, DOIs in show notes — script in `episodes/20260601_190410_mfm_rounds_-_week_of_2026_06_02_work/script.txt`.
- [x] **Phase 3 — multi-feed publishing (2026-06-01).** Shipped: `update_rss(feed_meta=...)` honors per-show channel metadata + filename; `git_publish(feed_filename=...)`; `run_digest` builds `feed_meta` from `digests.json` (display_name, description, author, category, cover_image) via new helper `_feed_meta_from_show`; `digest_ledger.record_episode` writes covered DOIs + PMIDs + episode_url after a successful publish; cover art generated locally with SDXL on the 4080 (`scripts/gen_covers.py`, FLUX-schnell deferred — repo is HF-gated). Smoke `--digest mfm` shipped a fresh peer-level episode ("Screening Chronic Hypertension Before Aspirin," 10:01) to `feed-mfm.xml` with `feed.xml` untouched; ledger persists all 5 DOIs so the next MFM run skips them. Bonus: RSS description preamble leak fixed (defensive `_strip_to_dialogue` + topic fallback in `update_rss`).
- [x] **MFM Rounds inaugural episode published (2026-06-01, `2d77530`).** "Screening Chronic Hypertension Before Aspirin" committed with `feed-mfm.xml`, ledger, and Phase-3 episode artifacts. **One-time manual TODO:** submit `https://rauscha.github.io/Dialog-podcast/feed-mfm.xml` to Spotify for Creators.
- [x] **Cover-art polish (2026-06-02, `059b612`).** MFM re-rolled to two-panel medical-monitor (brain silhouette + tocography trace). AI sourced from GPT-image (SDXL fought every classic neural-net attempt across 5+ seeds/prompts); lines thickened via new `scripts/thicken_lines.py` for thumbnail legibility. Fetal unchanged. New img2img `--edit` path added to `gen_covers.py` with `--strength` flag.
- [x] **MFM digest editorial overhaul (2026-06-02, `4b9ce60`).** After listening to the inaugural MFM episode user reported three issues: voice sounded influencer-y not peer-rounds; paper intros lacked titles/journals/n/authors; lead vs "what else" not differentiated. Three coordinated fixes shipped: (1) Juno voice swapped to **Jessa — Easygoing and Effortless** (`yj30vwTGJxSHezdAGsv9`), validated 13/13. (2) `first_author` plumbed through PubMed + Europe PMC parsers → ranker → digest card → `_source_labels_from_cards` so show notes render "Wright et al. - AJOG - 2026 - Title". (3) `_DIGEST_RESEARCH_SYSTEM` now requires `headline_intro` / `rounds_intros[]` / `structural_plan` fields; new `_DIGEST_PERFORMANCE_OVERLAY` appended to thesis/beat-sheet/dialogue-draft/anti-cliche/performance prompts when `episode_type=="digest"` — explicitly overrides the main-feed "move source detail to show notes" rule and mandates consultant-rounds register, form-first paper intros, hard pivot into rounds.
- [x] **Overnight verify-run (2026-06-03).** 3-show SKIP_GIT verify-run produced clean output across MFM, Fetal Frontier, Signal in the Scan. Form-first citations land verbatim, "Rounds — four other things this week" pivots land, consultant register holds throughout. Per user direction all 3 verify episodes published to `feed-mfm.xml` for morning-drive listening; sorting into proper feeds (`feed-fetal.xml`, `feed-ai.xml`) is the next follow-up.
- [x] **Proper per-show feeds created (2026-06-03, `cde0f97`).** `feed-fetal.xml` (The Fetal Frontier) and `feed-ai.xml` (Signal in the Scan) built with correct channel headers and cover art. Verify episodes copied (not moved) from `feed-mfm.xml` — all 4 items still in MFM for uninterrupted listening. **Manual TODO: submit the two new feed URLs to Spotify for Creators** (feed-fetal.xml, feed-ai.xml).
- [x] **Phase 4 — scheduling + on-demand (2026-06-03, `bb5a70a`).** `_show_is_due()` (weekday gating + 1-day catch-up), `run_all_due_digests()`, `--digest-all` + `--digest-force-all` CLI flags. Bot: `/digest` (status list), `/digest <show_id>` (run one), `/digest all` (run all), `/digest_preview <show_id>` (dry-run ranking). `run_digests.ps1` (Task Scheduler entry point) + `register_scheduled_task.ps1` (one-shot task registration, run as Admin).
- [x] **Activate the Task Scheduler entry (2026-06-03).** `register_scheduled_task.ps1` run as Admin; Telegram bot restarted — `/digest` commands live.
- [x] **Submit Fetal + AI feeds to Spotify for Creators (2026-06-03).** `feed-fetal.xml` and `feed-ai.xml` submitted.
- [x] **Phase 3.5 — small polish (2026-06-04).** Nested `<itunes:category>` (Science→Medicine) added via `_itunes_category_xml()` helper; existing 3 digest feeds patched in-place; `_strip_to_dialogue` regex tightened to disallow spaces in speaker labels (`[A-Z]{0,40}` vs former `[A-Z ]{1,40}`). Work-dir cleanup re-enabled (was deferred to 2026-06-06; applied early).
- **Tuning knobs surfaced in Phase 1** (optional; revisit while doing Phase 2):
  - Ranking is **LLM-dominant on fresh papers** (Altmetric is empty <6 wk old, so its weight renormalizes onto the LLM). Invest in the LLM prompt over weight-fiddling. Weights: LLM .46 / Altmetric .24 / quartile .18 / evidence .12.
  - `DISCOVER_LIMIT=80` sorted by date ⇒ effectively "freshest ~80," not the full 6 months (fine for a weekly run). Raise if you want to rank deeper.
  - Quartile CSV is a **curated 12-journal table** (SCImago hard-blocks scripted downloads, 403). Drop the official SCImago export into `assets/sjr_*.csv` and it supersedes automatically (newest filename wins).

## Voice quality — RESOLVED (2026-05-31)

Provider decision made and shipped (`a806a2c` + this session): **ElevenLabs hosts** (Juno + Caspar) + **Cartesia guests** with cross-provider rotation; **Fish Audio dropped**; OpenAI demoted. Per-turn loudness normalization added so cross-provider voices sit at one level. All **13 active voice IDs validated** (`validate_voices.py`). The old "listen to 3 comparison MP3s" task is done; `episodes/tts_comparison/*.mp3` can be deleted whenever.
- [ ] Optional: ship one real published episode on the ElevenLabs/Cartesia stack to confirm end-to-end (the Phase 2 digest test episode will also exercise this).

## Bugs found (address opportunistically)

- [x] **RSS `<description>` preamble leak — fixed in Phase 3 (2026-06-01).** `update_rss` now defensively calls `_strip_to_dialogue(episode["script"])` before slicing the 500-char preview, and falls back to the episode topic (with a warning log) if no SPEAKER line is found. The leaked entry in `feed.xml` from 2026-05-07 remains historical; future episodes are safe.
- [ ] **Historical `feed.xml` preamble leak (2026-05-07 "history of fetoscopy" entry).** Low priority. Options: (a) leave it — old, listeners moved on; (b) hand-edit the `<item>`'s `<description>` + `<content:encoded>` CDATA (~10 min); (c) re-render the episode + replace. Decision deferred from 2026-06-01 pending list.
- [x] **I — Stop leaking ElevenLabs voice IDs (2026-06-04).** `_public_tts_route(route, label=None)` now pops `voice_id` entirely and sets `voice_label = label or "[configured]"`. `_tts_routes_summary_for_script` passes the speaker label through. Companion JSON will show `{"voice_label": "JUNO"}` instead of any truncated ID. `_public_tts_route_for_bot` in `telegram_bot.py` is internal/owner-only (not committed to git) — left as-is.

## In-flight: P1-C — Sonic footnotes (cues)

User chose "full ship" 2026-05-30. NASA backend (Phase 1) in; remaining phases below. (Voice quality, which had jumped ahead of this, is now resolved.)

- [x] **Phase 1** — NASA backend + skeleton + splice wiring. Committed `4664f29`.
- [x] **Phase 1 cue episode + verdict (2026-05-31).** Cue was a complete miss (4 s of unrelated NASA podcast intro). Guest voice barely distinguishable but beats made sense. The bigger issue (stilted OpenAI voices) is now fixed.
- [x] **Phase 1.5 (2026-06-05).** Better `_PLACEMENT_SYSTEM` prompt (natural breathing points, 3-turn min gap). `_select_best_nasa_result()` keyword scoring. `_estimate_start_offset()` Haiku call for LLM timestamp picking (gated on description richness).
- [ ] **Phase 2** — Wikimedia Commons backend (MediaWiki API + `extmetadata` license parsing). Covers `commons_morse_code`, `commons_metronome`, `commons_tuning_fork`.
- [ ] **Phase 3** — Internet Archive backend (`advancedsearch.php` + `licenseurl`/`rights`). Covers `internet_archive_public_domain`.
- [ ] **Phase 4** — Freesound backend (needs `FREESOUND_API_KEY`). Covers `freesound_cc0_field_recording`.

## Cue quality & editorial polish

- [x] **Surface dropped cues (2026-06-04).** `sonic_footnote_mixer.py` now logs `logger.warning` at every drop point: unimplemented backend (Phase 2-4), LLM placement miss, and source download failure. Summary line at end of `prepare_footnotes`: "N/M planned cues were dropped (see warnings above)." All bare `print` statements converted to proper `logger` calls.
- [x] **Fix NASA fallback source quality (2026-06-04).** Two guards added: (1) `_nasa_query_fallbacks` now stops at 2-word minimum — single-word fallbacks like "apollo" matched podcast episodes. (2) `_is_nasa_podcast_item()` filters out any search result whose title/description matches a podcast-episode pattern before scoring. NASA no longer returns podcast clips on degenerate fallbacks.
- [x] **Consolidate turn enumeration (2026-06-05).** `_enumerate_turns` now accepts `known_speakers`; `prepare_footnotes` builds the set from cfg so placement and splicing count identical turns.
- [ ] **Restraint / interruption budget.** Cap cues per episode, enforce a minimum gap, bias toward genuine section breaks. Fewer, better.
- [ ] **Transition flow.** Tune fades + per-segment level-matching at cue↔dialogue seams.
- [ ] **Dry-run timeline.** Print the planned episode turn-by-turn with `[CUE]` markers before any TTS/network — cheap placement iteration. (The digest dry-run is a sibling pattern worth mirroring here.)

## P1 — remaining items (from deep review)

- [x] **D — Break Juno/Caspar turn symmetry (2026-06-04).** `_SYMMETRY_BREAK_SYSTEM` prompt added; new Sonnet call (`_script_from_research_package`) runs between anti-cliche and fact-check. Picks 3-5 spots: interruption splits (em-dash), reaction clusters (3-4 short lines), host-heavy beats, mid-turn self-corrections. Skipped for digest episodes (consultant-rounds structure must not be disturbed).
- [x] **E — Parallelize per-turn TTS (2026-06-04).** `ThreadPoolExecutor` (default 8 workers, configurable via `cfg["tts_max_workers"]`) wraps TTS synthesis + per-turn loudness normalization. Pre-pass assigns guest voice indexes sequentially; `executor.map` preserves order; per-turn exceptions are caught and logged rather than propagated.
- [x] **F — `cache_control: ephemeral` (2026-06-04).** All system prompts wrapped in cached content blocks inside `_anthropic_text` (covers every named prompt automatically). Direct `client.messages.create` calls in `_legacy_research_and_script` also patched. Content-block caching for host-memory/research-brief skipped — no hit possible within a single episode run because each stage uses a different system prompt, so the cache prefix always differs. Primary wins: digest runs (3 shows share the same pipeline prompts; 2nd+3rd show hit cache for `_DIGEST_RESEARCH_SYSTEM` and all editing prompts).
- [x] **G — Proactive Telegram completion notification (2026-06-04).** Completion message now leads with "Done in Xm Ys. <Topic>" and includes the direct GitHub Pages audio URL + episode duration before the full manifest summary. Same treatment for digest completions. Failed runs also show elapsed time.
- [x] **H — Pin `requirements.txt`, run `pip-audit` (2026-06-04).** requirements.txt rewritten with exact pinned versions. 5 packages patched: aiohttp 3.14.0, idna 3.18, pillow 12.2.0, urllib3 2.7.0, setuptools 82.0.1. pip-audit now reports "No known vulnerabilities found" (torch/torchaudio/torchvision CUDA builds skipped — not on PyPI; torch 2.11.0+cu128 is far newer than any flagged CVE range).
- [ ] **J — $10/day Anthropic + OpenAI spend caps** (user-side billing consoles).

## P0/P0-B — closed

- [x] **A — Verify no real Telegram token in git history.** Verified clean 2026-05-30.
- [x] **B — A11y: non-color cue for active chapter.** Shipped `eb12edb`.

## Hygiene / recurring

- [x] **Re-enable work-dir cleanup (2026-06-04).** Uncommented `shutil.rmtree(work_dir)` — applied 2 days ahead of the planned 2026-06-06 date.
- [ ] **Telegram token rotation** (BotFather `/revoke @AsynchronousPodBot`). Not urgent; git clean.
- [ ] **On laptop checkout**: add `NCBI_EMAIL` (and optional `NCBI_API_KEY`) to `.env` for digests; `ELEVENLABS_API_KEY` + `CARTESIA_API_KEY` needed for audio (Fish key no longer used); `bash scripts/install-hooks.sh` for the per-clone pre-commit secret hook.

## P2 / nice-to-have queue (from deep review §4)

Pull from here when P1 is closer to done.
- Per-user rate limit in the Telegram bot.
- [x] Git commit topic sanitization (2026-06-04) — strips control chars; see above.
- ~~Delete or guard archived email-webhook code~~ — README already comprehensive; no change.
- ~~ffprobe timeout `clip_mixer.py:273`~~ — already had `timeout=30`; no change needed.
- [x] CLI topic-length cap (2026-06-04) — rejects topics >500 chars; see above.
- Verify MusicGen model is cached between intro and outro.
- `/queue` ETA display in the bot.
- Website loading state during initial `fetch(feedUrl)`.
- Microcopy capitalization consistency; snap spacing to a 4 px grid.
- Source-weaving rewrite pass (push named citations into dialogue).

## Flourishes (deep review §5 — when you have an evening)

- [x] **Closing callback (2026-06-05).** `_select_and_write_callback()` shipped. Sonnet picks from last 5 `usable_callback` entries, writes 2-4 turn closing exchange. Non-digest only. **Untested on a real run — listen to the tail of the next episode.**
- **Reading-room companion** — per-episode annotated reading list under a "Going Deeper" tab. (The digest source cards are a natural fit here.)
- **Generative chapter art** — one small abstract illustration per chapter (~$0.02/ep via FLUX-schnell).

## Parked: Phase 5 — clip + cue co-mixing (not pursuing for now)

Shelved 2026-05-30. Design kept in case clips are ever revisited:
- Clips and cues use two different insertion rulers — clips by text-marker position (`<<<CLIP_CUE>>>`, `assemble_with_clips` in `clip_mixer.py:317`), cues by turn index (`_tts_two_host` splice). A cue's "after turn 8" is meaningless inside a clip chunk starting at turn 5.
- Merge approach: unify on the turn-index ruler; one splice pass inserts both with a collision rule (clip-then-cue) when both land after the same turn. Skip-gate at `generate_podcast.py:3298`.
- If revived, decide rights stance first (published feed = cues only was the leaning).
