from __future__ import annotations

from app.models.report import RegulatoryLimit, Report, ReportSchedule
from app.repositories.base import BaseRepository


class ReportRepository(BaseRepository[Report]):
    model = Report
    default_order = (Report.created_at.desc(),)
    sortable = {"created_at": Report.created_at, "name": Report.name}


class ReportScheduleRepository(BaseRepository[ReportSchedule]):
    model = ReportSchedule
    default_order = (ReportSchedule.name.asc(),)


class RegulatoryLimitRepository(BaseRepository[RegulatoryLimit]):
    model = RegulatoryLimit
    default_order = (RegulatoryLimit.parameter.asc(),)
