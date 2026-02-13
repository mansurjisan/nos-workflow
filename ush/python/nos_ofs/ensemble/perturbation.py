"""
Perturbation Generators for Ensemble Forecasting

Implements multiple perturbation strategies for creating diverse ensemble
members from a single deterministic model configuration:

Initial Condition Perturbations:
    GaussianICPerturbation   -- Spatially-correlated Gaussian noise on IC fields
    EOFPerturbation          -- Perturbations along dominant EOF modes
    HistoricalPerturbation   -- Sample from historical forecast error archive

Atmospheric Forcing Perturbations:
    WindPerturbation         -- Perturb wind speed and direction
    PressurePerturbation     -- Perturb sea level pressure
    PrecipPerturbation       -- Perturb precipitation rate

Boundary Condition Perturbations:
    OBCPerturbation          -- Perturb RTOFS boundary T/S/SSH/velocity

Model Parameter Perturbations:
    BottomFrictionPerturbation  -- Perturb bottom roughness
    WindDragPerturbation        -- Perturb wind drag coefficient
    MixingPerturbation          -- Perturb vertical mixing parameters

All perturbation classes use numpy.random.Generator (modern API) for
reproducible random number generation and support spatially-correlated
perturbation fields via FFT-based Gaussian random field generation.
"""

import copy
import logging
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

log = logging.getLogger(__name__)

# Optional imports for file manipulation
try:
    from netCDF4 import Dataset

    HAS_NETCDF4 = True
except ImportError:
    HAS_NETCDF4 = False


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class PerturbationResult:
    """Result of applying a perturbation to an ensemble member.

    Attributes:
        success: Whether perturbation was applied successfully.
        perturbation_type: Human-readable type identifier.
        member_id: Ensemble member index.
        description: Human-readable description of what was perturbed.
        modified_files: List of files that were modified or created.
        parameters: Dictionary of perturbed parameter values (for parameter perturbations).
        metadata: Additional metadata about the perturbation.
        errors: List of error messages if the perturbation failed.
    """

    success: bool
    perturbation_type: str
    member_id: int
    description: str = ""
    modified_files: List[Path] = field(default_factory=list)
    parameters: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Gaussian random field generator (FFT-based)
# ---------------------------------------------------------------------------


