"""
Tests for IBGE SIDRA population and GDP extraction module.

Covers table routing (6579 vs 4709), GDP per-capita computation,
metadata header skipping, NaN/missing value coercion, normalize_cod_ibge
application, and estimated GDP flagging using offline fixture data.
"""

import json
import pandas as pd
import pytest
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Fixture loading helpers
# ---------------------------------------------------------------------------

def _load_fixture(name: str) -> pd.DataFrame:
    """Load a SIDRA JSON fixture and return it as a DataFrame (as sidrapy would)."""
    path = FIXTURE_DIR / name
    with path.open("r", encoding="utf-8") as f:
        records = json.load(f)
    return pd.DataFrame(records)


@pytest.fixture()
def fixture_6579():
    """Table 6579 population estimates (2015-2021)."""
    return _load_fixture("sidra_6579_sample.json")


@pytest.fixture()
def fixture_5938():
    """Table 5938 GDP (variable 37, R$ 1,000)."""
    return _load_fixture("sidra_5938_sample.json")


@pytest.fixture()
def fixture_4709():
    """Table 4709 Census 2022 population."""
    return _load_fixture("sidra_4709_sample.json")


# ---------------------------------------------------------------------------
# Test 1: Population extraction (table 6579, year <= 2021)
# ---------------------------------------------------------------------------

def test_fetch_population_year_2021_columns(monkeypatch, fixture_6579):
    """fetch_population_year(2021) returns DataFrame with [cod_ibge, year, populacao]."""
    from scripts.extract_ibge_sidra import fetch_population_year

    import sidrapy
    monkeypatch.setattr(
        sidrapy, "get_table", lambda **kwargs: fixture_6579.copy()
    )

    df = fetch_population_year(2021)
    assert list(df.columns) == ["cod_ibge", "year", "populacao"]
    assert len(df) == 5  # 6 rows minus 1 header row


def test_fetch_population_year_2021_cod_ibge_7digit(monkeypatch, fixture_6579):
    """All cod_ibge values are 7-digit zero-padded strings."""
    from scripts.extract_ibge_sidra import fetch_population_year

    import sidrapy
    monkeypatch.setattr(
        sidrapy, "get_table", lambda **kwargs: fixture_6579.copy()
    )

    df = fetch_population_year(2021)
    for code in df["cod_ibge"]:
        assert isinstance(code, str), "cod_ibge should be string, got %s" % type(code)
        assert len(code) == 7, "cod_ibge should be 7 chars, got '%s' (%d)" % (code, len(code))


# ---------------------------------------------------------------------------
# Test 2: Population table switching (year >= 2022 uses 4709)
# ---------------------------------------------------------------------------

def test_fetch_population_year_2022_uses_table_4709(monkeypatch, fixture_4709):
    """fetch_population_year(2022) uses table 4709 with variable 93."""
    from scripts.extract_ibge_sidra import fetch_population_year

    import sidrapy
    call_args = {}

    def mock_get_table(**kwargs):
        call_args.update(kwargs)
        return fixture_4709.copy()

    monkeypatch.setattr(sidrapy, "get_table", mock_get_table)

    df = fetch_population_year(2022)
    assert call_args["table_code"] == "4709", (
        "Expected table 4709 for year 2022, got %s" % call_args.get("table_code")
    )
    assert call_args["variable"] == "93", (
        "Expected variable 93 for table 4709, got %s" % call_args.get("variable")
    )
    assert len(df) == 5
    assert list(df.columns) == ["cod_ibge", "year", "populacao"]


def test_fetch_population_year_2021_uses_table_6579(monkeypatch, fixture_6579):
    """fetch_population_year(2021) uses table 6579 with variable 9324."""
    from scripts.extract_ibge_sidra import fetch_population_year

    import sidrapy
    call_args = {}

    def mock_get_table(**kwargs):
        call_args.update(kwargs)
        return fixture_6579.copy()

    monkeypatch.setattr(sidrapy, "get_table", mock_get_table)

    fetch_population_year(2021)
    assert call_args["table_code"] == "6579"
    assert call_args["variable"] == "9324"


# ---------------------------------------------------------------------------
# Test 3: GDP extraction (table 5938, variable 37)
# ---------------------------------------------------------------------------

def test_fetch_gdp_year_columns(monkeypatch, fixture_5938):
    """fetch_gdp_year(2021) returns DataFrame with [cod_ibge, year, gdp_abs, gdp_estimated]."""
    from scripts.extract_ibge_sidra import fetch_gdp_year

    import sidrapy
    monkeypatch.setattr(
        sidrapy, "get_table", lambda **kwargs: fixture_5938.copy()
    )

    df = fetch_gdp_year(2021)
    assert list(df.columns) == ["cod_ibge", "year", "gdp_abs", "gdp_estimated"]
    # 6 rows - 1 header = 5 data rows
    assert len(df) == 5


def test_fetch_gdp_year_numeric(monkeypatch, fixture_5938):
    """gdp_abs column is numeric (float64) after coercion."""
    from scripts.extract_ibge_sidra import fetch_gdp_year

    import sidrapy
    monkeypatch.setattr(
        sidrapy, "get_table", lambda **kwargs: fixture_5938.copy()
    )

    df = fetch_gdp_year(2021)
    assert pd.api.types.is_float_dtype(df["gdp_abs"]), (
        "gdp_abs should be float, got %s" % df["gdp_abs"].dtype
    )


