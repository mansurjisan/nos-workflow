#!/usr/bin/env python3
"""YAML-to-shell environment-variable bridge for nos_workflow."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


__version__ = "3.0.0"


def load_yaml_with_inheritance(
    yaml_path: Union[str, Path],
    base_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Load a YAML file resolving ``_base: <name>`` deep-merge inheritance.

    Looks for the base under ``<base_dir>/base/<name>.yaml`` (abstract
    bases), then ``<base_dir>/systems/<name>.yaml`` (so a system yaml can
    inherit another system yaml), then a sibling of the config, then
    ``<base_dir>/<name>.yaml``. Inheritance is recursive; child values
    override parent values via :func:`deep_merge`.
    """
    import yaml  # lazy import

    yaml_path = Path(yaml_path)
    if base_dir is None:
        base_dir = yaml_path.parent

    with open(yaml_path, "r") as f:
        data = yaml.safe_load(f) or {}

    base_name = data.pop("_base", None)
    if base_name:
        # Resolve the base from the abstract-base dir (parm/base/), the systems
        # dir (parm/systems/ — so one system yaml can inherit another, e.g. the
        # standalone variant inheriting stofs_3d_atl_ufs), the config's own
        # directory (sibling), then base_dir itself. Without the systems/ and
        # sibling candidates a system->system _base silently no-ops.
        candidates = (
            base_dir / "base" / f"{base_name}.yaml",
            base_dir / "systems" / f"{base_name}.yaml",
            yaml_path.parent / f"{base_name}.yaml",
            base_dir / f"{base_name}.yaml",
        )
        base_path = next((p for p in candidates if p.exists()), None)
        if base_path is not None:
            base_data = load_yaml_with_inheritance(base_path, base_dir)
            data = deep_merge(base_data, data)

    return data


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Deep-merge ``override`` into ``base`` and return a new dict."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def get_nested_value(data: Dict[str, Any], path: str, default: Any = None) -> Any:
    """Look up a value via dot-notation path (``a.b.c``) inside ``data``."""
    keys = path.split(".")
    value: Any = data
    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return default
    return value


def _normalize_cyc(cyc: Any) -> Optional[str]:
    """Coerce ``cyc`` to a two-digit string, or return None."""
    if cyc is None or cyc == "":
        return None
    try:
        n = int(cyc)
    except (TypeError, ValueError):
        return None
    if not 0 <= n <= 23:
        return None
    return f"{n:02d}"


def _machine_profile():
    """Machine profile for ``$NOS_MACHINE`` (default wcoss2), or None.

    Imported lazily and with a sys.path bootstrap because this module is also
    run as a standalone script by ``nos_config.sh``, where ``ush/python`` is
    not necessarily importable yet. Credentials are not validated here -- only
    allocation facts are needed, and nothing is being submitted.
    """
    try:
        if __package__ in (None, ""):
            sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from nos_workflow.platform.profile import MachineProfile

        return MachineProfile.load(validate=False)
    except Exception as exc:  # missing profile, bad schema, no PyYAML
        print(f"WARNING: machine profile unavailable ({exc})", file=sys.stderr)
        return None


