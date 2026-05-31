#!/usr/bin/env python3
"""Plan a multi-episode Asynchronous learning path."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import anthropic

import llm_engines
from episode_manifest import slugify_topic
from episode_types import EPISODE_TYPES, episode_type_help, normalize_episode_type
from personal_context import load_personal_context, personal_context_prompt
from secret_env import load_secret_env


load_secret_env(Path(__file__).parent)

_DEFAULTS = {
    "learning_path_dir": "learning_paths",
    "learning_path_default_episodes": 5,
    "learning_path_default_level": "beginner-to-intermediate",
    "learning_path_model": "claude-sonnet-4-6",
    "local_llm_provider": "ollama",
    "local_llm_base_url": "http://127.0.0.1:11434",
    "local_llm_api_key_env": "LOCAL_LLM_API_KEY",
    "local_llm_timeout_sec": 3600,
    "local_llm_num_ctx": 32768,
    "local_llm_keep_alive": "30m",
    "local_llm_think": False,
    "use_personal_context": True,
    "personal_context_path": "personal_context.json",
    "personal_context_max_topics": 24,
    "personal_context_similarity_threshold": 0.34,
    "personal_context_sync_manifests": True,
}

_LEARNING_PATH_SYSTEM = """\
You are the curriculum producer for "Asynchronous", a source-grounded two-host
audio learning show hosted by Juno and Caspar.

Create a 3-8 episode mini-course from the user's topic. The output must be JSON
only. No Markdown fence, no commentary.

Shape:
{
  "title": "...",
  "topic": "...",
  "level": "...",
  "audience": "...",
  "path_promise": "...",
  "prerequisites": ["..."],
  "core_concepts": ["..."],
  "glossary": [{"term": "...", "definition": "..."}],
  "episodes": [
    {
      "number": 1,
      "title": "...",
      "episode_type": "overview",
      "topic_prompt": "...",
      "learning_objectives": ["..."],
      "key_questions": ["..."],
      "practice_prompt": "...",
      "quiz_questions": ["..."],
      "success_criteria": ["..."]
    }
  ],
  "capstone_prompt": "...",
  "follow_up_paths": ["..."]
}

Episode type must be one of:
__EPISODE_TYPE_KEYS__

Design rules:
- The sequence should compound. Each episode should make the next one easier.
- Include at least one practical/application episode when the topic supports it.
- Include a debate, myth_bust, decision_brief, or case_study episode when useful.
- End with a review episode that reinforces retrieval, not a bland recap.
- Avoid overloading episode 1. It should orient, motivate, and build vocabulary.
- Use personal context to tune depth, prerequisites, examples, and repeated-topic handling.
- Keep topic_prompt specific enough that generate_podcast.py can use it directly.
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _extract_text(content_blocks: Any) -> str:
    return "\n".join(
        block.text for block in content_blocks if hasattr(block, "text")
    ).strip()


def _extract_json_object(text: str) -> dict[str, Any] | None:
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


