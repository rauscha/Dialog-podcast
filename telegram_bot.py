#!/usr/bin/env python3
"""Telegram command center for Asynchronous episode generation."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import shlex
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from episode_manifest import EpisodeManifest, find_latest_manifest, slugify_topic
from episode_types import (
    episode_type_help,
    episode_type_label,
    normalize_episode_type,
    parse_episode_type_and_topic,
)
from job_control import cancel_active_job, get_status
from personal_context import (
    format_personal_context_summary,
    load_personal_context,
    remember_personal_context,
    save_personal_context,
)
from secret_env import load_secret_env

_LOG_DIR = Path(__file__).parent / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)


def _build_file_handler() -> logging.Handler:
    """Prefer bot.log, but do not crash if another process has it locked."""
    try:
        return logging.FileHandler(_LOG_DIR / "bot.log", encoding="utf-8")
    except OSError:
        fallback = _LOG_DIR / f"bot_{os.getpid()}.log"
        return logging.FileHandler(fallback, encoding="utf-8")


_FILE_HANDLER = _build_file_handler()
_FILE_HANDLER.setFormatter(
    logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%H:%M:%S",
    )
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%H:%M:%S",
    handlers=[_FILE_HANDLER, logging.StreamHandler()],
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.INFO)


load_secret_env(Path(__file__).parent)


def _parse_int_set(env_name: str) -> set[int]:
    values: set[int] = set()
    for item in os.environ.get(env_name, "").split(","):
        item = item.strip()
        if item.lstrip("-").isdigit():
            values.add(int(item))
    return values


def _parse_int_env(env_name: str, default: int) -> int:
    raw = os.environ.get(env_name, "")
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("%s=%r is invalid; using %s", env_name, raw, default)
        return default


TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ALLOWED_USERS = _parse_int_set("TELEGRAM_ALLOWED_USERS")
ALLOWED_CHATS = _parse_int_set("TELEGRAM_ALLOWED_CHATS")
GUEST_USERS = _parse_int_set("TELEGRAM_GUEST_USERS") - ALLOWED_USERS
OWNER_USER_ID = _parse_int_env("TELEGRAM_OWNER_USER_ID", 0) or (
    min(ALLOWED_USERS) if ALLOWED_USERS else 0
)
PODCAST_REPO_PATH = os.environ.get("PODCAST_REPO_PATH", str(Path(__file__).parent))
MAX_TOPIC_LEN = _parse_int_env("MAX_TOPIC_LEN", 500)
GENERATION_TIMEOUT_SEC = _parse_int_env("GENERATION_TIMEOUT_SEC", 7200)
MAX_PENDING_PER_GUEST = _parse_int_env("MAX_PENDING_PER_GUEST", 3)

_generation_lock = asyncio.Lock()
_queue: list[dict[str, str]] = []
_active_proc: asyncio.subprocess.Process | None = None
_active_topic: str | None = None
_active_episode_type: str | None = None
_active_started_at: datetime | None = None
_active_log: Path | None = None

# In-memory pending guest approvals. Lost on bot restart, which is acceptable
# given low volume — owner can ask the guest to resubmit if it matters.
_pending_approvals: dict[str, dict[str, Any]] = {}
_next_approval_id = 0


def _repo_root() -> Path:
    return Path(PODCAST_REPO_PATH).expanduser().resolve()


def _read_repo_config(repo_root: Path) -> dict[str, Any]:
    cfg_path = repo_root / "config.json"
    if not cfg_path.exists():
        return {}
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _read_output_dir(repo_root: Path) -> str:
    data = _read_repo_config(repo_root)
    return str(data.get("output_dir") or "episodes")


def _read_default_episode_type(repo_root: Path) -> str:
    data = _read_repo_config(repo_root)
    try:
        return normalize_episode_type(str(data.get("episode_type") or ""))
    except ValueError:
        return normalize_episode_type(None)


def _read_learning_path_defaults(repo_root: Path) -> tuple[int, str, str]:
    defaults = (5, "beginner-to-intermediate", "learning_paths")
    data = _read_repo_config(repo_root)
    try:
        count = int(data.get("learning_path_default_episodes") or defaults[0])
    except (TypeError, ValueError):
        count = defaults[0]
    level = str(data.get("learning_path_default_level") or defaults[1])
    output_dir = str(data.get("learning_path_dir") or defaults[2])
    return max(3, min(8, count)), level, output_dir


def _latest_learning_path(repo_root: Path) -> dict[str, Any] | None:
    _count, _level, output_dir = _read_learning_path_defaults(repo_root)
    latest = repo_root / output_dir / "latest_learning_path.json"
    if not latest.exists():
        return None
    try:
        data = json.loads(latest.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _latest_manifest(repo_root: Path) -> EpisodeManifest | None:
    return find_latest_manifest(repo_root, _read_output_dir(repo_root))


def _is_authorized(update: Update) -> bool:
    user_id = update.effective_user.id if update.effective_user else None
    if user_id not in ALLOWED_USERS:
        logger.warning("Rejected update from non-allowlisted user %s", user_id)
        return False

    chat = update.effective_chat
    if chat and chat.type != "private" and chat.id not in ALLOWED_CHATS:
        logger.warning(
            "Rejected update from chat %s; set TELEGRAM_ALLOWED_CHATS to allow groups",
            chat.id,
        )
        return False
    return True


def _is_guest(update: Update) -> bool:
    """True if this user can request episodes (with owner approval) but is not an owner."""
    user_id = update.effective_user.id if update.effective_user else None
    if user_id is None or user_id in ALLOWED_USERS or user_id not in GUEST_USERS:
        return False
    chat = update.effective_chat
    if chat and chat.type != "private":
        # Guests only via private DMs — no group surface.
        return False
    return True


def _is_known(update: Update) -> bool:
    """True if user is either an owner or a guest. Used for help/info-only commands."""
    return _is_authorized(update) or _is_guest(update)


def _describe_user(update: Update) -> str:
    """Human-readable label for the requesting user, for owner-facing messages."""
    user = update.effective_user
    if not user:
        return "(unknown user)"
    parts: list[str] = []
    name = (user.full_name or "").strip()
    if name:
        parts.append(name)
    if user.username:
        parts.append(f"@{user.username}")
    parts.append(f"id={user.id}")
    return " ".join(parts)


async def _reply(update: Update, text: str) -> None:
    if update.message:
        await update.message.reply_text(text[:3900])
    elif update.callback_query and update.callback_query.message:
        await update.callback_query.message.reply_text(text[:3900])


def _topic_from_args(context: ContextTypes.DEFAULT_TYPE) -> str:
    return " ".join(context.args or []).strip()


def _parse_generation_args(context: ContextTypes.DEFAULT_TYPE) -> tuple[str, str, str | None]:
    default_type = _read_default_episode_type(_repo_root())
    guest_mode: str | None = None
    filtered: list[str] = []
    args = list(context.args or [])
    i = 0
    while i < len(args):
        token = args[i]
        lower = token.lower()
        if lower in {"--guest", "--with-guest"}:
            guest_mode = "force"
        elif lower in {"--no-guest", "--without-guest"}:
            guest_mode = "off"
        elif lower == "--guest-mode":
            if i + 1 >= len(args):
                raise ValueError("Usage: --guest-mode auto|force|off")
            candidate = args[i + 1].lower()
            if candidate not in {"auto", "force", "off"}:
                raise ValueError("Guest mode must be auto, force, or off.")
            guest_mode = candidate
            i += 1
        elif lower.startswith("--guest-mode="):
            candidate = lower.split("=", 1)[1]
            if candidate not in {"auto", "force", "off"}:
                raise ValueError("Guest mode must be auto, force, or off.")
            guest_mode = candidate
        else:
            filtered.append(token)
        i += 1
    episode_type, topic = parse_episode_type_and_topic(" ".join(filtered).strip(), default=default_type)
    return episode_type, topic, guest_mode


def _format_elapsed(started_at: datetime | None) -> str:
    if started_at is None:
        return "unknown"
    elapsed = datetime.now() - started_at
    total = int(elapsed.total_seconds())
    minutes, seconds = divmod(max(0, total), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _format_duration(seconds: Any) -> str:
    if seconds is None:
        return "unknown"
    try:
        total = int(round(float(seconds)))
    except (TypeError, ValueError):
        return "unknown"
    minutes, sec = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{sec:02d}"
    return f"{minutes}:{sec:02d}"


def _format_manifest_summary(manifest: EpisodeManifest | None) -> str:
    if manifest is None:
        return "No episode manifest found yet."

    summary = manifest.to_summary()
    lines = [
        f"Topic: {summary.get('topic')}",
        f"Status: {summary.get('status')} / {summary.get('stage')}",
        f"Updated: {summary.get('updated_at')}",
    ]
    if summary.get("title") and summary.get("title") != summary.get("topic"):
        lines.insert(0, f"Title: {summary['title']}")
    if summary.get("episode_type_label"):
        lines.insert(1, f"Type: {summary['episode_type_label']}")
    if summary.get("word_count"):
        lines.append(f"Script: {summary['word_count']} words")
    if summary.get("guest_count"):
        lines.append(f"Guests: {summary['guest_count']}")
    if summary.get("source_count") is not None:
        lines.append(f"Sources: {summary['source_count']}")
    if summary.get("duration_sec") is not None:
        lines.append(f"Duration: {_format_duration(summary['duration_sec'])}")
    if summary.get("audio_path"):
        lines.append(f"Audio: {summary['audio_path']}")
    lines.append(f"Manifest: {manifest.path}")
    if summary.get("warnings"):
        lines.append(f"Warnings: {summary['warnings']}")
    if summary.get("errors"):
        lines.append(f"Errors: {summary['errors']}")
    return "\n".join(lines)


def _personal_context_cfg(repo_root: Path) -> dict[str, Any]:
    cfg = {
        "personal_context_path": "personal_context.json",
        "personal_context_max_topics": 24,
        "personal_context_similarity_threshold": 0.34,
        "personal_context_sync_manifests": True,
        "use_personal_context": True,
    }
    cfg.update(
        {
            key: value
            for key, value in _read_repo_config(repo_root).items()
            if key in cfg
        }
    )
    return cfg


def _json_object_value(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _tts_config(repo_root: Path) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "tts_provider": "openai",
        "tts_model": "gpt-4o-mini-tts",
        "host_a_voice": "cedar",
        "host_b_voice": "marin",
        "elevenlabs_voice_id_a": "",
        "elevenlabs_voice_id_b": "",
        "elevenlabs_guest_voice_ids": "",
        "elevenlabs_model": "eleven_turbo_v2",
        "tts_default_route": {},
        "tts_routes": {},
        "tts_command": "",
    }
    cfg = dict(defaults)
    repo_cfg = _read_repo_config(repo_root)
    cfg.update({key: repo_cfg[key] for key in defaults if key in repo_cfg})
    for key in defaults:
        env_value = os.environ.get(key.upper())
        if env_value is not None:
            cfg[key] = env_value
    cfg["tts_provider"] = str(cfg.get("tts_provider") or "openai").lower()
    cfg["tts_default_route"] = _json_object_value(cfg.get("tts_default_route"))
    cfg["tts_routes"] = _json_object_value(cfg.get("tts_routes"))
    return cfg


def _public_tts_route_for_bot(route: dict[str, Any]) -> dict[str, Any]:
    public = {
        key: value
        for key, value in route.items()
        if key not in {"api_key", "headers", "command"} and not key.endswith("_env")
    }
    if public.get("provider") == "elevenlabs" and public.get("voice_id"):
        voice_id = str(public["voice_id"])
        public["voice_id"] = f"{voice_id[:4]}...{voice_id[-4:]}" if len(voice_id) > 10 else "set"
    return public


def _format_tts_summary(repo_root: Path) -> str:
    cfg = _tts_config(repo_root)
    routes = cfg.get("tts_routes") if isinstance(cfg.get("tts_routes"), dict) else {}
    default_route = (
        cfg.get("tts_default_route") if isinstance(cfg.get("tts_default_route"), dict) else {}
    )
    providers = {str(cfg.get("tts_provider") or "openai").lower()}
    if default_route.get("provider"):
        providers.add(str(default_route["provider"]).lower())
    for route in routes.values():
        if isinstance(route, dict) and route.get("provider"):
            providers.add(str(route["provider"]).lower())

    lines = [
        "TTS routing:",
        f"Fallback provider: {cfg['tts_provider']}",
        f"Juno fallback voice: {cfg.get('host_a_voice')}",
        f"Caspar fallback voice: {cfg.get('host_b_voice')}",
        f"OpenAI key: {'set' if os.environ.get('OPENAI_API_KEY') else 'missing'}",
        f"ElevenLabs key: {'set' if os.environ.get('ELEVENLABS_API_KEY') else 'missing'}",
        f"Providers referenced: {', '.join(sorted(providers))}",
    ]
    if default_route:
        lines.append(
            "Default route: "
            + json.dumps(_public_tts_route_for_bot(default_route), sort_keys=True)
        )
    if routes:
        lines.append("Speaker routes:")
        for label, route in routes.items():
            if isinstance(route, dict):
                public = _public_tts_route_for_bot(route)
                lines.append(f"{label}: {json.dumps(public, sort_keys=True)}")
    else:
        lines.append("Speaker routes: none; using fallback provider and host voices.")
    if "command" in providers:
        lines.append("Command TTS: configured" if cfg.get("tts_command") else "Command TTS: missing command")
    return "\n".join(lines)


def _tail(path: Path, lines: int = 15, max_chars: int = 2800) -> str:
    if not path.exists():
        return "(log file not found)"
    tail = path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
    return "\n".join(tail)[-max_chars:] or "(log file is empty)"


def _validate_topic(topic: str) -> str | None:
    if not topic:
        return "Usage: /generate <topic>"
    if len(topic) > MAX_TOPIC_LEN:
        return f"Topic too long ({len(topic)} chars; max {MAX_TOPIC_LEN})."
    return None


def _parse_series_args(raw: str, repo_root: Path) -> tuple[str, int, str, bool]:
    default_count, default_level, _output_dir = _read_learning_path_defaults(repo_root)
    count = default_count
    level = default_level
    plan_only = False

    try:
        tokens = shlex.split(raw)
    except ValueError:
        tokens = raw.split()

    remaining: list[str] = []
    idx = 0
    while idx < len(tokens):
        token = tokens[idx]
        lower = token.lower()
        if lower in {"--plan-only", "--no-queue"}:
            plan_only = True
            idx += 1
            continue
        if lower in {"--episodes", "-n", "--count"} and idx + 1 < len(tokens):
            try:
                count = int(tokens[idx + 1])
            except ValueError:
                pass
            idx += 2
            continue
        if lower.startswith("--episodes=") or lower.startswith("--count="):
            value = token.split("=", 1)[1]
            try:
                count = int(value)
            except ValueError:
                pass
            idx += 1
            continue
        if lower in {"--level", "--audience"} and idx + 1 < len(tokens):
            level = tokens[idx + 1]
            idx += 2
            continue
        if lower.startswith("--level=") or lower.startswith("--audience="):
            level = token.split("=", 1)[1]
            idx += 1
            continue
        remaining.append(token)
        idx += 1

    text = " ".join(remaining).strip()
    count_match = re.search(r"\b(\d+)\s+episodes?\b", text, flags=re.I)
    if count_match:
        count = int(count_match.group(1))
        text = (text[: count_match.start()] + text[count_match.end() :]).strip()

    parts = text.split()
    if parts and re.search(r"(beginner|intermediate|advanced|expert|novice)", parts[-1], re.I):
        level = parts[-1]
        text = " ".join(parts[:-1]).strip()

    count = max(3, min(8, count))
    return text, count, level, plan_only


def _format_learning_path_summary(path_data: dict[str, Any] | None) -> str:
    if not path_data:
        return "No learning path found yet."
    lines = [
        f"Path: {path_data.get('title')}",
        f"Topic: {path_data.get('topic')}",
        f"Level: {path_data.get('level')}",
        f"Episodes: {len(path_data.get('episodes') or [])}",
    ]
    if path_data.get("markdown_path"):
        lines.append(f"Markdown: {path_data['markdown_path']}")
    elif path_data.get("path_id"):
        lines.append(f"Path ID: {path_data['path_id']}")
    lines.append("")
    for episode in (path_data.get("episodes") or [])[:8]:
        if not isinstance(episode, dict):
            continue
        ep_type = episode.get("episode_type", "deep_dive")
        lines.append(
            f"{episode.get('number', '?')}. [{episode_type_label(str(ep_type))}] "
            f"{episode.get('title', '(untitled)')}"
        )
    return "\n".join(lines)


_OWNER_HELP_TEXT = (
    "Asynchronous command center.\n\n"
    "Make episodes:\n"
    "/generate <topic> - start a new episode\n"
    "/generate --type how_to <topic> - typed episode\n"
    "/generate --guest <topic> - force a synthetic guest expert\n"
    "/generate --no-guest <topic> - disable guest experts\n"
    "/generate landscape: <topic> - shorthand typed episode\n"
    "/series <topic> - plan a mini-course and queue it\n"
    "/types - list available episode types\n\n"
    "Queue and control:\n"
    "/queue <topic> - add a topic to the queue\n"
    "/queue - show queued topics\n"
    "/next - generate the next queued topic\n"
    "/status - active job and latest manifest\n"
    "/cancel - stop the active generation\n\n"
    "See what shipped:\n"
    "/latest - most recent episode\n"
    "/paths - most recent learning path\n"
    "/context - listener profile and covered topics\n"
    "/remember domain|background|depth|goal|style|avoid|note <text>\n\n"
    "Plumbing:\n"
    "/tts - show active TTS routing config\n"
    "/doctor - check bot/server prerequisites\n"
    "/help, /start - show this list\n\n"
    "Guest access:\n"
    "Users in TELEGRAM_GUEST_USERS can send /generate; each request is forwarded here for approval."
)

_GUEST_HELP_TEXT = (
    "Asynchronous - guest access.\n\n"
    "/generate <topic> - request an episode (sent to the owner for approval)\n"
    "/help, /start - show this list\n\n"
    "When your request is approved you'll get a notification here, and another one when the episode is ready."
)


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if _is_authorized(update):
        await _reply(update, _OWNER_HELP_TEXT)
        return
    if _is_guest(update):
        await _reply(update, _GUEST_HELP_TEXT)
        return
    # Unknown user — _is_authorized already logged the rejection.


async def generate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if _is_guest(update):
        await _handle_guest_generate(update, context)
        return
    if not _is_authorized(update):
        return
    try:
        episode_type, topic, guest_mode = _parse_generation_args(context)
    except ValueError as exc:
        await _reply(update, f"{exc}\n\nUse /types to see available episode types.")
        return
    error = _validate_topic(topic)
    if error:
        await _reply(update, error)
        return
    await _run_generation(update, topic, episode_type, guest_mode=guest_mode)


async def _handle_guest_generate(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Validate, store, and forward a guest's /generate request to the owner."""
    global _next_approval_id

    user = update.effective_user
    chat = update.effective_chat
    if user is None or chat is None:
        return

    try:
        episode_type, topic, guest_mode = _parse_generation_args(context)
    except ValueError as exc:
        await _reply(update, f"{exc}")
        return
    error = _validate_topic(topic)
    if error:
        await _reply(update, error)
        return

    if not OWNER_USER_ID:
        await _reply(
            update,
            "Sorry — the owner hasn't configured an approval target. Try again later.",
        )
        logger.error(
            "Guest /generate from %s rejected: OWNER_USER_ID is unset.",
            _describe_user(update),
        )
        return

    pending_for_user = sum(
        1 for req in _pending_approvals.values() if req["user_id"] == user.id
    )
    if pending_for_user >= MAX_PENDING_PER_GUEST:
        await _reply(
            update,
            f"You already have {pending_for_user} request(s) waiting for approval. "
            "Please wait for one to be decided before sending another.",
        )
        return

    _next_approval_id += 1
    rid = str(_next_approval_id)
    submitted_at = datetime.now()
    _pending_approvals[rid] = {
        "user_id": user.id,
        "user_label": _describe_user(update),
        "chat_id": chat.id,
        "topic": topic,
        "episode_type": episode_type,
        "guest_mode": guest_mode,
        "submitted_at": submitted_at,
    }

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Approve", callback_data=f"approve:{rid}"),
                InlineKeyboardButton("Deny", callback_data=f"deny:{rid}"),
            ]
        ]
    )
    guest_note = f", guest={guest_mode}" if guest_mode else ""
    approval_text = (
        f"Guest request #{rid}\n\n"
        f"From: {_describe_user(update)}\n"
        f"Type: {episode_type_label(episode_type)}{guest_note}\n"
        f"Submitted: {submitted_at.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"Topic:\n{topic}"
    )
    try:
        await context.bot.send_message(
            chat_id=OWNER_USER_ID,
            text=approval_text[:3900],
            reply_markup=keyboard,
        )
    except Exception as exc:
        _pending_approvals.pop(rid, None)
        logger.exception("Failed to send approval prompt to owner")
        await _reply(update, f"Could not reach the owner: {exc!r}. Try again later.")
        return

    await _reply(
        update,
        f"Got it — forwarded to the owner for approval (request #{rid}). "
        "I'll message you once it's decided.",
    )


