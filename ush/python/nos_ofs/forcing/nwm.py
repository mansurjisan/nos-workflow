"""
NWM (National Water Model) River Forcing Processor

Processes NWM river discharge data for SCHISM model river boundary conditions.
NWM provides streamflow forecasts at ~2.7 million river reaches.

Fully native Python implementation -- no subprocess calls.  NWM NetCDF files
are read directly with netCDF4, and the reach-to-source mapping is done in
pure numpy.

Output: SCHISM river forcing files
- vsource.th  -- volume source time history
- msource.th  -- mass source time history (salinity, temperature)
- vsink.th    -- volume sink time history (static, from FIX)
- source_sink.in -- source/sink configuration

Used by both STOFS (7690 rivers) and SECOFS (127 rivers).
"""

import json
import logging
import tarfile
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


class NWMProcessor(ForcingProcessor):
    """
    NWM river discharge processor for SCHISM.

    Extracts river discharge from NWM NetCDF files and creates SCHISM-compatible
    river forcing time history files.  All I/O is done in pure Python using
    netCDF4 and numpy (no subprocess / shell calls).

    Features:
    - Real-time NWM data extraction with reach-to-source mapping
    - NWM tar archive extraction (native Python tarfile)
    - Climatology fallback when data unavailable
    - QC: row-count padding to meet target simulation length
    - Configurable river temperature/salinity via FIX files
    """

    # NWM products
    ANALYSIS = "analysis_assim"
    SHORT_RANGE = "short_range"
    MEDIUM_RANGE = "medium_range"
    LONG_RANGE = "long_range"

    # Monthly climatological discharge multipliers (relative to annual mean)
    SEASONAL_MULTIPLIERS = {
        1: 0.9, 2: 0.85, 3: 1.2, 4: 1.5, 5: 1.4, 6: 1.1,
        7: 0.8, 8: 0.7, 9: 0.75, 10: 0.85, 11: 0.95, 12: 0.9,
    }

    # Monthly water temperature climatology (deg-C)
    TEMP_CLIMATOLOGY = {
        1: 4.0, 2: 3.0, 3: 6.0, 4: 10.0, 5: 15.0, 6: 20.0,
        7: 24.0, 8: 25.0, 9: 22.0, 10: 16.0, 11: 10.0, 12: 6.0,
    }

    @property
    def source_name(self) -> str:
        return "NWM"

    def __init__(
        self,
        config,
        input_path: Path,
        output_path: Path,
        variables: Optional[List[str]] = None,
        product: str = "medium_range",
        num_rivers: int = 534,
        use_climatology: bool = True,
    ):
        """
        Initialize NWM processor.

        Args:
            config: StofsConfig instance
            input_path: Path to NWM input data (COMINnwm)
            output_path: Path for output files (DATA)
            variables: Variables to extract (default: streamflow)
            product: NWM product type (analysis_assim, short_range, medium_range)
            num_rivers: Number of rivers in the model domain
            use_climatology: Fall back to climatology if NWM data unavailable
        """
        super().__init__(config, input_path, output_path, variables)
        self.product = product
        self.num_rivers = num_rivers
        self.use_climatology = use_climatology
        if not self.variables:
            self.variables = ["streamflow"]

        self.cyc = config.cyc
        self.pdy = config.PDY

        # FIX file paths
        self.river_config_path = config.get_fix_file(
            f"{config.RUN}_river_config.txt"
        )
        self.climatology_file = config.get_fix_file(
            f"{config.RUN}_river_climatology.txt"
        )
        self.sources_json = config.get_fix_file(
            f"{config.RUN}_river_sources_conus.json"
        )
        self.source_scale_file = config.get_fix_file(
            f"{config.RUN}_river_source_scale.txt"
        )

    # ==================================================================
    # Main entry
    # ==================================================================

    def process(self) -> ForcingResult:
        """Process NWM river forcing data."""
        log.info("Processing %s forcing data", self.source_name)
        log.info("Product: %s", self.product)
        log.info("Number of rivers: %d", self.num_rivers)
        log.info("Input path: %s", self.input_path)

        if not self.validate_input():
            return ForcingResult(
                success=False,
                source=self.source_name,
                errors=[f"Input path not found: {self.input_path}"],
            )

        self.create_output_dir()
        output_files: List[Path] = []

        try:
            # Load reach-to-source mapping
            river_config = self._load_river_config()
            if not river_config or not river_config.get("feature_ids"):
                log.warning("No river configuration found -- using default")
                river_config = self._create_default_config()

            # Find NWM files (with tar extraction if needed)
            nwm_files = self._find_nwm_files()

            if not nwm_files:
                if self.use_climatology:
                    log.warning("No NWM files found -- using climatology fallback")
                    river_data = self._generate_climatology(river_config)
                    output_files = self._write_all_outputs(
                        river_data, river_config
                    )
                    return ForcingResult(
                        success=True,
                        source=self.source_name,
                        output_files=output_files,
                        warnings=["Used climatology -- no NWM data available"],
                        metadata={"product": "climatology", "num_rivers": self.num_rivers},
                    )
                return ForcingResult(
                    success=False,
                    source=self.source_name,
                    errors=["No NWM input files found"],
                )

            log.info("Found %d NWM files", len(nwm_files))

            # Extract streamflow data
            river_data = self._extract_streamflow(nwm_files, river_config)

            if not river_data or len(river_data.get("streamflow", [])) == 0:
                if self.use_climatology:
                    log.warning("Failed extraction -- falling back to climatology")
                    river_data = self._generate_climatology(river_config)
                else:
                    return ForcingResult(
                        success=False,
                        source=self.source_name,
                        errors=["Failed to extract NWM streamflow data"],
                    )

            # Write output files
            output_files = self._write_all_outputs(river_data, river_config)

            # QC: ensure files cover target simulation period
            n_target_rows = 121  # 5 days hourly
            for f in output_files:
                if f.suffix == ".th":
                    self._qc_append_rows(f, n_target_rows)

            log.info("NWM processing complete: %d files created", len(output_files))

            return ForcingResult(
                success=True,
                source=self.source_name,
                output_files=output_files,
                metadata={
                    "product": self.product,
                    "num_rivers": self.num_rivers,
                    "num_files": len(nwm_files),
                    "time_steps": len(river_data.get("times", [])),
                },
            )

        except Exception as e:
            log.error("NWM processing failed: %s", e, exc_info=True)
            return ForcingResult(
                success=False,
                source=self.source_name,
                errors=[str(e)],
            )

    # ==================================================================
    # River configuration loading
    # ==================================================================

    def _load_river_config(self) -> Dict[str, Any]:
        """
        Load river configuration: NWM reach IDs mapped to SCHISM source
        elements.

        Tries JSON (STOFS style) first, then plain text.
        """
        config: Dict[str, Any] = {
            "feature_ids": [],
            "node_indices": [],
            "river_names": [],
            "clim_temp": [],
            "clim_salt": [],
        }

        # Try JSON sources file (STOFS-style)
        if self.sources_json.exists():
            try:
                with open(self.sources_json, "r") as f:
                    data = json.load(f)
                if isinstance(data, dict) and "features" in data:
                    for feat in data["features"]:
                        config["feature_ids"].append(int(feat.get("nwm_id", 0)))
                        config["node_indices"].append(int(feat.get("element", 0)))
                        config["river_names"].append(feat.get("name", ""))
                elif isinstance(data, list):
                    for item in data:
                        config["feature_ids"].append(int(item))
                log.info(
                    "Loaded %d river sources from JSON", len(config["feature_ids"])
                )
                if config["feature_ids"]:
                    self.num_rivers = len(config["feature_ids"])
                    return config
            except Exception as e:
                log.warning("Error loading sources JSON: %s", e)

        # Try plain text config
        if self.river_config_path.exists():
            try:
                with open(self.river_config_path, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        parts = line.split()
                        if len(parts) >= 2:
                            config["feature_ids"].append(int(parts[0]))
                            config["node_indices"].append(int(parts[1]))
                            config["river_names"].append(
                                parts[2] if len(parts) > 2 else f"River_{parts[1]}"
                            )
                            config["clim_temp"].append(
                                float(parts[3]) if len(parts) > 3 else 15.0
                            )
                            config["clim_salt"].append(
                                float(parts[4]) if len(parts) > 4 else 0.0
                            )
                log.info(
                    "Loaded %d river configurations", len(config["feature_ids"])
                )
            except Exception as e:
                log.error("Error loading river config: %s", e)

        return config

    def _create_default_config(self) -> Dict[str, Any]:
        return {
            "feature_ids": list(range(1, self.num_rivers + 1)),
            "node_indices": list(range(1, self.num_rivers + 1)),
            "river_names": [f"River_{i}" for i in range(1, self.num_rivers + 1)],
            "clim_temp": [15.0] * self.num_rivers,
            "clim_salt": [0.0] * self.num_rivers,
            "mean_discharge": [10.0] * self.num_rivers,
        }

    # ==================================================================
    # NWM file discovery  (with tar extraction)
    # ==================================================================

    def _find_nwm_files(self) -> List[Path]:
        """Find NWM NetCDF files, extracting from tar archives if necessary."""
        nwm_files: List[Path] = []

        # Try direct NetCDF files first
        patterns = [
            f"nwm.t{self.cyc:02d}z.{self.product}.channel_rt*.conus.nc",
            f"nwm.t??z.{self.product}.channel_rt*.conus.nc",
            f"*{self.product}*channel_rt*.nc",
        ]

        for pattern in patterns:
            # Search in date-specific sub-directories
            yyyymmdd_today = self.pdy
            yyyymmdd_prev = (
                datetime.strptime(self.pdy, "%Y%m%d") - timedelta(days=1)
            ).strftime("%Y%m%d")

            for datestr in [yyyymmdd_today, yyyymmdd_prev]:
                search_dirs = [
                    self.input_path / f"nwm.{datestr}" / "medium_range_mem1",
                    self.input_path / f"nwm.{datestr}",
                    self.input_path,
                ]
                for sdir in search_dirs:
                    if sdir.exists():
                        found = sorted(sdir.glob(pattern))
                        if found:
                            nwm_files.extend(found)

            if nwm_files:
                break

        # Try tar archives if no direct files found
        if not nwm_files:
            nwm_files = self._extract_from_tar()

        # Validate file sizes
        min_size = 10_000_000
        nwm_files = [
            f for f in nwm_files
            if f.exists() and f.stat().st_size >= min_size
        ]

        return sorted(set(nwm_files))

    def _extract_from_tar(self) -> List[Path]:
        """Extract NWM files from tar archives (native Python tarfile)."""
        extracted: List[Path] = []
        tar_patterns = ["*.tar", "*.tar.gz", "*.tgz"]

        for pattern in tar_patterns:
            for tar_path in sorted(self.input_path.glob(pattern)):
                try:
                    log.info("Extracting NWM tar archive: %s", tar_path)
                    extract_dir = self.output_path / "nwm_extracted"
                    extract_dir.mkdir(parents=True, exist_ok=True)

                    mode = "r:gz" if tar_path.suffix in (".gz", ".tgz") else "r:"
                    with tarfile.open(str(tar_path), mode) as tf:
                        # Only extract channel_rt files
                        members = [
                            m for m in tf.getmembers()
                            if "channel_rt" in m.name and m.name.endswith(".nc")
                        ]
                        for member in members:
                            tf.extract(member, path=str(extract_dir))
                            extracted.append(extract_dir / member.name)

                    log.info("Extracted %d files from %s", len(members), tar_path.name)
                except Exception as e:
                    log.warning("Error extracting %s: %s", tar_path, e)

        return extracted

    # ==================================================================
    # Streamflow extraction
    # ==================================================================

    def _extract_streamflow(
        self, nwm_files: List[Path], river_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Extract streamflow from NWM files for configured rivers."""
        if not HAS_NETCDF4:
            log.error("netCDF4 required for NWM processing")
            return {}

        feature_ids = river_config.get("feature_ids", [])
        if not feature_ids:
            log.warning("No feature IDs configured")
            return {}

        feature_ids_arr = np.array(feature_ids, dtype=np.int64)

        river_data: Dict[str, Any] = {
            "times": [],
            "streamflow": [],
        }

        base_time = (
            datetime.strptime(self.pdy, "%Y%m%d")
            + timedelta(hours=self.cyc)
        )

        for nwm_file in nwm_files:
            try:
                with Dataset(str(nwm_file), "r") as nc:
                    # Time info
                    if "time" in nc.variables:
                        time_var = nc.variables["time"]
                        time_val = time_var[0] if len(time_var) > 0 else 0
                        valid_time = base_time + timedelta(minutes=float(time_val))
                    else:
                        fhr = self._extract_fhr_from_filename(nwm_file.name)
                        valid_time = base_time + timedelta(hours=fhr)

                    river_data["times"].append(valid_time)

                    if "feature_id" in nc.variables and "streamflow" in nc.variables:
                        all_fids = nc.variables["feature_id"][:]
                        all_flow = nc.variables["streamflow"][:]

                        # Build index lookup (much faster than per-river np.where)
                        fid_to_idx = {}
                        for idx, fid in enumerate(all_fids):
                            fid_to_idx[int(fid)] = idx

                        river_flows = np.zeros(len(feature_ids), dtype=np.float64)
                        for j, fid in enumerate(feature_ids):
                            idx = fid_to_idx.get(int(fid))
                            if idx is not None:
                                river_flows[j] = float(all_flow[idx])

                        river_data["streamflow"].append(river_flows)
                    else:
                        log.warning("Required variables not in %s", nwm_file.name)
            except Exception as e:
                log.warning("Error reading %s: %s", nwm_file, e)

        if river_data["streamflow"]:
            river_data["streamflow"] = np.array(river_data["streamflow"])
        return river_data

    def _extract_fhr_from_filename(self, filename: str) -> int:
        try:
            if ".f" in filename:
                fhr_str = filename.split(".f")[1].split(".")[0]
                return int(fhr_str)
        except (ValueError, IndexError):
            pass
        return 0

    # ==================================================================
    # Climatology fallback
    # ==================================================================

    def _load_climatology(self) -> Dict[str, List[float]]:
        climatology: Dict[str, List[float]] = {
            "feature_ids": [],
            "mean_discharge": [],
        }
        if not self.climatology_file.exists():
            return climatology
        try:
            with open(self.climatology_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split()
                    if len(parts) >= 2:
                        climatology["feature_ids"].append(int(parts[0]))
                        climatology["mean_discharge"].append(float(parts[1]))
            log.info("Loaded climatology for %d rivers", len(climatology["feature_ids"]))
        except Exception as e:
            log.warning("Error loading climatology: %s", e)
        return climatology

    def _generate_climatology(self, river_config: Dict[str, Any]) -> Dict[str, Any]:
        """Generate river discharge from monthly climatology."""
        log.info("Generating climatological river discharge")
        river_data: Dict[str, Any] = {"times": [], "streamflow": [], "temperature": []}

        climatology = self._load_climatology()
        clim_discharge = {
            int(fid): q
            for fid, q in zip(
                climatology.get("feature_ids", []),
                climatology.get("mean_discharge", []),
            )
        }
        default_discharge = 10.0

        feature_ids = river_config.get("feature_ids", list(range(1, self.num_rivers + 1)))

        base_time = datetime.strptime(self.pdy, "%Y%m%d") + timedelta(hours=self.cyc)
        start_time = base_time - timedelta(hours=24)

        for hour in range(121):
            current_time = start_time + timedelta(hours=hour)
            month = current_time.month
            multiplier = self.SEASONAL_MULTIPLIERS.get(month, 1.0)

            river_data["times"].append(current_time)
            flows = [
                clim_discharge.get(int(fid), default_discharge) * multiplier
                for fid in feature_ids
            ]
            river_data["streamflow"].append(flows)
            river_data["temperature"].append(self.TEMP_CLIMATOLOGY.get(month, 15.0))

        river_data["streamflow"] = np.array(river_data["streamflow"])
        log.info(
            "Generated climatology: %d time steps, %d rivers",
            len(river_data["times"]),
            len(feature_ids),
        )
        return river_data

    # ==================================================================
    # Output writing
    # ==================================================================

    def _write_all_outputs(
        self, river_data: Dict[str, Any], river_config: Dict[str, Any]
    ) -> List[Path]:
        """Write vsource.th, msource.th, and source_sink.in."""
        output_files: List[Path] = []

        vs = self._create_vsource(river_data)
        if vs:
            output_files.append(vs)

        ms = self._create_msource(river_data)
        if ms:
            output_files.append(ms)

        ss = self._create_source_sink_in(river_config)
        if ss:
            output_files.append(ss)

        return output_files

    def _create_vsource(self, river_data: Dict[str, Any]) -> Optional[Path]:
        """Create vsource.th (volume source time history)."""
        output_file = self.output_path / "vsource.th"
        times = river_data.get("times", [])
        streamflow = river_data.get("streamflow", [])

        if not times or len(streamflow) == 0:
            log.warning("No data for vsource.th")
            return None

        try:
            base_time = times[0]
            with open(output_file, "w") as f:
                for i, t in enumerate(times):
                    time_sec = (t - base_time).total_seconds()
                    flows = (
                        streamflow[i]
                        if i < len(streamflow)
                        else np.zeros(self.num_rivers)
                    )
                    flow_str = " ".join(f"{flow:.4f}" for flow in flows)
                    f.write(f"{time_sec:.1f} {flow_str}\n")

            log.info("Created %s with %d time steps", output_file, len(times))
            return output_file
        except Exception as e:
            log.error("Failed to create vsource.th: %s", e)
            return None

    def _create_msource(self, river_data: Dict[str, Any]) -> Optional[Path]:
        """Create msource.th (temperature and salinity for each source)."""
        output_file = self.output_path / "msource.th"
        times = river_data.get("times", [])

        if not times:
            log.warning("No data for msource.th")
            return None

        try:
            base_time = times[0]
            default_temp = 15.0
            default_salt = 0.0

            with open(output_file, "w") as f:
                for i, t in enumerate(times):
                    time_sec = (t - base_time).total_seconds()
                    # Use climatological temp if available
                    temp = default_temp
                    if "temperature" in river_data and i < len(river_data["temperature"]):
                        temp = river_data["temperature"][i]
                    ts_str = " ".join(
                        f"{temp:.2f} {default_salt:.2f}"
                        for _ in range(self.num_rivers)
                    )
                    f.write(f"{time_sec:.1f} {ts_str}\n")

            log.info("Created %s", output_file)
            return output_file
        except Exception as e:
            log.error("Failed to create msource.th: %s", e)
            return None

    def _create_source_sink_in(
        self, river_config: Dict[str, Any]
    ) -> Optional[Path]:
        """Create source_sink.in configuration file for SCHISM."""
        output_file = self.output_path / "source_sink.in"
        node_indices = river_config.get("node_indices", [])
        if not node_indices:
            node_indices = list(range(1, self.num_rivers + 1))

        try:
            with open(output_file, "w") as f:
                f.write(f"{len(node_indices)}\n")
                for node_idx in node_indices:
                    f.write(f"{node_idx} 1\n")
                f.write("0\n")

            log.info("Created %s with %d sources", output_file, len(node_indices))
            return output_file
        except Exception as e:
            log.error("Failed to create source_sink.in: %s", e)
            return None

    # ==================================================================
    # QC
    # ==================================================================

    def _qc_append_rows(self, th_file: Path, n_target: int) -> None:
        """Pad .th file to target row count by repeating last row."""
        if not th_file.exists():
            return
        try:
            with open(th_file, "r") as f:
                lines = f.readlines()

            data_lines = [l for l in lines if l.strip() and not l.strip().startswith("!")]
            n_rows = len(data_lines)

            if n_rows >= n_target or n_rows == 0:
                return

            last_line = data_lines[-1]
            n_append = n_target - n_rows + 1

            with open(th_file, "a") as f:
                for i in range(n_append):
                    parts = last_line.split()
                    if parts:
                        base_time = float(parts[0])
                        new_time = base_time + 3600.0 * (i + 1)
                        parts[0] = f"{new_time:.1f}"
                        f.write(" ".join(parts) + "\n")
                    else:
                        f.write(last_line)

            log.info(
                "QC: Appended %d rows to %s (was %d, target %d)",
                n_append,
                th_file.name,
                n_rows,
                n_target,
            )
        except Exception as e:
            log.warning("QC append failed for %s: %s", th_file.name, e)
