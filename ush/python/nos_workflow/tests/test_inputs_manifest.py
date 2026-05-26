"""Tests for the per-stage input-file manifest (nowcast/forecast/post).

The run-stage counterpart to the prep manifest in nos-utils. The JSON
shape is a cross-repo convention: per-group keys are exactly
``{category, source, count, files}`` (NO checksum/size/mtime), sorted by
``(category, source)``, files merged in add-order as ``str`` full paths.
"""
from __future__ import annotations

import json
from pathlib import Path

from nos_workflow.inputs_manifest import InputCollector, write_inputs_manifest


# ---------------------------------------------------------------------------
# InputCollector grouping
# ---------------------------------------------------------------------------


class TestCollectorGrouping:
    def test_grouped_by_category_and_source(self):
        c = InputCollector()
        c.add("hotstart", "HOTSTART", ["/d/hotstart.nc"])
        c.add("ocean", "OBC", ["/d/elev2D.th.nc", "/d/TEM_3D.th.nc"])
        c.add("river", "NWM", ["/d/vsource.th"])
        groups = c.groups()

        keyed = {(g["category"], g["source"]): g for g in groups}
        assert ("hotstart", "HOTSTART") in keyed
        assert ("ocean", "OBC") in keyed
        assert ("river", "NWM") in keyed
        obc = keyed[("ocean", "OBC")]
        assert obc["count"] == 2
        assert obc["files"] == ["/d/elev2D.th.nc", "/d/TEM_3D.th.nc"]

    def test_files_are_strings_full_paths(self):
        c = InputCollector()
        c.add("ocean", "OBC", [Path("/d/elev2D.th.nc"), Path("/d/uv3D.th.nc")])
        files = c.groups()[0]["files"]
        assert all(isinstance(f, str) for f in files)
        assert files == ["/d/elev2D.th.nc", "/d/uv3D.th.nc"]

    def test_keys_are_exactly_four_no_metadata(self):
        c = InputCollector()
        c.add("ocean", "OBC", ["/d/elev2D.th.nc"])
        for g in c.groups():
            assert set(g.keys()) == {"category", "source", "count", "files"}
            assert "checksum" not in g
            assert "size" not in g
            assert "mtime" not in g

    def test_same_group_merges_in_add_order(self):
        c = InputCollector()
        c.add("river", "RIVER", ["/d/flux.th"])
        c.add("river", "RIVER", ["/d/TEM_1.th"])
        rivers = [g for g in c.groups() if g["source"] == "RIVER"]
        assert len(rivers) == 1
        assert rivers[0]["count"] == 2
        assert rivers[0]["files"] == ["/d/flux.th", "/d/TEM_1.th"]

    def test_groups_sorted_by_category_then_source(self):
        c = InputCollector()
        c.add("tidal", "TIDAL", ["/d/bctides.in"])
        c.add("datm", "DATM", ["/d/datm.nc"])
        c.add("river", "NWM", ["/d/vsource.th"])
        c.add("river", "RIVER", ["/d/flux.th"])
        keys = [(g["category"], g["source"]) for g in c.groups()]
        assert keys == sorted(keys)

    def test_empty_group_count_zero(self):
        c = InputCollector()
        c.add("ocean", "OBC", [])
        groups = c.groups()
        assert len(groups) == 1
        assert groups[0]["count"] == 0
        assert groups[0]["files"] == []


# ---------------------------------------------------------------------------
# write_inputs_manifest
# ---------------------------------------------------------------------------


