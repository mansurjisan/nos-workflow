"""
Pytest configuration and fixtures for NOS OFS tests.

Provides comprehensive fixtures for testing forcing processors,
models, orchestration, and configuration modules.
"""

import os
import sys
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

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


# =========================================================================
# Mock config fixtures for different frameworks
# =========================================================================


@pytest.fixture
def sample_stofs_config():
    """Create a mock OFSConfig for STOFS framework."""
    config = Mock()
    config.OFS_FRAMEWORK = "stofs"
    config.framework = "stofs"
    config.model_type = "schism"
    config.system_name = "stofs_3d_atl"
    config.RUN = "stofs_3d_atl"
    config.PDY = "20250504"
    config.cyc = 12
    config.cycle = "t12z"
    config.dt = 150.0
    config.nvrt = 51
    config.ihot = 2
    config.hotstart_enabled = True
    config.rnday = 5.0
    config.lon_min = -98.5035
    config.lon_max = -52.4867
    config.lat_min = 7.347
    config.lat_max = 52.5904
    config.num_rivers = 534
    config.output_variables_2d = ["elev", "prmsl", "wind"]
    config.output_variables_3d = ["temp", "salt", "hvel"]
    config.output_interval_2d = 3600
    config.output_interval_station = 360
    config.forecast_length = 96
    config.nowcast_length = 6

    config.USHnos = "/tmp/ush"
    config.FIXnos = "/tmp/fix"
    config.FIXofs = "/tmp/fix"
    config.EXECnos = "/tmp/exec"
    config.DATA = "/tmp/data"
    config.COMOUT = "/tmp/comout"
    config.COMOUTrerun = "/tmp/comout_rerun"
    config.USHstofs3d = "/tmp/ush/stofs"
    config.FIXstofs3d = "/tmp/fix/stofs"
    config.EXECstofs3d = "/tmp/exec"
    config.HOMEnos = "/tmp/home"
    config.COMINgfs = "/tmp/comin/gfs"
    config.COMINhrrr = "/tmp/comin/hrrr"
    config.COMINrtofs = "/tmp/comin/rtofs"
    config.COMINnwm = "/tmp/comin/nwm"
    config.COMINadt = "/tmp/comin/adt"
    config.gfs_enabled = True
    config.hrrr_enabled = True
    config.nwm_enabled = True
    config.rtofs_enabled = True
    config.tides_enabled = True
    config.grid_horizontal = "stofs_3d_atl_hgrid.gr3"

    config.get_fix_file = Mock(side_effect=lambda name: Path("/tmp/fix") / name)
    config.get_exec_file = Mock(side_effect=lambda name: Path("/tmp/exec") / name)

    # Runtime mock
    config.runtime = Mock()
    config.runtime.pdy = "20250504"
    config.runtime.cyc = 12
    config.runtime.ush_ofs = "/tmp/ush"
    config.runtime.fix_ofs = "/tmp/fix"
    config.runtime.exec_ofs = "/tmp/exec"
    config.runtime.data = "/tmp/data"
    config.runtime.comout = "/tmp/comout"

    return config


@pytest.fixture
def sample_comf_config():
    """Create a mock OFSConfig for COMF framework."""
    config = Mock()
    config.OFS_FRAMEWORK = "comf"
    config.framework = "comf"
    config.model_type = "roms"
    config.system_name = "cbofs"
    config.RUN = "cbofs"
    config.PDY = "20250504"
    config.cyc = 0
    config.cycle = "t00z"
    config.dt = 6.0
    config.nvrt = 20
    config.ihot = 1
    config.hotstart_enabled = True
    config.lon_min = -77.5
    config.lon_max = -75.0
    config.lat_min = 36.5
    config.lat_max = 39.5
    config.num_rivers = 150

    config.USHnos = "/tmp/ush"
    config.FIXnos = "/tmp/fix"
    config.FIXofs = "/tmp/fix"
    config.EXECnos = "/tmp/exec"
    config.DATA = "/tmp/data"
    config.COMOUT = "/tmp/comout"

    config.get_fix_file = Mock(side_effect=lambda name: Path("/tmp/fix") / name)
    config.get_exec_file = Mock(side_effect=lambda name: Path("/tmp/exec") / name)

    # Runtime mock
    config.runtime = Mock()
    config.runtime.pdy = "20250504"
    config.runtime.cyc = 0
    config.runtime.ush_ofs = "/tmp/ush"
    config.runtime.fix_ofs = "/tmp/fix"
    config.runtime.exec_ofs = "/tmp/exec"
    config.runtime.data = "/tmp/data"
    config.runtime.comout = "/tmp/comout"

    return config


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Create a temporary DATA directory with standard subdirectories."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "sflux").mkdir()
    (data_dir / "outputs").mkdir()
    (data_dir / "rtofs_work").mkdir()
    return data_dir


@pytest.fixture
def mock_gfs_grib2(tmp_path):
    """Create mock GFS GRIB2 file structure."""
    gfs_dir = tmp_path / "gfs.20250504" / "12" / "atmos"
    gfs_dir.mkdir(parents=True)

    # Create mock GRIB2 files
    for fhr in range(0, 25, 3):
        fname = gfs_dir / f"gfs.t12z.pgrb2.0p25.f{fhr:03d}"
        fname.write_bytes(b"\x00" * 1024)

    return gfs_dir.parent.parent.parent  # Return the base directory


@pytest.fixture
def mock_rtofs_nc(tmp_path):
    """Create mock RTOFS NetCDF file structure."""
    rtofs_dir = tmp_path / "rtofs.20250504"
    rtofs_dir.mkdir(parents=True)

    # Create mock 2D files (need minimum size to pass validation)
    for prefix in ["n012", "n018", "f000", "f006", "f012", "f018",
                    "f024", "f030", "f036", "f042", "f048"]:
        fname = rtofs_dir / f"rtofs_glo_2ds_{prefix}_diag.nc"
        fname.write_bytes(b"\x00" * 200_000_000)  # Min size for 2D

    # Create mock 3D files
    for prefix in ["n012", "n018", "n024", "f006", "f012", "f018",
                    "f024", "f030", "f036", "f042", "f048"]:
        fname = rtofs_dir / f"rtofs_glo_3dz_{prefix}_6hrly_hvr_US_east.nc"
        fname.write_bytes(b"\x00" * 250_000_000)

    return rtofs_dir.parent


@pytest.fixture
def mock_nwm_nc(tmp_path):
    """Create mock NWM NetCDF file structure."""
    nwm_dir = tmp_path / "nwm"
    nwm_dir.mkdir(parents=True)

    for fhr in range(0, 25):
        fname = nwm_dir / f"nwm.t12z.medium_range.channel_rt.f{fhr:03d}.conus.nc"
        fname.write_bytes(b"\x00" * 1024)

    return nwm_dir


@pytest.fixture
def mock_hrrr_grib2(tmp_path):
    """Create mock HRRR GRIB2 file structure."""
    today_dir = tmp_path / "hrrr.20250504" / "conus"
    today_dir.mkdir(parents=True)

    for fhr in range(1, 25):
        fname = today_dir / f"hrrr.t12z.wrfsfcf{fhr:02d}.grib2"
        fname.write_bytes(b"\x00" * 1024)

    return tmp_path
