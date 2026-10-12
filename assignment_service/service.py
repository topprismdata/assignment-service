"""Assignment Service 编排：冲突检测 → 生效区间管理 → 双时态恢复。

不变量（测试锁定）：
- A1 PRIMARY_SELLING 独家：同店同日窗口内至多 1 条 active；
  违例抛 InvariantViolation——authority 再大也不能绕过（SRAF 02 §40）
- A2 历史不删除：关闭=写 valid_to；恢复=新区间重开（可完整回放原有效关系）
- A3 替班必须有 substitute_for 且不超过 substitute_max_days
- A4 每次变更留 decided_at/decided_by/source_approved_decision_id
"""
from __future__ import annotations

import datetime
import json
import sqlite3
from pathlib import Path
from typing import Optional

from assignment_service.models import (
    AssignmentStatus,
    ConflictViolation,
    Role,
    ServiceRelationship,
    new_id,
    now_iso,
)
from assignment_service.policy import ResponsibilityPolicy

_SCHEMA = """
CREATE TABLE IF NOT EXISTS assignments (
  assignment_id TEXT PRIMARY KEY,
  outlet_entity_id TEXT NOT NULL,
  rep_id TEXT NOT NULL,
  role TEXT NOT NULL,
  valid_from TEXT, valid_to TEXT,
  status TEXT,
  doc JSON NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_assign_outlet ON assignments(outlet_entity_id);
CREATE INDEX IF NOT EXISTS ix_assign_rep ON assignments(rep_id);
"""


def _load(doc: str) -> ServiceRelationship:
    d = json.loads(doc)
    d["role"] = Role(d["role"])
    d["status"] = AssignmentStatus(d["status"])
    return ServiceRelationship(**d)


class InvariantViolation(Exception):
    """A1：独家责任不变量。不可被任何审批绕过（SRAF 02 §40）。"""

    def __init__(self, v: ConflictViolation):
        super().__init__(v.message)
        self.violation = v


class PolicyViolation(Exception):
    """非 invariant 级策略违例：可走特批通道（记录在案）。"""


def _overlap(a_from: str, a_to: str, b_from: str, b_to: str) -> bool:
    """闭开区间 [from, to) 相交判定；空 to = 无限。"""
    a_to_eff = a_to or "9999-12-31"
    b_to_eff = b_to or "9999-12-31"
    return a_from < b_to_eff and b_from < a_to_eff


