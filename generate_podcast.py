#!/usr/bin/env python3
"""
Asynchronous Podcast Generator
Generates a two-host curiosity-radio episode on any topic.
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

import llm_engines
import tts_engines
from episode_manifest import EpisodeManifest, slugify_topic
from episode_types import episode_type_context, episode_type_label, normalize_episode_type
from job_control import acquire_generation_lock
from personal_context import (
    bounded_personal_context,
    load_personal_context,
    personal_context_prompt,
    record_topic,
    save_personal_context,
)
from sonic_footnotes import (
    compact_sonic_footnote_catalog,
    load_sonic_footnotes_catalog,
    normalize_sonic_footnote_plan,
    sonic_footnote_attributions,
)
from secret_env import load_secret_env

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)
load_secret_env(Path(__file__).parent)

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
    "research_model":       _RESEARCH_MODEL,
    "dialogue_model":       _DIALOGUE_MODEL,
    "fact_check_model":     _FACT_CHECK_MODEL,
    "local_llm_provider":   "ollama",
    "local_llm_base_url":   "http://127.0.0.1:11434",
    "local_llm_api_key_env": "LOCAL_LLM_API_KEY",
    "local_llm_timeout_sec": 3600,
    "local_llm_num_ctx":    32768,
    "local_llm_keep_alive": "30m",
    "local_llm_think":      False,
    "tts_provider":         "openai",
    "host_a_name":          "Cedar",
    "host_a_voice":         "cedar",
    "host_a_role":          "artistic",
    "host_b_name":          "Marin",
    "host_b_voice":         "marin",
    "host_b_role":          "scientific",
    "elevenlabs_voice_id_a": "",
    "elevenlabs_voice_id_b": "",
    "elevenlabs_guest_voice_ids": "",
    "elevenlabs_model":     "eleven_turbo_v2",
    "elevenlabs_stability": 0.5,
    "elevenlabs_similarity_boost": 0.75,
    "target_minutes":       15,
    "output_dir":           "episodes",
    "episode_type":         "deep_dive",
    "learning_path_dir":    "learning_paths",
    "learning_path_default_episodes": 5,
    "learning_path_default_level": "beginner-to-intermediate",
    "learning_path_model":  "claude-sonnet-4-6",
    "use_clips":            False,
    "use_music":            True,
    "use_sonic_footnotes":  True,
    "sonic_footnotes_catalog": "sonic_footnotes.json",
    "use_guest_hosts":      True,
    "guest_host_mode":      "auto",
    "guest_host_max":       1,
    "guest_host_voice_pool": "ash,ballad,coral,sage,shimmer,echo,onyx,nova,alloy,fable",
    "script_quality_pipeline": True,
    "host_memory_path":     "host_memory.json",
    "host_memory_max_episodes": 12,
    "host_memory_max_items": 18,
    "use_personal_context": True,
    "personal_context_path": "personal_context.json",
    "personal_context_max_topics": 24,
    "personal_context_similarity_threshold": 0.34,
    "personal_context_sync_manifests": True,
    "tts_model":            "gpt-4o-mini-tts",
    "tts_default_route":    {},
    "tts_routes":           {},
    "tts_request_timeout_sec": 180,
    "tts_command":          "",
    "tts_command_cwd":      "",
    "tts_command_timeout_sec": 600,
    "use_emotive_tts":      True,
    "turn_silence_ms":      180,
    "use_audio_mastering":  True,
    "audio_bitrate":        "192k",
    "audio_sample_rate":    44100,
    "audio_channels":       2,
    "audio_loudness_i":     -16.0,
    "audio_true_peak":      -1.5,
    "audio_lra":            11.0,
    "audio_highpass_hz":    60,
    "audio_lowpass_hz":     18000,
    "music_prompt_model":   "claude-haiku-4-5-20251001",
    "title_model":          "claude-haiku-4-5-20251001",
    "music_model":          "facebook/musicgen-small",
    "music_duration_sec":   12,
    "music_fade_sec":       2,
}

_BOOL_CONFIG_KEYS = {
    "use_clips",
    "use_music",
    "use_emotive_tts",
    "script_quality_pipeline",
    "use_sonic_footnotes",
    "use_guest_hosts",
    "use_personal_context",
    "personal_context_sync_manifests",
    "use_audio_mastering",
    "local_llm_think",
}
_INT_CONFIG_KEYS = {
    "target_minutes",
    "learning_path_default_episodes",
    "music_duration_sec",
    "host_memory_max_episodes",
    "host_memory_max_items",
    "guest_host_max",
    "personal_context_max_topics",
    "local_llm_timeout_sec",
    "local_llm_num_ctx",
    "turn_silence_ms",
    "tts_request_timeout_sec",
    "tts_command_timeout_sec",
    "audio_sample_rate",
    "audio_channels",
    "audio_highpass_hz",
    "audio_lowpass_hz",
}
_FLOAT_CONFIG_KEYS = {
    "music_fade_sec",
    "personal_context_similarity_threshold",
    "audio_loudness_i",
    "audio_true_peak",
    "audio_lra",
    "elevenlabs_stability",
    "elevenlabs_similarity_boost",
}
_JSON_CONFIG_KEYS = {
    "tts_default_route",
    "tts_routes",
}
_VALID_TTS_PROVIDERS = set(tts_engines.SUPPORTED_TTS_PROVIDERS)
_VALID_GUEST_HOST_MODES = {"off", "auto", "force"}

_DEFAULT_HOST_MEMORY: dict = {
    "schema_version": 1,
    "show": {
        "name": "Asynchronous",
        "promise": (
            "A personal curiosity show where two recurring synthetic hosts turn "
            "stray questions into source-grounded, emotionally alive episodes."
        ),
        "style_principles": [
            "Argument with affection beats polite Q&A.",
            "Concrete scenes beat abstract summaries.",
            "Citations belong mostly in metadata and show notes, not spoken lists.",
            "The hosts may be wrong briefly, revise themselves, and leave some tension unresolved.",
        ],
    },
    "hosts": {
        "CEDAR": {
            "core": "Art-minded, associative, warm, impatient with sterile explanations.",
            "strengths": [
                "Finds metaphors from ordinary objects.",
                "Notices emotional and cultural stakes quickly.",
                "Is willing to say the strange thought first.",
            ],
            "blind_spots": [
                "Can fall in love with a metaphor before checking if it is true.",
                "Sometimes wants the story to be more elegant than reality.",
            ],
            "speech_habits": [
                "Short vivid images.",
                "Small self-corrections.",
                "Occasional dry understatement when surprised.",
            ],
            "avoid": [
                "Generic awe.",
                "Perfect poetic monologues.",
                "Asking Marin to explain every fact.",
            ],
        },
        "MARIN": {
            "core": "Scientifically grounded, dry, careful, allergic to fake certainty.",
            "strengths": [
                "Names evidence and limits without killing the mood.",
                "Enjoys a correction when it makes the story better.",
                "Can admit when the data is messier than his first answer.",
            ],
            "blind_spots": [
                "Can hide behind precision when a human question needs a human answer.",
                "Sometimes underestimates Cedar's intuition.",
            ],
            "speech_habits": [
                "Plain-language caveats.",
                "Quiet jokes.",
                "Specific names, dates, and mechanisms when they matter.",
            ],
            "avoid": [
                "Pedantic lectures.",
                "Constant 'well actually' posture.",
                "Being only the fact machine.",
            ],
        },
    },
    "relationship": {
        "chemistry": (
            "Cedar pulls Marin toward meaning; Marin pulls Cedar toward evidence. "
            "They like each other enough to disagree without flattening the disagreement."
        ),
        "recurring_dynamics": [
            "Cedar makes a leap; Marin tests it; both keep part of it.",
            "Marin starts certain, then finds the caveat that makes him less certain.",
            "Cedar notices when the science has a human cost.",
        ],
    },
    "shared_memories": [],
    "episode_history": [],
    "phrase_blacklist": [
        "that's the thing",
        "this changes everything",
        "wait, so you're saying",
        "it's not just",
        "what does this mean for us",
        "the data tells a story",
    ],
}


def _parse_bool(value: object, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    val = str(value).strip().lower()
    if val in {"1", "true", "yes", "on"}:
        return True
    if val in {"0", "false", "no", "off", ""}:
        return False
    raise ValueError(
        f"{name} must be a boolean value: one of true/false, yes/no, on/off, 1/0"
    )


def _coerce_config_value(key: str, value: object) -> object:
    if key in _BOOL_CONFIG_KEYS:
        return _parse_bool(value, key)
    if key in _INT_CONFIG_KEYS:
        return int(value)
    if key in _FLOAT_CONFIG_KEYS:
        return float(value)
    if key in _JSON_CONFIG_KEYS and isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return {}
        try:
            return json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{key} must be valid JSON when provided as a string") from exc
    return value


def _audio_bitrate_value(cfg: dict) -> str:
    bitrate = str(cfg.get("audio_bitrate") or "192k").strip().lower()
    if not re.fullmatch(r"\d+[km]?", bitrate):
        raise ValueError("audio_bitrate must look like 192k, 256k, or 2m")
    return bitrate


def _should_skip_git() -> bool:
    return _parse_bool(os.environ.get("SKIP_GIT", "0"), "SKIP_GIT")


def load_config(repo_root: Path = Path(".")) -> dict:
    cfg = dict(DEFAULTS)
    cfg_path = repo_root / "config.json"
    if cfg_path.exists():
        with open(cfg_path, encoding="utf-8") as f:
            file_cfg = json.load(f)
        for key, value in file_cfg.items():
            if key in cfg:
                cfg[key] = _coerce_config_value(key, value)

    for cfg_key in DEFAULTS:
        env_key = cfg_key.upper()
        val = os.environ.get(env_key)
        if val is not None:
            cfg[cfg_key] = _coerce_config_value(cfg_key, val)

    cfg["tts_provider"] = str(cfg["tts_provider"]).lower()
    if cfg["tts_provider"] not in _VALID_TTS_PROVIDERS:
        raise ValueError(
            f"Unsupported tts_provider {cfg['tts_provider']!r}; "
            f"expected one of {sorted(_VALID_TTS_PROVIDERS)}"
        )
    if not isinstance(cfg.get("tts_default_route"), dict):
        raise ValueError("tts_default_route must be an object")
    if not isinstance(cfg.get("tts_routes"), dict):
        raise ValueError("tts_routes must be an object keyed by speaker label")
    cfg["guest_host_mode"] = str(cfg.get("guest_host_mode") or "auto").lower()
    if not cfg.get("use_guest_hosts", True):
        cfg["guest_host_mode"] = "off"
    if cfg["guest_host_mode"] not in _VALID_GUEST_HOST_MODES:
        raise ValueError(
            f"Unsupported guest_host_mode {cfg['guest_host_mode']!r}; "
            f"expected one of {sorted(_VALID_GUEST_HOST_MODES)}"
        )
    cfg["episode_type"] = normalize_episode_type(str(cfg.get("episode_type", "")))
    if int(cfg["target_minutes"]) <= 0:
        raise ValueError("target_minutes must be greater than 0")
    if int(cfg["music_duration_sec"]) <= 0:
        raise ValueError("music_duration_sec must be greater than 0")
    if int(cfg["learning_path_default_episodes"]) <= 0:
        raise ValueError("learning_path_default_episodes must be greater than 0")
    if int(cfg["host_memory_max_episodes"]) <= 0:
        raise ValueError("host_memory_max_episodes must be greater than 0")
    if int(cfg["host_memory_max_items"]) <= 0:
        raise ValueError("host_memory_max_items must be greater than 0")
    if int(cfg["guest_host_max"]) < 0:
        raise ValueError("guest_host_max must be zero or greater")
    if int(cfg["personal_context_max_topics"]) <= 0:
        raise ValueError("personal_context_max_topics must be greater than 0")
    if int(cfg["local_llm_timeout_sec"]) <= 0:
        raise ValueError("local_llm_timeout_sec must be greater than 0")
    if int(cfg["local_llm_num_ctx"]) <= 0:
        raise ValueError("local_llm_num_ctx must be greater than 0")
    if int(cfg["turn_silence_ms"]) < 0:
        raise ValueError("turn_silence_ms must be zero or greater")
    if int(cfg["tts_request_timeout_sec"]) <= 0:
        raise ValueError("tts_request_timeout_sec must be greater than 0")
    if int(cfg["tts_command_timeout_sec"]) <= 0:
        raise ValueError("tts_command_timeout_sec must be greater than 0")
    if int(cfg["audio_sample_rate"]) <= 0:
        raise ValueError("audio_sample_rate must be greater than 0")
    if int(cfg["audio_channels"]) not in {1, 2}:
        raise ValueError("audio_channels must be 1 or 2")
    if float(cfg["audio_lra"]) <= 0:
        raise ValueError("audio_lra must be greater than 0")
    if int(cfg["audio_highpass_hz"]) < 0:
        raise ValueError("audio_highpass_hz must be zero or greater")
    if int(cfg["audio_lowpass_hz"]) < 0:
        raise ValueError("audio_lowpass_hz must be zero or greater")
    _audio_bitrate_value(cfg)
    if float(cfg["music_fade_sec"]) < 0:
        raise ValueError("music_fade_sec must be zero or greater")
    threshold = float(cfg["personal_context_similarity_threshold"])
    if threshold < 0 or threshold > 1:
        raise ValueError("personal_context_similarity_threshold must be between 0 and 1")
    return cfg


# ── System prompts ─────────────────────────────────────────────────────────────

_RESEARCH_SYSTEM = """\
You are an expert researcher and science communicator.
Your task: produce a detailed research package — NOT a script.

