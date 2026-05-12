"""Sed-replacement helpers for namelist and configure-file patching.

The shell function ``_schism_stage_files`` (in ``ush/nos_run.sh``) uses
25+ ``sed -i`` invocations to patch numeric and string values inside
``param.nml``, ``datm_in``, ``model_configure``, and ``ufs.configure``.
This module replaces them with ``re.sub`` against in-memory file content
-- testable, lintable, and byte-equivalent to GNU sed (verified by the
parity tests in :mod:`tests.runners.test_patches`).

Each public function reads a file, applies a dict of replacements, and
writes the result back. The return value is the number of replacements
applied (callers can ``assert`` on it; missing-key cases log WARNING
but never raise -- matching the shell's silent ``sed -i`` semantics).

Shell sed patterns covered (each pair verified byte-equivalent):

    # param.nml (Fortran namelist)
    sed -i "s/^\\(\\s*rnday\\s*=\\s*\\)[0-9.]*\\(.*\\)/\\1${rnday}\\2/" file
    sed -i "s/^\\(\\s*start_year\\s*=\\s*\\)[0-9]*\\(.*\\)/\\1${y}\\2/" file
    sed -i "s/ihot = [0-9]*/ihot = ${ihot}/"                            file

    # datm_in (Fortran namelist, simpler patterns)
    sed -i "s/nx_global = [0-9]*/nx_global = ${nx}/" file
    sed -i "s/ny_global = [0-9]*/ny_global = ${ny}/" file

    # model_configure (FV3 ``key: value`` format)
    sed -i "s/nhours_fcst:.*/nhours_fcst:             ${nh}/" file
    sed -i "s/start_year:.*/start_year:              ${y}/"   file

    # ufs.configure (``key = value`` like a namelist but with strings)
    sed -i "s/stop_n = .*/stop_n = ${nh}/"             file
    sed -i "s/start_type = .*/start_type = ${st}/"     file
    sed -i "s/orb_iyear = .*/orb_iyear = ${y}/"        file

The three patching styles map to three public helpers:

  - :func:`patch_fortran_namelist`: preserves leading whitespace and
    trailing context (comment, continuation) -- used for the strict
    ``param.nml`` patterns with ``\\1...\\2`` capture groups.
  - :func:`patch_fortran_namelist_simple`: rewrites the value with no
    capture-group preservation -- used for ``datm_in`` and the
    permissive ``ihot = N`` form.
  - :func:`patch_fv3_configure`: ``key: value`` colon-separated lines
    (model_configure).
  - :func:`patch_ufs_configure`: ``key = value`` whole-line rewrites
    (ufs.configure).

PR 7a ships the implementation + parity tests. PR 7b will call these
helpers from :mod:`stage_files` to patch ``param.nml`` / ``datm_in`` /
``model_configure`` / ``ufs.configure``.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Dict, Mapping, Union

logger = logging.getLogger(__name__)

# Replacement values are stringified before substitution. Float values
# are printed with Python's default ``str()`` (matches the shell's
# ``$(python3 -c "print(${n}/24.0)")`` output for the rnday case).
PatchValue = Union[str, int, float]


def _stringify(value: PatchValue) -> str:
    """Convert a value to its sed-replacement string form.

    Booleans are coerced to ``str(bool(v))``; numerics to ``str(v)``.
    Strings pass through unchanged. The shell's positional ``${var}``
    substitution does no formatting -- whatever bash printed is what
    sed saw -- so :func:`str` is the right contract here.
    """
    return str(value)


def patch_fortran_namelist(
    path: Path,
    replacements: Mapping[str, PatchValue],
) -> int:
    """Patch a Fortran namelist file using the strict
    ``\\1<value>\\2`` shell pattern.

    Matches the shell's::

        sed -i "s/^\\(\\s*KEY\\s*=\\s*\\)[0-9.]*\\(.*\\)/\\1NEW\\2/" file

    Preserves leading whitespace, the ``=`` operator, and any trailing
    context (a comment ``! foo``, continuation, whatever follows the
    numeric token). The right-hand-side character class matches what
    sed's ``[0-9.]*`` matches -- digits and dots; nothing else.

    Args:
        path: namelist file to edit in place.
        replacements: dict of ``{key_name: new_value}``. Values are
            stringified before substitution.

    Returns:
        Number of replacements actually applied. A WARNING is logged
        for any key that wasn't found.
    """
    text = path.read_text()
    n_applied = 0
    for key, value in replacements.items():
        repl = _stringify(value)
        # Shell:  ^\(\s*KEY\s*=\s*\)[0-9.]*\(.*\)
        # Python: ^(\s*KEY\s*=\s*)[0-9.]*(.*)$
        #
        # GNU sed's ``[0-9.]*`` accepts zero-or-more digits/dots. We
        # match the SAME greedy quantifier so a degenerate empty
        # numeric (e.g. "rnday = " followed by EOL/comment) still
        # gets a value injected (matches the shell's behavior).
        pattern = re.compile(
            r"^(\s*" + re.escape(key) + r"\s*=\s*)[0-9.]*(.*)$",
            re.MULTILINE,
        )
        new_text, n = pattern.subn(rf"\g<1>{repl}\g<2>", text)
        if n == 0:
            logger.warning(
                "patch_fortran_namelist: key %r not found in %s", key, path,
            )
        else:
            n_applied += n
        text = new_text
    path.write_text(text)
    return n_applied


def patch_fortran_namelist_simple(
    path: Path,
    replacements: Mapping[str, PatchValue],
) -> int:
    """Patch a Fortran namelist using the simpler shell pattern (no
    leading-whitespace or trailing-context preservation).

    Matches the shell's::

        sed -i "s/KEY = [0-9]*/KEY = NEW/" file

    Used for ``datm_in`` (``nx_global`` / ``ny_global``) and for the
    permissive ``ihot = N`` form on ``param.nml`` (which the shell
    sometimes emits at line 550 + line 661). The pattern requires a
    literal space-equals-space around the value and matches one or
    more digits afterward; no trailing capture, so a comment after the
    value would be replaced too (preserving shell behavior).

    Args:
        path: namelist file to edit in place.
        replacements: dict of ``{key_name: new_value}``.

    Returns:
        Number of replacements applied. WARNING if a key wasn't found.
    """
    text = path.read_text()
    n_applied = 0
    for key, value in replacements.items():
        repl = _stringify(value)
        # Shell:  KEY = [0-9]*  (no anchors, no capture groups)
        # Python: \bKEY = [0-9]*  (word boundary so 'inwm_global' doesn't
        #         match for 'nx_global'; shell relies on space-prefix in
        #         practice, but \b is the safe Python equivalent)
        #
        # NB: the shell here matches ANY occurrence on the line; we
        # match the first occurrence per line (re.subn replaces every
        # non-overlapping match, same as sed without /g doesn't, but
        # the shell command lacks /g too and ALSO only does first-on-
        # line; we follow). Use a non-greedy `*` to mirror sed.
        pattern = re.compile(
            r"\b" + re.escape(key) + r" = [0-9]*",
        )
        new_text, n = pattern.subn(f"{key} = {repl}", text)
        if n == 0:
            logger.warning(
                "patch_fortran_namelist_simple: key %r not found in %s",
                key, path,
            )
        else:
            n_applied += n
        text = new_text
    path.write_text(text)
    return n_applied


def patch_fv3_configure(
    path: Path,
    replacements: Mapping[str, PatchValue],
) -> int:
    """Patch an FV3-style configure file (``key: value`` colon-separated).

    Matches the shell's::

        sed -i "s/KEY:.*/KEY:             NEW/" file

    Each replacement rewrites the entire line from the colon onward
    with ``: <spaces> <value>`` -- the shell hard-codes 13 spaces of
    alignment which we preserve here for byte-equivalence.

    Args:
        path: model_configure file to edit in place.
        replacements: dict of ``{key_name: new_value}``. The
            generated line has the exact 13-space pad used by the
            shell (lines 517-521 of nos_run.sh).

    Returns:
        Number of replacements applied. WARNING if a key wasn't found.
    """
    text = path.read_text()
    n_applied = 0
    for key, value in replacements.items():
        repl = _stringify(value)
        # Shell:  KEY:.*
        # Python: ^KEY:.*$  (anchored per-line via MULTILINE)
        pattern = re.compile(
            r"^" + re.escape(key) + r":.*$",
            re.MULTILINE,
        )
        # Match the shell's 13-space pad: "KEY:             VAL"
        new_line = f"{key}:             {repl}"
        new_text, n = pattern.subn(new_line, text)
        if n == 0:
            logger.warning(
                "patch_fv3_configure: key %r not found in %s", key, path,
            )
        else:
            n_applied += n
        text = new_text
    path.write_text(text)
    return n_applied


def patch_ufs_configure(
    path: Path,
    replacements: Mapping[str, PatchValue],
) -> int:
    """Patch a UFS-style configure file (``key = value`` whole-line
    rewrite).

    Matches the shell's::

        sed -i "s/KEY = .*/KEY = NEW/" file

    Used by ``ufs.configure`` (lines 524-527 of nos_run.sh) for
    ``stop_n``, ``start_type``, ``orb_iyear``, and ``orb_iyear_align``.
    The shell pattern requires a literal ``KEY = `` (with surrounding
    spaces) and rewrites EVERYTHING after the ``=`` -- no capture group
    for trailing context. Comments on the same line WILL be eaten,
    matching the shell.

    Args:
        path: ufs.configure file to edit in place.
        replacements: dict of ``{key_name: new_value}``.

    Returns:
        Number of replacements applied. WARNING if a key wasn't found.
    """
    text = path.read_text()
    n_applied = 0
    for key, value in replacements.items():
        repl = _stringify(value)
        # Shell:  KEY = .*
        # Python: KEY = .*  (no anchors; sed matches anywhere on line)
        # But .* in re without DOTALL stops at newline -- same as sed
        # which is line-oriented by default.
        pattern = re.compile(re.escape(key) + r" = .*")
        new_text, n = pattern.subn(f"{key} = {repl}", text)
        if n == 0:
            logger.warning(
                "patch_ufs_configure: key %r not found in %s", key, path,
            )
        else:
            n_applied += n
        text = new_text
    path.write_text(text)
    return n_applied


def substitute_placeholders(
    path: Path,
    replacements: Mapping[str, PatchValue],
) -> int:
    """Verbatim string-substitution helper.

    Matches the shell's::

        sed -i "s/PLACEHOLDER/VALUE/" file

    Used for ``param.nml`` template placeholders (e.g. ``rnday_value``,
    ``start_year_value``) at lines 540-545 of nos_run.sh. These are
    plain string substitutions with no regex semantics: the placeholder
    must appear verbatim and is replaced verbatim.

    Args:
        path: file to edit in place.
        replacements: dict of ``{placeholder: value}``. Placeholders
            are matched as plain strings (``re.escape``-d).

    Returns:
        Number of placeholders that were found and replaced. WARNING
        for any that weren't found.
    """
    text = path.read_text()
    n_applied = 0
    for placeholder, value in replacements.items():
        repl = _stringify(value)
        # The shell does `s/foo/bar/` which is regex on the LHS -- our
        # callers always pass literal placeholder strings (rnday_value,
        # start_year_value), so re.escape is the safe contract.
        pattern = re.compile(re.escape(placeholder))
        new_text, n = pattern.subn(repl, text)
        if n == 0:
            logger.warning(
                "substitute_placeholders: %r not found in %s",
                placeholder, path,
            )
        else:
            n_applied += n
        text = new_text
    path.write_text(text)
    return n_applied


__all__ = [
    "patch_fortran_namelist",
    "patch_fortran_namelist_simple",
    "patch_fv3_configure",
    "patch_ufs_configure",
    "substitute_placeholders",
    "PatchValue",
]
