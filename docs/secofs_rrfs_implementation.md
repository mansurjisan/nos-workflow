# RRFS Atmospheric Forcing Implementation for SECOFS Ensemble

## Overview

Ensemble member 005 uses RRFS (Rapid Refresh Forecast System) 3km atmospheric forcing as an alternative to the GFS+HRRR control and GEFS perturbation members. RRFS provides the highest-resolution atmospheric forcing in the ensemble at hourly temporal resolution.

| Property | Value |
|----------|-------|
| **Ensemble Member** | 005 |
| **Resolution** | 3km native (regridded to 0.03° lat/lon) |
| **Temporal** | Hourly |
| **Max Forecast** | 84h (extended cycles 00/06/12/18Z) |
| **WCOSS2 Status** | `para` (not yet operational) |
| **Source Path** | `/lfs/h1/ops/para/com/rrfs/v1.0/rrfs.YYYYMMDD/HH/` |
| **File Pattern** | `rrfs.tHHz.prslev.3km.fFFF.na.grib2` |

## Configuration

### YAML (`parm/systems/secofs.yaml`)

```yaml
ensemble:
  enabled: true
  n_members: 6
  method: gefs
  gefs:
    n_gefs_members: 4          # Does NOT count RRFS
    members:
      "000": { label: "control (GFS+HRRR)", met_source_1: GFS, met_source_2: HRRR }
      "001": { label: "GEFS p01", met_source_1: GEFS_01 }
      "002": { label: "GEFS p02", met_source_1: GEFS_02 }
      "003": { label: "GEFS p03", met_source_1: GEFS_03 }
      "004": { label: "GEFS p04", met_source_1: GEFS_04 }
      "005": { label: "RRFS",     met_source_1: RRFS }
    extra_sources: [GEFS_01, GEFS_02, GEFS_03, GEFS_04, RRFS]
  rrfs:
    enabled: true
    resolution: "3km"
    domain: "na"
    max_forecast_hours: 84
    fallback_source: null       # SECOFS 48h fits within 84h coverage
    version: "v1.0"
    status: "para"
```

## Data Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│  1. ATMOS PREP (JNOS_OFS_ENSEMBLE_ATMOS_PREP)                      │
│     - Reads YAML config, detects RRFS enabled                      │
│     - Sets COMINrrfs, domain bounds, COMOUTrerun                   │
│     - Calls shared RRFS forcing script                              │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│  2. RRFS FORCING SCRIPT                                             │
│     (ush/stofs_3d_atl/stofs_3d_atl_create_surface_forcing_rrfs.sh) │
│                                                                     │
│     a. Collect ~111 hourly RRFS GRIB2 files                        │
│     b. Per timestep:                                                │
│        - Extract vars (TMP, SPFH, UGRD, VGRD, MSLET, PRATE)       │
│        - Regrid Lambert Conformal → regular lat/lon (0.03°)        │
│        - Convert GRIB2 → NetCDF                                    │
│        - Rename MSLET → PRMSL                                      │
│        - Fill missing PRATE with zeros                              │
│     c. Merge all timesteps → single sflux file                     │
│     d. Archive to COMOUTrerun/                                     │
│                                                                     │
│     Output:                                                         │
│       ${COMOUTrerun}/secofs.t12z.rrfs.air.nc                       │
│       ${COMOUTrerun}/secofs.t12z.rrfs.prc.nc                       │
│       (no radiation — RRFS encoding issues)                         │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│  3. MEMBER STAGING (ush/nos_ofs_ensemble_run.sh)                    │
│                                                                     │
│     - Copy RRFS air+prc → member_005/sflux/sflux_{air,prc}_1.1.nc │
│     - Fix time(0): 0.499999 → 0.0 (COMF compatibility)            │
│     - Stage GFS sflux_rad_1.1.nc as radiation fallback             │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│  4. SCHISM EXECUTION (JNOS_OFS_ENSEMBLE_MEMBER)                     │
│                                                                     │
│     member_005/sflux/                                               │
│       ├── sflux_air_1.1.nc   ← RRFS (hourly, 0.03° regridded)    │
│       ├── sflux_prc_1.1.nc   ← RRFS (hourly, 0.03° regridded)    │
│       ├── sflux_rad_1.1.nc   ← GFS fallback                       │
│       └── sflux_inputs.txt                                          │
└─────────────────────────────────────────────────────────────────────┘
```

## Processing Details

### Lambert Conformal Regridding

RRFS native 3km grid is Lambert Conformal, which causes SCHISM's `get_weight()` to abort with "orientation not consistent" — LC quadrilaterals are non-convex in lon/lat space.

**Fix**: Regrid to regular lat/lon using wgrib2:

```bash
RRFS_REGRID_DX=0.03   # ~3.3km, preserves RRFS detail

