"""
Ensemble Visualization Helpers

Provides plotting utilities for ensemble forecast analysis:
- Spaghetti plots: All members at a single station
- Spread maps: Spatial distribution of ensemble uncertainty
- Probability maps: Exceedance probability spatial maps
- Rank histograms: Ensemble calibration assessment

All visualization depends on matplotlib. This module is optional --
if matplotlib is not installed, importing raises ImportError which is
caught by the ensemble __init__.py and EnsemblePlotter is set to None.

Usage:
    from nos_ofs.ensemble import EnsemblePlotter

    if EnsemblePlotter is not None:
        plotter = EnsemblePlotter(members, output_dir)
        fig = plotter.spaghetti_plot("station_001", "zeta")
        fig.savefig("spaghetti.png")
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

log = logging.getLogger(__name__)

# matplotlib is required for this module
import matplotlib

matplotlib.use("Agg")  # Non-interactive backend for HPC
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from matplotlib.figure import Figure

# Optional imports for data loading
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


# Variable name mapping (same as statistics module)
VARIABLE_NAME_MAP = {
    "zeta": ["zeta", "elevation", "eta2", "elev", "ssh", "surf_el"],
    "temp": ["temp", "temperature", "tr_nd1"],
    "salt": ["salt", "salinity", "tr_nd2"],
    "u": ["u", "horizontalVelX", "u_vel"],
    "v": ["v", "horizontalVelY", "v_vel"],
}

VARIABLE_UNITS = {
    "zeta": "m",
    "temp": "C",
    "salt": "PSU",
    "u": "m/s",
    "v": "m/s",
}

VARIABLE_LABELS = {
    "zeta": "Sea Surface Height",
    "temp": "Temperature",
    "salt": "Salinity",
    "u": "U-velocity",
    "v": "V-velocity",
}


class EnsemblePlotter:
    """
    Ensemble visualization helper.

    Generates publication-quality plots for ensemble forecast analysis.
    All plots are returned as matplotlib Figure objects for maximum
    flexibility (users can further customize before saving).

    Attributes:
        members: List of EnsembleMember instances with completed outputs.
        output_dir: Directory for saving generated figures.
    """

    def __init__(
        self,
        members: List[Any],
        output_dir: Optional[Path] = None,
    ):
        """
        Initialize ensemble plotter.

        Args:
            members: List of EnsembleMember instances.
            output_dir: Optional directory for auto-saving figures.
        """
        self.members = members
        self.output_dir = Path(output_dir) if output_dir else None

        if self.output_dir:
            self.output_dir.mkdir(parents=True, exist_ok=True)

    def spaghetti_plot(
        self,
        station_id: str,
        variable: str,
        time_range: Optional[Tuple] = None,
        figsize: Tuple[float, float] = (12, 6),
        alpha: float = 0.3,
        show_mean: bool = True,
        show_spread: bool = True,
        show_percentiles: Optional[List[float]] = None,
        title: Optional[str] = None,
    ) -> Figure:
        """
        Spaghetti plot of all ensemble members at a station.

        Overlays time series from all members with optional mean,
        spread envelope, and percentile lines.

        Args:
            station_id: Station identifier or index.
            variable: Variable name (e.g., 'zeta', 'temp').
            time_range: Optional (start, end) datetime tuple for x-axis.
            figsize: Figure size in inches.
            alpha: Transparency for individual member lines.
            show_mean: Whether to draw the ensemble mean.
            show_spread: Whether to show +/- 1 std envelope.
            show_percentiles: List of percentiles to draw (e.g., [10, 90]).
            title: Custom plot title.

        Returns:
            matplotlib Figure object.
        """
        fig, ax = plt.subplots(figsize=figsize)

        # Load timeseries for each member at this station
        all_series = []
        time_axis = None

        for member in self.members:
            ts, times = self._load_station_timeseries(
                member, station_id, variable
            )
            if ts is not None:
                all_series.append(ts)
                if time_axis is None:
                    time_axis = times

        if not all_series:
            ax.text(
                0.5, 0.5,
                f"No data found for station={station_id}, var={variable}",
                ha="center", va="center", transform=ax.transAxes,
            )
            return fig

        # Stack: (n_members, n_times)
        ensemble_data = np.array(all_series)
        n_members = ensemble_data.shape[0]

        # Create x-axis (time indices or actual times)
        if time_axis is not None:
            x = time_axis
        else:
            x = np.arange(ensemble_data.shape[1])

        # Plot individual members
        for i in range(n_members):
            ax.plot(
                x,
                ensemble_data[i],
                color="steelblue",
                alpha=alpha,
                linewidth=0.8,
                label="Members" if i == 0 else None,
            )

        # Ensemble mean
        if show_mean:
            mean = np.nanmean(ensemble_data, axis=0)
            ax.plot(
                x, mean, color="darkred", linewidth=2.0,
                label="Mean", zorder=5,
            )

        # Spread envelope
        if show_spread:
            mean = np.nanmean(ensemble_data, axis=0)
            std = np.nanstd(ensemble_data, axis=0)
            ax.fill_between(
                x,
                mean - std,
                mean + std,
                alpha=0.2,
                color="coral",
                label="Mean +/- 1 std",
                zorder=3,
            )

        # Percentiles
        if show_percentiles:
            colors = plt.cm.viridis(
                np.linspace(0.2, 0.8, len(show_percentiles))
            )
            for pct, color in zip(show_percentiles, colors):
                pct_values = np.nanpercentile(ensemble_data, pct, axis=0)
                ax.plot(
                    x, pct_values,
                    color=color, linewidth=1.5, linestyle="--",
                    label=f"P{int(pct)}", zorder=4,
                )

        # Labels
        var_label = VARIABLE_LABELS.get(variable, variable)
        var_units = VARIABLE_UNITS.get(variable, "")
        unit_str = f" ({var_units})" if var_units else ""

        if title:
            ax.set_title(title)
        else:
            ax.set_title(
                f"Ensemble Spaghetti Plot: {var_label} at {station_id} "
                f"({n_members} members)"
            )

        ax.set_ylabel(f"{var_label}{unit_str}")
        ax.set_xlabel("Time")
        ax.legend(loc="best", fontsize=9)
        ax.grid(True, alpha=0.3)

        fig.tight_layout()

        if self.output_dir:
            fig.savefig(
                self.output_dir / f"spaghetti_{variable}_{station_id}.png",
                dpi=150,
                bbox_inches="tight",
            )

        return fig

    def spread_map(
        self,
        variable: str,
        time_index: int = 0,
        figsize: Tuple[float, float] = (10, 8),
        cmap: str = "YlOrRd",
        title: Optional[str] = None,
    ) -> Figure:
        """
        Spatial map of ensemble spread (standard deviation).

        Shows where uncertainty is greatest across the model domain.

        Args:
            variable: Variable name.
            time_index: Time step index to plot.
            figsize: Figure size.
            cmap: Matplotlib colormap name.
            title: Custom title.

        Returns:
            matplotlib Figure.
        """
        fig, ax = plt.subplots(figsize=figsize)

        # Load 2D field from each member and compute spread
        fields = []
        for member in self.members:
            field_data = self._load_2d_field(member, variable, time_index)
            if field_data is not None:
                fields.append(field_data)

        if not fields:
            ax.text(
                0.5, 0.5,
                f"No 2D data found for {variable}",
                ha="center", va="center", transform=ax.transAxes,
            )
            return fig

        ensemble_arr = np.array(fields)
        spread = np.nanstd(ensemble_arr, axis=0)

        # Plot spread
        im = ax.pcolormesh(spread, cmap=cmap, shading="auto")
        cbar = fig.colorbar(im, ax=ax, shrink=0.8)

        var_label = VARIABLE_LABELS.get(variable, variable)
        var_units = VARIABLE_UNITS.get(variable, "")

        cbar.set_label(f"Spread ({var_units})" if var_units else "Spread")

        if title:
            ax.set_title(title)
        else:
            ax.set_title(
                f"Ensemble Spread: {var_label}, "
                f"t={time_index} ({len(fields)} members)"
            )

        ax.set_xlabel("Grid X")
        ax.set_ylabel("Grid Y")
        fig.tight_layout()

        if self.output_dir:
            fig.savefig(
                self.output_dir / f"spread_map_{variable}_t{time_index:04d}.png",
                dpi=150,
                bbox_inches="tight",
            )

        return fig

    def probability_map(
        self,
        variable: str,
        threshold: float,
        time_index: int = 0,
        figsize: Tuple[float, float] = (10, 8),
        cmap: str = "RdYlBu_r",
        title: Optional[str] = None,
    ) -> Figure:
        """
        Spatial map of probability of exceedance.

        Shows the fraction of ensemble members where the variable
        exceeds the given threshold. Essential for flood risk assessment.

        Args:
            variable: Variable name (typically 'zeta' for storm surge).
            threshold: Exceedance threshold in native units.
            time_index: Time step index.
            figsize: Figure size.
            cmap: Colormap.
            title: Custom title.

        Returns:
            matplotlib Figure.
        """
        fig, ax = plt.subplots(figsize=figsize)

        fields = []
        for member in self.members:
            field_data = self._load_2d_field(member, variable, time_index)
            if field_data is not None:
                fields.append(field_data)

        if not fields:
            ax.text(
                0.5, 0.5,
                f"No data for {variable}",
                ha="center", va="center", transform=ax.transAxes,
            )
            return fig

        ensemble_arr = np.array(fields)
        prob = np.nanmean(ensemble_arr > threshold, axis=0)

        im = ax.pcolormesh(
            prob, cmap=cmap, shading="auto", vmin=0, vmax=1
        )
        cbar = fig.colorbar(im, ax=ax, shrink=0.8)
        cbar.set_label("Probability")

        var_label = VARIABLE_LABELS.get(variable, variable)
        var_units = VARIABLE_UNITS.get(variable, "")

        if title:
            ax.set_title(title)
        else:
            ax.set_title(
                f"P({var_label} > {threshold}{var_units}), "
                f"t={time_index} ({len(fields)} members)"
            )

        ax.set_xlabel("Grid X")
        ax.set_ylabel("Grid Y")
        fig.tight_layout()

        if self.output_dir:
            fig.savefig(
                self.output_dir
                / f"prob_map_{variable}_gt{threshold:.2f}_t{time_index:04d}.png",
                dpi=150,
                bbox_inches="tight",
            )

        return fig

    def rank_histogram(
        self,
        variable: str,
        observation_file: Optional[Path] = None,
        figsize: Tuple[float, float] = (8, 5),
        title: Optional[str] = None,
    ) -> Figure:
        """
        Rank histogram for ensemble calibration assessment.

        A rank histogram (Talagrand diagram) shows where observations
        fall relative to the sorted ensemble. A well-calibrated ensemble
        produces a uniform rank histogram.

        Common patterns:
        - U-shaped: under-dispersive (spread too small)
        - Dome-shaped: over-dispersive (spread too large)
        - Skewed: biased ensemble

        Args:
            variable: Variable name.
            observation_file: Path to observation NetCDF with 'obs' variable.
                             If None, uses synthetic observations (mean + noise)
                             for demonstration purposes.
            figsize: Figure size.
            title: Custom title.

        Returns:
            matplotlib Figure.
        """
        fig, ax = plt.subplots(figsize=figsize)

        # Load ensemble data
        all_data = []
        for member in self.members:
            data = self._load_all_values(member, variable)
            if data is not None:
                all_data.append(data.flatten())

        if len(all_data) < 2:
            ax.text(
                0.5, 0.5,
                "Insufficient ensemble data for rank histogram",
                ha="center", va="center", transform=ax.transAxes,
            )
            return fig

        # Truncate to common length
        min_len = min(len(d) for d in all_data)
        ensemble_matrix = np.array([d[:min_len] for d in all_data])
        n_members = ensemble_matrix.shape[0]

        # Get or synthesize observations
        if observation_file and Path(observation_file).exists():
            obs = self._load_observations(observation_file, variable)
            if obs is not None:
                obs = obs.flatten()[:min_len]
            else:
                obs = None

        if observation_file is None or obs is None:
            # Synthetic: use ensemble mean + small noise for demonstration
            obs = np.nanmean(ensemble_matrix, axis=0) + np.random.normal(
                0, np.nanstd(ensemble_matrix, axis=0) * 0.5, min_len
            )

        # Compute ranks
        ranks = np.zeros(min_len, dtype=int)
        for i in range(min_len):
            sorted_members = np.sort(ensemble_matrix[:, i])
            rank = np.searchsorted(sorted_members, obs[i])
            ranks[i] = rank

        # Plot histogram
        bins = np.arange(n_members + 2) - 0.5
        ax.hist(
            ranks, bins=bins, density=True,
            color="steelblue", edgecolor="white", alpha=0.8,
        )

        # Reference line for uniform distribution
        uniform_level = 1.0 / (n_members + 1)
        ax.axhline(
            uniform_level, color="red", linestyle="--",
            linewidth=1.5, label="Uniform reference",
        )

        var_label = VARIABLE_LABELS.get(variable, variable)

        if title:
            ax.set_title(title)
        else:
            ax.set_title(
                f"Rank Histogram: {var_label} ({n_members} members)"
            )

        ax.set_xlabel("Rank")
        ax.set_ylabel("Relative Frequency")
        ax.legend()
        ax.set_xlim(-0.5, n_members + 0.5)
        fig.tight_layout()

        if self.output_dir:
            fig.savefig(
                self.output_dir / f"rank_histogram_{variable}.png",
                dpi=150,
                bbox_inches="tight",
            )

        return fig

    # ------------------------------------------------------------------
    # Data loading helpers
    # ------------------------------------------------------------------

    def _load_station_timeseries(
        self,
        member: Any,
        station_id: str,
        variable: str,
    ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """
        Load time series for a variable at a station from member output.

        Args:
            member: EnsembleMember.
            station_id: Station identifier or index.
            variable: Variable name.

        Returns:
            Tuple of (data_array, time_array) or (None, None).
        """
        output_dir = member.data_dir / "output"
        if not output_dir.exists():
            output_dir = member.data_dir

        # Try station output files
        station_patterns = [
            "staout_*",
            "*station*.nc",
            f"*{variable}*station*.nc",
        ]

        for pattern in station_patterns:
            files = list(output_dir.glob(pattern))
            for f in files:
                if f.suffix == ".nc" and HAS_NETCDF4:
                    try:
                        ds = Dataset(str(f), "r")

                        # Try to find variable
                        candidates = VARIABLE_NAME_MAP.get(
                            variable, [variable]
                        )
                        for var_name in candidates:
                            if var_name in ds.variables:
                                data = ds.variables[var_name][:]

                                # Extract station dimension
                                try:
                                    sta_idx = int(station_id)
                                except ValueError:
                                    sta_idx = 0

                                if data.ndim >= 2 and sta_idx < data.shape[1]:
                                    ts = data[:, sta_idx]
                                elif data.ndim == 1:
                                    ts = data
                                else:
                                    ts = data.flatten()

                                times = None
                                if "time" in ds.variables:
                                    times = ds.variables["time"][:]

                                ds.close()
                                return ts, times

                        ds.close()
                    except Exception:
                        continue

        return None, None

    def _load_2d_field(
        self,
        member: Any,
        variable: str,
        time_index: int,
    ) -> Optional[np.ndarray]:
        """Load a 2D field at a given time index from member output."""
        output_dir = member.data_dir / "output"
        if not output_dir.exists():
            output_dir = member.data_dir

        nc_files = list(output_dir.glob("*.nc"))

        for nc_file in nc_files:
            if not HAS_NETCDF4:
                continue
            try:
                ds = Dataset(str(nc_file), "r")
                candidates = VARIABLE_NAME_MAP.get(variable, [variable])

                for var_name in candidates:
                    if var_name in ds.variables:
                        data = ds.variables[var_name][:]

                        # Extract time slice
                        if data.ndim >= 3 and time_index < data.shape[0]:
                            field = data[time_index]
                        elif data.ndim == 2:
                            field = data
                        elif data.ndim == 1:
                            # 1D unstructured -- return as-is
                            if data.shape[0] > time_index:
                                field = data
                            else:
                                continue
                        else:
                            continue

                        ds.close()
                        return field

                ds.close()
            except Exception:
                continue

        return None

    def _load_all_values(
        self,
        member: Any,
        variable: str,
    ) -> Optional[np.ndarray]:
        """Load all values for a variable from member output (flattened)."""
        output_dir = member.data_dir / "output"
        if not output_dir.exists():
            output_dir = member.data_dir

        nc_files = list(output_dir.glob("*.nc"))

        for nc_file in nc_files:
            if not HAS_NETCDF4:
                continue
            try:
                ds = Dataset(str(nc_file), "r")
                candidates = VARIABLE_NAME_MAP.get(variable, [variable])

                for var_name in candidates:
                    if var_name in ds.variables:
                        data = ds.variables[var_name][:]
                        ds.close()
                        return data

                ds.close()
            except Exception:
                continue

        return None

    @staticmethod
    def _load_observations(
        obs_file: Path, variable: str
    ) -> Optional[np.ndarray]:
        """Load observation data from a NetCDF file."""
        if not HAS_NETCDF4:
            return None

        try:
            ds = Dataset(str(obs_file), "r")
            candidates = VARIABLE_NAME_MAP.get(variable, [variable])
            candidates = [f"obs_{c}" for c in candidates] + candidates

            for var_name in candidates:
                if var_name in ds.variables:
                    data = ds.variables[var_name][:]
                    ds.close()
                    return data

            ds.close()
        except Exception:
            pass

        return None
