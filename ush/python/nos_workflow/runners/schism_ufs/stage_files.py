"""Stage UFS-Coastal configs, SCHISM input files, forcing tars, and restart artifacts."""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Iterable, Optional

from .context import SchismRunContext

logger = logging.getLogger(__name__)


_UFS_CONFIG_FILES: tuple = (
    "model_configure",
    "datm_in",
    "datm.streams",
    "ufs.configure",
)

# UFS auxiliary files preferred from $FIXofs, fall back to $COMOUT.
_UFS_AUX_FILES: tuple = ("fd_ufs.yaml", "noahmptable.tbl")

_SCHISM_PROPERTY_FILES: tuple = (
    "shapiro.gr3",
    "diffmax.gr3",
    "diffmin.gr3",
    "watertype.gr3",
    "windrot_geo2proj.gr3",
    "albedo.gr3",
    "rough.gr3",
    "drag.gr3",
    "SAL_nudge.gr3",
    "TEM_nudge.gr3",
    "elev.ic",
    "hgrid.ll",
)

# partition.prop is critical: when present, SCHISM uses the pre-computed
# mesh partition instead of calling ParMETIS at runtime.
_SCHISM_PARTITION_FILES: tuple = (
    "partition.prop",
    "tvd.prop",
    "fluxflag.prop",
)


def _copy_if_exists(src: Path, dst: Path, *, label: str = "") -> bool:
    """Copy ``src`` to ``dst`` if ``src`` exists and is non-empty."""
    if not src.is_file():
        return False
    if src.stat().st_size == 0:
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    if label:
        logger.info("  Staged: %s", label)
    return True


def _data_subdir(ctx: SchismRunContext, name: str) -> Path:
    """Build ``$DATA/<name>`` and ensure it exists."""
    p = ctx.data / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def stage_ufs_configs(ctx: SchismRunContext, phase: str) -> int:
    """Stage UFS-Coastal configs, DATM input files, and the UFS executable.

    Returns the number of files staged.
    """
    del phase

    datm_dir_name = os.environ.get("DATM_INPUT_DIR") or "INPUT"
    datm_dir = _data_subdir(ctx, datm_dir_name)
    _data_subdir(ctx, "RESTART")
    _data_subdir(ctx, "outputs")

    staged = 0

    datm_src = ctx.comout / f"{ctx.run}.{ctx.cycle}.datm_input"
    if datm_src.is_dir():
        for src in sorted(datm_src.glob("*.nc")):
            shutil.copy2(src, datm_dir / src.name)
            staged += 1
        logger.info(
            "  Staged %d DATM files to %s/ from %s",
            staged, datm_dir_name, datm_src,
        )
    else:
        logger.warning("DATM input directory not found: %s", datm_src)

    prefix = f"{ctx.run}.{ctx.cycle}"
    for f in _UFS_CONFIG_FILES:
        src = ctx.comout / f"{prefix}.{f}"
        dst = ctx.data / f
        if _copy_if_exists(src, dst, label=f):
            staged += 1
        else:
            logger.warning("UFS config not found: %s", src)

    for f in _UFS_AUX_FILES:
        dst = ctx.data / f
        copied = False
        if ctx.fixofs is not None:
            src_fix = ctx.fixofs / f
            if _copy_if_exists(src_fix, dst):
                staged += 1
                copied = True
        if not copied:
            src_com = ctx.comout / f"{prefix}.{f}"
            if _copy_if_exists(src_com, dst):
                staged += 1

    ufs_exec_name = os.environ.get("UFS_EXEC_NAME") or "fv3_coastalS.exe"
    dst_exec = ctx.data / ufs_exec_name
    already_executable = dst_exec.is_file() and os.access(dst_exec, os.X_OK)
    if not already_executable and ctx.execnos is not None:
        src_exec = ctx.execnos / ufs_exec_name
        if src_exec.is_file() and os.access(src_exec, os.X_OK):
            shutil.copy2(src_exec, dst_exec)
            logger.info("  Staged executable: %s", ufs_exec_name)
            staged += 1

    return staged


