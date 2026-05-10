"""Nowcast stage entry point.

Right now only ``framework="comf"`` (SECOFS-UFS) has a real
implementation, mirroring the pre-migration ``scripts/exnos_nowcast.sh``.
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

The STOFS and ADCIRC branches raise ``NotImplementedError`` until
tasks #33 / #34 land.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Tuple

from ..bash_compat import run_shell_function
from ..errors import StageFailedError
from ..registry import OFSDescriptor

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


def _phase_header(ofs: str) -> None:
    """Emit the one-line phase header used by the J-job ``OUTPUT.$$`` log."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    logger.info("[%s] [%s] [%s] entered", ts, _STAGE, ofs)


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
        NotImplementedError: framework other than ``"comf"``; STOFS and
            ADCIRC branches are stubbed for tasks #33 / #34.
    """
    _phase_header(descriptor.name)

    if descriptor.framework == "comf":
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

    logger.info("=============================================")
    logger.info("=== NOWCAST PHASE (split-job mode) ===")
    logger.info("=============================================")
    logger.info("  OFS:            %s", descriptor.name)
    logger.info("  DATA:           %s", data)
    logger.info("  RNDAY_NOWCAST:  %s", shell_env.get("RNDAY_NOWCAST", "<unset>"))
    logger.info("  PDYHH_NCAST_BEGIN: %s",
                shell_env.get("PDYHH_NCAST_BEGIN", "<unset>"))
    logger.info("=============================================")

    for step in _STEPS:
        logger.info("--- nowcast step: %s ---", step)
        rc = _run_step(step, nos_run, data, shell_env)
        if rc != 0:
            raise StageFailedError(
                stage=_STAGE,
                ofs=descriptor.name,
                returncode=rc,
                msg=f"{step} nowcast failed (rc={rc})",
            )

    logger.info("=============================================")
    logger.info("COMF nowcast completed normally")
    logger.info("=============================================")
    return 0


def _run_step(
    step: str,
    nos_run: Path,
    data: Path,
    shell_env: "os._Environ",
) -> int:
    """Invoke one step of the 4-step contract via ``bash_compat``.

    We pass the full parent env explicitly (``env=os.environ.copy()``)
    so the shell sees every NCO + module-loader var the J-job set up.
    ``run_shell_function`` raises ``StageFailedError`` only if the
    script itself is missing; non-zero rc from the function body
    propagates back here as an int we handle in the caller.

    ``cwd=data`` mirrors the legacy ``cd $DATA`` before each helper.
    """
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
