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
#     execute_model <phase>       - Configure runtime and run model via mpiexec
#     archive_outputs <phase>     - Copy outputs to $COMOUT
#
#  Environment Requirements:
#     OFS_FRAMEWORK  - "stofs", "comf", or "adcirc"
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
        comf)   _comf_stage_files "$phase" ;;
        adcirc) _adcirc_stage_files "$phase" ;;
        *)      echo "ERROR: Unknown framework: ${OFS_FRAMEWORK}"; return 1 ;;
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
        comf)   _comf_prepare_restart "$phase" ;;
        adcirc) _adcirc_prepare_restart "$phase" ;;
        *)      echo "ERROR: Unknown framework: ${OFS_FRAMEWORK}"; return 1 ;;
    esac
}

################################################################################
# execute_model - Configure runtime and run the ocean model
#
# Arguments:
#   $1 - Phase: "nowcast" or "forecast"
################################################################################
execute_model() {
    local phase="${1:?phase argument required (nowcast|forecast)}"

    echo "=== execute_model: ${phase} (framework: ${OFS_FRAMEWORK}) ==="

    case "${OFS_FRAMEWORK}" in
        stofs) _stofs_execute_model "$phase" ;;
        comf)   _comf_execute_model "$phase" ;;
        adcirc) _adcirc_execute_model "$phase" ;;
        *)      echo "ERROR: Unknown framework: ${OFS_FRAMEWORK}"; return 1 ;;
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
        comf)   _comf_archive_outputs "$phase" ;;
        adcirc) _adcirc_archive_outputs "$phase" ;;
        *)      echo "ERROR: Unknown framework: ${OFS_FRAMEWORK}"; return 1 ;;
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

    # Nudging files (different naming convention) — skip for barotropic (no T/S)
    if [ "${BAROTROPIC:-false}" != "true" ]; then
        [ -f "$FIXstofs3d/${RUN}_tem_nudge.gr3" ] && ln -sf "$FIXstofs3d/${RUN}_tem_nudge.gr3" "$DATA/TEM_nudge.gr3"
        [ -f "$FIXstofs3d/${RUN}_sal_nudge.gr3" ] && ln -sf "$FIXstofs3d/${RUN}_sal_nudge.gr3" "$DATA/SAL_nudge.gr3"
    fi
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
        cp -p "${COMOUTrerun}/${RUN}.${cycle}.gfs.air.nc" "$DATA/sflux/sflux_air_1.1.nc"
    [ -s "${COMOUTrerun}/${RUN}.${cycle}.gfs.prc.nc" ] && \
        cp -p "${COMOUTrerun}/${RUN}.${cycle}.gfs.prc.nc" "$DATA/sflux/sflux_prc_1.1.nc"
    [ -s "${COMOUTrerun}/${RUN}.${cycle}.gfs.rad.nc" ] && \
        cp -p "${COMOUTrerun}/${RUN}.${cycle}.gfs.rad.nc" "$DATA/sflux/sflux_rad_1.1.nc"

    # HRRR atmospheric forcing (sflux stack 2 — optional)
    [ -s "${COMOUTrerun}/${RUN}.${cycle}.hrrr.air.nc" ] && \
        cp -p "${COMOUTrerun}/${RUN}.${cycle}.hrrr.air.nc" "$DATA/sflux/sflux_air_2.1.nc"
    [ -s "${COMOUTrerun}/${RUN}.${cycle}.hrrr.prc.nc" ] && \
        cp -p "${COMOUTrerun}/${RUN}.${cycle}.hrrr.prc.nc" "$DATA/sflux/sflux_prc_2.1.nc"
    [ -s "${COMOUTrerun}/${RUN}.${cycle}.hrrr.rad.nc" ] && \
        cp -p "${COMOUTrerun}/${RUN}.${cycle}.hrrr.rad.nc" "$DATA/sflux/sflux_rad_2.1.nc"

    # sflux_inputs.txt
    [ -s "$FIXstofs3d/${RUN}_sflux_inputs.txt" ] && \
        cp -p "$FIXstofs3d/${RUN}_sflux_inputs.txt" "$DATA/sflux/sflux_inputs.txt"

    # RTOFS OBC time-history files
    # Barotropic mode: only stage elev2D (SSH), skip T/S/velocity 3D OBC
    if [ "${BAROTROPIC:-false}" = "true" ]; then
        local obc_pairs=("elev2dth.nc:elev2D.th.nc")
    else
        local obc_pairs=("elev2dth.nc:elev2D.th.nc" "tem3dth.nc:TEM_3D.th.nc" "sal3dth.nc:SAL_3D.th.nc" "uv3dth.nc:uv3D.th.nc")
    fi
    for pair in "${obc_pairs[@]}"; do
        local src="${pair%%:*}" dst="${pair##*:}"
        [ -s "${COMOUTrerun}/${RUN}.${cycle}.${src}" ] && \
            cp -p "${COMOUTrerun}/${RUN}.${cycle}.${src}" "$DATA/${dst}"
    done

    # RTOFS nudging files — skip for barotropic (no T/S)
    if [ "${BAROTROPIC:-false}" != "true" ]; then
        local nudge_pairs=("temnu.nc:TEM_nu.nc" "salnu.nc:SAL_nu.nc")
        for pair in "${nudge_pairs[@]}"; do
            local src="${pair%%:*}" dst="${pair##*:}"
            [ -s "${COMOUTrerun}/${RUN}.${cycle}.${src}" ] && \
                cp -p "${COMOUTrerun}/${RUN}.${cycle}.${src}" "$DATA/${dst}"
        done
    fi

    echo "STOFS file staging complete for ${phase}"
}


