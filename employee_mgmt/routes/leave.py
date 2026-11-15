from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
import datetime
import uuid
import urllib.request
import json

router = APIRouter(prefix="/api/v1/leave", tags=["LeaveFlow"])

# Configuration: Replace with deployed Google Apps Script URL
GOOGLE_SHEET_WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbz_YOUR_WEBHOOK_ID_HERE/exec"

# 40-Employee In-Memory Balance Store (Mirrored from Sheet)
EMPLOYEES_DB = {
    f"EMP-{1000 + i}": {
        "id": f"EMP-{1000 + i}",
        "name": f"Employee {i}",
        "email": f"emp{i}@companyk.com",
        "annual_balance": 14 if i % 4 != 0 else 0, # Some employees have 0 balance
        "medical_balance": 8,
    }
    for i in range(1, 41)
}

# Add default user
EMPLOYEES_DB["EMP-1001"] = {
    "id": "EMP-1001",
    "name": "Muhammad Yasir",
    "email": "yasir@companyk.com",
    "annual_balance": 12,
    "medical_balance": 8
}

PENDING_HR_REQUESTS = {}

class LeaveApplication(BaseModel):
    employee_id: str
    leave_type: str  # "annual", "medical", "casual"
    days: int
    reason: str

class HRDecision(BaseModel):
    request_id: str
    approved: bool
    manager_pin: str
    decision_notes: Optional[str] = "Decision rendered"

def sync_to_google_sheet(payload: dict):
    if "YOUR_WEBHOOK" in GOOGLE_SHEET_WEBHOOK_URL:
        return  # Skip if URL not configured yet
    try:
        req = urllib.request.Request(
            GOOGLE_SHEET_WEBHOOK_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f"Google Sheet Webhook Sync Warning: {e}")

@router.get("/balances/{employee_id}")
def get_balance(employee_id: str):
    emp = EMPLOYEES_DB.get(employee_id)
    if not emp:
        return {"error": "Employee not found"}
    return emp

@router.post("/requests")
def process_leave_request(req: LeaveApplication):
    emp = EMPLOYEES_DB.get(req.employee_id)
    if not emp:
        return {"status": "REJECTED", "message": "Employee ID invalid."}

    req_id = f"REQ-{uuid.uuid4().hex[:6].upper()}"
    balance_key = "medical_balance" if req.leave_type.lower() == "medical" else "annual_balance"
    current_balance = emp[balance_key]
    
    is_medical_or_emergency = any(k in req.reason.lower() for k in ["medical", "sick", "doctor", "accident", "emergency", "hospital"])
    
    # Rule 1: Normal leave with sufficient balance auto-approves
    if current_balance >= req.days and not is_medical_or_emergency and req.days == 1:
        emp[balance_key] -= req.days
        sync_to_google_sheet({
            "action": "CREATE_REQUEST",
            "request_id": req_id,
            "employee_id": emp["id"],
            "employee_name": emp["name"],
            "leave_type": req.leave_type,
            "days": req.days,
            "reason": req.reason,
            "status": "APPROVED",
            "approved_by": "System Auto-Rule"
        })
        return {
            "status": "APPROVED",
            "request_id": req_id,
            "message": f"Leave approved automatically! Remaining {req.leave_type} balance: {emp[balance_key]} days.",
            "requires_hr": False
        }

    # Rule 2: Balance exceeded OR Medical/Emergency OR 2+ Days -> Gate to HR
    routing_reason = "Medical/Emergency exception" if is_medical_or_emergency else f"Insufficient balance (Requested: {req.days}, Balance: {current_balance})"
    if req.days > 1 and current_balance >= req.days:
        routing_reason = f"Multi-day duration ({req.days} days) requires HR acknowledgment"

    PENDING_HR_REQUESTS[req_id] = {
        "request_id": req_id,
        "employee_id": emp["id"],
        "employee_name": emp["name"],
        "leave_type": req.leave_type,
        "days": req.days,
        "reason": req.reason,
        "balance_key": balance_key,
        "status": "PENDING_HR"
    }

    sync_to_google_sheet({
        "action": "CREATE_REQUEST",
        "request_id": req_id,
        "employee_id": emp["id"],
        "employee_name": emp["name"],
        "leave_type": req.leave_type,
        "days": req.days,
        "reason": req.reason,
        "status": "PENDING_HR",
        "approved_by": "Awaiting HR Manager"
    })

    return {
        "status": "PENDING_HR",
        "request_id": req_id,
        "message": f"Your request has been routed to HR for review. Reason: {routing_reason}.",
        "requires_hr": True
    }

@router.post("/decide")
def hr_decision(dec: HRDecision):
    if dec.manager_pin != "Yasir098@@":
        return {"status": "ERROR", "message": "Unauthorized manager credentials."}

    req = PENDING_HR_REQUESTS.get(dec.request_id)
    if not req:
        return {"status": "ERROR", "message": "Request not found or already closed."}

    emp = EMPLOYEES_DB.get(req["employee_id"])
    new_status = "APPROVED" if dec.approved else "REJECTED"
    
    if dec.approved:
        emp[req["balance_key"]] = max(0, emp[req["balance_key"]] - req["days"])

    req["status"] = new_status

    sync_to_google_sheet({
        "action": "HR_DECISION",
        "request_id": req["request_id"],
        "employee_id": req["employee_id"],
        "employee_name": req["employee_name"],
        "leave_type": req["leave_type"],
        "days": req["days"],
        "reason": req["reason"],
        "status": new_status,
        "approved_by": "HR Manager (Authenticated)"
    })

    return {
        "status": new_status,
        "request_id": req["request_id"],
        "message": f"Request has been {new_status} by HR. Employee record updated in Google Sheet."
    }