"""Post stage tests for nos_workflow.stages.post.

Mirrors the contract laid out by ``test_stage_dispatch.py`` but with
filesystem + subprocess machinery isolated here so the dispatch suite
stays lightweight.

The COMF body shells out to two deployed scripts that don't live in
this tree (``schism_combine_outputs.py`` and ``ensemble_bias_correct.py``
under ``${HOMEnos}/ush/...``). We mock ``subprocess.run`` and stub the
combine script's expected output file so the body can exercise its real
control-file + station.lat.lon writers, the staout symlink loop, and
the COMOUT copy step.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from nos_workflow.errors import StageFailedError
from nos_workflow.registry import OFSDescriptor
from nos_workflow.stages import post as post_stage


# ---------------------------------------------------------------------------
# Descriptor fixtures (copied from test_stage_dispatch.py — the post stage
# only needs the framework field + name for log lines, but we keep the
# shape identical so we can drop these in there later without diffs).
# ---------------------------------------------------------------------------


def _secofs_ufs_desc() -> OFSDescriptor:
    return OFSDescriptor(
        name="secofs_ufs",
        framework="comf",
        canonical_stages=("prep", "nowcast", "forecast", "post"),
        stage_aliases={},
        yaml_path=Path("parm/systems/secofs_ufs.yaml"),
        runner_module="nos_workflow.runners.ufs_coastal",
        notes="test fixture",
    )


def _stofs_3d_atl_ufs_desc() -> OFSDescriptor:
    """STOFS-3D-ATL on UFS-Coastal — routes through the same UFS-Coastal
    body as ``comf``; the distinct framework label keeps it free for
    future divergence."""
    return OFSDescriptor(
        name="stofs_3d_atl_ufs",
        framework="stofs_ufs",
        canonical_stages=("prep", "nowcast", "forecast", "post"),
        stage_aliases={},
        yaml_path=Path("parm/systems/stofs_3d_atl_ufs.yaml"),
        runner_module="nos_workflow.runners.ufs_coastal",
        notes="test fixture",
    )


def _stofs_3d_desc() -> OFSDescriptor:
    return OFSDescriptor(
        name="stofs_3d_atl",
        framework="stofs",
        canonical_stages=("prep", "nowcast", "forecast", "post"),
        stage_aliases={"prep_nowcast": "prep", "now_forecast": "nowcast"},
        extra_stages=("post_1", "post_2", "temp_salt_restart"),
        yaml_path=Path("parm/systems/stofs_3d_atl.yaml"),
        runner_module="",
        notes="test fixture",
    )


def _adcirc_desc() -> OFSDescriptor:
    return OFSDescriptor(
        name="stofs_2d_glo",
        framework="adcirc",
        canonical_stages=("prep", "nowcast", "forecast", "post"),
        stage_aliases={},
        yaml_path=Path("parm/systems/stofs_2d_glo.yaml"),
        runner_module="",
        notes="test fixture",
    )


@pytest.fixture
def fake_env() -> object:
    """Trivial stand-in for ``NCOEnv`` — the post stage reads
    ``os.environ`` directly, so this is unused but matches the
    dispatch-test signature."""
    return object()


# ---------------------------------------------------------------------------
# Framework-branch tests (mirror prep_stage tests in test_stage_dispatch.py)
# ---------------------------------------------------------------------------


def test_post_stofs_branch_raises_not_implemented(fake_env):
    with pytest.raises(NotImplementedError) as exc_info:
        post_stage.run(_stofs_3d_desc(), fake_env)
    assert "STOFS-3D-ATL" in str(exc_info.value)


def test_post_adcirc_branch_raises_not_implemented(fake_env):
    with pytest.raises(NotImplementedError) as exc_info:
        post_stage.run(_adcirc_desc(), fake_env)
    assert "STOFS-2D-GLO" in str(exc_info.value)


def test_post_unknown_framework_raises_stage_failed(fake_env):
    desc = OFSDescriptor(
        name="weird",
        framework="not-a-framework",
        canonical_stages=("post",),
    )
    with pytest.raises(StageFailedError) as exc_info:
        post_stage.run(desc, fake_env)
    assert exc_info.value.stage == "post"


def test_post_phase_header_logged(fake_env, caplog):
    """The stage-start log record must fire on every dispatch. Stage + ofs
    live in record.extra under the LoggerAdapter pattern."""
    caplog.set_level("INFO", logger="nos_workflow.stages.post")
    with pytest.raises(NotImplementedError):
        post_stage.run(_stofs_3d_desc(), fake_env)
    assert any(
        rec.getMessage() == "stage start"
        and getattr(rec, "stage", None) == "post"
        and getattr(rec, "ofs", None) == "stofs_3d_atl"
        for rec in caplog.records
    )


# ---------------------------------------------------------------------------
# COMF body — happy path
# ---------------------------------------------------------------------------


def _make_minimal_post_env(tmp_path: Path) -> dict:
    """Build the env vars the COMF body requires, with stubs in tmp_path."""
    homenos = tmp_path / "home"
    fixofs = tmp_path / "fix"
    comout = tmp_path / "com"
    data = tmp_path / "data"
    for p in (homenos, fixofs, comout, data):
        p.mkdir(parents=True, exist_ok=True)

    # Drop a stub combine script (just has to exist for the existence check;
    # subprocess.run is mocked so its body is never executed).
    combine = homenos / "ush" / "nosofs" / "schism_combine_outputs.py"
    combine.parent.mkdir(parents=True, exist_ok=True)
    combine.write_text("# stub\n")

    # Build a SCHISM-style station.in: two header lines + N station rows.
    # Format: <id> <lon> <lat> <depth> ... (we only read cols 2 and 3).
    sta_in = fixofs / "nos.secofs_ufs.station.in"
    sta_in.write_text(
        "Header line 1\n"
        "Header line 2\n"
        "1 -76.5 38.5 0\n"
        "2 -75.5 37.5 0\n"
        "3 -74.5 36.5 0\n"
    )

    return {
        "HOMEnos": str(homenos),
        "FIXofs": str(fixofs),
        "COMOUT": str(comout),
        "DATA": str(data),
        "PDY": "20260507",
        "cyc": "00",
        "cycle": "t00z",
        "RUN": "nos.secofs_ufs",
        "PREFIXNOS": "nos.secofs_ufs",
        "LEN_NOWCAST": "6",
        "OFS": "secofs_ufs",
    }


def _seed_staout(comout: Path, run: str, cycle: str, phase: str) -> Path:
    """Drop a minimal staout_1 (plus a few more) in the
    ``${RUN}.${cycle}.{restart,forecast}_outputs`` directory."""
    dir_name = "restart_outputs" if phase == "nowcast" else "forecast_outputs"
    staout_dir = comout / f"{run}.{cycle}.{dir_name}"
    staout_dir.mkdir(parents=True, exist_ok=True)
    for n in range(1, 4):  # only seed staout_1..3; loop should still work
        (staout_dir / f"staout_{n}").write_text(f"# staout {n} {phase}\n")
    return staout_dir


def _fake_combine_subprocess_factory(
    work_dirs_seen: list,
    prefix_nos: str,
    pdy: str,
    cyc: str,
):
    """Build a fake ``subprocess.run`` that, when called for
    ``schism_combine_outputs.py``, drops the expected output NetCDF in
    its ``cwd`` so the post body's copy step succeeds."""

    def fake_run(cmd, **kwargs):
        cwd = kwargs.get("cwd")
        work_dirs_seen.append((cmd, cwd))
        # Figure out which phase by inspecting the working dir name.
        if cwd is not None:
            cwd_path = Path(cwd)
            phase = cwd_path.name.removeprefix("post_")
            out_nc = cwd_path / f"{prefix_nos}.t{cyc}z.{pdy}.stations.{phase}.nc"
            out_nc.write_bytes(b"\x89HDF\r\n\x1a\n")  # tiny non-empty stub
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    return fake_run


