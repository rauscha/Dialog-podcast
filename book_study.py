#!/usr/bin/env python3
"""Ultan's Library: write one Book of the New Sun study episode (text only).

Reads books/new-sun/chapters.json (made by scripts/ingest_new_sun.py) and writes,
under books/ultans-library/epNN/ (gitignored, like the book text):

  brief.json   chapter summaries, who's who, glossary, quotes, discussion seeds
  tail.json    "what this sets up" notes, each checked against later chapters
  script.txt   the dialogue, in the house format  SPEAKER [emotion]: text
  check.md     the text-check report (claims the book doesn't support, misquotes)
  guide.md     the written study guide

Spoiler fence by construction: the body of the episode is written and checked
with only the chapters read so far in context. Later chapters are used only for
the closing "what this sets up" segment, which the script announces so the
listener can skip it.

No audio. Rendering is a separate step once the voices are chosen.

    python book_study.py --episode 1 --volume 1 --chapters 1-7
    python book_study.py --episode 1 --render     # audio, using ultans_library.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import anthropic

from secret_env import load_secret_env

ROOT = Path(__file__).parent
load_secret_env(ROOT)

BOOK_DIR = ROOT / "books" / "new-sun"
OUT_DIR = ROOT / "books" / "ultans-library"
MODEL = "claude-opus-5-5"
TAIL_MARKER = "### WHAT THIS SETS UP ###"
WORDS_PER_MINUTE = 150

_SHOW = """\
"Ultan's Library" is a private two-host study show for one listener: Andrew, a
physician and musician, rereading Gene Wolfe's The Book of the New Sun for the
first time in about twenty years. He listens in the car, so everything must work
by ear alone: no "as you can see", no lists read aloud, names said clearly and
re-anchored ("Thecla, the exultant prisoner"), chapter titles spoken so he can
find his place. He remembers the shape of the books, not the details.

The hosts:
- JUNO: artistic, literary. She hears the prose: Wolfe's rare words, Severian's
  claim of perfect memory and what he chooses not to tell, the religious and
  mythic undertow, the way scenes rhyme. Warm, quick, delighted by a sentence.
- CASPAR: scientific, dry, a careful reader. He notices the far-future science
  fiction hiding under the fantasy furniture, keeps track of what the text
  actually says versus what the reader assumes, and asks "how do we know that?"
  Measured, with dry wit. He is the one who says "let's look at what's on the page."

The register is a good seminar between two people who love the book, not a
lecture and not a fan podcast. They disagree sometimes and leave some questions
open. Every interpretive claim is marked by how strong it is: what the text
says, a strong reading, or a theory readers argue about."""


COURSE = ROOT / "docs" / "ultans-library" / "course.md"
SOURCES = ROOT / "books" / "sources" / "text"


def course_unit(episode: int) -> dict:
    """This episode's unit from the course: fenced aims, payoff notes, critical frame."""
    if not COURSE.exists():
        return {}
    text = COURSE.read_text(encoding="utf-8")
    m = re.search(rf"^### Unit {episode} \u2014.*?(?=^### Unit |^## 6\.|\Z)", text, re.S | re.M)
    if not m:
        return {}
    unit = m.group(0)
    fenced, _, rest = unit.partition("**Payoff notes")
    payoff, _, frame = rest.partition("**Critical frame:**")
    return {"fenced": fenced.strip(), "payoff": ("**Payoff notes" + payoff).strip(),
            "frame": frame.strip()}


def chapter_guide(volume: int, first: int, last: int) -> str:
    """Andre-Driussi's Chapter Guide entries for these chapters (local copy, if present)."""
    path = SOURCES / "chapter-guide.txt"
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8").splitlines()
    starts = [i for i, ln in enumerate(lines) if ln.startswith("1. ")]  # four volumes, then Urth
    if len(starts) < volume:
        return ""
    lo = starts[volume - 1]
    hi = starts[volume] if volume < len(starts) else len(lines)
    out, keep = [], False
    for ln in lines[lo:hi]:
        m = re.match(r"^(\d+)\. \S", ln)
        if m:
            keep = first <= int(m.group(1)) <= last
        elif ln.startswith("Appendix"):
            keep = False
        if keep:
            out.append(ln)
    return "\n".join(out)


