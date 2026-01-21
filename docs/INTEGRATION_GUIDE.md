# NOS OFS Unified Package Integration Guide

This guide describes the recommended approach for integrating the Python-based YAML configuration system into the production nosofs.v3.7.0 workflow.

## Overview

The integration follows a **minimal-change approach** that:
- Adds YAML configuration support at the script level
- Maintains full backward compatibility with legacy `.ctl` files
- Requires no changes to ecFlow, J-jobs, or USH scripts
- Allows parallel testing of YAML vs .ctl configurations

---

## Current Production Workflow

### Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PRODUCTION FLOW (nosofs.v3.7.0)                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  pbs/jnos_secofs_prep_00.pbs                                               │
│  ├── Sources: versions/run.ver                                              │
│  ├── Loads modules (python, wgrib2, netcdf, etc.)                          │
│  ├── Sets environment: OFS=secofs, cyc=00                                  │
│  └── Calls: jobs/JNOS_OFS_PREP                                             │
│                    │                                                        │
│                    ▼                                                        │
│  jobs/JNOS_OFS_PREP                                                        │
│  ├── Sets paths: HOMEnos, FIXofs, USHnos, etc.                             │
│  ├── Creates directories: DATA, COMOUT                                      │
│  └── Calls: scripts/exnos_ofs_prep.sh                                      │
│                    │                                                        │
│                    ▼                                                        │
│  scripts/exnos_ofs_prep.sh                                                 │
│  ├── Sources: ${FIXofs}/secofs.ctl  ← CONFIGURATION LOADED HERE            │
│  ├── Calls: ush/nos_ofs_launch.sh                                          │
│  ├── Calls: ush/nos_ofs_create_forcing_met.sh                              │
│  ├── Calls: ush/nos_ofs_create_forcing_river.sh                            │
│  └── Calls: ush/nos_ofs_create_forcing_obc.sh                              │
│                    │                                                        │
│                    ▼                                                        │
│  ush/nos_ofs_create_forcing_*.sh                                           │
│  └── Uses environment variables: $MINLON, $MAXLON, $DBASE_MET_NOW, etc.    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key Insight

The USH scripts don't care where variables come from - they just use environment variables like `$MINLON`, `$MAXLON`, `$DBASE_MET_NOW`. This means we only need to change HOW variables are loaded, not the scripts that USE them.

---

## Recommended Integration Approach

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    INTEGRATED FLOW (with YAML support)                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  PBS Script        → OPTIONAL: Add OFS_CONFIG env var                       │
│  J-Job             → NO CHANGE                                              │
│  Script            → ADD: YAML loading with .ctl fallback                   │
│  USH Scripts       → NO CHANGE (use env vars as before)                     │
│                                                                             │
│  Configuration Priority:                                                    │
│  1. OFS_CONFIG env var (YAML)                                              │
│  2. ${FIXofs}/${PREFIXNOS}.yaml                                            │
│  3. ${FIXofs}/${PREFIXNOS}.ctl (legacy fallback)                           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Components to Change

