"""Subprocess and shell-bridge utilities for the workflow driver."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator, List, Optional, Sequence, Union

from .errors import StageFailedError

logger = logging.getLogger(__name__)


@contextmanager
def preserve_preload() -> Iterator[None]:
    """Save, unset, then restore ``LD_PRELOAD`` around the body.

    COMF Fortran executables need ``libnetcdff.so`` preloaded, but Python
    processes that import numpy / netCDF4 segfault when that library is
    force-loaded into the interpreter.
    """
    saved = os.environ.get("LD_PRELOAD")
    if saved is not None:
        del os.environ["LD_PRELOAD"]
    try:
        yield
    finally:
        if saved is not None:
            os.environ["LD_PRELOAD"] = saved


def postmsg(msg: str, jlogfile: Optional[str] = None) -> None:
    """Best-effort wrapper around NCO ``prod_util`` ``postmsg``. Never raises."""
    log_target = jlogfile or os.environ.get("jlogfile")
    binary = shutil.which("postmsg")
    if binary is None or not log_target:
        logger.warning("postmsg unavailable (jlogfile=%s): %s", log_target, msg)
        return
    try:
        subprocess.run([binary, log_target, msg], check=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("postmsg failed (%s): %s", exc, msg)


def err_chk(rc: int, message: str = "") -> None:
    """Raise ``StageFailedError`` on non-zero rc."""
    if rc != 0:
        raise StageFailedError(
            stage="<unknown>",
            ofs="<unknown>",
            returncode=rc,
            msg=message or "non-zero return code from external command",
        )


def run_shell_function(
    script: Union[str, Path],
    function: str,
    args: Sequence[str] = (),
    env: Optional[dict] = None,
    cwd: Optional[Path] = None,
) -> int:
    """Source ``script`` and invoke ``function`` with ``args``."""
    script_path = Path(script)
    if not script_path.is_file():
        raise StageFailedError(
            stage="<unknown>",
            ofs="<unknown>",
            returncode=2,
            msg=f"shell script not found: {script_path}",
        )
    quoted_args = " ".join(_shell_quote(a) for a in args)
    cmd = ["bash", "-c", f"source {_shell_quote(str(script_path))} && {function} {quoted_args}"]
    proc = subprocess.run(
        cmd,
        env=env if env is not None else {},
        cwd=str(cwd) if cwd is not None else None,
        check=False,
    )
    return proc.returncode


def cyc_str(cyc: Union[int, str, None]) -> str:
    """Zero-pad ``cyc`` to two digits."""
    if cyc is None or cyc == "":
        raise ValueError("cyc must be set (int 0..23 or string '00'..'23')")
    try:
        n = int(cyc)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"cyc not coercible to int: {cyc!r}") from exc
    if not 0 <= n <= 23:
        raise ValueError(f"cyc out of range 0..23: {cyc!r}")
    return f"{n:02d}"


def _shell_quote(s: str) -> str:
    """Single-quote ``s`` for safe inclusion in a bash -c string."""
    return "'" + s.replace("'", "'\\''") + "'"


__all__: List[str] = [
    "preserve_preload",
    "postmsg",
    "err_chk",
    "run_shell_function",
    "cyc_str",
]
