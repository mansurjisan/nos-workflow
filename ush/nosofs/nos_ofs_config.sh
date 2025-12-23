#!/bin/bash

################################################################################
#  Name: nos_ofs_config.sh
#  Purpose: Load configuration from YAML file for nosofs/COMF OFS systems
#           Provides unified config loading supporting both YAML and legacy .ctl files
#
#  Usage:
#     source ${USHnos}/nos_ofs_config.sh
#     # OR with explicit config path:
#     OFS_CONFIG=/path/to/config.yaml source ${USHnos}/nos_ofs_config.sh
#
#  Environment Variables:
#     OFS_CONFIG    - Path to YAML configuration file (optional)
#     FIXofs        - Fix directory containing default configs
#     PREFIXNOS     - OFS prefix (e.g., secofs, cbofs)
#
#  Created: December 2024
################################################################################

# Function to load YAML config and export as shell variables
load_nosofs_config() {
    local config_file="${1:-$OFS_CONFIG}"
    local yaml_to_env_script=""

    # Find yaml_to_env.py
    if [ -f "${HOMEnos}/../nos_ofs_project/yaml_to_env.py" ]; then
        yaml_to_env_script="${HOMEnos}/../nos_ofs_project/yaml_to_env.py"
    elif [ -f "${HOMEnos}/ush/yaml_to_env.py" ]; then
        yaml_to_env_script="${HOMEnos}/ush/yaml_to_env.py"
    elif [ -f "$(dirname "${BASH_SOURCE[0]}")/yaml_to_env.py" ]; then
        yaml_to_env_script="$(dirname "${BASH_SOURCE[0]}")/yaml_to_env.py"
    elif [ -f "${HOMEnosofs}/nos_ofs_project/yaml_to_env.py" ]; then
        yaml_to_env_script="${HOMEnosofs}/nos_ofs_project/yaml_to_env.py"
    fi

    # Check if config file exists
    if [ -z "$config_file" ] || [ ! -f "$config_file" ]; then
        echo "Warning: YAML config file not found: $config_file" >&2
        return 1
    fi

    # Check if yaml_to_env.py exists
    if [ -z "$yaml_to_env_script" ] || [ ! -f "$yaml_to_env_script" ]; then
        echo "Warning: yaml_to_env.py not found" >&2
        return 1
    fi

    # Load and eval the YAML config
    local exports
    exports=$(python3 "$yaml_to_env_script" "$config_file" --framework comf 2>/dev/null)

    if [ $? -eq 0 ] && [ -n "$exports" ]; then
        eval "$exports"
        echo "Info: Loaded YAML config from $config_file" >&2
        return 0
    else
        echo "Warning: Failed to parse YAML config: $config_file" >&2
        return 1
    fi
}

# Function to set default values if not loaded from config
set_nosofs_defaults() {
    # These defaults are for SECOFS - can be overridden by YAML or .ctl

    # Grid defaults
    export GRIDFILE=${GRIDFILE:-${PREFIXNOS}.hgrid.gr3}
    export GRIDFILE_LL=${GRIDFILE_LL:-${PREFIXNOS}.hgrid.ll}
    export VGRID_CTL=${VGRID_CTL:-${PREFIXNOS}.vgrid.in}
    export STA_OUT_CTL=${STA_OUT_CTL:-${PREFIXNOS}.station.in}

    # Domain bounds (SECOFS defaults)
    export MINLON=${MINLON:--88.0}
    export MAXLON=${MAXLON:--63.0}
    export MINLAT=${MINLAT:-17.0}
    export MAXLAT=${MAXLAT:-40.0}

    # Grid dimensions (SECOFS defaults)
    export np_global=${np_global:-1684786}
    export ne_global=${ne_global:-3322329}
    export ns_global=${ns_global:-5007180}
    export nvrt=${nvrt:-63}
    export KBm=${KBm:-$nvrt}

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

    # Dual met sources
    export DBASE_MET_NOW2=${DBASE_MET_NOW2:-HRRR}
    export DBASE_MET_FOR2=${DBASE_MET_FOR2:-HRRR}

    # Run length
    export LEN_FORECAST=${LEN_FORECAST:-48}
    export LEN_NOWCAST=${LEN_NOWCAST:-6}

    # Tidal forcing
    export CREATE_TIDEFORCING=${CREATE_TIDEFORCING:-1}

    # Control files
    export RIVER_CTL_FILE=${RIVER_CTL_FILE:-${PREFIXNOS}.river.ctl}
    export OBC_CTL_FILE=${OBC_CTL_FILE:-${PREFIXNOS}.obc.ctl}
    export RUNTIME_CTL=${RUNTIME_CTL:-${PREFIXNOS}.param.nml}
    export RUNTIME_MET_CTL=${RUNTIME_MET_CTL:-${PREFIXNOS}.sflux_inputs.txt}

    # Resources
    export TOTAL_TASKS=${TOTAL_TASKS:-1200}

    # Output intervals (in seconds)
    export NSTA=${NSTA:-360}
    export NHIS=${NHIS:-3600}
    export NRST=${NRST:-21600}
    export NAVG=${NAVG:-3600}
    export NFLT=${NFLT:-3600}
    export NQCK=${NQCK:-3600}
    export NDEFHIS=${NDEFHIS:-86400}
    export NDEFQCK=${NDEFQCK:-86400}
}

# Main execution - attempt to load config
# Priority: 1. OFS_CONFIG env var, 2. FIXofs YAML, 3. FIXofs .ctl, 4. defaults

config_loaded=0

# Try loading from OFS_CONFIG environment variable (YAML)
if [ -n "$OFS_CONFIG" ] && [ -f "$OFS_CONFIG" ]; then
    if load_nosofs_config "$OFS_CONFIG"; then
        config_loaded=1
    fi
fi

# Try loading from FIXofs directory (YAML)
if [ $config_loaded -eq 0 ] && [ -n "$FIXofs" ] && [ -n "$PREFIXNOS" ]; then
    yaml_config="${FIXofs}/${PREFIXNOS}.yaml"
    if [ -f "$yaml_config" ]; then
        if load_nosofs_config "$yaml_config"; then
            config_loaded=1
        fi
    fi
fi

# Try loading from central config directory (YAML)
if [ $config_loaded -eq 0 ] && [ -n "$PREFIXNOS" ]; then
    central_config="${HOMEnosofs}/nos_ofs_project/config/systems/${PREFIXNOS}.yaml"
    if [ -f "$central_config" ]; then
        if load_nosofs_config "$central_config"; then
            config_loaded=1
        fi
    fi
fi

# Note: Legacy .ctl file loading is handled by exnos_ofs_prep.sh
# This script adds YAML support as an alternative

# Always set defaults for any missing values
set_nosofs_defaults

# Export config_loaded status for downstream scripts
export NOSOFS_CONFIG_LOADED=$config_loaded
