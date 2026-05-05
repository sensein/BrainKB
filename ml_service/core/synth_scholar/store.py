"""PostgreSQL-backed review session store — DB-only architecture.

All persistent state (status, log, stage counters, result) lives exclusively
in Postgres. The only things kept in memory are the runtime primitives that
*cannot* be serialised: asyncio.Event, threading.Event, asyncio.Task, and a
tiny mirror of the last-known hot-path values so the SSE loop can emit events
without an extra DB round-trip on every message.

Ported from aep-knowledge-synthesis with one extension: the `owner_email`
column links reviews to the JWT subject that created them, so the routes
layer can scope listings per user (admins see all).
"""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, delete as sa_delete, update as sa_update

from synthscholar.models import (  # type: ignore[import-not-found]
    PRISMAReviewResult,
    CompareReviewResult,
    ReviewPlan,
    ReviewProtocol,
)

from .database import async_session
from .db_models import ReviewRow
from .progress_events import classify, merge_into_state
from .schemas import ReviewStatus

logger = logging.getLogger(__name__)

# How many progress messages to buffer before flushing to DB. Reduces write
# amplification while keeping intermediate state reasonably fresh.
_WRITE_BATCH = 10


# ── Runtime-only state ──────────────────────────────────────────────────

@dataclass
class _LiveState:
    """Per-session in-memory state for SSE subscribers and pipeline control.

    Only runtime OS-level primitives and a tiny mirror of hot-path values
    live here. Everything else is in Postgres.
    """
    run_token: str = field(default_factory=lambda: uuid.uuid4().hex)

    progress_event: asyncio.Event = field(default_factory=asyncio.Event)
    plan_gate: threading.Event = field(default_factory=threading.Event)
    plan_response: list = field(default_factory=lambda: [True])
    pending_plan: Optional[Any] = None
    plan_notify: asyncio.Event = field(default_factory=asyncio.Event)
    main_loop: Optional[Any] = None
    cancel_task: Optional[Any] = None
    cancel_flag: threading.Event = field(default_factory=threading.Event)

    latest_message: str = ""
    latest_event: Optional[dict] = None
    status: str = "pending"
    progress_step: int = 0
    stage: Optional[str] = None
    stage_index: Optional[int] = None
    stage_total: Optional[int] = None
    stage_done: int = 0
    stage_remaining: Optional[int] = None
    articles_included: Optional[int] = None

    _write_counter: int = 0


# ── ReviewSession ────────────────────────────────────────────────────────

