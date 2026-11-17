"""Alert-rule management (Ch. 13.2, endpoints #44-#47).

Keeps the alerts router thin and enforces the rules a hand-written rule set needs:
* the tag a rule watches must exist (clear 422 instead of a foreign-key failure),
* an identical enabled rule may not be created twice: two copies would raise two alerts for every
  breach (QA audit AQ-016). "Identical" = same tag, type, severity and condition.
Every change invalidates the rules engine's per-tag cache and is written to the audit log.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.exceptions import ConflictError, ValidationError
from app.models.alert import AlertRule
from app.repositories.alert_repository import AlertRuleRepository
from app.repositories.telemetry_repository import TagRepository
from app.schemas.alert import RuleCreate, RuleUpdate
from app.services.audit_service import AuditService
from app.services.telemetry_service import invalidate_rule_cache


class RuleService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.rules = AlertRuleRepository(session)

    async def _check(self, data: dict[str, Any], exclude: uuid.UUID | None = None) -> None:
        tag_id = data.get("tag_id")
        if tag_id and await TagRepository(self.session).get(uuid.UUID(str(tag_id))) is None:
            raise ValidationError("Rule references an unknown telemetry tag",
                                  [{"field": "tag_id", "message": "tag does not exist"}])
        if data.get("enabled", True):
            twin = await self.rules.find_duplicate(tag_id, data["rule_type"], data["severity"], data["condition"],
                                                   exclude=exclude)
            if twin is not None:
                raise ConflictError(f"An identical enabled rule already exists: '{twin.name}'",
                                    [{"field": "condition", "rule_id": str(twin.id)}])

    async def create(self, body: RuleCreate, principal: Principal) -> AlertRule:
        data = body.model_dump(mode="json")
        await self._check(data)
        rule = await self.rules.create(AlertRule(**data, created_by=principal.user_id))
        await invalidate_rule_cache(rule.tag_id)
        await AuditService(self.session).record("alert_rule.create", "alert_rule", rule.id, principal=principal,
                                                details={"name": rule.name, "type": str(rule.rule_type)})
        await self.session.commit()
        return rule

    async def update(self, rule_id: uuid.UUID, body: RuleUpdate, principal: Principal) -> AlertRule:
        rule = await self.rules.get_or_404(rule_id, "Rule")
        data = body.model_dump(mode="json")
        await self._check({"enabled": rule.enabled, **data}, exclude=rule.id)
        old_tag = rule.tag_id
        for k, v in data.items():
            setattr(rule, k, v)
        await invalidate_rule_cache(old_tag)
        await invalidate_rule_cache(rule.tag_id)
        await AuditService(self.session).record("alert_rule.update", "alert_rule", rule.id, principal=principal)
        await self.session.commit()
        return rule

    async def toggle(self, rule_id: uuid.UUID, principal: Principal) -> AlertRule:
        rule = await self.rules.get_or_404(rule_id, "Rule")
        if not rule.enabled:  # re-enabling must not create a duplicate pair either
            await self._check({"tag_id": rule.tag_id, "rule_type": rule.rule_type, "severity": rule.severity,
                               "condition": rule.condition, "enabled": True}, exclude=rule.id)
        rule.enabled = not rule.enabled
        await invalidate_rule_cache(rule.tag_id)
        await AuditService(self.session).record("alert_rule.toggle", "alert_rule", rule.id, principal=principal,
                                                details={"enabled": rule.enabled})
        await self.session.commit()
        return rule

    async def delete(self, rule_id: uuid.UUID, principal: Principal) -> None:
        rule = await self.rules.get_or_404(rule_id, "Rule")
        await invalidate_rule_cache(rule.tag_id)
        await AuditService(self.session).record("alert_rule.delete", "alert_rule", rule.id, principal=principal,
                                                details={"name": rule.name})
        await self.rules.delete(rule)
        await self.session.commit()
