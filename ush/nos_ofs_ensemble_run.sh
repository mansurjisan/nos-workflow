#!/bin/bash
################################################################################
#  Name: nos_ofs_ensemble_run.sh
#  Purpose: Ensemble-specific model run functions for NOS OFS systems.
#           Provides a 6-step interface for ensemble member runs.
#
#  Usage:
#     source ${USHnos}/nos_ofs_ensemble_run.sh
#     ensemble_generate_params
#     ensemble_stage_files
#     ensemble_configure_runtime
#     ensemble_prepare_restart
#     ensemble_execute_model
#     ensemble_archive_outputs
#
#  Environment Requirements:
#     OFS_FRAMEWORK   - "stofs", "comf", or "adcirc"
#     MEMBER_ID       - Ensemble member ID (e.g., 000, 001)
#     MEMBER_DATA     - Member working directory
#     DATA            - Parent working directory
#     COMOUT          - Output directory
#     ENSEMBLE_COMOUT - Member output directory ($COMOUT/ensemble/member_XXX)
#     PARAM_FILE      - (set by ensemble_generate_params)
#
################################################################################


################################################################################
# Step 1: Generate ensemble parameter perturbations
#
# Runs the Python param_generator for all members, then validates that
# this member's params.json was produced.  Sets PARAM_FILE.
################################################################################
ensemble_generate_params() {
    echo "=== ensemble_generate_params: member ${MEMBER_ID} ==="

    export PYTHONPATH=${HOMEnos}/ush/python:${PYTHONPATH:-}

    mkdir -p ${DATA}/ensemble_params

    python3 -m nos_ofs.ensemble.param_generator \
        "${OFS_CONFIG}" \
        --seed ${ENSEMBLE_SEED:-42} \
        --output-dir ${DATA}/ensemble_params \
        --json > ${DATA}/ensemble_params/all_members.json
    local rc=$?
    if [ $rc -ne 0 ]; then
        echo "FATAL: param_generator failed (exit code $rc)" >&2
        cat ${DATA}/ensemble_params/all_members.json 2>/dev/null || true
        return $rc
    fi

    export PARAM_FILE=${DATA}/ensemble_params/member_${MEMBER_ID}/params.json

    if [ ! -f "${PARAM_FILE}" ]; then
        echo "FATAL: Parameter file not found: ${PARAM_FILE}" >&2
        ls -lR ${DATA}/ensemble_params/ >&2 2>/dev/null || true
        return 1
    fi

    echo "Parameter overrides for member ${MEMBER_ID}:"
    cat ${PARAM_FILE}

    return 0
}


################################################################################
# Step 2: Stage static files and forcing for this member
#
# Links fix files, creates SCHISM bare-name symlinks, and stages atmospheric,
# ocean boundary, and river forcing from COMOUT/COMOUTrerun archives.
################################################################################
ensemble_stage_files() {
    echo "=== ensemble_stage_files: member ${MEMBER_ID} (framework: ${OFS_FRAMEWORK}) ==="

    cd ${MEMBER_DATA}

    case "${OFS_FRAMEWORK}" in
        adcirc)
            # ADCIRC does not use sflux/ directory; uses fort.* files directly
            _ensemble_adcirc_stage_static_files
            _ensemble_adcirc_stage_forcing
            ;;
        *)
            # SCHISM (stofs/comf) uses sflux/ and outputs/ directories
            mkdir -p ${MEMBER_DATA}/sflux ${MEMBER_DATA}/outputs

            # 2a: Link fix files and create bare-name symlinks
            _ensemble_stage_static_files

            # 2b: Stage atmospheric, OBC, and river forcing
            _ensemble_stage_forcing
            ;;
    esac

    echo "Ensemble file staging complete for member ${MEMBER_ID}"

    return 0
}


################################################################################
# Step 3: Configure param.nml for this member
#
# Copies the forecast param.nml, sets ihot=1, updates start_year/month/day/hour
# and rnday to match the forecast window, then applies LHS perturbations.
################################################################################
ensemble_configure_runtime() {
    echo "=== ensemble_configure_runtime: member ${MEMBER_ID} ==="

    cd ${MEMBER_DATA}

    case "${OFS_FRAMEWORK}" in
        adcirc)
            # ADCIRC uses fort.15 (plain text), not param.nml (Fortran namelist)
            _ensemble_adcirc_prepare_fort15
            local rc=$?
            if [ $rc -ne 0 ]; then return $rc; fi

            # Apply parameter perturbations via sed on fort.15
            _ensemble_adcirc_apply_perturbations
            ;;
        *)
            # SCHISM: copy param.nml, set ihot, update times, apply perturbations
            # 3a: Copy param.nml (forecast version from COMOUT or FIX fallback)
            _ensemble_copy_param_nml
            local rc=$?
            if [ $rc -ne 0 ]; then return $rc; fi

            # 3b: Set ihot=2 for hot restart with continued output
            # ihot=1: reads hotstart.nc but starts output from scratch (forecast-only staout)
            # ihot=2: reads hotstart.nc AND continues output (appends forecast to nowcast staout)
            # ihot=2 gives continuous nowcast+forecast timeseries in staout files.
            # Requires real staout/mirror/flux files from the deterministic nowcast
            # (restored in ensemble_prepare_restart).
            sed -i 's/ihot *= *[0-9]*/ihot = 2/' ${MEMBER_DATA}/param.nml
            echo "Set ihot=2 for hot restart with continued output (nowcast+forecast staout)"

            # 3c: Update start time and rnday for forecast period
            _ensemble_update_start_time

            # 3d: Apply parameter perturbations from params.json
            _ensemble_apply_perturbations
            ;;
    esac

    return 0
}


################################################################################
# Step 4: Prepare restart (hotstart + output state files)
#
# Finds the hotstart file from the deterministic nowcast in $COMOUT and
# restores SCHISM output state files (staout, mirror.out, flux.out).
################################################################################
ensemble_prepare_restart() {
    echo "=== ensemble_prepare_restart: member ${MEMBER_ID} ==="

    if [ "${OFS_FRAMEWORK}" = "adcirc" ]; then
        # ADCIRC restart is handled within _ensemble_adcirc_execute via
        # hotstart/restart files from the deterministic nowcast (fort.67/68).
        # The execute function stages these directly from COMOUT/COMOUTrerun.
        echo "ADCIRC restart preparation deferred to execute phase"
        return 0
    fi

    # Search for hotstart file in COMOUT (archived by nowcast job)
    # STOFS naming: ${RUN}.t${cyc}z.hotstart.stofs3d.nc
    # COMF naming:  ${PREFIXNOS}.${cycle}.${PDY}.rst.nowcast.nc
    local HOTSTART_FILE=""
    for candidate in \
        "${COMOUT}/${RUN}.${cycle}.hotstart.stofs3d.nc" \
        "${COMOUT}/${PREFIXNOS}.${cycle}.${PDY}.rst.nowcast.nc" \
        "${COMOUT}/${RUN}.${cycle}.${PDY}.rst.nowcast.nc" \
        "${COMOUT}/${PREFIXNOS}.${cycle}.rst.nowcast.nc" \
        "${COMOUT}/${PREFIXNOS}.${cycle}.hotstart.nc" \
        "${COMOUT}/hotstart.nc"; do
        if [ -f "${candidate}" ]; then
            HOTSTART_FILE="${candidate}"
            break
        fi
    done

    if [ -n "${HOTSTART_FILE}" ]; then
        echo "Linking hotstart: ${HOTSTART_FILE}"
        ln -sf "${HOTSTART_FILE}" ${MEMBER_DATA}/hotstart.nc
    else
        echo "WARNING: No hotstart file found in ${COMOUT}"
        echo "Checked patterns: ${RUN}.${cycle}.hotstart.stofs3d.nc, ${PREFIXNOS}.${cycle}.${PDY}.rst.nowcast.nc, etc."
        ls ${COMOUT}/*rst* ${COMOUT}/*hotstart* 2>/dev/null || echo "No restart/hotstart files found"
    fi

    # Restore staout/mirror/flux files from deterministic nowcast (ihot=2 requirement).
    # With ihot=2, SCHISM appends forecast output to existing staout files,
    # giving continuous nowcast+forecast timeseries.  Real nowcast staout files
    # are required -- empty files cause EOF errors.
    mkdir -p ${MEMBER_DATA}/outputs
    local RESTART_OUTPUTS_DIR="${COMOUT}/${RUN}.${cycle}.restart_outputs"
    local _has_staout=false
    if [ -d "${RESTART_OUTPUTS_DIR}" ]; then
        echo "Restoring restart output files from ${RESTART_OUTPUTS_DIR}"
        for f in mirror.out flux.out staout_1 staout_2 staout_3 staout_4 \
                 staout_5 staout_6 staout_7 staout_8 staout_9; do
            if [ -f "${RESTART_OUTPUTS_DIR}/$f" ]; then
                cp -p "${RESTART_OUTPUTS_DIR}/$f" ${MEMBER_DATA}/outputs/
            fi
        done
        # Check if staout_1 has real data (not empty)
        if [ -s "${MEMBER_DATA}/outputs/staout_1" ]; then
            _has_staout=true
            echo "Nowcast staout files restored -- ihot=2 will produce continuous timeseries"
        fi
    else
        echo "WARNING: restart_outputs dir not found: ${RESTART_OUTPUTS_DIR}"
    fi

    # If nowcast staout files are missing, fall back to ihot=1 (forecast-only output)
    if [ "${_has_staout}" = "false" ]; then
        echo "WARNING: No nowcast staout data available -- falling back to ihot=1"
        echo "Station timeseries will contain forecast period only"
        sed -i 's/ihot *= *[0-9]*/ihot = 1/' ${MEMBER_DATA}/param.nml
    fi

    # Ensure all required output state files exist (touch creates only if missing)
    touch ${MEMBER_DATA}/outputs/mirror.out
    touch ${MEMBER_DATA}/outputs/flux.out
    for i in 1 2 3 4 5 6 7 8 9; do
        [ ! -f "${MEMBER_DATA}/outputs/staout_${i}" ] && touch "${MEMBER_DATA}/outputs/staout_${i}"
    done

    return 0
}


