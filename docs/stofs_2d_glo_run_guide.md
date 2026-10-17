# Running STOFS-2D-Global with nos-workflow on WCOSS2 and Hercules

Applies to nos-workflow `develop` as of 2026-10-15. Update this guide in the same PR as any change to the 2D-Global cards, launchers, build/fetch/staging tools or Jenkins scripts.

## 1. What you are running

STOFS-2D-Global is ADCIRC v56.1 (`padcirc`, `adcprep`) on the 12.8 M node global mesh: 4064 compute ranks, time step 6 s, cycles at 00, 06, 12 and 18z. One yaml (`parm/systems/stofs_2d_glo.yaml`) and one set of cards serve two modes; `ADCIRC_MODE` picks the mode at submit time.

| | single (default) | ops (`ADCIRC_MODE=ops`) |
|---|---|---|
| Design | Zach Cobell's: a 6 h nowcast from the previous nowcast restart, then one 180 h forecast | The operational stofs.v3.1.5 layout inside the nos-workflow structure |
| Jobs per cycle | 3 (prep, nowcast, forecast) | 4 (prep, nowcast, forecast, post); the tide and surf streams run one after the other inside a job |
| Streams | one run, tide + surge | `tide` (NWS 0, chain file `.hotstart`) and `surf` (NWS 14014, chain file `.restart`), each an `ncst` and one 180 h `fcst` |
| Atmosphere | GFS 0.25 degree `pgrb2` files from `COMINgfs`, converted to OWI NetCDF with wgrib2, xarray, cfgrib and eccodes | GFS `sfcf` netCDF files from `COMINgfs`, built as ops builds them |
| Tides | 15 constituents from nos-utils (Python) | 8 constituents (K1 O1 P1 Q1 M2 S2 N2 K2); nodal factors from the Fortran `stofs_2d_glo_tide_fac` |
| fort.15 | written by nos-workflow | ops templates `stofs_2d_glo_tide.15` and `stofs_2d_glo_surf.15` |
| Fix files | `grid`, `attr` | everything from `tools/fetch_stofs_2d_glo_fix.sh`, with `WITH_BODY=1` (fort.24) |
| Post | none | anomaly -> bias -> ncdiff -> GRIB2/SHEF -> ncrcat, in the post job |
| Launcher | WCOSS2 only | WCOSS2 (all jobs) and Hercules (no anomaly, bias or GRIB2) |

Run identity: `NET=nos`, `RUN=OFS=PREFIXNOS=stofs_2d_glo`, pinned by the cards. COMOUT is `${COMROOT}/nos/stofs_2d_glo.<PDY>`.

**Ops mode in detail.**
- **Jobs and steps:** a job runs the steps of its `ADCIRC_SEGMENT` and `ADCIRC_STREAM` lists one after the other (`ncst` and `fcst` once per stream) and stops at the first failure. A list is space separated (commas are accepted), in the order of the steps below and without repeats; anything else stops the job before its first step. The log and the `STAGE_SUMMARY` line name each step and its seconds (`steps=tide_ncst:671,surf_ncst:791`), and a failure names its step (`reason=surf_fcst: ...`). The steps are: prep `adcprep` (cold start only), `gfs_ncst`, `gfs_fcst`; nowcast `spinup` (cold start only), `tide_ncst`, `surf_ncst`; forecast `tide_fcst`, `surf_fcst`; post `anomaly`, `bias`, `ncdiff`, `grib2`, `ncrcat`. A single value in either variable still runs one step, which is how a step is redone (section 2.5). The tide stream always runs before the surf stream. A cold start is only ever the `adcprep` and `spinup` segment names: the ops `run.ver` exports `COLDSTART=YES` into every job, so the jobs never read that variable.
- **Forecast:** operational runs the forecast as fcst1 + fcst2. nos-workflow runs one 180 h run with hourly forcing, so the fort.15 differs from ops only in the run length, and the forcing is interpolated to hourly after f120 (below).
- **Surface forcing:** the `gfs_ncst` and `gfs_fcst` steps of the prep job write `<CC>/rerun/stofs_2d_glo_{ncst,fcst}.{221,222,225}.nc` (pressure, 10 m wind, ice) from the GFS `sfcf` files. After f120 GFS is 3-hourly, so the hourly records of hours 121-179 that fall between GFS files are linearly interpolated, which is what ADCIRC does between the ops fcst2 snapshots. On a cold start prep runs before the spin-up, so the `ncst` window starts at the restart the spin-up will publish (cycle minus 6 h, 7 records to the cycle), which this cycle's `nod_equi` confirms; an older chain file does not move it. On 2026-10-12 00z the forcing was bitwise identical to ops: ncst 7/7 records, fcst1 121/121, fcst2 21/21.
- **Tide factors:** `nod_equi` comes from the ops Fortran `stofs_2d_glo_tide_fac` only (365 days from the spin-up start). There is no Python fallback, because a float32/float64 difference would freeze different factors into every segment.
- **Post:** the anomaly, bias and GRIB2 steps run the unchanged ops ex-scripts from the ops package; ncdiff and ncrcat are the same NCO calls as ops, run by nos-workflow.

**Products (ops mode).** Files are `<COMOUT>/stofs_2d_glo.t<HH>z.<name>`:

| Product | Name | Made by |
|---|---|---|
| htp (tide only) | `points.htp.nc`, `fields.htp.nc` | tide_fcst |
| cwl.noanomaly (tide + surge, uncorrected) | `points.cwl.noanomaly.nc`, `fields.cwl.noanomaly.nc`, `fields.cwl.maxele.noanomaly.nc` | surf_fcst |
| velocity and maxima | `points.cwl.vel.nc`, `fields.cwl.vel.nc`, `fields.cwl.maxvel.nc`, `fields.cwl.maxwvel.nc` | surf_fcst |
| cwl (anomaly and bias corrected) | `points.cwl.nc` (anomaly), `fields.cwl.nc` and `fields.cwl.maxele.nc` (bias) | anomaly, bias |
| swl (surge: cwl minus htp) | `points.swl.nc`, `fields.swl.nc` | ncdiff |
| forcing | `pressfc.nc`, `uvgrd10m.nc`, `icec.nc` | ncrcat |
| GRIB2 and SHEF | `<region>.f000.grib2` ... `<region>.f180.grib2` for conus.east, conus.west, puertori, alaska, hawaii, guam, northpacific; SHEF files | grib2 |
| anomaly history | `database.tar.gz` (one per day directory) | anomaly |

The point files hold 1687 stations. The `surf_fcst` step first publishes the uncorrected `points.cwl.nc` and `fields.cwl.nc`; the anomaly and bias steps replace them with the corrected files before ncdiff runs.

**Products (single mode).** One run directory per phase, `stofs_2d_glo.<PDY>/stofs_2d_glo.t<HH>z.nowcast` and `.forecast`, with `fort.61.nc` (stations), `fort.62.nc`, `fort.63.nc` (fields), `fort.64.nc`, the restart `fort.67.nc` / `fort.68.nc`, `maxele.63.nc`, `maxvel.63.nc`, `maxwvel.63.nc`, `fort.15`, `timing.json`, `adcirc.out` and `adcirc.err`.

## 2. WCOSS2 (Cactus / Dogwood, PBS)

### 2.1 One-time setup

Clone anywhere, with any directory name:
```bash
cd /lfs/h1/nos/estofs/noscrub/$LOGNAME/packages          # or any directory you own
git clone https://github.com/mansurjisan/nos-workflow
cd nos-workflow && git checkout develop && git pull --ff-only
git submodule update --init ush/python/nos-utils
```
No card edits are needed. The cards default `PACKAGEROOT` to `/lfs/h1/nos/estofs/noscrub/$LOGNAME/packages`, and the launcher works out its own clone location and passes `PACKAGEROOT` and `HOMEnos` (the clone path) to every job. If you run a card directly with `qsub`, add `-v PACKAGEROOT=<parent dir>,HOMEnos=<clone path>`.

If `~/.bashrc` sets `PACKAGEROOT` or `HOMEnos`, write them as defaults (`PACKAGEROOT=${PACKAGEROOT:-/path}`, `HOMEnos=${HOMEnos:-/path}`). PBS jobs source `~/.bashrc` after the `qsub -v` values are set, so a plain assignment there overrides the clone the launcher passes (section 9).

