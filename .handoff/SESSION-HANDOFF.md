# Session hand-off — 2026-06-20 (machine: laptop)

## STATE (read this first)
- Branch: `main`, clean and **pushed** (synced — desktop can pull immediately).
- This was a **diagnosis + editorial session**, not a build session. The big outcome: we figured out *why* episodes feel like an unfollowable mishmash (user's wife stopped listening to the Vienna ep). Full writeup committed at `.handoff/EDITORIAL-DIAGNOSIS-vienna.md` — **read that next**, it's the payload.
- One small feature also shipped: episodes now save a durable `.script.txt` next to the audio (survives work-dir cleanup, syncs across machines) so future scripts can be reviewed without re-transcribing.
- Two `audio-scope-*` dirs remain untracked **on purpose** — never commit them.

## Done this session
- **Editorial diagnosis of the Vienna episode** (`.handoff/EDITORIAL-DIAGNOSIS-vienna.md`). Root cause in one line: *scripts are a director's-commentary track for a documentary that was never made* — they argue ABOUT Vienna's history without ever telling it. Names dropped not rendered; "not X, that's Y" is the script's whole epistemics (punchline, no setup); tonal whiplash (Holocaust → coffee aphorism). The guest was the *best* part (only continuous content) → reopens the earlier "guests rare" plan.
- **Durable script sidecar** (`generate_podcast.py`, `_write_companion_artifacts`): writes `<audio>.script.txt` and publishes it with the other sidecars. Compiles clean.
- **`scripts/transcribe_episode.py`** — standalone faster-whisper transcriber to recover scripts of already-published episodes. Used it to recover the Vienna transcript (also committed).
- Persisted bot-run state (digest ledger + host memory).
- Memory written: `editorial_root_cause` (+ MEMORY.md index line).

## Next up
1. **🔴 C0 — structural prompt fix** (NEXT-STEPS.md, Phase C). Highest leverage. Pull the research + dialogue system prompts out of `generate_podcast.py`, read what's driving banter-about-facts, then add (a) an outline/beat-sheet step and (b) the constraint *establish before you adjudicate; one concrete scene per segment; define every name you invoke.* **Start this on a FRESH session** — it's prompt surgery and this session is loaded.
2. Only AFTER #1: reopen "guests rare" (the real fix is hosts carrying narrative, not fewer guests).
3. Only AFTER #1: extend `anti_slop.py` for the "not X, that's Y" antithesis family.
4. Carried from 2026-06-17 (still open, lower priority now): listen to the Vienna B1–B4 render; ear-check render to re-enable sonic footnotes (PENDING-DECISIONS #1); decide how to wire the anti-slop linter (PENDING-DECISIONS #2).

## Watch out for
- **Don't start by editing the guest planner or the anti-slop linter** — that's polishing a mishmash. The structure fix (C0) comes first and makes the rest cleanup.
- The `.script.txt` sidecar is **published/committed**, i.e. publicly reachable (just a transcript of already-public audio). User hasn't objected, but if he wants scripts local-only, pull `script_path` out of the returned list in `_write_companion_artifacts` and out of the publish set.
- The "every-N-episodes review trigger" the user asked about earlier was **not built** — we pivoted to the diagnosis. Pick it up if wanted, but C0 matters more.
- Whisper loop artifacts in the Vienna transcript (04:03, 10:02, 01:42) are TTS-transcription junk, not the real audio — ignore when reading.
- **`config.json` overrides DEFAULTS** — if an audio/footnote knob "isn't taking," check `config.json` first.
- **Two audio-scope dirs are untracked on purpose** — never commit them.
- Standing TODO (unchanged): rotate the leaked `@AsynchronousPodBot` Telegram token via BotFather `/revoke` when next at the home machine; git history verified clean.