async def approval_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle Approve/Deny button clicks on a guest's approval prompt."""
    query = update.callback_query
    if query is None or query.from_user is None:
        return

    if query.from_user.id != OWNER_USER_ID:
        await query.answer("Only the owner can approve guest requests.", show_alert=True)
        return

    data = query.data or ""
    action, _, rid = data.partition(":")
    if action not in {"approve", "deny"} or not rid:
        await query.answer("Unrecognized action.")
        return

    request = _pending_approvals.pop(rid, None)
    await query.answer()

    if request is None:
        with contextlib.suppress(Exception):
            await query.edit_message_text(
                (query.message.text if query.message else "")
                + "\n\n(Request already handled or expired.)"
            )
        return

    user_label = request["user_label"]
    topic = request["topic"]
    guest_chat = int(request["chat_id"])

    if action == "deny":
        with contextlib.suppress(Exception):
            await query.edit_message_text(
                f"DENIED - request #{rid}\n\nFrom: {user_label}\nTopic: {topic}"
            )
        with contextlib.suppress(Exception):
            await context.bot.send_message(
                chat_id=guest_chat,
                text=(
                    f"Your request was not approved this time.\n\nTopic: {topic}"
                ),
            )
        return

    # action == "approve"
    repo_root = _repo_root()
    busy = _generation_lock.locked() or get_status(repo_root) is not None
    if busy:
        item: dict[str, str] = {
            "topic": topic,
            "episode_type": request["episode_type"],
            "guest_requester_chat_id": str(guest_chat),
            "guest_requester_label": user_label,
        }
        if request.get("guest_mode"):
            item["guest_host_mode"] = str(request["guest_mode"])
        _queue.append(item)
        with contextlib.suppress(Exception):
            await query.edit_message_text(
                f"APPROVED - request #{rid} queued at position {len(_queue)}.\n\n"
                f"From: {user_label}\nTopic: {topic}\n\n"
                "Use /next when ready to run it."
            )
        with contextlib.suppress(Exception):
            await context.bot.send_message(
                chat_id=guest_chat,
                text=(
                    f"Approved! Your topic was queued (position {len(_queue)}). "
                    "I'll message you when the episode is ready.\n\n"
                    f"Topic: {topic}"
                ),
            )
        return

    # Idle — run now.
    with contextlib.suppress(Exception):
        await query.edit_message_text(
            f"APPROVED - request #{rid} starting now.\n\n"
            f"From: {user_label}\nTopic: {topic}"
        )
    with contextlib.suppress(Exception):
        await context.bot.send_message(
            chat_id=guest_chat,
            text=(
                "Approved! Generation is starting. I'll message you when it's ready.\n\n"
                f"Topic: {topic}"
            ),
        )

    # Spawn the actual generation in the background so the callback returns promptly.
    asyncio.create_task(
        _run_generation(
            update,
            topic,
            request["episode_type"],
            guest_mode=request.get("guest_mode"),
            notify_chat_ids=[guest_chat],
        )
    )


