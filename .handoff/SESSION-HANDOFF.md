# Session hand-off — 2026-06-09 (machine: desktop / RTX 4080)

## STATE (read this first)

- Branch: `main`, **clean and synced** with `origin/main` (HEAD `3528689`). One worktree only (`C:/Dialog-podcast`) — nothing stranded. Only untracked items are two generated HTML viewers, `audio-scope-20260608-162543/` and `audio-scope-interplanetary/` — **intentionally local, do NOT commit.**
- This session finished **Phase B** of the quality-upgrade plan: B3 (disfluency/backchannel script pass) and B4 (overlaid backchannels) are both built, committed, and pushed. **Phase B (B1–B4) is now feature-complete.** No code is waiting; the open thread is entirely a *listening* one — none of B3/B4 has been heard on a real episode yet.

## Done this session

- **Phase B3 — disfluency / backchannel pass (`ba6479a`).** New `_DISFLUENCY_SYSTEM` LLM stage between symmetry-break and fact-check (non-digest only; runs before fact-check so corrections still apply). Adds a *sparse* speech-realism layer: soft disfluencies before hard words (shaped `filler → pause → connector`, e.g. "the clever bit is — um, so, it's…", placed before the important word) and short backchannel turns ("mm-hmm"/"right") as their own lines for the listening host. Density-capped ~1 per 6 turns. Flag-gated `use_disfluency_pass` (default **on**); off or digest ⇒ script byte-identical. Verified on a real LLM call (B3's acceptance = *read the diff*, not ear): 8-turn sample drew exactly one disfluency + one backchannel, facts intact, em-dashes are genuine U+2014 (the `�` in console was just cp1252).
- **Phase B4 (stretch) — overlaid backchannels (`fa9f990`).** Folds B3's short reaction turns onto the *tail* of the talking host's line as a ducked overlay instead of a sequential segment. `_overlay_backchannel`: delay bc to start `backchannel_lead_ms`(120) before base ends, duck `backchannel_duck_db`(8), `amix normalize=0` (default halving would gut the main voice), `alimiter ~-1 dBFS` clip insurance. `_is_backchannel_turn`: diff speaker + non-question + ≤`backchannel_max_chars`(20). Fold pre-pass runs before the B2 gap interleave; only targets the immediately-prior real turn, never one already overlaid; best-effort (overlay failure ⇒ sequential, never load-bearing). **Flag `use_overlaid_backchannels` default OFF** (higher-risk mixing; enable only after an ear-check). Off ⇒ assembly byte-identical to pre-B4. Verified mechanically only: detection correct on all 5 cases; real-audio mix lands the overlap exactly where designed (base 2.0s → bc delayed 1.88s → mixed 2.33s), stereo+rate preserved, no clip.
- **NEXT-STEPS.md** updated: B3 and B4 both marked done with full detail; Phase B noted feature-complete.

## Next up

1. **One live render to clear the whole Phase-B listening backlog.** Render any topic **with `use_overlaid_backchannels=true`** — that single episode exercises B1+B2+B3+B4 at once. Then listen for: (B1) prosody flowing across cuts; (B2) timing/breath, no clipped onsets; (B3) disfluencies reading as hesitation, **not tics**; (B4) the "mm-hmm" overlapping naturally vs. muddying the main voice. All knobs are config if tuning is needed (`backchannel_*`, `turn_gap_*`, `turn_edge_*`, `use_disfluency_pass`).
2. **If B4 muddies:** first lever is `backchannel_duck_db` (raise to 10–12) or `backchannel_lead_ms` (lower to ~80 so less overlap); if disfluencies feel tic-y, tighten the B3 prompt density cap. If B4 just doesn't earn its complexity, leaving the flag off costs nothing.
3. **Then Phase C** — anti-slop critic + gate (C1); persona vocabulary + enforced disagreement (C2, small). Next code phase once Phase B is heard and signed off.

## Watch out for

- **The recurring audio scar:** Phase A and sonic-footnotes both shipped on measurement-only verification and both hid a blind spot only a *listen* caught. B3/B4 are verified mechanically but **not heard** — treat them as unproven until the render above is listened to. B4 especially (mixing graph) ships off for exactly this reason.
- **Two audio-scope dirs are untracked on purpose** — generated viewers, leave local or delete; never commit.
- **`config.json` overrides DEFAULTS** — if an audio knob "isn't taking," check `config.json` first (that was the old −16 LUFS bug). The new B3/B4 flags are *not* in config.json, so they fall through to DEFAULTS (B3 on, B4 off) correctly.
- **`.env` is not auto-loaded** by `generate_podcast.py`. The CLAUDE.md PowerShell loader throws cosmetic "String cannot be of zero length" errors on blank `.env` lines — harmless (only blank lines fail; real KEY=value lines set fine). A Python-side loader dodges it. Cosmetic papercut, not yet fixed.
- **Work-dir cleanup is live** (`shutil.rmtree` on success) — comment it out for any run you need to inspect afterward.
- **Standing TODO:** rotate the leaked @AsynchronousPodBot Telegram token via BotFather `/revoke` when next at the home machine (git history verified clean).
