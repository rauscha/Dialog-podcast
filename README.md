# Asynchronous

Asynchronous is a personal curiosity-radio generator. Send it a topic, and Cedar and Marin turn that stray question into a source-grounded two-host episode with research, dialogue, fact-checking, two-voice TTS, optional generated music, and RSS publishing.

The active remote workflow is local-first: a Telegram bot runs on your home machine, receives a topic from your phone, and launches the generation pipeline without exposing an inbound port.

---

## The Hosts

**Cedar** - Artistic, broad-thinking, asks "what does this mean for us?" She finds unexpected metaphors, follows tangents that sometimes become the point, and speaks with warmth and wonder.

**Marin** - Scientifically grounded, methodical, slightly older and more skeptical. He is the "well, actually" voice with dry wit and genuine curiosity, not pedantry. He names researchers, cites data, and keeps Cedar's flights of fancy anchored in evidence.

---

## Requirements

- **Python 3.10+**
- **ffmpeg** on PATH for audio concatenation, format conversion, and clip trimming
- **CUDA GPU recommended** for MusicGen; CPU works but is slow
- API keys: Anthropic required; at least one configured TTS provider such as OpenAI, ElevenLabs, or a local command engine

### Python Dependencies

```bash
pip install -r requirements.txt
```

> Note on `audiocraft`: Meta's audiocraft package may require a separate install step and a matching PyTorch version. If audiocraft is not installed, music generation falls back when possible or is skipped gracefully.

---

## Setup

1. Copy `.env.example` to `.env` and fill in your keys:

   ```text
   ANTHROPIC_API_KEY=sk-ant-...
   OPENAI_API_KEY=sk-...   # for OpenAI TTS routes
   ELEVENLABS_API_KEY=...  # for ElevenLabs TTS routes
   TELEGRAM_BOT_TOKEN=1234567890:AAE...
   TELEGRAM_ALLOWED_USERS=123456789
   ```

2. Edit `config.json`.

   At minimum, set `github_user` and `github_repo` if you want RSS publishing via GitHub Pages.

3. Install ffmpeg if not already present:

   - Windows: `winget install ffmpeg`
   - macOS: `brew install ffmpeg`
   - Linux: `apt install ffmpeg`

4. Load environment variables before running:

   ```powershell
   Get-Content .env | ForEach-Object { if ($_ -notmatch '^#') { $k,$v = $_ -split '=',2; [Environment]::SetEnvironmentVariable($k,$v) } }
   ```

---

## Generating An Episode

```powershell
python generate_podcast.py "the science of sleep and memory consolidation"
```

Or interactively:

```powershell
python generate_podcast.py
```

Development flags:

```powershell
$env:SKIP_GIT="true"; python generate_podcast.py "your topic"
$env:USE_MUSIC="false"; python generate_podcast.py "your topic"
$env:USE_CLIPS="true"; python generate_podcast.py "your topic"
python generate_podcast.py "build a tiny FM synth" --type how_to
python plan_learning_path.py "synthesis for app developers" --episodes 5 --level beginner-to-intermediate
```

Clips are off by default for safer publishing. Turn them on only for private experiments or rights-cleared runs.

---

## Triggering Remotely

The active remote-trigger path is a **Telegram command center** running on your tower. See [telegram-instructions.md](telegram-instructions.md) for setup.

```text
You on phone -> Telegram -> bot on tower -> generate_podcast.py -> episode + RSS
```

The bot uses long polling, so your machine does not expose a public inbound port.

Useful bot commands:

```text
/generate <topic>  Start an episode
/generate --type landscape <topic>
/generate how_to: <topic>
/generate --guest <topic>
/generate --no-guest <topic>
/series <topic> 5 episodes beginner-to-intermediate
/status            Show active run, lock, log, and manifest state
/cancel            Stop the active run
/queue <topic>     Save a topic for later
/types             List episode formats
/paths             Show the latest learning path
/context           Show personal context and covered topics
/remember domain <text>
/remember background <text>
/remember depth <text>
/tts               Show active TTS routing config
/latest            Show the latest episode manifest
/doctor            Check local prerequisites
```

Plain text does not start a generation; expensive work requires `/generate`.

Archived alternative: the old SendGrid email + Flask webhook + Fly.io path lives under [archive/email-webhook/](archive/email-webhook/README.md). It is not the recommended active path.