class GaussianRandomField:
    """
    Generate spatially-correlated Gaussian random fields using FFT.

    Uses the spectral method: generate white noise in Fourier space,
    multiply by the square root of the desired power spectrum (derived
    from the correlation length), then inverse FFT to real space.

    This produces fields with Gaussian marginal distribution and
    isotropic spatial correlation characterized by the given length scale.

    Attributes:
        rng: numpy random Generator for reproducibility.
    """

    def __init__(self, rng: np.random.Generator):
        """
        Initialize the Gaussian random field generator.

        Args:
            rng: numpy.random.Generator instance for reproducibility.
        """
        self.rng = rng

    def generate_2d(
        self,
        ny: int,
        nx: int,
        correlation_length: float,
        dx: float = 1.0,
        dy: float = 1.0,
    ) -> np.ndarray:
        """
        Generate a 2D spatially-correlated Gaussian random field.

        The field has zero mean and unit variance before scaling. The
        correlation structure follows exp(-r^2 / (2 * L^2)) where L is
        the correlation length.

        Args:
            ny: Number of grid points in y direction.
            nx: Number of grid points in x direction.
            correlation_length: Correlation length in grid units (same
                                units as dx/dy).
            dx: Grid spacing in x direction (default 1.0 for grid-unit
                correlation length).
            dy: Grid spacing in y direction (default 1.0).

        Returns:
            2D numpy array of shape (ny, nx) with the random field,
            normalized to zero mean and unit variance.
        """
        if correlation_length <= 0:
            # No spatial correlation -- pure white noise
            return self.rng.standard_normal((ny, nx))

        # Frequency grids
        kx = np.fft.fftfreq(nx, d=dx)
        ky = np.fft.fftfreq(ny, d=dy)
        KX, KY = np.meshgrid(kx, ky)
        K2 = KX ** 2 + KY ** 2

        # Power spectrum: Gaussian covariance -> Gaussian spectrum
        # Covariance: C(r) = exp(-r^2 / (2L^2))
        # Power spectrum: P(k) ~ exp(-2 pi^2 L^2 k^2)
        L = correlation_length
        power_spectrum = np.exp(-2.0 * (np.pi ** 2) * (L ** 2) * K2)

        # Generate complex white noise
        noise_real = self.rng.standard_normal((ny, nx))
        noise_imag = self.rng.standard_normal((ny, nx))
        noise_fft = noise_real + 1j * noise_imag

        # Multiply by sqrt of power spectrum and inverse FFT
        filtered = noise_fft * np.sqrt(power_spectrum)
        field_raw = np.real(np.fft.ifft2(filtered))

        # Normalize to zero mean, unit variance
        std = field_raw.std()
        if std > 0:
            field_raw = (field_raw - field_raw.mean()) / std

        return field_raw

    def generate_3d(
        self,
        nz: int,
        ny: int,
        nx: int,
        correlation_length_h: float,
        correlation_length_v: float,
        dx: float = 1.0,
        dy: float = 1.0,
        dz: float = 1.0,
    ) -> np.ndarray:
        """
        Generate a 3D spatially-correlated Gaussian random field.

        Horizontal and vertical correlation lengths can differ to capture
        the anisotropy typical in ocean models.

        Args:
            nz: Number of levels in z direction.
            ny: Number of grid points in y direction.
            nx: Number of grid points in x direction.
            correlation_length_h: Horizontal correlation length.
            correlation_length_v: Vertical correlation length.
            dx: Grid spacing in x.
            dy: Grid spacing in y.
            dz: Grid spacing in z.

        Returns:
            3D numpy array of shape (nz, ny, nx).
        """
        if correlation_length_h <= 0 and correlation_length_v <= 0:
            return self.rng.standard_normal((nz, ny, nx))

        kx = np.fft.fftfreq(nx, d=dx)
        ky = np.fft.fftfreq(ny, d=dy)
        kz = np.fft.fftfreq(nz, d=dz)
        # meshgrid with indexing="ij" and order (kz, ky, kx) produces
        # shape (nz, ny, nx) directly -- matching the output array layout.
        KZ, KY, KX = np.meshgrid(kz, ky, kx, indexing="ij")

        Lh = max(correlation_length_h, 1e-10)
        Lv = max(correlation_length_v, 1e-10)

        K2_h = KX ** 2 + KY ** 2
        K2_v = KZ ** 2
        power = np.exp(
            -2.0 * (np.pi ** 2) * (Lh ** 2 * K2_h + Lv ** 2 * K2_v)
        )

        noise = self.rng.standard_normal((nz, ny, nx)) + 1j * self.rng.standard_normal(
            (nz, ny, nx)
        )
        filtered = noise * np.sqrt(power)
        field_raw = np.real(np.fft.ifftn(filtered))

        std = field_raw.std()
        if std > 0:
            field_raw = (field_raw - field_raw.mean()) / std

        return field_raw

    def generate_temporal_ar1(
        self,
        n_times: int,
        shape: Tuple[int, ...],
        correlation_length_spatial: float,
        correlation_time_hours: float,
        dt_hours: float = 1.0,
    ) -> np.ndarray:
        """
        Generate a time-varying spatially-correlated random field with
        AR(1) temporal correlation.

        At each timestep, the field is a blend of the previous field
        (with coefficient phi) and a new independent random field
        (with coefficient sqrt(1-phi^2)), where phi = exp(-dt/tau).

        Args:
            n_times: Number of time steps.
            shape: Spatial shape tuple (e.g., (ny, nx)).
            correlation_length_spatial: Spatial correlation length in
                                        grid units.
            correlation_time_hours: Temporal e-folding time in hours.
            dt_hours: Time step interval in hours.

        Returns:
            Array of shape (n_times, *shape).
        """
        if correlation_time_hours <= 0:
            # No temporal correlation
            fields = np.zeros((n_times,) + shape)
            for t in range(n_times):
                fields[t] = self.generate_2d(
                    shape[0], shape[1], correlation_length_spatial
                )
            return fields

        phi = math.exp(-dt_hours / correlation_time_hours)
        innovation_scale = math.sqrt(1.0 - phi ** 2)

        fields = np.zeros((n_times,) + shape)
        fields[0] = self.generate_2d(
            shape[0], shape[1], correlation_length_spatial
        )

        for t in range(1, n_times):
            innovation = self.generate_2d(
                shape[0], shape[1], correlation_length_spatial
            )
            fields[t] = phi * fields[t - 1] + innovation_scale * innovation

        return fields


# ---------------------------------------------------------------------------
# Abstract base perturbation
# ---------------------------------------------------------------------------


class BasePerturbation(ABC):
    """
    Abstract base class for all perturbation generators.

    Subclasses implement the ``apply()`` method which modifies files or
    configuration for a specific ensemble member, and the ``describe()``
    method which returns a human-readable summary.

    Attributes:
        config: The perturbation-specific configuration object.
        rng: numpy random Generator instance for this perturbation.
        grf: GaussianRandomField helper for spatially-correlated fields.
    """

    def __init__(self, config: Any, rng: np.random.Generator):
        """
        Initialize base perturbation.

        Args:
            config: Perturbation-specific configuration dataclass.
            rng: numpy.random.Generator for reproducible random numbers.
        """
        self.config = config
        self.rng = rng
        self.grf = GaussianRandomField(rng)

    @abstractmethod
    def apply(self, member_id: int, data_dir: Path) -> PerturbationResult:
        """
        Apply perturbation for a specific ensemble member.

        Args:
            member_id: Ensemble member index (0-based).
            data_dir: Working directory for this member containing input files
                      to be perturbed.

        Returns:
            PerturbationResult describing what was modified.
        """
        pass

    @abstractmethod
    def describe(self) -> str:
        """Return a human-readable description of this perturbation."""
        pass


# ---------------------------------------------------------------------------
# Initial Condition Perturbations
# ---------------------------------------------------------------------------


