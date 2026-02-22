# RRFS Atmospheric Forcing Implementation for STOFS-3D-ATL Ensemble

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

### YAML (`parm/systems/stofs_3d_atl.yaml`)

```yaml
ensemble:
  enabled: true
  n_members: 6
  method: gefs
  gefs:
    n_gefs_members: 5          # Includes control in count
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
    fallback_source: GFS        # GFS backfill for hours 84-108
    version: "v1.0"
    status: "para"
```

### Domain Bounds

```yaml
grid:
  domain:
    lon_min: -98.5035
    lon_max: -52.4867
    lat_min: 7.347
    lat_max: 52.5904
```

The STOFS-3D-ATL domain is significantly larger than SECOFS (-88 to -63°, 17-40°N), covering the full western Atlantic from the Gulf of Mexico to Newfoundland.

## Data Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│  1. ATMOS PREP (JNOS_OFS_ENSEMBLE_ATMOS_PREP)                      │
│     - Reads YAML config, detects RRFS enabled                      │
│     - STOFS framework branch: calls RRFS script directly           │
│     - Sets COMINrrfs, domain bounds, COMOUTrerun                   │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│  2. RRFS FORCING SCRIPT                                             │
│     (ush/stofs_3d_atl/stofs_3d_atl_create_surface_forcing_rrfs.sh) │
│                                                                     │
│     a. Collect ~111 hourly RRFS GRIB2 files (cycle-aware)          │
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
│       ${COMOUTrerun}/stofs_3d_atl.t12z.rrfs.air.nc                 │
│       ${COMOUTrerun}/stofs_3d_atl.t12z.rrfs.prc.nc                 │
│       (no radiation — RRFS encoding issues)                         │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│  3. MEMBER STAGING (ush/nos_ofs_ensemble_run.sh)                    │
│     _ensemble_stofs_stage_atmos()                                   │
│                                                                     │
│     - Copy RRFS air+prc → member_005/sflux/sflux_{air,prc}_1.0001.nc│
│     - Stage GFS sflux_rad_1.0001.nc as radiation fallback           │
│     - STOFS uses .0001.nc naming (not .1.nc like COMF)              │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│  4. SCHISM EXECUTION (JNOS_OFS_ENSEMBLE_MEMBER)                     │
│     34 nodes × 128 cores = 4352 (4314 compute + 6 I/O scribes)     │
│     Walltime: 6 hours                                               │
│                                                                     │
│     member_005/sflux/                                               │
│       ├── sflux_air_1.0001.nc  ← RRFS (hourly, 0.03° regridded)  │
│       ├── sflux_prc_1.0001.nc  ← RRFS (hourly, 0.03° regridded)  │
│       ├── sflux_rad_1.0001.nc  ← GFS fallback                     │
│       └── sflux_inputs.txt                                          │
└─────────────────────────────────────────────────────────────────────┘
```

## Time Coverage and GFS Fallback

### The 84h Gap Problem

STOFS-3D-ATL runs a 24h nowcast + 108h forecast = **132h total**. RRFS extended cycles only provide **84h** of forecast data.

```
                    RRFS coverage (84h)
    ├───────────────────────────────────────┤
    |  nowcast (24h)  |      forecast (108h)          |
    ├─────────────────┼───────────────────────────────┤
                                            ├─────────┤
                                            GFS backfill
                                            (hours 84-108)
```

### Fallback Configuration

```yaml
rrfs:
  max_forecast_hours: 84
  fallback_source: GFS          # Backfill for hours beyond RRFS coverage
```

The RRFS forcing script collects files up to the 84h limit. For the remaining 24h (hours 84-108), the ensemble staging function falls back to GFS atmospheric forcing from the control member's prep output.

### Comparison with SECOFS

| | STOFS-3D-ATL | SECOFS |
|---|---|---|
| **Forecast length** | 108h | 48h |
| **RRFS coverage** | 84h | 84h |
| **Gap** | 24h (needs GFS backfill) | None (fully covered) |
| **`fallback_source`** | `GFS` | `null` |

## Processing Details

### Lambert Conformal Regridding

RRFS native 3km grid is Lambert Conformal, which causes SCHISM's `get_weight()` to abort with "orientation not consistent" — LC quadrilaterals are non-convex in lon/lat space.

```bash
RRFS_REGRID_DX=0.03   # ~3.3km, preserves RRFS detail

wgrib2 $input \
  -new_grid_winds earth \
  -new_grid latlon ${LONMIN}:${NLON}:${RRFS_REGRID_DX} \
                   ${LATMIN}:${NLAT}:${RRFS_REGRID_DX} \
  $output
