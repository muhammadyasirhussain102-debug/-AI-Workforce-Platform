"""Health check routes for the Employee Management API."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

try:
    from ... import MODULE_NAME, __version__
except ImportError:
    MODULE_NAME = "employee_mgmt"
    __version__ = "1.0.0"

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    """Standard health status response schema."""

    status: Literal["ok"] = Field(default="ok", description="Overall service health.")
    module: str = Field(..., description="Active backend module identifier.")
    version: str = Field(..., description="Current module version.")
    timestamp: str = Field(..., description="Current UTC timestamp in ISO-8601 format.")


class ReadinessResponse(BaseModel):
    """Readiness probe response schema."""

    status: Literal["ready"] = Field(
        default="ready", description="Indicates whether the service can accept traffic."
    )
    module: str = Field(..., description="Active backend module identifier.")
    checks: dict[str, str] = Field(
        ..., description="High-level non-sensitive dependency check states."
    )
    timestamp: str = Field(..., description="Current UTC timestamp in ISO-8601 format.")


def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


@router.get(
    "",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Check service health",
)
async def health_check() -> HealthResponse:
    """Return basic service health metadata for frontend and monitoring checks."""
    return HealthResponse(
        status="ok",
        module=MODULE_NAME,
        version=__version__,
        timestamp=_utc_now_iso(),
    )


@router.get(
    "/live",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Liveness probe",
)
async def liveness_check() -> HealthResponse:
    """Verify that the FastAPI process is alive and responding."""
    return HealthResponse(
        status="ok",
        module=MODULE_NAME,
        version=__version__,
        timestamp=_utc_now_iso(),
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    status_code=status.HTTP_200_OK,
    summary="Readiness probe",
)
async def readiness_check() -> ReadinessResponse:
    """Verify that the service is ready to handle incoming requests."""
    return ReadinessResponse(
        status="ready",
        module=MODULE_NAME,
        checks={"application": "ok"},
        timestamp=_utc_now_iso(),
    )


__all__ = ["router", "HealthResponse", "ReadinessResponse"]