# Running nos-workflow under ecFlow on WCOSS2

Applies to nos-workflow `develop` 4119cbe (2026-10-20). Update this guide in the same PR as any change to `ecf/` or to the cards and launchers whose resources it copies. The suite has been run only in a container (ecFlow 5.6.0, SLURM standing in for PBS, stub J-jobs). It has not run on a WCOSS2 ecFlow server; section 8 lists what that leaves open.

## 1. What you are running

One ecFlow suite, `nos_workflow`, with one family per system. It runs the same four stages the PBS cards run, as ecFlow tasks, and does what the cron entries and launchers do now: start each cycle at its time and chain the stages.

| Family | Config | Cycles (UTC) | Prep starts at | Nodes (nowcast / forecast) | Retries |
|---|---|---|---|---|---|
| `secofs_ufs` | `parm/systems/secofs_ufs.yaml` | 00 06 12 18 | 02:15 08:15 14:15 20:15 | 25 | 2 tries |
| `secofs_ufs_ww3` | `secofs_ufs_ww3.yaml` | 12 | 18:15 | 46 | 2 tries |
| `stofs_3d_atl_ufs` | `stofs_3d_atl_ufs.yaml` (coupled) | 12 | 18:15 | 42 | 2 tries |
| `stofs_3d_atl_ufs_standalone` | `stofs_3d_atl_ufs_standalone.yaml` | 12 | 18:15 | 41 | 1 try |
| `stofs_2d_glo` | `stofs_2d_glo.yaml` | 00 06 12 18 | 04:15 10:15 16:15 22:15 | 32 | 1 try |

The SECOFS start times are those of the crontab in `docs/secofs_run_guide.md` (section 3.4); the test `test_ecflow_suite.py` reads them from that guide. The ATL start time is a choice (no cron exists for ATL): GFS 12z and HRRR must be in. The 2D times are cycle + 4 h 15 min, after GFS f180 is complete.

Resources, modules and environment copy the cards, and for `stofs_2d_glo` the four-job shape of `pbs/stofs_2d_glo/launch_stofs_2d_glo.sh` (prep 0:50 on one prepost core, nowcast 0:50, forecast 2:00, post 3:10 on 8 x 32 cores; post runs `JNOS_POST` with the post segments). The test compares them with the cards and the launcher, so a card change that is not copied here fails it.

Every task: `prep`, then `nowcast`, then `forecast`, then `post`. Prep of a cycle also waits for the nowcast of the previous cycle of the same day (SECOFS and 2D), because prep reads that restart. The next day of a system starts when every task of the day has completed, so a failed 18z post holds the next 00z (override in section 4).

## 2. Layout

```
ecf/defs/nos_workflow.def        the suite: variables, families, triggers
ecf/scripts/jnos_{prep,nowcast,forecast,post}.ecf
                                 four generic task scripts; the system comes from suite variables
ecf/include/
  head.h, envir-p1.h, tail.h     development stand-ins for the NCO headers
  nos_env.h                      identity (OFS, NET, RUN)
  nos_modules_<set>.h            prep, fv3, pschism, post, adcirc  (the module blocks of the cards)
  nos_paths.h                    after the modules: COMROOT, DATAROOT, DCOMROOT, PACKAGEROOT, OFS_CONFIG
  nos_env_<set>.h                schism, adcirc  (the COMIN paths of the cards)
  nos_run_stage.h                runs the J-job and gates on its STAGE_SUMMARY
```

Tree in the server: `/nos_workflow/<system>/day/<cycle>/jnos_<stage>`. The family `day` holds `repeat date PDY`; the system family above it holds `defstatus suspended`. A defstatus is applied again each time its own node is requeued, so on the repeating family it would suspend every new day.

Differences between systems are suite variables, set per system family: `OFS`, `OFS_YAML` (the yaml name; the standalone variant keeps the coupled `OFS` because that sets the fix paths), `COMROOT`, `<STAGE>_SELECT`, `<STAGE>_PLACE`, `<STAGE>_WALLTIME`, `PREP_MODSET` / `RUN_MODSET` / `POST_MODSET` (which `nos_modules_<set>.h`), `ENVSET`, `PREP_ENV` / `RUN_ENV` (lists of `NAME=value` to export), and for 2D the ADCIRC segments and streams.

## 3. Before loading

Edit `ecf/defs/nos_workflow.def` for your account. These are the lines that need it:

