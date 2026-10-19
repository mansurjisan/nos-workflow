# Running SECOFS with nos-workflow on WCOSS2 and Hercules

Applies to nos-workflow `develop` 4ac0f15 (2026-10-19). Update this guide in the same PR as any change to the SECOFS yaml, cards, launchers or fix set. Statements marked "as of <date>" come from run records that this repository does not hold.

## 1. What you are running

Two configurations. Both couple through UFS-Coastal with the CMEPS mediator and a CDEPS data atmosphere (DATM).

| | `secofs_ufs` | `secofs_ufs_ww3` |
|---|---|---|
| Components | DATM + SCHISM | DATM + SCHISM + WAVEWATCH III |
| Executable | `fv3_coastalS.exe` | `fv3_coastalSW.exe` |
| Config | `parm/systems/secofs_ufs.yaml` | `parm/systems/secofs_ufs_ww3.yaml` (inherits `secofs_ufs`) |
| Ranks | 120 DATM/MED + 2794 SCHISM = 2914 | 120 DATM + 2794 SCHISM + 2606 WW3 = 5520 (the mediator spans all 5520) |
| WCOSS2 allocation | 25 nodes x 120 ranks | 46 nodes x 120 ranks |
| Machines | WCOSS2, Hercules | WCOSS2 |
| Model step, coupling | SCHISM dt 120 s, coupling 120 s | SCHISM dt 120 s, coupling 360 s (WW3 substeps 120 s) |
| Nowcast / forecast | 6 h / 48 h | 24 h / 48 h |
| Cycles | 00, 06, 12, 18 z | 12 z, daily |
| Launcher | `pbs/launch_secofs_ufs.sh <CYC>` | `pbs/secofs_ufs_ww3/launch_secofs_ufs_ww3.sh <CYC>` |

Common to both: the SECOFS mesh has 1,686,665 nodes, 3,325,055 elements and 63 levels. Forcing is GFS and HRRR blended into the DATM file (0.025 degree blend), NWM rivers, RTOFS ocean boundary and nudging, and tides from the yaml constituents (M2 S2 N2 K2 K1 O1 P1 Q1). The prep domain is lon -88 to -63, lat 17 to 40.

Each cycle has four stages: `prep`, `nowcast`, `forecast`, `post`. The forecast restarts from the nowcast restart. The station product has 430 stations; the `nstation: 97` in the yaml is stale (station.in has 430 rows, as of 2026-08-04).

Waves (`secofs_ufs_ww3` only): WW3 runs on a water-only wave mesh of about 689 thousand nodes with the GFS-Wave spectral grid (50 frequencies, 36 directions), as of 2026-08. Boundary spectra come from the GFS-Wave point-spectra product, built into `nest.ww3` by prep.

Run identity: `NET=nos`, `RUN=OFS=<config name>`. `PREFIXNOS` stays `secofs_ufs` for both, so the wave config reads the `secofs_ufs.*` fix statics. COMOUT is `${COMROOT}/nos/<RUN>.<PDY>`. The two configurations write different COMOUT names and can share one COMROOT.

The yaml also carries a GEFS ensemble block for `secofs_ufs`. This guide does not cover it; `secofs_ufs_ww3` disables it.

## 2. Concepts for both machines

### COMROOT

- WCOSS2: the cards fix `COMROOT=/lfs/h1/nos/ptmp/$LOGNAME/com`, work in `/lfs/h1/nos/ptmp/$LOGNAME/work/<RUN>` and logs in `/lfs/h1/nos/ptmp/$LOGNAME/rpt/<RUN>`.
- Hercules: `COMROOT` defaults to `$NOS_PTMP/$LOGNAME/com`. `NOS_PTMP` defaults to the maintainer's `/work2/noaa/nos-surge/mjisan/nos-run/ptmp`; set your own.

### First cycle versus later cycles

Later cycles need nothing. The nowcast starts from the previous cycle's restart (`<RUN>.t<cyc>z.<PDY>.rst.nowcast.nc`), and prep stages it for you. The first cycle of a COMROOT needs a seed.

The nowcast stage requires `$COMOUT/<RUN>.t<cyc>z.<PDY>.init.nowcast.nc` (`stage_hotstart` in `runners/schism_ufs/stage_files.py`). There is no automatic cold start: without this file the nowcast stops with `requires hotstart.nc but no source was found`. The file must be NETCDF4_CLASSIC.

How the file appears:
1. **Previous restart exists.** Prep's `HotstartProcessor` finds the previous cycle's restart, converts it to NETCDF4_CLASSIC (`nccopy`, or netCDF4-Python) and writes the init file. The restart written by `combine_hotstart7` is HDF5, so the conversion is required.
2. **You seed it.** If the init file already exists and is NETCDF4_CLASSIC, prep keeps it. With a previous restart present it logs that the seed is preserved, not overwritten. A seed that is not NETCDF4_CLASSIC fails prep.
3. **Nothing exists.** The nowcast fails. Make a seed as below.

