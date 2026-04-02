"""
Tests for database/deflate_ipca.py — IPCA deflation module.

Covers:
  - fetch_ipca_annual_index returns correct structure and base_year factor == 1.0
  - deflate_column preserves original as {col}_nominal
  - deflate_column leaves NaN values as NaN
"""

from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Fixtures — mock SIDRA response
# ---------------------------------------------------------------------------

def _make_sidra_response() -> pd.DataFrame:
    """Build a mock DataFrame mimicking sidrapy.get_table() output for table 1737.

    sidrapy returns a DataFrame where index 0 is a header row and subsequent
    rows contain the actual data.  Columns of interest:
      - D2C : period code (e.g., "201512" for Dec 2015)
      - V   : accumulated IPCA index value
    """
    rows = [
        # header row (index 0) — skipped in processing
        {"D2C": "Mês (Código)", "V": "Valor"},
    ]
    # December values for 2015-2023 (fabricated but structurally correct)
    dec_values = {
        2015: 4635.46,
        2016: 4936.86,
        2017: 5082.69,
        2018: 5271.38,
        2019: 5499.12,
        2020: 5753.27,
        2021: 6332.89,
        2022: 6697.74,
        2023: 7010.00,  # base year → factor = 1.0
    }
    for year, val in dec_values.items():
        rows.append({"D2C": f"{year}12", "V": str(val)})
        # Add non-December months to verify they are filtered out
        rows.append({"D2C": f"{year}06", "V": str(val * 0.97)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Test: fetch_ipca_annual_index
# ---------------------------------------------------------------------------

class TestFetchIpcaAnnualIndex:
    """Tests for fetch_ipca_annual_index()."""

    @patch("database.deflate_ipca.sidrapy")
    def test_deflation_factor_base_year_is_one(self, mock_sidrapy):
        """Base year (2023) deflation factor must be exactly 1.0."""
        mock_sidrapy.get_table.return_value = _make_sidra_response()

        from database.deflate_ipca import fetch_ipca_annual_index

        result = fetch_ipca_annual_index(
            years=list(range(2015, 2024)), base_year=2023
        )

        assert isinstance(result, pd.DataFrame)
        assert "year" in result.columns
        assert "ipca_index" in result.columns
        assert "deflation_factor" in result.columns

        row_2023 = result[result["year"] == 2023]
        assert len(row_2023) == 1
        assert row_2023["deflation_factor"].iloc[0] == pytest.approx(1.0)

    @patch("database.deflate_ipca.sidrapy")
    def test_deflation_factors_increase_for_older_years(self, mock_sidrapy):
        """Older years should have deflation_factor > 1.0 (prices were lower)."""
        mock_sidrapy.get_table.return_value = _make_sidra_response()

        from database.deflate_ipca import fetch_ipca_annual_index

        result = fetch_ipca_annual_index(
            years=list(range(2015, 2024)), base_year=2023
        )

        for year in range(2015, 2023):
            factor = result.loc[result["year"] == year, "deflation_factor"].iloc[0]
            assert factor > 1.0, (
                "deflation_factor for %d should be > 1.0, got %f" % (year, factor)
            )

    @patch("database.deflate_ipca.sidrapy")
    def test_returns_only_requested_years(self, mock_sidrapy):
        """Result should contain only the requested year range."""
        mock_sidrapy.get_table.return_value = _make_sidra_response()

        from database.deflate_ipca import fetch_ipca_annual_index

        result = fetch_ipca_annual_index(years=[2020, 2021, 2022, 2023], base_year=2023)
        assert set(result["year"].tolist()) == {2020, 2021, 2022, 2023}


# ---------------------------------------------------------------------------
# Test: deflate_column
# ---------------------------------------------------------------------------

class TestDeflateColumn:
    """Tests for deflate_column()."""

    def test_deflate_column_preserves_nominal(self):
        """Original values must be preserved in {col}_nominal column."""
        from database.deflate_ipca import deflate_column

        df = pd.DataFrame({
            "year": [2020, 2021, 2022, 2023],
            "gdp_per_capita": [1000.0, 1100.0, 1200.0, 1300.0],
        })
        factors = pd.Series(
            {2020: 1.5, 2021: 1.3, 2022: 1.1, 2023: 1.0}
        )

        result = deflate_column(df, "gdp_per_capita", factors)

        assert "gdp_per_capita_nominal" in result.columns
        pd.testing.assert_series_equal(
            result["gdp_per_capita_nominal"],
            pd.Series([1000.0, 1100.0, 1200.0, 1300.0], name="gdp_per_capita_nominal"),
        )

    def test_deflate_column_applies_factor(self):
        """Deflated values should equal nominal * factor."""
        from database.deflate_ipca import deflate_column

        df = pd.DataFrame({
            "year": [2020, 2023],
            "gdp_per_capita": [1000.0, 1300.0],
        })
        factors = pd.Series({2020: 1.5, 2023: 1.0})

        result = deflate_column(df, "gdp_per_capita", factors)

        assert result["gdp_per_capita"].iloc[0] == pytest.approx(1500.0)
        assert result["gdp_per_capita"].iloc[1] == pytest.approx(1300.0)

    def test_deflate_column_nan_stays_nan(self):
        """NaN values must remain NaN after deflation (not become 0 or error)."""
        from database.deflate_ipca import deflate_column

        df = pd.DataFrame({
            "year": [2020, 2021, 2022],
            "gdp_per_capita": [1000.0, np.nan, 1200.0],
        })
        factors = pd.Series({2020: 1.5, 2021: 1.3, 2022: 1.1})

        result = deflate_column(df, "gdp_per_capita", factors)

        assert np.isnan(result["gdp_per_capita"].iloc[1])
        assert result["gdp_per_capita"].iloc[0] == pytest.approx(1500.0)
        assert result["gdp_per_capita"].iloc[2] == pytest.approx(1320.0)
