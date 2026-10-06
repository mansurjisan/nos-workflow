# Running STOFS-3D-ATL v3.1 with nos-workflow on WCOSS2 and Hercules

Applies to nos-workflow `develop` as of 2026-10-06. Update this guide in the same PR as any change to the ATL cards, launchers or fetch tool.

## 1. What you are running

Two variants. Both use the same mesh, fix files, prep and ranks.

| Variant | Engine | Executable | Ranks | Config |
|---|---|---|---|---|
| Standalone (operational-equivalent) | SCHISM 5.14 `pschism`, operational build flags | `stofs_3d_atl_pschism_v3.1.5` | 4912 SCHISM + 8 scribes = 4920 | `parm/systems/stofs_3d_atl_ufs_standalone.yaml` |
| UFS coupled | DATM + CMEPS + SCHISM (ufs-coastal) | `fv3_stofs_3d_atl.exe` | 120 DATM/MED + 4912 OCN = 5032 | `parm/systems/stofs_3d_atl_ufs.yaml` |

Each cycle is 12z with four stages: `prep`, `nowcast` (24 h), `forecast` (96 h), `post`.

Operational STOFS-3D-ATL runs one continuous 5-day run. nos-workflow runs the nowcast and forecast as two runs (the forecast restarts from the nowcast restart). The result was checked against operational output over the full 5 days.

Run identity: `NET=nos`, `RUN=OFS=PREFIXNOS=stofs_3d_atl_ufs` for both variants. The standalone mode comes from its yaml overlay. COMOUT is `${COMROOT}/nos/stofs_3d_atl_ufs.<PDY>`.

## 2. Concepts for both machines

### COMROOT: one per variant

Both variants write `nos/stofs_3d_atl_ufs.<PDY>`, so each has its own COMROOT:
- standalone: `COMROOT_SA` (WCOSS2 default `/lfs/h1/nos/ptmp/$LOGNAME/com_atl_sa`)
- coupled: `COMROOT_UFS` (WCOSS2 default `/lfs/h1/nos/ptmp/$LOGNAME/com`)

The launchers forward these to the jobs. Never point both variants at one COMROOT.

### First cycle versus later cycles

The first cycle needs a seed (section 3.2 / 4.2). Every later cycle needs nothing: it uses the previous day's files in the same COMROOT.

What a cycle takes from the day before:
1. **Initial state:** `${COMOUT}/stofs_3d_atl_ufs.t12z.<PDY>.init.nowcast.nc`. There is no cold start for ATL. For the first cycle this is the operational restart for the same PDY, converted to NETCDF4_CLASSIC (prep aborts otherwise). Later cycles use the previous nowcast restart automatically.
2. **Dynamic water-level adjustment inputs** in `${COMROOT}/nos/stofs_3d_atl_ufs.<PDY-1>`: `staout_1` (at least 10 kB), `rerun/stofs_3d_atl_ufs.t12z.avg_bias`, optionally `rerun/stofs_3d_atl_ufs.t12z.param.nml`. For the first cycle, seed them from operational files (`tools/hercules_atl_seed_prev.sh`, or `COMINrerun=<flat seed dir>`). Later cycles: the forecast stage writes `staout_1` and prep archives `rerun/...avg_bias`.

Without these files the adjustment applies zero bias; prep only logs a warning on WCOSS2 (the Hercules prep cards stop).

A flat seed directory holds:
```
staout_1                              # operational <PDY-1> COMOUT root staout_1
stofs_3d_atl_ufs.t12z.avg_bias        # operational <PDY-1>/rerun/stofs_3d_atl.t12z.avg_bias, renamed
param.nml                             # operational <PDY-1>/rerun/stofs_3d_atl.t12z.param.nml
```

### Inputs read by prep

