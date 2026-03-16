#!/usr/bin/env python3
"""
Enhanced YAML-to-Shell Environment Variable Bridge

This module provides a bridge between YAML configuration and shell scripts,
allowing both STOFS and nosofs (COMF) shell scripts to read configuration
values from the unified YAML configuration system.

Features:
- Supports both STOFS (stofs_3d_atl) and nosofs (secofs) frameworks
- Uses shell_mappings from YAML to determine variable names
- Computes derived values (LEN_FORECAST, N_DAYS_MODEL_RUN_PERIOD, etc.)
- Outputs shell export statements or JSON

Usage in shell scripts:
    # Export all variables:
    eval $(python3 -m nos_ofs.yaml_to_env stofs_3d_atl.yaml)

    # Export specific section:
    eval $(python3 -m nos_ofs.yaml_to_env stofs_3d_atl.yaml --section domain)

    # Export for nosofs framework:
    eval $(python3 -m nos_ofs.yaml_to_env secofs.yaml --framework comf)

Author: Mansur Ali Jisan (NOS/CO-OPS)
Version: 2.3.0
"""

import sys
import argparse
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, Union

import yaml


def load_yaml_with_inheritance(yaml_path: Path, base_dir: Optional[Path] = None) -> Dict:
    """Load YAML file with _base inheritance support."""
    if base_dir is None:
        base_dir = yaml_path.parent

    with open(yaml_path, 'r') as f:
        data = yaml.safe_load(f) or {}

    # Handle inheritance
    base_name = data.pop('_base', None)
    if base_name:
        # Look for base file
        base_path = base_dir / 'base' / f'{base_name}.yaml'
        if not base_path.exists():
            base_path = base_dir / f'{base_name}.yaml'

        if base_path.exists():
            base_data = load_yaml_with_inheritance(base_path, base_dir)
            data = deep_merge(base_data, data)

    return data