_stofs_prepare_restart() {
    local phase=$1

    if [ "$phase" = "forecast" ]; then
        # Forecast: obtain combined hotstart, swap to forecast param.nml,
        # and set ihot=2 for hot restart
        echo "Preparing forecast restart..."

        cd $DATA

        # Priority 1: Combined hotstart from COMOUT (split-job mode)
        # The nowcast job archives a combined hotstart here via archive_outputs.
        local fn_hotstart_com="${COMOUT}/${RUN}.${cycle}.hotstart.stofs3d.nc"
        if [ -s "$fn_hotstart_com" ]; then
            echo "Found combined hotstart in COMOUT: $fn_hotstart_com"
            cp -p "$fn_hotstart_com" "$DATA/hotstart.nc"

            # Restore SCHISM output state files from nowcast archive.
            # SCHISM reads these on ihot=2 restart — empty files cause EOF errors.
            mkdir -p $DATA/outputs
            local restart_dir="${COMOUT}/${RUN}.${cycle}.restart_outputs"
            if [ -d "$restart_dir" ]; then
                echo "Restoring SCHISM output state files from $restart_dir"
                for f in mirror.out flux.out staout_1 staout_2 staout_3 staout_4 \
                         staout_5 staout_6 staout_7 staout_8 staout_9; do
                    [ -f "$restart_dir/$f" ] && cp -p "$restart_dir/$f" "$DATA/outputs/"
                done
            else
                echo "WARNING: restart_outputs dir not found: $restart_dir, creating empty files"
                touch $DATA/outputs/mirror.out
                touch $DATA/outputs/flux.out
                for i in 1 2 3 4 5 6 7 8 9; do
                    [ ! -f "$DATA/outputs/staout_${i}" ] && touch "$DATA/outputs/staout_${i}"
                done
            fi

        # Priority 2: Local combine (combined-job mode, same $DATA)
        elif [ -d "$DATA/outputs" ] && ls $DATA/outputs/hotstart_000000_*.nc &>/dev/null 2>&1; then
            echo "Combining distributed hotstart locally (combined-job mode)"
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
        else
            echo "ERROR: No hotstart available for forecast"
            echo "  Checked COMOUT: $fn_hotstart_com"
            echo "  Checked local:  $DATA/outputs/hotstart_000000_*.nc"
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

        # Clean nowcast output files but keep hotstart.nc (only relevant in combined mode)
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

    # Nowcast: find hotstart/restart and copy to $DATA/hotstart.nc
    echo "Searching for restart/hotstart file..."

    local fn_restart_rerun="${COMOUTrerun}/${RUN}.${cycle}.restart.nc"
    local found=0

    # Priority 1: Check if prep already placed restart.nc in COMOUTrerun
    if [ -s "$fn_restart_rerun" ]; then
        echo "Found restart from prep: $fn_restart_rerun"
        cp -p "$fn_restart_rerun" "$DATA/hotstart.nc"
        found=1
    fi

    # Priority 2: Search previous cycle hotstart in COMINstofs (0-4 days back)
    if [ $found -eq 0 ]; then
        local days=(0 1 2 3 4)
        for k in "${days[@]}"; do
            local date_k=$(date -d "${PDYHH_NCAST_BEGIN:0:8} ${k} days ago" +%Y%m%d)
            local fn_hotstart="${COMINstofs}/${RUN}.${date_k}/${RUN}.${cycle}.hotstart.stofs3d.nc"

            if [ -s "$fn_hotstart" ]; then
                echo "Found hotstart: $fn_hotstart"
                cp -p "$fn_hotstart" "$DATA/hotstart.nc"
                found=1
                break
            else
                echo "Not found: $fn_hotstart"
            fi
        done
    fi

    # Priority 3: Coldstart file from fix/
    if [ $found -eq 0 ]; then
        local fn_coldstart="${FIXstofs3d}/stofs_3d_atl_restart_coldstart.nc"
        if [ -s "$fn_coldstart" ]; then
            echo "Using coldstart file: $fn_coldstart"
            cp -p "$fn_coldstart" "$DATA/hotstart.nc"
        else
            echo "WARNING: No valid hotstart or coldstart file found"
            return 1
        fi
    fi

    echo "hotstart.nc staged in $DATA ($(ls -lh $DATA/hotstart.nc 2>/dev/null | awk '{print $5}'))"
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
    local nscribes=${NSCRIBES:-8}
    local executable="${EXECstofs3d}/${RUN}_pschism"
    # Fallback: stofs_2d_atl uses the same SCHISM executable as stofs_3d_atl
    [ ! -x "${executable}" ] && executable="${EXECstofs3d}/stofs_3d_atl_pschism"
    [ ! -x "${executable}" ] && executable="${EXECstofs3d}/pschism_TVD-VL"

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
        # Archive nowcast log to COMOUT for monitoring
        echo "Archiving nowcast outputs to ${COMOUT}"
        [ -s "$DATA/${RUN}.${cycle}.nowcast.log" ] && \
            cp -p "$DATA/${RUN}.${cycle}.nowcast.log" "$COMOUT/"

        # Combine distributed hotstart files and archive to COMOUT
        # so an independent forecast job can retrieve them (split-job mode).
        # In combined mode this is harmless — the forecast prep will find
        # the archived file via COMOUT priority check before trying local combine.
        cd $DATA/outputs
        local latest_step=""
        for step in 576 288; do  # Common nowcast steps (rnday=1.0, dt=150)
            if ls hotstart_000000_${step}.nc &>/dev/null; then
                latest_step=$step
                break
            fi
        done

        if [ -n "$latest_step" ]; then
            local nfiles=$(ls hotstart_0?????_${latest_step}.nc 2>/dev/null | wc -l)
            echo "Combining ${nfiles} hotstart files at step ${latest_step}"
            ${EXECstofs3d}/stofs_3d_atl_combine_hotstart -i ${latest_step}
            local fn_combined="hotstart_it=${latest_step}.nc"
            if [ -s "$fn_combined" ]; then
                cp -p "$fn_combined" "${COMOUT}/${RUN}.${cycle}.hotstart.stofs3d.nc"
                echo "Combined hotstart archived: ${COMOUT}/${RUN}.${cycle}.hotstart.stofs3d.nc"
            else
                echo "WARNING: combine_hotstart ran but output not found: $fn_combined"
            fi
        else
            echo "WARNING: No distributed hotstart files found for archival"
        fi

        # Archive SCHISM output state files needed for ihot=2 restart.
        # In split-job mode the forecast has a fresh $DATA and SCHISM
        # reads these files on restart — empty files cause EOF errors.
        local restart_dir="${COMOUT}/${RUN}.${cycle}.restart_outputs"
        mkdir -p "$restart_dir"
        for f in mirror.out flux.out staout_1 staout_2 staout_3 staout_4 \
                 staout_5 staout_6 staout_7 staout_8 staout_9; do
            [ -f "$DATA/outputs/$f" ] && cp -p "$DATA/outputs/$f" "$restart_dir/"
        done
        echo "Archived SCHISM restart output files to $restart_dir"

        cd $DATA

    elif [ "$phase" = "forecast" ]; then
        # Forecast: archive final hotstart for next cycle
        echo "Archiving forecast outputs to ${COMOUT}"

        # Archive model log
        [ -s "$DATA/${RUN}.${cycle}.forecast.log" ] && \
            cp -p "$DATA/${RUN}.${cycle}.forecast.log" "$COMOUT/"

        # Archive staout_1 to COMOUT root for dynamic bias correction.
        # The next cycle's prep (dynamic_adjust) reads ${COMOUT_PREV}/staout_1
        # to calculate model-vs-observation bias.
        if [ -f "$DATA/outputs/staout_1" ] && [ -s "$DATA/outputs/staout_1" ]; then
            cp -p "$DATA/outputs/staout_1" "${COMOUT}/staout_1"
            echo "Archived staout_1 to ${COMOUT}/ for bias correction"
        fi

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

        # In split-job mode, the prep job (JNOS_OFS_PREP) writes critical
        # time variables to files in $COMOUT. When launch.sh runs with
        # "nowcast" (not "prep"), the time computation block is skipped.
        # We must recover these variables for nos_ofs_nowcast_forecast.sh.
        echo "Recovering prep-generated time variables from $COMOUT"
        if [ -s "$COMOUT/time_hotstart.${cycle}" ]; then
            read time_hotstart < "$COMOUT/time_hotstart.${cycle}"
            export time_hotstart
            echo "  time_hotstart=$time_hotstart"
        else
            echo "FATAL: $COMOUT/time_hotstart.${cycle} not found!"
            echo "The prep job (JNOS_OFS_PREP) must complete successfully before nowcast."
            echo "Check that the prep job ran and wrote time_hotstart to COMOUT."
            msg="FATAL: time_hotstart not found in COMOUT — prep job may have failed"
            postmsg "${jlogfile:-/dev/null}" "$msg"
            return 1
        fi
        if [ -s "$COMOUT/time_nowcastend.${cycle}" ]; then
            read time_nowcastend < "$COMOUT/time_nowcastend.${cycle}"
            export time_nowcastend
            echo "  time_nowcastend=$time_nowcastend"
        fi
        if [ -s "$COMOUT/time_forecastend.${cycle}" ]; then
            read time_forecastend < "$COMOUT/time_forecastend.${cycle}"
            export time_forecastend
            echo "  time_forecastend=$time_forecastend"
        fi
        if [ -s "$COMOUT/base_date.${cycle}" ]; then
            read BASE_DATE < "$COMOUT/base_date.${cycle}"
            export BASE_DATE
            echo "  BASE_DATE=$BASE_DATE"
        fi

    elif [ "$phase" = "forecast" ]; then
        # In split-job mode, the forecast has its own $DATA and needs
        # to re-run launch.sh to stage grid/forcing files and find the
        # nowcast restart in COM (sets INI_FILE_FORECAST, etc.)
        echo "COMF forecast staging — re-running launch.sh for independent job"
        . $USHnos/nos_ofs_launch.sh $OFS nowcast
        export pgm="$USHnos/nos_ofs_launch.sh $OFS nowcast (forecast staging)"
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

        # Recover prep-generated time variables (same as nowcast above)
        echo "Recovering prep-generated time variables from $COMOUT"
        if [ -s "$COMOUT/time_hotstart.${cycle}" ]; then
            read time_hotstart < "$COMOUT/time_hotstart.${cycle}"
            export time_hotstart
            echo "  time_hotstart=$time_hotstart"
        fi
        if [ -s "$COMOUT/time_nowcastend.${cycle}" ]; then
            read time_nowcastend < "$COMOUT/time_nowcastend.${cycle}"
            export time_nowcastend
        fi
        if [ -s "$COMOUT/time_forecastend.${cycle}" ]; then
            read time_forecastend < "$COMOUT/time_forecastend.${cycle}"
            export time_forecastend
        fi
        if [ -s "$COMOUT/base_date.${cycle}" ]; then
            read BASE_DATE < "$COMOUT/base_date.${cycle}"
            export BASE_DATE
        fi
    fi

    # Stage UFS-Coastal DATM artifacts from prep job (if USE_DATM is enabled)
    if [ "${USE_DATM:-false}" == "true" ] || [ "${USE_DATM:-0}" == "1" ]; then
        echo "Staging UFS-Coastal DATM artifacts from $COMOUT"
        local DATM_DIR=${DATM_INPUT_DIR:-INPUT}
        mkdir -p ${DATA}/${DATM_DIR}
        mkdir -p ${DATA}/RESTART
        mkdir -p ${DATA}/outputs

        # Stage DATM forcing and mesh files
        local datm_dir="${COMOUT}/${RUN}.${cycle}.datm_input"
        if [ -d "$datm_dir" ]; then
            cp -p ${datm_dir}/*.nc ${DATA}/${DATM_DIR}/ 2>/dev/null || true
            echo "  Staged DATM files to ${DATM_DIR}/ from $datm_dir"
        else
            echo "WARNING: DATM input directory not found: $datm_dir"
        fi

        # Stage UFS config files
        for f in model_configure datm_in datm.streams ufs.configure; do
            local src="${COMOUT}/${RUN}.${cycle}.${f}"
            if [ -s "$src" ]; then
                cp -p "$src" "${DATA}/${f}"
                echo "  Staged: ${f}"
            else
                echo "WARNING: UFS config not found: $src"
            fi
        done

        # Stage fd_ufs.yaml (NUOPC field dictionary) and noahmptable.tbl
        for f in fd_ufs.yaml noahmptable.tbl; do
            if [ -s "${FIXofs}/${f}" ]; then
                cp -p "${FIXofs}/${f}" "${DATA}/${f}"
                echo "  Staged: ${f}"
            elif [ -s "${COMOUT}/${RUN}.${cycle}.${f}" ]; then
                cp -p "${COMOUT}/${RUN}.${cycle}.${f}" "${DATA}/${f}"
                echo "  Staged: ${f} (from COMOUT)"
            fi
        done

        # Stage UFS-Coastal executable to run directory (actual run pattern)
        local UFS_EXEC_NAME=${UFS_EXEC_NAME:-fv3_coastalS.exe}
        if [ ! -x "${DATA}/${UFS_EXEC_NAME}" ]; then
            if [ -x "${EXECnos:-}/${UFS_EXEC_NAME}" ]; then
                cp -p "${EXECnos}/${UFS_EXEC_NAME}" "${DATA}/${UFS_EXEC_NAME}"
                echo "  Staged executable: ${UFS_EXEC_NAME}"
            fi
        fi

        # Patch UFS configs for nowcast vs forecast
        # - nhours_fcst / stop_n: simulation length
        # - start_type: always startup (DATM has no restart files)
        # - start_year/month/day/hour: actual simulation start time
        #
        # CRITICAL: For forecast with ihot=2, the start time MUST match the
        # nowcast start time (time_hotstart). The hotstart step number is
        # relative to the original start time. If we change start_hour from
        # 06Z to 12Z, SCHISM interprets step 180 as 12Z+6h=18Z instead of
        # the correct 06Z+6h=12Z, causing a time mismatch with DATM forcing
        # and immediate CFL violation.
        local start_type="startup"
        # Both nowcast and forecast use the same start time (time_hotstart)
        local sim_start=${time_hotstart:-$($NDATE -${LEN_NOWCAST:-6} ${PDY}${cyc})}
        if [ "$phase" = "nowcast" ]; then
            local nhours=${LEN_NOWCAST:-6}
        else
            # Forecast total duration = nowcast + forecast hours from the
            # original start time, because ihot=2 resumes at the hotstart step
            local nhours=$(( ${LEN_NOWCAST:-6} + ${LEN_FORECAST:-48} ))
        fi

        # Extract date components from simulation start time
        local sim_yyyy=$(echo $sim_start | cut -c1-4)
        local sim_mm=$(echo $sim_start | cut -c5-6)
        local sim_dd=$(echo $sim_start | cut -c7-8)
        local sim_hh=$(echo $sim_start | cut -c9-10)

        echo "  Patching UFS configs for phase=$phase"
        echo "    nhours=$nhours, start_type=$start_type"
        echo "    sim_start=$sim_start (${sim_yyyy}-${sim_mm}-${sim_dd} ${sim_hh}Z)"

        if [ -s "${DATA}/model_configure" ]; then
            sed -i "s/nhours_fcst:.*/nhours_fcst:             ${nhours}/" ${DATA}/model_configure
            sed -i "s/start_year:.*/start_year:              ${sim_yyyy}/" ${DATA}/model_configure
            sed -i "s/start_month:.*/start_month:             ${sim_mm}/" ${DATA}/model_configure
            sed -i "s/start_day:.*/start_day:               ${sim_dd}/" ${DATA}/model_configure
            sed -i "s/start_hour:.*/start_hour:              ${sim_hh}/" ${DATA}/model_configure
        fi
        if [ -s "${DATA}/ufs.configure" ]; then
            sed -i "s/stop_n = .*/stop_n = ${nhours}/" ${DATA}/ufs.configure
            sed -i "s/start_type = .*/start_type = ${start_type}/" ${DATA}/ufs.configure
            # Update orb_iyear to match simulation year
            sed -i "s/orb_iyear = .*/orb_iyear = ${sim_yyyy}/" ${DATA}/ufs.configure
            sed -i "s/orb_iyear_align = .*/orb_iyear_align = ${sim_yyyy}/" ${DATA}/ufs.configure
        fi

        # SCHISM NUOPC cap requires param.nml (exact name) in $DATA.
        # nos_ofs_launch.sh copies ${RUNTIME_CTL} (e.g. secofs_ufs.param.nml)
        # to $DATA with its original prefixed name. We must:
        # 1. Copy it to param.nml
        # 2. Substitute template placeholders with actual runtime values
        if [ ! -s "${DATA}/param.nml" ] && [ -s "${DATA}/${RUNTIME_CTL}" ]; then
            cp -p "${DATA}/${RUNTIME_CTL}" "${DATA}/param.nml"
            echo "  Copied ${RUNTIME_CTL} -> param.nml"
        fi
        if [ -s "${DATA}/param.nml" ]; then
            local rnday=$(python3 -c "print(${nhours}/24.0)" 2>/dev/null || echo "0.25")
            local ihot_val=1
            if [ "$phase" = "forecast" ]; then
                ihot_val=2
            fi
            sed -i "s/rnday_value/${rnday}/" ${DATA}/param.nml
            # Also handle case where rnday already has a numeric value
            sed -i "s/^\(\s*rnday\s*=\s*\)[0-9.]*\(.*\)/\1${rnday}\2/" ${DATA}/param.nml
            sed -i "s/start_year_value/${sim_yyyy}/" ${DATA}/param.nml
            sed -i "s/start_month_value/${sim_mm#0}/" ${DATA}/param.nml
            sed -i "s/start_day_value/${sim_dd#0}/" ${DATA}/param.nml
            sed -i "s/start_hour_value/${sim_hh}/" ${DATA}/param.nml
            # Also handle case where start_hour already has a numeric value
            sed -i "s/^\(\s*start_hour\s*=\s*\)[0-9]*\(.*\)/\1${sim_hh#0}\2/" ${DATA}/param.nml
            sed -i "s/ihot = [0-9]*/ihot = ${ihot_val}/" ${DATA}/param.nml
            echo "  Patched param.nml: rnday=${rnday}, start=${sim_yyyy}-${sim_mm}-${sim_dd} ${sim_hh}Z, ihot=${ihot_val}"
        fi

        # SCHISM expects bare-name input files (hgrid.gr3, vgrid.in, etc.)
        # but nos_ofs_launch.sh copies them with prefixed names (e.g., secofs_ufs.hgrid.gr3).
        # The old COMF pathway (nos_ofs_nowcast_forecast.sh) re-copies from FIXofs with bare names.
        # For UFS-Coastal, we bypass that script, so we must create the bare-name copies here.
        if [ "${OCEAN_MODEL:-}" = "SCHISM" ] || [ "${OCEAN_MODEL:-}" = "schism" ]; then
            echo "  Staging SCHISM bare-name input files..."

            # Grid files: copy from FIXofs with bare SCHISM names
            [ -s "${FIXofs}/${PREFIXNOS}.hgrid.gr3" ] && \
                cp -p ${FIXofs}/${PREFIXNOS}.hgrid.gr3 ${DATA}/hgrid.gr3
            [ -s "${FIXofs}/${VGRID_CTL}" ] && \
                cp -p ${FIXofs}/${VGRID_CTL} ${DATA}/vgrid.in
            [ -s "${FIXofs}/${VGRID_NU_CTL:-${PREFIXNOS}.vgrid.nu.in}" ] && \
                cp -p ${FIXofs}/${VGRID_NU_CTL:-${PREFIXNOS}.vgrid.nu.in} ${DATA}/vgrid_nu.in
            [ -s "${FIXofs}/${STA_OUT_CTL}" ] && \
                cp -p ${FIXofs}/${STA_OUT_CTL} ${DATA}/station.in

            # Optional grid property files
            for bare in shapiro.gr3 diffmax.gr3 diffmin.gr3 watertype.gr3 \
                        windrot_geo2proj.gr3 albedo.gr3 rough.gr3 \
                        SAL_nudge.gr3 TEM_nudge.gr3 elev.ic hgrid.ll; do
                if [ -s "${FIXofs}/${PREFIXNOS}.${bare}" ]; then
                    cp -p ${FIXofs}/${PREFIXNOS}.${bare} ${DATA}/${bare}
                fi
            done

            # SCHISM property files (tvd.prop, fluxflag.prop)
            # NOTE: partition.prop is NOT copied because UFS-Coastal uses a different
            # SCHISM PET count (1080) than standalone (1200). SCHISM will use METIS
            # for internal partitioning if partition.prop is not present.
            for prop in tvd.prop fluxflag.prop; do
                if [ -s "${FIXofs}/${PREFIXNOS}.${prop}" ]; then
                    cp -p ${FIXofs}/${PREFIXNOS}.${prop} ${DATA}/${prop}
                fi
            done

            # bctides.in from COMOUT (prep-generated with correct nodal factors)
            if [ "$phase" = "nowcast" ]; then
                local bctides_file="${BCTIDES_IN:-${PREFIXNOS}.bctides.in}.nowcast"
            else
                local bctides_file="${BCTIDES_IN:-${PREFIXNOS}.bctides.in}.forecast"
            fi
            if [ -s "${COMOUT}/${bctides_file}" ]; then
                cp -p ${COMOUT}/${bctides_file} ${DATA}/bctides.in
                echo "  Staged bctides.in from ${bctides_file}"
            elif [ -s "${FIXofs}/${HC_FILE_OBC:-${PREFIXNOS}.bctides.in}" ]; then
                cp -p ${FIXofs}/${HC_FILE_OBC:-${PREFIXNOS}.bctides.in} ${DATA}/bctides.in
                echo "  WARNING: Using FIXofs bctides.in (prep-generated not found)"
            fi

            # Hotstart/initial condition file
            if [ "$phase" = "nowcast" ]; then
                if [ -n "${INI_FILE_NOWCAST:-}" ] && [ -s "${COMOUT}/${INI_FILE_NOWCAST}" ]; then
                    cp -p ${COMOUT}/${INI_FILE_NOWCAST} ${DATA}/hotstart.nc
                    echo "  Staged hotstart.nc from ${INI_FILE_NOWCAST}"
                elif [ -n "${INI_FILE:-}" ] && [ -s "${INI_FILE}" ]; then
                    cp -p ${INI_FILE} ${DATA}/hotstart.nc
                    echo "  Staged hotstart.nc from ${INI_FILE}"
                else
                    echo "  WARNING: No hotstart.nc found (ihot=${ihot_val})"
                fi
            elif [ "$phase" = "forecast" ]; then
                # Forecast uses nowcast restart as hotstart (ihot=2)
                if [ -n "${INI_FILE_FORECAST:-}" ] && [ -s "${COMOUT}/${INI_FILE_FORECAST}" ]; then
                    cp -p ${COMOUT}/${INI_FILE_FORECAST} ${DATA}/hotstart.nc
                    echo "  Staged hotstart.nc from ${INI_FILE_FORECAST}"
                elif [ -n "${RST_OUT_NOWCAST:-}" ] && [ -s "${COMOUT}/${RST_OUT_NOWCAST}" ]; then
                    cp -p ${COMOUT}/${RST_OUT_NOWCAST} ${DATA}/hotstart.nc
                    echo "  Staged hotstart.nc from ${RST_OUT_NOWCAST}"
                else
                    echo "  WARNING: No forecast hotstart.nc found"
                fi
                # Set ihot=2 for hot restart from nowcast
                if [ -s "${DATA}/param.nml" ]; then
                    sed -i "s/ihot = 1/ihot = 2/" ${DATA}/param.nml
                    echo "  Set ihot=2 in param.nml for forecast"
                fi
            fi

            # NWM river forcing from COMOUT
            if [ -n "${NWM_SOURCE_SINK_NOW:-}" ] && [ "$phase" = "nowcast" ]; then
                if [ -s "${COMOUT}/${NWM_SOURCE_SINK_NOW}" ]; then
                    cp -p ${COMOUT}/${NWM_SOURCE_SINK_NOW} ${DATA}/
                    tar xf ${DATA}/${NWM_SOURCE_SINK_NOW} -C ${DATA}/ 2>/dev/null || true
                    echo "  Staged NWM river forcing (nowcast)"
                fi
            elif [ -n "${NWM_SOURCE_SINK_FORE:-}" ] && [ "$phase" = "forecast" ]; then
                if [ -s "${COMOUT}/${NWM_SOURCE_SINK_FORE}" ]; then
                    cp -p ${COMOUT}/${NWM_SOURCE_SINK_FORE} ${DATA}/
                    tar xf ${DATA}/${NWM_SOURCE_SINK_FORE} -C ${DATA}/ 2>/dev/null || true
                    echo "  Staged NWM river forcing (forecast)"
                fi
            fi

            # Validate NWM river files exist (if_source=1 in param.nml requires these)
            if [ ! -s "${DATA}/source_sink.in" ]; then
                echo "WARNING: source_sink.in not found after NWM tar extraction"
                echo "  NWM tar may be empty — check prep job river forcing generation"
                echo "  SCHISM will abort if param.nml has if_source=1"
                # Fallback: try to get source_sink.in from FIX directory
                if [ -s "${FIXofs}/${PREFIXNOS}.source_sink.in" ]; then
                    cp -p ${FIXofs}/${PREFIXNOS}.source_sink.in ${DATA}/source_sink.in
                    echo "  Fallback: staged source_sink.in from FIXofs"
                fi
            fi
            for rivf in vsource.th vsink.th msource.th; do
                if [ ! -s "${DATA}/${rivf}" ]; then
                    echo "WARNING: ${rivf} not found after NWM tar extraction"
                    if [ -s "${FIXofs}/${PREFIXNOS}.${rivf}" ]; then
                        cp -p ${FIXofs}/${PREFIXNOS}.${rivf} ${DATA}/${rivf}
                        echo "  Fallback: staged ${rivf} from FIXofs"
                    fi
                fi
            done

            # OBC forcing from COMOUT (contains TEM_nu.nc, SAL_nu.nc,
            # TEM_3D.th.nc, SAL_3D.th.nc, elev2D.th.nc, uv3D.th.nc)
            if [ -n "${OBC_FORCING_FILE:-}" ]; then
                if [ -s "${COMOUT}/${OBC_FORCING_FILE}" ]; then
                    cp -p ${COMOUT}/${OBC_FORCING_FILE} ${DATA}/
                    tar xf ${DATA}/${OBC_FORCING_FILE} -C ${DATA}/
                    echo "  Staged OBC forcing from ${OBC_FORCING_FILE}"
                else
                    echo "WARNING: OBC forcing tar not found: ${COMOUT}/${OBC_FORCING_FILE}"
                fi
            fi

            # River forcing tar from COMOUT (contains schism_flux.th,
            # schism_temp.th, schism_salt.th for boundary flux forcing)
            if [ -n "${RIVER_FORCING_FILE:-}" ]; then
                if [ -s "${COMOUT}/${RIVER_FORCING_FILE}" ]; then
                    cp -p ${COMOUT}/${RIVER_FORCING_FILE} ${DATA}/
                    tar xf ${DATA}/${RIVER_FORCING_FILE} -C ${DATA}/
                    echo "  Staged river forcing from ${RIVER_FORCING_FILE}"
                else
                    echo "WARNING: River forcing tar not found: ${COMOUT}/${RIVER_FORCING_FILE}"
                fi
            fi

            # SCHISM river forcing file renames (COMF convention)
            [ -s "${DATA}/schism_temp.th" ] && cp -p ${DATA}/schism_temp.th ${DATA}/TEM_1.th
            [ -s "${DATA}/schism_flux.th" ] && cp -p ${DATA}/schism_flux.th ${DATA}/flux.th
            [ -s "${DATA}/schism_salt.th" ] && cp -p ${DATA}/schism_salt.th ${DATA}/salt.th

            # sflux_inputs.txt (not needed for DATM, but SCHISM may check)
            if [ -s "${FIXofs}/${PREFIXNOS}.sflux_inputs.txt" ]; then
                mkdir -p ${DATA}/sflux
                cp -p ${FIXofs}/${PREFIXNOS}.sflux_inputs.txt ${DATA}/sflux/sflux_inputs.txt
            fi

            # hgrid.gr3 must also be in outputs/ directory
            mkdir -p ${DATA}/outputs
            [ -s "${DATA}/hgrid.gr3" ] && cp -p ${DATA}/hgrid.gr3 ${DATA}/outputs/

            # Forecast needs restart_outputs from nowcast (ihot=2 requires
            # flux.out, mirror.out, staout_* in outputs/ directory)
            if [ "$phase" = "forecast" ]; then
                local restart_dir="${COMOUT}/${RUN}.${cycle}.restart_outputs"
                if [ -d "$restart_dir" ]; then
                    for f in mirror.out flux.out staout_1 staout_2 staout_3 staout_4 \
                             staout_5 staout_6 staout_7 staout_8 staout_9; do
                        [ -f "${restart_dir}/${f}" ] && cp -p ${restart_dir}/${f} ${DATA}/outputs/
                    done
                    echo "  Staged restart_outputs from ${restart_dir}"
                fi
                # Ensure all required output files exist (even if empty)
                # SCHISM ihot=2 opens these files regardless of content
                for f in mirror.out flux.out; do
                    [ ! -f "${DATA}/outputs/${f}" ] && touch "${DATA}/outputs/${f}"
                done
                for i in $(seq 1 9); do
                    [ ! -f "$DATA/outputs/staout_${i}" ] && touch "$DATA/outputs/staout_${i}"
                done
            fi

            echo "  SCHISM bare-name file staging complete"
        fi

        echo "  UFS-Coastal staging complete"
    fi
}


