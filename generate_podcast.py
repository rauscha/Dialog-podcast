#!/usr/bin/env python3
"""
Asynchronous Podcast Generator
Generates a two-host curiosity-radio episode on any topic.
Hosts: Juno (artistic) and Caspar (scientific).

Pipeline:
  1. Research brief    — web-searched facts, sources, story angles
  2. Dialogue script  — Juno/Caspar conversation from the brief
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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import anthropic

import audio_utils
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

try:
    from sonic_footnote_mixer import ResolvedFootnote, prepare_footnotes
    HAS_FOOTNOTE_MIXER = True
except ImportError:
    HAS_FOOTNOTE_MIXER = False
    ResolvedFootnote = None  # type: ignore[assignment]
    prepare_footnotes = None  # type: ignore[assignment]

# ── Models ─────────────────────────────────────────────────────────────────────
# Research stays on Opus for quality; dialogue + fact-check on Sonnet for cost.
_RESEARCH_MODEL   = "claude-opus-4-5"
_DIALOGUE_MODEL   = "claude-sonnet-4-6"
_FACT_CHECK_MODEL = "claude-sonnet-4-6"


# ── Config ─────────────────────────────────────────────────────────────────────

DEFAULTS: dict = {
    "podcast_title":        "Asynchronous",
    "podcast_description":  "Juno and Caspar roam the edges of art, science, and human experience.",
    "podcast_author":       "Juno & Caspar",
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
    "host_a_name":          "Juno",
    "host_a_voice":         "cedar",
    "host_a_role":          "artistic",
    "host_b_name":          "Caspar",
    "host_b_voice":         "marin",
    "host_b_role":          "scientific",
    "elevenlabs_voice_id_a": "",
    "elevenlabs_voice_id_b": "",
    "elevenlabs_guest_voice_ids": "",
    "elevenlabs_model":     "eleven_turbo_v2",
    "elevenlabs_stability": 0.5,
    "elevenlabs_similarity_boost": 0.75,
    "cartesia_voice_id_a":  "",
    "cartesia_voice_id_b":  "",
    "cartesia_guest_voice_ids": "",
    "cartesia_model":       "sonic-3.5",
    "cartesia_version":     "2026-03-01",
    "cartesia_sample_rate": 44100,
    "cartesia_bit_rate":    192000,
    "cartesia_speed":       1.0,
    "cartesia_language":    "en",
    "tts_max_fail_ratio":   0.2,
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
    # Sonic-footnote quality gates (redesign 2026-06-15). A cue is dropped unless
    # a real source clears the relevance floor (C) and the placement turn heralds
    # the sound (B); the spliced clip is framed by one deliberate pad (D) instead
    # of the incidental inter-turn gap. "Silence is preferred over decoration."
    "sonic_footnote_min_overlap":   1,    # min topical keyword overlap to use a source (C)
    "sonic_footnote_require_herald": True, # placement turn must reference the sound (B)
    "sonic_footnote_pad_ms":        350,  # deliberate symmetric frame around the cue (D)
    "use_guest_hosts":      True,
    "guest_host_mode":      "auto",
    "guest_host_max":       1,
    "guest_host_voice_pool": "ash,ballad,coral,sage,shimmer,echo,onyx,nova,alloy,fable",
    "guest_cross_provider": True,
    "script_quality_pipeline": True,
    "host_memory_path":     "host_memory.json",
    "host_memory_max_episodes": 12,
    "host_memory_max_items": 18,
    "use_personal_context": True,
    "personal_context_path": "personal_context.json",
    "personal_context_max_topics": 24,
    "personal_context_similarity_threshold": 0.34,
    "personal_context_sync_manifests": True,
    # Weekly journal-digest shows (Asynchronous Rounds) — show defs live in digests.json
    "digest_rank_model":    "claude-sonnet-4-6",
    "ncbi_email":           "",
    "ncbi_api_key_env":     "NCBI_API_KEY",
    "altmetric_enabled":    True,
    "digest_output_dir":    "episodes",
    "tts_model":            "gpt-4o-mini-tts",
    "tts_default_route":    {},
    "tts_routes":           {},
    "tts_request_timeout_sec": 180,
    "tts_command":          "",
    "tts_command_cwd":      "",
    "tts_command_timeout_sec": 600,
    "use_emotive_tts":      True,
    "turn_silence_ms":      180,    # base inter-turn gap; variable gaps flex around it (B2)
    # Phase B2 — speech timing. Edge-trim each turn's TTS-baked head/tail silence so
    # the inserted gap is the *perceived* gap, then flex that gap by conversational
    # context instead of a flat 180ms everywhere. A3's 10ms concat crossfade stays a
    # pure click-killer — the gap is the single spacing ruler, no double-apply.
    "turn_edge_trim":          True,   # trim leading/trailing near-silence from each turn
    "turn_edge_keep_ms":       40,     # silence pad to preserve at each edge (don't clip onsets)
    "turn_edge_trim_threshold_db": -50, # below this peak level counts as trimmable silence
    "turn_variable_gaps":      True,   # flex inter-turn gap by dialogue context (else flat base)
    "turn_gap_latch_ms":       70,     # interruption/dash latch or lowercase continuation — near-overlap
    "turn_gap_same_speaker_ms": 120,   # one host keeps going — keep the thought flowing
    "turn_gap_reaction_ms":    110,    # short non-question next line — snappy back-channel
    "turn_gap_beat_ms":        300,    # a long point that ends a sentence — let it land
    "turn_reaction_max_chars": 24,     # next line at/under this many chars counts as a reaction
    "turn_beat_min_chars":     320,    # prior line at/over this many chars can earn a landing beat
    # Phase B3 — speech realism. After symmetry-break and before fact-check, a sparse
    # pass adds soft disfluencies (um/uh before hard words: filler->pause->connector) and
    # short backchannel turns ("mm-hmm") for the listening host. Capped at ~1 per 6 turns.
    # Non-digest only (consultant-rounds register stays clean). Off => identical script.
    "use_disfluency_pass":     True,
    # Phase B4 (stretch) — overlaid backchannels. The short reaction turns B3 writes
    # for the *listening* host ("mm-hmm", "right") are mixed onto the TAIL of the
    # talking host's line — ducked, starting `lead_ms` before it ends — instead of
    # played sequentially, so the agreement physically overlaps the way real talk does.
    # OFF by default: higher-risk mixing, enable only after a live render is heard.
    "use_overlaid_backchannels": False,
    "backchannel_max_chars":   20,    # a reaction turn at/under this length can overlay
    "backchannel_duck_db":     8,     # how far under the main voice the backchannel sits
    "backchannel_lead_ms":     120,   # backchannel starts this many ms before the base ends
    "use_audio_mastering":  True,
    "normalize_turn_loudness": True,
    "audio_bitrate":        "192k",
    "audio_sample_rate":    44100,
    "audio_channels":       2,
    # Streaming-standard loudness (Spotify/YouTube). Apple-faithful -16/-1.5 stays
    # available via config override. Per-turn, final master, and inserted clips all
    # target this same value so the program is internally balanced.
    "audio_loudness_i":     -14.0,
    "audio_true_peak":      -1.0,
    "audio_lra":            11.0,
    "audio_highpass_hz":    60,
    "audio_lowpass_hz":     18000,
    "audio_master_two_pass": True,   # final master: two-pass linear loudnorm (else single-pass blind)
    "audio_deesser":        True,    # tame sibilance before loudnorm in the master chain
    "audio_deesser_freq":   6500,    # de-ess centre frequency (Hz); converted to normalized internally
    "audio_deesser_intensity": 0.40, # ffmpeg deesser i= (0..1); ~0.4 cuts sibilant peaks ~-5dB w/o dulling the body
    "concat_crossfade_ms":  10,      # micro-crossfade between speech segments at concat joins
    "music_crossfade_sec":  2.5,     # longer crossfade for music<->speech bookend transitions
    "music_prompt_model":   "claude-haiku-4-5-20251001",
    "title_model":          "claude-haiku-4-5-20251001",
    "music_model":          "facebook/musicgen-small",
    "music_duration_sec":   12,
    "music_fade_sec":       2,
    # ── Narration-first pipeline (2026-06-20 spec) ──────────────────
    "use_story_spine": True,
    "use_synthetic_listener": True,
    "use_expert_listener": True,
    "use_audio_roundtrip": True,
    "synthetic_listener_max_repair_rounds": 2,
    "clarification_density_turns": 8,
    "synthetic_listener_max_turns": 0,   # 0 = no cap; >0 truncates the naive read for cost
    "narration_ratio_threshold": 0.35,   # calibrated 2026-06-21: good digests measured 0.31-0.54; 0.6 over-triggered repair on good content
    "dialogue_draft_temperature": 0.6,   # spec §10.4 — lowered from 0.75
}

_BOOL_CONFIG_KEYS = {
    "use_clips",
    "use_music",
    "use_emotive_tts",
    "script_quality_pipeline",
    "use_sonic_footnotes",
    "sonic_footnote_require_herald",
    "use_guest_hosts",
    "use_personal_context",
    "personal_context_sync_manifests",
    "use_audio_mastering",
    "guest_cross_provider",
    "normalize_turn_loudness",
    "turn_edge_trim",
    "turn_variable_gaps",
    "use_disfluency_pass",
    "use_overlaid_backchannels",
    "audio_master_two_pass",
    "audio_deesser",
    "local_llm_think",
    "altmetric_enabled",
    "use_story_spine",
    "use_synthetic_listener",
    "use_expert_listener",
    "use_audio_roundtrip",
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
    "turn_edge_keep_ms",
    "turn_edge_trim_threshold_db",
    "turn_gap_latch_ms",
    "turn_gap_same_speaker_ms",
    "turn_gap_reaction_ms",
    "turn_gap_beat_ms",
    "turn_reaction_max_chars",
    "turn_beat_min_chars",
    "backchannel_max_chars",
    "backchannel_duck_db",
    "backchannel_lead_ms",
    "tts_request_timeout_sec",
    "tts_command_timeout_sec",
    "audio_sample_rate",
    "audio_channels",
    "audio_highpass_hz",
    "audio_lowpass_hz",
    "audio_deesser_freq",
    "concat_crossfade_ms",
    "cartesia_sample_rate",
    "cartesia_bit_rate",
    "synthetic_listener_max_repair_rounds",
    "clarification_density_turns",
    "synthetic_listener_max_turns",
}
_FLOAT_CONFIG_KEYS = {
    "music_fade_sec",
    "personal_context_similarity_threshold",
    "audio_loudness_i",
    "audio_true_peak",
    "audio_lra",
    "audio_deesser_intensity",
    "music_crossfade_sec",
    "elevenlabs_stability",
    "elevenlabs_similarity_boost",
    "cartesia_speed",
    "narration_ratio_threshold",
    "dialogue_draft_temperature",
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
        "JUNO": {
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
                "Asking Caspar to explain every fact.",
            ],
        },
        "CASPAR": {
            "core": "Scientifically grounded, dry, careful, allergic to fake certainty.",
            "strengths": [
                "Names evidence and limits without killing the mood.",
                "Enjoys a correction when it makes the story better.",
                "Can admit when the data is messier than his first answer.",
            ],
            "blind_spots": [
                "Can hide behind precision when a human question needs a human answer.",
                "Sometimes underestimates Juno's intuition.",
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
            "Juno pulls Caspar toward meaning; Caspar pulls Juno toward evidence. "
            "They like each other enough to disagree without flattening the disagreement."
        ),
        "recurring_dynamics": [
            "Juno makes a leap; Caspar tests it; both keep part of it.",
            "Caspar starts certain, then finds the caveat that makes him less certain.",
            "Juno notices when the science has a human cost.",
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
- JUNO: Artistic, broad-thinking, asks "what does this MEAN for us?" She finds
  unexpected metaphors and connections. She's enthusiastic and sometimes goes on
  tangents that turn out to be useful. She speaks with warmth and wonder.
- CASPAR: Scientifically grounded, methodical, slightly older and more skeptical.
  He's the one who says "well, actually..." but does it with dry wit and genuine
  curiosity, not pedantry. He grounds Juno's flights of fancy in evidence.

Format EVERY line with a speaker label AND an emotion delivery tag in square brackets:
JUNO [warm, curious]: dialogue text here
CASPAR [dry wit, measured]: dialogue text here

The emotion tag guides text-to-speech delivery — treat it as a director's note.
Keep tags to 2-4 words describing tone, and optionally pace or energy:
  JUNO [warm, wondering]: I keep thinking about this image...
  CASPAR [dry, slightly amused]: Well, the data would suggest otherwise.
  JUNO [genuinely excited, faster]: Wait — that's actually incredible.
  CASPAR [careful, searching]: There's something I can't quite put into words.
  JUNO [laughing slightly]: I mean, when you put it that way—
  CASPAR [somber, quieter]: And that's where it gets hard.
  JUNO [skeptical but intrigued]: Okay, but does it actually hold up?
  CASPAR [building, emphatic]: This is the part that changes everything.

Rules for great research-radio dialogue:
- They build on each other's thoughts — don't just trade monologues
- Interruptions are shown with em dashes: "And then the—"  "Right, exactly!"
- React to what the other person says. Use "wait", "okay but", "hold on",
  "that's the thing though"
- Tell it as a story — narrative arc, not just facts in order
- Juno often opens with an unexpected image or anecdote
- Caspar often grounds things by naming specific researchers or data
- Both can show genuine emotion: surprise, delight, discomfort
- No bullet points. No headers. Pure dialogue from first word to last.
- Sources section at the end as a natural spoken exchange:
  CASPAR: "And if you want to dig in further, the sources for today's episode
  include..." followed by a spoken list, with Juno occasionally chiming in
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

Your memo MUST end with these two labeled sections:

Exposition Order: an ordered list of what the listener must be TOLD before what —
the facts, names, and scenes that have to land first so nothing later is confusing.

Newcomer Promise: one sentence stating what a listener who knew NOTHING about this
topic will be able to retell a friend after the episode.

Frame the memo to serve TELLING THIS STORY clearly, not winning an argument. The
hosts' opinions are seasoning that comes after the material lands, never the spine.

Make the memo specific to the topic and the source material. Avoid generic stakes.
"""

_BEAT_SHEET_SYSTEM = """\
You are building the episode map before dialogue is written.

Create 8-12 beats. Each beat corresponds to ONE Story Spine segment, in order. For each beat:
1. Lead with the concrete ANCHOR — the scene/person/place/object the listener is shown.
2. State the STAKES in plain terms next.
3. Define every name in the segment's names_to_define, in line.
4. The HOST ANGLE (reaction, tension, or disagreement) is the LAST thing in the beat,
   and only after the material above has landed.

Build an arc, not a list. Do NOT manufacture disagreement; the hosts' job is to make
the listener understand, with opinion as seasoning at the end of a beat.

Each beat must also include:
- Beat id, purpose, and rough length
- Key claims or sources used
- Turning point by the end of the beat
- Transition into the next beat

Rules:
- If a Story Spine is provided it is authoritative (one beat per segment, in order).
  If the spine block is empty, fall back to building beats directly from the thesis and brief.
- Avoid symmetrical "Juno wonders, Caspar explains" repetition.
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
      "expertise": "what they can explain better than Juno or Caspar",
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
- Speaker labels must use only A-Z letters and spaces. No punctuation. No JUNO or CASPAR.
- Each guest needs an independent personality and a distinct voice from the provided pool.
- A guest should complicate or sharpen the episode, not deliver a polished lecture.
- If the episode type is complete_fiction, skip unless the user explicitly forced a guest.
"""

