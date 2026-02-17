# GEFS Atmospheric Ensemble Implementation Plan

## Overview

Replace the current 3-source atmospheric ensemble (GFS/HRRR/NAM switching) with GEFS
(Global Ensemble Forecast System) members for both SECOFS and STOFS-3D-ATL. GEFS provides
30 physically consistent perturbation members + 1 control, giving statistically robust
atmospheric uncertainty quantification.

---

## GEFS Data on WCOSS2

### Verified Path
```
/lfs/h1/ops/prod/com/gefs/v12.3/gefs.YYYYMMDD/HH/atmos/
```

### Products Available

| Product | Resolution | Directory | All sflux vars? |
|---------|-----------|-----------|-----------------|
| `pgrb2sp25` | 0.25 deg | `pgrb2sp25/` | **NO** - missing SPFH:2m, PRATE |
| `pgrb2ap5` | 0.50 deg | `pgrb2ap5/` | **YES** - all 8 variables |
| `pgrb2bp5` | 0.50 deg | `pgrb2bp5/` | Supplemental fields |

### WCOSS2 Verification (2026-02-15 12Z, gep01)

**pgrb2sp25 (0.25 deg) - INCOMPLETE for SCHISM:**
```
TMP:2 m above ground        YES
SPFH:2 m above ground       MISSING
UGRD:10 m above ground       YES
VGRD:10 m above ground       YES
PRMSL:mean sea level         YES
PRATE:surface                MISSING
DSWRF:surface                YES
DLWRF:surface                YES
```

**Decision: Must use `pgrb2ap5` (0.50 deg) for GEFS forcing.**
The 0.25 deg product lacks SPFH and PRATE entirely.

**pgrb2ap5 (0.50 deg) - VERIFIED on WCOSS2:**
```
TMP:2 m above ground         YES (direct)
RH:2 m above ground          YES (GEFS has RH, not SPFH — need conversion)
UGRD:10 m above ground       YES (direct)
VGRD:10 m above ground       YES (direct)
PRMSL:mean sea level         YES (direct)
APCP:surface                 YES (GEFS has APCP, not PRATE — need conversion)
DSWRF:surface                YES (direct)
DLWRF:surface                YES (direct)
USWRF:surface                YES (bonus)
ULWRF:surface                YES (bonus)
PRES:surface                 YES (needed for RH→SPFH conversion)
```

**File size**: 15 MB per file (compact — much smaller than GFS 0.25 deg at ~500 MB)
**Forecast hours**: 210 files per member (3-hourly f000-f384 + some extended)

### Variable Conversions Required

GEFS encodes two variables differently from GFS. The GEFS forcing script must convert:

**1. RH → SPFH (Relative Humidity → Specific Humidity)**
```
# Saturation vapor pressure (Tetens formula):
es = 611.2 * exp(17.67 * (T - 273.15) / (T - 29.65))   # T in Kelvin
# Actual vapor pressure:
e = (RH / 100.0) * es
# Specific humidity:
SPFH = 0.622 * e / (P - 0.378 * e)                      # P = surface pressure (Pa)
```
Can be done with `ncap2`:
```bash
ncap2 -s 'spfh=0.622*611.2*exp(17.67*(TMP_2maboveground-273.15)/(TMP_2maboveground-29.65))*(RH_2maboveground/100.0)/(PRES_surface-0.378*611.2*exp(17.67*(TMP_2maboveground-273.15)/(TMP_2maboveground-29.65))*(RH_2maboveground/100.0))'
```

**2. APCP → PRATE (Accumulated Precip → Precip Rate)**
```
# APCP is in kg/m2 accumulated over the forecast interval
# PRATE is in kg/m2/s (instantaneous rate)
# For 3-hourly GEFS: dt = 10800 seconds
PRATE = APCP / 10800.0
```
Can be done with `ncap2`:
```bash
ncap2 -s 'prate=APCP_surface/10800.0'
```

Note: APCP in GEFS is accumulated from the start of the accumulation period (e.g., "0-6 hour acc"),
so for successive time steps we may need to difference consecutive APCP values:
`PRATE(t) = (APCP(t) - APCP(t-1)) / dt`. Check GEFS APCP accumulation convention.