```

- `-new_grid_winds earth` rotates grid-relative winds to Earth-relative
- STOFS-3D-ATL regrid target: ~1535 × 1508 grid points (vs SECOFS ~834 × 767)
- Reduces native ~6GB files to ~2GB (STOFS-3D-ATL domain)

### Cycle-Aware File Collection

The RRFS forcing script uses different file collection strategies depending on cycle time:

**12Z cycle (primary STOFS-3D-ATL cycle):**
```
Nowcast period (24h lookback):
  prev-day 06Z f006             (1 file)
  prev-day 12Z f001-f006        (6 files)
  prev-day 18Z f001-f006        (6 files)
  today    00Z f001-f006        (6 files)
  today    06Z f001-f006        (6 files)
                                ─────────
                                25 files

Forecast period (84h ahead):
  today 12Z extended f001-f084  (84 files)
                                ─────────
Total: ~109 hourly files
```

Each file entry stores `VALID_HOUR|FILEPATH` for proper time-ordering when stitching files from multiple cycles. Deduplication prevents duplicate valid times.

### MSLET vs PRMSL

RRFS uses MSLET (Mean Sea Level pressure from ETA model reduction) instead of PRMSL:

```bash
ncrename -O -v MSLET_meansealevel,PRMSL_meansealevel ${file}
```

### NCO Variable Mapping

After regridding, RRFS uses the same `[latitude,longitude]` dimensions as GFS/GEFS:

```
# fix/stofs_3d_atl/stofs_3d_atl_gefs_input_nco_update_var.nco
time[time]                                = float(tin/24.);
lon[latitude,longitude]                   = float(longitude);
lat[latitude,longitude]                   = float(latitude);
stmp[time,latitude,longitude]             = TMP_2maboveground;
spfh[time,latitude,longitude]             = SPFH_2maboveground;
uwind[time,latitude,longitude]            = UGRD_10maboveground;
vwind[time,latitude,longitude]            = VGRD_10maboveground;
prmsl[time,latitude,longitude]            = PRMSL_meansealevel;
prate[time,latitude,longitude]            = PRATE_surface;
```

### Radiation Fallback

RRFS DSWRF/DLWRF variables have inconsistent wgrib2 `-netcdf` naming (averaged fields get suffixes that don't match the NCO rename script). Member 005 uses GFS radiation:

| sflux file | Source | Resolution |
|------------|--------|------------|
| `sflux_air_1.0001.nc` | RRFS | 0.03° hourly |
| `sflux_prc_1.0001.nc` | RRFS | 0.03° hourly |
| `sflux_rad_1.0001.nc` | GFS  | 0.25° 3-hourly |

### QC Thresholds

```bash
FILESIZE=500000000      # Minimum 500MB per RRFS GRIB2 file (native ~6GB)
N_dim_cr_min_cntList=30 # Minimum 30 timesteps for valid merged file
N_dim_cr_min=70         # Minimum 70 timesteps (~2.9 days) for archival QC
N_dim_cr_max=100        # Expected ~100 timesteps (~4.2 days)
list_fn_sz_cr=(2000000) # Merged file size threshold (~2GB for STOFS-ATL)
```

## Sflux File Naming Conventions

### STOFS vs COMF

| Convention | STOFS-3D-ATL | SECOFS (COMF) |
|------------|-------------|---------------|
| **Air forcing** | `sflux_air_1.0001.nc` | `sflux_air_1.1.nc` |
| **Precip** | `sflux_prc_1.0001.nc` | `sflux_prc_1.1.nc` |
| **Radiation** | `sflux_rad_1.0001.nc` | `sflux_rad_1.1.nc` |

### COMOUTrerun Archive Names

```
${RUN}.${cycle}.rrfs.air.nc     # e.g., stofs_3d_atl.t12z.rrfs.air.nc
${RUN}.${cycle}.rrfs.prc.nc     # e.g., stofs_3d_atl.t12z.rrfs.prc.nc
```

No `.rad.nc` archived — radiation comes from GFS.

## RRFS vs Other Ensemble Forcing Sources

| Property | GFS+HRRR (Control) | GEFS (001-004) | RRFS (005) |
|----------|-------------------|-----------------|------------|
| **Resolution** | 0.25° + 3km blend | 0.25° | 3km → 0.03° |
| **Temporal** | Hourly | 3-hourly | Hourly |
| **Radiation** | GFS | GEFS (own) | GFS (fallback) |
| **Variables** | All 8 sflux vars | All 8 sflux vars | 6 vars + GFS rad |
| **Forecast Length** | 384h | 384h | 84h (+GFS backfill) |
| **Pressure Var** | PRMSL | PRMSL | MSLET → PRMSL |
| **Humidity Var** | RH (converted) | SPFH | SPFH |
| **Precip Var** | APCP (converted) | PRATE | PRATE |
| **Native Grid** | Gaussian | Gaussian | Lambert Conformal |
| **Status** | Operational | Operational | Para |

## PBS Resources

### Atmospheric Prep (`jnos_stofs3datl_ensemble_atmos_prep.pbs`)

```
#PBS -l select=1:ncpus=128:mpiprocs=8
#PBS -l walltime=02:00:00
```

- 8 MPI procs: wgrib2/NCO are serial; parallel only via `cfp` for GEFS members
- GEFS members processed in parallel, RRFS processed sequentially
- 2-hour walltime accounts for large RRFS GRIB2 files

### Ensemble Member (`jnos_stofs3datl_ensemble_member.pbs`)

```
#PBS -l select=34:ncpus=128:mpiprocs=128
#PBS -l place=vscatter:exclhost
#PBS -l walltime=06:00:00
```

- 34 nodes × 128 cores = 4352 total (4314 compute + 6 I/O scribes)
- MPI tuning for WCOSS2:
  ```bash
  export MPICH_OFI_STARTUP_CONNECT=1
  export MPICH_COLL_SYNC=MPI_Bcast
  export MPICH_REDUCE_NO_SMP=1
  export FI_OFI_RXM_SAR_LIMIT=1572864
  ```

## PBS Launcher Dependency Chain

```
./launch_stofs3datl_ensemble.sh 12 --gefs --pdy 20260221
```

```
prep ─────────┐
              ▼
         atmos_prep (GEFS 01-04 + RRFS)
              │
              ├──→ member_000 (control GFS+HRRR) ──┐
              ├──→ member_001 (GEFS gep01)         ──┤
              ├──→ member_002 (GEFS gep02)         ──┤
              ├──→ member_003 (GEFS gep03)         ──┼──→ post_ensemble
              ├──→ member_004 (GEFS gep04)         ──┤
              └──→ member_005 (RRFS 3km)           ──┘
