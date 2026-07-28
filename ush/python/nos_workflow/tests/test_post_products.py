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


def test_resolve_yaml_non_mapping_root_falls_back(tmp_path):
    """A YAML whose root is a list/scalar must not raise -- selection
    falls back to defaults instead of failing the stage."""
    yml = tmp_path / "sys.yaml"
    yml.write_text("- just\n- a\n- list\n")
    env = {"OFS_CONFIG": str(yml)}
    assert resolve_product_names("comf", env) == [
        "stations_nc", "bias_correct",
    ]


_PARM = Path(__file__).resolve().parents[4] / "parm" / "systems"


def test_shipped_yaml_station_products_match_each_system():
    """The two systems need different station products, and the wrong one
    cannot merely underperform -- it fails every cycle.

    stations_nc assembles SECOFS' 3D station profiles from staout_5..8,
    which on that build carry nvrt values per station plus nvrt
    z-coordinates on alternating lines. STOFS-3D-ATL writes one value per
    station per step in those same files, so the reshape has nothing to
    work with. ATL's product is points_cwl, which is also what ops
    publishes there.
    """
    from nos_workflow.post.registry import _read_yaml_post_products

    secofs = _read_yaml_post_products(_PARM / "secofs_ufs.yaml")
    assert "stations_nc" in secofs
    assert "points_cwl" not in secofs

    for name in ("stofs_3d_atl_ufs.yaml", "stofs_3d_atl_ufs_standalone.yaml"):
        atl = _read_yaml_post_products(_PARM / name)
        assert "points_cwl" in atl, name
        assert "stations_nc" not in atl, name


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


def test_product_returning_non_result_is_isolated(
    tmp_path, fake_env, registry_snapshot
):
    """A product whose produce() returns something other than a
    ProductResult is marked failed, not allowed to crash the driver."""

    @register
    class NoneProduct(PostProduct):
        name = "returns_none"

        def produce(self, ctx: ProductContext):
            return None

    env = _post_env(tmp_path)
    env["NOS_POST_PRODUCTS"] = "returns_none,stations_nc"
    comout = Path(env["COMOUT"])
    _seed_staout(comout, env["RUN"], env["cycle"], "nowcast")
    _seed_staout(comout, env["RUN"], env["cycle"], "forecast")

    rc, seen = _run_post(env, fake_env)
    assert rc == 0
    assert len(seen) == 2  # stations_nc still ran

    data = _load_outputs_manifest(env)
    by_name = {p["name"]: p for p in data["products"]}
    assert by_name["returns_none"]["status"] == "failed"
    assert "ProductResult" in by_name["returns_none"]["detail"]
    assert by_name["stations_nc"]["status"] == "ok"


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


# ---------------------------------------------------------------------------
# Canonical naming helpers
# ---------------------------------------------------------------------------


def test_naming_helpers():
    from nos_workflow.post.naming import (
        fields_stack_name,
        phase_mode_flag,
        product_stem,
        stations_nc_name,
    )

    assert product_stem("secofs", "00", "20260710") == "secofs.t00z.20260710"
    assert stations_nc_name("secofs", "00", "20260710", "nowcast") == (
        "secofs.t00z.20260710.stations.nowcast.nc"
    )
    assert fields_stack_name(
        "secofs", "00", "20260710", "out2d", "nowcast", 1, 6
    ) == "secofs.t00z.20260710.fields.out2d.n001_006.nc"
    assert fields_stack_name(
        "stofs_3d_atl", "12", "20260710", "temperature", "forecast", 25, 48
    ) == "stofs_3d_atl.t12z.20260710.fields.temperature.f025_048.nc"
    assert phase_mode_flag("nowcast") == "n"
    assert phase_mode_flag("forecast") == "f"
    with pytest.raises(ValueError):
        phase_mode_flag("bogus")


# ---------------------------------------------------------------------------
# archive_fields flag resolution
# ---------------------------------------------------------------------------


def test_resolve_archive_fields_env_precedence():
    from nos_workflow.post.registry import resolve_archive_fields

    assert resolve_archive_fields({"NOS_ARCHIVE_FIELDS": "YES"}) is True
    assert resolve_archive_fields({"NOS_ARCHIVE_FIELDS": "true"}) is True
    assert resolve_archive_fields({"NOS_ARCHIVE_FIELDS": "1"}) is True
    assert resolve_archive_fields({"NOS_ARCHIVE_FIELDS": "no"}) is False
    assert resolve_archive_fields({}) is False


