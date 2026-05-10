"""Tests for the YAML-to-shell environment-variable bridge.

Ports the legacy ``ush/python/tests/test_yaml_to_env.py`` (renaming
``nos_ofs.utils.yaml_to_env`` -> ``nos_workflow.utils.yaml_to_env``)
and adds three new cases that pin behaviour the forensic review called
out as load-bearing:

    * ``_base`` deep-merge inheritance with a child overriding a single
      nested key.
    * ``cyc`` zero-pad invariant (``cyc=0`` -> ``cyc=00``).
    * Malformed-YAML error path: structured one-liner on stderr, no
      traceback, non-zero exit.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterator

import pytest

# Make ``nos_workflow`` importable when the suite is run from the
# package root via ``python -m pytest tests/``. Mirrors the legacy
# layout helper.
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from nos_workflow.utils.yaml_to_env import (  # noqa: E402
    deep_merge,
    export_for_shell,
    format_shell_exports,
    get_runtime_from_env,
    load_yaml_with_inheritance,
)


# ---------------------------------------------------------------------------
# Legacy ports (renamed to nos_workflow)
# ---------------------------------------------------------------------------


class TestYamlToEnv:
    """Tests for YAML to shell environment export."""

    def test_basic_export(self) -> None:
        """Test basic YAML to shell export."""
        yaml_content = """
system:
  name: test_ofs
  framework: comf

grid:
  n_nodes: 1000
  domain:
    lon_min: -80.0
    lon_max: -70.0
    lat_min: 30.0
    lat_max: 40.0
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        try:
            output = export_for_shell(temp_path, framework="comf")

            assert isinstance(output, str)
            assert "export" in output or "=" in output
        finally:
            os.unlink(temp_path)

    def test_stofs_framework_export(self) -> None:
        """Test export for STOFS framework (LONMIN/LONMAX style)."""
        yaml_content = """
system:
  name: stofs_3d_atl
  framework: stofs

grid:
  n_nodes: 1813443
  n_elements: 3564104
  n_levels: 51
  domain:
    lon_min: -98.5035
    lon_max: -52.4867
    lat_min: 7.347
    lat_max: 52.5904
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        try:
            output = export_for_shell(temp_path, framework="stofs")

            assert "LONMIN" in output
            assert "LONMAX" in output
        finally:
            os.unlink(temp_path)

    def test_comf_framework_export(self) -> None:
        """Test export for COMF framework (MINLON/MAXLON style)."""
        yaml_content = """
system:
  name: secofs
  framework: comf

grid:
  n_nodes: 1684786
  domain:
    lon_min: -88.0
    lon_max: -63.0
    lat_min: 17.0
    lat_max: 40.0
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        try:
            output = export_for_shell(temp_path, framework="comf")

            assert "MINLON" in output
            assert "MAXLON" in output
        finally:
            os.unlink(temp_path)

    def test_auto_framework_detection(self) -> None:
        """Test automatic framework detection from config."""
        yaml_stofs = """
system:
  name: stofs_3d_atl
  framework: stofs
grid:
  domain:
    lon_min: -98.0
    lon_max: -52.0
    lat_min: 7.0
    lat_max: 52.0
"""
        yaml_comf = """
system:
  name: secofs
  framework: comf
grid:
  domain:
    lon_min: -88.0
    lon_max: -63.0
    lat_min: 17.0
    lat_max: 40.0
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_stofs)
            temp_stofs = f.name

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_comf)
            temp_comf = f.name

        try:
            output_stofs = export_for_shell(temp_stofs, framework="auto")
            output_comf = export_for_shell(temp_comf, framework="auto")

            assert isinstance(output_stofs, str)
            assert isinstance(output_comf, str)
            # STOFS auto-detect should pick the LONMIN naming.
            assert "LONMIN" in output_stofs
            # COMF auto-detect should pick the MINLON naming.
            assert "MINLON" in output_comf
        finally:
            os.unlink(temp_stofs)
            os.unlink(temp_comf)

    def test_shell_safe_output(self) -> None:
        """Test that output is safe for shell eval."""
        yaml_content = """
system:
  name: test_ofs
  description: "Test OFS with special chars: $HOME `command`"

