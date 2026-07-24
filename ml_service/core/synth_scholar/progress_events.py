"""Classify raw pipeline progress strings into typed events.

synthscholar's `progress_callback` still receives plain strings; the richer
status display is produced by parsing those strings server-side into
categorised events with stage / article counters. This module is the only
place that knows the shape of those strings — everything downstream (session
state, SSE stream, frontend) consumes the structured dicts returned here.
"""

from __future__ import annotations

import re
from typing import Any, Optional, TypedDict


# ── Event kinds ────────────────────────────────────────────────────────
#
# "log"           — informational line (default)
# "stage_start"   — a named pipeline phase begins (may carry stage_total)
# "stage_done"    — a named pipeline phase ends (may carry articles_included)
# "article_start" — work on a single study begins within a stage
# "article_done"  — work on a single study completes (carries done/total/remaining)
# "plan_ready"    — search strategy is awaiting user confirmation
# "done"          — entire pipeline finished successfully

EVENT_KINDS = (
    "log",
    "stage_start",
    "stage_done",
    "article_start",
    "article_done",
    "plan_ready",
    "done",
)


class ClassifiedEvent(TypedDict, total=False):
    kind: str
    stage: Optional[str]
    stage_index: Optional[int]
    stage_total: Optional[int]
    stage_done: Optional[int]
    stage_remaining: Optional[int]
    articles_included: Optional[int]
    source: Optional[str]


_KNOWN_SOURCES = (
    "PubMed", "bioRxiv", "medRxiv", "Europe PMC",
    "Semantic Scholar", "CrossRef", "OpenAlex",
)


# Order matters: first match wins. More specific patterns first.
_STAGE_START_PATTERNS: tuple[tuple[re.Pattern[str], str, Optional[int]], ...] = (
    (re.compile(r"^Generating search strategy"),           "Search Strategy",          1),
    (re.compile(r"^PubMed search \d+/\d+:"),                "Database Search",          3),
    (re.compile(r"^bioRxiv search:"),                       "Database Search",          3),
    (re.compile(r"^Finding related articles"),              "Related Articles",         4),
    (re.compile(r"^Citation hop"),                          "Citation Hops",            5),
    (re.compile(r"^Deduplicating"),                         "Deduplication",            6),
    (re.compile(r"^Screening \d+ articles \(title/abstract"), "Title/Abstract Screening", 7),
    (re.compile(r"^Fetching full text for"),                "Full-text Retrieval",      8),
    (re.compile(r"^Full-text eligibility screening"),       "Full-text Screening",      9),
    (re.compile(r"^Extracting evidence spans"),             "Evidence Extraction",      10),
    (re.compile(r"^Extracting data from \d+ studies"),      "Data Extraction",          11),
    (re.compile(r"^Assessing risk of bias"),                "Risk of Bias",             12),
    (re.compile(r"^(?:Charting|Data charting for)\s"),      "Data Charting",            13),
    (re.compile(r"^(?:Critical appraisal|Appraising)\s"),   "Critical Appraisal",       14),
    (re.compile(r"^(?:Narrative rows?|Building narrative)"),"Narrative Synthesis",      15),
    (re.compile(r"^Synthesizing \d+ articles"),             "Synthesis",                16),
    (re.compile(r"^Validating grounding"),                  "Grounding Validation",     17),
    (re.compile(r"^Assessing overall bias and GRADE"),      "GRADE Assessment",         18),
)

_STAGE_TOTAL_RE = re.compile(
    r"(?:Screening|screening|Extracting data from|Fetching full text for)\s+\((?P<a>\d+)\s+articles|"
    r"(?:Screening|Extracting evidence spans\s+—)\s+(?P<b>\d+)\s+articles|"
    r"Extracting data from\s+(?P<c>\d+)\s+studies|"
    r"Fetching full text for\s+(?P<d>\d+)\s+PMC"
)

_ARTICLE_DONE_RE = re.compile(
    r"^\s*✓\s+(?:Charted\s+|Appraised\s+|Narrative\s+)?\S+\s+\[(\d+)/(\d+)\s+done,\s+(\d+)\s+remaining\]"
)

_ARTICLE_START_RE = re.compile(
    r"^\s*(?:\[(\d+)/(\d+)\]|(?:Charting|Appraising|Narrative)\s+\[(\d+)/(\d+),\s+(\d+)\s+remaining\])"
)

