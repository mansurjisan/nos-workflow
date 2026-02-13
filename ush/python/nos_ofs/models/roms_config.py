"""
ROMS Configuration Generator

Generates ROMS ocean.in control files from YAML configuration.
ocean.in uses a keyword = value format (not Fortran namelist).

The generator uses a template-based approach with config substitution,
following the same pattern as COMF's nos_ofs_prep_roms_ctl.sh.

Key ocean.in sections:
- Title and identification
- Time-stepping parameters
- Grid definition and S-coordinate
- Lateral boundary conditions
- Initial conditions and restart
- Forcing files
- Output configuration
- Physical parameters (viscosity, drag, mixing)

Reference: ROMS ocean.in User Manual
"""

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)


class ROMSConfigGenerator:
    """
    Generate ROMS ocean.in control file from YAML configuration.

    This generator produces the ocean.in file that ROMS reads at startup.
    It handles both nowcast and forecast stages, adjusting time parameters
    and restart settings accordingly.

    Usage:
        generator = ROMSConfigGenerator(config)
        path = generator.generate(
            output_path=Path("/work/cbofs"),
            stage="nowcast",
        )
    """

    # Default ROMS settings (can be overridden by YAML config)
    DEFAULTS = {
        # Time stepping
        "NTIMES": 86400,
        "DT": 4.0,
        "NDTFAST": 20,
        "NINFO": 100,
        # S-coordinate
        "Vtransform": 2,
        "Vstretching": 4,
        "THETA_S": 5.0,
        "THETA_B": 0.4,
        "TCLINE": 10.0,
        # Restart
        "NRST": 1440,
        "LDEFOUT": "T",
        # History output
        "NHIS": 360,
        "NDEFHIS": 0,
        # Average output
        "NTSAVG": 1,
        "NAVG": 360,
        "NDEFAVG": 0,
        # Lateral viscosity
        "VISC2": 5.0,
        "TNU2": "2*5.0d0",
        # Bottom drag
        "RDRG": 3.0e-4,
        "RDRG2": 3.0e-3,
        "Zob": 0.02,
        "Zos": 0.02,
        # Vertical mixing
        "AKV_BAK": 1.0e-5,
        "AKT_BAK": "2*1.0d-6",
        "AKS_BAK": "2*1.0d-6",
        # Nudging
        "TNUDG": "2*1.0d0",
        "ZNUDG": 360.0,
        "M2NUDG": 360.0,
        "M3NUDG": 360.0,
        # Sponge
        "OBCFAC": 120.0,
        # Generic length scale
        "GLS_P": -1.0,
        "GLS_M": 0.5,
        "GLS_N": -1.0,
        "GLS_Kmin": 7.6e-6,
        "GLS_Pmin": 1.0e-12,
        "GLS_CMU0": 0.5477,
        "GLS_C1": 0.555,
        "GLS_C2": 0.833,
        "GLS_C3M": -0.6,
        "GLS_C3P": 1.0,
        "GLS_SIGK": 2.0,
        "GLS_SIGP": 2.0,
    }

    def __init__(self, config: Any):
        """
        Initialize ROMS config generator.

        Args:
            config: OFSConfig instance
        """
        self.config = config
        self._yaml_data = self._get_yaml_data()

    def _get_yaml_data(self) -> Dict[str, Any]:
        """Extract raw YAML configuration data."""
        if hasattr(self.config, '_yaml_data'):
            return self.config._yaml_data
        if hasattr(self.config, 'system') and hasattr(self.config.system, '_raw'):
            return self.config.system._raw
        return {}

    def _get_model_param(self, key: str, default: Any = None) -> Any:
        """Get a model physics parameter from YAML config."""
        model = self._yaml_data.get('model', {})
        physics = model.get('physics', {})
        if key in physics:
            return physics[key]
        vertical = model.get('vertical', {})
        if key in vertical:
            return vertical[key]
        return default

    def _get_grid_param(self, key: str, default: Any = None) -> Any:
        """Get a grid parameter from YAML config."""
        grid = self._yaml_data.get('grid', {})
        if key in grid:
            return grid[key]
        domain = grid.get('domain', {})
        if key in domain:
            return domain[key]
        return default

    def generate(
        self,
        output_path: Path,
        stage: str = "nowcast",
        pdy: str = None,
        cyc: int = None,
    ) -> Path:
        """
        Generate ROMS ocean.in control file.

        Args:
            output_path: Directory to write ocean.in
            stage: Workflow stage ("nowcast" or "forecast")
            pdy: Production date (YYYYMMDD), defaults to config value
            cyc: Cycle hour, defaults to config value

        Returns:
            Path to generated ocean.in file
        """
        output_dir = Path(output_path)
        output_dir.mkdir(parents=True, exist_ok=True)
        ocean_in_path = output_dir / "ocean.in"

        pdy = pdy or getattr(self.config, 'PDY', datetime.now().strftime('%Y%m%d'))
        cyc = cyc if cyc is not None else getattr(self.config, 'cyc', 0)

        content = self._build_ocean_in(stage, pdy, cyc)

        with open(ocean_in_path, 'w') as f:
            f.write(content)

        log.info(f"Generated ROMS ocean.in: {ocean_in_path}")
        return ocean_in_path

    def _build_ocean_in(self, stage: str, pdy: str, cyc: int) -> str:
        """Build the ocean.in file content."""
        ofs_name = getattr(self.config, 'RUN', 'roms')
        prefix = self._yaml_data.get('system', {}).get('prefix', ofs_name)

        # Time parameters
        dt = self._get_model_param('dt', self.DEFAULTS['DT'])
        ndtfast = self._get_model_param('ndtfast', self.DEFAULTS['NDTFAST'])

        run_cfg = self._yaml_data.get('model', {}).get('run', {})
        if stage == "nowcast":
            run_hours = run_cfg.get('hindcast_days', 0.25) * 24
        else:
            run_hours = run_cfg.get('forecast_days', 2.0) * 24

        ntimes = int(run_hours * 3600 / dt)

        # S-coordinate parameters
        vtransform = self._get_model_param('vtransform', self.DEFAULTS['Vtransform'])
        vstretching = self._get_model_param('vstretching', self.DEFAULTS['Vstretching'])
        theta_s = self._get_model_param('theta_s', self.DEFAULTS['THETA_S'])
        theta_b = self._get_model_param('theta_b', self.DEFAULTS['THETA_B'])
        tcline = self._get_model_param('tcline', self.DEFAULTS['TCLINE'])
        n_levels = self._yaml_data.get('model', {}).get('vertical', {}).get('n', 20)

        # Grid file
        grid_cfg = self._yaml_data.get('grid', {}).get('files', {})
        grid_file = grid_cfg.get('grid', f'{prefix}_grid.nc')

        # Forcing files
        forcing_file = grid_cfg.get('forcing', f'{prefix}_forcing.nc')

        # Restart interval
        nrst = self._get_model_param('nrst', self.DEFAULTS['NRST'])
        if nrst == self.DEFAULTS['NRST']:
            # Compute from output interval (daily restart by default)
            output_cfg = self._yaml_data.get('output', {})
            restart_cfg = output_cfg.get('restart', {})
            restart_interval_s = restart_cfg.get('interval', 21600)
            nrst = int(restart_interval_s / dt)

        # History and average intervals
        output_cfg = self._yaml_data.get('output', {})
        fields_cfg = output_cfg.get('fields', {})
        fields_interval = fields_cfg.get('interval', 3600)
        nhis = int(fields_interval / dt)
        navg = nhis

        # Station output
        station_cfg = output_cfg.get('stations', {})
        station_interval = station_cfg.get('interval', 360)
        nsta = int(station_interval / dt)

        # Date reference for ROMS DSTART
        cycle_dt = datetime.strptime(f"{pdy}{cyc:02d}", "%Y%m%d%H")
        # ROMS uses a reference date, typically days since some epoch
        # COMF convention: DSTART = days from reference to simulation start
        ref_date = datetime(1858, 11, 17)  # Modified Julian Date epoch
        if stage == "nowcast":
            hindcast_days = run_cfg.get('hindcast_days', 0.25)
            sim_start = cycle_dt - timedelta(days=hindcast_days)
        else:
            sim_start = cycle_dt
        dstart = (sim_start - ref_date).total_seconds() / 86400.0

        # Time reference string
        time_ref = ref_date.strftime("%Y%m%d.0")

        # Initial conditions
        if stage == "forecast":
            ini_file = f"{prefix}.rst.nowcast.nc"
            nrrec = -1  # Use last record from restart
        else:
            ini_file = f"{prefix}.ini.nc"
            nrrec = 0

        # Lateral boundary conditions (LBC)
        # Default ROMS COMF configuration
        lbc_settings = self._get_lbc_settings()

        lines = []
        lines.append(f"! ROMS ocean.in for {ofs_name.upper()} - {stage}")
        lines.append(f"! Generated by nos_ofs ROMSConfigGenerator")
        lines.append(f"! Date: {pdy} Cycle: {cyc:02d}z Stage: {stage}")
        lines.append("")

        # Application title
        lines.append(f"       TITLE = {ofs_name.upper()} {stage}")
        lines.append(f"    MyAppCPP = {ofs_name.upper()}")
        lines.append(f"      VARNAME = varinfo.dat")
        lines.append("")

        # Grid dimensions
        lines.append(f"! Grid dimensions")
        n_xi = self._yaml_data.get('grid', {}).get('n_xi', 100)
        n_eta = self._yaml_data.get('grid', {}).get('n_eta', 100)
        lines.append(f"          Lm == {n_xi - 2}    ! Number of I-direction INTERIOR RHO-points")
        lines.append(f"          Mm == {n_eta - 2}    ! Number of J-direction INTERIOR RHO-points")
        lines.append(f"           N == {n_levels}    ! Number of vertical levels")
        lines.append("")

        # Number of nested grids
        lines.append(f"       Ngrids =  1")
        lines.append(f"  NtileI == 1")
        lines.append(f"  NtileJ == 1")
        lines.append("")

        # Time stepping
        lines.append(f"! Time stepping parameters")
        lines.append(f"      NTIMES == {ntimes}")
        lines.append(f"          DT == {dt:.1f}d0")
        lines.append(f"     NDTFAST == {ndtfast}")
        lines.append("")

        # Output intervals
        lines.append(f"! Output intervals")
        lines.append(f"        NRST == {nrst}")
        lines.append(f"     LDEFOUT == {self.DEFAULTS['LDEFOUT']}")
        lines.append(f"        NHIS == {nhis}")
        lines.append(f"     NDEFHIS == 0")
        lines.append(f"      NTSAVG == 1")
        lines.append(f"        NAVG == {navg}")
        lines.append(f"     NDEFAVG == 0")
        lines.append(f"        NSTA == {nsta}")
        lines.append(f"       NINFO == {self.DEFAULTS['NINFO']}")
        lines.append("")

        # S-coordinate
        lines.append(f"! S-coordinate vertical grid")
        lines.append(f"  Vtransform == {vtransform}")
        lines.append(f" Vstretching == {vstretching}")
        lines.append(f"     THETA_S == {theta_s:.1f}d0")
        lines.append(f"     THETA_B == {theta_b:.1f}d0")
        lines.append(f"      TCLINE == {tcline:.1f}d0")
        lines.append("")

        # Time reference
        lines.append(f"! Time reference")
        lines.append(f"      DSTART == {dstart:.4f}d0")
        lines.append(f"  TIME_REF == {time_ref}")
        lines.append("")

        # Initial conditions
        lines.append(f"! Initial conditions")
        lines.append(f"       NRREC == {nrrec}")
        lines.append(f"   LcycleRST == T")
        lines.append("")

        # Lateral boundary conditions
        lines.append(f"! Lateral boundary conditions")
        for lbc_line in lbc_settings:
            lines.append(f"   {lbc_line}")
        lines.append("")

        # Physical parameters
        lines.append(f"! Lateral viscosity")
        lines.append(f"       VISC2 == {self.DEFAULTS['VISC2']:.1f}d0")
        lines.append(f"        TNU2 == {self.DEFAULTS['TNU2']}")
        lines.append("")

        lines.append(f"! Bottom drag")
        lines.append(f"        RDRG == {self.DEFAULTS['RDRG']:.1e}d0")
        lines.append(f"       RDRG2 == {self.DEFAULTS['RDRG2']:.1e}d0")
        lines.append(f"         Zob == {self.DEFAULTS['Zob']}")
        lines.append(f"         Zos == {self.DEFAULTS['Zos']}")
        lines.append("")

        lines.append(f"! Vertical mixing")
        lines.append(f"     AKV_BAK == {self.DEFAULTS['AKV_BAK']:.1e}d0")
        lines.append(f"     AKT_BAK == {self.DEFAULTS['AKT_BAK']}")
        lines.append(f"     AKS_BAK == {self.DEFAULTS['AKS_BAK']}")
        lines.append("")

        # Nudging
        lines.append(f"! Nudging time scales (days)")
        lines.append(f"       TNUDG == {self.DEFAULTS['TNUDG']}")
        lines.append(f"       ZNUDG == {self.DEFAULTS['ZNUDG']:.1f}d0")
        lines.append(f"      M2NUDG == {self.DEFAULTS['M2NUDG']:.1f}d0")
        lines.append(f"      M3NUDG == {self.DEFAULTS['M3NUDG']:.1f}d0")
        lines.append(f"      OBCFAC == {self.DEFAULTS['OBCFAC']:.1f}d0")
        lines.append("")

        # GLS mixing model
        lines.append(f"! Generic Length Scale turbulence closure")
        lines.append(f"       GLS_P == {self.DEFAULTS['GLS_P']:.1f}d0")
        lines.append(f"       GLS_M == {self.DEFAULTS['GLS_M']:.1f}d0")
        lines.append(f"       GLS_N == {self.DEFAULTS['GLS_N']:.1f}d0")
        lines.append(f"    GLS_Kmin == {self.DEFAULTS['GLS_Kmin']:.1e}d0")
        lines.append(f"    GLS_Pmin == {self.DEFAULTS['GLS_Pmin']:.1e}d0")
        lines.append(f"    GLS_CMU0 == {self.DEFAULTS['GLS_CMU0']:.4f}d0")
        lines.append(f"      GLS_C1 == {self.DEFAULTS['GLS_C1']:.3f}d0")
        lines.append(f"      GLS_C2 == {self.DEFAULTS['GLS_C2']:.3f}d0")
        lines.append(f"     GLS_C3M == {self.DEFAULTS['GLS_C3M']:.1f}d0")
        lines.append(f"     GLS_C3P == {self.DEFAULTS['GLS_C3P']:.1f}d0")
        lines.append(f"    GLS_SIGK == {self.DEFAULTS['GLS_SIGK']:.1f}d0")
        lines.append(f"    GLS_SIGP == {self.DEFAULTS['GLS_SIGP']:.1f}d0")
        lines.append("")

        # Input files
        lines.append(f"! Input files")
        lines.append(f"     GRDNAME == {grid_file}")
        lines.append(f"     ININAME == {ini_file}")
        lines.append(f"     FRCNAME == {forcing_file}")
        lines.append(f"     CLMNAME == {prefix}_clm.nc")
        lines.append(f"     BRYNAME == {prefix}_bry.nc")
        lines.append("")

        # Output files
        lines.append(f"! Output files")
        lines.append(f"     RSTNAME == {prefix}.rst.{stage}.nc")
        lines.append(f"     HISNAME == {prefix}.his.{stage}.nc")
        lines.append(f"     AVGNAME == {prefix}.avg.{stage}.nc")
        lines.append(f"     STANAME == {prefix}.sta.{stage}.nc")
        lines.append("")

        return "\n".join(lines) + "\n"

    def _get_lbc_settings(self) -> list:
        """Get lateral boundary condition settings."""
        return [
            "LBC(isFsur) == Cha   Cha   Cha   Cha         ! free-surface",
            "LBC(isUbar) == Fla   Fla   Fla   Fla         ! 2D U-momentum",
            "LBC(isVbar) == Fla   Fla   Fla   Fla         ! 2D V-momentum",
            "LBC(isUvel) == Rad   Rad   Rad   Rad         ! 3D U-momentum",
            "LBC(isVvel) == Rad   Rad   Rad   Rad         ! 3D V-momentum",
            "LBC(isMtke) == Rad   Rad   Rad   Rad         ! mixing TKE",
            "LBC(isTvar) == RadNud RadNud RadNud RadNud    ! tracers",
        ]

    def generate_for_cycle(
        self,
        output_path: Path,
        pdy: str,
        cyc: int,
        stage: str = "nowcast",
    ) -> Path:
        """
        Generate ocean.in for a specific forecast cycle.

        Convenience method that matches the interface used by
        SCHISM's ParamNmlGenerator.

        Args:
            output_path: Full path to output file (or directory)
            pdy: Production date (YYYYMMDD)
            cyc: Cycle hour
            stage: Workflow stage

        Returns:
            Path to generated ocean.in
        """
        if output_path.suffix:
            # Path includes filename
            output_dir = output_path.parent
        else:
            output_dir = output_path

        return self.generate(output_dir, stage=stage, pdy=pdy, cyc=cyc)

    def __repr__(self) -> str:
        ofs_name = getattr(self.config, 'RUN', 'unknown')
        return f"ROMSConfigGenerator(ofs={ofs_name})"
