#!/bin/bash
###############################################################################
# stofs_3d_atl_config.sh
#
# STOFS-3D-ATL Configuration Loader
#
# This script loads configuration from YAML files and exports them as
# shell environment variables. It provides backward compatibility with
# legacy hardcoded values while enabling centralized configuration.
#
# Usage:
#   source $USHstofs3d/stofs_3d_atl_config.sh
#
# Environment Variables:
#   STOFS_CONFIG - Path to YAML config file (optional)
#   FIXstofs3d   - Path to FIX directory containing stofs_3d_atl.yaml
#   HOMEstofs    - STOFS installation home directory
#
# After sourcing, the following variables will be set:
#   LONMIN, LONMAX, LATMIN, LATMAX - Domain bounds
#   N_DAYS_MODEL_RUN_PERIOD        - Model run length (days)
#   nvrt, np_global, ne_global     - Grid dimensions
#   DELT_MODEL                     - Model timestep
#   And many more from stofs_3d_atl.yaml...
#
###############################################################################

set -u

# Track if config was loaded
export STOFS_CONFIG_LOADED=0

# Determine paths
STOFS_CONFIG_DIR="${HOMEstofs:-/lfs/h1/nos/nosofs/noscrub/STOFS-Oper}/nos_ofs/parm/systems"
STOFS_USH_DIR="${USHstofs3d:-${HOMEstofs:-/lfs/h1/nos/nosofs/noscrub/STOFS-Oper}/nos_ofs/ush/stofs_3d_atl}"

# Find yaml_to_env.py
yaml_to_env_script=""
for search_path in \
    "${HOMEstofs:-}/nos_ofs/ush/python/nos_ofs/utils/yaml_to_env.py" \
    "${USHstofs3d:-}/python/nos_ofs/utils/yaml_to_env.py" \
    "${STOFS_USH_DIR}/../python/nos_ofs/utils/yaml_to_env.py" \
    "/lfs/h1/nos/nosofs/noscrub/STOFS-Oper/nos_ofs/ush/python/nos_ofs/utils/yaml_to_env.py"
do
    if [ -f "$search_path" ]; then
        yaml_to_env_script="$search_path"
        break
    fi
done

###############################################################################
# load_stofs_config - Load STOFS configuration from YAML file
#
# Arguments:
#   $1 - Path to YAML config file (optional, uses defaults if not provided)
#
# Returns:
#   0 - Success
#   1 - Failed to load config
###############################################################################
load_stofs_config() {
    local config_file="${1:-}"

    # If no config file provided, search for one
    if [ -z "$config_file" ] || [ ! -f "$config_file" ]; then
        # Try STOFS_CONFIG environment variable first
        if [ -n "${STOFS_CONFIG:-}" ] && [ -f "${STOFS_CONFIG}" ]; then
            config_file="${STOFS_CONFIG}"
        # Then check FIX directory
        elif [ -f "${FIXstofs3d:-}/stofs_3d_atl.yaml" ]; then
            config_file="${FIXstofs3d}/stofs_3d_atl.yaml"
        # Then check parm directory
        elif [ -f "${STOFS_CONFIG_DIR}/stofs_3d_atl.yaml" ]; then
            config_file="${STOFS_CONFIG_DIR}/stofs_3d_atl.yaml"
        else
            echo "WARNING: No YAML config file found, using defaults" >&2
            _load_stofs_defaults
            return 0
        fi
    fi

    # Check if yaml_to_env.py is available
    if [ -z "$yaml_to_env_script" ]; then
        echo "WARNING: yaml_to_env.py not found, using defaults" >&2
        _load_stofs_defaults
        return 0
    fi

    # Check if Python is available
    if ! command -v python3 &> /dev/null; then
        echo "WARNING: python3 not found, using defaults" >&2
        _load_stofs_defaults
        return 0
    fi

    # Load configuration from YAML
    echo "Loading STOFS config from: $config_file"
    local exports
    exports=$(python3 "$yaml_to_env_script" "$config_file" --framework stofs 2>/dev/null)

    if [ $? -eq 0 ] && [ -n "$exports" ]; then
        eval "$exports"
        export STOFS_CONFIG_LOADED=1
        export STOFS_CONFIG_FILE="$config_file"
        echo "STOFS configuration loaded successfully"
        return 0
    else
        echo "WARNING: Failed to parse YAML config, using defaults" >&2
        _load_stofs_defaults
        return 0
    fi
}