- GFS 0.25 degree and HRRR CONUS (atmosphere); NWM medium_range_mem1 (rivers); RTOFS 2ds and 3dz US_east (ocean boundary).
- dcom: CO-OPS water levels (`dcom/<PDY>/coops_waterlvlobs/*.xml`), CMEMS ADT for PDY and PDY-1 (`dcom/<day>/validation_data/marine/cmems/ssh/nrt_global_allsat_phy_l4_<day>_<day>.nc`), St. Lawrence gauge (`dcom/<day>/can_streamgauge/02OA016_hydrometric.csv`).

On WCOSS2 these come from the operational tanks. On Hercules they must be staged (section 4.2).

### Fix files

`tools/fetch_stofs_3d_atl_fix.sh [DEST]` (default `fix/stofs_3d_atl_ufs`) stages everything in one command:
- 32 operational fix files (about 5.6 GB): mesh, vgrid, the 4912-rank `partition.prop`, nudging, ADT weights, the three operational river files (`river_msource.th`, `river_vsink.th`, `river_source_sink.in`) and the out2d mask. On WCOSS2 it copies from `/lfs/h1/ops/prod/packages/stofs.v3.1.5/fix/stofs_3d_atl`; elsewhere it downloads from the NCO mirror. Re-running skips files already complete.
- The coupled-only DATM/UFS templates (`datm_in.template`, `datm.streams.template`, `model_configure.template`, `fd_ufs.yaml`, `noahmptable.tbl`, `ufs.configure`). It copies the first five from `fix/secofs_ufs/` in the repo and derives `ufs.configure` from the SECOFS one (OCN ranks 120-5031, coupling step 150 s). Existing files are never overwritten.
- It ends by checking that `partition.prop` has 4912 ranks.

The two `param.nml` templates are tracked in git.

## 3. WCOSS2 (Cactus / Dogwood)

### 3.1 One-time setup

Clone anywhere, with any directory name:
```bash
cd /lfs/h1/nos/estofs/noscrub/$LOGNAME/packages          # or any directory you own
git clone https://github.com/mansurjisan/nos-workflow
cd nos-workflow && git checkout develop && git pull --ff-only
git submodule update --init ush/python/nos-utils
./tools/fetch_stofs_3d_atl_fix.sh
```
No card edits are needed. The cards default `PACKAGEROOT` to `/lfs/h1/nos/estofs/noscrub/$LOGNAME/packages`, and each launcher works out its own clone location and passes `PACKAGEROOT` to the jobs. Running a launcher from your clone uses your clone: it passes `PACKAGEROOT` and `HOMEnos` (the clone path) to every job. If you run a card directly with `qsub` (not through a launcher), add `-v PACKAGEROOT=<parent dir>,HOMEnos=<clone path>`.

Executables in `exec/`:

| File | How to get it |
|---|---|
| `stofs_3d_atl_pschism_v3.1.5` | `cp /apps/prod/schism/5.14.0/bin/pschism_WCOSS2_VL exec/stofs_3d_atl_pschism_v3.1.5` (the operational binary, built `-DNO_PARMETIS -DPREC_EVAP -DTVD_VL`). |
| `fv3_stofs_3d_atl.exe` | Coupled build, below. Keep it separate from SECOFS's `fv3_coastalS.exe`. |
| `nos_ofs_create_tide_fac_schism` | Fortran tide_fac. Copy from an existing nos-workflow `exec/` on WCOSS2. Required: for ATL a missing Fortran tide_fac fails prep (`STOFS-3D-ATL needs the Fortran tide_fac`); there is no Python fallback. |
| `schism_combine_hotstart7.exe` | Copy from an existing `exec/`. |

Coupled build: ufs-weather-model clone at oceanmodeling `3e5e83de23ce3b6d16207b0c4f78d7a56110b6b3` with submodules, plus two local patches applied before building:
- `SCHISM-interface/SCHISM-ESMF/src/schism/schism_nuopc_cap.F90`, md5 `b54e2615aa65ee1d38c385d5f7f1ea0c` after patching (`schism_esmf_cap_wcoss2_local.patch`)
- `CMEPS-interface/CMEPS/mediator/esmFldsExchange_coastal_mod.F90`, md5 `f243b8edc027a69f84c545f7e98f975c` after patching (`cmeps_wcoss2_local.patch`)

