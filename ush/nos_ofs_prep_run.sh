#!/bin/bash
################################################################################
#  Name: nos_ofs_prep_run.sh
#  Purpose: Unified prep functions for all NOS OFS systems
#           Provides a common 7-step interface for both STOFS and COMF frameworks
#
#  Usage:
#     source ${USHnos}/nos_ofs_prep_run.sh
#     stage_static_files
#     create_model_config
#     create_forcing_atmospheric
#     create_forcing_river
#     create_forcing_obc
#     create_forcing_nudging
#     prepare_initial_condition
#
#  Functions:
#     stage_static_files          - Link/copy grid, control files, static inputs
#     create_model_config         - Generate param.nml, bctides.in, runtime config
#     create_forcing_atmospheric  - GFS/HRRR (STOFS) or NAM/GFS/RTMA (COMF)
#     create_forcing_river        - NWM + St. Lawrence (STOFS) or NWM/USGS (COMF)
#     create_forcing_obc          - RTOFS/HYCOM open boundary conditions
#     create_forcing_nudging      - T/S interior nudging (optional)
#     prepare_initial_condition   - Restart/hotstart file search
#
#  Environment Requirements:
#     OFS_FRAMEWORK  - "stofs" or "comf"
#     DATA           - Working directory
#     COMOUT         - Output directory
#     Plus framework-specific variables (FIXstofs3d, COMOUTrerun, USHnos, etc.)
#
################################################################################

################################################################################
# stage_static_files - Link/copy grid, control files, static inputs to $DATA
################################################################################
stage_static_files() {
    echo "=== stage_static_files (framework: ${OFS_FRAMEWORK}) ==="

    case "${OFS_FRAMEWORK}" in
        stofs) _stofs_stage_static_files ;;
        comf)  _comf_stage_static_files ;;
        *)     echo "ERROR: Unknown framework: ${OFS_FRAMEWORK}"; return 1 ;;
    esac
}

################################################################################
# create_model_config - Generate param.nml, bctides.in, runtime control files
################################################################################
create_model_config() {
    echo "=== create_model_config (framework: ${OFS_FRAMEWORK}) ==="

    case "${OFS_FRAMEWORK}" in
        stofs) _stofs_create_model_config ;;
        comf)  _comf_create_model_config ;;
        *)     echo "ERROR: Unknown framework: ${OFS_FRAMEWORK}"; return 1 ;;
    esac
}

################################################################################
# create_forcing_atmospheric - GFS/HRRR (STOFS) or NAM/GFS/RTMA (COMF)
################################################################################
create_forcing_atmospheric() {
    echo "=== create_forcing_atmospheric (framework: ${OFS_FRAMEWORK}) ==="

    case "${OFS_FRAMEWORK}" in
        stofs) _stofs_create_forcing_atmospheric ;;
        comf)  _comf_create_forcing_atmospheric ;;
        *)     echo "ERROR: Unknown framework: ${OFS_FRAMEWORK}"; return 1 ;;
    esac
}

################################################################################
# create_forcing_river - NWM + St. Lawrence (STOFS) or NWM/USGS (COMF)
################################################################################
create_forcing_river() {
    echo "=== create_forcing_river (framework: ${OFS_FRAMEWORK}) ==="

    case "${OFS_FRAMEWORK}" in
        stofs) _stofs_create_forcing_river ;;
        comf)  _comf_create_forcing_river ;;
        *)     echo "ERROR: Unknown framework: ${OFS_FRAMEWORK}"; return 1 ;;
    esac
}

################################################################################
# create_forcing_obc - RTOFS/HYCOM open boundary conditions
################################################################################
create_forcing_obc() {
    echo "=== create_forcing_obc (framework: ${OFS_FRAMEWORK}) ==="

    case "${OFS_FRAMEWORK}" in
        stofs) _stofs_create_forcing_obc ;;
        comf)  _comf_create_forcing_obc ;;
        *)     echo "ERROR: Unknown framework: ${OFS_FRAMEWORK}"; return 1 ;;
    esac
}

################################################################################
# create_forcing_nudging - T/S interior nudging (optional, not all OFS use it)
################################################################################
create_forcing_nudging() {
    echo "=== create_forcing_nudging (framework: ${OFS_FRAMEWORK}) ==="

    case "${OFS_FRAMEWORK}" in
        stofs) _stofs_create_forcing_nudging ;;
        comf)  _comf_create_forcing_nudging ;;
        *)     echo "ERROR: Unknown framework: ${OFS_FRAMEWORK}"; return 1 ;;
    esac
}

################################################################################
# prepare_initial_condition - Restart/hotstart file search and staging
################################################################################
prepare_initial_condition() {
    echo "=== prepare_initial_condition (framework: ${OFS_FRAMEWORK}) ==="

    case "${OFS_FRAMEWORK}" in
        stofs) _stofs_prepare_initial_condition ;;
        comf)  _comf_prepare_initial_condition ;;
        *)     echo "ERROR: Unknown framework: ${OFS_FRAMEWORK}"; return 1 ;;
    esac
}


################################################################################
#
#  STOFS INTERNAL FUNCTIONS
#
################################################################################

