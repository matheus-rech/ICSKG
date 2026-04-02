"""
Tests for SIOPS Health Expenditure Extraction (BEST EFFORT)
============================================================
Verifies:
  - Graceful degradation: writes empty Parquet on API failure
  - No exceptions raised on connection failure
  - If API returns data, normalize_cod_ibge is applied
"""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Test graceful degradation
# ---------------------------------------------------------------------------

class TestExtractSiopsGracefulDegradation:
    """Test that extract_siops writes empty schema Parquet on failure."""

    @patch("scripts.extract_siops._try_siops_api", return_value=None)
    @patch("scripts.extract_siops._try_siops_tabnet", return_value=None)
    def test_empty_parquet_on_api_failure(self, mock_tabnet, mock_api, tmp_path):
        """When all API/TabNet calls fail, should write empty Parquet with schema."""
        from scripts.extract_siops import extract_siops

        output = extract_siops(
            years=[2020, 2021],
            output_dir=tmp_path / "siops",
        )

        assert output.exists()
        df = pd.read_parquet(output)
        assert len(df) == 0, "Should be empty when API fails"
        expected_cols = {"cod_ibge", "year", "health_expenditure_per_capita"}
        assert expected_cols == set(df.columns), (
            f"Empty schema should have {expected_cols}, got {set(df.columns)}"
        )

    def test_no_exception_on_total_failure(self, tmp_path):
        """extract_siops should never raise, even with network errors."""
        from scripts.extract_siops import extract_siops

        with patch("scripts.extract_siops._try_siops_api", return_value=None), \
             patch("scripts.extract_siops._try_siops_tabnet", return_value=None):
            # Should not raise
            output = extract_siops(
                years=[2020],
                output_dir=tmp_path / "siops",
            )
            assert output.exists()


# ---------------------------------------------------------------------------
# Test normalize_cod_ibge applied
# ---------------------------------------------------------------------------

class TestSiopsNormalization:
    """Test that normalize_cod_ibge is applied when data is available."""

    @patch("scripts.extract_siops._try_siops_tabnet", return_value=None)
    def test_normalize_applied_on_success(self, mock_tabnet, tmp_path):
        """When API returns data, cod_ibge should be normalized to 7-digit."""
        from scripts.extract_siops import extract_siops

        # Create mock API response with 6-digit codes
        mock_df = pd.DataFrame({
            "cod_ibge": ["355030", "330455"],
            "year": [2020, 2020],
            "health_expenditure_per_capita": [500.0, 600.0],
        })

        with patch("scripts.extract_siops._try_siops_api", return_value=mock_df):
            output = extract_siops(
                years=[2020],
                output_dir=tmp_path / "siops",
            )

        assert output.exists()
        df = pd.read_parquet(output)

        if len(df) > 0:
            # All codes should be 7-digit strings after normalization
            for code in df["cod_ibge"].dropna():
                assert len(str(code)) == 7, (
                    f"cod_ibge should be 7 digits after normalize, got '{code}'"
                )


# ---------------------------------------------------------------------------
# Test output schema
# ---------------------------------------------------------------------------

class TestSiopsSchema:
    """Test that output always has the expected schema."""

    @patch("scripts.extract_siops._try_siops_api", return_value=None)
    @patch("scripts.extract_siops._try_siops_tabnet", return_value=None)
    def test_output_schema(self, mock_tabnet, mock_api, tmp_path):
        """Output Parquet should always have required columns."""
        from scripts.extract_siops import extract_siops

        output = extract_siops(
            years=[2020],
            output_dir=tmp_path / "siops",
        )

        df = pd.read_parquet(output)
        required = {"cod_ibge", "year", "health_expenditure_per_capita"}
        assert required.issubset(set(df.columns)), (
            f"Missing columns: {required - set(df.columns)}"
        )
