#!/usr/bin/env python3
"""Anomaly-based ensemble bias correction for 2D barotropic members.

Combines a 3D deterministic solution with scaled 2D ensemble anomalies:

    WL_final(t) = WL_3d_det(t) + a_i * (WL_2d_member(t) - WL_2d_control(t))

where a_i is a per-station amplitude scaling factor derived from a training
period comparison of 2D control vs 3D deterministic.

The 3D deterministic carries the full baroclinic physics (mean SSH, density
currents, steric height). The 2D ensemble contributes only the spread
(perturbation anomalies), scaled to match the 3D amplitude response.

Training:
    - Compute a_i = std(WL_3d_det_demeaned) / std(WL_2d_ctl_demeaned)
    - For production: train on many past cycles, test on held-out cycles
    - For proof-of-concept: single cycle is acceptable

Usage:
    # Train: compute correction coefficients from one cycle
    python3 ensemble_bias_correct.py train \\
        --ctl-ncast <2d_control_nowcast_staout_1> \\
        --ctl-fcast <2d_control_forecast_staout_1> \\
        --det-ncast <3d_det_nowcast.nc> \\
        --det-fcast <3d_det_forecast.nc> \\
        --station-in <station.in> \\
        --nc-base 2026031806 --fc-base 2026031812 \\
        -o coefficients.json

    # Apply: correct ensemble member outputs
    python3 ensemble_bias_correct.py apply \\
        --coefficients coefficients.json \\
        --det-ncast <3d_det_nowcast.nc> \\
        --det-fcast <3d_det_forecast.nc> \\
        --ctl-ncast <2d_control_nowcast_staout_1> \\
        --ctl-fcast <2d_control_forecast_staout_1> \\
        --member-ncast <2d_member_nowcast_staout_1> \\
        --member-fcast <2d_member_forecast_staout_1> \\
        --nc-base 2026031806 --fc-base 2026031812 \\
        -o corrected_member_wl.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path

import numpy as np

# Optional netCDF4 import — only needed for 3D station .nc files
try:
    from netCDF4 import Dataset, num2date
    HAS_NC4 = True
except ImportError:
    HAS_NC4 = False


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def parse_station_in(path: Path) -> list[str]:
    """Parse station.in, return list of station labels."""
    labels = []
    with open(path) as f:
        f.readline()  # header
        nsta = int(f.readline().split()[0])
        for _ in range(nsta):
            line = f.readline().rstrip("\n")
            _, rhs = (line.split("!", 1) + [""])[:2]
            labels.append(rhs.strip().split(":")[0].strip() or f"sta_{len(labels)+1}")
    return labels


def read_staout(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Read SCHISM staout text file. Returns (time_seconds, values[time, station])."""
    data = np.loadtxt(path)
    return data[:, 0], data[:, 1:]


def combine_staout(
    ncast: Path, fcast: Path,
    nc_base: datetime, fc_base: datetime,
) -> tuple[list[datetime], np.ndarray]:
    """Combine nowcast + forecast staout files into single timeseries."""
    nt, nv = read_staout(ncast)
    ft, fv = read_staout(fcast)
    n_dates = [nc_base + timedelta(seconds=float(t)) for t in nt]
    f_dates = [fc_base + timedelta(seconds=float(t)) for t in ft]
    return n_dates + f_dates, np.vstack([nv, fv])


def read_3d_station_nc(path: Path) -> tuple[list[datetime], np.ndarray]:
    """Read 3D model station NetCDF. Returns (dates, zeta[time, station])."""
    if not HAS_NC4:
        raise ImportError("netCDF4 required for reading 3D station files")
    with Dataset(path) as ds:
        tv = ds.variables["time"]
        dates = [
            datetime(d.year, d.month, d.day, d.hour, d.minute, d.second)
            for d in num2date(tv[:], units=tv.units)
        ]
        zeta = np.ma.filled(ds.variables["zeta"][:], np.nan)
    return dates, np.asarray(zeta, dtype=float)


