# NOS OFS Example Run Scripts

This directory contains example scripts for running preprocessing for different OFS systems using the unified YAML configuration approach.

## Available Scripts

| Script | OFS | Framework | Model | Region |
|--------|-----|-----------|-------|--------|
| `run_stofs_3d_atl_prep.sh` | STOFS 3D Atlantic | STOFS | SCHISM | Atlantic Coast |
| `run_secofs_prep.sh` | SECOFS | COMF | SCHISM | Southeast Coast |
| `run_cbofs_prep.sh` | CBOFS | COMF | ROMS | Chesapeake Bay |
| `run_leofs_prep.sh` | LEOFS | COMF | FVCOM | Lake Erie |

## Quick Start

### 1. Make Scripts Executable

```bash
chmod +x *.sh
```

### 2. Edit Configuration

Each script has sections to customize:

```bash
# DATE/TIME - Update for your run
export PDY=20250504
export cyc=12

# DATA PATHS - Update to your data location
export CI_DATA=/path/to/your/data     # STOFS
export DCOMROOT=/path/to/your/data    # COMF models
```

### 3. Run

```bash
# STOFS 3D Atlantic
./run_stofs_3d_atl_prep.sh 2>&1 | tee stofs_prep.log

# SECOFS
./run_secofs_prep.sh 2>&1 | tee secofs_prep.log

# CBOFS
./run_cbofs_prep.sh 2>&1 | tee cbofs_prep.log

# LEOFS
./run_leofs_prep.sh 2>&1 | tee leofs_prep.log
```

## Model Comparison

### By Framework

| Framework | Models | Variable Naming | Workflow |
|-----------|--------|-----------------|----------|
| STOFS | stofs_3d_atl, stofs_3d_pac | `LONMIN`, `LATMAX` | Single continuous run |
| COMF | secofs, cbofs, leofs, etc. | `MINLON`, `MAXLAT` | Separate nowcast/forecast |

### By Ocean Model

| Model | Type | OFS Systems |
|-------|------|-------------|
| SCHISM | Unstructured | stofs_3d_atl, stofs_3d_pac, secofs, creofs |
| ROMS | Curvilinear | cbofs, dbofs, tbofs, gomofs, wcofs |
| FVCOM | Unstructured | leofs, loofs, lmhofs, ngofs2, sfbofs |

### By Forcing Requirements

| OFS | Atmospheric | Rivers | Ocean BC | Tides |
|-----|-------------|--------|----------|-------|
| stofs_3d_atl | GFS + HRRR | NWM (7690) | RTOFS | Yes |
| secofs | GFS + HRRR | NWM | RTOFS | Yes |
| cbofs | NAM/GFS | NWM + USGS | RTOFS | Yes |
| leofs | HRRR/GFS | NWM + USGS | None | None |

## YAML Configuration

All scripts use the Python CLI to load YAML configuration:

```bash
# Load config (framework auto-detected)
eval $(python3 -m nos_ofs.cli export-env --config $OFS_CONFIG)
```

### YAML Files Location

```
nos_ofs/parm/systems/
├── stofs_3d_atl.yaml    # STOFS 3D Atlantic
├── stofs_3d_pac.yaml    # STOFS 3D Pacific
├── secofs.yaml          # Southeast Coast OFS
├── cbofs.yaml           # Chesapeake Bay OFS
├── dbofs.yaml           # Delaware Bay OFS
├── leofs.yaml           # Lake Erie OFS
├── ngofs2.yaml          # Northern Gulf OFS
└── creofs.yaml          # Columbia River Estuary OFS
```

### Framework Detection

The framework is determined by `system.framework` in the YAML:

```yaml
# STOFS models
system:
  framework: stofs    # -> LONMIN, LATMAX, N_DAYS_MODEL_RUN_PERIOD

# COMF models
system:
  framework: comf     # -> MINLON, MAXLAT, PREFIXNOS, LEN_NOWCAST
```