class TestManifestWrite:
    def test_nowcast_manifest_filename_and_keys(self, tmp_path):
        comout = tmp_path / "comout"
        comout.mkdir()
        c = InputCollector()
        c.add("hotstart", "HOTSTART", ["/d/hotstart.nc"])
        c.add("ocean", "OBC", ["/d/elev2D.th.nc", "/d/TEM_3D.th.nc"])

        path = write_inputs_manifest(
            comout=comout, run="nos.secofs_ufs", cyc="18", pdy="20260324",
            stage="nowcast", collector=c, phase="nowcast",
        )

        assert path is not None
        assert path.name == "nos.secofs_ufs.t18z.20260324.inputs.nowcast.json"

        data = json.loads(path.read_text())
        # Top-level keys match the cross-repo (P1) convention.
        assert data["ofs"] == "nos.secofs_ufs"
        assert data["pdy"] == "20260324"
        assert data["cyc"] == "18"
        assert data["stage"] == "nowcast"
        assert data["phase"] == "nowcast"
        assert data["schema_version"] == 1
        assert "generated_at" in data
        assert isinstance(data["inputs"], list)

        keyed = {(g["category"], g["source"]): g for g in data["inputs"]}
        assert keyed[("hotstart", "HOTSTART")]["count"] == 1
        assert keyed[("ocean", "OBC")]["count"] == 2
        # No per-file metadata leaked into the manifest.
        for g in data["inputs"]:
            assert set(g.keys()) == {"category", "source", "count", "files"}

    def test_forecast_stage_and_phase(self, tmp_path):
        comout = tmp_path / "comout"
        comout.mkdir()
        c = InputCollector()
        c.add("hotstart", "HOTSTART", ["/d/hotstart.nc"])

        path = write_inputs_manifest(
            comout=comout, run="nos.secofs_ufs", cyc="00", pdy="20260324",
            stage="forecast", collector=c, phase="forecast",
        )
        data = json.loads(path.read_text())
        assert path.name == "nos.secofs_ufs.t00z.20260324.inputs.forecast.json"
        assert data["stage"] == "forecast"
        assert data["phase"] == "forecast"

    def test_post_phase_is_null(self, tmp_path):
        comout = tmp_path / "comout"
        comout.mkdir()
        c = InputCollector()
        c.add("model_output", "STAOUT_NOWCAST", ["/c/staout_1"])

        path = write_inputs_manifest(
            comout=comout, run="nos.secofs_ufs", cyc="12", pdy="20260324",
            stage="post", collector=c, phase=None,
        )
        data = json.loads(path.read_text())
        assert path.name == "nos.secofs_ufs.t12z.20260324.inputs.post.json"
        assert data["stage"] == "post"
        # phase serializes to JSON null.
        assert data["phase"] is None

    def test_shape_matches_prep_p1_convention(self, tmp_path):
        """Top-level keys must be the exact set the prep manifest emits."""
        comout = tmp_path / "comout"
        comout.mkdir()
        c = InputCollector()
        c.add("ocean", "OBC", ["/d/elev2D.th.nc"])

        path = write_inputs_manifest(
            comout=comout, run="stofs_3d_atl_ufs", cyc="06", pdy="20260324",
            stage="nowcast", collector=c, phase="nowcast",
        )
        data = json.loads(path.read_text())
        assert set(data.keys()) == {
            "ofs", "pdy", "cyc", "stage", "phase",
            "schema_version", "generated_at", "inputs",
        }

    def test_comout_none_returns_none_no_raise(self):
        c = InputCollector()
        c.add("ocean", "OBC", ["/d/elev2D.th.nc"])
        result = write_inputs_manifest(
            comout=None, run="nos.secofs_ufs", cyc="00", pdy="20260324",
            stage="nowcast", collector=c, phase="nowcast",
        )
        assert result is None

    def test_unwritable_comout_returns_none_no_raise(self, tmp_path):
        # comout points at a regular file, so opening the manifest path
        # (treating it as a directory child) raises OSError internally.
        not_a_dir = tmp_path / "not_a_dir"
        not_a_dir.write_text("i am a file\n")
        c = InputCollector()
        c.add("ocean", "OBC", ["/d/elev2D.th.nc"])
        result = write_inputs_manifest(
            comout=not_a_dir, run="nos.secofs_ufs", cyc="00", pdy="20260324",
            stage="nowcast", collector=c, phase="nowcast",
        )
        assert result is None
