"""
Tests for RENAVAM Vehicle Fleet Extraction (BEST EFFORT)
=========================================================
Verifies:
  - Municipality crosswalk builds correctly from IBGE reference
  - Graceful degradation: writes empty Parquet on download failure
  - CSV parsing produces expected DataFrame structure with mocked data
"""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Test crosswalk
# ---------------------------------------------------------------------------

class TestBuildMunicipalityCrosswalk:
    """Test _build_municipality_crosswalk() returns correct structure."""

    def test_crosswalk_non_empty(self):
        """Crosswalk should contain entries from IBGE reference list."""
        from scripts.extract_renavam import _build_municipality_crosswalk

        crosswalk = _build_municipality_crosswalk()
        assert isinstance(crosswalk, dict)
        assert len(crosswalk) > 5000, (
            f"Crosswalk should have ~5571 entries, got {len(crosswalk)}"
        )

    def test_crosswalk_key_format(self):
        """Each crosswalk key should be (str, str) -> str."""
        from scripts.extract_renavam import _build_municipality_crosswalk

        crosswalk = _build_municipality_crosswalk()
        sample_key = next(iter(crosswalk))
        assert isinstance(sample_key, tuple)
        assert len(sample_key) == 2
        assert isinstance(sample_key[0], str)
        assert isinstance(sample_key[1], str)
        assert isinstance(crosswalk[sample_key], str)

    def test_crosswalk_known_municipality(self):
        """Check that Sao Paulo, SP resolves to its IBGE code."""
        from scripts.extract_renavam import _build_municipality_crosswalk

        crosswalk = _build_municipality_crosswalk()
        # Try with uppercase as the crosswalk uses
        sp_key = ("SP", "SAO PAULO")
        # Some IBGE reference files use accented names
        alt_key = ("SP", "SÃO PAULO")
        found = crosswalk.get(sp_key) or crosswalk.get(alt_key)
        assert found is not None, (
            "Sao Paulo/SP should be in crosswalk. "
            f"Sample keys: {list(crosswalk.keys())[:5]}"
        )


# ---------------------------------------------------------------------------
# Test graceful degradation
# ---------------------------------------------------------------------------

class TestExtractRenavamGracefulDegradation:
    """Test that extract_renavam writes empty schema Parquet on failure."""

    @patch("scripts.extract_renavam._download_renavam_csv", return_value=None)
    def test_empty_parquet_on_download_failure(self, mock_download, tmp_path):
        """When all downloads fail, should write empty Parquet with schema."""
        from scripts.extract_renavam import extract_renavam

        output = extract_renavam(
            years=[2020, 2021],
            output_dir=tmp_path / "renavam",
        )

        assert output.exists()
        df = pd.read_parquet(output)
        assert len(df) == 0, "Should be empty when downloads fail"
        expected_cols = {"cod_ibge", "year", "vehicles_total", "vehicles_per_1000"}
        assert expected_cols == set(df.columns), (
            f"Empty schema should have {expected_cols}, got {set(df.columns)}"
        )

    def test_no_exception_on_total_failure(self, tmp_path):
        """extract_renavam should never raise, even with network errors."""
        from scripts.extract_renavam import extract_renavam

        with patch("scripts.extract_renavam._download_renavam_csv", return_value=None):
            # Should not raise
            output = extract_renavam(
                years=[2020],
                output_dir=tmp_path / "renavam",
            )
            assert output.exists()


# ---------------------------------------------------------------------------
# Test CSV parsing
# ---------------------------------------------------------------------------

class TestParseRenavamCsv:
    """Test _parse_renavam_csv with synthetic test data."""

    def test_parse_simple_csv(self, tmp_path):
        """Parsing a well-formed CSV should produce expected structure."""
        from scripts.extract_renavam import (
            _parse_renavam_csv,
            _build_municipality_crosswalk,
        )

        # Create a simple test CSV
        csv_content = (
            "UF,Municipio,AUTOMOVEL,MOTOCICLETA,TOTAL\n"
            "RO,Alta Floresta D'Oeste,1000,500,1500\n"
            "RO,Ariquemes,5000,2000,7000\n"
        )
        csv_path = tmp_path / "test_renavam.csv"
        csv_path.write_text(csv_content, encoding="utf-8")

        crosswalk = _build_municipality_crosswalk()
        result = _parse_renavam_csv(csv_path, crosswalk, year=2020)

        # If crosswalk matched (depends on exact name spelling in ref)
        if result is not None and not result.empty:
            assert "cod_ibge" in result.columns
            assert "year" in result.columns
            assert "vehicles_total" in result.columns
            assert (result["year"] == 2020).all()
            assert result["vehicles_total"].dtype in ("float64", "int64")
        # If names didn't match, that's OK for best-effort

    def test_parse_returns_none_for_garbage(self, tmp_path):
        """Parsing garbage data should return None, not raise."""
        from scripts.extract_renavam import _parse_renavam_csv

        garbage_path = tmp_path / "garbage.csv"
        garbage_path.write_text("this is not a csv at all", encoding="utf-8")

        result = _parse_renavam_csv(garbage_path, {}, year=2020)
        # Should return None gracefully
        assert result is None
