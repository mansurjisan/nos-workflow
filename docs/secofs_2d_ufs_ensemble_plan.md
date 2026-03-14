# SECOFS 2D UFS-Coastal Ensemble Plan

**Status**: Planned — start after 3D UFS ensemble verified on WCOSS2
**Branch**: `secofs-2d-ufs` off `ufs-ens`
**Date**: 2026-03-13

## Motivation

The 3D SECOFS UFS ensemble (63 vertical levels, 1.68M nodes) uses ~1,200 MPI tasks per member with ~2h walltime. This limits practical ensemble size to 5-7 members on WCOSS2. A 2D barotropic version (2 vertical levels, same horizontal grid) runs ~3x faster with ~50x less memory per member, enabling 20-30+ member ensembles for robust water level uncertainty quantification.

## Architecture Overview

```
                    ┌──────────────────────────────────────────┐
                    │           SECOFS 2D UFS Ensemble          │
                    │  Same horizontal grid (1.68M nodes)       │
                    │  2 vertical levels (barotropic)           │
                    │  UFS-Coastal: DATM + SCHISM via CMEPS     │
                    └──────────────────────────────────────────┘

 GEFS Atmospheric Ensemble (20-30 members)
 ┌─────────┬─────────┬─────────┬─────────┬───────────────────┐
 │ gep01   │ gep02   │ gep03   │ ...     │ gep30             │
 │ 0.25°   │ 0.25°   │ 0.25°   │         │ 0.25°             │
 └────┬────┴────┬────┴────┬────┴────┬────┴──────────┬────────┘
      │         │         │         │               │
      ▼         ▼         ▼         ▼               ▼
 ┌────────┐┌────────┐┌────────┐┌────────┐     ┌────────┐
 │Mem 001 ││Mem 002 ││Mem 003 ││Mem 004 │ ... │Mem 030 │
 │DATM+   ││DATM+   ││DATM+   ││DATM+   │     │DATM+   │
 │SCHISM  ││SCHISM  ││SCHISM  ││SCHISM  │     │SCHISM  │
 │2-level ││2-level ││2-level ││2-level │     │2-level │
 └────────┘└────────┘└────────┘└────────┘     └────────┘
      │         │         │         │               │
      └─────────┴─────────┴────┬────┴───────────────┘
                                │
                    ┌───────────▼───────────┐
                    │  Ensemble Statistics   │
                    │  Mean, spread, p5-p95  │
                    │  Station timeseries    │
                    └───────────────────────┘
```

## What Changes from 3D → 2D

### Parameters that change

| Parameter | 3D SECOFS UFS | 2D SECOFS UFS | Why |
|-----------|---------------|---------------|-----|
| `nvrt` | 63 | 2 | Barotropic — no vertical structure |
| `ibc` | 0 | 0 | Same (baroclinic flag, even 2D uses 0) |
| `itur` | 3 (GLS) | 0 | No turbulence closure needed |
| `inu_tr(1:2)` | 2,2 | 0,0 | No T/S nudging |
| T/S OBC | RTOFS 3D | SSH only | No temperature/salinity boundaries |
| 3D output | Yes | No | Only elevation, depth-avg velocity, wind |
| `nprocs` | 1080 (SCHISM) | ~480 | 2D needs far fewer cores |
| DATM tasks | 120 | 120 | Same atmospheric grid |
| Walltime | ~2h | ~30-45 min | No tracer transport |
| Memory/member | ~8 GB | ~0.5 GB | No 3D arrays |
| `perturb_physics` | true | false | Atmospheric-only ensemble |

### What stays the same

- Horizontal grid (1,684,786 nodes, 3,322,329 elements)
- Domain bounds (-88 to -63°E, 17 to 40°N)
- UFS-Coastal coupling (DATM + SCHISM via CMEPS)
- DATM forcing pipeline (GFS/GEFS/HRRR)
- Tidal forcing (8 constituents: M2, S2, N2, K2, K1, O1, P1, Q1)
- River forcing (NWM sources)
- Station output locations (272 stations)
- dt = 120s timestep
- Forecast length: 48h, Nowcast: 6h

## Resource Estimate

**Constraint**: Same total CPU budget as 3D ensemble = **8,400 cores** (7 members × 1,200 cores).

### Recommended: 15 members at 560 cores each

| Component | Tasks | Notes |
|-----------|-------|-------|
| DATM | 60 | Reduced from 120 — GEFS grid (1440×721) is small |
| SCHISM | 500 | 3.3M elements / 500 = 6,600 elements/task (efficient) |
| **Total per member** | **560** | |
| **Members × cores** | **15 × 560 = 8,400** | Fits within 3D budget |

### Scaling options within 8,400-core budget