def compute_derived_values(
    data: Dict[str, Any],
    runtime_env: Dict[str, Any],
) -> Dict[str, Any]:
    """Compute values that depend on multiple YAML / runtime inputs."""
    computed: Dict[str, Any] = {}

    model = data.get("model", {})
    run = model.get("run", {})

    hindcast_days = run.get("hindcast_days", 0.25)
    forecast_days = run.get("forecast_days", 5.0)

    computed["len_nowcast_hours"] = int(hindcast_days * 24)
    computed["len_forecast_hours"] = int(forecast_days * 24)
    computed["total_run_days"] = hindcast_days + forecast_days

    computed["rnday_nowcast"] = hindcast_days
    computed["rnday_forecast"] = forecast_days

    pdy = runtime_env.get("PDY")
    cyc_value = _normalize_cyc(runtime_env.get("cyc"))

    if pdy and cyc_value:
        try:
            cycle_time = datetime.strptime(f"{pdy}{cyc_value}", "%Y%m%d%H")

            ncast_begin = cycle_time - timedelta(days=hindcast_days)
            computed["PDYHH_NCAST_BEGIN"] = ncast_begin.strftime("%Y%m%d%H")

            computed["PDYHH_FCAST_BEGIN"] = cycle_time.strftime("%Y%m%d%H")

            fcast_end = cycle_time + timedelta(days=forecast_days)
            computed["PDYHH_FCAST_END"] = fcast_end.strftime("%Y%m%d%H")

            computed["time_nowcastend"] = cycle_time.strftime("%Y%m%d%H")
            computed["time_hotstart"] = ncast_begin.strftime("%Y%m%d%H")
            computed["time_forecastend"] = fcast_end.strftime("%Y%m%d%H")

        except (ValueError, TypeError):
            pass

    return computed


def get_runtime_from_env() -> Dict[str, Any]:
    """Return tracked NCO env vars from ``os.environ``."""
    runtime: Dict[str, Any] = {}

    env_vars = [
        "PDY", "cyc", "envir", "NET", "RUN",
        "HOMEnos", "HOMEstofs", "FIXofs", "FIXstofs3d",
        "EXECnos", "EXECstofs3d", "USHnos", "USHstofs3d",
        "PARMnos", "PARMstofs3d", "DATA", "COMOUT", "COMOUTrerun",
        "COMINgfs", "COMINhrrr", "COMINnam", "COMINrtofs", "COMINnwm", "COMINadt",
        "DCOMINusgs", "DCOMINports", "NOSBUFR", "USGSBUFR",
    ]

    for var in env_vars:
        if var in os.environ:
            value = os.environ[var]
            if var == "cyc":
                normalized = _normalize_cyc(value)
                runtime[var] = normalized if normalized is not None else value
            else:
                runtime[var] = value

    return runtime


def export_shell_mappings(
    data: Dict[str, Any],
    framework: str = "auto",
) -> Dict[str, Any]:
    """Build the flat ``{shell_var: value}`` table for one YAML config."""
    exports: Dict[str, Any] = {}

    runtime_env = get_runtime_from_env()
    computed = compute_derived_values(data, runtime_env)

    if framework == "auto":
        system = data.get("system", {})
        framework = system.get("framework", "stofs")

    shell_mappings = data.get("shell_mappings", {})
    variable_mappings = shell_mappings.get("variables", {})

    for shell_var, yaml_path in variable_mappings.items():
        if not isinstance(yaml_path, str):
            continue
        # A non-empty value already in the environment wins over the YAML
        # default. shell_mappings.variables is the per-run tuning surface,
        # so a value passed on the qsub line has to survive being resolved
        # here -- otherwise the YAML silently overwrites it and the run
        # does something other than what was asked for, with nothing in the
        # log to say so. Same ${VAR:-default} semantics the PBS cards use
        # for the COMIN* paths, including treating empty as unset (the
        # cards' own retry re-submits with empty values for unset vars).
        # get_standard_exports() is deliberately not covered: OFS,
        # OCEAN_MODEL and friends are the config's identity, not knobs.
        if os.environ.get(shell_var, "") != "":
            exports[shell_var] = os.environ[shell_var]
            continue
        if yaml_path.startswith("_computed."):
            computed_key = yaml_path.split(".", 1)[1]
            if computed_key in computed:
                exports[shell_var] = computed[computed_key]
        else:
            value = get_nested_value(data, yaml_path)
            if value is not None:
                exports[shell_var] = value

    exports.update(get_standard_exports(data, framework, computed, runtime_env))

    return exports


