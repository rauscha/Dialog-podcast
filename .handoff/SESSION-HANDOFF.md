# Session hand-off — 2026-06-08 (machine: desktop / RTX 4080)

## STATE (read this first)

- Branch: `main`, **clean and synced** with `origin/main` (HEAD `478a04b`). One worktree only — nothing stranded. Only untracked item is `audio-scope-interplanetary/` (a generated HTML viewer, intentionally local — do not commit).
- This session did the **Phase A live-render verification** that the 2026-06-06 hand-off asked for, and it paid off twice: it caught a **loudness-config bug** (fixed) and exposed the **sonic-footnote feature as not-ready** (now gated off by ear). Both are committed + pushed. The audio engineering (master/de-ess/crossfade) itself sounded fine; the cue feature did not.

## Done this session

- **Verified Phase A on a real render** — "The Last Problems Before Mars" (10:08), published live (`21b09a3`). Closing callback ✅ fired, crossfades + de-ess (0.40) ✅ ran. The new master/de-ess/crossfade was finally *heard*, not just measured.
- **Fixed a loudness-config bug** (`7aba039`): `config.json` still pinned the pre-Phase-A `-16 LUFS / -1.5 dBTP`, which **overrides DEFAULTS** in the priority chain — so every real render was landing at ~-16, not the Phase A target -14. Isolation tests missed it because they called `two_pass_loudnorm` with explicit -14 args, bypassing the config layer. Config now `-14.0 / -1.0`. The already-published episode was left at its -16 (valid spec) per user call.
- **Gated off sonic footnotes** (`478a04b`): first real cue render (`nasa_mars_wind`) was judged **garbage by ear** — quiet, irrelevant, unheralded, mushy. Set `use_sonic_footnotes=false` in `config.json`. Code-confirmed root causes documented in NEXT-STEPS as **BUGs A–D**:
  - **A (the big one):** footnote audio is the *only* source never loudnorm'd; the master's constant linear gain can't rescue a quiet clip next to loud speech.
  - **B:** no guaranteed herald — orphan clip when the dialogue model skips the setup beat.
  - **C:** no relevance floor — a 0-match NASA result still ships (query degraded `NASA Mars wind`→`NASA Mars`).
  - **D:** stacked fades (0.4s self + 180ms gap + 10ms crossfade), no framing/duck.

## Next up

1. **Phase B1 — emotion threading** (~30-min quick win): thread the prior turn's emotion tag into `_build_tts_instructions` so prosody transitions don't hard-reset. Compute `turns[i-1]` tag *before* the thread pool. (Was next-in-queue before the cue detour.)
2. **Sonic-footnote redesign** (feature is safely off — do when ready): fix in order **A → C → B → D** (see NEXT-STEPS "Cue quality & editorial polish"). BUG A (loudnorm the clip, mirror clip_mixer A4) is the single clearest win and unblocks re-enabling. **Don't re-enable until a live render passes a listen.**
3. **Confirm a real render actually lands at -14 LUFS** — the config fix is committed but unverified live; true-peak-limited linear loudnorm may undershoot to ~-15 without a limiter. Check the next episode's loudnorm summary (rides along on any future render).

## Watch out for

- **Two features now have the same scar:** Phase A and sonic footnotes both shipped on measurement-only verification and both hid a blind spot that only a *listen* caught. Treat "verified in isolation" as "not verified" for anything audible.
- **`config.json` overrides DEFAULTS** — when an audio knob "isn't taking," check config.json first (that was the -16 bug). config.json does *not* carry `audio_deesser_intensity`, `audio_master_two_pass`, `concat_crossfade_ms`, or `music_crossfade_sec`, so those correctly fall through to DEFAULTS.
- **`audio-scope-interplanetary/`** is untracked and intentional — it's the click-to-seek viewer for this episode. Leave it local or delete it; don't commit it.
- **Work-dir cleanup is re-enabled** — intermediate turn/clip/footnote files are deleted on success, so you can't inspect a render after the fact. Comment `shutil.rmtree` (`generate_podcast.py`, search "rmtree") for a run you need to debug.
- **A scheduled digest task is live** and auto-commits to `origin/main` on its weekday cadence. **Pull before starting work**; it may leave `ai_ledger.json`/`host_memory.json` uncommitted — check `git status` on pickup.
- **Standing TODO:** rotate the leaked @AsynchronousPodBot Telegram token via BotFather `/revoke` when next at the home machine (git history verified clean).
