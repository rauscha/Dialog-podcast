# Overnight log — 2026-06-05

## In progress

*(none — all tasks complete)*

---

## Done

- [x] **Turn enumeration consolidation** — `_enumerate_turns` now accepts `known_speakers`; `prepare_footnotes` builds the set from cfg. Commit `8ad0e31`.
- [x] **Closing callback** — `_select_and_write_callback()` + `_CLOSING_CALLBACK_SYSTEM` prompt added. Non-digest only. Commit `8ad0e31`.
- [x] **Phase 1.5** — three improvements committed separately:
  - Better `_PLACEMENT_SYSTEM` prompt: prefers natural breathing points, enforces 3-turn min gap, avoids mid-explanation turns.
  - `_select_best_nasa_result(items, cue)`: keyword-overlap scoring before URL fetch.
  - `_estimate_start_offset(item, cue, client)`: Haiku call estimating best clip start (gated on description richness ≥80 chars).

---

## Deferred

*(none yet)*
