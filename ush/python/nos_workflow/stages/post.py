"""Post stage entry point.

Both ``framework="comf"`` (SECOFS-UFS) and ``framework="stofs_ufs"``
(STOFS-3D-ATL-UFS) route through the UFS-Coastal implementation,
mirroring the pre-migration ``scripts/exnos_post.sh``.
The COMF body:

  1. For each of ``nowcast`` and ``forecast``, build a working dir
     under ``$DATA``, write a one-line-per-key ``.ctl`` control file,
     emit ``${PREFIXNOS}.station.lat.lon`` from the legacy
     ``${PREFIXNOS}.station.in`` (an awk-style header skip), symlink
     the ``staout_{1..9}`` text outputs in, and shell out to
     ``schism_combine_outputs.py`` (a deployed runtime script under
     ``${HOMEnos}/ush/nosofs/``). The script writes a CO-OPS standard
     station NetCDF that we then copy into ``$COMOUT``.

  2. If ``BAROTROPIC=true`` and the ensemble outputs are present, run
     ``ensemble_bias_correct.py`` once with ``train`` to fit anomaly
     coefficients against the 3D deterministic reference, then once
     per member with ``apply`` to write a corrected WL CSV beside that
     member's outputs.

Why ``schism_combine_outputs.py`` and ``ensemble_bias_correct.py``
stay as ``subprocess.run`` instead of being imported as modules:

  - Neither script lives in this repository — both are deployed under
    ``${HOMEnos}/ush/...`` at install time, so we cannot import them at
    package collection time without an ImportError.
  - Even at runtime, both have CLI-style ``argparse`` + ``sys.argv``
    glue at module top level (the known anti-pattern in the old
    ``feature/python-prep`` codebase). Importing them would execute that
    glue at import time. The migration philosophy doc (#220) explicitly
    flags this case for ``subprocess.run``.

The standalone STOFS and ADCIRC branches raise ``NotImplementedError``
until tasks #33 / #34 land.
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

from .._log import emit_stage_summary, stage_logger
from ..errors import StageFailedError
from ..registry import OFSDescriptor

if TYPE_CHECKING:
    # Forward-reference NCOEnv so the stage module doesn't import the
    # env module at collection time. The runtime parameter type is
    # structural.
    from ..env import NCOEnv  # noqa: F401


logger = logging.getLogger(__name__)


_STAGE = "post"

# Indices of the staout text files that schism_combine_outputs.py
# expects to find symlinked into its working directory.
_STAOUT_INDICES = tuple(range(1, 10))  # staout_1 .. staout_9


def run(descriptor: OFSDescriptor, env: "NCOEnv") -> int:
    """Execute the post stage for ``descriptor``.

    Args:
        descriptor: The OFS descriptor returned by ``registry.lookup``.
        env: NCO environment bundle (PDY, cyc, COM paths, etc.).

    Returns:
        0 on success; a non-zero return code is surfaced from the COMF
        post body if a fatal step (missing combine script, missing
        station.in) fires.

    Raises:
        StageFailedError: any unexpected exception during the COMF body,
            or an unknown framework.
        NotImplementedError: framework="stofs" (standalone STOFS-3D-ATL)
            or "adcirc" — stubs for tasks #33/#34.
    """
    sl = stage_logger(_STAGE, descriptor.name)
    sl.info("stage start")

    if descriptor.framework in ("comf", "stofs_ufs"):
        t_stage = time.monotonic()
        rc = _run_comf_post(descriptor, env)
        emit_stage_summary(
            sl, status="PASS" if rc == 0 else "FAIL",
            runtime_s=time.monotonic() - t_stage,
            extras={"rc": rc},
        )
        return rc
    if descriptor.framework == "stofs":
        raise NotImplementedError(
            "STOFS-3D-ATL post not yet ported — task #33 on the roadmap "
            "(two-phase post_1/post_2 needs its own migration)"
        )
    if descriptor.framework == "adcirc":
        raise NotImplementedError(
            "STOFS-2D-GLO post not yet ported — task #34"
        )

    raise StageFailedError(
        stage=_STAGE,
        ofs=descriptor.name,
        returncode=2,
        msg=f"unknown framework {descriptor.framework!r}",
    )


# ---------------------------------------------------------------------------
# COMF post body
# ---------------------------------------------------------------------------


def _run_comf_post(descriptor: OFSDescriptor, env: "NCOEnv") -> int:
    """COMF (SECOFS-UFS) post: combine staout to station NetCDF, then
    optionally bias-correct ensemble members.

    This wraps the shell logic in ``exnos_post.sh.preY-mig`` end-to-end.
    Any unexpected exception is caught and re-raised as
    ``StageFailedError`` so the CLI's top-level handler prints a clean
    one-line FATAL instead of dumping a traceback to ``OUTPUT.$$``.
    """
    try:
        return _comf_post_body(descriptor, env)
    except StageFailedError:
        raise
    except Exception as exc:  # noqa: BLE001 — wrap to StageFailedError
        raise StageFailedError(
            stage=_STAGE,
            ofs=descriptor.name,
            returncode=1,
            msg=f"unexpected exception in COMF post: {exc}",
        ) from exc


def _comf_post_body(descriptor: OFSDescriptor, env: "NCOEnv") -> int:
    sl = stage_logger(_STAGE, descriptor.name)
    """The actual COMF post work; raises ``StageFailedError`` on fatal
    failures, returns 0 on success (warnings are non-fatal).
    """
    # All these env vars come from nos_run.sh or the J-job. We deliberately
    # don't try to derive them from the YAML — keeping the contract
    # identical to what the legacy shell expected.
    shell_env = os.environ
    homenos = Path(_require_env(shell_env, "HOMEnos"))
    fixofs = Path(_require_env(shell_env, "FIXofs"))
    comout = Path(_require_env(shell_env, "COMOUT"))
    data = Path(_require_env(shell_env, "DATA"))
    pdy = _require_env(shell_env, "PDY")
    cyc = _require_env(shell_env, "cyc")
    cycle = shell_env.get("cycle") or f"t{cyc}z"
    run_name = _require_env(shell_env, "RUN")
    prefix_nos = _require_env(shell_env, "PREFIXNOS")
    pgmout = shell_env.get("pgmout", "OUTPUT.$$")

    sl.info("phase=POST pdy=%s cyc=%s comout=%s", pdy, cyc, comout)

    # Search for schism_combine_outputs.py. The legacy nosofs.v3.7.0 deploy
    # put it at $HOMEnos/ush/nosofs/. The refactored nos-workflow tree
    # consolidated $HOMEnos/ush/nosofs/ → $HOMEnos/ush/, so the file can
    # also live there. Operators can override via $NOS_COMBINE_OUTPUTS_SCRIPT.
    combine_script = _resolve_combine_script(homenos, shell_env)
    if combine_script is None:
        searched = [
            shell_env.get("NOS_COMBINE_OUTPUTS_SCRIPT", "<NOS_COMBINE_OUTPUTS_SCRIPT unset>"),
            str(homenos / "ush" / "nosofs" / "schism_combine_outputs.py"),
            str(homenos / "ush" / "schism_combine_outputs.py"),
            str(homenos / "ush" / "python" / "schism_combine_outputs.py"),
        ]
        raise StageFailedError(
            stage=_STAGE,
            ofs=descriptor.name,
            returncode=1,
            msg=(
                "schism_combine_outputs.py not found. Searched: "
                + ", ".join(searched)
                + ". Fix: set NOS_COMBINE_OUTPUTS_SCRIPT=<abs-path-to-script>, "
                "or copy/symlink the script into one of the searched paths."
            ),
        )

    sta_in = _resolve_station_in(fixofs, prefix_nos, shell_env)
    if sta_in is None:
        raise StageFailedError(
            stage=_STAGE,
            ofs=descriptor.name,
            returncode=1,
            msg=f"station.in not found under {fixofs} (looked for "
                f"{prefix_nos}.station.in and ${{STA_OUT_CTL}})",
        )

    nc_hour = _nowcast_base_hour(cyc, shell_env.get("LEN_NOWCAST"))

    # -- Per-phase combine --------------------------------------------------
    for phase in ("nowcast", "forecast"):
        _process_phase(
            phase=phase,
            data=data,
            comout=comout,
            run_name=run_name,
            cycle=cycle,
            pdy=pdy,
            cyc=cyc,
            nc_hour=nc_hour,
            prefix_nos=prefix_nos,
            sta_in=sta_in,
            combine_script=combine_script,
            pgmout=pgmout,
        )

    # -- Optional ensemble bias correction ---------------------------------
    if _is_barotropic(shell_env):
        _maybe_bias_correct(
            descriptor=descriptor,
            shell_env=shell_env,
            homenos=homenos,
            comout=comout,
            run_name=run_name,
            cycle=cycle,
            pdy=pdy,
            cyc=cyc,
            nc_hour=nc_hour,
            sta_in=sta_in,
            pgmout=pgmout,
        )

    sl.info("post-processing completed")
    return 0


# ---------------------------------------------------------------------------
# Phase processing — mirrors the for-phase loop in the .preY-mig shell.
# ---------------------------------------------------------------------------


def _process_phase(
    *,
    phase: str,
    data: Path,
    comout: Path,
    run_name: str,
    cycle: str,
    pdy: str,
    cyc: str,
    nc_hour: str,
    prefix_nos: str,
    sta_in: Path,
    combine_script: Path,
    pgmout: str,
) -> None:
    """Build the working dir for ``phase`` and run the combine script.

    Mirrors the inner body of the ``for phase in nowcast forecast`` loop
    in ``exnos_post.sh.preY-mig`` lines 57-120.

    Warnings (missing staout dir, combine-script non-zero, missing
    expected NetCDF) are logged and skipped — they were ``continue`` in
    the shell and we preserve that semantic so a missing forecast
    doesn't block a successful nowcast emit.
    """
    logger.info("")
    logger.info("--- Processing %s ---", phase)

    if phase == "nowcast":
        staout_dir = comout / f"{run_name}.{cycle}.restart_outputs"
        mode_flag = "n"
        timestart = f"{pdy}{nc_hour}"
    else:
        staout_dir = comout / f"{run_name}.{cycle}.forecast_outputs"
        mode_flag = "f"
        timestart = f"{pdy}{cyc}"

    staout_1 = staout_dir / "staout_1"
    if not staout_1.is_file():
        logger.warning(
            "WARNING: %s not found, skipping %s", staout_1, phase
        )
        return

    work_post = data / f"post_{phase}"
    work_post.mkdir(parents=True, exist_ok=True)

    # Write the control file the combine script reads.
    ctl_path = work_post / "schism_standard_output.ctl"
    ctl_path.write_text(
        f"{prefix_nos}\n{cyc}\n{pdy}\n{mode_flag}\n{timestart}\n"
    )

    # Build station.lat.lon: skip first 2 header lines, take cols 2,3.
    # Equivalent to: awk 'NR>2 && NF>=3 {print NR-2, $2, $3}'.
    sta_latlon = work_post / f"{prefix_nos}.station.lat.lon"
    _write_station_latlon(sta_in, sta_latlon)

    # Symlink staout files (force overwrite).
    for n in _STAOUT_INDICES:
        src = staout_dir / f"staout_{n}"
        if src.is_file():
            dst = work_post / f"staout_{n}"
            if dst.exists() or dst.is_symlink():
                dst.unlink()
            dst.symlink_to(src)

    # Run combine script in the working dir. LD_PRELOAD is scrubbed so
    # netCDF4/numpy don't segfault if the J-job preloaded libnetcdff.so
    # for upstream Fortran (memory lesson #6).
    logger.info("Running schism_combine_outputs.py for %s ...", phase)
    rc = _run_subprocess_appending(
        [
            "python3",
            str(combine_script),
        ],
        cwd=work_post,
        log_path=pgmout,
        scrub_ld_preload=True,
    )

    if rc != 0:
        logger.warning(
            "WARNING: schism_combine_outputs.py failed for %s (rc=%d)",
            phase, rc,
        )
        return

    # Copy the resulting station NetCDF into COMOUT.
    sta_nc = work_post / f"{prefix_nos}.t{cyc}z.{pdy}.stations.{phase}.nc"
    if sta_nc.is_file():
        target = comout / sta_nc.name
        _copy_preserve(sta_nc, target)
        logger.info("Created: %s", sta_nc.name)
    else:
        logger.warning(
            "WARNING: Expected station NetCDF not found: %s", sta_nc
        )


# ---------------------------------------------------------------------------
# Optional ensemble bias correction
# ---------------------------------------------------------------------------


def _maybe_bias_correct(
    *,
    descriptor: OFSDescriptor,
    shell_env: os._Environ,
    homenos: Path,
    comout: Path,
    run_name: str,
    cycle: str,
    pdy: str,
    cyc: str,
    nc_hour: str,
    sta_in: Path,
    pgmout: str,
) -> None:
    """Mirrors the ``if BAROTROPIC=true`` block in the legacy shell
    (lines 135-239).

    All failures here are non-fatal: the original shell only logs
    warnings and continues. We preserve that — bias correction is an
    optional polish step on top of the always-required station NetCDFs.
    """
    bias_script = (
        homenos / "ush" / "python" / "nos_ofs" / "ensemble"
        / "ensemble_bias_correct.py"
    )

    # Derive the 3D deterministic OFS name from the 2D barotropic name.
    # Defaults reproduce the sed pipeline:
    #   secofs_2d_ufs → secofs   (drop _2d_ufs)
    #   stofs_2d_atl  → stofs_3d_atl  (replace _2d_ with _3d_)
    ofs = descriptor.name
    det_ofs = shell_env.get("DET_OFS") or _derive_det_ofs(ofs)
    det_comout_env = shell_env.get("DET_COMOUT")
    if det_comout_env:
        det_comout = Path(det_comout_env)
    else:
        det_comout = comout.parent / f"{det_ofs}.{pdy}"

    det_ncast = det_comout / f"{det_ofs}.t{cyc}z.{pdy}.stations.nowcast.nc"
    det_fcast = det_comout / f"{det_ofs}.t{cyc}z.{pdy}.stations.forecast.nc"

    ens_dir = comout / "ensemble" / cycle
    ctl_ncast = (
        ens_dir / "member_000" / f"{run_name}.{cycle}.restart_outputs"
        / "staout_1"
    )
    ctl_fcast = (
        ens_dir / "member_000" / f"{run_name}.{cycle}.forecast_outputs"
        / "staout_1"
    )

    # Fall back to deterministic (non-ensemble) staout when no member_000.
    if not ctl_ncast.is_file():
        ctl_ncast = comout / f"{run_name}.{cycle}.restart_outputs" / "staout_1"
    if not ctl_fcast.is_file():
        ctl_fcast = comout / f"{run_name}.{cycle}.forecast_outputs" / "staout_1"

    missing = _missing_bias_inputs(
        bias_script=bias_script,
        det_ncast=det_ncast,
        det_fcast=det_fcast,
        ctl_ncast=ctl_ncast,
        ctl_fcast=ctl_fcast,
    )
    if missing:
        logger.info("")
        logger.info("Skipping ensemble bias correction (missing inputs):")
        for line in missing:
            logger.info("  - %s", line)
        return

    logger.info("")
    logger.info("=============================================")
    logger.info("Ensemble bias correction (2D -> 3D anchored)")
    logger.info("  3D det: %s", det_ofs)
    logger.info("  Control: member_000")
    logger.info("=============================================")

    coeff_file = comout / "bias_coefficients.json"

    # Step 1: train coefficients (control vs 3D det)
    logger.info("Training bias correction coefficients ...")
    train_rc = _run_subprocess_appending(
        [
            "python3", str(bias_script), "train",
            "--ctl-ncast", str(ctl_ncast),
            "--ctl-fcast", str(ctl_fcast),
            "--det-ncast", str(det_ncast),
            "--det-fcast", str(det_fcast),
            "--station-in", str(sta_in),
            "--nc-base", f"{pdy}{nc_hour}",
            "--fc-base", f"{pdy}{cyc}",
            "-o", str(coeff_file),
        ],
        cwd=None,
        log_path=pgmout,
        scrub_ld_preload=True,
    )

    if train_rc != 0 or not coeff_file.is_file():
        logger.warning(
            "WARNING: Bias correction training failed (rc=%d), skipping",
            train_rc,
        )
        return

    logger.info("Coefficients saved: %s", coeff_file)

    # Step 2: apply to each perturbed member (member_000 is the control,
    # anomaly is zero by construction, so skip it).
    for member_dir in sorted(ens_dir.glob("member_*")):
        if not member_dir.is_dir():
            continue
        # str.removeprefix is 3.9+; keep 3.8 compat manually.
        name = member_dir.name
        member_id = name[len("member_"):] if name.startswith("member_") else name
        if member_id == "000":
            continue

        mem_ncast = (
            member_dir / f"{run_name}.{cycle}.restart_outputs" / "staout_1"
        )
        mem_fcast = (
            member_dir / f"{run_name}.{cycle}.forecast_outputs" / "staout_1"
        )
        # Flat-layout fallback.
        if not mem_ncast.is_file():
            mem_ncast = member_dir / "staout_1_nowcast"
        if not mem_fcast.is_file():
            mem_fcast = member_dir / "staout_1_forecast"

        if not mem_ncast.is_file() or not mem_fcast.is_file():
            logger.info(
                "  Member %s: staout files not found, skipping",
                member_id,
            )
            continue

        corr_out = member_dir / "corrected_wl.csv"
        logger.info("  Correcting member %s ...", member_id)
        apply_rc = _run_subprocess_appending(
            [
                "python3", str(bias_script), "apply",
                "--coefficients", str(coeff_file),
                "--det-ncast", str(det_ncast),
                "--det-fcast", str(det_fcast),
                "--ctl-ncast", str(ctl_ncast),
                "--ctl-fcast", str(ctl_fcast),
                "--member-ncast", str(mem_ncast),
                "--member-fcast", str(mem_fcast),
                "--station-in", str(sta_in),
                "--nc-base", f"{pdy}{nc_hour}",
                "--fc-base", f"{pdy}{cyc}",
                "-o", str(corr_out),
            ],
            cwd=None,
            log_path=pgmout,
            scrub_ld_preload=True,
        )

        if apply_rc == 0 and corr_out.is_file():
            logger.info(
                "  Member %s: corrected -> %s", member_id, corr_out.name
            )
        else:
            logger.info("  Member %s: correction failed", member_id)


def _missing_bias_inputs(
    *,
    bias_script: Path,
    det_ncast: Path,
    det_fcast: Path,
    ctl_ncast: Path,
    ctl_fcast: Path,
) -> List[str]:
    """Return human-readable lines for whichever bias-corr inputs are
    missing, preserving the legacy shell's diagnostic order."""
    out: List[str] = []
    if not bias_script.is_file():
        out.append("bias correction script not found")
    if not det_ncast.is_file():
        out.append(f"3D det nowcast not found: {det_ncast}")
    if not det_fcast.is_file():
        out.append(f"3D det forecast not found: {det_fcast}")
    if not ctl_ncast.is_file():
        out.append(f"2D control nowcast not found: {ctl_ncast}")
    if not ctl_fcast.is_file():
        out.append(f"2D control forecast not found: {ctl_fcast}")
    return out


