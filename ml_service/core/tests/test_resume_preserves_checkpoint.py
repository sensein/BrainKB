"""Regression test — Resume from step N must preserve the checkpoint.

Pins the invariant: when a user clicks "Resume from step N" in the UI, the
backend must keep ``checkpoint_json`` and ``last_completed_step`` intact so
the next ``pipeline.run`` call picks up from step N rather than restarting
at step 0.

Path under test::

    UI clicks "Resume from step N"
       → POST /reviews/{id}/retry  body={"resume": true}
       → reset_for_retry(clear_checkpoint=False)
       → checkpoint_json + last_completed_step UNCHANGED
       → asyncio.create_task(_run_pipeline(...))
       → pipeline.run(checkpoint=session.checkpoint_json, ...)
       → _ckpt_step = checkpoint["last_completed_step"]  (= N)
       → all stage guards `if _ckpt_step >= N` skip already-completed work

Test scope: the in-process portion of ``reset_for_retry`` — we mock
``async_session`` so this runs offline without a real Postgres.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

import pytest

from core.synth_scholar.schemas import ReviewStatus
from core.synth_scholar.store import ReviewSession


def _stub_session():
    """Build a session with a populated checkpoint, as if a 6-hour run failed at step 15."""
    s = ReviewSession(review_id="rv-resume-test-001")
    s.status = ReviewStatus.FAILED
    s.error = "Server restarted while review was in progress"
    s.progress_step = 15
    s.pipeline_log = ["step 1 done", "step 7 done", "step 15 done"]
    # Pretend the pipeline checkpointed at step 15 with rich payload data.
    s.checkpoint_json = {
        "last_completed_step": 15,
        "ta_included": [{"pmid": "1"}, {"pmid": "2"}],
        "ft_included": [{"pmid": "1"}],
        "evidence": [{"text": "snippet", "paper_pmid": "1"}],
        "data_charting_rubrics": [{"foo": "bar"}],
        "narrative_rows": [],
    }
    s.last_completed_step = 15
    return s


@asynccontextmanager
async def _fake_db_session(*args, **kwargs):
    """Async context manager that yields a no-op DB session."""
    db = MagicMock()
    db.execute = MagicMock(return_value=asyncio.sleep(0))
    db.commit = MagicMock(return_value=asyncio.sleep(0))
    yield db


@pytest.mark.asyncio
async def test_resume_true_preserves_checkpoint_in_memory():
    """``reset_for_retry(clear_checkpoint=False)`` keeps the in-memory checkpoint intact."""
    s = _stub_session()
    expected_ckpt = dict(s.checkpoint_json)
    expected_step = s.last_completed_step

    with patch("core.synth_scholar.store.async_session", _fake_db_session):
        await s.reset_for_retry(clear_checkpoint=False)

    # Status reset for the new run...
    assert s.status == ReviewStatus.PENDING
    assert s.progress_step == 0
    assert s.pipeline_log == []
    assert s.error is None
    # ...but the checkpoint must survive verbatim.
    assert s.checkpoint_json == expected_ckpt, (
        "Resume from step N path lost the checkpoint payload — "
        "the next pipeline.run will restart from step 0"
    )
    assert s.last_completed_step == expected_step


@pytest.mark.asyncio
async def test_resume_false_clears_checkpoint():
    """``reset_for_retry(clear_checkpoint=True)`` (Full restart) must wipe checkpoint."""
    s = _stub_session()

    with patch("core.synth_scholar.store.async_session", _fake_db_session):
        await s.reset_for_retry(clear_checkpoint=True)

    assert s.checkpoint_json is None
    assert s.last_completed_step == 0
    # Status / progress also reset (covered above; assert here too for completeness).
    assert s.status == ReviewStatus.PENDING


@pytest.mark.asyncio
async def test_resume_db_update_omits_checkpoint_columns():
    """When clear_checkpoint=False, the DB UPDATE must NOT touch checkpoint columns.

    Otherwise a buggy implementation could clear the row's checkpoint in the
    database while leaving the in-memory copy intact — the next worker that
    loads from the DB would see no checkpoint and silently restart from step 0.
    """
    s = _stub_session()
    captured_values: list[dict] = []

    @asynccontextmanager
    async def _capturing_session(*args, **kwargs):
        db = MagicMock()
        async def _exec(stmt):
            # SQLAlchemy update().values(**kwargs) keeps the kwargs on the
            # compiled statement — we read them back via the internal
            # _values mapping.
            try:
                vals = dict(stmt.compile().params)
            except Exception:
                vals = dict(getattr(stmt, "_values", {}) or {})
            captured_values.append(vals)
            return MagicMock(rowcount=1)
        db.execute = _exec
        async def _commit(): return None
        db.commit = _commit
        yield db

    with patch("core.synth_scholar.store.async_session", _capturing_session):
        await s.reset_for_retry(clear_checkpoint=False)

    assert captured_values, "Expected at least one DB UPDATE to be issued"
    update_vals = captured_values[0]
    # The whole point: these two columns must NOT be in the UPDATE values
    # when clear_checkpoint=False.
    assert "checkpoint_json" not in update_vals
    assert "last_completed_step" not in update_vals