| Component | Change Required | Risk Level |
|-----------|-----------------|------------|
| ecf/ | None | - |
| jobs/ | None | - |
| scripts/exnos_ofs_prep.sh | Add YAML loading | Low |
| scripts/exnos_ofs_nowcast_forecast.sh | Add YAML loading | Low |
| ush/*.sh | None | - |
| fix/secofs/secofs.ctl | None (keep for fallback) | - |

### Components to Add

| Component | Purpose |
|-----------|---------|
| ush/python/nos_ofs/ | Python package for YAML processing |
| ush/nos_ofs_config.sh | Helper script for YAML loading |
| parm/systems/secofs.yaml | YAML configuration for SECOFS |
| parm/base/schism.yaml | Base SCHISM configuration |

---

## Complete File List for WCOSS2 Testing

### Files to Copy

The following files from the unified package need to be copied to your production installation:

```bash
# Set your package locations
UNIFIED_PKG=/path/to/nos-workflow/nos_ofs      # Cloned unified package
PROD_DIR=/path/to/nosofs.v3.7.0                # Production installation

# 1. Python package (REQUIRED)
mkdir -p ${PROD_DIR}/ush/python
cp -r ${UNIFIED_PKG}/ush/python/nos_ofs ${PROD_DIR}/ush/python/

# 2. Helper script for config loading (REQUIRED)
cp ${UNIFIED_PKG}/ush/nosofs/nos_ofs_config.sh ${PROD_DIR}/ush/

# 3. YAML configuration files (REQUIRED)
mkdir -p ${PROD_DIR}/parm/systems
mkdir -p ${PROD_DIR}/parm/base
cp ${UNIFIED_PKG}/parm/systems/secofs.yaml ${PROD_DIR}/parm/systems/
cp ${UNIFIED_PKG}/parm/base/schism.yaml ${PROD_DIR}/parm/base/

# 4. Modified shell scripts (BACKUP ORIGINALS FIRST)
cp ${PROD_DIR}/scripts/exnos_ofs_prep.sh ${PROD_DIR}/scripts/exnos_ofs_prep.sh.backup
cp ${PROD_DIR}/scripts/exnos_ofs_nowcast_forecast.sh ${PROD_DIR}/scripts/exnos_ofs_nowcast_forecast.sh.backup
cp ${PROD_DIR}/scripts/exnos_ofs_obs.sh ${PROD_DIR}/scripts/exnos_ofs_obs.sh.backup
cp ${PROD_DIR}/scripts/exnos_ofs_continue_forecast.sh ${PROD_DIR}/scripts/exnos_ofs_continue_forecast.sh.backup

cp ${UNIFIED_PKG}/scripts/nosofs/exnos_ofs_prep.sh ${PROD_DIR}/scripts/
cp ${UNIFIED_PKG}/scripts/nosofs/exnos_ofs_nowcast_forecast.sh ${PROD_DIR}/scripts/
cp ${UNIFIED_PKG}/scripts/nosofs/exnos_ofs_obs.sh ${PROD_DIR}/scripts/
cp ${UNIFIED_PKG}/scripts/nosofs/exnos_ofs_continue_forecast.sh ${PROD_DIR}/scripts/
```

### YAML Loading Methods

The modified scripts use two different approaches for loading YAML configuration:

| Script | YAML Loading Method | Helper Used |
|--------|---------------------|-------------|
| `exnos_ofs_prep.sh` | Sources helper script | `${USHnos}/nos_ofs_config.sh` |
| `exnos_ofs_nowcast_forecast.sh` | Direct Python call | `python3 -m nos_ofs.cli export-env` |
| `exnos_ofs_obs.sh` | Direct Python call | `python3 -m nos_ofs.cli export-env` |
| `exnos_ofs_continue_forecast.sh` | Direct Python call | `python3 -m nos_ofs.cli export-env` |

Both approaches:
- Follow the same priority: `OFS_CONFIG` env var → `FIXofs` YAML → `FIXofs` .ctl
- Fall back to legacy `.ctl` if YAML loading fails
- Export the same environment variables

### Safety Note

The `.ctl` fallback ensures that if YAML loading fails for any reason (missing Python package, parse error, etc.), the scripts will automatically fall back to the original `secofs.ctl` configuration. This makes testing safe - the workflow will continue to work even if YAML integration has issues.

---

## Step-by-Step Integration

### Step 1: Add Python Package

Copy the `nos_ofs` Python package to the production installation:

```bash
# From unified package
cp -r nos_ofs/ush/python/nos_ofs ${HOMEnos}/ush/python/

# Verify structure
ls ${HOMEnos}/ush/python/nos_ofs/
# Should show: __init__.py, cli.py, config/, forcing/, models/, utils/, etc.
```

### Step 2: Add YAML Configurations

```bash
# Create parm directories
mkdir -p ${HOMEnos}/parm/systems
mkdir -p ${HOMEnos}/parm/base

# Copy YAML configs
cp nos_ofs/parm/systems/secofs.yaml ${HOMEnos}/parm/systems/
cp nos_ofs/parm/base/schism.yaml ${HOMEnos}/parm/base/
```

### Step 3: Update Script (exnos_ofs_prep.sh)

Replace the configuration loading section in `scripts/exnos_ofs_prep.sh`:

**Original (lines 24-36):**
```bash
#  Control Files For Model Run
if [ -s ${FIXofs}/${PREFIXNOS}.ctl ]
then
  . ${FIXofs}/${PREFIXNOS}.ctl
else
  echo "${RUN} control file is not found"
  ...
fi
```

**Updated:**
```bash
##############################################################################
# CONFIGURATION LOADING
# Priority: 1. OFS_CONFIG env var (YAML), 2. FIXofs YAML, 3. FIXofs .ctl
##############################################################################

CONFIG_LOADED=0

# Find Python package location for YAML support
for search_path in \
    "${HOMEnos}/ush/python" \
    "$(dirname $0)/../ush/python"
do
    if [ -d "$search_path/nos_ofs" ]; then
        export PYnos_ofs="$search_path"
        break
    fi
done

# Option 1: Load from OFS_CONFIG environment variable (YAML)
if [ "$CONFIG_LOADED" -eq 0 ] && [ -n "$OFS_CONFIG" ] && [ -f "$OFS_CONFIG" ]; then
    echo "Attempting to load YAML config from OFS_CONFIG: $OFS_CONFIG"
    if [ -n "$PYnos_ofs" ]; then
        export PYTHONPATH="${PYnos_ofs}:${PYTHONPATH}"
        yaml_exports=$(python3 -m nos_ofs.cli export-env --config "$OFS_CONFIG" --framework comf 2>/dev/null)
        if [ $? -eq 0 ] && [ -n "$yaml_exports" ]; then
            eval "$yaml_exports"
            CONFIG_LOADED=1
            echo "Configuration loaded from YAML: $OFS_CONFIG"
        else
            echo "WARNING: Failed to parse YAML config: $OFS_CONFIG"
        fi
    fi
fi

# Option 2: Try to find YAML config in FIXofs
if [ "$CONFIG_LOADED" -eq 0 ] && [ -n "$PYnos_ofs" ] && [ -f "${FIXofs}/${PREFIXNOS}.yaml" ]; then
    echo "Attempting to load YAML config from FIXofs: ${FIXofs}/${PREFIXNOS}.yaml"
    export PYTHONPATH="${PYnos_ofs}:${PYTHONPATH}"
    yaml_exports=$(python3 -m nos_ofs.cli export-env --config "${FIXofs}/${PREFIXNOS}.yaml" --framework comf 2>/dev/null)
    if [ $? -eq 0 ] && [ -n "$yaml_exports" ]; then
        eval "$yaml_exports"
        export OFS_CONFIG="${FIXofs}/${PREFIXNOS}.yaml"
        CONFIG_LOADED=1
        echo "Configuration loaded from YAML: ${FIXofs}/${PREFIXNOS}.yaml"
    fi
fi

# Option 3: Fall back to legacy .ctl file
if [ "$CONFIG_LOADED" -eq 0 ]; then
    if [ -s ${FIXofs}/${PREFIXNOS}.ctl ]; then
        . ${FIXofs}/${PREFIXNOS}.ctl
        CONFIG_LOADED=1
        echo "Configuration loaded from legacy .ctl: ${FIXofs}/${PREFIXNOS}.ctl"
    fi
fi

# Verify configuration was loaded
if [ "$CONFIG_LOADED" -eq 0 ]; then
    echo "${RUN} control file is not found, FATAL ERROR!"
    echo "please provide ${RUN} config: ${PREFIXNOS}.yaml or ${PREFIXNOS}.ctl in ${FIXofs}"
    msg="${RUN} control file is not found, FATAL ERROR!"
    postmsg "$jlogfile" "$msg"
    err_chk
fi

echo "Configuration source: $([ -n \"$OFS_CONFIG\" ] && echo 'YAML' || echo '.ctl')"
```

### Step 4: Create Test PBS Script (Optional)

Create `pbs/jnos_secofs_prep_00_yaml.pbs` for testing:

```bash
#!/bin/bash
#PBS  -N secofs_prep_00_yaml
#PBS  -A NOSOFS-DEV
#PBS  -q dev
#PBS  -o /lfs/h1/nos/ptmp/$LOGNAME/rpt/v3.7.0/secofs_prep_00_yaml.out
#PBS  -e /lfs/h1/nos/ptmp/$LOGNAME/rpt/v3.7.0/secofs_prep_00_yaml.err
#PBS  -l place=vscatter,select=1:ncpus=128:mpiprocs=128
#PBS  -l walltime=1:30:00

. /lfs/h1/nos/estofs/noscrub/$LOGNAME/packages/nosofs.v3.7.0/versions/run.ver

# ... (same module loads as original) ...

# === YAML CONFIGURATION ===
export PYnos=${PACKAGEROOT}/nosofs.${nosofs_ver}/ush/python
export PYTHONPATH=${PYnos}:${PYTHONPATH}
export OFS_CONFIG=${PACKAGEROOT}/nosofs.${nosofs_ver}/parm/systems/secofs.yaml
# === END YAML CONFIGURATION ===

export envir=dev
export OFS=secofs
export cyc=00
# ... (rest same as original) ...

/lfs/h1/nos/estofs/noscrub/$LOGNAME/packages/nosofs.${nosofs_ver}/jobs/JNOS_OFS_PREP
```

---

## Testing Procedure

### Test 1: Verify Python Package

```bash
module load python/3.12.0
export PYTHONPATH=${HOMEnos}/ush/python:$PYTHONPATH

# Test import
python3 -c "from nos_ofs.cli import main; print('OK')"

# Test YAML export
python3 -m nos_ofs.cli export-env \
    --config ${HOMEnos}/parm/systems/secofs.yaml \
    --framework comf | head -20
```

### Test 2: Verify Variable Values

```bash
# Export and verify
eval $(python3 -m nos_ofs.cli export-env \
    --config ${HOMEnos}/parm/systems/secofs.yaml \
    --framework comf)

# Check key variables match secofs.ctl
echo "MINLON=$MINLON"           # Should be -88.0
echo "MAXLON=$MAXLON"           # Should be -63.0
echo "OCEAN_MODEL=$OCEAN_MODEL" # Should be SCHISM
echo "TOTAL_TASKS=$TOTAL_TASKS" # Should be 1200
```

### Test 3: Parallel Comparison

```bash
# Run with .ctl (baseline)
unset OFS_CONFIG
qsub jnos_secofs_prep_00.pbs
# Save output to baseline/

# Run with YAML
qsub jnos_secofs_prep_00_yaml.pbs
# Save output to yaml_test/

# Compare forcing files
diff baseline/ yaml_test/
```

---

## Directory Structure After Integration

```
nosofs.v3.7.0/
├── ecf/                          # NO CHANGE
├── jobs/
│   └── JNOS_OFS_PREP             # NO CHANGE
├── scripts/
│   ├── exnos_ofs_prep.sh              # UPDATED (YAML support)
│   ├── exnos_ofs_nowcast_forecast.sh  # UPDATED (YAML support)
│   ├── exnos_ofs_obs.sh               # UPDATED (YAML support)
│   └── exnos_ofs_continue_forecast.sh # UPDATED (YAML support)
├── ush/
│   ├── nos_ofs_config.sh              # NEW (helper for YAML loading)
│   ├── nos_ofs_create_forcing_*.sh    # NO CHANGE
│   └── python/                        # NEW
│       └── nos_ofs/                   # Python package
│           ├── __init__.py
│           ├── cli.py
│           ├── config/
│           ├── forcing/
│           └── utils/
├── parm/                         # NEW/UPDATED
│   ├── base/
│   │   └── schism.yaml
│   └── systems/
│       ├── secofs.yaml
│       └── stofs_3d_atl.yaml
├── fix/
│   └── secofs/
│       └── secofs.ctl            # KEEP (fallback)
├── pbs/
│   ├── jnos_secofs_prep_00.pbs       # ORIGINAL
│   └── jnos_secofs_prep_00_yaml.pbs  # NEW (for testing)
└── versions/
    └── run.ver                   # NO CHANGE
```

---

## YAML vs .ctl Configuration Mapping

| .ctl Variable | YAML Path | Value |
|---------------|-----------|-------|
| `MINLON` | `grid.domain.lon_min` | -88.0 |
| `MAXLON` | `grid.domain.lon_max` | -63.0 |
| `MINLAT` | `grid.domain.lat_min` | 17.0 |
| `MAXLAT` | `grid.domain.lat_max` | 40.0 |
| `OCEAN_MODEL` | `model.ocean_model` | SCHISM |
| `DBASE_MET_NOW` | `forcing.atmospheric.primary` | GFS |
| `DBASE_MET_FOR` | `forcing.atmospheric.forecast_source` | GFS |
| `TOTAL_TASKS` | `resources.nprocs` | 1200 |
| `DELT_MODEL` | `model.physics.dt` | 120.0 |
| `LEN_FORECAST` | `model.run.forecast_days × 24` | 48 |

---

## Rollback Procedure

If issues arise, rollback is simple:

```bash
# Option 1: Unset OFS_CONFIG (falls back to .ctl)
unset OFS_CONFIG

# Option 2: Restore original script
cp scripts/exnos_ofs_prep.sh.backup scripts/exnos_ofs_prep.sh

# Option 3: Use original PBS script
qsub jnos_secofs_prep_00.pbs  # Uses .ctl by default
```

---

## Benefits of YAML Integration

| Benefit | Description |
|---------|-------------|
| **Structured Config** | Hierarchical organization vs flat exports |
| **Inheritance** | Base configs reduce duplication |
| **Validation** | Schema validation possible |
| **Documentation** | Self-documenting with comments |
| **Version Control** | Easier diff/merge than .ctl |
| **Future-Ready** | Foundation for Python-native processors |

---

## Integration Approaches: Current vs Hybrid vs Pure Python

There are three possible approaches for integrating the unified package:

### Approach 1: YAML-to-Shell Bridge (Current/Short-term)

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│ YAML Config │ --> │ export-env   │ --> │ Shell Scripts   │
│ (secofs.yaml)    │ (Python CLI) │     │ (unchanged USH) │
└─────────────┘     └──────────────┘     └─────────────────┘
```

**How it works:**
- YAML configuration is converted to shell environment variables
- Existing USH scripts run unchanged, using env vars as before
- `.ctl` fallback ensures production safety

**Pros:**
- Minimal risk - USH scripts unchanged
- Easy rollback to `.ctl` if issues arise
- Can be tested in parallel with production

**Cons:**
- Shell scripts still do the heavy lifting
- Limited ability to leverage Python ecosystem (xarray, pandas)
- Two config systems to maintain during transition

**Best for:** Initial WCOSS2 testing and validation

---

### Approach 2: Hybrid (Recommended/Medium-term)

```
┌─────────────┐     ┌──────────────────────────────────────┐
│ YAML Config │ --> │ Python Workflow Controller           │
└─────────────┘     │  ├── Native Python (new processors)  │
                    │  └── Shell calls (legacy scripts)    │
                    └──────────────────────────────────────┘
```

**How it works:**
- Python workflow controller orchestrates all stages
- New forcing processors written in Python (GFS, HRRR, NWM)
- Legacy shell scripts called via subprocess where needed
- Gradual migration: replace one processor at a time

**Migration Order (recommended):**
1. Atmospheric forcing (GFS/HRRR) - most complex, highest benefit
2. River forcing (NWM) - already has Python dependencies
3. Ocean boundary conditions (RTOFS) - depends on xarray
4. Tidal forcing - relatively simple

**Pros:**
- Incremental migration reduces risk
- Can leverage Python ecosystem (xarray, dask, pandas)
- Better error handling and logging
- Easier unit testing

**Cons:**
- Mixed shell/Python during transition
- Need to maintain both code paths temporarily

**Best for:** Production deployment after YAML validation

---

### Approach 3: Pure Python (Long-term)

```
┌─────────────┐     ┌──────────────────────────────────────┐
│ YAML Config │ --> │ Pure Python Workflow                 │
└─────────────┘     │  ├── GFSProcessor                    │
                    │  ├── HRRRProcessor                   │
                    │  ├── NWMProcessor                    │
                    │  ├── RTOFSProcessor                  │
                    │  └── TidalProcessor                  │
                    └──────────────────────────────────────┘
```

**How it works:**
- All forcing processors implemented in Python
- No shell script dependencies
- Full Python workflow from config to model input

**Pros:**
- Single language, easier maintenance
- Full Python ecosystem benefits
- Better parallelization with dask/xarray
- Comprehensive unit testing

**Cons:**
- Significant development effort
- Need to replicate Fortran executable functionality
- Higher risk during initial deployment

**Best for:** Future development after hybrid approach is stable

---

### Fortran Wrapper Module

For the hybrid approach, we provide Python wrappers around the production Fortran executables. This ensures:
- **Validated outputs**: Same executables used in production
- **Easy comparison**: Can compare outputs with shell script runs
- **Gradual migration**: Replace wrappers with Python implementations over time

**Available Wrappers** (`nos_ofs/ush/python/nos_ofs/forcing/fortran_wrapper.py`):

| Wrapper Class | Fortran Executable | Purpose |
|--------------|-------------------|---------|
| `MetFileSearchWrapper` | `nos_ofs_met_file_search` | Search for available met files |
| `MetForcingWrapper` | `nos_ofs_create_forcing_met` | Create met forcing files |
| `RiverForcingWrapper` | `nos_ofs_create_forcing_river` | Create river forcing |
| `OBCForcingWrapper` | `nos_ofs_create_forcing_obc_schism` | Create ocean boundary conditions |
| `TidalForcingWrapper` | `nos_ofs_create_forcing_obc_tides` | Create tidal forcing |

**Usage Example:**

```python
from nos_ofs.forcing import get_fortran_wrappers

# Get all wrappers configured for SECOFS
wrappers = get_fortran_wrappers(
    model_type="SCHISM",
    exec_dir="/path/to/nosofs.v3.7.0/exec",
    work_dir="/path/to/DATA"
)

# Search for available GFS files
result = wrappers["met_search"].search(
    time_start="2025010100",
    time_nowcast_end="2025010106",
    time_end="2025010306",
    available_files=gfs_file_list,
)

if result.success:
    filtered_files = wrappers["met_search"].get_filtered_files(result)
    print(f"Found {len(filtered_files)} met files")

# Create met forcing using Fortran executable
result = wrappers["met_forcing"].create_forcing(
    dbase="GFS",
    runtype="nowcast",
    time_start="2025010100",
    time_end="2025010106",
    met_files=filtered_files,
    grid_file="secofs.hgrid.gr3",
    output_prefix="sflux",
)
```

**Environment Requirements:**

The wrappers look for executables in this order:
1. `exec_dir` parameter (if provided)
2. `$EXECnos` environment variable
3. `$HOMEnos/exec` directory
4. Current working directory

---

### Recommended Migration Path

```
Phase 1 (Now)           Phase 2 (After WCOSS2 Test)    Phase 3 (Future)
─────────────────────   ────────────────────────────   ─────────────────
YAML → env → shell      Python + Fortran wrappers      Pure Python

- Test on WCOSS2        - Python workflow controller   - All processors
- Validate YAML output  - Call Fortran via wrappers      in Python
- Compare with .ctl     - Same validated executables   - Remove Fortran
                        - Parallel validation            dependencies
```

**Phase 2 Details (Fortran Wrappers):**
- Python orchestrates the workflow
- Fortran wrappers call production executables (`nos_ofs_met_file_search`, `nos_ofs_create_forcing_met`, etc.)
- Output identical to shell scripts (same Fortran code)
- Enables Python-based logging, error handling, and parallelization

**Current Focus:** Phase 1 - Validate YAML configuration produces identical results to `.ctl` on WCOSS2.

---

## Next Steps After Successful Integration

1. **Validate on WCOSS2** - Run parallel tests with both YAML and .ctl configurations
2. **Compare Outputs** - Ensure YAML produces identical forcing files to .ctl
3. **Verify All Scripts** - Test prep, nowcast_forecast, obs, and continue_forecast
4. **Develop Python Processors** - Replace shell scripts gradually with native Python
5. **Production Deployment** - After thorough validation on WCOSS2

---

## Support

- Repository: https://github.com/mansurjisan/nos-workflow
- Branch: `feature/nos-ofs-unified-package`
