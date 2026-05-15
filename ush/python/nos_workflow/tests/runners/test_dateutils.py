"""Unit tests for ``nos_workflow.runners.schism_ufs._dateutils``.

The shell function ``_schism_setup_paths`` (and ``_schism_find_hotstart``)
make repeated ``${NDATE}`` / ``${NHOUR}`` subprocess calls. The Python
port replaces those with pure :mod:`datetime` arithmetic; these tests
pin the semantics so a regression in the math (off-by-one on DST, sign
flip, leap year, etc.) surfaces immediately rather than at 3 AM on
WCOSS2 when an operator stares at a CFL crash.

All dates are UTC YYYYMMDDHH strings -- NCO production has no DST
awareness; everything is wall-clock UTC.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from nos_workflow.runners.schism_ufs._dateutils import (
    format_date,
    ndate,
    nhour,
    parse_date,
)


# ---------------------------------------------------------------------------
# ndate semantics
# ---------------------------------------------------------------------------


def test_ndate_zero_offset_is_identity():
    """``ndate(0, X)`` must return X unchanged -- catches accidental
    string-vs-int hour math."""
    assert ndate(0, "2026051200") == "2026051200"


def test_ndate_negative_offset_back_six_hours():
    """Going back 6h from midnight crosses a day boundary."""
    assert ndate(-6, "2026051000") == "2026050918"


def test_ndate_positive_offset_forward_two_days():
    """48-hour shift advances by two calendar days, hour preserved."""
    assert ndate(48, "2026051000") == "2026051200"


def test_ndate_positive_one_hour():
    """Smallest positive shift -- catches sign errors."""
    assert ndate(1, "2026051200") == "2026051201"


def test_ndate_negative_one_hour():
    """Smallest negative shift -- catches sign errors. Going back 1h from
    midnight crosses into the previous calendar day at 23:00."""
    assert ndate(-1, "2026051200") == "2026051123"


def test_ndate_crosses_month_boundary():
    """48h from Jan 31 should land on Feb 2 (not Feb 0 or Jan 33).
    Confirms ``timedelta`` properly normalizes calendar arithmetic."""
    assert ndate(48, "2026013100") == "2026020200"


def test_ndate_crosses_year_boundary():
    """48h from Dec 31 should land in the new year."""
    assert ndate(48, "2026123100") == "2027010200"


def test_ndate_leap_year():
    """2028 is a leap year -- Feb 28 + 24h should be Feb 29, not Mar 1."""
    assert ndate(24, "2028022800") == "2028022900"


def test_ndate_non_leap_year_century():
    """2100 is NOT a leap year (centennial rule) -- Feb 28 + 24h is Mar 1."""
    assert ndate(24, "2100022800") == "2100030100"


def test_ndate_accepts_int_offset():
    """Operators sometimes pass ``int(env_var)`` -- make sure that's fine
    (the function signature is typed as int). 3h before midnight is
    21:00 of the previous day."""
    assert ndate(int(-3), "2026051200") == "2026051121"


# ---------------------------------------------------------------------------
# nhour semantics
# ---------------------------------------------------------------------------


def test_nhour_zero_diff():
    """Same date -> 0 hours -- catches accidental absolute-value math."""
    assert nhour("2026051200", "2026051200") == 0


def test_nhour_positive_diff_six_hours():
    """date1 > date2 -> positive."""
    assert nhour("2026051000", "2026050918") == 6


def test_nhour_negative_diff_returns_negative():
    """date1 < date2 -> negative.  Catches accidental ``abs(...)``."""
    assert nhour("2026050918", "2026051000") == -6


def test_nhour_one_day_diff():
    """24h forward should yield 24, not 0 or 1."""
    assert nhour("2026051200", "2026051100") == 24


def test_nhour_crosses_month():
    """End-of-Jan vs start-of-Feb -- catches month-wrap bugs."""
    assert nhour("2026020100", "2026013122") == 2
    assert nhour("2026013122", "2026020100") == -2


def test_nhour_long_span():
    """Multi-day forecast horizon (LEN_FORECAST=120 hr)."""
    assert nhour("2026051700", "2026051200") == 120


def test_nhour_integer_truncation():
    """Both inputs are YYYYMMDDHH -- no minutes/seconds component to
    truncate; result must be an int, not a float."""
    result = nhour("2026051200", "2026051100")
    assert isinstance(result, int)
    assert not isinstance(result, bool)


# ---------------------------------------------------------------------------
# parse_date / format_date round trip
# ---------------------------------------------------------------------------


def test_parse_format_round_trip():
    """The pair must be lossless for canonical YYYYMMDDHH input."""
    s = "2026051200"
    assert format_date(parse_date(s)) == s


def test_parse_date_returns_datetime():
    dt = parse_date("2026051200")
    assert isinstance(dt, datetime)
    assert dt.year == 2026 and dt.month == 5 and dt.day == 12 and dt.hour == 0


def test_format_date_returns_string():
    s = format_date(datetime(2026, 5, 12, 0))
    assert s == "2026051200"


def test_parse_date_rejects_bad_format():
    """Helps catch operator typos (e.g., wrong separator) at the
    boundary rather than as silent garbage downstream."""
    with pytest.raises(ValueError):
        parse_date("2026-05-12-00")  # ISO-ish, not YYYYMMDDHH
    with pytest.raises(ValueError):
        parse_date("not-a-date")  # complete garbage
    with pytest.raises(ValueError):
        parse_date("2026131200")  # month=13 out of range


# ---------------------------------------------------------------------------
# ndate + nhour are inverses
# ---------------------------------------------------------------------------


def test_ndate_and_nhour_are_inverses():
    """``nhour(ndate(h, X), X) == h`` for any h, X -- algebraic invariant."""
    base = "2026051200"
    for hours in (-49, -24, -6, -1, 0, 1, 6, 24, 48, 72, 120):
        shifted = ndate(hours, base)
        assert nhour(shifted, base) == hours, (
            f"inverse failed for hours={hours}: "
            f"ndate({hours}, {base})={shifted}; "
            f"nhour({shifted}, {base})={nhour(shifted, base)}"
        )
