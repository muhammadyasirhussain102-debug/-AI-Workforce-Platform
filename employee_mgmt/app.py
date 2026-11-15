from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from employee_mgmt.routes import policies, leave, attendance, tickets, complaints, training

app = FastAPI(title="Employee Management & Agentic RAG", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Har router ka prefix ensure karein taake 404 khatam ho
app.include_router(policies.router)
app.include_router(leave.router)
app.include_router(attendance.router)
app.include_router(tickets.router)
app.include_router(complaints.router)
app.include_router(training.router)

@app.get("/")
def root():
    return {"status": "online", "system": "Policy Brain & Enterprise Workforce OS"}