| Members | Cores/member | DATM | SCHISM | Elements/task | Est. walltime |
|---------|-------------|------|--------|---------------|---------------|
| **15** | **560** | **60** | **500** | **6,645** | **~45 min** |
| 20 | 420 | 40 | 380 | 8,743 | ~60 min |
| 10 | 840 | 80 | 760 | 4,372 | ~30 min |

### Comparison with current 3D ensemble

| Item | 3D (7 members) | 2D (15 members) |
|------|-----------------|------------------|
| Cores per member | 1,200 | 560 |
| Total cores | 8,400 | 8,400 (same budget) |
| Walltime per member | ~2h | ~45 min |
| Members in parallel | 7 | 15 (all at once) |
| Total wall time | ~2h | ~45 min |
| Storage per member | ~2 GB | ~200 MB |

GEFS produces 30 perturbation members at 0.25° resolution, all available from `COMINgefs`. With 15 members we use gep01-gep14 (+ 1 GFS control). Can scale to 20+ members by reducing cores per member.

## Files to Create

### 1. `parm/systems/secofs_2d_ufs.yaml`

New YAML config. Key sections:

```yaml
_base: schism

system:
  name: secofs_2d_ufs
  long_name: "Southeast Coastal Ocean Forecast System - 2D Barotropic (UFS-Coastal)"
  framework: comf
  prefix: secofs_2d_ufs
  model_type: schism

grid:
  n_nodes: 1684786
  n_elements: 3322329
  n_levels: 2           # ← 2D barotropic
  domain:
    lon_min: -88.0
    lon_max: -63.0
    lat_min: 17.0
    lat_max: 40.0

model:
  barotropic: true       # ← flag for scripts to skip T/S
  executable: fv3_coastalS.exe
  ocean_model: SCHISM
  coupling:
    type: ufs_coastal
    mediator: cmeps
    datm_tasks: 60
    schism_tasks: 500    # ← reduced from 1080; 8400 cores / 15 members = 560
    coupling_interval: 120
  physics:
    dt: 120.0
    nws: 4               # NUOPC atmospheric coupling
    ibc: 0
    itur: 0              # No turbulence closure
    nvrt: 2
    nscribes: 0          # CMEPS I/O
  run:
    nowcast_hours: 6
    forecast_hours: 48

forcing:
  atmospheric:
    primary: GFS25
    blend:
      enabled: true
      sources: [GFS25, HRRR]
      resolution: 0.025
  ocean:
    obc:
      ts_source: null     # ← No T/S for barotropic
      obc_mode: non_adjust
    nudging:
      enabled: false      # ← No T/S nudging
  river:
    source: NWM
  tidal:
    constituents: [M2, S2, N2, K2, K1, O1, P1, Q1]

output:
  fields_2d:
    variables: [elevation, dahv, wind_speed]
    interval: 3600
  fields_3d:
    enabled: false        # ← No 3D output
  stations:
    enabled: true
    interval: 360

ensemble:
  enabled: true
  n_members: 15           # 1 control + 14 GEFS (fits 8,400-core budget)
  method: gefs
  perturb_physics: false  # ← Atmospheric-only
  gefs:
    enabled: true
    n_gefs_members: 14    # GEFS gep01-gep14
    members:
      "000":
        label: "control (GFS+HRRR)"
        met_source_1: GFS25
        met_source_2: HRRR
      # 001-014 auto-generated from GEFS_01 to GEFS_14
  resources:
    select: "5:ncpus=128:mpiprocs=112"
    walltime: "01:00:00"

resources:
  nprocs: 560             # 60 DATM + 500 SCHISM
  nodes: 5
  walltime: "01:00:00"
```

### 2. `fix/secofs_2d_ufs/` — Fix files

Most files are symlinks to `fix/secofs_ufs/` (same horizontal grid):

| File | Source | Notes |
|------|--------|-------|
| `secofs_2d_ufs.hgrid.gr3` | Symlink → `secofs_ufs.hgrid.gr3` | Same horizontal grid |
| `secofs_2d_ufs.vgrid.in` | **NEW** | 2-level vertical grid |
| `secofs_2d_ufs.param.nml` | **Modified** from `secofs_ufs.param.nml` | nvrt=2, itur=0, no T/S output |
| `secofs_2d_ufs.station.in` | Symlink → `secofs_ufs.station.in` | Same stations |
| `secofs_2d_ufs.station.lat.lon` | Symlink → `secofs_ufs.station.lat.lon` | Same stations |
| `secofs_2d_ufs.bctides.in` | Symlink → `secofs_ufs.bctides.in` | Same tidal constituents |
| `datm_in.template` | Symlink → `secofs_ufs/datm_in.template` | Same DATM config |
| `datm.streams.template` | Symlink → `secofs_ufs/datm.streams.template` | Same DATM streams |
| `model_configure.template` | Symlink → `secofs_ufs/model_configure.template` | Same UFS driver |
| `ufs.configure` | **Modified** | Fewer SCHISM PETs |
| `fd_ufs.yaml` | Symlink → `secofs_ufs/fd_ufs.yaml` | Same UFS component list |
| `noahmptable.tbl` | Symlink → `secofs_ufs/noahmptable.tbl` | Same land model |

