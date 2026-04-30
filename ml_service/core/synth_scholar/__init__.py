"""SynthScholar — PRISMA-guided literature review pipeline.

Ported from aep-knowledge-synthesis/backend. Uses an independent SQLAlchemy
2.0 async engine for its own tables (reviews, plus synthscholar's bundled
article_store / review_cache / pipeline_checkpoints), separate from the
existing ml_service raw-asyncpg pool used by jwt_auth + structsense.

Entry point: `core.synth_scholar.routes.router` (mounted at /api/synth-scholar
by core/main.py). All endpoints require a valid JWT (Depends(get_current_user)).
"""
