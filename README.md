# NOS-OFS Workflow

Unified operational workflow for NOAA ocean forecast systems (SCHISM, FVCOM, ROMS). Runs on WCOSS2 via PBS.

## Quick Start

```bash
git clone --recurse-submodules https://github.com/mansurjisan/nos-workflow.git

# Submit SECOFS on WCOSS2
qsub pbs/jnos_secofs_prep_00.pbs
```

## Configuration

YAML configs in `parm/systems/` with inheritance from `parm/base/`:

```yaml
# parm/systems/secofs.yaml
_base: schism
grid:
  domain: {lon_min: -88, lon_max: -63, lat_min: 17, lat_max: 40}
forcing:
  atmospheric: {primary: GFS, secondary: HRRR, met_num: 2}
  river: {primary: nwm}
  ocean: {primary: rtofs}
model:
  run: {nowcast_hours: 6, forecast_hours: 48}
```

## Systems

| System | Model | Domain |
|--------|-------|--------|
| secofs | SCHISM | SE US coast |
| stofs_3d_atl | SCHISM | Atlantic |
| stofs_3d_pac | SCHISM | Pacific |
| cbofs, dbofs, tbofs, gomofs | ROMS | Chesapeake, Delaware, Tampa, Gulf |
| leofs, ngofs2, sfbofs | FVCOM | Great Lakes, Gulf, SF Bay |

## Directory Layout

```
jobs/          J-jobs (NCO standard entry points)
scripts/       Ex-scripts (execution logic)
ush/           Shell utilities + Python packages
parm/          YAML configuration (base/ + systems/)
pbs/           PBS job scripts for WCOSS2
fix/           Static grids, templates, harmonic constants
exec/          Compiled Fortran executables
```
