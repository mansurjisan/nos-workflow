"""Tests for the stations_mllw product, its fix table, and the generator.

Fixtures reproduce the two traps the real files carry: a ``station.in``
whose first column restarts per group (so it cannot be used as a station
key), and a control file that also lists current stations at depth != 0
under the same four-character codes.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from nos_workflow.post.base import ProductContext
from nos_workflow.post.naming import stations_mllw_name
from nos_workflow.post.products import stations_mllw
from nos_workflow.post.registry import get_product
from nos_workflow.stages.post import _ordered_products
from nos_workflow.tools import build_mllw_table


def _have(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


needs_netcdf4 = pytest.mark.skipif(
    not _have("netCDF4"), reason="netCDF4 not installed"
)

# Column 1 restarts at 1 on the fifth row, exactly as the real file does.
STATION_IN = """\
1 1 1 1 1 1 1 1 0 !flags
6
1 -81.808100 24.550800 0.000000 !Key_West(8724580): NOAA elev gauges
2 -82.629439 27.759567 0.000000 !St_Petersburg(8726520)
3 -80.900000 32.000000 0.000000 !Nowhere(9999999)
4 -76.083333 37.033333 0.000000 !CBBT_Chesapeake_Channel(8638901)
1 -82.555000 27.788400 -5.910000 !cg6g
2 -82.522000 27.786000 -4.910000 !buog
"""

CTL = """\
% MLLW Datum Factor to apply to model water levels
ST='Key_West(8724580)'   'keyw'  24.550800 -81.808100  0.400   1 1 1  1 1 0  1 1 0  1
ST='St_Petersburg(8726520)' 'stpe' 27.759567 -82.629439 0.481   1 1 1  1 1 0  1 1 0  1
ST='CBBT_Chesapeake_Channel(8638901)' 'cbbt' 37.033333 -76.083333 1.150  1 1 1  1 1 0  1 1 0  1
%ST='Commented_Out(8888888)' 'comm' 30.0 -80.0 0.500  1 1 1  1 1 0  1 1 0  1
ST='Cut G Channel Buoy 6G' 'cg6g'  27.788400 -82.555000  0.380   1 1 1  1 1 0  1 1 0  1
ST='Buoy G'                'buog'  27.786000 -82.522000  0.380   1 1 1  1 1 0  1 1 0  1
"""


@pytest.fixture()
def files(tmp_path: Path):
    sta = tmp_path / "station.in"
    sta.write_text(STATION_IN)
    ctl = tmp_path / "plot_timeseries_wl.ctl"
    ctl.write_text(CTL)
    out = tmp_path / "test.mllw_datum.csv"
    assert build_mllw_table.main(
        ["--ctl", str(ctl), "--station-in", str(sta), "--out", str(out)]
    ) == 0
    return sta, ctl, out


# --------------------------------------------------------------------------
# table generation
# --------------------------------------------------------------------------

def test_commented_ctl_entries_are_not_active(files):
    _, ctl, _ = files
    entries = build_mllw_table.read_ctl(ctl)
    assert [e["code"] for e in entries] == [
        "keyw", "stpe", "cbbt", "cg6g", "buog"
    ]


def test_current_stations_get_no_water_level_factor(files):
    """cg6g/buog sit at depth != 0; a WL datum must not be applied to them."""
    _, _, table = files
    rows = stations_mllw._read_factors(table)
    assert {r["coops_code"] for r in rows} == {"keyw", "stpe", "cbbt"}


def test_table_keys_on_row_order_not_the_restarting_column(files):
    """cg6g is column-1 value 1 but row 5; keying on column 1 would clash."""
    _, _, table = files
    rows = stations_mllw._read_factors(table)
    assert [r["station_row"] for r in rows] == [1, 2, 4]
    assert [r["mllw_factor"] for r in rows] == [0.400, 0.481, 1.150]


def test_station_with_no_ctl_entry_is_reported_and_omitted(files):
    """Row 3 has no factor and must simply be absent, not defaulted to 0."""
    _, _, table = files
    rows = stations_mllw._read_factors(table)
    assert 3 not in {r["station_row"] for r in rows}


def test_gauge_id_falls_back_to_the_station_list(tmp_path):
    """A ctl label may omit the id (``ST='Windmill'``) where station.in has it."""
    sta = tmp_path / "station.in"
    sta.write_text(
        "1 1 1 !flags\n1\n1 -76.083333 37.033333 0.0 !Windmill Point(8636580)\n"
    )
    ctl = tmp_path / "wl.ctl"
    ctl.write_text(
        "ST='Windmill'  'wmpt'  37.033333 -76.083333  0.950  1 1 1  1 1 0  1 1 0  1\n"
    )
    out = tmp_path / "t.csv"
    assert build_mllw_table.main(
        ["--ctl", str(ctl), "--station-in", str(sta), "--out", str(out)]
    ) == 0
    assert stations_mllw._read_factors(out)[0]["gauge_id"] == "8636580"


def test_hand_annotations_are_stripped_from_the_emitted_label(tmp_path):
    """'#' must not reach the CSV: it is that file's own comment character."""
    sta = tmp_path / "station.in"
    sta.write_text(
        "1 1 1 !flags\n2\n"
        "1 -79.9 32.78 0.0 !Charleston(8665530) # machuan changed\n"
        "2 -80.9 32.0 0.0 !Beaufort(8656483)  !! machuan revised\n"
    )
    ctl = tmp_path / "wl.ctl"
    ctl.write_text(
        "ST='Charleston(8665530)' 'char' 32.780 -79.900 1.196  1 1 1  1 1 0  1 1 0  1\n"
        "ST='Beaufort(8656483)'   'beau' 32.000 -80.900 0.877  1 1 1  1 1 0  1 1 0  1\n"
    )
    out = tmp_path / "t.csv"
    assert build_mllw_table.main(
        ["--ctl", str(ctl), "--station-in", str(sta), "--out", str(out)]
    ) == 0
    labels = [r["station_label"] for r in stations_mllw._read_factors(out)]
    assert labels == ["Charleston(8665530)", "Beaufort(8656483)"]
    assert "#" not in out.read_text().split("station_row,")[1]


