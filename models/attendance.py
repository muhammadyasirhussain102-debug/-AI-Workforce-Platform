import uuid
from datetime import date
from enum import Enum
from sqlalchemy import Column, String, Date, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from db.base import Base

class AttendanceStatus(str, Enum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    ON_LEAVE = "ON_LEAVE"
    HALF_DAY = "HALF_DAY"
    HOLIDAY = "HOLIDAY"
    WEEKEND = "WEEKEND"
    LATE = "LATE"

class Attendance(Base):
    __tablename__ = "attendance"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    employee_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    date = Column(Date, default=date.today, nullable=False, index=True)
    status = Column(SQLEnum(AttendanceStatus), default=AttendanceStatus.PRESENT, nullable=False)
    source = Column(String(50), default="check-in", nullable=False)  # check-in, manager, HR, import, leave
    locked_at = Column(DateTime, nullable=True)  # Populated when HR locks the month