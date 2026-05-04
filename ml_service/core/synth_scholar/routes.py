"""FastAPI routes for SynthScholar (PRISMA literature review).

Ported from aep-knowledge-synthesis/backend/routes.py with three adaptations
for ml_service:

1. Every endpoint requires a valid JWT via `Depends(get_current_user)`. The
   bearer's email is recorded as `owner_email` on each new review and is
   used to scope listings + reads. A claim of `roles=["Admin"]` bypasses
   ownership checks (admin oversight).
2. Routes are mounted under /api/synth-scholar (not /api/v1) to align with
   ml_service's existing /api prefix and avoid colliding with structsense's
   surface (/ws/*, /save/*, /ner, /structured-resource).
3. All references to the BioSynthAI feature (separate vertical in the source)
   are dropped — only the PRISMA review pipeline is ported.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Annotated, AsyncGenerator, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from synthscholar import __version__ as agent_version  # type: ignore[import-not-found]
from synthscholar.models import (  # type: ignore[import-not-found]
    ReviewProtocol, ReviewPlan, RoBTool, CompareReviewResult,
)
from synthscholar.pipeline import PRISMAReviewPipeline  # type: ignore[import-not-found]
from synthscholar.export import (  # type: ignore[import-not-found]
    to_markdown, to_json, to_bibtex, to_turtle, to_jsonld,
    to_rubric_markdown, to_rubric_json,
    to_charting_markdown, to_charting_json,
    to_appraisal_markdown, to_appraisal_json,
    to_narrative_summary_markdown, to_narrative_summary_json,
    to_compare_markdown, to_compare_json,
    to_compare_charting_markdown, to_compare_charting_json,
)
from synthscholar.agents import ROB_DOMAINS  # type: ignore[import-not-found]

from core.security import decode_jwt, get_user, get_current_user

from .schemas import (
    RunReviewRequest, CompareRunRequest, CompareReviewSummaryResponse,
    RetryRequest, PlanResponseRequest, ReviewStatus, ReviewSummaryResponse,
    ReviewDetailResponse, ArticleSummary, EvidenceSpanResponse,
    ScreeningLogResponse, GRADEResponse, FlowResponse, ProgressEvent,
    HealthResponse, VisibilityRequest, CacheSharingRequest,
    LiteratureSearchRequest, LiteratureSearchResponse,
    ReviewSearchRequest, ReviewSearchResponse,
    SearchArticleResult, SearchReviewResult,
    SearchSynthesisResponse, SearchSynthesisGroup,
)
from .store import review_store, ReviewSession
from .progress_events import classify

logger = logging.getLogger(__name__)

router = APIRouter()


# ── SSE auth dependency ────────────────────────────────────────────────
#
# EventSource (the browser API for SSE) cannot set custom headers, so the
# usual `Authorization: Bearer ...` dance doesn't work. Instead the client
# passes the JWT as a `?token=` query parameter. This dependency mirrors
# `core.security.get_current_user` but reads the token from either the
# Authorization header OR the query string. Used only by the SSE route.

async def _get_user_for_sse(
    request: Request,
    token: Optional[str] = Query(default=None, description="JWT bearer token (query-param fallback for SSE clients)"),
) -> dict:
    raw = token
    if not raw:
        auth = request.headers.get("authorization") or request.headers.get("Authorization")
        if auth and auth.lower().startswith("bearer "):
            raw = auth.split(None, 1)[1].strip()
    if not raw:
        raise HTTPException(
            status_code=401,
            detail="Missing JWT (set Authorization header or ?token= query param).",
        )
    try:
        payload = decode_jwt(raw)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")
    email = payload.get("sub")
    if not email:
        raise HTTPException(status_code=401, detail="Invalid token (missing sub claim).")
    user = await get_user(email=email)
    if user is None:
        raise HTTPException(status_code=401, detail="Token user not found.")
    return user


# OpenRouter slugs use hyphens (Anthropic API ID format), not dots.
# `anthropic/claude-opus-4.7` is NOT a valid slug — OpenRouter returns 401
# "User not found" for unknown models, which masquerades as an auth failure.
# Keep this list aligned with brainkb-ui/src/app/user/synth-scholar/page.tsx
# `MODEL_OPTIONS`. Add new entries only after confirming on
# https://openrouter.ai/models that OpenRouter routes them.
AVAILABLE_MODELS = [
    # Anthropic — Claude 4.x family.
    "anthropic/claude-opus-4-7",
    "anthropic/claude-opus-4-6",
    "anthropic/claude-sonnet-4-6",
    "anthropic/claude-opus-4",
    "anthropic/claude-sonnet-4",
    "anthropic/claude-haiku-4-5",
    "anthropic/claude-haiku-4",
    # Google.
    "google/gemini-2.5-pro",
    "google/gemini-2.5-flash",
    # OpenAI — only the slugs OpenRouter actually exposes.
    "openai/gpt-4.1",
    "openai/gpt-4o",
    "openai/gpt-4o-mini",
    # xAI / DeepSeek / Meta / Mistral.
    "x-ai/grok-2-1212",
    "deepseek/deepseek-chat",
    "deepseek/deepseek-r1",
    "meta-llama/llama-3.3-70b-instruct",
    "mistralai/mistral-large-2411",
]


# ────────────────────── Helpers ────────────────────────────────────────

def _filter_run_kwargs(run_method, kwargs: dict) -> dict:
    """Drop kwargs the installed synthscholar's pipeline.run doesn't accept.

    Defensive against version skew — older synthscholar wheels were missing
    checkpoint/on_checkpoint/assemble_timeout. Keeps the backend usable
    against pinned-broken versions while logging which features were dropped.
    """
    try:
        params = inspect.signature(run_method).parameters
    except (TypeError, ValueError):
        return kwargs
    accepted = {k: v for k, v in kwargs.items() if k in params}
    dropped = [k for k in kwargs if k not in params]
    if dropped:
        logger.warning(
            "synthscholar pipeline.run does not accept %s — feature(s) silently disabled.",
            dropped,
        )
    return accepted


def _resolve_api_key(request_key: Optional[str] = None) -> str:
    """Resolve the OpenRouter API key for a pipeline run.

    Precedence:
      1. Caller-supplied key (signed-in user's personal key, or the admin
         shared `shared.openrouter_api_key` setting forwarded by the frontend).
      2. OPENROUTER_API_KEY env var (operator fallback / dev).
    """
    if request_key and request_key.strip():
        return request_key.strip()
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        raise HTTPException(
            status_code=400,
            detail=(
                "No OpenRouter API key available. Configure one in the dashboard "
                "API key tab, ask an admin to set the shared key in /admin "
                "settings, or set OPENROUTER_API_KEY on the backend."
            ),
        )
    return key


def _is_admin(user: dict) -> bool:
    """JWT users carry a `scopes` list (existing ml_service convention) and
    optionally a `roles` claim (added when /api/token issues admin tokens).
    Treat either as admin for the purposes of cross-user oversight."""
    if not user:
        return False
    roles = user.get("roles") or []
    if isinstance(roles, list) and "Admin" in roles:
        return True
    scopes = user.get("scopes") or []
    if isinstance(scopes, list) and "admin" in scopes:
        return True
    return False


def _user_email(user: dict) -> str:
    """Pull a stable email/identifier from the JWT user dict.

    `get_current_user` returns the user record from the DB; the calling JWT's
    `sub` claim is its email. Fall back to `email` attribute on the model.
    """
    if isinstance(user, dict):
        return user.get("email") or user.get("sub") or ""
    return getattr(user, "email", "") or ""


async def _session_or_404(review_id: str, user: dict) -> ReviewSession:
    session = await review_store.get(review_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Review '{review_id}' not found")
    if not _is_admin(user):
        owner = session.owner_email or ""
        if owner and owner != _user_email(user):
            # Don't leak existence: return 404 to non-owners.
            raise HTTPException(status_code=404, detail=f"Review '{review_id}' not found")
    return session


def _to_flow_response(flow) -> FlowResponse:
    return FlowResponse(**flow.model_dump())


def _to_summary_response(s: ReviewSession) -> ReviewSummaryResponse:
    r = s.result
    return ReviewSummaryResponse(
        review_id=s.review_id,
        status=s.status,
        title=s.protocol.title if s.protocol else "",
        created_at=s.created_at,
        completed_at=s.completed_at,
        flow=_to_flow_response(r.flow) if r and not isinstance(r, CompareReviewResult) else None,
        included_count=(
            sum(len(mr.result.included_articles) for mr in r.model_results if mr.result)
            if r and isinstance(r, CompareReviewResult)
            else (len(r.included_articles) if r else 0)
        ),
        is_public=s.is_public,
        share_to_cache=s.share_to_cache,
        error=s.error,
        stage=s.stage,
        stage_index=s.stage_index,
        stage_total=s.stage_total,
        stage_done=s.stage_done,
        stage_remaining=s.stage_remaining,
        articles_included=s.articles_included,
    )


def _to_article_summary(article) -> ArticleSummary:
    return ArticleSummary(
        pmid=article.pmid,
        title=article.title,
        authors=article.authors,
        year=article.year,
        journal=article.journal,
        doi=article.doi,
        source=article.source,
        inclusion_status=article.inclusion_status.value if hasattr(article.inclusion_status, "value") else str(article.inclusion_status),
        rob_overall=article.risk_of_bias.overall.value if article.risk_of_bias else "",
        study_design=article.extracted_data.study_design if article.extracted_data else "",
        quality_score=article.quality_score,
    )


def _to_detail_response(session: ReviewSession) -> ReviewDetailResponse:
    r = session.result
    resp = ReviewDetailResponse(
        review_id=session.review_id,
        status=session.status,
        title=session.protocol.title if session.protocol else "",
        created_at=session.created_at,
        completed_at=session.completed_at,
        is_public=session.is_public,
        share_to_cache=session.share_to_cache,
        enable_cache=session.run_request.get("enable_cache") if session.run_request else None,
        last_completed_step=session.last_completed_step,
        run_request=session.run_request,
        error=session.error,
    )
    if r and isinstance(r, CompareReviewResult):
        resp.compare_result = r.model_dump()
        return resp
    if r:
        resp.research_question = r.research_question
        resp.flow = _to_flow_response(r.flow)
        resp.included_articles = [_to_article_summary(a) for a in r.included_articles]
        resp.screening_log = [
            ScreeningLogResponse(
                pmid=s.pmid, title=s.title,
                decision=s.decision.value if hasattr(s.decision, "value") else str(s.decision),
                reason=s.reason,
                stage=s.stage.value if hasattr(s.stage, "value") else str(s.stage),
            )
            for s in r.screening_log
        ]
        resp.evidence_spans = [
            EvidenceSpanResponse(
                text=e.text, paper_pmid=e.paper_pmid, paper_title=e.paper_title,
                section=e.section, relevance_score=e.relevance_score,
                claim=e.claim, doi=e.doi,
            )
            for e in r.evidence_spans
        ]
        resp.synthesis_text = r.synthesis_text
        resp.bias_assessment = r.bias_assessment
        resp.limitations = r.limitations
        resp.grade_assessments = [
            GRADEResponse(
                outcome=outcome,
                overall_certainty=g.overall_certainty.value,
                summary=g.summary,
                domains={k: {"rating": v.rating, "explanation": v.explanation} for k, v in g.domains.items()},
            )
            for outcome, g in r.grade_assessments.items()
        ]
        resp.search_queries = r.search_queries
        resp.data_charting_rubrics = r.data_charting_rubrics
        resp.narrative_rows = r.narrative_rows
        resp.critical_appraisals = r.critical_appraisals
        resp.grounding_validation = r.grounding_validation
        resp.structured_abstract = r.structured_abstract
        resp.introduction_text = r.introduction_text
        resp.conclusions_text = r.conclusions_text
        resp.quality_checklist = r.quality_checklist
        pga = getattr(r, "per_group_analysis", None)
        if pga is not None:
            resp.per_group_analysis = pga.model_dump() if hasattr(pga, "model_dump") else pga
    return resp


_LOG_ENTRY_RE = re.compile(r"^\[([^\]]+)\] (.+)$", re.DOTALL)


def _parse_log_entry(entry: str) -> tuple[str, str]:
    m = _LOG_ENTRY_RE.match(entry)
    if not m:
        return (datetime.now(timezone.utc).isoformat(), entry)
    ts_str, msg = m.group(1), m.group(2)
    if len(ts_str) > 8 and ("T" in ts_str or "-" in ts_str):
        return (ts_str, msg)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return (f"{today}T{ts_str}+00:00", msg)


# ────────────────────── Background Task ────────────────────────────────

def _build_protocol(request: RunReviewRequest, session: ReviewSession) -> ReviewProtocol:
    from .database import DATABASE_URL
    db_url = DATABASE_URL.replace("+asyncpg", "") if request.enable_cache else ""
    return ReviewProtocol(
        title=request.protocol.title,
        objective=request.protocol.objective or request.protocol.title,
        pico_population=request.protocol.pico_population,
        pico_intervention=request.protocol.pico_intervention,
        pico_comparison=request.protocol.pico_comparison,
        pico_outcome=request.protocol.pico_outcome,
        inclusion_criteria=request.protocol.inclusion_criteria,
        exclusion_criteria=request.protocol.exclusion_criteria,
        databases=request.protocol.databases,
        date_range_start=request.protocol.date_range_start,
        date_range_end=request.protocol.date_range_end,
        max_hops=request.protocol.max_hops,
        registration_number=request.protocol.registration_number,
        protocol_url=request.protocol.protocol_url,
        funding_sources=request.protocol.funding_sources,
        competing_interests=request.protocol.competing_interests,
        rob_tool=request.protocol.rob_tool,
        charting_questions=request.protocol.charting_questions,
        appraisal_domains=request.protocol.appraisal_domains,
        grouping_dimension=request.protocol.grouping_dimension,
        default_group_questions=request.protocol.default_group_questions,
        per_group_questions=request.protocol.per_group_questions,
        pg_dsn=db_url,
        review_id=session.review_id,
        share_to_cache=session.is_public or session.share_to_cache,
        max_articles=request.max_articles,
        article_concurrency=request.concurrency,
    )


async def _run_pipeline(session: ReviewSession, request: RunReviewRequest):
    try:
        await session.mark_running()
        api_key = _resolve_api_key(request.openrouter_api_key)
        main_loop = asyncio.get_running_loop()
        session._live.main_loop = main_loop

        protocol = _build_protocol(request, session)
        session.protocol = protocol

        pipeline = PRISMAReviewPipeline(
            api_key=api_key,
            model_name=request.model,
            ncbi_api_key=os.environ.get("NCBI_API_KEY", ""),
            protocol=protocol,
            enable_cache=request.enable_cache,
            max_per_query=request.max_results_per_query,
            related_depth=request.related_depth,
            biorxiv_days=request.biorxiv_days,
        )

        data_items = request.data_items if request.extract_data else None

        async def on_checkpoint(state: dict) -> None:
            await session.save_checkpoint(state)

        if not request.auto_confirm:
            result = await _run_pipeline_with_gate(
                session, pipeline, request, data_items, main_loop, on_checkpoint
            )
        else:
            run_kwargs = _filter_run_kwargs(pipeline.run, dict(
                progress_callback=session.update_progress,
                data_items=data_items,
                auto_confirm=True,
                output_synthesis_style=request.output_synthesis_style,
                checkpoint=session.checkpoint_json,
                on_checkpoint=on_checkpoint,
            ))
            result = await pipeline.run(**run_kwargs)

        await session.mark_completed(result)

    except asyncio.CancelledError:
        await session.mark_cancelled()
        raise
    except RuntimeError as e:
        # Cross-worker cancel: cancel_review on a non-owning worker writes
        # cancel_requested=True; the gate raises this RuntimeError. Treat
        # it as a cancellation, not a failure.
        if "cancelled by user" in str(e).lower():
            await session.mark_cancelled()
        else:
            logger.exception("[synth_scholar] pipeline failed for %s", session.review_id)
            await session.mark_failed(str(e))
    except Exception as e:
        logger.exception("[synth_scholar] pipeline failed for %s", session.review_id)
        await session.mark_failed(str(e))
    finally:
        review_store.evict(session.review_id)


async def _run_compare_pipeline(session: ReviewSession, request: CompareRunRequest):
    try:
        await session.mark_running()
        api_key = _resolve_api_key(request.openrouter_api_key)
        main_loop = asyncio.get_running_loop()
        session._live.main_loop = main_loop

        protocol = _build_protocol(
            RunReviewRequest(
                protocol=request.protocol,
                model=request.compare_models[0],
                max_results_per_query=request.max_results_per_query,
                related_depth=request.related_depth,
                biorxiv_days=request.biorxiv_days,
                enable_cache=request.enable_cache,
                extract_data=request.extract_data,
                data_items=request.data_items,
                max_plan_iterations=request.max_plan_iterations,
                output_synthesis_style=request.output_synthesis_style,
            ),
            session,
        )
        session.protocol = protocol

        pipeline = PRISMAReviewPipeline(
            api_key=api_key,
            model_name=request.compare_models[0],
            ncbi_api_key=os.environ.get("NCBI_API_KEY", ""),
            protocol=protocol,
            enable_cache=request.enable_cache,
            max_per_query=request.max_results_per_query,
            related_depth=request.related_depth,
            biorxiv_days=request.biorxiv_days,
        )

        data_items = request.data_items if request.extract_data else None

        if not request.auto_confirm:
            compare_result = await _run_compare_pipeline_with_gate(
                session, pipeline, request, data_items, main_loop
            )
        else:
            compare_kwargs = _filter_run_kwargs(pipeline.run_compare, dict(
                models=request.compare_models,
                progress_callback=session.update_progress,
                data_items=data_items,
                auto_confirm=True,
                consensus_model=request.consensus_model or request.compare_models[0],
                max_plan_iterations=request.max_plan_iterations,
                output_synthesis_style=request.output_synthesis_style,
                assemble_timeout=3600.0,
            ))
            compare_result = await pipeline.run_compare(**compare_kwargs)

        await session.mark_completed(compare_result)

    except asyncio.CancelledError:
        await session.mark_cancelled()
        raise
    except RuntimeError as e:
        if "cancelled by user" in str(e).lower():
            await session.mark_cancelled()
        else:
            logger.exception("[synth_scholar] compare pipeline failed for %s", session.review_id)
            await session.mark_failed(str(e))
    except Exception as e:
        logger.exception("[synth_scholar] compare pipeline failed for %s", session.review_id)
        await session.mark_failed(str(e))
    finally:
        review_store.evict(session.review_id)


async def _run_pipeline_with_gate(
    session: ReviewSession,
    pipeline: PRISMAReviewPipeline,
    request: RunReviewRequest,
    data_items,
    main_loop: asyncio.AbstractEventLoop,
    on_checkpoint_async=None,
):
    """Run pipeline in thread pool so the sync confirm_callback can block."""

    def confirm_callback(plan: ReviewPlan) -> "bool | str":
        asyncio.run_coroutine_threadsafe(
            _notify_plan(session, plan), main_loop
        ).result(timeout=5)
        return _wait_plan_gate(session, main_loop)

    def on_checkpoint_thread_safe(state: dict) -> None:
        if on_checkpoint_async:
            asyncio.run_coroutine_threadsafe(on_checkpoint_async(state), main_loop)

    def thread_fn():
        import asyncio as _asyncio
        thread_loop = _asyncio.new_event_loop()
        _asyncio.set_event_loop(thread_loop)
        try:
            run_kwargs = _filter_run_kwargs(pipeline.run, dict(
                progress_callback=_make_thread_safe_callback(session, main_loop),
                data_items=data_items,
                auto_confirm=False,
                confirm_callback=confirm_callback,
                max_plan_iterations=request.max_plan_iterations,
                output_synthesis_style=request.output_synthesis_style,
                checkpoint=session.checkpoint_json,
                on_checkpoint=on_checkpoint_thread_safe,
            ))
            return thread_loop.run_until_complete(pipeline.run(**run_kwargs))
        finally:
            thread_loop.close()

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="prisma-gate")
    try:
        result = await main_loop.run_in_executor(executor, thread_fn)
    finally:
        executor.shutdown(wait=False)
    return result


async def _run_compare_pipeline_with_gate(
    session: ReviewSession,
    pipeline: PRISMAReviewPipeline,
    request: CompareRunRequest,
    data_items,
    main_loop: asyncio.AbstractEventLoop,
):
    def confirm_callback(plan: ReviewPlan) -> "bool | str":
        asyncio.run_coroutine_threadsafe(
            _notify_plan(session, plan), main_loop
        ).result(timeout=5)
        return _wait_plan_gate(session, main_loop)

    def thread_fn():
        import asyncio as _asyncio
        thread_loop = _asyncio.new_event_loop()
        _asyncio.set_event_loop(thread_loop)
        try:
            compare_kwargs = _filter_run_kwargs(pipeline.run_compare, dict(
                models=request.compare_models,
                progress_callback=_make_thread_safe_callback(session, main_loop),
                data_items=data_items,
                auto_confirm=False,
                confirm_callback=confirm_callback,
                consensus_model=request.consensus_model or request.compare_models[0],
                max_plan_iterations=request.max_plan_iterations,
                output_synthesis_style=request.output_synthesis_style,
                assemble_timeout=3600.0,
            ))
            return thread_loop.run_until_complete(pipeline.run_compare(**compare_kwargs))
        finally:
            thread_loop.close()

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="prisma-compare-gate")
    try:
        result = await main_loop.run_in_executor(executor, thread_fn)
    finally:
        executor.shutdown(wait=False)
    return result


def _wait_plan_gate(
    session: ReviewSession,
    main_loop: asyncio.AbstractEventLoop,
    timeout_seconds: float = 600.0,
) -> "bool | str":
    """Block the pipeline thread until a plan response arrives, from either
    side of the cross-worker boundary:

    * Fast path — the local threading.Event set by submit_plan_response when
      it happens to land on this worker.
    * Slow path — a response written to plan_response_json in Postgres by
      submit_plan_response on a different worker, drained here via a 1s
      poll (claim_plan_response atomically reads + clears the column).

    Also honors a cross-worker cancel: cancel_review writes
    cancel_requested=True from any worker; this poll picks it up.

    Race-condition note: when the response arrives via the slow path, the
    worker that handled `submit_plan_response` already wrote
    `status="running"` to the DB via `mark_running()`. We MUST mirror that
    onto this worker's `_live.status` before returning — otherwise the very
    next `_persist_progress` flush from this worker reads
    `effective_status = self._live.status` (still "plan_pending") and
    overwrites the DB back to plan_pending, which the UI sees as the status
    oscillating and the plan dialog re-appearing.
    """
    def _mark_resumed() -> None:
        # Mirror the running-state transition that submit_plan_response made
        # in the DB. Clearing pending_plan stops set_plan_pending's stale
        # value from leaking back into the next SSE replay or
        # _persist_progress flush.
        session._live.status = ReviewStatus.RUNNING.value
        session.status = ReviewStatus.RUNNING
        session._live.pending_plan = None

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if session._live.plan_gate.wait(timeout=1.0):
            session._live.plan_gate.clear()
            if session._live.cancel_flag.is_set():
                raise RuntimeError("Review cancelled by user")
            _mark_resumed()
            return session._live.plan_response[0]

        try:
            response = asyncio.run_coroutine_threadsafe(
                session.claim_plan_response(), main_loop
            ).result(timeout=2.0)
        except Exception:
            response = None
        if response is not None:
            _mark_resumed()
            return response

        try:
            cancelled = asyncio.run_coroutine_threadsafe(
                session.is_cancel_requested(), main_loop
            ).result(timeout=2.0)
        except Exception:
            cancelled = False
        if cancelled:
            raise RuntimeError("Review cancelled by user")

    raise TimeoutError("Plan confirmation timed out (10 min)")


async def _notify_plan(session: ReviewSession, plan: ReviewPlan) -> None:
    session.set_plan_pending(plan, plan.iteration)
    session.signal_plan_notify()


def _make_thread_safe_callback(session: ReviewSession, main_loop: asyncio.AbstractEventLoop):
    """Return a progress_callback that signals SSE from a non-main thread."""
    def callback(message: str):
        session.progress_step += 1
        session._live.latest_message = message
        session._live.progress_step = session.progress_step
        session.pipeline_log.append(
            f"[{datetime.now(timezone.utc).isoformat()}] {message}"
        )
        session._apply_classified(message)
        session._live._write_counter += 1
        if session._live._write_counter >= 10:
            session._live._write_counter = 0
            asyncio.run_coroutine_threadsafe(session._persist_progress(), main_loop)
        asyncio.run_coroutine_threadsafe(_set_and_clear_progress(session), main_loop)
    return callback


async def _set_and_clear_progress(session: ReviewSession) -> None:
    session._live.progress_event.set()
    session._live.progress_event.clear()


# ────────────────────── Routes ─────────────────────────────────────────

@router.get("/synth-scholar/health", response_model=HealthResponse, tags=["SynthScholar — system"])
async def health(_user: Annotated[dict, Depends(get_current_user)]):
    """Health check with available models and RoB tools."""
    return HealthResponse(
        status="ok",
        version=agent_version,
        models=AVAILABLE_MODELS,
        rob_tools=[t.value for t in RoBTool],
    )


@router.get("/synth-scholar/rob-tools", tags=["SynthScholar — system"])
async def list_rob_tools(_user: Annotated[dict, Depends(get_current_user)]):
    """List all available Risk of Bias tools with their domains."""
    return [
        {
            "id": tool.value,
            "name": tool.value,
            "domains": ROB_DOMAINS.get(tool.value, []),
            "domain_count": len(ROB_DOMAINS.get(tool.value, [])),
        }
        for tool in RoBTool
    ]


@router.post(
    "/synth-scholar/reviews",
    response_model=ReviewSummaryResponse,
    status_code=202,
    tags=["SynthScholar — reviews"],
)
async def create_review(
    request: RunReviewRequest,
    user: Annotated[dict, Depends(get_current_user)],
):
    """Start a new PRISMA review. Returns immediately with a review_id; the
    pipeline runs in the background. Use GET /reviews/{id}/stream for live
    progress, or poll GET /reviews/{id}/status."""
    # Validate up-front that we have a usable key; fail fast before creating
    # the DB row + spawning the background task.
    _resolve_api_key(request.openrouter_api_key)

    protocol = ReviewProtocol(
        title=request.protocol.title,
        objective=request.protocol.objective or request.protocol.title,
    )
    # Persist the run request without the API key — it never lands in the DB.
    session = await review_store.create(
        protocol,
        run_request=request.model_dump(exclude={"openrouter_api_key"}),
        owner_email=_user_email(user),
    )

    task = asyncio.create_task(_run_pipeline(session, request))
    session._live.cancel_task = task

    return ReviewSummaryResponse(
        review_id=session.review_id,
        status=session.status,
        title=request.protocol.title,
        created_at=session.created_at,
    )


@router.post(
    "/synth-scholar/reviews/compare",
    response_model=CompareReviewSummaryResponse,
    status_code=202,
    tags=["SynthScholar — reviews"],
)
async def create_compare_review(
    request: CompareRunRequest,
    user: Annotated[dict, Depends(get_current_user)],
):
    """Start a compare-mode PRISMA review across 2–5 models."""
    _resolve_api_key(request.openrouter_api_key)

    protocol = ReviewProtocol(
        title=request.protocol.title,
        objective=request.protocol.objective or request.protocol.title,
    )
    run_req_dict = {**request.model_dump(exclude={"openrouter_api_key"}), "compare_mode": True}
    session = await review_store.create(
        protocol,
        run_request=run_req_dict,
        owner_email=_user_email(user),
    )

    task = asyncio.create_task(_run_compare_pipeline(session, request))
    session._live.cancel_task = task

    return CompareReviewSummaryResponse(
        review_id=session.review_id,
        status=session.status,
        compare_models=request.compare_models,
        created_at=session.created_at,
    )


@router.get(
    "/synth-scholar/reviews",
    response_model=list[ReviewSummaryResponse],
    tags=["SynthScholar — reviews"],
)
async def list_reviews(user: Annotated[dict, Depends(get_current_user)]):
    """List the caller's review sessions. Admins see every review."""
    owner = None if _is_admin(user) else _user_email(user)
    sessions = await review_store.list_for_owner(owner)
    return [_to_summary_response(s) for s in sessions]


