"""Sed-replacement helpers for namelist and configure-file patching."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Dict, Mapping, Union

logger = logging.getLogger(__name__)

PatchValue = Union[str, int, float]


def _stringify(value: PatchValue) -> str:
    """Convert a value to its sed-replacement string form."""
    return str(value)


def patch_fortran_namelist(
    path: Path,
    replacements: Mapping[str, PatchValue],
) -> int:
    """Patch a Fortran namelist using the strict ``\\1<value>\\2`` pattern.

    Preserves leading whitespace, the ``=`` operator, and any trailing
    comment/context. Returns the number of replacements applied.
    """
    text = path.read_text()
    n_applied = 0
    for key, value in replacements.items():
        repl = _stringify(value)
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
    """Patch a Fortran namelist using ``KEY = [0-9]*`` (no whitespace preservation).

    Used for datm_in keys and the permissive ihot form. Returns the number
    of replacements applied.
    """
    text = path.read_text()
    n_applied = 0
    for key, value in replacements.items():
        repl = _stringify(value)
        # \b word boundary prevents 'inwm_global' matching for 'nx_global'.
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
    """Patch an FV3-style configure file (``key:             value``).

    The 13-space pad is preserved verbatim from the shell. Returns the
    number of replacements applied.
    """
    text = path.read_text()
    n_applied = 0
    for key, value in replacements.items():
        repl = _stringify(value)
        pattern = re.compile(
            r"^" + re.escape(key) + r":.*$",
            re.MULTILINE,
        )
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
    """Patch a UFS-style configure file (``key = value`` whole-line rewrite)."""
    text = path.read_text()
    n_applied = 0
    for key, value in replacements.items():
        repl = _stringify(value)
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
    """Verbatim string substitution (placeholder -> value)."""
    text = path.read_text()
    n_applied = 0
    for placeholder, value in replacements.items():
        repl = _stringify(value)
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
