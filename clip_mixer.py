#!/usr/bin/env python3
"""clip_mixer.py — Enrich a Dialog episode with illustrative YouTube audio clips."""

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
import tempfile

import anthropic

_ALLOWED_VIDEO_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com",
    "music.youtube.com", "youtu.be",
}

# Sonnet for the cue-annotation pass — short structured-JSON task, no quality regression vs Opus.
_CUE_MODEL = "claude-sonnet-4-6"


def _is_allowed_video_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host in _ALLOWED_VIDEO_HOSTS


@dataclass
class ClipCue:
    cue_id: str
    search_query: str
    context: str
    timestamp_hint: str
    duration_sec: int
    intro_text: str
    outro_text: str


@dataclass
class ExtractedClip:
    cue: ClipCue
    audio_path: Path
    video_url: str
    video_title: str
    actual_duration: float
    attribution: str


# ── Script annotation ──────────────────────────────────────────────────────────

_CUE_SYSTEM = """\
You are a podcast producer enriching an Asynchronous episode with illustrative audio clips.

The script is a two-host dialogue between Juno and Caspar. Your job: insert
CLIP_CUE blocks at 2-4 natural moments where a real audio excerpt would
illustrate a point or add texture.

For each cue, output a JSON block at the insertion point:

<<<CLIP_CUE
{
  "cue_id": "CLIP_01",
  "search_query": "specific YouTube search including speaker name or title",
  "context": "what this clip illustrates in 1 sentence",
  "timestamp_hint": "0:00",
  "duration_sec": 20,
  "intro_text": "JUNO: Oh wait — let's actually hear this in her own words.",
  "outro_text": "CASPAR: And that's exactly what the data confirmed."
}
CLIP_CUE>>>

Rules:
- Maximum 4 cues, minimum 2
- duration_sec must be 10-28 (never 30+)
- intro_text and outro_text MUST be attributed to a host with a speaker label:
  "JUNO: ..." or "CASPAR: ..." — use whichever fits the conversational flow
- search_query must be specific enough to find the right video
- Space cues out — not back to back
- Return the FULL script with cue blocks inserted inline
"""


def _extract_text(content_blocks) -> str:
    return "\n".join(
        block.text for block in content_blocks if hasattr(block, "text")
    ).strip()


def annotate_script_with_cues(script: str) -> tuple:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model=_CUE_MODEL,
        max_tokens=5000,
        system=_CUE_SYSTEM,
        messages=[{"role": "user", "content": script}],
    )
    annotated = _extract_text(resp.content)
    cues = _parse_cues(annotated)
    return annotated, cues


def _parse_cues(annotated_script: str) -> list:
    pattern = r"<<<CLIP_CUE\s*(\{.*?\})\s*CLIP_CUE>>>"
    cues = []
    for m in re.finditer(pattern, annotated_script, re.DOTALL):
        try:
            data = json.loads(m.group(1))
            data["duration_sec"] = min(int(data.get("duration_sec", 20)), 28)
            cues.append(
                ClipCue(**{k: data[k] for k in ClipCue.__dataclass_fields__})
            )
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            print(f"   [clip] Warning: could not parse cue: {exc}")
    return cues


# ── YouTube search & clip extraction ──────────────────────────────────────────

def search_youtube(query: str, max_results: int = 5) -> list:
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--dump-json", "--flat-playlist",
        f"ytsearch{max_results}:{query}", "--no-warnings",
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60
        )
    except subprocess.TimeoutExpired:
        print(f"   [clip] yt-dlp search timed out for query: {query!r}")
        return []
    videos = []
    for line in result.stdout.strip().splitlines():
        try:
            videos.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return videos


def _pick_best_video(videos: list, cue: ClipCue):
    scored = []
    for v in videos:
        duration = v.get("duration") or 0
        if not (30 < duration < 7200):
            continue
        score = 0.0
        score += min(v.get("view_count", 0) / 1_000_000, 5)
        score += min(v.get("channel_follower_count", 0) / 100_000, 3)
        title_lower = (v.get("title") or "").lower()
        for kw in ["lecture", "explained", "ted", "mit", "stanford", "how", "why"]:
            if kw in title_lower:
                score += 1
        scored.append((score, v))
    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


