"""
Unit tests for Orchestration Handlers.

Tests STOFSPrepHandler, COMFPrepHandler, STOFSModelRunHandler,
COMFModelRunHandler: subprocess calls, static file staging,
config loading, and environment capture.
"""

import os
import sys
import subprocess
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, call

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from nos_ofs.orchestration.handlers.base import (
    StepResult,
    BasePrepHandler,
    BaseModelRunHandler,
)
from nos_ofs.orchestration.handlers.stofs import (
    STOFSPrepHandler,
    STOFSModelRunHandler,
)
from nos_ofs.orchestration.handlers.comf import (
    COMFPrepHandler,
    COMFModelRunHandler,
)


# =========================================================================
# StepResult tests
# =========================================================================


class TestStepResult:
    """Tests for StepResult dataclass."""

    def test_success_result(self):
        """Test creating a successful StepResult."""
        result = StepResult(
            success=True,
            step_name="stage_static_files",
            message="Staged 15 files",
            duration_seconds=2.5,
        )

        assert result.success
        assert result.step_name == "stage_static_files"
        assert result.message == "Staged 15 files"
        assert result.duration_seconds == 2.5

    def test_failure_result(self):
        """Test creating a failed StepResult."""
        result = StepResult(
            success=False,
            step_name="execute_model",
            message="Segfault",
            returncode=139,
            errors=["Segmentation fault"],
        )

        assert not result.success
        assert result.returncode == 139
        assert len(result.errors) == 1

    def test_default_values(self):
        """Test StepResult default values."""
        result = StepResult(success=True, step_name="test")

        assert result.message == ""
        assert result.command == ""
        assert result.stdout == ""
        assert result.stderr == ""
        assert result.returncode == 0
        assert result.duration_seconds == 0.0
        assert result.output_files == []
        assert result.errors == []
        assert result.warnings == []
        assert result.metadata == {}

    def test_bool_context(self):
        """Test StepResult in boolean context."""
        assert bool(StepResult(success=True, step_name="t")) is True
        assert bool(StepResult(success=False, step_name="t")) is False

    def test_with_output_files(self):
        """Test StepResult with output files."""
        result = StepResult(
            success=True,
            step_name="stage",
            output_files=[Path("/tmp/a.nc"), Path("/tmp/b.nc")],
        )

        assert len(result.output_files) == 2

    def test_with_metadata(self):
        """Test StepResult with metadata."""
        result = StepResult(
            success=True,
            step_name="run",
            metadata={"nprocs": 120, "model": "schism"},
        )

        assert result.metadata["nprocs"] == 120
        assert result.metadata["model"] == "schism"


# =========================================================================
# BasePrepHandler._run_subprocess tests
# =========================================================================


