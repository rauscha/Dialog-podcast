#!/usr/bin/env python3
"""Episode type definitions shared by the generator and Telegram bot."""

from __future__ import annotations

import re

DEFAULT_EPISODE_TYPE = "deep_dive"

EPISODE_TYPES: dict[str, dict[str, str | list[str]]] = {
    "deep_dive": {
        "label": "Deep Dive",
        "tagline": "A layered narrative investigation with emotional and factual depth.",
        "best_for": "Big questions, science/history topics, and anything with a surprising mechanism.",
        "research_focus": "Find the strongest claims, the human stakes, and one counterintuitive turn.",
        "structure": "Cold open -> puzzle -> evidence trail -> complication -> synthesis -> reflective ending.",
        "host_dynamic": "Juno chases meaning; Caspar tests certainty; both revise by the end.",
        "avoid": "Avoid becoming a list of facts or a smooth summary with no tension.",
    },
    "overview": {
        "label": "Broad Overview",
        "tagline": "A clear map of a subject for a smart listener who is new to it.",
        "best_for": "Introductions, explainers, and topics with lots of unfamiliar vocabulary.",
        "research_focus": "Prioritize definitions, mental models, timelines, and why the topic matters.",
        "structure": "Hook -> plain-language map -> key concepts -> examples -> common confusions -> next steps.",
        "host_dynamic": "Juno asks the listener's intuitive questions; Caspar builds the scaffolding.",
        "avoid": "Avoid over-specialized rabbit holes before the listener has a map.",
    },
    "how_to": {
        "label": "Teaching How-To",
        "tagline": "A practical lesson that helps the listener actually do or build something.",
        "best_for": "Skills, workflows, creative tools, engineering tasks, and learning plans.",
        "research_focus": "Find steps, prerequisites, mistakes, decision points, and concrete examples.",
        "structure": "Outcome -> prerequisites -> steps -> worked example -> failure modes -> practice plan.",
        "host_dynamic": "Caspar sequences the method; Juno notices motivation, friction, and useful metaphors.",
        "avoid": "Avoid fake precision, hand-wavy steps, or pretending the listener can skip prerequisites.",
    },
    "landscape": {
        "label": "Scout The Landscape",
        "tagline": "A field report on the players, trends, tradeoffs, and open questions.",
        "best_for": "Markets, emerging tech, creative tools, policy spaces, and fast-moving domains.",
        "research_focus": "Map actors, incentives, timelines, controversies, adoption, and weak signals.",
        "structure": "What changed -> who matters -> competing approaches -> risks -> likely next moves.",
        "host_dynamic": "Juno spots cultural signals; Caspar separates evidence from hype.",
        "avoid": "Avoid prediction theater. Label speculation clearly.",
    },
    "case_study": {
        "label": "Case Study",
        "tagline": "One concrete story used as a lens for the larger idea.",
        "best_for": "Companies, discoveries, failures, artworks, incidents, and biographies.",
        "research_focus": "Build a timeline, identify decisions, constraints, consequences, and alternate paths.",
        "structure": "Scene -> background -> decision points -> consequences -> what it reveals.",
        "host_dynamic": "Juno stays close to the people; Caspar tracks causes and counterfactuals.",
        "avoid": "Avoid flattening messy people into heroes, villains, or morals.",
    },
    "story": {
        "label": "Story",
        "tagline": "A narrative-first episode shaped around scenes, characters, and turns.",
        "best_for": "Human stories, strange incidents, personal essays, historical moments, and topics with a strong arc.",
        "research_focus": "Find scenes, chronology, character motivations, stakes, sensory texture, and verified turning points.",
        "structure": "Cold scene -> character desire -> complication -> reversal -> consequence -> resonant close.",
        "host_dynamic": "Juno carries scene and feeling; Caspar tracks what the evidence supports and how interpretations change.",
        "avoid": "Avoid generic exposition or inventing details when the story is nonfiction.",
    },
    "myth_bust": {
        "label": "Myth Bust",
        "tagline": "A careful teardown of a popular belief without becoming smug.",
        "best_for": "Common misconceptions, viral claims, folk wisdom, and simplistic narratives.",
        "research_focus": "Find the origin of the myth, what is true inside it, and what evidence complicates it.",
        "structure": "The belief -> why it feels true -> evidence -> nuance -> better replacement model.",
        "host_dynamic": "Juno defends the intuitive appeal; Caspar challenges the claim while preserving nuance.",
        "avoid": "Avoid dunking on people for believing understandable things.",
    },
    "debate": {
        "label": "Friendly Debate",
        "tagline": "A structured disagreement where both sides get stronger.",
        "best_for": "Ethical tradeoffs, design decisions, policy, philosophy, and ambiguous evidence.",
        "research_focus": "Collect the best arguments on multiple sides and where evidence is thin.",
        "structure": "Shared question -> case A -> case B -> cross-examination -> synthesis or live tension.",
        "host_dynamic": "Juno and Caspar each own a stance, then steelman the other side before ending.",
        "avoid": "Avoid false balance when one side is much better supported.",
    },
    "history": {
        "label": "Origin Story",
        "tagline": "How an idea, object, field, or habit became what it is.",
        "best_for": "Inventions, scientific concepts, cultural practices, tools, and institutions.",
        "research_focus": "Find chronology, forgotten contributors, turning points, and what changed meaning over time.",
        "structure": "Present-day object -> origin -> turning points -> forgotten branch -> present consequences.",
        "host_dynamic": "Juno follows symbols and people; Caspar follows mechanisms and dates.",
        "avoid": "Avoid simple 'great person invented X' stories unless the evidence truly supports that.",
    },
    "field_guide": {
        "label": "Field Guide",
        "tagline": "A listener's guide to noticing patterns in the real world.",
        "best_for": "Nature, design, cities, music, social behavior, health, and everyday science.",
        "research_focus": "Identify visible signs, categories, examples, and practical noticing exercises.",
        "structure": "What to look for -> categories -> examples -> mistakes -> listener challenge.",
        "host_dynamic": "Juno makes the world feel strange again; Caspar gives names and mechanisms.",
        "avoid": "Avoid abstract discussion without sensory examples.",
    },
    "decision_brief": {
        "label": "Decision Brief",
        "tagline": "A concise tradeoff analysis that helps someone choose a path.",
        "best_for": "Buying decisions, tool choices, career moves, architecture choices, and strategy.",
        "research_focus": "Compare options, constraints, cost, risk, reversibility, and who each option fits.",
        "structure": "Decision frame -> options -> tradeoffs -> scenarios -> recommendation logic.",
        "host_dynamic": "Caspar builds the matrix; Juno checks what the choice feels like in practice.",
        "avoid": "Avoid one-size-fits-all advice. State assumptions.",
    },
    "critique": {
        "label": "Critique",
        "tagline": "A rigorous, generous evaluation of a work, idea, tool, or argument.",
        "best_for": "Books, papers, films, apps, designs, strategies, products, claims, and creative work.",
        "research_focus": "Identify context, intent, strongest contributions, weak points, alternatives, and audience fit.",
        "structure": "Object under review -> context -> what works -> what breaks -> comparison -> final judgment.",
        "host_dynamic": "Juno evaluates taste, texture, and lived experience; Caspar tests evidence, logic, and tradeoffs.",
        "avoid": "Avoid snark, scorekeeping, or flattening critique into either praise or complaint.",
    },
    "future_scenario": {
        "label": "Future Scenario",
        "tagline": "A grounded speculation episode with clear uncertainty labels.",
        "best_for": "Emerging technology, climate, culture, medicine, media, and long-term possibilities.",
        "research_focus": "Separate known facts, plausible trajectories, constraints, and wildcards.",
        "structure": "Present signal -> drivers -> scenario one -> scenario two -> constraints -> watchlist.",
        "host_dynamic": "Juno imagines lived experience; Caspar keeps the futures attached to evidence.",
        "avoid": "Avoid confident prophecy or sci-fi drift unmoored from present facts.",
    },
    "lab_notes": {
        "label": "Lab Notes",
        "tagline": "A build-log or experiment episode with honest process and failure modes.",
        "best_for": "Personal projects, code experiments, creative process, prototypes, and debugging stories.",
        "research_focus": "Capture attempts, constraints, failures, tools, lessons, and next experiment.",
        "structure": "Goal -> setup -> attempt -> surprise -> fix or failure -> lessons -> next iteration.",
        "host_dynamic": "Juno tracks curiosity and taste; Caspar tracks method and reproducibility.",
        "avoid": "Avoid pretending the process was cleaner than it was.",
    },
    "complete_fiction": {
        "label": "Complete Fiction",
        "tagline": "A fully invented two-voice audio story with no claim to factual reportage.",
        "best_for": "Speculative vignettes, allegories, micro-dramas, surreal tutorials, and invented worlds.",
        "research_focus": "Use background research only for texture, genre awareness, and plausibility; the episode itself is fictional.",
        "structure": "Premise -> scene -> escalation -> reveal -> emotional turn -> clean ending.",
        "host_dynamic": "Juno and Caspar may perform characters, narrate, or remain fictionalized hosts inside the story.",
        "avoid": "Avoid fake citations, real-person defamation, and presenting invented events as true.",
    },
    "review": {
        "label": "Review And Quiz",
        "tagline": "A consolidation episode that checks understanding and reinforces the path.",
        "best_for": "Course checkpoints, recap episodes, spaced repetition, and final mini-course reviews.",
        "research_focus": "Extract the concepts worth remembering, common confusions, and useful questions.",
        "structure": "Recall -> concept map -> common traps -> quiz -> synthesis -> next learning step.",
        "host_dynamic": "Juno notices what finally clicked; Caspar turns it into retrieval practice.",
        "avoid": "Avoid bland recap. Make the listener actively retrieve and connect ideas.",
    },
    "digest": {
        "label": "Journal Digest",
        "tagline": "A weekly peer-level rounds on the most important new papers in a niche.",
        "best_for": "Recurring research round-ups for a specialist who already knows the field.",
        "research_focus": (
            "Work ONLY from the supplied ranked article list. For the headline paper, surface design, "
            "population, effect size, key limitations, and how it changes practice. For each quick-hit "
            "round, give one paraphrased finding, the journal, and why it matters to a specialist. "
            "Paraphrase from the metadata provided; never reproduce abstracts verbatim."
        ),
        "structure": (
            "Cold open on why this week matters -> headline paper in depth (design, numbers, caveats, "
            "practice impact) -> 3 to 5 rapid rounds (one finding each) -> what to watch / still unsettled "
            "-> sign-off; journal and DOI citations go in the show notes."
        ),
        "host_dynamic": (
            "Caspar drives methods, statistics, and evidence quality; Juno presses on clinical meaning, "
            "patient-facing stakes, and what actually changes. Peer-to-peer, not explainer; assume the "
            "listener is a specialist physician."
        ),
        "avoid": (
            "Avoid lay-explainer framing, defining basic specialist terms, reading abstracts verbatim, "
            "hype, and overclaiming from single small studies. Label preprints and weak evidence clearly."
        ),
    },
}

