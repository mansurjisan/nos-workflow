#!/bin/bash
# ============================================================================
# mpiexec_wrapper.sh - Translate Cray MPICH mpiexec args to OpenMPI mpirun
#
# WCOSS2 scripts call: mpiexec -n N -ppn P --cpu-bind core <executable>
# Docker OpenMPI needs: mpirun --allow-run-as-root -np N --oversubscribe <executable>
#
# Install as: ln -sf /opt/nosofs/docker/mpiexec_wrapper.sh /usr/local/bin/mpiexec
# ============================================================================

# Ensure the model executable finds spack-stack + OpenMPI shared libraries
# (libnetcdf.so.19, libnetcdff.so.7, libesmf.so, libmpi.so.40, ...). On
# Hercules the site MPI/modules may instead provide these; this is a
# self-contained fallback for the container's own OpenMPI build.
[ -f /opt/nosofs/docker/spack_libs.env ] && . /opt/nosofs/docker/spack_libs.env

NPROCS=""
EXECUTABLE=""
ARGS=()

# Parse Cray MPICH-style arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        -n|-np)
            NPROCS="$2"
            shift 2
            ;;
        -ppn|--ppn)
            # Ignore processes-per-node (OpenMPI handles this automatically)
            shift 2
            ;;
        --cpu-bind|--cpu_bind)
            # Ignore CPU binding (not needed in container)
            shift 2
            ;;
        --depth)
            # Ignore depth (Cray-specific)
            shift 2
            ;;
        -l|--line-buffer)
            # Ignore line buffering flag
            shift
            ;;
        -*)
            # Pass unknown flags through
            ARGS+=("$1")
            shift
            ;;
        *)
            # First non-flag argument is the executable
            EXECUTABLE="$1"
            shift
            # Everything after executable is its arguments
            ARGS+=("$@")
            break
            ;;
    esac
done

if [ -z "$NPROCS" ] || [ -z "$EXECUTABLE" ]; then
    echo "ERROR: mpiexec wrapper requires -n <nprocs> <executable>" >&2
    echo "Usage: mpiexec -n 12 ./fv3_coastalS.exe" >&2
    exit 1
fi

# Find the real mpirun (OpenMPI)
MPIRUN=$(command -v mpirun 2>/dev/null || echo "/usr/lib64/openmpi/bin/mpirun")

if [ ! -x "$MPIRUN" ]; then
    echo "ERROR: mpirun not found" >&2
    exit 1
fi

# For cfp: run serially (avoids 8x redundant work from MPI rank duplication)
# For model executables: use real MPI, capped to MPI_MAX_TASKS if set
if [ "$(basename "$EXECUTABLE")" = "cfp" ]; then
    echo "[mpiexec_wrapper] Running cfp serially (no MPI overhead)"
    exec "$EXECUTABLE" "${ARGS[@]}"
else
    # Cap MPI ranks to available resources (container has fewer cores than WCOSS2)
    if [ -n "${MPI_MAX_TASKS:-}" ] && [ "$NPROCS" -gt "$MPI_MAX_TASKS" ]; then
        echo "[mpiexec_wrapper] Capping MPI ranks from $NPROCS to $MPI_MAX_TASKS (MPI_MAX_TASKS)"
        NPROCS=$MPI_MAX_TASKS
    fi
    echo "[mpiexec_wrapper] Executing: $MPIRUN --allow-run-as-root -np $NPROCS --oversubscribe $EXECUTABLE ${ARGS[*]:-}"
    exec "$MPIRUN" --allow-run-as-root -np "$NPROCS" --oversubscribe "$EXECUTABLE" "${ARGS[@]}"
fi
