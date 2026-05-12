"""Python port of ``_schism_stage_files`` (PR 7a: static staging only).

PR 7a covers the static-file-staging phases of the shell function in
``ush/nos_run.sh`` (lines 395-768). Specifically:

  - :func:`stage_ufs_configs`   -- UFS-Coastal config + DATM input
    staging (model_configure, datm_in, datm.streams, ufs.configure,
    fd_ufs.yaml, noahmptable.tbl, and the UFS executable). Shell
    counterpart: lines 452-490 (the ``USE_DATM == true`` block).
  - :func:`stage_schism_bare_names` -- SCHISM bare-name input files
    (hgrid.gr3, vgrid.in, vgrid_nu.in, station.in + optional grid
    property files). Shell counterpart: lines 571-586.
  - :func:`stage_hotstart`      -- hotstart.nc from $COMOUT. Shell
    counterpart: lines 628-665 (phase-aware; nowcast uses
    INI_FILE_NOWCAST, forecast uses INI_FILE_FORECAST / RST_OUT_NOWCAST).
  - :func:`stage_partition_props` -- partition.prop + tvd.prop +
    fluxflag.prop from $FIXofs. Shell counterpart: lines 602-607.
  - :func:`stage_forecast_restart_outputs` -- forecast-only:
    previous-cycle restart_outputs (mirror.out / flux.out / staout_*)
    from $COMOUT. Shell counterpart: lines 744-764.

Phases held for follow-up PRs:

  - PR 7b: forcing tar extraction (lines 670-734) + namelist patching
    (lines 498-565 -- uses :mod:`patches`).
  - PR 7c: wire ``stage_files.run_python`` into the stage dispatcher
    and flip the runner flag.

Public API (each function takes a :class:`SchismRunContext` + ``phase``
string, returns ``int`` of files staged or raises on a fatal failure)::

    stage_ufs_configs(ctx, phase) -> int
    stage_schism_bare_names(ctx, phase) -> int
    stage_hotstart(ctx, phase) -> int                  # raises FileNotFoundError
    stage_partition_props(ctx, phase) -> int
    stage_forecast_restart_outputs(ctx, phase) -> int  # no-op on nowcast
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Iterable, Optional

from .context import SchismRunContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Optional / required file lists (kept as module-level tuples so tests can
# import + assert on them without re-running the staging logic).
# ---------------------------------------------------------------------------

# UFS config files staged from $COMOUT (one per file; the shell loop at
# lines 466-474 of nos_run.sh enumerates these).
_UFS_CONFIG_FILES: tuple = (
    "model_configure",
    "datm_in",
    "datm.streams",
    "ufs.configure",
)

# UFS auxiliary files that come from $FIXofs OR $COMOUT (shell prefers
# $FIXofs first, falls back to $COMOUT -- lines 477-483).
_UFS_AUX_FILES: tuple = ("fd_ufs.yaml", "noahmptable.tbl")

# Optional SCHISM property files staged with the PREFIXNOS prefix from
# $FIXofs (lines 580-586). Each is OPTIONAL -- missing = silent skip.
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

# SCHISM partition / mesh tuning files (lines 602-607). Each is staged
# only if the prefixed source exists; partition.prop in particular is
# the critical one (PR 230 fix: bypasses ParMETIS at runtime).
_SCHISM_PARTITION_FILES: tuple = (
    "partition.prop",
    "tvd.prop",
    "fluxflag.prop",
)


def _copy_if_exists(src: Path, dst: Path, *, label: str = "") -> bool:
    """``cp -p src dst`` if ``src`` exists and is non-empty. Returns
    True on success, False otherwise. Mirrors the shell's
    ``[ -s "$src" ] && cp -p "$src" "$dst"`` guard."""
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


# ---------------------------------------------------------------------------
# Phase 1: UFS-Coastal config + DATM input staging
# ---------------------------------------------------------------------------


def stage_ufs_configs(ctx: SchismRunContext, phase: str) -> int:
    """Stage UFS-Coastal configs + DATM input artifacts.

    Mirrors lines 452-490 of nos_run.sh (the ``USE_DATM == true``
    block). Specifically:

      1. ``mkdir -p $DATA/{INPUT,RESTART,outputs}``
      2. Copy ``$COMOUT/$RUN.$cycle.datm_input/*.nc`` to
         ``$DATA/INPUT/`` (the DATM forcing NetCDFs).
      3. Copy each of ``model_configure``, ``datm_in``,
         ``datm.streams``, ``ufs.configure`` from
         ``$COMOUT/$RUN.$cycle.<file>`` to ``$DATA/<file>``.
      4. Copy ``fd_ufs.yaml`` and ``noahmptable.tbl`` from $FIXofs
         (preferred) or $COMOUT (fallback).
      5. Stage the UFS executable (``$EXECnos/fv3_coastalS.exe`` ->
         ``$DATA/fv3_coastalS.exe``) if present and not already there.

    The shell allows :envvar:`DATM_INPUT_DIR` (default ``INPUT``) and
    :envvar:`UFS_EXEC_NAME` (default ``fv3_coastalS.exe``) overrides;
    Python reads them via ``os.environ.get`` to preserve behavior.

    Args:
        ctx: runner context (provides ``data``, ``comout``, ``run``,
            ``cycle``, ``fixofs``, ``execnos``).
        phase: ``"nowcast"`` or ``"forecast"``. Unused here -- both
            phases stage the same set -- but retained for API
            consistency with the other ``stage_*`` helpers.

    Returns:
        Number of files staged (0 if nothing matched).
    """
    del phase  # phase-agnostic; kept in signature for caller symmetry

    # Directory scaffolding -- mirrors line 454.
    datm_dir_name = os.environ.get("DATM_INPUT_DIR") or "INPUT"
    datm_dir = _data_subdir(ctx, datm_dir_name)
    _data_subdir(ctx, "RESTART")
    _data_subdir(ctx, "outputs")

    staged = 0

    # ---- 2. DATM forcing NetCDFs from $COMOUT/$RUN.$cycle.datm_input/
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

    # ---- 3. UFS configs from $COMOUT/$RUN.$cycle.<file>
    prefix = f"{ctx.run}.{ctx.cycle}"
    for f in _UFS_CONFIG_FILES:
        src = ctx.comout / f"{prefix}.{f}"
        dst = ctx.data / f
        if _copy_if_exists(src, dst, label=f):
            staged += 1
        else:
            logger.warning("UFS config not found: %s", src)

    # ---- 4. Auxiliary files from $FIXofs (preferred) or $COMOUT
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

    # ---- 5. UFS executable (only if not already staged AND src exists)
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


# ---------------------------------------------------------------------------
# Phase 2: SCHISM bare-name file staging
# ---------------------------------------------------------------------------


def stage_schism_bare_names(ctx: SchismRunContext, phase: str) -> int:
    """Stage SCHISM bare-name input files from $FIXofs.

    Mirrors lines 571-586 of nos_run.sh. SCHISM expects bare filenames
    (``hgrid.gr3``, ``vgrid.in``, ``station.in``, etc.) in its run
    directory; the canonical filenames in $FIXofs are PREFIXNOS-prefixed
    (e.g. ``nos.secofs_ufs.hgrid.gr3``). This function copies + strips
    the prefix.

    Required-ish bare-name files (each is conditionally staged via
    ``[ -s ... ] && cp -p``):

      - ``$PREFIXNOS.hgrid.gr3`` -> ``$DATA/hgrid.gr3``
      - ``$VGRID_CTL``           -> ``$DATA/vgrid.in``
      - ``$VGRID_NU_CTL`` or ``$PREFIXNOS.vgrid.nu.in`` -> ``$DATA/vgrid_nu.in``
      - ``$STA_OUT_CTL``         -> ``$DATA/station.in``

    Optional property files (loop at lines 580-586) -- each is staged
    only if the prefixed source exists; missing entries are silent
    skips. See :data:`_SCHISM_PROPERTY_FILES` for the full list.

    Args:
        ctx: runner context (needs ``fixofs``, ``data``, ``prefixnos``).
        phase: unused; kept for API symmetry.

    Returns:
        Number of files staged.
    """
    del phase

    if ctx.fixofs is None:
        logger.warning("stage_schism_bare_names: FIXofs not set; skipping")
        return 0

    staged = 0
    prefix = ctx.prefixnos or ""

    # ---- hgrid.gr3 (prefixed in $FIXofs, bare in $DATA)
    if prefix:
        src = ctx.fixofs / f"{prefix}.hgrid.gr3"
        if _copy_if_exists(src, ctx.data / "hgrid.gr3"):
            staged += 1

    # ---- vgrid.in (from $VGRID_CTL env var -- the canonical name in $FIXofs)
    vgrid_ctl = os.environ.get("VGRID_CTL") or ""
    if vgrid_ctl:
        src = ctx.fixofs / vgrid_ctl
        if _copy_if_exists(src, ctx.data / "vgrid.in"):
            staged += 1

    # ---- vgrid_nu.in (from $VGRID_NU_CTL or PREFIXNOS-prefixed fallback)
    vgrid_nu_ctl = os.environ.get("VGRID_NU_CTL") or (
        f"{prefix}.vgrid.nu.in" if prefix else ""
    )
    if vgrid_nu_ctl:
        src = ctx.fixofs / vgrid_nu_ctl
        if _copy_if_exists(src, ctx.data / "vgrid_nu.in"):
            staged += 1

    # ---- station.in (from $STA_OUT_CTL)
    sta_out_ctl = os.environ.get("STA_OUT_CTL") or ""
    if sta_out_ctl:
        src = ctx.fixofs / sta_out_ctl
        if _copy_if_exists(src, ctx.data / "station.in"):
            staged += 1

    # ---- Optional property files (PREFIXNOS-prefixed -> bare-name)
    if prefix:
        for bare in _SCHISM_PROPERTY_FILES:
            src = ctx.fixofs / f"{prefix}.{bare}"
            if _copy_if_exists(src, ctx.data / bare):
                staged += 1

    return staged


# ---------------------------------------------------------------------------
# Phase 3: hotstart.nc staging
# ---------------------------------------------------------------------------


def stage_hotstart(ctx: SchismRunContext, phase: str) -> int:
    """Stage ``$DATA/hotstart.nc`` from $COMOUT.

    Mirrors lines 628-657 of nos_run.sh.

    Source-file resolution order:

      - ``phase == "nowcast"``:
          1. ``$COMOUT/$INI_FILE_NOWCAST``
          2. ``$INI_FILE`` (absolute path; cold-start fallback)
      - ``phase == "forecast"``:
          1. ``$COMOUT/$INI_FILE_FORECAST``
          2. ``$COMOUT/$RST_OUT_NOWCAST`` (this cycle's nowcast restart)

    The shell exits via ``err_exit`` if NONE of the sources match;
    we raise :class:`FileNotFoundError` with the same diagnostic so
    the dispatcher can decide whether to fail-hard or fall back.

    Args:
        ctx: runner context. Reads ``ini_file_nowcast``,
            ``ini_file_forecast``, ``rst_out_nowcast``, ``ini_file``.
        phase: ``"nowcast"`` or ``"forecast"``.

    Returns:
        ``1`` (one file staged). Doesn't return on missing source.

    Raises:
        FileNotFoundError: if no candidate source matches. The message
            lists every source checked + the corresponding NCO env var
            (matches the shell diagnostic at lines 636-640 / 652-655).
        ValueError: if ``phase`` is not nowcast / forecast.
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

    # All sources missing -> fatal. Build a diagnostic message that
    # echoes the shell's ``Fix: stage a NETCDF4_CLASSIC hotstart...``
    # advice so operators have a copy-paste recovery path.
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


# ---------------------------------------------------------------------------
# Phase 8a: partition / tvd / fluxflag prop staging
# ---------------------------------------------------------------------------


def stage_partition_props(ctx: SchismRunContext, phase: str) -> int:
    """Stage SCHISM ``partition.prop`` / ``tvd.prop`` / ``fluxflag.prop``
    from $FIXofs.

    Mirrors lines 602-607 of nos_run.sh. Each file is staged only if
    the PREFIXNOS-prefixed source exists; missing entries are silent
    skips. ``partition.prop`` is the critical one -- when present, it
    lets SCHISM use the pre-computed mesh partition instead of calling
    ParMETIS at runtime (per the PR 230 fix that resolved the
    2794-rank heap-corruption heisenbug at line 590-601 of the shell).

    Args:
        ctx: runner context (needs ``fixofs``, ``data``, ``prefixnos``).
        phase: unused; kept for API symmetry.

    Returns:
        Number of files staged.
    """
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


# ---------------------------------------------------------------------------
# bctides.in: prep-generated tides with correct nodal factors
# ---------------------------------------------------------------------------


def stage_bctides_in(ctx: SchismRunContext, phase: str) -> int:
    """Stage ``$DATA/bctides.in`` from the prep-generated $COMOUT artifact.

    Mirrors lines 609-622 of nos_run.sh::

        if [ "$phase" = "nowcast" ]; then
            bctides_file="${BCTIDES_IN:-${PREFIXNOS}.bctides.in}.nowcast"
        else
            bctides_file="${BCTIDES_IN:-${PREFIXNOS}.bctides.in}.forecast"
        fi
        if [ -s "${COMOUT}/${bctides_file}" ]; then
            cp -p ${COMOUT}/${bctides_file} ${DATA}/bctides.in
        elif [ -s "${FIXofs}/${HC_FILE_OBC:-${PREFIXNOS}.bctides.in}" ]; then
            cp -p ${FIXofs}/${HC_FILE_OBC:-${PREFIXNOS}.bctides.in} ${DATA}/bctides.in
            echo "  WARNING: Using FIXofs bctides.in (prep-generated not found)"
        fi

    SCHISM aborts at ``read_bctides`` (early in mesh setup) if bctides.in
    is absent on a tidal-boundary grid -- the absence can surface as a
    partition_hgrid SIGSEGV when the tidal-boundary metadata feeds
    downstream partitioning state.  Staging it here closes a parity gap
    where the shell stages it and the Python path didn't.

    Args:
        ctx: runner context.
        phase: ``"nowcast"`` or ``"forecast"``.

    Returns:
        1 if a bctides.in was staged from either $COMOUT or $FIXofs;
        0 if neither source was present.
    """
    bctides_base = (
        os.environ.get("BCTIDES_IN")
        or (f"{ctx.prefixnos}.bctides.in" if ctx.prefixnos else "bctides.in")
    )
    if phase == "nowcast":
        bctides_file = f"{bctides_base}.nowcast"
    elif phase == "forecast":
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

    # Fall back to $FIXofs/$HC_FILE_OBC (or $PREFIXNOS.bctides.in).
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


# ---------------------------------------------------------------------------
# NWM FIXofs fallback for source_sink.in / vsource.th / vsink.th / msource.th
# ---------------------------------------------------------------------------

_NWM_FALLBACK_FILES: tuple = ("source_sink.in", "vsource.th", "vsink.th", "msource.th")


def fallback_nwm_files_from_fixofs(ctx: SchismRunContext, phase: str) -> int:
    """Copy NWM source/sink fallback files from $FIXofs when the tar
    extraction at :func:`forcing.untar_nwm_source_sink` left them absent.

    Mirrors lines 685-701 of nos_run.sh::

        if [ ! -s "${DATA}/source_sink.in" ]; then
            ...
            cp -p ${FIXofs}/${PREFIXNOS}.source_sink.in ${DATA}/source_sink.in
        fi
        for rivf in vsource.th vsink.th msource.th; do
            if [ ! -s "${DATA}/${rivf}" ]; then
                ...
                cp -p ${FIXofs}/${PREFIXNOS}.${rivf} ${DATA}/${rivf}
            fi
        done

    SCHISM aborts if ``if_source=1`` in param.nml and any of these
    files are missing.  The NWM tar covers the typical case; FIXofs
    fallback exists for cycles where NWM didn't produce a tar (e.g.,
    cold start, retro runs).

    Args:
        ctx: runner context.
        phase: present for API symmetry; unused (fallback set is
            phase-agnostic).

    Returns:
        Number of files staged from $FIXofs (0..4).
    """
    del phase

    if ctx.fixofs is None or not ctx.prefixnos:
        return 0

    staged = 0
    for fname in _NWM_FALLBACK_FILES:
        dst = ctx.data / fname
        if dst.is_file() and dst.stat().st_size > 0:
            continue  # tar extraction already produced this; respect it
        src = ctx.fixofs / f"{ctx.prefixnos}.{fname}"
        if _copy_if_exists(src, dst):
            logger.info("  Fallback: staged %s from FIXofs", fname)
            staged += 1
        else:
            logger.warning("WARNING: %s not found after NWM tar extraction "
                           "and no FIXofs fallback", fname)
    return staged


# ---------------------------------------------------------------------------
# SCHISM river forcing file renames (schism_*.th -> SCHISM canonical names)
# ---------------------------------------------------------------------------

# (source, dest) pairs.  Shell lines 725-728 of nos_run.sh.
_RIVER_RENAMES: tuple = (
    ("schism_temp.th", "TEM_1.th"),
    ("schism_flux.th", "flux.th"),
    ("schism_salt.th", "salt.th"),
)


def rename_river_th_files(ctx: SchismRunContext, phase: str) -> int:
    """Rename ``schism_*.th`` river forcing files to SCHISM canonical names.

    Mirrors lines 725-728 of nos_run.sh::

        [ -s "${DATA}/schism_temp.th" ] && cp -p ${DATA}/schism_temp.th ${DATA}/TEM_1.th
        [ -s "${DATA}/schism_flux.th" ] && cp -p ${DATA}/schism_flux.th ${DATA}/flux.th
        [ -s "${DATA}/schism_salt.th" ] && cp -p ${DATA}/schism_salt.th ${DATA}/salt.th

    The river forcing tar (extracted at :func:`forcing.untar_river_forcing`)
    ships ``schism_*.th`` names; SCHISM expects them under ``TEM_1.th`` /
    ``flux.th`` / ``salt.th`` based on bctides.in's river-segment refs.

    Args:
        ctx: runner context.
        phase: present for API symmetry; unused.

    Returns:
        Number of files renamed (0..3).
    """
    del phase

    renamed = 0
    for src_name, dst_name in _RIVER_RENAMES:
        src = ctx.data / src_name
        if src.is_file() and src.stat().st_size > 0:
            shutil.copy2(src, ctx.data / dst_name)
            renamed += 1
    return renamed


# ---------------------------------------------------------------------------
# sflux_inputs.txt: SCHISM probes for this even when DATM drives forcing
# ---------------------------------------------------------------------------


def stage_sflux_inputs_txt(ctx: SchismRunContext, phase: str) -> int:
    """Stage ``$DATA/sflux/sflux_inputs.txt`` from $FIXofs if present.

    Mirrors lines 730-734 of nos_run.sh::

        if [ -s "${FIXofs}/${PREFIXNOS}.sflux_inputs.txt" ]; then
            mkdir -p ${DATA}/sflux
            cp -p ${FIXofs}/${PREFIXNOS}.sflux_inputs.txt ${DATA}/sflux/sflux_inputs.txt
        fi

    DATM drives forcing for UFS-Coastal, so sflux_inputs.txt is not the
    primary data path, but SCHISM may probe for the file's existence in
    its sflux initialization.  Keeping this in parity with the shell.

    Args:
        ctx: runner context.
        phase: present for API symmetry; unused.

    Returns:
        1 if staged, 0 otherwise.
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


# ---------------------------------------------------------------------------
# hgrid.gr3 -> outputs/ copy (SCHISM probes for hgrid in outputs/ as well)
# ---------------------------------------------------------------------------


def copy_hgrid_to_outputs(ctx: SchismRunContext, phase: str) -> int:
    """Copy ``$DATA/hgrid.gr3`` to ``$DATA/outputs/hgrid.gr3``.

    Mirrors line 738 of nos_run.sh::

        mkdir -p ${DATA}/outputs
        [ -s "${DATA}/hgrid.gr3" ] && cp -p ${DATA}/hgrid.gr3 ${DATA}/outputs/

    Some SCHISM post-processing utilities (combine_output11, etc.) look
    for hgrid.gr3 in outputs/ rather than the run root.  The shell stages
    it unconditionally before mpiexec.

    Args:
        ctx: runner context.
        phase: present for API symmetry; unused.

    Returns:
        1 if the copy was made, 0 otherwise.
    """
    del phase

    outputs_dir = _data_subdir(ctx, "outputs")
    src = ctx.data / "hgrid.gr3"
    if not src.is_file() or src.stat().st_size == 0:
        return 0
    shutil.copy2(src, outputs_dir / "hgrid.gr3")
    return 1


# ---------------------------------------------------------------------------
# Phase 8b: forecast-only previous-cycle restart_outputs staging
# ---------------------------------------------------------------------------

# The shell touches mirror.out / flux.out and staout_1..9 unconditionally
# at the end of the forecast branch (lines 758-763) so SCHISM's
# open(status='old') calls don't trip. The set is exported for tests.
_FORECAST_REQUIRED_OUTPUTS: tuple = ("mirror.out", "flux.out") + tuple(
    f"staout_{i}" for i in range(1, 10)
)


def stage_forecast_restart_outputs(ctx: SchismRunContext, phase: str) -> int:
    """Stage the previous-cycle ``restart_outputs/`` artifacts for a
    forecast run.

    Mirrors lines 744-764 of nos_run.sh. Only does work when
    ``phase == "forecast"`` -- otherwise it's a no-op (returns 0).

    Behavior:

      1. Source: ``$COMOUT/$RUN.$cycle.restart_outputs/``.
      2. Destination: ``$DATA/outputs/``.
      3. For each of ``mirror.out``, ``flux.out``, ``staout_1`` ..
         ``staout_9``: if present in the source, ``cp -p`` to the
         destination. Missing sources are warned about (the shell
         echoes "WARNING: restart_outputs not found" when the parent
         dir is absent).
      4. After copying, ``touch`` any of the canonical output names
         that don't yet exist in ``$DATA/outputs/`` so that SCHISM's
         ``open(status='old')`` calls always find a file (matches
         lines 758-763).

    Args:
        ctx: runner context (needs ``data``, ``comout``, ``run``,
            ``cycle``).
        phase: ``"forecast"`` (no-op otherwise).

    Returns:
        Number of files copied from the source dir (does NOT count the
        empty placeholders created by ``touch``).
    """
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

    # Touch any missing canonical outputs so SCHISM's open(status='old')
    # doesn't choke. The shell uses ``[ ! -f ... ] && touch ...`` at
    # lines 758-763; we use ``Path.touch(exist_ok=True)`` for the same
    # effect (creates if absent; updates mtime only -- no truncation).
    for f in _FORECAST_REQUIRED_OUTPUTS:
        (outputs_dir / f).touch(exist_ok=True)

    return staged


# ---------------------------------------------------------------------------
# Phase orchestrator (PR 7b -- composes phases 1-8 in shell order)
# ---------------------------------------------------------------------------


def run_python(ctx: SchismRunContext, phase: str) -> int:
    """Compose all phases of ``_schism_stage_files`` in shell order.

    Wires together:

      - PR 7a's static-staging helpers (this module: phases 1, 2, 3, 8).
      - PR 7b's forcing-tar extractors (:mod:`forcing`: phases 4, 5, 6).
      - PR 7b's namelist patchers (:mod:`configure`: phase 7).
      - PR 4's ESMF mesh regeneration (:mod:`mesh`) -- folded in at the
        end because the param.nml + datm_in patches need to be in
        place before the mesh is rebuilt from the actual forcing file.

    The order matches the shell function in ``ush/nos_run.sh`` so a side-
    by-side diff is straightforward to audit:

      1. ``stage_ufs_configs``                  -- shell lines 452-490
      2. ``configure.patch_param_nml``          -- shell lines 538-551
         ``configure.patch_datm_in``            -- shell lines 555-565
         ``configure.patch_model_configure``    -- shell lines 516-522
         ``configure.patch_ufs_configure``      -- shell lines 523-528
      3. ``stage_schism_bare_names``            -- shell lines 571-586
      4. ``stage_partition_props``              -- shell lines 602-607
      5. ``stage_hotstart``                     -- shell lines 628-657
      6. ``forcing.untar_nwm_source_sink``      -- shell lines 670-683
      7. ``forcing.untar_obc_forcing``          -- shell lines 703-712
      8. ``forcing.untar_river_forcing``        -- shell lines 715-723
      9. ``stage_forecast_restart_outputs``     -- shell lines 744-764
     10. ESMF mesh regen                         -- shell mesh.py call

    Args:
        ctx: runner context.
        phase: ``"nowcast"`` or ``"forecast"``.

    Returns:
        0 on success.  Per-phase failures are logged but not propagated
        because the shell behaves similarly (only stage_hotstart raises
        on missing source; the rest log + continue).

    Note: PR 7b ships this function but does NOT wire it into the
    dispatcher.  The runner flag flip + stage-script call live in
    PR 7c.  We surface ``run_python`` here so PR 7c is a small diff:
    just replace the shell call with ``stage_files.run_python(ctx, phase)``.
    """
    # Imports are local so circular-import risk is avoided when
    # ``stage_files`` is imported from ``forcing`` or ``configure``
    # (currently neither does, but defending against future churn).
    from . import configure, forcing, mesh

    # Phase 1: static UFS-Coastal configs + DATM input directory.
    stage_ufs_configs(ctx, phase)

    # Bare-name rename for param.nml: SCHISM's NUOPC cap inquires for
    # the file literally named "param.nml" at schism_nuopc_cap.F90:316
    # and aborts if it's missing. setup_paths stages the prefixed file
    # ($DATA/${PREFIXNOS}.param.nml) via _stage_fix_files. The shell's
    # _schism_stage_files does the bare-name copy at nos_run.sh lines
    # 530-535; mirror that here BEFORE patch_param_nml runs (otherwise
    # patch_param_nml silently no-ops and SCHISM dies looking for
    # $DATA/param.nml at runtime).
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

    # Phase 7 (out of shell order, BUT before bare-name copies):
    # The shell does patches AFTER ufs-config staging but BEFORE the
    # SCHISM bare-name + forcing extraction.  Matches lines 491-565.
    configure.patch_model_configure(ctx, phase)
    configure.patch_ufs_configure(ctx, phase)
    configure.patch_param_nml(ctx, phase)
    configure.patch_datm_in(ctx, phase)

    # Phase 2: SCHISM bare-name files (hgrid.gr3, vgrid.in, etc.)
    stage_schism_bare_names(ctx, phase)

    # Phase 8a: SCHISM partition / tvd / fluxflag.
    stage_partition_props(ctx, phase)

    # bctides.in from prep ($COMOUT) -- shell lines 609-622.  Must be
    # staged BEFORE the hotstart so SCHISM finds tides metadata on the
    # same boundary segments referenced by the hotstart.
    stage_bctides_in(ctx, phase)

    # Phase 3: hotstart.nc (FATAL if missing -- raises FileNotFoundError).
    stage_hotstart(ctx, phase)

    # Phase 5 first (shell ordering): NWM source/sink tar (lines 670-683).
    # The OBC + river tars at lines 703-723 run AFTER this; we mirror.
    forcing.untar_nwm_source_sink(ctx, phase)

    # FIXofs fallback for any NWM payload the tar didn't supply --
    # shell lines 685-701.  SCHISM aborts if if_source=1 and these are
    # missing, so this guard is load-bearing for the typical config.
    fallback_nwm_files_from_fixofs(ctx, phase)

    # Phase 4 + 6: OBC + river tars (lines 703-723).
    forcing.untar_obc_forcing(ctx, phase)
    forcing.untar_river_forcing(ctx, phase)

    # SCHISM canonical river-forcing names (shell lines 725-728).
    rename_river_th_files(ctx, phase)

    # sflux_inputs.txt probe target (shell lines 730-734).
    stage_sflux_inputs_txt(ctx, phase)

    # hgrid.gr3 -> outputs/ (shell line 738).
    copy_hgrid_to_outputs(ctx, phase)

    # Phase 8b: forecast-only previous-cycle restart_outputs staging.
    stage_forecast_restart_outputs(ctx, phase)

    # PR 4 follow-up: ESMF mesh regen from the actual DATM forcing file.
    # The mesh path depends on $DATM_INPUT_DIR which defaults to INPUT.
    # Shell counterpart: lines 855-912 (pre-PR-4 inline Python heredoc).
    datm_dir_name = os.environ.get("DATM_INPUT_DIR") or "INPUT"
    forcing_file = ctx.data / datm_dir_name / "datm_forcing.nc"
    esmf_mesh_out = ctx.data / datm_dir_name / "datm_esmf_mesh.nc"
    if forcing_file.is_file() and forcing_file.stat().st_size > 0:
        try:
            mesh.generate_esmf_mesh(forcing_file, esmf_mesh_out)
        except Exception as exc:  # pragma: no cover -- mesh handles its own
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
