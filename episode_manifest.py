#!/usr/bin/env python3
"""Durable episode metadata for Asynchronous generation runs."""

from __future__ import annotations

import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
MANIFEST_NAME = "episode_manifest.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def slugify_topic(topic: str, max_len: int = 60) -> str:
    slug = re.sub(r"[^\w\-]+", "_", topic.strip().lower())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return (slug[:max_len].strip("_") or "episode")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return value


class EpisodeManifest:
    """Small JSON-backed state object written throughout an episode run."""

    def __init__(self, path: Path, data: dict[str, Any]) -> None:
        self.path = path
        self.data = data

    @classmethod
    def create(
        cls,
        path: Path,
        *,
        run_id: str,
        topic: str,
        slug: str,
        options: dict[str, Any],
        models: dict[str, Any],
    ) -> "EpisodeManifest":
        now = utc_now()
        data: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "topic": topic,
            "slug": slug,
            "created_at": now,
            "updated_at": now,
            "status": "running",
            "stage": "queued",
            "options": _jsonable(options),
            "models": _jsonable(models),
            "paths": {},
            "metrics": {},
            "sources": [],
            "claims": [],
            "clips": [],
            "audio": {},
            "publish": {},
            "warnings": [],
            "errors": [],
            "events": [],
        }
        manifest = cls(path, data)
        manifest.add_event("created", {"stage": "queued"})
        manifest.save()
        return manifest

    @classmethod
    def load(cls, path: Path) -> "EpisodeManifest":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(path, data)

    def save(self) -> None:
        self.data["updated_at"] = utc_now()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(_jsonable(self.data), indent=2, sort_keys=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.path.parent,
            delete=False,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
        ) as tmp:
            tmp.write(payload)
            tmp.write("\n")
            tmp_path = Path(tmp.name)
        tmp_path.replace(self.path)

    def add_event(self, event: str, details: dict[str, Any] | None = None) -> None:
        self.data.setdefault("events", []).append(
            {
                "at": utc_now(),
                "event": event,
                "details": _jsonable(details or {}),
            }
        )

    def set_stage(self, stage: str, status: str = "running") -> None:
        self.data["stage"] = stage
        self.data["status"] = status
        self.add_event("stage", {"stage": stage, "status": status})
        self.save()

    def set_path(self, key: str, value: str | Path) -> None:
        self.data.setdefault("paths", {})[key] = str(value)
        self.save()

    def set_metric(self, key: str, value: Any) -> None:
        self.data.setdefault("metrics", {})[key] = _jsonable(value)
        self.save()

    def set_sources(self, sources: list[str]) -> None:
        self.data["sources"] = list(sources)
        self.set_metric("source_count", len(sources))
        self.save()

    def set_clips(self, clips: list[Any]) -> None:
        self.data["clips"] = _jsonable(clips)
        self.save()

    def set_audio(
        self,
        path: str | Path,
        *,
        duration_sec: float | None = None,
        file_size: int | None = None,
    ) -> None:
        audio = {"path": str(path)}
        if duration_sec is not None:
            audio["duration_sec"] = round(float(duration_sec), 2)
        if file_size is not None:
            audio["file_size"] = int(file_size)
        self.data["audio"] = audio
        self.save()

    def set_publish(self, **values: Any) -> None:
        self.data.setdefault("publish", {}).update(_jsonable(values))
        self.save()

    def add_warning(self, message: str, *, stage: str | None = None) -> None:
        self.data.setdefault("warnings", []).append(
            {"at": utc_now(), "stage": stage or self.data.get("stage"), "message": message}
        )
        self.save()

    def fail(self, stage: str | None, exc: BaseException | str) -> None:
        self.data["status"] = "failed"
        if stage:
            self.data["stage"] = stage
        self.data.setdefault("errors", []).append(
            {
                "at": utc_now(),
                "stage": stage or self.data.get("stage"),
                "type": exc.__class__.__name__ if isinstance(exc, BaseException) else "Error",
                "message": str(exc),
            }
        )
        self.add_event("failed", {"stage": self.data.get("stage")})
        self.save()

    def complete(self) -> None:
        self.data["status"] = "completed"
        self.data["stage"] = "completed"
        self.add_event("completed", {})
        self.save()

    def cancel(self, message: str = "Generation was cancelled.") -> None:
        previous_stage = self.data.get("stage")
        self.data["status"] = "cancelled"
        self.data["stage"] = "cancelled"
        self.data.setdefault("warnings", []).append(
            {"at": utc_now(), "stage": previous_stage, "message": message}
        )
        self.add_event("cancelled", {"previous_stage": previous_stage})
        self.save()

    def durable_path(self, output_dir: Path) -> Path:
        """Stable location for this manifest that survives work-dir cleanup.

        Sibling to the published audio when known (``<audio_stem>.manifest.json``),
        otherwise keyed by run id under the output dir.
        """
        audio_path = (self.data.get("audio") or {}).get("path")
        if audio_path:
            stem = Path(audio_path).stem
        else:
            run_id = self.data.get("run_id") or "episode"
            slug = self.data.get("slug") or "episode"
            stem = f"{run_id}_{slug}"
        return output_dir / f"{stem}.manifest.json"

    def persist_durable(self, output_dir: Path) -> Path:
        """Copy this manifest to its durable location and return the path.

        The per-run ``_work`` dir (and the manifest inside it) is deleted on a
        successful run, so any "latest manifest" lookup would otherwise fall back
        to a stale survivor from an earlier run. This keeps a copy that outlives
        cleanup so consumers report on the run that just finished.
        """
        dest = self.durable_path(output_dir)
        dest.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(_jsonable(self.data), indent=2, sort_keys=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=dest.parent,
            delete=False,
            prefix=f".{dest.name}.",
            suffix=".tmp",
        ) as tmp:
            tmp.write(payload)
            tmp.write("\n")
            tmp_path = Path(tmp.name)
        tmp_path.replace(dest)
        return dest

    def to_summary(self) -> dict[str, Any]:
        return {
            "run_id": self.data.get("run_id"),
            "topic": self.data.get("topic"),
            "title": self.data.get("title"),
            "status": self.data.get("status"),
            "stage": self.data.get("stage"),
            "episode_type": self.data.get("options", {}).get("episode_type")
            or self.data.get("metrics", {}).get("episode_type"),
            "episode_type_label": self.data.get("options", {}).get("episode_type_label")
            or self.data.get("metrics", {}).get("episode_type_label"),
            "created_at": self.data.get("created_at"),
            "updated_at": self.data.get("updated_at"),
            "audio_path": self.data.get("audio", {}).get("path"),
            "duration_sec": self.data.get("audio", {}).get("duration_sec"),
            "word_count": self.data.get("metrics", {}).get("word_count"),
            "guest_count": self.data.get("metrics", {}).get("guest_count"),
            "source_count": self.data.get("metrics", {}).get("source_count"),
            "warnings": len(self.data.get("warnings", [])),
            "errors": len(self.data.get("errors", [])),
        }


def find_latest_manifest(
    repo_root: Path,
    output_dir: str = "episodes",
) -> EpisodeManifest | None:
    episodes_dir = repo_root / output_dir
    if not episodes_dir.exists():
        return None
    # Durable sidecars (written before work-dir cleanup) first, then in-flight
    # work-dir manifests as a fallback for runs still in progress.
    manifests = sorted(
        [
            *episodes_dir.glob("*.manifest.json"),
            *episodes_dir.glob(f"*_work/{MANIFEST_NAME}"),
        ],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for path in manifests:
        try:
            return EpisodeManifest.load(path)
        except (OSError, json.JSONDecodeError):
            continue
    return None