class TestBasePrepHandlerRunSubprocess:
    """Tests for BasePrepHandler._run_subprocess method."""

    def _make_handler(self, config):
        """Create a concrete handler for testing base class methods."""
        # STOFSPrepHandler is a concrete implementation
        return STOFSPrepHandler(config)

    @patch("subprocess.run")
    def test_run_subprocess_success(self, mock_run, sample_stofs_config):
        """Test _run_subprocess returns success on zero return code."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout="output text",
            stderr="",
        )

        handler = self._make_handler(sample_stofs_config)
        result = handler._run_subprocess("echo hello", "test_step")

        assert result.success
        assert result.step_name == "test_step"
        assert result.returncode == 0
        assert result.stdout == "output text"

    @patch("subprocess.run")
    def test_run_subprocess_failure(self, mock_run, sample_stofs_config):
        """Test _run_subprocess returns failure on non-zero return code."""
        mock_run.return_value = Mock(
            returncode=1,
            stdout="",
            stderr="error message",
        )

        handler = self._make_handler(sample_stofs_config)
        result = handler._run_subprocess("false", "test_step")

        assert not result.success
        assert result.returncode == 1
        assert "error message" in result.errors[0]

    @patch("subprocess.run")
    def test_run_subprocess_timeout(self, mock_run, sample_stofs_config):
        """Test _run_subprocess handles timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired("cmd", 60)

        handler = self._make_handler(sample_stofs_config)
        result = handler._run_subprocess("sleep 100", "test_step", timeout=60)

        assert not result.success
        assert "timed out" in result.errors[0].lower()

    @patch("subprocess.run")
    def test_run_subprocess_exception(self, mock_run, sample_stofs_config):
        """Test _run_subprocess handles unexpected exception."""
        mock_run.side_effect = OSError("Permission denied")

        handler = self._make_handler(sample_stofs_config)
        result = handler._run_subprocess("restricted_cmd", "test_step")

        assert not result.success
        assert "Permission denied" in result.errors[0]

    @patch("subprocess.run")
    def test_run_subprocess_stores_command(self, mock_run, sample_stofs_config):
        """Test _run_subprocess stores the command in result."""
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

        handler = self._make_handler(sample_stofs_config)
        result = handler._run_subprocess("ls -la /tmp", "list_files")

        assert result.command == "ls -la /tmp"

    @patch("subprocess.run")
    def test_run_subprocess_uses_shell(self, mock_run, sample_stofs_config):
        """Test _run_subprocess runs with shell=True."""
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

        handler = self._make_handler(sample_stofs_config)
        handler._run_subprocess("echo test", "test_step")

        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs.get("shell") is True or call_kwargs[1].get("shell") is True

    @patch("subprocess.run")
    def test_run_subprocess_env_merging(self, mock_run, sample_stofs_config):
        """Test _run_subprocess merges custom env with os.environ."""
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

        handler = self._make_handler(sample_stofs_config)
        custom_env = {"MY_VAR": "test_value"}
        handler._run_subprocess("echo $MY_VAR", "test_step", env=custom_env)

        call_kwargs = mock_run.call_args
        passed_env = call_kwargs.kwargs.get("env") or call_kwargs[1].get("env")
        assert passed_env is not None
        assert passed_env["MY_VAR"] == "test_value"

    @patch("subprocess.run")
    def test_run_subprocess_measures_duration(self, mock_run, sample_stofs_config):
        """Test _run_subprocess measures execution duration."""
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

        handler = self._make_handler(sample_stofs_config)
        result = handler._run_subprocess("echo fast", "test_step")

        assert result.duration_seconds >= 0


# =========================================================================
# BasePrepHandler._source_and_capture_env tests
# =========================================================================


class TestBasePrepHandlerSourceAndCapture:
    """Tests for BasePrepHandler._source_and_capture_env method."""

    @patch("subprocess.run")
    def test_source_success_updates_env(self, mock_run, sample_stofs_config):
        """Test _source_and_capture_env updates os.environ on success."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout="NEW_VAR=hello_world\nPATH=/usr/bin\n",
            stderr="",
        )

        handler = STOFSPrepHandler(sample_stofs_config)
        result = handler._source_and_capture_env(
            "/tmp/test_script.sh",
            step_name="test_source",
        )

        assert result.success
        assert os.environ.get("NEW_VAR") == "hello_world"

        # Cleanup
        os.environ.pop("NEW_VAR", None)

    @patch("subprocess.run")
    def test_source_failure(self, mock_run, sample_stofs_config):
        """Test _source_and_capture_env returns failure on error."""
        mock_run.return_value = Mock(
            returncode=1,
            stdout="",
            stderr="script not found",
        )

        handler = STOFSPrepHandler(sample_stofs_config)
        result = handler._source_and_capture_env(
            "/tmp/nonexistent.sh",
            step_name="test_source",
        )

        assert not result.success

    @patch("subprocess.run")
    def test_source_timeout(self, mock_run, sample_stofs_config):
        """Test _source_and_capture_env handles timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired(["bash"], 60)

        handler = STOFSPrepHandler(sample_stofs_config)
        result = handler._source_and_capture_env(
            "/tmp/slow_script.sh",
            step_name="test_source",
            timeout=60,
        )

        assert not result.success
        assert "timed out" in result.errors[0].lower()

    @patch("subprocess.run")
    def test_source_exception(self, mock_run, sample_stofs_config):
        """Test _source_and_capture_env handles exception."""
        mock_run.side_effect = FileNotFoundError("bash not found")

        handler = STOFSPrepHandler(sample_stofs_config)
        result = handler._source_and_capture_env(
            "/tmp/script.sh",
            step_name="test_source",
        )

        assert not result.success
        assert "bash not found" in result.errors[0]

    @patch("subprocess.run")
    def test_source_uses_bash_command(self, mock_run, sample_stofs_config):
        """Test _source_and_capture_env uses bash -c with source."""
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

        handler = STOFSPrepHandler(sample_stofs_config)
        handler._source_and_capture_env(
            "/tmp/script.sh",
            args="arg1 arg2",
            step_name="test_source",
        )

        call_args = mock_run.call_args
        command = call_args.kwargs.get("args") or call_args[0][0]
        # Should use bash -c ["bash", "-c", "source ..."]
        assert command[0] == "bash"
        assert command[1] == "-c"
        assert "source" in command[2]
        assert "/tmp/script.sh" in command[2]
        assert "arg1 arg2" in command[2]