def lexicon(words: list[str]) -> str:
    """Lexicon Urthus entries for these headwords (local copy, if present)."""
    path = SOURCES / "lexicon-urthus.txt"
    if not path.exists() or not words:
        return ""
    lines = path.read_text(encoding="utf-8").splitlines()
    out = []
    for w in words:
        key = w.lower().strip()
        for i, ln in enumerate(lines):
            if ln.lower().startswith(key + " ") or ln.lower() == key:
                out.extend(lines[i:i + 3])
                break
    return "\n".join(out)


def load_chapters(volume: int) -> list[dict]:
    data = json.loads((BOOK_DIR / "chapters.json").read_text(encoding="utf-8"))
    return [c for c in data if c["volume"] == volume and isinstance(c["chapter"], int)]


def chapter_block(chapters: list[dict]) -> str:
    return "\n\n".join(
        f"=== {c['volume_title']}, Chapter {c['chapter']}: {c['title']} ===\n\n{c['text']}"
        for c in chapters
    )


def ask(client: anthropic.Anthropic, system: str, book_text: str, prompt: str,
        effort: str = "high") -> str:
    """One streamed call with the book text as a cached first block."""
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=64000,
        betas=["server-side-fallback-2026-07-01"],
        extra_body={"fallbacks": "default"},
        output_config={"effort": effort},
        system=system,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": book_text, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": prompt},
            ],
        }],
    ) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        raise RuntimeError(f"model declined: {msg.stop_details}")
    if msg.stop_reason == "max_tokens":
        raise RuntimeError("hit max_tokens; output truncated")
    u = msg.usage
    print(f"    tokens in {u.input_tokens} (+{u.cache_read_input_tokens or 0} cached) "
          f"out {u.output_tokens}", flush=True)
    return "".join(b.text for b in msg.content if b.type == "text").strip()


def parse_json(text: str):
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    return json.loads(m.group(1) if m else text)


_BRIEF_PROMPT = """\
These are chapters {first}-{last} of {volume}, the part Andrew has just read.

This episode's unit in the course plan (teaching aims are spoiler-fenced):
{unit}

Michael Andre-Driussi's Chapter Guide notes for these chapters (a reference for
allusions and word sources; it sometimes mentions later events, which must not
reach the brief):
{guide}

Using ONLY the chapter text for what happens, write a study brief as JSON (no commentary) with:

{{
 "chapters": [{{"chapter": n, "title": "...", "summary": "4-6 sentences of what happens"}}],
 "who_is_who": [{{"name": "...", "how_to_say_it": "...", "who": "one line, as of this point"}}],
 "glossary": [{{"word": "...", "how_to_say_it": "...", "meaning": "what it means here, and the real
   archaic or technical word Wolfe took it from, if he did", "chapter": n}}],
 "quotes": [{{"chapter": n, "text": "exact words from the text, at most 40", "why": "..."}}],
 "threads": ["questions, images and patterns worth discussing, grounded in these chapters"],
 "watch_for": ["things to keep an eye on in the next chapters, phrased so they spoil nothing"]
}}

10-15 glossary words, 6-10 quotes copied exactly, 8-12 threads, 4-6 watch_for.
Nothing from later in the books, not even hints of it."""

_TAIL_PROMPT = """\
These are chapters {first}-{last} of {volume}. You also know the whole tetralogy.
For the closing, skippable segment of the episode, list every thing in these
chapters that genuinely pays off later (as many as there are; often 4-10, fewer
is fine if that is what the text supports) in The Book of the New Sun (all four volumes; not
The Urth of the New Sun). For each, say where the payoff is and give words that
appear in that later passage so it can be found in the text.

JSON only:
[{{"setup": "what happens or is said in these chapters",
   "payoff": "what it turns out to mean later",
   "volume": 1-4, "chapter_guess": n, "search_terms": ["2-4 distinctive words"]}}]"""

_TAIL_CHECK_PROMPT = """\
Below are "what this sets up" notes for a study episode, each followed by passages
retrieved from the book where the payoff is said to be. For each note: keep it if
the passages support it, correct it if they support a different version, and drop
it if nothing supports it. Distinguish what the text says from interpretation.

JSON only: [{{"setup": "...", "payoff": "...", "where": "Volume, chapter n: title",
"strength": "the text says | strong reading | reader theory", "verdict": "kept | corrected | dropped",
"note": "why"}}]

{notes}"""

