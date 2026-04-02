"""
Tests for database.impute_ifgf — IFGF multiple imputation and missingness report.
"""

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def synthetic_panel() -> pd.DataFrame:
    """Create a synthetic panel with controlled NaN in IFGF columns."""
    rng = np.random.default_rng(42)
    n = 100
    panel = pd.DataFrame({
        "cod_ibge": [f"{3500000 + i:07d}" for i in range(n)],
        "year": [2020] * n,
        "ifgf_geral": rng.uniform(0.2, 0.8, n).astype(float),
        "ifgf_ra": rng.uniform(0.1, 0.9, n).astype(float),
        "ifgf_gp": rng.uniform(0.1, 0.9, n).astype(float),
        "ifgf_id": rng.uniform(0.1, 0.9, n).astype(float),
        "ifgf_el": rng.uniform(0.1, 0.9, n).astype(float),
        "ifgf_sa": rng.uniform(0.1, 0.9, n).astype(float),
        "gdp_per_capita": rng.uniform(10000, 80000, n).astype(float),
        "populacao": rng.integers(5000, 500000, n).astype(float),
        "uf": rng.choice(["SP", "RJ", "MG", "BA", "RS"], n),
    })
    # Inject 20% NaN in all IFGF columns (same rows)
    nan_idx = rng.choice(n, size=20, replace=False)
    for col in ["ifgf_geral", "ifgf_ra", "ifgf_gp", "ifgf_id", "ifgf_el", "ifgf_sa"]:
        panel.loc[nan_idx, col] = np.nan
    return panel


@pytest.fixture()
def full_panel() -> pd.DataFrame:
    """Create a panel with NO missing IFGF values."""
    rng = np.random.default_rng(99)
    n = 50
    return pd.DataFrame({
        "cod_ibge": [f"{3500000 + i:07d}" for i in range(n)],
        "year": [2021] * n,
        "ifgf_geral": rng.uniform(0.2, 0.8, n),
        "ifgf_ra": rng.uniform(0.1, 0.9, n),
        "ifgf_gp": rng.uniform(0.1, 0.9, n),
        "ifgf_id": rng.uniform(0.1, 0.9, n),
        "ifgf_el": rng.uniform(0.1, 0.9, n),
        "ifgf_sa": rng.uniform(0.1, 0.9, n),
        "gdp_per_capita": rng.uniform(10000, 80000, n),
        "populacao": rng.integers(5000, 500000, n).astype(float),
        "uf": rng.choice(["SP", "RJ", "MG"], n),
    })


@pytest.fixture()
def missingness_panel() -> pd.DataFrame:
    """Panel with mixed missingness patterns for report testing."""
    rng = np.random.default_rng(7)
    n = 60
    panel = pd.DataFrame({
        "cod_ibge": [f"{3500000 + i:07d}" for i in range(n)],
        "year": [2020] * 30 + [2021] * 30,
        "ifgf_geral": rng.uniform(0.2, 0.8, n),
        "idhm": rng.uniform(0.5, 0.9, n),
        "gdp_per_capita": rng.uniform(10000, 80000, n),
        "pct_sanitation_adequate": rng.uniform(0.3, 0.95, n),
        "health_expenditure_per_capita": rng.uniform(100, 2000, n),
        "vehicles_per_1000": rng.uniform(50, 500, n),
    })
    # IFGF: MNAR -- inject NaN
    nan_idx = rng.choice(n, size=12, replace=False)
    panel.loc[nan_idx, "ifgf_geral"] = np.nan
    return panel


# ---------------------------------------------------------------------------
# Tests: impute_ifgf_mice
# ---------------------------------------------------------------------------