async def queue_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return
    try:
        episode_type, topic, guest_mode = _parse_generation_args(context)
    except ValueError as exc:
        await _reply(update, f"{exc}\n\nUse /types to see available episode types.")
        return
    if not topic:
        if not _queue:
            await _reply(update, "Queue is empty.")
            return
        lines = [
            f"{idx + 1}. [{episode_type_label(item['episode_type'])}]"
            f"{' guest=' + item['guest_host_mode'] if item.get('guest_host_mode') else ''}"
            f"{' (requested by ' + str(item['guest_requester_label']) + ')' if item.get('guest_requester_label') else ''} "
            f"{item['topic']}"
            for idx, item in enumerate(_queue)
        ]
        await _reply(update, "Queued topics:\n" + "\n".join(lines))
        return

    error = _validate_topic(topic)
    if error:
        error = error.replace("/generate", "/queue")
    if error:
        await _reply(update, error)
        return
    item = {"topic": topic, "episode_type": episode_type}
    if guest_mode:
        item["guest_host_mode"] = guest_mode
    _queue.append(item)
    guest_note = f", guest={guest_mode}" if guest_mode else ""
    await _reply(
        update,
        f"Queued at position {len(_queue)}: [{episode_type_label(episode_type)}{guest_note}] {topic!r}",
    )


