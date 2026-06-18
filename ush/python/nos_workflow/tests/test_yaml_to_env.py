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

    def test_system_inherits_another_system(self, base_dir: Path) -> None:
        """A ``systems/`` yaml may ``_base`` another ``systems/`` yaml.

        Reproduces the standalone-variant bug: stofs_3d_atl_ufs_standalone
        (systems/) inherits stofs_3d_atl_ufs (systems/), which itself
        inherits schism (base/) -- a two-level chain. The loader used to
        search only ``base/`` and ``parm/``, so the middle ``systems/``
        yaml was never found and the child inherited nothing.
        """
        (base_dir / "base" / "grandbase.yaml").write_text(
            "model:\n"
            "  type: schism\n"
            "  run:\n"
            "    hindcast_days: 1.0\n"
            "    forecast_days: 4.5\n"
        )
        (base_dir / "systems" / "middle.yaml").write_text(
            "_base: grandbase\n"
            "system:\n"
            "  name: middle_ofs\n"
            "grid:\n"
            "  n_levels: 51\n"
        )
        leaf_path = base_dir / "systems" / "leaf.yaml"
        leaf_path.write_text(
            "_base: middle\n"
            "execution:\n"
            "  mode: standalone\n"
        )

        merged = load_yaml_with_inheritance(leaf_path, base_dir=base_dir)

        # from the middle systems/ yaml
        assert merged["grid"]["n_levels"] == 51
        assert merged["system"]["name"] == "middle_ofs"
        # from the grandparent abstract base (two levels up)
        assert merged["model"]["run"]["hindcast_days"] == 1.0
        assert merged["model"]["run"]["forecast_days"] == 4.5
        assert merged["model"]["type"] == "schism"
        # the leaf's own value survives the merge
        assert merged["execution"]["mode"] == "standalone"

    def test_system_to_system_export_durations(self, base_dir: Path) -> None:
        """Durations inherited through a systems->systems chain reach export.

        The exact failure mode the standalone nowcast hit: without the
        ``systems/`` lookup, ``model.run`` never merged in and LEN_NOWCAST
        fell back to the 6h default (hindcast_days=0.25), running a 6h
        nowcast that never reached the step-576 hotstart write.
        """
        (base_dir / "base" / "grandbase.yaml").write_text(
            "model:\n"
            "  run:\n"
            "    hindcast_days: 1.0\n"
            "    forecast_days: 4.5\n"
        )
        (base_dir / "systems" / "middle.yaml").write_text(
            "_base: grandbase\n"
            "system:\n"
            "  name: middle_ofs\n"
            "  framework: stofs\n"
            "grid:\n"
            "  domain:\n"
            "    lon_min: -98.0\n"
            "    lon_max: -52.0\n"
            "    lat_min: 7.0\n"
            "    lat_max: 52.0\n"
        )
        leaf_path = base_dir / "systems" / "leaf.yaml"
        leaf_path.write_text("_base: middle\n")

        output = export_for_shell(leaf_path, framework="stofs")

        assert "export LEN_NOWCAST=24" in output     # 1.0*24, not the 6h default
        assert "export LEN_FORECAST=108" in output   # 4.5*24, not the 120h default

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


class TestPpnFromResourcesSelect:
    """``PPN`` (mpiexec -ppn) is parsed from ``resources.select`` mpiprocs=.

    Regression for the STOFS-3D-ATL-UFS nowcast MPI-launch failure: the
    shell ``_schism_run_mpi`` defaulted ``${PPN:-120}`` (a SECOFS-tuned
    constant); with the STOFS PBS sized for ``mpiprocs=128`` that under-
    packed nodes ("Cannot place all ranks", rc=127). PPN must instead
    track the YAML ``resources.select`` so it can never drift from the
    PBS allocation, while staying byte-silent for SECOFS (whose YAML has
    no ``resources.select`` -> the shell 120 default is preserved).
    """

    def _export(self, yaml_content: str) -> str:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            temp_path = f.name
        try:
            return export_for_shell(temp_path, framework="comf")
        finally:
            os.unlink(temp_path)

    def test_ppn_derived_from_stofs_select(self) -> None:
        """STOFS-style select=...:mpiprocs=128 -> export PPN=128."""
        output = self._export(
            """
system:
  name: stofs_3d_atl_ufs
  framework: comf
resources:
  nprocs: 4436
  select: "select=35:ncpus=128:mpiprocs=128"
"""
        )
        assert "export PPN=128" in output

    def test_ppn_absent_without_resources_select(self) -> None:
        """SECOFS-style resources (no select) -> PPN unset (shell keeps 120)."""
        output = self._export(
            """
system:
  name: secofs_ufs
  framework: comf
resources:
  nprocs: 2914
  nscribes: 0
"""
        )
        assert "export PPN=" not in output

    def test_ppn_is_parsed_not_hardcoded(self) -> None:
        """Arbitrary mpiprocs= flows through verbatim (parsed, not fixed)."""
        output = self._export(
            """
system:
  name: demo_ufs
  framework: comf
resources:
  nprocs: 600
  select: "select=5:ncpus=128:mpiprocs=120"
"""
        )
        assert "export PPN=120" in output


