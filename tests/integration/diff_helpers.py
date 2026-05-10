"""Shared diff helpers for stage-artifact parity tests.

Both ``test_prep_artifact_parity.py`` and ``test_post_artifact_parity.py``
diff COMOUT trees the same way: text artifacts must be byte-equal,
NetCDF artifacts must be ``numpy.allclose(rtol=1e-12)`` variable-by-
variable, and log files are size-only (timestamps + jobids differ
between runs).

Factoring these helpers out lets a third stage parity test (forecast,
post-2, …) drop in without re-inventing the diff machinery. The public
API stayed the same when this module was extracted from
``test_prep_artifact_parity.py`` in commit 5 of #219, so the prep test
continues to pass unchanged.

Public surface
--------------
- ``sha256(path)`` — stream-hash a file
- ``classify(name)`` — bucket a filename into text/netcdf/log/other
- ``walk_relative(root)`` — sorted list of files relative to ``root``
- ``diff_netcdf(a, b, rtol)`` — in-process NetCDF allclose diff
- ``text_diff_snippet(a, b, max_lines)`` — preview first diverging lines
- ``format_failure(headline, details)`` — structured pytest.fail message
- ``git_short_sha(repo)`` — short HEAD sha for manifest provenance
- ``build_manifest_entries(comout)`` — manifest entry list from a COMOUT
- ``assert_against_manifest(comout, mpath, stage)`` — manifest gate
- Constants: ``NETCDF_RTOL``, ``SIZE_TOLERANCE_PCT``,
  ``TEXT_ARTIFACT_PATTERNS``, ``LOG_PATTERNS``, ``NETCDF_PATTERN``

The ``stage`` argument on ``format_failure`` / ``assert_against_manifest``
controls the failure marker so the same helper can serve as both
``PREP_PARITY FAIL`` and ``POST_PARITY FAIL`` — operators grep CI logs
for those markers.
"""
from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from fnmatch import fnmatch
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pytest


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants — file-classification rules
# ---------------------------------------------------------------------------

# Text artifacts that must be byte-equal across paths. Globbed because
# the actual basename is prefixed with ``<ofs>.t<cyc>z.<pdy>.`` in
# COMOUT (e.g. ``secofs.t18z.20260324.bctides.in.nowcast``). Patterns
# cover both prep-stage products (bctides, vsource, param, …) and
# post-stage products (CSV bias outputs, station.in, control files).
TEXT_ARTIFACT_PATTERNS = (
    # prep-stage artifacts
    "*.bctides.in",
    "*.bctides.in.nowcast",
    "*.bctides.in.forecast",
    "*vsource.th*",
    "*vsink.th*",
    "*msource.th*",
    "*source_sink.in*",
    "*param.nml*",
    "*staout_*",
    "*.nowcast.in",
    "*.forecast.in",
    "*.combine.*.in",
    "base_date.*",
    "sflux_inputs.txt",
    "time_hotstart.*",
    "time_nowcastend.*",
    "time_forecastend.*",
    "*emailbody",
    "met_files_existed_*",
    "met_files_used_*",
    # post-stage artifacts
    "*.csv",
    "bias_coefficients.json",
    "schism_standard_output.ctl",
    "*.station.lat.lon",
    "*.station.in",
    "*.shef",
    "*.shef.txt",
    "*.awips*",
    "*.awips.txt",
    "corrected_wl.csv",
)

# Log files — content varies by timestamp / jobid; we confirm presence
# (set-match), not content.
LOG_PATTERNS = (
    "*jlogfile*",
    "*.jlogfile.log",
    "*.corms.log",
    "*_Fortran.t*.log",
    "*Fortran_*.t*.log",
    "*.tar",  # tar timestamps differ; spot-check size only
    # post-stage logs (size-only)
    "*post*.log",
    "OUTPUT.*",
    "pgmout.*",
)

# NetCDF artifacts — diff via netCDF4 (allclose); the file may be huge.
NETCDF_PATTERN = "*.nc"

# Size tolerance for manifest match (text files exact; nc + tar within %).
SIZE_TOLERANCE_PCT = 5.0

