"""Import every model so Alembic autogenerate and ``Base.metadata`` see the full schema."""

from app.models.alert import Alert, AlertEvent, AlertRule, Incident, Notification
from app.models.asset import Asset, AssetType, SparePart
from app.models.audit import AuditLog
from app.models.dashboard import Dashboard, DashboardWidget
from app.models.kpi import KPIDefinition, KPIValue
from app.models.ml_model import MLModel, Prediction
from app.models.report import RegulatoryLimit, Report, ReportSchedule
from app.models.system import Schedule, SystemConfig
from app.models.telemetry import TelemetryData, TelemetryTag
from app.models.user import ApiKey, Role, User
from app.models.work_order import WorkOrder

__all__ = [
    "Alert", "AlertEvent", "AlertRule", "ApiKey", "Asset", "AssetType", "AuditLog", "Dashboard",
    "DashboardWidget", "Incident", "KPIDefinition", "KPIValue", "MLModel", "Notification", "Prediction",
    "RegulatoryLimit", "Report", "ReportSchedule", "Role", "Schedule", "SparePart", "SystemConfig",
    "TelemetryData", "TelemetryTag", "User", "WorkOrder",
]
