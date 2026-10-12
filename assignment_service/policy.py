"""Responsibility Policy（SRAF 01 §41）：基数规则属策略层，不属数据库字段。

默认策略：
- PRIMARY_SELLING 独家：每店同时至多 1 条 active（§40 invariant 示例），
  且 INVARIANT 级——任何审批不可绕过
- 其余角色按 max_active 共存；PRIMARY_SELLING 与 MERCHANDISING 等可共存
- SUBSTITUTE_COVERAGE 不计入主访基数，但必须有 substitute_for 且期限有限
"""
from __future__ import annotations

from dataclasses import dataclass, field

from assignment_service.models import Role


@dataclass
class ResponsibilityPolicy:
    max_active: dict[Role, int] = field(default_factory=lambda: {
        Role.PRIMARY_SELLING: 1,
        Role.MERCHANDISING: 2,
        Role.KA_NEGOTIATION: 1,
        Role.PRODUCT_SUPPORT: 1,
    })
    # 独家责任角色：超基数 = invariant，不可特批
    exclusive_roles: set[Role] = field(default_factory=lambda: {Role.PRIMARY_SELLING})
    # 替班最长天数（0=不限）
    substitute_max_days: int = 90

    def max_for(self, role: Role) -> int:
        return self.max_active.get(role, 1)

    def is_invariant(self, role: Role) -> bool:
        return role in self.exclusive_roles