# rtol for NetCDF allclose — matches the #219 validation gate spec.
NETCDF_RTOL = 1e-12


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def sha256(p: Path) -> str:
    """Stream-hash a file. Used for text artifacts in the manifest."""
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _matches_any(name: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch(name, pat) for pat in patterns)


def classify(name: str) -> str:
    """Return one of ``text``, ``netcdf``, ``log``, ``other``.

    Order matters: log patterns shadow text/netcdf because some logs
    are ``.tar`` (would otherwise match ``other``) or ``.log`` (would
    otherwise match nothing).
    """
    if _matches_any(name, LOG_PATTERNS):
        return "log"
    if _matches_any(name, (NETCDF_PATTERN,)):
        return "netcdf"
    if _matches_any(name, TEXT_ARTIFACT_PATTERNS):
        return "text"
    return "other"


def walk_relative(root: Path) -> List[Path]:
    """Sorted list of files relative to root (no dirs, no symlinks-to-dir)."""
    out: List[Path] = []
    for p in root.rglob("*"):
        if p.is_file():
            out.append(p.relative_to(root))
    out.sort()
    return out


def diff_netcdf(a: Path, b: Path, rtol: float = NETCDF_RTOL) -> Optional[str]:
    """Compare two NetCDF files variable-by-variable.

    Returns ``None`` on agreement, a human-readable message on first
    mismatch. The helper uses netCDF4 (already in the SECOFS image and
    in CI deps) so we don't depend on an external ``nccmp`` binary.
    """
    try:
        import netCDF4  # type: ignore[import-not-found]
        import numpy as np
    except ImportError as exc:
        return f"netCDF4/numpy not importable: {exc}"

    try:
        ds_a = netCDF4.Dataset(str(a), "r")
        ds_b = netCDF4.Dataset(str(b), "r")
    except OSError as exc:
        return f"failed to open NetCDF: {exc}"

    try:
        keys_a = set(ds_a.variables.keys())
        keys_b = set(ds_b.variables.keys())
        if keys_a != keys_b:
            return (
                f"variable set differs: only-in-A={sorted(keys_a - keys_b)} "
                f"only-in-B={sorted(keys_b - keys_a)}"
            )
        for name in sorted(keys_a):
            va = ds_a.variables[name][:]
            vb = ds_b.variables[name][:]
            if va.shape != vb.shape:
                return f"var {name!r}: shape differs {va.shape} vs {vb.shape}"
            try:
                # allclose handles masked arrays and bool/int promotion
                if not np.allclose(va, vb, rtol=rtol, atol=0.0, equal_nan=True):
                    diff = np.abs(np.asarray(va) - np.asarray(vb))
                    return (
                        f"var {name!r}: allclose failed "
                        f"(max-abs-diff={diff.max():.3e}, rtol={rtol:.0e})"
                    )
            except TypeError:
                # Non-numeric (e.g. char) — fall back to exact equality.
                if not (va == vb).all():
                    return f"var {name!r}: char/byte content differs"
    finally:
        ds_a.close()
        ds_b.close()
    return None


def text_diff_snippet(a: Path, b: Path, max_lines: int = 6) -> str:
    """Return a tiny preview of the first few diverging lines."""
    try:
        with a.open("rb") as fh_a, b.open("rb") as fh_b:
            la = fh_a.read(8192).splitlines()
            lb = fh_b.read(8192).splitlines()
    except OSError as exc:
        return f"could not read: {exc}"
    out: List[str] = []
    for i, (line_a, line_b) in enumerate(zip(la, lb)):
        if line_a != line_b:
            out.append(f"line {i + 1}: A={line_a!r}")
            out.append(f"           B={line_b!r}")
            if len(out) >= max_lines * 2:
                break
    if not out and len(la) != len(lb):
        out.append(f"line count differs: A={len(la)} vs B={len(lb)}")
    return " | ".join(out) or "(content differs but no in-prefix line diff)"


