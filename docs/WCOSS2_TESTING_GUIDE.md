# WCOSS2 Testing Guide for NOS OFS Unified Workflow Package

This guide provides step-by-step instructions for testing the NOS OFS Unified Workflow Package on WCOSS2.

## Overview

The NOS OFS Unified Workflow Package enables YAML-driven configuration for NOAA's Operational Forecast Systems. This guide focuses on testing SECOFS and STOFS-3D-ATL on WCOSS2.

**Primary Goals:**
- Validate Python package imports correctly
- Verify YAML config exports to shell variables
- Test integration with existing shell scripts
- Ensure backward compatibility with legacy `.ctl` files

---

## 1. Clone the Repository

```bash
# On WCOSS2
cd /lfs/h2/emc/$USER/nosofs
git clone https://github.com/mansurjisan/nos-workflow.git
cd nos-workflow
git checkout feature/nos-ofs-unified-package
```

---

## 2. Required Directory Structure

```
/lfs/h2/emc/$USER/nosofs/
├── nos-workflow/                    # Cloned repo (HOMEnos)
│   ├── parm/
│   │   ├── base/
│   │   │   └── schism.yaml          # Base SCHISM config
│   │   └── systems/
│   │       ├── secofs.yaml          # SECOFS config
│   │       └── stofs_3d_atl.yaml    # STOFS config
│   ├── scripts/
│   │   └── nosofs/
│   │       ├── exnos_ofs_prep.sh
│   │       └── exnos_ofs_nowcast_forecast.sh
│   ├── ush/
│   │   ├── nosofs/
│   │   │   ├── nos_ofs_create_forcing_met.sh
│   │   │   ├── nos_ofs_create_forcing_river.sh
│   │   │   ├── nos_ofs_create_forcing_obc.sh
│   │   │   └── nos_ofs_config.sh
│   │   └── python/
│   │       └── nos_ofs/             # Python package
│   └── fix/                         # Link to FIX files
│       └── secofs/
│
├── work/                            # Working directory (DATA)
│   └── secofs.20250120/
│
└── com/                             # Output directory (COMOUT)
    └── secofs.20250120/
```

---

## 3. Required Files

### A. From Repository (Clone)

| Directory | Files | Purpose |
|-----------|-------|---------|
| `parm/systems/` | `secofs.yaml`, `stofs_3d_atl.yaml` | System configs |
| `parm/base/` | `schism.yaml` | Base SCHISM config |
| `scripts/nosofs/` | `exnos_ofs_*.sh` | Execution scripts |
| `ush/nosofs/` | `nos_ofs_*.sh` | Utility scripts |
| `ush/python/nos_ofs/` | Python package | YAML processing |

### B. From Production (Link or Copy)

```bash
# FIX files - link from production
ln -s /lfs/h1/ops/prod/packages/nosofs.v3.7.0/fix/secofs ${HOMEnos}/fix/secofs
```

Required FIX files for SECOFS:
- `secofs.hgrid.gr3` - Horizontal grid
- `secofs.vgrid.in` - Vertical grid
- `secofs.station.in` - Station output locations
- `secofs.river.ctl` - River control file
- `secofs.obc.ctl` - Open boundary control file
- `secofs.bctides.in_template` - Tidal boundary template

### C. Input Data Paths (COMIN)

```bash
export COMINgfs=/lfs/h1/ops/prod/com/gfs/v16.3
export COMINrtofs=/lfs/h1/ops/prod/com/rtofs/v2.3
export COMINnwm=/lfs/h1/ops/prod/com/nwm/v3.0
```

---

## 4. Environment Setup

Create `setup_env.sh` in your working directory:

```bash
#!/bin/bash
# WCOSS2 Environment Setup for NOS OFS Unified Package Testing

# Load required modules
module purge
module load envvar/1.0
module load PrgEnv-intel/8.1.0
module load intel/19.1.3.304
module load craype/2.7.13
module load cray-mpich/8.1.12
module load python/3.9.12
module load wgrib2/2.0.8
module load netcdf/4.7.4
module load hdf5/1.10.6

# Set HOMEnos to cloned repo
export HOMEnos=/lfs/h2/emc/$USER/nosofs/nos-workflow/nos_ofs

# NCO standard paths
export FIXofs=${HOMEnos}/fix/secofs
export USHnos=${HOMEnos}/ush/nosofs
export EXECnos=${HOMEnos}/exec
export SCRIPTSnos=${HOMEnos}/scripts/nosofs

# Python package
export PYnos=${HOMEnos}/ush/python
export PYTHONPATH=${PYnos}:${PYTHONPATH}

# OFS identification
export OFS=secofs
export PREFIXNOS=secofs
export RUN=secofs

# Date/cycle
export PDY=20250120
export cyc=06

# YAML config path
export OFS_CONFIG=${HOMEnos}/parm/systems/secofs.yaml

# Working directories
export DATA=/lfs/h2/emc/$USER/nosofs/work/${OFS}.${PDY}
export COMOUT=/lfs/h2/emc/$USER/nosofs/com/${OFS}.${PDY}

# Input data paths (production)
export COMINgfs=/lfs/h1/ops/prod/com/gfs/v16.3
export COMINrtofs=/lfs/h1/ops/prod/com/rtofs/v2.3
export COMINnwm=/lfs/h1/ops/prod/com/nwm/v3.0

# Create directories
mkdir -p $DATA $COMOUT

echo "============================================"
echo "Environment setup complete"
echo "============================================"
echo "HOMEnos:    $HOMEnos"
echo "OFS_CONFIG: $OFS_CONFIG"
echo "DATA:       $DATA"
echo "COMOUT:     $COMOUT"
echo "============================================"
```

