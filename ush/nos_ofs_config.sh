#!/bin/bash
################################################################################
#  Name: nos_ofs_config.sh
#  Purpose: Unified configuration loader for all NOS OFS systems
#           Supports both STOFS and COMF/nosofs frameworks via YAML config
#
#  Usage:
#     source ${USHnos}/nos_ofs_config.sh
#     load_ofs_config "/path/to/config.yaml" "stofs"   # explicit framework
#     load_ofs_config "/path/to/config.yaml"            # auto-detect framework
#
#  Functions:
#     load_ofs_config <config_file> [framework]  - Load config from YAML
#     get_ofs_config <var_name> [default]         - Get a config value
#     export_ofs_section <section>                - Export a YAML section
#     load_nosofs_config <config_file>            - Backward compat (COMF)
#     load_stofs_config <config_file>             - Backward compat (STOFS)
#
#  Environment Variables (set after loading):
#     OFS_CONFIG_LOADED  - 1 if config loaded successfully
#     OFS_CONFIG_SOURCE  - "yaml" or "defaults"
#     OFS_CONFIG_FILE    - Path to loaded config file
#
################################################################################

# Note: Do NOT use 'set -u' here - this script is sourced into other scripts
# and would cause unbound variable errors throughout the calling environment

export OFS_CONFIG_LOADED=${OFS_CONFIG_LOADED:-0}

# Find yaml_to_env.py
_ofs_yaml_to_env=""
for _search_path in \
    "${HOMEnos:-}/ush/python/nos_ofs/utils/yaml_to_env.py" \
    "${HOMEstofs:-}/ush/python/nos_ofs/utils/yaml_to_env.py" \
    "$(dirname "${BASH_SOURCE[0]}")/python/nos_ofs/utils/yaml_to_env.py"
do
    if [ -f "$_search_path" ]; then
        _ofs_yaml_to_env="$_search_path"
        break
    fi
done

################################################################################
# load_ofs_config - Load configuration from YAML file
#
# Arguments:
#   $1 - Path to YAML config file
#   $2 - Framework: "stofs", "comf", or "auto" (default: auto)
#
# Returns:
#   0 - Success
#   1 - Failed to load config
################################################################################
load_ofs_config() {
    local config_file="${1:-}"
    local framework="${2:-auto}"

    # Auto-detect framework from OFS name if not specified
    if [ "$framework" = "auto" ]; then
        case "${OFS:-}" in
            stofs_3d_atl|stofs_3d_pac) framework="stofs" ;;
            *)                         framework="comf" ;;
        esac
    fi

    # Search for config file if not provided or not found
    if [ -z "$config_file" ] || [ ! -f "$config_file" ]; then
        config_file=$(_find_config_file "$framework")
    fi

    if [ -z "$config_file" ] || [ ! -f "$config_file" ]; then
        echo "WARNING: No YAML config file found, using ${framework} defaults" >&2
        _load_defaults "$framework"
        return 0
    fi

    # Check if yaml_to_env.py is available
    if [ -z "$_ofs_yaml_to_env" ]; then
        echo "WARNING: yaml_to_env.py not found, using ${framework} defaults" >&2
        _load_defaults "$framework"
        return 0
    fi

    # Check if Python is available
    if ! command -v python3 &> /dev/null; then
        echo "WARNING: python3 not found, using ${framework} defaults" >&2
        _load_defaults "$framework"
        return 0
    fi

    # Load configuration from YAML
    echo "Loading OFS config from: $config_file (framework: $framework)"
    local exports
    local _yaml_err
    _yaml_err=$(python3 "$_ofs_yaml_to_env" "$config_file" --framework "$framework" 2>&1 1>/dev/null) || true
    exports=$(python3 "$_ofs_yaml_to_env" "$config_file" --framework "$framework" 2>/dev/null) || true

    if [ -n "$exports" ]; then
        eval "$exports"
        export OFS_CONFIG_LOADED=1
        export OFS_CONFIG_SOURCE="yaml"
        export OFS_CONFIG_FILE="$config_file"
        echo "OFS configuration loaded successfully (source: yaml)"

        # Apply framework-specific defaults for any values not set by YAML
        _load_defaults "$framework"
        return 0
    else
        echo "WARNING: Failed to parse YAML config, using ${framework} defaults" >&2
        if [ -n "${_yaml_err:-}" ]; then
            echo "YAML parse error: ${_yaml_err}" >&2
        fi
        _load_defaults "$framework"
        return 0
    fi
}

