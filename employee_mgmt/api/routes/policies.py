"""Policy Brain API routes for the Employee Management module.

Provides tenant-isolated policy drafting, fail-closed publishing with approval
checks, visibility-filtered retrieval, and citation-backed policy search.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from threading import Lock
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

router = APIRouter(prefix="/policies", tags=["policies"])

UserRole = Literal["employee", "manager", "hr", "admin"]
PolicyVisibility = Literal["all", "manager", "hr", "admin"]
PolicyStatus = Literal["draft", "published", "archived"]

ALLOWED_ROLES: frozenset[str] = frozenset({"employee", "manager", "hr", "admin"})
POLICY_MANAGER_ROLES: frozenset[str] = frozenset({"hr", "admin"})

_ROLE_VISIBILITY_ACCESS: dict[UserRole, frozenset[PolicyVisibility]] = {
    "employee": frozenset({"all"}),
    "manager": frozenset({"all", "manager"}),
    "hr": frozenset({"all", "manager", "hr"}),
    "admin": frozenset({"all", "manager", "hr", "admin"}),
}

_STOP_WORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "how",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "what",
        "when",
        "where",
        "who",
        "with",
    }
)


# ---------------------------------------------------------------------------
# Request / Response & Session Schemas
# (Will be moved to schemas/policy.py once schema files are implemented.)
# ---------------------------------------------------------------------------


class SessionUser(BaseModel):
    """Verified user identity loaded from server-side session state."""

    model_config = ConfigDict(frozen=True)

    user_id: str = Field(..., min_length=1, max_length=100)
    tenant_id: str = Field(..., min_length=1, max_length=100)
    role: UserRole


class PolicyChunkResponse(BaseModel):
    """Individual indexed chunk of a policy document."""

    chunk_index: int = Field(..., ge=0)
    text: str


class PolicyCreateRequest(BaseModel):
    """Payload to create a new draft policy document."""

    title: str = Field(..., min_length=3, max_length=200)
    category: str = Field(default="general", min_length=2, max_length=60)
    content: str = Field(..., min_length=20, max_length=50_000)
    visibility: PolicyVisibility = Field(default="all")

    @field_validator("title", "category", "content")
    @classmethod
    def strip_non_empty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Field cannot be empty or whitespace.")
        return cleaned

    @field_validator("category")
    @classmethod
    def normalize_category(cls, value: str) -> str:
        return value.lower()


class PolicyPublishRequest(BaseModel):
    """Approval metadata required for the high-risk policy.publish action."""

    approval_id: str = Field(
        ...,
        min_length=4,
        max_length=100,
        description="Verified approval reference authorizing policy publication.",
    )
    approved_by: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="User ID of the approver (must differ from the publisher).",
    )
    change_summary: str = Field(
        ...,
        min_length=5,
        max_length=500,
        description="Brief audit note describing what changed in this publication.",
    )

    @field_validator("approval_id", "approved_by", "change_summary")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Approval fields cannot be blank.")
        return cleaned


class PolicyResponse(BaseModel):
    """Full representation of a policy record."""

    id: str
    tenant_id: str
    title: str
    category: str
    content: str
    visibility: PolicyVisibility
    status: PolicyStatus
    version: int
    chunks: list[PolicyChunkResponse]
    created_by: str
    created_at: str
    published_at: str | None = None
    published_by: str | None = None
    approval_id: str | None = None
    approved_by: str | None = None
    change_summary: str | None = None


class PolicyListResponse(BaseModel):
    """Paginated list of policies visible to the current user."""

    total: int
    limit: int
    offset: int
    items: list[PolicyResponse]


class PolicyQueryRequest(BaseModel):
    """Search query against published policies."""

    question: str = Field(..., min_length=3, max_length=500)
    top_k: int = Field(default=3, ge=1, le=10)

    @field_validator("question")
    @classmethod
    def strip_question(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 3:
            raise ValueError("Question must be at least 3 characters long.")
        return cleaned


class PolicyCitation(BaseModel):
    """Grounded citation pointing to an exact published policy chunk."""

    policy_id: str
    policy_title: str
    category: str
    version: int
    chunk_index: int
    excerpt: str
    score: float


class PolicyQueryResponse(BaseModel):
    """Citation-backed policy search response."""

    question: str
    grounded: bool
    answer: str
    citations: list[PolicyCitation]


# ---------------------------------------------------------------------------
# Temporary Thread-Safe In-Memory Store
# (Will be replaced by services/policy_service.py + db/session.py once created.)
# ---------------------------------------------------------------------------

_STORE_LOCK = Lock()
_POLICY_STORE: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Security & Helper Functions
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def get_current_user(request: Request) -> SessionUser:
    """Extract verified user identity from server session state.

    Fails closed with 401 if authentication middleware has not populated
    `request.state.user`. Raw client-supplied identity headers are never trusted.
    """
    session_user = getattr(request.state, "user", None)
    if session_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: no verified server session found.",
        )

    if isinstance(session_user, SessionUser):
        return session_user

    if isinstance(session_user, dict):
        user_id = str(session_user.get("user_id", "")).strip()
        tenant_id = str(session_user.get("tenant_id", "")).strip()
        role = str(session_user.get("role", "")).strip().lower()
    else:
        user_id = str(getattr(session_user, "user_id", "")).strip()
        tenant_id = str(getattr(session_user, "tenant_id", "")).strip()
        role = str(getattr(session_user, "role", "")).strip().lower()

    if not user_id or not tenant_id or role not in ALLOWED_ROLES:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid server session user context.",
        )

    return SessionUser(user_id=user_id, tenant_id=tenant_id, role=role)  # type: ignore[arg-type]


def _require_policy_manager(current_user: SessionUser) -> None:
    """Ensure only HR or Admin users can manage or publish policies."""
    if current_user.role not in POLICY_MANAGER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only HR or Admin roles are authorized to manage policies.",
        )


def _can_view_policy(
    current_user: SessionUser, policy_record: dict[str, Any]
) -> bool:
    """Check tenant isolation, visibility scope, and publication status."""
    if policy_record["tenant_id"] != current_user.tenant_id:
        return False

    allowed_visibilities = _ROLE_VISIBILITY_ACCESS[current_user.role]
    if policy_record["visibility"] not in allowed_visibilities:
        return False

    if (
        policy_record["status"] != "published"
        and current_user.role not in POLICY_MANAGER_ROLES
    ):
        return False

    return True


def _chunk_policy_content(content: str, max_chars: int = 500) -> list[dict[str, Any]]:
    """Split policy text deterministically into citation-ready chunks."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]
    raw_chunks: list[str] = []

    for paragraph in paragraphs:
        if len(paragraph) <= max_chars:
            raw_chunks.append(paragraph)
            continue

        words = paragraph.split()
        buffer: list[str] = []
        current_len = 0

        for word in words:
            addition = len(word) + (1 if buffer else 0)
            if current_len + addition > max_chars and buffer:
                raw_chunks.append(" ".join(buffer))
                buffer = [word]
                current_len = len(word)
            else:
                buffer.append(word)
                current_len += addition

        if buffer:
            raw_chunks.append(" ".join(buffer))

    return [
        {"chunk_index": idx, "text": chunk_text}
        for idx, chunk_text in enumerate(raw_chunks)
    ]


