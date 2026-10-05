"""Parity tests for the execution.mode=standalone gating (Phases 2-3).

Identity-when-UFS is the non-negotiable contract: with USE_DATM unset or
``true``, every gated step must behave exactly as before Phase 2. With
USE_DATM=false (the only thing Phase-1's resolver sets for standalone),
the UFS-only work is skipped and the standalone path runs instead.

Covered:
  - _is_ufs() truth table
  - stage_files.run_python: UFS configs staged vs not; ESMF regen
    attempted vs untar_met_sflux invoked; exe-copy mode-common
  - execute._validate_configs / _maybe_regenerate_mesh gates
  - configure.patch_param_nml dict: UFS == current; standalone adds
    nws=2 + phase-aware ihot
  - forcing.untar_met_sflux extraction + hard-failure contract
"""
from __future__ import annotations

import dataclasses
import os
import shutil
import tarfile
from pathlib import Path
from unittest.mock import patch

import pytest

from nos_workflow.runners.schism_ufs import configure, execute, stage_files
from nos_workflow.runners.schism_ufs.context import SchismRunContext
from nos_workflow.runners.schism_ufs.forcing import untar_met_sflux

_TAR_PATH = shutil.which("tar")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_ctx(
    tmp_path: Path,
    *,
    phase: str = "nowcast",
    prefixnos: str = "stofs_3d_atl_ufs",
) -> SchismRunContext:
    comout = tmp_path / "comout"
    data = tmp_path / "data"
    fixofs = tmp_path / "fix"
    execnos = tmp_path / "exec"
    for p in (comout, data, fixofs, execnos):
        p.mkdir(parents=True, exist_ok=True)
    # run_python checks the ATL river set (check_atl_river_inputs); one source, one sink. MJ (10/03/26)
    (data / "source_sink.in").write_text("1\n300\n\n1\n7\n")
    for name, row in (("vsource.th", "1.0"), ("msource.th", "-9999 0"), ("vsink.th", "1.0")):
        (data / name).write_text(f"0 {row}\n")
    return SchismRunContext(
        comout=comout,
        data=data,
        phase=phase,
        run="nos.stofs_3d_atl_ufs",
        cycle="t00z",
        pdy="20260512",
        cyc="00",
        prefixnos=prefixnos,
        fixofs=fixofs,
        execnos=execnos,
        time_hotstart="2026051200",
        time_nowcastend="2026051206",
        len_nowcast="6",
        len_forecast="48",
        met_netcdf_nowcast="nos.stofs_3d_atl_ufs.t00z.20260512.met.nowcast.nc.tar",
        met_netcdf_forecast="nos.stofs_3d_atl_ufs.t00z.20260512.met.forecast.nc.tar",
    )


_PARAM_NML_LIVE = """\
&CORE
  rnday = 0.25
  start_year = 2020
  start_month = 1
  start_day = 1
  start_hour = 0
  ihot = 0
  nws = 4
/
"""


def _build_tar(tar_path: Path, files: dict) -> None:
    import io
    tar_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path, "w") as tf:
        for name, content in files.items():
            data = content if isinstance(content, bytes) else content.encode()
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))


def _seed_standalone_fix(ctx: SchismRunContext) -> None:
    """Seed the $FIXofs files the standalone preflight requires."""
    for name in ("partition.prop", "tvd.prop", "sflux_inputs.txt"):
        (ctx.fixofs / f"{ctx.prefixnos}.{name}").write_text(f"{name}\n")