_SCRIPT_PROMPT = """\
These are chapters {first}-{last} of {volume}. Write episode {episode} of Ultan's
Library covering them. This is one session of a literature course on the whole
book, not a recap: the episode knows what it is teaching.

This episode's unit in the course plan. Its teaching aims are the spine of the
body; its payoff notes are material for after the marker only:
{unit}

Lexicon Urthus entries for this episode's words (for glosses; say them in your
own words):
{lexicon}

Study brief (from these chapters only):
{brief}

Checked notes for the closing segment (the course's payoff notes are in the
unit above; use both, after the marker only):
{tail}

Shape:
1. Open by orienting the listener: what book and chapters this is, where Severian
   is, and (episode 1 only) what kind of book this is and who is telling it. Then
   say, in a sentence or two of natural talk, what this session is about: the
   question it will chase.
2. The body: three or four movements built around the strongest threads, not a
   chapter-by-chapter recap. Walk through what happens as you go, so he can follow
   even if his memory is hazy. Speak chapter titles at least once. Gloss rare
   words in passing, by ear. Quote the text a few times, briefly and exactly.
   Leave at least one question genuinely open between them.
3. Close the body by saying plainly what this session taught, which threads it
   leaves open for the course, and two or three questions for the next drive.
   When a critic's reading helps, name the critic and label it.
4. Then a line on its own, exactly: {marker}
5. The skippable segment: one host says plainly that what follows draws on the
   rest of the books, so this is the place to stop if he wants it fresh. Then
   the checked setups and payoffs, with how sure each one is. Give it the room
   the payoffs need, and no more.
6. A brief sign-off naming the chapters for next time if known.

Rules:
- The body uses ONLY what is in these chapters. Nothing from later books, no
  winks at what is coming. Everything later lives after the marker.
- Every line: SPEAKER [emotion]: text, with SPEAKER either JUNO or CASPAR and a
  2-4 word delivery note in the brackets. No headers, no stage directions, no
  bullet points, nothing that isn't spoken except the marker line.
- Interruptions with em dashes. They build on each other; no trading monologues.
- About {words} words before the marker. After it, as long as the payoffs need
  (roughly 100-150 words each).
- Plain spoken English. No sourcing of the "sources for today's episode" kind."""

_CHECK_PROMPT = """\
These are chapters {first}-{last} of {volume}. Below is the body of a study-episode
script about them. Check every claim about the book against this text only.

Report as JSON:
{{"issues": [{{"line": "the script line, abridged", "problem": "unsupported | contradicted |
  misquote | beyond these chapters | mispronunciation guide wrong", "detail": "...",
  "fix": "the corrected line, in the same SPEAKER [emotion]: text format, or empty to delete"}}],
 "verdict": "one sentence"}}

Interpretation is fine when it is presented as interpretation. Flag interpretation
stated as fact. A quote must match the text word for word.

SCRIPT BODY:
{body}"""


def retrieve(volume: int, terms: list[str], limit: int = 3) -> list[str]:
    chapters = load_chapters(volume)
    scored = []
    for c in chapters:
        for para in c["text"].split("\n\n"):
            low = para.lower()
            hits = sum(1 for t in terms if t.lower() in low)
            if hits:
                scored.append((hits, f"[{c['volume_title']}, ch. {c['chapter']}: {c['title']}] {para}"))
    scored.sort(key=lambda x: -x[0])
    return [p[:1500] for _, p in scored[:limit]]


def apply_fixes(body: str, issues: list[dict]) -> tuple[str, int]:
    lines = body.splitlines()
    applied = 0
    for issue in issues:
        target = issue.get("line", "").strip().rstrip(".…")
        if not target:
            continue
        probe = target[:60]
        for i, ln in enumerate(lines):
            if probe and probe in ln:
                lines[i] = issue.get("fix", "").strip()
                applied += 1
                break
    return "\n".join(lines), applied