@router.get(
    "/synth-scholar/reviews/{review_id}",
    response_model=ReviewDetailResponse,
    tags=["SynthScholar — reviews"],
)
async def get_review(
    review_id: str,
    user: Annotated[dict, Depends(get_current_user)],
):
    """Get full review detail including synthesis, evidence, screening log."""
    session = await _session_or_404(review_id, user)
    return _to_detail_response(session)


@router.get(
    "/synth-scholar/reviews/{review_id}/status",
    response_model=ReviewSummaryResponse,
    tags=["SynthScholar — reviews"],
)
async def get_review_status(
    review_id: str,
    user: Annotated[dict, Depends(get_current_user)],
):
    """Lightweight polling endpoint with status + flow counts."""
    session = await _session_or_404(review_id, user)
    return _to_summary_response(session)


async def _stream_from_db(
    review_id: str,
    session: ReviewSession,
    last_step: int,
) -> AsyncGenerator[str, None]:
    """SSE driver for the cross-worker case: the pipeline is running in some
    other gunicorn worker, so we don't have an asyncio.Event to wait on.
    Poll Postgres on a fixed tick instead. Everything emitted here is a
    replay of state that the owning worker already persisted, so it stays
    consistent with what the pipeline truly knows."""
    POLL_INTERVAL = 1.5
    last_plan_iteration = (
        session.pending_plan_iteration_db
        if session.pending_plan_iteration_db is not None
        else 0
    )
    if (
        session.status == ReviewStatus.PLAN_PENDING
        and session.pending_plan_db is not None
        and last_plan_iteration > 0
    ):
        yield (
            f"data: {ProgressEvent(review_id=review_id, step=last_step, message=f'Awaiting plan confirmation (iteration {last_plan_iteration})...', timestamp=datetime.now().isoformat(), event_type='plan_review', plan=session.pending_plan_db).model_dump_json()}\n\n"
        )

    while True:
        await asyncio.sleep(POLL_INTERVAL)
        # Owning worker may have come back online — let the live path take
        # over on the next reconnect.
        if review_id in review_store._runtime:
            yield f"data: {ProgressEvent(review_id=review_id, step=last_step, message='Owning worker reattached — reconnect for live stream.', timestamp=datetime.now().isoformat(), event_type='cancelled').model_dump_json()}\n\n"
            return

        refreshed = await review_store.get(review_id)
        if refreshed is None:
            return

        new_log = list(refreshed.pipeline_log)
        if len(new_log) > last_step:
            for i in range(last_step, len(new_log)):
                ts, msg = _parse_log_entry(new_log[i])
                ev = classify(msg)
                yield (
                    f"data: {ProgressEvent(review_id=review_id, step=i + 1, message=msg, timestamp=ts, event_type='progress', source=ev.get('source'), kind=ev.get('kind', 'log'), stage=refreshed.stage, stage_index=refreshed.stage_index, stage_total=refreshed.stage_total, stage_done=refreshed.stage_done, stage_remaining=refreshed.stage_remaining, articles_included=refreshed.articles_included).model_dump_json()}\n\n"
                )
            last_step = len(new_log)

        if (
            refreshed.status == ReviewStatus.PLAN_PENDING
            and refreshed.pending_plan_db is not None
            and (refreshed.pending_plan_iteration_db or 0) > last_plan_iteration
        ):
            last_plan_iteration = refreshed.pending_plan_iteration_db or 0
            yield (
                f"data: {ProgressEvent(review_id=review_id, step=last_step, message=f'Awaiting plan confirmation (iteration {last_plan_iteration})...', timestamp=datetime.now().isoformat(), event_type='plan_review', plan=refreshed.pending_plan_db).model_dump_json()}\n\n"
            )

        if refreshed.status in (ReviewStatus.COMPLETED, ReviewStatus.FAILED, ReviewStatus.CANCELLED):
            etype = (
                "completed" if refreshed.status == ReviewStatus.COMPLETED
                else "cancelled" if refreshed.status == ReviewStatus.CANCELLED
                else "failed"
            )
            yield (
                f"data: {ProgressEvent(review_id=review_id, step=last_step, message=f'Review {refreshed.status.value}' + (f': {refreshed.error}' if refreshed.error else ''), timestamp=datetime.now().isoformat(), event_type=etype).model_dump_json()}\n\n"
            )
            return