def _parse_timestamp(ts: str) -> float:
    parts = ts.strip().split(":")
    try:
        parts_f = [float(p) for p in parts]
        if len(parts_f) == 2:
            return parts_f[0] * 60 + parts_f[1]
        elif len(parts_f) == 3:
            return parts_f[0] * 3600 + parts_f[1] * 60 + parts_f[2]
        else:
            return float(parts_f[0])
    except ValueError:
        return 30.0


def extract_clip(cue: ClipCue, work_dir: Path):
    print(f"   [clip] Searching for: {cue.search_query!r}")
    videos = search_youtube(cue.search_query, max_results=8)
    if not videos:
        return None

    video = _pick_best_video(videos, cue)
    if not video:
        return None

    video_url   = video.get("url") or f"https://www.youtube.com/watch?v={video.get('id', '')}"
    if not _is_allowed_video_url(video_url):
        print(f"   [clip] Refusing non-YouTube URL for {cue.cue_id}: {video_url!r}")
        return None
    video_title = video.get("title", "Unknown")
    channel     = video.get("channel") or video.get("uploader", "Unknown")
    year        = str(video.get("upload_date", ""))[:4] or "n.d."

    start_sec = _parse_timestamp(cue.timestamp_hint)
    duration  = cue.duration_sec
    out_path  = work_dir / f"{cue.cue_id}.mp3"

    # Download only the needed segment — avoids full-video download
    raw_audio = work_dir / f"{cue.cue_id}_raw.%(ext)s"
    dl_cmd = [
        sys.executable, "-m", "yt_dlp",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "5",
        "--download-sections", f"*{max(0, start_sec - 2)}-{start_sec + duration + 2}",
        "--output", str(raw_audio),
        "--no-playlist",
        "--quiet",
        video_url,
    ]
    try:
        result = subprocess.run(
            dl_cmd, capture_output=True, text=True, timeout=120
        )
    except subprocess.TimeoutExpired:
        print(f"   [clip] yt-dlp download timed out for {cue.cue_id}")
        return None
    if result.returncode != 0:
        print(f"   [clip] yt-dlp failed for {cue.cue_id}: {result.stderr[:1000]}")
        return None

    raw_files = list(work_dir.glob(f"{cue.cue_id}_raw.*"))
    if not raw_files:
        return None
    raw_file = raw_files[0]

    cut_cmd = [
        "ffmpeg", "-y", "-i", str(raw_file),
        "-ss", str(max(0.0, start_sec - 1)),
        "-t", str(duration + 2),
        "-af", f"afade=t=in:st=0:d=0.5,afade=t=out:st={duration + 1}:d=0.5",
        "-ar", "44100", "-ac", "2",
        "-c:a", "libmp3lame", "-b:a", "192k",
        str(out_path),
    ]
    try:
        result = subprocess.run(
            cut_cmd, capture_output=True, text=True, timeout=120
        )
    except subprocess.TimeoutExpired:
        print(f"   [clip] ffmpeg trim timed out for {cue.cue_id}")
        raw_file.unlink(missing_ok=True)
        return None
    raw_file.unlink(missing_ok=True)

    if result.returncode != 0 or not out_path.exists():
        print(f"   [clip] ffmpeg trim failed for {cue.cue_id}: {result.stderr[:200]}")
        return None

    actual_dur  = _get_audio_duration(out_path)
    attribution = f'Clip from: "{video_title}" — {channel}, {year}'
    return ExtractedClip(
        cue=cue,
        audio_path=out_path,
        video_url=video_url,
        video_title=video_title,
        actual_duration=actual_dur,
        attribution=attribution,
    )


def _get_audio_duration(path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json", "-show_format", str(path),
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30
        )
    except subprocess.TimeoutExpired:
        return 0.0
    try:
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])
    except (json.JSONDecodeError, KeyError, ValueError):
        return 0.0


# ── Assembly ───────────────────────────────────────────────────────────────────

def _ffmpeg_concat(parts: list, output: Path) -> None:
    existing = [p for p in parts if Path(p).exists()]
    if not existing:
        raise ValueError("No audio segments to concatenate")
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as lf:
        lf.write("\n".join(f"file '{Path(p).resolve()}'" for p in existing))
        list_path = Path(lf.name)

    try:
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(list_path),
            "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k",
            str(output),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg concat failed: {result.stderr[:500]}")
    finally:
        list_path.unlink(missing_ok=True)


def _strip_cue_artifacts(text: str) -> str:
    return re.sub(r"<<<CLIP_CUE.*?CLIP_CUE>>>", "", text, flags=re.DOTALL).strip()


