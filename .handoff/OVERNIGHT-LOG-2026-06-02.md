# Overnight log — 2026-06-02 (laptop)

Pre-flight decisions (set at start):
- **Verify run:** all three shows (MFM + Fetal + AI), `SKIP_GIT=1` — produces episodes locally, does NOT publish.
- **Phase 4:** code-only build; do NOT register Task Scheduler entry or restart bot. User flips switches in the morning.
- **Sonic footnotes:** Phase 1.5 (LLM timestamp picker + smarter source selection).

Starting state: `main` at `4b9ce60` (digest editorial overhaul), in sync with origin.

## STATE timeline

- **Pre-run baseline:** `5f4c2db` on `main` (committed an auto-pipeline `host_memory.json` update that was sitting dirty: "Music AI Tools" episode memory). Tree clean.
- **Verify run launched** as background task `bdixy64wf` — sequential MFM → Fetal → AI with `SKIP_GIT=1`. Output streaming to `.handoff/verify-run.log`. Estimated ~30 min total. host_memory.json + feed-*.xml will go dirty by design (the publish step's `update_rss` writes them; SKIP_GIT only blocks the final git push).
- **Discovery during prep:**
  - **Bug "I" location confirmed.** `_write_companion_artifacts` at `generate_podcast.py:3088-3106` dumps `episode["tts_routes"]` verbatim — includes `voice_id` with partial truncation (e.g. `"wbih...s0wq"`). Fix: add `_public_tts_route` sanitizer returning `{provider, voice_label}` only, called in companion build.
  - **Phase 3.5 nested category location.** Channel RSS template at `generate_podcast.py:3298` emits flat `<itunes:category text="..."/>`. `_feed_meta_from_show` at `4149-4153` splits `"Science:Medicine"` on `:` and discards the subcategory (with a TODO comment). Fix: parameterize template to accept either a flat text or a child-tag block, generate the nested form from the colon-delimited string.
  - **Sonic 1.5 scope:** `sonic_footnote_mixer.py` resolves NASA cues by taking the first MP3 from progressive-shortening search + hard-coded `_DEFAULT_START_OFFSET_SEC=5.0`. Need (a) LLM picker over candidate items using their `title`/`description` against the cue's `beat`/`reason`, returning -1 (silence) when nothing matches; (b) LLM-estimated `start_offset_sec` based on item description so we don't grab podcast intros.
  - **Phase 4 (bot side):** `telegram_bot.py` already has `_run_generation` infra that spawns `generate_podcast.py` as subprocess. New `/digest`, `/digest_run`, `/digest_preview` commands mirror the `/generate` pattern. Lock + cancel reuse the existing `_pending_approvals`/`job_control` plumbing.
  - **Phase 4 (digest_ledger):** `last_run` already implemented at `digest_ledger.py:170-175` in `record_episode` (sets `aired_at`, `episode_url`, `recorded_keys`, `window`). Weekday gating just needs to *read* this and compare today vs `last_run.aired_at`. Tiny.

## Plan revised mid-flight (hand-off invoked)

User decided to publish all 3 verify episodes to `feed-mfm.xml` so he can listen on the morning drive (and sort into proper feeds later). Tried to redirect Fetal+AI to feed-mfm.xml by editing `digests.json` — **too late**: each subprocess loads `show` config at startup (`get_show` happens at `generate_podcast.py:4179`), and MFM had already finished (00:39:40) + Fetal already finished (00:49:28) when the edit landed. AI was already mid-run with show config locked. Reverted the digests.json edit (clean).

Actual timing from log:
- MFM: 00:30:11 → 00:39:40 (568s), wrote feed-mfm.xml + mfm_ledger.json
- Fetal: 00:39:40 → 00:49:28 (589s), wrote feed-fetal.xml + fetal_ledger.json (new files)
- AI: 00:49:28 → in flight, at thesis pass when last checked, ETA ~00:59

**Plan after AI finishes:**

1. Read all 3 script.txt files → log how form-first citations / lead-vs-rounds split / consultant register actually landed.
2. **Splice Fetal's `<item>` from feed-fetal.xml into feed-mfm.xml.** Same for AI's item from feed-ai.xml. (`update_rss` inserts before `</channel>`; just lift the item block.)
3. Delete feed-fetal.xml and feed-ai.xml (they only ever held one stub item each, never published).
4. Commit: feed-mfm.xml (3 items), 3 ledger updates (DOIs now legitimately covered since episodes are published), host_memory.json (3 memory entries), 9 episode artifact files, OVERNIGHT-LOG with findings.
5. Update NEXT-STEPS.md.
6. Write SESSION-HANDOFF.md.
7. Push to main.

Phase 3.5 polish, bug "I" sanitizer, Sonic 1.5, Phase 4 — all deferred to next session.

## Done overnight

(filled in at morning write-up)

## Waiting on you (decisions / gated tasks)

(filled in as items get deferred)
