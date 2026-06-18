# Pending decisions — from the 2026-06-17 overnight run

Two items need your call; the bot restart is already handled. Full detail in
`.handoff/OVERNIGHT-LOG-2026-06-17.md`.

## 1. Ear-check render to re-enable sonic footnotes
Sonic-footnote BUGs A–D are all fixed (loudnorm, relevance floor, herald gate, single
frame) and the Wikimedia Commons backend is in — but the feature stays
`use_sonic_footnotes=false` per your decision. To re-enable: set it `true` in
`config.json`, render a topic that draws a NASA- or Commons-backed cue
(space/physics/music subject), and listen for: audible at program level (A), relevant
clip (C), a host line that sets it up (B), clean framing (D). If it passes, commit the
flag flip. Tuning knobs: `sonic_footnote_min_overlap` (→2 for stricter), `_pad_ms`,
`_require_herald`.

## 2. Phase C — wire in the anti-slop linter?
`anti_slop.py` works standalone (report-only). Before making it part of the pipeline,
decide:
- **Gate vs. warn** — block + regenerate on a low score, or just log? (Regen = cost/latency.)
- **Threshold + attempts** — what score is "too sloppy," how many regen tries?
- **LLM critic layer** — add a Sonnet critic for subtler slop, or stay deterministic?
- **Phase C2** — per-persona vocab (Juno/Caspar) + enforced disagreement (not started).

Suggested: run `python anti_slop.py <recent script>` first to calibrate on real output;
lean warn-only, threshold ~60, deterministic-only until proven.

---
_Bot restart (rate-limit + ETA activation) was completed during the run — no action
needed._
