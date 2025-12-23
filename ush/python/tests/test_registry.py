"""
Unit tests for OFS Registry module.

Tests the factory pattern for creating model instances.
"""

import sys
from pathlib import Path

import pytest

# Add package to path for testing
sys.path.insert(0, str(Path(__file__).parent.parent))

from nos_ofs.registry import OFSRegistry
from nos_ofs.base_model import ModelType


class TestOFSRegistry:
    """Tests for OFSRegistry class."""

    def test_list_available(self):
        """Test listing available OFS systems."""
        available = OFSRegistry.list_available()

        assert isinstance(available, dict)
        assert len(available) > 0

        # Check some known systems
        assert 'stofs_3d_atl' in available
        assert 'cbofs' in available
        assert 'leofs' in available

    def test_get_model_type_schism(self):
        """Test getting model type for SCHISM-based systems."""
        # SCHISM systems
        schism_systems = ['stofs_3d_atl', 'stofs_3d_pac', 'secofs', 'creofs']

        for ofs in schism_systems:
            model_type = OFSRegistry.get_model_type(ofs)
            assert model_type == ModelType.SCHISM

    def test_get_model_type_roms(self):
        """Test getting model type for ROMS-based systems."""
        # ROMS systems
        roms_systems = ['cbofs', 'dbofs', 'tbofs', 'gomofs']

        for ofs in roms_systems:
            model_type = OFSRegistry.get_model_type(ofs)
            assert model_type == ModelType.ROMS

    def test_get_model_type_fvcom(self):
        """Test getting model type for FVCOM-based systems."""
        # FVCOM systems (Great Lakes and others)
        fvcom_systems = ['leofs', 'loofs', 'ngofs2']

        for ofs in fvcom_systems:
            model_type = OFSRegistry.get_model_type(ofs)
            assert model_type == ModelType.FVCOM

    def test_unknown_ofs(self):
        """Test handling of unknown OFS name."""
        with pytest.raises(ValueError) as exc_info:
            OFSRegistry.get_model_type('unknown_ofs')

        assert 'Unknown OFS' in str(exc_info.value)

    def test_case_insensitivity(self):
        """Test that OFS names are case-insensitive."""
        # Should work with different cases
        assert OFSRegistry.get_model_type('stofs_3d_atl') == ModelType.SCHISM
        assert OFSRegistry.get_model_type('STOFS_3D_ATL') == ModelType.SCHISM
        assert OFSRegistry.get_model_type('Stofs_3D_Atl') == ModelType.SCHISM

    def test_list_by_model_type(self):
        """Test filtering OFS systems by model type."""
        schism_systems = OFSRegistry.list_by_model_type(ModelType.SCHISM)
        assert 'stofs_3d_atl' in schism_systems
        assert 'secofs' in schism_systems

        roms_systems = OFSRegistry.list_by_model_type(ModelType.ROMS)
        assert 'cbofs' in roms_systems

        fvcom_systems = OFSRegistry.list_by_model_type(ModelType.FVCOM)
        assert 'leofs' in fvcom_systems

    def test_register_new_ofs(self):
        """Test registering a new OFS system."""
        # Register a custom OFS
        OFSRegistry.register_ofs('custom_ofs', ModelType.SCHISM)

        assert 'custom_ofs' in OFSRegistry.OFS_MODEL_TYPES
        assert OFSRegistry.get_model_type('custom_ofs') == ModelType.SCHISM

        # Clean up
        del OFSRegistry.OFS_MODEL_TYPES['custom_ofs']


class TestModelTypeEnum:
    """Tests for ModelType enumeration."""

    def test_model_type_values(self):
        """Test ModelType enum values."""
        assert ModelType.SCHISM.value == 'schism'
        assert ModelType.FVCOM.value == 'fvcom'
        assert ModelType.ROMS.value == 'roms'

    def test_model_type_comparison(self):
        """Test ModelType enum comparison."""
        assert ModelType.SCHISM == ModelType.SCHISM
        assert ModelType.SCHISM != ModelType.ROMS


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
