"""
ADCIRC Bias Correction

Implements bias correction for ADCIRC model output using CO-OPS tide
gauge observations. This corresponds to the operational MPI-based
bias_correction_mpi_v6_selective.py script used in STOFS-2D-Global.

The bias correction workflow:
1. Read model output (fort.63.nc - water surface elevation field)
2. Read CO-OPS tide gauge observations for the same time period
3. Compute bias (model - observed) at station locations
4. Spatially interpolate bias field to all mesh nodes using inverse
   distance weighting (IDW) or nearest-neighbor methods
5. Apply correction: corrected = model - interpolated_bias
6. Write corrected output files

This is applied as a post-processing step after the surface forcing
forecast runs (SURF_FORECAST1, SURF_FORECAST2) have completed.
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class BiasStation:
    """
    Represents a CO-OPS tide gauge station for bias correction.

    Attributes:
        station_id: CO-OPS station ID (e.g., "8518750")
        name: Station name (e.g., "The Battery, NY")
        lon: Station longitude
        lat: Station latitude
        observed: Observed water levels (time series)
        modeled: Model water levels at station (time series)
        bias: Computed bias (modeled - observed)
    """
    station_id: str
    name: str = ""
    lon: float = 0.0
    lat: float = 0.0
    observed: Optional[np.ndarray] = None
    modeled: Optional[np.ndarray] = None
    bias: Optional[np.ndarray] = None


@dataclass
class BiasCorrectionResult:
    """
    Result of a bias correction operation.

    Attributes:
        success: Whether correction completed successfully
        n_stations_used: Number of stations with valid bias data
        n_stations_total: Total number of stations attempted
        mean_bias: Mean bias across all stations (meters)
        max_bias: Maximum absolute bias (meters)
        output_file: Path to corrected output file
        errors: List of error messages
    """
    success: bool
    n_stations_used: int = 0
    n_stations_total: int = 0
    mean_bias: float = 0.0
    max_bias: float = 0.0
    output_file: Optional[Path] = None
    errors: List[str] = field(default_factory=list)


class ADCIRCBiasCorrection:
    """
    Bias correction for ADCIRC water level forecasts.

    Uses CO-OPS tide gauge observations to correct model output by
    computing and spatially interpolating the bias field. Supports
    both full-field correction and selective station-based correction.

    The operational STOFS-2D-Global system uses MPI parallelism for
    this computation due to the large mesh size (~4.8M nodes). This
    implementation provides serial and optionally parallel execution.

    Usage:
        corrector = ADCIRCBiasCorrection(config)
        result = corrector.correct(
            model_file=Path("fort.63.nc"),
            output_file=Path("fort.63.corrected.nc"),
        )
    """

    # Default configuration
    DEFAULTS = {
        'search_radius_deg': 5.0,      # Max distance for IDW interpolation
        'idw_power': 2,                 # Inverse distance weighting power
        'min_stations': 3,              # Minimum stations for correction
        'max_bias_threshold': 2.0,      # Reject stations with bias > 2m
        'time_window_hours': 6,         # Time window for obs comparison
    }

    def __init__(self, config: Any):
        """
        Initialize bias correction.

        Args:
            config: OFS configuration
        """
        self.config = config
        self._yaml_data = self._get_yaml_data()

        # Load bias correction config
        post_cfg = self._yaml_data.get('post_processing', {})
        bc_cfg = post_cfg.get('bias_correction', {})

        self.enabled = bc_cfg.get('enabled', True)
        self.method = bc_cfg.get('method', 'selective_mpi')
        self.search_radius = bc_cfg.get(
            'search_radius_deg', self.DEFAULTS['search_radius_deg']
        )
        self.idw_power = bc_cfg.get(
            'idw_power', self.DEFAULTS['idw_power']
        )
        self.min_stations = bc_cfg.get(
            'min_stations', self.DEFAULTS['min_stations']
        )
        self.max_bias_threshold = bc_cfg.get(
            'max_bias_threshold', self.DEFAULTS['max_bias_threshold']
        )

    def _get_yaml_data(self) -> Dict:
        """Extract YAML configuration data."""
        if hasattr(self.config, '_yaml_data'):
            return self.config._yaml_data
        if hasattr(self.config, 'system') and hasattr(self.config.system, '_raw'):
            return self.config.system._raw
        return {}

    def correct(
        self,
        model_file: Path,
        output_file: Path,
        obs_file: Optional[Path] = None,
        station_file: Optional[Path] = None,
    ) -> BiasCorrectionResult:
        """
        Apply bias correction to ADCIRC model output.

        First attempts to use the legacy MPI Python script if available.
        Otherwise falls back to the native implementation.

        Args:
            model_file: Path to model output (fort.63.nc)
            output_file: Path for corrected output
            obs_file: Path to CO-OPS observations (optional)
            station_file: Path to station list file (optional)

        Returns:
            BiasCorrectionResult with correction statistics
        """
        if not self.enabled:
            return BiasCorrectionResult(
                success=True,
                errors=["Bias correction disabled in configuration"],
            )

        # Try legacy MPI script
        legacy_result = self._try_legacy_mpi_script(model_file, output_file)
        if legacy_result is not None:
            return legacy_result

        # Fall back to native implementation
        return self._correct_native(model_file, output_file, obs_file, station_file)

    def _try_legacy_mpi_script(
        self,
        model_file: Path,
        output_file: Path,
    ) -> Optional[BiasCorrectionResult]:
        """
        Try to run the operational MPI bias correction script.

        The operational script is:
            bias_correction_mpi_v6_selective.py

        Returns:
            BiasCorrectionResult if script was found and executed, None otherwise
        """
        import subprocess

        ush_dir = os.environ.get('USHstofs2d', os.environ.get('PYstofs2d', ''))
        if not ush_dir:
            return None

        script_path = Path(ush_dir) / "bias_correction_mpi_v6_selective.py"
        if not script_path.exists():
            # Also check for non-versioned name
            script_path = Path(ush_dir) / "stofs_2d_glo_bias_correction.py"
            if not script_path.exists():
                return None

        data_dir = os.environ.get('DATA', '/tmp')
        nprocs = int(os.environ.get('TOTAL_TASKS', '24'))

        log.info(f"Running legacy bias correction: {script_path}")

        try:
            cmd = f"mpiexec -n {nprocs} python3 {script_path}"
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=data_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=7200,  # 2 hours
            )

            if result.returncode == 0:
                return BiasCorrectionResult(
                    success=True,
                    output_file=output_file if output_file.exists() else None,
                )
            else:
                return BiasCorrectionResult(
                    success=False,
                    errors=[
                        f"Legacy script failed (rc={result.returncode}): "
                        f"{result.stderr[:500] if result.stderr else 'Unknown error'}"
                    ],
                )
        except Exception as e:
            return BiasCorrectionResult(
                success=False,
                errors=[str(e)],
            )

    def _correct_native(
        self,
        model_file: Path,
        output_file: Path,
        obs_file: Optional[Path],
        station_file: Optional[Path],
    ) -> BiasCorrectionResult:
        """
        Native Python bias correction implementation.

        Args:
            model_file: Path to model fort.63.nc
            output_file: Path for corrected output
            obs_file: Path to observations NetCDF
            station_file: Path to station list

        Returns:
            BiasCorrectionResult
        """
        try:
            import netCDF4 as nc
        except ImportError:
            return BiasCorrectionResult(
                success=False,
                errors=["netCDF4 required for native bias correction"],
            )

        if not model_file.exists():
            return BiasCorrectionResult(
                success=False,
                errors=[f"Model file not found: {model_file}"],
            )

        try:
            # Read model output
            log.info(f"Reading model output: {model_file}")
            with nc.Dataset(model_file, 'r') as ds:
                model_lon = ds.variables['x'][:]
                model_lat = ds.variables['y'][:]
                model_zeta = ds.variables['zeta'][:]  # (time, nodes)
                model_time = ds.variables['time'][:]
                n_nodes = len(model_lon)
                n_times = len(model_time)

            log.info(f"Model grid: {n_nodes} nodes, {n_times} timesteps")

            # Load station observations
            stations = self._load_observations(obs_file, station_file)
            if not stations:
                return BiasCorrectionResult(
                    success=False,
                    errors=["No station observations available for bias correction"],
                )

            # Extract model values at station locations
            stations = self._extract_model_at_stations(
                stations, model_lon, model_lat, model_zeta
            )

            # Compute bias at each station
            valid_stations = []
            for sta in stations:
                if sta.observed is not None and sta.modeled is not None:
                    sta.bias = np.nanmean(sta.modeled - sta.observed)
                    if abs(sta.bias) <= self.max_bias_threshold:
                        valid_stations.append(sta)
                    else:
                        log.warning(
                            f"Station {sta.station_id} bias {sta.bias:.3f}m "
                            f"exceeds threshold, excluded"
                        )

            log.info(
                f"Valid stations for correction: {len(valid_stations)}/{len(stations)}"
            )

            if len(valid_stations) < self.min_stations:
                return BiasCorrectionResult(
                    success=False,
                    n_stations_used=len(valid_stations),
                    n_stations_total=len(stations),
                    errors=[
                        f"Insufficient valid stations: {len(valid_stations)} "
                        f"< {self.min_stations} minimum"
                    ],
                )

            # Interpolate bias field to all mesh nodes
            station_lons = np.array([s.lon for s in valid_stations])
            station_lats = np.array([s.lat for s in valid_stations])
            station_biases = np.array([s.bias for s in valid_stations])

            bias_field = self._interpolate_bias(
                station_lons, station_lats, station_biases,
                model_lon, model_lat,
            )

            # Apply correction to all timesteps
            corrected_zeta = model_zeta - bias_field[np.newaxis, :]

            # Write corrected output
            self._write_corrected(model_file, output_file, corrected_zeta)

            mean_bias = float(np.nanmean(station_biases))
            max_bias = float(np.nanmax(np.abs(station_biases)))

            log.info(
                f"Bias correction complete: mean={mean_bias:.4f}m, "
                f"max={max_bias:.4f}m, stations={len(valid_stations)}"
            )

            return BiasCorrectionResult(
                success=True,
                n_stations_used=len(valid_stations),
                n_stations_total=len(stations),
                mean_bias=mean_bias,
                max_bias=max_bias,
                output_file=output_file,
            )

        except Exception as e:
            log.error(f"Bias correction failed: {e}")
            return BiasCorrectionResult(
                success=False,
                errors=[str(e)],
            )

    def _load_observations(
        self,
        obs_file: Optional[Path],
        station_file: Optional[Path],
    ) -> List[BiasStation]:
        """
        Load CO-OPS station observations.

        Args:
            obs_file: Path to observation data file
            station_file: Path to station list

        Returns:
            List of BiasStation objects with observed data
        """
        stations = []

        # Try to find observation file
        if obs_file is None:
            data_dir = Path(os.environ.get('DATA', '/tmp'))
            fix_dir = Path(os.environ.get('FIXstofs2d', os.environ.get('FIXofs', '/tmp')))

            # Common observation file patterns
            for candidate in [
                data_dir / "coops_observations.nc",
                data_dir / "station_observations.nc",
            ]:
                if candidate.exists():
                    obs_file = candidate
                    break

        if obs_file is None or not obs_file.exists():
            log.warning("No observation file found for bias correction")
            return stations

        # Try to find station list
        if station_file is None:
            fix_dir = Path(os.environ.get('FIXstofs2d', os.environ.get('FIXofs', '/tmp')))
            for candidate in [
                fix_dir / "stofs_2d_glo_stations.txt",
                fix_dir / "station_list.txt",
            ]:
                if candidate.exists():
                    station_file = candidate
                    break

        try:
            import netCDF4 as nc

            with nc.Dataset(obs_file, 'r') as ds:
                # Read station metadata
                if 'station_id' in ds.variables:
                    n_stations = ds.dimensions['station'].size
                    for i in range(n_stations):
                        sta = BiasStation(
                            station_id=str(ds.variables['station_id'][i]),
                            lon=float(ds.variables['lon'][i]),
                            lat=float(ds.variables['lat'][i]),
                        )
                        if 'water_level' in ds.variables:
                            sta.observed = ds.variables['water_level'][:, i]
                        stations.append(sta)

            log.info(f"Loaded {len(stations)} observation stations")

        except Exception as e:
            log.warning(f"Could not read observations: {e}")

        return stations

    def _extract_model_at_stations(
        self,
        stations: List[BiasStation],
        model_lon: np.ndarray,
        model_lat: np.ndarray,
        model_zeta: np.ndarray,
    ) -> List[BiasStation]:
        """
        Extract model values at station locations using nearest-neighbor.

        Args:
            stations: List of stations with lon/lat
            model_lon: Model node longitudes
            model_lat: Model node latitudes
            model_zeta: Model water levels (time, nodes)

        Returns:
            Stations with modeled field populated
        """
        for sta in stations:
            # Find nearest model node
            dist = np.sqrt(
                (model_lon - sta.lon) ** 2 + (model_lat - sta.lat) ** 2
            )
            nearest_idx = np.argmin(dist)
            min_dist = dist[nearest_idx]

            if min_dist < 0.1:  # Within ~11km
                sta.modeled = model_zeta[:, nearest_idx]
            else:
                log.debug(
                    f"Station {sta.station_id} too far from nearest node "
                    f"({min_dist:.3f} deg)"
                )

        return stations

    def _interpolate_bias(
        self,
        sta_lon: np.ndarray,
        sta_lat: np.ndarray,
        sta_bias: np.ndarray,
        node_lon: np.ndarray,
        node_lat: np.ndarray,
    ) -> np.ndarray:
        """
        Spatially interpolate bias from stations to all mesh nodes.

        Uses inverse distance weighting (IDW) with configurable power
        and search radius.

        Args:
            sta_lon: Station longitudes
            sta_lat: Station latitudes
            sta_bias: Station bias values
            node_lon: Mesh node longitudes
            node_lat: Mesh node latitudes

        Returns:
            1D array of interpolated bias at each mesh node
        """
        n_nodes = len(node_lon)
        bias_field = np.zeros(n_nodes)

        # Process in chunks for memory efficiency
        chunk_size = 100000
        for start in range(0, n_nodes, chunk_size):
            end = min(start + chunk_size, n_nodes)
            chunk_lon = node_lon[start:end]
            chunk_lat = node_lat[start:end]

            # Compute distances from chunk nodes to all stations
            for i in range(len(chunk_lon)):
                dists = np.sqrt(
                    (sta_lon - chunk_lon[i]) ** 2 +
                    (sta_lat - chunk_lat[i]) ** 2
                )

                # Apply search radius
                mask = dists < self.search_radius
                if not np.any(mask):
                    # Use nearest station if none within radius
                    nearest = np.argmin(dists)
                    bias_field[start + i] = sta_bias[nearest]
                else:
                    # IDW interpolation
                    d = dists[mask]
                    b = sta_bias[mask]

                    # Avoid division by zero (exact match)
                    zero_dist = d < 1e-10
                    if np.any(zero_dist):
                        bias_field[start + i] = b[zero_dist][0]
                    else:
                        weights = 1.0 / d ** self.idw_power
                        bias_field[start + i] = np.sum(weights * b) / np.sum(weights)

        return bias_field

    def _write_corrected(
        self,
        input_file: Path,
        output_file: Path,
        corrected_zeta: np.ndarray,
    ) -> None:
        """
        Write bias-corrected water levels to a new NetCDF file.

        Copies the input file structure and replaces the zeta variable
        with corrected values.

        Args:
            input_file: Original model output file
            output_file: Output path for corrected file
            corrected_zeta: Corrected water level array (time, nodes)
        """
        import netCDF4 as nc
        import shutil

        # Copy the original file
        shutil.copy2(input_file, output_file)

        # Update the zeta values
        with nc.Dataset(output_file, 'r+') as ds:
            ds.variables['zeta'][:] = corrected_zeta
            ds.setncattr('bias_correction', 'Applied IDW bias correction from CO-OPS stations')

        log.info(f"Wrote corrected output: {output_file}")

    def __repr__(self) -> str:
        return f"ADCIRCBiasCorrection(enabled={self.enabled}, method={self.method})"
