# backend/models/schemas.py
"""
AIRP -- Pydantic Request/Response Schemas (T-046 / T-047 / T-048 / T-050 / T-051)

Pydantic v2 models for the auth and analysis endpoints' request bodies
and response shapes. Kept in a separate module from backend/models/orm.py
because these are API contract schemas (validated at the HTTP boundary),
not database table definitions -- the two evolve independently and mixing
them invites accidentally serialising a database-only field (like
password_hash) straight into an API response.

PRIORITY INSTRUCTION (project-wide rule): no `from __future__ import
annotations` in this module -- it breaks Pydantic v2 union resolution
at class-definition time.
"""

from datetime import datetime
from typing import Optional
import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

__all__ = [
    "UserRegisterRequest",
    "UserLoginRequest",
    "UserResponse",
    "TokenResponse",
    "TokenPayload",
    "AnalysisStartRequest",
    "AnalysisStartResponse",
    "AnalysisStatusResponse",
    "AgentStreamEventResponse",
    "InvestmentDecisionResponse",
    "HistoryEntryResponse",
    "HistoryResponse",
    "DocumentUploadResponse",
]

# ---------------------------------------------------------------------------
# Password policy
# ---------------------------------------------------------------------------

#: Minimum password length enforced at the API boundary. bcrypt itself
#: silently ignores bytes beyond 72, so the upper bound below keeps the
#: full password meaningfully hashed rather than truncated.
_MIN_PASSWORD_LENGTH = 8
_MAX_PASSWORD_LENGTH = 72


# ---------------------------------------------------------------------------
# Request schemas -- auth (T-046)
# ---------------------------------------------------------------------------


class UserRegisterRequest(BaseModel):
    """Body for POST /auth/register."""

    email: EmailStr = Field(..., description="User's email address")
    password: str = Field(
        ...,
        min_length=_MIN_PASSWORD_LENGTH,
        max_length=_MAX_PASSWORD_LENGTH,
        description=f"Plaintext password, {_MIN_PASSWORD_LENGTH}-"
        f"{_MAX_PASSWORD_LENGTH} characters. Never stored or logged as-is.",
    )
    display_name: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Optional display name shown in the dashboard",
    )

    @field_validator("password")
    @classmethod
    def _reject_whitespace_only(cls, value: str) -> str:
        """Reject a password that is technically long enough but blank."""
        if not value.strip():
            raise ValueError("password must not be empty or whitespace-only")
        return value


class UserLoginRequest(BaseModel):
    """Body for POST /auth/login."""

    email: EmailStr = Field(..., description="User's email address")
    password: str = Field(..., description="Plaintext password")


# ---------------------------------------------------------------------------
# Response schemas -- auth (T-046)
# ---------------------------------------------------------------------------


class UserResponse(BaseModel):
    """
    Public-safe user representation returned by /auth/register,
    /auth/login (nested under TokenResponse), and GET /auth/me.

    Deliberately excludes password_hash -- model_config's from_attributes
    lets this be built directly from a backend.models.orm.User ORM
    instance via UserResponse.model_validate(user), and since this
    schema has no password_hash field, there is no risk of it leaking
    into a response even if a future edit naively passed the whole ORM
    object through.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    display_name: Optional[str] = None
    is_active: bool
    created_at: datetime


class TokenResponse(BaseModel):
    """Body returned by both POST /auth/register and POST /auth/login."""

    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int
    user: UserResponse


class TokenPayload(BaseModel):
    """
    Decoded JWT claims, used internally by the auth dependency
    (backend.dependencies.auth.get_current_user) after verifying the
    token signature. Not returned directly in any API response.
    """

    sub: str = Field(..., description="Subject -- the user's UUID as a string")
    exp: int = Field(..., description="Expiry, Unix timestamp (seconds)")


# ---------------------------------------------------------------------------
# Request schema -- analysis trigger (T-047)
# ---------------------------------------------------------------------------

#: Exchanges AIRP currently supports -- mirrors backend.models.orm.ExchangeEnum.
_VALID_EXCHANGES = frozenset({"NSE", "BSE"})


class AnalysisStartRequest(BaseModel):
    """
    Body for POST /api/v1/analysis/start.

    ``company_name`` is the only field most callers need to supply (e.g.
    'TCS' or 'Tata Consultancy Services') -- the service layer
    (backend.services.analysis) resolves it to a Yahoo Finance ticker via
    a deterministic lookup table, the same pattern already used by
    backend.agents.valuation_agent._ticker_to_slug. ``ticker`` and
    ``exchange`` are optional overrides for callers (e.g. a future
    autocomplete-driven frontend) that already know the exact Yahoo
    Finance symbol and want to skip resolution entirely.
    """

    company_name: str = Field(
        ...,
        min_length=1,
        max_length=300,
        description="Company name or ticker as typed by the user, e.g. 'TCS'",
    )
    ticker: Optional[str] = Field(
        default=None,
        max_length=40,
        description=(
            "Optional Yahoo Finance ticker override (e.g. 'TCS.NS'). "
            "When omitted, the service layer resolves company_name."
        ),
    )
    exchange: Optional[str] = Field(
        default=None,
        description="Optional exchange override: 'NSE' or 'BSE'.",
    )

    @field_validator("company_name")
    @classmethod
    def _reject_blank_company_name(cls, value: str) -> str:
        """Reject a company_name that is whitespace-only."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("company_name must not be empty or whitespace-only")
        return stripped

    @field_validator("ticker")
    @classmethod
    def _normalize_ticker(cls, value: Optional[str]) -> Optional[str]:
        """Trim and uppercase an explicit ticker override, if provided."""
        if value is None:
            return None
        stripped = value.strip().upper()
        return stripped or None

    @field_validator("exchange")
    @classmethod
    def _validate_exchange(cls, value: Optional[str]) -> Optional[str]:
        """Reject an exchange override outside the supported set."""
        if value is None:
            return None
        normalized = value.strip().upper()
        if normalized not in _VALID_EXCHANGES:
            raise ValueError(
                f"exchange must be one of {sorted(_VALID_EXCHANGES)}, " f"got '{value}'"
            )
        return normalized


