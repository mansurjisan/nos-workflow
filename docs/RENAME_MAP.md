# Rename map: nosofs.v3.7.0 → nos_secofs_ufs

## Rename rules

1. **Directory root:** `nosofs.v3.7.0/` → `nos_secofs_ufs/` (no version, OFS-name suffix)
2. **File names:** drop the `_ofs_` middle infix in scripts. `nos_ofs_X` → `nos_X`. `JNOS_OFS_X` → `JNOS_X`. `exnos_ofs_X` → `exnos_X`.
3. **Env vars:** drop `nosofs_ver` and `nos_ofs_ver`. Keep `HOMEnos`, `EXECnos`, `FIXnos`, `USHnos`, `PARMnos`, `JOBSnos`, `SCRIPTSnos` (already short, no `nosofs` prefix).
4. **COM dir convention:** `com/nosofs/v3.7/` → `com/nos/secofs_ufs/`
5. **Repo:** stays `mansurjisan/nos-workflow`. New **branch** `nos-secofs_ufs` (parallel to `main` and `feature/python-prep`) containing only this clean tree at the repo root. Deployment clone target on WCOSS2: `$PACKAGEROOT/nos_secofs_ufs/`.

## File-by-file mapping

### J-jobs
| old | new |
|---|---|
| `jobs/JNOS_OFS_PREP` | `jobs/JNOS_PREP` |
| `jobs/JNOS_OFS_NOWCAST` | `jobs/JNOS_NOWCAST` |
| `jobs/JNOS_OFS_FORECAST` | `jobs/JNOS_FORECAST` |
| `jobs/JNOS_OFS_POST` | `jobs/JNOS_POST` |

### Ex-scripts
| old | new |
|---|---|
| `scripts/nosofs/exnos_ofs_prep_python.sh` | `scripts/exnos_prep_python.sh` |
| `scripts/nosofs/exnos_ofs_nowcast.sh` | `scripts/exnos_nowcast.sh` |
| `scripts/nosofs/exnos_ofs_forecast.sh` | `scripts/exnos_forecast.sh` |
| `scripts/nosofs/exnos_ofs_post.sh` | `scripts/exnos_post.sh` |

(Note: dropping the `nosofs/` subdirectory since this is now SECOFS-UFS-only)

### USH
| old | new |
|---|---|
| `ush/nos_ofs_config.sh` | `ush/nos_config.sh` |
| `ush/nos_ofs_model_run.sh` + `ush/nosofs/nos_ofs_launch.sh` | `ush/nos_run.sh` (consolidated) |

(Dropping: `ush/nosofs/*.sh` — 17 legacy scripts unused under FULL_PYTHON_PREP=YES)

### Python
| old | new |
|---|---|
| `ush/python/nos-utils/` | `ush/python/nos-utils/` (kept as-is — already cleanly named) |
| `ush/python/nos_ofs/` | DROPPED (legacy package, only `utils/yaml_to_env.py` was used; that one moves to `ush/yaml_to_env.py` if needed) |

### PARM
| old | new |
|---|---|
| `parm/systems/secofs_ufs.yaml` | `parm/systems/secofs_ufs.yaml` |
| `parm/base/schism.yaml` | `parm/base/schism.yaml` |

### FIX
| old | new |
|---|---|
| `fix/secofs_ufs/*` | `fix/secofs_ufs/*` (templates kept; mesh stays on WCOSS2) |

### PBS launchers
| old | new |
|---|---|
| `pbs/jnos_secofs_ufs_prep_00.pbs` | `pbs/jnos_prep_00.pbs` |
| `pbs/jnos_secofs_ufs_nowcast_00.pbs` | `pbs/jnos_nowcast_00.pbs` |
| `pbs/jnos_secofs_ufs_forecast_00.pbs` | `pbs/jnos_forecast_00.pbs` |
| `pbs/jnos_secofs_ufs_post_00.pbs` | `pbs/jnos_post_00.pbs` |

## Internal reference updates (sed pass)

Apply across all copied files:
- `nosofs.v3.7.0` → `nos_secofs_ufs`
- `nosofs.${nosofs_ver}` → `nos_secofs_ufs`
- `nosofs/v3.7` (in COM paths) → `nos/secofs_ufs`
- `${nosofs_ver}` and `${nos_ofs_ver}` → removed (no version)
- `nos_ofs_launch.sh` → removed (functionality in nos_run.sh)
- `nos_ofs_model_run.sh` → `nos_run.sh`
- `nos_ofs_config.sh` → `nos_config.sh`
- `JNOS_OFS_*` → `JNOS_*`
- `exnos_ofs_*` → `exnos_*`

## What's NOT renamed (intentional)

- `nos-utils` Python package and modules (already cleanly named)
- `HOMEnos`, `EXECnos`, `FIXnos`, `USHnos`, `PARMnos`, `JOBSnos`, `SCRIPTSnos` env vars (no `nosofs` substring)
- `OFSnos` in some scripts (small footprint, can revisit)
- `FIXofs` env var (this points to the OFS-specific fix subdir, conventional)
- `EXECofs`, `USHofs` similar — convention-based
- Any reference to `nos_ofs_create_tide_fac_schism` (the production Fortran exe — not ours to rename)
- Any reference to `schism_combine_hotstart7.exe` (production Fortran exe)

## Files dropped (not copied)

- `ush/nosofs/` — 14 of 17 scripts unused on SECOFS-UFS path under FULL_PYTHON_PREP=YES
- `ush/python/nos_ofs/` — entire legacy Python package (forcing/, models/, config/, datm/, ensemble/, orchestration/, postprocessing/) is dead code
- All `parm/systems/*.yaml` except `secofs_ufs.yaml` (creofs, dbofs, leofs, ngofs2, secofs, secofs_2d_ufs, stofs_2d_atl, stofs_2d_glo, ...)
- All ROMS / FVCOM `parm/base/` (kept only `schism.yaml`)
- All `JNOS_OFS_ENSEMBLE_*` jobs (separate ensemble flow not in scope)
- `exnos_grib2_prep.sh`, `exnos_ofs_continue_forecast.sh`, `exnos_ofs_obs.sh`, `exnos_ofs_prep_unified.sh`, `exnos_ofs_nowcast_forecast.sh`, `exnos_ofs_ensemble_member.sh`, `exnos_ofs_prep.sh` (legacy / unused on SECOFS-UFS path)
- `nos_ofs_ensemble_run.sh`, `nos_ofs_nowcast_forecast.sh`, `nos_ofs_prep_run.sh` (legacy USH)
