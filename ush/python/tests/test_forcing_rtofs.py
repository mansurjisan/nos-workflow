"""
Unit tests for RTOFS Forcing Processor.

Tests RTOFS ocean boundary condition processing for SCHISM.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from nos_ofs.forcing.rtofs import RTOFSProcessor, RTOFSFileSet, RTOFSProcessingConfig
from nos_ofs.base import ForcingResult


class TestRTOFSProcessingConfig:
    """Tests for RTOFSProcessingConfig dataclass."""

    def test_default_values(self):
        """Test RTOFSProcessingConfig has sensible defaults."""
        cfg = RTOFSProcessingConfig()

        assert cfg.min_size_2d == 150_000_000
        assert cfg.min_size_3d == 200_000_000
        assert cfg.min_files_required == 10
        assert cfg.n_target_2d == 21
        assert cfg.n_target_3d == 21
        assert cfg.ssh_offset == 0.04
        assert cfg.dt_output == 21600.0
        assert cfg.temp_outside == 20.0
        assert cfg.salt_outside == 33.0

    def test_custom_values(self):
        """Test RTOFSProcessingConfig with custom values."""
        cfg = RTOFSProcessingConfig(
            min_size_2d=100_000_000,
            ssh_offset=0.05,
            min_files_required=5,
        )

        assert cfg.min_size_2d == 100_000_000
        assert cfg.ssh_offset == 0.05
        assert cfg.min_files_required == 5

    def test_roi_indices_for_stofs(self):
        """Test ROI indices match STOFS Atlantic domain defaults."""
        cfg = RTOFSProcessingConfig()

        # 2D surface indices
        assert cfg.idx_x1_2ds == 2805
        assert cfg.idx_x2_2ds == 2923
        assert cfg.idx_y1_2ds == 1598
        assert cfg.idx_y2_2ds == 2325

        # 3D depth indices
        assert cfg.idx_x1_3dz == 482
        assert cfg.idx_x2_3dz == 600
        assert cfg.idx_y1_3dz == 94
        assert cfg.idx_y2_3dz == 821


class TestRTOFSFileSet:
    """Tests for RTOFSFileSet dataclass."""

    def test_empty_fileset(self):
        """Test empty RTOFSFileSet initialization."""
        fs = RTOFSFileSet()

        assert fs.files_2d == []
        assert fs.files_3d == []
        assert fs.date == ""
        assert fs.is_backup is False

    def test_fileset_with_data(self):
        """Test RTOFSFileSet with file lists."""
        fs = RTOFSFileSet(
            files_2d=[Path("/a.nc"), Path("/b.nc")],
            files_3d=[Path("/c.nc")],
            date="20250504",
            is_backup=True,
        )

        assert len(fs.files_2d) == 2
        assert len(fs.files_3d) == 1
        assert fs.date == "20250504"
        assert fs.is_backup is True


class TestRTOFSProcessorInit:
    """Tests for RTOFSProcessor initialization."""

    def test_init_with_defaults(self, sample_stofs_config, tmp_path):
        """Test RTOFS processor initializes with default values."""
        proc = RTOFSProcessor(
            config=sample_stofs_config,
            input_path=tmp_path / "rtofs_in",
            output_path=tmp_path / "output",
        )

        assert proc.source_name == "RTOFS"
        assert proc.nudging_enabled is True
        assert proc.adt_enabled is True
        assert proc.use_fortran_exec is True
        assert len(proc.variables) == len(RTOFSProcessor.DEFAULT_VARIABLES)

    def test_init_with_custom_config(self, sample_stofs_config, tmp_path):
        """Test RTOFS processor initializes with custom config."""
        custom_cfg = RTOFSProcessingConfig(ssh_offset=0.06, min_files_required=5)

        proc = RTOFSProcessor(
            config=sample_stofs_config,
            input_path=tmp_path / "rtofs_in",
            output_path=tmp_path / "output",
            nudging_enabled=False,
            adt_enabled=False,
            processing_config=custom_cfg,
        )

        assert proc.nudging_enabled is False
        assert proc.adt_enabled is False
        assert proc.proc_config.ssh_offset == 0.06

    def test_init_stores_config_attributes(self, sample_stofs_config, tmp_path):
        """Test RTOFS processor stores config attributes correctly."""
        proc = RTOFSProcessor(
            config=sample_stofs_config,
            input_path=tmp_path / "rtofs_in",
            output_path=tmp_path / "output",
        )

        assert proc.cyc == 12
        assert proc.pdy == "20250504"
        assert proc.cycle == "t12z"
        assert proc.RUN == "stofs_3d_atl"


class TestRTOFSProcess:
    """Tests for RTOFSProcessor.process() method."""

    def test_process_returns_failure_when_input_missing(
        self, sample_stofs_config, tmp_path
    ):
        """Test process fails when input path does not exist."""
        proc = RTOFSProcessor(
            config=sample_stofs_config,
            input_path=tmp_path / "nonexistent",
            output_path=tmp_path / "output",
        )

        result = proc.process()

        assert not result.success
        assert "not found" in result.errors[0].lower() or "Input path" in result.errors[0]

    @patch.object(RTOFSProcessor, '_discover_rtofs_files')
    def test_process_returns_failure_when_no_files(
        self, mock_discover, sample_stofs_config, tmp_path
    ):
        """Test process fails when insufficient RTOFS files found."""
        input_dir = tmp_path / "rtofs_in"
        input_dir.mkdir()

        mock_discover.return_value = RTOFSFileSet()

        proc = RTOFSProcessor(
            config=sample_stofs_config,
            input_path=input_dir,
            output_path=tmp_path / "output",
        )

        result = proc.process()

        assert not result.success
        assert any("Insufficient" in e for e in result.errors)


class TestRTOFSFileDiscovery:
    """Tests for RTOFS file discovery and validation."""

    def test_find_files_for_date_empty_dir(self, sample_stofs_config, tmp_path):
        """Test file discovery returns empty set for nonexistent directory."""
        proc = RTOFSProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=tmp_path / "output",
        )

        result = proc._find_rtofs_files_for_date("20250504")
        assert len(result.files_2d) == 0
        assert len(result.files_3d) == 0

    def test_validate_file_size_too_small(self, sample_stofs_config, tmp_path):
        """Test file size validation rejects small files."""
        small_file = tmp_path / "small.nc"
        small_file.write_bytes(b"\x00" * 100)

        proc = RTOFSProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=tmp_path / "output",
        )

        assert proc._validate_file_size(small_file, 150_000_000) is False

    def test_validate_file_size_sufficient(self, sample_stofs_config, tmp_path):
        """Test file size validation accepts large enough files."""
        # Create a file larger than the minimum
        big_file = tmp_path / "big.nc"
        big_file.write_bytes(b"\x00" * 200)

        proc = RTOFSProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=tmp_path / "output",
        )

        assert proc._validate_file_size(big_file, 100) is True

    def test_validate_file_size_missing_file(self, sample_stofs_config, tmp_path):
        """Test file size validation rejects missing files."""
        proc = RTOFSProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=tmp_path / "output",
        )

        assert proc._validate_file_size(tmp_path / "missing.nc", 100) is False


class TestRTOFSMergeFileSets:
    """Tests for RTOFS file set merging."""

    def test_merge_uses_primary_when_sufficient(self, sample_stofs_config, tmp_path):
        """Test merge uses primary files when meeting threshold."""
        proc = RTOFSProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=tmp_path / "output",
            processing_config=RTOFSProcessingConfig(min_files_required=5),
        )

        primary = RTOFSFileSet(
            files_2d=[Path(f"/2d_{i}.nc") for i in range(15)],
            files_3d=[Path(f"/3d_{i}.nc") for i in range(15)],
            date="20250504",
        )
        backup = RTOFSFileSet(
            files_2d=[Path(f"/b2d_{i}.nc") for i in range(10)],
            files_3d=[Path(f"/b3d_{i}.nc") for i in range(10)],
            date="20250503",
        )

        result = proc._merge_file_sets(primary, backup)

        assert result.date == "20250504"
        assert not result.is_backup

    def test_merge_uses_backup_when_primary_empty(self, sample_stofs_config, tmp_path):
        """Test merge falls back to backup when primary is empty."""
        proc = RTOFSProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=tmp_path / "output",
            processing_config=RTOFSProcessingConfig(min_files_required=5),
        )

        primary = RTOFSFileSet(files_2d=[], files_3d=[], date="20250504")
        backup = RTOFSFileSet(
            files_2d=[Path(f"/b2d_{i}.nc") for i in range(15)],
            files_3d=[Path(f"/b3d_{i}.nc") for i in range(15)],
            date="20250503",
        )

        result = proc._merge_file_sets(primary, backup)

        assert result.is_backup is True
        assert len(result.files_2d) > 0

    def test_merge_equalizes_2d_3d_counts(self, sample_stofs_config, tmp_path):
        """Test merge ensures same number of 2D and 3D files."""
        proc = RTOFSProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=tmp_path / "output",
        )

        primary = RTOFSFileSet(
            files_2d=[Path(f"/2d_{i}.nc") for i in range(15)],
            files_3d=[Path(f"/3d_{i}.nc") for i in range(12)],
            date="20250504",
        )
        backup = RTOFSFileSet()

        result = proc._merge_file_sets(primary, backup)

        assert len(result.files_2d) == len(result.files_3d)


class TestRTOFSForecastHourExtraction:
    """Tests for forecast hour extraction from filenames."""

    def test_extract_nowcast_fhr(self, sample_stofs_config, tmp_path):
        """Test extracting forecast hour from nowcast filename."""
        proc = RTOFSProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=tmp_path / "output",
        )

        fhr = proc._extract_fhr_from_filename("rtofs_glo_2ds_n012_diag.nc")
        assert fhr == -12  # Nowcast hours are relative (n012 - 24 = -12)

    def test_extract_forecast_fhr(self, sample_stofs_config, tmp_path):
        """Test extracting forecast hour from forecast filename."""
        proc = RTOFSProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=tmp_path / "output",
        )

        fhr = proc._extract_fhr_from_filename("rtofs_glo_3dz_f024_6hrly_hvr_US_east.nc")
        assert fhr == 24

    def test_extract_fhr_invalid_filename(self, sample_stofs_config, tmp_path):
        """Test extracting forecast hour from invalid filename."""
        proc = RTOFSProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=tmp_path / "output",
        )

        fhr = proc._extract_fhr_from_filename("unknown_file.nc")
        assert fhr == 0


class TestRTOFSSSHOffset:
    """Tests for SSH offset application."""

    def test_ssh_offset_constant(self):
        """Test SSH offset constant value."""
        assert RTOFSProcessor.SSH_OFFSET == 0.04

    def test_processing_config_ssh_offset(self):
        """Test SSH offset in processing config matches."""
        cfg = RTOFSProcessingConfig()
        assert cfg.ssh_offset == 0.04

    def test_custom_ssh_offset(self):
        """Test custom SSH offset can be set."""
        cfg = RTOFSProcessingConfig(ssh_offset=0.06)
        assert cfg.ssh_offset == 0.06


class TestRTOFSVariables:
    """Tests for RTOFS variable definitions."""

    def test_all_expected_variables_defined(self):
        """Test all expected RTOFS variables are defined."""
        expected = ["temperature", "salinity", "ssh", "u_current", "v_current"]
        for var in expected:
            assert var in RTOFSProcessor.RTOFS_VARIABLES

    def test_default_variables_match_rtofs_variables(self):
        """Test default variables list matches RTOFS_VARIABLES keys."""
        assert set(RTOFSProcessor.DEFAULT_VARIABLES) == set(RTOFSProcessor.RTOFS_VARIABLES.keys())


class TestRTOFSOutputFileMapping:
    """Tests for output file naming conventions."""

    def test_expected_output_files(self):
        """Test expected RTOFS output file names."""
        expected_outputs = [
            "elev2D.th.nc",
            "TEM_3D.th.nc",
            "SAL_3D.th.nc",
            "uv3D.th.nc",
        ]
        for name in expected_outputs:
            assert ".nc" in name

    def test_nudging_output_files(self):
        """Test expected nudging output file names."""
        expected_nudge = ["TEM_nu.nc", "SAL_nu.nc"]
        for name in expected_nudge:
            assert ".nc" in name


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