def format_failure(
    headline: str,
    details: Optional[Dict] = None,
    *,
    stage: str = "prep",
) -> str:
    """Structured one-liner + indented payload for ``pytest.fail`` messages.

    The marker is ``<STAGE>_PARITY FAIL`` so CI log scrapers can grep for
    a stable string regardless of which stage failed.
    """
    marker = f"{stage.upper()}_PARITY FAIL"
    summary = f"{marker}: {headline}"
    if not details:
        return summary
    body = json.dumps(details, indent=2, sort_keys=True)
    return f"{summary}\n{body}"


def git_short_sha(repo: Path) -> str:
    """Return the short sha at HEAD, or 'unknown' if git is unavailable."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        pass
    return "unknown"


def build_manifest_entries(comout: Path) -> List[Dict]:
    """Build a sorted list of manifest entries from a COMOUT dir."""
    entries: List[Dict] = []
    for rel in walk_relative(comout):
        abs_p = comout / rel
        mode = classify(rel.name)
        entry = {
            "path": str(rel),
            "size": abs_p.stat().st_size,
            "mode": mode,
        }
        if mode == "text":
            entry["sha256"] = sha256(abs_p)
        entries.append(entry)
    entries.sort(key=lambda e: e["path"])
    return entries


def assert_against_manifest(
    comout: Path,
    mpath: Path,
    *,
    stage: str = "prep",
) -> None:
    """Assert the COMOUT matches the checked-in manifest.

    Stage-keyed failure marker keeps the prep parity test's behavior
    identical (``PREP_PARITY FAIL``) while letting post / forecast
    tests surface ``POST_PARITY FAIL`` etc.
    """
    with mpath.open("r") as fh:
        manifest = json.load(fh)
    by_path = {e["path"]: e for e in manifest["files"]}
    present = {str(p): comout / p for p in walk_relative(comout)}

    missing = sorted(set(by_path) - set(present))
    if missing:
        pytest.fail(format_failure(
            "files listed in manifest but missing from Python-path COMOUT",
            details={"missing": missing[:20]},
            stage=stage,
        ))

    # New (unmanifested) files are not necessarily a failure — but they
    # are a signal that the manifest is stale. Warn loudly.
    extra = sorted(set(present) - set(by_path))
    if extra:
        log.warning(
            "Python-path produced %d files not in manifest "
            "(consider REGENERATE=1): %s",
            len(extra),
            extra[:10],
        )

    # For text artifacts, sha256 must match exactly.
    sha_failures: List[str] = []
    size_failures: List[str] = []
    for path, entry in by_path.items():
        abs_p = present.get(path)
        if abs_p is None:
            continue  # already counted in missing
        size_actual = abs_p.stat().st_size
        size_expected = entry["size"]
        if entry["mode"] == "text":
            actual_sha = sha256(abs_p)
            if actual_sha != entry.get("sha256"):
                sha_failures.append(
                    f"{path}: sha256 expected={entry.get('sha256')} "
                    f"actual={actual_sha}"
                )
        # Size within tolerance for all modes.
        if size_expected == 0 and size_actual == 0:
            continue
        denom = max(size_expected, size_actual, 1)
        diff_pct = abs(size_expected - size_actual) / denom * 100.0
        if diff_pct > SIZE_TOLERANCE_PCT:
            size_failures.append(
                f"{path}: size expected={size_expected} actual={size_actual} "
                f"({diff_pct:.1f}% diff)"
            )

    if sha_failures or size_failures:
        pytest.fail(format_failure(
            "manifest divergence",
            details={"sha256": sha_failures[:20], "size": size_failures[:20]},
            stage=stage,
        ))


__all__ = [
    "NETCDF_PATTERN",
    "NETCDF_RTOL",
    "SIZE_TOLERANCE_PCT",
    "TEXT_ARTIFACT_PATTERNS",
    "LOG_PATTERNS",
    "sha256",
    "classify",
    "walk_relative",
    "diff_netcdf",
    "text_diff_snippet",
    "format_failure",
    "git_short_sha",
    "build_manifest_entries",
    "assert_against_manifest",
]