# ---------------------------------------------------------------------------
# Small helpers (kept local so the post stage stays self-contained).
# ---------------------------------------------------------------------------


def _resolve_combine_script(
    homenos: Path, env: "os._Environ"
) -> Optional[Path]:
    """Locate schism_combine_outputs.py across legacy + refactored deploy paths.

    Lookup order (first existing file wins):
      1. ``$NOS_COMBINE_OUTPUTS_SCRIPT`` (explicit operator override)
      2. ``$HOMEnos/ush/nosofs/schism_combine_outputs.py`` (legacy nosofs.v3.7.0)
      3. ``$HOMEnos/ush/schism_combine_outputs.py`` (refactored consolidated ush/)
      4. ``$HOMEnos/ush/python/schism_combine_outputs.py`` (pysh-style location)

    Returns ``None`` if no candidate exists, leaving the caller to raise
    a StageFailedError with the full searched-path list for ops debugging.
    """
    override = env.get("NOS_COMBINE_OUTPUTS_SCRIPT")
    if override:
        p = Path(override)
        if p.is_file():
            return p
    for candidate in (
        homenos / "ush" / "nosofs" / "schism_combine_outputs.py",
        homenos / "ush" / "schism_combine_outputs.py",
        homenos / "ush" / "python" / "schism_combine_outputs.py",
    ):
        if candidate.is_file():
            return candidate
    return None