def assemble_with_clips(
    annotated_script: str,
    clips: dict,
    tts_fn,
    work_dir: Path,
    final_output: Path,
    two_host_tts_fn=None,
) -> Path:
    """Interleave narration TTS segments with extracted clips.

    two_host_tts_fn: if provided, used for intro/outro text that may carry
    JUNO:/CASPAR: speaker labels; falls back to tts_fn if None.
    """
    label_aware_fn = two_host_tts_fn if two_host_tts_fn is not None else tts_fn

    cue_pattern = r"<<<CLIP_CUE.*?CLIP_CUE>>>"
    parts = re.split(cue_pattern, annotated_script, flags=re.DOTALL)
    cue_matches = list(re.finditer(cue_pattern, annotated_script, re.DOTALL))

    audio_segments: list = []
    seg_idx = 0

    for i, text_part in enumerate(parts):
        clean_text = _strip_cue_artifacts(text_part)
        if clean_text.strip():
            tts_out = work_dir / f"seg_{seg_idx:03d}_narr.mp3"
            seg_idx += 1
            tts_fn(clean_text, tts_out)
            audio_segments.append(tts_out)

        if i < len(cue_matches):
            try:
                cue_json = re.search(
                    r"\{.*\}", cue_matches[i].group(), re.DOTALL
                )
                if not cue_json:
                    continue
                cue_data = json.loads(cue_json.group())
                cue_id   = cue_data.get("cue_id")

                if cue_id in clips:
                    clip = clips[cue_id]

                    if clip.cue.intro_text:
                        intro_path = work_dir / f"seg_{seg_idx:03d}_intro.mp3"
                        seg_idx += 1
                        label_aware_fn(clip.cue.intro_text, intro_path)
                        audio_segments.append(intro_path)

                    audio_segments.append(clip.audio_path)

                    outro_with_attr = (
                        clip.cue.outro_text.rstrip(".")
                        + f". {clip.attribution}."
                    )
                    outro_path = work_dir / f"seg_{seg_idx:03d}_outro.mp3"
                    seg_idx += 1
                    label_aware_fn(outro_with_attr, outro_path)
                    audio_segments.append(outro_path)

            except (AttributeError, json.JSONDecodeError, KeyError) as exc:
                print(f"   [clip] Warning: could not assemble cue at position {i}: {exc}")

    _ffmpeg_concat(audio_segments, final_output)
    return final_output


# ── Public entry point ─────────────────────────────────────────────────────────

def process_clips(
    script: str,
    tts_fn,
    work_dir: Path,
    final_output: Path,
    skip_failed: bool = True,
    two_host_tts_fn=None,
) -> tuple:
    """Annotate script with clip cues, extract clips, and assemble final audio.

    Uses a plain subdirectory (not TemporaryDirectory) for clip downloads so
    that copy+delete is used instead of rename, which avoids Windows file-handle
    issues when the TemporaryDirectory context manager tries to clean up.
    """
    work_dir.mkdir(parents=True, exist_ok=True)

    annotated_script, cues = annotate_script_with_cues(script)
    if not cues:
        tts_fn(script, final_output)
        return final_output, []

    clips_tmp = work_dir / "clips_dl"
    clips_tmp.mkdir(parents=True, exist_ok=True)

    extracted: dict = {}
    attributions: list = []

    try:
        for cue in cues:
            clip = extract_clip(cue, clips_tmp)
            if clip:
                # Copy to stable location, then remove from download dir — avoids
                # cross-directory rename issues and Windows handle contention
                stable_path = work_dir / clip.audio_path.name
                shutil.copy2(clip.audio_path, stable_path)
                clip.audio_path.unlink(missing_ok=True)
                clip.audio_path = stable_path
                extracted[cue.cue_id] = clip
                attributions.append(clip.attribution)
            elif not skip_failed:
                raise RuntimeError(
                    f"Failed to extract clip for cue {cue.cue_id}"
                )
    finally:
        # Best-effort cleanup; ignore errors (locked handles on Windows)
        shutil.rmtree(clips_tmp, ignore_errors=True)

    if not extracted:
        tts_fn(script, final_output)
        return final_output, []

    assemble_with_clips(
        annotated_script,
        extracted,
        tts_fn,
        work_dir,
        final_output,
        two_host_tts_fn=two_host_tts_fn,
    )
    return final_output, attributions