---

## Companion Website

`index.html` is a static companion site for GitHub Pages. It reads `feed.xml`, renders the episode archive, and turns the latest episode into a webplayer with chapter seeking and follow-up links.

Each new generated episode publishes two companion artifacts beside the MP3:

```text
episodes/<timestamp>_<topic>.chapters.json
episodes/<timestamp>_<topic>.companion.json
```

The RSS item points podcast apps to the chapters file with `<podcast:chapters>`. The website also reads the companion JSON for episode type, chapter titles, source-derived follow-up links, and source metadata. Older feed items without companion files still appear in the archive with basic playback.

---

## Configuration Reference

Defaults live in `generate_podcast.py`, repo settings live in `config.json`, and every config key can be overridden by an uppercase environment variable.

| Key | Default | Description |
|-----|---------|-------------|
| `podcast_title` | `"Asynchronous"` | RSS feed title |
| `podcast_description` | Personal curiosity-radio description | RSS feed description |
| `podcast_author` | `"Cedar & Marin"` | iTunes author field |
| `podcast_email` | `"you@example.com"` | iTunes owner email |
| `podcast_language` | `"en"` | RSS language tag |
| `podcast_category` | `"Science"` | iTunes category |
| `github_user` | `""` | GitHub username for RSS hosting |
| `github_repo` | `"dialog-podcast"` | GitHub repo name |
| `github_branch` | `"main"` | Branch intended for publishing |
| `research_model` | `"claude-opus-4-5"` | Research model; keep cloud-routed for web search quality |
| `dialogue_model` | `"claude-sonnet-4-6"` | Main script/planning model; can be `ollama:<model>` or `openai-compatible:<model>` |
| `fact_check_model` | `"claude-sonnet-4-6"` | Fact/continuity review model; cloud recommended for live fact-checking |
| `local_llm_provider` | `"ollama"` | Provider for `local:<model>` aliases |
| `local_llm_base_url` | `"http://127.0.0.1:11434"` | Ollama or OpenAI-compatible local server URL |
| `local_llm_timeout_sec` | `3600` | Timeout for long-running local LLM calls |
| `local_llm_num_ctx` | `32768` | Ollama context window hint |
| `local_llm_keep_alive` | `"30m"` | Ollama model keep-alive hint |
| `local_llm_think` | `false` | Disable Ollama thinking output by default so pipeline calls return clean script text |
| `tts_provider` | `"openai"` | Fallback TTS provider: `"openai"`, `"elevenlabs"`, or `"command"` |
| `host_a_name` | `"Cedar"` | Display name for host A |
| `host_a_voice` | `"cedar"` | Default OpenAI/local-command voice for host A |
| `host_a_role` | `"artistic"` | Informational label |
| `host_b_name` | `"Marin"` | Display name for host B |
| `host_b_voice` | `"marin"` | Default OpenAI/local-command voice for host B |
| `host_b_role` | `"scientific"` | Informational label |
| `elevenlabs_voice_id_a` | `""` | ElevenLabs voice ID for host A |
| `elevenlabs_voice_id_b` | `""` | ElevenLabs voice ID for host B |
| `elevenlabs_model` | `"eleven_turbo_v2"` | ElevenLabs model used by ElevenLabs routes |
| `elevenlabs_stability` | `0.5` | Default ElevenLabs stability setting |
| `elevenlabs_similarity_boost` | `0.75` | Default ElevenLabs similarity setting |
| `tts_default_route` | `{}` | Route fields merged into every speaker before per-speaker overrides |
| `tts_routes` | `{}` | Speaker-specific route map keyed by `DEFAULT`, `CEDAR`, `MARIN`, `GUEST`, or exact speaker label |
| `tts_request_timeout_sec` | `180` | Network timeout for provider HTTP calls |
| `tts_command` | `""` | Generic local command adapter for experimental TTS engines |
| `tts_command_cwd` | `""` | Optional working directory for command TTS |
| `tts_command_timeout_sec` | `600` | Timeout for command TTS processes |
| `target_minutes` | `15` | Target episode length |
| `output_dir` | `"episodes"` | Directory for output MP3s |
| `episode_type` | `"deep_dive"` | Default episode format |
| `learning_path_dir` | `"learning_paths"` | Directory for learning path plans |
| `learning_path_default_episodes` | `5` | Default mini-course length |
| `learning_path_default_level` | `"beginner-to-intermediate"` | Default learner level |
| `learning_path_model` | `"claude-sonnet-4-6"` | Model for learning path planning |
| `use_clips` | `false` | Insert third-party clips when explicitly enabled |
| `use_music` | `true` | Generate intro/outro music |
| `use_sonic_footnotes` | `true` | Let the script pipeline consider rights-aware open audio flourishes |
| `sonic_footnotes_catalog` | `"sonic_footnotes.json"` | Open/PD/CC sonic footnote source catalog |
| `use_guest_hosts` | `true` | Allow synthetic/composite guest expert personas |
| `guest_host_mode` | `"auto"` | Guest mode: `"auto"`, `"force"`, or `"off"` |
| `guest_host_max` | `1` | Maximum guest personas per episode |
| `guest_host_voice_pool` | OpenAI voice IDs | Voice pool for guest personas, excluding Cedar/Marin voices where possible |
| `elevenlabs_guest_voice_ids` | `""` | Optional comma-separated ElevenLabs voice IDs for guest personas |
| `script_quality_pipeline` | `true` | Use the multi-pass script writers' room |
| `host_memory_path` | `"host_memory.json"` | Persistent Cedar/Marin memory and character bible |
| `host_memory_max_episodes` | `12` | Episode memories retained for future callbacks |
| `host_memory_max_items` | `18` | Shared host memories retained |
| `use_personal_context` | `true` | Tune episodes to your background, preferred depth, domains, and prior coverage |
| `personal_context_path` | `"personal_context.json"` | Local private listener profile and topic history |
| `personal_context_max_topics` | `24` | Recent covered topics retained for repeated-topic detection |
| `personal_context_similarity_threshold` | `0.34` | Similarity cutoff for treating a topic as already covered |
| `personal_context_sync_manifests` | `true` | Seed topic history from existing episode manifests |
| `tts_model` | `"gpt-4o-mini-tts"` | OpenAI TTS model |
| `use_emotive_tts` | `true` | Pass delivery instructions to supported TTS models |
| `turn_silence_ms` | `180` | Pause inserted between separately synthesized host turns |
| `use_audio_mastering` | `true` | Apply final high/low-pass, loudness normalization, and publish encode |
| `audio_bitrate` | `"192k"` | MP3 bitrate for intermediate/final production encodes |
| `audio_sample_rate` | `44100` | Final sample rate |
| `audio_channels` | `2` | Final channel count, mono or stereo |
| `audio_loudness_i` | `-16.0` | Integrated loudness target for FFmpeg `loudnorm` |
| `audio_true_peak` | `-1.5` | True-peak ceiling for FFmpeg `loudnorm` |
| `audio_lra` | `11.0` | Loudness range target for FFmpeg `loudnorm` |
| `audio_highpass_hz` | `60` | Remove low rumble before loudness normalization |
| `audio_lowpass_hz` | `18000` | Gently remove extreme high-frequency hash before normalization |
| `music_prompt_model` | `"claude-haiku-4-5-20251001"` | Tiny prompt-writing model for MusicGen; can be local |
| `music_model` | `"facebook/musicgen-small"` | MusicGen model name |
| `music_duration_sec` | `12` | Length of intro/outro music clip |
| `music_fade_sec` | `2` | Fade duration in seconds |