class GaussianICPerturbation(BasePerturbation):
    """
    Add spatially-correlated Gaussian noise to initial condition fields.

    Reads the hotstart/restart NetCDF file, adds perturbation fields to
    the specified variables (temperature, salinity, SSH), and writes
    the modified file back.

    The perturbation for each variable is: field' = field + std_dev * GRF
    where GRF is a normalized Gaussian random field with the configured
    spatial correlation length.
    """

    def apply(self, member_id: int, data_dir: Path) -> PerturbationResult:
        """Apply Gaussian IC perturbation to hotstart file."""
        if not HAS_NETCDF4:
            return PerturbationResult(
                success=False,
                perturbation_type="gaussian_ic",
                member_id=member_id,
                errors=["netCDF4 not available for IC perturbation"],
            )

        modified_files = []
        descriptions = []

        # Find hotstart/restart file in data_dir
        hotstart_file = self._find_hotstart(data_dir)
        if hotstart_file is None:
            return PerturbationResult(
                success=False,
                perturbation_type="gaussian_ic",
                member_id=member_id,
                errors=[f"No hotstart file found in {data_dir}"],
            )

        try:
            ds = Dataset(str(hotstart_file), "r+")

            for var_name, var_config in self.config.variables.items():
                nc_var_name = self._map_variable_name(var_name)
                if nc_var_name not in ds.variables:
                    log.warning(
                        f"Variable {nc_var_name} not found in {hotstart_file}, "
                        f"skipping IC perturbation for {var_name}"
                    )
                    continue

                nc_var = ds.variables[nc_var_name]
                shape = nc_var.shape
                data = nc_var[:]

                # Generate perturbation field matching shape
                if len(shape) == 1:
                    # 1D field (e.g., SSH on unstructured grid)
                    pert = self.rng.standard_normal(shape) * var_config.std_dev
                elif len(shape) == 2:
                    # 2D field
                    pert = (
                        self.grf.generate_2d(
                            shape[0], shape[1], var_config.correlation_length
                        )
                        * var_config.std_dev
                    )
                elif len(shape) == 3:
                    # 3D field (nz, ny, nx) or (nelem, nlev, ...)
                    pert = (
                        self.grf.generate_3d(
                            shape[0],
                            shape[1],
                            shape[2],
                            var_config.correlation_length,
                            var_config.correlation_length / 5.0,
                        )
                        * var_config.std_dev
                    )
                else:
                    log.warning(
                        f"Unsupported shape {shape} for {nc_var_name}, "
                        f"using flat noise"
                    )
                    pert = (
                        self.rng.standard_normal(shape) * var_config.std_dev
                    )

                perturbed = data + pert

                # Apply clamping
                if var_config.clamp_min is not None:
                    perturbed = np.maximum(perturbed, var_config.clamp_min)
                if var_config.clamp_max is not None:
                    perturbed = np.minimum(perturbed, var_config.clamp_max)

                nc_var[:] = perturbed
                descriptions.append(
                    f"{var_name}: std={var_config.std_dev}, "
                    f"corr_len={var_config.correlation_length}km"
                )

            ds.close()
            modified_files.append(hotstart_file)

            return PerturbationResult(
                success=True,
                perturbation_type="gaussian_ic",
                member_id=member_id,
                description=f"Gaussian IC: {'; '.join(descriptions)}",
                modified_files=modified_files,
                metadata={
                    "variables": list(self.config.variables.keys()),
                },
            )

        except Exception as e:
            log.error(f"Failed to apply Gaussian IC perturbation: {e}")
            return PerturbationResult(
                success=False,
                perturbation_type="gaussian_ic",
                member_id=member_id,
                errors=[str(e)],
            )

    def describe(self) -> str:
        """Return description of Gaussian IC perturbation."""
        var_desc = []
        for name, cfg in self.config.variables.items():
            var_desc.append(
                f"{name}(std={cfg.std_dev}, L={cfg.correlation_length}km)"
            )
        return f"Gaussian IC perturbation: {', '.join(var_desc)}"

    @staticmethod
    def _find_hotstart(data_dir: Path) -> Optional[Path]:
        """Find hotstart/restart NetCDF file in data_dir."""
        patterns = [
            "hotstart*.nc",
            "*restart*.nc",
            "hotstart.nc",
            "*.hotstart.nc",
        ]
        for pattern in patterns:
            matches = list(data_dir.glob(pattern))
            if matches:
                return matches[0]
        return None

    @staticmethod
    def _map_variable_name(name: str) -> str:
        """Map user-friendly variable name to NetCDF variable name."""
        mapping = {
            "temperature": "tr_nd1",
            "temp": "tr_nd1",
            "salinity": "tr_nd2",
            "salt": "tr_nd2",
            "ssh": "eta2",
            "elevation": "eta2",
            "zeta": "eta2",
        }
        return mapping.get(name.lower(), name)