async def next_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return
    if not _queue:
        await _reply(update, "Queue is empty.")
        return
    if _generation_lock.locked() or get_status(_repo_root()):
        await _reply(update, "A generation is already running. Queue was left unchanged.")
        return
    item = _queue.pop(0)
    notify_chat_ids: list[int] = []
    guest_chat_raw = item.get("guest_requester_chat_id")
    if guest_chat_raw:
        try:
            notify_chat_ids.append(int(guest_chat_raw))
        except (TypeError, ValueError):
            pass
    await _run_generation(
        update,
        item["topic"],
        item["episode_type"],
        guest_mode=item.get("guest_host_mode"),
        notify_chat_ids=notify_chat_ids or None,
    )


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return
    repo_root = _repo_root()
    lines: list[str] = []

    if _active_proc and _active_proc.returncode is None:
        lines.append(f"Bot subprocess: running pid {_active_proc.pid}")
        lines.append(f"Topic: {_active_topic}")
        if _active_episode_type:
            active_label = (
                "Learning Path"
                if _active_episode_type == "learning_path"
                else episode_type_label(_active_episode_type)
            )
            lines.append(f"Type: {active_label}")
        lines.append(f"Elapsed: {_format_elapsed(_active_started_at)}")
        if _active_log:
            lines.append(f"Log: {_active_log}")
    else:
        lines.append("Bot subprocess: idle")

    lock_data = get_status(repo_root)
    if lock_data:
        lines.append("")
        lines.append(f"Generation lock: pid {lock_data.get('pid')}")
        lines.append(f"Run ID: {lock_data.get('run_id')}")
        lines.append(f"Started: {lock_data.get('started_at')}")
    else:
        lines.append("")
        lines.append("Generation lock: idle")

    lines.append("")
    lines.append("Latest manifest:")
    lines.append(_format_manifest_summary(_latest_manifest(repo_root)))
    await _reply(update, "\n".join(lines))


