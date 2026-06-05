# Session hand-off — 2026-06-05 (machine: desktop)

## STATE (read this first)

- Branch: `main`, clean, synced with `origin/main` ✅
- One worktree only (the main one) — nothing stranded.

Everything in P1 is done except P1-J (spend caps, user action on billing
consoles). The quick-wins batch is also complete. The scheduler fired the
Signal in the Scan digest this morning and the run data is committed.
**Next meaningful work: closing callback** (Flourish — last ~60 s of each
episode references a prior episode via host_memory.json).

## Done this session

- **P1-D** (commit 126886f) — Turn symmetry break: `_SYMMETRY_BREAK_SYSTEM`
  Sonnet pass sits between anti-cliche and fact-check; injects 3-5
  interruptions/clusters/host-heavy beats per episode. Skipped for digests.
- **P1-H** (commit 126886f) — Security pins + pip-audit: `requirements.txt`
  fully pinned; patched aiohttp 3.14.0, idna 3.18, pillow 12.2.0, urllib3
  2.7.0, setuptools 82.0.1. `pip-audit --local` → "No known vulnerabilities."
- **Quick-wins batch** (commit 2141266):
  - Surface dropped cues: `sonic_footnote_mixer.py` now logs warnings at
    every silent-drop point (unimplemented backend, LLM placement miss,
    download failure) + summary "N/M cues dropped" line.
  - NASA fallback fix: 2-word query minimum + `_is_nasa_podcast_item()`
    filter so podcast episodes can't be selected as cues.
  - CLI topic cap: `generate_podcast.py` rejects topics > 500 chars.
  - Git commit sanitization: control chars stripped from `safe_topic`.
  - Two items confirmed already-done: ffprobe timeout, email-webhook README.
- **Scheduled run** (commit 8492dc9) — Signal in the Scan fired ~05:01 UTC,
  5 DOIs recorded in ai_ledger.json; host_memory updated.

## Next up

1. **Closing callback** (highest leverage / evening project) — final ~60 s
   references a prior episode. `host_memory.json` has `usable_callback` fields
   ready; needs a new prompt pass + wiring into `_script_from_research_package`.
   See NEXT-STEPS.md § Flourishes.
2. **Sonic footnotes Phase 1.5** — LLM timestamp picker. Prerequisite first:
   consolidate the two different turn-enumeration functions so cue placement
   and cue splicing agree on turn counts (see NEXT-STEPS.md § Cue quality).
3. **P1-J** — $10/day Anthropic + OpenAI spend caps. User action on billing
   consoles; nothing to code.

## Watch out for

- `setuptools 82.0.1` is installed; `torch 2.11.0+cu128` declares
  `setuptools < 82` as a build-time (not runtime) constraint. Safe for now.
  If torch/audiocraft ever breaks mysteriously, try `pip install setuptools==79`.
- P1-D adds one Sonnet call per non-digest episode (7 LLM calls total vs 6).
  Watch per-episode cost as episode lengths grow.
- MFM digest is Mon, Fetal is Wed, AI/Signal is Thu — all three Spotify feeds
  submitted. Next manual TODO: listen to recent episodes for quality check.
