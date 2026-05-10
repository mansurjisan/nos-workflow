"""Prep-stage artifact parity: nos_workflow Python vs preserved legacy shell.

Goal (per #219, commit 4): prove that ``python -m nos_workflow run prep``
produces the *same* artifacts the pre-migration shell produced. Per the
philosophy doc (#220), side-by-side diffs are first-class operational
artifacts — bake the check into CI now while the migration is fresh.

How it works
------------
1. The test fires up the SECOFS-UFS Docker container twice for the same
   PDY/cyc, with the working tree (``ush/python/``, ``scripts/``,
   ``jobs/``) bind-mounted on top of ``/opt/nosofs/``:

     * Run A — Python path: ``NOS_USE_LEGACY_SHELL=NO``  (default)
     * Run B — Legacy path: ``NOS_USE_LEGACY_SHELL=YES``

   Both runs use the same staging dir (``/mnt/d/secofs_docker_data``)
   for inputs and write to host-side COMOUT roots inside ``tmp_path``.

2. The test diffs the two COMOUT trees:

     * Filename set: ``find ... -type f | sort`` symmetric difference
       must be empty.
     * Text artifacts (``vsource.th``, ``param.nml``, ``staout_*``,
       ``bctides.in``, ``source_sink.in``, ``msource.th``,
       ``vsink.th``): ``filecmp.cmp(shallow=False)`` byte-equal.
     * NetCDF artifacts (anything matching ``*.nc``): a small in-process
       helper using ``netCDF4.Dataset`` walks variables and asserts
       ``np.allclose(..., rtol=1e-12)``. ``nccmp`` is *not* shipped in
       the SECOFS-UFS image so we don't shell out to it.
     * Log files (jlogfile, corms.log, *_Fortran.t*.log,
       met_files_used_*): timestamps + jobids vary by run; we tolerate
       structural diffs there but still confirm presence.

3. The test also enforces a golden manifest (checked-in JSON at
   ``golden_manifests/secofs_ufs_prep_<pdy>_<cyc>z.json``). The
   manifest pins the expected file set, sizes (within tolerance), and
   sha256 of text artifacts. NetCDF sha256 is not pinned — bit-for-bit
   determinism through netCDF4 / HDF5 isn't promised across runs, so we
   rely on the variable-by-variable allclose diff for those.

Bootstrap mode
--------------
The very first run (or any time the prep output changes by design)
needs a fresh manifest. Invoke with::

    REGENERATE=1 pytest tests/integration/test_prep_artifact_parity.py

That writes a fresh manifest from the Python-path COMOUT and skips the
parity assertion. The next plain ``pytest`` run loads it and asserts.

Skip behavior
-------------
If the Docker image / staging dir aren't available (the common case on
hosted CI runners) the integration tests skip cleanly via the
``integration_preflight`` fixture in ``conftest.py``. The hosted CI
runner still validates the *manifest* shape via
``test_golden_manifest_well_formed`` — see
``.github/workflows/prep_parity.yml``.
"""
from __future__ import annotations

import filecmp
import hashlib
import json
import logging
import os
import re
import subprocess
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pytest


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants — file-classification rules
# ---------------------------------------------------------------------------

# Text artifacts that must be byte-equal across paths. Globbed because
# the actual basename is prefixed with ``<ofs>.t<cyc>z.<pdy>.`` in
# COMOUT (e.g. ``secofs.t18z.20260324.bctides.in.nowcast``).
TEXT_ARTIFACT_PATTERNS = (
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
)

# NetCDF artifacts — diff via netCDF4 (allclose); the file may be huge.
NETCDF_PATTERN = "*.nc"

# Size tolerance for manifest match (text files exact; nc + tar within %).
SIZE_TOLERANCE_PCT = 5.0

