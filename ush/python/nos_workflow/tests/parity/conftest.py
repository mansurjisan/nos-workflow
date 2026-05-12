"""Shared fixtures for the shell-vs-Python parity test suite.

Each helper port (PR 2 onwards) asserts byte-equivalence between the
legacy ``ush/nos_run.sh`` shell function and its Python replacement.
These fixtures un-tar captured ``$DATA`` / ``$COMOUT`` snapshots from
real SECOFS-UFS cycles on demand.

PR 1 ships this module empty — fixtures appear as individual helpers
are ported.
"""
from __future__ import annotations
