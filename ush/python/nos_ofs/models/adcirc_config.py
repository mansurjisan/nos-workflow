"""
ADCIRC Configuration Generator

Generates ADCIRC fort.15 control files from YAML configuration.

fort.15 is ADCIRC's main parameter file controlling:
- Time stepping and simulation duration
- Tidal forcing (constituent specification)
- Meteorological forcing parameters
- Output control (station timeseries, field output)
- Boundary conditions
- Physical parameters (friction, Coriolis)

The generator uses a template-based approach matching the operational
STOFS-2D-Global workflow which uses sed substitution for runtime values.

Reference: ADCIRC User Manual, Chapter 4 (fort.15 format)
"""

import logging
import math
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# Standard ADCIRC tidal constituent data
# (name, angular_frequency_deg_per_hr, earth_tidal_potential_constant)
TIDAL_CONSTITUENTS = {
    'M2':  {'frequency': 28.9841042,  'amplitude': 0.242334, 'etrf': 0.693, 'nj': 2},
    'S2':  {'frequency': 30.0000000,  'amplitude': 0.112841, 'etrf': 0.693, 'nj': 2},
    'N2':  {'frequency': 28.4397295,  'amplitude': 0.046398, 'etrf': 0.693, 'nj': 2},
    'K2':  {'frequency': 30.0821373,  'amplitude': 0.030704, 'etrf': 0.693, 'nj': 2},
    'K1':  {'frequency': 15.0410686,  'amplitude': 0.141565, 'etrf': 0.736, 'nj': 1},
    'O1':  {'frequency': 13.9430356,  'amplitude': 0.100514, 'etrf': 0.695, 'nj': 1},
    'P1':  {'frequency': 14.9589314,  'amplitude': 0.046843, 'etrf': 0.706, 'nj': 1},
    'Q1':  {'frequency': 13.3986609,  'amplitude': 0.019256, 'etrf': 0.695, 'nj': 1},
}