def _tokenize(text: str) -> set[str]:
    """Extract meaningful lowercase tokens for deterministic keyword matching."""
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return {t for t in tokens if len(t) >= 2 and t not in _STOP_WORDS}


# ---------------------------------------------------------------------------
# Route Handlers
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=PolicyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new draft policy",
)
async def create_policy_draft(
    payload: PolicyCreateRequest,
    current_user: SessionUser = Depends(get_current_user),
) -> PolicyResponse:
    """Create a tenant-scoped policy in draft state with deterministic chunks."""
    _require_policy_manager(current_user)

    chunks = _chunk_policy_content(payload.content)
    if not chunks:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Policy content could not be segmented into valid chunks.",
        )

    policy_id = f"pol_{uuid4().hex[:12]}"
    record: dict[str, Any] = {
        "id": policy_id,
        "tenant_id": current_user.tenant_id,
        "title": payload.title,
        "category": payload.category,
        "content": payload.content,
        "visibility": payload.visibility,
        "status": "draft",
        "version": 1,
        "chunks": chunks,
        "created_by": current_user.user_id,
        "created_at": _utc_now_iso(),
        "published_at": None,
        "published_by": None,
        "approval_id": None,
        "approved_by": None,
        "change_summary": None,
    }

    with _STORE_LOCK:
        _POLICY_STORE[policy_id] = record

    return PolicyResponse(**record)


@router.get(
    "",
    response_model=PolicyListResponse,
    status_code=status.HTTP_200_OK,
    summary="List policies visible to the authenticated user",
)
async def list_policies(
    category: str | None = Query(default=None, min_length=2, max_length=60),
    policy_status: PolicyStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: SessionUser = Depends(get_current_user),
) -> PolicyListResponse:
    """List tenant-scoped policies filtered by role visibility and optional filters."""
    if (
        policy_status is not None
        and policy_status != "published"
        and current_user.role not in POLICY_MANAGER_ROLES
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only HR or Admin roles can filter non-published policies.",
        )

    normalized_category = category.strip().lower() if category else None

    with _STORE_LOCK:
        records = list(_POLICY_STORE.values())

    visible_records = [
        rec
        for rec in records
        if _can_view_policy(current_user, rec)
        and (normalized_category is None or rec["category"] == normalized_category)
        and (policy_status is None or rec["status"] == policy_status)
    ]

    visible_records.sort(key=lambda item: item["created_at"], reverse=True)
    paginated = visible_records[offset : offset + limit]

    return PolicyListResponse(
        total=len(visible_records),
        limit=limit,
        offset=offset,
        items=[PolicyResponse(**rec) for rec in paginated],
    )