def test_resolve_archive_fields_from_yaml(tmp_path):
    from nos_workflow.post.registry import resolve_archive_fields

    yml = tmp_path / "sys.yaml"
    yml.write_text("post:\n  archive_fields: true\n")
    assert resolve_archive_fields({"OFS_CONFIG": str(yml)}) is True

    yml.write_text("post:\n  archive_fields: false\n")
    assert resolve_archive_fields({"OFS_CONFIG": str(yml)}) is False
    # Env override beats the yaml.
    assert resolve_archive_fields(
        {"OFS_CONFIG": str(yml), "NOS_ARCHIVE_FIELDS": "yes"}
    ) is True


def test_post_mapping_merges_across_base_chain(tmp_path):
    """Overlay keys and base keys both surface through the _base merge."""
    from nos_workflow.post.registry import resolve_archive_fields

    base = tmp_path / "parent.yaml"
    base.write_text("post:\n  products:\n    - stations_nc\n")
    overlay = tmp_path / "child.yaml"
    overlay.write_text("_base: parent\npost:\n  archive_fields: true\n")
    env = {"OFS_CONFIG": str(overlay)}
    # products come from the base, the flag from the overlay.
    assert resolve_product_names("comf", env) == ["stations_nc"]
    assert resolve_archive_fields(env) is True


# ---------------------------------------------------------------------------
# fields_nc product wiring (worker subprocess mocked)
# ---------------------------------------------------------------------------


def _seed_field_staging(comout: Path, run: str, cycle: str, phase: str) -> Path:
    dir_name = "restart_outputs" if phase == "nowcast" else "forecast_outputs"
    staging = comout / f"{run}.{cycle}.{dir_name}"
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "out2d_1.nc").write_bytes(b"\x89HDF\r\n")
    return staging


def _fake_fields_subprocess(comout: Path):
    """Fake subprocess.run for the fields worker: drops the canonical
    file + result json the way the real worker would."""
    import subprocess as _sp

    calls: list = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        args = {cmd[i]: cmd[i + 1] for i in range(len(cmd) - 1)}
        phase = args.get("--phase", "nowcast")
        mode = "n" if phase == "nowcast" else "f"
        prefix = args.get("--prefix", "p")
        name = (
            f"{prefix}.t{args['--cyc']}z.{args['--pdy']}"
            f".fields.out2d.{mode}001_006.nc"
        )
        created = comout / name
        created.write_bytes(b"\x89HDF\r\n")
        result_json = args.get("--result-json")
        if result_json:
            Path(result_json).write_text(
                json.dumps({"created": [str(created)]})
            )
        return _sp.CompletedProcess(args=cmd, returncode=0)

    return fake_run, calls


def test_fields_nc_skipped_without_staged_stacks(tmp_path, fake_env):
    env = _post_env(tmp_path)
    env["NOS_POST_PRODUCTS"] = "fields_nc"
    # No staged field files anywhere.
    _seed_staout(Path(env["COMOUT"]), env["RUN"], env["cycle"], "nowcast")

    rc, seen = _run_post(env, fake_env)
    assert rc == 0
    assert len(seen) == 0  # worker never invoked

    data = _load_outputs_manifest(env)
    by_name = {p["name"]: p for p in data["products"]}
    assert by_name["fields_nc"]["status"] == "skipped"
    assert by_name["fields_nc"]["detail"] == "no field stacks staged"


def test_fields_nc_runs_worker_per_staged_phase(tmp_path, fake_env):
    env = _post_env(tmp_path)
    env["NOS_POST_PRODUCTS"] = "fields_nc"
    comout = Path(env["COMOUT"])
    # Stage nowcast only -> exactly one worker call.
    _seed_field_staging(comout, env["RUN"], env["cycle"], "nowcast")

    fake_run, calls = _fake_fields_subprocess(comout)
    with patch.dict(os.environ, env, clear=False):
        with patch.object(post_stage.subprocess, "run", side_effect=fake_run):
            rc = post_stage.run(_secofs_ufs_desc(), fake_env)

    assert rc == 0
    assert len(calls) == 1
    assert "-m" in calls[0] and "nos_workflow.post.products.fields" in calls[0]

    data = _load_outputs_manifest(env)
    by_name = {p["name"]: p for p in data["products"]}
    assert by_name["fields_nc"]["status"] == "ok"
    assert by_name["fields_nc"]["count"] == 1
    assert by_name["fields_nc"]["outputs"][0].endswith(
        ".fields.out2d.n001_006.nc"
    )


