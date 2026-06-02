# Pending decisions — handoff 2026-06-01

Four open decisions surfaced at the end of Phase 3. None block the next session,
but the laptop-only artifacts (#1) will rot if you don't pick a path within a
few days.

## 1. Publish the smoke MFM Rounds episode? (laptop-only artifacts)

**What's sitting on the laptop, uncommitted:**
- `feed-mfm.xml` (11.5 KB) — the actual RSS feed file
- `digests/mfm_ledger.json` (3.3 KB) — DOI ledger with the 5 covered papers
- `episodes/20260601_203813_mfm_rounds_-_week_of_2026_06_02.mp3` (13.1 MB mastered)
- `episodes/20260601_203813_mfm_rounds_-_week_of_2026_06_02.chapters.json`
- `episodes/20260601_203813_mfm_rounds_-_week_of_2026_06_02.companion.json`
- Also: an earlier Phase 2 smoke at `episodes/20260601_190410_*` (~13 MB MP3 + JSONs) — same paper set, different episode title ("When Aspirin Delays Rather Than Prevents"), can probably delete.

**Options:**
- **(a) Ship as-is.** `git add` the Phase 3 set + `feed-mfm.xml` + `digests/`, commit "Publish MFM Rounds inaugural episode", push. Then submit `https://rauscha.github.io/Dialog-podcast/feed-mfm.xml` to Spotify for Creators.
- **(b) Listen + decide.** MP3 is at the path above. Quality verdict from this session: peer-level, study-design framing, no leaks. But you haven't actually heard it.
- **(c) Re-run on desktop fresh.** `python generate_podcast.py --digest mfm` will produce a slightly different episode against the same paper set (the ledger from this run was never committed, so PubMed will return the same candidates).

## 2. Cover-art re-roll for MFM and AI?

Quick honest read on the SDXL output (committed in `98ad4b2`):
- `cover-mfm.jpg` — navy vertical stripes on cream. Reads as a vintage book cover; not specifically medical. **Weakest.**
- `cover-fetal.jpg` — indigo + coral topographic ridges. **Strongest** — has motion and drama, frontier theme reads.
- `cover-ai.jpg` — mint green nested grids. Generic geometric; not specifically AI/radiology.

**Options:**
- **(a) Ship the placeholders.** Fine for soft-launch, can iterate later.
- **(b) Re-roll MFM + AI on this machine.** Edit the `(seed, prompt)` tuple in `scripts/gen_covers.py` and run `python scripts/gen_covers.py mfm ai`. ~30 s per cover. Try different seeds first (cheapest), then prompt-tune if still weak.
- **(c) Switch to FLUX-schnell.** Better aesthetics but needs HF auth: create an HF token, `huggingface-cli login`, accept the FLUX terms page once. Then swap `MODEL_ID` and pipeline class in `scripts/gen_covers.py` back to the FLUX path (4 steps, guidance_scale=0).

## 3. Clean up the historical `feed.xml` preamble leak?

The published `feed.xml` entry from 2026-05-07 ("The history of fetoscopy" topic) still has fact-check preamble in its `<description>`. The Phase 3 fix protects future writes; the old entry is grandfathered.

**Options:**
- **(a) Leave it.** It's old, listeners have moved on, low impact.
- **(b) Hand-edit `feed.xml`.** Find the `<item>` and rewrite its `<description>` + `<content:encoded>` CDATA blocks. ~10 min careful edit.
- **(c) Re-run the episode + replace.** Heavier; only worth it if you wanted to update that topic anyway.

## 4. Phase 4 — scheduling + on-demand?

The plan from `idempotent-strolling-riddle.md`. Roughly: `run_all_due_digests`, `--digest-all`, per-show weekday gating with `last_run`, `run_digests.ps1` + one daily Windows Task Scheduler entry, Telegram bot `/digest` command (with list / preview variants).

**Recommend a fresh session for Phase 4** per global preference — it's a different subsystem (cron / bot / Windows scheduler) than the Phase 3 RSS work.
