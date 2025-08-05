#!/bin/bash

# STOFS Workflow Docker Runner Script
# Usage: ./run_stofs_workflow.sh [date] [hour] [sandbox_path] [config_file] [mode]
# Example: ./run_stofs_workflow.sh 20250504 12 /home/wcoss2/sandbox/ config_schism.yaml run
# Modes: 'run' (default), 'debug', 'interactive'

# Default values
DATE=${1:-"20250504"}
HOUR=${2:-"12"}
SANDBOX_PATH=${3:-"/home/wcoss2/sandbox/"}
CONFIG_FILE=${4:-"config_schism.yaml"}
MODE=${5:-"run"}

# Check if running in a TTY (interactive) or not (cron)

if [ -t 1 ]; then
    DOCKER_INTERACTIVE="-it"
    echo "Running in interactive mode"
else
    DOCKER_INTERACTIVE=""
    echo "Running in non-interactive mode (likely cron)"
fi

# Create log directory and filename
LOG_DIR="./logs"
mkdir -p $LOG_DIR
LOG_FILE="$LOG_DIR/stofs_workflow_${DATE}_${HOUR}_$(date +%Y%m%d_%H%M%S).log"

echo "Running STOFS workflow with parameters:"
echo "Date: $DATE"
echo "Hour: $HOUR"
echo "Sandbox Path: $SANDBOX_PATH"
echo "Config File: $CONFIG_FILE"
echo "Mode: $MODE"
echo "Log file: $LOG_FILE"
echo

# Docker run options for STOFS3D Atlantic Workflow

DOCKER_OPTS="--tmpfs /tmp:rw,size=2g \
  -v /lustre/mjisan/20250504_datasets/extracted_gfs/lfs/h1/ops/prod/com/gfs:/lfs/h1/ops/prod/com/gfs \
  -v /lustre/mjisan/20250504_datasets/extracted_hrrr/lfs/h1/ops/prod/com/hrrr:/lfs/h1/ops/prod/com/hrrr \
  -v /lustre/mjisan/20250504_datasets/extracted_nwm/nwm/v3.0:/lfs/h1/ops/prod/com/nwm/v3.0 \
  -v /lustre/mjisan/extracted_fix/fix/stofs_3d_atl:/home/wcoss2/sandbox/stofs3d/fix/stofs_3d_atl \
  -v /lustre/mjisan/20250504_datasets/extracted_rtofs/rtofs:/lfs/h1/ops/prod/com/rtofs \
  -v /lustre/mjisan/20250504_datasets/20250503:/home/wcoss2/sandbox/dcom_root \
  -v /lustre/mjisan/stofs_rerun:/home/wcoss2/sandbox/stofs3d/rerun \
  -v /lustre/mjisan/stofs_dataroot:/home/wcoss2/sandbox/stofs3d/dataroot \
  -v $(pwd)/logs:/logs"

# Pull the latest Docker image from Docker Hub

echo "Pulling Docker image..." | tee -a $LOG_FILE
sudo docker pull mjisan/stofsworkflow:nightly 2>&1 | tee -a $LOG_FILE

case $MODE in
  "interactive")
    echo "Starting interactive container..."

    # Force interactive mode for this option
    sudo docker run -it $DOCKER_OPTS mjisan/stofsworkflow:nightly bash
    ;;
  "debug")
    echo "Running in debug mode - checking environment first..." | tee -a $LOG_FILE
    sudo docker run $DOCKER_INTERACTIVE $DOCKER_OPTS mjisan/stofsworkflow:nightly bash -c "
      echo '=== Initial environment ===' && \
      echo 'Initial PATH:' \$PATH && \
      echo '=== Sourcing environment ===' && \
      source environment.sh $DATE $HOUR $SANDBOX_PATH && \
      echo '=== After sourcing ===' && \
      echo 'Raw PATH:' \$PATH && \
      echo 'HOMEstofs:' \$HOMEstofs && \
      echo '=== Fixing PATH manually ===' && \
      export PATH=\"/home/wcoss2/.local/bin:/home/wcoss2/bin:/usr/share/Modules/bin:/opt/ncep/bin:/opt/ecflow/bin:/opt/slurm/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/lib64/openmpi/bin:\$HOMEstofs/exec/\" && \
      echo 'Fixed PATH:' \$PATH && \
      echo 'Checking for setpdy.sh:' && \
      test -f /opt/ncep/bin/setpdy.sh && echo 'setpdy.sh found!' || echo 'setpdy.sh not found' && \
      echo '=== Running stofs ===' && \
      stofs prep-forecast --config $CONFIG_FILE
    " 2>&1 | tee -a $LOG_FILE
    ;;
  "run"|*)
    echo "Starting Docker container and running STOFS workflow..." | tee -a $LOG_FILE
    sudo docker run $DOCKER_INTERACTIVE $DOCKER_OPTS mjisan/stofsworkflow:nightly bash -c "
      set -e
      echo 'Sourcing environment...'
      source environment.sh $DATE $HOUR $SANDBOX_PATH
      echo 'Environment sourced, fixing PATH manually...'
      # Set PATH manually with the correct directories from your interactive session
      export PATH=\"/home/wcoss2/.local/bin:/home/wcoss2/bin:/usr/share/Modules/bin:/opt/ncep/bin:/opt/ecflow/bin:/opt/slurm/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/lib64/openmpi/bin:\$HOMEstofs/exec/\"
      echo 'Fixed PATH:' \$PATH
      echo 'Running stofs prep-forecast...'
      stofs prep-forecast --config $CONFIG_FILE
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
