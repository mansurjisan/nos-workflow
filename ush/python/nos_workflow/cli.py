"""argparse-based CLI dispatcher for ``nos_uw``.

The CLI is intentionally thin: it parses arguments, builds an ``NCOEnv``,
looks up the OFS descriptor + stage runner, and calls into them. All the
real work lives in stage modules (Agent B's ``nos_workflow.stages.*``).

Subcommands:

  - ``run <stage> --ofs <name>``    — execute a stage
  - ``list``                        — print registered OFS systems
  - ``stages <ofs>``                — print stages an OFS exposes
  - ``validate <ofs>``              — sanity-check YAML + FIXofs + EXEC
  - ``env --ofs <name>``            — dump effective env (Agent C wires)

The top-level ``main`` returns an ``int`` exit code so ``__main__`` can
``raise SystemExit(main())``.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import logging
import os
import sys
import traceback
from pathlib import Path
from typing import List, Optional

from . import __version__
from .bash_compat import cyc_str
from .errors import (
    ConfigError,
    OFSNotRegisteredError,
    StageNotFoundError,
    WorkflowError,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


class _UTCFormatter(logging.Formatter):
    """Logging formatter that prints UTC timestamps with [stage] [ofs] tags."""

    def __init__(self) -> None:
        super().__init__(fmt="%(message)s")

    def format(self, record: logging.LogRecord) -> str:  # noqa: D401
        ts = _utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")
        stage = getattr(record, "stage", "-")
        ofs = getattr(record, "ofs", "-")
        return f"[{ts}] [{stage}] [{ofs}] {record.getMessage()}"


def _utc_now() -> _dt.datetime:
    """Return UTC ``datetime`` compatible with both 3.8 and 3.13.

    ``datetime.utcnow`` is deprecated on 3.12+; ``datetime.now(timezone.utc)``
    is the supported replacement. We need 3.8 support too, where both
    spellings work.
    """
    return _dt.datetime.now(_dt.timezone.utc)


def _configure_logging(verbose: bool) -> None:
    from ._log import StageContextFilter

    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_UTCFormatter())
    # Inject stage/ofs from contextvars onto records from bare loggers
    # (e.g. nos_utils.forcing.*) so they show as [prep] [ofs] rather than
    # [-] [-] in the formatted output.
    handler.addFilter(StageContextFilter())
    root = logging.getLogger()
    # Replace handlers — under repeated CLI invocations in tests we'd
    # otherwise stack duplicates.
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
    root.setLevel(level)


def _log_phase(stage: str, ofs: str, message: str) -> None:
    logger = logging.getLogger("nos_workflow.cli")
    logger.info(message, extra={"stage": stage, "ofs": ofs})


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _resolve_ofs(arg_ofs: Optional[str]) -> str:
    """Resolve OFS from --ofs, then $OFS, then $RUN; raise if unset."""
    candidate = arg_ofs or os.environ.get("OFS") or os.environ.get("RUN")
    if not candidate:
        raise ConfigError(
            "OFS not set: pass --ofs <name>, or export OFS / RUN before "
            "calling nos_uw"
        )
    return candidate.lower()


def _resolve_pdy(arg_pdy: Optional[str]) -> Optional[str]:
    return arg_pdy or os.environ.get("PDY")


def _resolve_cyc(arg_cyc: Optional[str]) -> Optional[str]:
    """Take --cyc / $cyc and return zero-padded HH or ``None`` if unset."""
    raw = arg_cyc if arg_cyc is not None else os.environ.get("cyc")
    if raw is None or raw == "":
        return None
    return cyc_str(raw)


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse tree. Exposed for testing."""
    parser = argparse.ArgumentParser(
        prog="nos_uw",
        description="Operational workflow driver for NOS-OFS systems.",
    )
    parser.add_argument(
        "--version", action="version", version=f"nos_uw {__version__}"
    )
    parser.add_argument(
        "--verbose", action="store_true", help="enable DEBUG-level logging"
    )
    sub = parser.add_subparsers(dest="cmd", required=True, metavar="<command>")

    # run -----------------------------------------------------------------
    p_run = sub.add_parser("run", help="execute a stage")
    p_run.add_argument("stage", help="stage name (prep, nowcast, forecast, post, ...)")
    p_run.add_argument("--ofs", help="OFS name; defaults to $OFS or $RUN")
    p_run.add_argument("--pdy", help="cycle date YYYYMMDD; defaults to $PDY")
    p_run.add_argument("--cyc", help="cycle hour HH; defaults to $cyc")
    p_run.set_defaults(func=cmd_run)

    # list ----------------------------------------------------------------
    p_list = sub.add_parser("list", help="list registered OFS systems")
    p_list.set_defaults(func=cmd_list)

    # stages --------------------------------------------------------------
    p_stages = sub.add_parser("stages", help="list stages exposed by an OFS")
    p_stages.add_argument("ofs", help="OFS name")
    p_stages.set_defaults(func=cmd_stages)

    # validate ------------------------------------------------------------
    p_validate = sub.add_parser(
        "validate", help="sanity-check YAML + FIXofs + EXEC paths"
    )
    p_validate.add_argument("ofs", help="OFS name")
    p_validate.set_defaults(func=cmd_validate)

    # env -----------------------------------------------------------------
    p_env = sub.add_parser(
        "env",
        help="dump effective env from YAML (eval-able shell, JSON, or .ctl)",
    )
    p_env.add_argument("--ofs", help="OFS name; defaults to $OFS or $RUN")
    p_env.add_argument(
        "--config",
        help="explicit YAML path; overrides the descriptor's yaml_path",
    )
    p_env.add_argument(
        "--section",
        choices=("domain", "model", "run", "forcing", "paths"),
        help="emit only one section of the export table",
    )
    fmt = p_env.add_mutually_exclusive_group()
    fmt.add_argument(
        "--shell", action="store_true",
        help="emit ``export KEY=VALUE`` lines for eval (default)",
    )
    fmt.add_argument(
        "--json", action="store_true", help="emit a JSON object",
    )
    fmt.add_argument(
        "--ctl", action="store_true",
        help="emit a nosofs-style .ctl file",
    )
    p_env.set_defaults(func=cmd_env)

    return parser


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def cmd_run(args: argparse.Namespace) -> int:
    """Resolve descriptor, translate stage alias, dispatch to stage module."""
    ofs = _resolve_ofs(args.ofs)
    pdy = _resolve_pdy(args.pdy)
    cyc = _resolve_cyc(args.cyc)

    # Bake resolved values back into the env so NCOEnv.from_env / shell
    # children agree with what the operator typed on the command line.
    if pdy:
        os.environ["PDY"] = pdy
    if cyc:
        os.environ["cyc"] = cyc
    os.environ["OFS"] = ofs

    _log_phase(args.stage, ofs, f"resolving descriptor for {ofs}")

    # Lazy imports so test runs (and `--help`) don't pull in the registry
    # at module-load time.
    from .registry import lookup, load_all_descriptors

    load_all_descriptors()
    descriptor = lookup(ofs)  # raises OFSNotRegisteredError on miss

    canonical_stage = descriptor.resolve_stage(args.stage)
    _log_phase(canonical_stage, ofs, f"loading stage module nos_workflow.stages.{canonical_stage}")

    from .env import NCOEnv  # local import so cli is importable without env wiring
    nco_env = NCOEnv.from_env(ofs=ofs)

    stage_module = _import_stage_module(canonical_stage)
    stage_run = getattr(stage_module, "run", None)
    if stage_run is None:
        raise StageNotFoundError(
            f"stage module nos_workflow.stages.{canonical_stage} has no run()"
        )

    _log_phase(canonical_stage, ofs, "stage start")
    rc = stage_run(descriptor, nco_env)
    _log_phase(canonical_stage, ofs, f"stage end rc={rc}")
    return int(rc or 0)


