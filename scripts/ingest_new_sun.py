#!/usr/bin/env python3
"""Split the four Book of the New Sun EPUBs into chapters.

Reads books/new-sun/{1-shadow,2-claw,3-sword,4-citadel}.epub and writes
books/new-sun/chapters.json: one entry per chapter with volume, chapter number,
title, and text. books/ is gitignored; the text is copyrighted and stays local.

The four files come from different sources and mark chapters three ways
("I" / "Chapter 1" / "CHAPTER ONE"), so a heading counts only when it is the
next ordinal in sequence, is followed by a title line, and prose follows within
a few lines. That skips tables of contents. Wolfe's appendices are kept as a
final "appendix" entry per volume.

pdf_derived=True handles a PDF-converted EPUB (lines broken mid-sentence, page
numbers on their own lines): page numbers are dropped and lines rejoined. The
first Shadow copy was one; the current copy (Pocket Books, via calibre) is not.
"""

from __future__ import annotations

import html
import json
import re
import sys
import zipfile
from pathlib import Path
from posixpath import dirname, join, normpath

BOOK_DIR = Path(__file__).resolve().parent.parent / "books" / "new-sun"
VOLUMES = [
    (1, "The Shadow of the Torturer", "1-shadow.epub"),
    (2, "The Claw of the Conciliator", "2-claw.epub"),
    (3, "The Sword of the Lictor", "3-sword.epub"),
    (4, "The Citadel of the Autarch", "4-citadel.epub"),
]
_STOP = re.compile(r"^(APPENDIX|ABOUT THE AUTHOR|ENTER THE SF GATEWAY|Спасибо)", re.I)
_ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
_WORDS = (
    "ONE TWO THREE FOUR FIVE SIX SEVEN EIGHT NINE TEN ELEVEN TWELVE THIRTEEN "
    "FOURTEEN FIFTEEN SIXTEEN SEVENTEEN EIGHTEEN NINETEEN"
).split()
_TENS = {"TWENTY": 20, "THIRTY": 30, "FORTY": 40}


def _roman(s: str) -> int | None:
    if not re.fullmatch(r"[IVXLC]+", s):
        return None
    total = 0
    for a, b in zip(s, s[1:] + " "):
        v = _ROMAN[a]
        total += -v if b != " " and _ROMAN[b] > v else v
    return total


def _words(s: str) -> int | None:
    parts = s.upper().split("-")
    if len(parts) == 1:
        if parts[0] in _TENS:
            return _TENS[parts[0]]
        return _WORDS.index(parts[0]) + 1 if parts[0] in _WORDS else None
    if parts[0] in _TENS and parts[1] in _WORDS[:9]:
        return _TENS[parts[0]] + _WORDS.index(parts[1]) + 1
    return None


def heading_number(line: str) -> int | None:
    m = re.fullmatch(r"(?:chapter\s+)?(\S+)", line.strip(), re.I)
    if not m:
        return None
    tok = m.group(1)
    if tok.isdigit():
        return int(tok) if line.lower().startswith("chapter") else None
    return _roman(tok) or (_words(tok) if line.upper().startswith("CHAPTER") else None)


def _titlecase(s: str) -> str:
    return " ".join(w[:1].upper() + w[1:].lower() for w in s.split())


def spine_lines(path: Path) -> list[str]:
    z = zipfile.ZipFile(path)
    opf_path = next(n for n in z.namelist() if n.endswith(".opf"))
    opf = z.read(opf_path).decode("utf-8", "replace")
    items = dict(re.findall(r'<item\b[^>]*?id="([^"]+)"[^>]*?href="([^"]+)"', opf))
    items.update({i: h for h, i in re.findall(r'<item\b[^>]*?href="([^"]+)"[^>]*?id="([^"]+)"', opf)})
    order = re.findall(r'<itemref\b[^>]*idref="([^"]+)"', opf)
    base = dirname(opf_path)
    raw = ""
    for idref in order:
        href = items.get(idref)
        if href:
            raw += z.read(normpath(join(base, href))).decode("utf-8", "replace")
    raw = re.sub(r"\s+", " ", raw)  # source newlines are line wrap, not breaks
    raw = re.sub(r"<(p|div|br|h\d|li)\b[^>]*>", "\n", raw, flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", "", raw))
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def split_chapters(lines: list[str], pdf_derived: bool) -> list[dict]:
    if pdf_derived:
        lines = [ln for ln in lines if not re.fullmatch(r"\d{1,3}", ln)]
    starts: list[tuple[int, int, str, int]] = []
    want = 1
    for k, ln in enumerate(lines[:-2]):
        if heading_number(ln) != want:
            continue
        title, skip = lines[k + 1], 2
        if pdf_derived and lines[k + 2].isupper() and len(lines[k + 2]) < 40:
            title, skip = f"{title} {lines[k + 2]}", 3  # title wrapped onto two lines
        after = lines[k + skip:k + skip + 3]
        min_prose = 30
        if len(title) > 70 or not any(len(x) > min_prose and re.search(r"[a-z]", x) for x in after):
            continue
        starts.append((k, want, title, skip))
        want += 1
    chapters = []
    for i, (k, num, title, skip) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(lines)
        body = lines[k + skip:end]
        appendix: list[str] = []
        if i + 1 == len(starts):
            stop = next((j for j, ln in enumerate(body) if _STOP.match(ln)), None)
            if stop is not None:
                appendix = [ln for ln in body[stop:] if not re.match(r"^(Спасибо|Оставить|Все книги|Другие книги)", ln)]
                body = body[:stop]
        joiner = " " if pdf_derived else "\n\n"
        chapters.append({"chapter": num, "title": _titlecase(title) if title.isupper() else title,
                         "text": joiner.join(body)})
        if appendix and not re.match(r"^(ABOUT THE AUTHOR|ENTER THE SF)", appendix[0], re.I):
            chapters.append({"chapter": "appendix", "title": _titlecase(appendix[0]),
                             "text": joiner.join(appendix[1:])})
    return chapters


def main() -> int:
    out = []
    for vol, name, fname in VOLUMES:
        path = BOOK_DIR / fname
        chapters = split_chapters(spine_lines(path), pdf_derived=False)
        numbered = [c for c in chapters if c["chapter"] != "appendix"]
        words = sum(len(c["text"].split()) for c in numbered)
        print(f"{vol} {name}: {len(numbered)} chapters, {words:,} words"
              f"{' + appendix' if len(chapters) > len(numbered) else ''}")
        for c in chapters:
            out.append({"volume": vol, "volume_title": name, **c,
                        "words": len(c["text"].split())})
    (BOOK_DIR / "chapters.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"wrote {BOOK_DIR / 'chapters.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
