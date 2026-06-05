#!/usr/bin/env python3
"""Resolve and splice rights-aware sonic footnotes into a Dialog episode.

The companion to sonic_footnotes.py (planner + catalog). This module takes a
planner-produced `sonic_footnote_plan` plus the final dialogue script, maps
each cue to a specific turn boundary, resolves the cue to a real licensed
audio file, downloads and trims it, and returns a list of ResolvedFootnote
records that the audio assembler can splice into the per-turn MP3 sequence.

Phase 1 supports the NASA backend (curated_source items via NASA's
images-api.nasa.gov search). Other backends raise NotImplementedError so the
dispatcher can fall through and the cue is silently dropped.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import anthropic

logger = logging.getLogger(__name__)

_PLACEMENT_MODEL = "claude-sonnet-4-6"

_NASA_SEARCH_URL = "https://images-api.nasa.gov/search"
_NASA_USER_AGENT = "Dialog-podcast/1.0 (+https://github.com/rauscha/Dialog-podcast)"
_HTTP_TIMEOUT_SEC = 30

# Re-implementation of generate_podcast.py:_TURN_RE so we don't form a circular
# import. Keep these in sync if the upstream regex ever changes.
_TURN_RE = re.compile(r"^([A-Z][A-Z ]*)(?:\s*\[([^\]]*)\])?\s*:\s*(.*)")


@dataclass
class ResolvedFootnote:
    catalog_id: str
    audio_path: Path
    duration_sec: float
    attribution: str
    source_url: str
    after_turn: int


# ── Turn parsing (mirrors generate_podcast._parse_dialogue_turns) ─────────────

def _enumerate_turns(
    script: str,
    known_speakers: set[str] | None = None,
) -> list[tuple[int, str, str]]:
    """Return [(turn_index, speaker_label, text), ...].

    turn_index is the position in the parsed turn list (0-indexed). Empty-text
    turns are dropped, matching the TTS pipeline.

    When known_speakers is provided, turns with unrecognised labels are skipped
    so the count matches generate_podcast._parse_dialogue_turns exactly.
    """
    turns: list[tuple[int, str, str]] = []
    current_label: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        if current_label and current_lines:
            text = " ".join(current_lines).strip()
            if text:
                turns.append((len(turns), current_label, text))

    for line in script.splitlines():
        m = _TURN_RE.match(line)
        if m:
            flush()
            label = m.group(1).strip().upper()
            if known_speakers is not None and label not in known_speakers:
                current_label = None
                current_lines = []
                continue
            current_label = label
            rest = m.group(3).strip()
            current_lines = [rest] if rest else []
        elif current_label is not None:
            stripped = line.strip()
            if stripped:
                current_lines.append(stripped)

    flush()
    return turns


# ── Cue-to-turn placement (LLM pass) ──────────────────────────────────────────

_PLACEMENT_SYSTEM = """\
You map sonic footnote cues to specific dialogue turn boundaries.

The script is a JUNO/CASPAR dialogue. Turns are numbered 0, 1, 2, ... in order.

For each cue in the plan, decide which turn it should follow. The cue plays
immediately AFTER the chosen turn concludes, before the next speaker begins.

Return JSON only:
{
  "placements": [
    {"catalog_id": "...", "after_turn": 7}
  ]
}

Rules:
- after_turn is 0-indexed.
- Pick the placement that best matches the cue's `placement` and `beat` text.
- One cue per turn boundary at most; if two cues collide, prefer the earlier
  one in the plan.