def test_generator_rejects_a_declared_count_that_does_not_match(tmp_path):
    bad = tmp_path / "station.in"
    bad.write_text("1 1 1 !flags\n9\n1 -80.0 30.0 0.0 !One(1111111)\n")
    with pytest.raises(ValueError, match="declares 9"):
        build_mllw_table.read_station_in(bad)


def test_coops_cross_check_flags_a_gauge_id_disagreement(files, tmp_path):
    _, _, table = files
    log = tmp_path / "obs.log"
    log.write_text(
        'StationNames 8724580 : keyw : "Key_West(8724580)"\n'
        'StationNames 9999999 : stpe : "Somewhere Else"\n'
    )
    rows = [
        dict(coops_code=r["coops_code"], gauge_id=r["gauge_id"])
        for r in stations_mllw._read_factors(table)
    ]
    problems = build_mllw_table.verify_against_coops(rows, log)
    assert any("stpe" in p and "9999999" in p for p in problems)
    assert any("cbbt" in p and "absent" in p for p in problems)


def test_tie_break_prefers_the_gauge_id_match(tmp_path):
    """Two entries near one station: only the gauge's own factor is kept."""
    mapped = [
        dict(station_row=9, coops_code="ebcw", mllw_factor=0.451,
             sep_km=0.74, evidence="coord", gauge_id="", station_label="East_Bay"),
        dict(station_row=9, coops_code="estb", mllw_factor=0.541,
             sep_km=0.00, evidence="coord+gid+name", gauge_id="8726674",
             station_label="East_Bay"),
    ]
    chosen, notes = build_mllw_table.pick_per_row(mapped)
    assert [c["coops_code"] for c in chosen] == ["estb"]
    assert notes and "factors differed" in notes[0]


# --------------------------------------------------------------------------
# the guard against a shifted station list
# --------------------------------------------------------------------------

