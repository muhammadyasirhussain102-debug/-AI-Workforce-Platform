import uuid
from datetime import date
from sqlalchemy import Column, String, Integer, Text, Date, ForeignKey, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from db.base import Base
from models.enums import PolicyStatus, PolicyVisibility

class PolicyDocument(Base):
    __tablename__ = "policy_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Shared labour law ka tenant_id NULL hoga (sab tenants padh sakte hain)
    tenant_id = Column(UUID(as_uuid=True), nullable=True, index=True) 
    title = Column(String(255), nullable=False)
    type = Column(String(50), nullable=False)  # company_policy, labour_law, helpdesk_kb
    visibility = Column(SQLEnum(PolicyVisibility), default=PolicyVisibility.ALL, nullable=False)
    version = Column(Integer, default=1, nullable=False)
    status = Column(SQLEnum(PolicyStatus), default=PolicyStatus.DRAFT, nullable=False)
    language = Column(String(10), default="en", nullable=False)
    effective_date = Column(Date, default=date.today, nullable=False)
    source = Column(String(255), nullable=True)
    file_ref = Column(String(500), nullable=True)


class PolicyChunk(Base):
    __tablename__ = "policy_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("policy_documents.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)
    section_path = Column(String(255), nullable=False)  # e.g., "Leave Policy > 4.2 Casual Leave"
    page_from = Column(Integer, nullable=False)
    page_to = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    language = Column(String(10), default="en", nullable=False)
    visibility = Column(SQLEnum(PolicyVisibility), default=PolicyVisibility.ALL, nullable=False)