@router.get("/synth-scholar/reviews/{review_id}/stream", tags=["SynthScholar — reviews"])
async def stream_progress(
    review_id: str,
    user: Annotated[dict, Depends(_get_user_for_sse)],
):
    """Server-Sent Events (SSE) stream of pipeline progress.

    Two paths, picked per-request based on whether this gunicorn worker
    owns the pipeline's runtime (`review_store._runtime[review_id]`):

    * Owning worker → live path. asyncio.Event wakeups from the pipeline
      thread give sub-second latency.
    * Non-owning worker → `_stream_from_db` polls Postgres on a 1.5s tick.
      The pipeline persists pipeline_log + pending_plan_json to the DB on
      every relevant transition, and `submit_plan_response` writes the
      response back via `plan_response_json` — so the round-trip works
      from any worker. The owning worker's `_wait_plan_gate` drains that
      column to unblock the gate.

    Never call `mark_failed` from this endpoint — the request landing on
    the wrong worker is normal, not a failure.
    """
    session = await _session_or_404(review_id, user)

    replay_state: dict = {
        "stage": None, "stage_index": None, "stage_total": None,
        "stage_done": 0, "stage_remaining": None, "articles_included": None,
    }

    async def event_generator() -> AsyncGenerator[str, None]:
        from .progress_events import merge_into_state
        history = list(session.pipeline_log)
        for i, entry in enumerate(history):
            ts, msg = _parse_log_entry(entry)
            ev = classify(msg)
            merge_into_state(replay_state, ev)
            yield f"data: {ProgressEvent(review_id=review_id, step=i + 1, message=msg, timestamp=ts, event_type='history', source=ev.get('source'), kind=ev.get('kind', 'log'), stage=replay_state['stage'], stage_index=replay_state['stage_index'], stage_total=replay_state['stage_total'], stage_done=replay_state['stage_done'], stage_remaining=replay_state['stage_remaining'], articles_included=replay_state['articles_included']).model_dump_json()}\n\n"

        last_step = len(history)

        # Cross-worker fallback. See stream_progress docstring for the full
        # picture; the short version is: _LiveState is per-process, so if
        # this request landed on a worker that doesn't own the pipeline,
        # we replay from Postgres instead of fabricating a failure.
        if review_id not in review_store._runtime and session.status in (
            ReviewStatus.RUNNING,
            ReviewStatus.PLAN_PENDING,
            ReviewStatus.PENDING,
        ):
            async for chunk in _stream_from_db(review_id, session, last_step):
                yield chunk
            return

        if session.status in (ReviewStatus.COMPLETED, ReviewStatus.FAILED, ReviewStatus.CANCELLED):
            if session.status == ReviewStatus.CANCELLED:
                _etype = "cancelled"
            elif session.status == ReviewStatus.COMPLETED:
                _etype = "completed"
            else:
                _etype = "failed"
            yield f"data: {ProgressEvent(review_id=review_id, step=last_step, message=f'Review {session.status.value}' + (f': {session.error}' if session.error else ''), timestamp=datetime.now().isoformat(), event_type=_etype).model_dump_json()}\n\n"
            return

        bound_token = session._live.run_token
        last_plan_iteration = 0
        while True:
            current_live = review_store._runtime.get(review_id)
            if current_live is not None and current_live.run_token != bound_token:
                yield f"data: {ProgressEvent(review_id=review_id, step=last_step, message='Session reset — reconnect for new run.', timestamp=datetime.now().isoformat(), event_type='cancelled').model_dump_json()}\n\n"
                return

            try:
                await asyncio.wait_for(session._progress_event.wait(), timeout=30.0)
            except asyncio.TimeoutError:
                if (
                    session._live.status == ReviewStatus.PLAN_PENDING.value
                    and session._live.pending_plan is not None
                    and session._live.pending_plan.iteration > last_plan_iteration
                ):
                    last_plan_iteration = session._live.pending_plan.iteration
                    yield f"data: {ProgressEvent(review_id=review_id, step=last_step, message=f'Awaiting plan confirmation (iteration {last_plan_iteration})...', timestamp=datetime.now().isoformat(), event_type='plan_review', plan=session._live.pending_plan.model_dump()).model_dump_json()}\n\n"
                else:
                    yield f"data: {ProgressEvent(review_id=review_id, step=last_step, message='keepalive', timestamp=datetime.now().isoformat(), event_type='keepalive').model_dump_json()}\n\n"
                continue

            if (
                session.status == ReviewStatus.PLAN_PENDING
                and session._live.pending_plan is not None
                and session._live.pending_plan.iteration > last_plan_iteration
            ):
                last_plan_iteration = session._live.pending_plan.iteration
                yield f"data: {ProgressEvent(review_id=review_id, step=last_step, message=f'Awaiting plan confirmation (iteration {last_plan_iteration})...', timestamp=datetime.now().isoformat(), event_type='plan_review', plan=session._live.pending_plan.model_dump()).model_dump_json()}\n\n"

            live_step = session._live.progress_step
            if live_step > last_step:
                last_step = live_step
                msg = session._live.latest_message
                latest = session._live.latest_event or {}
                event = ProgressEvent(
                    review_id=review_id,
                    step=last_step,
                    message=msg,
                    timestamp=datetime.now().isoformat(),
                    event_type="progress",
                    source=latest.get("source"),
                    kind=latest.get("kind", "log"),
                    stage=session._live.stage,
                    stage_index=session._live.stage_index,
                    stage_total=session._live.stage_total,
                    stage_done=session._live.stage_done,
                    stage_remaining=session._live.stage_remaining,
                    articles_included=session._live.articles_included,
                )
                yield f"data: {event.model_dump_json()}\n\n"

            live_status = session._live.status
            if live_status in ("completed", "failed", "cancelled"):
                final = ProgressEvent(
                    review_id=review_id,
                    step=last_step,
                    message=f"Review {live_status}" + (f": {session.error}" if session.error else ""),
                    timestamp=datetime.now().isoformat(),
                    event_type=live_status,
                )
                yield f"data: {final.model_dump_json()}\n\n"
                break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/synth-scholar/reviews/{review_id}/plan-response", tags=["SynthScholar — reviews"])