@pytest.mark.parametrize(
    "desc_factory",
    [_secofs_ufs_desc, _stofs_3d_atl_ufs_desc],
    ids=["comf", "stofs_ufs"],
)
def test_post_comf_happy_path_writes_station_nc(
    tmp_path, fake_env, caplog, desc_factory
):
    """End-to-end UFS-Coastal happy path: both phases combine cleanly,
    the station NetCDF lands in COMOUT, the control file +
    station.lat.lon are emitted with the right contents, and staout
    symlinks are wired into each phase's working dir.

    Parametrized across both ``framework="comf"`` (SECOFS-UFS) and
    ``framework="stofs_ufs"`` (STOFS-3D-ATL-UFS) since both must route
    through ``_run_comf_post`` identically.
    """
    caplog.set_level("INFO", logger="nos_workflow.stages.post")
    env = _make_minimal_post_env(tmp_path)
    comout = Path(env["COMOUT"])
    data = Path(env["DATA"])

    _seed_staout(comout, env["RUN"], env["cycle"], "nowcast")
    _seed_staout(comout, env["RUN"], env["cycle"], "forecast")

    seen: list = []
    fake_run = _fake_combine_subprocess_factory(
        seen, env["PREFIXNOS"], env["PDY"], env["cyc"]
    )

    with patch.dict(os.environ, env, clear=False):
        with patch.object(post_stage.subprocess, "run", side_effect=fake_run):
            rc = post_stage.run(desc_factory(), fake_env)

    assert rc == 0
    # subprocess.run was called exactly twice (one per phase, no bias-corr
    # since BAROTROPIC is unset).
    assert len(seen) == 2

    # Per-phase artifacts.
    for phase in ("nowcast", "forecast"):
        work = data / f"post_{phase}"
        ctl = work / "schism_standard_output.ctl"
        sta_latlon = work / f"{env['PREFIXNOS']}.station.lat.lon"
        sta_nc = comout / (
            f"{env['PREFIXNOS']}.t{env['cyc']}z.{env['PDY']}"
            f".stations.{phase}.nc"
        )

        # Control file: 5 lines, prefix/cyc/pdy/mode_flag/timestart.
        ctl_lines = ctl.read_text().splitlines()
        assert ctl_lines[0] == env["PREFIXNOS"]
        assert ctl_lines[1] == env["cyc"]
        assert ctl_lines[2] == env["PDY"]
        assert ctl_lines[3] in ("n", "f")

        # station.lat.lon: 3 rows, reindexed 1..3, lon/lat from cols 2/3.
        rows = sta_latlon.read_text().strip().splitlines()
        assert rows == ["1 -76.5 38.5", "2 -75.5 37.5", "3 -74.5 36.5"]

        # Symlinks staout_1..staout_3 (we seeded those); 4..9 absent.
        for n in (1, 2, 3):
            assert (work / f"staout_{n}").is_symlink()
        for n in (4, 5, 6, 7, 8, 9):
            assert not (work / f"staout_{n}").exists()

        # Station NetCDF copied to COMOUT.
        assert sta_nc.is_file()