def _require_env(env: "os._Environ", key: str) -> str:
    """Mirror ``env._require`` for plain ``os.environ``; raise
    ``StageFailedError`` with a useful message if unset/empty."""
    val = env.get(key)
    if val is None or val == "":
        raise StageFailedError(
            stage=_STAGE,
            ofs=env.get("OFS", "<unknown>"),
            returncode=1,
            msg=f"required NCO env var {key!r} not set",
        )
    return val


def _resolve_station_in(
    fixofs: Path, prefix_nos: str, env: "os._Environ"
) -> Optional[Path]:
    """Pick the station.in file, with the same two-step fallback the
    legacy shell used: ``{PREFIXNOS}.station.in`` first, then
    ``${STA_OUT_CTL:-…}``.
    """
    primary = fixofs / f"{prefix_nos}.station.in"
    if primary.is_file():
        return primary
    sta_ctl = env.get("STA_OUT_CTL") or f"{prefix_nos}.station.in"
    fallback = fixofs / sta_ctl
    if fallback.is_file():
        return fallback
    return None


def _nowcast_base_hour(cyc: str, len_nowcast: Optional[str]) -> str:
    """Compute the nowcast base hour, mirroring the shell:

        NC_HOUR = (cyc - LEN_NOWCAST) mod 24, zero-padded to two digits

    Defaults LEN_NOWCAST to 6 (matches the shell's ``${LEN_NOWCAST:-6}``).
    The legacy shell wraps negatives by adding 24 but does NOT roll the
    PDY back — we preserve that exact behavior.
    """
    try:
        cyc_int = int(cyc)
    except (TypeError, ValueError):
        cyc_int = 0
    try:
        len_nc = int(len_nowcast) if len_nowcast not in (None, "") else 6
    except (TypeError, ValueError):
        len_nc = 6
    nc = cyc_int - len_nc
    if nc < 0:
        nc += 24
    return f"{nc:02d}"


