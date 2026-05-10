"""Post-stage artifact parity: nos_workflow Python vs preserved legacy shell.

Goal (per #219, commit 5): prove that ``python -m nos_workflow run post``
produces the *same* artifacts the pre-migration shell produced. Mirror
of ``test_prep_artifact_parity.py`` (commit 4), differing only where
the post stage actually differs from prep — namely:

  * Post operates on **model outputs**, not raw forcing inputs. It
    needs ``$COMOUT/<ofs>.<pdy>/<ofs>.t<cyc>z.restart_outputs/`` and
    ``…forecast_outputs/`` to already be on disk from a prior nowcast
    + forecast run. The fixture ``post_integration_preflight`` skips
    cleanly when those aren't staged (the common case on hosted CI).
  * The expected COMOUT delta is much smaller — typically two station
    NetCDF files (``<prefix>.t<cyc>z.<pdy>.stations.{nowcast,forecast}.nc``)
    plus optional bias-correction artifacts (CSV + JSON) when running
    on a 2D barotropic ensemble OFS.

How it works
------------
1. Fires the SECOFS-UFS container twice for the same cycle, with the
   working tree bind-mounted at ``/opt/nosofs/``:

     * Run A — Python path: ``NOS_USE_LEGACY_SHELL=NO`` (default)
     * Run B — Legacy path: ``NOS_USE_LEGACY_SHELL=YES``

2. Diffs the two COMOUT trees using the shared helpers in
   ``diff_helpers.py``:

     * Text artifacts (CSV, JSON, station.in fragments,
       AWIPS/SHEF products): byte-equal via ``filecmp.cmp``.
     * NetCDF artifacts (``*.stations.{nowcast,forecast}.nc``):
       ``numpy.allclose(rtol=1e-12)`` variable-by-variable.
     * Logs (post.log, pgmout.*, jlogfile): size-only check.

3. Asserts the resulting Python-path COMOUT matches the checked-in
   manifest at
   ``golden_manifests/secofs_ufs_post_<pdy>_<cyc>z.json``.

Bootstrap mode
--------------
Same as prep — set ``REGENERATE=1`` to rewrite the manifest from a
fresh Python-path run::

    REGENERATE=1 pytest tests/integration/test_post_artifact_parity.py

Skip behavior
-------------
Three independent reasons to skip:

  * Docker image missing.
  * Base staging dir not populated.
  * ``restart_outputs`` / ``forecast_outputs`` absent from prior cycle.

All three are covered by ``post_integration_preflight``. The legacy
shell at ``scripts/legacy/exnos_post.sh.preY-mig`` is also probed —
if absent, the parity diff is skipped with an ``xfail``-style message
because the parallel migration agent has not yet landed it.

xfail mode
----------
While ``nos_workflow.stages.post.run`` still raises
``NotImplementedError`` (it does at the moment this commit lands), the
Python-path branch can't be exercised. The parity test is gated
behind a runtime probe (``_post_python_path_available``) so it stays
collectable; once the partner agent's commit lands, the gate flips
and the test runs unmodified.
"""
from __future__ import annotations

import filecmp
import json
import logging
import os
import re
import subprocess
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

import pytest

from .diff_helpers import (
    SIZE_TOLERANCE_PCT,
    assert_against_manifest,
    build_manifest_entries,
    classify,
    diff_netcdf,
    format_failure,
    git_short_sha,
    text_diff_snippet,
    walk_relative,
)


log = logging.getLogger(__name__)


_STAGE = "post"


# ---------------------------------------------------------------------------
# Docker driver
# ---------------------------------------------------------------------------

# Same bind-mount overlay shape as the prep test — see test_prep_artifact_parity
# for the rationale. Post needs the same scripts/ush layout in the container.
_BIND_OVERLAYS = (
    ("ush/python", "/opt/nosofs/ush/python:ro"),
    ("ush", "/opt/nosofs/ush:ro"),
    ("scripts", "/opt/nosofs/scripts:ro"),
    ("jobs", "/opt/nosofs/jobs:ro"),
    ("parm", "/opt/nosofs/parm:ro"),
)


