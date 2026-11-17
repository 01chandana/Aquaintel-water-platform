"""Tamper-evident audit trail (Ch. 17.7) and ``audit.events`` publication (Table 5.2).

``hash_n = SHA-256(hash_{n-1} || canonical_json(entry_n))``. Insertion takes a
transaction-scoped advisory lock so concurrent writers cannot fork the chain.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import client_ip_var, current_request_id
from app.core.events import AUDIT_EVENTS, envelope, get_event_bus
from app.core.logging import get_logger
from app.models.audit import AuditLog

log = get_logger(__name__)
GENESIS = "0" * 64
_LOCK_KEY = 7_301_017  # arbitrary constant for pg_advisory_xact_lock


def _canonical(entry: dict[str, Any]) -> str:
    return json.dumps(entry, sort_keys=True, separators=(",", ":"), default=str)


def compute_hash(prev_hash: str, entry: dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash + _canonical(entry)).encode()).hexdigest()


def _entry_fields(row: AuditLog | dict[str, Any]) -> dict[str, Any]:
    def get(key: str) -> Any:
        return row.get(key) if isinstance(row, dict) else getattr(row, key)

    created = get("created_at")
    return {
        "user_id": str(get("user_id")) if get("user_id") else None,
        "actor": get("actor"),
        "action": get("action"),
        "entity_type": get("entity_type"),
        "entity_id": get("entity_id"),
        "source_ip": str(get("source_ip")) if get("source_ip") else None,
        "details": get("details"),
        "created_at": created.isoformat() if isinstance(created, datetime) else created,
    }


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        action: str,
        entity_type: str,
        entity_id: Any = None,
        *,
        principal: Any = None,
        details: dict[str, Any] | None = None,
    ) -> AuditLog:
        await self.session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _LOCK_KEY})
        prev = (await self.session.execute(select(AuditLog.hash).order_by(AuditLog.id.desc()).limit(1))).scalar()
        prev_hash = prev or GENESIS
        now = datetime.now(UTC).replace(microsecond=0)
        fields = {
            "user_id": getattr(principal, "user_id", None),
            "actor": getattr(principal, "name", None) or "system",
            "action": action,
            "entity_type": entity_type,
            "entity_id": str(entity_id) if entity_id is not None else None,
            "source_ip": client_ip_var.get(),
            "details": json.loads(json.dumps(details, default=str)) if details else None,
            "created_at": now,
        }
        row = AuditLog(**fields, request_id=current_request_id(), prev_hash=prev_hash,
                       hash=compute_hash(prev_hash, _entry_fields(fields)))
        self.session.add(row)
        await self.session.flush()
        try:
            await get_event_bus().publish(AUDIT_EVENTS, envelope("audit.recorded", {
                "action": action, "entity_type": entity_type, "entity_id": fields["entity_id"],
                "actor": fields["actor"]}), key=entity_type)
        except Exception as exc:  # noqa: BLE001 - audit row is the source of truth
            log.warning("audit_event_publish_failed", error=str(exc))
        return row

    async def verify_chain(self, limit: int | None = None) -> dict[str, Any]:
        stmt = select(AuditLog).order_by(AuditLog.id.asc())
        if limit:
            stmt = stmt.limit(limit)
        prev_hash = GENESIS
        checked = 0
        for row in (await self.session.execute(stmt)).scalars():
            expected = compute_hash(prev_hash, _entry_fields(row))
            if row.prev_hash != prev_hash or row.hash != expected:
                return {"valid": False, "checked": checked, "broken_at_id": row.id,
                        "reason": "hash mismatch" if row.prev_hash == prev_hash else "chain link mismatch"}
            prev_hash = row.hash
            checked += 1
        return {"valid": True, "checked": checked, "head_hash": prev_hash}
