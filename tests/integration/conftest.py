"""Shared fixtures for prep-stage integration tests.

The integration tests in this directory require:

  - A populated Docker staging directory at ``/mnt/d/secofs_docker_data/``
    with COMINgfs, COMINhrrr, COMINnwm and a SECOFS-UFS sources.json
    under ``fix/secofs/``.
  - The ``nosofs/secofs-ufs:latest`` Docker image already pulled / built.

When either of those is missing (the common case on a fresh checkout or
on GitHub-hosted runners) the integration tests skip cleanly with a
useful message instead of failing. The CI gate at
``.github/workflows/prep_parity.yml`` keys off the same probe so the
hosted-runner job only validates the golden manifest schema.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Iterator

import pytest


# ---------------------------------------------------------------------------
# Knobs — tweak via environment variables when staging lives elsewhere.
# ---------------------------------------------------------------------------

DEFAULT_STAGING_DIR = Path(
    os.environ.get("SECOFS_STAGING_DIR", "/mnt/d/secofs_docker_data")
)
DEFAULT_DOCKER_IMAGE = os.environ.get("SECOFS_DOCKER_IMAGE", "nosofs/secofs-ufs:latest")
DEFAULT_PDY = os.environ.get("PREP_PARITY_PDY", "20260324")
DEFAULT_CYC = os.environ.get("PREP_PARITY_CYC", "18")
DEFAULT_OFS = os.environ.get("PREP_PARITY_OFS", "secofs")


def _docker_image_available(image: str) -> bool:
    """Return True if the Docker image is locally accessible."""
    if not shutil.which("docker"):
        return False
    try:
        proc = subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True,
            timeout=10,
        )
    except (subprocess.SubprocessError, OSError):
        return False
    return proc.returncode == 0


def _staging_dir_populated(staging: Path, pdy: str, cyc: str) -> bool:
    """Sanity-check the staging directory has the inputs prep needs."""
    if not staging.is_dir():
        return False
    must_exist = [
        staging / "com" / "gfs",
        staging / "com" / "nwm",
        staging / "fix" / "secofs",
    ]
    return all(p.is_dir() for p in must_exist)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def staging_dir() -> Path:
    """Path to the bind-mounted Docker data staging dir."""
    return DEFAULT_STAGING_DIR


@pytest.fixture(scope="session")
def docker_image() -> str:
    """Docker image tag used for the parity run."""
    return DEFAULT_DOCKER_IMAGE


@pytest.fixture(scope="session")
def prep_cycle() -> dict:
    """The PDY/cyc/OFS triplet under test."""
    return {"pdy": DEFAULT_PDY, "cyc": DEFAULT_CYC, "ofs": DEFAULT_OFS}


@pytest.fixture(scope="session")
def integration_preflight(staging_dir: Path, docker_image: str, prep_cycle: dict) -> None:
    """Skip the test session if Docker / staging are unavailable.

    Splitting this out into a fixture means the integration tests stay
    runnable even when pytest is invoked from a workstation that doesn't
    have the 12 GB container image — they just skip with a clear
    message.
    """
    if not _docker_image_available(docker_image):
        pytest.skip(
            f"Docker image {docker_image!r} not accessible — "
            "build it or set SECOFS_DOCKER_IMAGE to an available tag."
        )
    if not _staging_dir_populated(staging_dir, prep_cycle["pdy"], prep_cycle["cyc"]):
        pytest.skip(
            f"staging dir missing — see {staging_dir}. "
            "Populate com/gfs, com/nwm, fix/secofs or set SECOFS_STAGING_DIR."
        )


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Path to the working tree root (resolved from this file's location)."""
    return Path(__file__).resolve().parents[2]


@pytest.fixture
def tmp_comout_root(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """A fresh, disposable scratch dir for one parity run.

    The Docker container will write COMOUT trees here (one per path:
    Python and legacy). Cleaned automatically by pytest's tmp_path.
    """
    root = tmp_path_factory.mktemp("prep_parity")
    yield root
    # tmp_path_factory cleans up on its own when the test session ends;
    # we don't force-rm here because the user may want to inspect on
    # failure. pytest's --basetemp retention rule applies.