Boolean environment values accept `true/false`, `yes/no`, `on/off`, and `1/0`.

## Modular TTS Routing

The audio pipeline now resolves a TTS route for each speaker. You can keep the old single-provider setup with `tts_provider`, or mix providers per host and guest with `tts_routes`.

Example `config.json` override:

```json
{
  "tts_default_route": {
    "max_chars": 3800
  },
  "tts_routes": {
    "CEDAR": {
      "provider": "openai",
      "voice": "marin",
      "model": "gpt-4o-mini-tts"
    },
    "MARIN": {
      "provider": "elevenlabs",
      "voice_id": "your-elevenlabs-voice-id",
      "model": "eleven_turbo_v2",
      "stability": 0.42,
      "similarity_boost": 0.82
    },
    "GUEST": {
      "provider": "openai",
      "voice": "sage"
    }
  }
}
```

For local or experimental engines, use the `command` provider. The process must write the requested audio file to `{output_path}`; the adapter also provides `{text_path}`, `{voice}`, `{model}`, and `{metadata_path}` placeholders. Commands are run directly, not through a shell.

```json
{
  "tts_routes": {
    "DEFAULT": {
      "provider": "command",
      "command": "python local_tts.py --text {text_path} --out {output_path} --voice {voice}",
      "voice": "cedar-local",
      "model": "my-local-engine"
    }
  }
}
```