# rtol for NetCDF allclose — matches the #219 validation gate spec.
NETCDF_RTOL = 1e-12


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256(p: Path) -> str:
    """Stream-hash a file. Used for text artifacts in the manifest."""
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _matches_any(name: str, patterns: Iterable[str]) -> bool:
    from fnmatch import fnmatch
    return any(fnmatch(name, pat) for pat in patterns)


def _classify(name: str) -> str:
    """Return one of ``text``, ``netcdf``, ``log``, ``other``."""
    if _matches_any(name, LOG_PATTERNS):
        return "log"
    if _matches_any(name, (NETCDF_PATTERN,)):
        return "netcdf"
    if _matches_any(name, TEXT_ARTIFACT_PATTERNS):
        return "text"
    return "other"


def _walk_relative(root: Path) -> List[Path]:
    """Sorted list of files relative to root (no dirs, no symlinks-to-dir)."""
    out: List[Path] = []
    for p in root.rglob("*"):
        if p.is_file():
            out.append(p.relative_to(root))
    out.sort()
    return out


def _diff_netcdf(a: Path, b: Path, rtol: float = NETCDF_RTOL) -> Optional[str]:
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


# ---------------------------------------------------------------------------
# Docker driver
# ---------------------------------------------------------------------------

# The bind-mounted overlay maps the working tree onto WCOSS2-mirrored
# paths inside the container. We mount specific subdirectories rather
# than the whole repo to keep the container's own ``/opt/nosofs/``
# build artifacts intact.
_BIND_OVERLAYS = (
    ("ush/python", "/opt/nosofs/ush/python:ro"),
    ("ush", "/opt/nosofs/ush:ro"),
    ("scripts", "/opt/nosofs/scripts:ro"),
    ("jobs", "/opt/nosofs/jobs:ro"),
    ("parm", "/opt/nosofs/parm:ro"),
)


