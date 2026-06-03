# Session hand-off — 2026-06-03 (machine: laptop)

## STATE (read this first)
- Branch `main`, clean, in sync with origin.
- **Three new digest episodes just published to `feed-mfm.xml`** (all 4 items: prior MFM real + 3 overnight verify episodes). Cover art will show as MFM Rounds for all three — that's intentional; sort into the right feeds later.
- Digest editorial overhaul (form-first citations + headline-vs-rounds + consultant register) **verified live across all 3 shows**. Prompts landed cleanly.
- Phase 3.5 polish, Phase 4 scheduling, Sonic 1.5, bug "I" — all queued, none touched.

## Done this session
- **Juno voice swap → Jessa "Easygoing and Effortless"** (`c54e068`). New ElevenLabs ID `yj30vwTGJxSHezdAGsv9`, validated 13/13.
- **Digest editorial overhaul** (`4b9ce60`): three coordinated changes addressing live MFM feedback (sounded influencer-y; no titles/authors/n; lead-vs-rounds indistinct).
  - `first_author` plumbed through PubMed + Europe PMC parsers → ranker → digest card → show-notes labels (now render `Wright et al. - AJOG - 2026 - Title`).
  - `_DIGEST_RESEARCH_SYSTEM` rewritten to require `headline_intro` (one spoken citation sentence per paper, journal/year/author/design/n form), `rounds_intros[]`, and `structural_plan` (`headline_share`, `rounds_share_each`, literal `pivot_line`).
  - New `_DIGEST_PERFORMANCE_OVERLAY` appended to thesis/beat-sheet/dialogue-draft/anti-cliche/performance prompts when `episode_type=="digest"`. Explicitly overrides the main-feed "move source detail to show notes" rule and the curiosity-radio "Juno opens with an image" rule.
- **Overnight verify-run** (28 min, ~$10 in API tokens) — all 3 digest shows generated end-to-end with `SKIP_GIT=1`. Scripts inspected; new prompts are clean across the board (form-first intros land verbatim, "Rounds — four other things this week" pivot lands, no metaphor opens, no influencer phrasings).
- **Three verify episodes published to `feed-mfm.xml`** per user direction so they can be heard on the morning drive. Titles: "Preterm Birth and the Decades After" (MFM verify), "When Sequencing Beats the Microarray" (Fetal verify), "Validation Rigor Separates Signal From Noise" (AI verify). `feed-fetal.xml` and `feed-ai.xml` stubs deleted (only ever held the verify items; never went live).

## Next up
1. **Listen to the 3 verify episodes on the drive.** They're in `feed-mfm.xml` so any podcast app pointed at `feed-mfm.xml` will pick them up after GitHub Pages serves them. If a podcast app doesn't auto-refresh, force a feed refresh.
2. **Sort the Fetal + AI episodes into their proper feeds** (`feed-fetal.xml`, `feed-ai.xml`) after listening. Just move their `<item>` blocks. Channel art will then display correctly. This is a 10-min task — could be its own follow-up session.
3. **Phase 4 — scheduling + on-demand.** `run_all_due_digests` + `--digest-all` + weekday gating + bot `/digest` commands. Hand-off note from yesterday still stands: recommend a fresh session for this (cron/bot/Windows scheduler are a different subsystem from prompt work). Plan + file pointers documented in `.handoff/OVERNIGHT-LOG-2026-06-02.md` so resumption is fast.
4. **Phase 3.5 polish** — nested `<itunes:category>` + `_strip_to_dialogue` regex tightening. Small, queued.
5. **Bug "I"** — strip ElevenLabs voice IDs from companion JSON. Sanitizer function spec documented in overnight log.
6. **Sonic 1.5** — LLM timestamp picker + smarter source selection (your "wins over Phase 2" note). Plan documented in overnight log.

## Watch out for
- **All 3 ledgers updated**: `mfm_ledger.json` (5 new DOIs), `fetal_ledger.json` (5 DOIs, new file), `ai_ledger.json` (5 DOIs, new file). Those 15 papers are now "covered" and will be skipped by future scheduled runs. **If after listening you decide any episode is bad and you don't want it shipped**, you'll want to remove that show's verify entries from its ledger so the papers can resurface next run. The ledger's `last_run.recorded_keys` list tells you exactly which keys to delete.
- **All 3 episodes appear under "MFM Rounds" cover art** in podcast apps because they're in `feed-mfm.xml` whose channel image is the MFM cover. Resolved when you sort them into proper feeds (next-up #2).
- **`digests.json` is unchanged.** Earlier I tried to redirect Fetal+AI to `feed-mfm.xml` via that config file but the subprocesses had already locked their show config at startup (`get_show` is called once per run, before any of my edits could take effect). Reverted cleanly. **Future scheduled MFM/Fetal/AI runs will write to their proper feeds — no leftover misconfiguration.**
- **`run_id` from your `/loop` mode** — there is no autonomous loop; you can pick up cleanly with `/pick-up` from any machine.
- **`.handoff/run-verify.ps1`** was a helper for the overnight verify-run. Keeping it around in case useful next time, but you can delete it if it's clutter.

## Quick-reference paths
- MFM verify script: [episodes/20260603_003154_mfm_rounds_-_week_of_2026_06_03_work/script.txt](episodes/20260603_003154_mfm_rounds_-_week_of_2026_06_03_work/script.txt)
- Fetal verify script: [episodes/20260603_004102_the_fetal_frontier_-_week_of_2026_06_03_work/script.txt](episodes/20260603_004102_the_fetal_frontier_-_week_of_2026_06_03_work/script.txt)
- AI verify script: [episodes/20260603_005046_signal_in_the_scan_-_week_of_2026_06_03_work/script.txt](episodes/20260603_005046_signal_in_the_scan_-_week_of_2026_06_03_work/script.txt)
- Detailed overnight notes (plans, file pointers, design choices): [.handoff/OVERNIGHT-LOG-2026-06-02.md](.handoff/OVERNIGHT-LOG-2026-06-02.md)