def _legacy_post_script_present(repo: Path) -> bool:
    """Probe for the preserved pre-migration shell.

    The parallel migration agent in commit 5a is responsible for
    landing ``scripts/legacy/exnos_post.sh.preY-mig``. Until that file
    exists, the legacy-path run can't be exercised — the test gates
    on this probe so collection stays clean.
    """
    return (repo / "scripts" / "legacy" / "exnos_post.sh.preY-mig").is_file()


def _post_python_path_available(repo: Path) -> bool:
    """Probe whether ``nos_workflow.stages.post.run`` has been ported.

    Returns False while the stub still raises ``NotImplementedError``.
    Until the partner agent's commit lands, we can only validate the
    legacy-path manifest and the diff helpers — the cross-path parity
    diff is xfail-skipped with a clear reason.
    """
    post_module = repo / "ush" / "python" / "nos_workflow" / "stages" / "post.py"
    if not post_module.is_file():
        return False
    try:
        text = post_module.read_text(encoding="utf-8")
    except OSError:
        return False
    # Heuristic: any stage that still raises NotImplementedError in its
    # top-level run() body is not ready. The partner agent will replace
    # that with a real dispatcher (mirror of prep._run_comf_prep).
    return "NotImplementedError" not in text


def _docker_post_run(
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
    """Run a single post cycle inside the container.

    Same wiring as ``_docker_prep_run`` (see prep test for the deep
    dive on bind-mount + env conventions). The only post-specific
    knobs:

      * ``POST_ONLY=YES`` tells the entrypoint to skip the model
        execution and run the post-processing path only.
      * No ``PREP_ONLY``, ``COMINgfs``, etc. — post doesn't read raw
        forcing inputs, it reads the model's output COMOUT.
      * The container's ``COMOUT`` is bind-mounted from
        ``staging/com/nosofs/<ver>/<ofs>.<pdy>/`` (the prior nowcast
        + forecast run's output) so post finds its ``staout_*`` inputs.
    """
    comout_host.mkdir(parents=True, exist_ok=True)

    container_comroot = f"/lfs/h1/nos/ptmp/nosuser/com"
    container_dataroot = f"/lfs/h1/nos/ptmp/nosuser/work/{ofs}"

    # Bind mounts:
    #   /data — read-only staging (fix files, raw forcing, station.in, …)
    #   COMOUT root — read-write, host-mapped so the host can inspect
    #     post products. We also need to seed it with the prior
    #     restart_outputs/forecast_outputs so post can find its inputs;
    #     the container bootstrap below copies them in from the staged
    #     prior cycle under /data/com/nosofs/.
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
        "FIXofs": "/data/fix/secofs",
        # Trim the workflow so post alone is exercised.
        "POST_ONLY": "YES",
        "SENDCOM": "YES",
        "KEEPDATA": "YES",
        # Post-specific defaults — keep ensemble bias correction off in
        # the parity test (it's optional and adds non-determinism via
        # member ordering). The 3D station NC path is exercised either
        # way.
        "BAROTROPIC": "false",
    }
    env_args: List[str] = []
    for k, v in env_pairs.items():
        env_args += ["-e", f"{k}={v}"]

    # Inside the container: same WCOSS2-style env setup as the prep
    # test, then seed COMOUT with the prior cycle's outputs (so post
    # has staout files to consume) and invoke exnos_post.sh.
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
        export job=${{OFS}}_post_${{cyc}}_${{envir}}
        export jobid=${{job}}.dockerpost
        export DATA=${{DATAROOT}}/${{job}}
        export LEN_NOWCAST=${{LEN_NOWCAST:-6}}
        rm -rf "${{DATA}}"
        mkdir -p "${{DATA}}" "${{COMOUT}}"
        cd "${{DATA}}"
        export pgmout=${{DATA}}/OUTPUT.$$
        export jlogfile=${{DATA}}/jlogfile

        # Seed COMOUT with the prior cycle's nowcast + forecast outputs
        # so post has staout_* files to consume. Source the staged tree
        # under /data/com/nosofs/<ver>/<ofs>.<pdy>/.
        for SRC_VER in v3.7 v3.7.0; do
          SRC_COMOUT=/data/com/nosofs/${{SRC_VER}}/${{OFS}}.${{PDY}}
          if [ -d "${{SRC_COMOUT}}" ]; then
            for SUB in restart_outputs forecast_outputs; do
              SRC_DIR="${{SRC_COMOUT}}/${{OFS}}.${{cycle}}.${{SUB}}"
              DST_DIR="${{COMOUT}}/${{OFS}}.${{cycle}}.${{SUB}}"
              if [ -d "${{SRC_DIR}}" ] && [ ! -d "${{DST_DIR}}" ]; then
                cp -rp "${{SRC_DIR}}" "${{DST_DIR}}"
              fi
            done
            break
          fi
        done

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
        # Invoke the post J-job script directly.
        ${{HOMEnos}}/scripts/exnos_post.sh
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
    log.info(
        "docker run path=%s pdy=%s cyc=%s legacy=%s",
        "legacy" if use_legacy else "python", pdy, cyc, use_legacy,
    )
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)