_comf_prepare_restart() {
    local phase=$1
    # COMF restart handling is done inside nos_ofs_launch.sh (nowcast)
    # and the forecast uses INI_FILE_FORECAST = RST_OUT_NOWCAST
    echo "COMF restart handled by nos_ofs_launch.sh"
}


_comf_execute_model() {
    local phase=$1

    # UFS-Coastal: dispatch to coupled DATM+SCHISM execution
    if [ "${USE_DATM:-false}" == "true" ] || [ "${USE_DATM:-0}" == "1" ]; then
        _comf_execute_ufs_coastal "$phase"
        return $?
    fi

    # Verify critical time variables exist before running model
    if [ -z "${time_hotstart:-}" ]; then
        echo "FATAL: time_hotstart is not set!"
        echo "The prep job (JNOS_OFS_PREP) must write time_hotstart to COMOUT."
        echo "Check $COMOUT/time_hotstart.${cycle}"
        return 1
    fi

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

    # nos_ofs_nowcast_forecast.sh has a bug where it does 'exit' (code 0)
    # on fatal errors like missing time_hotstart. Double-check that the
    # model actually ran by looking for expected output files.
    if [ $err -ne 0 ]; then
        echo "Execution of $pgm did not complete normally, FATAL ERROR!"
        echo "Execution of $pgm did not complete normally, FATAL ERROR!" >> $cormslogfile 2>/dev/null || true
        msg=" Execution of $pgm did not complete normally, FATAL ERROR!"
        postmsg "$jlogfile" "$msg" 2>/dev/null || true
        postmsg "$nosjlogfile" "$msg" 2>/dev/null || true
        return $err
    else
        echo "Execution of $pgm completed normally" >> $cormslogfile 2>/dev/null || true
        echo "Execution of $pgm completed normally"
        msg=" Execution of $pgm completed normally"
        postmsg "$jlogfile" "$msg" 2>/dev/null || true
        postmsg "$nosjlogfile" "$msg" 2>/dev/null || true
    fi
}


