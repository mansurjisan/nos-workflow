"""Model completion signal from mirror.out (STOFS-3D-ATL)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Tuple

STATUS_NAME = "mirror.status"
_DONE = "Run completed successfully"
_STEP_RE = re.compile(r"TIME STEP=\s*(\d+)")
_PARAM_RE = r"(?im)^\s*{}\s*=\s*([0-9.]+(?:[eEdD][+-]?\d+)?)"


def _param(text: str, key: str) -> Optional[float]:
    m = re.search(_PARAM_RE.format(key), text)
    return float(m.group(1).lower().replace("d", "e")) if m else None


def check_mirror_out(mirror: Path, param_nml: Optional[Path], coupled: bool) -> Tuple[bool, str]:
    """Standalone: the "Run completed successfully" line. Coupled mirror.out has no such line,
    so its last "TIME STEP=" must equal rnday*86400/dt from param.nml. MJ (10/05/26)
    """
    if not mirror.is_file() or mirror.stat().st_size == 0:
        return False, f"{mirror} missing or empty"
    with mirror.open("rb") as fh:
        fh.seek(0, 2)
        fh.seek(max(0, fh.tell() - 65536))
        tail = fh.read().decode("utf-8", "replace")
    if not coupled:
        if _DONE in tail:
            return True, "Run completed successfully"
        return False, f'"{_DONE}" not found in {mirror}'
    steps = _STEP_RE.findall(tail)
    if not steps:
        return False, f'no "TIME STEP=" line in {mirror}'
    if param_nml is None or not param_nml.is_file():
        return False, f"param.nml not available to derive the expected step count"
    text = param_nml.read_text()
    rnday, dt = _param(text, "rnday"), _param(text, "dt")
    if not rnday or not dt:
        return False, f"rnday/dt not readable from {param_nml}"
    expect = int(round(rnday * 86400.0 / dt))
    last = int(steps[-1])
    if last != expect:
        return False, f"last TIME STEP={last}, expected {expect} (rnday={rnday}, dt={dt})"
    return True, f"TIME STEP={last} of {expect}"
