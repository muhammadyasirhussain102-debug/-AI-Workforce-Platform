"""Face ID & Attendance API routes for the Employee Management module.

Provides biometric check-in/check-out punching, tenant-scoped attendance
listing, record locking, and fail-closed post-lock edits with approval checks.
"""

from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator, model_validator

from .policies import SessionUser, get_current_user

router = APIRouter(prefix="/attendance", tags=["attendance"])

AttendanceStatus = Literal["checked_in", "checked_out"]
AllowedVerificationSource = Literal["Face ID", "Web Kiosk", "Manual Override"]

SUPERVISOR_ROLES: frozenset[str] = frozenset({"manager", "hr", "admin"})
ATTENDANCE_ADMIN_ROLES: frozenset[str] = frozenset({"hr", "admin"})


# ---------------------------------------------------------------------------
# Request / Response Schemas
# (Will be moved to schemas/attendance.py once schema files are implemented.)
# ---------------------------------------------------------------------------


class AttendancePunchRequest(BaseModel):
    """Payload matching frontend `client.ts` PunchPayload."""

    employee_id: str = Field(..., min_length=1, max_length=100)
    verification_source: str = Field(default="Face ID", min_length=2, max_length=50)
    face_detected: bool = Field(default=True)

    @field_validator("employee_id", "verification_source")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Field cannot be empty or whitespace.")
        return cleaned


class AttendancePunchResponse(BaseModel):
    """Response matching frontend `client.ts` PunchResponse."""

    id: int
    tenant_id: str
    employee_id: str
    check_in: str
    check_out: str | None = None
    verification_source: str
    is_locked: bool
    status: AttendanceStatus
    message: str


class AttendanceRecordResponse(BaseModel):
    """Full representation of an attendance record with lock and audit metadata."""

    id: int
    tenant_id: str
    employee_id: str
    check_in: str
    check_out: str | None = None
    verification_source: str
    status: AttendanceStatus
    is_locked: bool
    locked_at: str | None = None
    locked_by: str | None = None
    last_edited_at: str | None = None
    last_edited_by: str | None = None
    approval_id: str | None = None
    approved_by: str | None = None
    edit_reason: str | None = None


class AttendanceListResponse(BaseModel):
    """Paginated list of attendance records."""

    total: int
    limit: int
    offset: int
    items: list[AttendanceRecordResponse]


