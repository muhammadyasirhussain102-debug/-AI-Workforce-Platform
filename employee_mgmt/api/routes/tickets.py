"""IT Support Tickets API routes for the Employee Management module.

Provides tenant-isolated ticket creation, role-filtered listing,
state-machine-enforced status updates, and immutable lock protection.
"""

from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator, model_validator

from .policies import SessionUser, get_current_user

router = APIRouter(prefix="/tickets", tags=["tickets"])

TicketCategory = Literal["hardware", "software", "access", "network", "other"]
TicketPriority = Literal["low", "medium", "high", "urgent"]
TicketStatus = Literal["open", "in_progress", "resolved", "closed"]

SUPPORT_ROLES: frozenset[str] = frozenset({"manager", "hr", "admin"})
TICKET_ADMIN_ROLES: frozenset[str] = frozenset({"hr", "admin"})

# Explicit ticket lifecycle state machine.
ALLOWED_TRANSITIONS: dict[TicketStatus, frozenset[TicketStatus]] = {
    "open": frozenset({"in_progress", "resolved", "closed"}),
    "in_progress": frozenset({"open", "resolved", "closed"}),
    "resolved": frozenset({"in_progress", "closed"}),
    "closed": frozenset(),
}


# ---------------------------------------------------------------------------
# Request / Response Schemas
# (Will be moved to dedicated schema modules once created.)
# ---------------------------------------------------------------------------


class TicketCreateRequest(BaseModel):
    """Payload to open a new IT support ticket."""

    subject: str = Field(..., min_length=5, max_length=150)
    description: str = Field(..., min_length=10, max_length=2000)
    category: TicketCategory = Field(default="other")
    priority: TicketPriority = Field(default="medium")

    @field_validator("subject", "description")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Field cannot be empty or whitespace.")
        return cleaned


class TicketStatusUpdateRequest(BaseModel):
    """Payload to transition a ticket's lifecycle status or assignment."""

    status: TicketStatus
    assigned_to: str | None = Field(default=None, min_length=1, max_length=100)
    resolution_note: str | None = Field(default=None, max_length=1000)

    @field_validator("assigned_to", "resolution_note")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def validate_resolution_note(self) -> TicketStatusUpdateRequest:
        if self.status == "resolved":
            if not self.resolution_note or len(self.resolution_note) < 5:
                raise ValueError(
                    "A resolution_note of at least 5 characters is required "
                    "when marking a ticket as 'resolved'."
                )
        return self


class TicketLockRequest(BaseModel):
    """Optional audit note when explicitly locking a ticket."""

    lock_reason: str = Field(..., min_length=5, max_length=300)

    @field_validator("lock_reason")
    @classmethod
    def strip_lock_reason(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 5:
            raise ValueError("lock_reason must be at least 5 characters long.")
        return cleaned


class TicketResponse(BaseModel):
    """Full representation of an IT support ticket."""

    id: str
    tenant_id: str
    requester_id: str
    subject: str
    description: str
    category: TicketCategory
    priority: TicketPriority
    status: TicketStatus
    assigned_to: str | None = None
    resolution_note: str | None = None
    is_locked: bool
    locked_at: str | None = None
    locked_by: str | None = None
    lock_reason: str | None = None
    created_at: str
    updated_at: str
    closed_at: str | None = None


class TicketListResponse(BaseModel):
    """Paginated list of IT support tickets."""

    total: int
    limit: int
    offset: int
    items: list[TicketResponse]


# ---------------------------------------------------------------------------
# Temporary Thread-Safe In-Memory Store
# (Will be replaced by DB/service layer once models & db/session.py exist.)
# ---------------------------------------------------------------------------

_STORE_LOCK = Lock()
_TICKET_STORE: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Security & Helper Functions
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def can_transition(current_status: TicketStatus, target_status: TicketStatus) -> bool:
    """Return True only if the requested ticket lifecycle transition is valid."""
    return target_status in ALLOWED_TRANSITIONS.get(current_status, frozenset())


def _can_view_ticket(current_user: SessionUser, record: dict[str, Any]) -> bool:
    """Enforce tenant isolation and requester/support visibility."""
    if record["tenant_id"] != current_user.tenant_id:
        return False
    if record["requester_id"] == current_user.user_id:
        return True
    return current_user.role in SUPPORT_ROLES


# ---------------------------------------------------------------------------
# Route Handlers
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=TicketResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new IT support ticket",
)
async def create_ticket(
    payload: TicketCreateRequest,
    current_user: SessionUser = Depends(get_current_user),
) -> TicketResponse:
    """Create a tenant-scoped IT support ticket owned by the authenticated user."""
    now_iso = _utc_now_iso()
    ticket_id = f"tkt_{uuid4().hex[:12]}"

    record: dict[str, Any] = {
        "id": ticket_id,
        "tenant_id": current_user.tenant_id,
        "requester_id": current_user.user_id,
        "subject": payload.subject,
        "description": payload.description,
        "category": payload.category,
        "priority": payload.priority,
        "status": "open",
        "assigned_to": None,
        "resolution_note": None,
        "is_locked": False,
        "locked_at": None,
        "locked_by": None,
        "lock_reason": None,
        "created_at": now_iso,
        "updated_at": now_iso,
        "closed_at": None,
    }

    with _STORE_LOCK:
        _TICKET_STORE[ticket_id] = record

    return TicketResponse(**record)


