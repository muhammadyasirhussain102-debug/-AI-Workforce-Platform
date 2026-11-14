"""
Routes package for employee_mgmt module.
Exports all API routers for FastAPI inclusion.
"""

from employee_mgmt.routes.health import router as health_router
from employee_mgmt.routes.leave import router as leave_router
from employee_mgmt.routes.policies import router as policy_router
from employee_mgmt.routes.complaints import router as complaint_router
from employee_mgmt.routes.attendance import router as attendance_router
from employee_mgmt.routes.tickets import router as ticket_router
from employee_mgmt.routes.training import router as training_router

__all__ = [
    "health_router",
    "leave_router",
    "policy_router",
    "complaint_router",
    "attendance_router",
    "ticket_router",
    "training_router",
]