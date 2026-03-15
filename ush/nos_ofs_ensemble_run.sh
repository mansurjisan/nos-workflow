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
# Copies the forecast param.nml, sets ihot (1 for UFS, 2 for standalone),
# enforces nws/nscribes for UFS, updates start time and rnday, then applies
# LHS perturbations.
################################################################################
ensemble_configure_runtime() {
    echo "=== ensemble_configure_runtime: member ${MEMBER_ID} ==="

    cd ${MEMBER_DATA}

    # 3a: Copy param.nml (forecast version from COMOUT or FIX fallback)
    _ensemble_copy_param_nml
    local rc=$?
    if [ $rc -ne 0 ]; then return $rc; fi

    # 3b: Set ihot for hot restart
    # Standalone SCHISM: ihot=2 (continue from hotstart time, appends staout)
    # UFS-Coastal: ihot=1 (NUOPC start_type=startup resets ESMF clock to t=0;
    #   ihot=2 causes SCHISM/ESMF clock desync → ghost node pressure transient)
    if [ "${USE_DATM:-false}" == "true" ] || [ "${USE_DATM:-0}" == "1" ]; then
        sed -i 's/ihot *= *[0-9]*/ihot = 1/' ${MEMBER_DATA}/param.nml
        echo "Set ihot=1 for UFS-Coastal (NUOPC clock sync requires reset)"
    else
        sed -i 's/ihot *= *[0-9]*/ihot = 2/' ${MEMBER_DATA}/param.nml
        echo "Set ihot=2 for hot restart with continued output (nowcast+forecast staout)"
    fi

    # 3b2: Force UFS-Coastal param.nml overrides
    # If param.nml came from standalone SCHISM (nws=2, nscribes>0), fix for NUOPC.
    if [ "${USE_DATM:-false}" == "true" ] || [ "${USE_DATM:-0}" == "1" ]; then
        sed -i 's/nws *= *[0-9]*/nws = 4/' ${MEMBER_DATA}/param.nml
        sed -i 's/nscribes *= *[0-9]*/nscribes = 0/' ${MEMBER_DATA}/param.nml
        echo "Forced nws=4 (NUOPC coupling) and nscribes=0 (CMEPS I/O) for UFS-Coastal"
    fi

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

    # UFS-Coastal: dispatch to coupled DATM+SCHISM execution
    if [ "${USE_DATM:-false}" == "true" ] || [ "${USE_DATM:-0}" == "1" ]; then
        _ensemble_execute_ufs_coastal
        return $?
    fi

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
            # STOFS naming: ${RUN}_pschism (e.g., stofs_3d_atl_pschism)
            # stofs_2d_atl falls back to stofs_3d_atl executable (same SCHISM binary)
            SCHISM_EXEC=${EXECstofs3d}/${RUN}_pschism
            [ ! -x "${SCHISM_EXEC}" ] && SCHISM_EXEC=${EXECstofs3d}/stofs_3d_atl_pschism
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
# UFS-Coastal Ensemble Execution (DATM + SCHISM coupled via NUOPC/CMEPS)
#
# Stages UFS config files and DATM INPUT to member working directory,
# then runs the coupled ufs_coastal binary instead of standalone SCHISM.
################################################################################
_ensemble_execute_ufs_coastal() {
    echo "=== _ensemble_execute_ufs_coastal: member ${MEMBER_ID} ==="

    cd ${MEMBER_DATA}

    # --- Verify critical input files ---
    local MISSING=0
    for required in param.nml hotstart.nc bctides.in; do
        if [ ! -e "${MEMBER_DATA}/${required}" ]; then
            echo "MISSING: ${required}"
            MISSING=$((MISSING + 1))
        else
            echo "OK: ${required}"
        fi
    done

    # Check grid files
    for grid_file in hgrid.gr3 vgrid.in; do
        if [ -e "${MEMBER_DATA}/${grid_file}" ]; then
            echo "OK: ${grid_file}"
        else
            echo "MISSING: ${grid_file}"
            MISSING=$((MISSING + 1))
        fi
    done

    if [ $MISSING -gt 0 ]; then
        echo "FATAL: ${MISSING} required input files missing." >&2
        return 1
    fi

    # --- Stage UFS config files from COMOUT ---
    echo "Staging UFS config files to member directory..."
    for f in model_configure datm_in datm.streams ufs.configure; do
        local src="${COMOUT}/${RUN}.${cycle}.${f}"
        if [ -s "$src" ]; then
            cp -p "$src" "${MEMBER_DATA}/${f}"
            echo "  Staged: ${f}"
        else
            echo "FATAL: UFS config not found: $src" >&2
            return 1
        fi
    done

    # Stage DATM INPUT directory
    # Determine member-specific DATM input based on met_source_1 from params.json
    mkdir -p ${MEMBER_DATA}/INPUT
    local datm_dir=""
    local met_source=""

    if [ -f "${PARAM_FILE:-}" ]; then
        met_source=$(python3 -c "
import json, sys
with open('${PARAM_FILE}') as f:
    p = json.load(f)
# met_source_1 is nested under atmospheric_source in params.json
atm = p.get('atmospheric_source', {})
ms = atm.get('met_source_1', '') or p.get('met_source_1', '')
print(ms)
" 2>/dev/null || echo "")
    fi

    local is_control_det=false
    case "${met_source}" in
        GEFS_*)
            local gefs_id=$(echo "${met_source}" | sed 's/GEFS_//')
            datm_dir="${COMOUT}/${RUN}.${cycle}.datm_input_gefs_${gefs_id}"
            ;;
        RRFS)
            datm_dir="${COMOUT}/${RUN}.${cycle}.datm_input_rrfs"
            ;;
        *)
            # Control member (GFS+HRRR) uses the standard prep output
            datm_dir="${COMOUT}/${RUN}.${cycle}.datm_input"
            is_control_det=true
            ;;
    esac

    echo "Met source: ${met_source:-GFS (control)}"
    echo "DATM input dir: ${datm_dir}"

    if [ ! -d "$datm_dir" ]; then
        echo "FATAL: DATM input directory not found: $datm_dir" >&2
        return 1
    fi

    # Stage DATM files — check explicitly for datm_forcing.nc
    if [ -s "${datm_dir}/datm_forcing.nc" ]; then
        cp -p ${datm_dir}/datm_forcing.nc ${MEMBER_DATA}/INPUT/
        echo "Staged datm_forcing.nc from ${datm_dir}"
    else
        echo "FATAL: datm_forcing.nc not found in ${datm_dir}" >&2
        ls -la ${datm_dir}/ >&2 2>/dev/null
        return 1
    fi

    # Stage ESMF mesh — use member-specific if available, else control
    if [ -s "${datm_dir}/datm_esmf_mesh.nc" ]; then
        cp -p ${datm_dir}/datm_esmf_mesh.nc ${MEMBER_DATA}/INPUT/
        echo "Staged datm_esmf_mesh.nc from ${datm_dir}"
    elif [ -s "${COMOUT}/${RUN}.${cycle}.datm_input/datm_esmf_mesh.nc" ]; then
        cp -p ${COMOUT}/${RUN}.${cycle}.datm_input/datm_esmf_mesh.nc ${MEMBER_DATA}/INPUT/
        echo "Staged datm_esmf_mesh.nc from control datm_input (member dir had none)"
    fi

    # Patch datm_in nx_global/ny_global if member forcing has different grid dims
    if [ -s "${MEMBER_DATA}/INPUT/datm_forcing.nc" ] && [ -s "${MEMBER_DATA}/datm_in" ]; then
        local mem_dims=$(python3 -c "
from netCDF4 import Dataset
ds = Dataset('${MEMBER_DATA}/INPUT/datm_forcing.nc', 'r')
# Try 'x'/'y' dims first (blended output), then 'longitude'/'latitude' (raw GFS/GEFS)
try:
    print(len(ds.dimensions['x']), len(ds.dimensions['y']))
except:
    print(len(ds.dimensions['longitude']), len(ds.dimensions['latitude']))
ds.close()
" 2>/dev/null || echo "")
        if [ -n "$mem_dims" ]; then
            local mem_nx=$(echo $mem_dims | awk '{print $1}')
            local mem_ny=$(echo $mem_dims | awk '{print $2}')
            sed -i "s/nx_global[[:space:]]*=.*/nx_global = ${mem_nx}/" ${MEMBER_DATA}/datm_in
            sed -i "s/ny_global[[:space:]]*=.*/ny_global = ${mem_ny}/" ${MEMBER_DATA}/datm_in
            echo "Patched datm_in: nx_global=${mem_nx}, ny_global=${mem_ny}"

            # Always regenerate ESMF mesh from the forcing file.
            # This matches what _comf_execute_ufs_coastal() does for the DET
            # model run (nos_ofs_model_run.sh:1049-1111). The prep may create
            # a different mesh (different generation method or coordinate
            # convention), so we must regenerate to ensure identical
            # interpolation weights between DET and ensemble members.
            local mem_total=$((mem_nx * mem_ny))
            echo "Regenerating ESMF mesh from forcing (${mem_nx}x${mem_ny} = ${mem_total} nodes)..."
            python3 -c "
from netCDF4 import Dataset
import numpy as np

ds = Dataset('${MEMBER_DATA}/INPUT/datm_forcing.nc', 'r')
try:
    lons = ds.variables['longitude'][:]
    lats = ds.variables['latitude'][:]
    if lons.ndim == 1:
        lon2d, lat2d = np.meshgrid(lons, lats)
    else:
        lon2d, lat2d = lons, lats
except:
    lon2d = ds.variables['x'][:]
    lat2d = ds.variables['y'][:]
ds.close()

ny, nx = lon2d.shape
n_nodes = ny * nx
n_elems = (ny - 1) * (nx - 1)

out = Dataset('${MEMBER_DATA}/INPUT/datm_esmf_mesh.nc', 'w')
out.createDimension('nodeCount', n_nodes)
out.createDimension('elementCount', n_elems)
out.createDimension('maxNodePElement', 4)
out.createDimension('coordDim', 2)

nodeCoords = out.createVariable('nodeCoords', 'f8', ('nodeCount', 'coordDim'))
nodeCoords.units = 'degrees'
coords = np.column_stack([lon2d.ravel(), lat2d.ravel()])
nodeCoords[:] = coords

j_idx, i_idx = np.mgrid[0:ny-1, 0:nx-1]
n0 = (j_idx * nx + i_idx + 1).ravel()
conn = np.column_stack([n0, n0 + 1, n0 + nx + 1, n0 + nx]).astype(np.int32)

elemConn = out.createVariable('elementConn', 'i4', ('elementCount', 'maxNodePElement'))
elemConn.long_name = 'Node indices that define the element connectivity'
elemConn.start_index = 1
elemConn[:] = conn

numElemConn = out.createVariable('numElementConn', 'i4', ('elementCount',))
numElemConn[:] = 4

elementMask = out.createVariable('elementMask', 'i4', ('elementCount',))
elementMask[:] = np.ones(n_elems, dtype=np.int32)

centerCoords = out.createVariable('centerCoords', 'f8', ('elementCount', 'coordDim'))
centerCoords.units = 'degrees'
clon = 0.25 * (coords[conn[:,0]-1,0] + coords[conn[:,1]-1,0] + coords[conn[:,2]-1,0] + coords[conn[:,3]-1,0])
clat = 0.25 * (coords[conn[:,0]-1,1] + coords[conn[:,1]-1,1] + coords[conn[:,2]-1,1] + coords[conn[:,3]-1,1])
centerCoords[:] = np.column_stack([clon, clat])

out.title = 'ESMF mesh generated from DATM forcing file'
out.gridType = 'unstructured mesh'
out.close()
print('Generated ESMF mesh: {}x{} = {} nodes, {} elements'.format(nx, ny, n_nodes, n_elems))
" 2>&1
            if [ $? -ne 0 ]; then
                echo "WARNING: ESMF mesh generation failed — model may crash" >&2
            fi
        fi
    fi

    # Patch datm.streams AND datm_in to point to member-specific forcing files.
    # The datm.streams and datm_in copied from COMOUT contain the DET prep's
    # absolute path (e.g., $COMOUT/secofs_ufs.t12z.datm_input/datm_forcing.nc).
    # Each ensemble member has its own datm_forcing.nc in $MEMBER_DATA/INPUT/
    # (from the GEFS-specific prep), so we must redirect both files.
    if [ -s "${MEMBER_DATA}/INPUT/datm_forcing.nc" ]; then
        echo "Patching datm.streams and datm_in to use member-specific INPUT/..."

        # Patch datm.streams: stream_data_files01 and stream_mesh_file01
        if [ -s "${MEMBER_DATA}/datm.streams" ]; then
            sed -i "s|\"[^\"]*datm_forcing.nc\"|\"${MEMBER_DATA}/INPUT/datm_forcing.nc\"|g" ${MEMBER_DATA}/datm.streams
            sed -i "s|\"[^\"]*datm_esmf_mesh.nc\"|\"${MEMBER_DATA}/INPUT/datm_esmf_mesh.nc\"|g" ${MEMBER_DATA}/datm.streams
            echo "  datm.streams: data  -> ${MEMBER_DATA}/INPUT/datm_forcing.nc"
            echo "  datm.streams: mesh  -> ${MEMBER_DATA}/INPUT/datm_esmf_mesh.nc"
        fi

        # Patch datm_in: model_meshfile and model_maskfile
        # These also use the DET's @[DATM_INPUT_DIR] path and must point to
        # the member's ESMF mesh (which matches the GEFS grid, not DET grid).
        if [ -s "${MEMBER_DATA}/datm_in" ] && [ -s "${MEMBER_DATA}/INPUT/datm_esmf_mesh.nc" ]; then
            sed -i "s|model_meshfile[[:space:]]*=.*|model_meshfile = \"${MEMBER_DATA}/INPUT/datm_esmf_mesh.nc\"|" ${MEMBER_DATA}/datm_in
            sed -i "s|model_maskfile[[:space:]]*=.*|model_maskfile = \"${MEMBER_DATA}/INPUT/datm_esmf_mesh.nc\"|" ${MEMBER_DATA}/datm_in
            echo "  datm_in: meshfile -> ${MEMBER_DATA}/INPUT/datm_esmf_mesh.nc"
        fi
    fi

    # Ensure forcing NetCDF has all 8 variables expected by datm.streams.
    # GEFS pgrb2sp25 lacks SPFH_2maboveground, PRATE_surface, and uses
    # PRMSL_meansealevel instead of MSLMA_meansealevel.  Rather than
    # stripping variables from datm.streams (which breaks SCHISM's
    # atmospheric coupling), add missing variables as zeros and rename
    # PRMSL→MSLMA so the config matches the working deterministic exactly.
    if [ -s "${MEMBER_DATA}/INPUT/datm_forcing.nc" ]; then
        echo "Checking forcing NetCDF for required variables..."
        python3 -c "
from netCDF4 import Dataset
import numpy as np

ds = Dataset('${MEMBER_DATA}/INPUT/datm_forcing.nc', 'a')
vnames = list(ds.variables.keys())
time_dim = 'time'
lat_dims = [d for d in ds.dimensions if d in ('latitude','lat','y')]
lon_dims = [d for d in ds.dimensions if d in ('longitude','lon','x')]
if not lat_dims or not lon_dims:
    print('Forcing dims not recognized: {} — skipping variable check'.format(list(ds.dimensions.keys())))
    ds.close()
    import sys; sys.exit(0)
lat_dim = lat_dims[0]
lon_dim = lon_dims[0]
shape_3d = (len(ds.dimensions[time_dim]), len(ds.dimensions[lat_dim]), len(ds.dimensions[lon_dim]))
changed = False

# Rename PRMSL → MSLMA if needed
if 'PRMSL_meansealevel' in vnames and 'MSLMA_meansealevel' not in vnames:
    ds.renameVariable('PRMSL_meansealevel', 'MSLMA_meansealevel')
    print('Renamed PRMSL_meansealevel → MSLMA_meansealevel')
    changed = True

# Add missing SPFH as zeros
if 'SPFH_2maboveground' not in vnames:
    v = ds.createVariable('SPFH_2maboveground', 'f4', (time_dim, lat_dim, lon_dim))
    v.long_name = '2m specific humidity'
    v.units = 'kg/kg'
    v[:] = np.zeros(shape_3d, dtype=np.float32)
    print('Added SPFH_2maboveground (zeros) — GEFS pgrb2sp25 lacks this field')
    changed = True

# Add missing PRATE as zeros
if 'PRATE_surface' not in vnames:
    v = ds.createVariable('PRATE_surface', 'f4', (time_dim, lat_dim, lon_dim))
    v.long_name = 'surface precipitation rate'
    v.units = 'kg/m2/s'
    v[:] = np.zeros(shape_3d, dtype=np.float32)
    print('Added PRATE_surface (zeros) — GEFS pgrb2sp25 lacks this field')
    changed = True

ds.close()
if not changed:
    print('All 8 required variables present — no changes needed')
" 2>&1
    fi

    # Patch model_configure for ensemble forecast: start time + duration
    local nhours=${LEN_FORECAST:-48}

    # Derive forecast start time from time_nowcastend (= nowcast end = forecast begin)
    local _time_ncend=""
    [ -f "${COMOUT}/time_nowcastend.${cycle}" ] && read _time_ncend < "${COMOUT}/time_nowcastend.${cycle}"
    _time_ncend=${_time_ncend:-${PDY}$(printf '%02d' "${cyc}")}

    local sim_yyyy=${_time_ncend:0:4}
    local sim_mm=${_time_ncend:4:2}
    local sim_dd=${_time_ncend:6:2}
    local sim_hh=${_time_ncend:8:2}

    if [ -s "${MEMBER_DATA}/model_configure" ]; then
        sed -i "s/nhours_fcst:.*/nhours_fcst:             ${nhours}/" ${MEMBER_DATA}/model_configure
        sed -i "s/start_year:.*/start_year:              ${sim_yyyy}/" ${MEMBER_DATA}/model_configure
        sed -i "s/start_month:.*/start_month:             ${sim_mm}/" ${MEMBER_DATA}/model_configure
        sed -i "s/start_day:.*/start_day:               ${sim_dd}/" ${MEMBER_DATA}/model_configure
        sed -i "s/start_hour:.*/start_hour:              ${sim_hh}/" ${MEMBER_DATA}/model_configure
        echo "Patched model_configure: start=${sim_yyyy}-${sim_mm}-${sim_dd}T${sim_hh}Z, nhours_fcst=${nhours}"
    fi
    if [ -s "${MEMBER_DATA}/ufs.configure" ]; then
        sed -i "s/stop_n = .*/stop_n = ${nhours}/" ${MEMBER_DATA}/ufs.configure
    fi

    # --- Stage fd_ufs.yaml and noahmptable.tbl ---
    for f in fd_ufs.yaml noahmptable.tbl; do
        if [ -s "${FIXofs}/${f}" ] && [ ! -s "${MEMBER_DATA}/${f}" ]; then
            cp -p "${FIXofs}/${f}" "${MEMBER_DATA}/${f}"
        fi
    done

    # --- Determine executable ---
    local UFS_EXEC=""
    local UFS_EXEC_NAME=${UFS_EXEC_NAME:-fv3_coastalS.exe}
    if [ -x "${MEMBER_DATA}/${UFS_EXEC_NAME}" ]; then
        UFS_EXEC="${MEMBER_DATA}/${UFS_EXEC_NAME}"
    elif [ -x "${EXECnos:-}/${UFS_EXEC_NAME}" ]; then
        UFS_EXEC="${EXECnos}/${UFS_EXEC_NAME}"
    elif [ -x "${EXECnos:-}/ufs_coastal" ]; then
        UFS_EXEC="${EXECnos}/ufs_coastal"
    else
        echo "FATAL: UFS-Coastal executable not found" >&2
        return 1
    fi

    # --- Determine MPI task count ---
    local NTASKS=${TOTAL_TASKS:-1200}
    local PPN=${PPN:-120}

    echo "Executable: ${UFS_EXEC}"
    echo "TOTAL_TASKS: ${NTASKS}"
    echo "PPN: ${PPN}"
    echo "Working dir: ${MEMBER_DATA}"
    echo "Member ID: ${MEMBER_ID}"

    # --- Set UFS-Coastal runtime environment ---
    export OMP_STACKSIZE=${OMP_STACKSIZE:-512M}
    # Force OMP_NUM_THREADS=1 — Cray PBS sets it to ncpus (128) which
    # causes massive oversubscription with 120 MPI ranks per node
    export OMP_NUM_THREADS=1
    export OMP_PLACES=cores
    export ESMF_RUNTIME_COMPLIANCECHECK=OFF:depth=4
    export ESMF_RUNTIME_PROFILE=ON
    export ESMF_RUNTIME_PROFILE_OUTPUT="SUMMARY"

    # --- Run UFS-Coastal ---
    echo "UFS-Coastal ensemble simulation began at: $(date)"
    mpiexec -n ${NTASKS} -ppn ${PPN} -depth 1 ${UFS_EXEC} \
        > ${MEMBER_DATA}/${RUN}.${cycle}.member_${MEMBER_ID}.log 2>&1
    export err=$?
    echo "UFS-Coastal ensemble simulation ended at: $(date)"

    # Check for successful completion
    if [ -s "${MEMBER_DATA}/outputs/mirror.out" ]; then
        if grep -q "Run completed successfully" ${MEMBER_DATA}/outputs/mirror.out 2>/dev/null; then
            echo "UFS-Coastal member ${MEMBER_ID} completed successfully"
        else
            echo "WARNING: mirror.out exists but no success message"
            tail -5 ${MEMBER_DATA}/outputs/mirror.out
        fi
    else
        echo "WARNING: mirror.out not found or empty"
    fi

    if [ $err -ne 0 ]; then
        echo "FATAL: UFS-Coastal failed for member ${MEMBER_ID} (exit code: ${err})" >&2
        return $err
    fi

    return 0
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
        # tem_nudge.gr3 -> TEM_nudge.gr3 (SCHISM expects uppercase) — skip for barotropic
        if [ "${BAROTROPIC:-false}" != "true" ]; then
            [ -e "${MEMBER_DATA}/tem_nudge.gr3" ] && [ ! -e "${MEMBER_DATA}/TEM_nudge.gr3" ] && \
                ln -sf "${MEMBER_DATA}/tem_nudge.gr3" ${MEMBER_DATA}/TEM_nudge.gr3
            # sal_nudge.gr3 -> SAL_nudge.gr3 (SCHISM expects uppercase)
            [ -e "${MEMBER_DATA}/sal_nudge.gr3" ] && [ ! -e "${MEMBER_DATA}/SAL_nudge.gr3" ] && \
                ln -sf "${MEMBER_DATA}/sal_nudge.gr3" ${MEMBER_DATA}/SAL_nudge.gr3
            echo "Created STOFS special name mappings (source_sink.in, msource.th, TEM/SAL_nudge)"
        else
            echo "Created STOFS special name mappings (source_sink.in, msource.th — barotropic, no nudge)"
        fi
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

    # RTOFS OBC time-history files
    # Barotropic mode: only stage elev2D (SSH), skip T/S/velocity 3D OBC
    if [ "${BAROTROPIC:-false}" = "true" ]; then
        local _obc_pairs="elev2dth.nc:elev2D.th.nc"
    else
        local _obc_pairs="elev2dth.nc:elev2D.th.nc tem3dth.nc:TEM_3D.th.nc sal3dth.nc:SAL_3D.th.nc uv3dth.nc:uv3D.th.nc"
    fi
    for pair in ${_obc_pairs}; do
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
    # Skip for barotropic mode (no T/S nudging)
    if [ "${BAROTROPIC:-false}" != "true" ]; then
        for pair in "temnu.nc:TEM_nu.nc" "salnu.nc:SAL_nu.nc"; do
            local src_suffix="${pair%%:*}"
            local dst_name="${pair##*:}"
            local src="${COMOUTrerun}/${RUN}.${cycle}.${src_suffix}"
            if [ -s "${src}" ]; then
                cp -p "${src}" "${MEMBER_DATA}/${dst_name}"
                echo "  ${dst_name} <- ${src_suffix}"
            fi
        done
    fi

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
