#!/bin/bash
################################################################################
#  Name: nos_ofs_model_run.sh
#  Purpose: Unified model run functions for all NOS OFS systems
#           Provides a common 4-step interface for both STOFS and COMF frameworks
#
#  Usage:
#     source ${USHnos}/nos_ofs_model_run.sh
#     stage_model_files "nowcast"
#     prepare_restart "nowcast"
#     execute_model "nowcast"
#     archive_outputs "nowcast"
#
#  Functions:
#     stage_model_files <phase>   - Copy forcing/static files to $DATA
#     prepare_restart <phase>     - Find and stage hotstart/initial condition
#     execute_model <phase>       - Configure runtime and run SCHISM via mpiexec
#     archive_outputs <phase>     - Copy outputs to $COMOUT
#
#  Environment Requirements:
#     OFS_FRAMEWORK  - "stofs" or "comf"
#     DATA           - Working directory
#     COMOUT         - Output directory
#     Plus framework-specific variables (FIXstofs3d, COMOUTrerun, etc.)
#
################################################################################

################################################################################
# stage_model_files - Copy forcing and static files to working directory
#
# Arguments:
#   $1 - Phase: "nowcast" or "forecast"
################################################################################
stage_model_files() {
    local phase="${1:?phase argument required (nowcast|forecast)}"

    echo "=== stage_model_files: ${phase} (framework: ${OFS_FRAMEWORK}) ==="

    # Common: create output directories
    mkdir -p $DATA/outputs $DATA/sflux

    case "${OFS_FRAMEWORK}" in
        stofs) _stofs_stage_files "$phase" ;;
        comf)  _comf_stage_files "$phase" ;;
        *)     echo "ERROR: Unknown framework: ${OFS_FRAMEWORK}"; return 1 ;;
    esac
}

################################################################################
# prepare_restart - Find and stage hotstart/initial condition file
#
# Arguments:
#   $1 - Phase: "nowcast" or "forecast"
################################################################################
prepare_restart() {
    local phase="${1:?phase argument required (nowcast|forecast)}"

    echo "=== prepare_restart: ${phase} (framework: ${OFS_FRAMEWORK}) ==="

    case "${OFS_FRAMEWORK}" in
        stofs) _stofs_prepare_restart "$phase" ;;
        comf)  _comf_prepare_restart "$phase" ;;
        *)     echo "ERROR: Unknown framework: ${OFS_FRAMEWORK}"; return 1 ;;
    esac
}

################################################################################
# execute_model - Configure runtime and run SCHISM
#
# Arguments:
#   $1 - Phase: "nowcast" or "forecast"
################################################################################
execute_model() {
    local phase="${1:?phase argument required (nowcast|forecast)}"

    echo "=== execute_model: ${phase} (framework: ${OFS_FRAMEWORK}) ==="

    case "${OFS_FRAMEWORK}" in
        stofs) _stofs_execute_model "$phase" ;;
        comf)  _comf_execute_model "$phase" ;;
        *)     echo "ERROR: Unknown framework: ${OFS_FRAMEWORK}"; return 1 ;;
    esac
}

################################################################################
# archive_outputs - Copy model outputs to $COMOUT
#
# Arguments:
#   $1 - Phase: "nowcast" or "forecast"
################################################################################
archive_outputs() {
    local phase="${1:?phase argument required (nowcast|forecast)}"

    echo "=== archive_outputs: ${phase} (framework: ${OFS_FRAMEWORK}) ==="

    case "${OFS_FRAMEWORK}" in
        stofs) _stofs_archive_outputs "$phase" ;;
        comf)  _comf_archive_outputs "$phase" ;;
        *)     echo "ERROR: Unknown framework: ${OFS_FRAMEWORK}"; return 1 ;;
    esac
}


################################################################################
#
#  STOFS INTERNAL FUNCTIONS
#
################################################################################