A restart that prep finds, valid at a different time than cycle minus nowcast length, is relabelled to the cycle anchor, and prep warns that ocean evolution is skipped or re-simulated. A hand-made seed gets no time check; prep logs `Using operator-provided seed ... as-is`.

Ways to make a seed:
```bash
# rest state: elevation 0, velocity 0, uniform T/S (defaults 5 C, 32 psu)
# run from the clone root, with a python that has numpy and netCDF4
COMOUT=/lfs/h1/nos/ptmp/$LOGNAME/com/nos/<RUN>.<PDY>      # Hercules: $NOS_PTMP/$LOGNAME/com/nos/<RUN>.<PDY>
mkdir -p $COMOUT
FIX=fix/secofs_ufs
NVRT=$(awk 'NR==2{print $1; exit}' $FIX/secofs_ufs.vgrid.in)      # 63
python3 tools/make_cold_start_hotstart.py --hgrid $FIX/secofs_ufs.hgrid.gr3 --nvrt $NVRT \
        --out $COMOUT/<RUN>.t<cyc>z.<PDY>.init.nowcast.nc
# or convert an existing restart from another run of the same mesh
nccopy -k 'netCDF-4 classic model' <restart>.nc $COMOUT/<RUN>.t<cyc>z.<PDY>.init.nowcast.nc
```
The rest state has no baroclinic structure and needs spin-up; use a real restart when you have one. `make_cold_start_hotstart.py --verify` checks a file. The Jenkins stage data step uses the rest-state recipe in live mode (`.cicd/scripts/stage_data.sh`). For `secofs_ufs_ww3` the seed name uses `secofs_ufs_ww3`; a `secofs_ufs` restart of the same mesh has been used for this (August 2026 bring-up).

