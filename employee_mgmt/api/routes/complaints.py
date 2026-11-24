"""Anonymous Complaint Box API routes for the Employee Management module.

Enforces strict whistleblower privacy:
- Anonymous submissions and status lookups never require authentication and
  never inspect or store user_id, employee_id, IP address, User-Agent, or
  session metadata.
- Tracking tokens are generated with `secrets` and stored only as SHA-256 hashes.
- HR/Admin triage is tenant-scoped and enforces a deterministic state machine.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import re
import secrets
from threading import Lock
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .policies import SessionUser, get_current_user

router = APIRouter(prefix="/complaints", tags=["complaints"])

ComplaintCategory = Literal[
    "harassment",
    "discrimination",
    "safety",
    "ethics",
    "retaliation",
    "policy_violation",
    "other",
]
ComplaintStatus = Literal[
    "submitted",
    "under_review",
    "action_taken",
    "resolved",
    "dismissed",
]

# Restricted strictly to HR and Admin so complaints cannot be viewed by line managers.
COMPLAINT_REVIEWER_ROLES: frozenset[str] = frozenset({"hr", "admin"})

_TENANT_SLUG_PATTERN = re.compile(r"^[A-Za-z0-9_-]{2,100}$")

# Explicit complaint lifecycle state machine.
ALLOWED_TRANSITIONS: dict[ComplaintStatus, frozenset[ComplaintStatus]] = {
    "submitted": frozenset({"under_review", "dismissed"}),
    "under_review": frozenset({"action_taken", "resolved", "dismissed"}),
    "action_taken": frozenset({"resolved"}),
    "resolved": frozenset(),
    "dismissed": frozenset(),
}


# ---------------------------------------------------------------------------
# Request / Response Schemas
# (Will be moved to dedicated schema modules once created.)
# ---------------------------------------------------------------------------


class ComplaintCreateRequest(BaseModel):
    """Privacy-enforced payload for submitting an anonymous complaint.

    `extra="forbid"` rejects any accidentally included identifying fields
    such as `user_id`, `employee_id`, or `email`.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(
        default="default",
        min_length=2,
        max_length=100,
        description="Organization/tenant slug to route the complaint to HR.",
    )
    category: ComplaintCategory = Field(default="other")
    subject: str = Field(..., min_length=5, max_length=160)
    description: str = Field(..., min_length=20, max_length=5000)

    @field_validator("tenant_id")
    @classmethod
    def validate_tenant_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not _TENANT_SLUG_PATTERN.fullmatch(cleaned):
            raise ValueError(
                "tenant_id must be 2-100 characters using only letters, numbers, "
                "hyphens, or underscores."
            )
        return cleaned

    @field_validator("subject", "description")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Field cannot be empty or whitespace.")
        return cleaned


class ComplaintSubmissionResponse(BaseModel):
    """One-time receipt returned after an anonymous complaint submission."""

    complaint_id: str
    tracking_token: str = Field(
        ...,
        description=(
            "Save this token securely. It is shown only once and cannot be "
            "recovered because no submitter identity is stored."
        ),
    )
    status: ComplaintStatus
    submitted_at: str
    privacy_notice: str


