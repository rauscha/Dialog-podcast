# Deep Review — *Asynchronous*
**Date:** 2026-05-30
**Branch:** `main` (HEAD `0070797`)
**Reviewer:** Claude Code, fanning out seven read-only subagents across security, efficiency, UX, visual/art, delight, effectiveness, bugs, then synthesizing.

---

## The north star (as recorded)

Distilled from `README.md` and `CLAUDE.md`:

> A **personal curiosity-radio generator**. Send a topic via Telegram → Cedar and Marin turn that stray question into a **source-grounded two-host episode** with research, dialogue, fact-checking, two-voice TTS, optional generated music, and RSS publishing. **Local-first**: the bot runs on the home tower (RTX 4080), receives the topic from the phone, and launches the pipeline without exposing an inbound port.

Guiding principle: **local-first, single-user, source-grounded, sleek.** Cloud where it preserves quality (research, fact-check); local everywhere else.

Every finding in the *Effectiveness* dimension is judged against this. If you ever feel like a recommendation in this report drifts from that north star, push back.

---

## 1 · Executive summary

**The honest verdict:** the system is *working*. In the ten days from 2026-05-19 to 2026-05-29 it produced and shipped eleven complete episodes with zero failures in the work-dir trail — research brief, beat sheet, character-consistent script, fact-check, TTS, mastered audio, RSS item, GitHub push, all of it. The OPUS review from May 11 flagged a handful of real bugs (CDATA injection, missing subprocess timeouts, the Opus-everywhere cost bomb); most of those have been quietly absorbed. The codebase has *matured*.

Where it falls short is not on the rails it laid down for itself — it's on the **promises that exist as scaffolding but aren't yet wired to the speaker**.

The five things that matter most:

