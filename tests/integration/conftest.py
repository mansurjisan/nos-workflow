"""Shared fixtures for prep / post / nowcast stage integration tests.

The integration tests in this directory require:

  - A populated Docker staging directory at ``/mnt/d/secofs_docker_data/``
    with COMINgfs, COMINhrrr, COMINnwm and a SECOFS-UFS sources.json
    under ``fix/secofs/``.
  - The ``nosofs/secofs-ufs:latest`` Docker image already pulled / built.

When either of those is missing (the common case on a fresh checkout or
on GitHub-hosted runners) the integration tests skip cleanly with a
useful message instead of failing. The CI gate at
``.github/workflows/stage_parity.yml`` keys off the same probes so the
hosted-runner jobs only validate golden manifest schemas; the heavy
Docker parity jobs run only on the self-hosted ``secofs-docker`` runner.

Per-stage preflight fixtures:

  * ``integration_preflight``         — prep
  * ``post_integration_preflight``    — post (also needs prior model outputs)
  * ``nowcast_integration_preflight`` — nowcast (also needs prior cycle's
    hotstart for ``prepare_restart``)
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

# Post-stage parity cycle. Defaults track prep so the same staging dir
# can feed both tests, but they can be overridden independently when a
# specific post-stage cycle is staged with restart/forecast outputs.
DEFAULT_POST_PDY = os.environ.get("POST_PARITY_PDY", DEFAULT_PDY)
DEFAULT_POST_CYC = os.environ.get("POST_PARITY_CYC", DEFAULT_CYC)
DEFAULT_POST_OFS = os.environ.get("POST_PARITY_OFS", DEFAULT_OFS)

# Nowcast-stage parity cycle. Defaults track prep — the same staging
# dir feeds both. Independently overridable so a specific nowcast cycle
# (with prior-cycle hotstart staged) can be wired in via env vars.
DEFAULT_NOWCAST_PDY = os.environ.get("NOWCAST_PARITY_PDY", DEFAULT_PDY)
DEFAULT_NOWCAST_CYC = os.environ.get("NOWCAST_PARITY_CYC", DEFAULT_CYC)
DEFAULT_NOWCAST_OFS = os.environ.get("NOWCAST_PARITY_OFS", DEFAULT_OFS)


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


def _post_inputs_present(staging: Path, ofs: str, pdy: str, cyc: str) -> bool:
    """Sanity-check that a prior nowcast/forecast run's outputs exist.

    The post stage operates on artifacts the model already produced —
    ``restart_outputs/`` (nowcast) and/or ``forecast_outputs/``
    (forecast) under a populated COMOUT. We probe for both the
    typically-staged path layout (``com/nosofs/<ver>/<ofs>.<pdy>/...``)
    and the bare ``<ofs>.<pdy>/...`` form.

    Returns True iff at least one staout file (``staout_1`` from
    either phase) is reachable; the post script tolerates a missing
    phase but needs at least one to do useful work.
    """
    if not staging.is_dir():
        return False
    cycle = f"t{cyc}z"
    candidates = []
    nosofs_root = staging / "com" / "nosofs"
    if nosofs_root.is_dir():
        for ver_dir in nosofs_root.iterdir():
            if not ver_dir.is_dir():
                continue
            candidates.append(ver_dir / f"{ofs}.{pdy}")
    # Fallback: bare layout some test rigs use.
    candidates.append(staging / f"{ofs}.{pdy}")
    for c in candidates:
        if not c.is_dir():
            continue
        for phase_dir in (
            c / f"{ofs}.{cycle}.restart_outputs",
            c / f"{ofs}.{cycle}.forecast_outputs",
        ):
            if (phase_dir / "staout_1").is_file():
                return True
    return False


def _nowcast_inputs_present(staging: Path, ofs: str, pdy: str, cyc: str) -> bool:
    """Sanity-check that a prep-stage COMOUT + prior-cycle hotstart exist.

    The nowcast stage needs three filesystem fixtures at run time:

      1. The current cycle's prep artifacts in COMOUT (forcing files,
         param.nml, bctides.in, source_sink.in, …) — produced by a
         prior ``prep`` run.
      2. A prior-cycle hotstart NetCDF that ``prepare_restart`` can
         locate (``INI_FILE_NOWCAST`` or ``${COMOUT}/.../rst.nowcast.nc``).
      3. The base staging dir (com/gfs / com/nwm / fix/secofs — same
         as prep, used for incremental forcing if any).

    Building those from scratch would defeat the point of an
    integration test; we skip cleanly when they're not staged. Probes
    for the typical ``com/nosofs/<ver>/<ofs>.<pdy>/`` layout.

    Returns True iff at least one of: ``init.nowcast.nc``, ``rst.*.nc``,
    or a ``hotstart.nc`` is reachable under the cycle COMOUT.
    """
    if not staging.is_dir():
        return False
    cycle = f"t{cyc}z"
    candidates = []
    nosofs_root = staging / "com" / "nosofs"
    if nosofs_root.is_dir():
        for ver_dir in nosofs_root.iterdir():
            if not ver_dir.is_dir():
                continue
            candidates.append(ver_dir / f"{ofs}.{pdy}")
    candidates.append(staging / f"{ofs}.{pdy}")
    for c in candidates:
        if not c.is_dir():
            continue
        # nos_run.sh:_schism_find_hotstart looks for
        #   ${PREFIXNOS}.${cycle}.${PDY1}.init.nowcast.nc — INI_FILE_NOWCAST
        #   ${PREFIXNOS}.${cycle}.${PDY1}.rst.nowcast.nc  — RST_OUT_NOWCAST
        # We can't predict PDY1 (prior cycle date) without doing date
        # math, so we glob loosely on the cycle tag.
        for pat in (
            f"{ofs}.{cycle}.*.init.nowcast.nc",
            f"{ofs}.{cycle}.*.rst.nowcast.nc",
            f"{ofs}.{cycle}.*.rst.forecast.nc",
            "hotstart.nc",
        ):
            if any(c.glob(pat)):
                return True
    return False


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
def post_cycle() -> dict:
    """The PDY/cyc/OFS triplet for the post-stage parity test."""
    return {"pdy": DEFAULT_POST_PDY, "cyc": DEFAULT_POST_CYC, "ofs": DEFAULT_POST_OFS}


@pytest.fixture(scope="session")
def nowcast_cycle() -> dict:
    """The PDY/cyc/OFS triplet for the nowcast-stage parity test."""
    return {
        "pdy": DEFAULT_NOWCAST_PDY,
        "cyc": DEFAULT_NOWCAST_CYC,
        "ofs": DEFAULT_NOWCAST_OFS,
    }


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
def post_integration_preflight(
    staging_dir: Path, docker_image: str, post_cycle: dict
) -> None:
    """Skip post-stage integration tests if Docker / staging / model outputs absent.

    Post needs three things at run time:
      1. The Docker image (same as prep)
      2. The base staging dir (com/gfs etc — same shape as prep)
      3. A prior nowcast/forecast run's restart_outputs+forecast_outputs
         in COMOUT. Building those from scratch would defeat the point of
         an integration test, so we skip cleanly when they're not staged.
    """
    if not _docker_image_available(docker_image):
        pytest.skip(
            f"Docker image {docker_image!r} not accessible — "
            "build it or set SECOFS_DOCKER_IMAGE to an available tag."
        )
    if not _staging_dir_populated(
        staging_dir, post_cycle["pdy"], post_cycle["cyc"]
    ):
        pytest.skip(
            f"staging dir missing — see {staging_dir}. "
            "Populate com/gfs, com/nwm, fix/secofs or set SECOFS_STAGING_DIR."
        )
    if not _post_inputs_present(
        staging_dir, post_cycle["ofs"], post_cycle["pdy"], post_cycle["cyc"]
    ):
        pytest.skip(
            f"post inputs missing under {staging_dir} for "
            f"{post_cycle['ofs']}.{post_cycle['pdy']}.{post_cycle['cyc']}z. "
            "Stage a prior nowcast+forecast's restart_outputs/forecast_outputs "
            "(see scripts/legacy/exnos_post.sh.preY-mig for input layout)."
        )


@pytest.fixture(scope="session")
def nowcast_integration_preflight(
    staging_dir: Path, docker_image: str, nowcast_cycle: dict
) -> None:
    """Skip nowcast-stage integration tests when Docker/staging/hotstart absent.

    Three independent skip reasons (kept distinct so CI log scrapers can
    tell which knob is missing on the runner):

      1. Docker image not accessible.
      2. Base staging dir not populated (no com/gfs / com/nwm).
      3. Prior-cycle hotstart or current-cycle prep COMOUT not staged.

    The third one is nowcast-specific: ``prepare_restart`` needs a
    hotstart from a previous cycle (init.nowcast.nc, rst.nowcast.nc, or
    rst.forecast.nc — depending on which one happens to be the latest
    available restart point in the staging dir). Without that the
    nowcast can't even reach the MPI launch step, so the parity diff
    has nothing to chew on.
    """
    if not _docker_image_available(docker_image):
        pytest.skip(
            f"Docker image {docker_image!r} not accessible — "
            "build it or set SECOFS_DOCKER_IMAGE to an available tag."
        )
    if not _staging_dir_populated(
        staging_dir, nowcast_cycle["pdy"], nowcast_cycle["cyc"]
    ):
        pytest.skip(
            f"staging dir missing — see {staging_dir}. "
            "Populate com/gfs, com/nwm, fix/secofs or set SECOFS_STAGING_DIR."
        )
    if not _nowcast_inputs_present(
        staging_dir,
        nowcast_cycle["ofs"],
        nowcast_cycle["pdy"],
        nowcast_cycle["cyc"],
    ):
        pytest.skip(
            f"nowcast inputs missing under {staging_dir} for "
            f"{nowcast_cycle['ofs']}.{nowcast_cycle['pdy']}."
            f"{nowcast_cycle['cyc']}z. "
            "Stage prior cycle's hotstart (init.nowcast.nc / rst.*.nc) "
            "and current cycle's prep COMOUT — see "
            "scripts/legacy/exnos_nowcast.sh.preY-mig for input layout."
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