@dataclass
class ReviewSession:
    """Thin DTO that mirrors the DB row plus the attached _LiveState."""
    review_id: str
    status: ReviewStatus = ReviewStatus.PENDING
    protocol: Optional[ReviewProtocol] = None
    result: Optional[Any] = None
    pipeline_log: list[str] = field(default_factory=list)
    progress_step: int = 0
    created_at: str = ""
    completed_at: Optional[str] = None
    error: Optional[str] = None
    is_public: bool = False
    share_to_cache: bool = False
    run_request: Optional[dict] = None
    checkpoint_json: Optional[dict] = None
    last_completed_step: int = 0
    owner_email: Optional[str] = None

    stage: Optional[str] = None
    stage_index: Optional[int] = None
    stage_total: Optional[int] = None
    stage_done: int = 0
    stage_remaining: Optional[int] = None
    articles_included: Optional[int] = None
    latest_event: Optional[dict] = None

    # DB-mirrored plan fields. Populated by _row_to_session so the SSE
    # generator can replay plan-pending events on any worker, not just the
    # one running the pipeline.
    pending_plan_db: Optional[dict] = None
    pending_plan_iteration_db: Optional[int] = None

    _live: _LiveState = field(default_factory=_LiveState)

    @property
    def _progress_event(self) -> asyncio.Event:
        return self._live.progress_event

    @property
    def _latest_message(self) -> str:
        return self._live.latest_message

    @_latest_message.setter
    def _latest_message(self, value: str):
        self._live.latest_message = value

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    # ── Progress mutation ──────────────────────────────────────────────

    def update_progress(self, message: str):
        self.progress_step += 1
        self._latest_message = message
        self.pipeline_log.append(
            f"[{datetime.now(timezone.utc).isoformat()}] {message}"
        )
        if len(self.pipeline_log) > 5000:
            self.pipeline_log = self.pipeline_log[-5000:]
        self._apply_classified(message)
        self._live.progress_event.set()
        self._live.progress_event.clear()
        self._live._write_counter += 1
        if self._live._write_counter >= _WRITE_BATCH:
            self._live._write_counter = 0
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._persist_progress())
            except RuntimeError:
                pass

    def _apply_classified(self, message: str) -> dict:
        event = dict(classify(message))
        state: dict = {
            "stage": self.stage,
            "stage_index": self.stage_index,
            "stage_total": self.stage_total,
            "stage_done": self.stage_done,
            "stage_remaining": self.stage_remaining,
            "articles_included": self.articles_included,
        }
        merge_into_state(state, event)
        self.stage = state["stage"]
        self.stage_index = state["stage_index"]
        self.stage_total = state["stage_total"]
        self.stage_done = state["stage_done"] or 0
        self.stage_remaining = state["stage_remaining"]
        self.articles_included = state["articles_included"]
        self.latest_event = event
        self._live.stage = self.stage
        self._live.stage_index = self.stage_index
        self._live.stage_total = self.stage_total
        self._live.stage_done = self.stage_done
        self._live.stage_remaining = self.stage_remaining
        self._live.articles_included = self.articles_included
        self._live.latest_event = event
        self._live.progress_step = self.progress_step
        return event

    def rebuild_progress_state(self) -> None:
        """Recompute cumulative progress state from the full pipeline_log."""
        self.stage = None
        self.stage_index = None
        self.stage_total = None
        self.stage_done = 0
        self.stage_remaining = None
        self.articles_included = None
        for entry in self.pipeline_log:
            msg = entry.split("] ", 1)[1] if entry.startswith("[") and "] " in entry else entry
            self._apply_classified(msg)

    # ── DB persistence ─────────────────────────────────────────────────

    async def _persist_progress(self):
        try:
            effective_status = self._live.status or self.status.value
            async with async_session() as db:
                await db.execute(
                    sa_update(ReviewRow)
                    .where(ReviewRow.review_id == self.review_id)
                    .values(
                        progress_step=self.progress_step,
                        pipeline_log=list(self.pipeline_log[-2000:]),
                        status=effective_status,
                        stage=self.stage,
                        stage_idx=self.stage_index,
                        stage_total=self.stage_total,
                        stage_done_count=self.stage_done or 0,
                        stage_remaining=self.stage_remaining,
                        articles_included=self.articles_included,
                        latest_message=self._live.latest_message or None,
                    )
                )
                await db.commit()
        except Exception as exc:
            logger.warning("[_persist_progress] %s: %s", self.review_id, exc)

    async def mark_completed(self, result: PRISMAReviewResult) -> None:
        self.status = ReviewStatus.COMPLETED
        self._live.status = ReviewStatus.COMPLETED.value
        self.result = result
        self.completed_at = datetime.now(timezone.utc).isoformat()
        self._live.progress_event.set()
        try:
            async with async_session() as db:
                await db.execute(
                    sa_update(ReviewRow)
                    .where(ReviewRow.review_id == self.review_id)
                    .values(
                        status=self.status.value,
                        result_json=self.result.model_dump() if self.result else None,
                        completed_at=datetime.fromisoformat(self.completed_at),
                        progress_step=self.progress_step,
                        pipeline_log=list(self.pipeline_log),
                        stage=self.stage,
                        stage_idx=self.stage_index,
                        stage_total=self.stage_total,
                        stage_done_count=self.stage_done or 0,
                        stage_remaining=self.stage_remaining,
                        articles_included=self.articles_included,
                        latest_message=self._live.latest_message or None,
                        pending_plan_json=None,
                        pending_plan_iteration=None,
                        plan_response_json=None,
                    )
                )
                await db.commit()
        except Exception as exc:
            logger.error("[mark_completed] persist error %s: %s", self.review_id, exc)
            self.status = ReviewStatus.FAILED
            self._live.status = ReviewStatus.FAILED.value
            self.error = f"Persist failed after completion: {exc}"
            await self._persist_failed_minimal()
            return

        # Best-effort push to BrainKB's Oxigraph triplestore. Runs in a
        # threadpool so the synchronous httpx client doesn't block the event
        # loop, and never raises — Postgres remains the source of truth.
        try:
            from .oxigraph_push import push_review_to_oxigraph
            await asyncio.to_thread(push_review_to_oxigraph, self.review_id, result)
        except Exception as exc:
            logger.warning(
                "[mark_completed] oxigraph push raised unexpectedly for %s: %s",
                self.review_id, exc,
            )

    async def mark_failed(self, error: str) -> None:
        self.status = ReviewStatus.FAILED
        self._live.status = ReviewStatus.FAILED.value
        self.error = error
        self.completed_at = datetime.now(timezone.utc).isoformat()
        self._live.progress_event.set()
        await self._persist_failed_minimal()

    async def _persist_failed_minimal(self) -> None:
        try:
            async with async_session() as db:
                await db.execute(
                    sa_update(ReviewRow)
                    .where(ReviewRow.review_id == self.review_id)
                    .values(
                        status=self.status.value,
                        error=self.error,
                        completed_at=datetime.fromisoformat(self.completed_at) if self.completed_at else None,
                        progress_step=self.progress_step,
                        pipeline_log=list(self.pipeline_log[-2000:]),
                        pending_plan_json=None,
                        pending_plan_iteration=None,
                        plan_response_json=None,
                    )
                )
                await db.commit()
        except Exception as exc:
            logger.critical("[_persist_failed_minimal] %s: %s", self.review_id, exc)

    async def mark_cancelled(self) -> None:
        self.status = ReviewStatus.CANCELLED
        self._live.status = ReviewStatus.CANCELLED.value
        self.completed_at = datetime.now(timezone.utc).isoformat()
        self._live.progress_event.set()
        try:
            async with async_session() as db:
                await db.execute(
                    sa_update(ReviewRow)
                    .where(ReviewRow.review_id == self.review_id)
                    .values(
                        status=self.status.value,
                        completed_at=datetime.fromisoformat(self.completed_at),
                        progress_step=self.progress_step,
                        pipeline_log=list(self.pipeline_log[-2000:]),
                        pending_plan_json=None,
                        pending_plan_iteration=None,
                        plan_response_json=None,
                        cancel_requested=False,
                    )
                )
                await db.commit()
        except Exception as exc:
            logger.error("[mark_cancelled] %s: %s", self.review_id, exc)

    async def mark_running(self) -> None:
        self.status = ReviewStatus.RUNNING
        self._live.status = ReviewStatus.RUNNING.value
        async with async_session() as db:
            await db.execute(
                sa_update(ReviewRow)
                .where(ReviewRow.review_id == self.review_id)
                .values(
                    status=ReviewStatus.RUNNING.value,
                    pending_plan_json=None,
                    pending_plan_iteration=None,
                )
            )
            await db.commit()

    async def reset_for_retry(self, clear_checkpoint: bool = True):
        self.status = ReviewStatus.PENDING
        self._live.status = ReviewStatus.PENDING.value
        self.progress_step = 0
        self.pipeline_log = []
        self.error = None
        self.completed_at = None
        self.result = None
        self.stage = None
        self.stage_index = None
        self.stage_total = None
        self.stage_done = 0
        self.stage_remaining = None
        self.articles_included = None
        self.latest_event = None
        self._live = _LiveState()
        self._live.status = ReviewStatus.PENDING.value
        values: dict = dict(
            status=ReviewStatus.PENDING.value,
            progress_step=0,
            pipeline_log=[],
            error=None,
            completed_at=None,
            result_json=None,
            stage=None,
            stage_idx=None,
            stage_total=None,
            stage_done_count=0,
            stage_remaining=None,
            articles_included=None,
            latest_message=None,
        )
        if clear_checkpoint:
            self.checkpoint_json = None
            self.last_completed_step = 0
            values["checkpoint_json"] = None
            values["last_completed_step"] = 0
        async with async_session() as db:
            await db.execute(
                sa_update(ReviewRow)
                .where(ReviewRow.review_id == self.review_id)
                .values(**values)
            )
            await db.commit()

    async def save_checkpoint(self, state: dict) -> None:
        step = state.get("last_completed_step", 0)
        self.checkpoint_json = state
        self.last_completed_step = step
        try:
            async with async_session() as db:
                await db.execute(
                    sa_update(ReviewRow)
                    .where(ReviewRow.review_id == self.review_id)
                    .values(checkpoint_json=state, last_completed_step=step)
                )
                await db.commit()
        except Exception as exc:
            logger.warning("[checkpoint] save failed for %s: %s", self.review_id, exc)

    async def clear_checkpoint(self) -> None:
        self.checkpoint_json = None
        self.last_completed_step = 0
        async with async_session() as db:
            await db.execute(
                sa_update(ReviewRow)
                .where(ReviewRow.review_id == self.review_id)
                .values(checkpoint_json=None, last_completed_step=0)
            )
            await db.commit()

    # ── Plan confirmation gate ──────────────────────────────────────────

    def set_plan_pending(self, plan: ReviewPlan, iteration: int) -> None:
        self.status = ReviewStatus.PLAN_PENDING
        self._live.status = ReviewStatus.PLAN_PENDING.value
        self._live.pending_plan = plan
        self.pipeline_log.append(
            f"[{datetime.now().strftime('%H:%M:%S')}] Plan ready for review (iteration {iteration})"
        )
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._persist_plan_pending(plan, iteration))
        except RuntimeError:
            pass

    async def _persist_plan_pending(self, plan: ReviewPlan, iteration: int) -> None:
        """Stash pending_plan in Postgres so SSE on any worker can replay it
        and so submit_plan_response can write a response that the owning
        worker's confirm_callback will pick up via DB poll."""
        try:
            async with async_session() as db:
                await db.execute(
                    sa_update(ReviewRow)
                    .where(ReviewRow.review_id == self.review_id)
                    .values(
                        status=ReviewStatus.PLAN_PENDING.value,
                        pipeline_log=list(self.pipeline_log[-2000:]),
                        progress_step=self.progress_step,
                        pending_plan_json=plan.model_dump(),
                        pending_plan_iteration=iteration,
                        plan_response_json=None,
                    )
                )
                await db.commit()
        except Exception as exc:
            logger.warning("[_persist_plan_pending] %s: %s", self.review_id, exc)

    async def _clear_plan_state(self) -> None:
        """Clear pending_plan/response columns on terminal transitions or
        once the pipeline consumes the response."""
        try:
            async with async_session() as db:
                await db.execute(
                    sa_update(ReviewRow)
                    .where(ReviewRow.review_id == self.review_id)
                    .values(
                        pending_plan_json=None,
                        pending_plan_iteration=None,
                        plan_response_json=None,
                    )
                )
                await db.commit()
        except Exception as exc:
            logger.warning("[_clear_plan_state] %s: %s", self.review_id, exc)

    async def write_plan_response(self, response: "bool | str") -> None:
        """Stash the user's plan response in Postgres so the owning worker's
        confirm_callback picks it up via its DB-poll fallback."""
        async with async_session() as db:
            await db.execute(
                sa_update(ReviewRow)
                .where(ReviewRow.review_id == self.review_id)
                .values(plan_response_json={"response": response})
            )
            await db.commit()

    async def claim_plan_response(self) -> "bool | str | None":
        """Atomically read+clear the plan_response_json column. Returns the
        response if one was waiting, or None. Used by confirm_callback's
        DB-poll loop to drain a response written by another worker."""
        async with async_session() as db:
            row = await db.get(ReviewRow, self.review_id)
            if not row or not row.plan_response_json:
                return None
            response = row.plan_response_json.get("response")
            await db.execute(
                sa_update(ReviewRow)
                .where(ReviewRow.review_id == self.review_id)
                .values(plan_response_json=None)
            )
            await db.commit()
            return response

    async def request_cancel(self) -> None:
        """Set the cancel_requested flag in Postgres so the owning worker's
        progress and confirm callbacks pick it up. The status flip to
        CANCELLED is performed by the pipeline coroutine itself, not here —
        marking it cancelled from a non-owning worker would race with a
        still-running pipeline."""
        async with async_session() as db:
            await db.execute(
                sa_update(ReviewRow)
                .where(ReviewRow.review_id == self.review_id)
                .values(cancel_requested=True)
            )
            await db.commit()

    async def is_cancel_requested(self) -> bool:
        async with async_session() as db:
            row = await db.get(ReviewRow, self.review_id)
            return bool(row and row.cancel_requested)

    def signal_plan_notify(self) -> None:
        self._live.plan_notify.set()
        self._live.plan_notify.clear()

    def resolve_plan(self, response: "bool | str") -> None:
        self._live.plan_response.clear()
        self._live.plan_response.append(response)
        self._live.plan_gate.set()