def cmd_list(args: argparse.Namespace) -> int:
    """Print a table of registered OFS systems."""
    try:
        from .registry import list_ofs, load_all_descriptors
    except ImportError:
        print("No OFS systems registered yet (registry module not present).")
        return 0

    # Trigger descriptor module imports so register() side-effects populate
    # the registry. Idempotent across CLI calls.
    load_all_descriptors()
    rows = list_ofs()
    if not rows:
        print("No OFS systems registered.")
        return 0

    print(f"{'NAME':<20} {'FRAMEWORK':<12} STAGES")
    print("-" * 70)
    for d in rows:
        stages = ",".join(d.canonical_stages)
        if d.extra_stages:
            stages += "  (+" + ",".join(d.extra_stages) + ")"
        print(f"{d.name:<20} {d.framework:<12} {stages}")
    return 0


def cmd_stages(args: argparse.Namespace) -> int:
    """Print stages an OFS exposes."""
    from .registry import lookup, load_all_descriptors

    load_all_descriptors()
    descriptor = lookup(args.ofs.lower())  # raises OFSNotRegisteredError on miss

    for s in descriptor.canonical_stages:
        print(s)
    for s in descriptor.extra_stages:
        print(f"{s}  (extra)")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Sanity-check YAML + FIXofs + EXEC for an OFS."""
    from .registry import lookup, load_all_descriptors

    load_all_descriptors()
    descriptor = lookup(args.ofs.lower())  # raises OFSNotRegisteredError on miss

    problems: List[str] = []
    yaml_path = getattr(descriptor, "yaml_path", None)
    if yaml_path and not Path(yaml_path).is_file():
        problems.append(f"YAML config missing: {yaml_path}")

    fixofs = os.environ.get("FIXofs")
    if fixofs and not Path(fixofs).is_dir():
        problems.append(f"FIXofs not a directory: {fixofs}")

    execnos = os.environ.get("EXECnos")
    if execnos and not Path(execnos).is_dir():
        problems.append(f"EXECnos not a directory: {execnos}")

    if problems:
        for p in problems:
            print(f"FAIL: {p}")
        return 2
    print(f"OK: {args.ofs}")
    return 0


def cmd_env(args: argparse.Namespace) -> int:
    """Resolve a YAML config and emit its export table.

    Resolution order for the YAML path:
        1. ``--config`` CLI argument (explicit override).
        2. ``OFS_CONFIG`` env var (operational shell convention).
        3. The registered ``OFSDescriptor.yaml_path`` for ``--ofs``,
           resolved against ``$HOMEnos`` if relative.

    Errors print a one-line ``FATAL: ...`` to stdout via the standard
    ``WorkflowError`` path; ``yaml_to_env``'s own ``ERROR:`` line still
    goes to stderr. No tracebacks are dumped unless
    ``NOS_WORKFLOW_DEBUG=1`` is exported.
    """
    from .utils.yaml_to_env import export_for_shell

    if args.json:
        output_format = "json"
    elif args.ctl:
        output_format = "ctl"
    else:
        output_format = "shell"

    section = args.section

    config_path: Optional[Path] = None
    framework = "auto"

    if args.config:
        config_path = Path(args.config)
    else:
        env_config = os.environ.get("OFS_CONFIG")
        if env_config:
            config_path = Path(env_config)
        else:
            ofs = _resolve_ofs(args.ofs)
            try:
                from .registry import load_all_descriptors, lookup
            except ImportError as exc:  # pragma: no cover - defensive
                raise OFSNotRegisteredError(
                    f"registry module not available ({exc})"
                ) from exc
            # Trigger descriptor module imports so ``register()`` side-
            # effects populate the registry. Idempotent across CLI calls.
            load_all_descriptors()
            descriptor = lookup(ofs)
            framework = getattr(descriptor, "framework", "auto") or "auto"
            yaml_path = getattr(descriptor, "yaml_path", None)
            if yaml_path is None:
                raise ConfigError(
                    f"descriptor for ofs={ofs!r} has no yaml_path; pass --config"
                )
            yaml_path = Path(yaml_path)
            if not yaml_path.is_absolute():
                # Resolve against $HOMEnos first (operational layout),
                # then $PACKAGEROOT, then the current working directory.
                root_env = (
                    os.environ.get("HOMEnos")
                    or os.environ.get("PACKAGEROOT")
                    or os.getcwd()
                )
                yaml_path = Path(root_env) / yaml_path
            config_path = yaml_path

    if config_path is None or not config_path.exists():
        raise ConfigError(
            f"YAML config not found: {config_path} "
            f"(pass --config <path> or export OFS_CONFIG)"
        )

    output = export_for_shell(
        config_path=config_path,
        section=section,
        output_format=output_format,
        framework=framework,
    )
    print(output)
    return 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _import_stage_module(stage: str):
    """Import ``nos_workflow.stages.<stage>`` lazily.

    Raises ``StageNotFoundError`` rather than ``ImportError`` so the
    top-level handler logs a clean FATAL.
    """
    import importlib

    try:
        return importlib.import_module(f"nos_workflow.stages.{stage}")
    except ImportError as exc:
        raise StageNotFoundError(
            f"no stage module nos_workflow.stages.{stage} ({exc})"
        ) from exc


def _write_traceback_sidecar(stage: Optional[str]) -> Optional[Path]:
    """If ``$DATA`` is set, dump the active traceback there. Best-effort."""
    data = os.environ.get("DATA")
    if not data:
        return None
    try:
        data_path = Path(data)
        data_path.mkdir(parents=True, exist_ok=True)
        ts = _utc_now().strftime("%Y%m%dT%H%M%SZ")
        stage_tag = stage or "unknown"
        sidecar = data_path / f"nos_uw.{stage_tag}.{ts}.traceback"
        sidecar.write_text(traceback.format_exc())
        return sidecar
    except Exception:  # noqa: BLE001 — never let logging blow up exit path
        return None


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    """Parse args and dispatch. Returns shell-style exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(getattr(args, "verbose", False))

    stage_for_log: Optional[str] = getattr(args, "stage", None) or getattr(
        args, "cmd", None
    )

    try:
        return int(args.func(args) or 0)
    except WorkflowError as exc:
        # Operator-facing one-liner; full traceback to a sidecar if we have $DATA.
        print(f"FATAL: {exc}", flush=True)
        sidecar = _write_traceback_sidecar(stage_for_log)
        if sidecar is not None:
            print(f"FATAL: traceback written to {sidecar}", flush=True)
        return getattr(exc, "returncode", 1) or 1
    # Unexpected exceptions intentionally bubble: PBS will mark the job
    # FAILED and the operator gets the full stack in the log.


__all__ = ["main", "build_parser"]
