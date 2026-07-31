"""Contract tests for the standalone SCHISM cold-hotstart generator."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from netCDF4 import Dataset


_REPO_ROOT = Path(__file__).resolve().parents[4]
_TOOL = _REPO_ROOT / "tools" / "make_cold_start_hotstart.py"
_SPEC = importlib.util.spec_from_file_location("make_cold_start_hotstart", _TOOL)
assert _SPEC is not None and _SPEC.loader is not None
hotstart = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hotstart)

_SIZES = {
    "node": 4,
    "elem": 2,
    "side": 5,
    "nVert": 3,
    "ntracers": 2,
    "one": 1,
}
_INTEGER_VARS = {
    "iths",
    "ifile",
    "nsteps_from_cold",
    "idry_e",
    "idry_s",
    "idry",
}


def _write_schema(
    path: Path,
    *,
    override_name: str | None = None,
    override_dims: tuple[str, ...] | None = None,
) -> None:
    """Write the required variable set, optionally corrupting one layout."""
    with Dataset(path, "w", format="NETCDF4_CLASSIC") as ds:
        for name, size in _SIZES.items():
            ds.createDimension(name, size)
        for name, expected_dims in hotstart._EXPECTED_DIMS.items():
            dims = override_dims if name == override_name else expected_dims
            dtype = "i4" if name in _INTEGER_VARS else "f8"
            ds.createVariable(name, dtype, dims)


def _wrong_dims(expected: tuple[str, ...]) -> tuple[str, ...]:
    if expected == ("one",):
        return ("node",)
    if len(expected) == 1:
        return ("one",)
    return tuple(reversed(expected))


def test_writer_matches_complete_dimension_contract(tmp_path: Path) -> None:
    output = tmp_path / "hotstart.nc"
    hotstart.write_hotstart(
        output,
        np_global=_SIZES["node"],
        ne_global=_SIZES["elem"],
        ns_global=_SIZES["side"],
        nvrt=_SIZES["nVert"],
        ntracers=_SIZES["ntracers"],
        temp=5.0,
        salt=32.0,
        block=2,
    )

    assert hotstart.verify(output, 4, 2, 5, 3, 2) == 0
    with Dataset(output) as ds:
        got = {name: ds.variables[name].dimensions for name in hotstart._REQUIRED}
    assert got == hotstart._EXPECTED_DIMS


@pytest.mark.parametrize("name", hotstart._REQUIRED)
def test_verify_rejects_wrong_dims_for_every_required_variable(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    name: str,
) -> None:
    path = tmp_path / f"wrong-{name}.nc"
    expected = hotstart._EXPECTED_DIMS[name]
    _write_schema(path, override_name=name, override_dims=_wrong_dims(expected))

    assert hotstart.verify(path, 4, 2, 5, 3, 2) == 1
    assert f"{name} dim order" in capsys.readouterr().out
