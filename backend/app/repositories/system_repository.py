from __future__ import annotations

from app.models.system import Schedule, SystemConfig
from app.repositories.base import BaseRepository


class ScheduleRepository(BaseRepository[Schedule]):
    model = Schedule
    default_order = (Schedule.created_at.desc(),)


class SystemConfigRepository(BaseRepository[SystemConfig]):
    model = SystemConfig
    default_order = (SystemConfig.key.asc(),)
