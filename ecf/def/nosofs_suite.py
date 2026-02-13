#!/usr/bin/env python3
"""
NOS-OFS Unified ecFlow Suite Definition

Generates the ecFlow suite for all NOS-OFS systems under a single nosofs suite.
Supports three workflow patterns:
  - STOFS:  prep -> nowcst_fcst -> post_1 -> post_2
  - COMF:   prep -> nowcast -> forecast -> post
  - ADCIRC: prep -> nowcast -> forecast -> post

Usage:
    # Generate .def text file:
    python nosofs_suite.py --output nosofs.def

    # Generate text-only (no ecflow module required):
    python nosofs_suite.py --text-only --output nosofs.def

    # Load directly into ecFlow server:
    ecflow_client --load nosofs_suite.py

    # Generate and replace existing suite:
    python nosofs_suite.py --output nosofs.def
    ecflow_client --replace /nosofs nosofs.def

Environment:
    PACKAGEROOT  - Package installation root
    NOSOFS_VER   - Package version (e.g., v3.7.0)
    ECF_FILES    - Path to .ecf script files (auto-derived from PACKAGEROOT)
    ECF_INCLUDE  - Path to ecFlow include headers
"""

import argparse
import sys

try:
    import ecflow
except ImportError:
    ecflow = None
    print(
        "WARNING: ecflow Python module not available. "
        "Falling back to text-based .def generation.",
        file=sys.stderr,
    )


# ---------------------------------------------------------------------------
# OFS System Definitions
# ---------------------------------------------------------------------------
# Each entry defines one OFS system with its framework type, network
# identifier, cycle hours, version file relative path, and PBS resource
# requirements per task.  Resources are tuples of (select_stmt, walltime).

OFS_SYSTEMS = [
    # --- STOFS Framework (combined nowcst_fcst) ---
    {
        "name": "stofs_3d_atl",
        "framework": "stofs",
        "net": "stofs",
        "cycles": ["12"],
        "ver_file": "stofs_3d_atl/run.ver",
        "resources": {
            "prep":        ("select=1:ncpus=8:mpiprocs=8",      "01:30:00"),
            "nowcst_fcst": ("select=20:ncpus=128:mpiprocs=120", "06:00:00"),
            "post_1":      ("select=1:ncpus=8:mpiprocs=8",      "01:00:00"),
            "post_2":      ("select=1:ncpus=8:mpiprocs=8",      "01:00:00"),
        },
    },
    {
        "name": "stofs_3d_pac",
        "framework": "stofs",
        "net": "stofs",
        "cycles": ["12"],
        "ver_file": "stofs_3d_pac/run.ver",
        "resources": {
            "prep":        ("select=1:ncpus=8:mpiprocs=8",      "01:30:00"),
            "nowcst_fcst": ("select=20:ncpus=128:mpiprocs=120", "06:00:00"),
            "post_1":      ("select=1:ncpus=8:mpiprocs=8",      "01:00:00"),
            "post_2":      ("select=1:ncpus=8:mpiprocs=8",      "01:00:00"),
        },
    },
    # --- ADCIRC Framework (split nowcast/forecast) ---
    {
        "name": "stofs_2d_glo",
        "framework": "adcirc",
        "net": "stofs",
        "cycles": ["00", "06", "12", "18"],
        "ver_file": "run.ver",
        "resources": {
            "prep":     ("select=1:ncpus=8:mpiprocs=8",      "02:00:00"),
            "nowcast":  ("select=8:ncpus=128:mpiprocs=120",   "03:00:00"),
            "forecast": ("select=8:ncpus=128:mpiprocs=120",   "03:00:00"),
            "post":     ("select=1:ncpus=8:mpiprocs=8",       "01:00:00"),
        },
    },
    # --- COMF Framework (split nowcast/forecast) ---
    {
        "name": "secofs",
        "framework": "comf",
        "net": "nosofs",
        "cycles": ["00", "06", "12", "18"],
        "ver_file": "run.ver",
        "resources": {
            "prep":     ("select=1:ncpus=8:mpiprocs=8",       "02:00:00"),
            "nowcast":  ("select=10:ncpus=128:mpiprocs=120",   "01:30:00"),
            "forecast": ("select=10:ncpus=128:mpiprocs=120",   "05:30:00"),
            "post":     ("select=1:ncpus=8:mpiprocs=8",        "01:00:00"),
        },
    },
    {
        "name": "creofs",
        "framework": "comf",
        "net": "nosofs",
        "cycles": ["03", "09", "15", "21"],
        "ver_file": "run.ver",
        "resources": {
            "prep":     ("select=1:ncpus=8:mpiprocs=8",       "02:00:00"),
            "nowcast":  ("select=10:ncpus=128:mpiprocs=120",   "01:30:00"),
            "forecast": ("select=10:ncpus=128:mpiprocs=120",   "05:30:00"),
            "post":     ("select=1:ncpus=8:mpiprocs=8",        "01:00:00"),
        },
    },
    {
        "name": "cbofs",
        "framework": "comf",
        "net": "nosofs",
        "cycles": ["00", "06", "12", "18"],
        "ver_file": "run.ver",
        "resources": {
            "prep":     ("select=1:ncpus=8:mpiprocs=8",      "02:00:00"),
            "nowcast":  ("select=3:ncpus=128:mpiprocs=120",   "01:00:00"),
            "forecast": ("select=3:ncpus=128:mpiprocs=120",   "01:00:00"),
            "post":     ("select=1:ncpus=8:mpiprocs=8",       "01:00:00"),
        },
    },
    {
        "name": "dbofs",
        "framework": "comf",
        "net": "nosofs",
        "cycles": ["00", "06", "12", "18"],
        "ver_file": "run.ver",
        "resources": {
            "prep":     ("select=1:ncpus=8:mpiprocs=8",      "02:00:00"),
            "nowcast":  ("select=3:ncpus=128:mpiprocs=120",   "01:00:00"),
            "forecast": ("select=3:ncpus=128:mpiprocs=120",   "01:00:00"),
            "post":     ("select=1:ncpus=8:mpiprocs=8",       "01:00:00"),
        },
    },
    {
        "name": "leofs",
        "framework": "comf",
        "net": "nosofs",
        "cycles": ["00", "06", "12", "18"],
        "ver_file": "run.ver",
        "resources": {
            "prep":     ("select=1:ncpus=8:mpiprocs=8",      "02:00:00"),
            "nowcast":  ("select=3:ncpus=128:mpiprocs=120",   "01:00:00"),
            "forecast": ("select=3:ncpus=128:mpiprocs=120",   "01:00:00"),
            "post":     ("select=1:ncpus=8:mpiprocs=8",       "01:00:00"),
        },
    },
    {
        "name": "ngofs2",
        "framework": "comf",
        "net": "nosofs",
        "cycles": ["00", "06", "12", "18"],
        "ver_file": "run.ver",
        "resources": {
            "prep":     ("select=1:ncpus=8:mpiprocs=8",      "02:00:00"),
            "nowcast":  ("select=3:ncpus=128:mpiprocs=120",   "01:00:00"),
            "forecast": ("select=3:ncpus=128:mpiprocs=120",   "01:00:00"),
            "post":     ("select=1:ncpus=8:mpiprocs=8",       "01:00:00"),
        },
    },
]

