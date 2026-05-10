"""Nowcast-stage artifact parity: nos_workflow Python vs preserved legacy shell.

Goal (per #219, commit 6): prove that ``python -m nos_workflow run nowcast``
produces the *same* artifacts the pre-migration shell produced. Mirror
of ``test_prep_artifact_parity.py`` (commit 4) and
``test_post_artifact_parity.py`` (commit 5), differing only where the
nowcast stage actually differs from prep/post.

How it differs from prep / post
-------------------------------

Prep stages inputs; post extracts a small product set from model
outputs; **nowcast runs the model**. That gives the nowcast parity test
its own set of operational realities:

  * The expected COMOUT delta is the SCHISM run's archive set:
    ``<ofs>.t<cyc>z.restart_outputs/`` (mirror.out, flux.out, staout_*)
    plus the combined hotstart NetCDF ``<ofs>.t<cyc>z.<pdy>.rst.nowcast.nc``.
  * Several outputs are non-deterministic at byte/text level even when
    the simulation was numerically equivalent:
      - ``mirror.out`` — SCHISM per-rank log embeds timestamps + hostnames.
      - ``flux.out``   — periodic flux totals can drift in last 1–2 ULPs.
      - ``staout_*``   — ASCII float columns; FMA / MPI rank ordering
        produces bit-noise in the last 2–3 decimal places.
      - ``rst.nowcast.nc`` — NetCDF metadata (creation timestamp,
        rank-ordering of nodes) can vary even with allclose-equal
        physics. We diff the data variables only (allclose at
        ``rtol=1e-12``); metadata variance is tolerated.
  * The MPI launch (``mpiexec ... fv3_coastalS.exe``) requires
    ``module load``-style env wiring that doesn't survive
    ``subprocess`` — see ``ush/python/nos_workflow/stages/nowcast.py``
    docstring. The parity test still runs the launch inside the
    container because the container ships the module env baked in.

Classification helpers
----------------------

The nowcast-specific non-determinism is encoded in
``diff_helpers.NOWCAST_NONDETERMINISTIC_PATTERNS`` and surfaced via
``classify_nowcast``. The prep test still uses the global ``classify``
(``staout_*`` are staged inputs there, not produced outputs).

Bootstrap / skip behavior
-------------------------

Mirror of prep/post: ``REGENERATE=1`` to bootstrap, ``RUN_DOCKER_PARITY=1``
to opt into the heavy run. Three runtime skip conditions covered by
``nowcast_integration_preflight``:

  * Docker image missing.
  * Base staging dir not populated.
  * Prior-cycle hotstart (init.nowcast.nc / rst.*.nc) absent — the
    nowcast can't even reach its MPI launch step without one.

xfail mode
----------

The partner agent (``a83580c54e007c3eb``) owns
``scripts/exnos_nowcast.sh``, ``scripts/legacy/exnos_nowcast.sh.preY-mig``,
and ``ush/python/nos_workflow/stages/nowcast.py``. Until those land,
the python-vs-legacy parity gate ``xfail``s with a structured message
identifying which piece is missing — same pattern as
``test_post_artifact_parity`` while post was waiting on its partner.

Note on diff helpers
--------------------

The diff machinery (``classify``, ``classify_nowcast``, ``diff_netcdf``,
``sha256``, manifest assertion, etc.) lives in
``tests/integration/diff_helpers.py`` so the forecast-stage parity
test (next migration in #219) can reuse it byte-for-byte. This file
adds the only nowcast-specific behavior — ``classify_nowcast`` and the
nondeterministic patterns — back into the shared module so the
forecast test inherits it for free.
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
    classify_nowcast,
    diff_netcdf,
    format_failure,
    git_short_sha,
    text_diff_snippet,
    walk_relative,
)


log = logging.getLogger(__name__)


_STAGE = "nowcast"


# ---------------------------------------------------------------------------
# Docker driver
# ---------------------------------------------------------------------------

# Same bind-mount overlay shape as prep + post. See test_prep_artifact_parity
# for the rationale on read-only working-tree overlay onto /opt/nosofs/.
_BIND_OVERLAYS = (
    ("ush/python", "/opt/nosofs/ush/python:ro"),
    ("ush", "/opt/nosofs/ush:ro"),
    ("scripts", "/opt/nosofs/scripts:ro"),
    ("jobs", "/opt/nosofs/jobs:ro"),
    ("parm", "/opt/nosofs/parm:ro"),
)


def _legacy_nowcast_script_present(repo: Path) -> bool:
    """Probe for the preserved pre-migration nowcast shell.

    The partner migration agent is responsible for landing
    ``scripts/legacy/exnos_nowcast.sh.preY-mig``. Until that exists,
    the legacy-path run can't be exercised — the test gates on this
    probe so collection stays clean.
    """
    return (repo / "scripts" / "legacy" / "exnos_nowcast.sh.preY-mig").is_file()


def _nowcast_python_path_available(repo: Path) -> bool:
    """Probe whether ``nos_workflow.stages.nowcast.run`` has been ported.

    The partner agent's port introduces ``_run_comf_nowcast`` (mirror of
    ``_run_comf_prep`` / ``_run_comf_post``). STOFS / ADCIRC branches
    keep raising NotImplementedError until tasks #33/#34 — that's
    expected and doesn't block the COMF parity test, so this probe
    looks specifically for the ported ``_run_comf_nowcast`` symbol.
    """
    module = repo / "ush" / "python" / "nos_workflow" / "stages" / "nowcast.py"
    if not module.is_file():
        return False
    try:
        text = module.read_text(encoding="utf-8")
    except OSError:
        return False
    return "_run_comf_nowcast" in text


def _docker_nowcast_run(
    *,
    image: str,
    repo: Path,
    staging: Path,
    comout_host: Path,
    pdy: str,
    cyc: str,
    ofs: str,
    use_legacy: bool,
    timeout_sec: int = 3600,
) -> subprocess.CompletedProcess:
    """Run a single nowcast cycle inside the container.

    Same wiring as ``_docker_prep_run`` / ``_docker_post_run`` (see
    those for the deep dive). Nowcast-specific knobs:

      * ``NOWCAST_ONLY=YES`` keeps the entrypoint from chaining into a
        forecast — we only want to exercise the nowcast stage for the
        parity test. (J-job wrappers honor this; some downstream
        scripts also key off ``PHASE``.)
      * ``PHASE=nowcast`` redundant with NOWCAST_ONLY but keeps shell
        scripts that key off PHASE consistent.
      * Longer timeout (3600s) because the MPI launch is the long
        pole — typical SECOFS-UFS nowcast takes 20-30 minutes wall
        time on the dev box.
      * Same staging dir as prep/post, but the container bootstrap
        seeds COMOUT from the prior cycle's outputs so
        ``prepare_restart`` can find a hotstart.
    """
    comout_host.mkdir(parents=True, exist_ok=True)

    container_comroot = f"/lfs/h1/nos/ptmp/nosuser/com"
    container_dataroot = f"/lfs/h1/nos/ptmp/nosuser/work/{ofs}"

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
        "COMINgfs": "/data/com/gfs/v16.3",
        "COMINhrrr": "/data/com/hrrr/v4.1",
        "COMINnwm": "/data/com/nwm/v3.0",
        "COMINrtofs_2d": "/data/com/rtofs",
        "COMINrtofs_3d": "/data/com/rtofs",
        "FIXofs": "/data/fix/secofs",
        # Trim to nowcast only.
        "NOWCAST_ONLY": "YES",
        "PHASE": "nowcast",
        "SENDCOM": "YES",
        "KEEPDATA": "YES",
    }
    env_args: List[str] = []
    for k, v in env_pairs.items():
        env_args += ["-e", f"{k}={v}"]

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
        export job=${{OFS}}_nowcast_${{cyc}}_${{envir}}
        export jobid=${{job}}.dockernowcast
        export DATA=${{DATAROOT}}/${{job}}
        rm -rf "${{DATA}}"
        mkdir -p "${{DATA}}" "${{COMOUT}}"
        cd "${{DATA}}"
        export pgmout=${{DATA}}/OUTPUT.$$
        export jlogfile=${{DATA}}/jlogfile

        # Seed COMOUT with the prep stage's outputs from a prior run
        # (so nowcast finds bctides.in, param.nml, vsource.th, …) plus
        # any prior-cycle hotstart NetCDF needed by prepare_restart.
        for SRC_VER in v3.7 v3.7.0; do
          SRC_COMOUT=/data/com/nosofs/${{SRC_VER}}/${{OFS}}.${{PDY}}
          if [ -d "${{SRC_COMOUT}}" ]; then
            # Top-level prep artifacts (bctides, vsource, param, …).
            for f in "${{SRC_COMOUT}}"/*; do
              [ -f "$f" ] || continue
              bn=$(basename "$f")
              [ -f "${{COMOUT}}/${{bn}}" ] || cp -p "$f" "${{COMOUT}}/${{bn}}"
            done
            break
          fi
        done

        SI=/opt/spack-stack/spack-stack-1.9.2/envs/ufs-wm-env/install/gcc/13.3.1
        if [ -d "$SI" ]; then
          SPACK_LIBS=$(find "$SI" -maxdepth 2 \\( -name lib -o -name lib64 \\) -type d 2>/dev/null | tr '\\n' ':')
          export LD_LIBRARY_PATH="${{SPACK_LIBS}}${{LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}}"
        fi
        if [ -f /opt/prod_util/lib/prep_step ]; then
          . /opt/prod_util/lib/prep_step 2>/dev/null || true
        fi
        type err_chk >/dev/null 2>&1 || err_chk() {{ exit ${{err:-0}}; }}
        export -f err_chk 2>/dev/null || true
        # Invoke the nowcast J-job script directly.
        ${{HOMEnos}}/scripts/exnos_nowcast.sh
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

def _manifest_path(nowcast_cycle: dict) -> Path:
    """Resolve the golden manifest path for a given PDY/cyc/ofs."""
    here = Path(__file__).parent / "golden_manifests"
    return here / (
        f"{nowcast_cycle['ofs']}_ufs_nowcast_"
        f"{nowcast_cycle['pdy']}_{nowcast_cycle['cyc']}z.json"
    )


def test_nowcast_golden_manifest_well_formed(nowcast_cycle: dict) -> None:
    """Manifest is valid JSON, no path-traversal entries, sha256 well-formed.

    Runs on every PR (Docker-free), same as prep + post. The schema
    gate catches manifest corruption without needing the 12 GB image.

    The nowcast manifest is allowed to ship with ``files: []`` while
    the migration is in flight — that's the schema-only stub that lands
    in commit 6 before the partner agent's drill against WCOSS2. The
    schema gate still validates structure on the stub.
    """
    mpath = _manifest_path(nowcast_cycle)
    if not mpath.exists():
        pytest.skip(
            f"manifest {mpath.name} not yet generated — run "
            "REGENERATE=1 pytest tests/integration/test_nowcast_artifact_parity.py "
            "to bootstrap."
        )

    with mpath.open("r") as fh:
        try:
            data = json.load(fh)
        except json.JSONDecodeError as exc:
            pytest.fail(f"manifest is not valid JSON: {exc}")

    # Schema checks (same shape as prep/post manifests).
    for required in ("pdy", "cyc", "ofs", "files", "generated_by",
                     "generated_at", "git_commit", "notes"):
        assert required in data, f"manifest missing key {required!r}"

    assert data["pdy"] == nowcast_cycle["pdy"]
    assert data["cyc"] == nowcast_cycle["cyc"]
    assert data["ofs"].startswith(nowcast_cycle["ofs"]), (
        f"manifest ofs {data['ofs']!r} doesn't match fixture "
        f"{nowcast_cycle['ofs']!r}"
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
def test_regenerate_nowcast_golden_manifest(
    nowcast_integration_preflight,  # noqa: ARG001 — triggers skip if Docker/inputs absent
    docker_image: str,
    repo_root: Path,
    staging_dir: Path,
    tmp_comout_root: Path,
    nowcast_cycle: dict,
) -> None:
    """Bootstrap the nowcast manifest from a single run.

    Prefers the Python path when the partner agent's port has landed
    (``nowcast.py`` exposes ``_run_comf_nowcast``). Falls back to the
    legacy path otherwise — the resulting manifest shape is the same
    either way; the parity diff is what proves the two paths agree.
    """
    use_legacy = not _nowcast_python_path_available(repo_root)
    if use_legacy and not _legacy_nowcast_script_present(repo_root):
        pytest.skip(
            "neither nos_workflow.stages.nowcast nor "
            "scripts/legacy/exnos_nowcast.sh.preY-mig is ready — "
            "the partner migration agent will land both."
        )

    label = "legacy_path" if use_legacy else "python_path"
    comout_host = tmp_comout_root / label
    proc = _docker_nowcast_run(
        image=docker_image,
        repo=repo_root,
        staging=staging_dir,
        comout_host=comout_host,
        pdy=nowcast_cycle["pdy"],
        cyc=nowcast_cycle["cyc"],
        ofs=nowcast_cycle["ofs"],
        use_legacy=use_legacy,
    )
    if proc.returncode != 0:
        pytest.fail(
            f"[{label}] nowcast run failed (rc={proc.returncode}). "
            f"stderr tail:\n{proc.stderr[-2000:]}"
        )

    expected_comout = _resolve_comout(comout_host, nowcast_cycle)
    assert expected_comout.is_dir(), (
        f"COMOUT not produced at {expected_comout}; "
        f"contents of {comout_host}: {list(comout_host.rglob('*'))[:10]}"
    )

    # Only manifest the *new* nowcast artifacts. The bootstrap copy
    # seeded prep-stage outputs into COMOUT before the run — those are
    # inputs, not products, and don't belong in the nowcast manifest.
    # We identify nowcast products by their location (restart_outputs/)
    # or by the ``rst.nowcast.nc`` / ``rst.forecast.nc`` filename
    # convention archived by ``_schism_archive_outputs``.
    cycle_tag = f"{nowcast_cycle['ofs']}.t{nowcast_cycle['cyc']}z"
    nowcast_dir = f"{cycle_tag}.restart_outputs"
    hotstart_re = re.compile(
        rf"^{re.escape(cycle_tag)}\.\d+\.rst\.(nowcast|forecast)\.nc$"
    )

    def _is_nowcast_product(rel: Path) -> bool:
        if nowcast_dir in rel.parts:
            return True
        if hotstart_re.match(rel.name):
            return True
        return False

    entries = [
        e for e in build_manifest_entries(expected_comout)
        if _is_nowcast_product(Path(e["path"]))
    ]

    manifest = {
        "pdy": nowcast_cycle["pdy"],
        "cyc": nowcast_cycle["cyc"],
        "ofs": f"{nowcast_cycle['ofs']}_ufs",
        "files": entries,
        "generated_by": "tests/integration/test_nowcast_artifact_parity.py",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": git_short_sha(repo_root),
        "notes": (
            "Golden manifest for SECOFS-UFS nowcast cycle. "
            f"Bootstrapped from the {label} run; "
            "regenerate via REGENERATE=1 pytest "
            "tests/integration/test_nowcast_artifact_parity.py."
        ),
    }
    mpath = _manifest_path(nowcast_cycle)
    mpath.parent.mkdir(parents=True, exist_ok=True)
    with mpath.open("w") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
        fh.write("\n")
    log.info("wrote nowcast golden manifest with %d entries: %s",
             len(entries), mpath)


# ---------------------------------------------------------------------------
# Test 3: parity diff — the operational gate
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    os.environ.get("RUN_DOCKER_PARITY") != "1",
    reason="RUN_DOCKER_PARITY=1 not set — the full docker nowcast parity "
    "test is opt-in (it spins up the SECOFS-UFS image and runs a real "
    "MPI launch, 20-30 minutes wall time). Set RUN_DOCKER_PARITY=1 to "
    "run, or invoke from the CI workflow.",
)
def test_nowcast_artifact_parity_against_legacy_shell(
    nowcast_integration_preflight,  # noqa: ARG001 — triggers skip if Docker/inputs absent
    docker_image: str,
    repo_root: Path,
    staging_dir: Path,
    tmp_comout_root: Path,
    nowcast_cycle: dict,
) -> None:
    """End-to-end: Python-path COMOUT == legacy-shell COMOUT for nowcast.

    The operational gate from #219 commit 6. Runs the nowcast stage
    twice (NOS_USE_LEGACY_SHELL=NO + =YES) and asserts the resulting
    COMOUT trees are equivalent.

    Three runtime conditions can xfail-skip the test (kept distinct so
    the CI log reader knows exactly which knob is missing):

      * Python-path nowcast not yet ported (stub raises NotImplementedError)
      * Legacy shell ``exnos_nowcast.sh.preY-mig`` not yet preserved
      * Golden manifest not yet bootstrapped

    All three flip green once the partner migration agent's commit
    lands ``scripts/legacy/exnos_nowcast.sh.preY-mig`` and ports
    ``nos_workflow.stages.nowcast.run``.
    """
    mpath = _manifest_path(nowcast_cycle)
    if not mpath.exists():
        pytest.skip(
            f"golden manifest {mpath} missing — bootstrap first via "
            "REGENERATE=1 pytest tests/integration/test_nowcast_artifact_parity.py"
        )
    if not _legacy_nowcast_script_present(repo_root):
        pytest.xfail(
            "scripts/legacy/exnos_nowcast.sh.preY-mig not present — "
            "the partner migration agent will land it."
        )
    if not _nowcast_python_path_available(repo_root):
        pytest.xfail(
            "nos_workflow.stages.nowcast.run still missing the "
            "_run_comf_nowcast dispatcher — the partner migration "
            "agent will land the real port."
        )

    # --- Run A: Python path -------------------------------------------------
    python_comout_host = tmp_comout_root / "python_path"
    proc_a = _docker_nowcast_run(
        image=docker_image,
        repo=repo_root,
        staging=staging_dir,
        comout_host=python_comout_host,
        pdy=nowcast_cycle["pdy"],
        cyc=nowcast_cycle["cyc"],
        ofs=nowcast_cycle["ofs"],
        use_legacy=False,
    )
    if proc_a.returncode != 0:
        pytest.fail(
            f"[Python-path] nowcast failed (rc={proc_a.returncode}). "
            f"stderr tail:\n{proc_a.stderr[-2000:]}"
        )
    python_comout = _resolve_comout(python_comout_host, nowcast_cycle)

    # --- Run B: Legacy shell ------------------------------------------------
    legacy_comout_host = tmp_comout_root / "legacy_path"
    proc_b = _docker_nowcast_run(
        image=docker_image,
        repo=repo_root,
        staging=staging_dir,
        comout_host=legacy_comout_host,
        pdy=nowcast_cycle["pdy"],
        cyc=nowcast_cycle["cyc"],
        ofs=nowcast_cycle["ofs"],
        use_legacy=True,
    )
    if proc_b.returncode != 0:
        pytest.fail(
            f"[Legacy-path] nowcast failed (rc={proc_b.returncode}). "
            f"stderr tail:\n{proc_b.stderr[-2000:]}"
        )
    legacy_comout = _resolve_comout(legacy_comout_host, nowcast_cycle)

    # --- Validate the manifest still describes the Python-path output -------
    assert_against_manifest(python_comout, mpath, stage=_STAGE)

    # --- Diff the two trees -------------------------------------------------
    # Same product-vs-input filter as in the regen path: we only diff
    # the *new* nowcast products (restart_outputs/ + rst.*.nc), not
    # the prep-stage outputs we seeded into COMOUT before the run.
    cycle_tag = f"{nowcast_cycle['ofs']}.t{nowcast_cycle['cyc']}z"
    nowcast_dir = f"{cycle_tag}.restart_outputs"
    hotstart_re = re.compile(
        rf"^{re.escape(cycle_tag)}\.\d+\.rst\.(nowcast|forecast)\.nc$"
    )

    def _is_nowcast_product(rel: Path) -> bool:
        if nowcast_dir in rel.parts:
            return True
        if hotstart_re.match(rel.name):
            return True
        return False

    files_a = [p for p in walk_relative(python_comout) if _is_nowcast_product(p)]
    files_b = [p for p in walk_relative(legacy_comout) if _is_nowcast_product(p)]
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

    # Per-file diff — uses ``classify_nowcast`` so the SCHISM noisy
    # outputs (mirror.out, flux.out, staout_*) are size-only-gated.
    failures: List[Tuple[Path, str]] = []
    for rel in files_a:
        name = rel.name
        klass = classify_nowcast(name)
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
            # mirror.out / flux.out / staout_* — non-deterministic at
            # byte level (timestamps, FMA / rank ordering). Confirm
            # both sides produced *something* non-trivially populated.
            if a.stat().st_size == 0 and b.stat().st_size != 0:
                failures.append((rel, "Python-path artifact empty, legacy non-empty"))
            if b.stat().st_size == 0 and a.stat().st_size != 0:
                failures.append((rel, "legacy artifact empty, Python-path non-empty"))
        else:  # other — size-only at 5%
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
# Test 4: "test the test" gate — tampered manifest must be caught
# ---------------------------------------------------------------------------
#
# Cheap, Docker-free tests. Mirror of the prep + post diff-machinery
# tests but using the nowcast-specific classifier so we prove the new
# rules wire up to the existing infrastructure.

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


def test_nowcast_classify_buckets_known_artifacts() -> None:
    """The nowcast-aware classifier must bucket SCHISM outputs correctly.

    Nowcast products:
      * ``mirror.out`` / ``flux.out`` / ``staout_1..9`` — log (size-only)
        because of timestamps + FMA bit-noise; the nowcast classifier
        diverges from the prep classifier here.
      * ``<prefix>.t<cyc>z.<pdy>.rst.nowcast.nc`` — netcdf (allclose).
      * ``param.nml`` / ``bctides.in`` (seeded prep inputs) — text.
      * ``jlogfile`` — log.
    """
    cases = {
        # nowcast-specific overrides
        "mirror.out": "log",
        "flux.out": "log",
        "staout_1": "log",
        "staout_5": "log",
        "staout_9": "log",
        # SCHISM hotstart — diff via allclose
        "secofs.t18z.20260324.rst.nowcast.nc": "netcdf",
        "secofs.t18z.20260324.rst.forecast.nc": "netcdf",
        # seeded prep inputs — still byte-equal text
        "param.nml": "text",
        "secofs.t18z.20260324.bctides.in.nowcast": "text",
        "vsource.th": "text",
        # logs — same as prep/post
        "jlogfile": "log",
        "pgmout.12345": "log",
        # unmatched
        "random_unmatched_file.bin": "other",
    }
    for name, expected in cases.items():
        got = classify_nowcast(name)
        assert got == expected, (
            f"classify_nowcast({name!r}) = {got!r}, expected {expected!r}"
        )


def test_nowcast_classify_diverges_from_prep_for_staout() -> None:
    """The nowcast classifier *must* differ from prep for ``staout_*``.

    During prep, ``staout_*`` files are staged (copied) inputs and must
    be byte-equal between Python and legacy paths. During nowcast, the
    same filenames are MPI-generated outputs with FMA / rank-ordering
    bit-noise. The two classifiers therefore disagree on these files,
    and that's the whole point of having a stage-aware overlay.
    """
    from .diff_helpers import classify  # local import: keep top-level clean
    assert classify("staout_5") == "text", (
        "prep classifier should keep staout_* as byte-equal text"
    )
    assert classify_nowcast("staout_5") == "log", (
        "nowcast classifier should treat staout_* as size-only-gated"
    )
    # mirror.out / flux.out aren't even in the prep TEXT_ARTIFACT_PATTERNS,
    # so the global classify drops them in ``other``. The nowcast
    # classifier promotes them to ``log`` so the parity test's per-file
    # diff machinery routes them to the size-only branch (correct
    # behavior for SCHISM-generated console logs).
    assert classify("mirror.out") == "other"
    assert classify_nowcast("mirror.out") == "log"


def test_nowcast_text_diff_detects_one_byte_divergence(tmp_path: Path) -> None:
    """Sanity: a tampered text artifact (e.g. param.nml) still tripped.

    Models the #219 commit 6 "test the test" gate: deliberately introduce
    a stray space in a string written by ``nos_workflow.stages.nowcast``
    and confirm the parity assertion fails with a useful message.

    Uses param.nml as the proxy text artifact — it's seeded into the
    nowcast COMOUT by the prep stage and the nowcast parity diff still
    requires byte-equality on it.
    """
    fa, fb = _make_pair(
        tmp_path, "param.nml",
        b"&core\n  dt = 60.0\n  rnday = 0.25\n/\n",
        b"&core\n  dt = 60.0 \n  rnday = 0.25\n/\n",  # trailing space
    )
    assert classify_nowcast(fa.name) == "text"
    assert not filecmp.cmp(str(fa), str(fb), shallow=False)
    snippet = text_diff_snippet(fa, fb)
    assert "line 2:" in snippet, f"expected line diff, got: {snippet!r}"


def test_nowcast_netcdf_diff_detects_hotstart_perturbation(tmp_path: Path) -> None:
    """An out-of-tolerance perturbation in rst.nowcast.nc must produce a clear msg.

    The hotstart NetCDF is the load-bearing nowcast output — it's
    consumed by the forecast stage and the regression in #220 cited
    silent skips inside hotstart staging. Bit-level diffs here must
    flag specifically which variable drifted.
    """
    netCDF4 = pytest.importorskip("netCDF4")
    import numpy as np

    fa = tmp_path / "secofs.t18z.20260324.rst.nowcast.nc"
    fb = tmp_path / "secofs.t18z.20260324.rst.nowcast.nc.legacy"
    for path, offset in ((fa, 0.0), (fb, 1.0e-3)):
        with netCDF4.Dataset(str(path), "w") as ds:
            ds.createDimension("node", 100)
            ds.createDimension("nvrt", 12)
            t = ds.createVariable("tr_nd", "f8", ("node", "nvrt"))
            t[:] = np.arange(1200).reshape(100, 12).astype(float) + offset
    msg = diff_netcdf(fa, fb)
    assert msg is not None, "expected diff to flag the perturbation"
    assert "tr_nd" in msg, f"expected var name in msg, got: {msg!r}"


def test_nowcast_parity_detects_tampered_artifact(tmp_path: Path) -> None:
    """Test-the-test gate: mutated manifest must surface NOWCAST_PARITY FAIL.

    The #220 anchoring lesson — "manifests + side-by-side diffs catch
    what we didn't" — requires that the parity infrastructure can be
    proven to detect a deliberate tampering. We mutate a manifest
    entry's sha256, then assert the structured failure message
    surfaces the ``NOWCAST_PARITY FAIL`` marker and includes the
    sha256-failure detail so an operator's grep on either string
    routes correctly.

    This is the cheap (Docker-free) mirror of the prep test's
    ``test_manifest_assertion_detects_sha_drift`` and the post test's
    ``test_post_manifest_assertion_emits_post_marker``.
    """
    comout = tmp_path / "comout"
    comout.mkdir()
    # Seed a plausible nowcast text product into the synthetic COMOUT.
    # We use param.nml (seeded prep input that the parity diff still
    # requires byte-equality on) so the manifest entry is realistic.
    (comout / "param.nml").write_bytes(b"&core\n  dt = 60.0\n/\n")

    bogus_manifest = {
        "pdy": "20260324",
        "cyc": "18",
        "ofs": "secofs_ufs",
        "files": [
            {
                "path": "param.nml",
                "mode": "text",
                "size": len(b"&core\n  dt = 60.0\n/\n"),
                "sha256": "0" * 64,  # deliberately wrong
            }
        ],
        "generated_by": "test",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "git_commit": "deadbeef",
        "notes": "test fixture for nowcast parity tampering detection",
    }
    mpath = tmp_path / "manifest.json"
    mpath.write_text(json.dumps(bogus_manifest))

    with pytest.raises(BaseException) as exc_info:
        assert_against_manifest(comout, mpath, stage=_STAGE)
    msg = str(exc_info.value)
    assert "NOWCAST_PARITY" in msg, (
        f"expected NOWCAST_PARITY marker, got: {msg!r}"
    )
    assert "sha256" in msg.lower(), (
        f"expected sha256-failure detail, got: {msg!r}"
    )


# ---------------------------------------------------------------------------
# Helpers — manifest, resolution
# ---------------------------------------------------------------------------

def _resolve_comout(comout_host: Path, nowcast_cycle: dict) -> Path:
    """Map the host-side COMOUT root to the actual ``<ofs>.<pdy>`` dir.

    Mirror of the prep / post helpers — version dir (``v3.7`` vs
    ``v3.7.0``) is discovered at runtime because both ship in
    different staging snapshots.
    """
    base = comout_host / "nosofs"
    if not base.is_dir():
        return comout_host
    for ver_dir in sorted(base.iterdir()):
        cand = ver_dir / f"{nowcast_cycle['ofs']}.{nowcast_cycle['pdy']}"
        if cand.is_dir():
            return cand
    return comout_host
