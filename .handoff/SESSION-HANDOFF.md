# Session hand-off — 2026-05-30 (machine: desktop / CRANE-DESK)

## STATE (read this first)
- Branch: `main`, working tree clean, synced with `origin/main`. No unpushed commits, no stray worktrees.
- This session **shipped a real test episode** to exercise the Phase 1 (NASA) sonic-footnote cues, on a richer topic than planned: a **deep dive with a forced guest** on the history of barbecue competitions.
- Episode is **LIVE** on the public feed: *"The Sauce That Won a Competition"* (7:02). Committed + pushed (`d52f6f6`), verified serving via GitHub Pages.
- **The whole point was to LISTEN and decide cue direction — that listen has NOT happened yet.** The user is listening on his phone. His verdict on the cue + guest is the gating input for what's next (Phase 1.5 vs Phase 2). Everything below is structural read-off from the artifacts, not a substitute for his ears.

## Done this session
- **Picked up clean**, then chose to test with a new episode instead of "fm synthesis": `--type deep_dive --guest` on "the history of barbecue competitions".
- **Hit + fixed an auth failure (root cause partially open).** First run died at the research step with `401 invalid x-api-key` — the run's process environment carried an *invalid* `ANTHROPIC_API_KEY` value (likely harness-injected; not fully root-caused). Fixed by adding a fresh valid key to `.env` (gitignored), which takes precedence; validated with a 1-token call and re-ran clean. **Correction: the Windows User-scope key is NOT revoked** — later tested in isolation and it authenticates fine. OpenAI key was fine too.
- **Generated the episode** (exit 0): 1179 words, Cedar 13 / Marin 13 / guest 8 turns. Forced guest booked **Dr. Evelyn Cross — "Black Pitmaster Historian"** (voice *nova*), entering on the racial-erasure beats. Guest path works on paper.
- **Published it** the way the pipeline normally does (direct to `main` — GitHub Pages serves the feed/MP3s from main): staged mp3 + feed.xml + `.chapters.json` + `.companion.json` + `host_memory.json`, committed, pushed, confirmed HTTP 200 + feed item live.

## Cue test — the actual finding (awaiting his ears to confirm)
- Planner proposed **2 cues; only 1 was inserted.** The 2nd (`commons_morse_code`) needs the **Wikimedia backend = Phase 2, which isn't built**, so it **dropped silently — no warning, no error.** Real gap.
- The one cue that landed (`nasa_apollo_countdown`) used a **fallback query ('Apollo 11')** and actually grabbed 4s of an unrelated **NASA podcast episode** (`Ep393_Crew-11`), not a countdown. Placed **"after turn 0"** (before the hosts finish the opening image). This is the "cues feel random" signal — strong structural argument for **Phase 1.5**.

## Next up
1. **USER LISTENS, then decides direction.** Cue feels random/wrong → build **Phase 1.5 (LLM cue-moment + smarter source selection)**. Cue placement feels fine → **Phase 2 (Wikimedia backend)**. Also judge: does *nova* read distinct from Cedar/Marin, and do the guest's entrances/exits land?
2. **Fix: silent cue drop.** Cues planned against unbuilt backends must **log a warning** (and surface in the manifest), not vanish. Cheap, do regardless.
3. **Fix: NASA fallback grabs unrelated audio.** `nasa_apollo_countdown` resolving to a random NASA podcast clip is a real quality bug — the fixed-offset + keyword-fallback path produces "wrong N seconds." This overlaps heavily with the Phase 1.5 motivation.
4. **Turn-enumeration consolidation (step zero, still pending).** `_enumerate_turns` vs `_parse_dialogue_turns` can disagree; fix before more placement work.

## Watch out for
- **Two distinct, valid Anthropic keys on CRANE-DESK (both work).** `.env` (gitignored) holds the key this project uses; the Windows **User-scope** `ANTHROPIC_API_KEY` is a *different but also valid* key — verified by direct auth test 2026-05-30 (NOT revoked; the earlier in-session assumption was wrong). This project has **no `.env` auto-load** (no `load_dotenv`), so the User-scope key is likely what authenticates the Telegram bot / other projects when `.env` isn't sourced. **Decision (user, 2026-05-30): leave it in place** — don't delete without checking what depends on it.
- **This was a TEST episode but it's now PUBLIC.** It used `--guest` (forced) and shipped to the live feed. If you don't want a barbecue episode in the public feed long-term, remove the `<item>` from `feed.xml` + delete the MP3 and re-push. Left as-is for now so he can listen on his phone.
- `host_memory.json` was committed this session (pipeline normally leaves it uncommitted). Minor deviation; keeps the tree clean and the show-memory in sync, but watch for JSON merge conflicts if the laptop also updates it.
- Standing carryovers (unchanged): work-dir cleanup re-enable 2026-06-06; Telegram token rotation (not urgent, git clean); cosmetic mangled commit msg on `2baddfc`; clips stay OFF / cues are the focus (decision from last session holds).
