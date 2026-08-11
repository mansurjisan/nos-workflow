"""Tests for ``zCoordinates`` in the ``stations_nc`` product.

``ush/schism_combine_outputs.py`` lives outside the ``nos_workflow``
package, so it is loaded by path -- the same way
``nos_workflow.post.products.fields`` loads it to split combined
``schout_*.nc``.

The fixture data mirrors the real SCHISM station-output layout: each 3D
staout file (5-8) packs, per data line, ``nsta`` blocks of ``nver``
values for the variable itself followed by ``nsta`` more blocks of
``nver`` z-coordinates for the same stations -- the pre-op reference
(``nosofs.3.9/ush/pysh/schism_fields_station_redo.py``) reads that
second half out of ``staout_5`` and publishes it as ``zCoordinates``;
this is a straight port of that.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import List

import pytest

netCDF4 = pytest.importorskip("netCDF4")
import numpy as np  # noqa: E402

_COMBINE_SCRIPT = Path(__file__).resolve().parents[3] / "schism_combine_outputs.py"

NSTA = 4
NVER = 5
# Bottom -> surface sigma levels; station 3 shares station 1's water
# column (10 m), standing in for a nearest-node fallback like the real
# out-of-domain station -- SCHISM's station module has already resolved
# it to some column by the time staout_5 is written, so nothing here
# needs to know it is special.
DEPTHS = [10.0, 20.0, 5.0, 10.0]
SIGMA = np.linspace(-1.0, 0.0, NVER)
TIMES = [0.0, 3600.0]
ZETA = [
    [0.10, 0.05, -0.20, 0.05],
    [0.30, 0.15, -0.10, 0.05],
]  # [time][station]


def _load_combine_module():
    spec = importlib.util.spec_from_file_location(
        "schism_combine_outputs", _COMBINE_SCRIPT,
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sigma_z(depth: float, zeta: float) -> List[float]:
    """z = zeta + sigma * (depth + zeta): monotonic bottom->surface,
    top level equal to zeta -- the standard sigma-coordinate transform."""
    return [float(zeta + s * (depth + zeta)) for s in SIGMA]


def _write_2d_staout(path: Path, rows: List[List[float]]) -> None:
    lines = [
        " ".join([f"{t:.1f}"] + [f"{v:.6f}" for v in row])
        for t, row in zip(TIMES, rows)
    ]
    path.write_text("\n".join(lines) + "\n")


def _write_3d_staout(
    path: Path, var_by_station: List[List[List[float]]],
    z_by_station: List[List[List[float]]],
) -> None:
    """ops layout: odd lines are a header (only the token count matters
    here), even lines are ``time`` + nsta var-blocks + nsta z-blocks."""
    lines = []
    for it, t in enumerate(TIMES):
        lines.append(" ".join([f"{t:.1f}"] + ["0.0"] * (NSTA * 2 * NVER)))
        row = [f"{t:.1f}"]
        for s in range(NSTA):
            row += [f"{v:.6f}" for v in var_by_station[s][it]]
        for s in range(NSTA):
            row += [f"{v:.6f}" for v in z_by_station[s][it]]
        lines.append(" ".join(row))
    path.write_text("\n".join(lines) + "\n")


def _build_fixture(tmp_path: Path) -> None:
    z_by_station = [
        [_sigma_z(DEPTHS[s], ZETA[it][s]) for it in range(len(TIMES))]
        for s in range(NSTA)
    ]
    temp_by_station = [
        [[10.0 + s + 0.1 * k for k in range(NVER)] for _ in TIMES]
        for s in range(NSTA)
    ]
    salt_by_station = [
        [[30.0 + s for _ in range(NVER)] for _ in TIMES]
        for s in range(NSTA)
    ]
    zero_3d = [[[0.0] * NVER for _ in TIMES] for _ in range(NSTA)]

    _write_2d_staout(
        tmp_path / "staout_1", [[ZETA[it][s] for s in range(NSTA)] for it in range(len(TIMES))],
    )
    _write_2d_staout(tmp_path / "staout_3", [[0.0] * NSTA for _ in TIMES])
    _write_2d_staout(tmp_path / "staout_4", [[0.0] * NSTA for _ in TIMES])
    _write_3d_staout(tmp_path / "staout_5", temp_by_station, z_by_station)
    _write_3d_staout(tmp_path / "staout_6", salt_by_station, z_by_station)
    _write_3d_staout(tmp_path / "staout_7", zero_3d, z_by_station)
    _write_3d_staout(tmp_path / "staout_8", zero_3d, z_by_station)

    (tmp_path / "secofs.station.lat.lon").write_text(
        "\n".join(f"{i + 1} {-70.0 - i} {40.0 + i}" for i in range(NSTA)) + "\n"
    )


def _run_combine(tmp_path: Path):
    mod = _load_combine_module()
    ctl = {
        "PREFIXNOS": "secofs",
        "cyc": "00",
        "PDY": "20260810",
        "mode": "n",
        "timestart": "2026081000",
    }
    dims = {"n_stations": NSTA, "n_levels": NVER}
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        mod.process_station_files(ctl, dims)
    finally:
        os.chdir(cwd)
    return tmp_path / "secofs.t00z.20260810.stations.nowcast.nc"


def test_station_file_has_zcoordinates(tmp_path):
    _build_fixture(tmp_path)
    out_path = _run_combine(tmp_path)
    assert out_path.is_file()

    with netCDF4.Dataset(out_path) as ds:
        assert "zCoordinates" in ds.variables
        var = ds.variables["zCoordinates"]
        assert var.dimensions == ("time", "siglay", "station")
        assert var.shape == (len(TIMES), NVER, NSTA)

        assert var.long_name == "Z geopotential coordinates"
        assert var.location == "node"
        assert var.positive == "up"
        assert var.units == "meter"

        zc = var[:, :, :]
        assert np.isfinite(zc).all()

        # Bottom -> surface monotonic increase for every station/time,
        # including the nearest-node stand-in (station index 3).
        assert (np.diff(zc, axis=1) > 0).all()

        # Top layer equals the model's own zeta (float32 round-trip
        # tolerance only).
        zeta = ds.variables["zeta"][:, :]
        np.testing.assert_allclose(zc[:, -1, :], zeta, atol=1e-3)


def test_station_file_keeps_existing_variables_unchanged(tmp_path):
    """Adding zCoordinates must not disturb the existing CO-OPS schema."""
    _build_fixture(tmp_path)
    out_path = _run_combine(tmp_path)

    with netCDF4.Dataset(out_path) as ds:
        for name in ("zeta", "uwind_speed", "vwind_speed", "name_station"):
            assert name in ds.variables
        for name in ("temp", "salinity", "u", "v"):
            assert ds.variables[name].dimensions == ("time", "siglay", "station")
        assert len(ds.dimensions["station"]) == NSTA
        assert len(ds.dimensions["siglay"]) == NVER