The patch files are kept outside the repo; ask the maintainer.
```bash
cd ufs-weather-model/tests
./compile.sh wcoss2 "-DAPP=CSTLS -DUSE_ATMOS=ON -DNO_PARMETIS=ON -DOLDIO=ON -DBUILD_TOOLS=ON -DPREC_EVAP=ON" stofs_atl_pe intel YES NO
grep -E "PREC_EVAP|NO_PARMETIS|OLDIO|USE_ATMOS|^APP" build_fv3_stofs_atl_pe/CMakeCache.txt   # all ON, APP=CSTLS
cp fv3_stofs_atl_pe.exe <your nos-workflow>/exec/fv3_stofs_3d_atl.exe
```
`PREC_EVAP` matters: without it SCHISM ignores precipitation and the operational river sinks (1,986,300) drain the domain.

### 3.2 Seed the first cycle

```bash
PDY=20261001; PDYm1=20260930
OPS=/lfs/h1/ops/prod/com/stofs/v3.1                      # operational COMOUT keeps about 5 days
COM=/lfs/h1/nos/ptmp/$LOGNAME/com                        # use COMROOT_SA's path for the standalone variant
```

Initial state (about 26 GB; do this on a compute or transfer node, not the login node if avoidable):
```bash
mkdir -p $COM/nos/stofs_3d_atl_ufs.$PDY
module load intel/19.1.3.304 PrgEnv-intel hdf5/1.10.6 netcdf/4.7.4
nccopy -k 'netCDF-4 classic model' $OPS/stofs_3d_atl.$PDY/rerun/stofs_3d_atl.t12z.restart.nc \
       $COM/nos/stofs_3d_atl_ufs.$PDY/stofs_3d_atl_ufs.t12z.$PDY.init.nowcast.nc
ncdump -h $COM/nos/stofs_3d_atl_ufs.$PDY/stofs_3d_atl_ufs.t12z.$PDY.init.nowcast.nc | head -12
#   expect: node = 3052121, elem = 5872610, side = 8924888, nVert = 49, ntracers = 2
```
If operational has already purged that PDY, get `stofs_3d_atl.t12z.restart.nc` from `s3://noaa-nos-stofs3d-pds/STOFS-3D-Atl/stofs_3d_atl.<PDY>/rerun/`. `tools/hercules_atl_seed_init.sh` does download, conversion and checks.

Previous-cycle seed:
```bash
SEED=/lfs/h1/nos/estofs/noscrub/$LOGNAME/dyn_seed_$PDYm1 && mkdir -p $SEED
cp $OPS/stofs_3d_atl.$PDYm1/staout_1 $SEED/staout_1
cp $OPS/stofs_3d_atl.$PDYm1/rerun/stofs_3d_atl.t12z.avg_bias $SEED/stofs_3d_atl_ufs.t12z.avg_bias
cp $OPS/stofs_3d_atl.$PDYm1/rerun/stofs_3d_atl.t12z.param.nml $SEED/param.nml
./tools/hercules_atl_seed_prev.sh $SEED $COM $PDY       # lays it out under $COM/nos/stofs_3d_atl_ufs.$PDYm1
```
Copy seeds without `cp -p`. ptmp is purged by file age, and `cp -p` keeps the old timestamp, so a copied seed can vanish within days. Keep the flat seed on noscrub.

For the coupled variant use `COM=$COMROOT_UFS` paths; for standalone use the `COMROOT_SA` path. Seed each variant you will run.

### 3.3 Run