def _docker_prep_run(
    *,
    image: str,
    repo: Path,
    staging: Path,
    comout_host: Path,
    pdy: str,
    cyc: str,
    ofs: str,
    use_legacy: bool,
    timeout_sec: int = 1200,
) -> subprocess.CompletedProcess:
    """Run a single prep cycle inside the container.

    The container is invoked with the working tree bind-mounted at
    ``/opt/nosofs/`` (read-only) and a host-side COMOUT root mapped to
    the WCOSS2-style ``COMROOT`` inside the container. That lets us
    capture the artifacts on the host without copying out of the
    container after the fact.
    """
    comout_host.mkdir(parents=True, exist_ok=True)

    # Inside the container these paths match the WCOSS2 layout that the
    # existing docker run script in nos_ofs_complete_package uses.
    container_comroot = f"/lfs/h1/nos/ptmp/nosuser/com"
    container_dataroot = f"/lfs/h1/nos/ptmp/nosuser/work/{ofs}"

    # Bind-mount overlays for the migrated workflow code.
    mounts = [
        "-v", f"{staging}:/data:ro",
        "-v", f"{comout_host}:{container_comroot}",
    ]
    for src, dst in _BIND_OVERLAYS:
        mounts += ["-v", f"{(repo / src).resolve()}:{dst}"]

    env_pairs = {
        "PDY": pdy,
        "CYC": cyc,
        "cyc": cyc,
        "OFS": ofs,
        "RUN": ofs,
        "envir": "dev",
        "LOGNAME": "nosuser",
        "NOS_USE_LEGACY_SHELL": "YES" if use_legacy else "NO",
        # Point at the staged inputs.
        "COMINgfs": "/data/com/gfs/v16.3",
        "COMINhrrr": "/data/com/hrrr/v4.1",
        "COMINnwm": "/data/com/nwm/v3.0",
        "COMINrtofs_2d": "/data/com/rtofs",
        "COMINrtofs_3d": "/data/com/rtofs",
        "FIXofs": "/data/fix/secofs",
        # Trim the model run so prep alone exercises the migration.
        "PREP_ONLY": "YES",
        "SENDCOM": "YES",
        "KEEPDATA": "YES",
    }
    env_args: List[str] = []
    for k, v in env_pairs.items():
        env_args += ["-e", f"{k}={v}"]

    # Inside the container we drive the prep stage via the existing
    # run script under nos_ofs_complete_package — that script wraps the
    # J-job machinery and uses the same WCOSS2 paths the bind-mount sets
    # up. We can't depend on it being present in *this* repo, so we
    # inline the env setup and invoke ``exnos_prep.sh`` directly.
    inner_cmd = textwrap.dedent(
        f"""
        set -eu
        export OFS={ofs}
        export PDY={pdy}
        export cyc=$(printf '%02d' {cyc})
        export cycle=t${{cyc}}z
        export envir=dev
        export NET=nosofs
        export RUN={ofs}
        export PREFIXNOS={ofs}
        export PACKAGEROOT=/lfs/h1/nos/nosofs/packages
        export nosofs_ver=v3.7.0
        export nos_ofs_ver=v3.7.0
        export HOMEnos=${{PACKAGEROOT}}/nosofs.${{nosofs_ver}}
        mkdir -p ${{PACKAGEROOT}}
        if [ ! -e "${{HOMEnos}}" ]; then ln -sf /opt/nosofs ${{HOMEnos}}; fi
        export EXECnos=${{HOMEnos}}/exec
        export FIXnos=${{HOMEnos}}/fix/shared
        export PARMnos=${{HOMEnos}}/parm
        export USHnos=${{HOMEnos}}/ush
        export SCRIPTSnos=${{HOMEnos}}/scripts
        export COMROOT={container_comroot}
        export COMOUTroot=${{COMROOT}}/nosofs/${{nos_ofs_ver}}
        export COMOUT=${{COMOUTroot}}/${{OFS}}.${{PDY}}
        export COMIN=${{COMOUTroot}}/${{OFS}}.${{PDY}}
        export DATAROOT={container_dataroot}
        export OFS_CONFIG=${{HOMEnos}}/parm/systems/secofs_ufs.yaml
        export PYTHONPATH=${{HOMEnos}}/ush/python:${{HOMEnos}}/ush/python/nos-utils:${{PYTHONPATH:-}}
        export NDATE=$(command -v ndate)
        export job=${{OFS}}_prep_${{cyc}}_${{envir}}
        export jobid=${{job}}.dockerprep
        export DATA=${{DATAROOT}}/${{job}}
        rm -rf "${{DATA}}"
        mkdir -p "${{DATA}}" "${{COMOUT}}"
        cd "${{DATA}}"
        export pgmout=${{DATA}}/OUTPUT.$$
        export jlogfile=${{DATA}}/jlogfile
        # Spack libs (matches the docker run_secofs_ufs.sh convention).
        SI=/opt/spack-stack/spack-stack-1.9.2/envs/ufs-wm-env/install/gcc/13.3.1
        if [ -d "$SI" ]; then
          SPACK_LIBS=$(find "$SI" -maxdepth 2 \\( -name lib -o -name lib64 \\) -type d 2>/dev/null | tr '\\n' ':')
          export LD_LIBRARY_PATH="${{SPACK_LIBS}}${{LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}}"
        fi
        # err_chk is sourced from prod_util; fall back to a no-op if missing.
        if [ -f /opt/prod_util/lib/prep_step ]; then
          . /opt/prod_util/lib/prep_step 2>/dev/null || true
        fi
        type err_chk >/dev/null 2>&1 || err_chk() {{ exit ${{err:-0}}; }}
        export -f err_chk 2>/dev/null || true
        # Invoke the prep J-job script directly.
        ${{HOMEnos}}/scripts/exnos_prep.sh
        """
    )

    cmd = [
        "docker", "run", "--rm",
        *mounts,
        *env_args,
        "--entrypoint", "/bin/bash",
        image,
        "-lc", inner_cmd,
    ]
    log.info("docker run path=%s pdy=%s cyc=%s legacy=%s",
             "legacy" if use_legacy else "python", pdy, cyc, use_legacy)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)


