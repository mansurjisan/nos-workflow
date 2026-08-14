"""Integration tests for ``parm/{base,systems}/`` YAML configs.

Ported from the legacy ``ush/python/tests/test_yaml_configs.py``.

Every assertion that targets an OFS not yet present in the new tree
``skip``s rather than failing — we want the suite to grow naturally as
descriptors come back online without forcing this file to track them
manually.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, Iterator

import pytest
import yaml

# Make ``nos_workflow`` importable regardless of CWD.
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "nos-utils"))

from nos_utils.config import ForcingConfig  # noqa: E402
from nos_workflow.utils.yaml_to_env import (  # noqa: E402
    load_yaml_with_inheritance,
)


# ---------------------------------------------------------------------------
# Local fixtures (the package conftest only ships ``clean_env``)
# ---------------------------------------------------------------------------


def _repo_parm_dir() -> Path:
    """Walk up from this test file to the ``parm/`` directory.

    Layout:
        <repo>/parm/...
        <repo>/ush/python/nos_workflow/tests/test_yaml_configs.py

    so the parm dir is four levels up.
    """
    here = Path(__file__).resolve()
    return here.parents[4] / "parm"


@pytest.fixture
def parm_dir() -> Path:
    """Return the repository's ``parm/`` directory."""
    return _repo_parm_dir()


@pytest.fixture
def base_configs(parm_dir: Path) -> Dict[str, Path]:
    """Return paths to base model configs (may not all exist yet)."""
    base = parm_dir / "base"
    return {
        "schism": base / "schism.yaml",
        "fvcom": base / "fvcom.yaml",
        "roms": base / "roms.yaml",
    }


@pytest.fixture
def system_configs(parm_dir: Path) -> Dict[str, Path]:
    """Return paths to every system YAML present under ``parm/systems/``."""
    systems = parm_dir / "systems"
    configs: Dict[str, Path] = {}
    if systems.exists():
        for yaml_file in systems.glob("*.yaml"):
            configs[yaml_file.stem] = yaml_file
    return configs


# ---------------------------------------------------------------------------
# Base configs
# ---------------------------------------------------------------------------


class TestBaseConfigs:
    """Tests for base model configuration files."""

    def test_schism_base_exists(self, base_configs: Dict[str, Path]) -> None:
        if "schism" in base_configs and base_configs["schism"].exists():
            assert base_configs["schism"].exists()
        else:
            pytest.skip("schism.yaml not found")

    def test_fvcom_base_exists(self, base_configs: Dict[str, Path]) -> None:
        if "fvcom" in base_configs and base_configs["fvcom"].exists():
            assert base_configs["fvcom"].exists()
        else:
            pytest.skip("fvcom.yaml not found")

    def test_roms_base_exists(self, base_configs: Dict[str, Path]) -> None:
        if "roms" in base_configs and base_configs["roms"].exists():
            assert base_configs["roms"].exists()
        else:
            pytest.skip("roms.yaml not found")

    def test_base_configs_valid_yaml(self, base_configs: Dict[str, Path]) -> None:
        found_any = False
        for name, path in base_configs.items():
            if path.exists():
                found_any = True
                with open(path) as f:
                    data = yaml.safe_load(f)
                assert isinstance(data, dict), f"{name} config should be a dict"
        if not found_any:
            pytest.skip("No base configs found")


# ---------------------------------------------------------------------------
# System configs
# ---------------------------------------------------------------------------


