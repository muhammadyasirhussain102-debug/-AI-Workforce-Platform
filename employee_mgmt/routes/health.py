from fastapi import APIRouter
from datetime import datetime

router = APIRouter(prefix="/health", tags=["System Health"])

@router.get("")
async def health_check():
    """Liveness probe to confirm module status."""
    return {
        "status": "healthy",
        "module": "employee_mgmt",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat()
    }