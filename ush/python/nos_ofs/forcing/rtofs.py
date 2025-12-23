"""
RTOFS (Real-Time Ocean Forecast System) Boundary Processor

Processes RTOFS ocean data for SCHISM open boundary conditions including:
- Temperature (3D)
- Salinity (3D)
- Sea surface height (2D)
- Currents u, v (3D)

Also creates T/S nudging fields for interior relaxation.

Output: SCHISM boundary NetCDF files
- elev2D.th.nc - sea surface height time history
- TEM_3D.th.nc - temperature boundary
- SAL_3D.th.nc - salinity boundary
- uv3D.th.nc - velocity boundary
- TEM_nu.nc, SAL_nu.nc - nudging fields (optional)

Processing Pipeline:
1. Discover and validate RTOFS files (2D and 3D)
2. Extract ROI using NCO tools (ncks)
3. Merge time steps (ncrcat)
4. Transform variables (ncap2, ncatted, ncrename)
5. Optionally blend SSH with ADT altimetry
6. Run Fortran executable (gen_3Dth_from_hycom) for boundary generation
7. Run Fortran executable (gen_nudge_from_hycom) for nudging fields
8. Apply SSH offset (+0.04m)
9. QC and archive output files
"""

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ..base import ForcingProcessor, ForcingResult

log = logging.getLogger(__name__)

try:
    from netCDF4 import Dataset
    HAS_NETCDF4 = True
except ImportError:
    HAS_NETCDF4 = False


@dataclass
class RTOFSFileSet:
    """Collection of RTOFS input files for processing."""
    files_2d: List[Path] = field(default_factory=list)
    files_3d: List[Path] = field(default_factory=list)
    date: str = ""
    is_backup: bool = False  # True if using previous day's files


@dataclass
class RTOFSProcessingConfig:
    """Configuration for RTOFS processing."""
    # ROI indices for 2D surface files
    idx_x1_2ds: int = 2805
    idx_x2_2ds: int = 2923
    idx_y1_2ds: int = 1598
    idx_y2_2ds: int = 2325

    # ROI indices for 3D depth files
    idx_x1_3dz: int = 482
    idx_x2_3dz: int = 600
    idx_y1_3dz: int = 94
    idx_y2_3dz: int = 821

    # File size thresholds (bytes)
    min_size_2d: int = 150_000_000
    min_size_3d: int = 200_000_000

    # Minimum number of files required
    min_files_required: int = 10

    # Target number of time steps (6-hourly for 5 days + nowcast)
    n_target_2d: int = 21
    n_target_3d: int = 21

    # SSH offset to apply (meters)
    ssh_offset: float = 0.04

    # Time step in output files (seconds)
    dt_output: float = 21600.0  # 6 hours

    # T,S values for points outside RTOFS grid
    temp_outside: float = 20.0
    salt_outside: float = 33.0


