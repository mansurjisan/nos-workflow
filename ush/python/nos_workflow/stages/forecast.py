"""Forecast stage entry point.

Both ``framework="comf"`` (SECOFS-UFS) and ``framework="stofs_ufs"``
(STOFS-3D-ATL-UFS) route through the UFS-Coastal implementation,
mirroring the pre-migration ``scripts/exnos_forecast.sh``.
The COMF body executes the same 4-step interface the legacy shell drove:

    stage_model_files "forecast"
    prepare_restart   "forecast"
    execute_model     "forecast"      # MPI launch of fv3_coastalS.exe
    archive_outputs   "forecast"

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

Forecast-specific delta vs nowcast (all handled inside ``nos_run.sh``
by branching on the ``"forecast"`` phase arg, NOT here):

  - ``prepare_restart "forecast"`` picks up the combined hotstart from
    THIS cycle's nowcast (``${COMOUT}/${RUN}.${cycle}.${PDY}.rst.nowcast.nc``),
    not yesterday's COMOUT init. Operationally the nowcast job is a
    hard dependency of the forecast job.
  - The forecast uses ``RNDAY_FORECAST`` and ``PDYHH_FCAST_BEGIN`` env
    vars (vs nowcast's ``RNDAY_NOWCAST`` / ``PDYHH_NCAST_BEGIN``).
  - ``archive_outputs "forecast"`` writes to
    ``${COMOUT}/${RUN}.${cycle}.${PDY}.forecast_outputs/`` (vs
    ``.restart_outputs/`` for nowcast).

Deferred follow-up (do NOT fix in this commit): the forecast also
produces ``rst.forecast.nc`` (the combined hotstart at end-of-forecast).
The same ``rtol=1e-12`` strict-equality concern from commit 6c
(``ad6c36f``) applies to that artifact in the parity integration test.
Strict gate is the right default for now; the deferred concern is to
allow a small ``rtol`` if reproducibility on the BFB platform turns out
to be brittle. Logged here so future reviewers can find it.

What this Python stage owns:

  - Phase header + UTC timestamping for ``OUTPUT.$$``
  - Validating ``$DATA`` exists and ``cd``-ing into it (mirrors
    ``mkdir -p $DATA; cd $DATA`` in the legacy shell)
  - Calling each of the 4 steps in sequence, surfacing the first
    non-zero rc as a ``StageFailedError`` so the CLI prints a clean
    FATAL one-liner instead of dumping a traceback
  - Forwarding the parent ``os.environ`` into each shell call (the
    J-job set up the full COMF env before we got here)
  - ``postmsg`` observability at start, per-step failure, and success
    (matches commit 6c audit pattern from ``ad6c36f``)

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


_STAGE = "forecast"

# The 4-step contract from ``ush/nos_run.sh``. Order matters — each step
# depends on filesystem state laid down by the previous one.
_STEPS: Tuple[str, ...] = (
    "stage_model_files",
    "prepare_restart",
    "execute_model",
    "archive_outputs",
)


def run(descriptor: OFSDescriptor, env: "NCOEnv") -> int:
    """Execute the forecast stage for ``descriptor``.

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
        return _run_comf_forecast(descriptor, env)
    if descriptor.framework == "stofs":
        raise NotImplementedError(
            "STOFS-3D-ATL forecast not yet ported — task #33 on the roadmap"
        )
    if descriptor.framework == "adcirc":
        raise NotImplementedError(
            "STOFS-2D-GLO forecast not yet ported — task #34"
        )

    raise StageFailedError(
        stage=_STAGE,
        ofs=descriptor.name,
        returncode=2,
        msg=f"unknown framework {descriptor.framework!r}",
    )


# ---------------------------------------------------------------------------
# COMF forecast body
# ---------------------------------------------------------------------------


def _run_comf_forecast(descriptor: OFSDescriptor, env: "NCOEnv") -> int:
    """COMF (SECOFS-UFS) forecast: drive the 4-step contract in
    ``nos_run.sh`` end-to-end.

    Any unexpected exception is caught and re-raised as
    ``StageFailedError`` so the CLI's top-level handler prints a clean
    one-line FATAL instead of dumping a traceback to ``OUTPUT.$$``.
    """
    try:
        return _comf_forecast_body(descriptor, env)
    except StageFailedError:
        raise
    except Exception as exc:  # noqa: BLE001 — wrap to StageFailedError
        raise StageFailedError(
            stage=_STAGE,
            ofs=descriptor.name,
            returncode=1,
            msg=f"unexpected exception in COMF forecast: {exc}",
        ) from exc


def _comf_forecast_body(descriptor: OFSDescriptor, env: "NCOEnv") -> int:
    """The actual COMF forecast work; returns the first non-zero rc from
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

    sl.info("phase=FORECAST (split-job mode) data=%s rnday=%s pdyhh_begin=%s",
            data,
            shell_env.get("RNDAY_FORECAST", "<unset>"),
            shell_env.get("PDYHH_FCAST_BEGIN", "<unset>"))

    postmsg(f"exnos_forecast.sh (nos_workflow) started ({descriptor.name})")

    for step in _STEPS:
        with timed_step(sl, step):
            rc = _run_step(step, nos_run, data, shell_env)
            if rc != 0:
                postmsg(f"FATAL: {step} forecast failed (rc={rc})")
                emit_stage_summary(
                    sl, status="FAIL",
                    runtime_s=time.monotonic() - t_stage,
                    extras={"failed_step": step, "rc": rc},
                )
                raise StageFailedError(
                    stage=_STAGE,
                    ofs=descriptor.name,
                    returncode=rc,
                    msg=f"{step} forecast failed (rc={rc})",
                )

    postmsg(f"Finished exnos_forecast.sh (nos_workflow) SUCCESSFULLY ({descriptor.name})")
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
        if step == "archive_outputs":
            from ..runners.schism_ufs.archive import run_python as _archive_python
            from ..runners.schism_ufs.context import SchismRunContext
            ctx = SchismRunContext(
                comout=Path(shell_env["COMOUT"]),
                data=data,
                phase="forecast",
                run=shell_env["RUN"],
                cycle=shell_env["cycle"],
            )
            return _archive_python(ctx, "forecast")
        logger.warning(
            "NOS_WORKFLOW_PYTHON_* flag set for step=%r but no Python "
            "implementation has landed yet; falling back to shell.",
            step,
        )

    child_env = dict(shell_env)
    return run_shell_function(
        script=nos_run,
        function=step,
        args=("forecast",),
        env=child_env,
        cwd=data,
    )


# ---------------------------------------------------------------------------
# Helpers (kept local so the forecast stage stays self-contained).
# ---------------------------------------------------------------------------


def _require_env(env: "os._Environ", key: str) -> str:
    """Mirror ``nowcast._require_env`` for plain ``os.environ``; raise
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
