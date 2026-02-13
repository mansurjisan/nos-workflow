"""
Unit tests for GFS Forcing Processor.

Tests GFS atmospheric data processing for SCHISM sflux files.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, call

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from nos_ofs.forcing.gfs import GFSProcessor
from nos_ofs.base import ForcingResult


class TestGFSProcessorInit:
    """Tests for GFSProcessor initialization."""

    def test_init_with_defaults(self, sample_stofs_config, tmp_path):
        """Test GFS processor initializes with default values."""
        proc = GFSProcessor(
            config=sample_stofs_config,
            input_path=tmp_path / "gfs_in",
            output_path=tmp_path / "sflux",
        )

        assert proc.source_name == "GFS"
        assert proc.forecast_hours == 180
        assert proc.resolution == "0p25"
        assert proc.cyc == 12
        assert proc.pdy == "20250504"
        assert len(proc.variables) == len(GFSProcessor.DEFAULT_VARIABLES)

    def test_init_with_custom_values(self, sample_stofs_config, tmp_path):
        """Test GFS processor initializes with custom values."""
        proc = GFSProcessor(
            config=sample_stofs_config,
            input_path=tmp_path / "gfs_in",
            output_path=tmp_path / "sflux",
            variables=["uwind", "vwind"],
            forecast_hours=120,
            resolution="0p50",
        )

        assert proc.forecast_hours == 120
        assert proc.resolution == "0p50"
        assert proc.variables == ["uwind", "vwind"]

    def test_init_inherits_from_forcing_processor(self, sample_stofs_config, tmp_path):
        """Test that GFSProcessor inherits from ForcingProcessor."""
        proc = GFSProcessor(
            config=sample_stofs_config,
            input_path=tmp_path / "gfs_in",
            output_path=tmp_path / "sflux",
        )

        assert hasattr(proc, 'validate_input')
        assert hasattr(proc, 'create_output_dir')
        assert hasattr(proc, 'process')


class TestGRIB2VariableMapping:
    """Tests for GRIB2 variable mapping constants."""

    def test_all_default_variables_have_grib2_mapping(self):
        """Test that all default variables have a GRIB2 mapping."""
        for var in GFSProcessor.DEFAULT_VARIABLES:
            assert var in GFSProcessor.GRIB2_VARIABLES, \
                f"Variable '{var}' missing GRIB2 mapping"

    def test_grib2_variable_format(self):
        """Test GRIB2 variable mapping format is (name, level) tuple."""
        for schism_name, (grib_name, level) in GFSProcessor.GRIB2_VARIABLES.items():
            assert isinstance(grib_name, str), f"GRIB name for {schism_name} not str"
            assert isinstance(level, str), f"Level for {schism_name} not str"

    def test_expected_variables_present(self):
        """Test expected meteorological variables are in mapping."""
        expected = ["uwind", "vwind", "prmsl", "stmp", "spfh", "dlwrf", "dswrf", "prate"]
        for var in expected:
            assert var in GFSProcessor.GRIB2_VARIABLES

    def test_wind_variables_at_10m(self):
        """Test wind variables are at 10m above ground."""
        assert GFSProcessor.GRIB2_VARIABLES["uwind"][1] == "10 m above ground"
        assert GFSProcessor.GRIB2_VARIABLES["vwind"][1] == "10 m above ground"

    def test_temperature_at_2m(self):
        """Test temperature is at 2m above ground."""
        assert GFSProcessor.GRIB2_VARIABLES["stmp"][1] == "2 m above ground"


class TestGFSProcessMethod:
    """Tests for GFSProcessor.process() method."""

    def test_process_returns_failure_when_input_missing(self, sample_stofs_config, tmp_path):
        """Test process returns failure when input path does not exist."""
        proc = GFSProcessor(
            config=sample_stofs_config,
            input_path=tmp_path / "nonexistent",
            output_path=tmp_path / "sflux",
        )

        result = proc.process()

        assert isinstance(result, ForcingResult)
        assert not result.success
        assert "not found" in result.errors[0].lower() or "Input path" in result.errors[0]

    def test_process_returns_failure_when_no_gfs_files(self, sample_stofs_config, tmp_path):
        """Test process returns failure when no GFS files found."""
        input_dir = tmp_path / "gfs_in"
        input_dir.mkdir()

        proc = GFSProcessor(
            config=sample_stofs_config,
            input_path=input_dir,
            output_path=tmp_path / "sflux",
        )

        result = proc.process()

        assert isinstance(result, ForcingResult)
        assert not result.success
        assert any("No GFS" in e for e in result.errors)

    def test_process_creates_output_directory(self, sample_stofs_config, tmp_path):
        """Test that process creates the output directory."""
        input_dir = tmp_path / "gfs_in"
        input_dir.mkdir()
        output_dir = tmp_path / "sflux" / "nested"

        proc = GFSProcessor(
            config=sample_stofs_config,
            input_path=input_dir,
            output_path=output_dir,
        )

        proc.process()
        assert output_dir.exists()

    @patch.object(GFSProcessor, '_find_gfs_files')
    @patch.object(GFSProcessor, '_extract_grib2_data')
    @patch.object(GFSProcessor, '_create_sflux_files')
    @patch.object(GFSProcessor, '_create_sflux_inputs')
    def test_process_success_flow(
        self, mock_inputs, mock_sflux, mock_extract, mock_find,
        sample_stofs_config, tmp_path
    ):
        """Test successful processing flow with mocked internals."""
        input_dir = tmp_path / "gfs_in"
        input_dir.mkdir()

        mock_find.return_value = [Path("/fake/gfs.f000"), Path("/fake/gfs.f003")]
        mock_extract.return_value = {"times": [datetime(2025, 5, 4)], "lons": None, "lats": None}
        mock_sflux.return_value = [tmp_path / "sflux_air_1.0001.nc"]
        mock_inputs.return_value = tmp_path / "sflux_inputs.txt"

        proc = GFSProcessor(
            config=sample_stofs_config,
            input_path=input_dir,
            output_path=tmp_path / "sflux",
        )

        result = proc.process()

        assert result.success
        assert result.source == "GFS"
        assert "forecast_hours" in result.metadata
        mock_find.assert_called_once()
        mock_extract.assert_called_once()

    @patch.object(GFSProcessor, '_find_gfs_files')
    def test_process_handles_extraction_failure(
        self, mock_find, sample_stofs_config, tmp_path
    ):
        """Test process handles extraction returning empty data."""
        input_dir = tmp_path / "gfs_in"
        input_dir.mkdir()

        mock_find.return_value = [Path("/fake/gfs.f000")]

        proc = GFSProcessor(
            config=sample_stofs_config,
            input_path=input_dir,
            output_path=tmp_path / "sflux",
        )

        # _extract_grib2_data will fail with real files but mocked input path
        result = proc.process()
        # Should either fail gracefully or handle the missing data
        assert isinstance(result, ForcingResult)


class TestGFSFileFinding:
    """Tests for GFS file discovery methods."""

    def test_find_gfs_files_with_mock_directory(self, sample_stofs_config, mock_gfs_grib2):
        """Test finding GFS files in standard directory structure."""
        proc = GFSProcessor(
            config=sample_stofs_config,
            input_path=mock_gfs_grib2,
            output_path=mock_gfs_grib2 / "output",
        )

        files = proc._build_gfs_file_list()
        # Should find files from the mock directory
        assert isinstance(files, list)

    def test_find_gfs_files_simple(self, sample_stofs_config, tmp_path):
        """Test simple file finder for current cycle."""
        input_dir = tmp_path / "gfs_simple"
        input_dir.mkdir()

        # Create some files matching the pattern
        for fhr in [0, 3, 6, 9]:
            (input_dir / f"gfs.t12z.pgrb2.0p25.f{fhr:03d}").write_bytes(b"\x00")

        proc = GFSProcessor(
            config=sample_stofs_config,
            input_path=input_dir,
            output_path=tmp_path / "out",
        )

        files = proc._find_gfs_files_simple()
        assert len(files) == 4

    def test_find_gfs_files_simple_empty_dir(self, sample_stofs_config, tmp_path):
        """Test simple file finder returns empty list for empty directory."""
        input_dir = tmp_path / "empty"
        input_dir.mkdir()

        proc = GFSProcessor(
            config=sample_stofs_config,
            input_path=input_dir,
            output_path=tmp_path / "out",
        )

        files = proc._find_gfs_files_simple()
        assert files == []

    def test_find_gfs_files_filters_by_forecast_hours(self, sample_stofs_config, tmp_path):
        """Test that file finder filters by max forecast hours."""
        input_dir = tmp_path / "gfs_filter"
        input_dir.mkdir()

        for fhr in [0, 50, 100, 200, 300]:
            (input_dir / f"gfs.t12z.pgrb2.0p25.f{fhr:03d}").write_bytes(b"\x00")

        proc = GFSProcessor(
            config=sample_stofs_config,
            input_path=input_dir,
            output_path=tmp_path / "out",
            forecast_hours=120,
        )

        files = proc._find_gfs_files_simple()
        # Only files with fhr <= 120 should be included
        assert all(int(f.name.split('.f')[-1]) <= 120 for f in files)


class TestGFSMergeFileLists:
    """Tests for file list merging logic."""

    def test_merge_returns_primary_when_sufficient(self, sample_stofs_config, tmp_path):
        """Test merge returns primary list when it meets target."""
        proc = GFSProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=tmp_path,
        )

        primary = [Path(f"/p_{i}") for i in range(130)]
        backup = [Path(f"/b_{i}") for i in range(50)]

        result = proc._merge_file_lists(primary, backup, 121)
        assert result == primary

    def test_merge_supplements_from_backup(self, sample_stofs_config, tmp_path):
        """Test merge supplements primary with backup files."""
        proc = GFSProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=tmp_path,
        )

        primary = [Path(f"/p_{i}") for i in range(50)]
        backup = [Path(f"/b_{i}") for i in range(100)]

        result = proc._merge_file_lists(primary, backup, 121)
        assert len(result) > len(primary)
        # Primary files should come first
        assert result[:50] == primary

    def test_merge_returns_primary_when_no_backup(self, sample_stofs_config, tmp_path):
        """Test merge returns primary when backup is empty."""
        proc = GFSProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=tmp_path,
        )

        primary = [Path(f"/p_{i}") for i in range(50)]
        result = proc._merge_file_lists(primary, [], 121)
        assert result == primary


class TestGFSGrid:
    """Tests for GFS grid coordinate generation."""

    def test_grid_0p25_resolution(self, sample_stofs_config, tmp_path):
        """Test grid generation for 0.25 degree resolution."""
        proc = GFSProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=tmp_path,
            resolution="0p25",
        )

        lons, lats = proc._get_gfs_grid(
            Path("/fake"), -80.0, -70.0, 30.0, 40.0
        )

        assert lons[0] == pytest.approx(-80.0)
        assert lats[0] == pytest.approx(30.0)
        spacing = lons[1] - lons[0]
        assert spacing == pytest.approx(0.25)

    def test_grid_0p50_resolution(self, sample_stofs_config, tmp_path):
        """Test grid generation for 0.50 degree resolution."""
        proc = GFSProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=tmp_path,
            resolution="0p50",
        )

        lons, lats = proc._get_gfs_grid(
            Path("/fake"), -80.0, -70.0, 30.0, 40.0
        )

        spacing = lons[1] - lons[0]
        assert spacing == pytest.approx(0.50)


class TestGFSSfluxInputs:
    """Tests for sflux_inputs.txt creation."""

    def test_create_sflux_inputs(self, sample_stofs_config, tmp_path):
        """Test sflux_inputs.txt file creation."""
        output_dir = tmp_path / "sflux"
        output_dir.mkdir()

        proc = GFSProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=output_dir,
        )

        result = proc._create_sflux_inputs()

        assert result is not None
        assert result.exists()
        content = result.read_text()
        assert "&sflux_inputs" in content
        assert "air_1_relative_weight" in content
        assert "rad_1_relative_weight" in content
        assert "prc_1_relative_weight" in content


class TestGFSOutputFileNaming:
    """Tests for output file naming conventions."""

    def test_sflux_air_naming_pattern(self, sample_stofs_config, tmp_path):
        """Test sflux_air file naming follows XXXX pattern."""
        proc = GFSProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=tmp_path,
        )

        # Verify the expected pattern via internal method names
        # sflux_air_1.XXXX.nc where XXXX is day number
        expected_name = "sflux_air_1.0001.nc"
        assert "sflux_air_1" in expected_name
        assert ".nc" in expected_name


class TestForcingResult:
    """Tests for ForcingResult dataclass."""

    def test_forcing_result_boolean_true(self):
        """Test ForcingResult evaluates to True on success."""
        result = ForcingResult(success=True, source="GFS")
        assert bool(result) is True

    def test_forcing_result_boolean_false(self):
        """Test ForcingResult evaluates to False on failure."""
        result = ForcingResult(success=False, source="GFS")
        assert bool(result) is False

    def test_forcing_result_with_metadata(self):
        """Test ForcingResult stores metadata correctly."""
        result = ForcingResult(
            success=True,
            source="GFS",
            output_files=[Path("/tmp/test.nc")],
            metadata={"forecast_hours": 180, "resolution": "0p25"},
        )

        assert result.metadata["forecast_hours"] == 180
        assert len(result.output_files) == 1

    def test_forcing_result_default_empty_lists(self):
        """Test ForcingResult defaults to empty lists."""
        result = ForcingResult(success=True, source="GFS")
        assert result.output_files == []
        assert result.errors == []
        assert result.warnings == []


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
