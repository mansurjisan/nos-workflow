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
    # UFS-schema file already staged in $DATA (would crash legacy pschism).
    (ctx.data / "stofs_3d_atl_ufs.param.nml").write_text(
        "&CORE\n  nbins_veg_vert = 1\n/\n"
    )
    # Legacy-schema standalone variant available in $FIXofs.
    (ctx.fixofs / "stofs_3d_atl_ufs.standalone.param.nml").write_text(
        "&CORE\n  isav = 0\n/\n"
    )

    with patch.object(stage_files, "stage_executable", return_value=1), \
         patch.object(configure, "patch_param_nml", return_value=0), \
         patch("nos_workflow.runners.schism_ufs.forcing.untar_met_sflux",
               return_value=3), \
         patch.object(stage_files, "stage_hotstart", return_value=1):
        stage_files.run_python(ctx, "nowcast")

    # The legacy-schema file must have overwritten the staged UFS one,
    # so the bare param.nml comes from the standalone variant.
    assert (ctx.data / "param.nml").read_text() == "&CORE\n  isav = 0\n/\n"


def test_run_python_standalone_warns_when_legacy_param_nml_absent(
    tmp_path, monkeypatch, caplog,
):
    """No standalone param.nml in $FIXofs => loud WARNING + fall back to
    the UFS-schema file (parent must author the legacy file)."""
    import logging
    monkeypatch.setenv("USE_DATM", "false")
    monkeypatch.setenv("RUNTIME_CTL", "stofs_3d_atl_ufs.param.nml")
    ctx = _make_ctx(tmp_path)
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


def test_patch_param_nml_standalone_forecast_sets_nws_and_ihot2(
    tmp_path, monkeypatch,
):
    """Standalone forecast: ihot=2 (continues from nowcast hotstart)."""
    monkeypatch.setenv("USE_DATM", "false")
    ctx = _make_ctx(tmp_path, phase="forecast")
    seen = _capture_simple_patch_dicts(_PARAM_NML_LIVE, ctx, "forecast")
    assert seen[-1] == {"ihot": 2, "nws": 2}
    text = (ctx.data / "param.nml").read_text()
    assert "ihot = 2" in text
    assert "nws = 2" in text


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