# ---------------------------------------------------------------------------
# Test 1: golden-manifest schema (cheap, hosted-runner-safe)
# ---------------------------------------------------------------------------

def _manifest_path(prep_cycle: dict) -> Path:
    """Resolve the golden manifest path for a given PDY/cyc/ofs."""
    here = Path(__file__).parent / "golden_manifests"
    return here / f"{prep_cycle['ofs']}_ufs_prep_{prep_cycle['pdy']}_{prep_cycle['cyc']}z.json"


def test_golden_manifest_well_formed(prep_cycle: dict) -> None:
    """Manifest is valid JSON, no path-traversal entries, sha256 well-formed.

    This test does NOT require Docker — it runs on every PR including
    the hosted-runner side of the CI matrix. It catches PRs that
    corrupt the manifest without needing the 12 GB container.
    """
    mpath = _manifest_path(prep_cycle)
    if not mpath.exists():
        pytest.skip(
            f"manifest {mpath.name} not yet generated — run "
            "REGENERATE=1 pytest tests/integration/test_prep_artifact_parity.py "
            "to bootstrap."
        )

    with mpath.open("r") as fh:
        try:
            data = json.load(fh)
        except json.JSONDecodeError as exc:
            pytest.fail(f"manifest is not valid JSON: {exc}")

    # Schema checks.
    for required in ("pdy", "cyc", "ofs", "files", "generated_by",
                     "generated_at", "git_commit", "notes"):
        assert required in data, f"manifest missing key {required!r}"

    assert data["pdy"] == prep_cycle["pdy"]
    assert data["cyc"] == prep_cycle["cyc"]
    assert data["ofs"].startswith(prep_cycle["ofs"]), (
        f"manifest ofs {data['ofs']!r} doesn't match fixture {prep_cycle['ofs']!r}"
    )

    files = data["files"]
    assert isinstance(files, list), "files must be a list"
    seen_paths = set()
    sha_re = re.compile(r"^[0-9a-f]{64}$")
    for entry in files:
        for k in ("path", "size", "mode"):
            assert k in entry, f"file entry missing {k!r}: {entry}"
        p = entry["path"]
        assert isinstance(p, str), f"path must be str: {entry}"
        assert ".." not in p.split("/"), f"path-traversal in manifest: {p}"
        assert not p.startswith("/"), f"absolute path in manifest: {p}"
        assert p not in seen_paths, f"duplicate path in manifest: {p}"
        seen_paths.add(p)
        assert isinstance(entry["size"], int) and entry["size"] >= 0
        assert entry["mode"] in ("text", "netcdf", "log", "other")
        if entry["mode"] == "text" and "sha256" in entry:
            assert sha_re.match(entry["sha256"]), (
                f"malformed sha256 for {p}: {entry['sha256']!r}"
            )


