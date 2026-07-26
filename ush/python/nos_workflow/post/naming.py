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


def points_cwl_name(prefix: str, cyc: str, pdy: str, phase: str) -> str:
    """Ops-style station timeseries: ``{stem}.points.cwl.{phase}.nc``.

    Ops publishes one ``{prefix}.t{cyc}z.points.cwl.temp.salt.vel.nc``
    per cycle because it runs a single continuous simulation; our post
    runs the nowcast and forecast legs separately, so the canonical name
    carries the phase (and, as everywhere here, the date stem).
    """
    return f"{product_stem(prefix, cyc, pdy)}.points.cwl.{phase}.nc"


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


def field2d_stack_name(
    prefix: str,
    cyc: str,
    pdy: str,
    phase: str,
    hour_start: int,
    hour_end: int,
) -> str:
    """2D-slab stack: ``{stem}.field2d.{n|f}{HHH}_{HHH}.nc``.

    One file per input stack (ops names these ``field2d_*``), carrying
    the same phase-relative hour range as :func:`fields_stack_name`.
    """
    mode = phase_mode_flag(phase)
    return (
        f"{product_stem(prefix, cyc, pdy)}.field2d"
        f".{mode}{hour_start:03d}_{hour_end:03d}.nc"
    )


def disturbance_gpkg_name(
    prefix: str, cyc: str, pdy: str, phase: str, hour: int
) -> str:
    """Disturbance GeoPackage for one timestep:
    ``{stem}.disturbance.{n|f}NNN.gpkg``.

    ``hour`` follows the ops convention the nowCOAST feed expects:
    nowcast hours count *down* to ``n000`` at the cycle time, forecast
    hours count up from ``f001``.
    """
    mode = phase_mode_flag(phase)
    return (
        f"{product_stem(prefix, cyc, pdy)}.disturbance.{mode}{hour:03d}.gpkg"
    )


__all__ = [
    "disturbance_gpkg_name",
    "field2d_stack_name",
    "fields_stack_name",
    "phase_mode_flag",
    "points_cwl_name",
    "product_stem",
    "stations_nc_name",
]
