#!/usr/bin/env python3
"""Load and validate the per-show config for the Asynchronous Rounds digests.

Shows live in ``digests.json`` (not ``config.json``) because they are nested,
list-heavy editorial objects that don't fit the flat env/JSON overlay in
``generate_podcast.load_config``. Each show defines the journal set, query
terms, lookback window, output feed, and weekly schedule for one digest.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from episode_types import normalize_episode_type

DIGESTS_FILENAME = "digests.json"

# Keys every show must define.
_REQUIRED_KEYS = (
    "display_name",
    "feed_filename",
    "episode_type",
    "audience",
    "journals",
)

# Print or electronic ISSN, e.g. 1469-0705 or 1873-233X.
_ISSN_RE = re.compile(r"^\d{4}-\d{3}[\dxX]$")


class DigestConfigError(ValueError):
    """Raised when digests.json is missing, malformed, or invalid."""


def _digests_path(repo_root: Path) -> Path:
    return Path(repo_root) / DIGESTS_FILENAME


def load_shows(repo_root: Path = Path(".")) -> dict[str, dict[str, Any]]:
    """Return ``{show_id: normalized_show_dict}``; raise DigestConfigError on problems."""
    path = _digests_path(repo_root)
    if not path.exists():
        raise DigestConfigError(f"{path} not found")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DigestConfigError(f"could not read {path}: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("shows"), dict):
        raise DigestConfigError(f"{path} must contain a top-level 'shows' object")
    shows: dict[str, dict[str, Any]] = {}
    for show_id, show in raw["shows"].items():
        if not isinstance(show, dict):
            raise DigestConfigError(f"show {show_id!r} must be an object")
        shows[str(show_id)] = _validate_show(str(show_id), show)
    if not shows:
        raise DigestConfigError(f"{path} defines no shows")
    return shows


def list_show_ids(repo_root: Path = Path(".")) -> list[str]:
    return sorted(load_shows(repo_root).keys())


def get_show(repo_root: Path, show_id: str) -> dict[str, Any]:
    shows = load_shows(repo_root)
    if show_id not in shows:
        valid = ", ".join(sorted(shows)) or "(none)"
        raise DigestConfigError(f"unknown show {show_id!r}. Valid shows: {valid}")
    return shows[show_id]


def _validate_show(show_id: str, show: dict[str, Any]) -> dict[str, Any]:
    def err(msg: str) -> DigestConfigError:
        return DigestConfigError(f"show {show_id!r}: {msg}")

    for key in _REQUIRED_KEYS:
        if not show.get(key):
            raise err(f"missing required key {key!r}")

    out: dict[str, Any] = dict(show)
    out["id"] = show_id

    # episode_type must normalize against the shared episode-type menu.
    try:
        out["episode_type"] = normalize_episode_type(str(show["episode_type"]))
    except ValueError as exc:
        raise err(str(exc)) from exc

    # feed_filename must be a bare filename (no path traversal / separators).
    feed = str(show["feed_filename"]).strip()
    if not feed or "/" in feed or "\\" in feed or ".." in feed or feed != Path(feed).name:
        raise err(f"feed_filename must be a bare filename, got {feed!r}")
    out["feed_filename"] = feed

    # journals.{issns, ta_names}
    journals = show.get("journals")
    if not isinstance(journals, dict):
        raise err("'journals' must be an object")
    issns = journals.get("issns") or []
    ta_names = journals.get("ta_names") or []
    if not isinstance(issns, list) or not isinstance(ta_names, list):
        raise err("journals.issns and journals.ta_names must be arrays")
    if not ta_names:
        raise err("journals.ta_names must list at least one journal abbreviation")
    bad_issns = [i for i in issns if not _ISSN_RE.match(str(i).strip())]
    if bad_issns:
        raise err(f"malformed ISSN(s): {bad_issns}")
    out["journals"] = {
        "issns": [str(i).strip() for i in issns],
        "ta_names": [str(t).strip() for t in ta_names],
    }

    # Bounded numeric knobs with sensible defaults.
    out["target_minutes"] = _pos_int(show.get("target_minutes", 16), "target_minutes", err)
    out["window_months"] = _pos_int(show.get("window_months", 6), "window_months", err)
    out["top_n"] = _pos_int(show.get("top_n", 5), "top_n", err)
    out["max_rounds"] = _pos_int(show.get("max_rounds", 5), "max_rounds", err)

    # Optional fields with defaults.
    out.setdefault("description", out["display_name"])
    out.setdefault("author", "Juno & Caspar")
    out.setdefault("category", "Science")
    out.setdefault("cover_image", "")
    out["include_preprints"] = bool(show.get("include_preprints", False))
    out["mesh_terms"] = [str(m).strip() for m in (show.get("mesh_terms") or []) if str(m).strip()]
    out["keywords"] = [str(k).strip() for k in (show.get("keywords") or []) if str(k).strip()]

    topic_bias = show.get("topic_bias")
    if topic_bias is not None and not isinstance(topic_bias, dict):
        raise err("topic_bias must be an object mapping domain -> multiplier")
    out["topic_bias"] = topic_bias or None

    schedule = show.get("schedule") or {}
    if not isinstance(schedule, dict):
        raise err("schedule must be an object")
    try:
        hour = int(schedule.get("hour", 5))
    except (TypeError, ValueError):
        raise err("schedule.hour must be an integer") from None
    out["schedule"] = {
        "weekday": str(schedule.get("weekday", "mon")).strip().lower()[:3],
        "hour": max(0, min(23, hour)),
    }

    if not out["mesh_terms"] and not out["keywords"]:
        raise err("define at least one mesh_term or keyword for the topic filter")
    return out


def _pos_int(value: Any, name: str, err: Callable[[str], DigestConfigError]) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise err(f"{name} must be an integer") from None
    if n < 1:
        raise err(f"{name} must be >= 1")
    return n


if __name__ == "__main__":  # pragma: no cover - quick manual check
    import sys

    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    for sid, s in load_shows(root).items():
        print(f"{sid:8} {s['display_name']:24} feed={s['feed_filename']:16} "
              f"window={s['window_months']}mo top_n={s['top_n']} "
              f"journals={len(s['journals']['ta_names'])} preprints={s['include_preprints']}")
