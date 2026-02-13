"""
FVCOM Configuration Generator

Generates FVCOM run_control.nml (Fortran namelist format) from YAML configuration.

FVCOM uses a Fortran namelist file with multiple NML_* sections:
- NML_CASE: Case name, title, start/end time
- NML_STARTUP: Startup type (cold/hot), input files
- NML_IO: Input/output file naming
- NML_INTEGRATION: Time stepping parameters
- NML_RESTART: Restart file configuration
- NML_NETCDF: NetCDF output configuration
- NML_PHYSICS: Physical parameters (mixing, drag)
- NML_SURFACE_FORCING: Atmospheric forcing configuration
- NML_RIVER: River forcing configuration
- NML_OPEN_BOUNDARY_CONTROL: Open boundary settings
- NML_GRID_COORDINATES: Grid projection/coordinate system

Reference: FVCOM User Manual, nos_ofs_prep_fvcom_ctl.sh
"""

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)


class FVCOMConfigGenerator:
    """
    Generate FVCOM run_control.nml from YAML configuration.

    This generator produces the namelist file that FVCOM reads at startup.
    It handles both nowcast and forecast stages, adjusting time parameters
    and restart settings accordingly.

    Usage:
        generator = FVCOMConfigGenerator(config)
        path = generator.generate(
            output_path=Path("/work/leofs"),
            stage="nowcast",
        )
    """

    # Default FVCOM settings
    DEFAULTS = {
        # Time stepping
        "DTE": 0.5,         # External time step (seconds)
        "DTI": 10.0,        # Internal time step (seconds)
        "ISPLIT": 20,        # External/internal time step ratio
        # Sigma levels
        "KB": 21,            # Number of sigma levels
        "KSL": 1,            # Sigma level distribution type
        "P_SIGMA": 1.0,      # Power for sigma distribution
        # Bottom drag
        "BFRIC": 0.001,      # Bottom friction coefficient
        "Z0B": 0.001,        # Bottom roughness (meters)
        # Vertical mixing
        "UMOL": 1.0e-6,      # Background molecular viscosity
        "HORZMIX": "closure",
        "VERTMIX": "closure",
        # Smagorinsky
        "C_SMAGOR": 0.2,     # Smagorinsky constant
        # Coriolis
        "CORIOLIS_TYPE": "node",
    }

    def __init__(self, config: Any):
        """
        Initialize FVCOM config generator.

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

    def generate(
        self,
        output_path: Path,
        stage: str = "nowcast",
        pdy: str = None,
        cyc: int = None,
    ) -> Path:
        """
        Generate FVCOM run_control.nml file.

        Args:
            output_path: Directory to write run_control.nml
            stage: Workflow stage ("nowcast" or "forecast")
            pdy: Production date (YYYYMMDD), defaults to config value
            cyc: Cycle hour, defaults to config value

        Returns:
            Path to generated run_control.nml
        """
        output_dir = Path(output_path)
        output_dir.mkdir(parents=True, exist_ok=True)
        nml_path = output_dir / "run_control.nml"

        pdy = pdy or getattr(self.config, 'PDY', datetime.now().strftime('%Y%m%d'))
        cyc = cyc if cyc is not None else getattr(self.config, 'cyc', 0)

        content = self._build_namelist(stage, pdy, cyc)

        with open(nml_path, 'w') as f:
            f.write(content)

        log.info(f"Generated FVCOM run_control.nml: {nml_path}")
        return nml_path

    def _build_namelist(self, stage: str, pdy: str, cyc: int) -> str:
        """Build the run_control.nml file content."""
        ofs_name = getattr(self.config, 'RUN', 'fvcom')
        prefix = self._yaml_data.get('system', {}).get('prefix', ofs_name)
        casename = self._yaml_data.get('system', {}).get('casename', ofs_name)

        # Time parameters
        cycle_dt = datetime.strptime(f"{pdy}{cyc:02d}", "%Y%m%d%H")
        run_cfg = self._yaml_data.get('model', {}).get('run', {})

        if stage == "nowcast":
            run_days = run_cfg.get('hindcast_days', 0.25)
            sim_start = cycle_dt - timedelta(days=run_days)
        else:
            run_days = run_cfg.get('forecast_days', 5.0)
            sim_start = cycle_dt

        sim_end = sim_start + timedelta(days=run_days)

        # Time stepping
        dte = self._get_model_param('dt', self.DEFAULTS['DTE'])
        dti = self._get_model_param('dti', self.DEFAULTS['DTI'])
        isplit = self._get_model_param('isplit', self.DEFAULTS['ISPLIT'])

        # Sigma levels
        kb = self._get_model_param('kb', self.DEFAULTS['KB'])
        ksl = self._get_model_param('ksl', self.DEFAULTS['KSL'])
        p_sigma = self._get_model_param('p_sigma', self.DEFAULTS['P_SIGMA'])

        # Forcing config
        forcing_cfg = self._yaml_data.get('forcing', {})
        atmos_cfg = forcing_cfg.get('atmospheric', {})
        river_cfg = forcing_cfg.get('river', {})
        ocean_cfg = forcing_cfg.get('ocean', {})
        tidal_cfg = forcing_cfg.get('tidal', {})

        # Output config
        output_cfg = self._yaml_data.get('output', {})
        station_cfg = output_cfg.get('stations', {})
        fields_cfg = output_cfg.get('fields', {})
        restart_cfg = output_cfg.get('restart', {})

        station_interval = station_cfg.get('interval', 360)
        fields_interval = fields_cfg.get('interval', 3600)
        restart_interval = restart_cfg.get('interval', 21600)

        # Bottom drag
        bottom_roughness = self._get_model_param(
            'bottom_roughness', self.DEFAULTS['BFRIC']
        )

        # Startup type
        if stage == "forecast":
            startup_type = "hotstart"
            startup_file = f"{prefix}_restart_nowcast.nc"
        else:
            startup_type = "hotstart"
            startup_file = f"{prefix}_restart.nc"

        # Grid files
        grid_cfg = self._yaml_data.get('grid', {}).get('files', {})
        grd_file = grid_cfg.get('horizontal', f'{prefix}_grd.dat')
        dep_file = grid_cfg.get('depth', f'{prefix}_dep.dat')
        obc_file = grid_cfg.get('obc', f'{prefix}_obc.dat')

        sections = []

        # ====== NML_CASE ======
        sections.append(self._section(
            "NML_CASE",
            CASE_TITLE=f"'{ofs_name.upper()} {stage}'",
            TIMEZONE=f"'UTC'",
            DATE_FORMAT=f"'YMD'",
            DATE_REFERENCE=f"'default'",
            START_DATE=f"'{sim_start.strftime('%Y-%m-%d %H:%M:%S')}'",
            END_DATE=f"'{sim_end.strftime('%Y-%m-%d %H:%M:%S')}'",
            CASE_NAME=f"'{casename}'",
        ))

        # ====== NML_STARTUP ======
        sections.append(self._section(
            "NML_STARTUP",
            STARTUP_TYPE=f"'{startup_type}'",
            STARTUP_FILE=f"'{startup_file}'",
            STARTUP_UV_TYPE=f"'default'",
            STARTUP_TURB_TYPE=f"'default'",
            STARTUP_TS_TYPE=f"'constant'",
            STARTUP_T_VALS=f"18.0",
            STARTUP_S_VALS=f"35.0",
            STARTUP_DMAX=f"-10.0",
        ))

        # ====== NML_IO ======
        sections.append(self._section(
            "NML_IO",
            INPUT_DIR=f"'./input'",
            OUTPUT_DIR=f"'./output'",
            IREPORT=f"100",
            IPRINT=f"1",
            OBC_ON=f".TRUE." if ocean_cfg.get('enabled', False) or tidal_cfg.get('enabled', False) else ".FALSE.",
            OBC_NODE_LIST_FILE=f"'{obc_file}'",
        ))

        # ====== NML_INTEGRATION ======
        sections.append(self._section(
            "NML_INTEGRATION",
            EXTSTEP_SECONDS=f"{dte}",
            ISPLIT=f"{isplit}",
            IRAMP=f"0",
            MIN_DEPTH=f"0.05",
            STATIC_SSH_ADJ=f"0.0",
        ))

        # ====== NML_RESTART ======
        restart_int_str = f"{restart_interval / 3600.0:.1f}"
        sections.append(self._section(
            "NML_RESTART",
            RST_ON=f".TRUE.",
            RST_FIRST_OUT=f"'{sim_start.strftime('%Y-%m-%d %H:%M:%S')}'",
            RST_OUT_INTERVAL=f"seconds={restart_interval}.",
            RST_OUTPUT_STACK=f"0",
        ))

        # ====== NML_NETCDF ======
        sections.append(self._section(
            "NML_NETCDF",
            NC_ON=f".TRUE.",
            NC_FIRST_OUT=f"'{sim_start.strftime('%Y-%m-%d %H:%M:%S')}'",
            NC_OUT_INTERVAL=f"seconds={fields_interval}.",
            NC_OUTPUT_STACK=f"0",
            NC_GRID_METRICS=f".TRUE.",
            NC_FILE_DATE=f".TRUE.",
            NC_VELOCITY=f".TRUE.",
            NC_SALT_TEMP=f".TRUE.",
            NC_TURBULENCE=f".FALSE.",
            NC_AVERAGE_VEL=f".TRUE.",
            NC_VERTICAL_VEL=f".FALSE.",
            NC_WIND_VEL=f".TRUE.",
            NC_WIND_STRESS=f".FALSE.",
            NC_EVAP_PRECIP=f".FALSE.",
            NC_SURFACE_HEAT=f".FALSE.",
            NC_GROUNDWATER=f".FALSE.",
            NC_BIO=f".FALSE.",
            NC_WQM=f".FALSE.",
            NC_VORTICITY=f".FALSE.",
        ))

        # ====== NML_NETCDF_SURFACE ======
        sections.append(self._section(
            "NML_NETCDF_SURFACE",
            NCSF_ON=f".TRUE.",
            NCSF_FIRST_OUT=f"'{sim_start.strftime('%Y-%m-%d %H:%M:%S')}'",
            NCSF_OUT_INTERVAL=f"seconds={fields_interval}.",
            NCSF_OUTPUT_STACK=f"0",
            NCSF_SUBDOMAIN_FILES=f"'none'",
        ))

        # ====== NML_STATION_TIMESERIES ======
        sections.append(self._section(
            "NML_STATION_TIMESERIES",
            STATION_FILE=f"'{prefix}_station.dat'",
            LOCATION_TYPE=f"'node'",
            OUT_STATION_TIMESERIES_ON=f".TRUE." if station_cfg.get('enabled', True) else ".FALSE.",
            OUT_ELEVATION=f".TRUE.",
            OUT_VELOCITY_3D=f".TRUE.",
            OUT_VELOCITY_2D=f".TRUE.",
            OUT_SALT_TEMP=f".TRUE.",
            OUT_WIND_VELOCITY=f".TRUE.",
            OUT_INTERVAL=f"seconds={station_interval}.",
        ))

        # ====== NML_PHYSICS ======
        hmix = self._get_model_param('horizontal_mixing', 'smagorinsky')
        vmix = self._get_model_param('vertical_mixing', 'mellor_yamada25')

        # Map config names to FVCOM namelist values
        hmix_map = {
            'smagorinsky': 'closure',
            'constant': 'constant',
            'closure': 'closure',
        }
        vmix_map = {
            'mellor_yamada25': 'closure',
            'gotm': 'gotm',
            'closure': 'closure',
            'constant': 'constant',
        }

        sections.append(self._section(
            "NML_PHYSICS",
            HORIZONTAL_MIXING_TYPE=f"'{hmix_map.get(hmix, 'closure')}'",
            HORIZONTAL_MIXING_KIND=f"'constant'",
            HORIZONTAL_MIXING_COEFFICIENT=f"0.1",
            HORIZONTAL_PRANDTL_NUMBER=f"1.0",
            SMOLARKIEWICZ_ITERATIVE_FCTR=f"0.1",
            VERTICAL_MIXING_TYPE=f"'{vmix_map.get(vmix, 'closure')}'",
            VERTICAL_MIXING_COEFFICIENT=f"1.0E-5",
            VERTICAL_PRANDTL_NUMBER=f"1.0",
            BOTTOM_ROUGHNESS_TYPE=f"'orig'",
            BOTTOM_ROUGHNESS_KIND=f"'constant'",
            BOTTOM_ROUGHNESS_MINIMUM=f"{bottom_roughness}",
            CONVECTIVE_OVERTURNING=f".FALSE.",
            SCALAR_POSITIVITY_CONTROL=f".TRUE.",
            BAROTROPIC=f".FALSE.",
            BAROCLINIC_PRESSURE_GRADIENT=f"'sigma levels'",
            SEA_WATER_DENSITY_FUNCTION=f"'dens2'",
            RECALCULATE_RHO_MEAN=f".FALSE.",
            INTERVAL_RHO_MEAN=f"'seconds= 1800.0'",
            TEMPERATURE_ACTIVE=f".TRUE.",
            SALINITY_ACTIVE=f".TRUE.",
            SURFACE_WAVE_MIXING=f".FALSE.",
            WETTING_DRYING_ON=f".TRUE.",
        ))

        # ====== NML_SURFACE_FORCING ======
        wind_type = "'speed'"
        heat_calc = ".TRUE."
        wind_on = ".TRUE." if atmos_cfg.get('primary') else ".FALSE."

        sections.append(self._section(
            "NML_SURFACE_FORCING",
            WIND_ON=wind_on,
            WIND_TYPE=wind_type,
            WIND_FILE=f"'{prefix}_wnd.nc'",
            WIND_KIND=f"'variable'",
            WIND_X=f"0.0",
            WIND_Y=f"0.0",
            HEATING_ON=f".TRUE.",
            HEATING_TYPE=f"'flux'",
            HEATING_KIND=f"'variable'",
            HEATING_FILE=f"'{prefix}_hfx.nc'",
            HEATING_LONGWAVE_LENGTHSCALE=f"3.6",
            HEATING_LONGWAVE_PERCTAGE=f"0.55",
            HEATING_SHORTWAVE_LENGTHSCALE=f"0.35",
            PRECIPITATION_ON=f".TRUE.",
            PRECIPITATION_KIND=f"'variable'",
            PRECIPITATION_FILE=f"'{prefix}_evt.nc'",
            AIRPRESSURE_ON=f".TRUE.",
            AIRPRESSURE_KIND=f"'variable'",
            AIRPRESSURE_FILE=f"'{prefix}_air.nc'",
        ))

        # ====== NML_RIVER ======
        river_on = ".TRUE." if river_cfg.get('enabled', True) else ".FALSE."
        n_rivers = len(river_cfg.get('sources', []))

        sections.append(self._section(
            "NML_RIVER_TYPE",
            RIVER_NUMBER=f"{n_rivers}",
            RIVER_TS_SETTING=f"'specified'",
            RIVER_INFLOW_LOCATION=f"'node'",
            RIVER_INFO_FILE=f"'{prefix}_riv.nml'",
            RIVER_KIND=f"'variable'",
        ))

        # ====== NML_OPEN_BOUNDARY_CONTROL ======
        obc_on = ".TRUE." if (
            ocean_cfg.get('enabled', False) or tidal_cfg.get('enabled', False)
        ) else ".FALSE."

        sections.append(self._section(
            "NML_OPEN_BOUNDARY_CONTROL",
            OBC_ON=obc_on,
            OBC_ELEVATION_FORCING_ON=obc_on,
            OBC_CURRENT_FORCING_ON=f".FALSE.",
            OBC_SALT_TEMP_FORCING_ON=obc_on if ocean_cfg.get('enabled', False) else ".FALSE.",
            OBC_LONGSHORE_FLOW_ON=f".FALSE.",
            OBC_DEPTH_CONTROL_ON=f".FALSE.",
        ))

        # ====== NML_GRID_COORDINATES ======
        sections.append(self._section(
            "NML_GRID_COORDINATES",
            GRID_FILE=f"'{grd_file}'",
            GRID_FILE_UNITS=f"'degrees'",
            DEPTH_FILE=f"'{dep_file}'",
            DEPTH_FILE_UNITS=f"'meters'",
            SIGMA_LEVELS_FILE=f"'{prefix}_sigma.dat'",
            CORIOLIS_FILE=f"'{prefix}_cor.dat'",
            SPONGE_FILE=f"'{prefix}_spg.dat'",
        ))

        return "\n".join(sections) + "\n"

    def _section(self, name: str, **params) -> str:
        """
        Build a Fortran namelist section.

        Args:
            name: Namelist section name (e.g., "NML_CASE")
            **params: Parameter name-value pairs

        Returns:
            Formatted namelist section string
        """
        lines = [f" &{name}"]
        for key, value in params.items():
            lines.append(f"  {key} = {value},")
        lines.append(f" /")
        lines.append("")
        return "\n".join(lines)

    def generate_for_cycle(
        self,
        output_path: Path,
        pdy: str,
        cyc: int,
        stage: str = "nowcast",
    ) -> Path:
        """
        Generate run_control.nml for a specific forecast cycle.

        Convenience method matching the interface used by
        SCHISM's ParamNmlGenerator.

        Args:
            output_path: Full path to output file (or directory)
            pdy: Production date (YYYYMMDD)
            cyc: Cycle hour
            stage: Workflow stage

        Returns:
            Path to generated run_control.nml
        """
        if output_path.suffix:
            output_dir = output_path.parent
        else:
            output_dir = output_path

        return self.generate(output_dir, stage=stage, pdy=pdy, cyc=cyc)

    def __repr__(self) -> str:
        ofs_name = getattr(self.config, 'RUN', 'unknown')
        return f"FVCOMConfigGenerator(ofs={ofs_name})"