### File Naming Pattern
```
# Control member:
gec00.t{HH}z.pgrb2a.0p50.f{FFF}

# Perturbation members (01-30):
gep{NN}.t{HH}z.pgrb2a.0p50.f{FFF}

# Full path example:
/lfs/h1/ops/prod/com/gefs/v12.3/gefs.20260215/12/atmos/pgrb2ap5/gep01.t12z.pgrb2a.0p50.f006
```

### Key Specs
- **Members**: 31 total (1 control `gec00` + 30 perturbed `gep01`-`gep30`)
- **Cycles**: 00Z, 06Z, 12Z, 18Z (all produce 16-day forecasts)
- **Temporal resolution**: 3-hourly (f000, f003, f006, ..., f240)
- **Extended range**: 6-hourly f246-f384 (0.50 deg only)
- **File size**: ~100-200 MB per file at 0.50 deg (vs ~500 MB for GFS 0.25 deg global)
- **Data retention**: ~20 days rolling archive on WCOSS2

### Comparison with GFS

| Aspect | GFS (current) | GEFS |
|--------|--------------|------|
| Resolution | 0.25 deg | 0.50 deg (pgrb2ap5) |
| Temporal | Hourly (f001-f120) | 3-hourly |
| Members | 1 deterministic | 31 |
| Variable names | Same | Same (GRIB2 encoding identical) |
| File size | ~500 MB/file | ~100-200 MB/file |
| SCHISM wtiminc | 3600 (1hr) | 10800 (3hr) |

---

## SECOFS Implementation

### Member Strategy: 10-16 members

SECOFS is smaller (10 nodes/member, ~2hr walltime), allowing more members.

**Recommended 10-member configuration:**

| Member | Atmos Primary (sflux_1) | Atmos Secondary (sflux_2) | Physics |
|--------|------------------------|--------------------------|---------|
| 000 | GFS control (0.25 deg) | HRRR (3km) | Default |
| 001 | GEFS gep01 (0.50 deg) | HRRR (3km) | Default |
| 002 | GEFS gep02 (0.50 deg) | HRRR (3km) | Default |
| 003 | GEFS gep03 (0.50 deg) | HRRR (3km) | Default |
| 004 | GEFS gep04 (0.50 deg) | HRRR (3km) | Default |
| 005 | GEFS gep05 (0.50 deg) | HRRR (3km) | Default |
| 006 | GEFS gep06 (0.50 deg) | HRRR (3km) | Default |
| 007 | GEFS gep07 (0.50 deg) | HRRR (3km) | Default |
| 008 | GEFS gep08 (0.50 deg) | HRRR (3km) | Default |
| 009 | GEFS gep09 (0.50 deg) | HRRR (3km) | Default |

**Optional 15-member hybrid (GEFS + parameter perturbation):**
- Members 000-009: GEFS atmospheric forcing, default physics
- Members 010-014: GEFS control (gec00), LHS-perturbed physics (rdrg2, zob, akt_bak)

### Resource Budget (10 members)
- Compute: 10 x 10 nodes = 100 nodes concurrent
- Storage: 10 x 2-5 GB = 20-50 GB output
- Walltime: ~2hrs per member (parallel)
- GEFS atmos prep: ~30min (all members in parallel via cfp)

### Processing Approach: COMF Fortran Pipeline

Reuse existing `nos_ofs_create_forcing_met.sh` + `nos_ofs_create_forcing_met_fvcom`:

1. Add `DBASE=GEFS` option to `nos_ofs_create_forcing_met.sh` (~20 lines)
2. New env var `GEFS_MEMBER_ID` (e.g., `gep01`, `gec00`)
3. File search section maps to `${COMINgefs}/gefs.${TMPDATE}/${CYC}/atmos/pgrb2ap5/`
4. Output tar: `${PREFIXNOS}.${cycle}.${PDY}.met.forecast.GEFS_gep01.nc.tar`

The Fortran executable is DBASE-agnostic (reads from `Fortran_met.ctl`), so no Fortran changes needed.

---

## STOFS-3D-ATL Implementation

### Member Strategy: 3-5 members

STOFS is much larger (20 nodes/member, ~6hr walltime, 20-50GB output), limiting member count.