# ---------------------------------------------------------------------------
# _is_ufs() truth table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, True),       # unset -> UFS
        ("true", True),
        ("TRUE", True),
        ("True", True),
        ("1", True),        # anything not "false" -> UFS
        ("yes", True),
        ("false", False),   # the only standalone signal
        ("FALSE", False),
        ("  false  ", False),
    ],
)
def test_is_ufs_truth_table(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("USE_DATM", raising=False)
    else:
        monkeypatch.setenv("USE_DATM", value)
    assert stage_files._is_ufs() is expected


# ---------------------------------------------------------------------------
# stage_files.run_python -- UFS identity
# ---------------------------------------------------------------------------


def _seed_ufs_comout(ctx: SchismRunContext) -> None:
    """Seed the 4 UFS configs + aux files in $COMOUT for stage_ufs_configs."""
    prefix = f"{ctx.run}.{ctx.cycle}"
    for f in ("model_configure", "datm_in", "datm.streams", "ufs.configure"):
        (ctx.comout / f"{prefix}.{f}").write_text(f"# {f}\n")


def test_run_python_ufs_unset_stages_configs_and_attempts_mesh(
    tmp_path, monkeypatch,
):
    """USE_DATM unset => UFS path: stage_ufs_configs runs, the 4 UFS
    config patchers run, ESMF regen is attempted, untar_met_sflux NOT
    called. (Identity with pre-Phase-2 behaviour.)"""
    monkeypatch.delenv("USE_DATM", raising=False)
    ctx = _make_ctx(tmp_path)
    _seed_ufs_comout(ctx)

    with patch.object(stage_files, "stage_ufs_configs", return_value=4) as suc, \
         patch.object(stage_files, "stage_executable", return_value=1) as sx, \
         patch.object(configure, "patch_model_configure", return_value=0) as pmc, \
         patch.object(configure, "patch_ufs_configure", return_value=0) as puc, \
         patch.object(configure, "patch_param_nml", return_value=0) as ppn, \
         patch.object(configure, "patch_datm_in", return_value=0) as pdi, \
         patch("nos_workflow.runners.schism_ufs.mesh.generate_esmf_mesh",
               return_value=0) as gen, \
         patch("nos_workflow.runners.schism_ufs.forcing.untar_met_sflux") as ums, \
         patch.object(stage_files, "stage_hotstart", return_value=1):
        # Make the post-config DATM forcing exist so the ESMF block fires.
        (ctx.data / "INPUT").mkdir(parents=True, exist_ok=True)
        (ctx.data / "INPUT" / "datm_forcing.nc").write_bytes(b"x" * 64)
        rc, _collector = stage_files.run_python(ctx, "nowcast")

    assert rc == 0
    suc.assert_called_once()           # UFS configs staged
    sx.assert_called_once()            # exe staged (mode-common)
    pmc.assert_called_once()           # UFS-only patchers all run
    puc.assert_called_once()
    ppn.assert_called_once()           # param.nml patch runs in BOTH modes
    pdi.assert_called_once()
    gen.assert_called_once()           # ESMF mesh regen attempted
    ums.assert_not_called()            # standalone sflux NOT taken


def test_run_python_ufs_true_is_identical_to_unset(tmp_path, monkeypatch):
    """USE_DATM=true behaves exactly like unset (UFS path)."""
    monkeypatch.setenv("USE_DATM", "true")
    ctx = _make_ctx(tmp_path)
    _seed_ufs_comout(ctx)

    with patch.object(stage_files, "stage_ufs_configs", return_value=4) as suc, \
         patch.object(stage_files, "stage_executable", return_value=1), \
         patch.object(configure, "patch_model_configure", return_value=0) as pmc, \
         patch.object(configure, "patch_ufs_configure", return_value=0) as puc, \
         patch.object(configure, "patch_param_nml", return_value=0), \
         patch.object(configure, "patch_datm_in", return_value=0) as pdi, \
         patch("nos_workflow.runners.schism_ufs.mesh.generate_esmf_mesh",
               return_value=0), \
         patch("nos_workflow.runners.schism_ufs.forcing.untar_met_sflux") as ums, \
         patch.object(stage_files, "stage_hotstart", return_value=1):
        rc, _collector = stage_files.run_python(ctx, "nowcast")

    assert rc == 0
    suc.assert_called_once()
    pmc.assert_called_once()
    puc.assert_called_once()
    pdi.assert_called_once()
    ums.assert_not_called()


# ---------------------------------------------------------------------------
# stage_files.run_python -- standalone
# ---------------------------------------------------------------------------


def test_run_python_standalone_skips_ufs_configs_and_mesh(
    tmp_path, monkeypatch,
):
    """USE_DATM=false => standalone: stage_ufs_configs NOT called, the 3
    UFS-only patchers NOT called, ESMF regen NOT attempted,
    untar_met_sflux IS called. patch_param_nml + exe-copy still run."""
    monkeypatch.setenv("USE_DATM", "false")
    ctx = _make_ctx(tmp_path)
    _seed_standalone_fix(ctx)

    with patch.object(stage_files, "stage_ufs_configs") as suc, \
         patch.object(stage_files, "stage_executable", return_value=1) as sx, \
         patch.object(configure, "patch_model_configure") as pmc, \
         patch.object(configure, "patch_ufs_configure") as puc, \
         patch.object(configure, "patch_param_nml", return_value=0) as ppn, \
         patch.object(configure, "patch_datm_in") as pdi, \
         patch("nos_workflow.runners.schism_ufs.mesh.generate_esmf_mesh") as gen, \
         patch("nos_workflow.runners.schism_ufs.forcing.untar_met_sflux",
               return_value=3) as ums, \
         patch.object(stage_files, "stage_hotstart", return_value=1):
        # Even if a DATM forcing file existed, standalone must NOT regen.
        (ctx.data / "INPUT").mkdir(parents=True, exist_ok=True)
        (ctx.data / "INPUT" / "datm_forcing.nc").write_bytes(b"x" * 64)
        rc, _collector = stage_files.run_python(ctx, "nowcast")

    assert rc == 0
    suc.assert_not_called()            # UFS configs NOT staged
    sx.assert_called_once()            # exe still staged (mode-common)
    pmc.assert_not_called()            # UFS-only patchers skipped
    puc.assert_not_called()
    pdi.assert_not_called()
    ppn.assert_called_once()           # param.nml patch STILL runs
    gen.assert_not_called()            # ESMF regen NOT attempted
    ums.assert_called_once_with(ctx, "nowcast")  # standalone sflux taken


def test_run_python_standalone_prefers_legacy_param_nml(
    tmp_path, monkeypatch,
):
    """Standalone stages $FIXofs/<prefix>.standalone.param.nml (legacy
    schema) over the UFS-schema $RUNTIME_CTL when present."""
    monkeypatch.setenv("USE_DATM", "false")
    monkeypatch.setenv("RUNTIME_CTL", "stofs_3d_atl_ufs.param.nml")
    ctx = _make_ctx(tmp_path)
    _seed_standalone_fix(ctx)
    # UFS-schema file already staged in $DATA (would crash legacy pschism).
    (ctx.data / "stofs_3d_atl_ufs.param.nml").write_text(
        "&CORE\n  nbins_veg_vert = 1\n/\n"
    )
    # Legacy-schema standalone variant available in $FIXofs.
    (ctx.fixofs / "stofs_3d_atl_ufs.standalone.param.nml").write_text(
        "&CORE\n  iof_ugrid = 1\n/\n"
    )

    with patch.object(stage_files, "stage_executable", return_value=1), \
         patch.object(configure, "patch_param_nml", return_value=0), \
         patch("nos_workflow.runners.schism_ufs.forcing.untar_met_sflux",
               return_value=3), \
         patch.object(stage_files, "stage_hotstart", return_value=1):
        stage_files.run_python(ctx, "nowcast")

    # The ops-schema file must have overwritten the staged UFS one,
    # so the bare param.nml comes from the standalone variant.
    assert (ctx.data / "param.nml").read_text() == "&CORE\n  iof_ugrid = 1\n/\n"


def test_run_python_standalone_warns_when_legacy_param_nml_absent(
    tmp_path, monkeypatch, caplog,
):
    """No standalone param.nml in $FIXofs => loud WARNING + fall back to
    the UFS-schema file (parent must author the legacy file)."""
    import logging
    monkeypatch.setenv("USE_DATM", "false")
    monkeypatch.setenv("RUNTIME_CTL", "stofs_3d_atl_ufs.param.nml")
    ctx = _make_ctx(tmp_path)
    _seed_standalone_fix(ctx)
    (ctx.data / "stofs_3d_atl_ufs.param.nml").write_text("&CORE\n/\n")
    caplog.set_level(
        logging.WARNING, logger="nos_workflow.runners.schism_ufs.stage_files",
    )

    with patch.object(stage_files, "stage_executable", return_value=1), \
         patch.object(configure, "patch_param_nml", return_value=0), \
         patch("nos_workflow.runners.schism_ufs.forcing.untar_met_sflux",
               return_value=3), \
         patch.object(stage_files, "stage_hotstart", return_value=1):
        stage_files.run_python(ctx, "nowcast")

    assert any(
        "standalone.param.nml not found" in r.getMessage()
        for r in caplog.records
    )


# ---------------------------------------------------------------------------
# execute gates
# ---------------------------------------------------------------------------


def test_validate_configs_ufs_enforced(tmp_path, monkeypatch):
    """UFS: missing configs => rc=1 (unchanged hard check)."""
    monkeypatch.delenv("USE_DATM", raising=False)
    ctx = _make_ctx(tmp_path)
    assert execute._validate_configs(ctx, "nowcast") == 1


def test_validate_configs_ufs_passes_with_files(tmp_path, monkeypatch):
    """UFS: all 4 configs present => rc=0 (unchanged)."""
    monkeypatch.setenv("USE_DATM", "true")
    ctx = _make_ctx(tmp_path)
    for n in ("model_configure", "datm_in", "datm.streams", "ufs.configure"):
        (ctx.data / n).write_text("# stub\n")
    assert execute._validate_configs(ctx, "nowcast") == 0


def test_validate_configs_standalone_returns_zero_without_files(
    tmp_path, monkeypatch,
):
    """Standalone: rc=0 even with NO UFS configs (pschism needs none)."""
    monkeypatch.setenv("USE_DATM", "false")
    ctx = _make_ctx(tmp_path)
    assert execute._validate_configs(ctx, "nowcast") == 0


def test_maybe_regenerate_mesh_ufs_calls_generator(tmp_path, monkeypatch):
    """UFS: forcing present => generator invoked (unchanged)."""
    monkeypatch.delenv("USE_DATM", raising=False)
    ctx = _make_ctx(tmp_path)
    (ctx.data / "INPUT").mkdir()
    (ctx.data / "INPUT" / "datm_forcing.nc").write_bytes(b"x" * 64)
    with patch.object(execute.mesh, "generate_esmf_mesh", return_value=0) as g:
        assert execute._maybe_regenerate_mesh(ctx, "nowcast") == 0
        g.assert_called_once()


def test_maybe_regenerate_mesh_standalone_skips(tmp_path, monkeypatch):
    """Standalone: rc=0, generator NOT called even if forcing exists."""
    monkeypatch.setenv("USE_DATM", "false")
    ctx = _make_ctx(tmp_path)
    (ctx.data / "INPUT").mkdir()
    (ctx.data / "INPUT" / "datm_forcing.nc").write_bytes(b"x" * 64)
    with patch.object(execute.mesh, "generate_esmf_mesh") as g:
        assert execute._maybe_regenerate_mesh(ctx, "nowcast") == 0
        g.assert_not_called()


# ---------------------------------------------------------------------------
# configure.patch_param_nml -- dict identity (UFS) / extension (standalone)
# ---------------------------------------------------------------------------


def _capture_simple_patch_dicts(target_text: str, ctx, phase):
    """Run patch_param_nml capturing every patch_fortran_namelist_simple
    call's dict (the last call is the ihot/nws one under test)."""
    seen = []
    real = configure.patches.patch_fortran_namelist_simple

    def spy(target, mapping):
        seen.append(dict(mapping))
        return real(target, mapping)

    p = ctx.data / "param.nml"
    p.write_text(target_text)
    with patch.object(
        configure.patches, "patch_fortran_namelist_simple", side_effect=spy,
    ):
        configure.patch_param_nml(ctx, phase)
    return seen


def test_patch_param_nml_ufs_dict_unchanged_nowcast(tmp_path, monkeypatch):
    """UFS nowcast: the simple-patch dict is exactly {'ihot': 1} -- the
    pre-Phase-2 behaviour, no nws key."""
    monkeypatch.delenv("USE_DATM", raising=False)
    ctx = _make_ctx(tmp_path, phase="nowcast")
    seen = _capture_simple_patch_dicts(_PARAM_NML_LIVE, ctx, "nowcast")
    assert seen[-1] == {"ihot": 1}


def test_patch_param_nml_ufs_dict_unchanged_forecast(tmp_path, monkeypatch):
    """UFS forecast: still exactly {'ihot': 1} (UFS keeps always-ihot=1)."""
    monkeypatch.setenv("USE_DATM", "true")
    ctx = _make_ctx(tmp_path, phase="forecast")
    seen = _capture_simple_patch_dicts(_PARAM_NML_LIVE, ctx, "forecast")
    assert seen[-1] == {"ihot": 1}


def test_patch_param_nml_standalone_nowcast_sets_nws_and_ihot1(
    tmp_path, monkeypatch,
):
    """Standalone nowcast: dict == {'ihot': 1, 'nws': 2}."""
    monkeypatch.setenv("USE_DATM", "false")
    ctx = _make_ctx(tmp_path, phase="nowcast")
    seen = _capture_simple_patch_dicts(_PARAM_NML_LIVE, ctx, "nowcast")
    assert seen[-1] == {"ihot": 1, "nws": 2}
    text = (ctx.data / "param.nml").read_text()
    assert "ihot = 1" in text
    assert "nws = 2" in text


def test_patch_param_nml_standalone_forecast_resets_clock_ihot1(
    tmp_path, monkeypatch,
):
    """Standalone forecast: ihot=1 (clock reset) so the phase-relative
    forcing prep builds lines up; rnday=LEN_FORECAST/24, start=forecast
    start. ihot=2 would run 24 h short and read th files 24 h late."""
    monkeypatch.setenv("USE_DATM", "false")
    ctx = _make_ctx(tmp_path, phase="forecast")
    seen = _capture_simple_patch_dicts(_PARAM_NML_LIVE, ctx, "forecast")
    assert seen[-1] == {"ihot": 1, "nws": 2}
    text = (ctx.data / "param.nml").read_text()
    assert "ihot = 1" in text
    assert "nws = 2" in text
    assert "rnday = 2.0" in text
    assert "start_day = 12" in text
    assert "start_hour = 6" in text


# ---------------------------------------------------------------------------
# forcing.untar_met_sflux
# ---------------------------------------------------------------------------


@pytest.mark.skipif(_TAR_PATH is None, reason="tar not on PATH")
def test_untar_met_sflux_extracts_gfs_into_sflux_dir(tmp_path):
    """The GFS stack-1 tar extracts into $DATA/sflux/ (created)."""
    ctx = _make_ctx(tmp_path, phase="nowcast")
    _build_tar(
        ctx.comout / ctx.met_netcdf_nowcast,
        {
            "sflux_air_1.1.nc": b"air",
            "sflux_rad_1.1.nc": b"rad",
            "sflux_prc_1.1.nc": b"prc",
        },
    )
    n = untar_met_sflux(ctx, "nowcast")
    assert n == 3
    for f in ("sflux_air_1.1.nc", "sflux_rad_1.1.nc", "sflux_prc_1.1.nc"):
        assert (ctx.data / "sflux" / f).is_file()


@pytest.mark.skipif(_TAR_PATH is None, reason="tar not on PATH")
def test_untar_met_sflux_also_extracts_optional_hrrr(tmp_path):
    """The optional HRRR stack-2 tar (...met.{phase}.nc.2.tar) is also
    extracted when present."""
    ctx = _make_ctx(tmp_path, phase="nowcast")
    _build_tar(
        ctx.comout / ctx.met_netcdf_nowcast,
        {"sflux_air_1.1.nc": b"a", "sflux_rad_1.1.nc": b"r",
         "sflux_prc_1.1.nc": b"p"},
    )
    hrrr_name = ctx.met_netcdf_nowcast[:-7] + ".nc.2.tar"
    _build_tar(
        ctx.comout / hrrr_name,
        {"sflux_air_2.1.nc": b"a2", "sflux_rad_2.1.nc": b"r2",
         "sflux_prc_2.1.nc": b"p2"},
    )
    n = untar_met_sflux(ctx, "nowcast")
    assert n == 6
    assert (ctx.data / "sflux" / "sflux_air_2.1.nc").is_file()


@pytest.mark.skipif(_TAR_PATH is None, reason="tar not on PATH")
def test_untar_met_sflux_missing_hrrr_is_nonfatal(tmp_path):
    """Absent HRRR stack-2 tar is tolerated (optional secondary)."""
    ctx = _make_ctx(tmp_path, phase="forecast")
    _build_tar(
        ctx.comout / ctx.met_netcdf_forecast,
        {"sflux_air_1.1.nc": b"a", "sflux_rad_1.1.nc": b"r",
         "sflux_prc_1.1.nc": b"p"},
    )
    n = untar_met_sflux(ctx, "forecast")
    assert n == 3  # no exception, HRRR simply skipped


def test_untar_met_sflux_missing_gfs_is_hard_failure(tmp_path):
    """Missing GFS stack-1 tar => FileNotFoundError (SCHISM nws=2 needs
    sflux; this must NOT be a silent -1 like the optional forcings)."""
    ctx = _make_ctx(tmp_path, phase="nowcast")
    with pytest.raises(FileNotFoundError, match="GFS sflux tar"):
        untar_met_sflux(ctx, "nowcast")


def test_untar_met_sflux_unknown_phase_raises(tmp_path):
    ctx = _make_ctx(tmp_path)
    with pytest.raises(ValueError, match="unknown phase"):
        untar_met_sflux(ctx, "post")


def test_untar_met_sflux_hrrr_name_derivation(tmp_path):
    """The HRRR sibling name is the GFS name with .nc.tar -> .nc.2.tar
    (matches setup_paths MET_NETCDF_1_{PHASE}_2 and the orchestrator)."""
    from nos_workflow.runners.schism_ufs.forcing import _met_sflux_tar_names
    ctx = _make_ctx(tmp_path, phase="nowcast")
    gfs, hrrr = _met_sflux_tar_names(ctx, "nowcast")
    assert gfs == "nos.stofs_3d_atl_ufs.t00z.20260512.met.nowcast.nc.tar"
    assert hrrr == "nos.stofs_3d_atl_ufs.t00z.20260512.met.nowcast.nc.2.tar"


@pytest.mark.skipif(_TAR_PATH is None, reason="tar not on PATH")
def test_untar_met_sflux_links_unpadded_names(tmp_path):
    """nos-utils writes .0001.nc; the SCHISM 5.14 binary opens .1.nc, so
    both names must resolve (relative symlink, count excludes links)."""
    ctx = _make_ctx(tmp_path, phase="nowcast")
    _build_tar(
        ctx.comout / ctx.met_netcdf_nowcast,
        {"sflux_air_1.0001.nc": b"a", "sflux_rad_1.0001.nc": b"r",
         "sflux_prc_1.0001.nc": b"p"},
    )
    hrrr_name = ctx.met_netcdf_nowcast[:-7] + ".nc.2.tar"
    _build_tar(
        ctx.comout / hrrr_name,
        {"sflux_air_2.0001.nc": b"a2", "sflux_rad_2.0001.nc": b"r2",
         "sflux_prc_2.0001.nc": b"p2"},
    )

    n = untar_met_sflux(ctx, "nowcast")

    assert n == 6
    sflux = ctx.data / "sflux"
    for kind in ("air", "rad", "prc"):
        for stack in (1, 2):
            padded = sflux / f"sflux_{kind}_{stack}.0001.nc"
            link = sflux / f"sflux_{kind}_{stack}.1.nc"
            assert padded.is_file() and not padded.is_symlink()
            assert link.is_symlink()
            assert os.readlink(link) == padded.name
            assert link.read_bytes() == padded.read_bytes()


@pytest.mark.skipif(_TAR_PATH is None, reason="tar not on PATH")
def test_untar_met_sflux_links_every_day_file(tmp_path):
    """Multi-file mode (one file per day): .0002 -> .2, .0010 -> .10."""
    ctx = _make_ctx(tmp_path, phase="nowcast")
    members = {}
    for num in ("0001", "0002", "0010"):
        members[f"sflux_air_1.{num}.nc"] = b"a" + num.encode()
    _build_tar(ctx.comout / ctx.met_netcdf_nowcast, members)

    n = untar_met_sflux(ctx, "nowcast")

    assert n == 3
    sflux = ctx.data / "sflux"
    assert (sflux / "sflux_air_1.2.nc").read_bytes() == b"a0002"
    assert (sflux / "sflux_air_1.10.nc").read_bytes() == b"a0010"


@pytest.mark.skipif(_TAR_PATH is None, reason="tar not on PATH")
def test_untar_met_sflux_unpadded_members_get_no_link(tmp_path):
    """Ops-style .1.nc members are left alone (no self-link, no clobber)."""
    ctx = _make_ctx(tmp_path, phase="nowcast")
    _build_tar(
        ctx.comout / ctx.met_netcdf_nowcast,
        {"sflux_air_1.1.nc": b"a", "sflux_rad_1.1.nc": b"r",
         "sflux_prc_1.1.nc": b"p"},
    )

    n = untar_met_sflux(ctx, "nowcast")

    assert n == 3
    assert not any(p.is_symlink() for p in (ctx.data / "sflux").iterdir())


def test_link_unpadded_sflux_names_keeps_existing_file(tmp_path):
    """A real .1.nc already present is never replaced by a link."""
    from nos_workflow.runners.schism_ufs.forcing import _link_unpadded_sflux_names
    sflux = tmp_path / "sflux"
    sflux.mkdir()
    (sflux / "sflux_air_1.0001.nc").write_bytes(b"padded")
    (sflux / "sflux_air_1.1.nc").write_bytes(b"real")

    assert _link_unpadded_sflux_names(sflux) == 0
    assert not (sflux / "sflux_air_1.1.nc").is_symlink()
    assert (sflux / "sflux_air_1.1.nc").read_bytes() == b"real"


@pytest.mark.skipif(_TAR_PATH is None, reason="tar not on PATH")
def test_collect_staged_inputs_lists_sflux_once(tmp_path, monkeypatch):
    """The unpadded symlinks must not double-list sflux in the manifest."""
    monkeypatch.setenv("USE_DATM", "false")
    ctx = _make_ctx(tmp_path, phase="nowcast")
    _build_tar(
        ctx.comout / ctx.met_netcdf_nowcast,
        {"sflux_air_1.0001.nc": b"a", "sflux_rad_1.0001.nc": b"r",
         "sflux_prc_1.0001.nc": b"p"},
    )
    untar_met_sflux(ctx, "nowcast")

    collector = stage_files.collect_staged_inputs(ctx, "nowcast", ufs=False)

    met = [g for g in collector.groups() if g["category"] == "atmospheric"]
    assert len(met) == 1
    assert met[0]["count"] == 3
    assert not any(f.endswith(".1.nc") for f in met[0]["files"])


# ---------------------------------------------------------------------------
# standalone preflight: missing exe / partition.prop / sflux_inputs.txt
# ---------------------------------------------------------------------------


def _fake_exe(path: Path, mode: int = 0o755) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"#!fake\n")
    os.chmod(path, mode)
    return path