def combine_3d(
    ncast: Path, fcast: Path,
) -> tuple[list[datetime], np.ndarray]:
    """Combine nowcast + forecast 3D station NetCDF files."""
    nd, nv = read_3d_station_nc(ncast)
    fd, fv = read_3d_station_nc(fcast)
    return nd + fd, np.vstack([nv, fv])


def align_series(
    dates_a: list[datetime], vals_a: np.ndarray,
    dates_b: list[datetime], vals_b: np.ndarray,
) -> tuple[list[datetime], np.ndarray, np.ndarray]:
    """Align two timeseries by matching datetimes."""
    ma = {dt: i for i, dt in enumerate(dates_a)}
    mb = {dt: i for i, dt in enumerate(dates_b)}
    common = sorted(set(ma) & set(mb))
    ia = [ma[dt] for dt in common]
    ib = [mb[dt] for dt in common]
    return common, vals_a[ia, :], vals_b[ib, :]


def parse_datetime(s: str) -> datetime:
    """Parse YYYYMMDDHH string to datetime."""
    return datetime.strptime(s, "%Y%m%d%H")


# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------

def compute_coefficients(
    ctl_dates: list[datetime], ctl_wl: np.ndarray,
    det_dates: list[datetime], det_wl: np.ndarray,
    station_labels: list[str],
    amp_clip: tuple[float, float] = (0.1, 5.0),
    corr_floor: float = 0.3,
) -> list[dict]:
    """Compute per-station amplitude scaling from 2D control vs 3D det.

    a_i = std(det_demeaned_i) / std(ctl_demeaned_i)

    Clipped to [amp_clip[0], amp_clip[1]] to avoid blowup at weak-signal
    stations. If correlation < corr_floor, a_i is set to 1.0 (pass-through)
    to avoid scaling noise at stations where 2D and 3D are uncorrelated.

    Returns list of dicts with station label, a_i, and diagnostics.
    """
    common, ctl_a, det_a = align_series(ctl_dates, ctl_wl, det_dates, det_wl)
    nsta = min(ctl_a.shape[1], det_a.shape[1])

    coefficients = []
    for i in range(nsta):
        c = ctl_a[:, i]
        d = det_a[:, i]
        mask = np.isfinite(c) & np.isfinite(d)

        if mask.sum() < 4:
            coefficients.append({
                "station": station_labels[i] if i < len(station_labels) else f"sta_{i+1}",
                "a_i": 1.0,
                "ctl_std": 0.0,
                "det_std": 0.0,
                "ctl_mean": 0.0,
                "det_mean": 0.0,
                "corr": 0.0,
                "n_samples": int(mask.sum()),
                "clipped": False,
            })
            continue

        c_m = c[mask]
        d_m = d[mask]
        ctl_std = np.std(c_m - np.mean(c_m))
        det_std = np.std(d_m - np.mean(d_m))

        r = float(np.corrcoef(c_m - np.mean(c_m), d_m - np.mean(d_m))[0, 1])

        if ctl_std < 1e-6 or abs(r) < corr_floor:
            # Weak signal or uncorrelated: pass-through (scale=1.0)
            a_i = 1.0
            clipped = True
            gate_reason = "low_signal" if ctl_std < 1e-6 else "low_corr"
        else:
            a_i_raw = det_std / ctl_std
            a_i = float(np.clip(a_i_raw, amp_clip[0], amp_clip[1]))
            clipped = (a_i != a_i_raw)
            gate_reason = "clipped" if clipped else ""

        coefficients.append({
            "station": station_labels[i] if i < len(station_labels) else f"sta_{i+1}",
            "a_i": round(a_i, 6),
            "ctl_std": round(float(ctl_std), 6),
            "det_std": round(float(det_std), 6),
            "ctl_mean": round(float(np.mean(c_m)), 6),
            "det_mean": round(float(np.mean(d_m)), 6),
            "corr": round(r, 4),
            "n_samples": int(mask.sum()),
            "clipped": bool(clipped),
            "gate_reason": gate_reason,
        })

    return coefficients