@router.get(
    "",
    response_model=TicketListResponse,
    status_code=status.HTTP_200_OK,
    summary="List IT support tickets",
)
async def list_tickets(
    ticket_status: TicketStatus | None = Query(default=None, alias="status"),
    priority: TicketPriority | None = Query(default=None),
    category: TicketCategory | None = Query(default=None),
    is_locked: bool | None = Query(default=None),
    requester_id: str | None = Query(default=None, min_length=1, max_length=100),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: SessionUser = Depends(get_current_user),
) -> TicketListResponse:
    """List tenant-scoped IT support tickets visible to the current user."""
    normalized_requester = requester_id.strip() if requester_id else None
    if (
        normalized_requester is not None
        and normalized_requester != current_user.user_id
        and current_user.role not in SUPPORT_ROLES
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are only authorized to list your own support tickets.",
        )

    with _STORE_LOCK:
        records = list(_TICKET_STORE.values())

    visible_records = [
        rec
        for rec in records
        if _can_view_ticket(current_user, rec)
        and (ticket_status is None or rec["status"] == ticket_status)
        and (priority is None or rec["priority"] == priority)
        and (category is None or rec["category"] == category)
        and (is_locked is None or rec["is_locked"] == is_locked)
        and (
            normalized_requester is None
            or rec["requester_id"] == normalized_requester
        )
    ]

    visible_records.sort(key=lambda item: item["created_at"], reverse=True)
    paginated = visible_records[offset : offset + limit]

    return TicketListResponse(
        total=len(visible_records),
        limit=limit,
        offset=offset,
        items=[TicketResponse(**rec) for rec in paginated],
    )


@router.get(
    "/{ticket_id}",
    response_model=TicketResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a single IT support ticket",
)
async def get_ticket(
    ticket_id: str,
    current_user: SessionUser = Depends(get_current_user),
) -> TicketResponse:
    """Retrieve a single ticket if it belongs to the user's tenant and scope."""
    with _STORE_LOCK:
        record = _TICKET_STORE.get(ticket_id)

    if record is None or not _can_view_ticket(current_user, record):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found.",
        )

    return TicketResponse(**record)


@router.patch(
    "/{ticket_id}/status",
    response_model=TicketResponse,
    status_code=status.HTTP_200_OK,
    summary="Update ticket lifecycle status",
)
async def update_ticket_status(
    ticket_id: str,
    payload: TicketStatusUpdateRequest,
    current_user: SessionUser = Depends(get_current_user),
) -> TicketResponse:
    """Transition a ticket's status with RBAC, state-machine, and lock enforcement.

    Support roles (Manager/HR/Admin) may perform any valid transition.
    A ticket requester may only close their own unlocked ticket.
    Closing a ticket automatically locks it to prevent post-close tampering.
    """
    with _STORE_LOCK:
        record = _TICKET_STORE.get(ticket_id)
        if record is None or record["tenant_id"] != current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Ticket not found.",
            )

        is_owner = record["requester_id"] == current_user.user_id
        is_support = current_user.role in SUPPORT_ROLES

        if not is_support:
            if not is_owner:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Ticket not found.",
                )
            if payload.status != "closed" or payload.assigned_to is not None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        "Only Manager, HR, or Admin roles can change ticket "
                        "assignments or non-close statuses."
                    ),
                )

        if record["is_locked"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ticket is locked and can no longer be modified.",
            )

        if not can_transition(record["status"], payload.status):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Invalid state transition: cannot change ticket "
                    f"from '{record['status']}' to '{payload.status}'."
                ),
            )

        now_iso = _utc_now_iso()
        should_lock = payload.status == "closed"

        updated: dict[str, Any] = {
            **record,
            "status": payload.status,
            "assigned_to": (
                payload.assigned_to
                if payload.assigned_to is not None
                else record["assigned_to"]
            ),
            "resolution_note": (
                payload.resolution_note
                if payload.resolution_note is not None
                else record["resolution_note"]
            ),
            "updated_at": now_iso,
            "closed_at": now_iso if should_lock else record["closed_at"],
            "is_locked": True if should_lock else record["is_locked"],
            "locked_at": now_iso if should_lock else record["locked_at"],
            "locked_by": current_user.user_id if should_lock else record["locked_by"],
            "lock_reason": (
                "Automatically locked upon ticket closure."
                if should_lock
                else record["lock_reason"]
            ),
        }
        _TICKET_STORE[ticket_id] = updated

    return TicketResponse(**updated)


@router.post(
    "/{ticket_id}/lock",
    response_model=TicketResponse,
    status_code=status.HTTP_200_OK,
    summary="Lock an IT support ticket to prevent further edits",
)
async def lock_ticket(
    ticket_id: str,
    payload: TicketLockRequest,
    current_user: SessionUser = Depends(get_current_user),
) -> TicketResponse:
    """Explicitly lock a ticket for audit or compliance freeze (HR/Admin only)."""
    if current_user.role not in TICKET_ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only HR or Admin roles are authorized to lock support tickets.",
        )

    with _STORE_LOCK:
        record = _TICKET_STORE.get(ticket_id)
        if record is None or record["tenant_id"] != current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Ticket not found.",
            )

        if record["is_locked"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ticket is already locked.",
            )

        now_iso = _utc_now_iso()
        updated = {
            **record,
            "is_locked": True,
            "locked_at": now_iso,
            "locked_by": current_user.user_id,
            "lock_reason": payload.lock_reason,
            "updated_at": now_iso,
        }
        _TICKET_STORE[ticket_id] = updated

    return TicketResponse(**updated)


__all__ = [
    "router",
    "TicketCreateRequest",
    "TicketStatusUpdateRequest",
    "TicketLockRequest",
    "TicketResponse",
    "TicketListResponse",
    "can_transition",
]
+