def test_stage_executable_standalone_missing_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_DATM", "false")
    monkeypatch.setenv("UFS_EXEC_NAME", "pschism_x")
    ctx = _make_ctx(tmp_path)
    with pytest.raises(FileNotFoundError, match="pschism_x"):
        stage_files.stage_executable(ctx, "nowcast")


def test_stage_executable_standalone_not_executable_raises(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("USE_DATM", "false")
    monkeypatch.setenv("UFS_EXEC_NAME", "pschism_x")
    ctx = _make_ctx(tmp_path)
    _fake_exe(ctx.execnos / "pschism_x", mode=0o644)
    with pytest.raises(FileNotFoundError, match="not executable"):
        stage_files.stage_executable(ctx, "nowcast")


def test_stage_executable_standalone_copies_from_execnos(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("USE_DATM", "false")
    monkeypatch.setenv("UFS_EXEC_NAME", "pschism_x")
    ctx = _make_ctx(tmp_path)
    _fake_exe(ctx.execnos / "pschism_x")
    assert stage_files.stage_executable(ctx, "nowcast") == 1
    assert os.access(ctx.data / "pschism_x", os.X_OK)


def test_stage_executable_standalone_falls_back_to_homenos_exec(
    tmp_path, monkeypatch,
):
    """Same search order as nos_run.sh: $EXECnos then $HOMEnos/exec."""
    monkeypatch.setenv("USE_DATM", "false")
    monkeypatch.setenv("UFS_EXEC_NAME", "pschism_x")
    ctx = dataclasses.replace(_make_ctx(tmp_path), homenos=tmp_path / "home")
    _fake_exe(ctx.homenos / "exec" / "pschism_x")
    assert stage_files.stage_executable(ctx, "nowcast") == 1
    assert (ctx.data / "pschism_x").is_file()


def test_stage_executable_standalone_already_staged_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_DATM", "false")
    monkeypatch.setenv("UFS_EXEC_NAME", "pschism_x")
    ctx = _make_ctx(tmp_path)
    _fake_exe(ctx.data / "pschism_x")
    assert stage_files.stage_executable(ctx, "nowcast") == 0


def test_stage_executable_ufs_missing_stays_silent(tmp_path, monkeypatch):
    """UFS behaviour is unchanged: a missing binary is not an error here."""
    monkeypatch.delenv("USE_DATM", raising=False)
    monkeypatch.delenv("UFS_EXEC_NAME", raising=False)
    ctx = _make_ctx(tmp_path)
    assert stage_files.stage_executable(ctx, "nowcast") == 0


def test_stage_partition_props_standalone_missing_partition_raises(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("USE_DATM", "false")
    ctx = _make_ctx(tmp_path)
    (ctx.fixofs / f"{ctx.prefixnos}.tvd.prop").write_text("tvd\n")
    with pytest.raises(FileNotFoundError, match="partition.prop"):
        stage_files.stage_partition_props(ctx, "nowcast")


def test_stage_partition_props_standalone_missing_tvd_raises(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("USE_DATM", "false")
    ctx = _make_ctx(tmp_path)
    (ctx.fixofs / f"{ctx.prefixnos}.partition.prop").write_text("part\n")
    with pytest.raises(FileNotFoundError, match="tvd.prop"):
        stage_files.stage_partition_props(ctx, "nowcast")


def test_stage_partition_props_standalone_empty_partition_raises(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("USE_DATM", "false")
    ctx = _make_ctx(tmp_path)
    (ctx.fixofs / f"{ctx.prefixnos}.partition.prop").write_text("")
    (ctx.fixofs / f"{ctx.prefixnos}.tvd.prop").write_text("tvd\n")
    with pytest.raises(FileNotFoundError, match="partition.prop"):
        stage_files.stage_partition_props(ctx, "nowcast")


def test_stage_partition_props_standalone_present_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_DATM", "false")
    ctx = _make_ctx(tmp_path)
    _seed_standalone_fix(ctx)
    assert stage_files.stage_partition_props(ctx, "nowcast") == 2
    assert (ctx.data / "partition.prop").is_file()
    assert (ctx.data / "tvd.prop").is_file()


def test_stage_partition_props_standalone_no_fixofs_raises(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("USE_DATM", "false")
    ctx = dataclasses.replace(_make_ctx(tmp_path), fixofs=None)
    with pytest.raises(FileNotFoundError, match="FIXofs"):
        stage_files.stage_partition_props(ctx, "nowcast")


def test_stage_partition_props_ufs_missing_stays_silent(tmp_path, monkeypatch):
    monkeypatch.delenv("USE_DATM", raising=False)
    ctx = _make_ctx(tmp_path)
    assert stage_files.stage_partition_props(ctx, "nowcast") == 0


def test_stage_sflux_inputs_txt_standalone_missing_raises(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("USE_DATM", "false")
    ctx = _make_ctx(tmp_path)
    with pytest.raises(FileNotFoundError, match="sflux_inputs.txt"):
        stage_files.stage_sflux_inputs_txt(ctx, "nowcast")


def test_stage_sflux_inputs_txt_standalone_empty_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_DATM", "false")
    ctx = _make_ctx(tmp_path)
    (ctx.fixofs / f"{ctx.prefixnos}.sflux_inputs.txt").write_text("")
    with pytest.raises(FileNotFoundError, match="sflux_inputs.txt"):
        stage_files.stage_sflux_inputs_txt(ctx, "nowcast")


def test_stage_sflux_inputs_txt_standalone_present_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_DATM", "false")
    ctx = _make_ctx(tmp_path)
    _seed_standalone_fix(ctx)
    assert stage_files.stage_sflux_inputs_txt(ctx, "nowcast") == 1
    assert (ctx.data / "sflux" / "sflux_inputs.txt").is_file()


def test_stage_sflux_inputs_txt_ufs_missing_stays_silent(
    tmp_path, monkeypatch,
):
    monkeypatch.delenv("USE_DATM", raising=False)
    ctx = _make_ctx(tmp_path)
    assert stage_files.stage_sflux_inputs_txt(ctx, "nowcast") == 0


def test_run_python_standalone_missing_exe_fails_before_other_staging(
    tmp_path, monkeypatch,
):
    """The real stage_executable raises inside run_python, so the stage
    fails before any later staging step (and before mpiexec)."""
    monkeypatch.setenv("USE_DATM", "false")
    monkeypatch.setenv("UFS_EXEC_NAME", "pschism_x")
    ctx = _make_ctx(tmp_path)
    _seed_standalone_fix(ctx)
    with patch.object(stage_files, "stage_hotstart") as hs:
        with pytest.raises(FileNotFoundError, match="pschism_x"):
            stage_files.run_python(ctx, "nowcast")
    hs.assert_not_called()


# ---------------------------------------------------------------------------
# ATL flux.th always staged + partition.prop / flux.th preflight. MJ (10/03/26)
# ---------------------------------------------------------------------------


def _seed_flux_comout(ctx: SchismRunContext) -> None:
    (ctx.comout / f"{ctx.run}.{ctx.cycle}.riv.obs.flux.th").write_text(
        "0 -1\n3600 -1\n"
    )


def test_st_lawrence_staged_for_atl_without_manifest_flag(tmp_path, monkeypatch):
    monkeypatch.delenv("NOS_ARCHIVE_MANIFEST", raising=False)
    ctx = _make_ctx(tmp_path)
    _seed_flux_comout(ctx)
    assert stage_files.stage_st_lawrence_river(ctx, "nowcast") == 1
    assert (ctx.data / "flux.th").is_file()


def test_st_lawrence_not_staged_for_other_systems_without_flag(
    tmp_path, monkeypatch,
):
    monkeypatch.delenv("NOS_ARCHIVE_MANIFEST", raising=False)
    ctx = _make_ctx(tmp_path, prefixnos="secofs_ufs")
    _seed_flux_comout(ctx)
    assert stage_files.stage_st_lawrence_river(ctx, "nowcast") == 0
    assert not (ctx.data / "flux.th").exists()


@pytest.mark.parametrize("prefix", ["stofs_3d_atl_ufs", "stofs_3d_atl"])
def test_is_stofs_atl_true(tmp_path, prefix):
    assert stage_files._is_stofs_atl(_make_ctx(tmp_path, prefixnos=prefix))


@pytest.mark.parametrize(
    "prefix", ["secofs_ufs", "secofs_ufs_ww3", "stofs_3d_ak_ufs",
               "stofs_3d_pac_ufs", None],
)
def test_is_stofs_atl_false(tmp_path, prefix):
    assert not stage_files._is_stofs_atl(_make_ctx(tmp_path, prefixnos=prefix))


def _seed_atl_exec_inputs(ctx, *, ne=6, ranks=(0, 1, 2, 0, 1, 2), flux=True, obc=True):
    if obc:
        for name in execute._ATL_REQUIRED_INPUTS:
            (ctx.data / name).write_bytes(b"x")
    (ctx.data / "hgrid.gr3").write_text(f"grid\n{ne} 9\n")
    (ctx.data / "partition.prop").write_text(
        "".join(f"{i + 1} {r}\n" for i, r in enumerate(ranks))
    )
    if flux:
        (ctx.data / "flux.th").write_text("0 -1\n3600 -1\n")


def test_validate_atl_inputs_standalone_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_DATM", "false")
    monkeypatch.setenv("NPROCS", "5")
    monkeypatch.setenv("NSCRIBES", "2")
    ctx = _make_ctx(tmp_path)
    _seed_atl_exec_inputs(ctx)
    assert execute._validate_atl_inputs(ctx, "nowcast") == 0


def test_validate_atl_inputs_coupled_ok(tmp_path, monkeypatch):
    monkeypatch.delenv("USE_DATM", raising=False)
    monkeypatch.setenv("SCHISM_TASKS", "3")
    ctx = _make_ctx(tmp_path)
    _seed_atl_exec_inputs(ctx)
    assert execute._validate_atl_inputs(ctx, "nowcast") == 0


def test_validate_atl_inputs_rank_mismatch_fails(tmp_path, monkeypatch):
    monkeypatch.delenv("USE_DATM", raising=False)
    monkeypatch.setenv("SCHISM_TASKS", "4")
    ctx = _make_ctx(tmp_path)
    _seed_atl_exec_inputs(ctx)
    assert execute._validate_atl_inputs(ctx, "nowcast") == 1


def test_validate_atl_inputs_standalone_rank_mismatch_fails(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("USE_DATM", "false")
    monkeypatch.setenv("NPROCS", "5")
    monkeypatch.setenv("NSCRIBES", "1")
    ctx = _make_ctx(tmp_path)
    _seed_atl_exec_inputs(ctx)
    assert execute._validate_atl_inputs(ctx, "nowcast") == 1


def test_validate_atl_inputs_line_count_mismatch_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHISM_TASKS", "3")
    ctx = _make_ctx(tmp_path)
    _seed_atl_exec_inputs(ctx, ne=7)
    assert execute._validate_atl_inputs(ctx, "nowcast") == 1


def test_validate_atl_inputs_missing_flux_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHISM_TASKS", "3")
    ctx = _make_ctx(tmp_path)
    _seed_atl_exec_inputs(ctx, flux=False)
    assert execute._validate_atl_inputs(ctx, "nowcast") == 1


def test_validate_atl_inputs_skips_other_systems(tmp_path, monkeypatch):
    ctx = _make_ctx(tmp_path, prefixnos="secofs_ufs")
    assert execute._validate_atl_inputs(ctx, "nowcast") == 0


def test_validate_atl_inputs_coupled_uses_ocn_petlist_over_schism_tasks(
    tmp_path, monkeypatch,
):
    monkeypatch.delenv("USE_DATM", raising=False)
    monkeypatch.setenv("SCHISM_TASKS", "99")
    ctx = _make_ctx(tmp_path)
    _seed_atl_exec_inputs(ctx)
    (ctx.data / "ufs.configure").write_text(
        "MED_petlist_bounds: 0 4\nATM_petlist_bounds: 0 1\nOCN_petlist_bounds: 2 4\n"
    )
    assert execute._validate_atl_inputs(ctx, "nowcast") == 0
    (ctx.data / "ufs.configure").write_text("OCN_petlist_bounds: 2 5\n")
    assert execute._validate_atl_inputs(ctx, "nowcast") == 1


def test_validate_atl_inputs_min_rank_must_be_zero(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHISM_TASKS", "3")
    ctx = _make_ctx(tmp_path)
    _seed_atl_exec_inputs(ctx, ranks=(1, 2, 3, 1, 2, 3))
    assert execute._validate_atl_inputs(ctx, "nowcast") == 1


def test_validate_atl_inputs_standalone_prefers_total_tasks(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_DATM", "false")
    monkeypatch.setenv("TOTAL_TASKS", "5")
    monkeypatch.setenv("NPROCS", "9")
    monkeypatch.setenv("NSCRIBES", "2")
    ctx = _make_ctx(tmp_path)
    _seed_atl_exec_inputs(ctx)
    assert execute._validate_atl_inputs(ctx, "nowcast") == 0


@pytest.mark.parametrize("gone", ["bctides.in", "elev2D.th.nc", "TEM_3D.th.nc", "SAL_3D.th.nc",
                                  "uv3D.th.nc", "TEM_nu.nc", "SAL_nu.nc"])
def test_validate_atl_inputs_requires_obc_nudging_files(tmp_path, monkeypatch, gone):
    monkeypatch.setenv("USE_DATM", "false")
    monkeypatch.setenv("NPROCS", "5")
    monkeypatch.setenv("NSCRIBES", "2")
    ctx = _make_ctx(tmp_path)
    _seed_atl_exec_inputs(ctx)
    (ctx.data / gone).unlink()
    assert execute._validate_atl_inputs(ctx, "nowcast") == 1


def test_validate_atl_inputs_rejects_empty_obc_file(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_DATM", "false")
    monkeypatch.setenv("NPROCS", "5")
    monkeypatch.setenv("NSCRIBES", "2")
    ctx = _make_ctx(tmp_path)
    _seed_atl_exec_inputs(ctx)
    (ctx.data / "TEM_nu.nc").write_bytes(b"")
    assert execute._validate_atl_inputs(ctx, "nowcast") == 1
