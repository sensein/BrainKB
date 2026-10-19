"""SynthScholar review ingestion — the output directory of a SynthScholar run.

POST   /synthscholar/reviews                      ingest an output directory into a space
GET    /synthscholar/reviews                      reviews the caller can read
GET    /synthscholar/reviews/{review_id}          one review: summary, content, provenance, files
GET    /synthscholar/reviews/{review_id}/files/{path}   one of its files

Permissions are the space's, the same as any ingest: ingesting needs the ingest
role and owner/editor (or manage) rights on the space; reading a review or its
files needs read access to the space it was ingested into (public spaces: anyone).
See core/synthscholar.py for what is kept and what goes into the graph.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response

from core import rbac
from core import reserved_graphs as reserved
from core import spaces as sp
from core import synthscholar as ss
from core.database import create_job
from core.graph_database_connection_manager import check_named_graph_exists, insert_data_gdb_async
from core.models.user import LoginUserIn
from core.provenance import agent_ref
from core.security import get_current_user, get_current_user_optional, require_scopes, verify_user_access
from core.shared import get_oxigraph_endpoint, named_graph_metadata

router = APIRouter()
logger = logging.getLogger(__name__)


def _agent(user) -> str:
    try:
        return str(user["email"] or user["id"])
    except (KeyError, TypeError, IndexError):
        return "unknown"


async def _can_read(space: Optional[dict], member: Optional[str]) -> bool:
    """The same rule as reading a space's data (GET /spaces/{slug}/data)."""
    if not space:
        return False      # the space was deleted: so was the review's graph
    if space["visibility"] != "public":
        if member is None or await sp.member_role(space["space_id"], member) is None \
                or not await rbac.has_capability(member, rbac.READ_PRIVATE):
            return False
    return await sp.space_action_permitted(space, "read", member)


async def _can_add_graph(space: dict, member: str) -> bool:
    """The same rule as POST /spaces/{slug}/graphs: owner/editor, or a space manager."""
    from core.routers.spaces import _can_manage
    if await _can_manage(space, member):
        return True
    return await sp.member_role(space["space_id"], member) in sp.WRITE_ROLES


def _parse_left_out(raw: Optional[str]) -> list:
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except ValueError:
        raise HTTPException(400, "left_out must be a JSON list of {path, reason}")
    return items if isinstance(items, list) else []


async def _start_ingest_job(user_id: str, graph_iri: str, files: dict[str, bytes]) -> str:
    """Create an ordinary ingest job for these RDF files and run it in the background
    — the same job, provenance (PROV-O activity, delta) and search indexing as
    POST /insert/files/knowledge-graph-triples."""
    from core.routers.insert import JOB_BASE_DIR, _running_job_tasks, run_ingest_job
    job_id = uuid.uuid4().hex
    job_dir = os.path.join(JOB_BASE_DIR, user_id, f"job_{job_id}")
    os.makedirs(job_dir, exist_ok=True)
    for name, content in files.items():
        with open(os.path.join(job_dir, name), "wb") as out:
            out.write(content)
    await create_job(job_id=job_id, user_id=user_id, status="pending", total_files=len(files),
                     processed_files=0, success_count=0, fail_count=0, endpoint=get_oxigraph_endpoint(),
                     graph=graph_iri, job_dir=job_dir, start_time=time.time(), end_time=None)

    async def run_and_track():
        try:
            await run_ingest_job(job_id, 8, user_id, False)
        finally:
            _running_job_tasks.pop(job_id, None)
    _running_job_tasks[job_id] = asyncio.create_task(run_and_track())
    return job_id


@router.post("/synthscholar/reviews", status_code=202,
             dependencies=[Depends(require_scopes(["write"]))],
             summary="Ingest a SynthScholar review (its output directory) into a space",
             description="Upload every file of a SynthScholar run's output directory (each filename is its "
                         "path inside the folder). review.json and review.ttl are required. The review's graph, "
                         "https://brainkb.org/synthscholar/reviews/<protocol.review_id>/, is registered in the "
                         "space; review.ttl plus an import record linking every kept file are ingested as a job; "
                         "the files (all but work/) are kept and served under the space's read rules. Once per review.")