# =========================================================================
# STOFSPrepHandler tests
# =========================================================================


class TestSTOFSPrepHandlerInit:
    """Tests for STOFSPrepHandler initialization."""

    def test_init_stores_config(self, sample_stofs_config):
        """Test STOFSPrepHandler stores config reference."""
        handler = STOFSPrepHandler(sample_stofs_config)

        assert handler.config is sample_stofs_config

    def test_init_resolves_directories(self, sample_stofs_config):
        """Test STOFSPrepHandler resolves USH, FIX, DATA directories."""
        handler = STOFSPrepHandler(sample_stofs_config)

        assert isinstance(handler.ush_dir, Path)
        assert isinstance(handler.fix_dir, Path)
        assert isinstance(handler.data_dir, Path)


class TestSTOFSPrepHandlerStageStaticFiles:
    """Tests for STOFSPrepHandler.stage_static_files method."""

    def test_stage_static_files_success(self, sample_stofs_config, tmp_path):
        """Test staging static files when fix directory has files."""
        # Setup directories
        fix_dir = tmp_path / "fix"
        fix_dir.mkdir()
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        run = "stofs_3d_atl"

        # Create some fix files
        for suffix in ["hgrid.gr3", "vgrid.in", "drag.gr3", "station.in"]:
            (fix_dir / f"{run}_{suffix}").write_text("test")

        handler = STOFSPrepHandler(sample_stofs_config)
        handler.fix_dir = fix_dir
        handler.data_dir = data_dir

        result = handler.stage_static_files()

        assert result.success
        assert len(result.output_files) == 4

    def test_stage_static_files_missing_files_warns(self, sample_stofs_config, tmp_path):
        """Test staging reports warnings for missing files."""
        fix_dir = tmp_path / "fix"
        fix_dir.mkdir()
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        # Create only one fix file
        (fix_dir / "stofs_3d_atl_hgrid.gr3").write_text("test")

        handler = STOFSPrepHandler(sample_stofs_config)
        handler.fix_dir = fix_dir
        handler.data_dir = data_dir

        result = handler.stage_static_files()

        assert result.success  # Still succeeds with warnings
        assert len(result.warnings) > 0

    def test_stage_static_files_creates_symlinks(self, sample_stofs_config, tmp_path):
        """Test staging creates symlinks in data directory."""
        fix_dir = tmp_path / "fix"
        fix_dir.mkdir()
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        (fix_dir / "stofs_3d_atl_hgrid.gr3").write_text("grid data")

        handler = STOFSPrepHandler(sample_stofs_config)
        handler.fix_dir = fix_dir
        handler.data_dir = data_dir

        handler.stage_static_files()

        symlink = data_dir / "hgrid.gr3"
        assert symlink.is_symlink()
        assert symlink.read_text() == "grid data"


class TestSTOFSPrepHandlerStaticFileList:
    """Tests for STOFS static file mappings."""

    def test_static_file_mapping_count(self, sample_stofs_config, tmp_path):
        """Test STOFS defines the expected number of static files."""
        fix_dir = tmp_path / "fix"
        fix_dir.mkdir()
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        run = "stofs_3d_atl"

        # Create all expected static files
        expected_names = [
            "windrot_geo2proj.gr3", "watertype.gr3", "vgrid.in",
            "tvd.prop", "tem_nudge.gr3", "station.in",
            "river_source_sink.in", "shapiro.gr3", "sal_nudge.gr3",
            "param.nml_6globaloutput", "river_msource.th", "hgrid.ll",
            "hgrid.gr3", "estuary.gr3", "drag.gr3", "diffmin.gr3",
            "diffmax.gr3", "bctides.in_template", "albedo.gr3",
            "partition.prop",
        ]

        for name in expected_names:
            (fix_dir / f"{run}_{name}").write_text("test")

        handler = STOFSPrepHandler(sample_stofs_config)
        handler.fix_dir = fix_dir
        handler.data_dir = data_dir

        result = handler.stage_static_files()

        assert result.success
        assert len(result.output_files) == 20  # All 20 files


