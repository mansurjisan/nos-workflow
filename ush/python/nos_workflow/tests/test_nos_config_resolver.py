"""P2: ush/nos_config.sh must resolve the CANONICAL yaml_to_env
(nos_workflow/utils/) — not the legacy shim — and successfully load YAML into
shell exports. Exercises the real operational sourcing path used by the J-jobs.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_NOS_CONFIG = _REPO_ROOT / "ush" / "nos_config.sh"
_SECOFS_YAML = _REPO_ROOT / "parm" / "systems" / "secofs_ufs.yaml"

_CANONICAL_SUFFIX = "ush/python/nos_workflow/utils/yaml_to_env.py"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")
def test_nos_config_resolves_canonical_and_loads_yaml():
    if not _NOS_CONFIG.is_file() or not _SECOFS_YAML.is_file():
        pytest.skip("nos_config.sh or secofs_ufs.yaml not found")

    # Source nos_config.sh exactly as a J-job would, then load a real config.
    script = f"""
export HOMEnos="{_REPO_ROOT}"
export OFS=secofs_ufs PDY=20260101 cyc=00
source "{_NOS_CONFIG}"
echo "RESOLVER=$_ofs_yaml_to_env"
load_ofs_config "{_SECOFS_YAML}" comf >/dev/null 2>&1
echo "SOURCE=${{OFS_CONFIG_SOURCE:-none}}"
echo "OCEAN_MODEL=${{OCEAN_MODEL:-}}"
echo "PREFIXNOS=${{PREFIXNOS:-}}"
"""
    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout

    # P2: the resolver picked must be the canonical one, not the shim.
    resolver = next(ln for ln in out.splitlines() if ln.startswith("RESOLVER="))
    assert resolver.endswith(_CANONICAL_SUFFIX), f"resolver not canonical: {resolver}"

    # Config came from YAML (the resolver actually ran), not the hardcoded
    # _load_defaults fallback.
    assert "SOURCE=yaml" in out, out
    assert "OCEAN_MODEL=SCHISM" in out, out
    assert "PREFIXNOS=secofs_ufs" in out, out