def test_alignment_check_catches_an_inserted_station(files):
    sta, _, table = files
    factors = stations_mllw._read_factors(table)
    stations = stations_mllw._read_station_in(sta)
    stations_mllw._check_alignment(factors, stations)  # baseline passes

    shifted = [dict(s) for s in stations]
    shifted.insert(0, dict(row=0, lon=-80.0, lat=30.0, label="New_Gauge(1234567)"))
    for i, s in enumerate(shifted, 1):
        s["row"] = i
    with pytest.raises(ValueError, match="no longer matches station.in"):
        stations_mllw._check_alignment(factors, shifted)


def test_alignment_check_tolerates_hand_annotations(files):
    """station.in labels collect '## machuan changed'; that is not a mismatch."""
    sta, _, table = files
    factors = stations_mllw._read_factors(table)
    stations = stations_mllw._read_station_in(sta)
    stations[0]["label"] = "Key_West(8724580) ## machuan changed"
    stations_mllw._check_alignment(factors, stations)


def test_factor_table_rejects_a_repeated_row(tmp_path):
    table = tmp_path / "dupe.csv"
    table.write_text(
        "station_row,gauge_id,coops_code,station_label,mllw_factor\n"
        "1,8724580,keyw,Key_West(8724580),0.400\n"
        "1,8726520,stpe,St_Petersburg(8726520),0.481\n"
    )
    with pytest.raises(ValueError, match="station_row repeated"):
        stations_mllw._read_factors(table)


# --------------------------------------------------------------------------
# the product
# --------------------------------------------------------------------------

def test_product_is_registered_and_names_its_worker():
    cls = get_product("stations_mllw")
    assert cls is not None
    assert cls.worker == "nos_workflow.post.products.stations_mllw"


def test_stations_nc_runs_before_stations_mllw():
    assert _ordered_products(["stations_mllw", "stations_nc"]) == [
        "stations_nc", "stations_mllw"
    ]
    # already correct, and unrelated products keep their order
    assert _ordered_products(["stations_nc", "maxele", "stations_mllw"]) == [
        "stations_nc", "maxele", "stations_mllw"
    ]


def test_both_dependencies_are_satisfied_together():
    ordered = _ordered_products(
        ["stations_mllw", "geopkg", "fields_nc", "stations_nc"]
    )
    assert ordered.index("stations_nc") < ordered.index("stations_mllw")
    assert ordered.index("fields_nc") < ordered.index("geopkg")


def test_naming_is_a_sibling_of_the_station_product():
    assert stations_mllw_name("secofs_ufs", "12", "20260728", "forecast") == (
        "secofs_ufs.t12z.20260728.stations.mllw.forecast.nc"
    )


def test_a_repeated_product_runs_once():
    """A duplicated YAML entry must not re-split and re-publish everything."""
    assert _ordered_products(
        ["maxele", "fields_nc", "slab2d", "fields_nc"]
    ) == ["fields_nc", "maxele", "slab2d"]


def test_worker_args_skips_without_the_fix_table(tmp_path, files):
    ctx = _ctx(tmp_path, files, with_table=False)
    product = get_product("stations_mllw")()
    assert product.worker_args(ctx, "forecast", tmp_path, tmp_path) is None


def test_worker_args_skips_when_the_station_file_was_not_produced(tmp_path, files):
    ctx = _ctx(tmp_path, files)
    product = get_product("stations_mllw")()
    assert product.worker_args(ctx, "forecast", tmp_path, tmp_path) is None


def test_worker_args_points_at_the_station_product_output(tmp_path, files):
    from nos_workflow.post.naming import stations_nc_name

    ctx = _ctx(tmp_path, files)
    source = ctx.comout / stations_nc_name("secofs_ufs", "12", "20260728", "forecast")
    source.write_text("")
    args = get_product("stations_mllw")().worker_args(
        ctx, "forecast", tmp_path, tmp_path
    )
    assert args is not None
    paired = dict(zip(args[::2], args[1::2]))
    assert paired["--stations-nc"] == str(source)
    assert paired["--phase"] == "forecast"
    assert Path(paired["--factors"]).name == "secofs_ufs.mllw_datum.csv"
    assert paired["--station-in"] == str(ctx.sta_in)


