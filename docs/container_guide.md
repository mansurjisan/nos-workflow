# Running STOFS-3D-ATL prep in the WCOSS2-like container

The image (`containers/Dockerfile`) is Rocky 9 with SLURM, ecFlow, NCEP libs, wgrib2, ADCIRC, SCHISM and `stofs_3d_atl_tide_fac`, built from the public ops v3.1.5 source at image build time (prep's OBC and nudging use the Python ops ports). The current nos-workflow tree is at `/opt/nosofs` (also `/lfs/h1/nos/nosofs/packages/nos-workflow`), executables in `/opt/nosofs/exec`. Only prep is run in it.

The steps below build the frozen test case 20261001 12z and run STOFS-3D-ATL v3.1 standalone prep on it. They were tested on AWS ParallelWorks (4 vCPUs) on 2026-10-21: prep passed in about 19 minutes, and on a second machine its forcing matched the WCOSS2 nos-workflow run of the same cycle.

## 1. Docker and the image
```bash
sudo systemctl start docker                       # if `docker` cannot reach the daemon
sudo docker pull mjisan/stofsworkflow:develop
sudo docker tag mjisan/stofsworkflow:develop stofsworkflow:latest
```
CI (`.github/workflows/docker-build.yml`) publishes `:develop` on each develop push and `:develop-nightly` every day at 05:00 UTC. `:nightly` is the old v2.1 image. To build instead (30-60 min; fails at once if nos-utils is empty), run `sudo docker build -f containers/Dockerfile -t stofsworkflow:latest .` from a clone.

## 2. Clone and paths
```bash
export W=/path/to/work                            # about 120 GB
mkdir -p $W && cd $W
git clone --recurse-submodules https://github.com/oceanmodeling/nos-workflow.git && cd nos-workflow
export C=$W/atl_20261001                          # case data
export S=$C/sandbox                               # COMROOT, work dirs, logs
export COMIN=$C/comin DCOM=$C/stofs_3d_atl_20261001/dcom FIX=$PWD/fix/stofs_3d_atl_ufs
mkdir -p $C $S && chmod -R a+rwX $S
```
The container runs as `wcoss2` (uid 1000), so `$S` must be writable by that uid. Files it writes belong to the host user with uid 1000, so remove them with `sudo`.

## 3. Case data (about 30 min)
```bash
./tools/fetch_stofs_3d_atl_fix.sh                 # fix from the NCO ops package into $FIX, keeps the tracked templates
python3 ush/stage_comin.py --pdy 20261001 --cyc 12 --comroot $COMIN \
  --profile stofs_3d_atl --sources gfs,hrrr,nwm,rtofs --jobs 8      # 385 files, about 87 GB, from AWS
tar xzf <case tarball> -C $C                      # stofs_3d_atl_20261001/{dcom,seeds}, 73 MB
tools/hercules_atl_seed_prev.sh $C/stofs_3d_atl_20261001/seeds/dyn_seed_20260930 $S/com_atl_sa 20261001
sudo docker run --rm -v $S:$S -v $PWD/tools:/tools:ro stofsworkflow:latest \
  bash -c "bash /tools/hercules_atl_seed_init.sh 20261001 $S/com_atl_sa/nos/stofs_3d_atl_ufs.20261001"
sudo chmod -R a+rwX $S
```
- The case tarball holds the WCOSS2 dcom snapshot (CO-OPS water levels, St. Lawrence, CMEMS ADT) and the previous-cycle seed for 20261001. These are not public in this form. On ParallelWorks it is `/lustre/mjisan/pw_upload_20261001.tgz`.
- `hercules_atl_seed_init.sh` downloads the 26 GB ops restart from S3 and converts it to netCDF-4 classic with `nccopy`. It runs in the container because the host may not have `nccopy`. It ends with `init seed ready: ...init.nowcast.nc`.
- Coupled variant: also pass `$S/com_atl_ufs` as a fourth argument to `hercules_atl_seed_prev.sh`, and link the start state with a relative link, because seed_init's own link argument writes a host path that breaks in the container:
  `mkdir -p $S/com_atl_ufs/nos/stofs_3d_atl_ufs.20261001 && ln -sf ../../../com_atl_sa/nos/stofs_3d_atl_ufs.20261001/stofs_3d_atl_ufs.t12z.20261001.init.nowcast.nc $S/com_atl_ufs/nos/stofs_3d_atl_ufs.20261001/`

## 4. Run
```bash
sudo docker run --rm \
  -v $COMIN/gfs:/lfs/h1/ops/prod/com/gfs:ro -v $COMIN/hrrr:/lfs/h1/ops/prod/com/hrrr:ro \
  -v $COMIN/nwm:/lfs/h1/ops/prod/com/nwm:ro -v $COMIN/rtofs:/lfs/h1/ops/prod/com/rtofs:ro \
  -v $DCOM:/lfs/h1/ops/prod/dcom:ro \
  -v $FIX:/opt/nosofs/fix/stofs_3d_atl_ufs:ro \
  -v $S:/home/wcoss2/sandbox \
  stofsworkflow:latest bash -c 'source environment.sh 20261001 12 /home/wcoss2/sandbox && $HOMEnos/jobs/JNOS_PREP' \
  2>&1 | tee $C/prep.log | grep -E "STAGE_SUMMARY|: (OK|FAIL)|worker"
```
The log shows `Running 4 steps with 1 worker(s) (sequential)` and GFS, HRRR, NWM and TIDAL `OK` for the nowcast, then the same for the forecast, then `STAGE_SUMMARY stage=prep ofs=stofs_3d_atl_ufs status=PASS`. COMOUT `$S/com_atl_sa/nos/stofs_3d_atl_ufs.20261001` then has 22 files. A failure exits non-zero, with a FATAL line, and keeps its work directory under `$S/work/`.

`OFS=stofs_3d_atl_ufs_standalone` is the default. Add `-e OFS=stofs_3d_atl_ufs` for the coupled variant, whose COMROOT is `$S/com_atl_ufs`.

## Mounts
| Host | Container |
|---|---|
| `$COMIN/gfs` (`gfs.<PDY>/<HH>/atmos/`), `hrrr`, `nwm`, `rtofs` | `/lfs/h1/ops/prod/com/{gfs,hrrr,nwm,rtofs}` |
| `$DCOM` (`<day>/coops_waterlvlobs`, `can_streamgauge`, `validation_data/marine/cmems/ssh`; PDY and PDY-1) | `/lfs/h1/ops/prod/dcom` |
| `$FIX` | `/opt/nosofs/fix/stofs_3d_atl_ufs` |
| `$S` | `/home/wcoss2/sandbox` |

A `<ver>` subdirectory under a com mount is used when present. NWM, GFS, HRRR and RTOFS versions come from `versions/run.ver`. Prep runs its GFS, HRRR, NWM and TIDAL steps one at a time when netCDF4-python is 1.6 or newer, because HDF5 is not thread-safe. `-e NOS_PREP_WORKERS=<n>` overrides this. See `docs/stofs_3d_atl_run_guide.md` section 2 for the seeds.