################################################################################
# Step 5: Run SCHISM model for this member
#
# Verifies critical input files, finds the SCHISM executable, and runs
# mpiexec.  Checks mirror.out for successful completion.
################################################################################
ensemble_execute_model() {
    echo "=== ensemble_execute_model: member ${MEMBER_ID} ==="

    cd ${MEMBER_DATA}

    if [ "${OFS_FRAMEWORK}" = "adcirc" ]; then
        _ensemble_adcirc_execute
        return $?
    fi

    # --- Verify critical input files (SCHISM) ---
    local MISSING=0
    for required in param.nml hotstart.nc bctides.in flux.th; do
        if [ ! -e "${MEMBER_DATA}/${required}" ]; then
            echo "MISSING: ${required}"
            MISSING=$((MISSING + 1))
        else
            echo "OK: ${required}"
        fi
    done

    # Check sflux
    if ! ls ${MEMBER_DATA}/sflux/sflux_air_*.nc 1>/dev/null 2>&1; then
        echo "MISSING: sflux/sflux_air_*.nc (meteorological forcing)"
        MISSING=$((MISSING + 1))
    else
        echo "OK: sflux files ($(ls ${MEMBER_DATA}/sflux/sflux_air_*.nc | wc -l) air files)"
    fi

    # Check grid files (SCHISM requires bare names)
    for grid_file in hgrid.gr3 vgrid.in; do
        if [ -e "${MEMBER_DATA}/${grid_file}" ]; then
            echo "OK: ${grid_file}"
        else
            echo "MISSING: ${grid_file}"
            MISSING=$((MISSING + 1))
        fi
    done

    if [ $MISSING -gt 0 ]; then
        echo "FATAL: ${MISSING} required input files missing. Cannot run SCHISM." >&2
        ls -la ${MEMBER_DATA}/ >&2
        ls -la ${MEMBER_DATA}/sflux/ >&2 2>/dev/null || true
        return 1
    fi

    echo ""
    echo "Working directory listing:"
    ls -la ${MEMBER_DATA}/
    echo ""
    echo "sflux directory:"
    ls -la ${MEMBER_DATA}/sflux/ 2>/dev/null || echo "(no sflux dir)"

    # --- Determine MPI task count ---
    # Priority: explicit TOTAL_TASKS (from PBS script) > PBS_NODEFILE > default
    # STOFS partition.prop requires an exact match, so PBS scripts must set TOTAL_TASKS.
    if [ -n "${TOTAL_TASKS:-}" ]; then
        : # already set by PBS script -- use it (required for partition.prop match)
    elif [ -n "${PBS_NODEFILE:-}" ] && [ -f "${PBS_NODEFILE}" ]; then
        TOTAL_TASKS=$(wc -l < ${PBS_NODEFILE})
    else
        TOTAL_TASKS=1200  # default for SECOFS (10 nodes x 120 mpiprocs)
    fi
    export TOTAL_TASKS

    # Number of SCHISM I/O scribes (dedicated I/O processes)
    local _nscribes=${NSCRIBES:-7}

    # --- Find SCHISM executable ---
    local SCHISM_EXEC=""
    case "${OFS_FRAMEWORK}" in
        stofs)
            # STOFS naming: stofs_3d_atl_pschism (matches deterministic run)
            SCHISM_EXEC=${EXECstofs3d}/${RUN}_pschism
            [ ! -x "${SCHISM_EXEC}" ] && SCHISM_EXEC=${EXECstofs3d}/pschism_TVD-VL
            [ ! -x "${SCHISM_EXEC}" ] && SCHISM_EXEC=${EXECstofs3d}/schism_${OFS}
            ;;
        comf|*)
            # COMF naming: schism_${RUN} (e.g., schism_secofs)
            SCHISM_EXEC=${EXECnos}/schism_${RUN}
            [ ! -x "${SCHISM_EXEC}" ] && SCHISM_EXEC=${EXECnos}/${PREFIXNOS}
            ;;
    esac

    if [ ! -x "${SCHISM_EXEC}" ]; then
        echo "FATAL: SCHISM executable not found" >&2
        echo "  EXECstofs3d=${EXECstofs3d:-not set}" >&2
        echo "  EXECnos=${EXECnos:-not set}" >&2
        ls -la ${EXECstofs3d:-/dev/null}/ ${EXECnos:-/dev/null}/ 2>/dev/null || true
        return 1
    fi

    echo "Executable: ${SCHISM_EXEC}"
    echo "TOTAL_TASKS: ${TOTAL_TASKS}"
    echo "NSCRIBES: ${_nscribes}"
    echo "Working dir: ${MEMBER_DATA}"
    echo "Member ID: ${MEMBER_ID}"

    # Verify param.nml content before running
    echo "=== param.nml key settings ==="
    grep -E 'rnday|ihot|start_year|start_month|start_day|start_hour|nhot_write' \
        ${MEMBER_DATA}/param.nml 2>/dev/null || true
    echo "=== end param.nml ==="

    # --- Run SCHISM with MPI ---
    # Apply LD_PRELOAD for COMF Fortran executables only at model execution time.
    # Setting it earlier causes Python scripts (param_generator, staging) to segfault.
    if [ -n "${COMF_LD_PRELOAD:-}" ]; then
        export LD_PRELOAD="${COMF_LD_PRELOAD}:${LD_PRELOAD:-}"
        echo "LD_PRELOAD set for COMF Fortran: ${LD_PRELOAD}"
    fi
    echo "SCHISM simulation began at: $(date)"
    mpiexec -n ${TOTAL_TASKS} ${SCHISM_EXEC} ${_nscribes} \
        > ${MEMBER_DATA}/${RUN}.${cycle}.member_${MEMBER_ID}.log 2>&1
    export err=$?
    echo "SCHISM simulation ended at: $(date)"

    # Check for successful completion via mirror.out
    if [ -s "${MEMBER_DATA}/outputs/mirror.out" ]; then
        if grep -q "Run completed successfully" ${MEMBER_DATA}/outputs/mirror.out 2>/dev/null; then
            echo "SCHISM member ${MEMBER_ID} completed successfully"
        else
            echo "WARNING: mirror.out exists but no success message"
            tail -5 ${MEMBER_DATA}/outputs/mirror.out
        fi
    else
        echo "WARNING: mirror.out not found or empty"
    fi

    if [ $err -ne 0 ]; then
        echo "FATAL: SCHISM failed for member ${MEMBER_ID} (exit code: ${err})" >&2
        return $err
    fi
}


