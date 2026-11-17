"""Database enum types (values exactly as specified in Ch. 6.3)."""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Enum as SAEnum


def pg_enum(enum_cls: type[StrEnum], name: str) -> SAEnum:
    return SAEnum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


class AssetStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    MAINTENANCE = "maintenance"


class RuleType(StrEnum):  # Table 6.5
    THRESHOLD = "threshold"
    RATE = "rate"
    DEVIATION = "deviation"
    COMPOSITE = "composite"
    PREDICTIVE = "predictive"


class Severity(StrEnum):  # Table 6.5
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    WARNING = "warning"
    INFO = "info"


SEVERITY_RANK = {Severity.CRITICAL: 5, Severity.MAJOR: 4, Severity.MINOR: 3, Severity.WARNING: 2, Severity.INFO: 1}


class AlertStatus(StrEnum):  # Figure 13.1
    TRIGGERED = "triggered"
    ACKNOWLEDGED = "acknowledged"
    INVESTIGATING = "investigating"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    CLOSED = "closed"


OPEN_ALERT_STATUSES = (
    AlertStatus.TRIGGERED, AlertStatus.ACKNOWLEDGED, AlertStatus.INVESTIGATING, AlertStatus.ESCALATED,
)


class AggregationType(StrEnum):  # Table 6.6
    AVG = "avg"
    MIN = "min"
    MAX = "max"
    SUM = "sum"
    COUNT = "count"
    TIME_WEIGHTED = "time_weighted"


class WorkOrderStatus(StrEnum):
    OPEN = "open"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class WorkOrderType(StrEnum):
    CORRECTIVE = "corrective"
    PREVENTIVE = "preventive"
    PREDICTIVE = "predictive"
    INSPECTION = "inspection"
    AUDIT_FINDING = "audit_finding"


class Priority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class ModelStage(StrEnum):  # Ch. 10.11 stage transitions
    NONE = "none"
    STAGING = "staging"
    PRODUCTION = "production"
    ARCHIVED = "archived"


class ReportStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ReportFormat(StrEnum):  # Ch. 1.4 item 10
    PDF = "pdf"
    EXCEL = "excel"
    HTML = "html"


class NotificationChannel(StrEnum):  # Ch. 13.6
    DASHBOARD = "dashboard"
    EMAIL = "email"
    SMS = "sms"
    WEBHOOK = "webhook"