**New `secofs_2d_ufs.vgrid.in`:**
```
2 0 0. !nvrt=2, kz=0 (no Z-levels), h_c=0 (unused)
Z levels
S levels
2 -1.0
2  0.0
```

**Key `param.nml` changes** (from 3D version):
```fortran
! Vertical
nvrt = 2          ! was 63

! Physics
itur = 0          ! was 3 (GLS); no turbulence closure for 2D

! Tracers
ntracers = 0      ! was 2 (T/S); no tracers in barotropic mode
inu_tr(1:2) = 0,0 ! was 2,2; no T/S nudging

! Output (only 2D fields)
iof_hydro(1)  = 1  ! elevation
iof_hydro(14) = 1  ! wind speed
iof_hydro(16) = 1  ! depth-averaged velocity
iof_hydro(18) = 0  ! temperature (OFF)
iof_hydro(19) = 0  ! salinity (OFF)
iof_hydro(26) = 0  ! 3D velocity (OFF)
```

### 3. `pbs/launch_secofs_2d_ufs_ensemble.sh` — Ensemble launcher

Copy from `launch_secofs_ensemble.sh` with these changes:
- Default `OFS=secofs_2d_ufs`
- Default `N_MEMBERS=31` (1 control + 30 GEFS)
- `--ufs` mode is always on (this is UFS-only)
- Resources: `select=5:ncpus=128:mpiprocs=64` per member (vs 10 nodes for 3D)
- Walltime: 1h per member (vs 2h for 3D)
- Batch submission: submit 10 members at a time if queue limits apply
- GEFS atmos prep: generate forcing for 30 GEFS members (vs 5)

### 4. `pbs/jnos_secofs_2d_ufs_*.pbs` — PBS scripts

| Script | Resources | Walltime | Notes |
|--------|-----------|----------|-------|
| `jnos_secofs_2d_ufs_prep_*.pbs` | 1 node, 8 cores | 1h | Same prep, different OFS name |
| `jnos_secofs_2d_ufs_ensemble_member.pbs` | 5 nodes, 64 ppn | 1h | Smaller than 3D |
| `jnos_secofs_2d_ufs_gefs_prep_*.pbs` | 1 node, 8 cores | 3h | 30 members, ~6 min each |
| `jnos_secofs_2d_ufs_ensemble_post.pbs` | 1 node, 8 cores | 1h | Same post framework |

### 5. `ufs.configure` modification

Reduce SCHISM PET count:
```
# 3D: DATM PETs 0-119, SCHISM PETs 120-1199 (1080 SCHISM)
# 2D: DATM PETs 0-59,  SCHISM PETs 60-559   (500 SCHISM, 60 DATM)
EARTH_component_list: MED ATM OCN
ATM_model:            datm
OCN_model:            schism
MED_model:            cmeps

ATM_petlist_bounds:   0 59
OCN_petlist_bounds:   60 559
MED_petlist_bounds:   0 59
```

## Files to Modify

### 1. `ush/nos_ofs_ensemble_run.sh` — BAROTROPIC support

The shared ensemble library needs `BAROTROPIC` checks (already exist for STOFS-2D-ATL, may need review for UFS path):

```bash
# In ensemble_stage_files():
if [ "${BAROTROPIC:-false}" = "true" ]; then
    echo "  Barotropic mode: skipping T/S OBC and nudging files"
    # Skip: TEM_3D.th.nc, SAL_3D.th.nc, uv3D.th.nc
    # Skip: TEM_nudge.gr3, SAL_nudge.gr3
fi
```

### 2. `ush/nos_ofs_model_run.sh` — `_comf_execute_ufs_coastal()`

