from fastapi import APIRouter
from datetime import date
import uuid

router = APIRouter(prefix="/leave", tags=["LeaveFlow"])

@router.get("/balances/me")
async def get_my_balances():
    """Logged-in user ka leave balance dikhata hai (Roadmap Rule 3)"""
    return [
        {
            "leave_type": "Annual Leave",
            "entitled": 20.0,
            "used": 5.0,
            "reserved": 2.0,
            "available": 13.0
        },
        {
            "leave_type": "Sick Leave",
            "entitled": 10.0,
            "used": 1.0,
            "reserved": 0.0,
            "available": 9.0
        }
    ]

@router.post("/requests")
async def submit_leave_request(
    start_date: date,
    end_date: date,
    half_day: bool = False,
    reason: str = "Family event"
):
    """Leave request submit karne ka route"""
    return {
        "request_id": str(uuid.uuid4()),
        "status": "SUBMITTED",
        "working_days": 3.0,
        "check_result": {
            "outcome": "OK",
            "detail": "Leave balance available, notice period satisfied."
        }
    }