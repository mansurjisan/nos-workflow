# Running nos-workflow under ecFlow on WCOSS2

Applies to nos-workflow `develop` 4119cbe (2026-10-20). Update this guide in the same PR as any change to `ecf/` or to the cards and launchers whose resources it copies. The suite has been run only in a container (ecFlow 5.6.0, SLURM standing in for PBS, stub J-jobs). It has not run on a WCOSS2 ecFlow server; section 8 lists what that leaves open.

## 1. What you are running

One ecFlow suite, `nos_workflow`, with one family per system. It runs the same four stages the PBS cards run, as ecFlow tasks, and does what the cron entries and launchers do now: start each cycle at its time and chain the stages.

| Family | Config | Cycles (UTC) | Prep starts at | Nodes (nowcast / forecast) | Tries |
|---|---|---|---|---|---|
| `secofs_ufs` | `parm/systems/secofs_ufs.yaml` | 00 06 12 18 | 02:15 08:15 14:15 20:15 | 25 | 2 on nowcast, forecast, post; 1 on prep |
| `secofs_ufs_ww3` | `secofs_ufs_ww3.yaml` | 12 | 18:15 | 46 | 2 on nowcast, forecast, post; 1 on prep |
| `stofs_3d_atl_ufs` | `stofs_3d_atl_ufs.yaml` (coupled) | 12 | 18:15 | 42 | 2 on nowcast, forecast, post; 1 on prep |
| `stofs_3d_atl_ufs_standalone` | `stofs_3d_atl_ufs_standalone.yaml` | 12 | 18:15 | 41 | 2 on post; 1 elsewhere |
| `stofs_2d_glo` | `stofs_2d_glo.yaml` | 00 06 12 18 | 05:00 11:00 17:00 23:00 | 32 | 1 |

The SECOFS start times are those of the crontab in `docs/secofs_run_guide.md` (section 3.4); the test `test_ecflow_suite.py` reads them from that guide. The ATL start time is a choice (no cron exists for ATL): GFS 12z and HRRR must be in. The 2D times are cycle + 5 h: when GFS f180 is complete is not verified (+4 h 15 min is a guess), and a late GFS aborts the 2D prep, so the gate leaves a margin.

Resources, modules and environment copy the cards, and for `stofs_2d_glo` the four-job shape of `pbs/stofs_2d_glo/launch_stofs_2d_glo.sh` (prep 0:50 on one prepost core, nowcast 0:50, forecast 2:00, post 3:10 on 8 x 32 cores; post runs `JNOS_POST` with the post segments). The test compares the resources (select, place, walltime) and the exports whose absence fails silently (`UFS_EXEC_NAME` of ww3, the `MPICH_*` and `FI_OFI_*` values, `COLDSTART=NO` and `NOS_ARCHIVE_MANIFEST` of ATL) with the cards and launchers. It does not compare the module sequences or the other variables: a change to those in a card has to be copied into `ecf/include` by hand.

Every task: `prep`, then `nowcast`, then `forecast`, then `post`. Prep of a cycle also waits for the nowcast of the previous cycle of the same day (SECOFS and 2D), because prep reads that restart. The next day of a system starts when every task of the day has completed, so a failed 18z post holds the next 00z. The suite needs someone watching it (section 6).

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
| `ecflow_ver` | the `ecflow` module version. It is a placeholder (`5.6.0`): confirm with `module avail ecflow`. Jobs load it again after each module block. If the version is unknown the job falls back to the default `ecflow` module, so a wrong version alone does not leave a task in `submitted` |
| `ECF_JOB_CMD`, `ECF_KILL_CMD`, `ECF_STATUS_CMD` | PBS: `qsub -o %ECF_JOBOUT% %ECF_JOB%`, `qdel %ECF_RID%`, `qstat -f %ECF_RID%`. Without them ecFlow would run the job file on the server host |
| `QUEUE`, `PROJ`, `PROJENVIR` | `dev`, `ESTOFS`, `DEV`: the cards' `-q dev -A ESTOFS-DEV` |
| `repeat date PDY <first> <last>` | in each system's `day` family. `<first>` is the first PDY to run, and a load always starts there: it will be in the past, so after every load, begin, reload or `day` requeue set the real PDY with `--alter=change repeat` before resuming (sections 4 and 5); a plain suspend and resume in the middle of a day needs no change |
| `DCOMROOT` | the ops dcom for SECOFS and ATL, as their cards. The 2D family leaves it empty, so `prod_envir`'s value stands, as in the 2D card without an override. Jobs load `prod_envir` with `envir` unset, as the cards do, so that value is `/lfs/h1/ops/prod/dcom`; set it on the 2D family to change it |
| `STOFS_RUNVER` | the run.ver that supplies the module versions. 2D: the ops `stofs.v3.1.5/versions/run.ver`, set in the def. Standalone ATL: not set, so it follows its card: `<parent of your clone>/IT-stofs.v2.1.0/versions/stofs_3d_atl/run.ver` if readable, else the ops file, else the job fails. Setting it on the standalone family overrides both. The job output prints the file it used |

