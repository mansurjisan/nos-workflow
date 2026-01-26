# Hercules HPC Deployment Guide

This guide covers deploying and running the NOS-Workflow Singularity container on NOAA's Hercules HPC.

## Prerequisites

- Access to Hercules HPC
- Singularity/Apptainer available (check with `module avail singularity` or `which singularity`)
- Storage space for container (~1.5GB) and workflow data

## 1. Download the Container

### Option A: Pull from Sylabs Cloud (Recommended)

```bash
# Load singularity module if needed
module load singularity

# Create container directory
mkdir -p /work/$USER/containers
cd /work/$USER/containers

# Pull latest container
singularity pull library://mjisan/nos-workflow/nos-workflow:latest

# Or pull specific version
singularity pull library://mjisan/nos-workflow/nos-workflow:20260125
```

### Option B: Download from GitHub Releases

```bash
cd /work/$USER/containers
wget https://github.com/mansurjisan/nos-workflow/releases/latest/download/nos-workflow.sif
```

### Option C: Transfer from Another System

```bash
# From your local machine
scp nos-workflow.sif username@hercules.rdhpcs.noaa.gov:/work/$USER/containers/
```

## 2. Verify Container

```bash
# Check container info
singularity inspect nos-workflow.sif

# Test basic functionality
singularity exec nos-workflow.sif /opt/models/adcirc/bin/adcirc --version
singularity exec nos-workflow.sif /opt/ecflow/bin/ecflow_client --version
singularity exec nos-workflow.sif python3 -c "import numpy; import netCDF4; print('OK')"
singularity exec nos-workflow.sif stofs --help
```

## 3. Directory Structure Setup

```bash
# Create workspace
export STOFS_ROOT=/work/$USER/stofs
mkdir -p $STOFS_ROOT/{sandbox,logs,containers}
mkdir -p $STOFS_ROOT/sandbox/{stofs3d,date,dcom_root}
mkdir -p $STOFS_ROOT/sandbox/stofs3d/{fix,dataroot,rerun,versions,scripts,ush,exec}

# Copy container
cp /work/$USER/containers/nos-workflow.sif $STOFS_ROOT/containers/
```

## 4. Extract Configuration Files from Container

```bash
cd $STOFS_ROOT

# Extract config files and scripts from container
singularity exec containers/nos-workflow.sif bash -c "
    cp /home/wcoss2/config_*.yaml /tmp/
    cp /home/wcoss2/environment.sh /tmp/
    cp -r /home/wcoss2/sandbox/stofs3d/scripts/* /tmp/scripts/ 2>/dev/null || true
    cp -r /home/wcoss2/sandbox/stofs3d/ush/* /tmp/ush/ 2>/dev/null || true
    cp -r /home/wcoss2/sandbox/stofs3d/versions/* /tmp/versions/ 2>/dev/null || true
    cp -r /home/wcoss2/sandbox/stofs3d/exec/* /tmp/exec/ 2>/dev/null || true
"

# Copy from container's /tmp to your workspace
singularity exec --bind $STOFS_ROOT/sandbox:/output containers/nos-workflow.sif bash -c "
    cp /home/wcoss2/config_*.yaml /output/
    cp /home/wcoss2/environment.sh /output/
    cp -r /home/wcoss2/sandbox/stofs3d/versions/* /output/stofs3d/versions/ 2>/dev/null || true
"
```

## 5. Create Runner Script

Create `$STOFS_ROOT/run_stofs.sh`:

```bash
#!/bin/bash
#SBATCH --job-name=stofs_workflow
#SBATCH --output=/work/%u/stofs/logs/stofs_%j.log
#SBATCH --error=/work/%u/stofs/logs/stofs_%j.err
#SBATCH --time=04:00:00
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --partition=service

# ============================================================
# STOFS Workflow Runner for Hercules
# Usage: sbatch run_stofs.sh [YYYYMMDD] [HH] [workflow]
# Example: sbatch run_stofs.sh 20260125 12 prep-forecast
# ============================================================

# Default values
DATE=${1:-$(date +%Y%m%d)}
HOUR=${2:-"12"}
WORKFLOW=${3:-"prep-forecast"}
CONFIG=${4:-"config_schism.yaml"}

# Paths
STOFS_ROOT=/work/$USER/stofs
SIF_FILE=$STOFS_ROOT/containers/nos-workflow.sif
SANDBOX=$STOFS_ROOT/sandbox
LOG_DIR=$STOFS_ROOT/logs

# Data paths on Hercules (adjust as needed)
GFS_PATH=/path/to/gfs/data
HRRR_PATH=/path/to/hrrr/data
NWM_PATH=/path/to/nwm/data
RTOFS_PATH=/path/to/rtofs/data
DCOM_PATH=/path/to/dcom/data

# Load singularity
module load singularity

echo "============================================"
echo "STOFS Workflow - Hercules"
echo "============================================"
echo "Date: $DATE"
echo "Hour: $HOUR"
echo "Workflow: $WORKFLOW"
echo "Config: $CONFIG"
echo "Container: $SIF_FILE"
echo "============================================"

# Create date directory
mkdir -p $SANDBOX/stofs3d/$DATE
mkdir -p $LOG_DIR

# Bind mounts (read-only for input data)
BIND_OPTS="\
--bind ${GFS_PATH}:/lfs/h1/ops/prod/com/gfs:ro \
--bind ${HRRR_PATH}:/lfs/h1/ops/prod/com/hrrr:ro \
--bind ${NWM_PATH}:/lfs/h1/ops/prod/com/nwm/v3.0:ro \
--bind ${RTOFS_PATH}:/lfs/h1/ops/prod/com/rtofs:ro \
--bind ${DCOM_PATH}:/home/wcoss2/sandbox/dcom_root:ro \
--bind ${SANDBOX}:/home/wcoss2 \
--pwd /home/wcoss2"

# Run workflow
singularity exec --contain --no-home --cleanenv $BIND_OPTS $SIF_FILE bash -c "
    source /home/wcoss2/environment.sh $DATE $HOUR /home/wcoss2/sandbox/
    export PATH='/opt/ncep/bin:/opt/ecflow/bin:/opt/slurm/bin:/usr/local/bin:/usr/bin:/bin:/usr/lib64/openmpi/bin'
    stofs $WORKFLOW --config $CONFIG
"

EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo "Workflow completed successfully!"
else
    echo "Workflow failed with exit code: $EXIT_CODE"
fi

exit $EXIT_CODE
```