EPISODE_TYPE_ALIASES: dict[str, str] = {
    "default": "deep_dive",
    "deep": "deep_dive",
    "deep-dive": "deep_dive",
    "dive": "deep_dive",
    "broad": "overview",
    "intro": "overview",
    "primer": "overview",
    "explainer": "overview",
    "teach": "how_to",
    "teaching": "how_to",
    "howto": "how_to",
    "how-to": "how_to",
    "tutorial": "how_to",
    "lesson": "how_to",
    "scout": "landscape",
    "scan": "landscape",
    "market": "landscape",
    "landscape-scan": "landscape",
    "case": "case_study",
    "case-study": "case_study",
    "narrative": "story",
    "narrative-story": "story",
    "nonfiction-story": "story",
    "myth": "myth_bust",
    "mythbust": "myth_bust",
    "myth-bust": "myth_bust",
    "factcheck": "myth_bust",
    "argument": "debate",
    "versus": "debate",
    "vs": "debate",
    "origin": "history",
    "origins": "history",
    "historical": "history",
    "guide": "field_guide",
    "field-guide": "field_guide",
    "noticing": "field_guide",
    "decision": "decision_brief",
    "brief": "decision_brief",
    "compare": "decision_brief",
    "tradeoff": "decision_brief",
    "critic": "critique",
    "critical": "critique",
    "crit": "critique",
    "future": "future_scenario",
    "scenario": "future_scenario",
    "forecast": "future_scenario",
    "lab": "lab_notes",
    "build": "lab_notes",
    "build-log": "lab_notes",
    "experiment": "lab_notes",
    "fiction": "complete_fiction",
    "fictional": "complete_fiction",
    "complete-fiction": "complete_fiction",
    "completefiction": "complete_fiction",
    "audio-drama": "complete_fiction",
    "drama": "complete_fiction",
    "recap": "review",
    "quiz": "review",
    "assessment": "review",
    "journal": "digest",
    "rounds": "digest",
    "roundup": "digest",
    "weekly": "digest",
}


