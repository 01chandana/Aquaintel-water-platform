"""Alert and rule schemas (Table 7.5, Listing 13.1)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.models.enums import AlertStatus, NotificationChannel, RuleType, Severity
from app.schemas.common import APIModel, ORMModel

Operator = Literal[
    "greater_than", "less_than", "greater_equal", "less_equal", "equals", "not_equals",
    "outside_range", "inside_range",
]


class ThresholdCondition(APIModel):
    operator: Operator
    value: float | None = None
    low: float | None = None
    high: float | None = None
    unit: str | None = Field(default=None, max_length=20)
    sustained_seconds: int = Field(0, ge=0, le=86_400)
    hysteresis: float = Field(0, ge=0)


class RateCondition(APIModel):
    window_seconds: int = Field(300, ge=10)
    max_change_pct: float | None = None  # e.g. pressure drop > 15% in 5 minutes
    max_change_abs: float | None = None
    direction: Literal["rise", "drop", "any"] = "any"


class DeviationCondition(APIModel):
    method: Literal["sigma", "ewma", "moving_average"] = "sigma"
    window_points: int = Field(96, ge=5, le=10_000)
    n_sigma: float = Field(3.0, gt=0)
    alpha: float = Field(0.3, gt=0, le=1)  # EWMA smoothing
    max_deviation_pct: float | None = None  # moving average


class CompositeTerm(APIModel):
    tag_id: uuid.UUID
    operator: Operator
    value: float | None = None
    low: float | None = None
    high: float | None = None


class CompositeCondition(APIModel):
    logic: Literal["and", "or"] = "and"
    terms: list[CompositeTerm] = Field(min_length=2)
    sustained_seconds: int = 0
    spatial: bool = False  # spatial correlation: count of anomalous siblings in same zone


class PredictiveCondition(APIModel):
    model: str = Field(max_length=60)  # pump_failure | anomaly_detection | ...
    metric: Literal["failure_probability", "anomaly_score", "remaining_useful_life", "value"] = "failure_probability"
    operator: Operator = "greater_than"
    value: float


CONDITION_MODELS: dict[RuleType, type[BaseModel]] = {
    RuleType.THRESHOLD: ThresholdCondition,
    RuleType.RATE: RateCondition,
    RuleType.DEVIATION: DeviationCondition,
    RuleType.COMPOSITE: CompositeCondition,
    RuleType.PREDICTIVE: PredictiveCondition,
}


class Escalation(APIModel):
    initial_delay_minutes: int | None = None
    escalation_intervals: list[int] | None = None
    max_escalation_level: Literal["operator", "supervisor", "manager"] = "manager"


class NotificationSpec(APIModel):
    channels: list[NotificationChannel] = [NotificationChannel.DASHBOARD]
    recipients: list[str] = ["operator_shift"]
    repeat_interval_minutes: int = 60


class Suppression(APIModel):
    suppress_if_asset_in_maintenance: bool = True
    suppress_during_silent_hours: bool = False
    auto_resolve_seconds: int = 300


class RuleBase(APIModel):
    name: str = Field(min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    asset_id: uuid.UUID | None = None
    tag_id: uuid.UUID | None = None
    rule_type: RuleType
    severity: Severity
    condition: dict[str, Any]
    escalation_minutes: int = Field(0, ge=0)
    enabled: bool = True
    escalation: Escalation | None = None
    notification: NotificationSpec | None = None
    suppression: Suppression | None = None
    cooldown_minutes: int = Field(15, ge=0, le=1440)

    @model_validator(mode="after")
    def _validate_condition(self) -> RuleBase:
        model = CONDITION_MODELS[self.rule_type]
        self.condition = model.model_validate(self.condition).model_dump(mode="json")
        if self.rule_type in (RuleType.THRESHOLD, RuleType.RATE, RuleType.DEVIATION) and not self.tag_id:
            raise ValueError(f"{self.rule_type} rules require tag_id")
        if self.rule_type == RuleType.THRESHOLD:
            c = self.condition
            if c["operator"] in ("outside_range", "inside_range"):
                if c.get("low") is None or c.get("high") is None:
                    raise ValueError("range operators need low and high")
            elif c.get("value") is None:
                raise ValueError("threshold operator needs value")
        return self


class RuleCreate(RuleBase):
    pass


class RuleUpdate(RuleBase):
    pass


class RuleOut(ORMModel):
    id: uuid.UUID
    name: str
    description: str | None
    asset_id: uuid.UUID | None
    tag_id: uuid.UUID | None
    rule_type: RuleType
    severity: Severity
    condition: dict[str, Any]
    escalation_minutes: int
    enabled: bool
    escalation: dict[str, Any] | None
    notification: dict[str, Any] | None
    suppression: dict[str, Any] | None
    cooldown_minutes: int
    kpi_code: str | None
    created_at: datetime


class RuleTestRequest(APIModel):
    """Evaluate a (possibly unsaved) rule against supplied values: Rule Manager 'test'."""

    rule: RuleCreate
    values: list[float] = Field(min_length=1, max_length=10_000)
    interval_seconds: int = 60


class RuleSimulateRequest(APIModel):
    """Replay historical telemetry through a saved rule: Rule Manager 'simulate'."""

    start: datetime
    end: datetime


class AlertEventOut(ORMModel):
    id: uuid.UUID
    from_status: str | None
    to_status: str
    actor: str | None
    note: str | None
    created_at: datetime


class AlertOut(ORMModel):
    id: uuid.UUID
    rule_id: uuid.UUID | None
    asset_id: uuid.UUID | None
    tag_id: uuid.UUID | None
    incident_id: uuid.UUID | None
    severity: Severity
    status: AlertStatus
    title: str
    message: str | None
    source: str
    trigger_value: float | None
    threshold_value: float | None
    fault_code: str | None
    escalation_level: int
    occurrence_count: int
    suppressed: bool
    is_false_positive: bool | None
    context: dict[str, Any] | None
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime
    asset_name: str | None = None


class AlertDetail(AlertOut):
    events: list[AlertEventOut] = []
    rule: RuleOut | None = None


class AlertAction(APIModel):
    note: str | None = Field(default=None, max_length=2000)


class ResolveAction(AlertAction):
    is_false_positive: bool = False
    close: bool = False


class BulkAction(APIModel):
    alert_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    action: Literal["acknowledge", "resolve"]
    note: str | None = Field(default=None, max_length=2000)