async def submit_plan_response(
    review_id: str,
    body: PlanResponseRequest,
    user: Annotated[dict, Depends(get_current_user)],
):
    """Respond to a plan confirmation gate.

    The pipeline lives on whichever gunicorn worker handled POST /reviews,
    but this request can land on any worker. Source of truth is the DB:

    1. Write the response to plan_response_json so the owning worker's
       confirm_callback drains it via its DB-poll fallback.
    2. If we happen to be the owning worker, also signal the local
       threading.Event so the gate unblocks immediately (skips the 1s
       poll latency).
    3. Flip status to RUNNING optimistically. The pipeline thread continues
       within ~1s of the DB write and starts emitting progress events.
    """
    session = await _session_or_404(review_id, user)
    if session.status != ReviewStatus.PLAN_PENDING:
        raise HTTPException(
            status_code=409,
            detail=f"Review is not awaiting plan confirmation (status: {session.status.value})",
        )
    response = True if body.approved else body.feedback
    iteration = (
        session.pending_plan_iteration_db
        if session.pending_plan_iteration_db is not None
        else 0
    )
    await session.write_plan_response(response)
    if review_id in review_store._runtime:
        session._live = review_store._runtime[review_id]
        session.resolve_plan(response)
    await session.mark_running()
    return {
        "review_id": review_id,
        "status": ReviewStatus.RUNNING.value,
        "iteration": iteration,
    }