class ComplaintTrackRequest(BaseModel):
    """Anonymous status lookup payload (POST body avoids leaking token in URLs)."""

    model_config = ConfigDict(extra="forbid")

    tracking_token: str = Field(..., min_length=12, max_length=128)

    @field_validator("tracking_token")
    @classmethod
    def strip_token(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 12:
            raise ValueError("Invalid tracking token.")
        return cleaned


class ComplaintTrackResponse(BaseModel):
    """Sanitized status response visible to the anonymous reporter."""

    complaint_id: str
    category: ComplaintCategory
    status: ComplaintStatus
    submitted_at: str
    updated_at: str
    public_update: str | None = None
    resolved_at: str | None = None


class ComplaintStatusUpdateRequest(BaseModel):
    """HR/Admin triage payload to update complaint lifecycle status."""

    status: ComplaintStatus
    public_update: str | None = Field(
        default=None,
        max_length=1000,
        description="Non-identifying update visible to the anonymous reporter.",
    )
    internal_notes: str | None = Field(
        default=None,
        max_length=2000,
        description="Internal HR/Admin investigation notes (never shown publicly).",
    )

    @field_validator("public_update", "internal_notes")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def validate_terminal_update(self) -> ComplaintStatusUpdateRequest:
        if self.status in {"resolved", "dismissed"}:
            if not self.public_update or len(self.public_update) < 10:
                raise ValueError(
                    "A public_update of at least 10 characters is required when "
                    f"marking a complaint as '{self.status}'."
                )
        return self


class ComplaintAdminResponse(BaseModel):
    """HR/Admin view of an anonymous complaint (contains zero submitter PII)."""

    id: str
    tenant_id: str
    category: ComplaintCategory
    subject: str
    description: str
    status: ComplaintStatus
    public_update: str | None = None
    internal_notes: str | None = None
    submitted_at: str
    updated_at: str
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    resolved_at: str | None = None


class ComplaintListResponse(BaseModel):
    """Paginated list of tenant-scoped anonymous complaints for HR/Admin."""

    total: int
    limit: int
    offset: int
    items: list[ComplaintAdminResponse]


# ---------------------------------------------------------------------------
# Temporary Thread-Safe In-Memory Store
# (Will be replaced by DB/service layer once models & db/session.py exist.)
# ---------------------------------------------------------------------------

_STORE_LOCK = Lock()
_COMPLAINT_STORE: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Security & Privacy Helper Functions
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _hash_tracking_token(token: str) -> str:
    """Compute a deterministic SHA-256 hex digest of a tracking token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def can_transition(
    current_status: ComplaintStatus, target_status: ComplaintStatus
) -> bool:
    """Return True only if the requested complaint lifecycle transition is valid."""
    return target_status in ALLOWED_TRANSITIONS.get(current_status, frozenset())


def _require_complaint_reviewer(current_user: SessionUser) -> None:
    """Ensure only HR or Admin roles can inspect or triage complaints."""
    if current_user.role not in COMPLAINT_REVIEWER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only HR or Admin roles are authorized to review complaints.",
        )


def _to_admin_response(record: dict[str, Any]) -> ComplaintAdminResponse:
    """Serialize a stored complaint while excluding the tracking token hash."""
    return ComplaintAdminResponse(
        id=record["id"],
        tenant_id=record["tenant_id"],
        category=record["category"],
        subject=record["subject"],
        description=record["description"],
        status=record["status"],
        public_update=record["public_update"],
        internal_notes=record["internal_notes"],
        submitted_at=record["submitted_at"],
        updated_at=record["updated_at"],
        reviewed_by=record["reviewed_by"],
        reviewed_at=record["reviewed_at"],
        resolved_at=record["resolved_at"],
    )


# ---------------------------------------------------------------------------
# Anonymous Whistleblower Routes (No Auth, Zero Submitter Metadata)
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=ComplaintSubmissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit an anonymous complaint",
)
async def submit_anonymous_complaint(
    payload: ComplaintCreateRequest,
    response: Response,
) -> ComplaintSubmissionResponse:
    """Store an anonymous complaint with zero submitter-identifying metadata.

    Security & Privacy Guarantees:
    - Does not require or inspect any user session or auth cookies.
    - Does not inspect or persist IP address, User-Agent, or request headers.
    - Returns a one-time tracking token and stores only its SHA-256 hash.
    """
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"

    now_iso = _utc_now_iso()
    complaint_id = f"cmp_{uuid4().hex[:12]}"
    tracking_token = f"trk_{secrets.token_urlsafe(18)}"
    tracking_token_hash = _hash_tracking_token(tracking_token)

    # Strictly zero submitter-identifying fields are stored.
    record: dict[str, Any] = {
        "id": complaint_id,
        "tenant_id": payload.tenant_id,
        "category": payload.category,
        "subject": payload.subject,
        "description": payload.description,
        "status": "submitted",
        "tracking_token_hash": tracking_token_hash,
        "public_update": None,
        "internal_notes": None,
        "submitted_at": now_iso,
        "updated_at": now_iso,
        "reviewed_by": None,
        "reviewed_at": None,
        "resolved_at": None,
    }

    with _STORE_LOCK:
        _COMPLAINT_STORE[complaint_id] = record

    return ComplaintSubmissionResponse(
        complaint_id=complaint_id,
        tracking_token=tracking_token,
        status="submitted",
        submitted_at=now_iso,
        privacy_notice=(
            "Your submission was stored anonymously with zero user-tracking data. "
            "Save your tracking token now; it cannot be recovered later."
        ),
    )


@router.post(
    "/track",
    response_model=ComplaintTrackResponse,
    status_code=status.HTTP_200_OK,
    summary="Anonymously check complaint status using a tracking token",
)
async def track_anonymous_complaint(
    payload: ComplaintTrackRequest,
    response: Response,
) -> ComplaintTrackResponse:
    """Look up complaint status anonymously via constant-time token hash matching."""
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"

    candidate_hash = _hash_tracking_token(payload.tracking_token)
    matched_record: dict[str, Any] | None = None

    with _STORE_LOCK:
        for record in _COMPLAINT_STORE.values():
            if hmac.compare_digest(record["tracking_token_hash"], candidate_hash):
                matched_record = record
                break

    if matched_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No complaint found for the provided tracking token.",
        )

    return ComplaintTrackResponse(
        complaint_id=matched_record["id"],
        category=matched_record["category"],
        status=matched_record["status"],
        submitted_at=matched_record["submitted_at"],
        updated_at=matched_record["updated_at"],
        public_update=matched_record["public_update"],
        resolved_at=matched_record["resolved_at"],
    )


# ---------------------------------------------------------------------------
# HR / Admin Triage Routes (Authenticated & Tenant-Scoped)
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=ComplaintListResponse,
    status_code=status.HTTP_200_OK,
    summary="List anonymous complaints for HR/Admin review",
)
async def list_complaints(
    complaint_status: ComplaintStatus | None = Query(default=None, alias="status"),
    category: ComplaintCategory | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: SessionUser = Depends(get_current_user),
) -> ComplaintListResponse:
    """List tenant-scoped anonymous complaints (HR/Admin only)."""
    _require_complaint_reviewer(current_user)

    with _STORE_LOCK:
        records = list(_COMPLAINT_STORE.values())

    visible_records = [
        rec
        for rec in records
        if rec["tenant_id"] == current_user.tenant_id
        and (complaint_status is None or rec["status"] == complaint_status)
        and (category is None or rec["category"] == category)
    ]

    visible_records.sort(key=lambda item: item["submitted_at"], reverse=True)
    paginated = visible_records[offset : offset + limit]

    return ComplaintListResponse(
        total=len(visible_records),
        limit=limit,
        offset=offset,
        items=[_to_admin_response(rec) for rec in paginated],
    )


@router.get(
    "/{complaint_id}",
    response_model=ComplaintAdminResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a single anonymous complaint for HR/Admin review",
)
async def get_complaint(
    complaint_id: str,
    current_user: SessionUser = Depends(get_current_user),
) -> ComplaintAdminResponse:
    """Retrieve a single tenant-scoped complaint (HR/Admin only)."""
    _require_complaint_reviewer(current_user)

    with _STORE_LOCK:
        record = _COMPLAINT_STORE.get(complaint_id)

    if record is None or record["tenant_id"] != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Complaint not found.",
        )

    return _to_admin_response(record)


@router.patch(
    "/{complaint_id}/status",
    response_model=ComplaintAdminResponse,
    status_code=status.HTTP_200_OK,
    summary="Update anonymous complaint review status (HR/Admin only)",
)
async def update_complaint_status(
    complaint_id: str,
    payload: ComplaintStatusUpdateRequest,
    current_user: SessionUser = Depends(get_current_user),
) -> ComplaintAdminResponse:
    """Transition a complaint's review status using the strict state machine."""
    _require_complaint_reviewer(current_user)

    with _STORE_LOCK:
        record = _COMPLAINT_STORE.get(complaint_id)
        if record is None or record["tenant_id"] != current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Complaint not found.",
            )

        if not can_transition(record["status"], payload.status):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Invalid state transition: cannot change complaint "
                    f"from '{record['status']}' to '{payload.status}'."
                ),
            )

        now_iso = _utc_now_iso()
        is_terminal = payload.status in {"resolved", "dismissed"}

        updated: dict[str, Any] = {
            **record,
            "status": payload.status,
            "public_update": (
                payload.public_update
                if payload.public_update is not None
                else record["public_update"]
            ),
            "internal_notes": (
                payload.internal_notes
                if payload.internal_notes is not None
                else record["internal_notes"]
            ),
            "updated_at": now_iso,
            "reviewed_by": current_user.user_id,
            "reviewed_at": now_iso,
            "resolved_at": now_iso if is_terminal else record["resolved_at"],
        }
        _COMPLAINT_STORE[complaint_id] = updated

    return _to_admin_response(updated)


__all__ = [
    "router",
    "ComplaintCreateRequest",
    "ComplaintSubmissionResponse",
    "ComplaintTrackRequest",
    "ComplaintTrackResponse",
    "ComplaintStatusUpdateRequest",
    "ComplaintAdminResponse",
    "ComplaintListResponse",
    "can_transition",
]