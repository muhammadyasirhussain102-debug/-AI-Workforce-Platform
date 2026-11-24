"""Training & Quizzes API routes for the Employee Management module.

Provides tenant-isolated training plan creation, employee training assignments,
deterministic server-side quiz grading, and completion/pass tracking without
exposing quiz answer keys to learners.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from threading import Lock
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator, model_validator

from .policies import SessionUser, get_current_user

router = APIRouter(prefix="/training", tags=["training"])

AssignmentStatus = Literal["assigned", "in_progress", "completed"]

TRAINING_ADMIN_ROLES: frozenset[str] = frozenset({"hr", "admin"})
TRAINING_SUPERVISOR_ROLES: frozenset[str] = frozenset({"manager", "hr", "admin"})


# ---------------------------------------------------------------------------
# Request / Response Schemas
# (Will be moved to dedicated schema modules once created.)
# ---------------------------------------------------------------------------


class QuizQuestionCreate(BaseModel):
    """Single multiple-choice quiz question defined by HR/Admin."""

    prompt: str = Field(..., min_length=5, max_length=500)
    options: list[str] = Field(..., min_length=2, max_length=6)
    correct_option_index: int = Field(..., ge=0)

    @field_validator("prompt")
    @classmethod
    def strip_prompt(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 5:
            raise ValueError("Question prompt must be at least 5 characters long.")
        return cleaned

    @field_validator("options")
    @classmethod
    def validate_options(cls, value: list[str]) -> list[str]:
        cleaned_options = [opt.strip() for opt in value]
        if any(not opt for opt in cleaned_options):
            raise ValueError("Quiz options cannot be empty or whitespace.")
        if len(set(opt.lower() for opt in cleaned_options)) != len(cleaned_options):
            raise ValueError("Quiz options within a question must be unique.")
        return cleaned_options

    @model_validator(mode="after")
    def validate_correct_index(self) -> QuizQuestionCreate:
        if self.correct_option_index >= len(self.options):
            raise ValueError(
                "correct_option_index must point to a valid index in options."
            )
        return self


class QuizQuestionPublic(BaseModel):
    """Sanitized quiz question returned to clients (never exposes answer key)."""

    question_id: str
    prompt: str
    options: list[str]


class TrainingPlanCreateRequest(BaseModel):
    """Payload to create a tenant-scoped training plan and its quiz."""

    title: str = Field(..., min_length=3, max_length=180)
    description: str = Field(..., min_length=10, max_length=2000)
    category: str = Field(default="compliance", min_length=2, max_length=60)
    passing_score_percent: int = Field(default=80, ge=1, le=100)
    questions: list[QuizQuestionCreate] = Field(..., min_length=1, max_length=50)

    @field_validator("title", "description", "category")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Field cannot be empty or whitespace.")
        return cleaned

    @field_validator("category")
    @classmethod
    def normalize_category(cls, value: str) -> str:
        return value.lower()


class TrainingPlanResponse(BaseModel):
    """Public representation of a training plan (answer keys excluded)."""

    id: str
    tenant_id: str
    title: str
    description: str
    category: str
    passing_score_percent: int
    total_questions: int
    questions: list[QuizQuestionPublic]
    is_active: bool
    created_by: str
    created_at: str


class TrainingPlanListResponse(BaseModel):
    """Paginated list of training plans."""

    total: int
    limit: int
    offset: int
    items: list[TrainingPlanResponse]


class TrainingAssignmentCreateRequest(BaseModel):
    """Payload to assign a training plan to an employee."""

    employee_id: str = Field(..., min_length=1, max_length=100)
    due_date: date | None = Field(default=None)

    @field_validator("employee_id")
    @classmethod
    def strip_employee_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("employee_id cannot be empty or whitespace.")
        return cleaned


class TrainingAssignmentResponse(BaseModel):
    """Training plan assignment and completion/pass progress for an employee."""

    id: str
    tenant_id: str
    plan_id: str
    plan_title: str
    employee_id: str
    assigned_by: str
    assigned_at: str
    due_date: date | None = None
    status: AssignmentStatus
    attempts_count: int
    best_score_percent: float | None = None
    passed: bool
    completed_at: str | None = None
    updated_at: str


class TrainingAssignmentListResponse(BaseModel):
    """Paginated list of training assignments."""

    total: int
    limit: int
    offset: int
    items: list[TrainingAssignmentResponse]


class QuizAnswerItem(BaseModel):
    """Single selected answer submitted by an employee."""

    question_id: str = Field(..., min_length=1, max_length=50)
    selected_option_index: int = Field(..., ge=0)

    @field_validator("question_id")
    @classmethod
    def strip_question_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("question_id cannot be blank.")
        return cleaned


class QuizSubmissionRequest(BaseModel):
    """Quiz answers submitted for deterministic server-side grading."""

    answers: list[QuizAnswerItem] = Field(..., min_length=1, max_length=50)

    @model_validator(mode="after")
    def validate_unique_questions(self) -> QuizSubmissionRequest:
        seen_ids: set[str] = set()
        for item in self.answers:
            if item.question_id in seen_ids:
                raise ValueError(
                    f"Duplicate answer submitted for question '{item.question_id}'."
                )
            seen_ids.add(item.question_id)
        return self


class QuizAttemptResponse(BaseModel):
    """Graded quiz attempt result calculated deterministically on the server."""

    id: str
    tenant_id: str
    plan_id: str
    plan_title: str
    employee_id: str
    correct_answers: int
    total_questions: int
    score_percent: float
    passing_score_percent: int
    passed: bool
    submitted_at: str


class QuizAttemptListResponse(BaseModel):
    """Paginated list of quiz attempts."""

    total: int
    limit: int
    offset: int
    items: list[QuizAttemptResponse]


# ---------------------------------------------------------------------------
# Temporary Thread-Safe In-Memory Stores
# (Will be replaced by DB/service layer once models & db/session.py exist.)
# ---------------------------------------------------------------------------

_STORE_LOCK = Lock()
_PLAN_STORE: dict[str, dict[str, Any]] = {}
_ASSIGNMENT_STORE: dict[str, dict[str, Any]] = {}
_ATTEMPT_STORE: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Security & Deterministic Helper Functions
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _to_public_plan_response(record: dict[str, Any]) -> TrainingPlanResponse:
    """Serialize a stored plan while stripping all correct answer indices."""
    public_questions = [
        QuizQuestionPublic(
            question_id=q["question_id"],
            prompt=q["prompt"],
            options=list(q["options"]),
        )
        for q in record["questions"]
    ]
    return TrainingPlanResponse(
        id=record["id"],
        tenant_id=record["tenant_id"],
        title=record["title"],
        description=record["description"],
        category=record["category"],
        passing_score_percent=record["passing_score_percent"],
        total_questions=len(public_questions),
        questions=public_questions,
        is_active=record["is_active"],
        created_by=record["created_by"],
        created_at=record["created_at"],
    )


def _find_assignment_unlocked(
    tenant_id: str, plan_id: str, employee_id: str
) -> dict[str, Any] | None:
    """Return an existing assignment for (tenant, plan, employee) if present."""
    for record in _ASSIGNMENT_STORE.values():
        if (
            record["tenant_id"] == tenant_id
            and record["plan_id"] == plan_id
            and record["employee_id"] == employee_id
        ):
            return record
    return None


def _can_view_employee_record(
    current_user: SessionUser, record: dict[str, Any]
) -> bool:
    """Enforce tenant isolation and self/supervisor read visibility."""
    if record["tenant_id"] != current_user.tenant_id:
        return False
    if record["employee_id"] == current_user.user_id:
        return True
    return current_user.role in TRAINING_SUPERVISOR_ROLES


# ---------------------------------------------------------------------------
# Route Handlers
# ---------------------------------------------------------------------------


@router.post(
    "/plans",
    response_model=TrainingPlanResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new training plan with quiz questions",
)
async def create_training_plan(
    payload: TrainingPlanCreateRequest,
    current_user: SessionUser = Depends(get_current_user),
) -> TrainingPlanResponse:
    """Create a tenant-scoped training plan and store quiz answer keys server-side."""
    if current_user.role not in TRAINING_ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only HR or Admin roles are authorized to create training plans.",
        )

    plan_id = f"trn_{uuid4().hex[:12]}"
    stored_questions = [
        {
            "question_id": f"q_{idx + 1}",
            "prompt": question.prompt,
            "options": list(question.options),
            "correct_option_index": question.correct_option_index,
        }
        for idx, question in enumerate(payload.questions)
    ]

    record: dict[str, Any] = {
        "id": plan_id,
        "tenant_id": current_user.tenant_id,
        "title": payload.title,
        "description": payload.description,
        "category": payload.category,
        "passing_score_percent": payload.passing_score_percent,
        "questions": stored_questions,
        "is_active": True,
        "created_by": current_user.user_id,
        "created_at": _utc_now_iso(),
    }

    with _STORE_LOCK:
        _PLAN_STORE[plan_id] = record

    return _to_public_plan_response(record)


@router.get(
    "/plans",
    response_model=TrainingPlanListResponse,
    status_code=status.HTTP_200_OK,
    summary="List training plans in the current tenant",
)
async def list_training_plans(
    category: str | None = Query(default=None, min_length=2, max_length=60),
    is_active: bool | None = Query(default=True),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: SessionUser = Depends(get_current_user),
) -> TrainingPlanListResponse:
    """List tenant-scoped training plans without exposing answer keys."""
    normalized_category = category.strip().lower() if category else None

    with _STORE_LOCK:
        records = list(_PLAN_STORE.values())

    visible_records = [
        rec
        for rec in records
        if rec["tenant_id"] == current_user.tenant_id
        and (normalized_category is None or rec["category"] == normalized_category)
        and (is_active is None or rec["is_active"] == is_active)
    ]

    visible_records.sort(key=lambda item: item["created_at"], reverse=True)
    paginated = visible_records[offset : offset + limit]

    return TrainingPlanListResponse(
        total=len(visible_records),
        limit=limit,
        offset=offset,
        items=[_to_public_plan_response(rec) for rec in paginated],
    )


@router.get(
    "/plans/{plan_id}",
    response_model=TrainingPlanResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a single training plan",
)
async def get_training_plan(
    plan_id: str,
    current_user: SessionUser = Depends(get_current_user),
) -> TrainingPlanResponse:
    """Retrieve a single tenant-scoped training plan (answer keys stripped)."""
    with _STORE_LOCK:
        record = _PLAN_STORE.get(plan_id)

    if record is None or record["tenant_id"] != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Training plan not found.",
        )

    return _to_public_plan_response(record)


@router.post(
    "/plans/{plan_id}/assign",
    response_model=TrainingAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Assign a training plan to an employee",
)
async def assign_training_plan(
    plan_id: str,
    payload: TrainingAssignmentCreateRequest,
    current_user: SessionUser = Depends(get_current_user),
) -> TrainingAssignmentResponse:
    """Assign an active training plan to an employee (Manager/HR/Admin only)."""
    if current_user.role not in TRAINING_SUPERVISOR_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Manager, HR, or Admin roles can assign training plans.",
        )

    with _STORE_LOCK:
        plan = _PLAN_STORE.get(plan_id)
        if plan is None or plan["tenant_id"] != current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Training plan not found.",
            )

        if not plan["is_active"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot assign an inactive training plan.",
            )

        existing = _find_assignment_unlocked(
            tenant_id=current_user.tenant_id,
            plan_id=plan_id,
            employee_id=payload.employee_id,
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This training plan is already assigned to the employee.",
            )

        now_iso = _utc_now_iso()
        assignment_id = f"asg_{uuid4().hex[:12]}"
        record: dict[str, Any] = {
            "id": assignment_id,
            "tenant_id": current_user.tenant_id,
            "plan_id": plan_id,
            "plan_title": plan["title"],
            "employee_id": payload.employee_id,
            "assigned_by": current_user.user_id,
            "assigned_at": now_iso,
            "due_date": payload.due_date,
            "status": "assigned",
            "attempts_count": 0,
            "best_score_percent": None,
            "passed": False,
            "completed_at": None,
            "updated_at": now_iso,
        }
        _ASSIGNMENT_STORE[assignment_id] = record

    return TrainingAssignmentResponse(**record)


@router.get(
    "/assignments",
    response_model=TrainingAssignmentListResponse,
    status_code=status.HTTP_200_OK,
    summary="List training assignments and completion status",
)
async def list_training_assignments(
    employee_id: str | None = Query(default=None, min_length=1, max_length=100),
    plan_id: str | None = Query(default=None, min_length=1, max_length=100),
    assignment_status: AssignmentStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: SessionUser = Depends(get_current_user),
) -> TrainingAssignmentListResponse:
    """List tenant-scoped training assignments visible to the current user."""
    normalized_employee_id = employee_id.strip() if employee_id else None
    if (
        normalized_employee_id is not None
        and normalized_employee_id != current_user.user_id
        and current_user.role not in TRAINING_SUPERVISOR_ROLES
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are only authorized to view your own training assignments.",
        )

    with _STORE_LOCK:
        records = list(_ASSIGNMENT_STORE.values())

    visible_records = [
        rec
        for rec in records
        if _can_view_employee_record(current_user, rec)
        and (
            normalized_employee_id is None
            or rec["employee_id"] == normalized_employee_id
        )
        and (plan_id is None or rec["plan_id"] == plan_id)
        and (assignment_status is None or rec["status"] == assignment_status)
    ]

    visible_records.sort(key=lambda item: item["assigned_at"], reverse=True)
    paginated = visible_records[offset : offset + limit]

    return TrainingAssignmentListResponse(
        total=len(visible_records),
        limit=limit,
        offset=offset,
        items=[TrainingAssignmentResponse(**rec) for rec in paginated],
    )


@router.post(
    "/plans/{plan_id}/submit",
    response_model=QuizAttemptResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit quiz answers for deterministic grading",
)
async def submit_quiz_attempt(
    plan_id: str,
    payload: QuizSubmissionRequest,
    current_user: SessionUser = Depends(get_current_user),
) -> QuizAttemptResponse:
    """Grade an authenticated employee's quiz answers deterministically on the server."""
    with _STORE_LOCK:
        plan = _PLAN_STORE.get(plan_id)
        if plan is None or plan["tenant_id"] != current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Training plan not found.",
            )

        if not plan["is_active"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot submit a quiz for an inactive training plan.",
            )

        existing_assignment = _find_assignment_unlocked(
            tenant_id=current_user.tenant_id,
            plan_id=plan_id,
            employee_id=current_user.user_id,
        )
        if existing_assignment is not None and existing_assignment["passed"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You have already passed and completed this training quiz.",
            )

        question_map: dict[str, dict[str, Any]] = {
            q["question_id"]: q for q in plan["questions"]
        }
        submitted_map: dict[str, int] = {
            item.question_id: item.selected_option_index for item in payload.answers
        }

        unknown_ids = set(submitted_map.keys()) - set(question_map.keys())
        if unknown_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown question_id(s) submitted: {sorted(unknown_ids)}.",
            )

        missing_ids = set(question_map.keys()) - set(submitted_map.keys())
        if missing_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"All quiz questions must be answered. "
                    f"Missing question_id(s): {sorted(missing_ids)}."
                ),
            )

        correct_answers = 0
        for q_id, question in question_map.items():
            selected_idx = submitted_map[q_id]
            if selected_idx >= len(question["options"]):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Selected option index {selected_idx} is out of range "
                        f"for question '{q_id}'."
                    ),
                )
            if selected_idx == question["correct_option_index"]:
                correct_answers += 1

        total_questions = len(question_map)
        score_percent = round((correct_answers / total_questions) * 100.0, 2)
        passed = score_percent >= float(plan["passing_score_percent"])
        now_iso = _utc_now_iso()

        attempt_id = f"att_{uuid4().hex[:12]}"
        attempt_record: dict[str, Any] = {
            "id": attempt_id,
            "tenant_id": current_user.tenant_id,
            "plan_id": plan_id,
            "plan_title": plan["title"],
            "employee_id": current_user.user_id,
            "correct_answers": correct_answers,
            "total_questions": total_questions,
            "score_percent": score_percent,
            "passing_score_percent": plan["passing_score_percent"],
            "passed": passed,
            "submitted_at": now_iso,
        }
        _ATTEMPT_STORE[attempt_id] = attempt_record

        if existing_assignment is None:
            assignment_id = f"asg_{uuid4().hex[:12]}"
            _ASSIGNMENT_STORE[assignment_id] = {
                "id": assignment_id,
                "tenant_id": current_user.tenant_id,
                "plan_id": plan_id,
                "plan_title": plan["title"],
                "employee_id": current_user.user_id,
                "assigned_by": current_user.user_id,
                "assigned_at": now_iso,
                "due_date": None,
                "status": "completed" if passed else "in_progress",
                "attempts_count": 1,
                "best_score_percent": score_percent,
                "passed": passed,
                "completed_at": now_iso if passed else None,
                "updated_at": now_iso,
            }
        else:
            previous_best = existing_assignment["best_score_percent"]
            best_score = (
                score_percent
                if previous_best is None
                else max(float(previous_best), score_percent)
            )
            updated_assignment = {
                **existing_assignment,
                "status": "completed" if passed else "in_progress",
                "attempts_count": existing_assignment["attempts_count"] + 1,
                "best_score_percent": best_score,
                "passed": passed or existing_assignment["passed"],
                "completed_at": now_iso if passed else existing_assignment["completed_at"],
                "updated_at": now_iso,
            }
            _ASSIGNMENT_STORE[existing_assignment["id"]] = updated_assignment

    return QuizAttemptResponse(**attempt_record)


