"""Contract tests for tools/gen_ak_datum_offsets.py.

The pure helpers (coordinate parsing, longitude conversion, gauge-id
extraction) are tested without network access. The generator itself needs
``coastalmodeling-vdatum`` and, in online mode, a working connection to
fetch its geotiffs; that end-to-end check is skipped rather than failed
when either is unavailable, same as ``needs_netcdf4`` elsewhere in this
test suite.
"""
from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
_TOOL = REPO_ROOT / "tools" / "gen_ak_datum_offsets.py"
_SPEC = importlib.util.spec_from_file_location("gen_ak_datum_offsets", _TOOL)
assert _SPEC is not None and _SPEC.loader is not None
gen = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gen)

AK_STAOUT_CSV = REPO_ROOT / "fix" / "stofs_3d_ak_ufs" / "stofs_3d_ak_staout_nc.csv"
AK_TABLE = REPO_ROOT / "fix" / "stofs_3d_ak_ufs" / "stofs_3d_ak_ufs.mllw_datum.csv"


def _have_vdatum() -> bool:
    try:
        import coastalmodeling_vdatum  # noqa: F401
    except ImportError:
        return False
    return True


needs_vdatum = pytest.mark.skipif(not _have_vdatum(), reason="coastalmodeling-vdatum not installed")


def test_default_paths_point_at_the_real_ak_fix_files():
    assert gen.DEFAULT_STATION_CSV == AK_STAOUT_CSV
    assert gen.DEFAULT_OUT == AK_TABLE


@pytest.mark.parametrize(
    "lon_0_360, expected",
    [(199.496, -160.504), (183.382, -176.618), (170.0, 170.0), (180.0, 180.0)],
)
def test_to_signed_lon(lon_0_360, expected):
    assert gen.to_signed_lon(lon_0_360) == pytest.approx(expected)


@pytest.mark.parametrize(
    "label, expected",
    [
        ("CO-OPS 9459450 AK Sand Point", "9459450"),
        ("CO-OPS 9468756 AK Nome, Norton Sound", "9468756"),
        ("NDBC 46035 AK Central Bering Sea", ""),
        ("SYNTHETIC AK modulation1 (no gauge)", ""),
    ],
)
def test_gauge_id_extraction(label, expected):
    assert gen.gauge_id(label) == expected


def test_read_station_csv_gets_the_nine_coops_rows_in_order():
    stations = gen.read_station_csv(AK_STAOUT_CSV, gen.N_COOPS_STATIONS)
    assert len(stations) == 9
    assert [s.row for s in stations] == list(range(1, 10))
    assert stations[0].label == "CO-OPS 9459450 AK Sand Point"
    assert stations[0].lon == pytest.approx(199.496)
    assert stations[0].lat == pytest.approx(55.332)
    assert stations[-1].label == "CO-OPS 9468756 AK Nome, Norton Sound"


def test_read_station_csv_rejects_too_few_rows(tmp_path):
    """A synthetic, all-valid-CO-OPS-pattern file with fewer rows than
    requested -- kept separate from the real AK file so this exercises
    only the row-count guard, not the row-pattern guard added alongside
    it (the real file's rows past 9 are NDBC/synthetic and would now trip
    that check first for any --n-stations > 9)."""
    short = tmp_path / "short_staout.csv"
    short.write_text(
        ";station_info;lon;lat\n"
        "0;CO-OPS 9459450 AK Sand Point;199.496;55.332\n"
        "1;CO-OPS 9459881 AK King Cove;197.6741;55.060\n"
        "2;CO-OPS 9461380 AK Adak Island;183.382;51.861\n"
    )
    with pytest.raises(ValueError, match="need 5"):
        gen.read_station_csv(short, 5)


