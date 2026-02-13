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

The package provides two execution paths: a **shell orchestration layer** for production HPC environments and a **native Python layer** for development, testing, and next-generation workflows.

```
nos_ofs/
│
├── jobs/                                 # J-jobs (NCO standard entry points)
│   ├── JNOS_OFS_PREP                    #   Unified prep dispatch (STOFS/COMF/ADCIRC)
│   ├── JNOS_OFS_NOWCAST                  #   Nowcast model execution
│   ├── JNOS_OFS_FORECAST                 #   Forecast model execution
│   └── JNOS_OFS_POST                    #   Unified post-processing
│
├── scripts/                              # Ex-scripts (execution layer)
│   ├── nosofs/                           #   COMF framework scripts
│   │   ├── exnos_ofs_prep.sh            #     Original COMF prep
│   │   ├── exnos_ofs_prep_unified.sh    #     Unified prep (calls nos_ofs_prep_run.sh)
│   │   ├── exnos_ofs_nowcast.sh         #     Nowcast (calls nos_ofs_model_run.sh)
│   │   └── exnos_ofs_forecast.sh        #     Forecast
│   └── stofs_3d_atl/                     #   STOFS framework scripts
│       ├── exnos_ofs_prep.sh            #     Unified prep for STOFS
│       ├── exnos_ofs_nowcast.sh         #     Nowcast for STOFS
│       ├── exnos_ofs_forecast.sh        #     Forecast for STOFS
│       └── exstofs_3d_atl_*.sh          #     Legacy STOFS scripts (preserved)
│
├── ush/                                  # Utility scripts and libraries
│   ├── nos_ofs_prep_run.sh              #   Shell prep library (7 public functions)
│   │                                     #     stage_static_files, create_model_config,
│   │                                     #     create_forcing_{atmospheric,river,obc,nudging},
│   │                                     #     prepare_initial_condition
│   ├── nos_ofs_model_run.sh             #   Shell model run library (4 public functions)
│   │                                     #     stage_model_files, prepare_restart,
│   │                                     #     execute_model, archive_outputs
│   ├── nos_ofs_config.sh                #   YAML config loader for shell
│   ├── nosofs/                          #   COMF forcing scripts (Fortran wrappers)
│   ├── stofs_3d_atl/                    #   STOFS forcing scripts
│   └── python/                          #   Python package
│       ├── nos_ofs/                     #     Main package (67 modules, 34K lines)
│       │   ├── cli.py                   #       CLI: nos-ofs {list,prep,run,forcing,export-env}
│       │   ├── registry.py              #       OFSRegistry factory (19 systems)
│       │   ├── config/                  #       YAML config with _base inheritance
│       │   ├── forcing/                 #       8 native Python forcing processors
│       │   │   ├── gfs.py              #         GFS 0.25deg (cfgrib/xarray)
│       │   │   ├── hrrr.py             #         HRRR 3km (Lambert Conformal)
│       │   │   ├── nam.py              #         NAM 12km (ROMS/FVCOM/SCHISM output)
│       │   │   ├── rtofs.py            #         RTOFS 3D boundaries (scipy interp)
│       │   │   ├── nwm.py              #         NWM river reach-to-source mapping
│       │   │   ├── tidal.py            #         Nodal factors (Schureman 1958, 15 constituents)
│       │   │   ├── adt.py              #         ADT satellite altimetry
│       │   │   └── st_lawrence.py      #         St. Lawrence River climatology
│       │   ├── models/                  #       4 hydrodynamic model implementations
│       │   │   ├── schism_model.py     #         SCHISM (unstructured, 3D baroclinic)
│       │   │   ├── roms_model.py       #         ROMS (curvilinear, sigma-coord)
│       │   │   ├── fvcom_model.py      #         FVCOM (unstructured, sigma-coord)
│       │   │   ├── adcirc_model.py     #         ADCIRC (unstructured, 2D barotropic)
│       │   │   ├── *_grid.py           #         Grid I/O per model (fort.14, hgrid.gr3, etc.)
│       │   │   ├── *_config.py         #         Config gen (fort.15, param.nml, ocean.in, etc.)
│       │   │   └── adcirc_bias_correction.py  #  CO-OPS bias correction (IDW, 4.8M nodes)
│       │   ├── orchestration/           #       Workflow orchestration layer
│       │   │   ├── prep.py             #         PrepOrchestrator (7 steps)
│       │   │   ├── model_run.py        #         ModelRunOrchestrator (4 steps)
│       │   │   ├── post.py             #         PostOrchestrator (STOFS 2-phase / COMF 6-step)
│       │   │   └── handlers/           #         STOFS + COMF framework handlers
│       │   ├── postprocessing/          #       Model-specific post-processors
│       │   │   ├── schism.py           #         STOFS two-phase + COMF native xarray
│       │   │   ├── roms.py             #         Sigma-to-z interpolation, CF-1.6
│       │   │   └── fvcom.py            #         Unstructured-to-grid, Great Lakes
│       │   └── ensemble/                #       Ensemble forecasting
│       │       ├── perturbation.py     #         IC/atm/OBC/param perturbations (FFT random fields)
│       │       ├── member.py           #         Member directory + config management
│       │       ├── runner.py           #         Sequential/parallel execution
│       │       ├── statistics.py       #         Mean, spread, percentiles, exceedance
│       │       └── visualization.py    #         Spaghetti, spread maps, rank histograms
│       └── tests/                       #     18 test files (pytest)
│
├── parm/                                 # Configuration files (YAML)
│   ├── base/                            #   Base model configs (inherited via _base)
│   │   ├── schism.yaml                  #     SCHISM defaults
│   │   ├── roms.yaml                    #     ROMS defaults (S-coord, bulk flux)
│   │   ├── fvcom.yaml                   #     FVCOM defaults (sigma, GOTM mixing)
│   │   └── adcirc.yaml                  #     ADCIRC defaults (2D, OWI forcing)
│   ├── systems/                         #   Per-OFS system overrides (19 files)
│   └── ensemble/                        #   Ensemble config examples
│
├── pbs/                                  # PBS job scripts for WCOSS2
├── ecf/                                  # ecFlow definitions (placeholder)
├── fix/                                  # Static input files (grids, coefficients)
└── exec/                                 # Compiled executables (Fortran)
```

