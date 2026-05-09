#!/usr/bin/env python3
"""
Dialog Podcast Generator
Generates a two-host, Radiolab-style dialogue podcast on any topic.
Hosts: Cedar (artistic) and Marin (scientific).

Pipeline:
  1. Research brief    — web-searched facts, sources, story angles
  2. Dialogue script  — Cedar/Marin conversation from the brief
  3. Fact-check       — corrections applied inline
  4. Audio            — two-voice TTS, optional YouTube clips, optional music
  5. Publish          — RSS update + optional git push
"""

import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import anthropic

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Optional dependencies ──────────────────────────────────────────────────────

try:
    from music_gen import generate_intro_outro, HAS_AUDIOCRAFT, HAS_NUMPY as _HAS_NUMPY
    HAS_MUSIC_GEN = HAS_AUDIOCRAFT or _HAS_NUMPY
except ImportError:
    HAS_MUSIC_GEN = False
    generate_intro_outro = None  # type: ignore[assignment]

try:
    from clip_mixer import process_clips
    HAS_CLIP_MIXER = True
except ImportError:
    HAS_CLIP_MIXER = False

try:
    from openai import OpenAI as OpenAIClient
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

try:
    import requests as req_lib
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# ── Models ─────────────────────────────────────────────────────────────────────
# Research stays on Opus for quality; dialogue + fact-check on Sonnet for cost.
_RESEARCH_MODEL   = "claude-opus-4-5"
_DIALOGUE_MODEL   = "claude-sonnet-4-6"
_FACT_CHECK_MODEL = "claude-sonnet-4-6"


# ── Config ─────────────────────────────────────────────────────────────────────

DEFAULTS: dict = {
    "podcast_title":        "Asynchronous",
    "podcast_description":  "Cedar and Marin roam the edges of art, science, and human experience.",
    "podcast_author":       "Cedar & Marin",
    "podcast_email":        "you@example.com",
    "podcast_image":        "",
    "podcast_language":     "en",
    "podcast_category":     "Science",
    "github_user":          "",
    "github_repo":          "dialog-podcast",
    "github_branch":        "main",
    "tts_provider":         "openai",
    "host_a_name":          "Cedar",
    "host_a_voice":         "cedar",
    "host_a_role":          "artistic",
    "host_b_name":          "Marin",
    "host_b_voice":         "marin",
    "host_b_role":          "scientific",
    "elevenlabs_voice_id_a": "",
    "elevenlabs_voice_id_b": "",
    "target_minutes":       15,
    "output_dir":           "episodes",
    "use_clips":            True,
    "use_music":            True,
    "tts_model":            "gpt-4o-mini-tts",
    "use_emotive_tts":      True,
    "music_model":          "facebook/musicgen-small",
    "music_duration_sec":   12,
    "music_fade_sec":       2,
}


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    cfg_path = Path("config.json")
    if cfg_path.exists():
        with open(cfg_path, encoding="utf-8") as f:
            cfg.update(json.load(f))
    env_map = {
        "PODCAST_TITLE":  "podcast_title",
        "GITHUB_USER":    "github_user",
        "GITHUB_REPO":    "github_repo",
        "TTS_PROVIDER":   "tts_provider",
        "HOST_A_VOICE":   "host_a_voice",
        "HOST_B_VOICE":   "host_b_voice",
        "TARGET_MINUTES": "target_minutes",
    }
    for env_key, cfg_key in env_map.items():
        val = os.environ.get(env_key)
        if val:
            cfg[cfg_key] = val
    # Boolean override: USE_MUSIC=false disables MusicGen (used in CI)
    use_music_env = os.environ.get("USE_MUSIC")
    if use_music_env is not None:
        cfg["use_music"] = use_music_env.lower() not in ("0", "false", "no", "off", "")
    return cfg


# ── System prompts ─────────────────────────────────────────────────────────────

_RESEARCH_SYSTEM = """\
You are an expert researcher and science communicator.
Your task: produce a detailed research BRIEF — NOT a script.

The brief should contain:
- Key facts, data points, and statistics with named sources (author, publication, year)
- Names of researchers, institutions, relevant studies
- Interesting narrative angles, surprising or counterintuitive findings
- Any open questions or scientific debates
- Human-interest story hooks
- 5-8 sources for further reading

Rules:
- ACCURACY FIRST. Only state facts you are confident about.
- Flag uncertain claims with "Research suggests..." or "Some evidence indicates..."
- Be rich in specific detail — dates, numbers, names, places.
- This brief feeds a dialogue script, so include story angles and emotional resonance.
"""

