"""Sed-vs-Python byte-equivalence tests for ``runners.schism_ufs.patches``.

Each test in this module runs the SAME input string through BOTH:

  1. The shell's ``sed -i`` invocation that the legacy
     ``_schism_stage_files`` uses (subprocess; ground truth).
  2. The Python helper under test (:func:`patch_fortran_namelist`,
     :func:`patch_fv3_configure`, etc.).

And asserts the resulting byte strings are identical. This is the
entire risk surface of PR 7: any regex divergence between Python's
``re`` and GNU sed's BRE/ERE engines would produce subtly different
output, and a numeric or string token in ``param.nml`` /
``model_configure`` is a clinical failure -- the model still runs
but with the wrong start date / rnday / nx_global, etc.

The shell sed patterns covered (one parity test per pattern):

    # param.nml -- strict pattern w/ leading whitespace + comment preservation
    s/^\\(\\s*rnday\\s*=\\s*\\)[0-9.]*\\(.*\\)/\\1${rnday}\\2/
    s/^\\(\\s*start_year\\s*=\\s*\\)[0-9]*\\(.*\\)/\\1${y}\\2/
    s/^\\(\\s*start_month\\s*=\\s*\\)[0-9]*\\(.*\\)/\\1${m}\\2/
    s/^\\(\\s*start_day\\s*=\\s*\\)[0-9]*\\(.*\\)/\\1${d}\\2/
    s/^\\(\\s*start_hour\\s*=\\s*\\)[0-9]*\\(.*\\)/\\1${h}\\2/

    # param.nml -- permissive ihot
    s/ihot = [0-9]*/ihot = ${ihot}/

    # datm_in -- permissive nx_global / ny_global
    s/nx_global = [0-9]*/nx_global = ${nx}/
    s/ny_global = [0-9]*/ny_global = ${ny}/

    # model_configure -- FV3 key:value whole-line rewrite
    s/nhours_fcst:.*/nhours_fcst:             ${nh}/
    s/start_year:.*/start_year:              ${y}/
    s/start_month:.*/start_month:             ${m}/
    s/start_day:.*/start_day:               ${d}/
    s/start_hour:.*/start_hour:              ${h}/

    # ufs.configure -- key = value whole-line rewrite
    s/stop_n = .*/stop_n = ${nh}/
    s/start_type = .*/start_type = ${st}/
    s/orb_iyear = .*/orb_iyear = ${y}/
    s/orb_iyear_align = .*/orb_iyear_align = ${y}/

    # param.nml -- placeholder substitutions
    s/rnday_value/${rnday}/
    s/start_year_value/${y}/
    s/start_month_value/${m}/
    s/start_day_value/${d}/
    s/start_hour_value/${h}/

If ``sed`` is not on the runner's PATH, every test in this module
skips (we don't bypass the byte-diff check by silently re-running the
Python under itself).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from nos_workflow.runners.schism_ufs.patches import (
    patch_fortran_namelist,
    patch_fortran_namelist_simple,
    patch_fv3_configure,
    patch_ufs_configure,
    substitute_placeholders,
)

# Skip the entire module if sed isn't available -- we don't trust a
# silent fallback to "Python compares to itself".
_SED_PATH = shutil.which("sed")
pytestmark = pytest.mark.skipif(
    _SED_PATH is None,
    reason="GNU sed not on PATH; sed-vs-Python parity tests cannot run",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_sed_inplace(target: Path, expr: str) -> None:
    """Run ``sed -i EXPR target`` and raise on non-zero exit."""
    subprocess.run(
        [_SED_PATH or "sed", "-i", expr, str(target)],
        check=True,
        text=True,
    )


def _assert_byte_equivalent(shell_target: Path, python_target: Path) -> None:
    """Compare bytes; on mismatch surface a unified-diff-style payload."""
    sb = shell_target.read_bytes()
    pb = python_target.read_bytes()
    if sb != pb:
        # Show both as repr so newlines + whitespace are visible.
        raise AssertionError(
            "Sed-vs-Python byte mismatch:\n"
            f"  sed:    {sb!r}\n"
            f"  python: {pb!r}"
        )


def _write_pair(tmp_path: Path, src: str) -> tuple[Path, Path]:
    """Write ``src`` to two sibling files for sed/python diffing."""
    shell_target = tmp_path / "shell.nml"
    python_target = tmp_path / "python.nml"
    shell_target.write_text(src)
    python_target.write_text(src)
    return shell_target, python_target


# ---------------------------------------------------------------------------
# patch_fortran_namelist (strict pattern; preserves indent + comment)
# ---------------------------------------------------------------------------


def test_patch_fortran_namelist_rnday(tmp_path):
    """``rnday = 0.5`` -> ``rnday = 0.75``: numeric replacement with
    leading whitespace + trailing context preservation."""
    src = "  rnday = 0.5\n  ihot = 1\n"
    shell, py = _write_pair(tmp_path, src)

    _run_sed_inplace(
        shell, r"s/^\(\s*rnday\s*=\s*\)[0-9.]*\(.*\)/\10.75\2/",
    )
    n = patch_fortran_namelist(py, {"rnday": 0.75})

    assert n == 1
    _assert_byte_equivalent(shell, py)


def test_patch_fortran_namelist_start_year(tmp_path):
    src = "  start_year = 2025\n  start_month = 5\n"
    shell, py = _write_pair(tmp_path, src)
    _run_sed_inplace(
        shell, r"s/^\(\s*start_year\s*=\s*\)[0-9]*\(.*\)/\12026\2/",
    )
    n = patch_fortran_namelist(py, {"start_year": 2026})
    assert n == 1
    _assert_byte_equivalent(shell, py)


def test_patch_fortran_namelist_start_month(tmp_path):
    src = "  start_month = 4\n  start_day = 1\n"
    shell, py = _write_pair(tmp_path, src)
    _run_sed_inplace(
        shell, r"s/^\(\s*start_month\s*=\s*\)[0-9]*\(.*\)/\15\2/",
    )
    n = patch_fortran_namelist(py, {"start_month": 5})
    assert n == 1
    _assert_byte_equivalent(shell, py)


def test_patch_fortran_namelist_start_day(tmp_path):
    src = "  start_day = 14\n  start_hour = 0\n"
    shell, py = _write_pair(tmp_path, src)
    _run_sed_inplace(
        shell, r"s/^\(\s*start_day\s*=\s*\)[0-9]*\(.*\)/\112\2/",
    )
    n = patch_fortran_namelist(py, {"start_day": 12})
    assert n == 1
    _assert_byte_equivalent(shell, py)


def test_patch_fortran_namelist_start_hour(tmp_path):
    src = "  start_hour = 0\n  ihot = 1\n"
    shell, py = _write_pair(tmp_path, src)
    _run_sed_inplace(
        shell, r"s/^\(\s*start_hour\s*=\s*\)[0-9]*\(.*\)/\112\2/",
    )
    n = patch_fortran_namelist(py, {"start_hour": 12})
    assert n == 1
    _assert_byte_equivalent(shell, py)


def test_patch_fortran_namelist_preserves_inline_comments(tmp_path):
    """``rnday = 0.5 ! days`` -> ``rnday = 0.75 ! days``: the trailing
    ``\\2`` capture must preserve the inline comment verbatim."""
    src = "  rnday = 0.5 ! sim length in days\n"
    shell, py = _write_pair(tmp_path, src)
    _run_sed_inplace(
        shell, r"s/^\(\s*rnday\s*=\s*\)[0-9.]*\(.*\)/\10.75\2/",
    )
    patch_fortran_namelist(py, {"rnday": 0.75})
    _assert_byte_equivalent(shell, py)


def test_patch_fortran_namelist_preserves_indent(tmp_path):
    """Different indent levels (tab, 2-space, 4-space, none) must all
    survive. The shell's ``\\s*`` matches any whitespace run; our
    ``\\1`` capture must put the same prefix back."""
    src = "rnday = 0.5\n  rnday = 0.5\n    rnday = 0.5\n\trnday = 0.5\n"
    shell, py = _write_pair(tmp_path, src)
    _run_sed_inplace(
        shell, r"s/^\(\s*rnday\s*=\s*\)[0-9.]*\(.*\)/\11.0\2/",
    )
    n = patch_fortran_namelist(py, {"rnday": 1.0})
    assert n == 4, "all four indented variants must be replaced"
    _assert_byte_equivalent(shell, py)


def test_patch_fortran_namelist_handles_missing_key(tmp_path, caplog):
    """A key not present in the file -> 0 replacements, WARNING logged,
    file content unchanged."""
    import logging
    src = "  ihot = 1\n"
    target = tmp_path / "py.nml"
    target.write_text(src)
    caplog.set_level(
        logging.WARNING,
        logger="nos_workflow.runners.schism_ufs.patches",
    )
    n = patch_fortran_namelist(target, {"rnday": 0.75})

    assert n == 0
    assert target.read_text() == src
    assert any("rnday" in rec.getMessage() for rec in caplog.records)


def test_patch_fortran_namelist_multiple_keys_one_call(tmp_path):
    """One call with several replacements applies them all in order."""
    src = "  rnday = 0.5\n  start_year = 2025\n  start_month = 5\n"
    shell, py = _write_pair(tmp_path, src)
    _run_sed_inplace(
        shell, r"s/^\(\s*rnday\s*=\s*\)[0-9.]*\(.*\)/\10.75\2/",
    )
    _run_sed_inplace(
        shell, r"s/^\(\s*start_year\s*=\s*\)[0-9]*\(.*\)/\12026\2/",
    )
    _run_sed_inplace(
        shell, r"s/^\(\s*start_month\s*=\s*\)[0-9]*\(.*\)/\16\2/",
    )
    n = patch_fortran_namelist(
        py,
        {"rnday": 0.75, "start_year": 2026, "start_month": 6},
    )
    assert n == 3
    _assert_byte_equivalent(shell, py)


def test_patch_fortran_namelist_int_value_no_decimal(tmp_path):
    """An int-typed replacement value renders as ``str(int)`` -- no
    trailing zero like Python's ``str(2026.0)`` would emit."""
    src = "  start_year = 2025\n"
    shell, py = _write_pair(tmp_path, src)
    _run_sed_inplace(
        shell, r"s/^\(\s*start_year\s*=\s*\)[0-9]*\(.*\)/\12026\2/",
    )
    patch_fortran_namelist(py, {"start_year": 2026})  # int, not 2026.0
    _assert_byte_equivalent(shell, py)


