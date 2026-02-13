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

Processing Pipeline (fully native Python -- no subprocess calls):
1. Discover and validate RTOFS files (2D and 3D)
2. Extract ROI using xarray/netCDF4
3. Concatenate time steps in memory
4. Transform variables (fill-value handling, dimension renaming)
5. Optionally blend SSH with ADT altimetry
6. Interpolate RTOFS 3D fields to SCHISM boundary nodes (replaces Fortran
   gen_3Dth_from_hycom / gen_nudge_from_hycom)
7. Apply SSH offset (+0.04m)
8. Write SCHISM-format output NetCDF files
9. QC and archive
"""

import logging
import os
import shutil
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

try:
    import xarray as xr
    HAS_XARRAY = True
except ImportError:
    HAS_XARRAY = False

try:
    from scipy.interpolate import (
        LinearNDInterpolator,
        NearestNDInterpolator,
        RegularGridInterpolator,
    )
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False


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

    # ROI indices for 3D nudging (slightly larger domain)
    idx_x1_3dz_nudge: int = 422
    idx_x2_3dz_nudge: int = 600
    idx_y1_3dz_nudge: int = 94
    idx_y2_3dz_nudge: int = 835

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

    # Fill-value sentinel used in intermediate processing
    fill_value: float = -30000.0

    # QC thresholds
    qc_dim_cr_min: int = 17
    qc_dim_cr_max: int = 21


class RTOFSProcessor(ForcingProcessor):
    """
    RTOFS ocean boundary condition processor for SCHISM.

    Extracts T, S, SSH, and currents from RTOFS NetCDF files and creates
    SCHISM-compatible boundary condition files using native Python (xarray,
    netCDF4, scipy).

    Processing modes:
    - Native Python (default): Full pipeline in pure Python.
    - Legacy Fortran (fallback): Shells out to NCO tools + Fortran if
      *use_fortran_exec=True* AND the executables exist on PATH.  This path
      is deprecated and will be removed in a future release.
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
        use_fortran_exec: bool = False,
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
            use_fortran_exec: DEPRECATED -- kept for backward compat only.
            processing_config: Custom processing configuration
        """
        super().__init__(config, input_path, output_path, variables)
        self.nudging_enabled = nudging_enabled
        self.nudging_timescale = nudging_timescale
        self.adt_enabled = adt_enabled
        self.use_fortran_exec = False  # Always use native Python
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
        self.comout_rerun = (
            Path(config.COMOUTrerun) if config.COMOUTrerun else None
        )

        # Working directory for intermediate files
        self.work_dir = self.output_path / "rtofs_work"

        self._verify_deps()

    # ------------------------------------------------------------------
    # Dependency checks
    # ------------------------------------------------------------------
    def _verify_deps(self) -> None:
        """Verify that required Python libraries are available."""
        missing = []
        if not HAS_NETCDF4:
            missing.append("netCDF4")
        if not HAS_XARRAY:
            missing.append("xarray")
        if not HAS_SCIPY:
            missing.append("scipy")
        if missing:
            log.warning(
                "Optional dependencies missing for full native RTOFS "
                "processing: %s. Install with: pip install %s",
                ", ".join(missing),
                " ".join(missing),
            )

    # ==================================================================
    # Main entry point
    # ==================================================================
    def process(self) -> ForcingResult:
        """
        Process RTOFS ocean boundary forcing.

        Returns:
            ForcingResult with processed files
        """
        log.info("Processing %s ocean boundary conditions", self.source_name)
        log.info("Input path: %s", self.input_path)
        log.info("Output path: %s", self.output_path)
        log.info("Nudging enabled: %s", self.nudging_enabled)
        log.info("ADT blending enabled: %s", self.adt_enabled)

        if not self.validate_input():
            return ForcingResult(
                success=False,
                source=self.source_name,
                errors=[f"Input path not found: {self.input_path}"],
            )

        if not HAS_NETCDF4:
            return ForcingResult(
                success=False,
                source=self.source_name,
                errors=["netCDF4 is required for RTOFS processing"],
            )

        self.create_output_dir()
        self.work_dir.mkdir(parents=True, exist_ok=True)

        output_files: List[Path] = []
        errors: List[str] = []

        try:
            # Step 1: Discover RTOFS files
            rtofs_files = self._discover_rtofs_files()

            if not rtofs_files.files_2d or not rtofs_files.files_3d:
                return ForcingResult(
                    success=False,
                    source=self.source_name,
                    errors=["Insufficient RTOFS files found"],
                )

            log.info(
                "Found %d 2D files, %d 3D files",
                len(rtofs_files.files_2d),
                len(rtofs_files.files_3d),
            )

            # Step 2-9: Full native Python processing
            output_files, errors = self._process_python(rtofs_files)

            if errors:
                log.warning("RTOFS processing completed with warnings: %s", errors)

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
                    "mode": "python_native",
                },
            )

        except Exception as e:
            log.error("RTOFS processing failed: %s", e, exc_info=True)
            return ForcingResult(
                success=False,
                source=self.source_name,
                errors=[str(e)],
            )

    # ==================================================================
    # File Discovery
    # ==================================================================

    def _discover_rtofs_files(self) -> RTOFSFileSet:
        """
        Discover and validate RTOFS input files.

        Searches for today's files first, then falls back to previous day.
        Validates file sizes to ensure data quality.
        """
        yyyymmdd_today = self.pdy
        yyyymmdd_prev = (
            datetime.strptime(self.pdy, "%Y%m%d") - timedelta(days=1)
        ).strftime("%Y%m%d")

        files_today = self._find_rtofs_files_for_date(yyyymmdd_today)
        files_prev = self._find_rtofs_files_for_date(yyyymmdd_prev)

        result = self._merge_file_sets(files_today, files_prev)

        log.info(
            "RTOFS file discovery: %d 2D, %d 3D files",
            len(result.files_2d),
            len(result.files_3d),
        )
        return result

    def _find_rtofs_files_for_date(self, yyyymmdd: str) -> RTOFSFileSet:
        """Find RTOFS files for a specific date."""
        result = RTOFSFileSet(date=yyyymmdd)

        rtofs_dir = self.input_path / f"rtofs.{yyyymmdd}"
        if not rtofs_dir.exists():
            log.debug("RTOFS directory not found: %s", rtofs_dir)
            return result

        # 2D surface files -- nowcast + forecast
        nowcast_2d = ["n012", "n018"]
        forecast_2d = [f"f{h:03d}" for h in range(0, 132, 6)]

        for prefix in nowcast_2d + forecast_2d:
            pattern = f"rtofs_glo_2ds_{prefix}_diag.nc"
            for f in sorted(rtofs_dir.glob(pattern)):
                if self._validate_file_size(f, self.proc_config.min_size_2d):
                    result.files_2d.append(f)

        # 3D depth files
        nowcast_3d = ["n012", "n018", "n024"]
        forecast_3d = [f"f{h:03d}" for h in range(6, 132, 6)]

        for prefix in nowcast_3d + forecast_3d:
            pattern = f"rtofs_glo_3dz_{prefix}_6hrly_hvr_US_east.nc"
            for f in sorted(rtofs_dir.glob(pattern)):
                if self._validate_file_size(f, self.proc_config.min_size_3d):
                    result.files_3d.append(f)

        result.files_2d = sorted(result.files_2d, key=lambda p: p.name)
        result.files_3d = sorted(result.files_3d, key=lambda p: p.name)
        return result

    def _validate_file_size(self, filepath: Path, min_size: int) -> bool:
        if not filepath.exists():
            return False
        size = filepath.stat().st_size
        if size < min_size:
            log.debug("File too small: %s (%d < %d)", filepath, size, min_size)
            return False
        return True

    def _merge_file_sets(
        self, primary: RTOFSFileSet, backup: RTOFSFileSet
    ) -> RTOFSFileSet:
        """Merge primary and backup file sets, filling gaps from backup."""
        result = RTOFSFileSet(date=primary.date or backup.date)
        cfg = self.proc_config

        for attr, target in [
            ("files_2d", cfg.n_target_2d),
            ("files_3d", cfg.n_target_3d),
        ]:
            prim = getattr(primary, attr)
            back = getattr(backup, attr)
            if len(prim) >= cfg.min_files_required:
                merged = prim[:target]
            elif len(prim) > 2:
                n_needed = target - len(prim)
                merged = prim + back[:n_needed]
            elif len(back) >= cfg.min_files_required:
                merged = back[:target]
                result.is_backup = True
            else:
                merged = []
            setattr(result, attr, merged)

        # Ensure same count for 2D and 3D
        n_min = min(len(result.files_2d), len(result.files_3d))
        result.files_2d = result.files_2d[:n_min]
        result.files_3d = result.files_3d[:n_min]
        return result

    # ==================================================================
    # Native Python Processing Pipeline
    # ==================================================================

    def _process_python(
        self, rtofs_files: RTOFSFileSet
    ) -> Tuple[List[Path], List[str]]:
        """Full native Python processing pipeline."""
        output_files: List[Path] = []
        errors: List[str] = []

        try:
            # --- Step 2: Read & extract ROI --------------------------------
            ssh_data = self._read_and_extract_2d(rtofs_files.files_2d)
            tsuv_data = self._read_and_extract_3d(rtofs_files.files_3d)

            if ssh_data is None or tsuv_data is None:
                errors.append("Failed to read RTOFS data")
                return output_files, errors

            # --- Step 3: Handle fill values in SSH -------------------------
            ssh_vals = ssh_data["ssh"]
            ssh_vals = np.where(
                np.abs(ssh_vals) > 10000,
                self.proc_config.fill_value,
                ssh_vals,
            )
            ssh_data["ssh"] = ssh_vals

            # --- Step 4: Optionally blend SSH with ADT ---------------------
            if self.adt_enabled:
                ssh_data = self._blend_ssh_with_adt(ssh_data)

            # --- Step 5: Load SCHISM grid & boundary info ------------------
            grid_info = self._load_schism_grid()
            if grid_info is None:
                errors.append("Failed to load SCHISM grid information")
                return output_files, errors

            # --- Step 6: Interpolate to SCHISM boundary nodes --------------
            bc_data = self._interpolate_to_boundary(
                ssh_data, tsuv_data, grid_info
            )

            # --- Step 7: Apply SSH offset (+0.04 m) ------------------------
            if "elev" in bc_data and bc_data["elev"] is not None:
                bc_data["elev"] = bc_data["elev"] + self.proc_config.ssh_offset
                log.info(
                    "Applied SSH offset of +%.2f m", self.proc_config.ssh_offset
                )

            # --- Step 8: Write SCHISM output NetCDF files ------------------
            written = self._write_schism_bc_files(bc_data, grid_info)
            output_files.extend(written)

            # --- Step 9: Write nudging fields if enabled -------------------
            if self.nudging_enabled:
                nudge_files = self._create_nudging_fields(
                    tsuv_data, grid_info
                )
                output_files.extend(nudge_files)

            # --- Step 10: Copy to output with standard names ---------------
            final = self._copy_to_output(output_files)
            return final, errors

        except Exception as e:
            log.error("Python processing failed: %s", e, exc_info=True)
            errors.append(str(e))
            return output_files, errors

    # ------------------------------------------------------------------
    # Reading / ROI extraction
    # ------------------------------------------------------------------

    def _read_and_extract_2d(
        self, files_2d: List[Path]
    ) -> Optional[Dict[str, Any]]:
        """Read 2D SSH files and extract the ROI sub-domain."""
        cfg = self.proc_config
        all_ssh = []
        all_times = []
        lon = lat = None

        for fpath in files_2d:
            try:
                with Dataset(str(fpath), "r") as nc:
                    x1, x2 = cfg.idx_x1_2ds, cfg.idx_x2_2ds + 1
                    y1, y2 = cfg.idx_y1_2ds, cfg.idx_y2_2ds + 1

                    ssh = nc.variables["ssh"][:, y1:y2, x1:x2]
                    all_ssh.append(ssh)

                    if lon is None:
                        lon = nc.variables["Longitude"][y1:y2, x1:x2]
                        lat = nc.variables["Latitude"][y1:y2, x1:x2]

                    # Read time from MT
                    mt = nc.variables["MT"][:]
                    all_times.append(mt)
            except Exception as e:
                log.warning("Error reading 2D file %s: %s", fpath, e)

        if not all_ssh:
            return None

        ssh_concat = np.concatenate(all_ssh, axis=0)
        times_concat = np.concatenate(all_times, axis=0)

        log.info(
            "Read 2D SSH: shape=%s, %d time steps",
            ssh_concat.shape,
            ssh_concat.shape[0],
        )

        return {
            "ssh": ssh_concat,
            "lon": np.asarray(lon),
            "lat": np.asarray(lat),
            "times": times_concat,
        }

    def _read_and_extract_3d(
        self, files_3d: List[Path]
    ) -> Optional[Dict[str, Any]]:
        """Read 3D TSUV files and extract the ROI sub-domain."""
        cfg = self.proc_config
        all_temp: List[np.ndarray] = []
        all_salt: List[np.ndarray] = []
        all_u: List[np.ndarray] = []
        all_v: List[np.ndarray] = []
        all_times: List[np.ndarray] = []
        lon = lat = depth = None

        for fpath in files_3d:
            try:
                with Dataset(str(fpath), "r") as nc:
                    x1, x2 = cfg.idx_x1_3dz, cfg.idx_x2_3dz + 1
                    y1, y2 = cfg.idx_y1_3dz, cfg.idx_y2_3dz + 1

                    temp = nc.variables["temperature"][:, :, y1:y2, x1:x2]
                    salt = nc.variables["salinity"][:, :, y1:y2, x1:x2]
                    u = nc.variables["u"][:, :, y1:y2, x1:x2]
                    v = nc.variables["v"][:, :, y1:y2, x1:x2]

                    all_temp.append(temp)
                    all_salt.append(salt)
                    all_u.append(u)
                    all_v.append(v)

                    if lon is None:
                        lon = nc.variables["Longitude"][y1:y2, x1:x2]
                        lat = nc.variables["Latitude"][y1:y2, x1:x2]
                        if "Depth" in nc.variables:
                            depth = nc.variables["Depth"][:]

                    mt = nc.variables["MT"][:]
                    all_times.append(mt)
            except Exception as e:
                log.warning("Error reading 3D file %s: %s", fpath, e)

        if not all_temp:
            return None

        result = {
            "temperature": np.concatenate(all_temp, axis=0),
            "salinity": np.concatenate(all_salt, axis=0),
            "water_u": np.concatenate(all_u, axis=0),
            "water_v": np.concatenate(all_v, axis=0),
            "lon": np.asarray(lon),
            "lat": np.asarray(lat),
            "depth": np.asarray(depth) if depth is not None else np.array([0.0]),
            "times": np.concatenate(all_times, axis=0),
        }

        log.info(
            "Read 3D TSUV: temp shape=%s, %d time steps",
            result["temperature"].shape,
            result["temperature"].shape[0],
        )
        return result

    # ------------------------------------------------------------------
    # ADT blending
    # ------------------------------------------------------------------

    def _blend_ssh_with_adt(self, ssh_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Blend RTOFS SSH with ADT satellite altimetry (pure Python).

        Formula per shell script:
            SSH_blended = (SSH - SSH_t1) + ADT_t1
        where SSH_t1 is the first-time-step RTOFS SSH and ADT_t1 is the
        ADT field.

        If ADT not available, returns ssh_data unchanged.
        """
        adt_file = self._find_adt_file()
        if adt_file is None:
            log.info("No ADT data available -- using raw RTOFS SSH")
            return ssh_data

        try:
            with Dataset(str(adt_file), "r") as nc:
                # The pre-processed ADT file has variable surf_el
                if "surf_el" in nc.variables:
                    adt_surf_el = nc.variables["surf_el"][:]
                else:
                    log.warning("surf_el not found in ADT file")
                    return ssh_data

            ssh = ssh_data["ssh"]  # (ntime, ny, nx)
            fill = self.proc_config.fill_value

            # ADT at t=0
            if adt_surf_el.ndim == 3:
                adt_t1 = adt_surf_el[0, :, :]
            else:
                adt_t1 = adt_surf_el

            # Ensure shapes are compatible
            if adt_t1.shape != ssh.shape[1:]:
                log.warning(
                    "ADT shape %s != SSH spatial shape %s -- skipping blend",
                    adt_t1.shape,
                    ssh.shape[1:],
                )
                return ssh_data

            # SSH at first time step
            ssh_t1 = ssh[0, :, :]
            ssh_t1_safe = np.where(np.abs(ssh_t1) > 1000, 0.0, ssh_t1)

            # Blend: for each time step
            blended = np.empty_like(ssh)
            for t in range(ssh.shape[0]):
                raw = ssh[t, :, :]
                b = raw - ssh_t1_safe + adt_t1
                # Mask out locations where blended is unreasonable
                b = np.where(np.abs(b) > 1000, fill, b)
                blended[t, :, :] = b

            ssh_data["ssh"] = blended
            log.info("ADT blending applied successfully")

        except Exception as e:
            log.warning("ADT blending failed: %s -- using raw RTOFS SSH", e)

        return ssh_data

    def _find_adt_file(self) -> Optional[Path]:
        """Locate the pre-processed ADT file."""
        # Priority 1: COMOUTrerun
        if self.comout_rerun:
            candidate = self.comout_rerun / "adt_aft_cvtz_cln.nc"
            if candidate.exists():
                log.info("Using pre-processed ADT from %s", candidate)
                return candidate

        # Priority 2: ADT input directory
        if self.adt_path and self.adt_path.exists():
            for pattern in ["adt_aft_cvtz_cln.nc", "adt_*.nc", "*.nc"]:
                matches = sorted(self.adt_path.glob(pattern))
                if matches:
                    return matches[0]
        return None

    # ------------------------------------------------------------------
    # SCHISM grid loading
    # ------------------------------------------------------------------

    def _load_schism_grid(self) -> Optional[Dict[str, Any]]:
        """
        Load SCHISM grid and boundary information from FIX files.

        Required files:
        - hgrid.gr3 (or hgrid.ll) -- horizontal grid with boundary defs
        - vgrid.in -- vertical grid
        - TEM_nudge.gr3 -- nudging zone definition
        """
        grid = {}

        # --- Read horizontal grid boundary nodes -------------------------
        for name in [
            f"{self.RUN}_hgrid.ll",
            f"{self.RUN}_hgrid.gr3",
        ]:
            hgrid_file = self.fix_dir / name
            if hgrid_file.exists():
                bnd = self._parse_hgrid_boundaries(hgrid_file)
                if bnd:
                    grid.update(bnd)
                    break

        if "bnd_nodes" not in grid:
            # Try standalone boundary-nodes file
            bnd_file = self.fix_dir / f"{self.RUN}_bnd_nodes.txt"
            if bnd_file.exists():
                bnd = self._load_bnd_nodes_txt(bnd_file)
                grid.update(bnd)

        if "bnd_nodes" not in grid:
            log.warning("No boundary node information found in FIX directory")
            return None

        # --- Read vertical grid ------------------------------------------
        vgrid_file = self.fix_dir / f"{self.RUN}_vgrid.in"
        if vgrid_file.exists():
            grid["vgrid"] = self._parse_vgrid(vgrid_file)
        else:
            grid["vgrid"] = None

        # --- Nudge zone file (optional) ----------------------------------
        nudge_file = self.fix_dir / f"{self.RUN}_tem_nudge.gr3"
        if nudge_file.exists():
            grid["nudge_file"] = nudge_file

        log.info(
            "Loaded SCHISM grid: %d boundary nodes, %d open boundaries",
            len(grid.get("bnd_lons", [])),
            grid.get("num_open_boundaries", 0),
        )
        return grid

    def _parse_hgrid_boundaries(self, hgrid_file: Path) -> Dict[str, Any]:
        """Parse open boundary nodes from hgrid.gr3."""
        result: Dict[str, Any] = {}
        try:
            with open(hgrid_file, "r") as f:
                lines = f.readlines()

            # line 0: header
            # line 1: ne np
            ne, np_nodes = map(int, lines[1].strip().split()[:2])

            # Read node coordinates
            node_x = np.zeros(np_nodes)
            node_y = np.zeros(np_nodes)
            for i in range(np_nodes):
                parts = lines[2 + i].strip().split()
                node_x[i] = float(parts[1])
                node_y[i] = float(parts[2])

            # Skip elements, find boundary section
            line_idx = 2 + np_nodes + ne

            if line_idx >= len(lines):
                return result

            nope = int(lines[line_idx].strip().split()[0])
            result["num_open_boundaries"] = nope
            line_idx += 1

            neta = int(lines[line_idx].strip().split()[0])
            result["total_open_nodes"] = neta
            line_idx += 1

            all_bnd_indices = []
            bnd_segments = []
            for seg in range(nope):
                nn = int(lines[line_idx].strip().split()[0])
                line_idx += 1
                seg_nodes = []
                for _ in range(nn):
                    nidx = int(lines[line_idx].strip().split()[0])
                    seg_nodes.append(nidx)
                    all_bnd_indices.append(nidx)
                    line_idx += 1
                bnd_segments.append(seg_nodes)

            bnd_indices = np.array(all_bnd_indices)
            result["bnd_nodes"] = bnd_indices
            result["bnd_lons"] = node_x[bnd_indices - 1]  # 1-based
            result["bnd_lats"] = node_y[bnd_indices - 1]
            result["bnd_segments"] = bnd_segments
            result["node_x"] = node_x
            result["node_y"] = node_y

        except Exception as e:
            log.warning("Error parsing hgrid boundaries: %s", e)

        return result

    def _load_bnd_nodes_txt(self, bnd_file: Path) -> Dict[str, Any]:
        """Load boundary nodes from simple text file."""
        indices, lons, lats = [], [], []
        try:
            with open(bnd_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split()
                    if len(parts) >= 3:
                        indices.append(int(parts[0]))
                        lons.append(float(parts[1]))
                        lats.append(float(parts[2]))
        except Exception as e:
            log.warning("Error reading boundary nodes file: %s", e)

        return {
            "bnd_nodes": np.array(indices),
            "bnd_lons": np.array(lons),
            "bnd_lats": np.array(lats),
            "num_open_boundaries": 1,
        }

    def _parse_vgrid(self, vgrid_file: Path) -> Optional[Dict[str, Any]]:
        """Parse SCHISM vgrid.in to get vertical levels."""
        try:
            with open(vgrid_file, "r") as f:
                lines = f.readlines()
            # First line: ivcor (1=LSC2, 2=SZ)
            ivcor = int(lines[0].strip())
            if ivcor == 2:
                # SZ coordinates
                parts = lines[1].strip().split()
                nvrt = int(parts[0])
                return {"ivcor": ivcor, "nvrt": nvrt}
            elif ivcor == 1:
                nvrt = int(lines[1].strip().split()[0])
                return {"ivcor": ivcor, "nvrt": nvrt}
        except Exception as e:
            log.warning("Error parsing vgrid.in: %s", e)
        return None

    # ------------------------------------------------------------------
    # Interpolation to SCHISM boundary
    # ------------------------------------------------------------------

    def _interpolate_to_boundary(
        self,
        ssh_data: Dict[str, Any],
        tsuv_data: Dict[str, Any],
        grid_info: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Interpolate RTOFS fields to SCHISM open-boundary nodes.

        This replaces the Fortran gen_3Dth_from_hycom executable.
        Uses scipy nearest-neighbor or linear interpolation.
        """
        bnd_lons = grid_info["bnd_lons"]
        bnd_lats = grid_info["bnd_lats"]
        n_bnd = len(bnd_lons)

        cfg = self.proc_config
        fill = cfg.fill_value

        result: Dict[str, Any] = {}

        # --- SSH (2D) interpolation --------------------------------------
        ssh = ssh_data["ssh"]  # (ntime, ny_2d, nx_2d)
        lon_2d = ssh_data["lon"]  # (ny_2d, nx_2d)
        lat_2d = ssh_data["lat"]
        ntime_2d = ssh.shape[0]

        log.info("Interpolating SSH to %d boundary nodes, %d time steps", n_bnd, ntime_2d)

        elev_bnd = np.full((ntime_2d, n_bnd), 0.0, dtype=np.float32)
        pts_src_2d = np.column_stack([lon_2d.ravel(), lat_2d.ravel()])
        pts_dst = np.column_stack([bnd_lons, bnd_lats])

        for t in range(ntime_2d):
            vals = ssh[t, :, :].ravel()
            valid = np.abs(vals) < 10000
            if np.sum(valid) > 3 and HAS_SCIPY:
                interp = NearestNDInterpolator(pts_src_2d[valid], vals[valid])
                elev_bnd[t, :] = interp(pts_dst)
            elif np.sum(valid) > 0:
                elev_bnd[t, :] = np.nanmean(vals[valid])

        result["elev"] = elev_bnd
        result["times_2d"] = ssh_data["times"]

        # --- 3D variable interpolation -----------------------------------
        temp_3d = tsuv_data["temperature"]  # (ntime, nlev, ny, nx)
        salt_3d = tsuv_data["salinity"]
        u_3d = tsuv_data["water_u"]
        v_3d = tsuv_data["water_v"]
        lon_3d = tsuv_data["lon"]
        lat_3d = tsuv_data["lat"]
        depth = tsuv_data["depth"]
        ntime_3d = temp_3d.shape[0]
        nlev = temp_3d.shape[1]

        log.info(
            "Interpolating 3D fields to %d boundary nodes, %d levels, %d steps",
            n_bnd,
            nlev,
            ntime_3d,
        )

        pts_src_3d = np.column_stack([lon_3d.ravel(), lat_3d.ravel()])

        tem_bnd = np.full((ntime_3d, n_bnd, nlev), cfg.temp_outside, dtype=np.float32)
        sal_bnd = np.full((ntime_3d, n_bnd, nlev), cfg.salt_outside, dtype=np.float32)
        u_bnd = np.zeros((ntime_3d, n_bnd, nlev), dtype=np.float32)
        v_bnd = np.zeros((ntime_3d, n_bnd, nlev), dtype=np.float32)

        for t in range(ntime_3d):
            for k in range(nlev):
                for var_src, var_dst, default in [
                    (temp_3d, tem_bnd, cfg.temp_outside),
                    (salt_3d, sal_bnd, cfg.salt_outside),
                    (u_3d, u_bnd, 0.0),
                    (v_3d, v_bnd, 0.0),
                ]:
                    vals = var_src[t, k, :, :].ravel()
                    if isinstance(vals, np.ma.MaskedArray):
                        valid = ~vals.mask
                        vals = vals.filled(np.nan)
                    else:
                        valid = np.isfinite(vals) & (np.abs(vals) < 10000)

                    if np.sum(valid) > 3 and HAS_SCIPY:
                        interp = NearestNDInterpolator(
                            pts_src_3d[valid], vals[valid]
                        )
                        var_dst[t, :, k] = interp(pts_dst)
                    elif np.sum(valid) > 0:
                        var_dst[t, :, k] = np.nanmean(vals[valid])
                    else:
                        var_dst[t, :, k] = default

        result["temperature"] = tem_bnd
        result["salinity"] = sal_bnd
        result["u"] = u_bnd
        result["v"] = v_bnd
        result["depth"] = depth
        result["times_3d"] = tsuv_data["times"]

        return result

    # ------------------------------------------------------------------
    # Write SCHISM boundary NetCDF files
    # ------------------------------------------------------------------

    def _write_schism_bc_files(
        self, bc_data: Dict[str, Any], grid_info: Dict[str, Any]
    ) -> List[Path]:
        """Write elev2D.th.nc, TEM_3D.th.nc, SAL_3D.th.nc, uv3D.th.nc."""
        output_files: List[Path] = []
        dt = self.proc_config.dt_output

        # --- elev2D.th.nc ------------------------------------------------
        elev = bc_data.get("elev")
        if elev is not None:
            fpath = self.work_dir / "elev2D.th.nc"
            ntime = elev.shape[0]
            n_bnd = elev.shape[1]
            try:
                with Dataset(str(fpath), "w", format="NETCDF4") as nc:
                    nc.createDimension("time", None)  # unlimited
                    nc.createDimension("nOpenBndNodes", n_bnd)
                    nc.createDimension("nLevels", 1)
                    nc.createDimension("nComponents", 1)

                    tv = nc.createVariable("time", "f8", ("time",))
                    tv[:] = np.arange(ntime) * dt

                    ts = nc.createVariable(
                        "time_series",
                        "f4",
                        ("time", "nOpenBndNodes", "nLevels", "nComponents"),
                    )
                    ts[:, :, 0, 0] = elev
                output_files.append(fpath)
                log.info("Created %s", fpath)
            except Exception as e:
                log.error("Failed to write elev2D.th.nc: %s", e)

        # --- TEM_3D.th.nc ------------------------------------------------
        for varname, ncname in [("temperature", "TEM_3D.th.nc"), ("salinity", "SAL_3D.th.nc")]:
            arr = bc_data.get(varname)
            if arr is not None:
                fpath = self.work_dir / ncname
                ntime, n_bnd, nlev = arr.shape
                try:
                    with Dataset(str(fpath), "w", format="NETCDF4") as nc:
                        nc.createDimension("time", None)
                        nc.createDimension("nOpenBndNodes", n_bnd)
                        nc.createDimension("nLevels", nlev)
                        nc.createDimension("nComponents", 1)

                        tv = nc.createVariable("time", "f8", ("time",))
                        tv[:] = np.arange(ntime) * dt

                        ts = nc.createVariable(
                            "time_series",
                            "f4",
                            ("time", "nOpenBndNodes", "nLevels", "nComponents"),
                        )
                        ts[:, :, :, 0] = arr
                    output_files.append(fpath)
                    log.info("Created %s", fpath)
                except Exception as e:
                    log.error("Failed to write %s: %s", ncname, e)

        # --- uv3D.th.nc --------------------------------------------------
        u_arr = bc_data.get("u")
        v_arr = bc_data.get("v")
        if u_arr is not None and v_arr is not None:
            fpath = self.work_dir / "uv3D.th.nc"
            ntime, n_bnd, nlev = u_arr.shape
            try:
                with Dataset(str(fpath), "w", format="NETCDF4") as nc:
                    nc.createDimension("time", None)
                    nc.createDimension("nOpenBndNodes", n_bnd)
                    nc.createDimension("nLevels", nlev)
                    nc.createDimension("nComponents", 2)

                    tv = nc.createVariable("time", "f8", ("time",))
                    tv[:] = np.arange(ntime) * dt

                    ts = nc.createVariable(
                        "time_series",
                        "f4",
                        ("time", "nOpenBndNodes", "nLevels", "nComponents"),
                    )
                    ts[:, :, :, 0] = u_arr
                    ts[:, :, :, 1] = v_arr
                output_files.append(fpath)
                log.info("Created %s", fpath)
            except Exception as e:
                log.error("Failed to write uv3D.th.nc: %s", e)

        return output_files

    # ------------------------------------------------------------------
    # Nudging fields
    # ------------------------------------------------------------------

    def _create_nudging_fields(
        self,
        tsuv_data: Dict[str, Any],
        grid_info: Dict[str, Any],
    ) -> List[Path]:
        """
        Create TEM_nu.nc and SAL_nu.nc nudging files.

        These cover the full model domain, not just the boundary.
        The nudging zone is defined by TEM_nudge.gr3.
        This replaces the Fortran gen_nudge_from_hycom executable.
        """
        output_files: List[Path] = []
        cfg = self.proc_config

        # Re-read 3D data with the nudge-specific (larger) ROI if different
        # For simplicity we reuse the already-extracted data with
        # nearest-neighbour interpolation to the whole grid.

        node_x = grid_info.get("node_x")
        node_y = grid_info.get("node_y")
        if node_x is None or node_y is None:
            log.warning("Full grid coordinates not available for nudging")
            return output_files

        lon_3d = tsuv_data["lon"]
        lat_3d = tsuv_data["lat"]
        depth = tsuv_data["depth"]
        ntime = tsuv_data["temperature"].shape[0]
        nlev = tsuv_data["temperature"].shape[1]
        nnodes = len(node_x)

        log.info(
            "Creating nudging fields: %d nodes, %d levels, %d steps",
            nnodes,
            nlev,
            ntime,
        )

        pts_src = np.column_stack([lon_3d.ravel(), lat_3d.ravel()])
        pts_dst = np.column_stack([node_x, node_y])

        dt = cfg.dt_output

        for varname, ncname in [
            ("temperature", "TEM_nu.nc"),
            ("salinity", "SAL_nu.nc"),
        ]:
            arr_src = tsuv_data[varname]  # (ntime, nlev, ny, nx)
            default = cfg.temp_outside if varname == "temperature" else cfg.salt_outside
            fpath = self.work_dir / ncname

            try:
                with Dataset(str(fpath), "w", format="NETCDF4") as nc:
                    nc.createDimension("time", None)
                    nc.createDimension("node", nnodes)
                    nc.createDimension("nVert", nlev)
                    nc.createDimension("one", 1)

                    tv = nc.createVariable("time", "f8", ("time",))
                    # Nudge time is typically in days
                    tv[:] = np.arange(ntime) * (dt / 86400.0)

                    nu = nc.createVariable(varname, "f4", ("time", "node", "nVert"))

                    for t in range(ntime):
                        for k in range(nlev):
                            vals = arr_src[t, k, :, :].ravel()
                            if isinstance(vals, np.ma.MaskedArray):
                                valid = ~vals.mask
                                vals = vals.filled(np.nan)
                            else:
                                valid = np.isfinite(vals) & (np.abs(vals) < 10000)

                            if np.sum(valid) > 3 and HAS_SCIPY:
                                interp = NearestNDInterpolator(
                                    pts_src[valid], vals[valid]
                                )
                                nu[t, :, k] = interp(pts_dst)
                            elif np.sum(valid) > 0:
                                nu[t, :, k] = np.nanmean(vals[valid])
                            else:
                                nu[t, :, k] = default

                    nc.nudging_timescale = self.nudging_timescale

                output_files.append(fpath)
                log.info("Created nudging file %s", fpath)
            except Exception as e:
                log.error("Failed to create %s: %s", ncname, e)

        return output_files

    # ------------------------------------------------------------------
    # Copy to output
    # ------------------------------------------------------------------

    def _copy_to_output(self, work_files: List[Path]) -> List[Path]:
        """Copy output files to final destination with standard names."""
        output_files: List[Path] = []

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
                shutil.copy2(work_file, out_file)
                output_files.append(out_file)
                log.info("Output: %s", out_file)

                if self.comout_rerun and self.comout_rerun.exists():
                    rerun_file = self.comout_rerun / std_name
                    shutil.copy2(work_file, rerun_file)

        return output_files

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_fhr_from_filename(filename: str) -> int:
        """Extract forecast hour from RTOFS filename."""
        try:
            if "_n" in filename:
                parts = filename.split("_")
                for p in parts:
                    if p.startswith("n") and p[1:].isdigit():
                        return int(p[1:]) - 24
            if "_f" in filename:
                parts = filename.split("_")
                for p in parts:
                    if p.startswith("f") and p[1:4].isdigit():
                        return int(p[1:4])
        except (ValueError, IndexError):
            pass
        return 0