_stofs_stage_files() {
    local phase=$1

    cd $DATA

    # Link static files from FIXstofs3d
    local static_files=(
        "windrot_geo2proj.gr3"
        "watertype.gr3"
        "vgrid.in"
        "tvd.prop"
        "station.in"
        "shapiro.gr3"
        "drag.gr3"
        "diffmin.gr3"
        "diffmax.gr3"
        "albedo.gr3"
        "hgrid.ll"
        "hgrid.gr3"
        "estuary.gr3"
        "partition.prop"
    )

    for f in "${static_files[@]}"; do
        [ -f "$FIXstofs3d/${RUN}_${f}" ] && ln -sf "$FIXstofs3d/${RUN}_${f}" "$DATA/$f"
    done

    # Nudging files (different naming convention)
    [ -f "$FIXstofs3d/${RUN}_tem_nudge.gr3" ] && ln -sf "$FIXstofs3d/${RUN}_tem_nudge.gr3" "$DATA/TEM_nudge.gr3"
    [ -f "$FIXstofs3d/${RUN}_sal_nudge.gr3" ] && ln -sf "$FIXstofs3d/${RUN}_sal_nudge.gr3" "$DATA/SAL_nudge.gr3"
    [ -f "$FIXstofs3d/${RUN}_river_source_sink.in" ] && ln -sf "$FIXstofs3d/${RUN}_river_source_sink.in" "$DATA/source_sink.in"
    [ -f "$FIXstofs3d/${RUN}_river_msource.th" ] && ln -sf "$FIXstofs3d/${RUN}_river_msource.th" "$DATA/msource.th"

    # Copy phase-specific param.nml
    local fn_param="${COMOUTrerun}/${RUN}.${cycle}.param.${phase}.nml"
    if [ -s "$fn_param" ]; then
        cp -p "$fn_param" "$DATA/param.nml"
        echo "param.nml staged for ${phase}: $fn_param"
    else
        echo "WARNING: param.nml not found for ${phase}: $fn_param"
    fi

    # Tidal forcing
    [ -s "${COMOUTrerun}/${RUN}.${cycle}.bctides.in" ] && \
        cp -p "${COMOUTrerun}/${RUN}.${cycle}.bctides.in" "$DATA/bctides.in"

    # River forcing (NWM)
    for f in msource.th vsink.th vsource.th; do
        [ -s "${COMOUTrerun}/${RUN}.${cycle}.$f" ] && \
            cp -p "${COMOUTrerun}/${RUN}.${cycle}.$f" "$DATA/$f"
    done

    # St. Lawrence River
    [ -s "${COMOUTrerun}/${RUN}.${cycle}.riv.obs.flux.th" ] && \
        cp -p "${COMOUTrerun}/${RUN}.${cycle}.riv.obs.flux.th" "$DATA/flux.th"
    [ -s "${COMOUTrerun}/${RUN}.${cycle}.riv.obs.tem_1.th" ] && \
        cp -p "${COMOUTrerun}/${RUN}.${cycle}.riv.obs.tem_1.th" "$DATA/TEM_1.th"

    # GFS atmospheric forcing (sflux stack 1)
    [ -s "${COMOUTrerun}/${RUN}.${cycle}.gfs.air.nc" ] && \
        cp -p "${COMOUTrerun}/${RUN}.${cycle}.gfs.air.nc" "$DATA/sflux/sflux_air_1.0001.nc"
    [ -s "${COMOUTrerun}/${RUN}.${cycle}.gfs.prc.nc" ] && \
        cp -p "${COMOUTrerun}/${RUN}.${cycle}.gfs.prc.nc" "$DATA/sflux/sflux_prc_1.0001.nc"
    [ -s "${COMOUTrerun}/${RUN}.${cycle}.gfs.rad.nc" ] && \
        cp -p "${COMOUTrerun}/${RUN}.${cycle}.gfs.rad.nc" "$DATA/sflux/sflux_rad_1.0001.nc"

    # HRRR atmospheric forcing (sflux stack 2 — optional)
    [ -s "${COMOUTrerun}/${RUN}.${cycle}.hrrr.air.nc" ] && \
        cp -p "${COMOUTrerun}/${RUN}.${cycle}.hrrr.air.nc" "$DATA/sflux/sflux_air_2.0001.nc"
    [ -s "${COMOUTrerun}/${RUN}.${cycle}.hrrr.prc.nc" ] && \
        cp -p "${COMOUTrerun}/${RUN}.${cycle}.hrrr.prc.nc" "$DATA/sflux/sflux_prc_2.0001.nc"
    [ -s "${COMOUTrerun}/${RUN}.${cycle}.hrrr.rad.nc" ] && \
        cp -p "${COMOUTrerun}/${RUN}.${cycle}.hrrr.rad.nc" "$DATA/sflux/sflux_rad_2.0001.nc"

    # sflux_inputs.txt
    [ -s "$FIXstofs3d/${RUN}_sflux_inputs.txt" ] && \
        cp -p "$FIXstofs3d/${RUN}_sflux_inputs.txt" "$DATA/sflux/sflux_inputs.txt"

    # RTOFS OBC 3D time-history files
    local obc_pairs=("elev2dth.nc:elev2D.th.nc" "tem3dth.nc:TEM_3D.th.nc" "sal3dth.nc:SAL_3D.th.nc" "uv3dth.nc:uv3D.th.nc")
    for pair in "${obc_pairs[@]}"; do
        local src="${pair%%:*}" dst="${pair##*:}"
        [ -s "${COMOUTrerun}/${RUN}.${cycle}.${src}" ] && \
            cp -p "${COMOUTrerun}/${RUN}.${cycle}.${src}" "$DATA/${dst}"
    done

    # RTOFS nudging files
    local nudge_pairs=("temnu.nc:TEM_nu.nc" "salnu.nc:SAL_nu.nc")
    for pair in "${nudge_pairs[@]}"; do
        local src="${pair%%:*}" dst="${pair##*:}"
        [ -s "${COMOUTrerun}/${RUN}.${cycle}.${src}" ] && \
            cp -p "${COMOUTrerun}/${RUN}.${cycle}.${src}" "$DATA/${dst}"
    done

    echo "STOFS file staging complete for ${phase}"
}