class TestSTOFSPrepHandlerCreateModelConfig:
    """Tests for STOFSPrepHandler.create_model_config method."""

    @patch.object(STOFSPrepHandler, "_run_subprocess")
    def test_create_model_config_calls_param_nml(self, mock_run, sample_stofs_config):
        """Test create_model_config calls param.nml scripts."""
        mock_run.return_value = StepResult(
            success=True, step_name="create_param_nml_nowcast"
        )

        handler = STOFSPrepHandler(sample_stofs_config)
        result = handler.create_model_config()

        # Should call param.nml for nowcast, forecast, and bctides
        assert mock_run.call_count == 3

    @patch.object(STOFSPrepHandler, "_run_subprocess")
    def test_create_model_config_stops_on_failure(self, mock_run, sample_stofs_config):
        """Test create_model_config stops if param.nml nowcast fails."""
        mock_run.return_value = StepResult(
            success=False, step_name="create_param_nml_nowcast", message="Failed"
        )

        handler = STOFSPrepHandler(sample_stofs_config)
        result = handler.create_model_config()

        assert not result.success
        # Should stop after first failure
        assert mock_run.call_count == 1


class TestSTOFSPrepHandlerCreateForcing:
    """Tests for STOFS forcing creation methods."""

    @patch.object(STOFSPrepHandler, "_run_subprocess")
    def test_create_forcing_atmospheric(self, mock_run, sample_stofs_config):
        """Test atmospheric forcing calls GFS and HRRR scripts."""
        mock_run.return_value = StepResult(success=True, step_name="test")

        handler = STOFSPrepHandler(sample_stofs_config)
        result = handler.create_forcing_atmospheric()

        assert result.success
        assert mock_run.call_count == 2  # GFS + HRRR

    @patch.object(STOFSPrepHandler, "_run_subprocess")
    def test_create_forcing_river(self, mock_run, sample_stofs_config):
        """Test river forcing calls NWM and St. Lawrence scripts."""
        mock_run.return_value = StepResult(success=True, step_name="test")

        handler = STOFSPrepHandler(sample_stofs_config)
        result = handler.create_forcing_river()

        assert result.success
        assert mock_run.call_count == 2  # NWM + St. Lawrence

    @patch.object(STOFSPrepHandler, "_run_subprocess")
    def test_create_forcing_obc(self, mock_run, sample_stofs_config):
        """Test OBC forcing calls 3D-th script."""
        mock_run.return_value = StepResult(success=True, step_name="test")

        handler = STOFSPrepHandler(sample_stofs_config)
        result = handler.create_forcing_obc()

        assert result.success
        mock_run.assert_called_once()

    @patch.object(STOFSPrepHandler, "_run_subprocess")
    def test_create_forcing_nudging(self, mock_run, sample_stofs_config):
        """Test nudging forcing calls nudge script."""
        mock_run.return_value = StepResult(success=True, step_name="test")

        handler = STOFSPrepHandler(sample_stofs_config)
        result = handler.create_forcing_nudging()

        assert result.success
        mock_run.assert_called_once()


# =========================================================================
# COMFPrepHandler tests
# =========================================================================


class TestCOMFPrepHandlerInit:
    """Tests for COMFPrepHandler initialization."""

    def test_init_stores_config(self, sample_comf_config):
        """Test COMFPrepHandler stores config reference."""
        handler = COMFPrepHandler(sample_comf_config)

        assert handler.config is sample_comf_config

    def test_init_resolves_directories(self, sample_comf_config):
        """Test COMFPrepHandler resolves USH, FIX, EXEC, DATA directories."""
        handler = COMFPrepHandler(sample_comf_config)

        assert isinstance(handler.ush_dir, Path)
        assert isinstance(handler.fix_dir, Path)
        assert isinstance(handler.exec_dir, Path)
        assert isinstance(handler.data_dir, Path)

    def test_init_reads_ocean_model(self, sample_comf_config):
        """Test COMFPrepHandler reads ocean model from environment."""
        handler = COMFPrepHandler(sample_comf_config)

        assert handler.ocean_model is not None


