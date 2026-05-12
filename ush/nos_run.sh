#!/bin/bash
################################################################################
#  Name: nos_run.sh
#
#  Purpose:
#    Consolidated SECOFS-UFS-Coastal SCHISM run library.  Replaces the
#    previous 3-file flow:
#      - nos_run.sh (2145 lines, generic 4-step API + framework
#        dispatchers + STOFS/COMF/ADCIRC implementations)
#      - nosofs/nos_run.sh (898 lines, legacy COMF stager — was
#        dot-sourced from _comf_stage_files)
#    by inlining only the SECOFS-UFS-relevant code paths and dropping all
#    STOFS-3D-ATL, STOFS-2D-ATL/GLO ADCIRC, ROMS, FVCOM, SELFE, NEMO branches.
#
#    nos_config.sh (YAML loader) is NOT consolidated here — it remains
#    a separate dependency sourced by the J-job before nos_run.sh.
#
#  Scope:
#    - SECOFS-UFS-Coastal only (OCEAN_MODEL=SCHISM, USE_DATM=true)
#    - 4-step public API (J-job contract, unchanged)
#    - Byte-identical staging behavior to the legacy COMF path
#
#  Public API:
#      source ${USHnos}/nos_run.sh
#      stage_model_files <phase>     # nowcast | forecast
#      prepare_restart   <phase>
#      execute_model     <phase>
#      archive_outputs   <phase>
#
#  Required environment variables (set by the J-job and YAML loader):
#      OFS, RUN, PREFIXNOS, PDY, cyc, cycle, DATA, COMOUT, COMOUTroot
#      HOMEnos, USHnos, EXECnos, FIXofs, FIXnos
#      OCEAN_MODEL=SCHISM, USE_DATM=true
#      GRIDFILE, GRIDFILE_LL, VGRID_CTL, VGRID_NU_CTL, VGRID_FAKE_CTL
#      STA_OUT_CTL, RUNTIME_CTL, RUNTIME_CTL_FOR (optional)
#      HC_FILE_OBC, NWM_REACHID_FILE, CREATE_TIDEFORCING
#      LEN_FORECAST, LEN_NOWCAST, time_nowcastend (or PDY/cyc)
#      TOTAL_TASKS, PPN, NDATE, NHOUR
#
#  Variables produced for downstream consumers:
#      time_hotstart, time_nowcastend, time_forecastend, BASE_DATE
#      INI_FILE_NOWCAST, INI_FILE_FORECAST, RST_OUT_NOWCAST, RST_OUT_FORECAST
#      OBC_FORCING_FILE, RIVER_FORCING_FILE, BCTIDES_IN
#      NWM_SOURCE_SINK_NOW, NWM_SOURCE_SINK_FORE
#      MODEL_LOG_NOWCAST, MODEL_LOG_FORECAST, etc.
#
################################################################################

# ============================================================================
# SECTION 1: Public 4-step API
# ============================================================================

#-----------------------------------------------------------------------------
# stage_model_files - Copy forcing and static files to working directory
# Args:  $1 - phase (nowcast | forecast)
#-----------------------------------------------------------------------------
stage_model_files() {
    local phase="${1:?phase argument required (nowcast|forecast)}"

    echo "=== stage_model_files: ${phase} (SECOFS-UFS SCHISM) ==="

    mkdir -p $DATA/outputs $DATA/sflux

    _schism_stage_files "$phase"
}

#-----------------------------------------------------------------------------
# prepare_restart - Find and stage hotstart/initial condition file
# Args:  $1 - phase (nowcast | forecast)
#-----------------------------------------------------------------------------
prepare_restart() {
    local phase="${1:?phase argument required (nowcast|forecast)}"

    echo "=== prepare_restart: ${phase} (SECOFS-UFS SCHISM) ==="

    _schism_prepare_restart "$phase"
}

#-----------------------------------------------------------------------------
# execute_model - Configure runtime and run UFS-Coastal (DATM + SCHISM)
# Args:  $1 - phase (nowcast | forecast)
#-----------------------------------------------------------------------------
execute_model() {
    local phase="${1:?phase argument required (nowcast|forecast)}"

    echo "=== execute_model: ${phase} (SECOFS-UFS SCHISM) ==="

    _schism_execute_ufs_coastal "$phase"
}

#-----------------------------------------------------------------------------
# archive_outputs - Copy model outputs to $COMOUT
# Args:  $1 - phase (nowcast | forecast)
#-----------------------------------------------------------------------------
archive_outputs() {
    local phase="${1:?phase argument required (nowcast|forecast)}"

    echo "=== archive_outputs: ${phase} (SECOFS-UFS SCHISM) ==="

    _schism_archive_outputs "$phase"
}


# ============================================================================
# SECTION 2: Internal helpers
# ============================================================================