# Maximum concurrent jobs across the entire suite (prevents PBS queue overload)
MAX_JOBS = 20


# ---------------------------------------------------------------------------
# ecflow Python API suite builder
# ---------------------------------------------------------------------------

def create_suite_api():
    """Build the nosofs suite using the ecflow Python API."""
    if ecflow is None:
        raise RuntimeError("ecflow module required. Use --text-only instead.")

    defs = ecflow.Defs()
    suite = defs.add_suite("nosofs")

    # Suite-level variables (inherited by all children)
    suite.add_variable("ENVIR", "prod")
    suite.add_variable("PACKAGEROOT", "/lfs/h1/nos/nosofs/noscrub/packages")
    suite.add_variable("NOSOFS_VER", "v3.7.0")
    suite.add_variable("COMROOT", "/lfs/h1/ops/prod/com")
    suite.add_variable("DCOMROOT", "/lfs/h1/ops/prod/dcom")
    suite.add_variable("KEEPDATA", "NO")
    suite.add_variable("SENDCOM", "YES")
    suite.add_variable("SENDDBN", "YES")
    suite.add_variable("ECF_FILES",
                       "%PACKAGEROOT%/nosofs.%NOSOFS_VER%/ecf")
    suite.add_variable("ECF_INCLUDE",
                       "%PACKAGEROOT%/nosofs.%NOSOFS_VER%/ecf/include")
    suite.add_variable("ECF_TRIES", "2")

    # Global job limit
    suite.add_limit(ecflow.Limit("max_jobs", MAX_JOBS))

    # Build one family per OFS system
    for ofs in OFS_SYSTEMS:
        ofs_fam = suite.add_family(ofs["name"])
        ofs_fam.add_variable("OFS", ofs["name"])
        ofs_fam.add_variable("NET", ofs["net"])
        ofs_fam.add_variable("VER_FILE", ofs["ver_file"])

        # Sub-family per cycle hour (independent scheduling)
        for cyc in ofs["cycles"]:
            cyc_fam = ofs_fam.add_family("cyc{}".format(cyc))
            cyc_fam.add_variable("CYC", cyc)

            cron = ecflow.Cron()
            cron.set_time_series("{}:00".format(int(cyc)))
            cyc_fam.add_cron(cron)

            if ofs["framework"] == "stofs":
                _add_stofs_tasks(cyc_fam, ofs)
            else:
                _add_comf_tasks(cyc_fam, ofs)

    return defs