# ---------------------------------------------------------------------------
# Test 2: bootstrap / regenerate the manifest from a fresh Python-path run
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    os.environ.get("REGENERATE") != "1",
    reason="REGENERATE=1 not set — skip manifest bootstrap (this is the "
    "expected default; the parity test below validates the manifest).",
)
def test_regenerate_golden_manifest(
    integration_preflight,  # noqa: ARG001 — triggers skip if Docker absent
    docker_image: str,
    repo_root: Path,
    staging_dir: Path,
    tmp_comout_root: Path,
    prep_cycle: dict,
) -> None:
    """Bootstrap the golden manifest from a single Python-path prep run.

    Invoked once at the start of a migration cycle (or whenever the
    expected file set legitimately changes). Writes the manifest beside
    this test file and exits — the regular parity assertion is then the
    long-term gate.
    """
    comout_host = tmp_comout_root / "python_path"
    proc = _docker_prep_run(
        image=docker_image,
        repo=repo_root,
        staging=staging_dir,
        comout_host=comout_host,
        pdy=prep_cycle["pdy"],
        cyc=prep_cycle["cyc"],
        ofs=prep_cycle["ofs"],
        use_legacy=False,
    )
    if proc.returncode != 0:
        pytest.fail(
            f"Python-path prep run failed (rc={proc.returncode}). "
            f"stderr tail:\n{proc.stderr[-2000:]}"
        )

    # COMOUT lives at <comout_host>/nosofs/<ver>/<ofs>.<pdy>/ inside the
    # container — same path on the host because we bind-mounted.
    expected_comout = _resolve_comout(comout_host, prep_cycle)
    assert expected_comout.is_dir(), (
        f"COMOUT not produced at {expected_comout}; "
        f"contents of {comout_host}: {list(comout_host.rglob('*'))[:10]}"
    )

    entries = _build_manifest_entries(expected_comout)
    manifest = {
        "pdy": prep_cycle["pdy"],
        "cyc": prep_cycle["cyc"],
        "ofs": f"{prep_cycle['ofs']}_ufs",
        "files": entries,
        "generated_by": "tests/integration/test_prep_artifact_parity.py",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": _git_short_sha(repo_root),
        "notes": (
            "Golden manifest for SECOFS-UFS prep cycle. "
            "Regenerate via REGENERATE=1 pytest "
            "tests/integration/test_prep_artifact_parity.py."
        ),
    }
    mpath = _manifest_path(prep_cycle)
    mpath.parent.mkdir(parents=True, exist_ok=True)
    with mpath.open("w") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
        fh.write("\n")
    log.info("wrote golden manifest with %d entries: %s", len(entries), mpath)


