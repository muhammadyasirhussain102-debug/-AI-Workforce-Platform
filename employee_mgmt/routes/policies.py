from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
import uuid

from services.policy_service import PolicyChunker, PolicySearchEngine

router = APIRouter(prefix="/policies", tags=["Policy Brain (RAG)"])


class PolicyUploadRequest(BaseModel):
    title: str
    content: str
    type: str = "company_policy"  # company_policy, labour_law, helpdesk_kb
    visibility: str = "all"        # all, managers, hr_only


@router.post("/ingest")
async def ingest_policy_document(payload: PolicyUploadRequest):
    """
    Document ingest karta hai aur chunks mein split karta hai.
    """
    if not payload.content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty.")

    chunks = PolicyChunker.chunk_by_section(
        document_text=payload.content,
        section_title=payload.title
    )
    doc_id = str(uuid.uuid4())

    return {
        "document_id": doc_id,
        "title": payload.title,
        "type": payload.type,
        "visibility": payload.visibility,
        "status": "ACTIVE",
        "total_chunks_created": len(chunks),
        "chunks_preview": chunks[:2]
    }


@router.post("/ask")
async def ask_policy_brain(
    question: str = Query(..., description="Employee ka sawaal"),
    user_role: str = Query("employee", description="Current session user role (Rule 3)")
):
    """
    Policy Brain Q&A with strict citations (Rule 2 & Rule 4).
    """
    # Pre-retrieval security filter apply ho raha hai (Rule 4)
    query_filter = PolicySearchEngine.build_secure_query(
        tenant_id=None,
        user_role=user_role,
        search_term=question
    )

    # Cleaned mock grounded response with verified citation
    return {
        "question": question,
        "user_role": user_role,
        "applied_filter": query_filter,
        "answer_text": "Company policy ke mutabiq aap saal mein 20 annual leaves ke haqdaar hain. Leaves lene se pehle manager approval zaroori hai.",
        "grounded": True,
        "citations": [
            {
                "document_title": "Employee Handbook 2026",
                "version": 1,
                "section_path": "4.1 Annual Leave Entitlement",
                "page": 12,
                "snippet": "All full-time employees are entitled to 20 paid annual leave days per year."
            }
        ],
        "route_to_hr": False
    }