The research should contain:
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
- Follow the user's requested output format exactly.
- This package feeds a dialogue script, so include story angles and emotional resonance.
"""

_DIALOGUE_SYSTEM = """\
You are writing a podcast script for "Asynchronous" — a curious, source-grounded
two-host audio show.

The two hosts are:
- CEDAR: Artistic, broad-thinking, asks "what does this MEAN for us?" She finds
  unexpected metaphors and connections. She's enthusiastic and sometimes goes on
  tangents that turn out to be useful. She speaks with warmth and wonder.
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

Rules for great research-radio dialogue:
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

_THESIS_SYSTEM = """\
You are the story editor for "Asynchronous", a two-host curiosity audio show.
Create a concise editorial memo for an episode.

Return plain Markdown with these sections only:
- Thesis
- Audience Promise
- Why This Matters Now
- Ending We Are Aiming For
- Cold Open Options
- Risks And Things To Avoid

Make the memo specific to the topic and the source material. Avoid generic stakes.
"""

_BEAT_SHEET_SYSTEM = """\
You are building the episode map before dialogue is written.

Create 8-12 beats. Each beat must include:
- Beat id, purpose, and rough length
- Concrete scene, object, person, place, or question anchoring the beat
- What Cedar believes or feels at the start of the beat
- What Marin challenges, complicates, or admits
- Key claims or sources used
- Turning point by the end of the beat
- Transition into the next beat

Rules:
- Build an arc, not a list of facts.
- Include one affectionate disagreement.
- Let at least one host be wrong briefly and recover.
- Avoid symmetrical "Cedar wonders, Marin explains" repetition.
- Move most source detail to show notes; spoken source mentions need story value.
Return Markdown only.
"""

_GUEST_PLANNER_SYSTEM = """\
You are the guest-booking producer for "Asynchronous".

Decide whether this episode needs a synthetic/composite guest expert voice.
Return JSON only:
{
  "decision": "skip" | "use",
  "format": "guest_host" | "interview",
  "rationale": "...",
  "guests": [
    {
      "label": "UPPERCASE SPEAKER LABEL",
      "display_name": "Name used in notes",
      "field": "domain of expertise",
      "credential_frame": "why this composite voice has authority",
      "expertise": "what they can explain better than Cedar or Marin",
      "personality": "specific conversational personality, not a generic expert",
      "role_in_episode": "what beats they improve",
      "delivery_baseline": "short TTS direction",
      "voice": "one voice id from the provided pool",
      "boundaries": ["claims they should not overstate"]
    }
  ],
  "integration_notes": ["where they enter, what they change, when they leave"]
}

Rules:
- Most episodes should skip guests unless expertise or point-of-view clearly improves the show.
- Use at most __MAX_GUESTS__ guest(s).
- Guest personas must be fictional/synthetic composites, not real people and not impersonations.
- Do not invent a real affiliation, title, or institution.
- Speaker labels must use only A-Z letters and spaces. No punctuation. No CEDAR or MARIN.
- Each guest needs an independent personality and a distinct voice from the provided pool.
- A guest should complicate or sharpen the episode, not deliver a polished lecture.
- If the episode type is complete_fiction, skip unless the user explicitly forced a guest.
"""

_DIALOGUE_DRAFT_SYSTEM = """\
You are drafting the first full dialogue for "Asynchronous".

Write only dialogue lines in this exact format:
CEDAR [delivery tag]: text
MARIN [delivery tag]: text
OPTIONAL GUEST LABEL [delivery tag]: text

Character rules:
- Cedar is associative, visual, emotionally perceptive, and sometimes too eager to make meaning.
- Marin is careful, dry, scientifically grounded, and sometimes too protected by caveats.
- They know each other. They can interrupt, misunderstand, correct, tease, and recover.
- Their disagreement should feel affectionate, not hostile.
- If the guest plan says "use", include only the guest labels from that plan.
- Never use the literal placeholder "OPTIONAL GUEST LABEL".
- Guest voices are synthetic/composite expert personas. They should sound like specific people
  with boundaries and quirks, but must not impersonate real people or claim real affiliations.

Writing rules:
- Start with a concrete scene, object, person, or sensory image in the first 60 seconds.
- Follow the beat sheet, but do not announce sections or headers.
- Use the host memory for callbacks sparingly. One callback is enough unless the topic naturally asks for more.
- Use specific evidence, but do not end with a bibliography-style source list.
- Keep citations mostly implicit and natural: "a 2024 review", "the Stanford group", "historian X".
- If a guest appears, let Cedar and Marin interview, challenge, and react to them.
  The guest should enter for the beats where they add authority, then get out of the way.
- Let some turns be short. Let small jokes stay small.
- Avoid tidy TED-talk sentences and symmetrical Q&A.
- Target {target_words} words total, but end naturally.
"""

_ANTI_CLICHE_SYSTEM = """\
You are the anti-AI rewrite editor for "Asynchronous".
Rewrite the script to sound more human, less templated, and less evenly polished.

Return only dialogue lines in this exact format:
CEDAR [delivery tag]: text
MARIN [delivery tag]: text
OPTIONAL GUEST LABEL [delivery tag]: text
OPTIONAL GUEST LABEL [delivery tag]: text

Preserve factual content and the episode arc. You may tighten, rearrange within a beat,
cut filler, add tiny reactions, and make the hosts less symmetrical.
Preserve guest labels and guest personalities when a guest plan is present.
Never use the literal placeholder "OPTIONAL GUEST LABEL".

Remove or sharply limit:
- "that's the thing"
- "this changes everything"
- "wait, so you're saying"
- "it's not just X, it's Y"
- "the data tells a story"
- generic awe without concrete detail
- repeated skeptical/wonder role symmetry
- source-list narration

Add instead:
- concrete verbs and nouns
- a few imperfect, self-correcting lines
- one brief affectionate challenge
- one moment where a host revises their own view
- varied turn length
"""

_SONIC_FOOTNOTE_SYSTEM = """\
You are the sonic footnote editor for "Asynchronous".

Your job is to decide whether the episode would benefit from a tiny, rights-aware
open-source audio flourish. Most episodes should use zero. Use one only when it
demonstrates, clarifies, or emotionally sharpens a specific beat.

Return JSON only:
{
  "decision": "skip" | "use",
  "rationale": "...",
  "cues": [
    {
      "catalog_id": "...",
      "beat": "B03 or short beat description",
      "placement": "after Cedar's opening image / before Marin explains X / etc.",
      "duration_sec": 4,
      "reason": "why the sound adds meaning",
      "script_note": "how the hosts should make room for it without saying 'sound effect'",
      "license_note": "what must be verified or credited"
    }
  ]
}

Rules:
- Choose at most __MAX_CUES__ cues.
- Each cue must be at most __MAX_DURATION_SEC__ seconds.
- Choose only from the provided catalog.
- Do not choose a cue as decoration or a joke.
- If the catalog does not contain a truly relevant option, return decision "skip" and an empty cues array.
- If a catalog item says it requires file or item verification, say that in license_note.
"""

_FACT_CHECK_SYSTEM = """\
You are a rigorous fact-checker for a podcast.
Review the dialogue script below and silently correct any inaccurate, exaggerated,
or unverifiable claims directly in the dialogue — do not add markers or annotations.

Rules:
- Return ONLY the corrected script in the same speaker-label dialogue format.
- If a claim cannot be verified, soften the language ("some evidence suggests…")
  rather than stating it as fact.
- Do NOT append a corrections list, accuracy rating, editorial notes, or any section
  that is not part of the dialogue itself.
- Do NOT restructure, reorder, or add new dialogue turns.
- Preserve speaker labels AND emotion tags exactly as-is, including guest labels.
- Guest personas are synthetic/composite expert voices; do not turn them into real people
  or add fake affiliations.
"""

_FICTION_CONTINUITY_SYSTEM = """\
You are the continuity and safety editor for a fictional two-voice audio story.

Return only dialogue lines in this exact format:
CEDAR [delivery tag]: text
MARIN [delivery tag]: text

Rules:
- Preserve the fictional premise, invented events, emotional arc, and speaker labels.
- Never use the literal placeholder "OPTIONAL GUEST LABEL".
- Do not fact-check fictional worldbuilding as if it were reportage.
- Fix internal contradictions, unclear references, pacing snags, and spoken lines that would confuse TTS.
- Remove fake source citations, fake factual asides, or anything that presents invented events as real-world reporting.
- If real people, real companies, or real institutions appear, avoid defamatory invented actions and make the fictional frame clear in dialogue.
- Do not append notes, continuity comments, source lists, or section headers.
"""

_PERFORMANCE_SYSTEM = """\
You are the final performance editor for a conversational TTS podcast script.

Return only dialogue lines in this exact format:
CEDAR [delivery tag]: text
MARIN [delivery tag]: text
OPTIONAL GUEST LABEL [delivery tag]: text

Rules:
- Preserve facts, claims, episode order, and speaker ownership.
- Preserve any guest labels, guest personalities, and the guest's distinct point-of-view.
- Never use the literal placeholder "OPTIONAL GUEST LABEL".
- Keep delivery tags short and playable: 1-4 words.
- Do not make every line highly emotional.
- Add pauses, overlaps, laugh/breath marks, or interruptions only where they truly help.
- Remove text that would sound like stage directions if spoken.
- Make the opening and ending feel intentional, not over-written.
"""

