"""Report & compliance endpoints #64-72 (Table 7.8)."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Query, Response

from app.api.deps import DB, Pagination, Principal, require_permission
from app.core.responses import ok, paginated
from app.models.report import Report
from app.repositories.report_repository import ReportRepository, ReportScheduleRepository
from app.schemas.report import ReportGenerate, ReportOut, ScheduleCreate, ScheduleOut
from app.services.audit_service import AuditService
from app.services.compliance_service import ComplianceService
from app.services.report_service import DEFAULT_SECTIONS, EXT, MIME, ReportService
from app.workers.dispatch import dispatch

router = APIRouter(tags=["Reports & Compliance"])
READ = require_permission("reports:read")
SCHEDULE = require_permission("reports:schedule")
COMPLIANCE = require_permission("compliance:read")


@router.get("/reports", dependencies=[READ], summary="#64 List reports")
async def list_reports(db: DB, p: Pagination, report_type: str | None = None, status: str | None = None) -> dict:
    f = []
    if report_type:
        f.append(Report.report_type == report_type)
    if status:
        f.append(Report.status == status)
    items, total = await ReportRepository(db).list(*f, page=p.page, per_page=p.per_page)
    return paginated([ReportOut.model_validate(r) for r in items], p.page, p.per_page, total)


@router.get("/reports/sections", dependencies=[READ], summary="Report Builder: available sections per report type")
async def sections() -> dict:
    return ok({"types": DEFAULT_SECTIONS, "all": sorted({s for v in DEFAULT_SECTIONS.values() for s in v})})


@router.post("/reports/generate", status_code=202, summary="#65 Generate ad-hoc report",
             description="Creates the report record and generates it asynchronously (Celery report worker).")
async def generate(body: ReportGenerate, db: DB, principal: Principal = require_permission("reports:generate")) -> dict:
    report = await ReportService(db).request(body, principal)
    task_id = await dispatch("generate_report", str(report.id))
    return ok({**ReportOut.model_validate(report).model_dump(mode="json"), "task_id": task_id})


@router.post("/reports/preview", dependencies=[require_permission("reports:generate")],
             summary="Report Builder: HTML preview without persisting")
async def preview(body: ReportGenerate, db: DB) -> Response:
    from app.models.enums import ReportFormat
    from app.services.report_service import _period, render

    start, end = _period(body.report_type, body.start, body.end)
    doc = await ReportService(db).build_document(body.report_type, body.name or "Preview", start, end, body.sections)
    return Response(render(doc, ReportFormat.HTML), media_type="text/html")


@router.get("/reports/schedules", dependencies=[SCHEDULE], summary="#67 List scheduled reports")
async def list_schedules(db: DB) -> dict:
    return ok([ScheduleOut.model_validate(s) for s in await ReportScheduleRepository(db).all()])


@router.post("/reports/schedules", status_code=201, summary="#68 Create report schedule")
async def create_schedule(body: ScheduleCreate, db: DB, principal: Principal = SCHEDULE) -> dict:
    return ok(ScheduleOut.model_validate(await ReportService(db).create_schedule(body, principal)))


@router.delete("/reports/schedules/{schedule_id}", status_code=204, summary="#69 Remove schedule")
async def delete_schedule(schedule_id: uuid.UUID, db: DB, principal: Principal = SCHEDULE) -> Response:
    repo = ReportScheduleRepository(db)
    s = await repo.get_or_404(schedule_id, "Schedule")
    await AuditService(db).record("report_schedule.delete", "report_schedule", s.id, principal=principal)
    await repo.delete(s)
    await db.commit()
    return Response(status_code=204)


@router.get("/reports/{report_id}", dependencies=[READ], summary="Get report status")
async def get_report(report_id: uuid.UUID, db: DB) -> dict:
    return ok(ReportOut.model_validate(await ReportRepository(db).get_or_404(report_id, "Report")))


@router.get("/reports/{report_id}/download", dependencies=[READ], summary="#66 Download report (PDF/Excel/HTML)")
async def download(report_id: uuid.UUID, db: DB) -> Response:
    report, data = await ReportService(db).download(report_id)
    # header-safe ASCII filename: user-supplied names may contain quotes, CR/LF or non-Latin-1 text
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", report.name).strip("._")[:80] or "report"
    fname = f"{stem}.{EXT[report.format]}"
    return Response(data, media_type=MIME[report.format], headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.get("/compliance/summary/daily", dependencies=[COMPLIANCE], summary="#70 Get daily compliance")
async def daily(db: DB, day: date | None = None) -> dict:
    return ok(await ComplianceService(db).daily(day))


@router.get("/compliance/summary/monthly", dependencies=[COMPLIANCE], summary="#71 Get monthly compliance")
async def monthly(db: DB, year: int | None = Query(None, ge=2000, le=2100), month: int | None = Query(None, ge=1, le=12)) -> dict:
    return ok(await ComplianceService(db).monthly(year, month))


@router.get("/compliance/exceedances", dependencies=[COMPLIANCE], summary="#72 List exceedances")
async def exceedances(db: DB, start: datetime | None = None, end: datetime | None = None,
                      parameter: str | None = None, limit: int = Query(500, ge=1, le=5000)) -> dict:
    end = end or datetime.now(UTC)
    start = start or end - timedelta(days=30)
    rows = await ComplianceService(db).exceedances(start, end, parameter, limit)
    return ok(rows, {"count": len(rows)})
