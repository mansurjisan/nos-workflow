# NOS-OFS ecFlow Suite

This directory contains the ecFlow suite definition for the NOS-OFS unified
workflow package. It manages scheduling and dependency resolution for all
NOS Operational Forecast Systems across three framework types.

## Directory Structure

```
ecf/
  def/
    nosofs_suite.py   # Python suite definition (primary)
    nosofs.def        # Text format suite definition (generated)
  include/
    head.h            # ecFlow job header (PBS directives, module loads)
    tail.h            # ecFlow job trailer (error handling, cleanup)
  jnos_ofs_prep.ecf         # Preprocessing ecf script
  jnos_ofs_nowcast.ecf      # Nowcast ecf script
  jnos_ofs_forecast.ecf     # Forecast ecf script
  jnos_ofs_post.ecf         # Post-processing ecf script
```

## Workflow Patterns

All frameworks use split-job mode with separate nowcast and forecast jobs:

```
prep -> nowcast -> forecast -> post
```

- **prep**: Create forcing files and configure model
- **nowcast**: Run model for nowcast period, archive hotstart
- **forecast**: Restore hotstart, run model for forecast period
- **post**: Process and distribute output products

### STOFS Framework (stofs_3d_atl, stofs_3d_pac)

STOFS adds a second post-processing stage:

```
prep -> nowcast -> forecast -> post_1 -> post_2
```

- **post_1**: Extract 2D fields and station timeseries
- **post_2**: Generate ADCIRC-format NetCDF, GeoPackage, AWIPS/SHEF

## Loading the Suite

### Using the Python API (recommended)

```bash
# On WCOSS2 where ecflow module is available:
module load ecflow
python nosofs_suite.py --output nosofs.def --validate
ecflow_client --load nosofs.def
```

### Using text-only generation

```bash
# On any system with Python 3 (no ecflow module needed):
python nosofs_suite.py --text-only --output nosofs.def

# Then transfer nosofs.def to WCOSS2 and load:
ecflow_client --load nosofs.def
```

### Replacing an existing suite

```bash
ecflow_client --replace /nosofs nosofs.def
```

## Modifying for Development/Testing

### Change to dev environment

Override suite-level variables in the ecFlow GUI or via CLI:

```bash
ecflow_client --alter change variable ENVIR dev /nosofs
ecflow_client --alter change variable PACKAGEROOT /lfs/h1/nos/estofs/noscrub/$USER/packages /nosofs
ecflow_client --alter change variable SENDCOM NO /nosofs
ecflow_client --alter change variable SENDDBN NO /nosofs
ecflow_client --alter change variable KEEPDATA YES /nosofs
```

### Run a single OFS cycle manually

```bash
# Force-trigger secofs cycle 00:
ecflow_client --force=set /nosofs/secofs/cyc00 queued

# Or force a single task:
ecflow_client --force=set /nosofs/secofs/cyc00/prep queued
```

### Suspend/resume an OFS family

```bash
ecflow_client --suspend /nosofs/stofs_3d_atl
ecflow_client --resume /nosofs/stofs_3d_atl
```

## Variable Reference

### Suite-level Variables

| Variable | Default | Description |
|----------|---------|-------------|
| ENVIR | prod | Environment (prod or dev) |
| PACKAGEROOT | /lfs/h1/nos/nosofs/noscrub/packages | Package installation root |
| NOSOFS_VER | v3.7.0 | Package version |
| COMROOT | /lfs/h1/ops/prod/com | COM output root |
| DCOMROOT | /lfs/h1/ops/prod/dcom | DCOM input root |
| KEEPDATA | NO | Retain working directory after job |
| SENDCOM | YES | Copy products to COM |
| SENDDBN | YES | Send data to DBNet |
| ECF_FILES | (derived) | Path to .ecf scripts |
| ECF_INCLUDE | (derived) | Path to include headers |
| ECF_TRIES | 2 | Number of retry attempts per task |

### Family-level Variables

| Variable | Example | Description |
|----------|---------|-------------|
| OFS | secofs | OFS system name |
| NET | nosofs | Network identifier (nosofs or stofs) |
| VER_FILE | run.ver | Version file relative path |
| CYC | 00 | Cycle hour (zero-padded) |

### Task-level Variables

| Variable | Example | Description |
|----------|---------|-------------|
| RESOURCES | select=10:ncpus=128:mpiprocs=120 | PBS resource select statement |
| WALLTIME | 05:30:00 | PBS walltime limit |
| POST_STAGE | 1 | STOFS post-processing stage (1 or 2) |

## OFS Systems and Schedules

| OFS | Framework | Cycles (UTC) | Compute Nodes | Walltime |
|-----|-----------|-------------|---------------|----------|
| stofs_3d_atl | STOFS | 12 | 20 | 06:00:00 |
| stofs_3d_pac | STOFS | 12 | 20 | 06:00:00 |
| stofs_2d_glo | ADCIRC | 00,06,12,18 | 8 | 03:00:00 |
| secofs | COMF | 00,06,12,18 | 10 | 05:30:00 |
| creofs | COMF | 03,09,15,21 | 10 | 05:30:00 |
| cbofs | COMF | 00,06,12,18 | 3 | 01:00:00 |
| dbofs | COMF | 00,06,12,18 | 3 | 01:00:00 |
| leofs | COMF | 00,06,12,18 | 3 | 01:00:00 |
| ngofs2 | COMF | 00,06,12,18 | 3 | 01:00:00 |

## Job Limit

The suite enforces a global limit of 20 concurrent jobs (`max_jobs`) to
prevent overloading the WCOSS2 PBS queue. This can be adjusted:

```bash
ecflow_client --alter change limit_max max_jobs 30 /nosofs
```

## J-Jobs Reference

The .ecf scripts invoke these J-jobs from the `jobs/` directory:

| ecf Script | J-Job | Description |
|-----------|-------|-------------|
| jnos_ofs_prep.ecf | JNOS_OFS_PREP | Preprocessing and forcing |
| jnos_ofs_nowcast.ecf | JNOS_OFS_NOWCAST | Nowcast model run |
| jnos_ofs_forecast.ecf | JNOS_OFS_FORECAST | Forecast model run |
| jnos_ofs_post.ecf | JNOS_OFS_POST | Post-processing |
