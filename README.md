# nos-workflow

nos-workflow runs NOS coastal forecast systems as a prep -> nowcast -> forecast -> post cycle on WCOSS2 (PBS) and Hercules (Slurm), in the NCO package layout (`jobs/`, `scripts/`, `ush/`, `parm/`, `fix/`, `exec/`). The stages are Python (`ush/python/nos_workflow`); forcing generation and post products come from the `nos-utils` submodule. Model engines are SCHISM, run standalone or coupled to a CDEPS data atmosphere (and optionally WAVEWATCH III) through UFS-Coastal, and ADCIRC.

These are development configurations run by their maintainers, not NCO operational jobs; there are no ecFlow cards. `develop` is the default and integration branch. Applies to `develop` as of 2026-10-19 (`03f0f91`).

## Supported systems

| System (OFS name) | Model, ranks | Nowcast / forecast | Machines | Launcher | Guide |
|---|---|---|---|---|---|
| SECOFS (`secofs_ufs`) | DATM + SCHISM through UFS-Coastal, 2914 | 6 h / 48 h; 00, 06, 12, 18z | WCOSS2, Hercules | `pbs/launch_secofs_ufs.sh <CYC>` (cron driven; polls `STAGE_SUMMARY`); Hercules: `slurm/secofs_ufs/` cards | launcher header |
| SECOFS with waves (`secofs_ufs_ww3`) | DATM + SCHISM + WAVEWATCH III through UFS-Coastal (CMEPS), 5520 | 24 h / 48 h | WCOSS2 | `pbs/secofs_ufs_ww3/launch_secofs_ufs_ww3.sh <CYC>` | launcher header |
| STOFS-3D-ATL standalone (`stofs_3d_atl_ufs` + `stofs_3d_atl_ufs_standalone.yaml` overlay) | SCHISM 5.14 `pschism`, operational v3.1.5 source and build flags, 4920 | 24 h / 96 h; 12z | WCOSS2, Hercules | `pbs/stofs_3d_atl_ufs_standalone/launch_stofs_standalone.sh <PDY> [CYC]`; Hercules: `slurm/stofs_3d_atl_ufs_standalone/` cards | [docs/stofs_3d_atl_run_guide.md](docs/stofs_3d_atl_run_guide.md) |
| STOFS-3D-ATL coupled (`stofs_3d_atl_ufs`) | DATM + CMEPS + SCHISM (`fv3_stofs_3d_atl.exe`), 5032 | 24 h / 96 h; 12z | WCOSS2, Hercules | `pbs/stofs_3d_atl_ufs/launch_stofs_3d_atl_ufs.sh <PDY> [CYC]`; Hercules: `slurm/stofs_3d_atl_ufs/` cards | same guide |
| STOFS-3D-AK (`stofs_3d_ak_ufs`) | DATM + SCHISM through UFS-Coastal, 2513 | 24 h / 48 h; 12z default | WCOSS2 | `pbs/stofs_3d_ak_ufs/launch_stofs_3d_ak_ufs.sh <PDY> [CYC]` | launcher header |
| STOFS-2D-Global (`stofs_2d_glo`) | ADCIRC v56.1 in the operational stofs.v3.1.5 layout: tide and surf streams, ops fort.15 templates, Fortran tide_fac, ops post chain; 4064 compute ranks (surf adds 5 writers, one per output file) | 6 h nowcast and one 180 h forecast per stream; 00, 06, 12, 18z; four jobs: prep, nowcast, forecast, post | WCOSS2 (all post steps except GEMPAK); Hercules (post is ncdiff and ncrcat only) | `pbs/stofs_2d_glo/launch_stofs_2d_glo.sh <PDY> <CYC>`; Hercules: `slurm/stofs_2d_glo/launch_stofs_2d_glo.sh <PDY> <CYC>` (the four jobs are chained with afterok) | [docs/stofs_2d_glo_run_guide.md](docs/stofs_2d_glo_run_guide.md) (jobs, options, products, start from the ops state) |

2D-Global has no post card: the post job runs on the prep card (`jnos_prep_00`) with the post steps selected. Ops is the only 2D-Global mode: `ADCIRC_MODE=ops` is optional (unset means ops), and any other value stops the WCOSS2 launcher and the cards.