def _ctx(tmp_path: Path, files, with_table: bool = True):
    """A ProductContext with $FIXofs and $COMOUT laid out as on WCOSS2."""
    from unittest.mock import Mock

    sta, _, table = files
    fixofs = tmp_path / "fix"
    fixofs.mkdir(exist_ok=True)
    if with_table:
        (fixofs / "secofs_ufs.mllw_datum.csv").write_text(table.read_text())
    comout = tmp_path / "com"
    comout.mkdir(exist_ok=True)
    return ProductContext(
        descriptor=Mock(framework="stofs_ufs"),
        shell_env={},
        homenos=tmp_path,
        fixofs=fixofs,
        comout=comout,
        data=tmp_path / "data",
        pdy="20260728",
        cyc="12",
        cycle="2026072812",
        run_name="secofs_ufs",
        prefix_nos="secofs_ufs",
        nc_hour="00",
        sta_in=sta,
        combine_script=tmp_path / "combine.py",
        pgmout=str(tmp_path / "pgmout"),
    )


def test_missing_source_file_gives_the_documented_exit_code(tmp_path, files):
    _, _, table = files
    rc = stations_mllw.main([
        "--stations-nc", str(tmp_path / "absent.nc"),
        "--comout", str(tmp_path), "--prefix", "test", "--cyc", "12",
        "--pdy", "20260728", "--phase", "forecast",
        "--factors", str(table), "--station-in", str(tmp_path / "station.in"),
    ])
    assert rc == 2


@needs_netcdf4
def test_writes_shifted_water_level_for_the_mapped_stations(tmp_path, files):
    import numpy as np
    from netCDF4 import Dataset

    sta, _, table = files
    source = tmp_path / "src.nc"
    zeta = np.array([[0.10, 0.20, 0.30, 0.40, 0.0, 0.0],
                     [-0.05, 0.00, 0.05, 0.10, 0.0, 0.0]])
    with Dataset(source, "w") as ds:
        ds.createDimension("time", None)
        ds.createDimension("station", 6)
        t = ds.createVariable("time", "f8", ("time",))
        t.units = "seconds since 2026-07-28 12:00:00"
        t[:] = [0.0, 360.0]
        z = ds.createVariable("zeta", "f4", ("time", "station"))
        z[:] = zeta

    comout = tmp_path / "com"
    comout.mkdir()
    rc = stations_mllw.main([
        "--stations-nc", str(source), "--comout", str(comout),
        "--prefix", "test", "--cyc", "12", "--pdy", "20260728",
        "--phase", "forecast", "--factors", str(table),
        "--station-in", str(sta),
    ])
    assert rc == 0

    out = comout / stations_mllw_name("test", "12", "20260728", "forecast")
    with Dataset(out) as ds:
        assert ds.dimensions["station"].size == 3
        assert list(ds.variables["station_row"][:]) == [1, 2, 4]
        np.testing.assert_allclose(
            ds.variables["mllw_factor"][:], [0.400, 0.481, 1.150]
        )
        # zeta + factor, taken from source columns 0, 1 and 3
        np.testing.assert_allclose(
            ds.variables["zeta_mllw"][0, :],
            [0.10 + 0.400, 0.20 + 0.481, 0.40 + 1.150],
            atol=1e-6,
        )
        np.testing.assert_allclose(
            ds.variables["zeta_mllw"][1, :],
            [-0.05 + 0.400, 0.00 + 0.481, 0.10 + 1.150],
            atol=1e-6,
        )
        assert ds.variables["zeta_mllw"].datum == "MLLW"
        assert ds.model_vertical_datum == "xGEOID20B"
        assert ds.variables["time"].units == "seconds since 2026-07-28 12:00:00"
        # coordinates come from station.in, not from the source file
        np.testing.assert_allclose(
            ds.variables["lon"][:], [-81.8081, -82.629439, -76.083333]
        )