_stofs_stage_static_files() {
    echo "Linking STOFS static files from ${FIXstofs3d}..."

    cd $DATA

    ln -sf $FIXstofs3d/${RUN}_windrot_geo2proj.gr3  windrot_geo2proj.gr3
    ln -sf $FIXstofs3d/${RUN}_watertype.gr3  watertype.gr3
    ln -sf $FIXstofs3d/${RUN}_vgrid.in  vgrid.in
    ln -sf $FIXstofs3d/${RUN}_tvd.prop  tvd.prop
    ln -sf $FIXstofs3d/${RUN}_tem_nudge.gr3  TEM_nudge.gr3
    ln -sf $FIXstofs3d/${RUN}_station.in  station.in
    ln -sf $FIXstofs3d/${RUN}_river_source_sink.in  source_sink.in
    ln -sf $FIXstofs3d/${RUN}_shapiro.gr3  shapiro.gr3
    ln -sf $FIXstofs3d/${RUN}_sal_nudge.gr3  SAL_nudge.gr3
    ln -sf $FIXstofs3d/${RUN}_param.nml_6globaloutput param.nml_template
    ln -sf $FIXstofs3d/${RUN}_river_msource.th  msource.th
    ln -sf $FIXstofs3d/${RUN}_hgrid.ll  hgrid.ll
    ln -sf $FIXstofs3d/${RUN}_hgrid.gr3  hgrid.gr3
    ln -sf $FIXstofs3d/${RUN}_estuary.gr3  estuary.gr3
    ln -sf $FIXstofs3d/${RUN}_drag.gr3  drag.gr3
    ln -sf $FIXstofs3d/${RUN}_diffmin.gr3  diffmin.gr3
    ln -sf $FIXstofs3d/${RUN}_diffmax.gr3  diffmax.gr3
    ln -sf $FIXstofs3d/${RUN}_bctides.in_template  bctides.in_template
    ln -sf $FIXstofs3d/${RUN}_albedo.gr3  albedo.gr3
    ln -sf $FIXstofs3d/${RUN}_partition.prop  partition.prop

    echo "STOFS static file staging complete"
}


_stofs_create_model_config() {
    local file_log

    cd $DATA

    # Create param.nml for nowcast and forecast phases
    file_log=log_create_param_nml.${cycle}.log
    for _phase in nowcast forecast; do
        export pgm="${USHstofs3d}/stofs_3d_atl_create_param_nml.sh ${_phase}"
        echo "Creating param.nml for ${_phase}..."
        ${USHstofs3d}/stofs_3d_atl_create_param_nml.sh ${_phase} >> ${file_log} 2>&1
        export err=$?
        if [ $err -ne 0 ]; then
            msg=" Execution of $pgm (${_phase}) did not complete normally - WARNING"
            postmsg "$msg"
            cat ${file_log}
        else
            msg=" Execution of $pgm (${_phase}) completed normally"
            postmsg "$msg"
            cat ${file_log}
        fi
        echo $msg
    done

    echo

    # Create bctides.in
    file_log=log_create_bctides.${cycle}.log
    export pgm="${USHstofs3d}/stofs_3d_atl_create_bctides_in.sh"
    echo "Creating bctides.in..."
    ${USHstofs3d}/stofs_3d_atl_create_bctides_in.sh >> ${file_log} 2>&1
    export err=$?
    if [ $err -ne 0 ]; then
        msg=" Execution of $pgm did not complete normally - WARNING"
        postmsg "$msg"
    else
        msg=" Execution of $pgm completed normally"
        postmsg "$msg"
    fi
    echo $msg
    echo
}


_stofs_create_forcing_atmospheric() {
    local file_log

    cd $DATA

    # GFS surface forcing
    file_log=log_create_surface_forcing_gfs.${cycle}.log
    export pgm="${USHstofs3d}/stofs_3d_atl_create_surface_forcing_gfs.sh"
    echo "Creating GFS surface forcing..."
    ${USHstofs3d}/stofs_3d_atl_create_surface_forcing_gfs.sh >> ${file_log} 2>&1
    export err=$?
    if [ $err -ne 0 ]; then
        msg=" Execution of $pgm did not complete normally - WARNING"
        postmsg "$msg"
        cat ${file_log}
        err_chk
    else
        msg=" Execution of $pgm completed normally"
        postmsg "$msg"
        cat ${file_log}
    fi
    echo $msg
    echo

    # HRRR surface forcing
    file_log=log_create_surface_forcing_hrrr.${cycle}.log
    export pgm="${USHstofs3d}/stofs_3d_atl_create_surface_forcing_hrrr.sh"
    echo "Creating HRRR surface forcing..."
    ${USHstofs3d}/stofs_3d_atl_create_surface_forcing_hrrr.sh >> ${file_log} 2>&1
    export err=$?
    if [ $err -ne 0 ]; then
        msg=" Execution of $pgm did not complete normally - WARNING"
        postmsg "$msg"
        cat ${file_log}
        err_chk
    else
        msg=" Execution of $pgm completed normally"
        postmsg "$msg"
        cat ${file_log}
    fi
    echo $msg
    echo
}