## Input Data Requirements

### STOFS 3D Atlantic

| Source | Variable | Description |
|--------|----------|-------------|
| GFS | `COMINgfs` | Global atmospheric (0.25°) |
| HRRR | `COMINhrrr` | High-res CONUS (3km) |
| NWM | `COMINnwm` | National Water Model rivers |
| RTOFS | `COMINrtofs` | Real-Time Ocean Forecast System |

### SECOFS / CBOFS (Coastal)

| Source | Variable | Description |
|--------|----------|-------------|
| NAM/GFS | `COMINnam`/`COMINgfs` | Atmospheric forcing |
| HRRR | `COMINhrrr` | High-res atmospheric |
| RTOFS | `COMINrtofs` | Ocean boundary conditions |
| NWM | `COMINnwm` | River discharge |
| USGS | `DCOMINusgs` | River observations |

### LEOFS (Great Lakes)

| Source | Variable | Description |
|--------|----------|-------------|
| HRRR | `COMINhrrr` | High-res atmospheric (primary) |
| GFS | `COMINgfs` | Global atmospheric (fallback) |
| NWM | `COMINnwm` | River discharge |
| USGS | `DCOMINusgs` | River observations |

**Note:** Great Lakes models (LEOFS, LOOFS, LMHOFS, LSOFS) don't require ocean BC or tidal forcing.

## Output Structure

### STOFS Framework

```
work/stofs_3d_atl/
├── gfs/              # GFS forcing (sflux_air_1.nc, etc.)
├── hrrr/             # HRRR forcing (sflux_air_2.nc, etc.)
├── river/            # River forcing (vsource.th, vsink.th)
├── rtofs/            # Ocean BC (elev2dth.nc, tem3dth.nc)
└── rerun/            # Nudging, param.nml, bctides.in
```

### COMF Models (SECOFS, CBOFS, LEOFS)

```
work/<ofs>/
├── outputs/          # Model outputs
├── sflux/            # Surface forcing files
├── data/             # River source/sink data
└── rerun/            # Restart and control files
```

## Preprocessing Steps by Model

### SCHISM (STOFS, SECOFS)

1. Create param.nml
2. Create bctides.in (tidal forcing)
3. Create river forcing (NWM)
4. Create surface forcing (GFS/HRRR)
5. Create ocean BC (RTOFS 3D)
6. Create nudging fields

### ROMS (CBOFS, DBOFS)

1. Create atmospheric forcing
2. Create river forcing
3. Create ocean BC (RTOFS)
4. Create ROMS ocean.in control file

### FVCOM (LEOFS, NGOFS2)

1. Create atmospheric forcing
2. Create river forcing
3. Create FVCOM control files

## Troubleshooting

### YAML Not Loading

```bash
# Check PYTHONPATH
echo $PYTHONPATH

# Test import
python3 -c "import nos_ofs; print('OK')"

# Test CLI
python3 -m nos_ofs.cli list
```

### Missing Fix Files

Each OFS requires static files in `FIXofs`:
- Grid files (`.gr3`, `.nc`, `.dat`)
- Control file (`.ctl`)
- Template files (`.in`, `.nml`)

### Missing Tools

```bash
# wgrib2
export WGRIB2=$(which wgrib2 2>/dev/null || echo "/path/to/wgrib2")

# NCO tools
conda activate nos_ofs_prep
which ncks ncap2 ncrcat

# Library path (adjust to your conda environment)
export LD_LIBRARY_PATH=${CONDA_PREFIX}/lib:$LD_LIBRARY_PATH
```

## Adding New OFS

To add support for another OFS system:

1. Create YAML config: `parm/systems/<ofs_name>.yaml`
2. Copy appropriate example script (SCHISM/ROMS/FVCOM)
3. Update OFS name, paths, and model-specific settings
4. Set `framework: stofs` or `framework: comf` in YAML
5. Provide fix files in `FIXofs` directory