_DIALOGUE_SYSTEM = """\
You are writing a podcast script for "Asynchronous" — a show in the style of Radiolab.

The two hosts are:
- CEDAR: Artistic, broad-thinking, asks "what does this MEAN for us?" She finds
  unexpected metaphors and connections. She's enthusiastic and sometimes goes on
  tangents that turn out to be profound. She composed the show's theme music.
  She speaks with warmth and wonder.
- MARIN: Scientifically grounded, methodical, slightly older and more skeptical.
  He's the one who says "well, actually..." but does it with dry wit and genuine
  curiosity, not pedantry. He grounds Cedar's flights of fancy in evidence.

Format EVERY line with a speaker label AND an emotion delivery tag in square brackets:
CEDAR [warm, curious]: dialogue text here
MARIN [dry wit, measured]: dialogue text here

The emotion tag guides text-to-speech delivery — treat it as a director's note.
Keep tags to 2-4 words describing tone, and optionally pace or energy:
  CEDAR [warm, wondering]: I keep thinking about this image...
  MARIN [dry, slightly amused]: Well, the data would suggest otherwise.
  CEDAR [genuinely excited, faster]: Wait — that's actually incredible.
  MARIN [careful, searching]: There's something I can't quite put into words.
  CEDAR [laughing slightly]: I mean, when you put it that way—
  MARIN [somber, quieter]: And that's where it gets hard.
  CEDAR [skeptical but intrigued]: Okay, but does it actually hold up?
  MARIN [building, emphatic]: This is the part that changes everything.

Rules for great Radiolab-style dialogue:
- They build on each other's thoughts — don't just trade monologues
- Interruptions are shown with em dashes: "And then the—"  "Right, exactly!"
- React to what the other person says. Use "wait", "okay but", "hold on",
  "that's the thing though"
- Tell it as a story — narrative arc, not just facts in order
- Cedar often opens with an unexpected image or anecdote
- Marin often grounds things by naming specific researchers or data
- Both can show genuine emotion: surprise, delight, discomfort
- No bullet points. No headers. Pure dialogue from first word to last.
- Sources section at the end as a natural spoken exchange:
  MARIN: "And if you want to dig in further, the sources for today's episode
  include..." followed by a spoken list, with Cedar occasionally chiming in
- Target: {target_words} words total — but end naturally rather than padding if
  the content doesn't support the full length
"""

_FACT_CHECK_SYSTEM = """\
You are a rigorous fact-checker for a podcast.
Review the dialogue script below and silently correct any inaccurate, exaggerated,
or unverifiable claims directly in the dialogue — do not add markers or annotations.

Rules:
- Return ONLY the corrected script in the exact CEDAR:/MARIN: dialogue format.
- If a claim cannot be verified, soften the language ("some evidence suggests…")
  rather than stating it as fact.
- Do NOT append a corrections list, accuracy rating, editorial notes, or any section
  that is not part of the dialogue itself.
- Do NOT restructure, reorder, or add new dialogue turns.
- Preserve speaker labels AND emotion tags exactly as-is (e.g. CEDAR [warm, curious]: / MARIN [dry, measured]:).
"""

_CORRECTIONS_APPENDIX_RE = re.compile(
    r"\n{1,2}[-—*#\s]*(corrections?|changes?\s+made|editorial\s+notes?|"
    r"fact[\s\-]?check(?:er)?|accuracy\s+rat|accuracy\s+notes?)[^\n]*.*",
    re.IGNORECASE | re.DOTALL,
)


# ── Research pipeline ──────────────────────────────────────────────────────────

def _strip_corrections_appendix(script: str) -> str:
    """Strip trailing corrections/editorial-notes sections the fact-checker may add."""
    return _CORRECTIONS_APPENDIX_RE.sub("", script).strip()


def _extract_text(content_blocks) -> str:
    return "\n".join(
        block.text for block in content_blocks if hasattr(block, "text")
    ).strip()