class PostLockEditRequest(BaseModel):
    """Approval-backed payload for the high-risk `attendance.post_lock_edit` action."""

    check_in: datetime | None = Field(
        default=None,
        description="Updated check-in timestamp (UTC ISO-8601).",
    )
    check_out: datetime | None = Field(
        default=None,
        description="Updated check-out timestamp (UTC ISO-8601).",
    )
    approval_id: str = Field(
        ...,
        min_length=4,
        max_length=100,
        description="Verified approval reference authorizing post-lock edit.",
    )
    approved_by: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="User ID of the approver (must differ from acting user).",
    )
    edit_reason: str = Field(
        ...,
        min_length=10,
        max_length=500,
        description="Audit justification for editing a locked attendance record.",
    )

    @field_validator("approval_id", "approved_by", "edit_reason")
    @classmethod
    def strip_approval_fields(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Approval and audit fields cannot be blank.")
        return cleaned

    @model_validator(mode="after")
    def validate_updates(self) -> PostLockEditRequest:
        if self.check_in is None and self.check_out is None:
            raise ValueError(
                "At least one of 'check_in' or 'check_out' must be provided."
            )
        return self


# ---------------------------------------------------------------------------
# Temporary Thread-Safe In-Memory Store
# (Will be replaced by services/attendance_service.py + db/session.py later.)
# ---------------------------------------------------------------------------

_STORE_LOCK = Lock()
_ATTENDANCE_STORE: dict[int, dict[str, Any]] = {}
_NEXT_RECORD_ID: int = 1


# ---------------------------------------------------------------------------
# Security & Helper Functions
# ---------------------------------------------------------------------------


def _utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def _to_utc_iso(value: datetime) -> str:
    """Normalize a datetime to an ISO-8601 UTC string."""
    if value.tzinfo is None:
        normalized = value.replace(tzinfo=timezone.utc)
    else:
        normalized = value.astimezone(timezone.utc)
    return normalized.isoformat()


def _parse_iso_utc(value: str) -> datetime:
    """Parse an ISO-8601 timestamp string into a UTC-aware datetime."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _can_view_record(current_user: SessionUser, record: dict[str, Any]) -> bool:
    """Enforce tenant isolation and employee/supervisor read permissions."""
    if record["tenant_id"] != current_user.tenant_id:
        return False
    if record["employee_id"] == current_user.user_id:
        return True
    return current_user.role in SUPERVISOR_ROLES


def _find_open_record_unlocked(
    tenant_id: str, employee_id: str
) -> dict[str, Any] | None:
    """Return the most recent open (checked-in) record for an employee."""
    open_records = [
        rec
        for rec in _ATTENDANCE_STORE.values()
        if rec["tenant_id"] == tenant_id
        and rec["employee_id"] == employee_id
        and rec["check_out"] is None
    ]
    if not open_records:
        return None
    open_records.sort(key=lambda item: item["id"], reverse=True)
    return open_records[0]


# ---------------------------------------------------------------------------
# Route Handlers
# ---------------------------------------------------------------------------


@router.post(
    "/punch",
    response_model=AttendancePunchResponse,
    status_code=status.HTTP_200_OK,
    summary="Record a Face ID check-in or check-out punch",
)
async def punch_attendance(
    payload: AttendancePunchRequest,
    current_user: SessionUser = Depends(get_current_user),
) -> AttendancePunchResponse:
    """Record a check-in or close an active shift with a check-out."""
    global _NEXT_RECORD_ID

    # Enforce server-session identity: employees may only punch for themselves.
    if (
        payload.employee_id != current_user.user_id
        and current_user.role not in ATTENDANCE_ADMIN_ROLES
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are only authorized to record attendance for your own account.",
        )

    if not payload.face_detected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Face ID verification failed: No valid face detected.",
        )

    now_iso = _to_utc_iso(_utc_now())

    with _STORE_LOCK:
        open_record = _find_open_record_unlocked(
            tenant_id=current_user.tenant_id,
            employee_id=payload.employee_id,
        )

        if open_record is not None:
            if open_record["is_locked"]:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Active attendance record is locked and cannot be modified "
                        "without an approved post-lock edit."
                    ),
                )

            updated = {
                **open_record,
                "check_out": now_iso,
                "status": "checked_out",
            }
            _ATTENDANCE_STORE[open_record["id"]] = updated

            return AttendancePunchResponse(
                id=updated["id"],
                tenant_id=updated["tenant_id"],
                employee_id=updated["employee_id"],
                check_in=updated["check_in"],
                check_out=updated["check_out"],
                verification_source=updated["verification_source"],
                is_locked=updated["is_locked"],
                status="checked_out",
                message="Check-out recorded successfully.",
            )

        record_id = _NEXT_RECORD_ID
        _NEXT_RECORD_ID += 1

        new_record: dict[str, Any] = {
            "id": record_id,
            "tenant_id": current_user.tenant_id,
            "employee_id": payload.employee_id,
            "check_in": now_iso,
            "check_out": None,
            "verification_source": payload.verification_source,
            "status": "checked_in",
            "is_locked": False,
            "locked_at": None,
            "locked_by": None,
            "last_edited_at": None,
            "last_edited_by": None,
            "approval_id": None,
            "approved_by": None,
            "edit_reason": None,
        }
        _ATTENDANCE_STORE[record_id] = new_record

    return AttendancePunchResponse(
        id=new_record["id"],
        tenant_id=new_record["tenant_id"],
        employee_id=new_record["employee_id"],
        check_in=new_record["check_in"],
        check_out=new_record["check_out"],
        verification_source=new_record["verification_source"],
        is_locked=new_record["is_locked"],
        status="checked_in",
        message="Check-in recorded successfully.",
    )


@router.get(
    "",
    response_model=AttendanceListResponse,
    status_code=status.HTTP_200_OK,
    summary="List attendance records",
)
async def list_attendance_records(
    employee_id: str | None = Query(default=None, min_length=1, max_length=100),
    is_locked: bool | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: SessionUser = Depends(get_current_user),
) -> AttendanceListResponse:
    """List tenant-scoped attendance records visible to the authenticated user."""
    normalized_employee_id = employee_id.strip() if employee_id else None
    if (
        normalized_employee_id is not None
        and normalized_employee_id != current_user.user_id
        and current_user.role not in SUPERVISOR_ROLES
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are only authorized to view your own attendance records.",
        )

    with _STORE_LOCK:
        records = list(_ATTENDANCE_STORE.values())

    visible_records = [
        rec
        for rec in records
        if _can_view_record(current_user, rec)
        and (
            normalized_employee_id is None
            or rec["employee_id"] == normalized_employee_id
        )
        and (is_locked is None or rec["is_locked"] == is_locked)
    ]

    visible_records.sort(key=lambda item: item["id"], reverse=True)
    paginated = visible_records[offset : offset + limit]

    return AttendanceListResponse(
        total=len(visible_records),
        limit=limit,
        offset=offset,
        items=[AttendanceRecordResponse(**rec) for rec in paginated],
    )


@router.get(
    "/{record_id}",
    response_model=AttendanceRecordResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a single attendance record",
)
async def get_attendance_record(
    record_id: int,
    current_user: SessionUser = Depends(get_current_user),
) -> AttendanceRecordResponse:
    """Retrieve a single attendance record if visible to the current user."""
    with _STORE_LOCK:
        record = _ATTENDANCE_STORE.get(record_id)

    if record is None or not _can_view_record(current_user, record):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attendance record not found.",
        )

    return AttendanceRecordResponse(**record)


@router.post(
    "/{record_id}/lock",
    response_model=AttendanceRecordResponse,
    status_code=status.HTTP_200_OK,
    summary="Lock an attendance record for payroll/audit protection",
)
async def lock_attendance_record(
    record_id: int,
    current_user: SessionUser = Depends(get_current_user),
) -> AttendanceRecordResponse:
    """Lock an attendance record so normal punches and edits are prevented."""
    if current_user.role not in ATTENDANCE_ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only HR or Admin roles are authorized to lock attendance records.",
        )

    with _STORE_LOCK:
        record = _ATTENDANCE_STORE.get(record_id)
        if record is None or record["tenant_id"] != current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Attendance record not found.",
            )

        if record["is_locked"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Attendance record is already locked.",
            )

        updated = {
            **record,
            "is_locked": True,
            "locked_at": _to_utc_iso(_utc_now()),
            "locked_by": current_user.user_id,
        }
        _ATTENDANCE_STORE[record_id] = updated

    return AttendanceRecordResponse(**updated)


@router.patch(
    "/{record_id}/post-lock-edit",
    response_model=AttendanceRecordResponse,
    status_code=status.HTTP_200_OK,
    summary="Edit a locked attendance record (high-risk action, requires approval)",
)
async def post_lock_edit_attendance(
    record_id: int,
    payload: PostLockEditRequest,
    current_user: SessionUser = Depends(get_current_user),
) -> AttendanceRecordResponse:
    """Modify a locked attendance record with strict fail-closed approval checks.

    Guardrail: `attendance.post_lock_edit` is a high-risk action and fails closed
    unless performed by HR/Admin with an explicit, non-self approval reference.
    """
    if current_user.role not in ATTENDANCE_ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "High-risk action blocked (attendance.post_lock_edit): "
                "only HR or Admin roles are authorized."
            ),
        )

    if payload.approved_by == current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "High-risk action blocked (attendance.post_lock_edit): "
                "self-approval is not permitted."
            ),
        )

    with _STORE_LOCK:
        record = _ATTENDANCE_STORE.get(record_id)
        if record is None or record["tenant_id"] != current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Attendance record not found.",
            )

        if record["employee_id"] == current_user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "High-risk action blocked (attendance.post_lock_edit): "
                    "you cannot edit your own locked attendance record."
                ),
            )

        if not record["is_locked"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Record is not locked; post-lock edit applies only to locked records.",
            )

        effective_check_in = (
            _to_utc_iso(payload.check_in)
            if payload.check_in is not None
            else record["check_in"]
        )
        effective_check_out = (
            _to_utc_iso(payload.check_out)
            if payload.check_out is not None
            else record["check_out"]
        )

        if effective_check_out is not None:
            if _parse_iso_utc(effective_check_out) < _parse_iso_utc(effective_check_in):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="check_out timestamp cannot be earlier than check_in.",
                )

        updated_status: AttendanceStatus = (
            "checked_out" if effective_check_out is not None else "checked_in"
        )
        updated = {
            **record,
            "check_in": effective_check_in,
            "check_out": effective_check_out,
            "status": updated_status,
            "last_edited_at": _to_utc_iso(_utc_now()),
            "last_edited_by": current_user.user_id,
            "approval_id": payload.approval_id,
            "approved_by": payload.approved_by,
            "edit_reason": payload.edit_reason,
        }
        _ATTENDANCE_STORE[record_id] = updated

    return AttendanceRecordResponse(**updated)


__all__ = [
    "router",
    "AttendancePunchRequest",
    "AttendancePunchResponse",
    "AttendanceRecordResponse",
    "AttendanceListResponse",
    "PostLockEditRequest",
]