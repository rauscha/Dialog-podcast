# Telegram Command Center - Setup Guide

End to end: you message a Telegram bot from your phone, the bot running on your tower spawns `generate_podcast.py`, and the episode lands in `episodes/` with RSS updated. The bot connects outbound to Telegram, so your tower does not need to expose an inbound port.

## 1. Create The Bot

1. Open Telegram and message `@BotFather`.
2. Send `/newbot`.
3. Pick a display name, for example `Asynchronous Podcast Bot`.
4. Pick a username ending in `bot`.
5. BotFather replies with an HTTP API token. This is `TELEGRAM_BOT_TOKEN`; keep it secret.

Optional but recommended:

- `/setdescription` -> `Turns topic prompts into Asynchronous podcast episodes.`
- Keep BotFather privacy enabled unless you intentionally use group chats.

## 2. Get Your Telegram User ID

1. Message `@userinfobot`.
2. It replies with your numeric user ID, for example `123456789`.
3. Put that value in `TELEGRAM_ALLOWED_USERS`.

The bot ignores users not in this list. Group chats are rejected unless their numeric chat ID appears in `TELEGRAM_ALLOWED_CHATS`.

## 3. Install Dependencies

```powershell
pip install -r requirements.txt
```

## 4. Set Environment Variables

Add these to `.env`:

```text
TELEGRAM_BOT_TOKEN=1234567890:AAE...your-token-from-BotFather
TELEGRAM_ALLOWED_USERS=123456789
TELEGRAM_ALLOWED_CHATS=
PODCAST_REPO_PATH=C:\Dialog-podcast
GENERATION_TIMEOUT_SEC=7200

ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
ELEVENLABS_API_KEY=
SKIP_GIT=true
USE_CLIPS=false
USE_SONIC_FOOTNOTES=true
SONIC_FOOTNOTES_CATALOG=sonic_footnotes.json
EPISODE_TYPE=deep_dive
USE_GUEST_HOSTS=true
GUEST_HOST_MODE=auto
GUEST_HOST_MAX=1
GUEST_HOST_VOICE_POOL=ash,ballad,coral,sage,shimmer,echo,onyx,nova,alloy,fable
TTS_PROVIDER=openai
HOST_A_VOICE=marin
HOST_B_VOICE=cedar
ELEVENLABS_MODEL=eleven_turbo_v2
ELEVENLABS_STABILITY=0.5
ELEVENLABS_SIMILARITY_BOOST=0.75
ELEVENLABS_GUEST_VOICE_IDS=
TTS_DEFAULT_ROUTE={}
TTS_ROUTES={}
TTS_REQUEST_TIMEOUT_SEC=180
TTS_COMMAND=
TTS_COMMAND_CWD=
TTS_COMMAND_TIMEOUT_SEC=600
TURN_SILENCE_MS=180
USE_AUDIO_MASTERING=true
AUDIO_BITRATE=192k
AUDIO_SAMPLE_RATE=44100
AUDIO_CHANNELS=2
AUDIO_LOUDNESS_I=-16.0
AUDIO_TRUE_PEAK=-1.5
AUDIO_LRA=11.0
AUDIO_HIGHPASS_HZ=60
AUDIO_LOWPASS_HZ=18000
MUSIC_PROMPT_MODEL=claude-haiku-4-5-20251001
SCRIPT_QUALITY_PIPELINE=true
HOST_MEMORY_PATH=host_memory.json
USE_PERSONAL_CONTEXT=true
PERSONAL_CONTEXT_PATH=personal_context.json
PERSONAL_CONTEXT_MAX_TOPICS=24
PERSONAL_CONTEXT_SIMILARITY_THRESHOLD=0.34
PERSONAL_CONTEXT_SYNC_MANIFESTS=true
RESEARCH_MODEL=claude-opus-4-5
DIALOGUE_MODEL=claude-sonnet-4-6
FACT_CHECK_MODEL=claude-sonnet-4-6
LOCAL_LLM_PROVIDER=ollama
LOCAL_LLM_BASE_URL=http://127.0.0.1:11434
LOCAL_LLM_API_KEY_ENV=LOCAL_LLM_API_KEY
LOCAL_LLM_TIMEOUT_SEC=3600
LOCAL_LLM_NUM_CTX=32768
LOCAL_LLM_KEEP_ALIVE=30m
LOCAL_LLM_THINK=false
LEARNING_PATH_DIR=learning_paths
LEARNING_PATH_DEFAULT_EPISODES=5
LEARNING_PATH_DEFAULT_LEVEL=beginner-to-intermediate
```

`USE_CLIPS=false` is the safer default for published runs. Turn clips on only for private experiments or rights-cleared sources.

TTS can be mixed per speaker in `config.json` or with JSON env vars. For example, set `TTS_ROUTES={"JUNO":{"provider":"openai","voice":"marin"},"CASPAR":{"provider":"elevenlabs","voice_id":"..."}}` to keep Juno on OpenAI while Caspar uses ElevenLabs. Telegram commands use whatever routes are active when the generation starts.

## 5. Load `.env` In PowerShell

```powershell
Get-Content .env | ForEach-Object {
  if ($_ -notmatch '^#' -and $_ -match '=') {
    $k,$v = $_ -split '=',2
    [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim())
  }
}
```

## 6. Run The Bot

```powershell
python telegram_bot.py
```

Expected log:

```text
HH:MM:SS [INFO] __main__ - Bot polling started. Allowed users: [123456789]. Allowed chats: []. Repo: C:\Dialog-podcast
```

Open Telegram, find your bot, and send `/start`.

## 7. Commands

