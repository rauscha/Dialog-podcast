#!/usr/bin/env python3
"""Per-show DOI ledger for the Asynchronous Rounds digests.

Each show keeps a ledger at ``digests/<show_id>_ledger.json`` recording which
articles have already aired (``covered``, keyed by normalized DOI) plus a
``backlog`` of strong-but-unaired papers that can resurface in later episodes.
Exact DOI matching is the right dedup primitive for articles (unlike the fuzzy
topic-similarity used for free-form episodes in personal_context).

Phase 1 implemented load / filter / atomic-save and the key-normalization
helpers. Phase 3 adds ``record_episode``, which mutates the ledger after a
successful publish so future runs skip already-aired papers.
"""

from __future__ import annotations

import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LEDGER_DIR = "digests"

_DOI_PREFIXES = ("https://doi.org/", "http://doi.org/", "http://dx.doi.org/", "https://dx.doi.org/", "doi:")


def ledger_path(repo_root: Path, show_id: str) -> Path:
    return Path(repo_root) / LEDGER_DIR / f"{show_id}_ledger.json"


def _default_ledger(show_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "show_id": show_id,
        "covered": {},
        "backlog": [],
        "last_run": None,
        "updated_at": None,
    }


def load_ledger(repo_root: Path, show_id: str) -> dict[str, Any]:
    """Load a show's ledger, returning a fresh default if missing/corrupt."""
    path = ledger_path(repo_root, show_id)
    if not path.exists():
        return _default_ledger(show_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_ledger(show_id)
    if not isinstance(data, dict):
        return _default_ledger(show_id)
    # Normalize shape so callers can rely on the keys existing.
    base = _default_ledger(show_id)
    base.update({k: data.get(k, base[k]) for k in base})
    if not isinstance(base["covered"], dict):
        base["covered"] = {}
    if not isinstance(base["backlog"], list):
        base["backlog"] = []
    base["show_id"] = show_id
    return base


def save_ledger(repo_root: Path, show_id: str, ledger: dict[str, Any]) -> None:
    """Atomically write the ledger (temp file + replace), mirroring host-memory I/O."""
    path = ledger_path(repo_root, show_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    ledger = dict(ledger)
    ledger["show_id"] = show_id
    ledger["updated_at"] = datetime.now(timezone.utc).isoformat()
    payload = json.dumps(ledger, indent=2, sort_keys=True)
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


def normalize_doi(value: str) -> str:
    """Lowercase, strip URL/`doi:` prefixes and trailing punctuation."""
    doi = str(value or "").strip().lower()
    for prefix in _DOI_PREFIXES:
        if doi.startswith(prefix):
            doi = doi[len(prefix):]
            break
    return doi.strip().rstrip(".,;)")


def candidate_key(record: dict[str, Any]) -> str:
    """Stable dedup key: normalized DOI, else pmid:/epmc:, else a title slug."""
    doi = normalize_doi(record.get("doi") or "")
    if doi:
        return doi
    pmid = str(record.get("pmid") or "").strip()
    if pmid:
        return f"pmid:{pmid}"
    if str(record.get("source") or "") == "europepmc" and record.get("id"):
        return f"epmc:{record['id']}"
    title = re.sub(r"[^a-z0-9]+", "-", str(record.get("title") or "").lower()).strip("-")
    return f"title:{title[:80]}" if title else "unknown"


def filter_unseen(
    ledger: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split candidates into (unseen, already_covered) using the ledger's covered keys."""
    covered = set((ledger.get("covered") or {}).keys())
    unseen, seen = [], []
    for cand in candidates:
        key = candidate_key(cand)
        cand["_key"] = key
        (seen if key in covered else unseen).append(cand)
    return unseen, seen


def _covered_entry(record: dict[str, Any], episode_url: str, aired_at: str) -> dict[str, Any]:
    """Compact entry stored under ledger.covered[key] — no abstract text."""
    return {
        "title":       str(record.get("title") or "").strip(),
        "publication": str(record.get("publication") or record.get("journal") or "").strip(),
        "year":        record.get("year"),
        "doi":         normalize_doi(record.get("doi") or ""),
        "pmid":        str(record.get("pmid") or "").strip() or None,
        "url":         str(record.get("url") or "").strip(),
        "episode_url": episode_url,
        "aired_at":    aired_at,
    }


def record_episode(
    repo_root: Path,
    show_id: str,
    *,
    headline: dict[str, Any] | None,
    rounds: list[dict[str, Any]] | None = None,
    episode_url: str = "",
    window: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Mark headline + rounds papers as covered, then save the ledger atomically.

    Returns the updated ledger (for callers that want to log what was recorded).
    Soft-fails — anything missing a usable key is skipped with no exception so
    a single bad record never blocks publish bookkeeping.
    """
    ledger = load_ledger(repo_root, show_id)
    covered = dict(ledger.get("covered") or {})
    aired_at = datetime.now(timezone.utc).isoformat()

    recorded: list[str] = []
    for record in [headline, *(rounds or [])]:
        if not record or not isinstance(record, dict):
            continue
        key = candidate_key(record)
        if not key or key == "unknown" or key in covered:
            continue
        covered[key] = _covered_entry(record, episode_url, aired_at)
        recorded.append(key)

    ledger["covered"] = covered
    ledger["last_run"] = {
        "aired_at":  aired_at,
        "episode_url": episode_url,
        "recorded_keys": recorded,
        "window": window or {},
    }
    save_ledger(repo_root, show_id, ledger)
    return ledger