Each run records the resolved public routes in `episode_manifest.json` and the episode companion JSON, with secrets and command strings omitted.

From Telegram, `/tts` shows the active fallback provider, configured speaker routes, and whether required provider keys are present.

## Local-First Production

Quality-first recommendation: keep `research_model` and non-fiction `fact_check_model` on Claude because those stages currently use Anthropic web search tools. Move the tool-free writing/editing stages first:

```json
{
  "dialogue_model": "ollama:your-local-writing-model",
  "local_llm_provider": "ollama",
  "local_llm_base_url": "http://127.0.0.1:11434",
  "local_llm_num_ctx": 32768,
  "local_llm_think": false
}
```

For LM Studio, llama.cpp server, vLLM, or another OpenAI-compatible local server:

```json
{
  "dialogue_model": "openai-compatible:your-loaded-model",
  "local_llm_base_url": "http://127.0.0.1:1234/v1"
}
```

Local model prefixes supported by the generator are `local:`, `ollama:`, `lmstudio:`, and `openai-compatible:`. Local routes are intentionally blocked from stages that request Anthropic web-search tools, because silently dropping research tools would make episodes cheaper but less trustworthy.

Run a readiness report:

```powershell
python local_first_report.py
```

For a Windows Ollama bootstrap, see [docs/OLLAMA_LOCAL_SERVICE.md](docs/OLLAMA_LOCAL_SERVICE.md):

```powershell
.\scripts\setup_ollama_windows.ps1 -Install -Start -Pull -ConfigureRepo -Model qwen3:14b
python scripts\ollama_smoke_test.py --model qwen3:14b
```

The practical cheap/high-quality split is: cloud research and web fact-checking, local script drafting/rewrite/performance polish where your machine has enough VRAM, local or mixed TTS through `tts_routes`, local MusicGen/numpy music, and local ffmpeg mastering.

## Episode Types

Use an episode type when the same topic could become different shows:

| Type | Use it for |
|---|---|
| `deep_dive` | Layered narrative investigation |
| `overview` | Clear primer for a smart newcomer |
| `how_to` | Practical teaching, workflows, and build steps |
| `landscape` | Market/tool/trend scouting and weak signals |
| `case_study` | One concrete story as a lens |
| `story` | Narrative-first scenes, characters, and turns |
| `myth_bust` | Careful teardown of a popular belief |
| `debate` | Structured affectionate disagreement |
| `history` | Origin story and turning points |
| `field_guide` | How to notice patterns in the world |
| `decision_brief` | Tradeoff analysis for choosing a path |
| `critique` | Rigorous, generous evaluation of a work or idea |
| `future_scenario` | Grounded speculation with uncertainty labels |
| `lab_notes` | Build log, experiment, or debugging story |
| `complete_fiction` | Fully invented two-voice audio story |
| `review` | Consolidation, quiz, and retrieval practice |

## Learning Path Mode

Learning path mode turns one topic into a 3-8 episode mini-course:

```powershell
python plan_learning_path.py "synthesis for app developers" --episodes 5 --level beginner-to-intermediate
```

From Telegram:

```text
/series "synthesis for app developers" 5 episodes beginner-to-intermediate
/series --episodes 4 --level advanced "computer graphics fundamentals"
/series --plan-only "history of obstetric ultrasound"
```

`/series` writes `learning_paths/<path_id>_<topic>/learning_path.json` and `.md`. Unless `--plan-only` is supplied, it also queues the planned episodes so `/next` starts lesson 1.

## Personal Context Mode

Personal context mode keeps a local listener profile in `personal_context.json`. It stores favorite domains, professional background, preferred depth, learning goals, style preferences, avoid rules, and topic history. The generator uses it during research, thesis, beat-sheet, dialogue, and learning-path planning.