def deep_merge(base: Dict, override: Dict) -> Dict:
    """Deep merge two dictionaries."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def get_nested_value(data: Dict, path: str, default: Any = None) -> Any:
    """Get a value from nested dictionary using dot notation path."""
    keys = path.split('.')
    value = data
    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return default
    return value


def compute_derived_values(data: Dict, runtime_env: Dict) -> Dict[str, Any]:
    """Compute derived values that depend on multiple config values."""
    computed = {}

    # Get run configuration
    model = data.get('model', {})
    run = model.get('run', {})

    hindcast_days = run.get('hindcast_days', 0.25)
    forecast_days = run.get('forecast_days', 5.0)

    # Compute run lengths in hours
    computed['len_nowcast_hours'] = int(hindcast_days * 24)
    computed['len_forecast_hours'] = int(forecast_days * 24)
    computed['total_run_days'] = hindcast_days + forecast_days

    # Per-phase rnday for split nowcast/forecast SCHISM runs
    computed['rnday_nowcast'] = hindcast_days
    computed['rnday_forecast'] = forecast_days

    # Compute time boundaries if PDY and cyc are available
    pdy = runtime_env.get('PDY')
    cyc = runtime_env.get('cyc')

    if pdy and cyc:
        try:
            # Parse cycle time (cyc is string like "00", "06", "12", "18")
            cycle_time = datetime.strptime(f'{pdy}{cyc}', '%Y%m%d%H')

            # Nowcast begin (hindcast back from cycle)
            ncast_begin = cycle_time - timedelta(days=hindcast_days)
            computed['PDYHH_NCAST_BEGIN'] = ncast_begin.strftime('%Y%m%d%H')

            # Forecast begin = cycle time (nowcast end)
            computed['PDYHH_FCAST_BEGIN'] = cycle_time.strftime('%Y%m%d%H')

            # Forecast end
            fcast_end = cycle_time + timedelta(days=forecast_days)
            computed['PDYHH_FCAST_END'] = fcast_end.strftime('%Y%m%d%H')

            # Time boundaries for nosofs
            computed['time_nowcastend'] = cycle_time.strftime('%Y%m%d%H')
            computed['time_hotstart'] = ncast_begin.strftime('%Y%m%d%H')
            computed['time_forecastend'] = fcast_end.strftime('%Y%m%d%H')

        except (ValueError, TypeError):
            pass

    return computed


def get_runtime_from_env() -> Dict[str, Any]:
    """Get runtime values from environment variables."""
    runtime = {}

    # NCO standard environment variables
    env_vars = [
        'PDY', 'cyc', 'envir', 'NET', 'RUN',
        'HOMEnos', 'HOMEstofs', 'FIXofs', 'FIXstofs3d',
        'EXECnos', 'EXECstofs3d', 'USHnos', 'USHstofs3d',
        'PARMnos', 'PARMstofs3d', 'DATA', 'COMOUT', 'COMOUTrerun',
        'COMINgfs', 'COMINhrrr', 'COMINnam', 'COMINrtofs', 'COMINnwm', 'COMINadt',
        'DCOMINusgs', 'DCOMINports', 'NOSBUFR', 'USGSBUFR',
    ]

    for var in env_vars:
        if var in os.environ:
            value = os.environ[var]
            # Keep cyc as string to preserve leading zero (e.g., "00" not "0")
            # Shell scripts expect 2-digit format for time calculations
            runtime[var] = value

    return runtime


def export_shell_mappings(data: Dict, framework: str = 'auto') -> Dict[str, Any]:
    """
    Export variables based on shell_mappings in the YAML.

    Args:
        data: Loaded YAML configuration
        framework: 'stofs', 'comf', or 'auto' (detect from YAML)

    Returns:
        Dictionary of variable names to values
    """
    exports = {}

    # Get runtime from environment
    runtime_env = get_runtime_from_env()

    # Compute derived values
    computed = compute_derived_values(data, runtime_env)

    # Auto-detect framework
    if framework == 'auto':
        system = data.get('system', {})
        framework = system.get('framework', 'stofs')

    # Get shell_mappings from YAML
    shell_mappings = data.get('shell_mappings', {})
    variable_mappings = shell_mappings.get('variables', {})

    # Export variables based on mappings
    for shell_var, yaml_path in variable_mappings.items():
        if yaml_path.startswith('_computed.'):
            # Computed value
            computed_key = yaml_path.split('.', 1)[1]
            if computed_key in computed:
                exports[shell_var] = computed[computed_key]
        else:
            # Value from YAML
            value = get_nested_value(data, yaml_path)
            if value is not None:
                exports[shell_var] = value

    # Add standard exports based on framework
    exports.update(get_standard_exports(data, framework, computed, runtime_env))

    return exports


def get_standard_exports(
    data: Dict,
    framework: str,
    computed: Dict[str, Any],
    runtime_env: Dict[str, Any]
) -> Dict[str, Any]:
    """Get standard exports regardless of shell_mappings."""
    exports = {}

    # System info
    system = data.get('system', {})
    exports['OFS'] = system.get('name', '')
    exports['OFS_NAME'] = system.get('name', '')

    # Model type (uppercase for nosofs)
    model = data.get('model', {})
    ocean_model = model.get('ocean_model', model.get('type', 'SCHISM'))
    exports['OCEAN_MODEL'] = (ocean_model or 'SCHISM').upper()

    # Grid info
    grid = data.get('grid', {})
    exports['GRIDFILE'] = grid.get('files', {}).get('horizontal', '')

    # Domain bounds
    domain = grid.get('domain', {})
    if framework == 'stofs':
        # STOFS uses LONMIN, LONMAX, etc.
        exports['LONMIN'] = domain.get('lon_min', '')
        exports['LONMAX'] = domain.get('lon_max', '')
        exports['LATMIN'] = domain.get('lat_min', '')
        exports['LATMAX'] = domain.get('lat_max', '')
    else:
        # nosofs uses MINLON, MAXLON, etc.
        exports['MINLON'] = domain.get('lon_min', '')
        exports['MAXLON'] = domain.get('lon_max', '')
        exports['MINLAT'] = domain.get('lat_min', '')
        exports['MAXLAT'] = domain.get('lat_max', '')

    # Grid dimensions
    exports['nvrt'] = grid.get('n_levels', '')
    exports['KBm'] = grid.get('n_levels', '')
    exports['np_global'] = grid.get('n_nodes', '')
    exports['ne_global'] = grid.get('n_elements', '')
    exports['ns_global'] = grid.get('n_sides', '')

    # Model physics
    physics = model.get('physics', {})
    exports['DELT_MODEL'] = physics.get('dt', '')

    # Run lengths
    exports['LEN_NOWCAST'] = computed.get('len_nowcast_hours', '')
    exports['LEN_FORECAST'] = computed.get('len_forecast_hours', '')

    # STOFS specific
    if framework == 'stofs':
        exports['N_DAYS_MODEL_RUN_PERIOD'] = computed.get('total_run_days', '')
        if 'PDYHH_NCAST_BEGIN' in computed:
            exports['PDYHH_NCAST_BEGIN'] = computed['PDYHH_NCAST_BEGIN']
        if 'PDYHH_FCAST_BEGIN' in computed:
            exports['PDYHH_FCAST_BEGIN'] = computed['PDYHH_FCAST_BEGIN']

    # nosofs specific
    if framework == 'comf':
        exports['PREFIXNOS'] = system.get('prefix', system.get('name', ''))
        if 'time_nowcastend' in computed:
            exports['time_nowcastend'] = computed['time_nowcastend']
        if 'time_forecastend' in computed:
            exports['time_forecastend'] = computed['time_forecastend']
        if 'time_hotstart' in computed:
            exports['time_hotstart'] = computed['time_hotstart']

        # Forcing sources (uppercase for nosofs)
        forcing = data.get('forcing', {})
        atm = forcing.get('atmospheric', {})
        exports['DBASE_MET_NOW'] = (atm.get('primary') or '').upper()
        exports['DBASE_MET_FOR'] = (atm.get('forecast_source') or atm.get('primary') or '').upper()

        ocean = forcing.get('ocean', {})
        obc = ocean.get('obc', {})
        exports['DBASE_WL_NOW'] = (obc.get('wl_source') or '').upper()
        exports['DBASE_WL_FOR'] = (obc.get('wl_source') or '').upper()
        exports['DBASE_TS_NOW'] = (obc.get('ts_source') or '').upper()
        exports['DBASE_TS_FOR'] = (obc.get('ts_source') or '').upper()

        # Tidal
        tidal = forcing.get('tidal', {})
        exports['CREATE_TIDEFORCING'] = tidal.get('create_forcing', 1)

    # Resources
    resources = data.get('resources', {})
    exports['NPROCS'] = resources.get('nprocs', '')
    exports['NSCRIBES'] = resources.get('nscribes', '')

    # Include runtime environment variables
    exports.update(runtime_env)

    return exports


def format_shell_exports(exports: Dict[str, Any]) -> str:
    """Format exports as shell export statements."""
    lines = []
    for key, value in sorted(exports.items()):
        # Skip empty values
        if value is None or value == '':
            continue
        # Quote strings with spaces
        if isinstance(value, str) and (' ' in value or '"' in value):
            # Escape quotes and wrap in quotes
            escaped = value.replace('"', '\\"')
            lines.append(f'export {key}="{escaped}"')
        elif isinstance(value, bool):
            lines.append(f'export {key}={1 if value else 0}')
        elif isinstance(value, list):
            # Join lists with spaces
            lines.append(f'export {key}="{" ".join(str(v) for v in value)}"')
        else:
            lines.append(f'export {key}={value}')
    return '\n'.join(lines)


def format_json(exports: Dict[str, Any]) -> str:
    """Format exports as JSON."""
    return json.dumps(exports, indent=2, default=str)


def format_ctl_file(exports: Dict[str, Any], system_name: str) -> str:
    """
    Format exports as a nosofs-style .ctl file.

    This generates a file compatible with the .ctl files expected by
    nosofs scripts (e.g., secofs.ctl).
    """
    lines = [
        f"# {system_name}.ctl - Generated from YAML configuration",
        f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]

    # Group by category
    categories = {
        'Model': ['OCEAN_MODEL', 'GRIDFILE', 'GRIDFILE_LL', 'nvrt', 'KBm', 'np_global', 'ne_global', 'ns_global'],
        'Domain': ['MINLON', 'MAXLON', 'MINLAT', 'MAXLAT', 'IGRD_MET', 'IGRD_OBC'],
        'Physics': ['DELT_MODEL', 'NDTFAST', 'THETA_S', 'THETA_B', 'TCLINE', 'NVTRANS', 'NVSTR'],
        'Run': ['LEN_NOWCAST', 'LEN_FORECAST', 'BASE_DATE'],
        'Forcing': ['DBASE_MET_NOW', 'DBASE_MET_FOR', 'DBASE_WL_NOW', 'DBASE_WL_FOR', 'DBASE_TS_NOW', 'DBASE_TS_FOR'],
        'Tidal': ['CREATE_TIDEFORCING', 'HC_FILE_OBC', 'HC_FILE_OFS', 'HC_FILE_NWLON'],
        'Files': ['RUNTIME_CTL', 'RUNTIME_CTL_FOR', 'VGRID_CTL', 'STA_OUT_CTL', 'OBC_CTL_FILE', 'RIVER_CTL_FILE'],
        'Output': ['NSTA', 'NHIS', 'NDEFHIS', 'NQCK', 'NDEFQCK', 'NAVG', 'NFLT', 'NRST'],
    }

    for category, keys in categories.items():
        lines.append(f"# {category}")
        for key in keys:
            if key in exports and exports[key] not in (None, ''):
                value = exports[key]
                lines.append(f"export {key}={value}")
        lines.append("")

    return '\n'.join(lines)


def export_for_shell(
    config_path: Union[str, Path],
    section: Optional[str] = None,
    output_format: str = 'shell',
    framework: str = 'auto'
) -> str:
    """
    Export YAML config values for shell scripts.

    Args:
        config_path: Path to YAML config file
        section: Optional section to export (domain, model, forcing, etc.)
        output_format: Output format ('shell', 'json', or 'ctl')
        framework: Framework type ('stofs', 'comf', or 'auto')

    Returns:
        Formatted export statements, JSON, or CTL file content
    """
    config_path = Path(config_path)

    # Find config directory (for base file resolution)
    if config_path.parent.name == 'systems':
        base_dir = config_path.parent.parent
    else:
        base_dir = config_path.parent

    # Load YAML with inheritance
    data = load_yaml_with_inheritance(config_path, base_dir)

    # Get all exports
    exports = export_shell_mappings(data, framework)

    # Filter by section if specified
    if section:
        exports = filter_by_section(exports, section)

    # Format output
    if output_format == 'json':
        return format_json(exports)
    elif output_format == 'ctl':
        system_name = data.get('system', {}).get('name', 'unknown')
        return format_ctl_file(exports, system_name)
    else:
        return format_shell_exports(exports)


def filter_by_section(exports: Dict[str, Any], section: str) -> Dict[str, Any]:
    """Filter exports to only include specified section."""
    sections = {
        'domain': ['LONMIN', 'LONMAX', 'LATMIN', 'LATMAX', 'MINLON', 'MAXLON', 'MINLAT', 'MAXLAT',
                   'nvrt', 'KBm', 'np_global', 'ne_global', 'ns_global', 'GRIDFILE'],
        'model': ['OCEAN_MODEL', 'DELT_MODEL', 'NPROCS', 'NSCRIBES'],
        'run': ['LEN_NOWCAST', 'LEN_FORECAST', 'N_DAYS_MODEL_RUN_PERIOD',
                'RNDAY_NOWCAST', 'RNDAY_FORECAST',
                'PDYHH_NCAST_BEGIN', 'PDYHH_FCAST_BEGIN', 'time_nowcastend', 'time_forecastend'],
        'forcing': ['DBASE_MET_NOW', 'DBASE_MET_FOR', 'DBASE_WL_NOW', 'DBASE_WL_FOR',
                    'DBASE_TS_NOW', 'DBASE_TS_FOR', 'CREATE_TIDEFORCING'],
        'paths': ['HOMEnos', 'HOMEstofs', 'FIXofs', 'FIXstofs3d', 'DATA', 'COMOUT',
                  'COMINgfs', 'COMINhrrr', 'COMINrtofs', 'COMINnwm'],
    }

    if section not in sections:
        return exports

    section_vars = set(sections[section])
    return {k: v for k, v in exports.items() if k in section_vars}


def main():
    """Command-line interface."""
    parser = argparse.ArgumentParser(
        description='Export YAML config values as shell environment variables',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Export all variables for STOFS:
  eval $(python3 -m nos_ofs.yaml_to_env config/systems/stofs_3d_atl.yaml)

  # Export all variables for nosofs:
  eval $(python3 -m nos_ofs.yaml_to_env config/systems/secofs.yaml --framework comf)

  # Export only domain variables:
  eval $(python3 -m nos_ofs.yaml_to_env config.yaml --section domain)

  # Generate nosofs-style .ctl file:
  python3 -m nos_ofs.yaml_to_env secofs.yaml --format ctl > secofs.ctl

  # Output as JSON:
  python3 -m nos_ofs.yaml_to_env config.yaml --format json

Available sections:
  domain   - Grid bounds and dimensions
  model    - Model type and physics
  run      - Run length and time boundaries
  forcing  - Forcing data sources
  paths    - Directory paths

Frameworks:
  auto  - Auto-detect from system.framework in YAML
  stofs - STOFS (stofs_3d_atl, stofs_3d_pac)
  comf  - nosofs/COMF (secofs, leofs, cbofs, etc.)
        """
    )

    parser.add_argument(
        'config_file',
        help='Path to YAML configuration file'
    )
    parser.add_argument(
        '-s', '--section',
        choices=['domain', 'model', 'run', 'forcing', 'paths'],
        help='Export only specified section'
    )
    parser.add_argument(
        '-f', '--format',
        choices=['shell', 'json', 'ctl'],
        default='shell',
        help='Output format (default: shell)'
    )
    parser.add_argument(
        '--framework',
        choices=['auto', 'stofs', 'comf'],
        default='auto',
        help='Framework type (default: auto-detect)'
    )

    args = parser.parse_args()

    # Check config file exists
    config_path = Path(args.config_file)
    if not config_path.exists():
        print(f"Error: Config file not found: {args.config_file}", file=sys.stderr)
        sys.exit(1)

    try:
        output = export_for_shell(
            config_path,
            args.section,
            args.format,
            args.framework
        )
        print(output)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
