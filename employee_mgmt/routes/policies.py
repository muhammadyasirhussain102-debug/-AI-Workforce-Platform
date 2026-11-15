from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
import uuid
import datetime

router = APIRouter(prefix="/api/v1/policies", tags=["Policy Brain (RAG)"])

# In-memory fast store
DOCUMENTS = []
CHUNKS = []

class PolicyIngestRequest(BaseModel):
    title: str
    text: str
    visibility: Optional[str] = "all"

class PolicyAskRequest(BaseModel):
    question: str
    user_role: Optional[str] = "employee"

@router.post("/ingest")
def ingest_policy(req: PolicyIngestRequest):
    doc_id = f"DOC-{uuid.uuid4().hex[:6].upper()}"
    sections = [s.strip() for s in req.text.split("\n\n") if s.strip()]
    
    for i, s in enumerate(sections, 1):
        CHUNKS.append({
            "chunk_id": f"CHK-{doc_id}-{i}",
            "doc_title": req.title,
            "section_path": f"{req.title} > Section {i}",
            "text": s,
            "visibility": req.visibility
        })

    return {
        "message": "Policy ingested and chunked successfully",
        "data": {
            "document_id": doc_id,
            "chunks_created": len(sections),
            "status": "ACTIVE"
        }
    }

@router.post("/ask")
def ask_policy(req: PolicyAskRequest):
    q = req.question.lower()
    matches = [c for c in CHUNKS if any(w in c["text"].lower() for w in q.split())]
    
    if not matches:
        return {
            "grounded": False,
            "answer": "No relevant policy clause found in knowledge base.",
            "citations": []
        }
    
    top = matches[0]
    return {
        "grounded": True,
        "answer": f"According to {top['doc_title']}: {top['text']}",
        "citations": [{"section_path": top["section_path"], "chunk_id": top["chunk_id"]}]
    }