#-----------------------------------------------------------------------------
# _schism_setup_paths - The work formerly done by nos_run.sh
#
#    Stages static fix files, sets all of the "filename" environment variables
#    (INI_FILE_NOWCAST, RST_OUT_NOWCAST, OBC_FORCING_FILE, etc.) that the
#    legacy COMF/SCHISM scripts expect, recovers prep-job time variables from
#    $COMOUT, and (in prep mode only) hunts the COM tree for a usable
#    restart file.
#
#    NOTE: In SECOFS-UFS production this is invoked from stage_model_files
#    with runtype=nowcast (or "forecast" for the split-job forecast).
#    The COM-hunt block (formerly the "## For prep Only" block in
#    launch.sh) executes only when runtype=prep.  Production never enters
#    that block from this function — it relies on the prep job having
#    written time_hotstart/time_nowcastend/time_forecastend/base_date
#    files into $COMOUT, which we read back below.
#
#    Args:
#      $1 - runtype: "nowcast" | "forecast" | "prep"
#-----------------------------------------------------------------------------
_schism_setup_paths() {
    local runtype="${1:-nowcast}"
    set -x

    export OFS=${OFS:-secofs_ufs}
    export runtype

    echo "=== _schism_setup_paths: runtype=${runtype} OFS=${OFS} ==="
    echo "  started at UTC $(date)"
    [ -n "${cormslogfile:-}" ] && echo "_schism_setup_paths started: $(date)" >> $cormslogfile

    # Default time anchor for nowcast end (overridable upstream).
    export time_nowcastend=${PDY}${cyc}

    # ---- Required: horizontal grid file --------------------------------------
    if [ ! -s "${FIXofs}/${GRIDFILE}" ]; then
        echo "FATAL: ${FIXofs}/${GRIDFILE} not found"
        msg="FATAL ERROR: ${FIXofs}/${GRIDFILE} does not exist"
        postmsg "${jlogfile:-/dev/null}" "$msg" 2>/dev/null || true
        return 1
    fi
    cp -p ${FIXofs}/${GRIDFILE} ${DATA}/.

    # SCHISM-specific: outputs/sflux dirs + lat/lon grid + nudging weight
    mkdir -p ${DATA}/outputs ${DATA}/sflux
    [ -s "${FIXofs}/${GRIDFILE_LL}" ]    && cp -p ${FIXofs}/${GRIDFILE_LL}    ${DATA}/.
    [ -s "${FIXofs}/${Nudging_weight:-/dev/null}" ] && cp -p ${FIXofs}/${Nudging_weight} ${DATA}/.

    # ---- Tidal harmonic constants for OBC ------------------------------------
    if [ "${CREATE_TIDEFORCING:-0}" -gt 0 ] && [ "${DBASE_WL_NOW:-OBS}" != "OBS" ]; then
        if [ ! -s "${FIXofs}/${HC_FILE_OBC}" ]; then
            echo "FATAL: ${FIXofs}/${HC_FILE_OBC} not found"
            return 1
        fi
        cp -p ${FIXofs}/${HC_FILE_OBC} ${DATA}/.
    fi

    # ---- Vertical grid + SCHISM auxiliary files ------------------------------
    if [ -s "${FIXofs}/${VGRID_CTL}" ]; then
        cp -p ${FIXofs}/${VGRID_CTL} ${DATA}/.
    fi
    [ -s "${FIXofs}/${VGRID_NU_CTL:-}" ] && cp -p ${FIXofs}/${VGRID_NU_CTL} ${DATA}/.
    # vgrid.fake is copied OVER the vgrid name (intentional, see launch.sh:154)
    [ -s "${FIXofs}/${VGRID_FAKE_CTL:-}" ] && cp -p ${FIXofs}/${VGRID_FAKE_CTL} ${DATA}/${VGRID_CTL}
    [ -s "${FIXofs}/${PREFIXNOS}.nobc_nudge_index.dat" ] && \
        cp -p ${FIXofs}/${PREFIXNOS}.nobc_nudge_index.dat ${DATA}/nobc_nudge_index.dat
    [ -s "${FIXofs}/${PREFIXNOS}.nudge_point_at_ofs_grid.dat" ] && \
        cp -p ${FIXofs}/${PREFIXNOS}.nudge_point_at_ofs_grid.dat ${DATA}/nudge_point_at_ofs_grid.dat

    # ---- NWM river reach ID file (optional; falls back to USGS obs) ---------
    if [ -s "${FIXofs}/${NWM_REACHID_FILE:-}" ]; then
        cp -p ${FIXofs}/${NWM_REACHID_FILE} ${DATA}/.
        echo "Using NWM river forcing"
    else
        echo "WARNING: ${FIXofs}/${NWM_REACHID_FILE:-(unset)} not found — USGS obs fallback"
    fi

    # ---- Station control file ------------------------------------------------
    if [ ! -s "${FIXofs}/${STA_OUT_CTL}" ]; then
        echo "FATAL: ${FIXofs}/${STA_OUT_CTL} not found"
        return 1
    fi
    cp -p ${FIXofs}/${STA_OUT_CTL} ${DATA}/.

    # ---- Runtime control (param.nml template) -------------------------------
    if [ ! -s "${FIXofs}/${RUNTIME_CTL}" ]; then
        echo "FATAL: ${FIXofs}/${RUNTIME_CTL} not found"
        return 1
    fi
    cp -p ${FIXofs}/${RUNTIME_CTL} ${DATA}/.

    [ -s "${FIXofs}/${RUNTIME_CTL_FOR:-}" ] && cp -p ${FIXofs}/${RUNTIME_CTL_FOR} ${DATA}/.

    export HH=$cyc
    export PDY1=$PDY

    # =========================================================================
    # PREP-only block: COM-hunt for previous-cycle restart, BUFR check.
    #
    # Production SECOFS-UFS does NOT enter this block via stage_model_files.
    # The prep job (JNOS_PREP) runs the legacy launch.sh with
    # runtype=prep and writes time_hotstart, time_nowcastend, time_forecastend,
    # base_date to $COMOUT/<file>.${cycle}.  Nowcast/forecast jobs read those
    # files back below.
    #
    # Kept here so the consolidated nos_run.sh can also cover a future
    # standalone prep call (or for diagnostic/dev runs); functionally
    # equivalent to the old launch.sh "For prep Only" stanza.
    # =========================================================================
    if [ "${runtype}" = "prep" ] || [ "${runtype}" = "PREP" ]; then
        _schism_find_hotstart || return 1
    fi

    # =========================================================================
    # Output filename setup (always runs).  Mirrors launch.sh lines 802-895.
    # These names define the COMOUT artifacts written by prep, consumed by
    # _schism_stage_files later.
    # =========================================================================
    local YYYY MM DD HH
    YYYY=$(echo $time_nowcastend | cut -c1-4)
    MM=$(echo $time_nowcastend   | cut -c5-6)
    DD=$(echo $time_nowcastend   | cut -c7-8)
    HH=$(echo $time_nowcastend   | cut -c9-10)
    export PDY1=${YYYY}${MM}${DD}

    # Tarball/forcing names (same conventions as legacy COMF SCHISM)
    export OBC_FORCING_FILE=${PREFIXNOS}.${cycle}.${PDY1}.obc.tar
    export RIVER_FORCING_FILE=${PREFIXNOS}.${cycle}.${PDY1}.river.th.tar
    export NWM_SOURCE_SINK_NOW=${PREFIXNOS}.${cycle}.${PDY1}.nwm.source.sink.now.tar
    export NWM_SOURCE_SINK_FORE=${PREFIXNOS}.${cycle}.${PDY1}.nwm.source.sink.fore.tar
    export BCTIDES_IN=${PREFIXNOS}.${cycle}.${PDY1}.bctides.in

    export OBC_TIDALFORCING_FILE=${PREFIXNOS}.${cycle}.${PDY1}.roms.tides.nc
    export NUDG_FORCING_FILE=${PREFIXNOS}.${cycle}.${PDY1}.clim.nc
    export OBC_FORCING_FILE_EL=${PREFIXNOS}.${cycle}.${PDY1}.obc.el.tar
    export OBC_FORCING_FILE_TS=${PREFIXNOS}.${cycle}.${PDY1}.obc.ts.tar

    # Met forcing (sflux) tar names
    export MET_NETCDF_1_NOWCAST=${PREFIXNOS}.${cycle}.${PDY1}.met.nowcast.nc.tar
    export MET_NETCDF_1_FORECAST=${PREFIXNOS}.${cycle}.${PDY1}.met.forecast.nc.tar
    export MET_NETCDF_1_NOWCAST_2=${PREFIXNOS}.${cycle}.${PDY1}.met.nowcast.nc.2.tar
    export MET_NETCDF_1_FORECAST_2=${PREFIXNOS}.${cycle}.${PDY1}.met.forecast.nc.2.tar
    export MET_NETCDF_2_NOWCAST=${PREFIXNOS}.${cycle}.${PDY1}.hflux.nowcast.nc
    export MET_NETCDF_2_FORECAST=${PREFIXNOS}.${cycle}.${PDY1}.hflux.forecast.nc

    # Restart / initial file names (SCHISM uses .nc, not .bin)
    export INI_FILE_NOWCAST=${PREFIXNOS}.${cycle}.${PDY1}.init.nowcast.nc
    export RST_OUT_NOWCAST=${PREFIXNOS}.${cycle}.${PDY1}.rst.nowcast.nc
    export RST_OUT_FORECAST=${PREFIXNOS}.${cycle}.${PDY1}.rst.forecast.nc
    export INI_FILE_FORECAST=$RST_OUT_NOWCAST

    # Output product names
    export HIS_OUT_NOWCAST=${PREFIXNOS}.${cycle}.${PDY1}.fields.nowcast.nc
    export HIS_OUT_FORECAST=${PREFIXNOS}.${cycle}.${PDY1}.fields.forecast.nc
    export STA_OUT_NOWCAST=${PREFIXNOS}.${cycle}.${PDY1}.stations.nowcast.nc
    export STA_OUT_FORECAST=${PREFIXNOS}.${cycle}.${PDY1}.stations.forecast.nc
    export HIS_2D_NOWCAST=${PREFIXNOS}.${cycle}.${PDY1}.surface.nowcast.nc
    export HIS_2D_FORECAST=${PREFIXNOS}.${cycle}.${PDY1}.surface.forecast.nc
    export MODEL_LOG_NOWCAST=${PREFIXNOS}.${cycle}.${PDY1}.nowcast.log
    export MODEL_LOG_FORECAST=${PREFIXNOS}.${cycle}.${PDY1}.forecast.log

    # Runtime control filenames
    export RUNTIME_CTL_NOWCAST=${PREFIXNOS}.${cycle}.${PDY1}.nowcast.in
    export RUNTIME_CTL_FORECAST=${PREFIXNOS}.${cycle}.${PDY1}.forecast.in
    export RUNTIME_MET_CTL_NOWCAST=${PREFIXNOS}.${cycle}.${PDY1}.met_ctl.nowcast.in
    export RUNTIME_MET_CTL_FORECAST=${PREFIXNOS}.${cycle}.${PDY1}.met_ctl.forecast.in
    export RUNTIME_COMBINE_RST_NOWCAST=${PREFIXNOS}.${cycle}.${PDY1}.combine.hotstart.nowcast.in
    export RUNTIME_COMBINE_NETCDF_NOWCAST=${PREFIXNOS}.${cycle}.${PDY1}.combine.netcdf.nowcast.in
    export RUNTIME_COMBINE_NETCDF_FORECAST=${PREFIXNOS}.${cycle}.${PDY1}.combine.netcdf.forecast.in
    export RUNTIME_COMBINE_NETCDF_STA_NOWCAST=${PREFIXNOS}.${cycle}.${PDY1}.combine.netcdf.sta.nowcast.in
    export RUNTIME_COMBINE_NETCDF_STA_FORECAST=${PREFIXNOS}.${cycle}.${PDY1}.combine.netcdf.sta.forecast.in

    export RST_FILE=${RST_FILE:-}

    [ -n "${jlogfile:-}" ] && echo "Variable and parameter setup completed" >> $jlogfile

    return 0
}

