# Running STOFS-3D-ATL prep in the WCOSS2-like container

The image (`containers/Dockerfile`) is Rocky 9 with SLURM, ecFlow, NCEP libs, wgrib2, ADCIRC, SCHISM and the STOFS-3D-ATL utilities (`stofs_3d_atl_tide_fac`, `netcdf2shef`, `gen_3Dth_from_hycom`, `gen_nudge_from_hycom`) built from `sorc/`. The current nos-workflow tree is at `/opt/nosofs` (also `/lfs/h1/nos/nosofs/packages/nos-workflow`), executables in `/opt/nosofs/exec`. Only prep is run in it.

## Build or pull
```bash
docker build -f containers/Dockerfile -t stofsworkflow .      # repo root, nos-utils submodule initialized
docker pull <dockerhub-user>/stofsworkflow:develop           # pushed by CI from develop
```

## Mounts
| Host | Container |
|---|---|
| stage_comin output `gfs/` (holds `gfs.<PDY>/<HH>/atmos/`) | `/lfs/h1/ops/prod/com/gfs` |
| `hrrr/` (`hrrr.<PDY>/conus/`) | `/lfs/h1/ops/prod/com/hrrr` |
| `rtofs/` (`rtofs.<YYYYMMDD>/rtofs_glo_{2ds,3dz}_*`) | `/lfs/h1/ops/prod/com/rtofs` |
| `nwm/` (`nwm.<PDY>/medium_range_mem1/`) | `/lfs/h1/ops/prod/com/nwm` |
| dcom (`<day>/coops_waterlvlobs`, `can_streamgauge`, `validation_data/marine/cmems/ssh`; PDY and PDY-1) | `/lfs/h1/ops/prod/dcom` |
| full `fix/stofs_3d_atl_ufs` (from `tools/fetch_stofs_3d_atl_fix.sh`) | `/opt/nosofs/fix/stofs_3d_atl_ufs` |
| writable sandbox (COMOUT and work) | `/home/wcoss2/sandbox` |

If a mount holds a `<ver>` subdirectory (for example `gfs/v16.3/gfs.<PDY>`), it is used automatically. NWM defaults to v3.0 (`NWM_VER` overrides).

## Run
```bash
docker run --rm \
  -v $COMIN/gfs:/lfs/h1/ops/prod/com/gfs:ro -v $COMIN/hrrr:/lfs/h1/ops/prod/com/hrrr:ro \
  -v $COMIN/rtofs:/lfs/h1/ops/prod/com/rtofs:ro -v $COMIN/nwm:/lfs/h1/ops/prod/com/nwm:ro \
  -v $B/dcom:/lfs/h1/ops/prod/dcom:ro \
  -v $FIX/stofs_3d_atl_ufs:/opt/nosofs/fix/stofs_3d_atl_ufs:ro \
  -v $SANDBOX:/home/wcoss2/sandbox \
  stofsworkflow bash -c 'source environment.sh 20261001 12 /home/wcoss2/sandbox && $HOMEnos/jobs/JNOS_PREP'
```
`OFS=stofs_3d_atl_ufs_standalone` is the default; `-e OFS=stofs_3d_atl_ufs` runs the coupled variant. COMOUT is `$SANDBOX/com/nos/stofs_3d_atl_ufs.<PDY>`; a pass logs `STAGE_SUMMARY ... status=PASS`.

The first cycle needs the seeds of `docs/stofs_3d_atl_run_guide.md` section 2 under `$SANDBOX/com/nos` (restart `init.nowcast.nc`, and `staout_1` / `rerun/` in the PDY-1 directory).

## Getting the inputs
`python3 ush/stage_comin.py --pdy 20261001 --cyc 12 --comroot $COMIN --profile stofs_3d_atl --sources gfs,hrrr,nwm,rtofs` downloads GFS, HRRR, NWM and RTOFS from the AWS open-data buckets. dcom files come from the case bundle.