def _extract_sources(script: str) -> list:
    lines = script.splitlines()
    sources: list = []
    in_sources = False
    for line in lines:
        stripped = re.sub(r'^(CEDAR|MARIN)(?:\s*\[[^\]]*\])?\s*:\s*"?', "", line).strip().rstrip('"')
        if re.search(r'\b(sources|further reading|references)\b', stripped, re.I):
            in_sources = True
            continue
        if in_sources:
            if not stripped or stripped.startswith("#"):
                # Blank line or section header ends the sources list
                if sources:
                    break
                continue
            sources.append(stripped)
    return sources[:12]


def research_and_script(topic: str, cfg: dict, client: anthropic.Anthropic) -> dict:
    target_words = int(cfg["target_minutes"]) * 130

    # Pass 1 — Research brief
    logger.info(f"[1/5] Researching topic: {topic!r}")
    research_resp = client.messages.create(
        model=_RESEARCH_MODEL,
        max_tokens=4096,
        system=_RESEARCH_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Research this topic thoroughly for a podcast episode: {topic}\n\n"
                    "Produce a detailed research brief with facts, data, sources, "
                    "and story angles — NOT a script."
                ),
            }
        ],
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
    )
    research_brief = _extract_text(research_resp.content)

    # Pass 2 — Dialogue script
    logger.info("[2/5] Writing Cedar/Marin dialogue script...")
    dialogue_resp = client.messages.create(
        model=_DIALOGUE_MODEL,
        max_tokens=8192,
        system=_DIALOGUE_SYSTEM.format(target_words=target_words),
        messages=[
            {
                "role": "user",
                "content": (
                    f"Using the research brief below, write a Cedar/Marin dialogue "
                    f"podcast script about: {topic}\n\n"
                    f"Research Brief:\n{research_brief}"
                ),
            }
        ],
    )
    raw_script = _extract_text(dialogue_resp.content)

    # Pass 3 — Fact-check
    logger.info("[3/5] Fact-checking script...")
    fc_resp = client.messages.create(
        model=_FACT_CHECK_MODEL,
        max_tokens=8192,
        system=_FACT_CHECK_SYSTEM,
        messages=[{"role": "user", "content": raw_script}],
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
    )
    checked_script = _extract_text(fc_resp.content)
    final_script = re.sub(r"\[CORRECTION:[^\]]*\]", "", checked_script)
    final_script = _strip_corrections_appendix(final_script)
    # Strip any preamble text before the first speaker line
    first_turn = re.search(r"^(CEDAR|MARIN)(?:\s*\[[^\]]*\])?\s*:", final_script, re.MULTILINE)
    if first_turn:
        final_script = final_script[first_turn.start():]
    sources = _extract_sources(final_script)

    return {
        "topic":      topic,
        "script":     final_script,
        "sources":    sources,
        "word_count": len(final_script.split()),
    }


# ── Text utilities ─────────────────────────────────────────────────────────────