def _write_station_latlon(sta_in: Path, sta_latlon: Path) -> None:
    """Emit ``station.lat.lon`` from a SCHISM-style ``station.in``.

    Equivalent to the awk one-liner in the legacy shell:
        awk 'NR>2 && NF>=3 {print NR-2, $2, $3}' "$STA_IN"

    NR>2 skips the two header lines; NF>=3 filters blank/short rows;
    NR-2 reindexes the row counter so the first emitted row is 1.
    """
    out_lines: List[str] = []
    line_no = 0
    with sta_in.open("r") as fh:
        for raw in fh:
            line_no += 1
            if line_no <= 2:
                continue
            fields = raw.split()
            if len(fields) < 3:
                continue
            out_lines.append(f"{line_no - 2} {fields[1]} {fields[2]}")
    sta_latlon.write_text("\n".join(out_lines) + ("\n" if out_lines else ""))


def _copy_preserve(src: Path, dst: Path) -> None:
    """Mirror ``cp -p src dst`` (preserve mtime, mode)."""
    import shutil

    shutil.copy2(src, dst)


def _is_barotropic(env: "os._Environ") -> bool:
    """Return True for any of ``BAROTROPIC=true|1|TRUE`` (legacy
    semantic).  Anything else (or unset) is False.
    """
    raw = env.get("BAROTROPIC", "")
    return raw.lower() in ("true", "1")