```text
/generate <topic>  Start a new episode generation
/gen <topic>       Short alias for /generate
/generate --type how_to <topic>
/generate landscape: <topic>
/generate --guest <topic>
/generate --no-guest <topic>
/generate --guest-mode force <topic>
/series <topic> 5 episodes beginner-to-intermediate
/series --plan-only <topic>
/queue <topic>     Add a topic to the in-memory queue
/queue             Show queued topics
/types             Show available episode formats
/next              Run the next queued topic
/status            Show active subprocess, lock, log, and latest manifest
/latest            Show the most recent episode manifest
/paths             Show the latest learning path
/context           Show personal context and covered topics
/remember domain <text>
/remember background <text>
/remember depth <text>
/tts               Show active TTS routing config
/cancel            Stop the active generation process
/doctor            Check env vars, tools, config, and lock state
```

Plain text no longer starts expensive work. It replies with a hint to use `/generate` or `/queue`.

Available episode types:

```text
deep_dive, overview, how_to, landscape, case_study, myth_bust,
story, debate, history, field_guide, decision_brief, critique,
future_scenario, lab_notes, complete_fiction, review
```

## 8. Metadata And Logs

Each generation writes:

```text
episodes/<timestamp>_<topic>_work/episode_manifest.json
episodes/<timestamp>_<topic>_work/research_brief.md
episodes/<timestamp>_<topic>_work/source_cards.json
episodes/<timestamp>_<topic>_work/guest_plan.json
episodes/<timestamp>_<topic>_work/beat_sheet.md
episodes/<timestamp>_<topic>_work/personal_context_snapshot.json
episodes/<timestamp>_<topic>_work/personal_context_update.json
episodes/<timestamp>_<topic>_work/sonic_footnote_plan.json
episodes/<timestamp>_<topic>_work/draft_script.txt
episodes/<timestamp>_<topic>_work/natural_script.txt
episodes/<timestamp>_<topic>_work/fact_checked_script.txt
episodes/<timestamp>_<topic>_work/script.txt
episodes/<timestamp>_<topic>.chapters.json
episodes/<timestamp>_<topic>.companion.json
logs/<timestamp>_<topic>.log
logs/latest.log
```

Learning path mode writes:

```text
learning_paths/<path_id>_<topic>/learning_path.json
learning_paths/<path_id>_<topic>/learning_path.md
learning_paths/latest_learning_path.json
```

Unless `/series --plan-only ...` is used, the planned episodes are added to the in-memory queue and can be generated one at a time with `/next`.

The manifest tracks run ID, topic, status, current stage, config options, models, script pass artifacts, guest expert decisions, personal-context snapshots, sonic footnote decisions, audio mastering settings, sources, claims, clip credits, audio duration, output paths, publish URLs, warnings, and errors. Telegram `/status` and `/latest` read this manifest instead of guessing from logs.

`index.html` reads `feed.xml` plus each episode companion JSON to show a webplayer, clickable chapters, and follow-up links on the GitHub Pages companion site.

Guest expert mode can add a synthetic/composite interview guest with a distinct TTS voice when the topic benefits from outside authority. Use `--guest` to force one, `--no-guest` to suppress one, or leave `GUEST_HOST_MODE=auto` for the producer pass to decide. Guest personas are not real people or voice impersonations.

`sonic_footnotes.json` is a rights-aware open-source sound catalog. The script pipeline can propose tiny sonic flourishes from it, but remote items still need specific-file/license verification before any future mixer inserts audio.

`personal_context.json` is your local private listener profile. Use `/remember background ...`, `/remember domain ...`, `/remember depth ...`, `/remember goal ...`, `/remember style ...`, and `/remember avoid ...` to teach the bot what to assume about you. The generator also records covered topics there, so repeated topics are treated as deeper follow-ups instead of fresh primers.

`host_memory.json` is the persistent character bible for Juno and Caspar. The generator snapshots it into each work directory, then appends small callback-worthy memories after a successful script pass.

## 9. Auto-Start On Windows Login

Use Task Scheduler:

1. Open `taskschd.msc`.
2. Create Task.
3. General:
   - Name: `Asynchronous Podcast Bot`
   - Run only when user is logged on.
4. Triggers:
   - At log on.
   - Delay task for 30 seconds.
5. Actions:
   - Program/script: full path to `python.exe`.
   - Add arguments: `telegram_bot.py`.
   - Start in: `C:\Dialog-podcast`.
6. Settings:
   - Allow task to be run on demand.
   - Restart on failure.

The included `watchdog.ps1` can also restart the bot if the process disappears.

## 10. Safety Notes

- `/generate` is required for new work; accidental plain text does not launch a run.
- A cross-process lock at `.runtime/generation.lock` prevents overlapping CLI and Telegram runs.
- Use private chats by default. Add explicit group IDs to `TELEGRAM_ALLOWED_CHATS` only when you want group control.
- Use `SKIP_GIT=true` while testing locally.

## 11. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `RuntimeError: TELEGRAM_BOT_TOKEN is unset` | Env var is not loaded in the shell or scheduled task. |
| Bot ignores messages | Your numeric ID is not in `TELEGRAM_ALLOWED_USERS`, or the group is not in `TELEGRAM_ALLOWED_CHATS`. |
| `Conflict: terminated by other getUpdates request` | Two bot instances are running with the same token. |
| Bot says a generation is already running | Check `/status`; use `/cancel` only if you intend to stop it. |
| `/doctor` says ffmpeg or ffprobe is missing | Install ffmpeg and make sure it is on PATH for the bot process. |
| `model not found: claude-sonnet-4-6` | Update the Anthropic SDK. |
| `model not found: gpt-4o-mini-tts` | Update the OpenAI SDK. |