Wave state (`secofs_ufs_ww3`): WW3 and the mediator do not use the SCHISM hotstart. The nowcast writes `<RUN>.t<cyc>z.wave_restart/` (WW3 and CMEPS restarts) to COMOUT, and the same cycle's forecast reads it. The next cycle's nowcast also reads it (warm start, `forcing.waves.nowcast_warm_start: true`, enabled by PR #183 on 2026-09-03). It searches back up to `WAV_NOWCAST_WARM_START_BACK_HOURS` (default 24). With no usable restart the nowcast cold-starts the waves and logs a warning. Roll back with `nowcast_warm_start: false` in `secofs_ufs_ww3.yaml`, or `qsub` the nowcast card by hand with `-v ...,WAV_NOWCAST_WARM_START=0`. The launcher does not forward that variable.

### Inputs read by prep

| Input | WCOSS2 default | Used for |
|---|---|---|
| GFS 0.25 degree (`COMINgfs`) | `/lfs/h1/ops/prod/com/gfs/v16.3` | DATM atmosphere |
| HRRR (`COMINhrrr`) | `/lfs/h1/ops/prod/com/hrrr/v4.1` | DATM atmosphere, blended over GFS |
| RTOFS 2D and 3D (`COMINrtofs_2d`, `COMINrtofs_3d`) | `/lfs/h1/ops/prod/com/rtofs/v2.5` | ocean boundary, nudging |
| NWM (`COMINnwm`) | `/lfs/h1/ops/prod/com/nwm/v3.1` | river sources and sinks, Savannah flow boundary |
| GFS-Wave (`COMINgfswave`, wave config only) | same as `COMINgfs` | boundary spectra |
| Tides | `fix/secofs_ufs` files | `bctides.in` per cycle |

The versions come from `versions/run.ver`. Each `COMIN*` can be overridden in the environment. The GFS-Wave product is `gfs.<PDY>/<CC>/wave/station/gfswave.t<CC>z.ibp_tar` plus `spec_tar.gz`; prep walks back up to `forcing.waves.max_cycle_fallback` (2) older cycles when the newest is not posted.

Prep uses the Fortran tide_fac `nos_ofs_create_tide_fac_schism` from `exec/` when present, and otherwise Python nodal corrections with a warning.

### Fix files

There is no fetch tool for SECOFS. Copy the fix set from an existing package (section 3.1a). `fix/secofs_ufs` and `fix/secofs_ufs_ww3` track only the small templates and namelists; the rest is ignored by `.gitignore`.

Tracked in git:
- `fix/secofs_ufs`: `datm.streams.template`, `datm_in.template`, `model_configure.template`, `fd_ufs.yaml`, `ufs.configure`, `noahmptable.tbl`, `secofs_ufs.param.nml`, `secofs_ufs.mllw_datum.csv`.
- `fix/secofs_ufs_ww3`: the same templates, `secofs_ufs_ww3.param.nml`, `ww3_grid.nml`, `ww3_shel.nml`, `secofs_ufs_ww3.namelists_pdlib.nml`.

Untracked, named by `secofs_ufs.yaml`, all in `fix/secofs_ufs` with the `secofs_ufs.` prefix unless noted:
- Grid: `hgrid.gr3`, `hgrid.ll`, `vgrid.in`, `vgrid.nu.in`, `vgrid.fake.in`, `shapiro.gr3`, `diffmin.gr3`, `diffmax.gr3`, `albedo.gr3`, `rough.gr3`, `station.in`.
- Rivers: `sources.json`, `sinks.json`, `river.ctl`, `nwm.reach.dat` (one reach, Savannah), and `nosofs.river.clim.usgs.nc`.
- Ocean boundary and nudging: `obc.ctl`, `nudge.gr3`, `nobc_nudge_index.dat`, and `nosofs.clim.WOA05.nc`.
- Tides: `bctides.in`, `bctides.in_template`, and `nosofs.HC_NWLON.nc`.
- Met control: `sflux_inputs.txt` (the yaml `met_ctl_file`).
- `secofs_ufs.partition.prop` (2794 SCHISM ranks), required: `fv3_coastalS.exe` is a `NO_PARMETIS` build on both machines. `tvd.prop` and `fluxflag.prop` are staged if present. In UFS mode a missing `partition.prop` is skipped silently (`stage_partition_props`), so check the log (section 9).

`fix/secofs_ufs_ww3` must also carry every `secofs_ufs.*` static above (including `secofs_ufs.mllw_datum.csv`), because `$FIXofs` points there for the wave config, plus the wave-only files (all named `secofs_ufs.*`):
- `mod_def.ww3` (the preprocessed WW3 grid)
- `mesh_wav.nc` (WAV ESMF mesh)
- `ocn2wav_weights.nc` and `wav2ocn_weights.nc` (precomputed regrid weights)
- `ww3_bound_points.list` (boundary points; must exist before the first wave prep)

The grid file `*.msh` and the `.ww3` files are too large for git.

### Executables

In `exec/`:

| File | Needed by | How it was built |
|---|---|---|
| `fv3_coastalS.exe` | both (non-wave) | oceanmodeling `ufs-weather-model` fork, `tests/compile.sh`, app `CSTLS`. Hercules flags: `-DAPP=CSTLS -DUSE_ATMOS=ON -DNO_PARMETIS=ON -DOLDIO=ON -DBUILD_UTILS=ON` (`sorc/build_hercules.sh`). The WCOSS2 build is also `-DNO_PARMETIS=ON`, so `partition.prop` is required (section 2, fix files). |
| `fv3_coastalSW.exe` | wave config | same fork, app `CSTLSW`, built with the `USE_WW3` flag (without it the `RADFLAG` parameters in the param.nml are ignored). Carries three local patches (one CMEPS, two WW3) that are kept outside the repo. Ask the maintainer. |
| `schism_combine_hotstart7.exe` | both | `combine_hotstart7` from the same build tree, renamed |
| `combine_output11`, `combine_output11_MPI` | both | same build tree |
| `ww3_bound` | wave config | WW3 tool (WCOSS2 copy is a wrapper that sets `LD_LIBRARY_PATH`, as of 2026-08) |
| `nos_ofs_create_tide_fac_schism` | optional | Fortran tide_fac; without it prep uses the Python fallback |

Do not build the SECOFS executable from a SCHISM tree that carries a local "ihot=1 tidal phase fix": it shifts the boundary tide by the restart time (found and removed in August 2026). A clean build has no `tidal phase fix` string in `mirror.out`.

## 3. WCOSS2

### 3.1 One-time setup

```bash
cd /lfs/h1/nos/estofs/noscrub/$LOGNAME/packages
git clone https://github.com/oceanmodeling/nos-workflow
cd nos-workflow && git checkout develop && git pull --ff-only
git submodule update --init ush/python/nos-utils
```
The cards set `PACKAGEROOT=/lfs/h1/nos/estofs/noscrub/$LOGNAME/packages` by plain assignment and `HOMEnos=${PACKAGEROOT}/nos-workflow`, so `~/.bashrc` cannot override them. The jobs always run `$LOGNAME/packages/nos-workflow`. Clone at that path, or edit `PACKAGEROOT` in all 8 cards (4 per config). `PKG` only selects which card files a launcher submits.

Cards submit with `#PBS -A ESTOFS-DEV -q dev`. Without that project, change `#PBS -A`.

### 3.1a Fix files and executables from an existing package

Copy only fix files and executables, never the whole package. `fix/` and `exec/` are often symlinks, so use `cp -L`. As of 2026-10-19 the maintainer's package holds a validated set (the paths may move):
```bash
M=/lfs/h1/nos/estofs/noscrub/mansur.jisan/packages/nos-workflow
mkdir -p exec fix/secofs_ufs fix/secofs_ufs_ww3
cp -rL $M/fix/secofs_ufs/. fix/secofs_ufs/
cp -rL $M/fix/secofs_ufs_ww3/. fix/secofs_ufs_ww3/          # wave config only
git checkout -- fix/secofs_ufs fix/secofs_ufs_ww3           # keep this clone's tracked files
cp -L $M/exec/fv3_coastalS.exe $M/exec/schism_combine_hotstart7.exe exec/
cp -L $M/exec/combine_output11 $M/exec/combine_output11_MPI exec/
cp -L $M/exec/nos_ofs_create_tide_fac_schism exec/                         # optional
cp -L $M/exec/fv3_coastalSW.exe $M/exec/ww3_bound exec/                    # wave config only
ls exec fix/secofs_ufs | head -50
```
If a copy fails with "Permission denied", ask the maintainer to run `chmod -R g+rX` on the source. `$FIXofs` defaults to `<pkg>/fix/secofs_ufs_ww3` for the wave config, and the wave statics are there in the maintainer package.

### 3.2 Cards and launchers

| | `secofs_ufs` | `secofs_ufs_ww3` |
|---|---|---|
| Cards | `pbs/jnos_{prep,nowcast,forecast,post}_00.pbs` | `pbs/secofs_ufs_ww3/jnos_{prep,nowcast,forecast,post}_00.pbs` |
| Launcher | `pbs/launch_secofs_ufs.sh <CYC>` | `pbs/secofs_ufs_ww3/launch_secofs_ufs_ww3.sh <CYC>` |
| prep | 1 node (8 ranks), 2:00 | same |
| nowcast | 25 nodes, 1:30 | 46 nodes, 4:00 |
| forecast | 25 nodes, 5:30 | 46 nodes, 6:30 |
| post | 1 node, 2:00 | 1 node, 2:00 |

The `secofs_ufs` cards default `TOTAL_TASKS` to 1200. That default is stale and unused: the resolver sets 2914 from `resources.nprocs` in the yaml (checked with `yaml_to_env`). The wave cards also load the OFI settings (`FI_OFI_RXM_*`) needed at high rank counts and set `UFS_EXEC_NAME=fv3_coastalSW.exe`.

Run one cycle (PDY defaults to today, UTC):
```bash
cd /lfs/h1/nos/estofs/noscrub/$LOGNAME/packages/nos-workflow/pbs
DRYRUN=1 ./launch_secofs_ufs.sh 12                    # stage nothing, print the qsubs
./launch_secofs_ufs.sh 12
PDY=20261019 STAGES="forecast post" ./launch_secofs_ufs.sh 12    # re-run only some stages
./secofs_ufs_ww3/launch_secofs_ufs_ww3.sh 12
```
The launchers submit one stage, wait for `STAGE_SUMMARY ... status=PASS` in that stage's log, then submit the next. They do not use `afterok`, because a retry resubmits the stage under a new job id. A failed stage stops the cycle. Launcher logs and status files: `$RPTDIR/launch_<RUN>.<PDY>t<cyc>z.{log,status}`. A second launch for the same PDY and cycle exits at once while the first holds the lock. The post-stage knobs `NOS_POST_PRODUCTS`, `NOS_POST_MAX_WORKERS`, `NOS_PROFILES_OUTSIDE`, `POST_FIELDS_DEFLATE`, `NOS_ARCHIVE_FIELDS` and `NOS_COMBINE_OUTPUTS_SCRIPT` are forwarded when set.

If you run a card by hand, pass what it needs; `qsub -v` replaces the job environment:
```bash
qsub -v PDY=20261019,CYC=12 pbs/jnos_prep_00.pbs
```
Use uppercase `CYC`. A retry passes `CYC` on, and a lowercase variable silently re-runs non-00z cycles as 00z.

### 3.3 Timeouts and the ParMETIS retry

The nowcast and forecast cards carry a blind retry, a dormant safety net with the `NO_PARMETIS` builds, for the nondeterministic ParMETIS crash (`partition_hgrid`, `double free or corruption`, `Failed during initial partitioning`). The crash happens at about 2914 ranks. The card decides from the log, not the exit code: if that signature is in `.out` or `.err` and there is no `status=PASS`, it resubmits itself with `PARMETIS_RETRY` incremented, up to 8 times. The log shows `PARMETIS_RETRY: ... resubmitting attempt N/8`. Post and prep do not retry.

Launcher stage timeouts (seconds). Each is at least the card walltime; the launcher only stops watching and never runs `qdel`:

| Stage | `secofs_ufs` | `secofs_ufs_ww3` |
|---|---|---|
| prep | 7800 | 7800 |
| nowcast | 10800 (one attempt plus one retry) | 30600 (two attempts plus 30 min) |
| forecast | 20400 (one attempt) | 25200 (one attempt) |
| post | 7800 | 7800 |

A stage that is still retrying after its timeout is reported `FAIL ... TIMEOUT` although a later retry may pass. Read the outcome from the retried job's log under `$RPTDIR`.

### 3.4 Cron

Launch each cycle about 2 h 15 min after cycle time (UTC). Once, on the login node that will run cron:
```bash
mkdir -p /lfs/h1/nos/ptmp/$LOGNAME/rpt/secofs_ufs /lfs/h1/nos/ptmp/$LOGNAME/rpt/secofs_ufs_ww3
crontab -e
```
Add these lines, the maintainer's crontab. Cron runs each line through `/bin/sh`, which expands `$LOGNAME`:
```
15 2  * * * /lfs/h1/nos/estofs/noscrub/$LOGNAME/packages/nos-workflow/pbs/launch_secofs_ufs.sh 00 >> /lfs/h1/nos/ptmp/$LOGNAME/rpt/secofs_ufs/launch.00.log 2>&1
15 8  * * * /lfs/h1/nos/estofs/noscrub/$LOGNAME/packages/nos-workflow/pbs/launch_secofs_ufs.sh 06 >> /lfs/h1/nos/ptmp/$LOGNAME/rpt/secofs_ufs/launch.06.log 2>&1
15 14 * * * /lfs/h1/nos/estofs/noscrub/$LOGNAME/packages/nos-workflow/pbs/launch_secofs_ufs.sh 12 >> /lfs/h1/nos/ptmp/$LOGNAME/rpt/secofs_ufs/launch.12.log 2>&1
15 20 * * * /lfs/h1/nos/estofs/noscrub/$LOGNAME/packages/nos-workflow/pbs/launch_secofs_ufs.sh 18 >> /lfs/h1/nos/ptmp/$LOGNAME/rpt/secofs_ufs/launch.18.log 2>&1
15 18 * * * /lfs/h1/nos/estofs/noscrub/$LOGNAME/packages/nos-workflow/pbs/secofs_ufs_ww3/launch_secofs_ufs_ww3.sh 12 >> /lfs/h1/nos/ptmp/$LOGNAME/rpt/secofs_ufs_ww3/launch.12.log 2>&1
05 2,8,14,20 * * * /lfs/h1/nos/estofs/noscrub/$LOGNAME/packages/nos-workflow/pbs/clean_work.sh >> /lfs/h1/nos/ptmp/$LOGNAME/rpt/clean_work.log 2>&1
```
The wave cycle starts at 18:15 UTC, after the GFS-Wave tarball arrives (about 16:30 UTC, as of 2026-08-21). Check `crontab -l` afterwards: a multi-line paste can drop lines. The launchers set `PATH`, `USER` and `HOME` themselves.

`clean_work.sh [run ...]` keeps the newest work directory per stage and run (default runs: `secofs_ufs secofs_ufs_ww3`, `KEEP=2` keeps more, `DRYRUN=1` lists only). It never removes a directory of a job PBS still tracks. The cards set `KEEPDATA=YES`, so work directories otherwise accumulate.

### 3.5 Warm-start experiment launcher (wave config)

`pbs/secofs_ufs_ww3/launch_secofs_ufs_ww3_warm.sh [PDY]` runs only the nowcast leg of the 12 z cycle, warm-started from the previous cycle, into a scratch COMOUT (`/lfs/h1/nos/ptmp/$LOGNAME/warmtest/com/nos`). It waits for the operational prep of the same cycle, copies prep's inputs, submits `jnos_nowcast_00.pbs` with `WAV_NOWCAST_WARM_START=YES` and logs one `RESULT` line per day to `$WARM_BASE/launch_secofs_ufs_ww3_warm.chain.log`. It never touches the operational chain. Since the yaml now enables warm start, the operational chain warm-starts too; this launcher is an experiment tool. `DRYRUN=1` stages and prints the qsub.

## 4. Hercules (Slurm), `secofs_ufs` only

### 4.1 Setup

- Cards: `slurm/secofs_ufs/jnos_{prep,nowcast,forecast,post}_00.sh`. Prep and post use 1 node with 8 tasks (2:00). Nowcast (1:30) and forecast (5:30) use 37 nodes x 80 tasks. Defaults: account `nos-surge`, qos `batch`, partition `hercules`.
- Defaults point at the maintainer's `/work2/noaa/nos-surge/mjisan` for `PACKAGEROOT` and `NOS_PTMP`. Set `PACKAGEROOT` (the parent of your `nos-workflow` clone), `NOS_PTMP`, and `--account`/`--qos` for your own account.
- Modules: `modulefiles/nos_hercules.intel.lua`. Python extras (scipy, editable nos-utils) come from a venv, `NOS_VENV` (default `$HOME/nos-venv`), activated after the module load. Create it with the module loaded, with the stack's python, or `import` fails.
- Build the executable with `sorc/build_hercules.sh` (set `EXECnos`; optional `UFS_COASTAL_DIR`, `UFS_COASTAL_REF`, `MAKE_OPT`). It builds `fv3_coastalS.exe` with `-DAPP=CSTLS -DUSE_ATMOS=ON -DNO_PARMETIS=ON -DOLDIO=ON -DBUILD_UTILS=ON` and installs the combine tools. `NO_PARMETIS=ON` is required: ParMETIS hangs at 2794 ranks on Hercules (as of 2026-08-26). Stage `secofs_ufs.partition.prop` for 2794 ranks in `fix/secofs_ufs` (`tools/gen_stofs_partition_prop.sh <N_OCN_RANKS> <SCHISM_SRC> <HGRID>` generates one; pass the SECOFS hgrid, because the defaults are STOFS paths).
- Fix files: copy from a WCOSS2 or Hercules package as in section 3.1a.
- Inputs: Hercules has no COMIN trees. Stage the public NODD files (GFS, HRRR, RTOFS, NWM) of a completed published cycle:
```bash
COMROOT_STAGED=$NOS_PTMP/$LOGNAME/comin_2026101912    # any empty directory you own
python3 ush/stage_comin.py --pdy 20261019 --cyc 12 --comroot $COMROOT_STAGED
```
An unpublished or partial cycle exits nonzero on missing files. The cards read `$COMROOT_STAGED/{gfs,hrrr,rtofs,nwm}`.

### 4.2 Run

There is no launcher. Submit each stage after the previous one passes. Do not use `--dependency=afterok`: a crashed stage can exit 0.
```bash
cd <clone>/slurm/secofs_ufs
E=ALL,PDY=20261019,CYC=12,COMROOT_STAGED=$COMROOT_STAGED,NOS_PTMP=$NOS_PTMP
sbatch --export=$E jnos_prep_00.sh          # wait for STAGE_SUMMARY status=PASS in the log
sbatch --export=$E jnos_nowcast_00.sh
sbatch --export=$E jnos_forecast_00.sh
sbatch --export=$E jnos_post_00.sh
```
The first cycle needs the init file of section 2. The Hercules cards do not retry.

For Jenkins (manual or PR runs), frozen datasets and `freeze_dataset.sh`, see `docs/hercules_jenkins_run_guide.md`, sections 8 and 12.3.

## 5. Checking a run

Logs: `rpt/<RUN>/<RUN>_<stage>_00.<jobid>.out|.err` under your ptmp (`/lfs/h1/nos/ptmp/$LOGNAME` on WCOSS2, `$NOS_PTMP/$LOGNAME` on Hercules). Every stage ends with:
```bash
grep STAGE_SUMMARY /lfs/h1/nos/ptmp/$LOGNAME/rpt/secofs_ufs/secofs_ufs_nowcast_00.*.out
#   STAGE_SUMMARY stage=nowcast ofs=secofs_ufs status=PASS runtime_s=...
```
Always check `status=PASS`; the job exit code is not reliable. Model progress: `grep "TIME STEP" $DATA/outputs/mirror.out | tail -1` (180 steps for the 6 h nowcast, 1440 for the 48 h forecast, at dt 120 s). `KEEPDATA=YES` leaves `$DATA` in the work directory.

Prep log lines worth checking: the NWM river overlay line `(+ real-time NWM for 6/6 columns)`, and for the wave config `Wrote nest.ww3 from N boundary spectra` (the nowcast and forecast logs show `Staged: nest.ww3`). If the boundary spectra fail, wave prep degrades to wind sea only; `nest.ww3` is not a critical source.

Outputs in `COMOUT=<COMROOT>/nos/<RUN>.<PDY>/` (`<p>` = `<RUN>.t<cyc>z`):

| Path | Contents |
|---|---|
| `<p>.<PDY>.init.nowcast.nc`, `<p>.<PDY>.rst.nowcast.nc` | nowcast start state and nowcast-end restart (next cycle's seed) |
| `<p>.restart_outputs/`, `<p>.forecast_outputs/` | raw SCHISM outputs of the nowcast and forecast |
| `<p>.<PDY>.stations.{nowcast,forecast}.nc` | station time series (430 stations) |
| `<p>.<PDY>.stations.mllw.{nowcast,forecast}.nc` | MLLW-referenced water level at gauges with a published datum |
| `<p>.<PDY>.field2d.*.nc` | 2D slab stacks (`slab2d`) |
| `<p>.wave_restart/` | WW3 and CMEPS restarts (wave config) |
| `<p>.nest.ww3` | wave boundary file (wave config) |
| `<p>.<PDY>.inputs.<stage>.json`, `<p>.<PDY>.outputs.post.json` | input and output manifests |

Post products are set in the yaml: `stations_nc`, `stations_mllw`, `fields_nc` (split only, not published) and `slab2d`. The post log lists what was written.

## 6. Timing

Measured on WCOSS2 (stage runtime, seconds):

| Config and date | prep | nowcast | forecast | post |
|---|---|---|---|---|
| `secofs_ufs`, May 2026, new executable (6 h, 48 h) | not captured | 973 | 2874 | not captured |
| `secofs_ufs_ww3`, cycle 20260820 12z (24 h, 48 h), leg runtimes | not captured | about 4700 | about 7900 | not captured |

Other references:
- WCOSS2 `secofs_ufs` post with the full product suite took 33:11 on the 20260728 cycle. Prep takes about 30 minutes. The wave config's operational prep took 31 to 80 minutes (launcher comment).
- A 6 h wave nowcast took 1930 to 2134 s in the August bring-up, before the 24 h cadence.
- Hercules `secofs_ufs`, Jenkins build 5 on 2026-08-29 (PR #188): prep 27 min 36 s, nowcast 13 min 45 s, forecast 43 min 14 s, post 1 min 12 s, about 1 h 29 min in total.

## 7. Validation against operations

All comparisons are against pre-operational or operational SECOFS (standalone SCHISM, sflux forcing). Numbers are from run records, not from tests in this repository.

`secofs_ufs`, cycle 20260804 00z, WCOSS2, 430 stations index-matched:

| | Water level | Wind |
|---|---|---|
| Forecast | bias +3.5 mm, RMSE 2.6 cm, median r 0.9989, 426 of 430 stations under 5 cm | RMSE 0.23 m/s |
| Nowcast | bias -2.3 cm, RMSE 3.8 cm, median r 0.9999 | RMSE 0.32 m/s |

- The earlier acceptance cycle, 20260728 12z, gave a water-level RMSE of 4.3 cm and wind r 0.998. That run was made after the DATM mesh fix (PR #152, 2026-07-29).
- The only station group above 5 cm in 20260804 was the Savannah River head (about 25 cm high). The cause was a constant river climatology on the Savannah flow boundary. Real-time NWM overlay (nos-utils PR #49, plus a one-reach `secofs_ufs.nwm.reach.dat`) cut the discharge bias to -1.4% against USGS 02198500 on 2026-08-09, and the head bias to about 10.7 cm (was 28 cm). A residual head difference grows over the forecast (DATM versus sflux heat flux and forecast discharge).
- Prep against operations (20260607 00z): `bctides.in` byte-identical.

`secofs_ufs_ww3`, cycle 20260820 12z (first operational cycle), 72 h record:
- Tides phase-correct: Trident r 0.981, Fernandina 0.949, Charleston 0.986.
- Against CO-OPS observations at three gauges the wave-coupled run ties operations (Trident r 0.977, 6.7 cm, versus 0.982, 6.2 cm).
- 57-gauge census: 4 closer to observations than operations, 45 tied, 8 farther; median absolute difference 2.1 mm. Only about 28 h of the window was scored, because observations were still arriving (as of 2026-08-21).
- Waves, 7 buoys with mesh coverage: shelf close to unbiased (Frying Pan 1.02 times observed Hs, RMSE 0.10 m; Edisto 0.97; Grays Reef 0.88); Gulf weaker (West Tampa 1.39, RMSE 0.31 m).
- Warm start (PR #183): mean buoy Hs RMSE 0.178 to 0.111 m over four warm cycles; water level moved by under 1 mm in network median.

## 8. Known limitations

- **HRRR winds are rotated twice** in the DATM path of `secofs_ufs` and `secofs_ufs_ww3` (`hrrr.py` and `blender.py` in nos-utils), an extra 6 to 21 degrees over the SECOFS domain. Wind speed is unaffected. Confirmed 2026-10-03; nos-utils (pin `aef8702`) still keeps the legacy behavior for SECOFS (`datm_rotate_hrrr_winds` defaults to true; only STOFS-3D-ATL coupled turns it off). It needs its own change and a wind-direction check before it is deployed to SECOFS.
- **Wave flicker.** `secofs_ufs_ww3` shows isolated, bounded Hs spikes at marginal nodes (Georgia Bight, Puerto Rico and the Virgin Islands), 3.5 to 5.8 m against a p99.9 of 1.3 to 1.7 m on 20260820. The wave solver's scrub logs count them. The cause is under study; do not publish Hs from those areas without checking.
- **Cold-start wave spin-up.** From zero the waves need 8 to 16 h; a cold start costs about 37% in buoy Hs RMSE. This is why the nowcast is 24 h and why warm start is on. A first cycle, or a restart that fails the guards, spins up again. A `warm_start_max_hs` (25 m) guard rejects a poisoned wave restart.
- **No operational wave product** exists to compare with; wave skill is judged against buoys only.
- **Water level near the Upper Chesapeake and Potomac** differed from operations by several centimeters in two independent wave-config cycles (as of 2026-08-21); the cause is not established.
- The SCHISM `ifltype=5` open boundary clamps the subtidal boundary velocity to zero, in operations and in the UFS runs. It is a known open question.
- Time labels of some nowcast products are one day late (open on 4ac0f15). The nowcast start is built as PDY plus ((cyc - nowcast length) mod 24) h with no day rollback (`stages/post.py`, used for the time units in `schism_combine_outputs.py`). The wave 12z 24 h nowcast is stamped PDY 12z instead of PDY-1 12z, and the `secofs_ufs` 00z nowcast PDY 18z instead of PDY-1 18z. The values are correct.
- The WCOSS2 SECOFS cards set `COMROOT` and paths directly (no `qsub -v` override for `COMROOT`); use `COMOUT` overrides or edit the cards for a separate tree.
- The wave config is WCOSS2 only; Hercules has no wave cards or executable.
- No ecFlow cards (`ecf/` is empty). Cron plus the launchers is the cycling mechanism.
- The wave executable's patches are kept outside the repository.

## 9. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Nowcast: `requires hotstart.nc but no source was found` | No init file. Seed it (section 2). |
| Prep fails with a `HotstartStagingError` about format | A seed in COMOUT is not NETCDF4_CLASSIC. `nccopy -k 'netCDF-4 classic model'`. |
| Prep warns the restart is N h before or after the anchor | Cycles were skipped or repeated. Run the missing cycles, or accept the relabel. |
| `PARMETIS_RETRY: ... resubmitting` in a log | Normal blind retry (section 3.3). Follow the new job id. |
| `PARMETIS_RETRY: max retries (8) exhausted` | Eight crashes in a row. Check that the log has `Staged partition.prop` and that `exec/fv3_coastalS.exe` is the NO_PARMETIS build. With that build a missing `partition.prop` aborts SCHISM at startup; it does not fall back to ParMETIS. |
| Launcher says `FAIL ... TIMEOUT` but the job is alive | The timeout is the card walltime plus headroom. Read the job's own log. |
| Manual retry of a 06, 12 or 18 z cycle ran as 00 z | `CYC` was lowercase or missing in `qsub -v`. Pass `CYC=<cycle>`. |
| A job exited 0 but the stage failed | Check `STAGE_SUMMARY ... status=PASS`. |
| Jobs run another package's code | The cards fix `PACKAGEROOT` (section 3.1). Check that `$LOGNAME/packages/nos-workflow` is the clone you mean. |
| Wave nowcast aborts before launch with a PET layout message | Stale nos-utils pin (3-component `ufs.configure` patcher). Update the submodule. |
| Wave prep: `ww3_bound` not found or `nest.ww3` missing | Install `exec/ww3_bound`; stage `secofs_ufs.mod_def.ww3` and `secofs_ufs.ww3_bound_points.list`. Prep continues with wind sea only. |
| Wave nowcast runs cold although warm start is on | No usable `wave_restart` within the search window. Look for the warm-start line in the nowcast log. |
| Forecast stage: partial wave restart archive error | A crashed nowcast left a partial set. Re-run the nowcast. |
| MPI errors "OFI is failing to make progress" at high ranks | The wave cards set the `FI_OFI_RXM_*` sizes; do not remove them. |
| Hercules prep: `wgrib2 not found` or missing Python module | Load `nos_hercules.intel` and activate the venv created with that stack's python. |
| Hercules run uses the WCOSS2 profile (PPN 120) | `NOS_MACHINE=hercules` is set by the cards; do not unset it. |
| Hercules start hangs after `mnei, mnei_p` | ParMETIS at 2794 ranks. Rebuild with `NO_PARMETIS=ON` and stage `partition.prop`. |
| Inputs for an old PDY are gone | Operational GFS keeps about two days on WCOSS2 (as of 2026-08). Re-run recent cycles, or stage public files on Hercules. |
| Work directories fill ptmp | `KEEPDATA=YES`. Run `pbs/clean_work.sh`. |
