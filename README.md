# NOS OFS Unified Workflow Package

Unified Python package for NOAA's Operational Ocean Forecast Systems, supporting both STOFS and nosofs/COMF frameworks with YAML-driven configuration.

## Architecture

```
nos_ofs/
├── ecf/                          # ECFLOW scripts
├── jobs/                         # J-jobs (NCO standard)
│   ├── JNOS_OFS_PREP             # Unified prep job
│   ├── JNOS_OFS_NOWCST_FCST      # Unified nowcast/forecast
│   └── JNOS_OFS_POST             # Unified post-processing
├── scripts/                      # Ex-scripts
│   ├── nosofs/                   # COMF execution scripts
│   │   ├── exnos_ofs_prep.sh
│   │   └── exnos_ofs_prep_unified.sh  # YAML-enabled
│   └── stofs_3d_atl/             # STOFS execution scripts
│       ├── exstofs_3d_atl_prep_processing.sh
│       └── exstofs_3d_atl_prep_processing_unified.sh  # YAML-enabled
├── ush/                          # Utility scripts
│   ├── nosofs/                   # COMF shell utilities
│   ├── stofs_3d_atl/             # STOFS shell utilities
│   └── python/                   # Python package
│       └── nos_ofs/
│           ├── cli.py            # Command-line interface
│           ├── config/           # Configuration module
│           ├── forcing/          # Forcing processors
│           ├── models/           # Model implementations
│           └── utils/            # Utilities
├── parm/                         # Configuration files
│   ├── base/                     # Base model configs (YAML)
│   │   ├── schism.yaml
│   │   ├── fvcom.yaml
│   │   └── roms.yaml
│   └── systems/                  # OFS system configs (YAML)
│       ├── stofs_3d_atl.yaml
│       ├── secofs.yaml
│       └── ...
├── fix/                          # Static input files
└── exec/                         # Compiled executables
```

## Quick Start

### 1. Install Python Package

```bash
cd nos_ofs/ush/python
pip install -e .
```

### 2. List Available OFS Systems

```bash
python3 -m nos_ofs.cli list
```

### 3. Export YAML Config to Shell Environment

```bash
# For STOFS systems (LONMIN/LONMAX style)
eval $(python3 -m nos_ofs.cli export-env --config parm/systems/stofs_3d_atl.yaml --framework stofs)

# For nosofs/COMF systems (MINLON/MAXLON style)
eval $(python3 -m nos_ofs.cli export-env --config parm/systems/secofs.yaml --framework comf)
```

### 4. Run Preprocessing

```bash
# Using Python CLI
export OFS_CONFIG=/path/to/stofs_3d_atl.yaml
export PDY=20250115
export cyc=12
python3 -m nos_ofs.cli prep --config $OFS_CONFIG

# Or run specific forcing
python3 -m nos_ofs.cli forcing gfs --config $OFS_CONFIG
```

## Integration with Legacy Shell Scripts

The package supports two integration modes:

### Mode 1: Shell calls Python for config, then calls legacy scripts

```bash
# In ex-script:
export PYTHONPATH="${PYnos_ofs}:${PYTHONPATH}"
eval $(python3 -m nos_ofs.cli export-env --config "$OFS_CONFIG" --framework stofs)

# Now shell variables are set from YAML
echo "LONMIN=$LONMIN"  # From YAML

# Call legacy scripts which use these variables
${USHstofs3d}/stofs_3d_atl_create_surface_forcing_gfs.sh
```

### Mode 2: Python orchestrates legacy scripts

```python
from nos_ofs.models.legacy_runner import LegacyScriptRunner
from nos_ofs.models.schism_config import StofsConfig

config = StofsConfig.from_yaml("stofs_3d_atl.yaml")
runner = LegacyScriptRunner(config)

# Run full preprocessing (calls shell scripts)
results = runner.run_full_preprocessing(work_dir)

# Or run specific forcing
runner.create_gfs_forcing(work_dir)
runner.create_hrrr_forcing(work_dir)
```

## Supported OFS Systems

| System | Model | Framework | Config |
|--------|-------|-----------|--------|
| stofs_3d_atl | SCHISM | STOFS | stofs_3d_atl.yaml |
| stofs_3d_pac | SCHISM | STOFS | stofs_3d_pac.yaml |
| secofs | SCHISM | COMF | secofs.yaml |
| creofs | SCHISM | COMF | creofs.yaml |
| cbofs | ROMS | COMF | cbofs.yaml |
| dbofs | ROMS | COMF | dbofs.yaml |
| leofs | FVCOM | COMF | leofs.yaml |
| ngofs2 | FVCOM | COMF | ngofs2.yaml |

## YAML Configuration

Example configuration (stofs_3d_atl.yaml):

```yaml
_base: schism  # Inherit from base SCHISM config

system:
  name: stofs_3d_atl
  model_type: schism
  framework: stofs

grid:
  n_nodes: 1813443
  n_elements: 3564104
  n_levels: 51
  domain:
    lon_min: -98.5035
    lon_max: -52.4867
    lat_min: 7.347
    lat_max: 52.5904

forcing:
  atmospheric:
    primary: gfs
    hrrr_blend:
      enabled: true
  river:
    primary: nwm
    n_rivers: 7690
  ocean:
    primary: rtofs

legacy:
  enabled: true
  scripts:
    gfs: true
    hrrr: true
    river: true
    obc: true
```

## Environment Variables

The package respects NCO standard environment variables:

| Variable | Description |
|----------|-------------|
| OFS_CONFIG | Path to YAML config file |
| OFS | OFS system name |
| PDY | Processing date (YYYYMMDD) |
| cyc | Cycle hour (00, 06, 12, 18) |
| DATA | Working directory |
| COMOUT | Output directory |
| COMINgfs | GFS input path |
| COMINhrrr | HRRR input path |
| COMINnwm | NWM input path |
| COMINrtofs | RTOFS input path |

## Development

```bash
# Run tests
cd nos_ofs/ush/python
pytest

# Format code
black nos_ofs/

# Lint
flake8 nos_ofs/
```