# ---------------------------------------------------------------------------
# Response schema -- analysis trigger (T-047)
# ---------------------------------------------------------------------------


class AnalysisStartResponse(BaseModel):
    """
    Body returned by POST /api/v1/analysis/start.

    Returned the moment the ``analyses`` row is committed and the
    LangGraph pipeline has been handed to FastAPI's BackgroundTasks --
    before any agent has actually run. Callers poll
    GET /api/v1/analysis/{job_id}/status (T-048) or open
    WS /api/v1/analysis/{job_id}/stream (T-049) to follow progress.
    """

    job_id: uuid.UUID = Field(description="UUID of the newly created analysis job")
    status: str = Field(description="Initial lifecycle status -- always 'pending'")
    company_name: str = Field(description="Resolved company display name")
    ticker: str = Field(description="Resolved Yahoo Finance ticker, e.g. 'TCS.NS'")
    exchange: str = Field(description="Resolved exchange -- 'NSE' or 'BSE'")


# ---------------------------------------------------------------------------
# Response schema -- analysis status polling (T-048)
# ---------------------------------------------------------------------------


class AnalysisStatusResponse(BaseModel):
    """
    Body returned by GET /api/v1/analysis/{job_id}/status.

    Reflects the actual state of the LangGraph pipeline for this job,
    read from the ``analyses`` table -- the same row
    ``backend.services.state_persistence.StatePersistenceService``
    updates after every node completes (T-033) and on failure (T-033's
    ``mark_failed``). Nothing in this schema is computed from the
    request itself; every field is read straight off that row (or, for
    ``current_phase``/``progress_percent``, derived from
    ``last_completed_node`` via
    ``backend.services.analysis.compute_progress``), so a stale poll
    interval simply returns the same snapshot twice rather than ever
    inventing a value.
    """

    job_id: uuid.UUID = Field(description="UUID of the analysis job")
    status: str = Field(
        description="Lifecycle status: 'pending', 'running', 'completed', or 'failed'"
    )
    current_phase: str = Field(
        description=(
            "Human-readable name of the pipeline phase currently executing "
            "(or the terminal phase, once status is 'completed' or 'failed')"
        )
    )
    completed_nodes: list[str] = Field(
        description=(
            "LangGraph node names completed so far, in execution order, "
            "derived from last_completed_node's position in the canonical "
            "pipeline sequence"
        )
    )
    progress_percent: int = Field(
        ge=0,
        le=100,
        description="0-100 estimate of pipeline completion, based on nodes run",
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Human-readable failure reason when status='failed'; else null",
    )
    requested_at: Optional[datetime] = Field(
        default=None, description="UTC timestamp when the analysis was triggered"
    )
    started_at: Optional[datetime] = Field(
        default=None,
        description="UTC timestamp when the LangGraph pipeline began executing",
    )
    completed_at: Optional[datetime] = Field(
        default=None,
        description="UTC timestamp when the pipeline finished, success or failure",
    )


# ---------------------------------------------------------------------------
# Response schema -- WebSocket live progress stream (T-049)
# ---------------------------------------------------------------------------


