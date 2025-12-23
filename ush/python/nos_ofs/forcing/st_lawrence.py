"""
St. Lawrence River Forcing Processor

Processes St. Lawrence River discharge data for STOFS 3D Atlantic.
The St. Lawrence River enters the Atlantic domain through the Gulf of St. Lawrence
and requires special handling separate from NWM (which doesn't cover Canada).

Data sources:
- DCOM: Canadian hydrological data
- Climatology: Historical average flows

Output: Additional river source entries for vsource.th
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from ..base import ForcingProcessor, ForcingResult

log = logging.getLogger(__name__)


class StLawrenceProcessor(ForcingProcessor):
    """
    St. Lawrence River discharge processor.

    The St. Lawrence River is the largest river on the US/Canada Atlantic
    coast by volume (average ~10,000 mÂ³/s) and has significant impact on
    the circulation and salinity in the Gulf of St. Lawrence.

    Sources:
    - Real-time: Canadian Water Survey data via DCOM
    - Backup: Climatological discharge values

    Output is merged with NWM river forcing in vsource.th.
    """

    # St. Lawrence River configuration
    # Average discharge ~ 10,000 mÂ³/s, varies seasonally 7,000-14,000 mÂ³/s
    CLIMATOLOGY = {
        1: 8500.0,   # January
        2: 8000.0,   # February
        3: 8500.0,   # March
        4: 11000.0,  # April (spring melt)
        5: 13000.0,  # May (peak)
        6: 12000.0,  # June
        7: 10500.0,  # July
        8: 9500.0,   # August
        9: 9000.0,   # September
        10: 9000.0,  # October
        11: 9000.0,  # November
        12: 8500.0,  # December
    }

    # Default location (SCHISM node) for St. Lawrence discharge
    DEFAULT_NODE_INDEX = 1  # Placeholder - set from FIX file

    # Water temperature climatology (Â°C)
    TEMP_CLIMATOLOGY = {
        1: 1.0, 2: 0.5, 3: 1.0, 4: 4.0, 5: 8.0, 6: 14.0,
        7: 18.0, 8: 19.0, 9: 16.0, 10: 11.0, 11: 6.0, 12: 2.0,
    }

    @property
    def source_name(self) -> str:
        return "St_Lawrence"

    def __init__(
        self,
        config,
        input_path: Path,
        output_path: Path,
        variables: Optional[List[str]] = None,
        use_climatology: bool = True,
    ):
        """
        Initialize St. Lawrence processor.

        Args:
            config: StofsConfig instance
            input_path: Path to DCOM data
            output_path: Path for output files
            variables: Variables to process (default: discharge)
            use_climatology: Whether to use climatology as backup
        """
        super().__init__(config, input_path, output_path, variables)
        self.use_climatology = use_climatology
        if not self.variables:
            self.variables = ["discharge"]

        self.cyc = config.cyc
        self.pdy = config.PDY

        # Load St. Lawrence configuration from FIX
        self.stl_config = self._load_stl_config()

    def _load_stl_config(self) -> Dict:
        """
        Load St. Lawrence River configuration from FIX directory.

        Returns:
            Dictionary with node locations and mapping info
        """
        config = {
            "node_indices": [],
            "lons": [],
            "lats": [],
            "names": [],
        }

        # Try to load St. Lawrence config file
        stl_file = self.config.get_fix_file(f"{self.config.RUN}_st_lawrence.txt")

        if stl_file.exists():
            try:
                with open(stl_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith('#'):
                            continue
                        parts = line.split()
                        if len(parts) >= 3:
                            config["node_indices"].append(int(parts[0]))
                            config["lons"].append(float(parts[1]))
                            config["lats"].append(float(parts[2]))
                            config["names"].append(parts[3] if len(parts) > 3 else "StLawrence")

                log.info(f"Loaded St. Lawrence config: {len(config['node_indices'])} outlets")
            except Exception as e:
                log.warning(f"Error loading St. Lawrence config: {e}")
        else:
            log.info("St. Lawrence config not found - using defaults")
            # Default single outlet
            config["node_indices"] = [self.DEFAULT_NODE_INDEX]
            config["lons"] = [-69.5]  # Approximate longitude
            config["lats"] = [47.5]   # Approximate latitude
            config["names"] = ["StLawrence_main"]

        return config

    def process(self) -> ForcingResult:
        """
        Process St. Lawrence River forcing data.

        Returns:
            ForcingResult with processed files
        """
        log.info(f"Processing {self.source_name} river forcing")
        log.info(f"Input path: {self.input_path}")
        log.info(f"Use climatology: {self.use_climatology}")

        self.create_output_dir()
        output_files = []

        try:
            # Try to read real-time data from DCOM
            realtime_data = self._read_dcom_data()

            if realtime_data:
                log.info("Using real-time St. Lawrence data from DCOM")
                river_data = realtime_data
            elif self.use_climatology:
                log.info("Using climatological St. Lawrence data")
                river_data = self._generate_climatology()
            else:
                log.warning("No St. Lawrence data available and climatology disabled")
                return ForcingResult(
                    success=True,
                    source=self.source_name,
                    warnings=["No St. Lawrence data available"],
                )

            # Create output files
            vsource_file = self._create_vsource_stl(river_data)
            if vsource_file:
                output_files.append(vsource_file)

            msource_file = self._create_msource_stl(river_data)
            if msource_file:
                output_files.append(msource_file)

            log.info(f"St. Lawrence processing complete: {len(output_files)} files")

            return ForcingResult(
                success=True,
                source=self.source_name,
                output_files=output_files,
                metadata={
                    "data_source": "realtime" if realtime_data else "climatology",
                    "num_outlets": len(self.stl_config["node_indices"]),
                    "time_steps": len(river_data.get("times", [])),
                },
            )

        except Exception as e:
            log.error(f"St. Lawrence processing failed: {e}")
            import traceback
            log.error(traceback.format_exc())
            return ForcingResult(
                success=True,  # Non-fatal
                source=self.source_name,
                warnings=[f"St. Lawrence processing failed: {e}"],
            )

    def _read_dcom_data(self) -> Optional[Dict]:
        """
        Read real-time St. Lawrence data from DCOM.

        DCOM files contain Canadian Water Survey data for major rivers.
        File format varies by data source.

        Returns:
            Dictionary with times and discharge data, or None if unavailable
        """
        if not self.input_path.exists():
            log.debug(f"DCOM path not found: {self.input_path}")
            return None

        # Look for St. Lawrence data files
        # Pattern varies: check common naming conventions
        patterns = [
            f"st_lawrence*.txt",
            f"stlawrence*.csv",
            f"*STLAWRENCE*.dat",
            f"{self.pdy}/st_lawrence.txt",
        ]

        data_file = None
        for pattern in patterns:
            matches = list(self.input_path.glob(pattern))
            if matches:
                data_file = matches[0]
                break

        if not data_file:
            log.debug("No St. Lawrence data file found in DCOM")
            return None

        try:
            log.info(f"Reading St. Lawrence data: {data_file}")

            river_data = {
                "times": [],
                "discharge": [],
                "temperature": [],
            }

            # Parse data file (assuming simple text format)
            # Format: YYYY-MM-DD HH:MM discharge [temperature]
            with open(data_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue

                    parts = line.split()
                    if len(parts) >= 3:
                        try:
                            # Parse time
                            if '-' in parts[0]:
                                time_str = f"{parts[0]} {parts[1]}"
                                time_val = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
                            else:
                                # YYYYMMDDHH format
                                time_val = datetime.strptime(parts[0], "%Y%m%d%H")

                            river_data["times"].append(time_val)
                            river_data["discharge"].append(float(parts[-1]))

                            # Optional temperature
                            if len(parts) > 3:
                                river_data["temperature"].append(float(parts[-2]))

                        except (ValueError, IndexError) as e:
                            log.debug(f"Skipping line: {line} ({e})")

            if river_data["times"]:
                log.info(f"Read {len(river_data['times'])} St. Lawrence records")
                return river_data

        except Exception as e:
            log.warning(f"Error reading DCOM data: {e}")

        return None

    def _generate_climatology(self) -> Dict:
        """
        Generate climatological St. Lawrence discharge time series.

        Uses monthly average values interpolated to hourly.

        Returns:
            Dictionary with times and discharge data
        """
        river_data = {
            "times": [],
            "discharge": [],
            "temperature": [],
        }

        # Generate 5-day time series (matching SCHISM run)
        base_time = datetime.strptime(self.pdy, "%Y%m%d") + timedelta(hours=self.cyc)
        start_time = base_time - timedelta(hours=24)  # Start at nowcast begin

        # 5 days at hourly intervals
        for hour in range(5 * 24 + 1):
            current_time = start_time + timedelta(hours=hour)
            month = current_time.month

            # Get climatological values
            discharge = self.CLIMATOLOGY.get(month, 10000.0)
            temperature = self.TEMP_CLIMATOLOGY.get(month, 10.0)

            river_data["times"].append(current_time)
            river_data["discharge"].append(discharge)
            river_data["temperature"].append(temperature)

        log.info(f"Generated climatological data: {len(river_data['times'])} time steps")

        return river_data

    def _create_vsource_stl(self, river_data: Dict) -> Optional[Path]:
        """
        Create vsource_stl.th (St. Lawrence volume source time history).

        This file is appended to the main vsource.th or used separately.

        Format:
        time_seconds  flow1  flow2  ...
        """
        output_file = self.output_path / "vsource_stl.th"

        times = river_data.get("times", [])
        discharge = river_data.get("discharge", [])
        num_outlets = len(self.stl_config["node_indices"])

        if not times or not discharge:
            log.warning("No data for vsource_stl.th")
            return None

        try:
            base_time = times[0]

            with open(output_file, 'w') as f:
                f.write(f"! St. Lawrence River discharge\n")
                f.write(f"! Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"! Outlets: {num_outlets}\n")

                for i, t in enumerate(times):
                    time_sec = (t - base_time).total_seconds()

                    # Total discharge divided among outlets (if multiple)
                    flow = discharge[i] / num_outlets if i < len(discharge) else 10000.0 / num_outlets

                    # Write flow for each outlet
                    flow_str = " ".join(f"{flow:.2f}" for _ in range(num_outlets))
                    f.write(f"{time_sec:.1f} {flow_str}\n")

            log.info(f"Created {output_file}")
            return output_file

        except Exception as e:
            log.error(f"Failed to create vsource_stl.th: {e}")
            return None

    def _create_msource_stl(self, river_data: Dict) -> Optional[Path]:
        """
        Create msource_stl.th (St. Lawrence mass source - T/S).

        Format:
        time_seconds  temp1 salt1  temp2 salt2  ...
        """
        output_file = self.output_path / "msource_stl.th"

        times = river_data.get("times", [])
        temperature = river_data.get("temperature", [])
        num_outlets = len(self.stl_config["node_indices"])

        if not times:
            log.warning("No data for msource_stl.th")
            return None

        try:
            base_time = times[0]
            salinity = 0.0  # Fresh water

            with open(output_file, 'w') as f:
                f.write(f"! St. Lawrence River T/S\n")
                f.write(f"! Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

                for i, t in enumerate(times):
                    time_sec = (t - base_time).total_seconds()

                    # Temperature
                    if i < len(temperature):
                        temp = temperature[i]
                    else:
                        # Use climatology based on month
                        month = t.month
                        temp = self.TEMP_CLIMATOLOGY.get(month, 10.0)

                    # Write T/S for each outlet
                    ts_str = " ".join(f"{temp:.2f} {salinity:.2f}" for _ in range(num_outlets))
                    f.write(f"{time_sec:.1f} {ts_str}\n")

            log.info(f"Created {output_file}")
            return output_file

        except Exception as e:
            log.error(f"Failed to create msource_stl.th: {e}")
            return None

    def merge_with_nwm(
        self,
        nwm_vsource: Path,
        nwm_msource: Path,
        output_vsource: Path,
        output_msource: Path,
    ) -> Tuple[Optional[Path], Optional[Path]]:
        """
        Merge St. Lawrence sources with NWM river sources.

        The St. Lawrence River nodes are appended to the NWM sources
        to create combined vsource.th and msource.th files.

        Args:
            nwm_vsource: Path to NWM vsource.th
            nwm_msource: Path to NWM msource.th
            output_vsource: Path for merged vsource.th
            output_msource: Path for merged msource.th

        Returns:
            Tuple of (merged_vsource_path, merged_msource_path)
        """
        log.info("Merging St. Lawrence with NWM river forcing")

        stl_vsource = self.output_path / "vsource_stl.th"
        stl_msource = self.output_path / "msource_stl.th"

        merged_vs = None
        merged_ms = None

        # Merge vsource files
        if nwm_vsource.exists() and stl_vsource.exists():
            try:
                # Read NWM data
                nwm_data = np.loadtxt(nwm_vsource, comments='!')
                stl_data = np.loadtxt(stl_vsource, comments='!')

                # Combine columns (append St. Lawrence columns to NWM)
                merged_data = np.column_stack([nwm_data, stl_data[:, 1:]])

                # Write merged file
                np.savetxt(output_vsource, merged_data, fmt='%.4f')
                merged_vs = output_vsource
                log.info(f"Created merged vsource.th: {merged_vs}")

            except Exception as e:
                log.error(f"Error merging vsource: {e}")
                # Fall back to just copying NWM
                import shutil
                shutil.copy2(nwm_vsource, output_vsource)
                merged_vs = output_vsource

        # Merge msource files
        if nwm_msource.exists() and stl_msource.exists():
            try:
                nwm_data = np.loadtxt(nwm_msource, comments='!')
                stl_data = np.loadtxt(stl_msource, comments='!')

                merged_data = np.column_stack([nwm_data, stl_data[:, 1:]])

                np.savetxt(output_msource, merged_data, fmt='%.4f')
                merged_ms = output_msource
                log.info(f"Created merged msource.th: {merged_ms}")

            except Exception as e:
                log.error(f"Error merging msource: {e}")
                import shutil
                shutil.copy2(nwm_msource, output_msource)
                merged_ms = output_msource

        return merged_vs, merged_ms