@router.post(
    "/synth-scholar/reviews/{review_id}/retry",
    response_model=ReviewSummaryResponse,
    status_code=202,
    tags=["SynthScholar — reviews"],
)
async def retry_review(
    review_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    body: RetryRequest = Body(default=RetryRequest()),
):
    """Retry a failed or cancelled review; optionally override enable_cache."""
    session = await _session_or_404(review_id, user)
    if session.status not in (ReviewStatus.FAILED, ReviewStatus.CANCELLED):
        raise HTTPException(
            status_code=409,
            detail=f"Review cannot be retried (status: {session.status.value})",
        )
    if not session.run_request:
        raise HTTPException(
            status_code=500,
            detail="Cannot retry — original configuration not saved. Please create a new review.",
        )
    await session.reset_for_retry(clear_checkpoint=not body.resume)
    run_req = dict(session.run_request)
    if body.enable_cache is not None:
        run_req["enable_cache"] = body.enable_cache
        session.run_request = run_req
    review_store._runtime[review_id] = session._live
    if run_req.get("compare_mode"):
        compare_request = CompareRunRequest(**{k: v for k, v in run_req.items() if k != "compare_mode"})
        task = asyncio.create_task(_run_compare_pipeline(session, compare_request))
    else:
        request = RunReviewRequest(**run_req)
        task = asyncio.create_task(_run_pipeline(session, request))
    session._live.cancel_task = task
    return ReviewSummaryResponse(
        review_id=session.review_id,
        status=session.status,
        title=session.protocol.title if session.protocol else "",
        created_at=session.created_at,
        completed_at=session.completed_at,
        is_public=session.is_public,
        share_to_cache=session.share_to_cache,
        error=session.error,
    )