_MEMORY_UPDATE_SYSTEM = """\
You update a small persistent host-memory file for "Asynchronous".

Return JSON only with this shape:
{
  "episode_history_entry": {
    "topic": "...",
    "cedar_noticed": "...",
    "marin_challenged": "...",
    "relationship_moment": "...",
    "usable_callback": "..."
  },
  "new_shared_memories": [
    {
      "summary": "...",
      "tags": ["..."],
      "why_keep": "..."
    }
  ],
  "phrase_blacklist_additions": ["..."]
}

Keep only memories that would help future episodes sound like the same hosts.
Do not add generic facts from the topic unless they became a relationship callback.
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


def _model_for(cfg: dict, key: str, fallback: str) -> str:
    return str(cfg.get(key) or fallback)


def _anthropic_text(
    client: anthropic.Anthropic | None,
    *,
    model: str,
    system: str,
    content: str,
    max_tokens: int,
    tools: list | None = None,
    temperature: float | None = None,
    cfg: dict | None = None,
) -> str:
    if llm_engines.is_local_model(model):
        if tools:
            raise ValueError(
                f"Local model route {model!r} cannot use Anthropic tools. "
                "Keep web-search stages on Claude, or disable the tool-using stage."
            )
        return llm_engines.generate_text(
            model=model,
            system=system,
            content=content,
            max_tokens=max_tokens,
            cfg=cfg or {},
            temperature=temperature,
        )
    if client is None:
        raise ValueError(
            f"ANTHROPIC_API_KEY is required for cloud model {model!r}. "
            "Use a local: or ollama: model for tool-free stages if you want to avoid it."
        )
    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": content}],
    }
    if tools is not None:
        kwargs["tools"] = tools
    if temperature is not None:
        kwargs["temperature"] = temperature
    resp = client.messages.create(**kwargs)
    return _extract_text(resp.content)


def _extract_json_object(text: str) -> dict | None:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.I)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        parsed = json.loads(stripped)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(stripped[start : end + 1])
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _strip_to_dialogue(script: str) -> str:
    script = re.sub(r"\[CORRECTION:[^\]]*\]", "", script)
    script = _strip_corrections_appendix(script)
    first_turn = re.search(
        r"^([A-Z][A-Z ]{1,40})(?:\s*\[[^\]]*\])?\s*:",
        script,
        re.MULTILINE,
    )
    if first_turn:
        script = script[first_turn.start():]
    return script.strip()


def _memory_path(repo_root: Path, cfg: dict) -> Path:
    raw = Path(str(cfg.get("host_memory_path") or "host_memory.json"))
    return raw if raw.is_absolute() else repo_root / raw


def _clone_default_memory() -> dict:
    return json.loads(json.dumps(_DEFAULT_HOST_MEMORY))


def _save_host_memory(path: Path, memory: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    memory["updated_at"] = datetime.now(timezone.utc).isoformat()
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
        prefix=f".{path.name}.",
        suffix=".tmp",
    ) as tmp:
        json.dump(memory, tmp, indent=2, sort_keys=True)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def _load_host_memory(repo_root: Path, cfg: dict) -> tuple[dict, Path]:
    path = _memory_path(repo_root, cfg)
    if not path.exists():
        memory = _clone_default_memory()
        _save_host_memory(path, memory)
        return memory, path
    try:
        memory = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(memory, dict):
            raise ValueError("host memory root is not an object")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        logger.warning(f"Host memory could not be read ({exc}); using defaults")
        memory = _clone_default_memory()
    return memory, path


def _bounded_host_memory(memory: dict, cfg: dict) -> dict:
    max_items = int(cfg.get("host_memory_max_items", 18))
    max_episodes = int(cfg.get("host_memory_max_episodes", 12))
    bounded = json.loads(json.dumps(memory))
    bounded["shared_memories"] = list(bounded.get("shared_memories", []))[-max_items:]
    bounded["episode_history"] = list(bounded.get("episode_history", []))[-max_episodes:]
    return bounded


def _host_memory_prompt(memory: dict, cfg: dict) -> str:
    return json.dumps(_bounded_host_memory(memory, cfg), indent=2, sort_keys=True)


def _personal_context_for_topic(
    repo_root: Path,
    cfg: dict,
    topic: str,
) -> tuple[dict, Path | None, dict, str]:
    if not cfg.get("use_personal_context", True):
        return {}, None, {}, "Personal context mode is disabled."
    context, context_path = load_personal_context(repo_root, cfg)
    snapshot = bounded_personal_context(
        context,
        max_topics=int(cfg.get("personal_context_max_topics", 24)),
    )
    return context, context_path, snapshot, personal_context_prompt(context, topic, cfg)


def _record_personal_topic(
    *,
    context: dict,
    context_path: Path | None,
    cfg: dict,
    topic: str,
    episode_type: str,
    episode_type_label_text: str,
    run_id: str,
    word_count: int | None,
    source_count: int | None,
) -> dict:
    if not context_path or not cfg.get("use_personal_context", True):
        return {}
    entry = record_topic(
        context,
        topic=topic,
        episode_type=episode_type,
        episode_type_label=episode_type_label_text,
        run_id=run_id,
        word_count=word_count,
        source_count=source_count,
    )
    max_topics = int(cfg.get("personal_context_max_topics", 24))
    context["topic_history"] = list(context.get("topic_history", []))[-max_topics:]
    save_personal_context(context_path, context)
    return entry


def _source_labels_from_cards(cards: list | None) -> list:
    labels: list = []
    for card in cards or []:
        if not isinstance(card, dict):
            continue
        title = str(card.get("title") or card.get("source") or "").strip()
        publication = str(card.get("publication") or card.get("publisher") or "").strip()
        year = str(card.get("year") or "").strip()
        url = str(card.get("url") or "").strip()
        parts = [p for p in [title, publication, year] if p]
        label = " - ".join(parts)
        if url:
            label = f"{label} ({url})" if label else url
        if label:
            labels.append(label)
    return labels[:12]


def _csv_list(value: object) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = str(value or "").split(",")
    return [str(item).strip() for item in raw_items if str(item).strip()]


def _guest_host_mode(cfg: dict) -> str:
    if not cfg.get("use_guest_hosts", True):
        return "off"
    mode = str(cfg.get("guest_host_mode") or "auto").lower().strip()
    return mode if mode in _VALID_GUEST_HOST_MODES else "auto"


def _guest_voice_pool(cfg: dict) -> list[str]:
    voices = _csv_list(cfg.get("guest_host_voice_pool"))
    host_voices = {
        str(cfg.get("host_a_voice") or "").strip().lower(),
        str(cfg.get("host_b_voice") or "").strip().lower(),
    }
    distinct = [voice for voice in voices if voice.lower() not in host_voices]
    return distinct or voices or [str(cfg.get("host_a_voice") or "cedar")]


def _fallback_guest_label(index: int) -> str:
    labels = ["GUEST EXPERT", "GUEST ANALYST", "GUEST GUIDE", "GUEST CRITIC"]
    return labels[index] if index < len(labels) else f"GUEST {chr(65 + (index % 26))}"


def _sanitize_guest_label(value: object, index: int, used: set[str]) -> str:
    label = re.sub(r"[^A-Za-z ]+", " ", str(value or ""))
    label = re.sub(r"\s+", " ", label).strip().upper()
    if not label or label in {"CEDAR", "MARIN"}:
        label = _fallback_guest_label(index)
    words = label.split()
    if len(label) > 28:
        label = " ".join(words[:3]).strip() or _fallback_guest_label(index)
    if label in {"CEDAR", "MARIN"}:
        label = _fallback_guest_label(index)
    base = label
    suffix_index = 0
    while label in used:
        suffix = chr(65 + (suffix_index % 26))
        label = f"{base} {suffix}"
        suffix_index += 1
    used.add(label)
    return label


def _normalize_guest_plan(plan: dict | None, cfg: dict, *, force: bool = False) -> dict:
    max_guests = int(cfg.get("guest_host_max", 1))
    if force and max_guests <= 0:
        max_guests = 1
    if max_guests <= 0:
        return {
            "decision": "skip",
            "format": "none",
            "rationale": "Guest hosts are disabled by guest_host_max=0.",
            "guests": [],
            "integration_notes": [],
        }

    plan = plan if isinstance(plan, dict) else {}
    raw_guests = plan.get("guests") if isinstance(plan.get("guests"), list) else []
    if force and not raw_guests:
        raw_guests = [
            {
                "label": "GUEST EXPERT",
                "display_name": "Guest Expert",
                "field": "topic-specific domain expertise",
                "credential_frame": "Synthetic composite expert persona built from the research package.",
                "expertise": "Adds domain authority, caveats, and concrete examples.",
                "personality": "Plain-spoken, precise, mildly wry, and willing to push back.",
                "role_in_episode": "Enters for the most technical or high-stakes beats.",
                "delivery_baseline": "authoritative, warm, concise",
            }
        ]

    voice_pool = _guest_voice_pool(cfg)
    used_labels = {"CEDAR", "MARIN"}
    guests: list[dict] = []
    for idx, item in enumerate(raw_guests[:max_guests]):
        if not isinstance(item, dict):
            continue
        label = _sanitize_guest_label(
            item.get("label") or item.get("display_name") or item.get("field"),
            idx,
            used_labels,
        )
        voice = str(item.get("voice") or "").strip()
        if voice not in voice_pool:
            voice = voice_pool[len(guests) % len(voice_pool)]
        display_name = str(item.get("display_name") or label.title()).strip()
        field = str(item.get("field") or "domain expertise").strip()
        guests.append(
            {
                "label": label,
                "display_name": display_name,
                "field": field,
                "credential_frame": str(
                    item.get("credential_frame")
                    or "Synthetic composite expert persona based on the episode research."
                ).strip(),
                "expertise": str(item.get("expertise") or field).strip(),
                "personality": str(
                    item.get("personality")
                    or "Specific, conversational, careful with uncertainty."
                ).strip(),
                "role_in_episode": str(
                    item.get("role_in_episode")
                    or "Adds expert context where Cedar and Marin need outside authority."
                ).strip(),
                "delivery_baseline": str(
                    item.get("delivery_baseline") or "authoritative, conversational"
                ).strip(),
                "voice": voice,
                "boundaries": [
                    str(boundary).strip()
                    for boundary in item.get("boundaries", [])
                    if str(boundary).strip()
                ][:6],
                "synthetic": True,
            }
        )

    decision = "use" if (force or str(plan.get("decision")).lower() == "use") and guests else "skip"
    return {
        "decision": decision,
        "format": str(plan.get("format") or ("interview" if guests else "none")),
        "rationale": str(plan.get("rationale") or "").strip(),
        "guests": guests if decision == "use" else [],
        "integration_notes": [
            str(note).strip()
            for note in plan.get("integration_notes", [])
            if str(note).strip()
        ][:8],
        "voice_pool": voice_pool,
        "mode": _guest_host_mode(cfg),
    }


def _plan_guest_hosts(
    topic: str,
    episode_type: str,
    type_note: str,
    research_package: dict,
    thesis: str,
    cfg: dict,
    client: anthropic.Anthropic | None,
) -> dict:
    mode = _guest_host_mode(cfg)
    force = mode == "force"
    if mode == "off":
        return {
            "decision": "skip",
            "format": "none",
            "rationale": "Guest hosts are disabled.",
            "guests": [],
            "integration_notes": [],
            "mode": mode,
        }
    if episode_type == "complete_fiction" and not force:
        return {
            "decision": "skip",
            "format": "none",
            "rationale": "Guest expert mode is skipped for complete fiction unless forced.",
            "guests": [],
            "integration_notes": [],
            "mode": mode,
        }

    configured_max = int(cfg.get("guest_host_max", 1))
    if configured_max <= 0 and not force:
        return {
            "decision": "skip",
            "format": "none",
            "rationale": "Guest hosts are disabled by guest_host_max=0.",
            "guests": [],
            "integration_notes": [],
            "mode": mode,
        }
    max_guests = max(1 if force else 0, configured_max)
    voice_pool = _guest_voice_pool(cfg)
    raw_plan = _anthropic_text(
        client,
        model=_model_for(cfg, "dialogue_model", _DIALOGUE_MODEL),
        max_tokens=2048,
        system=_GUEST_PLANNER_SYSTEM.replace("__MAX_GUESTS__", str(max_guests)),
        content=(
            f"Topic: {topic}\n\n"
            f"{type_note}\n\n"
            f"Guest mode: {mode}. {'The user explicitly requested a guest.' if force else 'Use a guest only if it truly improves the episode.'}\n"
            f"Available voice pool: {', '.join(voice_pool)}\n\n"
            f"Editorial memo:\n{thesis}\n\n"
            f"Research package:\n{json.dumps(research_package, indent=2)[:22000]}"
        ),
        temperature=0.35,
        cfg=cfg,
    )
    return _normalize_guest_plan(_extract_json_object(raw_plan), cfg, force=force)


def _script_quality_metrics(script: str, memory: dict, cfg: dict | None = None) -> dict:
    lowered = script.lower()
    blacklist = memory.get("phrase_blacklist", _DEFAULT_HOST_MEMORY["phrase_blacklist"])
    hits = {
        phrase: lowered.count(str(phrase).lower())
        for phrase in blacklist
        if str(phrase).strip() and str(phrase).lower() in lowered
    }
    cedar_turns = len(re.findall(r"^CEDAR(?:\s*\[[^\]]*\])?\s*:", script, re.M))
    marin_turns = len(re.findall(r"^MARIN(?:\s*\[[^\]]*\])?\s*:", script, re.M))
    guest_labels = {
        match.group(1).strip().upper()
        for match in re.finditer(_TURN_RE.pattern, script, re.M)
        if match.group(1).strip().upper() not in {"CEDAR", "MARIN"}
    }
    active_guest_labels = {
        str(guest.get("label", "")).upper()
        for guest in (cfg or {}).get("active_guest_hosts", [])
        if isinstance(guest, dict)
    }
    guest_labels = guest_labels | {label for label in active_guest_labels if label}
    return {
        "cedar_turns": cedar_turns,
        "marin_turns": marin_turns,
        "guest_turns": sum(
            len(re.findall(rf"^{re.escape(label)}(?:\s*\[[^\]]*\])?\s*:", script, re.M))
            for label in guest_labels
        ),
        "guest_labels": sorted(guest_labels),
        "anti_ai_phrase_hits": hits,
    }


def _fallback_episode_title(topic: str) -> str:
    """Truncate a raw topic into a usable title when LLM generation isn't available."""
    cleaned = re.sub(r"\s+", " ", topic).strip().strip(".,;:!?-")
    if not cleaned:
        return "Untitled Episode"
    if len(cleaned) <= 70:
        return cleaned
    return cleaned[:67].rstrip() + "..."


def _generate_episode_title(
    topic: str,
    thesis: str | None,
    cfg: dict,
    client: "anthropic.Anthropic | None",
) -> str:
    """Summarize the user's raw topic into a 3-7 word episode title.

    Returns a fallback truncation of the topic if the LLM call fails or the
    response is unusable. Never raises.
    """
    fallback = _fallback_episode_title(topic)
    if client is None:
        return fallback

    model = _model_for(cfg, "title_model", "claude-haiku-4-5-20251001")
    system = (
        "You write short, evocative episode titles for Asynchronous, a "
        "curiosity-radio show with two hosts (Cedar and Marin) that turns "
        "a listener's question into a 20-30 minute source-grounded deep dive.\n\n"
        "Rules:\n"
        " - 3 to 7 words. Hard limit.\n"
        " - Specific and concrete; suggest the angle or question, not the textbook chapter.\n"
        " - Title Case.\n"
        " - No subtitles, colons, em-dashes, quotation marks, or trailing punctuation.\n"
        " - No filler: avoid 'A Deep Dive into', 'Exploring', 'Understanding', 'The Story of'.\n\n"
        "Examples:\n"
        "  Topic: explain how the NES audio processing unit creates chiptune sounds\n"
        "  Title: Inside the NES Sound Chip\n\n"
        "  Topic: history of the metronome and how it changed practice rooms\n"
        "  Title: How the Metronome Won Time\n\n"
        "  Topic: fetoscopy as a window into prenatal medicine\n"
        "  Title: Seeing Through the Womb\n\n"
        "  Topic: open source music generation tools landscape\n"
        "  Title: Music Models You Can Run at Home\n\n"
        "Respond with the title only. No explanation, no quotes."
    )
    user_lines = [f"Topic: {topic.strip()}"]
    if thesis and thesis.strip():
        user_lines.append("")
        user_lines.append(f"Episode thesis (for context):\n{thesis.strip()}")
    user_lines.append("")
    user_lines.append("Title:")
    content = "\n".join(user_lines)

    try:
        raw = _anthropic_text(
            client,
            model=model,
            system=system,
            content=content,
            max_tokens=64,
            temperature=0.6,
        )
    except Exception:
        logger.exception("Title generation failed; falling back to truncated topic.")
        return fallback

    title = (raw or "").strip()
    if not title:
        return fallback
    # Take only the first non-empty line in case the model added explanation.
    for line in title.splitlines():
        candidate = line.strip()
        if candidate:
            title = candidate
            break
    # Strip wrapping quotes/backticks and trailing punctuation the model may have added.
    title = title.strip("\"'`").strip().rstrip(".,;:!?")
    # If the model ignored "no subtitles", keep only the headline.
    for sep in (": ", " — ", " – ", " - "):
        if sep in title:
            title = title.split(sep, 1)[0].strip()
            break
    # Hard length cap: protect feed/UI from a runaway response.
    words = title.split()
    if len(words) > 10:
        title = " ".join(words[:10])
    if len(title) > 90:
        title = title[:87].rstrip() + "..."
    return title or fallback