Run the launcher from your clone. Each stage waits on `afterok` of the previous one.
```bash
cd <your nos-workflow>/pbs/stofs_3d_atl_ufs_standalone && ./launch_stofs_standalone.sh 20261001 12
cd <your nos-workflow>/pbs/stofs_3d_atl_ufs            && bash launch_stofs_3d_atl_ufs.sh 20261001 12
STAGES=post ./launch_stofs_standalone.sh 20261001 12           # re-run only some stages
STAGES="forecast post" bash launch_stofs_3d_atl_ufs.sh 20261001 12
```
Use `bash <launcher>` if a fresh clone (for example on a Windows-mounted drive) lost the execute bit and you get Permission denied.

The standalone cards load the module stack for `pschism` from a version file: `$PACKAGEROOT/IT-stofs.v2.1.0/versions/stofs_3d_atl/run.ver` if it exists, otherwise the operational `/lfs/h1/ops/prod/packages/stofs.v3.1.5/versions/run.ver` (which matches the operational binary). Only the compiler/MPI/hdf5 stack comes from that file; the J-job keeps the nos-workflow python. They stop if neither is readable, and the job log prints `STOFS_RUNVER=<file used>`. Set `STOFS_RUNVER` to override.

Optional settings go in the environment before the launcher and are forwarded: `COMROOT_SA`, `COMROOT_UFS`, `NOS_POST_PRODUCTS`, `NOS_POST_MAX_WORKERS`, `PKG` (override the clone location), `STOFS_RUNVER` (standalone only).

One stage at a time, for example with a flat seed:
```bash
cd <your nos-workflow>/pbs/stofs_3d_atl_ufs_standalone
qsub -v PDY=20261001,CYC=12,NOS_ARCHIVE_MANIFEST=YES,PACKAGEROOT=<parent dir>,HOMEnos=<clone path>,COMINrerun=$SEED jnos_prep_00.pbs
```
`qsub -v` replaces the job environment, so pass everything the job needs.

### 3.4 Later cycles

No seed. Submit day N+1 after day N's forecast has passed (its restart and `staout_1` must exist):
```bash
./launch_stofs_standalone.sh 20261002 12
```
The launcher gates only the stages of one cycle; it does not wait for the previous day. Maintenance windows: PBS will not start a job whose walltime crosses one.

### 3.5 Resources (WCOSS2, 128 cores/node)

| Stage | Standalone | Coupled |
|---|---|---|
| prep | 1 node, 5 h limit | 1 node (also builds the DATM forcing) |
| nowcast (24 h) | 41 nodes, 5 h limit | 42 nodes, 1:30 limit |
| forecast (96 h) | 41 nodes, 5 h limit | 42 nodes, 5:30 limit |
| post | 1 node, 2 h limit | 1 node, 4 h limit |

## 4. Hercules (RDHPCS, Slurm)

### 4.1 One-time setup

Use one clone of nos-workflow on `develop`, e.g. `/work2/noaa/nos-surge/$LOGNAME/nos-workflow`; it can hold SECOFS and ATL. Environment file; source it in every ATL shell, never in a shell used to submit SECOFS jobs:
```bash
cat > /work2/noaa/nos-surge/$LOGNAME/atl_env.sh <<'EOF'
export PK=/work2/noaa/nos-surge/$LOGNAME
export A=$PK/atl_inputs B=$PK/atl_inputs/stofs_atl_1001
export PACKAGEROOT=$PK HW=$PK/nos-workflow
export NOS_PTMP=$PK/nos-run/ptmp
export COMROOT_SA=$NOS_PTMP/$LOGNAME/com_atl_sa COMROOT_UFS=$NOS_PTMP/$LOGNAME/com_atl_ufs
export EXECnos=$PK/nos-workflow/exec PDY=20261001
EOF
. /work2/noaa/nos-surge/$LOGNAME/atl_env.sh
module purge; module use $HW/modulefiles; module load nos_hercules.intel; . ~/nos-venv/bin/activate
cd $HW && git submodule update --init ush/python/nos-utils && ./tools/fetch_stofs_3d_atl_fix.sh
```
The Slurm cards require `PACKAGEROOT` and stop within seconds without it.