### Workflow Pipeline

```
                ┌──────────────────────────────────────────────────────────────┐
                │                       J-Job Dispatch                          │
                │  JNOS_OFS_PREP → JNOS_OFS_NOWCAST → JNOS_OFS_FORECAST → POST │
                └───────┬───────────────────┬──────────────────────┬────────────┘
                             │                  │                  │
              ┌──────────────▼──────────┐  ┌────▼─────────┐  ┌────▼─────────┐
              │   nos_ofs_prep_run.sh   │  │  model_run.sh│  │  Python Post │
              │   (7-step dispatch)     │  │  (4-step)    │  │  Processor   │
              └──────┬──────┬───────────┘  └──────────────┘  └──────────────┘
                     │      │
           ┌─────────▼─┐ ┌─▼──────────┐
           │  _stofs_*  │ │  _comf_*   │    Framework-specific internals
           │  functions │ │  functions │    call existing forcing scripts
           └────────────┘ └────────────┘
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

# Create model instance for any of the 19 OFS systems
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
from nos_ofs.ensemble import EnsembleConfig, EnsembleRunner, EnsembleStatistics

config = OFSConfig.from_yaml("parm/systems/stofs_3d_atl.yaml")
ens_config = EnsembleConfig.from_yaml("parm/ensemble/stofs_3d_atl_ensemble.yaml")

runner = EnsembleRunner(config, ens_config)
result = runner.run_all("forecast")

# Compute statistics
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
