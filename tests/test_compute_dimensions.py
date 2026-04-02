"""
Tests for analysis.compute_dimensions — CIMI dimension computation,
within-year min-max normalization, and CUDS geometric mean.
"""

import sqlite3

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def sample_panel() -> pd.DataFrame:
    """3 municipalities x 2 years with realistic panel values.

    Municipality C has NaN for vehicles_per_1000 and
    health_expenditure_per_capita to test missing dimension handling.
    """
    return pd.DataFrame({
        "cod_ibge": [
            "3550308", "3304557", "5300108",  # year 2020
            "3550308", "3304557", "5300108",  # year 2021
        ],
        "year": [2020, 2020, 2020, 2021, 2021, 2021],
        "ifgf_geral": [0.75, 0.50, 0.30, 0.80, 0.55, 0.35],
        "gdp_per_capita": [60000.0, 40000.0, 20000.0, 65000.0, 42000.0, 22000.0],
        "idhm": [0.805, 0.799, 0.824, 0.805, 0.799, 0.824],
        "sus_dependence_rate": [0.40, 0.70, 0.90, 0.38, 0.68, 0.88],
        "pct_sanitation_adequate": [0.90, 0.75, 0.50, 0.91, 0.76, 0.52],
        "vehicles_per_1000": [400.0, 250.0, np.nan, 420.0, 260.0, np.nan],
        "total_beds": [5000.0, 3000.0, 800.0, 5200.0, 3100.0, 850.0],
        "populacao": [12300000.0, 6700000.0, 3000000.0, 12400000.0, 6800000.0, 3050000.0],
        "health_expenditure_per_capita": [800.0, 600.0, np.nan, 850.0, 620.0, np.nan],
    })


@pytest.fixture()
def sample_dims() -> pd.DataFrame:
    """Pre-computed raw dimension DataFrame for normalization tests.

    3 municipalities x 1 year, with controlled values for easy
    assertion of min-max extremes.
    """
    return pd.DataFrame({
        "cod_ibge": ["1100015", "2100055", "3550308"],
        "year": [2020, 2020, 2020],
        "D1": [0.3, 0.6, 0.9],
        "D2": [10000.0, 30000.0, 60000.0],
        "D3": [0.5, 0.7, 0.8],
        "D4": [0.9, 0.5, 0.2],  # will be inverted after normalization
        "D5": [0.4, 0.7, 0.95],
        "D6": [100.0, 300.0, 500.0],
        "D7": [1.0, 3.0, 5.0],
        "D9": [200.0, 500.0, 900.0],
    })


# ---------------------------------------------------------------------------
# Test 1: compute_all_dimensions column mapping
# ---------------------------------------------------------------------------

class TestComputeAllDimensions:
    """Tests for compute_all_dimensions()."""

    def test_maps_panel_columns_to_dimensions(
        self, sample_panel: pd.DataFrame,
    ) -> None:
        """compute_all_dimensions maps panel columns to D1-D7, D9."""
        from analysis.compute_dimensions import compute_all_dimensions

        dims = compute_all_dimensions(sample_panel)

        # Must have cod_ibge, year, and all 8 dimension columns
        assert "cod_ibge" in dims.columns
        assert "year" in dims.columns
        for d in ["D1", "D2", "D3", "D4", "D5", "D6", "D7", "D9"]:
            assert d in dims.columns, "Missing dimension column: %s" % d

        # D8 must NOT be present
        assert "D8" not in dims.columns

        # Row count preserved
        assert len(dims) == len(sample_panel)

        # D1 maps from ifgf_geral
        assert dims.loc[0, "D1"] == pytest.approx(0.75)

        # D2 maps from gdp_per_capita
        assert dims.loc[0, "D2"] == pytest.approx(60000.0)

        # D3 maps from idhm
        assert dims.loc[0, "D3"] == pytest.approx(0.805)

        # D4 maps from sus_dependence_rate (raw, NOT inverted yet)
        assert dims.loc[0, "D4"] == pytest.approx(0.40)

        # D5 maps from pct_sanitation_adequate
        assert dims.loc[0, "D5"] == pytest.approx(0.90)

    def test_d7_computed_as_beds_per_10k(
        self, sample_panel: pd.DataFrame,
    ) -> None:
        """D7 = total_beds / populacao * 10_000."""
        from analysis.compute_dimensions import compute_all_dimensions

        dims = compute_all_dimensions(sample_panel)

        expected_d7 = 5000.0 / 12300000.0 * 10_000
        assert dims.loc[0, "D7"] == pytest.approx(expected_d7, rel=1e-6)

    def test_preserves_nan_in_source_columns(
        self, sample_panel: pd.DataFrame,
    ) -> None:
        """NaN in source columns preserved in dimension output."""
        from analysis.compute_dimensions import compute_all_dimensions

        dims = compute_all_dimensions(sample_panel)

        # Municipality 5300108 (index 2, 5) has NaN for vehicles_per_1000 -> D6
        assert pd.isna(dims.loc[2, "D6"])
        assert pd.isna(dims.loc[5, "D6"])

        # And NaN for health_expenditure_per_capita -> D9
        assert pd.isna(dims.loc[2, "D9"])
        assert pd.isna(dims.loc[5, "D9"])


