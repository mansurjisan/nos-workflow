# ecFlow suite for nos-workflow

ecFlow definitions and task scripts that run the nos-workflow stages the way
NCO runs production systems on WCOSS2: an ecFlow task per stage, whose `.ecf`
script carries the PBS directives and calls the J-job.

```
ecf/
├── defs/nos_ufs_coastal.def   development suite: secofs_ufs (00/06/12/18),
│                              stofs_3d_atl_ufs (12), secofs_ufs_ww3 (suspended)
├── scripts/jnos_{prep,nowcast,forecast,post}.ecf
│                              one generic script per stage; the system comes
│                              from %OFS%, resources from %NODES%/%WALLTIME%
└── include/
    ├── nos_env.h              common environment (OFS, cyc, PDY, HOMEnos, COM/DATA roots)
    ├── nos_modules_prep.h     WCOSS2 modules for prep and post
    ├── nos_modules_model.h    hpc-stack modules (modules.fv3) for nowcast and forecast
    ├── nos_run_stage.h        runs the J-job and gates on STAGE_SUMMARY status=PASS
    └── head.h, tail.h, envir-p1.h
                               development stand-ins for the NCO headers
```

## How success is decided

A task completes only if the J-job exits 0 **and** its output contains

```
STAGE_SUMMARY stage=<stage> ofs=<OFS> status=PASS
```

The J-job exit code alone is not reliable after a model crash, so the summary
line is the contract (the same one the PBS launchers and Jenkins verify step
use). Nowcast and forecast tasks have `ECF_TRIES 3`, so ecFlow requeues them
after an abort; this replaces the `qsub` blind-retry in the development PBS
cards (ParMETIS partition crash, issue #98).

## Dependencies

Within a cycle: prep, then nowcast, then forecast, then post. Each nowcast
also waits for the previous cycle's nowcast, whose restart it reads. The 00z
nowcast's dependency on the previous day's 18z is not expressed across the
`PDY` repeat; cold start or a manual set-complete covers the first day.

## Using it in development

1. Edit the variables at the top of `defs/nos_ufs_coastal.def`
   (`PACKAGEROOT`, `ECF_FILES`, `ECF_INCLUDE`, `COMROOT`, `DATAROOT`,
   `QUEUE`, `PROJ`, `PROJENVIR`, and the `PDY` repeat start date).
2. `ecflow_client --load=ecf/defs/nos_ufs_coastal.def`
3. `ecflow_client --begin=nos_ufs_coastal`
4. Resume `secofs_ufs_ww3` when the wave configuration should run.

## In operations

NCO supplies its own `head.h`, `tail.h` and `envir-p1.h`; put NCO's include
directory before `ecf/include` in `ECF_INCLUDE` so those win. `PDY` then comes
from `setpdy.sh` in the J-jobs, and `COMROOT`/`DATAROOT` from `prod_envir`.
The production suite definition is NCO's; `defs/` here is a development
reference for the families, triggers and resources.

Resources and launch times mirror the development PBS cards in `pbs/` and the
cron schedule in `pbs/launch_secofs_ufs.sh`; update both together.

## Status

Not yet run on an ecFlow server. Job creation was checked offline: every task
preprocesses with all variables defined, every trigger path resolves, and
every generated job passes `bash -n`.
