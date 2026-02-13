"""
Unit tests for SCHISM param.nml Generator.

Tests param.nml generation, parameter validation, and template loading.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from nos_ofs.models.param import SchismParameters, ParamNmlGenerator


class TestSchismParameters:
    """Tests for SchismParameters dataclass."""

    def test_default_values(self):
        """Test SchismParameters has sensible defaults."""
        params = SchismParameters()

        assert params.ipre == 0
        assert params.dt == 150.0
        assert params.rnday == 5.0
        assert params.ics == 2  # lon/lat coordinate system
        assert params.nws == 2  # sflux input
        assert params.nvrt == 51
        assert params.ihot == 0

    def test_custom_values(self):
        """Test SchismParameters with custom values."""
        params = SchismParameters(
            dt=120.0,
            rnday=3.5,
            nvrt=41,
            ihot=2,
        )

        assert params.dt == 120.0
        assert params.rnday == 3.5
        assert params.nvrt == 41
        assert params.ihot == 2

    def test_output_flags_defaults(self):
        """Test output flag defaults."""
        params = SchismParameters()

        assert params.iof_elev == 1
        assert params.iof_temp == 1
        assert params.iof_salt == 1
        assert params.iof_hvel == 1
        assert params.iof_flux == 0  # Off by default
        assert params.iof_vert == 0  # Off by default

    def test_custom_params_dict(self):
        """Test custom_params defaults to empty dict."""
        params = SchismParameters()
        assert params.custom_params == {}

    def test_to_namelist_string(self):
        """Test namelist string generation."""
        params = SchismParameters(dt=100.0, rnday=3.0)
        nml = params.to_namelist_string()

        assert "&CORE" in nml
        assert "&OPT" in nml
        assert "&SCHOUT" in nml
        assert "dt = 100.0" in nml
        assert "rnday = 3.000000" in nml
        # Verify all groups are properly terminated
        assert nml.count("/") >= 3

    def test_to_namelist_string_contains_all_core_params(self):
        """Test namelist string contains all CORE parameters."""
        params = SchismParameters()
        nml = params.to_namelist_string()

        core_params = [
            "ipre", "ibc", "ibtp", "rnday", "dt", "ics",
            "slam0", "sfea0", "ihot", "nvrt", "ncor", "nws",
        ]
        for param in core_params:
            assert f"  {param} = " in nml, f"Missing parameter: {param}"

    def test_to_namelist_string_contains_schout_params(self):
        """Test namelist string contains SCHOUT output parameters."""
        params = SchismParameters()
        nml = params.to_namelist_string()

        schout_params = [
            "iof_elev", "iof_temp", "iof_salt", "iof_hvel",
            "iout_sta", "nspool_sta",
        ]
        for param in schout_params:
            assert f"  {param} = " in nml, f"Missing SCHOUT parameter: {param}"


class TestParamNmlGenerator:
    """Tests for ParamNmlGenerator class."""

    def _make_config(self):
        """Create a mock config for generator."""
        config = Mock()
        config.dt = 150.0
        config.nvrt = 51
        config.RUN = "stofs_3d_atl"
        config.PDY = "20250504"
        config.cyc = 12
        config.lon_min = -98.5
        config.lon_max = -52.5
        config.lat_min = 7.3
        config.lat_max = 52.6
        config.ihot = 2
        config.hotstart_enabled = True
        config.system_name = "stofs_3d_atl"
        config.forecast_length = 96
        config.nowcast_length = 6
        config.output_interval_2d = 3600
        config.output_interval_station = 360
        config.output_variables_2d = ["elev", "wind"]
        config.output_variables_3d = ["temp", "salt"]
        config.get_fix_file = Mock(return_value=Path("/tmp/nonexistent_template"))
        return config

    def test_init_from_config(self):
        """Test generator initializes from config."""
        config = self._make_config()
        gen = ParamNmlGenerator(config)

        assert gen.params.dt == 150.0
        assert gen.params.nvrt == 51

    def test_init_sets_reference_coordinates(self):
        """Test generator computes reference coordinates from domain."""
        config = self._make_config()
        gen = ParamNmlGenerator(config)

        expected_slam0 = (-98.5 + -52.5) / 2.0
        expected_sfea0 = (7.3 + 52.6) / 2.0

        assert gen.params.slam0 == pytest.approx(expected_slam0)
        assert gen.params.sfea0 == pytest.approx(expected_sfea0)

    def test_init_sets_hotstart(self):
        """Test generator sets hotstart from config."""
        config = self._make_config()
        config.hotstart_enabled = True
        config.ihot = 2

        gen = ParamNmlGenerator(config)

        assert gen.params.ihot == 2

    def test_init_coldstart(self):
        """Test generator sets ihot=0 for cold start."""
        config = self._make_config()
        config.hotstart_enabled = False

        gen = ParamNmlGenerator(config)

        assert gen.params.ihot == 0


class TestParamNmlRunPeriod:
    """Tests for run period configuration."""

    def _make_gen(self):
        """Create a generator with mock config."""
        config = Mock()
        config.dt = 150.0
        config.nvrt = 51
        config.RUN = "stofs_3d_atl"
        config.PDY = "20250504"
        config.cyc = 12
        config.lon_min = -98.5
        config.lon_max = -52.5
        config.lat_min = 7.3
        config.lat_max = 52.6
        config.ihot = 0
        config.hotstart_enabled = False
        config.forecast_length = 96
        config.nowcast_length = 6
        config.output_interval_2d = 3600
        config.output_interval_station = 360
        config.output_variables_2d = []
        config.output_variables_3d = []
        config.system_name = "stofs_3d_atl"
        config.get_fix_file = Mock(return_value=Path("/tmp/nonexistent"))
        return ParamNmlGenerator(config)

    def test_set_run_period(self):
        """Test setting run period from hours."""
        gen = self._make_gen()
        gen.set_run_period(
            start_time=datetime(2025, 5, 3, 12),
            nowcast_hours=24,
            forecast_hours=96,
        )

        assert gen.params.rnday == pytest.approx(5.0)  # 120 hours = 5 days

    def test_set_run_period_short_forecast(self):
        """Test setting short run period."""
        gen = self._make_gen()
        gen.set_run_period(
            start_time=datetime(2025, 5, 3, 12),
            nowcast_hours=12,
            forecast_hours=48,
        )

        assert gen.params.rnday == pytest.approx(2.5)  # 60 hours = 2.5 days

    def test_set_hotstart_enabled(self):
        """Test enabling hotstart."""
        gen = self._make_gen()
        gen.set_hotstart(enabled=True, ihot=2)

        assert gen.params.ihot == 2

    def test_set_hotstart_disabled(self):
        """Test disabling hotstart."""
        gen = self._make_gen()
        gen.set_hotstart(enabled=False)

        assert gen.params.ihot == 0


class TestParamNmlOutputVariables:
    """Tests for output variable configuration."""

    def _make_gen(self):
        config = Mock()
        config.dt = 150.0
        config.nvrt = 51
        config.RUN = "stofs_3d_atl"
        config.PDY = "20250504"
        config.cyc = 12
        config.lon_min = -98.5
        config.lon_max = -52.5
        config.lat_min = 7.3
        config.lat_max = 52.6
        config.ihot = 0
        config.hotstart_enabled = False
        config.forecast_length = 96
        config.nowcast_length = 6
        config.output_interval_2d = 3600
        config.output_interval_station = 360
        config.output_variables_2d = []
        config.output_variables_3d = []
        config.system_name = "stofs_3d_atl"
        config.get_fix_file = Mock(return_value=Path("/tmp/nonexistent"))
        return ParamNmlGenerator(config)

    def test_set_2d_output_variables(self):
        """Test setting 2D output variables."""
        gen = self._make_gen()
        gen.set_output_variables(variables_2d=["elev", "wind", "flux"])

        assert gen.params.iof_elev == 1
        assert gen.params.iof_wind == 1
        assert gen.params.iof_flux == 1

    def test_set_3d_output_variables(self):
        """Test setting 3D output variables."""
        gen = self._make_gen()
        gen.set_output_variables(variables_3d=["temp", "salt", "velocity"])

        assert gen.params.iof_temp == 1
        assert gen.params.iof_salt == 1
        assert gen.params.iof_hvel == 1

    def test_set_output_variables_with_aliases(self):
        """Test setting output variables with alias names."""
        gen = self._make_gen()
        gen.set_output_variables(
            variables_2d=["elevation", "pressure"],
            variables_3d=["temperature", "salinity"],
        )

        assert gen.params.iof_elev == 1
        assert gen.params.iof_prmsl == 1
        assert gen.params.iof_temp == 1
        assert gen.params.iof_salt == 1


class TestParamNmlTemplateLoading:
    """Tests for template file loading."""

    def _make_gen(self):
        config = Mock()
        config.dt = 150.0
        config.nvrt = 51
        config.RUN = "stofs_3d_atl"
        config.PDY = "20250504"
        config.cyc = 12
        config.lon_min = -98.5
        config.lon_max = -52.5
        config.lat_min = 7.3
        config.lat_max = 52.6
        config.ihot = 0
        config.hotstart_enabled = False
        config.forecast_length = 96
        config.nowcast_length = 6
        config.output_interval_2d = 3600
        config.output_interval_station = 360
        config.output_variables_2d = []
        config.output_variables_3d = []
        config.system_name = "stofs_3d_atl"
        config.get_fix_file = Mock(return_value=Path("/tmp/nonexistent"))
        return ParamNmlGenerator(config)

    def test_load_template_missing_file(self):
        """Test loading template from non-existent file does not crash."""
        gen = self._make_gen()
        gen.load_template(Path("/tmp/nonexistent_template.nml"))

        # Should continue with default parameters
        assert gen.params.dt == 150.0

    def test_load_template_parses_values(self, tmp_path):
        """Test loading template parses parameter values."""
        template = tmp_path / "param.nml"
        template.write_text("""