async def latest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return
    await _reply(update, _format_manifest_summary(_latest_manifest(_repo_root())))


async def types_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return
    await _reply(
        update,
        "Episode types:\n"
        + episode_type_help()
        + "\n\nExamples:\n"
        "/generate --type how_to make a tiny FM synth\n"
        "/generate landscape: open source music generation tools",
    )


async def series_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return
    repo_root = _repo_root()
    raw = _topic_from_args(context)
    topic, count, level, plan_only = _parse_series_args(raw, repo_root)
    error = _validate_topic(topic)
    if error:
        await _reply(
            update,
            "Usage: /series <topic> [5 episodes] [beginner-to-intermediate]\n"
            "Options: --episodes N, --level LEVEL, --plan-only",
        )
        return
    await _run_learning_path(update, topic, count, level, plan_only=plan_only)


async def paths_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return
    await _reply(update, _format_learning_path_summary(_latest_learning_path(_repo_root())))


async def context_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return
    repo_root = _repo_root()
    cfg = _personal_context_cfg(repo_root)
    data, path = load_personal_context(repo_root, cfg)
    summary = format_personal_context_summary(
        data,
        max_topics=int(cfg.get("personal_context_max_topics", 24)),
    )
    await _reply(
        update,
        summary
        + f"\n\nFile: {path}\n"
        "Teach me with:\n"
        "/remember background <your professional context>\n"
        "/remember domain <favorite domain>\n"
        "/remember depth <preferred depth>\n"
        "/remember goal <learning goal>\n"
        "/remember style <style preference>\n"
        "/remember avoid <thing to avoid>",
    )