Executables (all four in `$EXECnos`):
```bash
# operational source for both: ask the maintainer for the v3.1.5 sorc tarball, unpacked in $A/sorc
SRC=$A/sorc/stofs_3d_atl_tide_fac.fd $HW/tools/build_stofs_3d_atl_tide_fac_hercules.sh
SRC=$A/sorc/stofs_3d_atl_pschism.fd  $HW/tools/build_stofs_3d_atl_pschism_hercules.sh
# coupled: a SEPARATE ufs clone, never the SECOFS one
cd $PK && git clone https://github.com/oceanmodeling/ufs-weather-model ufs-weather-model-atl
cd ufs-weather-model-atl && git checkout 3e5e83de23ce3b6d16207b0c4f78d7a56110b6b3 && git submodule update --init --recursive
git -C SCHISM-interface/SCHISM-ESMF apply $A/ufs_wcoss2_patches/schism_esmf_cap_wcoss2_local.patch
git -C CMEPS-interface/CMEPS apply $A/ufs_wcoss2_patches/cmeps_wcoss2_local.patch
UFS_DIR=$PK/ufs-weather-model-atl UFS_COMMIT=3e5e83de23ce3b6d16207b0c4f78d7a56110b6b3 $HW/tools/build_stofs_3d_atl_ufs_hercules.sh
```
`schism_combine_hotstart7.exe` is already in the shared `exec/`. The coupled build script stops unless the clone is at that commit, both patched sources match the md5 values, `PREC_EVAP`/`NO_PARMETIS`/`OLDIO` are ON, and all libraries resolve.

### 4.2 Inputs and seeds

Public data, about 100 GB per cycle. Stage a cycle only after its GFS 12z run is complete:
```bash
python3 $HW/ush/stage_comin.py --pdy $PDY --cyc 12 --comroot $NOS_PTMP/$LOGNAME/comin_atl --profile stofs_3d_atl --jobs 8
```
Expected counts for 20261001: GFS 127, HRRR 73, NWM 139, RTOFS 46 files.

dcom files are not public in this form; ask the maintainer for the case bundle (copied from WCOSS2) and unpack it into `$B`. The prep card stops if any of the dcom files in section 2 are missing.

First-cycle seeds (run in `tmux`):
```bash
$HW/tools/hercules_atl_seed_init.sh $PDY $COMROOT_SA/nos/stofs_3d_atl_ufs.$PDY $COMROOT_UFS/nos/stofs_3d_atl_ufs.$PDY
$HW/tools/hercules_atl_seed_prev.sh $B/seeds/dyn_seed_<PDY-1> $COMROOT_SA $PDY $COMROOT_UFS
```
`seed_init` downloads the 26 GB operational restart from S3, converts it to NETCDF4_CLASSIC, checks dimensions, and links the coupled copy to the standalone one.

### 4.3 Run

Submit one stage at a time and wait for `status=PASS` before the next (do not use `--dependency=afterok`):
```bash
cd $NOS_PTMP/$LOGNAME
sbatch --export=ALL,CYC=12,DCOMROOT=$B/dcom $HW/slurm/stofs_3d_atl_ufs_standalone/jnos_prep_00.sh
sbatch --export=ALL,CYC=12 $HW/slurm/stofs_3d_atl_ufs_standalone/jnos_nowcast_00.sh
sbatch --export=ALL,CYC=12 $HW/slurm/stofs_3d_atl_ufs_standalone/jnos_forecast_00.sh
sbatch --export=ALL,CYC=12 $HW/slurm/stofs_3d_atl_ufs_standalone/jnos_post_00.sh
# coupled: the same four cards under slurm/stofs_3d_atl_ufs/
```
Add `COMINrerun=$B/seeds/dyn_seed_<PDY-1>` to the prep `--export` to use a flat seed. Later cycles: set `PDY` for the new day, stage its inputs, and run the same four cards with no seed.