def apply_correction(
    det_dates: list[datetime], det_wl: np.ndarray,
    ctl_dates: list[datetime], ctl_wl: np.ndarray,
    mem_dates: list[datetime], mem_wl: np.ndarray,
    coefficients: list[dict],
) -> tuple[list[datetime], np.ndarray]:
    """Apply anomaly-based correction to an ensemble member.

    WL_final(t) = WL_3d_det(t) + a_i * (WL_2d_member(t) - WL_2d_control(t))

    All three timeseries are aligned by datetime before correction.
    Station counts are validated across all inputs.
    """
    # Align det and ctl
    common_dc, det_a, ctl_a = align_series(det_dates, det_wl, ctl_dates, ctl_wl)
    # Align result with member
    map_dc = {dt: i for i, dt in enumerate(common_dc)}
    map_m = {dt: i for i, dt in enumerate(mem_dates)}
    common = sorted(set(map_dc) & set(map_m))
    idx_dc = [map_dc[dt] for dt in common]
    idx_m = [map_m[dt] for dt in common]

    det_aligned = det_a[idx_dc, :]
    ctl_aligned = ctl_a[idx_dc, :]
    mem_aligned = mem_wl[idx_m, :]

    # Validate station counts match
    n_det = det_aligned.shape[1]
    n_ctl = ctl_aligned.shape[1]
    n_mem = mem_aligned.shape[1]
    n_coeff = len(coefficients)

    if n_ctl != n_mem:
        raise ValueError(
            f"Station count mismatch: 2D control has {n_ctl} stations "
            f"but member has {n_mem}. All 2D runs must use the same station.in.")
    if n_det != n_coeff:
        raise ValueError(
            f"Station count mismatch: 3D det has {n_det} stations "
            f"but coefficients have {n_coeff}. "
            f"Were coefficients trained with a different station.in?")
    if n_ctl != n_det:
        raise ValueError(
            f"Station count mismatch: 2D has {n_ctl} stations "
            f"but 3D det has {n_det}. Check station.in consistency.")

    nsta = n_det
    corrected = np.full((len(common), nsta), np.nan)
    for i in range(nsta):
        a_i = coefficients[i]["a_i"]
        anomaly = mem_aligned[:, i] - ctl_aligned[:, i]
        corrected[:, i] = det_aligned[:, i] + a_i * anomaly

    return common, corrected


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cmd_train(args):
    """Train: compute correction coefficients."""
    nc_base = parse_datetime(args.nc_base)
    fc_base = parse_datetime(args.fc_base)
    labels = parse_station_in(Path(args.station_in))

    ctl_dates, ctl_wl = combine_staout(
        Path(args.ctl_ncast), Path(args.ctl_fcast), nc_base, fc_base)
    det_dates, det_wl = combine_3d(
        Path(args.det_ncast), Path(args.det_fcast))

    coeffs = compute_coefficients(ctl_dates, ctl_wl, det_dates, det_wl, labels,
                                  amp_clip=(args.amp_min, args.amp_max),
                                  corr_floor=args.corr_floor)

    # Summary
    a_vals = [c["a_i"] for c in coeffs]
    clipped = sum(1 for c in coeffs if c["clipped"])
    gated_corr = sum(1 for c in coeffs if c.get("gate_reason") == "low_corr")
    print(f"Computed {len(coeffs)} station coefficients")
    print(f"  a_i range: [{min(a_vals):.3f}, {max(a_vals):.3f}]")
    print(f"  a_i mean:  {np.mean(a_vals):.3f}")
    print(f"  Gated (corr<{args.corr_floor}): {gated_corr}/{len(coeffs)}")
    print(f"  Clipped:   {clipped}/{len(coeffs)}")

    # Show a few
    print(f"\n  {'Station':<30} {'a_i':>6} {'corr':>6} {'ctl_std':>8} {'det_std':>8}")
    print(f"  {'─'*25} {'─'*6} {'─'*6} {'─'*8} {'─'*8}")
    for c in coeffs[:20]:
        print(f"  {c['station']:<30} {c['a_i']:6.3f} {c['corr']:6.3f} "
              f"{c['ctl_std']:8.4f} {c['det_std']:8.4f}")
    if len(coeffs) > 20:
        print(f"  ... ({len(coeffs) - 20} more)")

    out = Path(args.output)
    with open(out, "w") as f:
        json.dump({"coefficients": coeffs,
                    "training": {
                        "nc_base": args.nc_base,
                        "fc_base": args.fc_base,
                        "amp_clip": [args.amp_min, args.amp_max],
                    }}, f, indent=2)
    print(f"\nSaved: {out}")