# =============================================================================
# UFS-Coastal Execution (DATM + SCHISM coupled via NUOPC/CMEPS)
# =============================================================================
_comf_execute_ufs_coastal() {
    local phase=$1

    echo "============================================"
    echo "UFS-Coastal Execution ($phase)"
    echo "============================================"

    # Validate UFS config files
    for f in model_configure datm_in datm.streams ufs.configure; do
        if [ ! -s "${DATA}/${f}" ]; then
            echo "FATAL: Missing UFS config file: ${DATA}/${f}"
            return 1
        fi
    done

    # Validate DATM forcing directory (INPUT/ or era5/ or configurable)
    local DATM_DIR=${DATM_INPUT_DIR:-INPUT}
    if [ ! -d "${DATA}/${DATM_DIR}" ] || [ -z "$(ls ${DATA}/${DATM_DIR}/*.nc 2>/dev/null)" ]; then
        echo "FATAL: No DATM forcing files in ${DATA}/${DATM_DIR}/"
        return 1
    fi

    echo "UFS config files:"
    for f in model_configure datm_in datm.streams ufs.configure; do
        echo "  $(wc -l < ${DATA}/${f}) lines: ${f}"
    done
    echo "DATM forcing files:"
    ls -lh ${DATA}/${DATM_DIR}/*.nc 2>/dev/null

    # Validate fd_ufs.yaml (NUOPC field dictionary)
    if [ ! -s "${DATA}/fd_ufs.yaml" ]; then
        echo "WARNING: fd_ufs.yaml not found in ${DATA}/"
    fi

    # Determine executable
    local UFS_EXEC=""
    if [ -x "${DATA}/fv3_coastalS.exe" ]; then
        UFS_EXEC="${DATA}/fv3_coastalS.exe"
    elif [ -x "${EXECnos:-}/fv3_coastalS.exe" ]; then
        UFS_EXEC="${EXECnos}/fv3_coastalS.exe"
    elif [ -x "${EXECnos:-}/ufs_coastal" ]; then
        UFS_EXEC="${EXECnos}/ufs_coastal"
    elif [ -x "${EXECnos:-}/ufs_model" ]; then
        UFS_EXEC="${EXECnos}/ufs_model"
    else
        echo "FATAL: UFS-Coastal executable not found"
        echo "  Checked: ${DATA}/fv3_coastalS.exe"
        echo "  Checked: ${EXECnos:-}/fv3_coastalS.exe"
        echo "  Checked: ${EXECnos:-}/ufs_coastal"
        echo "  Checked: ${EXECnos:-}/ufs_model"
        return 1
    fi

    # Determine total MPI tasks and PPN
    local NTASKS=${TOTAL_TASKS:-1200}
    local PPN=${PPN:-120}

    echo "Executable: $UFS_EXEC"
    echo "Total MPI tasks: $NTASKS"
    echo "PPN: $PPN"
    echo "Phase: $phase"

    # Set UFS-Coastal runtime environment
    # Force OMP_NUM_THREADS=1 — Cray PBS can set it to ncpus (128) which
    # causes massive oversubscription with 120 MPI ranks per node
    export OMP_STACKSIZE=512M
    export OMP_NUM_THREADS=1
    export OMP_PLACES=cores
    export ESMF_RUNTIME_COMPLIANCECHECK=OFF:depth=4
    export ESMF_RUNTIME_PROFILE=ON
    export ESMF_RUNTIME_PROFILE_OUTPUT="SUMMARY"

    # Clear LD_PRELOAD — the COMF J-job sets it for standalone Fortran execs
    # (libnetcdff.so from system netcdf/4.7.4) but UFS-Coastal uses its own
    # hpc-stack libraries (netcdf-D/4.9.2) loaded via modules.fv3
    unset LD_PRELOAD 2>/dev/null || true

    # Run UFS-Coastal
    echo "Starting UFS-Coastal at: $(date)"
    echo "  mpiexec -n ${NTASKS} -ppn ${PPN} --cpu-bind core ${UFS_EXEC}"

    cd $DATA
    mpiexec -n ${NTASKS} -ppn ${PPN} --cpu-bind core ${UFS_EXEC}
    export err=$?

    echo "UFS-Coastal finished at: $(date) with exit code: $err"

    if [ $err -ne 0 ]; then
        echo "UFS-Coastal execution FAILED (rc=$err)"
        echo "UFS-Coastal $phase execution failed" >> $cormslogfile 2>/dev/null || true
        msg="UFS-Coastal $phase execution failed (rc=$err)"
        postmsg "${jlogfile:-/dev/null}" "$msg" 2>/dev/null || true
        return $err
    fi

    # Verify completion by checking for mirror.out in outputs/
    if [ -d "${DATA}/outputs" ] && [ -s "${DATA}/outputs/mirror.out" ]; then
        echo "UFS-Coastal $phase completed successfully (mirror.out found)"
    else
        echo "WARNING: mirror.out not found — UFS-Coastal may not have completed properly"
    fi

    # After nowcast: combine distributed hotstart files and archive for forecast
    if [ "$phase" = "nowcast" ] && [ -d "${DATA}/outputs" ]; then
        echo "Combining distributed hotstart files..."
        cd ${DATA}/outputs

        # Calculate the hotstart timestep (total nowcast steps)
        local dt_val=$(grep -m1 '^\s*dt\s*=' ${DATA}/param.nml | sed 's/.*=\s*//;s/[^0-9.]//g')
        local nhot_write_val=$(grep -m1 '^\s*nhot_write\s*=' ${DATA}/param.nml | sed 's/.*=\s*//;s/[^0-9]//g')
        local nsteps=${nhot_write_val:-180}
        echo "  Hotstart timestep: $nsteps (dt=${dt_val:-unknown})"

        # Run combine_hotstart7 executable
        local COMBINE_EXE="${EXECnos:-}/schism_combine_hotstart7.exe"
        if [ -x "$COMBINE_EXE" ]; then
            $COMBINE_EXE -i $nsteps
            local combine_err=$?
            if [ $combine_err -eq 0 ] && [ -s "hotstart_it=${nsteps}.nc" ]; then
                echo "  Hotstart combined successfully: hotstart_it=${nsteps}.nc"
                cp -p "hotstart_it=${nsteps}.nc" "${COMOUT}/${RST_OUT_NOWCAST:-${RUN}.${cycle}.${PDY}.rst.nowcast.nc}"
                echo "  Archived to ${COMOUT}/${RST_OUT_NOWCAST:-${RUN}.${cycle}.${PDY}.rst.nowcast.nc}"
            else
                echo "WARNING: combine_hotstart7 failed (rc=$combine_err) or output missing"
            fi
        else
            echo "WARNING: schism_combine_hotstart7.exe not found at $COMBINE_EXE"
            # Fallback: check if a combined hotstart already exists
            local combined=$(ls hotstart_it=*.nc 2>/dev/null | tail -1)
            if [ -n "$combined" ] && [ -s "$combined" ]; then
                cp -p "$combined" "${COMOUT}/${RST_OUT_NOWCAST:-${RUN}.${cycle}.${PDY}.rst.nowcast.nc}"
                echo "  Found pre-combined hotstart: $combined, archived to COMOUT"
            fi
        fi
        cd ${DATA}
    fi

    echo "UFS-Coastal $phase execution completed normally"
    msg="UFS-Coastal $phase execution completed normally"
    postmsg "${jlogfile:-/dev/null}" "$msg" 2>/dev/null || true
    return 0
}