class TestCOMFPrepHandlerConfigLoading:
    """Tests for COMFPrepHandler 3-tier config loading."""

    @patch.object(COMFPrepHandler, "_source_and_capture_env")
    def test_stage_static_files_yaml_config(self, mock_source, sample_comf_config, tmp_path):
        """Test stage_static_files loads YAML config when OFS_CONFIG is set."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        fix_dir = tmp_path / "fix"
        fix_dir.mkdir()

        # Create config file
        yaml_path = tmp_path / "test_config.yaml"
        yaml_path.write_text("system:\n  name: cbofs\n")

        os.environ["OFS_CONFIG"] = str(yaml_path)
        os.environ["OFS_CONFIG_LOADED"] = "1"

        mock_source.return_value = StepResult(success=True, step_name="test")

        handler = COMFPrepHandler(sample_comf_config)
        handler.data_dir = data_dir
        handler.fix_dir = fix_dir
        handler.ush_dir = tmp_path

        result = handler.stage_static_files()

        # Should have called _source_and_capture_env
        assert mock_source.called

        # Cleanup
        os.environ.pop("OFS_CONFIG", None)
        os.environ.pop("OFS_CONFIG_LOADED", None)

    @patch.object(COMFPrepHandler, "_source_and_capture_env")
    def test_stage_static_files_ctl_fallback(self, mock_source, sample_comf_config, tmp_path):
        """Test stage_static_files falls back to .ctl when no YAML."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        fix_dir = tmp_path / "fix"
        fix_dir.mkdir()

        # Create .ctl file (no YAML)
        (fix_dir / "cbofs.ctl").write_text("OCEAN_MODEL=ROMS\n")

        # Remove OFS_CONFIG so it goes through fallback
        os.environ.pop("OFS_CONFIG", None)
        os.environ.pop("OFS_CONFIG_LOADED", None)

        mock_source.return_value = StepResult(success=True, step_name="test")

        handler = COMFPrepHandler(sample_comf_config)
        handler.data_dir = data_dir
        handler.fix_dir = fix_dir
        handler.ush_dir = tmp_path

        result = handler.stage_static_files()

        assert mock_source.called

    @patch.object(COMFPrepHandler, "_source_and_capture_env")
    def test_stage_static_files_no_config_fails(self, mock_source, sample_comf_config, tmp_path):
        """Test stage_static_files fails when no config files exist."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        fix_dir = tmp_path / "fix"
        fix_dir.mkdir()

        # No config files at all
        os.environ.pop("OFS_CONFIG", None)
        os.environ.pop("OFS_CONFIG_LOADED", None)

        handler = COMFPrepHandler(sample_comf_config)
        handler.data_dir = data_dir
        handler.fix_dir = fix_dir
        handler.ush_dir = tmp_path

        result = handler.stage_static_files()

        assert not result.success
        assert "not found" in result.errors[0].lower() or "Control file" in result.errors[0]


class TestCOMFPrepHandlerCreateModelConfig:
    """Tests for COMFPrepHandler.create_model_config method."""

    @patch.object(COMFPrepHandler, "_run_subprocess")
    def test_create_roms_config(self, mock_run, sample_comf_config):
        """Test creating ROMS model config."""
        mock_run.return_value = StepResult(success=True, step_name="test")

        handler = COMFPrepHandler(sample_comf_config)
        handler.ocean_model = "ROMS"

        result = handler.create_model_config()

        assert result.success

    @patch.object(COMFPrepHandler, "_run_subprocess")
    def test_create_fvcom_config(self, mock_run, sample_comf_config):
        """Test creating FVCOM model config."""
        mock_run.return_value = StepResult(success=True, step_name="test")

        handler = COMFPrepHandler(sample_comf_config)
        handler.ocean_model = "FVCOM"

        result = handler.create_model_config()

        assert result.success

    @patch.object(COMFPrepHandler, "_run_subprocess")
    def test_create_schism_config(self, mock_run, sample_comf_config):
        """Test creating SCHISM model config."""
        mock_run.return_value = StepResult(success=True, step_name="test")

        handler = COMFPrepHandler(sample_comf_config)
        handler.ocean_model = "SCHISM"

        result = handler.create_model_config()

        assert result.success

    def test_unknown_model_type_fails(self, sample_comf_config):
        """Test unknown ocean model type fails."""
        handler = COMFPrepHandler(sample_comf_config)
        handler.ocean_model = "UNKNOWN_MODEL"

        result = handler.create_model_config()

        assert not result.success
        assert "Unknown" in result.message or "Unsupported" in result.errors[0]


class TestCOMFPrepHandlerOBCSkipping:
    """Tests for COMFPrepHandler OBC skipping."""

    @patch.object(COMFPrepHandler, "_run_subprocess")
    def test_obc_skipped_for_lsofs(self, mock_run, sample_comf_config):
        """Test OBC is skipped for lsofs."""
        handler = COMFPrepHandler(sample_comf_config)
        handler.ofs = "lsofs"

        result = handler.create_forcing_obc()

        assert result.success
        assert "not required" in result.message
        mock_run.assert_not_called()

    @patch.object(COMFPrepHandler, "_run_subprocess")
    def test_obc_skipped_for_loofs(self, mock_run, sample_comf_config):
        """Test OBC is skipped for loofs."""
        handler = COMFPrepHandler(sample_comf_config)
        handler.ofs = "loofs"

        result = handler.create_forcing_obc()

        assert result.success
        mock_run.assert_not_called()

    @patch.object(COMFPrepHandler, "_run_subprocess")
    def test_obc_runs_for_cbofs(self, mock_run, sample_comf_config):
        """Test OBC runs for cbofs."""
        mock_run.return_value = StepResult(success=True, step_name="test")

        handler = COMFPrepHandler(sample_comf_config)
        handler.ofs = "cbofs"

        result = handler.create_forcing_obc()

        assert result.success
        mock_run.assert_called_once()


class TestCOMFPrepHandlerNudging:
    """Tests for COMFPrepHandler nudging handling."""

    @patch.object(COMFPrepHandler, "_run_subprocess")
    def test_nudging_skipped_when_disabled(self, mock_run, sample_comf_config):
        """Test nudging is skipped when TS_NUDGING=0."""
        os.environ["TS_NUDGING"] = "0"

        handler = COMFPrepHandler(sample_comf_config)
        result = handler.create_forcing_nudging()

        assert result.success
        assert "not enabled" in result.message
        mock_run.assert_not_called()

        os.environ.pop("TS_NUDGING", None)

    @patch.object(COMFPrepHandler, "_run_subprocess")
    def test_nudging_runs_when_enabled(self, mock_run, sample_comf_config):
        """Test nudging runs when TS_NUDGING=1."""
        os.environ["TS_NUDGING"] = "1"
        mock_run.return_value = StepResult(success=True, step_name="test")

        handler = COMFPrepHandler(sample_comf_config)
        result = handler.create_forcing_nudging()

        assert result.success
        mock_run.assert_called_once()

        os.environ.pop("TS_NUDGING", None)


class TestCOMFPrepHandlerInitialCondition:
    """Tests for COMFPrepHandler.prepare_initial_condition."""

    def test_initial_condition_handled_by_launch(self, sample_comf_config):
        """Test COMF initial condition is handled by nos_ofs_launch.sh."""
        handler = COMFPrepHandler(sample_comf_config)
        result = handler.prepare_initial_condition()

        assert result.success
        assert "nos_ofs_launch" in result.message


# =========================================================================
# STOFSModelRunHandler tests
# =========================================================================


class TestSTOFSModelRunHandler:
    """Tests for STOFSModelRunHandler."""

    def test_init(self, sample_stofs_config):
        """Test STOFSModelRunHandler initialization."""
        handler = STOFSModelRunHandler(sample_stofs_config)

        assert handler.config is sample_stofs_config
        assert isinstance(handler.ush_dir, Path)
        assert isinstance(handler.data_dir, Path)
        assert isinstance(handler.comout, Path)

    @patch.object(STOFSModelRunHandler, "_run_subprocess")
    def test_stage_model_files(self, mock_run, sample_stofs_config):
        """Test stage_model_files calls shell script."""
        mock_run.return_value = StepResult(success=True, step_name="test")

        handler = STOFSModelRunHandler(sample_stofs_config)
        result = handler.stage_model_files("nowcast")

        assert result.success
        mock_run.assert_called_once()

    @patch.object(STOFSModelRunHandler, "_run_subprocess")
    def test_prepare_restart(self, mock_run, sample_stofs_config):
        """Test prepare_restart calls shell script."""
        mock_run.return_value = StepResult(success=True, step_name="test")

        handler = STOFSModelRunHandler(sample_stofs_config)
        result = handler.prepare_restart("forecast")

        assert result.success
        mock_run.assert_called_once()

    @patch.object(STOFSModelRunHandler, "_run_subprocess")
    def test_execute_model(self, mock_run, sample_stofs_config):
        """Test execute_model calls shell script with 8hr timeout."""
        mock_run.return_value = StepResult(success=True, step_name="test")

        handler = STOFSModelRunHandler(sample_stofs_config)
        result = handler.execute_model("nowcast")

        assert result.success
        # Verify timeout is set to 8 hours (28800)
        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs.get("timeout") == 28800

    @patch.object(STOFSModelRunHandler, "_run_subprocess")
    def test_archive_outputs(self, mock_run, sample_stofs_config):
        """Test archive_outputs calls shell script."""
        mock_run.return_value = StepResult(success=True, step_name="test")

        handler = STOFSModelRunHandler(sample_stofs_config)
        result = handler.archive_outputs("forecast")

        assert result.success
        mock_run.assert_called_once()


# =========================================================================
# COMFModelRunHandler tests
# =========================================================================


class TestCOMFModelRunHandler:
    """Tests for COMFModelRunHandler."""

    def test_init(self, sample_comf_config):
        """Test COMFModelRunHandler initialization."""
        handler = COMFModelRunHandler(sample_comf_config)

        assert handler.config is sample_comf_config
        assert isinstance(handler.ush_dir, Path)
        assert isinstance(handler.data_dir, Path)

    @patch.object(COMFModelRunHandler, "_run_subprocess")
    def test_stage_model_files(self, mock_run, sample_comf_config):
        """Test stage_model_files calls nos_ofs_launch.sh."""
        mock_run.return_value = StepResult(success=True, step_name="test")

        handler = COMFModelRunHandler(sample_comf_config)
        result = handler.stage_model_files("nowcast")

        assert result.success

    def test_prepare_restart_handled_by_launch(self, sample_comf_config):
        """Test prepare_restart is handled by nos_ofs_launch.sh."""
        handler = COMFModelRunHandler(sample_comf_config)
        result = handler.prepare_restart("nowcast")

        assert result.success
        assert "nos_ofs_launch" in result.message

    @patch.object(COMFModelRunHandler, "_run_subprocess")
    def test_execute_model(self, mock_run, sample_comf_config):
        """Test execute_model calls nos_ofs_nowcast_forecast.sh."""
        mock_run.return_value = StepResult(success=True, step_name="test")

        handler = COMFModelRunHandler(sample_comf_config)
        result = handler.execute_model("nowcast")

        assert result.success
        # Verify the script name is in the command
        call_args = mock_run.call_args
        command = call_args[0][0] if call_args[0] else call_args.kwargs.get("command", "")
        assert "nos_ofs_nowcast_forecast" in command

    @patch.object(COMFModelRunHandler, "_run_subprocess")
    def test_execute_model_forecast(self, mock_run, sample_comf_config):
        """Test execute_model passes forecast phase."""
        mock_run.return_value = StepResult(success=True, step_name="test")

        handler = COMFModelRunHandler(sample_comf_config)
        handler.execute_model("forecast")

        call_args = mock_run.call_args
        command = call_args[0][0] if call_args[0] else call_args.kwargs.get("command", "")
        assert "forecast" in command

    @patch.object(COMFModelRunHandler, "_run_subprocess")
    def test_archive_outputs(self, mock_run, sample_comf_config):
        """Test archive_outputs calls nos_ofs_archive.sh."""
        mock_run.return_value = StepResult(success=True, step_name="test")

        handler = COMFModelRunHandler(sample_comf_config)
        result = handler.archive_outputs("nowcast")

        assert result.success
        call_args = mock_run.call_args
        command = call_args[0][0] if call_args[0] else call_args.kwargs.get("command", "")
        assert "nos_ofs_archive" in command

    @patch.object(COMFModelRunHandler, "_run_subprocess")
    def test_execute_model_8hr_timeout(self, mock_run, sample_comf_config):
        """Test execute_model uses 8hr timeout."""
        mock_run.return_value = StepResult(success=True, step_name="test")

        handler = COMFModelRunHandler(sample_comf_config)
        handler.execute_model("nowcast")

        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs.get("timeout") == 28800


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