@router.post(
    "/synth-scholar/reviews/{review_id}/cancel",
    response_model=ReviewSummaryResponse,
    tags=["SynthScholar — reviews"],
)
async def cancel_review(
    review_id: str,
    user: Annotated[dict, Depends(get_current_user)],
):
    """Cancel a running, pending, or plan_pending review.

    Cross-worker behavior: if this request lands on the worker that owns the
    pipeline, we cancel the asyncio.Task directly and the existing
    `except CancelledError → mark_cancelled` path handles state transitions.
    Otherwise we only set cancel_requested in Postgres — the owning worker's
    confirm_callback poll picks it up at the next plan gate, and the
    pipeline raises, which trips its own mark_failed/mark_cancelled. We do
    NOT call mark_cancelled() here from a non-owning worker, because that
    would race with a still-running pipeline and corrupt the final status.
    """
    session = await _session_or_404(review_id, user)
    effective_status = session.status.value
    if effective_status not in ("pending", "running", "plan_pending"):
        raise HTTPException(
            status_code=409,
            detail=f"Review cannot be cancelled (status: {effective_status})",
        )

    if review_id in review_store._runtime:
        live = review_store._runtime[review_id]
        session._live = live
        live.cancel_flag.set()
        if effective_status == "plan_pending":
            session.resolve_plan(False)
        if live.cancel_task:
            live.cancel_task.cancel()
        await session.mark_cancelled()
    else:
        await session.request_cancel()
        if effective_status == "plan_pending":
            await session.write_plan_response(False)
        # Status flip is deferred — the owning worker's pipeline will hit
        # the cancel signal at its next plan gate or progress tick and
        # transition CANCELLED itself. The UI sees CANCELLED via the SSE
        # DB-poll fallback within ~2s.

    return ReviewSummaryResponse(
        review_id=session.review_id,
        status=session.status,
        title=session.protocol.title if session.protocol else "",
        created_at=session.created_at,
        completed_at=session.completed_at,
        is_public=session.is_public,
        share_to_cache=session.share_to_cache,
        error=session.error,
    )


