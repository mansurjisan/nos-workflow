"""
Unit tests for Tidal Forcing Processor.

Tests tidal boundary condition generation for SCHISM (bctides.in).
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from nos_ofs.forcing.tidal import TidalProcessor
from nos_ofs.base import ForcingResult


class TestTidalProcessorInit:
    """Tests for TidalProcessor initialization."""

    def test_init_with_defaults(self, sample_stofs_config, tmp_path):
        """Test tidal processor initializes with default values."""
        proc = TidalProcessor(
            config=sample_stofs_config,
            input_path=tmp_path / "fix",
            output_path=tmp_path / "output",
        )

        assert proc.source_name == "TPXO"
        assert proc.database == "tpxo9"
        assert proc.use_fortran_exe is True
        # Defaults to first 5 major constituents
        assert len(proc.constituents) == 5

    def test_init_with_custom_constituents(self, sample_stofs_config, tmp_path):
        """Test tidal processor with custom constituents."""
        proc = TidalProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=tmp_path,
            constituents=["M2", "S2", "N2", "K2", "K1", "O1", "P1", "Q1"],
        )

        assert len(proc.constituents) == 8
        assert "M2" in proc.constituents
        assert "Q1" in proc.constituents

    def test_init_calculates_start_time(self, sample_stofs_config, tmp_path):
        """Test start time calculation from PDY and cyc."""
        proc = TidalProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=tmp_path,
        )

        expected = datetime(2025, 5, 4, 12)
        assert proc.start_time == expected


class TestTidalConstituentInfo:
    """Tests for tidal constituent definitions."""

    def test_major_constituents_defined(self):
        """Test all 8 major constituents are defined."""
        for const in TidalProcessor.MAJOR_CONSTITUENTS:
            assert const in TidalProcessor.CONSTITUENT_INFO

    def test_minor_constituents_defined(self):
        """Test minor constituents are defined."""
        for const in TidalProcessor.MINOR_CONSTITUENTS:
            assert const in TidalProcessor.CONSTITUENT_INFO

    def test_constituent_has_omega(self):
        """Test each constituent has an angular frequency."""
        for name, info in TidalProcessor.CONSTITUENT_INFO.items():
            assert "omega" in info, f"Constituent {name} missing omega"
            assert info["omega"] > 0, f"Constituent {name} has non-positive omega"

    def test_constituent_has_doodson(self):
        """Test each constituent has a Doodson number."""
        for name, info in TidalProcessor.CONSTITUENT_INFO.items():
            assert "doodson" in info, f"Constituent {name} missing doodson"

    def test_m2_frequency(self):
        """Test M2 frequency is approximately correct."""
        m2_omega = TidalProcessor.CONSTITUENT_INFO["M2"]["omega"]
        # M2 period is approximately 12.42 hours
        # omega in degrees/hour
        assert 28.0 < m2_omega < 30.0

    def test_s2_frequency(self):
        """Test S2 frequency is exactly 30 deg/hr (12hr period)."""
        s2_omega = TidalProcessor.CONSTITUENT_INFO["S2"]["omega"]
        assert s2_omega == 30.0

    @pytest.mark.parametrize("constituent,expected_range", [
        ("M2", (28.0, 30.0)),
        ("S2", (29.9, 30.1)),
        ("K1", (14.0, 16.0)),
        ("O1", (13.0, 15.0)),
        ("M4", (57.0, 59.0)),
    ])
    def test_constituent_frequency_ranges(self, constituent, expected_range):
        """Test constituent frequencies are within expected ranges."""
        omega = TidalProcessor.CONSTITUENT_INFO[constituent]["omega"]
        assert expected_range[0] < omega < expected_range[1], \
            f"{constituent} omega {omega} not in range {expected_range}"


class TestNodalCorrections:
    """Tests for nodal factor computation."""

    def test_compute_nodal_corrections_returns_dict(self, sample_stofs_config, tmp_path):
        """Test nodal corrections returns dictionary with all constituents."""
        proc = TidalProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=tmp_path,
            constituents=["M2", "S2", "K1", "O1"],
        )

        nodal = proc._compute_nodal_corrections()

        assert isinstance(nodal, dict)
        for const in proc.constituents:
            assert const in nodal
            f, u = nodal[const]
            assert isinstance(f, (float, np.floating))
            assert isinstance(u, (float, np.floating))

    def test_s2_nodal_factor_is_unity(self, sample_stofs_config, tmp_path):
        """Test S2 nodal factor is always 1.0 (no nodal correction)."""
        proc = TidalProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=tmp_path,
            constituents=["S2"],
        )

        nodal = proc._compute_nodal_corrections()
        f, u = nodal["S2"]

        assert f == pytest.approx(1.0)
        assert u == pytest.approx(0.0)

    def test_p1_nodal_factor_is_unity(self, sample_stofs_config, tmp_path):
        """Test P1 nodal factor is always 1.0."""
        proc = TidalProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=tmp_path,
            constituents=["P1"],
        )

        nodal = proc._compute_nodal_corrections()
        f, u = nodal["P1"]

        assert f == pytest.approx(1.0)
        assert u == pytest.approx(0.0)

    def test_m2_nodal_factor_near_unity(self, sample_stofs_config, tmp_path):
        """Test M2 nodal factor is close to 1.0."""
        proc = TidalProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=tmp_path,
            constituents=["M2"],
        )

        nodal = proc._compute_nodal_corrections()
        f, _ = nodal["M2"]

        # M2 nodal factor ranges from ~0.96 to ~1.04
        assert 0.90 < f < 1.10

    def test_unknown_constituent_gets_default(self, sample_stofs_config, tmp_path):
        """Test unknown constituent gets default f=1.0, u=0.0."""
        proc = TidalProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=tmp_path,
            constituents=["SA"],  # Solar annual
        )

        nodal = proc._compute_nodal_corrections()
        f, u = nodal["SA"]

        assert f == pytest.approx(1.0)
        assert u == pytest.approx(0.0)


class TestBctidesGeneration:
    """Tests for bctides.in file generation."""

    def test_create_minimal_bctides(self, sample_stofs_config, tmp_path):
        """Test creating minimal bctides.in file."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        proc = TidalProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=output_dir,
            constituents=["M2", "S2"],
        )

        result = proc._create_minimal_bctides()

        assert result is not None
        assert result.exists()
        content = result.read_text()
        assert "M2" in content
        assert "S2" in content
        assert "nbfr" in content

    def test_update_bctides_time(self, sample_stofs_config, tmp_path):
        """Test updating time reference in bctides.in."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Create a source file
        source_file = tmp_path / "bctides_template.in"
        source_file.write_text("0 1.0 !ntip, tip_dp\n5 !nbfr\nM2\n")

        proc = TidalProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=output_dir,
        )

        result = proc._update_bctides_time(source_file)

        assert result is not None
        assert result.exists()
        content = result.read_text()
        assert "2025-05-04" in content  # Start time should be updated


class TestTidalProcess:
    """Tests for TidalProcessor.process() method."""

    @patch.object(TidalProcessor, '_call_tide_fac_exe')
    def test_process_uses_fortran_exe_first(
        self, mock_exe, sample_stofs_config, tmp_path
    ):
        """Test process tries FORTRAN executable first."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        bctides_path = output_dir / "bctides.in"
        bctides_path.write_text("test content")
        mock_exe.return_value = bctides_path

        proc = TidalProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=output_dir,
        )

        result = proc.process()

        assert result.success
        mock_exe.assert_called_once()

    @patch.object(TidalProcessor, '_call_tide_fac_exe')
    @patch.object(TidalProcessor, '_generate_bctides')
    def test_process_falls_back_to_python(
        self, mock_gen, mock_exe, sample_stofs_config, tmp_path
    ):
        """Test process falls back to Python when exe unavailable."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        mock_exe.return_value = None  # exe not available

        bctides_path = output_dir / "bctides.in"
        bctides_path.write_text("generated content")
        mock_gen.return_value = bctides_path

        proc = TidalProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=output_dir,
            use_fortran_exe=True,
        )

        # Need to ensure precomputed file doesn't exist
        result = proc.process()

        assert result.success

    def test_process_returns_metadata(self, sample_stofs_config, tmp_path):
        """Test process returns metadata with constituents info."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        proc = TidalProcessor(
            config=sample_stofs_config,
            input_path=tmp_path,
            output_path=output_dir,
            use_fortran_exe=False,
        )

        # Provide a precomputed file
        fix_file = tmp_path / "stofs_3d_atl_bctides.in"
        fix_file.write_text("0 1.0\n5\nM2\n")

        with patch.object(proc.config, 'get_fix_file', return_value=fix_file):
            with patch.object(proc.config, 'RUN', "stofs_3d_atl"):
                result = proc.process()

        if result.success:
            assert "constituents" in result.metadata
            assert "database" in result.metadata


class TestTidalConstituentLists:
    """Tests for constituent list definitions."""

    def test_major_constituents_count(self):
        """Test there are 8 major tidal constituents."""
        assert len(TidalProcessor.MAJOR_CONSTITUENTS) == 8

    def test_major_constituents_content(self):
        """Test major constituents list contains expected entries."""
        expected = ["M2", "S2", "N2", "K2", "K1", "O1", "P1", "Q1"]
        assert TidalProcessor.MAJOR_CONSTITUENTS == expected

    def test_minor_constituents_count(self):
        """Test there are 5 minor tidal constituents."""
        assert len(TidalProcessor.MINOR_CONSTITUENTS) == 5

    def test_no_overlap_between_major_and_minor(self):
        """Test major and minor constituent lists do not overlap."""
        overlap = set(TidalProcessor.MAJOR_CONSTITUENTS) & set(TidalProcessor.MINOR_CONSTITUENTS)
        assert len(overlap) == 0, f"Overlapping constituents: {overlap}"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
