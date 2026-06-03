# Session hand-off — 2026-06-03 (machine: laptop)

## STATE (read this first)
- Branch `main`, clean, in sync with origin. Two commits ahead of this morning: `cde0f97` + `bb5a70a`.
- **Phase 4 shipped.** The scheduling + bot digest layer is fully code-complete. Two things need a one-time manual flip before they run: (1) register the Task Scheduler entry, (2) restart the Telegram bot.
- **Three proper per-show feeds are live on GitHub Pages.** `feed-mfm.xml`, `feed-fetal.xml`, `feed-ai.xml` — each with correct channel metadata and cover art. Two new feeds need to be submitted to Spotify.

## Done this session
- **`feed-fetal.xml` + `feed-ai.xml` created (`cde0f97`).** Copied (not moved) the Fetal/AI verify episodes from `feed-mfm.xml`. MFM untouched — all 4 items still live for the morning drive.
- **Phase 4 complete (`bb5a70a`):**
  - `generate_podcast.py`: `_show_is_due()` (weekday gating + 1-day catch-up window), `run_all_due_digests()`, `--digest-all` (gated, for Task Scheduler), `--digest-force-all` (bypass gating).
  - `telegram_bot.py`: `/digest` (status list), `/digest mfm/fetal/ai` (run one show), `/digest all` (run all, force), `/digest_preview mfm` (dry-run ranking → Telegram reply). All share the existing generation lock + cancel plumbing.
  - `run_digests.ps1`: daily Task Scheduler entry point (loads `.env`, calls `--digest-all`).
  - `register_scheduled_task.ps1`: one-shot registration, run once as Admin.

## Next up
1. **Register the Task Scheduler entry** — run `.\register_scheduled_task.ps1` as Administrator. Test immediately: `Start-ScheduledTask -TaskName "Dialog-podcast-daily-digests"`. Check result: `Get-ScheduledTaskInfo -TaskName "Dialog-podcast-daily-digests" | Select-Object LastRunTime, LastTaskResult`.
2. **Restart the Telegram bot** so `/digest` commands are live (`python telegram_bot.py`).
3. **Submit Fetal + AI feeds to Spotify for Creators:** `https://rauscha.github.io/Dialog-podcast/feed-fetal.xml` and `https://rauscha.github.io/Dialog-podcast/feed-ai.xml`.
4. **After listening to the 3 verify episodes:** decide whether to prune the Fetal/AI items from `feed-mfm.xml` (they're duplicated there by design for now). If any episode is bad, also remove its DOIs from the relevant ledger so papers can resurface.
5. **Phase 3.5 polish** (small, optional before anything else): nested `<itunes:category>` + `_strip_to_dialogue` regex tightening.

## Watch out for
- **The Task Scheduler task doesn't exist yet** — `register_scheduled_task.ps1` must be run as Admin on the machine that will run the nightly jobs (the desktop, presumably). Until then, digests only run when you trigger them manually or via `/digest` in Telegram.
- **Bot needs a restart** to pick up the new `/digest` commands. If the bot is already running as a background process, kill it and re-launch.
- **`feed-mfm.xml` has 4 items** (inaugural + 3 verify copies). Once you've listened and are happy, the Fetal and AI items can be pruned from it. No rush — the GUIDs are unique so podcast apps won't duplicate.
- **Ledgers are set.** The 15 papers from the 3 verify-run episodes are recorded as covered. If you decide an episode was bad and want those papers to resurface, delete the relevant DOI entries from `digests/mfm_ledger.json`, `digests/fetal_ledger.json`, or `digests/ai_ledger.json`.