&CORE
  dt = 120.0
  rnday = 3.5
  nvrt = 41
/
""")

        gen = self._make_gen()
        gen.load_template(template)

        assert gen.params.dt == 120.0
        assert gen.params.rnday == 3.5
        assert gen.params.nvrt == 41

    def test_load_template_handles_comments(self, tmp_path):
        """Test template parser handles inline comments."""
        template = tmp_path / "param.nml"
        template.write_text("""
! This is a comment
&CORE
  dt = 200.0  ! Time step in seconds
  rnday = 4.0  ! Run length in days
/
""")

        gen = self._make_gen()
        gen.load_template(template)

        assert gen.params.dt == 200.0
        assert gen.params.rnday == 4.0

    def test_load_template_stores_custom_params(self, tmp_path):
        """Test template stores unrecognized parameters in custom_params."""
        template = tmp_path / "param.nml"
        template.write_text("""
&CORE
  dt = 150.0
  my_custom_param = 42
/
""")

        gen = self._make_gen()
        gen.load_template(template)

        assert "my_custom_param" in gen.params.custom_params


class TestParamNmlGenerate:
    """Tests for param.nml file generation."""

    def _make_gen(self):
        config = Mock()
        config.dt = 150.0
        config.nvrt = 51
        config.RUN = "stofs_3d_atl"
        config.PDY = "20250504"
        config.cyc = 12
        config.lon_min = -98.5
        config.lon_max = -52.5
        config.lat_min = 7.3
        config.lat_max = 52.6
        config.ihot = 0
        config.hotstart_enabled = False
        config.forecast_length = 96
        config.nowcast_length = 6
        config.output_interval_2d = 3600
        config.output_interval_station = 360
        config.output_variables_2d = ["elev"]
        config.output_variables_3d = ["temp"]
        config.system_name = "stofs_3d_atl"
        config.get_fix_file = Mock(return_value=Path("/tmp/nonexistent"))
        return ParamNmlGenerator(config)

    def test_generate_creates_file(self, tmp_path):
        """Test generate creates a param.nml file."""
        gen = self._make_gen()
        output_file = tmp_path / "param.nml"

        result = gen.generate(output_file, use_template=False)

        assert result.exists()
        content = result.read_text()
        assert "&CORE" in content
        assert "&SCHOUT" in content

    def test_generate_for_cycle(self, tmp_path):
        """Test generate_for_cycle creates correct file."""
        gen = self._make_gen()
        output_file = tmp_path / "param.nml"

        result = gen.generate_for_cycle(
            output_path=output_file,
            pdy="20250504",
            cyc=12,
        )

        assert result.exists()
        content = result.read_text()
        assert "stofs_3d_atl" in content

    def test_generate_for_cycle_coldstart(self, tmp_path):
        """Test generate_for_cycle with coldstart=True."""
        gen = self._make_gen()
        output_file = tmp_path / "param.nml"

        gen.generate_for_cycle(
            output_path=output_file,
            pdy="20250504",
            cyc=12,
            coldstart=True,
        )

        assert gen.params.ihot == 0

    def test_generate_content_includes_header(self, tmp_path):
        """Test generated content includes informative header."""
        gen = self._make_gen()
        output_file = tmp_path / "param.nml"

        gen.generate(output_file, use_template=False)
        content = output_file.read_text()

        assert "param.nml" in content
        assert "stofs_3d_atl" in content


class TestParamNmlDefaultRunPeriods:
    """Tests for default run period configurations."""

    def test_stofs_3d_atl_default_period(self):
        """Test STOFS 3D Atlantic default run period."""
        assert ParamNmlGenerator.DEFAULT_RUN_PERIODS["stofs_3d_atl"] == 5.0

    def test_secofs_default_period(self):
        """Test SECOFS default run period."""
        assert ParamNmlGenerator.DEFAULT_RUN_PERIODS["secofs"] == 3.5

    def test_default_output_intervals_exist(self):
        """Test default output intervals are defined."""
        assert "stofs_3d_atl" in ParamNmlGenerator.DEFAULT_OUTPUT_INTERVALS
        assert "nspool" in ParamNmlGenerator.DEFAULT_OUTPUT_INTERVALS["stofs_3d_atl"]


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