def get_standard_exports(
    data: Dict[str, Any],
    framework: str,
    computed: Dict[str, Any],
    runtime_env: Dict[str, Any],
) -> Dict[str, Any]:
    """Standard exports applied regardless of ``shell_mappings``."""
    exports: Dict[str, Any] = {}

    system = data.get("system", {})
    exports["OFS"] = system.get("name", "")
    exports["OFS_NAME"] = system.get("name", "")

    model = data.get("model", {})
    ocean_model = model.get("ocean_model", model.get("type", "SCHISM"))
    exports["OCEAN_MODEL"] = (ocean_model or "SCHISM").upper()

    grid = data.get("grid", {})
    exports["GRIDFILE"] = grid.get("files", {}).get("horizontal", "")

    domain = grid.get("domain", {})
    if framework == "stofs":
        exports["LONMIN"] = domain.get("lon_min", "")
        exports["LONMAX"] = domain.get("lon_max", "")
        exports["LATMIN"] = domain.get("lat_min", "")
        exports["LATMAX"] = domain.get("lat_max", "")
    else:
        exports["MINLON"] = domain.get("lon_min", "")
        exports["MAXLON"] = domain.get("lon_max", "")
        exports["MINLAT"] = domain.get("lat_min", "")
        exports["MAXLAT"] = domain.get("lat_max", "")

    exports["nvrt"] = grid.get("n_levels", "")
    exports["KBm"] = grid.get("n_levels", "")
    exports["np_global"] = grid.get("n_nodes", "")
    exports["ne_global"] = grid.get("n_elements", "")
    exports["ns_global"] = grid.get("n_sides", "")

    physics = model.get("physics", {})
    exports["DELT_MODEL"] = physics.get("dt", "")

    exports["LEN_NOWCAST"] = computed.get("len_nowcast_hours", "")
    exports["LEN_FORECAST"] = computed.get("len_forecast_hours", "")

    if framework == "stofs":
        exports["N_DAYS_MODEL_RUN_PERIOD"] = computed.get("total_run_days", "")
        if "PDYHH_NCAST_BEGIN" in computed:
            exports["PDYHH_NCAST_BEGIN"] = computed["PDYHH_NCAST_BEGIN"]
        if "PDYHH_FCAST_BEGIN" in computed:
            exports["PDYHH_FCAST_BEGIN"] = computed["PDYHH_FCAST_BEGIN"]

    if framework == "comf":
        exports["PREFIXNOS"] = system.get("prefix", system.get("name", ""))
        if "time_nowcastend" in computed:
            exports["time_nowcastend"] = computed["time_nowcastend"]
        if "time_forecastend" in computed:
            exports["time_forecastend"] = computed["time_forecastend"]
        if "time_hotstart" in computed:
            exports["time_hotstart"] = computed["time_hotstart"]

        forcing = data.get("forcing", {})
        atm = forcing.get("atmospheric", {})
        exports["DBASE_MET_NOW"] = (atm.get("primary") or "").upper()
        exports["DBASE_MET_FOR"] = (
            atm.get("forecast_source") or atm.get("primary") or ""
        ).upper()

        ocean = forcing.get("ocean", {})
        obc = ocean.get("obc", {})
        exports["DBASE_WL_NOW"] = (obc.get("wl_source") or "").upper()
        exports["DBASE_WL_FOR"] = (obc.get("wl_source") or "").upper()
        exports["DBASE_TS_NOW"] = (obc.get("ts_source") or "").upper()
        exports["DBASE_TS_FOR"] = (obc.get("ts_source") or "").upper()

        tidal = forcing.get("tidal", {})
        exports["CREATE_TIDEFORCING"] = tidal.get("create_forcing", 1)

    if framework == "adcirc":
        exports["PREFIXNOS"] = system.get("prefix", system.get("name", ""))
        if "time_nowcastend" in computed:
            exports["time_nowcastend"] = computed["time_nowcastend"]
        if "time_forecastend" in computed:
            exports["time_forecastend"] = computed["time_forecastend"]
        if "time_hotstart" in computed:
            exports["time_hotstart"] = computed["time_hotstart"]

    # execution.mode=standalone overlays standalone resources/exec; ufs/absent
    # is a strict no-op so the UFS export dict stays byte-identical.
    resources = data.get("resources", {})
    if data.get("execution", {}).get("mode", "ufs") == "standalone":
        overlay = data.get("standalone", {})
        resources = {**resources, **{
            k: overlay[k] for k in ("nprocs", "nscribes", "mem_per_node")
            if k in overlay
        }}
        if "executable" in overlay:
            exports["UFS_EXEC_NAME"] = overlay["executable"]
        if "nws" in overlay:
            exports["NWS_VALUE"] = overlay["nws"]
        exports["USE_DATM"] = "false"

    # ``nprocs`` is total mpiexec rank count; ``nscribes`` is the SCHISM
    # I/O-rank count. NPROCS/TOTAL_TASKS/NCPU_PBS are aliases.
    total = resources.get("nprocs")
    if total in (None, ""):
        total = resources.get("total_tasks", "")
    nscribes_val = resources.get("nscribes", "")
    exports["NPROCS"] = total if total is not None else ""
    exports["TOTAL_TASKS"] = exports["NPROCS"]
    exports["NCPU_PBS"] = exports["NPROCS"]
    exports["NSCRIBES"] = nscribes_val

    # Ranks-per-node and the node count are machine facts, so they come from
    # parm/machines/<NOS_MACHINE>.yaml rather than from a PBS ``select=``
    # string embedded in the system config. PPN is exported whenever the
    # profile's allocation.emit_ranks_per_node is true -- true for both
    # WCOSS2 (PPN=120) and Hercules (PPN=80, via --ntasks-per-node) today;
    # it is only suppressed for a machine profile that sets it false.
    profile = _machine_profile()
    if profile is not None:
        if profile.allocation.emit_ranks_per_node:
            exports["PPN"] = str(profile.allocation.ranks_per_node)
        try:
            exports["NNODES"] = str(profile.nodes(int(total)))
        except (TypeError, ValueError):
            pass

    if resources.get("select"):
        # Left behind by an older config; the allocation no longer comes from it.
        print(
            f"WARNING: resources.select is ignored (allocation now comes from "
            f"parm/machines/); remove it from this config: {resources['select']!r}",
            file=sys.stderr,
        )

    exports.update(runtime_env)

    return exports


