# SendGrid Inbound Parse → Dialog Podcast — Setup Guide

End-to-end walkthrough: email arrives → SendGrid parses it → webhook fires → GitHub Actions generates episode → RSS feed updated.

---

## 1. SendGrid account & API key

1. Sign up at https://sendgrid.com (free tier is fine for low volume).
2. Go to **Settings → API Keys → Create API Key**.
3. Choose **Restricted Access**, enable **Mail Send** (if you also want to send confirmations) and **Inbound Parse → Read**.
4. Copy the key — you'll need it shortly as `SENDGRID_API_KEY`.

---

## 2. Authenticate your sending domain (required for Inbound Parse)

1. **Settings → Sender Authentication → Authenticate Your Domain**.
2. Enter your domain (e.g. `yourdomain.com`).
3. Add the CNAME records SendGrid gives you to your DNS provider.
4. Click **Verify**.

---

## 3. Configure Inbound Parse

### 3a. Add a subdomain MX record

In your DNS provider, add an MX record for a subdomain you'll use for podcast emails:

| Type | Host | Value | Priority |
|------|------|-------|----------|
| MX | `mail` | `mx.sendgrid.net` | 10 |

This routes all email to `anything@mail.yourdomain.com` to SendGrid.

> **Tip:** Use a dedicated subdomain (e.g. `mail`) rather than your root domain so your regular email is unaffected.

### 3b. Register the webhook in SendGrid

1. Go to **Settings → Inbound Parse → Add Host & URL**.
2. **Subdomain:** `mail` (or whatever you chose)
3. **Domain:** `yourdomain.com`
4. **Destination URL:** `https://your-server.example.com/webhook/email`
5. Leave **Check incoming emails for spam** checked if you like.
6. **Save**.

---

## 4. Send a test email

Send an email to `podcast@mail.yourdomain.com` with:
- **Subject:** `PODCAST: the history of the internet`
- **Body:** anything

SendGrid will POST the parsed fields to your webhook URL. The server responds 202 and fires the GitHub Actions workflow (or local subprocess if `GH_TOKEN` is not set).

---

## 5. Deploy `email_trigger.py`

### Option A — Fly.io

```bash
# Install flyctl: https://fly.io/docs/getting-started/installing-flyctl/
fly auth login
fly launch --no-deploy --name dialog-podcast-webhook
# Edit fly.toml if needed, then:
fly secrets set \
  WEBHOOK_SECRET="your-random-secret" \
  ALLOWED_SENDERS="you@yourdomain.com" \
  GH_TOKEN="ghp_..." \
  GITHUB_USER="your-github-username" \
  GITHUB_REPO="dialog-podcast"
fly deploy
```

Your webhook URL will be: `https://dialog-podcast-webhook.fly.dev/webhook/email`

### Option B — Railway

```bash
# Install: https://docs.railway.app/develop/cli
railway login
railway init           # in the C:\Dialog-podcast directory
railway up
```

Then in the Railway dashboard → **Variables**, add:

| Variable | Value |
|----------|-------|
| `WEBHOOK_SECRET` | your-random-secret |
| `ALLOWED_SENDERS` | you@yourdomain.com |
| `GH_TOKEN` | ghp_... |
| `GITHUB_USER` | your-github-username |
| `GITHUB_REPO` | dialog-podcast |
| `PORT` | 8080 |

Railway auto-detects `Procfile` (`web: python email_trigger.py`).

Your webhook URL will be the Railway-assigned domain, e.g.:  
`https://dialog-podcast-webhook.up.railway.app/webhook/email`

---

## 6. Required environment variables summary

| Variable | Where to set | Description |
|----------|-------------|-------------|
| `WEBHOOK_SECRET` | Platform secrets | Arbitrary random string; used to verify signed requests to `/webhook/prompt` |
| `ALLOWED_SENDERS` | Platform secrets | Comma-separated list of email addresses allowed to trigger episodes |
| `GH_TOKEN` | Platform secrets | GitHub personal access token with `repo` scope (to fire `repository_dispatch`) |
| `GITHUB_USER` | Platform secrets | Your GitHub username |
| `GITHUB_REPO` | Platform secrets | The repo name (e.g. `dialog-podcast`) |
| `PORT` | Platform env | HTTP port (Railway/Fly set this automatically) |

---

## 7. GitHub repo secrets (for the Actions workflow)

In your GitHub repo → **Settings → Secrets and variables → Actions**, add:

| Secret | Description |
|--------|-------------|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `OPENAI_API_KEY` | Your OpenAI API key (for TTS) |
| `ELEVENLABS_API_KEY` | Optional — only if using ElevenLabs TTS |

---

## 8. Enable GitHub Pages

1. In your GitHub repo → **Settings → Pages**.
2. **Source:** Deploy from a branch → `main` → `/ (root)`.
3. Save. GitHub will publish `index.html` and `feed.xml` at  
   `https://YOUR_USERNAME.github.io/dialog-podcast/`.

---

## 9. Full flow recap

```
you@yourdomain.com  →  podcast@mail.yourdomain.com
       ↓
   SendGrid Inbound Parse
       ↓
   POST /webhook/email  (your Fly/Railway server)
       ↓
   GitHub API: repository_dispatch  {topic: "..."}
       ↓
   GitHub Actions: generate_podcast.py
       ↓
   episodes/YYYYMMDD_topic.mp3  +  feed.xml  committed to repo
       ↓
   https://YOU.github.io/dialog-podcast/  (live RSS + landing page)
```

Poll generation progress:
```bash
curl https://your-server/webhook/status/latest
```