```

All members run in parallel after atmos_prep completes. Post-processing waits for all members to finish.

### Launcher Options

```bash
# Full 6-member GEFS+RRFS ensemble
./launch_stofs3datl_ensemble.sh 12 --gefs --pdy 20260221

# Smaller test (3 members: control + 2 GEFS)
./launch_stofs3datl_ensemble.sh 12 3 --gefs --pdy 20260221

# Ensemble + deterministic in parallel
./launch_stofs3datl_ensemble.sh 12 --gefs --with-det --pdy 20260221

# Deterministic only (prep → nowcast → forecast)
./launch_stofs3datl_ensemble.sh 12 --det-only --pdy 20260221
```

## Key Files

| File | Purpose |
|------|---------|
| `parm/systems/stofs_3d_atl.yaml` | RRFS + ensemble configuration |
| `jobs/JNOS_OFS_ENSEMBLE_ATMOS_PREP` | Orchestrates RRFS + GEFS processing |
| `ush/stofs_3d_atl/stofs_3d_atl_create_surface_forcing_rrfs.sh` | RRFS forcing script (585 lines) |
| `fix/stofs_3d_atl/stofs_3d_atl_gefs_input_nco_update_var.nco` | NCO variable mapping (shared after regridding) |
| `ush/nos_ofs_ensemble_run.sh` | Member staging with STOFS `.0001.nc` naming |
| `scripts/stofs_3d_atl/exnos_ofs_ensemble_member.sh` | STOFS member execution script |
| `pbs/launch_stofs3datl_ensemble.sh` | PBS launcher with dependency chain |
| `pbs/jnos_stofs3datl_ensemble_member.pbs` | PBS resources (34 nodes, 6h) |
| `pbs/jnos_stofs3datl_ensemble_atmos_prep.pbs` | PBS resources (1 node, 2h) |

## Differences from SECOFS RRFS Implementation

| Aspect | STOFS-3D-ATL | SECOFS |
|--------|-------------|--------|
| **Framework** | STOFS | COMF |
| **Domain** | -98.5 to -52.5°, 7.3-52.6°N | -88 to -63°, 17-40°N |
| **Regrid size** | ~1535 × 1508 | ~834 × 767 |
| **Forecast** | 108h (exceeds RRFS 84h) | 48h (within RRFS 84h) |
| **GFS fallback** | Required (hours 84-108) | Not needed |
| **sflux naming** | `.0001.nc` | `.1.nc` |
| **time(0) fix** | Not needed (native STOFS) | Required (0.499999 → 0.0) |
| **Cores per member** | 4352 (34 nodes) | 480 (4 nodes) |
| **Walltime** | 6 hours | 1.5 hours |
| **n_gefs_members** | 5 (includes control) | 4 (excludes control) |