# ---------------------------------------------------------------------------
# Test 3: parity diff — the operational gate
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    os.environ.get("RUN_DOCKER_PARITY") != "1",
    reason="RUN_DOCKER_PARITY=1 not set — the full docker prep parity test "
    "is opt-in because it takes 10+ minutes and produces multi-GB artifacts. "
    "Set RUN_DOCKER_PARITY=1 to run, or invoke from the CI workflow.",
)
def test_prep_python_vs_legacy_parity(
    integration_preflight,  # noqa: ARG001 — triggers skip if Docker absent
    docker_image: str,
    repo_root: Path,
    staging_dir: Path,
    tmp_comout_root: Path,
    prep_cycle: dict,
) -> None:
    """End-to-end: Python-path COMOUT == legacy-shell COMOUT.

    This is the operational gate from #219. It runs prep twice and
    asserts the resulting COMOUT trees are equivalent (byte-equal for
    text, allclose for netCDF, structural-match for logs/tars).
    """
    # Manifest must exist — caller can bootstrap with REGENERATE=1.
    mpath = _manifest_path(prep_cycle)
    if not mpath.exists():
        pytest.skip(
            f"golden manifest {mpath} missing — bootstrap first via "
            "REGENERATE=1 pytest tests/integration/test_prep_artifact_parity.py"
        )

    # --- Run A: Python path -------------------------------------------------
    python_comout_host = tmp_comout_root / "python_path"
    proc_a = _docker_prep_run(
        image=docker_image,
        repo=repo_root,
        staging=staging_dir,
        comout_host=python_comout_host,
        pdy=prep_cycle["pdy"],
        cyc=prep_cycle["cyc"],
        ofs=prep_cycle["ofs"],
        use_legacy=False,
    )
    if proc_a.returncode != 0:
        pytest.fail(
            f"[Python-path] prep failed (rc={proc_a.returncode}). "
            f"stderr tail:\n{proc_a.stderr[-2000:]}"
        )
    python_comout = _resolve_comout(python_comout_host, prep_cycle)

    # --- Run B: Legacy shell ------------------------------------------------
    legacy_comout_host = tmp_comout_root / "legacy_path"
    proc_b = _docker_prep_run(
        image=docker_image,
        repo=repo_root,
        staging=staging_dir,
        comout_host=legacy_comout_host,
        pdy=prep_cycle["pdy"],
        cyc=prep_cycle["cyc"],
        ofs=prep_cycle["ofs"],
        use_legacy=True,
    )
    if proc_b.returncode != 0:
        pytest.fail(
            f"[Legacy-path] prep failed (rc={proc_b.returncode}). "
            f"stderr tail:\n{proc_b.stderr[-2000:]}"
        )
    legacy_comout = _resolve_comout(legacy_comout_host, prep_cycle)

    # --- Validate the manifest still describes the Python-path output -------
    _assert_against_manifest(python_comout, mpath)

    # --- Diff the two trees -------------------------------------------------
    files_a = _walk_relative(python_comout)
    files_b = _walk_relative(legacy_comout)
    set_a = set(files_a)
    set_b = set(files_b)
    only_in_a = sorted(set_a - set_b)
    only_in_b = sorted(set_b - set_a)
    assert not only_in_a and not only_in_b, _format_failure(
        "filename-set mismatch",
        details={
            "only_in_python": [str(p) for p in only_in_a[:20]],
            "only_in_legacy": [str(p) for p in only_in_b[:20]],
        },
    )

    # Per-file diff.
    failures: List[Tuple[Path, str]] = []
    for rel in files_a:
        name = rel.name
        klass = _classify(name)
        a = python_comout / rel
        b = legacy_comout / rel
        if klass == "text":
            if not filecmp.cmp(str(a), str(b), shallow=False):
                failures.append((rel, _text_diff_snippet(a, b)))
        elif klass == "netcdf":
            msg = _diff_netcdf(a, b)
            if msg is not None:
                failures.append((rel, msg))
        elif klass == "log":
            # Logs differ by timestamp / jobid — we only confirm both
            # sides produced *something* non-trivially populated.
            if a.stat().st_size == 0 and b.stat().st_size != 0:
                failures.append((rel, "Python-path log empty, legacy non-empty"))
            if b.stat().st_size == 0 and a.stat().st_size != 0:
                failures.append((rel, "legacy log empty, Python-path non-empty"))
        else:  # other — size-only check at 5%
            sa, sb = a.stat().st_size, b.stat().st_size
            if sa != sb and abs(sa - sb) > max(sa, sb, 1) * SIZE_TOLERANCE_PCT / 100.0:
                failures.append((rel, f"size mismatch {sa} vs {sb} bytes"))

    if failures:
        pytest.fail(_format_failure(
            f"{len(failures)} artifact(s) diverged",
            details={"failures": [
                {"path": str(p), "issue": msg} for p, msg in failures[:25]
            ]},
        ))


# ---------------------------------------------------------------------------
# Test 4: diff-machinery unit tests — "test the test" gate
# ---------------------------------------------------------------------------
#
# The full Docker parity run is expensive. These cheap, Docker-free tests
# exercise the underlying diff helpers so a deliberate one-byte
# divergence in an artifact can be detected without spinning up the
# container. Per the #219 punch list: "deliberately introduce a one-byte
# divergence … and confirm the test FAILS with a useful message."

def _make_pair(tmp_path: Path, name: str, content_a: bytes, content_b: bytes
              ) -> Tuple[Path, Path]:
    """Create two host-side files with identical paths under two roots."""
    a_root = tmp_path / "python_path"
    b_root = tmp_path / "legacy_path"
    a_root.mkdir(parents=True, exist_ok=True)
    b_root.mkdir(parents=True, exist_ok=True)
    fa = a_root / name
    fb = b_root / name
    fa.write_bytes(content_a)
    fb.write_bytes(content_b)
    return fa, fb


