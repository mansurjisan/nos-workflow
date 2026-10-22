"""MLLW-referenced station water level, derived from the station NetCDF.

Model water level is on xGEOID20B ("model zero"), which no tide gauge is
referenced to, so nothing in ``stations_nc`` is directly comparable to an
observation. This product publishes the same water level shifted onto MLLW
for the stations CO-OPS has a datum factor for::

    zeta_mllw = zeta + mllw_factor

The factors come from the CO-OPS control file via
``nos_workflow.tools.build_mllw_table``; see that module for how the
station mapping is derived and verified.

The direction of the shift is measured, not assumed. Operational
observations are fetched with ``datum=MLLW``, so the observations already
sit on MLLW and are not what moves; and against ops' own ``zeta`` at Key
West, ``zeta + 0.400`` lands within 0.057 m of the observed value at two
times 28 h apart, where subtracting misses by 0.857 m and not shifting by
0.457 m.

Kept separate from ``stations_nc`` deliberately: that file matches the ops
schema, which is what allows it to be handed to the CO-OPS plotting job
unchanged. Adding a variable to it would forfeit that.

Coordinates are read from ``station.in`` rather than copied from the source
file, because the ops station metadata is keyed inconsistently and its x/y
can arrive transposed (see ``points_cwl._warn_transposed_coords``);
``station.in`` is unambiguous.

Exit codes: 2 source station file absent, 5 unusable factor table, a station
list that no longer matches it, or a source whose coordinates or dimensions
contradict it. Note the phase-has-no-station-output skip is delivered by
``StationsMllwProduct.worker_args`` returning None *before* the worker runs;
rc 2 only covers the file vanishing in between, and the framework reports any
non-zero rc as a product failure.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from ..naming import stations_mllw_name

_MISSING = -99999.0

# Published verbatim when the factor table's header carries no "# source:"
# line -- true today only for SECOFS's CO-OPS-derived table. Kept as the
# unconditional default (rather than a templated string) so SECOFS's
# published attributes cannot drift by editing the template for another
# system; see _factor_comment/_global_comment below.
_DEFAULT_FACTOR_COMMENT = "MLLW minus xGEOID20B, from the CO-OPS datum table"
_DEFAULT_GLOBAL_COMMENT = (
    "Water level from the station product, shifted onto MLLW with "
    "the CO-OPS per-station datum factors. Only stations with a "
    "published factor appear here; the rest remain on model zero "
    "in the station product."
)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    source = Path(args.stations_nc)
    if not source.is_file():
        print(f"stations_mllw: source station file absent: {source}")
        return 2

    try:
        factors = _read_factors(Path(args.factors))
        provenance = _read_provenance(Path(args.factors))
        datum_note = _read_datum_note(Path(args.factors))
    except (OSError, ValueError) as exc:
        print(f"stations_mllw: unusable factor table {args.factors}: {exc}")
        return 5
    if not factors:
        print(f"stations_mllw: no stations in {args.factors}")
        return 5

    try:
        stations = _read_station_in(Path(args.station_in))
        _check_alignment(factors, stations)
    except (OSError, IndexError, ValueError) as exc:
        print(f"stations_mllw: {args.station_in}: {exc}")
        return 5

    out_path = Path(args.comout) / stations_mllw_name(
        args.prefix, args.cyc, args.pdy, args.phase
    )
    from ..worker_base import atomic_publish

    try:
        with atomic_publish(out_path) as tmp:
            n_time = _write(
                source, tmp, factors, stations, provenance, datum_note
            )
    except (OSError, KeyError, ValueError) as exc:
        print(f"stations_mllw: {source.name}: {exc}")
        return 5

    print(
        f"stations_mllw: {len(factors)} stations x {n_time} times "
        f"-> {out_path.name}"
    )
    if args.result_json:
        Path(args.result_json).write_text(
            json.dumps({"created": [str(out_path)]}, indent=2)
        )
    return 0


def _parse_args(argv: Optional[List[str]]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--stations-nc", required=True, help="the stations_nc output")
    p.add_argument("--comout", required=True)
    p.add_argument("--prefix", required=True)
    p.add_argument("--cyc", required=True)
    p.add_argument("--pdy", required=True)
    p.add_argument("--phase", required=True, help="nowcast | forecast")
    p.add_argument("--factors", required=True, help="MLLW datum fix table CSV")
    p.add_argument(
        "--station-in", required=True,
        help="station.in, checked against the factor table and read for coords",
    )
    p.add_argument("--result-json", default="")
    return p.parse_args(argv)


def _read_factors(path: Path) -> List[dict]:
    """Rows of the fix table, in station order. Comment lines are skipped.

    ``lon``/``lat`` are optional (SECOFS's table does not carry them; the
    AK generator does, since its labels need the coordinate fallback in
    ``_check_alignment`` below) and come back as ``None`` when absent.
    """
    lines = [
        ln for ln in path.read_text().splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]
    out = []
    for rec in csv.DictReader(lines):
        try:
            lon_raw = rec.get("lon")
            lat_raw = rec.get("lat")
            out.append(
                dict(
                    station_row=int(rec["station_row"]),
                    gauge_id=(rec.get("gauge_id") or "").strip(),
                    coops_code=(rec.get("coops_code") or "").strip(),
                    station_label=(rec.get("station_label") or "").strip(),
                    mllw_factor=float(rec["mllw_factor"]),
                    lon=float(lon_raw) if lon_raw not in (None, "") else None,
                    lat=float(lat_raw) if lat_raw not in (None, "") else None,
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"bad row {rec!r}: {exc}") from None
    # An empty label would make the alignment check below compare "" to ""
    # and pass for whatever station happens to occupy that row, which is the
    # one failure the check exists to prevent.
    blank = [r["station_row"] for r in out if not r["station_label"]]
    if blank:
        raise ValueError(
            f"station_label is empty for row(s) {blank}; the alignment check "
            "cannot verify those and would silently accept any station"
        )
    rows = [r["station_row"] for r in out]
    if len(set(rows)) != len(rows):
        dupes = sorted({r for r in rows if rows.count(r) > 1})
        raise ValueError(f"station_row repeated: {dupes}")
    return sorted(out, key=lambda r: r["station_row"])


def _read_header_field(path: Path, key: str) -> Optional[str]:
    """The optional ``# <key>: <text>`` header line, if the factor table
    carries one; ``None`` otherwise. Only scans the comment header --
    stops at the first non-comment, non-blank line, since data rows never
    start with '#'.
    """
    prefix = f"{key.lower()}:"
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped.startswith("#"):
            if stripped:
                break
            continue
        body = stripped.lstrip("#").strip()
        if body.lower().startswith(prefix):
            return body.split(":", 1)[1].strip()
    return None


def _read_provenance(path: Path) -> Optional[str]:
    """The optional ``# source: <text>`` header line, if the factor table
    carries one.

    SECOFS's CO-OPS-derived table does not carry this line, so callers get
    ``None`` and fall back to the hardcoded CO-OPS wording those published
    attributes have always had. Alaska's generated table does carry it
    (added by ``tools/gen_ak_datum_offsets.py``), since its factors come
    from coastalmodeling-vdatum, not a CO-OPS control file, and saying
    otherwise in a published netCDF attribute would be false provenance.
    """
    return _read_header_field(path, "source")


def _read_datum_note(path: Path) -> Optional[str]:
    """The optional ``# datum_note: <text>`` header line, if the factor
    table carries one.

    SECOFS's table does not carry this line, so callers get ``None`` and
    published attributes are unaffected. Alaska's generated table does
    (added by ``tools/gen_ak_datum_offsets.py``), because its premise --
    that model zero is xGEOID20B -- is a working assumption pending
    confirmation, not an established fact (see that module's docstring);
    publishing ``model_vertical_datum`` without that caveat would overstate
    it as settled.
    """
    return _read_header_field(path, "datum_note")


def _factor_comment(source: Optional[str]) -> str:
    if source:
        return f"MLLW minus xGEOID20B, from {source}"
    return _DEFAULT_FACTOR_COMMENT


def _global_comment(source: Optional[str]) -> str:
    if source:
        return (
            "Water level from the station product, shifted onto MLLW "
            f"with per-station datum factors from {source}. Only "
            "stations with a published factor appear here; the rest "
            "remain on model zero in the station product."
        )
    return _DEFAULT_GLOBAL_COMMENT


def _read_station_in(path: Path) -> List[dict]:
    """Station rows in file order, with the declared count enforced.

    Column 1 of station.in restarts per variable group and is not a station
    key; row order is what SCHISM writes the station dimension in.
    """
    lines = path.read_text().splitlines()
    declared = int(lines[1].split()[0])
    rows = []
    for line in lines[2:]:
        if not line.strip():
            continue
        head, _, comment = line.partition("!")
        parts = head.split()
        if len(parts) < 4:
            continue
        label = comment.split("!")[0].split("#")[0].split(":")[0].strip()
        rows.append(
            dict(
                row=len(rows) + 1,
                lon=float(parts[1]),
                lat=float(parts[2]),
                label=label,
            )
        )
    if len(rows) != declared:
        raise ValueError(
            f"{path}: header declares {declared} stations, found {len(rows)}"
        )
    return rows


#: 0.01 deg (~1.1 km at these latitudes) is generous rounding slack for two
#: values that describe the same model station node -- one written by
#: gen_ak_datum_offsets.py (signed longitude) and one read back here from
#: station.in (0-360; this domain straddles the dateline) -- while staying
#: far tighter than the tens-to-hundreds of km spacing between distinct AK
#: gauges, so an actual station.in reorder still trips it.
_ALIGNMENT_COORD_TOL_DEG = 0.01

_GAUGE_ID_RE = re.compile(r"\b(\d{7})\b")


def _wrapped_lon(lon: float) -> float:
    """Normalize to -180..180.

    Puts a 0-360 value (station.in's convention here, since this domain
    crosses the dateline) and a signed value (the factor table's, see
    ``gen_ak_datum_offsets.to_signed_lon``) that describe the same point
    on the same footing before they are compared.
    """
    return ((lon + 180.0) % 360.0) - 180.0


def _lon_delta(a: float, b: float) -> float:
    """Circular distance in degrees, so e.g. -179.99 and 179.99 read as
    0.02 deg apart rather than 359.98 -- this domain has stations on both
    sides of the antimeridian."""
    d = abs(_wrapped_lon(a) - _wrapped_lon(b))
    return min(d, 360.0 - d)


def _extract_gauge_id(rec: dict) -> str:
    """The CO-OPS gauge id for a factor row.

    Prefers the table's own ``gauge_id`` column; falls back to pulling it
    from ``station_label`` (the AK generator always embeds it there, e.g.
    "CO-OPS 9459450 AK Sand Point"). Requires exactly 7 digits -- CO-OPS's
    own station-id length -- so a stray number elsewhere in the label
    cannot be mistaken for it.
    """
    gid = (rec.get("gauge_id") or "").strip()
    if re.fullmatch(r"\d{7}", gid):
        return gid
    m = _GAUGE_ID_RE.search(rec.get("station_label") or "")
    return m.group(1) if m else ""


def _check_alignment(factors: List[dict], stations: List[dict]) -> None:
    """Fail loudly when the station list no longer matches the factor table.

    A station inserted or reordered in station.in shifts every row after it,
    which would apply each factor to the wrong gauge and publish a water
    level that looks entirely plausible. There is no way to detect that from
    the values, so it is checked here against what the table recorded.

    Exact label equality (ignoring case and hand annotations) is tried
    first and, when it holds, is trusted on its own -- this is SECOFS's
    path: its ctl file and its station.in both derive their labels from
    the same source and always agree verbatim, so this is the only path
    its real table ever takes.

    Alaska's labels never take that path: the generator writes "CO-OPS
    9459450 AK Sand Point" while the real station.in's own comment reads
    "[WL,T],9459450,CO-OPS,Sand Point" -- same station, unrelated wording,
    because Alaska's station.in was staged independently of this table
    rather than reconciled against it the way SECOFS's ctl file is (see
    ``tools/gen_ak_datum_offsets.py``). For that case the check falls back
    to two independent signals that must BOTH hold: the CO-OPS gauge id
    appears in the station.in comment text, and the model-node coordinates
    the table and station.in each carry for that row agree within
    ``_ALIGNMENT_COORD_TOL_DEG``. Either alone would be spoofable by a
    reorder that happens to preserve it (a reordered id could still land
    near its old coordinates, or vice versa); both together only hold when
    the row is genuinely the same station.
    """
    by_row = {s["row"]: s for s in stations}
    problems = []
    for rec in factors:
        station = by_row.get(rec["station_row"])
        if station is None:
            problems.append(
                f"row {rec['station_row']} ({rec['coops_code']}) is past the "
                f"end of the {len(stations)}-station list"
            )
            continue
        if _norm(station["label"]) == _norm(rec["station_label"]):
            continue

        gid = _extract_gauge_id(rec)
        if not gid or gid not in station["label"]:
            problems.append(
                f"row {rec['station_row']}: table says {rec['station_label']!r}, "
                f"station.in says {station['label']!r}"
            )
            continue

        rec_lon, rec_lat = rec.get("lon"), rec.get("lat")
        if rec_lon is None or rec_lat is None:
            problems.append(
                f"row {rec['station_row']}: labels disagree "
                f"({rec['station_label']!r} vs {station['label']!r}) and the "
                f"factor table carries no coordinates to confirm gauge id "
                f"{gid} against -- regenerate the table with a version of "
                "gen_ak_datum_offsets.py that writes lon/lat"
            )
            continue

        dlon = _lon_delta(station["lon"], rec_lon)
        dlat = abs(station["lat"] - rec_lat)
        if dlon > _ALIGNMENT_COORD_TOL_DEG or dlat > _ALIGNMENT_COORD_TOL_DEG:
            problems.append(
                f"row {rec['station_row']}: gauge id {gid} matches but "
                f"coordinates differ by ({dlon:.4f}, {dlat:.4f}) deg -- table "
                f"({rec_lon}, {rec_lat}) vs station.in "
                f"({station['lon']}, {station['lat']})"
            )
    if problems:
        raise ValueError(
            "factor table no longer matches station.in; regenerate it with "
            "nos_workflow.tools.build_mllw_table:\n  " + "\n  ".join(problems)
        )


def _norm(text: str) -> str:
    """Compare labels ignoring case and the hand annotations they collect."""
    return re.sub(r"[^a-z0-9]", "", text.split("#")[0].lower())


def _write(
    source: Path,
    out: Path,
    factors: List[dict],
    stations: List[dict],
    provenance: Optional[str] = None,
    datum_note: Optional[str] = None,
) -> int:
    import numpy as np
    from netCDF4 import Dataset

    labels = [r["station_label"] for r in factors]
    name_len = max(len(s) for s in labels) if labels else 1

    with Dataset(source, "r") as src:
        zeta = src.variables["zeta"]
        # Exactly 2-D, not just a (time, station) prefix: a third axis would
        # broadcast the per-station shift along it whenever its length
        # happened to equal the station count, applying a different factor
        # per level before failing anywhere obvious.
        if zeta.dimensions != ("time", "station"):
            raise ValueError(
                f"unexpected zeta dimensions {zeta.dimensions}, "
                "expected exactly (time, station)"
            )
        n_time = zeta.shape[0]
        n_station_src = zeta.shape[1]
        if n_station_src != len(stations):
            raise ValueError(
                f"{source.name} has {n_station_src} stations but "
                f"station.in declares {len(stations)}"
            )
        idx = [r["station_row"] - 1 for r in factors]
        _check_source_coords(src, idx, factors, stations, source.name)
        shift = np.asarray([r["mllw_factor"] for r in factors], dtype="f8")
        values, n_absent = _shifted(zeta, idx, shift)
        if n_absent == values.size:
            raise ValueError(
                "no usable water level in source zeta -- every value is "
                "absent or fill. The combine step warns and leaves zeta "
                "unwritten when staout_1 is missing; that is the likely cause"
            )
        if n_absent:
            print(
                f"stations_mllw: WARNING: {n_absent} of {values.size} source "
                "values absent or fill; written as _FillValue, not shifted"
            )

        src_time = src.variables["time"]
        time_units = getattr(src_time, "units", "")
        time_vals = np.asarray(src_time[:])

        with Dataset(out, "w", format="NETCDF4") as ds:
            ds.createDimension("time", None)
            ds.createDimension("station", len(factors))
            ds.createDimension("name_strlen", name_len)

            t = ds.createVariable("time", "f8", ("time",))
            if time_units:
                t.units = time_units
            for attr in ("standard_name", "long_name", "calendar", "base_date"):
                if hasattr(src_time, attr):
                    setattr(t, attr, getattr(src_time, attr))
            t[:] = time_vals

            z = ds.createVariable(
                "zeta_mllw", "f4", ("time", "station"),
                fill_value=_MISSING, zlib=True, complevel=4,
            )
            z.long_name = "water level above MLLW"
            z.standard_name = "sea surface height above mean lower low water"
            z.units = "meters"
            z.datum = "MLLW"
            z.comment = (
                "model water level on xGEOID20B plus the per-station "
                "mllw_factor of this file"
            )
            z[:] = values

            f = ds.createVariable("mllw_factor", "f8", ("station",))
            f.long_name = "datum factor added to model water level"
            f.units = "meters"
            f.comment = _factor_comment(provenance)
            f[:] = shift

            row = ds.createVariable("station_row", "i4", ("station",))
            row.long_name = "1-based row of this station in station.in"
            row.comment = (
                "the station dimension order SCHISM writes; station.in "
                "column 1 restarts per group and is not a station key"
            )
            row[:] = np.asarray([r["station_row"] for r in factors], dtype="i4")

            lon = ds.createVariable("lon", "f8", ("station",))
            lon.long_name = "station longitude"
            lon.units = "degrees_east"
            lon.standard_name = "longitude"
            lat = ds.createVariable("lat", "f8", ("station",))
            lat.long_name = "station latitude"
            lat.units = "degrees_north"
            lat.standard_name = "latitude"
            by_row = {s["row"]: s for s in stations}
            lon[:] = np.asarray(
                [by_row[r["station_row"]]["lon"] for r in factors], dtype="f8"
            )
            lat[:] = np.asarray(
                [by_row[r["station_row"]]["lat"] for r in factors], dtype="f8"
            )

            _write_strings(ds, "station_name", labels, name_len,
                           "station name from station.in")
            _write_strings(
                ds, "coops_code",
                [r["coops_code"] for r in factors], name_len,
                "CO-OPS four-character station code",
            )
            _write_strings(
                ds, "gauge_id", [r["gauge_id"] for r in factors], name_len,
                "NOS/USGS gauge identifier, empty when the station has none",
            )

            ds.title = "MLLW-referenced station water level"
            ds.source_file = source.name
            ds.datum = "MLLW"
            if datum_note:
                # The premise this shift rests on (model zero == xGEOID20B)
                # is an unconfirmed working assumption, not an established
                # fact -- see gen_ak_datum_offsets.py's docstring. Saying so
                # only where the factor table itself says so keeps SECOFS's
                # published attributes (no datum_note line) byte-identical.
                ds.model_vertical_datum = "xGEOID20B (provisional)"
                ds.datum_note = datum_note
            else:
                ds.model_vertical_datum = "xGEOID20B"
            ds.comment = _global_comment(provenance)
    return n_time


def _shifted(zeta, idx, shift):
    """``zeta[:, idx] + shift``, keeping absent values absent.

    netCDF4 hands back a masked array, and ``np.asarray`` on it silently
    returns the raw fill bytes -- so adding the factor to a gap yields a
    number like -99998.6 that no consumer can tell from a water level. Three
    kinds of absence are folded into one mask: the array's own (from
    ``_FillValue``/``missing_value``), non-finite values, and the netCDF
    type default fill that an unassigned variable carries, which is not
    always masked because no attribute advertises it.

    Returns the masked result and the number of absent elements, so the
    caller can refuse a source that is entirely fill.
    """
    import numpy as np

    raw = np.ma.asarray(zeta[:, idx], dtype="f8")
    data = np.ma.getdata(raw)
    absent = (
        np.ma.getmaskarray(raw)
        | ~np.isfinite(data)
        | (np.abs(data) > 1e20)
    )
    return np.ma.masked_array(data + shift[None, :], mask=absent), int(absent.sum())


def _check_source_coords(src, idx, factors, stations, source_name: str) -> None:
    """Confirm the source's own coordinates agree with station.in row order.

    The netCDF station dimension is written by a different parser than the
    one keying the factor table -- one numbers by physical file line, the
    other by accepted-row counter -- and the two are only *assumed* to
    agree. They both carry coordinates, so the assumption is checkable, and
    on the real pair it holds exactly (max difference 0.0 over 430 rows).
    Without this, a station.in line the two parsers disagree about shifts
    the mapping and every factor lands on the wrong gauge.

    Skipped, with a note, when the source carries no usable coordinates.
    """
    import numpy as np

    for lon_name, lat_name in (("lon", "lat"), ("x", "y")):
        if lon_name in src.variables and lat_name in src.variables:
            break
    else:
        print(
            f"stations_mllw: {source_name} carries no lon/lat; station "
            "alignment checked against station.in labels only"
        )
        return

    try:
        src_lon = np.asarray(src.variables[lon_name][:], dtype="f8")[idx]
        src_lat = np.asarray(src.variables[lat_name][:], dtype="f8")[idx]
    except (IndexError, ValueError) as exc:
        raise ValueError(
            f"{source_name}: cannot read {lon_name}/{lat_name} for the "
            f"mapped stations: {exc}"
        ) from None

    by_row = {s["row"]: s for s in stations}
    want_lon = np.asarray(
        [by_row[r["station_row"]]["lon"] for r in factors], dtype="f8"
    )
    want_lat = np.asarray(
        [by_row[r["station_row"]]["lat"] for r in factors], dtype="f8"
    )
    off = np.maximum(np.abs(src_lon - want_lon), np.abs(src_lat - want_lat))
    bad = np.nonzero(off > 1e-3)[0]
    if bad.size:
        worst = ", ".join(
            f"{factors[i]['coops_code']} (row {factors[i]['station_row']}) "
            f"off by {off[i]:.4f} deg"
            for i in bad[:5]
        )
        raise ValueError(
            f"{source_name}: station coordinates disagree with station.in for "
            f"{bad.size} of {len(idx)} mapped stations -- the station "
            f"dimension is not in station.in row order, so every factor would "
            f"be applied to the wrong gauge: {worst}"
        )


def _write_strings(
    ds, name: str, values: List[str], strlen: int, long_name: str
) -> None:
    """One char(station, name_strlen) variable, space-padded like ops.

    Space rather than NUL: netCDF4 returns NUL bytes as masked elements, so
    a zero-padded name reaches the reader as a masked array and the obvious
    way to decode it raises.
    """
    import numpy as np

    var = ds.createVariable(name, "S1", ("station", "name_strlen"))
    var.long_name = long_name
    padded = np.full((len(values), strlen), b" ", dtype="S1")
    for i, text in enumerate(values):
        for j, ch in enumerate(text[:strlen].encode("ascii", "replace")):
            padded[i, j] = bytes([ch])
    var[:] = padded


if __name__ == "__main__":
    sys.exit(main())