| Variable | What |
|---|---|
| `PACKAGEHOME` | your clone, named `nos-workflow` (the J-jobs and cards assume the name) |
| `ECF_INCLUDE` | the same path plus `/ecf/include`. ecFlow does not expand variables in this one, so the path is written twice |
| `COMROOT`, `DATAROOT` | where COMOUT and the work directories go. Defaults are the cards' (`/lfs/h1/nos/ptmp/$LOGNAME/com`, `.../work/<OFS>`); the standalone family has `.../com_atl_sa` |
| `ecflow_ver` | the `ecflow` module version. It is a placeholder (`5.6.0`): confirm with `module avail ecflow`. Jobs load it again after each module block |
| `ECF_JOB_CMD`, `ECF_KILL_CMD`, `ECF_STATUS_CMD` | PBS: `qsub -o %ECF_JOBOUT% %ECF_JOB%`, `qdel %ECF_RID%`, `qstat -f %ECF_RID%`. Without them ecFlow would run the job file on the server host |
| `QUEUE`, `PROJ`, `PROJENVIR` | `dev`, `ESTOFS`, `DEV`: the cards' `-q dev -A ESTOFS-DEV` |
| `repeat date PDY <first> <last>` | in each system's `day` family. `<first>` is the first PDY to run |
| `DCOMROOT` | the ops dcom for SECOFS and ATL, as their cards. The 2D family leaves it empty, so `prod_envir`'s value stands, as in the 2D card without an override; set it on the 2D family to change that |
| `STOFS_RUNVER` | standalone ATL and 2D: the ops `stofs.v3.1.5/versions/run.ver` that supplies the module versions |

Optional variables, empty by default and exported when set: `NOS_POST_PRODUCTS`, `NOS_POST_MAX_WORKERS`, `NOS_PROFILES_OUTSIDE`, `POST_FIELDS_DEFLATE`, `NOS_ARCHIVE_FIELDS`, `NOS_COMBINE_OUTPUTS_SCRIPT` (post, as the launchers forward them), `ADCIRC_MODULE_PATH`, `ADCIRC_EXEC_DIR` (2D). Set one with `ecflow_client --alter=add variable NAME value /nos_workflow/<system>`.

`KEEPDATA` is `YES` except for 2D (`NO`, as its launcher: a run directory is about 150 GB). `pbs/clean_work.sh` still has to run from cron for the `YES` systems; the work directories keep the card names (`<stem>_<stage>_<cycle>_dev.<jobid>`), which is what it matches.

## 4. Load, run, steer

You need an ecFlow server and its address. Start your own from the module (`ecflow_start.sh -p <port>`) or use the one NCO gives you; this guide does not know which WCOSS2 will provide.

```bash
module load ecflow/<ecflow_ver>
export ECF_HOST=<server host> ECF_PORT=<port>
ecflow_client --ping
ecflow_client --load=$PWD/ecf/defs/nos_workflow.def      # from the clone root; refuses a suite of the same name unless "force" is added
ecflow_client --begin=nos_workflow                       # nothing starts: every system is suspended
ecflow_client --resume=/nos_workflow/stofs_3d_atl_ufs    # start one system
ecflow_client --suspend=/nos_workflow/stofs_3d_atl_ufs   # stop submitting; running jobs finish
```

Look at it with `ecflow_client --get=/nos_workflow/secofs_ufs` (state tree) or `ecflow_client --query state /nos_workflow/secofs_ufs/day/12/jnos_nowcast`. Each completed task shows `status=PASS runtime_s=...` in its `summary` label. The job output of a try is `<ECF_HOME>/nos_workflow/<system>/day/<cycle>/jnos_<stage>.<try>`; ECF_HOME is the server directory unless you set it.

| To | Command |
|---|---|
| set the PDY of a system | `ecflow_client --alter=change repeat 20261022 /nos_workflow/secofs_ufs/day` |
| rerun a task after fixing the cause | `ecflow_client --requeue=/nos_workflow/secofs_ufs/day/12/jnos_nowcast` |
| rerun all aborted tasks of a cycle | `ecflow_client --requeue=abort /nos_workflow/secofs_ufs/day/12` |
| let a cycle go on without a task | `ecflow_client --force=complete /nos_workflow/secofs_ufs/day/18/jnos_post` |
| change a variable, for example a walltime | `ecflow_client --alter=change variable NOWCAST_WALLTIME 02:00:00 /nos_workflow/secofs_ufs` |
| reload an edited def | `ecflow_client --load=<def> force`, then `--begin=nos_workflow` and resume the systems again (the reload resets the state of the suite) |

Do not requeue a `day` family: a requeue resets the repeat to its first value. A job that was queued before a `git pull` of the clone runs the new scripts, as with the cards.

## 5. First cycle of a system

