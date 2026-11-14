"""
Public read-only database views for external modules (e.g. Payroll).
Roadmap Contract:
- pub_attendance: employee_id, date, status, source, is_locked
- pub_leave: employee_id, leave_type, start_date, end_date, working_days, status
- pub_complaint_counts: counts per category/month, hiding small teams (<5)
"""

CREATE_PUB_ATTENDANCE_VIEW = """
CREATE OR REPLACE VIEW pub_attendance AS
SELECT 
    a.tenant_id,
    a.employee_id,
    a.date,
    a.status,
    a.source,
    (a.locked_at IS NOT NULL) AS is_locked
FROM attendance a;
"""

CREATE_PUB_LEAVE_VIEW = """
CREATE OR REPLACE VIEW pub_leave AS
SELECT 
    lr.tenant_id,
    lr.employee_id,
    lt.name AS leave_type,
    lr.start_date,
    lr.end_date,
    lr.working_days,
    lr.status
FROM leave_requests lr
JOIN leave_types lt ON lr.type_id = lt.id;
"""

CREATE_PUB_COMPLAINT_COUNTS_VIEW = """
CREATE OR REPLACE VIEW pub_complaint_counts AS
SELECT 
    category,
    TO_CHAR(created_date, 'YYYY-MM') AS month,
    COUNT(*) AS total_count
FROM complaints
GROUP BY category, TO_CHAR(created_date, 'YYYY-MM')
HAVING COUNT(*) >= 5;  -- Small teams identity protection (Rule 6)
"""