@router.get("/synth-scholar/reviews/{review_id}/export", tags=["SynthScholar — export"])
async def export_review(
    review_id: str,
    user: Annotated[dict, Depends(get_current_user)],
    format: str = Query(
        default="markdown",
        pattern=r"^(markdown|json|bibtex|ttl|jsonld|rubric_markdown|rubric_json|charting_markdown|charting_json|appraisal_markdown|appraisal_json|narrative_summary_markdown|narrative_summary_json)$",
    ),
    model: Optional[str] = Query(default=None, description="Compare-mode only: export a single model's result by model_name"),
):
    """Export a completed review in the requested format."""
    session = await _session_or_404(review_id, user)
    if session.status != ReviewStatus.COMPLETED or not session.result:
        raise HTTPException(
            status_code=400,
            detail=f"Review is not completed (status: {session.status.value})",
        )

    result = session.result
    ts = datetime.now().strftime("%Y%m%d")
    is_compare = isinstance(result, CompareReviewResult)

    single_result = None
    single_model_slug = ""
    if is_compare:
        if model:
            match = next(
                (r for r in result.model_results if r.model_name == model and r.result is not None),
                None,
            )
            if match is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Model '{model}' has no successful result in this compare review",
                )
            single_result = match.result
            single_model_slug = "_" + re.sub(r"[^a-zA-Z0-9_-]+", "-", model).strip("-")
        else:
            first_ok = next((r for r in result.model_results if r.result is not None), None)
            if first_ok is not None:
                single_result = first_ok.result
                single_model_slug = "_" + re.sub(r"[^a-zA-Z0-9_-]+", "-", first_ok.model_name).strip("-")

    def _stem(base: str) -> str:
        return f"{base}{single_model_slug}_{ts}" if (is_compare and single_result and model) else f"{base}_{ts}"

    if format == "markdown":
        if is_compare and not model:
            content = to_compare_markdown(result)
            filename = f"prisma_compare_{ts}.md"
        else:
            target = single_result or result
            content = to_markdown(target)
            pr = getattr(target, "prisma_review", None)
            extraction_with_fields = (
                pr and pr.methods
                and any(getattr(r, "field_answers", None) for r in (pr.methods.data_extraction or []))
            )
            if extraction_with_fields:
                content += "\n\n---\n\n" + to_charting_markdown(target)
            filename = f"{_stem('prisma_review')}.md"
        media_type = "text/markdown"
    elif format == "json":
        if is_compare and not model:
            content = to_compare_json(result)
            filename = f"prisma_compare_{ts}.json"
        else:
            content = to_json(single_result or result)
            filename = f"{_stem('prisma_review')}.json"
        media_type = "application/json"
    elif format == "bibtex":
        content = to_bibtex(single_result or result)
        filename = f"{_stem('prisma_references')}.bib"
        media_type = "text/plain"
    elif format == "ttl":
        content = to_turtle(single_result or result)
        filename = f"{_stem('prisma_review')}.ttl"
        media_type = "text/turtle"
    elif format == "jsonld":
        content = to_jsonld(single_result or result)
        filename = f"{_stem('prisma_review')}.jsonld"
        media_type = "application/ld+json"
    elif format == "rubric_markdown":
        if is_compare and not model:
            content = to_compare_charting_markdown(result)
            filename = f"prisma_compare_rubrics_{ts}.md"
        else:
            content = to_rubric_markdown(single_result or result)
            filename = f"{_stem('prisma_rubrics')}.md"
        media_type = "text/markdown"
    elif format == "rubric_json":
        if is_compare and not model:
            content = to_compare_charting_json(result)
            filename = f"prisma_compare_rubrics_{ts}.json"
        else:
            content = to_rubric_json(single_result or result)
            filename = f"{_stem('prisma_rubrics')}.json"
        media_type = "application/json"
    elif format in ("charting_markdown", "charting_json"):
        target = single_result or result
        pr = getattr(target, "prisma_review", None)
        has_extraction = bool(pr and pr.methods and getattr(pr.methods, "data_extraction", None))
        has_field_answers = has_extraction and any(
            getattr(r, "field_answers", None) for r in pr.methods.data_extraction
        )
        if not has_field_answers:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Charting export not available — this review has no field-level "
                    "extraction. Re-run with extract_data=true and a charting template."
                ),
            )
        if format == "charting_markdown":
            content = to_charting_markdown(target)
            filename = f"{_stem('prisma_charting')}.md"
            media_type = "text/markdown"
        else:
            content = to_charting_json(target)
            filename = f"{_stem('prisma_charting')}.json"
            media_type = "application/json"
    elif format in ("appraisal_markdown", "appraisal_json"):
        target = single_result or result
        pr = getattr(target, "prisma_review", None)
        appraisal_results = (
            (pr.methods.critical_appraisal_results if pr and pr.methods else None)
            or getattr(target, "structured_appraisal_results", None)
            or []
        )
        if not appraisal_results:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Critical appraisal export not available — this review has no "
                    "appraisal results. Re-run with a critical_appraisal config."
                ),
            )
        if format == "appraisal_markdown":
            content = to_appraisal_markdown(target)
            filename = f"{_stem('prisma_appraisal')}.md"
            media_type = "text/markdown"
        else:
            content = to_appraisal_json(target)
            filename = f"{_stem('prisma_appraisal')}.json"
            media_type = "application/json"
    elif format in ("narrative_summary_markdown", "narrative_summary_json"):
        target = single_result or result
        if not getattr(target, "narrative_rows", None):
            raise HTTPException(
                status_code=422,
                detail=(
                    "Narrative summary export not available — this review has no narrative rows."
                ),
            )
        if format == "narrative_summary_markdown":
            content = to_narrative_summary_markdown(target)
            filename = f"{_stem('prisma_narrative_summary')}.md"
            media_type = "text/markdown"
        else:
            content = to_narrative_summary_json(target)
            filename = f"{_stem('prisma_narrative_summary')}.json"
            media_type = "application/json"
    else:
        raise HTTPException(status_code=400, detail=f"Unknown format: {format}")

    return StreamingResponse(
        iter([content]),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/synth-scholar/reviews/{review_id}/log", tags=["SynthScholar — reviews"])
async def get_pipeline_log(
    review_id: str,
    user: Annotated[dict, Depends(get_current_user)],
):
    """Get the full pipeline execution log."""
    session = await _session_or_404(review_id, user)
    log_entries = list(session.pipeline_log)
    log_events = [
        {"step": i + 1, "message": msg, "timestamp": ts}
        for i, (ts, msg) in enumerate(_parse_log_entry(e) for e in log_entries)
    ]
    return {
        "review_id": review_id,
        "status": session.status.value,
        "step_count": session.progress_step,
        "log": log_entries,
        "log_events": log_events,
    }


@router.patch(
    "/synth-scholar/reviews/{review_id}/visibility",
    response_model=ReviewSummaryResponse,
    tags=["SynthScholar — reviews"],
)
async def set_review_visibility(
    review_id: str,
    body: VisibilityRequest,
    user: Annotated[dict, Depends(get_current_user)],
):
    """Toggle public/private visibility. Mirrors share_to_cache."""
    session = await _session_or_404(review_id, user)
    await review_store.set_visibility(review_id, body.is_public)
    session.is_public = body.is_public
    session.share_to_cache = body.is_public
    await _apply_cache_sharing(review_id, body.is_public)
    _r = session.result
    return ReviewSummaryResponse(
        review_id=session.review_id,
        status=session.status,
        title=session.protocol.title if session.protocol else "",
        created_at=session.created_at,
        completed_at=session.completed_at,
        flow=_to_flow_response(_r.flow) if _r and not isinstance(_r, CompareReviewResult) else None,
        included_count=len(_r.included_articles) if _r and not isinstance(_r, CompareReviewResult) else 0,
        is_public=session.is_public,
        share_to_cache=session.share_to_cache,
        error=session.error,
    )


@router.patch(
    "/synth-scholar/reviews/{review_id}/cache-sharing",
    response_model=ReviewSummaryResponse,
    tags=["SynthScholar — reviews"],
)
async def set_cache_sharing(
    review_id: str,
    body: CacheSharingRequest,
    user: Annotated[dict, Depends(get_current_user)],
):
    """Toggle whether this review's cache is available to other users."""
    session = await _session_or_404(review_id, user)
    await review_store.set_cache_sharing(review_id, body.share_to_cache)
    session.share_to_cache = body.share_to_cache
    await _apply_cache_sharing(review_id, body.share_to_cache)
    _r2 = session.result
    return ReviewSummaryResponse(
        review_id=session.review_id,
        status=session.status,
        title=session.protocol.title if session.protocol else "",
        created_at=session.created_at,
        completed_at=session.completed_at,
        flow=_to_flow_response(_r2.flow) if _r2 and not isinstance(_r2, CompareReviewResult) else None,
        included_count=len(_r2.included_articles) if _r2 and not isinstance(_r2, CompareReviewResult) else 0,
        is_public=session.is_public,
        share_to_cache=session.share_to_cache,
        error=session.error,
    )


async def _apply_cache_sharing(review_id: str, is_shared: bool) -> None:
    """Update is_shared on any existing review_cache entries for this review."""
    from .database import DATABASE_URL
    try:
        from synthscholar.cache.store import CacheStore  # type: ignore[import-not-found]
        pg_dsn = DATABASE_URL.replace("+asyncpg", "")
        store = CacheStore(dsn=pg_dsn)
        await store.connect()
        await store.set_sharing(review_id, is_shared)
        await store.close()
    except Exception:
        pass  # Cache may not be initialised; safe to ignore


@router.delete("/synth-scholar/reviews/{review_id}", tags=["SynthScholar — reviews"])
async def delete_review(
    review_id: str,
    user: Annotated[dict, Depends(get_current_user)],
):
    """Delete a review session."""
    session = await _session_or_404(review_id, user)
    if session.status == ReviewStatus.RUNNING:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete a running review. Wait for completion.",
        )
    await review_store.delete(review_id)
    return {"deleted": review_id}