class EOFPerturbation(BasePerturbation):
    """
    Perturb initial conditions along dominant EOF (Empirical Orthogonal
    Function) modes.

    This is a more physically constrained approach that perturbs the
    initial state in directions that represent the dominant variability
    patterns. Requires pre-computed EOF data from a historical archive.

    The perturbation is: field' = field + sum_i (alpha_i * sqrt(lambda_i) * EOF_i)
    where alpha_i ~ N(0,1) and lambda_i is the eigenvalue of mode i.
    """

    def apply(self, member_id: int, data_dir: Path) -> PerturbationResult:
        """Apply EOF-based perturbation to initial conditions."""
        eof_path = self.config.eof_data_path
        if eof_path is None or not Path(eof_path).exists():
            return PerturbationResult(
                success=False,
                perturbation_type="eof_ic",
                member_id=member_id,
                errors=[
                    f"EOF data not found at {eof_path}. "
                    "Pre-compute EOF modes from historical data first."
                ],
            )

        if not HAS_NETCDF4:
            return PerturbationResult(
                success=False,
                perturbation_type="eof_ic",
                member_id=member_id,
                errors=["netCDF4 required for EOF perturbation"],
            )

        try:
            # Load EOF data
            eof_ds = Dataset(str(eof_path), "r")
            n_modes = min(self.config.eof_modes, len(eof_ds.dimensions.get("mode", [])))

            if n_modes == 0:
                eof_ds.close()
                return PerturbationResult(
                    success=False,
                    perturbation_type="eof_ic",
                    member_id=member_id,
                    errors=["No EOF modes found in data file"],
                )

            # Random amplitudes for each mode
            alphas = self.rng.standard_normal(n_modes)

            hotstart_file = GaussianICPerturbation._find_hotstart(data_dir)
            if hotstart_file is None:
                eof_ds.close()
                return PerturbationResult(
                    success=False,
                    perturbation_type="eof_ic",
                    member_id=member_id,
                    errors=[f"No hotstart file found in {data_dir}"],
                )

            hs_ds = Dataset(str(hotstart_file), "r+")

            for var_name in self.config.variables:
                nc_var_name = GaussianICPerturbation._map_variable_name(var_name)
                eof_var = f"eof_{var_name}"
                eval_var = f"eigenvalue_{var_name}"

                if eof_var not in eof_ds.variables:
                    log.warning(f"EOF variable {eof_var} not found, skipping")
                    continue

                if nc_var_name not in hs_ds.variables:
                    log.warning(f"Variable {nc_var_name} not in hotstart, skipping")
                    continue

                eofs = eof_ds.variables[eof_var][:]  # (n_modes, ...)
                eigenvalues = eof_ds.variables[eval_var][:n_modes]

                # Construct perturbation
                perturbation = np.zeros_like(hs_ds.variables[nc_var_name][:])
                for i in range(n_modes):
                    perturbation += alphas[i] * np.sqrt(eigenvalues[i]) * eofs[i]

                hs_ds.variables[nc_var_name][:] += perturbation

            hs_ds.close()
            eof_ds.close()

            return PerturbationResult(
                success=True,
                perturbation_type="eof_ic",
                member_id=member_id,
                description=(
                    f"EOF perturbation with {n_modes} modes, "
                    f"amplitudes={alphas[:3].tolist()}..."
                ),
                modified_files=[hotstart_file],
                metadata={
                    "n_modes": n_modes,
                    "amplitudes": alphas.tolist(),
                },
            )

        except Exception as e:
            log.error(f"EOF perturbation failed: {e}")
            return PerturbationResult(
                success=False,
                perturbation_type="eof_ic",
                member_id=member_id,
                errors=[str(e)],
            )

    def describe(self) -> str:
        return (
            f"EOF perturbation: {self.config.eof_modes} modes, "
            f"variables={list(self.config.variables.keys())}"
        )


class HistoricalPerturbation(BasePerturbation):
    """
    Sample perturbations from an archive of historical forecast errors.

    This approach uses the difference between past forecasts and analyses
    as representative error patterns, then randomly selects and applies
    one of these error patterns to the current initial condition.

    Requires a pre-built archive of (forecast - analysis) differences
    stored as a NetCDF file with dimensions (n_samples, ...).
    """

    def apply(self, member_id: int, data_dir: Path) -> PerturbationResult:
        """Apply historical error perturbation."""
        error_path = self.config.historical_error_path
        if error_path is None or not Path(error_path).exists():
            return PerturbationResult(
                success=False,
                perturbation_type="historical_ic",
                member_id=member_id,
                errors=[
                    f"Historical error archive not found at {error_path}. "
                    "Build archive from forecast-analysis pairs first."
                ],
            )

        if not HAS_NETCDF4:
            return PerturbationResult(
                success=False,
                perturbation_type="historical_ic",
                member_id=member_id,
                errors=["netCDF4 required for historical perturbation"],
            )

        try:
            archive = Dataset(str(error_path), "r")
            n_samples_dim = archive.dimensions.get("sample")
            if n_samples_dim is None:
                archive.close()
                return PerturbationResult(
                    success=False,
                    perturbation_type="historical_ic",
                    member_id=member_id,
                    errors=["Historical archive missing 'sample' dimension"],
                )

            n_samples = len(n_samples_dim)
            sample_idx = self.rng.integers(0, n_samples)

            hotstart_file = GaussianICPerturbation._find_hotstart(data_dir)
            if hotstart_file is None:
                archive.close()
                return PerturbationResult(
                    success=False,
                    perturbation_type="historical_ic",
                    member_id=member_id,
                    errors=[f"No hotstart file found in {data_dir}"],
                )

            hs_ds = Dataset(str(hotstart_file), "r+")

            modified_vars = []
            for var_name in self.config.variables:
                nc_var_name = GaussianICPerturbation._map_variable_name(var_name)
                error_var = f"error_{var_name}"

                if error_var not in archive.variables:
                    log.warning(f"Error variable {error_var} not in archive, skipping")
                    continue

                if nc_var_name not in hs_ds.variables:
                    log.warning(f"Variable {nc_var_name} not in hotstart, skipping")
                    continue

                error_pattern = archive.variables[error_var][sample_idx]
                hs_ds.variables[nc_var_name][:] += error_pattern
                modified_vars.append(var_name)

            hs_ds.close()
            archive.close()

            return PerturbationResult(
                success=True,
                perturbation_type="historical_ic",
                member_id=member_id,
                description=(
                    f"Historical error sample {sample_idx}/{n_samples}, "
                    f"variables={modified_vars}"
                ),
                modified_files=[hotstart_file],
                metadata={
                    "sample_index": int(sample_idx),
                    "n_samples_available": n_samples,
                    "variables": modified_vars,
                },
            )

        except Exception as e:
            log.error(f"Historical perturbation failed: {e}")
            return PerturbationResult(
                success=False,
                perturbation_type="historical_ic",
                member_id=member_id,
                errors=[str(e)],
            )

    def describe(self) -> str:
        return (
            f"Historical error perturbation from {self.config.historical_error_path}, "
            f"variables={list(self.config.variables.keys())}"
        )