class TestSystemConfigs:
    """Tests for system configuration files."""

    def test_system_configs_exist(self, system_configs: Dict[str, Path]) -> None:
        if len(system_configs) == 0:
            pytest.skip("No system configs found in parm/systems/")

    def test_secofs_ufs_config(self, system_configs: Dict[str, Path]) -> None:
        """SECOFS-UFS is the canonical OFS in the new tree."""
        if "secofs_ufs" not in system_configs:
            pytest.skip("secofs_ufs.yaml not found")

        path = system_configs["secofs_ufs"]
        with open(path) as f:
            data = yaml.safe_load(f)

        assert "system" in data
        assert data["system"]["name"] == "secofs_ufs"
        assert data["system"]["framework"] == "comf"

    def test_stofs_3d_atl_ufs_config(self, system_configs: Dict[str, Path]) -> None:
        """STOFS-3D-ATL on UFS-Coastal — SCHISM + CDEPS DATM via NUOPC.

        Locks the production-vintage values: framework label, total/per-component
        rank counts, v2.1 operational grid dimensions, and the PBS ``select=``
        line. These are pinned because the runtime dispatcher and the PBS
        jobcard generator both depend on them — drifting any of these silently
        is the kind of bug that only surfaces inside a 4434-rank allocation.

        Grid dimensions match the v2.1 operational STOFS-3D-ATL mesh extracted
        from /lfs/h1/ops/prod/com/stofs/v2.1/.../rerun/*.restart.nc on
        2026-05-11. The UFS rank layout uses the operational 4314 SCHISM OCN
        ranks (+120 DATM = 4434 total), sharing the standalone 4314 partition.prop.
        """
        if "stofs_3d_atl_ufs" not in system_configs:
            pytest.skip("stofs_3d_atl_ufs.yaml not found")

        path = system_configs["stofs_3d_atl_ufs"]
        with open(path) as f:
            data = yaml.safe_load(f)

        # Identity
        assert "system" in data
        assert data["system"]["name"] == "stofs_3d_atl_ufs"
        assert data["system"]["framework"] == "stofs_ufs"

        # Resources / UFS-Coastal task split (v2.1 operational partition.prop)
        ufs = data.get("ufs_coastal", {})
        assert ufs.get("total_tasks") == 4434
        assert ufs.get("schism_tasks") == 4314
        assert ufs.get("datm_tasks") == 120
        assert ufs.get("nscribes") == 0

        # Grid dimensions (v2.1 operational mesh)
        grid = data.get("grid", {})
        assert grid.get("n_nodes") == 2926236
        assert grid.get("n_elements") == 5654157
        assert grid.get("n_sides") == 8580540
        assert grid.get("n_levels") == 49

        # PBS select — operational ppn=120 + ompthreads=1 packing (37 nodes, 4440 >= 4434)
        det = data.get("resources", {})
        select_str = det.get("select")
        assert select_str == "select=37:ncpus=128:mpiprocs=120:ompthreads=1"

    def test_secofs_ufs_ww3_config(self, system_configs: Dict[str, Path]) -> None:
        """SECOFS-UFS-WW3 -- DATM+SCHISM+WW3 4-component coupled variant.

        Pins the AK-validated 4-component task split (nos-utils
        UFSConfigProcessor._patch_pet_bounds cross-checks this exact
        invariant at prep time: datm + schism + wav must equal total, or
        the PET-bounds patch is rejected and ufs.configure is left
        unpatched). Also pins that system.prefix stays "secofs_ufs"
        (unchanged from the base) so this variant reuses the exact same
        SCHISM-side fix filenames (hgrid, bctides, nudging, river, tidal)
        as secofs_ufs -- only $FIXofs itself and the wave/coupling keys
        differ.
        """
        if "secofs_ufs_ww3" not in system_configs:
            pytest.skip("secofs_ufs_ww3.yaml not found")

        path = system_configs["secofs_ufs_ww3"]
        merged = load_yaml_with_inheritance(path, base_dir=path.parent.parent)

        assert merged["system"]["name"] == "secofs_ufs_ww3"
        assert merged["system"]["framework"] == "comf"
        assert merged["system"]["prefix"] == "secofs_ufs"

        ufs = merged["ufs_coastal"]
        assert ufs["datm_tasks"] == 120
        assert ufs["schism_tasks"] == 2794
        assert ufs["wav_tasks"] == 2606
        assert ufs["total_tasks"] == 5520
        # The wave variant's invariant: datm + schism + wav == total.
        assert ufs["datm_tasks"] + ufs["schism_tasks"] + ufs["wav_tasks"] == ufs["total_tasks"]
        # Coupling interval must be an integer multiple of model.physics.dt
        # (nos-utils UFSConfigProcessor._patch_runseq_interval enforces this
        # at prep time; SCHISM can only land on whole-extstep boundaries).
        assert ufs["coupling_interval"] % merged["model"]["physics"]["dt"] == 0
        assert ufs["wav_model"] == "ww3"
        # mesh_wav must match ufs.configure's WAV_attributes::mesh_wav line
        # (fix/secofs_ufs_ww3/ufs.configure) -- this is the only place the
        # two are cross-checked in-repo.
        assert ufs["wav_mesh"] == "secofs_ufs.mesh_wav.nc"
        # ocn2wav_weights must match ufs.configure's
        # MED_attributes::ocn2wav_smapname line (same file) -- the
        # precomputed ocn->wav regrid weight file.
        assert ufs["ocn2wav_weights"] == "secofs_ufs.ocn2wav_weights.nc"

        assert merged["model"]["executable"] == "fv3_coastalSW.exe"
        assert merged["model"]["runtime"]["ctl_file"] == "secofs_ufs_ww3.param.nml"

        det = merged["resources"]
        assert det["nprocs"] == ufs["total_tasks"]
        assert det["select"] == "select=46:ncpus=128:mpiprocs=120:ompthreads=1"

        assert merged["ensemble"]["enabled"] is False

        # forcing.waves: GFS-Wave boundary spectra (nos-utils
        # WaveBoundaryProcessor). Deep-merged onto secofs_ufs's inherited
        # forcing block -- prove the other forcing sources survive the merge.
        waves = merged["forcing"]["waves"]
        assert waves["enabled"] is True
        window = waves["window"]
        assert window["lon_min"] < window["lon_max"]
        assert window["lat_min"] < window["lat_max"]
        # Window must bracket the mesh's own open-boundary extent (both
        # segments; see the yaml's own comment for the census this window
        # is grounded in).
        assert window["lon_min"] < -87.09 and window["lon_max"] > -64.00
        assert window["lat_min"] < 17.54 and window["lat_max"] > 37.92
        assert waves.get("extra_points") in (None, [])
        assert waves["points_file"] == "secofs_ufs.ww3_bound_points.list"
        assert waves["max_cycle_fallback"] >= 1
        # Deliberately not critical: WAVE_BC must stay out of prep.critical_sources
        # so a late/missing gfswave product degrades prep instead of failing it.
        assert "prep" not in merged or "critical_sources" not in merged.get("prep", {})
        # Other inherited forcing sources must survive the deep-merge.
        assert "atmospheric" in merged["forcing"]
        assert "river" in merged["forcing"]

    def test_stofs_3d_ak_ufs_rtofs_region(
        self,
        system_configs: Dict[str, Path],
    ) -> None:
        """Alaska must never fall back to another regional RTOFS 3-D tile."""
        if "stofs_3d_ak_ufs" not in system_configs:
            pytest.skip("stofs_3d_ak_ufs.yaml not found")

        path = system_configs["stofs_3d_ak_ufs"]
        with open(path) as f:
            data = yaml.safe_load(f)

        assert data["forcing"]["ocean"]["rtofs_3d_region"] == "alaska"
        assert ForcingConfig.from_yaml(path).rtofs_3d_region == "alaska"

    def test_stofs_3d_atl_config(self, system_configs: Dict[str, Path]) -> None:
        if "stofs_3d_atl" not in system_configs:
            pytest.skip("stofs_3d_atl.yaml not found")

        path = system_configs["stofs_3d_atl"]
        with open(path) as f:
            data = yaml.safe_load(f)

        assert "system" in data
        assert data["system"]["name"] == "stofs_3d_atl"
        assert data["system"]["framework"] == "stofs"

        assert "grid" in data
        assert "domain" in data["grid"]
        assert data["grid"]["domain"]["lon_min"] < data["grid"]["domain"]["lon_max"]

    def test_secofs_config(self, system_configs: Dict[str, Path]) -> None:
        if "secofs" not in system_configs:
            pytest.skip("secofs.yaml not found")

        path = system_configs["secofs"]
        with open(path) as f:
            data = yaml.safe_load(f)

        assert "system" in data
        assert data["system"]["name"] == "secofs"
        assert data["system"]["framework"] == "comf"

    def test_cbofs_config(self, system_configs: Dict[str, Path]) -> None:
        if "cbofs" not in system_configs:
            pytest.skip("cbofs.yaml not found")

        path = system_configs["cbofs"]
        with open(path) as f:
            data = yaml.safe_load(f)

        assert "system" in data
        assert data["system"]["name"] == "cbofs"
        assert data["_base"] == "roms"
        assert data["model"]["ocean_model"] == "ROMS"
        assert data["execution"]["mode"] == "standalone"

    def test_leofs_config(self, system_configs: Dict[str, Path]) -> None:
        if "leofs" not in system_configs:
            pytest.skip("leofs.yaml not found")

        path = system_configs["leofs"]
        with open(path) as f:
            data = yaml.safe_load(f)

        assert "system" in data
        assert data["system"]["name"] == "leofs"
        assert data["_base"] == "fvcom"
        if "forcing" in data and "ocean" in data["forcing"]:
            assert data["forcing"]["ocean"].get("enabled", True) is False

    def test_creofs_config(self, system_configs: Dict[str, Path]) -> None:
        if "creofs" not in system_configs:
            pytest.skip("creofs.yaml not found")

        path = system_configs["creofs"]
        with open(path) as f:
            data = yaml.safe_load(f)

        assert "system" in data
        assert data["system"]["name"] == "creofs"
        assert data["_base"] == "schism"
        assert data["system"]["framework"] == "comf"

    def test_dbofs_config(self, system_configs: Dict[str, Path]) -> None:
        if "dbofs" not in system_configs:
            pytest.skip("dbofs.yaml not found")

        path = system_configs["dbofs"]
        with open(path) as f:
            data = yaml.safe_load(f)

        assert "system" in data
        assert data["system"]["name"] == "dbofs"
        assert data["_base"] == "roms"
        assert data["model"]["ocean_model"] == "ROMS"
        assert data["execution"]["mode"] == "standalone"

    def test_ngofs2_config(self, system_configs: Dict[str, Path]) -> None:
        if "ngofs2" not in system_configs:
            pytest.skip("ngofs2.yaml not found")

        path = system_configs["ngofs2"]
        with open(path) as f:
            data = yaml.safe_load(f)

        assert "system" in data
        assert data["system"]["name"] == "ngofs2"
        assert data["_base"] == "fvcom"
        assert data["model"]["ocean_model"] == "FVCOM"
        assert data["execution"]["mode"] == "standalone"

    def test_stofs_3d_pac_config(self, system_configs: Dict[str, Path]) -> None:
        if "stofs_3d_pac" not in system_configs:
            pytest.skip("stofs_3d_pac.yaml not found")

        path = system_configs["stofs_3d_pac"]
        with open(path) as f:
            data = yaml.safe_load(f)

        assert "system" in data
        assert data["system"]["name"] == "stofs_3d_pac"
        assert data["system"]["framework"] == "stofs"
        if "forcing" in data and "atmospheric" in data["forcing"]:
            hrrr = data["forcing"]["atmospheric"].get("hrrr_blend", {})
            assert hrrr.get("enabled", True) is False

    def test_all_configs_valid_yaml(self, system_configs: Dict[str, Path]) -> None:
        if len(system_configs) == 0:
            pytest.skip("No system configs found")
        for name, path in system_configs.items():
            with open(path) as f:
                data = yaml.safe_load(f)
            assert isinstance(data, dict), f"{name} config should be a dict"

    def test_all_configs_have_system_name(self, system_configs: Dict[str, Path]) -> None:
        if len(system_configs) == 0:
            pytest.skip("No system configs found")
        for name, path in system_configs.items():
            # Resolve inheritance: a thin variant (e.g. the standalone yaml)
            # gets its system.name from the system config it _base-inherits.
            data = load_yaml_with_inheritance(path, base_dir=path.parent.parent)
            assert "system" in data, f"{name} missing system section"
            assert "name" in data["system"], f"{name} missing system.name"

    def test_all_configs_have_base_or_model(self, system_configs: Dict[str, Path]) -> None:
        if len(system_configs) == 0:
            pytest.skip("No system configs found")
        for name, path in system_configs.items():
            with open(path) as f:
                data = yaml.safe_load(f)
            has_base = "_base" in data
            has_model = "model" in data
            assert has_base or has_model, f"{name} missing _base or model section"


