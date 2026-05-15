# nos-workflow

nos-workflow is a Python-based unified workflow framework for UFS-based NOAA's National Ocean Service (NOS) coastal ocean forecast systems. It drives the prep → nowcast → forecast → post cycle on WCOSS2 for any UFS-Coastal-coupled NOS-OFS configuration, providing a common API for all operational forecast systems.

The coupled system uses SCHISM as the ocean model, with a CDEPS data atmosphere (DATM) connected through NUOPC mediation. Forcing inputs — boundary conditions, atmospheric forcing, rivers, tides, and nudging — are prepared in Python and anchored to the production COMF cycle-6h convention.

## Supported configurations

- **SECOFS** — Southeast Coastal Ocean Forecast System (UFS-Coastal)
- **STOFS-3D-ATL** — Storm and Tide Operational Forecast System, 3D Atlantic (UFS-Coastal)

## Layout

```
nos-workflow/
├── jobs/             J-jobs (JNOS_PREP, JNOS_NOWCAST, JNOS_FORECAST, JNOS_POST)
├── scripts/          ex-scripts (exnos_prep.sh, exnos_nowcast.sh, exnos_forecast.sh, exnos_post.sh)
├── pbs/              PBS launchers (jnos_*.pbs)
├── ush/              shell + Python utilities
│   ├── nos_run.sh    HPC module-load bootstrap + MPI launch shim
│   ├── nos_config.sh YAML config loader
│   └── python/
│       ├── nos-utils/    forcing-data package (NWM, RTOFS, GFS, HRRR, tidal, nudging, DATM)
│       └── nos_workflow/ stage orchestration (prep / nowcast / forecast / post)
├── parm/
│   ├── base/         cross-OFS defaults
│   └── systems/      per-OFS configs (secofs_ufs.yaml, stofs_3d_atl_ufs.yaml)
└── fix/<ofs>/        static input files (grids, mesh templates, partition.prop, fix tables)
```

## Public API

```bash
# Invoked from J-jobs after sourcing nos_run.sh
. ${USHnos}/nos_run.sh
exec python3 -m nos_workflow run prep --ofs "${OFS}"
```

```bash
# Direct invocation for development / parity testing
python3 -m nos_workflow run prep     --ofs secofs_ufs
python3 -m nos_workflow run nowcast  --ofs secofs_ufs
python3 -m nos_workflow run forecast --ofs secofs_ufs
python3 -m nos_workflow run post     --ofs secofs_ufs
```