def _source(path, zeta, n_station=6, fill=None, lonlat=None, dims=None):
    """Minimal stand-in for a stations_nc output."""
    import numpy as np
    from netCDF4 import Dataset

    with Dataset(path, "w") as ds:
        ds.createDimension("time", None)
        ds.createDimension("station", n_station)
        t = ds.createVariable("time", "f8", ("time",))
        t.units = "seconds since 2026-07-28 12:00:00"
        t[:] = np.arange(len(zeta)) * 360.0
        kw = {"fill_value": fill} if fill is not None else {}
        z = ds.createVariable("zeta", "f4", dims or ("time", "station"), **kw)
        z[:] = zeta
        if lonlat is not None:
            lon, lat = lonlat
            ds.createVariable("lon", "f8", ("station",))[:] = lon
            ds.createVariable("lat", "f8", ("station",))[:] = lat


def _run(tmp_path, files, source, comout=None):
    sta, _, table = files
    out = comout or (tmp_path / "com")
    out.mkdir(exist_ok=True)
    return out, stations_mllw.main([
        "--stations-nc", str(source), "--comout", str(out),
        "--prefix", "test", "--cyc", "12", "--pdy", "20260728",
        "--phase", "forecast", "--factors", str(table),
        "--station-in", str(sta),
    ])


@needs_netcdf4
def test_absent_source_values_stay_absent_instead_of_becoming_water_levels(
    tmp_path, files
):
    """A masked source value must not be published as fill+factor.

    netCDF4 returns a masked array and np.asarray on it hands back the raw
    fill bytes, so adding the factor would yield something like -99998.6 --
    indistinguishable from a real water level to any consumer.
    """
    import numpy as np
    from netCDF4 import Dataset

    src = tmp_path / "masked.nc"
    zeta = np.ma.masked_array(
        [[0.10, 0.20, 0.30, 0.40, 0.0, 0.0],
         [0.15, 0.25, 0.35, 0.45, 0.0, 0.0]],
        mask=[[False] * 6, [True] + [False] * 5],
    )
    _source(src, zeta, fill=-99999.0)

    comout, rc = _run(tmp_path, files, src)
    assert rc == 0
    out = comout / stations_mllw_name("test", "12", "20260728", "forecast")
    with Dataset(out) as ds:
        got = ds.variables["zeta_mllw"][:]
        assert np.ma.is_masked(got)
        assert got.mask[1, 0]
        assert not got.mask[0, 0]
        np.testing.assert_allclose(got[0, 0], 0.10 + 0.400, atol=1e-6)
        # nothing anywhere near a fill value leaked through as a number
        assert np.abs(got.compressed()).max() < 10.0


@needs_netcdf4
def test_an_entirely_unwritten_zeta_is_refused(tmp_path, files):
    """The combine step leaves zeta at the type default fill when staout_1 is
    missing; publishing 9.97e36 for every station must not report success."""
    import numpy as np
    from netCDF4 import Dataset

    src = tmp_path / "unwritten.nc"
    with Dataset(src, "w") as ds:
        ds.createDimension("time", None)
        ds.createDimension("station", 6)
        t = ds.createVariable("time", "f8", ("time",))
        t.units = "seconds since 2026-07-28 12:00:00"
        t[:] = [0.0]
        ds.createVariable("zeta", "f4", ("time", "station"))  # never assigned
    _, rc = _run(tmp_path, files, src)
    assert rc == 5


@needs_netcdf4
def test_source_coordinates_disagreeing_with_station_in_is_fatal(tmp_path, files):
    """If the station dimension is not in station.in row order, every factor
    would land on the wrong gauge -- and the labels alone cannot detect it."""
    import numpy as np

    src = tmp_path / "shuffled.nc"
    lon = [-81.8081, -82.629439, -80.9, -76.083333, -82.555, -82.522]
    lat = [24.5508, 27.759567, 32.0, 37.033333, 27.7884, 27.786]
    # rotate the coordinates: same values, wrong rows
    _source(src, [[0.0] * 6], lonlat=(lon[1:] + lon[:1], lat[1:] + lat[:1]))
    _, rc = _run(tmp_path, files, src)
    assert rc == 5