# ---------------------------------------------------------------------------
# Test 4: GDP per capita computation
# ---------------------------------------------------------------------------

def test_compute_gdp_per_capita(monkeypatch, fixture_5938, fixture_6579):
    """compute_gdp_per_capita merges GDP and population, producing gdp_per_capita = gdp_abs * 1000 / populacao."""
    from scripts.extract_ibge_sidra import fetch_gdp_year, fetch_population_year, compute_gdp_per_capita

    import sidrapy
    # Mock: first call returns GDP, second returns population
    call_count = [0]

    def mock_get_table(**kwargs):
        call_count[0] += 1
        if kwargs.get("table_code") == "5938":
            return fixture_5938.copy()
        return fixture_6579.copy()

    monkeypatch.setattr(sidrapy, "get_table", mock_get_table)

    gdp_df = fetch_gdp_year(2021)
    pop_df = fetch_population_year(2021)
    result = compute_gdp_per_capita(gdp_df, pop_df)

    assert "gdp_per_capita" in result.columns
    # Sao Paulo: gdp_abs=763782590 (R$ 1,000), pop=12325232
    # gdp_per_capita = 763782590 * 1000 / 12325232 = ~61,970.42
    sp_row = result[result["cod_ibge"] == "3550308"]
    assert len(sp_row) == 1
    expected_per_capita = 763782590.0 * 1000 / 12325232.0
    assert abs(sp_row.iloc[0]["gdp_per_capita"] - expected_per_capita) < 0.01


# ---------------------------------------------------------------------------
# Test 5: Metadata header row is skipped
# ---------------------------------------------------------------------------

def test_first_row_skipped(monkeypatch, fixture_6579):
    """First row of sidrapy response (metadata header) is NOT in the output."""
    from scripts.extract_ibge_sidra import fetch_population_year

    import sidrapy
    monkeypatch.setattr(
        sidrapy, "get_table", lambda **kwargs: fixture_6579.copy()
    )

    df = fetch_population_year(2021)
    # The header row has D1C="Municipio (Codigo)" -- should not appear
    assert "Municipio (Codigo)" not in df["cod_ibge"].values
    # Should have 5 data rows (not 6 including header)
    assert len(df) == 5


# ---------------------------------------------------------------------------
# Test 6: NaN / missing values coerced (not crash)
# ---------------------------------------------------------------------------

def test_nan_values_coerced(monkeypatch, fixture_5938):
    """'...' and '-' in V column are coerced to NaN, not raise errors."""
    from scripts.extract_ibge_sidra import fetch_gdp_year

    import sidrapy
    monkeypatch.setattr(
        sidrapy, "get_table", lambda **kwargs: fixture_5938.copy()
    )

    df = fetch_gdp_year(2021)
    # Belo Horizonte has V="..." and Curitiba has V="-"
    bh_row = df[df["cod_ibge"] == "3106200"]
    curitiba_row = df[df["cod_ibge"] == "4106902"]
    assert pd.isna(bh_row.iloc[0]["gdp_abs"]), "V='...' should be NaN"
    assert pd.isna(curitiba_row.iloc[0]["gdp_abs"]), "V='-' should be NaN"
    # Other rows should have valid numeric values
    sp_row = df[df["cod_ibge"] == "3550308"]
    assert not pd.isna(sp_row.iloc[0]["gdp_abs"])


# ---------------------------------------------------------------------------
# Test 7: 2022-2023 GDP estimated flag
# ---------------------------------------------------------------------------

def test_gdp_estimated_flag_2021(monkeypatch, fixture_5938):
    """2021 GDP rows have gdp_estimated=False."""
    from scripts.extract_ibge_sidra import fetch_gdp_year

    import sidrapy
    monkeypatch.setattr(
        sidrapy, "get_table", lambda **kwargs: fixture_5938.copy()
    )

    df = fetch_gdp_year(2021)
    assert (df["gdp_estimated"] == False).all(), (  # noqa: E712
        "2021 GDP should not be flagged as estimated"
    )


def test_gdp_estimated_flag_2022(monkeypatch, fixture_5938):
    """2022 GDP rows have gdp_estimated=True."""
    from scripts.extract_ibge_sidra import fetch_gdp_year

    import sidrapy
    monkeypatch.setattr(
        sidrapy, "get_table", lambda **kwargs: fixture_5938.copy()
    )

    df = fetch_gdp_year(2022)
    assert (df["gdp_estimated"] == True).all(), (  # noqa: E712
        "2022 GDP should be flagged as estimated"
    )


def test_gdp_estimated_flag_2023(monkeypatch, fixture_5938):
    """2023 GDP rows have gdp_estimated=True."""
    from scripts.extract_ibge_sidra import fetch_gdp_year

    import sidrapy
    monkeypatch.setattr(
        sidrapy, "get_table", lambda **kwargs: fixture_5938.copy()
    )

    df = fetch_gdp_year(2023)
    assert (df["gdp_estimated"] == True).all(), (  # noqa: E712
        "2023 GDP should be flagged as estimated"
    )