_comf_archive_outputs() {
    local phase=$1

    export pgm="$USHnos/nos_ofs_archive.sh $phase"
    $USHnos/nos_ofs_archive.sh $phase
    export err=$?

    if [ $err -ne 0 ]; then
        echo "Execution of $pgm did not complete normally, FATAL ERROR!"
        echo "Execution of $pgm did not complete normally, FATAL ERROR!" >> $cormslogfile 2>/dev/null || true
        msg=" Execution of $pgm did not complete normally, FATAL ERROR!"
        postmsg "$jlogfile" "$msg" 2>/dev/null || true
        postmsg "$nosjlogfile" "$msg" 2>/dev/null || true
        return $err
    else
        echo "Execution of $pgm completed normally" >> $cormslogfile 2>/dev/null || true
        echo "Execution of $pgm completed normally"
        msg=" Execution of $pgm completed normally"
        postmsg "$jlogfile" "$msg" 2>/dev/null || true
        postmsg "$nosjlogfile" "$msg" 2>/dev/null || true
    fi

    # Archive SCHISM output state files needed for ihot=2 restart in split-job mode.
    # Without real staout/mirror/flux files the forecast (or ensemble) crashes with
    # "end-of-file during read" on the empty placeholders.
    # Note: nos_ofs_nowcast_forecast.sh renames $DATA/outputs → $DATA/outputs_nowcast
    # after the nowcast completes, so check both locations.
    if [ "$phase" = "nowcast" ]; then
        local outputs_dir=""
        if [ -d "$DATA/outputs" ]; then
            outputs_dir="$DATA/outputs"
        elif [ -d "$DATA/outputs_nowcast" ]; then
            outputs_dir="$DATA/outputs_nowcast"
        fi
        if [ -n "$outputs_dir" ]; then
            local restart_dir="${COMOUT}/${RUN}.${cycle}.restart_outputs"
            mkdir -p "$restart_dir"
            for f in mirror.out flux.out staout_1 staout_2 staout_3 staout_4 \
                     staout_5 staout_6 staout_7 staout_8 staout_9; do
                [ -f "$outputs_dir/$f" ] && cp -p "$outputs_dir/$f" "$restart_dir/"
            done
            echo "Archived SCHISM restart output files from $outputs_dir to $restart_dir"
        else
            echo "WARNING: Neither $DATA/outputs nor $DATA/outputs_nowcast found, skipping restart_outputs archive"
        fi
    fi
}


################################################################################
#
#  ADCIRC INTERNAL FUNCTIONS (STOFS-2D-GLO)
#  Multi-phase workflow:
#    Nowcast:  tide-only (NWS=0) → surface+tide (NWS=12)
#    Forecast: tide-only → surface+tide × 2 periods (fcst1: 0-120h, fcst2: 120-180h)
#
#  Each sub-phase is a complete ADCIRC run with its own fort.15.
#  Between sub-phases, outputs are saved to COMOUTrerun and the working
#  directory is cleaned for the next run.
#
################################################################################

#------------------------------------------------------------------------------
# Helper: Generate fort.15 from template using nod_equi tidal factors
#   Uses: time_now (from calling scope), FIXstofs2d, RUN, ${RUN}_nod_equi
#   Args: template rnday ihot nout touts toutf nhstar nhsinc [winc]
#------------------------------------------------------------------------------
_adcirc_generate_fort15() {
    local template=$1 rnday_val=$2 ihot_val=$3 nout_val=$4
    local touts_val=$5 toutf_val=$6 nhstar_val=$7 nhsinc_val=$8
    local winc_val=${9:-}

    cpreq $FIXstofs2d/${RUN}_${template} ${RUN}_fort.15

    # Read tidal nodal equilibrium values
    local hh dd mm yyyy
    local _con fft1 facet1 fft2 facet2 fft3 facet3 fft4 facet4
    local fft5 facet5 fft6 facet6 fft7 facet7 fft8 facet8
    {
        read hh dd mm yyyy
        read _con fft1 facet1
        read _con fft2 facet2
        read _con fft3 facet3
        read _con fft4 facet4
        read _con fft5 facet5
        read _con fft6 facet6
        read _con fft7 facet7
        read _con fft8 facet8
    } < "${RUN}_nod_equi"

    mm=$(printf "%02d" $mm)
    dd=$(printf "%02d" $dd)
    hh=$(printf "%02d" $hh)

    # Optional winc sed argument (only for surface forcing templates)
    local winc_sed=""
    if [ -n "$winc_val" ]; then
        winc_sed="-e s/winc/${winc_val}/g"
    fi

    sed -e "s/cycle/${time_now}/g" \
        -e "s/ihot/${ihot_val}/g" \
        -e "s/rnday/${rnday_val}/g" \
        -e "s/fft1/${fft1}/g" -e "s/facet1/${facet1}/g" \
        -e "s/fft2/${fft2}/g" -e "s/facet2/${facet2}/g" \
        -e "s/fft3/${fft3}/g" -e "s/facet3/${facet3}/g" \
        -e "s/fft4/${fft4}/g" -e "s/facet4/${facet4}/g" \
        -e "s/fft5/${fft5}/g" -e "s/facet5/${facet5}/g" \
        -e "s/fft6/${fft6}/g" -e "s/facet6/${facet6}/g" \
        -e "s/fft7/${fft7}/g" -e "s/facet7/${facet7}/g" \
        -e "s/fft8/${fft8}/g" -e "s/facet8/${facet8}/g" \
        -e "s/nout/${nout_val}/g" \
        -e "s/touts/${touts_val}/g" -e "s/toutf/${toutf_val}/g" \
        -e "s/nhstar/${nhstar_val}/g" -e "s/nhsinc/${nhsinc_val}/g" \
        -e "s/hh/${hh}/g" -e "s/dd/${dd}/g" \
        -e "s/mm/${mm}/g" -e "s/yyyy/${yyyy}/g" \
        $winc_sed \
        ${RUN}_fort.15 | \
    sed -n "/DUMMY/!p" > fort.15

    rm -f ${RUN}_fort.15

    if [ ! -f fort.15 ]; then
        echo "FATAL: fort.15 generation failed from template $template"
        return 1
    fi
    echo "Generated fort.15 from $template (rnday=$rnday_val, ihot=$ihot_val)"
}

#------------------------------------------------------------------------------
# Helper: Run adcprep (partmesh + prepall or prep15 only)
#   Uses: ncpu, RUN, pgmout, COMGES from calling scope
#------------------------------------------------------------------------------
_adcirc_run_adcprep() {
    if [ ! -s ${RUN}_${ncpu}.tar.gz ]; then
        echo "Running full adcprep (partmesh + prepall, ncpu=$ncpu)..."
        mpiexec -n 1 -ppn 1 adcprep --np $ncpu --partmesh >> ${pgmout:-/dev/null} 2>errfile
        export err=$?
        if [ $err -ne 0 ]; then echo "FATAL: adcprep --partmesh failed"; return 1; fi
        mpiexec -n 1 -ppn 1 adcprep --np $ncpu --prepall >> ${pgmout:-/dev/null} 2>errfile
        export err=$?
        if [ $err -ne 0 ]; then echo "FATAL: adcprep --prepall failed"; return 1; fi
        filelist="partmesh.txt PE*/fort.14 PE*/fort.18 PE*/fort.13 PE*/fort.24 PE*/elev_stat.151 PE*/vel_stat.151"
        tar cvzf ${RUN}_${ncpu}.tar.gz $filelist
        cpfs ${RUN}_${ncpu}.tar.gz $COMGES/.
        echo "Created and archived partmesh tar for $ncpu CPUs"
    else
        echo "Running adcprep --prep15 (pre-decomposed grid available)..."
        mpiexec -n 1 -ppn 1 adcprep --np $ncpu --prep15 >> ${pgmout:-/dev/null} 2>errfile
        export err=$?
        if [ $err -ne 0 ]; then echo "FATAL: adcprep --prep15 failed"; return 1; fi
    fi
}

#------------------------------------------------------------------------------
# Helper: Check ADCIRC completion status
#   Args: subphase_name (for logging)
#------------------------------------------------------------------------------
_adcirc_check_completion() {
    local subphase=${1:-""}
    if [[ -n $(grep 'ADCIRC stopping' adcirc.err 2>/dev/null) || \
          -n $(grep 'ADCIRC Terminating' adcirc.err 2>/dev/null) ]]; then
        echo "FATAL: ADCIRC crashed during ${subphase}"
        return 1
    fi
    echo "ADCIRC ${subphase} completed normally"
    return 0
}

#------------------------------------------------------------------------------
# Helper: Clean ADCIRC output files between sub-phases
#------------------------------------------------------------------------------
_adcirc_clean_subphase() {
    rm -f fort.61.nc fort.62.nc fort.63.nc fort.64.nc
    rm -f fort.67.nc fort.68.nc fort.15
    rm -f maxele.63.nc maxvel.63.nc maxwvel.63.nc
    rm -f adcirc.err
    rm -f fort.221.nc fort.222.nc fort.225.nc
}


