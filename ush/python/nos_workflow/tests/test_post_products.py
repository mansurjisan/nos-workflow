"""Tests for the post-product framework (nos_workflow.post).

Registry + selection unit tests, plus driver-level integration through
``nos_workflow.stages.post.run`` reusing the env/subprocess harness from
``test_post_stage`` -- the P1 contract is that the framework changes no
observable behavior of the stage beyond the new outputs manifest.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from nos_workflow.post import registry as post_registry
from nos_workflow.post.base import PostProduct, ProductContext, ProductResult
from nos_workflow.post.registry import (
    available_products,
    get_product,
    register,
    resolve_product_names,
)
from nos_workflow.stages import post as post_stage
from nos_workflow.tests.test_post_stage import (
    _fake_combine_subprocess_factory,
    _make_minimal_post_env,
    _secofs_ufs_desc,
    _seed_staout,
)


@pytest.fixture
def registry_snapshot():
    """Restore the product registry after tests that register extras."""
    saved = dict(post_registry._REGISTRY)
    yield
    post_registry._REGISTRY.clear()
    post_registry._REGISTRY.update(saved)


@pytest.fixture
def fake_env() -> object:
    return object()


def _post_env(tmp_path: Path) -> dict:
    """Minimal post env, isolated from host-level selection overrides."""
    env = _make_minimal_post_env(tmp_path)
    env["NOS_POST_PRODUCTS"] = ""
    env["OFS_CONFIG"] = ""
    return env


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_builtin_products_registered():
    # Importing nos_workflow.stages.post registers the P1 products.
    assert "stations_nc" in available_products()
    assert "bias_correct" in available_products()
    assert get_product("stations_nc") is post_stage.StationsNcProduct
    assert get_product("nope") is None


def test_register_same_class_is_idempotent():
    assert register(post_stage.StationsNcProduct) is post_stage.StationsNcProduct


def test_register_rejects_duplicate_name(registry_snapshot):
    class Imposter(PostProduct):
        name = "stations_nc"

        def produce(self, ctx):  # pragma: no cover - never called
            return ProductResult(name=self.name, status="ok")

    with pytest.raises(ValueError):
        register(Imposter)


def test_register_requires_name():
    class Nameless(PostProduct):
        def produce(self, ctx):  # pragma: no cover - never called
            return ProductResult(name="", status="ok")

    with pytest.raises(ValueError):
        register(Nameless)


# ---------------------------------------------------------------------------
# Product selection
# ---------------------------------------------------------------------------


def test_resolve_env_override_wins(tmp_path):
    env = {"NOS_POST_PRODUCTS": "bias_correct, stations_nc"}
    assert resolve_product_names("comf", env) == [
        "bias_correct", "stations_nc",
    ]


def test_resolve_framework_defaults():
    assert resolve_product_names("comf", {}) == [
        "stations_nc", "bias_correct",
    ]
    assert resolve_product_names("stofs_ufs", {}) == [
        "stations_nc", "bias_correct",
    ]
    assert resolve_product_names("something_else", {}) == ["stations_nc"]


def test_resolve_yaml_products_via_ofs_config(tmp_path):
    yml = tmp_path / "sys.yaml"
    yml.write_text("post:\n  products:\n    - stations_nc\n")
    env = {"OFS_CONFIG": str(yml)}
    assert resolve_product_names("comf", env) == ["stations_nc"]


def test_resolve_yaml_dict_entries_and_enabled_flag(tmp_path):
    yml = tmp_path / "sys.yaml"
    yml.write_text(
        "post:\n"
        "  products:\n"
        "    - name: stations_nc\n"
        "    - name: bias_correct\n"
        "      enabled: false\n"
    )
    env = {"OFS_CONFIG": str(yml)}
    assert resolve_product_names("comf", env) == ["stations_nc"]


def test_resolve_yaml_follows_base_chain(tmp_path):
    base = tmp_path / "parent.yaml"
    base.write_text("post:\n  products:\n    - stations_nc\n")
    overlay = tmp_path / "child.yaml"
    overlay.write_text("_base: parent\nstandalone:\n  mode: standalone\n")
    env = {"OFS_CONFIG": str(overlay)}
    assert resolve_product_names("comf", env) == ["stations_nc"]


def test_resolve_yaml_empty_list_is_respected(tmp_path):
    yml = tmp_path / "sys.yaml"
    yml.write_text("post:\n  products: []\n")
    env = {"OFS_CONFIG": str(yml)}
    assert resolve_product_names("comf", env) == []


def test_resolve_yaml_malformed_falls_back_to_defaults(tmp_path):
    yml = tmp_path / "sys.yaml"
    yml.write_text("post:\n  products: not-a-list\n")
    env = {"OFS_CONFIG": str(yml)}
    assert resolve_product_names("comf", env) == [
        "stations_nc", "bias_correct",
    ]


def test_resolve_descriptor_yaml_under_homenos(tmp_path):
    homenos = tmp_path / "home"
    rel = Path("parm/systems/secofs_ufs.yaml")
    yml = homenos / rel
    yml.parent.mkdir(parents=True)
    yml.write_text("post:\n  products:\n    - stations_nc\n")
    assert resolve_product_names(
        "comf", {}, homenos=homenos, yaml_path=rel
    ) == ["stations_nc"]


# ---------------------------------------------------------------------------
# Driver integration (through stages.post.run)
# ---------------------------------------------------------------------------


def _run_post(env: dict, fake_env: object):
    seen: list = []
    fake_run = _fake_combine_subprocess_factory(
        seen, env["PREFIXNOS"], env["PDY"], env["cyc"]
    )
    with patch.dict(os.environ, env, clear=False):
        with patch.object(post_stage.subprocess, "run", side_effect=fake_run):
            rc = post_stage.run(_secofs_ufs_desc(), fake_env)
    return rc, seen


def _load_outputs_manifest(env: dict) -> dict:
    path = Path(env["COMOUT"]) / (
        f"{env['RUN']}.t{env['cyc']}z.{env['PDY']}.outputs.post.json"
    )
    assert path.is_file()
    return json.loads(path.read_text())


def test_post_writes_outputs_manifest(tmp_path, fake_env):
    env = _post_env(tmp_path)
    comout = Path(env["COMOUT"])
    _seed_staout(comout, env["RUN"], env["cycle"], "nowcast")
    _seed_staout(comout, env["RUN"], env["cycle"], "forecast")

    rc, seen = _run_post(env, fake_env)
    assert rc == 0
    assert len(seen) == 2

    data = _load_outputs_manifest(env)
    assert data["ofs"] == env["RUN"]
    assert data["stage"] == "post"
    assert data["schema_version"] == 1

    by_name = {p["name"]: p for p in data["products"]}
    stations = by_name["stations_nc"]
    assert stations["status"] == "ok"
    assert stations["count"] == 2
    assert stations["outputs"][0].endswith("stations.nowcast.nc")
    assert stations["outputs"][1].endswith("stations.forecast.nc")

    bias = by_name["bias_correct"]
    assert bias["status"] == "skipped"
    assert bias["detail"] == "BAROTROPIC not set"
    assert bias["count"] == 0

    for p in data["products"]:
        assert set(p.keys()) == {
            "name", "status", "count", "outputs", "detail", "duration_s",
        }


def test_failing_product_is_isolated(tmp_path, fake_env, caplog, registry_snapshot):
    """A product raising an unexpected exception is marked failed; the
    remaining products still run and the stage returns 0."""

    @register
    class BoomProduct(PostProduct):
        name = "boom"

        def produce(self, ctx: ProductContext) -> ProductResult:
            raise RuntimeError("kaboom")

    caplog.set_level("WARNING", logger="nos_workflow.stages.post")
    env = _post_env(tmp_path)
    env["NOS_POST_PRODUCTS"] = "boom,stations_nc"
    comout = Path(env["COMOUT"])
    _seed_staout(comout, env["RUN"], env["cycle"], "nowcast")
    _seed_staout(comout, env["RUN"], env["cycle"], "forecast")

    rc, seen = _run_post(env, fake_env)
    assert rc == 0
    assert len(seen) == 2  # stations_nc still ran both phases

    data = _load_outputs_manifest(env)
    by_name = {p["name"]: p for p in data["products"]}
    assert by_name["boom"]["status"] == "failed"
    assert "kaboom" in by_name["boom"]["detail"]
    assert by_name["stations_nc"]["status"] == "ok"
    assert any("boom failed" in rec.getMessage() for rec in caplog.records)


def test_unknown_product_name_warns_and_skips(tmp_path, fake_env, caplog):
    caplog.set_level("WARNING", logger="nos_workflow.stages.post")
    env = _post_env(tmp_path)
    env["NOS_POST_PRODUCTS"] = "nope,stations_nc"
    comout = Path(env["COMOUT"])
    _seed_staout(comout, env["RUN"], env["cycle"], "nowcast")
    _seed_staout(comout, env["RUN"], env["cycle"], "forecast")

    rc, seen = _run_post(env, fake_env)
    assert rc == 0
    assert len(seen) == 2

    data = _load_outputs_manifest(env)
    by_name = {p["name"]: p for p in data["products"]}
    assert by_name["nope"]["status"] == "skipped"
    assert by_name["nope"]["detail"] == "unregistered product"
    assert any(
        "unknown post product" in rec.getMessage() for rec in caplog.records
    )


def test_yaml_selection_drives_the_stage(tmp_path, fake_env):
    """OFS_CONFIG post.products controls which products run end-to-end."""
    env = _post_env(tmp_path)
    yml = tmp_path / "system.yaml"
    yml.write_text("post:\n  products:\n    - stations_nc\n")
    env["OFS_CONFIG"] = str(yml)
    comout = Path(env["COMOUT"])
    _seed_staout(comout, env["RUN"], env["cycle"], "nowcast")
    _seed_staout(comout, env["RUN"], env["cycle"], "forecast")

    rc, seen = _run_post(env, fake_env)
    assert rc == 0
    assert len(seen) == 2

    data = _load_outputs_manifest(env)
    names = [p["name"] for p in data["products"]]
    assert names == ["stations_nc"]
