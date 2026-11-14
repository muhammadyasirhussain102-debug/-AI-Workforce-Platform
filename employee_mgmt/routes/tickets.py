from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import uuid

router = APIRouter(prefix="/tickets", tags=["Helpdesk & Tickets"])


class TicketCreateRequest(BaseModel):
    category: str = "IT Support"  # IT Support, HR Query, Facilities, Finance
    subject: str
    description: str
    priority: str = "MEDIUM"      # LOW, MEDIUM, HIGH, URGENT


@router.post("")
async def create_ticket(
    subject: str = Query(..., description="Ticket ka unwan"),
    category: str = Query("IT Support", description="Ticket category"),
    priority: str = Query("MEDIUM", description="Priority level"),
    description: str = Query(..., description="Detailed description")
):
    """
    Naya internal helpdesk ticket create karta hai.
    """
    if not subject.strip() or not description.strip():
        raise HTTPException(status_code=400, detail="Subject aur description empty nahi ho sakte.")

    ticket_id = f"TCK-{uuid.uuid4().hex[:6].upper()}"

    return {
        "ticket_id": ticket_id,
        "subject": subject,
        "category": category,
        "priority": priority,
        "status": "OPEN",
        "created_at": datetime.utcnow().isoformat(),
        "assigned_to": "Tier-1 Support Team",
        "message": "Ticket kamyabi se darj ho chuka hai."
    }


@router.get("/me")
async def get_my_tickets():
    """
    Logged-in user ke active helpdesk tickets ki list return karta hai.
    """
    return [
        {
            "ticket_id": "TCK-B910A2",
            "subject": "VPN Access Configuration",
            "category": "IT Support",
            "priority": "HIGH",
            "status": "IN_PROGRESS",
            "created_at": "2026-03-28T09:15:00"
        },
        {
            "ticket_id": "TCK-A44F12",
            "subject": "Tax Certificate Request",
            "category": "Finance",
            "priority": "LOW",
            "status": "RESOLVED",
            "created_at": "2026-03-25T14:30:00"
        }
    ]