"""
Pytest configuration and fixtures for NOS OFS tests.
"""

import os
import sys
from pathlib import Path

import pytest

# Add package to path
package_root = Path(__file__).parent.parent
sys.path.insert(0, str(package_root))


@pytest.fixture
def package_root():
    """Return the package root directory."""
    return Path(__file__).parent.parent


@pytest.fixture
def parm_dir():
    """Return the parm directory with YAML configs."""
    # Navigate from ush/python/tests to nos_ofs/parm/
    return Path(__file__).parent.parent.parent.parent / 'parm'


@pytest.fixture
def base_configs(parm_dir):
    """Return paths to base model configs."""
    base_dir = parm_dir / 'base'
    return {
        'schism': base_dir / 'schism.yaml',
        'fvcom': base_dir / 'fvcom.yaml',
        'roms': base_dir / 'roms.yaml',
    }


@pytest.fixture
def system_configs(parm_dir):
    """Return paths to system configs."""
    systems_dir = parm_dir / 'systems'
    configs = {}
    if systems_dir.exists():
        for yaml_file in systems_dir.glob('*.yaml'):
            configs[yaml_file.stem] = yaml_file
    return configs


@pytest.fixture
def temp_yaml_config(tmp_path):
    """Create a temporary YAML config file."""
    def _create_config(content: str, name: str = 'test_config.yaml'):
        config_path = tmp_path / name
        config_path.write_text(content)
        return config_path
    return _create_config


@pytest.fixture(autouse=True)
def clean_env():
    """Clean environment variables before and after each test."""
    # Save original environment
    original_env = {
        'OFS_CONFIG': os.environ.get('OFS_CONFIG'),
        'OFS': os.environ.get('OFS'),
        'PDY': os.environ.get('PDY'),
        'cyc': os.environ.get('cyc'),
    }

    yield

    # Restore original environment
    for key, value in original_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
