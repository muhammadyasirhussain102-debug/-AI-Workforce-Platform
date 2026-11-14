from datetime import date
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, UUID4
from models.enums import LeaveRequestStatus

# Leave Request create karne ke liye aane wala data
class LeaveRequestCreate(BaseModel):
    type_id: UUID4
    start_date: date
    end_date: date
    half_day: bool = False
    reason: Optional[str] = None

# Leave Request ka response (jo user ko wapas dikhega)
class LeaveRequestResponse(BaseModel):
    id: UUID4
    employee_id: UUID4
    type_id: UUID4
    start_date: date
    end_date: date
    half_day: bool
    working_days: float
    status: LeaveRequestStatus
    reason: Optional[str] = None

    class Config:
        from_attributes = True

# Balance check karne ke liye response schema
class LeaveBalanceResponse(BaseModel):
    type_id: UUID4
    type_name: str
    year: int
    entitled: float
    used: float
    reserved: float
    available: float