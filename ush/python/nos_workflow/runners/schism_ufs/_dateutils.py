"""Date arithmetic helpers replacing NDATE / NHOUR / bc shell calls.

NDATE / NHOUR are NCO production utilities that ship with prod_util,
but they're just thin wrappers around date arithmetic. For Python
code paths in the migration, this module provides equivalents using
``datetime`` + ``timedelta`` -- no subprocess overhead, no shell
quoting traps.

Date string format throughout is ``YYYYMMDDHH`` (e.g., 2026051200).

Shell counterpart usage in ``ush/nos_run.sh``::

    $NDATE -6 $time_nowcastend   ->  ndate(-6, time_nowcastend)
    $NHOUR $date1 $date2         ->  nhour(date1, date2)

Test coverage in ``tests/runners/test_dateutils.py``.
"""
from __future__ import annotations

from datetime import datetime, timedelta


_FMT = "%Y%m%d%H"


def ndate(hours: int, ref_date: str) -> str:
    """Replicate ``${NDATE} <hours> <YYYYMMDDHH>``.

    Args:
        hours: Hour offset. Negative goes back in time, positive forward.
        ref_date: Reference date as YYYYMMDDHH string.

    Returns:
        Shifted date as YYYYMMDDHH string.

    Examples:
        >>> ndate(-6, "2026051000")
        '2026050918'
        >>> ndate(48, "2026051000")
        '2026051200'
    """
    ref = datetime.strptime(ref_date, _FMT)
    shifted = ref + timedelta(hours=int(hours))
    return shifted.strftime(_FMT)


def nhour(date1: str, date2: str) -> int:
    """Replicate ``${NHOUR} <date1> <date2>``.

    Args:
        date1: Later date as YYYYMMDDHH string.
        date2: Earlier date as YYYYMMDDHH string.

    Returns:
        Integer hours from date2 to date1 (``date1 - date2``, in hours).

    Examples:
        >>> nhour("2026051000", "2026050918")
        6
        >>> nhour("2026050918", "2026051000")
        -6
    """
    d1 = datetime.strptime(date1, _FMT)
    d2 = datetime.strptime(date2, _FMT)
    return int((d1 - d2).total_seconds() // 3600)


def parse_date(date_str: str) -> datetime:
    """Parse YYYYMMDDHH -> ``datetime``.

    Helper for callers that need direct ``datetime`` arithmetic
    (e.g., decimal days from base date, which the shell does via
    ``echo "scale=4;$DAY0+${NH_NOWCAST}/24.0" | bc``).
    """
    return datetime.strptime(date_str, _FMT)


def format_date(dt: datetime) -> str:
    """Format ``datetime`` -> YYYYMMDDHH. Inverse of :func:`parse_date`."""
    return dt.strftime(_FMT)


__all__ = ["ndate", "nhour", "parse_date", "format_date"]
