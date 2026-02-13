# NOS-OFS Unified Workflow Package

Unified Python package for NOAA's Operational Ocean Forecast Systems (OFS), supporting 19 forecast systems across 4 hydrodynamic models with native Python forcing processors, ensemble forecasting, and YAML-driven configuration.

## Supported Systems

| Model | Framework | OFS Systems |
|-------|-----------|-------------|
| SCHISM | STOFS | stofs_3d_atl, stofs_3d_pac |
| SCHISM | COMF | secofs, creofs |
| FVCOM | COMF | leofs, loofs, lmhofs, lsofs, ngofs2, sfbofs, sscofs |
| ROMS | COMF | cbofs, dbofs, tbofs, gomofs, ciofs, wcofs |
| ADCIRC | STOFS | stofs_2d_glo |

## Architecture

```
nos_ofs/
├── jobs/                             # J-jobs (NCO standard)
│   ├── JNOS_OFS_PREP                # Unified prep dispatch
│   ├── JNOS_OFS_NOWCST_FCST         # Unified model execution
│   └── JNOS_OFS_POST                # Unified post-processing
├── scripts/                          # Ex-scripts (framework-specific)
│   ├── nosofs/                       # COMF execution scripts
│   └── stofs_3d_atl/                 # STOFS execution scripts
├── ush/                              # Utility scripts
│   ├── nos_ofs_prep_run.sh           # Shell prep library (7-step API)
│   ├── nos_ofs_model_run.sh          # Shell model run library (4-step API)
│   ├── nos_ofs_config.sh             # YAML config loader for shell
│   ├── nosofs/                       # COMF shell utilities
│   ├── stofs_3d_atl/                 # STOFS shell utilities
│   └── python/nos_ofs/               # Python package (see below)
├── parm/                             # Configuration (YAML)
│   ├── base/                         # Base model configs
│   │   ├── schism.yaml
│   │   ├── roms.yaml
│   │   ├── fvcom.yaml
│   │   └── adcirc.yaml
│   ├── systems/                      # Per-OFS system configs (19 files)
│   └── ensemble/                     # Ensemble configuration examples
├── pbs/                              # PBS job scripts for WCOSS2
├── fix/                              # Static input files (grids, coefficients)
└── exec/                             # Compiled executables
```

## Python Package (`nos_ofs`)

```
ush/python/nos_ofs/
├── cli.py                    # Command-line interface
├── config/                   # YAML configuration loader
├── forcing/                  # Native Python forcing processors
│   ├── gfs.py               #   GFS atmospheric (cfgrib/xarray)
│   ├── hrrr.py              #   HRRR high-res atmospheric
│   ├── nam.py               #   NAM atmospheric (ROMS/FVCOM/SCHISM)
│   ├── rtofs.py             #   RTOFS ocean boundary (scipy interpolation)
│   ├── nwm.py               #   NWM river forcing
│   ├── tidal.py             #   Tidal nodal factors (Schureman 1958)
│   ├── adt.py               #   ADT satellite altimetry
│   └── st_lawrence.py       #   St. Lawrence River climatology
├── models/                   # Hydrodynamic model implementations
│   ├── schism_model.py      #   SCHISM (unstructured, 3D)
│   ├── roms_model.py        #   ROMS (curvilinear, 3D)
│   ├── fvcom_model.py       #   FVCOM (unstructured, 3D)
│   ├── adcirc_model.py      #   ADCIRC (unstructured, 2D barotropic)
│   ├── *_grid.py            #   Grid I/O for each model type
│   └── *_config.py          #   Config generation (param.nml, ocean.in, fort.15, etc.)
├── orchestration/            # Workflow orchestration
│   ├── prep.py              #   PrepOrchestrator (7-step)
│   ├── model_run.py         #   ModelRunOrchestrator (4-step)
│   ├── post.py              #   PostOrchestrator
│   └── handlers/            #   STOFS/COMF framework-specific handlers
├── postprocessing/           # Post-processing by model type
│   ├── schism.py            #   SCHISM (STOFS two-phase + COMF native)
│   ├── roms.py              #   ROMS (sigma-to-z interpolation)
│   └── fvcom.py             #   FVCOM (unstructured-to-grid, Great Lakes)
├── ensemble/                 # Ensemble forecasting
│   ├── perturbation.py      #   IC, atmospheric, OBC, parameter perturbations
│   ├── runner.py            #   Sequential/parallel member execution
│   ├── statistics.py        #   Mean, spread, percentiles, exceedance
│   └── visualization.py     #   Spaghetti plots, spread maps, rank histograms
└── utils/                    # YAML-to-env converter, helpers
```

## Quick Start

### Install

```bash
cd ush/python
pip install -e ".[full]"    # With xarray, netCDF4, scipy, cfgrib
```

### List Available Systems

```bash
nos-ofs list
```

### Run a Forecast (Python)

