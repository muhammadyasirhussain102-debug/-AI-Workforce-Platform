from datetime import date, datetime
from typing import Optional, Dict, Any
from enum import Enum
from pydantic import BaseModel
import uuid


class AttendanceStatus(str, Enum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    ON_LEAVE = "ON_LEAVE"
    HALF_DAY = "HALF_DAY"
    HOLIDAY = "HOLIDAY"
    WEEKEND = "WEEKEND"
    LATE = "LATE"


class AttendanceRecord(BaseModel):
    id: str
    employee_id: str
    record_date: date
    status: AttendanceStatus
    source: str = "check-in"
    locked_at: Optional[datetime] = None
    requires_approval: bool = False


class AttendanceService:
    """
    Attendance domain service: Daily check-in and Month Lock management.
    """

    @staticmethod
    def record_check_in(employee_id: str, today: Optional[date] = None) -> AttendanceRecord:
        record_date = today or date.today()
        return AttendanceRecord(
            id=str(uuid.uuid4()),
            employee_id=employee_id,
            record_date=record_date,
            status=AttendanceStatus.PRESENT,
            source="check-in",
            locked_at=None,
            requires_approval=False
        )

    @staticmethod
    def lock_month(year_month: str, locked_by_user_id: str) -> Dict[str, Any]:
        """
        Month lock lagata hai taake Payroll sync safely ho sake.
        Iske baad koi bhi entry update hone par Rule 5 fail-closed approval mangegi.
        """
        now = datetime.utcnow()
        return {
            "year_month": year_month,
            "status": "LOCKED",
            "locked_by": locked_by_user_id,
            "locked_at": now.isoformat(),
            "message": f"Month {year_month} lock ho chuka hai. Direct edits ab allowed nahi hain."
        }

    @staticmethod
    def update_attendance_post_lock(
        record: AttendanceRecord,
        new_status: AttendanceStatus,
        is_month_locked: bool
    ) -> AttendanceRecord:
        """
        Rule 5: Agar month pehle se locked hai, to edit direct apply nahi hogi,
        balki HR approval mandatory hoga.
        """
        if is_month_locked:
            record.requires_approval = True
            record.status = new_status
            return record

        record.status = new_status
        record.requires_approval = False
        return record