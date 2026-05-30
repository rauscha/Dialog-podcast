#!/usr/bin/env python3
"""Personal listener context and topic-history helpers."""

from __future__ import annotations

import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CONTEXT_NAME = "personal_context.json"

DEFAULT_PERSONAL_CONTEXT: dict[str, Any] = {
    "schema_version": 1,
    "profile": {
        "professional_background": [],
        "favorite_domains": [],
        "preferred_depth": (
            "Deep and technical when useful, but still audio-friendly. Start with "
            "only enough orientation to make the deeper mechanism, tradeoff, or "
            "story legible."
        ),
        "learning_goals": [],
        "style_preferences": [
            "Candid, specific, and source-grounded.",
            "Prefer mechanisms, tradeoffs, examples, and failure modes over broad summaries.",
            "When a topic repeats, assume the listener wants a deeper cut, not the same primer.",
        ],
        "avoid": [
            "Generic overviews when the topic has already been covered.",
            "Explaining every basic term unless the episode type calls for a primer.",
        ],
    },
    "manual_notes": [],
    "topic_history": [],
}

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "vs",
    "with",
}

_REMEMBER_TARGETS = {
    "background": ("profile", "professional_background"),
    "career": ("profile", "professional_background"),
    "profession": ("profile", "professional_background"),
    "domain": ("profile", "favorite_domains"),
    "favorite": ("profile", "favorite_domains"),
    "depth": ("profile", "preferred_depth"),
    "goal": ("profile", "learning_goals"),
    "style": ("profile", "style_preferences"),
    "avoid": ("profile", "avoid"),
    "note": ("manual_notes",),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def topic_key(topic: str) -> str:
    key = re.sub(r"[^\w\-]+", "_", topic.strip().lower())
    key = re.sub(r"_+", "_", key).strip("_")
    return key or "topic"


def topic_tokens(topic: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", topic.lower())
    return {w for w in words if len(w) >= 2 and w not in _STOPWORDS}


def topic_similarity(a: str, b: str) -> float:
    a_key = topic_key(a)
    b_key = topic_key(b)
    if a_key == b_key:
        return 1.0
    a_tokens = topic_tokens(a)
    b_tokens = topic_tokens(b)
    if not a_tokens or not b_tokens:
        return 0.0
    overlap = len(a_tokens & b_tokens)
    union = len(a_tokens | b_tokens)
    score = overlap / union if union else 0.0
    if a_key in b_key or b_key in a_key:
        score = max(score, 0.82)
    return score


def _context_path(repo_root: Path, context_path: str | Path | None = None) -> Path:
    raw = Path(str(context_path or CONTEXT_NAME))
    return raw if raw.is_absolute() else repo_root / raw


def _clone_default_context() -> dict[str, Any]:
    return json.loads(json.dumps(DEFAULT_PERSONAL_CONTEXT))


def normalize_personal_context(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        data = {}
    ctx = _clone_default_context()
    ctx.update({k: v for k, v in data.items() if k not in {"profile"}})
    profile = data.get("profile") if isinstance(data.get("profile"), dict) else {}
    ctx["profile"].update(profile)

    for key in ["professional_background", "favorite_domains", "learning_goals", "style_preferences", "avoid"]:
        value = ctx["profile"].get(key)
        if value is None:
            ctx["profile"][key] = []
        elif not isinstance(value, list):
            ctx["profile"][key] = [str(value)]

    if not isinstance(ctx["profile"].get("preferred_depth"), str):
        ctx["profile"]["preferred_depth"] = str(
            DEFAULT_PERSONAL_CONTEXT["profile"]["preferred_depth"]
        )
    if not isinstance(ctx.get("manual_notes"), list):
        ctx["manual_notes"] = []
    if not isinstance(ctx.get("topic_history"), list):
        ctx["topic_history"] = []
    return ctx


def save_personal_context(path: Path, context: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    context["updated_at"] = utc_now()
    payload = json.dumps(normalize_personal_context(context), indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
        prefix=f".{path.name}.",
        suffix=".tmp",
    ) as tmp:
        tmp.write(payload)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def load_personal_context(repo_root: Path, cfg: dict[str, Any]) -> tuple[dict[str, Any], Path]:
    path = _context_path(repo_root, cfg.get("personal_context_path", CONTEXT_NAME))
    if not path.exists():
        ctx = _clone_default_context()
        save_personal_context(path, ctx)
    else:
        try:
            ctx = normalize_personal_context(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, ValueError):
            ctx = _clone_default_context()
    if _coerce_bool(cfg.get("personal_context_sync_manifests", True), True):
        added = sync_topic_history_from_manifests(
            repo_root,
            ctx,
            output_dir=str(cfg.get("output_dir") or "episodes"),
            max_topics=int(cfg.get("personal_context_max_topics", 24)),
        )
        if added:
            save_personal_context(path, ctx)
    return ctx, path


def _coerce_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off", ""}:
        return False
    return default


def sync_topic_history_from_manifests(
    repo_root: Path,
    context: dict[str, Any],
    *,
    output_dir: str = "episodes",
    max_topics: int = 24,
) -> int:
    episodes_dir = repo_root / output_dir
    if not episodes_dir.exists():
        return 0

    normalized = normalize_personal_context(context)
    context.clear()
    context.update(normalized)
    history = [item for item in context.get("topic_history", []) if isinstance(item, dict)]
    seen = {
        str(item.get("run_id") or "") or f"{item.get('topic_key')}:{item.get('created_at')}"
        for item in history
    }
    added = 0
    manifests = sorted(
        episodes_dir.glob("*_work/episode_manifest.json"),
        key=lambda p: p.stat().st_mtime,
    )
    for manifest_path in manifests:
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        status = str(data.get("status") or "").lower()
        if status and status != "completed":
            continue
        topic = str(data.get("topic") or "").strip()
        if not topic:
            continue
        run_id = str(data.get("run_id") or manifest_path.parent.name)
        if run_id in seen:
            continue
        options = data.get("options") if isinstance(data.get("options"), dict) else {}
        metrics = data.get("metrics") if isinstance(data.get("metrics"), dict) else {}
        entry = {
            "topic": topic,
            "topic_key": topic_key(topic),
            "episode_type": str(
                options.get("episode_type")
                or metrics.get("episode_type")
                or "deep_dive"
            ),
            "episode_type_label": str(
                options.get("episode_type_label")
                or metrics.get("episode_type_label")
                or ""
            ),
            "run_id": run_id,
            "created_at": str(data.get("created_at") or utc_now()),
        }
        try:
            if metrics.get("word_count") is not None:
                entry["word_count"] = int(metrics["word_count"])
        except (TypeError, ValueError):
            pass
        try:
            if metrics.get("source_count") is not None:
                entry["source_count"] = int(metrics["source_count"])
        except (TypeError, ValueError):
            pass
        history.append(entry)
        seen.add(run_id)
        added += 1

    history.sort(key=lambda item: str(item.get("created_at") or ""))
    context["topic_history"] = history[-max_topics:]
    return added


def bounded_personal_context(
    context: dict[str, Any],
    *,
    max_topics: int = 24,
) -> dict[str, Any]:
    bounded = normalize_personal_context(context)
    bounded["topic_history"] = list(bounded.get("topic_history", []))[-max_topics:]
    return bounded


def find_related_topics(
    context: dict[str, Any],
    topic: str,
    *,
    limit: int = 5,
    threshold: float = 0.34,
) -> list[dict[str, Any]]:
    related: list[dict[str, Any]] = []
    for item in context.get("topic_history", []):
        if not isinstance(item, dict):
            continue
        prior_topic = str(item.get("topic") or "")
        if not prior_topic:
            continue
        score = topic_similarity(topic, prior_topic)
        if score >= threshold:
            copy = dict(item)
            copy["similarity"] = round(score, 3)
            related.append(copy)
    related.sort(key=lambda row: (float(row.get("similarity", 0)), str(row.get("created_at", ""))), reverse=True)
    return related[:limit]


def personal_context_prompt(
    context: dict[str, Any],
    topic: str,
    cfg: dict[str, Any],
) -> str:
    max_topics = int(cfg.get("personal_context_max_topics", 24))
    threshold = float(cfg.get("personal_context_similarity_threshold", 0.34))
    bounded = bounded_personal_context(context, max_topics=max_topics)
    profile = bounded["profile"]
    related = find_related_topics(
        bounded,
        topic,
        limit=5,
        threshold=threshold,
    )
    payload = {
        "profile": profile,
        "manual_notes": bounded.get("manual_notes", [])[-10:],
        "recent_topics": bounded.get("topic_history", [])[-max_topics:],
        "related_prior_topics": related,
    }
    guidance = [
        "Personal context mode is enabled.",
        "Use this context to choose depth, examples, analogies, and assumed audience knowledge.",
        "Do not announce or expose private profile details unless the user explicitly asked for that.",
        "Use favorite domains as optional lenses, not as forced tangents.",
        "If related_prior_topics is non-empty, avoid repeating the same primer. Re-enter the subject through a deeper mechanism, a new angle, unresolved questions, or a more advanced application.",
    ]
    return "\n".join(guidance) + "\n\n" + json.dumps(payload, indent=2, sort_keys=True)


def record_topic(
    context: dict[str, Any],
    *,
    topic: str,
    episode_type: str,
    episode_type_label: str,
    run_id: str,
    word_count: int | None = None,
    source_count: int | None = None,
) -> dict[str, Any]:
    normalized = normalize_personal_context(context)
    context.clear()
    context.update(normalized)
    entry: dict[str, Any] = {
        "topic": topic,
        "topic_key": topic_key(topic),
        "episode_type": episode_type,
        "episode_type_label": episode_type_label,
        "run_id": run_id,
        "created_at": utc_now(),
    }
    if word_count is not None:
        entry["word_count"] = int(word_count)
    if source_count is not None:
        entry["source_count"] = int(source_count)
    history = [item for item in context.get("topic_history", []) if isinstance(item, dict)]
    history.append(entry)
    context["topic_history"] = history
    return entry


def remember_personal_context(
    context: dict[str, Any],
    category: str,
    value: str,
) -> tuple[dict[str, Any], str]:
    context = normalize_personal_context(context)
    key = category.strip().lower().replace("-", "_")
    target = _REMEMBER_TARGETS.get(key)
    if not target:
        valid = ", ".join(sorted(_REMEMBER_TARGETS))
        raise ValueError(f"Unknown context category {category!r}. Valid: {valid}")

    value = value.strip()
    if not value:
        raise ValueError("Nothing to remember.")

    if target == ("profile", "preferred_depth"):
        context["profile"]["preferred_depth"] = value
        return context, "preferred depth"

    if target == ("manual_notes",):
        bucket = context.setdefault("manual_notes", [])
        if value not in bucket:
            bucket.append(value)
        return context, "manual note"

    _, field = target
    bucket = context.setdefault("profile", {}).setdefault(field, [])
    if not isinstance(bucket, list):
        bucket = [str(bucket)]
        context["profile"][field] = bucket
    if value not in bucket:
        bucket.append(value)
    return context, field


def format_personal_context_summary(context: dict[str, Any], *, max_topics: int = 8) -> str:
    context = normalize_personal_context(context)
    profile = context["profile"]

    def line_list(values: list[Any]) -> str:
        cleaned = [str(v).strip() for v in values if str(v).strip()]
        return ", ".join(cleaned) if cleaned else "(none yet)"

    lines = [
        "Personal context:",
        f"Background: {line_list(profile.get('professional_background', []))}",
        f"Favorite domains: {line_list(profile.get('favorite_domains', []))}",
        f"Preferred depth: {profile.get('preferred_depth') or '(none yet)'}",
        f"Learning goals: {line_list(profile.get('learning_goals', []))}",
        f"Style: {line_list(profile.get('style_preferences', []))}",
        f"Avoid: {line_list(profile.get('avoid', []))}",
    ]
    history = [item for item in context.get("topic_history", []) if isinstance(item, dict)]
    if history:
        lines.append("")
        lines.append("Recent covered topics:")
        for item in history[-max_topics:]:
            label = str(item.get("episode_type_label") or item.get("episode_type") or "?")
            lines.append(f"- [{label}] {item.get('topic')}")
    return "\n".join(lines)