_stofs_prepare_restart() {
    local phase=$1

    if [ "$phase" = "forecast" ]; then
        # Forecast: combine distributed hotstart files from nowcast output,
        # swap to forecast param.nml, and set ihot=2 for hot restart
        echo "Preparing forecast restart from nowcast outputs..."

        cd $DATA

        # Call existing hot restart prep script to find and combine
        # distributed hotstart files into a single hotstart.nc
        if [ -f "${SCRIstofs3d}/exstofs_3d_atl_hot_restart_prep.sh" ]; then
            ${SCRIstofs3d}/exstofs_3d_atl_hot_restart_prep.sh
            export err=$?
            if [ $err -ne 0 ]; then
                echo "ERROR: Hot restart prep failed"
                return 1
            fi
        else
            echo "ERROR: exstofs_3d_atl_hot_restart_prep.sh not found"
            return 1
        fi

        # Swap to forecast param.nml (correct rnday & start date)
        local fn_param="${COMOUTrerun}/${RUN}.${cycle}.param.forecast.nml"
        if [ -s "$fn_param" ]; then
            cp -p "$fn_param" "$DATA/param.nml"
            # Set ihot=2 for hot restart from nowcast output
            sed -i "s/ihot = 1/ihot = 2/" "$DATA/param.nml"
            echo "Forecast param.nml staged with ihot=2"
        else
            echo "ERROR: Forecast param.nml not found: $fn_param"
            return 1
        fi

        # Clean nowcast output files but keep hotstart.nc
        rm -f $DATA/outputs/schout_*.nc 2>/dev/null
        rm -f $DATA/outputs/mirror.out_cold_restart 2>/dev/null
        # Ensure required output files exist for SCHISM ihot=2 restart
        touch $DATA/outputs/mirror.out
        touch $DATA/outputs/flux.out
        for i in 1 2 3 4 5 6 7 8 9; do
            [ ! -f "$DATA/outputs/staout_${i}" ] && touch "$DATA/outputs/staout_${i}"
        done

        # Validate hotstart.nc
        if [ ! -s "$DATA/hotstart.nc" ]; then
            echo "ERROR: hotstart.nc not found after restart prep"
            return 1
        fi

        echo "Forecast restart preparation complete"
        return 0
    fi

    # Nowcast: find hotstart from previous cycle or use coldstart
    echo "Searching for previous cycle hotstart..."

    local fn_restart_rerun="${COMOUTrerun}/${RUN}.${cycle}.restart.nc"
    local days=(0 1 2 3 4)
    local found=0

    for k in "${days[@]}"; do
        local date_k=$(date -d "${PDYHH_NCAST_BEGIN:0:8} ${k} days ago" +%Y%m%d)
        local fn_hotstart="${COMINstofs}/${RUN}.${date_k}/${RUN}.${cycle}.hotstart.stofs3d.nc"

        if [ -s "$fn_hotstart" ]; then
            if [[ $(find "$fn_hotstart" -type f -size +20G 2>/dev/null) ]]; then
                echo "Found valid hotstart: $fn_hotstart"
                cp -p "$fn_hotstart" "$fn_restart_rerun"
                found=1
                break
            else
                echo "WARNING: $fn_hotstart exists but too small (<20GB)"
            fi
        else
            echo "Not found: $fn_hotstart"
        fi
    done

    if [ $found -eq 0 ]; then
        # Try coldstart file
        local fn_coldstart="${FIXstofs3d}/stofs_3d_atl_restart_coldstart.nc"
        if [ -s "$fn_coldstart" ]; then
            echo "Using coldstart file: $fn_coldstart"
            cp -p "$fn_coldstart" "$fn_restart_rerun"
        else
            echo "WARNING: No valid hotstart or coldstart file found"
            return 1
        fi
    fi
}