_stofs_create_forcing_river() {
    local file_log

    cd $DATA

    # NWM river forcing
    file_log=log_create_river_forcing_nwm.${cycle}.log
    export pgm="${USHstofs3d}/stofs_3d_atl_create_river_forcing_nwm.sh"
    echo "Creating NWM river forcing..."
    ${USHstofs3d}/stofs_3d_atl_create_river_forcing_nwm.sh >> ${file_log} 2>&1
    export err=$?
    if [ $err -ne 0 ]; then
        msg=" Execution of $pgm did not complete normally - WARNING"
        postmsg "$msg"
        cat ${file_log}
        err_chk
    else
        msg=" Execution of $pgm completed normally"
        postmsg "$msg"
        cat ${file_log}
    fi
    echo $msg
    echo

    # St. Lawrence River forcing
    file_log=log_create_river_st_lawrence.${cycle}.log
    export pgm="${USHstofs3d}/stofs_3d_atl_create_river_st_lawrence.sh"
    echo "Creating St. Lawrence River forcing..."
    ${USHstofs3d}/stofs_3d_atl_create_river_st_lawrence.sh >> ${file_log} 2>&1
    export err=$?
    if [ $err -ne 0 ]; then
        msg=" Execution of $pgm did not complete normally - WARNING"
        postmsg "$msg"
        cat ${file_log}
        err_chk
    else
        msg=" Execution of $pgm completed normally"
        postmsg "$msg"
        cat ${file_log}
    fi
    echo $msg
    echo
}


_stofs_create_forcing_obc() {
    local file_log

    cd $DATA

    # RTOFS OBC 3D time-history
    file_log=log_stofs_3d_atl_create_obc_3d_th.${cycle}.log
    export pgm="${USHstofs3d}/stofs_3d_atl_create_obc_3d_th.sh"
    echo "Creating RTOFS OBC 3D forcing..."
    ${USHstofs3d}/stofs_3d_atl_create_obc_3d_th.sh >> ${file_log} 2>&1
    export err=$?
    if [ $err -ne 0 ]; then
        msg=" Execution of $pgm did not complete normally - WARNING"
        postmsg "$msg"
        cat ${file_log}
        err_chk
    else
        msg=" Execution of $pgm completed normally"
        postmsg "$msg"
        cat ${file_log}
    fi
    echo $msg
    echo
}


_stofs_create_forcing_nudging() {
    local file_log

    cd $DATA

    # RTOFS OBC nudging
    file_log=log_stofs_3d_atl_create_obc_nudge.${cycle}.log
    export pgm="${USHstofs3d}/stofs_3d_atl_create_obc_nudge.sh"
    echo "Creating RTOFS OBC nudging..."
    ${USHstofs3d}/stofs_3d_atl_create_obc_nudge.sh >> ${file_log} 2>&1
    export err=$?
    if [ $err -ne 0 ]; then
        msg=" Execution of $pgm did not complete normally - WARNING"
        postmsg "$msg"
        cat ${file_log}
        err_chk
    else
        msg=" Execution of $pgm completed normally"
        postmsg "$msg"
        cat ${file_log}
    fi
    echo $msg
    echo
}


_stofs_prepare_initial_condition() {
    local file_log fn_restart_coldstart_fix fn_restart_rerun

    cd $DATA

    file_log=log_create_restart.${cycle}.log

    fn_restart_coldstart_fix=${FIXstofs3d}/stofs_3d_atl_restart_coldstart.nc
    fn_restart_rerun=${COMOUTrerun}/${RUN}.${cycle}.restart.nc

    mkdir -p ${COMOUTrerun}
    mkdir -p ${DATA_prep_restart}

    if [[ $COLDSTART = YES ]]; then
        msg="restart.nc: COLDSTART=${COLDSTART}, restart file from fix/"
        echo -e ${msg}; echo "${msg}" >> ${file_log}

        if [[ $(find ${fn_restart_coldstart_fix} -type f -size +20G 2>/dev/null) ]]; then
            cpreq -fp ${fn_restart_coldstart_fix} ${fn_restart_rerun}
            msg="done: copy ${fn_restart_coldstart_fix} to ${fn_restart_rerun}"
            echo -e "${msg}"; echo "${msg}" >> ${file_log}
        else
            msg="WARNING: not found - ${fn_restart_coldstart_fix}"
            echo "${msg}"; echo "${msg}" >> ${file_log}
        fi

    else
        # COLDSTART=NO — search previous cycle hotstart
        msg="COLDSTART=${COLDSTART}"
        echo "${msg}"

        LIST_fn_fnl_hotstart=''
        days=(0 1 2 3 4)
        cnt_files=0

        for k in ${days[@]}; do
            date_k=$(date -d "${PDYHH_NCAST_BEGIN:0:8} ${k} days ago" +%Y%m%d)
            fn_hotstart_oper=$COMINstofs/${RUN}.${date_k}/${RUN}.${cycle}.hotstart.stofs3d.nc

            if [ -s $fn_hotstart_oper ]; then
                if [[ $(find ${fn_hotstart_oper} -type f -size +20G 2>/dev/null) ]]; then
                    LIST_fn_fnl_hotstart+="${fn_hotstart_oper} "
                    echo "OK: $fn_hotstart_oper : filesize GT 22GB"
                    cnt_files=$((cnt_files+1))
                    break
                else
                    echo "WARNING: $fn_hotstart_oper : filesize less than 22GB"
                fi
            else
                echo "WARNING: $fn_hotstart_oper does not exist"
            fi
        done
        echo "cnt_files = ${cnt_files}"

        if [[ $cnt_files -ge 1 ]]; then
            LIST_fn_fnl_hotstart=(${LIST_fn_fnl_hotstart[@]})
            fn_hotstart_oper_prev=${LIST_fn_fnl_hotstart[0]}
            echo "found: fn_hotstart_oper_prev = ${fn_hotstart_oper_prev}"
            cpreq -pf ${fn_hotstart_oper_prev} ${fn_restart_rerun}
        else
            msg="WARNING: not found - hotstart file in COMINstofs"
            echo "${msg}"; echo "${msg}" >> ${file_log}
        fi
    fi
}