# ---------------------------------------------------------------------------
# Atmospheric Forcing Perturbations
# ---------------------------------------------------------------------------


class WindPerturbation(BasePerturbation):
    """
    Perturb atmospheric wind forcing fields (speed and direction).

    Wind is one of the most important forcing variables for storm surge
    modeling. This perturbation adds spatially and temporally correlated
    noise to wind speed and direction.

    Speed perturbation: speed' = speed * (1 + pct/100 * GRF)
    Direction perturbation applied by rotating (u,v) components.

    Uses AR(1) temporal correlation for smooth perturbations over time.
    """

    def apply(self, member_id: int, data_dir: Path) -> PerturbationResult:
        """Apply wind perturbation to sflux air files."""
        if not HAS_NETCDF4:
            return PerturbationResult(
                success=False,
                perturbation_type="wind",
                member_id=member_id,
                errors=["netCDF4 required for wind perturbation"],
            )

        # Find sflux air files
        sflux_dir = data_dir / "sflux"
        if not sflux_dir.exists():
            sflux_dir = data_dir  # Files may be in data_dir directly

        air_files = sorted(sflux_dir.glob("sflux_air_*.nc"))
        if not air_files:
            return PerturbationResult(
                success=False,
                perturbation_type="wind",
                member_id=member_id,
                errors=[f"No sflux_air files found in {sflux_dir}"],
            )

        modified_files = []
        speed_pct = self.config.speed_std_pct
        dir_std = self.config.direction_std_deg
        corr_len = self.config.correlation_length
        corr_time = self.config.correlation_time_hours

        try:
            # Pre-generate a persistent direction offset field
            # (shared across all files for temporal consistency)
            direction_offset_rad = None

            for air_file in air_files:
                ds = Dataset(str(air_file), "r+")

                if "uwind" not in ds.variables or "vwind" not in ds.variables:
                    ds.close()
                    continue

                uwind = ds.variables["uwind"][:]
                vwind = ds.variables["vwind"][:]
                nt, ny, nx = uwind.shape

                # Generate speed perturbation field (time-varying, spatially correlated)
                speed_pert = self.grf.generate_temporal_ar1(
                    nt, (ny, nx), corr_len, corr_time
                )

                # Generate direction perturbation (time-varying)
                dir_pert = self.grf.generate_temporal_ar1(
                    nt, (ny, nx), corr_len, corr_time
                )

                for t in range(nt):
                    # Speed perturbation: multiply by (1 + fraction)
                    speed_factor = 1.0 + (speed_pct / 100.0) * speed_pert[t]
                    # Ensure speed factor stays positive
                    speed_factor = np.maximum(speed_factor, 0.1)

                    u_new = uwind[t] * speed_factor
                    v_new = vwind[t] * speed_factor

                    # Direction perturbation: rotate wind vector
                    angle_rad = np.deg2rad(dir_std) * dir_pert[t]
                    cos_a = np.cos(angle_rad)
                    sin_a = np.sin(angle_rad)

                    u_rot = u_new * cos_a - v_new * sin_a
                    v_rot = u_new * sin_a + v_new * cos_a

                    uwind[t] = u_rot
                    vwind[t] = v_rot

                ds.variables["uwind"][:] = uwind
                ds.variables["vwind"][:] = vwind
                ds.close()
                modified_files.append(air_file)

            return PerturbationResult(
                success=True,
                perturbation_type="wind",
                member_id=member_id,
                description=(
                    f"Wind: speed_std={speed_pct}%, dir_std={dir_std}deg, "
                    f"corr_len={corr_len}km, corr_time={corr_time}h"
                ),
                modified_files=modified_files,
                metadata={
                    "speed_std_pct": speed_pct,
                    "direction_std_deg": dir_std,
                    "n_files": len(modified_files),
                },
            )

        except Exception as e:
            log.error(f"Wind perturbation failed: {e}")
            return PerturbationResult(
                success=False,
                perturbation_type="wind",
                member_id=member_id,
                errors=[str(e)],
            )

    def describe(self) -> str:
        return (
            f"Wind perturbation: speed={self.config.speed_std_pct}%, "
            f"direction={self.config.direction_std_deg}deg, "
            f"corr_len={self.config.correlation_length}km, "
            f"corr_time={self.config.correlation_time_hours}h"
        )