def render_guide(episode: int, volume_title: str, first: int, last: int, brief: dict,
                 tail: list[dict]) -> str:
    out = [f"# Ultan's Library, episode {episode}", "",
           f"*{volume_title}*, chapters {first}–{last}", ""]
    out += ["## What happens", ""]
    for c in brief["chapters"]:
        out += [f"**{c['chapter']}. {c['title']}.** {c['summary']}", ""]
    out += ["## Who's who", ""]
    out += [f"- **{p['name']}** ({p['how_to_say_it']}): {p['who']}" for p in brief["who_is_who"]] + [""]
    out += ["## Words", ""]
    out += [f"- **{g['word']}** ({g['how_to_say_it']}), ch. {g['chapter']}: {g['meaning']}"
            for g in brief["glossary"]] + [""]
    out += ["## Passages", ""]
    out += [f"> {q['text']}\n>\n> — ch. {q['chapter']}. {q['why']}\n" for q in brief["quotes"]]
    out += ["## To think about", ""]
    out += [f"{i}. {t}" for i, t in enumerate(brief["threads"], 1)] + [""]
    out += ["## Watch for", ""]
    out += [f"- {w}" for w in brief["watch_for"]] + [""]
    kept = [t for t in tail if t.get("verdict") != "dropped"]
    if kept:
        out += ["## What this sets up (spoilers for the rest of the books)", ""]
        out += [f"- **{t['setup']}** → {t['payoff']} ({t['where']}; {t['strength']})" for t in kept]
    return "\n".join(out) + "\n"