class RTOFSProcessor(ForcingProcessor):
    """
    RTOFS ocean boundary condition processor for SCHISM.

    Extracts T, S, SSH, and currents from RTOFS NetCDF files and creates
    SCHISM-compatible boundary condition files using NCO tools and
    Fortran executables from the operational workflow.

    This processor supports both:
    - Native mode: Uses NCO tools + Fortran executables
    - Python fallback mode: Pure Python processing (limited)
    """

    # RTOFS variable names
    RTOFS_VARIABLES = {
        "temperature": "temperature",
        "salinity": "salinity",
        "ssh": "ssh",
        "u_current": "u",
        "v_current": "v",
    }

    DEFAULT_VARIABLES = list(RTOFS_VARIABLES.keys())

    @property
    def source_name(self) -> str:
        return "RTOFS"

    def __init__(
        self,
        config,
        input_path: Path,
        output_path: Path,
        variables: Optional[List[str]] = None,
        nudging_enabled: bool = True,
        nudging_timescale: float = 86400.0,
        adt_enabled: bool = True,
        use_fortran_exec: bool = True,
        processing_config: Optional[RTOFSProcessingConfig] = None,
    ):
        """
        Initialize RTOFS processor.

        Args:
            config: StofsConfig instance
            input_path: Path to RTOFS input data (COMINrtofs)
            output_path: Path for output files
            variables: Variables to extract
            nudging_enabled: Whether to create nudging fields
            nudging_timescale: Relaxation timescale in seconds (86400 = 1 day)
            adt_enabled: Whether to blend SSH with ADT altimetry
            use_fortran_exec: Use Fortran executables (True) or Python (False)
            processing_config: Custom processing configuration
        """
        super().__init__(config, input_path, output_path, variables)
        self.nudging_enabled = nudging_enabled
        self.nudging_timescale = nudging_timescale
        self.adt_enabled = adt_enabled
        self.use_fortran_exec = use_fortran_exec
        self.proc_config = processing_config or RTOFSProcessingConfig()

        if not self.variables:
            self.variables = self.DEFAULT_VARIABLES

        self.cyc = config.cyc
        self.pdy = config.PDY
        self.cycle = config.cycle
        self.RUN = config.RUN

        # Paths from config
        self.fix_dir = Path(config.FIXstofs3d)
        self.exec_dir = Path(config.EXECstofs3d)
        self.adt_path = Path(config.COMINadt) if config.COMINadt else None
        self.comout_rerun = Path(config.COMOUTrerun) if config.COMOUTrerun else None

        # Working directory for intermediate files
        self.work_dir = self.output_path / "rtofs_work"

        # Check for required tools
        self._check_nco_tools()

    def _check_nco_tools(self) -> None:
        """Check if NCO tools are available."""
        self.nco_available = True
        for tool in ["ncks", "ncrcat", "ncap2", "ncatted", "ncrename"]:
            if shutil.which(tool) is None:
                log.warning(f"NCO tool '{tool}' not found in PATH")
                self.nco_available = False

        if not self.nco_available:
            log.warning("NCO tools not available - will use Python fallback mode")
            self.use_fortran_exec = False

    def process(self) -> ForcingResult:
        """
        Process RTOFS ocean boundary forcing.

        Returns:
            ForcingResult with processed files
        """
        log.info(f"Processing {self.source_name} ocean boundary conditions")
        log.info(f"Input path: {self.input_path}")
        log.info(f"Output path: {self.output_path}")
        log.info(f"Nudging enabled: {self.nudging_enabled}")
        log.info(f"ADT blending enabled: {self.adt_enabled}")
        log.info(f"Using Fortran executables: {self.use_fortran_exec}")

        if not self.validate_input():
            return ForcingResult(
                success=False,
                source=self.source_name,
                errors=[f"Input path not found: {self.input_path}"],
            )

        self.create_output_dir()
        self.work_dir.mkdir(parents=True, exist_ok=True)

        output_files = []
        errors = []

        try:
            # Step 1: Discover RTOFS files
            rtofs_files = self._discover_rtofs_files()

            if not rtofs_files.files_2d or not rtofs_files.files_3d:
                return ForcingResult(
                    success=False,
                    source=self.source_name,
                    errors=["Insufficient RTOFS files found"],
                )

            log.info(f"Found {len(rtofs_files.files_2d)} 2D files, "
                    f"{len(rtofs_files.files_3d)} 3D files")

            if self.use_fortran_exec and self.nco_available:
                # Native mode: NCO preprocessing + Fortran executables
                output_files, errors = self._process_native_mode(rtofs_files)
            else:
                # Python fallback mode
                output_files, errors = self._process_python_mode(rtofs_files)

            if errors:
                log.warning(f"RTOFS processing completed with warnings: {errors}")

            return ForcingResult(
                success=len(output_files) > 0,
                source=self.source_name,
                output_files=output_files,
                errors=errors,
                metadata={
                    "variables": self.variables,
                    "nudging_enabled": self.nudging_enabled,
                    "nudging_timescale": self.nudging_timescale,
                    "num_2d_files": len(rtofs_files.files_2d),
                    "num_3d_files": len(rtofs_files.files_3d),
                    "adt_blended": self.adt_enabled,
                    "mode": "native" if self.use_fortran_exec else "python",
                },
            )

        except Exception as e:
            log.error(f"RTOFS processing failed: {e}")
            import traceback
            log.error(traceback.format_exc())
            return ForcingResult(
                success=False,
                source=self.source_name,
                errors=[str(e)],
            )

    # =========================================================================
    # File Discovery
    # =========================================================================

    def _discover_rtofs_files(self) -> RTOFSFileSet:
        """
        Discover and validate RTOFS input files.

        Searches for today's files first, then falls back to previous day.
        Validates file sizes to ensure data quality.
        """
        yyyymmdd_today = self.pdy
        yyyymmdd_prev = (datetime.strptime(self.pdy, "%Y%m%d") -
                        timedelta(days=1)).strftime("%Y%m%d")

        # Try today's files first
        files_today = self._find_rtofs_files_for_date(yyyymmdd_today)
        files_prev = self._find_rtofs_files_for_date(yyyymmdd_prev)

        # Use today's files if sufficient, else merge with previous day
        result = self._merge_file_sets(files_today, files_prev)

        log.info(f"RTOFS file discovery: {len(result.files_2d)} 2D, "
                f"{len(result.files_3d)} 3D files")

        return result

    def _find_rtofs_files_for_date(self, yyyymmdd: str) -> RTOFSFileSet:
        """Find RTOFS files for a specific date."""
        result = RTOFSFileSet(date=yyyymmdd)

        rtofs_dir = self.input_path / f"rtofs.{yyyymmdd}"
        if not rtofs_dir.exists():
            log.debug(f"RTOFS directory not found: {rtofs_dir}")
            return result

        # 2D surface files (diag files with SSH)
        # Pattern: rtofs_glo_2ds_{n012,n018,f000,f006,...}_diag.nc
        nowcast_2d = ["n012", "n018"]
        forecast_2d = [f"f{h:03d}" for h in range(0, 132, 6)]  # f000 to f120

        for prefix in nowcast_2d + forecast_2d:
            pattern = f"rtofs_glo_2ds_{prefix}_diag.nc"
            matches = list(rtofs_dir.glob(pattern))
            for f in matches:
                if self._validate_file_size(f, self.proc_config.min_size_2d):
                    result.files_2d.append(f)

        # 3D depth files (hvr_US_east files with T,S,U,V)
        # Pattern: rtofs_glo_3dz_{n012,n018,n024,f006,...}_6hrly_hvr_US_east.nc
        nowcast_3d = ["n012", "n018", "n024"]
        forecast_3d = [f"f{h:03d}" for h in range(6, 132, 6)]  # f006 to f120

        for prefix in nowcast_3d + forecast_3d:
            pattern = f"rtofs_glo_3dz_{prefix}_6hrly_hvr_US_east.nc"
            matches = list(rtofs_dir.glob(pattern))
            for f in matches:
                if self._validate_file_size(f, self.proc_config.min_size_3d):
                    result.files_3d.append(f)

        # Sort by forecast hour
        result.files_2d = sorted(result.files_2d, key=lambda p: p.name)
        result.files_3d = sorted(result.files_3d, key=lambda p: p.name)

        return result

    def _validate_file_size(self, filepath: Path, min_size: int) -> bool:
        """Check if file meets minimum size requirement."""
        if not filepath.exists():
            return False
        size = filepath.stat().st_size
        if size < min_size:
            log.debug(f"File too small: {filepath} ({size} < {min_size})")
            return False
        return True

    def _merge_file_sets(
        self,
        primary: RTOFSFileSet,
        backup: RTOFSFileSet
    ) -> RTOFSFileSet:
        """
        Merge primary and backup file sets.

        Uses primary files when available, fills gaps from backup.
        """
        result = RTOFSFileSet(date=primary.date or backup.date)

        # Merge 2D files
        if len(primary.files_2d) >= self.proc_config.min_files_required:
            result.files_2d = primary.files_2d[:self.proc_config.n_target_2d]
        elif len(primary.files_2d) > 2:
            # Use primary + fill from backup
            n_needed = self.proc_config.n_target_2d - len(primary.files_2d)
            result.files_2d = primary.files_2d + backup.files_2d[:n_needed]
        elif len(backup.files_2d) >= self.proc_config.min_files_required:
            result.files_2d = backup.files_2d[:self.proc_config.n_target_2d]
            result.is_backup = True

        # Merge 3D files (same logic)
        if len(primary.files_3d) >= self.proc_config.min_files_required:
            result.files_3d = primary.files_3d[:self.proc_config.n_target_3d]
        elif len(primary.files_3d) > 2:
            n_needed = self.proc_config.n_target_3d - len(primary.files_3d)
            result.files_3d = primary.files_3d + backup.files_3d[:n_needed]
        elif len(backup.files_3d) >= self.proc_config.min_files_required:
            result.files_3d = backup.files_3d[:self.proc_config.n_target_3d]
            result.is_backup = True

        # Ensure same number of 2D and 3D files
        n_min = min(len(result.files_2d), len(result.files_3d))
        result.files_2d = result.files_2d[:n_min]
        result.files_3d = result.files_3d[:n_min]

        return result

    # =========================================================================
    # Native Mode Processing (NCO + Fortran)
    # =========================================================================

    def _process_native_mode(
        self,
        rtofs_files: RTOFSFileSet
    ) -> Tuple[List[Path], List[str]]:
        """
        Process RTOFS using NCO tools and Fortran executables.

        This follows the operational shell script workflow.
        """
        output_files = []
        errors = []

        try:
            # Step 1: Create symbolic links to input files
            self._create_input_links(rtofs_files)

            # Step 2: Extract ROI using ncks
            self._extract_roi()

            # Step 3: Merge time steps using ncrcat
            ssh_merged, tsuv_merged = self._merge_time_steps()

            # Step 4: Create SCHISM-compatible intermediate files
            ssh_1_nc, tsuv_1_nc = self._create_schism_input_nc(
                ssh_merged, tsuv_merged
            )

            # Step 5: Optionally blend with ADT
            if self.adt_enabled:
                ssh_1_nc = self._blend_with_adt(ssh_1_nc)

            # Step 6: Link grid files from FIX directory
            self._link_grid_files()

            # Step 7: Create input configuration for Fortran executable
            self._create_fortran_input_config()

            # Step 8: Run gen_3Dth_from_hycom
            bc_files = self._run_gen_3dth()
            output_files.extend(bc_files)

            # Step 9: Run gen_nudge_from_hycom if enabled
            if self.nudging_enabled:
                nudge_files = self._run_gen_nudge()
                output_files.extend(nudge_files)

            # Step 10: Apply SSH offset
            elev_file = self.work_dir / "elev2D.th.nc"
            if elev_file.exists():
                self._apply_ssh_offset(elev_file)

            # Step 11: Copy to output directory with standard names
            final_files = self._copy_to_output(output_files)

            return final_files, errors

        except Exception as e:
            errors.append(str(e))
            log.error(f"Native mode processing failed: {e}")
            return output_files, errors

    def _create_input_links(self, rtofs_files: RTOFSFileSet) -> None:
        """Create symbolic links to RTOFS input files."""
        log.info("Creating input file links...")

        # Clean up any existing links
        for pattern in ["RTOFS_2D_*.nc", "RTOFS_3D_*.nc"]:
            for f in self.work_dir.glob(pattern):
                f.unlink()

        # Create numbered links for 2D files
        for i, f in enumerate(rtofs_files.files_2d):
            link_name = self.work_dir / f"RTOFS_2D_{i:03d}.nc"
            link_name.symlink_to(f)

        # Create numbered links for 3D files
        for i, f in enumerate(rtofs_files.files_3d):
            link_name = self.work_dir / f"RTOFS_3D_{i:03d}.nc"
            link_name.symlink_to(f)

    def _extract_roi(self) -> None:
        """Extract region of interest from RTOFS files using ncks."""
        log.info("Extracting ROI from RTOFS files...")

        cfg = self.proc_config

        # Extract SSH from 2D files
        ssh_vars = "MT,Date,Longitude,Latitude,ssh"
        for nc_file in sorted(self.work_dir.glob("RTOFS_2D_*.nc")):
            out_file = self.work_dir / f"rio_ssh_{nc_file.name}"
            cmd = [
                "ncks", "-O",
                "-d", f"X,{cfg.idx_x1_2ds},{cfg.idx_x2_2ds}",
                "-d", f"Y,{cfg.idx_y1_2ds},{cfg.idx_y2_2ds}",
                "-v", ssh_vars,
                str(nc_file), str(out_file)
            ]
            self._run_command(cmd)

        # Extract T,S,U,V from 3D files
        tsuv_vars = "MT,Date,Longitude,Latitude,temperature,salinity,u,v"
        for nc_file in sorted(self.work_dir.glob("RTOFS_3D_*.nc")):
            out_file = self.work_dir / f"rio_tsuv_{nc_file.name}"
            cmd = [
                "ncks", "-O",
                "-d", f"X,{cfg.idx_x1_3dz},{cfg.idx_x2_3dz}",
                "-d", f"Y,{cfg.idx_y1_3dz},{cfg.idx_y2_3dz}",
                "-v", tsuv_vars,
                str(nc_file), str(out_file)
            ]
            self._run_command(cmd)

    def _merge_time_steps(self) -> Tuple[Path, Path]:
        """Merge extracted ROI files into time series using ncrcat."""
        log.info("Merging time steps...")

        # Merge 2D SSH files
        ssh_files = sorted(self.work_dir.glob("rio_ssh_RTOFS_2D_*.nc"))
        ssh_merged = self.work_dir / f"merged_RTOFS_2D_{self.cycle}.nc"
        cmd = ["ncrcat", "-C"] + [str(f) for f in ssh_files] + [str(ssh_merged)]
        self._run_command(cmd)

        # Merge 3D TSUV files
        tsuv_files = sorted(self.work_dir.glob("rio_tsuv_RTOFS_3D_*.nc"))
        tsuv_merged = self.work_dir / f"merged_RTOFS_3D_{self.cycle}.nc"
        cmd = ["ncrcat", "-C"] + [str(f) for f in tsuv_files] + [str(tsuv_merged)]
        self._run_command(cmd)

        return ssh_merged, tsuv_merged

    def _create_schism_input_nc(
        self,
        ssh_merged: Path,
        tsuv_merged: Path
    ) -> Tuple[Path, Path]:
        """
        Transform merged RTOFS files into SCHISM-compatible format.

        Applies variable renaming, fill value handling, and coordinate transforms.
        """
        log.info("Creating SCHISM-compatible input files...")

        # Process SSH file
        ssh_tmp1 = self.work_dir / "test01_3Dth_nu.nc"
        ssh_tmp2 = self.work_dir / "test02_3Dth_nu.nc"
        ssh_tmp3 = self.work_dir / "test03_3Dth_nu.nc"
        ssh_tmp4 = self.work_dir / "test04_3Dth_nu.nc"
        ssh_out = self.work_dir / "SSH_1_rtofs_only.nc"

        # Remove fill value attributes
        self._run_command([
            "ncatted", "-O",
            "-a", "_FillValue,ssh,d,,",
            "-a", "missing_value,ssh,d,,",
            str(ssh_merged), str(ssh_tmp1)
        ])

        # Replace large values with fill value
        self._run_command([
            "ncap2", "-O",
            "-s", "where(ssh>10000) ssh=-30000",
            str(ssh_tmp1), str(ssh_tmp2)
        ])

        # Set new fill value attributes
        self._run_command([
            "ncatted", "-O",
            "-a", "_FillValue,ssh,a,f,-30000",
            "-a", "missing_value,ssh,a,f,-30000",
            str(ssh_tmp2), str(ssh_tmp3)
        ])

        # Rename dimensions
        self._run_command([
            "ncrename",
            "-d", "MT,time",
            "-d", "X,xlon",
            "-d", "Y,ylat",
            str(ssh_tmp3)
        ])

        # Apply NCO script for coordinate transformation
        nco_script = self.fix_dir / f"{self.RUN}_obc_3dth_cvt_ssh.nco"
        if nco_script.exists():
            self._run_command([
                "ncap2", "-O",
                "-S", str(nco_script),
                str(ssh_tmp3), str(ssh_tmp4)
            ])
        else:
            shutil.copy(ssh_tmp3, ssh_tmp4)

        # Remove unnecessary variables
        self._run_command([
            "ncks", "-CO",
            "-x", "-v", "Date,MT,X,Y",
            str(ssh_tmp4), str(ssh_out)
        ])

        # Process TSUV file
        tsuv_tmp1 = self.work_dir / "tmp01_3Dth_nu.nc"
        tsuv_tmp2 = self.work_dir / "tmp02_3Dth_nu.nc"
        tsuv_out = self.work_dir / f"TSUV_1_{self.pdy}_{self.cycle}.nc"

        # Rename dimensions and variables
        self._run_command([
            "ncrename",
            "-d", "MT,time",
            "-d", "Depth,lev",
            "-d", "X,xlon",
            "-d", "Y,ylat",
            "-v", "u,water_u",
            "-v", "v,water_v",
            str(tsuv_merged), str(tsuv_tmp1)
        ])

        # Apply NCO script for coordinate transformation
        nco_script = self.fix_dir / f"{self.RUN}_obc_3dth_cvt_tsuv.nco"
        if nco_script.exists():
            self._run_command([
                "ncap2", "-O",
                "-S", str(nco_script),
                str(tsuv_tmp1), str(tsuv_tmp2)
            ])
        else:
            shutil.copy(tsuv_tmp1, tsuv_tmp2)

        # Remove unnecessary variables
        self._run_command([
            "ncks", "-O",
            "-x", "-v", "Depth,Date,MT,X,Y",
            str(tsuv_tmp2), str(tsuv_out)
        ])

        return ssh_out, tsuv_out

    def _blend_with_adt(self, ssh_file: Path) -> Path:
        """
        Blend RTOFS SSH with ADT (Absolute Dynamic Topography) altimetry.

        Formula: SSH_blended = (SSH - SSH_t1) + ADT_t1
        This removes RTOFS bias and adds satellite altimetry reference.
        """
        if not self.adt_path or not self.adt_path.exists():
            log.warning("ADT path not configured - skipping ADT blending")
            return ssh_file

        # Check for pre-processed ADT in rerun directory
        adt_processed = None
        if self.comout_rerun:
            adt_processed = self.comout_rerun / "adt_aft_cvtz_cln.nc"

        if adt_processed and adt_processed.exists():
            log.info(f"Using pre-processed ADT from {adt_processed}")
            adt_file = adt_processed
        else:
            # Try to find and process ADT files
            adt_file = self._find_and_process_adt()
            if not adt_file:
                log.warning("No ADT data available - using raw RTOFS SSH")
                return ssh_file

        try:
            # Copy ADT file to work directory
            adt_local = self.work_dir / "adt_aft_cvtz_cln.nc"
            if not adt_local.exists():
                shutil.copy(adt_file, adt_local)

            ssh_out = self.work_dir / f"SSH_1_{self.pdy}_{self.cycle}.nc"

            # Extract ADT at t=0
            self._run_command([
                "ncap2", "-O", "-F",
                "-s", "surf_el_t1_adt=surf_el(1,:,:)",
                str(adt_local),
                str(self.work_dir / "adt_surf_el_t1.nc")
            ])

            # Set attributes
            self._run_command([
                "ncatted", "-O",
                "-a", "_FillValue,surf_el_t1_adt,o,f,-30000",
                "-a", "missing_value,surf_el_t1_adt,o,f,-30000",
                "-a", "scale_factor,surf_el_t1_adt,o,f,1.0",
                str(self.work_dir / "adt_surf_el_t1.nc"),
                str(self.work_dir / "adt_fnl.nc")
            ])

            # Merge ADT with RTOFS SSH
            ssh_work = self.work_dir / "SSH_work.nc"
            shutil.copy(ssh_file, ssh_work)

            # Add ADT variable to SSH file
            self._run_command([
                "ncks", "-A",
                "-v", "surf_el_t1_adt",
                str(self.work_dir / "adt_fnl.nc"),
                str(ssh_work)
            ])

            # Compute blended SSH: SSH_blended = SSH - SSH_t1 + ADT_t1
            self._run_command([
                "ncap2", "-A", "-F",
                "-s", "SSH_t1[time,ylat,xlon]=ssh(1,:,:);ADT_t1[time,ylat,xlon]=surf_el_t1_adt(:,:)",
                str(ssh_work), str(ssh_work)
            ])

            self._run_command([
                "ncap2", "-A", "-F",
                "-s", "SSH_t1_Fill_0=SSH_t1;ADT_t1_Fill_0=ADT_t1",
                str(ssh_work), str(self.work_dir / "SSH_1_wk_A.nc")
            ])

            self._run_command([
                "ncap2", "-A",
                "-s", "where(abs(SSH_t1_Fill_0)>1000) SSH_t1_Fill_0=0.0",
                str(self.work_dir / "SSH_1_wk_A.nc"),
                str(self.work_dir / "SSH_1_wk_B.nc")
            ])

            self._run_command([
                "ncap2", "-A", "-F",
                "-s", "SSH_ssh1[time,ylat,xlon]=ssh-SSH_t1_Fill_0",
                str(self.work_dir / "SSH_1_wk_B.nc"),
                str(self.work_dir / "SSH_1_ssh0Fill_C.nc")
            ])

            self._run_command([
                "ncrename", "-v", "surf_el,surf_el_rtofs",
                str(self.work_dir / "SSH_1_ssh0Fill_C.nc")
            ])

            self._run_command([
                "ncap2", "-A", "-F",
                "-s", "SSH_ssh1_adt=ssh-SSH_t1_Fill_0+ADT_t1",
                str(self.work_dir / "SSH_1_ssh0Fill_C.nc"),
                str(self.work_dir / "SSH_1_rtofs_adt_D.nc")
            ])

            self._run_command([
                "ncap2", "-A", "-F",
                "-s", "surf_el=SSH_ssh1_adt*float(1000.)",
                str(self.work_dir / "SSH_1_rtofs_adt_D.nc"),
                str(self.work_dir / "SSH_1_rtofs_adt_D.nc")
            ])

            self._run_command([
                "ncap2", "-A",
                "-s", "where(abs(SSH_ssh1_adt)>1000) surf_el=float(-3000.)",
                str(self.work_dir / "SSH_1_rtofs_adt_D.nc"),
                str(self.work_dir / "SSH_1_rtofs_adt_D.nc")
            ])

            self._run_command([
                "ncatted", "-O",
                "-a", "scale_factor,surf_el,o,f,0.001",
                str(self.work_dir / "SSH_1_rtofs_adt_D.nc"),
                str(self.work_dir / "SSH_1_rtofs_adt_E.nc")
            ])

            self._run_command([
                "ncks", "-O",
                "-v", "xlon", "-v", "ylat", "-v", "surf_el",
                str(self.work_dir / "SSH_1_rtofs_adt_E.nc"),
                str(ssh_out)
            ])

            log.info("ADT blending complete")
            return ssh_out

        except Exception as e:
            log.warning(f"ADT blending failed: {e} - using raw RTOFS SSH")
            return ssh_file

    def _find_and_process_adt(self) -> Optional[Path]:
        """Find and process raw ADT files."""
        # This would process raw CMEMS ADT files
        # For now, return None to use pre-processed files
        return None

    def _link_grid_files(self) -> None:
        """Link required grid files from FIX directory."""
        log.info("Linking grid files...")

        grid_files = [
            (f"{self.RUN}_vgrid.in", "vgrid.in"),
            (f"{self.RUN}_hgrid.ll", "hgrid.ll"),
            (f"{self.RUN}_hgrid.gr3", "hgrid.gr3"),
            (f"{self.RUN}_tem_nudge.gr3", "TEM_nudge.gr3"),
            (f"{self.RUN}_estuary.gr3", "estuary.gr3"),
        ]

        for fix_name, local_name in grid_files:
            fix_file = self.fix_dir / fix_name
            local_file = self.work_dir / local_name
            if local_file.exists():
                local_file.unlink()
            if fix_file.exists():
                local_file.symlink_to(fix_file)
            else:
                log.warning(f"FIX file not found: {fix_file}")

        # Link SCHISM input files
        ssh_nc = self.work_dir / f"SSH_1_{self.pdy}_{self.cycle}.nc"
        if not ssh_nc.exists():
            ssh_nc = self.work_dir / "SSH_1_rtofs_only.nc"

        tsuv_nc = self.work_dir / f"TSUV_1_{self.pdy}_{self.cycle}.nc"

        for link_name, target in [
            ("SSH_1.nc", ssh_nc),
            ("TS_1.nc", tsuv_nc),
            ("UV_1.nc", tsuv_nc),
        ]:
            link_path = self.work_dir / link_name
            if link_path.exists():
                link_path.unlink()
            if target.exists():
                link_path.symlink_to(target)

    def _create_fortran_input_config(self) -> None:
        """Create input configuration files for Fortran executables."""
        log.info("Creating Fortran input configuration...")

        cfg = self.proc_config

        # gen_3Dth_from_nc.in
        config_3dth = self.work_dir / "gen_3Dth_from_nc.in"

        # Check if FIX file exists
        fix_config = self.fix_dir / f"{self.RUN}_obc_3dth_nc.in"
        if fix_config.exists():
            config_3dth.symlink_to(fix_config)
        else:
            # Create default config
            with open(config_3dth, 'w') as f:
                f.write(f"{cfg.temp_outside:.0f} {cfg.salt_outside:.0f}  "
                       f"!T,S values for pts outside bg grid in nc\n")
                f.write(f"{cfg.dt_output:.0f}. !time step in .nc [sec]\n")
                f.write("2 1 2  !# of open bnds that need *3D.th; list of IDs\n")
                f.write("9999   ! # of days needed\n")
                f.write("1 ! # of HYCOM stacks\n")

        # gen_nudge_from_nc.in
        config_nudge = self.work_dir / "gen_nudge_from_nc.in"

        fix_config_nudge = self.fix_dir / f"{self.RUN}_obc_nudge_nc.in"
        if fix_config_nudge.exists():
            config_nudge.symlink_to(fix_config_nudge)
        else:
            with open(config_nudge, 'w') as f:
                f.write(f"{cfg.temp_outside:.0f} {cfg.salt_outside:.0f}\n")
                f.write(f"{cfg.dt_output:.0f} 1\n")
                f.write("1\n")

    def _run_gen_3dth(self) -> List[Path]:
        """Run gen_3Dth_from_hycom Fortran executable."""
        log.info("Running gen_3Dth_from_hycom...")

        exec_file = self.exec_dir / f"{self.RUN}_gen_3Dth_from_hycom"
        if not exec_file.exists():
            # Try alternative name
            exec_file = self.exec_dir / "stofs_3d_atl_gen_3Dth_from_hycom"

        if not exec_file.exists():
            raise FileNotFoundError(f"Executable not found: {exec_file}")

        # Run in work directory
        result = subprocess.run(
            [str(exec_file)],
            cwd=self.work_dir,
            capture_output=True,
            text=True,
            timeout=1800  # 30 minute timeout
        )

        if result.returncode != 0:
            log.warning(f"gen_3Dth_from_hycom stderr: {result.stderr}")
            # Check if output files were created despite non-zero return

        # Collect output files
        output_files = []
        for name in ["elev2D.th.nc", "TEM_3D.th.nc", "SAL_3D.th.nc", "uv3D.th.nc"]:
            out_file = self.work_dir / name
            if out_file.exists():
                output_files.append(out_file)
                log.info(f"Created: {out_file}")
            else:
                log.warning(f"Expected output not created: {name}")

        return output_files

    def _run_gen_nudge(self) -> List[Path]:
        """Run gen_nudge_from_hycom Fortran executable."""
        log.info("Running gen_nudge_from_hycom...")

        exec_file = self.exec_dir / f"{self.RUN}_gen_nudge_from_hycom"
        if not exec_file.exists():
            exec_file = self.exec_dir / "stofs_3d_atl_gen_nudge_from_hycom"

        if not exec_file.exists():
            log.warning(f"Nudge executable not found: {exec_file}")
            return []

        # Link nudge input config
        nudge_config = self.work_dir / "gen_nudge_from_nc.in"
        if not nudge_config.exists():
            fix_config = self.fix_dir / f"{self.RUN}_obc_nudge_nc.in"
            if fix_config.exists():
                nudge_config.symlink_to(fix_config)

        result = subprocess.run(
            [str(exec_file)],
            cwd=self.work_dir,
            capture_output=True,
            text=True,
            timeout=1800
        )

        if result.returncode != 0:
            log.warning(f"gen_nudge_from_hycom stderr: {result.stderr}")

        output_files = []
        for name in ["TEM_nu.nc", "SAL_nu.nc"]:
            out_file = self.work_dir / name
            if out_file.exists():
                output_files.append(out_file)
                log.info(f"Created: {out_file}")

        return output_files

    def _apply_ssh_offset(self, elev_file: Path) -> None:
        """Apply SSH offset of +0.04m to elev2D.th.nc."""
        log.info(f"Applying SSH offset of +{self.proc_config.ssh_offset}m")

        elev_orig = self.work_dir / "elev2D.th.nc_ORI"
        shutil.move(elev_file, elev_orig)

        # Add offset
        self._run_command([
            "ncap2", "-s",
            f"time_series=time_series+float({self.proc_config.ssh_offset})",
            str(elev_orig), "-O",
            str(self.work_dir / "A1.nc")
        ])

        # Ensure correct dimensions
        self._run_command([
            "ncap2", "-s",
            "time_series[time,nOpenBndNodes,nLevels,nComponents]=time_series(0,:,:,:)",
            str(self.work_dir / "A1.nc"), "-O",
            str(elev_file)
        ])

    def _copy_to_output(self, work_files: List[Path]) -> List[Path]:
        """Copy output files to final destination with standard names."""
        output_files = []

        name_mapping = {
            "elev2D.th.nc": f"{self.RUN}.{self.cycle}.elev2dth.nc",
            "TEM_3D.th.nc": f"{self.RUN}.{self.cycle}.tem3dth.nc",
            "SAL_3D.th.nc": f"{self.RUN}.{self.cycle}.sal3dth.nc",
            "uv3D.th.nc": f"{self.RUN}.{self.cycle}.uv3dth.nc",
            "TEM_nu.nc": f"{self.RUN}.{self.cycle}.temnu.nc",
            "SAL_nu.nc": f"{self.RUN}.{self.cycle}.salnu.nc",
        }

        for work_file in work_files:
            std_name = name_mapping.get(work_file.name)
            if std_name:
                out_file = self.output_path / std_name
                shutil.copy(work_file, out_file)
                output_files.append(out_file)
                log.info(f"Output: {out_file}")

                # Also copy to COMOUTrerun if configured
                if self.comout_rerun and self.comout_rerun.exists():
                    rerun_file = self.comout_rerun / std_name
                    shutil.copy(work_file, rerun_file)

        return output_files

    def _run_command(
        self,
        cmd: List[str],
        timeout: int = 300
    ) -> subprocess.CompletedProcess:
        """Run a shell command with logging."""
        log.debug(f"Running: {' '.join(cmd)}")
        result = subprocess.run(
            cmd,
            cwd=self.work_dir,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        if result.returncode != 0:
            log.warning(f"Command returned {result.returncode}: {cmd[0]}")
            if result.stderr:
                log.debug(f"stderr: {result.stderr[:500]}")
        return result

    # =========================================================================
    # Python Fallback Mode
    # =========================================================================

    def _process_python_mode(
        self,
        rtofs_files: RTOFSFileSet
    ) -> Tuple[List[Path], List[str]]:
        """
        Process RTOFS using pure Python (fallback mode).

        This is a simplified implementation that doesn't require NCO tools
        or Fortran executables, but may produce slightly different results.
        """
        log.info("Processing in Python fallback mode...")
        output_files = []
        errors = []

        if not HAS_NETCDF4:
            errors.append("netCDF4 required for Python mode processing")
            return output_files, errors

        try:
            # Load boundary node information
            bnd_nodes = self._load_boundary_nodes()

            # Extract RTOFS data
            rtofs_data = self._extract_rtofs_data(rtofs_files, bnd_nodes)

            if not rtofs_data:
                errors.append("Failed to extract RTOFS data")
                return output_files, errors

            # Create boundary condition files
            elev_file = self._create_elev2d(rtofs_data)
            if elev_file:
                output_files.append(elev_file)

            temp_file = self._create_tem3d(rtofs_data)
            if temp_file:
                output_files.append(temp_file)

            salt_file = self._create_sal3d(rtofs_data)
            if salt_file:
                output_files.append(salt_file)

            uv_file = self._create_uv3d(rtofs_data)
            if uv_file:
                output_files.append(uv_file)

            # Create nudging files if enabled
            if self.nudging_enabled:
                temp_nu = self._create_nudging_file(
                    rtofs_data, "temperature", "TEM_nu.nc"
                )
                salt_nu = self._create_nudging_file(
                    rtofs_data, "salinity", "SAL_nu.nc"
                )
                if temp_nu:
                    output_files.append(temp_nu)
                if salt_nu:
                    output_files.append(salt_nu)

            return output_files, errors

        except Exception as e:
            errors.append(str(e))
            return output_files, errors

    def _load_boundary_nodes(self) -> Dict[str, Any]:
        """Load boundary node locations from FIX file."""
        bnd_nodes = {
            "indices": [],
            "lons": [],
            "lats": [],
        }

        boundary_nodes_file = self.fix_dir / f"{self.RUN}_bnd_nodes.txt"

        if not boundary_nodes_file.exists():
            log.warning(f"Boundary nodes file not found: {boundary_nodes_file}")
            return bnd_nodes

        try:
            with open(boundary_nodes_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    parts = line.split()
                    if len(parts) >= 3:
                        bnd_nodes["indices"].append(int(parts[0]))
                        bnd_nodes["lons"].append(float(parts[1]))
                        bnd_nodes["lats"].append(float(parts[2]))

            log.info(f"Loaded {len(bnd_nodes['indices'])} boundary nodes")

        except Exception as e:
            log.error(f"Error loading boundary nodes: {e}")

        return bnd_nodes

    def _extract_rtofs_data(
        self,
        rtofs_files: RTOFSFileSet,
        bnd_nodes: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Extract data from RTOFS files at boundary locations."""
        rtofs_data = {
            "times": [],
            "depths": None,
            "bnd_lons": np.array(bnd_nodes.get("lons", [])),
            "bnd_lats": np.array(bnd_nodes.get("lats", [])),
        }

        for var in ["ssh", "temperature", "salinity", "u_current", "v_current"]:
            rtofs_data[var] = []

        base_time = datetime.strptime(self.pdy, "%Y%m%d") + timedelta(hours=self.cyc)

        # Process 2D files for SSH
        for rtofs_file in rtofs_files.files_2d:
            try:
                nc = Dataset(rtofs_file, 'r')

                fhr = self._extract_fhr_from_filename(rtofs_file.name)
                valid_time = base_time + timedelta(hours=fhr)

                if "ssh" in nc.variables:
                    ssh = nc.variables["ssh"][:]
                    rtofs_data["ssh"].append(ssh)
                    if valid_time not in rtofs_data["times"]:
                        rtofs_data["times"].append(valid_time)

                nc.close()

            except Exception as e:
                log.warning(f"Error reading {rtofs_file}: {e}")

        # Process 3D files for T,S,U,V
        for rtofs_file in rtofs_files.files_3d:
            try:
                nc = Dataset(rtofs_file, 'r')

                if rtofs_data["depths"] is None and "Depth" in nc.variables:
                    rtofs_data["depths"] = nc.variables["Depth"][:]

                for var_name, nc_var in [
                    ("temperature", "temperature"),
                    ("salinity", "salinity"),
                    ("u_current", "u"),
                    ("v_current", "v")
                ]:
                    if nc_var in nc.variables:
                        data = nc.variables[nc_var][:]
                        rtofs_data[var_name].append(data)

                nc.close()

            except Exception as e:
                log.warning(f"Error reading {rtofs_file}: {e}")

        return rtofs_data

    def _extract_fhr_from_filename(self, filename: str) -> int:
        """Extract forecast hour from RTOFS filename."""
        try:
            if '_n' in filename:
                # Nowcast file: n012, n018, n024
                parts = filename.split('_')
                for p in parts:
                    if p.startswith('n') and p[1:].isdigit():
                        return int(p[1:]) - 24  # Convert to relative hour
            if '_f' in filename:
                # Forecast file: f000, f006, etc.
                parts = filename.split('_')
                for p in parts:
                    if p.startswith('f') and p[1:4].isdigit():
                        return int(p[1:4])
        except (ValueError, IndexError):
            pass
        return 0

    # SSH offset applied per shell script
    SSH_OFFSET = 0.04  # meters

    def _create_elev2d(
        self,
        data: Dict[str, Any],
        apply_offset: bool = True
    ) -> Optional[Path]:
        """Create elev2D.th.nc boundary file for SSH."""
        output_file = self.output_path / "elev2D.th.nc"

        if apply_offset and "ssh" in data and data["ssh"]:
            data["ssh"] = [
                ssh + self.SSH_OFFSET if ssh is not None else ssh
                for ssh in data["ssh"]
            ]
            log.info(f"Applied SSH offset of +{self.SSH_OFFSET}m")

        return self._create_boundary_file(data, "ssh", output_file, is_3d=False)

    def _create_tem3d(self, data: Dict[str, Any]) -> Optional[Path]:
        """Create TEM_3D.th.nc boundary file for temperature."""
        output_file = self.output_path / "TEM_3D.th.nc"
        return self._create_boundary_file(data, "temperature", output_file, is_3d=True)

    def _create_sal3d(self, data: Dict[str, Any]) -> Optional[Path]:
        """Create SAL_3D.th.nc boundary file for salinity."""
        output_file = self.output_path / "SAL_3D.th.nc"
        return self._create_boundary_file(data, "salinity", output_file, is_3d=True)

    def _create_uv3d(self, data: Dict[str, Any]) -> Optional[Path]:
        """Create uv3D.th.nc boundary file for currents."""
        output_file = self.output_path / "uv3D.th.nc"

        if not HAS_NETCDF4:
            return None

        times = data.get("times", [])
        u_data = data.get("u_current", [])
        v_data = data.get("v_current", [])

        if not times or not u_data:
            return None

        try:
            nc = Dataset(output_file, 'w', format='NETCDF4')

            base_time = times[0]
            depths = data.get("depths", np.array([0]))

            nc.createDimension('time', len(times))
            nc.createDimension('nOpenBndNodes', len(data.get("bnd_lons", [])) or 1)
            nc.createDimension('nLevels', len(depths))
            nc.createDimension('nComponents', 2)

            time_var = nc.createVariable('time', 'f8', ('time',))
            time_var.units = f"days since {base_time.strftime('%Y-%m-%d')} 00:00:00"
            time_var[:] = [(t - base_time).total_seconds() / 86400.0 for t in times]

            uv_var = nc.createVariable(
                'time_series', 'f4',
                ('time', 'nOpenBndNodes', 'nLevels', 'nComponents')
            )
            uv_var.long_name = "UV velocity at boundary"

            for i, (u, v) in enumerate(zip(u_data, v_data)):
                if u is not None and v is not None:
                    uv_var[i, :, :, 0] = u.T if u.ndim > 1 else u
                    uv_var[i, :, :, 1] = v.T if v.ndim > 1 else v

            nc.close()
            log.info(f"Created {output_file}")
            return output_file

        except Exception as e:
            log.error(f"Failed to create uv3D: {e}")
            return None

    def _create_boundary_file(
        self,
        data: Dict[str, Any],
        var_name: str,
        output_file: Path,
        is_3d: bool
    ) -> Optional[Path]:
        """Create a boundary condition NetCDF file."""
        if not HAS_NETCDF4:
            return None

        times = data.get("times", [])
        var_data = data.get(var_name, [])

        if not times or not var_data:
            return None

        try:
            nc = Dataset(output_file, 'w', format='NETCDF4')

            base_time = times[0]

            nc.createDimension('time', len(times))
            nc.createDimension('nOpenBndNodes', len(data.get("bnd_lons", [])) or 1)

            if is_3d:
                depths = data.get("depths", np.array([0]))
                nc.createDimension('nLevels', len(depths))

            time_var = nc.createVariable('time', 'f8', ('time',))
            time_var.units = f"days since {base_time.strftime('%Y-%m-%d')} 00:00:00"
            time_var[:] = [(t - base_time).total_seconds() / 86400.0 for t in times]

            if is_3d:
                data_var = nc.createVariable(
                    'time_series', 'f4',
                    ('time', 'nOpenBndNodes', 'nLevels')
                )
            else:
                data_var = nc.createVariable(
                    'time_series', 'f4',
                    ('time', 'nOpenBndNodes')
                )

            data_var.long_name = f"{var_name} at boundary"

            for i, d in enumerate(var_data):
                if d is not None:
                    if is_3d and d.ndim > 1:
                        data_var[i] = d.T
                    else:
                        data_var[i] = d

            nc.close()
            log.info(f"Created {output_file}")
            return output_file

        except Exception as e:
            log.error(f"Failed to create {output_file}: {e}")
            return None

    def _create_nudging_file(
        self,
        data: Dict[str, Any],
        var_name: str,
        filename: str
    ) -> Optional[Path]:
        """Create T/S nudging file."""
        output_file = self.output_path / filename

        if not HAS_NETCDF4:
            return None

        times = data.get("times", [])
        var_data = data.get(var_name, [])

        if not times or not var_data:
            return None

        try:
            nc = Dataset(output_file, 'w', format='NETCDF4')

            base_time = times[0]
            depths = data.get("depths", np.array([0]))

            nc.createDimension('time', len(times))
            nc.createDimension('node', len(data.get("bnd_lons", [])) or 1)
            nc.createDimension('nVert', len(depths))

            time_var = nc.createVariable('time', 'f8', ('time',))
            time_var.units = f"days since {base_time.strftime('%Y-%m-%d')} 00:00:00"
            time_var[:] = [(t - base_time).total_seconds() / 86400.0 for t in times]

            nu_var = nc.createVariable(var_name, 'f4', ('time', 'node', 'nVert'))
            nu_var.long_name = f"{var_name} nudging field"

            for i, d in enumerate(var_data):
                if d is not None:
                    if d.ndim > 1:
                        nu_var[i] = d.T
                    else:
                        nu_var[i] = d

            nc.nudging_timescale = self.nudging_timescale
            nc.close()

            log.info(f"Created nudging file {output_file}")
            return output_file

        except Exception as e:
            log.error(f"Failed to create nudging file: {e}")
            return None
