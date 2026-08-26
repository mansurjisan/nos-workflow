"""Shared pytest fixtures for nos_workflow tests.

Memory: tests have leaked NCO env vars between cases more than once.
The autouse ``clean_env`` fixture snapshots the relevant variables,
unsets them for the test body, and restores whatever the host shell had
when the suite started.
"""
from __future__ import annotations

import os
from typing import Iterator

import pytest

_TRACKED_ENV_VARS = (
    "OFS",
    "RUN",
    "PDY",
    "cyc",
    "cycle",
    "NET",
    "OFS_CONFIG",
    "COMOUT",
    "COMIN",
    "COMOUTROOT",
    "DATA",
    "DATAROOT",
    "HOMEnos",
    "FIXofs",
    "PARMnos",
    "USHnos",
    "EXECnos",
    "SCRIPTSnos",
    "pgmout",
    "jlogfile",
    "SENDCOM",
    "SENDDBN",
    "KEEPDATA",
    "LD_PRELOAD",
    # Machine-profile selection: a NOS_MACHINE=hercules (or NOS_ACCOUNT/
    # NOS_QOS) already exported in the caller's shell otherwise leaks into
    # every test that resolves a machine profile or renders a card, silently
    # switching it off the wcoss2 default those tests assume.
    "NOS_MACHINE",
    "NOS_ACCOUNT",
    "NOS_QOS",
)


@pytest.fixture(autouse=True)
def clean_env() -> Iterator[None]:
    """Snapshot and restore tracked NCO env vars around each test."""
    saved = {k: os.environ.get(k) for k in _TRACKED_ENV_VARS}
    for k in _TRACKED_ENV_VARS:
        if k in os.environ:
            del os.environ[k]
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                if k in os.environ:
                    del os.environ[k]
            else:
                os.environ[k] = v
