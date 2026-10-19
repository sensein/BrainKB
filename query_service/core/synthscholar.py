"""Ingesting a SynthScholar review from its output directory.

A SynthScholar run (the synthscholar skill: `run_local_review.py` +
`export_review.py`) leaves an output directory: `review.json` (the review in the
synthscholar package's result format), `review.ttl` (its RDF), the manuscript, PDF,
figures, tables and verification reports. Uploading that directory is an ingest
like any other, with three additions:

  * the review's graph is named by the review's own id —
    https://brainkb.org/synthscholar/reviews/<protocol.review_id>/ — and is
    registered in the chosen space, once;
  * the files (everything but intermediate `work/`) are kept, in Postgres, and the
    graph links to them: alongside `review.ttl`, an import record goes into the
    review's graph (who imported what, when, each file with its media type, size
    and sha256, and what was left out);
  * a summary of the review is kept for listing and viewing.

`review.json` is read as plain JSON in the package's format — never validated
through the installed package — so a review written by a newer skill still ingests.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import posixpath
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional
from urllib.parse import quote

from rdflib import Graph, Literal, Namespace, URIRef, RDF, RDFS, XSD
from rdflib.namespace import DCTERMS, PROV

from core.database import get_db_connection

GRAPH_BASE = "https://brainkb.org/synthscholar/reviews/"
SCHEMA = Namespace("https://schema.org/")

REQUIRED_FILES = ("review.json", "review.ttl")
EXCLUDED_DIRS = {"work", ".git", "__pycache__", "node_modules", ".ipynb_checkpoints", ".venv"}
EXCLUDED_NAMES = {".DS_Store", "Thumbs.db"}
MAX_FILE_BYTES = 200 * 1024 * 1024
MAX_TOTAL_BYTES = 600 * 1024 * 1024
MAX_FILES = 1000              # Starlette's multipart default (max_files)
MAX_LEFT_OUT = 5000
# Public base of this service's API, for the file links in the graph
# (e.g. https://queryservice.brainkb.org). Without it, files are identified by IRI only.
PUBLIC_API_BASE = os.getenv("SYNTHSCHOLAR_PUBLIC_API_BASE", "").rstrip("/")

_MEDIA = {
    ".ttl": "text/turtle", ".jsonld": "application/ld+json", ".json": "application/json",
    ".md": "text/markdown", ".csv": "text/csv", ".tsv": "text/tab-separated-values",
    ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".pdf": "application/pdf", ".bib": "application/x-bibtex", ".tex": "application/x-tex",
    ".txt": "text/plain", ".html": "text/html", ".xml": "application/xml",
}


class ImportError_(ValueError):
    """The upload is not an ingestible SynthScholar output directory."""


def graph_iri_for(review_id: str) -> str:
    return f"{GRAPH_BASE}{quote(review_id, safe='')}/"


def media_type(path: str) -> str:
    ext = posixpath.splitext(path)[1].lower()
    return _MEDIA.get(ext) or mimetypes.guess_type(path)[0] or "application/octet-stream"


def kind_of(path: str) -> str:
    """What a file IS in the review, for the UI and the import record."""
    name = posixpath.basename(path)
    exact = {
        "review.json": "review_result", "review.pdf": "manuscript_pdf",
        "review.manuscript.md": "manuscript_markdown", "review.manuscript.json": "manuscript_sections",
        "review.tex": "manuscript_tex", "review.md": "review_markdown",
        "review.ttl": "rdf", "review.jsonld": "rdf", "review.bib": "bibliography",
        "protocol.json": "protocol", "search_log.json": "search_log",
        "url_verification.json": "url_verification", "README.md": "readme",
    }
    if path in exact:
        return exact[path]
    if name.startswith("review.citations.") or name.startswith("review.references."):
        return "citation_verification"
    if path.startswith("figures/"):
        return "figure_data" if name.endswith(".json") else "figure"
    ext = posixpath.splitext(name)[1].lower()
    return {".csv": "table", ".tsv": "table", ".svg": "figure", ".png": "figure", ".jpg": "figure",
            ".jpeg": "figure", ".md": "report", ".json": "data", ".jsonld": "data", ".pdf": "document"}.get(ext, "other")


def clean_path(path: str) -> Optional[str]:
    """A safe relative POSIX path, or None (absolute, traversal, empty)."""
    p = (path or "").replace("\\", "/").strip()
    if not p or p.startswith("/") or ":" in p.split("/", 1)[0]:
        return None
    parts = [x for x in p.split("/") if x not in ("", ".")]
    if not parts or any(x == ".." for x in parts):
        return None
    return "/".join(parts)


# ── choosing what to keep ────────────────────────────────────────────────

@dataclass
class ImportFile:
    path: str            # relative to the review's root (the folder holding review.json)
    content: bytes
    kind: str
    media_type: str
    sha256: str

    @property
    def size(self) -> int:
        return len(self.content)


@dataclass
class ImportPlan:
    files: list[ImportFile] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    root: str = ""

    def get(self, path: str) -> Optional[ImportFile]:
        return next((f for f in self.files if f.path == path), None)

    def manifest(self) -> dict:
        return {
            "root": self.root,
            "file_count": len(self.files),
            "total_bytes": sum(f.size for f in self.files),
            "files": [{"path": f.path, "kind": f.kind, "media_type": f.media_type,
                       "size_bytes": f.size, "sha256": f.sha256} for f in self.files],
            "skipped": self.skipped,
        }


def plan_import(uploads: Iterable[tuple[str, bytes]], client_skipped: Iterable = ()) -> ImportPlan:
    """Choose what to keep from an uploaded output directory.

    `uploads` are (relative path as sent by the browser, content); the review's
    root is the folder holding review.json and everything is stored relative to
    it. `client_skipped` lists what the client chose not to upload ({path, reason})
    — recorded as left out, never trusted as content."""
    items, plan = [], ImportPlan()
    for raw_path, content in uploads:
        p = clean_path(raw_path)
        if p is None:
            plan.skipped.append({"path": str(raw_path)[:300], "reason": "unsafe path"})
            continue
        items.append((p, content))
    if len(items) > MAX_FILES:
        raise ImportError_(f"too many files ({len(items)}; at most {MAX_FILES})")
    roots = sorted((posixpath.dirname(p) for p, _ in items if posixpath.basename(p) == "review.json"), key=len)
    if not roots:
        raise ImportError_("no review.json in the selected folder — choose a SynthScholar output directory")
    plan.root = roots[0]
    prefix = f"{plan.root}/" if plan.root else ""
    total = 0
    for p, content in items:
        if prefix and not p.startswith(prefix):
            plan.skipped.append({"path": p, "reason": "outside the review's folder"})
            continue
        rel = p[len(prefix):]
        parts = rel.split("/")
        if parts[-1] in EXCLUDED_NAMES:
            continue
        if any(x in EXCLUDED_DIRS for x in parts[:-1]):
            plan.skipped.append({"path": rel, "reason": f"intermediate files ({parts[0]}/)"})
            continue
        if len(content) > MAX_FILE_BYTES:
            plan.skipped.append({"path": rel, "reason": f"larger than {MAX_FILE_BYTES // (1024 * 1024)} MB"})
            continue
        total += len(content)
        if total > MAX_TOTAL_BYTES:
            raise ImportError_(f"the review's files exceed {MAX_TOTAL_BYTES // (1024 * 1024)} MB in total")
        plan.files.append(ImportFile(path=rel, content=content, kind=kind_of(rel), media_type=media_type(rel),
                                     sha256=hashlib.sha256(content).hexdigest()))
    for item in list(client_skipped)[:MAX_LEFT_OUT]:
        p = clean_path(str(item.get("path", ""))) if isinstance(item, dict) else None
        if p:
            plan.skipped.append({"path": p, "reason": str(item.get("reason") or "left out before upload")[:120],
                                 "by": "client"})
    for required in REQUIRED_FILES:
        if not plan.get(required):
            hint = " — export the review with --formats ttl" if required == "review.ttl" else ""
            raise ImportError_(f"{required} is missing from the output folder{hint}")
    plan.files.sort(key=lambda f: f.path)
    return plan


# ── reading review.json (the package's result format, as plain JSON) ──────

def read_review(plan: ImportPlan) -> dict:
    f = plan.get("review.json")
    if f is None:
        raise ImportError_("review.json is missing from the output folder")
    try:
        data = json.loads(f.content.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise ImportError_(f"review.json is not valid JSON: {str(e)[:200]}")
    if not isinstance(data, dict) or not isinstance(data.get("protocol"), dict):
        raise ImportError_("review.json is not a SynthScholar review (no protocol)")
    return data


def review_id_of(review: dict) -> str:
    rid = str((review.get("protocol") or {}).get("review_id") or "").strip()
    if not rid:
        raise ImportError_("review.json has no protocol.review_id — the review's graph is named by it")
    if len(rid) > 200 or clean_path(rid) != rid or "/" in rid:
        raise ImportError_(f"protocol.review_id {rid[:80]!r} is not a usable identifier")
    return rid


def _s(v: Any) -> str:
    return v if isinstance(v, str) else ""


def _rob_overall(rob: Any) -> str:
    if isinstance(rob, dict):
        return _s(rob.get("overall") or rob.get("overall_rating") or rob.get("overall_risk"))
    if isinstance(rob, str):   # some runs store the assessment as its Python repr
        m = re.search(r"""['"]overall(?:_rating|_risk)?['"]\s*:\s*['"]([^'"]{1,60})['"]""", rob)
        if m:
            return m.group(1)
    return ""


def summary_of(review: dict) -> dict:
    """What a listing needs."""
    proto = review.get("protocol") or {}
    flow = review.get("flow") if isinstance(review.get("flow"), dict) else None
    return {
        "title": _s(proto.get("title"))[:500],
        "research_question": _s(review.get("research_question"))[:2000],
        "run_completed_at": _s(review.get("timestamp")) or None,
        "included_count": len(review.get("included_articles") or []),
        "flow": flow,
    }


def detail_of(review: dict) -> dict:
    """What the review page shows. Long texts are kept; per-article full texts and
    abstracts are not (they live in review.json, which is kept as a file)."""
    articles = []
    for a in review.get("included_articles") or []:
        if not isinstance(a, dict):
            continue
        articles.append({
            "pmid": _s(a.get("pmid")), "title": _s(a.get("title")), "authors": _s(a.get("authors")),
            "year": str(a.get("year") or ""), "journal": _s(a.get("journal")), "doi": _s(a.get("doi")),
            "source": _s(a.get("source")), "inclusion_status": _s(a.get("inclusion_status")),
            "rob_overall": _rob_overall(a.get("risk_of_bias")),
            "full_text": bool(a.get("full_text")), "full_text_source": _s(a.get("full_text_source")),
        })
    basis: dict = defaultdict(Counter)
    ft_sources: Counter = Counter()
    log = [e for e in (review.get("screening_log") or []) if isinstance(e, dict)]
    for e in log:
        basis[str(e.get("stage") or "")][str(e.get("assessed_on") or "")] += 1
        if e.get("assessed_on") == "full_text" and e.get("full_text_source"):
            ft_sources[str(e["full_text_source"])] += 1
    routes = Counter((a["full_text_source"] or "none") if a["full_text"] else "abstract only" for a in articles)
    grade = review.get("grade_assessments")
    grade_items = list(grade.items()) if isinstance(grade, dict) else []
    return {
        "research_question": _s(review.get("research_question")),
        "structured_abstract": _s(review.get("structured_abstract")),
        "introduction_text": _s(review.get("introduction_text")),
        "synthesis_text": _s(review.get("synthesis_text")),
        "bias_assessment": _s(review.get("bias_assessment")),
        "limitations": _s(review.get("limitations")),
        "conclusions_text": _s(review.get("conclusions_text")),
        "search_queries": [q for q in (review.get("search_queries") or []) if isinstance(q, str)],
        "flow": review.get("flow") if isinstance(review.get("flow"), dict) else None,
        "included_articles": articles,
        "grade_assessments": [
            {"outcome": str(k), "overall_certainty": _s((g or {}).get("overall_certainty")), "summary": _s((g or {}).get("summary"))}
            for k, g in grade_items],
        "screening": {
            "decisions": len(log),
            "basis_by_stage": {stage: dict(c) for stage, c in basis.items()},
            "full_text_sources": dict(ft_sources),
        },
        "retrieval": {
            "included": len(articles),
            "with_full_text": sum(1 for a in articles if a["full_text"]),
            "abstract_only": sum(1 for a in articles if not a["full_text"]),
            "routes": dict(routes),
        },
    }


def local_run_provenance(plan: ImportPlan) -> dict:
    """What a run keeps in its sidecar files: the exact query, count and date per
    database (search_log.json), citation and URL verification, the manuscript's own
    check. Numbers and queries only — never the local paths these files may contain."""
    def load(path):
        f = plan.get(path)
        if f is None:
            return None
        try:
            return json.loads(f.content.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
    out: dict = {}
    log = load("search_log.json")
    if isinstance(log, dict):
        out["search_log"] = [
            {"database": db, "query": str(e.get("query") or "")[:4000], "count": e.get("count"), "date": e.get("date")}
            for db, e in log.items() if isinstance(e, dict)]
    cites = load("review.citations.json")
    if isinstance(cites, dict) and isinstance(cites.get("summary"), dict):
        def plain(v):
            if isinstance(v, (int, float, bool)) or (isinstance(v, str) and len(v) < 200 and "/" not in v):
                return True
            if isinstance(v, dict):
                return all(isinstance(x, (int, float, bool, str)) for x in v.values())
            if isinstance(v, list):
                return len(v) <= 50 and all(isinstance(x, (int, float, str)) for x in v)
            return False
        out["citation_verification"] = {k: v for k, v in cites["summary"].items() if plain(v)}
    urls = load("url_verification.json")
    if isinstance(urls, dict) and urls:
        statuses = [u.get("status") for u in urls.values() if isinstance(u, dict)]
        checked = [str(u["checked_at"]) for u in urls.values() if isinstance(u, dict) and u.get("checked_at")]
        out["url_verification"] = {
            "checked": len(statuses),
            "reachable": sum(1 for s in statuses if isinstance(s, int) and s < 400),
            "statuses": dict(Counter(str(s) for s in statuses)),
            "checked_at": max(checked) if checked else None,
        }
    check = load("review.manuscript.check.json")
    if isinstance(check, dict):
        out["manuscript_check"] = {k: check.get(k) for k in ("body_words", "word_target", "estimated_pages",
                                                              "page_limit", "figures", "references") if k in check}
    return out


# ── the import record (goes into the review's graph with review.ttl) ──────

def file_iri(review_id: str, path: str) -> str:
    return f"{graph_iri_for(review_id)}files/{quote(path, safe='/')}"


def file_url(review_id: str, path: str) -> Optional[str]:
    if not PUBLIC_API_BASE:
        return None
    return f"{PUBLIC_API_BASE}/api/synthscholar/reviews/{quote(review_id, safe='')}/files/{quote(path, safe='/')}"


def import_record_ttl(review_id: str, plan: ImportPlan, *, agent: URIRef, imported_at: str,
                      space_slug: str, summary: dict) -> str:
    """PROV-O record of the import, linking every kept file: an import activity that
    used the output directory's files (each a prov:Entity / schema:MediaObject with
    its media type, size and sha256, and where to download it) and was associated
    with the person who ingested it. IRIs only — no blank nodes, since the graph is
    append-only."""
    g = Graph()
    for prefix, ns in (("prov", PROV), ("dcterms", DCTERMS), ("schema", SCHEMA)):
        g.bind(prefix, ns)
    base = graph_iri_for(review_id)
    act = URIRef(f"{base}import")
    g.add((act, RDF.type, PROV.Activity))
    g.add((act, RDFS.label, Literal("Import of a SynthScholar review output directory")))
    g.add((act, PROV.startedAtTime, Literal(imported_at, datatype=XSD.dateTime)))
    g.add((act, PROV.wasAssociatedWith, agent))
    g.add((act, DCTERMS.identifier, Literal(review_id)))
    g.add((act, SCHEMA.isPartOf, Literal(space_slug)))
    if summary.get("title"):
        g.add((act, DCTERMS.title, Literal(summary["title"])))
    if summary.get("run_completed_at"):
        g.add((act, DCTERMS.date, Literal(summary["run_completed_at"])))
    for f in plan.files:
        e = URIRef(file_iri(review_id, f.path))
        g.add((act, PROV.used, e))
        g.add((e, RDF.type, PROV.Entity))
        g.add((e, RDF.type, SCHEMA.MediaObject))
        g.add((e, SCHEMA.name, Literal(f.path)))
        g.add((e, DCTERMS.type, Literal(f.kind)))
        g.add((e, SCHEMA.encodingFormat, Literal(f.media_type)))
        g.add((e, SCHEMA.contentSize, Literal(f.size, datatype=XSD.integer)))
        g.add((e, SCHEMA.sha256, Literal(f.sha256)))
        url = file_url(review_id, f.path)
        if url:
            g.add((e, SCHEMA.contentUrl, URIRef(url)))
    left = [s for s in plan.skipped]
    if left:
        reasons = Counter(s["reason"] for s in left)
        g.add((act, RDFS.comment, Literal(
            f"Left out {len(left)} file(s): " + "; ".join(f"{n} — {r}" for r, n in reasons.most_common()))))
    return g.serialize(format="turtle")


# ── storage ──────────────────────────────────────────────────────────────

_TABLES = """
CREATE TABLE IF NOT EXISTS synthscholar_reviews (
    review_id     TEXT PRIMARY KEY,
    graph_iri     TEXT NOT NULL UNIQUE,
    space_slug    TEXT NOT NULL,
    title         TEXT NOT NULL DEFAULT '',
    owner_email   TEXT NOT NULL,
    imported_at   TIMESTAMPTZ NOT NULL,
    job_id        TEXT,
    summary       JSONB NOT NULL,
    detail        JSONB NOT NULL,
    manifest      JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS synthscholar_files (
    review_id     TEXT NOT NULL REFERENCES synthscholar_reviews(review_id) ON DELETE CASCADE,
    path          TEXT NOT NULL,
    kind          TEXT NOT NULL,
    media_type    TEXT NOT NULL,
    size_bytes    BIGINT NOT NULL,
    sha256        TEXT NOT NULL,
    content       BYTEA NOT NULL,
    PRIMARY KEY (review_id, path)
);
"""
_tables_ready = False


async def ensure_tables() -> None:
    global _tables_ready
    if _tables_ready:
        return
    async with get_db_connection() as conn:
        await conn.execute(_TABLES)
    _tables_ready = True


async def review_exists(review_id: str) -> bool:
    await ensure_tables()
    async with get_db_connection() as conn:
        return bool(await conn.fetchval("SELECT 1 FROM synthscholar_reviews WHERE review_id = $1", review_id))


async def save_review(*, review_id: str, space_slug: str, owner_email: str, imported_at: datetime,
                      summary: dict, detail: dict, manifest: dict, plan: ImportPlan) -> None:
    await ensure_tables()
    async with get_db_connection() as conn:
        async with conn.transaction():
            await conn.execute(
                """INSERT INTO synthscholar_reviews
                   (review_id, graph_iri, space_slug, title, owner_email, imported_at, summary, detail, manifest)
                   VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb,$9::jsonb)""",
                review_id, graph_iri_for(review_id), space_slug, summary.get("title") or review_id, owner_email,
                imported_at, json.dumps(summary), json.dumps(detail), json.dumps(manifest))
            await conn.executemany(
                """INSERT INTO synthscholar_files (review_id, path, kind, media_type, size_bytes, sha256, content)
                   VALUES ($1,$2,$3,$4,$5,$6,$7)""",
                [(review_id, f.path, f.kind, f.media_type, f.size, f.sha256, f.content) for f in plan.files])


async def set_job(review_id: str, job_id: str) -> None:
    async with get_db_connection() as conn:
        await conn.execute("UPDATE synthscholar_reviews SET job_id = $2 WHERE review_id = $1", review_id, job_id)


async def delete_review(review_id: str) -> None:
    async with get_db_connection() as conn:
        await conn.execute("DELETE FROM synthscholar_reviews WHERE review_id = $1", review_id)


def _row(r, *, with_detail: bool = False) -> dict:
    out = {
        "review_id": r["review_id"], "graph_iri": r["graph_iri"], "space_slug": r["space_slug"],
        "title": r["title"], "owner_email": r["owner_email"],
        "imported_at": r["imported_at"].isoformat() if r["imported_at"] else None,
        "job_id": r["job_id"], **json.loads(r["summary"]),
    }
    if with_detail:
        out["detail"] = json.loads(r["detail"])
        out["manifest"] = json.loads(r["manifest"])
    return out


async def list_reviews() -> list[dict]:
    await ensure_tables()
    async with get_db_connection() as conn:
        rows = await conn.fetch("""SELECT review_id, graph_iri, space_slug, title, owner_email, imported_at, job_id, summary
                                   FROM synthscholar_reviews ORDER BY imported_at DESC""")
    return [_row(r) for r in rows]


async def get_review(review_id: str) -> Optional[dict]:
    await ensure_tables()
    async with get_db_connection() as conn:
        r = await conn.fetchrow("SELECT * FROM synthscholar_reviews WHERE review_id = $1", review_id)
        if r is None:
            return None
        files = await conn.fetch("""SELECT path, kind, media_type, size_bytes, sha256 FROM synthscholar_files
                                    WHERE review_id = $1 ORDER BY path""", review_id)
    out = _row(r, with_detail=True)
    out["files"] = [dict(f) for f in files]
    return out


async def get_file(review_id: str, path: str) -> Optional[dict]:
    await ensure_tables()
    async with get_db_connection() as conn:
        r = await conn.fetchrow("""SELECT r.space_slug, f.path, f.media_type, f.sha256, f.content
                                   FROM synthscholar_files f JOIN synthscholar_reviews r USING (review_id)
                                   WHERE f.review_id = $1 AND f.path = $2""", review_id, path)
    return dict(r) if r else None


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ── querying a review (from its stored review.json) ────────────────────────
# Answers the questions a review is asked after the fact — which studies were
# read in full, by which route; what each screening decision was judged on and
# why studies were excluded; what evidence supports a claim; which reviews include
# a study — from the review.json kept with it, so every ingested review can be
# queried without re-ingesting. Read access is the caller's (router).

_REASON_CODE = re.compile(r"^\s*\[([A-Za-z]{1,6}\d{0,3}[a-z]?)\]")
MAX_PAGE = 200


def _norm(s: Any) -> str:
    return str(s or "").strip().lower()


def _doi(s: Any) -> str:
    return re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", _norm(s))


def _page(items: list, limit: int, offset: int) -> dict:
    limit = max(1, min(int(limit or 50), MAX_PAGE))
    offset = max(0, int(offset or 0))
    return {"total": len(items), "offset": offset, "limit": limit, "items": items[offset:offset + limit]}


def _match(q: str, *fields: Any) -> bool:
    return not q or any(q in _norm(f) for f in fields)


def query_studies(review: dict, *, q: str = "", full_text: Optional[bool] = None, source: str = "",
                  rob: str = "", year_from: Optional[int] = None, year_to: Optional[int] = None,
                  with_abstract: bool = False, limit: int = 50, offset: int = 0) -> dict:
    """Included studies, filtered: text (title/authors/journal/doi/pmid/keywords),
    read in full or abstract only, full-text route, risk-of-bias rating, year range."""
    q, source, rob = _norm(q), _norm(source), _norm(rob)
    out = []
    for a in review.get("included_articles") or []:
        if not isinstance(a, dict):
            continue
        has_ft = bool(a.get("full_text"))
        if full_text is not None and has_ft != full_text:
            continue
        if source and source not in _norm(a.get("full_text_source")):
            continue
        rating = _rob_overall(a.get("risk_of_bias"))
        if rob and rob not in rating.lower():
            continue
        try:
            year = int(str(a.get("year") or "")[:4])
        except ValueError:
            year = None
        if (year_from and (year is None or year < year_from)) or (year_to and (year is None or year > year_to)):
            continue
        if not _match(q, a.get("title"), a.get("authors"), a.get("journal"), a.get("doi"), a.get("pmid"), a.get("keywords")):
            continue
        row = {"pmid": _s(a.get("pmid")), "doi": _s(a.get("doi")), "title": _s(a.get("title")),
               "authors": _s(a.get("authors")), "year": str(a.get("year") or ""), "journal": _s(a.get("journal")),
               "read": "full text" if has_ft else "abstract only", "full_text_source": _s(a.get("full_text_source")),
               "rob_overall": rating, "quality_score": a.get("quality_score")}
        if with_abstract:
            row["abstract"] = _s(a.get("abstract"))[:3000]
        out.append(row)
    return _page(out, limit, offset)


def query_screening(review: dict, *, stage: str = "", decision: str = "", assessed_on: str = "",
                    reason: str = "", q: str = "", pmid: str = "", limit: int = 50, offset: int = 0) -> dict:
    """The screening audit trail, filtered, with counts: per stage and decision, what
    the decisions were judged on, and exclusion reasons by criterion code ([EC2] …)."""
    stage, decision, assessed_on, reason, q = map(_norm, (stage, decision, assessed_on, reason, q))
    rows = []
    by_stage: dict = defaultdict(Counter)
    basis: dict = defaultdict(Counter)
    reasons: Counter = Counter()
    for e in review.get("screening_log") or []:
        if not isinstance(e, dict):
            continue
        if stage and _norm(e.get("stage")) != stage:
            continue
        if decision and _norm(e.get("decision")) != decision:
            continue
        if assessed_on and _norm(e.get("assessed_on")) != assessed_on:
            continue
        if pmid and _norm(e.get("pmid")) != _norm(pmid):
            continue
        if reason and reason not in _norm(e.get("reason")):
            continue
        if not _match(q, e.get("title"), e.get("reason"), e.get("pmid")):
            continue
        st, dec = str(e.get("stage") or ""), str(e.get("decision") or "")
        by_stage[st][dec] += 1
        basis[st][str(e.get("assessed_on") or "")] += 1
        if dec.lower() == "exclude":
            m = _REASON_CODE.match(str(e.get("reason") or ""))
            reasons[m.group(1) if m else (str(e.get("reason") or "")[:80] or "(no reason)")] += 1
        rows.append({"pmid": _s(e.get("pmid")), "title": _s(e.get("title")), "stage": st, "decision": dec,
                     "assessed_on": _s(e.get("assessed_on")), "full_text_source": _s(e.get("full_text_source")),
                     "reason": _s(e.get("reason"))[:1000]})
    return {**_page(rows, limit, offset),
            "counts": {"by_stage": {k: dict(v) for k, v in by_stage.items()},
                       "assessed_on": {k: dict(v) for k, v in basis.items()},
                       "exclusion_reasons": dict(reasons.most_common())}}


def query_evidence(review: dict, *, q: str = "", claim: str = "", pmid: str = "", grounded: Optional[bool] = None,
                   limit: int = 50, offset: int = 0) -> dict:
    """Evidence spans: the quoted text a review's claims rest on, with the study,
    section, relevance and whether the quote was matched in the source text."""
    q, claim = _norm(q), _norm(claim)
    out = []
    for e in review.get("evidence_spans") or []:
        if not isinstance(e, dict):
            continue
        if claim and claim not in _norm(e.get("claim")):
            continue
        if pmid and _norm(e.get("paper_pmid")) != _norm(pmid):
            continue
        g = str(e.get("grounded")).lower() in ("true", "1", "yes")
        if grounded is not None and g != grounded:
            continue
        if not _match(q, e.get("text"), e.get("claim"), e.get("paper_title")):
            continue
        out.append({"text": _s(e.get("text"))[:2000], "claim": _s(e.get("claim")), "paper_pmid": _s(e.get("paper_pmid")),
                    "paper_title": _s(e.get("paper_title")), "doi": _s(e.get("doi")), "section": _s(e.get("section")),
                    "relevance_score": e.get("relevance_score"), "grounded": g})
    return _page(out, limit, offset)


def study_in_review(review: dict, *, doi: str = "", pmid: str = "", title: str = "") -> list[dict]:
    """Where a study appears in one review: included, and/or each screening decision."""
    d, p, t = _doi(doi), _norm(pmid), _norm(title)

    def hit(rec_doi, rec_pmid, rec_title):
        return (d and _doi(rec_doi) == d) or (p and _norm(rec_pmid) == p) or (t and t in _norm(rec_title))
    found = []
    for a in review.get("included_articles") or []:
        if isinstance(a, dict) and hit(a.get("doi"), a.get("pmid"), a.get("title")):
            found.append({"as": "included", "pmid": _s(a.get("pmid")), "doi": _s(a.get("doi")), "title": _s(a.get("title")),
                          "read": "full text" if a.get("full_text") else "abstract only"})
    for e in review.get("screening_log") or []:
        if isinstance(e, dict) and hit("", e.get("pmid"), e.get("title")):
            found.append({"as": "screened", "pmid": _s(e.get("pmid")), "title": _s(e.get("title")), "stage": _s(e.get("stage")),
                          "decision": _s(e.get("decision")), "reason": _s(e.get("reason"))[:300]})
    return found


async def load_review_json(review_id: str) -> Optional[dict]:
    """The review's own review.json (kept with it), parsed — cached per worker by
    content hash, since one can run to tens of MB."""
    f = await get_file(review_id, "review.json")
    if f is None:
        return None
    key = f["sha256"]
    if key not in _REVIEW_CACHE:
        if len(_REVIEW_CACHE) >= _REVIEW_CACHE_SIZE:
            _REVIEW_CACHE.pop(next(iter(_REVIEW_CACHE)))
        _REVIEW_CACHE[key] = json.loads(bytes(f["content"]).decode("utf-8"))
    return _REVIEW_CACHE[key]


_REVIEW_CACHE: dict = {}
_REVIEW_CACHE_SIZE = int(os.getenv("SYNTHSCHOLAR_REVIEW_CACHE", "4"))


# Per-study records the review produced, by kind, and its own text sections.
RECORD_KINDS = {"charting": "data_charting_rubrics", "appraisal": "critical_appraisals", "narrative": "narrative_rows"}
TEXT_SECTIONS = {
    "research_question": "research_question", "abstract": "structured_abstract", "introduction": "introduction_text",
    "synthesis": "synthesis_text", "bias": "bias_assessment", "limitations": "limitations",
    "conclusions": "conclusions_text",
}


def _flat(v: Any, limit: int = 2000) -> Any:
    """A record value as plain JSON, long strings cut — records can nest deeply."""
    if isinstance(v, str):
        return v[:limit]
    if isinstance(v, (int, float, bool)) or v is None:
        return v
    if isinstance(v, list):
        return [_flat(x, limit) for x in v[:50]]
    if isinstance(v, dict):
        return {str(k): _flat(x, limit) for k, x in list(v.items())[:100]}
    return str(v)[:limit]


def _values_text(v: Any) -> str:
    """The answers in a record, as one lowercase string — values only: the charting
    form's questions are its field names, and matching them would match every record."""
    if isinstance(v, dict):
        return " ".join(_values_text(x) for x in v.values())
    if isinstance(v, list):
        return " ".join(_values_text(x) for x in v)
    return "" if v is None else str(v).lower()


def query_records(review: dict, kind: str, *, q: str = "", study: str = "", fields: str = "",
                  limit: int = 50, offset: int = 0) -> dict:
    """Per-study records — `charting` (the data-charting form's answers), `appraisal`
    (critical appraisal by domain) or `narrative` (narrative synthesis rows) — filtered
    by text in the record's answers or by study (source id, title, DOI or PMID), and
    trimmed to `fields` (comma-separated) when given. Lists the available fields."""
    key = RECORD_KINDS.get(_norm(kind))
    if key is None:
        raise ImportError_(f"kind must be one of {', '.join(RECORD_KINDS)}")
    records = [r for r in (review.get(key) or []) if isinstance(r, dict)]
    want = [f.strip() for f in fields.split(",") if f.strip()]
    q, study = _norm(q), _norm(study)
    available: Counter = Counter()
    out = []
    for r in records:
        available.update(r.keys())
        if study and not any(study == _norm(r.get(k)) or (k == "title" and study in _norm(r.get(k)))
                             for k in ("source_id", "title", "doi", "pmid")):
            continue
        if q and q not in _values_text(r):
            continue
        out.append(_flat({k: r.get(k) for k in want} if want else r))
    page = _page(out, limit, offset)
    page["fields"] = [k for k, _ in available.most_common()]
    return page


def review_text(review: dict, section: str = "") -> dict:
    """The review's own text: one section, or all of them (plus the search queries
    and the per-group analysis when there is one)."""
    sec = _norm(section)
    if sec and sec not in TEXT_SECTIONS and sec not in ("per_group", "search_queries"):
        raise ImportError_(f"section must be one of {', '.join([*TEXT_SECTIONS, 'per_group', 'search_queries'])}")
    out: dict = {}
    for name, key in TEXT_SECTIONS.items():
        if not sec or sec == name:
            out[name] = _s(review.get(key))
    if not sec or sec == "search_queries":
        out["search_queries"] = [x for x in (review.get("search_queries") or []) if isinstance(x, str)]
    if (not sec or sec == "per_group") and isinstance(review.get("per_group_analysis"), dict):
        out["per_group"] = _flat(review["per_group_analysis"], 4000)
    return out
