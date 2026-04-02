"""
Tests for database/impute_ifgf.py — IFGF multiple imputation and missingness report.
"""

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_synthetic_panel(n_munic: int = 100, years: list[int] | None = None,
                          pct_missing: float = 0.20, seed: int = 42) -> pd.DataFrame:
    """Create a synthetic panel with controlled IFGF missingness."""
    if years is None:
        years = [2020, 2021]
    rng = np.random.default_rng(seed)

    rows = []
    for year in years:
        for i in range(n_munic):
            row = {
                "cod_ibge": f"{1100015 + i:07d}",
                "year": year,
                "ifgf_geral": rng.uniform(0.2, 0.9),
                "ifgf_ra": rng.uniform(0.1, 0.8),
                "ifgf_gp": rng.uniform(0.1, 0.8),
                "ifgf_id": rng.uniform(0.1, 0.8),
                "ifgf_el": rng.uniform(0.1, 0.8),
                "ifgf_sa": rng.uniform(0.1, 0.8),
                "gdp_per_capita": rng.uniform(10000, 80000),
                "populacao": rng.integers(5000, 500000),
                "uf": rng.choice(["SP", "RJ", "MG", "BA", "RS"]),
            }
            rows.append(row)

    df = pd.DataFrame(rows)

    # Introduce MNAR missing in IFGF columns for pct_missing of rows
    n_total = len(df)
    n_missing = int(n_total * pct_missing)
    missing_idx = rng.choice(df.index, size=n_missing, replace=False)
    ifgf_cols = ["ifgf_geral", "ifgf_ra", "ifgf_gp", "ifgf_id", "ifgf_el", "ifgf_sa"]
    for col in ifgf_cols:
        df.loc[missing_idx, col] = np.nan

    return df


# ---------------------------------------------------------------------------
# Tests — impute_ifgf_mice
# ---------------------------------------------------------------------------

class TestImputeIfgfMice:
    """Tests for the impute_ifgf_mice() function."""

    def test_impute_fills_nan(self):
        """Synthetic panel with 20% NaN in IFGF should have zero NaN after imputation."""
        from database.impute_ifgf import impute_ifgf_mice

        panel = _make_synthetic_panel(n_munic=100, pct_missing=0.20)
        ifgf_cols = ["ifgf_geral", "ifgf_ra", "ifgf_gp", "ifgf_id", "ifgf_el", "ifgf_sa"]

        # Confirm there ARE NaN values before imputation
        assert panel[ifgf_cols].isna().sum().sum() > 0

        result, log = impute_ifgf_mice(panel, m=3, max_iter=5)

        # All IFGF NaN should be filled
        assert result[ifgf_cols].isna().sum().sum() == 0

    def test_impute_log_structure(self):
        """Imputation log must contain required keys."""
        from database.impute_ifgf import impute_ifgf_mice

        panel = _make_synthetic_panel(n_munic=50, pct_missing=0.20)
        _, log = impute_ifgf_mice(panel, m=3, max_iter=5)

        required_keys = {"m", "max_iter", "method", "n_imputed_rows",
                         "ifgf_cols", "aux_cols", "per_year"}
        assert required_keys.issubset(set(log.keys())), (
            "Missing keys: %s" % (required_keys - set(log.keys()))
        )
        assert log["m"] == 3
        assert log["max_iter"] == 5
        assert log["n_imputed_rows"] > 0
        assert isinstance(log["per_year"], dict)

    def test_impute_preserves_aux(self):
        """Auxiliary columns must NOT be modified by imputation."""
        from database.impute_ifgf import impute_ifgf_mice

        panel = _make_synthetic_panel(n_munic=50, pct_missing=0.20)
        aux_cols = ["gdp_per_capita", "populacao"]
        original_aux = panel[aux_cols].copy()

        result, _ = impute_ifgf_mice(panel, m=3, max_iter=5)

        pd.testing.assert_frame_equal(result[aux_cols], original_aux)

    def test_impute_no_missing_noop(self):
        """Panel with zero missing IFGF should return unchanged and n_imputed_rows=0."""
        from database.impute_ifgf import impute_ifgf_mice

        panel = _make_synthetic_panel(n_munic=50, pct_missing=0.0)
        ifgf_cols = ["ifgf_geral", "ifgf_ra", "ifgf_gp", "ifgf_id", "ifgf_el", "ifgf_sa"]

        # Confirm no NaN
        assert panel[ifgf_cols].isna().sum().sum() == 0

        result, log = impute_ifgf_mice(panel, m=3, max_iter=5)

        assert log["n_imputed_rows"] == 0
        pd.testing.assert_frame_equal(result[ifgf_cols], panel[ifgf_cols])

    def test_impute_adds_flag_column(self):
        """ifgf_is_imputed column should be 1 where imputed, 0 otherwise."""
        from database.impute_ifgf import impute_ifgf_mice

        panel = _make_synthetic_panel(n_munic=50, pct_missing=0.20)
        result, _ = impute_ifgf_mice(panel, m=3, max_iter=5)

        assert "ifgf_is_imputed" in result.columns
        assert set(result["ifgf_is_imputed"].unique()).issubset({0, 1})
        assert result["ifgf_is_imputed"].sum() > 0


# ---------------------------------------------------------------------------
# Tests — generate_missingness_report
# ---------------------------------------------------------------------------

class TestGenerateMissingnessReport:
    """Tests for the generate_missingness_report() function."""

    def test_missingness_report_format(self):
        """Report CSV must have correct columns and MNAR/cross_sectional labels."""
        from database.impute_ifgf import generate_missingness_report

        panel = _make_synthetic_panel(n_munic=50, pct_missing=0.20)
        # Add an IDHM column (cross-sectional)
        panel["idhm"] = 0.75
        # Add a fully observed column
        panel["populacao"] = panel["populacao"].fillna(10000)

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "missingness.csv"
            result_path = generate_missingness_report(panel, out_path)

            assert result_path.exists()
            report = pd.read_csv(result_path)

            expected_cols = {"variable", "year", "n_total", "n_observed",
                            "n_missing", "pct_missing", "missingness_mechanism",
                            "handling_method"}
            assert expected_cols.issubset(set(report.columns))

            # IFGF cols should be marked MNAR
            ifgf_rows = report[report["variable"] == "ifgf_geral"]
            assert len(ifgf_rows) > 0
            assert (ifgf_rows["missingness_mechanism"] == "MNAR").all()
            assert (ifgf_rows["handling_method"] == "multiple_imputation_m5").all()

            # IDHM should be cross-sectional
            idhm_rows = report[report["variable"] == "idhm"]
            assert len(idhm_rows) > 0
            assert (idhm_rows["missingness_mechanism"] == "cross_sectional_2010").all()

    def test_missingness_report_fully_observed(self):
        """Column with 0% missing should have mechanism 'NA' and handling 'none'."""
        from database.impute_ifgf import generate_missingness_report

        panel = _make_synthetic_panel(n_munic=50, pct_missing=0.0)

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "missingness.csv"
            generate_missingness_report(panel, out_path)

            report = pd.read_csv(out_path, keep_default_na=False)

            # gdp_per_capita should be fully observed (NA mechanism)
            gdp_rows = report[report["variable"] == "gdp_per_capita"]
            assert len(gdp_rows) > 0
            assert (gdp_rows["missingness_mechanism"] == "NA").all()
            assert (gdp_rows["handling_method"] == "none").all()