def test_text_diff_detects_one_byte_divergence(tmp_path: Path) -> None:
    """A single trailing-space change in a text artifact must trip the diff.

    Models the #219 "test the test" scenario: introduce a stray space in
    a string written by ``nos_workflow.stages.prep`` and confirm the
    parity assertion fails with a useful message.
    """
    fa, fb = _make_pair(
        tmp_path, "vsource.th",
        b"date time q1 q2\n0.0 0.0 1.500 2.300\n",
        b"date time q1 q2\n0.0 0.0 1.500 2.300 \n",  # trailing space
    )
    assert _classify(fa.name) == "text"
    assert not filecmp.cmp(str(fa), str(fb), shallow=False)
    snippet = _text_diff_snippet(fa, fb)
    assert "line 2:" in snippet, f"expected line diff, got: {snippet!r}"


def test_text_diff_passes_for_identical_files(tmp_path: Path) -> None:
    """Sanity: identical text files don't trip the diff."""
    payload = b"vsource col 1 col 2\n0.0 1.0 2.0\n10.0 1.5 2.5\n"
    fa, fb = _make_pair(tmp_path, "vsource.th", payload, payload)
    assert filecmp.cmp(str(fa), str(fb), shallow=False)


def test_netcdf_diff_detects_value_perturbation(tmp_path: Path) -> None:
    """An out-of-tolerance NetCDF perturbation must produce a clear msg."""
    netCDF4 = pytest.importorskip("netCDF4")
    import numpy as np

    fa = tmp_path / "elev2D.th.nc"
    fb = tmp_path / "elev2D.th.nc.legacy"
    for path, offset in ((fa, 0.0), (fb, 1.0)):
        with netCDF4.Dataset(str(path), "w") as ds:
            ds.createDimension("time", 3)
            ds.createDimension("node", 5)
            v = ds.createVariable("elev", "f8", ("time", "node"))
            v[:] = np.arange(15).reshape(3, 5) + offset
    msg = _diff_netcdf(fa, fb)
    assert msg is not None, "expected diff to flag the perturbation"
    assert "elev" in msg, f"expected var name in msg, got: {msg!r}"


def test_netcdf_diff_passes_for_identical(tmp_path: Path) -> None:
    """Sanity: identical NetCDF files trip nothing."""
    netCDF4 = pytest.importorskip("netCDF4")
    import numpy as np

    fa = tmp_path / "a.nc"
    fb = tmp_path / "b.nc"
    for path in (fa, fb):
        with netCDF4.Dataset(str(path), "w") as ds:
            ds.createDimension("x", 4)
            v = ds.createVariable("salt", "f8", ("x",))
            v[:] = np.array([35.0, 35.1, 35.2, 35.3])
    msg = _diff_netcdf(fa, fb)
    assert msg is None, f"expected agreement, got: {msg!r}"


def test_manifest_assertion_detects_sha_drift(tmp_path: Path) -> None:
    """If a text artifact's sha256 drifts, the manifest gate must fire."""
    comout = tmp_path / "comout"
    comout.mkdir()
    (comout / "vsource.th").write_bytes(b"normal content\n")

    bogus_manifest = {
        "pdy": "20260324",
        "cyc": "18",
        "ofs": "secofs_ufs",
        "files": [
            {
                "path": "vsource.th",
                "mode": "text",
                "size": len(b"normal content\n"),
                "sha256": "0" * 64,  # deliberately wrong
            }
        ],
        "generated_by": "test",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "git_commit": "deadbeef",
        "notes": "test fixture",
    }
    mpath = tmp_path / "manifest.json"
    mpath.write_text(json.dumps(bogus_manifest))

    # pytest.fail() raises Failed; that lives in _pytest.outcomes and is
    # the appropriate type to catch here.
    with pytest.raises(BaseException) as exc_info:
        _assert_against_manifest(comout, mpath)
    msg = str(exc_info.value)
    assert "sha256" in msg.lower() or "PREP_PARITY" in msg, (
        f"expected sha256-failure marker in message, got: {msg!r}"
    )


