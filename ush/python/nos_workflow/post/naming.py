"""Canonical post-product filename builders.

One naming scheme for every system: ``{prefix}.t{cyc}z.{pdy}.<product>``.
The ``prefix`` token (PREFIXNOS) plus the per-system COMOUT tree carry
the OFS identity; the product vocabulary after the date stem is shared
across systems. Products must build COMOUT names through these helpers
rather than inline f-strings.
"""
from __future__ import annotations

_MODE_FLAGS = {"nowcast": "n", "forecast": "f"}


def product_stem(prefix: str, cyc: str, pdy: str) -> str:
    """``{prefix}.t{cyc}z.{pdy}`` -- the shared stem of every product."""
    return f"{prefix}.t{cyc}z.{pdy}"


def phase_mode_flag(phase: str) -> str:
    """Map nowcast/forecast to the n/f filename token."""
    try:
        return _MODE_FLAGS[phase]
    except KeyError:
        raise ValueError(f"unknown phase {phase!r}") from None


def stations_nc_name(prefix: str, cyc: str, pdy: str, phase: str) -> str:
    """Station-timeseries NetCDF: ``{stem}.stations.{phase}.nc``."""
    return f"{product_stem(prefix, cyc, pdy)}.stations.{phase}.nc"


def fields_stack_name(
    prefix: str,
    cyc: str,
    pdy: str,
    var: str,
    phase: str,
    hour_start: int,
    hour_end: int,
) -> str:
    """Per-variable field stack: ``{stem}.fields.{var}.{n|f}{HHH}_{HHH}.nc``.

    ``hour_start``/``hour_end`` are hours relative to the phase start
    (e.g. the first 6-hour nowcast stack of an hourly-output run is
    ``n001_006``).
    """
    mode = phase_mode_flag(phase)
    return (
        f"{product_stem(prefix, cyc, pdy)}.fields.{var}"
        f".{mode}{hour_start:03d}_{hour_end:03d}.nc"
    )


__all__ = [
    "fields_stack_name",
    "phase_mode_flag",
    "product_stem",
    "stations_nc_name",
]