- If no good fit exists for a cue, omit it (silently drop).
- Never place a cue after the final turn.
"""


def _extract_json_object(text: str) -> dict:
    """Extract the first top-level JSON object from a Sonnet response."""
    if not text:
        return {}
    start = text.find("{")
    if start < 0:
        return {}
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return {}
    return {}


def _place_cues(
    script: str,
    plan: dict,
    client: anthropic.Anthropic,
    known_speakers: set[str] | None = None,
) -> dict[str, int]:
    """Ask Sonnet which turn each cue should follow. Returns {catalog_id: after_turn}."""
    cues = plan.get("cues", []) or []
    if not cues:
        return {}

    turns = _enumerate_turns(script, known_speakers)
    if len(turns) < 2:
        return {}

    last_valid_turn = len(turns) - 2  # never place after the final turn

    numbered_script_lines: list[str] = []
    for idx, label, text in turns:
        snippet = text if len(text) <= 220 else text[:217] + "..."
        numbered_script_lines.append(f"[turn {idx}] {label}: {snippet}")
    numbered_script = "\n".join(numbered_script_lines)

    cue_summary = []
    for cue in cues:
        if not isinstance(cue, dict):
            continue
        cue_summary.append({
            "catalog_id": cue.get("catalog_id"),
            "beat": cue.get("beat"),
            "placement": cue.get("placement"),
            "reason": cue.get("reason"),
        })

    user_msg = (
        f"Numbered dialogue:\n{numbered_script}\n\n"
        f"Cues to place:\n{json.dumps(cue_summary, indent=2)}\n\n"
        f"Valid after_turn range: 0 to {last_valid_turn}."
    )

    try:
        resp = client.messages.create(
            model=_PLACEMENT_MODEL,
            max_tokens=512,
            system=_PLACEMENT_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
    except anthropic.APIError as exc:
        logger.warning("[footnote] Placement pass failed: %s", exc)
        return {}

    raw = "\n".join(b.text for b in resp.content if hasattr(b, "text")).strip()
    payload = _extract_json_object(raw)

    placements: dict[str, int] = {}
    used_turns: set[int] = set()
    for entry in payload.get("placements", []) or []:
        if not isinstance(entry, dict):
            continue
        cid = str(entry.get("catalog_id") or "").strip()
        try:
            after = int(entry.get("after_turn"))
        except (TypeError, ValueError):
            continue
        if not cid or after < 0 or after > last_valid_turn:
            continue
        if after in used_turns or cid in placements:
            continue
        placements[cid] = after
        used_turns.add(after)
    return placements


# ── NASA backend ─────────────────────────────────────────────────────────────

def _http_get_json(url: str) -> dict | None:
    req = urllib.request.Request(url, headers={"User-Agent": _NASA_USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SEC) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        logger.warning("[footnote] HTTP GET failed for %s: %s", url, exc)
        return None


def _search_nasa_audio(query: str, max_results: int = 5) -> list[dict]:
    params = urllib.parse.urlencode({"q": query, "media_type": "audio"})
    payload = _http_get_json(f"{_NASA_SEARCH_URL}?{params}")
    if not payload:
        return []
    items = payload.get("collection", {}).get("items", []) or []
    # Filter out podcast episodes — they contain long intro/outro sections
    # rather than the primary audio asset we need (countdown, wind recording, etc.)
    items = [i for i in items if not _is_nasa_podcast_item(i)]
    return items[:max_results]


def _pick_nasa_audio_url(collection_url: str) -> str | None:
    """Given a NASA collection.json URL, pick the best playable MP3."""
    payload = _http_get_json(collection_url)
    if not isinstance(payload, list):
        return None
    # NASA convention: ~orig.mp3 highest fidelity, ~128k.mp3 smaller, also m4a.
    mp3_urls = [u for u in payload if isinstance(u, str) and u.lower().endswith(".mp3")]
    if not mp3_urls:
        return None
    # Prefer compressed (smaller, faster) when both exist.
    for u in mp3_urls:
        if "~128k" in u:
            return u
    return mp3_urls[0]


def _nasa_query_fallbacks(query: str) -> list[str]:
    """Progressive shortening — NASA's API rejects longer compound queries.

    e.g. "NASA Mars wind audio" -> [full, "NASA Mars wind", "NASA Mars"].
    Drops trailing words first; also strips a leading "NASA" if present after
    other shortenings, since that prefix sometimes over-narrows results.

    Minimum 2 words: single-word queries are too broad and tend to match
    podcast episodes rather than primary audio assets.
    """
    words = [w for w in query.split() if w]
    seen: set[str] = set()
    variants: list[str] = []
    while len(words) >= 2:            # ← 2-word minimum — stops degenerate hits
        candidate = " ".join(words)
        if candidate not in seen:
            seen.add(candidate)
            variants.append(candidate)
        words.pop()
    # Also try without a leading "NASA" prefix
    extras: list[str] = []
    for v in variants:
        if v.lower().startswith("nasa ") and v[5:].strip():
            tail = v[5:].strip()
            if tail not in seen and len(tail.split()) >= 2:
                seen.add(tail)
                extras.append(tail)
    return variants + extras


# Words that indicate a NASA item is a podcast episode rather than a
# primary audio asset (countdown audio, environmental recording, etc.).
_PODCAST_TITLE_RE = re.compile(
    r"\bpodcast\b|\bepisode\s*\d|\bep\.\s*\d|\bhoustonwearegoingback\b"
    r"|\bnasa explorers\b|\bshort sharp science\b",
    re.IGNORECASE,
)


def _is_nasa_podcast_item(item: dict) -> bool:
    """Return True if the NASA search result looks like a podcast episode."""
    data = item.get("data") or []
    if not data or not isinstance(data, list):
        return False
    first = data[0] if isinstance(data[0], dict) else {}
    title = str(first.get("title") or "")
    description = str(first.get("description") or "")
    return bool(
        _PODCAST_TITLE_RE.search(title)
        or _PODCAST_TITLE_RE.search(description[:300])
    )


def _resolve_nasa(cue: dict, catalog_item: dict) -> str | None:
    """Search NASA, pick a result, return its audio URL (ffmpeg-fetchable)."""
    query = str(catalog_item.get("suggested_search") or "").strip()
    if not query:
        return None

    items: list[dict] = []
    for candidate in _nasa_query_fallbacks(query):
        items = _search_nasa_audio(candidate)
        if items:
            if candidate != query:
                logger.info("[footnote] NASA fallback query hit: %r", candidate)
            break
    if not items:
        logger.warning("[footnote] NASA search returned no non-podcast items for %r", query)
        return None

    for item in items:
        collection_href = item.get("href")
        if not isinstance(collection_href, str):
            continue
        audio_url = _pick_nasa_audio_url(collection_href)
        if audio_url:
            # NASA serves http:// in collection.json; upgrade to https for transit.
            if audio_url.startswith("http://"):
                audio_url = "https://" + audio_url[len("http://"):]
            return audio_url
    return None


# ── Audio trim / fade ────────────────────────────────────────────────────────

# Phase 1 heuristic: skip likely silence/intro at the very start of long NASA
# files. Cue moment selection (finding the actual countdown within a 30-min
# episode) is deferred to Phase 1.5.
_DEFAULT_START_OFFSET_SEC = 5.0
_FADE_SEC = 0.4


def _trim_and_fade(
    input_source: str,
    output_path: Path,
    duration_sec: float,
    start_offset_sec: float = _DEFAULT_START_OFFSET_SEC,
) -> bool:
    """Trim to duration_sec starting at start_offset_sec, with fade in/out.

    input_source may be a local path or an http(s) URL — ffmpeg handles both.
    Using a remote URL leverages range requests so we don't download the full
    file (NASA podcasts can be 30–80 MB just to get a 5-second window).
    """
    duration_sec = max(0.5, float(duration_sec))
    fade_out_start = max(0.0, duration_sec - _FADE_SEC)
    af = (
        f"afade=t=in:st=0:d={_FADE_SEC},"
        f"afade=t=out:st={fade_out_start}:d={_FADE_SEC}"
    )
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_offset_sec),
        "-t", str(duration_sec),
        "-user_agent", _NASA_USER_AGENT,
        "-i", str(input_source),
        "-af", af,
        "-ar", "44100", "-ac", "2",
        "-c:a", "libmp3lame", "-b:a", "192k",
        str(output_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        logger.warning("[footnote] ffmpeg trim timed out for %s", output_path.name)
        return False
    if result.returncode != 0 or not output_path.exists():
        logger.warning("[footnote] ffmpeg trim failed: %s", result.stderr[:200])
        return False
    return True


def _audio_duration_sec(path: Path) -> float:
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return 0.0
    try:
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])
    except (json.JSONDecodeError, KeyError, ValueError):
        return 0.0


# ── Resolver dispatch ────────────────────────────────────────────────────────

def _catalog_item(catalog: dict, catalog_id: str) -> dict | None:
    for item in catalog.get("items", []) or []:
        if isinstance(item, dict) and str(item.get("id") or "") == catalog_id:
            return item
    return None


def _attribution_for(item: dict, source_url: str) -> str:
    label = str(item.get("label") or item.get("id") or "").strip()
    credit = str(item.get("credit") or item.get("source") or "").strip()
    license_label = str(item.get("license_label") or item.get("license_family") or "").strip()
    parts = [label, credit, license_label]
    if source_url:
        parts.append(source_url)
    return " - ".join(p for p in parts if p)


def _resolve_cue(
    cue: dict,
    catalog: dict,
    after_turn: int,
    work_dir: Path,
) -> ResolvedFootnote | None:
    catalog_id = str(cue.get("catalog_id") or "").strip()
    item = _catalog_item(catalog, catalog_id)
    if not item:
        return None

    source = str(item.get("source") or "").strip().lower()
    if source == "nasa":
        source_url = _resolve_nasa(cue, item)
    else:
        # Phase 2-4: Wikimedia, Internet Archive, Freesound — not yet implemented.
        logger.warning(
            "[footnote] Cue %r skipped — backend %r not yet implemented "
            "(Phase 2-4 work required).",
            catalog_id, source,
        )
        return None

    if not source_url:
        return None

    trimmed_path = work_dir / f"footnote_{catalog_id}.mp3"
    duration = float(cue.get("duration_sec", 5.0))
    if not _trim_and_fade(source_url, trimmed_path, duration):
        return None

    actual_duration = _audio_duration_sec(trimmed_path)

    return ResolvedFootnote(
        catalog_id=catalog_id,
        audio_path=trimmed_path,
        duration_sec=actual_duration,
        attribution=_attribution_for(item, source_url),
        source_url=source_url,
        after_turn=after_turn,
    )


# ── Public entry point ───────────────────────────────────────────────────────

def prepare_footnotes(
    script: str,
    plan: dict,
    catalog: dict,
    cfg: dict,
    work_dir: Path,
    client: anthropic.Anthropic | None = None,
) -> list[ResolvedFootnote]:
    """Place each planned cue, resolve and download audio, return ready-to-splice records.

    Failures (no API, no search results, ffmpeg error) silently drop the cue —
    the episode still ships, just without that particular footnote.
    """
    cues = plan.get("cues", []) or []
    if not cues or plan.get("decision") == "skip":
        return []

    work_dir.mkdir(parents=True, exist_ok=True)

    if client is None:
        try:
            import os
            client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        except KeyError:
            logger.warning("[footnote] ANTHROPIC_API_KEY not set; cannot place cues")
            return []

    # Build known-speaker set from cfg — mirrors generate_podcast._known_speaker_labels
    # so _enumerate_turns counts turns the same way _parse_dialogue_turns does.
    host_a = str(cfg.get("host_a_name") or "Juno").upper()
    host_b = str(cfg.get("host_b_name") or "Caspar").upper()
    known_speakers: set[str] = {host_a, host_b, "JUNO", "CASPAR"}
    for g in cfg.get("active_guest_hosts") or []:
        if isinstance(g, dict):
            if g.get("label"):
                known_speakers.add(str(g["label"]).upper())
            if g.get("display_name"):
                known_speakers.add(str(g["display_name"]).upper())

    placements = _place_cues(script, plan, client, known_speakers)
    if not placements:
        return []

    resolved: list[ResolvedFootnote] = []
    for cue in cues:
        if not isinstance(cue, dict):
            continue
        catalog_id = str(cue.get("catalog_id") or "").strip()
        after_turn = placements.get(catalog_id)
        if after_turn is None:
            logger.warning(
                "[footnote] Cue %r was not placed by the LLM pass — dropped.",
                catalog_id,
            )
            continue
        footnote = _resolve_cue(cue, catalog, after_turn, work_dir)
        if footnote:
            resolved.append(footnote)
            logger.info(
                "[footnote] Resolved %s -> %s (%.1fs, after turn %d)",
                catalog_id, footnote.audio_path.name,
                footnote.duration_sec, after_turn,
            )
        else:
            logger.warning(
                "[footnote] Cue %r resolved to no audio (source unavailable or download failed).",
                catalog_id,
            )

    n_planned = len([c for c in cues if isinstance(c, dict)])
    n_resolved = len(resolved)
    if n_planned > n_resolved:
        logger.warning(
            "[footnote] %d/%d planned cues were dropped (see warnings above).",
            n_planned - n_resolved, n_planned,
        )
    resolved.sort(key=lambda f: f.after_turn)
    return resolved