def test_post_comf_phase_skipped_when_staout_missing(tmp_path, fake_env, caplog):
    """If a phase has no ``staout_1``, the body must log a WARNING and
    continue to the next phase rather than aborting."""
    caplog.set_level("WARNING", logger="nos_workflow.stages.post")
    env = _make_minimal_post_env(tmp_path)
    comout = Path(env["COMOUT"])
    # Seed only the forecast directory; nowcast is missing.
    _seed_staout(comout, env["RUN"], env["cycle"], "forecast")

    seen: list = []
    fake_run = _fake_combine_subprocess_factory(
        seen, env["PREFIXNOS"], env["PDY"], env["cyc"]
    )

    with patch.dict(os.environ, env, clear=False):
        with patch.object(post_stage.subprocess, "run", side_effect=fake_run):
            rc = post_stage.run(_secofs_ufs_desc(), fake_env)

    assert rc == 0
    # Only forecast ran.
    assert len(seen) == 1
    assert any(
        "skipping nowcast" in rec.getMessage() for rec in caplog.records
    )


def test_post_comf_combine_failure_warns_and_continues(tmp_path, fake_env, caplog):
    """When schism_combine_outputs.py returns non-zero, the body should
    WARN, skip the COMOUT copy, and continue — same semantic as the
    legacy shell's ``continue``."""
    caplog.set_level("WARNING", logger="nos_workflow.stages.post")
    env = _make_minimal_post_env(tmp_path)
    comout = Path(env["COMOUT"])
    _seed_staout(comout, env["RUN"], env["cycle"], "nowcast")
    _seed_staout(comout, env["RUN"], env["cycle"], "forecast")

    def failing_run(cmd, **kwargs):
        return subprocess.CompletedProcess(args=cmd, returncode=1)

    with patch.dict(os.environ, env, clear=False):
        with patch.object(post_stage.subprocess, "run", side_effect=failing_run):
            rc = post_stage.run(_secofs_ufs_desc(), fake_env)

    assert rc == 0  # body still returns 0; warnings are not fatal
    msgs = [rec.getMessage() for rec in caplog.records]
    assert any("failed for nowcast" in m for m in msgs)
    assert any("failed for forecast" in m for m in msgs)


