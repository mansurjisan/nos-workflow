#!/bin/bash

##############################################################################
#  Name: exnos_ofs_prep_unified.sh                                           #
#                                                                            #
#  Unified preprocessing script for COMF-based OFS systems (SECOFS, CREOFS,  #
#  and traditional nosofs systems) using Python + YAML configuration.        #
#                                                                            #
#  Supports both YAML and legacy .ctl configuration:                         #
#  - If OFS_CONFIG is set and points to a YAML file, use YAML                #
#  - Otherwise, fall back to .ctl file in FIXofs                             #
#                                                                            #
#  Usage:                                                                    #
#    export OFS=secofs                                                       #
#    export OFS_CONFIG=/path/to/secofs.yaml  # Optional                      #
#    ./exnos_ofs_prep_unified.sh                                             #
#                                                                            #
##############################################################################

set -x

export PS4=' $SECONDS + '
date

fn_this_script="exnos_ofs_prep_unified.sh"

msg="Starting script: NOS OFS PREP (Unified) for ${OFS}"
echo "$msg"
postmsg "$jlogfile" "$msg"

##############################################################################
# CONFIGURATION LOADING
##############################################################################

CONFIG_SOURCE="none"

# Find Python package location
for search_path in \
    "${HOMEnos}/ush/python" \
    "${HOMEnos}/nos_ofs/ush/python" \
    "$(dirname $0)/../../ush/python"
do
    if [ -d "$search_path/nos_ofs" ]; then
        export PYnos_ofs="$search_path"
        break
    fi
done

# Option 1: Load from OFS_CONFIG environment variable (YAML)
if [ -n "$OFS_CONFIG" ] && [ -f "$OFS_CONFIG" ]; then
    echo "Attempting to load YAML config from OFS_CONFIG: $OFS_CONFIG"

    if [ -n "$PYnos_ofs" ]; then
        export PYTHONPATH="${PYnos_ofs}:${PYTHONPATH}"

        # Export YAML to shell environment (COMF-style variables)
        yaml_exports=$(python3 -m nos_ofs.cli export-env --config "$OFS_CONFIG" --framework comf 2>/dev/null)

        if [ $? -eq 0 ] && [ -n "$yaml_exports" ]; then
            eval "$yaml_exports"
            CONFIG_SOURCE="yaml"
            echo "Configuration loaded from YAML: $OFS_CONFIG"
        else
            echo "WARNING: Failed to parse YAML config"
        fi
    else
        echo "WARNING: Python package not found, cannot load YAML"
    fi
fi

# Option 2: Try to find YAML config in standard locations
if [ "$CONFIG_SOURCE" = "none" ] && [ -n "$PYnos_ofs" ]; then
    for yaml_path in \
        "${HOMEnos}/parm/systems/${OFS}.yaml" \
        "${FIXofs}/${OFS}.yaml"
    do
        if [ -f "$yaml_path" ]; then
            echo "Found YAML config: $yaml_path"
            export PYTHONPATH="${PYnos_ofs}:${PYTHONPATH}"

            yaml_exports=$(python3 -m nos_ofs.cli export-env --config "$yaml_path" --framework comf 2>/dev/null)

            if [ $? -eq 0 ] && [ -n "$yaml_exports" ]; then
                eval "$yaml_exports"
                export OFS_CONFIG="$yaml_path"
                CONFIG_SOURCE="yaml"
                echo "Configuration loaded from YAML: $yaml_path"
                break
            fi
        fi
    done
fi

# Option 3: Fall back to legacy .ctl file
if [ "$CONFIG_SOURCE" = "none" ]; then
    if [ -s ${FIXofs}/${PREFIXNOS}.ctl ]; then
        . ${FIXofs}/${PREFIXNOS}.ctl
        CONFIG_SOURCE="ctl"
        echo "Configuration loaded from .ctl file: ${FIXofs}/${PREFIXNOS}.ctl"
    else
        echo "ERROR: No configuration found (YAML or .ctl)"
        exit 1
    fi
fi

echo "Configuration source: $CONFIG_SOURCE"
echo "Key variables:"
echo "  OCEAN_MODEL=$OCEAN_MODEL"
echo "  MINLON=$MINLON, MAXLON=$MAXLON"
echo "  MINLAT=$MINLAT, MAXLAT=$MAXLAT"
echo "  DBASE_MET_NOW=$DBASE_MET_NOW"

