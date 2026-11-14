# Module Decisions & Architecture Log: Employee Management & Agentic RAG

## 1. Module Identity & Solo Ownership
- **Developer:** Solo Edition (Self-Reviewed, VS Code cockpit)
- **Primary Repository Workspace:** `modules/employee-mgmt` (web) and `modules/employee_mgmt` (api)
- **Core Entities:** `policy_documents`, `policy_chunks`, `leave_types`, `leave_requests`, `leave_balances`, `attendance`, `tickets`, `training_plans`, `quiz_results`, `complaints`
- **Extra Table Prefix:** `emp_`

---

## 2. Six Non-Negotiable Module Rules
1. **Search finds, agent explains, code decides:** Leave days, balances, working days, and policy violations are computed in plain Python code, never by LLM math.
2. **No citation, no answer:** If Policy Brain cannot ground an answer with verified chunks, it abstains and routes the question to an HR ticket.
3. **Identity comes from login session:** Tools like `get_my_leave_balance` pull identity from the server session, never from model prompts.
4. **Documents are untrusted data:** Uploaded files cannot instruct the agent. Document visibility (`all`, `managers`, `hr_only`) and `tenant_id` are enforced in SQL before retrieval.
5. **Fail closed on money, law, and identity:** Leave exceptions, payroll lock edits, and policy publishing mandate explicit approval steps. Compliance advice is advisory, not legal counsel.
6. **Zero-trace anonymous complaints:** The anonymous complaint box stores no user ID, no IP address, no user agent, and records date only (no exact time).

---

## 3. Architecture Decision Records (ADRs)

### ADR-001: Labour Law Corpus Partitioning
- **Decision:** Labour-law documents use `tenant_id = NULL`.
- **Reason:** Accessible as read-only by all tenants under Row-Level Security (RLS), writable by none.
- **Date:** 2026-11-14

### ADR-002: Anonymous Complaint Box Privacy
- **Decision:** Total identity omission in DB, application logs, and traces.
- **Reason:** Complete whistleblower protection.
- **Implementation:** Excluded from request logging middleware; tracking via `case_code_hash` and salted `secret_key_hash`. Small-team threshold enforces suppression of counts `< 5`.
- **Date:** 2026-11-14

### ADR-003: Public Contracts (`pub_` Read Views)
- **pub_attendance:** `(tenant_id, employee_id, date, status, source, is_locked)`
- **pub_leave:** `(tenant_id, employee_id, leave_type, start_date, end_date, working_days, status)`
- **pub_training_progress:** `(tenant_id, employee_id, plan_id, modules_completed, total_modules, status)`
- **pub_ticket_summary:** `(tenant_id, category, status, count)`
- **pub_complaint_counts:** `(category, month, total_count)` where `total_count >= 5`
- **Date:** 2026-11-14

### ADR-004: Event Registry
- **Incoming Events:** `employee.created` (idempotent setup of balances, training, and attendance).
- **Outgoing Events:** `leave.approved`, `leave.cancelled`, `attendance.month_locked`.
- **Approval Types:** `policy.publish`, `leave.exception`, `attendance.post_lock_edit`.
- **Date:** 2026-11-14

---

## 4. State Machines

### Policy Document
`DRAFT` -> `PROCESSING` -> `REVIEW` -> `ACTIVE` -> `SUPERSEDED` / `FAILED`

### Leave Request
`DRAFT` -> `SUBMITTED` -> `PENDING_MANAGER` -> `PENDING_HR_EXCEPTION` (if violation) -> `APPROVED` / `REJECTED` / `CANCELLED` / `EXPIRED`

### Attendance Record
`PRESENT` | `ABSENT` | `ON_LEAVE` | `HALF_DAY` | `HOLIDAY` | `WEEKEND` | `LATE`

### Ticket (Helpdesk)
`OPEN` -> `IN_PROGRESS` -> `WAITING` -> `RESOLVED` -> `CLOSED`

### Anonymous Complaint
`NEW` -> `ACKNOWLEDGED` -> `INVESTIGATING` -> `RESOLVED` -> `CLOSED`

---

## 5. Phase Progress Log
- [x] **S0: Prepare** - Environment setup, ADR logging, directory scaffolding.
- [x] **S1: Data & Contracts** - Core models, Pydantic schemas, initial API stubs, and `pub_` views defined.
- [x] **S2: Policy Ingestion** - Document chunking, section extraction, and SQL security filters.
- [ ] **S3: Policy Brain (Agentic RAG)** - LangGraph node graph, citation verification, and fallback HR ticketing.
- [ ] **S4: LeaveFlow** - Policy check engine rules and temporal workflow orchestration.
- [ ] **S5: Attendance** - Daily entry, month lock, and payroll sync.
- [ ] **S6: Helpdesk** - KB answer-or-ticket flow with SLA timers.
- [ ] **S7: Training** - Day 1-3 scheduled plans and quiz retries.
- [ ] **S8: Compliance & Complaints** - Labour law diff engine and anonymous hash box.
- [ ] **S9: Hardening & Integration** - Failure drills, eval benchmark, and demo verification.