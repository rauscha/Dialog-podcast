#!/usr/bin/env python3
"""Citation-free ranking engine for the Asynchronous Rounds journal digests.

Pipeline:  Discover -> filter (ledger) -> cheap pre-rank funnel -> enrich
(Altmetric / SCImago / evidence) -> batched LLM importance -> 4-signal weighted
score -> recency weight + topic bias -> pick headline + rounds.

Why citation-free: target articles are 1-6 months old, so citation counts are
near-zero and useless. The signals that discriminate fresh papers are an LLM's
read of the abstract, age-normalized Altmetric attention, journal quartile, and
study-design / evidence level.

COPYRIGHT FIREWALL: raw abstracts are used ONLY inside this module (for LLM
scoring). The objects returned to callers carry the LLM's short *paraphrase*
plus bibliographic metadata + DOI — never the abstract text.

This module generates no audio and writes no files (the dry-run CLI only prints,
or writes a clean JSON when asked).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import digest_ledger as ledger_mod
import digest_sources as src
from digest_shows import DigestConfigError, get_show, list_show_ids

logger = logging.getLogger(__name__)

# Funnel sizes.
DISCOVER_LIMIT = 80     # PMIDs to esearch/efetch per show
PRESCORE_KEEP = 20      # candidates sent through Altmetric + the LLM

# Signal weights (renormalized over whichever signals are present).
W_LLM, W_ALT, W_QUART, W_EVID = 0.46, 0.24, 0.18, 0.12

QUARTILE_SCORE = {"Q1": 1.0, "Q2": 0.6, "Q3": 0.3, "Q4": 0.1}

# PublicationType -> evidence level (checked high-to-low; first match wins).
_EVIDENCE_TIERS: list[tuple[float, tuple[str, ...]]] = [
    (1.00, ("practice guideline", "guideline", "meta-analysis", "systematic review",
            "randomized controlled trial")),
    (0.70, ("multicenter study", "controlled clinical trial", "clinical trial, phase iii",
            "clinical trial", "comparative study")),
    (0.40, ("observational study", "validation study", "evaluation study", "clinical study")),
    (0.30, ("review",)),
    (0.15, ("case reports", "editorial", "comment", "letter", "news", "historical article")),
]


# ── date helpers ─────────────────────────────────────────────────────────────

def _window_dates(window_months: int, now: datetime) -> tuple[str, str]:
    until = now
    since = now - timedelta(days=window_months * 30 + 5)
    return since.strftime("%Y/%m/%d"), until.strftime("%Y/%m/%d")


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    value = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(value[: len(fmt) + 2], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _recency_norm(record: dict[str, Any], window_months: int, now: datetime) -> float:
    dt = _parse_date(record.get("entry_date")) or _parse_date(record.get("pub_date"))
    if dt is None:
        return 0.5
    days_old = max(0.0, (now - dt).days)
    span = max(1, window_months * 30)
    return max(0.0, min(1.0, 1.0 - days_old / span))


# ── query construction ───────────────────────────────────────────────────────

def _pubmed_term(show: dict[str, Any]) -> str:
    journals = " OR ".join(f'"{ta}"[ta]' for ta in show["journals"]["ta_names"])
    topic_parts = [f'"{m}"[mesh]' for m in show.get("mesh_terms", [])]
    topic_parts += [f'"{k}"[tiab]' for k in show.get("keywords", [])]
    topic = " OR ".join(topic_parts)
    return f"({journals}) AND ({topic}) AND English[la]"


def _europepmc_query(show: dict[str, Any], mindate: str, maxdate: str) -> str:
    # Preprints aren't in the target journals, so match by topic keywords + SRC:PPR.
    kws = show.get("keywords") or show.get("mesh_terms") or []
    topic = " OR ".join(f'"{k}"' for k in kws)
    lo = mindate.replace("/", "-")
    hi = maxdate.replace("/", "-")
    return f"({topic}) AND (SRC:PPR) AND (FIRST_PDATE:[{lo} TO {hi}])"


# ── discovery ────────────────────────────────────────────────────────────────

def discover(show: dict[str, Any], cfg: dict[str, Any], now: datetime) -> tuple[list[dict[str, Any]], dict[str, str]]:
    email, api_key = _resolve_ncbi(cfg)
    mindate, maxdate = _window_dates(int(show["window_months"]), now)
    term = _pubmed_term(show)

    pmids = src.pubmed_esearch(
        term, mindate=mindate, maxdate=maxdate, retmax=DISCOVER_LIMIT,
        email=email, api_key=api_key,
    )
    records = src.pubmed_efetch(pmids, email=email, api_key=api_key) if pmids else []

    if show.get("include_preprints"):
        records += src.europepmc_search(_europepmc_query(show, mindate, maxdate), page_size=40)

    # Dedup by stable key; drop untitled records.
    seen_keys: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for rec in records:
        if not str(rec.get("title") or "").strip():
            continue
        key = ledger_mod.candidate_key(rec)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(rec)

    meta = {"term": term, "mindate": mindate, "maxdate": maxdate}
    return deduped[:DISCOVER_LIMIT], meta


def _resolve_ncbi(cfg: dict[str, Any]) -> tuple[str, str | None]:
    email = str(cfg.get("ncbi_email") or "").strip()
    if not email:
        logger.warning("ncbi_email is empty; PubMed may throttle. Set NCBI_EMAIL or config ncbi_email.")
    api_key = os.environ.get(str(cfg.get("ncbi_api_key_env") or "NCBI_API_KEY")) or None
    return email, api_key


# ── enrichment ───────────────────────────────────────────────────────────────

def _evidence_level(pub_types: list[str]) -> float | None:
    if not pub_types:
        return None
    lc = [p.lower() for p in pub_types]
    for level, needles in _EVIDENCE_TIERS:
        if any(any(n in pt for pt in lc) for n in needles):
            return level
    return 0.40  # recognized as a research article but no special design tag


def enrich_cheap(records: list[dict[str, Any]], repo_root: Path) -> None:
    """Evidence level + journal quartile (local CSV only; no network)."""
    for rec in records:
        rec["evidence"] = _evidence_level(rec.get("publication_types") or [])
        quartile = None
        for issn in rec.get("issns") or []:
            q = src.sjr_quartile(issn, repo_root=repo_root)
            if q and (quartile is None or QUARTILE_SCORE[q] > QUARTILE_SCORE[quartile]):
                quartile = q
        rec["quartile"] = quartile
        rec["quartile_score"] = QUARTILE_SCORE.get(quartile) if quartile else None


def enrich_altmetric(records: list[dict[str, Any]], cfg: dict[str, Any]) -> None:
    """Altmetric age-normalized percentile (network; throttled to ~1 req/s)."""
    if not cfg.get("altmetric_enabled", True):
        for rec in records:
            rec["altmetric_pct"] = None
        return
    for rec in records:
        pct = None
        doi = rec.get("doi")
        if doi:
            data = src.altmetric_by_doi(doi)
            if data and data.get("percentile") is not None:
                pct = max(0.0, min(1.0, float(data["percentile"]) / 100.0))
        rec["altmetric_pct"] = pct


def _prescore(rec: dict[str, Any], window_months: int, now: datetime) -> float:
    quart = rec.get("quartile_score")
    quart = 0.3 if quart is None else quart
    evid = rec.get("evidence")
    evid = 0.4 if evid is None else evid
    recency = _recency_norm(rec, window_months, now)
    return 0.45 * quart + 0.35 * evid + 0.20 * recency


# ── LLM importance (batched, cloud model, no tools) ──────────────────────────

def _llm_importance(records: list[dict[str, Any]], show: dict[str, Any], client, model: str) -> dict[int, dict[str, Any]]:
    if client is None or not records:
        return {}
    lines = []
    for i, rec in enumerate(records):
        abstract = (rec.get("abstract") or "").strip().replace("\n", " ")[:1200]
        mesh = ", ".join((rec.get("mesh") or [])[:8])
        pts = ", ".join((rec.get("publication_types") or [])[:6])
        lines.append(
            f"[{i}] TITLE: {rec.get('title','')}\n"
            f"    JOURNAL: {rec.get('journal','')} ({rec.get('year','')}); "
            f"AUTHORS: {rec.get('authors',0)}; TYPES: {pts}; PREPRINT: {rec.get('is_preprint', False)}\n"
            f"    MESH: {mesh}\n"
            f"    ABSTRACT: {abstract or '(none)'}"
        )
    system = (
        "You are a senior editor curating a peer-level journal-club digest.\n"
        f"AUDIENCE: {show.get('audience','a specialist physician')}\n"
        "Rank each article's importance to that audience, scoring them RELATIVE to each other in this batch.\n"
        "Reward practice-changing findings, strong design (RCT/meta-analysis/large multicenter), and genuine novelty.\n"
        "Down-weight small-N, single-center, pilot/feasibility, animal/in-vitro, and purely incremental work.\n"
        "Treat preprints with extra caution (unreviewed).\n"
        "Write findings in YOUR OWN WORDS (paraphrase) — never copy sentences from the abstract.\n"
        "Return ONLY a JSON array, one object per article index, no prose:\n"
        '[{"idx": int, "importance": 0..1, "domain": "obgyn"|"imaging"|"general"|"other", '
        '"evidence_guess": 0..1, "finding": "<= 30 words, paraphrased", "why": "<= 12 words"}]'
    )
    content = "Articles:\n\n" + "\n\n".join(lines)
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": content}],
        )
        text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
        parsed = _extract_json_array(text)
    except Exception as exc:  # noqa: BLE001 - degrade to non-LLM ranking
        logger.warning("LLM importance scoring failed (%s); falling back to metadata signals.", exc)
        return {}
    if not parsed:
        logger.warning("LLM importance scoring returned no parseable JSON; using metadata signals.")
        return {}
    out: dict[int, dict[str, Any]] = {}
    for item in parsed:
        if not isinstance(item, dict) or "idx" not in item:
            continue
        try:
            idx = int(item["idx"])
        except (TypeError, ValueError):
            continue
        out[idx] = item
    return out


def _extract_json_array(text: str) -> list | None:
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1] if t.count("```") >= 2 else t.strip("`")
        t = t[4:] if t.lower().startswith("json") else t
        t = t.strip()
    try:
        parsed = json.loads(t)
        return parsed if isinstance(parsed, list) else None
    except json.JSONDecodeError:
        pass
    start, end = t.find("["), t.rfind("]")
    if start != -1 and end > start:
        try:
            parsed = json.loads(t[start : end + 1])
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
    # Salvage truncated/partial output: collect complete top-level {...} objects.
    objs: list = []
    depth = 0
    obj_start: int | None = None
    for i, ch in enumerate(t):
        if ch == "{":
            if depth == 0:
                obj_start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and obj_start is not None:
                try:
                    objs.append(json.loads(t[obj_start : i + 1]))
                except json.JSONDecodeError:
                    pass
                obj_start = None
    return objs or None


def _clamp01(value: Any) -> float | None:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def _infer_domain(rec: dict[str, Any]) -> str:
    hay = " ".join([rec.get("journal", "")] + (rec.get("mesh") or [])).lower()
    if any(w in hay for w in ("obstet", "gynecol", "pregnan", "fetal", "prenat", "perinat")):
        return "obgyn"
    if any(w in hay for w in ("radiol", "imaging", "ultrasound", "tomograph", "mri")):
        return "imaging"
    return "general"


# ── scoring ──────────────────────────────────────────────────────────────────

def score(records: list[dict[str, Any]], show: dict[str, Any], client, cfg: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    model = str(cfg.get("digest_rank_model") or "claude-sonnet-4-6")
    llm = _llm_importance(records, show, client, model)
    window_months = int(show["window_months"])
    topic_bias = show.get("topic_bias")

    for i, rec in enumerate(records):
        info = llm.get(i, {})
        importance = _clamp01(info.get("importance"))
        evid = rec.get("evidence")
        if evid is None:
            evid = _clamp01(info.get("evidence_guess"))
        alt = rec.get("altmetric_pct")
        quart = rec.get("quartile_score")

        signals: list[tuple[float, float]] = []
        if importance is not None:
            signals.append((W_LLM, importance))
        if alt is not None:
            signals.append((W_ALT, alt))
        if quart is not None:
            signals.append((W_QUART, quart))
        if evid is not None:
            signals.append((W_EVID, evid))
        base = sum(w * v for w, v in signals) / sum(w for w, _ in signals) if signals else 0.0

        recency = _recency_norm(rec, window_months, now)
        ranked = base * (0.7 + 0.3 * recency)

        domain = str(info.get("domain") or _infer_domain(rec)).lower()
        if topic_bias:
            factor = topic_bias.get(domain, topic_bias.get("other", 0.5))
            ranked *= float(factor)

        rec["_importance"] = importance
        rec["_evid"] = evid
        rec["_alt"] = alt
        rec["_quart_score"] = quart
        rec["_recency"] = recency
        rec["_domain"] = domain
        rec["_base"] = base
        rec["score"] = ranked
        rec["_finding"] = str(info.get("finding") or "").strip()
        rec["_why"] = str(info.get("why") or "").strip()

    return sorted(records, key=lambda r: r.get("score", 0.0), reverse=True)


# ── public entry point ───────────────────────────────────────────────────────

def _clean(rec: dict[str, Any], role: str, rank: int) -> dict[str, Any]:
    """Build a published-safe view of a ranked article (NO abstract text)."""
    doi = ledger_mod.normalize_doi(rec.get("doi") or "")
    pmid = rec.get("pmid")
    if doi:
        url = f"https://doi.org/{doi}"
    elif pmid:
        url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    else:
        url = ""
    return {
        "role": role,
        "rank": rank,
        "key": rec.get("_key") or ledger_mod.candidate_key(rec),
        "doi": doi or None,
        "pmid": pmid,
        "title": rec.get("title", ""),
        "journal": rec.get("journal", ""),
        "year": rec.get("year"),
        "first_author": rec.get("first_author") or None,
        "quartile": rec.get("quartile"),
        "evidence": rec.get("_evid"),
        "altmetric_pct": rec.get("_alt"),
        "importance": rec.get("_importance"),
        "domain": rec.get("_domain"),
        "score": round(float(rec.get("score", 0.0)), 4),
        "finding": rec.get("_finding", ""),
        "why": rec.get("_why", ""),
        "is_preprint": bool(rec.get("is_preprint")),
        "url": url,
    }


def rank_show(
    show: dict[str, Any],
    ledger: dict[str, Any],
    client,
    *,
    cfg: dict[str, Any],
    repo_root: Path,
    now: datetime | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Rank a show's recent literature and return headline + rounds (+ full table)."""
    now = now or datetime.now(timezone.utc)
    records, meta = discover(show, cfg, now)
    unseen, seen = ledger_mod.filter_unseen(ledger, records)

    enrich_cheap(unseen, repo_root)
    unseen.sort(key=lambda r: _prescore(r, int(show["window_months"]), now), reverse=True)
    kept = unseen[:PRESCORE_KEEP]

    enrich_altmetric(kept, cfg)
    scored = score(kept, show, client, cfg, now)

    top_n = int(show["top_n"])
    max_rounds = int(show["max_rounds"])
    headline = _clean(scored[0], "headline", 1) if scored else None
    rounds_n = max(0, min(top_n - 1, max_rounds, len(scored) - 1))
    rounds = [_clean(r, "round", i + 2) for i, r in enumerate(scored[1 : 1 + rounds_n])]

    return {
        "show_id": show["id"],
        "display_name": show["display_name"],
        "generated_at": now.isoformat(),
        "window": {"from": meta["mindate"], "to": meta["maxdate"]},
        "term": meta["term"],
        "discovered": len(records),
        "filtered_covered": len(seen),
        "considered": len(kept),
        "headline": headline,
        "rounds": rounds,
        "all_scored": [_clean(r, "round" if i else "headline", i + 1) for i, r in enumerate(scored)],
        "filtered_out_keys": [ledger_mod.candidate_key(r) for r in seen],
        "dry_run": dry_run,
    }


