"""
Unit tests for NWM Forcing Processor.

Tests NWM river discharge processing for SCHISM.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from nos_ofs.forcing.nwm import NWMProcessor
from nos_ofs.base import ForcingResult


class TestNWMProcessorInit:
    """Tests for NWMProcessor initialization."""

    def test_init_with_defaults(self, sample_stofs_config, tmp_path):
        """Test NWM processor initializes with default values."""
        proc = NWMProcessor(
            config=sample_stofs_config,
            input_path=tmp_path / "nwm_in",
            output_path=tmp_path / "output",
        )

        assert proc.source_name == "NWM"
        assert proc.product == "medium_range"
        assert proc.num_rivers == 534
        assert proc.use_climatology is True
        assert proc.variables == ["streamflow"]

    def test_init_with_custom_values(self, sample_stofs_config, tmp_path):
        """Test NWM processor initializes with custom values."""
        proc = NWMProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=tmp_path,
            product="short_range",
            num_rivers=127,
            use_climatology=False,
        )

        assert proc.product == "short_range"
        assert proc.num_rivers == 127
        assert proc.use_climatology is False


class TestNWMProductTypes:
    """Tests for NWM product type constants."""

    def test_product_type_constants(self):
        """Test NWM product type constant values."""
        assert NWMProcessor.ANALYSIS == "analysis_assim"
        assert NWMProcessor.SHORT_RANGE == "short_range"
        assert NWMProcessor.MEDIUM_RANGE == "medium_range"
        assert NWMProcessor.LONG_RANGE == "long_range"


class TestNWMClimatology:
    """Tests for NWM climatological data."""

    def test_seasonal_multipliers_cover_all_months(self):
        """Test seasonal multipliers exist for all 12 months."""
        for month in range(1, 13):
            assert month in NWMProcessor.SEASONAL_MULTIPLIERS

    def test_seasonal_multipliers_are_positive(self):
        """Test all seasonal multipliers are positive."""
        for month, mult in NWMProcessor.SEASONAL_MULTIPLIERS.items():
            assert mult > 0, f"Month {month} has non-positive multiplier"

    def test_spring_peak_higher_than_summer(self):
        """Test spring discharge peak is higher than summer low."""
        spring_peak = NWMProcessor.SEASONAL_MULTIPLIERS[4]  # April
        summer_low = NWMProcessor.SEASONAL_MULTIPLIERS[8]   # August
        assert spring_peak > summer_low

    def test_temp_climatology_covers_all_months(self):
        """Test temperature climatology covers all 12 months."""
        for month in range(1, 13):
            assert month in NWMProcessor.TEMP_CLIMATOLOGY

    def test_temp_climatology_is_reasonable(self):
        """Test temperature values are within reasonable range."""
        for month, temp in NWMProcessor.TEMP_CLIMATOLOGY.items():
            assert -5 <= temp <= 35, f"Month {month} temp {temp} out of range"


class TestNWMProcess:
    """Tests for NWMProcessor.process() method."""

    def test_process_fails_when_input_missing(self, sample_stofs_config, tmp_path):
        """Test process fails when input path does not exist."""
        proc = NWMProcessor(
            config=sample_stofs_config,
            input_path=tmp_path / "nonexistent",
            output_path=tmp_path / "output",
        )

        result = proc.process()

        assert not result.success
        assert len(result.errors) > 0

    @patch.object(NWMProcessor, '_load_river_config')
    @patch.object(NWMProcessor, '_find_nwm_files')
    @patch.object(NWMProcessor, '_generate_climatology')
    @patch.object(NWMProcessor, '_create_vsource')
    @patch.object(NWMProcessor, '_create_msource')
    @patch.object(NWMProcessor, '_create_source_sink_in')
    def test_process_falls_back_to_climatology(
        self, mock_ss, mock_ms, mock_vs, mock_clim, mock_find, mock_rc,
        sample_stofs_config, tmp_path
    ):
        """Test process falls back to climatology when no NWM files."""
        input_dir = tmp_path / "nwm_in"
        input_dir.mkdir()

        mock_rc.return_value = {"feature_ids": [1, 2], "node_indices": [1, 2]}
        mock_find.return_value = []
        mock_clim.return_value = {
            "times": [datetime(2025, 5, 4)],
            "streamflow": np.array([[10.0, 20.0]]),
        }
        mock_vs.return_value = tmp_path / "vsource.th"
        mock_ms.return_value = tmp_path / "msource.th"
        mock_ss.return_value = tmp_path / "source_sink.in"

        proc = NWMProcessor(
            config=sample_stofs_config,
            input_path=input_dir,
            output_path=tmp_path / "output",
            use_climatology=True,
        )

        result = proc.process()

        assert result.success
        assert "climatology" in result.warnings[0].lower() or "climatology" in result.metadata.get("product", "")
        mock_clim.assert_called_once()


class TestNWMFileFinding:
    """Tests for NWM file discovery."""

    def test_find_nwm_files_with_mock_directory(self, sample_stofs_config, mock_nwm_nc):
        """Test finding NWM files in standard directory."""
        proc = NWMProcessor(
            config=sample_stofs_config,
            input_path=mock_nwm_nc,
            output_path=mock_nwm_nc / "output",
        )

        files = proc._find_nwm_files()
        assert len(files) == 25

    def test_find_nwm_files_empty_dir(self, sample_stofs_config, tmp_path):
        """Test finding NWM files returns empty list for empty dir."""
        input_dir = tmp_path / "empty"
        input_dir.mkdir()

        proc = NWMProcessor(
            config=sample_stofs_config,
            input_path=input_dir,
            output_path=tmp_path / "output",
        )

        files = proc._find_nwm_files()
        assert files == []


class TestNWMForecastHourExtraction:
    """Tests for forecast hour extraction from NWM filenames."""

    def test_extract_fhr_from_standard_filename(self, sample_stofs_config, tmp_path):
        """Test extracting forecast hour from standard NWM filename."""
        proc = NWMProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=tmp_path,
        )

        fhr = proc._extract_fhr_from_filename(
            "nwm.t12z.medium_range.channel_rt.f024.conus.nc"
        )
        assert fhr == 24

    def test_extract_fhr_from_invalid_filename(self, sample_stofs_config, tmp_path):
        """Test extracting forecast hour from invalid filename returns 0."""
        proc = NWMProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=tmp_path,
        )

        fhr = proc._extract_fhr_from_filename("unknown_file.nc")
        assert fhr == 0


class TestNWMRiverConfig:
    """Tests for river configuration loading."""

    def test_create_default_config(self, sample_stofs_config, tmp_path):
        """Test creating default river configuration."""
        proc = NWMProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=tmp_path,
            num_rivers=10,
        )

        config = proc._create_default_config()

        assert len(config["feature_ids"]) == 10
        assert len(config["node_indices"]) == 10
        assert len(config["river_names"]) == 10
        assert all(t == 15.0 for t in config["clim_temp"])
        assert all(s == 0.0 for s in config["clim_salt"])

    def test_load_river_config_missing_file(self, sample_stofs_config, tmp_path):
        """Test loading river config when file is missing."""
        proc = NWMProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=tmp_path,
        )

        config = proc._load_river_config()

        assert config["feature_ids"] == []
        assert config["node_indices"] == []


class TestNWMClimatologyGeneration:
    """Tests for climatological discharge generation."""

    def test_generate_climatology_produces_121_timesteps(self, sample_stofs_config, tmp_path):
        """Test climatology generates 121 time steps (5 days hourly)."""
        proc = NWMProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=tmp_path,
            num_rivers=5,
        )

        river_config = proc._create_default_config()
        data = proc._generate_climatology(river_config)

        assert len(data["times"]) == 121
        assert data["streamflow"].shape == (121, 5)

    def test_generate_climatology_applies_seasonal_multiplier(
        self, sample_stofs_config, tmp_path
    ):
        """Test climatology applies seasonal multiplier correctly."""
        proc = NWMProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=tmp_path,
            num_rivers=1,
        )

        river_config = {
            "feature_ids": [1],
            "node_indices": [1],
            "mean_discharge": [100.0],
        }

        data = proc._generate_climatology(river_config)

        # All streamflow values should be positive
        assert np.all(data["streamflow"] > 0)


class TestNWMOutputFiles:
    """Tests for NWM output file creation."""

    def test_create_vsource_with_data(self, sample_stofs_config, tmp_path):
        """Test vsource.th creation with valid data."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        proc = NWMProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=output_dir,
            num_rivers=2,
        )

        times = [
            datetime(2025, 5, 4, 0),
            datetime(2025, 5, 4, 1),
            datetime(2025, 5, 4, 2),
        ]
        river_data = {
            "times": times,
            "streamflow": np.array([[10.0, 20.0], [11.0, 21.0], [12.0, 22.0]]),
        }

        result = proc._create_vsource(river_data)

        assert result is not None
        assert result.exists()
        content = result.read_text()
        lines = [l for l in content.strip().split('\n') if l.strip()]
        assert len(lines) == 3

    def test_create_vsource_empty_data(self, sample_stofs_config, tmp_path):
        """Test vsource.th returns None with empty data."""
        proc = NWMProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=tmp_path,
        )

        result = proc._create_vsource({"times": [], "streamflow": []})
        assert result is None

    def test_create_msource_with_data(self, sample_stofs_config, tmp_path):
        """Test msource.th creation with valid data."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        proc = NWMProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=output_dir,
            num_rivers=2,
        )

        times = [datetime(2025, 5, 4, 0), datetime(2025, 5, 4, 1)]
        river_data = {"times": times}

        result = proc._create_msource(river_data)

        assert result is not None
        assert result.exists()
        content = result.read_text()
        # Should contain temp and salinity for each river
        lines = [l for l in content.strip().split('\n') if l.strip()]
        assert len(lines) == 2

    def test_create_source_sink_in(self, sample_stofs_config, tmp_path):
        """Test source_sink.in creation."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        proc = NWMProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=output_dir,
            num_rivers=3,
        )

        river_config = {
            "node_indices": [100, 200, 300],
        }

        result = proc._create_source_sink_in(river_config)

        assert result is not None
        assert result.exists()
        content = result.read_text()
        lines = content.strip().split('\n')
        # First line = number of sources, then one line per source, then "0" for sinks
        assert lines[0].strip() == "3"
        assert "0" in lines[-1]  # No sinks


