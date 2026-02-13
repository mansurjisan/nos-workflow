"""
ADCIRC Forcing Processors

Provides ADCIRC-specific atmospheric forcing conversion from GFS GRIB2
to the OWI (Oceanweather Inc.) NetCDF format used by ADCIRC.

ADCIRC uses OWI-format forcing files when NWS=12:
- fort.221.nc: Atmospheric pressure (Pa) on a regular lat/lon grid
- fort.222.nc: Wind u-component (m/s) on a regular lat/lon grid
- fort.225.nc: Wind v-component (m/s) on a regular lat/lon grid

The OWI format stores meteorological fields on a regular rectangular
grid that ADCIRC interpolates to its unstructured mesh nodes at runtime.

This module also provides a tidal nodal factor processor that wraps
the tide_fac Fortran executable used by STOFS-2D-Global.
"""

import logging
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..base_forcing import (
    BaseForcingProcessor,
    AtmosphericProcessor,
    ForcingResult,
)

log = logging.getLogger(__name__)


class ADCIRCGFSForcing(AtmosphericProcessor):
    """
    Convert GFS GRIB2 data to ADCIRC OWI NetCDF format.

    The OWI format requires three separate NetCDF files on a regular
    lat/lon grid covering the model domain:
    - fort.221.nc: Sea-level pressure (Pa)
    - fort.222.nc: Eastward wind component at 10m (m/s)
    - fort.225.nc: Northward wind component at 10m (m/s)

    Each file contains a time dimension and 2D lat/lon fields.
    The temporal resolution matches GFS output (typically 1-hour for
    the first 120 hours, then 3-hour out to 384 hours).

    In the operational workflow, this conversion is handled by shell
    scripts using wgrib2 for GRIB2 extraction and NCO tools (ncks,
    ncap2, ncrcat) for NetCDF manipulation. This processor provides
    the same functionality via Python when the shell scripts are not
    available, or delegates to the legacy scripts when they are.
    """

    source_name = "GFS"
    forcing_type = "atmospheric"

    # GFS variables needed for ADCIRC OWI forcing
    REQUIRED_VARIABLES = {
        'pressure': {'grib_name': 'PRMSL', 'level': 'mean sea level'},
        'wind_u': {'grib_name': 'UGRD', 'level': '10 m above ground'},
        'wind_v': {'grib_name': 'VGRD', 'level': '10 m above ground'},
    }

    # OWI output file names
    OWI_FILES = {
        'pressure': 'fort.221.nc',
        'wind_u': 'fort.222.nc',
        'wind_v': 'fort.225.nc',
    }

    def __init__(
        self,
        config: Any,
        input_path: Path = None,
        output_path: Path = None,
        grid: Any = None,
        enabled: bool = True,
    ):
        """
        Initialize ADCIRC GFS forcing processor.

        Args:
            config: OFS configuration
            input_path: Path to GFS GRIB2 input files
            output_path: Path to write OWI NetCDF output
            grid: ADCIRC grid handler (optional, for domain bounds)
            enabled: Whether this processor is enabled
        """
        super().__init__(
            config=config,
            grid=grid,
            input_path=input_path,
            output_path=output_path,
            enabled=enabled,
        )

        # Extract domain bounds from config
        self._yaml_data = self._get_yaml_data()
        domain = self._yaml_data.get('grid', {}).get('domain', {})
        self.lon_min = domain.get('lon_min', -180.0)
        self.lon_max = domain.get('lon_max', 180.0)
        self.lat_min = domain.get('lat_min', -90.0)
        self.lat_max = domain.get('lat_max', 90.0)

        # GFS grid resolution
        atmos_cfg = self._yaml_data.get('forcing', {}).get('atmospheric', {})
        gfs_cfg = atmos_cfg.get('gfs', {})
        self.gfs_resolution = float(gfs_cfg.get('resolution', 0.25))

    def _get_yaml_data(self) -> Dict:
        """Extract YAML configuration data."""
        if hasattr(self.config, '_yaml_data'):
            return self.config._yaml_data
        if hasattr(self.config, 'system') and hasattr(self.config.system, '_raw'):
            return self.config.system._raw
        return {}

    def find_input_files(self) -> List[Path]:
        """
        Find GFS GRIB2 input files for the forecast cycle.

        GFS files follow the naming convention:
            gfs.tHHz.pgrb2.0p25.fFFF
        where HH is the cycle hour and FFF is the forecast hour.

        Returns:
            List of available GFS GRIB2 file paths
        """
        pdy = getattr(self.config, 'PDY', '')
        cyc = getattr(self.config, 'cyc', 0)

        if not self.input_path or not self.input_path.exists():
            log.warning(f"GFS input path does not exist: {self.input_path}")
            return []

        # Look for GFS files with various naming patterns
        patterns = [
            f"gfs.t{cyc:02d}z.pgrb2.0p25.f*",
            f"gfs.t{cyc:02d}z.pgrb2b.0p25.f*",
            f"atmos/gfs.t{cyc:02d}z.pgrb2.0p25.f*",
        ]

        files = []
        for pattern in patterns:
            found = sorted(self.input_path.glob(pattern))
            files.extend(found)

        if files:
            log.info(f"Found {len(files)} GFS GRIB2 files")
        else:
            log.warning(f"No GFS files found in {self.input_path}")

        return files

    def process(self) -> ForcingResult:
        """
        Process GFS GRIB2 data into ADCIRC OWI NetCDF format.

        This method first attempts to delegate to the legacy shell
        scripts. If those are not available, it uses wgrib2 and NCO
        tools via subprocess to perform the conversion.

        Returns:
            ForcingResult with output file paths
        """
        # Try legacy shell script execution first
        legacy_result = self._try_legacy_scripts()
        if legacy_result is not None:
            return legacy_result

        # Otherwise, use wgrib2/NCO-based processing
        return self._process_via_wgrib2()

    def _try_legacy_scripts(self) -> Optional[ForcingResult]:
        """
        Try to execute the legacy STOFS GFS forcing shell script.

        Returns:
            ForcingResult if script was found and executed, None otherwise
        """
        ush_dir = os.environ.get('USHstofs2d', '')
        if not ush_dir:
            return None

        script_path = Path(ush_dir) / "stofs_2d_glo_create_surface_forcing_gfs.sh"
        if not script_path.exists():
            return None

        log.info(f"Using legacy GFS forcing script: {script_path}")
        data_dir = os.environ.get('DATA', '/tmp')

        try:
            result = subprocess.run(
                str(script_path),
                shell=True,
                cwd=data_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=7200,  # 2 hours
            )

            if result.returncode == 0:
                output_files = []
                for fname in self.OWI_FILES.values():
                    fpath = Path(data_dir) / fname
                    if fpath.exists():
                        output_files.append(fpath)

                return ForcingResult(
                    success=True,
                    source="GFS (legacy shell)",
                    output_files=output_files,
                )
            else:
                return ForcingResult(
                    success=False,
                    source="GFS (legacy shell)",
                    errors=[result.stderr[:500] if result.stderr else "Script failed"],
                )
        except Exception as e:
            return ForcingResult(
                success=False,
                source="GFS (legacy shell)",
                errors=[str(e)],
            )

    def _process_via_wgrib2(self) -> ForcingResult:
        """
        Process GFS GRIB2 to OWI NetCDF using wgrib2 and NCO tools.

        This follows the same logic as the operational shell script:
        1. Extract PRMSL, UGRD:10m, VGRD:10m from GFS GRIB2
        2. Subset to model domain
        3. Convert to NetCDF
        4. Concatenate time steps into single files

        Returns:
            ForcingResult with output file paths
        """
        input_files = self.find_input_files()
        if not input_files:
            return ForcingResult(
                success=False,
                source="GFS",
                errors=["No GFS input files found"],
            )

        data_dir = Path(os.environ.get('DATA', '/tmp'))
        output_files = []

        try:
            # Check for required tools
            for tool in ['wgrib2', 'ncks']:
                result = subprocess.run(
                    f"which {tool}", shell=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
                if result.returncode != 0:
                    return ForcingResult(
                        success=False,
                        source="GFS",
                        errors=[f"Required tool '{tool}' not found in PATH"],
                    )

            # Process each variable
            for var_key, var_info in self.REQUIRED_VARIABLES.items():
                owi_name = self.OWI_FILES[var_key]
                output_file = data_dir / owi_name

                temp_files = []
                for grib_file in input_files:
                    # Extract variable from GRIB2
                    temp_nc = data_dir / f"tmp_{var_key}_{grib_file.stem}.nc"

                    # wgrib2 extraction and subsetting
                    match_str = var_info['grib_name']
                    level_str = var_info['level']
                    cmd = (
                        f"wgrib2 {grib_file} "
                        f"-match ':{match_str}:{level_str}:' "
                        f"-small_grib "
                        f"{self.lon_min}:{self.lon_max} "
                        f"{self.lat_min}:{self.lat_max} "
                        f"- | wgrib2 - -netcdf {temp_nc}"
                    )

                    result = subprocess.run(
                        cmd, shell=True, cwd=str(data_dir),
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=True, timeout=300,
                    )

                    if result.returncode == 0 and temp_nc.exists():
                        temp_files.append(temp_nc)

                if not temp_files:
                    log.warning(f"No data extracted for {var_key}")
                    continue

                # Concatenate time steps
                if len(temp_files) == 1:
                    temp_files[0].rename(output_file)
                else:
                    file_list = " ".join(str(f) for f in temp_files)
                    cmd = f"ncrcat -O {file_list} {output_file}"
                    result = subprocess.run(
                        cmd, shell=True, cwd=str(data_dir),
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=True, timeout=600,
                    )

                    if result.returncode != 0:
                        log.error(f"ncrcat failed for {var_key}: {result.stderr}")
                        continue

                    # Clean up temp files
                    for tf in temp_files:
                        if tf.exists():
                            tf.unlink()

                if output_file.exists():
                    output_files.append(output_file)
                    log.info(f"Created OWI file: {output_file}")

            if len(output_files) == len(self.OWI_FILES):
                return ForcingResult(
                    success=True,
                    source="GFS",
                    output_files=output_files,
                    metadata={'n_timesteps': len(input_files)},
                )
            else:
                return ForcingResult(
                    success=False,
                    source="GFS",
                    output_files=output_files,
                    errors=[
                        f"Only {len(output_files)}/{len(self.OWI_FILES)} "
                        f"OWI files created successfully"
                    ],
                )

        except Exception as e:
            return ForcingResult(
                success=False,
                source="GFS",
                errors=[str(e)],
            )


class ADCIRCTidalForcing(BaseForcingProcessor):
    """
    ADCIRC tidal forcing processor.

    Wraps the tide_fac Fortran executable that computes tidal nodal
    factors and equilibrium arguments for the specified constituents
    and simulation reference time. The results are used to update
    the fort.15 control file.

    In STOFS-2D-Global, tide_fac is called before each tidal run
    (TIDE_NOWCAST, TIDE_FORECAST1, TIDE_FORECAST2) to compute
    time-varying astronomical corrections.
    """

    source_name = "Tidal"
    forcing_type = "tidal"

    def __init__(
        self,
        config: Any,
        input_path: Path = None,
        output_path: Path = None,
        grid: Any = None,
        enabled: bool = True,
    ):
        """
        Initialize ADCIRC tidal forcing processor.

        Args:
            config: OFS configuration
            input_path: Path to tidal database files
            output_path: Working directory for tide_fac
            grid: ADCIRC grid handler (not used)
            enabled: Whether tidal forcing is enabled
        """
        super().__init__(
            config=config,
            grid=grid,
            input_path=input_path or Path("/tmp"),
            output_path=output_path or Path("/tmp"),
            enabled=enabled,
        )

    def find_input_files(self) -> List[Path]:
        """
        Find tidal input files (fort.15 template).

        For ADCIRC, tidal forcing is defined in fort.15 rather than
        separate input files. The tide_fac executable reads the
        simulation time and outputs nodal factors.

        Returns:
            List containing fort.15 path if it exists
        """
        data_dir = Path(os.environ.get('DATA', '/tmp'))
        fort15 = data_dir / "fort.15"
        if fort15.exists():
            return [fort15]
        return []

    def process(self) -> ForcingResult:
        """
        Run tide_fac to compute tidal nodal factors.

        Returns:
            ForcingResult with status
        """
        exec_dir = os.environ.get('EXECstofs2d', os.environ.get('EXECnos', ''))
        data_dir = Path(os.environ.get('DATA', '/tmp'))

        # Find the executable
        tide_fac = None
        for name in ['stofs_2d_glo_tide_fac', 'tide_fac']:
            candidate = Path(exec_dir) / name if exec_dir else Path(name)
            if candidate.exists():
                tide_fac = candidate
                break

        if tide_fac is None:
            return ForcingResult(
                success=False,
                source="Tidal",
                errors=["tide_fac executable not found"],
            )

        log.info(f"Running tide_fac: {tide_fac}")

        try:
            result = subprocess.run(
                str(tide_fac),
                shell=True,
                cwd=str(data_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=300,
            )

            if result.returncode == 0:
                return ForcingResult(
                    success=True,
                    source="Tidal (tide_fac)",
                )
            else:
                return ForcingResult(
                    success=False,
                    source="Tidal (tide_fac)",
                    errors=[result.stderr[:500] if result.stderr else "tide_fac failed"],
                )

        except Exception as e:
            return ForcingResult(
                success=False,
                source="Tidal (tide_fac)",
                errors=[str(e)],
            )
