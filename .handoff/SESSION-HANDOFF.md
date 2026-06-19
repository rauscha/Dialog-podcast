# Session hand-off — 2026-06-17 (machine: desktop / RTX 4080, bot host)

## STATE (read this first)

- Branch: `main`, **clean and synced** with `origin/main` (HEAD `c6dd270`). One worktree
  only (`C:/Dialog-podcast`) — nothing stranded. Only untracked items are the two
  generated viewers `audio-scope-20260608-162543/` and `audio-scope-interplanetary/` —
  **intentionally local, do NOT commit.**
- Two phases this session: (1) fixed a bot bug that mislabeled every ad-hoc episode as a
  "digest"; (2) an overnight build of four tracks. All committed + pushed. The Telegram
  bot was restarted on the new code (**PID 39944**).
- **The open thread is entirely *listening*** — three audio/editorial things are built and
  verified mechanically but not yet heard/used on a real episode. Same blind spot that has
  bitten the audio twice. See "Next up."

## Done this session

- **Durable-manifest bug fix (`fa342f6`).** The bot's completion reply read "newest
  manifest on disk," but work-dir cleanup deletes each run's manifest, so it fell back to a
  stale June-4 *digest* manifest — which is why a Vienna episode came back labeled a digest.
  Now each run writes a durable manifest sidecar that survives cleanup. The Vienna episode
  itself was fine (main feed, all of B1–B4) — only the reply was wrong.
- **B4 enabled (`be96d15`).** `use_overlaid_backchannels=true` in config now, so the Vienna
  render ("When Vienna Stopped Believing in Politics") is the **first-ever B1+B2+B3+B4
  episode** — awaiting your ear.
- **Overnight build (4 tracks, `dc0abf9`…`a838564`):**
  - **Sonic-footnote BUGs A–D fixed** — loudnorm the clip, relevance floor, herald gate,
    single framing pad. Feature still `use_sonic_footnotes=false` pending your ear-check.
  - **Wikimedia Commons backend** — second cue source (morse/metronome/tuning-fork), license-
    filtered + attributed; verified live against the Commons API.
  - **P2 polish** — MusicGen model caching (was loading twice/episode), accessible website
    loading spinner, bot per-user rate limit + `/queue` ETA.
  - **Phase C first pass** — `anti_slop.py`, a standalone deterministic slop linter (report-
    only; not wired in — that's a deferred design call).
- Full detail in `.handoff/OVERNIGHT-LOG-2026-06-17.md`; deferred calls in
  `.handoff/PENDING-DECISIONS.md`; `NEXT-STEPS.md` reconciled.

## Next up

1. **Listen to the Vienna episode** (first B1–B4 render) — judge B3 disfluencies (hesitation,
   not tics) and B4 overlapping "mm-hmm" (natural vs. muddy). B4 is now ON by default; if it
   muddies, lower `backchannel_duck_db`/`backchannel_lead_ms` or set the flag back off.
2. **Ear-check render to re-enable sonic footnotes** — BUGs A–D are fixed; set
   `use_sonic_footnotes=true`, render a space/physics/music topic, listen, and commit the
   flip if it passes. (PENDING-DECISIONS #1.)
3. **Decide how to wire the anti-slop linter** — gate vs. warn, threshold, LLM critic, Phase
   C2. Run `python anti_slop.py <recent script>` first to calibrate. (PENDING-DECISIONS #2.)

## Watch out for

- **The recurring audio scar:** everything audio/editorial this session is verified
  mechanically, **not heard**. Treat footnotes + B3/B4 + the linter as unproven until a
  listen. The three "Next up" items all close that gap.
- **B4 is now enabled by default** (config) — affects the next main-feed episode. Digests are
  unaffected (they skip B3/B4).
- **`config.json` overrides DEFAULTS** — if an audio/footnote knob "isn't taking," check
  `config.json` first. The new footnote knobs (`sonic_footnote_min_overlap`, `_require_herald`,
  `_pad_ms`) are in DEFAULTS, not config, so they fall through correctly.
- **Two audio-scope dirs are untracked on purpose** — never commit them.
- **Standing TODO:** rotate the leaked @AsynchronousPodBot Telegram token via BotFather
  `/revoke` when convenient (git history verified clean).
