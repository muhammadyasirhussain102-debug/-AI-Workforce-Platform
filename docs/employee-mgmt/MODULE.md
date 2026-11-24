# Employee Management, Agentic RAG & Automation Module

## 1. Architecture Overview
This module is organized into three clear layers:
- **Documentation (`docs/employee-mgmt/MODULE.md`):** Module specification, boundaries, and operational guardrails.
- **Frontend (`modules/employee-mgmt/`):** Browser UI (`index.html`), navigation definitions (`src/nav.ts`), API client (`src/api/client.ts`), UI components (`src/components/`), pages (`src/pages/`), and design tokens (`src/styles/tokens.css`).
- **Backend (`modules/employee_mgmt/`):** FastAPI application (`app.py`), route handlers (`api/routes/`), configuration (`core/config.py`), database session/base (`db/`), SQLAlchemy models (`models/`), Pydantic schemas (`schemas/`), business services (`services/`), migrations (`migrations/versions/`), and tests (`tests/`).

## 2. Core Functional Areas
- **Policy Brain (RAG & Search):** Policy ingestion, chunking, visibility filtering, and citation-backed answers.
- **LeaveFlow:** Leave requests, code-calculated leave balances, status transitions, and approval checks.
- **Face ID & Attendance:** Biometric check-in/check-out tracking, lock protection, and audit-safe records.
- **IT Support Tickets:** Ticket creation, lifecycle status updates, and lock enforcement.
- **Training & Quizzes:** Training plans and quiz completion/pass tracking.
- **Anonymous Complaint Box:** Privacy-preserving submission and status tracking.

## 3. Non-Negotiable Guardrails
- **Identity & Tenancy:** Server session/auth context determines user identity and tenant scope; never trust raw client-supplied identity headers without verification.
- **Deterministic Business Logic:** Leave balances, eligibility, and state transitions are computed in backend code—never guessed by an LLM.
- **Fail-Closed High-Risk Actions:** High-risk operations (`policy.publish`, `leave.exception`, `attendance.post_lock_edit`) must fail closed if required approvals are missing.
- **Whistleblower Privacy:** Anonymous complaints must not store `user_id`, IP address, user-agent, or identifying metadata.
- **Grounded Citations:** Policy responses should rely on retrieved policy chunks rather than unverified assumptions.