################################################################################
# get_ofs_config - Retrieve a specific config value
#
# Arguments:
#   $1 - Variable name
#   $2 - Default value if not set (optional)
################################################################################
get_ofs_config() {
    local var_name="${1:-}"
    local default_value="${2:-}"

    if [ -z "$var_name" ]; then
        echo "$default_value"
        return
    fi

    local value="${!var_name:-$default_value}"
    echo "$value"
}

################################################################################
# export_ofs_section - Export a specific YAML section
#
# Arguments:
#   $1 - Section name (domain, model, forcing, etc.)
################################################################################
export_ofs_section() {
    local section="${1:-}"
    local config_file="${OFS_CONFIG_FILE:-}"

    if [ -z "$section" ] || [ -z "$config_file" ] || [ ! -f "$config_file" ]; then
        echo "WARNING: Cannot export section '$section' - no config file" >&2
        return 1
    fi

    if [ -z "$_ofs_yaml_to_env" ]; then
        echo "WARNING: yaml_to_env.py not found" >&2
        return 1
    fi

    local exports
    exports=$(python3 "$_ofs_yaml_to_env" "$config_file" --section "$section" 2>/dev/null)

    if [ $? -eq 0 ] && [ -n "$exports" ]; then
        eval "$exports"
        return 0
    else
        echo "WARNING: Failed to export section '$section'" >&2
        return 1
    fi
}

################################################################################
# Backward-compatible wrappers
################################################################################
load_nosofs_config() {
    load_ofs_config "${1:-}" "comf"
}

load_stofs_config() {
    load_ofs_config "${1:-}" "stofs"
}

################################################################################
# _find_config_file - Search standard locations for a config file
################################################################################
_find_config_file() {
    local framework="${1:-comf}"

    # Try OFS_CONFIG environment variable
    if [ -n "${OFS_CONFIG:-}" ] && [ -f "${OFS_CONFIG}" ]; then
        echo "${OFS_CONFIG}"
        return
    fi

    # Try parm/systems directory
    local parm_config="${PARMnos:-}/systems/${OFS:-}.yaml"
    if [ -f "$parm_config" ]; then
        echo "$parm_config"
        return
    fi

    # Try FIX directory
    if [ "$framework" = "stofs" ]; then
        local fix_config="${FIXstofs3d:-}/${OFS:-}.yaml"
    else
        local fix_config="${FIXofs:-}/${PREFIXNOS:-${OFS:-}}.yaml"
    fi
    if [ -f "$fix_config" ]; then
        echo "$fix_config"
        return
    fi

    echo ""
}

################################################################################
# _load_defaults - Load framework-specific default values
#
# These fill in any variables not already set by YAML or environment.
################################################################################
_load_defaults() {
    local framework="${1:-comf}"

    case "$framework" in
        stofs)  _load_stofs_defaults ;;
        *)      _load_comf_defaults ;;
    esac
}

################################################################################
# _load_stofs_defaults - STOFS-3D default values
################################################################################
_load_stofs_defaults() {
    # Domain bounds
    export LONMIN=${LONMIN:--98.5035}
    export LONMAX=${LONMAX:--52.4867}
    export LATMIN=${LATMIN:-7.347}
    export LATMAX=${LATMAX:-52.5904}

    # Model configuration
    export N_DAYS_MODEL_RUN_PERIOD=${N_DAYS_MODEL_RUN_PERIOD:-5.5}
    export DELT_MODEL=${DELT_MODEL:-150.0}
    export OCEAN_MODEL=${OCEAN_MODEL:-SCHISM}

    # Grid dimensions
    export nvrt=${nvrt:-51}
    export np_global=${np_global:-1813443}
    export ne_global=${ne_global:-3564104}

    # River sources
    export N_RIVER_SOURCES=${N_RIVER_SOURCES:-7690}

    # Run configuration
    export LEN_NOWCAST=${LEN_NOWCAST:-6}
    export LEN_FORECAST=${LEN_FORECAST:-120}

    # Forcing sources
    export ATMOS_PRIMARY=${ATMOS_PRIMARY:-gfs}
    export ATMOS_FALLBACK=${ATMOS_FALLBACK:-hrrr}
    export OCEAN_SOURCE=${OCEAN_SOURCE:-rtofs}
    export RIVER_SOURCE=${RIVER_SOURCE:-nwm}
}

