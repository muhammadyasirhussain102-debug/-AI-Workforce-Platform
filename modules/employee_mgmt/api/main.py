from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from modules.employee_mgmt.api.routes import health, leave, policies, attendance, tickets, complaints

app = FastAPI(
    title="Enterprise AI Workforce Platform - Employee Management",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, tags=["Health"])
app.include_router(leave.router, prefix="/leave", tags=["Leave"])
app.include_router(policies.router, prefix="/policies", tags=["Policies"])
app.include_router(attendance.router, prefix="/attendance", tags=["Attendance"])
app.include_router(tickets.router, prefix="/tickets", tags=["Tickets"])
app.include_router(complaints.router, prefix="/complaints", tags=["Complaints"])

@app.get("/")
def read_root():
    return {"status": "online", "module": "employee_mgmt", "version": "1.0.0"}
