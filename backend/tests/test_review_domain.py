"""审核纯规则与旧应用错误契约：无需建库或启动服务。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.modules.reviews.domain.decisions import DecisionViolation, review_decision_violation


@pytest.mark.parametrize(
    ("current", "requested", "expected"),
    [
        ("pending", "approved", None),
        ("pending", "rejected", None),
        ("approved", "rejected", DecisionViolation.ALREADY_DECIDED),
        ("rejected", "approved", DecisionViolation.ALREADY_DECIDED),
        ("pending", "pending", DecisionViolation.INVALID_DECISION),
        # 原应用先验证请求结论，再看记录状态，不能把输入错误改成冲突。
        ("approved", "pending", DecisionViolation.INVALID_DECISION),
    ],
)
def test_review_decision_rules(current, requested, expected):
    assert review_decision_violation(current, requested) is expected


@pytest.mark.parametrize("requested", ["pending", "rejected"])
def test_application_preserves_error_mapping_before_any_write(requested):
    from app.modules.platform.exceptions import ConflictError, ValidationAppError
    from app.modules.reviews.application.service import decide

    db = Mock()
    review = SimpleNamespace(id="review_checked", status="approved")
    error_type = ValidationAppError if requested == "pending" else ConflictError
    with pytest.raises(error_type) as captured:
        decide(db, project=None, review=review, status=requested)

    error = captured.value
    if requested == "pending":
        assert error.message == "审核结论只能是 approved 或 rejected"
        assert error.details == {}
    else:
        assert error.message == "该审核已经处理"
        assert error.details == {"review_id": "review_checked", "status": "approved"}
    assert review.status == "approved"
    db.flush.assert_not_called()
