#!/usr/bin/env python3
"""Build the STOFS-3D-AK MLLW datum-factor fix table from vdatum surfaces.

SECOFS gets its per-station MLLW factors from a CO-OPS IDL control file
(``tools/build_mllw_table.py`` reconciles it against ``station.in``). No
such control file exists for Alaska, so this tool computes the factors
directly from the NOAA vertical-datum transformation surfaces via the
``coastalmodeling-vdatum`` package (``pip install coastalmodeling-vdatum``),
at the model station coordinates rather than the CO-OPS gauge coordinates
(the two are up to ~860 m apart at Unalakleet; the model needs the shift at
the point it actually samples). The emitted table is read by the same
``stations_mllw`` post product and carries SECOFS's five columns
(``fix/secofs_ufs/secofs_ufs.mllw_datum.csv``) plus two Alaska-only ones,
``lon``/``lat`` (signed, the coastalmodeling-vdatum convention).

SECOFS's ctl file and its station.in both derive their station labels from
the same source, so they always match verbatim and ``stations_mllw`` can
align the two on that alone. Alaska's station.in was staged independently
(fetched directly from the R09a run, never passed through a ctl-reconciling
step) and its comments read e.g. ``[WL,T],9459450,CO-OPS,Sand Point``, not
this tool's ``CO-OPS 9459450 AK Sand Point`` -- so an exact-label match
never holds here. ``stations_mllw._check_alignment`` falls back, for rows
where it does not, to confirming the gauge id against the station.in
comment text plus these two coordinate columns against station.in's own;
that fallback is why lon/lat are written here even though SECOFS's table
has no need for them.

    zeta_mllw = zeta + mllw_factor,  where zeta is on xGEOID20B ("model zero")

mllw_factor is computed as ``vdatum.convert("xgeoid20b", "mllw", lat, lon,
0.0)[2]`` -- the height, in the MLLW system, of the point that sits at 0 in
the xGEOID20B system, which is exactly xGEOID20B's height above MLLW at that
location (verified against an independently 3-way-validated reference table
to < 1 mm). "lmsl" is also queried, printed for cross-reference only; it is
not one of the columns written to the table.

Two premises this result rests on, both worth re-checking before trusting it
operationally:

  * Model zero really is xGEOID20B. STOFS-3D-AK ships no xgeoid->datum .nco
    (parm/systems/stofs_3d_ak_ufs.yaml's obc.ssh_offset is null, "UNVERIFIED
    for Alaska"), so this is a working assumption pending confirmation from
    Felicio Cassalho, not an established fact. If it is wrong, the fix is
    not a constant shift applied to every factor here -- the difference
    between two vertical datums/geoids varies spatially, so the factors
    would need to be regenerated against whichever reference surface model
    zero actually is.

  * Epoch mismatch. The vdatum surfaces used
    (nwldatum_4.7.0, ITRF2020, epoch 2020.0) are not on the same temporal
    footing as CO-OPS's own MLLW, which is defined over the National Tidal
    Datum Epoch (1983-2001). At these latitudes the gap folds into
    coastalmodeling-vdatum's own quoted ~9 cm transform uncertainty for this
    region; it is not corrected for separately here.

Only the 9 CO-OPS water-level gauges (station.in rows 1-9) get a factor.
Rows 10-22 (NDBC buoys, synthetic "modulation" points) have no tidal datum
and are simply absent from the table -- the same "absent, not defaulted to
0" behavior SECOFS uses for a station its control file does not cover.

Usage (online; fetches the vdatum geotiffs from S3 over HTTPS via pyproj's
network-enabled grid shift, cached under pyproj's user data dir):

    python3 tools/gen_ak_datum_offsets.py \\
        --station-csv fix/stofs_3d_ak_ufs/stofs_3d_ak_staout_nc.csv \\
        --out fix/stofs_3d_ak_ufs/stofs_3d_ak_ufs.mllw_datum.csv

Offline alternative (e.g. a WCOSS2 compute node with no outbound network):
fetch the surfaces coastalmodeling_vdatum._path.py names --

    us_noaa_nos_MLLW-ITRF2020_2020.0_nwldatum_4.7.0_20240621_3.tif
    us_noaa_nos_LMSL-ITRF2020_2020.0_nwldatum_4.7.0_20240621_3.tif
    xGEOID20B.tif

from ``s3://noaa-nos-stofs2d-pds/_archive/coastalmodeling-vdatum/`` (public,
no credentials needed) onto a login node, place them where PROJ's grid
search looks (``PROJ_DATA``, or pyproj's user data dir --
``pyproj.datadir.get_user_data_dir()``), then rerun with ``--offline``.
``coastalmodeling_vdatum.vdatum.convert`` is given ``online=False``, which
skips the pyproj network toggle and resolves the same grid names locally.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path
from typing import List, NamedTuple, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATION_CSV = (
    REPO_ROOT / "fix" / "stofs_3d_ak_ufs" / "stofs_3d_ak_staout_nc.csv"
)
DEFAULT_OUT = (
    REPO_ROOT / "fix" / "stofs_3d_ak_ufs" / "stofs_3d_ak_ufs.mllw_datum.csv"
)

#: Only the leading rows of the staout CSV are CO-OPS water-level gauges;
#: the rest are NDBC buoys and synthetic points with no tidal datum.
N_COOPS_STATIONS = 9

_GAUGE_ID_RE = re.compile(r"\b(\d{6,8})\b")

#: A row selected as a CO-OPS tidal gauge must actually be one -- the
#: staout metadata csv is just "the first N rows are CO-OPS, the rest
#: aren't" with nothing else enforcing it. This is the pattern the tool
#: actually emits for CO-OPS rows, e.g. "CO-OPS 9459450 AK Sand Point".
_COOPS_ROW_RE = re.compile(r"^CO-OPS \d{7}\b")

_HEADER = """\
# MLLW datum factors, added to model water level (xGEOID20B) to
# reference it to MLLW. Generated by tools/gen_ak_datum_offsets.py from
# coastalmodeling-vdatum (nwldatum_4.7.0 ITRF2020 LMSL/MLLW surfaces,
# differenced against xGEOID20B at each station); do not hand-edit.
#
# source: coastalmodeling-vdatum vertical-datum transformation surfaces (nwldatum_4.7.0, ITRF2020), not a CO-OPS control file
#
# datum_note: model zero = xGEOID20B is a working assumption pending confirmation; factors from nwldatum 4.7.0 ITRF2020 surfaces (~9 cm transform uncertainty; CO-OPS tidal epoch 1983-2001)
#
# station_row is the 1-based row order of station.in, which is the
# station dimension order SCHISM writes. Column 1 of station.in is a
# per-group counter and is NOT a station key.
#
# Premise: model zero is xGEOID20B. Working assumption pending
# confirmation from Felicio Cassalho -- stofs_3d_ak_ufs ships no
# xgeoid->datum .nco yet (obc.ssh_offset in
# parm/systems/stofs_3d_ak_ufs.yaml is null, "UNVERIFIED for Alaska").
# If wrong, the fix is not a constant shift applied to every factor below
# -- the datum difference varies spatially, so the factors would need to
# be regenerated against whichever reference surface model zero actually is.
#
# Epoch caveat: these surfaces are referenced to epoch 2020.0
# (ITRF2020); CO-OPS's own MLLW is defined over the National Tidal
# Datum Epoch 1983-2001. That gap is within coastalmodeling-vdatum's
# own quoted ~9 cm transform uncertainty for this region and is not
# separately corrected for here.
#
# Coordinates are the model station nodes (this file's own source,
# fix/stofs_3d_ak_ufs/stofs_3d_ak_staout_nc.csv), not the CO-OPS gauge
# coordinates -- up to ~860 m apart at Unalakleet -- since the shift
# is needed at the point the model actually samples.
#
# Only the 9 CO-OPS water-level gauges (station.in rows 1-9) get a
# factor; rows 10-22 (NDBC buoys, synthetic modulation points) have no
# tidal datum and are simply absent, as SECOFS also omits stations its
# control file does not cover.
#
# Regenerate with:
#   python3 tools/gen_ak_datum_offsets.py \\
#       --station-csv fix/stofs_3d_ak_ufs/stofs_3d_ak_staout_nc.csv \\
#       --out fix/stofs_3d_ak_ufs/stofs_3d_ak_ufs.mllw_datum.csv
"""

#: SECOFS's five columns plus lon/lat -- signed, coastalmodeling-vdatum's
#: own convention (see ``to_signed_lon``) -- which ``stations_mllw``'s
#: alignment check uses to confirm a gauge id it found in station.in's
#: comment actually sits at the row it claims to (see the module
#: docstring). SECOFS's table has no need for them and stays 5 columns.
_FIELDS = [
    "station_row", "gauge_id", "coops_code", "station_label", "mllw_factor",
    "lon", "lat",
]


class Station(NamedTuple):
    row: int
    label: str
    lon: float  # degrees_east, 0-360 (this domain's convention; see below)
    lat: float


def read_station_csv(path: Path, n_stations: int) -> List[Station]:
    """The first ``n_stations`` rows of the staout-nc CSV, in file order.

    Format: ``;``-separated, columns located by header name (``station_info``,
    ``lon``, ``lat``), matching ``nos_utils.post.stations.load_station_csv``.
    Row *i* (0-based) is station.in row *i+1* -- the file is already in
    SCHISM's station dimension order.
    """
    with path.open(newline="") as fh:
        rows = [
            r for r in csv.reader(fh, delimiter=";")
            if any(cell.strip() for cell in r)
        ]
    if not rows:
        raise ValueError(f"{path}: empty station csv")
    col = {name: i for i, name in enumerate(rows[0])}
    missing = [k for k in ("station_info", "lon", "lat") if k not in col]
    if missing:
        raise ValueError(f"{path}: missing column(s) {missing}")

    out = []
    for i, row in enumerate(rows[1 : n_stations + 1], start=1):
        label = row[col["station_info"]].strip()
        if not _COOPS_ROW_RE.match(label):
            raise ValueError(
                f"{path}: row {i} of the leading {n_stations}-row CO-OPS "
                f"block is not a CO-OPS tidal gauge: station_info={label!r}; "
                "expected it to start with 'CO-OPS ' followed by a "
                "7-digit station id. Check that --n-stations still matches "
                "the leading CO-OPS block in this file -- a non-CO-OPS row "
                "(e.g. an NDBC buoy) this far up would get a bogus MLLW "
                "factor computed for it"
            )
        out.append(
            Station(
                row=i,
                label=label,
                lon=float(row[col["lon"]]),
                lat=float(row[col["lat"]]),
            )
        )
    if len(out) < n_stations:
        raise ValueError(
            f"{path}: only {len(out)} data row(s), need {n_stations}"
        )
    return out


def to_signed_lon(lon_0_360: float) -> float:
    """0-360 (this domain's dateline-crossing convention) -> -180..180.

    vdatum's transform pipeline expects standard signed longitude.
    """
    return lon_0_360 - 360.0 if lon_0_360 > 180.0 else lon_0_360


def mllw_factor(lat: float, lon_signed: float, online: bool) -> float:
    """``xGEOID20B`` height above ``MLLW`` at (lat, lon): the factor itself.

    ``vdatum.convert("xgeoid20b", "mllw", lat, lon, 0.0)`` returns the MLLW
    value of the point that sits at 0 in the xGEOID20B system -- i.e.
    exactly xGEOID20B's height above MLLW there, which is what
    ``zeta_mllw = zeta + mllw_factor`` needs added to a model water level.
    """
    from coastalmodeling_vdatum import vdatum

    _, _, cz = vdatum.convert(
        "xgeoid20b", "mllw", lat, lon_signed, 0.0, online=online
    )
    return float(cz)


def lmsl_reference(lat: float, lon_signed: float, online: bool) -> float:
    """LMSL's height above xGEOID20B, for cross-reference only (not stored)."""
    from coastalmodeling_vdatum import vdatum

    _, _, cz = vdatum.convert(
        "lmsl", "xgeoid20b", lat, lon_signed, 0.0, online=online
    )
    return float(cz)


def gauge_id(label: str) -> str:
    m = _GAUGE_ID_RE.search(label)
    return m.group(1) if m else ""


def build_rows(stations: List[Station], online: bool) -> List[dict]:
    rows = []
    for s in stations:
        lon = to_signed_lon(s.lon)
        factor = round(mllw_factor(s.lat, lon, online), 3)
        lmsl = lmsl_reference(s.lat, lon, online)
        print(
            f"row {s.row:2d}  {s.label:45s}  mllw_factor={factor:+.3f}  "
            f"(lmsl_ref={lmsl:+.3f})"
        )
        rows.append(
            dict(
                station_row=s.row,
                gauge_id=gauge_id(s.label),
                coops_code="",  # no Alaska ctl/short-code table exists yet
                station_label=s.label,
                mllw_factor=factor,
                lon=round(lon, 4),  # signed; station.in itself is 0-360
                lat=round(s.lat, 4),
            )
        )
    return rows


def write_table(rows: List[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as fh:
        fh.write(_HEADER)
        # excel's default lineterminator is "\r\n"; the header above is
        # plain "\n", and a per-writer mix trips `git diff --check` and
        # leaves the file "ASCII text, with CRLF, LF line terminators".
        writer = csv.DictWriter(
            fh, fieldnames=_FIELDS, extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        for rec in rows:
            writer.writerow(rec)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--station-csv", type=Path, default=DEFAULT_STATION_CSV)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument(
        "--n-stations", type=int, default=N_COOPS_STATIONS,
        help="leading rows of --station-csv that are CO-OPS gauges",
    )
    ap.add_argument(
        "--offline", action="store_true",
        help="use locally cached vdatum geotiffs instead of fetching over "
             "the network (see the module docstring for the S3 source)",
    )
    args = ap.parse_args(argv)

    try:
        from coastalmodeling_vdatum import vdatum  # noqa: F401
    except ImportError as exc:
        print(f"gen_ak_datum_offsets: coastalmodeling-vdatum unavailable: {exc}")
        return 1

    try:
        stations = read_station_csv(args.station_csv, args.n_stations)
    except (OSError, ValueError) as exc:
        print(f"gen_ak_datum_offsets: {args.station_csv}: {exc}")
        return 1

    rows = build_rows(stations, online=not args.offline)
    write_table(rows, args.out)
    factors = sorted(r["mllw_factor"] for r in rows)
    print(
        f"\nwrote {args.out} ({len(rows)} stations, factors "
        f"{factors[0]:+.3f} .. {factors[-1]:+.3f})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
