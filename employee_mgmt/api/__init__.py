"""API package for the Employee Management module."""

from __future__ import annotations

from fastapi import APIRouter

API_V1_PREFIX: str = "/api/v1"

# Central router for Employee Management API endpoints.
# Individual feature routers from `api/routes/` will be registered here
# as each route file is implemented.
api_router = APIRouter()


def get_api_router() -> APIRouter:
    """Return the configured API router for mounting in app.py."""
    return api_router


__all__ = ["API_V1_PREFIX", "api_router", "get_api_router"]