# ---------------------------------------------------------------------------
# Test 1: golden-manifest schema (cheap, hosted-runner-safe)
# ---------------------------------------------------------------------------

def _manifest_path(post_cycle: dict) -> Path:
    """Resolve the golden manifest path for the given PDY/cyc/ofs."""
    here = Path(__file__).parent / "golden_manifests"
    return here / f"{post_cycle['ofs']}_ufs_post_{post_cycle['pdy']}_{post_cycle['cyc']}z.json"


def test_post_golden_manifest_well_formed(post_cycle: dict) -> None:
    """Manifest is valid JSON, no path-traversal entries, sha256 well-formed.

    Runs on every PR (Docker-free), same as prep. The schema gate
    catches manifest corruption without needing the 12 GB image.

    The post manifest is allowed to have ``files: []`` while the
    migration is in flight — that's the schema-only stub that lands in
    commit 5 before the partner agent's real port. The schema gate
    still validates structure on the stub.
    """
    mpath = _manifest_path(post_cycle)
    if not mpath.exists():
        pytest.skip(
            f"manifest {mpath.name} not yet generated — run "
            "REGENERATE=1 pytest tests/integration/test_post_artifact_parity.py "
            "to bootstrap."
        )

    with mpath.open("r") as fh:
        try:
            data = json.load(fh)
        except json.JSONDecodeError as exc:
            pytest.fail(f"manifest is not valid JSON: {exc}")

    # Schema checks (same shape as prep manifest).
    for required in ("pdy", "cyc", "ofs", "files", "generated_by",
                     "generated_at", "git_commit", "notes"):
        assert required in data, f"manifest missing key {required!r}"

    assert data["pdy"] == post_cycle["pdy"]
    assert data["cyc"] == post_cycle["cyc"]
    assert data["ofs"].startswith(post_cycle["ofs"]), (
        f"manifest ofs {data['ofs']!r} doesn't match fixture {post_cycle['ofs']!r}"
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
def test_regenerate_post_golden_manifest(
    post_integration_preflight,  # noqa: ARG001 — triggers skip if Docker/inputs absent
    docker_image: str,
    repo_root: Path,
    staging_dir: Path,
    tmp_comout_root: Path,
    post_cycle: dict,
) -> None:
    """Bootstrap the post manifest from a single run.

    Prefers the Python-path when the partner agent's port has landed
    (post.py no longer raises NotImplementedError). Falls back to the
    legacy path otherwise — the resulting manifest is the same shape
    either way; the parity diff is what proves the two paths agree.
    """
    use_legacy = not _post_python_path_available(repo_root)
    if use_legacy and not _legacy_post_script_present(repo_root):
        pytest.skip(
            "neither nos_workflow.stages.post nor "
            "scripts/legacy/exnos_post.sh.preY-mig is ready — "
            "the partner migration agent will land both."
        )

    label = "legacy_path" if use_legacy else "python_path"
    comout_host = tmp_comout_root / label
    proc = _docker_post_run(
        image=docker_image,
        repo=repo_root,
        staging=staging_dir,
        comout_host=comout_host,
        pdy=post_cycle["pdy"],
        cyc=post_cycle["cyc"],
        ofs=post_cycle["ofs"],
        use_legacy=use_legacy,
    )
    if proc.returncode != 0:
        pytest.fail(
            f"[{label}] post run failed (rc={proc.returncode}). "
            f"stderr tail:\n{proc.stderr[-2000:]}"
        )

    expected_comout = _resolve_comout(comout_host, post_cycle)
    assert expected_comout.is_dir(), (
        f"COMOUT not produced at {expected_comout}; "
        f"contents of {comout_host}: {list(comout_host.rglob('*'))[:10]}"
    )

    # Only manifest the *new* post artifacts, not the seeded model
    # outputs we copied in. Filter out anything under
    # ``<ofs>.t<cyc>z.{restart,forecast}_outputs/`` which is input.
    cycle_tag = f"{post_cycle['ofs']}.t{post_cycle['cyc']}z"
    input_dirs = (
        f"{cycle_tag}.restart_outputs",
        f"{cycle_tag}.forecast_outputs",
    )

    def _is_input(rel: Path) -> bool:
        parts = rel.parts
        return any(d in parts for d in input_dirs)

    entries = [
        e for e in build_manifest_entries(expected_comout)
        if not _is_input(Path(e["path"]))
    ]

    manifest = {
        "pdy": post_cycle["pdy"],
        "cyc": post_cycle["cyc"],
        "ofs": f"{post_cycle['ofs']}_ufs",
        "files": entries,
        "generated_by": "tests/integration/test_post_artifact_parity.py",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": git_short_sha(repo_root),
        "notes": (
            "Golden manifest for SECOFS-UFS post cycle. "
            f"Bootstrapped from the {label} run; "
            "regenerate via REGENERATE=1 pytest "
            "tests/integration/test_post_artifact_parity.py."
        ),
    }
    mpath = _manifest_path(post_cycle)
    mpath.parent.mkdir(parents=True, exist_ok=True)
    with mpath.open("w") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
        fh.write("\n")
    log.info("wrote post golden manifest with %d entries: %s", len(entries), mpath)


# ---------------------------------------------------------------------------
# Test 3: parity diff — the operational gate
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    os.environ.get("RUN_DOCKER_PARITY") != "1",
    reason="RUN_DOCKER_PARITY=1 not set — the full docker post parity test "
    "is opt-in. Set RUN_DOCKER_PARITY=1 to run, or invoke from the CI workflow.",
)
def test_post_python_vs_legacy_parity(
    post_integration_preflight,  # noqa: ARG001 — triggers skip if Docker/inputs absent
    docker_image: str,
    repo_root: Path,
    staging_dir: Path,
    tmp_comout_root: Path,
    post_cycle: dict,
) -> None:
    """End-to-end: Python-path COMOUT == legacy-shell COMOUT for the post stage.

    The operational gate from #219 commit 5. Runs post twice and
    asserts the resulting COMOUT trees are equivalent.

    Three runtime conditions can xfail-skip the test (kept distinct so
    the CI log reader knows exactly which knob is missing):

      * Python-path post not yet ported (stub raises NotImplementedError)
      * Legacy shell ``exnos_post.sh.preY-mig`` not yet preserved
      * Golden manifest not yet bootstrapped

    All three are expected to flip green once the partner migration
    agent lands ``scripts/legacy/exnos_post.sh.preY-mig`` and ports
    ``nos_workflow.stages.post.run``.
    """
    mpath = _manifest_path(post_cycle)
    if not mpath.exists():
        pytest.skip(
            f"golden manifest {mpath} missing — bootstrap first via "
            "REGENERATE=1 pytest tests/integration/test_post_artifact_parity.py"
        )
    if not _legacy_post_script_present(repo_root):
        pytest.xfail(
            "scripts/legacy/exnos_post.sh.preY-mig not present — the partner "
            "migration agent will land it in commit 5a."
        )
    if not _post_python_path_available(repo_root):
        pytest.xfail(
            "nos_workflow.stages.post.run still raises NotImplementedError "
            "— the partner migration agent will land the real port in commit 5a."
        )

    # --- Run A: Python path -------------------------------------------------
    python_comout_host = tmp_comout_root / "python_path"
    proc_a = _docker_post_run(
        image=docker_image,
        repo=repo_root,
        staging=staging_dir,
        comout_host=python_comout_host,
        pdy=post_cycle["pdy"],
        cyc=post_cycle["cyc"],
        ofs=post_cycle["ofs"],
        use_legacy=False,
    )
    if proc_a.returncode != 0:
        pytest.fail(
            f"[Python-path] post failed (rc={proc_a.returncode}). "
            f"stderr tail:\n{proc_a.stderr[-2000:]}"
        )
    python_comout = _resolve_comout(python_comout_host, post_cycle)

    # --- Run B: Legacy shell ------------------------------------------------
    legacy_comout_host = tmp_comout_root / "legacy_path"
    proc_b = _docker_post_run(
        image=docker_image,
        repo=repo_root,
        staging=staging_dir,
        comout_host=legacy_comout_host,
        pdy=post_cycle["pdy"],
        cyc=post_cycle["cyc"],
        ofs=post_cycle["ofs"],
        use_legacy=True,
    )
    if proc_b.returncode != 0:
        pytest.fail(
            f"[Legacy-path] post failed (rc={proc_b.returncode}). "
            f"stderr tail:\n{proc_b.stderr[-2000:]}"
        )
    legacy_comout = _resolve_comout(legacy_comout_host, post_cycle)

    # --- Validate the manifest still describes the Python-path output -------
    assert_against_manifest(python_comout, mpath, stage=_STAGE)

    # --- Diff the two trees -------------------------------------------------
    # Filter out the seeded model-output inputs so we only diff the
    # actual post products. Otherwise we'd compare cp -rp'd directories
    # whose mtimes diverge between the two runs.
    cycle_tag = f"{post_cycle['ofs']}.t{post_cycle['cyc']}z"
    input_dirs = (
        f"{cycle_tag}.restart_outputs",
        f"{cycle_tag}.forecast_outputs",
    )

    def _is_input(rel: Path) -> bool:
        parts = rel.parts
        return any(d in parts for d in input_dirs)

    files_a = [p for p in walk_relative(python_comout) if not _is_input(p)]
    files_b = [p for p in walk_relative(legacy_comout) if not _is_input(p)]
    set_a = set(files_a)
    set_b = set(files_b)
    only_in_a = sorted(set_a - set_b)
    only_in_b = sorted(set_b - set_a)
    assert not only_in_a and not only_in_b, format_failure(
        "filename-set mismatch",
        details={
            "only_in_python": [str(p) for p in only_in_a[:20]],
            "only_in_legacy": [str(p) for p in only_in_b[:20]],
        },
        stage=_STAGE,
    )

    # Per-file diff.
    failures: List[Tuple[Path, str]] = []
    for rel in files_a:
        name = rel.name
        klass = classify(name)
        a = python_comout / rel
        b = legacy_comout / rel
        if klass == "text":
            if not filecmp.cmp(str(a), str(b), shallow=False):
                failures.append((rel, text_diff_snippet(a, b)))
        elif klass == "netcdf":
            msg = diff_netcdf(a, b)
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
        pytest.fail(format_failure(
            f"{len(failures)} artifact(s) diverged",
            details={"failures": [
                {"path": str(p), "issue": msg} for p, msg in failures[:25]
            ]},
            stage=_STAGE,
        ))