# ---------------------------------------------------------------------------
# COMF body — fatal paths
# ---------------------------------------------------------------------------


def test_post_comf_missing_combine_script_raises(tmp_path, fake_env):
    """If ``schism_combine_outputs.py`` is absent under HOMEnos, fail
    fast with a StageFailedError naming the missing path."""
    env = _make_minimal_post_env(tmp_path)
    # Yank the stub combine script.
    combine = (
        Path(env["HOMEnos"]) / "ush" / "nosofs" / "schism_combine_outputs.py"
    )
    combine.unlink()

    with patch.dict(os.environ, env, clear=False):
        with pytest.raises(StageFailedError) as exc_info:
            post_stage.run(_secofs_ufs_desc(), fake_env)
    assert exc_info.value.stage == "post"
    assert "schism_combine_outputs.py" in str(exc_info.value)


def test_post_comf_missing_station_in_raises(tmp_path, fake_env):
    """station.in absence is fatal — there's nothing for the awk-style
    writer to consume."""
    env = _make_minimal_post_env(tmp_path)
    sta = Path(env["FIXofs"]) / "nos.secofs_ufs.station.in"
    sta.unlink()

    with patch.dict(os.environ, env, clear=False):
        with pytest.raises(StageFailedError) as exc_info:
            post_stage.run(_secofs_ufs_desc(), fake_env)
    assert exc_info.value.stage == "post"
    assert "station.in" in str(exc_info.value)


def test_post_comf_missing_required_env_var_raises(tmp_path, fake_env):
    """Missing PREFIXNOS (or any other required env var) must be a
    structured StageFailedError, not a KeyError."""
    env = _make_minimal_post_env(tmp_path)
    del env["PREFIXNOS"]

    with patch.dict(os.environ, env, clear=False):
        # Ensure PREFIXNOS isn't sneaking in from the host shell either.
        os.environ.pop("PREFIXNOS", None)
        with pytest.raises(StageFailedError) as exc_info:
            post_stage.run(_secofs_ufs_desc(), fake_env)
    assert "PREFIXNOS" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Pure-function helpers
# ---------------------------------------------------------------------------


def test_nowcast_base_hour_default_len_nowcast():
    # cyc=06, default len_nowcast=6 → 00
    assert post_stage._nowcast_base_hour("06", None) == "00"


def test_nowcast_base_hour_wraps_negative():
    # cyc=00, len_nowcast=6 → -6 → wrap to 18
    assert post_stage._nowcast_base_hour("00", "6") == "18"


def test_nowcast_base_hour_zero_pads():
    # cyc=12, len_nowcast=3 → 09 (zero-padded)
    assert post_stage._nowcast_base_hour("12", "3") == "09"


def test_derive_det_ofs_2d_ufs_drop():
    assert post_stage._derive_det_ofs("secofs_2d_ufs") == "secofs"


def test_derive_det_ofs_2d_to_3d_swap():
    assert post_stage._derive_det_ofs("stofs_2d_atl") == "stofs_3d_atl"


def test_derive_det_ofs_passthrough():
    assert post_stage._derive_det_ofs("cbofs") == "cbofs"


def test_is_barotropic_accepts_true_and_1():
    assert post_stage._is_barotropic({"BAROTROPIC": "true"}) is True
    assert post_stage._is_barotropic({"BAROTROPIC": "1"}) is True
    assert post_stage._is_barotropic({"BAROTROPIC": "TRUE"}) is True
    assert post_stage._is_barotropic({}) is False
    assert post_stage._is_barotropic({"BAROTROPIC": "false"}) is False
    assert post_stage._is_barotropic({"BAROTROPIC": "0"}) is False


def test_write_station_latlon_skips_headers_and_short_rows(tmp_path):
    sta = tmp_path / "station.in"
    sta.write_text(
        "header 1\n"
        "header 2\n"
        "1 -76.5 38.5 0\n"
        "\n"                       # blank row — skipped
        "2 -75.5 37.5 0 extra\n"
        "short row\n"              # too few fields — skipped
        "3 -74.5 36.5 0\n"
    )
    out = tmp_path / "out.latlon"
    post_stage._write_station_latlon(sta, out)
    rows = out.read_text().strip().splitlines()
    # Blank + short rows skipped; surviving rows reindexed 1..3.
    assert rows == ["1 -76.5 38.5", "3 -75.5 37.5", "5 -74.5 36.5"]