The UFS execution function already handles datm_in patching and ESMF mesh generation. Need to verify it works with 2-level SCHISM (should be transparent since DATM doesn't care about ocean vertical levels).

### 3. `pbs/launch_secofs_ensemble.sh` — Optional

Add `--2d` flag that sets `OFS=secofs_2d_ufs` and adjusts member count/resources. Or keep as a completely separate launcher (simpler).

## Implementation Sequence

### Phase 1: Fix Files & Config (1-2 hours)

1. Create `fix/secofs_2d_ufs/` directory with symlinks + new vgrid.in
2. Create `secofs_2d_ufs.param.nml` (copy 3D, modify nvrt/itur/tracers)
3. Create `parm/systems/secofs_2d_ufs.yaml`
4. Modify `ufs.configure` for fewer SCHISM PETs

### Phase 2: Launcher & PBS Scripts (1 hour)

5. Create `pbs/launch_secofs_2d_ufs_ensemble.sh`
6. Create PBS job scripts (prep, member, gefs_prep, post)

### Phase 3: Code Changes (30 min)

7. Verify `BAROTROPIC` checks in `nos_ofs_ensemble_run.sh` work for UFS path
8. Verify `nos_ofs_model_run.sh` UFS execution works with nvrt=2

### Phase 4: Testing (iterative)

9. Single deterministic 2D run (1 control member) — verify SCHISM runs with 2 levels
10. 3-member 2D ensemble — verify different GEFS forcing produces spread
11. Scale to 10, then 30 members

## Verification Plan

### Step 1: Single-member deterministic
```bash
# Run 2D control only
./launch_secofs_2d_ufs_ensemble.sh 12 --pdy 20260311 --n-members 1
# Check: SCHISM completes with nvrt=2
# Check: staout_1 has reasonable water levels
# Check: No T/S output files generated
```

### Step 2: 3-member smoke test
```bash
./launch_secofs_2d_ufs_ensemble.sh 12 --pdy 20260311 --n-members 3
# Check: Members 000-002 produce different staout_1
# Check: md5sum shows distinct files (unlike the 3D bug)
# Check: Water level spread is physically reasonable (~0.1-0.5m)
```

### Step 3: Full 30-member ensemble
```bash
./launch_secofs_2d_ufs_ensemble.sh 12 --pdy 20260311
# Check: All 30 members complete
# Check: Ensemble statistics (mean, spread, percentiles)
# Check: PFAS-style plots show clear uncertainty band
# Check: Total wall time < 2h (with parallel member submission)
```

### Step 4: Validation against 3D
```bash
# Compare 2D vs 3D water levels at the 6 target stations
# Expect: Similar mean, 2D may have slightly different tidal amplitudes
# 2D spread (30 members) should better sample atmospheric uncertainty
```

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Separate OFS name (`secofs_2d_ufs`) vs toggle | Separate | Cleaner config, independent fix files, no conditional logic in YAML |
| Separate launcher vs `--2d` flag | Separate | Simpler, different default member counts and resources |
| Physics perturbation | Disabled | 2D barotropic responds mainly to atmospheric forcing; bottom drag perturbation less meaningful without vertical structure |
| GEFS member count | 30 | Use full GEFS ensemble; 2D is cheap enough |
| Horizontal grid | Same as 3D | Identical domain coverage, same station locations, easier comparison |
| SCHISM tasks | 480 (vs 1080) | 2D needs fewer cores; no tracer solve |
| Separate branch | Yes (`secofs-2d-ufs` off `ufs-ens`) | Keep 3D ensemble stable while developing 2D |

## Risk Assessment

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| SCHISM crashes with nvrt=2 + UFS coupling | Low | STOFS-2D-ATL works with nvrt=2 standalone; test UFS coupling early |
| DATM mesh generation fails for 2D | Very low | DATM is atmosphere-side, unaffected by ocean vertical levels |
| 30 GEFS members overwhelm queue | Medium | Submit in batches of 10; use array jobs |
| 2D water levels differ significantly from 3D | Medium | Expected — validate against NWLON tide gauges, not just 3D |
| GEFS atmos prep too slow for 30 members | Low | Each member takes ~5 min; 30 × 5 = 2.5h; parallelize if needed |

## Comparison with Existing 2D Systems

| Feature | STOFS-2D-ATL | SECOFS 2D UFS (proposed) |
|---------|-------------|--------------------------|
| Framework | STOFS (standalone SCHISM) | UFS-Coastal (DATM+SCHISM) |
| Grid | 1.8M nodes | 1.68M nodes |
| Forcing coupling | nws=2 (sflux files) | nws=4 (NUOPC/CMEPS) |
| Ensemble members | 6 (5 GEFS + 1 RRFS) | 31 (30 GEFS + 1 control) |
| Physics perturbation | No | No |
| Executable | pschism_TVD-VL | fv3_coastalS.exe |
| Post-processing | STOFS pipeline | COMF pipeline |

## Dependencies

- **3D UFS ensemble must be verified first** — confirms GEFS forcing pipeline, datm_in patching, ESMF mesh generation all work
- **`fv3_coastalS.exe` on WCOSS2** — already compiled for 3D; should work for 2D without recompilation (SCHISM handles nvrt internally)
- **GEFS data availability** — `COMINgefs` has 30 perturbation members; confirm gep06-gep30 file paths match gep01-gep05 pattern
- **Fix files on WCOSS2** — need to deploy `secofs_2d_ufs.vgrid.in` and modified `param.nml`
