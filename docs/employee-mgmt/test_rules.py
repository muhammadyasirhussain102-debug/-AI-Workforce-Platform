from datetime import date, timedelta
from services.leave_service import LeavePolicyEngine, CheckOutcome
from services.policy_service import PolicyChunker, PolicySearchEngine


def test_rule_1_deterministic_working_days():
    # 2026-04-06 (Monday) to 2026-04-10 (Friday) = 5 working days
    start = date(2026, 4, 6)
    end = date(2026, 4, 10)
    days = LeavePolicyEngine.calculate_working_days(
        start=start,
        end=end,
        holidays=set(),
        weekend_days={5, 6},
        half_day=False
    )
    assert days == 5.0


def test_rule_1_probation_violation():
    rules = {
        "allowed_during_probation": False,
        "min_notice_days": 1
    }
    res = LeavePolicyEngine.evaluate_request(
        start=date(2026, 4, 10),
        end=date(2026, 4, 11),
        half_day=False,
        rules=rules,
        current_balance=10.0,
        reserved_balance=0.0,
        is_probation=True,
        holidays=set(),
        today=date(2026, 4, 1)
    )
    assert res.outcome == CheckOutcome.VIOLATION
    assert any("Probation" in v for v in res.violations)


def test_rule_4_visibility_filter():
    emp_filter = PolicySearchEngine.build_secure_query(
        tenant_id="tenant-1",
        user_role="employee",
        search_term="leave"
    )
    assert "hr_only" not in emp_filter["allowed_visibilities"]

    hr_filter = PolicySearchEngine.build_secure_query(
        tenant_id="tenant-1",
        user_role="hr_admin",
        search_term="leave"
    )
    assert "hr_only" in hr_filter["allowed_visibilities"]