"""
Unit tests for SCHISMModel.

Tests SCHISM model initialization, capabilities, and workflow.
"""

import sys
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, PropertyMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from nos_ofs.base_model import ModelType, ModelCapabilities, GridType, ModelResult


class TestModelType:
    """Tests for ModelType enumeration."""

    def test_model_type_values(self):
        """Test ModelType enum values."""
        assert ModelType.SCHISM.value == "schism"
        assert ModelType.FVCOM.value == "fvcom"
        assert ModelType.ROMS.value == "roms"

    def test_model_type_comparison(self):
        """Test ModelType enum comparison."""
        assert ModelType.SCHISM == ModelType.SCHISM
        assert ModelType.SCHISM != ModelType.ROMS
        assert ModelType.FVCOM != ModelType.ROMS

    def test_model_type_from_value(self):
        """Test creating ModelType from string value."""
        assert ModelType("schism") == ModelType.SCHISM
        assert ModelType("fvcom") == ModelType.FVCOM
        assert ModelType("roms") == ModelType.ROMS


class TestGridType:
    """Tests for GridType enumeration."""

    def test_grid_type_values(self):
        """Test GridType enum values."""
        assert GridType.STRUCTURED.value == "structured"
        assert GridType.UNSTRUCTURED.value == "unstructured"


class TestModelCapabilities:
    """Tests for ModelCapabilities dataclass."""

    def test_schism_capabilities(self):
        """Test SCHISM capabilities."""
        caps = ModelCapabilities(
            grid_type=GridType.UNSTRUCTURED,
            supports_nwm=True,
            vertical_coords="generalized",
        )

        assert caps.grid_type == GridType.UNSTRUCTURED
        assert caps.supports_nwm is True
        assert caps.vertical_coords == "generalized"
        assert caps.native_output_format == "netcdf"

    def test_default_capabilities(self):
        """Test default capability values."""
        caps = ModelCapabilities(grid_type=GridType.STRUCTURED)

        assert caps.supports_nwm is False
        assert caps.supports_da is False
        assert caps.supports_nesting is False
        assert caps.vertical_coords == "sigma"

    def test_roms_capabilities(self):
        """Test ROMS capabilities."""
        caps = ModelCapabilities(
            grid_type=GridType.STRUCTURED,
            supports_nesting=True,
            vertical_coords="sigma",
        )

        assert caps.grid_type == GridType.STRUCTURED
        assert caps.supports_nesting is True


class TestModelResult:
    """Tests for ModelResult dataclass."""

    def test_success_result(self):
        """Test successful model result."""
        result = ModelResult(
            success=True,
            stage="nowcast",
            message="Completed successfully",
        )

        assert result.success
        assert result.stage == "nowcast"

    def test_failure_result(self):
        """Test failed model result."""
        result = ModelResult(
            success=False,
            stage="forecast",
            message="Model crashed",
            errors=["Segfault at line 42"],
        )

        assert not result.success
        assert len(result.errors) == 1

    def test_result_with_output_files(self):
        """Test model result with output files."""
        result = ModelResult(
            success=True,
            stage="nowcast",
            output_files=[Path("/out/file1.nc"), Path("/out/file2.nc")],
        )

        assert len(result.output_files) == 2

    def test_result_default_empty_lists(self):
        """Test model result defaults to empty lists."""
        result = ModelResult(success=True, stage="test")

        assert result.output_files == []
        assert result.errors == []
        assert result.warnings == []
        assert result.metadata == {}


class TestSCHISMModelImport:
    """Tests for SCHISMModel import and class attributes."""

    def test_import_schism_model(self):
        """Test SCHISMModel can be imported."""
        from nos_ofs.models.schism_model import SCHISMModel
        assert SCHISMModel is not None

    def test_schism_model_type(self):
        """Test SCHISMModel has correct model type."""
        from nos_ofs.models.schism_model import SCHISMModel
        assert SCHISMModel.model_type == ModelType.SCHISM

    def test_schism_capabilities(self):
        """Test SCHISMModel capabilities."""
        from nos_ofs.models.schism_model import SCHISMModel
        caps = SCHISMModel.capabilities

        assert caps.grid_type == GridType.UNSTRUCTURED
        assert caps.supports_nwm is True
        assert caps.vertical_coords == "generalized"
        assert caps.native_output_format == "netcdf"