################################################################################
#
#  COMF INTERNAL FUNCTIONS
#  These wrap existing nosofs scripts to maintain backward compatibility
#
################################################################################

_comf_stage_static_files() {
    # COMF setup is done by nos_ofs_launch.sh which copies grid files,
    # control files, etc. to $DATA

    echo "Start ${RUN} Preparation" > $cormslogfile

    # Load YAML or .ctl configuration first
    CONFIG_SOURCE="none"

    # Option 1: Load from OFS_CONFIG environment variable (YAML)
    if [ -n "${OFS_CONFIG:-}" ] && [ -f "${OFS_CONFIG:-}" ]; then
        echo "Loading configuration from YAML: $OFS_CONFIG"
        if [ -f "${USHnos}/nos_ofs_config.sh" ]; then
            . ${USHnos}/nos_ofs_config.sh
            if [ "${OFS_CONFIG_LOADED:-0}" -eq 1 ]; then
                CONFIG_SOURCE="yaml"
                echo "Successfully loaded YAML config from $OFS_CONFIG" >> $cormslogfile
            fi
        fi
    fi

    # Option 2: Check for YAML config in FIXofs
    if [ "$CONFIG_SOURCE" = "none" ] && [ -f "${FIXofs}/${PREFIXNOS}.yaml" ]; then
        echo "Loading configuration from YAML: ${FIXofs}/${PREFIXNOS}.yaml"
        export OFS_CONFIG="${FIXofs}/${PREFIXNOS}.yaml"
        if [ -f "${USHnos}/nos_ofs_config.sh" ]; then
            . ${USHnos}/nos_ofs_config.sh
            if [ "${OFS_CONFIG_LOADED:-0}" -eq 1 ]; then
                CONFIG_SOURCE="yaml"
                echo "Successfully loaded YAML config from ${FIXofs}/${PREFIXNOS}.yaml" >> $cormslogfile
            fi
        fi
    fi

    # Option 3: Fall back to legacy .ctl file
    if [ "$CONFIG_SOURCE" = "none" ]; then
        if [ -s ${FIXofs}/${PREFIXNOS}.ctl ]; then
            . ${FIXofs}/${PREFIXNOS}.ctl
            CONFIG_SOURCE="ctl"
            echo "Loaded legacy .ctl config from ${FIXofs}/${PREFIXNOS}.ctl" >> $cormslogfile
        else
            echo "${RUN} control file is not found"
            echo "please provide ${RUN} control file: ${PREFIXNOS}.yaml or ${PREFIXNOS}.ctl in ${FIXofs}"
            msg="${RUN} control file is not found"
            postmsg "$jlogfile" "$msg"
            postmsg "$nosjlogfile" "$msg"
            echo "${RUN} control file is not found" >> $cormslogfile
            err_chk
        fi
    fi
    echo "Configuration loaded from: $CONFIG_SOURCE"

    # Run nos_ofs_launch.sh to set up NOS configuration and stage files
    export pgm="$USHnos/nos_ofs_launch.sh $OFS prep"
    echo "run the launch script to set the NOS configuration"
    . $USHnos/nos_ofs_launch.sh $OFS prep
    export err=$?
    if [ $err -ne 0 ]; then
        echo "Execution of $pgm did not complete normally, FATAL ERROR!"
        echo "Execution of $pgm did not complete normally, FATAL ERROR!" >> $cormslogfile
        msg=" Execution of $pgm did not complete normally, FATAL ERROR!"
        postmsg "$jlogfile" "$msg"
        postmsg "$nosjlogfile" "$msg"
        err_chk
    else
        echo "Execution of $pgm completed normally" >> $cormslogfile
        echo "Execution of $pgm completed normally"
        msg=" Execution of $pgm completed normally"
        postmsg "$jlogfile" "$msg"
        postmsg "$nosjlogfile" "$msg"
    fi
}