wgrib2 $input \
  -new_grid_winds earth \
  -new_grid latlon ${LONMIN}:${NLON}:${RRFS_REGRID_DX} \
                   ${LATMIN}:${NLAT}:${RRFS_REGRID_DX} \
  $output
```

- `-new_grid_winds earth` rotates grid-relative winds to Earth-relative
- Reduces file size from ~6GB native to ~1.6GB regridded (SECOFS domain)

### MSLET vs PRMSL

RRFS uses MSLET (Mean Sea Level pressure from ETA model reduction) instead of PRMSL. The script renames after extraction:

```bash
ncrename -O -v MSLET_meansealevel,PRMSL_meansealevel ${file}
```

### NCO Variable Mapping

After regridding, RRFS data uses the same `[latitude,longitude]` dimensions as GFS/GEFS, so the shared NCO script applies:

```
# fix/stofs_3d_atl/stofs_3d_atl_gefs_input_nco_update_var.nco
lon[latitude,longitude] = float(longitude);
lat[latitude,longitude] = float(latitude);
stmp[time,latitude,longitude] = TMP_2maboveground;
spfh[time,latitude,longitude] = SPFH_2maboveground;
uwind[time,latitude,longitude] = UGRD_10maboveground;
vwind[time,latitude,longitude] = VGRD_10maboveground;
prmsl[time,latitude,longitude] = PRMSL_meansealevel;
prate[time,latitude,longitude] = PRATE_surface;
```

### Radiation Fallback

RRFS does not provide usable DSWRF/DLWRF in its GRIB2 output. Member 005 uses GFS radiation:

| sflux file | Source | Resolution |
|------------|--------|------------|
| `sflux_air_1.1.nc` | RRFS | 0.03° hourly |
| `sflux_prc_1.1.nc` | RRFS | 0.03° hourly |
| `sflux_rad_1.1.nc` | GFS  | 0.25° 3-hourly |

### Time Coverage

SECOFS runs a 6h nowcast + 48h forecast = 54h total. RRFS extended cycles provide 84h of data, so **no GFS fallback is needed** for time coverage (unlike STOFS-3D-ATL which needs 108h).

## RRFS vs Other Ensemble Forcing Sources

| Property | GFS+HRRR (Control) | GEFS (001-004) | RRFS (005) |
|----------|-------------------|-----------------|------------|
| **Resolution** | 0.25° + 3km blend | 0.25° | 3km → 0.03° |
| **Temporal** | Hourly | 3-hourly | Hourly |
| **Radiation** | GFS | GEFS (own) | GFS (fallback) |
| **Variables** | All 8 sflux vars | All 8 sflux vars | 6 vars + GFS rad |
| **Forecast Length** | 384h | 384h | 84h |
| **Status** | Operational | Operational | Para |

## Key Files

| File | Purpose |
|------|---------|
| `parm/systems/secofs.yaml` | RRFS configuration (lines 369-391) |
| `jobs/JNOS_OFS_ENSEMBLE_ATMOS_PREP` | Orchestrates RRFS processing for COMF |
| `ush/stofs_3d_atl/stofs_3d_atl_create_surface_forcing_rrfs.sh` | Shared RRFS forcing script (585 lines) |
| `fix/stofs_3d_atl/stofs_3d_atl_gefs_input_nco_update_var.nco` | NCO variable mapping (shared after regridding) |
| `ush/nos_ofs_ensemble_run.sh` | Member staging with time(0) fix |
| `pbs/launch_secofs_ensemble.sh` | PBS launcher (6 members default with `--gefs`) |

## WCOSS2 Launch

```bash
# Full 6-member ensemble (GFS+HRRR control, 4×GEFS, RRFS)
./pbs/launch_secofs_ensemble.sh 12 --gefs --pdy 20260221

# Monitor
qstat -u $LOGNAME
tail -f /lfs/h1/nos/ptmp/$LOGNAME/rpt/secofs/secofs_ens005_12.out
```
