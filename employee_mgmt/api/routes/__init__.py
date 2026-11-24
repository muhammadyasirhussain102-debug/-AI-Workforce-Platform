"""Route package for the Employee Management API.

Individual feature routers (health, policies, leave, attendance, tickets,
training, and complaints) will be registered here as each route file is
implemented.
"""

from __future__ import annotations

from fastapi import APIRouter

# Feature routers will be added to this tuple as each route module is completed.
FEATURE_ROUTERS: tuple[APIRouter, ...] = ()


def build_routes_router() -> APIRouter:
    """Create and return an APIRouter combining all registered feature routers."""
    combined_router = APIRouter()
    for feature_router in FEATURE_ROUTERS:
        combined_router.include_router(feature_router)
    return combined_router


def register_routes(parent_router: APIRouter) -> APIRouter:
    """Attach all registered feature routers onto the provided parent router."""
    if not isinstance(parent_router, APIRouter):
        raise TypeError("parent_router must be a FastAPI APIRouter instance.")

    for feature_router in FEATURE_ROUTERS:
        parent_router.include_router(feature_router)
    return parent_router


routes_router = build_routes_router()

__all__ = [
    "FEATURE_ROUTERS",
    "routes_router",
    "build_routes_router",
    "register_routes",
]