@needs_netcdf4
def test_matching_source_coordinates_pass_the_check(tmp_path, files):
    src = tmp_path / "aligned.nc"
    lon = [-81.8081, -82.629439, -80.9, -76.083333, -82.555, -82.522]
    lat = [24.5508, 27.759567, 32.0, 37.033333, 27.7884, 27.786]
    _source(src, [[0.1] * 6], lonlat=(lon, lat))
    _, rc = _run(tmp_path, files, src)
    assert rc == 0


@needs_netcdf4
def test_a_three_dimensional_zeta_is_rejected_not_broadcast(tmp_path, files):
    """With a level axis the per-station shift could broadcast along it."""
    import numpy as np
    from netCDF4 import Dataset

    src = tmp_path / "zeta3d.nc"
    with Dataset(src, "w") as ds:
        ds.createDimension("time", None)
        ds.createDimension("station", 6)
        ds.createDimension("lev", 3)
        t = ds.createVariable("time", "f8", ("time",))
        t.units = "seconds since 2026-07-28 12:00:00"
        t[:] = [0.0]
        ds.createVariable("zeta", "f4", ("time", "station", "lev"))[:] = np.zeros(
            (1, 6, 3)
        )
    _, rc = _run(tmp_path, files, src)
    assert rc == 5


def test_a_table_row_with_no_label_is_refused(tmp_path):
    """An empty label would make the alignment check vacuously true."""
    table = tmp_path / "blank.csv"
    table.write_text(
        "station_row,gauge_id,coops_code,station_label,mllw_factor\n"
        "1,8724580,keyw,,0.400\n"
    )
    with pytest.raises(ValueError, match="station_label is empty"):
        stations_mllw._read_factors(table)


def test_generator_refuses_a_station_with_no_name_comment(tmp_path):
    sta = tmp_path / "station.in"
    sta.write_text("1 1 1 !flags\n1\n1 -81.808100 24.550800 0.000000 !\n")
    ctl = tmp_path / "wl.ctl"
    ctl.write_text(
        "ST='Key_West(8724580)' 'keyw' 24.550800 -81.808100 0.400  1 1 1  1 1 0  1 1 0  1\n"
    )
    assert build_mllw_table.main(
        ["--ctl", str(ctl), "--station-in", str(sta),
         "--out", str(tmp_path / "t.csv")]
    ) == 1


def test_generator_tolerates_trailing_text_after_the_flags(tmp_path):
    """The flags are not consumed, so a trailing note must not abort the tool."""
    ctl = tmp_path / "wl.ctl"
    ctl.write_text(
        "ST='Key_West(8724580)' 'keyw' 24.550800 -81.808100 0.400"
        "  1 1 1  1 1 0  1 1 0  1  ; ops note\n"
    )
    entries = build_mllw_table.read_ctl(ctl)
    assert [e["code"] for e in entries] == ["keyw"]
    assert entries[0]["factor"] == 0.400


def test_truncated_station_in_reports_rather_than_tracebacks(tmp_path, files):
    _, _, table = files
    short = tmp_path / "short.in"
    short.write_text("1 1 1 1 !flags only\n")
    rc = stations_mllw.main([
        "--stations-nc", str(tmp_path), "--comout", str(tmp_path),
        "--prefix", "test", "--cyc", "12", "--pdy", "20260728",
        "--phase", "forecast", "--factors", str(table),
        "--station-in", str(short),
    ])
    assert rc in (2, 5)


@needs_netcdf4
def test_station_count_mismatch_between_source_and_list_fails(tmp_path, files):
    from netCDF4 import Dataset

    sta, _, table = files
    source = tmp_path / "short.nc"
    with Dataset(source, "w") as ds:
        ds.createDimension("time", None)
        ds.createDimension("station", 4)  # station.in declares 6
        t = ds.createVariable("time", "f8", ("time",))
        t.units = "seconds since 2026-07-28 12:00:00"
        t[:] = [0.0]
        ds.createVariable("zeta", "f4", ("time", "station"))[:] = [[0.0] * 4]

    rc = stations_mllw.main([
        "--stations-nc", str(source), "--comout", str(tmp_path),
        "--prefix", "test", "--cyc", "12", "--pdy", "20260728",
        "--phase", "forecast", "--factors", str(table),
        "--station-in", str(sta),
    ])
    assert rc == 5
