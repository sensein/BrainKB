"""Importing a locally-run SynthScholar review from its output directory.

A local run (the synthscholar skill, `run_local_review.py` + `export_review.py`)
leaves an output directory: `review.json` (the full PRISMAReviewResult) plus the
manuscript, PDF, figures, tables, RDF and verification reports. The UI uploads that
directory as-is; this module decides what is kept and how each file is labelled.

Kept: every file except intermediate work (`work/`, caches, VCS folders). Required:
`review.json`. Each kept file becomes a review artifact with a kind, a media type
and its sha256; the import manifest records what was kept and what was skipped and
why, so the import itself is provenance.
"""
from __future__ import annotations

import hashlib
import mimetypes
import posixpath
from dataclasses import dataclass, field
from typing import Iterable, Optional

REQUIRED_FILE = "review.json"
# intermediate scripts, raw records and text bundles — not part of the review
EXCLUDED_DIRS = {"work", ".git", "__pycache__", "node_modules", ".ipynb_checkpoints", ".venv"}
EXCLUDED_NAMES = {".DS_Store", "Thumbs.db"}
MAX_FILE_BYTES = 200 * 1024 * 1024
MAX_TOTAL_BYTES = 600 * 1024 * 1024
MAX_FILES = 1000          # Starlette's multipart default (max_files) — a request with more fails anyway

_MEDIA = {
    ".ttl": "text/turtle", ".jsonld": "application/ld+json", ".json": "application/json",
    ".md": "text/markdown", ".csv": "text/csv", ".tsv": "text/tab-separated-values",
    ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".pdf": "application/pdf", ".bib": "application/x-bibtex", ".tex": "application/x-tex",
    ".txt": "text/plain", ".html": "text/html", ".xml": "application/xml",
}


def media_type(path: str) -> str:
    ext = posixpath.splitext(path)[1].lower()
    return _MEDIA.get(ext) or mimetypes.guess_type(path)[0] or "application/octet-stream"


def kind_of(path: str) -> str:
    """What a file IS in the review, for the UI and the provenance record."""
    name = posixpath.basename(path)
    top = path.split("/", 1)[0] if "/" in path else ""
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
    if top == "figures":
        return "figure_data" if name.endswith(".json") else "figure"
    ext = posixpath.splitext(name)[1].lower()
    if ext in (".csv", ".tsv"):
        return "table"
    if ext in (".svg", ".png", ".jpg", ".jpeg"):
        return "figure"
    if ext == ".md":
        return "report"
    if ext in (".json", ".jsonld"):
        return "data"
    if ext == ".pdf":
        return "document"
    return "other"


def _clean(path: str) -> Optional[str]:
    """A safe relative POSIX path, or None (absolute, traversal, empty)."""
    p = (path or "").replace("\\", "/").strip()
    if not p or p.startswith("/") or ":" in p.split("/", 1)[0]:
        return None
    parts = [x for x in p.split("/") if x not in ("", ".")]
    if not parts or any(x == ".." for x in parts):
        return None
    return "/".join(parts)


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


class ImportError_(ValueError):
    """The upload is not an importable SynthScholar output directory."""


MAX_CLIENT_SKIPPED = 5000


def plan_import(uploads: Iterable[tuple[str, bytes]], client_skipped: Iterable = ()) -> ImportPlan:
    """Choose what to keep from an uploaded output directory.

    `uploads` are (relative path as sent by the browser, content). The browser's
    paths start with the chosen folder's name ("output/review.json"); the review's
    root is the folder that holds review.json, and everything is stored relative to
    it. `client_skipped` lists what the browser chose not to upload ({path, reason},
    paths relative to the review's folder) — recorded as skipped, never trusted as
    content. Raises ImportError_ when review.json is missing or limits are exceeded."""
    items = []
    plan = ImportPlan()
    for raw_path, content in uploads:
        p = _clean(raw_path)
        if p is None:
            plan.skipped.append({"path": raw_path, "reason": "unsafe path"})
            continue
        items.append((p, content))
    if len(items) > MAX_FILES:
        raise ImportError_(f"too many files ({len(items)}; at most {MAX_FILES})")
    roots = sorted((posixpath.dirname(p) for p, _ in items if posixpath.basename(p) == REQUIRED_FILE), key=len)
    if not roots:
        raise ImportError_("no review.json in the selected folder — choose a SynthScholar output directory")
    root = roots[0]
    plan.root = root
    prefix = f"{root}/" if root else ""
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
    for item in list(client_skipped)[:MAX_CLIENT_SKIPPED]:
        p = _clean(str(item.get("path", ""))) if isinstance(item, dict) else None
        if p:
            reason = str(item.get("reason") or "left out before upload")[:120]
            plan.skipped.append({"path": p, "reason": reason, "by": "client"})
    if not plan.get(REQUIRED_FILE):
        raise ImportError_("review.json was skipped — it must be in the selected folder")
    plan.files.sort(key=lambda f: f.path)
    return plan


def summary_of(result) -> dict:
    """Flow counts and included count for listings (store.summary_json)."""
    try:
        flow = result.flow.model_dump() if getattr(result, "flow", None) is not None else None
    except Exception:
        flow = None
    return {"flow": flow, "included_count": len(getattr(result, "included_articles", None) or [])}


def local_run_provenance(plan: ImportPlan) -> dict:
    """Provenance a local (skill) run keeps in its sidecar files rather than in
    review.json: the exact query, count and date per database (search_log.json),
    citation verification, URL checks, and the manuscript's own check. Numbers and
    queries only — never the local paths these files may contain."""
    import json as _json
    from collections import Counter

    def load(path):
        f = plan.get(path)
        if f is None:
            return None
        try:
            return _json.loads(f.content.decode("utf-8"))
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
        def plain(v):   # numbers, short strings and flat dicts/lists of them — no file paths, no blobs
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
        checked = [u.get("checked_at") for u in urls.values() if isinstance(u, dict) and u.get("checked_at")]
        out["url_verification"] = {
            "checked": len(statuses),
            "reachable": sum(1 for s in statuses if isinstance(s, int) and s < 400),
            "statuses": dict(Counter(str(s) for s in statuses)),
            "checked_at": max(checked) if checked else None,
        }
    check = load("review.manuscript.check.json")
    if isinstance(check, dict):
        out["manuscript_check"] = {k: check.get(k) for k in ("body_words", "word_target", "estimated_pages", "page_limit",
                                                              "figures", "references") if k in check}
    return out
