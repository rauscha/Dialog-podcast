# Session hand-off — 2026-06-03 (machine: desktop)

## STATE (read this first)
- Branch `main`, clean, in sync with origin.
- **The digest pipeline is fully operational end-to-end.** Task Scheduler registered and tested, Telegram bot running with all `/digest` commands live, `feed-fetal.xml` + `feed-ai.xml` submitted to Spotify. Daily weekday digests will now fire automatically.

## Done this session
- Task Scheduler entry registered (user ran `register_scheduled_task.ps1` as Admin).
- Telegram bot killed and restarted — `/digest`, `/digest <show>`, `/digest all`, `/digest_preview` all live.
- `feed-fetal.xml` and `feed-ai.xml` submitted to Spotify for Creators.
- Reviewed full NEXT-STEPS list; no new code landed this session.

## Next up
1. **Listen to the 3 verify episodes** (in `feed-mfm.xml`) — decide whether to prune the Fetal/AI items from MFM now that proper feeds exist.
2. **Phase 3.5 polish** — nested `<itunes:category>` + tighten `_strip_to_dialogue` regex (small, ~30 min).
3. **P1-E — Parallelize per-turn TTS** (`ThreadPoolExecutor`) — biggest wall-clock speed win still outstanding.
4. **Re-enable work-dir cleanup on 2026-06-06** — uncomment `shutil.rmtree(work_dir)` in `generate_podcast.py` (3 days away).

## Watch out for
- **Cleanup date is 2026-06-06** — 3 days away. Don't miss it or debug artifacts accumulate indefinitely.
- **`feed-mfm.xml` has 4 items** including Fetal + AI verify copies. They're there on purpose for morning listening; prune after listening if they don't belong long-term.
- **Spotify approval** for the two new feeds can take a day or two; check back to confirm they're indexed.
- **Ledgers are set.** 15 papers from the 3 verify episodes are recorded as covered. If an episode turns out bad and you want those papers to resurface, delete the relevant DOI entries from `digests/mfm_ledger.json`, `digests/fetal_ledger.json`, or `digests/ai_ledger.json`.