# ---------------------------------------------------------------------------
# Inheritance + bounds sanity
# ---------------------------------------------------------------------------


class TestConfigInheritance:
    """Tests for configuration inheritance."""

    def test_base_reference_valid(
        self,
        system_configs: Dict[str, Path],
        base_configs: Dict[str, Path],
    ) -> None:
        if len(system_configs) == 0:
            pytest.skip("No system configs found")
        for name, path in system_configs.items():
            with open(path) as f:
                data = yaml.safe_load(f)

            if "_base" in data:
                base_name = data["_base"]
                # A system config may inherit an abstract base (parm/base/)
                # or another system config (parm/systems/) -- e.g. the
                # standalone variant inheriting stofs_3d_atl_ufs.
                valid = base_name in base_configs or base_name in system_configs
                assert valid, (
                    f"{name} references unknown base config: {base_name}"
                )


class TestDomainBounds:
    """Tests for domain bound validation."""

    def test_domain_lon_order(self, system_configs: Dict[str, Path]) -> None:
        if len(system_configs) == 0:
            pytest.skip("No system configs found")
        for name, path in system_configs.items():
            with open(path) as f:
                data = yaml.safe_load(f)

            if "grid" in data and "domain" in data["grid"]:
                domain = data["grid"]["domain"]
                if "lon_min" in domain and "lon_max" in domain:
                    if domain["lon_min"] == -180.0:
                        # Wrapped (Pacific) domain — skip.
                        pass
                    else:
                        assert domain["lon_min"] < domain["lon_max"], (
                            f"{name}: lon_min should be less than lon_max"
                        )

    def test_domain_lat_order(self, system_configs: Dict[str, Path]) -> None:
        if len(system_configs) == 0:
            pytest.skip("No system configs found")
        for name, path in system_configs.items():
            with open(path) as f:
                data = yaml.safe_load(f)

            if "grid" in data and "domain" in data["grid"]:
                domain = data["grid"]["domain"]
                if "lat_min" in domain and "lat_max" in domain:
                    assert domain["lat_min"] < domain["lat_max"], (
                        f"{name}: lat_min should be less than lat_max"
                    )


class TestWaveFixFiles:
    """``fix/secofs_ufs_ww3/`` static content that isn't per-cycle patched."""

    def test_ww3_shel_point_output_disabled(self) -> None:
        """``date%point%stride`` must be '0' (point output OFF): no
        SECOFS wave-station list exists yet, and WW3 opens
        ``type%point%file`` unconditionally whenever the stride is
        non-zero -- a non-existent ``ww3_points.list`` then hard-aborts
        WW3 (EXTCDE 1104) after the allocation is already up. The
        ``type%point%file`` line itself may stay (harmless -- never
        opened while the stride is 0), but the stride is the load-bearing
        value and must not silently flip back to non-zero.
        """
        repo_root = Path(__file__).resolve().parents[4]
        ww3_shel = repo_root / "fix" / "secofs_ufs_ww3" / "ww3_shel.nml"
        if not ww3_shel.is_file():
            pytest.skip("fix/secofs_ufs_ww3/ww3_shel.nml not found")

        text = ww3_shel.read_text()
        assert "date%point%stride   = '0'" in text
        # Nothing patches the point stride at run time -- confirm it isn't
        # a @[...]-style placeholder either.
        assert "@[" not in text.split("date%point%stride")[1].split("\n")[0]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
