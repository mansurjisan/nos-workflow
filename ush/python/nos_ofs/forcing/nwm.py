"""
NWM (National Water Model) River Forcing Processor

Processes NWM river discharge data for SCHISM model river boundary conditions.
NWM provides streamflow forecasts at ~2.7 million river reaches.

Output: SCHISM river forcing files
- vsource.th - volume source time history
- msource.th - mass source time history (salinity, temperature)
- source_sink.in - source/sink configuration

Used by both STOFS (534 rivers) and SECOFS (127 rivers).
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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
    river forcing time history files.

    Features:
    - Real-time NWM data extraction
    - Climatology fallback when data unavailable
    - Configurable river temperature/salinity
    """

    # NWM products
    ANALYSIS = "analysis_assim"
    SHORT_RANGE = "short_range"
    MEDIUM_RANGE = "medium_range"
    LONG_RANGE = "long_range"

    # Monthly climatological discharge multipliers (relative to annual mean)
    # Based on typical seasonal patterns for US Atlantic coast rivers
    SEASONAL_MULTIPLIERS = {
        1: 0.9,   # January - winter low
        2: 0.85,  # February
        3: 1.2,   # March - spring rise
        4: 1.5,   # April - spring peak
        5: 1.4,   # May
        6: 1.1,   # June
        7: 0.8,   # July - summer low
        8: 0.7,   # August
        9: 0.75,  # September
        10: 0.85, # October
        11: 0.95, # November
        12: 0.9,  # December
    }

    # Monthly water temperature climatology (Â°C)
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

        # River configuration file path
        self.river_config = config.get_fix_file(f"{config.RUN}_river_config.txt")

        # Climatology file (contains mean annual discharge per river)
        self.climatology_file = config.get_fix_file(f"{config.RUN}_river_climatology.txt")

    def process(self) -> ForcingResult:
        """
        Process NWM river forcing data.

        Returns:
            ForcingResult with processed files
        """
        log.info(f"Processing {self.source_name} forcing data")
        log.info(f"Product: {self.product}")
        log.info(f"Number of rivers: {self.num_rivers}")
        log.info(f"Input path: {self.input_path}")

        if not self.validate_input():
            return ForcingResult(
                success=False,
                source=self.source_name,
                errors=[f"Input path not found: {self.input_path}"],
            )

        self.create_output_dir()
        output_files = []

        try:
            # Load river configuration (NWM reach IDs mapped to SCHISM nodes)
            river_config = self._load_river_config()

            if not river_config:
                log.warning("No river configuration found - using default")
                river_config = self._create_default_config()

            # Find NWM files
            nwm_files = self._find_nwm_files()

            if not nwm_files:
                if self.use_climatology:
                    log.warning("No NWM files found - using climatology fallback")
                    river_data = self._generate_climatology(river_config)
                    if river_data:
                        vsource_file = self._create_vsource(river_data)
                        if vsource_file:
                            output_files.append(vsource_file)
                        msource_file = self._create_msource(river_data)
                        if msource_file:
                            output_files.append(msource_file)
                        source_sink_file = self._create_source_sink_in(river_config)
                        if source_sink_file:
                            output_files.append(source_sink_file)

                        return ForcingResult(
                            success=True,
                            source=self.source_name,
                            output_files=output_files,
                            warnings=["Used climatology - no NWM data available"],
                            metadata={
                                "product": "climatology",
                                "num_rivers": self.num_rivers,
                            },
                        )
                return ForcingResult(
                    success=False,
                    source=self.source_name,
                    errors=["No NWM input files found"],
                )

            log.info(f"Found {len(nwm_files)} NWM files")

            # Extract streamflow data
            river_data = self._extract_streamflow(nwm_files, river_config)

            if not river_data:
                return ForcingResult(
                    success=False,
                    source=self.source_name,
                    errors=["Failed to extract NWM streamflow data"],
                )

            # Create SCHISM river forcing files
            vsource_file = self._create_vsource(river_data)
            if vsource_file:
                output_files.append(vsource_file)

            msource_file = self._create_msource(river_data)
            if msource_file:
                output_files.append(msource_file)

            source_sink_file = self._create_source_sink_in(river_config)
            if source_sink_file:
                output_files.append(source_sink_file)

            # QC: Ensure files have target number of rows
            n_target_rows = 121  # 5 days hourly
            if vsource_file:
                self._qc_append_rows(vsource_file, n_target_rows)
            if msource_file:
                self._qc_append_rows(msource_file, n_target_rows)

            log.info(f"NWM processing complete: {len(output_files)} files created")

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
            log.error(f"NWM processing failed: {e}")
            import traceback
            log.error(traceback.format_exc())
            return ForcingResult(
                success=False,
                source=self.source_name,
                errors=[str(e)],
            )

    def _load_river_config(self) -> Dict[str, any]:
        """
        Load river configuration mapping NWM reach IDs to SCHISM nodes.

        The configuration file contains:
        - NWM feature_id (reach ID)
        - SCHISM node index
        - River name
        - Climatological values

        Returns:
            Dictionary with river configuration
        """
        config = {
            "feature_ids": [],
            "node_indices": [],
            "river_names": [],
            "clim_temp": [],  # Climatological temperature
            "clim_salt": [],  # Climatological salinity (usually 0 for rivers)
        }

        if not self.river_config.exists():
            log.warning(f"River config not found: {self.river_config}")
            return config

        try:
            with open(self.river_config, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue

                    parts = line.split()
                    if len(parts) >= 4:
                        config["feature_ids"].append(int(parts[0]))
                        config["node_indices"].append(int(parts[1]))
                        config["river_names"].append(parts[2] if len(parts) > 2 else f"River_{parts[1]}")
                        config["clim_temp"].append(float(parts[3]) if len(parts) > 3 else 15.0)
                        config["clim_salt"].append(float(parts[4]) if len(parts) > 4 else 0.0)

            log.info(f"Loaded {len(config['feature_ids'])} river configurations")

        except Exception as e:
            log.error(f"Error loading river config: {e}")

        return config

    def _create_default_config(self) -> Dict[str, any]:
        """Create default river configuration if none exists."""
        return {
            "feature_ids": list(range(1, self.num_rivers + 1)),
            "node_indices": list(range(1, self.num_rivers + 1)),
            "river_names": [f"River_{i}" for i in range(1, self.num_rivers + 1)],
            "clim_temp": [15.0] * self.num_rivers,
            "clim_salt": [0.0] * self.num_rivers,
            "mean_discharge": [10.0] * self.num_rivers,  # mÂ³/s default
        }

    def _load_climatology(self) -> Dict[str, List[float]]:
        """
        Load river discharge climatology from FIX file.

        Returns:
            Dictionary with mean annual discharge per river
        """
        climatology = {
            "feature_ids": [],
            "mean_discharge": [],  # Mean annual discharge in mÂ³/s
        }

        if not self.climatology_file.exists():
            log.debug(f"Climatology file not found: {self.climatology_file}")
            return climatology

        try:
            with open(self.climatology_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    parts = line.split()
                    if len(parts) >= 2:
                        climatology["feature_ids"].append(int(parts[0]))
                        climatology["mean_discharge"].append(float(parts[1]))

            log.info(f"Loaded climatology for {len(climatology['feature_ids'])} rivers")

        except Exception as e:
            log.warning(f"Error loading climatology: {e}")

        return climatology

    def _generate_climatology(self, river_config: Dict[str, any]) -> Dict[str, any]:
        """
        Generate river discharge from climatology when NWM data unavailable.

        Uses monthly seasonal multipliers applied to mean annual discharge.

        Args:
            river_config: River configuration dictionary

        Returns:
            Dictionary with times and streamflow data
        """
        log.info("Generating climatological river discharge")

        river_data = {
            "times": [],
            "streamflow": [],
            "temperature": [],
        }

        # Load mean annual discharge from climatology file or use defaults
        climatology = self._load_climatology()

        # Create a mapping from feature_id to mean discharge
        clim_discharge = {}
        for i, fid in enumerate(climatology.get("feature_ids", [])):
            clim_discharge[fid] = climatology["mean_discharge"][i]

        # Default discharge for rivers not in climatology
        default_discharge = 10.0  # mÂ³/s

        # Get feature IDs from river config
        feature_ids = river_config.get("feature_ids", [])
        if not feature_ids:
            feature_ids = list(range(1, self.num_rivers + 1))

        # Generate 5-day time series (120 hours + 1)
        base_time = datetime.strptime(self.pdy, "%Y%m%d") + timedelta(hours=self.cyc)
        start_time = base_time - timedelta(hours=24)  # Nowcast begin

        for hour in range(121):  # 0 to 120 hours
            current_time = start_time + timedelta(hours=hour)
            month = current_time.month

            river_data["times"].append(current_time)

            # Get seasonal multiplier for this month
            multiplier = self.SEASONAL_MULTIPLIERS.get(month, 1.0)

            # Calculate discharge for each river
            river_flows = []
            for fid in feature_ids:
                mean_q = clim_discharge.get(fid, default_discharge)
                seasonal_q = mean_q * multiplier
                river_flows.append(seasonal_q)

            river_data["streamflow"].append(river_flows)

            # Temperature from climatology
            temp = self.TEMP_CLIMATOLOGY.get(month, 15.0)
            river_data["temperature"].append(temp)

        # Convert to numpy array
        river_data["streamflow"] = np.array(river_data["streamflow"])

        log.info(f"Generated climatology: {len(river_data['times'])} time steps, {len(feature_ids)} rivers")

        return river_data

    def _qc_append_rows(self, th_file: Path, n_target: int) -> None:
        """
        QC check: append last row if file has fewer rows than target.

        This ensures the .th file covers the full forecast period.
        Shell script logic (lines 314-365):
            if N_rows < N_list_target:
                append last line until N_rows == N_list_target

        Args:
            th_file: Path to .th file (vsource.th or msource.th)
            n_target: Target number of rows
        """
        if not th_file.exists():
            return

        try:
            with open(th_file, 'r') as f:
                lines = f.readlines()

            # Filter out comment lines
            data_lines = [l for l in lines if l.strip() and not l.strip().startswith('!')]
            n_rows = len(data_lines)

            if n_rows >= n_target:
                log.debug(f"{th_file.name}: {n_rows} rows >= target {n_target}")
                return

            if n_rows == 0:
                log.warning(f"{th_file.name}: no data rows found")
                return

            # Get last data line
            last_line = data_lines[-1]

            # Append to reach target
            n_append = n_target - n_rows + 1

            with open(th_file, 'a') as f:
                for i in range(n_append):
                    # Update time value in last line
                    parts = last_line.split()
                    if parts:
                        # Increment time by 3600s (hourly) for each appended line
                        base_time = float(parts[0])
                        new_time = base_time + 3600.0 * (i + 1)
                        parts[0] = f"{new_time:.1f}"
                        f.write(" ".join(parts) + "\n")
                    else:
                        f.write(last_line)

            log.info(f"QC: Appended {n_append} rows to {th_file.name} (was {n_rows}, target {n_target})")

        except Exception as e:
            log.warning(f"QC append failed for {th_file.name}: {e}")

    def _find_nwm_files(self) -> List[Path]:
        """Find NWM NetCDF files."""
        nwm_files = []

        # NWM file pattern varies by product
        # medium_range: nwm.tHHz.medium_range.channel_rt.fHHH.conus.nc
        patterns = [
            f"nwm.t{self.cyc:02d}z.{self.product}.channel_rt.f*.conus.nc",
            f"nwm.t{self.cyc:02d}z.{self.product}.channel_rt*.nc",
            f"*{self.product}*channel_rt*.nc",
        ]

        for pattern in patterns:
            found = sorted(self.input_path.glob(pattern))
            if found:
                nwm_files = found
                break

        return nwm_files

    def _extract_streamflow(
        self, nwm_files: List[Path], river_config: Dict[str, any]
    ) -> Dict[str, any]:
        """
        Extract streamflow from NWM files for configured rivers.

        Args:
            nwm_files: List of NWM NetCDF files
            river_config: River configuration dictionary

        Returns:
            Dictionary with times and streamflow data
        """
        if not HAS_NETCDF4:
            log.error("netCDF4 required for NWM processing")
            return {}

        feature_ids = river_config.get("feature_ids", [])
        if not feature_ids:
            log.warning("No feature IDs configured")
            return {}

        river_data = {
            "times": [],
            "streamflow": [],  # Shape: (ntimes, nrivers)
        }

        base_time = datetime.strptime(self.pdy, "%Y%m%d") + timedelta(hours=self.cyc)

        for nwm_file in nwm_files:
            try:
                nc = Dataset(nwm_file, 'r')

                # Get time info
                if 'time' in nc.variables:
                    time_var = nc.variables['time']
                    time_val = time_var[0] if len(time_var) > 0 else 0
                    # NWM time is usually minutes since model start
                    valid_time = base_time + timedelta(minutes=float(time_val))
                else:
                    # Extract time from filename
                    fhr = self._extract_fhr_from_filename(nwm_file.name)
                    valid_time = base_time + timedelta(hours=fhr)

                river_data["times"].append(valid_time)

                # Get feature_id and streamflow
                if 'feature_id' in nc.variables and 'streamflow' in nc.variables:
                    all_feature_ids = nc.variables['feature_id'][:]
                    all_streamflow = nc.variables['streamflow'][:]

                    # Extract streamflow for our rivers
                    river_flows = []
                    for fid in feature_ids:
                        idx = np.where(all_feature_ids == fid)[0]
                        if len(idx) > 0:
                            flow = all_streamflow[idx[0]]
                            # Convert to mÂ³/s if needed (NWM is typically in mÂ³/s)
                            river_flows.append(float(flow))
                        else:
                            # Use climatological value or 0
                            river_flows.append(0.0)

                    river_data["streamflow"].append(river_flows)
                else:
                    log.warning(f"Required variables not found in {nwm_file.name}")

                nc.close()

            except Exception as e:
                log.warning(f"Error reading {nwm_file}: {e}")
                continue

        # Convert to numpy arrays
        if river_data["streamflow"]:
            river_data["streamflow"] = np.array(river_data["streamflow"])

        return river_data

    def _extract_fhr_from_filename(self, filename: str) -> int:
        """Extract forecast hour from NWM filename."""
        try:
            # Pattern: nwm.tHHz.product.channel_rt.fHHH.conus.nc
            if '.f' in filename:
                fhr_str = filename.split('.f')[1].split('.')[0]
                return int(fhr_str)
        except (ValueError, IndexError):
            pass
        return 0

    def _create_vsource(self, river_data: Dict[str, any]) -> Optional[Path]:
        """
        Create vsource.th (volume source time history) file.

        Format:
        time_seconds  flow_river1  flow_river2  ...
        """
        output_file = self.output_path / "vsource.th"

        times = river_data.get("times", [])
        streamflow = river_data.get("streamflow", [])

        if not times or len(streamflow) == 0:
            log.warning("No data for vsource.th")
            return None

        try:
            base_time = times[0]

            with open(output_file, 'w') as f:
                for i, t in enumerate(times):
                    # Time in seconds since start
                    time_sec = (t - base_time).total_seconds()

                    # Write time and all river flows
                    flows = streamflow[i] if i < len(streamflow) else [0.0] * self.num_rivers
                    flow_str = " ".join(f"{flow:.4f}" for flow in flows)
                    f.write(f"{time_sec:.1f} {flow_str}\n")

            log.info(f"Created {output_file} with {len(times)} time steps")
            return output_file

        except Exception as e:
            log.error(f"Failed to create vsource.th: {e}")
            return None

    def _create_msource(self, river_data: Dict[str, any]) -> Optional[Path]:
        """
        Create msource.th (mass source time history) file.

        Contains temperature and salinity for each river source.
        Format:
        time_seconds  temp1 salt1  temp2 salt2  ...
        """
        output_file = self.output_path / "msource.th"

        times = river_data.get("times", [])

        if not times:
            log.warning("No data for msource.th")
            return None

        try:
            base_time = times[0]

            # Use climatological values (rivers are fresh, typical temp)
            default_temp = 15.0  # Â°C
            default_salt = 0.0   # PSU

            with open(output_file, 'w') as f:
                for t in times:
                    time_sec = (t - base_time).total_seconds()

                    # Write time and T/S for each river
                    ts_str = " ".join(f"{default_temp:.2f} {default_salt:.2f}"
                                     for _ in range(self.num_rivers))
                    f.write(f"{time_sec:.1f} {ts_str}\n")

            log.info(f"Created {output_file}")
            return output_file

        except Exception as e:
            log.error(f"Failed to create msource.th: {e}")
            return None

    def _create_source_sink_in(self, river_config: Dict[str, any]) -> Optional[Path]:
        """
        Create source_sink.in configuration file for SCHISM.

        Format:
        num_sources
        node_index  type
        ...
        """
        output_file = self.output_path / "source_sink.in"

        node_indices = river_config.get("node_indices", [])

        if not node_indices:
            # Use default indices
            node_indices = list(range(1, self.num_rivers + 1))

        try:
            with open(output_file, 'w') as f:
                # Number of sources
                f.write(f"{len(node_indices)}\n")

                # Source elements
                for i, node_idx in enumerate(node_indices):
                    # Format: element_index, type (1=volume source)
                    f.write(f"{node_idx} 1\n")

                # Number of sinks (usually 0)
                f.write("0\n")

            log.info(f"Created {output_file} with {len(node_indices)} sources")
            return output_file

        except Exception as e:
            log.error(f"Failed to create source_sink.in: {e}")
            return None