##############################################################################
# CREATE WORKING DIRECTORIES
##############################################################################

mkdir -p ${DATA}
cd $DATA

mkdir -p ${COMOUT}

##############################################################################
# RUN PREPROCESSING STEPS BASED ON MODEL TYPE
##############################################################################

if [ ${OCEAN_MODEL} == "SCHISM" -o ${OCEAN_MODEL} == "schism" ]; then
    echo "Running SCHISM preprocessing for ${OFS}"

    # Create control file from YAML config
    if [ "$CONFIG_SOURCE" = "yaml" ]; then
        echo "Generating runtime control from YAML"
        # The variables are already exported, scripts will use them
    fi

    # 1. Meteorological forcing
    file_log=log_create_forcing_met.${cycle}.log
    export pgm="${USHnos}/nos_ofs_create_forcing_met.sh"

    ${USHnos}/nos_ofs_create_forcing_met.sh >> ${file_log} 2>&1
    export err=$?

    if [ $err -ne 0 ]; then
        msg=" Execution of $pgm did not complete normally - WARNING"
        postmsg "$msg"
    else
        msg=" Execution of $pgm completed normally"
        postmsg "$msg"
    fi
    echo $msg

    # 2. River forcing
    file_log=log_create_forcing_river.${cycle}.log
    export pgm="${USHnos}/nos_ofs_create_forcing_river.sh"

    ${USHnos}/nos_ofs_create_forcing_river.sh >> ${file_log} 2>&1
    export err=$?

    if [ $err -ne 0 ]; then
        msg=" Execution of $pgm did not complete normally - WARNING"
        postmsg "$msg"
    else
        msg=" Execution of $pgm completed normally"
        postmsg "$msg"
    fi
    echo $msg

    # 3. Open boundary forcing
    file_log=log_create_forcing_obc.${cycle}.log
    export pgm="${USHnos}/nos_ofs_create_forcing_obc.sh"

    ${USHnos}/nos_ofs_create_forcing_obc.sh >> ${file_log} 2>&1
    export err=$?

    if [ $err -ne 0 ]; then
        msg=" Execution of $pgm did not complete normally - WARNING"
        postmsg "$msg"
    else
        msg=" Execution of $pgm completed normally"
        postmsg "$msg"
    fi
    echo $msg

    # 4. Nudging forcing (if enabled)
    if [ "${CREATE_NUDGING:-0}" -eq 1 ]; then
        file_log=log_create_forcing_nudg.${cycle}.log
        export pgm="${USHnos}/nos_ofs_create_forcing_nudg.sh"

        ${USHnos}/nos_ofs_create_forcing_nudg.sh >> ${file_log} 2>&1
        export err=$?

        if [ $err -ne 0 ]; then
            msg=" Execution of $pgm did not complete normally - WARNING"
            postmsg "$msg"
        else
            msg=" Execution of $pgm completed normally"
            postmsg "$msg"
        fi
        echo $msg
    fi

elif [ ${OCEAN_MODEL} == "ROMS" -o ${OCEAN_MODEL} == "roms" ]; then
    echo "Running ROMS preprocessing for ${OFS}"

    # ROMS-specific preprocessing
    ${USHnos}/nos_ofs_create_forcing_met.sh
    ${USHnos}/nos_ofs_create_forcing_river.sh
    ${USHnos}/nos_ofs_create_forcing_obc.sh

elif [ ${OCEAN_MODEL} == "FVCOM" -o ${OCEAN_MODEL} == "fvcom" ]; then
    echo "Running FVCOM preprocessing for ${OFS}"

    # FVCOM-specific preprocessing
    ${USHnos}/nos_ofs_create_forcing_met.sh
    ${USHnos}/nos_ofs_create_forcing_river.sh
    ${USHnos}/nos_ofs_create_forcing_obc.sh

else
    echo "ERROR: Unknown OCEAN_MODEL: $OCEAN_MODEL"
    exit 1
fi

##############################################################################
# COMPLETION
##############################################################################

msg=" Finished NOS OFS PREP (Unified) for ${OFS} SUCCESSFULLY "
postmsg "$msg"

echo
echo " Finished running - ${fn_this_script} at " `date`
echo