_comf_create_model_config() {
    cd $DATA

    # Model-specific control file generation based on OCEAN_MODEL
    if [ "${OCEAN_MODEL}" = "FVCOM" ] || [ "${OCEAN_MODEL}" = "fvcom" ]; then
        echo "Preparing FVCOM Control File for nowcast"
        export pgm="nos_ofs_prep_fvcom_ctl.sh $OFS nowcast"
        $USHnos/nos_ofs_prep_fvcom_ctl.sh $OFS nowcast
        export err=$?
        if [ $err -ne 0 ]; then
            echo "Execution of nowcast ctl did not complete normally, FATAL ERROR!"
            echo "Execution of nowcast ctl did not complete normally, FATAL ERROR!" >> $cormslogfile
            msg=" Execution of nowcast ctl did not complete normally, FATAL ERROR!"
            postmsg "$jlogfile" "$msg"
            err_chk
        else
            echo "Execution of nowcast ctl completed normally"
            echo "Execution of nowcast ctl completed normally" >> $cormslogfile
            msg=" Execution of nowcast ctl completed normally"
            postmsg "$jlogfile" "$msg"
        fi

        if [ ${LEN_FORECAST:-0} -gt 0 ]; then
            echo "Preparing FVCOM Control File for forecast"
            $USHnos/nos_ofs_prep_fvcom_ctl.sh $OFS forecast
            export err=$?
            if [ $err -ne 0 ]; then
                echo "Execution of forecast ctl did not complete normally, FATAL ERROR!"
                echo "Execution of forecast ctl did not complete normally, FATAL ERROR!" >> $cormslogfile
                msg=" Execution of forecast ctl did not complete normally, FATAL ERROR!"
                postmsg "$jlogfile" "$msg"
                err_chk
            else
                echo "Execution of forecast ctl completed normally"
                echo "Execution of forecast ctl completed normally" >> $cormslogfile
                msg=" Execution of forecast ctl completed normally"
                postmsg "$jlogfile" "$msg"
            fi
        fi

    elif [ "${OCEAN_MODEL}" = "ROMS" ] || [ "${OCEAN_MODEL}" = "roms" ]; then
        echo "Preparing ROMS Control File for nowcast"
        export pgm=nos_ofs_prep_roms_ctl.sh
        . prep_step
        $USHnos/nos_ofs_prep_roms_ctl.sh $OFS nowcast
        export err=$?
        if [ $err -ne 0 ]; then
            echo "Execution of $pgm did not complete normally, FATAL ERROR!"
            echo "Execution of $pgm did not complete normally, FATAL ERROR!" >> $cormslogfile
            msg=" Execution of $pgm did not complete normally, FATAL ERROR!"
            postmsg "$jlogfile" "$msg"
            postmsg "$nosjlogfile" "$msg"
            err_chk
        else
            echo "Execution of $pgm completed normally"
            echo "Execution of $pgm completed normally" >> $cormslogfile
            msg=" Execution of $pgm completed normally"
            postmsg "$jlogfile" "$msg"
            postmsg "$nosjlogfile" "$msg"
        fi

        if [ ${LEN_FORECAST:-0} -gt 0 ]; then
            echo "Preparing ROMS Control File for forecast"
            export pgm=nos_ofs_prep_roms_ctl.sh
            . prep_step
            $USHnos/nos_ofs_prep_roms_ctl.sh $OFS forecast
            export err=$?
            if [ $err -ne 0 ]; then
                echo "Execution of $pgm did not complete normally, FATAL ERROR!"
                echo "Execution of $pgm did not complete normally, FATAL ERROR!" >> $cormslogfile
                msg=" Execution of $pgm did not complete normally, FATAL ERROR!"
                postmsg "$jlogfile" "$msg"
                postmsg "$nosjlogfile" "$msg"
                err_chk
            else
                echo "Execution of $pgm completed normally"
                echo "Execution of $pgm completed normally" >> $cormslogfile
                msg=" Execution of $pgm completed normally"
                postmsg "$jlogfile" "$msg"
                postmsg "$nosjlogfile" "$msg"
            fi
        fi

    elif [ "${OCEAN_MODEL}" = "SELFE" ] || [ "${OCEAN_MODEL}" = "selfe" ] || \
         [ "${OCEAN_MODEL}" = "SCHISM" ] || [ "${OCEAN_MODEL}" = "schism" ]; then
        echo "Preparing SCHISM Control File for nowcast"
        export pgm="nos_ofs_prep_schism_ctl.sh $OFS nowcast"
        $USHnos/nos_ofs_prep_schism_ctl.sh $OFS nowcast
        export err=$?
        if [ $err -ne 0 ]; then
            echo "Execution of nowcast ctl did not complete normally, FATAL ERROR!"
            echo "Execution of nowcast ctl did not complete normally, FATAL ERROR!" >> $cormslogfile
            msg=" Execution of nowcast ctl did not complete normally, FATAL ERROR!"
            postmsg "$jlogfile" "$msg"
            err_chk
        else
            echo "Execution of nowcast ctl completed normally"
            echo "Execution of nowcast ctl completed normally" >> $cormslogfile
            msg=" Execution of nowcast ctl completed normally"
            postmsg "$jlogfile" "$msg"
        fi

        # SCHISM NWM source/sink tar archive for nowcast/forecast
        tar -cvf ${NWM_SOURCE_SINK_NOW} -C ./data/ .
        cp ${NWM_SOURCE_SINK_NOW} ${COMOUT}/${NWM_SOURCE_SINK_NOW}

        read rnday < "nowcast_running_day"
        ns=$(echo "scale=0; $rnday * 3600 *24" | bc)
        nsecond=$(printf "%.0f\n" "$ns")

        cd ./data
        for i in vsink.th vsource.th msource.th; do
            awk -v awk_var=$nsecond '{ $1 = $1 - awk_var ; print }' $i > $i.new
            awk '$1 >= 0' $i.new > $i.new.new
            mv $i.new.new $i
        done
        rm -f *.new
        cd ..

        tar -cvf ${NWM_SOURCE_SINK_FORE} -C ./data/ .
        cp ${NWM_SOURCE_SINK_FORE} ${COMOUT}/${NWM_SOURCE_SINK_FORE}

        if [ ${LEN_FORECAST:-0} -gt 0 ]; then
            echo "Preparing SCHISM Control File for forecast"
            $USHnos/nos_ofs_prep_schism_ctl.sh $OFS forecast
            export err=$?
            if [ $err -ne 0 ]; then
                echo "Execution of forecast ctl did not complete normally, FATAL ERROR!"
                echo "Execution of forecast ctl did not complete normally, FATAL ERROR!" >> $cormslogfile
                msg=" Execution of forecast ctl did not complete normally, FATAL ERROR!"
                postmsg "$jlogfile" "$msg"
                err_chk
            else
                echo "Execution of forecast ctl completed normally"
                echo "Execution of forecast ctl completed normally" >> $cormslogfile
                msg=" Execution of forecast ctl completed normally"
                postmsg "$jlogfile" "$msg"
            fi
        fi
    fi
}