async def remember_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return
    raw = _topic_from_args(context)
    if not raw:
        await _reply(
            update,
            "Usage: /remember domain|background|depth|goal|style|avoid|note <text>",
        )
        return
    parts = raw.split(maxsplit=1)
    if len(parts) < 2:
        await _reply(
            update,
            "Usage: /remember domain|background|depth|goal|style|avoid|note <text>",
        )
        return
    category, value = parts[0], parts[1]
    repo_root = _repo_root()
    cfg = _personal_context_cfg(repo_root)
    data, path = load_personal_context(repo_root, cfg)
    try:
        data, label = remember_personal_context(data, category, value)
    except ValueError as exc:
        await _reply(update, str(exc))
        return
    save_personal_context(path, data)
    await _reply(update, f"Remembered {label}: {value}\n\nFile: {path}")


async def tts_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return
    await _reply(update, _format_tts_summary(_repo_root()))


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return

    repo_root = _repo_root()
    lock_data = get_status(repo_root)
    ok, message = cancel_active_job(repo_root)

    if _active_proc and _active_proc.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            _active_proc.terminate()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(_active_proc.wait(), timeout=10)
        if _active_proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                _active_proc.kill()

    manifest = _latest_manifest(repo_root)
    if (
        ok
        and lock_data
        and manifest
        and manifest.data.get("run_id") == lock_data.get("run_id")
        and manifest.data.get("status") == "running"
    ):
        manifest.cancel("Cancelled from Telegram command center.")

    await _reply(update, message if ok else f"Cancel request: {message}")


async def doctor_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return
    repo_root = _repo_root()
    cfg_path = repo_root / "config.json"
    lines = ["Doctor report:"]

    def check(label: str, ok: bool, detail: str = "") -> None:
        status = "OK" if ok else "MISSING"
        suffix = f" - {detail}" if detail else ""
        lines.append(f"{status}: {label}{suffix}")

    check("repo path", repo_root.exists(), str(repo_root))
    check("generate_podcast.py", (repo_root / "generate_podcast.py").exists())
    check("TELEGRAM_BOT_TOKEN", bool(TELEGRAM_BOT_TOKEN))
    check("TELEGRAM_ALLOWED_USERS", bool(ALLOWED_USERS), f"{len(ALLOWED_USERS)} users")
    if GUEST_USERS:
        check(
            "TELEGRAM_GUEST_USERS",
            bool(GUEST_USERS),
            f"{len(GUEST_USERS)} guests; owner={OWNER_USER_ID}; "
            f"pending={len(_pending_approvals)}",
        )
    check("ANTHROPIC_API_KEY", bool(os.environ.get("ANTHROPIC_API_KEY")))
    check("OPENAI_API_KEY", bool(os.environ.get("OPENAI_API_KEY")))
    check("ELEVENLABS_API_KEY", bool(os.environ.get("ELEVENLABS_API_KEY")))
    check("ffmpeg", shutil.which("ffmpeg") is not None)
    check("ffprobe", shutil.which("ffprobe") is not None)
    check("git", shutil.which("git") is not None)

    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            detail = (
                f"output_dir={cfg.get('output_dir', 'episodes')}, "
                f"episode_type={cfg.get('episode_type', 'deep_dive')}, "
                f"research_model={cfg.get('research_model', 'claude-opus-4-5')}, "
                f"dialogue_model={cfg.get('dialogue_model', 'claude-sonnet-4-6')}, "
                f"fact_check_model={cfg.get('fact_check_model', 'claude-sonnet-4-6')}, "
                f"tts_provider={cfg.get('tts_provider', 'openai')}, "
                f"tts_routes={len(cfg.get('tts_routes') or {})}, "
                f"use_clips={cfg.get('use_clips')}, "
                f"use_sonic_footnotes={cfg.get('use_sonic_footnotes')}, "
                f"use_personal_context={cfg.get('use_personal_context')}, "
                f"personal_context_sync_manifests={cfg.get('personal_context_sync_manifests')}, "
                f"use_audio_mastering={cfg.get('use_audio_mastering')}, "
                f"audio_bitrate={cfg.get('audio_bitrate')}, "
                f"script_quality_pipeline={cfg.get('script_quality_pipeline')}"
            )
            check("config.json", True, detail)
        except json.JSONDecodeError as exc:
            check("config.json", False, str(exc))
    else:
        check("config.json", False)

    lock_data = get_status(repo_root)
    check("generation lock", lock_data is None, "idle" if lock_data is None else "active")
    context_cfg = _personal_context_cfg(repo_root)
    context_raw = Path(str(context_cfg.get("personal_context_path", "personal_context.json")))
    context_path = context_raw if context_raw.is_absolute() else repo_root / context_raw
    check("personal context", context_path.exists(), str(context_path))
    latest = _latest_manifest(repo_root)
    if latest:
        summary = latest.to_summary()
        lines.append(
            f"Latest: {summary.get('status')} / {summary.get('stage')} - {summary.get('topic')}"
        )

    await _reply(update, "\n".join(lines))


