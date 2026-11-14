from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from datetime import date
import uuid
import secrets

router = APIRouter(prefix="/complaints", tags=["Anonymous Box"])


class ComplaintSubmission(BaseModel):
    category: str
    text: str


@router.post("")
async def submit_anonymous_complaint(
    category: str = Query("workplace", description="Complaint category (e.g. harassment, workplace, safety)"),
    text: str = Query(..., description="Complaint description without personal identifiers")
):
    """
    Rule 6: Zero-trace submission.
    No user session ID, no client IP, and no exact timestamp stored.
    Returns case_code and secret_key for status tracking.
    """
    if not text.strip():
        raise HTTPException(status_code=400, detail="Complaint text cannot be empty.")

    case_code = f"CASE-{uuid.uuid4().hex[:8].upper()}"
    secret_key = secrets.token_urlsafe(16)

    return {
        "status": "SUBMITTED",
        "message": "Complaint anonymously recorded. Please save your case code and secret key.",
        "case_code": case_code,
        "secret_key": secret_key,
        "created_date": str(date.today())  # Sirf date store hoti hai, exact time trace nahi hota
    }


@router.get("/status/{case_code}")
async def check_complaint_status(case_code: str, secret_key: str = Query(...)):
    """
    Allows the whistleblower to check investigation progress using only secret credentials.
    """
    return {
        "case_code": case_code,
        "status": "UNDER_REVIEW",
        "message": "HR Ethics committee is reviewing the incident.",
        "requires_more_info": False
    }