# ---------------------------------------------------------------------------
# Test 2-4: normalize_within_year
# ---------------------------------------------------------------------------

class TestNormalizeWithinYear:
    """Tests for normalize_within_year()."""

    def test_minmax_invariant(self, sample_dims: pd.DataFrame) -> None:
        """Exactly one 0.0 and one 1.0 per year per dimension."""
        from analysis.compute_dimensions import normalize_within_year

        norm = normalize_within_year(sample_dims)

        dim_cols = ["D1", "D2", "D3", "D5", "D6", "D7", "D9"]
        for col in dim_cols:
            year_data = norm[norm["year"] == 2020][col]
            assert year_data.min() == 0.0, (
                "%s min should be 0.0, got %f" % (col, year_data.min())
            )
            assert year_data.max() == 1.0, (
                "%s max should be 1.0, got %f" % (col, year_data.max())
            )

    def test_preserves_nan(self, sample_panel: pd.DataFrame) -> None:
        """NaN values not filled during normalization."""
        from analysis.compute_dimensions import (
            compute_all_dimensions, normalize_within_year,
        )

        dims = compute_all_dimensions(sample_panel)
        norm = normalize_within_year(dims)

        # D6 NaN for 5300108 should remain NaN
        mask = norm["cod_ibge"] == "5300108"
        assert norm.loc[mask, "D6"].isna().all()

    def test_constant_column_assigns_half(self) -> None:
        """All same values in a dimension -> 0.5 for all."""
        from analysis.compute_dimensions import normalize_within_year

        df = pd.DataFrame({
            "cod_ibge": ["A", "B", "C"],
            "year": [2020, 2020, 2020],
            "D1": [5.0, 5.0, 5.0],
            "D2": [1.0, 2.0, 3.0],
            "D3": [1.0, 1.0, 1.0],
            "D4": [0.5, 0.5, 0.5],
            "D5": [1.0, 2.0, 3.0],
            "D6": [1.0, 2.0, 3.0],
            "D7": [1.0, 2.0, 3.0],
            "D9": [1.0, 2.0, 3.0],
        })
        norm = normalize_within_year(df)

        # D1 and D3 are constant -> all 0.5
        assert (norm["D1"] == 0.5).all()
        assert (norm["D3"] == 0.5).all()

    def test_d4_inverted_after_normalization(
        self, sample_dims: pd.DataFrame,
    ) -> None:
        """D4: higher SUS dependence -> LOWER social cohesion score."""
        from analysis.compute_dimensions import normalize_within_year

        norm = normalize_within_year(sample_dims)

        # In sample_dims: D4 raw = [0.9, 0.5, 0.2]
        # After min-max: [1.0, 0.4286, 0.0]
        # After inversion (1 - x): [0.0, 0.5714, 1.0]
        # So municipality with highest SUS dependence (0.9) gets D4 = 0.0
        # and municipality with lowest SUS dependence (0.2) gets D4 = 1.0
        d4_vals = norm[norm["year"] == 2020]["D4"].values
        # The municipality with raw 0.9 (highest SUS dependence) should have LOWEST score
        assert d4_vals[0] == pytest.approx(0.0, abs=1e-10)
        # The municipality with raw 0.2 (lowest SUS dependence) should have HIGHEST score
        assert d4_vals[2] == pytest.approx(1.0, abs=1e-10)


# ---------------------------------------------------------------------------
# Test 5-7: compute_cuds
# ---------------------------------------------------------------------------

