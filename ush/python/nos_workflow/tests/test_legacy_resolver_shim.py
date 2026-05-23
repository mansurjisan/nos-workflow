"""The legacy resolver must be a thin re-export of the canonical one.

``ush/python/utils/yaml_to_env.py`` is the file ``nos_config.sh`` runs for
operational shell env exports. It must re-export
``nos_workflow.utils.yaml_to_env`` so the two can never drift (the dual-resolver
keep-in-sync hazard). We assert the public functions are the SAME objects — not
copies — which makes drift structurally impossible, and we exercise the actual
script invocation path that ``nos_config.sh`` uses.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

from nos_workflow.utils import yaml_to_env as canonical


# .../nos_workflow/tests/test_*.py
_TESTS_DIR = Path(__file__).resolve()
_LEGACY_PATH = _TESTS_DIR.parents[2] / "utils" / "yaml_to_env.py"          # ush/python/utils/...
_CANONICAL_PATH = _TESTS_DIR.parents[1] / "utils" / "yaml_to_env.py"       # ush/python/nos_workflow/utils/...
_REPO_ROOT = _TESTS_DIR.parents[4]                                          # .../nos_ofs


def _load_legacy_module():
    spec = importlib.util.spec_from_file_location("_legacy_yaml_to_env", _LEGACY_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_legacy_resolver_is_a_reexport_of_canonical():
    """Every public symbol in the legacy file must BE the canonical object."""
    legacy = _load_legacy_module()
    for name in canonical.__all__:
        assert getattr(legacy, name) is getattr(canonical, name), (
            f"legacy.{name} is not the canonical object — the resolvers have "
            "drifted; the legacy file must re-export nos_workflow.utils.yaml_to_env"
        )


def test_legacy_version_matches_canonical():
    legacy = _load_legacy_module()
    assert legacy.__version__ == canonical.__version__


@pytest.mark.parametrize("ofs", ["secofs_ufs", "stofs_3d_atl_ufs"])
def test_legacy_shim_script_matches_canonical(ofs):
    """nos_config.sh runs `python3 <legacy> <cfg> --framework comf`. The shim
    must execute (sys.path bootstrap works) and produce byte-identical output
    to the canonical resolver for the running UFS systems."""
    cfg = _REPO_ROOT / "parm" / "systems" / f"{ofs}.yaml"
    if not cfg.is_file():
        pytest.skip(f"{cfg} not found")
    env = {**os.environ, "HOMEnos": str(_REPO_ROOT), "PDY": "20260101", "cyc": "00"}

    def _run(script: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(script), str(cfg), "--framework", "comf"],
            capture_output=True, text=True, env=env,
        )

    legacy = _run(_LEGACY_PATH)
    canon = _run(_CANONICAL_PATH)
    assert legacy.returncode == 0, legacy.stderr
    assert legacy.stdout == canon.stdout