def _add_stofs_tasks(fam, ofs):
    """STOFS chain: prep -> nowcst_fcst -> post_1 -> post_2"""
    res = ofs["resources"]

    t = fam.add_task("prep")
    t.add_variable("ECF_JOB_CMD", "%ECF_FILES%/jnos_ofs_prep.ecf")
    t.add_variable("RESOURCES", res["prep"][0])
    t.add_variable("WALLTIME", res["prep"][1])
    t.add_inlimit("max_jobs")

    t = fam.add_task("nowcst_fcst")
    t.add_variable("ECF_JOB_CMD", "%ECF_FILES%/jnos_ofs_nowcst_fcst.ecf")
    t.add_variable("RESOURCES", res["nowcst_fcst"][0])
    t.add_variable("WALLTIME", res["nowcst_fcst"][1])
    t.add_trigger("prep == complete")
    t.add_inlimit("max_jobs")

    t = fam.add_task("post_1")
    t.add_variable("ECF_JOB_CMD", "%ECF_FILES%/jnos_ofs_post.ecf")
    t.add_variable("RESOURCES", res["post_1"][0])
    t.add_variable("WALLTIME", res["post_1"][1])
    t.add_variable("POST_STAGE", "1")
    t.add_trigger("nowcst_fcst == complete")
    t.add_inlimit("max_jobs")

    t = fam.add_task("post_2")
    t.add_variable("ECF_JOB_CMD", "%ECF_FILES%/jnos_ofs_post.ecf")
    t.add_variable("RESOURCES", res["post_2"][0])
    t.add_variable("WALLTIME", res["post_2"][1])
    t.add_variable("POST_STAGE", "2")
    t.add_trigger("post_1 == complete")
    t.add_inlimit("max_jobs")


def _add_comf_tasks(fam, ofs):
    """COMF/ADCIRC chain: prep -> nowcast -> forecast -> post"""
    res = ofs["resources"]

    t = fam.add_task("prep")
    t.add_variable("ECF_JOB_CMD", "%ECF_FILES%/jnos_ofs_prep.ecf")
    t.add_variable("RESOURCES", res["prep"][0])
    t.add_variable("WALLTIME", res["prep"][1])
    t.add_inlimit("max_jobs")

    t = fam.add_task("nowcast")
    t.add_variable("ECF_JOB_CMD", "%ECF_FILES%/jnos_ofs_nowcast.ecf")
    t.add_variable("RESOURCES", res["nowcast"][0])
    t.add_variable("WALLTIME", res["nowcast"][1])
    t.add_trigger("prep == complete")
    t.add_inlimit("max_jobs")

    t = fam.add_task("forecast")
    t.add_variable("ECF_JOB_CMD", "%ECF_FILES%/jnos_ofs_forecast.ecf")
    t.add_variable("RESOURCES", res["forecast"][0])
    t.add_variable("WALLTIME", res["forecast"][1])
    t.add_trigger("nowcast == complete")
    t.add_inlimit("max_jobs")

    t = fam.add_task("post")
    t.add_variable("ECF_JOB_CMD", "%ECF_FILES%/jnos_ofs_post.ecf")
    t.add_variable("RESOURCES", res["post"][0])
    t.add_variable("WALLTIME", res["post"][1])
    t.add_trigger("forecast == complete")
    t.add_inlimit("max_jobs")


# ---------------------------------------------------------------------------
# Plain text .def generation (no ecflow module required)
# ---------------------------------------------------------------------------

def _indent(level):
    """Return indentation string for the given nesting level."""
    return "  " * level