def test_fields_nc_worker_failure_warns_not_fatal(tmp_path, fake_env, caplog):
    import subprocess as _sp

    caplog.set_level("WARNING", logger="nos_workflow.stages.post")
    env = _post_env(tmp_path)
    env["NOS_POST_PRODUCTS"] = "fields_nc"
    comout = Path(env["COMOUT"])
    _seed_field_staging(comout, env["RUN"], env["cycle"], "nowcast")

    def failing_run(cmd, **kwargs):
        return _sp.CompletedProcess(args=cmd, returncode=4)

    with patch.dict(os.environ, env, clear=False):
        with patch.object(post_stage.subprocess, "run", side_effect=failing_run):
            rc = post_stage.run(_secofs_ufs_desc(), fake_env)

    assert rc == 0
    data = _load_outputs_manifest(env)
    by_name = {p["name"]: p for p in data["products"]}
    # Worker failure is non-fatal to the stage but surfaced in the
    # product status for monitoring.
    assert by_name["fields_nc"]["status"] == "failed"
    assert by_name["fields_nc"]["count"] == 0
    assert "nowcast" in by_name["fields_nc"]["detail"]
    assert any(
        "fields worker failed" in rec.getMessage() for rec in caplog.records
    )


# ---------------------------------------------------------------------------
# Product ordering: fields_nc materialises what the others read
# ---------------------------------------------------------------------------


def test_fields_nc_is_hoisted_ahead_of_its_consumers():
    """On the coupled path fields_nc splits the combined schout stacks
    that maxele/slab2d/geopkg/adcirc/profiles read, so it cannot be left
    to run after them just because the YAML lists it that way."""
    from nos_workflow.stages.post import _ordered_products

    assert _ordered_products(["maxele", "fields_nc", "slab2d"]) == [
        "fields_nc", "maxele", "slab2d",
    ]


def test_ordering_preserves_the_list_when_nothing_depends_on_fields():
    from nos_workflow.stages.post import _ordered_products

    names = ["stations_nc", "bias_correct", "fields_nc"]
    assert _ordered_products(names) == names


def test_ordering_leaves_consumers_alone_without_fields_nc():
    """No fields_nc means no split will happen; the consumers must still
    run (and fail loudly) rather than be quietly reordered or dropped."""
    from nos_workflow.stages.post import _ordered_products

    names = ["maxele", "slab2d"]
    assert _ordered_products(names) == names


def test_ordering_is_stable_for_the_rest():
    from nos_workflow.stages.post import _ordered_products

    assert _ordered_products(
        ["geopkg", "bias_correct", "fields_nc", "adcirc", "stations_nc"]
    ) == ["fields_nc", "geopkg", "bias_correct", "adcirc", "stations_nc"]


# ---------------------------------------------------------------------------
# Per-product options
# ---------------------------------------------------------------------------


def _ctx_with(options, shell_env=None, tmp_path=None):
    from nos_workflow.post.base import ProductContext

    base = tmp_path or Path("/tmp")
    return ProductContext(
        descriptor=None, shell_env=shell_env or {}, homenos=base,
        fixofs=base, comout=base, data=base, pdy="20260728", cyc="00",
        cycle="t00z", run_name="r", prefix_nos="p", nc_hour="18",
        sta_in=base / "s.in", combine_script=base / "c.py", pgmout="log",
        product_options=options,
    )


def _probe(name="profiles"):
    class Probe(PostProduct):
        def produce(self, ctx):  # pragma: no cover - never called
            return ProductResult(name=self.name, status="ok")

    Probe.name = name
    return Probe()