class AgentStreamEventResponse(BaseModel):
    """
    Shape of every JSON message sent over
    WS /api/v1/analysis/{job_id}/stream.

    Mirrors backend.services.ws_broadcaster.AgentStreamEvent field for
    field -- that module defines the runtime TypedDict the WebSocket
    route handler actually receives from
    backend.graph.nodes._run_broadcast and sends as-is;
    this Pydantic model exists purely so the websocket route's OpenAPI
    documentation (FastAPI can document WebSocket message schemas
    separately, surfaced in /docs) and any client-side codegen have a
    single, explicit, versioned contract to target, matching the
    existing pattern of every other *Response schema in this module.
    Not used to validate outgoing messages at runtime -- the route
    handler sends the TypedDict directly via WebSocket.send_json for
    minimal per-event overhead during a live stream, the same
    "schema documents the contract, the hot path skips re-validating
    it" tradeoff implicit in every other AIRP response model that is
    only ever constructed once per request rather than once per
    streamed event.
    """

    job_id: uuid.UUID = Field(
        description="UUID of the analysis job this event belongs to"
    )
    agent: str = Field(
        description=(
            "LangGraph node name that just completed, e.g. "
            "'fundamental_analyst', 'risk_officer', 'pdf_export'"
        )
    )
    status: str = Field(
        description="Pipeline lifecycle status at the moment this node completed"
    )
    output_preview: str = Field(
        description="Short human-readable summary of what this node produced"
    )
    progress_percent: int = Field(
        ge=0,
        le=100,
        description=(
            "0-100 estimate of pipeline completion -- identical to "
            "AnalysisStatusResponse.progress_percent at the same point in time"
        ),
    )
    is_final: bool = Field(
        description=(
            "True exactly once per job, on the event after which the server "
            "closes the WebSocket connection"
        )
    )


# ---------------------------------------------------------------------------
# Response schema -- analysis result (T-050)
# ---------------------------------------------------------------------------


class InvestmentDecisionResponse(BaseModel):
    """
    Body returned by GET /api/v1/analysis/{job_id}/result.

    Field-for-field identical to
    ``backend.agents.output_models.InvestmentDecision`` (the Portfolio
    Manager agent's Pydantic output model) -- this schema exists
    because that model lives in the ``backend.agents`` package and is
    constructed by LangGraph node code, not by this router; mirroring
    its shape here (rather than importing and reusing the agent model
    directly as a FastAPI response_model) keeps the same boundary
    every other schema in this module already enforces, between
    agent-internal models and the public HTTP response contract --
    see this module's own docstring on why backend.models.orm and
    backend.models.schemas are kept separate for the identical reason.

    Built from ``backend.services.analysis.AnalysisResultData.decision``,
    which is the exact ``InvestmentDecision.model_dump()`` dict
    persisted into ``analyses.state_snapshot`` (T-033) by
    ``portfolio_manager_node`` -- every field below round-trips through
    that JSONB column with no further computation in this router.
    """

    agent_name: str = Field(
        default="portfolio_manager",
        description=(
            "Always 'portfolio_manager' -- the agent that produced this decision"
        ),
    )
    analysis_id: str = Field(description="UUID of the parent Analysis job, as a string")
    company_name: str = Field(description="Human-readable company name")
    ticker: str = Field(description="Yahoo Finance ticker with exchange suffix")
    generated_at: datetime = Field(
        description="UTC timestamp when the Portfolio Manager produced this decision"
    )
    error: Optional[str] = Field(
        default=None,
        description=(
            "Always null for a result returned by this endpoint -- a non-null "
            "error here would mean the Portfolio Manager itself failed, which "
            "the pipeline never persists as status='completed'"
        ),
    )

    verdict: str = Field(
        description="Final investment recommendation: BUY, HOLD, or SELL"
    )
    conviction_score: int = Field(
        ge=1, le=10, description="Portfolio Manager confidence in the verdict, 1-10"
    )
    price_target: Optional[str] = Field(
        default=None, description="Implied price target, or null if inconclusive"
    )
    time_horizon: str = Field(description="Suggested holding period for this verdict")

    executive_summary: str = Field(description="2-3 paragraph executive summary")
    investment_thesis: str = Field(
        description="Core investment thesis in 3-5 sentences"
    )
    bull_case: str = Field(description="Bull case argument")
    bear_case: str = Field(description="Bear case, incorporating Contrarian/Risk flags")
    risk_summary: str = Field(description="Top risks ranked by potential impact")
    valuation_summary: str = Field(description="DCF and peer comparison summary")

    key_risks: list[str] = Field(
        default_factory=list, description="Structured list of the most important risks"
    )
    key_catalysts: list[str] = Field(
        default_factory=list,
        description="Structured list of factors that could move the thesis forward",
    )

    contrarian_response: str = Field(
        description=(
            "How the Portfolio Manager addressed the Contrarian's " "strongest argument"
        )
    )
    debate_rounds_used: int = Field(
        ge=1, description="Number of agent debate rounds completed before this decision"
    )
    agent_weights: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "Weight (0.0-1.0) assigned to each agent's output, keyed by agent_name"
        ),
    )
    summary: str = Field(
        description="One-sentence summary suitable for dashboard display"
    )


