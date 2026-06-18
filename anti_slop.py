#!/usr/bin/env python3
"""anti_slop.py — deterministic "slop" linter for episode scripts.

Phase C (editorial), first pass. A fast, free, deterministic pass that flags the
AI-podcast / LLM clichés and filler that survive the existing anti-cliche rewrite,
so they can be caught before TTS. This is a *report-only* tool by design — it does
not gate or rewrite anything. Run it on a finished script to see what reads as slop,
then tune the pattern list to taste.

    python anti_slop.py episodes/<...>/script.txt
    python anti_slop.py -  < script.txt

Deferred (need editorial judgment — see .handoff/PENDING-DECISIONS.md):
  - whether to wire this into the pipeline as a gate (reject + regenerate) vs. a
    warning, and at what score threshold / how many regen attempts;
  - an optional LLM critic layer for subtler slop the lexical pass can't see;
  - Phase C2: per-persona vocabulary lists + enforced-disagreement rules.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field


@dataclass
class SlopPattern:
    label: str
    regex: re.Pattern
    severity: int          # 1 = filler, 2 = cliche, 3 = strong LLM tell
    note: str = ""


def _p(pattern: str, label: str, severity: int, note: str = "") -> SlopPattern:
    return SlopPattern(label, re.compile(pattern, re.IGNORECASE), severity, note)


# Strong LLM "tells" — words a person almost never says aloud in conversation.
_LLM_TELLS = [
    _p(r"\bdelv(e|ing|ed)\b", "delve", 3),
    _p(r"\btapestr(y|ies)\b", "tapestry", 3),
    _p(r"\bin the realm of\b", "in the realm of", 3),
    _p(r"\ba testament to\b", "a testament to", 3),
    _p(r"\bnavigat(e|ing) the (complex|complexit|landscape|nuanc)", "navigate the complexities", 3),
    _p(r"\bplays? a (crucial|pivotal|vital|key|significant) role\b", "plays a crucial role", 3),
    _p(r"\bunderscor(e|es|ing|ed)\b", "underscore", 2),
    _p(r"\bmultifaceted\b", "multifaceted", 3),
]

# Podcast-host clichés / canned transitions.
_CLICHES = [
    _p(r"\b(dive|diving|dig|digging)\s+(deep(er)?|right in|in|into)\b", "let's dive in", 2),
    _p(r"\bbuckle up\b", "buckle up", 3),
    _p(r"\bwithout further ado\b", "without further ado", 3),
    _p(r"\bstay tuned\b", "stay tuned", 2),
    _p(r"\bat the end of the day\b", "at the end of the day", 2),
    _p(r"\bneedless to say\b", "needless to say", 2),
    _p(r"\bgame[\s-]?changer\b", "game-changer", 2),
    _p(r"\bthe bottom line\b", "the bottom line", 2),
    _p(r"\bin today'?s episode\b", "in today's episode", 2),
    _p(r"\blet'?s unpack\b", "let's unpack", 2),
    _p(r"\blet'?s break (it|this) down\b", "let's break it down", 2),
    _p(r"\b(i'?m glad you asked|great question)\b", "glad you asked / great question", 2),
    _p(r"\bit'?s not just\b.{1,45}?,?\s*it'?s\b", "it's not just X, it's Y", 3),
    _p(r"\brabbit hole\b", "rabbit hole", 1),
    _p(r"\bmind[\s-]?blow(ing|n)\b|\bblew my mind\b", "mind-blowing", 2),
    _p(r"\bthe (fascinating|interesting|crazy|wild) (thing|part) (is|here)\b", "the fascinating thing is", 2),
    _p(r"\bspoiler alert\b", "spoiler alert", 2),
    _p(r"\bwhen it comes to\b", "when it comes to", 1),
    _p(r"\bit'?s worth noting\b", "it's worth noting", 2),
]

# Filler / over-used intensifiers — natural in small doses, slop in bulk (density-judged).
_FILLERS = [
    _p(r"\bfascinating\b", "fascinating", 1),
    _p(r"\b(incredibly|extremely|absolutely|literally|truly|genuinely|utterly)\b", "intensifier", 1),
    _p(r"\bthat being said\b", "that being said", 1),
    _p(r"\bto be fair\b", "to be fair", 1),
]

# Conversational tags — only slop when over-dense (handled separately, not per-hit).
_TAG_RE = re.compile(r"\b(right|you know|i mean|kind of|sort of)\b[\s,?]", re.IGNORECASE)

ALL_PATTERNS: list[SlopPattern] = _LLM_TELLS + _CLICHES + _FILLERS


@dataclass
class Finding:
    label: str
    severity: int
    count: int
    examples: list[str] = field(default_factory=list)


def _word_count(text: str) -> int:
    return max(1, len(re.findall(r"\b\w+\b", text)))


def scan_slop(text: str) -> dict:
    """Scan text for slop patterns. Returns a length-normalized score (0-100, higher
    is cleaner) plus per-pattern findings and a density-based tag-overuse check."""
    words = _word_count(text)
    findings: list[Finding] = []
    weighted = 0

    for pat in ALL_PATTERNS:
        matches = pat.regex.findall(text)
        if not matches:
            continue
        # findall may return tuples when the pattern has groups; recount with finditer
        # for accurate count + readable examples.
        spans = list(pat.regex.finditer(text))
        count = len(spans)
        examples = [m.group(0).strip() for m in spans[:3]]
        findings.append(Finding(pat.label, pat.severity, count, examples))
        weighted += pat.severity * count

    # Conversational-tag overuse: only the portion above a natural baseline counts.
    tag_hits = len(_TAG_RE.findall(text))
    tag_per_1k = tag_hits / words * 1000
    tag_excess = 0
    if tag_per_1k > 12:  # baseline ~12 tags / 1000 words reads natural
        tag_excess = round((tag_per_1k - 12) * words / 1000)
        if tag_excess > 0:
            findings.append(Finding("conversational-tag overuse", 1, tag_excess,
                                    [f"{tag_hits} tags across {words} words"]))
            weighted += tag_excess

    density = weighted / words * 1000  # weighted slop per 1000 words
    score = max(0, round(100 - density * 4))
    findings.sort(key=lambda f: (f.severity, f.count), reverse=True)
    return {
        "score": score,
        "words": words,
        "weighted_hits": weighted,
        "density_per_1k": round(density, 2),
        "findings": findings,
    }


def format_report(result: dict) -> str:
    lines = [
        f"Anti-slop score: {result['score']}/100  "
        f"({result['weighted_hits']} weighted hits across {result['words']} words, "
        f"{result['density_per_1k']}/1k)",
    ]
    if not result["findings"]:
        lines.append("  clean — no slop patterns matched.")
        return "\n".join(lines)
    sev_name = {3: "TELL", 2: "cliche", 1: "filler"}
    for f in result["findings"]:
        ex = f"  e.g. {', '.join(repr(e) for e in f.examples)}" if f.examples else ""
        lines.append(f"  [{sev_name.get(f.severity, '?')}] {f.label} x{f.count}{ex}")
    return "\n".join(lines)


def _main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    src = argv[1]
    text = sys.stdin.read() if src == "-" else open(src, encoding="utf-8").read()
    print(format_report(scan_slop(text)))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
