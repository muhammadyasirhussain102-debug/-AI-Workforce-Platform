import uuid
from datetime import datetime
from enum import Enum
from sqlalchemy import Column, String, Text, DateTime, JSON, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from db.base import Base

class TicketStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    WAITING = "WAITING"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"

class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    requester_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    category = Column(String(50), nullable=False)  # IT, Admin, HR, Other
    priority = Column(String(20), default="medium", nullable=False)  # low, medium, high, urgent
    status = Column(SQLEnum(TicketStatus), default=TicketStatus.OPEN, nullable=False)
    assignee_id = Column(UUID(as_uuid=True), nullable=True)
    sla_due = Column(DateTime, nullable=True)
    summary = Column(String(255), nullable=False)
    thread = Column(JSON, default=list, nullable=False)  # Message history store karega
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)