################################################################################
# Step 6: Archive member output to COMOUT
#
# Copies SCHISM NetCDF outputs and parameter provenance to ENSEMBLE_COMOUT.
################################################################################
ensemble_archive_outputs() {
    echo "=== ensemble_archive_outputs: member ${MEMBER_ID} ==="

    case "${OFS_FRAMEWORK}" in
        adcirc)
            _ensemble_adcirc_collect_output
            ;;
        *)
            # Copy outputs to ensemble COMOUT
            # SCHISM writes split output: out2d_*.nc, temperature_*.nc, salinity_*.nc
            # (not combined schout_*.nc when using I/O scribes)
            if [ -d "${MEMBER_DATA}/outputs" ]; then
                mkdir -p ${ENSEMBLE_COMOUT}/outputs
                for pattern in out2d_*.nc temperature_*.nc salinity_*.nc \
                               horizontalVelX_*.nc horizontalVelY_*.nc \
                               schout_*.nc staout_*; do
                    cp ${MEMBER_DATA}/outputs/${pattern} ${ENSEMBLE_COMOUT}/outputs/ 2>/dev/null || true
                done
                # Report what was archived
                local N_ARCHIVED=$(ls ${ENSEMBLE_COMOUT}/outputs/*.nc 2>/dev/null | wc -l)
                echo "Archived ${N_ARCHIVED} NetCDF files to ${ENSEMBLE_COMOUT}/outputs/"
            fi
            ;;
    esac

    # Save parameter overrides for provenance
    cp ${PARAM_FILE} ${ENSEMBLE_COMOUT}/params.json

    echo "Member ${MEMBER_ID} output archived to ${ENSEMBLE_COMOUT}"

    return 0
}


################################################################################
#
#  INTERNAL HELPER FUNCTIONS
#
################################################################################

#-------------------------------------------------------------------------------
# Stage static fix files and create SCHISM bare-name symlinks
#
# Links all fix files from FIXofs (and FIXstofs3d if different), then strips
# the OFS prefix to create bare names (e.g., stofs_3d_atl_hgrid.gr3 -> hgrid.gr3).
# Also creates STOFS-specific special name mappings and vgrid_nu.in.
#-------------------------------------------------------------------------------
_ensemble_stage_static_files() {
    # --- Link fix files from FIXofs ---
    if [ -d "${FIXofs}" ]; then
        echo "Linking fix files from ${FIXofs}"
        for f in ${FIXofs}/*; do
            ln -sf "$f" ${MEMBER_DATA}/$(basename "$f")
        done
    fi

    # Link STOFS fix files if framework is stofs and directory differs from FIXofs
    if [ "${OFS_FRAMEWORK}" = "stofs" ] && [ -d "${FIXstofs3d}" ] && \
       [ "${FIXstofs3d}" != "${FIXofs}" ]; then
        for f in ${FIXstofs3d}/*; do
            local bname=$(basename "$f")
            [ ! -e "${MEMBER_DATA}/${bname}" ] && ln -sf "$f" ${MEMBER_DATA}/${bname}
        done
    fi

    # --- Create SCHISM-required bare-name symlinks ---
    # SCHISM expects hgrid.gr3, hgrid.ll, vgrid.in etc. without the OFS prefix.
    # COMF uses dot separator: secofs.hgrid.gr3 -> hgrid.gr3
    # STOFS uses underscore separator: stofs_3d_atl_hgrid.gr3 -> hgrid.gr3
    # EXCLUDE param.nml and bctides.in -- handled separately.
    local _PREFIX_SEP
    if [ "${OFS_FRAMEWORK}" = "stofs" ]; then
        _PREFIX_SEP="${PREFIXNOS}_"
    else
        _PREFIX_SEP="${PREFIXNOS}."
    fi

    echo "Creating SCHISM bare-name symlinks (stripping ${_PREFIX_SEP} prefix)"
    for f in ${MEMBER_DATA}/${_PREFIX_SEP}*; do
        [ ! -e "$f" ] && continue
        local bname=$(basename "$f")
        local bare=${bname#${_PREFIX_SEP}}
        # Skip param.nml and bctides.in -- handled separately
        case "${bare}" in
            param.nml|param.nml_6globaloutput|bctides.in|bctides.in_template) continue ;;
        esac
        if [ ! -e "${MEMBER_DATA}/${bare}" ]; then
            ln -sf "$f" ${MEMBER_DATA}/${bare}
            echo "  ${bname} -> ${bare}"
        fi
    done

    # --- STOFS special name mappings ---
    # The automated bare-name loop strips ${PREFIXNOS}_ but some SCHISM files
    # have different target names than the bare remainder.  These match the
    # explicit symlinks in exstofs_3d_atl_prep_processing.sh (lines 69-88).
    if [ "${OFS_FRAMEWORK}" = "stofs" ]; then
        # river_source_sink.in -> source_sink.in
        [ -e "${MEMBER_DATA}/river_source_sink.in" ] && \
            ln -sf "${MEMBER_DATA}/river_source_sink.in" ${MEMBER_DATA}/source_sink.in
        # river_msource.th -> msource.th
        [ -e "${MEMBER_DATA}/river_msource.th" ] && \
            ln -sf "${MEMBER_DATA}/river_msource.th" ${MEMBER_DATA}/msource.th
        # river_vsink.th -> vsink.th
        [ -e "${MEMBER_DATA}/river_vsink.th" ] && \
            ln -sf "${MEMBER_DATA}/river_vsink.th" ${MEMBER_DATA}/vsink.th
        # tem_nudge.gr3 -> TEM_nudge.gr3 (SCHISM expects uppercase)
        [ -e "${MEMBER_DATA}/tem_nudge.gr3" ] && [ ! -e "${MEMBER_DATA}/TEM_nudge.gr3" ] && \
            ln -sf "${MEMBER_DATA}/tem_nudge.gr3" ${MEMBER_DATA}/TEM_nudge.gr3
        # sal_nudge.gr3 -> SAL_nudge.gr3 (SCHISM expects uppercase)
        [ -e "${MEMBER_DATA}/sal_nudge.gr3" ] && [ ! -e "${MEMBER_DATA}/SAL_nudge.gr3" ] && \
            ln -sf "${MEMBER_DATA}/sal_nudge.gr3" ${MEMBER_DATA}/SAL_nudge.gr3
        echo "Created STOFS special name mappings (source_sink.in, msource.th, TEM/SAL_nudge)"
    fi

    # --- Create vgrid_nu.in for nudging ---
    # SCHISM nudging expects vgrid_nu.in (a copy of vgrid.in with underscore name).
    local _vgrid_src="${FIXofs}/${_PREFIX_SEP}vgrid.in"
    if [ -f "${_vgrid_src}" ]; then
        cp -p "${_vgrid_src}" ${MEMBER_DATA}/vgrid_nu.in
        echo "Created vgrid_nu.in from $(basename ${_vgrid_src})"
    fi

    return 0
}


#-------------------------------------------------------------------------------
# Stage atmospheric, OBC, and river forcing for this member
#
# Reads atmospheric_source from params.json and dispatches to framework-specific
# staging functions (STOFS copies from COMOUTrerun, COMF extracts from tars).
#-------------------------------------------------------------------------------
_ensemble_stage_forcing() {
    # --- Read atmospheric source configuration from params.json ---
    local ATMOS_MET1="" ATMOS_MET2="" ATMOS_LABEL="" ATMOS_CONFIGURED=false

    local _atmos_output
    _atmos_output=$(python3 -c "
import json, os, sys
pf = os.environ.get('PARAM_FILE', '')
if not pf or not os.path.isfile(pf):
    sys.exit(1)
with open(pf) as f:
    m = json.load(f)
atm = m.get('atmospheric_source')
if not atm:
    sys.exit(1)
print(atm.get('met_source_1', ''))
print(atm.get('met_source_2') or '')
print(atm.get('label', ''))
" 2>/dev/null) && ATMOS_CONFIGURED=true

    if [ "${ATMOS_CONFIGURED}" = true ]; then
        ATMOS_MET1=$(echo "${_atmos_output}" | sed -n '1p')
        ATMOS_MET2=$(echo "${_atmos_output}" | sed -n '2p')
        ATMOS_LABEL=$(echo "${_atmos_output}" | sed -n '3p')
        echo "Atmospheric source config: met1=${ATMOS_MET1}, met2=${ATMOS_MET2} (${ATMOS_LABEL})"
    fi

    # --- Stage atmospheric forcing ---
    # Note: adcirc is handled separately by _ensemble_adcirc_stage_forcing
    case "${OFS_FRAMEWORK}" in
        stofs) _ensemble_stofs_stage_atmos "${ATMOS_MET1}" "${ATMOS_MET2}" "${ATMOS_LABEL}" "${ATMOS_CONFIGURED}" ;;
        comf)  _ensemble_comf_stage_atmos  "${ATMOS_MET1}" "${ATMOS_MET2}" "${ATMOS_LABEL}" "${ATMOS_CONFIGURED}" ;;
    esac

    # --- Stage OBC, river, and tidal forcing ---
    case "${OFS_FRAMEWORK}" in
        stofs) _ensemble_stofs_stage_obc_river ;;
        comf)  _ensemble_comf_stage_obc_river  ;;
    esac

    # --- Rename schism_* river files to bare names ---
    # river.th.tar contains schism_flux.th, schism_temp.th, schism_salt.th
    # but SCHISM reads flux.th, salt.th (and TEM_1.th for itetype=1 boundaries)
    for f in ${MEMBER_DATA}/schism_*.th; do
        [ ! -f "$f" ] && continue
        local bare=$(basename "$f" | sed 's/^schism_//')
        mv "$f" "${MEMBER_DATA}/${bare}"
        echo "  Renamed $(basename $f) -> ${bare}"
    done

    # Create TEM_1.th for river boundaries with itetype=1 in bctides.in.
    # The deterministic run does: cp schism_temp.th -> TEM_1.th
    if [ -f "${MEMBER_DATA}/temp.th" ] && [ ! -f "${MEMBER_DATA}/TEM_1.th" ]; then
        cp "${MEMBER_DATA}/temp.th" "${MEMBER_DATA}/TEM_1.th"
        echo "Created TEM_1.th from temp.th (for itetype=1 river boundaries)"
    fi

    # --- Copy bctides.in ---
    # STOFS already handled in _ensemble_stofs_stage_obc_river.
    # COMF: copy from COMOUT forecast archive.
    if [ "${OFS_FRAMEWORK}" != "stofs" ]; then
        rm -f ${MEMBER_DATA}/bctides.in
        local BCTIDES_SRC="${COMOUT}/${PREFIXNOS}.${cycle}.${PDY}.bctides.in.forecast"
        if [ -f "${BCTIDES_SRC}" ]; then
            echo "Copying bctides.in from ${BCTIDES_SRC}"
            cp "${BCTIDES_SRC}" ${MEMBER_DATA}/bctides.in
        else
            echo "WARNING: bctides.in.forecast not found in COMOUT: ${BCTIDES_SRC}"
            echo "  Falling back to FIX template"
            [ -f "${FIXofs}/${PREFIXNOS}.bctides.in" ] && \
                cp "${FIXofs}/${PREFIXNOS}.bctides.in" ${MEMBER_DATA}/bctides.in
        fi
    fi

    return 0
}


#-------------------------------------------------------------------------------
# STOFS: Stage atmospheric forcing from COMOUTrerun
#
# STOFS forcing scripts write individual NetCDF files (not tars) to COMOUTrerun:
#   ${RUN}.${cycle}.gfs.{air,prc,rad}.nc   (GFS, sflux stack 1)
#   ${RUN}.${cycle}.hrrr.{air,prc,rad}.nc  (HRRR, sflux stack 2)
#   ${RUN}.${cycle}.gefs_XX.{air,prc,rad}.nc (GEFS members)
#   ${RUN}.${cycle}.nam.{air,prc,rad}.nc   (NAM, sflux stack 2 for ensemble)
#
# Arguments: ATMOS_MET1 ATMOS_MET2 ATMOS_LABEL ATMOS_CONFIGURED
#-------------------------------------------------------------------------------
_ensemble_stofs_stage_atmos() {
    local ATMOS_MET1=$1 ATMOS_MET2=$2 ATMOS_LABEL=$3 ATMOS_CONFIGURED=$4
    local N_MET_SOURCES=1

    export COMOUTrerun=${COMOUTrerun:-${COMOUT}/rerun}

    if [ "${ATMOS_CONFIGURED}" = true ] && [ -n "${ATMOS_MET1}" ]; then
        # --- Source 1 (primary, sflux stack 1) ---
        local SRC1
        if [[ "${ATMOS_MET1}" == GEFS_* ]]; then
            # GEFS member: GEFS_01 -> gefs_01, GEFS_c00 -> gefs_c00
            local GEFS_ID=$(echo "${ATMOS_MET1}" | sed 's/GEFS_//')
            SRC1="gefs_${GEFS_ID}"
        else
            SRC1=$(echo "${ATMOS_MET1}" | tr '[:upper:]' '[:lower:]')
        fi
        for var in air prc rad; do
            local src="${COMOUTrerun}/${RUN}.${cycle}.${SRC1}.${var}.nc"
            local dst="${MEMBER_DATA}/sflux/sflux_${var}_1.0001.nc"
            if [ -s "${src}" ]; then
                cp -p "${src}" "${dst}"
                echo "  sflux_${var}_1 <- ${SRC1}"
            else
                echo "ERROR: Primary sflux not found: ${src}" >&2
            fi
        done

        # --- Source 2 (secondary, sflux stack 2) ---
        if [ -n "${ATMOS_MET2}" ]; then
            local SRC2=$(echo "${ATMOS_MET2}" | tr '[:upper:]' '[:lower:]')
            for var in air prc rad; do
                local src="${COMOUTrerun}/${RUN}.${cycle}.${SRC2}.${var}.nc"
                local dst="${MEMBER_DATA}/sflux/sflux_${var}_2.0001.nc"
                if [ -s "${src}" ]; then
                    cp -p "${src}" "${dst}"
                    echo "  sflux_${var}_2 <- ${SRC2}"
                fi
            done
            N_MET_SOURCES=2
        else
            echo "Single-source member: no secondary met (${ATMOS_LABEL})"
        fi
    else
        # --- Default STOFS: GFS (stack 1) + HRRR (stack 2) -- same as deterministic ---
        for var in air prc rad; do
            [ -s "${COMOUTrerun}/${RUN}.${cycle}.gfs.${var}.nc" ] && \
                cp -p "${COMOUTrerun}/${RUN}.${cycle}.gfs.${var}.nc" "${MEMBER_DATA}/sflux/sflux_${var}_1.0001.nc"
        done
        N_MET_SOURCES=1
        for var in air prc rad; do
            if [ -s "${COMOUTrerun}/${RUN}.${cycle}.hrrr.${var}.nc" ]; then
                cp -p "${COMOUTrerun}/${RUN}.${cycle}.hrrr.${var}.nc" "${MEMBER_DATA}/sflux/sflux_${var}_2.0001.nc"
                N_MET_SOURCES=2
            fi
        done
    fi

    # Generate per-member sflux_inputs.txt
    _ensemble_generate_sflux_inputs "${N_MET_SOURCES}" "${ATMOS_MET1:-}" "${ATMOS_CONFIGURED}"

    return 0
}


#-------------------------------------------------------------------------------
# COMF: Stage atmospheric forcing from tar archives
#
# COMF prep job writes met forcing as tar archives to COMOUT:
#   ${PREFIXNOS}.${cycle}.${PDY}.met.forecast.nc.tar   (GFS, metnum=1)
#   ${PREFIXNOS}.${cycle}.${PDY}.met.forecast.nc.2.tar (HRRR, metnum=2)
#   ${PREFIXNOS}.${cycle}.${PDY}.met.forecast.GEFS_gepXX.nc.tar (GEFS members)
#
# Arguments: ATMOS_MET1 ATMOS_MET2 ATMOS_LABEL ATMOS_CONFIGURED
#-------------------------------------------------------------------------------
_ensemble_comf_stage_atmos() {
    local ATMOS_MET1=$1 ATMOS_MET2=$2 ATMOS_LABEL=$3 ATMOS_CONFIGURED=$4
    local N_MET_SOURCES=1

    if [ "${ATMOS_CONFIGURED}" = true ] && [ -n "${ATMOS_MET1}" ]; then
        # --- Source 1 (primary met, metnum=1 -> sflux_air_1.*.nc) ---

        if [ "${ATMOS_MET1}" = "RRFS" ]; then
            # RRFS uses sflux NetCDFs in COMOUTrerun (same as STOFS pipeline),
            # NOT tar archives.  The RRFS forcing script produces SCHISM-ready
            # sflux files directly via wgrib2/ncap2.
            # RRFS radiation variables (DSWRF/DLWRF) are encoded as averaged fields
            # in GRIB2, so wgrib2 -netcdf variable names don't match NCO expectations.
            # Stage air+prc from RRFS; use GFS rad from default prep output.
            #
            # COMF SCHISM uses .{N}.nc naming (sflux_air_1.1.nc), NOT .0001.nc.
            # The STOFS archival also sets time(0)=0.499999 making the time axis
            # non-monotonic; fix time(0) to 0.0 for COMF compatibility.
            local _COMOUTrerun=${COMOUTrerun:-${COMOUT}/rerun}
            echo "RRFS primary: staging sflux from ${_COMOUTrerun}"
            for var in air prc; do
                local src="${_COMOUTrerun}/${RUN}.${cycle}.rrfs.${var}.nc"
                local dst="${MEMBER_DATA}/sflux/sflux_${var}_1.1.nc"
                if [ -s "${src}" ]; then
                    cp -p "${src}" "${dst}"
                    # Fix non-monotonic time(0) from STOFS archival convention.
                    # Use Python netCDF4 for in-place edit (fast for large RRFS files);
                    # fall back to ncap2 (rewrites entire file, slow for multi-GB files).
                    python3 -c "
import netCDF4
with netCDF4.Dataset('${dst}', 'r+') as f:
    f.variables['time'][0] = 0.0
" 2>/dev/null || ncap2 -Oh -s 'time(0)=float(0.0)' "${dst}" "${dst}" 2>/dev/null || true
                    echo "  sflux_${var}_1 <- rrfs (time[0] fixed)"
                else
                    echo "WARNING: RRFS sflux not found: ${src}" >&2
                fi
            done
            # Radiation: check if RRFS rad exists (future-proof),
            # otherwise use GFS rad from default prep tar
            local rad_src="${_COMOUTrerun}/${RUN}.${cycle}.rrfs.rad.nc"
            if [ -s "${rad_src}" ]; then
                cp -p "${rad_src}" "${MEMBER_DATA}/sflux/sflux_rad_1.1.nc"
                python3 -c "
import netCDF4
with netCDF4.Dataset('${MEMBER_DATA}/sflux/sflux_rad_1.1.nc', 'r+') as f:
    f.variables['time'][0] = 0.0
" 2>/dev/null || ncap2 -Oh -s 'time(0)=float(0.0)' "${MEMBER_DATA}/sflux/sflux_rad_1.1.nc" "${MEMBER_DATA}/sflux/sflux_rad_1.1.nc" 2>/dev/null || true
                echo "  sflux_rad_1 <- rrfs (time[0] fixed)"
            else
                local _GFS_TAR="${COMOUT}/${PREFIXNOS}.${cycle}.${PDY}.met.forecast.nc.tar"
                if [ -f "${_GFS_TAR}" ]; then
                    echo "  sflux_rad_1 <- GFS (RRFS has no radiation data)"
                    # Extract ONLY sflux_rad; COMF tar uses .1.nc naming
                    tar xf "${_GFS_TAR}" -C ${MEMBER_DATA}/sflux/ sflux_rad_1.1.nc
                else
                    echo "  WARNING: No rad source (RRFS has no rad, GFS tar not found)"
                fi
            fi
        else
            # GFS/GEFS/other: use tar archives from COMOUT
            local MET1_TAR
            case "${ATMOS_MET1}" in
                GFS)
                    MET1_TAR="${COMOUT}/${PREFIXNOS}.${cycle}.${PDY}.met.forecast.nc.tar"
                    ;;
                GEFS_*)
                    # GEFS now uses sflux NetCDFs in COMOUTrerun (wgrib2/NCO pipeline),
                    # NOT tar archives.  Check COMOUTrerun first, fall back to tar.
                    local _GEFS_ID=$(echo "${ATMOS_MET1}" | sed 's/GEFS_//')
                    local _COMOUTrerun=${COMOUTrerun:-${COMOUT}/rerun}
                    local _gefs_found=false

                    # Try COMOUTrerun sflux NetCDFs first
                    if [ -s "${_COMOUTrerun}/${RUN}.${cycle}.gefs_${_GEFS_ID}.air.nc" ]; then
                        echo "GEFS primary: staging sflux from ${_COMOUTrerun} (member=${_GEFS_ID})"
                        # GEFS pgrb2sp25 has all 8 sflux variables including radiation.
                        # Stage air, prc, and rad from GEFS; fall back to GFS rad if missing.
                        #
                        # COMF SCHISM uses .{N}.nc naming (sflux_air_1.1.nc), NOT .0001.nc.
                        # The STOFS archival also sets time(0)=0.499999 making the time axis
                        # non-monotonic; fix time(0) to 0.0 for COMF compatibility.
                        for var in air prc; do
                            local src="${_COMOUTrerun}/${RUN}.${cycle}.gefs_${_GEFS_ID}.${var}.nc"
                            local dst="${MEMBER_DATA}/sflux/sflux_${var}_1.1.nc"
                            if [ -s "${src}" ]; then
                                cp -p "${src}" "${dst}"
                                # Fix non-monotonic time(0) from STOFS archival convention
                                ncap2 -Oh -s 'time(0)=float(0.0)' "${dst}" "${dst}" 2>/dev/null || true
                                echo "  sflux_${var}_1 <- gefs_${_GEFS_ID} (time[0] fixed)"
                            else
                                echo "WARNING: GEFS sflux not found: ${src}" >&2
                            fi
                        done
                        # Radiation: use GEFS rad if available,
                        # otherwise fall back to GFS rad from default prep tar
                        local rad_src="${_COMOUTrerun}/${RUN}.${cycle}.gefs_${_GEFS_ID}.rad.nc"
                        if [ -s "${rad_src}" ]; then
                            cp -p "${rad_src}" "${MEMBER_DATA}/sflux/sflux_rad_1.1.nc"
                            ncap2 -Oh -s 'time(0)=float(0.0)' "${MEMBER_DATA}/sflux/sflux_rad_1.1.nc" "${MEMBER_DATA}/sflux/sflux_rad_1.1.nc" 2>/dev/null || true
                            echo "  sflux_rad_1 <- gefs_${_GEFS_ID} (time[0] fixed)"
                        else
                            # Extract ONLY sflux_rad from default prep tar; COMF tar uses .1.nc naming
                            local _GFS_TAR="${COMOUT}/${PREFIXNOS}.${cycle}.${PDY}.met.forecast.nc.tar"
                            if [ -f "${_GFS_TAR}" ]; then
                                echo "  sflux_rad_1 <- GFS fallback (GEFS rad not found)"
                                tar xf "${_GFS_TAR}" -C ${MEMBER_DATA}/sflux/ sflux_rad_1.1.nc
                            else
                                echo "  WARNING: No rad source (GEFS rad missing, GFS tar not found)"
                            fi
                        fi
                        _gefs_found=true
                    fi

                    # Fall back to tar archives (legacy path)
                    if [ "${_gefs_found}" = false ]; then
                        local _GEFS_TAG
                        if [ "${_GEFS_ID}" = "c00" ] || [ "${_GEFS_ID}" = "00" ]; then
                            _GEFS_TAG="gec00"
                        else
                            _GEFS_TAG="gep$(printf '%02d' "${_GEFS_ID}" 2>/dev/null || echo "${_GEFS_ID}")"
                        fi
                        MET1_TAR="${COMOUT}/${PREFIXNOS}.${cycle}.${PDY}.met.forecast.GEFS_${_GEFS_TAG}.nc.tar"
                        [ ! -f "${MET1_TAR}" ] && \
                            MET1_TAR="${COMOUT}/${PREFIXNOS}.${cycle}.${PDY}.met.forecast.GEFS_${_GEFS_TAG}.tar"
                        echo "GEFS primary: member=${_GEFS_ID} tag=${_GEFS_TAG} (tar fallback)"
                    fi
                    ;;
                *)
                    MET1_TAR="${COMOUT}/${PREFIXNOS}.${cycle}.${PDY}.met.forecast.${ATMOS_MET1}.tar"
                    ;;
            esac

            # MET1_TAR is empty when GEFS sflux were already staged from COMOUTrerun
            if [ -n "${MET1_TAR}" ]; then
                if [ -f "${MET1_TAR}" ]; then
                    echo "Extracting primary met (${ATMOS_MET1}): $(basename ${MET1_TAR})"
                    tar xf "${MET1_TAR}" -C ${MEMBER_DATA}/sflux/
                else
                    echo "ERROR: Primary met tar not found: ${MET1_TAR}" >&2
                    echo "  Falling back to default GFS tar"
                    local FALLBACK_TAR="${COMOUT}/${PREFIXNOS}.${cycle}.${PDY}.met.forecast.nc.tar"
                    [ -f "${FALLBACK_TAR}" ] && tar xf "${FALLBACK_TAR}" -C ${MEMBER_DATA}/sflux/
                fi
            fi
        fi

        # --- Source 2 (secondary met, metnum=2 -> sflux_air_2.*.nc) ---
        if [ -n "${ATMOS_MET2}" ]; then
            local MET2_TAR
            case "${ATMOS_MET2}" in
                HRRR) MET2_TAR="${COMOUT}/${PREFIXNOS}.${cycle}.${PDY}.met.forecast.nc.2.tar" ;;
                *)    MET2_TAR="${COMOUT}/${PREFIXNOS}.${cycle}.${PDY}.met.forecast.${ATMOS_MET2}.tar" ;;
            esac
            if [ -f "${MET2_TAR}" ]; then
                echo "Extracting secondary met (${ATMOS_MET2}): $(basename ${MET2_TAR})"
                tar xf "${MET2_TAR}" -C ${MEMBER_DATA}/sflux/
            else
                echo "WARNING: Secondary met tar not found: ${MET2_TAR}"
            fi
            N_MET_SOURCES=2
        else
            echo "Single-source member: no secondary met (${ATMOS_LABEL})"
        fi
    else
        # --- Default behavior (no atmospheric ensemble, COMF) ---
        for tar_file in \
            "${COMOUT}/${PREFIXNOS}.${cycle}.${PDY}.met.forecast.nc.tar" \
            "${COMOUT}/${PREFIXNOS}.${cycle}.${PDY}.met.forecast.nc.2.tar"; do
            if [ -f "${tar_file}" ]; then
                echo "Extracting $(basename ${tar_file})"
                tar xf "${tar_file}" -C ${MEMBER_DATA}/sflux/
            else
                echo "WARNING: Not found: ${tar_file}"
            fi
        done
        # Determine N_MET_SOURCES from what was extracted
        if ls ${MEMBER_DATA}/sflux/sflux_air_2.*.nc 1>/dev/null 2>&1; then
            N_MET_SOURCES=2
        fi
    fi

    # Generate per-member sflux_inputs.txt
    _ensemble_generate_sflux_inputs "${N_MET_SOURCES}" "${ATMOS_MET1:-}" "${ATMOS_CONFIGURED}"

    return 0
}


#-------------------------------------------------------------------------------
# Generate sflux_inputs.txt based on number of atmospheric sources
#
# For single-source members, creates a 1-source namelist.
# For dual-source GEFS members, creates a custom namelist with 120h window.
# For default dual-source (GFS+HRRR), copies from FIX.
#
# Arguments: N_MET_SOURCES ATMOS_MET1 ATMOS_CONFIGURED
#-------------------------------------------------------------------------------
_ensemble_generate_sflux_inputs() {
    local N_MET_SOURCES=$1 ATMOS_MET1=$2 ATMOS_CONFIGURED=$3
    local _PRIMARY_WINDOW=120.

    if [ "${N_MET_SOURCES}" -eq 1 ]; then
        echo "Generating single-source sflux_inputs.txt (nfile=1)"
        cat > ${MEMBER_DATA}/sflux/sflux_inputs.txt << SFLUX_EOF
&sflux_inputs
air_1_relative_weight=1.,
air_1_max_window_hours=${_PRIMARY_WINDOW},
air_1_fail_if_missing=.true.,
air_1_file='sflux_air_1',
uwind_name='uwind',
vwind_name='vwind',
prmsl_name='prmsl',
stmp_name='stmp',
spfh_name='spfh',

rad_1_relative_weight=1.,
rad_1_max_window_hours=${_PRIMARY_WINDOW},
rad_1_fail_if_missing=.true.,
rad_1_file='sflux_rad_1',
dlwrf_name='dlwrf',
dswrf_name='dswrf',

prc_1_relative_weight=1.,
prc_1_max_window_hours=${_PRIMARY_WINDOW},
prc_1_fail_if_missing=.true.,
prc_1_file='sflux_prc_1',
prate_name='prate',
/
SFLUX_EOF
    elif ls ${MEMBER_DATA}/sflux/sflux_air_*.nc 1>/dev/null 2>&1; then
        # Dual-source: GEFS primary needs a custom sflux_inputs.txt because
        # the FIX default assumes GFS (hourly).  For GEFS (3-hourly) primary +
        # HRRR secondary, we generate one inline.  For GFS primary, copy from FIX.
        if [[ "${ATMOS_MET1:-}" == GEFS_* ]]; then
            echo "Generating GEFS+HRRR dual-source sflux_inputs.txt (GEFS=3-hourly primary)"
            cat > ${MEMBER_DATA}/sflux/sflux_inputs.txt << 'SFLUX_EOF'
&sflux_inputs
air_1_relative_weight=1.,
air_1_max_window_hours=120.,
air_1_fail_if_missing=.true.,
air_1_file='sflux_air_1',
uwind_name='uwind',
vwind_name='vwind',
prmsl_name='prmsl',
stmp_name='stmp',
spfh_name='spfh',

air_2_relative_weight=1.,
air_2_max_window_hours=120.,
air_2_fail_if_missing=.false.,
air_2_file='sflux_air_2',

rad_1_relative_weight=1.,
rad_1_max_window_hours=120.,
rad_1_fail_if_missing=.true.,
rad_1_file='sflux_rad_1',
dlwrf_name='dlwrf',
dswrf_name='dswrf',

rad_2_relative_weight=1.,
rad_2_max_window_hours=120.,
rad_2_fail_if_missing=.false.,
rad_2_file='sflux_rad_2',

prc_1_relative_weight=1.,
prc_1_max_window_hours=120.,
prc_1_fail_if_missing=.true.,
prc_1_file='sflux_prc_1',
prate_name='prate',

prc_2_relative_weight=1.,
prc_2_max_window_hours=120.,
prc_2_fail_if_missing=.false.,
prc_2_file='sflux_prc_2',
/
SFLUX_EOF
        elif [ "${OFS_FRAMEWORK}" = "stofs" ]; then
            # STOFS: sflux_inputs.txt is in FIXstofs3d with underscore naming
            if [ -f "${FIXstofs3d}/${RUN}_sflux_inputs.txt" ]; then
                cp "${FIXstofs3d}/${RUN}_sflux_inputs.txt" ${MEMBER_DATA}/sflux/sflux_inputs.txt
                echo "Copied dual-source sflux_inputs.txt from STOFS FIX"
            elif [ -f "${FIXofs}/${PREFIXNOS}.sflux_inputs.txt" ]; then
                cp "${FIXofs}/${PREFIXNOS}.sflux_inputs.txt" ${MEMBER_DATA}/sflux/sflux_inputs.txt
            fi
        else
            # COMF: copy from COMOUT or FIX
            if [ -f "${COMOUT}/sflux_inputs.txt" ]; then
                cp "${COMOUT}/sflux_inputs.txt" ${MEMBER_DATA}/sflux/sflux_inputs.txt
            elif [ -f "${FIXofs}/${PREFIXNOS}.sflux_inputs.txt" ]; then
                echo "Copying sflux_inputs.txt from FIX"
                cp "${FIXofs}/${PREFIXNOS}.sflux_inputs.txt" ${MEMBER_DATA}/sflux/sflux_inputs.txt
            fi
        fi
    fi

    return 0
}


#-------------------------------------------------------------------------------
# STOFS: Stage OBC and river forcing from COMOUTrerun
#-------------------------------------------------------------------------------
_ensemble_stofs_stage_obc_river() {
    echo "Staging STOFS OBC and river forcing from COMOUTrerun"

    export COMOUTrerun=${COMOUTrerun:-${COMOUT}/rerun}

    # RTOFS OBC 3D time-history files
    for pair in "elev2dth.nc:elev2D.th.nc" "tem3dth.nc:TEM_3D.th.nc" \
                "sal3dth.nc:SAL_3D.th.nc" "uv3dth.nc:uv3D.th.nc"; do
        local src_suffix="${pair%%:*}"
        local dst_name="${pair##*:}"
        local src="${COMOUTrerun}/${RUN}.${cycle}.${src_suffix}"
        if [ -s "${src}" ]; then
            cp -p "${src}" "${MEMBER_DATA}/${dst_name}"
            echo "  ${dst_name} <- ${src_suffix}"
        fi
    done

    # River forcing (NWM)
    for f in msource.th vsink.th vsource.th; do
        [ -s "${COMOUTrerun}/${RUN}.${cycle}.$f" ] && \
            cp -p "${COMOUTrerun}/${RUN}.${cycle}.$f" "${MEMBER_DATA}/$f"
    done

    # St. Lawrence River
    [ -s "${COMOUTrerun}/${RUN}.${cycle}.riv.obs.flux.th" ] && \
        cp -p "${COMOUTrerun}/${RUN}.${cycle}.riv.obs.flux.th" "${MEMBER_DATA}/flux.th"
    [ -s "${COMOUTrerun}/${RUN}.${cycle}.riv.obs.tem_1.th" ] && \
        cp -p "${COMOUTrerun}/${RUN}.${cycle}.riv.obs.tem_1.th" "${MEMBER_DATA}/TEM_1.th"

    # RTOFS nudging files (time-varying, generated by prep's obc_nudge script)
    for pair in "temnu.nc:TEM_nu.nc" "salnu.nc:SAL_nu.nc"; do
        local src_suffix="${pair%%:*}"
        local dst_name="${pair##*:}"
        local src="${COMOUTrerun}/${RUN}.${cycle}.${src_suffix}"
        if [ -s "${src}" ]; then
            cp -p "${src}" "${MEMBER_DATA}/${dst_name}"
            echo "  ${dst_name} <- ${src_suffix}"
        fi
    done

    # Tidal forcing (bctides.in)
    if [ -s "${COMOUTrerun}/${RUN}.${cycle}.bctides.in" ]; then
        rm -f ${MEMBER_DATA}/bctides.in
        cp -p "${COMOUTrerun}/${RUN}.${cycle}.bctides.in" "${MEMBER_DATA}/bctides.in"
        echo "  bctides.in from COMOUTrerun"
    fi

    return 0
}


#-------------------------------------------------------------------------------
# COMF: Stage OBC and river forcing from tar archives
#-------------------------------------------------------------------------------
_ensemble_comf_stage_obc_river() {
    echo "Staging COMF OBC and river forcing from tar archives"

    # Ocean boundary conditions (elev2D.th.nc, TEM_3D.th.nc, SAL_3D.th.nc, uv3D.th.nc)
    if [ -f "${COMOUT}/${PREFIXNOS}.${cycle}.${PDY}.obc.tar" ]; then
        echo "Extracting OBC files"
        tar xf "${COMOUT}/${PREFIXNOS}.${cycle}.${PDY}.obc.tar" -C ${MEMBER_DATA}/
    fi

    # River forcing (vsource.th, vsink.th, msource.th or source_sink.in)
    for tar_file in \
        "${COMOUT}/${PREFIXNOS}.${cycle}.${PDY}.river.th.tar" \
        "${COMOUT}/${PREFIXNOS}.${cycle}.${PDY}.nwm.source.sink.fore.tar"; do
        if [ -f "${tar_file}" ]; then
            echo "Extracting $(basename ${tar_file})"
            tar xf "${tar_file}" -C ${MEMBER_DATA}/
        fi
    done

    return 0
}


#-------------------------------------------------------------------------------
# Copy param.nml (forecast version from COMOUT, with FIX fallback)
#
# IMPORTANT: Removes any stale symlink first -- the bare-name loop may have
# created param.nml -> secofs.param.nml -> FIX file.  cp follows symlinks
# and would silently overwrite the shared FIX file instead of creating a
# real file in the member directory.
#-------------------------------------------------------------------------------
_ensemble_copy_param_nml() {
    rm -f ${MEMBER_DATA}/param.nml

    local PARAM_NML_SRC=""
    if [ "${OFS_FRAMEWORK}" = "stofs" ]; then
        export COMOUTrerun=${COMOUTrerun:-${COMOUT}/rerun}
        # STOFS: param.nml for forecast is in COMOUTrerun
        PARAM_NML_SRC="${COMOUTrerun}/${RUN}.${cycle}.param.forecast.nml"
        [ ! -f "${PARAM_NML_SRC}" ] && \
            PARAM_NML_SRC="${COMOUT}/${PREFIXNOS}.${cycle}.${PDY}.forecast.in"
    else
        # COMF: param.nml for forecast is in COMOUT
        PARAM_NML_SRC="${COMOUT}/${PREFIXNOS}.${cycle}.${PDY}.forecast.in"
    fi

    if [ -f "${PARAM_NML_SRC}" ]; then
        echo "Using forecast param.nml from: ${PARAM_NML_SRC}"
        cp "${PARAM_NML_SRC}" ${MEMBER_DATA}/param.nml
        return 0
    fi

    # --- Fallback to FIX directory template ---
    echo "WARNING: Forecast param.nml not found in COMOUT, using FIX template"
    for candidate in \
        "${FIXofs}/${RUN}_param.nml_6globaloutput" \
        "${FIXofs}/${PREFIXNOS}.param.nml" \
        "${FIXofs}/${OFS}_param.nml_6globaloutput" \
        "${FIXofs}/${OFS}.param.nml"; do
        if [ -f "${candidate}" ]; then
            echo "Using FIX template: ${candidate}"
            cp "${candidate}" ${MEMBER_DATA}/param.nml
            return 0
        fi
    done

    echo "FATAL: No param.nml source found" >&2
    echo "  Tried: ${COMOUTrerun:-}/${RUN}.${cycle}.param.forecast.nml" >&2
    echo "  Tried: ${FIXofs}/${RUN}_param.nml_6globaloutput" >&2
    return 1
}


#-------------------------------------------------------------------------------
# Update param.nml start time and rnday for forecast period
#
# With ihot=2, SCHISM continues from the hotstart and appends output to
# existing staout files.  start_year/month/day/hour must be set to the
# forecast start (= nowcast end), and rnday is the forecast duration only.
# This matches the COMF deterministic forecast behavior in
# nos_ofs_prep_schism_ctl.sh (RUNTYPE=FORECAST, IHOT_VALUE=2).
#-------------------------------------------------------------------------------
_ensemble_update_start_time() {
    echo "Updating param.nml start time and rnday for forecast period"

    # Read time_nowcastend and time_forecastend from COMOUT
    local _time_ncend="" _time_fcend=""
    [ -f "${COMOUT}/time_nowcastend.${cycle}" ] && read _time_ncend < "${COMOUT}/time_nowcastend.${cycle}"
    [ -f "${COMOUT}/time_forecastend.${cycle}" ] && read _time_fcend < "${COMOUT}/time_forecastend.${cycle}"

    # Fallback: derive from PDY/cyc
    _time_ncend=${_time_ncend:-${PDY}$(printf '%02d' "${cyc}")}
    echo "Forecast start (time_nowcastend): ${_time_ncend}"
    echo "Forecast end   (time_forecastend): ${_time_fcend:-unknown}"

    # Parse YYYYMMDDHH -> year, month, day, hour
    local _fc_year=${_time_ncend:0:4}
    local _fc_month=$((10#${_time_ncend:4:2}))
    local _fc_day=$((10#${_time_ncend:6:2}))
    local _fc_hour=$((10#${_time_ncend:8:2}))

    # Update start_year/month/day/hour in param.nml
    sed -i "s/start_year *= *[0-9]*/start_year = ${_fc_year}/" ${MEMBER_DATA}/param.nml
    sed -i "s/start_month *= *[0-9]*/start_month = ${_fc_month}/" ${MEMBER_DATA}/param.nml
    sed -i "s/start_day *= *[0-9]*/start_day = ${_fc_day}/" ${MEMBER_DATA}/param.nml
    sed -i "s/start_hour *= *[0-9.]*/start_hour = ${_fc_hour}./" ${MEMBER_DATA}/param.nml
    echo "Set start_year=${_fc_year}, start_month=${_fc_month}, start_day=${_fc_day}, start_hour=${_fc_hour}"

    # Compute and set rnday (forecast duration in days)
    if [ -n "${_time_fcend}" ]; then
        local _fc_hours
        if [ -n "${NHOUR:-}" ] && command -v ${NHOUR} &> /dev/null; then
            _fc_hours=$(${NHOUR} ${_time_fcend} ${_time_ncend})
        elif command -v nhour &> /dev/null; then
            _fc_hours=$(nhour ${_time_fcend} ${_time_ncend})
        else
            # Fallback: use python to compute hours between two YYYYMMDDHH strings
            _fc_hours=$(python3 -c "
from datetime import datetime
t1 = datetime.strptime('${_time_ncend}', '%Y%m%d%H')
t2 = datetime.strptime('${_time_fcend}', '%Y%m%d%H')
print(int((t2 - t1).total_seconds() / 3600))
")
        fi
        local _fc_rnday=$(python3 -c "print(${_fc_hours} / 24.0)")
        sed -i "s/rnday *= *[0-9.eE+-]*/rnday = ${_fc_rnday}/" ${MEMBER_DATA}/param.nml
        echo "Set rnday=${_fc_rnday} (${_fc_hours} hours)"
    fi

    return 0
}


#-------------------------------------------------------------------------------
# Apply parameter perturbations to param.nml
#
# Uses Python to read params.json and modify the SCHISM namelist.
# Control member (000) is skipped (is_control=true in params.json).
#-------------------------------------------------------------------------------
_ensemble_apply_perturbations() {
    echo "Applying parameter perturbations"

    python3 << 'APPLY_PARAMS'
import json
import os
import re
import sys

param_file = os.environ["PARAM_FILE"]
member_data = os.environ["MEMBER_DATA"]
nml_path = os.path.join(member_data, "param.nml")

with open(param_file, "r") as f:
    member = json.load(f)

if member.get("is_control", False):
    print("Control member - no perturbations applied")
    sys.exit(0)

params = member.get("parameters", {})
if not params:
    print("No parameter perturbations to apply")
    sys.exit(0)

if not os.path.isfile(nml_path):
    print(f"WARNING: param.nml not found at {nml_path}, skipping perturbation")
    sys.exit(0)

with open(nml_path, "r") as f:
    content = f.read()

# Map parameter names to their namelist variable names
# These are direct matches to SCHISM param.nml variable names
param_nml_map = {
    "rdrg2": "rdrg2",
    "zob": "Zo",
    "akt_bak": "akt_bak",
    "akv_bak": "akv_bak",
    "akk_bak": "akk_bak",
    "akp_bak": "akp_bak",
    "scale_hflux": "scale_hflux",
}

for param_name, value in params.items():
    nml_name = param_nml_map.get(param_name, param_name)
    # Match the variable assignment in namelist format
    # Handles: varname = value  or  varname=value
    pattern = rf"(\b{re.escape(nml_name)}\s*=\s*)([^\s,!/]+)"
    new_content = re.sub(pattern, rf"\g<1>{value:.6e}", content)
    if new_content != content:
        print(f"  {nml_name} = {value:.6e}")
        content = new_content
    else:
        print(f"  WARNING: Could not find '{nml_name}' in param.nml")

with open(nml_path, "w") as f:
    f.write(content)

print("Parameter perturbations applied successfully")
APPLY_PARAMS

    return 0
}


################################################################################
#
#  ADCIRC (STOFS-2D-GLO) ENSEMBLE FUNCTIONS
#
#  ADCIRC is fundamentally different from SCHISM:
#    - Uses fort.15 (plain text) instead of param.nml (Fortran namelist)
#    - Uses OWI format forcing (fort.221/222) instead of sflux/ NetCDF
#    - Runs multiple sub-phases: tide (NWS=0) → surface (NWS=12)
#    - Uses adcprep + padcirc instead of pschism
#    - Hotstart alternates between fort.67.nc and fort.68.nc
#
#  For ensemble, we run only the surface forecast (NWS=12) sub-phase
#  to keep ensemble member runs tractable. The tidal component is
#  deterministic (same across members), so we reuse the deterministic
#  tide forecast output and only perturb the surface (wind+pressure)
#  portion where physics parameters matter.
#
################################################################################

#-------------------------------------------------------------------------------
# ADCIRC: Stage static fix files to member directory
#
# Links ADCIRC grid (fort.14), attributes (fort.13), body tide (fort.24),
# rotation matrix (fort.rotm), station lists, and pre-decomposed grid.
#-------------------------------------------------------------------------------
_ensemble_adcirc_stage_static_files() {
    echo "Staging ADCIRC static files for member ${MEMBER_ID}"

    export FIXstofs2d=${FIXstofs2d:-${FIXstofs3d:-${FIXofs}}}

    # Link ADCIRC static grid and attribute files
    ln -sf $FIXstofs2d/${RUN}_attr       ${MEMBER_DATA}/fort.13
    ln -sf $FIXstofs2d/${RUN}_grid       ${MEMBER_DATA}/fort.14
    ln -sf $FIXstofs2d/${RUN}_body       ${MEMBER_DATA}/fort.24
    ln -sf $FIXstofs2d/${RUN}_rotm       ${MEMBER_DATA}/fort.rotm
    ln -sf $FIXstofs2d/${RUN}_elev_stat  ${MEMBER_DATA}/elev_stat.151
    ln -sf $FIXstofs2d/${RUN}_elev_stat  ${MEMBER_DATA}/vel_stat.151

    # Copy tidal nodal equilibrium file (needed for fort.15 generation)
    export COMGES=${COMGES:-${COMOUTroot}/${RUN}}
    if [ -f $COMGES/${RUN}_nod_equi ]; then
        cp -p $COMGES/${RUN}_nod_equi ${MEMBER_DATA}/${RUN}_nod_equi
        echo "  Copied nod_equi from $COMGES"
    elif [ -f ${COMOUTrerun}/${RUN}_nod_equi ]; then
        cp -p ${COMOUTrerun}/${RUN}_nod_equi ${MEMBER_DATA}/${RUN}_nod_equi
        echo "  Copied nod_equi from COMOUTrerun"
    else
        echo "  WARNING: ${RUN}_nod_equi not found"
    fi

    # Copy fort.15 templates from FIX
    for tmpl in tide.15 surf.15; do
        if [ -f $FIXstofs2d/${RUN}_${tmpl} ]; then
            cp -p $FIXstofs2d/${RUN}_${tmpl} ${MEMBER_DATA}/${RUN}_${tmpl}
            echo "  Copied template: ${RUN}_${tmpl}"
        fi
    done

    # Link meteorological control file (fort.22, for surface runs)
    if [ -f $FIXstofs2d/${RUN}_met ]; then
        ln -sf $FIXstofs2d/${RUN}_met ${MEMBER_DATA}/fort.22
        echo "  Linked fort.22 (met control)"
    fi

    # Extract pre-decomposed grid from COMGES
    export ncpu=${NCPU:-${TOTAL_TASKS:-960}}
    if [ -f $COMGES/${RUN}_${ncpu}.tar.gz ]; then
        cp -p $COMGES/${RUN}_${ncpu}.tar.gz ${MEMBER_DATA}/
        cd ${MEMBER_DATA}
        tar xzf ${RUN}_${ncpu}.tar.gz
        echo "  Extracted pre-decomposed grid (${ncpu} CPUs)"
    else
        echo "  INFO: No pre-decomposed grid tar (will run adcprep --prepall)"
    fi

    return 0
}


#-------------------------------------------------------------------------------
# ADCIRC: Stage atmospheric forcing for this member
#
# ADCIRC uses OWI format forcing: fort.221.nc (pressure), fort.222.nc (wind),
# fort.225.nc (ice). These are prepared by the deterministic prep job and
# archived in COMOUTrerun. For ensemble members that use different atmospheric
# sources (e.g., GEFS), member-specific OWI files would need to be
# pre-generated by a separate prep step. Currently, all members use the
# same GFS forcing from the deterministic prep.
#-------------------------------------------------------------------------------
_ensemble_adcirc_stage_forcing() {
    echo "Staging ADCIRC forcing for member ${MEMBER_ID}"

    export COMOUTrerun=${COMOUTrerun:-${COMOUT}/rerun}

    # Stage GFS OWI forcing files for the surface forecast sub-phase
    # The deterministic prep archives these as ${RUN}_fcst1.221.nc etc.
    # For the ensemble, we run the surface forecast (fcst1 period: 0-120h).
    local _forcing_found=false
    for forcing_prefix in "fcst1" "ncst"; do
        if [ -f ${COMOUTrerun}/${RUN}_${forcing_prefix}.221.nc ]; then
            ln -sf ${COMOUTrerun}/${RUN}_${forcing_prefix}.221.nc ${MEMBER_DATA}/fort.221.nc
            ln -sf ${COMOUTrerun}/${RUN}_${forcing_prefix}.222.nc ${MEMBER_DATA}/fort.222.nc
            [ -f ${COMOUTrerun}/${RUN}_${forcing_prefix}.225.nc ] && \
                ln -sf ${COMOUTrerun}/${RUN}_${forcing_prefix}.225.nc ${MEMBER_DATA}/fort.225.nc
            echo "  OWI forcing staged from ${forcing_prefix} (fort.221/222/225)"
            _forcing_found=true
            break
        fi
    done

    if [ "${_forcing_found}" = false ]; then
        echo "  WARNING: No OWI forcing files found in COMOUTrerun"
        echo "  Checked: ${COMOUTrerun}/${RUN}_{fcst1,ncst}.221.nc"
    fi

    # Stage tide outputs from deterministic run (used as starting state
    # for ensemble surface forecast)
    for pair in "tide.61.nc:fort.61.nc" "tide.63.nc:fort.63.nc"; do
        local src_suffix="${pair%%:*}"
        local dst_name="${pair##*:}"
        local src="${COMOUTrerun}/${RUN}_${src_suffix}"
        if [ -s "${src}" ]; then
            cp -p "${src}" "${MEMBER_DATA}/${dst_name}"
            echo "  ${dst_name} <- ${src_suffix}"
        fi
    done

    # Stage surface nowcast outputs (for continuation into forecast)
    for f in surf.61.nc surf.62.nc surf.63.nc surf.64.nc \
             maxele.63.nc maxvel.63.nc maxwvel.63.nc; do
        local src="${COMOUTrerun}/${RUN}_${f}"
        if [ -s "${src}" ]; then
            # Map surf.6X.nc -> fort.6X.nc
            local dst=$(echo "$f" | sed 's/^surf\./fort./')
            # maxele/maxvel/maxwvel keep their names
            case "$f" in
                max*) dst="$f" ;;
            esac
            cp -p "${src}" "${MEMBER_DATA}/${dst}"
            echo "  ${dst} <- ${f}"
        fi
    done

    # Stage restart/hotstart from deterministic surface nowcast
    if [ -f ${COMOUTrerun}/${RUN}_surf.68.nc ]; then
        cp -p ${COMOUTrerun}/${RUN}_surf.68.nc ${MEMBER_DATA}/${YMDH:-${PDY}${cyc}}.restart
        echo "  Restart staged from surf.68.nc"
    elif [ -f ${COMOUT}/${RUN}.${cycle}.restart ]; then
        cp -p ${COMOUT}/${RUN}.${cycle}.restart ${MEMBER_DATA}/${YMDH:-${PDY}${cyc}}.restart
        echo "  Restart staged from COMOUT"
    else
        echo "  WARNING: No restart file found for ADCIRC ensemble member"
    fi

    # Stage retime.out (time tracking from deterministic nowcast)
    if [ -f ${COMOUTrerun}/${RUN}_retime.out ]; then
        cp -p ${COMOUTrerun}/${RUN}_retime.out ${MEMBER_DATA}/retime.out
        echo "  retime.out staged"
    fi

    return 0
}