def format_shell_exports(exports: Dict[str, Any]) -> str:
    """Render the export table as ``export KEY=VALUE`` lines."""
    lines: List[str] = []
    for key, value in sorted(exports.items()):
        if value is None or value == "":
            continue
        if key == "cyc":
            normalized = _normalize_cyc(value)
            if normalized is not None:
                lines.append(f"export {key}={normalized}")
                continue
        if isinstance(value, str) and (" " in value or '"' in value):
            escaped = value.replace('"', '\\"')
            lines.append(f'export {key}="{escaped}"')
        elif isinstance(value, bool):
            lines.append(f"export {key}={1 if value else 0}")
        elif isinstance(value, list):
            joined = " ".join(str(v) for v in value)
            lines.append(f'export {key}="{joined}"')
        else:
            lines.append(f"export {key}={value}")
    return "\n".join(lines)


def format_json(exports: Dict[str, Any]) -> str:
    """Render the export table as pretty-printed JSON."""
    return json.dumps(exports, indent=2, default=str, sort_keys=True)


def format_ctl_file(exports: Dict[str, Any], system_name: str) -> str:
    """Render the export table as a nosofs-style ``.ctl`` file."""
    lines: List[str] = [
        f"# {system_name}.ctl - Generated from YAML configuration",
        f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]

    categories: Dict[str, List[str]] = {
        "Model": [
            "OCEAN_MODEL", "GRIDFILE", "GRIDFILE_LL",
            "nvrt", "KBm", "np_global", "ne_global", "ns_global",
        ],
        "Domain": [
            "MINLON", "MAXLON", "MINLAT", "MAXLAT",
            "IGRD_MET", "IGRD_OBC",
        ],
        "Physics": [
            "DELT_MODEL", "NDTFAST", "THETA_S", "THETA_B",
            "TCLINE", "NVTRANS", "NVSTR",
        ],
        "Run": ["LEN_NOWCAST", "LEN_FORECAST", "BASE_DATE"],
        "Forcing": [
            "DBASE_MET_NOW", "DBASE_MET_FOR",
            "DBASE_WL_NOW", "DBASE_WL_FOR",
            "DBASE_TS_NOW", "DBASE_TS_FOR",
        ],
        "Tidal": [
            "CREATE_TIDEFORCING",
            "HC_FILE_OBC", "HC_FILE_OFS", "HC_FILE_NWLON",
        ],
        "Files": [
            "RUNTIME_CTL", "RUNTIME_CTL_FOR", "VGRID_CTL",
            "STA_OUT_CTL", "OBC_CTL_FILE", "RIVER_CTL_FILE",
        ],
        "Output": [
            "NSTA", "NHIS", "NDEFHIS",
            "NQCK", "NDEFQCK", "NAVG", "NFLT", "NRST",
        ],
    }

    for category, keys in categories.items():
        lines.append(f"# {category}")
        for key in keys:
            if key in exports and exports[key] not in (None, ""):
                value = exports[key]
                lines.append(f"export {key}={value}")
        lines.append("")

    return "\n".join(lines)


