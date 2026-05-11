# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running an episode

```powershell
# Set env vars first (once per shell session)
Get-Content .env | ForEach-Object { if ($_ -notmatch '^#') { $k,$v = $_ -split '=',2; [Environment]::SetEnvironmentVariable($k,$v) } }

python generate_podcast.py "your topic here"
# or interactively: python generate_podcast.py

# Skip git push during development
$env:SKIP_GIT=1; python generate_podcast.py "your topic"

# Disable MusicGen (faster, no GPU needed)
$env:USE_MUSIC="false"; python generate_podcast.py "your topic"
```

## Running the Telegram bot

```powershell
python telegram_bot.py
# Requires: TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_USERS (numeric IDs, comma-separated)
# Logs to: logs/bot.log
```

## Architecture

```
generate_podcast.py   orchestrator — 5-step pipeline: research → script → fact-check → audio → RSS/git
  ├── music_gen.py    MusicGen (audiocraft) wrapper; numpy ambient-pad fallback when audiocraft absent
  └── clip_mixer.py   YouTube clip extraction via yt-dlp, interleaved into dialogue audio

telegram_bot.py       long-polling Telegram bot; spawns generate_podcast.py as a subprocess per message
```

### Pipeline steps in `generate_podcast.py`

1. **Research** (`_RESEARCH_MODEL` = Opus) — web_search tool, produces a fact-rich brief
2. **Dialogue script** (`_DIALOGUE_MODEL` = Sonnet) — Cedar/Marin conversation from the brief; speaker lines tagged `CEDAR [emotion]: text`
3. **Fact-check** (`_FACT_CHECK_MODEL` = Sonnet) — corrects inline; strips any corrections appendix it appends
4. **Audio** — per-turn TTS via OpenAI `gpt-4o-mini-tts` with per-line emotion instructions; ffmpeg concat; optional YouTube clips interleaved by `clip_mixer.py`; optional MusicGen intro/outro bookends; show intro ident prepended (cached at `assets/intro_ident.mp3`)
5. **RSS + git** — appends new `<item>` to `feed.xml`; `git add / commit / push` (skipped if `SKIP_GIT=1`)

### Audio assembly order

```
[intro_ident] → [music_intro] → [dialogue + clips] → [music_outro]
```

Music and ident are each optional/conditional; only present segments are concatenated.

### Config system

Priority (highest first): environment variables → `config.json` → `DEFAULTS` dict in `generate_podcast.py`.

Notable `config.json` / env overrides:
- `USE_MUSIC=false` — disables MusicGen
- `SKIP_GIT=1` — skips `git push`
- `TTS_PROVIDER` — `"openai"` (default) or `"elevenlabs"`
- `use_emotive_tts` — passes per-line emotion tags to `gpt-4o-mini-tts` as `instructions`; only works with that model

### clip_mixer.py

Claude (`_CUE_MODEL` = Sonnet) annotates the script with `<<<CLIP_CUE {...} CLIP_CUE>>>` blocks (2–4 cues). For each cue: `yt-dlp` searches YouTube, scores results by view count + channel size, downloads only the needed time segment, trims with ffmpeg. All clip URLs are validated against `_ALLOWED_VIDEO_HOSTS` before download.

### music_gen.py

Claude Haiku generates a 10-word MusicGen text prompt for the topic. `facebook/musicgen-small` runs on CUDA if available. Falls back to a numpy Cmaj7 ambient pad when audiocraft is absent. Outro uses 2× fade duration.

### Telegram bot

Single `asyncio.Lock` prevents concurrent generations. On failure, replies with the last 15 lines of `logs/latest.log`. Exponential-backoff restart loop (5s → 300s cap) on crashes.

## Work directory

Each run creates `episodes/<timestamp>_<topic>_work/` for intermediate files (turn MP3s, clip downloads, music). Cleanup (`shutil.rmtree`) is commented out until 2026-06-06 to preserve artifacts for debugging first-month runs.

## Dependencies

- **ffmpeg** must be on PATH (audio concat, WAV→MP3, clip trimming)
- **audiocraft** optional — if absent, music falls back to numpy; episode still generates
- **yt-dlp** required for clip insertion; clips are silently skipped on failure (`skip_failed=True`)
- **python-telegram-bot** only needed for `telegram_bot.py`
