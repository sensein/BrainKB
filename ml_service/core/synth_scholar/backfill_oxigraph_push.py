"""One-shot backfill — push every completed review's RDF to Oxigraph.

Use cases:

* You ran reviews **before** the auto-push (mark_completed → oxigraph_push)
  was wired in.  Their result_json is sitting in Postgres but no triples
  ever reached Oxigraph.
* The auto-push silently failed for a batch of reviews (e.g. the bare-IRI
  serialisation bug fixed in synthscholar 0.0.10) and you want to re-push
  them after upgrading.
* You're standing up a fresh Oxigraph and want to populate it from the
  durable Postgres source of truth.

Each push uses ``GraphDBConfig.replace=True`` (the default for BrainKB),
so running this script twice is **idempotent** — the second run overwrites
the same named graph rather than duplicating triples.

Usage (run inside the brainkb-unified container, where the Postgres DSN
and GRAPHDATABASE_* env vars are already set)::

    # Push every completed review:
    docker exec brainkb-unified python -m core.synth_scholar.backfill_oxigraph_push

    # Just one review:
    docker exec brainkb-unified python -m core.synth_scholar.backfill_oxigraph_push \\
        --review-id review_0001_20260505234027

    # Inspect first; don't push:
    docker exec brainkb-unified python -m core.synth_scholar.backfill_oxigraph_push \\
        --dry-run --limit 5
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from typing import Any, Optional

from sqlalchemy import select

from .database import async_session
from .db_models import ReviewRow
from .oxigraph_push import push_review_to_oxigraph

logger = logging.getLogger("backfill_oxigraph_push")


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="backfill_oxigraph_push",
        description=__doc__.split("\n\n", 1)[0],
    )
    p.add_argument(
        "--review-id",
        action="append",
        default=[],
        metavar="REVIEW_ID",
        help="Push only this review_id. Repeatable. If omitted, every "
             "completed review with a result_json is pushed.",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Cap how many reviews to push (after filtering). Useful for "
             "smoke-testing before a full backfill.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't actually push — just print which reviews would be processed.",
    )
    p.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose logging (DEBUG level).",
    )
    return p


async def _select_reviews(
    only_ids: list[str] | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    """Return [(review_id, result_json), ...] for completed reviews with payload.

    Filters out rows where ``result_json`` is NULL — those reviews never
    reached the synthesis stage and have nothing to serialise.
    """
    async with async_session() as db:
        stmt = (
            select(ReviewRow.review_id, ReviewRow.result_json)
            .where(ReviewRow.status == "completed")
            .where(ReviewRow.result_json.isnot(None))
            .order_by(ReviewRow.completed_at.asc())
        )
        if only_ids:
            stmt = stmt.where(ReviewRow.review_id.in_(only_ids))
        result = await db.execute(stmt)
        rows: list[tuple[str, dict[str, Any]]] = [
            (rid, payload) for rid, payload in result.all()
        ]
    return rows


def _reconstruct_result(payload: dict[str, Any]) -> Optional[Any]:
    """Materialise a PRISMAReviewResult from the persisted JSONB payload.

    Returns None if synthscholar can't be imported or validation fails
    (callers should treat this as a skip, not a hard error — backfill
    should keep going for other reviews).
    """
    try:
        from synthscholar.models import PRISMAReviewResult  # type: ignore[import-not-found]
    except Exception as exc:
        logger.error(
            "Cannot import synthscholar.models — install the agent package "
            "in this container before running the backfill: %s", exc,
        )
        return None
    try:
        return PRISMAReviewResult.model_validate(payload)
    except Exception as exc:
        logger.warning(
            "PRISMAReviewResult.model_validate failed (skipping): %s",
            str(exc)[:300],
        )
        return None


async def main_async(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    rows = await _select_reviews(args.review_id or None)
    if args.limit is not None:
        rows = rows[: args.limit]

    if not rows:
        logger.warning(
            "No completed reviews with a result_json matched. "
            "Did you pass --review-id for a review that hasn't completed?"
        )
        return 0

    logger.info(
        "Backfill plan: %d review%s%s",
        len(rows),
        "" if len(rows) == 1 else "s",
        " (dry-run — no pushes will fire)" if args.dry_run else "",
    )

    pushed = 0
    skipped = 0
    failed = 0

    for review_id, payload in rows:
        if args.dry_run:
            logger.info("[dry-run] would push %s", review_id)
            continue

        result = _reconstruct_result(payload)
        if result is None:
            skipped += 1
            continue

        # push_review_to_oxigraph never raises — it returns the HTTP status
        # on success, or None on skip/failure (and logs WARNING). Counts
        # below mirror that contract.
        status = await asyncio.to_thread(push_review_to_oxigraph, review_id, result)
        if status is None:
            failed += 1
            logger.warning("✗ push returned None for %s — see warning above", review_id)
        else:
            pushed += 1
            logger.info("✓ pushed %s — HTTP %s", review_id, status)

    logger.info(
        "Backfill done: pushed=%d skipped=%d failed=%d (out of %d total)",
        pushed, skipped, failed, len(rows),
    )
    # Non-zero exit if anything failed AND we were not in dry-run mode, so
    # CI / cron drivers can surface the problem.
    return 1 if (failed > 0 and not args.dry_run) else 0


def main() -> int:
    try:
        return asyncio.run(main_async())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
