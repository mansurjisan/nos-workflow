"""Stage UFS-Coastal configs, SCHISM input files, forcing tars, and restart artifacts."""
from __future__ import annotations

import logging
import os
import re
import shutil
from pathlib import Path
from typing import Iterable, Optional, Tuple

from . import _dateutils
from .context import SchismRunContext

logger = logging.getLogger(__name__)


def _is_ufs() -> bool:
    """True unless Phase-1's resolver explicitly emitted USE_DATM=false.

    Standalone is the ONLY caller that sets ``USE_DATM=false``; unset or
    anything else => UFS (the strict, validated pass-through path).
    """
    return os.environ.get("USE_DATM", "true").strip().lower() != "false"


def _is_wave_enabled() -> bool:
    """True when this system couples WW3 (``ufs_coastal.wav_tasks`` > 0).

    ``WAV_TASKS`` is exported from ``ufs_coastal.wav_tasks`` via
    ``shell_mappings`` only on wave-coupled system YAMLs (e.g.
    secofs_ufs_ww3); it is unset (or 0) on every other system, so this is
    False everywhere except an actual wave-coupled run. All wave-specific
    staging/patching/validation in this package is gated on this single
    predicate so non-wave systems stay byte-identical.
    """
    try:
        return int(os.environ.get("WAV_TASKS", "0") or "0") > 0
    except (TypeError, ValueError):
        return False


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

    return staged


def stage_executable(ctx: SchismRunContext, phase: str) -> int:
    """Stage the model executable from $EXECnos (mode-common).

    UFS: $UFS_EXEC_NAME=fv3_coastalS.exe. Standalone: Phase-1's resolver
    sets $UFS_EXEC_NAME=pschism_WCOSS2 (same env var, different binary).
    """
    del phase

    exec_name = os.environ.get("UFS_EXEC_NAME") or "fv3_coastalS.exe"
    dst_exec = ctx.data / exec_name
    if dst_exec.is_file() and os.access(dst_exec, os.X_OK):
        return 0
    if ctx.execnos is None:
        return 0
    src_exec = ctx.execnos / exec_name
    if src_exec.is_file() and os.access(src_exec, os.X_OK):
        shutil.copy2(src_exec, dst_exec)
        logger.info("  Staged executable: %s", exec_name)
        return 1
    return 0


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
        f"$COMOUT/$RUN.$cycle.$PDY.init.{phase}.nc (or set $INI_FILE to "
        f"an absolute path)."
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


def _archive_manifest_enabled() -> bool:
    """True when the opt-in archive-manifest flag is set (YES/1/TRUE).

    Mirrors ``nos_utils.orchestrator.PrepOrchestrator._archive_manifest_enabled``.
    The St. Lawrence individual files only exist in $COMOUT when prep ran
    with the manifest path AND ``st_lawrence_enabled`` (STOFS-3D-ATL
    only), so this stage-side consumer is gated on the same flag for
    symmetry and is additionally a hard no-op when the files are absent
    (SECOFS).
    """
    return os.environ.get("NOS_ARCHIVE_MANIFEST", "").upper() in (
        "YES", "1", "TRUE",
    )


# St. Lawrence individual archive files -> SCHISM run-dir names.
# Prep writes ``{run}.{cycle}.riv.obs.flux.th`` / ``...riv.obs.tem_1.th``
# (operational STOFS convention; see
# stofs_3d_atl_create_river_st_lawrence.sh and the nos-utils
# archive_to_comout St. Lawrence extra). The legacy run-side restage is
# exstofs_3d_atl_now_forecast.sh:182-225.
_ST_LAWRENCE_RESTAGE: tuple = (
    ("riv.obs.flux.th", "flux.th"),
    ("riv.obs.tem_1.th", "TEM_1.th"),
)


def stage_st_lawrence_river(ctx: SchismRunContext, phase: str) -> int:
    """Restage St. Lawrence flux.th / TEM_1.th from $COMOUT into $DATA.

    STOFS-3D-ATL only. The St. Lawrence climatology is the authoritative
    ``flux.th`` / ``TEM_1.th`` for the STOFS boundary; it must be staged
    AFTER :func:`rename_river_th_files` so the SECOFS-style
    ``schism_temp.th -> TEM_1.th`` / ``schism_flux.th -> flux.th`` rename
    does not clobber it.

    No-op for SECOFS: ``archive_to_comout`` only writes the
    ``{run}.{cycle}.riv.obs.*`` files when ``st_lawrence_enabled`` (false
    for SECOFS), so the source files are absent and nothing is copied.
    Also gated on the ``NOS_ARCHIVE_MANIFEST`` opt-in flag for symmetry
    with the prep side.

    Returns the number of files staged (0..2).
    """
    del phase

    if not _archive_manifest_enabled():
        return 0

    prefix = f"{ctx.run}.{ctx.cycle}"
    staged = 0
    for src_suffix, dst_name in _ST_LAWRENCE_RESTAGE:
        src = ctx.comout / f"{prefix}.{src_suffix}"
        if src.is_file() and src.stat().st_size > 0:
            shutil.copy2(src, ctx.data / dst_name)
            logger.info(
                "  Staged St. Lawrence %s -> %s", src.name, dst_name,
            )
            staged += 1
    return staged


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


