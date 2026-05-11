# STOFS-3D-ATL UFS-Coastal Port Plan

Scoping document for the STOFS-3D Atlantic port to the UFS-Coastal coupling
stack on `nos_workflow`. Tracked under issue #219 task #33.

This is a greenfield effort: STOFS-3D-ATL has never been UFS-compliant before.
The deterministic operational system on `feature/python-prep` is standalone
SCHISM driven by sflux atmospheric forcing files. The target system on this
branch (`feature/stofs-3d-atl-ufs`) is SCHISM coupled to CDEPS DATM via the
NUOPC mediator inside a single coupled executable (`fv3_coastalS.exe`), i.e.
the same coupling stack that SECOFS-UFS has just been migrated onto.

## 1. Baseline summary — what STOFS-3D-ATL looks like on `feature/python-prep`

Repository layout, drawn from `git show origin/feature/python-prep`:

- `parm/systems/stofs_3d_atl.yaml` (431 lines): grid 1.8M nodes / 3.5M elements,
  51 vertical levels, GFS+HRRR atmospheric forcing, NWM river forcing with 7690
  source/sink reaches, RTOFS open-boundary water level and 3D T/S, ADT satellite
  SSH adjustment, 8-constituent TPXO9 tides, NAVD88-MSL datum shift for station
  products, GEFS+RRFS ensemble, `framework: stofs`.
- `scripts/stofs_3d_atl/`:
  - `exstofs_3d_atl_prep_processing.sh` (429 lines) drives the prep stage as a
    single bash script. It links static files from `$FIXstofs3d`, then calls
    individual USH scripts in sequence (`stofs_3d_atl_create_param_nml.sh`,
    `_create_bctides_in.sh`, `_create_river_forcing_nwm.sh`,
    `_create_surface_forcing_gfs.sh`, `_create_surface_forcing_hrrr.sh`,
    `_create_obc_3d_th_non_adjust.sh`, `_create_obc_3d_th_dynamic_adjust.sh`).
  - `exstofs_3d_atl_now_forecast.sh` (155 lines): combined nowcast+forecast using
    a shared 4-step library (`nos_ofs_model_run.sh`'s `stage_model_files` /
    `prepare_restart` / `execute_model` / `archive_outputs`). Both phases run
    the same standalone `pschism_WCOSS2` executable; restart is staged from
    previous-cycle COMOUT for nowcast, from this-cycle nowcast outputs for
    forecast.
  - `exstofs_3d_atl_post_1.sh`, `_post_2.sh`, `_temp_salt_restart.sh`: 3-phase
    post-processing. post_1 extracts station timeseries and produces SHEF/AWIPS
    products; post_2 generates 2D ADCIRC-format NetCDF and the GeoPackage;
    temp_salt_restart writes the combined T/S restart file for the next cycle.
- `ush/stofs_3d_atl/`: 27 shell helpers (the `stofs_3d_atl_create_*` family)
  plus `pysh/` containing 10 Python helpers (`gen_sourcesink.py`,
  `extract_slab_fcst_netcdf4.py`, `generate_adcirc.py`, etc.) and a vendored
  `pylibs/` from VIMS upstream.
- Descriptor today: `framework="stofs"`, `stage_aliases={"prep_nowcast": "prep",
  "now_forecast": "nowcast"}`, `extra_stages=("post_1", "post_2",
  "temp_salt_restart")`. The runner module is empty — every `stages/*.py`
  branch for `framework="stofs"` currently raises `NotImplementedError` with a
  pointer to "task #33".

What is unclear from a code read alone and must be confirmed before commits 2-6:

