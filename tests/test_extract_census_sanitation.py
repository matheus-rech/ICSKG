"""
Tests for Census 2022 sanitation extraction module.

Covers SIDRA table parsing for sanitation (6805) and water supply (6803),
municipality code normalization, cross-sectional year handling, and output
schema using mocked sidrapy responses.
"""

import json
import pandas as pd
import pytest
from pathlib import Path
from unittest.mock import patch

FIXTURE_DIR = Path(__file__).parent / "fixtures"
FIXTURE_JSON = FIXTURE_DIR / "sidra_6805_sample.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_sidra_fixture() -> pd.DataFrame:
    """Load SIDRA fixture JSON as a DataFrame (simulating sidrapy.get_table output)."""
    with open(FIXTURE_JSON, encoding="utf-8") as f:
        data = json.load(f)
    return pd.DataFrame(data)


def _make_water_fixture() -> pd.DataFrame:
    """Create water supply fixture by modifying sanitation fixture values."""
    df = _load_sidra_fixture()
    # Shift values slightly to simulate different water supply percentages
    for i in range(1, len(df)):
        try:
            val = float(df.at[i, "V"])
            df.at[i, "V"] = str(val + 5.0)
        except (ValueError, TypeError):
            pass  # Keep "..." as-is
    return df


def _mock_get_table(**kwargs):
    """Mock sidrapy.get_table() returning sanitation or water fixture."""
    table_code = kwargs.get("table_code", "")
    if table_code == "6805":
        return _load_sidra_fixture()
    elif table_code == "6803":
        return _make_water_fixture()
    else:
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Test 1: fetch_sanitation returns correct columns
# ---------------------------------------------------------------------------

def test_fetch_sanitation_columns():
    """fetch_sanitation() with mocked sidrapy returns [cod_ibge, pct_sanitation_adequate]."""
    from scripts.extract_census_sanitation import fetch_sanitation

    with patch("scripts.extract_census_sanitation.sidrapy") as mock_sidra:
        mock_sidra.get_table.return_value = _load_sidra_fixture()
        result = fetch_sanitation()

    assert "cod_ibge" in result.columns
    assert "pct_sanitation_adequate" in result.columns
    assert len(result.columns) == 2


# ---------------------------------------------------------------------------
# Test 2: fetch_water_supply returns correct columns
# ---------------------------------------------------------------------------

def test_fetch_water_supply_columns():
    """fetch_water_supply() with mocked sidrapy returns [cod_ibge, pct_water_adequate]."""
    from scripts.extract_census_sanitation import fetch_water_supply

    with patch("scripts.extract_census_sanitation.sidrapy") as mock_sidra:
        mock_sidra.get_table.return_value = _make_water_fixture()
        result = fetch_water_supply()

    assert "cod_ibge" in result.columns
    assert "pct_water_adequate" in result.columns
    assert len(result.columns) == 2


# ---------------------------------------------------------------------------
# Test 3: extract_sanitation merges both into correct output
# ---------------------------------------------------------------------------

def test_extract_sanitation_merges_both(tmp_path):
    """extract_sanitation() merges into [cod_ibge, year, pct_sanitation_adequate, pct_water_adequate]."""
    from scripts.extract_census_sanitation import extract_sanitation

    with patch("scripts.extract_census_sanitation.sidrapy") as mock_sidra:
        mock_sidra.get_table.side_effect = lambda **kw: _mock_get_table(**kw)
        result_path = extract_sanitation(output_dir=tmp_path)

    df = pd.read_parquet(result_path)
    expected_cols = {"cod_ibge", "year", "pct_sanitation_adequate", "pct_water_adequate"}
    assert set(df.columns) == expected_cols, (
        "Column mismatch: extra=%s missing=%s"
        % (set(df.columns) - expected_cols, expected_cols - set(df.columns))
    )


# ---------------------------------------------------------------------------
# Test 4: year column is always 2022 (cross-sectional)
# ---------------------------------------------------------------------------

def test_year_always_2022(tmp_path):
    """Year column is always 2022 (cross-sectional)."""
    from scripts.extract_census_sanitation import extract_sanitation

    with patch("scripts.extract_census_sanitation.sidrapy") as mock_sidra:
        mock_sidra.get_table.side_effect = lambda **kw: _mock_get_table(**kw)
        result_path = extract_sanitation(output_dir=tmp_path)

    df = pd.read_parquet(result_path)
    assert (df["year"] == 2022).all(), "All rows must have year=2022"


# ---------------------------------------------------------------------------
# Test 5: First row (metadata header) skipped
# ---------------------------------------------------------------------------

def test_metadata_header_skipped():
    """First row (metadata header) from sidrapy is skipped."""
    from scripts.extract_census_sanitation import fetch_sanitation

    with patch("scripts.extract_census_sanitation.sidrapy") as mock_sidra:
        mock_sidra.get_table.return_value = _load_sidra_fixture()
        result = fetch_sanitation()

    # The fixture has 7 rows: 1 header + 5 data + 1 missing data
    # After skipping header and coercing "..." to NaN, we should have <= 6 rows
    assert len(result) <= 6
    # No row should have the metadata header value
    assert "Municipio (Codigo)" not in result["cod_ibge"].values
    assert "Valor" not in result.get("pct_sanitation_adequate", pd.Series()).astype(str).values


# ---------------------------------------------------------------------------
# Test 6: normalize_cod_ibge applied to D1C values
# ---------------------------------------------------------------------------

def test_cod_ibge_normalized():
    """normalize_cod_ibge() applied to D1C values -- all 7-digit strings."""
    from scripts.extract_census_sanitation import fetch_sanitation

    with patch("scripts.extract_census_sanitation.sidrapy") as mock_sidra:
        mock_sidra.get_table.return_value = _load_sidra_fixture()
        result = fetch_sanitation()

    for code in result["cod_ibge"].dropna():
        assert len(code) == 7, "Expected 7-digit code, got '%s'" % code
        assert code.isdigit(), "Code should be all digits, got '%s'" % code

    # 3550308 should remain 3550308 (already 7-digit)
    assert "3550308" in result["cod_ibge"].values


# ---------------------------------------------------------------------------
# Test 7: Percentage values are numeric floats between 0 and 100
# ---------------------------------------------------------------------------

def test_percentage_values_numeric():
    """Percentage values are numeric floats between 0 and 100."""
    from scripts.extract_census_sanitation import fetch_sanitation

    with patch("scripts.extract_census_sanitation.sidrapy") as mock_sidra:
        mock_sidra.get_table.return_value = _load_sidra_fixture()
        result = fetch_sanitation()

    valid_pcts = result["pct_sanitation_adequate"].dropna()
    assert len(valid_pcts) > 0, "Should have at least some valid percentages"
    assert pd.api.types.is_float_dtype(valid_pcts), (
        "Percentages should be float, got %s" % valid_pcts.dtype
    )
    assert (valid_pcts >= 0).all(), "Percentages should be >= 0"
    assert (valid_pcts <= 100).all(), "Percentages should be <= 100"