def _plan_sonic_footnotes(
    topic: str,
    episode_type: str,
    type_note: str,
    research_package: dict,
    thesis: str,
    beat_sheet: str,
    catalog: dict,
    cfg: dict,
    client: anthropic.Anthropic | None,
) -> dict:
    compact_catalog = compact_sonic_footnote_catalog(catalog)
    policy = catalog.get("policy", {})
    max_cues = int(policy.get("max_per_episode", 2))
    max_duration = float(policy.get("max_duration_sec", 8))
    if not compact_catalog:
        return {
            "decision": "skip",
            "rationale": "No eligible sonic footnote catalog entries are available.",
            "cues": [],
            "policy": policy,
        }

    raw_plan = _anthropic_text(
        client,
        model=_model_for(cfg, "dialogue_model", _DIALOGUE_MODEL),
        max_tokens=2048,
        system=_SONIC_FOOTNOTE_SYSTEM.replace("__MAX_CUES__", str(max_cues)).replace(
            "__MAX_DURATION_SEC__", str(max_duration)
        ),
        content=(
            f"Topic: {topic}\n\n"
            f"{type_note}\n\n"
            f"Research package:\n{json.dumps(research_package, indent=2)[:18000]}\n\n"
            f"Editorial memo:\n{thesis}\n\n"
            f"Beat sheet:\n{beat_sheet}\n\n"
            f"Available sonic footnote catalog:\n{json.dumps(compact_catalog, indent=2)}"
        ),
        temperature=0.25,
        cfg=cfg,
    )
    return normalize_sonic_footnote_plan(_extract_json_object(raw_plan), catalog)


def _update_host_memory(
    topic: str,
    final_script: str,
    memory: dict,
    memory_path: Path,
    cfg: dict,
    client: anthropic.Anthropic | None,
    run_id: str = "",
) -> dict:
    content = (
        f"Topic: {topic}\n"
        f"Run ID: {run_id}\n\n"
        f"Existing host memory:\n{_host_memory_prompt(memory, cfg)}\n\n"
        f"Final script:\n{final_script[:18000]}"
    )
    try:
        raw_update = _anthropic_text(
            client,
            model=_model_for(cfg, "dialogue_model", _DIALOGUE_MODEL),
            max_tokens=1536,
            system=_MEMORY_UPDATE_SYSTEM,
            content=content,
            temperature=0.2,
            cfg=cfg,
        )
        update = _extract_json_object(raw_update) or {}
    except Exception as exc:
        logger.warning(f"Host memory update failed: {exc}")
        update = {}

    now = datetime.now(timezone.utc).isoformat()
    entry = update.get("episode_history_entry") if isinstance(update, dict) else None
    if not isinstance(entry, dict):
        entry = {
            "topic": topic,
            "cedar_noticed": "",
            "marin_challenged": "",
            "relationship_moment": "",
            "usable_callback": "",
        }
    entry.update({"run_id": run_id, "topic": topic, "created_at": now})
    memory.setdefault("episode_history", []).append(entry)

    additions = update.get("new_shared_memories", []) if isinstance(update, dict) else []
    for idx, item in enumerate(additions):
        if not isinstance(item, dict) or not item.get("summary"):
            continue
        item.setdefault("id", f"{run_id or 'memory'}_{idx + 1:02d}")
        item.setdefault("created_at", now)
        memory.setdefault("shared_memories", []).append(item)

    phrase_additions = update.get("phrase_blacklist_additions", []) if isinstance(update, dict) else []
    if isinstance(phrase_additions, list):
        current = {str(p).lower() for p in memory.get("phrase_blacklist", [])}
        for phrase in phrase_additions:
            phrase_text = str(phrase).strip()
            if phrase_text and phrase_text.lower() not in current:
                memory.setdefault("phrase_blacklist", []).append(phrase_text)
                current.add(phrase_text.lower())

    max_items = int(cfg.get("host_memory_max_items", 18))
    max_episodes = int(cfg.get("host_memory_max_episodes", 12))
    memory["shared_memories"] = list(memory.get("shared_memories", []))[-max_items:]
    memory["episode_history"] = list(memory.get("episode_history", []))[-max_episodes:]
    _save_host_memory(memory_path, memory)
    return update


def _extract_sources(script: str) -> list:
    lines = script.splitlines()
    sources: list = []
    in_sources = False
    for line in lines:
        stripped = re.sub(
            r'^([A-Z][A-Z ]{1,40})(?:\s*\[[^\]]*\])?\s*:\s*"?',
            "",
            line,
        ).strip().rstrip('"')
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


def _legacy_research_and_script(
    topic: str,
    cfg: dict,
    client: anthropic.Anthropic | None,
    repo_root: Path,
    run_id: str = "",
) -> dict:
    if client is None:
        raise ValueError(
            "The legacy script pipeline requires ANTHROPIC_API_KEY. "
            "Use script_quality_pipeline=true for local dialogue_model routing."
        )
    target_words = int(cfg["target_minutes"]) * 130
    episode_type = normalize_episode_type(str(cfg.get("episode_type", "")))
    type_note = episode_type_context(episode_type)
    personal_context, personal_context_path, personal_context_snapshot, personal_context_text = (
        _personal_context_for_topic(repo_root, cfg, topic)
    )

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
                    f"{type_note}\n\n"
                    f"Personal context:\n{personal_context_text}\n\n"
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
                    f"{type_note}\n\n"
                    f"Personal context:\n{personal_context_text}\n\n"
                    f"Research Brief:\n{research_brief}"
                ),
            }
        ],
    )
    raw_script = _extract_text(dialogue_resp.content)

    # Pass 3 — Fact-check
    fiction_mode = episode_type == "complete_fiction"
    logger.info(
        "[3/5] Reviewing fiction continuity..."
        if fiction_mode
        else "[3/5] Fact-checking script..."
    )
    fc_kwargs = {
        "model": _FACT_CHECK_MODEL,
        "max_tokens": 8192,
        "system": _FICTION_CONTINUITY_SYSTEM if fiction_mode else _FACT_CHECK_SYSTEM,
        "messages": [{"role": "user", "content": raw_script}],
    }
    if not fiction_mode:
        fc_kwargs["tools"] = [{"type": "web_search_20250305", "name": "web_search"}]
    fc_resp = client.messages.create(**fc_kwargs)
    checked_script = _extract_text(fc_resp.content)
    final_script = _strip_to_dialogue(checked_script)
    sources = _extract_sources(final_script)
    word_count = len(final_script.split())
    personal_context_update = _record_personal_topic(
        context=personal_context,
        context_path=personal_context_path,
        cfg=cfg,
        topic=topic,
        episode_type=episode_type,
        episode_type_label_text=episode_type_label(episode_type),
        run_id=run_id,
        word_count=word_count,
        source_count=len(sources),
    )

    return {
        "topic":          topic,
        "episode_type":   episode_type,
        "episode_type_label": episode_type_label(episode_type),
        "research_brief": research_brief,
        "script":         final_script,
        "sources":        sources,
        "word_count":     word_count,
        "personal_context_path": str(personal_context_path) if personal_context_path else "",
        "personal_context_snapshot": personal_context_snapshot,
        "personal_context_update": personal_context_update,
        "script_passes":  [
            "personal_context",
            "research",
            "dialogue",
            "fiction_continuity" if fiction_mode else "fact_check",
        ],
    }