- Whether the ESMF mesh for the 1.8M-node ATL grid has ever been generated; the
  closest precedent is the 1.7M-node SECOFS-UFS mesh, but the ATL grid covers a
  much larger lon/lat box (-98.5..-52.5, 7..52.6 vs SECOFS' -88..-63, 17..40).
- Whether `fv3_coastalS.exe` has been built for the WCOSS2 module stack with
  STOFS-3D-ATL grid hardcoded compile-time constants, or whether the build is
  geometry-agnostic and the same binary works.
- The exact 7690-reach NWM source/sink mapping format expected by the coupled
  binary (the standalone `gen_sourcesink.py` writes `vsource.th`, `vsink.th`,
  `msource.th`; the coupled binary may want them produced by the
  `nos_utils.forcing.nwm.NWMProcessor` path SECOFS-UFS uses).
- Whether the ADT (Altimetry Dynamic Topography) bias-correction step in
  `_create_obc_3d_th_dynamic_adjust.sh` survives unchanged or needs a parallel
  path that operates on DATM-coupled output instead of standalone SCHISM.

## 2. Target architecture — STOFS-3D-ATL-UFS

Derived from the SECOFS-UFS canonical (commit `6089b00` on `nos-unified-workflow`):

- `framework="comf"` in the descriptor. Once UFS-coupled, dispatch is identical
  to SECOFS-UFS via `stages/{prep,nowcast,forecast,post}.py` `comf` branch. The
  legacy `framework="stofs"` descriptor and its `NotImplementedError` branches
  in `stages/*.py` stay reserved for any future standalone STOFS support, and
  are NOT touched by this port.
- `canonical_stages=("prep","nowcast","forecast","post")`, `stage_aliases={}`,
  `extra_stages=()`. The pre-UFS STOFS-3D-ATL extras (`post_1`, `post_2`,
  `temp_salt_restart`) fold into a single `post` stage once the prep+nowcast
  arithmetic becomes COMF-style.
- YAML at `parm/systems/stofs_3d_atl_ufs.yaml`, derived from
  `stofs_3d_atl.yaml` on `feature/python-prep` plus the UFS-Coastal extensions
  from `secofs_ufs.yaml`.
- Model executable: `fv3_coastalS.exe` (the same binary SECOFS-UFS uses).
- Atmospheric forcing: `datm_forcing.nc` (single blended GFS+HRRR file)
  produced by `nos_utils.forcing.atm.BlenderProcessor` on a regular lat/lon
  grid sized to the ATL domain (-98..-55, 10..53 at 0.025 degrees would give
  1721x1721 — identical sizing to SECOFS-UFS by happy coincidence; ATL is wider
  east-west but SECOFS sub-domain happens to need 43-degree-wide blend grid as
  well; this is TBD and a candidate for adjustment in commit 4).
- ESMF mesh: regenerated from the actual `datm_forcing.nc` per cycle inside
  `_schism_execute_ufs_coastal` in `ush/nos_run.sh` (the same code path
  SECOFS-UFS uses). No precomputed mesh file required.
- River forcing: `nos_utils.forcing.nwm.NWMProcessor` aggregating 7,690 ATL
  reaches. The `feature/python-prep` STOFS scripts call `gen_sourcesink.py`
  directly; we replace that with the same Python path used by SECOFS-UFS via
  `nos_utils.nco_bridge.run_prep`. Output formats — `vsource.th`, `vsink.th`,
  `msource.th`, plus `source_sink.in` — match the formats `fv3_coastalS.exe`
  already consumes for SECOFS-UFS.
- OBC + nudging: RTOFS interpolation via `nos_utils.forcing.rtofs.RTOFSProcessor`
  and `nos_utils.forcing.nudging.NudgingProcessor` — the same path SECOFS-UFS
  uses. The ATL boundary segments and the larger ROI from
  `stofs_3d_atl.yaml.forcing.ocean.obc.roi_3d{z,s}` are carried into the new
  YAML.
- Tidal: `nos_utils.forcing.tidal.TidalProcessor` writes `bctides.in` from the
  8 constituents in `stofs_3d_atl_ufs.yaml.forcing.tidal.constituents`; the
  TPXO9 harmonic constants file `stofs_3d_atl_ufs.tidal_hc.nc` lives in
  `$FIXofs`.
- Coupling: MED+ATM share 120 PETs, OCN gets the remaining ranks. ATL grid is
  larger than SECOFS so the OCN partition target is likely higher than
  SECOFS-UFS' 2794. Suggested initial guess: 4192 OCN ranks + 120 ATM/MED =
  4312 total tasks, mirroring the original-vintage `partition.prop` size on
  WCOSS2 with one rank margin. Confirmation needed before commit 2.
- Post-processing: the COMF `post` stage's `schism_combine_outputs.py` produces
  the CO-OPS standard station NetCDF. The legacy `post_1` / `post_2` / 
  `temp_salt_restart` deliverables (SHEF, AWIPS GRIB2, ADCIRC-format NetCDF,
  GeoPackage, T/S restart for the next cycle) need to be ported into the same
  `post` stage body. This is the largest scope risk in the plan and is tracked
  separately under commit 6.

## 3. Architectural delta table

| Component             | STOFS-3D-ATL now (feature/python-prep)       | SECOFS-UFS now (nos-unified-workflow)             | STOFS-3D-ATL-UFS target                                  | Effort |
| --------------------- | -------------------------------------------- | -------------------------------------------------- | -------------------------------------------------------- | ------ |
| Model executable      | `pschism_WCOSS2` (standalone)                | `fv3_coastalS.exe` (UFS-Coastal coupled)           | `fv3_coastalS.exe` — same binary, ATL grid via mesh      | S (build) |
| Atm forcing pipeline  | sflux generated by `_create_surface_forcing_gfs.sh` + `_hrrr.sh` (NCO/ncap2) | `BlenderProcessor` writes single `datm_forcing.nc` | `BlenderProcessor` at ATL extent, single `datm_forcing.nc` | M |
| Atm forcing file fmt  | `sflux_air/prc/rad_1.{1..N}.nc` (multi-file) | `INPUT/datm_forcing.nc` (single)                   | `INPUT/datm_forcing.nc` (single)                         | S |
| nws value             | 2 (sflux)                                    | 4 (NUOPC)                                          | 4 (NUOPC)                                                | S |
| ESMF mesh             | n/a (standalone SCHISM doesn't use one)      | regenerated per cycle from forcing in `nos_run.sh` | regenerated per cycle (same code path); larger ny*nx     | M  |
| River forcing         | `gen_sourcesink.py` (7690 reaches) called by `_create_river_forcing_nwm.sh` | `nos_utils.forcing.nwm.NWMProcessor` (~70 reaches for SECOFS) | `nos_utils.forcing.nwm.NWMProcessor` at ATL scale (7690 reaches) | L |
| OBC                   | `_create_obc_3d_th_non_adjust.sh` + `_dynamic_adjust.sh` (RTOFS + ADT) | `nos_utils.forcing.rtofs.RTOFSProcessor` + `dynamic_adjust` | `nos_utils.forcing.rtofs.RTOFSProcessor` with ATL boundary segments + ADT path | L |
| Nudging               | `_create_obc_nudge.sh` (RTOFS to nudge.gr3)  | `nos_utils.forcing.nudging.NudgingProcessor`       | `nos_utils.forcing.nudging.NudgingProcessor` with `SAL_nudge.gr3` / `TEM_nudge.gr3` and ATL ROI | M  |
| Grid (hgrid/vgrid)    | `stofs_3d_atl.hgrid.gr3` / `.vgrid.in` in `$FIXstofs3d` | `secofs_ufs.hgrid.gr3` / `.vgrid.in` in `$FIXofs` | `stofs_3d_atl_ufs.hgrid.gr3` / `.vgrid.in` in `$FIXofs`  | S (symlink) |
| param.nml template    | `stofs_3d_atl_param.nml_8globaloutput`       | `secofs_ufs.param.nml` template                    | `stofs_3d_atl_ufs.param.nml` template (nws=4, ihot=1)    | M  |
| bctides.in            | `bctides.in_template` rendered by `_create_bctides_in.sh` | written by `nos_utils.forcing.tidal.TidalProcessor` | written by `nos_utils.forcing.tidal.TidalProcessor`      | S |
| source_sink.in        | static fix file `stofs_3d_atl_river_source_sink.in` (VIMS v7) | written by `NWMProcessor` | written by `NWMProcessor` (ATL scale)                    | M |
| Runtime config (UFS)  | n/a (no model_configure / datm_in / ufs.configure) | `UFSConfigProcessor` writes from templates        | `UFSConfigProcessor` with ATL templates                  | M |
| MPI launcher          | `mpiexec -n nprocs pschism_WCOSS2`           | `mpiexec -n total_tasks fv3_coastalS.exe`         | `mpiexec -n total_tasks fv3_coastalS.exe`               | S |
| Resource sizing       | nprocs=4320 (4314 compute + 6 scribes)       | nprocs=2914 (2794 OCN + 120 ATM/MED)               | nprocs=~4312 (~4192 OCN + 120 ATM/MED), TBD by partition.prop | M  |
| Post-processing       | 3-phase: post_1 (stations/SHEF), post_2 (ADCIRC/GeoPackage), temp_salt_restart | single `post` stage (`schism_combine_outputs.py`) | single `post` stage with extended body for SHEF/ADCIRC/T-S restart | L |

Effort key: S=small (under a day), M=medium (1-3 days), L=large (a week+).

## 4. Commit sequence — six independent, parity-tested steps

Each commit lands on `feature/stofs-3d-atl-ufs`. All six are designed to be
individually reviewable.

### Commit 1 — descriptor + YAML scaffolding  (this commit, S)

- `ush/python/nos_workflow/descriptors/stofs_3d_atl_ufs.py` — `OFSDescriptor`,
  `framework="comf"`, canonical stages only, `runner_module="nos_workflow.runners.ufs_coastal"`.
- `parm/systems/stofs_3d_atl_ufs.yaml` — based on the operational
  `stofs_3d_atl.yaml` plus the UFS-Coastal extensions from `secofs_ufs.yaml`.
  Many fields are placeholders marked with `TODO(stofs-ufs-port)` and the
  forcing/coupling sections are wired through to the comf branch.
- Unit test for the descriptor in `ush/python/nos_workflow/tests/test_descriptors.py`.
- `nos_uw list` shows the new OFS; `nos_uw stages stofs_3d_atl_ufs` lists the
  4 canonical stages.

No runtime code path uses the new descriptor yet — the YAML placeholders make
the prep / nowcast / forecast / post stages fail loudly with useful messages
the moment they're invoked, but the dispatch wiring + smoke tests prove the
descriptor is correctly registered.

### Commit 2 — UFS-Coastal build hooks for the ATL grid  (S documentation, M actual)

- `docs/STOFS_3D_ATL_UFS_PORT_PLAN.md`: add the WCOSS2 build invocation that
  matches `secofs_ufs` (`sorc/build_ufs_coastal.sh ATL` or whatever the existing
  convention is) and document the expectation that `fv3_coastalS.exe` is
  geometry-agnostic — the grid is plumbed via the `hgrid.gr3` / `.vgrid.in` /
  `param.nml` files at runtime, NOT compiled in.
- If the build needs differences (e.g., NTRACERS, MAX_BC_SEGMENTS bumped for
  ATL), capture them here. The actual binary build is operator-side and
  out-of-scope for this commit.
- Smoke test: load YAML and assert `model.executable == "fv3_coastalS.exe"`.

### Commit 3 — atm forcing pipeline switch sflux to datm  (M)

- Wire `nos_utils.forcing.blender.BlenderProcessor` for STOFS-3D-ATL-UFS,
  retaining the bigger ATL extent (-98..-55, 10..53 vs SECOFS' -88..-63,
  17..40 — these will likely need to be different lat/lon bounds vs SECOFS).
- Validate `INPUT/datm_forcing.nc` is produced end-to-end on a representative
  cycle.
- Tests: a tiny `BlenderProcessor` smoke test asserting it accepts the ATL YAML
  config without raising.

### Commit 4 — ESMF mesh regen for 1.8M-node ATL grid  (M)

- Update the `_schism_execute_ufs_coastal` Python block in `ush/nos_run.sh` if
  the ATL forcing grid sizing changes the mesh generation arithmetic. The
  current code is geometry-agnostic so this is likely a no-op aside from
  resource sizing of the auxiliary script.
- Risk: ESMF mesh generation at the larger ATL grid (estimated 1721x1721 to
  3441x1801 nodes depending on the blend resolution choice) may be slow enough
  that we need to cache the mesh between cycles. Decision deferred.

### Commit 5 — river forcing via `nos_utils.forcing.nwm` at ATL scale  (L)

- Verify `NWMProcessor` handles 7,690 reaches without scaling issues; if it
  doesn't, add a chunking path or a config knob.
- Migrate the St. Lawrence climatology insertion (the
  `_create_river_st_lawrence.sh` step on the legacy branch) into
  `NWMProcessor` or a sibling processor.
- Write the source_sink.in + vsource.th + vsink.th + msource.th expected by
  `fv3_coastalS.exe` for the ATL run.

### Commit 6 — end-to-end parity test vs current STOFS-3D-ATL v3.1.1 ops baseline  (L)

- Run on WCOSS2 against a recent operational cycle; compare:
  - water-level station timeseries at 10 representative stations (Cape May,
    Boston, Charleston, Miami, etc.) within (TBD: 1cm RMS? 5cm RMS?)
  - full-domain elevation snapshot at +0h, +24h, +48h, +108h
  - the deliverables that the legacy `post_1` / `post_2` / `temp_salt_restart`
    produced (SHEF, AWIPS GRIB2, ADCIRC NetCDF, GeoPackage, T/S restart)
- Land the post stage extensions needed to write those deliverables.
- The parity test gates merge to `nos-unified-workflow`.

## 5. Risk list

- ESMF mesh generation at 1.8M-node ATL grid resolution may be slow enough to
  push the prep stage past its PBS walltime budget. Mitigation: cache the mesh
  between cycles by hashing the forcing-file lat/lon bounds + resolution and
  reusing the on-disk mesh when the hash matches.
- UFS-Coastal binary build for STOFS-3D-ATL may need bumped compile-time
  constants (MAX_BC_SEGMENTS, NSCRIBES, MAX_TRACERS) compared to SECOFS-UFS.
  Mitigation: capture diffs against `secofs_ufs` build in commit 2's notes.
- The 7,690-reach NWM aggregation at ATL scale stresses `NWMProcessor`'s
  in-memory data structures (the SECOFS path handles ~70 reaches). Mitigation:
  benchmark on a real cycle in commit 5 and add chunking only if needed.
- The ADT (Altimetry Dynamic Topography) bias correction path on
  `_dynamic_adjust.sh` operates on the standalone SCHISM output structure. Once
  inside the coupled `fv3_coastalS.exe`, the equivalent of the ADT step needs
  to run BEFORE the mpiexec, against the `nos_utils.forcing.rtofs` output, not
  against post-run SCHISM history. Mitigation: lift the ADT logic into the
  prep stage via `nos_utils.forcing.dynamic_adjust` (already exists).
- The legacy post_1 / post_2 / temp_salt_restart deliverables (SHEF, AWIPS
  GRIB2, ADCIRC-format NetCDF, GeoPackage, T/S restart) are non-trivial bash
  pipelines that NCO downstream consumers depend on. Commit 6 must preserve
  byte-identical output for those products, or the migration cannot ship to
  ops.
- The `feature/python-prep` STOFS-3D-ATL branch carries a `framework="stofs"`
  descriptor that still references the pre-UFS workflow with `prep_nowcast` /
  `now_forecast` aliases and three extra stages. The UFS port introduces a new
  OFS name (`stofs_3d_atl_ufs`) rather than mutating the legacy descriptor; the
  legacy one stays as a `NotImplementedError`-only stub. Operators eventually
  retiring the legacy `stofs_3d_atl` descriptor is a follow-up that does NOT
  block this port.

## 6. Open questions for the user

These cannot be decided from a code read alone:

1. **Should `stofs_3d_atl_ufs.yaml` `system.framework` be `comf` or some new
   value `stofs_ufs`?** Today, descriptor `framework="comf"` triggers the
   SECOFS-UFS code path in `stages/*.py`. The legacy STOFS-3D-ATL is
   `framework="stofs"`. The cleanest semantics would be `framework="comf"` (the
   dispatch is identical), but the descriptor and the YAML's `system.framework`
   are read by different bits of code at different times. This commit picks
   `comf` for both. Confirm.
2. **Naming: `stofs_3d_atl_ufs` or `stofs_3d_atl_v2`?** Going with
   `stofs_3d_atl_ufs` to match the SECOFS-UFS convention, but the operational
   ops team may have a preference (the legacy descriptor stays as
   `stofs_3d_atl`).
3. **Resource sizing target.** The legacy nprocs=4320 (4314 compute + 6
   scribes) maps to `partition.prop` rank count for the standalone binary.
   For the UFS-Coastal coupled binary, do we keep the same OCN partition (and
   add 120 ATM/MED on top, total 4434) or do we recompute partition.prop for
   the smaller OCN domain that DATM coupling expects? Commit 1 sets a
   placeholder of `total_tasks: 4312` (4192 OCN + 120 ATM/MED) marked TODO;
   the right value lands in commit 2.

## 7. What lands in this commit (commit 1)

Files added:

- `ush/python/nos_workflow/descriptors/stofs_3d_atl_ufs.py`
- `parm/systems/stofs_3d_atl_ufs.yaml`
- `docs/STOFS_3D_ATL_UFS_PORT_PLAN.md` (this document)

Files modified:

- `ush/python/nos_workflow/tests/test_descriptors.py` (one new test function)

What is NOT touched:

- `ush/python/nos_workflow/descriptors/stofs_3d_atl.py` (the legacy stub) stays
  exactly as-is.
- `ush/python/nos_workflow/descriptors/secofs_ufs.py`, `secofs_ufs.yaml`, and
  every other SECOFS-UFS file is reserved.
- `ush/python/nos_workflow/stages/*.py` `framework="stofs"` branches stay as
  `NotImplementedError` placeholders — the new descriptor uses
  `framework="comf"` and dispatches to the existing canonical body.
- `parm/base/schism.yaml` is unchanged; the new YAML inherits from it.

Validation done before commit:

- `python -m pytest nos_workflow/tests/ -q` from `ush/python/` — 120 passing
  (baseline was 119; the new test function adds one).
- `python -m nos_workflow list` shows `stofs_3d_atl_ufs` row.
- `python -m nos_workflow stages stofs_3d_atl_ufs` prints the 4 canonical
  stages.