Updating an existing clone: `git status --short | grep -v '^??'` should print nothing. Older clones may carry edits to the cards; the launcher passes the clone path now, so discard them (`git checkout -- pbs/stofs_2d_glo`), then `git pull --ff-only` and `git submodule update ush/python/nos-utils`. Update only while no job from the clone is queued or running; a queued job reads its card when it starts.

The cards submit with `#PBS -A ESTOFS-DEV -q dev`. Without that project, ask for access or change `#PBS -A` in your clone's cards (that is the one card edit to keep).

### 2.2 Fix files

From the clone root:
```bash
WITH_BODY=1 ./tools/fetch_stofs_2d_glo_fix.sh      # about 7.2 GB; default destination fix/stofs_2d_glo
```
- Source: on WCOSS2 it copies from `/lfs/h1/ops/prod/packages/stofs.v3.1.5/fix/stofs_2d_glo`; elsewhere it downloads from the NCO mirror. A file whose size already matches is skipped, so re-running resumes.
- Without `WITH_BODY=1` it stages about 3.3 GB: `stofs_2d_glo_grid` (1.7 GB), `stofs_2d_glo_attr` (1.5 GB), `rotm`, `elev_stat`, `met`, `station.ctl`, `msl2mllw`, `surf.15`, `tide.15`. That is enough for single mode. Ops mode also needs `stofs_2d_glo_body` (3.9 GB, the fort.24 self-attraction/loading file), so use `WITH_BODY=1`.
- It ends with `grid:  <nodes> nodes, <elements> elements` and `OK`. A node count outside 12.7-12.9 M prints a WARNING and exits 2.

### 2.3 Executables