# ---------------------------------------------------------------------------
# Test 4: diff-machinery and post-specific unit tests
# ---------------------------------------------------------------------------
#
# Cheap, Docker-free tests that exercise:
#   * Post-specific artifacts get classified correctly.
#   * The manifest assertion fires the ``POST_PARITY FAIL`` marker
#     (not ``PREP_PARITY FAIL``) so CI log scrapers can route alerts.
#   * Sanity that the shared diff helpers still work for the post
#     artifact set (NetCDF station files, bias-correction CSV).

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


def test_post_classify_buckets_known_artifacts() -> None:
    """The classifier must bucket SECOFS-UFS post artifacts correctly.

    Post products are typically:
      * .stations.{nowcast,forecast}.nc — NetCDF (allclose diff)
      * bias_coefficients.json — text (sha256)
      * corrected_wl.csv — text (sha256)
      * schism_standard_output.ctl — text (sha256)
      * AWIPS/SHEF text products — text (sha256)
      * post.log / pgmout — log (size-only)
    """
    cases = {
        "secofs.t18z.20260324.stations.nowcast.nc": "netcdf",
        "secofs.t18z.20260324.stations.forecast.nc": "netcdf",
        "bias_coefficients.json": "text",
        "corrected_wl.csv": "text",
        "schism_standard_output.ctl": "text",
        "secofs.station.lat.lon": "text",
        "secofs.t18z.20260324.shef": "text",
        "secofs.t18z.20260324.awips.txt": "text",
        "post.log": "log",
        "OUTPUT.12345": "log",
        "pgmout.12345": "log",
        "random_unmatched_file.bin": "other",
    }
    for name, expected in cases.items():
        got = classify(name)
        assert got == expected, f"classify({name!r}) = {got!r}, expected {expected!r}"