def _quality_research_and_script(
    topic: str,
    cfg: dict,
    client: anthropic.Anthropic | None,
    repo_root: Path,
    run_id: str = "",
) -> dict:
    target_words = int(cfg["target_minutes"]) * 130
    episode_type = normalize_episode_type(str(cfg.get("episode_type", "")))
    type_note = episode_type_context(episode_type)
    memory, memory_path = _load_host_memory(repo_root, cfg)
    memory_snapshot = _bounded_host_memory(memory, cfg)
    host_memory_text = _host_memory_prompt(memory, cfg)
    personal_context, personal_context_path, personal_context_snapshot, personal_context_text = (
        _personal_context_for_topic(repo_root, cfg, topic)
    )
    sonic_catalog: dict = {}
    sonic_catalog_path: Path | None = None
    if cfg.get("use_sonic_footnotes", True):
        sonic_catalog, sonic_catalog_path = load_sonic_footnotes_catalog(repo_root, cfg)

    logger.info(f"[1/5] Researching topic package: {topic!r}")
    research_text = _anthropic_text(
        client,
        model=_model_for(cfg, "research_model", _RESEARCH_MODEL),
        max_tokens=8192,
        system=_RESEARCH_SYSTEM,
        content=(
            f"Research this topic thoroughly for an Asynchronous episode: {topic}\n\n"
            f"{type_note}\n\n"
            f"Personal context:\n{personal_context_text}\n\n"
            "Return JSON only with these keys:\n"
            "- topic\n"
            "- readable_brief\n"
            "- source_cards: array of {id,title,author,publication,year,url,why_it_matters}\n"
            "- key_claims: array of {id,claim,confidence,source_ids}\n"
            "- story_hooks\n"
            "- counterintuitive_findings\n"
            "- open_questions\n"
            "- things_to_avoid\n\n"
            "Use live web search. Be specific about dates, people, institutions, "
            "and uncertainty. Do not write a script."
        ),
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        temperature=0.2,
        cfg=cfg,
    )
    research_package = _extract_json_object(research_text) or {
        "topic": topic,
        "readable_brief": research_text,
        "source_cards": [],
        "key_claims": [],
        "story_hooks": [],
        "counterintuitive_findings": [],
        "open_questions": [],
        "things_to_avoid": [],
    }
    research_brief = str(research_package.get("readable_brief") or research_text)
    source_cards = research_package.get("source_cards", [])
    key_claims = research_package.get("key_claims", [])
    if not isinstance(source_cards, list):
        source_cards = []
    if not isinstance(key_claims, list):
        key_claims = []

    logger.info("[2/5] Planning thesis and audience promise...")
    thesis = _anthropic_text(
        client,
        model=_model_for(cfg, "dialogue_model", _DIALOGUE_MODEL),
        max_tokens=2048,
        system=_THESIS_SYSTEM,
        content=(
            f"Topic: {topic}\n\n"
            f"{type_note}\n\n"
            f"Host memory:\n{host_memory_text}\n\n"
            f"Personal context:\n{personal_context_text}\n\n"
            f"Research package:\n{json.dumps(research_package, indent=2)[:24000]}"
        ),
        temperature=0.5,
        cfg=cfg,
    )

    logger.info("[2/5] Deciding whether to book a guest expert...")
    guest_plan = _plan_guest_hosts(
        topic,
        episode_type,
        type_note,
        research_package,
        thesis,
        cfg,
        client,
    )
    guest_hosts = guest_plan.get("guests", []) if guest_plan.get("decision") == "use" else []
    speaker_cfg = {**cfg, "active_guest_hosts": guest_hosts}

    logger.info("[2/5] Building beat sheet and host stance map...")
    beat_sheet = _anthropic_text(
        client,
        model=_model_for(cfg, "dialogue_model", _DIALOGUE_MODEL),
        max_tokens=4096,
        system=_BEAT_SHEET_SYSTEM,
        content=(
            f"Topic: {topic}\n\n"
            f"{type_note}\n\n"
            f"Target words: {target_words}\n\n"
            f"Host memory:\n{host_memory_text}\n\n"
            f"Personal context:\n{personal_context_text}\n\n"
            f"Editorial memo:\n{thesis}\n\n"
            f"Guest plan:\n{json.dumps(guest_plan, indent=2)}\n\n"
            f"Research package:\n{json.dumps(research_package, indent=2)[:26000]}"
        ),
        temperature=0.55,
        cfg=cfg,
    )

    sonic_footnote_plan = {
        "decision": "skip",
        "rationale": "Sonic footnotes are disabled.",
        "cues": [],
    }
    sonic_footnote_credits: list[str] = []
    if cfg.get("use_sonic_footnotes", True):
        logger.info("[2/5] Considering sonic footnote flourishes...")
        sonic_footnote_plan = _plan_sonic_footnotes(
            topic,
            episode_type,
            type_note,
            research_package,
            thesis,
            beat_sheet,
            sonic_catalog,
            cfg,
            client,
        )
        sonic_footnote_credits = sonic_footnote_attributions(
            sonic_footnote_plan.get("cues", []),
            sonic_catalog,
        )

    logger.info("[2/5] Drafting Cedar/Marin dialogue...")
    draft_script = _anthropic_text(
        client,
        model=_model_for(cfg, "dialogue_model", _DIALOGUE_MODEL),
        max_tokens=8192,
        system=_DIALOGUE_DRAFT_SYSTEM.format(target_words=target_words),
        content=(
            f"Topic: {topic}\n\n"
            f"{type_note}\n\n"
            f"Host memory:\n{host_memory_text}\n\n"
            f"Personal context:\n{personal_context_text}\n\n"
            f"Editorial memo:\n{thesis}\n\n"
            f"Guest plan:\n{json.dumps(guest_plan, indent=2)}\n\n"
            f"Beat sheet:\n{beat_sheet}\n\n"
            f"Sonic footnote plan:\n{json.dumps(sonic_footnote_plan, indent=2)}\n\n"
            "If the sonic plan has cues, make room around the relevant beat in the "
            "conversation, but do not write sound-effect labels or stage directions "
            "into the spoken script.\n\n"
            "If the guest plan decision is skip, do not include guest speaker labels. "
            "If it is use, include the guest naturally and only with the listed labels.\n\n"
            f"Research package:\n{json.dumps(research_package, indent=2)[:26000]}"
        ),
        temperature=0.75,
        cfg=cfg,
    )
    draft_script = _strip_to_dialogue(draft_script)

    logger.info("[2/5] Rewriting for naturalness and anti-cliche cleanup...")
    natural_script = _anthropic_text(
        client,
        model=_model_for(cfg, "dialogue_model", _DIALOGUE_MODEL),
        max_tokens=8192,
        system=_ANTI_CLICHE_SYSTEM,
        content=(
            f"Topic: {topic}\n\n"
            f"{type_note}\n\n"
            f"Host memory and phrase blacklist:\n{host_memory_text}\n\n"
            f"Personal context:\n{personal_context_text}\n\n"
            f"Editorial memo:\n{thesis}\n\n"
            f"Guest plan:\n{json.dumps(guest_plan, indent=2)}\n\n"
            f"Beat sheet:\n{beat_sheet}\n\n"
            f"Sonic footnote plan:\n{json.dumps(sonic_footnote_plan, indent=2)}\n\n"
            f"Draft script:\n{draft_script}"
        ),
        temperature=0.65,
        cfg=cfg,
    )
    natural_script = _strip_to_dialogue(natural_script)

    fiction_mode = episode_type == "complete_fiction"
    if fiction_mode:
        logger.info("[3/5] Reviewing fiction continuity...")
        fact_checked_script = _anthropic_text(
            client,
            model=_model_for(cfg, "fact_check_model", _FACT_CHECK_MODEL),
            max_tokens=8192,
            system=_FICTION_CONTINUITY_SYSTEM,
            content=(
                f"Topic or premise: {topic}\n\n"
                f"{type_note}\n\n"
                f"Personal context:\n{personal_context_text}\n\n"
                f"Guest plan:\n{json.dumps(guest_plan, indent=2)}\n\n"
                "Review this as a fictional audio story. Preserve invention, "
                "but make the fictional frame and internal continuity clear.\n\n"
                f"Script:\n{natural_script}"
            ),
            temperature=0.25,
            cfg=cfg,
        )
    else:
        logger.info("[3/5] Fact-checking and calibrating claims...")
        fact_checked_script = _anthropic_text(
            client,
            model=_model_for(cfg, "fact_check_model", _FACT_CHECK_MODEL),
            max_tokens=8192,
            system=_FACT_CHECK_SYSTEM,
            content=(
                f"Topic: {topic}\n\n"
                f"{type_note}\n\n"
                f"Personal context:\n{personal_context_text}\n\n"
                f"Guest plan:\n{json.dumps(guest_plan, indent=2)}\n\n"
                "Use the research package as the first reference, and web search "
                "when anything important needs verification. Correct only claims "
                "that need correcting or softening.\n\n"
                f"Research package:\n{json.dumps(research_package, indent=2)[:26000]}\n\n"
                f"Script:\n{natural_script}"
            ),
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            temperature=0.2,
            cfg=cfg,
        )
    fact_checked_script = _strip_to_dialogue(fact_checked_script)

    logger.info("[3/5] Preparing final performance script...")
    performance_script = _anthropic_text(
        client,
        model=_model_for(cfg, "dialogue_model", _DIALOGUE_MODEL),
        max_tokens=8192,
        system=_PERFORMANCE_SYSTEM,
        content=(
            f"Topic: {topic}\n\n"
            f"{type_note}\n\n"
            f"Guest plan:\n{json.dumps(guest_plan, indent=2)}\n\n"
            f"Sonic footnote plan:\n{json.dumps(sonic_footnote_plan, indent=2)}\n\n"
            f"Host memory:\n{host_memory_text}\n\n"
            f"Personal context:\n{personal_context_text}\n\n"
            f"{'Continuity-reviewed fictional script' if fiction_mode else 'Fact-checked script'}:\n"
            f"{fact_checked_script}"
        ),
        temperature=0.45,
        cfg=cfg,
    )
    final_script = _filter_dialogue_to_known_speakers(
        _strip_to_dialogue(performance_script),
        speaker_cfg,
    )

    memory_update = _update_host_memory(
        topic,
        final_script,
        memory,
        memory_path,
        cfg,
        client,
        run_id=run_id,
    )

    sources = _source_labels_from_cards(source_cards) or _extract_sources(final_script)
    word_count = len(final_script.split())
    personal_context_update = _record_personal_topic(
        context=personal_context,
        context_path=personal_context_path,
        cfg=cfg,
        topic=topic,
        episode_type=episode_type,
        episode_type_label_text=episode_type_label(episode_type),
        run_id=run_id,
        word_count=word_count,
        source_count=len(sources),
    )
    metrics = _script_quality_metrics(final_script, memory, speaker_cfg)

    return {
        "topic": topic,
        "episode_type": episode_type,
        "episode_type_label": episode_type_label(episode_type),
        "research_brief": research_brief,
        "research_package": research_package,
        "source_cards": source_cards,
        "key_claims": key_claims,
        "episode_thesis": thesis,
        "beat_sheet": beat_sheet,
        "guest_plan": guest_plan,
        "guest_hosts": guest_hosts,
        "sonic_footnote_plan": sonic_footnote_plan,
        "sonic_footnote_attributions": sonic_footnote_credits,
        "sonic_footnotes_catalog_path": str(sonic_catalog_path) if sonic_catalog_path else "",
        "draft_script": draft_script,
        "natural_script": natural_script,
        "fact_checked_script": fact_checked_script,
        "script": final_script,
        "sources": sources,
        "word_count": word_count,
        "script_quality_metrics": metrics,
        "script_passes": [
            "personal_context",
            "research_package",
            "episode_thesis",
            "guest_host_decision",
            "beat_sheet",
            "sonic_footnote_decision",
            "dialogue_draft",
            "anti_cliche_rewrite",
            "fiction_continuity" if fiction_mode else "fact_check",
            "performance_script",
            "host_memory_update",
        ],
        "host_memory_path": str(memory_path),
        "host_memory_snapshot": memory_snapshot,
        "host_memory_update": memory_update,
        "personal_context_path": str(personal_context_path) if personal_context_path else "",
        "personal_context_snapshot": personal_context_snapshot,
        "personal_context_update": personal_context_update,
    }


def research_and_script(
    topic: str,
    cfg: dict,
    client: anthropic.Anthropic | None,
    repo_root: Path = Path("."),
    run_id: str = "",
) -> dict:
    if cfg.get("script_quality_pipeline", True):
        return _quality_research_and_script(topic, cfg, client, repo_root, run_id=run_id)
    return _legacy_research_and_script(topic, cfg, client, repo_root, run_id=run_id)


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


def _html_escape(text: str) -> str:
    return _xml_escape(str(text))


# ── Two-voice TTS ──────────────────────────────────────────────────────────────

_TURN_RE = re.compile(r"^([A-Z][A-Z ]*)(?:\s*\[([^\]]*)\])?\s*:\s*(.*)")


def _active_guest_hosts(cfg: dict) -> list[dict]:
    guests = cfg.get("active_guest_hosts") or cfg.get("guest_hosts") or []
    return [guest for guest in guests if isinstance(guest, dict)]


def _guest_for_label(label: str, cfg: dict) -> dict | None:
    normalized = label.strip().upper()
    for guest in _active_guest_hosts(cfg):
        labels = {
            str(guest.get("label") or "").strip().upper(),
            str(guest.get("display_name") or "").strip().upper(),
        }
        if normalized in labels:
            return guest
    return None


def _known_speaker_labels(cfg: dict) -> set[str]:
    host_a = cfg.get("host_a_name", "Cedar").upper()
    host_b = cfg.get("host_b_name", "Marin").upper()
    labels = {host_a, host_b, "CEDAR", "MARIN"}
    for guest in _active_guest_hosts(cfg):
        if guest.get("label"):
            labels.add(str(guest["label"]).upper())
        if guest.get("display_name"):
            labels.add(str(guest["display_name"]).upper())
    return labels


def _speaker_file_stem(label: str) -> str:
    stem = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    return stem or "speaker"


def _parse_dialogue_turns(script: str, cfg: dict) -> list:
    """Return [(speaker_label, emotion_tag, text), ...] triples from a dialogue script.

    Handles both tagged format  CEDAR [warm, curious]: text
    and untagged format         CEDAR: text  (emotion_tag will be empty string).
    """
    known = _known_speaker_labels(cfg)

    turns: list = []
    current_label: str | None = None
    current_tag: str = ""
    current_lines: list = []

    for line in script.splitlines():
        m = _TURN_RE.match(line)
        if m:
            matched_label = m.group(1).strip().upper()
            if matched_label not in known:
                continue
            if current_label and current_lines:
                turns.append((current_label, current_tag, " ".join(current_lines).strip()))
            current_label = matched_label
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


def _format_dialogue_turns(turns: list[tuple[str, str, str]]) -> str:
    lines: list[str] = []
    for label, tag, text in turns:
        if tag:
            lines.append(f"{label} [{tag}]: {text}")
        else:
            lines.append(f"{label}: {text}")
    return "\n".join(lines).strip()


def _filter_dialogue_to_known_speakers(script: str, cfg: dict) -> str:
    turns = _parse_dialogue_turns(script, cfg)
    return _format_dialogue_turns(turns) if turns else script.strip()


def _voice_for_label(label: str, cfg: dict) -> str:
    host_a = cfg.get("host_a_name", "Cedar").upper()
    host_b = cfg.get("host_b_name", "Marin").upper()
    if label in {host_a, "CEDAR"}:
        return cfg.get("host_a_voice", "cedar")
    if label in {host_b, "MARIN"}:
        return cfg.get("host_b_voice", "marin")
    guest = _guest_for_label(label, cfg)
    if guest and guest.get("voice"):
        return str(guest["voice"])
    return cfg.get("host_a_voice", "cedar")


def _speaker_role_for_label(label: str, cfg: dict) -> str:
    normalized = label.strip().upper()
    host_a = cfg.get("host_a_name", "Cedar").upper()
    host_b = cfg.get("host_b_name", "Marin").upper()
    if normalized in {host_a, "CEDAR"}:
        return "CEDAR"
    if normalized in {host_b, "MARIN"}:
        return "MARIN"
    if _guest_for_label(normalized, cfg):
        return "GUEST"
    return normalized


def _clean_tts_route(route: dict | None) -> dict:
    if not isinstance(route, dict):
        return {}
    return {str(key): value for key, value in route.items() if value not in (None, "")}


def _explicit_tts_route_for_label(label: str, cfg: dict) -> dict:
    routes = cfg.get("tts_routes") if isinstance(cfg.get("tts_routes"), dict) else {}
    normalized = label.strip().upper()
    role = _speaker_role_for_label(normalized, cfg)
    route: dict = {}
    for key in ("DEFAULT", role, normalized):
        candidate = routes.get(key) or routes.get(key.lower())
        route.update(_clean_tts_route(candidate))
    return route


def _legacy_tts_route_for_label(label: str, cfg: dict, guest_index: int = 0) -> dict:
    provider = str(cfg.get("tts_provider") or "openai").lower()
    route: dict = {"provider": provider}
    if provider == "openai":
        route.update({"voice": _voice_for_label(label, cfg), "model": cfg.get("tts_model")})
    elif provider == "elevenlabs":
        route.update(
            {
                "voice_id": _elevenlabs_voice_for_label(label, cfg, guest_index),
                "model": cfg.get("elevenlabs_model"),
                "stability": cfg.get("elevenlabs_stability"),
                "similarity_boost": cfg.get("elevenlabs_similarity_boost"),
            }
        )
    elif provider == "command":
        route.update({"voice": _voice_for_label(label, cfg), "command": cfg.get("tts_command")})
    return _clean_tts_route(route)


def _tts_route_for_label(label: str, cfg: dict, guest_index: int = 0) -> dict:
    route = _legacy_tts_route_for_label(label, cfg, guest_index)
    route.update(_clean_tts_route(cfg.get("tts_default_route")))
    route.update(_explicit_tts_route_for_label(label, cfg))
    provider = str(route.get("provider") or cfg.get("tts_provider") or "openai").lower()
    route["provider"] = provider
    if provider not in _VALID_TTS_PROVIDERS:
        raise ValueError(
            f"Unsupported TTS provider {provider!r} for {label}; "
            f"expected one of {sorted(_VALID_TTS_PROVIDERS)}"
        )
    if provider == "openai":
        if route.get("voice_id") and not route.get("voice"):
            route["voice"] = route["voice_id"]
        route.pop("voice_id", None)
        route.setdefault("voice", _voice_for_label(label, cfg))
        route.setdefault("model", cfg.get("tts_model"))
    elif provider == "elevenlabs":
        if route.get("voice") and not route.get("voice_id"):
            route["voice_id"] = route["voice"]
        if route.get("voice_id"):
            route.pop("voice", None)
        route.setdefault("voice_id", _elevenlabs_voice_for_label(label, cfg, guest_index))
        route.setdefault("model", cfg.get("elevenlabs_model"))
        route.setdefault("stability", cfg.get("elevenlabs_stability"))
        route.setdefault("similarity_boost", cfg.get("elevenlabs_similarity_boost"))
    elif provider == "command":
        route.setdefault("voice", _voice_for_label(label, cfg))
        route.setdefault("command", cfg.get("tts_command"))
    return _clean_tts_route(route)