class TestComputeCuds:
    """Tests for compute_cuds()."""

    def test_geometric_mean_with_epsilon(self) -> None:
        """CUDS is geometric mean with epsilon=0.01 floor; no exact 0.0."""
        from analysis.compute_dimensions import compute_cuds

        df = pd.DataFrame({
            "cod_ibge": ["A", "B"],
            "year": [2020, 2020],
            "D1": [0.5, 0.0],
            "D2": [0.6, 0.0],
            "D3": [0.7, 0.0],
            "D4": [0.8, 0.0],
            "D5": [0.4, 0.0],
            "D6": [0.3, 0.0],
            "D7": [0.9, 0.0],
            "D9": [0.5, 0.0],
        })
        cuds = compute_cuds(df)

        # No CUDS value should be exactly 0.0 (epsilon floor)
        assert cuds.iloc[1] != 0.0
        assert cuds.iloc[1] > 0.0  # epsilon prevents zero

        # First municipality should have positive CUDS
        assert cuds.iloc[0] > 0.0

    def test_excludes_nan_from_geometric_mean(self) -> None:
        """Municipality with 6 of 8 dims uses geometric mean of those 6."""
        from analysis.compute_dimensions import compute_cuds

        df = pd.DataFrame({
            "cod_ibge": ["A"],
            "year": [2020],
            "D1": [0.5],
            "D2": [0.6],
            "D3": [0.7],
            "D4": [0.8],
            "D5": [0.4],
            "D6": [np.nan],  # missing
            "D7": [0.9],
            "D9": [np.nan],  # missing
        })
        cuds = compute_cuds(df)

        # Should use 6 dimensions, not 8
        # Manually: geometric_mean of (0.5+0.01, 0.6+0.01, 0.7+0.01,
        #  0.8+0.01, 0.4+0.01, 0.9+0.01) - 0.01
        scores = np.array([0.5, 0.6, 0.7, 0.8, 0.4, 0.9]) + 0.01
        expected = np.exp(np.log(scores).mean()) - 0.01
        assert cuds.iloc[0] == pytest.approx(expected, rel=1e-6)

    def test_all_nan_returns_nan(self) -> None:
        """Municipality with zero available dims gets NaN CUDS."""
        from analysis.compute_dimensions import compute_cuds

        df = pd.DataFrame({
            "cod_ibge": ["A"],
            "year": [2020],
            "D1": [np.nan],
            "D2": [np.nan],
            "D3": [np.nan],
            "D4": [np.nan],
            "D5": [np.nan],
            "D6": [np.nan],
            "D7": [np.nan],
            "D9": [np.nan],
        })
        cuds = compute_cuds(df)
        assert pd.isna(cuds.iloc[0])


# ---------------------------------------------------------------------------
# Test 9: dimension_scores DDL in build_database_v3
# ---------------------------------------------------------------------------

class TestDimensionScoresDDL:
    """Tests for dimension_scores table DDL in build_database_v3."""

    def test_dimension_scores_table_created(self) -> None:
        """dimension_scores DDL exists and creates table with correct schema."""
        from database.build_database_v3 import create_schema

        conn = sqlite3.connect(":memory:")
        create_schema(conn)

        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "dimension_scores" in tables

        # Check columns
        cols = {
            row[1]
            for row in conn.execute(
                "PRAGMA table_info(dimension_scores)"
            ).fetchall()
        }
        expected_cols = {
            "cod_ibge", "year",
            "D1", "D2", "D3", "D4", "D5", "D6", "D7", "D9",
            "cuds", "n_dimensions",
        }
        assert expected_cols.issubset(cols), (
            "Missing columns: %s" % (expected_cols - cols)
        )

        conn.close()


# ---------------------------------------------------------------------------
# Test 10: persist_dimension_scores
# ---------------------------------------------------------------------------

class TestPersistDimensionScores:
    """Tests for persist_dimension_scores()."""

    def test_writes_to_sqlite_correct_count(self) -> None:
        """persist_dimension_scores writes rows and returns matching count."""
        from analysis.compute_dimensions import persist_dimension_scores

        dims = pd.DataFrame({
            "cod_ibge": ["3550308", "3304557", "5300108"],
            "year": [2020, 2020, 2020],
            "D1": [0.8, 0.5, 0.2],
            "D2": [0.9, 0.4, 0.1],
            "D3": [0.7, 0.6, 0.5],
            "D4": [0.3, 0.6, 0.9],
            "D5": [0.8, 0.5, 0.3],
            "D6": [0.7, 0.4, 0.1],
            "D7": [0.9, 0.5, 0.2],
            "D9": [0.6, 0.3, 0.1],
            "cuds": [0.65, 0.42, 0.20],
            "n_dimensions": [8, 8, 8],
        })

        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.sqlite"
            n = persist_dimension_scores(dims, db_path)
            assert n == 3

            # Verify via SQL
            conn = sqlite3.connect(str(db_path))
            count = conn.execute(
                "SELECT COUNT(*) FROM dimension_scores"
            ).fetchone()[0]
            assert count == 3
            conn.close()