class AssignmentService:
    def __init__(self, db_path: str | Path = "assignment.db",
                 policy: ResponsibilityPolicy | None = None):
        self.db = sqlite3.connect(str(db_path))
        self.db.executescript(_SCHEMA)
        self.policy = policy or ResponsibilityPolicy()

    # ---- 查询 ----
    def active_for_outlet(self, outlet_entity_id: str, role: Role | None = None,
                          on_date: str | None = None) -> list[ServiceRelationship]:
        day = on_date or datetime.date.today().isoformat()
        rows = self.db.execute(
            "SELECT doc FROM assignments WHERE outlet_entity_id=?", (outlet_entity_id,)
        ).fetchall()
        out = []
        for (doc,) in rows:
            a = _load(doc)
            if a.valid_from <= day and (not a.valid_to or day < a.valid_to):
                if role is None or a.role is role:
                    out.append(a)
        return out

    def history_for_outlet(self, outlet_entity_id: str) -> list[ServiceRelationship]:
        rows = self.db.execute(
            "SELECT doc FROM assignments WHERE outlet_entity_id=? ORDER BY valid_from",
            (outlet_entity_id,),
        ).fetchall()
        return [_load(r[0]) for r in rows]

    # ---- 核心：建立关系 ----
    def assign(
        self,
        outlet_entity_id: str,
        rep_id: str,
        role: Role,
        valid_from: str,
        valid_to: str = "",
        decided_by: str = "",
        source_approved_decision_id: str = "",
        substitute_for: str = "",
        policy_override_approved: bool = False,
    ) -> ServiceRelationship:
        # A3 替班前置校验
        if role is Role.SUBSTITUTE_COVERAGE:
            if not substitute_for:
                raise PolicyViolation("替班必须引用被替主访 assignment_id（A3）")
            orig = self._get(substitute_for)
            if orig is None or orig.role is not Role.PRIMARY_SELLING:
                raise PolicyViolation("substitute_for 必须指向 active 的主访关系")
            if valid_to:
                days = (datetime.date.fromisoformat(valid_to)
                        - datetime.date.fromisoformat(valid_from)).days
                if days > self.policy.substitute_max_days:
                    raise PolicyViolation(
                        f"替班 {days} 天超上限 {self.policy.substitute_max_days}（A3）")
            # 替班与被替主访同日并存是合法的（顶班语义），跳过主访基数检查

        # ---- 冲突检测：同店同角色 active 基数 ----
        overlapping = [
            a for a in self.active_for_outlet(outlet_entity_id, role, valid_from)
            if _overlap(valid_from, valid_to, a.valid_from, a.valid_to)
        ]
        if len(overlapping) >= self.policy.max_for(role):
            v = ConflictViolation(
                code="INVARIANT_EXCLUSIVE_PRIMARY" if self.policy.is_invariant(role)
                else "POLICY_MAX_ACTIVE",
                message=f"{role.value} 超基数：已有 {len(overlapping)} 条 active 区间相交",
                existing_assignment_id=overlapping[0].assignment_id,
                invariant=self.policy.is_invariant(role),
            )
            if v.invariant:
                # A1：不可审批绕过——即使 policy_override_approved=True
                raise InvariantViolation(v)
            if not policy_override_approved:
                raise PolicyViolation(v.message)
            # 特批通道：允许但留痕（A4）

        rel = ServiceRelationship(
            assignment_id=new_id("asg"),
            outlet_entity_id=outlet_entity_id,
            rep_id=rep_id,
            role=role,
            valid_from=valid_from,
            valid_to=valid_to,
            substitute_for=substitute_for,
            source_approved_decision_id=source_approved_decision_id,
            decided_by=decided_by,
        )
        self.db.execute(
            "INSERT INTO assignments VALUES (?,?,?,?,?,?,?,?)",
            (rel.assignment_id, rel.outlet_entity_id, rel.rep_id, rel.role.value,
             rel.valid_from, rel.valid_to, rel.status.value,
             json.dumps(rel.__dict__, ensure_ascii=False)),
        )
        self.db.commit()
        return rel

    # ---- 关闭与恢复（A2 双时态）----
    def close(self, assignment_id: str, valid_to: str, decided_by: str = "",
              reason: str = "") -> ServiceRelationship:
        rel = self._get(assignment_id)
        if rel is None:
            raise KeyError(assignment_id)
        rel.valid_to = valid_to
        rel.status = AssignmentStatus.CLOSED
        rel.decided_at = now_iso()
        rel.decided_by = decided_by
        if reason:
            rel.source_approved_decision_id = rel.source_approved_decision_id or reason
        self._update(rel)
        return rel

    def restore(self, assignment_id: str, valid_from: str, decided_by: str = "",
                source_approved_decision_id: str = "") -> ServiceRelationship:
        """恢复原有效关系：以新区间重开同 (outlet, rep, role) 组合，
        引用原 assignment（decided_at 链），不篡改旧区间（A2）。"""
        orig = self._get(assignment_id)
        if orig is None:
            raise KeyError(assignment_id)
        # 冲突检测照常（若该店已有新主访则恢复会被拒）
        return self.assign(
            outlet_entity_id=orig.outlet_entity_id,
            rep_id=orig.rep_id,
            role=orig.role,
            valid_from=valid_from,
            decided_by=decided_by,
            source_approved_decision_id=source_approved_decision_id
            or f"restore_of:{orig.assignment_id}",
        )

    # ---- 内部 ----
    def _get(self, assignment_id: str) -> Optional[ServiceRelationship]:
        row = self.db.execute(
            "SELECT doc FROM assignments WHERE assignment_id=?", (assignment_id,)
        ).fetchone()
        return _load(row[0]) if row else None

    def _update(self, rel: ServiceRelationship) -> None:
        self.db.execute(
            "UPDATE assignments SET valid_to=?, status=?, doc=? WHERE assignment_id=?",
            (rel.valid_to, rel.status.value, json.dumps(rel.__dict__, ensure_ascii=False),
             rel.assignment_id),
        )
        self.db.commit()

    def close_db(self) -> None:
        self.db.close()
