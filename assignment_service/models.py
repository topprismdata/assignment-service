"""SRAF 01 §39-41 / 02 §40 人店关系核心对象。

本体锚定（prism-ontology outlet-insight 0.1.0-rc4）：
- 关系主体: prism:sales/ServiceRelationship
- 资源:     prism:sales/SalesRep
- 客户对象: prism:sales/CustomerAccount

双时态：valid_from/valid_to = 业务有效时间；decided_at = 决策知识时间。
历史只关闭不删除；恢复 = 以新区间重开（可追溯原有效关系）。
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum


class Role(str, Enum):
    PRIMARY_SELLING = "PRIMARY_SELLING"      # 主访（独家责任，默认 max 1）
    MERCHANDISING = "MERCHANDISING"          # 理货
    KA_NEGOTIATION = "KA_NEGOTIATION"        # KA 谈判
    PRODUCT_SUPPORT = "PRODUCT_SUPPORT"      # 产品支持
    SUBSTITUTE_COVERAGE = "SUBSTITUTE_COVERAGE"  # 替班（临时顶班，引用被替主访）


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"        # valid_to 已关；历史保留
    SUSPENDED = "SUSPENDED"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


@dataclass
class ServiceRelationship:
    """一条人店服务关系（SRAF 01 §39 全结构）。"""

    assignment_id: str
    outlet_entity_id: str            # Account 层 entity（identity-service 的 survivor）
    rep_id: str                      # prism:sales/SalesRep
    role: Role
    valid_from: str                  # 业务生效日（YYYY-MM-DD）
    valid_to: str = ""               # 空=仍有效
    status: AssignmentStatus = AssignmentStatus.ACTIVE
    substitute_for: str = ""         # 替班引用的原主访 assignment_id
    source_approved_decision_id: str = ""   # 溯源：哪个批准产生了这条
    decided_at: str = field(default_factory=now_iso)
    decided_by: str = ""
    ontology_class: str = "prism:sales/ServiceRelationship"


@dataclass
class ConflictViolation:
    """§41 冲突/§40 不变量违例。invariant 级不可被任何审批绕过。"""

    code: str                 # INVARIANT_EXCLUSIVE_PRIMARY / POLICY_MAX_ACTIVE ...
    message: str
    existing_assignment_id: str = ""
    invariant: bool = False   # True=不可审批绕过；False=policy 级可特批通道
