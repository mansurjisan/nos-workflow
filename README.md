# nos_secofs_ufs

NOAA NOS SECOFS-UFS-Coastal (Southeast Coastal Ocean Forecast System, UFS-Coastal coupled)
operational workflow — clean SECOFS-UFS-only refactor of the v3.7.0 multi-OFS workflow.

## Status

Refactored from `nosofs.v3.7.0/` (multi-OFS, supports SECOFS, CBOFS, DBOFS, LEOFS, STOFS variants, …) into a SECOFS-UFS-only tree. Files used by other OFS systems are dropped.

This is **not yet validated end-to-end on WCOSS2** — it is a draft for review. Once validated, this tree becomes the canonical SECOFS-UFS workflow and the legacy `nosofs.v3.7.0/` is retired.

## Repo / branch

- **GitHub repo:** [`mansurjisan/nos-workflow`](https://github.com/mansurjisan/nos-workflow) (unchanged)
- **Target branch:** `nos-secofs_ufs` (new clean branch — root-level files are the contents of this `nos_secofs_ufs/` working dir)
- **Existing branches:** `feature/python-prep` (current development) and `main` are preserved; this is a parallel clean-slate branch
- **Deployment dir on WCOSS2:** `$PACKAGEROOT/nos_secofs_ufs/` (clone target name)

```bash
# On WCOSS2, when deploying:
cd $PACKAGEROOT
git clone -b nos-secofs_ufs https://github.com/mansurjisan/nos-workflow.git nos_secofs_ufs
```

## Layout

```
nos_secofs_ufs/
├── docs/             — RENAME_MAP.md (what was renamed/dropped vs nosofs.v3.7.0)
├── jobs/             — J-jobs (JNOS_PREP, JNOS_NOWCAST, JNOS_FORECAST, JNOS_POST)
├── scripts/          — ex-scripts (exnos_prep_python.sh, exnos_nowcast.sh, exnos_forecast.sh, exnos_post.sh)
├── pbs/              — PBS launchers (jnos_*.pbs)
├── ush/              — shell + Python utilities
│   ├── nos_run.sh    — consolidated 4-step API (replaces nos_ofs_model_run.sh + nos_ofs_launch.sh)
│   ├── nos_config.sh — YAML loader
│   └── python/
│       ├── nos-utils/  — Python forcing package (orchestrator + processors)
│       └── utils/      — yaml_to_env.py
├── parm/             — YAML configs
│   ├── base/schism.yaml
│   ├── systems/secofs_ufs.yaml
│   └── templates/    — (UFS templates moved here; see fix/secofs_ufs/ instead)
├── fix/secofs_ufs/   — UFS templates + param.nml + noahmptable.tbl
├── exec/             — placeholder for compiled Fortran binaries (filled by sorc/ build)
└── sorc/             — Fortran source (TBD: copy schism_combine_hotstart7 + tide_fac_schism here)
```

## Public API (unchanged from legacy)

```bash
source ${USHnos}/nos_config.sh
load_ofs_config "${OFS_CONFIG}" "comf"

source ${USHnos}/nos_run.sh
stage_model_files nowcast
prepare_restart   nowcast
execute_model     nowcast
archive_outputs   nowcast
```

## Deployment to WCOSS2 (when ready)

1. Copy this tree to `$PACKAGEROOT/nos_secofs_ufs/`
2. Copy `fix/secofs_ufs/` mesh files (hgrid.gr3, vgrid.in, .gr3 overlays, station.in, etc.) from the legacy `nosofs.v3.7.0/fix/secofs_ufs/` (these stayed on WCOSS2, not in the repo).
3. Build EXEC binaries from `sorc/` (TBD).
4. Update PBS launchers' `OFS_CONFIG` path to point at the new location.
5. Submit `pbs/jnos_prep_00.pbs` followed by `pbs/jnos_nowcast_00.pbs` and `pbs/jnos_forecast_00.pbs`.

## Validation strategy

Before retiring `nosofs.v3.7.0/`:
1. Run a full nowcast+forecast cycle from this tree on WCOSS2.
2. Compare COMOUT byte-for-byte against the equivalent legacy run.
3. Confirm `f9914ee` hotstart NETCDF4_CLASSIC fix is in effect (`ncdump -k rst.nowcast.nc` reports "netCDF-4 classic model").

## What was dropped (full list in `docs/RENAME_MAP.md`)

- 14 of 17 `ush/nosofs/*.sh` scripts (unused under FULL_PYTHON_PREP=YES)
- entire `ush/python/nos_ofs/` legacy Python package (~thousands of lines, dead code on SECOFS-UFS path)
- 8 `parm/systems/*.yaml` for other OFS (creofs, dbofs, leofs, ngofs2, secofs, secofs_2d_ufs, stofs_2d_atl, stofs_2d_glo, …)
- `parm/base/{fvcom,roms}.yaml`
- All `JNOS_OFS_ENSEMBLE_*` jobs and ensemble PBS launchers
- All `_stofs_*`, `_adcirc_*` functions in the run library (consolidated into `nos_run.sh` with SCHISM-only paths)

## Phase 4 cleanup (still TODO)

- Strip STOFS/ADCIRC/legacy framework dispatch from J-jobs (`jobs/JNOS_*` still has `case ${RUN} in stofs_*|adcirc_*` cases that are dead for SECOFS-UFS)
- Drop the `$SCRIPTSnos/exnos_ofs_prep.sh` legacy fallback path in `JNOS_PREP` (only the Python prep path matters)
- Audit `nos_config.sh` for `load_stofs_config` / `load_nosofs_config` backward-compat shims (~50 lines droppable)
- Final `set -x` audit in `nos_run.sh` (currently inherits from launch.sh; leaks trace into caller scope)