The cards check first and stop within seconds on: missing `PACKAGEROOT`; pinned `OFS/NET/RUN/PREFIXNOS`; `COMROOT` coming only from `COMROOT_SA`/`COMROOT_UFS`; inherited `COMOUT`, `DATA`, `COMIN*`, `USE_DATM`, `UFS_EXEC*` cleared; nos-utils not at the pinned commit; and in prep, missing Fortran tide_fac, dcom files or previous-cycle seed.

Resources (80 cores/node): standalone 62 nodes, coupled 63 nodes for nowcast and forecast; prep and post 1 node.

## 5. Checking a run

Logs (WCOSS2): `/lfs/h1/nos/ptmp/$LOGNAME/rpt/stofs_3d_atl_ufs/<card>_<stage>_00.<jobid>.out|.err`. Hercules: `$NOS_PTMP/$LOGNAME/rpt/stofs_3d_atl_ufs/`; a job with no log there stopped in a card check (see `<jobname>.<jobid>.out` where you submitted).
```bash
L=$(ls -t /lfs/h1/nos/ptmp/$LOGNAME/rpt/stofs_3d_atl_ufs/*standalone_prep_00.*.out | head -1)
grep -E "Running Fortran tide_fac|adj0=|1986300 sinks|Found ADT|STAGE_SUMMARY" $L
```
A healthy prep shows:
- `Running Fortran tide_fac` in both phases;
- `Applied SSH dynamic adjust ... adj1=<non-zero>`;
- `1348 sources, 1986300 sinks`;
- ADT found for 2 days;
- `STAGE_SUMMARY ... status=PASS`.

Always check `STAGE_SUMMARY ... status=PASS` for every stage. A failed stage now stops the PBS chain: the later jobs are cancelled. If any remain held, `qdel <jobid>` them (see `qstat -u $LOGNAME`). Fix the problem and re-launch with `STAGES=` set to the stages still needed.

Model progress: `grep "TIME STEP" <DATA>/outputs/mirror.out | tail -1` (576 steps = 24 h nowcast, dt 150 s).

Outputs in `COMOUT=<COMROOT>/nos/stofs_3d_atl_ufs.<PDY>/`:

| Path | Contents |
|---|---|
| `stofs_3d_atl_ufs.t12z.restart_outputs/` | nowcast `staout_1..8` (station water level, pressure, wind, T, S, u, v), `mirror.out` |
| `stofs_3d_atl_ufs.t12z.forecast_outputs/` | forecast station files |
| `stofs_3d_atl_ufs.t12z.<PDY>.rst.nowcast.nc` | restart for the next cycle |
| `staout_1` | nowcast + forecast joined, used by the next cycle's adjustment |
| `rerun/` | `avg_bias`, `param.nml`, ... |

Cleaning up: work directories (`/lfs/h1/nos/ptmp/$LOGNAME/work/...`, `$NOS_PTMP/.../work`) can be deleted once the job has finished, because the outputs are archived to COMOUT. Do not delete COMOUT of the previous day while you still plan to run the next cycle.

## 6. Timing

Operational v3.1 (one continuous run): prep 0:31, now_forecast 1:24, post1 0:22, post2 0:52.

nos-workflow on WCOSS2, day 1, PDY 20261003 (seconds):

| Stage | Standalone | Coupled |
|---|---|---|
| prep | not measured | 1711 |
| nowcast (24 h) | 2350 | 3316 |
| forecast (96 h) | 4825 | 5899 |
| post | 3485 | 7215 (coupled post limit raised to 4 h) |

Hercules, PDY 20261001: standalone prep 8 min, nowcast stage 25 min (SCHISM 16 min); coupled prep 24 min (DATM build), nowcast stage 28 min.

## 7. Comparing with operational

Reference data: the operational COMOUT (about 5 days) has `staout_1` and `rerun/`. The public bucket `noaa-nos-stofs3d-pds/STOFS-3D-Atl/stofs_3d_atl.<PDY>/` (kept indefinitely) has `rerun/`, `points.cwl.nc`, station profiles and 2D fields, but no `staout_1` or `avg_bias`.

