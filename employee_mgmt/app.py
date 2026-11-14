from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from employee_mgmt.routes.leave import router as leave_router
from employee_mgmt.routes.policies import router as policy_router
from employee_mgmt.routes.complaints import router as complaint_router
from employee_mgmt.routes.attendance import router as attendance_router
from employee_mgmt.routes.tickets import router as ticket_router
from employee_mgmt.routes.training import router as training_router

app = FastAPI(
    title="Employee Management & Agentic RAG",
    description="Solo Module Core Feature 2 API",
    version="1.0.0"
)

# Frontend browser se connect karne ke liye
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Saare routes mount ho rahe hain
app.include_router(leave_router, prefix="/api/v1")
app.include_router(policy_router, prefix="/api/v1")
app.include_router(complaint_router, prefix="/api/v1")
app.include_router(attendance_router, prefix="/api/v1")
app.include_router(ticket_router, prefix="/api/v1")
app.include_router(training_router, prefix="/api/v1")

@app.get("/")
async def root():
    return {"status": "running", "module": "employee_mgmt"}