async def ingest_review(
    user: Annotated[LoginUserIn, Depends(get_current_user)],
    space_slug: Annotated[str, Form(description="Space to ingest into")],
    files: Annotated[list[UploadFile], File(description="The output directory's files")],
    left_out: Annotated[Optional[str], Form(description="JSON list of {path, reason} not uploaded (e.g. work/)")] = None,
    user_id: Annotated[Optional[str], Form(description="Job owner id (defaults to your email)")] = None,
):
    member = _agent(user)
    if not await rbac.has_capability(member, rbac.INGEST):
        raise HTTPException(403, "Not authorized to ingest: a write-capable role is required.")
    space = await sp.get_space(space_slug)
    if not space:
        raise HTTPException(404, f"space {space_slug!r} not found")
    if not await _can_add_graph(space, member):
        raise HTTPException(403, "only the space owner/editors (or a space manager) can add a review to it")
    allowed, why = await sp.can_write_space(space, member)
    if not allowed:
        raise HTTPException(403, f"Not authorized to ingest into this space: {why}")
    job_user = user_id or member
    verify_user_access(job_user, user)

    try:
        plan = ss.plan_import([(f.filename or "", await f.read()) for f in files], _parse_left_out(left_out))
        review = ss.read_review(plan)
        review_id = ss.review_id_of(review)
    except ss.ImportError_ as e:
        raise HTTPException(400, str(e))
    graph_iri = ss.graph_iri_for(review_id)

    ok, why = await reserved.check_allowed(graph_iri, member, space["space_id"])
    if not ok:
        raise HTTPException(403, why)
    # Once per review: its graph is append-only (a second pass would not de-duplicate,
    # it would add a disconnected copy). The same run uploaded again is refused here.
    if await ss.review_exists(review_id) or await check_named_graph_exists(graph_iri) \
            or await sp.get_space_for_graph(graph_iri) is not None:
        raise HTTPException(409, f"review {review_id} is already ingested ({graph_iri})")

    try:
        await sp.attach_graph(space["space_id"], graph_iri)
    except sp.GraphAlreadyBound as e:
        raise HTTPException(409, str(e))
    summary = ss.summary_of(review)
    await insert_data_gdb_async(named_graph_metadata(
        named_graph_url=graph_iri,
        description=f"SynthScholar review: {summary.get('title') or review_id}"[:300],
        agent_uri=str(agent_ref(member)),
    ))
    await sp.mirror_space_to_rdf(await sp.get_space(space_slug) or space)

    imported_at = ss.now_utc()
    manifest = {**plan.manifest(), "imported_by": member, "imported_at": imported_at.isoformat(),
                "local_run": ss.local_run_provenance(plan)}
    await ss.save_review(review_id=review_id, space_slug=space_slug, owner_email=member, imported_at=imported_at,
                         summary=summary, detail=ss.detail_of(review), manifest=manifest, plan=plan)
    record = ss.import_record_ttl(review_id, plan, agent=agent_ref(member), imported_at=imported_at.isoformat(),
                                  space_slug=space_slug, summary=summary)
    try:
        job_id = await _start_ingest_job(job_user, graph_iri, {
            "review.ttl": plan.get("review.ttl").content,          # plan_import guarantees it
            "synthscholar-import.ttl": record.encode("utf-8"),
        })
    except Exception:
        logger.exception("[synthscholar] could not start the ingest job for %s", review_id)
        await ss.delete_review(review_id)   # the graph stays registered and empty; a retry is refused (409)
        raise HTTPException(500, "The review was received but its ingest job could not be started.")
    await ss.set_job(review_id, job_id)
    logger.info("[synthscholar] %s ingested %s into %s (%d files, %d left out) job=%s",
                member, review_id, space_slug, len(plan.files), len(plan.skipped), job_id)
    return {"review_id": review_id, "graph_iri": graph_iri, "space_slug": space_slug, "job_id": job_id,
            "title": summary.get("title"), "files_kept": len(plan.files), "left_out": len(plan.skipped),
            "status_url": f"/api/insert/jobs?job_id={job_id}&user_id={job_user}"}


@router.get("/synthscholar/reviews", summary="SynthScholar reviews you can read")
async def list_reviews(user: Annotated[Optional[object], Depends(get_current_user_optional)],
                       space: Optional[str] = Query(default=None, description="Only this space")):
    member = _agent(user) if user else None
    cache: dict = {}
    out = []
    for r in await ss.list_reviews():
        if space and r["space_slug"] != space:
            continue
        slug = r["space_slug"]
        if slug not in cache:
            s = await sp.get_space(slug)
            cache[slug] = (await _can_read(s, member), (s or {}).get("visibility"))
        readable, visibility = cache[slug]
        if not readable:
            continue
        if member is None:
            r.pop("owner_email", None)
        out.append({**r, "space_visibility": visibility})
    return {"reviews": out}


async def _readable_review(review_id: str, user) -> dict:
    review = await ss.get_review(review_id)
    member = _agent(user) if user else None
    if review is None or not await _can_read(await sp.get_space(review["space_slug"]), member):
        raise HTTPException(404, f"review {review_id!r} not found")   # don't disclose private reviews
    return review


@router.get("/synthscholar/reviews/{review_id}", summary="One SynthScholar review")
async def get_review(review_id: str, user: Annotated[Optional[object], Depends(get_current_user_optional)]):
    review = await _readable_review(review_id, user)
    if not user:
        review.pop("owner_email", None)
        review["manifest"].pop("imported_by", None)
    review["manifest"]["skipped_count"] = len(review["manifest"].get("skipped") or [])
    review["manifest"]["skipped_reasons"] = sorted({s.get("reason", "") for s in review["manifest"].get("skipped") or []})
    review["manifest"].pop("skipped", None)        # can run to thousands of work/ paths
    review["manifest"].pop("files", None)          # same as `files`
    return review


@router.get("/synthscholar/reviews/{review_id}/files/{path:path}", summary="A file kept with a review")
async def get_file(review_id: str, path: str, user: Annotated[Optional[object], Depends(get_current_user_optional)],
                   download: bool = False):
    await _readable_review(review_id, user)
    clean = ss.clean_path(path)
    f = await ss.get_file(review_id, clean) if clean else None
    if f is None:
        raise HTTPException(404, "file not found")
    name = clean.rsplit("/", 1)[-1]
    return Response(f["content"], media_type=f["media_type"], headers={
        "Content-Disposition": f'{"attachment" if download else "inline"}; filename="{name}"',
        "ETag": f'"{f["sha256"]}"',
        # served from the API origin: never let an uploaded file run script there
        "Content-Security-Policy": "default-src 'none'; img-src data:; style-src 'unsafe-inline'; sandbox",
        "X-Content-Type-Options": "nosniff",
    })
