"""
Tests for ANS quarterly average beneficiary extraction module.

Covers quarterly averaging logic, municipality code normalization,
coverage rate computation, and output schema using offline fixture data.
All network calls are mocked via monkeypatch.
"""

import pandas as pd
import pytest
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent / "fixtures"
FIXTURE_CSV = FIXTURE_DIR / "ans_quarterly_sample.csv"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_fixture() -> pd.DataFrame:
    """Load the ANS quarterly sample fixture as a DataFrame."""
    return pd.read_csv(FIXTURE_CSV, sep=";", dtype=str)


def _make_quarterly_frames(year: int = 2020) -> list[pd.DataFrame]:
    """Build per-quarter DataFrames from the fixture, simulating parse_csv() output."""
    raw = _load_fixture()
    raw["comp_year"] = pd.to_numeric(raw["comp_year"])
    raw["comp_month"] = pd.to_numeric(raw["comp_month"])
    raw["BENEFICIARIOS"] = pd.to_numeric(
        raw["BENEFICIARIOS"].str.replace(".", "", regex=False),
        errors="coerce",
    )
    frames = []
    for month in [3, 6, 9, 12]:
        subset = raw[(raw["comp_year"] == year) & (raw["comp_month"] == month)].copy()
        if len(subset) > 0:
            frames.append(subset)
    return frames


# ---------------------------------------------------------------------------
# Test 1: Quarterly average computes mean of 4 quarters, not December value
# ---------------------------------------------------------------------------

def test_quarterly_average_is_mean_not_december():
    """compute_quarterly_average() returns mean of 4 quarterly values, not December."""
    from scripts.extract_ans_quarterly import compute_quarterly_average

    frames = _make_quarterly_frames(2020)
    result = compute_quarterly_average(frames, year=2020)

    # Municipality 355030: Q1=100000, Q2=110000, Q3=105000, Q4=115000 -> mean=107500
    row = result[result["cod_ibge"].str.endswith("355030")]
    assert len(row) == 1
    assert abs(row.iloc[0]["beneficiarios_mean"] - 107500.0) < 0.01

    # NOT the December value of 115000
    assert row.iloc[0]["beneficiarios_mean"] != 115000.0


# ---------------------------------------------------------------------------
# Test 2: Municipality with only 3 quarters computes mean from 3
# ---------------------------------------------------------------------------

def test_quarterly_average_partial_quarters():
    """If only 3 quarters available, mean is computed from 3 (not NaN)."""
    from scripts.extract_ans_quarterly import compute_quarterly_average

    frames = _make_quarterly_frames(2020)
    result = compute_quarterly_average(frames, year=2020)

    # Municipality 150140: Q1=8000, Q3=9000, Q4=9500 -> mean = (8000+9000+9500)/3 = 8833.33
    row = result[result["cod_ibge"].str.endswith("150140")]
    assert len(row) == 1
    assert not pd.isna(row.iloc[0]["beneficiarios_mean"])
    assert abs(row.iloc[0]["beneficiarios_mean"] - 8833.33) < 1.0


# ---------------------------------------------------------------------------
# Test 3: 6-digit CD_MUNICIPIO zero-padded to 7-digit via normalize_cod_ibge
# ---------------------------------------------------------------------------

def test_cod_ibge_normalized_to_7_digits():
    """6-digit CD_MUNICIPIO values are zero-padded to 7-digit strings."""
    from scripts.extract_ans_quarterly import compute_quarterly_average

    frames = _make_quarterly_frames(2020)
    result = compute_quarterly_average(frames, year=2020)

    # All cod_ibge values should be 7-digit strings
    for code in result["cod_ibge"]:
        assert len(code) == 7, "Expected 7-digit code, got '%s'" % code
        assert code.isdigit(), "Code should be all digits, got '%s'" % code

    # 355030 (6-digit) should become 0355030 (7-digit)
    assert "0355030" in result["cod_ibge"].values
    # 120020 (6-digit) should become 0120020 (7-digit)
    assert "0120020" in result["cod_ibge"].values


# ---------------------------------------------------------------------------
# Test 4: Coverage rate and SUS dependence computation
# ---------------------------------------------------------------------------

def test_coverage_rate_computation():
    """compute_coverage_rate() divides by population, computes sus_dependence = 1 - rate."""
    from scripts.extract_ans_quarterly import compute_quarterly_average, compute_coverage_rate

    frames = _make_quarterly_frames(2020)
    df = compute_quarterly_average(frames, year=2020)

    # Create a mock population DataFrame
    pop_df = pd.DataFrame({
        "cod_ibge": ["0355030", "0120020", "0330455", "0150140"],
        "year": [2020, 2020, 2020, 2020],
        "populacao": [1000000.0, 50000.0, 2000000.0, 100000.0],
    })

    result = compute_coverage_rate(df, population_df=pop_df)

    # Check coverage_rate = beneficiarios_mean / populacao
    row_sp = result[result["cod_ibge"] == "0355030"]
    expected_coverage = 107500.0 / 1000000.0  # ~0.1075
    assert abs(row_sp.iloc[0]["coverage_rate"] - expected_coverage) < 0.001

    # Check sus_dependence = 1 - coverage_rate
    expected_sus = 1.0 - expected_coverage
    assert abs(row_sp.iloc[0]["sus_dependence"] - expected_sus) < 0.001


# ---------------------------------------------------------------------------
# Test 5: Output has correct columns
# ---------------------------------------------------------------------------

def test_output_columns():
    """Output has columns [cod_ibge, year, beneficiarios_mean, coverage_rate, sus_dependence]."""
    from scripts.extract_ans_quarterly import compute_quarterly_average, compute_coverage_rate

    frames = _make_quarterly_frames(2020)
    df = compute_quarterly_average(frames, year=2020)

    # Without population: coverage_rate and sus_dependence are NaN
    result = compute_coverage_rate(df, population_df=None)
    expected_cols = {"cod_ibge", "year", "beneficiarios_mean", "coverage_rate", "sus_dependence"}
    assert set(result.columns) == expected_cols, (
        "Column mismatch: extra=%s missing=%s"
        % (set(result.columns) - expected_cols, expected_cols - set(result.columns))
    )


# ---------------------------------------------------------------------------
# Test 6: Multiple years produce one row per municipality per year
# ---------------------------------------------------------------------------

def test_multiple_years_one_row_per_muni_year():
    """Multiple years produce one row per municipality per year."""
    from scripts.extract_ans_quarterly import compute_quarterly_average

    # Build frames for year 2020 (from fixture)
    frames_2020 = _make_quarterly_frames(2020)
    result_2020 = compute_quarterly_average(frames_2020, year=2020)

    # Simulate a second year by modifying the data
    frames_2021 = []
    for f in frames_2020:
        f2 = f.copy()
        f2["comp_year"] = 2021
        f2["BENEFICIARIOS"] = f2["BENEFICIARIOS"] * 1.05  # 5% growth
        frames_2021.append(f2)
    result_2021 = compute_quarterly_average(frames_2021, year=2021)

    # Concatenate both years
    combined = pd.concat([result_2020, result_2021], ignore_index=True)

    # Each municipality should appear once per year
    for code in result_2020["cod_ibge"].unique():
        rows = combined[combined["cod_ibge"] == code]
        assert len(rows) == 2, "Expected 2 rows (2020, 2021) for %s, got %d" % (code, len(rows))
        assert set(rows["year"]) == {2020, 2021}

    # No duplicates within a year
    assert not combined.duplicated(subset=["cod_ibge", "year"]).any()