_SECTIONS: Dict[str, List[str]] = {
    "domain": [
        "LONMIN", "LONMAX", "LATMIN", "LATMAX",
        "MINLON", "MAXLON", "MINLAT", "MAXLAT",
        "nvrt", "KBm", "np_global", "ne_global", "ns_global", "GRIDFILE",
    ],
    "model": ["OCEAN_MODEL", "DELT_MODEL", "NPROCS", "NSCRIBES"],
    "run": [
        "LEN_NOWCAST", "LEN_FORECAST", "N_DAYS_MODEL_RUN_PERIOD",
        "RNDAY_NOWCAST", "RNDAY_FORECAST",
        "PDYHH_NCAST_BEGIN", "PDYHH_FCAST_BEGIN",
        "time_nowcastend", "time_forecastend",
    ],
    "forcing": [
        "DBASE_MET_NOW", "DBASE_MET_FOR",
        "DBASE_WL_NOW", "DBASE_WL_FOR",
        "DBASE_TS_NOW", "DBASE_TS_FOR",
        "CREATE_TIDEFORCING",
    ],
    "paths": [
        "HOMEnos", "HOMEstofs", "FIXofs", "FIXstofs3d",
        "DATA", "COMOUT",
        "COMINgfs", "COMINhrrr", "COMINrtofs", "COMINnwm",
    ],
}


def filter_by_section(exports: Dict[str, Any], section: str) -> Dict[str, Any]:
    """Return the subset of ``exports`` that belongs to ``section``."""
    if section not in _SECTIONS:
        return exports
    section_vars = set(_SECTIONS[section])
    return {k: v for k, v in exports.items() if k in section_vars}


def export_for_shell(
    config_path: Union[str, Path],
    section: Optional[str] = None,
    output_format: str = "shell",
    framework: str = "auto",
) -> str:
    """Top-level helper: load YAML, merge bases, format exports."""
    config_path = Path(config_path)

    if config_path.parent.name == "systems":
        base_dir = config_path.parent.parent
    else:
        base_dir = config_path.parent

    data = load_yaml_with_inheritance(config_path, base_dir)

    exports = export_shell_mappings(data, framework)

    if section:
        exports = filter_by_section(exports, section)

    if output_format == "json":
        return format_json(exports)
    if output_format == "ctl":
        system_name = data.get("system", {}).get("name", "unknown")
        return format_ctl_file(exports, system_name)
    return format_shell_exports(exports)