Comparison scripts (ask the maintainer for the validation set): `compare_staout.py`, `plot_staout_compare.py`, `plot_ufs_compare.py` (operational vs standalone vs coupled), `plot_5day_compare.py` (joins nowcast and forecast, compares with operational and CO-OPS observations), `compare_sflux.py`, `plot_river_compare.py`, `make_case_bundle.sh`.

`staout` column = row order in `station.in` (166 stations). Five (Christiansted, Limetree Bay, Lameshur Bay, Esperanza, Culebra) lie outside the mesh and output 1e7. Exclude them from statistics.

Parity achieved, PDY 20261001, 161 stations in the mesh (median station max absolute difference from operational):

| Comparison | Nowcast | Forecast |
|---|---|---|
| Standalone | 0.09 mm | 0.96 mm (first output bit-identical at all 161 stations) |
| Coupled | 2.3 mm | 6.1 mm |
| Hercules vs WCOSS2 | 0.06 mm standalone, 0.10 mm coupled | |

## 8. Known limitations

- ecFlow cards are not done yet; use the launchers (WCOSS2) or the Slurm cards (Hercules).
- post2 products (GRIB2, SHEF) and the geopackage are not ported; no post product beyond stations and fields has been compared with operational.
- The annual temperature/salinity restart reset (operational does it on 5 April) is not implemented. It is required before 2027-04-05.
- The coupled variant shows a slow temperature/salinity drift relative to operational.
- Coupled post: a fix for the empty trailing OLDIO field stack is in progress.
- Bad-day handling follows operational for ATL: prep checks restart age and size and fails on missing HOTSTART, OBC_QC, NUDGING or OPS_OBC_INPUTS; the previous-cycle fallback reads `$COMOUT_PREV/rerun`. Cases operational handles differently may remain.
- The launcher does not wait for the previous day; submit the next day only after the forecast has passed.

## 9. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Prep fails on a missing river file | The three operational river files are not in `fix/stofs_3d_atl_ufs/`. Re-run `tools/fetch_stofs_3d_atl_fix.sh`. |
| Coupled run cannot find `ufs.configure` or `datm_in.template` | The fetch tool was not run from a clone that has `fix/secofs_ufs/`. Re-run it from the repo. |
| `Permission denied` running a launcher | Execute bit lost on the clone. Run `bash launch_<name>.sh <PDY> 12`. |
| Jobs run the wrong clone | `PKG`, `PACKAGEROOT` or `HOMEnos` set in your shell. Unset them or set them deliberately. |
| Seed files vanished from ptmp | ptmp purges by file age and `cp -p` keeps old timestamps. Copy without `-p`; keep seeds on noscrub. |
| Prep aborts: hotstart not NETCDF4_CLASSIC | Convert the seed with `nccopy -k 'netCDF-4 classic model'`. |
| `partition.prop` rank error before launch | The file must have 4912 ranks (the operational file). |
| Prep fails with "STOFS-3D-ATL needs the Fortran tide_fac" | Install `nos_ofs_create_tide_fac_schism` in `exec/`. |
| `adj0=0 adj1=0` | Previous-cycle `staout_1` / `avg_bias` not found (section 2). Check the log line "Dynamic adjust previous-cycle inputs". |
| Later jobs still held after a failure | Normally PBS cancels them. `qdel` any that remain, fix, re-launch with `STAGES=`. |
| A job exited 0 but the stage failed | Always check `STAGE_SUMMARY ... status=PASS`. |
| Hercules job ran the SECOFS package | `PACKAGEROOT` not set; the ATL cards refuse to run without it. |
| SECOFS job on Hercules read ATL inputs | `atl_env.sh` was sourced in that shell. Use a fresh shell for SECOFS. |
| Slow or hanging start at high rank counts | ParMETIS. All ATL builds use `NO_PARMETIS` with the staged `partition.prop`. |