@router.get(
    "/{policy_id}",
    response_model=PolicyResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a single policy by ID",
)
async def get_policy(
    policy_id: str,
    current_user: SessionUser = Depends(get_current_user),
) -> PolicyResponse:
    """Retrieve a policy if it belongs to the user's tenant and visibility scope."""
    with _STORE_LOCK:
        record = _POLICY_STORE.get(policy_id)

    if record is None or not _can_view_policy(current_user, record):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Policy not found.",
        )

    return PolicyResponse(**record)


@router.post(
    "/{policy_id}/publish",
    response_model=PolicyResponse,
    status_code=status.HTTP_200_OK,
    summary="Publish a draft policy (high-risk action, requires approval)",
)
async def publish_policy(
    policy_id: str,
    payload: PolicyPublishRequest,
    current_user: SessionUser = Depends(get_current_user),
) -> PolicyResponse:
    """Publish a draft policy.

    Guardrail: `policy.publish` is a high-risk action and fails closed unless
    authorized by HR/Admin with an explicit, non-self approval reference.
    """
    _require_policy_manager(current_user)

    if payload.approved_by == current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "High-risk action blocked (policy.publish): "
                "self-approval is not permitted."
            ),
        )

    with _STORE_LOCK:
        record = _POLICY_STORE.get(policy_id)
        if record is None or record["tenant_id"] != current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Policy not found.",
            )

        if record["status"] != "draft":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot publish a policy in '{record['status']}' state.",
            )

        if not record["chunks"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot publish a policy without indexed chunks.",
            )

        updated = {
            **record,
            "status": "published",
            "published_at": _utc_now_iso(),
            "published_by": current_user.user_id,
            "approval_id": payload.approval_id,
            "approved_by": payload.approved_by,
            "change_summary": payload.change_summary,
        }
        _POLICY_STORE[policy_id] = updated

    return PolicyResponse(**updated)


@router.post(
    "/query",
    response_model=PolicyQueryResponse,
    status_code=status.HTTP_200_OK,
    summary="Search published policies with grounded citations",
)
async def query_policies(
    payload: PolicyQueryRequest,
    current_user: SessionUser = Depends(get_current_user),
) -> PolicyQueryResponse:
    """Return citation-backed excerpts strictly from published, visible policies."""
    query_tokens = _tokenize(payload.question)
    if not query_tokens:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please provide a more specific policy question.",
        )

    with _STORE_LOCK:
        records = list(_POLICY_STORE.values())

    scored_citations: list[PolicyCitation] = []
    for record in records:
        if record["status"] != "published" or not _can_view_policy(current_user, record):
            continue

        title_tokens = _tokenize(record["title"])
        for chunk in record["chunks"]:
            chunk_tokens = _tokenize(chunk["text"])
            overlap = query_tokens.intersection(chunk_tokens | title_tokens)
            if not overlap:
                continue

            score = round(len(overlap) / len(query_tokens), 4)
            scored_citations.append(
                PolicyCitation(
                    policy_id=record["id"],
                    policy_title=record["title"],
                    category=record["category"],
                    version=record["version"],
                    chunk_index=chunk["chunk_index"],
                    excerpt=chunk["text"],
                    score=score,
                )
            )

    scored_citations.sort(key=lambda item: item.score, reverse=True)
    top_citations = scored_citations[: payload.top_k]

    if not top_citations:
        return PolicyQueryResponse(
            question=payload.question,
            grounded=False,
            answer=(
                "No published policy matching your query was found within your "
                "access scope. Please contact HR for clarification."
            ),
            citations=[],
        )

    primary = top_citations[0]
    answer_text = (
        f"According to '{primary.policy_title}' (v{primary.version}, "
        f"chunk #{primary.chunk_index}): {primary.excerpt}"
    )

    return PolicyQueryResponse(
        question=payload.question,
        grounded=True,
        answer=answer_text,
        citations=top_citations,
    )


__all__ = [
    "router",
    "SessionUser",
    "PolicyCreateRequest",
    "PolicyPublishRequest",
    "PolicyResponse",
    "PolicyListResponse",
    "PolicyQueryRequest",
    "PolicyCitation",
    "PolicyQueryResponse",
    "get_current_user",
]