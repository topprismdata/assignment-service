# assignment-service

人店关系 Assignment Service（潜店雷达模块① WP06）。
规格来源：SRAF `01_WORLD_MODEL_SPEC` §39-41（ResponsibilityAssignment/基数/冲突）、
`02_DECISION_ONTOLOGY` §40（Invariant 不可被普通审批绕过）。
概念锚定 prism-ontology outlet-insight：`prism:sales/ServiceRelationship` ×
`prism:sales/SalesRep` × `prism:sales/CustomerAccount`。

## 核心语义

- **基数属 Responsibility Policy，不属数据库字段**（§41）：主访独家（max 1，
  INVARIANT 级），理货/KA/产品支持按策略共存；策略级违例可特批留痕
- **主访独家不变量不可绕过**：同期第二主访即使 `policy_override_approved=True`
  也拒绝（`InvariantViolation`，测试锁定）
- **替班**（SUBSTITUTE_COVERAGE）：必须引用被替主访、期限受 `substitute_max_days`
  约束、不计入主访基数——顶班语义合法，非双主访
- **双时态**：关闭=写 `valid_to`（历史保留）；恢复=新区间重开并引用原
  assignment（`restore_of:` 溯源），恢复时照常过冲突检测
- **全量审计**：每次变更带 decided_at / decided_by / source_approved_decision_id

## 用法

```python
from assignment_service import AssignmentService, Role

svc = AssignmentService("assignment.db")
svc.assign("outlet_e1", "repA", Role.PRIMARY_SELLING, "2026-01-01")
svc.close(asg.assignment_id, "2026-03-01", decided_by="mgr01")
svc.restore(asg.assignment_id, "2026-06-01", decided_by="mgr01")
```