class TestSCHISMModelInit:
    """Tests for SCHISMModel initialization."""

    @patch('nos_ofs.models.schism_model.SCHISMGrid')
    def test_init_creates_grid(self, mock_grid_cls, sample_stofs_config):
        """Test SCHISMModel creates grid handler on init."""
        from nos_ofs.models.schism_model import SCHISMModel

        model = SCHISMModel(sample_stofs_config)

        mock_grid_cls.assert_called_once_with(sample_stofs_config)
        assert model.grid is not None

    @patch('nos_ofs.models.schism_model.SCHISMGrid')
    def test_init_creates_forcing_processors(self, mock_grid, sample_stofs_config):
        """Test SCHISMModel creates forcing processors on init."""
        from nos_ofs.models.schism_model import SCHISMModel

        model = SCHISMModel(sample_stofs_config)

        assert isinstance(model.forcing_processors, dict)
        # With all forcing enabled, should have multiple processors
        assert len(model.forcing_processors) > 0

    @patch('nos_ofs.models.schism_model.SCHISMGrid')
    def test_init_stores_config(self, mock_grid, sample_stofs_config):
        """Test SCHISMModel stores config reference."""
        from nos_ofs.models.schism_model import SCHISMModel

        model = SCHISMModel(sample_stofs_config)

        assert model.config is sample_stofs_config

    @patch('nos_ofs.models.schism_model.SCHISMGrid')
    def test_repr(self, mock_grid, sample_stofs_config):
        """Test SCHISMModel string representation."""
        from nos_ofs.models.schism_model import SCHISMModel

        model = SCHISMModel(sample_stofs_config)

        repr_str = repr(model)
        assert "SCHISMModel" in repr_str
        assert "stofs_3d_atl" in repr_str


class TestSCHISMModelForcingInit:
    """Tests for SCHISM forcing processor initialization."""

    @patch('nos_ofs.models.schism_model.SCHISMGrid')
    def test_gfs_processor_created_when_enabled(self, mock_grid, sample_stofs_config):
        """Test GFS processor is created when gfs_enabled is True."""
        from nos_ofs.models.schism_model import SCHISMModel

        sample_stofs_config.gfs_enabled = True
        model = SCHISMModel(sample_stofs_config)

        assert 'gfs' in model.forcing_processors

    @patch('nos_ofs.models.schism_model.SCHISMGrid')
    def test_hrrr_processor_created_when_enabled(self, mock_grid, sample_stofs_config):
        """Test HRRR processor is created when hrrr_enabled is True."""
        from nos_ofs.models.schism_model import SCHISMModel

        sample_stofs_config.hrrr_enabled = True
        model = SCHISMModel(sample_stofs_config)

        assert 'hrrr' in model.forcing_processors

    @patch('nos_ofs.models.schism_model.SCHISMGrid')
    def test_hrrr_not_created_when_disabled(self, mock_grid, sample_stofs_config):
        """Test HRRR processor is not created when hrrr_enabled is False."""
        from nos_ofs.models.schism_model import SCHISMModel

        sample_stofs_config.hrrr_enabled = False
        model = SCHISMModel(sample_stofs_config)

        assert 'hrrr' not in model.forcing_processors


class TestSCHISMModelRunModel:
    """Tests for SCHISMModel.run_model() method."""

    @patch('nos_ofs.models.schism_model.SCHISMGrid')
    @patch('nos_ofs.models.schism_model.SchismWorkflowModel')
    def test_run_model_success(self, mock_wf_cls, mock_grid, sample_stofs_config):
        """Test run_model returns success on completion."""
        from nos_ofs.models.schism_model import SCHISMModel

        mock_wf = MagicMock()
        mock_wf_cls.return_value = mock_wf

        model = SCHISMModel(sample_stofs_config)
        result = model.run_model("nowcast")

        assert isinstance(result, ModelResult)
        assert result.success
        assert result.stage == "nowcast"

    @patch('nos_ofs.models.schism_model.SCHISMGrid')
    @patch('nos_ofs.models.schism_model.SchismWorkflowModel')
    def test_run_model_failure(self, mock_wf_cls, mock_grid, sample_stofs_config):
        """Test run_model returns failure on exception."""
        from nos_ofs.models.schism_model import SCHISMModel

        mock_wf = MagicMock()
        mock_wf.run_stage.side_effect = RuntimeError("Model crashed")
        mock_wf_cls.return_value = mock_wf

        model = SCHISMModel(sample_stofs_config)
        result = model.run_model("forecast")

        assert isinstance(result, ModelResult)
        assert not result.success
        assert "crashed" in result.message.lower()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