###############################################################################
# _load_stofs_defaults - Load default STOFS-3D-ATL values
#
# These values match the hardcoded values in the original IT-STOFS scripts
###############################################################################
_load_stofs_defaults() {
    echo "Loading STOFS-3D-ATL default values"

    # Domain bounds (from stofs_3d_atl_create_surface_forcing_gfs.sh)
    export LONMIN=-98.5035
    export LONMAX=-52.4867
    export LATMIN=7.347
    export LATMAX=52.5904

    # Model configuration
    export N_DAYS_MODEL_RUN_PERIOD=5.5
    export DELT_MODEL=150.0
    export OCEAN_MODEL=SCHISM

    # Grid dimensions
    export nvrt=51
    export np_global=1813443
    export ne_global=3564104

    # River sources (from stofs_3d_atl_create_river_forcing_nwm.sh)
    export N_RIVER_SOURCES=7690

    # Run configuration
    export LEN_NOWCAST=6
    export LEN_FORECAST=120

    # Forcing sources
    export ATMOS_PRIMARY=gfs
    export ATMOS_FALLBACK=hrrr
    export OCEAN_SOURCE=rtofs
    export RIVER_SOURCE=nwm

    export STOFS_CONFIG_LOADED=1
    export STOFS_CONFIG_FILE="defaults"
}

###############################################################################
# get_stofs_config - Retrieve a specific config value
#
# Arguments:
#   $1 - Variable name to retrieve
#   $2 - Default value if not set (optional)
#
# Output:
#   Prints the variable value to stdout
###############################################################################
get_stofs_config() {
    local var_name="${1:-}"
    local default_value="${2:-}"

    if [ -z "$var_name" ]; then
        echo "$default_value"
        return
    fi

    # Use indirect variable reference
    local value="${!var_name:-$default_value}"
    echo "$value"
}

###############################################################################
# export_stofs_section - Export a specific section of the config
#
# Arguments:
#   $1 - Section name (domain, model, forcing, etc.)
###############################################################################
export_stofs_section() {
    local section="${1:-}"
    local config_file="${STOFS_CONFIG_FILE:-}"

    if [ -z "$section" ] || [ -z "$config_file" ] || [ ! -f "$config_file" ]; then
        echo "WARNING: Cannot export section '$section' - no config file" >&2
        return 1
    fi

    if [ -z "$yaml_to_env_script" ]; then
        echo "WARNING: yaml_to_env.py not found" >&2
        return 1
    fi

    local exports
    exports=$(python3 "$yaml_to_env_script" "$config_file" --framework stofs --section "$section" 2>/dev/null)

    if [ $? -eq 0 ] && [ -n "$exports" ]; then
        eval "$exports"
        return 0
    else
        echo "WARNING: Failed to export section '$section'" >&2
        return 1
    fi
}

###############################################################################
# Auto-load configuration if STOFS_CONFIG is set
###############################################################################
if [ "${STOFS_CONFIG_LOADED:-0}" -eq 0 ]; then
    if [ -n "${STOFS_CONFIG:-}" ] && [ -f "${STOFS_CONFIG}" ]; then
        load_stofs_config "${STOFS_CONFIG}"
    fi
fi

echo "STOFS-3D-ATL configuration module loaded"
echo "  Use: load_stofs_config [config_file] to load configuration"
echo "  Use: get_stofs_config VAR_NAME [default] to get a value"
