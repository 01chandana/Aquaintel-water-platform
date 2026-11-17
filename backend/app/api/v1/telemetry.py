"""Telemetry endpoints #31-37 (Table 7.4)."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, File, Query, UploadFile

from app.api.deps import DB, Principal, require_permission
from app.core.exceptions import ValidationError
from app.core.responses import ok
from app.models.telemetry import TelemetryTag
from app.repositories.telemetry_repository import TagRepository, TelemetryRepository
from app.schemas.telemetry import IngestRequest, TagCreate, TagOut, TelemetryPoint
from app.services.audit_service import AuditService
from app.services.telemetry_service import TelemetryService, parse_interval

router = APIRouter(prefix="/telemetry", tags=["Telemetry"])
READ = require_permission("telemetry:read")
MAX_RANGE = timedelta(days=400)


def _range(start: datetime | None, end: datetime | None, default: timedelta = timedelta(hours=24)) -> tuple[datetime, datetime]:
    end = end or datetime.now(UTC)
    start = start or end - default
    if start >= end:
        raise ValidationError("start must be before end")
    if end - start > MAX_RANGE:
        raise ValidationError("query range too large (max 400 days); use the aggregate endpoint")
    return start, end


@router.post("/ingest", summary="#31 Ingest telemetry batch",
             description="Integration endpoint (API key with `telemetry:ingest`). Up to 10 000 points per call; "
                         "points are validated and published to `telemetry.raw`.")
async def ingest(body: IngestRequest, db: DB, principal: Principal = require_permission("telemetry:ingest")) -> dict:
    return ok(await TelemetryService(db).ingest(body, principal))


@router.post("/ingest/csv", summary="Batch CSV upload (Ch. 1.4: CSV/Excel batch upload)",
             description="CSV columns: `tag,time,value[,quality]`.")
async def ingest_csv(db: DB, file: UploadFile = File(...),
                     principal: Principal = require_permission("telemetry:write")) -> dict:
    if not (file.filename or "").lower().endswith(".csv"):
        raise ValidationError("Only .csv files are accepted")
    text = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    points = [TelemetryPoint(tag=r["tag"], time=datetime.fromisoformat(r["time"]), value=float(r["value"]),
                             quality=int(r.get("quality") or 192)) for r in reader]
    if not points:
        raise ValidationError("CSV contains no rows")
    accepted = rejected = 0
    errors: list[dict[str, Any]] = []
    for i in range(0, len(points), 10_000):
        res = await TelemetryService(db).ingest(IngestRequest(source="csv", points=points[i:i + 10_000]), principal)
        accepted += res.accepted
        rejected += res.rejected
        errors += res.errors[:20]
    total = {"accepted": accepted, "rejected": rejected, "errors": errors}
    await AuditService(db).record("telemetry.csv_upload", "telemetry", file.filename, principal=principal,
                                  details={"rows": len(points), "accepted": total["accepted"]})
    await db.commit()
    return ok(total)


@router.get("/query", dependencies=[READ], summary="#32 Query time-series data")
async def query(db: DB, tag_ids: list[uuid.UUID] = Query(...), start: datetime | None = None,
                end: datetime | None = None, limit: int = Query(10_000, ge=1, le=100_000)) -> dict:
    start, end = _range(start, end)
    rows = await TelemetryRepository(db).query(tag_ids, start, end, limit)
    return ok(rows, {"count": len(rows), "start": start.isoformat(), "end": end.isoformat(), "truncated": len(rows) >= limit})


@router.get("/query/aggregate", dependencies=[READ], summary="#33 Get aggregated data",
            description="Uses the `telemetry_hourly` continuous aggregate for intervals >= 1h, `time_bucket` "
                        "otherwise; `gapfill=true` uses `time_bucket_gapfill` + `locf` (TimescaleDB).")
async def aggregate(db: DB, tag_ids: list[uuid.UUID] = Query(...), start: datetime | None = None,
                    end: datetime | None = None, interval: str = "1h", gapfill: bool = False) -> dict:
    start, end = _range(start, end, timedelta(days=7))
    step = parse_interval(interval)
    if (end - start) / step > 20_000:
        raise ValidationError("too many buckets; increase interval")
    rows = await TelemetryRepository(db).aggregate(tag_ids, start, end, step, gapfill)
    return ok(rows, {"interval": interval, "count": len(rows)})


@router.get("/tags", dependencies=[READ], summary="#34 List telemetry tags")
async def list_tags(db: DB, asset_id: uuid.UUID | None = None, parameter: str | None = None) -> dict:
    filters = []
    if asset_id:
        filters.append(TelemetryTag.asset_id == asset_id)
    if parameter:
        filters.append(TelemetryTag.parameter == parameter)
    return ok([TagOut.model_validate(t) for t in await TagRepository(db).all(*filters)])


@router.post("/tags", status_code=201, summary="#35 Register tag")
async def create_tag(body: TagCreate, db: DB, principal: Principal = require_permission("telemetry:write")) -> dict:
    repo = TagRepository(db)
    if (await repo.by_external_ids([body.external_id])):
        from app.core.exceptions import ConflictError

        raise ConflictError(f"Tag {body.external_id} already exists")
    tag = await repo.create(TelemetryTag(**body.model_dump()))
    await AuditService(db).record("telemetry.tag_created", "telemetry_tag", tag.id, principal=principal,
                                  details={"external_id": tag.external_id})
    await db.commit()
    return ok(TagOut.model_validate(tag))


@router.get("/tags/{tag_id}", dependencies=[READ], summary="#36 Get tag details")
async def get_tag(tag_id: uuid.UUID, db: DB) -> dict:
    tag = await TagRepository(db).get_or_404(tag_id, "Tag")
    latest = await TelemetryService(db).latest([tag.id])
    return ok({**TagOut.model_validate(tag).model_dump(mode="json"), "asset_name": tag.asset.name,
               "latest": latest[0] if latest else None})


@router.get("/latest", dependencies=[READ], summary="#37 Get all latest values",
            description="Served from the Redis write-through cache (30 s TTL), falling back to TimescaleDB.")
async def latest(db: DB, parameter: str | None = None, asset_id: uuid.UUID | None = None) -> dict:
    ids = None
    if parameter or asset_id:
        filters = []
        if parameter:
            filters.append(TelemetryTag.parameter == parameter)
        if asset_id:
            filters.append(TelemetryTag.asset_id == asset_id)
        ids = [t.id for t in await TagRepository(db).all(*filters)]
    return ok(await TelemetryService(db).latest(ids))
