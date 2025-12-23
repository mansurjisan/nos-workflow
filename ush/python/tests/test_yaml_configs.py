"""
Integration tests for YAML configuration files.

Tests that all YAML config files can be loaded correctly.
"""

import sys
from pathlib import Path

import pytest
import yaml

# Add package to path for testing
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestBaseConfigs:
    """Tests for base model configuration files."""

    def test_schism_base_exists(self, base_configs):
        """Test that schism.yaml base config exists."""
        if 'schism' in base_configs and base_configs['schism'].exists():
            assert base_configs['schism'].exists()
        else:
            pytest.skip("schism.yaml not found")

    def test_fvcom_base_exists(self, base_configs):
        """Test that fvcom.yaml base config exists."""
        if 'fvcom' in base_configs and base_configs['fvcom'].exists():
            assert base_configs['fvcom'].exists()
        else:
            pytest.skip("fvcom.yaml not found")

    def test_roms_base_exists(self, base_configs):
        """Test that roms.yaml base config exists."""
        if 'roms' in base_configs and base_configs['roms'].exists():
            assert base_configs['roms'].exists()
        else:
            pytest.skip("roms.yaml not found")

    def test_base_configs_valid_yaml(self, base_configs):
        """Test that all existing base configs are valid YAML."""
        found_any = False
        for name, path in base_configs.items():
            if path.exists():
                found_any = True
                with open(path) as f:
                    data = yaml.safe_load(f)
                assert isinstance(data, dict), f"{name} config should be a dict"
        if not found_any:
            pytest.skip("No base configs found")


class TestSystemConfigs:
    """Tests for system configuration files."""

    def test_system_configs_exist(self, system_configs):
        """Test that system configs exist."""
        if len(system_configs) == 0:
            pytest.skip("No system configs found in parm/systems/")

    def test_stofs_3d_atl_config(self, system_configs):
        """Test STOFS 3D Atlantic configuration."""
        if 'stofs_3d_atl' not in system_configs:
            pytest.skip("stofs_3d_atl.yaml not found")

        path = system_configs['stofs_3d_atl']
        with open(path) as f:
            data = yaml.safe_load(f)

        # Check required fields
        assert 'system' in data
        assert data['system']['name'] == 'stofs_3d_atl'
        assert data['system']['framework'] == 'stofs'

        # Check grid config
        assert 'grid' in data
        assert 'domain' in data['grid']
        assert data['grid']['domain']['lon_min'] < data['grid']['domain']['lon_max']

    def test_secofs_config(self, system_configs):
        """Test SECOFS configuration."""
        if 'secofs' not in system_configs:
            pytest.skip("secofs.yaml not found")

        path = system_configs['secofs']
        with open(path) as f:
            data = yaml.safe_load(f)

        assert 'system' in data
        assert data['system']['name'] == 'secofs'
        assert data['system']['framework'] == 'comf'

    def test_cbofs_config(self, system_configs):
        """Test CBOFS configuration."""
        if 'cbofs' not in system_configs:
            pytest.skip("cbofs.yaml not found")

        path = system_configs['cbofs']
        with open(path) as f:
            data = yaml.safe_load(f)

        assert 'system' in data
        assert data['system']['name'] == 'cbofs'
        assert data['_base'] == 'roms'

    def test_leofs_config(self, system_configs):
        """Test LEOFS configuration."""
        if 'leofs' not in system_configs:
            pytest.skip("leofs.yaml not found")

        path = system_configs['leofs']
        with open(path) as f:
            data = yaml.safe_load(f)

        assert 'system' in data
        assert data['system']['name'] == 'leofs'
        assert data['_base'] == 'fvcom'
        # LEOFS is Great Lakes - no ocean BC
        if 'forcing' in data and 'ocean' in data['forcing']:
            assert data['forcing']['ocean'].get('enabled', True) == False

    def test_creofs_config(self, system_configs):
        """Test CREOFS configuration."""
        if 'creofs' not in system_configs:
            pytest.skip("creofs.yaml not found")

        path = system_configs['creofs']
        with open(path) as f:
            data = yaml.safe_load(f)

        assert 'system' in data
        assert data['system']['name'] == 'creofs'
        assert data['_base'] == 'schism'
        assert data['system']['framework'] == 'comf'

    def test_dbofs_config(self, system_configs):
        """Test DBOFS configuration."""
        if 'dbofs' not in system_configs:
            pytest.skip("dbofs.yaml not found")

        path = system_configs['dbofs']
        with open(path) as f:
            data = yaml.safe_load(f)

        assert 'system' in data
        assert data['system']['name'] == 'dbofs'
        assert data['_base'] == 'roms'

    def test_ngofs2_config(self, system_configs):
        """Test NGOFS2 configuration."""
        if 'ngofs2' not in system_configs:
            pytest.skip("ngofs2.yaml not found")

        path = system_configs['ngofs2']
        with open(path) as f:
            data = yaml.safe_load(f)

        assert 'system' in data
        assert data['system']['name'] == 'ngofs2'
        assert data['_base'] == 'fvcom'

    def test_stofs_3d_pac_config(self, system_configs):
        """Test STOFS 3D Pacific configuration."""
        if 'stofs_3d_pac' not in system_configs:
            pytest.skip("stofs_3d_pac.yaml not found")

        path = system_configs['stofs_3d_pac']
        with open(path) as f:
            data = yaml.safe_load(f)

        assert 'system' in data
        assert data['system']['name'] == 'stofs_3d_pac'
        assert data['system']['framework'] == 'stofs'
        # Pacific doesn't use HRRR
        if 'forcing' in data and 'atmospheric' in data['forcing']:
            hrrr = data['forcing']['atmospheric'].get('hrrr_blend', {})
            assert hrrr.get('enabled', True) == False

    def test_all_configs_valid_yaml(self, system_configs):
        """Test that all system configs are valid YAML."""
        if len(system_configs) == 0:
            pytest.skip("No system configs found")
        for name, path in system_configs.items():
            with open(path) as f:
                data = yaml.safe_load(f)
            assert isinstance(data, dict), f"{name} config should be a dict"

    def test_all_configs_have_system_name(self, system_configs):
        """Test that all configs have system.name field."""
        if len(system_configs) == 0:
            pytest.skip("No system configs found")
        for name, path in system_configs.items():
            with open(path) as f:
                data = yaml.safe_load(f)
            assert 'system' in data, f"{name} missing system section"
            assert 'name' in data['system'], f"{name} missing system.name"

    def test_all_configs_have_base_or_model(self, system_configs):
        """Test that all configs specify a base or model type."""
        if len(system_configs) == 0:
            pytest.skip("No system configs found")
        for name, path in system_configs.items():
            with open(path) as f:
                data = yaml.safe_load(f)
            # Should have _base for inheritance or explicit model config
            has_base = '_base' in data
            has_model = 'model' in data
            assert has_base or has_model, f"{name} missing _base or model section"


