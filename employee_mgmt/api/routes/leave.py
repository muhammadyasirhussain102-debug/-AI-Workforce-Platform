"""LeaveFlow API routes for the Employee Management module.

Provides deterministic leave balance calculations, leave request submission
with overlap checks, state-machine-enforced approval/cancellation workflows,
and fail-closed high-risk leave exception overrides.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from threading import Lock
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator, model_validator

from .policies import SessionUser, get_current_user

router = APIRouter(prefix="/leave", tags=["leave"])

LeaveType = Literal["annual", "sick", "casual", "unpaid"]
LeaveStatus = Literal["pending", "approved", "rejected", "cancelled"]
DecisionAction = Literal["approve", "reject"]

APPROVER_ROLES: frozenset[str] = frozenset({"manager", "hr", "admin"})
EXCEPTION_MANAGER_ROLES: frozenset[str] = frozenset({"hr", "admin"})

# Deterministic annual leave entitlements (in business days).
# `None` indicates unpaid leave has no fixed paid-balance cap.
DEFAULT_ANNUAL_ENTITLEMENTS: dict[LeaveType, int | None] = {
    "annual": 20,
    "sick": 10,
    "casual": 5,
    "unpaid": None,
}

# Explicit leave lifecycle state machine.
ALLOWED_TRANSITIONS: dict[LeaveStatus, frozenset[LeaveStatus]] = {
    "pending": frozenset({"approved", "rejected", "cancelled"}),
    "approved": frozenset({"cancelled"}),
    "rejected": frozenset(),
    "cancelled": frozenset(),
}


# ---------------------------------------------------------------------------
# Request / Response Schemas
# (Will be moved to schemas/leave.py once schema files are implemented.)
# ---------------------------------------------------------------------------


class LeaveRequestCreate(BaseModel):
    """Payload to submit a standard employee leave request."""

    leave_type: LeaveType
    start_date: date
    end_date: date
    reason: str = Field(..., min_length=5, max_length=500)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 5:
            raise ValueError("Reason must be at least 5 characters long.")
        return cleaned

    @model_validator(mode="after")
    def validate_date_range(self) -> LeaveRequestCreate:
        if self.end_date < self.start_date:
            raise ValueError("end_date cannot be earlier than start_date.")
        if self.start_date.year != self.end_date.year:
            raise ValueError(
                "Leave requests cannot span across calendar years. "
                "Please submit separate requests for each year."
            )
        return self


class LeaveDecisionRequest(BaseModel):
    """Payload for a manager/HR/admin to approve or reject a pending request."""

    action: DecisionAction
    comment: str | None = Field(default=None, max_length=500)

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class LeaveExceptionCreate(BaseModel):
    """Approval-backed payload for the high-risk `leave.exception` action."""

    employee_id: str = Field(..., min_length=1, max_length=100)
    leave_type: LeaveType
    start_date: date
    end_date: date
    reason: str = Field(..., min_length=5, max_length=500)
    approval_id: str = Field(
        ...,
        min_length=4,
        max_length=100,
        description="Verified approval reference authorizing this leave exception.",
    )
    approved_by: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="User ID of the approver (must differ from the acting user).",
    )
    exception_reason: str = Field(
        ...,
        min_length=10,
        max_length=500,
        description="Audit justification for overriding normal leave rules.",
    )

    @field_validator(
        "employee_id",
        "reason",
        "approval_id",
        "approved_by",
        "exception_reason",
    )
    @classmethod
    def strip_required_fields(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Field cannot be empty or whitespace.")
        return cleaned

    @model_validator(mode="after")
    def validate_date_range(self) -> LeaveExceptionCreate:
        if self.end_date < self.start_date:
            raise ValueError("end_date cannot be earlier than start_date.")
        if self.start_date.year != self.end_date.year:
            raise ValueError(
                "Leave exceptions cannot span across calendar years."
            )
        return self


class LeaveRequestResponse(BaseModel):
    """Full representation of a leave request record."""

    id: str
    tenant_id: str
    employee_id: str
    leave_type: LeaveType
    start_date: date
    end_date: date
    business_days: int
    reason: str
    status: LeaveStatus
    is_exception: bool
    created_by: str
    created_at: str
    updated_at: str
    decided_by: str | None = None
    decided_at: str | None = None
    decision_comment: str | None = None
    approval_id: str | None = None
    approved_by: str | None = None
    exception_reason: str | None = None


class LeaveRequestListResponse(BaseModel):
    """Paginated list of leave requests."""

    total: int
    limit: int
    offset: int
    items: list[LeaveRequestResponse]


class LeaveTypeBalance(BaseModel):
    """Deterministic balance breakdown for a single leave type."""

    leave_type: LeaveType
    entitled_days: int | None
    used_days: int
    pending_days: int
    remaining_days: int | None


class LeaveBalanceResponse(BaseModel):
    """Code-calculated leave balance summary for an employee in a given year."""

    tenant_id: str
    employee_id: str
    year: int
    balances: list[LeaveTypeBalance]


# ---------------------------------------------------------------------------
# Temporary Thread-Safe In-Memory Store
# (Will be replaced by services/leave_service.py + db/session.py once created.)
# ---------------------------------------------------------------------------

_STORE_LOCK = Lock()
_LEAVE_STORE: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Deterministic Business Logic & Security Helpers
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def can_transition(current_status: LeaveStatus, target_status: LeaveStatus) -> bool:
    """Return True only if transitioning between statuses is allowed."""
    return target_status in ALLOWED_TRANSITIONS.get(current_status, frozenset())


def calculate_business_days(start_date: date, end_date: date) -> int:
    """Deterministically count weekday (Mon-Fri) business days inclusive."""
    if end_date < start_date:
        return 0

    total_days = (end_date - start_date).days + 1
    business_days = 0
    for offset in range(total_days):
        current_day = start_date + timedelta(days=offset)
        if current_day.weekday() < 5:  # 0=Monday .. 4=Friday
            business_days += 1
    return business_days


def _compute_balances_unlocked(
    tenant_id: str, employee_id: str, year: int
) -> list[LeaveTypeBalance]:
    """Calculate exact balances from stored records (caller must hold _STORE_LOCK)."""
    used_by_type: dict[LeaveType, int] = {
        "annual": 0,
        "sick": 0,
        "casual": 0,
        "unpaid": 0,
    }
    pending_by_type: dict[LeaveType, int] = {
        "annual": 0,
        "sick": 0,
        "casual": 0,
        "unpaid": 0,
    }

    for record in _LEAVE_STORE.values():
        if (
            record["tenant_id"] != tenant_id
            or record["employee_id"] != employee_id
            or record["start_date"].year != year
        ):
            continue

        leave_type: LeaveType = record["leave_type"]
        if record["status"] == "approved":
            used_by_type[leave_type] += record["business_days"]
        elif record["status"] == "pending":
            pending_by_type[leave_type] += record["business_days"]

    balances: list[LeaveTypeBalance] = []
    for leave_type, entitled in DEFAULT_ANNUAL_ENTITLEMENTS.items():
        used = used_by_type[leave_type]
        pending = pending_by_type[leave_type]
        remaining = None if entitled is None else entitled - used - pending
        balances.append(
            LeaveTypeBalance(
                leave_type=leave_type,
                entitled_days=entitled,
                used_days=used,
                pending_days=pending,
                remaining_days=remaining,
            )
        )
    return balances


def _get_remaining_days_unlocked(
    tenant_id: str, employee_id: str, year: int, leave_type: LeaveType
) -> int | None:
    """Return remaining days for a specific leave type (caller holds _STORE_LOCK)."""
    balances = _compute_balances_unlocked(tenant_id, employee_id, year)
    for item in balances:
        if item.leave_type == leave_type:
            return item.remaining_days
    return None


def _has_overlapping_leave_unlocked(
    tenant_id: str,
    employee_id: str,
    start_date: date,
    end_date: date,
    exclude_request_id: str | None = None,
) -> bool:
    """Check whether any pending or approved leave overlaps the requested dates."""
    for record in _LEAVE_STORE.values():
        if record["id"] == exclude_request_id:
            continue
        if (
            record["tenant_id"] != tenant_id
            or record["employee_id"] != employee_id
            or record["status"] not in {"pending", "approved"}
        ):
            continue
        if start_date <= record["end_date"] and end_date >= record["start_date"]:
            return True
    return False


def _can_view_request(current_user: SessionUser, record: dict[str, Any]) -> bool:
    """Check tenant isolation and ownership/approver authorization."""
    if record["tenant_id"] != current_user.tenant_id:
        return False
    if record["employee_id"] == current_user.user_id:
        return True
    return current_user.role in APPROVER_ROLES


# ---------------------------------------------------------------------------
# Route Handlers
# ---------------------------------------------------------------------------


@router.get(
    "/balance",
    response_model=LeaveBalanceResponse,
    status_code=status.HTTP_200_OK,
    summary="Get deterministic leave balances",
)
async def get_leave_balance(
    year: int = Query(
        default_factory=lambda: datetime.now(timezone.utc).year,
        ge=2000,
        le=2100,
    ),
    employee_id: str | None = Query(default=None, min_length=1, max_length=100),
    current_user: SessionUser = Depends(get_current_user),
) -> LeaveBalanceResponse:
    """Return code-calculated leave balances for the current or authorized employee."""
    target_employee_id = current_user.user_id
    if employee_id is not None:
        cleaned_employee_id = employee_id.strip()
        if (
            cleaned_employee_id != current_user.user_id
            and current_user.role not in APPROVER_ROLES
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are only authorized to view your own leave balance.",
            )
        target_employee_id = cleaned_employee_id

    with _STORE_LOCK:
        balances = _compute_balances_unlocked(
            tenant_id=current_user.tenant_id,
            employee_id=target_employee_id,
            year=year,
        )

    return LeaveBalanceResponse(
        tenant_id=current_user.tenant_id,
        employee_id=target_employee_id,
        year=year,
        balances=balances,
    )


@router.post(
    "/requests",
    response_model=LeaveRequestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a new leave request",
)
async def create_leave_request(
    payload: LeaveRequestCreate,
    current_user: SessionUser = Depends(get_current_user),
) -> LeaveRequestResponse:
    """Create a pending leave request after validating business days, overlap, and balance."""
    business_days = calculate_business_days(payload.start_date, payload.end_date)
    if business_days <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Selected date range contains no business days (Mon-Fri).",
        )

    with _STORE_LOCK:
        if _has_overlapping_leave_unlocked(
            tenant_id=current_user.tenant_id,
            employee_id=current_user.user_id,
            start_date=payload.start_date,
            end_date=payload.end_date,
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Leave request overlaps with an existing pending or approved leave.",
            )

        remaining_days = _get_remaining_days_unlocked(
            tenant_id=current_user.tenant_id,
            employee_id=current_user.user_id,
            year=payload.start_date.year,
            leave_type=payload.leave_type,
        )
        if remaining_days is not None and business_days > remaining_days:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Insufficient {payload.leave_type} leave balance: "
                    f"requested {business_days} business day(s), "
                    f"remaining {max(remaining_days, 0)} day(s)."
                ),
            )

        now_iso = _utc_now_iso()
        request_id = f"lvr_{uuid4().hex[:12]}"
        record: dict[str, Any] = {
            "id": request_id,
            "tenant_id": current_user.tenant_id,
            "employee_id": current_user.user_id,
            "leave_type": payload.leave_type,
            "start_date": payload.start_date,
            "end_date": payload.end_date,
            "business_days": business_days,
            "reason": payload.reason,
            "status": "pending",
            "is_exception": False,
            "created_by": current_user.user_id,
            "created_at": now_iso,
            "updated_at": now_iso,
            "decided_by": None,
            "decided_at": None,
            "decision_comment": None,
            "approval_id": None,
            "approved_by": None,
            "exception_reason": None,
        }
        _LEAVE_STORE[request_id] = record

    return LeaveRequestResponse(**record)


@router.get(
    "/requests",
    response_model=LeaveRequestListResponse,
    status_code=status.HTTP_200_OK,
    summary="List leave requests",
)
async def list_leave_requests(
    leave_status: LeaveStatus | None = Query(default=None, alias="status"),
    leave_type: LeaveType | None = Query(default=None),
    employee_id: str | None = Query(default=None, min_length=1, max_length=100),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: SessionUser = Depends(get_current_user),
) -> LeaveRequestListResponse:
    """List tenant-scoped leave requests visible to the authenticated user."""
    normalized_employee_id = employee_id.strip() if employee_id else None
    if (
        normalized_employee_id is not None
        and normalized_employee_id != current_user.user_id
        and current_user.role not in APPROVER_ROLES
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are only authorized to list your own leave requests.",
        )

    with _STORE_LOCK:
        records = list(_LEAVE_STORE.values())

    visible_records = [
        rec
        for rec in records
        if _can_view_request(current_user, rec)
        and (leave_status is None or rec["status"] == leave_status)
        and (leave_type is None or rec["leave_type"] == leave_type)
        and (
            normalized_employee_id is None
            or rec["employee_id"] == normalized_employee_id
        )
    ]

    visible_records.sort(key=lambda item: item["created_at"], reverse=True)
    paginated = visible_records[offset : offset + limit]

    return LeaveRequestListResponse(
        total=len(visible_records),
        limit=limit,
        offset=offset,
        items=[LeaveRequestResponse(**rec) for rec in paginated],
    )


@router.get(
    "/requests/{request_id}",
    response_model=LeaveRequestResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a single leave request",
)
async def get_leave_request(
    request_id: str,
    current_user: SessionUser = Depends(get_current_user),
) -> LeaveRequestResponse:
    """Retrieve a single leave request if visible to the current user."""
    with _STORE_LOCK:
        record = _LEAVE_STORE.get(request_id)

    if record is None or not _can_view_request(current_user, record):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Leave request not found.",
        )

    return LeaveRequestResponse(**record)


@router.post(
    "/requests/{request_id}/decision",
    response_model=LeaveRequestResponse,
    status_code=status.HTTP_200_OK,
    summary="Approve or reject a pending leave request",
)
async def decide_leave_request(
    request_id: str,
    payload: LeaveDecisionRequest,
    current_user: SessionUser = Depends(get_current_user),
) -> LeaveRequestResponse:
    """Approve or reject a pending request with RBAC and no-self-approval checks."""
    if current_user.role not in APPROVER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Manager, HR, or Admin roles can approve or reject leave requests.",
        )

    target_status: LeaveStatus = (
        "approved" if payload.action == "approve" else "rejected"
    )

    with _STORE_LOCK:
        record = _LEAVE_STORE.get(request_id)
        if record is None or record["tenant_id"] != current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Leave request not found.",
            )

        if record["employee_id"] == current_user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Self-approval or self-rejection of your own leave request is not permitted.",
            )

        if not can_transition(record["status"], target_status):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Invalid state transition: cannot change leave request "
                    f"from '{record['status']}' to '{target_status}'."
                ),
            )

        now_iso = _utc_now_iso()
        updated = {
            **record,
            "status": target_status,
            "updated_at": now_iso,
            "decided_by": current_user.user_id,
            "decided_at": now_iso,
            "decision_comment": payload.comment,
        }
        _LEAVE_STORE[request_id] = updated

    return LeaveRequestResponse(**updated)


@router.post(
    "/requests/{request_id}/cancel",
    response_model=LeaveRequestResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel a pending or approved leave request",
)
async def cancel_leave_request(
    request_id: str,
    current_user: SessionUser = Depends(get_current_user),
) -> LeaveRequestResponse:
    """Cancel a leave request if owned by the current user or performed by HR/Admin."""
    with _STORE_LOCK:
        record = _LEAVE_STORE.get(request_id)
        if record is None or record["tenant_id"] != current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Leave request not found.",
            )

        is_owner = record["employee_id"] == current_user.user_id
        if not is_owner and current_user.role not in EXCEPTION_MANAGER_ROLES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the request owner, HR, or Admin can cancel this leave request.",
            )

        if not can_transition(record["status"], "cancelled"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot cancel a leave request in '{record['status']}' state.",
            )

        now_iso = _utc_now_iso()
        updated = {
            **record,
            "status": "cancelled",
            "updated_at": now_iso,
        }
        _LEAVE_STORE[request_id] = updated

    return LeaveRequestResponse(**updated)


@router.post(
    "/exceptions",
    response_model=LeaveRequestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Grant a leave exception override (high-risk action, requires approval)",
)
async def create_leave_exception(
    payload: LeaveExceptionCreate,
    current_user: SessionUser = Depends(get_current_user),
) -> LeaveRequestResponse:
    """Record an approved exceptional leave override.

    Guardrail: `leave.exception` is a high-risk action and fails closed unless
    performed by HR/Admin with an explicit, non-self approval reference.
    """
    if current_user.role not in EXCEPTION_MANAGER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "High-risk action blocked (leave.exception): "
                "only HR or Admin roles are authorized."
            ),
        )

    if payload.approved_by == current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "High-risk action blocked (leave.exception): "
                "self-approval is not permitted."
            ),
        )

    if payload.employee_id == current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "High-risk action blocked (leave.exception): "
                "you cannot grant a leave exception for yourself."
            ),
        )

    business_days = calculate_business_days(payload.start_date, payload.end_date)
    if business_days <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Selected date range contains no business days (Mon-Fri).",
        )

    with _STORE_LOCK:
        if _has_overlapping_leave_unlocked(
            tenant_id=current_user.tenant_id,
            employee_id=payload.employee_id,
            start_date=payload.start_date,
            end_date=payload.end_date,
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Leave exception overlaps with an existing pending or approved leave.",
            )

        now_iso = _utc_now_iso()
        request_id = f"lvx_{uuid4().hex[:12]}"
        record: dict[str, Any] = {
            "id": request_id,
            "tenant_id": current_user.tenant_id,
            "employee_id": payload.employee_id,
            "leave_type": payload.leave_type,
            "start_date": payload.start_date,
            "end_date": payload.end_date,
            "business_days": business_days,
            "reason": payload.reason,
            "status": "approved",
            "is_exception": True,
            "created_by": current_user.user_id,
            "created_at": now_iso,
            "updated_at": now_iso,
            "decided_by": current_user.user_id,
            "decided_at": now_iso,
            "decision_comment": payload.exception_reason,
            "approval_id": payload.approval_id,
            "approved_by": payload.approved_by,
            "exception_reason": payload.exception_reason,
        }
        _LEAVE_STORE[request_id] = record

    return LeaveRequestResponse(**record)


__all__ = [
    "router",
    "LeaveRequestCreate",
    "LeaveDecisionRequest",
    "LeaveExceptionCreate",
    "LeaveRequestResponse",
    "LeaveRequestListResponse",
    "LeaveTypeBalance",
    "LeaveBalanceResponse",
    "can_transition",
    "calculate_business_days",
]