**Recommended 5-member configuration:**

| Member | Atmos Primary (sflux_1) | Atmos Secondary (sflux_2) | Physics |
|--------|------------------------|--------------------------|---------|
| 000 | GFS control (0.25 deg) | HRRR (3km) | Default |
| 001 | GEFS gep01 (0.50 deg) | HRRR (3km) | Perturbed |
| 002 | GEFS gep02 (0.50 deg) | HRRR (3km) | Perturbed |
| 003 | GEFS gep03 (0.50 deg) | HRRR (3km) | Perturbed |
| 004 | GEFS gep04 (0.50 deg) | HRRR (3km) | Perturbed |

**Minimum viable (3 members):**
Members 000, 001, 002 only.

### Resource Budget (5 members)
- Compute: 5 x 20 nodes = 100 nodes concurrent
- Storage: 5 x 20-50 GB = 100-250 GB output
- Walltime: ~6hrs per member (parallel)
- GEFS atmos prep: ~25min (0.50 deg, fewer grid points than GFS)

### Processing Approach: wgrib2/NCO Pipeline

Adapt existing `stofs_3d_atl_create_surface_forcing_gfs.sh`:

1. New script: `stofs_3d_atl_create_surface_forcing_gefs.sh`
2. Input: `GEFS_MEMBER` env var (e.g., `01`, `02`, `c00`)
3. Path: `${COMINgefs}/gefs.${YYYYMMDD}/${HH}/atmos/pgrb2ap5/gep${GEFS_MEMBER}.t${HH}z.pgrb2a.0p50.f${FFF}`
4. Same wgrib2 variable extraction (identical GRIB2 encoding)
5. Reduced file size threshold (~125 MB vs 500 MB for GFS)
6. Output: `${RUN}.${cycle}.gefs_${NN}.{air,prc,rad}.nc` in COMOUTrerun
7. NCO rename script: reuse `stofs_3d_atl_gfs_input_nco_update_var.nco` (same variable names)

### Key Difference: 3-hourly vs hourly
- Current GFS: hourly data, `seq -f "%03g" 1 1 99` (99 files)
- GEFS: 3-hourly data, `seq -f "%03g" 3 3 132` (~44 files)
- SCHISM handles this via `wtiminc` parameter in sflux_inputs.txt
- Fewer files = faster prep (~half the processing time)

---

## Architecture: Shared Prep + GEFS Atmos Prep + Members

```
prep (shared: GFS+HRRR+NWM+RTOFS+tides)
  |
  └─> gefs_atmos_prep (parallel: process N GEFS members via cfp)
        |
        ├─> member_000 (GFS control + HRRR)
        ├─> member_001 (GEFS gep01 + HRRR)
        ├─> member_002 (GEFS gep02 + HRRR)
        ├─> ...
        └─> member_N
              |
              └─> post_ensemble
```

### What's Shared (from prep)
- GFS deterministic forcing (for control member 000)
- HRRR forcing (secondary stack for all members)
- NWM river forcing
- RTOFS ocean boundary conditions
- Tidal forcing (bctides.in)
- Grid files, param.nml template

### What's Per-Member (from gefs_atmos_prep)
- GEFS member atmospheric forcing (sflux stack 1)
- Perturbed param.nml (if using physics perturbation)

### GEFS Atmos Prep Job

Process all GEFS members in parallel using cfp within a single PBS job:

```bash
# Inside JNOS_OFS_ENSEMBLE_ATMOS_PREP, GEFS branch:
cat /dev/null > ${DATA}/gefs_cmdfile

for GEFS_MEM in 01 02 03 04; do
    echo "${USH_SCRIPT} ${GEFS_MEM}" >> ${DATA}/gefs_cmdfile
done

# Run all members in parallel
mpiexec -np 4 -ppn 4 cfp ${DATA}/gefs_cmdfile
```

Each member's GEFS processing takes ~15-25 min, all running simultaneously.

---

## GEFS vs Current Approach: Why Switch?

