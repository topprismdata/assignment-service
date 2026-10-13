"""assignment-service: 人店关系 Assignment Service (WP06, SRAF 01 §39-41 / 02 §40)."""
from assignment_service.models import (
    AssignmentStatus, ConflictViolation, Role, ServiceRelationship,
)
from assignment_service.policy import ResponsibilityPolicy
from assignment_service.service import AssignmentService, InvariantViolation, PolicyViolation

__version__ = "0.2.0"

__all__ = [
    "AssignmentService", "AssignmentStatus", "ConflictViolation",
    "InvariantViolation", "PolicyViolation", "ResponsibilityPolicy", "Role",
    "ServiceRelationship", "__version__",
]
