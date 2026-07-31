"""Build the MLLW datum-factor fix table from the CO-OPS control file.

The per-station MLLW factors are not a WCOSS2 artifact: they live in the
CO-OPS IDL plotting control file ``plot_timeseries_wl.ctl``, which is
shared across OFS and also lists current stations. This tool reconciles
that file against a system's ``station.in`` and emits the fix table the
``stations_mllw`` post product reads.

Run it when the control file or the station list changes; commit the
result. It is not called at runtime -- post reads the emitted CSV.

    python3 -m nos_workflow.tools.build_mllw_table \
        --ctl plot_timeseries_wl.ctl \
        --station-in fix/secofs_ufs/secofs_ufs.station.in \
        --out fix/secofs_ufs/secofs_ufs.mllw_datum.csv \
        [--coops-log get_nwlon_obs.log]

Two things this guards against, both of which produce a plausible-looking
wrong water level rather than an error:

*Row keying.* ``station.in``'s first column is a within-group counter that
restarts (430 rows, 134 distinct values on SECOFS), so it cannot identify a
station. SCHISM writes the station dimension in file row order, so row order
is the only valid key and is what the table stores.

*Target selection.* ``plot_timeseries_wl.ctl`` also lists current stations,
which appear in ``station.in`` at depth != 0 under the same four-character
codes. An unconstrained nearest-neighbour join sends several water level
factors to a current station and leaves the real gauge without one, so
candidates are restricted to depth == 0 rows and every match must be
corroborated by gauge id, code, or name -- coordinates alone only inside
1 km.

With ``--coops-log``, the ``StationNames <id> : <code> : "<label>"`` lines of
an operational observation-fetch log are used as the authoritative
id-to-code table and any disagreement is reported.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from math import cos, radians
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_ST_RE = re.compile(
    r"^ST\s*=\s*'([^']*)'\s+'([^']*)'\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+(.*)$"
)
_ID_RE = re.compile(r"\((\d{6,8})\)")
_AUTH_RE = re.compile(r'^StationNames\s+(\S+)\s*:\s*(\S+)\s*:\s*"([^"]*)"', re.M)

#: Coordinates alone are accepted as evidence only inside this radius.
COORD_TOL_KM = 1.0


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.split("(")[0].lower())


def _clean_label(comment: str) -> str:
    """Station name from a station.in comment, without its annotations.

    Hand annotations arrive three ways -- ``: NOAA elev gauges`` after the
    first station of a block, ``!! machuan revised`` after a second bang, and
    ``## machuan changed`` -- and none of them are part of the name. The
    ``#`` forms matter beyond tidiness: this label is written into a CSV
    whose own comment character is ``#``.
    """
    return comment.split("!")[0].split("#")[0].split(":")[0].strip()


def _km(alat: float, alon: float, blat: float, blon: float) -> float:
    dy = (alat - blat) * 111.32
    dx = (alon - blon) * 111.32 * cos(radians((alat + blat) / 2.0))
    return (dx * dx + dy * dy) ** 0.5


def read_ctl(path: Path) -> List[dict]:
    """Active ``ST=`` entries. Commented-out ``%ST=`` lines are excluded."""
    out = []
    for lineno, line in enumerate(path.read_text().splitlines(), 1):
        m = _ST_RE.match(line.strip())
        if not m:
            continue
        label, code, lat, lon, factor, _flags = m.groups()
        gid = _ID_RE.search(label)
        out.append(
            dict(
                lineno=lineno,
                label=label.strip(),
                code=code.strip().lower(),
                lat=float(lat),
                lon=float(lon),
                factor=float(factor),
                gid=gid.group(1) if gid else None,
                name=_norm(label),
            )
        )
    return out


def read_station_in(path: Path) -> List[dict]:
    """Station rows in file order. Column 1 is read but never used as a key."""
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
        label = _clean_label(comment)
        gid = _ID_RE.search(label)
        rows.append(
            dict(
                row=len(rows) + 1,
                lon=float(parts[1]),
                lat=float(parts[2]),
                depth=float(parts[3]),
                label=label,
                gid=gid.group(1) if gid else None,
                name=_norm(label),
                bare=re.sub(r"[^A-Za-z0-9]", "", label).lower(),
            )
        )
    if len(rows) != declared:
        raise ValueError(
            f"{path}: header declares {declared} stations, found {len(rows)}"
        )
    return rows


def _sole(matches: List[dict]) -> Optional[dict]:
    return matches[0] if len(matches) == 1 else None


def reconcile(
    ctl: List[dict], stations: List[dict]
) -> Tuple[List[dict], List[dict], List[dict]]:
    """Return (mapped, unmatched, conflicts).

    ``mapped`` holds one record per accepted ctl entry, several of which may
    target the same row; :func:`pick_per_row` applies the tie-break.
    """
    wl = [s for s in stations if s["depth"] == 0.0]
    if not wl:
        raise ValueError(
            "no depth==0 rows in the station list, so there is nothing a "
            "water level datum could apply to"
        )
    mapped, unmatched, conflicts = [], [], []
    for entry in ctl:
        evidence: Dict[str, dict] = {}
        if entry["gid"]:
            hit = _sole([s for s in wl if s["gid"] == entry["gid"]])
            if hit:
                evidence["gid"] = hit
        hit = _sole([s for s in wl if s["bare"] == entry["code"]])
        if hit:
            evidence["code"] = hit
        if entry["name"]:
            hit = _sole([s for s in wl if s["name"] == entry["name"]])
            if hit:
                evidence["name"] = hit
        nearest = min(wl, key=lambda s: _km(entry["lat"], entry["lon"], s["lat"], s["lon"]))
        if _km(entry["lat"], entry["lon"], nearest["lat"], nearest["lon"]) < COORD_TOL_KM:
            evidence["coord"] = nearest

        targets = {s["row"] for s in evidence.values()}
        if len(targets) > 1:
            conflicts.append((entry, evidence))
        elif not targets:
            unmatched.append(entry)
        else:
            station = next(iter(evidence.values()))
            mapped.append(
                dict(
                    station_row=station["row"],
                    # A few ctl labels carry no id (``ST='Windmill'``) even
                    # though station.in names the gauge; prefer the ctl but
                    # fall back rather than publish a blank.
                    gauge_id=entry["gid"] or station["gid"] or "",
                    coops_code=entry["code"],
                    station_label=station["label"],
                    mllw_factor=entry["factor"],
                    sep_km=round(
                        _km(entry["lat"], entry["lon"], station["lat"], station["lon"]), 3
                    ),
                    evidence="+".join(sorted(evidence)),
                )
            )
    return mapped, unmatched, conflicts


def pick_per_row(mapped: List[dict]) -> Tuple[List[dict], List[str]]:
    """One factor per station row, preferring a gauge-id match, then distance.

    Several ctl entries can sit near one model station -- distinct physical
    sites that the model samples at a single node. Only the entry that
    identifies the *gauge* should set its datum; the others describe places
    we have no output for.
    """
    by_row: Dict[int, List[dict]] = {}
    for rec in mapped:
        by_row.setdefault(rec["station_row"], []).append(rec)

    chosen, notes = [], []
    for row, recs in sorted(by_row.items()):
        best = sorted(
            recs, key=lambda r: (0 if "gid" in r["evidence"] else 1, r["sep_km"])
        )[0]
        chosen.append(best)
        if len(recs) > 1:
            others = ", ".join(
                f"{r['coops_code']}({r['mllw_factor']:.3f})"
                for r in recs
                if r is not best
            )
            differ = len({r["mllw_factor"] for r in recs}) > 1
            notes.append(
                f"row {row} {best['station_label']}: kept "
                f"{best['coops_code']}({best['mllw_factor']:.3f}), dropped {others}"
                + ("  [factors differed]" if differ else "")
            )
    return chosen, notes


def verify_against_coops(chosen: List[dict], log: Path) -> List[str]:
    """Check code and gauge id against an ops observation-fetch log."""
    auth = {
        code.lower(): (sid, label)
        for sid, code, label in _AUTH_RE.findall(log.read_text())
    }
    if not auth:
        return [f"{log}: no StationNames lines found"]
    problems = []
    for rec in chosen:
        entry = auth.get(rec["coops_code"])
        if entry is None:
            problems.append(
                f"{rec['coops_code']}: absent from the CO-OPS station table"
            )
            continue
        sid, label = entry
        if rec["gauge_id"] and rec["gauge_id"] != sid:
            problems.append(
                f"{rec['coops_code']}: CO-OPS says gauge {sid} ({label}), "
                f"table says {rec['gauge_id']}"
            )
    return problems


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ctl", required=True, type=Path)
    ap.add_argument("--station-in", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument(
        "--coops-log",
        type=Path,
        default=None,
        help="ops observation-fetch log, used as the authoritative id/code table",
    )
    args = ap.parse_args(argv)

    ctl = read_ctl(args.ctl)
    stations = read_station_in(args.station_in)
    wl_rows = [s for s in stations if s["depth"] == 0.0]
    print(f"ctl active entries      : {len(ctl)}")
    print(f"station.in rows         : {len(stations)} (depth==0: {len(wl_rows)})")

    mapped, unmatched, conflicts = reconcile(ctl, stations)
    if conflicts:
        print(f"\nERROR: {len(conflicts)} ctl entries match more than one station:")
        for entry, evidence in conflicts:
            detail = " ".join(f"{k}=row{v['row']}" for k, v in sorted(evidence.items()))
            print(f"  ctl:{entry['lineno']} {entry['label']} [{detail}]")
        return 1

    chosen, notes = pick_per_row(mapped)
    print(f"ctl entries matched     : {len(mapped)}")
    print(f"station rows with factor: {len(chosen)} of {len(wl_rows)}")
    print(f"ctl entries not a WL station here: {len(unmatched)}")
    for note in notes:
        print(f"  tie-break: {note}")

    uncovered = [s for s in wl_rows if s["row"] not in {c["station_row"] for c in chosen}]
    for station in uncovered:
        print(f"  no factor: row {station['row']} {station['label']}")

    if args.coops_log:
        problems = verify_against_coops(chosen, args.coops_log)
        print(f"\nCO-OPS cross-check: {len(problems)} disagreement(s)")
        for problem in problems:
            print(f"  {problem}")
        if problems:
            return 1

    # The runtime guard verifies each row against this label, and an empty one
    # would make that comparison vacuously true for any station.
    blank = [c["station_row"] for c in chosen if not c["station_label"]]
    if blank:
        print(
            f"\nERROR: station.in row(s) {blank} have no name comment, so the "
            "emitted table could not be checked against the station list at "
            "runtime. Name them in station.in and rerun."
        )
        return 1

    factors = sorted(c["mllw_factor"] for c in chosen)
    print(
        f"\nfactors {factors[0]:.3f} .. {factors[-1]:.3f} "
        f"median {factors[len(factors) // 2]:.3f}"
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fields = ["station_row", "gauge_id", "coops_code", "station_label", "mllw_factor"]
    with args.out.open("w", newline="") as fh:
        fh.write(
            "# MLLW datum factors, added to model water level (xGEOID20B) to\n"
            "# reference it to MLLW. Generated by nos_workflow.tools.build_mllw_table\n"
            "# from the CO-OPS plot_timeseries_wl.ctl; do not hand-edit.\n"
            "# station_row is the 1-based row order of station.in, which is the\n"
            "# station dimension order SCHISM writes. Column 1 of station.in is a\n"
            "# per-group counter and is NOT a station key.\n"
        )
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for rec in chosen:
            writer.writerow(rec)
    print(f"wrote {args.out} ({len(chosen)} stations)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
