"""Date arithmetic helpers (YYYYMMDDHH format)."""
from __future__ import annotations

from datetime import datetime, timedelta


_FMT = "%Y%m%d%H"


def ndate(hours: int, ref_date: str) -> str:
    """Shift ``ref_date`` (YYYYMMDDHH) by ``hours`` and return YYYYMMDDHH."""
    ref = datetime.strptime(ref_date, _FMT)
    shifted = ref + timedelta(hours=int(hours))
    return shifted.strftime(_FMT)


def nhour(date1: str, date2: str) -> int:
    """Return integer hours from ``date2`` to ``date1`` (both YYYYMMDDHH)."""
    d1 = datetime.strptime(date1, _FMT)
    d2 = datetime.strptime(date2, _FMT)
    return int((d1 - d2).total_seconds() // 3600)


def parse_date(date_str: str) -> datetime:
    """Parse YYYYMMDDHH to datetime."""
    return datetime.strptime(date_str, _FMT)


def format_date(dt: datetime) -> str:
    """Format datetime as YYYYMMDDHH."""
    return dt.strftime(_FMT)


__all__ = ["ndate", "nhour", "parse_date", "format_date"]
