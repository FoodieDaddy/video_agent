"""审核决定的纯状态规则。

这里仅判断一次决定是否允许，不写记录、不批准资产，也不安排工作流恢复。
应用用例负责把违规原因映射为既有异常，并在规则通过后执行原来的写入。
"""

from __future__ import annotations

from enum import Enum


class DecisionViolation(Enum):
    INVALID_DECISION = "invalid_decision"
    ALREADY_DECIDED = "already_decided"


def review_decision_violation(current_status: str, requested_status: str) -> DecisionViolation | None:
    """按既有顺序检查结论和当前状态，返回首个违规原因。

    即使审核已经处理，非法结论也应先报告为输入错误；这一顺序属于现有
    应用错误契约。只有待审记录可以接受 approved 或 rejected 决定。
    """
    if requested_status not in {"approved", "rejected"}:
        return DecisionViolation.INVALID_DECISION
    if current_status != "pending":
        return DecisionViolation.ALREADY_DECIDED
    return None