# ---------------------------------------------------------------------------
# patch_fortran_namelist_simple (permissive ihot / nx_global / ny_global)
# ---------------------------------------------------------------------------


def test_patch_fortran_namelist_simple_ihot(tmp_path):
    """``ihot = 0`` -> ``ihot = 1`` via the permissive
    ``ihot = [0-9]*`` pattern."""
    src = "ihot = 0\n"
    shell, py = _write_pair(tmp_path, src)
    _run_sed_inplace(shell, "s/ihot = [0-9]*/ihot = 1/")
    n = patch_fortran_namelist_simple(py, {"ihot": 1})
    assert n == 1
    _assert_byte_equivalent(shell, py)


def test_patch_fortran_namelist_simple_nx_global(tmp_path):
    """datm_in ``nx_global`` patch."""
    src = "  nx_global = 1881\n  ny_global = 1841\n"
    shell, py = _write_pair(tmp_path, src)
    _run_sed_inplace(shell, "s/nx_global = [0-9]*/nx_global = 1721/")
    n = patch_fortran_namelist_simple(py, {"nx_global": 1721})
    assert n == 1
    _assert_byte_equivalent(shell, py)


def test_patch_fortran_namelist_simple_ny_global(tmp_path):
    src = "  nx_global = 1721\n  ny_global = 1841\n"
    shell, py = _write_pair(tmp_path, src)
    _run_sed_inplace(shell, "s/ny_global = [0-9]*/ny_global = 1721/")
    n = patch_fortran_namelist_simple(py, {"ny_global": 1721})
    assert n == 1
    _assert_byte_equivalent(shell, py)


