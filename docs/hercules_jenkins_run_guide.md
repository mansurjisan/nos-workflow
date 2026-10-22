# Running the Hercules Jenkins CI: STOFS-3D-Atlantic and STOFS-2D-Global

Status as of 2026-10-16.

STOFS-3D-Atlantic and STOFS-2D-Global both run from one manual Jenkins job on Hercules, `NOS/nos-workflow-atl-hercules`. Open **Build with Parameters**, pick the system with `OFS` and the depth with `LEVEL`, and run against a frozen dataset. The stages (Prep, Nowcast, Forecast, Post, Verify) are the same ones SECOFS uses. The first smoke build of each system passed bitwise against its reference on 2026-10-15.

Every build runs on Hercules as the CI account `role-nosofs`, whoever starts it. You need only a Jenkins login to run a build against an existing dataset. You need your own Hercules account only to make a new test case (section 8).

| I want to | I need | Read |
| --- | --- | --- |
| Run a build on an existing dataset | A Jenkins login with Build permission | sections 1-7 |
| Add my own test case (a new PDY/CYC) | The above, plus a Hercules account and a finished hand run | section 8 |
| Test a branch or PR | The above, plus Configure permission on the job and push access to `github.com/oceanmodeling/nos-workflow` | section 9 |

The system details are in the Jenkins sections of the run guides: [STOFS-3D-ATL section 10](stofs_3d_atl_run_guide.md#10-jenkins-hercules-manual-only) and [STOFS-2D-Global section 5](stofs_2d_glo_run_guide.md#5-jenkins-hercules-manual-only).

## 1. Get access (once)

1. Open <https://jenkins.epic.oarcloud.noaa.gov> and sign in through the EPIC single sign-on page with your NOAA account.
2. Ask the CI maintainer (Mansur Jisan) to have the EPIC Jenkins administrators give your account **Build** permission on the `NOS` folder. Ask for **Configure** as well if you will test branches (section 9).
3. Join the Slack channel `#nos-notifications`. Every build posts its result there.

Nothing on Hercules is needed for sections 2-7.

## 2. Before each build

- **Only one CI build runs at a time.** The job never runs two builds at once, and it shares a lock (`$NOS_CI_ROOT/.ci-lock`) with the SECOFS job `NOS/nos-workflow-secofs-hercules`. A second build of this job waits in the queue until the first ends, and takes over a lock the first one left behind; a build while a SECOFS build runs fails at Gate. The next build of this job that takes the lock cancels the last Slurm job an earlier build submitted (when its id is still in `ci_logs/`), whether or not that build also left the lock. Gate then prints `cancelling job <id> left by build <N>`; for a build that ended normally the job has already finished and this does nothing. Check `squeue -A nosofs` if in doubt. Check both jobs' Build History first.
- **The job builds the `develop` branch** (*Branches to build* = `*/develop`). Section 9 covers other branches.
- **Never use Build Now** for these systems: it always runs the SECOFS defaults.
- **Large jobs queue.** The nowcast and forecast jobs take 52-63 nodes, so a build can wait in the Slurm queue before it runs. That wait does not count against a stage's time limit, only against the 16 h build limit (section 7).

## 3. Start a build

1. Open the job: <https://jenkins.epic.oarcloud.noaa.gov/job/NOS/job/nos-workflow-atl-hercules/>. The name is historical; the job runs both systems.
2. Click **Build with Parameters** in the left menu.
3. Set the parameters from the table below. Leave every other parameter at its default.
4. Click **Build**. The build appears at the top of **Build History** with its number.
5. Click the build number to follow it (section 6).

| Parameter | ATL standalone | ATL coupled | 2D-Global |
| --- | --- | --- | --- |
| `OFS` | `stofs_3d_atl_ufs_standalone` | `stofs_3d_atl_ufs` | `stofs_2d_glo` |
| `LEVEL` | `smoke` | `smoke` | `smoke`, `cycle` or `full` |
| `DATA_MODE` | `frozen` | `frozen` | `frozen` |
| `PDY` | `20261001` | `20261001` | `20261012` |
| `CYC` | `12` (forced to 12 anyway) | `12` (forced to 12 anyway) | `06` for smoke and cycle, `00` for full |

To stop a running build, click the red **X** next to it in Build History (or **Abort** on the build page). The cleanup then cancels the Slurm job the build was waiting on. You can confirm with `squeue -A nosofs` on Hercules. Click Abort once and wait for the cleanup to finish: a second click can interrupt the cleanup and leave the CI lock behind. The next build of this job clears such a lock, but it blocks the SECOFS job (it shares the lock) for up to 18 h.

**All parameters:**

| Parameter | Default | What it does | Change it? |
| --- | --- | --- | --- |
| `OFS` | `secofs_ufs` | The system to run | Always (table above) |
| `LEVEL` | `smoke` | How far the build goes (section 4) | As needed |
| `DATA_MODE` | `live` | `frozen` runs a stored dataset; `live` downloads today's inputs (section 10) | Set `frozen` |
| `PDY`, `CYC` | `20260827`, `06` | The cycle; it must match a dataset (section 5). A nightly timer build ignores them (section 10) | Always |
| `SEED_RT` | `/work2/noaa/nos-surge/mjisan/nos-workflow-rt` | Where Bootstrap copies a dataset from, the first time a build needs it | Only for your own dataset (section 8) |
| `SEED_SRC` | `/work2/noaa/nos-surge/mjisan/nos-workflow` | Where Bootstrap copies `fix/` and `exec/` from, the first time a system runs in this CI root | No; all three systems are already copied (section 8.1). Only a first 2D-Global build in a new CI root needs the 2D package |
| `NOS_CI_ROOT` | `/work2/noaa/nosofs/role-nosofs/nos-ci` | The CI's own tree: package, venv, datasets, ptmp, lock | No |
| `SLURM_ACCOUNT`, `SLURM_QOS` | `nosofs`, `batch` | What the CI's Slurm jobs are charged to | No |
| `DCOM_BUNDLE` | empty | ATL live mode only (section 10) | No |

## 4. What each LEVEL runs

Every build runs the same stages in order. `LEVEL` decides only whether Forecast and Post run, and what Verify checks.

Section 12 has what each stage does, system by system, including SECOFS.

1. **Checkout:** the job's branch.
2. **Gate:** lets a manual STOFS build through without a PR label, forces `CYC=12` for ATL, and takes the CI lock.
3. **Bootstrap:** builds the CI Python venv. The first time a system runs in the CI root, it copies `fix/` and `exec/` from `SEED_SRC`; the first time a dataset is used, it copies the dataset from `SEED_RT` (the ATL smoke dataset, 118 GB, in 5.5 min; the 2D-Global dataset, 60 GB, in 2.5 min). Later builds reuse the copies (section 8.1).
4. **Deploy:** copies the checked-out nos-workflow into the CI package root, so the branch's cards and scripts are what runs.
5. **Environment Check:** modules, Python imports and executables. It fails before anything is submitted.
6. **Stage Data:** removes only this system's earlier cycle directories from the CI `com`, then links the dataset in.
7. **Prep, Nowcast, Forecast, Post:** each submits one Slurm job from the system's card through `.cicd/scripts/run_stage.sh` and waits for it. A stage passes only when its job log has `STAGE_SUMMARY ... status=PASS`.
8. **Verify:** compares the outputs with the dataset's reference.

| LEVEL | Stages after Stage Data | ATL Verify | 2D-Global Verify |
| --- | --- | --- | --- |
| `smoke` | Prep, Nowcast, Verify | the 8 nowcast `staout` files | `rerun/stofs_2d_glo_{tide,surf}.61.nc` |
| `cycle` | Prep, Nowcast, Forecast, Post, Verify | the 8 nowcast and 8 forecast `staout` files, plus `points.cwl` and `station.profile` (nowcast and forecast) | the `.61.nc` files and `points.*.nc`, plus the ops comparison |
| `full` | Prep, Nowcast, Forecast, Post, Verify | as cycle, plus the ops comparison | as cycle, from a cold start (`adcprep` in Prep, spin-up in Nowcast) |

2D-Global smoke and cycle continue from the previous cycle stored in the dataset. Verify passes on bitwise equality, or when the largest difference in the time-dependent variables is within `CMP_TOL` (default 1e-3 m for water level, m/s for velocity and wind). ATL scales it by 10 for temperature and salinity (degC, psu) and by 100 for the `staout_2` pressure (Pa). The ops comparison is a report against the operational products: its warnings (above `OPS_WARN_MM`, default 500 mm) never fail a build, and only a missing output of this run does. `CMP_TOL` and `OPS_WARN_MM` are environment variables of the scripts, not build parameters.

**Measured CI runtimes and cost** (queue wait comes on top):

| Build | System, LEVEL | Prep | Nowcast | Nowcast nodes | Node-hours | Verify |
| --- | --- | --- | --- | --- | --- | --- |
| #10 | 2D-Global, smoke | 30 s | 1352 s | 52 | about 20 | tide and surf `.61.nc` bitwise |
| #7 | ATL coupled, smoke | 1592 s | 3094 s | 63 | about 55 | 8/8 bitwise |
| #6 | ATL standalone, smoke | 511 s | 1562 s | 62 | about 27 | 8/8 bitwise |

2D-Global Prep takes seconds because the dataset already holds the forcing. The cycle and full levels have not run in CI yet. From hand runs on Hercules, a 2D-Global forecast adds about 77 min on 52 nodes (about 66 node-hours) and post about 15 min on one node. A 2D-Global `full` build adds about 1.9 h of `adcprep` (one node) and a 26 min spin-up on 52 nodes. ATL forecast and post have not been timed on Hercules.

## 5. Datasets available now

A frozen dataset is a stored copy of one finished hand run: its inputs, plus its outputs as the reference. They live under `SEED_RT`, `/work2/noaa/nos-surge/mjisan/nos-workflow-rt`.

| Dataset | System | Cycle | Levels it supports | Tested |
| --- | --- | --- | --- | --- |
| `stofs_3d_atl/standalone/2026100112` | ATL standalone | 20261001 12z | smoke | build #6, 8/8 bitwise |
| `stofs_3d_atl/coupled/2026100112` | ATL coupled | 20261001 12z | smoke | build #7, 8/8 bitwise |
| `stofs_2d_glo/2026101206` | 2D-Global | 20261012 06z | smoke, cycle | smoke: build #10, bitwise |
| `stofs_2d_glo/2026101200` | 2D-Global | 20261012 00z (cold start) | full | not yet |

The ATL datasets were seeded from runs that had finished only prep and nowcast, so Stage Data refuses `cycle` and `full` on them. They become cycle datasets after a re-seed (section 8.3). Both ATL variants write to the same CI `com` directory, so a coupled build overwrites the outputs of an earlier standalone build of the same cycle.

## 6. Reading the result

A green build means every model stage logged `status=PASS` and Verify matched the reference. Where to look when you need more:

- **Stage view** (build page): one column per stage. In a smoke build Forecast and Post show as skipped. A red column is the stage that failed.
- **Console Output** (build page, left menu): a model stage prints `jobid=<id>`, polls `sacct` every 30 s, and ends with `PASS[<stage>]: <log path>`. On failure it prints `FAIL[<stage>]` and the last 60 lines of the job log. Bootstrap prints what it copied, for example `bootstrap: dataset copied: <files> files, <size>, <seconds> s`.
- **Build Artifacts** (build page, `ci_logs/`): each stage's Slurm `.out` and `.err`, and Verify's report (`compare_atl.txt` or `compare_2dglo.txt`), so you rarely need the cluster. For a Verify failure, read the report: it lists each file as bitwise or with its largest difference.
- **On Hercules:** job logs are in `$NOS_CI_ROOT/ptmp/role-nosofs/rpt/stofs_3d_atl_ufs/` or `rpt/stofs_2d_glo/`. Outputs are in `com/nos/stofs_3d_atl_ufs.<PDY>/` or `com/nos/stofs_2d_glo.<PDY>/` under the same ptmp. You can read them only if the CI tree's permissions allow it; otherwise use Build Artifacts.
- **Slack:** `#nos-notifications` gets SUCCESS or FAILURE with the system, LEVEL, DATA_MODE, PDY/CYC and a link to the build. ABORTED carries only the job name, build number and link.

ATL work directories are about 150 GB a cycle. A passing ATL stage deletes its own; a failed one is kept for debugging until the next build of the same ATL variant. 2D-Global jobs always remove theirs.

## 7. When a build fails

Find the red column, open Console Output, then match the message below.

| Stage | Message or symptom | Cause | Fix |
| --- | --- | --- | --- |
| Gate | `another CI cycle holds the lock` | The SECOFS job is running (a lock left by an earlier build of this job is cleared at once) | Wait for the SECOFS build. Abort a build only once and let its cleanup finish, or the lock stays behind. A SECOFS lock older than 18 h is cleared automatically. The next build of this job that takes the lock cancels the last Slurm job an earlier build submitted (when its id is still in `ci_logs/`), whether or not that build also left the lock. Gate then prints `cancelling job <id> left by build <N>`; for a build that ended normally the job has already finished and this does nothing. Check `squeue -A nosofs` if in doubt. |
| (any) | The build ran SECOFS | Started with Build Now | Use Build with Parameters and set `OFS` |
| (form) | A parameter is missing from the form | Jenkins shows a new parameter only after one build of the Jenkinsfile that adds it | Start one build, abort it, then use Build with Parameters again |
| Bootstrap | `FATAL: ... is not readable by role-nosofs` or `not readable as role-nosofs`, with a `chmod` hint | `SEED_SRC` or `SEED_RT` is not readable by the CI account | The owner of that path runs the printed `chmod -R o+rX`, plus `chmod o+x` on every parent directory (section 8.4) |
| Bootstrap | `FATAL: <SEED_RT>/<system>/<PDY><CYC> not readable as role-nosofs.` followed by `If the dataset does not exist yet, seed it once` | Usually a PDY/CYC with no dataset (section 5) | Check `PDY`/`CYC` first, then the permissions (section 8.4) |
| Bootstrap | `FATAL: .../fix/stofs_2d_glo not readable` or the ADCIRC directory not readable, on the first 2D-Global build in a CI root | `SEED_SRC` was left at its default, which has no 2D-Global files | Set `SEED_SRC` to the 2D package (section 11) |
| Stage Data | Refuses `LEVEL=cycle` or `full` | The ATL dataset was seeded at smoke level | Run smoke, or upgrade the seed (section 8.3) |
| Prep to Post | `rc=timeout` | `sacct` still showed the job as live past the stage limit, counted from when it started (accounting lag, or a suspended or requeued job). A run longer than its walltime is ended by Slurm first and shows as `no STAGE_SUMMARY PASS` with `sacct final state: TIMEOUT` | Check `sacct -j <jobid>` and `squeue -j <jobid>` on Hercules, then rebuild |
| Prep to Post | `rc=unstartable` | The job could never start: held, over a per-job or partition limit, or a bad account or QOS (the reason is printed) | Fix the account, QOS or card resources, then rebuild |
| Prep to Post | `FAIL[<stage>]: no STAGE_SUMMARY PASS` | The job failed | Read the stage's `.out` and `.err` in Build Artifacts. A failed ATL stage keeps its work directory until the next build of the same variant |
| Verify | Every compared file differs slightly | The reference came from a different environment (venv or MPI build) | Seed a new dataset (new PDY/CYC) from a run in the CI environment; a re-seed of the same cycle never reaches the CI (section 8.1). Not seen so far |

**Stage time limits** (from when the job starts; queue wait does not count). ATL: the card walltime plus 30 min. 2D-Global: the launcher walltime plus 1 h. The whole build is also capped at 16 h, which a slow ATL cycle or full build can reach before Post ends (the coupled limits add up to 17.5 h).

| Stage | ATL limit | 2D-Global limit |
| --- | --- | --- |
| Prep | 3:30 | 1:50 (4:50 for `full`) |
| Nowcast | 3:00 | 2:20 (3:20 for `full`) |
| Forecast | 6:30 | 3:00 |
| Post | 2:30 (coupled 4:30) | 2:15 |

If you cannot fix it, send the maintainer the build number, the failing stage and the `FAIL` lines from Console Output.

A failed build cancels only the Slurm job it submitted itself (`ci_logs/current_jobid` records the build number). A build that fails before Deploy (at Gate or Bootstrap) still holds the previous build's `ci_logs/`: its Build Artifacts are the previous build's logs, and the cleanup prints `skipping stale jobid` instead of cancelling.

## 8. Add your own test case (from your Hercules account)

A new test case is a new frozen dataset: one finished hand run of yours, copied into your own `SEED_RT`. The CI account then copies it into its own tree on the first build that names it.

### 8.1 What the CI copies, and when

Bootstrap copies each item once, then reuses it, and checks a `.seeded_ok` marker to know. Apart from the ATL smoke-to-cycle refresh, it never looks at the source again.

| Item | Copied from | Copied again when |
| --- | --- | --- |
| A system's `fix/` | `SEED_SRC/fix/<system>` | Never, until someone with `role-nosofs` access removes the matching `.seeded_ok` under `$NOS_CI_ROOT` |
| A system's executables | `SEED_SRC/exec` | Never, as above |
| The 2D-Global ADCIRC build | `adcirc_v56.1.0_exec` beside `SEED_SRC` | Never, as above |
| A dataset (system, PDY, CYC) | `SEED_RT/<system>/<PDY><CYC>` | Never, except that an ATL smoke copy is refreshed once its source is upgraded to cycle |
| The CI Python venv | built from the checked-out nos-utils | Rebuilt whenever `import scipy, nos_utils` fails in it (checked before modules load), which today is every build |

What this means for you:

- **A new dataset needs a PDY/CYC that the CI does not have yet.** Datasets are told apart by system, PDY and CYC only, not by `SEED_RT`. A dataset of yours for 20261001 12z would be ignored, and for ATL a cycle-level one would be copied over the CI's smoke copy and mix two runs. Always use a PDY/CYC the CI does not have.
- **`SEED_SRC` does not matter once a system has run.** New fix files or executables reach the CI only after the maintainer removes the CI copy's `.seeded_ok`.
- **`FORCE=1` re-seeds stay local.** Replacing your dataset of an existing cycle changes nothing in the CI; use a new PDY/CYC.

### 8.2 Make a finished hand run

Set up your own nos-workflow clone on Hercules and run a cycle by hand, following the run guide:

- **STOFS-3D-ATL:** [run guide section 4](stofs_3d_atl_run_guide.md#4-hercules-rdhpcs-slurm). Run all four stages (prep, nowcast, forecast, post) for a dataset that supports `cycle` and `full`. Prep and nowcast alone give a smoke-only dataset. Seed the previous cycle with `tools/hercules_atl_seed_prev.sh` (not the flat `COMINrerun` option): the dataset seed reads `staout_1` and `avg_bias` from the PDY-1 directory of the run's COMROOT.
- **STOFS-2D-Global:** [run guide section 3](stofs_2d_glo_run_guide.md#3-hercules-rdhpcs-slurm). Run a 00z cold start through post, then the following 06z cycle with `COLD=0`. The 06z cycle becomes the smoke and cycle dataset, and the 00z cold start the full dataset. Stage the forcing with `tools/hercules_2d_glo_stage_forcing.sh` so the ops station files are downloaded too; the ops comparison uses them.

All stages must end with `status=PASS`.

### 8.3 Seed the dataset

Run from your nos-workflow clone on a Hercules login node. Both seed scripts default `SEED_RT` to the maintainer's tree, so always export `SEED_RT` to a directory of yours first, and give the same path to the `SEED_RT` build parameter (section 8.5). The script copies the run into `${SEED_RT}/<system>/<PDY><CYC>/`, makes the copy world-readable, and prints the `chmod o+x` its parent directories need.

**STOFS-3D-Atlantic** (about 110-130 GB per variant; the second variant hard-links what it shares with the first). Arguments: the run's COMROOT, its staged comin tree and its dcom directory. `$COMROOT_SA`, `$COMROOT_UFS` and `$B` (the case bundle) are the variables of ATL run guide sections 4.1 and 4.2.

```bash
export SEED_RT=/work2/noaa/nos-surge/$LOGNAME/nos-workflow-rt
bash .cicd/scripts/stofs_3d_atl.sh seed <PDY> standalone \
  $COMROOT_SA $NOS_PTMP/$LOGNAME/comin_atl $B/dcom
bash .cicd/scripts/stofs_3d_atl.sh seed <PDY> coupled \
  $COMROOT_UFS $NOS_PTMP/$LOGNAME/comin_atl $B/dcom
```

Put `SEED_LEVEL=smoke` in front of a command to seed from a run that has finished only prep and nowcast; the dataset then supports `LEVEL=smoke` only. Once the run has finished forecast and post, repeat the same command without `SEED_LEVEL` (and without `FORCE`) to upgrade the dataset to cycle.

**STOFS-2D-Global** (about 60 GB). `COMROOT_2DGLO` is the com root of your finished runs:

```bash
export SEED_RT=/work2/noaa/nos-surge/$LOGNAME/nos-workflow-rt
export COMROOT_2DGLO=$NOS_PTMP/$LOGNAME/com
bash .cicd/scripts/stofs_2d_glo.sh seed <PDY> 00 cold
bash .cicd/scripts/stofs_2d_glo.sh seed <PDY> 06
```

The seed also stores the ops station files when the forcing tool downloaded them (`OPS_DIR`, default `$NOS_PTMP/$LOGNAME/ops_s3/<PDY><CYC>/products`).

Both scripts refuse to overwrite an existing dataset unless `FORCE=1` is set; the ATL smoke-to-cycle upgrade is the one exception. The 2D-Global seed also needs the run to have finished Post, because it stores the `points` files.

### 8.4 Open the path to the CI account

`role-nosofs` is not in your Unix group, so it reads your files through the "other" permission bits. The seed makes the dataset itself world-readable. You must also allow `o+x` (traverse, not list) on every directory above it, for example:

```bash
chmod o+x /work2/noaa/nos-surge/$LOGNAME
chmod o+x $SEED_RT $SEED_RT/stofs_2d_glo
namei -l $SEED_RT/stofs_2d_glo/<PDY>06
```

`namei -l` lists every directory on the path with its permissions. Each one needs an `x` in the last triplet. Use the same steps for `stofs_3d_atl/<variant>`.

### 8.5 Run it in Jenkins

Start a build as in section 3, with `SEED_RT` set to your directory and `PDY`/`CYC` set to your cycle. In Console Output, Bootstrap should print `seeding frozen dataset ... from <your SEED_RT>` and then `bootstrap: dataset copied: ...`. Later builds of that cycle reuse the CI copy, so `SEED_RT` no longer matters for it.

Each dataset copy uses space in the CI tree (ATL about 110-130 GB, 2D-Global about 60 GB). Tell the maintainer when you add one, and when an old one can go.

## 9. Test a branch or PR

The job runs the branch named under Configure, and Deploy copies that branch's cards and scripts into the CI package. You need Configure permission.

1. Push the branch to `github.com/oceanmodeling/nos-workflow` (the job's repository; forks are not built).
2. Tell the team on Slack: the job is shared, and it runs one build at a time.
3. Open the job, click **Configure**, set *Branches to build* to `*/<your-branch>`, and click **Save**.
4. If the branch adds or changes a Jenkins parameter, start one build and abort it, so the form shows the new parameter.
5. Run **Build with Parameters** as in section 3.
6. When you are done, set *Branches to build* back to `*/develop` and click **Save**.

A branch cannot change `fix/` or `exec/` in the CI (section 8.1).

## 10. Live mode (not yet tested in CI)

`DATA_MODE=live` downloads the inputs for `PDY`/`CYC` instead of using a dataset. Use frozen for regression checks; live is for checking a new date end to end.

- **2D-Global:** Stage Data downloads the ops forcing for the cycle (about 39 GB) on the front-end node. Before the download it removes the other days' 2D-Global directories from the CI `com` and the other cycles' download directories under `ops_s3`. It keeps the shared `nos/stofs_2d_glo` (the cached 4064-rank decomposition and the chain state) and the days of `PDY` and of the cycle 6 h earlier, so a rerun of the same day does not download again. It continues from the 2D-Global state already there: run `LEVEL=full` first (a cold start), then `LEVEL=cycle` for the cycle 6 h later, with no frozen 2D-Global build in between (a frozen build clears that state).
- **Nightly:** the ATL job `NOS/nos-workflow-atl-hercules` (not the SECOFS job) has a timer between 20:00 and 21:00 UTC. It runs `stofs_2d_glo`, `LEVEL=full`, `DATA_MODE=live`, `CYC=12` for today's UTC date, whatever the parameter defaults are. The 12z ops forcing is on S3 at about 19:05Z and the ops station files at about 19:20Z. A once-a-day 12z run cannot chain, so every night is a cold start. Jenkins registers the timer only after the job has run the merged Jenkinsfile once (one manual build). The build takes the same CI lock as SECOFS, so a SECOFS build running at that time makes that night's build fail at Gate. Disk stays at about one cycle because Stage Data removes the older days, as above.
- **ATL:** also needs `DCOM_BUNDLE`, a case bundle directory with `dcom/` and `seeds/dyn_seed_<PDY-1>/` (ATL run guide section 4.2) that `role-nosofs` can read. It downloads about 125 GB per build.

Live mode has no reference run. At smoke, Verify checks nothing beyond the stage PASS for either system, and ATL cycle Verify likewise. 2D-Global compares with the ops products at cycle and full; ATL downloads and compares them only at full.

## 11. Reference

| What | Where |
| --- | --- |
| Jenkins | <https://jenkins.epic.oarcloud.noaa.gov>, job `NOS/nos-workflow-atl-hercules`, branch `*/develop` |
| SECOFS job (shares the lock) | `NOS/nos-workflow-secofs-hercules` |
| Agent, user, Slurm account | `Hercules-NOS`, `role-nosofs`, `nosofs` (qos `batch`) |
| CI root (`NOS_CI_ROOT`) | `/work2/noaa/nosofs/role-nosofs/nos-ci` |
| CI package, venv, datasets | `$NOS_CI_ROOT/nos-workflow`, `$NOS_CI_ROOT/nos-venv`, `$NOS_CI_ROOT/nos-workflow-rt` |
| CI com, rpt, work | `$NOS_CI_ROOT/ptmp/role-nosofs/{com,rpt,work}` |
| Dataset source (`SEED_RT` default) | `/work2/noaa/nos-surge/mjisan/nos-workflow-rt` |
| ATL package source (`SEED_SRC` default) | `/work2/noaa/nos-surge/mjisan/nos-workflow` |
| 2D-Global package source | `/work2/noaa/nos-surge/mjisan/packages_2dglo/nos-workflow` |
| 2D-Global ADCIRC build | `/work2/noaa/nos-surge/mjisan/packages_2dglo/adcirc_v56.1.0_exec` |
| Pipeline and scripts | `.cicd/Jenkinsfile`, `.cicd/scripts/run_stage.sh`, `.cicd/scripts/bootstrap.sh`, `.cicd/scripts/stofs_3d_atl.sh`, `.cicd/scripts/stofs_2d_glo.sh` |
| Slack | `#nos-notifications` |

## 12. Stage by stage

What each Jenkins stage does for each system. The three systems share the stage names and `.cicd/scripts/run_stage.sh`. SECOFS is included because it runs in the same pipeline (it is what **Build Now** runs) and in its own job, `NOS/nos-workflow-secofs-hercules`.

The Slurm stages all work the same way. `run_stage.sh` submits the system's card with account `nosofs` and polls `sacct` every 30 s. A stage passes only when the job log has `STAGE_SUMMARY stage=<stage> ofs=<system> status=PASS` (`ofs=stofs_3d_atl_ufs` for both ATL variants). Its time limit counts from when the job starts running, so queue wait does not count; the 16 h build limit still does.

### 12.1 STOFS-3D-Atlantic

Both variants: standalone (`stofs_3d_atl_ufs_standalone`) and coupled (`stofs_3d_atl_ufs`).

| Stage | Runs on | What it does | LEVEL | Time (smoke builds) |
| --- | --- | --- | --- | --- |
| Checkout | Jenkins agent | Checks out the job's branch (`*/develop`) | all | seconds |
| Gate | Jenkins agent | Lets a manual ATL build run without the PR label, forces `CYC=12` (ATL has only the 12z cycle) and takes the CI lock shared with the SECOFS job | all | seconds |
| Bootstrap | Jenkins agent | Builds the CI venv. Once per CI root, copies `fix/stofs_3d_atl_ufs` and the variant's executables from `SEED_SRC` (pschism for standalone, `fv3_stofs_3d_atl.exe` for coupled, plus `tide_fac`). Once per dataset, copies `stofs_3d_atl/<variant>/<PDY>12` from `SEED_RT` and makes its `input/` files read-only; the second variant hard-links what it shares with the first | all | first copy 118 GB in 5.5 min, then seconds |
| Deploy | Jenkins agent | Copies the checked-out nos-workflow (cards, scripts, Python, nos-utils) into the CI package root, leaving `fix/` and `exec/` alone; clears `ci_logs/` | all | seconds |
| Environment Check | Jenkins agent | Modules, Python imports, executables and wgrib2; fails before any Slurm job is submitted | all | seconds |
| Stage Data | Jenkins agent | Removes earlier `com/nos/stofs_3d_atl_ufs.<day>` directories from the CI com, then hard-links the dataset's PDY-1 and PDY day directories in: the init state, plus `staout_1` and `avg_bias` for the dynamic adjustment. comin and dcom are read in place from the dataset. Refuses `cycle` and `full` on a smoke-only dataset | all | about 1 s |
| Prep | Slurm, 1 node | The variant's `jnos_prep_00.sh` builds the model inputs: atmospheric forcing (standalone: GFS+HRRR sflux; coupled: DATM forcing and its ESMF mesh), NWM rivers and the St. Lawrence, RTOFS boundary conditions and nudging, ADT-blended SSH, tides, and the dynamic water-level adjustment | all | 511 s standalone, 1592 s coupled |
| Nowcast | Slurm, 62 nodes (standalone) or 63 (coupled) | The 24 h nowcast from the init state; writes the station output and the hotstart the forecast continues from | all | 1562 s standalone, 3094 s coupled |
| Forecast | Slurm, 62 or 63 nodes | The 96 h forecast from the nowcast hotstart | cycle, full | not yet run in CI |
| Post | Slurm, 1 node | Station products (`points.cwl`, `station.profile`) and field products, nowcast and forecast | cycle, full | not yet run in CI |
| Verify | Jenkins agent | `compare_atl.py regress` against the dataset's reference. smoke: the 8 nowcast `staout` files. cycle: also the 8 forecast `staout` files, `points.cwl` and `station.profile`. full: also the ops comparison (report only). Report: `compare_atl.txt` | all | seconds |
| post-build | Jenkins agent | Releases the lock and archives `ci_logs/`; on failure or abort, cancels the Slurm job the build was waiting on; posts to Slack | all | seconds |

Time limit per Slurm stage: the card walltime plus 30 min (section 7). A passing stage deletes its own work directory (about 150 GB a cycle); a failed one keeps it for debugging. Verify tolerance: `CMP_TOL` (default 1e-3) for water level, velocity and wind, 10 times that for temperature and salinity, 100 times for pressure.

### 12.2 STOFS-2D-Global

`smoke` and `cycle` continue from the previous cycle (`COLD=0`); `full` is a cold start (`COLD=1`).

| Stage | Runs on | What it does | LEVEL | Time (smoke build #10) |
| --- | --- | --- | --- | --- |
| Checkout | Jenkins agent | Checks out the job's branch (`*/develop`) | all | seconds |
| Gate | Jenkins agent | Lets a manual 2D build run without the PR label and takes the CI lock. `CYC` is used as given (06 for smoke and cycle, 00 for full) | all | seconds |
| Bootstrap | Jenkins agent | Builds the CI venv. Once per CI root, copies `fix/stofs_2d_glo` and `stofs_2d_glo_tide_fac` from `SEED_SRC`, and the ADCIRC build (`padcirc`, `adcprep`) from `adcirc_v56.1.0_exec` beside it. Once per dataset, copies `stofs_2d_glo/<PDY><CYC>` from `SEED_RT`; its forcing, decomposition tar and `nod_equi` become read-only | all | first copy 60 GB in 2.5 min, then seconds |
| Deploy | Jenkins agent | Copies the checked-out nos-workflow into the CI package root, leaving `fix/` and `exec/` alone; clears `ci_logs/` | all | seconds |
| Environment Check | Jenkins agent | Modules, Python imports, `tide_fac`, `padcirc`, `adcprep`, the NCO tools (`ncdiff`, `ncrcat`, `ncks`) and `sbatch`/`sacct` | all | seconds |
| Stage Data | Jenkins agent | Removes only `com/nos/stofs_2d_glo` and `com/nos/stofs_2d_glo.<day>` from the CI com, then links the dataset in: the cycle's forcing into `rerun/`, read-only; for smoke and cycle also `nod_equi` and the 4064-rank decomposition tar, read-only, and the previous cycle's chain files (`hotstart` for tide, `restart` for surf) as writable copies | all | seconds |
| Prep | Slurm, 1 node, 64 GB | `gfs_ncst` and `gfs_fcst` (the forcing build) skip, because the dataset already holds the forcing. At `full`, `adcprep` runs first and builds `nod_equi` and the decomposition | all | 30 s (`full`: about 1.9 h more) |
| Nowcast | Slurm, 52 nodes | The 6 h nowcast from the previous cycle's chain files: tide (NWS=0, 4064 ranks on 51 nodes), then surf (NWS=14014, 4064 + 5 writer ranks). Writes this cycle's chain files and checks every output for dropped records. At `full`, the 162 h spin-up runs first | all | 1352 s (`full`: spin-up about 26 min more) |
| Forecast | Slurm, 52 nodes | The 180 h forecast: tide, then surf, each followed by the record-gap check | cycle, full | not yet run in CI; about 77 min in hand runs |
| Post | Slurm, 1 node, 100 GB (on the prep card) | `ncdiff` makes the surge-only products, swl = cwl - htp, for the station and field files. `ncrcat` joins the met forcing into the ops met files (`pressfc`, `uvgrd10m`, `icec`): hourly to 120 h, then 3-hourly to 180 h, 7 + 121 + 21 = 149 records. anomaly, bias and GRIB2 are not run on Hercules | cycle, full | not yet run in CI; about 15 min in hand runs |
| Verify | Jenkins agent | `compare_2dglo.py` against the dataset's reference. smoke: `rerun/stofs_2d_glo_{tide,surf}.61.nc`. cycle and full: also the `points.*.nc` station files, plus the station comparison with ops (report only; warns above 500 mm). Report: `compare_2dglo.txt` | all | seconds |
| post-build | Jenkins agent | Releases the lock and archives `ci_logs/`; on failure or abort, cancels the Slurm job the build was waiting on; posts to Slack | all | seconds |

Time limit per Slurm stage: the launcher walltime plus 1 h (section 7). The jobs run with `KEEPDATA=NO` and remove their own work directories. Verify tolerance: bitwise, or the largest difference in zeta, u-vel and v-vel within `CMP_TOL` (default 1e-3 m or m/s).

### 12.3 SECOFS

`OFS=secofs_ufs`: DATM and SCHISM coupled through UFS-Coastal, a 6 h nowcast and a 48 h forecast. `LEVEL` is ignored; every build runs all four model stages.

| Stage | Runs on | What it does | Time limit |
| --- | --- | --- | --- |
| Checkout | Jenkins agent | Checks out the job's branch, or the PR merge commit on a PR build | - |
| Gate | Jenkins agent | A PR build runs only when the PR carries the `hercules-nos-RT` label; Build Now and branch builds always run. Takes the CI lock and posts a `pending` GitHub status (`hercules-ci/cycle`) on the PR head commit, or on the branch commit for a branch build | - |
| Bootstrap | Jenkins agent | Builds the CI venv. Once per CI root, copies the whole `fix/` and `exec/` trees from `SEED_SRC` and checks for `fv3_coastalS.exe`. In frozen mode, once per dataset, copies `comin_<PDY><CYC>` (about 80 GB) from `SEED_RT` | - |
| Deploy | Jenkins agent | Copies the checked-out nos-workflow into the CI package root, leaving `fix/` and `exec/` alone; clears `ci_logs/` | - |
| Environment Check | Jenkins agent | Modules, Python imports, `fv3_coastalS.exe`, `schism_combine_hotstart7.exe` and `wgrib2 -config` | - |
| Stage Data | Jenkins agent | live (the default): `ush/stage_comin.py` downloads the cycle's public inputs (GFS, HRRR, RTOFS, NWM) into `$RT_DATA_ROOT/comin_<PDY><CYC>`. frozen: checks the stored dataset. Then makes sure the nowcast init file exists: frozen copies it from the dataset, live makes a cold-start rest state when it is missing | - |
| Prep | Slurm, 1 node | Builds the DATM atmospheric forcing (GFS/HRRR GRIB2) and its ESMF mesh, NWM rivers, RTOFS boundary conditions and nudging, and tides | 2:10 |
| Nowcast | Slurm, 37 nodes | The 6 h coupled nowcast from the init state; writes the hotstart the forecast continues from | 3:00 (the 1:30 walltime doubled, a value taken from the WCOSS2 PBS launcher, whose cards retry after a ParMETIS crash; the Hercules card does not retry) |
| Forecast | Slurm, 37 nodes | The 48 h coupled forecast | 5:40 |
| Post | Slurm, 1 node | Station and field products | 2:10 |
| Verify | Jenkins agent | `verify.sh`: all four stage logs have `STAGE_SUMMARY ... status=PASS`, and `restart_outputs` exists with files over 1 MB. There is no comparison against a reference | - |
| post-build | Jenkins agent | Releases the lock and archives `ci_logs/`; on failure or abort, cancels the current Slurm job. Posts `success` or `failure` to `hercules-ci/cycle` on the same commit; on a PR build also removes the `hercules-nos-RT` label. Posts to Slack | - |

### 12.4 SECOFS against the STOFS systems

| | SECOFS | STOFS-3D-ATL and STOFS-2D-Global |
| --- | --- | --- |
| Trigger | the `hercules-nos-RT` PR label, Build Now, or a branch build | Build with Parameters only |
| `LEVEL` | ignored: always Prep, Nowcast, Forecast, Post | smoke, cycle or full |
| Data | live (downloads the cycle's inputs), the default | frozen (a stored dataset), which you must set; `DATA_MODE` defaults to live for every system |
| Verify | stage PASS and output present | regression against a reference run, bitwise or within tolerance |
| GitHub status | `hercules-ci/cycle` on the PR head or branch commit | none |
| Stage time limits | fixed in `run_stage.sh` (above) | ATL: card walltime + 30 min; 2D-Global: launcher walltime + 1 h |

A SECOFS build shows that the cycle ran, not that its numbers match a reference.
