"""WP06 测试：基数策略/不变量/替班/双时态恢复/历史保全。"""
from __future__ import annotations

import pytest

from assignment_service.models import AssignmentStatus, Role
from assignment_service.policy import ResponsibilityPolicy
from assignment_service.service import (
    AssignmentService,
    InvariantViolation,
    PolicyViolation,
)

D1, D2, D3, D4 = "2026-01-01", "2026-03-01", "2026-06-01", "2026-12-31"
SUB_END = "2026-04-01"  # 替班 31 天 < 90 上限


@pytest.fixture()
def svc(tmp_path):
    s = AssignmentService(tmp_path / "a.db")
    yield s
    s.close_db()


def test_primary_exclusive_invariant_cannot_be_bypassed(svc):
    svc.assign("O1", "repA", Role.PRIMARY_SELLING, D1)
    # 同期第二主访 = invariant，即使带特批标记也拒绝（A1/SRAF 02 §40）
    with pytest.raises(InvariantViolation):
        svc.assign("O1", "repB", Role.PRIMARY_SELLING, D2, policy_override_approved=True)


def test_primary_sequential_intervals_allowed(svc):
    a = svc.assign("O1", "repA", Role.PRIMARY_SELLING, D1, valid_to=D2)
    svc.assign("O1", "repB", Role.PRIMARY_SELLING, D2)  # 前任已关，新区间合法
    assert len(svc.history_for_outlet("O1")) == 2


def test_non_primary_roles_coexist(svc):
    svc.assign("O1", "repA", Role.PRIMARY_SELLING, D1)
    svc.assign("O1", "repB", Role.MERCHANDISING, D1)   # 理货可与主访共存（§41）
    assert len(svc.active_for_outlet("O1", on_date=D2)) == 2


def test_policy_level_violation_has_override_channel(svc):
    svc.assign("O1", "mA", Role.MERCHANDISING, D1)
    svc.assign("O1", "mB", Role.MERCHANDISING, D1)
    with pytest.raises(PolicyViolation):
        svc.assign("O1", "mC", Role.MERCHANDISING, D1)  # 超 max 2，无特批
    rel = svc.assign("O1", "mC", Role.MERCHANDISING, D1, policy_override_approved=True)
    assert rel.assignment_id  # 特批通道放行（留痕）


def test_substitute_requires_primary_reference_and_window(svc):
    primary = svc.assign("O1", "repA", Role.PRIMARY_SELLING, D1)
    with pytest.raises(PolicyViolation):
        svc.assign("O1", "repB", Role.SUBSTITUTE_COVERAGE, D2, valid_to=SUB_END)  # 缺引用
    sub = svc.assign("O1", "repB", Role.SUBSTITUTE_COVERAGE, D2, valid_to=SUB_END,
                     substitute_for=primary.assignment_id)
    assert sub.substitute_for == primary.assignment_id
    with pytest.raises(PolicyViolation):
        svc.assign("O1", "repC", Role.SUBSTITUTE_COVERAGE, D2, valid_to="2027-01-01",
                   substitute_for=primary.assignment_id)  # 超时长上限


def test_substitute_allows_third_party_during_primary_absence(svc):
    primary = svc.assign("O1", "repA", Role.PRIMARY_SELLING, D1)
    svc.assign("O1", "repB", Role.SUBSTITUTE_COVERAGE, D2, valid_to=SUB_END,
               substitute_for=primary.assignment_id)
    # 替班期 ≠ 双主访：substitute 语义合法，主访基数不受影响
    assert len(svc.active_for_outlet("O1", Role.PRIMARY_SELLING, on_date=D2)) == 1


def test_bitemporal_restore_reopens_new_interval(svc):
    a = svc.assign("O1", "repA", Role.PRIMARY_SELLING, D1)
    svc.close(a.assignment_id, D2, decided_by="mgr01")
    # 期间他人接手
    b = svc.assign("O1", "repB", Role.PRIMARY_SELLING, D2)
    # 恢复原关系：新主访在即 → 冲突检测拦截
    with pytest.raises(InvariantViolation):
        svc.restore(a.assignment_id, D3, decided_by="mgr01")
    # 接手关系关闭后可恢复，且引用原 assignment
    svc.close(b.assignment_id, D3, decided_by="mgr01")
    c = svc.restore(a.assignment_id, D3, decided_by="mgr01")
    assert c.source_approved_decision_id.startswith("restore_of:")
    assert c.rep_id == "repA" and c.valid_from == D3


def test_history_never_lost_and_audit_fields_present(svc):
    a = svc.assign("O1", "repA", Role.PRIMARY_SELLING, D1, decided_by="mgr01",
                   source_approved_decision_id="dec-777")
    svc.close(a.assignment_id, D2, decided_by="mgr01")
    h = svc.history_for_outlet("O1")
    assert len(h) == 1  # 关闭不删除
    assert h[0].status is AssignmentStatus.CLOSED
    assert h[0].valid_to == D2 and h[0].decided_by == "mgr01"
    assert h[0].source_approved_decision_id == "dec-777"
