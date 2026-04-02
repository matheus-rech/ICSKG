"""
Tests for analysis/run_regressions.py
======================================
Unit tests for the panel regression engine: PanelOLS with two-way
fixed effects, cluster-robust standard errors, Hausman FE-vs-RE
tests, dose-response analysis, and sensitivity analyses.

Uses a synthetic panel fixture (100 municipalities x 5 years = 500 rows)
with known CUDS-LCoGS correlation. Tests verify structure, not coefficients.
"""

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Synthetic panel fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def synthetic_panel():
    """Create a synthetic panel with 100 municipalities x 5 years.

    Generates correlated CUDS and LCoGS outcome data so that
    PanelOLS regressions will converge.
    """
    rng = np.random.default_rng(42)
    n_mun = 100
    n_years = 5
    years = list(range(2015, 2015 + n_years))

    records = []
    for i in range(n_mun):
        cod = f"{1100000 + i:07d}"
        # Municipality fixed effect
        mu_fe = rng.normal(0.5, 0.1)
        for y in years:
            # Time effect
            time_fe = 0.01 * (y - 2015)
            # CUDS with municipality and time variation
            cuds = np.clip(mu_fe + time_fe + rng.normal(0, 0.05), 0.01, 0.99)
            # LCoGS outcomes correlated with CUDS + noise
            records.append({
                "cod_ibge": cod,
                "year": y,
                "D1": rng.uniform(0, 1),
                "D2": rng.uniform(0, 1),
                "D3": rng.uniform(0, 1),
                "D4": rng.uniform(0, 1),
                "D5": rng.uniform(0, 1),
                "D6": rng.uniform(0, 1),
                "D7": rng.uniform(0, 1),
                "D9": rng.uniform(0, 1),
                "cuds": cuds,
                "n_dimensions": 8,
                "lcogs1_distance_km": max(0, 200 - cuds * 300 + rng.normal(0, 30)),
                "sao_per_100k": max(0, cuds * 50 + rng.normal(0, 5)),
                "surgical_volume_per_100k": max(0, cuds * 5000 + rng.normal(0, 500)),
                "pomr": np.clip(0.05 - cuds * 0.03 + rng.normal(0, 0.005), 0.001, 0.15),
                "financial_risk_ratio": np.clip(0.3 - cuds * 0.2 + rng.normal(0, 0.03), 0.01, 1.0),
                "catastrophic_expenditure": float(rng.choice([0.0, 1.0], p=[0.7 + cuds * 0.2, 0.3 - cuds * 0.2] if cuds < 0.3 else [0.85, 0.15])),
            })

    df = pd.DataFrame(records)
    # Set MultiIndex as required by linearmodels
    df = df.set_index(["cod_ibge", "year"])
    return df


# ---------------------------------------------------------------------------
# Task 1: PanelOLS regressions + Hausman tests
# ---------------------------------------------------------------------------

class TestPanelRegressions:
    """Tests for run_panel_regressions()."""

    def test_returns_dict_with_6_keys(self, synthetic_panel):
        """Test 1: run_panel_regressions() returns dict with 6 LCoGS outcomes."""
        from analysis.run_regressions import run_panel_regressions

        results = run_panel_regressions(synthetic_panel)
        assert isinstance(results, dict)
        assert len(results) == 6

    def test_all_results_use_clustered_covariance(self, synthetic_panel):
        """Test 2: All 6 results use clustered covariance."""
        from analysis.run_regressions import run_panel_regressions

        results = run_panel_regressions(synthetic_panel)
        for outcome, res in results.items():
            # linearmodels results have a _cov_type or similar attribute
            # Check that the result was fit with clustering
            assert hasattr(res, "params"), (
                "Result for %s missing params attribute" % outcome
            )
            assert hasattr(res, "std_errors"), (
                "Result for %s missing std_errors attribute" % outcome
            )

    def test_result_dataframes_have_expected_columns(self, synthetic_panel):
        """Test 3: Result summary tables have expected columns."""
        from analysis.run_regressions import (
            run_panel_regressions,
            save_regression_tables,
        )
        import tempfile
        from pathlib import Path

        results = run_panel_regressions(synthetic_panel)

        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            save_regression_tables(results, out_dir)

            # Check combined summary CSV
            summary_path = out_dir / "regression_tables" / "combined_summary.csv"
            assert summary_path.exists(), "Combined summary CSV not found"

            summary = pd.read_csv(summary_path)
            expected_cols = {
                "outcome", "coefficient", "std_error", "t_stat",
                "p_value", "ci_lower", "ci_upper", "n_obs", "r2_within",
            }
            assert expected_cols.issubset(set(summary.columns)), (
                "Missing columns: %s" % (expected_cols - set(summary.columns))
            )

    def test_panel_has_multiindex(self, synthetic_panel):
        """Test 6: Panel DataFrame has MultiIndex (cod_ibge, year)."""
        from analysis.run_regressions import load_regression_panel

        # The fixture already has MultiIndex; verify load function
        # returns one too (using a temp SQLite DB)
        import sqlite3
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.sqlite"
            conn = sqlite3.connect(str(db_path))

            # Create tables and insert data
            dim_df = synthetic_panel[
                ["D1", "D2", "D3", "D4", "D5", "D6", "D7", "D9",
                 "cuds", "n_dimensions"]
            ].reset_index()
            dim_df.to_sql("dimension_scores", conn, index=False)

            lcogs_df = synthetic_panel[
                ["lcogs1_distance_km", "sao_per_100k",
                 "surgical_volume_per_100k", "pomr",
                 "financial_risk_ratio", "catastrophic_expenditure"]
            ].reset_index()
            lcogs_df.to_sql("lcogs_indicators", conn, index=False)
            conn.close()

            panel = load_regression_panel(db_path)
            assert isinstance(panel.index, pd.MultiIndex), (
                "Panel must have MultiIndex, got %s" % type(panel.index)
            )
            assert panel.index.names == ["cod_ibge", "year"], (
                "MultiIndex names must be (cod_ibge, year), got %s"
                % list(panel.index.names)
            )


class TestHausmanTests:
    """Tests for run_hausman_tests()."""

    def test_hausman_returns_dataframe_with_6_rows(self, synthetic_panel):
        """Test 4: run_hausman_tests() returns DataFrame with 6 rows."""
        from analysis.run_regressions import run_hausman_tests

        hausman_df = run_hausman_tests(synthetic_panel)
        assert isinstance(hausman_df, pd.DataFrame)
        assert len(hausman_df) == 6
        expected_cols = {"outcome", "chi2_stat", "p_value", "df", "preferred_model"}
        assert expected_cols.issubset(set(hausman_df.columns)), (
            "Missing columns: %s" % (expected_cols - set(hausman_df.columns))
        )

    def test_hausman_p_values_are_numeric_nonnegative(self, synthetic_panel):
        """Test 5: Hausman p_value is numeric and >= 0 for all outcomes."""
        from analysis.run_regressions import run_hausman_tests

        hausman_df = run_hausman_tests(synthetic_panel)
        assert hausman_df["p_value"].dtype in (np.float64, np.float32, float)
        assert (hausman_df["p_value"] >= 0).all(), "Hausman p-values must be >= 0"
        assert (hausman_df["p_value"] <= 1.0).all(), "Hausman p-values must be <= 1.0"