When a new topic overlaps something in topic history, the prompt explicitly asks the writers' room to avoid repeating the same primer and instead choose a deeper mechanism, unresolved question, advanced application, or fresh angle. On load, the file can also seed topic history from existing episode manifests.

Telegram commands:

```text
/context
/remember background principal engineer working on developer tools
/remember domain audio systems
/remember depth assume I want mechanism-level explanations after a short orientation
/remember goal get better at production ML systems
/remember style candid, specific, no fake awe
/remember avoid generic beginner summaries
```

`personal_context.json` is ignored by git because it can contain private information. Each run snapshots the context that shaped the episode into the episode work directory.

## Sonic Footnotes

Sonic footnotes are optional micro-cues from open or public-domain audio sources. The writers' room now has a dedicated pass that asks whether the episode would benefit from one. Most episodes should say no.

The catalog lives in `sonic_footnotes.json` and currently points to rights-aware source pools such as NASA media, Wikimedia Commons, Freesound CC0/CC BY searches, and public-domain archival audio. The plan is saved as `sonic_footnote_plan.json` in the episode work directory and recorded in the manifest.

This pass does not blindly download or splice remote files. Items marked `requires_file_verification` or `requires_item_verification` must be resolved to a specific file and attribution before a future mixer inserts them.

## Guest Expert Mode

Guest expert mode lets some episodes add a third chair: a synthetic/composite guest persona with topic-specific expertise, an independent personality, and a distinct TTS voice. In `auto` mode, the producer pass skips guests unless they genuinely add authority or a useful point-of-view. Use `--guest` or `GUEST_HOST_MODE=force` when you want an interview-style episode.

Guests are not real people and do not impersonate real people. They are disclosed in show notes as synthetic composite expert voices.

```powershell
python generate_podcast.py "why databases choose B-trees" --guest
python generate_podcast.py "the ethics of embryo selection" --guest-mode off
```

Telegram examples:

```text
/generate --guest landscape: open source robotics
/generate --no-guest a quick overview of HTTP caching
```

## Audio Production

The audio path now adds short pauses between independently synthesized host turns, encodes production segments at 192 kbps by default, and runs a final mastering pass before publishing. The mastering pass uses FFmpeg filters for low-rumble cleanup, high-frequency cleanup, and podcast-style loudness normalization.

Defaults target roughly `-16 LUFS` integrated loudness, `-1.5 dBTP` true peak, and `11 LU` loudness range. If FFmpeg mastering fails, the episode is left as the premaster audio and the manifest records a warning instead of throwing away the run.

---

## Architecture

```text
generate_podcast.py   orchestrator: research -> script -> fact-check -> audio -> RSS/git
  |-- music_gen.py    MusicGen wrapper; numpy ambient-pad fallback when audiocraft absent
  |-- clip_mixer.py   Optional clip extraction and audio assembly
  |-- episode_manifest.py durable metadata spine for each run
  |-- episode_types.py shared episode format definitions
  |-- job_control.py  cross-process lock and cancellation helpers
  |-- plan_learning_path.py mini-course planner and queue source
  |-- sonic_footnotes.py rights-aware sonic flourish catalog helpers
  |-- personal_context.py private listener profile and topic-history helpers
  |-- host_memory.json persistent host traits, callbacks, and anti-cliche phrases

telegram_bot.py       long-polling Telegram command center; spawns generate_podcast.py

archive/email-webhook/ deprecated SendGrid + Flask + Fly.io path
```

Each run writes `episode_manifest.json`, `research_brief.md`, `source_cards.json`, `guest_plan.json`, `beat_sheet.md`, `personal_context_snapshot.json`, `personal_context_update.json`, draft scripts, and `script.txt` into its work directory. `/status` and `/latest` read the manifest so the bot can report stage, output paths, duration, warnings, and failure details.

The default script path is now multi-pass: research package -> thesis -> guest decision -> beat sheet and host stance map -> dialogue draft -> anti-cliche rewrite -> fact-check -> performance script -> host-memory update. Set `SCRIPT_QUALITY_PIPELINE=false` for the older, faster three-pass path.

AI-generated voices are synthetic; public descriptions should disclose that Cedar and Marin are generated hosts.
