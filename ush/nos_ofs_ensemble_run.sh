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
#     OFS_FRAMEWORK   - "stofs" or "comf"
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
    mkdir -p ${MEMBER_DATA}/sflux ${MEMBER_DATA}/outputs

    # 2a: Link fix files and create bare-name symlinks
    _ensemble_stage_static_files

    # 2b: Stage atmospheric, OBC, and river forcing
    _ensemble_stage_forcing

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

    # 3a: Copy param.nml (forecast version from COMOUT or FIX fallback)
    _ensemble_copy_param_nml
    local rc=$?
    if [ $rc -ne 0 ]; then return $rc; fi

    # 3b: Set ihot=1 for hot restart with fresh output
    # ihot=1: reads hotstart.nc but starts output from scratch (no staout dependency)
    # ihot=2: reads hotstart.nc AND continues output (requires real staout/mirror/flux)
    # For ensemble members, ihot=1 is correct -- each member produces independent output.
    sed -i 's/ihot *= *[0-9]*/ihot = 1/' ${MEMBER_DATA}/param.nml
    echo "Set ihot=1 for hot restart with fresh output"

    # 3c: Update start time and rnday for forecast period
    _ensemble_update_start_time

    # 3d: Apply parameter perturbations from params.json
    _ensemble_apply_perturbations

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

    # Restore staout/mirror/flux files if available (SCHISM ihot=2 requirement).
    # SCHISM reads these on restart -- empty files cause EOF errors in some
    # versions but are better than missing files.  If the nowcast archived
    # real files, use them.
    mkdir -p ${MEMBER_DATA}/outputs
    local RESTART_OUTPUTS_DIR="${COMOUT}/${RUN}.${cycle}.restart_outputs"
    if [ -d "${RESTART_OUTPUTS_DIR}" ]; then
        echo "Restoring restart output files from ${RESTART_OUTPUTS_DIR}"
        for f in mirror.out flux.out staout_1 staout_2 staout_3 staout_4 \
                 staout_5 staout_6 staout_7 staout_8 staout_9; do
            [ -f "${RESTART_OUTPUTS_DIR}/$f" ] && cp -p "${RESTART_OUTPUTS_DIR}/$f" ${MEMBER_DATA}/outputs/
        done
    else
        echo "WARNING: restart_outputs dir not found: ${RESTART_OUTPUTS_DIR}"
        echo "Creating empty placeholder files for SCHISM restart"
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

    # --- Verify critical input files ---
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
            local _COMOUTrerun=${COMOUTrerun:-${COMOUT}/rerun}
            echo "RRFS primary: staging sflux from ${_COMOUTrerun}"
            for var in air prc rad; do
                local src="${_COMOUTrerun}/${RUN}.${cycle}.rrfs.${var}.nc"
                local dst="${MEMBER_DATA}/sflux/sflux_${var}_1.0001.nc"
                if [ -s "${src}" ]; then
                    cp -p "${src}" "${dst}"
                    echo "  sflux_${var}_1 <- rrfs"
                else
                    echo "ERROR: RRFS sflux not found: ${src}" >&2
                    echo "  Falling back to default GFS tar"
                    local FALLBACK_TAR="${COMOUT}/${PREFIXNOS}.${cycle}.${PDY}.met.forecast.nc.tar"
                    [ -f "${FALLBACK_TAR}" ] && tar xf "${FALLBACK_TAR}" -C ${MEMBER_DATA}/sflux/
                    break
                fi
            done
        else
            # GFS/GEFS/other: use tar archives from COMOUT
            local MET1_TAR
            case "${ATMOS_MET1}" in
                GFS)
                    MET1_TAR="${COMOUT}/${PREFIXNOS}.${cycle}.${PDY}.met.forecast.nc.tar"
                    ;;
                GEFS_*)
                    local _GEFS_ID=$(echo "${ATMOS_MET1}" | sed 's/GEFS_//')
                    local _GEFS_TAG
                    if [ "${_GEFS_ID}" = "c00" ] || [ "${_GEFS_ID}" = "00" ]; then
                        _GEFS_TAG="gec00"
                    else
                        _GEFS_TAG="gep$(printf '%02d' "${_GEFS_ID}" 2>/dev/null || echo "${_GEFS_ID}")"
                    fi
                    MET1_TAR="${COMOUT}/${PREFIXNOS}.${cycle}.${PDY}.met.forecast.GEFS_${_GEFS_TAG}.nc.tar"
                    [ ! -f "${MET1_TAR}" ] && \
                        MET1_TAR="${COMOUT}/${PREFIXNOS}.${cycle}.${PDY}.met.forecast.GEFS_${_GEFS_TAG}.tar"
                    echo "GEFS primary: member=${_GEFS_ID} tag=${_GEFS_TAG}"
                    ;;
                *)
                    MET1_TAR="${COMOUT}/${PREFIXNOS}.${cycle}.${PDY}.met.forecast.${ATMOS_MET1}.tar"
                    ;;
            esac

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
# CRITICAL: With ihot=1, SCHISM starts its clock at start_year/month/day/hour
# from param.nml, NOT from the hotstart file time.  The forecast param.nml
# has start times from the simulation start (BASE_DATE), which can predate
# the forecast sflux data.  We must update start times to the forecast start
# (= nowcast end) so SCHISM's time_now falls within the sflux data window.
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