grid:
  domain:
    lon_min: -80.0
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        try:
            output = export_for_shell(temp_path, framework="comf")
            assert isinstance(output, str)
        finally:
            os.unlink(temp_path)

    def test_nested_value_flattening(self) -> None:
        """Test flattening of nested YAML values."""
        yaml_content = """
forcing:
  atmospheric:
    primary: gfs
    hrrr_blend:
      enabled: true
      lon_min: -98.5
      lon_max: -49.5
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        try:
            output = export_for_shell(temp_path, framework="stofs")
            assert isinstance(output, str)
        finally:
            os.unlink(temp_path)


class TestEnvEval:
    """Tests for evaluating exported environment in shell context."""

    def test_export_can_be_sourced(self) -> None:
        """Test that export output can be sourced in bash."""
        yaml_content = """
system:
  name: eval_test
grid:
  n_nodes: 500
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        sh_path = None
        try:
            output = export_for_shell(temp_path, framework="comf")

            with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as sh:
                sh.write("#!/bin/bash\n")
                sh.write(output)
                sh.write('\necho "SUCCESS"\n')
                sh_path = sh.name

            assert output is not None
        finally:
            os.unlink(temp_path)
            if sh_path is not None:
                os.unlink(sh_path)


# ---------------------------------------------------------------------------
# New tests (forensic-review follow-ups)
# ---------------------------------------------------------------------------


@pytest.fixture
def base_dir(tmp_path: Path) -> Iterator[Path]:
    """Construct a ``parm/`` skeleton with ``base/`` and ``systems/`` subdirs.

    Mirrors the production ``parm/`` layout so the inheritance loader's
    base-directory search resolves the ``_base`` reference correctly.
    """
    parm = tmp_path / "parm"
    (parm / "base").mkdir(parents=True)
    (parm / "systems").mkdir(parents=True)
    yield parm


class TestBaseInheritance:
    """``_base`` deep-merge inheritance must keep working."""

    def test_child_overrides_one_nested_key(self, base_dir: Path) -> None:
        """A child YAML extending a base overrides one nested key only.

        Two layers:
            * base/schism_test.yaml: model.physics.dt=150, model.physics.itur=3
            * systems/child.yaml extends schism_test, overriding model.physics.dt=120.

        The merged config must show dt=120 (from child) and itur=3 (from base).
        """
        base_path = base_dir / "base" / "schism_test.yaml"
        base_path.write_text(
            "model:\n"
            "  type: schism\n"
            "  physics:\n"
            "    dt: 150.0\n"
            "    itur: 3\n"
            "grid:\n"
            "  n_levels: 51\n"
        )
        child_path = base_dir / "systems" / "child.yaml"
        child_path.write_text(
            "_base: schism_test\n"
            "system:\n"
            "  name: child_ofs\n"
            "  framework: comf\n"
            "model:\n"
            "  physics:\n"
            "    dt: 120.0\n"
            "grid:\n"
            "  n_nodes: 1000\n"
        )

        # ``export_for_shell`` is what the operational CLI calls; it
        # walks ``systems`` -> ``parm`` so the inheritance loader can
        # find ``parm/base/<name>.yaml``.
        merged = load_yaml_with_inheritance(child_path, base_dir=base_dir)

        assert merged["model"]["physics"]["dt"] == 120.0
        assert merged["model"]["physics"]["itur"] == 3
        assert merged["model"]["type"] == "schism"
        assert merged["grid"]["n_nodes"] == 1000
        assert merged["grid"]["n_levels"] == 51
        assert merged["system"]["name"] == "child_ofs"

    def test_export_uses_inherited_values(self, base_dir: Path) -> None:
        """Shell export must include keys whose values come from the base."""
        base_path = base_dir / "base" / "schism_test.yaml"
        base_path.write_text(
            "model:\n"
            "  type: schism\n"
            "  physics:\n"
            "    dt: 150.0\n"
            "  run:\n"
            "    hindcast_days: 0.25\n"
            "    forecast_days: 5.0\n"
            "grid:\n"
            "  n_levels: 51\n"
        )
        child_path = base_dir / "systems" / "child.yaml"
        child_path.write_text(
            "_base: schism_test\n"
            "system:\n"
            "  name: child_ofs\n"
            "  framework: comf\n"
            "grid:\n"
            "  n_nodes: 1000\n"
            "  domain:\n"
            "    lon_min: -80.0\n"
            "    lon_max: -70.0\n"
            "    lat_min: 30.0\n"
            "    lat_max: 40.0\n"
        )

        output = export_for_shell(child_path, framework="comf")

        # DELT_MODEL comes straight from the base's model.physics.dt.
        assert "export DELT_MODEL=150.0" in output
        # nvrt comes from the base's grid.n_levels.
        assert "export nvrt=51" in output

    def test_deep_merge_preserves_base(self) -> None:
        """``deep_merge`` must not mutate the ``base`` dict."""
        base = {"a": {"b": 1, "c": 2}}
        override = {"a": {"b": 99}}

        merged = deep_merge(base, override)

        assert base == {"a": {"b": 1, "c": 2}}, "deep_merge mutated the base dict"
        assert merged == {"a": {"b": 99, "c": 2}}