def cmd_apply(args):
    """Apply correction to an ensemble member."""
    nc_base = parse_datetime(args.nc_base)
    fc_base = parse_datetime(args.fc_base)

    with open(args.coefficients) as f:
        data = json.load(f)
    coeffs = data["coefficients"]

    det_dates, det_wl = combine_3d(
        Path(args.det_ncast), Path(args.det_fcast))
    ctl_dates, ctl_wl = combine_staout(
        Path(args.ctl_ncast), Path(args.ctl_fcast), nc_base, fc_base)
    mem_dates, mem_wl = combine_staout(
        Path(args.member_ncast), Path(args.member_fcast), nc_base, fc_base)

    common, corrected = apply_correction(
        det_dates, det_wl, ctl_dates, ctl_wl, mem_dates, mem_wl, coeffs)

    # Write CSV with proper quoting for station names containing commas
    out = Path(args.output)
    nsta = corrected.shape[1]
    with open(out, "w", newline="") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(["datetime"] + [c["station"] for c in coeffs[:nsta]])
        for i, dt in enumerate(common):
            row = [dt.strftime("%Y-%m-%d %H:%M:%S")]
            row.extend(f"{corrected[i, j]:.6f}" for j in range(nsta))
            writer.writerow(row)

    print(f"Corrected {nsta} stations, {len(common)} timesteps → {out}")


def main():
    parser = argparse.ArgumentParser(
        description="Anomaly-based ensemble bias correction (2D→3D)")
    sub = parser.add_subparsers(dest="command")

    # Train
    p_train = sub.add_parser("train", help="Compute correction coefficients")
    p_train.add_argument("--ctl-ncast", required=True, help="2D control nowcast staout_1")
    p_train.add_argument("--ctl-fcast", required=True, help="2D control forecast staout_1")
    p_train.add_argument("--det-ncast", required=True, help="3D det nowcast station .nc")
    p_train.add_argument("--det-fcast", required=True, help="3D det forecast station .nc")
    p_train.add_argument("--station-in", required=True, help="station.in file")
    p_train.add_argument("--nc-base", required=True, help="Nowcast base time (YYYYMMDDHH)")
    p_train.add_argument("--fc-base", required=True, help="Forecast base time (YYYYMMDDHH)")
    p_train.add_argument("--amp-min", type=float, default=0.1, help="Min a_i clip (default 0.1)")
    p_train.add_argument("--amp-max", type=float, default=5.0, help="Max a_i clip (default 5.0)")
    p_train.add_argument("--corr-floor", type=float, default=0.3,
                        help="Min correlation to fit a_i; below this, a_i=1.0 (default 0.3)")
    p_train.add_argument("-o", "--output", default="bias_coefficients.json")

    # Apply
    p_apply = sub.add_parser("apply", help="Apply correction to ensemble member")
    p_apply.add_argument("--coefficients", required=True, help="coefficients.json from train")
    p_apply.add_argument("--det-ncast", required=True, help="3D det nowcast station .nc")
    p_apply.add_argument("--det-fcast", required=True, help="3D det forecast station .nc")
    p_apply.add_argument("--ctl-ncast", required=True, help="2D control nowcast staout_1")
    p_apply.add_argument("--ctl-fcast", required=True, help="2D control forecast staout_1")
    p_apply.add_argument("--member-ncast", required=True, help="2D member nowcast staout_1")
    p_apply.add_argument("--member-fcast", required=True, help="2D member forecast staout_1")
    p_apply.add_argument("--nc-base", required=True, help="Nowcast base time (YYYYMMDDHH)")
    p_apply.add_argument("--fc-base", required=True, help="Forecast base time (YYYYMMDDHH)")
    p_apply.add_argument("-o", "--output", default="corrected_wl.csv")

    args = parser.parse_args()
    if args.command == "train":
        cmd_train(args)
    elif args.command == "apply":
        cmd_apply(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
