"""Time utility helpers for consistent timezone handling."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional


def utc_now() -> datetime:
    """Return the current time in UTC as an aware datetime."""

    return datetime.now(timezone.utc)


def local_now() -> datetime:
    """Return the current local time as an aware datetime."""

    return utc_now().astimezone()


def local_today() -> date:
    """Return today's date in the local timezone."""

    return local_now().date()


def ensure_utc(dt: datetime) -> datetime:
    """Coerce a datetime into UTC, assuming naive values are already UTC."""

    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_local(dt: Optional[datetime]) -> Optional[datetime]:
    """Convert a datetime to the local timezone (None-safe)."""

    if dt is None:
        return None
    return ensure_utc(dt).astimezone()
