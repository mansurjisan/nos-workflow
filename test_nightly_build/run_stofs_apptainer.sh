#!/bin/bash

# STOFS Workflow Apptainer/Singularity Runner Script
# Usage: ./run_stofs_apptainer.sh [date] [hour] [sandbox_path] [config_file] [workflow] [mode]
# Example: ./run_stofs_apptainer.sh 20250504 12 /home/wcoss2/sandbox/ config_schism.yaml prep-nowcast run
# Workflows: prep-nowcast, nowcast, prep-forecast, forecast, post
# Modes: 'run' (default), 'debug', 'interactive'

# Default values
DATE=${1:-"20250504"}
HOUR=${2:-"12"}
SANDBOX_PATH=${3:-"/home/wcoss2/sandbox/"}
CONFIG_FILE=${4:-"config_schism.yaml"}
WORKFLOW=${5:-"prep-nowcast"}
MODE=${6:-"run"}

# Paths - adjust these to match your setup
DATA_ROOT="/mnt/f/STOFS_CI_DATA"
SIF_FILE="/mnt/d/nos-workflow-container/nos-workflow/nos-workflow.sif"

# Create output directories
STOFS_RERUN="/mnt/f/STOFS_CI_DATA/stofs_rerun"
STOFS_DATAROOT="/mnt/f/STOFS_CI_DATA/stofs_dataroot"
STOFS_SANDBOX="/mnt/f/STOFS_CI_DATA/stofs_sandbox"
mkdir -p "$STOFS_RERUN"
mkdir -p "$STOFS_DATAROOT"
mkdir -p "$STOFS_SANDBOX/stofs3d"

# Create log directory
LOG_DIR="./logs"
mkdir -p $LOG_DIR
LOG_FILE="$LOG_DIR/stofs_workflow_${DATE}_${HOUR}_$(date +%Y%m%d_%H%M%S).log"

echo "Running STOFS workflow with Apptainer"
echo "======================================"
echo "Date: $DATE"
echo "Hour: $HOUR"
echo "Sandbox Path: $SANDBOX_PATH"
echo "Config File: $CONFIG_FILE"
echo "Workflow: $WORKFLOW"
echo "Mode: $MODE"
echo "Container: $SIF_FILE"
echo "Log file: $LOG_FILE"
echo

# Check if container exists
if [ ! -f "$SIF_FILE" ]; then
    echo "ERROR: Container not found at $SIF_FILE"
    exit 1
fi

# Apptainer bind mounts (equivalent to Docker -v)
# INPUT DATA: mounted as READ-ONLY (:ro) to protect your files
# OUTPUT DATA: mounted as read-write for workflow results
# SAFETY FLAGS:
# --contain    : Don't bind home directory, /tmp, or other host paths automatically
# --no-home    : Extra protection - don't mount user's home directory
# --cleanenv   : Don't pass host environment variables (cleaner isolation)
SAFETY_OPTS="--contain --no-home --cleanenv"

BIND_OPTS="\
--bind ${DATA_ROOT}/extracted_gfs/lfs/h1/ops/prod/com/gfs:/lfs/h1/ops/prod/com/gfs:ro \
--bind ${DATA_ROOT}/extracted_hrrr/lfs/h1/ops/prod/com/hrrr:/lfs/h1/ops/prod/com/hrrr:ro \
--bind ${DATA_ROOT}/extracted_nwm/nwm/v3.0:/lfs/h1/ops/prod/com/nwm/v3.0:ro \
--bind ${DATA_ROOT}/extracted_rtofs/rtofs:/lfs/h1/ops/prod/com/rtofs:ro \
--bind ${DATA_ROOT}/20250503:/home/wcoss2/sandbox/dcom_root:ro \
--bind ${STOFS_SANDBOX}:/home/wcoss2 \
--pwd /home/wcoss2"

case $MODE in
  "interactive")
    echo "Starting interactive container..."
    apptainer shell $SAFETY_OPTS $BIND_OPTS "$SIF_FILE"
    ;;
  "debug")
    echo "Running in debug mode - checking environment first..." | tee -a $LOG_FILE
    apptainer exec $SAFETY_OPTS $BIND_OPTS "$SIF_FILE" bash -c "
      echo '=== Initial environment ==='
      echo 'Initial PATH:' \$PATH
      echo '=== Sourcing environment ==='
      source /home/wcoss2/environment.sh $DATE $HOUR $SANDBOX_PATH
      echo '=== After sourcing ==='
      echo 'Raw PATH:' \$PATH
      echo 'HOMEstofs:' \$HOMEstofs
      echo '=== Fixing PATH manually ==='
      export PATH='/home/wcoss2/.local/bin:/home/wcoss2/bin:/usr/share/Modules/bin:/opt/ncep/bin:/opt/ecflow/bin:/opt/slurm/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/lib64/openmpi/bin:'\$HOMEstofs'/exec/'
      echo 'Fixed PATH:' \$PATH
      echo 'Checking for setpdy.sh:'
      test -f /opt/ncep/bin/setpdy.sh && echo 'setpdy.sh found!' || echo 'setpdy.sh not found'
      echo '=== Checking bind mounts ==='
      ls -la /lfs/h1/ops/prod/com/gfs 2>/dev/null | head -5 || echo 'GFS not mounted'
      ls -la /lfs/h1/ops/prod/com/hrrr 2>/dev/null | head -5 || echo 'HRRR not mounted'
      ls -la /lfs/h1/ops/prod/com/nwm/v3.0 2>/dev/null | head -5 || echo 'NWM not mounted'
      ls -la /home/wcoss2/sandbox/stofs3d/fix/stofs_3d_atl 2>/dev/null | head -5 || echo 'Fix not mounted'
      echo '=== Running stofs $WORKFLOW ==='
      stofs $WORKFLOW --config $CONFIG_FILE
    " 2>&1 | tee -a $LOG_FILE
    ;;
  "run"|*)
    echo "Starting Apptainer container and running STOFS workflow..." | tee -a $LOG_FILE
    apptainer exec $SAFETY_OPTS $BIND_OPTS "$SIF_FILE" bash -c "
      set -e
      echo 'Sourcing environment...'
      source /home/wcoss2/environment.sh $DATE $HOUR $SANDBOX_PATH
      echo 'Environment sourced, fixing PATH manually...'
      export PATH='/home/wcoss2/.local/bin:/home/wcoss2/bin:/usr/share/Modules/bin:/opt/ncep/bin:/opt/ecflow/bin:/opt/slurm/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/lib64/openmpi/bin:'\$HOMEstofs'/exec/'
      echo 'Fixed PATH:' \$PATH
      echo 'Running stofs $WORKFLOW...'
      stofs $WORKFLOW --config $CONFIG_FILE
    " 2>&1 | tee -a $LOG_FILE
    ;;
esac

if [ $? -eq 0 ]; then
    echo "STOFS workflow completed successfully!" | tee -a $LOG_FILE
else
    echo "STOFS workflow failed! Check log file: $LOG_FILE" | tee -a $LOG_FILE
    echo "Try running in debug mode: $0 $DATE $HOUR $SANDBOX_PATH $CONFIG_FILE debug"
    exit 1
fi
