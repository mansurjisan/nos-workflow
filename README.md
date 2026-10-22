# nos-workflow

nos-workflow runs NOS coastal forecast systems as a prep, nowcast, forecast and post cycle in the NCO package layout. The stages are Python (`ush/python/nos_workflow`); forcing and post products come from the `nos-utils` submodule. Models are SCHISM, standalone or coupled through UFS-Coastal to a CDEPS data atmosphere (optionally WAVEWATCH III), and ADCIRC. Machines are WCOSS2 (PBS) and Hercules (Slurm).

These are development configurations, not NCO operational jobs. `develop` is the integration branch.

## Systems

| System (yaml name) | Model | Machines | Launch |
|---|---|---|---|
| SECOFS (`secofs_ufs`) | SCHISM + DATM | WCOSS2, Hercules | `pbs/launch_secofs_ufs.sh <CYC>`; Hercules: `slurm/secofs_ufs/` |
| SECOFS with waves (`secofs_ufs_ww3`) | SCHISM + DATM + WW3 | WCOSS2 | `pbs/secofs_ufs_ww3/launch_secofs_ufs_ww3.sh <CYC>` |
| STOFS-3D-ATL standalone (`stofs_3d_atl_ufs` + standalone overlay) | SCHISM | WCOSS2, Hercules | `pbs/stofs_3d_atl_ufs_standalone/launch_stofs_standalone.sh <PDY>`; see guide |
| STOFS-3D-ATL coupled (`stofs_3d_atl_ufs`) | SCHISM + DATM | WCOSS2, Hercules | `pbs/stofs_3d_atl_ufs/launch_stofs_3d_atl_ufs.sh <PDY>`; see guide |
| STOFS-3D-AK (`stofs_3d_ak_ufs`) | SCHISM + DATM | WCOSS2 | `pbs/stofs_3d_ak_ufs/launch_stofs_3d_ak_ufs.sh <PDY>` |
| STOFS-2D-Global (`stofs_2d_glo`) | ADCIRC | WCOSS2, Hercules | `pbs/` or `slurm/stofs_2d_glo/launch_stofs_2d_glo.sh <PDY> <CYC>` |

## Quick start

```bash
git clone https://github.com/oceanmodeling/nos-workflow.git && cd nos-workflow
git submodule update --init ush/python/nos-utils
```

- Fix files and executables: see the run guide for your system (`tools/fetch_<system>_fix.sh` fetches the fix files).
- A first cycle needs an initial state: a hotstart or restart file, or for STOFS-2D-Global a cold start. See the guide.
- Launch with the command in the table.
- Logs: `.out`/`.err` per job under the `rpt/<OFS>/` directory of your scratch. Outputs: `${COMROOT}/nos/<RUN>.<PDY>/`. A stage log ends with `STAGE_SUMMARY ... status=PASS` or `FAIL`.

## Layout

- `jobs/`, `scripts/`: NCO J-jobs and ex-scripts
- `ush/`: shell libraries and the `nos_workflow` Python package (`ush/python`)
- `parm/`: system, model and machine yaml
- `fix/`: tracked templates and small tables (large files are fetched)
- `exec/`: executables (not tracked)
- `pbs/`, `slurm/`: WCOSS2 and Hercules cards and launchers
- `ecf/`: ecFlow suite (WCOSS2, not yet run on a server)
- `.cicd/`: Jenkins pipeline
- `docs/`: run guides
- `tools/`: fix fetch, builds, forcing staging, seeds
- `containers/`: WCOSS2-like STOFS container and the SECOFS UFS image

Branches: `develop` is the primary branch, with the full development tree and CI. `main` is generated from develop on every develop push (`.github/workflows/sync-main.yml`). It keeps only the NCO Implementation Standards package layout (`docs ecf fix jobs modulefiles parm scripts sorc ush versions`) and drops `containers pbs slurm tests tools .cicd`, the workflow files and `ush/python/nos_workflow/tests`. Do not commit to `main` directly. To run the systems (cards, launchers, tools), clone `develop`.

## Documentation

- [docs/secofs_run_guide.md](docs/secofs_run_guide.md)
- [docs/stofs_3d_atl_run_guide.md](docs/stofs_3d_atl_run_guide.md)
- [docs/stofs_2d_glo_run_guide.md](docs/stofs_2d_glo_run_guide.md)
- [docs/ecflow_run_guide.md](docs/ecflow_run_guide.md)
- [docs/hercules_jenkins_run_guide.md](docs/hercules_jenkins_run_guide.md)

STOFS-3D-AK is documented in its launcher header.

## Tests and CI

- Unit tests: `cd ush/python && PYTHONPATH=$PWD:$PWD/nos-utils python3 -m pytest -q nos_workflow/tests`
- CI: Jenkins on Hercules and GitHub Actions; see the Jenkins guide.

## Disclaimer

This repository is a scientific product and is not official communication of the National Oceanic and Atmospheric Administration, or the United States Department of Commerce. All NOAA GitHub project code is provided on an "as is" basis and the user assumes responsibility for its use. Any claims against the Department of Commerce or Department of Commerce bureaus stemming from the use of this GitHub project will be governed by all applicable Federal law. Any reference to specific commercial products, processes, or services by service mark, trademark, manufacturer, or otherwise, does not constitute or imply their endorsement, recommendation or favoring by the Department of Commerce. The Department of Commerce seal and logo, or the seal and logo of a DOC bureau, shall not be used in any manner to imply endorsement of any commercial product or activity by DOC or the United States Government.