def stage_schism_bare_names(ctx: SchismRunContext, phase: str) -> int:
    """Stage SCHISM bare-name input files from $FIXofs.

    SCHISM expects bare filenames in its run directory; $FIXofs holds the
    PREFIXNOS-prefixed equivalents. Returns the number of files staged.
    """
    del phase

    if ctx.fixofs is None:
        logger.warning("stage_schism_bare_names: FIXofs not set; skipping")
        return 0

    staged = 0
    prefix = ctx.prefixnos or ""

    if prefix:
        src = ctx.fixofs / f"{prefix}.hgrid.gr3"
        if _copy_if_exists(src, ctx.data / "hgrid.gr3"):
            staged += 1

    vgrid_ctl = os.environ.get("VGRID_CTL") or ""
    if vgrid_ctl:
        src = ctx.fixofs / vgrid_ctl
        if _copy_if_exists(src, ctx.data / "vgrid.in"):
            staged += 1

    vgrid_nu_ctl = os.environ.get("VGRID_NU_CTL") or (
        f"{prefix}.vgrid.nu.in" if prefix else ""
    )
    if vgrid_nu_ctl:
        src = ctx.fixofs / vgrid_nu_ctl
        if _copy_if_exists(src, ctx.data / "vgrid_nu.in"):
            staged += 1

    sta_out_ctl = os.environ.get("STA_OUT_CTL") or ""
    if sta_out_ctl:
        src = ctx.fixofs / sta_out_ctl
        if _copy_if_exists(src, ctx.data / "station.in"):
            staged += 1

    if prefix:
        for bare in _SCHISM_PROPERTY_FILES:
            src = ctx.fixofs / f"{prefix}.{bare}"
            if _copy_if_exists(src, ctx.data / bare):
                staged += 1

    return staged


def stage_hotstart(ctx: SchismRunContext, phase: str) -> int:
    """Stage $DATA/hotstart.nc from $COMOUT.

    Raises FileNotFoundError if no candidate source matches; raises
    ValueError if ``phase`` is not nowcast / forecast.
    """
    dst = ctx.data / "hotstart.nc"
    dst.parent.mkdir(parents=True, exist_ok=True)

    candidates: list[tuple[str, Optional[Path]]] = []
    if phase == "nowcast":
        if ctx.ini_file_nowcast:
            candidates.append(
                ("INI_FILE_NOWCAST", ctx.comout / ctx.ini_file_nowcast),
            )
        if ctx.ini_file:
            candidates.append(("INI_FILE", Path(ctx.ini_file)))
    elif phase == "forecast":
        if ctx.ini_file_forecast:
            candidates.append(
                ("INI_FILE_FORECAST", ctx.comout / ctx.ini_file_forecast),
            )
        if ctx.rst_out_nowcast:
            candidates.append(
                ("RST_OUT_NOWCAST", ctx.comout / ctx.rst_out_nowcast),
            )
    else:
        raise ValueError(
            f"stage_hotstart: unknown phase {phase!r} (expected nowcast/forecast)"
        )

    for label, src in candidates:
        if src is None:
            continue
        if src.is_file() and src.stat().st_size > 0:
            shutil.copy2(src, dst)
            logger.info("  Staged hotstart.nc from %s (%s)", label, src.name)
            return 1

    searched = "\n".join(
        f"      {label}: {src} (missing or empty)"
        for label, src in candidates
    ) or "      (no candidate paths -- ctx fields are None)"
    raise FileNotFoundError(
        f"stage_hotstart: phase={phase} requires hotstart.nc but no "
        f"source was found.\n  Searched:\n{searched}\n"
        f"  Fix: stage a NETCDF4_CLASSIC hotstart at "
        f"$COMOUT/$PREFIXNOS.init.{phase}.nc (or set $INI_FILE to an "
        f"absolute path)."
    )


def stage_partition_props(ctx: SchismRunContext, phase: str) -> int:
    """Stage SCHISM partition.prop, tvd.prop, and fluxflag.prop from $FIXofs."""
    del phase

    if ctx.fixofs is None or not ctx.prefixnos:
        return 0

    staged = 0
    for prop in _SCHISM_PARTITION_FILES:
        src = ctx.fixofs / f"{ctx.prefixnos}.{prop}"
        if _copy_if_exists(src, ctx.data / prop):
            staged += 1
            if prop == "partition.prop":
                logger.info(
                    "  Staged partition.prop "
                    "(pre-computed, bypasses ParMETIS at runtime)"
                )

    return staged