class TestNWMQCAppendRows:
    """Tests for QC row append functionality."""

    def test_qc_append_rows_extends_file(self, sample_stofs_config, tmp_path):
        """Test QC appends rows when file is too short."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        th_file = output_dir / "vsource.th"
        th_file.write_text("0.0 10.0 20.0\n3600.0 11.0 21.0\n")

        proc = NWMProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=output_dir,
        )

        proc._qc_append_rows(th_file, 5)

        content = th_file.read_text()
        lines = [l for l in content.strip().split('\n') if l.strip()]
        assert len(lines) >= 5

    def test_qc_append_rows_no_change_when_sufficient(self, sample_stofs_config, tmp_path):
        """Test QC does not modify file when rows are sufficient."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        lines = [f"{i * 3600.0:.1f} 10.0 20.0" for i in range(10)]
        th_file = output_dir / "vsource.th"
        th_file.write_text("\n".join(lines) + "\n")

        proc = NWMProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=output_dir,
        )

        proc._qc_append_rows(th_file, 5)

        content = th_file.read_text()
        result_lines = [l for l in content.strip().split('\n') if l.strip()]
        assert len(result_lines) == 10  # No change

    def test_qc_append_missing_file(self, sample_stofs_config, tmp_path):
        """Test QC handles missing file gracefully."""
        proc = NWMProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=tmp_path,
        )

        # Should not raise
        proc._qc_append_rows(tmp_path / "nonexistent.th", 10)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
