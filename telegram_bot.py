#!/usr/bin/env python3
"""telegram_bot.py — Long-polling Telegram bot that triggers Dialog episode generation.

Usage: set TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_USERS env vars, then run
`python telegram_bot.py`. Bot connects outbound to Telegram's servers — no
inbound port exposure required. See telegram-instructions.md for setup.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────

TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ALLOWED_USERS: set = {
    int(s.strip())
    for s in os.environ.get("TELEGRAM_ALLOWED_USERS", "").split(",")
    if s.strip().lstrip("-").isdigit()
}
PODCAST_REPO_PATH: str = os.environ.get(
    "PODCAST_REPO_PATH", str(Path(__file__).parent)
)

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError(
        "TELEGRAM_BOT_TOKEN is unset. Get one from @BotFather on Telegram."
    )
if not ALLOWED_USERS:
    raise RuntimeError(
        "TELEGRAM_ALLOWED_USERS is unset. Set to your numeric Telegram user ID "
        "(comma-separated for multiple). Find your ID via @userinfobot."
    )

MAX_TOPIC_LEN = 500

# Single generation in flight at a time — matches the "concurrent runs clobber
# each other" finding from the audit.
_generation_lock = asyncio.Lock()


# ── Auth ───────────────────────────────────────────────────────────────────────

def _is_allowed(user_id: int | None) -> bool:
    return user_id is not None and user_id in ALLOWED_USERS


# ── Handlers ───────────────────────────────────────────────────────────────────

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id if update.effective_user else None
    if not _is_allowed(user_id):
        logger.warning(f"/start from non-allowlisted user {user_id}")
        return
    await update.message.reply_text(
        "Send me a topic and I'll generate a Dialog episode about it.\n"
        "Example: \"the history of the internet\"\n"
        "Generation takes ~15 minutes; I'll ping you when it's done."
    )


async def handle_topic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id if update.effective_user else None
    if not _is_allowed(user_id):
        logger.warning(f"Rejected message from non-allowlisted user {user_id}")
        return

    topic = (update.message.text or "").strip()
    if not topic:
        await update.message.reply_text("Empty message — send a topic.")
        return
    if len(topic) > MAX_TOPIC_LEN:
        await update.message.reply_text(
            f"Topic too long ({len(topic)} chars; max {MAX_TOPIC_LEN})."
        )
        return

    if _generation_lock.locked():
        await update.message.reply_text(
            "I'm already generating an episode. Try again in ~15 minutes."
        )
        return

    async with _generation_lock:
        await update.message.reply_text(
            f"Generating: {topic!r}\nETA ~15 minutes. I'll reply when it's done."
        )

        log_dir = Path(PODCAST_REPO_PATH) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "latest.log"

        try:
            with open(log_file, "w", encoding="utf-8") as log_fh:
                proc = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "generate_podcast.py",
                    topic,
                    "--repo",
                    PODCAST_REPO_PATH,
                    cwd=Path(__file__).parent,
                    stdout=log_fh,
                    stderr=log_fh,
                    env=os.environ.copy(),
                )
                returncode = await proc.wait()

            if returncode == 0:
                await update.message.reply_text(
                    f"Done — episode generated for: {topic!r}\n"
                    "Check the episodes/ folder or the RSS feed."
                )
            else:
                tail = log_file.read_text(encoding="utf-8").splitlines()[-15:]
                joined = "\n".join(tail)[-3000:]  # Telegram message limit ~4096
                await update.message.reply_text(
                    f"Generation failed (exit {returncode}). Last log lines:\n\n{joined}"
                )
        except Exception as exc:
            logger.exception("Generation crashed")
            await update.message.reply_text(f"Crashed: {exc!r}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", start_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_topic))

    logger.info(
        f"Bot polling started. Allowed users: {sorted(ALLOWED_USERS)}. "
        f"Repo path: {PODCAST_REPO_PATH}"
    )
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