def stage_bctides_in(ctx: SchismRunContext, phase: str) -> int:
    """Stage $DATA/bctides.in from the prep-generated $COMOUT artifact.

    Falls back to $FIXofs/$HC_FILE_OBC if the prep-generated artifact is
    missing. Returns 1 if staged from either source, 0 otherwise.
    """
    # Use the cycle-stamped name from ctx (built by compute_paths). The
    # bare $PREFIXNOS.bctides.in form drops the cycle stamp and won't
    # match what prep wrote to $COMOUT. BCTIDES_IN env var isn't set in
    # os.environ when stage_files is dispatched without sourcing nos_run.sh.
    if phase == "nowcast":
        bctides_base = (
            ctx.bctides_in_nowcast
            or os.environ.get("BCTIDES_IN")
            or (f"{ctx.prefixnos}.bctides.in" if ctx.prefixnos else "bctides.in")
        )
        bctides_file = f"{bctides_base}.nowcast"
    elif phase == "forecast":
        bctides_base = (
            ctx.bctides_in_forecast
            or os.environ.get("BCTIDES_IN")
            or (f"{ctx.prefixnos}.bctides.in" if ctx.prefixnos else "bctides.in")
        )
        bctides_file = f"{bctides_base}.forecast"
    else:
        logger.warning(
            "stage_bctides_in: unknown phase=%r, skipping", phase,
        )
        return 0

    dst = ctx.data / "bctides.in"
    com_src = ctx.comout / bctides_file
    if _copy_if_exists(com_src, dst, label=f"bctides.in from {bctides_file}"):
        return 1

    hc_file_obc = (
        os.environ.get("HC_FILE_OBC")
        or (f"{ctx.prefixnos}.bctides.in" if ctx.prefixnos else None)
    )
    if hc_file_obc and ctx.fixofs is not None:
        fix_src = ctx.fixofs / hc_file_obc
        if _copy_if_exists(fix_src, dst):
            logger.warning(
                "  Using FIXofs bctides.in (prep-generated %s not found)",
                bctides_file,
            )
            return 1
    return 0


_NWM_FALLBACK_FILES: tuple = ("source_sink.in", "vsource.th", "vsink.th", "msource.th")


def fallback_nwm_files_from_fixofs(ctx: SchismRunContext, phase: str) -> int:
    """Copy NWM source/sink fallback files from $FIXofs when the tar extraction
    left them absent.

    SCHISM aborts if ``if_source=1`` in param.nml and any are missing.
    """
    del phase

    if ctx.fixofs is None or not ctx.prefixnos:
        return 0

    staged = 0
    for fname in _NWM_FALLBACK_FILES:
        dst = ctx.data / fname
        if dst.is_file() and dst.stat().st_size > 0:
            continue
        src = ctx.fixofs / f"{ctx.prefixnos}.{fname}"
        if _copy_if_exists(src, dst):
            logger.info("  Fallback: staged %s from FIXofs", fname)
            staged += 1
        else:
            logger.warning("WARNING: %s not found after NWM tar extraction "
                           "and no FIXofs fallback", fname)
    return staged


# (source, dest) pairs: schism_*.th -> SCHISM canonical names per bctides.in.
_RIVER_RENAMES: tuple = (
    ("schism_temp.th", "TEM_1.th"),
    ("schism_flux.th", "flux.th"),
    ("schism_salt.th", "salt.th"),
)


def rename_river_th_files(ctx: SchismRunContext, phase: str) -> int:
    """Rename schism_*.th river forcing files to SCHISM canonical names."""
    del phase

    renamed = 0
    for src_name, dst_name in _RIVER_RENAMES:
        src = ctx.data / src_name
        if src.is_file() and src.stat().st_size > 0:
            shutil.copy2(src, ctx.data / dst_name)
            renamed += 1
    return renamed


def stage_sflux_inputs_txt(ctx: SchismRunContext, phase: str) -> int:
    """Stage $DATA/sflux/sflux_inputs.txt from $FIXofs if present.

    DATM drives forcing for UFS-Coastal, but SCHISM probes for this file
    in its sflux initialization.
    """
    del phase

    if ctx.fixofs is None or not ctx.prefixnos:
        return 0

    src = ctx.fixofs / f"{ctx.prefixnos}.sflux_inputs.txt"
    if not src.is_file() or src.stat().st_size == 0:
        return 0

    sflux_dir = _data_subdir(ctx, "sflux")
    shutil.copy2(src, sflux_dir / "sflux_inputs.txt")
    return 1


def copy_hgrid_to_outputs(ctx: SchismRunContext, phase: str) -> int:
    """Copy $DATA/hgrid.gr3 to $DATA/outputs/hgrid.gr3.

    SCHISM post-processing utilities (combine_output11 etc.) look for
    hgrid.gr3 in outputs/ rather than the run root.
    """
    del phase

    outputs_dir = _data_subdir(ctx, "outputs")
    src = ctx.data / "hgrid.gr3"
    if not src.is_file() or src.stat().st_size == 0:
        return 0
    shutil.copy2(src, outputs_dir / "hgrid.gr3")
    return 1


