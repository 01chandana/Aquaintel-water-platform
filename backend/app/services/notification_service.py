"""Multi-channel notification dispatch (Ch. 13.6) and escalation recipients (Table 13.1).

Channels: in-app dashboard (WebSocket via Redis pub/sub), email (SMTP), SMS (Twilio/AWS SNS
adapter; logged in development) and outbound webhook (Slack/Teams/PagerDuty). Every
attempt is persisted in ``notifications`` so alert analytics can report delivery.
"""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import REALTIME_CHANNEL, get_cache
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import notifications_sent_total
from app.core.resilience import BREAKERS, HTTP_TIMEOUT
from app.models.alert import Alert, AlertRule, Notification
from app.models.enums import NotificationChannel
from app.models.user import Role, User

log = get_logger(__name__)

ESCALATION_LEVEL_NAMES = {0: "operator", 1: "operator", 2: "supervisor", 3: "manager"}
# Recipient groups -> roles (operator shift, maintenance lead, supervisor, manager)
RECIPIENT_GROUPS: dict[str, list[str]] = {
    "operator_shift": ["operator"],
    "maintenance_lead": ["technician", "engineer"],
    "supervisor": ["engineer"],
    "manager": ["admin", "super_admin"],
    "quality_team": ["engineer", "data_scientist"],
}


async def broadcast(message_type: str, data: Any) -> None:
    """Push a real-time message to every dashboard WebSocket (Ch. 8.7)."""
    try:
        await get_cache().publish(REALTIME_CHANNEL, {"type": message_type, "data": data})
    except Exception as exc:  # noqa: BLE001
        log.warning("broadcast_failed", error=str(exc))


async def send_email(to: str, subject: str, body: str) -> bool:
    s = get_settings()
    host = s.smtp_host
    if not host:
        log.info("email_logged", to=to, subject=subject)  # development: no SMTP configured
        return True

    def _send() -> None:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = s.smtp_from, to, subject
        msg.set_content(body)
        with smtplib.SMTP(host, s.smtp_port, timeout=10) as smtp:
            smtp.starttls()
            if s.smtp_user and s.smtp_password:
                smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(msg)

    await asyncio.to_thread(BREAKERS["smtp"].call, _send)
    return True


async def send_sms(to: str, text: str) -> bool:
    provider = get_settings().sms_provider or "log"
    # Provider adapters (Twilio / AWS SNS) plug in here; credentials come from Vault/K8s secrets.
    log.info("sms_dispatched", provider=provider, to=to, chars=len(text))
    return True


async def send_webhook(url: str, payload: dict[str, Any]) -> bool:
    async def _post() -> None:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()

    from app.core.resilience import call_with_resilience

    await call_with_resilience("webhook", _post)
    return True


class NotificationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _recipients(self, groups: list[str], level: int) -> list[User]:
        roles: set[str] = set()
        for g in groups:
            roles.update(RECIPIENT_GROUPS.get(g, []))
        if level >= 2:
            roles.update(RECIPIENT_GROUPS["supervisor"])
        if level >= 3:
            roles.update(RECIPIENT_GROUPS["manager"])
        stmt = select(User).join(Role).where(Role.name.in_(roles), User.is_active.is_(True))
        return list((await self.session.execute(stmt)).unique().scalars().all())

    async def dispatch(self, alert: Alert, rule: AlertRule | None, level: int = 0,
                       skip_external: bool = False) -> list[Notification]:
        spec = (rule.notification if rule and rule.notification else None) or {
            "channels": ["dashboard", "email"] if alert.severity in ("critical", "major") else ["dashboard"],
            "recipients": ["operator_shift"],
        }
        channels = [NotificationChannel(c) for c in spec.get("channels", ["dashboard"])]
        if alert.severity == "critical" and NotificationChannel.SMS not in channels and level >= 1:
            channels.append(NotificationChannel.SMS)  # critical alerts escalate to SMS
        payload = {
            "alert_id": str(alert.id), "title": alert.title, "severity": str(alert.severity),
            "status": str(alert.status), "asset_id": str(alert.asset_id) if alert.asset_id else None,
            "escalation_level": level, "message": alert.message,
            "created_at": alert.created_at.isoformat() if alert.created_at else None,
        }
        records: list[Notification] = []
        users = await self._recipients(spec.get("recipients", ["operator_shift"]), level)
        role_label = ESCALATION_LEVEL_NAMES.get(level, "manager")
        for channel in channels:
            if channel == NotificationChannel.DASHBOARD:
                await broadcast("alert", payload)
                records.append(self._record(alert, channel, f"dashboard:{role_label}", "sent", level))
                continue
            if skip_external:
                records.append(self._record(alert, channel, role_label, "skipped", level, "suppressed"))
                continue
            if channel == NotificationChannel.WEBHOOK:
                url = get_settings().webhook_url
                if url:
                    records.append(await self._attempt(alert, channel, url, level, send_webhook(url, payload)))
                continue
            for user in users:
                if channel == NotificationChannel.EMAIL:
                    body = (f"[{str(alert.severity).upper()}] {alert.title}\n\n{alert.message or ''}\n\n"
                            f"Escalation level: {role_label}\nAlert: {alert.id}")
                    coro = send_email(user.email, f"AquaIntel alert: {alert.title}", body)
                    records.append(await self._attempt(alert, channel, user.email, level, coro))
                elif channel == NotificationChannel.SMS and user.phone:
                    coro = send_sms(user.phone, f"AquaIntel {alert.severity}: {alert.title}"[:160])
                    records.append(await self._attempt(alert, channel, user.phone, level, coro))
        self.session.add_all(records)
        await self.session.flush()
        return records

    async def _attempt(self, alert: Alert, channel: NotificationChannel, recipient: str, level: int,
                       coro: Any) -> Notification:
        try:
            await coro
            return self._record(alert, channel, recipient, "sent", level)
        except Exception as exc:  # noqa: BLE001 - one failing channel must not block others
            log.warning("notification_failed", channel=str(channel), error=str(exc))
            return self._record(alert, channel, recipient, "failed", level, str(exc)[:500])

    @staticmethod
    def _record(alert: Alert, channel: NotificationChannel, recipient: str, status: str, level: int,
                error: str | None = None) -> Notification:
        notifications_sent_total.labels(channel=str(channel), status=status).inc()
        return Notification(alert_id=alert.id, channel=channel, recipient=recipient, status=status,
                            escalation_level=level, error=error)
