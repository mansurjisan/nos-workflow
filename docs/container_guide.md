# Running STOFS-3D-ATL prep in the WCOSS2-like container

The image (`containers/Dockerfile`) is Rocky 9 with SLURM, ecFlow, NCEP libs, wgrib2, ADCIRC, SCHISM and the STOFS-3D-ATL utilities (`stofs_3d_atl_tide_fac`, `netcdf2shef`, `gen_3Dth_from_hycom`, `gen_nudge_from_hycom`) built from `sorc/`. The current nos-workflow tree is at `/opt/nosofs` (also `/lfs/h1/nos/nosofs/packages/nos-workflow`), executables in `/opt/nosofs/exec`. Only prep is run in it.

## Build or pull
```bash
git clone --recurse-submodules https://github.com/oceanmodeling/nos-workflow.git && cd nos-workflow
git checkout feat/container-atl      # becomes develop after merge
docker build -f containers/Dockerfile -t stofsworkflow .   # fails at once if nos-utils is empty
docker pull <dockerhub-user>/stofsworkflow:develop         # or pull the CI image
```

## Inputs on the host
```bash
export PDY=20261001 CLONE=$PWD
export B=<bundle root>          # the extracted case bundle, top folder stofs_3d_atl_20261001/
export COMIN=<comin dir>        # stage_comin.py writes gfs/ hrrr/ nwm/ rtofs/ here
export SANDBOX=$HOME/atl_sandbox
mkdir -p $SANDBOX
# fix: fetch into the clone (keeps the two tracked param.nml templates), or merge the E: tarball into it
./tools/fetch_stofs_3d_atl_fix.sh                       # -> $CLONE/fix/stofs_3d_atl_ufs
# tar -xzf /mnt/e/STOFS_3D_ATL_FILES/atl_fix_stofs_3d_atl_ufs.tgz -C $CLONE   # alternative
export FIX=$CLONE/fix/stofs_3d_atl_ufs
# GFS, HRRR, NWM are not in the bundle (RTOFS is): download from AWS
python3 ush/stage_comin.py --pdy $PDY --cyc 12 --comroot $COMIN --profile stofs_3d_atl --sources gfs,hrrr,nwm,rtofs --jobs 8
# first-cycle seeds (run on the host; need nccopy or ncks; tools/ is not in the image)
tools/hercules_atl_seed_init.sh $PDY $SANDBOX/com_atl_sa/nos/stofs_3d_atl_ufs.$PDY
# coupled variant: a RELATIVE link, so it also resolves inside the container
mkdir -p $SANDBOX/com_atl_ufs/nos/stofs_3d_atl_ufs.$PDY && ln -sf ../../../com_atl_sa/nos/stofs_3d_atl_ufs.$PDY/stofs_3d_atl_ufs.t12z.$PDY.init.nowcast.nc $SANDBOX/com_atl_ufs/nos/stofs_3d_atl_ufs.$PDY/
tools/hercules_atl_seed_prev.sh $B/seeds/dyn_seed_<PDY-1> $SANDBOX/com_atl_sa $PDY $SANDBOX/com_atl_ufs
chmod -R a+rwX $SANDBOX         # the container user (wcoss2, uid 1000) must be able to write
```

## Mounts
| Host | Container |
|---|---|
| `$COMIN/gfs` (`gfs.<PDY>/<HH>/atmos/`), `hrrr`, `nwm`, `rtofs` | `/lfs/h1/ops/prod/com/{gfs,hrrr,nwm,rtofs}` |
| dcom (`<day>/coops_waterlvlobs`, `can_streamgauge`, `validation_data/marine/cmems/ssh`; PDY and PDY-1) | `/lfs/h1/ops/prod/dcom` |
| `$FIX` | `/opt/nosofs/fix/stofs_3d_atl_ufs` |
| `$SANDBOX` | `/home/wcoss2/sandbox` |

A `<ver>` subdirectory under a com mount is used when present. NWM, GFS, HRRR and RTOFS versions come from `versions/run.ver`.

## Run
```bash
docker run --rm \
  -v $COMIN/gfs:/lfs/h1/ops/prod/com/gfs:ro -v $COMIN/hrrr:/lfs/h1/ops/prod/com/hrrr:ro \
  -v $COMIN/rtofs:/lfs/h1/ops/prod/com/rtofs:ro -v $COMIN/nwm:/lfs/h1/ops/prod/com/nwm:ro \
  -v $B/dcom:/lfs/h1/ops/prod/dcom:ro \
  -v $FIX:/opt/nosofs/fix/stofs_3d_atl_ufs:ro \
  -v $SANDBOX:/home/wcoss2/sandbox \
  stofsworkflow bash -c 'source environment.sh '$PDY' 12 /home/wcoss2/sandbox && $HOMEnos/jobs/JNOS_PREP'
```
`OFS=stofs_3d_atl_ufs_standalone` is the default; add `-e OFS=stofs_3d_atl_ufs` for the coupled variant. Each variant has its own COMROOT: `$SANDBOX/com_atl_sa` (standalone) and `$SANDBOX/com_atl_ufs` (coupled); COMOUT is `<COMROOT>/nos/stofs_3d_atl_ufs.<PDY>`. A pass logs `STAGE_SUMMARY ... status=PASS`. See `docs/stofs_3d_atl_run_guide.md` section 2 for the seeds.