def stage_wave_configs(ctx: SchismRunContext, phase: str) -> int:
    """Stage WW3 runtime inputs for a wave-coupled system.

    No-op unless the system couples WW3 (:func:`_is_wave_enabled`) -- this
    keeps every non-wave system's staging behavior byte-identical.

    Stages, all from $FIXofs (falling back to $COMOUT for the two files
    that need per-cycle templating):
      - mod_def.ww3    -- the pre-processed WW3 grid, staged to the bare
                           name WW3 reads from the run directory.
      - the WAV ESMF mesh (``$WAV_MESH``) -- name preserved verbatim; it
                           must match the ``mesh_wav`` attribute CMEPS
                           reads out of ufs.configure.
      - the ocn->wav regrid weight file (``$WAV_OCN2WAV_WEIGHTS``), if
                           configured -- name preserved verbatim; it must
                           match the ``ocn2wav_smapname`` attribute CMEPS
                           reads out of ufs.configure. Precomputed so ESMF
                           skips building an internal dual of SCHISM's mesh
                           for this map at runtime.
      - the wav->ocn regrid weight file (``$WAV_WAV2OCN_WEIGHTS``), if
                           configured -- the transpose-direction twin of
                           the ocn->wav weight file above; name preserved
                           verbatim, must match the ``wav2ocn_smapname``
                           attribute CMEPS reads out of ufs.configure
                           (requires the wav2ocn_smapname CMEPS patch).
      - ww3_shel.nml   -- the WW3 shell control namelist; staged as-is
                           (with @[VAR] placeholders) and patched in place
                           by configure.patch_ww3_shel.
      - the PDLIB solver namelist (``$WAV_PDLIB_NML``), if configured --
                           staged defensively in case ww3_shel/ww3_multi
                           re-reads it directly at run time (not just
                           during offline ww3_grid mesh preprocessing).

    Also stages the per-cycle boundary file nest.ww3 from $COMOUT only
    (there is no FIXofs fallback for a per-cycle artifact) when present.

    Returns the number of files staged.
    """
    del phase

    if not _is_wave_enabled():
        return 0

    staged = 0
    prefix = ctx.prefixnos or ""

    if prefix and ctx.fixofs is not None:
        src = ctx.fixofs / f"{prefix}.mod_def.ww3"
        if _copy_if_exists(src, ctx.data / "mod_def.ww3", label="mod_def.ww3"):
            staged += 1

    wav_mesh = os.environ.get("WAV_MESH") or (
        f"{prefix}.mesh_wav.nc" if prefix else ""
    )
    if wav_mesh and ctx.fixofs is not None:
        src = ctx.fixofs / wav_mesh
        if _copy_if_exists(src, ctx.data / wav_mesh, label=wav_mesh):
            staged += 1

    ocn2wav_weights = os.environ.get("WAV_OCN2WAV_WEIGHTS") or (
        f"{prefix}.ocn2wav_weights.nc" if prefix else ""
    )
    if ocn2wav_weights and ctx.fixofs is not None:
        src = ctx.fixofs / ocn2wav_weights
        if _copy_if_exists(
            src, ctx.data / ocn2wav_weights, label=ocn2wav_weights,
        ):
            staged += 1

    wav2ocn_weights = os.environ.get("WAV_WAV2OCN_WEIGHTS") or (
        f"{prefix}.wav2ocn_weights.nc" if prefix else ""
    )
    if wav2ocn_weights and ctx.fixofs is not None:
        src = ctx.fixofs / wav2ocn_weights
        if _copy_if_exists(
            src, ctx.data / wav2ocn_weights, label=wav2ocn_weights,
        ):
            staged += 1

    run_cycle_prefix = f"{ctx.run}.{ctx.cycle}"
    wave_configs = ["ww3_shel.nml"]
    wav_pdlib_nml = os.environ.get("WAV_PDLIB_NML") or ""
    if wav_pdlib_nml:
        wave_configs.append(wav_pdlib_nml)

    for name in wave_configs:
        dst = ctx.data / name
        copied = False
        if ctx.fixofs is not None:
            src_fix = ctx.fixofs / name
            if _copy_if_exists(src_fix, dst, label=name):
                staged += 1
                copied = True
        if not copied:
            src_com = ctx.comout / f"{run_cycle_prefix}.{name}"
            if _copy_if_exists(src_com, dst, label=name):
                staged += 1

    nest_src = ctx.comout / f"{run_cycle_prefix}.nest.ww3"
    if _copy_if_exists(nest_src, ctx.data / "nest.ww3", label="nest.ww3"):
        staged += 1

    return staged


_DEFAULT_NOWCAST_WARM_START_BACK_HOURS = 24
_DEFAULT_WARM_START_MAX_HS = 25.0

# A real WW3 use_restartnc restart (ufs.cpld.ww3.r.*.nc) stores the 2D
# spectrum as one variable PER spectral component -- va0001, va0002, ...
# vaNSPEC (float32, ~node-length, with a _FillValue of nf90_fill_float,
# +9.9692099683868690e+36, marking inactive/land nodes) -- never a single
# derived Hs-like field. _wave_restart_looks_sane sweeps exactly these
# variables; _VA_VAR_RE is anchored (^va\d+$) so it never matches an
# unrelated variable that merely starts with "va".
_VA_VAR_RE = re.compile(r"^va\d+$")

# Scalar grid-shape variables present in a real restart; not validated
# against anything external here (no independent source of truth for the
# expected spectral grid is available at this call site), but surfaced in
# the guard's accept/reject log line so a grid mismatch between the
# candidate restart and this run's own WW3 grid is at least visible.
_VA_GRID_VAR_NAMES: tuple = ("nth", "nk")


def _cmeps_restart_names(stamp: str) -> Tuple[str, str, str]:
    """Build (mediator, WW3, pointer) basenames for a CMEPS restart stamp.

    Same ``ufs.cpld.<comp>.r.<stamp>.nc`` / ``rpointer.cpl.<stamp>``
    convention setup_paths.compute_paths uses to build
    wav/med_rst_out_nowcast from _dateutils.cmeps_restart_stamp -- inlined
    here (rather than imported) because the nowcast warm-start search
    needs these names for a stamp OTHER than ctx's own
    time_nowcastend-derived one (see _stage_wave_restarts_nowcast).
    """
    return (
        f"ufs.cpld.cpl.r.{stamp}.nc",
        f"ufs.cpld.ww3.r.{stamp}.nc",
        f"rpointer.cpl.{stamp}",
    )


