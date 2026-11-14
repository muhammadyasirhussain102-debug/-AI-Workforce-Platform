from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional
import uuid

router = APIRouter(prefix="/training", tags=["Onboarding & Training"])


class TrainingModuleProgress(BaseModel):
    module_id: str
    title: str
    day_number: int
    status: str  # COMPLETED, IN_PROGRESS, PENDING
    score: Optional[float] = None


@router.get("/roadmap")
async def get_onboarding_roadmap():
    """
    Day 1-3 Structured Onboarding track return karta hai.
    """
    return {
        "track_name": "New Hire Fast-Track Onboarding",
        "total_days": 3,
        "modules": [
            {
                "module_id": "MOD-001",
                "day_number": 1,
                "title": "Company Culture, Tools & Workspace Setup",
                "status": "COMPLETED",
                "required_time_mins": 45
            },
            {
                "module_id": "MOD-002",
                "day_number": 2,
                "title": "Security, Compliance & Confidentiality (Rule 6)",
                "status": "IN_PROGRESS",
                "required_time_mins": 60
            },
            {
                "module_id": "MOD-003",
                "day_number": 3,
                "title": "Architecture Standards & Module Deep-Dive",
                "status": "PENDING",
                "required_time_mins": 90
            }
        ]
    }


@router.post("/modules/{module_id}/complete")
async def mark_module_completed(
    module_id: str,
    score: Optional[float] = Query(None, ge=0.0, le=100.0, description="Quiz score agar applicable ho")
):
    """
    Training module ko complete mark karta hai.
    """
    return {
        "module_id": module_id,
        "status": "COMPLETED",
        "quiz_score": score,
        "message": f"Module {module_id} kamyabi se mukammal ho gaya."
    }