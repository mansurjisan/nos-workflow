"""
SCHISM param.nml Generator

Generates SCHISM namelist parameter file (param.nml) from configuration.
This is a critical file that controls all model settings including:
- Run duration and time stepping
- Physics options (turbulence, transport, etc.)
- Output configuration
- Boundary condition settings
- Restart/hotstart configuration

The generator supports both STOFS and COMF naming conventions
and can read template files for site-specific customization.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

log = logging.getLogger(__name__)


@dataclass
class SchismParameters:
    """
    SCHISM model parameters for param.nml generation.

    Contains all namelist groups:
    - CORE: Core model settings
    - OPT: Optional modules (SED, WWM, etc.)
    - SCHOUT: Output control

    Parameters follow SCHISM v5.10 conventions.
    """

    # =========================================================================
    # CORE Namelist
    # =========================================================================

    # Run control
    ipre: int = 0          # Pre-processor flag (0=normal run, 1=pre-process)
    ibc: int = 0           # Baroclinic/barotropic mode
    ibtp: int = 1          # Barotropic solver (1=implicit)
    rnday: float = 5.0     # Total run length in days
    dt: float = 150.0      # Time step in seconds

    # Coordinate system
    ics: int = 2           # Coordinate system (1=Cartesian, 2=lon/lat)
    slam0: float = -77.0   # Reference longitude for CPP projection
    sfea0: float = 35.0    # Reference latitude for CPP projection

    # Hotstart/restart
    ihot: int = 0          # Hotstart flag (0=cold, 1=hotstart, 2=hotstart+adjust)
    nhot: int = 1          # Write hotstart every nhot output steps
    nhot_write: int = 1    # Number of hotstart files to keep

    # Vertical grid
    ivcor: int = 1         # Vertical coordinate (1=localized sigma, 2=SZ)
    nvrt: int = 51         # Number of vertical levels

    # Coriolis
    ncor: int = 1          # Coriolis (0=f-plane, 1=beta-plane, -1=variable)
    coricoef: float = 0.0  # Coriolis coefficient for f-plane

    # Bottom drag
    nchi: int = 0          # Bottom friction (0=const, 1=depth-dep, -1=from file)
    dzb_min: float = 0.5   # Minimum bottom cell thickness
    hmin_radstress: float = 1.0  # Min depth for radiation stress

    # Wind
    nws: int = 2           # Wind/pressure input (0=off, 1=const, 2=sflux)
    wtiminc: float = 3600.0  # Wind time increment (s)
    drampwind: float = 1.0   # Wind ramp-up time (days)

    # Heat flux
    ihconsv: int = 1       # Heat conservation (0=off, 1=on)
    isconsv: int = 1       # Salt conservation (0=off, 1=on)
    itur: int = 3          # Turbulence closure (3=GLS, 4=KL)
    dfv0: float = 1e-6     # Background vertical diffusivity
    dfh0: float = 1e-6     # Background horizontal diffusivity

    # Transport
    ntracers: int = 2      # Number of tracers (2=T,S)
    h_tvd: float = 5.0     # Depth threshold for TVD

    # Tides
    iettype: int = 3       # Elevation BC type (3=tidal)
    ifltype: int = 3       # Flow BC type (3=tidal)
    itetype: int = 0       # Temperature BC type
    isatype: int = 0       # Salinity BC type

    # Output flags
    nspool: int = 12       # Global output interval (time steps)
    ihfskip: int = 576     # Stack file increment (time steps)

    # =========================================================================
    # SCHOUT Namelist - Output Control
    # =========================================================================

    # 2D output variables
    iof_elev: int = 1      # Surface elevation
    iof_prmsl: int = 1     # Pressure at MSL
    iof_dahv: int = 1      # Depth-averaged horizontal velocity
    iof_wind: int = 1      # Wind speed
    iof_flux: int = 0      # Horizontal flux

    # 3D output variables
    iof_temp: int = 1      # Temperature
    iof_salt: int = 1      # Salinity
    iof_hvel: int = 1      # Horizontal velocity
    iof_vert: int = 0      # Vertical velocity
    iof_dens: int = 0      # Density
    iof_diff: int = 0      # Diffusivity
    iof_visc: int = 0      # Viscosity
    iof_tdff: int = 0      # Temperature diffusivity

    # Station output
    iout_sta: int = 1      # Station output flag
    nspool_sta: int = 24   # Station output interval (time steps)

    # =========================================================================
    # Additional parameters (from templates)
    # =========================================================================

    # Custom parameters dictionary for template merging
    custom_params: Dict[str, Any] = field(default_factory=dict)

    def to_namelist_string(self) -> str:
        """Convert parameters to Fortran namelist format."""
        lines = []

        # CORE namelist
        lines.append("&CORE")
        lines.append(f"  ipre = {self.ipre}")
        lines.append(f"  ibc = {self.ibc}")
        lines.append(f"  ibtp = {self.ibtp}")
        lines.append(f"  rnday = {self.rnday:.6f}")
        lines.append(f"  dt = {self.dt:.1f}")
        lines.append(f"  ics = {self.ics}")
        lines.append(f"  slam0 = {self.slam0:.6f}")
        lines.append(f"  sfea0 = {self.sfea0:.6f}")
        lines.append(f"  ihot = {self.ihot}")
        lines.append(f"  nhot = {self.nhot}")
        lines.append(f"  nhot_write = {self.nhot_write}")
        lines.append(f"  ivcor = {self.ivcor}")
        lines.append(f"  nvrt = {self.nvrt}")
        lines.append(f"  ncor = {self.ncor}")
        lines.append(f"  coricoef = {self.coricoef}")
        lines.append(f"  nchi = {self.nchi}")
        lines.append(f"  dzb_min = {self.dzb_min}")
        lines.append(f"  hmin_radstress = {self.hmin_radstress}")
        lines.append(f"  nws = {self.nws}")
        lines.append(f"  wtiminc = {self.wtiminc}")
        lines.append(f"  drampwind = {self.drampwind}")
        lines.append(f"  ihconsv = {self.ihconsv}")
        lines.append(f"  isconsv = {self.isconsv}")
        lines.append(f"  itur = {self.itur}")
        lines.append(f"  dfv0 = {self.dfv0:.2e}")
        lines.append(f"  dfh0 = {self.dfh0:.2e}")
        lines.append(f"  ntracers = {self.ntracers}")
        lines.append(f"  h_tvd = {self.h_tvd}")
        lines.append(f"  nspool = {self.nspool}")
        lines.append(f"  ihfskip = {self.ihfskip}")
        lines.append("/\n")

        # OPT namelist (optional modules - disabled by default)
        lines.append("&OPT")
        lines.append("  isav = 0       !SAV module off")
        lines.append("  nstep_ice = 1  !Ice module steps")
        lines.append("  isplit = 1     !Baroclinic splitting")
        lines.append("/\n")

        # SCHOUT namelist (output control)
        lines.append("&SCHOUT")
        lines.append(f"  iof_elev = {self.iof_elev}")
        lines.append(f"  iof_prmsl = {self.iof_prmsl}")
        lines.append(f"  iof_dahv = {self.iof_dahv}")
        lines.append(f"  iof_wind = {self.iof_wind}")
        lines.append(f"  iof_flux = {self.iof_flux}")
        lines.append(f"  iof_temp = {self.iof_temp}")
        lines.append(f"  iof_salt = {self.iof_salt}")
        lines.append(f"  iof_hvel = {self.iof_hvel}")
        lines.append(f"  iof_vert = {self.iof_vert}")
        lines.append(f"  iof_dens = {self.iof_dens}")
        lines.append(f"  iof_diff = {self.iof_diff}")
        lines.append(f"  iof_visc = {self.iof_visc}")
        lines.append(f"  iof_tdff = {self.iof_tdff}")
        lines.append(f"  iout_sta = {self.iout_sta}")
        lines.append(f"  nspool_sta = {self.nspool_sta}")
        lines.append("/\n")

        return "\n".join(lines)


class ParamNmlGenerator:
    """
    Generate param.nml for SCHISM from configuration.

    Supports:
    - Template-based generation (read existing param.nml and modify)
    - Full generation from StofsConfig
    - Time-aware settings (start time, run duration)
    - Hotstart/coldstart handling

    Example:
        generator = ParamNmlGenerator(config)
        generator.generate(output_path / "param.nml")
    """

    # Default run periods for different systems
    DEFAULT_RUN_PERIODS = {
        "stofs_3d_atl": 5.0,    # 5 days (24hr nowcast + 96hr forecast)
        "stofs_3d_pac": 5.0,    # 5 days
        "secofs": 3.5,          # 3.5 days (12hr nowcast + 72hr forecast)
    }

    # Default output intervals (in time steps)
    DEFAULT_OUTPUT_INTERVALS = {
        "stofs_3d_atl": {"nspool": 12, "nspool_sta": 24},
        "stofs_3d_pac": {"nspool": 12, "nspool_sta": 24},
        "secofs": {"nspool": 8, "nspool_sta": 16},
    }

    def __init__(self, config) -> None:
        """
        Initialize param.nml generator.

        Args:
            config: StofsConfig instance
        """
        self.config = config
        self.params = SchismParameters()

        # Initialize from config
        self._init_from_config()

    def _init_from_config(self) -> None:
        """Initialize parameters from StofsConfig."""
        # Time stepping
        self.params.dt = self.config.dt

        # Vertical levels
        self.params.nvrt = self.config.nvrt

        # Run duration
        run_name = self.config.RUN.lower()
        self.params.rnday = self.DEFAULT_RUN_PERIODS.get(run_name, 5.0)

        # Coordinate reference point (center of domain)
        self.params.slam0 = (self.config.lon_min + self.config.lon_max) / 2.0
        self.params.sfea0 = (self.config.lat_min + self.config.lat_max) / 2.0

        # Output intervals
        intervals = self.DEFAULT_OUTPUT_INTERVALS.get(run_name, {})
        self.params.nspool = intervals.get("nspool", 12)
        self.params.nspool_sta = intervals.get("nspool_sta", 24)

        # Hotstart settings
        self.params.ihot = self.config.ihot if self.config.hotstart_enabled else 0

    def set_run_period(
        self,
        start_time: datetime,
        nowcast_hours: int = 24,
        forecast_hours: int = 96,
    ) -> None:
        """
        Set run period based on nowcast and forecast lengths.

        Args:
            start_time: Model start time (PDYHH_NCAST_BEGIN)
            nowcast_hours: Nowcast length in hours
            forecast_hours: Forecast length in hours
        """
        total_hours = nowcast_hours + forecast_hours
        self.params.rnday = total_hours / 24.0

        log.info(f"Run period: {nowcast_hours}hr nowcast + {forecast_hours}hr forecast = {self.params.rnday:.2f} days")

    def set_hotstart(self, enabled: bool = True, ihot: int = 1) -> None:
        """
        Configure hotstart settings.

        Args:
            enabled: Whether hotstart is enabled
            ihot: Hotstart mode (1=standard, 2=adjust time)
        """
        self.params.ihot = ihot if enabled else 0
        log.info(f"Hotstart: {'enabled' if enabled else 'disabled'} (ihot={self.params.ihot})")

    def set_output_variables(
        self,
        variables_2d: Optional[List[str]] = None,
        variables_3d: Optional[List[str]] = None,
    ) -> None:
        """
        Configure output variables.

        Args:
            variables_2d: List of 2D variables to output
            variables_3d: List of 3D variables to output
        """
        # Map variable names to output flags
        var_2d_map = {
            "elev": "iof_elev",
            "elevation": "iof_elev",
            "prmsl": "iof_prmsl",
            "pressure": "iof_prmsl",
            "dahv": "iof_dahv",
            "wind": "iof_wind",
            "flux": "iof_flux",
        }

        var_3d_map = {
            "temp": "iof_temp",
            "temperature": "iof_temp",
            "salt": "iof_salt",
            "salinity": "iof_salt",
            "hvel": "iof_hvel",
            "velocity": "iof_hvel",
            "vert": "iof_vert",
            "dens": "iof_dens",
            "density": "iof_dens",
        }

        if variables_2d:
            for var in variables_2d:
                flag = var_2d_map.get(var.lower())
                if flag and hasattr(self.params, flag):
                    setattr(self.params, flag, 1)

        if variables_3d:
            for var in variables_3d:
                flag = var_3d_map.get(var.lower())
                if flag and hasattr(self.params, flag):
                    setattr(self.params, flag, 1)

    def load_template(self, template_path: Path) -> None:
        """
        Load and parse a param.nml template file.

        This allows using site-specific templates with pre-configured
        parameters while still updating time-dependent settings.

        Args:
            template_path: Path to template param.nml
        """
        if not template_path.exists():
            log.warning(f"Template not found: {template_path}")
            return

        log.info(f"Loading param.nml template: {template_path}")

        try:
            with open(template_path, 'r') as f:
                content = f.read()

            # Parse namelist format (simplified parser)
            current_group = None
            for line in content.split('\n'):
                line = line.strip()

                # Skip comments and empty lines
                if not line or line.startswith('!'):
                    continue

                # Detect namelist group
                if line.startswith('&'):
                    current_group = line[1:].upper()
                    continue

                if line == '/' or line.startswith('/'):
                    current_group = None
                    continue

                # Parse parameter assignments
                if '=' in line and current_group:
                    # Handle inline comments
                    if '!' in line:
                        line = line.split('!')[0].strip()

                    parts = line.split('=')
                    if len(parts) >= 2:
                        param_name = parts[0].strip().lower()
                        param_value = parts[1].strip().rstrip(',')

                        # Try to set on params object
                        if hasattr(self.params, param_name):
                            try:
                                current_value = getattr(self.params, param_name)
                                if isinstance(current_value, int):
                                    setattr(self.params, param_name, int(float(param_value)))
                                elif isinstance(current_value, float):
                                    setattr(self.params, param_name, float(param_value))
                                else:
                                    setattr(self.params, param_name, param_value)
                            except ValueError:
                                pass
                        else:
                            # Store in custom_params for potential use
                            self.params.custom_params[param_name] = param_value

            log.info(f"Loaded {len(self.params.custom_params)} custom parameters from template")

        except Exception as e:
            log.error(f"Error loading template: {e}")

    def generate(self, output_path: Path, use_template: bool = True) -> Path:
        """
        Generate param.nml file.

        Args:
            output_path: Path for output param.nml
            use_template: Whether to try loading template from FIX

        Returns:
            Path to generated file
        """
        log.info("Generating param.nml")

        # Try to load template if requested
        if use_template:
            template_file = self.config.get_fix_file(
                f"{self.config.RUN}_param.nml_6globaloutput"
            )
            if template_file.exists():
                self.load_template(template_file)
            else:
                # Try alternative template name
                alt_template = self.config.get_fix_file(f"{self.config.RUN}_param.nml")
                if alt_template.exists():
                    self.load_template(alt_template)

        # Update time-dependent settings
        self._update_time_settings()

        # Set output variables from config
        self.set_output_variables(
            variables_2d=self.config.output_variables_2d,
            variables_3d=self.config.output_variables_3d,
        )

        # Generate namelist content
        content = self._generate_content()

        # Write file
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w') as f:
            f.write(content)

        log.info(f"Created param.nml: {output_path}")
        log.info(f"  rnday = {self.params.rnday:.4f} days")
        log.info(f"  dt = {self.params.dt:.1f} s")
        log.info(f"  ihot = {self.params.ihot}")
        log.info(f"  nvrt = {self.params.nvrt}")

        return output_path

    def _update_time_settings(self) -> None:
        """Update time-dependent settings."""
        # Calculate run duration from config
        nowcast_hours = getattr(self.config, 'nowcast_length', 6) * 4  # Convert to hours
        forecast_hours = getattr(self.config, 'forecast_length', 48)

        # STOFS uses 24hr nowcast from NCAST_BEGIN
        # Total run = 24hr nowcast + 96hr forecast = 120hr = 5 days
        total_hours = 24 + forecast_hours  # STOFS standard
        self.params.rnday = total_hours / 24.0

        # Calculate output steps
        output_interval_2d = getattr(self.config, 'output_interval_2d', 3600)
        output_interval_sta = getattr(self.config, 'output_interval_station', 360)

        self.params.nspool = int(output_interval_2d / self.params.dt)
        self.params.nspool_sta = int(output_interval_sta / self.params.dt)

        # Calculate ihfskip (outputs per stack file)
        # Typically 24 hours per stack for hourly output
        self.params.ihfskip = int(24 * 3600 / self.params.dt)

    def _generate_content(self) -> str:
        """Generate the full param.nml content."""
        lines = []

        # Header comment
        lines.append(f"! param.nml for {self.config.system_name}")
        lines.append(f"! Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"! RUN={self.config.RUN}, cyc={self.config.cyc:02d}, PDY={self.config.PDY}")
        lines.append("")

        # Main namelist content
        lines.append(self.params.to_namelist_string())

        # Add any custom parameters from template
        if self.params.custom_params:
            lines.append("! Custom parameters from template")
            lines.append("&CUSTOM")
            for name, value in self.params.custom_params.items():
                lines.append(f"  {name} = {value}")
            lines.append("/")

        return "\n".join(lines)

    def generate_for_cycle(
        self,
        output_path: Path,
        pdy: str,
        cyc: int,
        coldstart: bool = False,
    ) -> Path:
        """
        Generate param.nml for a specific cycle.

        This is the main entry point for operational generation.

        Args:
            output_path: Output file path
            pdy: Process date (YYYYMMDD)
            cyc: Cycle hour (0, 6, 12, 18)
            coldstart: Whether this is a cold start

        Returns:
            Path to generated file
        """
        log.info(f"Generating param.nml for cycle {pdy} t{cyc:02d}z")

        # Set hotstart based on coldstart flag
        self.set_hotstart(enabled=not coldstart)

        # Calculate start time (24 hours before PDY+cyc for nowcast)
        forecast_begin = datetime.strptime(f"{pdy}{cyc:02d}", "%Y%m%d%H")
        nowcast_begin = forecast_begin - timedelta(hours=24)

        # Set run period
        self.set_run_period(
            start_time=nowcast_begin,
            nowcast_hours=24,
            forecast_hours=getattr(self.config, 'forecast_length', 96),
        )

        return self.generate(output_path, use_template=True)