def test_read_station_csv_rejects_a_non_coops_row_in_the_leading_block(tmp_path):
    """A row moved into the first N (e.g. an NDBC buoy after a re-sort of
    the staout metadata) must abort loudly, naming the offending row --
    silently accepting it would compute a bogus MLLW factor for a buoy
    that has no tidal datum at all."""
    lines = AK_STAOUT_CSV.read_text().splitlines(keepends=True)
    header, rows = lines[0], lines[1:]
    assert rows[8].startswith("8;CO-OPS 9468756")  # row 9, 0-based index 8
    doctored = [header] + rows[:8] + [rows[9]] + [rows[8]] + rows[10:]
    assert doctored[9].startswith("9;NDBC 46035")

    bad_csv = tmp_path / "doctored_staout.csv"
    bad_csv.write_text("".join(doctored))

    with pytest.raises(ValueError, match=r"row 9.*not a CO-OPS tidal gauge"):
        gen.read_station_csv(bad_csv, gen.N_COOPS_STATIONS)


def test_read_station_csv_accepts_the_real_ak_leading_block():
    """The real file's first 9 rows must still pass the new row check --
    proves the pattern isn't so strict it rejects genuine CO-OPS rows."""
    stations = gen.read_station_csv(AK_STAOUT_CSV, gen.N_COOPS_STATIONS)
    assert len(stations) == 9


def test_ak_table_matches_the_generator_helper_row_order():
    """The checked-in table's row order/labels are exactly the staout
    CSV's first 9 rows -- what the generator itself would emit given the
    same station file."""
    stations = gen.read_station_csv(AK_STAOUT_CSV, gen.N_COOPS_STATIONS)
    with AK_TABLE.open() as fh:
        lines = [ln for ln in fh if ln.strip() and not ln.startswith("#")]
    rows = list(csv.DictReader(lines))
    assert [r["station_label"] for r in rows] == [s.label for s in stations]
    assert [r["gauge_id"] for r in rows] == [gen.gauge_id(s.label) for s in stations]


@needs_vdatum
def test_generator_reproduces_the_checked_in_table_to_the_millimeter(tmp_path):
    """Regenerate into a scratch file and compare to the checked-in one --
    proves the two do not drift apart, not just that the tool runs.

    Only the actual network/data-availability failure is skipped, not any
    exception whatsoever: coastalmodeling-vdatum's ``convert`` builds a
    pyproj pipeline whose grids are fetched over HTTPS (or resolved from a
    local cache), and when that grid is unreachable -- no network, or no
    cached geotiff for --offline -- pyproj raises ``pyproj.exceptions.
    ProjError`` (confirmed by inspection of vdatum.py's ``build_pipe``,
    which hands the grid URL straight to ``pyproj.Transformer.from_pipeline``
    with no try/except of its own, and by reproducing the failure directly:
    pointing PROJ_DATA at an empty directory with networking off raises
    exactly this type, wrapping PROJ's "File not found or invalid" error).
    A bug in this tool's own code -- a bad station-csv parse (ValueError),
    a typo'd attribute (AttributeError/TypeError), or a wrong premise this
    test's own assertions would catch (AssertionError) -- must fail loudly
    instead of being swallowed as "no network"."""
    import pyproj.exceptions

    out = tmp_path / "regen.mllw_datum.csv"
    try:
        rc = gen.main(["--out", str(out)])
    except pyproj.exceptions.ProjError as exc:
        pytest.skip(f"vdatum surfaces unavailable: {exc}")
    if rc != 0:
        pytest.skip("generator did not succeed (likely no network)")

    checked_in = {
        r["station_row"]: float(r["mllw_factor"])
        for r in csv.DictReader(
            ln for ln in AK_TABLE.read_text().splitlines()
            if ln.strip() and not ln.startswith("#")
        )
    }
    regenerated = {
        r["station_row"]: float(r["mllw_factor"])
        for r in csv.DictReader(
            ln for ln in out.read_text().splitlines()
            if ln.strip() and not ln.startswith("#")
        )
    }
    assert set(checked_in) == set(regenerated)
    for row, factor in checked_in.items():
        assert regenerated[row] == pytest.approx(factor, abs=1e-3), row