The suite starts nothing by itself. Seed the first cycle as the system's guide says, then set the PDY and resume:
- SECOFS and wave: `docs/secofs_run_guide.md`, section 2, "First cycle versus later cycles" (an `init.nowcast.nc` in COMOUT, NETCDF4_CLASSIC).
- ATL, both variants: `docs/stofs_3d_atl_run_guide.md`, sections 2 and 3.2 (restart and the previous day's `staout_1`, `avg_bias`).
- 2D: `docs/stofs_2d_glo_run_guide.md`, sections 2.5 and 2.6.

The 2D cold start is the segment lists and the walltimes of its first cycle, as `COLDSTART=YES` does in its launcher. Before resuming, and only for that first cycle:
```bash
ecflow_client --alter=change variable PREP_SEGMENT    "adcprep ncst fcst" /nos_workflow/stofs_2d_glo
ecflow_client --alter=change variable PREP_WALLTIME   3:50:00            /nos_workflow/stofs_2d_glo
ecflow_client --alter=change variable NOWCAST_SEGMENT "spinup ncst"      /nos_workflow/stofs_2d_glo
ecflow_client --alter=change variable NOWCAST_WALLTIME 1:50:00           /nos_workflow/stofs_2d_glo
```
After that cycle's nowcast has completed, change the four back to `ncst fcst`, `0:50:00`, `ncst`, `0:50:00`. The variables are on the family, so they apply to every cycle until changed back. Do not set `COLDSTART` for 2D.

## 6. How success and retries work

A task completes only when its J-job exits 0 and its output has `STAGE_SUMMARY stage=<stage> ofs=<OFS> status=PASS`. The JNOS scripts exit 0 even when the stage fails, so the summary is the gate; the cards' ATL and 2D tails check the same line. Anything else aborts the task: a non-zero exit, no summary, `status=FAIL`, or a failed module load. An abort that happens after a module purge still reaches the server (the error trap loads `ecflow` again).

`ECF_TRIES 2` on nowcast and forecast of `secofs_ufs`, `secofs_ufs_ww3` and `stofs_3d_atl_ufs` replaces the cards' blind ParMETIS retry (which `qsub`s itself up to 8 times on a `partition_hgrid` signature). It is blind: ecFlow retries any abort, not only that one, and a retry is a new PBS job on 25 to 46 nodes. The crash is dormant with the `NO_PARMETIS` builds (`docs/secofs_run_guide.md`, section 3.3). Every other task has 1 try. Change it with `ecflow_client --alter=change variable ECF_TRIES 1 /nos_workflow/<system>/day/<cycle>/jnos_nowcast`.

Prep starts when the UTC clock has passed the start time of its PDY. The condition is a trigger on `ECF_DATE` and `TIME`, not a `today` or `time` attribute: after a requeue `today` is already free if its time has passed, so a day that ended early would start the next cycle at once, and `time` would wait a full day after a late finish. With a past PDY the condition is open, so a repeat started on an old date runs the days one after the other (a catch-up, limited by the input data that still exists).

## 7. Testing without disturbing the SECOFS cron

The cron launchers use `/lfs/h1/nos/ptmp/$LOGNAME/com`, `.../work/secofs_ufs` and their own clone. To try the suite beside them:
1. A separate clone, for example `/lfs/h1/nos/estofs/noscrub/$LOGNAME/packages_ecf/nos-workflow`, with the same fix files and executables (symlinks are fine).
2. In the def: `PACKAGEHOME` and `ECF_INCLUDE` to that clone, and in the suite variables `COMROOT` to `/lfs/h1/nos/ptmp/$LOGNAME/ecf_test/com` and `DATAROOT` to `/lfs/h1/nos/ptmp/$LOGNAME/ecf_test/work/%OFS%`. The standalone family sets its own `COMROOT`; change it too.
3. Seed `ecf_test/com` for the system you try (section 5), since prep reads the previous restart from COMROOT.
4. Use another ecFlow port than anyone else, and resume one system only.

Anything outside the suite that writes to the shared COMROOT, like the launchers, stays as it is.

## 8. Limits

- Not run on a WCOSS2 ecFlow server. In a container (ecFlow 5.6.0, SLURM as the batch system through a PBS stand-in, a `module` stand-in, stub J-jobs) these were checked: the real def and the generated job of all 44 tasks, a full two-day run of the five families, the PDY advance, prep waiting for the previous nowcast, the PASS gate, retries, aborts and the environment each stub J-job saw.
- Not verified: `ecflow_ver`; the real `module` behaviour (that `module load ecflow` after the purge keeps the model modules intact); the PBS job command and the job output location; the ecFlow server and its owner; the UTC clock of the server (the start times assume UTC).
- The J-jobs were stubs, so no model ran. The suite changes nothing in the J-jobs, cards or launchers.
- The ATL and 2D cards do not re-export `PACKAGEROOT` from the clone after their module block; the suite does, for every system.
- Not in the suite: the per-job `rpt/` logs (the job output is the log), `clean_work.sh`, the warm-start experiment launcher, the Hercules cards, STOFS-3D-AK, and the cards' 2D preflight of fix files and `adcprep`/`padcirc` (a missing file fails in the J-job with a FAIL summary).
- A stuck or failed stage holds that system's next day. Use `--force=complete` on the task, or `--alter=change repeat` to skip a day.

## 9. Troubleshooting

| Symptom | Likely cause |
|---|---|
| Task `aborted`, job output ends `ended without STAGE_SUMMARY` | The J-job failed before its summary; read the output above that line |
| Task `aborted` at once, `module` error | Module block: a version missing from `run.ver`, or `STOFS_RUNVER` unreadable |
| Task stays `active` after the job is gone | The job could not reach the server (host or port in the job file) or died before the trap; `ecflow_client --force=aborted` it and look at the PBS output |
| Prep `queued` although the time has passed | A prep waits for the previous cycle's nowcast; check that task, and that the server clock is UTC |
| Jobs run on the server host | `ECF_JOB_CMD` is the default; set the PBS commands |
| `Mismatched ecfmicro(%)` at load | A script has a lone `%`; ecFlow needs `%%` or another construct |