class TestCycZeroPad:
    """``cyc`` must always serialize as a two-digit string."""

    def test_cyc_zero_yaml_value(self, base_dir: Path) -> None:
        """``cyc: 0`` from the runtime env must export as ``cyc=00``."""
        config_path = base_dir / "systems" / "small.yaml"
        config_path.write_text(
            "system:\n"
            "  name: small\n"
            "  framework: comf\n"
            "grid:\n"
            "  n_nodes: 100\n"
            "  domain:\n"
            "    lon_min: -80.0\n"
            "    lon_max: -70.0\n"
            "    lat_min: 30.0\n"
            "    lat_max: 40.0\n"
        )

        os.environ["cyc"] = "0"
        os.environ["PDY"] = "20260510"

        output = export_for_shell(config_path, framework="comf")

        assert "export cyc=00" in output
        assert "export cyc=0\n" not in output + "\n"
        # Bonus: PDYHH_NCAST_BEGIN must consume cyc=00 too, so the
        # cycle datetime parses correctly.
        assert "20260510" in output

    def test_format_shell_exports_renormalises_cyc(self) -> None:
        """``format_shell_exports`` must zero-pad even raw ``cyc`` values.

        The runtime env layer normalises ``cyc`` already, but if a
        caller bypasses ``get_runtime_from_env`` and stuffs an integer
        ``cyc`` into the export dict directly, the formatter must still
        emit ``cyc=00`` so operational filename templates don't break.
        """
        out = format_shell_exports({"cyc": 0})
        assert "export cyc=00" in out

        out = format_shell_exports({"cyc": "6"})
        assert "export cyc=06" in out

    def test_runtime_env_cyc_normalises(self) -> None:
        """``get_runtime_from_env`` normalises ``cyc`` in-place."""
        os.environ["cyc"] = "0"
        runtime = get_runtime_from_env()
        assert runtime["cyc"] == "00"


class TestErrorHandling:
    """Malformed YAML must produce a one-line stderr error and exit 1."""

    def test_cli_malformed_yaml(self, tmp_path: Path) -> None:
        """``python -m nos_workflow.utils.yaml_to_env`` on bad YAML.

        Expect:
            * exitcode != 0
            * stderr contains exactly one ``ERROR:`` line
            * stdout is empty
            * no traceback unless NOS_WORKFLOW_DEBUG=1 is set
        """
        bad = tmp_path / "bad.yaml"
        bad.write_text("system: { unbalanced: {\n")

        # Run the module entry point in a clean child so we test the
        # actual CLI error path, not just the in-process call.
        env = {k: v for k, v in os.environ.items() if k != "NOS_WORKFLOW_DEBUG"}
        result = subprocess.run(
            [sys.executable, "-m", "nos_workflow.utils.yaml_to_env", "--config", str(bad)],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(Path(__file__).parent.parent.parent),
        )

        assert result.returncode != 0, "CLI should exit non-zero on bad YAML"
        assert result.stdout == "", f"stdout should be empty on error, got: {result.stdout!r}"
        assert "ERROR: yaml_to_env:" in result.stderr
        # Exactly one ERROR line — not a Python traceback.
        error_lines = [
            ln for ln in result.stderr.splitlines() if ln.startswith("ERROR:")
        ]
        assert len(error_lines) == 1, f"expected one ERROR line, got: {result.stderr!r}"
        # No traceback noise.
        assert "Traceback" not in result.stderr
        # The error line should name the offending config path.
        assert str(bad) in result.stderr

    def test_cli_missing_config_file(self, tmp_path: Path) -> None:
        """A missing config path also yields a structured ERROR + rc=1."""
        missing = tmp_path / "does_not_exist.yaml"

        result = subprocess.run(
            [sys.executable, "-m", "nos_workflow.utils.yaml_to_env",
             "--config", str(missing)],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).parent.parent.parent),
        )

        assert result.returncode != 0
        assert "ERROR: yaml_to_env:" in result.stderr
        assert "config file not found" in result.stderr
        assert "Traceback" not in result.stderr


# ---------------------------------------------------------------------------
# Self-test entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