#-------------------------------------------------------------------------------
# ADCIRC: Generate fort.15 for this ensemble member
#
# Copies the surface forecast fort.15 template and fills in tidal nodal
# factors, time parameters, and output settings. Uses the same approach
# as the deterministic _adcirc_generate_fort15 but adapted for ensemble.
#-------------------------------------------------------------------------------
_ensemble_adcirc_prepare_fort15() {
    echo "Preparing ADCIRC fort.15 for ensemble member ${MEMBER_ID}"

    cd ${MEMBER_DATA}

    export FIXstofs2d=${FIXstofs2d:-${FIXstofs3d:-${FIXofs}}}
    export COMOUTrerun=${COMOUTrerun:-${COMOUT}/rerun}

    # Verify nod_equi is available
    if [ ! -f ${MEMBER_DATA}/${RUN}_nod_equi ]; then
        echo "FATAL: ${RUN}_nod_equi not found in ${MEMBER_DATA}"
        return 1
    fi

    # Use the surf.15 template (NWS=12, surface forcing)
    local template="surf.15"
    if [ ! -f ${MEMBER_DATA}/${RUN}_${template} ]; then
        echo "FATAL: Template ${RUN}_${template} not found"
        return 1
    fi

    cp ${MEMBER_DATA}/${RUN}_${template} ${MEMBER_DATA}/${RUN}_fort.15

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
    } < "${MEMBER_DATA}/${RUN}_nod_equi"

    mm=$(printf "%02d" $mm)
    dd=$(printf "%02d" $dd)
    hh=$(printf "%02d" $hh)

    # Read time parameters from retime.out (from deterministic nowcast)
    local restart_count=0 time_restart=0 touts=0 toutf=0
    if [ -f ${MEMBER_DATA}/retime.out ]; then
        restart_count=$(awk '{print $1}' ${MEMBER_DATA}/retime.out)
        time_restart=$(awk '{print $2}' ${MEMBER_DATA}/retime.out)
        touts=$(awk '{print $3}' ${MEMBER_DATA}/retime.out)
        toutf=$(awk '{print $4}' ${MEMBER_DATA}/retime.out)
    else
        echo "WARNING: retime.out not found, using defaults"
    fi

    # Compute ADCIRC time parameters
    local time_now=${YMDH:-${PDY}${cyc}}
    local nowh=6
    local lsth=${ADCIRC_LSTH:-180}
    local wndh=3

    # Determine ihot from restart time
    local ihot=367
    if [ -f ${MEMBER_DATA}/${time_now}.restart ]; then
        local _restart_time
        _restart_time=$(ncdump -v time ${MEMBER_DATA}/${time_now}.restart 2>/dev/null | \
            grep 'time = [0-9]' | awk '{print $3}' || echo "0")
        if [ -n "${_restart_time}" ] && [ "${_restart_time}" != "0" ]; then
            if [ $(expr $(echo "scale=0; ${_restart_time}/($nowh*3600)" | bc) % 2) = 0 ]; then
                ihot=368
                cp -p ${MEMBER_DATA}/${time_now}.restart ${MEMBER_DATA}/fort.68.nc
            else
                ihot=367
                cp -p ${MEMBER_DATA}/${time_now}.restart ${MEMBER_DATA}/fort.67.nc
            fi
            echo "  ihot=${ihot} (restart_time=${_restart_time})"
        fi
    else
        echo "  WARNING: No restart file for ihot determination"
    fi

    # Calculate rnday for forecast surface run
    local fcstd=$(echo "scale=5; $time_restart/86400" | bc)
    local rnday=$(echo "scale=5; $fcstd+$lsth/36" | bc)
    local winc=3600
    local nout=3
    local nhstar=3
    local nhsinc=3600

    # Apply sed substitutions to generate fort.15
    sed -e "s/cycle/${time_now}/g" \
        -e "s/ihot/${ihot}/g" \
        -e "s/rnday/${rnday}/g" \
        -e "s/fft1/${fft1}/g" -e "s/facet1/${facet1}/g" \
        -e "s/fft2/${fft2}/g" -e "s/facet2/${facet2}/g" \
        -e "s/fft3/${fft3}/g" -e "s/facet3/${facet3}/g" \
        -e "s/fft4/${fft4}/g" -e "s/facet4/${facet4}/g" \
        -e "s/fft5/${fft5}/g" -e "s/facet5/${facet5}/g" \
        -e "s/fft6/${fft6}/g" -e "s/facet6/${facet6}/g" \
        -e "s/fft7/${fft7}/g" -e "s/facet7/${facet7}/g" \
        -e "s/fft8/${fft8}/g" -e "s/facet8/${facet8}/g" \
        -e "s/nout/${nout}/g" \
        -e "s/touts/${touts}/g" -e "s/toutf/${toutf}/g" \
        -e "s/nhstar/${nhstar}/g" -e "s/nhsinc/${nhsinc}/g" \
        -e "s/hh/${hh}/g" -e "s/dd/${dd}/g" \
        -e "s/mm/${mm}/g" -e "s/yyyy/${yyyy}/g" \
        -e "s/winc/${winc}/g" \
        ${MEMBER_DATA}/${RUN}_fort.15 | \
    sed -n "/DUMMY/!p" > ${MEMBER_DATA}/fort.15

    rm -f ${MEMBER_DATA}/${RUN}_fort.15

    if [ ! -f ${MEMBER_DATA}/fort.15 ]; then
        echo "FATAL: fort.15 generation failed"
        return 1
    fi

    echo "Generated fort.15 (rnday=${rnday}, ihot=${ihot}, winc=${winc})"

    return 0
}


