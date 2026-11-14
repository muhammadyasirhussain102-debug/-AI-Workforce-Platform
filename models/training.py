import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from db.base import Base

class TrainingPlan(Base):
    __tablename__ = "training_plans"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    employee_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    # Day 1, 2, 3 content links aur quizzes ka structured data
    schedule = Column(JSON, default=list, nullable=False)
    status = Column(String(50), default="IN_PROGRESS", nullable=False)  # IN_PROGRESS, COMPLETED, FAILED
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class QuizResult(Base):
    __tablename__ = "quiz_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plan_id = Column(UUID(as_uuid=True), ForeignKey("training_plans.id", ondelete="CASCADE"), nullable=False)
    day_number = Column(Integer, nullable=False)
    attempt_number = Column(Integer, default=1, nullable=False)
    score = Column(Float, nullable=False)
    passed = Column(Boolean, default=False, nullable=False)
    submitted_at = Column(DateTime, default=datetime.utcnow, nullable=False)