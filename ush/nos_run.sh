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

    # Standalone SCHISM: Phase-1's resolver emits USE_DATM=false and stages
    # the scribed pschism binary under $UFS_EXEC_NAME (pschism_WCOSS2). It
    # takes nscribes as argv[1]; there is no DATM/NUOPC layer to bind.
    if [ "${USE_DATM:-true}" = "false" ]; then
        local SCHISM_EXEC=${SCHISM_EXEC:-}
        local _exe_name=${UFS_EXEC_NAME:-pschism_WCOSS2}
        if [ -z "${SCHISM_EXEC}" ] || [ ! -x "${SCHISM_EXEC}" ]; then
            local _cand
            for _cand in \
                "${DATA}/${_exe_name}" \
                "${EXECnos:-}/${_exe_name}" \
                "${HOMEnos:-}/exec/${_exe_name}"; do
                if [ -x "$_cand" ]; then SCHISM_EXEC="$_cand"; break; fi
            done
        fi
        local NSCRIBES=${NSCRIBES:-6}
        echo "_schism_run_mpi: launching standalone SCHISM for phase=${phase}"
        echo "  mpiexec -n ${NTASKS} -ppn ${PPN} --cpu-bind core ${SCHISM_EXEC} ${NSCRIBES}"
        mpiexec -n ${NTASKS} -ppn ${PPN} --cpu-bind core ${SCHISM_EXEC} ${NSCRIBES}
        local rc=$?
        echo "_schism_run_mpi: mpiexec returned rc=${rc}"
        return ${rc}
    fi

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

# _schism_run_combine_fields <phase> - combine_output11(_MPI) wrapper for
#   OLDIO per-rank field output (schout_<rank>_<stack>.nc). Combines every
#   stack into global schout_<stack>.nc inside ${DATA}/outputs. No-op when
#   the run is scribed (global out2d_* already present) or no per-rank
#   files exist. Stays in shell for the same hpc-stack module-env reason
#   as _schism_run_combine_hotstart.
#   Required env: DATA; EXECnos / HOMEnos for exe resolution.
_schism_run_combine_fields() {
    local phase=${1:-nowcast}

    cd ${DATA}/outputs || {
        echo "_schism_run_combine_fields: missing ${DATA}/outputs"
        return 2
    }

    if ls out2d_[0-9]*.nc >/dev/null 2>&1; then
        echo "_schism_run_combine_fields: scribed outputs present; nothing to combine"
        return 0
    fi

    # Stack range from rank 0's per-rank files: schout_000000_<stack>.nc
    local _stacks=$(ls schout_000000_*.nc 2>/dev/null \
        | sed 's/.*_\([0-9][0-9]*\)\.nc$/\1/' | sort -n)
    if [ -z "${_stacks}" ]; then
        echo "_schism_run_combine_fields: no per-rank schout files; nothing to combine"
        return 0
    fi
    local _b=$(echo "${_stacks}" | head -1)
    local _e=$(echo "${_stacks}" | tail -1)
    local _n=$(echo "${_stacks}" | wc -l)

    local MPI_EXE="" SERIAL_EXE=""
    for _cand in \
        "${EXECnos:-}/combine_output11_MPI" \
        "${HOMEnos:-}/exec/combine_output11_MPI"; do
        if [ -x "$_cand" ]; then MPI_EXE="$_cand"; break; fi
    done
    for _cand in \
        "${EXECnos:-}/combine_output11" \
        "${HOMEnos:-}/exec/combine_output11"; do
        if [ -x "$_cand" ]; then SERIAL_EXE="$_cand"; break; fi
    done
    if [ -z "$MPI_EXE" ] && [ -z "$SERIAL_EXE" ]; then
        echo "WARNING: combine_output11(_MPI) not found under EXECnos/HOMEnos; fields combine skipped"
        return 3
    fi

    # Same hpc-stack LD_LIBRARY_PATH patch as the hotstart combine.
    for _lib in \
        /apps/prod/hpc-stack/intel-19.1.3.304/netcdf/4.7.4/lib \
        /apps/prod/hpc-stack/intel-19.1.3.304/hdf5/*/lib \
        /apps/prod/hpc-stack/intel-*/netcdf/*/lib \
        /apps/prod/hpc-stack/intel-*/hdf5/*/lib; do
        [ -d "$_lib" ] && export LD_LIBRARY_PATH="${_lib}:${LD_LIBRARY_PATH:-}"
    done

    echo "_schism_run_combine_fields: phase=${phase} stacks=${_b}..${_e} (${_n})"
    local rc=1
    if [ -n "$MPI_EXE" ]; then
        echo "  mpiexec -n ${_n} ${MPI_EXE} -b ${_b} -e ${_e}"
        mpiexec -n ${_n} ${MPI_EXE} -b ${_b} -e ${_e}
        rc=$?
        [ $rc -ne 0 ] && echo "WARNING: MPI fields combine failed (rc=${rc})"
    fi
    if [ $rc -ne 0 ] && [ -n "$SERIAL_EXE" ]; then
        echo "  ${SERIAL_EXE} -b ${_b} -e ${_e} (serial)"
        ${SERIAL_EXE} -b ${_b} -e ${_e}
        rc=$?
    fi

    if [ $rc -eq 0 ] && [ -s "schout_${_e}.nc" ]; then
        echo "_schism_run_combine_fields: combined schout_${_b}..${_e}.nc OK"
    else
        echo "WARNING: fields combine failed (rc=${rc}) or schout_${_e}.nc missing"
        [ $rc -eq 0 ] && rc=4
    fi
    return ${rc}
}

# End of nos_run.sh
