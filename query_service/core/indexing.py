# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# DISCLAIMER: This software is provided "as is" without any warranty,
# express or implied, including but not limited to the warranties of
# merchantability, fitness for a particular purpose, and non-infringement.
# -----------------------------------------------------------------------------

# @Author  : Tek Raj Chhetri
# @Email   : tekraj@mit.edu
# @File    : indexing.py

"""
Async search-indexing task queue.

Search indexing (building the Postgres locator rows from Oxigraph) can be slow for
large graphs, so it must not run inline with ingestion. This module provides a
lightweight in-process asyncio queue with a single background consumer, backed by a
durable `index_tasks` table for observability and cross-restart recovery.

Ingest enqueues an 'ingest' task (fast) and returns immediately; a 'backfill' task
reindexes every graph. Tasks are claimed atomically in the DB so multiple gunicorn
workers never process the same task twice.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from core.database import get_db_connection
from core.search import index_graph_subjects, _sparql_select

logger = logging.getLogger(__name__)

# Graphs that are infrastructure, not user data — never indexed for search.
_SKIP_GRAPHS = {
    "https://brainkb.org/metadata/named-graph",
    "https://brainkb.org/metadata/spaces/",
    "https://brainkb.org/provenance/",
}

_queue: Optional[asyncio.Queue] = None
_consumer: Optional[asyncio.Task] = None


def _get_queue() -> asyncio.Queue:
    global _queue
    if _queue is None:
        _queue = asyncio.Queue()
    return _queue


async def enqueue_ingest(named_graph_iri: str, delta_graph: Optional[str] = None) -> str:
    """Queue an indexing task for a single graph (called by ingest). Non-blocking."""
    task_id = uuid.uuid4().hex
    async with get_db_connection() as conn:
        await conn.execute(
            """
            INSERT INTO index_tasks (task_id, kind, target, delta_graph, status, created_at)
            VALUES ($1, 'ingest', $2, $3, 'queued', $4)
            """,
            task_id, named_graph_iri, delta_graph, time.time(),
        )
    _get_queue().put_nowait({"task_id": task_id, "kind": "ingest",
                             "target": named_graph_iri, "delta_graph": delta_graph})
    return task_id


async def enqueue_backfill() -> str:
    """Queue a full reindex of every user graph. Non-blocking."""
    task_id = uuid.uuid4().hex
    async with get_db_connection() as conn:
        await conn.execute(
            """
            INSERT INTO index_tasks (task_id, kind, target, status, created_at)
            VALUES ($1, 'backfill', 'ALL', 'queued', $2)
            """,
            task_id, time.time(),
        )
    _get_queue().put_nowait({"task_id": task_id, "kind": "backfill", "target": "ALL"})
    return task_id


async def _claim(task_id: str) -> bool:
    """Atomically move a task queued->running. Returns False if already claimed
    (by another worker) or not claimable — prevents double processing."""
    async with get_db_connection() as conn:
        row = await conn.fetchrow(
            """
            UPDATE index_tasks SET status = 'running', started_at = $2
            WHERE task_id = $1 AND status = 'queued'
            RETURNING task_id
            """,
            task_id, time.time(),
        )
        return row is not None


async def _finish(task_id: str, status: str, subjects: int = 0, message: str = "",
                  graphs_total: Optional[int] = None, graphs_done: int = 0) -> None:
    async with get_db_connection() as conn:
        await conn.execute(
            """
            UPDATE index_tasks
            SET status = $2, subjects_indexed = $3, message = $4,
                graphs_total = COALESCE($5, graphs_total), graphs_done = $6, ended_at = $7
            WHERE task_id = $1
            """,
            task_id, status, subjects, message[:500] if message else None,
            graphs_total, graphs_done, time.time(),
        )


async def _all_user_graphs() -> List[str]:
    rows = await _sparql_select("SELECT DISTINCT ?g WHERE { GRAPH ?g { ?s ?p ?o } }")
    graphs = []
    for b in rows:
        g = b.get("g", {}).get("value")
        if g and g not in _SKIP_GRAPHS and "/provenance/delta/" not in g:
            graphs.append(g)
    return graphs


async def _run(task: Dict[str, Any]) -> None:
    task_id = task["task_id"]
    if not await _claim(task_id):
        return  # another worker already handling it, or not queued
    try:
        if task["kind"] == "ingest":
            n = await index_graph_subjects(task["target"], task.get("delta_graph"))
            await _finish(task_id, "done", subjects=n, message=f"indexed {n} subject(s)")
        elif task["kind"] == "backfill":
            graphs = await _all_user_graphs()
            total, done, subs = len(graphs), 0, 0
            # record the total up front (status stays 'running')
            async with get_db_connection() as conn:
                await conn.execute("UPDATE index_tasks SET graphs_total=$2 WHERE task_id=$1", task_id, total)
            for g in graphs:
                subs += await index_graph_subjects(g)
                done += 1
                async with get_db_connection() as conn:
                    await conn.execute(
                        "UPDATE index_tasks SET graphs_done=$2, subjects_indexed=$3 WHERE task_id=$1",
                        task_id, done, subs,
                    )
            await _finish(task_id, "done", subjects=subs, graphs_total=total, graphs_done=done,
                          message=f"reindexed {done}/{total} graph(s), {subs} subject(s)")
    except Exception as e:
        logger.error(f"[indexing] task {task_id} failed: {e}", exc_info=True)
        await _finish(task_id, "error", message=str(e))


async def _consume() -> None:
    q = _get_queue()
    while True:
        task = await q.get()
        try:
            await _run(task)
        except Exception as e:
            logger.error(f"[indexing] consumer error: {e}", exc_info=True)
        finally:
            q.task_done()


async def start_worker() -> None:
    """Start the background consumer and recover tasks from a previous run.
    Called once on application startup."""
    global _consumer
    # Recovery: any task left 'running' by a crashed process is re-queued.
    try:
        async with get_db_connection() as conn:
            await conn.execute("UPDATE index_tasks SET status = 'queued' WHERE status = 'running'")
            pending = await conn.fetch(
                "SELECT task_id, kind, target, delta_graph FROM index_tasks WHERE status = 'queued'"
            )
    except Exception as e:
        logger.warning(f"[indexing] recovery query failed: {e}")
        pending = []

    if _consumer is None or _consumer.done():
        _consumer = asyncio.create_task(_consume())
        logger.info("[indexing] background consumer started")

    for p in pending:
        _get_queue().put_nowait({
            "task_id": p["task_id"], "kind": p["kind"],
            "target": p["target"], "delta_graph": p["delta_graph"],
        })
    if pending:
        logger.info(f"[indexing] re-queued {len(pending)} pending task(s) from previous session")


async def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    async with get_db_connection() as conn:
        row = await conn.fetchrow("SELECT * FROM index_tasks WHERE task_id = $1", task_id)
        return dict(row) if row else None


async def list_tasks(limit: int = 50) -> List[Dict[str, Any]]:
    async with get_db_connection() as conn:
        rows = await conn.fetch(
            "SELECT * FROM index_tasks ORDER BY created_at DESC LIMIT $1", limit
        )
        return [dict(r) for r in rows]