def test_option_precedence_is_env_then_yaml_then_default():
    prod = _probe()
    yaml_only = _ctx_with({"profiles": {"outside": "drop"}})
    assert prod.option(yaml_only, "outside", default="error") == "drop"

    # Env wins, so an operator can override config for one run -- same
    # precedence as NOS_POST_PRODUCTS over post.products.
    both = _ctx_with(
        {"profiles": {"outside": "drop"}},
        shell_env={"NOS_PROFILES_OUTSIDE": "nearest"},
    )
    assert prod.option(
        both, "outside", default="error", env_key="NOS_PROFILES_OUTSIDE"
    ) == "nearest"

    # An empty env var is not an override.
    empty = _ctx_with(
        {"profiles": {"outside": "drop"}},
        shell_env={"NOS_PROFILES_OUTSIDE": ""},
    )
    assert prod.option(
        empty, "outside", default="error", env_key="NOS_PROFILES_OUTSIDE"
    ) == "drop"

    assert prod.option(_ctx_with({}), "outside", default="error") == "error"
    # Options for another product must not leak.
    assert _probe("geopkg").option(
        _ctx_with({"profiles": {"outside": "drop"}}), "outside", default="error"
    ) == "error"


def test_options_parse_from_yaml_and_survive_an_env_name_override(tmp_path):
    from nos_workflow.post.registry import resolve_product_options

    yml = tmp_path / "sys.yaml"
    yml.write_text(
        "post:\n"
        "  products:\n"
        "    - stations_nc\n"
        "    - name: profiles\n"
        "      options:\n"
        "        outside: drop\n"
        "    - name: geopkg\n"
        "      options:\n"
        "        max_workers: 8\n"
    )
    env = {"OFS_CONFIG": str(yml)}
    assert resolve_product_options(env) == {
        "profiles": {"outside": "drop"},
        "geopkg": {"max_workers": 8},
    }

    # Selecting by env carries names only, so options must still resolve --
    # otherwise NOS_POST_PRODUCTS=profiles would silently lose outside=drop.
    env_override = dict(env, NOS_POST_PRODUCTS="profiles")
    assert resolve_product_names("comf", env_override) == ["profiles"]
    assert resolve_product_options(env_override)["profiles"] == {
        "outside": "drop"
    }


def test_malformed_options_are_ignored_not_fatal(tmp_path):
    from nos_workflow.post.registry import resolve_product_options

    yml = tmp_path / "sys.yaml"
    yml.write_text(
        "post:\n  products:\n    - name: profiles\n      options: not-a-map\n"
    )
    assert resolve_product_options({"OFS_CONFIG": str(yml)}) == {}
    assert resolve_product_options({}) == {}


def test_shipped_yaml_enables_only_what_has_been_validated():
    """SECOFS ran every one of these on a real coupled cycle. ATL has not,
    so it stays narrower."""
    from nos_workflow.post.registry import (
        _read_yaml_post_products, resolve_product_options,
    )

    secofs = _read_yaml_post_products(_PARM / "secofs_ufs.yaml")
    for name in ("maxele", "slab2d", "adcirc", "profiles", "geopkg"):
        assert name in secofs, name

    for name in ("stofs_3d_atl_ufs.yaml", "stofs_3d_atl_ufs_standalone.yaml"):
        atl = _read_yaml_post_products(_PARM / name)
        for ready in ("maxele", "slab2d", "adcirc"):
            assert ready in atl, (name, ready)
        # Held until timed / fix files staged on ATL.
        assert "geopkg" not in atl, name
        assert "profiles" not in atl, name


def test_no_system_enables_profiles_without_an_outside_setting():
    """A standing guard, not a snapshot: profiles defaults to ops parity
    (abort on one out-of-mesh station), so enabling it anywhere without
    saying what to do about that ships a product that fails every cycle."""
    from nos_workflow.post.registry import (
        _read_yaml_post_products, resolve_product_options,
    )

    checked = 0
    for yml in sorted(_PARM.glob("*.yaml")):
        names = _read_yaml_post_products(yml) or []
        if "profiles" not in names:
            continue
        checked += 1
        opts = resolve_product_options({"OFS_CONFIG": str(yml)})
        assert opts.get("profiles", {}).get("outside"), (
            f"{yml.name} enables profiles with no options.outside"
        )
    assert checked, "no system enables profiles -- guard would be vacuous"