class PressurePerturbation(BasePerturbation):
    """
    Perturb sea level pressure (PRMSL) in atmospheric forcing files.

    Adds spatially and temporally correlated Gaussian perturbation to
    the pressure field: prmsl' = prmsl + std_dev * GRF_temporal
    """

    def apply(self, member_id: int, data_dir: Path) -> PerturbationResult:
        """Apply pressure perturbation to sflux air files."""
        if not HAS_NETCDF4:
            return PerturbationResult(
                success=False,
                perturbation_type="pressure",
                member_id=member_id,
                errors=["netCDF4 required for pressure perturbation"],
            )

        sflux_dir = data_dir / "sflux"
        if not sflux_dir.exists():
            sflux_dir = data_dir

        air_files = sorted(sflux_dir.glob("sflux_air_*.nc"))
        if not air_files:
            return PerturbationResult(
                success=False,
                perturbation_type="pressure",
                member_id=member_id,
                errors=[f"No sflux_air files found in {sflux_dir}"],
            )

        modified_files = []
        std_dev = self.config.std_dev
        corr_len = self.config.correlation_length
        corr_time = self.config.correlation_time_hours

        try:
            for air_file in air_files:
                ds = Dataset(str(air_file), "r+")

                if "prmsl" not in ds.variables:
                    ds.close()
                    continue

                prmsl = ds.variables["prmsl"][:]
                nt, ny, nx = prmsl.shape

                pert = self.grf.generate_temporal_ar1(
                    nt, (ny, nx), corr_len, corr_time
                )

                ds.variables["prmsl"][:] = prmsl + std_dev * pert
                ds.close()
                modified_files.append(air_file)

            return PerturbationResult(
                success=True,
                perturbation_type="pressure",
                member_id=member_id,
                description=(
                    f"Pressure: std={std_dev}Pa, "
                    f"corr_len={corr_len}km, corr_time={corr_time}h"
                ),
                modified_files=modified_files,
            )

        except Exception as e:
            log.error(f"Pressure perturbation failed: {e}")
            return PerturbationResult(
                success=False,
                perturbation_type="pressure",
                member_id=member_id,
                errors=[str(e)],
            )

    def describe(self) -> str:
        return (
            f"Pressure perturbation: std={self.config.std_dev}Pa, "
            f"corr_len={self.config.correlation_length}km"
        )


class PrecipPerturbation(BasePerturbation):
    """
    Perturb precipitation rate (PRATE) in atmospheric forcing files.

    Uses multiplicative perturbation to preserve non-negativity:
    prate' = prate * exp(std * GRF)

    The log-normal approach ensures prate remains non-negative.
    """

    def apply(self, member_id: int, data_dir: Path) -> PerturbationResult:
        """Apply precipitation perturbation to sflux prc files."""
        if not HAS_NETCDF4:
            return PerturbationResult(
                success=False,
                perturbation_type="precipitation",
                member_id=member_id,
                errors=["netCDF4 required for precipitation perturbation"],
            )

        sflux_dir = data_dir / "sflux"
        if not sflux_dir.exists():
            sflux_dir = data_dir

        prc_files = sorted(sflux_dir.glob("sflux_prc_*.nc"))
        if not prc_files:
            return PerturbationResult(
                success=False,
                perturbation_type="precipitation",
                member_id=member_id,
                errors=[f"No sflux_prc files found in {sflux_dir}"],
            )

        modified_files = []
        std_pct = self.config.std_pct
        corr_len = self.config.correlation_length
        corr_time = self.config.correlation_time_hours

        try:
            for prc_file in prc_files:
                ds = Dataset(str(prc_file), "r+")

                if "prate" not in ds.variables:
                    ds.close()
                    continue

                prate = ds.variables["prate"][:]
                nt, ny, nx = prate.shape

                pert = self.grf.generate_temporal_ar1(
                    nt, (ny, nx), corr_len, corr_time
                )

                # Log-normal multiplicative perturbation
                log_std = std_pct / 100.0
                factor = np.exp(log_std * pert - 0.5 * log_std ** 2)
                ds.variables["prate"][:] = prate * factor
                ds.close()
                modified_files.append(prc_file)

            return PerturbationResult(
                success=True,
                perturbation_type="precipitation",
                member_id=member_id,
                description=(
                    f"Precipitation: std_pct={std_pct}%, "
                    f"corr_len={corr_len}km, corr_time={corr_time}h"
                ),
                modified_files=modified_files,
            )

        except Exception as e:
            log.error(f"Precipitation perturbation failed: {e}")
            return PerturbationResult(
                success=False,
                perturbation_type="precipitation",
                member_id=member_id,
                errors=[str(e)],
            )

    def describe(self) -> str:
        return (
            f"Precipitation perturbation: std={self.config.std_pct}%, "
            f"corr_len={self.config.correlation_length}km"
        )


# ---------------------------------------------------------------------------
# Boundary Condition Perturbations
# ---------------------------------------------------------------------------


