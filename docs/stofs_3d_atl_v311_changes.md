# STOFS-3D-ATL v3.1.0 → v3.1.1 Change Analysis

**Date:** 2026-02-24
**Source:** `/mnt/e/IT_STOFS_V.3.1/stofs_3d_atl/stofs_3d_atl/`
**Target:** `/mnt/d/NOS-Workflow-Project/nos_ofs_complete_package/nos_ofs/` (branch: `feature/unified-nowcast-forecast`)
**Para output for validation:** https://noaa-nos-stofs3d-pds.s3.amazonaws.com/index.html#STOFS-3D-Atl/para/stofs.v3.1.1_CMMB/

---

## Table of Contents

1. [Unchanged Scripts](#unchanged-scripts)
2. [USH Forcing Script Changes](#ush-forcing-script-changes)
3. [Post-Processing Script Changes](#post-processing-script-changes)
4. [Architecture Changes](#architecture-changes)
5. [Python Script Changes](#python-script-changes)
6. [New Fix Files](#new-fix-files-needed-on-wcoss2)
7. [Ex-Script Changes](#ex-script-changes)
8. [J-Job Changes](#j-job-changes)
9. [Integration Strategy](#integration-strategy)

---

## Unchanged Scripts

These v3.1.0 scripts are byte-identical in v3.1.1 — no work needed:

- `stofs_3d_atl_create_surface_forcing_gfs.sh`
- `stofs_3d_atl_create_surface_forcing_hrrr.sh`
- `stofs_3d_atl_create_obc_nudge.sh`
- `stofs_3d_atl_create_bctides_in.sh`
- `stofs_3d_atl_create_param_nml.sh`
- `make_ntc_file.pl`

---

## USH Forcing Script Changes

### 1. `stofs_3d_atl_create_river_forcing_nwm.sh` — MAJOR

**VIMS v7 simplified river source/sink system:**

- v3.1.0 used 7 fix files: `source_sink.in.before_relocate`, `sources_conus.json`, `source_scale.txt`, `sinks_conus.json`, `relocate_map.txt`, `source_sink.in`, plus `relocate_source_feeder_lean.py`
- v3.1.1 uses only `sources_conus.json` (renamed to `sources.json`) — no relocation, no sinks, no scale file
- The time-axis correction block (`if [ 1 -eq 1 ]`) is retained but immediately overwritten by `cp -f ${fn_river_th} ${fn_river_th_std}` — meaning the sed/cut time rewrite is effectively bypassed
- Added `sed 's/^ *//g' -i` to strip leading whitespace from river forcing output

### 2. `stofs_3d_atl_create_river_st_lawrence.sh` — MAJOR

**St. Lawrence River data source and processing changed:**

- **Data source path:** `${DCOMROOT}/${date}/canadian_water/QC_02OA016_hourly_hydrometric.csv` → `${COMINlaw}/${date}/can_streamgauge/02OA016_hydrometric.csv` (new `COMINlaw` variable)
- **Symlink naming:** No longer creates `river_st_law_obs.csv` symlink; directly symlinks `02OA016_hydrometric.csv`
- **New datetime format:** Added `str_yyyy_mm_dd_hr_mm_ss_py_Law` variable in format `YYYY-MM-DD HH:00:00` (was `YYYY-MM-DD-HH`)
- Added `rm -f TEM_1.th` before TEM_1.th creation (cleanup of stale files)

### 3. `stofs_3d_atl_create_obc_3d_th_non_adjust.sh` — MAJOR

**ADT processing restored and output renamed:**

- v3.1.0 had all ADT code commented out (workaround reading pre-processed `adt_aft_cvtz_cln.nc` from rerun dir)
- v3.1.1 restores the full ADT processing pipeline: 3 code paths for both/today/prev ADT data availability
- **ADT size validation:** New check `sz_adt_aft_cvtz_cln` — if ADT file < 5MB, falls back to previous day's rerun copy
- Archives `adt_aft_cvtz_cln.nc` to `${COMOUTrerun}`
- **Output renamed:** `elev2dth` → `elev2dth_non_adj` (differentiates from dynamically adjusted version)
- **Bug fix in backup fallback:** `cpreq -pf ${fn_std} ${COMOUTrerun}/${fn_std}` changed to `cpreq -pf ${fn_prev} ${COMOUTrerun}/${fn_std}` (was overwriting with empty current file instead of previous day's file)

### 4. `stofs_3d_atl_create_obc_3d_th_dynamic_adjust.sh` — NEW

**Entirely new: Dynamic bias correction for OBC water levels.**

This is the single biggest scientific change in v3.1.1:

1. Reads CO-OPS water level observations from 11 tide stations (Fort Pulaski to Newport) via `${DCOMROOT}/${date}/coops_waterlvlobs/${staID}.xml`
2. Creates NPZ database from observation CSVs via `create_npz_NOAA.py`
3. Derives model bias via `derive_bias.py` comparing SCHISM `staout_1` against observations over a 2-day window
4. Applies the bias correction to `elev2D.th.nc`:
   - Time step 0: subtract `adj0` (previous cycle's bias)
   - Time step 1: subtract average of `adj0` and `adj1`
   - Time steps 2+: subtract `adj1` (today's bias)
5. Archives bias value (`avg_bias`) for use by next cycle
6. Uses `cdo inttime` to resample to hourly before applying corrections

**Dependencies:** `pylibs/` (VIMS pylib library), `create_npz_NOAA.py`, `derive_bias.py`, `station.bp`, `diff.bp` (xGEOID-NAVD offsets)

### 5. `stofs_3d_atl_create_restart_combine_rtofs_stofs.sh` — Minor

- Threshold for RTOFS 2D/3D file count changed from `$cnt > 1` to `$cnt > 0` (allows processing with exactly 1 file)
- Stderr redirects renamed: `errfile` → `errfile_rtofs` and `errfile_python_combine` (avoids overwriting)

---

## Post-Processing Script Changes

### 6. `stofs_3d_atl_add_attr_2d_3d_nc.sh` — MAJOR

**Two new output variables added (6 → 8 global outputs):**

- Added `verticalVelocity` (units="m/s")
- Added `diffusivity` (units="m2/s")
- Added `nSCHISM_vgrid_layers` dimension (49 levels) to out2d files via `ncap2 -s 'defdim("nSCHISM_vgrid_layers",49);vgrid_dummy[nSCHISM_vgrid_layers]=0.'`

### 7. `stofs_3d_atl_create_2d_field_nc.sh` — Rewritten

- Working directory changed from `results/` to `dir_slab_2d/`
- Adds `vgrid.in` symlink (not present in v3.1.0)
- Python call changed: removed `--date` argument, added `--output_dir` argument
- Comment notes "lack of `import psutil`" as motivation

### 8. `stofs_3d_atl_create_adcirc_nc.sh` — MAJOR (Parallelized)

**Restructured for MPMD parallel execution:**

- v3.1.0: Sequential loop over stacks 1-10, then merges pairs into 5 daily files
- v3.1.1: Takes 3 positional arguments (`idx_1_adc`, `idx_2_adc`, `idx_day_adc`), merges two stacks via `ncrcat` first, then runs Python on the merged file
- Designed for `mpiexec cfp` parallel dispatch from `post_1.sh`
- Fixed typo: `mstofs` → `msg`

### 9. `stofs_3d_atl_create_awips_shef.sh` — MAJOR (Datum Shift)

**Vertical datum changed from NAVD88 to MSL:**

- All references to `navd` replaced with `msl`
- Fix file `stofs_3d_atl_sta_cwl_xgeoid_to_navd.nco` → `stofs_3d_atl_sta_cwl_xgeoid_to_msl.nco`
- Fix file `stofs_3d_atl_sta_awips_shef_navd88_mllw.txt` → `stofs_3d_atl_sta_awips_shef_msl_mllw.txt`
- SHEF station count: 107 → 150 (`ncks -O -C -d station,0,106,1` → `ncks -O -C -d station,0,149,1`)

### 10. `stofs_3d_atl_create_station_profile_nc.sh` — MAJOR (Parallelized + Datum)

**Restructured for MPMD + datum shift:**

- v3.1.0: Two sequential Python calls (nowcast stacks 1-2, forecast stacks 3-10)
- v3.1.1: Takes single positional argument `stack_no_oi`, processes one stack per invocation (for MPMD dispatch)
- Output directory changed from `results/` to `dir_profile/`
- Adds `vgrid.in`, `hgrid.gr3`, `station.in` symlinks
- **Datum shift:** NAVD NCO file → MSL NCO file (`stofs_3d_atl_sta_cwl_xgeoid_to_msl.nco`)
- Removed SENDDBN alert calls (archival/merge moved to calling script)

### 11. `stofs_3d_atl_create_awips_grib2.sh` — Changed

- File list reduced from `schout_adcirc_{1..10}.nc` to `schout_adcirc_{1..5}.nc` (matches new daily-merged ADCIRC format)
- `ncrcat` merges 5 files instead of 10
- Removed `SENDDBN_NTC` / `dbn_alert NTC_LOW` block (NTC dissemination dropped)

### 12. `stofs_3d_atl_create_geopackage.sh` — Changed

- v3.1.0 copied from `Dir_backup_2d3d/out2d_*.nc`
- v3.1.1 copies directly from `outputs/{horizontalVelX,horizontalVelY,out2d,salinity,temperature,zCoordinates}*.nc`
- Removed stray `export err=$?` at end

### 13. `stofs_3d_atl_create_AWS_autoval_nc.sh` — Minor

- File glob changed from `out2d_?.nc` to `out2d_{?,??}.nc` to match 2-digit stack numbers (stacks 1-10)

### 14. `stofs_3d_atl_create_merged_hotstart_nc.sh` — NEW

**Standalone hotstart merge script for MPMD parallel execution.**

Previously inline in `exstofs_3d_atl_post_2.sh`, now extracted:
- Calls `stofs_3d_atl_combine_hotstart -i 576`
- Sets `time=0.0` in the merged file
- Archives to `${COMOUT}/${RUN}.${cycle}.hotstart.stofs3d.nc`

### 15. `stofs_3d_atl_create_partition_prop.sh` — NEW

**Dynamic mesh partitioning at runtime.**

Handles PBS node allocation differing from pre-computed partition:
- Reads max processor ID from existing `partition.prop`
- Compares with `${NCPU_PBS} - n_scribes` (n_scribes now 8)
- If mismatch: runs `gpmetis` on `stofs_3d_atl_graphinfo.txt` to generate new partitioning
- Archives result to `${COMOUT}/rerun/stofs_3d_atl_partition.prop`

---

## Architecture Changes

### Watchdog Job (NEW)

`exstofs_3d_atl_watchdog.sh` (357 lines) — the biggest architectural addition in v3.1.1.

Runs as a **concurrent PBS job** alongside `now_forecast`:

1. **Discovers NF run directory:** Reads PID and output path from `${COMOUT}/rerun/file_one_line_dir_NF_run_outputs` (written by now_forecast)
2. **Polls `mirror.out`:** Watches for `TIME STEP=` entries at 288-step intervals (288, 576, ..., 2880)
3. **Incrementally archives** to both `${COMOUT}/outputs_watchdog/` and `${TMPPATH}_${pid}`:
   - `local_to_global_*` files (once, on first timestep)
   - `hotstart_*_${step}.nc` subdomain files
   - History NC files (8 variables: horizontalVelX/Y, out2d, salinity, temperature, zCoordinates, verticalVelocity, diffusivity)
   - `staout_*` files, `mirror.out`
4. **Skips final timestep (2880):** Defers to now_forecast for final archival

**Impact:** Eliminates the 5-hour polling loops in post_1/post_2. Post jobs read from `outputs_watchdog/` directly.

> **Note for unified workflow:** Our split nowcast/forecast approach archives after each phase via `archive_outputs()`, so we do NOT need the watchdog. However, the post-processing scripts now expect `outputs_watchdog/` paths — we'll need to adjust these references.

### Other Architecture Changes

| Change | v3.1.0 | v3.1.1 |
|--------|--------|--------|
| I/O scribes | 6 | **8** |
| Global output variables | 6 | **8** (+ verticalVelocity, diffusivity) |
| param.nml template | `_param.nml_6globaloutput` | **`_param.nml_8globaloutput`** |
| sflux file naming | `.0001.nc` (4-digit padded) | **`.1.nc`** (non-padded, matches COMF!) |
| COLDSTART | Allowed (copies fix file) | **Forbidden** (`err_exit`) |
| Missing restart | Warning only | **Fatal** (`err_exit`) |
| Annual T/S restart date | April 5 | **April 15** |
| Post-processing data source | `$DATA/outputs/` | **`${COMOUT}/outputs_watchdog/`** |
| Station profiles | Sequential | **MPMD parallel** (10 tasks) |
| ADCIRC NC extraction | Sequential loop (10 stacks) | **MPMD parallel** (5 tasks, paired stacks) |
| Hotstart merge | Inline in post_2 | **Standalone script** via MPMD |

---

## Python Script Changes

### Changed Files

| File | Severity | Key Changes |
|------|----------|-------------|
| `gen_sourcesink.py` | **Major rewrite** | VIMS v7: removed `relocate_source_feeder_lean.py`, `write_th_file`, `write_mth_file`, `get_aggregated_features`; simplified to direct numpy ops; uses `sources.json` only; no more sink/scale/relocate processing |
| `gen_fluxth_st_lawrence_riv.py` | **Rewrite** | Renamed `get_river_discharge()` → `get_river_hydrometric()`; extracts both flow AND temperature; new CSV column parsing; hardcoded `02OA016_hydrometric.csv`; time format `%.3f` → `%d` |
| `extract_slab_fcst_netcdf4.py` | **Complete rewrite** | New `VerticalInterpInfo` dataclass; `vertical_interp()` replaces `get_zcor_interp_coefficient()`; memory-save mode via `--mem_save_mode`; `--stack N` argument; imports `generate_adcirc.split_quads` |
| `generate_adcirc.py` | **Significant** | `split_quads()` vectorized with numpy; `--datum` CLI arg (default `xGEOID20B`); dry node masking via `dryFlagNode`; fixed depth coordinates attribute `"y x"` |
| `hotstart_proc.py` | **Significant** | `zdata` class imported from `pylib` (was inline); `self.dims` → `my_hot.sizes` (xarray compat); `infile/outfile` → `foreground_file/background_file`; sample functions extracted |
| `pylib.py` | **Major refactoring** | `pylibs/src/` submodule support; import restructuring (`src.mylib`, `src.schism_file`); many new functions imported; lazy imports for pandas/pyproj/netCDF4; `numpy._core` aliasing for newer numpy |
| `gen_geojson.py` | Changed | Disturbance threshold `< 0.3` → `< -5`; GeoPackage levels expanded `np.arange(0.3, 2.1, 0.1)` → `np.arange(-0.5, 2.1, 0.1)` with -5 min and 20 max (supports negative water levels) |
| `get_stations_profile.py` | Minor | Output filename `stofs_stations_forecast.nc` → `stofs_stations_profile_{stack_start}_{stack_end}.nc` |

### New Files

| File | Lines | Purpose |
|------|-------|---------|
| `create_npz_NOAA.py` | 60 | Converts CO-OPS XML water level obs to NPZ format for bias correction |
| `derive_bias.py` | 276 | Calculates model-observation bias at 11 Atlantic coast stations; outputs average bias correction value |
| `pylibs/` | (directory) | VIMS upstream `pylib` library (git submodule with `src/mylib.py`, `src/schism_file.py`, scripts, tutorials) |

### Identical Python Files

- `gen_temp_1_st_lawrence_riv.py`
- `generate_station_timeseries.py`
- `mylib.py`
- `relocate_source_feeder_lean.py`
- `river_th_extract2asci.py`
- `schism_file.py`
- `utils.py`

---

## New Fix Files Needed on WCOSS2

These files exist in v3.1.1's `fix/stofs_3d_atl/` and must be staged on WCOSS2:

### Dynamic OBC Bias Correction
- `stofs_3d_atl_obc_adjust_msl_geoid.bp` (639 B) — MSL-to-geoid adjustment for 11 OBC stations
- `stofs_3d_atl_obc_adjust_station.bp` (478 B) — OBC adjustment station definitions

### VIMS v7 River Sources
- `stofs_3d_atl_river_msource.th` (135 KB) — River momentum source time history
- `stofs_3d_atl_river_source_sink.in` (15 MB) — River source/sink definitions
- `stofs_3d_atl_river_sources_conus.json` (130 KB) — CONUS river-to-NWM reach ID mapping (8575 lines)
- `stofs_3d_atl_river_vsink.th` (42 MB) — River volume sink time history

### MSL Datum Products
- `stofs_3d_atl_sta_awips_shef_msl_mllw.txt` (2.3 KB) — Station MSL-to-MLLW offsets for SHEF (150 stations)
- `stofs_3d_atl_sta_cwl_xgeoid_to_msl.nco` (6.5 KB) — Per-station geoid-to-MSL NCO corrections (166 lines)

### Station Metadata
- `stofs_3d_atl_staout_nc.csv` (11 KB) — Station info CSV (167 stations: ID, name, lat, lon)
- `stofs_3d_atl_staout_nc.json` (1.1 KB) — Output variable metadata JSON

### Model Configuration
- `stofs_3d_atl_param.nml_8globaloutput` (62 KB) — Updated param.nml template with 8 global outputs

### Unchanged Fix Files (already on WCOSS2)
All `.gr3` files (312 MB each), `vgrid.in` (1.6 GB), `graphinfo.txt` (1.4 GB), `partition.prop` (71 MB), etc. are unchanged.

---

## Ex-Script Changes

### `exstofs_3d_atl_prep_processing.sh`

| Area | v3.1.0 | v3.1.1 |
|------|--------|--------|
| Debug mode | `set $setoff` | `set $seton` |
| param.nml template | `_param.nml_6globaloutput` | `_param.nml_8globaloutput` |
| OBC scripts | Single `_obc_3d_th.sh` | Split: `_non_adjust.sh` then `_dynamic_adjust.sh` |
| Script order | St. Lawrence → OBC | OBC → St. Lawrence |
| COLDSTART | Allowed (copy fix file) | **Forbidden** (`err_exit`) |
| Missing restart | Warning | **Fatal** (`err_exit`) |
| `source_sink.in` | Active symlink | Commented out |
| `postmsg` | `postmsg "$jlogfile" "$msg"` | `postmsg "$msg"` |

### `exstofs_3d_atl_now_forecast.sh`

| Area | v3.1.0 | v3.1.1 |
|------|--------|--------|
| n_scribes | 6 | **8** |
| sflux naming | `.0001.nc` | **`.1.nc`** |
| partition.prop | Static from fix | **Dynamic** via `create_partition_prop.sh` |
| Watchdog PID | Not present | **Exports** `pid_JOBS_NF_run` and writes to `file_one_line_dir_NF_run_outputs` |
| Post-run archival | None | **Copies** key outputs to `${COMOUT}/outputs_watchdog/` |
| Post-run sleep | None | **`sleep 180s`** |

### `exstofs_3d_atl_post_1.sh`

| Area | v3.1.0 | v3.1.1 |
|------|--------|--------|
| Polling loop | 30 iterations × 600s (5 hours max) | **Removed** — reads from `outputs_watchdog/` directly |
| Data source | `$DATA/outputs/` | **`${COMOUT}/outputs_watchdog/`** |
| Station profiles | Sequential Python calls | **MPMD parallel** (2 nowcast + 8 forecast tasks) |
| ADCIRC NC | Sequential loop over 10 stacks | **MPMD parallel** (5 tasks, paired stacks) |
| Error handling | Warning | **Fatal** (`err_exit`) |

### `exstofs_3d_atl_post_2.sh`

| Area | v3.1.0 | v3.1.1 |
|------|--------|--------|
| Polling loop | Present | **Removed** |
| Hotstart merge | Inline | **Standalone** `create_merged_hotstart_nc.sh` via MPMD |
| Attribute update | Only in post_1 | **Also runs here** (10-process MPMD) |
| Data source | `$DATA/outputs/` | **`${COMOUT}/outputs_watchdog/`** |

### `exstofs_3d_atl_temp_salt_restart.sh`

- Annual T/S update date: April 5 (`0405`) → **April 15** (`0415`)

### `exstofs_3d_atl_hot_restart_prep.sh`

| Area | v3.1.0 | v3.1.1 |
|------|--------|--------|
| NCPU_PBS_hot_restart | Hardcoded `4314` | **Dynamic** `NCPU_PBS - n_scribes` |
| Hotstart search | Starts at step 2880 | **Starts at 2592** (skips 2880, handled by now_forecast) |
| File source | `$DATA/outputs/` | **`${COMOUT}/outputs_watchdog/`** |
| param.nml backup | `_hot_restart` suffix | `_backup_ihot1` / `_back_ihot2` suffixes |

### `exstofs_3d_atl_watchdog.sh` — NEW

357-line companion job running concurrently with `now_forecast`. See [Architecture Changes](#watchdog-job-new) above.

---

## J-Job Changes

All v3.1.1 J-jobs have these common structural changes:

- **Date as argument:** Accepts `$1` for `YMD_CURRENT_DATE` (no more hardcoded dates)
- **PID-based DATA directories:** `${DATAROOT}/prep_${YMD_CURRENT_DATE}.${pid}` (prevents collisions)
- **`COMROOT` version bump:** `com/stofs/v2.1` → `com/stofs/v3.1`
- **`NET` changed:** `stofs` → `stofs3d`
- **Removed `compath.py` calls:** Direct `${COMPATH}/...` paths instead
- **New path variables:** `COMPATH`, `COMPATH_DCOM` as base paths

### Per-Job Changes

| J-Job | v3.1.1 Changes |
|-------|----------------|
| `JSTOFS_3D_ATL_PREP` | New forcing source dirs: `COMINadt`, `COMINgfs`, `COMINhrrr`, `COMINrtofs`, `COMINnwm`, `COMINlaw`, `COMINwl` |
| `JSTOFS_3D_ATL_NOW_FORECAST` | Exports `pid_JOBS_NF_run=$$` for watchdog; `KEEPDATA="YES"` always |
| `JSTOFS_3D_ATL_POST_I` | `SENDCOM` defaulted to NO |
| `JSTOFS_3D_ATL_POST_II` | All `SEND*` defaulted to NO |
| `JSTOFS_3D_ATL_TEMP_SALT_RESTART` | `SORCstofs3d` path added; `COMINrtofs` defined |
| `JSTOFS_3D_ATL_WATCHDOG` | **NEW** — `TMPPATH` variable for temp archive |

---

## Integration Strategy

### Approach

**Copy v3.1.1 USH scripts and Python exactly, then re-apply our YAML config loading and unified workflow adaptations on top.**

### What We Update (STOFS-specific scripts)

1. **USH scripts in `ush/stofs_3d_atl/`** — Replace with v3.1.1 versions, re-add YAML config loading blocks
2. **Python scripts in `ush/stofs_3d_atl/pysh/`** — Copy all v3.1.1 Python files (including new ones)
3. **STOFS ex-scripts in `scripts/stofs_3d_atl/`** — Update to match v3.1.1 logic (OBC split, 8globaloutput, MPMD, etc.)

### What We Keep (unified framework)

1. **Unified J-jobs** (`jobs/JNOS_OFS_*`) — Already framework-aware, just need new env vars (`COMINlaw`, `COMINwl`, etc.)
2. **Unified ex-scripts** (`scripts/nosofs/exnos_ofs_prep.sh`, etc.) — Update STOFS branch to call new script names
3. **Shared libraries** (`ush/nos_ofs_config.sh`, `nos_ofs_prep_run.sh`, `nos_ofs_model_run.sh`) — Minimal changes
4. **YAML config** (`parm/systems/stofs_3d_atl.yaml`) — Update for 8 globals, MSL datum, VIMS v7 rivers

### What We Skip

1. **Watchdog job** — Our split nowcast/forecast approach archives after each phase via `archive_outputs()`, eliminating the need for concurrent monitoring
2. **`outputs_watchdog/` paths in post-processing** — Adapt post scripts to read from our archive location instead
3. **STOFS-specific J-jobs** — We use unified `JNOS_OFS_*` jobs

### Sflux Naming Alignment

The sflux naming change (`.0001.nc` → `.1.nc`) is actually beneficial — it **aligns v3.1.1 with our COMF convention**, eliminating the naming mismatch documented in MEMORY.md lesson #11.

### New Fix Files

Must be copied from v3.1.1 `fix/` to WCOSS2's `$FIXstofs3d` directory before testing.