# mirror.out / flux.out / staout_1..9 are touched unconditionally at the
# end of the forecast branch so SCHISM's open(status='old') calls don't trip.
_FORECAST_REQUIRED_OUTPUTS: tuple = ("mirror.out", "flux.out") + tuple(
    f"staout_{i}" for i in range(1, 10)
)


def stage_forecast_restart_outputs(ctx: SchismRunContext, phase: str) -> int:
    """Stage previous-cycle restart_outputs for a forecast run (no-op for nowcast)."""
    if phase != "forecast":
        return 0

    outputs_dir = _data_subdir(ctx, "outputs")
    restart_src = ctx.comout / f"{ctx.run}.{ctx.cycle}.restart_outputs"

    staged = 0
    if restart_src.is_dir():
        for f in _FORECAST_REQUIRED_OUTPUTS:
            src = restart_src / f
            if src.is_file():
                shutil.copy2(src, outputs_dir / f)
                staged += 1
        logger.info("  Staged restart_outputs from %s (%d files)",
                    restart_src, staged)
    else:
        logger.warning("restart_outputs not found: %s", restart_src)

    # Touch missing canonical outputs so SCHISM's open(status='old') succeeds.
    for f in _FORECAST_REQUIRED_OUTPUTS:
        (outputs_dir / f).touch(exist_ok=True)

    return staged


def run_python(ctx: SchismRunContext, phase: str) -> int:
    """Compose all staging phases in shell order."""
    from . import configure, forcing, mesh

    stage_ufs_configs(ctx, phase)

    # SCHISM's NUOPC cap inquires for the literal "param.nml" at
    # schism_nuopc_cap.F90:316. setup_paths stages the prefixed file; copy
    # to the bare name BEFORE patch_param_nml runs (otherwise patch is a
    # silent no-op and SCHISM dies at MPI startup).
    runtime_ctl = os.environ.get("RUNTIME_CTL") or (
        f"{ctx.prefixnos}.param.nml" if ctx.prefixnos else "param.nml"
    )
    runtime_ctl_src = ctx.data / runtime_ctl
    param_nml_dst = ctx.data / "param.nml"
    if not param_nml_dst.is_file() and runtime_ctl_src.is_file():
        shutil.copy2(runtime_ctl_src, param_nml_dst)
        logger.info("  Copied %s -> param.nml", runtime_ctl)
    elif not param_nml_dst.is_file():
        logger.error(
            "Cannot stage param.nml: neither $DATA/param.nml nor "
            "$DATA/%s exists. patch_param_nml will skip and SCHISM "
            "will abort at schism_nuopc_cap.F90:316.",
            runtime_ctl,
        )

    configure.patch_model_configure(ctx, phase)
    configure.patch_ufs_configure(ctx, phase)
    configure.patch_param_nml(ctx, phase)
    configure.patch_datm_in(ctx, phase)

    stage_schism_bare_names(ctx, phase)

    stage_partition_props(ctx, phase)

    # bctides.in must precede hotstart so SCHISM finds tides metadata on
    # the same boundary segments referenced by the hotstart.
    stage_bctides_in(ctx, phase)

    stage_hotstart(ctx, phase)

    forcing.untar_nwm_source_sink(ctx, phase)

    fallback_nwm_files_from_fixofs(ctx, phase)

    forcing.untar_obc_forcing(ctx, phase)
    forcing.untar_river_forcing(ctx, phase)

    rename_river_th_files(ctx, phase)

    stage_sflux_inputs_txt(ctx, phase)

    copy_hgrid_to_outputs(ctx, phase)

    stage_forecast_restart_outputs(ctx, phase)

    # Regenerate ESMF mesh from the actual DATM forcing file after patches.
    datm_dir_name = os.environ.get("DATM_INPUT_DIR") or "INPUT"
    forcing_file = ctx.data / datm_dir_name / "datm_forcing.nc"
    esmf_mesh_out = ctx.data / datm_dir_name / "datm_esmf_mesh.nc"
    if forcing_file.is_file() and forcing_file.stat().st_size > 0:
        try:
            mesh.generate_esmf_mesh(forcing_file, esmf_mesh_out)
        except Exception as exc:  # pragma: no cover
            logger.warning("ESMF mesh regen failed: %s", exc)

    return 0


__all__ = [
    "stage_ufs_configs",
    "stage_schism_bare_names",
    "stage_hotstart",
    "stage_partition_props",
    "stage_forecast_restart_outputs",
    "stage_bctides_in",
    "fallback_nwm_files_from_fixofs",
    "rename_river_th_files",
    "stage_sflux_inputs_txt",
    "copy_hgrid_to_outputs",
    "run_python",
]
