# NOS OFS Unified Workflow

Unified workflow for NOAA's Operational Ocean Forecast Systems, supporting SCHISM, FVCOM, and ROMS models with YAML-driven configuration.

## Architecture

```
nos_ofs/
├── jobs/                          # J-jobs (NCO standard)
│   ├── JNOS_OFS_PREP             # Prep: USE_PYTHON_PREP=YES for Python mode
│   ├── JNOS_OFS_NOWCAST          # Nowcast model run
│   ├── JNOS_OFS_FORECAST         # Forecast model run
│   └── JNOS_OFS_POST             # Post-processing
├── scripts/                      # Ex-scripts
│   ├── nosofs/
│   │   ├── exnos_ofs_prep.sh            # Legacy shell+Fortran prep
│   │   └── exnos_ofs_prep_python.sh     # Python prep (nos-utils)
│   └── stofs_3d_atl/
├── ush/                          # Utility scripts
│   ├── nosofs/                   # COMF shell forcing scripts
│   ├── stofs_3d_atl/             # STOFS shell forcing scripts
│   └── python/
│       ├── nos_ofs/              # Legacy Python package
│       └── nos-utils/            # Standalone forcing generators (submodule)
├── parm/
│   ├── base/                     # Base model configs (schism.yaml, fvcom.yaml, roms.yaml)
│   └── systems/                  # Per-OFS configs (secofs.yaml, stofs_3d_atl.yaml, ...)
├── pbs/                          # PBS/SLURM job scripts for WCOSS2
├── fix/                          # Static input files (grids, templates)
└── exec/                         # Compiled Fortran executables
```

## Preprocessing Modes

### Python Prep (nos-utils) — recommended for new development

Set `USE_PYTHON_PREP=YES` in the PBS script or environment:

```bash
# PBS script
export USE_PYTHON_PREP=YES
${HOMEnos}/jobs/JNOS_OFS_PREP
```

Or use the dedicated PBS script:
```bash
qsub pbs/jnos_secofs_prep_python_00.pbs
```

Or use the CLI directly:
```bash
nos-utils prep --ofs secofs --pdy 20260324 --cyc 12 \
  --gfs /data/gfs/v16.3 --hrrr /data/hrrr/v4.1 \
  --fix /data/fix/secofs --output /work/prep/
```

The Python prep replaces ~3,700 lines of shell+Fortran with tested Python processors:

| Shell Script (replaced) | Python Processor | Output |
|------------------------|-----------------|--------|
| `nos_ofs_create_forcing_met.sh` | GFSProcessor + HRRRProcessor | sflux_air/rad/prc |
| `nos_ofs_create_forcing_river.sh` | NWMProcessor | vsource.th, msource.th |
| `nos_ofs_create_forcing_obc.sh` | RTOFSProcessor | elev2D, TEM/SAL_3D, uv3D |
| `nos_ofs_prep_schism_ctl.sh` | ParamNmlProcessor | param.nml |
| `nos_ofs_create_forcing_obc_tides.sh` | TidalProcessor | bctides.in |

### Legacy Shell Prep — default, unchanged

```bash
# Default behavior (USE_PYTHON_PREP not set or NO)
${HOMEnos}/jobs/JNOS_OFS_PREP
```

## nos-utils Package

Standalone forcing generator at [github.com/mansurjisan/nos-utils](https://github.com/mansurjisan/nos-utils). Included as a git submodule at `ush/python/nos-utils/`.

```bash
# Clone with submodule
git clone --recurse-submodules -b feature/python-prep https://github.com/mansurjisan/nos-workflow.git

# Or init submodule after clone
git submodule update --init --recursive
```

### Processors

| Processor | Source | Description |
|-----------|--------|-------------|
| GFSProcessor | GFS 0.25° | Primary atmospheric forcing (hourly) |
| HRRRProcessor | HRRR 3km | Secondary CONUS forcing (LCC→latlon regrid) |
| GEFSProcessor | GEFS ensemble | 3-hourly, RH→SPFH conversion, per-member |
| RTOFSProcessor | RTOFS global | Ocean boundary (SSH, T/S, velocity) |
| NWMProcessor | National Water Model | River discharge with climatology fallback |
| TidalProcessor | TPXO9 | bctides.in with nodal corrections |
| ParamNmlProcessor | Template | param.nml generation from SCHISM template |
| HotstartProcessor | Restart files | Hotstart discovery with date fallback |
| PartitionProcessor | hgrid.gr3 | MPI domain partition (partition.prop) |
| ESMFMeshProcessor | Forcing grid | ESMF mesh for UFS-Coastal DATM |
| BlenderProcessor | GFS+HRRR sflux | Delaunay blending for DATM |

## YAML Configuration

All OFS systems are configured via YAML with inheritance:

```yaml
# parm/systems/secofs.yaml
_base: schism                    # Inherits from parm/base/schism.yaml

system:
  name: secofs
  framework: comf

grid:
  domain:
    lon_min: -88.0
    lon_max: -63.0
    lat_min: 17.0
    lat_max: 40.0

forcing:
  atmospheric:
    met_num: 2                   # GFS + HRRR
    primary: GFS
    secondary: HRRR
  river:
    primary: nwm
  ocean:
    primary: rtofs
    nudging:
      enabled: true
      timescale_seconds: 10800.0
  tidal:
    enabled: true
    constituents: [M2, S2, N2, K2, K1, O1, P1, Q1]

model:
  run:
    nowcast_hours: 6
    forecast_hours: 48
```

## Supported OFS Systems

| System | Model | Framework | Config |
|--------|-------|-----------|--------|
| secofs | SCHISM | COMF | secofs.yaml |
| stofs_3d_atl | SCHISM | STOFS | stofs_3d_atl.yaml |
| stofs_3d_pac | SCHISM | STOFS | stofs_3d_pac.yaml |
| creofs | SCHISM | COMF | creofs.yaml |
| cbofs | ROMS | COMF | cbofs.yaml |
| dbofs | ROMS | COMF | dbofs.yaml |
| tbofs | ROMS | COMF | tbofs.yaml |
| gomofs | ROMS | COMF | gomofs.yaml |
| leofs | FVCOM | COMF | leofs.yaml |
| ngofs2 | FVCOM | COMF | ngofs2.yaml |

## Environment Variables

Standard NCO variables used by both shell and Python prep:

| Variable | Description |
|----------|-------------|
| `PDY` | Production date (YYYYMMDD) |
| `cyc` | Cycle hour (00, 06, 12, 18) |
| `OFS` / `RUN` | OFS system name |
| `OFS_CONFIG` | Path to YAML config file |
| `USE_PYTHON_PREP` | `YES` to use Python prep, `NO` for legacy shell |
| `COMINgfs` | GFS input data path |
| `COMINhrrr` | HRRR input data path |
| `COMINrtofs` | RTOFS input data path |
| `COMINnwm` | NWM input data path |
| `FIXofs` | Static fix files directory |
| `DATA` | Working directory |
| `COMOUT` | Output archive directory |

## Development

```bash
# nos-utils tests (standalone, no data needed)
cd ush/python/nos-utils
pip install -e ".[dev]"
pytest -v

# Integration test in Docker (needs real data)
docker run --rm \
  -v /data/com:/data/com:ro \
  -v /path/to/nos-utils:/opt/nos-utils \
  --entrypoint bash nosofs/secofs-ufs:latest -c '
    export PYTHONPATH=/opt/nos-utils:$PYTHONPATH
    nos-utils prep --ofs secofs --pdy 20260324 --cyc 12 --output /tmp/test
  '
```
