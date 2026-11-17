"""Plant-local time (spec Appendix C: ``AQUAINTEL_TZ``).

Everything is *stored* and *exchanged* in UTC (TIMESTAMPTZ, ISO-8601 with offset). Anything that
depends on the hour of day at the plant - tariff windows, shift changes, the diurnal demand curve,
silent hours, report schedules - is evaluated in the plant's time zone, so a 17:00-22:00 peak
tariff means 17:00-22:00 on the plant's clock whatever zone the server runs in.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

import pandas as pd

from app.core.config import get_settings


@lru_cache
def plant_tz() -> ZoneInfo:
    return ZoneInfo(get_settings().tz)


def to_plant(ts: datetime) -> datetime:
    """Aware datetime in plant-local time (naive input is treated as UTC)."""
    return (ts if ts.tzinfo else ts.replace(tzinfo=ZoneInfo("UTC"))).astimezone(plant_tz())


def local_hour(ts: datetime) -> int:
    return to_plant(ts).hour


def local_times(times: pd.Series) -> pd.Series:
    """A tz-aware (or UTC-naive) pandas datetime series converted to plant time."""
    return pd.to_datetime(times, utc=True).dt.tz_convert(plant_tz())


def local_hours(times: pd.Series) -> pd.Series:
    """Hour of day (0-23) in plant time."""
    return local_times(times).dt.hour
