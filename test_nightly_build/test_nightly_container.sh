#!/bin/bash
set -e

echo "[INFO] Pulling nightly image..."
sudo docker pull mjisan/stofsworkflow:nightly

echo "[INFO] Running container..."
sudo docker run --rm -it \
  --tmpfs /tmp:rw,size=2g \
  -v /lustre/mjisan/20250504_datasets/extracted_gfs/lfs/h1/ops/prod/com/gfs:/lfs/h1/ops/prod/com/gfs \
  -v /lustre/mjisan/20250504_datasets/extracted_hrrr/lfs/h1/ops/prod/com/hrrr:/lfs/h1/ops/prod/com/hrrr \
  -v /lustre/mjisan/20250504_datasets/extracted_nwm/nwm/v3.0:/lfs/h1/ops/prod/com/nwm/v3.0 \
  -v /lustre/mjisan/extracted_fix/fix/stofs_3d_atl:/home/wcoss2/sandbox/stofs3d/fix/stofs_3d_atl \
  -v /lustre/mjisan/20250504_datasets/extracted_rtofs/rtofs:/lfs/h1/ops/prod/com/rtofs \
  -v /lustre/mjisan/20250504_datasets/20250503:/home/wcoss2/sandbox/dcom_root \
  -v /lustre/mjisan/stofs_rerun:/home/wcoss2/sandbox/stofs3d/rerun \
  -v /lustre/mjisan/stofs_dataroot:/home/wcoss2/sandbox/stofs3d/dataroot \
  mjisan/stofsworkflow:nightly bash -c "
    echo '[INFO] Sourcing environment...';
    source /home/wcoss2/environment.sh 20250504 12 /home/wcoss2/sandbox

    echo '[INFO] Running STOFS workflow prep-forecast...';
    stofs prep-forecast --config config_schism.yaml
  "