def _derive_det_ofs(ofs: str) -> str:
    """Map a 2D OFS name to its 3D deterministic counterpart.

    Reproduces the shell's two-step sed:
        secofs_2d_ufs -> secofs        (drop ``_2d_ufs``)
        stofs_2d_atl  -> stofs_3d_atl  (replace ``_2d_`` with ``_3d_``)

    Anything else passes through unchanged.
    """
    if "_2d_ufs" in ofs:
        return ofs.replace("_2d_ufs", "")
    if "_2d_" in ofs:
        return ofs.replace("_2d_", "_3d_")
    return ofs


def _run_subprocess_appending(
    cmd: List[str],
    *,
    cwd: Optional[Path],
    log_path: str,
    scrub_ld_preload: bool,
) -> int:
    """Run ``cmd``, appending merged stdout/stderr to ``log_path``.

    Mirrors the shell's ``>> $pgmout 2>&1`` redirection. If ``log_path``
    can't be opened (e.g. running under a smoke test without ``$pgmout``
    pointing at a writable file), we fall back to the parent process's
    stdout/stderr — same outcome the operator sees on the console.

    ``scrub_ld_preload=True`` removes ``LD_PRELOAD`` from the child env;
    needed for any Python child that imports netCDF4 / numpy when the
    J-job preloaded ``libnetcdff.so`` for upstream Fortran (lesson #6).
    """
    child_env = os.environ.copy()
    if scrub_ld_preload and "LD_PRELOAD" in child_env:
        del child_env["LD_PRELOAD"]

    log_fh = None
    try:
        try:
            log_fh = open(log_path, "a")
        except OSError:
            log_fh = None

        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd is not None else None,
            env=child_env,
            stdout=log_fh if log_fh is not None else None,
            stderr=subprocess.STDOUT if log_fh is not None else None,
            check=False,
        )
        return proc.returncode
    finally:
        if log_fh is not None:
            log_fh.close()


__all__ = ["run"]