_TA_SCREENING_DONE_RE = re.compile(r"^Screening:\s+(\d+)\s+included,\s+(\d+)\s+excluded")
_FT_INCLUDED_RE = re.compile(r"^Final included:\s+(\d+)\s+articles")
_DEDUP_DONE_RE = re.compile(r"^After dedup:\s+(\d+)\s+\(removed\s+(\d+)\)")
_EVIDENCE_DONE_RE = re.compile(r"^Extracted\s+\d+\s+evidence spans from\s+(\d+)\s+articles")
_TOTAL_IDENT_RE = re.compile(r"^Total identified:\s+(\d+)")
_PLAN_READY_RE = re.compile(r"^Awaiting plan confirmation")
_DONE_RE = re.compile(r"^Review complete!?\s*$")


def _extract_source(message: str) -> Optional[str]:
    stripped = message.lstrip()
    for src in _KNOWN_SOURCES:
        if stripped.startswith(src):
            return src
    return None


def classify(message: str) -> ClassifiedEvent:
    """Classify one raw progress string into a typed event.

    Returns a dict with `kind` plus any fields the message explicitly
    establishes (stage, counters, source). Callers maintain their own
    cumulative session state by merging successive events.
    """
    msg = message or ""

    if _PLAN_READY_RE.match(msg):
        return {"kind": "plan_ready"}

    if _DONE_RE.match(msg):
        return {"kind": "done"}

    m = _ARTICLE_DONE_RE.match(msg)
    if m:
        return {
            "kind": "article_done",
            "stage_done": int(m.group(1)),
            "stage_total": int(m.group(2)),
            "stage_remaining": int(m.group(3)),
        }

    m = _ARTICLE_START_RE.match(msg)
    if m:
        idx = m.group(1) or m.group(3)
        total = m.group(2) or m.group(4)
        remaining = m.group(5)
        ev: ClassifiedEvent = {"kind": "article_start"}
        if idx and total:
            ev["stage_done"] = int(idx) - 1
            ev["stage_total"] = int(total)
        if remaining:
            ev["stage_remaining"] = int(remaining)
        return ev

    m = _TA_SCREENING_DONE_RE.match(msg)
    if m:
        return {
            "kind": "stage_done",
            "stage": "Title/Abstract Screening",
            "stage_index": 7,
            "articles_included": int(m.group(1)),
        }

    m = _FT_INCLUDED_RE.match(msg)
    if m:
        return {
            "kind": "stage_done",
            "stage": "Full-text Screening",
            "stage_index": 9,
            "articles_included": int(m.group(1)),
        }

    m = _DEDUP_DONE_RE.match(msg)
    if m:
        return {
            "kind": "stage_done",
            "stage": "Deduplication",
            "stage_index": 6,
            "stage_total": int(m.group(1)),
        }

    m = _EVIDENCE_DONE_RE.match(msg)
    if m:
        return {
            "kind": "stage_done",
            "stage": "Evidence Extraction",
            "stage_index": 10,
            "stage_total": int(m.group(1)),
        }

    m = _TOTAL_IDENT_RE.match(msg)
    if m:
        return {
            "kind": "stage_done",
            "stage": "Database Search",
            "stage_index": 5,
            "stage_total": int(m.group(1)),
        }

    for pat, stage_name, stage_index in _STAGE_START_PATTERNS:
        if pat.match(msg):
            ev = {"kind": "stage_start", "stage": stage_name, "stage_index": stage_index}
            tm = _STAGE_TOTAL_RE.search(msg)
            if tm:
                total_str = tm.group("a") or tm.group("b") or tm.group("c") or tm.group("d")
                if total_str:
                    ev["stage_total"] = int(total_str)
            src = _extract_source(msg)
            if src:
                ev["source"] = src
            return ev

    ev_log: ClassifiedEvent = {"kind": "log"}
    src = _extract_source(msg)
    if src:
        ev_log["source"] = src
    return ev_log


def merge_into_state(state: dict[str, Any], event: ClassifiedEvent) -> dict[str, Any]:
    """Merge a classified event into cumulative session progress state."""
    kind = event.get("kind", "log")

    if kind == "stage_start":
        state["stage"] = event.get("stage") or state.get("stage")
        state["stage_index"] = event.get("stage_index") or state.get("stage_index")
        state["stage_total"] = event.get("stage_total")
        state["stage_done"] = 0
        state["stage_remaining"] = event.get("stage_total")
        return state

    if kind == "stage_done":
        if event.get("stage"):
            state["stage"] = event["stage"]
            state["stage_index"] = event.get("stage_index") or state.get("stage_index")
        if event.get("stage_total") is not None:
            state["stage_total"] = event["stage_total"]
            state["stage_done"] = event["stage_total"]
            state["stage_remaining"] = 0
        if event.get("articles_included") is not None:
            state["articles_included"] = event["articles_included"]
        return state

    if kind in ("article_start", "article_done"):
        for key in ("stage_total", "stage_done", "stage_remaining"):
            if event.get(key) is not None:
                state[key] = event[key]
        return state

    return state