# ---------------------------------------------------------------------------
# Response schemas -- analysis history (T-050)
# ---------------------------------------------------------------------------


class HistoryEntryResponse(BaseModel):
    """
    One row of GET /api/v1/analysis/history's paginated result.

    Deliberately a much smaller shape than ``InvestmentDecisionResponse``
    -- a history list shows enough to identify and triage past analyses
    (company, verdict, when, status) without the cost of returning the
    full Investment Memo text for every row on every page. A caller
    that wants the full decision for a specific row follows up with
    GET /api/v1/analysis/{job_id}/result using this entry's ``job_id``.
    """

    job_id: uuid.UUID = Field(description="UUID of the analysis job")
    company_name: str = Field(description="Company display name")
    ticker: str = Field(description="Yahoo Finance ticker with exchange suffix")
    exchange: str = Field(description="Exchange -- 'NSE' or 'BSE'")
    status: str = Field(
        description="Lifecycle status: 'pending', 'running', 'completed', or 'failed'"
    )
    requested_at: datetime = Field(
        description="UTC timestamp when the analysis was triggered"
    )
    completed_at: Optional[datetime] = Field(
        default=None, description="UTC timestamp when the pipeline finished, if it has"
    )
    verdict: Optional[str] = Field(
        default=None,
        description=(
            "Final verdict (BUY/HOLD/SELL) once available; null for a "
            "pending, running, or failed analysis"
        ),
    )
    conviction_score: Optional[int] = Field(
        default=None,
        ge=1,
        le=10,
        description="Conviction score (1-10) once available; null until then",
    )


class HistoryResponse(BaseModel):
    """
    Body returned by GET /api/v1/analysis/history.

    ``limit``/``offset`` echo back exactly what was requested (after
    the router's own clamping via FastAPI's ``Query(ge=..., le=...)``
    validation -- see backend.routers.analysis.get_analysis_history_endpoint)
    so a caller can compute the next page's offset
    (``offset + len(items)``) without tracking pagination state
    anywhere except this response, and ``has_more`` saves it from
    having to compare that arithmetic against ``total_count`` itself.
    """

    items: list[HistoryEntryResponse] = Field(
        description="This page's analyses, newest first"
    )
    total_count: int = Field(
        ge=0, description="Total number of analyses this user has ever triggered"
    )
    limit: int = Field(description="Page size used for this request")
    offset: int = Field(ge=0, description="Number of rows skipped before this page")
    has_more: bool = Field(
        description="True when at least one further row exists beyond this page"
    )


# ---------------------------------------------------------------------------
# Response schema -- document upload (T-051)
# ---------------------------------------------------------------------------


class DocumentUploadResponse(BaseModel):
    """
    Body returned by POST /api/v1/documents/upload.

    There is no matching ``*Request`` schema in this module because the
    request body is ``multipart/form-data`` (a PDF file plus a couple of
    plain form fields), not JSON -- FastAPI validates that shape directly
    via ``UploadFile``/``Form(...)`` parameters on the route handler
    itself (see backend.routers.documents.upload_document), the same
    reason backend.routers.analysis's WebSocket route has no Pydantic
    request schema either.

    ``chunks_ingested`` is the number of ChromaDB chunks written, not the
    number of pages or characters -- a caller wanting to confirm the
    upload is now queryable cares about "did at least one chunk land in
    the vector store", which this field answers directly.
    """

    company_name: str = Field(description="Resolved company display name")
    ticker: str = Field(description="Yahoo Finance ticker with exchange suffix")
    exchange: str = Field(
        description="Exchange the company was resolved to: NSE or BSE"
    )
    source_filename: str = Field(description="Original filename of the uploaded PDF")
    doc_type: str = Field(
        description="Document category stored in ChromaDB metadata: "
        "'annual_report' or 'transcript'"
    )
    chunks_ingested: int = Field(
        ge=0,
        description=(
            "Number of text chunks embedded and stored in ChromaDB. "
            "0 means the PDF was accepted but contained no extractable "
            "text (e.g. a scanned, image-only PDF) -- nothing was "
            "embedded, so it will not be retrievable by agents."
        ),
    )
    characters_extracted: int = Field(
        ge=0, description="Total character count of the text extracted from the PDF"
    )