#-----------------------------------------------------------------------------
# _schism_find_hotstart - COM-hunt for a usable previous-cycle restart
#
#    Walks back hour-by-hour from time_nowcastend looking for
#    ${COMOUTroot}/${RUN}.YYYYMMDD/${PREFIXNOS}.tHHz.YYYYMMDD.rst.nowcast.nc.
#    Sets RST_FILE, INI_FILE, COLD_START, BASE_DATE and runs
#    nos_ofs_read_restart(_schism: a no-op stub) to derive time_hotstart and
#    DSTART_NOWCAST.
#
#    Production SECOFS-UFS only invokes this from runtype=prep.
#-----------------------------------------------------------------------------
_schism_find_hotstart() {
    local COLD_START="F"
    local BACK_SEARCH=49
    local CURRENTTIME=$($NDATE -1 $time_nowcastend)
    local YYYY MM DD HH

    YYYY=$(echo $CURRENTTIME | cut -c1-4)
    MM=$(echo $CURRENTTIME   | cut -c5-6)
    DD=$(echo $CURRENTTIME   | cut -c7-8)
    HH=$(echo $CURRENTTIME   | cut -c9-10)
    RST_FILE=${COMOUTroot}/${RUN}.${YYYY}${MM}${DD}/${PREFIXNOS}.t${HH}z.${YYYY}${MM}${DD}.rst.nowcast.nc

    while [ ! -s "$RST_FILE" ]; do
        CURRENTTIME=$($NDATE -1 $CURRENTTIME)
        if [ $CURRENTTIME -le $($NDATE -$BACK_SEARCH $time_nowcastend) ]; then
            COLD_START="T"
            break
        fi
        YYYY=$(echo $CURRENTTIME | cut -c1-4)
        MM=$(echo $CURRENTTIME   | cut -c5-6)
        DD=$(echo $CURRENTTIME   | cut -c7-8)
        HH=$(echo $CURRENTTIME   | cut -c9-10)
        RST_FILE=${COMOUTroot}/${RUN}.${YYYY}${MM}${DD}/${PREFIXNOS}.t${HH}z.${YYYY}${MM}${DD}.rst.nowcast.nc
    done

    if [ "$COLD_START" = "T" ]; then
        echo "FATAL: NO VALID RESTART FILE in last ${BACK_SEARCH}h. Check $COMOUT."
        err_exit "NO VALID RESTART FILE AVAILABLE"
    fi

    INI_FILE=$RST_FILE
    BASE_DATE=${YYYY}${MM}${DD}${HH}
    local NH_NOWCAST=$($NHOUR $time_nowcastend $BASE_DATE)
    if [ $NH_NOWCAST -ge 48 ]; then
        INI_FILE=${FIXofs}/${PREFIXNOS}.init.nc
        COLD_START="T"
        BASE_DATE=$($NDATE -48 $time_nowcastend)
    fi
    export BASE_DATE INI_FILE

    YYYY=$(echo $time_nowcastend | cut -c1-4)
    MM=$(echo $time_nowcastend   | cut -c5-6)
    DD=$(echo $time_nowcastend   | cut -c7-8)
    HH=$(echo $time_nowcastend   | cut -c9-10)
    export INI_FILE_ROMS=${PREFIXNOS}.${cycle}.${YYYY}${MM}${DD}.init.nowcast.nc
    cp -p $INI_FILE $DATA/$INI_FILE_ROMS

    # SCHISM has no Fortran read_restart — emit a synthetic time_initial.dat
    # to mirror the legacy launch.sh:640 logic.
    echo $BASE_DATE 0 0.0 0.0d0 > ${DATA}/${RUN}_time_initial.dat
    read time_hotstart NTIMES DAY0 TIDE_START < ${DATA}/${RUN}_time_initial.dat

    if [ $time_hotstart -ge $time_nowcastend ]; then
        echo "FATAL: time_hotstart ($time_hotstart) >= time_nowcastend ($time_nowcastend)"
        return 1
    fi

    local NRREC=0
    [ $NTIMES -gt 0 ] && NRREC=-1
    export DSTART_NOWCAST=$DAY0
    export time_hotstart NTIMES NRREC TIDE_START

    export time_forecastend=$($NDATE $LEN_FORECAST $time_nowcastend)
    export NH_NOWCAST=$($NHOUR $time_nowcastend $time_hotstart)
    export NSTEP_NOWCAST=$(expr $NH_NOWCAST \* 3600 / ${DELT_MODEL%.*})
    export NTIMES_NOWCAST=$NSTEP_NOWCAST
    export NH_FORECAST=$($NHOUR $time_forecastend $time_nowcastend)
    export NSTEP_FORECAST=$(expr $NH_FORECAST \* 3600 / ${DELT_MODEL%.*})
    export NTIMES_FORECAST=$NSTEP_FORECAST
    export DSTART_FORECAST=$(echo "scale=4;$DAY0+${NH_NOWCAST}/24.0" | bc)

    # Persist time variables for nowcast/forecast jobs to read back
    echo $time_nowcastend  > $COMOUT/time_nowcastend.${cycle}
    echo $time_hotstart    > $COMOUT/time_hotstart.${cycle}
    echo $time_forecastend > $COMOUT/time_forecastend.${cycle}
    echo $BASE_DATE        > $COMOUT/base_date.${cycle}

    return 0
}