_DIALOGUE_DRAFT_SYSTEM = """\
You are drafting the first full dialogue for "Asynchronous".

Write only dialogue lines in this exact format:
JUNO [delivery tag]: text
CASPAR [delivery tag]: text
OPTIONAL GUEST LABEL [delivery tag]: text

Character rules:
- Juno is associative, visual, emotionally perceptive, and sometimes too eager to make meaning.
- Caspar is careful, dry, scientifically grounded, and sometimes too protected by caveats.
- They know each other. They can interrupt, misunderstand, correct, tease, and recover.
- Their disagreement should feel affectionate, not hostile.
- If the guest plan says "use", include only the guest labels from that plan.
- Never use the literal placeholder "OPTIONAL GUEST LABEL".
- Guest voices are synthetic/composite expert personas. They should sound like specific people
  with boundaries and quirks, but must not impersonate real people or claim real affiliations.

Grounding rules (non-negotiable):
- OPEN by introducing the topic: a listener must never wonder "what am I even
  listening to?"
- Explain every term, name, and abbreviation a non-expert wouldn't know, in line,
  the first time it appears.
- Establish before you adjudicate: deliver the scene and the stakes BEFORE any host
  reacts, judges, or disagrees.
- One concrete scene per segment — show it, don't reference it.

Host jobs (from the Story Spine, per segment):
- The CARRIER delivers the material — the scene, the people, what happened, the stakes.
- The SURROGATE is the listener's proxy: asks the exact questions a curious newcomer
  would, forcing the carrier to answer with CONTENT, not quips.
- Keep Juno (associative/artistic) and Caspar (grounded/skeptical) personalities, but
  the JOB above outranks personality. Cleverness is seasoning after the material lands.

Writing rules:
- Start with a concrete scene, object, person, or sensory image in the first 60 seconds.
- Follow the beat sheet, but do not announce sections or headers.
- Use the host memory for callbacks sparingly. One callback is enough unless the topic naturally asks for more.
- Use specific evidence, but do not end with a bibliography-style source list.
- Keep citations mostly implicit and natural: "a 2024 review", "the Stanford group", "historian X".
- If a guest appears, let Juno and Caspar interview, challenge, and react to them.
  The guest should enter for the beats where they add authority, then get out of the way.
- Let some turns be short. Let small jokes stay small.
- Avoid tidy TED-talk sentences and symmetrical Q&A.
- Target {target_words} words total, but end naturally.
"""

_ANTI_CLICHE_SYSTEM = """\
You are the anti-AI rewrite editor for "Asynchronous".
Rewrite the script to sound more human, less templated, and less evenly polished.

Return only dialogue lines in this exact format:
JUNO [delivery tag]: text
CASPAR [delivery tag]: text
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

_SYMMETRY_BREAK_SYSTEM = """\
You are the rhythm editor for "Asynchronous".

Your job: break the strict JUNO-CASPAR-JUNO-CASPAR alternation so the hosts
feel like two people actually talking — cutting in, reacting in clusters,
carrying unequal weight across different beats.

Return only dialogue lines in this exact format:
JUNO [delivery tag]: text
CASPAR [delivery tag]: text
OPTIONAL GUEST LABEL [delivery tag]: text
Never use the literal placeholder "OPTIONAL GUEST LABEL".

Pick 3-5 spots across the script and apply ONE structural change at each:

1. SPLIT a long turn into an interruption sequence:
   JUNO [excited]: So the key finding was—
   CASPAR [cutting in]: The one from the Lancet study?
   JUNO [resuming]: Yeah — that timing matters more than dosage.

2. RUN a 3-4 line reaction cluster while one host carries the main idea
   in longer turns:
   CASPAR [dry]: Three cohorts.
   JUNO [surprised]: Three?
   CASPAR [flat]: Over six years.
   JUNO [landing it]: That's a long time to follow a hunch.

3. Make one beat HOST-HEAVY: one host drives a chain of longer turns,
   the other only reacts. Then flip for a different beat.

4. Let one host revise themselves mid-turn with a dash:
   JUNO [working it out]: The risk is — well, it's not really a risk,
   it's more a delayed cost nobody's accounting for yet.

Do NOT:
- Change factual content, the episode arc, or beat order.
- Reassign a turn from one speaker to another.
- Add or remove guest turns; preserve guest labels and personality.
- Use delivery tags longer than 4 words.
"""

_DISFLUENCY_SYSTEM = """\
You are the speech-realism editor for "Asynchronous".

Two synthetic hosts (Juno and Caspar) are about to be read aloud by a TTS engine.
Right now every line is too clean — fully formed, evenly fluent, no hesitation.
Real people stumble a little before the words that matter and murmur tiny
acknowledgements while the other person talks. Add a SPARSE, surgical layer of
that, and nothing more.

Return only dialogue lines in this exact format:
JUNO [delivery tag]: text
CASPAR [delivery tag]: text
OPTIONAL GUEST LABEL [delivery tag]: text
Never use the literal placeholder "OPTIONAL GUEST LABEL".

You may add exactly TWO kinds of thing:

1. A SOFT DISFLUENCY before a genuinely hard or important word — a hesitation
   that buys the speaker a beat of thought. The shape is always
   FILLER -> PAUSE -> CONNECTOR -> the real point:
     CASPAR [thinking]: The mechanism is — um, so, it's basically a feedback loop.
   Rules for these:
   - Only an "um", "uh", or a brief false start ("The risk is— the real risk is").
   - Place it BEFORE the complex/important word, never mid-stride after it, and
     never on a short or throwaway line.
   - Use a dash or comma so the TTS actually pauses; then a connector
     ("so", "I mean", "well") into the real content.
   - The sentence's meaning and facts stay identical.

2. A BACKCHANNEL turn for the LISTENING host — its own short line, inserted
   while the other host is carrying a longer idea:
     JUNO [quietly]: Mm-hmm.
     JUNO [warm]: Right.
     CASPAR [curious]: Oh — interesting.
   Rules for these:
   - It is a brand-new short turn by the OTHER speaker, not an edit to an
     existing line. Two or three words at most.
   - Drop it between two turns of the host who is doing the talking, at a spot
     where a real listener would murmur agreement — not on every handoff.

DENSITY — this is the whole game. Overdoing it sounds MORE fake, not less.
- At most ONE added disfluency or backchannel per ~6 turns of script.
- A short script gets two or three total; never a tic on every line.
- When in doubt, leave the line clean.

Do NOT:
- Change factual content, the episode arc, or beat order.
- Reassign a turn from one speaker to another, or alter guest labels/personality.
- Add filler to a line that is already short, punchy, or a reaction.
- Stack two fillers in one line, or repeat the same filler word back-to-back.
- Use delivery tags longer than 4 words.
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
      "placement": "after Juno's opening image / before Caspar explains X / etc.",
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
JUNO [delivery tag]: text
CASPAR [delivery tag]: text

Rules:
- Preserve the fictional premise, invented events, emotional arc, and speaker labels.
- Never use the literal placeholder "OPTIONAL GUEST LABEL".
- Do not fact-check fictional worldbuilding as if it were reportage.
- Fix internal contradictions, unclear references, pacing snags, and spoken lines that would confuse TTS.
- Remove fake source citations, fake factual asides, or anything that presents invented events as real-world reporting.
- If real people, real companies, or real institutions appear, avoid defamatory invented actions and make the fictional frame clear in dialogue.
- Do not append notes, continuity comments, source lists, or section headers.
"""

_CLOSING_CALLBACK_SYSTEM = """\
You add a closing callback to a podcast script for "Asynchronous".

A callback is a brief, natural moment where Juno or Caspar connects something from the
current episode to a specific memorable detail from a prior episode. It should feel like a
genuine association — not a promotional call-back or a polished bow on a gift.

You receive:
- The current episode topic and thesis
- The last ~500 characters of the fact-checked script (so you know what was just said)
- Up to 5 recent episode callbacks, each labelled with an index, the prior topic, and
  a memorable detail or formulation from that episode

Task:
1. Pick the callback whose detail most naturally connects to the current episode's ideas or
   final exchange. If none genuinely fits, return {"selected_callback_index": null,
   "closing_segment": null}.
2. Write a closing exchange of 2-4 turns (~120-150 words total). Requirements:
   - Opens with JUNO or CASPAR noticing the connection — naturally, not "by the way"
   - Relaxed, end-of-conversation tone — not a summary or encore
   - Feel like two hosts with shared history (they recall past episodes casually)
   - Does NOT introduce new factual claims or start a new topic
   - Flows naturally from what was just said in the script tail
   - Each line: SPEAKER [emotion tag]: text

Return JSON only:
{
  "selected_callback_index": 2,
  "closing_segment": "JUNO [warm, drifting]: text\nCASPAR [dry]: text"
}

Or, if no callback fits:
{
  "selected_callback_index": null,
  "closing_segment": null
}
"""

_STORY_SPINE_SYSTEM = """\
You are the story architect for the podcast "Asynchronous." Before any dialogue \
exists, lay out the STORY the episode will tell — not the argument it will make. \
The hosts will be forced to follow this spine exactly.

