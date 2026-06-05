# Overnight log — 2026-06-05

## Done overnight

### 1. Turn enumeration consolidation (commit `8ad0e31`)
`_enumerate_turns()` in `sonic_footnote_mixer.py` now accepts an optional `known_speakers` set. When provided, it skips any speaker label not in the set — exactly matching how `_parse_dialogue_turns()` in `generate_podcast.py` works. `prepare_footnotes()` now builds this set from `cfg` (host names + active guest labels) and passes it down, so cue *placement* and cue *splicing* count the same turns. This was the prerequisite for Phase 1.5.

### 2. Closing callback (commit `8ad0e31`)
New `_CLOSING_CALLBACK_SYSTEM` prompt + `_select_and_write_callback()` helper in `generate_podcast.py`. At the end of each non-digest episode, Sonnet picks the most thematically resonant entry from the last 5 `usable_callback` items in `episode_history`, then writes a 2-4 turn closing exchange (~120-150 words) that naturally references that prior episode. The segment is appended to `fact_checked_script` before the performance pass, so it gets emotion-tag treatment. Returns `None` cleanly if no good match exists. Digests are explicitly skipped (consultant-rounds structure must stay intact). `"closing_callback"` added to `script_passes` when used.

### 3. Sonic footnotes Phase 1.5 (commit `14a3cce`)

**Better placement prompt** — `_PLACEMENT_SYSTEM` now tells Sonnet to prefer natural breathing points (end of thought, after a punchline, after a summary sentence), avoid mid-explanation turns, and enforce a 3-turn minimum gap between consecutive cues. Previously the prompt just said "best placement" with no guidance on *what* makes a placement good.

**Smarter NASA source selection** — new `_select_best_nasa_result(items, cue)` scores all returned NASA items by keyword overlap with the cue's beat/reason/placement text before picking one to fetch. Deterministic; no extra LLM call. Previously the code just took the first result with a playable URL.

**LLM start-offset estimation** — new `_estimate_start_offset(item, cue, client)` asks Haiku where in a NASA recording the relevant moment is likely to start. Gated on description length ≥ 80 chars (sparse metadata → skip, use 5 s default). `client` now threads from `prepare_footnotes()` through `_resolve_cue()` to enable this. Previously a hardcoded 5-second skip was used for all files regardless of content.

---

## Waiting on you

*(none — no design decisions deferred)*

---

## Next up (suggested order)

1. **Listen to a new episode** — the closing callback and symmetry-break (P1-D) are both live but untested on a real run. Generate one episode and listen to the closing 90 seconds specifically. Does the callback feel natural, or forced?
2. **Sonic footnotes Phase 2** — Wikimedia Commons backend. The placement and source-selection machinery is now solid; extending it to a new source is the next expansion.
3. **P1-J** — your action: set $10/day spend caps on Anthropic + OpenAI billing consoles.