def export_env(
    yaml_path: Union[str, Path],
    framework: str = "auto",
    output_format: str = "shell",
    section: Optional[str] = None,
) -> str:
    """Cleaner alias for :func:`export_for_shell`."""
    return export_for_shell(
        config_path=yaml_path,
        section=section,
        output_format=output_format,
        framework=framework,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m nos_workflow.utils.yaml_to_env",
        description="Export YAML config values as shell environment variables.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  eval $(nos_uw env --ofs secofs_ufs --shell)

  eval $(python -m nos_workflow.utils.yaml_to_env \\
      --config parm/systems/secofs_ufs.yaml --framework comf)

  eval $(python -m nos_workflow.utils.yaml_to_env \\
      --config parm/systems/stofs_3d_atl.yaml --section domain)

  python -m nos_workflow.utils.yaml_to_env \\
      --config parm/systems/secofs_ufs.yaml --format ctl > secofs_ufs.ctl

Available sections:
  domain   - Grid bounds and dimensions
  model    - Model type and physics
  run      - Run length and time boundaries
  forcing  - Forcing data sources
  paths    - Directory paths

Frameworks:
  auto    - Auto-detect from system.framework in YAML
  stofs   - STOFS (stofs_3d_atl, stofs_3d_pac)
  comf    - nosofs / COMF (secofs, secofs_ufs, leofs, cbofs, ...)
  adcirc  - STOFS-2D-GLO (ADCIRC)
""",
    )

    parser.add_argument(
        "config_file",
        nargs="?",
        default=None,
        help="path to YAML configuration file (positional)",
    )
    parser.add_argument(
        "-c", "--config",
        dest="config_kw",
        default=None,
        help="path to YAML configuration file (keyword form, preferred)",
    )
    parser.add_argument(
        "-s", "--section",
        choices=sorted(_SECTIONS.keys()),
        help="export only the named section",
    )
    parser.add_argument(
        "-f", "--format",
        choices=["shell", "json", "ctl"],
        default="shell",
        help="output format (default: shell)",
    )
    parser.add_argument(
        "--framework",
        choices=["auto", "stofs", "comf", "adcirc"],
        default="auto",
        help="framework type (default: auto-detect)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"yaml_to_env {__version__}",
    )
    return parser


def _emit_error(reason: str, config_path: Optional[Path]) -> None:
    """Emit a single structured error line on stderr."""
    cfg_repr = str(config_path) if config_path is not None else "<unset>"
    print(
        f"ERROR: yaml_to_env: {reason} (config={cfg_repr})",
        file=sys.stderr,
    )
    if os.environ.get("NOS_WORKFLOW_DEBUG") == "1":
        import traceback as _tb
        _tb.print_exc(file=sys.stderr)


def main(argv: Optional[List[str]] = None) -> int:
    """argparse entry point."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    config_arg = args.config_kw or args.config_file
    if not config_arg:
        parser.error("a config path is required (use --config <path> or pass it positionally)")

    config_path = Path(config_arg)
    if not config_path.exists():
        _emit_error(f"config file not found: {config_path}", config_path)
        return 1

    try:
        output = export_for_shell(
            config_path=config_path,
            section=args.section,
            output_format=args.format,
            framework=args.framework,
        )
    except Exception as exc:  # noqa: BLE001
        _emit_error(f"{type(exc).__name__}: {exc}", config_path)
        return 1

    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "load_yaml_with_inheritance",
    "deep_merge",
    "get_nested_value",
    "compute_derived_values",
    "get_runtime_from_env",
    "export_shell_mappings",
    "get_standard_exports",
    "format_shell_exports",
    "format_json",
    "format_ctl_file",
    "export_for_shell",
    "export_env",
    "filter_by_section",
    "main",
]