def _public_tts_route(route: dict) -> dict:
    hidden = {"api_key", "headers", "command"}
    public = {
        key: value
        for key, value in route.items()
        if key not in hidden and not key.endswith("_env")
    }
    if "voice_id" in public and public.get("provider") == "elevenlabs":
        voice_id = str(public["voice_id"])
        public["voice_id"] = f"{voice_id[:4]}...{voice_id[-4:]}" if len(voice_id) > 10 else "set"
    return public


def _tts_routes_summary_for_script(script: str, cfg: dict) -> dict:
    turns = _parse_dialogue_turns(script, cfg)
    if not turns:
        route = _tts_route_for_label("CEDAR", cfg)
        return {"CEDAR": _public_tts_route(route)}
    guest_voice_indexes: dict[str, int] = {}
    summary: dict[str, dict] = {}
    for label, _tag, _text in turns:
        if _guest_for_label(label, cfg) and label not in guest_voice_indexes:
            guest_voice_indexes[label] = len(guest_voice_indexes)
        route = _tts_route_for_label(label, cfg, guest_voice_indexes.get(label, 0))
        summary.setdefault(label, _public_tts_route(route))
    return summary


def _elevenlabs_voice_for_label(label: str, cfg: dict, guest_index: int = 0) -> str:
    host_a = cfg.get("host_a_name", "Cedar").upper()
    host_b = cfg.get("host_b_name", "Marin").upper()
    if label in {host_a, "CEDAR"}:
        return str(cfg.get("elevenlabs_voice_id_a", ""))
    if label in {host_b, "MARIN"}:
        return str(cfg.get("elevenlabs_voice_id_b", ""))
    guest = _guest_for_label(label, cfg)
    if guest and guest.get("elevenlabs_voice_id"):
        return str(guest["elevenlabs_voice_id"])
    guest_voice_ids = _csv_list(cfg.get("elevenlabs_guest_voice_ids"))
    if guest_voice_ids:
        return guest_voice_ids[guest_index % len(guest_voice_ids)]
    return str(cfg.get("elevenlabs_voice_id_b") or cfg.get("elevenlabs_voice_id_a") or "")


def _emotion_default_for_label(label: str, cfg: dict) -> str:
    host_a = cfg.get("host_a_name", "Cedar").upper()
    if label in {host_a, "CEDAR"}:
        return "warm, curious"
    guest = _guest_for_label(label, cfg)
    if guest and guest.get("delivery_baseline"):
        return str(guest["delivery_baseline"])
    return "measured, thoughtful"


def _build_tts_instructions(emotion_tag: str, label: str, cfg: dict) -> str:
    tag = emotion_tag if emotion_tag else _emotion_default_for_label(label, cfg)
    guest = _guest_for_label(label, cfg)
    if guest:
        return (
            f"You are voicing {guest.get('display_name', label)}, a synthetic guest "
            f"expert in {guest.get('field', 'the topic')}. "
            f"Personality: {guest.get('personality', 'specific, conversational, careful')}. "
            f"Deliver this line with: {tag}. Speak naturally in the interview, "
            "with authority but without sounding like a lecture."
        )
    return (
        f"Deliver this line with: {tag}. "
        "Speak naturally, as if in genuine conversation."
    )


def _ffmpeg_concat(
    parts: list,
    output: Path,
    *,
    bitrate: str = "192k",
    sample_rate: int = 44100,
    channels: int = 2,
) -> None:
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
            "-ar", str(sample_rate), "-ac", str(channels),
            "-c:a", "libmp3lame", "-b:a", bitrate,
            str(output),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg concat failed: {result.stderr[:500]}")
    finally:
        list_path.unlink(missing_ok=True)


def _make_silence(path: Path, duration_ms: int, cfg: dict) -> Path:
    """Create a tiny MP3 silence segment for natural turn spacing."""
    duration = max(0.001, float(duration_ms) / 1000.0)
    sample_rate = int(cfg.get("audio_sample_rate", 44100))
    channels = int(cfg.get("audio_channels", 2))
    channel_layout = "mono" if channels == 1 else "stereo"
    path = path.with_suffix(".mp3")
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=r={sample_rate}:cl={channel_layout}",
        "-t",
        f"{duration:.3f}",
        "-ar",
        str(sample_rate),
        "-ac",
        str(channels),
        "-c:a",
        "libmp3lame",
        "-b:a",
        _audio_bitrate_value(cfg),
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg silence generation failed: {result.stderr[:500]}")
    return path


def _interleave_silence(parts: list[Path], silence_path: Path | None) -> list[Path]:
    if not silence_path or not silence_path.exists() or len(parts) <= 1:
        return list(parts)
    interleaved: list[Path] = []
    for idx, part in enumerate(parts):
        if idx:
            interleaved.append(silence_path)
        interleaved.append(part)
    return interleaved


def _ffmpeg_concat_configured(parts: list, output: Path, cfg: dict) -> None:
    _ffmpeg_concat(
        parts,
        output,
        bitrate=_audio_bitrate_value(cfg),
        sample_rate=int(cfg.get("audio_sample_rate", 44100)),
        channels=int(cfg.get("audio_channels", 2)),
    )