def _clean_for_tts(text: str) -> str:
    text = re.sub(r"^#+\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", text)
    text = re.sub(r"`[^`]+`", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^\s*[-*]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _chunk_text(text: str, max_chars: int = 4000) -> list:
    """Split text at sentence boundaries; hard-split sentences exceeding max_chars."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list = []
    current = ""

    for s in sentences:
        if len(s) > max_chars:
            # Flush current buffer first
            if current.strip():
                chunks.append(current.strip())
                current = ""
            # Hard-split on word boundaries
            words = s.split()
            part = ""
            for w in words:
                if len(part) + len(w) + 1 > max_chars:
                    if part.strip():
                        chunks.append(part.strip())
                    part = w
                else:
                    part = (part + " " + w).strip() if part else w
            if part.strip():
                chunks.append(part.strip())
        elif len(current) + len(s) + 1 > max_chars:
            if current.strip():
                chunks.append(current.strip())
            current = s
        else:
            current = (current + " " + s).strip() if current else s

    if current.strip():
        chunks.append(current.strip())
    return chunks or [text]


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
    )


def _cdata_safe(text: str) -> str:
    """Defuse CDATA-end sequences so a string can't break out of <![CDATA[ ... ]]>."""
    return text.replace("]]>", "]]]]><![CDATA[>")


# ── Two-voice TTS ──────────────────────────────────────────────────────────────

_TURN_RE = re.compile(r"^([A-Z][A-Z ]*)(?:\s*\[([^\]]*)\])?\s*:\s*(.*)")


def _parse_dialogue_turns(script: str, cfg: dict) -> list:
    """Return [(speaker_label, emotion_tag, text), ...] triples from a CEDAR/MARIN script.

    Handles both tagged format  CEDAR [warm, curious]: text
    and untagged format         CEDAR: text  (emotion_tag will be empty string).
    """
    host_a = cfg.get("host_a_name", "Cedar").upper()
    host_b = cfg.get("host_b_name", "Marin").upper()
    known = {host_a, host_b, "CEDAR", "MARIN"}

    turns: list = []
    current_label: str | None = None
    current_tag: str = ""
    current_lines: list = []

    for line in script.splitlines():
        m = _TURN_RE.match(line)
        if m and m.group(1).strip().upper() in known:
            if current_label and current_lines:
                turns.append((current_label, current_tag, " ".join(current_lines).strip()))
            current_label = m.group(1).strip().upper()
            current_tag = (m.group(2) or "").strip()
            rest = m.group(3).strip()
            current_lines = [rest] if rest else []
        elif current_label is not None:
            stripped = line.strip()
            if stripped:
                current_lines.append(stripped)

    if current_label and current_lines:
        turns.append((current_label, current_tag, " ".join(current_lines).strip()))

    return turns


def _voice_for_label(label: str, cfg: dict) -> str:
    host_a = cfg.get("host_a_name", "Cedar").upper()
    host_b = cfg.get("host_b_name", "Marin").upper()
    if label in {host_a, "CEDAR"}:
        return cfg.get("host_a_voice", "cedar")
    if label in {host_b, "MARIN"}:
        return cfg.get("host_b_voice", "marin")
    return cfg.get("host_a_voice", "cedar")


def _emotion_default_for_label(label: str, cfg: dict) -> str:
    host_a = cfg.get("host_a_name", "Cedar").upper()
    if label in {host_a, "CEDAR"}:
        return "warm, curious"
    return "measured, thoughtful"


def _build_tts_instructions(emotion_tag: str, label: str, cfg: dict) -> str:
    tag = emotion_tag if emotion_tag else _emotion_default_for_label(label, cfg)
    return (
        f"Deliver this line with: {tag}. "
        "Speak naturally, as if in genuine conversation."
    )


def _ffmpeg_concat(parts: list, output: Path) -> None:
    """Concatenate audio files in order using ffmpeg."""
    existing = [p for p in parts if Path(p).exists()]
    if not existing:
        raise ValueError("No audio segments to concatenate — all paths missing")
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
            "-ar", "44100", "-ac", "2", "-b:a", "128k",
            str(output),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg concat failed: {result.stderr[:500]}")
    finally:
        list_path.unlink(missing_ok=True)


def _tts_openai_voice(
    text: str,
    voice: str,
    output_path: Path,
    cfg: dict,
    instructions: str = "",
) -> Path:
    """Generate TTS for a single voice, with sentence-boundary chunking.

    When cfg['use_emotive_tts'] is true and instructions is non-empty, the
    instructions string is passed to gpt-4o-mini-tts to guide delivery style.
    If the API rejects the instructions parameter, the call is retried without it.
    """
    if not HAS_OPENAI:
        raise ImportError("openai package not installed.")

    oa_client = OpenAIClient(api_key=os.environ["OPENAI_API_KEY"])
    output_path = output_path.with_suffix(".mp3")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    model = cfg.get("tts_model", "gpt-4o-mini-tts")
    use_instructions = (
        cfg.get("use_emotive_tts", True)
        and bool(instructions)
        and model == "gpt-4o-mini-tts"
    )

    clean = _clean_for_tts(text)
    chunks = _chunk_text(clean, max_chars=4000)
    audio_segments: list = []

    for i, chunk in enumerate(chunks):
        if not chunk.strip():
            continue
        logger.debug(f"TTS chunk {i + 1}/{len(chunks)} voice={voice!r} ({len(chunk)} chars)")
        kwargs: dict = {"model": model, "voice": voice, "input": chunk}
        if use_instructions:
            kwargs["instructions"] = instructions
        try:
            response = oa_client.audio.speech.create(**kwargs)
        except Exception as exc:
            if use_instructions and "instructions" in str(exc).lower():
                logger.warning(f"TTS instructions not accepted, retrying without: {exc}")
                kwargs.pop("instructions")
                response = oa_client.audio.speech.create(**kwargs)
            else:
                raise
        chunk_path = output_path.with_stem(f"{output_path.stem}_c{i}")
        response.stream_to_file(str(chunk_path))
        audio_segments.append(chunk_path)

    if not audio_segments:
        raise RuntimeError(f"No audio generated for text starting: {text[:60]!r}")

    if len(audio_segments) == 1:
        audio_segments[0].rename(output_path)
    else:
        _ffmpeg_concat(audio_segments, output_path)
        for p in audio_segments:
            p.unlink(missing_ok=True)

    return output_path


def _tts_two_host(
    script: str,
    output_path: Path,
    cfg: dict,
    work_dir: Path,
) -> Path:
    """Generate two-voice TTS from a Cedar/Marin dialogue script."""
    turns = _parse_dialogue_turns(script, cfg)
    if not turns:
        logger.warning("No dialogue turns found — falling back to single-voice TTS")
        return _tts_openai_voice(
            script, cfg.get("host_a_voice", "cedar"), output_path, cfg
        )

    work_dir.mkdir(parents=True, exist_ok=True)
    turn_files: list = []

    for i, (label, emotion_tag, text) in enumerate(turns):
        if not text.strip():
            continue
        voice = _voice_for_label(label, cfg)
        instructions = _build_tts_instructions(emotion_tag, label, cfg)
        turn_path = work_dir / f"turn_{i:04d}_{label.lower()}.mp3"
        _tts_openai_voice(text, voice, turn_path, cfg, instructions=instructions)
        if turn_path.exists():
            turn_files.append(turn_path)

    if not turn_files:
        raise RuntimeError("No turn audio files were generated")

    output_path = output_path.with_suffix(".mp3")
    _ffmpeg_concat(turn_files, output_path)

    for p in turn_files:
        p.unlink(missing_ok=True)

    return output_path


def _tts_elevenlabs_chunked(
    text: str,
    voice_id: str,
    output_path: Path,
) -> Path:
    """ElevenLabs TTS with proper sentence-boundary chunking."""
    if not HAS_REQUESTS:
        raise ImportError("requests package not installed.")
    api_key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not api_key:
        raise ValueError("ELEVENLABS_API_KEY not set.")
    if not voice_id:
        raise ValueError("ElevenLabs voice_id is empty.")

    output_path = output_path.with_suffix(".mp3")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    clean = _clean_for_tts(text)
    chunks = _chunk_text(clean, max_chars=4500)
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {"xi-api-key": api_key, "Content-Type": "application/json"}
    chunk_paths: list = []

    for i, chunk in enumerate(chunks):
        if not chunk.strip():
            continue
        payload = {
            "text": chunk,
            "model_id": "eleven_turbo_v2",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }
        r = req_lib.post(url, json=payload, headers=headers)
        r.raise_for_status()
        cp = output_path.with_stem(f"{output_path.stem}_el{i}")
        cp.write_bytes(r.content)
        chunk_paths.append(cp)

    if not chunk_paths:
        raise RuntimeError("No audio chunks generated from ElevenLabs")

    if len(chunk_paths) == 1:
        chunk_paths[0].rename(output_path)
    else:
        _ffmpeg_concat(chunk_paths, output_path)
        for p in chunk_paths:
            p.unlink(missing_ok=True)

    return output_path


def generate_audio(
    script: str,
    output_path: Path,
    cfg: dict,
    work_dir: Path,
) -> Path:
    """Generate episode audio from a dialogue script."""
    provider = cfg["tts_provider"].lower()
    logger.info(f"[4/5] Generating audio via {provider}...")

    if provider == "openai":
        return _tts_two_host(script, output_path, cfg, work_dir / "turns")

    elif provider == "elevenlabs":
        turns = _parse_dialogue_turns(script, cfg)
        if not turns:
            voice_id = cfg.get("elevenlabs_voice_id_a", "")
            return _tts_elevenlabs_chunked(script, voice_id, output_path)
        turn_dir = work_dir / "turns"
        turn_dir.mkdir(parents=True, exist_ok=True)
        turn_files: list = []
        for i, (label, _emotion_tag, text) in enumerate(turns):
            if not text.strip():
                continue
            host_a = cfg.get("host_a_name", "Cedar").upper()
            if label in {host_a, "CEDAR"}:
                voice_id = cfg.get("elevenlabs_voice_id_a", "")
            else:
                voice_id = cfg.get("elevenlabs_voice_id_b", "")
            if not voice_id:
                logger.warning(f"No ElevenLabs voice_id for {label}, skipping turn")
                continue
            tp = turn_dir / f"turn_{i:04d}.mp3"
            _tts_elevenlabs_chunked(text, voice_id, tp)
            if tp.exists():
                turn_files.append(tp)
        if not turn_files:
            raise RuntimeError("No ElevenLabs audio generated")
        output_path = output_path.with_suffix(".mp3")
        _ffmpeg_concat(turn_files, output_path)
        for p in turn_files:
            p.unlink(missing_ok=True)
        return output_path

    else:
        txt_path = output_path.with_suffix(".txt")
        txt_path.write_text(script, encoding="utf-8")
        return txt_path


def _prepend_append_audio(
    main: Path,
    intro: Path | None,
    outro: Path | None,
    output: Path,
) -> None:
    """Build final audio by optionally prepending intro and appending outro music."""
    segments = []
    if intro and intro.exists():
        segments.append(intro)
    segments.append(main)
    if outro and outro.exists():
        segments.append(outro)

    if len(segments) == 1:
        shutil.copy2(main, output)
        return

    _ffmpeg_concat(segments, output)


# ── RSS ────────────────────────────────────────────────────────────────────────

_RSS_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
     xmlns:content="http://purl.org/rss/1.0/modules/content/"
     xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{podcast_title}</title>
    <link>{base_url}</link>
    <description>{podcast_description}</description>
    <language>{podcast_language}</language>
    <itunes:author>{podcast_author}</itunes:author>
    <itunes:category text="{podcast_category}"/>
    <itunes:explicit>false</itunes:explicit>
    <itunes:owner>
      <itunes:name>{podcast_author}</itunes:name>
      <itunes:email>{podcast_email}</itunes:email>
    </itunes:owner>
    <itunes:image href="{podcast_image_url}"/>
    <atom:link href="{feed_url}" rel="self" type="application/rss+xml"/>
    {items}
  </channel>
</rss>"""

_ITEM_TEMPLATE = """\
    <item>
      <title>{title}</title>
      <description><![CDATA[{description}]]></description>
      <pubDate>{pub_date}</pubDate>
      <guid isPermaLink="false">{guid}</guid>
      <enclosure url="{audio_url}" length="{file_size}" type="audio/mpeg"/>
      <itunes:duration>{duration}</itunes:duration>
      <itunes:explicit>false</itunes:explicit>
    </item>"""


def update_rss(
    episode: dict,
    audio_path: Path,
    cfg: dict,
    repo_root: Path,
) -> None:
    base_url  = f"https://{cfg['github_user']}.github.io/{cfg['github_repo']}"
    feed_url  = f"{base_url}/feed.xml"
    audio_url = f"{base_url}/{cfg['output_dir']}/{audio_path.name}"
    file_size = audio_path.stat().st_size if audio_path.exists() else 0
    pub_date  = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
    # SHA-256 instead of MD5 for GUID uniqueness
    guid = hashlib.sha256((episode["topic"] + pub_date).encode()).hexdigest()
    duration = f"{cfg['target_minutes']}:00"

    sources_html = ""
    if episode.get("sources"):
        items_html = "".join(
            f"<li>{_xml_escape(s)}</li>" for s in episode["sources"]
        )
        sources_html = f"<br><br><strong>Sources:</strong><ul>{items_html}</ul>"

    music_html = ""
    if episode.get("music_credit"):
        music_html = f"<br><em>{_xml_escape(episode['music_credit'])}</em>"

    # Script preview — escape any XML-sensitive chars outside CDATA wrap
    preview = _xml_escape(
        re.sub(r"^(CEDAR|MARIN)(?:\s*\[[^\]]*\])?\s*:\s*", "", episode["script"][:500], flags=re.MULTILINE)
    )
    description = _cdata_safe(preview + "..." + sources_html + music_html)

    new_item = _ITEM_TEMPLATE.format(
        title       = _xml_escape(episode["topic"]),
        description = description,
        pub_date    = pub_date,
        guid        = guid,
        audio_url   = audio_url,
        file_size   = file_size,
        duration    = duration,
    )

    feed_path = repo_root / "feed.xml"
    if feed_path.exists():
        content = feed_path.read_text(encoding="utf-8")
        # Insert newest item just before </channel> so every run appends correctly.
        # (The atom:link tag is self-closing — </atom:link> never appears in the file.)
        content = content.replace("</channel>", new_item + "\n  </channel>", 1)
    else:
        content = _RSS_TEMPLATE.format(
            podcast_title       = _xml_escape(cfg["podcast_title"]),
            base_url            = base_url,
            podcast_description = _xml_escape(cfg["podcast_description"]),
            podcast_language    = cfg["podcast_language"],
            podcast_author      = _xml_escape(cfg["podcast_author"]),
            podcast_category    = _xml_escape(cfg["podcast_category"]),
            podcast_email       = _xml_escape(cfg["podcast_email"]),
            podcast_image_url   = cfg.get("podcast_image", ""),
            feed_url            = feed_url,
            items               = new_item,
        )

    feed_path.write_text(content, encoding="utf-8")
    logger.info(f"RSS feed updated → {feed_path}")


def git_publish(audio_path: Path, repo_root: Path, topic: str) -> None:
    safe_topic = re.sub(r"[\r\n]+", " ", topic).strip()[:120] or "(untitled)"
    for cmd in [
        ["git", "add", "-f", str(audio_path), "feed.xml"],
        ["git", "commit", "-m", f"New episode: {safe_topic}"],
    ]:
        result = subprocess.run(
            cmd, cwd=repo_root, capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"git {cmd[1]} failed:\n{result.stderr}"
            )

    # Retry push up to 3 attempts (transient remote errors)
    last_err = ""
    for attempt in range(3):
        result = subprocess.run(
            ["git", "push"], cwd=repo_root, capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            return
        last_err = result.stderr
        if attempt < 2:
            logger.warning(f"git push failed (attempt {attempt + 1}/3), retrying in 3s…")
            time.sleep(3)

    raise RuntimeError(f"git push failed after 3 attempts:\n{last_err}")


# ── clip_mixer integration ─────────────────────────────────────────────────────

def _make_tts_fn(cfg: dict, work_dir: Path):
    """Return a (text, output_path) -> Path closure for clip_mixer compatibility.

    Automatically detects dialogue speaker labels and routes to two-host TTS
    when present, falling back to single-voice for plain narration.
    """
    provider = cfg["tts_provider"].lower()

    def tts_fn(text: str, output: Path) -> Path:
        if provider == "openai":
            if re.search(r"^(CEDAR|MARIN)(?:\s*\[[^\]]*\])?\s*:", text, re.MULTILINE | re.IGNORECASE):
                return _tts_two_host(text, output, cfg, work_dir / "tts_turns")
            return _tts_openai_voice(
                text, cfg.get("host_a_voice", "cedar"), output, cfg
            )
        elif provider == "elevenlabs":
            voice_id = cfg.get("elevenlabs_voice_id_a", "")
            return _tts_elevenlabs_chunked(text, voice_id, output)
        else:
            p = output.with_suffix(".txt")
            p.write_text(text, encoding="utf-8")
            return p

    return tts_fn


# ── Intro ident ───────────────────────────────────────────────────────────────

_INTRO_IDENT_TEXT = "Asynchronous. A podcast about ideas. With Cedar and Marin."


def _ensure_intro_ident(cfg: dict, repo_root: Path) -> "Path | None":
    """Generate and cache the show intro ident at assets/intro_ident.mp3.

    Uses Cedar's TTS voice. Skips silently if OpenAI is unavailable.
    Only synthesised once; subsequent calls return the cached file immediately.
    """
    ident_path = repo_root / "assets" / "intro_ident.mp3"
    if ident_path.exists():
        return ident_path

    if not HAS_OPENAI or not os.environ.get("OPENAI_API_KEY"):
        logger.warning("OpenAI unavailable — skipping intro ident generation")
        return None

    try:
        ident_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Generating show intro ident (first run only)…")
        cedar_voice = cfg.get("host_a_voice", "marin")
        _tts_openai_voice(
            _INTRO_IDENT_TEXT,
            cedar_voice,
            ident_path,
            cfg,
            instructions=(
                "Calm, warm, and inviting — like the opening of a thoughtful "
                "radio documentary. Speak slowly and with gentle gravitas."
            ),
        )
        logger.info(f"Intro ident cached: {ident_path}")
        return ident_path
    except Exception as exc:
        logger.warning(f"Intro ident generation failed: {exc}")
        return None


# ── Main run ───────────────────────────────────────────────────────────────────

def run(topic: str, repo_root: Path = Path(".")) -> dict:
    cfg = load_config()
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    episode = research_and_script(topic, cfg, client)

    safe_name   = re.sub(r"[^\w\-]", "_", topic)[:60]
    timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
    ep_filename = f"{timestamp}_{safe_name}"
    ep_dir      = repo_root / cfg["output_dir"]
    ep_dir.mkdir(parents=True, exist_ok=True)
    final_mp3   = ep_dir / f"{ep_filename}.mp3"
    work_dir    = ep_dir / f"{ep_filename}_work"
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        logger.info("[4/5] Generating episode audio...")
        raw_audio = work_dir / f"{ep_filename}_raw.mp3"

        use_clips = cfg.get("use_clips", True) and HAS_CLIP_MIXER
        attributions: list = []

        if use_clips:
            tts_fn = _make_tts_fn(cfg, work_dir)
            try:
                audio_path, attributions = process_clips(
                    script=episode["script"],
                    tts_fn=tts_fn,
                    work_dir=work_dir / "clips",
                    final_output=raw_audio,
                    skip_failed=True,
                    two_host_tts_fn=tts_fn,
                )
            except Exception as exc:
                logger.warning(f"Clip pipeline error ({exc}) — falling back to dialogue-only")
                audio_path = generate_audio(episode["script"], raw_audio, cfg, work_dir)
                attributions = []
        else:
            audio_path = generate_audio(episode["script"], raw_audio, cfg, work_dir)

        # Intro ident — cached after first run
        ident_path = _ensure_intro_ident(cfg, repo_root)

        # Music integration (Cedar is credited as composer)
        if cfg.get("use_music") and HAS_MUSIC_GEN and generate_intro_outro is not None:
            music_dir = work_dir / "music"
            intro_path, outro_path = generate_intro_outro(
                cfg, topic, music_dir, client
            )
            if intro_path and outro_path:
                logger.info("Wrapping episode with ident + intro/outro music…")
                # Assembly order: ident → music intro → dialogue → music outro
                segments = []
                if ident_path and ident_path.exists():
                    segments.append(ident_path)
                segments += [intro_path, audio_path, outro_path]
                _ffmpeg_concat(segments, final_mp3)
                episode["music_credit"] = (
                    f"Original theme music composed by {cfg['host_a_name']}."
                )
            else:
                if ident_path and ident_path.exists():
                    _ffmpeg_concat([ident_path, audio_path], final_mp3)
                else:
                    shutil.copy2(audio_path, final_mp3)
        else:
            if ident_path and ident_path.exists():
                _ffmpeg_concat([ident_path, audio_path], final_mp3)
            else:
                shutil.copy2(audio_path, final_mp3)

        audio_path = final_mp3

        logger.info("[5/5] Updating RSS feed...")
        update_rss(episode, audio_path, cfg, repo_root)

        if not os.environ.get("SKIP_GIT"):
            git_publish(audio_path, repo_root, topic)

    finally:
        # TODO 2026-06-06: re-enable to stop bloating disk; kept off for first-month debug window.
        # if work_dir.exists():
        #     shutil.rmtree(work_dir, ignore_errors=True)
        pass

    logger.info(
        f"\nDone!  Episode: {topic!r}  "
        f"({episode['word_count']} words, audio: {final_mp3.name})"
    )
    return episode


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a Dialog podcast episode.")
    parser.add_argument("topic", nargs="?", help="Episode topic")
    parser.add_argument("--repo", default=".", help="Repo root directory")
    args = parser.parse_args()
    topic = args.topic or input("Enter podcast topic: ").strip()
    if not topic:
        sys.exit(1)
    run(topic, repo_root=Path(args.repo))