---

## 5. Test Cases

### Test 1: Python Package Import

Verify the `nos_ofs` Python package can be imported.

```bash
source setup_env.sh

python3 -c "from nos_ofs.cli import main; print('Import OK')"
python3 -c "import yaml; print(f'PyYAML version: {yaml.__version__}')"
```

**Expected Output:**
```
Import OK
PyYAML version: 6.0
```

### Test 2: YAML Export-Env

Test the YAML to shell variable export functionality.

```bash
source setup_env.sh

python3 -m nos_ofs.cli export-env \
  --config ${OFS_CONFIG} \
  --framework comf | head -20
```

**Expected Output:**
```
export BASE_DATE=2011010100
export CREATE_TIDEFORCING=1
export DBASE_MET_FOR=GFS
export DBASE_MET_NOW=GFS
export DELT_MODEL=120.0
...
```

### Test 3: Variable Loading Verification

Verify that exported variables have correct values.

```bash
source setup_env.sh

# Export YAML to environment
eval $(python3 -m nos_ofs.cli export-env --config ${OFS_CONFIG} --framework comf)

# Verify key variables
echo "=== YAML Variables Loaded ==="
echo "MINLON=$MINLON"                # Expected: -88.0
echo "MAXLON=$MAXLON"                # Expected: -63.0
echo "MINLAT=$MINLAT"                # Expected: 17.0
echo "MAXLAT=$MAXLAT"                # Expected: 40.0
echo "DBASE_MET_NOW=$DBASE_MET_NOW"  # Expected: GFS
echo "TOTAL_TASKS=$TOTAL_TASKS"      # Expected: 1200
echo "OCEAN_MODEL=$OCEAN_MODEL"      # Expected: SCHISM
echo "DELT_MODEL=$DELT_MODEL"        # Expected: 120.0
```

**Expected Output:**
```
=== YAML Variables Loaded ===
MINLON=-88.0
MAXLON=-63.0
MINLAT=17.0
MAXLAT=40.0
DBASE_MET_NOW=GFS
TOTAL_TASKS=1200
OCEAN_MODEL=SCHISM
DELT_MODEL=120.0
```

### Test 4: CLI List Commands

Test the CLI commands for listing systems and stages.

```bash
source setup_env.sh

# List available OFS systems
python3 -m nos_ofs.cli list

# List available workflow stages
python3 -m nos_ofs.cli stages
```

**Expected Output:**
```
Available OFS Systems:
----------------------------------------
  cbofs                (roms)
  creofs               (schism)
  secofs               (schism)
  stofs_3d_atl         (schism)
  ...

Available Workflow Stages:
------------------------------------------------------------

STOFS Framework (stofs_3d_atl, stofs_3d_pac):
  prep_nowcast       Prepare all forcing data
  now_forecast       Run combined nowcast + forecast simulation
  ...
```

### Test 5: Script Config Loading (Dry Run)

Test that shell scripts correctly load YAML configuration.

```bash
source setup_env.sh

cd $DATA

# Run prep script - will fail at forcing (no data) but should load config
bash -x ${SCRIPTSnos}/exnos_ofs_prep.sh 2>&1 | head -100
```

**Look for:**
```
Configuration loaded from YAML: /lfs/h2/emc/.../secofs.yaml
```

### Test 6: Full PREP Stage (With Input Data)

If input data is available, run the full prep stage.

```bash
source setup_env.sh

cd $DATA
${SCRIPTSnos}/exnos_ofs_prep.sh 2>&1 | tee prep.log

# Check output
ls -la $DATA/
```

---

## 6. PBS Job Script for Testing

Create `test_yaml_wcoss2.sh`:

