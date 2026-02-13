"""
St. Lawrence River Forcing Processor

Processes St. Lawrence River discharge data for STOFS 3D Atlantic.
The St. Lawrence River enters the Atlantic domain through the Gulf of
St. Lawrence and requires special handling separate from NWM (which doesn't
cover Canada).

Data sources:
- DCOM: Canadian hydrological data (QC_02OA016_hourly_hydrometric.csv)
- Climatology: Historical monthly average flows

Fully native Python -- reads CSV/text directly, no subprocess/shell calls.

Output:
- vsource_stl.th  -- volume source time history for St. Lawrence
- msource_stl.th  -- T/S mass source for St. Lawrence
- flux.th         -- flux time history (for gen_fluxth compatibility)
- TEM_1.th        -- temperature time history
"""

import csv
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ..base import ForcingProcessor, ForcingResult

log = logging.getLogger(__name__)


class StLawrenceProcessor(ForcingProcessor):
    """
    St. Lawrence River discharge processor.

    The St. Lawrence River is the largest river on the US/Canada Atlantic
    coast by volume (average ~10,000 m3/s) with significant impact on
    circulation and salinity in the Gulf of St. Lawrence.

    Sources:
    - Real-time: Canadian Water Survey data via DCOM (CSV)
    - Backup: previous cycle's archived data
    - Fallback: climatological monthly averages

    Output is merged with NWM river forcing in vsource.th.
    """

    # Monthly climatological discharge (m3/s)
    CLIMATOLOGY = {
        1: 8500.0, 2: 8000.0, 3: 8500.0, 4: 11000.0,
        5: 13000.0, 6: 12000.0, 7: 10500.0, 8: 9500.0,
        9: 9000.0, 10: 9000.0, 11: 9000.0, 12: 8500.0,
    }

    DEFAULT_NODE_INDEX = 1

    # Water temperature climatology (deg-C)
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

        self.stl_config = self._load_stl_config()

    def _load_stl_config(self) -> Dict[str, Any]:
        """Load St. Lawrence River configuration from FIX directory."""
        config: Dict[str, Any] = {
            "node_indices": [],
            "lons": [],
            "lats": [],
            "names": [],
        }

        stl_file = self.config.get_fix_file(f"{self.config.RUN}_st_lawrence.txt")

        if stl_file.exists():
            try:
                with open(stl_file, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        parts = line.split()
                        if len(parts) >= 3:
                            config["node_indices"].append(int(parts[0]))
                            config["lons"].append(float(parts[1]))
                            config["lats"].append(float(parts[2]))
                            config["names"].append(
                                parts[3] if len(parts) > 3 else "StLawrence"
                            )
                log.info(
                    "Loaded St. Lawrence config: %d outlets",
                    len(config["node_indices"]),
                )
            except Exception as e:
                log.warning("Error loading St. Lawrence config: %s", e)
        else:
            log.info("St. Lawrence config not found -- using defaults")
            config["node_indices"] = [self.DEFAULT_NODE_INDEX]
            config["lons"] = [-69.5]
            config["lats"] = [47.5]
            config["names"] = ["StLawrence_main"]

        return config

    # ==================================================================
    # Main entry
    # ==================================================================

    def process(self) -> ForcingResult:
        """Process St. Lawrence River forcing data."""
        log.info("Processing %s river forcing", self.source_name)
        log.info("Input path: %s", self.input_path)

        self.create_output_dir()
        output_files: List[Path] = []

        try:
            # Try real-time data from DCOM
            realtime_data = self._read_dcom_data()

            if realtime_data:
                log.info("Using real-time St. Lawrence data from DCOM")
                river_data = realtime_data
            elif self.use_climatology:
                log.info("Using climatological St. Lawrence data")
                river_data = self._generate_climatology()
            else:
                log.warning("No St. Lawrence data available")
                return ForcingResult(
                    success=True,
                    source=self.source_name,
                    warnings=["No St. Lawrence data available"],
                )

            vsource_file = self._create_vsource_stl(river_data)
            if vsource_file:
                output_files.append(vsource_file)

            msource_file = self._create_msource_stl(river_data)
            if msource_file:
                output_files.append(msource_file)

            # Also write flux.th and TEM_1.th for shell-script compatibility
            flux_file = self._create_flux_th(river_data)
            if flux_file:
                output_files.append(flux_file)

            tem_file = self._create_tem_1_th(river_data)
            if tem_file:
                output_files.append(tem_file)

            log.info(
                "St. Lawrence processing complete: %d files", len(output_files)
            )

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
            log.error("St. Lawrence processing failed: %s", e, exc_info=True)
            return ForcingResult(
                success=True,  # Non-fatal
                source=self.source_name,
                warnings=[f"St. Lawrence processing failed: {e}"],
            )

    # ==================================================================
    # DCOM data reading (native Python CSV parser)
    # ==================================================================

    def _read_dcom_data(self) -> Optional[Dict[str, Any]]:
        """
        Read real-time St. Lawrence data from DCOM.

        DCOM file: QC_02OA016_hourly_hydrometric.csv
        This is the Canadian Water Survey gauge at Cornwall, ON.
        """
        if not self.input_path.exists():
            log.debug("DCOM path not found: %s", self.input_path)
            return None

        yyyymmdd_today = self.pdy
        yyyymmdd_prev = (
            datetime.strptime(self.pdy, "%Y%m%d") - timedelta(days=1)
        ).strftime("%Y%m%d")

        # Try today then yesterday
        for datestr in [yyyymmdd_today, yyyymmdd_prev]:
            candidates = [
                self.input_path / datestr / "canadian_water" / "QC_02OA016_hourly_hydrometric.csv",
                self.input_path / "canadian_water" / "QC_02OA016_hourly_hydrometric.csv",
            ]

            # Also try generic patterns
            patterns = [
                "st_lawrence*.txt",
                "stlawrence*.csv",
                "*STLAWRENCE*.dat",
                f"{datestr}/st_lawrence.txt",
                "*QC_02OA016*.csv",
            ]
            for pattern in patterns:
                candidates.extend(self.input_path.glob(pattern))

            for data_file in candidates:
                if isinstance(data_file, Path) and data_file.exists():
                    parsed = self._parse_dcom_csv(data_file)
                    if parsed:
                        return parsed

        log.debug("No St. Lawrence data file found in DCOM")
        return None

    def _parse_dcom_csv(self, data_file: Path) -> Optional[Dict[str, Any]]:
        """Parse Canadian Water Survey CSV file."""
        river_data: Dict[str, Any] = {
            "times": [],
            "discharge": [],
            "temperature": [],
        }

        try:
            log.info("Reading St. Lawrence data: %s", data_file)

            with open(data_file, "r", encoding="utf-8", errors="replace") as f:
                # Try CSV reader first
                reader = csv.reader(f)
                header = None
                for row in reader:
                    if not row:
                        continue
                    # Skip comment lines
                    if row[0].strip().startswith("#"):
                        continue
                    # Detect header
                    if header is None and any(
                        h in row[0].lower() for h in ["date", "time", "discharge"]
                    ):
                        header = row
                        continue

                    try:
                        # Try YYYY-MM-DD HH:MM format
                        if len(row) >= 3 and "-" in row[0]:
                            time_str = f"{row[0]} {row[1]}"
                            time_val = datetime.strptime(
                                time_str.strip(), "%Y-%m-%d %H:%M"
                            )
                            discharge = float(row[2])
                        elif len(row) >= 2:
                            time_val = datetime.strptime(
                                row[0].strip(), "%Y%m%d%H"
                            )
                            discharge = float(row[1])
                        else:
                            continue

                        river_data["times"].append(time_val)
                        river_data["discharge"].append(discharge)
                    except (ValueError, IndexError):
                        # Try space-delimited fallback
                        try:
                            parts = row[0].split()
                            if len(parts) >= 2:
                                time_val = datetime.strptime(
                                    parts[0], "%Y%m%d%H"
                                )
                                river_data["times"].append(time_val)
                                river_data["discharge"].append(float(parts[-1]))
                        except (ValueError, IndexError):
                            pass

            if river_data["times"] and len(river_data["times"]) >= 6:
                log.info(
                    "Read %d St. Lawrence records", len(river_data["times"])
                )
                return river_data

        except Exception as e:
            log.warning("Error reading DCOM data: %s", e)

        return None

    # ==================================================================
    # Climatology
    # ==================================================================

    def _generate_climatology(self) -> Dict[str, Any]:
        """Generate climatological St. Lawrence discharge time series."""
        river_data: Dict[str, Any] = {
            "times": [],
            "discharge": [],
            "temperature": [],
        }

        base_time = (
            datetime.strptime(self.pdy, "%Y%m%d") + timedelta(hours=self.cyc)
        )
        start_time = base_time - timedelta(hours=24)

        for hour in range(5 * 24 + 1):
            current_time = start_time + timedelta(hours=hour)
            month = current_time.month

            river_data["times"].append(current_time)
            river_data["discharge"].append(self.CLIMATOLOGY.get(month, 10000.0))
            river_data["temperature"].append(self.TEMP_CLIMATOLOGY.get(month, 10.0))

        log.info(
            "Generated climatological data: %d time steps",
            len(river_data["times"]),
        )
        return river_data

    # ==================================================================
    # Output writing
    # ==================================================================

    def _create_vsource_stl(self, river_data: Dict[str, Any]) -> Optional[Path]:
        """Create vsource_stl.th (volume source time history)."""
        output_file = self.output_path / "vsource_stl.th"
        times = river_data.get("times", [])
        discharge = river_data.get("discharge", [])
        num_outlets = len(self.stl_config["node_indices"])

        if not times or not discharge:
            return None

        try:
            base_time = times[0]
            with open(output_file, "w") as f:
                f.write(f"! St. Lawrence River discharge\n")
                f.write(f"! Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"! Outlets: {num_outlets}\n")

                for i, t in enumerate(times):
                    time_sec = (t - base_time).total_seconds()
                    flow = (
                        discharge[i] / num_outlets
                        if i < len(discharge)
                        else 10000.0 / num_outlets
                    )
                    flow_str = " ".join(f"{flow:.2f}" for _ in range(num_outlets))
                    f.write(f"{time_sec:.1f} {flow_str}\n")

            log.info("Created %s", output_file)
            return output_file
        except Exception as e:
            log.error("Failed to create vsource_stl.th: %s", e)
            return None

    def _create_msource_stl(self, river_data: Dict[str, Any]) -> Optional[Path]:
        """Create msource_stl.th (T/S mass source)."""
        output_file = self.output_path / "msource_stl.th"
        times = river_data.get("times", [])
        temperature = river_data.get("temperature", [])
        num_outlets = len(self.stl_config["node_indices"])

        if not times:
            return None

        try:
            base_time = times[0]
            salinity = 0.0

            with open(output_file, "w") as f:
                f.write(f"! St. Lawrence River T/S\n")
                f.write(f"! Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

                for i, t in enumerate(times):
                    time_sec = (t - base_time).total_seconds()
                    if i < len(temperature):
                        temp = temperature[i]
                    else:
                        temp = self.TEMP_CLIMATOLOGY.get(t.month, 10.0)

                    ts_str = " ".join(
                        f"{temp:.2f} {salinity:.2f}" for _ in range(num_outlets)
                    )
                    f.write(f"{time_sec:.1f} {ts_str}\n")

            log.info("Created %s", output_file)
            return output_file
        except Exception as e:
            log.error("Failed to create msource_stl.th: %s", e)
            return None

    def _create_flux_th(self, river_data: Dict[str, Any]) -> Optional[Path]:
        """Create flux.th for backward compatibility with shell scripts."""
        output_file = self.output_path / "flux.th"
        times = river_data.get("times", [])
        discharge = river_data.get("discharge", [])

        if not times or not discharge:
            return None

        try:
            base_time = times[0]
            with open(output_file, "w") as f:
                for i, t in enumerate(times):
                    time_sec = (t - base_time).total_seconds()
                    flow = discharge[i] if i < len(discharge) else 10000.0
                    f.write(f"{time_sec:.1f} {flow:.2f}\n")
            log.info("Created %s", output_file)
            return output_file
        except Exception as e:
            log.error("Failed to create flux.th: %s", e)
            return None

    def _create_tem_1_th(self, river_data: Dict[str, Any]) -> Optional[Path]:
        """Create TEM_1.th for backward compatibility with shell scripts."""
        output_file = self.output_path / "TEM_1.th"
        times = river_data.get("times", [])
        temperature = river_data.get("temperature", [])

        if not times:
            return None

        try:
            base_time = times[0]
            with open(output_file, "w") as f:
                for i, t in enumerate(times):
                    time_sec = (t - base_time).total_seconds()
                    temp = (
                        temperature[i]
                        if i < len(temperature)
                        else self.TEMP_CLIMATOLOGY.get(t.month, 10.0)
                    )
                    f.write(f"{time_sec:.1f} {temp:.2f}\n")
            log.info("Created %s", output_file)
            return output_file
        except Exception as e:
            log.error("Failed to create TEM_1.th: %s", e)
            return None

    # ==================================================================
    # Merge helper
    # ==================================================================

    def merge_with_nwm(
        self,
        nwm_vsource: Path,
        nwm_msource: Path,
        output_vsource: Path,
        output_msource: Path,
    ) -> Tuple[Optional[Path], Optional[Path]]:
        """
        Merge St. Lawrence sources with NWM river sources.

        Appends St. Lawrence columns to the NWM .th files.
        """
        log.info("Merging St. Lawrence with NWM river forcing")

        stl_vsource = self.output_path / "vsource_stl.th"
        stl_msource = self.output_path / "msource_stl.th"
        import shutil

        merged_vs = None
        merged_ms = None

        for nwm_src, stl_src, out in [
            (nwm_vsource, stl_vsource, output_vsource),
            (nwm_msource, stl_msource, output_msource),
        ]:
            if nwm_src.exists() and stl_src.exists():
                try:
                    nwm_data = np.loadtxt(nwm_src, comments="!")
                    stl_data = np.loadtxt(stl_src, comments="!")
                    merged = np.column_stack([nwm_data, stl_data[:, 1:]])
                    np.savetxt(out, merged, fmt="%.4f")
                    if "vsource" in out.name:
                        merged_vs = out
                    else:
                        merged_ms = out
                    log.info("Created merged %s", out)
                except Exception as e:
                    log.error("Error merging %s: %s", out.name, e)
                    shutil.copy2(nwm_src, out)
                    if "vsource" in out.name:
                        merged_vs = out
                    else:
                        merged_ms = out

        return merged_vs, merged_ms
