"""
Unit tests for NOS OFS CLI module.

Tests command-line interface functionality.
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Add package to path for testing
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestCLIList:
    """Tests for CLI list command."""

    def test_list_command(self):
        """Test the list command output."""
        from nos_ofs import cli

        # Mock args
        class MockArgs:
            pass

        result = cli.cmd_list(MockArgs())
        assert result == 0

    def test_list_includes_systems(self, capsys):
        """Test that list shows expected OFS systems."""
        from nos_ofs import cli

        class MockArgs:
            pass

        cli.cmd_list(MockArgs())
        captured = capsys.readouterr()

        # Should list known systems
        assert 'stofs_3d_atl' in captured.out or 'Available' in captured.out


class TestCLIExportEnv:
    """Tests for CLI export-env command."""

    def test_export_env_with_config(self):
        """Test export-env with a config file."""
        from nos_ofs import cli

        yaml_content = """
system:
  name: test_ofs
  framework: comf

grid:
  n_nodes: 1000
  domain:
    lon_min: -80.0
    lon_max: -70.0
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        try:
            class MockArgs:
                config = temp_path
                framework = 'comf'

            result = cli.cmd_export_env(MockArgs())
            assert result == 0
        finally:
            os.unlink(temp_path)

    def test_export_env_missing_config(self):
        """Test export-env with missing config file."""
        from nos_ofs import cli

        class MockArgs:
            config = '/nonexistent/path/config.yaml'
            framework = 'auto'

        # Clear OFS_CONFIG if set
        old_config = os.environ.pop('OFS_CONFIG', None)

        try:
            result = cli.cmd_export_env(MockArgs())
            # Should return error code when config not found
            assert result == 1
        finally:
            if old_config:
                os.environ['OFS_CONFIG'] = old_config


class TestCLIPrep:
    """Tests for CLI prep command."""

    def test_prep_missing_config(self):
        """Test prep command with missing configuration."""
        from nos_ofs import cli

        class MockArgs:
            config = '/nonexistent/config.yaml'
            step = None

        # Clear environment
        old_config = os.environ.pop('OFS_CONFIG', None)

        try:
            result = cli.cmd_prep(MockArgs())
            assert result == 1
        except ModuleNotFoundError as e:
            # Skip if forcing modules not available
            pytest.skip(f"Module not available: {e}")
        finally:
            if old_config:
                os.environ['OFS_CONFIG'] = old_config


class TestCLIForcing:
    """Tests for CLI forcing command."""

    def test_forcing_unknown_type(self):
        """Test forcing command with unknown forcing type."""
        from nos_ofs import cli

        yaml_content = """
system:
  name: test_ofs
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        try:
            class MockArgs:
                config = temp_path
                type = 'unknown_forcing'

            result = cli.cmd_forcing(MockArgs())
            # Should fail with unknown forcing type
            assert result == 1
        except ModuleNotFoundError as e:
            # Skip if forcing modules not available
            pytest.skip(f"Module not available: {e}")
        finally:
            os.unlink(temp_path)


class TestCLIMain:
    """Tests for CLI main entry point."""

    def test_main_no_args(self):
        """Test main with no arguments."""
        from nos_ofs import cli

        # Mock sys.argv
        with patch.object(sys, 'argv', ['nos_ofs.cli']):
            result = cli.main()
            # Should return 0 (print help)
            assert result == 0

    def test_main_list(self):
        """Test main with list command."""
        from nos_ofs import cli

        with patch.object(sys, 'argv', ['nos_ofs.cli', 'list']):
            result = cli.main()
            assert result == 0


class TestGetConfigPath:
    """Tests for config path resolution."""

    def test_config_from_environment(self):
        """Test getting config path from OFS_CONFIG env var."""
        from nos_ofs import cli

        # Create temp config
        yaml_content = "system:\n  name: test\n"
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        try:
            os.environ['OFS_CONFIG'] = temp_path
            config_path = cli.get_config_path()
            assert config_path is not None
            assert str(config_path) == temp_path
        finally:
            del os.environ['OFS_CONFIG']
            os.unlink(temp_path)

    def test_config_not_found(self):
        """Test when no config can be found."""
        from nos_ofs import cli

        # Clear relevant env vars
        old_config = os.environ.pop('OFS_CONFIG', None)
        old_ofs = os.environ.pop('OFS', None)

        try:
            config_path = cli.get_config_path()
            assert config_path is None
        finally:
            if old_config:
                os.environ['OFS_CONFIG'] = old_config
            if old_ofs:
                os.environ['OFS'] = old_ofs


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
