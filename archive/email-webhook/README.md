# Archived: SendGrid email-trigger path

These files implement the original email→webhook→GitHub-Actions flow. They've been moved here because the active trigger path is now a Telegram bot (`telegram_bot.py` at the repo root), which fits the user's actual workflow better and avoids exposing the tower to the internet.

## What's here

- `email_trigger.py` — Flask webhook server. Handles `/webhook/email` (SendGrid Inbound Parse), `/webhook/prompt` (HMAC-signed JSON POST), `/health`, `/status`, `/logs`, `/webhook/status/<run_id>`. Phase-1 hardening already applied: fail-closed `WEBHOOK_SECRET` check, `hmac.compare_digest` for the plaintext path, deny-all on empty `ALLOWED_SENDERS`, `PODCAST:` prefix required, 500-char topic cap.
- `Procfile` — `web: python email_trigger.py` for Heroku/Railway-style deploys.
- `fly.toml` — Fly.io deploy config (256 MB shared CPU, port 8080).
- `SENDGRID_SETUP.md` — full domain-auth, MX-record, Inbound-Parse setup walkthrough.

## Why archived, not deleted

You may want to revive this path if you ever:
- Want to trigger episodes from a system that can email but can't reach Telegram.
- Set up the bot to email a stakeholder a confirmation/preview before publishing (the audit's Phase-4 "approval mode" feature could reuse the SendGrid send-mail half).
- Move generation off your tower (e.g., to a cloud GPU host) and want HTTP triggering again.

## How to revive

1. Move all four files back to the repo root: `git mv archive/email-webhook/* .` then move `README.md` out of the way.
2. Make sure `flask>=3.0.0` is uncommented in `requirements.txt` and run `pip install -r requirements.txt`.
3. Decide whether you also want the SendGrid path or just `/webhook/prompt`. If SendGrid: follow `SENDGRID_SETUP.md` from step 1.
4. If exposing to the internet: replace `app.run()` with `waitress` (`pip install waitress`; `from waitress import serve; serve(app, host="0.0.0.0", port=port)`). The dev server isn't safe for hostile traffic.
5. Decide whether you still want the Telegram bot running in parallel — running both simultaneously is fine, but the audit's "concurrent runs clobber each other" concern applies (latest.log gets truncated, work-dirs can collide). Add coordination if you do.

## Open issues from the audit (not fixed before archiving)

- `/status` and `/logs` are unauthenticated — anyone hitting the URL gets the run log. Add auth or remove these routes when reviving.
- `/webhook/email` does not verify the SendGrid signature; the `from` field is spoofable. Add signature verification (SendGrid signs the request when "Signed Webhooks" is enabled).
- The dev Flask server in `Procfile` is not production-safe; switch to `waitress` (Windows-friendly) or `gunicorn` (Linux/Mac) before exposing publicly.
- No rate limiting; one attacker who finds the URL could drain Anthropic + OpenAI credits. Add `flask-limiter` or set spend caps in both consoles before exposing.