class TestExecutionMode:
    """``execution.mode`` drives UFS (default) vs standalone SCHISM.

    Phase 1 is config-resolution plumbing only. The whole point is parity:
    the production-validated UFS path MUST stay byte-identical when
    ``execution.mode`` is ``ufs`` or absent. ``standalone`` flips a small,
    enumerated set of resource/coupling exports from the yaml's
    ``standalone:`` overlay and nothing else.
    """

    _STOFS_UFS_YAML = (
        Path(__file__).parent.parent.parent.parent.parent
        / "parm" / "systems" / "stofs_3d_atl_ufs.yaml"
    )

    def _export(self, yaml_text: str) -> str:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_text)
            temp_path = f.name
        try:
            return export_for_shell(temp_path, framework="stofs")
        finally:
            os.unlink(temp_path)

    def _strip_execmode_blocks(self, text: str) -> str:
        """Drop the ``execution:`` and ``standalone:`` top-level blocks.

        Both are written as a top-level key followed by indented lines and
        a trailing blank line in stofs_3d_atl_ufs.yaml, so a small state
        machine that skips from the key until the next non-indented,
        non-blank line removes exactly those blocks and nothing else.
        """
        out, skipping = [], False
        for line in text.splitlines(keepends=True):
            stripped = line.rstrip("\n")
            if not skipping and stripped in ("execution:", "standalone:"):
                skipping = True
                continue
            if skipping:
                if stripped == "" or line[:1] in (" ", "\t"):
                    continue
                skipping = False
            out.append(line)
        return "".join(out)

    def test_ufs_path_is_byte_identical_to_stripped_config(self) -> None:
        """absent/``ufs`` execution.mode == config with the blocks removed.

        This is the parity gate: adding the ``execution:``/``standalone:``
        blocks (mode=ufs) must not perturb a single exported value vs the
        same yaml with those blocks physically deleted.
        """
        full_text = self._STOFS_UFS_YAML.read_text()
        full_lines = full_text.splitlines()
        assert "execution:" in full_lines and "standalone:" in full_lines

        stripped_text = self._strip_execmode_blocks(full_text)
        stripped_lines = stripped_text.splitlines()
        assert "execution:" not in stripped_lines
        assert "standalone:" not in stripped_lines

        with_blocks = self._export(full_text)            # mode: ufs
        without_blocks = self._export(stripped_text)     # blocks absent

        assert with_blocks == without_blocks

    def test_ufs_mode_never_reads_standalone_overlay(self) -> None:
        """With ``mode: ufs``, deleting ``standalone:`` changes nothing.

        Proves the resolver is keyed purely on the mode and never touches
        the overlay on the UFS path (the file ships ``mode: ufs``).
        """
        full_text = self._STOFS_UFS_YAML.read_text()
        no_overlay = self._strip_execmode_blocks(full_text)
        # Re-add only the execution block (mode: ufs), keeping standalone gone.
        with_exec_only = (
            "execution:\n  mode: ufs\n\n" + no_overlay
        )
        assert self._export(with_exec_only) == self._export(no_overlay)

    def test_standalone_overrides_resource_and_coupling_exports(self) -> None:
        """``mode: standalone`` flips exactly the overlay-backed exports."""
        full_text = self._STOFS_UFS_YAML.read_text()
        standalone_text = full_text.replace(
            "  mode: ufs ", "  mode: standalone "
        )
        assert "  mode: standalone " in standalone_text

        out = self._export(standalone_text)
        lines = set(out.splitlines())

        assert "export USE_DATM=false" in lines
        assert "export NWS_VALUE=2" in lines
        assert "export TOTAL_TASKS=4320" in lines
        assert "export NPROCS=4320" in lines
        assert "export NSCRIBES=6" in lines
        assert "export UFS_EXEC_NAME=pschism_WCOSS2" in lines
        # PPN parsed from the standalone select (mpiprocs=120), not the
        # UFS one (also 120 here, but it must come from the overlay).
        assert "export PPN=120" in lines

    def test_standalone_does_not_touch_shared_grid_exports(self) -> None:
        """Standalone overlay is resources/coupling only; grid is shared."""
        full_text = self._STOFS_UFS_YAML.read_text()
        ufs_out = self._export(full_text)
        standalone_out = self._export(
            full_text.replace("  mode: ufs ", "  mode: standalone ")
        )

        def _val(text: str, key: str) -> str:
            for ln in text.splitlines():
                if ln.startswith(f"export {key}="):
                    return ln
            return ""

        for shared in ("np_global", "ne_global", "ns_global", "nvrt",
                       "LONMIN", "LONMAX", "LATMIN", "LATMAX",
                       "GRIDFILE", "DELT_MODEL"):
            assert _val(ufs_out, shared) == _val(standalone_out, shared), shared


# ---------------------------------------------------------------------------
# Self-test entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
