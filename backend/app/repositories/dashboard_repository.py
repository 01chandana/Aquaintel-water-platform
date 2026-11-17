from __future__ import annotations

from app.models.dashboard import Dashboard
from app.repositories.base import BaseRepository


class DashboardRepository(BaseRepository[Dashboard]):
    model = Dashboard
    default_order = (Dashboard.updated_at.desc(),)
