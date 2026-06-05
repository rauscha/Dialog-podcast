# State of the Art: Automated AI Podcast Generation — Scoping Review

*Compiled June 2026. A broad survey of how NotebookLM, commercial tools, open-source
projects, and the AI audio community design, write, refine, theme, and voice
auto-generated podcasts — mapped to this repo's pipeline (research → dialogue script →
fact-check → per-turn `gpt-4o-mini-tts` → ffmpeg assembly + MusicGen/clips).*

This is a **scoping document**, not a work order. Nothing here has been implemented.
The point is to lay out the landscape so we can later cherry-pick what's worth translating.

> ## 🔴 P0 — NEXT TASK
> **Create a walkthrough of next steps to implement these improvements.** This scoping
> review is complete; the current top priority is turning Section 7's shortlist into a
> concrete, ordered implementation walkthrough (what to change in `generate_podcast.py`,
> `clip_mixer.py`, and `music_gen.py`, in what order, with acceptance criteria) so the
> improvements can actually be built.

**Confidence tags used below:** `[CONFIRMED]` (primary source / first-party docs /
shipping code), `[REPORTED]` (credible secondary teardown, consistent across sources),
`[INFERRED]` (well-reasoned but unconfirmed), `[VENDOR]` (self-reported marketing —
discount accordingly).

---

## 0. The one finding that matters most