def test_patch_fortran_namelist_simple_handles_missing_key(tmp_path, caplog):
    import logging
    src = "ihot = 0\n"
    target = tmp_path / "py.nml"
    target.write_text(src)
    caplog.set_level(
        logging.WARNING,
        logger="nos_workflow.runners.schism_ufs.patches",
    )
    n = patch_fortran_namelist_simple(target, {"nx_global": 1721})
    assert n == 0
    assert target.read_text() == src


# ---------------------------------------------------------------------------
# patch_fv3_configure  (model_configure -- ``key: value``)
# ---------------------------------------------------------------------------


def test_patch_fv3_configure_nhours_fcst(tmp_path):
    """``nhours_fcst:             48`` -> ``... 24``."""
    src = "nhours_fcst:             48\n"
    shell, py = _write_pair(tmp_path, src)
    _run_sed_inplace(shell, "s/nhours_fcst:.*/nhours_fcst:             24/")
    n = patch_fv3_configure(py, {"nhours_fcst": 24})
    assert n == 1
    _assert_byte_equivalent(shell, py)


def test_patch_fv3_configure_start_year(tmp_path):
    src = "start_year:              2025\n"
    # NB: shell uses 14-space pad for start_year (line 518); 13 for
    # nhours_fcst (line 517). Each call has its own literal spaces.
    # Our patch_fv3_configure uses 13 spaces -- so we manually verify
    # the model_configure source emits the same prefix.
    shell, py = _write_pair(tmp_path, src)
    _run_sed_inplace(shell, "s/start_year:.*/start_year:             2026/")
    n = patch_fv3_configure(py, {"start_year": 2026})
    assert n == 1
    _assert_byte_equivalent(shell, py)