Optional variables, empty by default and exported when set: `NOS_POST_PRODUCTS`, `NOS_POST_MAX_WORKERS`, `NOS_PROFILES_OUTSIDE`, `POST_FIELDS_DEFLATE`, `NOS_ARCHIVE_FIELDS`, `NOS_COMBINE_OUTPUTS_SCRIPT` (post, as the launchers forward them), `ADCIRC_MODULE_PATH`, `ADCIRC_EXEC_DIR` (2D). Set one with `ecflow_client --alter=add variable NAME value /nos_workflow/<system>`.

`KEEPDATA` is `YES`, as in the cards, except for 2D (`NO`, as its launcher: a run directory is about 150 GB), so the work directories of the other systems pile up until someone cleans them. `pbs/clean_work.sh` has to run from cron, and by default it cleans only `secofs_ufs` and `secofs_ufs_ww3` (the SECOFS cron line passes no names). To include the coupled ATL, name the runs: `clean_work.sh secofs_ufs secofs_ufs_ww3 stofs_3d_atl_ufs`. It never matches the standalone ATL, whose directories are `stofs_3d_atl_ufs_sa_<stage>_12_dev.<jobid>` in the same `work/stofs_3d_atl_ufs`: remove the old ones by hand (keep the last cycle's), or set `KEEPDATA` to `NO` on that family if nobody needs them after a run.

## 4. Load, run, steer

You need an ecFlow server and its address. Start your own from the module (`ecflow_start.sh -p <port>`) or use the one NCO gives you; this guide does not know which WCOSS2 will provide.

```bash
module load ecflow/<ecflow_ver>
export ECF_HOST=<server host> ECF_PORT=<port>
ecflow_client --ping
ecflow_client --load=$PWD/ecf/defs/nos_workflow.def      # from the clone root; refuses a suite of the same name unless "force" is added
ecflow_client --begin=nos_workflow                       # nothing starts: every system is suspended
ecflow_client --alter=change repeat 20261022 /nos_workflow/stofs_3d_atl_ufs/day   # the first PDY to run: the def holds an older date
ecflow_client --resume=/nos_workflow/stofs_3d_atl_ufs    # start one system
ecflow_client --suspend=/nos_workflow/stofs_3d_atl_ufs   # stop submitting; running jobs finish
```

Look at it with `ecflow_client --get=/nos_workflow/secofs_ufs` (state tree) or `ecflow_client --query state /nos_workflow/secofs_ufs/day/12/jnos_nowcast`. Each completed task shows `status=PASS runtime_s=...` in its `summary` label. The job output of a try is `<ECF_HOME>/nos_workflow/<system>/day/<cycle>/jnos_<stage>.<try>`; ECF_HOME is the server directory unless you set it.

| To | Command |
|---|---|
| set the PDY of a system | `ecflow_client --alter=change repeat 20261022 /nos_workflow/secofs_ufs/day` |
| rerun a task after fixing the cause | `ecflow_client --requeue=/nos_workflow/secofs_ufs/day/12/jnos_nowcast` |
| rerun all aborted tasks of a cycle | `ecflow_client --requeue=abort /nos_workflow/secofs_ufs/day/12` |
| let a cycle go on without a task, or the day advance past a failed one | `ecflow_client --force=complete /nos_workflow/secofs_ufs/day/18/jnos_post` on the failed node. When its later tasks never ran and should be skipped too: `ecflow_client --force=complete recursive /nos_workflow/secofs_ufs/day/18` |
| change a variable, for example a walltime | `ecflow_client --alter=change variable NOWCAST_WALLTIME 02:00:00 /nos_workflow/secofs_ufs` |
| reload an edited def | `ecflow_client --load=<def> force`, then `--begin=nos_workflow`. The reload resets every repeat to the first date in the def, and the date gate is open for past dates, so a system resumed as it is would rerun every day since then and rewrite their COMOUT (for SECOFS also the cron's). Before each `--resume`, set the repeat to the next PDY to run: `ecflow_client --alter=change repeat <PDY> /nos_workflow/<system>/day` |

Do not requeue a `day` family: a requeue resets the repeat to its first value, with the same effect as a reload. If you must, suspend the system first, requeue `day`, set the repeat, then resume; on a running system the 00z prep would be submitted at once. A job that was queued before a `git pull` of the clone runs the new scripts, as with the cards.

## 5. First cycle of a system

The suite starts nothing by itself. For each system:
1. Seed the first cycle as the system's guide says:
   - SECOFS and wave: `docs/secofs_run_guide.md`, section 2, "First cycle versus later cycles" (an `init.nowcast.nc` in COMOUT, NETCDF4_CLASSIC).
   - ATL, both variants: `docs/stofs_3d_atl_run_guide.md`, sections 2 and 3.2 (restart and the previous day's `staout_1`, `avg_bias`).
   - 2D: `docs/stofs_2d_glo_run_guide.md`, sections 2.5 and 2.6.
2. Set the repeat to the PDY of that first cycle: `ecflow_client --alter=change repeat <PDY> /nos_workflow/<system>/day`. Do this after every load, begin or reload, never skip it: the def holds an older date, and a past date makes the suite run every day from there to today.
3. For the 2D cold start only, the next block.
4. `ecflow_client --resume=/nos_workflow/<system>`.

The 2D cold start is the segment lists and the walltimes of its first cycle, as `COLDSTART=YES` does in its launcher. Set them on the two task nodes of that cycle, not on the family, so no other cycle sees them (`<cyc>` is the first cycle that runs, `00` for a whole day):
```bash
D=/nos_workflow/stofs_2d_glo/day/<cyc>
ecflow_client --alter=add variable PREP_SEGMENT     "adcprep ncst fcst" $D/jnos_prep
ecflow_client --alter=add variable PREP_WALLTIME    3:50:00             $D/jnos_prep
ecflow_client --alter=add variable NOWCAST_SEGMENT  "spinup ncst"       $D/jnos_nowcast
ecflow_client --alter=add variable NOWCAST_WALLTIME 1:50:00             $D/jnos_nowcast
```
As soon as that cycle's nowcast has completed, delete them. They stay on the nodes, and the same cycle on the next day would cold-start again:
```bash
for v in PREP_SEGMENT PREP_WALLTIME;      do ecflow_client --alter=delete variable $v $D/jnos_prep;    done
for v in NOWCAST_SEGMENT NOWCAST_WALLTIME; do ecflow_client --alter=delete variable $v $D/jnos_nowcast; done
```
Do not set `COLDSTART` for 2D.

## 6. How success and retries work

A task completes only when its J-job exits 0 and its output has `STAGE_SUMMARY stage=<stage> ofs=<OFS> status=PASS`. The JNOS scripts exit 0 even when the stage fails, so the summary is the gate; the cards' ATL and 2D tails check the same line. Anything else aborts the task: a non-zero exit, no summary, `status=FAIL`, or a failed module load (not `prod_util`, which only warns, and not an unknown `ecflow` version, which falls back to the default module). An abort that happens after a module purge still reaches the server (the error trap loads `ecflow` again).

`ECF_TRIES 2` on nowcast and forecast of `secofs_ufs`, `secofs_ufs_ww3` and `stofs_3d_atl_ufs` replaces the cards' blind ParMETIS retry (which `qsub`s itself up to 8 times on a `partition_hgrid` signature). It is blind: ecFlow retries any abort, not only that one, and a retry is a new PBS job on 25 to 46 nodes. The crash is dormant with the `NO_PARMETIS` builds (`docs/secofs_run_guide.md`, section 3.3). Post has 2 tries in every system but `stofs_2d_glo`: it uses one node and can be rerun. The 2D post has 1 try, since whether a second run of anomaly and bias on the same cycle keeps the anomaly history (`database.tar.gz`) intact is not verified. Every other task has 1 try. Change it with `ecflow_client --alter=change variable ECF_TRIES 1 /nos_workflow/<system>/day/<cycle>/jnos_nowcast`.

A failed task holds its system. The `day` repeat advances only when every task of the day is complete, and a later cycle's prep waits for the previous nowcast, so one aborted post at night stops all of the next day, for SECOFS all four cycles. The cron does not do this: there a failed post, or a failed cycle, does not stop the next cycle, and prep takes the newest restart. Nothing here retries beyond the tries above and nothing alerts, so someone has to watch the suite (`ecflow_client --get=/nos_workflow`, or an ecFlow UI). After a failure, fix the cause and `--requeue` the task, or let the system go on without it: `--force=complete` on the failed node (post, in the usual case) lets the day advance; with `recursive` on the cycle family it also skips the tasks behind it that never ran (a forced nowcast would let the forecast start without a restart). Checked in the container: a post that failed on both tries kept the next PDY from starting, and `--force=complete` on it advanced the day.

Prep starts when the UTC clock has passed the start time of its PDY. The condition is a trigger on `ECF_DATE` and `TIME`, not a `today` or `time` attribute: after a requeue `today` is already free if its time has passed, so a day that ended early would start the next cycle at once, and `time` would wait a full day after a late finish. With a past PDY the condition is open, so a repeat started on an old date runs the days one after the other (a catch-up, limited by the input data that still exists).

## 7. Testing without disturbing the SECOFS cron

The cron launchers use `/lfs/h1/nos/ptmp/$LOGNAME/com`, `.../work/secofs_ufs` and their own clone. To try the suite beside them:
1. A separate clone, for example `/lfs/h1/nos/estofs/noscrub/$LOGNAME/packages_ecf/nos-workflow`, with the same fix files and executables (symlinks are fine).
2. In the def: `PACKAGEHOME` and `ECF_INCLUDE` to that clone (both, and the same clone: if they differ, the scripts come from one clone and the includes from the other; the test checks the pair only in the repo copy), and in the suite variables `COMROOT` to `/lfs/h1/nos/ptmp/$LOGNAME/ecf_test/com` and `DATAROOT` to `/lfs/h1/nos/ptmp/$LOGNAME/ecf_test/work/%OFS%`. The standalone family sets its own `COMROOT`; change it too.
3. Seed `ecf_test/com` for the system you try (section 5), since prep reads the previous restart from COMROOT.
4. Use another ecFlow port than anyone else, and resume one system only.
5. Keep the suite name `nos_workflow`: the prep triggers name `/nos_workflow:ECF_DATE` and `/nos_workflow:TIME`, so a renamed suite needs those edited too.

Anything outside the suite that writes to the shared COMROOT, like the launchers, stays as it is.

## 8. Limits

- Not run on a WCOSS2 ecFlow server. In a container (ecFlow 5.6.0, SLURM as the batch system through a PBS stand-in, a `module` stand-in, stub J-jobs) these were checked: the real def and the generated job of all 44 tasks, a full two-day run of the five families, the PDY advance, prep waiting for the previous nowcast, the PASS gate, retries, aborts and the environment each stub J-job saw. The stand-in rejects `prod_util/2.0.17` and an unknown `ecflow` version (the card logs show `prod_util/2.0.17` unknown on WCOSS2) and gives `prod_envir` the prod roots when `envir` is unset.
- Not verified: the `ecflow` module name and version (`ecflow_ver`); the ecFlow server, its port and its owner; the real `module` behaviour, in particular that the model module stacks load under the ecFlow path and that `module load ecflow` after the purge keeps them intact and leaves python and `PYTHONPATH` alone (the post job prints the python it uses); the PBS job command and the job output location; the UTC clock of the server (the start times assume UTC).
- `versions/run.ver` pins `prod_util/2.0.17`, which WCOSS2 does not know, and the cards run without prod_util, so the suite does too: the load only prints a warning. Correcting `run.ver` changes the cards (the J-jobs would start running `setpdy.sh`, `compath.py` and `postmsg`, which no card has exercised) and belongs in its own change.
- The includes `module purge`; NCO's own task scripts load on top of the `module reset` of their `head.h`. Fine for development; flag it for the NCO code review at the hand-off.
- The J-jobs were stubs, so no model ran. The suite changes nothing in the J-jobs, cards or launchers.
- The ATL and 2D cards do not re-export `PACKAGEROOT` from the clone after their module block; the suite does, for every system.
- Not in the suite: the per-job `rpt/` logs (the job output is the log), `clean_work.sh`, the warm-start experiment launcher, the Hercules cards, STOFS-3D-AK, and the cards' 2D preflight of fix files and `adcprep`/`padcirc` (a missing file fails in the J-job with a FAIL summary).
- A stuck or failed stage holds that system's next day (section 6): `--force=complete` on the task, or `--alter=change repeat` to skip a day.

## 9. Troubleshooting

| Symptom | Likely cause |
|---|---|
| Task `aborted`, job output ends `ended without STAGE_SUMMARY` | The J-job failed before its summary; read the output above that line |
| Task `aborted` at once, `module` error | Module block: a version missing from `run.ver`, or no readable STOFS run.ver (the standalone needs the IT-stofs or the ops one) |
| Job output has `WARNING: prod_util not loaded` | Expected: `run.ver` pins `prod_util/2.0.17`, unknown on WCOSS2, and the cards run without it |
| Task stays `submitted` | It waits in the PBS queue. If `qstat` shows the job gone, it could not load any `ecflow` module: read its PBS output |
| Task stays `active` after the job is gone | The job could not reach the server (host or port in the job file) or died before the trap; `ecflow_client --force=aborted` it and look at the PBS output |
| Prep `queued` although the time has passed | A prep waits for the previous cycle's nowcast; check that task, and that the server clock is UTC |
| Jobs run on the server host | `ECF_JOB_CMD` is the default; set the PBS commands |
| `Mismatched ecfmicro(%)` at load | A script has a lone `%`; ecFlow needs `%%` or another construct |