async def text_hint(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if _is_authorized(update):
        await _reply(
            update,
            "Use /generate <topic> for an episode, /series <topic> for a learning path, /context for personal memory, or /types to browse formats.",
        )
        return
    if _is_guest(update):
        await _reply(
            update,
            "Send /generate <topic> to request an episode. The owner will approve or deny, and I'll let you know either way.",
        )


async def _run_generation(
    update: Update,
    topic: str,
    episode_type: str,
    *,
    guest_mode: str | None = None,
    notify_chat_ids: list[int] | None = None,
) -> None:
    global _active_episode_type, _active_log, _active_proc, _active_started_at, _active_topic

    repo_root = _repo_root()

    async def notify(text: str) -> None:
        await _reply(update, text)
        if notify_chat_ids:
            bot = update.get_bot()
            for cid in notify_chat_ids:
                with contextlib.suppress(Exception):
                    await bot.send_message(chat_id=cid, text=text[:3900])

    if _generation_lock.locked() or get_status(repo_root):
        await notify(
            "A generation is already running. Use /status to inspect it or /cancel to stop it.",
        )
        return

    async with _generation_lock:
        log_dir = repo_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = log_dir / f"{stamp}_{slugify_topic(topic, max_len=48)}.log"
        latest_log = log_dir / "latest.log"

        start_message = (
            f"Starting generation: {topic!r}\n"
            f"Type: {episode_type_label(episode_type)}\n"
            + (f"Guest mode: {guest_mode}\n" if guest_mode else "")
            + f"Log: {log_file}\n"
            + "Use /status for progress or /cancel to stop it."
        )
        await notify(start_message)

        env = os.environ.copy()
        env.setdefault("PYTHONUTF8", "1")

        returncode: int | None = None
        try:
            with open(log_file, "w", encoding="utf-8") as log_fh:
                cmd = [
                    sys.executable,
                    "generate_podcast.py",
                    topic,
                    "--type",
                    episode_type,
                    "--repo",
                    str(repo_root),
                ]
                if guest_mode:
                    cmd.extend(["--guest-mode", guest_mode])
                _active_proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    cwd=repo_root,
                    stdout=log_fh,
                    stderr=log_fh,
                    env=env,
                )
                _active_topic = topic
                _active_episode_type = episode_type
                _active_started_at = datetime.now()
                _active_log = log_file

                try:
                    returncode = await asyncio.wait_for(
                        _active_proc.wait(),
                        timeout=GENERATION_TIMEOUT_SEC,
                    )
                except asyncio.TimeoutError:
                    ok, message = cancel_active_job(repo_root)
                    if not ok and _active_proc.returncode is None:
                        with contextlib.suppress(ProcessLookupError):
                            _active_proc.kill()
                    await notify(
                        f"Generation timed out after {GENERATION_TIMEOUT_SEC}s. {message}",
                    )
                    return

            with contextlib.suppress(OSError):
                shutil.copy2(log_file, latest_log)

            manifest = _latest_manifest(repo_root)
            if returncode == 0:
                queue_note = (
                    f"\nQueue has {len(_queue)} topic(s). Use /next to continue."
                    if _queue
                    else ""
                )
                await notify(
                    "Done.\n\n" + _format_manifest_summary(manifest) + queue_note,
                )
            else:
                summary = _format_manifest_summary(manifest)
                await notify(
                    f"Generation failed (exit {returncode}).\n\n{summary}\n\n"
                    f"Last log lines:\n{_tail(log_file)}",
                )
        except Exception as exc:
            logger.exception("Generation command crashed")
            await notify(f"Generation command crashed: {exc!r}")
        finally:
            _active_proc = None
            _active_topic = None
            _active_episode_type = None
            _active_started_at = None
            _active_log = None