# ── Hydration helpers ────────────────────────────────────────────────────

def _row_to_session(row: ReviewRow) -> ReviewSession:
    """Convert a DB row to a ReviewSession (without live SSE state)."""
    protocol = None
    if row.protocol_json:
        protocol = ReviewProtocol.model_validate(row.protocol_json)

    result = None
    if row.result_json:
        is_compare = row.run_request_json and row.run_request_json.get("compare_mode")
        if is_compare:
            result = CompareReviewResult.model_validate(row.result_json)
        else:
            result = PRISMAReviewResult.model_validate(row.result_json)

    session = ReviewSession(
        review_id=row.review_id,
        status=ReviewStatus(row.status),
        protocol=protocol,
        result=result,
        pipeline_log=list(row.pipeline_log) if row.pipeline_log else [],
        progress_step=row.progress_step,
        created_at=row.created_at.isoformat() if row.created_at else "",
        completed_at=row.completed_at.isoformat() if row.completed_at else None,
        error=row.error,
        is_public=row.is_public,
        share_to_cache=row.share_to_cache,
        run_request=row.run_request_json,
        checkpoint_json=row.checkpoint_json,
        last_completed_step=row.last_completed_step or 0,
        owner_email=row.owner_email,
    )
    if row.stage is not None or row.stage_idx is not None:
        session.stage = row.stage
        session.stage_index = row.stage_idx
        session.stage_total = row.stage_total
        session.stage_done = row.stage_done_count or 0
        session.stage_remaining = row.stage_remaining
        session.articles_included = row.articles_included
    else:
        session.rebuild_progress_state()
    # Surface the persisted plan-pending state so SSE generators on a worker
    # that doesn't own the runtime can still emit a plan_review event with
    # the plan body. Live runtime state, when present, takes precedence.
    session.pending_plan_db = row.pending_plan_json
    session.pending_plan_iteration_db = row.pending_plan_iteration
    return session