#-------------------------------------------------------------------------------
# ADCIRC: Apply parameter perturbations to fort.15 via sed
#
# Reads perturbation values from params.json and modifies specific lines
# in fort.15. ADCIRC perturbable parameters:
#   - FFACTOR: Bottom friction factor scaling (line with FFACTOR)
#   - ESLM:    Lateral eddy viscosity / Smagorinsky coefficient
#   - TAU0:    GWCE weighting factor (negative = spatially variable)
#
# Control member (000) is skipped (is_control=true in params.json).
#-------------------------------------------------------------------------------
_ensemble_adcirc_apply_perturbations() {
    echo "Applying ADCIRC parameter perturbations to fort.15"

    python3 << 'APPLY_ADCIRC_PARAMS'
import json
import os
import re
import sys

param_file = os.environ["PARAM_FILE"]
member_data = os.environ["MEMBER_DATA"]
fort15_path = os.path.join(member_data, "fort.15")

with open(param_file, "r") as f:
    member = json.load(f)

if member.get("is_control", False):
    print("Control member - no perturbations applied to fort.15")
    sys.exit(0)

params = member.get("parameters", {})
if not params:
    print("No parameter perturbations to apply to fort.15")
    sys.exit(0)

if not os.path.isfile(fort15_path):
    print(f"WARNING: fort.15 not found at {fort15_path}, skipping perturbation")
    sys.exit(0)

with open(fort15_path, "r") as f:
    lines = f.readlines()

# ADCIRC fort.15 parameter modification strategy:
# fort.15 is a fixed-format text file where specific lines contain
# parameter values. We use sed-style line matching to find and modify
# the relevant values.
#
# FFACTOR: appears on the line that sets the friction scaling factor.
#   In fort.15, the FFACTOR line typically looks like:
#   "0.0025  CF  FFACTOR" or just the numeric value on a specific line.
#   We scale the existing CF value by FFACTOR.
#
# ESLM: lateral eddy viscosity coefficient, appears as a standalone value.
#
# TAU0: GWCE weighting, appears early in fort.15 (typically line ~15).

modified = False
new_lines = list(lines)

for param_name, value in params.items():
    param_lower = param_name.lower()

    if param_lower == "ffactor":
        # FFACTOR scales the bottom friction coefficient (CF).
        # Find lines containing "FFACTOR" or the CF parameter line.
        # In STOFS-2D-GLO fort.15, the friction line has format:
        #   <CF_value>  <other> ! ... FFACTOR ...
        # We replace the CF value (first number on the line).
        for i, line in enumerate(new_lines):
            if "FFACTOR" in line.upper() or "CF " in line.upper():
                # Extract the first floating-point number and scale it
                match = re.match(r"(\s*)([0-9.eE+-]+)(.*)", line)
                if match:
                    old_cf = float(match.group(2))
                    new_cf = old_cf * value
                    new_lines[i] = f"{match.group(1)}{new_cf:.6e}{match.group(3)}\n"
                    print(f"  FFACTOR: CF {old_cf:.6e} * {value:.4f} = {new_cf:.6e}")
                    modified = True
                break

    elif param_lower == "eslm":
        # ESLM is the lateral viscosity (Smagorinsky) coefficient.
        # In fort.15, it appears on a line by itself or with a comment.
        for i, line in enumerate(new_lines):
            if "ESLM" in line.upper():
                match = re.match(r"(\s*)([0-9.eE+-]+)(.*)", line)
                if match:
                    old_val = float(match.group(2))
                    new_lines[i] = f"{match.group(1)}{value:.6e}{match.group(3)}\n"
                    print(f"  ESLM: {old_val:.6e} -> {value:.6e}")
                    modified = True
                break

    elif param_lower == "tau0":
        # TAU0 is the GWCE weighting factor.
        # Negative values indicate spatially variable weighting.
        for i, line in enumerate(new_lines):
            if "TAU0" in line.upper():
                match = re.match(r"(\s*)([0-9.eE+-]+)(.*)", line)
                if match:
                    old_val = float(match.group(2))
                    new_lines[i] = f"{match.group(1)}{value:.6e}{match.group(3)}\n"
                    print(f"  TAU0: {old_val:.6e} -> {value:.6e}")
                    modified = True
                break

    else:
        # Generic: search for the parameter name as a comment and modify
        # the numeric value on that line.
        param_upper = param_name.upper()
        for i, line in enumerate(new_lines):
            if param_upper in line.upper():
                match = re.match(r"(\s*)([0-9.eE+-]+)(.*)", line)
                if match:
                    old_val = float(match.group(2))
                    new_lines[i] = f"{match.group(1)}{value:.6e}{match.group(3)}\n"
                    print(f"  {param_name}: {old_val:.6e} -> {value:.6e}")
                    modified = True
                break
        if not modified:
            print(f"  WARNING: Could not find '{param_name}' in fort.15")

if modified:
    with open(fort15_path, "w") as f:
        f.writelines(new_lines)
    print("ADCIRC parameter perturbations applied successfully")
else:
    print("No modifications made to fort.15")
APPLY_ADCIRC_PARAMS

    return 0
}