```python
from nos_ofs import OFSRegistry, OFSConfig
from nos_ofs.orchestration import PrepOrchestrator, ModelRunOrchestrator, PostOrchestrator

# Create model instance
model = OFSRegistry.create_model("stofs_3d_atl")

# Or use orchestration layer
config = OFSConfig.from_yaml("parm/systems/stofs_3d_atl.yaml")

# Prep (7 steps: stage files, config, atm, river, obc, nudging, IC)
prep = PrepOrchestrator(config)
result = prep.run_all()

# Model run (4 steps: stage, restart, execute, archive)
runner = ModelRunOrchestrator(config)
nowcast = runner.run_all("nowcast")
forecast = runner.run_all("forecast")

# Post-processing
post = PostOrchestrator(config)
post_result = post.run_all()
```

### Run Ensemble Forecast

```python
from nos_ofs.ensemble import EnsembleConfig, EnsembleRunner

config = OFSConfig.from_yaml("parm/systems/stofs_3d_atl.yaml")
ens_config = EnsembleConfig.from_yaml("parm/ensemble/stofs_3d_atl_ensemble.yaml")

runner = EnsembleRunner(config, ens_config)
result = runner.run_all("forecast")

# Compute statistics
from nos_ofs.ensemble import EnsembleStatistics
stats = EnsembleStatistics(result.members, output_dir)
stats.compute_all()  # mean, spread, percentiles, probability of exceedance
```

### Shell Integration

```bash
# Export YAML config to shell environment variables
eval $(python3 -m nos_ofs.cli export-env --config parm/systems/secofs.yaml --framework comf)

# Run unified prep (dispatches to framework-specific scripts)
source ush/nos_ofs_prep_run.sh
stage_static_files
create_model_config
create_forcing_atmospheric
create_forcing_river
create_forcing_obc
create_forcing_nudging
prepare_initial_condition
```

## Forcing Processors

All 8 forcing processors are **native Python** with zero subprocess calls to wgrib2, NCO tools, or Fortran executables:

| Processor | Input | Output | Method |
|-----------|-------|--------|--------|
| GFS | GRIB2 (0.25deg) | sflux_air/rad/prc NetCDF | cfgrib + xarray |
| HRRR | GRIB2 (3km Lambert) | sflux secondary NetCDF | cfgrib + projection handling |
| NAM | GRIB2 (12km) | ROMS/FVCOM/SCHISM met files | cfgrib + scipy interpolation |
| RTOFS | NetCDF (HYCOM) | elev2D/TEM_3D/SAL_3D/uv3D.th.nc | scipy NearestNDInterpolator |
| NWM | NetCDF | vsource.th, msource.th | numpy reach-to-source mapping |
| Tidal | Constituent DB | bctides.in | Schureman (1958) nodal factors |
| ADT | NetCDF (altimetry) | SSH boundary correction | scipy griddata |
| St. Lawrence | CSV climatology | River forcing files | Native CSV parsing |

## YAML Configuration

Configs use inheritance (`_base`) and are overridden by environment variables:

```yaml
_base: schism                    # Inherit from parm/base/schism.yaml

system:
  name: stofs_3d_atl
  framework: stofs

grid:
  n_nodes: 1813443
  domain:
    lon_min: -98.5035
    lon_max: -52.4867

forcing:
  atmospheric:
    primary: gfs
    hrrr_blend: { enabled: true }
  river:
    primary: nwm
    n_rivers: 7690
  ocean:
    primary: rtofs
```

## Ensemble Configuration

```yaml
ensemble:
  n_members: 20
  seed: 42
  perturbations:
    initial_conditions:
      enabled: true
      method: gaussian
      variables:
        temperature: { std_dev: 0.5, correlation_length: 50 }
        ssh: { std_dev: 0.05, correlation_length: 100 }
    atmospheric:
      enabled: true
      wind: { speed_std_pct: 10, direction_std_deg: 15 }
  statistics:
    percentiles: [5, 10, 25, 50, 75, 90, 95]
    probability_thresholds:
      zeta: [0.5, 1.0, 1.5, 2.0]    # Flood levels (m above MHHW)
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `OFS_CONFIG` | Path to YAML config file |
| `OFS` | OFS system name |
| `PDY` | Processing date (YYYYMMDD) |
| `cyc` | Cycle hour (00, 06, 12, 18) |
| `DATA` | Working directory |
| `COMOUT` | Output directory |
| `COMINgfs` | GFS input path |
| `COMINhrrr` | HRRR input path |
| `COMINnwm` | NWM input path |
| `COMINrtofs` | RTOFS input path |

## Development

```bash
cd ush/python

# Run tests
pytest

# Run specific test module
pytest tests/test_forcing_gfs.py -v

# Format and lint
black nos_ofs/
flake8 nos_ofs/
```

## HPC Deployment (WCOSS2)

```bash
# Clone and checkout
git clone https://github.com/mansurjisan/nos-workflow.git
cd nos-workflow
git checkout feature/full-python-package

# Submit PBS jobs
qsub pbs/jnos_stofs3datl_prep_12.pbs
qsub pbs/jnos_secofs_prep_00.pbs
```