def _coerce_int(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_bool(value: object, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off", ""}:
        return False
    return default


def _as_list(value: object) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [str(value)]


def load_config(repo_root: Path) -> dict[str, Any]:
    cfg = dict(_DEFAULTS)
    cfg_path = repo_root / "config.json"
    if cfg_path.exists():
        try:
            file_cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            for key in cfg:
                if key in file_cfg:
                    cfg[key] = file_cfg[key]
        except json.JSONDecodeError:
            pass

    for key in cfg:
        val = os.environ.get(key.upper())
        if val is not None:
            cfg[key] = val

    cfg["learning_path_default_episodes"] = _coerce_int(
        cfg.get("learning_path_default_episodes"),
        int(_DEFAULTS["learning_path_default_episodes"]),
    )
    cfg["personal_context_max_topics"] = _coerce_int(
        cfg.get("personal_context_max_topics"),
        int(_DEFAULTS["personal_context_max_topics"]),
    )
    cfg["local_llm_timeout_sec"] = _coerce_int(
        cfg.get("local_llm_timeout_sec"),
        int(_DEFAULTS["local_llm_timeout_sec"]),
    )
    cfg["local_llm_num_ctx"] = _coerce_int(
        cfg.get("local_llm_num_ctx"),
        int(_DEFAULTS["local_llm_num_ctx"]),
    )
    cfg["local_llm_think"] = _coerce_bool(
        cfg.get("local_llm_think"),
        bool(_DEFAULTS["local_llm_think"]),
    )
    cfg["personal_context_similarity_threshold"] = _coerce_float(
        cfg.get("personal_context_similarity_threshold"),
        float(_DEFAULTS["personal_context_similarity_threshold"]),
    )
    cfg["use_personal_context"] = _coerce_bool(
        cfg.get("use_personal_context"),
        bool(_DEFAULTS["use_personal_context"]),
    )
    cfg["personal_context_sync_manifests"] = _coerce_bool(
        cfg.get("personal_context_sync_manifests"),
        bool(_DEFAULTS["personal_context_sync_manifests"]),
    )
    return cfg


def _fallback_path(topic: str, count: int, level: str) -> dict[str, Any]:
    episode_types = ["overview", "deep_dive", "how_to", "debate", "review"]
    episodes = []
    for idx in range(count):
        ep_type = episode_types[idx] if idx < len(episode_types) else "case_study"
        episodes.append(
            {
                "number": idx + 1,
                "title": f"{topic}: Part {idx + 1}",
                "episode_type": ep_type,
                "topic_prompt": f"{topic} - learning path part {idx + 1}",
                "learning_objectives": [f"Understand part {idx + 1} of {topic}."],
                "key_questions": [f"What should a {level} learner notice here?"],
                "practice_prompt": "Write a brief teach-back in your own words.",
                "quiz_questions": ["What is the most important idea from this episode?"],
                "success_criteria": ["You can explain the episode's main idea simply."],
            }
        )
    return {
        "title": f"Learning Path: {topic}",
        "topic": topic,
        "level": level,
        "audience": level,
        "path_promise": f"A {count}-episode path for learning {topic}.",
        "prerequisites": [],
        "core_concepts": [],
        "glossary": [],
        "episodes": episodes,
        "capstone_prompt": f"Explain {topic} as a connected system.",
        "follow_up_paths": [],
    }


def _validate_path(data: dict[str, Any], topic: str, count: int, level: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        data = _fallback_path(topic, count, level)
    data.setdefault("title", f"Learning Path: {topic}")
    data["topic"] = str(data.get("topic") or topic)
    data["level"] = str(data.get("level") or level)
    data.setdefault("audience", level)
    data.setdefault("path_promise", f"A {count}-episode path for learning {topic}.")

    for key in ["prerequisites", "core_concepts", "follow_up_paths"]:
        if not isinstance(data.get(key), list):
            data[key] = []
    if not isinstance(data.get("glossary"), list):
        data["glossary"] = []

    episodes = data.get("episodes")
    if not isinstance(episodes, list) or not episodes:
        episodes = _fallback_path(topic, count, level)["episodes"]

    cleaned = []
    for idx, episode in enumerate(episodes[:count]):
        if not isinstance(episode, dict):
            episode = {}
        ep_type_raw = str(episode.get("episode_type") or "deep_dive")
        try:
            ep_type = normalize_episode_type(ep_type_raw)
        except ValueError:
            ep_type = "deep_dive"
        title = str(episode.get("title") or f"{topic}: Part {idx + 1}")
        topic_prompt = str(
            episode.get("topic_prompt")
            or f"{topic} - {title} for a {level} learner"
        )
        cleaned.append(
            {
                "number": idx + 1,
                "title": title,
                "episode_type": ep_type,
                "topic_prompt": topic_prompt,
                "learning_objectives": _as_list(episode.get("learning_objectives")),
                "key_questions": _as_list(episode.get("key_questions")),
                "practice_prompt": str(episode.get("practice_prompt") or ""),
                "quiz_questions": _as_list(episode.get("quiz_questions")),
                "success_criteria": _as_list(episode.get("success_criteria")),
            }
        )

    while len(cleaned) < count:
        fallback = _fallback_path(topic, count, level)["episodes"][len(cleaned)]
        cleaned.append(fallback)

    data["episodes"] = cleaned
    data.setdefault("capstone_prompt", f"Teach back the main map of {topic}.")
    return data


def render_markdown(path_data: dict[str, Any]) -> str:
    lines = [
        f"# {path_data['title']}",
        "",
        f"Topic: {path_data['topic']}",
        f"Level: {path_data['level']}",
        "",
        "## Promise",
        "",
        str(path_data.get("path_promise", "")),
        "",
        "## Prerequisites",
        "",
    ]
    prereqs = path_data.get("prerequisites") or ["None specified."]
    lines.extend(f"- {item}" for item in prereqs)
    lines.extend(["", "## Core Concepts", ""])
    concepts = path_data.get("core_concepts") or ["None specified."]
    lines.extend(f"- {item}" for item in concepts)
    lines.extend(["", "## Episodes", ""])
    for episode in path_data["episodes"]:
        lines.extend(
            [
                f"### {episode['number']}. {episode['title']}",
                "",
                f"- Type: `{episode['episode_type']}`",
                f"- Prompt: {episode['topic_prompt']}",
            ]
        )
        objectives = episode.get("learning_objectives") or []
        if objectives:
            lines.append("- Objectives: " + "; ".join(objectives))
        questions = episode.get("key_questions") or []
        if questions:
            lines.append("- Key questions: " + "; ".join(questions))
        if episode.get("practice_prompt"):
            lines.append(f"- Practice: {episode['practice_prompt']}")
        quiz = episode.get("quiz_questions") or []
        if quiz:
            lines.append("- Quiz: " + "; ".join(quiz))
        lines.append("")

    glossary = path_data.get("glossary") or []
    if glossary:
        lines.extend(["## Glossary", ""])
        for item in glossary:
            if isinstance(item, dict):
                lines.append(f"- **{item.get('term', '')}**: {item.get('definition', '')}")
        lines.append("")

    lines.extend(
        [
            "## Capstone",
            "",
            str(path_data.get("capstone_prompt", "")),
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def write_learning_path(
    repo_root: Path,
    path_data: dict[str, Any],
    output_dir: str,
) -> tuple[Path, Path]:
    path_id = path_data["path_id"]
    slug = slugify_topic(path_data["topic"])
    path_dir = repo_root / output_dir / f"{path_id}_{slug}"
    path_dir.mkdir(parents=True, exist_ok=True)
    json_path = path_dir / "learning_path.json"
    md_path = path_dir / "learning_path.md"
    path_data["json_path"] = str(json_path)
    path_data["markdown_path"] = str(md_path)

    payload = json.dumps(path_data, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path_dir,
        delete=False,
        prefix=".learning_path.",
        suffix=".tmp",
    ) as tmp:
        tmp.write(payload)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    tmp_path.replace(json_path)
    md_path.write_text(render_markdown(path_data), encoding="utf-8")

    latest = repo_root / output_dir / "latest_learning_path.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(payload + "\n", encoding="utf-8")
    return json_path, md_path


def plan_learning_path(
    topic: str,
    *,
    repo_root: Path = Path("."),
    count: int | None = None,
    level: str | None = None,
    client: anthropic.Anthropic | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    cfg = load_config(repo_root)
    count = count or int(cfg["learning_path_default_episodes"])
    count = max(3, min(8, int(count)))
    level = level or str(cfg["learning_path_default_level"])
    model = str(cfg["learning_path_model"])
    output_dir = str(cfg["learning_path_dir"])

    if client is None and not llm_engines.is_local_model(model):
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError(
                f"ANTHROPIC_API_KEY is required for cloud model {model!r}. "
                "Use local:, ollama:, or openai-compatible: for a local learning path model."
            )
        client = anthropic.Anthropic(api_key=api_key)

    personal_context_text = "Personal context mode is disabled."
    if cfg.get("use_personal_context", True):
        context, _context_path = load_personal_context(repo_root, cfg)
        personal_context_text = personal_context_prompt(context, topic, cfg)

    prompt = (
        f"Topic: {topic}\n"
        f"Episode count: {count}\n"
        f"Level: {level}\n\n"
        f"Personal context:\n{personal_context_text}\n\n"
        "Available episode types:\n"
        f"{episode_type_help()}\n\n"
        "Build the mini-course now."
    )
    system = _LEARNING_PATH_SYSTEM.replace(
        "__EPISODE_TYPE_KEYS__", ", ".join(sorted(EPISODE_TYPES))
    )
    if llm_engines.is_local_model(model):
        raw = llm_engines.generate_text(
            model=model,
            system=system,
            content=prompt,
            max_tokens=8192,
            cfg=cfg,
            temperature=0.35,
        )
    else:
        if client is None:
            raise RuntimeError("Anthropic client was not initialized.")
        response = client.messages.create(
            model=model,
            max_tokens=8192,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = _extract_text(response.content)
    path_data = _extract_json_object(raw) or _fallback_path(topic, count, level)
    path_data = _validate_path(path_data, topic, count, level)
    path_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    path_data.update(
        {
            "schema_version": 1,
            "path_id": path_id,
            "created_at": _utc_now(),
            "requested_episode_count": count,
            "model": model,
        }
    )
    json_path, md_path = write_learning_path(repo_root, path_data, output_dir)
    return path_data


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan an Asynchronous learning path.")
    parser.add_argument("topic", nargs="?", help="Learning path topic")
    parser.add_argument("--repo", default=".", help="Repo root directory")
    parser.add_argument("--episodes", "-n", type=int, default=None, help="Episode count")
    parser.add_argument("--level", default=None, help="Target learner level")
    args = parser.parse_args()

    topic = args.topic or input("Learning path topic: ").strip()
    if not topic:
        sys.exit(1)
    path_data = plan_learning_path(
        topic,
        repo_root=Path(args.repo),
        count=args.episodes,
        level=args.level,
    )
    print(json.dumps({
        "path_id": path_data["path_id"],
        "json_path": path_data["json_path"],
        "markdown_path": path_data["markdown_path"],
        "episodes": len(path_data["episodes"]),
    }))


if __name__ == "__main__":
    main()
