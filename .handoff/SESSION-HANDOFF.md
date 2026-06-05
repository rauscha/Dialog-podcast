# Session hand-off — 2026-06-05 (overnight build)

## STATE (read this first)

- Branch: `main`, clean, synced with `origin/main` ✅
- One worktree only — nothing stranded.

Overnight build is complete. Three features shipped:
1. **Turn enumeration consolidation** — cue placement and TTS splicing now count turns identically.
2. **Closing callback** — non-digest episodes now end with a ~60-second segment referencing a past episode.
3. **Sonic footnotes Phase 1.5** — better placement, smarter NASA source selection, LLM start-offset estimation.

**Both new features (callback + Phase 1.5) are untested on a real run.** Generating one episode and listening to the tail is the suggested first action.

## Done overnight

- **Turn consolidation** (commit `8ad0e31`) — `_enumerate_turns` now filters to known speakers via a `known_speakers` param; `prepare_footnotes` builds the set from cfg.
- **Closing callback** (commit `8ad0e31`) — `_select_and_write_callback()` added; Sonnet picks from last 5 `usable_callback` entries and writes a closing exchange. Non-digest only.
- **Phase 1.5** (commit `14a3cce`) — improved `_PLACEMENT_SYSTEM` prompt, `_select_best_nasa_result()` keyword scoring, `_estimate_start_offset()` Haiku call.

Full details in `.handoff/OVERNIGHT-LOG-2026-06-05.md`.

## Next up

1. **Test run** — generate one episode; listen to the closing ~90 seconds for the callback. Does it feel natural?
2. **Sonic footnotes Phase 2** — Wikimedia Commons backend.
3. **P1-J** — $10/day spend caps on Anthropic + OpenAI billing consoles (user-side).

## Watch out for

- The closing callback is appended *before* the performance pass — if Sonnet returns a segment that's too long or weirdly formatted, `_strip_to_dialogue` will clean it, but the performance pass is the safety net.
- `_estimate_start_offset` is gated on description ≥ 80 chars. Most short NASA targeted clips will just use the 5 s fallback — that's correct behavior.
- Digest episodes still get the old pipeline (no callback, no symmetry-break). If you ever want callbacks on digests, that's a one-line config flag away.