def test_post_text_diff_detects_one_byte_divergence(tmp_path: Path) -> None:
    """A trailing-space change in a post CSV must trip the diff.

    The "test the test" gate from #219 commit 5: deliberately tamper
    and confirm the helper catches it.
    """
    fa, fb = _make_pair(
        tmp_path, "corrected_wl.csv",
        b"station,time,wl\nST001,2026-03-24T18:00:00Z,1.234\n",
        b"station,time,wl\nST001,2026-03-24T18:00:00Z,1.234 \n",  # trailing space
    )
    assert classify(fa.name) == "text"
    assert not filecmp.cmp(str(fa), str(fb), shallow=False)
    snippet = text_diff_snippet(fa, fb)
    assert "line 2:" in snippet, f"expected line diff, got: {snippet!r}"


def test_post_netcdf_diff_detects_station_perturbation(tmp_path: Path) -> None:
    """An out-of-tolerance perturbation in a stations NC must produce a clear msg."""
    netCDF4 = pytest.importorskip("netCDF4")
    import numpy as np

    fa = tmp_path / "secofs.t18z.20260324.stations.nowcast.nc"
    fb = tmp_path / "secofs.t18z.20260324.stations.nowcast.nc.legacy"
    for path, offset in ((fa, 0.0), (fb, 1.0e-3)):
        with netCDF4.Dataset(str(path), "w") as ds:
            ds.createDimension("station", 5)
            ds.createDimension("time", 7)
            v = ds.createVariable("water_level", "f8", ("time", "station"))
            v[:] = np.arange(35).reshape(7, 5).astype(float) + offset
    msg = diff_netcdf(fa, fb)
    assert msg is not None, "expected diff to flag the perturbation"
    assert "water_level" in msg, f"expected var name in msg, got: {msg!r}"


