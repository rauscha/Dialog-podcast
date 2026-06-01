# Session hand-off — 2026-05-31 (machine: desktop / CRANE-DESK)

## STATE (read this first)
- Branch: `main`, clean + synced with `origin/main` after this hand-off. Only the main worktree exists — nothing stranded anywhere.
- **A new feature was planned, approved, and its Phase 1 shipped: "Asynchronous Rounds" — three weekly auto-generated journal-digest shows** (MFM Rounds / The Fetal Frontier / Signal in the Scan) for the commute. Phase 1 is the **ranking engine only — it generates NO audio, writes NO files, publishes nothing.** It picks the most important recent papers per field and prints a ranked table. Validated live across all three shows and the picks look genuinely good.
- This session also committed the **prior session's pending voice work** (Juno/Caspar doc sweep, cross-provider Cartesia guests, per-turn loudness, voice-ID validation) that had been sitting uncommitted. The whole TTS-provider question from the last hand-off is now closed.

## Done this session
- **Planned + approved the digest feature.** Full plan: `C:\Users\andre\.claude\plans\idempotent-strolling-riddle.md` (read it before Phase 2). Key decisions: headline + 3–5 rounds format, rolling 6-month window, sub-brand under Juno/Caspar, 3 separate feeds, citation-free ranking.
- **Shipped Phase 1** (`58d0a67`): `digest_sources.py` (PubMed/Europe PMC/Altmetric/SCImago clients, all soft-fail), `digest_ranker.py` (discover→ledger-filter→enrich→batched-LLM→score→pick), `digest_shows.py` + `digests.json` (3 shows), `digest_ledger.py` (DOI ledger), `assets/sjr_2024.csv` (quartile table), `digest` episode type, `--digest-dry-run <show>` CLI. Soft-failure + copyright firewall tested.
- **Committed prior voice finalization** (`ff6715c` docs + validator; `58d0a67` carries the config/engine parts): ElevenLabs hosts + Cartesia guests, Fish dropped, per-turn loudness, 13/13 voices validated.

## Next up
1. **Phase 2 — digest episode type + research branch (generates the first real audio).** Extract `_script_from_research_package`, add `_digest_research_and_script` (cloud research model, NO tools, paraphrase-only), branch on `cfg["digest_articles"]`, `_run_with_cfg` + `run_digest(show_id)` + `--digest` CLI. Plan §"Build phases". **Recommend a fresh session for this** — it's a different subsystem.
2. **Phase 3** multi-feed publishing, then **Phase 4** scheduling (Task Scheduler) + bot `/digest`.
3. Optional: eyeball more `--digest-dry-run` output and tune the LLM ranking prompt before spending audio.

## Watch out for
- **Phase 1 publishes nothing.** No feeds, no episodes, no audio. The dry-run is read-only. Don't expect a feed yet.
- **Ranking is LLM-dominant on fresh papers** — Altmetric is empty for papers <6 wk old (404→None), so its weight renormalizes onto the LLM. By design; tune the LLM prompt, not the weights.
- **Quartile CSV is a curated 12-journal table**, not the full SCImago export (SCImago returns 403 to scripted downloads). Drop the official export into `assets/sjr_*.csv` and it supersedes (newest filename wins).
- **The `digest` episode type is already registered** in `episode_types.py` (pulled forward so show config validates). Don't re-add it in Phase 2.
- **Shared-file commit note:** `58d0a67` also contains the cross-provider-guest + per-turn-loudness changes, because `config.json`/`generate_podcast.py`/`.env.example` were touched by both that prior effort and the digest work (couldn't cleanly split without interactive staging).
- **Laptop pickup:** add `NCBI_EMAIL` (+ optional `NCBI_API_KEY`) to `.env` for digests; `ELEVENLABS_API_KEY` + `CARTESIA_API_KEY` for audio (Fish key no longer used); `bash scripts/install-hooks.sh` for the pre-commit secret hook.
- **Pre-existing bug:** RSS `<description>` leaked a fact-check preamble (`_strip_to_dialogue` anchors on first `SPEAKER:` line). Noted in NEXT-STEPS; digests share the path.
- **Standing carryovers:** work-dir cleanup re-enable 2026-06-06; Telegram token rotation (not urgent, git clean); CRLF→LF warnings on commit are benign.