_adcirc_stage_files() {
    local phase=$1

    cd $DATA

    # Link ADCIRC static grid and attribute files
    ln -sf $FIXstofs2d/${RUN}_attr       fort.13
    ln -sf $FIXstofs2d/${RUN}_grid       fort.14
    ln -sf $FIXstofs2d/${RUN}_body       fort.24
    ln -sf $FIXstofs2d/${RUN}_rotm       fort.rotm
    ln -sf $FIXstofs2d/${RUN}_elev_stat  elev_stat.151
    ln -sf $FIXstofs2d/${RUN}_elev_stat  vel_stat.151

    # Copy tidal nodal equilibrium file
    if [ -f $COMGES/${RUN}_nod_equi ]; then
        cpreq $COMGES/${RUN}_nod_equi .
        echo "Copied nod_equi from $COMGES"
    else
        echo "WARNING: ${RUN}_nod_equi not found in $COMGES"
    fi

    # Extract pre-decomposed grid
    export ncpu=${NCPU:-${TOTAL_TASKS:-960}}
    if [ -f $COMGES/${RUN}_${ncpu}.tar.gz ]; then
        cpreq $COMGES/${RUN}_${ncpu}.tar.gz .
        tar xvzf ${RUN}_${ncpu}.tar.gz
        export err=$?
        if [ $err -ne 0 ]; then echo "WARNING: Failed to extract partmesh tar"; fi
    else
        echo "INFO: No pre-decomposed grid tar (will run adcprep --prepall)"
    fi

    # Copy fort.15 templates from FIX
    for tmpl in tide.15 surf.15; do
        if [ -f $FIXstofs2d/${RUN}_${tmpl} ]; then
            cp -p $FIXstofs2d/${RUN}_${tmpl} $DATA/${RUN}_${tmpl}
        fi
    done

    # Link meteorological control file (for surface runs)
    if [ -f $FIXstofs2d/${RUN}_met ]; then
        ln -sf $FIXstofs2d/${RUN}_met fort.22
    fi

    echo "ADCIRC file staging complete for ${phase}"
}


_adcirc_prepare_restart() {
    local phase=$1

    cd $DATA

    if [ "$phase" = "nowcast" ]; then
        # Verify prerequisites for nowcast
        if [ ! -f ${RUN}_nod_equi ]; then
            echo "FATAL: nod_equi not found — cannot generate fort.15"
            return 1
        fi
        echo "ADCIRC nowcast prerequisites verified"

    elif [ "$phase" = "forecast" ]; then
        # Verify nowcast outputs are available for forecast continuation
        local missing=0
        for f in hottime.out tide.61.nc tide.63.nc retime.out \
                 surf.61.nc surf.62.nc surf.63.nc surf.64.nc; do
            if [ ! -f $COMOUTrerun/${RUN}_${f} ]; then
                echo "WARNING: Missing $COMOUTrerun/${RUN}_${f}"
                missing=1
            fi
        done
        # Check for hotstart from tide nowcast
        if [ ! -f $COMOUT/${RUN}.${cycle}.hotstart ] && \
           [ ! -f $COMOUTrerun/${RUN}_tide.68.nc ]; then
            echo "FATAL: No hotstart from nowcast for forecast"
            return 1
        fi
        # Check for restart from surf nowcast
        if [ ! -f $COMOUT/${RUN}.${cycle}.restart ] && \
           [ ! -f $COMOUTrerun/${RUN}_surf.68.nc ]; then
            echo "FATAL: No restart from nowcast for forecast"
            return 1
        fi
        if [ $missing -eq 1 ]; then
            echo "WARNING: Some forecast prerequisites missing — may cause errors"
        fi
        echo "ADCIRC forecast prerequisites verified"
    fi
}