def render(episode: int) -> int:
    """Voice script.txt with the show's voices; a pause marks the spoiler segment."""
    import subprocess

    import generate_podcast as gp
    from audio_utils import two_pass_loudnorm

    out = OUT_DIR / f"ep{episode:02d}"
    script = (out / "script.txt").read_text(encoding="utf-8")
    cfg = gp.load_config(ROOT)
    show = json.loads((ROOT / "ultans_library.json").read_text(encoding="utf-8"))
    cfg.update({k: v for k, v in show.items() if not k.startswith("_")})

    work = out / "render"
    parts = []
    for name, text in zip(("body", "tail"), script.split(TAIL_MARKER, 1)):
        turns = gp._parse_dialogue_turns(text, cfg)
        if not turns:
            continue
        chars = sum(len(t[2]) for t in turns)
        print(f"{name}: {len(turns)} turns, {chars:,} characters", flush=True)
        turn_dir = work / f"turns_{name}"
        target = work / f"{name}.mp3"
        if target.exists() and target.stat().st_mtime > (out / "script.txt").stat().st_mtime:
            print(f"{name}: already rendered from this script, reusing", flush=True)
            parts.append(target)
            continue
        # tts_max_fail_ratio 0 (show config) makes a single unvoiced line abort the render.
        parts.append(gp._tts_two_host(text, target, cfg, turn_dir))

    joined = work / "joined.mp3"
    gap = float(cfg.get("spoiler_gap_sec", 2.5))
    inputs, chain = [], []
    for i, part in enumerate(parts):
        inputs += ["-i", str(part)]
        chain.append(f"[{i}:a]aresample=44100,aformat=channel_layouts=stereo[a{i}]")
    if len(parts) == 2:
        chain.append(f"[a0]apad=pad_dur={gap}[p0]")
        chain.append("[p0][a1]concat=n=2:v=0:a=1[out]")
    else:
        chain.append("[a0]anull[out]")
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs,
                    "-filter_complex", ";".join(chain), "-map", "[out]",
                    "-c:a", "libmp3lame", "-b:a", "192k", str(joined)], check=True)
    final = out / f"ultans-library-ep{episode:02d}.mp3"
    two_pass_loudnorm(joined, final, target_i=float(cfg.get("audio_loudness_i", -14.0)),
                      target_tp=float(cfg.get("audio_true_peak", -1.0)))
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(final)], capture_output=True, text=True).stdout
    print(f"done: {final} ({float(dur) / 60:.1f} min)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--episode", type=int, required=True)
    ap.add_argument("--volume", type=int)
    ap.add_argument("--chapters", help="e.g. 1-7")
    ap.add_argument("--minutes", type=int, default=27)
    ap.add_argument("--render", action="store_true", help="voice an existing script.txt")
    args = ap.parse_args()
    if args.render:
        return render(args.episode)
    if not (args.volume and args.chapters):
        ap.error("--volume and --chapters are required to write an episode")

    first, last = (int(x) for x in args.chapters.split("-"))
    chapters = [c for c in load_chapters(args.volume) if first <= c["chapter"] <= last]
    if len(chapters) != last - first + 1:
        print(f"expected {last - first + 1} chapters, found {len(chapters)}", file=sys.stderr)
        return 1
    volume_title = chapters[0]["volume_title"]
    book_text = chapter_block(chapters)
    out = OUT_DIR / f"ep{args.episode:02d}"
    out.mkdir(parents=True, exist_ok=True)
    unit = course_unit(args.episode)
    unit_fenced = "\n\n".join(x for x in (unit.get("fenced"), unit.get("frame")) if x) or "(none)"
    unit_all = "\n\n".join(x for x in (unit_fenced, unit.get("payoff")) if x)
    fmt = dict(first=first, last=last, volume=volume_title, episode=args.episode)
    client = anthropic.Anthropic()

    print(f"[1/5] brief: {volume_title} ch. {first}-{last}, "
          f"{sum(c['words'] for c in chapters):,} words of text", flush=True)
    brief = parse_json(ask(client, _SHOW, book_text, _BRIEF_PROMPT.format(
        **fmt, unit=unit_fenced, guide=chapter_guide(args.volume, first, last) or "(none)")))
    (out / "brief.json").write_text(json.dumps(brief, indent=1, ensure_ascii=False))

    print("[2/5] what this sets up: draft, then check against later chapters", flush=True)
    notes = parse_json(ask(client, _SHOW, book_text, _TAIL_PROMPT.format(**fmt)))
    blocks = []
    for n in notes:
        passages = retrieve(int(n["volume"]), n.get("search_terms", []))
        blocks.append(json.dumps({k: n[k] for k in ("setup", "payoff", "volume", "chapter_guess")})
                      + "\nPASSAGES:\n" + ("\n---\n".join(passages) or "(none found)"))
    tail = parse_json(ask(client, _SHOW, book_text,
                          _TAIL_CHECK_PROMPT.format(notes="\n\n=====\n\n".join(blocks))))
    (out / "tail.json").write_text(json.dumps(tail, indent=1, ensure_ascii=False))
    kept = [t for t in tail if t.get("verdict") != "dropped"]
    print(f"    {len(kept)} of {len(tail)} notes kept", flush=True)

    words = args.minutes * WORDS_PER_MINUTE
    print(f"[3/5] script: about {words:,} words ({args.minutes} min)", flush=True)
    script = ask(client, _SHOW, book_text, _SCRIPT_PROMPT.format(
        **fmt, brief=json.dumps(brief, ensure_ascii=False), tail=json.dumps(kept, ensure_ascii=False),
        unit=unit_all, lexicon=lexicon([g["word"] for g in brief.get("glossary", [])]) or "(none)",
        marker=TAIL_MARKER, words=words))
    (out / "script.draft.txt").write_text(script + "\n")
    if TAIL_MARKER not in script:
        print("    warning: no tail marker in the script", flush=True)
    body, _, tail_text = script.partition(TAIL_MARKER)

    print("[4/5] text-check the body against these chapters only", flush=True)
    report = parse_json(ask(client, _SHOW, book_text, _CHECK_PROMPT.format(**fmt, body=body)))
    issues = report.get("issues", [])
    body, applied = apply_fixes(body, issues)
    final = body.rstrip() + ("\n\n" + TAIL_MARKER + tail_text if tail_text else "")
    final = re.sub(r"\n{3,}", "\n\n", final)
    (out / "script.txt").write_text(final.strip() + "\n")
    lines = [f"# Text-check, episode {args.episode}", "", report.get("verdict", ""), "",
             f"{len(issues)} issues, {applied} fixes applied to script.txt "
             f"(the draft is in script.draft.txt).", ""]
    for i in issues:
        lines += [f"- **{i.get('problem')}**: {i.get('line')}", f"  - {i.get('detail')}",
                  f"  - fix: {i.get('fix') or '(line deleted)'}"]
    (out / "check.md").write_text("\n".join(lines) + "\n")

    print("[5/5] study guide", flush=True)
    (out / "guide.md").write_text(render_guide(args.episode, volume_title, first, last, brief, tail))

    spoken = sum(len(re.sub(r"^\w+\s*\[[^\]]*\]\s*:", "", ln).split())
                 for ln in final.splitlines() if ":" in ln)
    print(f"done: {spoken:,} spoken words, about {spoken / WORDS_PER_MINUTE:.0f} min -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