# ── ReviewStore ──────────────────────────────────────────────────────────

class ReviewStore:
    """PostgreSQL-only store. Runtime primitives live in _runtime; everything
    else is in Postgres. There is no in-memory data cache — every get() reads
    from the DB so status is always authoritative."""

    def __init__(self):
        self._runtime: dict[str, _LiveState] = {}

    async def create(
        self,
        protocol: ReviewProtocol,
        run_request: Optional[dict] = None,
        owner_email: Optional[str] = None,
    ) -> ReviewSession:
        now = datetime.now(timezone.utc)
        async with async_session() as db:
            count_result = await db.execute(select(ReviewRow.review_id))
            counter = len(count_result.all()) + 1

        review_id = f"review_{counter:04d}_{now.strftime('%Y%m%d%H%M%S')}"

        row = ReviewRow(
            review_id=review_id,
            status=ReviewStatus.PENDING.value,
            title=protocol.title,
            protocol_json=protocol.model_dump(),
            pipeline_log=[],
            progress_step=0,
            created_at=now,
            is_public=False,
            share_to_cache=False,
            run_request_json=run_request,
            owner_email=owner_email,
        )
        async with async_session() as db:
            db.add(row)
            await db.commit()

        session = ReviewSession(
            review_id=review_id,
            status=ReviewStatus.PENDING,
            protocol=protocol,
            created_at=now.isoformat(),
            share_to_cache=False,
            run_request=run_request,
            owner_email=owner_email,
        )
        live = _LiveState(status=ReviewStatus.PENDING.value)
        session._live = live
        self._runtime[review_id] = live
        return session

    async def get(self, review_id: str) -> Optional[ReviewSession]:
        async with async_session() as db:
            row = await db.get(ReviewRow, review_id)
            if not row:
                return None
        session = _row_to_session(row)
        if review_id in self._runtime:
            live = self._runtime[review_id]
            session._live = live
            if live.status:
                try:
                    session.status = ReviewStatus(live.status)
                except ValueError:
                    pass
            session.stage = live.stage if live.stage is not None else session.stage
            session.stage_index = live.stage_index if live.stage_index is not None else session.stage_index
            session.stage_total = live.stage_total if live.stage_total is not None else session.stage_total
            session.stage_done = live.stage_done or session.stage_done
            session.stage_remaining = live.stage_remaining if live.stage_remaining is not None else session.stage_remaining
            session.articles_included = live.articles_included if live.articles_included is not None else session.articles_included
            session.progress_step = max(session.progress_step, live.progress_step)
        return session

    async def list_for_owner(self, owner_email: Optional[str]) -> list[ReviewSession]:
        """List reviews. If owner_email is None → list ALL (admin view)."""
        async with async_session() as db:
            stmt = select(ReviewRow).order_by(ReviewRow.created_at.desc())
            if owner_email is not None:
                stmt = stmt.where(ReviewRow.owner_email == owner_email)
            result = await db.execute(stmt)
            rows = result.scalars().all()

        sessions = []
        for row in rows:
            s = _row_to_session(row)
            if row.review_id in self._runtime:
                live = self._runtime[row.review_id]
                s._live = live
                if live.status:
                    try:
                        s.status = ReviewStatus(live.status)
                    except ValueError:
                        pass
                s.stage = live.stage if live.stage is not None else s.stage
                s.stage_index = live.stage_index if live.stage_index is not None else s.stage_index
                s.stage_total = live.stage_total if live.stage_total is not None else s.stage_total
                s.stage_done = live.stage_done or s.stage_done
                s.stage_remaining = live.stage_remaining if live.stage_remaining is not None else s.stage_remaining
                s.articles_included = live.articles_included if live.articles_included is not None else s.articles_included
                s.progress_step = max(s.progress_step, live.progress_step)
            sessions.append(s)
        return sessions

    async def delete(self, review_id: str) -> bool:
        self._runtime.pop(review_id, None)
        async with async_session() as db:
            result = await db.execute(
                sa_delete(ReviewRow).where(ReviewRow.review_id == review_id)
            )
            await db.commit()
            return result.rowcount > 0

    async def set_visibility(self, review_id: str, is_public: bool) -> bool:
        async with async_session() as db:
            result = await db.execute(
                sa_update(ReviewRow)
                .where(ReviewRow.review_id == review_id)
                .values(is_public=is_public, share_to_cache=is_public)
            )
            await db.commit()
        return result.rowcount > 0

    async def set_cache_sharing(self, review_id: str, share_to_cache: bool) -> bool:
        async with async_session() as db:
            result = await db.execute(
                sa_update(ReviewRow)
                .where(ReviewRow.review_id == review_id)
                .values(share_to_cache=share_to_cache)
            )
            await db.commit()
        return result.rowcount > 0

    def evict(self, review_id: str):
        self._runtime.pop(review_id, None)