def create_suite_text():
    """Generate the nosofs suite as a plain text .def string."""
    lines = []

    lines.append("suite nosofs")
    lines.append("  # -----------------------------------------------------------")
    lines.append("  # Suite-level variables (inherited by all families and tasks)")
    lines.append("  # -----------------------------------------------------------")
    lines.append("  edit ENVIR 'prod'")
    lines.append("  edit PACKAGEROOT '/lfs/h1/nos/nosofs/noscrub/packages'")
    lines.append("  edit NOSOFS_VER 'v3.7.0'")
    lines.append("  edit COMROOT '/lfs/h1/ops/prod/com'")
    lines.append("  edit DCOMROOT '/lfs/h1/ops/prod/dcom'")
    lines.append("  edit KEEPDATA 'NO'")
    lines.append("  edit SENDCOM 'YES'")
    lines.append("  edit SENDDBN 'YES'")
    lines.append("  edit ECF_FILES '%PACKAGEROOT%/nosofs.%NOSOFS_VER%/ecf'")
    lines.append("  edit ECF_INCLUDE '%PACKAGEROOT%/nosofs.%NOSOFS_VER%/ecf/include'")
    lines.append("  edit ECF_TRIES '2'")
    lines.append("  limit max_jobs {}".format(MAX_JOBS))
    lines.append("")

    for ofs in OFS_SYSTEMS:
        lines.append("  # ==========================================================")
        lines.append("  # {} ({} framework)".format(
            ofs["name"].upper(), ofs["framework"].upper()))
        lines.append("  # ==========================================================")
        lines.append("  family {}".format(ofs["name"]))
        lines.append("    edit OFS '{}'".format(ofs["name"]))
        lines.append("    edit NET '{}'".format(ofs["net"]))
        lines.append("    edit VER_FILE '{}'".format(ofs["ver_file"]))

        for cyc in ofs["cycles"]:
            lines.append("")
            lines.append("    family cyc{}".format(cyc))
            lines.append("      edit CYC '{}'".format(cyc))
            lines.append("      cron {}:00".format(int(cyc)))

            pfx = _indent(3)
            if ofs["framework"] == "stofs":
                r = ofs["resources"]
                for task, ecf, trig, extra in [
                    ("prep", "jnos_ofs_prep.ecf", None, None),
                    ("nowcst_fcst", "jnos_ofs_nowcst_fcst.ecf", "prep", None),
                    ("post_1", "jnos_ofs_post.ecf", "nowcst_fcst", "POST_STAGE '1'"),
                    ("post_2", "jnos_ofs_post.ecf", "post_1", "POST_STAGE '2'"),
                ]:
                    lines.append("")
                    lines.append("{}task {}".format(pfx, task))
                    lines.append("{}  edit ECF_JOB_CMD '%ECF_FILES%/{}'".format(pfx, ecf))
                    lines.append("{}  edit RESOURCES '{}'".format(pfx, r[task][0]))
                    lines.append("{}  edit WALLTIME '{}'".format(pfx, r[task][1]))
                    if extra:
                        lines.append("{}  edit {}".format(pfx, extra))
                    if trig:
                        lines.append("{}  trigger {} == complete".format(pfx, trig))
                    lines.append("{}  inlimit /nosofs:max_jobs".format(pfx))
            else:
                r = ofs["resources"]
                for task, ecf, trig in [
                    ("prep", "jnos_ofs_prep.ecf", None),
                    ("nowcast", "jnos_ofs_nowcast.ecf", "prep"),
                    ("forecast", "jnos_ofs_forecast.ecf", "nowcast"),
                    ("post", "jnos_ofs_post.ecf", "forecast"),
                ]:
                    lines.append("")
                    lines.append("{}task {}".format(pfx, task))
                    lines.append("{}  edit ECF_JOB_CMD '%ECF_FILES%/{}'".format(pfx, ecf))
                    lines.append("{}  edit RESOURCES '{}'".format(pfx, r[task][0]))
                    lines.append("{}  edit WALLTIME '{}'".format(pfx, r[task][1]))
                    if trig:
                        lines.append("{}  trigger {} == complete".format(pfx, trig))
                    lines.append("{}  inlimit /nosofs:max_jobs".format(pfx))

            lines.append("    endfamily")

        lines.append("  endfamily")
        lines.append("")

    lines.append("endsuite")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_suite(defs):
    """Run ecFlow built-in validation and print results."""
    result = defs.check()
    if result:
        print("Suite validation warnings/errors:")
        print(result)
    else:
        print("Suite validation passed (no errors).")
    return result


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="NOS-OFS Unified ecFlow Suite Definition Generator"
    )
    parser.add_argument(
        "--output", "-o", default="nosofs.def",
        help="Output .def file path (default: nosofs.def)",
    )
    parser.add_argument(
        "--text-only", action="store_true",
        help="Generate plain text .def without requiring ecflow module",
    )
    parser.add_argument(
        "--validate", action="store_true",
        help="Validate the suite after generation (requires ecflow module)",
    )
    args = parser.parse_args()

    if args.text_only or ecflow is None:
        print("Generating suite definition as plain text...")
        def_text = create_suite_text()
        with open(args.output, "w") as fh:
            fh.write(def_text)
        print("Wrote {}".format(args.output))
    else:
        print("Generating suite definition using ecflow Python API...")
        defs = create_suite_api()
        if args.validate:
            validate_suite(defs)
        print(defs)
        defs.save_as_defs(args.output)
        print("Wrote {}".format(args.output))

    return 0


if __name__ == "__main__":
    sys.exit(main())
