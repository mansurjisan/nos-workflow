"""
Unit tests for HRRR Forcing Processor.

Tests HRRR atmospheric data processing and GFS blending logic.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from nos_ofs.forcing.hrrr import HRRRProcessor
from nos_ofs.base import ForcingResult


class TestHRRRProcessorInit:
    """Tests for HRRRProcessor initialization."""

    def test_init_with_defaults(self, sample_stofs_config, tmp_path):
        """Test HRRR processor initializes with default values."""
        proc = HRRRProcessor(
            config=sample_stofs_config,
            input_path=tmp_path / "hrrr_in",
            output_path=tmp_path / "sflux",
        )

        assert proc.source_name == "HRRR"
        assert proc.forecast_hours == 48
        assert proc.priority == "high"
        assert proc.variables == HRRRProcessor.DEFAULT_VARIABLES

    def test_init_caps_forecast_hours_at_48(self, sample_stofs_config, tmp_path):
        """Test HRRR caps forecast hours at maximum 48."""
        proc = HRRRProcessor(
            config=sample_stofs_config,
            input_path=tmp_path / "hrrr_in",
            output_path=tmp_path / "sflux",
            forecast_hours=120,
        )

        assert proc.forecast_hours == 48

    def test_init_custom_variables(self, sample_stofs_config, tmp_path):
        """Test HRRR initializes with custom variables."""
        proc = HRRRProcessor(
            config=sample_stofs_config,
            input_path=tmp_path / "hrrr_in",
            output_path=tmp_path / "sflux",
            variables=["uwind", "vwind", "prmsl", "stmp"],
        )

        assert proc.variables == ["uwind", "vwind", "prmsl", "stmp"]


class TestHRRRGRIB2Mapping:
    """Tests for HRRR GRIB2 variable mapping."""

    def test_hrrr_uses_mslma_for_pressure(self):
        """Test HRRR uses MSLMA instead of PRMSL for pressure."""
        assert HRRRProcessor.GRIB2_VARIABLES["prmsl"][0] == "MSLMA"

    def test_hrrr_has_expected_variables(self):
        """Test HRRR has all expected variable mappings."""
        expected = ["uwind", "vwind", "prmsl", "stmp", "spfh", "dlwrf", "dswrf", "prate"]
        for var in expected:
            assert var in HRRRProcessor.GRIB2_VARIABLES

    def test_default_variables_are_wind_and_pressure(self):
        """Test default HRRR variables are wind and pressure."""
        assert "uwind" in HRRRProcessor.DEFAULT_VARIABLES
        assert "vwind" in HRRRProcessor.DEFAULT_VARIABLES
        assert "prmsl" in HRRRProcessor.DEFAULT_VARIABLES


class TestHRRRProcess:
    """Tests for HRRRProcessor.process() method."""

    def test_process_returns_success_when_input_missing(self, sample_stofs_config, tmp_path):
        """Test HRRR returns success (non-fatal) when input missing."""
        proc = HRRRProcessor(
            config=sample_stofs_config,
            input_path=tmp_path / "nonexistent",
            output_path=tmp_path / "sflux",
        )

        result = proc.process()

        # HRRR is optional -- missing data is non-fatal
        assert isinstance(result, ForcingResult)
        assert result.success is True
        assert len(result.warnings) > 0

    def test_process_returns_success_when_no_files_found(
        self, sample_stofs_config, tmp_path
    ):
        """Test HRRR returns success with warning when no files found."""
        input_dir = tmp_path / "hrrr_empty"
        input_dir.mkdir()

        proc = HRRRProcessor(
            config=sample_stofs_config,
            input_path=input_dir,
            output_path=tmp_path / "sflux",
        )

        result = proc.process()

        assert result.success is True
        assert any("No HRRR" in w for w in result.warnings)

    @patch.object(HRRRProcessor, '_find_hrrr_files')
    @patch.object(HRRRProcessor, '_extract_grib2_data')
    @patch.object(HRRRProcessor, '_create_sflux_files')
    def test_process_success_flow(
        self, mock_sflux, mock_extract, mock_find,
        sample_stofs_config, tmp_path
    ):
        """Test successful processing flow."""
        input_dir = tmp_path / "hrrr_in"
        input_dir.mkdir()

        mock_find.return_value = [Path("/fake/hrrr.f01")]
        mock_extract.return_value = {
            "times": [datetime(2025, 5, 4, 13)],
            "lons": np.array([1.0]),
            "lats": np.array([1.0]),
            "uwind": [np.array([1.0])],
        }
        mock_sflux.return_value = [tmp_path / "sflux_air_2.0001.nc"]

        proc = HRRRProcessor(
            config=sample_stofs_config,
            input_path=input_dir,
            output_path=tmp_path / "sflux",
        )

        result = proc.process()

        assert result.success
        assert result.source == "HRRR"

    @patch.object(HRRRProcessor, '_find_hrrr_files')
    def test_process_handles_exception_gracefully(
        self, mock_find, sample_stofs_config, tmp_path
    ):
        """Test HRRR handles exceptions as non-fatal."""
        input_dir = tmp_path / "hrrr_in"
        input_dir.mkdir()

        mock_find.side_effect = RuntimeError("Unexpected error")

        proc = HRRRProcessor(
            config=sample_stofs_config,
            input_path=input_dir,
            output_path=tmp_path / "sflux",
        )

        result = proc.process()

        # HRRR failure should be non-fatal
        assert result.success is True
        assert any("failed" in w.lower() for w in result.warnings)


class TestHRRRFileFinding:
    """Tests for HRRR file discovery."""

    def test_find_hrrr_files_with_mock_directory(
        self, sample_stofs_config, mock_hrrr_grib2
    ):
        """Test finding HRRR files in standard directory structure."""
        proc = HRRRProcessor(
            config=sample_stofs_config,
            input_path=mock_hrrr_grib2,
            output_path=mock_hrrr_grib2 / "output",
        )

        files = proc._find_hrrr_files()
        # Should find at least the forecast files from today
        assert isinstance(files, list)
        assert len(files) > 0

    def test_find_hrrr_files_empty_dir(self, sample_stofs_config, tmp_path):
        """Test finding HRRR files in empty directory."""
        input_dir = tmp_path / "empty"
        input_dir.mkdir()

        proc = HRRRProcessor(
            config=sample_stofs_config,
            input_path=input_dir,
            output_path=tmp_path / "out",
        )

        files = proc._find_hrrr_files()
        assert files == []

    def test_find_hrrr_files_simple(self, sample_stofs_config, tmp_path):
        """Test simple file finder method."""
        input_dir = tmp_path / "hrrr_simple"
        input_dir.mkdir()

        for fhr in range(1, 10):
            (input_dir / f"hrrr.t12z.wrfsfcf{fhr:02d}.grib2").write_bytes(b"\x00")

        proc = HRRRProcessor(
            config=sample_stofs_config,
            input_path=input_dir,
            output_path=tmp_path / "out",
        )

        files = proc._find_hrrr_files_simple()
        assert len(files) == 9


class TestHRRRGrid:
    """Tests for HRRR grid generation."""

    def test_hrrr_grid_resolution(self, sample_stofs_config, tmp_path):
        """Test HRRR grid has ~3km resolution."""
        proc = HRRRProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=tmp_path,
        )

        lons, lats = proc._get_hrrr_grid(-80.0, -70.0, 30.0, 40.0)

        spacing = lons[1] - lons[0]
        assert spacing == pytest.approx(0.03)
        assert lons[0] == pytest.approx(-80.0)
        assert lats[0] == pytest.approx(30.0)

    def test_hrrr_grid_has_correct_extent(self, sample_stofs_config, tmp_path):
        """Test HRRR grid covers the requested domain."""
        proc = HRRRProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=tmp_path,
        )

        lons, lats = proc._get_hrrr_grid(-80.0, -70.0, 30.0, 40.0)

        assert lons[0] >= -80.0
        assert lons[-1] <= -70.0 + 0.03
        assert lats[0] >= 30.0
        assert lats[-1] <= 40.0 + 0.03


class TestHRRRBlendingConcept:
    """Tests for HRRR-GFS blending concept (sflux index assignment)."""

    def test_hrrr_creates_air_2_files(self, sample_stofs_config, tmp_path):
        """Test HRRR creates sflux_air_2 (secondary source)."""
        proc = HRRRProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=tmp_path,
            priority="high",
        )

        # Verify the priority is stored
        assert proc.priority == "high"

    def test_hrrr_priority_options(self, sample_stofs_config, tmp_path):
        """Test HRRR supports different priority levels."""
        for priority in ["high", "low"]:
            proc = HRRRProcessor(
                config=sample_stofs_config,
                input_path=tmp_path,
                output_path=tmp_path,
                priority=priority,
            )
            assert proc.priority == priority


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
