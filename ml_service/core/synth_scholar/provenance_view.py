"""The review's provenance, as the UI shows it: where the review came from (run
here, or imported from a local run's output directory), which SynthScholar
version and model produced it, how the plan and the search evolved, which agents
did what, what every screening decision was judged on, how full texts were
obtained, and where the review went in the graph database.

Built from fields the PRISMAReviewResult already records (run_configuration,
plan_iterations, search_iterations, agent_invocations, screening_log,
included_articles) plus the import manifest and graph-ingest records. Prompt texts
are left out (they can run to megabytes); the JSON export keeps them.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def _v(x: Any) -> str:
    return getattr(x, "value", x) if x is not None else ""


def build_provenance(session, *, include_people: bool = True) -> dict:
    r = getattr(session, "result", None)
    manifest = session.import_manifest or {}
    out: dict = {
        "origin": {
            "source": session.source,
            "created_at": session.created_at,
            "completed_at": session.completed_at,
        },
        "graph_ingests": list(session.graph_ingests or []),
    }
    if session.source == "import":
        out["origin"].update({
            "imported_at": manifest.get("imported_at"),
            "imported_by": manifest.get("imported_by") if include_people else None,
            "original_review_id": manifest.get("original_review_id"),
            "run_completed_at": manifest.get("run_completed_at"),
            "file_count": manifest.get("file_count"),
            "total_bytes": manifest.get("total_bytes"),
            "skipped": manifest.get("skipped") or [],
            # what a local run recorded in its sidecar files (search log, verification)
            "local_run": manifest.get("local_run") or {},
        })
    if not include_people:
        for g in out["graph_ingests"]:
            g.pop("ingested_by", None)
    if r is None or not hasattr(r, "screening_log"):
        return out

    rc = getattr(r, "run_configuration", None)
    if rc is not None:
        out["software"] = {
            "synthscholar_version": rc.package_version or manifest.get("synthscholar_version") or "",
            "model_name": rc.model_name,
            "started_at": rc.started_at,
            "environment": dict(rc.env_vars_present or {}),        # presence only, never values
            "pipeline_settings": {k: v for k, v in (rc.pipeline_kwargs or {}).items()
                                  if isinstance(v, (str, int, float, bool)) and "key" not in k.lower()},
        }
    out["plan_iterations"] = [
        {"iteration": p.iteration_index, "decision": p.decision, "generated_at": p.generated_at,
         "model_name": p.model_name, "feedback": p.user_feedback}
        for p in (getattr(r, "plan_iterations", None) or [])
    ]
    out["search_iterations"] = [
        {"iteration": s.iteration_index, "kind": s.iteration_kind, "database": s.database, "query": s.query,
         "new_records": len(s.new_pmids or []), "cumulative": s.cumulative_count,
         "started_at": s.started_at, "duration_ms": s.duration_ms}
        for s in (getattr(r, "search_iterations", None) or [])
    ]
    def _blank() -> dict[str, Any]:
        return {"calls": 0, "requests": 0, "tokens": 0, "duration_ms": 0.0, "failures": 0, "first_at": "", "last_at": ""}
    agents: dict[tuple, dict[str, Any]] = defaultdict(_blank)
    for a in getattr(r, "agent_invocations", None) or []:
        k = (a.agent_name, a.step_name, a.model_name)
        e = agents[k]
        e["calls"] += 1
        e["requests"] += a.requests or 0
        e["tokens"] += a.total_tokens or 0
        e["duration_ms"] += a.duration_ms or 0.0
        e["failures"] += 0 if a.succeeded else 1
        if a.started_at:
            e["first_at"] = min(filter(None, [e["first_at"], a.started_at]))
            e["last_at"] = max(e["last_at"], a.started_at)
    out["agents"] = [{"agent": k[0], "step": k[1], "model_name": k[2], **v}
                     for k, v in sorted(agents.items(), key=lambda kv: kv[1]["first_at"] or "")]
    basis: dict = defaultdict(Counter)
    ft_sources: Counter = Counter()
    for e in r.screening_log or []:
        basis[_v(e.stage)][e.assessed_on] += 1
        if e.assessed_on == "full_text" and e.full_text_source:
            ft_sources[e.full_text_source] += 1
    out["screening"] = {
        "decisions": len(r.screening_log or []),
        "basis_by_stage": {stage: dict(c) for stage, c in basis.items()},
        "full_text_sources": dict(ft_sources),
    }
    included = r.included_articles or []
    routes = Counter((a.full_text_source or "none") if a.full_text else "abstract only" for a in included)
    out["retrieval"] = {
        "included": len(included),
        "with_full_text": sum(1 for a in included if a.full_text),
        "abstract_only": sum(1 for a in included if not a.full_text),
        "routes": dict(routes),
    }
    return out


GRAPH_BASE = "https://brainkb.org/synthscholar/reviews/"


def review_graph_iri(session) -> str:
    """The review's graph IRI: one review, one graph, wherever it ran. Named by the
    review's own id — for an import, the id the local run gave it (protocol.review_id,
    e.g. review_local_<ts>), so the same review ingested from its .ttl directly and
    from here lands in the same graph and the second attempt is refused."""
    manifest = getattr(session, "import_manifest", None) or {}
    rid = (manifest.get("original_review_id") if session.source == "import" else None) or session.review_id
    from urllib.parse import quote
    return f"{GRAPH_BASE}{quote(str(rid), safe='')}/"


def safe_graph_entry(entry: dict) -> dict:
    """What a graph-ingest record keeps: no tokens, no free-form payloads."""
    keys = ("space_slug", "graph_iri", "job_id", "ingested_at", "ingested_by", "triples", "source_file", "sha256")
    return {k: entry.get(k) for k in keys if entry.get(k) is not None}
