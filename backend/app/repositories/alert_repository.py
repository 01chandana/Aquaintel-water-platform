from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import cast, select
from sqlalchemy.dialects.postgresql import JSONB

from app.models.alert import Alert, AlertRule, Incident, Notification
from app.models.enums import OPEN_ALERT_STATUSES
from app.repositories.base import BaseRepository


class AlertRuleRepository(BaseRepository[AlertRule]):
    model = AlertRule
    default_order = (AlertRule.created_at.desc(),)
    sortable = {"name": AlertRule.name, "severity": AlertRule.severity, "created_at": AlertRule.created_at}

    async def enabled_for_tag(self, tag_id: uuid.UUID) -> list[AlertRule]:
        return await self.all(AlertRule.tag_id == tag_id, AlertRule.enabled.is_(True))

    async def enabled_of_type(self, rule_type: str) -> list[AlertRule]:
        return await self.all(AlertRule.rule_type == rule_type, AlertRule.enabled.is_(True))

    async def find_duplicate(self, tag_id: uuid.UUID | str | None, rule_type: str, severity: str,
                             condition: dict[str, Any], exclude: uuid.UUID | None = None) -> AlertRule | None:
        """An enabled rule with the same tag, type, severity and condition (JSONB equality ignores key order)."""
        stmt = select(AlertRule).where(
            AlertRule.tag_id.is_(None) if tag_id is None else AlertRule.tag_id == uuid.UUID(str(tag_id)),
            AlertRule.rule_type == rule_type, AlertRule.severity == severity,
            AlertRule.condition == cast(condition, JSONB), AlertRule.enabled.is_(True))
        if exclude is not None:
            stmt = stmt.where(AlertRule.id != exclude)
        return (await self.session.execute(stmt.limit(1))).scalar_one_or_none()


class AlertRepository(BaseRepository[Alert]):
    model = Alert
    default_order = (Alert.created_at.desc(),)
    sortable = {"created_at": Alert.created_at, "severity": Alert.severity, "status": Alert.status,
                "updated_at": Alert.updated_at}

    async def open_for(self, rule_id: uuid.UUID | None, asset_id: uuid.UUID | None,
                       source: str | None = None) -> Alert | None:
        stmt = select(Alert).where(Alert.status.in_(OPEN_ALERT_STATUSES), Alert.asset_id == asset_id)
        stmt = stmt.where(Alert.rule_id == rule_id) if rule_id else stmt.where(Alert.rule_id.is_(None))
        if source:
            stmt = stmt.where(Alert.source == source)
        return (await self.session.execute(stmt.order_by(Alert.created_at.desc()).limit(1))).unique().scalar_one_or_none()

    async def open_on_assets(self, asset_ids: list[uuid.UUID], since: datetime) -> list[Alert]:
        return await self.all(Alert.asset_id.in_(asset_ids), Alert.status.in_(OPEN_ALERT_STATUSES),
                              Alert.created_at >= since)


class IncidentRepository(BaseRepository[Incident]):
    model = Incident
    default_order = (Incident.created_at.desc(),)


class NotificationRepository(BaseRepository[Notification]):
    model = Notification
    default_order = (Notification.created_at.desc(),)