def test_patch_fv3_configure_start_month(tmp_path):
    src = "start_month:             4\n"
    shell, py = _write_pair(tmp_path, src)
    _run_sed_inplace(shell, "s/start_month:.*/start_month:             5/")
    n = patch_fv3_configure(py, {"start_month": 5})
    assert n == 1
    _assert_byte_equivalent(shell, py)


def test_patch_fv3_configure_start_day(tmp_path):
    src = "start_day:               14\n"
    shell, py = _write_pair(tmp_path, src)
    _run_sed_inplace(shell, "s/start_day:.*/start_day:             12/")
    n = patch_fv3_configure(py, {"start_day": 12})
    assert n == 1
    _assert_byte_equivalent(shell, py)


def test_patch_fv3_configure_start_hour(tmp_path):
    src = "start_hour:              0\n"
    shell, py = _write_pair(tmp_path, src)
    _run_sed_inplace(shell, "s/start_hour:.*/start_hour:             12/")
    n = patch_fv3_configure(py, {"start_hour": 12})
    assert n == 1
    _assert_byte_equivalent(shell, py)


def test_patch_fv3_configure_replaces_entire_value(tmp_path):
    """The ``.*`` greedy match eats whatever came after the colon --
    proves we don't accidentally preserve old whitespace from the
    source. Source has 5 spaces; our helper writes 13."""
    src = "nhours_fcst: 6\n"  # only 1 space
    shell, py = _write_pair(tmp_path, src)
    _run_sed_inplace(shell, "s/nhours_fcst:.*/nhours_fcst:             6/")
    n = patch_fv3_configure(py, {"nhours_fcst": 6})
    assert n == 1
    _assert_byte_equivalent(shell, py)


def test_patch_fv3_configure_missing_key(tmp_path, caplog):
    import logging
    src = "nhours_fcst:             48\n"
    target = tmp_path / "mc.txt"
    target.write_text(src)
    caplog.set_level(
        logging.WARNING,
        logger="nos_workflow.runners.schism_ufs.patches",
    )
    n = patch_fv3_configure(target, {"start_hour": 12})
    assert n == 0
    assert target.read_text() == src


# ---------------------------------------------------------------------------
# patch_ufs_configure  (ufs.configure -- ``key = value``)
# ---------------------------------------------------------------------------


