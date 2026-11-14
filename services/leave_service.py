from datetime import date, timedelta
from enum import Enum
from typing import Set, Dict, Any, Optional
from pydantic import BaseModel


class CheckOutcome(str, Enum):
    OK = "OK"
    NEEDS_ATTACHMENT = "NEEDS_ATTACHMENT"
    BLOCKED_BLACKOUT = "BLOCKED_BLACKOUT"
    VIOLATION = "VIOLATION"


class PolicyCheckResult(BaseModel):
    outcome: CheckOutcome
    working_days: float
    balance_after: float
    violations: list[str] = []
    required_attachments: list[str] = []


class LeavePolicyEngine:
    """
    Deterministic leave calculation engine (Rule 1).
    Zero LLM arithmetic: All calculations strictly executed in Python.
    """

    @staticmethod
    def calculate_working_days(
        start: date,
        end: date,
        holidays: Set[date],
        weekend_days: Set[int] = {5, 6},  # Saturday=5, Sunday=6
        half_day: bool = False
    ) -> float:
        if end < start:
            return 0.0

        total_days = 0.0
        cur = start
        while cur <= end:
            if cur.weekday() not in weekend_days and cur not in holidays:
                total_days += 0.5 if half_day else 1.0
            cur += timedelta(days=1)

        return total_days

    @classmethod
    def evaluate_request(
        cls,
        start: date,
        end: date,
        half_day: bool,
        rules: Dict[str, Any],
        current_balance: float,
        reserved_balance: float,
        is_probation: bool,
        holidays: Set[date],
        weekend_days: Set[int] = {5, 6},
        has_overlap: bool = False,
        today: Optional[date] = None
    ) -> PolicyCheckResult:
        if today is None:
            today = date.today()

        violations = []
        attachments = []

        # 1. Overlap Check
        if has_overlap:
            violations.append("Pehle se exist karti hui leave ke sath dates overlap kar rahi hain.")

        # 2. Working days calculate karein
        working_days = cls.calculate_working_days(start, end, holidays, weekend_days, half_day)

        # 3. Probation Check
        allowed_in_probation = rules.get("allowed_during_probation", True)
        if is_probation and not allowed_in_probation:
            violations.append("Probation period ke dauran yeh leave type allowed nahi hai.")

        # 4. Notice Period Check
        min_notice = rules.get("min_notice_days", 0)
        notice_given = (start - today).days
        if notice_given < min_notice:
            violations.append(f"Is leave ke liye kam az kam {min_notice} din pehle notice zaroori hai.")

        # 5. Balance Check
        available = current_balance - reserved_balance
        if working_days > available:
            violations.append(f"Kafi balance nahi hai. Darkar: {working_days}, Dastyab: {available}")

        # 6. Attachment Check (e.g. medical certificate for sick leaves > 2 days)
        requires_cert_after = rules.get("requires_attachment_after_days", 0)
        if requires_cert_after > 0 and working_days > requires_cert_after:
            attachments.append("Medical Certificate / Proof Document")

        # Outcome determine karein
        if violations:
            outcome = CheckOutcome.VIOLATION
        elif attachments:
            outcome = CheckOutcome.NEEDS_ATTACHMENT
        else:
            outcome = CheckOutcome.OK

        balance_after = available - working_days if outcome == CheckOutcome.OK else available

        return PolicyCheckResult(
            outcome=outcome,
            working_days=working_days,
            balance_after=balance_after,
            violations=violations,
            required_attachments=attachments
        )