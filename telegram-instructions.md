# Telegram-bot trigger — setup guide

End-to-end: you message a Telegram bot from your phone → the bot, running on your tower, spawns `generate_podcast.py` → episode lands in `episodes/`, RSS updates, optional `git push`. No internet exposure: the bot connects *outbound* to Telegram, so your tower never opens a port.

---

## 1. Create the bot (5 min)

1. On your phone, open Telegram and message **`@BotFather`** (it's a real, official bot).
2. Send `/newbot`.
3. Pick a **display name** (e.g. *Dialog Podcast Bot*) — this is what shows in chats.
4. Pick a **username** ending in `bot` (e.g. `dialog_podcast_andre_bot`). Must be globally unique.
5. BotFather replies with an **HTTP API token** that looks like `1234567890:AAExxxx...`. **This is your `TELEGRAM_BOT_TOKEN`.** Keep it secret — anyone with it can impersonate the bot.

Optional but recommended:
- `/setdescription` → "Generates Dialog podcast episodes from a topic prompt."
- `/setprivacy` → **Disable** (default is enabled, which restricts the bot from seeing non-command messages in groups; harmless for 1:1 chats but flip it for clarity).

---

## 2. Get your Telegram user ID (1 min)

1. Message **`@userinfobot`** on Telegram.
2. It replies with your numeric ID, e.g. `123456789`. **This is your `TELEGRAM_ALLOWED_USERS`.**
3. If multiple people should be able to trigger the bot, comma-separate (e.g. `123456789,987654321`).

The bot ignores messages from any sender not in this list. There is no other auth — the user-ID allowlist is the security boundary.

---

## 3. Install the library

```powershell
pip install python-telegram-bot
```

(The repo's `requirements.txt` already pins `python-telegram-bot>=21.0`, so `pip install -r requirements.txt` works too.)

---

## 4. Set environment variables

Add to your `.env` (or set in the system environment):

```
TELEGRAM_BOT_TOKEN=1234567890:AAE...your-token-from-step-1
TELEGRAM_ALLOWED_USERS=123456789
PODCAST_REPO_PATH=C:\Dialog-podcast
```

Plus the existing keys you already have:

```
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GH_TOKEN=ghp_...
GITHUB_USER=your-github-username
GITHUB_REPO=dialog-podcast
SKIP_GIT=1   # set to disable the git push during local testing
```

---

## 5. Sanity test

```powershell
python telegram_bot.py
```

You should see:

```
HH:MM:SS [INFO] __main__ — Bot polling started. Allowed users: [123456789]. Repo path: C:\Dialog-podcast
```

Open Telegram, find your bot by its `@username`, send `/start`. You should get a greeting back. Send a short topic like `"a brief test"` to confirm the round-trip works (it will start generation, which takes 15 min — interrupt with Ctrl-C if you don't want to wait).

---

## 6. Auto-start on Windows login (Task Scheduler)

This makes the bot start whenever you log in to Windows, so it's quietly running in the background and ready to receive your dog-walk topic ideas.

1. Press **Win+R**, type `taskschd.msc`, hit Enter.
2. **Action menu → Create Task...** (NOT "Create Basic Task" — we need the full options).
3. **General** tab:
   - **Name:** `Dialog Podcast Bot`
   - **Description:** `Long-polling Telegram bot that triggers podcast generation`
   - Check **Run only when user is logged on** (default).
   - Leave **Configure for** at *Windows 10/11*.
4. **Triggers** tab → **New...**:
   - **Begin the task:** `At log on`
   - **Specific user:** your account
   - **Delay task for:** `30 seconds` (lets network/services come up first)
   - OK.
5. **Actions** tab → **New...**:
   - **Action:** `Start a program`
   - **Program/script:** the full path to your Python — find it with `where python` in PowerShell. Typically:
     `C:\Users\<you>\AppData\Local\Programs\Python\Python312\python.exe`
   - **Add arguments:** `telegram_bot.py`
   - **Start in:** `C:\Dialog-podcast`
   - OK.
6. **Conditions** tab:
   - **UNCHECK** *Start the task only if the computer is on AC power* (otherwise it won't run on a laptop on battery).
7. **Settings** tab:
   - Check **Allow task to be run on demand**.
   - **If the task fails, restart every:** `1 minute`, attempt up to `3` times.
   - **If the running task does not end when requested, force it to stop**.
8. **OK** → enter your password if prompted.

Test it: right-click the task → **Run**. Open Task Manager → Details → look for `python.exe` running with command line `telegram_bot.py`. Send your bot a message — it should respond.

---

## 7. Where do logs go?

**Bot's own logs** (startup, allow/reject decisions, crashes):
- When run from a terminal: visible in that terminal.
- When run from Task Scheduler: not captured by default. Easiest fix — wrap with a redirect. Edit your Task Scheduler **Add arguments** field to:
  ```
  -c "import sys; sys.stdout = open(r'C:\Dialog-podcast\logs\bot.log', 'a', buffering=1, encoding='utf-8'); sys.stderr = sys.stdout; exec(open('telegram_bot.py', encoding='utf-8').read())"
  ```
  …or simpler: write a one-line `run_bot.bat` and have Task Scheduler run that:
  ```bat
  @echo off
  python C:\Dialog-podcast\telegram_bot.py >> C:\Dialog-podcast\logs\bot.log 2>&1
  ```

**Generation logs** (the actual episode generation): always written to `C:\Dialog-podcast\logs\latest.log` regardless of how the bot was started.

---

## 8. Stopping / restarting

- **Stop:** Task Manager → Details → right-click `python.exe` (the one running `telegram_bot.py`) → End task. Or `taskkill /IM python.exe` (kills *all* python processes — careful).
- **Restart:** Task Scheduler → right-click the task → **End**, then **Run**.
- **Disable temporarily:** Task Scheduler → right-click → **Disable**.

---

## 9. Full flow recap

```
you (phone, walking dog)
       ↓
   "the history of the internet"  →  Telegram
       ↓
   long-polling bot on your tower
       ↓
   subprocess: python generate_podcast.py "..."
       ↓ (~15 min, on your 4080)
   research → script → fact-check → TTS → music → MP3
       ↓
   feed.xml updated, optional git push to GitHub Pages
       ↓
   bot replies: "Done — check episodes/"
       ↓
   tomorrow's commute: hit play in your podcast app
```

---

## 10. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `RuntimeError: TELEGRAM_BOT_TOKEN is unset` | Env var not set in the shell or scheduled task. Double-check `.env` is loaded, or set it in Task Scheduler's environment via the wrapping `.bat`. |
| Bot ignores your messages silently | Your user ID isn't in `TELEGRAM_ALLOWED_USERS`. Check via `@userinfobot` again — IDs are numeric, no `@`. |
| `Conflict: terminated by other getUpdates request` | Two bot instances are running with the same token. Only one can poll at a time. Find and kill the duplicate. |
| Bot says "I'm already generating" | `_generation_lock` is held. If you suspect a stuck run, restart the bot — the lock is in-memory only. |
| Generation fails with `model not found: claude-sonnet-4-6` | Update the `anthropic` SDK: `pip install --upgrade anthropic`. |
| `model not found: gpt-4o-mini-tts` | Update the `openai` SDK: `pip install --upgrade openai`. |