Other names printed by `python3 -m nos_workflow list` are placeholders; see Known gaps.

## Machines

| | WCOSS2 (Cactus / Dogwood) | Hercules (RDHPCS) |
|---|---|---|
| Scheduler, cards | PBS; `pbs/<system>/jnos_<stage>_00.pbs` (the `secofs_ufs` cards sit at the `pbs/` root) | Slurm; `slurm/<system>/jnos_<stage>_00.sh` |
| Module stack | `versions/run.ver` (python 3.8.6); the UFS run cards load `modulefiles/modules.fv3.lua`; the 2D-Global cards and the ATL standalone run cards also source the operational package's `run.ver` (`STOFS_RUNVER`) | `versions/run.hercules.ver` and `modulefiles/nos_hercules.intel.lua` (spack-stack 1.9.2, oneAPI 2024.2.1, python 3.11.7), plus a python venv (`NOS_VENV`, default `$VENV_PATH` or `~/nos-venv`; packages listed in the 2D-Global run guide, section 3.1) |
| Inputs | operational `com` and `dcom` trees | staged with `ush/stage_comin.py` (GFS, HRRR, RTOFS, NWM from public buckets) and `tools/hercules_2d_glo_stage_forcing.sh` (2D-Global ops forcing); ATL also needs a dcom case bundle from the maintainers and first-cycle seeds (`tools/hercules_atl_seed_*.sh`) |
| Executables | staged into `exec/`, or the ops adcirc module for 2D-Global `padcirc`/`adcprep`, as the run guide says | built with `sorc/build_hercules.sh` (SECOFS `fv3_coastalS.exe`) and `tools/build_*_hercules.sh` (ATL pschism and coupled exe, tide_fac, ADCIRC) |
| Profile | `parm/machines/wcoss2.yaml` (default) | `parm/machines/hercules.yaml`; the cards export `NOS_MACHINE=hercules` |

## Quick start

```bash
git clone https://github.com/mansurjisan/nos-workflow.git && cd nos-workflow   # keep the name: the cards run $PACKAGEROOT/nos-workflow
git submodule update --init ush/python/nos-utils     # pinned to a commit; the ATL and 2D-Global Hercules cards refuse a mismatched checkout
tools/fetch_<system>_fix.sh                           # stofs_3d_atl, stofs_3d_ak, stofs_2d_glo; SECOFS fix files are copied from an existing package
mkdir -p exec                                        # a fresh clone has no exec/
# executables: the run guide (ATL, 2D-Global); SECOFS and AK run exec/fv3_coastalS.exe, SECOFS with waves exec/fv3_coastalSW.exe
<launcher from the table> <PDY> <CYC>                 # the SECOFS launchers take <CYC> only (PDY defaults to today UTC); on Hercules submit the slurm/<system>/ cards, or the 2D-Global Slurm launcher (`slurm/stofs_2d_glo/launch_stofs_2d_glo.sh`)
```

