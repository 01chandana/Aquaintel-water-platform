"""Report generation in PDF, Excel and HTML (Ch. 1.4 item 10, Table 7.8, Use Cases 2 & 4).

A report is assembled as a format-neutral document model (sections of key/value pairs,
tables and text) and then rendered by one of three renderers. Files are stored in MinIO
(``aquaintel-reports`` bucket) with a local-filesystem fallback.
"""

from __future__ import annotations

import html
import io
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from croniter import croniter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.storage import get_store
from app.core.timeutil import to_plant
from app.models.alert import Alert
from app.models.asset import Asset
from app.models.enums import OPEN_ALERT_STATUSES, ReportFormat, ReportStatus, WorkOrderStatus
from app.models.kpi import KPIDefinition, KPIValue
from app.models.report import Report, ReportSchedule
from app.models.system import SystemConfig
from app.models.work_order import WorkOrder
from app.repositories.report_repository import ReportRepository, ReportScheduleRepository
from app.schemas.report import ReportGenerate, ScheduleCreate
from app.services.audit_service import AuditService
from app.services.compliance_service import ComplianceService
from app.services.kpi_engine import DEFAULT_CONFIG

log = get_logger(__name__)
SHIFT_HOURS = (6, 14, 22)  # shift changes; handover report runs 30 min before (Use Case 2)

DEFAULT_SECTIONS: dict[str, list[str]] = {
    "shift_handover": ["summary", "kpi_summary", "alerts", "equipment_status", "work_orders"],
    "compliance_daily": ["summary", "compliance", "exceedances"],
    "compliance_monthly": ["summary", "compliance", "exceedances", "kpi_compliance"],
    "kpi_summary": ["summary", "kpi_summary", "energy_carbon"],
    "alert_summary": ["summary", "alerts", "alert_stats"],
    "asset_performance": ["summary", "benchmark"],
    "custom": ["summary", "kpi_summary", "alerts"],
}
MIME = {ReportFormat.PDF: "application/pdf", ReportFormat.HTML: "text/html",
        ReportFormat.EXCEL: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
EXT = {ReportFormat.PDF: "pdf", ReportFormat.HTML: "html", ReportFormat.EXCEL: "xlsx"}


def _period(report_type: str, start: datetime | None, end: datetime | None) -> tuple[datetime, datetime]:
    now = datetime.now(UTC)
    if start and end:
        return start, end
    if report_type == "shift_handover":
        boundaries = [now.replace(hour=h, minute=0, second=0, microsecond=0) for h in SHIFT_HOURS]
        past = [b for b in boundaries if b <= now] or [boundaries[-1] - timedelta(days=1)]
        return past[-1], now
    if report_type == "compliance_monthly":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0), now
    return now - timedelta(days=1), now