#-----------------------------------------------------------------------------
# _schism_stage_files - SECOFS-UFS file staging into $DATA
#
#    Combines the work formerly split across:
#      _comf_stage_files (model_run.sh:489-946)
#      nos_run.sh (898 lines, dot-sourced)
#
#    Steps (in order):
#      1. Run _schism_setup_paths to copy fix files & set env var names
#      2. Recover time_hotstart/etc from $COMOUT (prep-job artifacts)
#      3. Stage UFS-Coastal DATM artifacts (model_configure, datm_in, ESMF mesh)
#      4. Patch model_configure / ufs.configure / param.nml for phase
#      5. Stage SCHISM bare-name input files (hgrid.gr3, vgrid.in, ...)
#      6. Stage hotstart.nc (from INI_FILE_NOWCAST or INI_FILE_FORECAST)
#      7. Untar NWM river forcing, OBC forcing, river forcing tarballs
#      8. Final validation + restart_outputs staging for forecast
#-----------------------------------------------------------------------------
_schism_stage_files() {
    local phase=$1

    # --------------------------------------------------------------------
    # 1. Setup paths and filename env vars (formerly: . nos_run.sh)
    # --------------------------------------------------------------------
    echo "Running _schism_setup_paths (replaces nos_run.sh)"
    _schism_setup_paths "nowcast"
    export err=$?
    if [ $err -ne 0 ]; then
        echo "FATAL: _schism_setup_paths failed (rc=$err)"
        msg="FATAL: _schism_setup_paths failed"
        postmsg "${jlogfile:-/dev/null}" "$msg" 2>/dev/null || true
        [ -n "${cormslogfile:-}" ] && echo "$msg" >> $cormslogfile
        err_chk
        return $err
    fi
    [ -n "${cormslogfile:-}" ] && echo "_schism_setup_paths completed normally" >> $cormslogfile

    # --------------------------------------------------------------------
    # 2. Recover prep-generated time variables from $COMOUT (split-job mode)
    # --------------------------------------------------------------------
    echo "Recovering prep-generated time variables from $COMOUT"
    if [ -s "$COMOUT/time_hotstart.${cycle}" ]; then
        read time_hotstart < "$COMOUT/time_hotstart.${cycle}"
        export time_hotstart
        echo "  time_hotstart=$time_hotstart"
    else
        echo "FATAL: $COMOUT/time_hotstart.${cycle} not found!"
        echo "The prep job (JNOS_PREP) must run before nowcast/forecast."
        msg="FATAL: time_hotstart not found in COMOUT"
        postmsg "${jlogfile:-/dev/null}" "$msg" 2>/dev/null || true
        return 1
    fi
    if [ -s "$COMOUT/time_nowcastend.${cycle}" ]; then
        read time_nowcastend < "$COMOUT/time_nowcastend.${cycle}"; export time_nowcastend
        echo "  time_nowcastend=$time_nowcastend"
    fi
    if [ -s "$COMOUT/time_forecastend.${cycle}" ]; then
        read time_forecastend < "$COMOUT/time_forecastend.${cycle}"; export time_forecastend
        echo "  time_forecastend=$time_forecastend"
    fi
    if [ -s "$COMOUT/base_date.${cycle}" ]; then
        read BASE_DATE < "$COMOUT/base_date.${cycle}"; export BASE_DATE
        echo "  BASE_DATE=$BASE_DATE"
    fi

    # --------------------------------------------------------------------
    # 3. UFS-Coastal DATM staging (only when USE_DATM=true).
    #     Skip silently otherwise — this draft is SECOFS-UFS-only and DATM
    #     is always on, but kept guarded for diagnostic/standalone runs.
    # --------------------------------------------------------------------
    if [ "${USE_DATM:-false}" != "true" ] && [ "${USE_DATM:-0}" != "1" ]; then
        echo "USE_DATM is not enabled — skipping DATM/UFS-Coastal staging"
        return 0
    fi

    echo "Staging UFS-Coastal DATM artifacts from $COMOUT"
    local DATM_DIR=${DATM_INPUT_DIR:-INPUT}
    mkdir -p ${DATA}/${DATM_DIR} ${DATA}/RESTART ${DATA}/outputs

    # DATM forcing + ESMF mesh
    local datm_dir="${COMOUT}/${RUN}.${cycle}.datm_input"
    if [ -d "$datm_dir" ]; then
        cp -p ${datm_dir}/*.nc ${DATA}/${DATM_DIR}/ 2>/dev/null || true
        echo "  Staged DATM files to ${DATM_DIR}/ from $datm_dir"
    else
        echo "WARNING: DATM input directory not found: $datm_dir"
    fi

    # UFS configs (model_configure, datm_in, datm.streams, ufs.configure)
    for f in model_configure datm_in datm.streams ufs.configure; do
        local src="${COMOUT}/${RUN}.${cycle}.${f}"
        if [ -s "$src" ]; then
            cp -p "$src" "${DATA}/${f}"
            echo "  Staged: ${f}"
        else
            echo "WARNING: UFS config not found: $src"
        fi
    done

    # NUOPC field dictionary + Noah-MP parameters
    for f in fd_ufs.yaml noahmptable.tbl; do
        if [ -s "${FIXofs}/${f}" ]; then
            cp -p "${FIXofs}/${f}" "${DATA}/${f}"
        elif [ -s "${COMOUT}/${RUN}.${cycle}.${f}" ]; then
            cp -p "${COMOUT}/${RUN}.${cycle}.${f}" "${DATA}/${f}"
        fi
    done

    # UFS-Coastal executable
    local UFS_EXEC_NAME=${UFS_EXEC_NAME:-fv3_coastalS.exe}
    if [ ! -x "${DATA}/${UFS_EXEC_NAME}" ] && [ -x "${EXECnos:-}/${UFS_EXEC_NAME}" ]; then
        cp -p "${EXECnos}/${UFS_EXEC_NAME}" "${DATA}/${UFS_EXEC_NAME}"
        echo "  Staged executable: ${UFS_EXEC_NAME}"
    fi

    # --------------------------------------------------------------------
    # 4. Patch model_configure / ufs.configure / param.nml for this phase.
    #    UFS-Coastal NUOPC clock semantics (ihot=1 always, time reset):
    #      - nowcast:  start at time_hotstart, run LEN_NOWCAST hours
    #      - forecast: start at time_nowcastend, run LEN_FORECAST hours
    # --------------------------------------------------------------------
    local start_type="startup"
    local nhours sim_start
    if [ "$phase" = "nowcast" ]; then
        nhours=${LEN_NOWCAST:-6}
        sim_start=${time_hotstart:-$($NDATE -${LEN_NOWCAST:-6} ${PDY}${cyc})}
    else
        nhours=${LEN_FORECAST:-48}
        sim_start=${time_nowcastend:-${PDY}${cyc}}
    fi
    local sim_yyyy=$(echo $sim_start | cut -c1-4)
    local sim_mm=$(  echo $sim_start | cut -c5-6)
    local sim_dd=$(  echo $sim_start | cut -c7-8)
    local sim_hh=$(  echo $sim_start | cut -c9-10)

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
        sed -i "s/orb_iyear = .*/orb_iyear = ${sim_yyyy}/" ${DATA}/ufs.configure
        sed -i "s/orb_iyear_align = .*/orb_iyear_align = ${sim_yyyy}/" ${DATA}/ufs.configure
    fi

    # SCHISM NUOPC cap requires the file named exactly "param.nml" in $DATA.
    # _schism_setup_paths copied ${RUNTIME_CTL} (e.g., secofs_ufs.param.nml)
    # to $DATA with its prefixed name; here we rename + substitute placeholders.
    if [ ! -s "${DATA}/param.nml" ] && [ -s "${DATA}/${RUNTIME_CTL}" ]; then
        cp -p "${DATA}/${RUNTIME_CTL}" "${DATA}/param.nml"
        echo "  Copied ${RUNTIME_CTL} -> param.nml"
    fi
    local ihot_val=1   # ihot=1 for both nowcast and forecast (NUOPC clock sync)
    if [ -s "${DATA}/param.nml" ]; then
        local rnday=$(python3 -c "print(${nhours}/24.0)" 2>/dev/null || echo "0.25")
        sed -i "s/rnday_value/${rnday}/"                 ${DATA}/param.nml
        sed -i "s/^\(\s*rnday\s*=\s*\)[0-9.]*\(.*\)/\1${rnday}\2/" ${DATA}/param.nml
        sed -i "s/start_year_value/${sim_yyyy}/"         ${DATA}/param.nml
        sed -i "s/start_month_value/${sim_mm#0}/"        ${DATA}/param.nml
        sed -i "s/start_day_value/${sim_dd#0}/"          ${DATA}/param.nml
        sed -i "s/start_hour_value/${sim_hh}/"           ${DATA}/param.nml
        sed -i "s/^\(\s*start_year\s*=\s*\)[0-9]*\(.*\)/\1${sim_yyyy}\2/"  ${DATA}/param.nml
        sed -i "s/^\(\s*start_month\s*=\s*\)[0-9]*\(.*\)/\1${sim_mm#0}\2/" ${DATA}/param.nml
        sed -i "s/^\(\s*start_day\s*=\s*\)[0-9]*\(.*\)/\1${sim_dd#0}\2/"   ${DATA}/param.nml
        sed -i "s/^\(\s*start_hour\s*=\s*\)[0-9]*\(.*\)/\1${sim_hh#0}\2/"  ${DATA}/param.nml
        sed -i "s/ihot = [0-9]*/ihot = ${ihot_val}/"     ${DATA}/param.nml
        echo "  Patched param.nml: rnday=${rnday}, start=${sim_yyyy}-${sim_mm}-${sim_dd} ${sim_hh}Z, ihot=${ihot_val}"
    fi

    # Patch datm_in nx_global/ny_global to match actual forcing grid
    if [ -s "${DATA}/datm_in" ] && [ -s "${DATA}/${DATM_DIR}/datm_forcing.nc" ]; then
        local _dims=$(ncdump -h "${DATA}/${DATM_DIR}/datm_forcing.nc" 2>/dev/null | \
            grep -oP '(x|y|longitude|latitude)\s*=\s*\K[0-9]+' | head -2)
        local _nx=$(echo $_dims | awk '{print $1}')
        local _ny=$(echo $_dims | awk '{print $2}')
        if [ -n "$_nx" ] && [ -n "$_ny" ]; then
            sed -i "s/nx_global = [0-9]*/nx_global = ${_nx}/" ${DATA}/datm_in
            sed -i "s/ny_global = [0-9]*/ny_global = ${_ny}/" ${DATA}/datm_in
            echo "  Patched datm_in: nx_global=${_nx}, ny_global=${_ny}"
        fi
    fi

    # --------------------------------------------------------------------
    # 5. SCHISM bare-name file staging (re-copies from FIXofs without
    #    PREFIXNOS prefix, since SCHISM expects bare filenames).
    # --------------------------------------------------------------------
    echo "  Staging SCHISM bare-name input files..."

    [ -s "${FIXofs}/${PREFIXNOS}.hgrid.gr3" ] && cp -p ${FIXofs}/${PREFIXNOS}.hgrid.gr3 ${DATA}/hgrid.gr3
    [ -s "${FIXofs}/${VGRID_CTL}" ]            && cp -p ${FIXofs}/${VGRID_CTL}            ${DATA}/vgrid.in
    [ -s "${FIXofs}/${VGRID_NU_CTL:-${PREFIXNOS}.vgrid.nu.in}" ] && \
        cp -p ${FIXofs}/${VGRID_NU_CTL:-${PREFIXNOS}.vgrid.nu.in} ${DATA}/vgrid_nu.in
    [ -s "${FIXofs}/${STA_OUT_CTL}" ]          && cp -p ${FIXofs}/${STA_OUT_CTL}          ${DATA}/station.in

    # Optional grid property files
    for bare in shapiro.gr3 diffmax.gr3 diffmin.gr3 watertype.gr3 \
                windrot_geo2proj.gr3 albedo.gr3 rough.gr3 drag.gr3 \
                SAL_nudge.gr3 TEM_nudge.gr3 elev.ic hgrid.ll; do
        if [ -s "${FIXofs}/${PREFIXNOS}.${bare}" ]; then
            cp -p ${FIXofs}/${PREFIXNOS}.${bare} ${DATA}/${bare}
        fi
    done

    # SCHISM property files.
    #
    # partition.prop is staged when present so SCHISM reads the pre-computed
    # partitioning instead of calling ParMETIS at runtime. At 2794-rank scale
    # (the v3.9 mesh SCHISM/OCN rank count), ParMETIS's multi-level
    # partitioner exhibits heap corruption inside partition_hgrid (seen on
    # WCOSS2 jobid 262503199: "Could not find pointer in mcore" during
    # ParMETIS_V3_PartGeomKway). The original comment here said
    # "UFS-Coastal uses different PET count than standalone, so SCHISM uses
    # METIS internal partitioning" — that was a stale assumption: what
    # matters is the OCN/SCHISM rank count (2794), not the total PET count
    # (2914 = 120 ATM/MED + 2794 OCN). partition.prop sized for max rank
    # 2793 (commit f9e8f85) is exactly the right shape for the UFS-Coastal
    # SCHISM partition.
    for prop in partition.prop tvd.prop fluxflag.prop; do
        if [ -s "${FIXofs}/${PREFIXNOS}.${prop}" ]; then
            cp -p ${FIXofs}/${PREFIXNOS}.${prop} ${DATA}/${prop}
            [ "${prop}" = "partition.prop" ] && echo "  Staged partition.prop (pre-computed, bypasses ParMETIS at runtime)"
        fi
    done

    # bctides.in from prep-generated COMOUT (correct nodal factors)
    local bctides_file
    if [ "$phase" = "nowcast" ]; then
        bctides_file="${BCTIDES_IN:-${PREFIXNOS}.bctides.in}.nowcast"
    else
        bctides_file="${BCTIDES_IN:-${PREFIXNOS}.bctides.in}.forecast"
    fi
    if [ -s "${COMOUT}/${bctides_file}" ]; then
        cp -p ${COMOUT}/${bctides_file} ${DATA}/bctides.in
        echo "  Staged bctides.in from ${bctides_file}"
    elif [ -s "${FIXofs}/${HC_FILE_OBC:-${PREFIXNOS}.bctides.in}" ]; then
        cp -p ${FIXofs}/${HC_FILE_OBC:-${PREFIXNOS}.bctides.in} ${DATA}/bctides.in
        echo "  WARNING: Using FIXofs bctides.in (prep-generated not found)"
    fi

    # --------------------------------------------------------------------
    # 6. Stage hotstart.nc.  ihot=1 for both phases means SCHISM still
    #    needs the file (ocean state), but it resets the model clock.
    # --------------------------------------------------------------------
    if [ "$phase" = "nowcast" ]; then
        if [ -n "${INI_FILE_NOWCAST:-}" ] && [ -s "${COMOUT}/${INI_FILE_NOWCAST}" ]; then
            cp -p ${COMOUT}/${INI_FILE_NOWCAST} ${DATA}/hotstart.nc
            echo "  Staged hotstart.nc from ${INI_FILE_NOWCAST}"
        elif [ -n "${INI_FILE:-}" ] && [ -s "${INI_FILE}" ]; then
            cp -p ${INI_FILE} ${DATA}/hotstart.nc
            echo "  Staged hotstart.nc from ${INI_FILE}"
        else
            echo "FATAL: nowcast requires hotstart.nc (ihot=${ihot_val}) but none was found." >&2
            echo "  Searched: \${COMOUT}/\${INI_FILE_NOWCAST} (INI_FILE_NOWCAST=${INI_FILE_NOWCAST:-<unset>})" >&2
            echo "            \${INI_FILE} (INI_FILE=${INI_FILE:-<unset>})" >&2
            echo "  Fix: stage a NETCDF4_CLASSIC hotstart at \${COMOUT}/\${PREFIXNOS}.init.nowcast.nc" >&2
            echo "       (auto-stage in nos_utils.forcing.hotstart needs a previous-cycle rst.nowcast.nc)" >&2
            export err=1; err_exit
        fi
    else
        # Forecast uses nowcast restart (ihot=1, time reset)
        if [ -n "${INI_FILE_FORECAST:-}" ] && [ -s "${COMOUT}/${INI_FILE_FORECAST}" ]; then
            cp -p ${COMOUT}/${INI_FILE_FORECAST} ${DATA}/hotstart.nc
            echo "  Staged hotstart.nc from ${INI_FILE_FORECAST}"
        elif [ -n "${RST_OUT_NOWCAST:-}" ] && [ -s "${COMOUT}/${RST_OUT_NOWCAST}" ]; then
            cp -p ${COMOUT}/${RST_OUT_NOWCAST} ${DATA}/hotstart.nc
            echo "  Staged hotstart.nc from ${RST_OUT_NOWCAST}"
        else
            echo "FATAL: forecast requires hotstart.nc but no nowcast restart was found." >&2
            echo "  Searched: \${COMOUT}/\${INI_FILE_FORECAST} (INI_FILE_FORECAST=${INI_FILE_FORECAST:-<unset>})" >&2
            echo "            \${COMOUT}/\${RST_OUT_NOWCAST} (RST_OUT_NOWCAST=${RST_OUT_NOWCAST:-<unset>})" >&2
            echo "  Fix: ensure the nowcast stage archived its combined hotstart to \${COMOUT} as rst.nowcast.nc" >&2
            export err=1; err_exit
        fi
        # Force ihot=1 in case the runtime ctl shipped ihot=2.  Original COMF
        # uses ihot=1 for forecast (clock reset; rnday = forecast duration).
        if [ -s "${DATA}/param.nml" ]; then
            sed -i 's/ihot *= *[0-9]*/ihot = 1/' ${DATA}/param.nml
            echo "  Set ihot=1 in param.nml for forecast (matches original COMF)"
            mkdir -p ${DATA}/outputs
        fi
    fi

    # --------------------------------------------------------------------
    # 7. Untar prep-generated forcing tarballs into $DATA
    # --------------------------------------------------------------------
    # NWM river forcing
    if [ "$phase" = "nowcast" ] && [ -n "${NWM_SOURCE_SINK_NOW:-}" ]; then
        if [ -s "${COMOUT}/${NWM_SOURCE_SINK_NOW}" ]; then
            cp -p ${COMOUT}/${NWM_SOURCE_SINK_NOW} ${DATA}/
            tar xf ${DATA}/${NWM_SOURCE_SINK_NOW} -C ${DATA}/ 2>/dev/null || true
            echo "  Staged NWM river forcing (nowcast)"
        fi
    elif [ "$phase" = "forecast" ] && [ -n "${NWM_SOURCE_SINK_FORE:-}" ]; then
        if [ -s "${COMOUT}/${NWM_SOURCE_SINK_FORE}" ]; then
            cp -p ${COMOUT}/${NWM_SOURCE_SINK_FORE} ${DATA}/
            tar xf ${DATA}/${NWM_SOURCE_SINK_FORE} -C ${DATA}/ 2>/dev/null || true
            echo "  Staged NWM river forcing (forecast)"
        fi
    fi

    # Validate NWM river files (SCHISM aborts if if_source=1 and these are missing)
    if [ ! -s "${DATA}/source_sink.in" ]; then
        echo "WARNING: source_sink.in not found after NWM tar extraction"
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

    # OBC forcing (TEM_nu.nc, SAL_nu.nc, TEM_3D.th.nc, SAL_3D.th.nc, elev2D.th.nc, uv3D.th.nc)
    if [ -n "${OBC_FORCING_FILE:-}" ]; then
        if [ -s "${COMOUT}/${OBC_FORCING_FILE}" ]; then
            cp -p ${COMOUT}/${OBC_FORCING_FILE} ${DATA}/
            tar xf ${DATA}/${OBC_FORCING_FILE} -C ${DATA}/
            echo "  Staged OBC forcing from ${OBC_FORCING_FILE}"
        else
            echo "WARNING: OBC forcing tar not found: ${COMOUT}/${OBC_FORCING_FILE}"
        fi
    fi

    # River forcing tar (schism_flux.th, schism_temp.th, schism_salt.th)
    if [ -n "${RIVER_FORCING_FILE:-}" ]; then
        if [ -s "${COMOUT}/${RIVER_FORCING_FILE}" ]; then
            cp -p ${COMOUT}/${RIVER_FORCING_FILE} ${DATA}/
            tar xf ${DATA}/${RIVER_FORCING_FILE} -C ${DATA}/
            echo "  Staged river forcing from ${RIVER_FORCING_FILE}"
        else
            echo "WARNING: River forcing tar not found: ${COMOUT}/${RIVER_FORCING_FILE}"
        fi
    fi

    # SCHISM expects TEM_1.th / flux.th / salt.th names
    [ -s "${DATA}/schism_temp.th" ] && cp -p ${DATA}/schism_temp.th ${DATA}/TEM_1.th
    [ -s "${DATA}/schism_flux.th" ] && cp -p ${DATA}/schism_flux.th ${DATA}/flux.th
    [ -s "${DATA}/schism_salt.th" ] && cp -p ${DATA}/schism_salt.th ${DATA}/salt.th

    # sflux_inputs.txt (not used by DATM, but SCHISM may probe for it)
    if [ -s "${FIXofs}/${PREFIXNOS}.sflux_inputs.txt" ]; then
        mkdir -p ${DATA}/sflux
        cp -p ${FIXofs}/${PREFIXNOS}.sflux_inputs.txt ${DATA}/sflux/sflux_inputs.txt
    fi

    # hgrid.gr3 also required in outputs/
    mkdir -p ${DATA}/outputs
    [ -s "${DATA}/hgrid.gr3" ] && cp -p ${DATA}/hgrid.gr3 ${DATA}/outputs/

    # --------------------------------------------------------------------
    # 8. Forecast-only: stage previous-cycle restart_outputs + ensure
    #    mirror.out/flux.out exist (SCHISM open(status='old') requirement).
    # --------------------------------------------------------------------
    if [ "$phase" = "forecast" ]; then
        local restart_dir="${COMOUT}/${RUN}.${cycle}.restart_outputs"
        if [ -d "$restart_dir" ]; then
            for f in mirror.out flux.out staout_1 staout_2 staout_3 staout_4 \
                     staout_5 staout_6 staout_7 staout_8 staout_9; do
                [ -f "${restart_dir}/${f}" ] && cp -p ${restart_dir}/${f} ${DATA}/outputs/
            done
            echo "  Staged restart_outputs from ${restart_dir}"
            [ -s "${DATA}/outputs/staout_1" ] && \
                echo "  staout_1: $(wc -l < ${DATA}/outputs/staout_1) lines"
        else
            echo "  WARNING: restart_outputs not found: ${restart_dir}"
        fi
        # Ensure mandatory output files exist
        for f in mirror.out flux.out; do
            [ ! -f "${DATA}/outputs/${f}" ] && touch "${DATA}/outputs/${f}"
        done
        for i in $(seq 1 9); do
            [ ! -f "${DATA}/outputs/staout_${i}" ] && touch "${DATA}/outputs/staout_${i}"
        done
    fi

    echo "  SCHISM bare-name file staging complete"
    echo "  UFS-Coastal staging complete"
}