- WCOSS2: the SECOFS, SECOFS with waves and STOFS-3D-AK cards hard-code `PACKAGEROOT=/lfs/h1/nos/estofs/noscrub/$LOGNAME/packages` and `COMROOT=/lfs/h1/nos/ptmp/$LOGNAME/com`; clone there or edit the cards. The ATL and 2D-Global launchers pass `PACKAGEROOT` and `HOMEnos` from the clone they run from and forward `COMROOT_SA`, `COMROOT_UFS` or `COMROOT_2DGLO`. Every WCOSS2 card charges `ESTOFS-DEV`.
- Hercules: export `PACKAGEROOT` (the clone's parent; the ATL and 2D-Global cards require it, the SECOFS cards default it) and `NOS_PTMP` first; the card defaults are the maintainer's directories.
- A stage that finishes writes `STAGE_SUMMARY ... status=PASS` or `status=FAIL` to its log; treat a job whose log has no `status=PASS` as failed, whatever the scheduler reports.
- First cycle: the launchers do not create the initial state.
  - SCHISM systems (SECOFS, SECOFS with waves, AK, ATL) have no cold start: nowcast fails on a fresh COMROOT unless `$COMOUT/<RUN>.t<cyc>z.<PDY>.init.nowcast.nc` exists (the `stage_hotstart` input; `tools/make_cold_start_hotstart.py` writes a rest-state one for a new domain). Later cycles use the previous nowcast restart.
  - STOFS-3D-ATL needs the operational restart converted to NETCDF4_CLASSIC as that file, plus the dynamic-adjustment seeds, on both machines (ATL guide, sections 3.2 and 4.2; on Hercules `tools/hercules_atl_seed_*.sh`).
  - STOFS-2D-Global: the WCOSS2 launcher defaults to a warm start (the previous cycle's chain files in COMOUT), so a first cycle needs `COLDSTART=YES` or the ops state (2D-Global guide, section 2.6). The Hercules launcher defaults to `COLD=1`, a cold start; later cycles need `COLD=0` (sections 3.3 and 3.4).
- Logs: one `.out`/`.err` pair per job, named after its card and job id, under `/lfs/h1/nos/ptmp/$LOGNAME/rpt/<OFS>/` (WCOSS2) or `$NOS_PTMP/$LOGNAME/rpt/<OFS>/` (Hercules); Slurm also writes nearly empty `%x.%j.out`/`.err` files in the submit directory. Outputs: `${COMROOT}/nos/<RUN>.<PDY>/`.

## How a cycle runs

```
launcher (pbs/ or slurm/)
  -> job card jnos_<stage>_00       scheduler header, modules, log redirect, exports (OFS, CYC, COMROOT, ...)
  -> jobs/JNOS_<STAGE>              NCO variables (NET, RUN, PDY, cyc, DATA, COMOUT); yaml -> environment
                                    through ush/nos_config.sh; framework chosen from the OFS name
  -> scripts/exnos_<stage>.sh       PYTHONPATH, then python3 -m nos_workflow run <stage> --ofs $OFS
     (scripts/exnos_adcirc.sh <stage> for ADCIRC)
  -> nos_workflow.stages.<stage>    dispatch by framework to runners/schism_ufs or runners/adcirc
  -> nos_utils                      forcing (GFS, HRRR, NWM, RTOFS, tides, nudging, ADT, St. Lawrence,
                                    DATM streams, ADCIRC met and tides, WW3 boundary) and post products
```

For SCHISM the MPI launch and the hotstart combine stay in shell (`ush/nos_run.sh`, called from the Python runner) because the module environment does not survive a Python subprocess. The ADCIRC runner builds its command lines from the machine profile and does not source `nos_run.sh`. `python3 -m nos_workflow.machine card|mpi` renders the scheduler header and the MPI launch line from the machine profile: `ush/nos_run.sh` takes its MPI line from it, the cards keep literal headers, and `ush/python/nos_workflow/tests/test_job_card_render.py` checks 14 WCOSS2 cards against the rendered output (SECOFS, ATL coupled and standalone, 2D-Global; not SECOFS with waves, AK or the ATL standalone post).

## Repository layout

```
nos-workflow/
├── jobs/            J-jobs: JNOS_PREP, JNOS_NOWCAST, JNOS_FORECAST, JNOS_POST
├── scripts/         ex-scripts: exnos_{prep,nowcast,forecast,post}.sh (SCHISM), exnos_adcirc.sh (ADCIRC)
├── pbs/             WCOSS2 cards and launchers; root = SECOFS, one subdirectory per other system
├── slurm/           Hercules cards (secofs_ufs, stofs_3d_atl_ufs[_standalone], stofs_2d_glo) and the 2D-Global launcher and status script
├── ush/
│   ├── nos_run.sh               SCHISM-UFS run library (MPI launch, hotstart combine)
│   ├── nos_config.sh            yaml -> environment loader used by the J-jobs
│   ├── stage_comin.py           stage GFS/HRRR/RTOFS/NWM from public buckets into a COMIN tree (Hercules)
│   ├── schism_combine_outputs.py
│   └── python/
│       ├── nos_workflow/        cli, stages, runners (schism_ufs, adcirc), descriptors, machine, post, utils, tests
│       └── nos-utils/           submodule: forcing processors and post products
├── parm/
│   ├── base/        model-family templates: adcirc, fvcom, roms, schism
│   ├── systems/     one yaml per system (`_base:` inheritance; stofs_3d_atl_ufs_standalone.yaml is an overlay)
│   └── machines/    wcoss2.yaml, hercules.yaml
├── fix/<ofs>/       tracked templates, param.nml files and small tables only; grids, partition.prop and
│                    river files are untracked (staged by tools/fetch_*_fix.sh); do not add them
├── exec/            executables (not tracked; absent in a fresh clone, so `mkdir -p exec`)
├── tools/           fix fetch, Hercules builds, forcing staging, seeds, cold-start hotstart, comparisons
├── versions/        run.ver (WCOSS2), run.hercules.ver, build.ver
├── modulefiles/     modules.fv3.lua (WCOSS2 UFS runtime), nos_hercules.intel.lua
├── sorc/            build_hercules.sh (SECOFS fv3_coastalS.exe)
├── docker/          SECOFS prep container used by CI
├── tests/           Docker-backed integration parity tests and golden manifests
├── docs/            run guides (ATL, 2D-Global, Hercules Jenkins)
├── .cicd/           Jenkins pipeline (Hercules), the stage template run_stage.sh and its scripts
├── .github/         Actions workflows, pull request template
└── ecf/             only .gitkeep (no ecFlow cards yet)
```

## Configuration

- `parm/base/<model>.yaml` holds the model-family defaults; `parm/systems/<ofs>.yaml` inherits one with `_base:` (a system yaml can also inherit another system, as `secofs_ufs_ww3` and `stofs_3d_atl_ufs_standalone` do).
- The J-jobs read `OFS_CONFIG` (default `parm/systems/${OFS}.yaml`); the ATL standalone cards point it at the overlay.
- `shell_mappings.variables` in the yaml is the export table. A non-empty variable already in the job environment wins over the yaml value, so `qsub -v` and `sbatch --export` overrides survive; the system identity exports (`OFS`, `OCEAN_MODEL`, ...) cannot be overridden.
- `parm/machines/<machine>.yaml` holds the scheduler, allocation and MPI launcher facts; `NOS_MACHINE` selects the profile (default `wcoss2`).

## Python package and CLI

`ush/python/nos_workflow` (`ush/python/bin/nos_uw` is a shell shim for `python3 -m nos_workflow`). From the repository root with `PYTHONPATH=ush/python:ush/python/nos-utils`:

```bash
python3 -m nos_workflow list                        # registered systems and stages
python3 -m nos_workflow stages stofs_2d_glo
python3 -m nos_workflow validate secofs_ufs         # yaml present; FIXofs and EXECnos are directories when set
python3 -m nos_workflow env --ofs secofs_ufs        # resolved export table (--json, --ctl, --section <name>)
python3 -m nos_workflow run prep --ofs secofs_ufs   # what the ex-scripts call; PDY and cyc from the environment or --pdy/--cyc
python3 -m nos_workflow.machine card --system secofs_ufs --stage prep   # scheduler header from parm/machines
python3 -m nos_workflow.machine mpi --ranks 2914                        # MPI launch line
```

`validate` checks `parm/systems/<ofs>.yaml` relative to the current directory, so run it from the repository root. `env` uses `--config`, then `OFS_CONFIG` (which wins over `--ofs`), then `parm/systems/<ofs>.yaml` under `HOMEnos`, `PACKAGEROOT` or the current directory.

nos-utils (`ush/python/nos-utils`) is a git submodule pinned to a commit. A change that needs both repositories lands in nos-utils first; a nos-workflow PR then bumps the submodule pointer.

## Tests

```bash
cd ush/python/nos_workflow
PYTHONPATH=$PWD/..:$PWD/../nos-utils python3 -m pytest -q                   # unit suite (needs pytest, netCDF4, numpy, pyyaml)
NOS_WORKFLOW_RUN_PARITY=1 PYTHONPATH=$PWD/..:$PWD/../nos-utils \
    python3 -m pytest -q tests/parity                                       # shell-vs-Python parity; the hotstart and
                                                                            # setup_paths cases skip unless this is set
                                                                            # on a machine with nos_run.sh's modules
cd ../../..
PYTHONPATH=ush/python:ush/python/nos-utils python3 -m pytest -q tests/integration   # Docker parity; the Docker cases skip
                                                                                    # without the staging dir (SECOFS_STAGING_DIR)
                                                                                    # and the nosofs/secofs-ufs image
cd ush/python/nos-utils && python3 -m pytest -q                              # nos-utils suite
```

## Continuous integration

- Jenkins on Hercules (`.cicd/Jenkinsfile`, agent `hercules-nos`) has two jobs from one Jenkinsfile. Bootstrap, Deploy, Environment Check and Stage Data run for every system; Prep, Nowcast, Forecast and Post are submitted through `.cicd/scripts/run_stage.sh` and gated on the card's `STAGE_SUMMARY`; Verify runs the system's own script.
  - `NOS/nos-workflow-secofs-hercules`: SECOFS, on a PR carrying the `hercules-nos-RT` label, on Build Now or on branch builds; it posts the `hercules-ci/cycle` status to GitHub. `hercules-ci.yml` dispatches it by hand.
  - `NOS/nos-workflow-atl-hercules`: STOFS-3D-ATL (standalone `stofs_3d_atl_ufs_standalone` and coupled `stofs_3d_atl_ufs`) and STOFS-2D-Global, from Build with Parameters on `develop` (`OFS`, `LEVEL=smoke|cycle|full`, `DATA_MODE=live|frozen`, `PDY`, `CYC`), normally against frozen datasets; the result is in the Jenkins build only.
  - Step-by-step use: [docs/hercules_jenkins_run_guide.md](docs/hercules_jenkins_run_guide.md); system details in section 10 of the ATL guide and section 5 of the 2D-Global guide.
- GitHub Actions: `stage_parity.yml` (golden-manifest checks and the nos_workflow unit suite on hosted runners; Docker parity on a self-hosted runner, opt-in through the `ENABLE_DOCKER_PARITY` repository variable) runs only when its paths change (the four SECOFS stage modules, `yaml_to_env.py`, nos-utils, the SECOFS ex-scripts, `ush/nos_run.sh`, `secofs_ufs.yaml`, `tests/integration`), so a PR that touches only `runners/adcirc`, cards or other yamls gets no unit-suite run there: run pytest locally. `ci-tier2-docker.yml` (SECOFS prep image) is path-filtered (`docker/`, `jobs/`, `scripts/`, `ush/`, `parm/`, ...) and also runs nightly. `r2o-check.yml` is an advisory NCO compliance lint; `hercules-ci.yml` is a manual dispatch of the SECOFS Jenkins job.

## Documentation

- [docs/stofs_3d_atl_run_guide.md](docs/stofs_3d_atl_run_guide.md): both ATL variants on WCOSS2 and Hercules, and the Jenkins job.
- [docs/stofs_2d_glo_run_guide.md](docs/stofs_2d_glo_run_guide.md): 2D-Global (ops mode) on WCOSS2 and Hercules, including a start from the ops state on Hercules (section 3.4), and the Jenkins job.
- [docs/hercules_jenkins_run_guide.md](docs/hercules_jenkins_run_guide.md): running, reading and extending the Hercules Jenkins builds for STOFS-3D-ATL and STOFS-2D-Global.
- SECOFS, SECOFS with waves and STOFS-3D-AK have no run guide: their launcher headers cover launching and cron, not fix files, executables (`exec/fv3_coastalS.exe`; `fv3_coastalSW.exe` with waves) or the first-cycle init file. Only `pbs/launch_secofs_ufs.sh` has a crontab example in its header; the AK launcher requires `<PDY>`.

Each guide states the `develop` date it applies to. A change to a system's cards, launchers, fetch, build or staging tools, or CI scripts updates its guide in the same PR.

## Contributing

PRs target `develop` and follow [.github/PULL_REQUEST_TEMPLATE.md](.github/PULL_REQUEST_TEMPLATE.md) (description, type, change characteristics, how tested, checklist). Do not edit a shared `FIXofs` while a run is cycling from it.

## Known gaps

- No ecFlow cards (`ecf/` holds only `.gitkeep`). Each launcher submits one cycle per call; the SECOFS, SECOFS with waves and STOFS-3D-AK launchers are written to be run from cron (only the SECOFS header has a crontab example).
- `cbofs`, `dbofs`, `ngofs2` (ROMS and FVCOM standalone) and `stofs_3d_atl` (legacy STOFS framework) are registered and listed by `python3 -m nos_workflow list`, but their prep is not implemented; they are placeholders.
- SECOFS and SECOFS with waves have no fix fetch tool; their fix files are copied from an existing package (CI seeds them from `SEED_SRC`).
- Per-system limitations are in section 8 of each run guide.
