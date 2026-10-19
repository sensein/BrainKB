"""SQLAlchemy ORM models for SynthScholar reviews.

Complex nested objects (protocol, result) are stored as JSONB. owner_email
is the only addition over the upstream model — it lets us scope listings to
the calling user without joining against the JWT user table.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class ReviewRow(Base):
    """Persistent review session."""

    __tablename__ = "reviews"

    review_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")

    protocol_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    result_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    pipeline_log: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    progress_step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    share_to_cache: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    run_request_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    checkpoint_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_completed_step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Typed progress state (written on each batch flush + terminal events).
    stage: Mapped[str | None] = mapped_column(String(200), nullable=True)
    stage_idx: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stage_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stage_done_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stage_remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)
    articles_included: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latest_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # JWT email of the user who created the review. Listings are filtered by
    # this in the routes layer; admins see everything.
    owner_email: Mapped[str | None] = mapped_column(String(320), nullable=True)

    # Cross-worker plan-confirmation gate. The pipeline lives in one gunicorn
    # worker but SSE/POST requests round-robin across all of them, so the
    # plan and the user's response have to flow through Postgres for any
    # other worker to see them.
    pending_plan_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    pending_plan_iteration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    plan_response_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Where the review came from: "pipeline" (run here) or "import" (a local
    # SynthScholar run's output directory, uploaded). Imports keep their files in
    # review_artifacts and the import's own provenance in import_json.
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="pipeline")
    import_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Every push of the review into BrainKB's graph database: space, graph IRI,
    # ingest job, who and when. A review is ingested once (its RDF is append-only).
    graph_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Flow counts + included count for listings, so a list never has to load and
    # re-validate every review's full result (an imported review can be 30 MB).
    summary_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class ReviewArtifactRow(Base):
    """A file belonging to a review: an imported run's PDF, manuscript, figures,
    tables, RDF, verification reports; or a PDF generated on demand. Stored in
    Postgres (same database, same backups); content-addressed by sha256."""

    __tablename__ = "review_artifacts"

    review_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("reviews.review_id", ondelete="CASCADE"), primary_key=True)
    path: Mapped[str] = mapped_column(String(512), primary_key=True)   # relative, e.g. figures/fig_prisma.svg
    kind: Mapped[str] = mapped_column(String(40), nullable=False, default="other")
    media_type: Mapped[str] = mapped_column(String(120), nullable=False, default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