class TestImputeIfgfMice:
    """Tests for the impute_ifgf_mice function."""

    def test_impute_fills_nan(self, synthetic_panel: pd.DataFrame) -> None:
        """Imputed panel should have zero NaN in IFGF columns."""
        from database.impute_ifgf import impute_ifgf_mice

        result, _log = impute_ifgf_mice(synthetic_panel, m=3, max_iter=5)
        ifgf_cols = ["ifgf_geral", "ifgf_ra", "ifgf_gp",
                     "ifgf_id", "ifgf_el", "ifgf_sa"]
        for col in ifgf_cols:
            assert result[col].isna().sum() == 0, (
                "Column %s still has NaN after imputation" % col
            )

    def test_impute_log_structure(self, synthetic_panel: pd.DataFrame) -> None:
        """Imputation log must contain required keys."""
        from database.impute_ifgf import impute_ifgf_mice

        _result, log = impute_ifgf_mice(synthetic_panel, m=3, max_iter=5)
        required_keys = {
            "m", "max_iter", "method", "n_imputed_rows",
            "ifgf_cols", "aux_cols", "per_year",
        }
        assert required_keys.issubset(set(log.keys())), (
            "Missing log keys: %s" % (required_keys - set(log.keys()))
        )
        assert log["m"] == 3
        assert log["max_iter"] == 5
        assert log["n_imputed_rows"] == 20  # 20 rows had NaN injected

    def test_impute_preserves_aux(self, synthetic_panel: pd.DataFrame) -> None:
        """Auxiliary columns must NOT be modified by imputation."""
        from database.impute_ifgf import impute_ifgf_mice

        orig_gdp = synthetic_panel["gdp_per_capita"].copy()
        orig_pop = synthetic_panel["populacao"].copy()

        result, _log = impute_ifgf_mice(synthetic_panel, m=3, max_iter=5)

        pd.testing.assert_series_equal(
            result["gdp_per_capita"], orig_gdp,
            check_names=False,
        )
        pd.testing.assert_series_equal(
            result["populacao"], orig_pop,
            check_names=False,
        )

    def test_impute_no_missing_noop(self, full_panel: pd.DataFrame) -> None:
        """Panel with zero missing IFGF returns n_imputed_rows=0."""
        from database.impute_ifgf import impute_ifgf_mice

        result, log = impute_ifgf_mice(full_panel, m=3, max_iter=5)
        assert log["n_imputed_rows"] == 0
        # DataFrame should be unchanged (no ifgf_is_imputed column or all 0)
        if "ifgf_is_imputed" in result.columns:
            assert result["ifgf_is_imputed"].sum() == 0

    def test_impute_adds_flag_column(self, synthetic_panel: pd.DataFrame) -> None:
        """Imputed panel must have ifgf_is_imputed flag column."""
        from database.impute_ifgf import impute_ifgf_mice

        result, _log = impute_ifgf_mice(synthetic_panel, m=3, max_iter=5)
        assert "ifgf_is_imputed" in result.columns
        assert result["ifgf_is_imputed"].sum() == 20


# ---------------------------------------------------------------------------
# Tests: generate_missingness_report
# ---------------------------------------------------------------------------

class TestMissingnessReport:
    """Tests for the generate_missingness_report function."""

    def test_missingness_report_format(self, missingness_panel: pd.DataFrame) -> None:
        """Missingness CSV must have correct columns and labels."""
        from database.impute_ifgf import generate_missingness_report

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "missingness.csv"
            result_path = generate_missingness_report(
                missingness_panel, out_path,
            )
            assert result_path.exists()
            df = pd.read_csv(result_path, keep_default_na=False)

            expected_cols = {
                "variable", "year", "n_total", "n_observed",
                "n_missing", "pct_missing", "missingness_mechanism",
                "handling_method",
            }
            assert expected_cols == set(df.columns), (
                "Columns mismatch: got %s" % set(df.columns)
            )

            # IFGF should be MNAR
            ifgf_rows = df[df["variable"] == "ifgf_geral"]
            assert all(
                ifgf_rows["missingness_mechanism"] == "MNAR"
            ), "IFGF should be classified as MNAR"

            # IDHM should be cross_sectional_2010
            idhm_rows = df[df["variable"] == "idhm"]
            assert all(
                idhm_rows["missingness_mechanism"] == "cross_sectional_2010"
            ), "IDHM should be classified as cross_sectional_2010"

    def test_missingness_report_fully_observed(
        self, missingness_panel: pd.DataFrame,
    ) -> None:
        """Column with 0% missing should have mechanism NA and handling none."""
        from database.impute_ifgf import generate_missingness_report

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "missingness.csv"
            generate_missingness_report(missingness_panel, out_path)
            df = pd.read_csv(out_path, keep_default_na=False)

            # GDP is fully observed in the fixture
            gdp_rows = df[df["variable"] == "gdp_per_capita"]
            assert all(gdp_rows["pct_missing"] == 0.0), (
                "GDP should have 0%% missing"
            )
            assert all(gdp_rows["missingness_mechanism"] == "NA"), (
                "Fully observed should have mechanism NA"
            )
            assert all(gdp_rows["handling_method"] == "none"), (
                "Fully observed should have handling none"
            )

    def test_missingness_sanitation_cross_sectional(
        self, missingness_panel: pd.DataFrame,
    ) -> None:
        """Sanitation columns should be marked cross_sectional_2022."""
        from database.impute_ifgf import generate_missingness_report

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "missingness.csv"
            generate_missingness_report(missingness_panel, out_path)
            df = pd.read_csv(out_path, keep_default_na=False)

            sanit_rows = df[df["variable"] == "pct_sanitation_adequate"]
            assert all(
                sanit_rows["missingness_mechanism"] == "cross_sectional_2022"
            ), "Sanitation should be cross_sectional_2022"