_stofs_execute_model() {
    local phase=$1

    cd $DATA

    # Validate critical input files
    local missing=0
    for f in param.nml bctides.in hgrid.gr3 vgrid.in; do
        if [ ! -s "$DATA/$f" ]; then
            echo "ERROR: Missing required file: $DATA/$f"
            missing=1
        fi
    done

    # Check hotstart
    if [ ! -s "$DATA/hotstart.nc" ]; then
        echo "WARNING: hotstart.nc not found — may be cold start"
    fi

    if [ $missing -eq 1 ]; then
        echo "FATAL: Missing critical model input files"
        return 1
    fi

    # Determine MPI task count and executable
    local nprocs=${TOTAL_TASKS:-${NCPU_PBS:-960}}
    local nscribes=${NSCRIBES:-6}
    local executable="${EXECstofs3d}/stofs_3d_atl_pschism"

    echo "Running SCHISM ${phase}: mpiexec -n ${nprocs} --cpu-bind core ${executable} ${nscribes}"

    mpiexec -n ${nprocs} --cpu-bind core ${executable} ${nscribes} \
        > "${DATA}/${RUN}.${cycle}.${phase}.log" 2>&1

    export err=$?

    # Verify completion via mirror.out
    if [ -s "$DATA/outputs/mirror.out" ] && \
       grep -q "Run completed successfully" "$DATA/outputs/mirror.out" 2>/dev/null; then
        echo "SCHISM ${phase} completed successfully"
        return 0
    else
        echo "ERROR: SCHISM ${phase} did not complete successfully"
        [ -s "$DATA/outputs/mirror.out" ] && tail -5 "$DATA/outputs/mirror.out"
        return 1
    fi
}


_stofs_archive_outputs() {
    local phase=$1

    if [ "$phase" = "nowcast" ]; then
        # Nowcast: outputs stay in $DATA for forecast to use
        # Archive key files to COMOUT for monitoring
        echo "Nowcast outputs staged for forecast phase"
        [ -s "$DATA/${RUN}.${cycle}.nowcast.log" ] && \
            cp -p "$DATA/${RUN}.${cycle}.nowcast.log" "$COMOUT/"
    elif [ "$phase" = "forecast" ]; then
        # Forecast: archive final hotstart for next cycle
        echo "Archiving forecast outputs to ${COMOUT}"

        # Archive model log
        [ -s "$DATA/${RUN}.${cycle}.forecast.log" ] && \
            cp -p "$DATA/${RUN}.${cycle}.forecast.log" "$COMOUT/"

        # The hotstart file for next cycle is handled by post/restart jobs
        echo "Forecast archive complete"
    fi
}


################################################################################
#
#  COMF INTERNAL FUNCTIONS
#  These wrap existing nosofs scripts to maintain backward compatibility
#
################################################################################

_comf_stage_files() {
    local phase=$1

    # COMF staging is handled inside nos_ofs_launch.sh
    # which copies grid files, control files, etc. to $DATA
    # We only need to call launch for the nowcast phase
    if [ "$phase" = "nowcast" ]; then
        echo "COMF file staging delegated to nos_ofs_launch.sh"
        . $USHnos/nos_ofs_launch.sh $OFS nowcast
        export pgm="$USHnos/nos_ofs_launch.sh $OFS nowcast"
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
            msg=" Execution of $pgm completed normally"
            postmsg "$jlogfile" "$msg"
            postmsg "$nosjlogfile" "$msg"
        fi
    fi
    # Forecast phase uses same $DATA with nowcast output as init
}


_comf_prepare_restart() {
    local phase=$1
    # COMF restart handling is done inside nos_ofs_launch.sh (nowcast)
    # and the forecast uses INI_FILE_FORECAST = RST_OUT_NOWCAST
    echo "COMF restart handled by nos_ofs_launch.sh"
}


_comf_execute_model() {
    local phase=$1

    echo "     " >> $jlogfile
    echo "     " >> $nosjlogfile
    echo " Start $phase " >> $jlogfile
    echo " Start $phase " >> $nosjlogfile
    echo "Making $phase at : $(date)" >> $jlogfile
    echo "Making $phase at : $(date)" >> $nosjlogfile
    echo "Making $phase at : $(date)"

    export pgm="$USHnos/nos_ofs_nowcast_forecast.sh $phase"
    $USHnos/nos_ofs_nowcast_forecast.sh $phase
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


_comf_archive_outputs() {
    local phase=$1

    export pgm="$USHnos/nos_ofs_archive.sh $phase"
    $USHnos/nos_ofs_archive.sh $phase
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