async def _run_learning_path(
    update: Update,
    topic: str,
    count: int,
    level: str,
    *,
    plan_only: bool,
) -> None:
    global _active_episode_type, _active_log, _active_proc, _active_started_at, _active_topic

    repo_root = _repo_root()
    if _generation_lock.locked() or get_status(repo_root):
        await _reply(
            update,
            "A generation or learning-path job is already running. Use /status to inspect it.",
        )
        return

    async with _generation_lock:
        log_dir = repo_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = log_dir / f"{stamp}_{slugify_topic(topic, max_len=48)}_learning_path.log"

        await _reply(
            update,
            f"Planning learning path: {topic!r}\n"
            f"Episodes: {count}\n"
            f"Level: {level}\n"
            f"Log: {log_file}",
        )

        env = os.environ.copy()
        env.setdefault("PYTHONUTF8", "1")

        try:
            with open(log_file, "w", encoding="utf-8") as log_fh:
                _active_proc = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "plan_learning_path.py",
                    topic,
                    "--episodes",
                    str(count),
                    "--level",
                    level,
                    "--repo",
                    str(repo_root),
                    cwd=repo_root,
                    stdout=log_fh,
                    stderr=log_fh,
                    env=env,
                )
                _active_topic = topic
                _active_episode_type = "learning_path"
                _active_started_at = datetime.now()
                _active_log = log_file
                returncode = await asyncio.wait_for(
                    _active_proc.wait(),
                    timeout=GENERATION_TIMEOUT_SEC,
                )

            if returncode != 0:
                await _reply(
                    update,
                    f"Learning path planning failed (exit {returncode}).\n\n"
                    f"Last log lines:\n{_tail(log_file)}",
                )
                return

            path_data = _latest_learning_path(repo_root)
            if not path_data:
                await _reply(update, "Learning path was created, but I could not read it.")
                return

            added = 0
            if not plan_only:
                path_id = str(path_data.get("path_id") or "")
                for episode in path_data.get("episodes") or []:
                    if not isinstance(episode, dict):
                        continue
                    _queue.append(
                        {
                            "topic": str(episode.get("topic_prompt") or episode.get("title")),
                            "episode_type": str(episode.get("episode_type") or "deep_dive"),
                            "learning_path_id": path_id,
                            "title": str(episode.get("title") or ""),
                        }
                    )
                    added += 1

            suffix = (
                f"\n\nQueued {added} episode(s). Use /next to start lesson 1."
                if added
                else "\n\nPlan-only mode: nothing queued."
            )
            await _reply(update, _format_learning_path_summary(path_data) + suffix)
        except asyncio.TimeoutError:
            if _active_proc and _active_proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    _active_proc.kill()
            await _reply(update, f"Learning path planning timed out after {GENERATION_TIMEOUT_SEC}s.")
        except Exception as exc:
            logger.exception("Learning path command crashed")
            await _reply(update, f"Learning path command crashed: {exc!r}")
        finally:
            _active_proc = None
            _active_topic = None
            _active_episode_type = None
            _active_started_at = None
            _active_log = None


def _require_config() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is unset. Get one from @BotFather on Telegram."
        )
    if not ALLOWED_USERS:
        raise RuntimeError(
            "TELEGRAM_ALLOWED_USERS is unset. Set it to your numeric Telegram user ID."
        )
    if GUEST_USERS and not OWNER_USER_ID:
        raise RuntimeError(
            "TELEGRAM_GUEST_USERS is set but no owner could be resolved. "
            "Set TELEGRAM_OWNER_USER_ID or ensure TELEGRAM_ALLOWED_USERS is non-empty."
        )


def main() -> None:
    _require_config()
    retry_delay = 5
    while True:
        try:
            app = (
                Application.builder()
                .token(TELEGRAM_BOT_TOKEN)
                .concurrent_updates(True)
                .build()
            )
            app.add_handler(CommandHandler("start", start_cmd))
            app.add_handler(CommandHandler("help", start_cmd))
            app.add_handler(CommandHandler(["generate", "gen"], generate_cmd))
            app.add_handler(CommandHandler("queue", queue_cmd))
            app.add_handler(CommandHandler("next", next_cmd))
            app.add_handler(CommandHandler("status", status_cmd))
            app.add_handler(CommandHandler("latest", latest_cmd))
            app.add_handler(CommandHandler("types", types_cmd))
            app.add_handler(CommandHandler(["series", "learningpath", "path"], series_cmd))
            app.add_handler(CommandHandler("paths", paths_cmd))
            app.add_handler(CommandHandler("context", context_cmd))
            app.add_handler(CommandHandler("remember", remember_cmd))
            app.add_handler(CommandHandler("tts", tts_cmd))
            app.add_handler(CommandHandler("cancel", cancel_cmd))
            app.add_handler(CommandHandler("doctor", doctor_cmd))
            app.add_handler(
                CallbackQueryHandler(approval_callback, pattern=r"^(approve|deny):")
            )
            app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_hint))

            logger.info(
                "Bot polling started. Allowed users: %s. Guest users: %s. Owner: %s. "
                "Allowed chats: %s. Repo: %s",
                sorted(ALLOWED_USERS),
                sorted(GUEST_USERS),
                OWNER_USER_ID,
                sorted(ALLOWED_CHATS),
                _repo_root(),
            )
            app.run_polling(allowed_updates=Update.ALL_TYPES)
            retry_delay = 5
        except (KeyboardInterrupt, SystemExit):
            logger.info("Bot stopped.")
            break
        except Exception as exc:
            logger.error("Bot crashed: %r. Restarting in %ss...", exc, retry_delay)
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 300)


if __name__ == "__main__":
    main()
