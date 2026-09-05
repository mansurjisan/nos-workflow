"""Post stage entry point."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

from .._log import emit_stage_summary, stage_logger
from ..errors import StageFailedError
from ..post.base import PostProduct, ProductContext, ProductResult
from ..post.naming import points_cwl_name, stations_nc_name
from ..post.registry import (
    get_product,
    register,
    resolve_product_names,
    resolve_product_options,
)
from ..post.worker_base import (
    NosUtilsProduct,
    fix_file,
    has_3d_stacks,
    has_field_stacks,
    has_staout,
    staging_dir,
)
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
    if descriptor.framework == "comf_standalone":
        raise NotImplementedError(
            "comf_standalone post (ROMS/FVCOM standalone) not yet wired; "
            "model execution shells out to the legacy COMF scripts (WCOSS2-gated)"
        )

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
    # Worker output is echoed here as each finishes, but a worker still
    # running when the job is killed only has its lines in $pgmout. Say
    # where that is so it can be tailed live rather than reconstructed.
    sl.info("worker output also at $pgmout=%s (tail -f during the run)", pgmout)

    combine_script = _resolve_combine_script(homenos, shell_env)
    if combine_script is None:
        searched = [
            shell_env.get("NOS_COMBINE_OUTPUTS_SCRIPT", "<NOS_COMBINE_OUTPUTS_SCRIPT unset>"),
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

    ctx = ProductContext(
        descriptor=descriptor,
        shell_env=shell_env,
        homenos=homenos,
        fixofs=fixofs,
        comout=comout,
        data=data,
        pdy=pdy,
        cyc=cyc,
        cycle=cycle,
        run_name=run_name,
        prefix_nos=prefix_nos,
        nc_hour=nc_hour,
        sta_in=sta_in,
        combine_script=combine_script,
        pgmout=pgmout,
        product_options=resolve_product_options(
            shell_env, homenos=homenos, yaml_path=descriptor.yaml_path,
        ),
    )

    results: List[ProductResult] = []
    for name in _ordered_products(
        resolve_product_names(
            descriptor.framework,
            shell_env,
            homenos=homenos,
            yaml_path=descriptor.yaml_path,
        )
    ):
        product_cls = get_product(name)
        if product_cls is None:
            logger.warning(
                "WARNING: unknown post product %r, skipping", name
            )
            results.append(
                ProductResult(
                    name=name, status="skipped", detail="unregistered product"
                )
            )
            continue
        results.append(_execute_product(product_cls(), ctx))

    _write_post_manifest(
        comout=comout,
        run_name=run_name,
        cycle=cycle,
        pdy=pdy,
        cyc=cyc,
        sta_in=sta_in,
    )

    _write_post_outputs_manifest(
        comout=comout,
        run_name=run_name,
        cyc=cyc,
        pdy=pdy,
        results=results,
    )

    sl.info("post-processing completed")
    return 0


#: Products that read the split field stacks, and so must not run before
#: ``fields_nc`` has materialised them on the coupled (OLDIO) path.
_SPLIT_CONSUMERS = ("maxele", "slab2d", "geopkg", "adcirc", "profiles")


#: ``(producer, consumers, why)`` -- the producer is hoisted ahead of any
#: selected consumer. Declaring the dependency here is cheaper than
#: teaching each consumer to detect and recover from "inputs exist but are
#: not built yet", and much cheaper than having them skip silently, which
#: would turn a missed prerequisite into no output and no complaint.
_DEPENDENCIES = (
    (
        "fields_nc",
        _SPLIT_CONSUMERS,
        "it splits the combined stacks that %s read",
    ),
    (
        "stations_nc",
        ("stations_mllw",),
        "it writes the station file that %s shifts onto MLLW",
    ),
    (
        "points_cwl",
        ("stations_mllw",),
        "it writes the station file that %s shifts onto MLLW",
    ),
)


def _ordered_products(names: List[str]) -> List[str]:
    """Hoist each producer in :data:`_DEPENDENCIES` ahead of its consumers.

    On the coupled path the run stage stages combined ``schout_*.nc`` and
    ``fields_nc`` is what splits them into the per-variable stacks every
    other field product reads; ``stations_mllw`` likewise re-reads what
    ``stations_nc`` publishes. Both are real dependencies, and leaving them
    to the order someone happened to write in the YAML makes the suite's
    success depend on a list's spelling.

    Only reorders when both sides are present; otherwise the caller's
    order is preserved exactly.
    """
    # A product repeated in the YAML would otherwise be run twice -- and for
    # a producer, hoisting only moves its first occurrence, leaving the
    # duplicate to re-split and re-publish everything downstream.
    ordered: List[str] = []
    for name in names:
        if name not in ordered:
            ordered.append(name)

    for producer, consumers, why in _DEPENDENCIES:
        if producer not in ordered:
            continue
        selected = [n for n in ordered if n in consumers]
        if not selected:
            continue
        first = min(ordered.index(n) for n in selected)
        if ordered.index(producer) < first:
            continue
        ordered.remove(producer)
        ordered.insert(first, producer)
        logger.info(
            "post: running %s first; %s", producer, why % ", ".join(selected)
        )
    return ordered


def _execute_product(product: PostProduct, ctx: ProductContext) -> ProductResult:
    """Run one product with isolation: unexpected exceptions warn and mark
    the product failed so the remaining products still run;
    ``StageFailedError`` stays fatal."""
    t0 = time.monotonic()
    try:
        result = product.produce(ctx)
        if not isinstance(result, ProductResult):
            raise TypeError(
                f"produce() returned {type(result).__name__}, "
                "expected ProductResult"
            )
    except StageFailedError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "WARNING: post product %s failed: %s", product.name, exc
        )
        result = ProductResult(
            name=product.name, status="failed", detail=str(exc)
        )
    result.duration_s = time.monotonic() - t0
    return result


def _write_post_outputs_manifest(
    *,
    comout: Path,
    run_name: str,
    cyc: str,
    pdy: str,
    results: List[ProductResult],
) -> None:
    """Write the product-outcome manifest; never fails the stage."""
    try:
        from ..post.outputs_manifest import write_outputs_manifest

        write_outputs_manifest(
            comout=comout, run=run_name, cyc=cyc, pdy=pdy, results=results,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("outputs manifest write skipped: %s", exc)


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
) -> Optional[Path]:
    """Build the working dir for ``phase`` and run the combine script.

    Returns the COMOUT path of the copied station NetCDF, or None when
    the phase was skipped or produced nothing.
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
        return None

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
        return None

    sta_nc = work_post / stations_nc_name(prefix_nos, cyc, pdy, phase)
    if sta_nc.is_file():
        target = comout / sta_nc.name
        _copy_preserve(sta_nc, target)
        logger.info("Created: %s", sta_nc.name)
        return target
    logger.warning(
        "WARNING: Expected station NetCDF not found: %s", sta_nc
    )
    return None


