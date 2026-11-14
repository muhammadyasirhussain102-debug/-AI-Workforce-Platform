import uuid
from datetime import date
from enum import Enum
from sqlalchemy import Column, String, Integer, Float, Boolean, Date, JSON, ForeignKey, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from db.base import Base

class LeaveRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PENDING_MANAGER = "PENDING_MANAGER"
    PENDING_HR_EXCEPTION = "PENDING_HR_EXCEPTION"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"

class LeaveType(Base):
    __tablename__ = "leave_types"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    paid = Column(Boolean, default=True, nullable=False)
    rules = Column(JSON, nullable=False, default=dict)
    active = Column(Boolean, default=True, nullable=False)

class LeaveRequest(Base):
    __tablename__ = "leave_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    employee_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    type_id = Column(UUID(as_uuid=True), ForeignKey("leave_types.id"), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    half_day = Column(Boolean, default=False)
    working_days = Column(Float, nullable=False)
    status = Column(SQLEnum(LeaveRequestStatus), default=LeaveRequestStatus.DRAFT, nullable=False)
    check_result = Column(JSON, nullable=True)
    reason = Column(String(500), nullable=True)
    workflow_id = Column(String(255), nullable=True)

class LeaveBalance(Base):
    __tablename__ = "leave_balances"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    employee_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    type_id = Column(UUID(as_uuid=True), ForeignKey("leave_types.id"), nullable=False)
    year = Column(Integer, nullable=False)
    entitled = Column(Float, default=0.0, nullable=False)
    used = Column(Float, default=0.0, nullable=False)
    reserved = Column(Float, default=0.0, nullable=False)