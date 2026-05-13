"""Nowcast stage entry point."""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Tuple

from .._log import emit_stage_summary, stage_logger, timed_step
from ..bash_compat import postmsg
from ..errors import StageFailedError
from ..registry import OFSDescriptor

if TYPE_CHECKING:
    from ..env import NCOEnv  # noqa: F401


_STAGE = "nowcast"

_STEPS: Tuple[str, ...] = (
    "stage_model_files",
    "prepare_restart",
    "execute_model",
    "archive_outputs",
)


def run(descriptor: OFSDescriptor, env: "NCOEnv") -> int:
    """Execute the nowcast stage for ``descriptor``."""
    sl = stage_logger(_STAGE, descriptor.name)
    sl.info("stage start")

    if descriptor.framework in ("comf", "stofs_ufs"):
        return _run_comf_nowcast(descriptor, env)
    if descriptor.framework == "stofs":
        raise NotImplementedError("STOFS-3D-ATL nowcast not yet ported")
    if descriptor.framework == "adcirc":
        raise NotImplementedError("STOFS-2D-GLO nowcast not yet ported")

    raise StageFailedError(
        stage=_STAGE,
        ofs=descriptor.name,
        returncode=2,
        msg=f"unknown framework {descriptor.framework!r}",
    )


def _run_comf_nowcast(descriptor: OFSDescriptor, env: "NCOEnv") -> int:
    """COMF (SECOFS-UFS) nowcast: drive the 4-step contract."""
    try:
        return _comf_nowcast_body(descriptor, env)
    except StageFailedError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise StageFailedError(
            stage=_STAGE,
            ofs=descriptor.name,
            returncode=1,
            msg=f"unexpected exception in COMF nowcast: {exc}",
        ) from exc


def _comf_nowcast_body(descriptor: OFSDescriptor, env: "NCOEnv") -> int:
    """Run the 4-step contract; return first non-zero rc or 0."""
    sl = stage_logger(_STAGE, descriptor.name)
    t_stage = time.monotonic()
    shell_env = os.environ
    _require_env(shell_env, "USHnos")
    data = Path(_require_env(shell_env, "DATA"))

    data.mkdir(parents=True, exist_ok=True)

    sl.info("phase=NOWCAST (split-job mode) data=%s rnday=%s pdyhh_begin=%s",
            data,
            shell_env.get("RNDAY_NOWCAST", "<unset>"),
            shell_env.get("PDYHH_NCAST_BEGIN", "<unset>"))

    postmsg(f"exnos_nowcast.sh (nos_workflow) started ({descriptor.name})")

    for step in _STEPS:
        with timed_step(sl, step):
            rc = _run_step(step, data, shell_env)
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
    data: Path,
    shell_env: "os._Environ",
) -> int:
    """Invoke one step of the 4-step contract (Python-only)."""
    if step == "stage_model_files":
        from ..env import NCOEnv
        from ..runners.schism_ufs.setup_paths import compute_paths
        from ..runners.schism_ufs.stage_files import (
            run_python as _stage_files_python,
        )
        env = NCOEnv.from_env(ofs=shell_env.get("OFS"))
        ctx = compute_paths(env, phase="nowcast", runtype="nowcast")
        return _stage_files_python(ctx, "nowcast")
    elif step == "prepare_restart":
        ctx = _build_schism_context(shell_env, data, "nowcast")
        from ..runners.schism_ufs.prepare_restart import (
            run_python as _prepare_python,
        )
        return _prepare_python(ctx, "nowcast")
    elif step == "execute_model":
        from ..env import NCOEnv
        from ..runners.schism_ufs.execute import run_python as _execute_python
        from ..runners.schism_ufs.setup_paths import compute_paths
        env = NCOEnv.from_env(ofs=shell_env.get("OFS"))
        ctx = compute_paths(env, phase="nowcast", runtype="nowcast")
        return _execute_python(ctx, "nowcast")
    elif step == "archive_outputs":
        ctx = _build_schism_context(shell_env, data, "nowcast")
        from ..runners.schism_ufs.archive import run_python as _archive_python
        return _archive_python(ctx, "nowcast")
    else:
        raise StageFailedError(
            stage=_STAGE,
            ofs=shell_env.get("OFS", "<unknown>"),
            returncode=1,
            msg=f"unknown step {step!r}",
        )


def _build_schism_context(
    shell_env: "os._Environ",
    data: Path,
    phase: str,
):
    """Build a ``SchismRunContext`` for the given phase."""
    from ..runners.schism_ufs.context import SchismRunContext
    return SchismRunContext.from_env_and_phase(dict(shell_env), phase=phase)


def _require_env(env: "os._Environ", key: str) -> str:
    """Return ``env[key]`` or raise ``StageFailedError`` if unset/empty."""
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
