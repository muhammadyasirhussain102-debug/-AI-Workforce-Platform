from fastapi import APIRouter
from datetime import date
import uuid

router = APIRouter(prefix="/attendance", tags=["Attendance"])

@router.get("")
async def get_my_attendance():
    """Employee ka attendance record"""
    return [
        {"date": str(date.today()), "status": "PRESENT", "source": "check-in", "is_locked": False}
    ]

@router.post("/check-in")
async def daily_check_in():
    """Rozana ka biometric ya self check-in"""
    return {
        "status": "SUCCESS",
        "date": str(date.today()),
        "record_status": "PRESENT",
        "source": "check-in"
    }

@router.post("/months/{year_month}/lock")
async def lock_month(year_month: str):
    """HR month lock karta hai taake Payroll data freeze ho jaye"""
    return {
        "year_month": year_month,
        "status": "LOCKED",
        "message": f"{year_month} lock ho chuka hai. Iske baad ka edit HR approval mangega."
    }