################################################################################
# _load_comf_defaults - COMF/nosofs default values
################################################################################
_load_comf_defaults() {
    # Grid defaults
    export GRIDFILE=${GRIDFILE:-${PREFIXNOS:-${OFS:-}}.hgrid.gr3}
    export GRIDFILE_LL=${GRIDFILE_LL:-${PREFIXNOS:-${OFS:-}}.hgrid.ll}
    export VGRID_CTL=${VGRID_CTL:-${PREFIXNOS:-${OFS:-}}.vgrid.in}
    export STA_OUT_CTL=${STA_OUT_CTL:-${PREFIXNOS:-${OFS:-}}.station.in}

    # Domain bounds
    export MINLON=${MINLON:--88.0}
    export MAXLON=${MAXLON:--63.0}
    export MINLAT=${MINLAT:-17.0}
    export MAXLAT=${MAXLAT:-40.0}

    # Grid dimensions
    export np_global=${np_global:-1684786}
    export ne_global=${ne_global:-3322329}
    export ns_global=${ns_global:-5007180}
    export nvrt=${nvrt:-63}
    export KBm=${KBm:-${nvrt:-63}}

    # Model settings
    export OCEAN_MODEL=${OCEAN_MODEL:-SCHISM}
    export DELT_MODEL=${DELT_MODEL:-120.0}
    export NDTFAST=${NDTFAST:-20}

    # Forcing data sources
    export DBASE_MET_NOW=${DBASE_MET_NOW:-GFS}
    export DBASE_MET_FOR=${DBASE_MET_FOR:-GFS}
    export DBASE_WL_NOW=${DBASE_WL_NOW:-RTOFS}
    export DBASE_WL_FOR=${DBASE_WL_FOR:-RTOFS}
    export DBASE_TS_NOW=${DBASE_TS_NOW:-RTOFS}
    export DBASE_TS_FOR=${DBASE_TS_FOR:-RTOFS}
    export MET_NUM=${MET_NUM:-2}
    export DBASE_MET_NOW2=${DBASE_MET_NOW2:-HRRR}
    export DBASE_MET_FOR2=${DBASE_MET_FOR2:-HRRR}

    # Run length
    export LEN_FORECAST=${LEN_FORECAST:-48}
    export LEN_NOWCAST=${LEN_NOWCAST:-6}

    # Tidal forcing
    export CREATE_TIDEFORCING=${CREATE_TIDEFORCING:-1}

    # Control files
    export RIVER_CTL_FILE=${RIVER_CTL_FILE:-${PREFIXNOS:-${OFS:-}}.river.ctl}
    export OBC_CTL_FILE=${OBC_CTL_FILE:-${PREFIXNOS:-${OFS:-}}.obc.ctl}
    export RUNTIME_CTL=${RUNTIME_CTL:-${PREFIXNOS:-${OFS:-}}.param.nml}
    export RUNTIME_MET_CTL=${RUNTIME_MET_CTL:-${PREFIXNOS:-${OFS:-}}.sflux_inputs.txt}

    # Resources
    export TOTAL_TASKS=${TOTAL_TASKS:-1200}

    # Output intervals (seconds)
    export NSTA=${NSTA:-360}
    export NHIS=${NHIS:-3600}
    export NRST=${NRST:-21600}
    export NAVG=${NAVG:-3600}
    export NFLT=${NFLT:-3600}
    export NQCK=${NQCK:-3600}
    export NDEFHIS=${NDEFHIS:-86400}
    export NDEFQCK=${NDEFQCK:-86400}
}

################################################################################
# Auto-load if OFS_CONFIG is set and config not yet loaded
################################################################################
if [ "${OFS_CONFIG_LOADED:-0}" -eq 0 ]; then
    if [ -n "${OFS_CONFIG:-}" ] && [ -f "${OFS_CONFIG}" ]; then
        load_ofs_config "${OFS_CONFIG}"
    fi
fi