1. **[P0 — CRITICAL] Verify the Telegram bot token didn't actually escape into git history.** Your own memory note (2026-05-07) says it did, pending revocation. The security agent searched and saw only *references* to the env-var name — not a confirmed leaked value — but this needs a 60-second `git log --all -S` against the actual token format before you go to sleep. If a token did escape, even years ago, GitHub indexes are scraped continuously and revocation via BotFather is the only fix. (See §2 item A.)
2. **[P0 — CRITICAL] The companion website fails its own designer.** The "active chapter" state changes by color alone (amber → coral, [index.html:408](index.html#L408)). You are color blind. By your own standard this is a hard accessibility fail — and it's a five-minute CSS fix. Painfully ironic, easy to retire. (§2 item B.)
3. **[P1 — IMPORTANT] Sonic footnotes are the project's single most original idea, sitting on a shelf.** The pipeline devotes a full LLM pass to deciding whether an episode needs one, builds a beautifully license-aware plan, writes it to the manifest — *and then nothing downstream consumes it*. The audio assembler never inserts a single cue. This was the same finding from two completely independent subagents (Effectiveness and Delight). Either **ship it** (a clip-mixer-style resolver-and-splicer pass, maybe a week) or **kill it** (delete the planning pass and the README promise). The current state — promised, planned, never delivered — is the worst of both. (§2 item C.)
4. **[P1 — IMPORTANT] Cedar and Marin are written but not yet *alive*.** Their character bible in `host_memory.json` is genuinely architected — specific blind spots, speech habits, a working disagreement dynamic. But the rendered scripts read as competent NPR alternation: Cedar opens, Marin grounds, Cedar reacts, Marin caveats. They almost never interrupt, correct, or playfully contradict mid-thought. The architecture is there; one more script pass that explicitly *breaks turn symmetry* would unlock the soul this show is supposed to have. (§2 item D.)
5. **[P1 — IMPORTANT] LLM cost is fine; LLM *latency* is the real friction.** Your per-episode bill is roughly **$0.70–$1.20** — already a win since the Opus-everywhere days. But ~60–100 OpenAI TTS calls run in serial (~2 sec each) and yt-dlp clip downloads run in serial. Parallelizing both is the single biggest UX upgrade in this codebase: a 12-minute generation becomes a 6-minute one, which changes what it feels like to send a topic from a walk. (§2 item E.)

A sixth thing that didn't make the top five but deserves naming: the **OPUS review has aged well**. Most of its blocking items are fixed — CDATA escaping landed, subprocess timeouts landed, voice IDs were verified valid. This was a real maturation in two and a half weeks. The remaining items are real but second-order. You should feel good about that.

---

## 2 · Action plan — the P0 and P1 list, in order

This is the "what do I do Monday morning" section. Each item: the problem, why it matters, the fix, and effort (S = under an hour, M = an afternoon, L = a day-plus).

### A — [P0 — CRITICAL] Verify no real Telegram token is in git history. *(Effort: S)*

**Why this is first.** Anything that escapes to a public git repo is *forever* — GitHub mirrors are indexed by scrapers within minutes of a push. A leaked bot token lets anyone impersonate `@AsynchronousPodBot`: send `/generate` from outside your whitelist, exhaust your Anthropic + OpenAI quota in an afternoon, and read any topic any user (you) ever sent. The asyncio lock won't save you — the attacker is *being* the bot.

Your memory note dated 2026-05-07 already flags this as pending revocation. The security agent searched but couldn't confirm whether a real token value (not just `TELEGRAM_BOT_TOKEN` env-var references) is in history.

**The fix.** Two commands, in this order:

```powershell
# Telegram tokens are shaped: <digits 9-10>:<35-char base64ish>
git log --all -p | Select-String -Pattern '\d{9,10}:[A-Za-z0-9_-]{35}'
git log --all -p | Select-String -Pattern 'sk-[A-Za-z0-9_-]{20,}'   # Anthropic + OpenAI keys
```

If either matches, **revoke via BotFather (`/revoke`) immediately** and rotate the corresponding API keys via the Anthropic + OpenAI consoles. History rewriting (`git filter-repo`) is theatre after the fact — the token is already harvested; revocation is the only real fix.

If nothing matches, **add a pre-commit hook** that rejects those two patterns so a future paste from a debug session can't sneak through:

```powershell
# .git/hooks/pre-commit — keep it short
git diff --cached -U0 | Select-String -Pattern '\d{9,10}:[A-Za-z0-9_-]{35}|sk-[A-Za-z0-9_-]{20,}' -Quiet
if ($LASTEXITCODE -eq 0) { Write-Error "Possible secret in staged diff. Aborting commit."; exit 1 }
```

### B — [P0 — CRITICAL] Make the active-chapter indicator work for you. *(Effort: S)*

**Why this matters.** [index.html:408](index.html#L408) marks the currently-playing chapter by changing `.chapter-time`'s color from amber to coral. You are color blind. The interaction *exists* — the audio jumps when you click, the state updates internally — but the visual feedback is invisible to the only listener this site has. By the standard you've set for the rest of your tooling (the deep-review skill explicitly says "never color words, the reader is color blind"), this is a hard fail.

**The fix.** Add a non-color cue. The cleanest:

```css
.chapter.active .chapter-time {
  font-weight: 600;
  border-left: 2px solid var(--accent-amber);
  padding-left: 6px;
}
```

Audit `index.html` for any other state-by-color-only patterns while you're in there — the visual subagent saw nothing else egregious, but a one-pass grep for `color:` near `.active`, `.selected`, `:hover` is cheap insurance.

### C — [P1 — IMPORTANT] Sonic footnotes: ship them or kill them. *(Effort: M to ship, S to kill)*

**Why this matters.** Two independent subagents — *Effectiveness* and *Delight* — flagged exactly the same thing: the sonic-footnote system is the single most distinctive sound-design idea in the codebase, and it never reaches the audio. The pipeline runs a Claude pass that decides yes/no, plans the placement, writes `sonic_footnote_plan.json` to the work dir, records it in `episode_manifest.json` — and then the audio assembler ignores it. The chiptune episode planned two metronome cues; the final MP3 has zero insertions.

The metaphor that fits: it's a fully-instrumented MRI sequence that produces a beautifully formatted DICOM header and then never fires the gradient coils. The patient leaves with a report and no image.

This is also where the show could most cheaply earn its "Radiolab-adjacent, not Radiolab-fanfic" identity. A chiptune episode that includes a real NES APU tone is a different show than one that talks about NES APU tones.

**The fix — option 1 (ship it, ~1 week of evening work).** A `sonic_footnote_mixer.py` that mirrors `clip_mixer.py`'s structure: read the plan, resolve each cue to a verified file (Freesound API for CC0/CC-BY, NASA media catalog for public-domain space audio, Wikimedia Commons API for PD), download with rights metadata, splice with ffmpeg at the planned beat marker. The catalog already has the right shape — `requires_file_verification` is a placeholder that resolution would fill in. You already wrote half the system; the other half is the same shape as the clip mixer you've already debugged.

**The fix — option 2 (kill it, ~30 min).** Delete the planning pass from the script pipeline, drop the README section, leave the catalog file for a future revisit. This is the honest move if you're not going to finish it in the next sprint.

The current state — promised, planned, never delivered — is the worst of the three options. It costs LLM tokens every run and erodes trust in the README.

### D — [P1 — IMPORTANT] Break Cedar and Marin's turn symmetry. *(Effort: M)*

**Why this matters.** Open `host_memory.json` and you'll find a *real* character bible: Cedar's metaphor-first tendency and her habit of trailing off when an idea catches her; Marin's data-and-citation habit and his soft contempt for sloppy framing; an explicit anti-cliché phrase blacklist; tracked callbacks across episodes. This is genuinely careful work. Now open `episodes/.../script.txt` from any recent run. The dialogue alternates clean Q-A-Q-A turns with thesis-evidence-thesis-evidence rhythm. The architecture for character is doing nothing the readout can hear.

The diagnosis: the anti-cliche rewrite pass strips specific words, but no pass strips *structural* turn-taking. So you get clean prose dialogue that sounds like the New York Times's "Hard Fork" — competent, friendly, and forgettable.

**The fix.** Add (or modify the anti-cliché pass to include) an explicit *interruption pass*. Its instructions are roughly:

> Re-read the script. For roughly 10–15% of turn transitions, break the symmetry: have one host interrupt the other mid-sentence with "Wait —", "No, that's —", "Actually you're —", then the original speaker finishes or recovers. Have one host get a fact slightly wrong and the other gently correct it. Have at least one moment where Cedar trails off because an idea caught her. Have at least one moment where Marin softens — admits he's reaching, or that Cedar's metaphor was better. Do not add new content; only restructure the turn boundaries and add the small recoveries.

This is one Sonnet call after the dialogue-draft pass and before fact-check. Token cost is negligible. Wins or loses on whether the prompt is specific enough.

### E — [P1 — IMPORTANT] Parallelize TTS and clip downloads. *(Effort: M each)*

**Why this matters.** Your per-episode wall-clock breaks down roughly:
- Research + script + fact-check: ~2 min (already cloud-parallel)
- **TTS (60–100 calls × ~2 sec serial): ~2–4 min ← bottleneck**
- **YouTube clips (3–4 × ~15 sec serial): ~1 min ← bottleneck if `USE_CLIPS=true`**
- MusicGen on the 4080: ~30–60 sec
- ffmpeg mastering: ~30 sec
- Git push: ~5 sec

The two highlighted lines are pure I/O-bound serial calls with no shared state. A thread pool of 4–8 workers cuts each to roughly a fifth of its current wall-clock. The math: a 12-minute generation becomes a 6–7 minute generation, which is the difference between "send from a walk and check later" and "send from a walk and have it before you're home." That changes the *feel* of the product more than any single visual change you could make.

The reason TTS is the priority of the two: it always runs (clips are opt-in). The implementation risk is low — `synthesize_tts` has no state mutations between calls; the only care needed is output-path naming, which is already per-turn-indexed.

**The fix.** In the per-turn TTS loop in `generate_podcast.py`, wrap the calls in a `concurrent.futures.ThreadPoolExecutor(max_workers=6)` (start conservative; OpenAI's TTS quota is per-key, not per-connection). Same shape for `clip_mixer.process_clips`.

### F — [P1 — IMPORTANT] Cache the long static system prompts with Anthropic prompt caching. *(Effort: S)*

**Why this matters.** Several large blocks of text are reused verbatim across passes within a single episode: the research system prompt, the dialogue-draft system prompt, the anti-cliché system prompt, the performance system prompt, and most importantly the **research brief itself** — which is fed back into thesis, beat-sheet, dialogue-draft, anti-cliché, and fact-check passes. Combined ~8-10KB of static text shoveled through Claude five times per episode. Anthropic's `cache_control: ephemeral` reads cached input at ~10% of normal cost. At Sonnet pricing the dollar savings are modest (~$0.01/ep), but **latency improvement is real and compounding** — the second pass through a cached block is noticeably faster on the wire.

**The fix.** Wrap your `_anthropic_text()` (or wherever the message construction happens) so that any system prompt or research-brief block can be tagged:

```python
{"type": "text", "text": research_brief, "cache_control": {"type": "ephemeral"}}
```

Apply it to: each of the four named system prompts, the research-brief block in every downstream pass, and the host-memory bible block.

### G — [P1 — IMPORTANT] Add a proactive Telegram notification when generation finishes. *(Effort: M)*

**Why this matters.** The lived experience today: you send `/generate`, walk away, and have to remember to `/status` or refresh the website. The UX agent's strongest observation was that the bot is *reactive* — it answers when asked but doesn't speak first. A single outbound message on completion (success or failure, with the website link and elapsed time) closes the loop. This is one async call at the end of the pipeline and a friendlier UX than anything else on this list.

### H — [P1 — IMPORTANT] Pin dependencies and run pip-audit once. *(Effort: M)*

**Why this matters.** `requirements.txt` uses floating lower bounds (`anthropic>=0.40.0`, `openai>=1.30.0`, `torch>=2.1.0`). On a fresh pip install — say, after rebuilding the tower, or syncing the project to a laptop — pip can resolve to a newer version with a regression or, worse, to a *very old* cached version with a known issue. Pin everything to an exact version that's known-good for you today, run `pip-audit --desc` once, write down the date and the result, and treat that as your baseline. Re-run quarterly.

### I — [P1 — IMPORTANT] Stop leaking partial ElevenLabs voice IDs into the public companion JSON. *(Effort: S)*

**Why this matters.** `_public_tts_route()` in `generate_podcast.py` masks ElevenLabs voice IDs to `first_4...last_4` form and writes them to companion JSON, which is *served from the public GitHub Pages site*. A partial voice ID is not a credential per se, but it narrows the brute-force search space against the ElevenLabs API if anyone ever decided to. There's no reason the front-end player needs the voice ID at all — it can read a human label ("Cedar — warm alto") instead.

### J — [P1 — IMPORTANT] Set hard spend limits on Anthropic and OpenAI. *(Effort: S)*

**Why this matters.** Both consoles let you set per-day hard caps. Set them. Suggested floor: **$10/day** for each. A whitelisted user who got pwned, a runaway loop in a new script pass, or a future you who accidentally schedules a `/loop` task that fires every minute — any of those drains a credit card if no cap is in place. The cap is the bulkhead in a ship's hull: most days it does nothing; the one day it does something, it's the whole game.

---

## 3 · Vision & originality — what's genuinely yours, what's tired

This is the consolidated read across all seven dimensions.

**What's genuinely visionary or rare in this project:**

- **The conception itself.** "Local-first, single-listener, Telegram-triggered curiosity radio that runs on a gaming GPU at home" is a real niche. Most AI-podcast tools (Wondercraft, Podcast Factory, etc.) optimize for *publishers* — multiple listeners, a brand, ad slots. You optimized for **one listener whose curiosity is the product**. That framing isn't crowded.
- **Source-grounding-first, aesthetic-second.** Most AI-audio products lead with voice quality; you lead with "we have real claims and we tracked them." The companion JSON architecture — chapters, sources with `why_it_matters` rationales, follow-up links — is genuinely well-thought and serves the framing.
- **The character architecture.** The `host_memory.json` with specific blind spots, anti-cliché blacklist, and tracked callbacks across episodes is the kind of design choice you'd expect from someone running an actual writers' room, not from a hobby project.
- **The sonic-footnotes idea.** Whether or not it ships, the *concept* — license-aware, taste-curated micro-cues from public-domain catalogs — is a more interesting use of generative audio than "have an LLM write a script and a TTS read it."
- **The cover art and visual identity.** Concentric rings + italic serif wordmark on a warm earth palette — the visual subagent called this distinctive and not template. It does look like a real publication.
- **The professional discipline in the codebase**: atomic JSON writes via `Path.replace()`, subprocess timeouts everywhere, specific exception types in catch blocks, graceful audiocraft → numpy fallback. This is the work of someone who has been burned by half-finished tools and decided to do it properly.

**What's competent-but-derivative:**

- **The Telegram bot command surface.** The vocabulary (`/generate`, `/status`, `/queue`, `/cancel`) is standard bot UX; the *composition* is thoughtful but the bones are conventional.
- **The website layout.** Sticky player + tabbed archive is familiar. Good execution, but the form is borrowed.
- **The dialogue-as-rendered.** Despite the character architecture, what comes out today reads like good public-radio talk — Hard Fork, Search Engine, Reply All in their last seasons. It's not yet *Asynchronous-shaped*. (This is item D in the action plan.)
- **The error-handling pattern.** Pragmatic and Pythonic, not novel. Fine.

**The single most original idea, still mostly potential:** Cedar and Marin as a *persistent* two-host relationship — not just characters but a *partnership that evolves across episodes*, with callbacks, callbacks-to-callbacks, in-jokes, and the kind of texture that only emerges from continuity. The `host_memory.json` is the engine. Today the engine is mostly idling. The action-plan items C and D are how you put it in gear.

---

## 4 · Additional findings — P2 and P3 items

These are the things that won't bite this week but are worth queueing.

**Security:**
- [P2] Telegram bot has no per-user rate limit or cooldown. A whitelisted user can queue 10 expensive generations in a minute. Pair this with item J (spend caps) and add a per-user `/quota` view.
- [P2] Work directories (research brief, draft scripts, personal-context snapshot) sit on disk indefinitely. They're git-ignored, so they don't leak via GitHub; the risk is a stolen tower. The `2026-06-06` cleanup deadline (now seven days away) is the natural trigger to either re-enable `shutil.rmtree` or move work dirs to `$TEMP`.
- [P2] Topic sanitization for git commit messages is mostly defensive but could be tighter — restrict to alphanumerics/dashes via a static template rather than f-string interpolation.
- [P2] Archived email-webhook code is still in the tree. Either delete it or guard it with a `raise RuntimeError("archived")` so a future you can't accidentally `python email_trigger.py` and bring it up.
- [P3] yt-dlp search query is LLM-derived and passed via subprocess list args (so not command-injectable), but adding a regex sanity check on the query is cheap insurance.

**Efficiency:**
- [P2] Verify MusicGen model is cached between intro and outro generation. If audiocraft re-loads the 2 GB model, batch the two prompts into a single `.generate([intro, outro])` call — roughly halves GPU time.
- [P2] `loudnorm` is single-pass. Fine for podcast loudness targets; revisit only if you add dynamic-range compression.
- [P3] `_ffmpeg_concat` always full-re-encodes at 192 kbps. If all input segments are already the same codec/bitrate (which they are inside a single voice), use `-c copy` with the concat protocol — bit-identical output in roughly 1/20 the time. Two concats per episode → ~20 sec saved.
- [P3] `personal_context.find_related_topics` is O(N) over the topic history. At N≈24 this is microseconds; only matters if you ever raise `max_topics` above ~200.

**UX:**
- [P2] `/queue` doesn't tell you the estimated wait when adding. "Position 2, ahead is estimated 12–18 min."
- [P2] Website player has no loading state during the initial `fetch(feedUrl)` — on a slow LTE connection it briefly looks broken.
- [P3] Long episode titles wrap with `overflow-wrap: anywhere`, which breaks mid-word on mobile. Use word-wrap with a 2-line + ellipsis truncation instead.
- [P3] Selecting a chapter via the player doesn't scroll the chapter list to keep the active item in view.
- [P3] `/latest` and `/status` could include a deep link to the episode on the website.

**Visual:**
- [P2] Spacing scale is almost-but-not-quite a 4 px grid (`13/14/18` deviations). Snap everything to `4/8/12/16/24/32/48`.
- [P2] Microcopy capitalization is inconsistent ("Now Playing" vs "Follow-Up" vs "Chapters" vs "Copy RSS"). Pick one rule: ALL-CAPS for section headers, Title Case for action buttons.
- [P3] Type scale (`clamp(1.5rem, 3vw, 2.1rem)` for H1) is modest at desktop. Push to ~2.4–2.8 rem so "Asynchronous" actually dominates as a wordmark.
- [P3] Border-radius is 8 px everywhere — neither crisp (4 px) nor distinctly rounded (12 px). Pick a side.
- [P3] Episode duration in the meta line isn't `font-variant-numeric: tabular-nums`; chapter times are. Trivially inconsistent.

**Delight:**
- [P2] The Telegram bot's voice is purely transactional. One warm line per message ("Done. They got into it.") is ten lines of code.
- [P2] MusicGen prompt is generic per episode. Thread the episode thesis or beat-sheet mood into the prompt — chiptune ep gets a retro/8-bit prompt, fetoscopy ep gets something contemplative.
- [P3] Website microcopy is template-grade. One personality line on the front page ("Two synthetic hosts. Real disagreement. Source-grounded but emotionally alive.") proves someone is home.

**Effectiveness:**
- [P2] **Learning-path mode is built but not wired.** `plan_learning_path.py` is callable; `/series` is documented in the README; no `learning_paths/` directory has ever been created and no episode evidence exists of an end-to-end series run. Ship it or de-advertise.
- [P2] Spoken source attribution is thin. The metadata is rich (companion JSON has dates, authors, why-it-matters); the dialogue says "the 2A03" not "the NES APU as documented by NESdev." A short "source-weaving" rewrite pass that nudges named citations into dialogue would strengthen the in-audio claim-to-evidence chain without cluttering the script.
- [P3] Personal context exists but you haven't seeded it. The infrastructure is ready; the listener profile is empty. Five `/remember` commands (background, domain, depth, goal, style) unlock the deduplication and depth-tuning that the system promises.

**Bugs:**
- [P2] One ffprobe call in `clip_mixer.py:273` (`_get_audio_duration`) is missing `timeout=`. All others have it. One-line fix.
- [P2] CLI entrypoint to `generate_podcast.py` has no topic-length cap, though the Telegram bot does (`MAX_TOPIC_LEN=500`). Match it.
- [P3] The 2026-06-06 cleanup TODO is genuinely seven days away. Decide now whether you re-enable `shutil.rmtree(work_dir)` on that date or migrate work dirs to `$TEMP` so they auto-clean on reboot.

---

## 5 · Flourishes — three level-up ideas

These are the imaginative bets, not the bug fixes. Each one is here because it punches above its effort and fits *this* project (not "any podcast tool").

### Flourish 1 — *The closing callback.* (Effort: M, Impact: high)

The end of every episode currently just stops. Add a final pass that reads the new `host_memory.json` and chooses one *prior* episode's idea to call back to in the last 60 seconds — "remember when we said constraint breeds creativity, in the chiptune episode? This is that, but for clinical reasoning." This requires almost no new code: you already track callbacks; you just don't *use* the system to enforce one per closer. The effect over time is enormous — episodes start to feel like chapters in a single ongoing show rather than discrete uploads. It is also the cheapest way to start making your back catalog feel listenable as a body of work, not a feed.

### Flourish 2 — *The reading-room companion.* (Effort: M, Impact: medium-high, fit: very high)

You're a professor; your listeners (well, listener) think in terms of *what should I read next*. On the website, render a per-episode **annotated reading list** — not just the URLs that the source-cards JSON already has, but a one-sentence "if you only read one of these, read this one" pulled from a tiny Haiku pass. Each card: title, link, one-sentence why. Place it under the chapters tab as a third tab labeled "Going Deeper." It costs ~$0.001 per episode in Haiku calls, no new infrastructure, and it turns the website from "podcast archive" into "a syllabus the show happens to come with." That framing is what differentiates *Asynchronous* from every other AI-podcast project on GitHub.

### Flourish 3 — *Generative chapter art.* (Effort: M, Impact: medium, fit: experimental)

Each episode already produces ~5–8 chapters with titles. A single batched call to a small image model (Replicate-hosted FLUX-schnell, or a local Stable Diffusion if you want to keep it local-first) could generate one small abstract illustration per chapter — same warm-earth palette as the cover art, same concentric-circle motif evolved per chapter theme. Render them inline in the chapter list. The cost is ~$0.02/episode at most; the *feel* is that of a New York Review of Books essay, where each section has its own engraving. This is the kind of detail that announces "someone lives here." It's also pleasingly recursive: a generative podcast with generative art.

---

## 6 · Concrete next steps — sequenced

The Monday-morning checklist, in order. The first three are 30 minutes total.

1. **Today, before anything else.** Run the two `git log --all -S` searches in item A. If either hits, revoke via BotFather (`/revoke`) and rotate the matching API key in the Anthropic and OpenAI consoles.
2. **Today.** Open the Anthropic and OpenAI consoles, set $10/day hard caps (item J).
3. **Today (5 min).** Patch [index.html:408](index.html#L408) per item B — add `font-weight: 600` and a 2 px left border on `.chapter.active .chapter-time`.
4. **This week.** Decide on sonic footnotes: ship or kill (item C). The decision matters more than the answer; the current limbo is the worst state.
5. **This week.** Add the interruption pass to break Cedar/Marin's turn symmetry (item D). One Sonnet call, prompt-only change, immediate audible payoff.
6. **This week.** Pin `requirements.txt`, run `pip-audit --desc`, write the date and the result down (item H).
7. **Next week.** Parallelize TTS (item E, TTS half). Measure wall-clock before and after — should be the single most visible speedup in the codebase.
8. **Next week.** Add `cache_control: ephemeral` to the four named system prompts and the research-brief block (item F). Trivial diff, measurable wire-latency win.
9. **Next week.** Add the on-completion Telegram notification (item G).
10. **Before 2026-06-06.** Decide on the work-dir cleanup: re-enable `shutil.rmtree`, migrate to `$TEMP`, or write a maintenance script that prunes anything older than 7 days. Don't let the date pass with the decision still pending.
11. **Whenever you have an evening to spare.** Pick one of the three flourishes. The *closing callback* (Flourish 1) is the highest-leverage one for the smallest effort.

---

## 7 · Appendix — full per-dimension summaries

The seven subagent reports, lightly tidied for legibility but otherwise unchanged.

### A · Security

**Overall health:** Generally sound for a single-user local tool. Several real findings around credential handling, dependency management, and git history.

**Findings:**

- **[P0 — CRITICAL] Possible Telegram bot token in git history.** Memory note (2026-05-07) flags a leak; `TELEGRAM_BOT_TOKEN` env-var name appears in commits `7f35113`, `0b4ecdd`, `ac7f0ba` but verifying whether a real token value escaped requires `git log --all -S` with the actual token shape. If anything escaped, revoke via BotFather. Add a pre-commit hook for `\d{9,10}:[A-Za-z0-9_-]{35}` and `sk-[A-Za-z0-9_-]{20,}`. **Effort: S.**
- **[P1 — IMPORTANT] API keys are inherited by every subprocess.** `os.environ` copy is passed to yt-dlp, ffmpeg, custom TTS command. Means a malicious TTS command (the `command` provider) could log the environment. Use distinct lower-privilege keys for the pipeline; set spend caps. **Effort: M.**
- **[P1 — IMPORTANT] Floating dependency versions, no audit baseline.** `anthropic>=0.40.0`, `openai>=1.30.0`, `torch>=2.1.0`. Pin all exact; run `pip-audit --desc` once. **Effort: M.**
- **[P1 — IMPORTANT] Partial ElevenLabs voice IDs in public companion JSON.** `_public_tts_route()` masks but still leaks `first_4...last_4`. Drop entirely or replace with a human label. **Effort: S.**
- **[P2 — WORTH DOING] No rate limiting in the Telegram bot.** Whitelisted user can queue infinite expensive generations. Add per-user cooldown + audit log + `/quota`. **Effort: M.**
- **[P2 — WORTH DOING] Topic sanitization for git commit messages.** XML-escaping in RSS is correct; commit messages still use f-string interpolation. Use a static template restricted to alphanumerics + dashes. **Effort: M.**
- **[P2 — WORTH DOING] Work directories retained indefinitely.** Personal-context snapshots, draft scripts, source quotes sit on disk forever (cleanup deferred to 2026-06-06). Re-enable cleanup or migrate to `$TEMP`. **Effort: S–M.**
- **[P2 — WORTH DOING] Archived email-webhook still in tree.** Delete or guard with a runtime block. **Effort: S.**
- **[P3 — OPTIONAL] yt-dlp search query has no input validation.** Subprocess list args make it non-injectable; adding a regex check is cheap insurance. **Effort: S.**

**Standout strengths:** CDATA defense (`_defuse_cdata_end`), all subprocess calls use list args (no `shell=True`), `_public_tts_route()` shows clear intent to separate private/public metadata, topic length cap (`MAX_TOPIC_LEN=500`) in the Telegram surface.

**Originality read:** Competent but conventional. Standard defenses applied. The CDATA defense is the one place the security thinking is more specific than textbook.

### B · Efficiency

**Overall health:** Competent but not optimized. ~$0.70–$1.20/episode today (already a big improvement on the $2.20/ep Opus-everywhere days). Biggest wins remaining: parallelize serial TTS, cache static prompts.

**Findings:**

- **[P0 — CRITICAL] Serial TTS per-turn synthesis.** 60–100 OpenAI calls × ~2 sec = 120–200 wall-clock sec. Thread pool with `max_workers=4–8` → 20–40 sec. **Effort: M.**
- **[P1 — IMPORTANT] No prompt caching on stable blocks.** ~8–10 KB of system prompt + research brief reused across 5+ passes per episode. Tag with `cache_control: ephemeral`. **Effort: S.**
- **[P1 — IMPORTANT] Double audio encoding in clips pipeline.** yt-dlp → MP3, then ffmpeg trim+fade → MP3 again. Trim before encode, or use `-c:a copy`. **Effort: M.**
- **[P1 — IMPORTANT] yt-dlp clip downloads are serial.** 3–4 independent downloads, ~60 sec total. Trivially parallelizable. **Effort: M.**
- **[P2 — WORTH DOING] MusicGen model possibly re-loaded between intro and outro.** Verify caching; if not cached, batch into one `.generate([intro, outro])` call. **Effort: S.**
- **[P2 — WORTH DOING] Single-pass `loudnorm`.** Fine for podcast; revisit only with dynamic-range compression.
- **[P2 — WORTH DOING] Personal-context topic similarity is O(N).** At N=24 it's microseconds; only an issue if `max_topics` grows >200.
- **[P2 — WORTH DOING] Work-dir cleanup deletes expensive caches on failure.** Rename to `work_${status}` and keep failed dirs for 7 days. **Effort: S.**
- **[P3 — OPTIONAL] `_ffmpeg_concat` full-re-encodes when `-c copy` would do.** ~20 sec/episode saved. **Effort: M.**
- **[P3 — OPTIONAL] Set `use_cleanup=true` after 2026-06-06.** **Effort: S.**

**Standout strengths:** Graceful audiocraft → numpy fallback; intro-ident caching (one-time per-show cost); routed TTS abstraction; thoughtful dialogue-turn parser.

**Originality read:** The multi-pass writers' room is genuinely thoughtful — most podcast generators skip 4–5 of those steps. Personal context + topic similarity is smart personalization that few single-user tools bother with. Sonic footnotes is creative-but-serial (and incomplete, see Effectiveness).

### C · User Interface & Experience

**Overall health:** Sleek and exceptionally well-thought-out. Bot, website, and end-to-end flows reflect genuine care for a non-developer user. Proactive feedback, transparent wait states, respect for the user's time.

**Findings:**

- **[P0 — CRITICAL — but I'd reframe as P1]** `/status` reply is technically verbose. A 15-min generation, the user checks progress, sees "Bot subprocess: running pid 12345" and lock data instead of "Still working on fetoscopy — elapsed 8m 42s, checking facts now." Lead with felt progress; keep PIDs below. **Effort: S.**
- **[P1 — IMPORTANT] Bot is reactive, not proactive.** No outbound message when generation completes. Add a single "Done!" notification with link + elapsed time. **Effort: M.**
- **[P2 — WORTH DOING] `/queue` doesn't show ETA.** Append "Episode ahead is estimated 12–18 min." **Effort: M.**
- **[P2 — WORTH DOING] Website fetch has no loading state.** Spinner/skeleton while `fetch(feedUrl)` is in flight. **Effort: M.**
- **[P3 — OPTIONAL] Long titles wrap badly on mobile.** `overflow-wrap: anywhere` breaks mid-word; use 2-line + ellipsis. **Effort: S.**
- **[P3 — OPTIONAL] Chapter list doesn't scroll active chapter into view on selection.** **Effort: S.**
- **[P3 — OPTIONAL] `/latest` and `/status` don't deep-link to the website episode.** **Effort: M.**

**Standout strengths:** Bot command surface is comprehensive without being overwhelming. Responsive sticky-player layout is pitch-perfect for phone-while-walking. Live chapter scrubbing is subtle but delightful. RSS feed is thorough and works correctly in Apple Podcasts / Overcast / Pocket Casts. Queue management is intuitive and collision-free.

**Originality read:** Command vocabulary is derivative; composition is original. The `/remember` semantic memory + `/doctor` empathy + `/types` discovery teach without demanding tutorial reading. The user is treated as a curious person with a busy schedule, not a technician.

### D · Visual & Art Design

**Overall health:** Genuinely stellar. A sleek, cohesive design that eschews template defaults in favor of thoughtful typographic and spatial hierarchy.

**Findings:**

- **[P0 — CRITICAL] Color-only chapter active state.** `.chapter.active .chapter-time` shifts amber → coral. User is color blind. Add `font-weight: 600` + 2 px left border. **Effort: S.**
- **[P1 — IMPORTANT] Border-radius is 8 px throughout — neither crisp (4 px) nor distinctly rounded (12–16 px).** Pick a side, apply everywhere. **Effort: S.**
- **[P1 — IMPORTANT] Type scale lacks a declared ratio.** Hierarchy reads functional, not designed. Adopt 1.2 or 1.25 scale; push H1 to 2.4–2.8 rem at desktop. **Effort: M.**
- **[P2 — WORTH DOING] Spacing is almost-but-not-quite a 4 px grid.** 13/14/18 deviations. Snap to 4/8/12/16/24/32/48. **Effort: M.**
- **[P2 — WORTH DOING] Microcopy capitalization inconsistent.** "Now Playing" vs "Follow-Up" vs "Chapters" vs "Copy RSS". Pick a rule. **Effort: S.**
- **[P2 — WORTH DOING] Episode duration not `tabular-nums`; chapter times are.** Trivially inconsistent. **Effort: S.**

**Standout strengths:** Cover art is distinctive — concentric rings + italic-serif wordmark on warm earth palette. Not stock-template. WCAG-AAA contrast on body text. Genuinely minimal responsive layout (no hamburger cruft). Inter typeface + sensible fallback chain. Letter-spacing on section headers adds formality without amateurism.

**Originality read:** Distinctive. Cover art is not the default Spotify/Apple aesthetic. Warm-brown + muted-teal sidesteps the typical podcast dark-mode blues. Grade: **B+ — nearly A; a few microcopy details and the type-scale work would elevate it further.**

### E · Delight

**Overall health:** Has bones, no meat. Clear character architecture; doesn't yet sing.

**Findings:**

- **[P1 — IMPORTANT] Cedar & Marin written but not alive.** Architecture in `host_memory.json` is genuinely careful; rendered scripts are competent Q-A symmetry. Need an interruption / structural-asymmetry pass that adds stumbles and small recoveries. **Effort: M.**
- **[P2 — WORTH DOING] Sonic footnotes catalogued but never used.** Beautiful curated catalog (NASA, Wikimedia, Freesound CC0); plan files written; audio never inserted. **Effort: S (force at least one per episode by editing the planner) or M (build the inserter — see Effectiveness §F).**
- **[P2 — WORTH DOING] Telegram bot voice is invisible.** Pure transactional copy. Add 2–3 personality response templates. **Effort: S.**
- **[P3 — OPTIONAL] Website microcopy is styled but template-grade.** One front-page personality line proves someone's home. **Effort: S.**
- **[P3 — OPTIONAL] MusicGen prompt is generic.** Thread episode mood/thesis into the prompt. **Effort: M.**

**Standout strengths:** `host_memory.json` is *architected*, not templated — real blind spots and relationship dynamics. `personal_context.json` tracks listener with taste. Sonic footnote catalog is *curatorial*, not "drop sound effects". Script quality pipeline is real (anti-cliché rewriter, performance editor).

**Originality read:** Radiolab-adjacent, not Radiolab fanfic. Cedar/Marin have specific enough blind spots that they could find angles a radio journalist would miss. But the *voice* — the audio personality — isn't there yet. Reads like good NPR, not like *Asynchronous.* Architecture for a soul; hasn't found its rhythm.

### F · Effectiveness

**Overall verdict:** **Mostly.** System reliably generates and publishes complete episodes; two promised features exist as scaffolding without delivery.

**North-star pillar scorecard:**

| Pillar | Status |
|---|---|
| Local-first | Delivered |
| Single-user (Telegram, RTX 4080) | Delivered |
| Source-grounded | Partial (metadata yes; in-audio thin) |
| Two-host Cedar/Marin character | Delivered (architecture); partial (voice — see Delight) |
| Sleek topic → earbuds | Delivered |
| Optional music / clips / sonic flourishes | Music yes, clips yes, **sonic footnotes code-but-not-wired** |
| RSS publishing | Delivered |

**Findings:**

- **[P1 — CRITICAL within Effectiveness] Sonic footnotes are half-built.** Planning pass runs, plan file written to manifest, no downstream consumer. Two metronome cues planned in a recent ep; zero audio insertions in the MP3. **Ship the inserter, or remove the pass and the README promise. Effort: M to ship, S to kill.**
- **[P2 — IMPORTANT] Learning-path mode is built but not wired.** `/series` documented; no `learning_paths/` directory ever created; not invoked from `telegram_bot.py`. Ship it (wire the command + run end-to-end) or de-advertise. **Effort: S.**
- **[P2 — WORTH DOING] Source transparency could be stronger.** Companion JSON metadata is rich; spoken dialogue is generic ("the 2A03"). Add a "source-weaving" pass that nudges 1–2 named citations into the dialogue without cluttering. **Effort: M.**
- **[P3 — OPTIONAL] Personal context is live but rarely observed.** Infrastructure ready, listener profile empty. Five `/remember` commands unlock it. **Effort: S (configuration).**
- **[P3 — OPTIONAL] Guest mode works but bloats broad topics.** Use `guest_host_mode=auto` (default); educate use only for niche-authority topics.

**Standout strengths:** 11 episodes shipped in 10 days, zero failures in work-dir trail. Character continuity tracks across episodes. Source-grounding in metadata is sleek and technically sound. Local-first delivery is clean. Honest failure modes (MusicGen fallback to numpy, ffmpeg mastering fails → ship premaster).

**Originality read:** "AI podcast" is crowded, but *local-first, single-user, Telegram-triggered, source-grounded, character-memory-driven curiosity radio that runs on a gaming GPU at home* is rare. The original move: source-grounding first, aesthetic second. The user's commitment to topics (fetoscopy, FM synthesis, metronome history) is itself the real north star — without that, the "curiosity" framing would fall flat. With it, this works.

### G · Bug Hunt

**Overall health:** Mature. The codebase has absorbed most critical OPUS findings and demonstrates thoughtful error handling and atomic writes. No active P0 bugs.

**Active bugs (likely to bite soon):**

- **[P2 — WORTH DOING] Missing timeout on ffprobe call.** `clip_mixer.py:273` `_get_audio_duration()` lacks `timeout=30`. All other ffprobe/ffmpeg calls have one. **Effort: S.**

**Latent fragility:**

- **[P2 — WORTH DOING] Unbounded topic length at CLI.** `generate_podcast.py` main() has no length check; Telegram entry has `MAX_TOPIC_LEN=500`. Match it. **Effort: S.**
- **[P3 — OPTIONAL] 2026-06-06 cleanup TODO.** Comment-out of `shutil.rmtree` expires soon. Set the reminder or migrate to `$TEMP`. **Effort: S.**

**Standout strengths:** Atomic file writes via temp-and-`Path.replace()` in `personal_context.py` and `episode_manifest.py`. Subprocess timeout discipline (ffmpeg 600/30/120/900s, git 60/120s, yt-dlp 60/120s). `job_control.py` asyncio.Lock + cross-process PID check. Specific exception types in catch blocks (no bare `except:`). CDATA injection fixed (`_defuse_cdata_end`).

**OPUS-review status (since 2026-05-11):** CDATA escaping ✓ landed. Subprocess timeouts ✓ landed. Cleanup commented with date ✓. OpenAI voice IDs ✓ verified valid. Log file design ✓ correct. Two minor items still open: ffprobe timeout, CLI topic length.

**Originality read:** Pragmatic, not over-engineered. Pythonic "fail informatively" school. Specific exception names is good discipline. The duck-typing voice-routing design is fine for a single-user tool; would need protocols if it grew.

---

*End of report.*
