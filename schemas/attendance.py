from datetime import date
from typing import Optional
from pydantic import BaseModel, UUID4
from models.attendance import AttendanceStatus

# Rozana check-in request
class AttendanceCheckIn(BaseModel):
    status: AttendanceStatus = AttendanceStatus.PRESENT

# Manual attendance entry (by HR ya Manager)
class AttendanceEntryCreate(BaseModel):
    employee_id: UUID4
    date: date
    status: AttendanceStatus
    source: str = "manager"

# Response schema jo user ko haziri dikhayega
class AttendanceResponse(BaseModel):
    id: UUID4
    employee_id: UUID4
    date: date
    status: AttendanceStatus
    source: str
    is_locked: bool

    class Config:
        from_attributes = True

# Month lock karne ka schema
class MonthLockRequest(BaseModel):
    year_month: str  # Format: "YYYY-MM" (e.g., "2026-11")