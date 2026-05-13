"""Post stage entry point."""
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
    from ..env import NCOEnv  # noqa: F401


logger = logging.getLogger(__name__)


_STAGE = "post"

_STAOUT_INDICES = tuple(range(1, 10))


def run(descriptor: OFSDescriptor, env: "NCOEnv") -> int:
    """Execute the post stage for ``descriptor``."""
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
        raise NotImplementedError("STOFS-3D-ATL post not yet ported")
    if descriptor.framework == "adcirc":
        raise NotImplementedError("STOFS-2D-GLO post not yet ported")

    raise StageFailedError(
        stage=_STAGE,
        ofs=descriptor.name,
        returncode=2,
        msg=f"unknown framework {descriptor.framework!r}",
    )


def _run_comf_post(descriptor: OFSDescriptor, env: "NCOEnv") -> int:
    """SCHISM-UFS (framework=comf|stofs_ufs) post: combine staout, then optionally bias-correct."""
    try:
        return _comf_post_body(descriptor, env)
    except StageFailedError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise StageFailedError(
            stage=_STAGE,
            ofs=descriptor.name,
            returncode=1,
            msg=f"unexpected exception in COMF post: {exc}",
        ) from exc


def _comf_post_body(descriptor: OFSDescriptor, env: "NCOEnv") -> int:
    """Run COMF post-processing; raise on fatal failures, return 0 on success."""
    sl = stage_logger(_STAGE, descriptor.name)
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
    """Build the working dir for ``phase`` and run the combine script."""
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

    ctl_path = work_post / "schism_standard_output.ctl"
    ctl_path.write_text(
        f"{prefix_nos}\n{cyc}\n{pdy}\n{mode_flag}\n{timestart}\n"
    )

    sta_latlon = work_post / f"{prefix_nos}.station.lat.lon"
    _write_station_latlon(sta_in, sta_latlon)

    for n in _STAOUT_INDICES:
        src = staout_dir / f"staout_{n}"
        if src.is_file():
            dst = work_post / f"staout_{n}"
            if dst.exists() or dst.is_symlink():
                dst.unlink()
            dst.symlink_to(src)

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

    sta_nc = work_post / f"{prefix_nos}.t{cyc}z.{pdy}.stations.{phase}.nc"
    if sta_nc.is_file():
        target = comout / sta_nc.name
        _copy_preserve(sta_nc, target)
        logger.info("Created: %s", sta_nc.name)
    else:
        logger.warning(
            "WARNING: Expected station NetCDF not found: %s", sta_nc
        )


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
    """Optional ensemble bias correction. All failures here are non-fatal."""
    bias_script = (
        homenos / "ush" / "python" / "nos_ofs" / "ensemble"
        / "ensemble_bias_correct.py"
    )

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

    for member_dir in sorted(ens_dir.glob("member_*")):
        if not member_dir.is_dir():
            continue
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
    """Return human-readable lines for any missing bias-corr inputs."""
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


def _resolve_combine_script(
    homenos: Path, env: "os._Environ"
) -> Optional[Path]:
    """Locate schism_combine_outputs.py."""
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
    """Return ``env[key]`` or raise ``StageFailedError`` if unset/empty."""
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
    """Pick the station.in file with the two-step fallback."""
    primary = fixofs / f"{prefix_nos}.station.in"
    if primary.is_file():
        return primary
    sta_ctl = env.get("STA_OUT_CTL") or f"{prefix_nos}.station.in"
    fallback = fixofs / sta_ctl
    if fallback.is_file():
        return fallback
    return None


def _nowcast_base_hour(cyc: str, len_nowcast: Optional[str]) -> str:
    """Compute the nowcast base hour: (cyc - LEN_NOWCAST) mod 24."""
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
    """Emit ``station.lat.lon`` from a SCHISM-style ``station.in``."""
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
    """Mirror ``cp -p src dst``."""
    import shutil

    shutil.copy2(src, dst)


def _is_barotropic(env: "os._Environ") -> bool:
    """Return True for any of ``BAROTROPIC=true|1|TRUE``."""
    raw = env.get("BAROTROPIC", "")
    return raw.lower() in ("true", "1")


def _derive_det_ofs(ofs: str) -> str:
    """Map a 2D OFS name to its 3D deterministic counterpart."""
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

    ``scrub_ld_preload=True`` removes ``LD_PRELOAD`` from the child env to
    keep netCDF4 / numpy from segfaulting when the J-job preloaded
    ``libnetcdff.so`` for upstream Fortran.
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