_adcirc_execute_model() {
    local phase=$1

    cd $DATA

    # Common parameters
    local wndh=3 nowh=6 lsth=${ADCIRC_LSTH:-180}
    export ncpu=${NCPU:-${TOTAL_TASKS:-960}}
    export date=$PDY
    export YMDH=${PDY}${cyc}
    export nback=${nback:-20}

    # time_now is NOT local — used by _adcirc_generate_fort15
    time_now=$YMDH
    local time_end=$($NDATE $lsth $YMDH)

    if [ "$phase" = "nowcast" ]; then
        echo "=== ADCIRC Nowcast: tide-only → surface+tide ==="

        # ---------------------------------------------------------------
        # Sub-phase 1/2: Tide Nowcast (NWS=0, no writers)
        # ---------------------------------------------------------------
        echo "--- Sub-phase 1/2: Tide Nowcast ---"

        ${USHstofs2d}/${RUN}_multistart.sh "hotstart" >> ${pgmout:-/dev/null} 2>errfile
        export err=$?
        if [ $err -ne 0 ]; then
            echo "FATAL: multistart.sh hotstart search failed"
            return 1
        fi
        local ymdh=$(head ${RUN}_multistart.out | awk '{ print $1 }')
        rm -f ${RUN}_multistart.out

        local time_beg=$ymdh
        local hdate=$(echo $ymdh | cut -c1-8)
        local hcyc=$(echo $ymdh | cut -c9-10)
        local hdir=$COM/${RUN}.${hdate}
        local hfile=${RUN}.t${hcyc}z.hotstart

        if [ -d $hdir ] && [ -f $hdir/$hfile ]; then
            cpreq $hdir/$hfile ${time_beg}.hotstart
        else
            echo "FATAL: Hotstart not found at $hdir/$hfile"
            return 1
        fi

        # Determine ihot from hotstart time (fort.67/68 alternation)
        ncdump -v time ${time_beg}.hotstart > hotstart.out
        export err=$?
        if [ $err -ne 0 ]; then echo "FATAL: ncdump failed on hotstart"; return 1; fi
        local time_hotstart=$(grep 'time = [0-9]' hotstart.out | awk '{print $3}')
        rm -f hotstart.out

        local ihot
        if [ $(expr $(echo "scale=0; $time_hotstart/($wndh*3600)" | bc) % 2) = 0 ]; then
            ihot=368; cpreq ${time_beg}.hotstart fort.68.nc
        else
            ihot=367; cpreq ${time_beg}.hotstart fort.67.nc
        fi

        # Calculate time parameters
        local ncsth=$($NHOUR $time_now $time_beg)
        local ncstd=$(echo "scale=5; ($time_hotstart+$ncsth*3600)/86400" | bc)
        local rnday=$(echo "scale=5; $ncstd+$lsth/24" | bc)
        local nout=-3
        local touts=$(echo "scale=5; $rnday-($nowh+$lsth)/24" | bc)
        local toutf=$rnday
        local nhstar=3
        local nhsinc=1800
        local time_ncst=$(echo "scale=0; $ncstd*86400" | bc)
        local hotstart_count=0
        time_hotstart=$(printf "%.0f" "$time_ncst")
        echo $hotstart_count $time_hotstart $touts $toutf $DATA > hottime.out
        cpfs hottime.out $COMOUTrerun/${RUN}_hottime.out

        # Generate fort.15, run adcprep, run padcirc
        _adcirc_generate_fort15 "tide.15" "$ncstd" "$ihot" "$nout" \
            "$touts" "$toutf" "$nhstar" "$nhsinc"
        if [ $? -ne 0 ]; then return 1; fi

        _adcirc_run_adcprep
        if [ $? -ne 0 ]; then return 1; fi

        echo "Running padcirc for tide nowcast (ncpu=$ncpu)..."
        mpiexec -n $ncpu -ppn ${PPN} --cpu-bind core padcirc \
            >> ${pgmout:-/dev/null} 2>adcirc.err
        export err=$?
        _adcirc_check_completion "tide nowcast"
        if [ $? -ne 0 ]; then return 1; fi

        # Save tide hotstart and outputs
        if [ $(expr $(echo "scale=0; $time_ncst/($wndh*3600)" | bc) % 2) = 0 ]; then
            cpfs fort.68.nc ${time_now}.hotstart
        else
            cpfs fort.67.nc ${time_now}.hotstart
        fi
        cpfs fort.61.nc     $COMOUTrerun/${RUN}_tide.61.nc
        cpfs fort.63.nc     $COMOUTrerun/${RUN}_tide.63.nc
        cpfs ${time_now}.hotstart  $COMOUT/${RUN}.${cycle}.hotstart
        echo "Tide nowcast outputs saved"

        _adcirc_clean_subphase

        # ---------------------------------------------------------------
        # Sub-phase 2/2: Surface Nowcast (NWS=12, with writers)
        # ---------------------------------------------------------------
        echo "--- Sub-phase 2/2: Surface Nowcast ---"

        ${USHstofs2d}/${RUN}_multistart.sh "restart" >> ${pgmout:-/dev/null} 2>errfile
        export err=$?
        if [ $err -ne 0 ]; then
            echo "FATAL: multistart.sh restart search failed"
            return 1
        fi
        ymdh=$(head ${RUN}_multistart.out | awk '{ print $1 }')
        rm -f ${RUN}_multistart.out

        time_beg=$ymdh
        local rdate=$(echo $ymdh | cut -c1-8)
        local rcyc=$(echo $ymdh | cut -c9-10)
        local rdir=$COM/${RUN}.${rdate}
        local rfile=${RUN}.t${rcyc}z.restart

        if [ -d $rdir ] && [ -f $rdir/$rfile ]; then
            cpreq $rdir/$rfile ${time_beg}.restart
        else
            echo "FATAL: Restart not found at $rdir/$rfile"
            return 1
        fi

        # Link GFS nowcast forcing
        if [ -f $COMOUTrerun/${RUN}_ncst.221.nc ]; then
            ln -sf ${COMOUTrerun}/${RUN}_ncst.221.nc fort.221.nc
            ln -sf ${COMOUTrerun}/${RUN}_ncst.222.nc fort.222.nc
            ln -sf ${COMOUTrerun}/${RUN}_ncst.225.nc fort.225.nc
        else
            echo "FATAL: GFS nowcast forcing not found in COMOUTrerun"
            return 1
        fi

        # Link fort.22 (met control) for surface run
        ln -sf $FIXstofs2d/${RUN}_met fort.22

        # Determine ihot from restart time
        ncdump -v time ${time_beg}.restart > restart.out
        export err=$?
        if [ $err -ne 0 ]; then echo "FATAL: ncdump failed on restart"; return 1; fi
        local time_restart=$(grep 'time = [0-9]' restart.out | awk '{print $3}')
        rm -f restart.out

        if [ $(expr $(echo "scale=0; $time_restart/($wndh*3600)" | bc) % 2) = 0 ]; then
            ihot=368; cpreq ${time_beg}.restart fort.68.nc
        else
            ihot=367; cpreq ${time_beg}.restart fort.67.nc
        fi

        # Time calculations for surface nowcast
        ncsth=$($NHOUR $time_now $time_beg)
        ncstd=$(echo "scale=5; ($time_restart+$ncsth*3600)/86400" | bc)
        rnday=$(echo "scale=5; $ncstd+$lsth/24" | bc)
        local winc=3600
        nout=-3
        touts=$(echo "scale=5; $rnday-($nowh+$lsth)/24" | bc)
        toutf=$rnday
        nhstar=3
        nhsinc=1800
        time_ncst=$(echo "scale=0; $ncstd*86400" | bc)
        local restart_count=0
        time_restart=$(printf "%.0f" "$time_ncst")
        echo $restart_count $time_restart $touts $toutf $DATA > retime.out
        cpfs retime.out $COMOUTrerun/${RUN}_retime.out

        _adcirc_generate_fort15 "surf.15" "$ncstd" "$ihot" "$nout" \
            "$touts" "$toutf" "$nhstar" "$nhsinc" "$winc"
        if [ $? -ne 0 ]; then return 1; fi

        # adcprep --prep15 (grid already decomposed from tide sub-phase)
        mpiexec -n 1 -ppn 1 adcprep --np $ncpu --prep15 \
            >> ${pgmout:-/dev/null} 2>errfile
        export err=$?
        if [ $err -ne 0 ]; then echo "FATAL: adcprep --prep15 failed"; return 1; fi

        echo "Running padcirc for surface nowcast (ncpu=${TOT_NCPU:-$ncpu}, writers=${NUM_WRITERS:-6})..."
        mpiexec -n ${TOT_NCPU:-$ncpu} -ppn ${PPN} --cpu-bind core \
            padcirc -W ${NUM_WRITERS:-6} >> ${pgmout:-/dev/null} 2>adcirc.err
        export err=$?
        _adcirc_check_completion "surface nowcast"
        if [ $? -ne 0 ]; then return 1; fi

        # Save surf restart and outputs
        if [ $(expr $(echo "scale=0; $time_ncst/($wndh*3600)" | bc) % 2) = 0 ]; then
            cpfs fort.68.nc ${time_now}.restart
        else
            cpfs fort.67.nc ${time_now}.restart
        fi
        cpfs fort.61.nc     $COMOUTrerun/${RUN}_surf.61.nc
        cpfs fort.62.nc     $COMOUTrerun/${RUN}_surf.62.nc
        cpfs fort.63.nc     $COMOUTrerun/${RUN}_surf.63.nc
        cpfs fort.64.nc     $COMOUTrerun/${RUN}_surf.64.nc
        cpfs maxele.63.nc   $COMOUTrerun/${RUN}_maxele.63.nc
        cpfs maxvel.63.nc   $COMOUTrerun/${RUN}_maxvel.63.nc
        cpfs maxwvel.63.nc  $COMOUTrerun/${RUN}_maxwvel.63.nc
        cpfs ${time_now}.restart  $COMOUT/${RUN}.${cycle}.restart
        echo "Surface nowcast outputs saved"

        echo "=== ADCIRC Nowcast complete ==="

    elif [ "$phase" = "forecast" ]; then
        echo "=== ADCIRC Forecast: 4 sub-phases (tide+surf x fcst1+fcst2) ==="

        local ihot fcstd

        # ---------------------------------------------------------------
        # Sub-phase 1/4: Tide Forecast1 (0-120h, NWS=0)
        # ---------------------------------------------------------------
        echo "--- Sub-phase 1/4: Tide Forecast1 ---"

        if [ -f $COMOUTrerun/${RUN}_tide.68.nc ]; then
            cpreq $COMOUTrerun/${RUN}_tide.68.nc ${time_now}.hotstart
        else
            cpreq $COMOUT/${RUN}.${cycle}.hotstart ${time_now}.hotstart
        fi
        cpreq $COMOUTrerun/${RUN}_tide.61.nc fort.61.nc
        cpreq $COMOUTrerun/${RUN}_tide.63.nc fort.63.nc

        cpreq $COMOUTrerun/${RUN}_hottime.out hottime.out
        local hotstart_count=$(awk '{print $1}' hottime.out)
        local time_hotstart=$(awk '{print $2}' hottime.out)
        local touts=$(awk '{print $3}' hottime.out)
        local toutf=$(awk '{print $4}' hottime.out)

        if [ $(expr $(echo "scale=0; $time_hotstart/($nowh*3600)" | bc) % 2) = 0 ]; then
            ihot=368; cpreq ${time_now}.hotstart fort.68.nc
        else
            ihot=367; cpreq ${time_now}.hotstart fort.67.nc
        fi

        fcstd=$(echo "scale=5; ($time_hotstart)/86400" | bc)
        local rnday_hotstart=$(echo "scale=5; $fcstd+$lsth/36" | bc)
        local nout=3
        local nhstar=3
        local nhsinc=3600
        local time_fcst=$(echo "scale=0; $rnday_hotstart*86400" | bc)
        hotstart_count=$((hotstart_count + 1))
        time_hotstart=$(printf "%.0f" "$time_fcst")
        echo $hotstart_count $time_hotstart $touts $toutf $DATA > hottime.out
        cpfs hottime.out $COMOUTrerun/${RUN}_hottime.out

        _adcirc_generate_fort15 "tide.15" "$rnday_hotstart" "$ihot" "$nout" \
            "$touts" "$toutf" "$nhstar" "$nhsinc"
        if [ $? -ne 0 ]; then return 1; fi

        mpiexec -n 1 -ppn 1 adcprep --np $ncpu --prep15 \
            >> ${pgmout:-/dev/null} 2>errfile
        export err=$?; if [ $err -ne 0 ]; then return 1; fi

        echo "Running padcirc for tide forecast1..."
        mpiexec -n $ncpu -ppn ${PPN} --cpu-bind core padcirc \
            >> ${pgmout:-/dev/null} 2>adcirc.err
        export err=$?
        _adcirc_check_completion "tide forecast1"
        if [ $? -ne 0 ]; then return 1; fi

        if [ $(expr $(echo "scale=0; $time_fcst/($nowh*3600)" | bc) % 2) = 0 ]; then
            cpfs fort.68.nc ${RUN}.tide.68.nc
        else
            cpfs fort.67.nc ${RUN}.tide.68.nc
        fi
        cpfs fort.61.nc        $COMOUTrerun/${RUN}_tide.61.nc
        cpfs fort.63.nc        $COMOUTrerun/${RUN}_tide.63.nc
        cpfs ${RUN}.tide.68.nc $COMOUTrerun/${RUN}_tide.68.nc
        echo "Tide forecast1 outputs saved"

        _adcirc_clean_subphase

        # ---------------------------------------------------------------
        # Sub-phase 2/4: Surface Forecast1 (0-120h, NWS=12, with writers)
        # ---------------------------------------------------------------
        echo "--- Sub-phase 2/4: Surface Forecast1 ---"

        if [ -f $COMOUTrerun/${RUN}_surf.68.nc ]; then
            cpreq $COMOUTrerun/${RUN}_surf.68.nc ${time_now}.restart
        else
            cpreq $COMOUT/${RUN}.${cycle}.restart ${time_now}.restart
        fi
        cpreq $COMOUTrerun/${RUN}_surf.61.nc    fort.61.nc
        cpreq $COMOUTrerun/${RUN}_surf.62.nc    fort.62.nc
        cpreq $COMOUTrerun/${RUN}_surf.63.nc    fort.63.nc
        cpreq $COMOUTrerun/${RUN}_surf.64.nc    fort.64.nc
        cpreq $COMOUTrerun/${RUN}_maxele.63.nc  maxele.63.nc
        cpreq $COMOUTrerun/${RUN}_maxvel.63.nc  maxvel.63.nc
        cpreq $COMOUTrerun/${RUN}_maxwvel.63.nc maxwvel.63.nc

        if [ -f $COMOUTrerun/${RUN}_fcst1.221.nc ]; then
            ln -sf ${COMOUTrerun}/${RUN}_fcst1.221.nc fort.221.nc
            ln -sf ${COMOUTrerun}/${RUN}_fcst1.222.nc fort.222.nc
            ln -sf ${COMOUTrerun}/${RUN}_fcst1.225.nc fort.225.nc
        else
            echo "FATAL: GFS forecast1 forcing not found"
            return 1
        fi
        ln -sf $FIXstofs2d/${RUN}_met fort.22

        cpreq $COMOUTrerun/${RUN}_retime.out retime.out
        local restart_count=$(awk '{print $1}' retime.out)
        local time_restart=$(awk '{print $2}' retime.out)
        touts=$(awk '{print $3}' retime.out)
        toutf=$(awk '{print $4}' retime.out)

        if [ $(expr $(echo "scale=0; $time_restart/($nowh*3600)" | bc) % 2) = 0 ]; then
            ihot=368; cpreq ${time_now}.restart fort.68.nc
        else
            ihot=367; cpreq ${time_now}.restart fort.67.nc
        fi

        local winc=3600
        fcstd=$(echo "scale=5; $time_restart/86400" | bc)
        local rnday_restart=$(echo "scale=5; $fcstd+$lsth/36" | bc)
        nout=3; nhstar=3; nhsinc=3600
        time_fcst=$(echo "scale=5; $rnday_restart*86400" | bc)
        restart_count=$((restart_count + 1))
        time_restart=$(printf "%.0f" "$time_fcst")
        echo $restart_count $time_restart $touts $toutf $DATA > retime.out
        cpfs retime.out $COMOUTrerun/${RUN}_retime.out

        _adcirc_generate_fort15 "surf.15" "$rnday_restart" "$ihot" "$nout" \
            "$touts" "$toutf" "$nhstar" "$nhsinc" "$winc"
        if [ $? -ne 0 ]; then return 1; fi

        mpiexec -n 1 -ppn 1 adcprep --np $ncpu --prep15 \
            >> ${pgmout:-/dev/null} 2>errfile
        export err=$?; if [ $err -ne 0 ]; then return 1; fi

        echo "Running padcirc for surface forecast1 (ncpu=${TOT_NCPU:-$ncpu}, writers=${NUM_WRITERS:-6})..."
        mpiexec -n ${TOT_NCPU:-$ncpu} -ppn ${PPN} --cpu-bind core \
            padcirc -W ${NUM_WRITERS:-6} >> ${pgmout:-/dev/null} 2>adcirc.err
        export err=$?
        _adcirc_check_completion "surface forecast1"
        if [ $? -ne 0 ]; then return 1; fi

        if [ $(expr $(echo "scale=0; $time_restart/($nowh*3600)" | bc) % 2) = 0 ]; then
            cpfs fort.68.nc ${RUN}.surf.68.nc
        else
            cpfs fort.67.nc ${RUN}.surf.68.nc
        fi
        cpfs fort.61.nc        $COMOUTrerun/${RUN}_surf.61.nc
        cpfs fort.62.nc        $COMOUTrerun/${RUN}_surf.62.nc
        cpfs fort.63.nc        $COMOUTrerun/${RUN}_surf.63.nc
        cpfs fort.64.nc        $COMOUTrerun/${RUN}_surf.64.nc
        cpfs maxele.63.nc      $COMOUTrerun/${RUN}_maxele.63.nc
        cpfs maxvel.63.nc      $COMOUTrerun/${RUN}_maxvel.63.nc
        cpfs maxwvel.63.nc     $COMOUTrerun/${RUN}_maxwvel.63.nc
        cpfs ${RUN}.surf.68.nc $COMOUTrerun/${RUN}_surf.68.nc
        echo "Surface forecast1 outputs saved"

        _adcirc_clean_subphase

        # ---------------------------------------------------------------
        # Sub-phase 3/4: Tide Forecast2 (120-180h, NWS=0)
        # ---------------------------------------------------------------
        echo "--- Sub-phase 3/4: Tide Forecast2 ---"

        if [ -f $COMOUTrerun/${RUN}_tide.68.nc ]; then
            cpreq $COMOUTrerun/${RUN}_tide.68.nc ${time_now}.hotstart
        else
            cpreq $COMOUT/${RUN}.${cycle}.hotstart ${time_now}.hotstart
        fi
        cpreq $COMOUTrerun/${RUN}_tide.61.nc fort.61.nc
        cpreq $COMOUTrerun/${RUN}_tide.63.nc fort.63.nc

        cpreq $COMOUTrerun/${RUN}_hottime.out hottime.out
        hotstart_count=$(awk '{print $1}' hottime.out)
        time_hotstart=$(awk '{print $2}' hottime.out)
        touts=$(awk '{print $3}' hottime.out)
        toutf=$(awk '{print $4}' hottime.out)

        if [ $(expr $(echo "scale=0; $time_hotstart/($nowh*3600)" | bc) % 2) = 0 ]; then
            ihot=368; cpreq ${time_now}.hotstart fort.68.nc
        else
            ihot=367; cpreq ${time_now}.hotstart fort.67.nc
        fi

        fcstd=$(echo "scale=5; ($time_hotstart)/86400" | bc)
        rnday_hotstart=$(echo "scale=5; $fcstd+$lsth/72" | bc)
        nout=3; nhstar=3; nhsinc=7200
        time_fcst=$(echo "scale=0; $rnday_hotstart*86400" | bc)
        hotstart_count=$((hotstart_count + 1))
        time_hotstart=$(printf "%.0f" "$time_fcst")
        echo $hotstart_count $time_hotstart $touts $toutf $DATA > hottime.out
        cpfs hottime.out $COMOUTrerun/${RUN}_hottime.out

        _adcirc_generate_fort15 "tide.15" "$rnday_hotstart" "$ihot" "$nout" \
            "$touts" "$toutf" "$nhstar" "$nhsinc"
        if [ $? -ne 0 ]; then return 1; fi

        mpiexec -n 1 -ppn 1 adcprep --np $ncpu --prep15 \
            >> ${pgmout:-/dev/null} 2>errfile
        export err=$?; if [ $err -ne 0 ]; then return 1; fi

        echo "Running padcirc for tide forecast2..."
        mpiexec -n $ncpu -ppn ${PPN} --cpu-bind core padcirc \
            >> ${pgmout:-/dev/null} 2>adcirc.err
        export err=$?
        _adcirc_check_completion "tide forecast2"
        if [ $? -ne 0 ]; then return 1; fi

        if [ $(expr $(echo "scale=0; $time_fcst/($nowh*3600)" | bc) % 2) = 0 ]; then
            cpfs fort.68.nc ${RUN}.tide.68.nc
        else
            cpfs fort.67.nc ${RUN}.tide.68.nc
        fi
        cpfs fort.61.nc        $COMOUTrerun/${RUN}_tide.61.nc
        cpfs fort.63.nc        $COMOUTrerun/${RUN}_tide.63.nc
        cpfs ${RUN}.tide.68.nc $COMOUTrerun/${RUN}_tide.68.nc
        # Final tide products to COMOUT
        if [ "${SENDCOM:-YES}" = YES ]; then
            cpfs fort.61.nc  $COMOUT/${RUN}.${cycle}.points.htp.nc
            cpfs fort.63.nc  $COMOUT/${RUN}.${cycle}.fields.htp.nc
        fi
        echo "Tide forecast2 outputs saved"

        _adcirc_clean_subphase

        # ---------------------------------------------------------------
        # Sub-phase 4/4: Surface Forecast2 (120-180h, NWS=12, no writers)
        # ---------------------------------------------------------------
        echo "--- Sub-phase 4/4: Surface Forecast2 ---"

        if [ -f $COMOUTrerun/${RUN}_surf.68.nc ]; then
            cpreq $COMOUTrerun/${RUN}_surf.68.nc ${time_now}.restart
        else
            cpreq $COMOUT/${RUN}.${cycle}.restart ${time_now}.restart
        fi
        cpreq $COMOUTrerun/${RUN}_surf.61.nc    fort.61.nc
        cpreq $COMOUTrerun/${RUN}_surf.62.nc    fort.62.nc
        cpreq $COMOUTrerun/${RUN}_surf.63.nc    fort.63.nc
        cpreq $COMOUTrerun/${RUN}_surf.64.nc    fort.64.nc
        cpreq $COMOUTrerun/${RUN}_maxele.63.nc  maxele.63.nc
        cpreq $COMOUTrerun/${RUN}_maxvel.63.nc  maxvel.63.nc
        cpreq $COMOUTrerun/${RUN}_maxwvel.63.nc maxwvel.63.nc

        # Link GFS forecast2 forcing (3-hourly)
        if [ -f $COMOUTrerun/${RUN}_fcst2.221.nc ]; then
            ln -sf ${COMOUTrerun}/${RUN}_fcst2.221.nc fort.221.nc
            ln -sf ${COMOUTrerun}/${RUN}_fcst2.222.nc fort.222.nc
            ln -sf ${COMOUTrerun}/${RUN}_fcst2.225.nc fort.225.nc
        else
            echo "FATAL: GFS forecast2 forcing not found"
            return 1
        fi
        ln -sf $FIXstofs2d/${RUN}_met fort.22

        cpreq $COMOUTrerun/${RUN}_retime.out retime.out
        restart_count=$(awk '{print $1}' retime.out)
        time_restart=$(awk '{print $2}' retime.out)
        touts=$(awk '{print $3}' retime.out)
        toutf=$(awk '{print $4}' retime.out)

        if [ $(expr $(echo "scale=0; $time_restart/($nowh*3600)" | bc) % 2) = 0 ]; then
            ihot=368; cpreq ${time_now}.restart fort.68.nc
        else
            ihot=367; cpreq ${time_now}.restart fort.67.nc
        fi

        winc=10800  # 3-hourly for forecast2
        fcstd=$(echo "scale=5; $time_restart/86400" | bc)
        rnday_restart=$(echo "scale=5; $fcstd+$lsth/72" | bc)
        nout=3; nhstar=3; nhsinc=7200
        time_fcst=$(echo "scale=5; $rnday_restart*86400" | bc)
        restart_count=$((restart_count + 1))
        time_restart=$(printf "%.0f" "$time_fcst")
        echo $restart_count $time_restart $touts $toutf $DATA > retime.out
        cpfs retime.out $COMOUTrerun/${RUN}_retime.out

        _adcirc_generate_fort15 "surf.15" "$rnday_restart" "$ihot" "$nout" \
            "$touts" "$toutf" "$nhstar" "$nhsinc" "$winc"
        if [ $? -ne 0 ]; then return 1; fi

        mpiexec -n 1 -ppn 1 adcprep --np $ncpu --prep15 \
            >> ${pgmout:-/dev/null} 2>errfile
        export err=$?; if [ $err -ne 0 ]; then return 1; fi

        # Forecast2 surf runs WITHOUT dedicated writers (matches operational)
        echo "Running padcirc for surface forecast2 (ncpu=$ncpu, no writers)..."
        mpiexec -n $ncpu -ppn ${PPN} --cpu-bind core padcirc \
            >> ${pgmout:-/dev/null} 2>adcirc.err
        export err=$?
        _adcirc_check_completion "surface forecast2"
        if [ $? -ne 0 ]; then return 1; fi

        if [ $(expr $(echo "scale=0; $time_restart/($nowh*3600)" | bc) % 2) = 0 ]; then
            cpfs fort.68.nc ${RUN}.surf.68.nc
        else
            cpfs fort.67.nc ${RUN}.surf.68.nc
        fi
        cpfs fort.61.nc    $COMOUTrerun/${RUN}_surf.61.nc
        cpfs fort.62.nc    $COMOUTrerun/${RUN}_surf.62.nc
        cpfs fort.63.nc    $COMOUTrerun/${RUN}_surf.63.nc
        cpfs fort.64.nc    $COMOUTrerun/${RUN}_surf.64.nc
        cpfs maxele.63.nc  $COMOUTrerun/${RUN}_maxele.63.nc
        cpfs maxvel.63.nc  $COMOUTrerun/${RUN}_maxvel.63.nc
        cpfs maxwvel.63.nc $COMOUTrerun/${RUN}_maxwvel.63.nc
        cpfs ${RUN}.surf.68.nc $COMOUTrerun/${RUN}_surf.68.nc

        # Final surface products to COMOUT
        if [ "${SENDCOM:-YES}" = YES ]; then
            cpfs fort.61.nc    $COMOUT/${RUN}.${cycle}.points.cwl.nc
            cpfs fort.61.nc    $COMOUT/${RUN}.${cycle}.points.cwl.noanomaly.nc
            cpfs fort.62.nc    $COMOUT/${RUN}.${cycle}.points.cwl.vel.nc
            cpfs fort.63.nc    $COMOUT/${RUN}.${cycle}.fields.cwl.nc
            cpfs fort.63.nc    $COMOUT/${RUN}.${cycle}.fields.cwl.noanomaly.nc
            cpfs fort.64.nc    $COMOUT/${RUN}.${cycle}.fields.cwl.vel.nc
            cpfs maxele.63.nc  $COMOUT/${RUN}.${cycle}.fields.cwl.maxele.nc
            cpfs maxele.63.nc  $COMOUT/${RUN}.${cycle}.fields.cwl.maxele.noanomaly.nc
            cpfs maxvel.63.nc  $COMOUT/${RUN}.${cycle}.fields.cwl.maxvel.nc
            cpfs maxwvel.63.nc $COMOUT/${RUN}.${cycle}.fields.cwl.maxwvel.nc
        fi
        echo "Surface forecast2 outputs saved"

        echo "=== ADCIRC Forecast complete ==="
    fi
}


