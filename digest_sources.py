#!/usr/bin/env python3
"""Thin, soft-failing data-source clients for the digest ranking engine.

Every function here is defensive: network/parse errors are logged and turned
into an empty result (``[]`` / ``None`` / ``{}``) rather than raised, so the
ranker degrades gracefully when a single API is down. Nothing here generates
audio or writes files.

Sources:
    PubMed E-utilities  esearch + efetch        (free; abstract, pub-types, MeSH, authors, DOI, edat)
    Europe PMC REST     search (resultType=core) (no-auth fallback + preprints)
    Altmetric           v1/doi/{doi}             (free per-DOI details; 404 == no attention)
    SCImago             local CSV export         (ISSN -> SJR best quartile; offline join)

COPYRIGHT NOTE: abstracts returned by efetch/Europe PMC are publisher-copyrighted.
They are used only inside the ranker (LLM scoring); never published verbatim.
"""

from __future__ import annotations

import csv
import logging
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

_PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_EUROPEPMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_ALTMETRIC_DOI = "https://api.altmetric.com/v1/doi/"
_USER_AGENT = "AsynchronousRounds/0.1 (podcast digest; mailto:{email})"

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


# ── PubMed ───────────────────────────────────────────────────────────────────

def pubmed_esearch(
    term: str,
    *,
    mindate: str,
    maxdate: str,
    datetype: str = "edat",
    retmax: int = 200,
    sort: str = "date",
    email: str = "",
    api_key: str | None = None,
    timeout: int = 30,
) -> list[str]:
    """Return a list of PMIDs for ``term`` within [mindate, maxdate] (YYYY/MM/DD)."""
    params: dict[str, Any] = {
        "db": "pubmed",
        "term": term,
        "retmode": "json",
        "retmax": int(retmax),
        "datetype": datetype,
        "mindate": mindate,
        "maxdate": maxdate,
        "sort": sort,
        "tool": "AsynchronousRounds",
    }
    if email:
        params["email"] = email
    if api_key:
        params["api_key"] = api_key
    try:
        resp = requests.get(
            f"{_PUBMED_BASE}/esearch.fcgi",
            params=params,
            timeout=timeout,
            headers={"User-Agent": _USER_AGENT.format(email=email or "anonymous")},
        )
        if resp.status_code != 200:
            logger.warning("PubMed esearch HTTP %s: %s", resp.status_code, resp.text[:160])
            return []
        idlist = resp.json().get("esearchresult", {}).get("idlist", [])
        return [str(pmid) for pmid in idlist if str(pmid).strip()]
    except (requests.RequestException, ValueError) as exc:
        logger.warning("PubMed esearch failed: %s", exc)
        return []


def pubmed_efetch(
    pmids: list[str],
    *,
    email: str = "",
    api_key: str | None = None,
    timeout: int = 60,
) -> list[dict[str, Any]]:
    """Fetch full records for ``pmids`` and parse to normalized article dicts."""
    pmids = [str(p).strip() for p in pmids if str(p).strip()]
    if not pmids:
        return []
    data: dict[str, Any] = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
        "tool": "AsynchronousRounds",
    }
    if email:
        data["email"] = email
    if api_key:
        data["api_key"] = api_key
    try:
        resp = requests.post(
            f"{_PUBMED_BASE}/efetch.fcgi",
            data=data,
            timeout=timeout,
            headers={"User-Agent": _USER_AGENT.format(email=email or "anonymous")},
        )
        if resp.status_code != 200:
            logger.warning("PubMed efetch HTTP %s: %s", resp.status_code, resp.text[:160])
            return []
        return _parse_pubmed_xml(resp.text)
    except requests.RequestException as exc:
        logger.warning("PubMed efetch failed: %s", exc)
        return []


def _parse_pubmed_xml(xml_text: str) -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("PubMed efetch XML parse failed: %s", exc)
        return []
    out: list[dict[str, Any]] = []
    for art in root.findall(".//PubmedArticle"):
        try:
            out.append(_parse_one_pubmed_article(art))
        except Exception as exc:  # noqa: BLE001 - never let one bad record kill the batch
            logger.debug("skipping malformed PubMed article: %s", exc)
    return out