async def fix_stuck_reviews() -> int:
    """Mark in-progress reviews as FAILED at server startup.

    The pipeline ran as an in-process asyncio task; if the container restarted
    (deploy, OOM, scale-in) while a review was active, that task is gone and
    the review is no longer making progress.  Two distinct cases:

    1. **Resumable** — ``checkpoint_json`` is non-NULL.  The pipeline had
       saved at least one checkpoint, so the user can pick up where it
       stopped via the "Resume from step N" action in the UI.  We preserve
       ``checkpoint_json`` and ``last_completed_step`` (UPDATE doesn't touch
       them) and set an error message that hints at this option.
    2. **Not resumable** — no checkpoint yet.  Plain retry is the only path.

    Returns the total number of rows updated across both cases.
    """
    in_progress = ["running", "pending", "plan_pending"]
    async with async_session() as db:
        # Resumable: checkpoint exists → tell the user they can resume.
        resumable = await db.execute(
            sa_update(ReviewRow)
            .where(ReviewRow.status.in_(in_progress))
            .where(ReviewRow.checkpoint_json.isnot(None))
            .values(
                status=ReviewStatus.FAILED.value,
                error="Server restarted while review was in progress — "
                      "use 'Resume from step N' to continue, or 'Full restart' "
                      "to start over.",
            )
        )
        # Not resumable: no checkpoint to fall back on.
        not_resumable = await db.execute(
            sa_update(ReviewRow)
            .where(ReviewRow.status.in_(in_progress))
            .where(ReviewRow.checkpoint_json.is_(None))
            .values(
                status=ReviewStatus.FAILED.value,
                error="Server restarted while review was in progress — please retry.",
            )
        )
        await db.commit()
    return (resumable.rowcount or 0) + (not_resumable.rowcount or 0)


# Singleton
review_store = ReviewStore()
