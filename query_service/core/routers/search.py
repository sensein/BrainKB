# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# DISCLAIMER: This software is provided "as is" without any warranty,
# express or implied, including but not limited to the warranties of
# merchantability, fitness for a particular purpose, and non-infringement.
# -----------------------------------------------------------------------------

# @Author  : Tek Raj Chhetri
# @Email   : tekraj@mit.edu
# @File    : search.py (router)

"""Search endpoint — hybrid Postgres-locator + Oxigraph-data, access-filtered."""

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query

from core.models.user import LoginUserIn
from core.security import get_current_user, get_current_user_optional, require_scopes
from core import search as se
from core import indexing as ix

router = APIRouter()
logger = logging.getLogger(__name__)


def _agent(user) -> Optional[str]:
    if not user:
        return None
    try:
        return user["email"]
    except (KeyError, TypeError, IndexError):
        return None


@router.get(
    "/search",
    summary="Search knowledge graphs (access-filtered)",
    description=(
        "Full-text search over the knowledge graphs, honoring space visibility. "
        "Postgres locates matching subjects (fast, filtered by workspace/visibility); "
        "the matched triples are then fetched from Oxigraph.\n\n"
        "- **Anonymous** (no token): searches **public** spaces only.\n"
        "- **Authenticated**: public spaces + the caller's own/member (private) spaces "
        "(and legacy/unmapped graphs).\n"
        "- Pass `space` to scope the search to a single space you can access; omit it "
        "for a full search across everything you may read.\n\n"
        "Private data is never returned to non-members — the filter is enforced in the "
        "locator query itself."
    ),
)
async def search(
    user: Annotated[Optional[object], Depends(get_current_user_optional)],
    q: Annotated[str, Query(..., min_length=1, description="Search terms")],
    space: Annotated[Optional[str], Query(description="Restrict to a single space slug")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return await se.search(q=q, caller=_agent(user), space_slug=space, limit=limit, offset=offset)


@router.post(
    "/search/reindex",
    dependencies=[Depends(require_scopes(["admin"]))],
    summary="Backfill/rebuild the search index (admin) — runs in background",
    description="Queues a background task that reindexes every user graph into the "
                "Postgres locator index. Returns immediately with a task_id; poll "
                "GET /search/index-tasks for progress.",
)
async def reindex(user: Annotated[LoginUserIn, Depends(get_current_user)]):
    task_id = await ix.enqueue_backfill()
    return {"status": "queued", "task_id": task_id,
            "message": "Backfill reindex queued; runs in the background."}


@router.get(
    "/search/index-tasks",
    dependencies=[Depends(require_scopes(["read"]))],
    summary="List background indexing tasks and their status",
)
async def index_tasks(
    user: Annotated[LoginUserIn, Depends(get_current_user)],
    task_id: Annotated[Optional[str], Query(description="Fetch a single task by id")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    if task_id:
        t = await ix.get_task(task_id)
        return t or {"error": "task not found"}
    return {"tasks": await ix.list_tasks(limit)}