class ADCIRCConfigGenerator:
    """
    Generate ADCIRC fort.15 control file from YAML configuration.

    This generator produces the fort.15 file that ADCIRC reads at startup.
    It handles different workflow stages (cold start, tidal spinup, nowcast,
    forecast) by adjusting time parameters and forcing flags.

    Usage:
        generator = ADCIRCConfigGenerator(config)
        path = generator.generate(
            output_path=Path("/work/stofs_2d_glo"),
            stage="nowcast",
        )
    """

    # Default ADCIRC settings (can be overridden by YAML config)
    DEFAULTS = {
        # Run control
        'NFOVER': 0,        # Nonlinear finite amplitude option
        'NABOUT': -1,       # Abbreviated output
        'NSCREEN': 100,     # Screen output interval (timesteps)
        'IHOT': 0,          # Hot start flag (0=cold, 67/68=hotstart)
        'IDEN': 0,          # Identifier (not used)
        'NOLIBF': 2,        # Bottom friction: 0=linear, 1=quadratic, 2=hybrid
        'NOLIFA': 2,        # Finite amplitude: 0=off, 1=on, 2=with wetting/drying
        'NOLICA': 0,        # Spatial advection terms
        'NOLICAT': 0,       # Time derivative advection terms
        'NWP': 0,           # Number of nodal attributes from fort.13
        'NCOR': 1,          # Coriolis: 0=constant, 1=spatially varying
        'NTIP': 2,          # Tidal potential: 0=none, 1=forcing, 2=forcing+self-attraction
        'NWS': 0,           # Met forcing: 0=none, 12=OWI NetCDF, etc.
        'NRAMP': 1,         # Ramp function: 0=none, 1=hyperbolic tangent
        'G': 9.81,          # Gravitational acceleration
        'TAU0': -3.0,       # GWCE weighting factor (-3=spatially varying via fort.13)
        # Time parameters
        'DT': 2.0,          # Timestep (seconds)
        'STATIM': 0.0,      # Starting simulation time (days)
        'REFTIM': 0.0,      # Reference time (days)
        'DRAMP': 3.0,       # Ramp period (days)
        'A00': 0.35,        # Time weighting factors for GWCE
        'B00': 0.30,
        'C00': 0.35,
        # Bottom friction
        'CF': 0.0025,       # Bottom friction coefficient (quadratic)
        'ESLM': -0.20,      # Smagorinsky coefficient (negative = spatially varying)
        'CORI': 0.0,        # Coriolis parameter (used only if NCOR=0)
        # Minimum depth for wetting/drying
        'H0': 0.05,         # Minimum water depth (meters)
        # Output control defaults
        'NOUTGE': 1,        # Global elevation output: 0=off, 1=on
        'NOUTGV': 0,        # Global velocity output: 0=off
        'NOUTGC': 0,        # Global concentration output
        'NOUTGW': 0,        # Global wind output
        'NOUTGM': 0,        # Global met output (pressure)
        # Station output
        'NOUTE': 1,         # Station elevation output: 1=on
        'NOUTV': 0,         # Station velocity output
    }

    def __init__(self, config: Any):
        """
        Initialize ADCIRC config generator.

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
        run = model.get('run', {})
        if key in run:
            return run[key]
        return default

    def _get_forcing_param(self, section: str, key: str, default: Any = None) -> Any:
        """Get a forcing parameter from YAML config."""
        forcing = self._yaml_data.get('forcing', {})
        section_cfg = forcing.get(section, {})
        return section_cfg.get(key, default)

    def _get_output_param(self, section: str, key: str, default: Any = None) -> Any:
        """Get an output parameter from YAML config."""
        output = self._yaml_data.get('output', {})
        section_cfg = output.get(section, {})
        return section_cfg.get(key, default)

    def generate(
        self,
        output_path: Path,
        stage: str = "nowcast",
        pdy: str = None,
        cyc: int = None,
    ) -> Path:
        """
        Generate ADCIRC fort.15 control file.

        Args:
            output_path: Directory to write fort.15
            stage: Workflow stage ("cold_spinup", "tide_nowcast",
                   "tide_forecast", "surf_nowcast", "surf_forecast",
                   "nowcast", "forecast")
            pdy: Production date (YYYYMMDD), defaults to config value
            cyc: Cycle hour, defaults to config value

        Returns:
            Path to generated fort.15 file
        """
        output_dir = Path(output_path)
        output_dir.mkdir(parents=True, exist_ok=True)
        fort15_path = output_dir / "fort.15"

        pdy = pdy or getattr(self.config, 'PDY', datetime.now().strftime('%Y%m%d'))
        cyc = cyc if cyc is not None else getattr(self.config, 'cyc', 0)

        content = self._build_fort15(stage, pdy, cyc)

        with open(fort15_path, 'w') as f:
            f.write(content)

        log.info(f"Generated ADCIRC fort.15: {fort15_path}")
        return fort15_path

    def _build_fort15(self, stage: str, pdy: str, cyc: int) -> str:
        """Build the fort.15 file content."""
        ofs_name = getattr(self.config, 'RUN', 'stofs_2d_glo')
        prefix = self._yaml_data.get('system', {}).get('prefix', ofs_name)

        # Determine run parameters based on stage
        cycle_dt = datetime.strptime(f"{pdy}{cyc:02d}", "%Y%m%d%H")
        run_cfg = self._yaml_data.get('model', {}).get('run', {})

        # Stage-specific configuration
        is_cold = 'cold' in stage.lower()
        is_tidal = 'tide' in stage.lower()
        is_surface = 'surf' in stage.lower()
        is_forecast = 'forecast' in stage.lower()
        is_nowcast = 'nowcast' in stage.lower() or stage == 'nowcast'

        # Hotstart flag
        if is_cold:
            ihot = 0
        else:
            ihot = self._get_model_param('ihot', 67)

        # Run length in days
        if is_cold:
            rnday = run_cfg.get('spinup_days', 15.0)
        elif is_forecast:
            forecast_days = run_cfg.get('forecast_days', 7.5)
            # STOFS-2D splits forecast into 2 segments
            if '1' in stage:
                rnday = forecast_days / 2.0
            elif '2' in stage:
                rnday = forecast_days / 2.0
            else:
                rnday = forecast_days
        else:
            # Nowcast
            nowcast_hours = run_cfg.get('nowcast_hours', 6)
            rnday = nowcast_hours / 24.0

        # Timestep
        dt = self._get_model_param('dt', self.DEFAULTS['DT'])

        # Meteorological forcing
        if is_surface or (not is_tidal and not is_cold):
            nws = self._get_model_param('nws', 12)  # OWI NetCDF
        else:
            nws = 0  # No met forcing for tidal-only runs

        # Ramp
        dramp = self._get_model_param('dramp', self.DEFAULTS['DRAMP'])
        nramp = 1 if dramp > 0 else 0

        # Tidal constituents
        tidal_cfg = self._yaml_data.get('forcing', {}).get('tidal', {})
        constituents = tidal_cfg.get('constituents', ['M2', 'S2', 'N2', 'K2', 'K1', 'O1', 'P1', 'Q1'])
        ntip = self._get_model_param('ntip', self.DEFAULTS['NTIP'])
        tides_enabled = tidal_cfg.get('enabled', True)

        # Number of nodal attributes from fort.13
        nwp = self._get_model_param('nwp', self.DEFAULTS['NWP'])

        # Nodal attribute names (if NWP > 0)
        nodal_attr_names = self._get_model_param('nodal_attributes', [])
        if not nodal_attr_names and nwp > 0:
            nodal_attr_names = [
                'mannings_n_at_sea_floor',
                'primitive_weighting_in_continuity_equation',
            ]
            nwp = len(nodal_attr_names)

        # Output intervals (in seconds for conversion to timestep counts)
        station_interval = self._get_output_param('stations', 'interval', 360.0)
        field_interval = self._get_output_param('fields_2d', 'interval', 3600.0)

        # Convert to timestep counts
        nspoolge = int(field_interval / dt) if field_interval > 0 else 0
        nspoole = int(station_interval / dt) if station_interval > 0 else 0

        # Build fort.15 lines
        lines = []

        # Line 1: Run description (32 char header)
        lines.append(f"{ofs_name.upper()} {stage} ! 32 CHARACTER ALPHANUMERIC RUN DESCRIPTION")

        # Line 2: Run identification (24 char)
        lines.append(f"{pdy}{cyc:02d}_{stage} ! 24 CHARACTER ALPHANUMERIC RUN IDENTIFICATION")

        # Line 3: NFOVER
        lines.append(f"{self.DEFAULTS['NFOVER']} ! NFOVER - NONFATAL ERROR OVERRIDE OPTION")

        # Line 4: NABOUT
        lines.append(f"{self.DEFAULTS['NABOUT']} ! NABOUT - ABBREVIATED OUTPUT OPTION PARAMETER")

        # Line 5: NSCREEN
        lines.append(f"{self.DEFAULTS['NSCREEN']} ! NSCREEN - OUTPUT TO SCREEN/UNIT 6")

        # Line 6: IHOT
        lines.append(f"{ihot} ! IHOT - HOT START PARAMETER")

        # Line 7: ICS (coordinate system: 1=Cartesian, 2=spherical)
        lines.append(f"2 ! ICS - COORDINATE SYSTEM (2=SPHERICAL)")

        # Line 8: IM (model type: 0=2DDI barotropic, 111313=3D, etc.)
        lines.append(f"0 ! IM - MODEL TYPE (0=2DDI BAROTROPIC)")

        # Line 9: NOLIBF (bottom friction)
        nolibf = self._get_model_param('nolibf', self.DEFAULTS['NOLIBF'])
        lines.append(f"{nolibf} ! NOLIBF - BOTTOM FRICTION OPTION")

        # Line 10: NOLIFA
        nolifa = self._get_model_param('nolifa', self.DEFAULTS['NOLIFA'])
        lines.append(f"{nolifa} ! NOLIFA - FINITE AMPLITUDE OPTION")

        # Line 11: NOLICA
        lines.append(f"{self.DEFAULTS['NOLICA']} ! NOLICA - SPATIAL ADVECTION OPTION")

        # Line 12: NOLICAT
        lines.append(f"{self.DEFAULTS['NOLICAT']} ! NOLICAT - TIME DERIVATIVE ADVECTION OPTION")

        # Line 13: NWP
        lines.append(f"{nwp} ! NWP - NUMBER OF NODAL ATTRIBUTES")

        # Nodal attribute names (one per line if NWP > 0)
        for attr_name in nodal_attr_names[:nwp]:
            lines.append(f"{attr_name}")

        # Line: NCOR
        ncor = self._get_model_param('ncor', self.DEFAULTS['NCOR'])
        lines.append(f"{ncor} ! NCOR - CORIOLIS OPTION")

        # Line: NTIP
        if tides_enabled:
            lines.append(f"{ntip} ! NTIP - TIDAL POTENTIAL OPTION")
        else:
            lines.append(f"0 ! NTIP - TIDAL POTENTIAL OPTION (DISABLED)")

        # Line: NWS
        lines.append(f"{nws} ! NWS - WIND STRESS AND PRESSURE OPTION")

        # Line: NRAMP
        lines.append(f"{nramp} ! NRAMP - RAMP FUNCTION OPTION")

        # Line: G
        lines.append(f"{self.DEFAULTS['G']:.4f} ! G - GRAVITATIONAL ACCELERATION")

        # Line: TAU0
        tau0 = self._get_model_param('tau0', self.DEFAULTS['TAU0'])
        lines.append(f"{tau0} ! TAU0 - GENERALIZED WAVE CONTINUITY EQUATION WEIGHTING")

        # Line: DT
        lines.append(f"{dt:.6f} ! DT - TIMESTEP (SECONDS)")

        # Line: STATIM
        lines.append(f"{self.DEFAULTS['STATIM']:.4f} ! STATIM - STARTING TIME (DAYS)")

        # Line: REFTIM
        lines.append(f"{self.DEFAULTS['REFTIM']:.4f} ! REFTIM - REFERENCE TIME (DAYS)")

        # Line: WTIMINC (met forcing time increment, only if NWS > 0)
        if nws != 0:
            wtiminc = self._get_model_param('wtiminc', 3600)
            lines.append(f"{wtiminc} ! WTIMINC - MET FORCING TIME INCREMENT (SECONDS)")

        # Line: RNDAY
        lines.append(f"{rnday:.6f} ! RNDAY - TOTAL LENGTH OF SIMULATION (DAYS)")

        # Line: DRAMP (only if NRAMP > 0)
        if nramp > 0:
            lines.append(f"{dramp:.4f} ! DRAMP - RAMP PERIOD (DAYS)")

        # Line: A00 B00 C00 (time weighting for GWCE)
        lines.append(
            f"{self.DEFAULTS['A00']:.4f} {self.DEFAULTS['B00']:.4f} "
            f"{self.DEFAULTS['C00']:.4f} ! A00, B00, C00 - TIME WEIGHTING FACTORS"
        )

        # Line: H0 (minimum depth)
        h0 = self._get_model_param('h0', self.DEFAULTS['H0'])
        lines.append(f"{h0:.4f} 0 0 0.05 ! H0, NODEDRYMIN, NODEWETRMP, VELMIN")

        # Line: SLAM0 SFEA0 (reference longitude/latitude for spherical coordinates)
        slam0 = self._get_model_param('slam0', 0.0)
        sfea0 = self._get_model_param('sfea0', 0.0)
        lines.append(f"{slam0:.4f} {sfea0:.4f} ! SLAM0, SFEA0 - CENTER OF CPP PROJECTION")

        # Line: CF (bottom friction coefficient)
        cf = self._get_model_param('cf', self.DEFAULTS['CF'])
        if nolibf == 0:
            # Linear friction
            lines.append(f"{cf} ! TAU - LINEAR BOTTOM FRICTION COEFFICIENT")
        elif nolibf == 1:
            # Quadratic friction
            lines.append(f"{cf} ! CF - QUADRATIC BOTTOM FRICTION COEFFICIENT")
        else:
            # Hybrid nonlinear (nolibf=2): CF HBREAK FTHETA FGAMMA
            hbreak = self._get_model_param('hbreak', 1.0)
            ftheta = self._get_model_param('ftheta', 10.0)
            fgamma = self._get_model_param('fgamma', 0.3333)
            lines.append(
                f"{cf} {hbreak} {ftheta} {fgamma} "
                f"! CF, HBREAK, FTHETA, FGAMMA"
            )

        # Line: ESLM (horizontal eddy viscosity)
        eslm = self._get_model_param('eslm', self.DEFAULTS['ESLM'])
        lines.append(f"{eslm} ! ESLM - HORIZONTAL EDDY VISCOSITY (SMAGORINSKY IF <0)")

        # Line: CORI (Coriolis, only used if NCOR=0)
        lines.append(f"{self.DEFAULTS['CORI']} ! CORI - CORIOLIS PARAMETER")

        # =====================================================================
        # Tidal Forcing Section
        # =====================================================================
        if tides_enabled and ntip > 0:
            # NTIF - number of tidal potential constituents
            ntif = len(constituents)
            lines.append(f"{ntif} ! NTIF - NUMBER OF TIDAL POTENTIAL CONSTITUENTS")

            for const_name in constituents:
                if const_name.upper() in TIDAL_CONSTITUENTS:
                    const = TIDAL_CONSTITUENTS[const_name.upper()]
                    # Each constituent: TIPOTAG, TPK, AMIGT, ETRF, FFT, FACET
                    lines.append(f"{const_name.upper()}")
                    lines.append(
                        f"  {const['amplitude']:.6f}  "
                        f"{const['frequency']:.10f}  "
                        f"{const['etrf']:.6f}  "
                        f"1.000000  0.000000"
                    )
                else:
                    log.warning(f"Unknown tidal constituent: {const_name}")

            # NBFR - number of tidal forcing frequencies on open boundaries
            nbfr = len(constituents)
            lines.append(f"{nbfr} ! NBFR - NUMBER OF FORCING FREQUENCIES ON OPEN BOUNDARIES")

            for const_name in constituents:
                if const_name.upper() in TIDAL_CONSTITUENTS:
                    const = TIDAL_CONSTITUENTS[const_name.upper()]
                    lines.append(f"{const_name.upper()}")
                    lines.append(
                        f"  {const['frequency']:.10f}  "
                        f"1.000000  0.000000"
                    )

            # Boundary forcing - each open boundary segment gets amplitude/phase
            # per constituent. In the operational system, these are pre-computed
            # and stored in fort.15 templates. Here we write placeholder
            # comments since actual values come from the tide_fac executable.
            lines.append(f"! NOTE: Boundary tidal forcing amplitudes and phases")
            lines.append(f"! are computed by tide_fac and inserted at runtime")
        else:
            lines.append(f"0 ! NTIF - NO TIDAL POTENTIAL")
            lines.append(f"0 ! NBFR - NO TIDAL BOUNDARY FORCING")

        # =====================================================================
        # Output Control Section
        # =====================================================================

        # --- Global (field) elevation output ---
        noutge = self.DEFAULTS['NOUTGE'] if self._get_output_param('fields_2d', 'enabled', True) else 0
        toutsge = 0.0  # Start of output (days from STATIM)
        toutfge = rnday  # End of output
        lines.append(
            f"{noutge} {toutsge:.4f} {toutfge:.4f} {nspoolge} "
            f"! NOUTGE, TOUTSGE, TOUTFGE, NSPOOLGE"
        )

        # --- Global velocity output ---
        noutgv = self.DEFAULTS['NOUTGV']
        lines.append(
            f"{noutgv} {toutsge:.4f} {toutfge:.4f} {nspoolge} "
            f"! NOUTGV, TOUTSGV, TOUTFGV, NSPOOLGV"
        )

        # --- Global met output (if NWS != 0) ---
        if nws != 0:
            noutgm = 1  # Enable met output for surface forcing runs
            lines.append(
                f"{noutgm} {toutsge:.4f} {toutfge:.4f} {nspoolge} "
                f"! NOUTGM, TOUTSGM, TOUTFGM, NSPOOLGM"
            )
        else:
            lines.append(
                f"0 {toutsge:.4f} {toutfge:.4f} {nspoolge} "
                f"! NOUTGM, TOUTSGM, TOUTFGM, NSPOOLGM"
            )

        # --- Station elevation output ---
        stations_enabled = self._get_output_param('stations', 'enabled', True)
        noute = 1 if stations_enabled else 0
        toutse = 0.0
        toutfe = rnday
        lines.append(
            f"{noute} {toutse:.4f} {toutfe:.4f} {nspoole} "
            f"! NOUTE, TOUTSE, TOUTFE, NSPOOLE"
        )

        # Number of station locations (0 = read from fort.15, stations in fort.71)
        # In production, station list comes from a separate section
        n_stations = self._get_output_param('stations', 'n_stations', 0)
        lines.append(f"{n_stations} ! NSTAE - NUMBER OF ELEVATION RECORDING STATIONS")

        # Station velocity output
        noutv = self.DEFAULTS['NOUTV']
        lines.append(
            f"{noutv} {toutse:.4f} {toutfe:.4f} {nspoole} "
            f"! NOUTV, TOUTSV, TOUTFV, NSPOOLV"
        )
        lines.append(f"0 ! NSTAV - NUMBER OF VELOCITY RECORDING STATIONS")

        # --- Max elevation output (maxele.63) ---
        max_enabled = self._get_output_param('max_envelope', 'enabled', True)
        if max_enabled:
            lines.append(f"1 {toutsge:.4f} {toutfge:.4f} ! NOUTGE_MAX (MAXELE.63)")
        else:
            lines.append(f"0 {toutsge:.4f} {toutfge:.4f} ! NOUTGE_MAX (MAXELE.63)")

        # --- Hotstart output control ---
        # NHSTAR: hotstart output interval flag
        # NHSINC: hotstart output interval (timesteps)
        nhstar = 5 if ihot > 0 or not is_cold else 0
        nhsinc = int(rnday * 86400 / dt)  # Write at end of run
        lines.append(f"{nhstar} {nhsinc} ! NHSTAR, NHSINC - HOTSTART OUTPUT")

        # =====================================================================
        # Iteration Control
        # =====================================================================
        lines.append(f"1 1.0E-10 25 ! ITITER, ISLDIA, CONVCR, ITMAX")

        # =====================================================================
        # Met Forcing File Names (for NWS=12, OWI NetCDF)
        # =====================================================================
        if nws == 12:
            lines.append(f"! OWI NetCDF forcing files")
            lines.append(f"fort.221.nc ! Pressure field file")
            lines.append(f"fort.222.nc ! Wind u-component file")
            lines.append(f"fort.225.nc ! Wind v-component file")

        lines.append(f"! END OF FORT.15")

        return "\n".join(lines) + "\n"

    def generate_for_cycle(
        self,
        output_path: Path,
        pdy: str,
        cyc: int,
        stage: str = "nowcast",
    ) -> Path:
        """
        Generate fort.15 for a specific forecast cycle.

        Convenience method matching the interface used by other model
        config generators.

        Args:
            output_path: Full path to output file (or directory)
            pdy: Production date (YYYYMMDD)
            cyc: Cycle hour
            stage: Workflow stage

        Returns:
            Path to generated fort.15
        """
        if output_path.suffix:
            output_dir = output_path.parent
        else:
            output_dir = output_path

        return self.generate(output_dir, stage=stage, pdy=pdy, cyc=cyc)

    def get_stage_params(self, stage: str) -> Dict[str, Any]:
        """
        Get stage-specific parameters for the STOFS-2D-Global workflow.

        The STOFS-2D-Global workflow has multiple stages with different
        configurations:
        - COLD_SPINUP: ihot=0, nws=0, long spinup
        - TIDE_NOWCAST: ihot=67, nws=0
        - TIDE_FORECAST: ihot=67, nws=0
        - SURF_NOWCAST: ihot=67, nws=12 (with atmospheric forcing)
        - SURF_FORECAST: ihot=67, nws=12

        Args:
            stage: Stage name

        Returns:
            Dict of stage-specific parameters
        """
        stage_lower = stage.lower()

        params = {
            'cold_spinup': {
                'ihot': 0, 'nws': 0, 'description': 'Tidal spinup from rest',
            },
            'tide_nowcast': {
                'ihot': 67, 'nws': 0, 'description': 'Tidal-only nowcast',
            },
            'tide_forecast1': {
                'ihot': 67, 'nws': 0, 'description': 'Tidal-only forecast phase 1',
            },
            'tide_forecast2': {
                'ihot': 67, 'nws': 0, 'description': 'Tidal-only forecast phase 2',
            },
            'surf_nowcast': {
                'ihot': 67, 'nws': 12, 'description': 'Surface forcing nowcast',
            },
            'surf_forecast1': {
                'ihot': 67, 'nws': 12, 'description': 'Surface forcing forecast phase 1',
            },
            'surf_forecast2': {
                'ihot': 67, 'nws': 12, 'description': 'Surface forcing forecast phase 2',
            },
        }

        return params.get(stage_lower, {'ihot': 67, 'nws': 12, 'description': stage})

    def __repr__(self) -> str:
        ofs_name = getattr(self.config, 'RUN', 'unknown')
        return f"ADCIRCConfigGenerator(ofs={ofs_name})"