### Problems with Current GFS/HRRR/NAM Switching
1. Only 3 discrete atmospheric samples — not statistically robust
2. GFS vs NAM differences reflect **structural model biases**, not proper uncertainty
3. HRRR can't be a standalone primary (doesn't cover full domain)
4. NAM domain too small for STOFS-3D-ATL (lat 14-43N vs domain 7-53N)

### Advantages of GEFS
1. **30 physically consistent members** from perturbed initial conditions + stochastic physics
2. **Statistically proper uncertainty**: each member is equally likely
3. **Same model physics**: spread reflects genuine atmospheric uncertainty, not model bias
4. **Same GRIB2 encoding**: minimal processing pipeline changes
5. **Scalable**: use 3 members (research) or 30 (comprehensive)

### What GEFS Does NOT Replace
- **Parameter perturbation** (rdrg2, zob, akt_bak) — GEFS captures atmospheric uncertainty only
- **HRRR blending** — keep HRRR as secondary sflux stack for coastal detail
- **Ocean boundary uncertainty** — would need RTOFS ensemble (future)
- **River forcing uncertainty** — would need NWM ensemble (future)

### Recommended Strategy
**Replace atmospheric source ensemble with GEFS. Retain parameter perturbation.**
- SECOFS: 10 GEFS members + optional 5 parameter-perturbed = 10-15 total
- STOFS: 3-5 GEFS members with physics perturbation on each

---

## Files to Create

| File | System | Description |
|------|--------|-------------|
| `ush/stofs_3d_atl/stofs_3d_atl_create_surface_forcing_gefs.sh` | STOFS | GEFS forcing script (adapt from GFS script) |
| `pbs/jnos_stofs3datl_ensemble_gefs_prep.pbs` | STOFS | PBS for GEFS atmos prep (or reuse existing atmos_prep) |
| `pbs/jnos_secofs_ensemble_gefs_prep.pbs` | SECOFS | PBS for GEFS atmos prep (or reuse existing atmos_prep) |

## Files to Modify

| File | Changes |
|------|---------|
| `ush/nosofs/nos_ofs_create_forcing_met.sh` | Add `DBASE=GEFS` option (~20 lines in file search) |
| `jobs/JNOS_OFS_ENSEMBLE_ATMOS_PREP` | Add GEFS member loop (cfp parallel processing) |
| `jobs/JNOS_OFS_ENSEMBLE_MEMBER` | Recognize GEFS source names in sflux staging |
| `parm/systems/secofs.yaml` | Replace `atmospheric_ensemble` with GEFS config |
| `parm/systems/stofs_3d_atl.yaml` | Replace `atmospheric_ensemble` with GEFS config |
| `ush/python/nos_ofs/ensemble/param_generator.py` | Add `gefs` method mapping members to GEFS IDs |
| `pbs/launch_secofs_ensemble.sh` | Support larger member counts, GEFS prep step |
| `pbs/launch_stofs3datl_ensemble.sh` | Support GEFS prep step |

---

## YAML Configuration (Proposed)

### SECOFS (10 GEFS members)
```yaml
ensemble:
  enabled: true
  n_members: 10
  method: gefs
  seed: 42
  gefs:
    enabled: true
    n_gefs_members: 10
    resolution: "0p50"
    product: "pgrb2ap5"
    control_member: "gec00"
    perturbation_prefix: "gep"
    members:
      "000":
        label: "control (GFS+HRRR)"
        met_source_1: GFS          # Keep deterministic GFS for control
        met_source_2: HRRR
      "001":
        label: "GEFS p01 + HRRR"
        met_source_1: GEFS_01
        met_source_2: HRRR
      "002":
        label: "GEFS p02 + HRRR"
        met_source_1: GEFS_02
        met_source_2: HRRR
      # ... through 009
    extra_sources:
      - GEFS_01
      - GEFS_02
      - GEFS_03
      - GEFS_04
      - GEFS_05
      - GEFS_06
      - GEFS_07
      - GEFS_08
      - GEFS_09
  parameters:         # Optional: physics perturbation on top
    rdrg2:
      min: 0.001
      max: 0.01
      distribution: uniform
    zob:
      min: 0.0001
      max: 0.001
      distribution: log_uniform
    akt_bak:
      min: 1.0e-6
      max: 1.0e-5
      distribution: log_uniform
```