class ReportService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.reports = ReportRepository(session)
        self.schedules = ReportScheduleRepository(session)

    # ---- request & lifecycle -------------------------------------------------------------
    async def request(self, data: ReportGenerate, principal: Principal | None, schedule_id: uuid.UUID | None = None) -> Report:
        start, end = _period(data.report_type, data.start, data.end)
        name = data.name or f"{data.report_type.replace('_', ' ').title()} {end:%Y-%m-%d %H:%M}"
        due = data.due_at
        if due is None and data.report_type.startswith("compliance"):
            due = end + timedelta(days=10 if data.report_type == "compliance_monthly" else 1)
        report = await self.reports.create(Report(
            name=name, report_type=data.report_type, format=data.format, status=ReportStatus.PENDING,
            parameters={"start": start.isoformat(), "end": end.isoformat(),
                        "site_id": str(data.site_id) if data.site_id else None,
                        "sections": data.sections or DEFAULT_SECTIONS[data.report_type]},
            generated_by=principal.user_id if principal else None, due_at=due, schedule_id=schedule_id))
        await AuditService(self.session).record("report.requested", "report", report.id, principal=principal,
                                                details={"type": data.report_type, "format": str(data.format)})
        await self.session.commit()
        return report

    async def generate(self, report_id: uuid.UUID) -> Report:
        report = await self.reports.get_or_404(report_id, "Report")
        report.status = ReportStatus.RUNNING
        await self.session.commit()
        try:
            params = report.parameters or {}
            start, end = datetime.fromisoformat(params["start"]), datetime.fromisoformat(params["end"])
            doc = await self.build_document(report.report_type, report.name, start, end, params.get("sections"))
            data = render(doc, ReportFormat(report.format))
            key = f"{report.report_type}/{report.created_at:%Y/%m}/{report.id}.{EXT[ReportFormat(report.format)]}"
            uri = await get_store().put(get_settings().minio_bucket_reports, key, data, MIME[ReportFormat(report.format)])
            report.file_key, report.file_uri, report.file_size = key, uri, len(data)
            report.status, report.completed_at = ReportStatus.COMPLETED, datetime.now(UTC)
            if report.report_type.startswith("compliance"):
                report.submitted_at = report.completed_at
        except Exception as exc:
            log.exception("report_failed", report_id=str(report.id))
            report.status, report.error = ReportStatus.FAILED, str(exc)[:1000]
        await self.session.commit()
        return report

    async def download(self, report_id: uuid.UUID) -> tuple[Report, bytes]:
        report = await self.reports.get_or_404(report_id, "Report")
        if report.status != ReportStatus.COMPLETED or not report.file_key:
            from app.core.exceptions import ConflictError

            raise ConflictError(f"Report is {report.status}")
        return report, await get_store().get(get_settings().minio_bucket_reports, report.file_key)

    # ---- schedules -------------------------------------------------------------------------
    async def create_schedule(self, data: ScheduleCreate, principal: Principal) -> ReportSchedule:
        nxt = croniter(data.cron, to_plant(datetime.now(UTC))).get_next(datetime)  # cron fields = plant clock
        sched = await self.schedules.create(ReportSchedule(**data.model_dump(), next_run_at=nxt,
                                                           created_by=principal.user_id))
        await AuditService(self.session).record("report_schedule.create", "report_schedule", sched.id,
                                                principal=principal, details={"cron": data.cron})
        await self.session.commit()
        return sched

    async def due_schedules(self) -> list[Report]:
        """Celery beat: enqueue reports for schedules whose ``next_run_at`` has passed."""
        now = datetime.now(UTC)
        created = []
        for s in await self.schedules.all(ReportSchedule.enabled.is_(True), ReportSchedule.next_run_at <= now):
            report = await self.request(ReportGenerate(report_type=s.report_type, format=s.format,
                                                       name=f"{s.name} {now:%Y-%m-%d %H:%M}"), None, s.id)
            s.last_run_at, s.next_run_at = now, croniter(s.cron, to_plant(now)).get_next(datetime)
            created.append(report)
        await self.session.commit()
        return created

    # ---- content -------------------------------------------------------------------------
    async def build_document(self, report_type: str, title: str, start: datetime, end: datetime,
                             sections: list[str] | None) -> dict[str, Any]:
        doc: dict[str, Any] = {"title": title, "subtitle": f"{start:%Y-%m-%d %H:%M} to {end:%Y-%m-%d %H:%M} UTC",
                               "generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "sections": []}
        builders = {
            "summary": self._summary, "kpi_summary": self._kpis, "alerts": self._alerts, "alert_stats": self._alert_stats,
            "equipment_status": self._equipment, "work_orders": self._work_orders, "compliance": self._compliance,
            "exceedances": self._exceedances, "kpi_compliance": self._kpi_compliance, "benchmark": self._benchmark,
            "energy_carbon": self._energy_carbon,
        }
        for name in sections or DEFAULT_SECTIONS.get(report_type, ["summary"]):
            if name in builders:
                doc["sections"].append(await builders[name](start, end))
        return doc

    async def _summary(self, start: datetime, end: datetime) -> dict[str, Any]:
        alerts = (await self.session.execute(select(func.count()).select_from(Alert).where(
            Alert.created_at >= start, Alert.created_at <= end))).scalar_one()
        crit = (await self.session.execute(select(func.count()).select_from(Alert).where(
            Alert.created_at >= start, Alert.created_at <= end, Alert.severity == "critical"))).scalar_one()
        open_alerts = (await self.session.execute(select(func.count()).select_from(Alert).where(
            Alert.status.in_(OPEN_ALERT_STATUSES)))).scalar_one()
        open_wo = (await self.session.execute(select(func.count()).select_from(WorkOrder).where(
            WorkOrder.status.notin_([WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED])))).scalar_one()
        return {"heading": "Summary", "kind": "kv", "items": [
            ("Period start", f"{start:%Y-%m-%d %H:%M}"), ("Period end", f"{end:%Y-%m-%d %H:%M}"),
            ("Alerts raised in period", alerts), ("Critical alerts in period", crit),
            ("Alerts still open", open_alerts), ("Open work orders", open_wo)]}

    async def _latest_kpis(self, end: datetime, category: str | None = None) -> list[tuple[KPIDefinition, KPIValue]]:
        sites = select(Asset.id).where(Asset.parent_id.is_(None))
        sub = (select(KPIValue.kpi_id, func.max(KPIValue.time).label("t")).where(
            KPIValue.time <= end, KPIValue.asset_id.in_(sites)).group_by(KPIValue.kpi_id).subquery())
        stmt = (select(KPIDefinition, KPIValue).join(KPIValue, KPIValue.kpi_id == KPIDefinition.id)
                .join(sub, (sub.c.kpi_id == KPIValue.kpi_id) & (sub.c.t == KPIValue.time))
                .where(KPIValue.asset_id.in_(sites)).order_by(KPIDefinition.number))
        if category:
            stmt = stmt.where(KPIDefinition.category == category)
        return [(kd, kv) for kd, kv in (await self.session.execute(stmt)).all()]

    async def _kpis(self, start: datetime, end: datetime) -> dict[str, Any]:
        rows = [[d.number or "-", d.name, f"{v.value:,.3f}", d.unit, v.status.upper(),
                 d.threshold_warning if d.threshold_warning is not None else "-",
                 d.threshold_critical if d.threshold_critical is not None else "-"]
                for d, v in await self._latest_kpis(end)]
        return {"heading": "KPI Summary", "kind": "table",
                "columns": ["#", "KPI", "Value", "Unit", "Status", "Warning", "Critical"], "rows": rows}

    async def _kpi_compliance(self, start: datetime, end: datetime) -> dict[str, Any]:
        rows = [[d.name, f"{v.value:,.3f}", d.unit, v.status.upper()] for d, v in await self._latest_kpis(end, "compliance")]
        return {"heading": "Compliance KPIs", "kind": "table", "columns": ["KPI", "Value", "Unit", "Status"], "rows": rows}

    async def _alerts(self, start: datetime, end: datetime) -> dict[str, Any]:
        alerts = (await self.session.execute(select(Alert).where(Alert.created_at >= start, Alert.created_at <= end)
                                             .order_by(Alert.created_at).limit(300))).unique().scalars().all()
        rows = [[f"{a.created_at:%m-%d %H:%M}", str(a.severity).upper(), a.title[:60],
                 a.asset.name if a.asset else "-", str(a.status), a.occurrence_count] for a in alerts]
        return {"heading": "Alert Timeline", "kind": "table",
                "columns": ["Time", "Severity", "Alert", "Asset", "Status", "Occurrences"], "rows": rows}

    async def _alert_stats(self, start: datetime, end: datetime) -> dict[str, Any]:
        from app.services.alert_service import AlertService

        a = await AlertService(self.session).analytics(start, end)
        return {"heading": "Alert Analytics", "kind": "kv", "items": [
            ("Total alerts", a["total"]), ("Mean time to acknowledge (min)", a["mean_time_to_acknowledge_min"] or "-"),
            ("Mean time to resolve (min)", a["mean_time_to_resolve_min"] or "-"),
            ("False positive rate (%)", a["false_positive_rate_pct"] or "-"), ("Suppressed by fatigue controls", a["suppressed"])]}

    async def _equipment(self, start: datetime, end: datetime) -> dict[str, Any]:
        assets = (await self.session.execute(select(Asset).where(Asset.parent_id.is_not(None)).order_by(Asset.path))).unique().scalars().all()
        rows = [[a.name, a.asset_type.category, str(a.status)] for a in assets if a.asset_type.category in ("pump", "valve", "motor", "tank")]
        return {"heading": "Equipment Status", "kind": "table", "columns": ["Asset", "Type", "Status"], "rows": rows}

    async def _work_orders(self, start: datetime, end: datetime) -> dict[str, Any]:
        wos = (await self.session.execute(select(WorkOrder).where(
            (WorkOrder.status.notin_([WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED])) | (WorkOrder.completed_at >= start))
            .order_by(WorkOrder.created_at.desc()).limit(100))).unique().scalars().all()
        rows = [[w.number, w.title[:50], w.asset.name, str(w.wo_type), str(w.priority), str(w.status)] for w in wos]
        return {"heading": "Pending & Recent Work Orders", "kind": "table",
                "columns": ["Number", "Title", "Asset", "Type", "Priority", "Status"], "rows": rows}

    async def _compliance(self, start: datetime, end: datetime) -> dict[str, Any]:
        s = await ComplianceService(self.session).summary(start, end)
        rows = [[p["display_name"], p["unit"], p["limit_min"] if p["limit_min"] is not None else "-",
                 p["limit_max"] if p["limit_max"] is not None else "-", p["samples"], p["exceedances"],
                 p["compliance_pct"], p["coverage_pct"], p["status"].upper()] for p in s["parameters"]]
        return {"heading": f"Regulatory Compliance (overall {s['overall_compliance_pct']}%)", "kind": "table",
                "columns": ["Parameter", "Unit", "Min", "Max", "Samples", "Exceedances", "Compliance %", "Coverage %", "Status"],
                "rows": rows}

    async def _exceedances(self, start: datetime, end: datetime) -> dict[str, Any]:
        rows = [[f"{e['time']:%m-%d %H:%M}", e["asset_name"], e["parameter"], round(e["value"], 3), e["unit"],
                 e["limit_min"] if e["limit_min"] is not None else "-", e["limit_max"] if e["limit_max"] is not None else "-",
                 e["regulation"]] for e in await ComplianceService(self.session).exceedances(start, end, limit=200)]
        return {"heading": "Exceedances", "kind": "table",
                "columns": ["Time", "Location", "Parameter", "Value", "Unit", "Min", "Max", "Regulation"], "rows": rows}

    async def _benchmark(self, start: datetime, end: datetime) -> dict[str, Any]:
        """Use Case 5: percentile ranking of comparable pumps on efficiency & health."""
        codes = ["PUMP_EFFICIENCY_INDEX", "EQUIPMENT_HEALTH_SCORE"]
        rows_q = (await self.session.execute(
            select(Asset.name, KPIDefinition.code, func.avg(KPIValue.value))
            .join(KPIValue, KPIValue.asset_id == Asset.id).join(KPIDefinition, KPIDefinition.id == KPIValue.kpi_id)
            .where(KPIDefinition.code.in_(codes), KPIValue.time >= start, KPIValue.time <= end, Asset.parent_id.is_not(None))
            .group_by(Asset.name, KPIDefinition.code))).all()
        table: dict[str, dict[str, float]] = {}
        for name, code, avg in rows_q:
            table.setdefault(name, {})[code] = float(avg)
        effs = sorted(v.get("PUMP_EFFICIENCY_INDEX", 0) for v in table.values())
        rows = []
        for name, v in sorted(table.items(), key=lambda kv: -kv[1].get("PUMP_EFFICIENCY_INDEX", 0)):
            e = v.get("PUMP_EFFICIENCY_INDEX")
            pct = round(sum(1 for x in effs if x <= (e or 0)) / len(effs) * 100) if effs else None
            rows.append([name, round(e, 1) if e else "-", round(v.get("EQUIPMENT_HEALTH_SCORE", 0), 1), pct,
                         "Investigate" if pct is not None and pct <= 25 else ("Best practice" if pct and pct >= 75 else "-")])
        return {"heading": "Asset Performance Benchmarking", "kind": "table",
                "columns": ["Pump", "Efficiency Index %", "Health Score", "Percentile", "Action"], "rows": rows}

    async def _energy_carbon(self, start: datetime, end: datetime) -> dict[str, Any]:
        """Use Cases 20 & 21: energy per site, the water-energy intensity, and Scope 2 CO2e.

        Energy is reconstructed from the daily KPIs (SEC kWh/m3 x production m3) so the section agrees with
        the KPI pages; emissions use the configured grid factor ``energy.grid_emission_factor_kg_per_kwh``.
        """
        cfg = (await self.session.execute(select(SystemConfig.value).where(
            SystemConfig.key == "energy.grid_emission_factor_kg_per_kwh"))).scalar_one_or_none()
        factor = float(cfg if cfg is not None else DEFAULT_CONFIG["energy.grid_emission_factor_kg_per_kwh"])
        rows_q = (await self.session.execute(
            select(Asset.name, KPIDefinition.code, func.avg(KPIValue.value), func.count())
            .join(KPIValue, KPIValue.asset_id == Asset.id).join(KPIDefinition, KPIDefinition.id == KPIValue.kpi_id)
            .where(KPIDefinition.code.in_(["SPECIFIC_ENERGY_CONSUMPTION", "PRODUCTION_VOLUME"]),
                   KPIValue.time >= start, KPIValue.time <= end, Asset.parent_id.is_(None))
            .group_by(Asset.name, KPIDefinition.code))).all()
        sites: dict[str, dict[str, tuple[float, int]]] = {}
        for name, code, avg, n in rows_q:
            sites.setdefault(name, {})[code] = (float(avg), int(n))
        hours = max((end - start).total_seconds() / 3600, 1.0)
        rows = []
        for name, v in sorted(sites.items()):
            sec = v.get("SPECIFIC_ENERGY_CONSUMPTION", (0.0, 0))[0]
            # PRODUCTION_VOLUME is a rolling 24 h total: average x (window / 24 h) = volume over the window
            volume = v.get("PRODUCTION_VOLUME", (0.0, 0))[0] * hours / 24
            kwh = sec * volume
            rows.append([name, f"{volume:,.0f}", f"{sec:.3f}", f"{kwh:,.0f}", f"{kwh * factor / 1000:,.2f}"])
        return {"heading": "Energy and Carbon (Scope 2)", "kind": "table",
                "columns": ["Site", "Water produced (m3)", "SEC (kWh/m3)", "Energy (kWh)", "CO2e (t)"],
                "rows": rows, "note": f"Grid emission factor {factor} kg CO2e/kWh (System > Configuration)."}


# ---- renderers ---------------------------------------------------------------------------
def render(doc: dict[str, Any], fmt: ReportFormat) -> bytes:
    return {ReportFormat.PDF: render_pdf, ReportFormat.EXCEL: render_excel, ReportFormat.HTML: render_html}[fmt](doc)


def render_html(doc: dict[str, Any]) -> bytes:
    e = html.escape
    parts = [f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{e(doc['title'])}</title><style>"
             "body{font-family:Inter,Arial,sans-serif;margin:32px;color:#0f172a}h1{color:#0b4f6c;margin-bottom:0}"
             ".sub{color:#64748b;margin-bottom:24px}table{border-collapse:collapse;width:100%;margin:8px 0 24px}"
             "th{background:#0b4f6c;color:#fff;text-align:left}th,td{padding:6px 8px;border-bottom:1px solid #e2e8f0;font-size:13px}"
             "@media print{body{margin:0}}</style></head><body>",
             f"<h1>{e(doc['title'])}</h1><div class='sub'>{e(doc['subtitle'])} &middot; generated {e(doc['generated_at'])}</div>"]
    for s in doc["sections"]:
        parts.append(f"<h2>{e(s['heading'])}</h2>")
        if s["kind"] == "kv":
            parts.append("<table>" + "".join(f"<tr><th>{e(str(k))}</th><td>{e(str(v))}</td></tr>" for k, v in s["items"]) + "</table>")
        elif s["kind"] == "table":
            head = "".join(f"<th>{e(str(c))}</th>" for c in s["columns"])
            body = "".join("<tr>" + "".join(f"<td>{e(str(c))}</td>" for c in r) + "</tr>" for r in s["rows"]) or \
                f"<tr><td colspan='{len(s['columns'])}'>No records</td></tr>"
            parts.append(f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>")
        if s.get("note"):
            parts.append(f"<p class='sub'>{e(s['note'])}</p>")
    parts.append("</body></html>")
    return "".join(parts).encode()


def _as_text(row: Any) -> None:
    """Keep user text as text (QA audit AQ-022: formula injection).

    openpyxl stores any string starting with ``=`` as a live formula, so an asset named
    ``=HYPERLINK("http://evil", "x")`` would execute when the export is opened. Report cells never hold
    formulas, so every formula-typed cell is downgraded to a plain string.
    """
    for cell in row:
        if cell.data_type == "f":
            cell.data_type = "s"


def render_excel(doc: dict[str, Any]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "Overview"
    ws.append([doc["title"]])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([doc["subtitle"]])
    header_fill = PatternFill("solid", fgColor="0B4F6C")
    for s in doc["sections"]:
        sheet = ws if s["kind"] == "kv" else wb.create_sheet(s["heading"][:31].replace("/", "-"))
        if s["kind"] == "kv":
            ws.append([])
            ws.append([s["heading"]])
            ws.cell(ws.max_row, 1).font = Font(bold=True)
            for k, v in s["items"]:
                ws.append([k, v])
                _as_text(ws[ws.max_row])
        else:
            sheet.append(s["columns"])
            for c in sheet[1]:
                c.font, c.fill = Font(bold=True, color="FFFFFF"), header_fill
            for r in s["rows"]:
                sheet.append(list(r))
                _as_text(sheet[sheet.max_row])
            if s.get("note"):
                sheet.append([])
                sheet.append([s["note"]])
            for col in sheet.columns:
                sheet.column_dimensions[col[0].column_letter].width = min(48, max(10, max(len(str(c.value or "")) for c in col) + 2))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def render_pdf(doc: dict[str, Any]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buf = io.BytesIO()
    pdf = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=14 * mm, rightMargin=14 * mm,
                            topMargin=14 * mm, bottomMargin=14 * mm, title=doc["title"])
    styles = getSampleStyleSheet()
    cell = styles["BodyText"].clone("cell", fontSize=8, leading=10)
    # reportlab Paragraphs parse XML-like markup: data must be escaped or a "<" in an asset name breaks the PDF
    x = xml_escape
    story: list[Any] = [Paragraph(x(doc["title"]), styles["Title"]),
                        Paragraph(x(f"{doc['subtitle']} - generated {doc['generated_at']}"), styles["Normal"]),
                        Spacer(1, 8)]
    brand = colors.HexColor("#0B4F6C")
    for s in doc["sections"]:
        story.append(Paragraph(x(s["heading"]), styles["Heading2"]))
        if s["kind"] == "kv":
            data = [[Paragraph(x(str(k)), cell), Paragraph(x(str(v)), cell)] for k, v in s["items"]]
            t = Table(data, colWidths=[80 * mm, 120 * mm])
            t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                                   ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EEF6F9"))]))
        else:
            rows = s["rows"] or [["No records"] + [""] * (len(s["columns"]) - 1)]
            data = [[Paragraph(f"<b>{x(str(c))}</b>", cell) for c in s["columns"]]] + \
                [[Paragraph(x(str(c)), cell) for c in r] for r in rows]
            t = Table(data, repeatRows=1)
            t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), brand), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                                   ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                                   ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")])]))
        story += [t, Spacer(1, 4 if s.get("note") else 10)]
        if s.get("note"):
            story += [Paragraph(x(s["note"]), cell), Spacer(1, 8)]
    pdf.build(story)
    return buf.getvalue()
