# nos_secofs_ufs

NOAA NOS SECOFS-UFS-Coastal — Southeast Coastal Ocean Forecast System, UFS-Coastal coupled (SCHISM + CDEPS DATM via NUOPC).

Operational workflow for nowcast and forecast on WCOSS2.

## Layout

```
nos_secofs_ufs/
├── jobs/             J-jobs (JNOS_PREP, JNOS_NOWCAST, JNOS_FORECAST, JNOS_POST)
├── scripts/          ex-scripts (exnos_prep.sh, exnos_nowcast.sh, exnos_forecast.sh, exnos_post.sh)
├── pbs/              PBS launchers (jnos_*.pbs)
├── ush/              shell + Python utilities
│   ├── nos_run.sh    consolidated 4-step run library
│   ├── nos_config.sh YAML config loader
│   └── python/
│       ├── nos-utils/  forcing-data package (NWM, RTOFS, GFS, HRRR, tidal, nudging, DATM)
│       └── utils/      yaml_to_env.py
├── parm/
│   ├── base/schism.yaml
│   └── systems/secofs_ufs.yaml
├── fix/secofs_ufs/   UFS templates + param.nml + noahmptable.tbl
├── exec/             compiled Fortran binaries
└── sorc/             Fortran source
```

## Public API

```bash
source ${USHnos}/nos_config.sh
load_ofs_config "${OFS_CONFIG}" "comf"

source ${USHnos}/nos_run.sh
stage_model_files nowcast
prepare_restart   nowcast
execute_model     nowcast
archive_outputs   nowcast
```

## Deploy on WCOSS2

```bash
cd $PACKAGEROOT
git clone -b nos-secofs_ufs https://github.com/mansurjisan/nos-workflow.git nos_secofs_ufs
```

Then:
1. Stage mesh + boundary files into `fix/secofs_ufs/` (hgrid.gr3, vgrid.in, .gr3 overlays, station.in, sources.json, sinks.json — too large to ship in git).
2. Build the Fortran executables from `sorc/` into `exec/`.
3. Submit:
   ```
   qsub pbs/jnos_prep_00.pbs
   qsub pbs/jnos_nowcast_00.pbs
   qsub pbs/jnos_forecast_00.pbs
   ```

## Verifying the build

After a nowcast run, confirm the hotstart is parallel-IO-safe:
```bash
ncdump -k $COMOUT/secofs_ufs.t${cyc}z.${PDY}.rst.nowcast.nc
# Expected: netCDF-4 classic model
```