# ────────────────────── Search ────────────────────────────────────────

def _psycopg_dsn() -> str:
    from .database import DATABASE_URL
    return DATABASE_URL.replace("+asyncpg", "")


@router.post(
    "/synth-scholar/search/literature",
    response_model=LiteratureSearchResponse,
    tags=["SynthScholar — search"],
)
async def search_literature(
    req: LiteratureSearchRequest,
    _user: Annotated[dict, Depends(get_current_user)],
):
    """Search the cached article corpus (keyword / by_title / semantic)."""
    from synthscholar.cache.article_store import ArticleStore  # type: ignore[import-not-found]

    store = ArticleStore(dsn=_psycopg_dsn())
    try:
        await store.connect()
        try:
            if req.mode == "semantic":
                articles = await store.search_semantic(req.query, limit=req.top)
            elif req.mode == "by_title":
                articles = await store.search_by_title(req.query, limit=req.top)
            else:
                articles = await store.search_by_keyword(req.query, limit=req.top)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc))

        results = [
            SearchArticleResult(
                pmid=a.pmid, title=a.title, abstract=a.abstract, authors=a.authors,
                journal=a.journal, year=a.year, doi=a.doi, pmc_id=a.pmc_id,
                source=getattr(a, "source", "") or "",
                similarity=getattr(a, "similarity", None),
            )
            for a in articles
        ]

        synthesis = None
        if req.summarize and articles:
            api_key = _resolve_api_key()
            from synthscholar.agents import AgentDeps, run_search_synthesis  # type: ignore[import-not-found]

            deps = AgentDeps(
                protocol=ReviewProtocol(title=req.query, objective=req.query),
                api_key=api_key,
                model_name=req.summary_model,
            )
            try:
                synth = await run_search_synthesis(req.query, articles, deps, top_k=req.summary_top)
                synthesis = SearchSynthesisResponse(
                    query=synth.query,
                    n_articles_synthesized=synth.n_articles_synthesized,
                    overview=synth.overview,
                    overall_caveats=getattr(synth, "overall_caveats", "") or "",
                    groups=[
                        SearchSynthesisGroup(
                            label=g.label,
                            n_studies=g.n_studies,
                            aggregate_finding=g.aggregate_finding,
                            representative_pmids=list(getattr(g, "representative_pmids", []) or []),
                            caveats=getattr(g, "caveats", "") or "",
                        )
                        for g in synth.groups
                    ],
                )
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"Search synthesis failed: {exc}")

        return LiteratureSearchResponse(
            query=req.query, mode=req.mode, results=results, synthesis=synthesis,
        )
    finally:
        await store.close()


@router.post(
    "/synth-scholar/search/reviews",
    response_model=ReviewSearchResponse,
    tags=["SynthScholar — search"],
)
async def search_reviews(
    req: ReviewSearchRequest,
    _user: Annotated[dict, Depends(get_current_user)],
):
    """Search past completed reviews stored in the cache (shared or owned)."""
    from synthscholar.cache.store import CacheStore  # type: ignore[import-not-found]

    store = CacheStore(dsn=_psycopg_dsn())
    try:
        await store.connect()
        try:
            if req.mode == "semantic":
                entries = await store.search_reviews_semantic(
                    req.query, limit=req.top, include_expired=req.include_expired,
                )
            else:
                entries = await store.search_reviews_keyword(
                    req.query, limit=req.top, include_expired=req.include_expired,
                )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc))

        results = []
        for e in entries:
            crit = e.criteria_json or {}
            results.append(
                SearchReviewResult(
                    review_id=getattr(e, "review_id", "") or "",
                    criteria_fingerprint=e.criteria_fingerprint,
                    title=str(crit.get("title", "")),
                    research_question=str(crit.get("question", "") or crit.get("research_question", "")),
                    model_name=e.model_name,
                    created_at=e.created_at,
                    similarity=getattr(e, "similarity", None),
                )
            )
        return ReviewSearchResponse(query=req.query, mode=req.mode, results=results)
    finally:
        await store.close()