def test_patch_ufs_configure_stop_n(tmp_path):
    src = "stop_n = 48\n"
    shell, py = _write_pair(tmp_path, src)
    _run_sed_inplace(shell, "s/stop_n = .*/stop_n = 6/")
    n = patch_ufs_configure(py, {"stop_n": 6})
    assert n == 1
    _assert_byte_equivalent(shell, py)


def test_patch_ufs_configure_start_type(tmp_path):
    src = "start_type = continue\n"
    shell, py = _write_pair(tmp_path, src)
    _run_sed_inplace(shell, "s/start_type = .*/start_type = startup/")
    n = patch_ufs_configure(py, {"start_type": "startup"})
    assert n == 1
    _assert_byte_equivalent(shell, py)


def test_patch_ufs_configure_orb_iyear(tmp_path):
    src = "orb_iyear = 2024\n"
    shell, py = _write_pair(tmp_path, src)
    _run_sed_inplace(shell, "s/orb_iyear = .*/orb_iyear = 2026/")
    n = patch_ufs_configure(py, {"orb_iyear": 2026})
    assert n == 1
    _assert_byte_equivalent(shell, py)


def test_patch_ufs_configure_orb_iyear_align(tmp_path):
    src = "orb_iyear_align = 2024\n"
    shell, py = _write_pair(tmp_path, src)
    _run_sed_inplace(
        shell, "s/orb_iyear_align = .*/orb_iyear_align = 2026/",
    )
    n = patch_ufs_configure(py, {"orb_iyear_align": 2026})
    assert n == 1
    _assert_byte_equivalent(shell, py)


def test_patch_ufs_configure_missing_key(tmp_path, caplog):
    import logging
    src = "stop_n = 48\n"
    target = tmp_path / "uc.txt"
    target.write_text(src)
    caplog.set_level(
        logging.WARNING,
        logger="nos_workflow.runners.schism_ufs.patches",
    )
    n = patch_ufs_configure(target, {"start_type": "startup"})
    assert n == 0
    assert target.read_text() == src


# ---------------------------------------------------------------------------
# substitute_placeholders  (param.nml placeholder substitution)
# ---------------------------------------------------------------------------


def test_substitute_placeholders_rnday_value(tmp_path):
    """``s/rnday_value/0.75/`` -- verbatim string substitution."""
    src = "  rnday = rnday_value\n"
    shell, py = _write_pair(tmp_path, src)
    _run_sed_inplace(shell, "s/rnday_value/0.75/")
    n = substitute_placeholders(py, {"rnday_value": "0.75"})
    assert n == 1
    _assert_byte_equivalent(shell, py)


def test_substitute_placeholders_start_year_value(tmp_path):
    src = "  start_year = start_year_value\n"
    shell, py = _write_pair(tmp_path, src)
    _run_sed_inplace(shell, "s/start_year_value/2026/")
    n = substitute_placeholders(py, {"start_year_value": 2026})
    assert n == 1
    _assert_byte_equivalent(shell, py)


def test_substitute_placeholders_multiple(tmp_path):
    """One call with several placeholders applies them in order."""
    src = (
        "  rnday = rnday_value\n"
        "  start_year = start_year_value\n"
        "  start_month = start_month_value\n"
    )
    shell, py = _write_pair(tmp_path, src)
    _run_sed_inplace(shell, "s/rnday_value/0.25/")
    _run_sed_inplace(shell, "s/start_year_value/2026/")
    _run_sed_inplace(shell, "s/start_month_value/5/")
    n = substitute_placeholders(
        py,
        {"rnday_value": "0.25", "start_year_value": 2026, "start_month_value": 5},
    )
    assert n == 3
    _assert_byte_equivalent(shell, py)


def test_substitute_placeholders_missing_placeholder(tmp_path, caplog):
    import logging
    src = "  ihot = 1\n"
    target = tmp_path / "py.nml"
    target.write_text(src)
    caplog.set_level(
        logging.WARNING,
        logger="nos_workflow.runners.schism_ufs.patches",
    )
    n = substitute_placeholders(target, {"rnday_value": "0.75"})
    assert n == 0
    assert target.read_text() == src