@router.get(
    "/attempts",
    response_model=QuizAttemptListResponse,
    status_code=status.HTTP_200_OK,
    summary="List graded quiz attempts",
)
async def list_quiz_attempts(
    plan_id: str | None = Query(default=None, min_length=1, max_length=100),
    employee_id: str | None = Query(default=None, min_length=1, max_length=100),
    passed: bool | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: SessionUser = Depends(get_current_user),
) -> QuizAttemptListResponse:
    """List tenant-scoped quiz attempts visible to the authenticated user."""
    normalized_employee_id = employee_id.strip() if employee_id else None
    if (
        normalized_employee_id is not None
        and normalized_employee_id != current_user.user_id
        and current_user.role not in TRAINING_SUPERVISOR_ROLES
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are only authorized to view your own quiz attempts.",
        )

    with _STORE_LOCK:
        records = list(_ATTEMPT_STORE.values())

    visible_records = [
        rec
        for rec in records
        if _can_view_employee_record(current_user, rec)
        and (plan_id is None or rec["plan_id"] == plan_id)
        and (
            normalized_employee_id is None
            or rec["employee_id"] == normalized_employee_id
        )
        and (passed is None or rec["passed"] == passed)
    ]

    visible_records.sort(key=lambda item: item["submitted_at"], reverse=True)
    paginated = visible_records[offset : offset + limit]

    return QuizAttemptListResponse(
        total=len(visible_records),
        limit=limit,
        offset=offset,
        items=[QuizAttemptResponse(**rec) for rec in paginated],
    )


__all__ = [
    "router",
    "QuizQuestionCreate",
    "QuizQuestionPublic",
    "TrainingPlanCreateRequest",
    "TrainingPlanResponse",
    "TrainingPlanListResponse",
    "TrainingAssignmentCreateRequest",
    "TrainingAssignmentResponse",
    "TrainingAssignmentListResponse",
    "QuizAnswerItem",
    "QuizSubmissionRequest",
    "QuizAttemptResponse",
    "QuizAttemptListResponse",
]