_comf_create_forcing_atmospheric() {
    cd $DATA

    export metnum=1

    # Nowcast meteorological forcing
    echo "The script nos_ofs_create_forcing_met.sh nowcast starts at time: $(date)"
    . prep_step
    echo "Generating the meteorological forcing for nowcast"
    export pgm=nos_ofs_create_forcing_met.sh
    DBASE=$DBASE_MET_NOW
    TIME_START_TMP=${time_hotstart}
    TIME_END_TMP=$time_nowcastend
    $USHnos/nos_ofs_create_forcing_met.sh nowcast $DBASE $TIME_START_TMP $TIME_END_TMP
    export err=$?
    if [ $err -ne 0 ]; then
        echo "Execution of $pgm did not complete normally, FATAL ERROR!"
        echo "Execution of $pgm did not complete normally, FATAL ERROR!" >> $cormslogfile
        msg=" Execution of $pgm did not complete normally, FATAL ERROR!"
        postmsg "$jlogfile" "$msg"
        postmsg "$nosjlogfile" "$msg"
        err_chk
    else
        echo "Execution of $pgm completed normally" >> $cormslogfile
        echo "Execution of $pgm completed normally"
        msg=" Execution of $pgm completed normally"
        postmsg "$jlogfile" "$msg"
        postmsg "$nosjlogfile" "$msg"
    fi
    if [ -s MET_DBASE.NOWCAST ]; then
        read DBASE < MET_DBASE.NOWCAST
        echo 'DBASE=' $DBASE 'DBASE_MET_NOW=' $DBASE_MET_NOW
        if [ $DBASE != $DBASE_MET_NOW ]; then
            DBASE_MET_NOW=$DBASE
            export DBASE_MET_NOW
        fi
    fi

    # Second nowcast met source (if MET_NUM=2)
    if [ ${MET_NUM:-1} -eq 2 ]; then
        export metnum=2
        export pgm=nos_ofs_create_forcing_met.sh
        DBASE=$DBASE_MET_NOW2
        TIME_START_TMP=${time_hotstart}
        TIME_END_TMP=$time_nowcastend
        $USHnos/nos_ofs_create_forcing_met.sh nowcast $DBASE $TIME_START_TMP $TIME_END_TMP
        export err=$?
        if [ $err -ne 0 ]; then
            echo "Execution of $pgm did not complete normally, FATAL ERROR!"
            echo "Execution of $pgm did not complete normally, FATAL ERROR!" >> $cormslogfile
            msg=" Execution of $pgm did not complete normally, FATAL ERROR!"
            postmsg "$jlogfile" "$msg"
            postmsg "$nosjlogfile" "$msg"
            err_chk
        else
            echo "Execution of $pgm completed normally" >> $cormslogfile
            echo "Execution of $pgm completed normally"
            msg=" Execution of $pgm completed normally"
            postmsg "$jlogfile" "$msg"
            postmsg "$nosjlogfile" "$msg"
        fi
        if [ -s MET_DBASE.NOWCAST ]; then
            read DBASE < MET_DBASE.NOWCAST
            echo 'DBASE=' $DBASE 'DBASE_MET_NOW=' $DBASE_MET_NOW
            if [ $DBASE != $DBASE_MET_NOW ]; then
                DBASE_MET_NOW=$DBASE
                export DBASE_MET_NOW
            fi
        fi
    fi

    # Forecast meteorological forcing
    export metnum=1

    if [ ${LEN_FORECAST:-0} -gt 0 ]; then
        echo "The script nos_ofs_create_forcing_met.sh forecast starts at time: $(date)"
        echo "Generating the meteorological forcing for forecast"

        # Determine number of forecast met sources (blended, e.g. HRRR:NDFD)
        res="${DBASE_MET_FOR//[^:]}"
        nnn=${#res}
        export nfore=$((nnn + 1))

        if [ $nfore -eq 1 ]; then
            DBASE=${DBASE_MET_FOR%:*}
            TIME_START_TMP=${time_nowcastend}
            TIME_END_TMP=$time_forecastend
            export pgm=nos_ofs_create_forcing_met.sh
            $USHnos/nos_ofs_create_forcing_met.sh forecast $DBASE $TIME_START_TMP $TIME_END_TMP
            export err=$?
            if [ $err -ne 0 ]; then
                echo "Execution of $pgm did not complete normally, FATAL ERROR!"
                echo "Execution of $pgm did not complete normally, FATAL ERROR!" >> $cormslogfile
                msg=" Execution of $pgm did not complete normally, FATAL ERROR!"
                postmsg "$jlogfile" "$msg"
                postmsg "$nosjlogfile" "$msg"
                err_chk
            else
                echo "Execution of $pgm completed normally"
                echo "Execution of $pgm completed normally" >> $cormslogfile
                msg=" Execution of $pgm completed normally"
                postmsg "$jlogfile" "$msg"
                postmsg "$nosjlogfile" "$msg"
            fi

        elif [ $nfore -eq 2 ]; then
            DBASE=${DBASE_MET_FOR%:*}
            TIME_START_TMP=${time_nowcastend}
            TIME_END_TMP=$($NDATE +48 $TIME_START_TMP)
            export pgm=nos_ofs_create_forcing_met.sh
            export met_fore_round=1
            $USHnos/nos_ofs_create_forcing_met.sh forecast $DBASE $TIME_START_TMP $TIME_END_TMP
            export err=$?
            if [ $err -ne 0 ]; then
                echo "Execution of $pgm did not complete normally, FATAL ERROR!"
                echo "Execution of $pgm did not complete normally, FATAL ERROR!" >> $cormslogfile
                msg=" Execution of $pgm did not complete normally, FATAL ERROR!"
                postmsg "$jlogfile" "$msg"
                postmsg "$nosjlogfile" "$msg"
                err_chk
            else
                echo "Execution of $pgm completed normally"
                echo "Execution of $pgm completed normally" >> $cormslogfile
                msg=" Execution of $pgm completed normally"
                postmsg "$jlogfile" "$msg"
                postmsg "$nosjlogfile" "$msg"
                if [ -s MET_DBASE.FORECAST ]; then
                    read DBASE < MET_DBASE.FORECAST
                    echo 'DBASE=' $DBASE 'DBASE_MET_FOR=' $DBASE_MET_FOR
                fi
                cp -p $MET_NETCDF_1_FORECAST"1" ${MET_NETCDF_1_FORECAST}.$DBASE
                cp -p $MET_NETCDF_2_FORECAST"1" ${MET_NETCDF_2_FORECAST}.$DBASE
            fi

            DBASE=${DBASE_MET_FOR#*:}
            TIME_START_TMP=${time_nowcastend}
            TIME_END_TMP=${time_forecastend}
            export pgm=nos_ofs_create_forcing_met.sh
            export met_fore_round=2
            $USHnos/nos_ofs_create_forcing_met.sh forecast $DBASE $TIME_START_TMP $TIME_END_TMP
            export err=$?
            if [ $err -ne 0 ]; then
                echo "Execution of $pgm did not complete normally, FATAL ERROR!"
                echo "Execution of $pgm did not complete normally, FATAL ERROR!" >> $cormslogfile
                msg=" Execution of $pgm did not complete normally, FATAL ERROR!"
                postmsg "$jlogfile" "$msg"
                postmsg "$nosjlogfile" "$msg"
                err_chk
            else
                echo "Execution of $pgm completed normally"
                echo "Execution of $pgm completed normally" >> $cormslogfile
                msg=" Execution of $pgm completed normally"
                postmsg "$jlogfile" "$msg"
                postmsg "$nosjlogfile" "$msg"
                if [ -s MET_DBASE.FORECAST ]; then
                    read DBASE < MET_DBASE.FORECAST
                    echo 'DBASE=' $DBASE 'DBASE_MET_FOR=' $DBASE_MET_FOR
                fi
                mv $MET_NETCDF_1_FORECAST"2" ${MET_NETCDF_1_FORECAST}.$DBASE
                mv $MET_NETCDF_2_FORECAST"2" ${MET_NETCDF_2_FORECAST}.$DBASE
                rm -f $MET_NETCDF_1_FORECAST"1"
                rm -f $MET_NETCDF_2_FORECAST"1"
            fi
        fi

        # Second forecast met source (if MET_NUM=2)
        if [ ${MET_NUM:-1} -eq 2 ]; then
            export metnum=2
            DBASE=$DBASE_MET_FOR2
            TIME_START_TMP=${time_nowcastend}
            TIME_END_TMP=${time_forecastend}
            export pgm=nos_ofs_create_forcing_met.sh
            $USHnos/nos_ofs_create_forcing_met.sh forecast $DBASE $TIME_START_TMP $TIME_END_TMP
            export err=$?
            if [ $err -ne 0 ]; then
                echo "Execution of $pgm did not complete normally, FATAL ERROR!"
                echo "Execution of $pgm did not complete normally, FATAL ERROR!" >> $cormslogfile
                msg=" Execution of $pgm did not complete normally, FATAL ERROR!"
                postmsg "$jlogfile" "$msg"
                postmsg "$nosjlogfile" "$msg"
                err_chk
            else
                echo "Execution of $pgm completed normally"
                echo "Execution of $pgm completed normally" >> $cormslogfile
                msg=" Execution of $pgm completed normally"
                postmsg "$jlogfile" "$msg"
                postmsg "$nosjlogfile" "$msg"
                if [ -s MET_DBASE.FORECAST ]; then
                    read DBASE < MET_DBASE.FORECAST
                    echo 'DBASE=' $DBASE 'DBASE_MET_FOR=' $DBASE_MET_FOR
                fi
                mv $MET_NETCDF_1_FORECAST"2" ${MET_NETCDF_1_FORECAST}.$DBASE
                mv $MET_NETCDF_2_FORECAST"2" ${MET_NETCDF_2_FORECAST}.$DBASE
                rm -f $MET_NETCDF_1_FORECAST"1"
                rm -f $MET_NETCDF_2_FORECAST"1"
            fi
        fi

        # Update DBASE_MET_FOR if actual forcing source changed
        if [ -s MET_DBASE.FORECAST ]; then
            read DBASE < MET_DBASE.FORECAST
            echo 'DBASE=' $DBASE 'DBASE_MET_FOR=' $DBASE_MET_FOR
            if [ $DBASE != $DBASE_MET_FOR ]; then
                DBASE_MET_FOR=$DBASE
                export DBASE_MET_FOR
            fi
        fi
        echo "The script nos_ofs_create_forcing_met.sh forecast ended at time: $(date)"
    fi
}


_comf_create_forcing_river() {
    cd $DATA

    echo "The script nos_ofs_create_forcing_river.sh starts at time: $(date)"
    echo "Generating the river forcing"
    export pgm=nos_ofs_create_forcing_river.sh
    . prep_step
    $USHnos/nos_ofs_create_forcing_river.sh
    export err=$?
    if [ $err -ne 0 ]; then
        echo "Execution of $pgm did not complete normally, FATAL ERROR!"
        echo "Execution of $pgm did not complete normally, FATAL ERROR!" >> $cormslogfile
        msg=" Execution of $pgm did not complete normally, FATAL ERROR!"
        postmsg "$jlogfile" "$msg"
        postmsg "$nosjlogfile" "$msg"
        err_chk
    else
        echo "Execution of $pgm completed normally"
        echo "Execution of $pgm completed normally" >> $cormslogfile
        msg=" Execution of $pgm completed normally"
        postmsg "$jlogfile" "$msg"
        postmsg "$nosjlogfile" "$msg"
    fi
}


_comf_create_forcing_obc() {
    cd $DATA

    # Skip OBC for systems that don't need it (lsofs, loofs)
    if [ "${OFS,,}" = "lsofs" ] || [ "${OFS,,}" = "loofs" ]; then
        echo "Skipping OBC forcing for ${OFS} (not required)"
        return 0
    fi

    echo "The script nos_ofs_create_forcing_obc.sh starts at time: $(date)"
    echo "Generating the open boundary forcing"
    export pgm=nos_ofs_create_forcing_obc.sh
    . prep_step
    $USHnos/nos_ofs_create_forcing_obc.sh
    export err=$?
    if [ $err -ne 0 ]; then
        echo "Execution of $pgm did not complete normally, FATAL ERROR!"
        echo "Execution of $pgm did not complete normally, FATAL ERROR!" >> $cormslogfile
        msg=" Execution of $pgm did not complete normally, FATAL ERROR!"
        postmsg "$jlogfile" "$msg"
        postmsg "$nosjlogfile" "$msg"
        err_chk
    else
        echo "Execution of $pgm completed normally"
        echo "Execution of $pgm completed normally" >> $cormslogfile
        msg=" Execution of $pgm completed normally"
        postmsg "$jlogfile" "$msg"
        postmsg "$nosjlogfile" "$msg"
    fi
}


_comf_create_forcing_nudging() {
    cd $DATA

    TS_NUDGING=${TS_NUDGING:-0}
    if [ $TS_NUDGING -eq 1 ]; then
        echo "Generating the forcing for T/S nudging fields"
        export pgm=nos_ofs_create_forcing_nudg.sh
        . prep_step
        $USHnos/nos_ofs_create_forcing_nudg.sh
        export err=$?
        if [ $err -ne 0 ]; then
            echo "Execution of $pgm did not complete normally, FATAL ERROR!"
            echo "Execution of $pgm did not complete normally, FATAL ERROR!" >> $cormslogfile
            msg=" Execution of $pgm did not complete normally, FATAL ERROR!"
            postmsg "$jlogfile" "$msg"
            postmsg "$nosjlogfile" "$msg"
            err_chk
        else
            echo "Execution of $pgm completed normally"
            echo "Execution of $pgm completed normally" >> $cormslogfile
            msg=" Execution of $pgm completed normally"
            postmsg "$jlogfile" "$msg"
            postmsg "$nosjlogfile" "$msg"
        fi
    else
        echo "T/S nudging not enabled (TS_NUDGING=${TS_NUDGING})"
    fi
}


_comf_prepare_initial_condition() {
    # COMF restart/initial condition is handled inside nos_ofs_launch.sh
    # which was already called by stage_static_files
    echo "COMF initial condition handled by nos_ofs_launch.sh"
}