#-------------------------------------------------------------------------------
# ADCIRC: Execute the ensemble member
#
# For ensemble, runs only the surface forecast sub-phase (NWS=12).
# The tidal component is deterministic (identical across members) so we
# reuse the deterministic tide forecast output. Only the surface run
# (where wind forcing and friction parameters matter) is perturbed.
#
# Steps: adcprep (partition + prep15) → padcirc → check completion
#-------------------------------------------------------------------------------
_ensemble_adcirc_execute() {
    echo "=== ADCIRC ensemble execute: member ${MEMBER_ID} ==="

    cd ${MEMBER_DATA}

    # --- Verify critical input files ---
    local MISSING=0
    for required in fort.14 fort.15 fort.22; do
        if [ ! -e "${MEMBER_DATA}/${required}" ]; then
            echo "MISSING: ${required}"
            MISSING=$((MISSING + 1))
        else
            echo "OK: ${required}"
        fi
    done

    # Check OWI forcing files
    if [ ! -e "${MEMBER_DATA}/fort.221.nc" ]; then
        echo "MISSING: fort.221.nc (OWI pressure forcing)"
        MISSING=$((MISSING + 1))
    else
        echo "OK: fort.221.nc (OWI pressure)"
    fi
    if [ ! -e "${MEMBER_DATA}/fort.222.nc" ]; then
        echo "MISSING: fort.222.nc (OWI wind forcing)"
        MISSING=$((MISSING + 1))
    else
        echo "OK: fort.222.nc (OWI wind)"
    fi

    # Check for restart file (fort.67 or fort.68)
    if [ ! -e "${MEMBER_DATA}/fort.67.nc" ] && [ ! -e "${MEMBER_DATA}/fort.68.nc" ]; then
        echo "MISSING: fort.67.nc or fort.68.nc (restart/hotstart)"
        MISSING=$((MISSING + 1))
    else
        echo "OK: restart file ($(ls ${MEMBER_DATA}/fort.6[78].nc 2>/dev/null | head -1))"
    fi

    if [ $MISSING -gt 0 ]; then
        echo "FATAL: ${MISSING} required input files missing. Cannot run ADCIRC." >&2
        ls -la ${MEMBER_DATA}/ >&2
        return 1
    fi

    echo ""
    echo "Working directory listing:"
    ls -la ${MEMBER_DATA}/ | head -30
    echo ""

    # --- Determine MPI task count ---
    export ncpu=${NCPU:-${TOTAL_TASKS:-960}}
    local _ppn=${PPN:-120}
    local _tot_ncpu=${TOT_NCPU:-$((ncpu + ${NUM_WRITERS:-6}))}
    local _num_writers=${NUM_WRITERS:-6}

    echo "ncpu: ${ncpu}"
    echo "TOT_NCPU: ${_tot_ncpu}"
    echo "PPN: ${_ppn}"
    echo "NUM_WRITERS: ${_num_writers}"
    echo "Working dir: ${MEMBER_DATA}"

    # --- Run adcprep ---
    # If pre-decomposed grid is available, only run --prep15 (fort.15 update)
    # Otherwise run full partmesh + prepall
    if [ -f ${MEMBER_DATA}/${RUN}_${ncpu}.tar.gz ] || [ -d ${MEMBER_DATA}/PE0000 ]; then
        echo "Running adcprep --prep15 (pre-decomposed grid available)..."
        mpiexec -n 1 -ppn 1 adcprep --np $ncpu --prep15 \
            >> ${MEMBER_DATA}/${RUN}.member_${MEMBER_ID}.adcprep.log 2>&1
        export err=$?
        if [ $err -ne 0 ]; then
            echo "FATAL: adcprep --prep15 failed (exit code: $err)"
            return 1
        fi
    else
        echo "Running full adcprep (partmesh + prepall)..."
        mpiexec -n 1 -ppn 1 adcprep --np $ncpu --partmesh \
            >> ${MEMBER_DATA}/${RUN}.member_${MEMBER_ID}.adcprep.log 2>&1
        export err=$?
        if [ $err -ne 0 ]; then
            echo "FATAL: adcprep --partmesh failed (exit code: $err)"
            return 1
        fi
        mpiexec -n 1 -ppn 1 adcprep --np $ncpu --prepall \
            >> ${MEMBER_DATA}/${RUN}.member_${MEMBER_ID}.adcprep.log 2>&1
        export err=$?
        if [ $err -ne 0 ]; then
            echo "FATAL: adcprep --prepall failed (exit code: $err)"
            return 1
        fi
    fi

    # --- Run padcirc (surface forecast with writers) ---
    echo "ADCIRC simulation began at: $(date)"
    echo "Running padcirc (ncpu=${_tot_ncpu}, writers=${_num_writers})..."

    mpiexec -n ${_tot_ncpu} -ppn ${_ppn} --cpu-bind core \
        padcirc -W ${_num_writers} \
        > ${MEMBER_DATA}/${RUN}.${cycle}.member_${MEMBER_ID}.log 2>adcirc.err

    export err=$?
    echo "ADCIRC simulation ended at: $(date)"

    # --- Check for successful completion ---
    if [ -f adcirc.err ]; then
        if grep -q 'ADCIRC stopping' adcirc.err 2>/dev/null || \
           grep -q 'ADCIRC Terminating' adcirc.err 2>/dev/null; then
            echo "FATAL: ADCIRC crashed for member ${MEMBER_ID}" >&2
            tail -20 adcirc.err >&2
            return 1
        fi
    fi

    # Check fort.16 for completion message
    if [ -f fort.16 ]; then
        if grep -qi "Run completed" fort.16 2>/dev/null; then
            echo "ADCIRC member ${MEMBER_ID} completed successfully"
        else
            echo "WARNING: fort.16 exists but no completion message"
            tail -5 fort.16
        fi
    else
        echo "WARNING: fort.16 not found"
    fi

    if [ $err -ne 0 ]; then
        echo "FATAL: ADCIRC failed for member ${MEMBER_ID} (exit code: ${err})" >&2
        return $err
    fi

    return 0
}