### STOFS-3D-ATL (5 GEFS members)
```yaml
ensemble:
  enabled: true
  n_members: 5
  method: gefs
  seed: 42
  gefs:
    enabled: true
    n_gefs_members: 5
    resolution: "0p50"
    product: "pgrb2ap5"
    control_member: "gec00"
    perturbation_prefix: "gep"
    members:
      "000":
        label: "control (GFS+HRRR)"
        met_source_1: GFS
        met_source_2: HRRR
      "001":
        label: "GEFS p01 + HRRR"
        met_source_1: GEFS_01
        met_source_2: HRRR
      "002":
        label: "GEFS p02 + HRRR"
        met_source_1: GEFS_02
        met_source_2: HRRR
      "003":
        label: "GEFS p03 + HRRR"
        met_source_1: GEFS_03
        met_source_2: HRRR
      "004":
        label: "GEFS p04 + HRRR"
        met_source_1: GEFS_04
        met_source_2: HRRR
    extra_sources:
      - GEFS_01
      - GEFS_02
      - GEFS_03
      - GEFS_04
```

---

## Environment Variables Needed

```bash
# In PBS scripts and run.ver:
export gefs_ver=v12.3
export COMINgefs=/lfs/h1/ops/prod/com/gefs/${gefs_ver}

# Per-member GEFS processing:
export GEFS_MEMBER=01           # Member number (01-30 or c00)
export GEFS_PRODUCT=pgrb2ap5    # Product directory
export GEFS_RESOLUTION=0p50     # Resolution string in filename
```

---

## Verification Checklist

### Pre-Implementation (on WCOSS2)
- [x] Confirm GEFS path: `/lfs/h1/ops/prod/com/gefs/v12.3/` exists
- [x] Confirm pgrb2sp25 (0.25 deg): MISSING SPFH and PRATE
- [ ] Confirm pgrb2ap5 (0.50 deg): has all 8 sflux variables
- [ ] Check pgrb2ap5 file size: `ls -la gep01.t12z.pgrb2a.0p50.f006`
- [ ] Verify 3-hourly availability: `ls gep01.t12z.pgrb2a.0p50.f{003,006,009,012}`
- [ ] Check forecast hour range: `ls gep01.t12z.pgrb2a.0p50.f* | wc -l`
- [ ] Verify control member: `ls gec00.t12z.pgrb2a.0p50.f006`

### Post-Implementation
- [ ] GEFS forcing script generates valid sflux NetCDFs
- [ ] sflux variable names match SCHISM expectations (stmp, spfh, uwind, vwind, prmsl, prate, dswrf, dlwrf)
- [ ] 3-hourly time steps are correct in sflux NetCDF
- [ ] Each GEFS member produces different atmospheric forcing
- [ ] SCHISM runs successfully with GEFS primary + HRRR secondary
- [ ] Ensemble spread is physically reasonable (larger at exposed coast, smaller in estuaries)

---

## Implementation Order

### Phase 1: Verify Data (Day 1)
1. Run pgrb2ap5 wgrib2 check on WCOSS2
2. Confirm all 8 variables present
3. Check file sizes and forecast hour coverage

### Phase 2: STOFS Script (Day 1-2)
1. Create `stofs_3d_atl_create_surface_forcing_gefs.sh` from GFS template
2. Test on WCOSS2 with single GEFS member (manual run)
3. Verify output sflux NetCDF is valid

### Phase 3: SECOFS Integration (Day 2-3)
1. Add `DBASE=GEFS` to `nos_ofs_create_forcing_met.sh`
2. Test with single SECOFS member
3. Verify sflux tar output

### Phase 4: J-Job & Launcher Updates (Day 3-4)
1. Update `JNOS_OFS_ENSEMBLE_ATMOS_PREP` for GEFS member loop
2. Update `JNOS_OFS_ENSEMBLE_MEMBER` for GEFS sflux staging
3. Update YAML configs
4. Update param_generator.py
5. Update PBS launcher scripts

### Phase 5: Full Ensemble Test (Day 4-5)
1. SECOFS 3-member GEFS ensemble test
2. STOFS 3-member GEFS ensemble test
3. Compare spread with current GFS/NAM/HRRR ensemble
