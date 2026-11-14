import uuid
from datetime import date
from enum import Enum
from sqlalchemy import Column, String, Text, Date, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from db.base import Base

class ComplaintStatus(str, Enum):
    NEW = "NEW"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"

class Complaint(Base):
    __tablename__ = "complaints"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Strictly NO employee_id, NO user_id, NO IP address stored
    case_code_hash = Column(String(255), unique=True, nullable=False, index=True)
    secret_key_hash = Column(String(255), nullable=False)
    category = Column(String(100), nullable=False)
    severity = Column(String(50), default="medium", nullable=False)
    text = Column(Text, nullable=False)
    status = Column(SQLEnum(ComplaintStatus), default=ComplaintStatus.NEW, nullable=False)
    # Date only, no exact timestamp so user timing cannot be correlated
    created_date = Column(Date, default=date.today, nullable=False)