#-------------------------------------------------------------------------------
# ADCIRC: Collect member output to ENSEMBLE_COMOUT
#
# Copies ADCIRC NetCDF outputs (station elevation, field elevation,
# velocity, max fields) to the member's ensemble output directory.
#-------------------------------------------------------------------------------
_ensemble_adcirc_collect_output() {
    echo "Collecting ADCIRC output for member ${MEMBER_ID}"

    mkdir -p ${ENSEMBLE_COMOUT}

    # Station output (elevation timeseries at observation points)
    if [ -f ${MEMBER_DATA}/fort.61.nc ]; then
        cp -p ${MEMBER_DATA}/fort.61.nc ${ENSEMBLE_COMOUT}/fort.61.nc
        echo "  Archived fort.61.nc (station elevation)"
    fi

    # Station velocity
    if [ -f ${MEMBER_DATA}/fort.62.nc ]; then
        cp -p ${MEMBER_DATA}/fort.62.nc ${ENSEMBLE_COMOUT}/fort.62.nc
        echo "  Archived fort.62.nc (station velocity)"
    fi

    # Field output (2D elevation on entire grid)
    if [ -f ${MEMBER_DATA}/fort.63.nc ]; then
        cp -p ${MEMBER_DATA}/fort.63.nc ${ENSEMBLE_COMOUT}/fort.63.nc
        echo "  Archived fort.63.nc (field elevation)"
    fi

    # Field velocity
    if [ -f ${MEMBER_DATA}/fort.64.nc ]; then
        cp -p ${MEMBER_DATA}/fort.64.nc ${ENSEMBLE_COMOUT}/fort.64.nc
        echo "  Archived fort.64.nc (field velocity)"
    fi

    # Maximum fields (useful for ensemble max envelope)
    for f in maxele.63.nc maxvel.63.nc maxwvel.63.nc; do
        if [ -f ${MEMBER_DATA}/${f} ]; then
            cp -p ${MEMBER_DATA}/${f} ${ENSEMBLE_COMOUT}/${f}
            echo "  Archived ${f}"
        fi
    done

    # Archive the fort.15 used (for provenance/debugging)
    if [ -f ${MEMBER_DATA}/fort.15 ]; then
        cp -p ${MEMBER_DATA}/fort.15 ${ENSEMBLE_COMOUT}/fort.15
        echo "  Archived fort.15 (for provenance)"
    fi

    local N_ARCHIVED=$(ls ${ENSEMBLE_COMOUT}/*.nc 2>/dev/null | wc -l)
    echo "Archived ${N_ARCHIVED} NetCDF files to ${ENSEMBLE_COMOUT}/"

    return 0
}