def _nowcast_warm_start_enabled() -> bool:
    """True when the opt-in nowcast warm-start switch is on (default off).

    Plumbed via $WAV_NOWCAST_WARM_START, exported from
    forcing.waves.nowcast_warm_start the same way WAV_MESH/WAV_PDLIB_NML/
    WAV_OCN2WAV_WEIGHTS/WAV_WAV2OCN_WEIGHTS are exported from their
    forcing.waves siblings (see shell_mappings.variables in
    parm/systems/secofs_ufs_ww3.yaml). Off by default: the wave blow-up
    that motivated always cold-starting the nowcast leg must be resolved
    before this is enabled operationally -- cold start currently acts as
    a daily reset for that.
    """
    return os.environ.get("WAV_NOWCAST_WARM_START", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _warm_start_max_hs() -> float:
    """Max Hs-like sanity threshold (meters) for the warm-start guard.

    $WAV_WARM_START_MAX_HS, exported from forcing.waves.warm_start_max_hs
    the same way as the other forcing.waves keys; defaults to 25.0m when
    unset or non-numeric.
    """
    raw = os.environ.get("WAV_WARM_START_MAX_HS", "")
    try:
        return float(raw) if raw else _DEFAULT_WARM_START_MAX_HS
    except (TypeError, ValueError):
        return _DEFAULT_WARM_START_MAX_HS


def _nowcast_warm_start_back_hours() -> int:
    """Backward-search window (hours) for the nowcast warm-start restart.

    $WAV_NOWCAST_WARM_START_BACK_HOURS, an operational override in the
    same spirit as hotstart.find_hotstart's $BACK_SEARCH; defaults to 48h
    when unset or non-numeric. Not YAML-plumbed (no operational need for
    a per-system default beyond this one identified so far); add a
    forcing.waves key later if that changes.
    """
    raw = os.environ.get("WAV_NOWCAST_WARM_START_BACK_HOURS", "")
    try:
        return int(raw) if raw else _DEFAULT_NOWCAST_WARM_START_BACK_HOURS
    except (TypeError, ValueError):
        return _DEFAULT_NOWCAST_WARM_START_BACK_HOURS


def _wave_restart_search_dir(ctx: SchismRunContext, candidate_time: str) -> Path:
    """$COMOUT wave_restart archive dir for a candidate PRIOR cycle.

    Mirrors hotstart._candidate_restart_path's $COMOUTroot/$RUN.$PDY
    per-date layout (NCOEnv: comoutroot defaults to comout.parent when
    $COMOUTROOT is unset) so a candidate cycle on an earlier date --
    or simply an earlier cyc within today's $COMOUT -- resolves to the
    right directory. ``candidate_time`` is a YYYYMMDDHH string; only the
    date and hour are used (NCO cycles are always on-the-hour).
    """
    comoutroot = ctx.comoutroot or ctx.comout.parent
    yyyymmdd = candidate_time[:8]
    hh = candidate_time[8:10]
    return (
        comoutroot / f"{ctx.run}.{yyyymmdd}"
        / f"{ctx.run}.t{hh}z.wave_restart"
    )


def _wave_restart_looks_sane(path: Path) -> Tuple[bool, str]:
    """Cheap sanity guard on a candidate WW3 restart before warm-starting.

    Only used by the nowcast warm-start path (_stage_wave_restarts_nowcast)
    -- the existing forecast handoff restores this SAME cycle's own
    just-completed nowcast leg output, which needs no such guard. The
    nowcast path instead pulls a restart archived a full cycle (or more,
    on the crash-recovery fallback) in the past, so a poisoned file
    (the class of failure behind the wave blow-up this feature is gated
    behind) is worth catching before it propagates into a multi-thousand-
    rank job.

    A real WW3 use_restartnc restart carries the 2D spectrum as one
    variable PER spectral component -- va0001, va0002, ... vaNSPEC
    (float32, ~node-length, _FillValue=nf90_fill_float marking inactive
    nodes) -- alongside time, the nth/nk grid-shape scalars, mapsta, and
    optionally ice. There is no single Hs-like field to threshold against,
    so $WAV_WARM_START_MAX_HS (forcing.waves.warm_start_max_hs, default
    25.0m) is instead converted into a bound on the raw spectral density:

        ceiling = warm_start_max_hs ** 2 * 100.0

    Derivation (order-of-magnitude tripwire, NOT a precise Hs
    computation): Hs = 4*sqrt(E_total), where E_total is the spectrum
    integrated over frequency and direction. A single bin's contribution
    to E_total is ~ N * dsigma * dtheta, where N is that bin's
    action/energy density (the va* value) -- but the actual bin widths
    (dsigma, dtheta) aren't available from the restart file, so a
    rigorous per-bin integral isn't possible here. Instead: treat
    warm_start_max_hs**2 as a proxy for total spectral energy (dropping
    the factor-of-16 from Hs=4*sqrt(E) and the sub-unity bin-width
    factors, both of which only make the bound tighter), then scale it up
    by two more orders of magnitude (100x) as slack for it being a
    SINGLE-bin value rather than the full integral. A physically
    plausible sea state -- even a 25m extreme -- cannot concentrate its
    entire energy budget into one spectral bin at 100x that budget; a
    blown-up (e.g. ~1e18) value trips it trivially.

    For each va* variable: read as a masked array and mask _FillValue
    occurrences using the variable's OWN _FillValue attribute (never
    assume the fill is positive, and never collapse the masked array with
    plain np.asarray -- that silently reads the raw .data buffer,
    including masked fill cells, which is exactly the kind of leak this
    guard exists to avoid). Reject if any UNMASKED value is non-finite
    (NaN/Inf), more negative than a small floating-point tolerance
    (-1e-6; WW3 spectral action/energy density is physically >= 0), or
    exceeds ``ceiling`` above. The nth/nk grid-shape scalars aren't
    checked against anything external (no independent source of truth at
    this call site), but are surfaced in the accept/reject log line so a
    grid mismatch between the candidate restart and this run's own WW3
    grid is at least visible.

    Not over-engineered further: the job here is "obviously-poisoned
    restart => cold start," not a full physical validation. Returns
    (True, "") if the restart passes (or can't be checked -- see below),
    else (False, reason). Never raises: the entire body below is wrapped
    in a catch-all so any unreadable or pathological file (including one
    that raises mid-sweep, e.g. an unsupported variable type) is grounds
    for rejection, not a hard failure -- this only gates an optional warm
    start with an already-loud cold-start fallback, and a crash here must
    never kill the staging job.
    """
    try:
        from netCDF4 import Dataset
        import numpy as np
    except ImportError as exc:
        logger.warning(
            "stage_wave_restarts: netCDF4/numpy not available (%s); "
            "falling back to the size+nonzero check already applied to "
            "%s -- no spectral sanity check performed", exc, path,
        )
        return True, ""

    from ...bash_compat import preserve_preload

    try:
        # Strip LD_PRELOAD before touching netCDF4 -- see
        # mesh.generate_esmf_mesh.
        with preserve_preload():
            try:
                ds = Dataset(str(path), "r")
            except OSError as exc:
                return False, f"unreadable as netCDF ({exc})"
            try:
                max_hs = _warm_start_max_hs()
                ceiling = max_hs ** 2 * 100.0

                grid_bits = []
                for dim_name in _VA_GRID_VAR_NAMES:
                    if dim_name in ds.variables:
                        try:
                            grid_bits.append(
                                f"{dim_name}="
                                f"{int(ds.variables[dim_name][...])}"
                            )
                        except Exception:
                            grid_bits.append(f"{dim_name}=<unreadable>")
                grid_desc = f" [{', '.join(grid_bits)}]" if grid_bits else ""

                va_checked = 0
                va_max = float("-inf")
                for name, var in ds.variables.items():
                    if not _VA_VAR_RE.match(name):
                        continue
                    if not np.issubdtype(var.dtype, np.floating):
                        continue

                    raw = var[:]
                    fill = getattr(var, "_FillValue", None)
                    # Non-finite detection must happen BEFORE any
                    # masked_invalid-style masking: a NaN/Inf cell is
                    # corruption unless it IS the declared fill, and
                    # silently masking it would let a NaN-poisoned
                    # restart through (WW3 reads the original file, not
                    # this guard's masked view).
                    data_arr = np.ma.getdata(raw).astype(
                        "float64", copy=False,
                    )
                    fill_mask = np.ma.getmaskarray(raw).copy()
                    if fill is not None:
                        fill64 = float(fill)
                        if np.isnan(fill64):
                            fill_mask |= np.isnan(data_arr)
                        else:
                            fill_mask |= data_arr == fill64
                    valid = ~fill_mask
                    if data_arr.size == 0 or not valid.any():
                        continue
                    unmasked = data_arr[valid]

                    va_checked += 1
                    if not np.all(np.isfinite(unmasked)):
                        return False, (
                            f"{name} contains non-finite unmasked "
                            f"spectral values{grid_desc}"
                        )
                    vmin = float(unmasked.min())
                    if vmin < -1e-6:
                        return False, (
                            f"{name} contains negative unmasked spectral "
                            f"density (min={vmin:.3g}); WW3 spectral "
                            f"action/energy density must be >= 0"
                            f"{grid_desc}"
                        )
                    vmax = float(unmasked.max())
                    va_max = max(va_max, vmax)
                    if vmax > ceiling:
                        return False, (
                            f"{name} max={vmax:.3g} exceeds the "
                            f"spectral-density ceiling {ceiling:.3g} "
                            f"derived from "
                            f"warm_start_max_hs={max_hs:.2f}m{grid_desc}"
                        )

                if va_checked == 0:
                    logger.warning(
                        "stage_wave_restarts: %s has no va* spectral "
                        "variables to check%s -- not a recognized WW3 "
                        "use_restartnc layout; accepting without a "
                        "spectral sanity check", path, grid_desc,
                    )
                    return True, ""

                logger.debug(
                    "stage_wave_restarts: guard accepted %s -- checked "
                    "%d va* variable(s), max=%.3g (ceiling=%.3g, "
                    "warm_start_max_hs=%.2fm)%s",
                    path, va_checked, va_max, ceiling, max_hs, grid_desc,
                )
                return True, ""
            finally:
                ds.close()
    except Exception as exc:  # never raises -- see docstring
        return False, f"guard error: {exc}"


def _stage_wave_restarts_nowcast(ctx: SchismRunContext) -> bool:
    """Warm-start the nowcast leg's WW3 + CMEPS mediator from a PRIOR cycle.

    Opt-in (see _nowcast_warm_start_enabled) and off by default -- every
    nowcast leg cold-starts WW3 today (see stage_wave_restarts's forecast
    branch, which only restores THIS SAME cycle's own nowcast-end output
    into the forecast leg). This restores the PREVIOUS cycle's archived
    nowcast-end restart instead, so the nowcast leg itself stops resetting
    the wave spectrum every cycle.

    Stamp: this nowcast's own start time is ctx.time_hotstart (see
    configure._resolve_phase_anchors -- nowcast's sim_start), exactly the
    instant a normally-cycling predecessor's OWN nowcast leg ended
    (setup_paths.compute_paths stamps wav/med_rst_out_nowcast from
    time_nowcastend, which _compute_filenames/_read_comout_time_anchors
    set to that cycle's own nominal PDY+cyc). So the immediate
    predecessor cycle (one cycle-interval, i.e. one LEN_NOWCAST, back)
    is the exact, non-stale match for THIS leg's start.

    Search: walk candidate predecessor cycles backward from there in
    LEN_NOWCAST steps -- the same ndate-walk shape as
    hotstart.find_hotstart's back-search -- up to
    $WAV_NOWCAST_WARM_START_BACK_HOURS (default 48h). Each candidate is
    checked under ITS OWN natural stamp (its own nominal cycle time);
    a complete match found on any candidate OTHER than the immediate
    predecessor is a crash-recovery fallback and is therefore stale by
    that many extra hours.

    The default window is one cycle interval, so in normal operation only
    the immediate predecessor qualifies and anything staler cold-starts.
    That default was 48h on the reasoning that a stale warm start beats a
    needless cold start. A run on 2026-08-28 showed the opposite: with the
    immediate predecessor's archive unreachable, the search fell back to a
    48h-stale wave field, restaged it onto this leg's stamp, and SCHISM
    aborted in bktrk_subs (backtracking overflow). The operational
    cold-start run of the same cycle, same forcing, passed. A wave field
    two days out of date drives radiation stress inconsistent with the
    ocean state it is applied to, and cold start is a safe, known
    fallback -- so the trade runs the other way.

    Widen $WAV_NOWCAST_WARM_START_BACK_HOURS deliberately if a longer
    reach is ever wanted; a fallback beyond the immediate predecessor is
    still staged and still logged loudly, it is just no longer the
    default.

    All-three-or-nothing per candidate, restaged (never verbatim) to
    THIS leg's own stamp -- the same destinations
    stage_wave_restarts's forecast branch uses, just keyed on
    time_hotstart instead of time_nowcastend:
      - $DATA/RESTART/ufs.cpld.cpl.r.<stamp>.nc
      - $DATA/rpointer.cpl.<stamp>   (content reconstructed to reference
        the restaged mediator filename above -- NOT copied byte-for-byte
        like the forecast branch, because a fallback candidate's archived
        pointer names ITS OWN stamp, not this leg's)
      - $DATA/ufs.cpld.ww3.r.<stamp>.nc

    A complete candidate also passes _wave_restart_looks_sane before
    staging; a poisoned candidate is rejected (logged) and the backward
    search continues, same as a partial one.

    Unlike the forecast branch, a partial archive here does NOT raise --
    logs a warning naming the missing pieces and keeps searching older
    candidates. Rationale: a prior cycle's crash must never wedge the
    next cycle's nowcast. Returns True if a complete, sane candidate was
    staged; False if the entire search window turned up nothing usable
    (cold start, exactly today's behavior).
    """
    if not ctx.time_hotstart or not ctx.len_nowcast:
        logger.warning(
            "stage_wave_restarts: nowcast warm start requires "
            "ctx.time_hotstart and ctx.len_nowcast (time_hotstart missing?); "
            "treating as cold start",
        )
        return False

    # NOTE: this equates the backward-search step with THIS system's own
    # nowcast leg length, i.e. it assumes cycle spacing == hindcast_days
    # (LEN_NOWCAST). That holds for SECOFS today (its cadence matches its
    # nowcast length), so walking back one LEN_NOWCAST always lands
    # exactly on the previous cycle's own nowcast-end stamp. It would be
    # WRONG for a system whose cycle cadence differs from its nowcast
    # length (e.g. a 6h-cadence system with a 12h nowcast leg) -- the
    # step would overshoot or undershoot the actual predecessor cycle.
    # Revisit (probably by threading an explicit cycle-interval value
    # through ctx) before enabling this feature on such a system.
    try:
        interval = int(ctx.len_nowcast)
    except (TypeError, ValueError):
        interval = 0
    if interval <= 0:
        logger.warning(
            "stage_wave_restarts: LEN_NOWCAST=%r is not a positive "
            "integer; cannot step the nowcast warm-start backward "
            "search -- treating as cold start", ctx.len_nowcast,
        )
        return False

    back_hours = _nowcast_warm_start_back_hours()
    dest_stamp = _dateutils.cmeps_restart_stamp(ctx.time_hotstart)
    dest_med_name, dest_wav_name, dest_pointer_name = _cmeps_restart_names(
        dest_stamp,
    )

    partial_seen = False
    poisoned_seen = False
    offset = 0
    while offset <= back_hours:
        candidate_time = _dateutils.ndate(-offset, ctx.time_hotstart)
        candidate_stamp = _dateutils.cmeps_restart_stamp(candidate_time)
        candidate_med, candidate_wav, candidate_pointer = _cmeps_restart_names(
            candidate_stamp,
        )
        archive_dir = _wave_restart_search_dir(ctx, candidate_time)

        med_src = archive_dir / candidate_med
        wav_src = archive_dir / candidate_wav
        pointer_src = archive_dir / candidate_pointer

        found = {
            "mediator restart": med_src.is_file() and med_src.stat().st_size > 0,
            "WW3 restart": wav_src.is_file() and wav_src.stat().st_size > 0,
            "pointer file": pointer_src.is_file() and pointer_src.stat().st_size > 0,
        }

        if all(found.values()):
            ok, reason = _wave_restart_looks_sane(wav_src)
            if not ok:
                poisoned_seen = True
                logger.warning(
                    "stage_wave_restarts: rejecting nowcast warm-start "
                    "candidate at %s (offset=%dh from %s): %s -- "
                    "continuing the backward search rather than "
                    "warm-starting from a poisoned restart",
                    archive_dir, offset, ctx.time_hotstart, reason,
                )
                offset += interval
                continue

            # Re-stamping (copying the candidate's files to THIS leg's own
            # stamp rather than its native one) is safe ONLY because
            # wav_restart_mod's netCDF read path (use_restartnc) ignores
            # the restart file's own internal time field and simply
            # trusts the filename/pointer it's told to open. The BINARY
            # WW3 restart path (restart_from_binary='true' in
            # ufs.configure) DOES validate the internal time against the
            # run's expected start and would hard-abort on a mismatch --
            # this whole re-stamping feature requires restart_from_binary
            # to stay 'false' there.
            restart_dir = ctx.data / "RESTART"
            restart_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(med_src, restart_dir / dest_med_name)
            shutil.copy2(wav_src, ctx.data / dest_wav_name)
            (ctx.data / dest_pointer_name).write_text(f"RESTART/{dest_med_name}\n")

            if offset == 0:
                logger.info(
                    "  Staged nowcast wave restart handoff: %s, %s, %s "
                    "(from %s)", dest_med_name, dest_wav_name,
                    dest_pointer_name, archive_dir,
                )
            else:
                logger.warning(
                    "  Staged nowcast wave restart handoff from a %dh-"
                    "stale predecessor cycle (%s) -- the immediate "
                    "predecessor's archive was missing or partial: %s, "
                    "%s, %s (from %s)",
                    offset, candidate_time, dest_med_name, dest_wav_name,
                    dest_pointer_name, archive_dir,
                )
            return True

        if any(found.values()):
            partial_seen = True
            missing = [label for label, ok in found.items() if not ok]
            logger.warning(
                "stage_wave_restarts: partial wave restart archive at %s "
                "(offset=%dh from %s) -- missing %s; this is NOT a "
                "legitimate cold start, but the nowcast leg never raises "
                "for it -- continuing the backward search rather than "
                "wedging this cycle on a prior cycle's crash.",
                archive_dir, offset, ctx.time_hotstart, missing,
            )

        offset += interval

    extra = []
    if partial_seen:
        extra.append("partial archive(s) seen but never complete")
    if poisoned_seen:
        extra.append("a poisoned candidate was rejected")
    suffix = f" ({'; '.join(extra)})" if extra else ""
    logger.warning(
        "stage_wave_restarts: no usable archived wave restart found in "
        "the %dh nowcast warm-start search window back from %s%s; "
        "treating this as a cold start -- WW3 and the CMEPS mediator "
        "will start up fresh for this nowcast leg.",
        back_hours, ctx.time_hotstart, suffix,
    )
    return False


def stage_wave_restarts(ctx: SchismRunContext, phase: str) -> bool:
    """Restore the WW3 + CMEPS mediator restart handoff into $DATA.

    Wave systems only -- False (no-op) otherwise. SCHISM cycles
    nowcast->forecast via its own hotstart (ihot=1), but WW3 and the
    CMEPS mediator have no such mechanism under UFS-Coastal NUOPC -- they
    cycle via CMEPS netCDF restarts (see execute._archive_wave_restarts)
    and must be staged back here before ``configure.patch_ufs_configure``
    decides start_type for the leg.

    Two independent handoffs, both gated on this same entry point:
      - forecast (always on): restores THIS SAME cycle's own nowcast-end
        restart -- the cross-leg handoff that has existed since this
        system's wave coupling landed. See the artifact list and
        cold-start/partial-archive policy below.
      - nowcast (opt-in, off by default -- see
        _nowcast_warm_start_enabled): restores the PREVIOUS cycle's
        archived nowcast-end restart, so the nowcast leg stops
        cold-starting WW3 every cycle. See
        :func:`_stage_wave_restarts_nowcast` for that branch's search,
        staleness, and sanity-guard policy, which differs from the
        forecast branch's below (crash tolerance instead of a hard
        raise on a partial archive).

    Forecast branch -- three artifacts, restored verbatim (filenames and
    the pointer file's content untouched -- CDEPS/WW3 locate them by
    these exact names/paths):
      - $DATA/RESTART/ufs.cpld.cpl.r.<stamp>.nc  (mediator restart;
        ufs.configure's restart_dir = RESTART/)
      - $DATA/rpointer.cpl.<stamp>                (pointer file, run-dir
        root; its CONTENT is the RESTART/-relative mediator path -- copied
        byte-for-byte, never reconstructed, so that content is guaranteed
        correct)
      - $DATA/ufs.cpld.ww3.r.<stamp>.nc            (WW3 restart, run-dir
        root -- w3initmd's read path has no directory prefix)

    Cold-start policy: if NONE of the three artifacts exist in the
    archived $COMOUT location, this is treated as the system's first-ever
    wave-coupled cycle (nothing to restore yet) -- returns False, and
    ``configure.patch_ufs_configure`` falls back to start_type=startup
    with a loud warning. If only SOME are found, that is NOT a legitimate
    cold start (this cycle's own nowcast leg ran and, being wave-enabled,
    should have produced all three together) -- raises
    FileNotFoundError rather than silently guessing, matching
    :func:`stage_hotstart`'s convention for SCHISM's own restart.
    ``execute._archive_wave_restarts`` now assembles the archive
    atomically (tmp dir + rename into place only on full success), so in
    normal operation this branch should be unreachable -- the archive
    dir is either absent or complete, never mixed. The raise stays as
    defense-in-depth for anything that predates that fix or otherwise
    tampers with the archive dir directly.

    Returns True if all three artifacts were staged, False on the
    cold-start fallback (nothing archived).
    """
    if not _is_wave_enabled():
        return False

    if phase == "nowcast":
        if not _nowcast_warm_start_enabled():
            return False
        return _stage_wave_restarts_nowcast(ctx)

    if phase != "forecast":
        return False

    if not ctx.med_rst_out_nowcast or not ctx.wav_rst_out_nowcast or not ctx.time_nowcastend:
        logger.warning(
            "stage_wave_restarts: wave restart filenames not resolved in "
            "ctx (time_nowcastend missing?); treating as cold start",
        )
        return False

    stamp = _dateutils.cmeps_restart_stamp(ctx.time_nowcastend)
    pointer_name = f"rpointer.cpl.{stamp}"

    # Must match execute._wave_restart_comout_dir -- the archive side.
    archive_dir = ctx.comout / f"{ctx.run}.{ctx.cycle}.wave_restart"
    med_src = archive_dir / ctx.med_rst_out_nowcast
    wav_src = archive_dir / ctx.wav_rst_out_nowcast
    pointer_src = archive_dir / pointer_name

    found = {
        "mediator restart": med_src.is_file() and med_src.stat().st_size > 0,
        "pointer file": pointer_src.is_file() and pointer_src.stat().st_size > 0,
        "WW3 restart": wav_src.is_file() and wav_src.stat().st_size > 0,
    }

    if not any(found.values()):
        logger.warning(
            "stage_wave_restarts: no archived wave restart at %s; "
            "treating this as the first wave-coupled cycle for this "
            "system (cold start -- WW3 and the CMEPS mediator will "
            "start up fresh for this forecast leg). If this is NOT the "
            "first cycle, the prior nowcast leg failed to archive its "
            "wave restart -- check that leg's "
            "execute._archive_wave_restarts logs.",
            archive_dir,
        )
        return False

    if not all(found.values()):
        missing = [label for label, ok in found.items() if not ok]
        present = [label for label, ok in found.items() if ok]
        raise FileNotFoundError(
            f"stage_wave_restarts: forecast requires the wave restart "
            f"handoff but only found {present} in {archive_dir} -- "
            f"missing {missing}. This is a partial archive, not a "
            f"legitimate cold start (this cycle's nowcast leg ran and, "
            f"being wave-enabled, should have produced all three "
            f"together); refusing to guess rather than launch a "
            f"multi-thousand-rank job that aborts at init. Fix: inspect "
            f"the nowcast leg's execute._archive_wave_restarts logs."
        )

    restart_dir = ctx.data / "RESTART"
    restart_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(med_src, restart_dir / ctx.med_rst_out_nowcast)
    shutil.copy2(wav_src, ctx.data / ctx.wav_rst_out_nowcast)
    shutil.copy2(pointer_src, ctx.data / pointer_name)
    logger.info(
        "  Staged wave restart handoff: %s, %s, %s (from %s)",
        ctx.med_rst_out_nowcast, ctx.wav_rst_out_nowcast, pointer_name,
        archive_dir,
    )
    return True


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


def _stage_standalone_param_nml(ctx: SchismRunContext) -> bool:
    """Prefer the legacy-schema standalone param.nml when present.

    The staged $RUNTIME_CTL ($DATA/<prefix>.param.nml) is authored for the
    UFS-Coastal SCHISM schema (has &CORE nbins_veg_vert/nmarsh_types); the
    operational standalone pschism uses the legacy schema (isav, no veg
    keys) and SCHISM's nml_read ABORTS on unrecognized keys. If
    $FIXofs/<prefix>.standalone.param.nml exists, copy it to $DATA so the
    downstream bare-name rename picks it up; otherwise fall back to the
    UFS file with a loud WARNING (parent must author the legacy file).
    Returns True if the standalone variant was staged.
    """
    if ctx.fixofs is None or not ctx.prefixnos:
        return False
    src = ctx.fixofs / f"{ctx.prefixnos}.standalone.param.nml"
    if not src.is_file() or src.stat().st_size == 0:
        logger.warning(
            "standalone: %s not found; falling back to the UFS-schema "
            "param.nml. pschism will ABORT in nml_read if its &CORE "
            "schema differs (nbins_veg_vert/nmarsh_types vs isav). "
            "Author a legacy-schema %s.standalone.param.nml in $FIXofs.",
            src, ctx.prefixnos,
        )
        return False
    dst = ctx.data / f"{ctx.prefixnos}.param.nml"
    shutil.copy2(src, dst)
    logger.info("  Staged standalone param.nml: %s", src.name)
    return True


# Canonical $DATA destination names by manifest (category, source). Used by
# collect_staged_inputs to surface what run_python staged WITHOUT changing the
# count-returning signatures of the staging/untar helpers: every entry is a
# deterministic run-dir name the helpers above resolve, so presence in $DATA
# after staging is the source of truth.
_HOTSTART_DEST: tuple = ("hotstart.nc",)
_UFS_CONFIG_DEST: tuple = _UFS_CONFIG_FILES + _UFS_AUX_FILES
_TIDAL_DEST: tuple = ("bctides.in",)

# bare-name SCHISM static inputs (grid/vgrid/station/property/partition files).
_FIX_DEST: tuple = (
    "hgrid.gr3",
    "vgrid.in",
    "vgrid_nu.in",
    "station.in",
) + _SCHISM_PROPERTY_FILES + _SCHISM_PARTITION_FILES

# St. Lawrence climatology run-dir names (subset of river; collected as a
# distinct source only when the gated restage actually placed them).
_ST_LAWRENCE_DEST: tuple = tuple(
    dst for _src, dst in _ST_LAWRENCE_RESTAGE
)
# river.th canonical names produced by rename_river_th_files.
_RIVER_DEST: tuple = tuple(dst for _src, dst in _RIVER_RENAMES)


def _present_in_data(ctx: SchismRunContext, names: Iterable[str]) -> list:
    """Return full $DATA paths for ``names`` that exist as non-empty files."""
    out = []
    for name in names:
        p = ctx.data / name
        if p.is_file() and p.stat().st_size > 0:
            out.append(str(p))
    return out


def collect_staged_inputs(
    ctx: SchismRunContext, phase: str, *, ufs: bool,
) -> "InputCollector":
    """Build an :class:`InputCollector` of the inputs staged into $DATA.

    Reads the deterministic run-dir destinations the staging helpers
    resolve (the helpers themselves return counts only; presence in $DATA
    is the source of truth here). Mapped to the cross-repo category/source
    convention shared with the prep manifest.
    """
    from ...inputs_manifest import InputCollector
    from .forcing import (
        _NWM_PAYLOAD_NAMES,
        _OBC_PAYLOAD_NAMES,
    )

    collector = InputCollector()

    collector.add("hotstart", "HOTSTART", _present_in_data(ctx, _HOTSTART_DEST))
    collector.add("ocean", "OBC", _present_in_data(ctx, _OBC_PAYLOAD_NAMES))
    collector.add("river", "NWM", _present_in_data(ctx, _NWM_PAYLOAD_NAMES))
    collector.add("river", "RIVER", _present_in_data(ctx, _RIVER_DEST))
    collector.add(
        "river", "ST_LAWRENCE", _present_in_data(ctx, _ST_LAWRENCE_DEST),
    )
    collector.add("tidal", "TIDAL", _present_in_data(ctx, _TIDAL_DEST))
    collector.add("static", "FIX", _present_in_data(ctx, _FIX_DEST))

    if _is_wave_enabled():
        wav_mesh = os.environ.get("WAV_MESH") or (
            f"{ctx.prefixnos}.mesh_wav.nc" if ctx.prefixnos else ""
        )
        wav_pdlib_nml = os.environ.get("WAV_PDLIB_NML") or ""
        ocn2wav_weights = os.environ.get("WAV_OCN2WAV_WEIGHTS") or (
            f"{ctx.prefixnos}.ocn2wav_weights.nc" if ctx.prefixnos else ""
        )
        wav2ocn_weights = os.environ.get("WAV_WAV2OCN_WEIGHTS") or (
            f"{ctx.prefixnos}.wav2ocn_weights.nc" if ctx.prefixnos else ""
        )
        wave_dest = ["mod_def.ww3", "ww3_shel.nml", "nest.ww3"]
        if wav_mesh:
            wave_dest.append(wav_mesh)
        if wav_pdlib_nml:
            wave_dest.append(wav_pdlib_nml)
        if ocn2wav_weights:
            wave_dest.append(ocn2wav_weights)
        if wav2ocn_weights:
            wave_dest.append(wav2ocn_weights)
        collector.add("wave", "WW3", _present_in_data(ctx, wave_dest))

    if ufs:
        collector.add(
            "static", "UFS_CONFIG", _present_in_data(ctx, _UFS_CONFIG_DEST),
        )
        datm_dir_name = os.environ.get("DATM_INPUT_DIR") or "INPUT"
        datm_dir = ctx.data / datm_dir_name
        datm_files = (
            [str(p) for p in sorted(datm_dir.glob("*.nc"))]
            if datm_dir.is_dir() else []
        )
        collector.add("datm", "DATM", datm_files)
    else:
        sflux_dir = ctx.data / "sflux"
        sflux_files = (
            [str(p) for p in sorted(sflux_dir.glob("sflux_*.nc"))]
            if sflux_dir.is_dir() else []
        )
        collector.add("atmospheric", "MET", sflux_files)

    return collector


def run_python(ctx: SchismRunContext, phase: str):
    """Compose all staging phases in shell order.

    Returns ``(rc, collector)``: ``rc`` is the staging return code (0 on
    success, preserved from the legacy int-returning contract) and
    ``collector`` is an :class:`InputCollector` of the inputs staged into
    $DATA, for the per-stage input manifest. Callers that only need the rc
    can unpack the first element.
    """
    from . import configure, forcing, mesh

    ufs = _is_ufs()

    if ufs:
        stage_ufs_configs(ctx, phase)
    else:
        _stage_standalone_param_nml(ctx)

    stage_wave_configs(ctx, phase)
    # Must run BEFORE patch_ufs_configure below: it decides start_type by
    # checking what this staged into $DATA.
    stage_wave_restarts(ctx, phase)

    stage_executable(ctx, phase)

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

    if ufs:
        configure.patch_model_configure(ctx, phase)
        configure.patch_ufs_configure(ctx, phase)
    configure.patch_param_nml(ctx, phase)
    if ufs:
        configure.patch_datm_in(ctx, phase)
    if _is_wave_enabled():
        configure.patch_ww3_shel(ctx, phase)

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

    # STOFS-3D-ATL only; must follow rename_river_th_files so the
    # St. Lawrence climatology is not clobbered by the schism_*.th
    # rename. No-op for SECOFS (source files absent).
    stage_st_lawrence_river(ctx, phase)

    stage_sflux_inputs_txt(ctx, phase)

    copy_hgrid_to_outputs(ctx, phase)

    stage_forecast_restart_outputs(ctx, phase)

    if ufs:
        # Regenerate ESMF mesh from the actual DATM forcing file after patches.
        datm_dir_name = os.environ.get("DATM_INPUT_DIR") or "INPUT"
        forcing_file = ctx.data / datm_dir_name / "datm_forcing.nc"
        esmf_mesh_out = ctx.data / datm_dir_name / "datm_esmf_mesh.nc"
        if forcing_file.is_file() and forcing_file.stat().st_size > 0:
            try:
                mesh.generate_esmf_mesh(forcing_file, esmf_mesh_out)
            except Exception as exc:  # pragma: no cover
                logger.warning("ESMF mesh regen failed: %s", exc)
    else:
        # Standalone SCHISM (nws=2) reads sflux from $DATA/sflux/ instead
        # of DATM; prep tarred it to $COMOUT.
        forcing.untar_met_sflux(ctx, phase)

    # Input-manifest collection must never fail staging — on any error,
    # fall back to an empty collector (the manifest is provenance metadata).
    try:
        collector = collect_staged_inputs(ctx, phase, ufs=ufs)
    except Exception as exc:  # noqa: BLE001
        logger.warning("input collection skipped: %s", exc)
        from ...inputs_manifest import InputCollector
        collector = InputCollector()
    return 0, collector


__all__ = [
    "_is_ufs",
    "_is_wave_enabled",
    "_cmeps_restart_names",
    "stage_ufs_configs",
    "stage_wave_configs",
    "stage_wave_restarts",
    "stage_executable",
    "stage_schism_bare_names",
    "stage_hotstart",
    "stage_partition_props",
    "stage_forecast_restart_outputs",
    "stage_bctides_in",
    "fallback_nwm_files_from_fixofs",
    "rename_river_th_files",
    "stage_st_lawrence_river",
    "stage_sflux_inputs_txt",
    "copy_hgrid_to_outputs",
    "collect_staged_inputs",
    "run_python",
]
