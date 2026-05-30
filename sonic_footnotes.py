#!/usr/bin/env python3
"""Rights-aware sonic footnote catalog and planning helpers."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

CATALOG_NAME = "sonic_footnotes.json"

DEFAULT_POLICY = {
    "max_per_episode": 2,
    "max_duration_sec": 8,
    "allowed_license_families": ["public_domain", "cc0", "cc_by", "cc_by_sa"],
    "disallowed_license_families": ["cc_by_nc", "cc_by_nd", "unknown", "restricted"],
    "selection_rule": (
        "Use a sonic footnote only when it clarifies, demonstrates, or emotionally "
        "sharpens a specific beat. Silence is preferred over decoration."
    ),
    "script_rule": (
        "Do not include sound-effect markup in spoken script text. The plan is an "
        "editorial/mixing note saved to the manifest."
    ),
}

DEFAULT_SONIC_FOOTNOTES = {
    "schema_version": 1,
    "policy": DEFAULT_POLICY,
    "sources_reviewed": [
        {
            "name": "NASA Images and Media Guidelines",
            "url": "https://www.nasa.gov/nasa-brand-center/images-and-media/",
            "note": (
                "NASA audio/media are generally not subject to US copyright, but "
                "NASA should be acknowledged and third-party marked material is excluded."
            ),
        },
        {
            "name": "Wikimedia Commons licensing",
            "url": "https://commons.wikimedia.org/wiki/Commons:Licensing",
            "note": "Commons hosts public-domain and freely licensed media with per-file obligations.",
        },
        {
            "name": "Freesound licensing FAQ",
            "url": "https://freesound.org/help/faq/",
            "note": "Freesound includes CC0, CC BY, and CC BY-NC sounds; only CC0/CC BY are allowed here.",
        },
        {
            "name": "Internet Archive metadata",
            "url": "https://internetarchive.readthedocs.io/en/stable/metadata.html",
            "note": "Internet Archive item-level licenseurl and rights fields must be checked before use.",
        },
    ],
    "items": [
        {
            "id": "nasa_apollo_countdown",
            "label": "NASA Apollo countdown or mission control call",
            "source": "NASA",
            "source_url": "https://www.nasa.gov/audio-and-ringtones/",
            "license_family": "public_domain",
            "license_label": "NASA media guidelines",
            "credit": "Audio source: NASA",
            "status": "curated_source",
            "topics": ["space", "moon", "apollo", "launch", "engineering", "history"],
            "best_for": "A brief historical or engineering beat where a real mission-control texture matters.",
            "avoid_when": "The topic is only metaphorically about launching or exploration.",
            "suggested_search": "Apollo 11 countdown NASA audio",
        },
        {
            "id": "nasa_mars_wind",
            "label": "NASA Mars wind or rover environmental audio",
            "source": "NASA",
            "source_url": "https://www.nasa.gov/audio-and-ringtones/",
            "license_family": "public_domain",
            "license_label": "NASA media guidelines",
            "credit": "Audio source: NASA",
            "status": "curated_source",
            "topics": ["mars", "planetary science", "space", "weather", "robotics"],
            "best_for": "A moment that needs the listener to feel a remote environment, not just hear facts.",
            "avoid_when": "The episode already has enough atmosphere from music or narration.",
            "suggested_search": "NASA Mars wind audio",
        },
        {
            "id": "nasa_jupiter_radio",
            "label": "NASA planetary radio emission sonification",
            "source": "NASA",
            "source_url": "https://www.nasa.gov/audio-and-ringtones/",
            "license_family": "public_domain",
            "license_label": "NASA media guidelines",
            "credit": "Audio source: NASA",
            "status": "curated_source",
            "topics": ["jupiter", "radio", "magnetosphere", "space", "sonification"],
            "best_for": "A demonstration beat about translating data into audible form.",
            "avoid_when": "The script would imply it is literal audible sound in space without explanation.",
            "suggested_search": "NASA Jupiter radio emissions audio",
        },
        {
            "id": "commons_morse_code",
            "label": "Morse code signal",
            "source": "Wikimedia Commons",
            "source_url": "https://commons.wikimedia.org/wiki/Category:Morse_code_audio_files",
            "license_family": "cc_by",
            "license_label": "Per-file Commons license required",
            "credit": "Credit per selected Wikimedia Commons file",
            "status": "requires_file_verification",
            "topics": ["telegraph", "radio", "communication", "signals", "history"],
            "best_for": "A short signal-processing or communication-history flourish.",
            "avoid_when": "No specific file has been chosen and attributed.",
            "suggested_search": "Wikimedia Commons Morse code audio CC BY",
        },
        {
            "id": "commons_metronome",
            "label": "Metronome tick",
            "source": "Wikimedia Commons",
            "source_url": "https://commons.wikimedia.org/wiki/Category:Metronomes",
            "license_family": "cc_by",
            "license_label": "Per-file Commons license required",
            "credit": "Credit per selected Wikimedia Commons file",
            "status": "requires_file_verification",
            "topics": ["music", "time", "rhythm", "metronome", "measurement"],
            "best_for": "A timing/rhythm beat where an audible tick explains the concept faster than words.",
            "avoid_when": "It would become a cute but distracting joke.",
            "suggested_search": "Wikimedia Commons metronome audio",
        },
        {
            "id": "commons_tuning_fork",
            "label": "Tuning fork tone",
            "source": "Wikimedia Commons",
            "source_url": "https://commons.wikimedia.org/wiki/Category:Audio_files_of_tuning_forks",
            "license_family": "cc_by",
            "license_label": "Per-file Commons license required",
            "credit": "Credit per selected Wikimedia Commons file",
            "status": "requires_file_verification",
            "topics": ["sound", "frequency", "music", "physics", "hearing"],
            "best_for": "A physics or music beat that benefits from hearing pitch stability.",
            "avoid_when": "The final audio will already include generated music in the same frequency range.",
            "suggested_search": "Wikimedia Commons tuning fork audio",
        },
        {
            "id": "freesound_cc0_field_recording",
            "label": "CC0 field recording from Freesound",
            "source": "Freesound",
            "source_url": "https://freesound.org/",
            "license_family": "cc0",
            "license_label": "Must verify selected file is CC0",
            "credit": "Credit optional for CC0, but keep source metadata in manifest",
            "status": "requires_file_verification",
            "topics": ["nature", "city", "machines", "ambience", "field recording"],
            "best_for": "A real-world place or machine texture when a CC0 file is selected.",
            "avoid_when": "A file is CC BY-NC or license metadata is missing.",
            "suggested_search": "Freesound CC0 field recording",
        },
        {
            "id": "internet_archive_public_domain",
            "label": "Public-domain archival audio from Internet Archive",
            "source": "Internet Archive",
            "source_url": "https://archive.org/details/audio",
            "license_family": "public_domain",
            "license_label": "Must verify item rights metadata",
            "credit": "Credit per selected Internet Archive item",
            "status": "requires_item_verification",
            "topics": ["history", "speech", "archive", "radio", "public domain"],
            "best_for": "A historical episode where a specific archival recording is materially relevant.",
            "avoid_when": "Rights metadata is unclear or the clip is merely decorative.",
            "suggested_search": "Internet Archive public domain audio",
        },
    ],
}


def _catalog_path(repo_root: Path, catalog_path: str | Path | None = None) -> Path:
    raw = Path(str(catalog_path or CATALOG_NAME))
    return raw if raw.is_absolute() else repo_root / raw


def ensure_sonic_footnotes_catalog(
    repo_root: Path,
    catalog_path: str | Path | None = None,
) -> Path:
    path = _catalog_path(repo_root, catalog_path)
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(DEFAULT_SONIC_FOOTNOTES, indent=2, sort_keys=True)
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
    return path


def load_sonic_footnotes_catalog(repo_root: Path, cfg: dict) -> tuple[dict, Path]:
    path = ensure_sonic_footnotes_catalog(
        repo_root,
        cfg.get("sonic_footnotes_catalog", CATALOG_NAME),
    )
    try:
        catalog = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(catalog, dict):
            raise ValueError("catalog root is not an object")
    except (OSError, json.JSONDecodeError, ValueError):
        catalog = json.loads(json.dumps(DEFAULT_SONIC_FOOTNOTES))
    catalog.setdefault("policy", DEFAULT_POLICY)
    catalog.setdefault("items", [])
    return catalog, path


def sonic_footnote_policy(catalog: dict) -> dict:
    policy = dict(DEFAULT_POLICY)
    if isinstance(catalog.get("policy"), dict):
        policy.update(catalog["policy"])
    return policy


def compact_sonic_footnote_catalog(catalog: dict, max_items: int = 18) -> list[dict]:
    policy = sonic_footnote_policy(catalog)
    allowed = set(policy.get("allowed_license_families", []))
    disallowed = set(policy.get("disallowed_license_families", []))
    compact: list[dict] = []
    for item in catalog.get("items", [])[:max_items]:
        if not isinstance(item, dict):
            continue
        license_family = str(item.get("license_family", "unknown"))
        if license_family in disallowed or license_family not in allowed:
            continue
        compact.append(
            {
                "id": item.get("id"),
                "label": item.get("label"),
                "source": item.get("source"),
                "source_url": item.get("source_url"),
                "license_family": license_family,
                "license_label": item.get("license_label"),
                "status": item.get("status"),
                "topics": item.get("topics", []),
                "best_for": item.get("best_for"),
                "avoid_when": item.get("avoid_when"),
                "suggested_search": item.get("suggested_search"),
            }
        )
    return compact


def normalize_sonic_footnote_plan(
    plan: dict | None,
    catalog: dict,
    max_items: int | None = None,
) -> dict:
    policy = sonic_footnote_policy(catalog)
    limit = int(max_items or policy.get("max_per_episode", 2))
    max_duration = float(policy.get("max_duration_sec", 8))
    allowed_ids = {
        str(item.get("id"))
        for item in compact_sonic_footnote_catalog(catalog, max_items=999)
        if item.get("id")
    }

    if not isinstance(plan, dict):
        plan = {}
    cues = []
    for cue in plan.get("cues", []) or []:
        if not isinstance(cue, dict):
            continue
        catalog_id = str(cue.get("catalog_id") or cue.get("id") or "").strip()
        if catalog_id not in allowed_ids:
            continue
        try:
            duration = min(float(cue.get("duration_sec", max_duration)), max_duration)
        except (TypeError, ValueError):
            duration = max_duration
        cues.append(
            {
                "catalog_id": catalog_id,
                "placement": str(cue.get("placement") or ""),
                "beat": str(cue.get("beat") or ""),
                "duration_sec": round(max(0.5, duration), 2),
                "reason": str(cue.get("reason") or ""),
                "script_note": str(cue.get("script_note") or ""),
                "license_note": str(cue.get("license_note") or ""),
            }
        )
        if len(cues) >= limit:
            break

    decision = "use" if cues else "skip"
    return {
        "decision": str(plan.get("decision") or decision),
        "rationale": str(plan.get("rationale") or ""),
        "cues": cues,
        "policy": policy,
    }


def sonic_footnote_attributions(cues: list[dict], catalog: dict) -> list[str]:
    by_id = {
        str(item.get("id")): item
        for item in catalog.get("items", [])
        if isinstance(item, dict) and item.get("id")
    }
    attributions: list[str] = []
    for cue in cues:
        item = by_id.get(str(cue.get("catalog_id")))
        if not item:
            continue
        credit = str(item.get("credit") or item.get("source") or "").strip()
        label = str(item.get("label") or item.get("id") or "").strip()
        license_label = str(item.get("license_label") or item.get("license_family") or "").strip()
        source_url = str(item.get("source_url") or "").strip()
        parts = [label, credit, license_label]
        if source_url:
            parts.append(source_url)
        attributions.append(" - ".join(p for p in parts if p))
    return attributions
