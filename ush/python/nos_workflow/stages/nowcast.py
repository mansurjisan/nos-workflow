"""Nowcast stage entry point.

Both ``framework="comf"`` (SECOFS-UFS) and ``framework="stofs_ufs"``
(STOFS-3D-ATL-UFS) route through the UFS-Coastal implementation,
mirroring the pre-migration ``scripts/exnos_nowcast.sh``.
The COMF body executes the same 4-step interface the legacy shell drove:

    stage_model_files "nowcast"
    prepare_restart   "nowcast"
    execute_model     "nowcast"      # MPI launch of fv3_coastalS.exe
    archive_outputs   "nowcast"

Each step is invoked through ``bash_compat.run_shell_function`` against
``${USHnos}/nos_run.sh``. The MPI launch (``mpiexec ... fv3_coastalS.exe``)
and all the post-MPI cleanup (``combine_hotstart7``, NETCDF4_CLASSIC
``nccopy``, archive into ``$COMOUT``) live inside
``_schism_execute_ufs_coastal`` / ``_schism_archive_outputs`` in
``nos_run.sh``. Those stay in shell because:

  - ``module load`` (used to wire MPI, netCDF, ESMF compilers + libs)
    does not persist into a Python ``subprocess`` — by the time we
    re-exec, the modules are gone. The orchestration philosophy doc
    (#220) is explicit about keeping MPI launches in shell for exactly
    this reason.
  - ``LD_LIBRARY_PATH`` patches that ``combine_hotstart7`` needs (hpc-
    stack netcdf/4.7.4 lookup) are scoped per-shell-call; reimplementing
    them in Python would be ``os.environ`` mutation with no upside.

What this Python stage owns:

  - Phase header + UTC timestamping for ``OUTPUT.$$``
  - Validating ``$DATA`` exists and ``cd``-ing into it (mirrors
    ``mkdir -p $DATA; cd $DATA`` in the legacy shell)
  - Calling each of the 4 steps in sequence, surfacing the first
    non-zero rc as a ``StageFailedError`` so the CLI prints a clean
    FATAL one-liner instead of dumping a traceback
  - Forwarding the parent ``os.environ`` into each shell call (the
    J-job set up the full COMF env before we got here)

The standalone STOFS and ADCIRC branches raise ``NotImplementedError``
until tasks #33 / #34 land.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Tuple

from .._log import emit_stage_summary, stage_logger, timed_step
from ..bash_compat import postmsg, run_shell_function
from ..errors import StageFailedError
from ..registry import OFSDescriptor
from ..runners.schism_ufs import _flags as _runner_flags

if TYPE_CHECKING:
    # Forward-reference NCOEnv so the stage module doesn't import the
    # env module at collection time. The runtime parameter type is
    # structural.
    from ..env import NCOEnv  # noqa: F401


logger = logging.getLogger(__name__)


_STAGE = "nowcast"

# The 4-step contract from ``ush/nos_run.sh``. Order matters — each step
# depends on filesystem state laid down by the previous one.
_STEPS: Tuple[str, ...] = (
    "stage_model_files",
    "prepare_restart",
    "execute_model",
    "archive_outputs",
)


def run(descriptor: OFSDescriptor, env: "NCOEnv") -> int:
    """Execute the nowcast stage for ``descriptor``.

    Args:
        descriptor: The OFS descriptor returned by ``registry.lookup``.
        env: NCO environment bundle (PDY, cyc, COM paths, etc.).

    Returns:
        0 on success; a non-zero return code is surfaced from the first
        failing step in the 4-step contract.

    Raises:
        StageFailedError: any unexpected exception during the COMF body,
            a missing required env var, or an unknown framework.
        NotImplementedError: framework="stofs" (standalone STOFS-3D-ATL)
            or "adcirc" — stubs for tasks #33/#34.
    """
    sl = stage_logger(_STAGE, descriptor.name)
    sl.info("stage start")

    if descriptor.framework in ("comf", "stofs_ufs"):
        return _run_comf_nowcast(descriptor, env)
    if descriptor.framework == "stofs":
        raise NotImplementedError(
            "STOFS-3D-ATL nowcast not yet ported — task #33 on the roadmap"
        )
    if descriptor.framework == "adcirc":
        raise NotImplementedError(
            "STOFS-2D-GLO nowcast not yet ported — task #34"
        )

    raise StageFailedError(
        stage=_STAGE,
        ofs=descriptor.name,
        returncode=2,
        msg=f"unknown framework {descriptor.framework!r}",
    )


# ---------------------------------------------------------------------------
# COMF nowcast body
# ---------------------------------------------------------------------------


def _run_comf_nowcast(descriptor: OFSDescriptor, env: "NCOEnv") -> int:
    """COMF (SECOFS-UFS) nowcast: drive the 4-step contract in
    ``nos_run.sh`` end-to-end.

    Any unexpected exception is caught and re-raised as
    ``StageFailedError`` so the CLI's top-level handler prints a clean
    one-line FATAL instead of dumping a traceback to ``OUTPUT.$$``.
    """
    try:
        return _comf_nowcast_body(descriptor, env)
    except StageFailedError:
        raise
    except Exception as exc:  # noqa: BLE001 — wrap to StageFailedError
        raise StageFailedError(
            stage=_STAGE,
            ofs=descriptor.name,
            returncode=1,
            msg=f"unexpected exception in COMF nowcast: {exc}",
        ) from exc


def _comf_nowcast_body(descriptor: OFSDescriptor, env: "NCOEnv") -> int:
    """The actual COMF nowcast work; returns the first non-zero rc from
    the 4-step contract, or 0 if every step succeeded.
    """
    sl = stage_logger(_STAGE, descriptor.name)
    t_stage = time.monotonic()
    shell_env = os.environ
    ushnos = Path(_require_env(shell_env, "USHnos"))
    data = Path(_require_env(shell_env, "DATA"))

    # nos_run.sh holds every helper we call below.
    nos_run = ushnos / "nos_run.sh"
    if not nos_run.is_file():
        raise StageFailedError(
            stage=_STAGE,
            ofs=descriptor.name,
            returncode=1,
            msg=f"nos_run.sh not found at {nos_run}",
        )

    # The legacy shell did ``mkdir -p $DATA; cd $DATA`` before invoking
    # any of the 4 steps. ``stage_model_files`` itself does ``mkdir -p
    # $DATA/outputs`` but expects $DATA to already exist.
    data.mkdir(parents=True, exist_ok=True)

    sl.info("phase=NOWCAST (split-job mode) data=%s rnday=%s pdyhh_begin=%s",
            data,
            shell_env.get("RNDAY_NOWCAST", "<unset>"),
            shell_env.get("PDYHH_NCAST_BEGIN", "<unset>"))

    postmsg(f"exnos_nowcast.sh (nos_workflow) started ({descriptor.name})")

    for step in _STEPS:
        with timed_step(sl, step):
            rc = _run_step(step, nos_run, data, shell_env)
            if rc != 0:
                postmsg(f"FATAL: {step} nowcast failed (rc={rc})")
                emit_stage_summary(
                    sl, status="FAIL",
                    runtime_s=time.monotonic() - t_stage,
                    extras={"failed_step": step, "rc": rc},
                )
                raise StageFailedError(
                    stage=_STAGE,
                    ofs=descriptor.name,
                    returncode=rc,
                    msg=f"{step} nowcast failed (rc={rc})",
                )

    postmsg(f"Finished exnos_nowcast.sh (nos_workflow) SUCCESSFULLY ({descriptor.name})")
    emit_stage_summary(
        sl, status="PASS",
        runtime_s=time.monotonic() - t_stage,
        extras={"steps_completed": len(_STEPS)},
    )
    return 0


def _run_step(
    step: str,
    nos_run: Path,
    data: Path,
    shell_env: "os._Environ",
) -> int:
    """Invoke one step of the 4-step contract.

    When ``_runner_flags.is_python_enabled(step)`` returns True, the
    Python implementation handles ``step``; otherwise we shell out to
    ``nos_run.sh`` via ``bash_compat.run_shell_function``. PR 1 ships
    only the dispatcher scaffolding — no Python helpers exist yet — so
    any truthy flag logs a WARNING and falls through to shell with the
    original behavior intact. Subsequent PRs (#2 onwards) replace the
    WARNING with real Python dispatch one helper at a time.

    ``cwd=data`` mirrors the legacy ``cd $DATA`` before each helper.
    """
    if _runner_flags.is_python_enabled(step):
        if step in ("archive_outputs", "prepare_restart"):
            ctx = _build_schism_context(shell_env, data, "nowcast")
            if step == "archive_outputs":
                from ..runners.schism_ufs.archive import run_python as _archive_python
                return _archive_python(ctx, "nowcast")
            if step == "prepare_restart":
                from ..runners.schism_ufs.prepare_restart import (
                    run_python as _prepare_python,
                )
                return _prepare_python(ctx, "nowcast")
        if step == "stage_model_files":
            # PR 7c: dispatch to the full stage_files.run_python
            # orchestrator. Unlike archive/prepare_restart (which only
            # need the minimal SchismRunContext built from os.environ),
            # stage_files needs a fully-populated context with FIXofs
            # staging, filename conventions, and time anchors.  Build
            # via setup_paths.compute_paths() -- the PR 5 port that
            # mirrors the shell's _schism_setup_paths function.
            from ..env import NCOEnv
            from ..runners.schism_ufs.setup_paths import compute_paths
            from ..runners.schism_ufs.stage_files import (
                run_python as _stage_files_python,
            )
            env = NCOEnv.from_env(ofs=shell_env.get("OFS"))
            ctx = compute_paths(env, phase="nowcast", runtype="nowcast")
            return _stage_files_python(ctx, "nowcast")
        logger.warning(
            "NOS_WORKFLOW_PYTHON_* flag set for step=%r but no Python "
            "implementation has landed yet; falling back to shell.",
            step,
        )

    child_env = dict(shell_env)
    return run_shell_function(
        script=nos_run,
        function=step,
        args=("nowcast",),
        env=child_env,
        cwd=data,
    )


# ---------------------------------------------------------------------------
# Helpers (kept local so the nowcast stage stays self-contained).
# ---------------------------------------------------------------------------


def _build_schism_context(
    shell_env: "os._Environ",
    data: Path,
    phase: str,
):
    """Build a ``SchismRunContext`` for the given phase.

    Wraps ``SchismRunContext.from_env_and_phase`` so the dispatcher can
    keep its import local (the runner package is heavy-import-aware —
    pulling it in at module load would pin the schism_ufs imports
    even on shell-path runs)."""
    from ..runners.schism_ufs.context import SchismRunContext
    return SchismRunContext.from_env_and_phase(dict(shell_env), phase=phase)


def _require_env(env: "os._Environ", key: str) -> str:
    """Mirror ``post._require_env`` for plain ``os.environ``; raise
    ``StageFailedError`` with a useful message if unset/empty."""
    val = env.get(key)
    if val is None or val == "":
        raise StageFailedError(
            stage=_STAGE,
            ofs=env.get("OFS", "<unknown>"),
            returncode=1,
            msg=f"required NCO env var {key!r} not set",
        )
    return val


__all__ = ["run"]