Make it executable:

```bash
chmod +x $STOFS_ROOT/run_stofs.sh
```

## 6. Running the Workflow

### Interactive Run (for testing)

```bash
# Load singularity
module load singularity

# Run interactively
cd $STOFS_ROOT
./run_stofs.sh 20260125 12 prep-forecast
```

### Batch Job Submission

```bash
# Submit as SLURM job
sbatch run_stofs.sh 20260125 12 prep-forecast

# Check job status
squeue -u $USER
```

### Interactive Shell (for debugging)

```bash
singularity shell --bind /work/$USER/stofs/sandbox:/home/wcoss2 nos-workflow.sif
```

## 7. Cron Job Setup (Operational Runs)

For automated daily runs, create a cron wrapper script `$STOFS_ROOT/cron_stofs.sh`:

```bash
#!/bin/bash
# Cron wrapper for STOFS workflow

STOFS_ROOT=/work/$USER/stofs
LOG_DIR=$STOFS_ROOT/logs/cron
DATE=$(date +%Y%m%d)
HOUR=12

mkdir -p $LOG_DIR

# Submit the job
cd $STOFS_ROOT
sbatch run_stofs.sh $DATE $HOUR prep-forecast >> $LOG_DIR/cron_${DATE}.log 2>&1
```

Add to crontab:

```bash
crontab -e

# Run daily at 14:00 UTC (after 12Z data is available)
0 14 * * * /work/username/stofs/cron_stofs.sh
```

## 8. Updating the Container

When a new container version is released:

```bash
cd /work/$USER/stofs/containers

# Backup current version
mv nos-workflow.sif nos-workflow.sif.backup

# Pull new version
singularity pull library://mjisan/nos-workflow/nos-workflow:latest

# Verify
singularity exec nos-workflow.sif stofs --version

# If issues, rollback
# mv nos-workflow.sif.backup nos-workflow.sif
```

## 9. Data Path Configuration

Update the paths in `run_stofs.sh` based on Hercules data locations:

| Data | Typical Hercules Path |
|------|----------------------|
| GFS | `/lfs4/HFIP/hfv3gfs/gfs` or project-specific |
| HRRR | `/lfs4/HFIP/hfv3gfs/hrrr` or project-specific |
| NWM | Check with data management team |
| RTOFS | Check with data management team |
| Fix files | Copy to your workspace or shared location |

## 10. Troubleshooting

### Container won't run

```bash
# Check singularity is loaded
module load singularity
singularity --version

# Check container integrity
singularity verify nos-workflow.sif
```

### Permission denied errors

```bash
# Check file permissions
ls -la nos-workflow.sif

# Container should be readable
chmod 644 nos-workflow.sif
```

### Out of memory

```bash
# Request more memory in SLURM
#SBATCH --mem=32G
```

### Missing data paths

```bash
# Verify bind mount paths exist
ls -la /path/to/gfs/data
```

### Debug mode

```bash
# Run with verbose output
singularity exec --debug $BIND_OPTS $SIF_FILE bash -c "..."
```

## 11. Environment Variables Reference

| Variable | Description | Example |
|----------|-------------|---------|
| `PDY` | Cycle date | 20260125 |
| `CYC` | Cycle hour | 12 |
| `HOMEstofs` | STOFS home directory | /home/wcoss2/sandbox/stofs3d |
| `DATAROOT` | Output data root | /home/wcoss2/sandbox/stofs3d/dataroot |
| `COMOUT` | Output directory | /home/wcoss2/sandbox/stofs3d/$PDY |

## 12. Support

- **Container Issues:** https://github.com/mansurjisan/nos-workflow/issues
- **Hercules Support:** RDHPCS help desk
- **STOFS Workflow:** Contact the development team
