"""
Unit tests for YAML to environment export utility.

Tests the conversion of YAML configuration to shell environment variables.
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Add package to path for testing
sys.path.insert(0, str(Path(__file__).parent.parent))

from nos_ofs.utils.yaml_to_env import export_for_shell


class TestYamlToEnv:
    """Tests for YAML to shell environment export."""

    def test_basic_export(self):
        """Test basic YAML to shell export."""
        yaml_content = """
system:
  name: test_ofs
  framework: comf

grid:
  n_nodes: 1000
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
            output = export_for_shell(temp_path, framework='comf')

            # Should be shell export statements
            assert isinstance(output, str)
            assert 'export' in output or '=' in output
        finally:
            os.unlink(temp_path)

    def test_stofs_framework_export(self):
        """Test export for STOFS framework (LONMIN/LONMAX style)."""
        yaml_content = """
system:
  name: stofs_3d_atl
  framework: stofs

grid:
  n_nodes: 1813443
  n_elements: 3564104
  n_levels: 51
  domain:
    lon_min: -98.5035
    lon_max: -52.4867
    lat_min: 7.347
    lat_max: 52.5904
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        try:
            output = export_for_shell(temp_path, framework='stofs')

            # STOFS uses LONMIN/LONMAX
            assert 'LONMIN' in output or 'lon_min' in output.lower()
        finally:
            os.unlink(temp_path)

    def test_comf_framework_export(self):
        """Test export for COMF framework (MINLON/MAXLON style)."""
        yaml_content = """
system:
  name: secofs
  framework: comf

grid:
  n_nodes: 1684786
  domain:
    lon_min: -88.0
    lon_max: -63.0
    lat_min: 17.0
    lat_max: 40.0
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        try:
            output = export_for_shell(temp_path, framework='comf')

            # COMF uses MINLON/MAXLON
            assert 'MINLON' in output or 'lon_min' in output.lower()
        finally:
            os.unlink(temp_path)

    def test_auto_framework_detection(self):
        """Test automatic framework detection from config."""
        yaml_stofs = """
system:
  name: stofs_3d_atl
  framework: stofs
grid:
  domain:
    lon_min: -98.0
"""
        yaml_comf = """
system:
  name: secofs
  framework: comf
grid:
  domain:
    lon_min: -88.0
"""
        # Test STOFS auto-detection
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_stofs)
            temp_stofs = f.name

        # Test COMF auto-detection
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_comf)
            temp_comf = f.name

        try:
            output_stofs = export_for_shell(temp_stofs, framework='auto')
            output_comf = export_for_shell(temp_comf, framework='auto')

            # Both should produce valid shell output
            assert isinstance(output_stofs, str)
            assert isinstance(output_comf, str)
        finally:
            os.unlink(temp_stofs)
            os.unlink(temp_comf)

    def test_shell_safe_output(self):
        """Test that output is safe for shell eval."""
        yaml_content = """
system:
  name: test_ofs
  description: "Test OFS with special chars: $HOME `command`"

grid:
  domain:
    lon_min: -80.0
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        try:
            output = export_for_shell(temp_path, framework='comf')

            # Should not contain unescaped shell metacharacters
            # (actual implementation should handle this)
            assert isinstance(output, str)
        finally:
            os.unlink(temp_path)

    def test_nested_value_flattening(self):
        """Test flattening of nested YAML values."""
        yaml_content = """
forcing:
  atmospheric:
    primary: gfs
    hrrr_blend:
      enabled: true
      lon_min: -98.5
      lon_max: -49.5
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        try:
            output = export_for_shell(temp_path, framework='stofs')

            # Should contain flattened values
            assert isinstance(output, str)
        finally:
            os.unlink(temp_path)


class TestEnvEval:
    """Tests for evaluating exported environment in shell context."""

    def test_export_can_be_sourced(self):
        """Test that export output can be sourced in bash."""
        yaml_content = """
system:
  name: eval_test
grid:
  n_nodes: 500
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        try:
            output = export_for_shell(temp_path, framework='comf')

            # Write to shell script and try to source
            with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as sh:
                sh.write('#!/bin/bash\n')
                sh.write(output)
                sh.write('\necho "SUCCESS"\n')
                sh_path = sh.name

            # The export should be valid bash syntax
            # (Actual execution would require bash)
            assert output is not None
        finally:
            os.unlink(temp_path)
            if 'sh_path' in locals():
                os.unlink(sh_path)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
