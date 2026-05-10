"""Tests for ``nos_workflow.env.NCOEnv.from_env``."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from nos_workflow.env import NCOEnv
from nos_workflow.errors import ConfigError


def _set_minimum_env(
    *,
    ofs: str = "secofs_ufs",
    pdy: str = "20260510",
    cyc: str = "12",
    comout: str = "/tmp/com/secofs_ufs.20260510",
    data: str = "/tmp/data/secofs_ufs.20260510.t12z",
) -> None:
    os.environ["OFS"] = ofs
    os.environ["PDY"] = pdy
    os.environ["cyc"] = cyc
    os.environ["COMOUT"] = comout
    os.environ["DATA"] = data


def test_from_env_minimum_required() -> None:
    _set_minimum_env()
    env = NCOEnv.from_env()
    assert env.ofs == "secofs_ufs"
    assert env.pdy == "20260510"
    assert env.cyc == "12"
    assert env.cycle == "t12z"
    # OFS isn't a stofs-family system, so net defaults to "nos".
    assert env.net == "nos"
    assert env.run == "secofs_ufs"
    assert env.comout == Path("/tmp/com/secofs_ufs.20260510")
    assert env.data == Path("/tmp/data/secofs_ufs.20260510.t12z")


def test_from_env_zero_pads_cyc() -> None:
    """cyc=0 in the env must come out as '00' on the dataclass."""
    _set_minimum_env(cyc="0")
    env = NCOEnv.from_env()
    assert env.cyc == "00"
    assert env.cycle == "t00z"


def test_from_env_stofs_net_derivation() -> None:
    """OFS names starting with 'stofs' default to NET=stofs."""
    _set_minimum_env(ofs="stofs_3d_atl")
    env = NCOEnv.from_env()
    assert env.net == "stofs"


def test_from_env_explicit_net_overrides() -> None:
    _set_minimum_env(ofs="secofs_ufs")
    os.environ["NET"] = "custom_net"
    env = NCOEnv.from_env()
    assert env.net == "custom_net"


def test_from_env_missing_pdy_raises_configerror() -> None:
    _set_minimum_env()
    del os.environ["PDY"]
    with pytest.raises(ConfigError, match="PDY"):
        NCOEnv.from_env()


def test_from_env_missing_cyc_raises_configerror() -> None:
    _set_minimum_env()
    del os.environ["cyc"]
    with pytest.raises(ConfigError, match="cyc"):
        NCOEnv.from_env()


def test_from_env_missing_comout_raises_configerror() -> None:
    _set_minimum_env()
    del os.environ["COMOUT"]
    with pytest.raises(ConfigError, match="COMOUT"):
        NCOEnv.from_env()


def test_from_env_missing_data_raises_configerror() -> None:
    _set_minimum_env()
    del os.environ["DATA"]
    with pytest.raises(ConfigError, match="DATA"):
        NCOEnv.from_env()


def test_from_env_no_ofs_raises_configerror() -> None:
    """No --ofs, no $OFS, no $RUN must emit a clear ConfigError."""
    os.environ["PDY"] = "20260510"
    os.environ["cyc"] = "12"
    os.environ["COMOUT"] = "/tmp/comout"
    os.environ["DATA"] = "/tmp/data"
    with pytest.raises(ConfigError, match="OFS"):
        NCOEnv.from_env()


def test_from_env_run_fallback_for_ofs() -> None:
    """If OFS isn't set but RUN is, RUN is used as the OFS name."""
    os.environ["RUN"] = "cbofs"
    os.environ["PDY"] = "20260510"
    os.environ["cyc"] = "06"
    os.environ["COMOUT"] = "/tmp/comout"
    os.environ["DATA"] = "/tmp/data"
    env = NCOEnv.from_env()
    assert env.ofs == "cbofs"
    assert env.run == "cbofs"


def test_from_env_explicit_argument_overrides_env() -> None:
    _set_minimum_env(ofs="secofs_ufs")
    env = NCOEnv.from_env(ofs="OVERRIDE")
    assert env.ofs == "override"


def test_as_shell_env_round_trips() -> None:
    _set_minimum_env()
    env = NCOEnv.from_env()
    shell = env.as_shell_env()
    assert shell["OFS"] == "secofs_ufs"
    assert shell["PDY"] == "20260510"
    assert shell["cyc"] == "12"
    assert shell["cycle"] == "t12z"
    assert shell["NET"] == "nos"
    assert shell["COMOUT"] == "/tmp/com/secofs_ufs.20260510"
    # All values must be strings — they're going to subprocess.run(env=).
    for k, v in shell.items():
        assert isinstance(v, str), f"{k} -> {v!r} is not a string"


def test_dataclass_is_frozen() -> None:
    _set_minimum_env()
    env = NCOEnv.from_env()
    with pytest.raises(Exception):  # FrozenInstanceError
        env.cyc = "00"  # type: ignore[misc]
