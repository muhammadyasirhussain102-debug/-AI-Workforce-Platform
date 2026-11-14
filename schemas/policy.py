from datetime import date
from typing import Optional, List
from pydantic import BaseModel, UUID4
from models.policy import PolicyStatus, PolicyVisibility

# Citation schema jo Policy Brain ke answer ke sath hawala dikhayega
class Citation(BaseModel):
    chunk_id: UUID4
    document_title: str
    version: int
    section_path: str
    page: int
    snippet: str

# User ka question request
class AskQuestionRequest(BaseModel):
    question: str

# Policy Brain ka structured answer
class AskQuestionResponse(BaseModel):
    language: str
    answer_text: str
    citations: List[Citation] = []
    used_tools: List[str] = []
    grounded: bool = True
    route_to_hr: bool = False
    ticket_id: Optional[UUID4] = None

# Policy Document upload metadata
class PolicyDocumentCreate(BaseModel):
    title: str
    type: str  # company_policy, labour_law, helpdesk_kb
    visibility: PolicyVisibility = PolicyVisibility.ALL
    language: str = "en"
    effective_date: date = date.today()
    source: Optional[str] = None