class OBCPerturbation(BasePerturbation):
    """
    Perturb open boundary condition files (RTOFS-derived T/S/SSH/velocity).

    Adds spatially-correlated Gaussian noise to boundary forcing files,
    capturing uncertainty from the upstream RTOFS/HYCOM model that provides
    boundary conditions.

    Works with time-varying boundary files:
    - elev2D.th.nc (SSH)
    - TEM_3D.th.nc (temperature)
    - SAL_3D.th.nc (salinity)
    - uv3D.th.nc (velocity)
    """

    def apply(self, member_id: int, data_dir: Path) -> PerturbationResult:
        """Apply OBC perturbation to boundary forcing files."""
        if not HAS_NETCDF4:
            return PerturbationResult(
                success=False,
                perturbation_type="obc",
                member_id=member_id,
                errors=["netCDF4 required for OBC perturbation"],
            )

        modified_files = []
        descriptions = []

        # Variable name -> boundary file mapping
        var_file_map = {
            "temperature": ["TEM_3D.th.nc", "tem_3D.th.nc"],
            "salinity": ["SAL_3D.th.nc", "sal_3D.th.nc"],
            "ssh": ["elev2D.th.nc"],
            "velocity": ["uv3D.th.nc"],
        }

        try:
            for var_name, var_config in self.config.variables.items():
                file_patterns = var_file_map.get(var_name, [f"{var_name}.th.nc"])

                obc_file = None
                for pattern in file_patterns:
                    candidate = data_dir / pattern
                    if candidate.exists():
                        obc_file = candidate
                        break

                if obc_file is None:
                    log.warning(
                        f"OBC file for {var_name} not found in {data_dir}, skipping"
                    )
                    continue

                ds = Dataset(str(obc_file), "r+")

                # Find the main data variable (usually 'time_series' or first non-dim var)
                data_var_name = None
                for vname in ds.variables:
                    if vname not in ("time",) and ds.variables[vname].ndim >= 2:
                        data_var_name = vname
                        break

                if data_var_name is None:
                    ds.close()
                    continue

                data_arr = ds.variables[data_var_name][:]
                shape = data_arr.shape

                # Generate perturbation matching field shape
                if len(shape) == 2:
                    # (ntime, npts) -- e.g., 2D SSH boundary
                    nt, npts = shape
                    pert = np.zeros_like(data_arr)
                    for t in range(nt):
                        pert[t] = self.rng.standard_normal(npts) * var_config.std_dev
                elif len(shape) == 3:
                    # (ntime, npts, nlev) or (ntime, nlev, npts)
                    pert = self.rng.standard_normal(shape) * var_config.std_dev
                else:
                    pert = self.rng.standard_normal(shape) * var_config.std_dev

                perturbed = data_arr + pert

                if var_config.clamp_min is not None:
                    perturbed = np.maximum(perturbed, var_config.clamp_min)
                if var_config.clamp_max is not None:
                    perturbed = np.minimum(perturbed, var_config.clamp_max)

                ds.variables[data_var_name][:] = perturbed
                ds.close()
                modified_files.append(obc_file)
                descriptions.append(
                    f"{var_name}: std={var_config.std_dev}"
                )

            return PerturbationResult(
                success=True,
                perturbation_type="obc",
                member_id=member_id,
                description=f"OBC: {'; '.join(descriptions)}",
                modified_files=modified_files,
            )

        except Exception as e:
            log.error(f"OBC perturbation failed: {e}")
            return PerturbationResult(
                success=False,
                perturbation_type="obc",
                member_id=member_id,
                errors=[str(e)],
            )

    def describe(self) -> str:
        var_desc = []
        for name, cfg in self.config.variables.items():
            var_desc.append(f"{name}(std={cfg.std_dev})")
        return f"OBC perturbation: {', '.join(var_desc)}"


# ---------------------------------------------------------------------------
# Model Parameter Perturbations
# ---------------------------------------------------------------------------


class BottomFrictionPerturbation(BasePerturbation):
    """
    Perturb bottom friction parameters in model configuration.

    For SCHISM: modifies Zob (bottom roughness) or RDRG2 in param.nml.
    For FVCOM: modifies bottom roughness in run_control.nml.
    For ROMS: modifies RDRG/RDRG2 in ROMS.in.

    Uses multiplicative perturbation: param' = param * exp(std * N(0,1))
    to ensure the parameter remains positive.
    """

    def apply(self, member_id: int, data_dir: Path) -> PerturbationResult:
        """Apply bottom friction perturbation to model config file."""
        std_pct = self.config.bottom_friction_std_pct

        # Find model configuration file
        config_file = self._find_config_file(data_dir)
        if config_file is None:
            return PerturbationResult(
                success=False,
                perturbation_type="bottom_friction",
                member_id=member_id,
                errors=[f"No model config file found in {data_dir}"],
            )

        try:
            # Generate perturbation factor
            log_std = std_pct / 100.0
            z = self.rng.standard_normal()
            factor = math.exp(log_std * z - 0.5 * log_std ** 2)

            # Read and modify the config file
            content = config_file.read_text()
            original_values = {}
            new_values = {}

            # SCHISM param.nml parameters
            param_names = ["Zob", "rdrg2", "RDRG2", "bfric"]
            for param in param_names:
                content, orig, new = self._perturb_namelist_param(
                    content, param, factor
                )
                if orig is not None:
                    original_values[param] = orig
                    new_values[param] = new

            config_file.write_text(content)

            return PerturbationResult(
                success=True,
                perturbation_type="bottom_friction",
                member_id=member_id,
                description=(
                    f"Bottom friction: factor={factor:.4f} "
                    f"(std={std_pct}%)"
                ),
                modified_files=[config_file],
                parameters=new_values,
                metadata={
                    "factor": factor,
                    "original_values": original_values,
                },
            )

        except Exception as e:
            log.error(f"Bottom friction perturbation failed: {e}")
            return PerturbationResult(
                success=False,
                perturbation_type="bottom_friction",
                member_id=member_id,
                errors=[str(e)],
            )

    def describe(self) -> str:
        return (
            f"Bottom friction perturbation: "
            f"std={self.config.bottom_friction_std_pct}%"
        )

    @staticmethod
    def _find_config_file(data_dir: Path) -> Optional[Path]:
        """Find model configuration file in data_dir."""
        candidates = [
            "param.nml",
            "*.param.nml",
            "run_control.nml",
            "ROMS.in",
            "roms.in",
        ]
        for pattern in candidates:
            matches = list(data_dir.glob(pattern))
            if matches:
                return matches[0]
        return None

    @staticmethod
    def _perturb_namelist_param(
        content: str, param_name: str, factor: float
    ) -> Tuple[str, Optional[float], Optional[float]]:
        """
        Perturb a numeric parameter in a Fortran namelist file.

        Searches for lines matching 'param_name = value' and multiplies
        the value by the given factor.

        Args:
            content: File content as string.
            param_name: Parameter name to search for.
            factor: Multiplicative perturbation factor.

        Returns:
            Tuple of (modified_content, original_value, new_value).
            original_value is None if parameter not found.
        """
        import re

        pattern = rf"(\s*{re.escape(param_name)}\s*=\s*)([\d.eE+-]+)"
        match = re.search(pattern, content, re.IGNORECASE)

        if match is None:
            return content, None, None

        original = float(match.group(2))
        new_val = original * factor

        # Preserve formatting: use same precision
        if "e" in match.group(2).lower() or "E" in match.group(2):
            new_str = f"{new_val:.6e}"
        elif "." in match.group(2):
            n_decimals = len(match.group(2).split(".")[-1])
            new_str = f"{new_val:.{n_decimals}f}"
        else:
            new_str = str(int(round(new_val)))

        new_content = content[: match.start(2)] + new_str + content[match.end(2) :]

        return new_content, original, new_val


