"""FastAPI application entry point for the Employee Management module."""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging
import os
from typing import AsyncIterator

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

try:
    from . import MODULE_NAME, __version__
except ImportError:
    MODULE_NAME = "employee_mgmt"
    __version__ = "1.0.0"

logger = logging.getLogger(MODULE_NAME)

API_V1_PREFIX = "/api/v1"

DEFAULT_CORS_ORIGINS: list[str] = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
]


def _get_allowed_origins() -> list[str]:
    """Load explicit CORS origins from environment or safe local defaults."""
    raw_origins = os.getenv("CORS_ORIGINS", "").strip()
    if not raw_origins:
        return DEFAULT_CORS_ORIGINS

    origins = [
        origin.strip().rstrip("/")
        for origin in raw_origins.split(",")
        if origin.strip() and origin.strip() != "*"
    ]
    return origins or DEFAULT_CORS_ORIGINS


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and shutdown lifecycle cleanly."""
    logger.info("Starting %s backend service (v%s)", MODULE_NAME, __version__)
    yield
    logger.info("Shutting down %s backend service", MODULE_NAME)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    application = FastAPI(
        title="AI Workforce Platform — Employee Management API",
        version=__version__,
        description=(
            "Backend API for Employee Management, Agentic RAG, LeaveFlow, "
            "Attendance, IT Support Tickets, Training, and Anonymous Complaints."
        ),
        lifespan=lifespan,
    )

    # Explicit origins are required when frontend sends credentials ("include").
    application.add_middleware(
        CORSMiddleware,
        allow_origins=_get_allowed_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept", "X-Requested-With"],
    )

    @application.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @application.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": exc.errors()},
        )

    @application.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "An internal server error occurred."},
        )

    @application.get("/", tags=["system"])
    async def root() -> dict[str, str]:
        return {
            "service": "AI Workforce Platform — Employee Management API",
            "module": MODULE_NAME,
            "version": __version__,
            "status": "running",
        }

    @application.get("/health", tags=["health"])
    @application.get(f"{API_V1_PREFIX}/health", tags=["health"])
    async def health_check() -> dict[str, str]:
        return {
            "status": "ok",
            "module": MODULE_NAME,
            "version": __version__,
        }

    # Feature routers from api/routes/ will be mounted here once created.
    return application


app = create_app()