Ops mode needs the Fortran tide_fac in `exec/` (single mode does not):
```bash
mkdir -p exec
cp /lfs/h1/ops/prod/packages/stofs.v3.1.5/exec/stofs_2d_glo/stofs_2d_glo_tide_fac exec/
ls exec | grep -xE 'padcirc|adcprep' && echo "WARNING: exec/ has its own padcirc/adcprep"     # expect no output
```
`padcirc` and `adcprep` come from the ops `adcirc/<adcirc_ver>` module (version from the ops `run.ver`). They are searched in this order: `ADCIRC_EXEC_DIR`, then `$EXECnos` (the clone's `exec/`), then `PATH`. A `padcirc` or `adcprep` left in `exec/` would silently replace the ops executables, which is why the check above matters.

If there is no ops adcirc module, point the jobs at a build directory that holds both executables (the launcher forwards `ADCIRC_EXEC_DIR`, and `ADCIRC_MODULE_PATH` if the modulefile is not on your default module path):
```bash
export ADCIRC_EXEC_DIR=<dir with padcirc and adcprep>
ldd $ADCIRC_EXEC_DIR/padcirc | grep -iE "hdf5|netcdf|not found"      # no "not found" under the ops module stack
```

### 2.4 Environment check

The cards load the ops module stack from `STOFS_RUNVER` (default `/lfs/h1/ops/prod/packages/stofs.v3.1.5/versions/run.ver`), but keep the nos-workflow python (3.8.6): the ops run.ver sets python 3.12, which has no yaml or netCDF4. The python's netCDF4 bundles its own HDF5, so check that combination with a real netCDF4 write. Run from the clone root:
```bash
P=$PWD
( . $P/versions/run.ver; _py=$python_ver; . /lfs/h1/ops/prod/packages/stofs.v3.1.5/versions/run.ver; python_ver=$_py
  module purge; module reset
  module load PrgEnv-intel/$PrgEnv_intel_ver craype/$craype_ver intel/$intel_ver cray-mpich/$cray_mpich_ver cray-pals/$cray_pals_ver hdf5/$hdf5_ver netcdf/$netcdf_ver
  module load adcirc/$adcirc_ver || echo "NO adcirc/$adcirc_ver module"; module load python/$python_ver
  echo "python $python_ver; padcirc: $(command -v padcirc)  adcprep: $(command -v adcprep)"
  cd $P/ush/python && PYTHONPATH=$PWD:$PWD/nos-utils:$PYTHONPATH python3 -c "import numpy, netCDF4, cftime, yaml, nos_workflow, nos_utils; netCDF4.Dataset('/tmp/$LOGNAME.t.nc','w').close(); print('imports + netCDF4 write ok; cftime', cftime.__version__)"
  ldd $(python3 -c "import netCDF4._netCDF4 as m; print(m.__file__)") | grep -iE "hdf5|netcdf" )
# the post job (anomaly, bias, ncdiff, grib2, ncrcat) runs the nos-workflow runner on the ops ve/stofs python; that path imports only the standard library, yaml and numpy
( . /lfs/h1/ops/prod/packages/stofs.v3.1.5/versions/run.ver; module load ve/stofs/$ve_stofs
  cd $P/ush/python && PYTHONPATH=$PWD:$PWD/nos-utils:$PYTHONPATH python3 -c "import yaml, numpy, nos_workflow; print('ve/stofs ok')" )
ls /lfs/h1/ops/prod/dcom/$(date -u +%Y%m%d)/coops_waterlvlobs | head -3     # CO-OPS observations for the anomaly step
```
Expected: `imports + netCDF4 write ok` with a single HDF5 version in the `ldd` output, `ve/stofs ok`, and a few CO-OPS files. If any of these fail, stop and send the output.

The ops-mode prep and post jobs ask for prepost nodes (`prepost=true`), as ops does. Check that the dev queue accepts both shapes; each line should print `accepted <id>` (the test jobs are deleted at once):
```bash
for sel in "1:ncpus=1:prepost=true:mem=400gb" "8:ncpus=32:prepost=true:mem=800gb"; do
  id=$(echo true | qsub -A ESTOFS-DEV -q dev -N prepost_check -l walltime=0:02:00 -l select=$sel -l place=vscatter:exclhost -o /dev/null -e /dev/null) && echo "accepted $id" && qdel $id; done
```

### 2.5 Run

Run the launcher from your clone. It passes `PDY`, `CYC`, `PACKAGEROOT` and `HOMEnos`, and forwards these when set: `COMROOT_2DGLO`, `ADCIRC_EXEC_DIR`, `ADCIRC_MODULE_PATH`, `STOFS_RUNVER`, `DCOMROOT`, `ATMOSPHERIC_FORCING` (false = tide only), `COLDSTART_SPINUP_DAYS`, `NOWCAST_HOURS`. `PKG` overrides the clone location. The cycle argument defaults to 12.

**Single mode** (prep -> nowcast -> forecast, each gated on `afterok` of the previous):
```bash
cd <your nos-workflow>/pbs/stofs_2d_glo
./launch_stofs_2d_glo.sh 20261013 12
STAGES="nowcast forecast" ./launch_stofs_2d_glo.sh 20261013 12       # re-run only some stages
```
- The first cycle cold-starts by itself when no previous nowcast restart exists: a tide-only spin-up of 18 days (`COLDSTART_SPINUP_DAYS`) inside the nowcast, then GFS forcing for the forecast. The first prep also runs the full serial `adcprep`; later cycles reuse the decomposition (section 4).
- The nowcast interval is 6 h (`NOWCAST_HOURS`). For a once-a-day 12z run set `NOWCAST_HOURS=24`, otherwise every day cold-starts.
- Resources: prep 1 node (8 cores, 100 GB, 6 h limit); nowcast 32 nodes x 128 (6 h); forecast 32 nodes x 128 (3 h). Single mode needs `COMINgfs` (default `/lfs/h1/ops/prod/com/gfs/v16.3`) to exist.
- `KEEPDATA` is not forwarded in single mode, so the cards' default `KEEPDATA=YES` applies: work directories stay until you delete them.

**Ops mode, first cycle** (cold start). Pick a cycle old enough that its GFS `sfcf000` to `sfcf180` are in `COMINgfs` and, for the comparison, that ops has finished its post:
```bash
export COMROOT_2DGLO=/lfs/h1/nos/ptmp/$LOGNAME/com_2dglo_ops      # optional; default is the shared com (section 4)
cd <your nos-workflow>/pbs/stofs_2d_glo
COLDSTART=YES ADCIRC_MODE=ops ./launch_stofs_2d_glo.sh 20261012 00 | tee $HOME/2dglo_2026101200.jobs
```
**Ops mode, later cycles** (every 6 h; submit cycle N+1 after cycle N's nowcast job has finished, because its `tide_ncst` and `surf_ncst` steps publish the chain files the next cycle starts from; the launcher does not wait for the previous cycle):
```bash
ADCIRC_MODE=ops ./launch_stofs_2d_glo.sh 20261012 06
KEEPDATA=YES ADCIRC_MODE=ops ./launch_stofs_2d_glo.sh 20261012 12      # keep every job's work directory (about 150 GB a cycle)
```
In ops mode `KEEPDATA` defaults to `NO` and is forwarded, and the launcher prints one line per job. `COLDSTART=YES` (a launcher-side switch, not forwarded) adds `adcprep` to the prep job and `spinup` to the nowcast job. `STAGES` is a subset of `"prep nowcast forecast post"` in that order (default all); only the submitted jobs are linked with `afterok`. `STREAMS` (default `"tide surf"`; only `tide`, `surf` or both, in that order) is passed as `ADCIRC_STREAM`. The launcher prints the stages it submits and a `NOTE` when they are a subset, so a `STAGES` left in your shell from single mode is visible. `qsub -v` splits at commas, so the list values the jobs receive are space separated (`ADCIRC_SEGMENT=ncst fcst`); typed by hand, the whole `-v` value goes in one pair of quotes (the forms are in the comment block of `jnos_nowcast_00.pbs`); without them `qsub` refuses the stray words.

| Job | Resources | Walltime | Steps | Waits for |
|---|---|---|---|---|
| prep | 1 core, prepost, 400 GB | 0:50 (cold start 3:50) | [`adcprep`,] `gfs_ncst`, `gfs_fcst` | |
| nowcast | 32 nodes x 128 (surf: 4064 + 5 writers) | 0:50 (cold start 1:50) | [`spinup`,] `tide_ncst`, `surf_ncst` | prep |
| forecast | 32 nodes x 128 (surf: 4064 + 5 writers) | 2:00 | `tide_fcst`, `surf_fcst` | nowcast |
| post | 8 nodes x 32 cores, prepost, 800 GB, exclusive | 3:10 | `anomaly`, `bias`, `ncdiff`, `grib2`, `ncrcat` | forecast |

The walltimes are the sums of the former per-job values, which were the ops ecf values except `adcprep` 3:00 (full adcprep with fort.24, plus the cache tar), `ncst` 0:25 (the first WCOSS2 cycle took 750 and 821 s of the ecf 0:15) and `ncrcat` 0:25: prep 0:10 + 0:40 (+ 3:00); nowcast 2 x 0:25 (+ 1:00 spin-up); forecast 0:55 + 1:05; post 0:15 + 2:00 + 0:10 + 0:20 + 0:25. The post job takes the bias shape (8 x 32 cores, exclusive), which also covers the 7 cores of `grib2` and the one-core steps. That is 4 jobs, with or without a cold start. If `qsub` rejects a job, the launcher stops partway: `qdel` the ids it printed and fix the message.

**Redoing a step.** There are no done-markers. A failed job names its failing step in the `STAGE_SUMMARY` reason, and the steps before it passed. Resubmit the failed job with a narrower list and its downstream jobs behind it:
- After a failed nowcast step (`tide_ncst` or `surf_ncst`), one launch redoes it and everything behind it:
```bash
STAGES="nowcast forecast post" ADCIRC_MODE=ops ./launch_stofs_2d_glo.sh 20261012 12
```
  Re-running `tide_ncst` after it passed is safe: an `ncst` step starts from the same input chain file and publishes the same result, and it costs about 13 min. To redo only the surf stream use two launches, `STAGES=nowcast STREAMS=surf` first and `STAGES="forecast post"` only after that job has finished (the launcher does not wait for it).
- A forecast step cannot run twice (`advanced past this fcst`), so after a failed `surf_fcst` redo only that stream:
```bash
STAGES="forecast post" STREAMS=surf ADCIRC_MODE=ops ./launch_stofs_2d_glo.sh 20261012 12
```
- A step that fails with `padcirc dropped an output record` (a time series with a missing record, checked before anything is published) is redone like any failed step above: `STAGES="nowcast forecast post"` after `ncst` (both streams; re-running `tide_ncst` is safe), `STAGES="forecast post"` after a `tide_fcst` failure (both streams) and `STAGES="forecast post" STREAMS=surf` after a `surf_fcst` failure. The nowcast and forecast jobs stop at the first failed step, so redo the failed stream and every stream after it.
- The GFS steps skip forcing that already exists, so a failed prep is resubmitted whole. Do not add `COLDSTART=YES` to a resubmission unless the cold start has to be redone, as below.
- Cold start, WCOSS2. `adcprep` runs only in a prep job and `spinup` only in a nowcast job, and `COLDSTART=YES` adds each to its job.
  - The spin-up failed (adcprep passed): `COLDSTART=YES STAGES="nowcast forecast post" ADCIRC_MODE=ops ./launch_stofs_2d_glo.sh <PDY> <CYC>`. The nowcast gets `spinup ncst`; no prep job is submitted, so adcprep does not run again.
  - The cold prep failed after adcprep passed (for example in `gfs_fcst`): `STAGES=prep ADCIRC_MODE=ops ./launch_stofs_2d_glo.sh <PDY> <CYC>` (without `COLDSTART`, so it runs only the GFS steps), and once that job has finished `COLDSTART=YES STAGES="nowcast forecast post" ADCIRC_MODE=ops ./launch_stofs_2d_glo.sh <PDY> <CYC>`. The cold-start `ncst` window needs this cycle's `nod_equi`, which adcprep already wrote.
  - `adcprep` itself failed: repeat the whole cold launch.
- A different list, or a single step, is a `qsub` of the card with `ADCIRC_SEGMENT` and `ADCIRC_STREAM` set (the comment block at the top of `pbs/stofs_2d_glo/jnos_nowcast_00.pbs` has the forms).

Trade-offs of the four-job layout: the post job holds 8 exclusive prepost nodes for its whole 3:10 walltime (about twice the prepost node-hours of the former separate post jobs), the streams run one after the other, so a cycle's latency is the sum of its steps, and on Hercules the tide stream runs on 51 of the 52 nodes (`srun -N 51`, the same layout as the former separate tide job), so its results are reproducible with the separate-job layout.

### 2.6 Starting from the ops state

A cycle started from the operational state is the close comparison with ops (section 7). Ops keeps each cycle's chain files in its COM (`stofs_2d_glo.t<HH>z.hotstart` for tide, `.restart` for surf), its nodal factors in `nwges/stofs_2d_glo_nod_equi`, and the anomaly history in `database.tar.gz`. Copy them into a fresh COMROOT and the next cycle starts where ops was. Example: start 20261012 06z from the ops 00z state:
```bash
OPS=/lfs/h1/ops/prod/com/stofs/v3.1                     # operational COM
PDY=20261012; CYC=06; PREV=20261012; PCYC=00            # PREV/PCYC: the cycle 6 h before PDY/CYC
ls -l $OPS/nwges/stofs_2d_glo_nod_equi $OPS/stofs_2d_glo.$PREV/stofs_2d_glo.t${PCYC}z.{hotstart,restart}
export COMROOT_2DGLO=/lfs/h1/nos/ptmp/$LOGNAME/com_2dglo_opsstate
G=$COMROOT_2DGLO/nos/stofs_2d_glo; D=$COMROOT_2DGLO/nos/stofs_2d_glo.$PREV
mkdir -p $G $D
cp <COMROOT of an earlier ops-mode run>/nos/stofs_2d_glo/stofs_2d_glo_4064.tar{,.json} $G/     # reuse the decomposition
cp $OPS/nwges/stofs_2d_glo_nod_equi $G/                                                       # ops nodal factors
cp $OPS/stofs_2d_glo.$PREV/stofs_2d_glo.t${PCYC}z.{hotstart,restart} $D/                      # ops chain files
cp $OPS/stofs_2d_glo.$PREV/database.tar.gz $D/ || echo "no ops database.tar.gz"                # seeds the anomaly history
cd <your nos-workflow>/pbs/stofs_2d_glo && ADCIRC_MODE=ops ./launch_stofs_2d_glo.sh $PDY $CYC
```
- If the first `ls` shows other names or no files, stop and check the ops COM before copying.
- The decomposition does not depend on the start time, so reuse the tar of an earlier ops-mode run (it is keyed on the rank count and on the mesh and attribute file sizes). Without it, the first `ncst` step of the nowcast job runs the full adcprep inside the job's 0:50 walltime. A tar made in single mode has no fort.24 and is refused (section 9).
- This is a 4-job cycle, no cold start.
- Put `database.tar.gz` in the day directory of the cycle you run (06, 12, 18z) or in the previous day's directory (00z, and a once-a-day 12z run falls back to it too). Without it the anomaly history starts empty, so `points.cwl.nc` and `points.swl.nc` differ from ops at the anomaly-corrected stations. Ops overwrites its tar every cycle, so the copy may be from a later cycle than the one you start.
- The ops restart files are not public, so this works on WCOSS2 only.

### 2.7 Checking a run

Logs: `/lfs/h1/nos/ptmp/$LOGNAME/rpt/stofs_2d_glo/stofs_2d_glo_{prep,nowcast,forecast}_00.<jobid>.out|.err`. Every stage ends with a summary line, and the card exits 1 unless it says `status=PASS`, so a failed stage stops the PBS chain (the later jobs stay held or are cancelled by PBS; `qdel` any that remain).
```bash
R=/lfs/h1/nos/ptmp/$LOGNAME/rpt/stofs_2d_glo
grep -H -o 'STAGE_SUMMARY.*' $(ls -t $R/*.out | head -4)        # newest 4 logs: one launch
qstat -u $LOGNAME
```
Model progress: each ADCIRC job writes `adcirc.out` in `<DATA>/<stream>_<segment>/` (for example `surf_fcst`), where `DATA` is `/lfs/h1/nos/ptmp/$LOGNAME/work/stofs_2d_glo/<job>.<PBS jobid>`. If padcirc fails, the job log shows the last 30 lines of `adcirc.out` and `adcirc.err`.

Outputs of a cycle (`C=$COMROOT_2DGLO/nos/stofs_2d_glo.$PDY`):
```bash
ls -l $C/$CYC/rerun/                                              # forcing, tide and surf .61/.63, max*, hottime/retime
ls -lh $C | grep -E "t${CYC}z\.(points|fields)|pressfc|uvgrd10m|icec|database"
ls $C | grep -c grib2
du -sh $COMROOT_2DGLO
```

### 2.8 Comparing with ops

Reference data: the operational COM `$OPS/stofs_2d_glo.<PDY>/` (`OPS=/lfs/h1/ops/prod/com/stofs/v3.1`) holds `stofs_2d_glo.t<CC>z.points.{htp,cwl.noanomaly,cwl,swl}.nc` and `<CC>/rerun/stofs_2d_glo_{ncst,fcst1,fcst2}.{221,222,225}.nc`. The public bucket `noaa-gestofs-pds` (`stofs_2d_glo.<PDY>/`) holds the same points files and the forcing.

Station comparison (the cmp_points comparison), run from the clone with python 3.8.6 and netCDF4:
```bash
python3 .cicd/scripts/compare_2dglo.py ops --out $COMROOT_2DGLO --ops-dir $OPS/stofs_2d_glo.$PDY --pdy $PDY --cyc $CYC
```
For `points.htp`, `points.cwl.noanomaly` and `points.swl` it takes the common times, computes the maximum absolute water-level difference per station, skips stations where ops itself exceeds 20 m, and prints the median, the counts within 1 mm, 1 cm and over 10 cm, and the five worst stations. It only reports: a median above `--warn-mm` (default 500) prints WARN and still exits 0.

The 2D fields and the met products are compared the same way (reported only; a missing or unreadable file exits 1). Download the ops files of the cycle from `https://noaa-gestofs-pds.s3.amazonaws.com/stofs_2d_glo.$PDY/` with `curl -fLO` (the field files are 10 to 20 GB each), then on Hercules (`OPS_S3` is the download directory; run it on a compute node with `srun`, or use `--chunk 2` on a login node, since a chunk of 8 holds about 2.5 GB):
```bash
OPS_S3=$NOS_PTMP/$LOGNAME/ops_s3/$PDY$CYC/fields   # download directory
python3 .cicd/scripts/compare_2dglo.py fields --ours $COMROOT_2DGLO/nos/stofs_2d_glo.$PDY/stofs_2d_glo.t${CYC}z.fields.cwl.nc --ops $OPS_S3/stofs_2d_glo.t${CYC}z.fields.cwl.nc --chunk 8 --map cwl.png
python3 .cicd/scripts/compare_2dglo.py met --ours-dir $COMROOT_2DGLO/nos/stofs_2d_glo.$PDY --ops-dir $OPS_S3 --cyc $CYC
```
`fields` prints the per-node max |d| statistics, the ten worst nodes and the wet/dry mismatches (maxele files compare `zeta_max` directly); `met` checks the 149 records and bitwise equality of `pressfc`, `uvgrd10m` and `icec`.

Forcing comparison (a maintainer helper, not in the repo; ask for it): compare the staged `rerun/` files with the ops files record by record. Our ncst records equal ops ncst; our fcst records 0-120 equal ops fcst1; our fcst records 120, 123, ..., 180 equal ops fcst2 records 0-20; the other hours after 120 are interpolated and not compared. Reading the 80 GB takes 10-20 min.

## 3. Hercules (RDHPCS, Slurm)

Hercules runs ops mode (the Slurm launcher submits no single-mode chain), as a cold start followed by 6-hourly cycles. Differences from WCOSS2:
- **No GFS build.** GFS `sfcf` netCDF files are not public past f012, so the surf forcing is taken from the operational files on the public S3 bucket (`noaa-gestofs-pds`) and staged into `rerun/` by a tool. The prep job's `gfs_ncst` and `gfs_fcst` steps find the staged files and skip.
- **No anomaly, bias or GRIB2/SHEF steps.** They run the unchanged ops ex-scripts and need the ops package, `mpirun`, `cfp` and `tocgrib2`. The post job is `ncdiff` and `ncrcat`.
- **ADCIRC and tide_fac are built here** from the public NCO source; there is no adcirc module.
- **Compute nodes have no internet.** Every download (source, fix files, forcing) runs on a login node.
- **Cold start only.** The ops restart files and `nod_equi` are not public, so a start from the ops state is WCOSS2 only.

### 3.1 One-time setup

The clone must be named `nos-workflow` (the cards run `$PACKAGEROOT/nos-workflow`); `PACKAGEROOT` is its parent. The cards, launcher and tools default `NOS_PTMP` to the maintainer's ptmp (`/work2/noaa/nos-surge/mjisan/nos-run/ptmp`), so export your own before anything else. Source nothing from another system's environment file (for example the ATL `atl_env.sh`) in the shell you use for 2D-Global.
```bash
export PK=/work2/noaa/nos-surge/$LOGNAME/packages_2dglo          # any directory you own
export NOS_PTMP=/work2/noaa/nos-surge/$LOGNAME/nos-run/ptmp     # your own ptmp (example path)
mkdir -p $PK && cd $PK
git clone https://github.com/mansurjisan/nos-workflow nos-workflow
cd nos-workflow && git checkout develop && git pull --ff-only
git submodule update --init ush/python/nos-utils
mkdir -p exec
WITH_BODY=1 ./tools/fetch_stofs_2d_glo_fix.sh 2>&1 | tail -15     # NCO mirror, about 7.2 GB, resumable; run in tmux on a login node
```
The cards load module `nos_hercules.intel` (spack-stack, oneAPI) and activate the python venv `$NOS_VENV` (default `$VENV_PATH`, else `~/nos-venv`), which must provide numpy, netCDF4, yaml, scipy, pandas and xarray. The Slurm cards require `PACKAGEROOT` and stop within seconds without it (the launcher sets it).

Executables (all builds use the cards' module set; run `download` on a login node, the compile can go on a compute node):
```bash
tools/build_stofs_2d_glo_adcirc_hercules.sh download     # login node: ADCIRC v56.1.0 source and the ops flags.make
srun -A nos-surge -p hercules --qos=batch -N 1 -n 16 -t 1:00:00 --pty bash -l
tools/build_stofs_2d_glo_adcirc_hercules.sh build        # on the compute node; verifies version, hash, flags and libraries
exit
tools/build_stofs_2d_glo_tide_fac_hercules.sh            # download + build + smoke test; installs <clone>/exec/stofs_2d_glo_tide_fac
```
- `tools/build_stofs_2d_glo_adcirc_hercules.sh [download|build|all]`: the default `all` downloads and builds on the login node (`make -j 4`). `build` and `all` need an unlimited stack (`ulimit -s unlimited`); where the shell cannot raise it, run `build` under `srun`. `padcirc` and `adcprep` are installed into `ADCIRC_EXEC_DIR` (default `<parent of the clone>/adcirc_v56.1.0_exec`, which is also the launcher's default). `SRC` (source, default `<parent>/adcirc_v56.1.0_src`) must not sit inside a git checkout. The script checks that `padcirc -v` prints `v56.1.0` and `padcirc --hash` prints `6e667fc9dcc759116f0620f4d9ac76cfd1361fbd`.
- `tools/build_stofs_2d_glo_tide_fac_hercules.sh [download|build|all]`: source from the NCO mirror, built with `ifort -O2 -fp-model strict` (the ops flags). The smoke run must write 16 lines with the constituents in the order K1 O1 P1 Q1 M2 S2 N2 K2. An inherited `EXECnos` from another shell is ignored with a warning (`TIDE_FAC_EXEC_DIR` overrides the install directory).

### 3.2 Stage the forcing

Run on a login node, in `tmux`; it takes 45-90 min and resumes:
```bash
tools/hercules_2d_glo_stage_forcing.sh --rm-raw 20261012 00
```
- It downloads the nine ops rerun files (`stofs_2d_glo_{ncst,fcst1,fcst2}.{221,222,225}.nc`, about 39 GB) from the S3 bucket, writes the six files nos-workflow reads (ncst 7 records, fcst 181 hourly records, about 50 GB) to `$COMROOT_2DGLO/nos/stofs_2d_glo.<PDY>/<CYC>/rerun`, and checks the record counts. `--rm-raw` deletes the raw downloads afterwards; the reference files stay.
- It also downloads the ops station files `stofs_2d_glo.t<CYC>z.points.{htp,cwl.noanomaly,swl}.nc` to `$NOS_PTMP/$LOGNAME/ops_s3/<PDY><CYC>/products` for the comparison. Exit 3 means the forcing is staged but one of these could not be downloaded.
- A re-run skips what exists (`STAGE_FORCE=1` redoes both steps). `STAGE_SRUN="srun -A nos-surge -p hercules --qos=batch -N 1 -n 1 --mem=16G -t 2:00:00"` moves the 8 min staging step to a compute node. `DL_JOBS` sets the parallel downloads (default 4).
- Stage a cycle only after ops has published it. Do this for every cycle you run.

Hercules builds its own forcing (own-forcing path): download only the four needed messages (`PRES:surface`, `UGRD:10 m above ground`, `VGRD:10 m above ground`, `ICEC:surface`) of the public GFS flux files, then let the prep job build the rerun files:
```bash
tools/hercules_2d_glo_stage_forcing.sh --source gfs 20261012 00                       # login node, tmux; about 2-3 GB a cycle
SUBMIT_GFS=1 COLD=0 slurm/stofs_2d_glo/launch_stofs_2d_glo.sh 20261012 00             # prep builds the forcing, then the chain runs
```
- `--source gfs` fetches `gfs.t<CYC>z.sfluxgrbfFFF.grib2` of the bucket `noaa-gfs-bdp-pds` by byte range (about 15 MB an hour instead of 310 MB) into `${COMROOT_STAGED:-$NOS_PTMP/$LOGNAME/comin_2dglo}/gfs/gfs.<PDY>/<CYC>/atmos`, the tree the cards read as `COMINgfs`. It checks four messages per file, skips complete files and retries failed ones. It does not build the rerun files and it still downloads the ops reference station files.
- `SUBMIT_GFS=1` sets `ADCIRC_GFS_SOURCE=sflux` for the jobs (sfcf past f012 is not public); the preflight lists the GFS files missing for the stages you submit and names this command.
- This forcing is not bitwise equal to ops: the GRIB2 packing differs from the netCDF sfcf the ops builder reads. Measured against the ops ncst for 20261012 12z: winds agree within 0.005 m/s (up to 0.05 m/s in a few coarsely packed analysis-hour files), `icec` within 5e-4, surface pressure within 0.7 Pa mean over the ocean (up to about 270 Pa near steep terrain), and the file structure equals ops apart from the NCO history. The ops-copy path above stays the parity option.
- The ncst window is 7 hourly records (cycle - 6 h .. cycle); `COLD=0` already requires the cycle - 6 h chain. After a gap, when the chain start is older, stage and launch with `NCST_RECORDS=<hours since the chain start + 1>`. The preflight checks the GFS files only when `prep` is in `STAGES`.

### 3.3 Run

From a login node shell (the launcher refuses inside an `srun`/`salloc` allocation), with `NOS_PTMP` exported:
```bash
slurm/stofs_2d_glo/launch_stofs_2d_glo.sh 20261012 00                    # cold start: COLD=1 is the default
COLD=0 slurm/stofs_2d_glo/launch_stofs_2d_glo.sh 20261012 06             # next cycle, 6 h later
slurm/stofs_2d_glo/status_stofs_2d_glo.sh 20261012 00
```
Run from the clone you want the cards to use. The launcher unsets package-selecting variables from your shell (`HOMEnos`, `EXECnos`, `PYTHONPATH`, `COMROOT`, `COMOUT`, ...), sets `PACKAGEROOT` itself, and checks everything first: it lists every missing piece (`MISSING: <path>`) before anything is queued.

| Option | Meaning |
|---|---|
| `COLD=1` (default) | add `adcprep` to the prep job and `spinup` to the nowcast job; refused when `STAGES` has `nowcast` and no `prep` |
| `COLD=spinup` | only the spin-up (`nod_equi` and the decomposition tar exist); only for the same PDY and CYC as the `adcprep` that made `nod_equi` |
| `COLD=0` | neither; the previous 6-hourly cycle's `hotstart` and `restart` must be in COMOUT |
| `STAGES="prep nowcast forecast post"` | a subset of the four jobs, in that order (default all); only the submitted jobs are linked. The preflight needs the `ncst` forcing for a nowcast job, the `fcst` forcing for a forecast job and both for prep or post |
| `STREAMS="tide surf"` | the streams each nowcast and forecast job runs, one after the other (passed as `ADCIRC_STREAM`); `tide`, `surf` or both in that order |
| `KEEPDATA=YES` | keep each job's `$DATA` (default `NO`) |
| `W_PREP W_NOWCAST W_FORECAST W_POST` | override the walltimes below |
| `ADCIRC_EXEC_DIR`, `COMROOT_2DGLO`, `NOS_PTMP`, `NOS_VENV`, `COMROOT_STAGED` | locations (defaults in section 4) |
| `SUBMIT_GFS=1` | let the prep job's `ncst` and `fcst` steps build the forcing from GFS instead of finding the staged ops forcing (prep then keeps the card's whole node); `ADCIRC_GFS_SOURCE` (default `sflux` here) picks the GFS file family; on Hercules stage the public flux files first with `tools/hercules_2d_glo_stage_forcing.sh --source gfs` |
| `SLURM_CI_ACCOUNT`, `SLURM_CI_QOS` | passed to every `sbatch` as `--account` and `--qos`, overriding the cards' `nos-surge` / `batch` |

| Job | Resources | Walltime | Steps | Waits for |
|---|---|---|---|---|
| prep | 1 node, 1 task, 64 GB | 0:50:00 (cold start 3:50:00) | [`adcprep`,] `gfs_ncst`, `gfs_fcst` | |
| nowcast | 52 nodes x 80 (surf: 4064 + 5 writers) | 1:20:00 (with `spinup` 2:20:00) | [`spinup`,] `tide_ncst`, `surf_ncst` | prep |
| forecast | 52 nodes x 80 | 2:00:00 | `tide_fcst`, `surf_fcst` | nowcast |
| post | 1 node, 1 task, 100 GB | 1:15:00 | `ncdiff`, `ncrcat` | forecast |

The streams run one after the other, so only 52 nodes are busy at a time. The launcher passes the segment and stream lists, space separated, in the environment of `sbatch` (`--export` splits values at commas). There are no done-markers: after a failure resubmit the failed job with a narrower list, as in section 2.5, with `COLD=0`, or `COLD=spinup` if this cold cycle's spin-up has not passed (for example `COLD=0 STAGES="nowcast forecast post"` after a failed nowcast step and `COLD=0 STAGES="forecast post" STREAMS=surf` after a failed `surf_fcst`). On a cold cycle where `adcprep` passed and either the spin-up or the rest of prep failed, one `COLD=spinup` launch redoes the cycle (add `STAGES="nowcast forecast post"` to skip the prep job, whose forcing steps skip files that exist); it needs this cycle's `nod_equi` and the decomposition tar. `COLD=1`, the default, adds `adcprep` to the prep job, so the launcher refuses it when `STAGES` has `nowcast` but no `prep`; use `COLD=spinup` or `COLD=0`. The old `W_COLD`, `W_SPIN`, `W_TNC`, `W_TFC`, `W_SNC`, `W_SFC`, `W_DIFF`, `W_CAT`, `W_GN`, `W_GF` and `SERIAL` stop the launcher with a message naming `W_PREP`, `W_NOWCAST`, `W_FORECAST` and `W_POST`.

Walltimes are the sums of the former per-job Hercules values (measurements plus margin, not the ecf values). A failure cancels the jobs behind it (`--kill-on-invalid-dep=yes`). The launcher writes the job ids to `$NOS_PTMP/$LOGNAME/slurm_2dglo/jobs_<PDY><CYC>.txt`; cancel a chain with `scancel $(awk '{print $2}' <that file>)`. The empty `#SBATCH --output` files land in that directory; the real logs are in `$NOS_PTMP/$LOGNAME/rpt/stofs_2d_glo/`.

Outputs, checks and the station comparison are as on WCOSS2 (sections 2.7 and 2.8). For the comparison use the files the staging tool downloaded:
```bash
python3 .cicd/scripts/compare_2dglo.py ops --out $COMROOT_2DGLO --ops-dir $NOS_PTMP/$LOGNAME/ops_s3/20261012${CYC}/products --pdy 20261012 --cyc $CYC
```

## 4. COMROOT layout and defaults

Both machines use one shared com. Every directory is RUN-prefixed (`stofs_2d_glo`), so nothing collides with SECOFS or ATL in the same tree. Set `COMROOT_2DGLO` to move a run to its own COMROOT for an experiment (for example `com_2dglo_ops` or `com_2dglo_opsstate`).

| Item | WCOSS2 | Hercules |
|---|---|---|
| COMROOT | `${COMROOT_2DGLO:-/lfs/h1/nos/ptmp/$LOGNAME/com}` | `${COMROOT_2DGLO:-$NOS_PTMP/$LOGNAME/com}` |
| Logs | `/lfs/h1/nos/ptmp/$LOGNAME/rpt/stofs_2d_glo` | `$NOS_PTMP/$LOGNAME/rpt/stofs_2d_glo` |
| Work (`DATAROOT`) | `/lfs/h1/nos/ptmp/$LOGNAME/work/stofs_2d_glo` | `$NOS_PTMP/$LOGNAME/work/stofs_2d_glo` |
| GFS (`COMINgfs`) | `/lfs/h1/ops/prod/com/gfs/v16.3` | `$COMROOT_STAGED/gfs`; `COMROOT_STAGED` defaults to `$NOS_PTMP/$LOGNAME/comin_2dglo` (not used in ops mode without `SUBMIT_GFS=1`) |
| `EXECnos` | `<clone>/exec` | `<clone>/exec` |
| ADCIRC | ops `adcirc` module, or `ADCIRC_EXEC_DIR` | `ADCIRC_EXEC_DIR` (launcher default `<parent of the clone>/adcirc_v56.1.0_exec`) |
| `KEEPDATA` | cards `YES`; ops launcher `NO` | cards `YES`; launcher `NO` |

Layout under `$COMROOT/nos/` (ops mode):
```
stofs_2d_glo/                                  COMGES: state that outlives a cycle
    stofs_2d_glo_nod_equi                      tide factors, 365 days from the spin-up start
    stofs_2d_glo_4064.tar, .tar.json           decomposition cache (4064 ranks, keyed on mesh and attribute file sizes)
stofs_2d_glo.<PDY>/                            COMOUT of the day
    stofs_2d_glo.t<HH>z.hotstart               tide chain file
    stofs_2d_glo.t<HH>z.restart                surf chain file
    stofs_2d_glo.t<HH>z.{points,fields}.*.nc   products (section 1)
    stofs_2d_glo.t<HH>z.{pressfc,uvgrd10m,icec}.nc, <region>.f*.grib2, database.tar.gz
    <HH>/rerun/                                per-cycle files: forcing, tide/surf .61-.64, max*, hottime/retime
```
Single mode adds `stofs_2d_glo_mesh_info.json` to COMGES and the `t<HH>z.nowcast` / `t<HH>z.forecast` run directories to the day directory. Both modes use the same decomposition file names in COMGES; a tar made by single mode has no fort.24 and ops mode refuses it, so use a separate `COMROOT_2DGLO` per mode.

- **Chain files:** a cycle starts from the newest chain file found by stepping back 6 h at a time from the cycle minus 6 h, 21 steps (about 5 days). The `ncst` runs from there to the cycle, so a skipped cycle just makes it longer, and the forcing must cover that window.
- **Work directories:** each job works in `$DATAROOT/<job>.<jobid>`. `KEEPDATA=NO` removes it when the job ends; the ADCIRC log tails are copied into the job log first if the run fails.
- **Disk:** plan for about 300 GB of COM per ops-mode cycle (ops writes about 155 GB of products plus 98 GB of rerun files; our forcing is hourly past 120 h) and about 150 GB of work space while a cycle runs.
- **Purge:** ptmp is purged by file age. `nod_equi`, the decomposition tar and the chain files live there; if they age out the next cycle needs a cold start (section 9). Keep a copy of `nod_equi` and the tar on noscrub, and copy without `cp -p`.

## 5. Jenkins (Hercules, manual only)

For a step-by-step build, how to read the result and fixes for common failures, see [hercules_jenkins_run_guide.md](hercules_jenkins_run_guide.md).

STOFS-2D-Global runs in the Hercules Jenkins pipeline only from **Build with Parameters**. The PR-label trigger (`hercules-nos-RT`) is not used for it: a build started by a user with `OFS=stofs_2d_glo` bypasses the label check, and automatic or **Build Now** builds keep `OFS=secofs_ufs`. It reports in the Jenkins build only (no GitHub status).

| Parameter | Values | Meaning |
|---|---|---|
| `OFS` | `secofs_ufs` (default), `stofs_2d_glo`, and the two STOFS-3D-ATL variants | system to run |
| `LEVEL` | `smoke`, `cycle`, `full` | see below (2D-Global and ATL) |
| `DATA_MODE` | `live`, `frozen` | `live`: stage the ops forcing for PDY/CYC now; `frozen`: use a pre-staged dataset |
| `PDY`, `CYC` | date, hour | the frozen datasets are 20261012 06 (smoke, cycle) and 20261012 00 (full) |
| `SEED_RT`, `SEED_SRC`, `NOS_CI_ROOT`, `SLURM_ACCOUNT`, `SLURM_QOS` | | where datasets and trees are seeded from, and the CI account |

2D-Global uses the same Jenkins stages as SECOFS and ATL: Prep, Nowcast, Forecast, Post and Verify. Each model stage calls `.cicd/scripts/run_stage.sh <stage> <PDY> <CYC>`, which submits one job of the section 3.3 chain (the same card, `-N`/`--mem` flags and walltime as `launch_stofs_2d_glo.sh`), waits for it, and passes only on `STAGE_SUMMARY stage=<stage> ofs=stofs_2d_glo status=PASS` in the job log. `stofs_2d_glo.sh card-env <stage>` supplies what differs from SECOFS (card, flags, exports, log prefix, timeout), so there is no separate run chain or poller.

| Stage | Steps | Card | Walltime (cold) | Timeout |
|---|---|---|---|---|
| Prep | [`adcprep`], `gfs_ncst`, `gfs_fcst` | prep | 0:50 (3:50) | walltime + 1 h |
| Nowcast | [`spinup`], `tide_ncst`, `surf_ncst` | nowcast, `-N 52` | 1:20 (2:20) | walltime + 1 h |
| Forecast | `tide_fcst`, `surf_fcst` | forecast, `-N 52` | 2:00 | walltime + 1 h |
| Post | `ncdiff`, `ncrcat` | prep card, `-N 1 -n 1 --mem=100G` (logs under the prep name) | 1:15 | walltime + 1 h |

| LEVEL | Stages run | COLD | Verify |
|---|---|---|---|
| smoke | Prep, Nowcast, Verify | 0 | `rerun/stofs_2d_glo_{tide,surf}.61.nc` against the reference |
| cycle | Prep, Nowcast, Forecast, Post, Verify | 0 | the same, plus `points.*.nc` against the reference; ops comparison reported |
| full | Prep, Nowcast, Forecast, Post, Verify | 1 | the same as cycle (a cold start is deterministic); ops comparison reported |

At every level Prep finds the staged ops forcing and skips its GFS steps, so it takes seconds (full adds `adcprep`). The jobs run with `KEEPDATA=NO` and remove their own work directory. The regression compares bitwise first, and otherwise needs the largest difference in the time-dependent variables (zeta, u-vel, v-vel) within `CMP_TOL` (default 1e-3, in m or m/s). The ops comparison is the section 2.8 report (`OPS_WARN_MM`, default 500). A job in any bad state, or without `STAGE_SUMMARY status=PASS`, fails its stage and the build.

**Layout.** Like SECOFS and ATL, the jobs use the shared `$NOS_PTMP/$LOGNAME/{com,rpt,work}` (the old `com_2dglo_ci` is removed once; an inherited `COMROOT_2DGLO` is ignored). `RUN=stofs_2d_glo` is unique, so the state sits beside SECOFS's and ATL's without touching it: COMGES is `com/nos/stofs_2d_glo` and a cycle is `com/nos/stofs_2d_glo.<PDY>`.

- **frozen:** Stage Data removes only `com/nos/stofs_2d_glo` and `com/nos/stofs_2d_glo.<8 digits>` (exact names, no symlinks, every target checked before the first delete), then links the dataset in: hard links, or copies across file systems. The forcing sits in `rerun/`, a real writable directory in com, because the jobs also publish their products there. The jobs only read the forcing, `nod_equi` and the decomposition tar (they replace the tar by rename), so those are read-only, shared with the dataset. The chain files (`hotstart`, `restart`) are copied into the ADCIRC run directory with their mode and rewritten there, so they stay writable, and Stage copies them (like the `.json` beside the tar, which is rewritten in place when the decomposition is rebuilt) instead of linking. Stage also applies the read-only mode to datasets copied earlier. Use the 06z-type dataset for smoke and cycle (they continue from the previous cycle) and the 00z-type dataset for full.
- **live:** stages the ops forcing with `tools/hercules_2d_glo_stage_forcing.sh --rm-raw` on the front-end node and does not clear com. It continues from the state already there: run `LEVEL=full` first, then `LEVEL=cycle` at +6 h.
- **Prerequisites:** Bootstrap copies `fix/stofs_2d_glo` and `exec/stofs_2d_glo_tide_fac` from `SEED_SRC`, and the ADCIRC build from `SEED_ADCIRC` (default `<parent of SEED_SRC>/adcirc_v56.1.0_exec`). These must be world-readable for the CI account.

**One-time seeding of the frozen datasets.** Run by hand from the clone, as the user who owns the finished runs (a cold start at 00z and the following 06z cycle):
```bash
export COMROOT_2DGLO=$NOS_PTMP/$LOGNAME/com_2dglo_ops          # the finished run
bash .cicd/scripts/stofs_2d_glo.sh seed 20261012 00 cold
bash .cicd/scripts/stofs_2d_glo.sh seed 20261012 06
```
`seed <PDY> <CYC> [cold]` copies the cycle's inputs (the staged forcing, and for a non-cold seed also `nod_equi`, the decomposition tar and the previous cycle's chain files), the reference outputs (tide and surf `.61.nc` and the points files) and, when present, the ops products into `${SEED_RT}/stofs_2d_glo/<PDY><CYC>/`. Optional environment: `SEED_RT` (default `/work2/noaa/nos-surge/mjisan/nos-workflow-rt`), `OPS_DIR` (default `$NOS_PTMP/$LOGNAME/ops_s3/<PDY><CYC>/products`), `NOS_PTMP`, `FORCE=1` (replace an existing dataset). The dataset is made world-readable, and its forcing, `nod_equi` and tar read-only; the script prints the `chmod o+x` for the two parent directories.

## 6. Measured timings

Runs of 2026-10-12: the 00z cold start on both machines, and the 06z `COLD=0` cycle on Hercules. They ran one job per step; in the four-job layout these are the step seconds in each job's `steps=` list. Launcher walltimes are in sections 2.5 (WCOSS2) and 3.3 (Hercules).

WCOSS2 (seconds):

| Step | Runtime |
|---|---|
| adcprep | 6177 |
| spinup | 1564 |
| gfs_ncst | 19 |
| gfs_fcst | 416 |
| tide_ncst | 750 |
| surf_ncst | 821 |
| tide_fcst | 1672 |
| surf_fcst | 2335 |
| anomaly | 241 |
| bias | 1496 |
| ncdiff | 91 |
| grib2 | 649 |
| ncrcat | 443 |

The four jobs run their steps one after the other, so a cycle takes the sum of its steps: about 2.5 h on WCOSS2 (435 s prep, 1571 s nowcast, 4007 s forecast, 2920 s post), plus queue. The two ncst steps spend most of their time on decomposition extract and staging.

Hercules (seconds):

| Step | 00z cold start | 06z (`COLD=0`) |
|---|---|---|
| adcprep | 6716 | not run |
| spinup | 1576 | not run |
| tide_ncst | 1128 | 671 |
| surf_ncst | 1115 | 791 |
| tide_fcst | 1808 | 2131 |
| surf_fcst | 2205 | 2457 |
| ncdiff | 209 | 256 |
| ncrcat | 586 | 592 |

## 7. Results against operational

Metric: for each station, the maximum absolute water-level difference from ops over the common times; the table gives the median over stations (`compare_2dglo.py ops`, section 2.8), in mm.

| Run | htp | cwl.noanomaly | swl |
|---|---|---|---|
| Cold start 20261012 00z, WCOSS2 | 59 | 173 | 164 |
| Cold start 20261012 00z, Hercules | 59 | 173 | 164 |
| 20261012 06z, `COLD=0`, Hercules | 52.6 | 154.5 | 141.8 |

WCOSS2 and Hercules agree. The differences are cold-start effects, not the run mechanics:
- ops has cycled for months, while a cold start spins up tide-only for 162 h (6.75 days) from rest and then runs the 6 h nowcast, so the cycle is 7 days after the start;
- the DRAMP ramp is 6.75 days (tanh), about 0.97 at the cycle time, so the tide is not fully developed;
- the nodal factors come from the cold-start date (`nod_equi` starts at the spin-up start), while ops uses its own `nod_equi`; a start from the ops state copies that file.

The worst stations are macro-tidal (Bristol Bay, Valdez, Anchorage). SA816 (Sea of Azov) and SA803 (Black Sea) are non-physical in the operational output as well, so differences there are not a nos-workflow problem. The forcing itself matches ops exactly (section 1).

The close comparison is a start from the ops state (section 2.6): same chain files, nodal factors, forcing and rank count, so the nowcast and the first 120 h of the forecast should be very close to ops, with small differences after 120 h from the interpolated forcing. Last-bit agreement needs the ops adcirc module (its adcprep partition and padcirc). This is WCOSS2 only, and this guide records no result for it yet.

## 8. Known limitations

- GEMPAK is not ported.
- The SHEF bulletins are made but not sent (`SENDDBN=NO`).
- No watchdogs.
- No unattended 4-a-day cycling (cron or ecFlow cards): use the launchers.
- Anomaly, bias and GRIB2/SHEF run on WCOSS2 only (they need the ops package, `cfp` and `tocgrib2`).
- A cold start from rest is the only start on Hercules; a start from the ops state is WCOSS2 only.
- Single mode has no post stage.
- The first ops-mode cycle without a seeded `database.tar.gz` has an empty anomaly history.
- `nod_equi` is fixed for 365 days from the spin-up start; there is no check for its age, so run `COLDSTART=YES` again (or copy the ops file) well before then.

## 9. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Jobs run another package's code although the launcher was run from your clone | A plain `PACKAGEROOT=...` or `HOMEnos=...` in `~/.bashrc` overrides the clone path the launcher passes (section 2.1). Find it with `grep -n -e PACKAGEROOT -e HOMEnos ~/.bashrc ~/.bash_profile` and use `${VAR:-...}`. |
| `FATAL: <clone>/fix/stofs_2d_glo/stofs_2d_glo_grid missing (tools/fetch_stofs_2d_glo_fix.sh)` (or `stofs_2d_glo_attr`) | Fix files not staged in this clone. Run the fetch tool from the clone root (`WITH_BODY=1` for ops mode). |
| `FATAL: padcirc not found (module adcirc or ADCIRC_EXEC_DIR)` or `FATAL: adcprep not found (module adcirc or ADCIRC_EXEC_DIR)` | No ops adcirc module on this login. Export `ADCIRC_EXEC_DIR` (and `ADCIRC_MODULE_PATH`) before the launcher, or on Hercules build with `tools/build_stofs_2d_glo_adcirc_hercules.sh`. |
| `FATAL: stofs_2d_glo_tide_fac not found in EXECnos (...)` | Copy it into `exec/` (section 2.3) or build it on Hercules (section 3.1). |
| `FATAL ERROR: there are no restart files, run a cold start (...)` (or `hotstart`) | No chain file in the last 21 x 6 h. The previous cycle did not finish, the ptmp copy aged out, or the section 2.6 copy is missing. Start with `COLDSTART=YES` (WCOSS2) or `COLD=1` (Hercules). |
| `FATAL ERROR: no .../stofs_2d_glo_nod_equi; there are no tidal spin-up files, run a cold start (...)` | `nod_equi` is missing from COMGES: no cold start was run in this COMROOT, it aged out of ptmp, or the section 2.6 copy is missing. |
| `FATAL ERROR: ... is a single-mode decomposition (no fort.24); delete it and its .json to rebuild, or run a cold start (...)` | A tar made in single mode is in this COMROOT. Delete `stofs_2d_glo_4064.tar` and its `.json`, or use a separate `COMROOT_2DGLO`. |
| `GFS file did not appear before the wait expired: <path>` | The GFS `sfcf` file is missing or purged (the WCOSS2 tank keeps about 10 days). Pick another cycle or launch later; the GFS steps wait up to 420 s (ncst) and 1800 s (fcst) in total. |
| `<file> has N records but the restart chain start needs M: the forcing window does not match it; delete rerun/...22?.nc and re-run the GFS ncst prep` | The cycle was launched before the previous cycle's nowcasts finished, or a cycle was skipped. Delete the named `rerun` forcing files and relaunch. On Hercules, stage the forcing with the matching `NCST_RECORDS`. |
| `FATAL ERROR: GFS surface forcing does not exist: <path>` | The surf segment ran without its forcing. WCOSS2: the prep job did not pass. Hercules: run `tools/hercules_2d_glo_stage_forcing.sh <PDY> <CYC>` first. |
| `ops package (STOFS_RUNVER=...) or tools missing for post <segment>: ...` | The post preflight lists the missing ops package files, modules or tools. Check `STOFS_RUNVER` and the section 2.4 check. |
| `ncdiff not found on PATH (module load nco)` | NCO is not on the job's `PATH`. The WCOSS2 prep card loads `nco` and `nos_hercules.intel` provides it on Hercules; check `module list` in the job log. |
| `<N> ranks (compute + writers) exceed the <M> allocated; raise the node count at submit time` | The allocation is too small. Surf needs 4064 + 5 = 4069 ranks: 32 x 128 on WCOSS2, 51 x 80 on Hercules (the jobs request 52). |
| `padcirc dropped an output record: re-run this step (STAGES=... [STREAMS=...]); fort.63.nc (surf fcst) has 185 records, expected 186; gap times: ...` | A padcirc writer drop left a gap in a `fort.61` to `fort.64` series. The surf run writes five files per output step (`fort.63`, `fort.64`, `fort.73`, `fort.74`, and the ice file `fort.93`) and ADCIRC hands each event to the next writer in turn, so with many writers two overlapping writes of one file can take the same record slot and one record is lost; the surf run uses 5 writers, one per file, which avoids it. the step fails before it publishes anything or advances the state, so it re-runs cleanly. Use the `STAGES`/`STREAMS` the message prints: after `ncst` `STAGES="nowcast forecast post"`; after `tide_fcst` `STAGES="forecast post"`; after `surf_fcst` `STAGES="forecast post" STREAMS=surf` (section 2.5). |
| `... has advanced past this fcst ... redo the cycle from ncst`, or `missing or empty ...hottime.out; run the tide nowcast first` | The forecast ran before its nowcast, or twice. Re-run the stream from `ncst`. |
| `nod_equi starts ... but this cycle's spin-up starts ...; run the adcprep segment for this cycle first (COLDSTART=YES / COLD=1)` | `COLD=spinup` only works for the same PDY and CYC as the `adcprep` step that made `nod_equi`. |
| `ADCIRC execution failed with return code N` or `ADCIRC crashed (rc=0 but log reports): ...` | The job log shows the last 30 lines of `adcirc.out` and `adcirc.err`. To keep the whole work directory, relaunch with `KEEPDATA=YES`. |
| A job exited 0 but the stage failed | Always check `STAGE_SUMMARY ... status=PASS`. The cards exit 1 unless the log has it. |
| WCOSS2: later jobs still held after a failure | Normally PBS cancels them. `qdel` any that remain (`qstat -u $LOGNAME`), fix, relaunch. |
| WCOSS2: the launcher printed fewer than the 4 jobs (or the `STAGES` you asked for) | `qsub` rejected a job. `qdel` the printed ids, fix the message (check the section 2.4 queue test). |
| WCOSS2: a post job stays queued for hours | The dev queue may not reach prepost nodes for that shape. Check `qstat -f <id>` for the comment line. |
| HDF5 version-mismatch abort in python | The python's netCDF4 and the module HDF5 clash. Run the section 2.4 check and send the output. |
| `xarray/cfgrib/eccodes not importable` (single mode) | `pip install cfgrib eccodes` in the python, or set `ECCODES_DIR`. |
| Seed or chain files vanished from ptmp | ptmp purges by file age. Keep `nod_equi` and the decomposition tar on noscrub, copy without `cp -p`, and cold-start again if the chain files are gone. |
| Hercules: `ERROR: ... is not named nos-workflow; the cards run $PACKAGEROOT/nos-workflow` | Clone it as `<dir>/nos-workflow`. |
| Hercules: `ERROR: SLURM_JOB_ID=... is set (srun/salloc shell)` | Exit the allocation and run the launcher from a login node shell. |
| Hercules: `MISSING: <path>` from the launcher | Everything missing is listed at once: executables, staged forcing, fix files, and for `COLD=spinup`/`COLD=0` the `nod_equi`, tar and previous chain files. Nothing was queued. |
| Hercules: `FATAL: inside Slurm job N: compute nodes have no internet; run '... download' on a login node, then 'build'` | Run the download mode (or the staging and fetch tools) on a login node. |
| Hercules: `FATAL: nos-utils HEAD ... != gitlink ...` | `git submodule update ush/python/nos-utils` in the clone. |
| Hercules: `export PACKAGEROOT=<dir holding the 2D-Global nos-workflow clone>` | A card was submitted directly without `PACKAGEROOT`. Use the launcher. |
| Hercules job ran another package (SECOFS or ATL) | A leaked variable in the submitting shell. The launcher unsets the package-selecting ones; start from a fresh shell. |
| `KEEPDATA=NO` and the work directory is gone | By design. Relaunch with `KEEPDATA=YES`. In single mode the cards default to `YES`, so those directories pile up; delete them by hand. |