def _canonical_token(value: str) -> str:
    return re.sub(r"[\s_]+", "-", value.strip().lower())


def normalize_episode_type(value: str | None) -> str:
    if not value:
        return DEFAULT_EPISODE_TYPE
    token = _canonical_token(value)
    direct = token.replace("-", "_")
    if direct in EPISODE_TYPES:
        return direct
    if token in EPISODE_TYPE_ALIASES:
        return EPISODE_TYPE_ALIASES[token]
    valid = ", ".join(sorted(EPISODE_TYPES))
    raise ValueError(f"Unknown episode type {value!r}. Valid types: {valid}")


def episode_type_label(value: str | None) -> str:
    key = normalize_episode_type(value)
    return str(EPISODE_TYPES[key]["label"])


def episode_type_context(value: str | None) -> str:
    key = normalize_episode_type(value)
    data = EPISODE_TYPES[key]
    return "\n".join(
        [
            f"Episode type: {key} - {data['label']}",
            f"Tagline: {data['tagline']}",
            f"Best for: {data['best_for']}",
            f"Research focus: {data['research_focus']}",
            f"Structure: {data['structure']}",
            f"Host dynamic: {data['host_dynamic']}",
            f"Avoid: {data['avoid']}",
        ]
    )


def episode_type_help() -> str:
    lines = []
    for key, data in EPISODE_TYPES.items():
        lines.append(f"{key}: {data['label']} - {data['tagline']}")
    return "\n".join(lines)


def parse_episode_type_and_topic(
    text: str,
    default: str | None = DEFAULT_EPISODE_TYPE,
) -> tuple[str, str]:
    """Parse `--type how_to topic`, `--type=how_to topic`, or `howto: topic`."""
    raw = text.strip()
    if not raw:
        return normalize_episode_type(default), ""

    match = re.match(r"^--(?:type|episode-type)(?:=|\s+)(\S+)\s+(.+)$", raw, re.I)
    if match:
        return normalize_episode_type(match.group(1)), match.group(2).strip()
    if re.match(r"^--(?:type|episode-type)(?:=|\s+)", raw, re.I):
        raise ValueError("Episode type flag needs both a type and a topic.")

    match = re.match(r"^type=(\S+)\s+(.+)$", raw, re.I)
    if match:
        return normalize_episode_type(match.group(1)), match.group(2).strip()
    if re.match(r"^type=", raw, re.I):
        raise ValueError("type=... needs both a type and a topic.")

    match = re.match(r"^([A-Za-z][A-Za-z0-9_\-\s]{1,32}):\s+(.+)$", raw)
    if match:
        try:
            return normalize_episode_type(match.group(1)), match.group(2).strip()
        except ValueError:
            pass

    return normalize_episode_type(default), raw
