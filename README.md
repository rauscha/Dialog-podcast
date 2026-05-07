# Dialog

An AI-powered podcast in the style of Radiolab. Two hosts — Cedar and Marin — explore ideas at the intersection of art, science, and wonder. Each episode is generated from a single topic prompt: researched with live web search, written as a natural conversation, fact-checked, narrated in two voices, wrapped in generative theme music, and published to an RSS feed.

---

## The hosts

**Cedar** — Artistic, broad-thinking, asks "what does this *mean* for us?" She finds unexpected metaphors, goes on tangents that turn out to be profound, and speaks with warmth and wonder. She composed the show's theme music.

**Marin** — Scientifically grounded, methodical, slightly older and more skeptical. He's the "well, actually..." voice — but with dry wit and genuine curiosity, never pedantry. He names researchers, cites data, and keeps Cedar's flights of fancy anchored in evidence.

---

## Requirements

- **Python 3.10+**
- **ffmpeg** (must be on PATH — used for audio concatenation and format conversion)
- **CUDA GPU recommended** for MusicGen (works on CPU but is slow); tested on NVIDIA RTX 4080 16 GB
- API keys: Anthropic (required), OpenAI (required for TTS), optionally ElevenLabs

### Python dependencies

```bash
pip install -r requirements.txt
```

> **Note on audiocraft:** Meta's audiocraft package may require a separate install step and a matching PyTorch version. See https://github.com/facebookresearch/audiocraft for platform-specific instructions. If audiocraft is not installed, music generation is skipped gracefully and episodes are produced without intro/outro music.

---

## Setup

1. **Clone / copy** this directory to your machine.

2. **Copy `.env.example` to `.env`** and fill in your keys:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   OPENAI_API_KEY=sk-...
   ```

3. **Edit `config.json`** — at minimum set `github_user` and `github_repo` if you want RSS publishing. Set `SKIP_GIT=1` in your `.env` to skip git push during development.

4. **Install ffmpeg** if not already present:
   - Windows: `winget install ffmpeg` or download from https://ffmpeg.org/download.html
   - macOS: `brew install ffmpeg`
   - Linux: `apt install ffmpeg`

5. **Load environment variables** before running:
   ```bash
   # Linux/macOS
   export $(grep -v '^#' .env | xargs)

   # Windows PowerShell
   Get-Content .env | ForEach-Object { if ($_ -notmatch '^#') { $k,$v = $_ -split '=',2; [Environment]::SetEnvironmentVariable($k,$v) } }
   ```

---

## Generating an episode

```bash
python generate_podcast.py "the science of sleep and memory consolidation"
```

Or interactively:
```bash
python generate_podcast.py
# Enter podcast topic: the science of sleep and memory consolidation
```

The pipeline runs five steps and prints progress:
```
[1/5] Researching topic...
[2/5] Writing Cedar/Marin dialogue script...
[3/5] Fact-checking script...
[4/5] Generating audio...
[5/5] Updating RSS feed...
Done!  Episode: '...'  (2150 words, audio: 20260506_120000_the_science_of_sleep.mp3)
```

Output files land in `episodes/`.

---

## Triggering via webhook

Start the Flask server:
```bash
python email_trigger.py
```

### Direct POST
```bash
curl -X POST http://localhost:5001/webhook/prompt \
  -H "Content-Type: application/json" \
  -d '{"topic": "dark matter and the large-scale structure of the universe", "secret": "your-webhook-secret"}'
```

### Email webhook (Mailgun / SendGrid inbound parse)
Configure your email provider to POST inbound mail to `http://your-server:5001/webhook/email`. Emails from addresses in `ALLOWED_SENDERS` whose subject starts with `PODCAST:` will trigger generation:
```
Subject: PODCAST: the Cambrian explosion
```

### Monitoring
```
GET /status       — last 40 lines of the current generation log
GET /logs         — last 100 lines
GET /health       — {"status": "ok"}
```

---

## Configuration reference

| Key | Default | Description |
|-----|---------|-------------|
| `podcast_title` | `"Dialog"` | RSS feed title |
| `podcast_description` | … | RSS feed description |
| `podcast_author` | `"Cedar & Marin"` | iTunes author field |
| `podcast_email` | `"you@example.com"` | iTunes owner email |
| `podcast_language` | `"en"` | RSS language tag |
| `podcast_category` | `"Science"` | iTunes category |
| `github_user` | `""` | GitHub username for RSS hosting |
| `github_repo` | `"dialog-podcast"` | GitHub repo name |
| `github_branch` | `"main"` | Branch to push to |
| `tts_provider` | `"openai"` | `"openai"` or `"elevenlabs"` |
| `host_a_name` | `"Cedar"` | Display name for host A |
| `host_a_voice` | `"cedar"` | OpenAI TTS voice ID for host A |
| `host_a_role` | `"artistic"` | Informational label |
| `host_b_name` | `"Marin"` | Display name for host B |
| `host_b_voice` | `"marin"` | OpenAI TTS voice ID for host B |
| `host_b_role` | `"scientific"` | Informational label |
| `elevenlabs_voice_id_a` | `""` | ElevenLabs voice ID for host A |
| `elevenlabs_voice_id_b` | `""` | ElevenLabs voice ID for host B |
| `target_minutes` | `15` | Target episode length (script will end naturally if content runs short) |
| `output_dir` | `"episodes"` | Directory for output MP3s |
| `use_clips` | `true` | Insert YouTube audio clips when relevant |
| `use_music` | `true` | Generate intro/outro music via MusicGen |
| `music_model` | `"facebook/musicgen-small"` | MusicGen model name |
| `music_duration_sec` | `12` | Length of intro/outro music clip |
| `music_fade_sec` | `2` | Fade duration in seconds (outro uses 2×) |

All keys can be overridden by environment variables (see `.env.example`).

---

## Architecture

```
generate_podcast.py   — orchestrator: research → script → TTS → music → RSS
  ├── music_gen.py    — MusicGen wrapper; generates Cedar's theme music
  └── clip_mixer.py  — YouTube clip extraction and audio assembly

email_trigger.py      — Flask webhook server (email + direct POST)
```