class WindDragPerturbation(BasePerturbation):
    """
    Perturb wind drag coefficient in model configuration.

    Modifies the surface wind stress drag coefficient which controls
    how much momentum is transferred from the atmosphere to the ocean.
    Critical for storm surge amplitude.

    For SCHISM, this typically involves adjusting parameters in param.nml
    that control the wind drag formulation.
    """

    def apply(self, member_id: int, data_dir: Path) -> PerturbationResult:
        """Apply wind drag perturbation."""
        std_pct = self.config.wind_drag_std_pct

        config_file = BottomFrictionPerturbation._find_config_file(data_dir)
        if config_file is None:
            return PerturbationResult(
                success=False,
                perturbation_type="wind_drag",
                member_id=member_id,
                errors=[f"No model config file found in {data_dir}"],
            )

        try:
            log_std = std_pct / 100.0
            z = self.rng.standard_normal()
            factor = math.exp(log_std * z - 0.5 * log_std ** 2)

            content = config_file.read_text()
            original_values = {}
            new_values = {}

            # Wind drag parameters across model types
            drag_params = [
                "windcd_max",
                "windcd_min",
                "cdmax",
                "rdrg",
                "RDRG",
            ]
            for param in drag_params:
                content, orig, new = (
                    BottomFrictionPerturbation._perturb_namelist_param(
                        content, param, factor
                    )
                )
                if orig is not None:
                    original_values[param] = orig
                    new_values[param] = new

            config_file.write_text(content)

            return PerturbationResult(
                success=True,
                perturbation_type="wind_drag",
                member_id=member_id,
                description=(
                    f"Wind drag: factor={factor:.4f} (std={std_pct}%)"
                ),
                modified_files=[config_file],
                parameters=new_values,
                metadata={"factor": factor, "original_values": original_values},
            )

        except Exception as e:
            log.error(f"Wind drag perturbation failed: {e}")
            return PerturbationResult(
                success=False,
                perturbation_type="wind_drag",
                member_id=member_id,
                errors=[str(e)],
            )

    def describe(self) -> str:
        return f"Wind drag perturbation: std={self.config.wind_drag_std_pct}%"


class MixingPerturbation(BasePerturbation):
    """
    Perturb vertical mixing parameters in model configuration.

    Modifies background diffusivity and viscosity parameters that control
    how mixing occurs in the water column. These parameters significantly
    affect temperature and salinity stratification.

    For SCHISM: AKT_BAK (tracer), AKV_BAK (momentum), AKK_BAK (TKE).
    For FVCOM: similar turbulence closure parameters.
    For ROMS: AKT_BAK, AKV_BAK.
    """

    def apply(self, member_id: int, data_dir: Path) -> PerturbationResult:
        """Apply mixing parameter perturbation."""
        std_pct = self.config.mixing_std_pct

        config_file = BottomFrictionPerturbation._find_config_file(data_dir)
        if config_file is None:
            return PerturbationResult(
                success=False,
                perturbation_type="mixing",
                member_id=member_id,
                errors=[f"No model config file found in {data_dir}"],
            )

        try:
            log_std = std_pct / 100.0
            z = self.rng.standard_normal()
            factor = math.exp(log_std * z - 0.5 * log_std ** 2)

            content = config_file.read_text()
            original_values = {}
            new_values = {}

            mixing_params = [
                "akt_bak",
                "AKT_BAK",
                "akv_bak",
                "AKV_BAK",
                "akk_bak",
                "AKK_BAK",
                "akp_bak",
                "AKP_BAK",
                "visc2",
                "VISC2",
            ]
            for param in mixing_params:
                content, orig, new = (
                    BottomFrictionPerturbation._perturb_namelist_param(
                        content, param, factor
                    )
                )
                if orig is not None:
                    original_values[param] = orig
                    new_values[param] = new

            config_file.write_text(content)

            return PerturbationResult(
                success=True,
                perturbation_type="mixing",
                member_id=member_id,
                description=(
                    f"Mixing: factor={factor:.4f} (std={std_pct}%)"
                ),
                modified_files=[config_file],
                parameters=new_values,
                metadata={"factor": factor, "original_values": original_values},
            )

        except Exception as e:
            log.error(f"Mixing perturbation failed: {e}")
            return PerturbationResult(
                success=False,
                perturbation_type="mixing",
                member_id=member_id,
                errors=[str(e)],
            )

    def describe(self) -> str:
        return f"Mixing perturbation: std={self.config.mixing_std_pct}%"