def _write_post_manifest(
    *,
    comout: Path,
    run_name: str,
    cycle: str,
    pdy: str,
    cyc: str,
    sta_in: Path,
) -> None:
    """Write the post-stage input manifest; never fails the stage.

    Post consumes the per-phase ``staout_*`` files combined this cycle
    (under ``$COMOUT/{run}.{cycle}.{restart,forecast}_outputs``) plus the
    resolved ``station.in``. ``phase`` is ``None`` -- post spans both
    nowcast and forecast.
    """
    try:
        from ..inputs_manifest import InputCollector, write_inputs_manifest

        collector = InputCollector()
        for phase, dir_suffix, src_label in (
            ("nowcast", "restart_outputs", "STAOUT_NOWCAST"),
            ("forecast", "forecast_outputs", "STAOUT_FORECAST"),
        ):
            staout_dir = comout / f"{run_name}.{cycle}.{dir_suffix}"
            files = []
            if staout_dir.is_dir():
                for n in _STAOUT_INDICES:
                    p = staout_dir / f"staout_{n}"
                    if p.is_file():
                        files.append(str(p))
            collector.add("model_output", src_label, files)

        collector.add("static", "STATION", [str(sta_in)])

        write_inputs_manifest(
            comout=comout,
            run=run_name,
            cyc=cyc,
            pdy=pdy,
            stage="post",
            collector=collector,
            phase=None,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("input manifest write skipped: %s", exc)


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
        homenos / "ush" / "python" / "nos_workflow" / "ensemble"
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
    """Run ``cmd``, echoing merged stdout/stderr into the stage log.

    Output reaches the stage log as each worker finishes, as well as
    ``log_path`` (the NCO ``$pgmout``). The echo is not cosmetic:
    $pgmout is only surfaced by the J-job's closing ``cat``, so a post
    job that is killed -- walltime, OOM -- lost every product's output at
    once, and the log gave no way to tell which products had finished or
    where it stopped.

    A worker still in flight when the kill lands does lose its output
    here; its lines are in $pgmout on disk and can be tailed live during
    the run, which is why that path is logged up front.

    ``scrub_ld_preload=True`` removes ``LD_PRELOAD`` from the child env to
    keep netCDF4 / numpy from segfaulting when the J-job preloaded
    ``libnetcdff.so`` for upstream Fortran.
    """
    child_env = os.environ.copy()
    if scrub_ld_preload and "LD_PRELOAD" in child_env:
        del child_env["LD_PRELOAD"]
    # Unbuffered child stdout, or a killed worker's last lines die in its
    # own pipe buffer -- which is the failure this streaming exists to fix.
    child_env["PYTHONUNBUFFERED"] = "1"

    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        env=child_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    captured = getattr(proc, "stdout", None) or ""
    for line in captured.splitlines():
        logger.info("%s", line)
    if captured:
        try:
            with open(log_path, "a") as log_fh:
                log_fh.write(
                    captured if captured.endswith("\n") else captured + "\n"
                )
        except OSError:
            pass
    return proc.returncode


@register
class StationsNcProduct(PostProduct):
    """Station-timeseries NetCDF per phase via ``schism_combine_outputs.py``.

    Wraps the legacy per-phase flow (control file, station.lat.lon,
    staout symlinks, combine subprocess, COMOUT copy) unchanged.

    This is a SECOFS-shaped product: the combine script reads the 3D
    staout files in the layout SECOFS' SCHISM build writes (per station,
    nvrt values of the variable followed by nvrt z-coordinates, wrapped
    onto alternating lines). STOFS-3D-ATL writes one value per station
    per step in those same files, so there is no profile to assemble
    there and the reshape fails -- ATL's station product is
    ``points_cwl``, which is what ops itself produces for that system.
    """

    name = "stations_nc"

    def produce(self, ctx: ProductContext) -> ProductResult:
        outputs: List[str] = []
        attempted: List[str] = []
        failed: List[str] = []
        for phase in ("nowcast", "forecast"):
            # Checked up front only to classify the outcome; the call
            # below still does its own warn-and-continue on absent input.
            staged = has_staout(staging_dir(ctx, phase))
            if staged:
                attempted.append(phase)
            created = _process_phase(
                phase=phase,
                data=ctx.data,
                comout=ctx.comout,
                run_name=ctx.run_name,
                cycle=ctx.cycle,
                pdy=ctx.pdy,
                cyc=ctx.cyc,
                nc_hour=ctx.nc_hour,
                prefix_nos=ctx.prefix_nos,
                sta_in=ctx.sta_in,
                combine_script=ctx.combine_script,
                pgmout=ctx.pgmout,
            )
            if created is not None:
                outputs.append(str(created))
            elif staged:
                # Inputs were there and we still have nothing: a real
                # failure, not an absent-input skip. Reporting "ok" here
                # is how ATL's every-cycle breakage stayed invisible.
                failed.append(phase)

        if not attempted:
            return ProductResult(
                name=self.name, status="skipped",
                detail="no staout files staged",
            )
        if failed:
            return ProductResult(
                name=self.name, status="failed", outputs=outputs,
                detail="produced nothing for: " + ", ".join(failed),
            )
        return ProductResult(name=self.name, status="ok", outputs=outputs)


_FIELD_STACK_GLOBS = (
    "out2d_[0-9]*.nc",
    "temperature_[0-9]*.nc",
    "salinity_[0-9]*.nc",
    "horizontalVelX_[0-9]*.nc",
    "horizontalVelY_[0-9]*.nc",
    "zCoordinates_[0-9]*.nc",
    "verticalVelocity_[0-9]*.nc",
    "diffusivity_[0-9]*.nc",
)


def _has_staged_field_stacks(staging: Path) -> bool:
    """True when the staging dir holds split stacks or combined schout."""
    if not staging.is_dir():
        return False
    for pattern in _FIELD_STACK_GLOBS:
        if any(staging.glob(pattern)):
            return True
    return any(
        f.name.count("_") == 1 for f in staging.glob("schout_[0-9]*.nc")
    )


def _product_base_date(ctx, phase: str) -> str:
    """Fallback time origin for products whose inputs carry no units.

    Preferred source is the staged stacks themselves (see
    ``worker_base.base_date_from_staging``); this is used only when no
    stack is readable, e.g. points_cwl on staout text alone.

    Real date arithmetic, NOT ``(cyc - LEN_NOWCAST) % 24`` glued to PDY:
    when the nowcast reaches back past midnight -- every standard cycle
    of both target systems -- the hour wraps but the DATE must roll back
    too, or every timestamp lands exactly one day late.

    Phase anchors follow the engine: the nowcast leg starts at
    cycle - LEN_NOWCAST; a forecast leg that restarts its clock (coupled,
    ihot=1) starts at the cycle time, while one that continues the
    nowcast clock (standalone, ihot=2) keeps the nowcast origin. With
    USE_DATM unset the coupled anchor is used, which is the repo-wide
    reading of that variable (see ``runners/schism_ufs/stage_files.py``:
    standalone is the only thing that ever sets it, and it sets it to
    false).
    """
    from datetime import datetime, timedelta

    try:
        cycle_dt = datetime.strptime(f"{ctx.pdy}{int(ctx.cyc):02d}", "%Y%m%d%H")
    except (TypeError, ValueError):
        return f"{ctx.pdy[:4]}-{ctx.pdy[4:6]}-{ctx.pdy[6:8]} 00:00:00"

    try:
        len_nowcast = float(ctx.shell_env.get("LEN_NOWCAST", "") or 6.0)
    except (TypeError, ValueError):
        len_nowcast = 6.0

    origin = cycle_dt - timedelta(hours=len_nowcast)
    if phase == "forecast" and _forecast_clock_restarts(ctx):
        origin = cycle_dt
    # ops units format: whitespace-separated, seconds present.
    return origin.strftime("%Y-%m-%d %H:%M:%S")


def _forecast_clock_restarts(ctx) -> bool:
    """True when the forecast leg starts its model clock afresh.

    The coupled build hot-starts with ihot=1 (clock reset); the
    standalone build uses ihot=2 and continues the nowcast clock. USE_DATM
    is the resolver's coupled/standalone switch, and only standalone ever
    sets it -- so unset means coupled.

    Tested exactly as the rest of the repo tests it (``!= "false"``, cf.
    ``stage_files.py`` and ``nos_run.sh``) rather than against a wider
    set of falsey spellings: accepting "0"/"no" here while the run side
    accepts only "false" would let one value route the run coupled and
    the timestamps standalone, which is a silent six-hour offset.
    """
    return str(ctx.shell_env.get("USE_DATM", "true")).strip().lower() != "false"


def _len_nowcast_hours(env) -> str:
    """LEN_NOWCAST as a string for the fields worker (default 6 h)."""
    raw = env.get("LEN_NOWCAST", "")
    try:
        return str(float(raw))
    except (TypeError, ValueError):
        return "6.0"


def _post_max_workers(env: "os._Environ", configured=None) -> str:
    """Worker count for the timestep-parallel products (geopkg).

    Contouring one SECOFS timestep means a 1.69M-node triangulation, and
    a cycle has tens of them; ops fanned that over a fork pool, so
    leaving it serial is not a small difference -- it is the difference
    between finishing inside the job's walltime and not. Defaults to the
    cores PBS gave us rather than 1.
    """
    if configured is not None:
        try:
            n = int(configured)
            if n > 0:
                return str(n)
        except (TypeError, ValueError):
            logger.warning(
                "post: max_workers %r is not a positive integer; falling "
                "back to the job's core count", configured,
            )
    # $NCPUS is what PBS allocated, not a preference, so it ranks below
    # anything explicitly asked for.
    raw = env.get("NCPUS", "")
    try:
        n = int(raw)
        if n > 0:
            return str(n)
    except (TypeError, ValueError):
        pass
    return str(max(1, (os.cpu_count() or 2) - 1))


def _fields_deflate(raw: object) -> str:
    """zlib level for published field stacks (``POST_FIELDS_DEFLATE``).

    Defaults to 0 -- ops publishes these stacks uncompressed, and SCHISM
    already deflates the 3D ones itself, so compressing here is an opt-in
    trade of post CPU for roughly 7% of cycle volume.
    """
    try:
        level = int(raw)
    except (TypeError, ValueError):
        return "0"
    return str(level) if 0 <= level <= 9 else "0"


def _option_bool(raw: object, default: bool) -> bool:
    """A yes/true/1 vs no/false/0 option that may arrive as a yaml bool
    (native) or a string (env override, or yaml quoted as text)."""
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in ("yes", "true", "1"):
        return True
    if text in ("no", "false", "0"):
        return False
    return default


def _read_fields_result(result_json: Path) -> List[str]:
    """Created-file list from the fields worker's result json."""
    try:
        data = json.loads(result_json.read_text())
        return [str(p) for p in data.get("created", [])]
    except Exception:  # noqa: BLE001
        logger.warning("fields_nc: result json unreadable: %s", result_json)
        return []


@register
class FieldsNcProduct(PostProduct):
    """Canonical per-variable field stacks from the staged model outputs.

    Delegates to the ``nos_workflow.post.products.fields`` worker in a
    subprocess so the netCDF4 work stays out of the stage process (same
    LD_PRELOAD rationale as the stations combine). Skips cleanly when
    the run stages did not stage field files (``post.archive_fields``
    off).

    ``publish: false`` keeps the split step (what slab2d/maxele/etc.
    read on the coupled OLDIO path) but publishes nothing to COMOUT.
    """

    name = "fields_nc"

    def produce(self, ctx: ProductContext) -> ProductResult:
        publish = _option_bool(
            self.option(ctx, "publish", default=True, env_key="POST_FIELDS_PUBLISH"),
            default=True,
        )
        outputs: List[str] = []
        staged_any = False
        failed_phases: List[str] = []
        for phase, dir_suffix in (
            ("nowcast", "restart_outputs"),
            ("forecast", "forecast_outputs"),
        ):
            staging = ctx.comout / f"{ctx.run_name}.{ctx.cycle}.{dir_suffix}"
            if not _has_staged_field_stacks(staging):
                logger.info(
                    "fields_nc: no field stacks staged for %s, skipping",
                    phase,
                )
                continue
            staged_any = True
            work = ctx.data / f"post_fields_{phase}"
            work.mkdir(parents=True, exist_ok=True)
            result_json = work / "fields_result.json"
            argv = [
                "python3", "-m", "nos_workflow.post.products.fields",
                "--staging", str(staging),
                "--comout", str(ctx.comout),
                "--prefix", ctx.prefix_nos,
                "--cyc", ctx.cyc,
                "--pdy", ctx.pdy,
                "--phase", phase,
                "--nowcast-hours", _len_nowcast_hours(ctx.shell_env),
                "--deflate", _fields_deflate(
                    self.option(
                        ctx, "deflate", default="0",
                        env_key="POST_FIELDS_DEFLATE",
                    )
                ),
                "--combine-script", str(ctx.combine_script),
                "--result-json", str(result_json),
            ]
            if not publish:
                argv.append("--split-only")
            rc = _run_subprocess_appending(
                argv,
                cwd=work,
                log_path=ctx.pgmout,
                scrub_ld_preload=True,
            )
            if rc != 0:
                logger.warning(
                    "WARNING: fields worker failed for %s (rc=%d)", phase, rc,
                )
                failed_phases.append(phase)
                continue
            outputs.extend(_read_fields_result(result_json))

        if not staged_any:
            return ProductResult(
                name=self.name,
                status="skipped",
                detail="no field stacks staged",
            )
        if failed_phases:
            # Non-fatal to the stage, but surfaced for monitoring.
            return ProductResult(
                name=self.name,
                status="failed",
                outputs=outputs,
                detail="worker failed for: " + ", ".join(failed_phases),
            )
        if not publish:
            return ProductResult(
                name=self.name,
                status="ok",
                outputs=outputs,
                detail="split only, nothing published",
            )
        return ProductResult(name=self.name, status="ok", outputs=outputs)


@register
class MaxeleProduct(NosUtilsProduct):
    """Maximum water level over the forecast window (autoval product).

    Ops reduces the forecast stacks only, so this runs on the forecast
    phase alone. The time window is derived from the data rather than
    stamped with ops' hardcoded (90000, 432000) s: that constant is
    simply ops' own 5-day run expressed in seconds, and this branch
    forecasts longer. Pass --ops-window to opt back in.

    NOTE the published name carries no phase token, so this product is
    only safe while ``phases`` names exactly one leg -- widening it would
    make both legs write the same COMOUT file.
    """

    name = "maxele"
    worker = "nos_workflow.post.products.maxele"
    phases = ("forecast",)

    def worker_args(self, ctx, phase, staging, work):
        if not has_field_stacks(staging):
            return None
        return [
            "--staging", str(staging),
            "--comout", str(ctx.comout),
            "--prefix", ctx.prefix_nos,
            "--cyc", ctx.cyc,
            "--pdy", ctx.pdy,
            "--base-date", _product_base_date(ctx, phase),
        ]


@register
class AdcircProduct(NosUtilsProduct):
    """ADCIRC-format water-level fields: the CERA feed and the AWIPS
    grib2 step's input.

    Both legs run: the published name carries the phase token (and the
    hour range), so the nowcast and forecast files cannot collide -- the
    guard test pins that. The urban small-disturbance mask is optional,
    so a system without the ops node-id fix file publishes unmasked
    rather than skipping.
    """

    name = "adcirc"
    worker = "nos_workflow.post.products.adcirc"
    empty_is_skipped = True

    def worker_args(self, ctx, phase, staging, work):
        if not has_field_stacks(staging):
            return None
        args = [
            "--staging", str(staging),
            "--comout", str(ctx.comout),
            "--prefix", ctx.prefix_nos,
            "--cyc", ctx.cyc,
            "--pdy", ctx.pdy,
            "--phase", phase,
            "--base-date", _product_base_date(ctx, phase),
            "--nowcast-hours", _len_nowcast_hours(ctx.shell_env),
        ]
        # Fix name is the ops system's, not our variant's (points_cwl
        # precedent): stofs_3d_atl_ufs -> stofs_3d_atl_node_id_*.txt.
        ops = ctx.prefix_nos.split("_ufs")[0]
        city = fix_file(
            ctx,
            "node_id_city_poly_adcirc.txt",
            f"{ops}_node_id_city_poly_adcirc.txt",
        )
        if city is not None:
            args += ["--city-nodes", str(city)]
        else:
            logger.info(
                "adcirc: no city node-id file under %s; urban "
                "small-disturbance masking off (ops uses "
                "%s_node_id_city_poly_adcirc.txt)", ctx.fixofs, ops,
            )
        return args


def _elev_metadata_claims_a_datum(var_defs_path: Path) -> bool:
    """True when the staout-nc JSON's first (elevation) entry names a
    vertical datum (NAVD88/MSL) in its long_name/standard_name.

    The ops ATL fix set shifts zeta to NAVD88 and labels it as such; the
    "publishing unshifted, expect a bias" warning below only makes sense
    for a fix set that makes that claim. A system whose metadata is
    honest about carrying the raw model datum (e.g. Alaska, which has no
    xgeoid .nco yet) must not trigger it.
    """
    try:
        with open(var_defs_path) as f:
            var_defs = json.load(f)
        first = next(iter(var_defs.values()))
    except (OSError, ValueError, StopIteration):
        return False
    text = " ".join(
        str(first.get(key, ""))
        for key in ("long_name", "stardard_name", "standard_name")
    ).lower()
    return "navd" in text or "msl" in text


@register
class PointsCwlProduct(NosUtilsProduct):
    """Ops-style station timeseries from the staged staout files.

    Needs the ops staout-nc metadata pair in $FIXofs; a system without
    it (SECOFS has none) skips cleanly. Fix names are tried under both
    PREFIXNOS and the ops system prefix, since the variant suffix is
    ours (``stofs_3d_atl_ufs`` -> ``stofs_3d_atl_staout_nc.json``).
    """

    name = "points_cwl"
    worker = "nos_workflow.post.products.points_cwl"

    def worker_args(self, ctx, phase, staging, work):
        ops = ctx.prefix_nos.split("_ufs")[0]
        var_defs = fix_file(ctx, "staout_nc.json", f"{ops}_staout_nc.json")
        meta = fix_file(ctx, "staout_nc.csv", f"{ops}_staout_nc.csv")
        if not has_staout(staging) or var_defs is None or meta is None:
            return None
        args = [
            "--staging", str(staging),
            "--comout", str(ctx.comout),
            "--prefix", ctx.prefix_nos,
            "--cyc", ctx.cyc,
            "--pdy", ctx.pdy,
            "--phase", phase,
            "--base-date", _product_base_date(ctx, phase),
            "--var-defs", str(var_defs),
            "--station-meta", str(meta),
        ]
        # The station JSON labels zeta with a datum (NAVD88 on the ATL
        # fix set) that is only true AFTER the ops ncap2 shift, so the
        # .nco must be applied whenever the metadata claims one.
        # Current ops uses the _msl file; the older lineage used _navd --
        # try both, newest first.
        nco = None
        for stem in ("sta_cwl_xgeoid_to_msl.nco", "sta_cwl_xgeoid_to_navd.nco"):
            nco = fix_file(ctx, stem, f"{ops}_{stem}")
            if nco is not None:
                break
        if nco is not None:
            args += ["--datum-offsets", str(nco)]
        elif _elev_metadata_claims_a_datum(var_defs):
            # Publishing raw xGEOID values under a NAVD88/MSL label would be
            # a silent ~0.3 m bias, so say so loudly rather than shipping it.
            logger.warning(
                "WARNING: points_cwl: no xgeoid->datum .nco found under %s; "
                "publishing UNSHIFTED elevations even though %s labels them "
                "with a datum. Stage the .nco or expect a ~0.3 m bias.",
                ctx.fixofs, var_defs.name,
            )
        else:
            logger.info(
                "points_cwl: no datum .nco staged; elevations are "
                "published unshifted, matching the metadata's "
                "model-datum labeling.",
            )
        return args


@register
class StationsMllwProduct(NosUtilsProduct):
    """MLLW-referenced station water level, from the station product output.

    Compute is local rather than in nos-utils; ``NosUtilsProduct`` is used
    only for its phase iteration and failure isolation.

    Needs the per-system datum table in $FIXofs and a station timeseries
    file for the same phase. Two products write one, and which a system
    runs depends on its ``iout_sta`` setting: ``stations_nc`` (SECOFS) or
    ``points_cwl`` (stofs_3d_ak_ufs, stofs_3d_atl_ufs). Both write
    ``zeta(time, station)`` plus per-station coordinates -- see
    ``nos_utils.post.stations.write_station_timeseries`` -- so either is an
    equally valid source; this tries ``stations_nc`` first since that is
    what SECOFS, the only system with a table so far, produces. A system
    with no table skips cleanly, as does a phase whose station file (of
    either kind) was not produced.
    """

    name = "stations_mllw"
    worker = "nos_workflow.post.products.stations_mllw"

    def worker_args(self, ctx, phase, staging, work):
        table = fix_file(ctx, "mllw_datum.csv")
        if table is None:
            return None
        source = ctx.comout / stations_nc_name(
            ctx.prefix_nos, ctx.cyc, ctx.pdy, phase
        )
        if not source.is_file():
            source = ctx.comout / points_cwl_name(
                ctx.prefix_nos, ctx.cyc, ctx.pdy, phase
            )
        if not source.is_file():
            return None
        return [
            "--stations-nc", str(source),
            "--comout", str(ctx.comout),
            "--prefix", ctx.prefix_nos,
            "--cyc", ctx.cyc,
            "--pdy", ctx.pdy,
            "--phase", phase,
            "--factors", str(table),
            "--station-in", str(ctx.sta_in),
        ]


@register
class Slab2dProduct(NosUtilsProduct):
    """2D slabs (surface/bottom/fixed-depth) per staged output stack.

    Ops extracts a ``field2d`` per output stack of the run, so both
    phases run here; the worker skips any stack index missing one of the
    six families it needs.
    """

    name = "slab2d"
    worker = "nos_workflow.post.products.slab2d"
    empty_is_skipped = True

    def worker_args(self, ctx, phase, staging, work):
        if not has_field_stacks(staging):
            return None
        return [
            "--staging", str(staging),
            "--comout", str(ctx.comout),
            "--prefix", ctx.prefix_nos,
            "--cyc", ctx.cyc,
            "--pdy", ctx.pdy,
            "--phase", phase,
            "--base-date", _product_base_date(ctx, phase),
            "--nowcast-hours", _len_nowcast_hours(ctx.shell_env),
        ]


@register
class GeopkgProduct(NosUtilsProduct):
    """Per-timestep disturbance GeoPackages for the nowCOAST feed.

    Needs only the out2d stacks. The contour/geometry stack
    (matplotlib/shapely/geopandas) is optional at runtime, so a worker
    that wrote nothing reads as skipped rather than failed.
    """

    name = "geopkg"
    worker = "nos_workflow.post.products.geopkg"
    empty_is_skipped = True

    def worker_args(self, ctx, phase, staging, work):
        if not has_field_stacks(staging):
            return None
        return [
            "--staging", str(staging),
            "--comout", str(ctx.comout),
            "--prefix", ctx.prefix_nos,
            "--cyc", ctx.cyc,
            "--pdy", ctx.pdy,
            "--phase", phase,
            "--nowcast-hours", _len_nowcast_hours(ctx.shell_env),
            "--max-workers", _post_max_workers(
                ctx.shell_env,
                self.option(
                    ctx, "max_workers", env_key="NOS_POST_MAX_WORKERS"
                ),
            ),
        ]


@register
class ProfilesProduct(NosUtilsProduct):
    """Station vertical profiles (ops ``{ncast,fcast}.station.profile.nc``).

    Needs the mesh (hgrid.gr3 + vgrid.in) and the station list from
    $FIXofs, tried under both spellings: the ATL fix set carries the ops
    system prefix (``stofs_3d_atl_station.in``) while ours carries
    PREFIXNOS (``{prefix}.station.in``). A system missing any of the
    three skips cleanly, and the station list falls back to the one the
    stage already resolved (which also honours $STA_OUT_CTL).

    A station outside the mesh fails the phase, as the ops driver does;
    ``NOS_PROFILES_OUTSIDE=nearest`` opts into pylib's nearest-node
    fallback instead (see the worker).
    """

    name = "profiles"
    worker = "nos_workflow.post.products.profiles"

    def worker_args(self, ctx, phase, staging, work):
        ops = ctx.prefix_nos.split("_ufs")[0]
        hgrid = fix_file(ctx, "hgrid.gr3", f"{ops}_hgrid.gr3")
        vgrid = fix_file(ctx, "vgrid.in", f"{ops}_vgrid.in")
        station = fix_file(ctx, "station.in", f"{ops}_station.in")
        if station is None and ctx.sta_in and Path(ctx.sta_in).is_file():
            station = ctx.sta_in
        # zCoordinates, not just any stack: a 2D-only run stages out2d and
        # nothing else, and reporting "failed" every cycle for a system
        # that has no vertical output is noise, not a signal.
        if not has_3d_stacks(staging) or None in (hgrid, vgrid, station):
            return None
        return [
            "--staging", str(staging),
            "--comout", str(ctx.comout),
            "--prefix", ctx.prefix_nos,
            "--cyc", ctx.cyc,
            "--pdy", ctx.pdy,
            "--phase", phase,
            "--base-date", _product_base_date(ctx, phase),
            "--hgrid", str(hgrid),
            "--vgrid", str(vgrid),
            "--station-in", str(station),
            "--outside", str(
                self.option(
                    ctx, "outside", default="error",
                    env_key="NOS_PROFILES_OUTSIDE",
                )
            ),
        ]


@register
class BiasCorrectProduct(PostProduct):
    """Ensemble 2D->3D bias correction; no-op unless ``BAROTROPIC`` is set."""

    name = "bias_correct"

    def produce(self, ctx: ProductContext) -> ProductResult:
        if not _is_barotropic(ctx.shell_env):
            return ProductResult(
                name=self.name, status="skipped", detail="BAROTROPIC not set",
            )
        _maybe_bias_correct(
            descriptor=ctx.descriptor,
            shell_env=ctx.shell_env,
            homenos=ctx.homenos,
            comout=ctx.comout,
            run_name=ctx.run_name,
            cycle=ctx.cycle,
            pdy=ctx.pdy,
            cyc=ctx.cyc,
            nc_hour=ctx.nc_hour,
            sta_in=ctx.sta_in,
            pgmout=ctx.pgmout,
        )
        outputs: List[str] = []
        coeff = ctx.comout / "bias_coefficients.json"
        if coeff.is_file():
            outputs.append(str(coeff))
        return ProductResult(name=self.name, status="ok", outputs=outputs)


__all__ = ["run"]