#-----------------------------------------------------------------------------
# _schism_prepare_restart - No-op for SECOFS-UFS.
#
#    All restart handling is folded into _schism_stage_files (steps 6 + 8).
#    This stub remains as a public API contract — exposed for future restart
#    logic if/when COMF restart semantics change (e.g., dynamic IC fallback).
#-----------------------------------------------------------------------------
_schism_prepare_restart() {
    local phase=$1
    echo "Restart handling done in _schism_stage_files (no-op here)"
    return 0
}

#-----------------------------------------------------------------------------
# _schism_execute_ufs_coastal - The main UFS-Coastal (DATM + SCHISM) execution
#
#    Validates UFS configs/forcing, regenerates ESMF mesh from forcing file
#    for guaranteed dimensional consistency, runs mpiexec, then combines the
#    distributed hotstart files and converts to NETCDF4_CLASSIC for parallel-IO
#    safety on the next forecast/nowcast.
#-----------------------------------------------------------------------------
_schism_execute_ufs_coastal() {
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

    # Validate DATM forcing directory
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

    [ ! -s "${DATA}/fd_ufs.yaml" ] && echo "WARNING: fd_ufs.yaml not found"

    # ------------------------------------------------------------------
    # Sync datm_in + ESMF mesh with actual forcing file dimensions.  The
    # datm_in template may carry stale nx_global/ny_global values (e.g.,
    # raw GFS 0.25 grid) that don't match the actual forcing file (e.g.,
    # blended HRRR+GFS).  Mismatched dims scramble CDEPS interpolation.
    # ------------------------------------------------------------------
    local _forcing_file="${DATA}/${DATM_DIR}/datm_forcing.nc"
    if [ -s "${_forcing_file}" ] && [ -s "${DATA}/datm_in" ]; then
        local _fdims=$(python3 -c "
from netCDF4 import Dataset
ds = Dataset('${_forcing_file}', 'r')
try:
    print(len(ds.dimensions['x']), len(ds.dimensions['y']))
except:
    print(len(ds.dimensions['longitude']), len(ds.dimensions['latitude']))
ds.close()
" 2>/dev/null || echo "")

        if [ -n "$_fdims" ]; then
            local _fnx=$(echo $_fdims | awk '{print $1}')
            local _fny=$(echo $_fdims | awk '{print $2}')
            local _old_nx=$(grep -oP 'nx_global\s*=\s*\K[0-9]+' ${DATA}/datm_in 2>/dev/null || echo "0")
            local _old_ny=$(grep -oP 'ny_global\s*=\s*\K[0-9]+' ${DATA}/datm_in 2>/dev/null || echo "0")
            if [ "${_old_nx}" != "${_fnx}" ] || [ "${_old_ny}" != "${_fny}" ]; then
                echo "Patching datm_in: nx_global ${_old_nx}->${_fnx}, ny_global ${_old_ny}->${_fny}"
            fi
            sed -i "s/nx_global[[:space:]]*=.*/nx_global = ${_fnx}/" ${DATA}/datm_in
            sed -i "s/ny_global[[:space:]]*=.*/ny_global = ${_fny}/" ${DATA}/datm_in

            # Regenerate ESMF mesh from forcing file (guarantees consistent
            # dims, elementMask, coordinates — never trust template meshes).
            local _ftotal=$((_fnx * _fny))
            echo "Generating ESMF mesh from forcing (${_fnx}x${_fny} = ${_ftotal} nodes)..."
            python3 -m nos_workflow.runners.schism_ufs.mesh \
                --forcing "${_forcing_file}" \
                --output "${DATA}/${DATM_DIR}/datm_esmf_mesh.nc" 2>&1
            if [ $? -ne 0 ]; then
                echo "WARNING: ESMF mesh generation failed - using existing mesh" >&2
            fi
        fi
    fi

    # Determine UFS-Coastal executable
    local UFS_EXEC=""
    if   [ -x "${DATA}/fv3_coastalS.exe" ];           then UFS_EXEC="${DATA}/fv3_coastalS.exe"
    elif [ -x "${EXECnos:-}/fv3_coastalS.exe" ];      then UFS_EXEC="${EXECnos}/fv3_coastalS.exe"
    elif [ -x "${EXECnos:-}/ufs_coastal" ];           then UFS_EXEC="${EXECnos}/ufs_coastal"
    elif [ -x "${EXECnos:-}/ufs_model" ];             then UFS_EXEC="${EXECnos}/ufs_model"
    else
        echo "FATAL: UFS-Coastal executable not found"
        echo "  Checked: ${DATA}/fv3_coastalS.exe"
        echo "  Checked: ${EXECnos:-}/fv3_coastalS.exe"
        echo "  Checked: ${EXECnos:-}/ufs_coastal"
        echo "  Checked: ${EXECnos:-}/ufs_model"
        return 1
    fi

    local NTASKS=${TOTAL_TASKS:-1200}
    local PPN=${PPN:-120}

    echo "Executable: $UFS_EXEC"
    echo "Total MPI tasks: $NTASKS"
    echo "PPN: $PPN"
    echo "Phase: $phase"

    # UFS-Coastal runtime environment
    # OMP_NUM_THREADS=1 forced — Cray PBS can default it to ncpus (128)
    # which oversubscribes 120 ranks/node massively.
    export OMP_STACKSIZE=512M
    export OMP_NUM_THREADS=1
    export OMP_PLACES=cores
    export ESMF_RUNTIME_COMPLIANCECHECK=OFF:depth=4
    export ESMF_RUNTIME_PROFILE=ON
    export ESMF_RUNTIME_PROFILE_OUTPUT="SUMMARY"

    # Drop LD_PRELOAD: the COMF J-job sets it for standalone Fortran execs
    # (system netcdf/4.7.4 libnetcdff.so) but UFS-Coastal links its own
    # hpc-stack libraries (netcdf-D/4.9.2) loaded by modules.fv3.
    unset LD_PRELOAD 2>/dev/null || true

    echo "Starting UFS-Coastal at: $(date)"
    echo "  mpiexec -n ${NTASKS} -ppn ${PPN} --cpu-bind core ${UFS_EXEC}"

    cd $DATA
    mpiexec -n ${NTASKS} -ppn ${PPN} --cpu-bind core ${UFS_EXEC}
    export err=$?

    echo "UFS-Coastal finished at: $(date) with exit code: $err"

    if [ $err -ne 0 ]; then
        echo "UFS-Coastal execution FAILED (rc=$err)"
        [ -n "${cormslogfile:-}" ] && echo "UFS-Coastal $phase execution failed" >> $cormslogfile
        msg="UFS-Coastal $phase execution failed (rc=$err)"
        postmsg "${jlogfile:-/dev/null}" "$msg" 2>/dev/null || true
        return $err
    fi

    if [ -d "${DATA}/outputs" ] && [ -s "${DATA}/outputs/mirror.out" ]; then
        echo "UFS-Coastal $phase completed successfully (mirror.out found)"
    else
        echo "WARNING: mirror.out not found - UFS-Coastal may not have completed"
    fi

    # ------------------------------------------------------------------
    # Combine distributed hotstart, then convert to NETCDF4_CLASSIC.
    # Nowcast hotstart -> forecast in same cycle.
    # Forecast hotstart -> next cycle's nowcast.
    # ------------------------------------------------------------------
    if [ "$phase" = "nowcast" ] || [ "$phase" = "forecast" ] && [ -d "${DATA}/outputs" ]; then
        echo "Combining distributed hotstart files..."
        cd ${DATA}/outputs

        local dt_val=$(grep -m1 '^\s*dt\s*=' ${DATA}/param.nml | sed 's/.*=\s*//;s/[^0-9.]//g')
        local nhot_write_val=$(grep -m1 'nhot_write' ${DATA}/param.nml | sed 's/!.*//;s/.*=//;s/[^0-9]//g')
        local nsteps=${nhot_write_val:-180}
        # Pick the actual last hotstart step from distributed files
        # (hotstart_RANK_STEP.nc, e.g. hotstart_000000_180.nc)
        local _last_step=$(ls hotstart_000000_*.nc 2>/dev/null | sort -t_ -k3 -n | tail -1 | sed 's/.*_\([0-9]*\)\.nc/\1/')
        nsteps=${_last_step:-$nsteps}
        echo "  Hotstart timestep: $nsteps (nhot_write=${nhot_write_val:-unknown}, dt=${dt_val:-unknown})"

        # Locate combine_hotstart7 (multiple search locations)
        local COMBINE_EXE=""
        for _cand in \
            "${EXECnos:-}/schism_combine_hotstart7.exe" \
            "${HOMEnos:-}/exec/schism_combine_hotstart7.exe" \
            "${EXECnos:-}/nos_ofs_combine_hotstart" \
            "${EXECstofs3d:-}/stofs_3d_atl_combine_hotstart"; do
            if [ -x "$_cand" ]; then COMBINE_EXE="$_cand"; break; fi
        done

        if [ -n "$COMBINE_EXE" ]; then
            echo "  Using combine executable: $COMBINE_EXE"
            # combine_hotstart7 links against /apps/prod/hpc-stack/intel-*/netcdf/4.7.4
            for _lib in \
                /apps/prod/hpc-stack/intel-19.1.3.304/netcdf/4.7.4/lib \
                /apps/prod/hpc-stack/intel-19.1.3.304/hdf5/*/lib \
                /apps/prod/hpc-stack/intel-*/netcdf/*/lib \
                /apps/prod/hpc-stack/intel-*/hdf5/*/lib; do
                [ -d "$_lib" ] && export LD_LIBRARY_PATH="${_lib}:${LD_LIBRARY_PATH:-}"
            done
            $COMBINE_EXE -i $nsteps
            local combine_err=$?
            if [ $combine_err -eq 0 ] && [ -s "hotstart_it=${nsteps}.nc" ]; then
                echo "  Hotstart combined successfully: hotstart_it=${nsteps}.nc"
                local _rst_name="${RUN}.${cycle}.${PDY}.rst.${phase}.nc"
                local _combined="hotstart_it=${nsteps}.nc"

                # Archive rst.${phase}.nc in combine_hotstart7's native HDF5
                # (NF90_NETCDF4) format -- DO NOT convert here.
                #
                # SCHISM-UFS at 2,914-rank scale has an inverted per-file
                # format rule (verified V19 jobid 262555114, 2026-05-11):
                #
                #   - rst.nowcast.nc consumed by FORECAST init: MUST stay HDF5.
                #     Converting to NETCDF4_CLASSIC here crashes the forecast
                #     at partition_hgrid:534 with SIGABRT + "double free or
                #     corruption" inside libpnetcdf.
                #
                #   - init.nowcast.nc consumed by NOWCAST init: MUST be
                #     NETCDF4_CLASSIC.  That conversion is done in nos-utils
                #     HotstartProcessor.stage_init_to_comout when prep stages
                #     the previous cycle's rst.${phase}.nc into THIS cycle's
                #     ${COMOUT}/${prefix}.t{cyc}z.{pdy}.init.nowcast.nc.
                #
                # So the chain is:
                #   combine_hotstart7 -> rst.${phase}.nc (HDF5, this archive)
                #     -> next cycle prep nccopy -> init.nowcast.nc (CLASSIC)
                #     -> nowcast hotstart.nc (CLASSIC).
                # Forecast reads rst.nowcast.nc directly (HDF5).

                cp -p "$_combined" "${COMOUT}/${_rst_name}"
                echo "  Archived to ${COMOUT}/${_rst_name} (NETCDF4/HDF5 — native combine output, do not convert)"
            else
                echo "WARNING: combine_hotstart7 failed (rc=$combine_err) or output missing"
            fi
        else
            echo "WARNING: schism_combine_hotstart7.exe not found"
            local combined=$(ls hotstart_it=*.nc 2>/dev/null | tail -1)
            if [ -n "$combined" ] && [ -s "$combined" ]; then
                local _rst_name="${RUN}.${cycle}.${PDY}.rst.${phase}.nc"
                cp -p "$combined" "${COMOUT}/${_rst_name}"
                echo "  Found pre-combined hotstart: $combined, archived as ${_rst_name}"
            fi
        fi
        cd ${DATA}
    fi

    echo "UFS-Coastal $phase execution completed normally"
    msg="UFS-Coastal $phase execution completed normally"
    postmsg "${jlogfile:-/dev/null}" "$msg" 2>/dev/null || true
    return 0
}

#-----------------------------------------------------------------------------
# _schism_archive_outputs - Archive SCHISM outputs to $COMOUT
#
#    UFS-Coastal naming differs from legacy COMF, so we skip nos_ofs_archive.sh
#    (which expects COMF naming).  We archive:
#      - nowcast: restart_outputs (mirror.out, flux.out, staout_*) for the
#                 forecast job to consume in split-job mode
#      - forecast: forecast_outputs (staout_*) for post-processing
#-----------------------------------------------------------------------------
_schism_archive_outputs() {
    local phase=$1

    # UFS-Coastal: skip nos_ofs_archive.sh (file naming differs).
    echo "Skipping nos_ofs_archive.sh for UFS-Coastal (file naming differs)"

    # Nowcast: archive restart outputs for forecast / ensemble.
    # SCHISM open(status='old') needs mirror.out/flux.out to exist; ensemble
    # (ihot=2) also needs real staout files to append to.
    # NOTE: nos_ofs_nowcast_forecast.sh historically renamed
    # $DATA/outputs -> $DATA/outputs_nowcast after nowcast.  Check both.
    if [ "$phase" = "nowcast" ]; then
        local outputs_dir=""
        if   [ -d "$DATA/outputs" ];          then outputs_dir="$DATA/outputs"
        elif [ -d "$DATA/outputs_nowcast" ];  then outputs_dir="$DATA/outputs_nowcast"
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

    # Forecast: archive staout files for post-processing
    if [ "$phase" = "forecast" ]; then
        local outputs_dir=""
        [ -d "$DATA/outputs" ] && outputs_dir="$DATA/outputs"
        if [ -n "$outputs_dir" ]; then
            local fcast_staout_dir="${COMOUT}/${RUN}.${cycle}.forecast_outputs"
            mkdir -p "$fcast_staout_dir"
            for f in staout_1 staout_2 staout_3 staout_4 staout_5 \
                     staout_6 staout_7 staout_8 staout_9; do
                [ -f "$outputs_dir/$f" ] && cp -p "$outputs_dir/$f" "$fcast_staout_dir/"
            done
            echo "Archived forecast staout files to $fcast_staout_dir"
        fi
    fi
}

# End of nos_run.sh