```bash
#!/bin/bash
#PBS -N test_nos_ofs_yaml
#PBS -l select=1:ncpus=1:mem=4GB
#PBS -l walltime=00:30:00
#PBS -q dev
#PBS -A NOSOFS-DEV
#PBS -o /lfs/h2/emc/$USER/nosofs/logs/test_yaml.out
#PBS -e /lfs/h2/emc/$USER/nosofs/logs/test_yaml.err

set -x
cd $PBS_O_WORKDIR

# Source environment
source /lfs/h2/emc/$USER/nosofs/setup_env.sh

echo "=========================================="
echo "TEST 1: Python Import"
echo "=========================================="
python3 -c "from nos_ofs.cli import main; print('PASS: Import OK')" || echo "FAIL: Import"

echo "=========================================="
echo "TEST 2: PyYAML Available"
echo "=========================================="
python3 -c "import yaml; print(f'PASS: PyYAML {yaml.__version__}')" || echo "FAIL: PyYAML"

echo "=========================================="
echo "TEST 3: YAML Export"
echo "=========================================="
python3 -m nos_ofs.cli export-env --config ${OFS_CONFIG} --framework comf > /tmp/yaml_export.sh
if [ $? -eq 0 ]; then
    echo "PASS: YAML export successful"
    echo "First 10 variables:"
    head -10 /tmp/yaml_export.sh
else
    echo "FAIL: YAML export failed"
fi

echo "=========================================="
echo "TEST 4: Variable Loading"
echo "=========================================="
eval $(python3 -m nos_ofs.cli export-env --config ${OFS_CONFIG} --framework comf)

test_var() {
    local var_name=$1
    local expected=$2
    local actual=${!var_name}
    if [ "$actual" = "$expected" ]; then
        echo "PASS: $var_name=$actual"
    else
        echo "FAIL: $var_name expected '$expected', got '$actual'"
    fi
}

test_var "MINLON" "-88.0"
test_var "MAXLON" "-63.0"
test_var "MINLAT" "17.0"
test_var "MAXLAT" "40.0"
test_var "OCEAN_MODEL" "SCHISM"
test_var "DBASE_MET_NOW" "GFS"

echo "=========================================="
echo "TEST 5: CLI Commands"
echo "=========================================="
echo "--- OFS List ---"
python3 -m nos_ofs.cli list | head -10

echo "--- Stages ---"
python3 -m nos_ofs.cli stages | head -15

echo "=========================================="
echo "TEST 6: Total Variables Exported"
echo "=========================================="
var_count=$(python3 -m nos_ofs.cli export-env --config ${OFS_CONFIG} --framework comf | wc -l)
echo "Total variables exported: $var_count"

echo "=========================================="
echo "ALL TESTS COMPLETE"
echo "=========================================="
```

Submit with:
```bash
qsub test_yaml_wcoss2.sh
```

---

## 7. Validation Checklist

Use this checklist to track testing progress:

```
[ ] Python 3.9+ available (module load python/3.9.12)
[ ] PyYAML importable (python3 -c "import yaml")
[ ] nos_ofs package importable
[ ] export-env produces correct output format
[ ] All 67 variables exported correctly
[ ] Variables match expected values from secofs.yaml
[ ] Scripts detect OFS_CONFIG environment variable
[ ] Scripts load YAML configuration successfully
[ ] Scripts fall back to .ctl if YAML not found
[ ] Prep stage runs without configuration errors
[ ] Output files generated in correct locations
```

---

## 8. Troubleshooting

### Python Import Errors

```bash
# Check Python version
python3 --version  # Should be 3.9+

# Check PYTHONPATH
echo $PYTHONPATH  # Should include ush/python

# Check package location
ls -la ${HOMEnos}/ush/python/nos_ofs/
```

### YAML Not Found

```bash
# Verify config file exists
ls -la ${OFS_CONFIG}

# Check file is readable
cat ${OFS_CONFIG} | head -20
```

### Variables Not Set

```bash
# Debug export-env
python3 -m nos_ofs.cli export-env --config ${OFS_CONFIG} --framework comf 2>&1

# Check for errors in YAML syntax
python3 -c "import yaml; yaml.safe_load(open('${OFS_CONFIG}'))"
```

### Script Falls Back to .ctl

This is expected behavior if:
- `OFS_CONFIG` not set
- YAML file not found
- Python not available
- PyYAML import fails

Check script output for:
```
Configuration loaded from legacy .ctl: /path/to/secofs.ctl
```

---

## 9. Expected Results

After successful testing, you should see:

1. **Python tests pass** - All imports work
2. **67 variables exported** - From YAML config
3. **Correct values** - Match secofs.yaml definitions
4. **Scripts load YAML** - "Configuration loaded from YAML" message
5. **Backward compatible** - Falls back to .ctl when needed

---

## 10. Next Steps After Validation

Once WCOSS2 testing passes:

1. **Run parallel tests** - Compare YAML vs .ctl output
2. **Full cycle test** - PREP → NOWCAST → FORECAST → POST
3. **Performance check** - Verify no significant overhead
4. **Move to hybrid approach** - Develop Python processors

---

## Contact

For issues or questions about this testing guide:
- Repository: https://github.com/mansurjisan/nos-workflow
- Branch: `feature/nos-ofs-unified-package`
