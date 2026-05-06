"""API request / response schemas.

Thin wrappers around synthscholar models for API boundaries, plus
review-session management models. Imports from `synthscholar.models` are
late-bound below so this module loads even when the library hasn't been
installed yet (e.g. lint / typecheck environments without the heavy
dependency tree).
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional, Any
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from synthscholar.models import (  # type: ignore[import-not-found]
    RoBTool,
    DataChartingRubric,
    PRISMANarrativeRow,
    CriticalAppraisalRubric,
    GroundingValidationResult,
)


# ────────────────────── Request Schemas ────────────────────────────────

class ProtocolRequest(BaseModel):
    """Create or update a review protocol."""
    title: str = Field(..., min_length=1, max_length=500)
    objective: str = ""
    pico_population: str = ""
    pico_intervention: str = ""
    pico_comparison: str = ""
    pico_outcome: str = ""
    inclusion_criteria: str = ""
    exclusion_criteria: str = ""
    databases: list[str] = Field(
        default_factory=lambda: [
            "pubmed", "biorxiv", "medrxiv",
            "europe_pmc", "openalex", "crossref", "doaj",
            "semantic_scholar", "arxiv", "core",
        ]
    )
    date_range_start: str = ""
    date_range_end: str = ""
    max_hops: int = Field(default=1, ge=0, le=10)
    registration_number: str = ""
    protocol_url: str = ""
    funding_sources: str = ""
    competing_interests: str = ""
    rob_tool: RoBTool = RoBTool.ROB_2
    charting_questions: list[str] = Field(default_factory=list)
    appraisal_domains: list[str] = Field(default_factory=list)

    grouping_dimension: str = Field(
        default="disorder_cohort",
        description=(
            "DataChartingRubric attribute used for bucketing during per-group analysis."
        ),
    )
    default_group_questions: list[str] = Field(default_factory=list, max_length=10)
    per_group_questions: dict[str, list[str]] = Field(default_factory=dict)


class RunReviewRequest(BaseModel):
    """Start a review pipeline run."""
    protocol: ProtocolRequest
    model: str = "anthropic/claude-sonnet-4"
    max_results_per_query: int = Field(default=20, ge=5, le=1000)
    related_depth: int = Field(default=1, ge=0, le=10)
    biorxiv_days: int = Field(default=180, ge=30, le=730)
    enable_cache: bool = True
    extract_data: bool = True
    data_items: list[str] = Field(default_factory=list)
    auto_confirm: bool = True
    max_plan_iterations: int = Field(default=3, ge=1, le=10)
    output_synthesis_style: Literal["paragraph", "question_answer", "bullet_list", "table"] = "paragraph"
    max_articles: Optional[int] = Field(default=None, ge=10, le=10000)
    concurrency: int = Field(default=5, ge=1, le=50)
    # Caller-supplied OpenRouter API key. The frontend resolves this from the
    # signed-in user's personal key (sessionStorage) or the admin-shared key
    # (admin_setting `shared.openrouter_api_key`). The backend uses it as the
    # primary key for the run; if absent, falls back to OPENROUTER_API_KEY env.
    # Not persisted to the review's run_request_json — see routes.py.
    openrouter_api_key: Optional[str] = Field(default=None, exclude=True, repr=False)


class CompareRunRequest(BaseModel):
    """Start a compare-mode review with 2–5 models."""
    protocol: ProtocolRequest
    compare_models: list[str] = Field(..., min_length=2, max_length=5)
    consensus_model: Optional[str] = None
    max_results_per_query: int = Field(default=20, ge=5, le=1000)
    related_depth: int = Field(default=1, ge=0, le=10)
    biorxiv_days: int = Field(default=180, ge=30, le=730)
    enable_cache: bool = True
    extract_data: bool = True
    data_items: list[str] = Field(default_factory=list)
    auto_confirm: bool = True
    max_plan_iterations: int = Field(default=3, ge=1, le=10)
    output_synthesis_style: Literal["paragraph", "question_answer", "bullet_list", "table"] = "paragraph"
    max_articles: Optional[int] = Field(default=None, ge=10, le=10000)
    concurrency: int = Field(default=5, ge=1, le=50)
    # See RunReviewRequest.openrouter_api_key — same semantics.
    openrouter_api_key: Optional[str] = Field(default=None, exclude=True, repr=False)


class RetryRequest(BaseModel):
    enable_cache: Optional[bool] = None
    resume: bool = True
    # OpenRouter API key for the re-run. The key is intentionally NOT
    # persisted with the original review (`run_request` is stored with
    # ``exclude={"openrouter_api_key"}`` for security), so every retry has
    # to provide it again — same shape as ``RunReviewRequest`` /
    # ``CompareRunRequest``. Excluded from logs / model dumps via
    # ``exclude=True, repr=False``.
    openrouter_api_key: Optional[str] = Field(default=None, exclude=True, repr=False)


class PlanResponseRequest(BaseModel):
    approved: bool
    feedback: str = ""

    @model_validator(mode="after")
    def feedback_required_when_rejected(self) -> "PlanResponseRequest":
        if not self.approved and not self.feedback.strip():
            raise ValueError("feedback is required when approved=false")
        return self


# ────────────────────── Response Schemas ───────────────────────────────

class ReviewStatus(str, Enum):
    PENDING = "pending"
    PLAN_PENDING = "plan_pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ArticleSummary(BaseModel):
    pmid: str
    title: str
    authors: str
    year: str
    journal: str
    doi: str
    source: str
    inclusion_status: str
    rob_overall: str = ""
    study_design: str = ""
    quality_score: float = 0.0


class EvidenceSpanResponse(BaseModel):
    text: str
    paper_pmid: str
    paper_title: str
    section: str
    relevance_score: float
    claim: str
    doi: str


class ScreeningLogResponse(BaseModel):
    pmid: str
    title: str
    decision: str
    reason: str
    stage: str


class GRADEResponse(BaseModel):
    outcome: str
    overall_certainty: str
    summary: str
    domains: dict = Field(default_factory=dict)


class FlowResponse(BaseModel):
    """PRISMA flow counts."""
    db_pubmed: int = 0
    db_biorxiv: int = 0
    db_medrxiv: int = 0
    db_related: int = 0
    db_hops: int = 0
    db_other_sources: dict[str, int] = Field(default_factory=dict)
    total_identified: int = 0
    duplicates_removed: int = 0
    after_dedup: int = 0
    screened_title_abstract: int = 0
    excluded_title_abstract: int = 0
    sought_fulltext: int = 0
    not_retrieved: int = 0
    assessed_eligibility: int = 0
    excluded_eligibility: int = 0
    excluded_reasons: dict[str, int] = Field(default_factory=dict)
    included_synthesis: int = 0


class ReviewSummaryResponse(BaseModel):
    review_id: str
    status: ReviewStatus
    title: str
    created_at: str
    completed_at: Optional[str] = None
    flow: Optional[FlowResponse] = None
    included_count: int = 0
    is_public: bool = False
    share_to_cache: bool = False
    error: Optional[str] = None
    stage: Optional[str] = None
    stage_index: Optional[int] = None
    stage_total: Optional[int] = None
    stage_done: Optional[int] = None
    stage_remaining: Optional[int] = None
    articles_included: Optional[int] = None


class CompareReviewSummaryResponse(BaseModel):
    review_id: str
    status: ReviewStatus
    compare_models: list[str]
    created_at: str


class ReviewDetailResponse(BaseModel):
    review_id: str
    status: ReviewStatus
    title: str
    created_at: str
    completed_at: Optional[str] = None
    is_public: bool = False
    share_to_cache: bool = False
    enable_cache: Optional[bool] = None
    last_completed_step: int = 0
    run_request: Optional[dict] = None
    research_question: str = ""
    flow: Optional[FlowResponse] = None
    included_articles: list[ArticleSummary] = Field(default_factory=list)
    screening_log: list[ScreeningLogResponse] = Field(default_factory=list)
    evidence_spans: list[EvidenceSpanResponse] = Field(default_factory=list)
    synthesis_text: str = ""
    bias_assessment: str = ""
    limitations: str = ""
    grade_assessments: list[GRADEResponse] = Field(default_factory=list)
    search_queries: list[str] = Field(default_factory=list)
    data_charting_rubrics: list[DataChartingRubric] = Field(default_factory=list)
    narrative_rows: list[PRISMANarrativeRow] = Field(default_factory=list)
    critical_appraisals: list[CriticalAppraisalRubric] = Field(default_factory=list)
    grounding_validation: Optional[GroundingValidationResult] = None
    structured_abstract: str = ""
    introduction_text: str = ""
    conclusions_text: str = ""
    quality_checklist: dict[str, bool] = Field(default_factory=dict)
    error: Optional[str] = None
    compare_result: Optional[dict] = None
    per_group_analysis: Optional[dict] = None


class ProgressEvent(BaseModel):
    """SSE progress event.

    `event_type` is the transport category (progress | history | plan_review |
    completed | failed | cancelled | keepalive). `kind` is the pipeline-level
    classification (log | stage_start | stage_done | article_start |
    article_done | plan_ready | done) produced by the server-side parser.
    """
    review_id: str
    step: int
    message: str
    timestamp: str = ""
    event_type: str = "progress"
    source: Optional[str] = None
    plan: Optional[dict] = None

    kind: str = "log"
    stage: Optional[str] = None
    stage_index: Optional[int] = None
    stage_total: Optional[int] = None
    stage_done: Optional[int] = None
    stage_remaining: Optional[int] = None
    articles_included: Optional[int] = None


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = ""
    models: list[str] = Field(default_factory=list)
    rob_tools: list[str] = Field(default_factory=list)


class VisibilityRequest(BaseModel):
    is_public: bool


class CacheSharingRequest(BaseModel):
    share_to_cache: bool


# ────────────────────── Search Schemas ────────────────────────────────

LiteratureSearchMode = Literal["keyword", "by_title", "semantic"]
ReviewSearchMode = Literal["keyword", "semantic"]


class LiteratureSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    mode: LiteratureSearchMode = "keyword"
    top: int = Field(default=20, ge=1, le=200)
    summarize: bool = False
    summary_top: int = Field(default=15, ge=1, le=100)
    summary_model: str = "anthropic/claude-sonnet-4"


class ReviewSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    mode: ReviewSearchMode = "keyword"
    top: int = Field(default=20, ge=1, le=200)
    include_expired: bool = False


class SearchArticleResult(BaseModel):
    pmid: str = ""
    title: str = ""
    abstract: str = ""
    authors: str = ""
    journal: str = ""
    year: str = ""
    doi: str = ""
    pmc_id: str = ""
    source: str = ""
    similarity: Optional[float] = None


class SearchReviewResult(BaseModel):
    review_id: str = ""
    criteria_fingerprint: str
    title: str = ""
    research_question: str = ""
    model_name: str
    created_at: datetime
    similarity: Optional[float] = None


class SearchSynthesisGroup(BaseModel):
    label: str
    n_studies: int
    aggregate_finding: str
    representative_pmids: list[str] = Field(default_factory=list)
    caveats: str = ""


class SearchSynthesisResponse(BaseModel):
    query: str
    n_articles_synthesized: int
    overview: str
    overall_caveats: str = ""
    groups: list[SearchSynthesisGroup] = Field(default_factory=list)


class LiteratureSearchResponse(BaseModel):
    query: str
    mode: LiteratureSearchMode
    results: list[SearchArticleResult]
    synthesis: Optional[SearchSynthesisResponse] = None


class ReviewSearchResponse(BaseModel):
    query: str
    mode: ReviewSearchMode
    results: list[SearchReviewResult]
