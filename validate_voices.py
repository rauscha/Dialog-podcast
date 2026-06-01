#!/usr/bin/env python3
"""Validate every configured host + guest voice ID against its provider's API.

These are read-only metadata lookups (no speech synthesis), so the check costs
nothing and simply confirms each ID resolves to a real, accessible voice and
prints its human-readable name. Loads `.env` + `config.json` like compare_tts.py.

Endpoints:
    ElevenLabs  GET https://api.elevenlabs.io/v1/voices/{voice_id}   (header: xi-api-key)
    Cartesia    GET https://api.cartesia.ai/voices/{id}              (Bearer + Cartesia-Version)

Usage:
    python validate_voices.py            # validate all configured IDs
    python validate_voices.py elevenlabs # just one provider
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _load_dotenv(path: Path = Path(".env")) -> None:
    """Minimal .env loader (does not overwrite already-set env vars)."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()

import requests  # noqa: E402 — env must be loaded first


def _csv(value: object) -> list[str]:
    return [s.strip() for s in str(value or "").split(",") if s.strip()]


def _load_cfg() -> dict:
    path = Path("config.json")
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def check_elevenlabs(voice_id: str, api_key: str, timeout: int = 30) -> tuple[bool, str]:
    url = f"https://api.elevenlabs.io/v1/voices/{voice_id}"
    try:
        resp = requests.get(url, headers={"xi-api-key": api_key}, timeout=timeout)
    except requests.RequestException as exc:
        return False, f"request error: {exc}"
    if resp.status_code == 200:
        try:
            return True, str(resp.json().get("name") or "(unnamed)")
        except ValueError:
            return True, "(200, body unparsed)"
    return False, f"HTTP {resp.status_code}: {resp.text[:140]}"


def check_cartesia(voice_id: str, api_key: str, version: str, timeout: int = 30) -> tuple[bool, str]:
    url = f"https://api.cartesia.ai/voices/{voice_id}"
    headers = {"Authorization": f"Bearer {api_key}", "Cartesia-Version": version}
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        return False, f"request error: {exc}"
    if resp.status_code == 200:
        try:
            return True, str(resp.json().get("name") or "(unnamed)")
        except ValueError:
            return True, "(200, body unparsed)"
    return False, f"HTTP {resp.status_code}: {resp.text[:140]}"


def main() -> int:
    cfg = _load_cfg()
    requested = {a.lower() for a in sys.argv[1:]} or {"elevenlabs", "cartesia"}

    el_key = os.environ.get("ELEVENLABS_API_KEY", "")
    car_key = os.environ.get("CARTESIA_API_KEY", "")
    car_version = str(cfg.get("cartesia_version") or "2026-03-01")

    rows: list[tuple[str, str, str, bool, str]] = []  # provider, role, id, ok, detail

    if "elevenlabs" in requested:
        targets: list[tuple[str, str]] = []
        if cfg.get("elevenlabs_voice_id_a"):
            targets.append(("HOST A / Juno", str(cfg["elevenlabs_voice_id_a"])))
        if cfg.get("elevenlabs_voice_id_b"):
            targets.append(("HOST B / Caspar", str(cfg["elevenlabs_voice_id_b"])))
        for i, vid in enumerate(_csv(cfg.get("elevenlabs_guest_voice_ids"))):
            targets.append((f"guest {i + 1}", vid))
        for role, vid in targets:
            if not el_key:
                rows.append(("elevenlabs", role, vid, False, "ELEVENLABS_API_KEY not set"))
            else:
                ok, detail = check_elevenlabs(vid, el_key)
                rows.append(("elevenlabs", role, vid, ok, detail))

    if "cartesia" in requested:
        targets = []
        if cfg.get("cartesia_voice_id_a"):
            targets.append(("HOST A", str(cfg["cartesia_voice_id_a"])))
        if cfg.get("cartesia_voice_id_b"):
            targets.append(("HOST B", str(cfg["cartesia_voice_id_b"])))
        for i, vid in enumerate(_csv(cfg.get("cartesia_guest_voice_ids"))):
            targets.append((f"guest {i + 1}", vid))
        for role, vid in targets:
            if not car_key:
                rows.append(("cartesia", role, vid, False, "CARTESIA_API_KEY not set"))
            else:
                ok, detail = check_cartesia(vid, car_key, car_version)
                rows.append(("cartesia", role, vid, ok, detail))

    print(f"{'PROVIDER':<12}{'ROLE':<18}{'STATUS':<7}ID  ->  NAME / ERROR")
    print("-" * 104)
    ok_count = 0
    for provider, role, vid, ok, detail in rows:
        if ok:
            ok_count += 1
        print(f"{provider:<12}{role:<18}{'OK' if ok else 'FAIL':<7}{vid}  ->  {detail}")
    print("-" * 104)
    print(f"{ok_count}/{len(rows)} voice IDs valid")
    return 0 if rows and ok_count == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