def test_post_manifest_assertion_emits_post_marker(tmp_path: Path) -> None:
    """The post manifest gate must emit ``POST_PARITY FAIL`` (not PREP).

    Operators wire CI alerts on a per-stage marker. The shared
    ``assert_against_manifest`` takes ``stage="post"`` and surfaces
    ``POST_PARITY FAIL`` on the headline so the alert routes
    correctly.
    """
    comout = tmp_path / "comout"
    comout.mkdir()
    (comout / "bias_coefficients.json").write_bytes(b'{"trained": true}\n')

    bogus_manifest = {
        "pdy": "20260324",
        "cyc": "18",
        "ofs": "secofs_ufs",
        "files": [
            {
                "path": "bias_coefficients.json",
                "mode": "text",
                "size": len(b'{"trained": true}\n'),
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

    with pytest.raises(BaseException) as exc_info:
        assert_against_manifest(comout, mpath, stage=_STAGE)
    msg = str(exc_info.value)
    assert "POST_PARITY" in msg, (
        f"expected POST_PARITY marker, got: {msg!r}"
    )
    assert "sha256" in msg.lower(), (
        f"expected sha256-failure detail, got: {msg!r}"
    )


# ---------------------------------------------------------------------------
# Helpers — manifest, resolution
# ---------------------------------------------------------------------------

def _resolve_comout(comout_host: Path, post_cycle: dict) -> Path:
    """Map the host-side COMOUT root to the actual ``<ofs>.<pdy>`` dir.

    Mirror of the prep helper — version dir is discovered at runtime
    because v3.7 and v3.7.0 both ship in different staging snapshots.
    """
    base = comout_host / "nosofs"
    if not base.is_dir():
        return comout_host
    for ver_dir in sorted(base.iterdir()):
        cand = ver_dir / f"{post_cycle['ofs']}.{post_cycle['pdy']}"
        if cand.is_dir():
            return cand
    return comout_host
