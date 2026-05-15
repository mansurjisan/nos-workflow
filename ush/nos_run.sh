#!/bin/bash
###############################################################################
#  nos_run.sh - SCHISM-UFS-Coastal run library.
#
#  This file is sourced by ex-scripts to expose `_schism_run_mpi` and
#  `_schism_run_combine_hotstart` to the Python orchestrator via
#  bash_compat.run_shell_function. The Python runner
#  (nos_workflow.runners.schism_ufs) drives the full nowcast/forecast
#  pipeline; these two helpers remain in shell because they depend on
#  `module load` (cray-pals, intel-*, hpc-stack netcdf/hdf5) which does
#  not survive a Python subprocess.
#
#  Scope: any OFS coupling SCHISM via UFS-Coastal NUOPC (currently
#  secofs_ufs and stofs_3d_atl_ufs; both register framework=comf or
#  framework=stofs_ufs and route through the same Python runner).
#
#  Required env (set by the J-job and YAML loader):
#    OFS, RUN, PREFIXNOS, PDY, cyc, cycle, DATA, COMOUT, COMOUTroot,
#    HOMEnos, USHnos, EXECnos, FIXofs, FIXnos,
#    OCEAN_MODEL=SCHISM, USE_DATM=true,
#    GRIDFILE, GRIDFILE_LL, VGRID_CTL, VGRID_NU_CTL, VGRID_FAKE_CTL,
#    STA_OUT_CTL, RUNTIME_CTL, RUNTIME_CTL_FOR (optional),
#    HC_FILE_OBC, NWM_REACHID_FILE, CREATE_TIDEFORCING,
#    LEN_FORECAST, LEN_NOWCAST, time_nowcastend (or PDY/cyc),
#    TOTAL_TASKS, PPN, NDATE, NHOUR
###############################################################################

# _schism_run_mpi <phase> - mpiexec wrapper for UFS-Coastal. Stays in shell
#   because `module load` (cray-pals, intel-*, hpc-stack) does not survive a
#   Python subprocess; callers from Python invoke this helper directly via
#   bash_compat.run_shell_function.
#   Required env: UFS_EXEC, NTASKS, PPN, DATA.
_schism_run_mpi() {
    local phase=${1:-nowcast}
    cd ${DATA}

    # Resolve NTASKS / PPN / UFS_EXEC defensively in case the function is
    # called from a context where the caller's locals aren't in scope.
    local NTASKS=${NTASKS:-${TOTAL_TASKS:-1200}}
    local PPN=${PPN:-120}
    local UFS_EXEC=${UFS_EXEC:-}
    if [ -z "${UFS_EXEC}" ] || [ ! -x "${UFS_EXEC}" ]; then
        local _cand
        for _cand in \
            "${DATA}/fv3_coastalS.exe" \
            "${EXECnos:-}/fv3_coastalS.exe" \
            "${HOMEnos:-}/exec/fv3_coastalS.exe" \
            "${EXECnos:-}/ufs_coastal" \
            "${HOMEnos:-}/exec/ufs_coastal"; do
            if [ -x "$_cand" ]; then UFS_EXEC="$_cand"; break; fi
        done
    fi

    echo "_schism_run_mpi: launching mpiexec for phase=${phase}"
    echo "  mpiexec -n ${NTASKS} -ppn ${PPN} --cpu-bind core ${UFS_EXEC}"
    mpiexec -n ${NTASKS} -ppn ${PPN} --cpu-bind core ${UFS_EXEC}
    local rc=$?
    echo "_schism_run_mpi: mpiexec returned rc=${rc}"
    return ${rc}
}

# _schism_run_combine_hotstart <step> <phase> - combine_hotstart7 wrapper.
#   Stays in shell because combine_hotstart7 links against hpc-stack
#   netcdf/4.7.4 + hdf5 loaded by `module load`, which does not survive a
#   Python subprocess. We extend LD_LIBRARY_PATH here so the dynamic linker
#   finds libnetcdff.so / libhdf5*.so.
#   Required env: DATA, COMOUT, RUN, cycle, PDY, EXECnos / HOMEnos.
_schism_run_combine_hotstart() {
    local step=${1:-0}
    local phase=${2:-nowcast}

    if [ -z "$step" ] || [ "$step" = "0" ]; then
        echo "_schism_run_combine_hotstart: invalid step=${step}, skipping"
        return 1
    fi

    cd ${DATA}/outputs || {
        echo "_schism_run_combine_hotstart: missing ${DATA}/outputs"
        return 2
    }

    local COMBINE_EXE=""
    for _cand in \
        "${EXECnos:-}/schism_combine_hotstart7.exe" \
        "${HOMEnos:-}/exec/schism_combine_hotstart7.exe" \
        "${EXECnos:-}/nos_ofs_combine_hotstart" \
        "${EXECstofs3d:-}/stofs_3d_atl_combine_hotstart"; do
        if [ -x "$_cand" ]; then COMBINE_EXE="$_cand"; break; fi
    done

    if [ -z "$COMBINE_EXE" ]; then
        echo "WARNING: schism_combine_hotstart7.exe not found"
        local _combined=$(ls hotstart_it=*.nc 2>/dev/null | tail -1)
        if [ -n "$_combined" ] && [ -s "$_combined" ]; then
            local _rst_name="${RUN}.${cycle}.${PDY}.rst.${phase}.nc"
            cp -p "$_combined" "${COMOUT}/${_rst_name}"
            echo "  Found pre-combined hotstart: $_combined, archived as ${_rst_name}"
            return 0
        fi
        return 3
    fi

    echo "_schism_run_combine_hotstart: step=${step} phase=${phase}"
    echo "  Using combine executable: $COMBINE_EXE"

    # Patch LD_LIBRARY_PATH for hpc-stack netcdf/4.7.4 + hdf5;
    # combine_hotstart7 is compiled against these libs and the OS default
    # netcdf is not ABI-compatible.
    for _lib in \
        /apps/prod/hpc-stack/intel-19.1.3.304/netcdf/4.7.4/lib \
        /apps/prod/hpc-stack/intel-19.1.3.304/hdf5/*/lib \
        /apps/prod/hpc-stack/intel-*/netcdf/*/lib \
        /apps/prod/hpc-stack/intel-*/hdf5/*/lib; do
        [ -d "$_lib" ] && export LD_LIBRARY_PATH="${_lib}:${LD_LIBRARY_PATH:-}"
    done

    $COMBINE_EXE -i $step
    local rc=$?
    echo "_schism_run_combine_hotstart: combine_hotstart7 returned rc=${rc}"

    if [ $rc -eq 0 ] && [ -s "hotstart_it=${step}.nc" ]; then
        local _rst_name="${RUN}.${cycle}.${PDY}.rst.${phase}.nc"
        local _combined="hotstart_it=${step}.nc"
        # Archive in combine_hotstart7's native HDF5 format - do NOT convert
        # here. rst.nowcast.nc must stay HDF5; the CLASSIC conversion happens
        # downstream when staging to init.nowcast.nc.
        cp -p "$_combined" "${COMOUT}/${_rst_name}"
        echo "  Archived to ${COMOUT}/${_rst_name} (NETCDF4/HDF5, native combine output)"
    else
        echo "WARNING: combine_hotstart7 failed (rc=${rc}) or output missing"
    fi

    return ${rc}
}

# End of nos_run.sh
