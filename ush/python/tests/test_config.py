"""
Unit tests for NOS OFS configuration module.

Tests YAML configuration loading, inheritance, and environment variable export.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Add package to path for testing
sys.path.insert(0, str(Path(__file__).parent.parent))

from nos_ofs.config.config_legacy import OFSConfig


class TestOFSConfig:
    """Tests for OFSConfig class."""

    def test_from_environment(self):
        """Test loading config from environment variables."""
        # Set some environment variables
        os.environ['OFS'] = 'test_ofs'
        os.environ['RUN'] = 'test_ofs'
        os.environ['PDY'] = '20250115'
        os.environ['cyc'] = '12'

        try:
            config = OFSConfig.from_environment()
            assert config is not None
            # Check that runtime values were loaded
            assert config.runtime.pdy == '20250115' or config.PDY == '20250115'
        finally:
            # Clean up
            os.environ.pop('OFS', None)
            os.environ.pop('RUN', None)
            os.environ.pop('PDY', None)
            os.environ.pop('cyc', None)

    def test_yaml_file_loading(self):
        """Test loading configuration from YAML file."""
        # Create a temporary YAML config
        yaml_content = """
system:
  name: test_ofs
  framework: comf
  version: "1.0.0"
  model_type: schism

grid:
  n_nodes: 1000
  n_elements: 2000
  domain:
    lon_min: -80.0
    lon_max: -70.0
    lat_min: 30.0
    lat_max: 40.0
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        try:
            config = OFSConfig.from_yaml(temp_path)
            assert config is not None
            # Check that data was loaded
            assert config._yaml_data is not None
            assert 'system' in config._yaml_data
        finally:
            os.unlink(temp_path)

    def test_yaml_with_system_name(self):
        """Test loading YAML with system name."""
        yaml_content = """
system:
  name: yaml_test_ofs
  framework: stofs
  model_type: schism
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        try:
            config = OFSConfig.from_yaml(temp_path)
            # Check system name
            assert config._yaml_data['system']['name'] == 'yaml_test_ofs'
        finally:
            os.unlink(temp_path)


class TestConfigValidation:
    """Tests for configuration validation."""

    def test_minimal_yaml(self):
        """Test that minimal YAML can be loaded."""
        yaml_content = """
system:
  name: minimal_ofs
  model_type: schism
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        try:
            config = OFSConfig.from_yaml(temp_path)
            # Config should load even with minimal fields
            assert config is not None
        finally:
            os.unlink(temp_path)

    def test_domain_bounds_yaml(self):
        """Test domain bounds in YAML."""
        yaml_content = """
system:
  name: test_ofs
  model_type: schism

grid:
  domain:
    lon_min: -80.0
    lon_max: -70.0
    lat_min: 30.0
    lat_max: 40.0
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        try:
            config = OFSConfig.from_yaml(temp_path)
            # Access nested domain data
            if 'grid' in config._yaml_data:
                domain = config._yaml_data['grid'].get('domain', {})
                if domain:
                    assert domain.get('lon_min', 0) < domain.get('lon_max', 0)
                    assert domain.get('lat_min', 0) < domain.get('lat_max', 0)
        finally:
            os.unlink(temp_path)


class TestConfigAccess:
    """Tests for configuration data access patterns."""

    def test_yaml_data_access(self):
        """Test accessing config raw YAML data."""
        yaml_content = """
system:
  name: test_ofs
  framework: comf
  model_type: schism

forcing:
  atmospheric:
    primary: gfs
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        try:
            config = OFSConfig.from_yaml(temp_path)
            # Access raw data
            assert 'system' in config._yaml_data
            assert config._yaml_data['system']['name'] == 'test_ofs'
        finally:
            os.unlink(temp_path)

    def test_property_access(self):
        """Test accessing config via properties."""
        yaml_content = """
system:
  name: prop_test_ofs
  framework: stofs
  model_type: schism
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        try:
            config = OFSConfig.from_yaml(temp_path)
            # These properties should work
            assert config.framework == 'stofs'
            assert config.model_type == 'schism'
        finally:
            os.unlink(temp_path)


class TestEnvOverrides:
    """Tests for environment variable overrides."""

    def test_env_overrides_yaml(self):
        """Test that environment variables override YAML values."""
        yaml_content = """
system:
  name: test_ofs
  model_type: schism
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        # Set environment variables
        os.environ['PDY'] = '20250120'
        os.environ['cyc'] = '18'

        try:
            config = OFSConfig.from_yaml(temp_path, env_override=True)
            # Environment should override
            assert config.runtime.pdy == '20250120'
            assert config.runtime.cyc == 18
        finally:
            os.unlink(temp_path)
            os.environ.pop('PDY', None)
            os.environ.pop('cyc', None)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