_adcirc_archive_outputs() {
    local phase=$1

    # Final output archival is handled within execute_model for ADCIRC
    # since each sub-phase saves its outputs immediately.
    if [ "$phase" = "nowcast" ]; then
        echo "ADCIRC nowcast outputs archived (hotstart+restart to COMOUT)"
    elif [ "$phase" = "forecast" ]; then
        echo "ADCIRC forecast outputs archived (htp+cwl to COMOUT)"
        # DBN alerts for downstream processing
        if [ "${SENDDBN:-NO}" = YES ] && [ -n "${DBNROOT:-}" ]; then
            $DBNROOT/bin/dbn_alert MODEL ${DBN_ALERT_TYPE:-STOFS} $job \
                $COMOUT/${RUN}.${cycle}.points.htp.nc 2>/dev/null || true
            $DBNROOT/bin/dbn_alert MODEL ${DBN_ALERT_TYPE:-STOFS} $job \
                $COMOUT/${RUN}.${cycle}.fields.htp.nc 2>/dev/null || true
            $DBNROOT/bin/dbn_alert MODEL ${DBN_ALERT_TYPE:-STOFS} $job \
                $COMOUT/${RUN}.${cycle}.points.cwl.nc 2>/dev/null || true
            $DBNROOT/bin/dbn_alert MODEL ${DBN_ALERT_TYPE:-STOFS} $job \
                $COMOUT/${RUN}.${cycle}.fields.cwl.nc 2>/dev/null || true
        fi
    fi
}