**NotebookLM's hosts sound human because the disfluencies are added by the *audio
model*, not written into the LLM script.** The "um"s, the micro-interjections ("Oh
really?", "Totally"), the stammers and breaths are a deliberate, separate final stage —
the team explicitly tunes for them because "if you don't have that noise, it sounds too
robotic." `[CONFIRMED — corroborated independently by 4 source trails]`

- Latent Space, *How NotebookLM Was Made* (Raiza Martin & Usama Bin Shafqat) —
  https://www.latent.space/p/notebooklm
- Simon Willison — https://simonwillison.net/2024/Sep/29/notebooklm-audio-overview/
- DeepMind podcast — https://deepmind.google/discover/the-podcast/inside-notebooklm-with-raiza-martin-and-steven-johnson/
- ElevenLabs GenFM's loading screen literally reads **"Sprinkling some umms"** /
  "adding some thoughtful pauses" — same philosophy, surfaced in the UI —
  https://techcrunch.com/2024/11/27/elevenlabs-new-feature-is-a-notebooklm-competitor-for-creating-genai-podcasts/

**Why this matters for us:** our `gpt-4o-mini-tts` is a *per-turn isolated generator* with
no cross-turn context and no native disfluency injection. So the work NotebookLM offloads
to its audio model, **we must do in the script and in post-processing.** This single
asymmetry drives most of the recommendations below. Note the deliberate counter-example:
MoonCast, SoulX-Podcast, and open-notebooklm instead put disfluencies *in the text* — which
is the path available to us.

---

## 1. Research & source-grounding (our Step 1)

The whole field converges on the same shape we already have: **research/RAG → brief →
script.** Validation that our design is correct, plus a few upgrades.

- **MoonCast** (NeurIPS 2025) uses an explicit two-prompt split: `INPUT2BRIEF` (condense
  sources to a tight brief) then `BRIEF2SCRIPT`. Its ablation found **script spontaneity
  is empirically as crucial as the TTS modeling itself** for perceived naturalness. `[REPORTED]`
  https://arxiv.org/abs/2503.14345 · https://www.alphaxiv.org/overview/2503.14345v2
- **Grounding reduces but never eliminates hallucination:** well-built RAG cuts it up to
  ~71%, but even RAG-powered legal tools hallucinated 17–34% of queries (Stanford). A
  dedicated grounding/fact-check pass is non-optional. `[CONFIRMED]`
  https://www.k2view.com/blog/what-is-grounding-and-hallucinations-in-ai/
- **Citation-Enhanced Generation** (arXiv 2402.16063): an NLI module **regenerates until
  every statement is supported by a citation** — a "regenerate-until-grounded" loop, which
  is a stronger pattern than our current single corrective pass. `[CONFIRMED]`
  https://arxiv.org/pdf/2402.16063
- **FACTS Grounding** (DeepMind) — a usable rubric for a factuality critic.
  https://deepmind.google/blog/facts-grounding-a-new-benchmark-for-evaluating-the-factuality-of-large-language-models/

**Translatable:** keep our research→brief split (it's the proven recipe); consider making
fact-check a *regenerate-until-grounded loop* rather than one pass; have research explicitly
emit a fact-rich brief that the script step consumes (we largely do this).

---

## 2. Script & dialogue generation (our Step 2)

### 2a. Architecture: outline-then-draft, chunked, multi-pass

- **Two-stage brief→script is the dominant pattern** (MoonCast, PodAgent, our pipeline). `[REPORTED]`
- **Per-section chunked generation beats single-shot for long content.** The closest
  reference architecture to ours is **`evandempsey/podcast-llm`** `[CONFIRMED — shipping code]`:
  research → `outline_episode` (Pydantic sections/subsections) → per-subsection **Q&A rounds**
  (interviewer `ask_question()` → expert `answer_question()`, default 2 rounds) →
  `write_final_script` **rewriter pass** → TTS. It also has **checkpoint/resume**.
  https://github.com/evandempsey/podcast-llm
- **Outline-first has measured long-form gains** — DOC (Detailed Outline Control) reports
  +22.5% plot coherence, +28.2% outline relevance, +20.7% interestingness over its baseline. `[CONFIRMED]`
  https://arxiv.org/html/2212.10077 · Skeleton-of-Thought https://github.com/imagination-research/sot

### 2b. Multi-agent writer / editor / critic loops

- **PodAgent** (ACL 2025 Findings): **Host-Agent** (outline + assigns guest profiles +
  curates questions) → **Guest-Agents** (answer from pre-defined expertise personas) →
  **Writer-Agent** (turns raw exchange into natural dialogue). Beats GPT-4 single-shot on
  content quality. `[CONFIRMED]` https://arxiv.org/abs/2503.00455
- **neuralnoise** (open source) implements exactly this as an AutoGen group chat:
  analyzer → script writers → editor → cast, with **per-segment JSON so only changed
  segments are re-rendered.** `[CONFIRMED — code]` https://github.com/leopiney/neuralnoise
- **Self-Refine** (generate → self-critique → revise): ~20% absolute average improvement
  across tasks *including dialogue generation*. `[CONFIRMED]` https://arxiv.org/abs/2303.17651
- **Anti-slop warning for the critic:** "Measuring AI Slop" (arXiv 2509.19163) finds reward
  models / naïve LLM judges **over-reward length, structure, jargon, sycophancy, and
  vagueness** — a generic "make it better" critic *rewards* slop. A good critic must
  explicitly penalize uniform sentence length, over-structure, and vagueness, and reward
  variability (fragments, tangents, callbacks). `[CONFIRMED]` https://arxiv.org/html/2509.19163v1

### 2c. The "verifier-gated, no-time-limit" pattern (most relevant to your overnight goal)

A comedy-podcast Show HN is the strongest reference for a quality-over-speed pipeline `[REPORTED]`:
- Durable workflow orchestration (Temporal); episode = **~10 independently written "beats,"
  each verified for grounding**; a **verifier gate checks factual claims, forbidden/cliché
  phrases, AND character-voice consistency before any audio renders**; ~2 hours end-to-end
  per episode — explicitly trading time for quality.
- https://news.ycombinator.com/item?id=47301386

### 2d. Prompt rules from actual shipping prompts

- **`open-notebooklm/prompts.py`** `[CONFIRMED — file read]`: "world-class podcast producer";
  **each dialogue line ≤ 100 characters** (≈5–8s); host always initiates; "occasional verbal
  fillers (um, well, you know)"; **guest responses must be substantiated by the input text**;
  arc = strong hook → increasing complexity → "breather moments" → end on a high note.
  https://github.com/gabrielchua/open-notebooklm/blob/main/prompts.py
- **Reverse-engineered NotebookLM style** `[INFERRED — reconstruction]`: open with "welcome back…",
  alternate short punchy lines with longer explanations, frequent affirmations ("Right,"
  "Exactly," "Absolutely"), rhetorical questions as transitions, analogies for complex ideas.
  https://nicolehennig.com/notebooklm-reverse-engineering-the-system-prompt-for-audio-overviews/

**Translatable:** generate per outline-section as interviewer/expert Q&A rounds (maps cleanly
onto Juno=curious / Caspar=expert); add a dedicated **rewriter/polish pass** after assembly;
make the critic explicitly anti-slop; for the "overnight quality" goal, adopt **beat-based
generation + a verifier gate (facts + cliché-phrases + per-character voice) before audio**;
keep lines short.

---

## 3. Theming, personas & show design

- **Persona must be structured fields, not just "tone."** Jellypod's framework — assign each
  host a **name, backstory, personality** and an archetypal role: **Anchor** (drives episode),
  **Analyst** (technical depth), **Advocate** (argues a position), **Skeptic** (challenges).
  Most directly copyable persona scheme. `[VENDOR but concrete]`
  https://www.jellypod.com/blog/create-multi-host-podcast-ai-voices
- **Podcastfy defaults** (copyable): `roles_person1: "main summarizer"`,
  `roles_person2: "questioner/clarifier"`; `engagement_techniques: [rhetorical questions,
  anecdotes, analogies, humor]`; explicit `[Introduction, Main Content, Conclusion]` structure. `[CONFIRMED]`
  https://github.com/souzatharsis/podcastfy/blob/main/usage/conversation_custom.md
- **personalized-podcast** ships a `PROMPT.md` "show bible": curious/expert dyad ("two friends
  over coffee, not news anchors"); a `tone` field flips serious/funny/academic; format presets
  include **debate** and **eavesdrop**. `[CONFIRMED — code]` https://github.com/zarazhangrui/personalized-podcast
- **Build in disagreement.** The most-repeated anti-boredom heuristic: hosts who agree on
  everything are boring; design respectful debate / tension. `[advice]`
- **Google had to tune hosts to *not act annoyed at humans*** — persona affect is a real
  failure mode worth guarding against. `[REPORTED]`
  https://techcrunch.com/2025/01/14/googles-notebooklm-had-to-teach-its-ai-podcast-hosts-not-to-act-annoyed-at-humans/
- **Show-level memory:** Moonfish's "create a show, then add episodes" model encodes
  persona/format once and lets episodes inherit it — a pattern for series consistency &
  recurring segments (cold open template, "hot takes," callbacks). `[REPORTED]`
  https://news.ycombinator.com/item?id=45635262
- **It's dramaturgy, not summarization:** good output feels *directed* — "one host sets up
  the idea, the other asks the obvious question, the first answers, the second reframes."
  https://roballandale.com/briefs/notebooklm-audio-overviews-workflow-teardown/

**Translatable:** give Juno & Caspar a persistent **character bible** (distinct vocabulary,
explicit roles — e.g. Juno=curious Anchor, Caspar=expert Analyst/Skeptic) stored across
episodes; add a reusable **cold-open template + recurring-segment** scaffold; deliberately
write in **respectful disagreement**.

---

## 4. Realistic voice interaction (the hard part for our per-turn TTS)

### 4a. The architectural divide

The biggest determinant of "do the hosts react to each other" is **whole-dialogue /
shared-context generation** (one model generates the whole conversation, so speaker B's
prosody is conditioned on speaker A) **vs. per-turn TTS concatenated** (prosody resets every
line — *our current approach*). The frontier has moved decisively to shared-context. `[CONFIRMED]`

- **Whole-dialogue / one-pass:** ElevenLabs v3 Text-to-Dialogue, Google Gemini native audio,
  MoonCast, VibeVoice, Dia, Higgs Audio v2, DialoSpeech.
- **Context-conditioned per-utterance:** Sesame CSM (conditions each turn on prior turns'
  actual *audio* — the canonical "prosody continuity" mechanism). https://github.com/SesameAILabs/csm
- **Full-duplex real-time** (overlaps/backchannels emerge natively): Kyutai Moshi, OpenAI
  gpt-realtime, Gemini native audio — built for live agents, not batch rendering.

### 4b. How the dialogue models express interaction

- **ElevenLabs v3 audio tags** (inline, free-text brackets, *not* an enum): turn-taking
  `[interrupting]` `[overlapping]`; emotion `[excited]` `[annoyed]`; pacing `[hesitates]`
  `[pause]`; non-verbals `[laughs]` `[sighs]` `[whispers]`. Overlap convention: **em-dash at
  the cut-off point**, next speaker picks up mid-thought; ellipses/periods control pauses. `[CONFIRMED]`
  https://elevenlabs.io/blog/v3-audiotags · https://elevenlabs.io/docs/overview/capabilities/text-to-dialogue
- **Dia** (open, Apache-2.0, 1.6B, runs on consumer GPU): `[S1]`/`[S2]` speaker tags;
  `(laughs)` `(coughs)` rendered as real non-verbal audio. Architecture inspired by SoundStorm
  + Descript Audio Codec. https://github.com/nari-labs/dia `[CONFIRMED]`
- **Play.ai PlayDialog's "Adaptive Speech Contextualizer"**: conditions each turn on the full
  conversation history so co-hosts "feed off each other." Same core idea as CSM. `[VENDOR/REPORTED]`
  https://blog.play.ai/blog/introducing-playdialog
- **MoonCast's spontaneity trick:** its script module emits **ASR-transcript-style scripts**
  that already contain fillers, hesitations, and breathing pauses (via punctuation/spacing),
  then the audio LM is trained to render that style. `[REPORTED]` https://arxiv.org/abs/2503.14345
- **SoulX-Podcast** uses inline paralinguistic tags in text: `<|laughter|>` `<|sigh|>`
  `<|breathing|>`; 90+ min stable timbre. https://arxiv.org/abs/2510.23541 `[REPORTED]`

### 4c. Backchannels & timing research (for a concatenative pipeline like ours)

- **>40% of natural speaker turns involve overlapping speech**; backchannels ("mm-hmm,"
  "right," "yeah") are short tokens that react without taking the floor. `[CONFIRMED]`
  https://arxiv.org/html/2509.04093v1
- **Filler words only work with correct timing**: humans say "um" → *pause* → restart with a
  connector ("so…"). Agents that say "um" then continue at full speed sound *more* fake. Place
  fillers before complex/important words. `[REPORTED — LiveKit/Rime]`
  https://blog.livekit.io/prompting-voice-agents-to-sound-more-realistic/ ·
  https://rime.ai/resources/filler-words-a-secret-facet-of-conversational-realism
- **Speaker-aware timing simulation** (arXiv 2509.15808, "From Independence to Interaction"):
  model inter-speaker gaps/overlaps rather than fixed silences when assembling independent
  tracks. `[CONFIRMED]` https://arxiv.org/pdf/2509.15808

### 4d. `gpt-4o-mini-tts` hard limits (our current model)

- Steered by a whole-input natural-language **`instructions`** field (not SSML, not per-word
  tags). **No cross-turn context, no seed → prosody resets each call, non-deterministic;**
  long outputs (>1–2 min) can drift. ~2,000-token window. The `instructions` text is billed. `[CONFIRMED]`
  https://community.openai.com/t/gpt-4o-mini-tts-too-inconsistant-can-we-get-a-seed-id-back/1292673

**Translatable (keep gpt-4o-mini-tts, simulate the rest):**
1. **Script-level disfluency/backchannel pass** after fact-check — inject light "um/uh,"
   false starts, and short backchannel turns ("mm-hmm," "right," "oh interesting") for the
   *listening* host, with the filler-then-pause-then-connector timing rule.
2. **Trim per-clip edge silence, then insert variable speaker-aware gaps** (~150–250ms fast
   exchanges, ~400–700ms at topic shifts) instead of fixed pauses.
3. **Render backchannels as tiny separate TTS turns and *overlay* them** (ffmpeg `amix`/`adelay`,
   ducked ~6–10 dB, ~80–150ms before the speaker finishes) rather than concatenating.
4. **Thread emotional state across turns** by passing the prior turn's emotion into the next
   line's `instructions` ("continuing the excited tone, now more reflective") so prosody
   doesn't hard-reset.
5. **Use punctuation for pacing** (ellipsis = trail off, em-dash = interruption then physically
   overlap the clips, commas = breath).
6. **Add a low room-tone bed under the whole dialogue** so silences aren't dead-digital — alone
   reduces the "two clips stitched" feel.

**The ceiling fix** is to move the dialogue render to a shared-context model (ElevenLabs v3
Text-to-Dialogue hosted, or **Dia / MoonCast / Higgs Audio v2** self-hosted on GPU) so
reactions and prosody are generated *jointly* rather than hand-simulated. Note **VibeVoice
does NOT do overlaps**; Dia / DialoSpeech / Higgs / v3 are the overlap-capable options.

---

## 5. TTS landscape & audio assembly (our Step 4)

### 5a. Model landscape (2025–2026)

| Model | ~Cost | Emotion control | Cloning | Notes |
|---|---|---|---|---|
| **OpenAI gpt-4o-mini-tts** (ours) | ~$0.015/min | whole-input `instructions` only | No | Cheapest mainstream; no per-word tags, no cross-turn context |
| **ElevenLabs v3** | credit-based, higher | inline `[tags]`, per-word | Yes (best) | Expressiveness/cloning leader; native Text-to-Dialogue |
| **Hume Octave 2** | ~$50–150/1M ch | infers from text, no tags | Yes | "Reads for meaning" (renders sarcasm) |
| **Cartesia Sonic 3** | ~$35/1M ch | AI laughter/emotion | 3s instant | Latency leader (~40–90ms) |
| **Google Gemini 2.5 TTS** | $0.01–0.08/1K ch | text-steerable | — | Native multi-speaker one-generation |
| **Kokoro-82M** (open) | <$0.06/hr audio | — | No | Tiny, CPU-capable, topped TTS Arena; single-speaker |
| **Chatterbox** (open) | self-host | from 10s ref | Yes | Beat ElevenLabs Turbo ~64% in *vendor* blind test |
| **Dia / VibeVoice / Higgs v2** (open) | self-host | tags / nonverbals | Yes | Dialogue-native multi-speaker |

`[CONFIRMED for capabilities; pricing volatile — verify before relying]`
Leaderboards (Artificial Analysis Speech Arena, TTS Arena V2): realtime models from Alibaba,
Google Gemini, Inworld, Cartesia now top *blind naturalness* Elo; **ElevenLabs v3 remains the
expressiveness/cloning leader but no longer clearly #1 on raw naturalness.** `[REPORTED — Elo volatile]`

### 5b. Audio assembly — concrete numbers worth adopting

- **Loudness:** Apple = **−16 LUFS** (±1, what we use); Spotify/YouTube normalize to **−14 LUFS**.
  Safe compromise: **−14 LUFS, True Peak −1.0 dBTP.** `[CONFIRMED]`
  https://sone.app/blog/podcast-loudness-standards-2026-spotify-apple-youtube
- **Two-pass ffmpeg `loudnorm`** (EBU R128) with `linear=true` applies one constant gain so
  dialogue dynamics aren't squashed — the **single highest-value missing step** for us.
  Or use the `ffmpeg-normalize` Python wrapper (`--preset podcast`). `[CONFIRMED]`
  https://dev.to/masonwritescode/two-pass-loudness-normalization-with-ffmpeg-loudnorm-the-right-way-1nm3
- **Micro-crossfade ~10ms at every concat join** (ffmpeg `acrossfade`) kills clicks between
  per-turn files; 2–5s fades for music↔speech bookends. `[CONFIRMED]`
- **Sample rate 48kHz/24-bit internally** (stay consistent across narration, music, clips);
  export **128kbps mono** (or 192 stereo if music-heavy). `[CONFIRMED]`
- **De-esser ~5–9 kHz before the limiter** — AI TTS sibilance is a known artifact. `[CONFIRMED]`
- **Mastering chain:** EQ → compression → de-essing → limiting (brick-wall at −1.0 dBTP). `[CONFIRMED]`

### 5c. Music & clips (our MusicGen + clip_mixer)

- **Music bed at −18 to −20 LUFS** (~6–8 LU below speech); **duck −6 to −12 dB under speech**
  via ffmpeg `sidechaincompress` (ref: `threshold=0.02, ratio=4, attack=200ms, release=800ms`). `[CONFIRMED]`
- **Loudness-match every inserted clip** (two-pass `loudnorm` per clip to the program target)
  before interleaving — so YouTube clips don't jump in volume. `[CONFIRMED]`
- MusicGen remains the right open/local fit for an auto-pipeline; Suno v5.5 / Udio are higher
  quality but require their platforms. `[REPORTED]`

**Translatable (high value, low effort, all ffmpeg):** add a final **two-pass loudnorm master**;
**normalize each clip** in `clip_mixer.py` to the same target; **duck music** under speech;
**micro-crossfade** concat joins; add a **de-esser** stage; standardize 48k internal / 128k export.

---

## 6. Open-source reference projects (closest to our shape)

| Project | Stars | Why it's worth a look |
|---|---|---|
| `souzatharsis/podcastfy` | ~6.3k | De-facto open NotebookLM; pluggable LLM + 4 TTS backends; chunked longform; copyable persona config |
| `MODSetter/SurfSense` | ~14.4k | Privacy-focused, unlimited sources; "two-host podcast" built in |
| `evandempsey/podcast-llm` | ~150 | **Closest reference architecture**: outline → per-section Q&A rounds → rewriter; checkpoint/resume |
| `leopiney/neuralnoise` | ~225 | Multi-agent writer→editor with **per-segment re-render** |
| `gabrielchua/open-notebooklm` | — | Clean shipping prompts (line-length, grounding, arc) |
| `microsoft/VibeVoice` | — | 90-min, 4-speaker open dialogue TTS (no overlaps) |
| `nari-labs/dia` | — | Consumer-GPU dialogue-native TTS with `[S1]/[S2]` + nonverbals |
| `Soul-AILab/SoulX-Podcast` | — | 90-min podcast TTS with inline paralinguistic tags |

---

## 7. Shortlist — what looks most translatable to *this* pipeline

Ordered by impact-to-effort, to sort through later. **(Not yet decided or implemented.)**

**Cheap & high-impact (script + ffmpeg, keep gpt-4o-mini-tts):**
1. Final **two-pass loudnorm master** + **per-clip loudness match** + **music ducking** +
   **10ms concat crossfades** + **de-esser**. (Pure audio-engineering; biggest quality jump
   for least work.)
2. **Script-level disfluency/backchannel pass** with correct filler→pause→connector timing.
3. **Variable, speaker-aware inter-turn gaps** (+ trim per-clip edge silence) and **overlaid
   backchannels** instead of fixed-gap concat.
4. **Anti-slop critic** + a **rewriter/polish pass** after the script.
5. **Persona character-bible** for Juno/Caspar (distinct roles + vocabulary) with deliberate
   disagreement; persist it for series consistency.

**Medium (architecture, fits the "overnight / quality-over-speed" goal):**
6. **Beat-based + verifier-gated generation**: write the episode as N beats, each grounded;
   a gate checks facts + cliché phrases + per-character voice **before audio renders**; with
   **checkpoint/resume**. Thread prior-turn emotion into each `instructions`.
7. **Per-outline-section Q&A-round generation** (interviewer/expert) for longer episodes.
8. **Regenerate-until-grounded fact-check** loop.

**Big lever (needs a GPU or paid API — the realism ceiling):**
9. Swap the dialogue render to a **shared-context / dialogue-native model** (ElevenLabs v3
   Text-to-Dialogue hosted; or Dia / Higgs Audio v2 / MoonCast self-hosted) so cross-host
   reactions and prosody are generated jointly instead of simulated. (Overlap-capable: Dia,
   DialoSpeech, Higgs, v3 — *not* VibeVoice.)

---

## 8. Caveats on this review

- WebFetch was blocked (HTTP 403) on many primary pages, so a number of paper/blog specifics
  rest on search-engine extracts rather than full-page reads. The most reliably-sourced items
  are the shipping GitHub prompts/code (read via raw.githubusercontent), the NotebookLM
  disfluency finding (4 independent trails), the ElevenLabs/Dia tag schemas, and the
  audio-engineering numbers.
- Vendor benchmark wins (VibeVoice > v3, Octave > ElevenLabs, Chatterbox > ElevenLabs Turbo)
  are **self-reported** — treat as marketing until independently reproduced.
- TTS leaderboard Elo and all pricing shift frequently — verify live before committing.
- The SoundStorm/AudioLM-is-NotebookLM's-audio-model lineage is **well-reasoned inference**,
  not confirmed by Google. The reverse-engineered NotebookLM "system prompt" is a
  reconstruction, not the real prompt.
