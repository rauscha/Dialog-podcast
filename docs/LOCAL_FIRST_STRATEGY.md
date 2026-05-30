# Local-First Production Strategy

Date: 2026-05-11

## Executive Take

The project can move a lot of runtime local without hurting the soul of the show, but not all of it should move local at once.

The highest-quality cheap split is:

| Pipeline Area | Best Route Now | Why |
|---|---|---|
| Research package | Cloud Claude with web search | Freshness, citations, uncertainty handling, and source discovery matter more than cost here. |
| Thesis, beat sheet, guest decision, sonic-footnote decision | Local candidate | These are editorial/planning tasks once research is already packaged. |
| Draft dialogue, anti-cliche rewrite, performance polish | Strong local candidate | Long runtimes are fine, and these are expensive token-heavy passes that can be evaluated by listening. |
| Non-fiction fact-check | Cloud Claude with web search | This is the safety rail. Keep it good. |
| Fiction continuity review | Local candidate | No live web search required. |
| Host memory update | Local candidate | Cheap structured summarization; low blast radius. |
| Learning path planning | Local candidate | Curriculum planning can be local after prompt tuning. |
| TTS | Local or mixed | The new `tts_routes` system supports local command engines per speaker. |
| Music | Local already | MusicGen or numpy fallback runs locally; the tiny prompt step is now local-capable too. |
| Audio mastering, chapters, companion site, RSS | Local already | ffmpeg and local file generation. |
| Clip search/download | Mostly local/network, cloud cue pass | `yt-dlp` and ffmpeg are local; cue annotation currently uses Claude. |

My candid recommendation: do not chase a fully local pipeline first. Chase a **local-heavy, quality-preserving pipeline**. Keep the expensive-but-critical research/fact-check guardrails on cloud models, move script craft and voice production local, then A/B test whether local research is good enough for evergreen topics.

## What Changed In This Pass

- Added local LLM adapters in `llm_engines.py`.
- `generate_podcast.py` can now route tool-free model calls to:
  - `ollama:<model>`
  - `local:<model>` using `local_llm_provider`
  - `lmstudio:<model>`
  - `openai-compatible:<model>`
- Local model routes are blocked when a stage asks for Anthropic tools, so research/fact-check do not silently degrade.
- `plan_learning_path.py` can now use local models for learning path planning.
- Added `local_first_report.py` for machine/config readiness checks.
- Made the MusicGen prompt step local-capable through `music_prompt_model`.
- Added `docs/OLLAMA_LOCAL_SERVICE.md` and setup/smoke-test scripts for bringing up Ollama on Windows.
- Documented local-first routing in `README.md`, `.env.example`, and Telegram setup docs.

## How To Try It

### Conservative Quality-Preserving Trial

Set up Ollama first:

```powershell
.\scripts\setup_ollama_windows.ps1 -Install -Start -Pull -ConfigureRepo -Model qwen3:14b
python scripts\ollama_smoke_test.py --model qwen3:14b
```

Keep research and fact-check on Claude. Move only the writing room local:

```json
{
  "research_model": "claude-opus-4-5",
  "dialogue_model": "ollama:your-local-writing-model",
  "fact_check_model": "claude-sonnet-4-6",
  "local_llm_provider": "ollama",
  "local_llm_base_url": "http://127.0.0.1:11434",
  "local_llm_num_ctx": 32768,
  "local_llm_keep_alive": "30m",
  "local_llm_think": false
}
```

This moves thesis planning, guest planning, sonic-footnote planning, beat sheets, drafting, naturalness rewrite, performance polish, and host memory update local.

### LM Studio / OpenAI-Compatible Trial

```json
{
  "dialogue_model": "openai-compatible:your-loaded-model",
  "local_llm_base_url": "http://127.0.0.1:1234/v1",
  "local_llm_timeout_sec": 3600
}
```

LM Studio documents that it can run downloaded models offline and expose OpenAI-like local endpoints; Ollama documents its local API at `localhost:11434/api`.

### TTS Local Trial

The new TTS routing layer already supports a local command adapter:

```json
{
  "tts_routes": {
    "CEDAR": {
      "provider": "command",
      "command": "python local_tts.py --text {text_path} --out {output_path} --voice cedar",
      "voice": "cedar"
    },
    "MARIN": {
      "provider": "openai",
      "voice": "onyx"
    }
  }
}
```

Use this to test Piper, Kokoro-style local tools, XTTS-style tools, or any local server wrapper without tying the podcast generator to one TTS project. Piper is worth testing for speed and reliability, but voice quality may not match paid neural TTS for a conversational two-host show. Always check voice/model licenses.

## Locality Scorecard

| Component | Current Locality | Move Local? | Risk |
|---|---|---:|---|
| Telegram bot | Local | Already local | Low |
| Job lock, manifests, context, host memory | Local | Already local | Low |
| Research | Cloud | Later | High: freshness/source quality |
| Source cards/key claims | Cloud | Later with local retrieval | Medium-high |
| Thesis/beat sheet | Cloud by default, local-capable | Now | Medium: style drift |
| Dialogue draft/rewrite/performance | Cloud by default, local-capable | Now | Medium: host voice quality |
| Fact-check | Cloud | Keep cloud for now | High: bad facts are expensive reputationally |
| Fiction continuity | Cloud by default, local-capable | Now | Low-medium |
| Learning path planning | Cloud by default, local-capable | Now | Low-medium |
| TTS | Cloud/mixed/local-capable | Now | Medium: voice quality |
| MusicGen | Local | Already local | Low |
| Music prompt | Cloud tiny call | Optional later | Low |
| Mastering | Local | Already local | Low |
| Companion website | Local/static | Already local | Low |

## Cost Strategy

The most cost-effective move is not local research. It is local drafting and rewriting.

The script quality upgrade intentionally added multiple passes. Those passes are exactly where local inference helps: they are long, subjective, iterative, and asynchronous. If a local model takes 45 minutes to make a better script for effectively zero marginal cost, that fits the project.

Recommended order:

1. Route `dialogue_model` local and listen to three episodes.
2. Keep `fact_check_model` cloud and compare before/after factual corrections.
3. Try local TTS for one host only, while the other host stays on OpenAI/ElevenLabs as a quality anchor.
4. Move learning path planning local.
5. Only then consider local retrieval for research.

## Quality Gates

Do not judge local quality by whether the script "looks okay." Judge by listening.

Use this checklist:

- Do Cedar and Marin still disagree in character, or do they collapse into one generic narrator?
- Are there fewer fake epiphanies and repetitive bridge phrases?
- Does the local model preserve speaker labels perfectly?
- Does the fact-check pass need to repair more than usual?
- Do guest experts sound authoritative without becoming encyclopedia entries?
- Does TTS handle interruptions, dry humor, and short turns naturally?

## Future Work

Highest-value next improvements:

- Add per-stage model routing beyond the three top-level model keys, for example `thesis_model`, `draft_model`, `rewrite_model`, `performance_model`, and `memory_model`.
- Add local retrieval: crawl selected trusted sources into a local vector store, then let local research work against that corpus for evergreen topics.
- Add automated A/B judging: generate local and cloud scripts from the same research package, then score for character separation, cliche density, unsupported claims, and listenability.
- Add a local TTS wrapper template for one recommended local engine so `tts_command` users do not have to write glue code first.
- Cache research packages by topic and source URL so repeated episodes pay only for new deltas.

## References

- Ollama API docs: https://docs.ollama.com/api
- LM Studio docs: https://lmstudio.ai/docs
- LM Studio offline operation: https://www.lmstudio.ai/docs/app/offline
- Piper repository: https://github.com/rhasspy/piper