def _text(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return "".join(node.itertext()).strip()


def _parse_one_pubmed_article(art: ET.Element) -> dict[str, Any]:
    pmid = _text(art.find(".//MedlineCitation/PMID")) or None
    title = _text(art.find(".//Article/ArticleTitle"))
    journal = _text(art.find(".//Article/Journal/ISOAbbreviation")) or _text(
        art.find(".//MedlineJournalInfo/MedlineTA")
    )

    issns = []
    for tag in (".//Article/Journal/ISSN", ".//MedlineJournalInfo/ISSNLinking"):
        for node in art.findall(tag):
            val = (node.text or "").strip()
            if val:
                issns.append(val)

    pub_types = [(_text(n)) for n in art.findall(".//PublicationTypeList/PublicationType") if _text(n)]
    mesh = [(_text(n)) for n in art.findall(".//MeshHeadingList/MeshHeading/DescriptorName") if _text(n)]

    abstract_parts = []
    for node in art.findall(".//Article/Abstract/AbstractText"):
        label = (node.get("Label") or "").strip()
        body = "".join(node.itertext()).strip()
        if not body:
            continue
        abstract_parts.append(f"{label}: {body}" if label else body)
    abstract = "\n".join(abstract_parts)

    authors = 0
    first_author: str | None = None
    for a in art.findall(".//Article/AuthorList/Author"):
        if a.find("LastName") is not None or a.find("CollectiveName") is not None:
            authors += 1
            if first_author is None:
                last = _text(a.find("LastName"))
                if last:
                    first_author = last
                else:
                    collective = _text(a.find("CollectiveName"))
                    if collective:
                        first_author = collective

    doi = None
    for tag in (".//Article/ELocationID[@EIdType='doi']", ".//PubmedData/ArticleIdList/ArticleId[@IdType='doi']"):
        node = art.find(tag)
        if node is not None and (node.text or "").strip():
            doi = (node.text or "").strip().lower()
            break

    pub_date = _pubmed_pub_date(art)
    entry_date = _pubmed_history_date(art, ("entrez", "pubmed"))
    year = None
    for candidate in (pub_date, entry_date):
        if candidate:
            year = int(candidate[:4])
            break

    is_preprint = any("preprint" in pt.lower() for pt in pub_types)

    return {
        "source": "pubmed",
        "pmid": pmid,
        "doi": doi,
        "title": title,
        "journal": journal,
        "issns": issns,
        "year": year,
        "pub_date": pub_date,
        "entry_date": entry_date or pub_date,
        "authors": authors,
        "first_author": first_author,
        "publication_types": pub_types,
        "mesh": mesh,
        "abstract": abstract,
        "is_preprint": is_preprint,
    }


def _pubmed_pub_date(art: ET.Element) -> str | None:
    pd = art.find(".//Article/Journal/JournalIssue/PubDate")
    if pd is None:
        return None
    year = _text(pd.find("Year"))
    if not year:
        medline = _text(pd.find("MedlineDate"))
        m = re.search(r"\d{4}", medline)
        return m.group(0) if m else None
    month_raw = _text(pd.find("Month"))
    day_raw = _text(pd.find("Day"))
    month = _month_to_int(month_raw)
    if month is None:
        return year
    if day_raw.isdigit():
        return f"{year}-{month:02d}-{int(day_raw):02d}"
    return f"{year}-{month:02d}-01"


def _pubmed_history_date(art: ET.Element, statuses: tuple[str, ...]) -> str | None:
    for status in statuses:
        node = art.find(f".//PubmedData/History/PubMedPubDate[@PubStatus='{status}']")
        if node is None:
            continue
        year = _text(node.find("Year"))
        if not year:
            continue
        month = _month_to_int(_text(node.find("Month"))) or 1
        day_raw = _text(node.find("Day"))
        day = int(day_raw) if day_raw.isdigit() else 1
        return f"{year}-{month:02d}-{day:02d}"
    return None


def _month_to_int(value: str) -> int | None:
    value = (value or "").strip()
    if not value:
        return None
    if value.isdigit():
        n = int(value)
        return n if 1 <= n <= 12 else None
    return _MONTHS.get(value[:3].lower())


# ── Europe PMC ───────────────────────────────────────────────────────────────

def europepmc_search(
    query: str,
    *,
    page_size: int = 100,
    timeout: int = 30,
) -> list[dict[str, Any]]:
    """Search Europe PMC (resultType=core) and return normalized article dicts."""
    params = {
        "query": query,
        "resultType": "core",
        "pageSize": int(page_size),
        "format": "json",
    }
    try:
        resp = requests.get(
            _EUROPEPMC_SEARCH,
            params=params,
            timeout=timeout,
            headers={"User-Agent": _USER_AGENT.format(email="anonymous")},
        )
        if resp.status_code != 200:
            logger.warning("Europe PMC HTTP %s: %s", resp.status_code, resp.text[:160])
            return []
        results = resp.json().get("resultList", {}).get("result", [])
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Europe PMC search failed: %s", exc)
        return []

    out: list[dict[str, Any]] = []
    for r in results:
        try:
            out.append(_parse_europepmc(r))
        except Exception as exc:  # noqa: BLE001
            logger.debug("skipping malformed Europe PMC record: %s", exc)
    return out


def _parse_europepmc(r: dict[str, Any]) -> dict[str, Any]:
    journal_info = r.get("journalInfo") or {}
    journal_obj = journal_info.get("journal") or {}
    issns = [v for v in (journal_obj.get("issn"), journal_obj.get("essn")) if v]

    pub_types = (r.get("pubTypeList") or {}).get("pubType") or []
    if isinstance(pub_types, str):
        pub_types = [pub_types]

    mesh = []
    for mh in ((r.get("meshHeadingList") or {}).get("meshHeading") or []):
        name = mh.get("descriptorName")
        if name:
            mesh.append(name)

    authors = 0
    first_author: str | None = None
    author_list = (r.get("authorList") or {}).get("author") or []
    if author_list:
        authors = len(author_list)
        first = author_list[0] if isinstance(author_list[0], dict) else {}
        first_author = (
            (first.get("lastName") or "").strip()
            or (first.get("fullName") or "").strip().split(",")[0].strip()
            or None
        )
    elif r.get("authorString"):
        parts = [a.strip() for a in str(r["authorString"]).split(",") if a.strip()]
        authors = len(parts)
        if parts:
            # authorString is "Wright DE, Smith J, Jones A" — first token has trailing initials.
            first_author = parts[0].split(" ")[0] or None

    doi = (r.get("doi") or "").strip().lower() or None
    pub_date = r.get("firstPublicationDate") or None
    year = None
    if r.get("pubYear"):
        try:
            year = int(str(r["pubYear"])[:4])
        except ValueError:
            year = None

    is_preprint = str(r.get("source") or "").upper() == "PPR" or any(
        "preprint" in str(pt).lower() for pt in pub_types
    )

    return {
        "source": "europepmc",
        "pmid": r.get("pmid"),
        "doi": doi,
        "title": (r.get("title") or "").strip(),
        "journal": journal_obj.get("isoabbreviation") or journal_obj.get("title") or "",
        "issns": issns,
        "year": year,
        "pub_date": pub_date,
        "entry_date": pub_date,
        "authors": authors,
        "first_author": first_author,
        "publication_types": list(pub_types),
        "mesh": mesh,
        "abstract": (r.get("abstractText") or "").strip(),
        "is_preprint": is_preprint,
    }


# ── Altmetric ────────────────────────────────────────────────────────────────

_ALTMETRIC_MIN_INTERVAL = 1.1  # seconds; free endpoint is ~1 req/s
_last_altmetric_call = [0.0]


def altmetric_by_doi(doi: str, *, timeout: int = 30) -> dict[str, Any] | None:
    """Return {'score', 'percentile'} for a DOI, or None when Altmetric has no record.

    ``percentile`` is the age-and-journal-normalized percentile (0-100) when
    available, which is the signal we want — a 3-week-old paper isn't penalized
    against a 10-month-old one. A 404 means zero attention, returned as None.
    """
    doi = (doi or "").strip().lower()
    if not doi:
        return None
    # polite client-side throttle
    wait = _ALTMETRIC_MIN_INTERVAL - (time.monotonic() - _last_altmetric_call[0])
    if wait > 0:
        time.sleep(wait)
    try:
        resp = requests.get(
            f"{_ALTMETRIC_DOI}{doi}",
            timeout=timeout,
            headers={"User-Agent": _USER_AGENT.format(email="anonymous")},
        )
        _last_altmetric_call[0] = time.monotonic()
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            logger.debug("Altmetric HTTP %s for %s", resp.status_code, doi)
            return None
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.debug("Altmetric lookup failed for %s: %s", doi, exc)
        return None

    context = data.get("context") or {}
    percentile = None
    for key in ("similar_age_journal_3m", "similar_age_3m", "journal", "all"):
        ctx = context.get(key) or {}
        pct = ctx.get("pct")
        if pct is not None:
            try:
                percentile = float(pct)
                break
            except (TypeError, ValueError):
                continue
    score = None
    try:
        score = float(data.get("score")) if data.get("score") is not None else None
    except (TypeError, ValueError):
        score = None
    return {"score": score, "percentile": percentile}


# ── SCImago quartile (offline CSV join) ──────────────────────────────────────

_sjr_cache: dict[str, dict[str, str]] = {}
_sjr_missing_logged: set[str] = set()
_QUARTILE_RANK = {"Q1": 4, "Q2": 3, "Q3": 2, "Q4": 1}


def _normalize_issn(value: str) -> str:
    """Strip to the 8-char ISSN core (digits + optional trailing X), uppercased."""
    return re.sub(r"[^0-9xX]", "", str(value or "")).upper()


def _find_sjr_csv(repo_root: Path | None) -> Path | None:
    if repo_root is None:
        return None
    assets = Path(repo_root) / "assets"
    if not assets.exists():
        return None
    matches = sorted(assets.glob("sjr_*.csv"))
    return matches[-1] if matches else None


def _load_sjr_map(csv_path: Path) -> dict[str, str]:
    key = str(csv_path)
    if key in _sjr_cache:
        return _sjr_cache[key]
    mapping: dict[str, str] = {}
    try:
        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            sample = f.read(4096)
            f.seek(0)
            delimiter = ";" if sample.count(";") >= sample.count(",") else ","
            reader = csv.DictReader(f, delimiter=delimiter)
            # Resolve column names case-insensitively.
            cols = {c.lower().strip(): c for c in (reader.fieldnames or [])}
            issn_col = cols.get("issn")
            q_col = cols.get("sjr best quartile") or cols.get("best quartile")
            if not issn_col or not q_col:
                logger.warning("SCImago CSV %s missing Issn/Quartile columns", csv_path)
                _sjr_cache[key] = mapping
                return mapping
            for row in reader:
                quartile = (row.get(q_col) or "").strip().upper()
                if quartile not in _QUARTILE_RANK:
                    continue
                for token in re.split(r"[,\s]+", row.get(issn_col) or ""):
                    issn8 = _normalize_issn(token)
                    if len(issn8) != 8:
                        continue
                    prev = mapping.get(issn8)
                    if prev is None or _QUARTILE_RANK[quartile] > _QUARTILE_RANK[prev]:
                        mapping[issn8] = quartile
    except OSError as exc:
        logger.warning("Could not read SCImago CSV %s: %s", csv_path, exc)
    _sjr_cache[key] = mapping
    return mapping


def sjr_quartile(
    issn: str,
    *,
    csv_path: Path | None = None,
    repo_root: Path | None = None,
) -> str | None:
    """Return 'Q1'..'Q4' for an ISSN from the SCImago CSV, or None if unknown/missing."""
    path = Path(csv_path) if csv_path else _find_sjr_csv(repo_root)
    if path is None or not path.exists():
        marker = str(path or repo_root)
        if marker not in _sjr_missing_logged:
            logger.warning("SCImago CSV not found (looked near %s); quartile signal disabled", marker)
            _sjr_missing_logged.add(marker)
        return None
    issn8 = _normalize_issn(issn)
    if len(issn8) != 8:
        return None
    return _load_sjr_map(path).get(issn8)