Hard rules:
- Each segment must have ONE concrete anchor the listener is SHOWN — a scene, a \
person doing something, a place, an object. Not a topic, not a thesis.
- Establish before you adjudicate. Stakes and facts come first; the hosts' \
angle/disagreement is marked as coming AFTER the material lands.
- Every proper noun a smart layperson wouldn't know goes in names_to_define with a \
one-line gloss.
- Assume the listener knows nothing and cannot rewind. If a segment can't be \
followed cold, it is wrong.
- Assign a carrier (the host who TELLS this segment) and a surrogate (the host who \
asks the newcomer's questions here). Rotate them across segments so neither host is \
stuck in one role.

Return ONLY a JSON object with this exact shape:
{
  "logline": "one sentence: the story this episode tells",
  "newcomer_promise": "what a listener who knew nothing can follow/retell after",
  "segments": [
    {
      "id": "S1",
      "anchor": "the ONE concrete scene/person/place/object shown here",
      "stakes": "why this matters, in plain terms, before any cleverness",
      "names_to_define": [{"name": "X", "one_line": "gloss"}],
      "comprehension_target": "what the listener must understand by segment end",
      "host_angle": "the reaction/tension, explicitly AFTER the material lands",
      "carrier": "JUNO or CASPAR",
      "surrogate": "the other host"
    }
  ]
}
Do not include any prose outside the JSON object."""

_SYNTHETIC_LISTENER_SYSTEM = """\
You are a smart, curious layperson on your commute, listening to a podcast for the \
first time. You know NOTHING about this topic beyond what you have already heard. \
You CANNOT rewind, and you CANNOT look ahead.

You will be given everything you have heard SO FAR, and then the ONE new line you are \
hearing right now. Judge ONLY from what you have actually heard. You may not use any \
outside knowledge or guess what comes next.

For the new line, return ONLY a JSON object:
{
  "delivered_new_material": true/false,   // did this line TELL you something new
                                          // (a fact, scene, who someone is), vs just
                                          // react/comment on things already said?
  "confusion": "what just lost you, or null",
  "type": "undefined_name | lost_thread | no_stakes | whiplash | bored | null",
  "severity": "low | med | high | null",
  "holding_question": "an open question you're still carrying, or null",
  "engaged": true/false                   // are you still with it?
}
No prose outside the JSON."""

_EXPERT_LISTENER_SYSTEM = """\
You are a domain expert reviewing a podcast script for HOLLOWNESS and ERROR. You know \
the field. Find places where the hosts REACT TO or ARGUE ABOUT material the script \
never actually delivered, where names are dropped but not rendered into content, and \
any factual errors.

Return ONLY JSON:
{
  "hollow_spots": [{"turn": <int>, "detail": "what's hollow"}],
  "errors": [{"turn": <int>, "detail": "the factual problem"}]
}
Turn numbers are 0-based line indices among the dialogue lines. No prose outside JSON."""

_REWRITE_GLOSS_SYSTEM = """\
You repair ONE line of a podcast script so a first-time listener isn't lost. You will \
get the line and the confusion it caused. Fold a short, natural gloss (<= 8 words) into \
the line — define the name or fill the small gap — WITHOUT adding a new line and without \
turning it into a question. Keep the speaker, the emotion tag, and the voice. Return \
ONLY the single rewritten line in the exact format  SPEAKER [emotion]: text"""


_CLARIFY_INSERT_SYSTEM = """\
A first-time listener got lost at a meaty point and a curious newcomer would genuinely \
want this drawn out. Write a SHORT two-line exchange that turns that confusion into real \
on-show back-and-forth: first the SURROGATE host asks the exact newcomer question, then \
the CARRIER host answers with actual content (the stakes/the scene), not a quip. Use the \
two speaker names given. Do NOT do "what's that?/it's X" trivia. Return ONLY the two \
lines, each in the format  SPEAKER [emotion]: text"""


_PERFORMANCE_SYSTEM = """\
You are the final performance editor for a conversational TTS podcast script.

Return only dialogue lines in this exact format:
JUNO [delivery tag]: text
CASPAR [delivery tag]: text
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
    "juno_noticed": "...",
    "caspar_challenged": "...",
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
    # Wrap a plain string system prompt in a cached content block so repeated
    # calls that reuse the same (large) prompt — e.g. digest runs across 3 shows —
    # hit the Anthropic prompt cache and skip re-encoding those tokens.
    system_payload: str | list = (
        [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        if isinstance(system, str)
        else system
    )
    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system_payload,
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
        r"^([A-Z][A-Z]{0,40})(?:\s*\[[^\]]*\])?\s*:",
        script,
        re.MULTILINE,
    )
    if first_turn:
        script = script[first_turn.start():]
    return script.strip()


# _TURN_LINE_RE / _split_turns / _join_turns are a second, intentionally distinct
# parser from _parse_dialogue_turns. That function requires cfg, filters to known
# speaker labels, and accumulates multi-line turns — designed for TTS assembly.
# These functions are cfg-free, line-level, and keep an exact `raw` field so that
# _join_turns(_split_turns(script)) == script losslessly. Required contract for the
# synthetic-listener (Task 7, feeds one turn at a time) and repair loop (Task 9,
# inserts/edits/renumbers turns) which need round-trip fidelity without cfg.
_TURN_LINE_RE = re.compile(r"^([A-Z][A-Z0-9_]{0,39})\s*(?:\[([^\]]*)\])?\s*:\s*(.*)$")


def _split_turns(script: str) -> list[dict]:
    """Parse a dialogue script into structured turns. Non-dialogue lines skipped."""
    turns: list[dict] = []
    for line in (script or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        m = _TURN_LINE_RE.match(stripped)
        if not m:
            continue
        speaker, emotion, text = m.group(1), (m.group(2) or "").strip(), m.group(3).strip()
        turns.append({
            "index": len(turns),
            "speaker": speaker,
            "emotion": emotion,
            "text": text,
            "raw": line,
        })
    return turns


def _join_turns(turns: list[dict]) -> str:
    """Inverse of _split_turns; reassembles using each turn's raw line."""
    return "\n".join(t["raw"] for t in turns)


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
        author = str(card.get("author") or "").strip()
        url = str(card.get("url") or "").strip()
        # Author is a single last name (e.g. "Wright"); render as "Wright et al."
        # so digest show-notes give listeners a complete handle on each paper.
        author_label = f"{author} et al." if author and " " not in author and len(author) < 40 else author
        parts = [p for p in [author_label, publication, year, title] if p]
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


def _combined_guest_voice_pool(cfg: dict) -> list[dict]:
    """ElevenLabs + Cartesia guest voices interleaved and tagged by provider.

    Interleaving (EL, Cartesia, EL, Cartesia, ...) keeps both providers in play
    even for single-guest episodes once the per-topic rotation offset is applied,
    so the Cartesia voices actually get used instead of always losing to slot 0.
    """
    el_ids = _csv_list(cfg.get("elevenlabs_guest_voice_ids"))
    car_ids = _csv_list(cfg.get("cartesia_guest_voice_ids"))
    pool: list[dict] = []
    for idx in range(max(len(el_ids), len(car_ids))):
        if idx < len(el_ids):
            pool.append({"provider": "elevenlabs", "voice_id": el_ids[idx]})
        if idx < len(car_ids):
            pool.append({"provider": "cartesia", "voice_id": car_ids[idx]})
    return pool


def _stable_seed(text: str) -> int:
    """Deterministic, PYTHONHASHSEED-independent non-negative int from text."""
    digest = hashlib.md5(str(text or "").encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _fallback_guest_label(index: int) -> str:
    labels = ["GUEST EXPERT", "GUEST ANALYST", "GUEST GUIDE", "GUEST CRITIC"]
    return labels[index] if index < len(labels) else f"GUEST {chr(65 + (index % 26))}"


def _sanitize_guest_label(value: object, index: int, used: set[str]) -> str:
    label = re.sub(r"[^A-Za-z ]+", " ", str(value or ""))
    label = re.sub(r"\s+", " ", label).strip().upper()
    if not label or label in {"JUNO", "CASPAR"}:
        label = _fallback_guest_label(index)
    words = label.split()
    if len(label) > 28:
        label = " ".join(words[:3]).strip() or _fallback_guest_label(index)
    if label in {"JUNO", "CASPAR"}:
        label = _fallback_guest_label(index)
    base = label
    suffix_index = 0
    while label in used:
        suffix = chr(65 + (suffix_index % 26))
        label = f"{base} {suffix}"
        suffix_index += 1
    used.add(label)
    return label


def _normalize_guest_plan(plan: dict | None, cfg: dict, *, force: bool = False, topic: str = "") -> dict:
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
    combined_guest_pool = (
        _combined_guest_voice_pool(cfg) if cfg.get("guest_cross_provider", True) else []
    )
    guest_seed = _stable_seed(topic)
    used_labels = {"JUNO", "CASPAR"}
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
        guest_entry = {
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
                or "Adds expert context where Juno and Caspar need outside authority."
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
        if combined_guest_pool:
            picked = combined_guest_pool[(guest_seed + len(guests)) % len(combined_guest_pool)]
            guest_entry["tts_provider"] = picked["provider"]
            if picked["provider"] == "elevenlabs":
                guest_entry["elevenlabs_voice_id"] = picked["voice_id"]
            elif picked["provider"] == "cartesia":
                guest_entry["cartesia_voice_id"] = picked["voice_id"]
        guests.append(guest_entry)

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
    return _normalize_guest_plan(_extract_json_object(raw_plan), cfg, force=force, topic=topic)


def _script_quality_metrics(script: str, memory: dict, cfg: dict | None = None) -> dict:
    lowered = script.lower()
    blacklist = memory.get("phrase_blacklist", _DEFAULT_HOST_MEMORY["phrase_blacklist"])
    hits = {
        phrase: lowered.count(str(phrase).lower())
        for phrase in blacklist
        if str(phrase).strip() and str(phrase).lower() in lowered
    }
    juno_turns = len(re.findall(r"^JUNO(?:\s*\[[^\]]*\])?\s*:", script, re.M))
    caspar_turns = len(re.findall(r"^CASPAR(?:\s*\[[^\]]*\])?\s*:", script, re.M))
    guest_labels = {
        match.group(1).strip().upper()
        for match in re.finditer(_TURN_RE.pattern, script, re.M)
        if match.group(1).strip().upper() not in {"JUNO", "CASPAR"}
    }
    active_guest_labels = {
        str(guest.get("label", "")).upper()
        for guest in (cfg or {}).get("active_guest_hosts", [])
        if isinstance(guest, dict)
    }
    guest_labels = guest_labels | {label for label in active_guest_labels if label}
    return {
        "juno_turns": juno_turns,
        "caspar_turns": caspar_turns,
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
        "curiosity-radio show with two hosts (Juno and Caspar) that turns "
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
            "juno_noticed": "",
            "caspar_challenged": "",
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
        system=[{"type": "text", "text": _RESEARCH_SYSTEM, "cache_control": {"type": "ephemeral"}}],
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
    logger.info("[2/5] Writing Juno/Caspar dialogue script...")
    dialogue_resp = client.messages.create(
        model=_DIALOGUE_MODEL,
        max_tokens=8192,
        system=[{
            "type": "text",
            "text": _DIALOGUE_SYSTEM.format(target_words=target_words),
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[
            {
                "role": "user",
                "content": (
                    f"Using the research brief below, write a Juno/Caspar dialogue "
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


def _select_and_write_callback(
    topic: str,
    thesis: str,
    script_tail: str,
    memory: dict,
    client: anthropic.Anthropic | None,
    cfg: dict,
) -> str | None:
    """Pick a past-episode callback and write a 120-150 word closing exchange.

    Selects the most thematically resonant entry from the last 5 usable_callback
    items in episode_history, then writes a 2-4 turn JUNO/CASPAR closing segment.
    Returns None when no good fit exists or client is unavailable.
    """
    if client is None:
        return None

    history = [
        e for e in (memory.get("episode_history") or [])
        if isinstance(e, dict) and e.get("usable_callback")
    ]
    if not history:
        return None

    candidates = history[-5:]
    candidate_lines = []
    for i, e in enumerate(candidates):
        prior_topic = str(e.get("topic") or "")[:120]
        callback_text = str(e.get("usable_callback") or "")
        candidate_lines.append(
            f"[{i}] Prior topic: {prior_topic!r}\n    Callback detail: {callback_text}"
        )

    content = (
        f"Current episode topic: {topic}\n\n"
        f"Current episode thesis:\n{thesis}\n\n"
        f"End of script (last ~500 chars):\n{script_tail[-500:]}\n\n"
        f"Recent episode callbacks:\n" + "\n".join(candidate_lines)
    )

    try:
        raw = _anthropic_text(
            client,
            model=_model_for(cfg, "dialogue_model", _DIALOGUE_MODEL),
            max_tokens=600,
            system=_CLOSING_CALLBACK_SYSTEM,
            content=content,
            temperature=0.65,
            cfg=cfg,
        )
    except Exception as exc:
        logger.warning("[callback] Closing callback pass failed: %s", exc)
        return None

    data = _extract_json_object(raw) if raw else {}
    segment = data.get("closing_segment")
    if not segment or not isinstance(segment, str):
        return None
    cleaned = _strip_to_dialogue(segment.strip())
    return cleaned if cleaned else None


_STORY_SPINE_SEGMENT_FIELDS = (
    "id", "anchor", "stakes", "comprehension_target",
    "host_angle", "carrier", "surrogate",
)


def _validate_story_spine(obj: dict) -> tuple[bool, list[str]]:
    """Pure structural validation of a Story Spine. open_loops is optional."""
    errors: list[str] = []
    if not isinstance(obj, dict):
        return False, ["spine is not an object"]
    for key in ("logline", "newcomer_promise"):
        if not isinstance(obj.get(key), str) or not obj.get(key, "").strip():
            errors.append(f"missing or empty top-level field: {key}")
    segments = obj.get("segments")
    if not isinstance(segments, list) or not segments:
        errors.append("segments must be a non-empty list")
        return (not errors), errors
    for i, seg in enumerate(segments):
        if not isinstance(seg, dict):
            errors.append(f"segment {i} is not an object")
            continue
        for field in _STORY_SPINE_SEGMENT_FIELDS:
            if not str(seg.get(field, "")).strip():
                errors.append(f"segment {i} ({seg.get('id', '?')}): missing field {field}")
        if not isinstance(seg.get("names_to_define", []), list):
            errors.append(f"segment {i}: names_to_define must be a list")
    return (not errors), errors


def _build_story_spine(topic, cfg, client, thesis, guest_plan, research_package) -> dict | None:
    """Produce the Story Spine artifact. Returns None if disabled or invalid."""
    if not cfg.get("use_story_spine", True):
        return None
    if str(cfg.get("episode_type", "")).strip().lower() == "digest":
        logger.info("[story-spine] digest episode — skipping spine (digest uses its structural_plan)")
        return None
    brief = research_package.get("readable_brief", "") if isinstance(research_package, dict) else ""
    content = (
        f"TOPIC: {topic}\n\n"
        f"EDITORIAL MEMO (thesis):\n{thesis}\n\n"
        f"GUEST PLAN:\n{guest_plan}\n\n"
        f"RESEARCH BRIEF:\n{brief}\n"
    )
    raw = _anthropic_text(
        client,
        model=_model_for(cfg, "dialogue_model", _DIALOGUE_MODEL),
        system=_STORY_SPINE_SYSTEM,
        content=content,
        max_tokens=4096,
        temperature=0.5,
        cfg=cfg,
    )
    spine = _extract_json_object(raw)
    if spine is None:
        logger.warning("[story-spine] no JSON parsed; proceeding without a spine")
        return None
    ok, errors = _validate_story_spine(spine)
    if not ok:
        logger.warning("[story-spine] invalid spine, proceeding without: %s", "; ".join(errors[:5]))
        return None
    logger.info("[story-spine] %d segments; logline: %s",
                len(spine.get("segments", [])), spine.get("logline", "")[:80])
    return spine


def _compute_narration_ratio(per_turn: list[dict], threshold: float) -> dict:
    """Pure: render-beats / total-beats from the naive trace's per-turn verdicts."""
    total = len(per_turn)
    render = sum(1 for t in per_turn if t.get("delivered_new_material"))
    react = total - render
    ratio = (render / total) if total else 0.0
    return {
        "render_beats": render,
        "react_only_beats": react,
        "ratio": ratio,
        "threshold": threshold,
        "pass": total > 0 and ratio >= threshold,
    }


def _naive_listener_turn(client, cfg, prior_text: str, this_turn: dict) -> dict:
    content = (
        "WHAT YOU'VE HEARD SO FAR:\n"
        + (prior_text if prior_text else "(nothing yet — this is the very first line)")
        + "\n\nTHE NEW LINE YOU'RE HEARING NOW:\n"
        + this_turn["raw"]
    )
    raw = _anthropic_text(
        client,
        model=_model_for(cfg, "dialogue_model", _DIALOGUE_MODEL),
        system=_SYNTHETIC_LISTENER_SYSTEM,
        content=content,
        max_tokens=512,
        temperature=0.2,
        cfg=cfg,
    )
    verdict = _extract_json_object(raw) or {}
    verdict["turn"] = this_turn["index"]
    # Normalise null-ish strings to None.
    for k in ("confusion", "type", "severity", "holding_question"):
        if str(verdict.get(k)).strip().lower() in ("", "null", "none"):
            verdict[k] = None
    verdict["delivered_new_material"] = bool(verdict.get("delivered_new_material"))
    verdict["engaged"] = bool(verdict.get("engaged", True))
    return verdict


def _run_naive_listener(script: str, cfg: dict, client) -> dict:
    """Iterative, no-look-ahead naive read. Returns the comprehension trace."""
    turns = _split_turns(script)
    cap = int(cfg.get("synthetic_listener_max_turns", 0) or 0)
    if cap > 0:
        turns = turns[:cap]
    per_turn: list[dict] = []
    breaks: list[dict] = []
    first_bounce = None
    prior_lines: list[str] = []
    for t in turns:
        v = _naive_listener_turn(client, cfg, "\n".join(prior_lines), t)
        per_turn.append(v)
        if v.get("confusion"):
            brk = {"turn": v["turn"], "type": v.get("type"),
                   "detail": v["confusion"], "severity": v.get("severity") or "low"}
            breaks.append(brk)
        if first_bounce is None and v.get("engaged") is False:
            first_bounce = v["turn"]
        prior_lines.append(t["raw"])
    threshold = float(cfg.get("narration_ratio_threshold", 0.6))
    return {
        "naive": {
            "breaks": breaks,
            "followed_overall": first_bounce is None,
            "first_bounce_turn": first_bounce,
            "per_turn": per_turn,
        },
        "narration_vs_banter": _compute_narration_ratio(per_turn, threshold),
    }


def _run_expert_listener(script: str, cfg: dict, client) -> dict:
    if not cfg.get("use_expert_listener", True):
        return {"hollow_spots": [], "errors": []}
    raw = _anthropic_text(
        client,
        model=_model_for(cfg, "dialogue_model", _DIALOGUE_MODEL),
        system=_EXPERT_LISTENER_SYSTEM,
        content=script,
        max_tokens=2048,
        temperature=0.2,
        cfg=cfg,
    )
    out = _extract_json_object(raw) or {}
    return {
        "hollow_spots": out.get("hollow_spots") or [],
        "errors": out.get("errors") or [],
    }


# ── Repair loop (narration-first pipeline §6.5) ─────────────────────────────

_MEATY_TYPES = {"no_stakes", "lost_thread"}


def _select_repair_move(break_item: dict, clarify_used_turns: list[int], cfg: dict) -> str:
    """Pure logic — no LLM. Returns 'rewrite', 'clarify', or 'skip'."""
    severity = (break_item.get("severity") or "low").lower()
    btype = (break_item.get("type") or "").lower()
    if severity == "low":
        return "skip"
    if btype in _MEATY_TYPES and severity in ("med", "high"):
        density = int(cfg.get("clarification_density_turns", 8))
        turn = int(break_item.get("turn", 0))
        too_close = any(abs(turn - u) < density for u in clarify_used_turns)
        return "rewrite" if too_close else "clarify"
    # undefined_name, whiplash, bored, or anything else med/high → inline gloss.
    return "rewrite"


def _renumber_turns(turns: list[dict]) -> list[dict]:
    return [dict(t, index=i) for i, t in enumerate(turns)]


def _apply_repair(turns: list[dict], break_item: dict, move: str, cfg: dict, client) -> list[dict]:
    """Return a new turns list with the chosen repair applied. Best-effort:
    on any failure, returns the turns unchanged."""
    idx = int(break_item.get("turn", -1))
    target = next((t for t in turns if t["index"] == idx), None)
    if target is None or move == "skip":
        return turns
    try:
        if move == "rewrite":
            new_line = _anthropic_text(
                client, model=_model_for(cfg, "dialogue_model", _DIALOGUE_MODEL),
                system=_REWRITE_GLOSS_SYSTEM,
                content=f"LINE:\n{target['raw']}\n\nCONFUSION:\n{break_item.get('detail','')}",
                max_tokens=300, temperature=0.4, cfg=cfg,
            ).strip()
            parsed = _split_turns(new_line)
            if parsed:
                return [dict(t, raw=parsed[0]["raw"], text=parsed[0]["text"]) if t["index"] == idx else t
                        for t in turns]
            return turns
        # move == "clarify": insert two lines AFTER the break turn.
        carrier = target["speaker"]
        surrogate = "CASPAR" if carrier == "JUNO" else "JUNO"
        two = _anthropic_text(
            client, model=_model_for(cfg, "dialogue_model", _DIALOGUE_MODEL),
            system=_CLARIFY_INSERT_SYSTEM,
            content=(f"SURROGATE = {surrogate}\nCARRIER = {carrier}\n\n"
                     f"LINE THAT LOST THEM:\n{target['raw']}\n\n"
                     f"CONFUSION:\n{break_item.get('detail','')}"),
            max_tokens=400, temperature=0.5, cfg=cfg,
        )
        inserted = _split_turns(two)
        if not inserted:
            return turns
        # Splice the inserted lines in right after the break turn, then renumber.
        cut = turns.index(target) + 1
        new_turns = turns[:cut] + inserted + turns[cut:]
        return _renumber_turns(new_turns)
    except Exception as exc:  # best-effort, never load-bearing
        logger.warning("[repair] move=%s failed at turn %s: %s", move, idx, exc)
        return turns


def _run_repair_loop(script: str, cfg: dict, client) -> tuple[str, dict]:
    """Gate → repair → re-gate until pass or max rounds. Surface-don't-block on residual."""
    if not cfg.get("use_synthetic_listener", True):
        return script, {}
    max_rounds = int(cfg.get("synthetic_listener_max_repair_rounds", 2))
    current = script
    trace = _run_naive_listener(current, cfg, client)
    expert = _run_expert_listener(current, cfg, client)
    rounds = 0
    while rounds < max_rounds:
        naive = trace["naive"]
        ratio_ok = trace["narration_vs_banter"]["pass"]
        actionable = [b for b in naive["breaks"] if (b.get("severity") or "low").lower() != "low"]
        if not actionable and ratio_ok and not expert["hollow_spots"]:
            break
        turns = _split_turns(current)
        clarify_used: list[int] = []
        # Highest severity first so the worst breaks get the richer repair budget.
        order = {"high": 0, "med": 1, "low": 2}
        for brk in sorted(actionable, key=lambda b: order.get((b.get("severity") or "low").lower(), 3)):
            move = _select_repair_move(brk, clarify_used, cfg)
            if move == "clarify":
                clarify_used.append(int(brk.get("turn", 0)))
            turns = _apply_repair(turns, brk, move, cfg, client)
        # Expert hollow spots always deepen via rewrite.
        for hs in expert["hollow_spots"]:
            turns = _apply_repair(turns, {**hs, "type": "lost_thread", "severity": "high"}, "rewrite", cfg, client)
        current = _join_turns(turns)
        rounds += 1
        trace = _run_naive_listener(current, cfg, client)
        expert = _run_expert_listener(current, cfg, client)
    if not trace.get("narration_vs_banter", {}).get("pass", False) or \
       any((b.get("severity") or "low").lower() == "high" for b in trace["naive"]["breaks"]):
        logger.warning("[repair] residual comprehension issues after %d rounds — "
                       "publishing but surfacing trace: ratio=%.2f, high-sev breaks=%d",
                       rounds, trace["narration_vs_banter"].get("ratio", 0.0),
                       sum(1 for b in trace["naive"]["breaks"] if (b.get("severity") or "").lower() == "high"))
    return current, trace


def _script_from_research_package(
    topic: str,
    cfg: dict,
    client: anthropic.Anthropic | None,
    repo_root: Path,
    run_id: str,
    research_package: dict,
    *,
    web_factcheck: bool = True,
) -> dict:
    """Shared downstream pipeline: research_package -> final performance script.

    Used by both `_quality_research_and_script` (web-searched topics) and
    `_digest_research_and_script` (curated article lists). Runs thesis ->
    guest decision -> beat sheet -> sonic plan -> dialogue draft ->
    anti-cliche -> fact-check (or fiction continuity) -> performance ->
    host-memory / personal-context update.

    web_factcheck=True keeps the live web_search tool on the fact-check pass;
    set False to keep that pass tool-free (digests use this so the supplied
    paraphrased findings stay the source of truth).
    """
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

    research_brief = str(research_package.get("readable_brief") or "")
    source_cards = research_package.get("source_cards", [])
    key_claims = research_package.get("key_claims", [])
    if not isinstance(source_cards, list):
        source_cards = []
    if not isinstance(key_claims, list):
        key_claims = []

    is_digest = (str(cfg.get("episode_type", "")).strip().lower() == "digest")
    digest_overlay = (
        f"\n\n{_digest_performance_overlay(research_package)}" if is_digest else ""
    )

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
            f"{digest_overlay}"
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

    story_spine = _build_story_spine(topic, cfg, client, thesis, guest_plan, research_package)
    spine_text = json.dumps(story_spine, ensure_ascii=False, indent=2) if story_spine else ""
    # spine_text consumed by beat-sheet/draft (Tasks 5-6)

    logger.info("[2/5] Building beat sheet and host stance map...")
    beat_sheet = _anthropic_text(
        client,
        model=_model_for(cfg, "dialogue_model", _DIALOGUE_MODEL),
        max_tokens=4096,
        system=_BEAT_SHEET_SYSTEM,
        content=(
            (f"STORY SPINE (authoritative — one beat per segment, in order):\n{spine_text}\n\n" if spine_text else "")
            + f"Topic: {topic}\n\n"
            f"{type_note}\n\n"
            f"Target words: {target_words}\n\n"
            f"Host memory:\n{host_memory_text}\n\n"
            f"Personal context:\n{personal_context_text}\n\n"
            f"Editorial memo:\n{thesis}\n\n"
            f"Guest plan:\n{json.dumps(guest_plan, indent=2)}\n\n"
            f"Research package:\n{json.dumps(research_package, indent=2)[:26000]}"
            f"{digest_overlay}"
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

    logger.info("[2/5] Drafting Juno/Caspar dialogue...")
    draft_script = _anthropic_text(
        client,
        model=_model_for(cfg, "dialogue_model", _DIALOGUE_MODEL),
        max_tokens=8192,
        system=_DIALOGUE_DRAFT_SYSTEM.format(target_words=target_words),
        content=(
            (f"STORY SPINE (authoritative — Carrier tells / Surrogate asks, one scene per segment):\n{spine_text}\n\n" if spine_text else "")
            + f"Topic: {topic}\n\n"
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
            f"{digest_overlay}"
        ),
        temperature=float(cfg.get("dialogue_draft_temperature", 0.6)),
        cfg=cfg,
    )
    draft_script = _strip_to_dialogue(draft_script)

    listener_trace = {}
    if cfg.get("use_synthetic_listener", True) and not is_digest:
        logger.info("[gate] Synthetic First Listener -- comprehension pass...")
        draft_script, listener_trace = _run_repair_loop(draft_script, cfg, client)
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
            f"{digest_overlay}"
        ),
        temperature=0.65,
        cfg=cfg,
    )
    natural_script = _strip_to_dialogue(natural_script)

    # P1-D: symmetry-break pass — non-digest episodes only (digests have a
    # tightly specified consultant-rounds structure that must not be disturbed).
    if not is_digest:
        logger.info("[2/5] Breaking turn symmetry and rhythm...")
        rhythm_script = _anthropic_text(
            client,
            model=_model_for(cfg, "dialogue_model", _DIALOGUE_MODEL),
            max_tokens=8192,
            system=_SYMMETRY_BREAK_SYSTEM,
            content=(
                f"Topic: {topic}\n\n"
                f"{type_note}\n\n"
                f"Guest plan:\n{json.dumps(guest_plan, indent=2)}\n\n"
                f"Script:\n{natural_script}"
            ),
            temperature=0.6,
            cfg=cfg,
        )
        natural_script = _strip_to_dialogue(rhythm_script)

    # P1-B3: disfluency / backchannel pass — non-digest only (consultant-rounds
    # register stays clean). Sparse soft disfluencies before hard words and short
    # backchannel turns for the listening host. Runs before fact-check so any
    # wording corrections still apply to the final lines. Flag-gated; off ⇒ no-op.
    if not is_digest and cfg.get("use_disfluency_pass", True):
        logger.info("[2/5] Adding speech disfluencies and backchannels...")
        disfluent_script = _anthropic_text(
            client,
            model=_model_for(cfg, "dialogue_model", _DIALOGUE_MODEL),
            max_tokens=8192,
            system=_DISFLUENCY_SYSTEM,
            content=(
                f"Topic: {topic}\n\n"
                f"{type_note}\n\n"
                f"Guest plan:\n{json.dumps(guest_plan, indent=2)}\n\n"
                f"Script:\n{natural_script}"
            ),
            temperature=0.5,
            cfg=cfg,
        )
        natural_script = _strip_to_dialogue(disfluent_script)

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
        fact_check_tools = (
            [{"type": "web_search_20250305", "name": "web_search"}]
            if web_factcheck
            else None
        )
        fact_check_guidance = (
            "Use the research package as the first reference, and web search "
            "when anything important needs verification."
            if web_factcheck
            else "Use the research package as the source of truth — do NOT "
                 "introduce facts that are not supported by the supplied package."
        )
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
                f"{fact_check_guidance} Correct only claims that need correcting or softening.\n\n"
                f"Research package:\n{json.dumps(research_package, indent=2)[:26000]}\n\n"
                f"Script:\n{natural_script}"
            ),
            tools=fact_check_tools,
            temperature=0.2,
            cfg=cfg,
        )
    fact_checked_script = _strip_to_dialogue(fact_checked_script)

    # Closing callback — non-digest only (digest consultant-rounds structure must not change).
    if not is_digest:
        logger.info("[3/5] Weaving closing callback from episode history...")
        callback_segment = _select_and_write_callback(
            topic=topic,
            thesis=thesis,
            script_tail=fact_checked_script,
            memory=memory,
            client=client,
            cfg=cfg,
        )
        if callback_segment:
            fact_checked_script = fact_checked_script.rstrip() + "\n\n" + callback_segment

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
            f"{digest_overlay}"
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
        "listener_trace": listener_trace,
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
            *(["closing_callback"] if not is_digest else []),
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


def _quality_research_and_script(
    topic: str,
    cfg: dict,
    client: anthropic.Anthropic | None,
    repo_root: Path,
    run_id: str = "",
) -> dict:
    """Standard entry point: open-ended web_search research -> shared pipeline."""
    episode_type = normalize_episode_type(str(cfg.get("episode_type", "")))
    type_note = episode_type_context(episode_type)
    # Just-in-time personal context for the research prompt only;
    # _script_from_research_package reloads its own copy for downstream passes.
    _, _, _, personal_context_text = _personal_context_for_topic(repo_root, cfg, topic)

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
    return _script_from_research_package(
        topic, cfg, client, repo_root, run_id, research_package
    )


_DIGEST_RESEARCH_SYSTEM = """\
You are the editorial producer for a peer-level weekly journal-club podcast.
You have already been handed a ranked list of recently published articles
(one headline + 3-5 quick-hit rounds), each with a short already-paraphrased
finding line, journal, year, first_author, evidence tier, and DOI. You will
NOT see the abstracts and must NEVER reproduce abstract text verbatim.

Your job: assemble a clean research package the dialogue writer can use to
draft a peer-to-peer rounds-style episode. Stay clinical and concrete.
Paraphrase the supplied findings further if useful; never invent numbers or
claims that are not in the supplied finding line.

Listeners hear this on their commute and cannot click through to show notes
in real time. Every paper's first spoken mention must therefore announce
itself as a citation, not as "a new study." You produce the exact spoken
intro line for each paper so the dialogue writer cannot drift.

Return JSON only with these keys:
- topic
- headline_intro: ONE spoken sentence the dialogue writer will deliver
  verbatim or near-verbatim on first mention of the headline paper. Form:
  "From [journal abbreviation], [year]: [first_author] et al., [study
  design including n if known] — [short paper title or topic phrase]."
  Use "and colleagues" if first_author is null. Keep it natural enough to
  speak. Example: "From AJOG, 2026: Wright and colleagues, an RCT-embedded
  multicenter cohort of about 4,800 chronic hypertensives — first-trimester
  biomarker screening before aspirin."
- rounds_intros: array of one spoken intro sentence per rounds paper in
  rank order, same form as headline_intro. One sentence each.
- structural_plan: object with shape {
    "headline_share": 0.55,
    "rounds_share_each": 0.10,
    "pivot_line": "the literal spoken sentence the host says to transition
       from the headline segment into rounds — e.g. 'Rounds — four other
       things this week.' Keep it short, declarative, no rhetorical flourish.",
    "headline_arc": [
       "clinical question the paper answers",
       "design choice that earns the evidence grade",
       "effect size or key result in numbers",
       "important caveat or limitation",
       "what changes in practice (or honestly: what doesn't)"
    ],
    "rounds_beat_template": [
       "form-first intro (use rounds_intros line verbatim)",
       "the finding in one sentence",
       "the one caveat the listener must hear",
       "the clinical hook — what to do or watch for"
    ]
  }
  These are instructions for the downstream beat sheet and dialogue stages.
- readable_brief: 4-8 paragraphs. Open with why this week matters in the
  field. Walk through the headline paper (design, what was measured, the
  effect, key caveats, what it would change in practice) — full structure,
  not a hook. Then a clean break — one paragraph per rounds paper, each
  opening with the formal citation, NOT with narrative through-line. End
  with what to watch and what is still unsettled.
- source_cards: one entry per article in rank order (headline first, then
  rounds), shape {id,title,author,publication,year,url,why_it_matters}.
  Populate `author` from the supplied first_author field — leave empty
  ONLY if first_author was null in the input.
- key_claims: array of {id,claim,confidence,source_ids}. One per article.
  claim is the finding in your own words. confidence is "high" for RCT,
  meta-analysis, or large multicenter; "medium" for solid observational;
  "low" for preprints, small-N, single-center, or pilot work.
- story_hooks: 2-4 angles a host could open or pivot on.
- counterintuitive_findings: 0-3 surprises across the supplied papers.
- open_questions: 2-4 honest unresolved questions in this niche.
- things_to_avoid: hype, lay-explainer framing, defining basic specialist
  terms, reading any abstract verbatim, overclaiming from small studies,
  metaphor-led opens, personal anecdotes, chatty asides about "the patient
  in the room."

Do not invent additional articles. Do not add citation counts. Return only
the JSON object — no preamble, no closing remarks.
"""


_DIGEST_PERFORMANCE_OVERLAY_TEMPLATE = """\
================================================================
DIGEST EPISODE OVERLAY — this overrides any conflicting rule above
================================================================
This is a peer-level journal-club rounds episode, not a curiosity radio
show. Two rules from the general "Asynchronous" voice are explicitly
overridden:

1. "Move most source detail to show notes; spoken source mentions need
   story value." — DOES NOT APPLY HERE. The citation IS the story value.
   Listeners are commuting clinicians who cannot click through in real
   time. They need to hear the journal, year, first author, design, and
   n out loud so they can note the paper for later.
2. "Juno opens with an unexpected image or anecdote." — DOES NOT APPLY.
   No metaphor opens, no personal anecdotes, no "I keep thinking about
   this image." Cold open names what this week's lead paper changes.

Tone & register:
- Consultant on morning rounds presenting papers to peers. Dry, concrete,
  measured. Disagreement is welcome but must sit on data, not vibes. No
  chatty asides like "not a satisfying answer for the patient in the
  room." Open in form.

Structure (use these literal anchors):
- COLD OPEN (one or two beats): name what this week's lead paper changes
  in plain clinical terms. No metaphor.
- HEADLINE SEGMENT — approximately {headline_share_pct}% of runtime.
  First spoken mention of the headline paper MUST be this line, verbatim
  or very close to it:
      "{headline_intro}"
  Then follow the headline arc: clinical question → design choice that
  earns the evidence grade → effect in numbers → key caveat → what
  changes in practice (be honest if the answer is "nothing yet").
- PIVOT into rounds. Speak this sentence (or a very close variant):
      "{pivot_line}"
- ROUNDS SEGMENT — approximately {rounds_share_each_pct}% of runtime per
  paper. Each round opens with its bibliographic intro verbatim or near-
  verbatim. Intros in rank order:
{rounds_intros_block}
  Each round then follows: finding in one sentence → one caveat the
  listener must hear → clinical hook (what to do or watch for). Keep it
  fast. Do NOT let any round expand into headline-length back-and-forth.
- CLOSE (one or two beats): what to watch, what is still unsettled. Sign
  off with a short reference to show notes for DOIs.

Citation rules:
- Every paper's first spoken mention uses its formal citation line.
  Later references can be shorter ("the Wright cohort," "the Danish
  study"). The goal: a listener driving to work can note which paper
  to look up.
- The headline and each round must be distinctly identifiable by ear.
  Equal-weight treatment of all five papers is a failure mode.

Strip on contact:
- Metaphor opens, image-led cold opens, "I keep thinking about..."
- Casual asides about the patient experience that aren't operationally
  specific.
- Any spoken sentence that could appear unchanged on a wellness-influencer
  podcast.
================================================================
"""


def _digest_performance_overlay(research_package: dict) -> str:
    """Build the digest-specific overlay text appended to downstream prompts."""
    plan = research_package.get("structural_plan") or {}
    try:
        headline_share = float(plan.get("headline_share") or 0.55)
    except (TypeError, ValueError):
        headline_share = 0.55
    try:
        rounds_each = float(plan.get("rounds_share_each") or 0.10)
    except (TypeError, ValueError):
        rounds_each = 0.10
    pivot = str(plan.get("pivot_line") or "Rounds — other things this week.").strip()
    headline_intro = str(research_package.get("headline_intro") or "").strip()
    rounds_intros = research_package.get("rounds_intros") or []
    if not isinstance(rounds_intros, list):
        rounds_intros = []
    intro_lines = [str(line).strip() for line in rounds_intros if str(line).strip()]
    rounds_block = (
        "\n".join(f"      {i+1}. {line}" for i, line in enumerate(intro_lines))
        or "      (no rounds intros supplied — open each with formal citation)"
    )
    headline_display = (
        headline_intro
        or "(headline intro missing — open with formal citation: journal, year, first author, design, n, title)"
    )
    return _DIGEST_PERFORMANCE_OVERLAY_TEMPLATE.format(
        headline_share_pct=int(round(headline_share * 100)),
        rounds_share_each_pct=int(round(rounds_each * 100)),
        headline_intro=headline_display,
        pivot_line=pivot,
        rounds_intros_block=rounds_block,
    )


def _digest_research_and_script(
    topic: str,
    cfg: dict,
    client: anthropic.Anthropic | None,
    repo_root: Path,
    run_id: str = "",
) -> dict:
    """Digest entry point: ranked-article list -> research_package -> shared pipeline.

    Uses the cloud research model with NO tools (copyright firewall — abstracts
    never leave digest_ranker; only paraphrased findings + metadata propagate).
    Delegates to _script_from_research_package with web_factcheck disabled so
    the supplied paraphrases stay the source of truth.
    """
    articles = cfg.get("digest_articles") or {}
    headline = articles.get("headline") or {}
    rounds = list(articles.get("rounds") or [])
    if not headline:
        raise ValueError(
            "Digest run requires cfg['digest_articles'] with a headline; got nothing."
        )

    audience = str(cfg.get("audience") or "A specialist physician in the show's field.")
    show_id = str(cfg.get("show_id") or "")
    window_meta = articles.get("window") or {}

    def _card(article: dict) -> dict:
        return {
            "rank": article.get("rank"),
            "role": article.get("role"),
            "title": article.get("title", ""),
            "journal": article.get("journal", ""),
            "year": article.get("year"),
            "first_author": article.get("first_author") or None,
            "doi": article.get("doi"),
            "url": article.get("url", ""),
            "quartile": article.get("quartile"),
            "evidence": article.get("evidence"),
            "importance": article.get("importance"),
            "is_preprint": bool(article.get("is_preprint")),
            "finding": article.get("finding", ""),
            "why": article.get("why", ""),
            "domain": article.get("domain"),
        }

    article_brief = {
        "show_id": show_id,
        "display_name": articles.get("display_name") or topic,
        "audience": audience,
        "window": window_meta,
        "headline": _card(headline),
        "rounds": [_card(r) for r in rounds],
    }

    logger.info(
        f"[1/5] Building digest research package "
        f"(headline + {len(rounds)} rounds, no web tools)..."
    )
    package_text = _anthropic_text(
        client,
        model=_model_for(cfg, "research_model", _RESEARCH_MODEL),
        max_tokens=8192,
        system=_DIGEST_RESEARCH_SYSTEM,
        content=(
            f"Show: {articles.get('display_name', topic)}\n"
            f"Audience: {audience}\n"
            f"Window covered: {window_meta.get('from','?')} to {window_meta.get('to','?')}\n\n"
            "Ranked article list (paraphrased findings — work strictly from these):\n"
            f"{json.dumps(article_brief, indent=2)[:24000]}"
        ),
        temperature=0.3,
        cfg=cfg,
    )

    research_package = _extract_json_object(package_text) or {}
    # Hard floor so downstream passes never trip on missing keys.
    research_package.setdefault("topic", topic)
    if not research_package.get("readable_brief"):
        research_package["readable_brief"] = package_text
    research_package.setdefault("source_cards", [])
    research_package.setdefault("key_claims", [])
    research_package.setdefault("story_hooks", [])
    research_package.setdefault("counterintuitive_findings", [])
    research_package.setdefault("open_questions", [])
    research_package.setdefault(
        "things_to_avoid",
        [
            "Reading abstracts verbatim",
            "Lay-explainer framing or basic-term definitions",
            "Overclaiming from small or preprint studies",
            "Metaphor-led opens, personal anecdotes, chatty patient-room asides",
        ],
    )
    research_package.setdefault("headline_intro", "")
    research_package.setdefault("rounds_intros", [])
    research_package.setdefault("structural_plan", {})
    research_package["digest_input"] = article_brief

    return _script_from_research_package(
        topic, cfg, client, repo_root, run_id, research_package,
        web_factcheck=False,
    )


def research_and_script(
    topic: str,
    cfg: dict,
    client: anthropic.Anthropic | None,
    repo_root: Path = Path("."),
    run_id: str = "",
) -> dict:
    if cfg.get("digest_articles"):
        return _digest_research_and_script(topic, cfg, client, repo_root, run_id=run_id)
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
    host_a = cfg.get("host_a_name", "Juno").upper()
    host_b = cfg.get("host_b_name", "Caspar").upper()
    labels = {host_a, host_b, "JUNO", "CASPAR"}
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

    Handles both tagged format  JUNO [warm, curious]: text
    and untagged format         JUNO: text  (emotion_tag will be empty string).
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
    host_a = cfg.get("host_a_name", "Juno").upper()
    host_b = cfg.get("host_b_name", "Caspar").upper()
    if label in {host_a, "JUNO"}:
        return cfg.get("host_a_voice", "cedar")
    if label in {host_b, "CASPAR"}:
        return cfg.get("host_b_voice", "marin")
    guest = _guest_for_label(label, cfg)
    if guest and guest.get("voice"):
        return str(guest["voice"])
    return cfg.get("host_a_voice", "cedar")


def _guest_provider_override(label: str, cfg: dict) -> str | None:
    """A booked guest can carry its own TTS provider (e.g. Cartesia while the
    hosts run on ElevenLabs), assigned at plan-normalize time. Returns that
    provider when cross-provider guests are enabled, else None to fall back to
    the global ``tts_provider``."""
    if not cfg.get("guest_cross_provider", True):
        return None
    guest = _guest_for_label(label, cfg)
    if guest:
        provider = str(guest.get("tts_provider") or "").strip().lower()
        if provider in _VALID_TTS_PROVIDERS:
            return provider
    return None


def _speaker_role_for_label(label: str, cfg: dict) -> str:
    normalized = label.strip().upper()
    host_a = cfg.get("host_a_name", "Juno").upper()
    host_b = cfg.get("host_b_name", "Caspar").upper()
    if normalized in {host_a, "JUNO"}:
        return "JUNO"
    if normalized in {host_b, "CASPAR"}:
        return "CASPAR"
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
    provider = _guest_provider_override(label, cfg) or str(cfg.get("tts_provider") or "openai").lower()
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
    elif provider == "cartesia":
        route.update(
            {
                "voice_id": _cartesia_voice_for_label(label, cfg, guest_index),
                "model": cfg.get("cartesia_model"),
                "version": cfg.get("cartesia_version"),
                "sample_rate": cfg.get("cartesia_sample_rate"),
                "bit_rate": cfg.get("cartesia_bit_rate"),
                "language": cfg.get("cartesia_language"),
                "speed": cfg.get("cartesia_speed"),
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
    elif provider == "cartesia":
        # Accept voice / reference_id / voice_id from explicit routes; normalize to voice_id.
        if route.get("voice") and not route.get("voice_id"):
            route["voice_id"] = route["voice"]
        if route.get("reference_id") and not route.get("voice_id"):
            route["voice_id"] = route["reference_id"]
        route.pop("voice", None)
        route.pop("reference_id", None)
        route.setdefault("voice_id", _cartesia_voice_for_label(label, cfg, guest_index))
        route.setdefault("model", cfg.get("cartesia_model"))
        route.setdefault("version", cfg.get("cartesia_version"))
        route.setdefault("sample_rate", cfg.get("cartesia_sample_rate"))
        route.setdefault("bit_rate", cfg.get("cartesia_bit_rate"))
        route.setdefault("language", cfg.get("cartesia_language"))
        route.setdefault("speed", cfg.get("cartesia_speed"))
    elif provider == "command":
        route.setdefault("voice", _voice_for_label(label, cfg))
        route.setdefault("command", cfg.get("tts_command"))
    return _clean_tts_route(route)


def _public_tts_route(route: dict, label: str | None = None) -> dict:
    """Build a sanitised copy of a TTS route dict safe to commit to a public repo.

    Any voice_id is replaced by a human-readable ``voice_label`` so that provider
    API identifiers are never written into the public companion JSON.
    ``label`` should be the speaker label (e.g. "JUNO"); falls back to "[configured]".
    """
    hidden = {"api_key", "headers", "command"}
    public = {
        key: value
        for key, value in route.items()
        if key not in hidden and not key.endswith("_env")
    }
    # Replace any voice_id with a human label — never expose provider IDs in committed files.
    if "voice_id" in public:
        public.pop("voice_id")
        public["voice_label"] = label if label else "[configured]"
    return public


def _tts_routes_summary_for_script(script: str, cfg: dict) -> dict:
    turns = _parse_dialogue_turns(script, cfg)
    if not turns:
        route = _tts_route_for_label("JUNO", cfg)
        return {"JUNO": _public_tts_route(route, label="JUNO")}
    guest_voice_indexes: dict[str, int] = {}
    summary: dict[str, dict] = {}
    for label, _tag, _text in turns:
        if _guest_for_label(label, cfg) and label not in guest_voice_indexes:
            guest_voice_indexes[label] = len(guest_voice_indexes)
        route = _tts_route_for_label(label, cfg, guest_voice_indexes.get(label, 0))
        summary.setdefault(label, _public_tts_route(route, label=label))
    return summary


def _elevenlabs_voice_for_label(label: str, cfg: dict, guest_index: int = 0) -> str:
    host_a = cfg.get("host_a_name", "Juno").upper()
    host_b = cfg.get("host_b_name", "Caspar").upper()
    if label in {host_a, "JUNO"}:
        return str(cfg.get("elevenlabs_voice_id_a", ""))
    if label in {host_b, "CASPAR"}:
        return str(cfg.get("elevenlabs_voice_id_b", ""))
    guest = _guest_for_label(label, cfg)
    if guest and guest.get("elevenlabs_voice_id"):
        return str(guest["elevenlabs_voice_id"])
    guest_voice_ids = _csv_list(cfg.get("elevenlabs_guest_voice_ids"))
    if guest_voice_ids:
        return guest_voice_ids[guest_index % len(guest_voice_ids)]
    return str(cfg.get("elevenlabs_voice_id_b") or cfg.get("elevenlabs_voice_id_a") or "")


def _cartesia_voice_for_label(label: str, cfg: dict, guest_index: int = 0) -> str:
    host_a = cfg.get("host_a_name", "Juno").upper()
    host_b = cfg.get("host_b_name", "Caspar").upper()
    if label in {host_a, "JUNO"}:
        return str(cfg.get("cartesia_voice_id_a", ""))
    if label in {host_b, "CASPAR"}:
        return str(cfg.get("cartesia_voice_id_b", ""))
    guest = _guest_for_label(label, cfg)
    if guest and guest.get("cartesia_voice_id"):
        return str(guest["cartesia_voice_id"])
    guest_voice_ids = _csv_list(cfg.get("cartesia_guest_voice_ids"))
    if guest_voice_ids:
        return guest_voice_ids[guest_index % len(guest_voice_ids)]
    return str(cfg.get("cartesia_voice_id_b") or cfg.get("cartesia_voice_id_a") or "")


def _emotion_default_for_label(label: str, cfg: dict) -> str:
    host_a = cfg.get("host_a_name", "Juno").upper()
    if label in {host_a, "JUNO"}:
        return "warm, curious"
    guest = _guest_for_label(label, cfg)
    if guest and guest.get("delivery_baseline"):
        return str(guest["delivery_baseline"])
    return "measured, thoughtful"


def _build_tts_instructions(
    emotion_tag: str,
    label: str,
    cfg: dict,
    prev_emotion_tag: str = "",
) -> str:
    tag = emotion_tag if emotion_tag else _emotion_default_for_label(label, cfg)
    # Thread the prior turn's emotion so prosody flows across the cut instead of
    # hard-resetting to neutral on every line. Only when the previous turn carried
    # a genuine (explicit) tag that differs from this line's — a default baseline
    # carries no real signal, and identical tags need no transition cue.
    transition = ""
    prev = prev_emotion_tag.strip()
    if prev and prev.lower() != tag.strip().lower():
        transition = (
            f" The previous line was delivered with: {prev}. Let this line emerge "
            "from that moment rather than resetting — carry the conversation's energy "
            "and shift into your own tone naturally."
        )
    guest = _guest_for_label(label, cfg)
    if guest:
        return (
            f"You are voicing {guest.get('display_name', label)}, a synthetic guest "
            f"expert in {guest.get('field', 'the topic')}. "
            f"Personality: {guest.get('personality', 'specific, conversational, careful')}. "
            f"Deliver this line with: {tag}.{transition} Speak naturally in the interview, "
            "with authority but without sounding like a lecture."
        )
    return (
        f"Deliver this line with: {tag}.{transition} "
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


def _edge_trim_silence(path: Path, cfg: dict) -> None:
    """Trim leading/trailing near-silence from one rendered turn, in place (B2).

    TTS engines pad each utterance with a variable amount of head/tail silence.
    Left in, that padding makes the real inter-turn gap unpredictable and defeats
    the variable spacing below — so we strip it down to a small preserved pad
    (``turn_edge_keep_ms``) that keeps onsets and breaths from being clipped.

    Best-effort: any ffmpeg failure (e.g. an option an older build rejects) leaves
    the original file untouched rather than sinking the turn.
    """
    if not cfg.get("turn_edge_trim", True):
        return
    thr = cfg.get("turn_edge_trim_threshold_db", -50)
    keep = max(0.0, float(cfg.get("turn_edge_keep_ms", 40)) / 1000.0)
    sr = int(cfg.get("audio_sample_rate", 44100))
    ch = int(cfg.get("audio_channels", 2))
    # Trim leading silence, reverse, trim what is now the (former trailing) edge,
    # reverse back. peak detection is conservative — it won't mistake quiet speech
    # for silence the way RMS can.
    one = (
        f"silenceremove=start_periods=1:start_threshold={thr}dB:"
        f"start_silence={keep:.3f}:detection=peak"
    )
    sf = f"{one},areverse,{one},areverse"
    tmp = path.with_name(path.stem + "_trim" + path.suffix)
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-i", str(path), "-af", sf,
        "-ar", str(sr), "-ac", str(ch),
        "-c:a", "libmp3lame", "-b:a", _audio_bitrate_value(cfg), str(tmp),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if r.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
            os.replace(tmp, path)
        else:
            if r.returncode != 0:
                logger.warning(
                    "Edge-trim failed for %s (ffmpeg rc=%d); leaving untrimmed",
                    path.name, r.returncode,
                )
            tmp.unlink(missing_ok=True)
    except (subprocess.SubprocessError, OSError) as exc:
        logger.warning("Edge-trim errored for %s (%s); leaving untrimmed", path.name, exc)
        tmp.unlink(missing_ok=True)


def _inter_turn_gap_ms(rendered_meta: list, k: int, cfg: dict) -> int:
    """Gap (ms) to place after rendered turn ``k`` (boundary k → k+1), by context.

    ``rendered_meta`` is an ordered ``[(label, text), ...]`` of the turns that
    actually rendered. Falls back to the flat base gap when variable gaps are off
    or no signal fires. Signals are checked tightest-first so an interruption
    always wins over a would-be landing beat.
    """
    base = int(cfg.get("turn_silence_ms", 180))
    if not cfg.get("turn_variable_gaps", True) or k + 1 >= len(rendered_meta):
        return base
    lbl_a, txt_a = rendered_meta[k]
    lbl_b, txt_b = rendered_meta[k + 1]
    a = (txt_a or "").strip()
    b = (txt_b or "").strip()
    head = b[:1]
    # 1. Latch / interruption: prior trails off on a dash, or the next line opens
    #    mid-thought (lowercase) — deliver near-overlapped.
    if a.endswith(("—", "--", "–")) or (head.isalpha() and head.islower()):
        return int(cfg.get("turn_gap_latch_ms", 70))
    # 2. Same-speaker continuation: one host keeps going — keep the thought flowing.
    if lbl_a == lbl_b:
        return int(cfg.get("turn_gap_same_speaker_ms", 120))
    # 3. Quick reaction / back-channel: a short next line that isn't a question.
    if len(b) <= int(cfg.get("turn_reaction_max_chars", 24)) and not b.endswith("?"):
        return int(cfg.get("turn_gap_reaction_ms", 110))
    # 4. Landing beat: a substantial point that ends a sentence — let it breathe.
    if len(a) >= int(cfg.get("turn_beat_min_chars", 320)) and a.endswith((".", "?", "!", "…")):
        return int(cfg.get("turn_gap_beat_ms", 300))
    return base


def _probe_dur(path: Path) -> float:
    """Best-effort segment duration in seconds (0.0 if unknown)."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        return float(r.stdout.strip())
    except (subprocess.SubprocessError, OSError, ValueError):
        return 0.0


def _is_backchannel_turn(rendered_meta: list, k: int, cfg: dict) -> bool:
    """True if rendered turn ``k`` is a short reaction the *other* host murmurs
    while the previous speaker is still carrying the idea — the B4 overlay
    candidate. Requires a different speaker than the prior turn, a tight length
    cap, and a non-question (a question expects a real beat/answer, not overlap).
    """
    if k <= 0 or k >= len(rendered_meta):
        return False
    lbl_prev, _ = rendered_meta[k - 1]
    lbl_cur, txt_cur = rendered_meta[k]
    if lbl_cur == lbl_prev:
        return False
    b = (txt_cur or "").strip()
    if not b or b.endswith("?"):
        return False
    return len(b) <= int(cfg.get("backchannel_max_chars", 20))


def _overlay_backchannel(
    base_path: Path, bc_path: Path, out_path: Path, cfg: dict
) -> Path | None:
    """Mix a short backchannel onto the *tail* of ``base_path`` instead of playing
    it sequentially: duck it ~`backchannel_duck_db`, delay it to start
    `backchannel_lead_ms` before the base ends, sum with the base, and limit the
    result so the brief overlap can't clip. Returns the mixed file, or None on any
    failure (caller falls back to sequential concat — overlay is never load-bearing).
    """
    base_dur = _probe_dur(base_path)
    bc_dur = _probe_dur(bc_path)
    if base_dur <= 0 or bc_dur <= 0:
        return None
    lead_ms = max(0, int(cfg.get("backchannel_lead_ms", 120)))
    duck_db = abs(float(cfg.get("backchannel_duck_db", 8)))
    delay_ms = max(0, int(round(base_dur * 1000)) - lead_ms)
    sample_rate = int(cfg.get("audio_sample_rate", 44100))
    channels = int(cfg.get("audio_channels", 2))
    delay_arg = "|".join([str(delay_ms)] * max(1, channels))
    # Duck + delay the backchannel, sum without amix's auto-normalization (which
    # would halve the main voice), then limit ~-1 dBFS as clip insurance — the final
    # master re-loudnorms the whole program afterward regardless.
    filtergraph = (
        f"[1:a]volume=-{duck_db:g}dB,adelay={delay_arg}[bc];"
        f"[0:a][bc]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0[m];"
        f"[m]alimiter=limit=0.89[out]"
    )
    out_path = out_path.with_suffix(".mp3")
    cmd = [
        "ffmpeg", "-y",
        "-i", str(base_path),
        "-i", str(bc_path),
        "-filter_complex", filtergraph,
        "-map", "[out]",
        "-ar", str(sample_rate),
        "-ac", str(channels),
        "-c:a", "libmp3lame",
        "-b:a", _audio_bitrate_value(cfg),
        str(out_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (subprocess.SubprocessError, OSError) as exc:
        logger.warning("Backchannel overlay failed (%s); using sequential turn", exc)
        return None
    if result.returncode != 0 or not out_path.exists():
        logger.warning(
            "Backchannel overlay ffmpeg error; using sequential turn: %s",
            result.stderr[:300],
        )
        return None
    return out_path


def _crossfade_concat(
    parts: list,
    output: Path,
    join_durations: list,
    *,
    sample_rate: int = 44100,
    channels: int = 2,
    bitrate: str = "192k",
    curve: str = "tri",
    timeout: int = 900,
) -> None:
    """Concatenate audio with an ``acrossfade`` at every join (A3).

    ``join_durations[i]`` is the desired crossfade (seconds) between
    ``parts[i]`` and ``parts[i+1]``; each is clamped to <45% of the shorter
    neighbor so the fade can never exceed (or swallow) a short segment such as
    the intro ident. ``acrossfade`` *overlaps* clips, so total duration shrinks
    by the sum of the realized crossfades — any caller that also inserts gaps
    (Phase B2) must account for this and not double-apply.

    Inputs are passed relative to their common parent with ffmpeg's cwd set
    there, and the filter graph goes through a temp script file, so the argv
    stays well under the Windows ~32k limit even for hundreds of segments.
    """
    existing = [Path(p) for p in parts if Path(p).exists()]
    if not existing:
        raise ValueError("No audio segments to concatenate")
    output.parent.mkdir(parents=True, exist_ok=True)
    if len(existing) == 1:
        shutil.copy2(existing[0], output)
        return

    durs = [_probe_dur(p) for p in existing]
    clamped: list[float] = []
    for i in range(len(existing) - 1):
        d = float(join_durations[i]) if i < len(join_durations) else float(join_durations[-1])
        neigh = min(durs[i], durs[i + 1]) if durs[i] > 0 and durs[i + 1] > 0 else 0.0
        if neigh > 0:
            d = min(d, 0.45 * neigh)
        clamped.append(max(0.001, d))

    abs_parts = [p.resolve() for p in existing]
    try:
        base = Path(os.path.commonpath([str(p.parent) for p in abs_parts]))
    except ValueError:
        base = abs_parts[0].parent
    rel = [os.path.relpath(p, base) for p in abs_parts]

    inputs: list[str] = []
    for r in rel:
        inputs += ["-i", r]
    fc_parts: list[str] = []
    label = "[0:a]"
    for i in range(1, len(existing)):
        outl = f"[a{i}]"
        fc_parts.append(
            f"{label}[{i}:a]acrossfade=d={clamped[i-1]:.4f}:c1={curve}:c2={curve}{outl}"
        )
        label = outl
    fc = ";".join(fc_parts)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as sf:
        sf.write(fc)
        script_path = Path(sf.name)
    try:
        cmd = [
            "ffmpeg", "-y", "-hide_banner", *inputs,
            "-filter_complex_script", str(script_path),
            "-map", label,
            "-ar", str(int(sample_rate)), "-ac", str(int(channels)),
            "-c:a", "libmp3lame", "-b:a", str(bitrate),
            str(output.resolve()),
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=str(base)
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg crossfade concat failed: {result.stderr[:500]}")
    finally:
        script_path.unlink(missing_ok=True)


def _ffmpeg_concat_configured(
    parts: list,
    output: Path,
    cfg: dict,
    *,
    join_durations: list | None = None,
    curve: str = "tri",
) -> None:
    """Concatenate configured-format segments, with micro-crossfades (A3).

    Defaults to a ``concat_crossfade_ms`` (10 ms) crossfade at every join to kill
    click/pop at seams; pass ``join_durations`` (per-join seconds) for the
    music<->speech bookends, which want a longer fade. Falls back to a hard
    concat if crossfading is disabled, there's nothing to fade, or the crossfade
    pass errors — assembly must never fail over a fade.
    """
    sample_rate = int(cfg.get("audio_sample_rate", 44100))
    channels = int(cfg.get("audio_channels", 2))
    bitrate = _audio_bitrate_value(cfg)
    existing = [Path(p) for p in parts if Path(p).exists()]

    xfade_ms = int(cfg.get("concat_crossfade_ms", 10))
    if join_durations is None and xfade_ms > 0:
        join_durations = [xfade_ms / 1000.0] * max(0, len(existing) - 1)

    if (
        join_durations is not None
        and len(existing) > 1
        and any(d > 0 for d in join_durations)
    ):
        try:
            _crossfade_concat(
                existing, output, join_durations,
                sample_rate=sample_rate, channels=channels,
                bitrate=bitrate, curve=curve,
            )
            return
        except (RuntimeError, ValueError, subprocess.SubprocessError, OSError) as exc:
            logger.warning("Crossfade concat failed (%s); falling back to hard concat", exc)

    _ffmpeg_concat(
        existing, output,
        bitrate=bitrate, sample_rate=sample_rate, channels=channels,
    )


def _normalize_turn_loudness(path: Path, cfg: dict, work_dir: Path) -> None:
    """Loudness-match one rendered turn in place so cross-provider voices align.

    ElevenLabs hosts and ElevenLabs/Cartesia guests can be mastered to different
    reference levels by their providers. The final program master sets overall
    loudness but cannot fix per-speaker balance, so each turn is leveled to the
    common program target before concat. Delegates to the shared two-pass helper
    (measure -> linear gain), which preserves natural dynamics, skips near-silent
    turns untouched, and never raises — a normalization hiccup must not abort the
    episode. (``work_dir`` is retained for signature stability; the helper writes
    its temp file beside the target.)
    """
    if not cfg.get("normalize_turn_loudness", True):
        return
    path = Path(path)
    if not path.exists():
        return
    audio_utils.two_pass_loudnorm(
        path, path,
        target_i=float(cfg.get("audio_loudness_i", -14.0)),
        target_tp=float(cfg.get("audio_true_peak", -1.0)),
        target_lra=float(cfg.get("audio_lra", 11.0)),
        sample_rate=int(cfg.get("audio_sample_rate", 44100)),
        channels=int(cfg.get("audio_channels", 2)),
        bitrate=_audio_bitrate_value(cfg),
        encode_timeout=180,
    )


def _master_chain_pre_filters(cfg: dict) -> list[str]:
    """Build the master EQ/de-ess chain that runs *before* loudnorm.

    Order: highpass -> lowpass -> deesser. The de-esser (A2) tames sibilance in
    the ~5-9 kHz band before the loudnorm gain stage so harsh "s"/"sh" energy
    isn't normalized up along with everything else.
    """
    sample_rate = int(cfg.get("audio_sample_rate", 44100))
    highpass = int(cfg.get("audio_highpass_hz", 60))
    lowpass = int(cfg.get("audio_lowpass_hz", 18000))
    pre: list[str] = []
    if highpass > 0:
        pre.append(f"highpass=f={highpass}")
    if lowpass > 0:
        pre.append(f"lowpass=f={lowpass}")
    if cfg.get("audio_deesser", True):
        pre.append(
            audio_utils.deesser_filter(
                float(cfg.get("audio_deesser_freq", 6500)),
                sample_rate,
                float(cfg.get("audio_deesser_intensity", 0.12)),
            )
        )
    return pre


def _master_audio(input_path: Path, output_path: Path, cfg: dict, work_dir: Path) -> dict:
    """Apply final podcast mastering and encode the publishable MP3.

    Chain: highpass -> lowpass -> deesser (A2) -> loudnorm. Loudnorm is two-pass
    + linear (A1) when ``audio_master_two_pass`` is set, falling back to a single
    blind pass if measurement fails or the option is disabled. The program target
    defaults to streaming-standard -14 LUFS / -1.0 dBTP.
    """
    if not cfg.get("use_audio_mastering", True):
        if input_path.resolve() != output_path.resolve():
            shutil.copy2(input_path, output_path)
        return {"enabled": False}

    if not input_path.exists():
        raise FileNotFoundError(f"Audio file not found for mastering: {input_path}")

    sample_rate = int(cfg.get("audio_sample_rate", 44100))
    channels = int(cfg.get("audio_channels", 2))
    target_i = float(cfg.get("audio_loudness_i", -14.0))
    target_tp = float(cfg.get("audio_true_peak", -1.0))
    target_lra = float(cfg.get("audio_lra", 11.0))
    bitrate = _audio_bitrate_value(cfg)
    pre_filters = _master_chain_pre_filters(cfg)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    want_two_pass = bool(cfg.get("audio_master_two_pass", True))
    mode = "single_pass"

    if want_two_pass:
        ln = audio_utils.two_pass_loudnorm(
            input_path, output_path,
            target_i=target_i, target_tp=target_tp, target_lra=target_lra,
            sample_rate=sample_rate, channels=channels, bitrate=bitrate,
            pre_filters=pre_filters,
        )
        if ln["ok"]:
            mode = ln["mode"]
        else:
            # Measurement skipped/failed: fall through to a single blind pass so
            # we still always emit a master (or raise on a genuine ffmpeg error).
            logger.debug("Master two-pass loudnorm not applied (%s); single-pass fallback", ln["mode"])
            want_two_pass = False

    if not want_two_pass:
        af = ",".join(
            pre_filters
            + [f"loudnorm=I={target_i}:TP={target_tp}:LRA={target_lra}:print_format=summary"]
        )
        master_path = output_path
        if input_path.resolve() == output_path.resolve():
            master_path = work_dir / f"{output_path.stem}_mastered{output_path.suffix}"
        cmd = [
            "ffmpeg", "-y", "-i", str(input_path), "-vn", "-af", af,
            "-ar", str(sample_rate), "-ac", str(channels),
            "-c:a", "libmp3lame", "-b:a", bitrate, str(master_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg audio mastering failed: {result.stderr[:800]}")
        if master_path != output_path:
            master_path.replace(output_path)
        mode = "single_pass"

    filters = pre_filters + [
        f"loudnorm=I={target_i}:TP={target_tp}:LRA={target_lra}"
    ]
    return {
        "enabled": True,
        "filters": filters,
        "loudnorm_mode": mode,
        "deesser": bool(cfg.get("audio_deesser", True)),
        "bitrate": bitrate,
        "sample_rate": sample_rate,
        "channels": channels,
        "loudness_i": target_i,
        "true_peak": target_tp,
        "lra": target_lra,
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

    # Durable copy of the final spoken script, next to the audio. The work-dir
    # script.txt is deleted by cleanup, so this sidecar is what survives for the
    # periodic editorial review (flow / AI-tell passes). Published alongside the
    # other sidecars so it syncs across machines.
    script_path = audio_path.with_suffix(".script.txt")
    script_path.write_text(episode.get("script", "") or "", encoding="utf-8")

    episode["audio_url"] = audio_url
    episode["chapters"] = chapters
    episode["chapters_url"] = chapters_url
    episode["chapters_path"] = str(chapters_path)
    episode["companion_url"] = companion_url
    episode["companion_path"] = str(companion_path)
    episode["script_sidecar_path"] = str(script_path)
    episode["follow_up_links"] = follow_up_links
    return [chapters_path, companion_path, script_path]


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
    footnotes: list | None = None,
) -> Path:
    """Generate routed TTS from a speaker-labelled dialogue script.

    If `footnotes` is a list of ResolvedFootnote records, each cue's audio is
    spliced into the per-turn sequence immediately after the planned turn,
    before the inter-turn silence.
    """
    turns = _parse_dialogue_turns(script, cfg)
    if not turns:
        logger.warning("No dialogue turns found - falling back to default TTS route")
        route = _tts_route_for_label("JUNO", cfg)
        return tts_engines.synthesize_tts(
            text=script,
            output_path=output_path,
            route=route,
            cfg=cfg,
            instructions=_build_tts_instructions("", "JUNO", cfg),
        )

    work_dir.mkdir(parents=True, exist_ok=True)

    # Pre-pass: assign guest voice indexes in turn order (order-sensitive).
    guest_voice_indexes: dict[str, int] = {}
    for _i, (label, _tag, text) in enumerate(turns):
        if not text.strip():
            continue
        if _guest_for_label(label, cfg) and label not in guest_voice_indexes:
            guest_voice_indexes[label] = len(guest_voice_indexes)

    # Build ordered work items with pre-resolved routes and turn paths.
    # `prev_emotion` carries the last *rendered* (non-empty) turn's tag forward so
    # _build_tts_instructions can thread prosody across the cut. Computed here, in
    # order, before the thread pool — the instructions are baked into each work item.
    work_items = []
    prev_emotion = ""
    for i, (label, emotion_tag, text) in enumerate(turns):
        if not text.strip():
            continue
        route = _tts_route_for_label(label, cfg, guest_voice_indexes.get(label, 0))
        instructions = _build_tts_instructions(
            emotion_tag, label, cfg, prev_emotion_tag=prev_emotion
        )
        turn_path = work_dir / f"turn_{i:04d}_{_speaker_file_stem(label)}.mp3"
        work_items.append((i, label, route, instructions, text, turn_path))
        prev_emotion = emotion_tag

    def _synthesize_one(item: tuple):
        idx, lbl, route, instructions, text, turn_path = item
        try:
            generated_path = tts_engines.synthesize_tts(
                text=text,
                output_path=turn_path,
                route=route,
                cfg=cfg,
                instructions=instructions,
            )
            if generated_path.exists():
                _normalize_turn_loudness(generated_path, cfg, work_dir)
                _edge_trim_silence(generated_path, cfg)
                return (idx, generated_path)
        except Exception as exc:
            logger.warning("TTS synthesis failed for turn %d (%s): %s", idx, lbl, exc)
        return (idx, None)

    # Synthesize all turns in parallel; cap workers to avoid provider rate-limit hits.
    # Set cfg["tts_max_workers"] to override (default 8).
    n_workers = min(int(cfg.get("tts_max_workers", 8)), len(work_items))
    logger.info("Synthesizing %d turns in parallel (max_workers=%d)", len(work_items), n_workers)
    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        raw_results = list(executor.map(_synthesize_one, work_items))

    # executor.map preserves input order; sort is a defensive safety net.
    raw_results.sort(key=lambda r: r[0])
    turn_files: list = [path for _, path in raw_results if path is not None]
    turn_indices: list[int] = [i for i, path in raw_results if path is not None]

    # Fail loud on widespread TTS failure. Per-turn exceptions are swallowed above
    # (so a single bad turn never sinks an episode), but if too many turns fail we
    # must abort rather than publish a near-silent episode — the usual culprit is a
    # provider auth/quota wall (e.g. ElevenLabs returns 401 once the monthly
    # character limit is hit), which fails every turn at once.
    total_turns = len(work_items)
    failed_turns = total_turns - len(turn_files)
    max_fail_ratio = float(cfg.get("tts_max_fail_ratio", 0.2))
    if total_turns and (failed_turns / total_turns) > max_fail_ratio:
        raise RuntimeError(
            f"TTS synthesis failed for {failed_turns}/{total_turns} turns "
            f"({failed_turns / total_turns:.0%} > {max_fail_ratio:.0%} allowed); "
            "aborting before publish. Check TTS provider credentials/quota "
            "(e.g. ElevenLabs character limit) — see the per-turn warnings above."
        )

    output_path = output_path.with_suffix(".mp3")

    # Rendered-turn metadata (label, text) aligned to turn_files order, for gap decisions.
    rendered_meta = [(turns[ti][0], turns[ti][2]) for ti in turn_indices]

    footnotes_by_after: dict[int, list] = {}
    for fn in (footnotes or []):
        footnotes_by_after.setdefault(int(fn.after_turn), []).append(fn)

    # Flat ordered sequence of (path, rendered_k). rendered_k indexes rendered_meta;
    # it is None for a spliced footnote, whose boundaries fall back to the base gap.
    flat: list[tuple[Path, int | None]] = []
    for k, (file_path, turn_idx) in enumerate(zip(turn_files, turn_indices)):
        flat.append((file_path, k))
        for fn in footnotes_by_after.get(turn_idx, []):
            if Path(fn.audio_path).exists():
                flat.append((Path(fn.audio_path), None))

    # Phase B4 (stretch, default off): fold a short backchannel turn onto the *tail*
    # of the prior (other-host) turn as a ducked overlay instead of a sequential
    # segment, so the agreement physically overlaps. Best-effort and non-load-bearing
    # — any overlay failure leaves that turn sequential. Only the immediately-prior
    # *real* turn (k not None) is a fold target, and never one already carrying an
    # overlay, so a resuming turn after the murmur can't be stacked onto the same base.
    # (Minor: the gap after an overlaid turn is classified vs the consumed backchannel,
    # not the resume — a sub-perceptual 110ms reaction gap, within B2's existing band.)
    overlay_tmps: list[Path] = []
    if cfg.get("use_overlaid_backchannels", False) and len(flat) > 1:
        folded: list[tuple[Path, int | None]] = []
        folded_overlaid: list[bool] = []
        for path, k in flat:
            if (
                k is not None
                and folded
                and folded[-1][1] is not None
                and not folded_overlaid[-1]
                and _is_backchannel_turn(rendered_meta, k, cfg)
            ):
                base_path, base_k = folded[-1]
                mixed = _overlay_backchannel(
                    base_path, path, work_dir / f"_bc_{base_k:04d}", cfg
                )
                if mixed is not None:
                    folded[-1] = (mixed, base_k)
                    folded_overlaid[-1] = True
                    overlay_tmps.append(mixed)
                    continue
            folded.append((path, k))
            folded_overlaid.append(False)
        flat = folded

    base_ms = int(cfg.get("turn_silence_ms", 180))
    # BUG D: a spliced footnote is framed by one deliberate, symmetric pad so it
    # reads as a production beat, not the incidental inter-turn gap. This is the
    # single arrangement ruler around the cue — the clip's own 0.4s fade shapes its
    # entry/exit and A3's 10ms crossfade only kills seam clicks (neither is spacing).
    footnote_pad_ms = max(0, int(cfg.get("sonic_footnote_pad_ms", 350)))
    silence_cache: dict[int, Path] = {}

    def _gap_segment(ms: int) -> Path | None:
        ms = max(0, int(ms))
        if ms <= 0:
            return None
        if ms not in silence_cache:
            silence_cache[ms] = _make_silence(work_dir / f"_gap_{ms}", ms, cfg)
        return silence_cache[ms]

    # Interleave variable-length gaps. A3's micro-crossfade still fires at every join
    # to kill seam clicks; the gap segment is the single spacing ruler (no double-apply).
    if base_ms > 0 and len(flat) > 1:
        assembled: list[Path] = []
        for idx, (path, k) in enumerate(flat):
            if idx:
                prev_k = flat[idx - 1][1]
                if prev_k is not None and k is not None:
                    gap_ms = _inter_turn_gap_ms(rendered_meta, prev_k, cfg)
                else:
                    # footnote-adjacent boundary (entry or exit) — deliberate frame
                    gap_ms = footnote_pad_ms
                seg = _gap_segment(gap_ms)
                if seg is not None:
                    assembled.append(seg)
            assembled.append(path)
    else:
        assembled = [path for path, _ in flat]

    _ffmpeg_concat_configured(assembled, output_path, cfg)

    # Delete the per-turn mp3s and cached gap segments; footnote files are left in the
    # work dir for archiving (they were never added to turn_files).
    for p in turn_files:
        p.unlink(missing_ok=True)
    for seg in silence_cache.values():
        seg.unlink(missing_ok=True)
    for t in overlay_tmps:
        t.unlink(missing_ok=True)

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
    footnotes: list | None = None,
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
    return _tts_two_host(script, output_path, cfg, work_dir / "turns", footnotes=footnotes)


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


def _itunes_category_xml(category_raw: str) -> str:
    """Return the correct <itunes:category> element for flat or nested categories.

    Apple Podcasts expects nested subcategories as a child element, e.g.:
        <itunes:category text="Science">
          <itunes:category text="Medicine"/>
        </itunes:category>
    Pass "Science" for a flat tag, "Science:Medicine" for a nested one.
    """
    parts = category_raw.split(":", 1)
    top = _xml_escape(parts[0].strip())
    if len(parts) == 2 and parts[1].strip():
        sub = _xml_escape(parts[1].strip())
        return (
            f'<itunes:category text="{top}">\n'
            f'      <itunes:category text="{sub}"/>\n'
            f'    </itunes:category>'
        )
    return f'<itunes:category text="{top}"/>'


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
    {podcast_category_xml}
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
    *,
    feed_meta: dict | None = None,
) -> Path:
    """Append a new <item> to the show's RSS feed; create the feed if absent.

    When ``feed_meta`` is None, writes to ``feed.xml`` with channel metadata
    drawn from ``cfg`` — the original open-topic show behavior. When
    ``feed_meta`` is provided (digest runs), it must supply ``feed_filename``
    plus per-show channel overrides (title/description/author/category/image)
    so each digest publishes into its own feed at e.g. ``feed-mfm.xml``.

    Returns the absolute path of the feed file that was written.
    """
    feed_meta = feed_meta or {}
    feed_filename = feed_meta.get("feed_filename") or "feed.xml"
    base_url  = f"https://{cfg['github_user']}.github.io/{cfg['github_repo']}"
    feed_url  = f"{base_url}/{feed_filename}"
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
        "<br><br><em>Juno, Caspar, and any guest voices are AI-generated. "
        "Episode text and audio are generated with human-directed software.</em>"
    )

    # Script preview — escape any XML-sensitive chars outside CDATA wrap.
    # Defensive re-strip first: if any upstream pass leaks prose preamble
    # (e.g. a fact-check call that returns "Here's the corrected script…"
    # before the dialogue), _strip_to_dialogue snaps back to the first
    # SPEAKER: line. If no speaker line exists at all, fall back to the
    # episode topic so we never publish raw model preamble.
    script_for_preview = _strip_to_dialogue(episode.get("script", ""))
    if not re.search(
        r"^([A-Z][A-Z]{0,40})(?:\s*\[[^\]]*\])?\s*:",
        script_for_preview,
        re.MULTILINE,
    ):
        logger.warning(
            "update_rss: stripped script has no SPEAKER: line; "
            "falling back to topic for description preview."
        )
        script_for_preview = episode.get("topic", "")
    preview = _xml_escape(
        re.sub(
            r"^([A-Z][A-Z ]{1,40})(?:\s*\[[^\]]*\])?\s*:\s*",
            "",
            script_for_preview[:500],
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

    feed_path = repo_root / feed_filename
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
        # Per-show channel metadata: feed_meta overrides win, otherwise the
        # config defaults are used (open-topic show keeps its existing values).
        content = _RSS_TEMPLATE.format(
            podcast_title       = _xml_escape(feed_meta.get("podcast_title")       or cfg["podcast_title"]),
            base_url            = base_url,
            podcast_description = _xml_escape(feed_meta.get("podcast_description") or cfg["podcast_description"]),
            podcast_language    = feed_meta.get("podcast_language")                or cfg["podcast_language"],
            podcast_author      = _xml_escape(feed_meta.get("podcast_author")      or cfg["podcast_author"]),
            podcast_category_xml = _itunes_category_xml(
                feed_meta.get("podcast_category") or cfg["podcast_category"]
            ),
            podcast_email       = _xml_escape(feed_meta.get("podcast_email")       or cfg["podcast_email"]),
            podcast_image_url   = feed_meta.get("podcast_image")                   or cfg.get("podcast_image", ""),
            feed_url            = feed_url,
            items               = new_item,
        )

    feed_path.write_text(content, encoding="utf-8")
    logger.info(f"RSS feed updated → {feed_path}")
    return feed_path


def git_publish(
    audio_path: Path,
    repo_root: Path,
    topic: str,
    extra_paths: list[Path] | None = None,
    title: str | None = None,
    *,
    feed_filename: str = "feed.xml",
) -> None:
    """Commit + push the new audio file, the show's RSS feed, and any extras.

    ``feed_filename`` selects which feed XML to stage (e.g. ``feed-mfm.xml``
    for digest runs). Defaults to the open-topic show's ``feed.xml``.
    """
    headline = (title or topic or "").strip()
    safe_topic = re.sub(r"[\r\n]+", " ", headline)
    safe_topic = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", safe_topic)  # strip control chars
    safe_topic = re.sub(r"\s+", " ", safe_topic).strip()[:120] or "(untitled)"
    add_paths = [str(audio_path), feed_filename] + [
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
        route = _tts_route_for_label("JUNO", cfg)
        return tts_engines.synthesize_tts(
            text=text,
            output_path=output,
            route=route,
            cfg=cfg,
            instructions=_build_tts_instructions("", "JUNO", cfg),
        )

    return tts_fn


# ── Intro ident ───────────────────────────────────────────────────────────────

_INTRO_IDENT_TEXT = "Asynchronous. A podcast about ideas. With Juno and Caspar."


def _ensure_intro_ident(cfg: dict, repo_root: Path) -> "Path | None":
    """Generate and cache the show intro ident at assets/intro_ident.mp3.

    Uses Juno's configured TTS route.
    Only synthesised once; subsequent calls return the cached file immediately.
    """
    ident_path = repo_root / "assets" / "intro_ident.mp3"
    if ident_path.exists():
        return ident_path

    try:
        ident_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Generating show intro ident (first run only)…")
        route = _tts_route_for_label("JUNO", cfg)
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


# ── Audio round-trip QA ────────────────────────────────────────────────────────

def _audio_roundtrip_check(audio_path, cfg, client) -> dict:
    """Transcribe the rendered master mp3, run the naive listener on it, and log a
    report.  Report-only and best-effort: never raises; returns a result dict in
    all cases.
    """
    if not cfg.get("use_audio_roundtrip", True):
        return {"ran": False, "transcript_path": None, "breaks": [], "ratio": None}
    try:
        from scripts.transcribe_episode import main as _transcribe
    except Exception as exc:
        logger.warning("[audio-roundtrip] transcriber unavailable: %s", exc)
        return {"ran": False, "transcript_path": None, "breaks": [], "ratio": None}
    try:
        out_txt = str(Path(audio_path).with_suffix(".transcript.txt"))
        rc = _transcribe(["transcribe_episode", str(audio_path), out_txt])
        if rc != 0:
            logger.warning("[audio-roundtrip] transcription returned %s", rc)
            return {"ran": False, "transcript_path": None, "breaks": [], "ratio": None}
        transcript = Path(out_txt).read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        logger.warning("[audio-roundtrip] failed: %s", exc)
        return {"ran": False, "transcript_path": None, "breaks": [], "ratio": None}
    # The transcript is timestamped prose, not SPEAKER-tagged; wrap each line as a turn
    # so the naive ear can read it sequentially.
    try:
        pseudo = "\n".join(f"NARRATOR [neutral]: {ln.strip()}"
                           for ln in transcript.splitlines() if ln.strip())
        trace = _run_naive_listener(pseudo, cfg, client)
        breaks = trace["naive"]["breaks"]
        ratio = trace["narration_vs_banter"]["ratio"]
        high = [b for b in breaks if (b.get("severity") or "").lower() == "high"]
        logger.info("[audio-roundtrip] REPORT — %d breaks (%d HIGH), narration ratio %.2f. "
                    "Report-only; not gating publish.", len(breaks), len(high), ratio)
        for b in high:
            logger.info("[audio-roundtrip]   [HIGH] turn %s: %s", b.get("turn"), b.get("detail"))
        return {"ran": True, "transcript_path": out_txt, "breaks": breaks, "ratio": ratio}
    except Exception as exc:
        logger.warning("[audio-roundtrip] naive read failed: %s", exc)
        return {"ran": False, "transcript_path": out_txt, "breaks": [], "ratio": None}


# ── Main run ───────────────────────────────────────────────────────────────────

def _run_with_cfg(
    topic: str,
    cfg: dict,
    repo_root: Path,
    *,
    feed_meta: dict | None = None,
    digest_articles: dict | None = None,
) -> dict:
    """Drive the audio pipeline with a fully-built cfg.

    Shared body for `run()` (open-topic episodes) and `run_digest()` (digest
    shows). `digest_articles`, when present, is stashed on cfg so the
    research_and_script branch picks the digest path. `feed_meta` is a Phase 3
    hook (per-show feed metadata); ignored for now — all episodes still publish
    to the default feed.xml.
    """
    if digest_articles is not None:
        cfg["digest_articles"] = digest_articles
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
            feed_filename = (feed_meta or {}).get("feed_filename") or "feed.xml"
            manifest.data.setdefault("paths", {}).update(
                {
                    "repo_root": str(repo_root),
                    "work_dir": str(work_dir),
                    "final_audio": str(final_mp3),
                    "rss": str(repo_root / feed_filename),
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

            resolved_footnotes: list = []
            footnote_plan = episode.get("sonic_footnote_plan") or {}
            planned_cues = footnote_plan.get("cues") or []
            if (
                cfg.get("use_sonic_footnotes", True)
                and HAS_FOOTNOTE_MIXER
                and prepare_footnotes is not None
                and planned_cues
            ):
                if use_clips:
                    # Phase 1: clip + footnote co-mixing not yet supported; clips
                    # owns the splice path. Footnotes are deferred for this run.
                    manifest.add_warning(
                        "Sonic footnotes skipped this run: not yet supported alongside use_clips=true.",
                        stage=current_stage,
                    )
                else:
                    try:
                        sonic_catalog, _ = load_sonic_footnotes_catalog(repo_root, cfg)
                        resolved_footnotes = prepare_footnotes(
                            script=episode["script"],
                            plan=footnote_plan,
                            catalog=sonic_catalog,
                            cfg=cfg,
                            work_dir=work_dir / "footnotes",
                            client=client,
                        )
                    except Exception as exc:
                        logger.warning(
                            f"Sonic footnote resolution failed ({exc}); shipping without cues"
                        )
                        manifest.add_warning(
                            f"Sonic footnote resolution failed: {exc}",
                            stage=current_stage,
                        )
                        resolved_footnotes = []

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
                        clip_loudnorm_i=float(cfg.get("audio_loudness_i", -14.0)),
                    )
                except Exception as exc:
                    logger.warning(
                        f"Clip pipeline error ({exc}) - falling back to dialogue-only"
                    )
                    manifest.add_warning(
                        f"Clip pipeline failed; generated dialogue-only audio: {exc}",
                        stage=current_stage,
                    )
                    audio_path = generate_audio(
                        episode["script"], raw_audio, cfg, work_dir,
                        footnotes=resolved_footnotes,
                    )
                    attributions = []
            else:
                audio_path = generate_audio(
                    episode["script"], raw_audio, cfg, work_dir,
                    footnotes=resolved_footnotes,
                )

            if attributions:
                episode["clip_attributions"] = attributions
                manifest.set_clips(attributions)

            if resolved_footnotes:
                inserted_attribs = [fn.attribution for fn in resolved_footnotes]
                inserted_records = [
                    {
                        "catalog_id": fn.catalog_id,
                        "after_turn": fn.after_turn,
                        "duration_sec": round(fn.duration_sec, 2),
                        "source_url": fn.source_url,
                        "attribution": fn.attribution,
                    }
                    for fn in resolved_footnotes
                ]
                episode["sonic_footnote_attributions"] = inserted_attribs
                episode["sonic_footnote_inserted"] = inserted_records
                manifest.data["sonic_footnote_attributions"] = inserted_attribs
                manifest.data["sonic_footnote_inserted"] = inserted_records
                manifest.save()

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
                    # Longer, equal-power crossfades for the music<->speech
                    # bookends (A3); each join clamps to the shorter segment.
                    music_xf = float(cfg.get("music_crossfade_sec", 2.5))
                    _ffmpeg_concat_configured(
                        segments, final_mp3, cfg,
                        join_durations=[music_xf] * (len(segments) - 1),
                        curve="qsin",
                    )
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

            if cfg.get("use_audio_roundtrip", True):
                _audio_roundtrip_check(final_mp3, cfg, client)

            current_stage = "rss"
            manifest.set_stage(current_stage)
            logger.info("[5/5] Updating RSS feed...")
            feed_path = update_rss(
                episode, final_mp3, cfg, repo_root, feed_meta=feed_meta
            )
            base_url = f"https://{cfg['github_user']}.github.io/{cfg['github_repo']}"
            manifest.set_publish(
                rss_updated=True,
                rss_path=str(feed_path),
                feed_url=f"{base_url}/{feed_path.name}",
                audio_url=f"{base_url}/{cfg['output_dir']}/{final_mp3.name}",
                chapters_url=episode.get("chapters_url"),
                companion_url=episode.get("companion_url"),
            )

            # If feed_meta names a cover image that lives in the repo, include
            # it in the git commit so per-show feeds always reference an asset
            # that's actually been pushed.
            publish_extras = list(companion_paths)
            cover_local = (feed_meta or {}).get("cover_local_path")
            if cover_local:
                cover_path = Path(cover_local)
                if not cover_path.is_absolute():
                    cover_path = repo_root / cover_path
                if cover_path.exists():
                    publish_extras.append(cover_path)

            if not skip_git:
                current_stage = "git"
                manifest.set_stage(current_stage)
                git_publish(
                    final_mp3,
                    repo_root,
                    topic,
                    extra_paths=publish_extras,
                    title=episode.get("title"),
                    feed_filename=feed_path.name,
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
        if manifest is not None:
            try:
                manifest.persist_durable(repo_root / cfg["output_dir"])
            except Exception:
                logger.warning(
                    "Could not persist durable manifest copy", exc_info=True
                )
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)

    if episode is None:
        raise RuntimeError("Episode generation ended before an episode was produced")

    logger.info(
        f"\nDone!  Episode: {topic!r}  "
        f"({episode['word_count']} words, audio: {final_mp3.name})"
    )
    return episode


def run(
    topic: str,
    repo_root: Path = Path("."),
    episode_type: str | None = None,
    guest_host_mode: str | None = None,
) -> dict:
    """Thin wrapper: load cfg, apply CLI overrides, then drive `_run_with_cfg`."""
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
    return _run_with_cfg(topic, cfg, repo_root)


def _feed_meta_from_show(show: dict, cfg: dict) -> dict:
    """Build the `feed_meta` payload for `update_rss` / `git_publish` from a show.

    Channel-level overrides fall back to global cfg keys where unset so each
    digest feed can be partially customized (e.g. just title + cover) without
    re-stating everything. ``cover_local_path`` (derived from cover_image URL)
    lets `_run_with_cfg` stage the JPG into the publish commit.
    """
    cover_url = str(show.get("cover_image") or "").strip()
    cover_local = ""
    if cover_url:
        # Convention: cover_image URLs point at .../assets/cover-<slug>.jpg.
        # Stage the matching repo-local file so the very first publish doesn't
        # ship a feed pointing at a 404'd image.
        cover_local = f"assets/{cover_url.rsplit('/', 1)[-1]}"
    # Pass the full "Science:Medicine" string; _itunes_category_xml renders the
    # correct nested <itunes:category> element when update_rss builds a new feed.
    category_raw = str(show.get("category") or cfg["podcast_category"])
    return {
        "feed_filename":       str(show.get("feed_filename") or "feed.xml"),
        "podcast_title":       str(show.get("display_name") or cfg["podcast_title"]),
        "podcast_description": str(show.get("description")  or cfg["podcast_description"]),
        "podcast_author":      str(show.get("author")       or cfg["podcast_author"]),
        "podcast_category":    category_raw,
        "podcast_image":       cover_url or cfg.get("podcast_image", ""),
        "podcast_email":       str(show.get("email") or cfg["podcast_email"]),
        "podcast_language":    str(show.get("language") or cfg["podcast_language"]),
        "cover_local_path":    cover_local,
    }


def run_digest(show_id: str, repo_root: Path = Path(".")) -> dict:
    """Rank a digest show's recent papers and generate one episode end-to-end.

    Publishes into the show's own feed (feed-mfm.xml etc.) and records the
    headline + rounds DOIs in the show's ledger so they're skipped next run.
    """
    import digest_ranker
    from digest_shows import get_show
    from digest_ledger import load_ledger, record_episode

    repo_root = repo_root.resolve()
    cfg = load_config(repo_root)
    show = get_show(repo_root, show_id)

    cfg["episode_type"] = show["episode_type"]
    cfg["target_minutes"] = int(show["target_minutes"])
    cfg["show_id"] = show_id
    cfg["audience"] = show.get("audience", "")

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is required to generate a digest episode "
            "(both for ranking and for the script-build call)."
        )
    client = anthropic.Anthropic(api_key=anthropic_key)

    logger.info(f"Ranking {show['display_name']} ({show_id})...")
    ranked = digest_ranker.rank_show(
        show,
        load_ledger(repo_root, show_id),
        client,
        cfg=cfg,
        repo_root=repo_root,
    )
    if not ranked.get("headline"):
        raise RuntimeError(
            f"Digest {show_id!r}: no candidates found this run "
            f"(check journals / window / ledger). Aborting."
        )

    window_to = (ranked.get("window") or {}).get("to") or ""
    topic = (
        f"{show['display_name']} - week of {window_to}"
        if window_to else show["display_name"]
    )
    feed_meta = _feed_meta_from_show(show, cfg)
    episode = _run_with_cfg(
        topic, cfg, repo_root,
        feed_meta=feed_meta,
        digest_articles=ranked,
    )

    # Ledger write happens AFTER the pipeline returns successfully — never
    # mark a paper covered if the build raised mid-way.
    try:
        episode_url = (episode or {}).get("audio_url") or ""
        record_episode(
            repo_root,
            show_id,
            headline=ranked.get("headline"),
            rounds=ranked.get("rounds") or [],
            episode_url=episode_url,
            window=ranked.get("window") or {},
        )
        logger.info(
            f"Ledger updated for {show_id}: 1 headline + "
            f"{len(ranked.get('rounds') or [])} rounds papers."
        )
    except Exception as exc:  # noqa: BLE001 — never block on bookkeeping
        logger.warning(f"Ledger write failed for {show_id}: {exc}")

    return episode


# ---------------------------------------------------------------------------
# Phase 4 — weekday gating + multi-show scheduler
# ---------------------------------------------------------------------------

_WEEKDAY_MAP = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

# Each digest show fires at most once per this many days. Guards against the
# catch-up window (rule 4 below) re-firing a backlog when a show's ledger goes
# stale after a missed/failed stretch (e.g. an ElevenLabs quota outage). 6 (not
# 7) so a show that caught up a day late can still return to its scheduled
# weekday the following week without locking onto the catch-up day.
_DIGEST_MIN_DAYS_BETWEEN_RUNS = 6


def _show_is_due(
    show: dict,
    ledger: dict,
    *,
    force: bool = False,
    today=None,  # datetime | None — injected in tests
) -> tuple:
    """Return (is_due: bool, reason: str) for a digest show.

    Rules (checked in order):
    1. ``force=True`` → always due.
    2. ``last_run.aired_at`` is within the last ``_DIGEST_MIN_DAYS_BETWEEN_RUNS``
       days → weekly throttle, skip (also covers the "already ran today" case).
    3. Today is the show's scheduled weekday → due.
    4. Today is one day *after* the scheduled weekday (catch-up window) → due.
    5. Otherwise → not due.
    """
    from datetime import datetime as _dt, timezone as _tz

    if force:
        return True, "forced"

    now = today if today is not None else _dt.now(_tz.utc)
    today_date = now.date()
    sched_wd_name = str((show.get("schedule") or {}).get("weekday") or "mon").lower()[:3]
    scheduled_wd = _WEEKDAY_MAP.get(sched_wd_name, 0)
    today_wd = today_date.weekday()  # Monday=0

    # Weekly throttle: never fire more than once per ~week. Compared on dates
    # (not datetimes) so a same-weekday run a full week later isn't blocked by a
    # few hours' clock drift. Subsumes the old "already ran today" guard (a run
    # today or in the future yields days_since_last < the threshold).
    last_run = ledger.get("last_run") or {}
    last_aired = last_run.get("aired_at") or ""
    if last_aired:
        try:
            last_date = _dt.fromisoformat(last_aired.replace("Z", "+00:00")).date()
            days_since_last = (today_date - last_date).days
            if days_since_last < _DIGEST_MIN_DAYS_BETWEEN_RUNS:
                return False, (
                    f"ran {days_since_last}d ago "
                    f"(weekly throttle: min {_DIGEST_MIN_DAYS_BETWEEN_RUNS}d)"
                )
        except ValueError:
            pass

    days_since = (today_wd - scheduled_wd) % 7
    if days_since == 0:
        return True, "scheduled today"
    if days_since == 1:
        return True, "catch-up (missed yesterday)"
    days_until = (scheduled_wd - today_wd) % 7
    return False, f"not due until next {sched_wd_name} ({days_until} day(s) away)"


def run_all_due_digests(repo_root=None, *, force: bool = False) -> dict:
    """Run every digest show that is due today (or all shows when force=True).

    Weekday gating uses each show's ``schedule.weekday`` key against today's
    date (UTC), with a 1-day catch-up window for missed days.  Env vars
    (SKIP_GIT, etc.) are inherited by child ``run_digest`` calls.

    Returns ``{show_id: "ok" | "skipped: <reason>" | "error: <msg>"}`` for
    every show; continues to the next show on any individual failure.
    """
    from digest_shows import load_shows, DigestConfigError
    from digest_ledger import load_ledger

    if repo_root is None:
        repo_root = Path(".")
    repo_root = Path(repo_root).resolve()

    try:
        shows = load_shows(repo_root)
    except DigestConfigError as exc:
        raise RuntimeError(f"Could not load shows config: {exc}") from exc

    results = {}
    for show_id, show in sorted(shows.items()):
        ledger = load_ledger(repo_root, show_id)
        is_due, reason = _show_is_due(show, ledger, force=force)
        if not is_due:
            logger.info("Skipping digest %r: %s", show_id, reason)
            results[show_id] = f"skipped: {reason}"
            continue
        logger.info("Running digest %r: %s", show_id, reason)
        try:
            run_digest(show_id, repo_root=repo_root)
            results[show_id] = "ok"
        except Exception as exc:  # noqa: BLE001
            logger.error("Digest %r failed: %s", show_id, exc)
            results[show_id] = f"error: {exc}"

    return results


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
    parser.add_argument(
        "--digest",
        metavar="SHOW_ID",
        default=None,
        help="Generate one digest episode end-to-end for the given show (mfm, fetal, ai).",
    )
    parser.add_argument(
        "--digest-dry-run",
        metavar="SHOW_ID",
        default=None,
        help="Rank a digest show's recent articles and print the ranked table; generates no audio.",
    )
    parser.add_argument(
        "--digest-all",
        action="store_true",
        default=False,
        help=(
            "Run all digest shows that are due today (weekday gating + 1-day catch-up). "
            "Designed for daily Task Scheduler / cron use."
        ),
    )
    parser.add_argument(
        "--digest-force-all",
        action="store_true",
        default=False,
        help="Run all digest shows unconditionally, bypassing weekday gating.",
    )
    args = parser.parse_args()

    if args.digest_dry_run:
        # Phase 1: ranking-only preview. No audio, no writes.
        import digest_ranker
        from digest_shows import DigestConfigError, get_show
        from digest_ledger import load_ledger

        repo_root = Path(args.repo)
        try:
            show = get_show(repo_root, args.digest_dry_run)
        except DigestConfigError as exc:
            print(f"error: {exc}", file=sys.stderr)
            sys.exit(2)
        cfg = load_config(repo_root)
        akey = os.environ.get("ANTHROPIC_API_KEY")
        client = anthropic.Anthropic(api_key=akey) if akey else None
        if client is None:
            logger.warning("ANTHROPIC_API_KEY not set; ranking uses metadata signals only (no LLM importance).")
        result = digest_ranker.rank_show(
            show,
            load_ledger(repo_root, show["id"]),
            client,
            cfg=cfg,
            repo_root=repo_root,
            dry_run=True,
        )
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # journal titles carry non-cp1252 chars
        except Exception:
            pass
        print(digest_ranker.format_dry_run_table(result))
        sys.exit(0)

    if args.digest:
        # Phase 2: generate one real digest episode end-to-end.
        from digest_shows import DigestConfigError
        try:
            run_digest(args.digest, repo_root=Path(args.repo))
        except DigestConfigError as exc:
            print(f"error: {exc}", file=sys.stderr)
            sys.exit(2)
        sys.exit(0)

    if args.digest_all or args.digest_force_all:
        # Phase 4: run all shows that are due today (or all shows unconditionally).
        from digest_shows import DigestConfigError
        try:
            results = run_all_due_digests(
                Path(args.repo), force=args.digest_force_all
            )
        except (DigestConfigError, RuntimeError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            sys.exit(2)
        any_error = any(v.startswith("error:") for v in results.values())
        for sid, status in sorted(results.items()):
            print(f"  {sid:8} {status}")
        sys.exit(1 if any_error else 0)

    topic = args.topic or input("Enter podcast topic: ").strip()
    if not topic:
        sys.exit(1)
    _CLI_MAX_TOPIC_LEN = 500  # mirrors Telegram bot MAX_TOPIC_LEN
    if len(topic) > _CLI_MAX_TOPIC_LEN:
        print(
            f"error: topic too long ({len(topic)} chars, max {_CLI_MAX_TOPIC_LEN})",
            file=sys.stderr,
        )
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
