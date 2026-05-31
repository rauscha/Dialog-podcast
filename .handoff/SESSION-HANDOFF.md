# Session hand-off — 2026-05-31 (machine: desktop / CRANE-DESK)

## STATE (read this first)
- Branch: `main`, working tree clean, synced with `origin/main`. No unpushed commits, no stray worktrees.
- **The whole session's deliverable is three MP3s waiting on a back-to-back listen.** The user gave his BBQ-episode verdict (cue is a complete miss; guest barely distinguishable but workable; **OpenAI voices feel stilted vs ElevenLabs/Fish Audio in his other projects**). That pivoted priority: voice quality is now the top lever, above all cue work.
- This session built Fish Audio as a third TTS provider, then ran a triple comparison so he can A/B/C OpenAI vs ElevenLabs vs Fish Audio on the same 6-turn script. **The listen has NOT happened yet.** His verdict picks the new default provider, gates voice swaps, and only then does cue work resume.

## Done this session
- **Confirmed cue + voice verdict** from the BBQ episode listen: NASA cue was a complete miss (4s of an unrelated podcast intro); guest voice barely distinguishable but conceptually works; **OpenAI gpt-4o-mini-tts reads stilted** compared to ElevenLabs / Fish Audio used in other projects.
- **Re-prioritized.** Voice quality jumps the queue above cue work. Phase 1.5 still wins over Phase 2 for cues. "Fail closed to silence" promoted from option to rule.
- **Wired Fish Audio as a third TTS provider** (commit `59f522b`):
  - `tts_engines.py`: `synthesize_fish_audio()` mirroring the ElevenLabs path. POST `api.fish.audio/v1/tts`, Bearer auth, `model` selected via HTTP header (`s2-pro` default). Registered in `SUPPORTED_TTS_PROVIDERS`, dispatch added in `synthesize_tts()`.
  - `generate_podcast.py`: `fish_audio_*` DEFAULTS + INT/FLOAT key registration, `_fish_audio_voice_for_label()` helper, branches in `_legacy_tts_route_for_label` and `_tts_route_for_label`, sanitization in `_public_tts_route`.
  - `config.json`: voice IDs locked in with `_*_label` companion keys for human readability. **Both ElevenLabs and Fish Audio voice IDs are educated guesses — see Watch out for.**
  - `compare_tts.py`: new standalone driver, hardcoded 6-turn Cedar/Marin script (Voyager Golden Record), auto-loads `.env` (no `dotenv` dep), skips a provider cleanly if its key or voice IDs are missing.
- **Rendered the three comparison MP3s** (~45s each, all clean, ~4MB combined) and committed them so they travel with `git pull`:
  - `episodes/tts_comparison/openai.mp3` — OpenAI voices `marin` (Cedar) / `cedar` (Marin)
  - `episodes/tts_comparison/elevenlabs.mp3` — **Bella** (Cedar, female) / **Antoni** (Marin, male)
  - `episodes/tts_comparison/fish_audio.mp3` — **Sarah** (Cedar, female narrator) / **Ethan** (Marin, male educational)
- API keys (`ELEVENLABS_API_KEY`, `FISH_AUDIO_API_KEY`) added to desktop `.env` by the user.

## Next up
1. **LISTEN to all three MP3s back-to-back.** That verdict gates everything else. Decide: which provider becomes the new default? Or do we pair providers per host (e.g. ElevenLabs Cedar + Fish Audio Marin)? Are the picked voices keepers or swap candidates?
2. **Swap voice IDs if needed.** Fish Audio voice library is at fish.audio/voice-library/ (filter by `narration` tag). ElevenLabs library has hundreds of premade voices. Driver supports per-run env overrides (`CEDAR_ELEVENLABS_VOICE`, `MARIN_ELEVENLABS_VOICE`, `CEDAR_FISH_VOICE`, `MARIN_FISH_VOICE`) for fast iteration without editing config.
3. **Lock the winner into `config.json`** (`tts_provider` + voice IDs), regenerate a small real episode to confirm the pipeline still works end-to-end with the new provider, ship it.
4. **Then return to cue work.** Same queue as before but with sharper rules:
   - **(cheap, do regardless)** Silent dropped-cue warning + manifest note (e.g. `commons_morse_code` vanishing because Wikimedia backend isn't built).
   - **(cheap, do regardless)** NASA fallback fail-closed to silence — never grab semantically-unrelated audio.
   - **Phase 1.5**: LLM timestamp picker + smarter source selection.
   - Turn-enumeration consolidation (step zero) still pending.

## Watch out for
- **Voice IDs are guesses, not user-verified.** Picked by searching ElevenLabs default library + querying Fish Audio's `/model` endpoint filtered to `narration`-tagged top scorers. The names match the Cedar/Marin personas on paper but he hasn't confirmed by ear. Fully expect at least one swap.
- **OpenAI render uses voices literally named "marin" and "cedar"** — those are OpenAI's gpt-4o-mini-tts voice names, predating the show. The OpenAI track should sound identical to the BBQ episode. Not a bug; expect it.
- **Apples-to-oranges gender split.** ElevenLabs + Fish Audio renders use female Cedar / male Marin (max distinguishability). OpenAI render uses the existing same-genderish neutral pair. If he wants like-for-like, the driver makes swapping trivial.
- **API keys live in desktop `.env` only.** If picking up on the laptop, `ELEVENLABS_API_KEY` and `FISH_AUDIO_API_KEY` need to be added to that machine's `.env` before `compare_tts.py` will produce anything on those two providers. The driver skips with a clear message if a key is missing.
- **Test MP3s are committed.** `episodes/tts_comparison/{openai,elevenlabs,fish_audio}.mp3` are in git (so they travel cross-machine). If voices change, regenerate and the diff will show. Per-turn intermediates under `_work/` are gitignored.
- **Standing carryovers (unchanged):** work-dir cleanup re-enable 2026-06-06; Telegram token rotation (not urgent, git clean); cosmetic mangled commit msg on `2baddfc`; clips stay OFF / cues are the focus (decision holds).