def test_classify_buckets_known_artifacts() -> None:
    """The classifier must bucket SECOFS-UFS prep artifacts correctly."""
    cases = {
        "secofs.t18z.20260324.bctides.in.nowcast": "text",
        "vsource.th": "text",
        "msource.th": "text",
        "source_sink.in": "text",
        "param.nml": "text",
        "staout_5": "text",
        "secofs.t18z.20260324.init.nowcast.nc": "netcdf",
        "jlogfile": "log",
        "secofs.t18z.20260324.corms.log": "log",
        "GFS25.forecast_Fortran.t18z.log": "log",
        "Fortran_river.t18z.log": "log",
        "secofs.t18z.20260324.river.th.tar": "log",
        "random_unmatched_file.bin": "other",
    }
    for name, expected in cases.items():
        got = _classify(name)
        assert got == expected, f"_classify({name!r}) = {got!r}, expected {expected!r}"


# ---------------------------------------------------------------------------
# Helpers — manifest, resolution, formatting
# ---------------------------------------------------------------------------

def _resolve_comout(comout_host: Path, prep_cycle: dict) -> Path:
    """Map the host-side COMOUT root to the actual ``<ofs>.<pdy>`` dir.

    The container writes to::

        <comout_host>/nosofs/<nos_ofs_ver>/<ofs>.<pdy>/

    We need to find the version dir at runtime because the SECOFS image
    occasionally pivots between ``v3.7`` and ``v3.7.0`` depending on
    where hotstart files were staged.
    """
    base = comout_host / "nosofs"
    if not base.is_dir():
        return comout_host
    for ver_dir in sorted(base.iterdir()):
        cand = ver_dir / f"{prep_cycle['ofs']}.{prep_cycle['pdy']}"
        if cand.is_dir():
            return cand
    return comout_host


def _build_manifest_entries(comout: Path) -> List[Dict]:
    """Build a sorted list of manifest entries from a COMOUT dir."""
    entries: List[Dict] = []
    for rel in _walk_relative(comout):
        abs_p = comout / rel
        mode = _classify(rel.name)
        entry = {
            "path": str(rel),
            "size": abs_p.stat().st_size,
            "mode": mode,
        }
        if mode == "text":
            entry["sha256"] = _sha256(abs_p)
        entries.append(entry)
    entries.sort(key=lambda e: e["path"])
    return entries


def _assert_against_manifest(comout: Path, mpath: Path) -> None:
    """Assert the COMOUT matches the checked-in manifest."""
    with mpath.open("r") as fh:
        manifest = json.load(fh)
    by_path = {e["path"]: e for e in manifest["files"]}
    present = {str(p): comout / p for p in _walk_relative(comout)}

    missing = sorted(set(by_path) - set(present))
    if missing:
        pytest.fail(_format_failure(
            "files listed in manifest but missing from Python-path COMOUT",
            details={"missing": missing[:20]},
        ))

    # New (unmanifested) files are not necessarily a failure — but they
    # are a signal that the manifest is stale. Warn loudly.
    extra = sorted(set(present) - set(by_path))
    if extra:
        log.warning("Python-path produced %d files not in manifest "
                    "(consider REGENERATE=1): %s", len(extra), extra[:10])

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
            actual_sha = _sha256(abs_p)
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
        pytest.fail(_format_failure(
            "manifest divergence",
            details={"sha256": sha_failures[:20], "size": size_failures[:20]},
        ))


def _text_diff_snippet(a: Path, b: Path, max_lines: int = 6) -> str:
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


def _format_failure(headline: str, details: Optional[Dict] = None) -> str:
    """Structured one-liner + indented payload for pytest.fail messages."""
    summary = f"PREP_PARITY FAIL: {headline}"
    if not details:
        return summary
    body = json.dumps(details, indent=2, sort_keys=True)
    return f"{summary}\n{body}"


def _git_short_sha(repo: Path) -> str:
    """Return the short sha at HEAD, or 'unknown' if git is unavailable."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        pass
    return "unknown"