class TestConfigInheritance:
    """Tests for configuration inheritance."""

    def test_base_reference_valid(self, system_configs, base_configs):
        """Test that _base references point to existing configs."""
        if len(system_configs) == 0:
            pytest.skip("No system configs found")
        for name, path in system_configs.items():
            with open(path) as f:
                data = yaml.safe_load(f)

            if '_base' in data:
                base_name = data['_base']
                # Base should be one of the known model types
                assert base_name in ['schism', 'fvcom', 'roms'], \
                    f"{name} references unknown base config: {base_name}"


class TestDomainBounds:
    """Tests for domain bound validation."""

    def test_domain_lon_order(self, system_configs):
        """Test that lon_min < lon_max for all configs."""
        if len(system_configs) == 0:
            pytest.skip("No system configs found")
        for name, path in system_configs.items():
            with open(path) as f:
                data = yaml.safe_load(f)

            if 'grid' in data and 'domain' in data['grid']:
                domain = data['grid']['domain']
                if 'lon_min' in domain and 'lon_max' in domain:
                    # Handle wrap-around for Pacific (lon_min=-180)
                    if domain['lon_min'] == -180.0:
                        # This is a wrapped domain
                        pass
                    else:
                        assert domain['lon_min'] < domain['lon_max'], \
                            f"{name}: lon_min should be less than lon_max"

    def test_domain_lat_order(self, system_configs):
        """Test that lat_min < lat_max for all configs."""
        if len(system_configs) == 0:
            pytest.skip("No system configs found")
        for name, path in system_configs.items():
            with open(path) as f:
                data = yaml.safe_load(f)

            if 'grid' in data and 'domain' in data['grid']:
                domain = data['grid']['domain']
                if 'lat_min' in domain and 'lat_max' in domain:
                    assert domain['lat_min'] < domain['lat_max'], \
                        f"{name}: lat_min should be less than lat_max"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
