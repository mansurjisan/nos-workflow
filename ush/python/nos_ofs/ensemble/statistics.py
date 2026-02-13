"""
Ensemble Statistics

Computes post-processing statistics from an ensemble of completed model runs:
- Ensemble mean
- Ensemble spread (standard deviation)
- Percentiles (e.g., 10th, 50th, 90th)
- Probability of exceedance (e.g., P(SSH > 1.0m))

Statistics are computed for configurable output variables (zeta/elevation,
temperature, salinity, currents) and written to NetCDF files suitable for
downstream visualization and dissemination.

Uses xarray for lazy/chunked computation when available, falling back to
numpy for smaller datasets.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from .config import StatisticsConfig

log = logging.getLogger(__name__)

# Optional imports
try:
    import xarray as xr

    HAS_XARRAY = True
except ImportError:
    HAS_XARRAY = False

try:
    from netCDF4 import Dataset

    HAS_NETCDF4 = True
except ImportError:
    HAS_NETCDF4 = False


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class EnsembleStatsResult:
    """
    Result of ensemble statistics computation.

    Attributes:
        success: Whether statistics were computed successfully.
        output_files: List of generated NetCDF output files.
        variables_computed: List of variables for which statistics were computed.
        n_members_used: Number of ensemble members used in computation.
        errors: List of error messages.
        metadata: Additional metadata.
    """

    success: bool
    output_files: List[Path] = field(default_factory=list)
    variables_computed: List[str] = field(default_factory=list)
    n_members_used: int = 0
    errors: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        """Human-readable summary of statistics results."""
        status = "SUCCESS" if self.success else "FAILED"
        lines = [
            f"Ensemble Statistics: {status}",
            f"  Members used: {self.n_members_used}",
            f"  Variables: {self.variables_computed}",
            f"  Output files: {len(self.output_files)}",
        ]
        if self.errors:
            for err in self.errors[:3]:
                lines.append(f"  Error: {err}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Variable name mapping
# ---------------------------------------------------------------------------

# Map user-friendly names to possible NetCDF variable names across model types
VARIABLE_NAME_MAP = {
    "zeta": ["zeta", "elevation", "eta2", "elev", "ssh", "surf_el"],
    "temp": ["temp", "temperature", "tr_nd1", "salt_temperature"],
    "salt": ["salt", "salinity", "tr_nd2"],
    "u": ["u", "horizontalVelX", "u_vel", "u_eastward"],
    "v": ["v", "horizontalVelY", "v_vel", "v_northward"],
}


def _find_variable(ds: Any, var_name: str) -> Optional[str]:
    """
    Find a variable in a dataset by trying common name variants.

    Args:
        ds: xarray Dataset or netCDF4 Dataset.
        var_name: User-friendly variable name.

    Returns:
        Actual variable name found in the dataset, or None.
    """
    candidates = VARIABLE_NAME_MAP.get(var_name, [var_name])

    if HAS_XARRAY and isinstance(ds, xr.Dataset):
        for c in candidates:
            if c in ds.data_vars:
                return c
    elif HAS_NETCDF4 and isinstance(ds, Dataset):
        for c in candidates:
            if c in ds.variables:
                return c

    return None


# ---------------------------------------------------------------------------
# Ensemble statistics class
# ---------------------------------------------------------------------------


class EnsembleStatistics:
    """
    Compute ensemble statistics from completed member outputs.

    Loads model output from each member, stacks them along a new 'member'
    dimension, and computes configured statistics (mean, spread, percentiles,
    probability of exceedance).

    The class supports two modes:
    - xarray mode: uses xarray.open_mfdataset for lazy loading and
      dask-backed computation. Preferred for large datasets.
    - numpy mode: loads data directly with netCDF4. Suitable for smaller
      datasets when xarray is not available.

    Attributes:
        members: List of successful EnsembleMember instances.
        output_dir: Directory to write statistics output files.
        config: StatisticsConfig with variable list and percentiles.
    """

    def __init__(
        self,
        members: List[Any],  # List[EnsembleMember]
        output_dir: Path,
        config: Optional[StatisticsConfig] = None,
    ):
        """
        Initialize ensemble statistics calculator.

        Args:
            members: List of EnsembleMember instances that completed
                     successfully. Each must have a data_dir with output files.
            output_dir: Directory to write computed statistics.
            config: StatisticsConfig. If None, uses defaults.
        """
        self.members = members
        self.output_dir = Path(output_dir)
        self.config = config or StatisticsConfig()

        self.output_dir.mkdir(parents=True, exist_ok=True)

    def compute_mean(self, variable: str) -> Optional[Any]:
        """
        Compute ensemble mean for a variable.

        Args:
            variable: Variable name (e.g., 'zeta', 'temp').

        Returns:
            xarray.DataArray with ensemble mean, or numpy array.
            None if computation fails.
        """
        data = self._load_ensemble_data(variable)
        if data is None:
            return None

        if HAS_XARRAY and isinstance(data, xr.DataArray):
            return data.mean(dim="member")
        else:
            return np.nanmean(data, axis=0)

    def compute_spread(self, variable: str) -> Optional[Any]:
        """
        Compute ensemble spread (standard deviation) for a variable.

        Args:
            variable: Variable name.

        Returns:
            xarray.DataArray or numpy array with ensemble spread.
            None if computation fails.
        """
        data = self._load_ensemble_data(variable)
        if data is None:
            return None

        if HAS_XARRAY and isinstance(data, xr.DataArray):
            return data.std(dim="member")
        else:
            return np.nanstd(data, axis=0)

    def compute_percentiles(
        self, variable: str, percentiles: Optional[List[float]] = None
    ) -> Optional[Any]:
        """
        Compute ensemble percentiles for a variable.

        Args:
            variable: Variable name.
            percentiles: List of percentile values (0-100). If None,
                         uses config.percentiles.

        Returns:
            xarray.Dataset or dict mapping percentile to numpy array.
            None if computation fails.
        """
        if percentiles is None:
            percentiles = self.config.percentiles

        data = self._load_ensemble_data(variable)
        if data is None:
            return None

        if HAS_XARRAY and isinstance(data, xr.DataArray):
            # xarray quantile expects fractions (0-1)
            quantiles = [p / 100.0 for p in percentiles]
            result = data.quantile(quantiles, dim="member")
            return result
        else:
            result = {}
            for p in percentiles:
                result[p] = np.nanpercentile(data, p, axis=0)
            return result

    def compute_probability_exceedance(
        self, variable: str, threshold: float
    ) -> Optional[Any]:
        """
        Compute probability that a variable exceeds a threshold.

        This is particularly useful for flood forecasting: P(SSH > threshold).

        Args:
            variable: Variable name.
            threshold: Threshold value in native units.

        Returns:
            xarray.DataArray or numpy array with probability values (0-1).
            None if computation fails.
        """
        data = self._load_ensemble_data(variable)
        if data is None:
            return None

        if HAS_XARRAY and isinstance(data, xr.DataArray):
            exceedance = (data > threshold).astype(float)
            return exceedance.mean(dim="member")
        else:
            exceedance = (data > threshold).astype(float)
            return np.nanmean(exceedance, axis=0)

    def compute_all(self) -> EnsembleStatsResult:
        """
        Compute all configured statistics and write to NetCDF.

        Iterates over configured variables and computes mean, spread,
        percentiles, and probability of exceedance for each. Results
        are written to individual NetCDF files per variable.

        Returns:
            EnsembleStatsResult with output file list and metadata.
        """
        output_files = []
        variables_computed = []
        errors = []

        for variable in self.config.variables:
            log.info(f"Computing statistics for {variable}")

            try:
                # Compute statistics
                mean = self.compute_mean(variable)
                spread = self.compute_spread(variable)
                percentiles = self.compute_percentiles(variable)

                if mean is None:
                    log.warning(
                        f"Could not load data for {variable}, skipping"
                    )
                    continue

                # Write to NetCDF
                output_file = self.output_dir / f"ensemble_stats_{variable}.nc"
                self._write_stats_netcdf(
                    output_file, variable, mean, spread, percentiles
                )
                output_files.append(output_file)
                variables_computed.append(variable)

                # Compute probability of exceedance if thresholds configured
                thresholds = self.config.probability_thresholds.get(
                    variable, []
                )
                for threshold in thresholds:
                    prob = self.compute_probability_exceedance(
                        variable, threshold
                    )
                    if prob is not None:
                        prob_file = (
                            self.output_dir
                            / f"ensemble_prob_{variable}_gt_{threshold:.2f}.nc"
                        )
                        self._write_probability_netcdf(
                            prob_file, variable, threshold, prob
                        )
                        output_files.append(prob_file)

            except Exception as e:
                log.error(f"Statistics failed for {variable}: {e}")
                errors.append(f"{variable}: {e}")

        success = len(variables_computed) > 0

        return EnsembleStatsResult(
            success=success,
            output_files=output_files,
            variables_computed=variables_computed,
            n_members_used=len(self.members),
            errors=errors,
            metadata={
                "percentiles": self.config.percentiles,
                "probability_thresholds": self.config.probability_thresholds,
            },
        )

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_ensemble_data(self, variable: str) -> Optional[Any]:
        """
        Load output data for a variable from all members and stack.

        Tries xarray first for lazy loading, falls back to netCDF4.

        Args:
            variable: Variable name.

        Returns:
            Stacked array with shape (n_members, ...) or xarray DataArray
            with 'member' dimension. None if loading fails.
        """
        if HAS_XARRAY:
            return self._load_xarray(variable)
        elif HAS_NETCDF4:
            return self._load_numpy(variable)
        else:
            log.error(
                "Neither xarray nor netCDF4 available for loading ensemble data"
            )
            return None

    def _load_xarray(self, variable: str) -> Optional[Any]:
        """Load ensemble data using xarray."""
        datasets = []

        for member in self.members:
            output_dir = member.data_dir / "output"
            if not output_dir.exists():
                output_dir = member.data_dir

            # Find output files containing this variable
            nc_files = list(output_dir.glob("*.nc"))
            if not nc_files:
                log.warning(
                    f"No NetCDF files found for member {member.member_id:04d}"
                )
                continue

            for nc_file in nc_files:
                try:
                    ds = xr.open_dataset(nc_file)
                    actual_name = _find_variable(ds, variable)
                    if actual_name:
                        datasets.append(ds[actual_name])
                        break
                    ds.close()
                except Exception:
                    continue

        if not datasets:
            log.warning(f"No data found for variable '{variable}'")
            return None

        # Stack along new 'member' dimension
        try:
            stacked = xr.concat(datasets, dim="member")
            return stacked
        except Exception as e:
            log.error(f"Failed to stack ensemble data for {variable}: {e}")
            return None

    def _load_numpy(self, variable: str) -> Optional[np.ndarray]:
        """Load ensemble data using netCDF4 into numpy arrays."""
        arrays = []

        for member in self.members:
            output_dir = member.data_dir / "output"
            if not output_dir.exists():
                output_dir = member.data_dir

            nc_files = list(output_dir.glob("*.nc"))
            found = False

            for nc_file in nc_files:
                try:
                    ds = Dataset(str(nc_file), "r")
                    actual_name = _find_variable(ds, variable)
                    if actual_name:
                        data = ds.variables[actual_name][:]
                        arrays.append(data)
                        found = True
                        ds.close()
                        break
                    ds.close()
                except Exception:
                    continue

            if not found:
                log.warning(
                    f"Variable '{variable}' not found for "
                    f"member {member.member_id:04d}"
                )

        if not arrays:
            return None

        # Stack along new axis 0 (member dimension)
        try:
            return np.stack(arrays, axis=0)
        except ValueError as e:
            log.error(
                f"Cannot stack arrays for {variable} (shape mismatch?): {e}"
            )
            return None

    # ------------------------------------------------------------------
    # NetCDF output
    # ------------------------------------------------------------------

    def _write_stats_netcdf(
        self,
        output_file: Path,
        variable: str,
        mean: Any,
        spread: Any,
        percentiles: Any,
    ) -> None:
        """
        Write ensemble statistics to a NetCDF file.

        Args:
            output_file: Output file path.
            variable: Variable name.
            mean: Mean array.
            spread: Spread (std dev) array.
            percentiles: Percentile data (dict or xr.Dataset).
        """
        if HAS_XARRAY and isinstance(mean, xr.DataArray):
            self._write_stats_xarray(
                output_file, variable, mean, spread, percentiles
            )
        elif HAS_NETCDF4:
            self._write_stats_netcdf4(
                output_file, variable, mean, spread, percentiles
            )
        else:
            log.error("No NetCDF writing library available")

    def _write_stats_xarray(
        self,
        output_file: Path,
        variable: str,
        mean: Any,
        spread: Any,
        percentiles: Any,
    ) -> None:
        """Write statistics using xarray."""
        ds = xr.Dataset()
        ds[f"{variable}_mean"] = mean
        ds[f"{variable}_spread"] = spread

        if isinstance(percentiles, xr.DataArray):
            ds[f"{variable}_percentiles"] = percentiles

        ds.attrs["description"] = (
            f"Ensemble statistics for {variable}"
        )
        ds.attrs["n_members"] = len(self.members)

        ds.to_netcdf(output_file)
        log.info(f"Wrote ensemble stats to {output_file}")

    def _write_stats_netcdf4(
        self,
        output_file: Path,
        variable: str,
        mean: np.ndarray,
        spread: np.ndarray,
        percentiles: Optional[Dict[float, np.ndarray]],
    ) -> None:
        """Write statistics using netCDF4."""
        try:
            nc = Dataset(str(output_file), "w", format="NETCDF4")

            # Create dimensions from mean shape
            for i, dim_size in enumerate(mean.shape):
                dim_name = f"dim_{i}"
                nc.createDimension(dim_name, dim_size)

            dim_names = tuple(f"dim_{i}" for i in range(len(mean.shape)))

            # Mean
            mean_var = nc.createVariable(
                f"{variable}_mean", "f4", dim_names, fill_value=-9999.0
            )
            mean_var[:] = mean
            mean_var.long_name = f"Ensemble mean of {variable}"

            # Spread
            spread_var = nc.createVariable(
                f"{variable}_spread", "f4", dim_names, fill_value=-9999.0
            )
            spread_var[:] = spread
            spread_var.long_name = f"Ensemble spread of {variable}"

            # Percentiles
            if percentiles and isinstance(percentiles, dict):
                for pct, data in percentiles.items():
                    pct_name = f"{variable}_p{int(pct):02d}"
                    pct_var = nc.createVariable(
                        pct_name, "f4", dim_names, fill_value=-9999.0
                    )
                    pct_var[:] = data
                    pct_var.long_name = (
                        f"{int(pct)}th percentile of {variable}"
                    )

            nc.description = f"Ensemble statistics for {variable}"
            nc.n_members = len(self.members)
            nc.close()

            log.info(f"Wrote ensemble stats to {output_file}")

        except Exception as e:
            log.error(f"Failed to write stats NetCDF: {e}")

    def _write_probability_netcdf(
        self,
        output_file: Path,
        variable: str,
        threshold: float,
        probability: Any,
    ) -> None:
        """
        Write probability of exceedance to NetCDF.

        Args:
            output_file: Output file path.
            variable: Variable name.
            threshold: Exceedance threshold value.
            probability: Probability array (0-1).
        """
        if HAS_XARRAY and isinstance(probability, xr.DataArray):
            ds = xr.Dataset()
            ds[f"prob_{variable}_gt_{threshold:.2f}"] = probability
            ds.attrs["threshold"] = threshold
            ds.attrs["variable"] = variable
            ds.attrs["n_members"] = len(self.members)
            ds.to_netcdf(output_file)
        elif HAS_NETCDF4:
            try:
                nc = Dataset(str(output_file), "w", format="NETCDF4")

                prob_arr = np.asarray(probability)
                for i, dim_size in enumerate(prob_arr.shape):
                    nc.createDimension(f"dim_{i}", dim_size)

                dim_names = tuple(
                    f"dim_{i}" for i in range(len(prob_arr.shape))
                )
                var = nc.createVariable(
                    f"prob_{variable}_exceedance",
                    "f4",
                    dim_names,
                    fill_value=-9999.0,
                )
                var[:] = prob_arr
                var.long_name = (
                    f"Probability of {variable} exceeding {threshold}"
                )
                var.units = "fraction"
                var.threshold = threshold

                nc.description = (
                    f"Probability of {variable} > {threshold}"
                )
                nc.n_members = len(self.members)
                nc.close()

            except Exception as e:
                log.error(f"Failed to write probability NetCDF: {e}")

        log.info(f"Wrote probability file to {output_file}")