# ── dry-run rendering ────────────────────────────────────────────────────────

def _fmt(value: Any, width: int = 4) -> str:
    if value is None:
        return "-".rjust(width)
    try:
        return f"{float(value):.2f}".rjust(width)
    except (TypeError, ValueError):
        return str(value).rjust(width)


def format_dry_run_table(result: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("=" * 100)
    lines.append(f"{result['display_name']}  ({result['show_id']})   window {result['window']['from']} -> {result['window']['to']}")
    lines.append(
        f"discovered={result['discovered']}  already-covered(skipped)={result['filtered_covered']}  "
        f"considered={result['considered']}"
    )
    lines.append("-" * 100)
    lines.append(f"{'#':>2}  {'score':>5}  {'llm':>4}  {'alt':>4}  {'Q':>2}  {'ev':>4}  {'journal':<22}  title")
    lines.append("-" * 100)
    for row in result["all_scored"]:
        q = row.get("quartile") or "-"
        flag = "*" if row["role"] == "headline" else (" " if row["rank"] > (1 + len(result["rounds"])) else "+")
        title = (row["title"][:47] + "...") if len(row["title"]) > 50 else row["title"]
        journal = (row["journal"][:19] + "...") if len(row["journal"]) > 22 else row["journal"]
        lines.append(
            f"{row['rank']:>2}{flag} {_fmt(row['score'],5)}  {_fmt(row['importance'])}  "
            f"{_fmt(row['altmetric_pct'])}  {q:>2}  {_fmt(row['evidence'])}  {journal:<22}  {title}"
        )
    lines.append("-" * 100)
    if result["headline"]:
        h = result["headline"]
        lines.append(f"HEADLINE: {h['title']}")
        lines.append(f"          {h['journal']} {h.get('year') or ''}  |  {h['url']}")
        if h["finding"]:
            lines.append(f"          finding: {h['finding']}")
        lines.append("ROUNDS:")
        for r in result["rounds"]:
            lines.append(f"  {r['rank']}. {r['title']}  [{r['journal']}]")
            if r["finding"]:
                lines.append(f"      finding: {r['finding']}")
    else:
        lines.append("(no candidates found — check journal abbreviations / query / date window)")
    lines.append("* = headline   + = round   (legend)")
    lines.append("=" * 100)
    return "\n".join(lines)


# ── standalone CLI ───────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # journal titles carry non-cp1252 chars
    except Exception:  # noqa: BLE001
        pass
    parser = argparse.ArgumentParser(description="Rank recent journal articles for an Asynchronous Rounds digest (dry-run).")
    parser.add_argument("show", nargs="?", help="Show id (e.g. mfm, fetal, ai)")
    parser.add_argument("--repo", default=".", help="Repo root")
    parser.add_argument("--window-months", type=int, default=None, help="Override the show's lookback window")
    parser.add_argument("--json", default=None, help="Also write the clean result JSON to this path")
    parser.add_argument("--list", action="store_true", help="List available shows and exit")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo)
    try:
        if args.list or not args.show:
            print("Shows:", ", ".join(list_show_ids(repo_root)))
            return 0
        show = get_show(repo_root, args.show)
    except DigestConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.window_months:
        show = dict(show)
        show["window_months"] = args.window_months

    # Reuse the generator's config loader + Anthropic client construction.
    from generate_podcast import load_config  # lazy: avoids heavy import at module load
    import anthropic

    cfg = load_config(repo_root)
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    client = anthropic.Anthropic(api_key=api_key) if api_key else None
    if client is None:
        logger.warning("ANTHROPIC_API_KEY not set; ranking will use metadata signals only (no LLM importance).")

    ledger = ledger_mod.load_ledger(repo_root, show["id"])
    result = rank_show(show, ledger, client, cfg=cfg, repo_root=repo_root, dry_run=True)
    print(format_dry_run_table(result))

    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"\nWrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
