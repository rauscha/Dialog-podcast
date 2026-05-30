#!/usr/bin/env python3
"""Cross-process generation lock and cancellation helpers."""

from __future__ import annotations

import contextlib
import ctypes
import json
import os
import signal
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

LOCK_DIR = ".runtime"
LOCK_FILE = "generation.lock"


class JobAlreadyRunning(RuntimeError):
    def __init__(self, lock_data: dict[str, Any]) -> None:
        self.lock_data = lock_data
        topic = lock_data.get("topic", "(unknown topic)")
        pid = lock_data.get("pid", "?")
        super().__init__(f"Generation already running for {topic!r} (pid {pid})")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def lock_path(repo_root: Path) -> Path:
    return repo_root / LOCK_DIR / LOCK_FILE


def read_lock(repo_root: Path) -> dict[str, Any] | None:
    path = lock_path(repo_root)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _is_pid_running_windows(pid: int) -> bool:
    kernel32 = ctypes.windll.kernel32
    process_query = 0x1000
    synchronize = 0x00100000
    wait_timeout = 0x00000102
    handle = kernel32.OpenProcess(process_query | synchronize, False, pid)
    if not handle:
        return False
    try:
        return kernel32.WaitForSingleObject(handle, 0) == wait_timeout
    finally:
        kernel32.CloseHandle(handle)


def is_pid_running(pid: int | str | None) -> bool:
    try:
        pid_int = int(pid or 0)
    except (TypeError, ValueError):
        return False
    if pid_int <= 0:
        return False
    if os.name == "nt":
        return _is_pid_running_windows(pid_int)
    try:
        os.kill(pid_int, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def active_lock(repo_root: Path) -> dict[str, Any] | None:
    data = read_lock(repo_root)
    if not data:
        return None
    if is_pid_running(data.get("pid")):
        data["alive"] = True
        return data
    with contextlib.suppress(OSError):
        lock_path(repo_root).unlink()
    return None


@contextlib.contextmanager
def acquire_generation_lock(
    repo_root: Path,
    *,
    run_id: str,
    topic: str,
) -> Iterator[dict[str, Any]]:
    path = lock_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing = active_lock(repo_root)
    if existing:
        raise JobAlreadyRunning(existing)

    data = {
        "pid": os.getpid(),
        "run_id": run_id,
        "topic": topic,
        "started_at": _utc_now(),
        "repo_root": str(repo_root),
    }

    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        existing = active_lock(repo_root)
        if existing:
            raise JobAlreadyRunning(existing)
        with contextlib.suppress(OSError):
            path.unlink()
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)

    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")

    try:
        yield data
    finally:
        current = read_lock(repo_root)
        if (
            current
            and current.get("pid") == os.getpid()
            and current.get("run_id") == run_id
        ):
            with contextlib.suppress(OSError):
                path.unlink()


def get_status(repo_root: Path) -> dict[str, Any] | None:
    data = active_lock(repo_root)
    if not data:
        return None
    return data


def cancel_active_job(repo_root: Path) -> tuple[bool, str]:
    data = active_lock(repo_root)
    if not data:
        return False, "No active generation found."

    pid = int(data["pid"])
    if os.name == "nt":
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode != 0:
            return False, result.stderr.strip() or result.stdout.strip()
    else:
        os.kill(pid, signal.SIGTERM)

    with contextlib.suppress(OSError):
        lock_path(repo_root).unlink()
    return True, f"Cancelled generation process {pid}."