def _master_audio(input_path: Path, output_path: Path, cfg: dict, work_dir: Path) -> dict:
    """Apply final podcast mastering and encode the publishable MP3."""
    if not cfg.get("use_audio_mastering", True):
        if input_path.resolve() != output_path.resolve():
            shutil.copy2(input_path, output_path)
        return {"enabled": False}

    if not input_path.exists():
        raise FileNotFoundError(f"Audio file not found for mastering: {input_path}")

    highpass = int(cfg.get("audio_highpass_hz", 60))
    lowpass = int(cfg.get("audio_lowpass_hz", 18000))
    filters: list[str] = []
    if highpass > 0:
        filters.append(f"highpass=f={highpass}")
    if lowpass > 0:
        filters.append(f"lowpass=f={lowpass}")
    filters.append(
        "loudnorm="
        f"I={float(cfg.get('audio_loudness_i', -16.0))}:"
        f"TP={float(cfg.get('audio_true_peak', -1.5))}:"
        f"LRA={float(cfg.get('audio_lra', 11.0))}:"
        "print_format=summary"
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    master_path = output_path
    if input_path.resolve() == output_path.resolve():
        master_path = work_dir / f"{output_path.stem}_mastered{output_path.suffix}"

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-vn",
        "-af",
        ",".join(filters),
        "-ar",
        str(int(cfg.get("audio_sample_rate", 44100))),
        "-ac",
        str(int(cfg.get("audio_channels", 2))),
        "-c:a",
        "libmp3lame",
        "-b:a",
        _audio_bitrate_value(cfg),
        str(master_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg audio mastering failed: {result.stderr[:800]}")
    if master_path != output_path:
        master_path.replace(output_path)

    return {
        "enabled": True,
        "filters": filters,
        "bitrate": _audio_bitrate_value(cfg),
        "sample_rate": int(cfg.get("audio_sample_rate", 44100)),
        "channels": int(cfg.get("audio_channels", 2)),
        "loudness_i": float(cfg.get("audio_loudness_i", -16.0)),
        "true_peak": float(cfg.get("audio_true_peak", -1.5)),
        "lra": float(cfg.get("audio_lra", 11.0)),
    }


def _probe_audio_duration(path: Path) -> float | None:
    """Return audio duration in seconds using ffprobe when available."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def _format_itunes_duration(seconds: float | int | None, fallback_minutes: int) -> str:
    if seconds is None:
        return f"{fallback_minutes}:00"
    total = max(0, int(round(float(seconds))))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _format_timestamp(seconds: float | int) -> str:
    total = max(0, int(round(float(seconds))))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _clean_markdown_inline(text: str) -> str:
    text = re.sub(r"`([^`]+)`", r"\1", str(text))
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -:\t")


def _chapter_titles_from_beat_sheet(beat_sheet: str) -> list[str]:
    titles: list[str] = []
    for line in str(beat_sheet or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = re.match(
            r"^(?:#{1,4}\s*)?(?:[-*]\s*)?(?:\*\*)?(?:beat\s*)?([Bb]?\d{1,2})"
            r"(?:\*\*)?[\).:\-\s]+(.+)$",
            stripped,
            flags=re.I,
        )
        if not match:
            continue
        title = _clean_markdown_inline(match.group(2))
        title = re.sub(
            r"\b(purpose|rough length|length|key claims?|sources?)\b.*$",
            "",
            title,
            flags=re.I,
        ).strip(" -:")
        if title and len(title) <= 90:
            titles.append(title)
        if len(titles) >= 10:
            break

    if not titles:
        titles = [
            "Opening question",
            "The setup",
            "The first turn",
            "Evidence and complications",
            "What changes",
            "Where to go next",
        ]
    return titles


def _build_chapters(episode: dict, duration_sec: float | None, cfg: dict) -> list[dict]:
    titles = _chapter_titles_from_beat_sheet(str(episode.get("beat_sheet") or ""))
    duration = float(duration_sec) if duration_sec is not None else float(
        int(cfg.get("target_minutes", 15)) * 60
    )
    duration = max(duration, 60.0)
    count = max(1, len(titles))
    end_cap = max(0.0, duration - 45.0)
    spacing = end_cap / count if count else end_cap
    chapters: list[dict] = []
    for idx, title in enumerate(titles):
        start_sec = 0.0 if idx == 0 else min(end_cap, spacing * idx)
        chapters.append(
            {
                "start_sec": round(start_sec, 2),
                "start_time": _format_timestamp(start_sec),
                "title": title,
            }
        )
    return chapters


def _follow_up_links_from_episode(episode: dict, limit: int = 8) -> list[dict]:
    links: list[dict] = []
    seen: set[str] = set()
    for card in episode.get("source_cards") or []:
        if not isinstance(card, dict):
            continue
        url = str(card.get("url") or "").strip()
        if not url or url in seen:
            continue
        title = str(card.get("title") or card.get("publication") or url).strip()
        publisher = str(card.get("publication") or card.get("publisher") or "").strip()
        reason = str(card.get("why_it_matters") or "").strip()
        links.append(
            {
                "title": title,
                "url": url,
                "source": publisher,
                "reason": reason,
            }
        )
        seen.add(url)
        if len(links) >= limit:
            return links

    for source in episode.get("sources") or []:
        text = str(source)
        url_match = re.search(r"https?://[^\s)]+", text)
        if not url_match:
            continue
        url = url_match.group(0).rstrip(".,")
        if url in seen:
            continue
        title = _clean_markdown_inline(text.replace(url, "")).strip(" ()-") or url
        links.append({"title": title, "url": url, "source": "", "reason": ""})
        seen.add(url)
        if len(links) >= limit:
            break
    return links


def _chapters_json_payload(chapters: list[dict]) -> dict:
    return {
        "version": "1.2.0",
        "chapters": [
            {
                "startTime": float(chapter.get("start_sec", 0)),
                "title": str(chapter.get("title") or "Chapter"),
            }
            for chapter in chapters
        ],
    }


def _write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_companion_artifacts(
    episode: dict,
    audio_path: Path,
    cfg: dict,
    repo_root: Path,
) -> list[Path]:
    base_url = f"https://{cfg['github_user']}.github.io/{cfg['github_repo']}"
    audio_url = f"{base_url}/{cfg['output_dir']}/{audio_path.name}"
    chapters = _build_chapters(episode, episode.get("duration_sec"), cfg)
    follow_up_links = _follow_up_links_from_episode(episode)

    chapters_path = audio_path.with_suffix(".chapters.json")
    companion_path = audio_path.with_suffix(".companion.json")
    chapters_url = f"{base_url}/{cfg['output_dir']}/{chapters_path.name}"
    companion_url = f"{base_url}/{cfg['output_dir']}/{companion_path.name}"

    _write_json(chapters_path, _chapters_json_payload(chapters))
    companion = {
        "schema_version": 1,
        "topic": episode.get("topic"),
        "episode_type": episode.get("episode_type"),
        "episode_type_label": episode.get("episode_type_label"),
        "audio_url": audio_url,
        "chapters_url": chapters_url,
        "companion_url": companion_url,
        "duration_sec": episode.get("duration_sec"),
        "word_count": episode.get("word_count"),
        "guest_hosts": episode.get("guest_hosts", []),
        "tts_routes": episode.get("tts_routes", {}),
        "chapters": chapters,
        "follow_up_links": follow_up_links,
        "sources": episode.get("sources", []),
        "source_cards": episode.get("source_cards", []),
        "key_claims": episode.get("key_claims", []),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(companion_path, companion)

    episode["audio_url"] = audio_url
    episode["chapters"] = chapters
    episode["chapters_url"] = chapters_url
    episode["chapters_path"] = str(chapters_path)
    episode["companion_url"] = companion_url
    episode["companion_path"] = str(companion_path)
    episode["follow_up_links"] = follow_up_links
    return [chapters_path, companion_path]


def _tts_openai_voice(
    text: str,
    voice: str,
    output_path: Path,
    cfg: dict,
    instructions: str = "",
) -> Path:
    """Backward-compatible OpenAI route wrapper."""
    return tts_engines.synthesize_tts(
        text=text,
        output_path=output_path,
        route={"provider": "openai", "voice": voice, "model": cfg.get("tts_model")},
        cfg=cfg,
        instructions=instructions,
    )


def _tts_two_host(
    script: str,
    output_path: Path,
    cfg: dict,
    work_dir: Path,
) -> Path:
    """Generate routed TTS from a speaker-labelled dialogue script."""
    turns = _parse_dialogue_turns(script, cfg)
    if not turns:
        logger.warning("No dialogue turns found - falling back to default TTS route")
        route = _tts_route_for_label("CEDAR", cfg)
        return tts_engines.synthesize_tts(
            text=script,
            output_path=output_path,
            route=route,
            cfg=cfg,
            instructions=_build_tts_instructions("", "CEDAR", cfg),
        )

    work_dir.mkdir(parents=True, exist_ok=True)
    turn_files: list = []
    guest_voice_indexes: dict[str, int] = {}

    for i, (label, emotion_tag, text) in enumerate(turns):
        if not text.strip():
            continue
        if _guest_for_label(label, cfg) and label not in guest_voice_indexes:
            guest_voice_indexes[label] = len(guest_voice_indexes)
        route = _tts_route_for_label(label, cfg, guest_voice_indexes.get(label, 0))
        instructions = _build_tts_instructions(emotion_tag, label, cfg)
        turn_path = work_dir / f"turn_{i:04d}_{_speaker_file_stem(label)}.mp3"
        generated_path = tts_engines.synthesize_tts(
            text=text,
            output_path=turn_path,
            route=route,
            cfg=cfg,
            instructions=instructions,
        )
        if generated_path.exists():
            turn_files.append(generated_path)

    if not turn_files:
        raise RuntimeError("No turn audio files were generated")

    output_path = output_path.with_suffix(".mp3")
    silence_path: Path | None = None
    silence_ms = int(cfg.get("turn_silence_ms", 180))
    if silence_ms > 0 and len(turn_files) > 1:
        silence_path = _make_silence(work_dir / "_turn_silence", silence_ms, cfg)
    _ffmpeg_concat_configured(
        _interleave_silence(turn_files, silence_path),
        output_path,
        cfg,
    )

    for p in turn_files:
        p.unlink(missing_ok=True)
    if silence_path:
        silence_path.unlink(missing_ok=True)

    return output_path


def _tts_elevenlabs_chunked(
    text: str,
    voice_id: str,
    output_path: Path,
    cfg: dict | None = None,
) -> Path:
    """Backward-compatible ElevenLabs route wrapper."""
    route_cfg = cfg or DEFAULTS
    return tts_engines.synthesize_tts(
        text=text,
        output_path=output_path,
        route={
            "provider": "elevenlabs",
            "voice_id": voice_id,
            "model": route_cfg.get("elevenlabs_model"),
        },
        cfg=route_cfg,
    )


def generate_audio(
    script: str,
    output_path: Path,
    cfg: dict,
    work_dir: Path,
) -> Path:
    """Generate episode audio from a dialogue script."""
    route_summary = _tts_routes_summary_for_script(script, cfg)
    providers = sorted(
        {
            str(route.get("provider", cfg.get("tts_provider", "openai")))
            for route in route_summary.values()
        }
    )
    logger.info(f"[4/5] Generating audio via routed TTS providers: {providers}")
    return _tts_two_host(script, output_path, cfg, work_dir / "turns")


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
     xmlns:podcast="https://podcastindex.org/namespace/1.0"
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
      <content:encoded><![CDATA[{content_encoded}]]></content:encoded>
      <pubDate>{pub_date}</pubDate>
      <guid isPermaLink="false">{guid}</guid>
      <enclosure url="{audio_url}" length="{file_size}" type="audio/mpeg"/>
      <itunes:duration>{duration}</itunes:duration>
      <itunes:explicit>false</itunes:explicit>
      {chapters_tag}
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
    duration = _format_itunes_duration(
        episode.get("duration_sec"), int(cfg["target_minutes"])
    )

    sources_html = ""
    if episode.get("sources"):
        items_html = "".join(
            f"<li>{_xml_escape(s)}</li>" for s in episode["sources"]
        )
        sources_html = f"<br><br><strong>Sources:</strong><ul>{items_html}</ul>"

    music_html = ""
    if episode.get("music_credit"):
        music_html = f"<br><em>{_xml_escape(episode['music_credit'])}</em>"

    clips_html = ""
    if episode.get("clip_attributions"):
        clip_items = "".join(
            f"<li>{_xml_escape(s)}</li>" for s in episode["clip_attributions"]
        )
        clips_html = f"<br><br><strong>Clip credits:</strong><ul>{clip_items}</ul>"

    guest_html = ""
    if episode.get("guest_hosts"):
        guest_items = "".join(
            "<li>"
            f"{_html_escape(guest.get('display_name') or guest.get('label') or 'Guest')} "
            f"- {_html_escape(guest.get('field') or guest.get('expertise') or 'guest expert')}"
            "</li>"
            for guest in episode["guest_hosts"]
            if isinstance(guest, dict)
        )
        if guest_items:
            guest_html = (
                "<br><br><strong>Guest voices:</strong><ul>"
                f"{guest_items}</ul>"
                "<em>Guest experts are synthetic composite personas, not real people "
                "or voice impersonations.</em>"
            )

    chapters_html = ""
    if episode.get("chapters"):
        chapter_items = "".join(
            "<li>"
            f"<a href=\"{_html_escape(audio_url)}#t={int(float(ch.get('start_sec', 0)))}\">"
            f"{_html_escape(ch.get('start_time', '0:00'))}</a> "
            f"{_html_escape(ch.get('title', 'Chapter'))}"
            "</li>"
            for ch in episode["chapters"]
        )
        chapters_html = f"<br><br><strong>Chapters:</strong><ol>{chapter_items}</ol>"

    follow_up_html = ""
    if episode.get("follow_up_links"):
        link_items = "".join(
            "<li>"
            f"<a href=\"{_html_escape(link.get('url', ''))}\">"
            f"{_html_escape(link.get('title') or link.get('url') or 'Link')}</a>"
            + (
                f" - {_html_escape(link.get('reason'))}"
                if link.get("reason")
                else ""
            )
            + "</li>"
            for link in episode["follow_up_links"]
            if link.get("url")
        )
        if link_items:
            follow_up_html = f"<br><br><strong>Follow-up links:</strong><ul>{link_items}</ul>"

    disclosure_html = (
        "<br><br><em>Cedar, Marin, and any guest voices are AI-generated. "
        "Episode text and audio are generated with human-directed software.</em>"
    )

    # Script preview — escape any XML-sensitive chars outside CDATA wrap
    preview = _xml_escape(
        re.sub(
            r"^([A-Z][A-Z ]{1,40})(?:\s*\[[^\]]*\])?\s*:\s*",
            "",
            episode["script"][:500],
            flags=re.MULTILINE,
        )
    )
    companion_data_html = ""
    if episode.get("companion_url"):
        companion_data_html = (
            f"<br><br><a href=\"{_html_escape(episode['companion_url'])}\">"
            "Episode companion data</a>"
        )
    companion_html = guest_html + chapters_html + follow_up_html + companion_data_html
    description = _cdata_safe(preview + "..." + disclosure_html + companion_html)
    content_encoded = _cdata_safe(
        preview
        + "..."
        + disclosure_html
        + guest_html
        + chapters_html
        + follow_up_html
        + sources_html
        + clips_html
        + music_html
        + companion_data_html
    )

    chapters_tag = ""
    if episode.get("chapters_url"):
        chapters_tag = (
            f'<podcast:chapters url="{_xml_escape(episode["chapters_url"])}" '
            'type="application/json+chapters"/>'
        )

    new_item = _ITEM_TEMPLATE.format(
        title       = _xml_escape(episode.get("title") or episode["topic"]),
        description = description,
        content_encoded = content_encoded,
        pub_date    = pub_date,
        guid        = guid,
        audio_url   = audio_url,
        file_size   = file_size,
        duration    = duration,
        chapters_tag = chapters_tag,
    )

    feed_path = repo_root / "feed.xml"
    if feed_path.exists():
        content = feed_path.read_text(encoding="utf-8")
        if "xmlns:podcast=" not in content:
            content = content.replace(
                '<rss version="2.0"',
                '<rss version="2.0"\n     xmlns:podcast="https://podcastindex.org/namespace/1.0"',
                1,
            )
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


def git_publish(
    audio_path: Path,
    repo_root: Path,
    topic: str,
    extra_paths: list[Path] | None = None,
    title: str | None = None,
) -> None:
    headline = (title or topic or "").strip()
    safe_topic = re.sub(r"[\r\n]+", " ", headline).strip()[:120] or "(untitled)"
    add_paths = [str(audio_path), "feed.xml"] + [
        str(path) for path in (extra_paths or []) if Path(path).exists()
    ]
    for cmd in [
        ["git", "add", "-f", *add_paths],
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
    def tts_fn(text: str, output: Path) -> Path:
        if _parse_dialogue_turns(text, cfg):
            return _tts_two_host(text, output, cfg, work_dir / "tts_turns")
        route = _tts_route_for_label("CEDAR", cfg)
        return tts_engines.synthesize_tts(
            text=text,
            output_path=output,
            route=route,
            cfg=cfg,
            instructions=_build_tts_instructions("", "CEDAR", cfg),
        )

    return tts_fn


# ── Intro ident ───────────────────────────────────────────────────────────────

_INTRO_IDENT_TEXT = "Asynchronous. A podcast about ideas. With Cedar and Marin."


def _ensure_intro_ident(cfg: dict, repo_root: Path) -> "Path | None":
    """Generate and cache the show intro ident at assets/intro_ident.mp3.

    Uses Cedar's configured TTS route.
    Only synthesised once; subsequent calls return the cached file immediately.
    """
    ident_path = repo_root / "assets" / "intro_ident.mp3"
    if ident_path.exists():
        return ident_path

    try:
        ident_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Generating show intro ident (first run only)…")
        route = _tts_route_for_label("CEDAR", cfg)
        tts_engines.synthesize_tts(
            text=_INTRO_IDENT_TEXT,
            output_path=ident_path,
            route=route,
            cfg=cfg,
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

def run(
    topic: str,
    repo_root: Path = Path("."),
    episode_type: str | None = None,
    guest_host_mode: str | None = None,
) -> dict:
    repo_root = repo_root.resolve()
    cfg = load_config(repo_root)
    if episode_type:
        cfg["episode_type"] = normalize_episode_type(episode_type)
    if guest_host_mode:
        mode = guest_host_mode.lower().strip()
        if mode not in _VALID_GUEST_HOST_MODES:
            raise ValueError(
                f"Unsupported guest_host_mode {guest_host_mode!r}; "
                f"expected one of {sorted(_VALID_GUEST_HOST_MODES)}"
            )
        cfg["guest_host_mode"] = mode
        cfg["use_guest_hosts"] = mode != "off"
    skip_git = _should_skip_git()

    slug = slugify_topic(topic)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ep_filename = f"{timestamp}_{slug}"
    run_id = ep_filename
    ep_dir = repo_root / cfg["output_dir"]
    final_mp3 = ep_dir / f"{ep_filename}.mp3"
    work_dir = ep_dir / f"{ep_filename}_work"

    manifest: EpisodeManifest | None = None
    episode: dict | None = None
    current_stage = "initializing"

    try:
        with acquire_generation_lock(repo_root, run_id=run_id, topic=topic):
            ep_dir.mkdir(parents=True, exist_ok=True)
            work_dir.mkdir(parents=True, exist_ok=True)

            manifest = EpisodeManifest.create(
                work_dir / "episode_manifest.json",
                run_id=run_id,
                topic=topic,
                slug=slug,
                options={
                    "target_minutes": cfg["target_minutes"],
                    "episode_type": cfg["episode_type"],
                    "episode_type_label": episode_type_label(cfg["episode_type"]),
                    "use_sonic_footnotes": cfg.get("use_sonic_footnotes", True),
                    "sonic_footnotes_catalog": cfg.get("sonic_footnotes_catalog"),
                    "use_guest_hosts": cfg.get("use_guest_hosts", True),
                    "guest_host_mode": cfg.get("guest_host_mode"),
                    "guest_host_max": cfg.get("guest_host_max"),
                    "guest_host_voice_pool": cfg.get("guest_host_voice_pool"),
                    "use_personal_context": cfg.get("use_personal_context", True),
                    "personal_context_path": cfg.get("personal_context_path"),
                    "personal_context_max_topics": cfg.get("personal_context_max_topics"),
                    "personal_context_sync_manifests": cfg.get("personal_context_sync_manifests"),
                    "tts_provider": cfg["tts_provider"],
                    "use_clips": cfg.get("use_clips", False),
                    "use_music": cfg.get("use_music", False),
                    "use_emotive_tts": cfg.get("use_emotive_tts", False),
                    "turn_silence_ms": cfg.get("turn_silence_ms"),
                    "use_audio_mastering": cfg.get("use_audio_mastering", True),
                    "audio_bitrate": cfg.get("audio_bitrate"),
                    "audio_sample_rate": cfg.get("audio_sample_rate"),
                    "audio_channels": cfg.get("audio_channels"),
                    "audio_loudness_i": cfg.get("audio_loudness_i"),
                    "audio_true_peak": cfg.get("audio_true_peak"),
                    "audio_lra": cfg.get("audio_lra"),
                    "output_dir": cfg["output_dir"],
                    "skip_git": skip_git,
                },
                models={
                    "research": cfg.get("research_model"),
                    "dialogue": cfg.get("dialogue_model"),
                    "fact_check": cfg.get("fact_check_model"),
                    "tts": cfg.get("tts_model"),
                    "music": cfg.get("music_model"),
                },
            )
            manifest.data.setdefault("paths", {}).update(
                {
                    "repo_root": str(repo_root),
                    "work_dir": str(work_dir),
                    "final_audio": str(final_mp3),
                    "rss": str(repo_root / "feed.xml"),
                }
            )
            manifest.save()

            current_stage = "research_script"
            manifest.set_stage(current_stage)
            anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
            client = (
                anthropic.Anthropic(api_key=anthropic_key)
                if anthropic_key
                else None
            )
            episode = research_and_script(
                topic,
                cfg,
                client,
                repo_root=repo_root,
                run_id=run_id,
            )
            episode["run_id"] = run_id
            episode["manifest_path"] = str(manifest.path)
            episode.setdefault("episode_type", cfg["episode_type"])
            episode.setdefault("episode_type_label", episode_type_label(cfg["episode_type"]))

            # Generate a short, evocative episode title (RSS / website / manifest).
            # Topic remains the raw user prompt; title is the published headline.
            episode["title"] = _generate_episode_title(
                topic,
                episode.get("episode_thesis"),
                cfg,
                client,
            )
            manifest.data["title"] = episode["title"]
            logger.info(f"Episode title: {episode['title']!r}")

            research_path = work_dir / "research_brief.md"
            script_path = work_dir / "script.txt"
            research_path.write_text(episode.get("research_brief", ""), encoding="utf-8")
            script_path.write_text(episode["script"], encoding="utf-8")
            script_artifacts: dict = {}
            artifact_specs = {
                "research_package": ("research_package.json", episode.get("research_package")),
                "source_cards": ("source_cards.json", episode.get("source_cards")),
                "key_claims": ("key_claims.json", episode.get("key_claims")),
                "episode_thesis": ("episode_thesis.md", episode.get("episode_thesis")),
                "beat_sheet": ("beat_sheet.md", episode.get("beat_sheet")),
                "sonic_footnote_plan": (
                    "sonic_footnote_plan.json",
                    episode.get("sonic_footnote_plan"),
                ),
                "guest_plan": ("guest_plan.json", episode.get("guest_plan")),
                "draft_script": ("draft_script.txt", episode.get("draft_script")),
                "natural_script": ("natural_script.txt", episode.get("natural_script")),
                "fact_checked_script": (
                    "fact_checked_script.txt",
                    episode.get("fact_checked_script"),
                ),
                "host_memory_snapshot": (
                    "host_memory_snapshot.json",
                    episode.get("host_memory_snapshot"),
                ),
                "host_memory_update": (
                    "host_memory_update.json",
                    episode.get("host_memory_update"),
                ),
                "personal_context_snapshot": (
                    "personal_context_snapshot.json",
                    episode.get("personal_context_snapshot"),
                ),
                "personal_context_update": (
                    "personal_context_update.json",
                    episode.get("personal_context_update"),
                ),
            }
            for key, (filename, value) in artifact_specs.items():
                if value in (None, "", [], {}):
                    continue
                artifact_path = work_dir / filename
                if isinstance(value, (dict, list)):
                    artifact_path.write_text(
                        json.dumps(value, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                else:
                    artifact_path.write_text(str(value), encoding="utf-8")
                script_artifacts[key] = str(artifact_path)
            manifest.data.setdefault("paths", {}).update(
                {
                    "research_brief": str(research_path),
                    "script": str(script_path),
                    **script_artifacts,
                }
            )
            manifest.data.setdefault("metrics", {}).update(
                {
                    "episode_type": episode.get("episode_type"),
                    "episode_type_label": episode.get("episode_type_label"),
                    "word_count": episode["word_count"],
                    "line_count": len(episode["script"].splitlines()),
                    "guest_count": len(episode.get("guest_hosts", [])),
                    "script_passes": episode.get("script_passes", []),
                    **episode.get("script_quality_metrics", {}),
                }
            )
            if episode.get("host_memory_path"):
                manifest.data["host_memory_path"] = episode["host_memory_path"]
            if episode.get("personal_context_path"):
                manifest.data["personal_context_path"] = episode["personal_context_path"]
            if episode.get("personal_context_update"):
                manifest.data["personal_context_update"] = episode["personal_context_update"]
            if episode.get("sonic_footnotes_catalog_path"):
                manifest.data["sonic_footnotes_catalog_path"] = episode[
                    "sonic_footnotes_catalog_path"
                ]
            if episode.get("sonic_footnote_plan"):
                manifest.data["sonic_footnote_plan"] = episode["sonic_footnote_plan"]
            if episode.get("sonic_footnote_attributions"):
                manifest.data["sonic_footnote_attributions"] = episode[
                    "sonic_footnote_attributions"
                ]
            if episode.get("guest_plan"):
                manifest.data["guest_plan"] = episode["guest_plan"]
            if episode.get("guest_hosts"):
                manifest.data["guest_hosts"] = episode["guest_hosts"]
            if episode.get("source_cards"):
                manifest.data["source_cards"] = episode["source_cards"]
            if episode.get("key_claims"):
                manifest.data["claims"] = episode["key_claims"]
            manifest.set_sources(episode.get("sources", []))
            cfg["active_guest_hosts"] = episode.get("guest_hosts", [])
            episode["tts_routes"] = _tts_routes_summary_for_script(episode["script"], cfg)
            manifest.data["tts_routes"] = episode["tts_routes"]
            manifest.data.setdefault("metrics", {})["tts_providers"] = sorted(
                {
                    str(route.get("provider"))
                    for route in episode["tts_routes"].values()
                    if route.get("provider")
                }
            )
            manifest.save()

            current_stage = "audio"
            manifest.set_stage(current_stage)
            logger.info("[4/5] Generating episode audio...")
            raw_audio = work_dir / f"{ep_filename}_raw.mp3"

            requested_clips = bool(cfg.get("use_clips", False))
            use_clips = requested_clips and HAS_CLIP_MIXER
            attributions: list = []
            if requested_clips and not HAS_CLIP_MIXER:
                manifest.add_warning(
                    "Clips were requested but clip_mixer could not be imported.",
                    stage=current_stage,
                )

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
                    logger.warning(
                        f"Clip pipeline error ({exc}) - falling back to dialogue-only"
                    )
                    manifest.add_warning(
                        f"Clip pipeline failed; generated dialogue-only audio: {exc}",
                        stage=current_stage,
                    )
                    audio_path = generate_audio(episode["script"], raw_audio, cfg, work_dir)
                    attributions = []
            else:
                audio_path = generate_audio(episode["script"], raw_audio, cfg, work_dir)

            if attributions:
                episode["clip_attributions"] = attributions
                manifest.set_clips(attributions)

            ident_path = _ensure_intro_ident(cfg, repo_root)
            if ident_path:
                manifest.set_path("intro_ident", ident_path)

            if cfg.get("use_music") and HAS_MUSIC_GEN and generate_intro_outro is not None:
                music_dir = work_dir / "music"
                intro_path, outro_path = generate_intro_outro(
                    cfg, topic, music_dir, client
                )
                if intro_path and outro_path:
                    logger.info("Wrapping episode with ident + intro/outro music...")
                    segments = []
                    if ident_path and ident_path.exists():
                        segments.append(ident_path)
                    segments += [intro_path, audio_path, outro_path]
                    _ffmpeg_concat_configured(segments, final_mp3, cfg)
                    manifest.data.setdefault("paths", {}).update(
                        {
                            "music_intro": str(intro_path),
                            "music_outro": str(outro_path),
                        }
                    )
                    manifest.save()
                    episode["music_credit"] = (
                        "Original synthetic theme music generated locally for this episode."
                    )
                else:
                    manifest.add_warning(
                        "Music generation returned incomplete intro/outro files.",
                        stage=current_stage,
                    )
                    if ident_path and ident_path.exists():
                        _ffmpeg_concat_configured([ident_path, audio_path], final_mp3, cfg)
                    else:
                        shutil.copy2(audio_path, final_mp3)
            else:
                if cfg.get("use_music") and not HAS_MUSIC_GEN:
                    manifest.add_warning(
                        "Music was requested but music generation dependencies are unavailable.",
                        stage=current_stage,
                    )
                if ident_path and ident_path.exists():
                    _ffmpeg_concat_configured([ident_path, audio_path], final_mp3, cfg)
                else:
                    shutil.copy2(audio_path, final_mp3)

            try:
                mastering_report = _master_audio(final_mp3, final_mp3, cfg, work_dir)
                episode["audio_mastering"] = mastering_report
                manifest.data["audio_mastering"] = mastering_report
                manifest.save()
            except Exception as exc:
                logger.warning(f"Audio mastering failed; leaving premaster audio: {exc}")
                manifest.add_warning(
                    f"Audio mastering failed; leaving premaster audio: {exc}",
                    stage=current_stage,
                )

            duration_sec = _probe_audio_duration(final_mp3)
            if duration_sec is None:
                manifest.add_warning(
                    "Could not probe final audio duration with ffprobe.",
                    stage=current_stage,
                )
            episode["duration_sec"] = duration_sec
            file_size = final_mp3.stat().st_size if final_mp3.exists() else 0
            manifest.set_audio(final_mp3, duration_sec=duration_sec, file_size=file_size)

            companion_paths = _write_companion_artifacts(
                episode,
                final_mp3,
                cfg,
                repo_root,
            )
            manifest.data.setdefault("paths", {}).update(
                {
                    "chapters": episode.get("chapters_path"),
                    "companion": episode.get("companion_path"),
                }
            )
            manifest.data["chapters"] = episode.get("chapters", [])
            manifest.data["follow_up_links"] = episode.get("follow_up_links", [])
            manifest.save()

            current_stage = "rss"
            manifest.set_stage(current_stage)
            logger.info("[5/5] Updating RSS feed...")
            update_rss(episode, final_mp3, cfg, repo_root)
            base_url = f"https://{cfg['github_user']}.github.io/{cfg['github_repo']}"
            manifest.set_publish(
                rss_updated=True,
                rss_path=str(repo_root / "feed.xml"),
                feed_url=f"{base_url}/feed.xml",
                audio_url=f"{base_url}/{cfg['output_dir']}/{final_mp3.name}",
                chapters_url=episode.get("chapters_url"),
                companion_url=episode.get("companion_url"),
            )

            if not skip_git:
                current_stage = "git"
                manifest.set_stage(current_stage)
                git_publish(
                    final_mp3,
                    repo_root,
                    topic,
                    extra_paths=companion_paths,
                    title=episode.get("title"),
                )
                manifest.set_publish(git_pushed=True)
            else:
                manifest.set_publish(git_pushed=False, git_skipped=True)

            manifest.complete()

    except Exception as exc:
        if manifest is not None:
            manifest.fail(current_stage, exc)
        raise
    finally:
        # TODO 2026-06-06: re-enable to stop bloating disk; kept off for first-month debug window.
        # if work_dir.exists():
        #     shutil.rmtree(work_dir, ignore_errors=True)
        pass

    if episode is None:
        raise RuntimeError("Episode generation ended before an episode was produced")

    logger.info(
        f"\nDone!  Episode: {topic!r}  "
        f"({episode['word_count']} words, audio: {final_mp3.name})"
    )
    return episode


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate an Asynchronous podcast episode.")
    parser.add_argument("topic", nargs="?", help="Episode topic")
    parser.add_argument("--repo", default=".", help="Repo root directory")
    parser.add_argument(
        "--type",
        "--episode-type",
        dest="episode_type",
        default=None,
        help="Episode type, e.g. deep_dive, overview, how_to, landscape.",
    )
    parser.add_argument(
        "--guest-mode",
        choices=sorted(_VALID_GUEST_HOST_MODES),
        default=None,
        help="Guest expert mode: auto, force, or off.",
    )
    parser.add_argument(
        "--guest",
        action="store_true",
        help="Force a synthetic/composite guest expert for this episode.",
    )
    parser.add_argument(
        "--no-guest",
        action="store_true",
        help="Disable guest experts for this episode.",
    )
    args = parser.parse_args()
    topic = args.topic or input("Enter podcast topic: ").strip()
    if not topic:
        sys.exit(1)
    guest_mode = args.guest_mode
    if args.guest:
        guest_mode = "force"
    if args.no_guest:
        guest_mode = "off"
    run(
        topic,
        repo_root=Path(args.repo),
        episode_type=args.episode_type,
        guest_host_mode=guest_mode,
    )
