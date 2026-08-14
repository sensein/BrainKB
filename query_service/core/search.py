# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# DISCLAIMER: This software is provided "as is" without any warranty,
# express or implied, including but not limited to the warranties of
# merchantability, fitness for a particular purpose, and non-infringement.
# -----------------------------------------------------------------------------

# @Author  : Tek Raj Chhetri
# @Email   : tekraj@mit.edu
# @File    : search.py

"""
Hybrid search: Postgres is a full-text **locator** index, Oxigraph is the source
of truth for the data.

At ingest time each subject's literal text is indexed into `graph_search_index`
along with its named graph and owning space (workspace). A search query runs in
Postgres (fast, access-filtered by space visibility/membership) to LOCATE the
matching subjects, then the actual triples for that page of hits are fetched from
Oxigraph.

Access model (identical to spaces):
  * anonymous  -> public-space subjects only
  * logged-in  -> public + the caller's member spaces (+ legacy/unmapped, authed)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from core.database import get_db_connection
from core.shared import get_oxigraph_auth
from core.graph_database_connection_manager import _get_endpoint
from core.provenance import query_provenance_jsonld
from core.spaces import get_space_for_graph

logger = logging.getLogger(__name__)


async def _sparql_select(query: str) -> List[Dict[str, Any]]:
    """Run a SPARQL SELECT and return its bindings (empty list on error)."""
    try:
        endpoint = _get_endpoint("get")
        auth = get_oxigraph_auth()
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
            resp = await client.post(
                endpoint,
                data={"query": query},
                headers={"Accept": "application/sparql-results+json"},
                auth=auth,
            )
        if resp.status_code != 200:
            logger.warning("[search] SELECT failed (HTTP %s): %s", resp.status_code, (resp.text or "")[:400])
            return []
        return resp.json().get("results", {}).get("bindings", [])
    except Exception as e:
        logger.warning(f"[search] SELECT error: {e}", exc_info=True)
        return []


async def index_graph_subjects(named_graph_iri: str, delta_graph: Optional[str] = None) -> int:
    """
    (Re)index the subjects of a named graph into the Postgres locator index.

    Each subject's searchable text is the concatenation of its literal objects,
    read from Oxigraph. When `delta_graph` is given, only subjects touched by that
    job are (re)indexed (their full text is still read from the target graph).
    Best-effort — returns the number of subjects indexed (0 on failure).
    """
    try:
        if delta_graph:
            q = f"""
            SELECT ?s (GROUP_CONCAT(DISTINCT STR(?o); SEPARATOR=" ") AS ?text)
            WHERE {{
              GRAPH <{delta_graph}> {{ ?s ?dp ?do }}
              GRAPH <{named_graph_iri}> {{ ?s ?p ?o FILTER(isLiteral(?o)) }}
            }} GROUP BY ?s
            """
        else:
            q = f"""
            SELECT ?s (GROUP_CONCAT(DISTINCT STR(?o); SEPARATOR=" ") AS ?text)
            WHERE {{ GRAPH <{named_graph_iri}> {{ ?s ?p ?o FILTER(isLiteral(?o)) }} }}
            GROUP BY ?s
            """
        rows = await _sparql_select(q)
        if not rows:
            return 0

        space = await get_space_for_graph(named_graph_iri)
        space_id = space["space_id"] if space else None

        import time
        now = time.time()
        records = []
        for b in rows:
            subj = b.get("s", {}).get("value")
            text = b.get("text", {}).get("value", "")
            if subj and text.strip():
                records.append((named_graph_iri, space_id, subj, text, now))
        if not records:
            return 0

        async with get_db_connection() as conn:
            await conn.executemany(
                """
                INSERT INTO graph_search_index (named_graph_iri, space_id, subject, text, tsv, updated_at)
                VALUES ($1, $2, $3, $4, to_tsvector('english', $4), $5)
                ON CONFLICT (named_graph_iri, subject) DO UPDATE SET
                    space_id = EXCLUDED.space_id,
                    text = EXCLUDED.text,
                    tsv = EXCLUDED.tsv,
                    updated_at = EXCLUDED.updated_at
                """,
                records,
            )
        logger.info(f"[search] Indexed {len(records)} subject(s) for {named_graph_iri}")
        return len(records)
    except Exception as e:
        logger.warning(f"[search] Failed to index {named_graph_iri}: {e}", exc_info=True)
        return 0


async def reindex_graph_space(named_graph_iri: str, space_id: str) -> None:
    """Point a graph's existing index rows at a (new) space — e.g. when a graph is
    attached to a space after it was already indexed."""
    try:
        async with get_db_connection() as conn:
            await conn.execute(
                "UPDATE graph_search_index SET space_id = $1 WHERE named_graph_iri = $2",
                space_id, named_graph_iri,
            )
    except Exception as e:
        logger.warning(f"[search] Failed to reassign space for {named_graph_iri}: {e}", exc_info=True)


async def search(q: str, caller: Optional[str], space_slug: Optional[str] = None,
                 limit: int = 25, offset: int = 0) -> Dict[str, Any]:
    """
    Locate matching subjects in Postgres (access-filtered), then fetch their triples
    from Oxigraph. `caller` is the user email, or None for anonymous.
    """
    # Build the access-filtered locator query. Access is authoritative from the
    # spaces tables (joined live), so visibility flips need no reindex.
    params: List[Any] = [q, caller]
    where = [
        "i.tsv @@ plainto_tsquery('english', $1)",
        "(s.visibility = 'public' OR m.member IS NOT NULL OR (i.space_id IS NULL AND $2 IS NOT NULL))",
    ]
    idx = 3
    if space_slug:
        where.append(f"s.slug = ${idx}")
        params.append(space_slug)
        idx += 1
    limit_i, offset_i = idx, idx + 1
    params.extend([limit, offset])

    sql = f"""
        SELECT i.named_graph_iri, i.subject, i.text,
               s.slug AS space_slug, s.visibility AS visibility,
               ts_rank(i.tsv, plainto_tsquery('english', $1)) AS rank
        FROM graph_search_index i
        LEFT JOIN spaces s ON s.space_id = i.space_id
        LEFT JOIN space_members m ON m.space_id = i.space_id AND m.member = $2
        WHERE {' AND '.join(where)}
        ORDER BY rank DESC, i.subject
        LIMIT ${limit_i} OFFSET ${offset_i}
    """
    async with get_db_connection() as conn:
        rows = await conn.fetch(sql, *params)

    hits = []
    for r in rows:
        text = r["text"] or ""
        hits.append({
            "subject": r["subject"],
            "named_graph_iri": r["named_graph_iri"],
            "space": r["space_slug"],
            "visibility": r["visibility"] or ("legacy" if r["named_graph_iri"] else None),
            "snippet": (text[:240] + "…") if len(text) > 240 else text,
        })

    # Fetch the located subjects' triples from Oxigraph (the source of truth).
    data = None
    if hits:
        construct = "CONSTRUCT { ?s ?p ?o } WHERE { " + " UNION ".join(
            f'{{ BIND(<{h["subject"]}> AS ?s) GRAPH <{h["named_graph_iri"]}> {{ ?s ?p ?o }} }}'
            for h in hits
        ) + " }"
        data = await query_provenance_jsonld(construct)

    return {"query": q, "space": space_slug, "count": len(hits), "hits": hits, "data": data}
