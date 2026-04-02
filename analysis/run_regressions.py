"""
ICSKG-BR Panel Regression Engine
==================================
Runs six two-way fixed-effects panel regressions of CUDS on each LCoGS
outcome using linearmodels PanelOLS, with cluster-robust standard errors
at municipality level, Hausman FE-vs-RE selection tests, polynomial
dose-response analysis, and sensitivity analyses.

Regressions (6)
-----------------
  1. LCoGS-1: Bellwether Access (km)       -- lcogs1_distance_km
  2. LCoGS-2: SAO Density per 100k         -- sao_per_100k
  3. LCoGS-3: Surgical Volume per 100k     -- surgical_volume_per_100k
  4. LCoGS-4: Perioperative Mortality       -- pomr
  5. LCoGS-5: Financial Risk Ratio          -- financial_risk_ratio
  6. LCoGS-6: Catastrophic Expenditure      -- catastrophic_expenditure

Model specification
--------------------
  dependent ~ cuds  (+ municipality FE + year FE)
  Two-way fixed effects: entity_effects=True, time_effects=True
  Cluster-robust SE: cov_type="clustered", cluster_entity=True

Hausman test
-------------
  Compares FE vs RE for each outcome; FE used regardless for robustness.

Dose-response
--------------
  Quantile-binned CUDS with polynomial fit (degree 3) for non-linearity.

Sensitivity
------------
  1. Arithmetic-mean CUDS (vs geometric-mean)
  2. Exclude municipalities with >=2 missing dimensions

Usage
-----
    python analysis/run_regressions.py \\
        --db-path database/icskg_br.sqlite \\
        --out-dir results

Exports
-------
    load_regression_panel(db_path) -> pd.DataFrame
    run_panel_regressions(panel) -> dict
    run_hausman_tests(panel) -> pd.DataFrame
    run_dose_response(panel, outcome, n_bins) -> pd.DataFrame
    run_sensitivity(panel, db_path) -> dict
    save_regression_tables(results, out_dir) -> None
    main(argv) -> int
"""

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from linearmodels.panel import PanelOLS, RandomEffects
from scipy import stats

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# LCoGS outcomes for 6 regressions
LCOGS_OUTCOMES = [
    ("lcogs1_distance_km",       "LCoGS-1: Bellwether Access (km)"),
    ("sao_per_100k",             "LCoGS-2: SAO Density per 100k"),
    ("surgical_volume_per_100k", "LCoGS-3: Surgical Volume per 100k"),
    ("pomr",                     "LCoGS-4: Perioperative Mortality"),
    ("financial_risk_ratio",     "LCoGS-5: Financial Risk Ratio"),
    ("catastrophic_expenditure", "LCoGS-6: Catastrophic Expenditure"),
]

# Dimension columns from compute_dimensions.py
DIM_COLS = ["D1", "D2", "D3", "D4", "D5", "D6", "D7", "D9"]

# Epsilon for geometric mean (from compute_dimensions.py)
EPSILON = 0.01


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_regression_panel(db_path: Path) -> pd.DataFrame:
    """Load dimension_scores and lcogs_indicators from SQLite, join, set index.

    Parameters
    ----------
    db_path : Path
        Path to SQLite database containing dimension_scores and
        lcogs_indicators tables.

    Returns
    -------
    pd.DataFrame
        Panel with MultiIndex (cod_ibge, year) as required by linearmodels.
        Contains cuds (independent variable) and 6 LCoGS outcome columns.
    """
    db_path = Path(db_path)
    conn = sqlite3.connect(str(db_path))

    try:
        dims = pd.read_sql("SELECT * FROM dimension_scores", conn)
        lcogs = pd.read_sql("SELECT * FROM lcogs_indicators", conn)
    finally:
        conn.close()

    # Ensure consistent types for join keys
    dims["cod_ibge"] = dims["cod_ibge"].astype(str)
    dims["year"] = dims["year"].astype(int)
    lcogs["cod_ibge"] = lcogs["cod_ibge"].astype(str)
    lcogs["year"] = lcogs["year"].astype(int)

    # Inner join: only keep municipality-years present in both tables
    panel = dims.merge(lcogs, on=["cod_ibge", "year"], how="inner")

    # Drop rows where cuds is NaN (independent variable must be non-null)
    n_before = len(panel)
    panel = panel.dropna(subset=["cuds"])
    n_dropped = n_before - len(panel)
    if n_dropped > 0:
        logger.info(
            "load_regression_panel: dropped %d rows with NaN cuds "
            "(%d remaining)",
            n_dropped, len(panel),
        )

    # Set MultiIndex as required by linearmodels PanelOLS
    panel = panel.set_index(["cod_ibge", "year"])

    logger.info(
        "load_regression_panel: %d observations loaded from %s",
        len(panel), db_path,
    )

    return panel


# ---------------------------------------------------------------------------
# Core regression function
# ---------------------------------------------------------------------------

def run_panel_regressions(panel: pd.DataFrame) -> dict:
    """Run six PanelOLS regressions of LCoGS outcomes on CUDS.

    Each regression uses two-way fixed effects (municipality + year)
    with cluster-robust standard errors at the municipality level.

    Parameters
    ----------
    panel : pd.DataFrame
        Panel with MultiIndex (cod_ibge, year) containing cuds and
        6 LCoGS outcome columns.

    Returns
    -------
    dict
        Mapping from outcome column name to PanelOLS result object.
    """
    results = {}

    for outcome_col, outcome_label in LCOGS_OUTCOMES:
        if outcome_col not in panel.columns:
            logger.warning(
                "run_panel_regressions: outcome '%s' not in panel -- skipping",
                outcome_col,
            )
            continue

        # Drop rows with NaN in the dependent variable (per-regression)
        subset = panel[["cuds", outcome_col]].dropna()

        if len(subset) < 10:
            logger.warning(
                "run_panel_regressions: %s has only %d valid observations "
                "-- skipping",
                outcome_col, len(subset),
            )
            continue

        y = subset[outcome_col]
        x = subset[["cuds"]]

        # PanelOLS with two-way fixed effects
        mod = PanelOLS(
            dependent=y,
            exog=x,
            entity_effects=True,
            time_effects=True,
            check_rank=False,
        )

        # Fit with cluster-robust SE at municipality level (STAT-02)
        res = mod.fit(cov_type="clustered", cluster_entity=True)

        results[outcome_col] = res

        logger.info(
            "  %s: N=%d, R2_within=%.4f, coef=%.4f, p=%.4f",
            outcome_label,
            res.nobs,
            res.rsquared_within,
            res.params.get("cuds", float("nan")),
            res.pvalues.get("cuds", float("nan")),
        )

    logger.info(
        "run_panel_regressions: %d of %d regressions completed",
        len(results), len(LCOGS_OUTCOMES),
    )

    return results


# ---------------------------------------------------------------------------
# Hausman test
# ---------------------------------------------------------------------------

def run_hausman_tests(panel: pd.DataFrame) -> pd.DataFrame:
    """Run Hausman FE-vs-RE test for each LCoGS outcome.

    Computes H = (b_FE - b_RE)' * (V_FE - V_RE)^{-1} * (b_FE - b_RE)
    where b are coefficient vectors and V are covariance matrices.

    Parameters
    ----------
    panel : pd.DataFrame
        Panel with MultiIndex (cod_ibge, year) containing cuds and
        6 LCoGS outcome columns.

    Returns
    -------
    pd.DataFrame
        Columns: outcome, chi2_stat, p_value, df, preferred_model.
    """
    rows = []

    for outcome_col, outcome_label in LCOGS_OUTCOMES:
        if outcome_col not in panel.columns:
            continue

        subset = panel[["cuds", outcome_col]].dropna()
        if len(subset) < 10:
            rows.append({
                "outcome": outcome_col,
                "chi2_stat": np.nan,
                "p_value": np.nan,
                "df": 0,
                "preferred_model": "insufficient_data",
            })
            continue

        y = subset[outcome_col]
        x = subset[["cuds"]]

        # Fixed effects model
        fe_mod = PanelOLS(
            dependent=y, exog=x,
            entity_effects=True,
            check_rank=False,
        )
        fe_res = fe_mod.fit()

        # Random effects model
        re_mod = RandomEffects(dependent=y, exog=x, check_rank=False)
        re_res = re_mod.fit()

        # Hausman test statistic
        b_fe = fe_res.params.values
        b_re = re_res.params.values
        v_fe = np.array(fe_res.cov)
        v_re = np.array(re_res.cov)

        # Difference in coefficients and covariance
        b_diff = b_fe - b_re
        v_diff = v_fe - v_re

        try:
            # H = b_diff' * inv(v_diff) * b_diff
            v_diff_inv = np.linalg.inv(v_diff)
            h_stat = float(b_diff @ v_diff_inv @ b_diff)
            # Ensure non-negative (numerical precision)
            h_stat = max(0.0, h_stat)
            k = len(b_diff)
            p_val = float(stats.chi2.sf(h_stat, df=k))
        except np.linalg.LinAlgError:
            h_stat = np.nan
            p_val = np.nan
            k = len(b_diff)

        preferred = "FE" if (not np.isnan(p_val) and p_val < 0.05) else "RE"

        rows.append({
            "outcome": outcome_col,
            "chi2_stat": h_stat,
            "p_value": p_val,
            "df": k,
            "preferred_model": preferred,
        })

        logger.info(
            "  Hausman %s: H=%.4f, p=%.4f, preferred=%s",
            outcome_label, h_stat, p_val, preferred,
        )

    hausman_df = pd.DataFrame(rows)

    logger.info(
        "run_hausman_tests: %d tests completed", len(hausman_df),
    )

    return hausman_df


# ---------------------------------------------------------------------------
# Result export
# ---------------------------------------------------------------------------

def save_regression_tables(results: dict, out_dir: Path) -> None:
    """Save regression results as CSV tables.

    Creates one CSV per regression in results/regression_tables/ plus
    a combined summary CSV.

    Parameters
    ----------
    results : dict
        Mapping from outcome column name to PanelOLS result object.
    out_dir : Path
        Root output directory (results/).
    """
    out_dir = Path(out_dir)
    tables_dir = out_dir / "regression_tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    summary_rows = []

    for outcome_col, res in results.items():
        # Extract per-regression details
        params = res.params
        std_errors = res.std_errors
        tstats = res.tstats
        pvalues = res.pvalues
        conf_int = res.conf_int()

        # Build detailed table
        detail = pd.DataFrame({
            "variable": params.index,
            "coefficient": params.values,
            "std_error": std_errors.values,
            "t_stat": tstats.values,
            "p_value": pvalues.values,
            "ci_lower": conf_int.iloc[:, 0].values,
            "ci_upper": conf_int.iloc[:, 1].values,
        })

        # Add model-level statistics
        detail["n_obs"] = res.nobs
        detail["r2_within"] = res.rsquared_within
        detail["r2_between"] = res.rsquared_between
        detail["r2_overall"] = res.rsquared_overall

        detail.to_csv(tables_dir / ("%s.csv" % outcome_col), index=False)

        # Summary row for combined table (cuds coefficient only)
        if "cuds" in params.index:
            cuds_idx = list(params.index).index("cuds")
            summary_rows.append({
                "outcome": outcome_col,
                "coefficient": float(params["cuds"]),
                "std_error": float(std_errors["cuds"]),
                "t_stat": float(tstats["cuds"]),
                "p_value": float(pvalues["cuds"]),
                "ci_lower": float(conf_int.iloc[cuds_idx, 0]),
                "ci_upper": float(conf_int.iloc[cuds_idx, 1]),
                "n_obs": int(res.nobs),
                "r2_within": float(res.rsquared_within),
                "r2_between": float(res.rsquared_between),
                "r2_overall": float(res.rsquared_overall),
            })

    if summary_rows:
        summary_df = pd.DataFrame(summary_rows)
        summary_df.to_csv(tables_dir / "combined_summary.csv", index=False)
        logger.info(
            "save_regression_tables: %d tables saved to %s",
            len(results), tables_dir,
        )


# ---------------------------------------------------------------------------
# Dose-response analysis
# ---------------------------------------------------------------------------

def run_dose_response(
    panel: pd.DataFrame,
    outcome: str,
    n_bins: int = 20,
) -> pd.DataFrame:
    """Compute binned dose-response of CUDS on a LCoGS outcome.

    Bins CUDS into quantile bins (vingtiles by default), computes
    mean and SE of the outcome for each bin, and fits a polynomial
    regression (degree 3) for the non-linear relationship.

    Parameters
    ----------
    panel : pd.DataFrame
        Panel with MultiIndex (cod_ibge, year) containing cuds and
        the outcome column.
    outcome : str
        Name of the LCoGS outcome column.
    n_bins : int
        Number of quantile bins (default: 20 = vingtiles).

    Returns
    -------
    pd.DataFrame
        Columns: cuds_bin_midpoint, mean_outcome, se_outcome, n_obs,
        poly_predicted.
    """
    if outcome not in panel.columns:
        logger.warning(
            "run_dose_response: outcome '%s' not in panel", outcome,
        )
        return pd.DataFrame()

    subset = panel[["cuds", outcome]].dropna()
    if len(subset) < n_bins:
        logger.warning(
            "run_dose_response: only %d valid observations for %s "
            "(need >= %d for binning)",
            len(subset), outcome, n_bins,
        )
        return pd.DataFrame()

    # Bin CUDS into quantile bins
    subset = subset.copy()
    subset["cuds_bin"] = pd.qcut(
        subset["cuds"], q=n_bins, duplicates="drop",
    )

    # Compute bin-level statistics
    grouped = subset.groupby("cuds_bin", observed=True)
    binned = grouped.agg(
        cuds_bin_midpoint=("cuds", "mean"),
        mean_outcome=(outcome, "mean"),
        se_outcome=(outcome, "sem"),
        n_obs=(outcome, "count"),
    ).reset_index(drop=True)

    # Add 95 % CI columns to the binned output
    binned["ci_lower"] = binned["mean_outcome"] - 1.96 * binned["se_outcome"]
    binned["ci_upper"] = binned["mean_outcome"] + 1.96 * binned["se_outcome"]

    # Polynomial fit (degree 3) on the raw data for predicted values
    coeffs = np.polyfit(subset["cuds"].values, subset[outcome].values, deg=3)
    poly = np.poly1d(coeffs)
    binned["poly_predicted"] = poly(binned["cuds_bin_midpoint"].values)

    # Store polynomial coefficients as metadata
    binned.attrs["poly_coefficients"] = coeffs.tolist()
    binned.attrs["poly_degree"] = 3

    logger.info(
        "run_dose_response(%s): %d bins, poly degree 3, "
        "coeffs=%s",
        outcome, len(binned),
        [round(c, 6) for c in coeffs],
    )

    return binned


# ---------------------------------------------------------------------------
# Sensitivity analyses
# ---------------------------------------------------------------------------

def run_sensitivity(panel: pd.DataFrame, db_path: Path | None = None) -> dict:
    """Run two sensitivity analyses.

    Sensitivity 1 -- Arithmetic-mean CUDS:
      Recomputes CUDS as simple arithmetic mean of available normalized
      dimensions (no epsilon, no geometric mean).

    Sensitivity 2 -- Exclude high-missingness municipalities:
      Filters panel to rows where n_dimensions >= 7 (at most 1 of 8
      dimensions missing).

    Parameters
    ----------
    panel : pd.DataFrame
        Panel with MultiIndex (cod_ibge, year) containing cuds,
        dimension columns (D1..D7, D9), n_dimensions, and 6 LCoGS
        outcome columns.
    db_path : Path, optional
        Not used directly; reserved for future sensitivity extensions.

    Returns
    -------
    dict
        Keys: "arithmetic_cuds" and "exclude_missing_dims", each
        containing a dict of regression results (same format as
        run_panel_regressions output).
    """
    results = {}

    # --- Sensitivity 1: Arithmetic-mean CUDS ---
    logger.info("─" * 60)
    logger.info("SENSITIVITY 1: Arithmetic-mean CUDS")
    logger.info("─" * 60)

    available_dims = [c for c in DIM_COLS if c in panel.columns]
    if available_dims:
        panel_arith = panel.copy()
        panel_arith["cuds"] = panel_arith[available_dims].mean(
            axis=1, skipna=True,
        )
        arith_results = run_panel_regressions(panel_arith)
        results["arithmetic_cuds"] = arith_results

        logger.info(
            "Sensitivity 1: %d regressions with arithmetic CUDS",
            len(arith_results),
        )
    else:
        logger.warning(
            "Sensitivity 1: no dimension columns found -- skipping",
        )
        results["arithmetic_cuds"] = {}

    # --- Sensitivity 2: Exclude high-missingness municipalities ---
    logger.info("─" * 60)
    logger.info("SENSITIVITY 2: Exclude high-missingness municipalities")
    logger.info("─" * 60)

    if "n_dimensions" in panel.columns:
        n_before = len(panel)
        panel_filtered = panel[panel["n_dimensions"] >= 7].copy()
        n_after = len(panel_filtered)
        n_dropped = n_before - n_after

        logger.info(
            "Sensitivity 2: dropped %d rows with n_dimensions < 7 "
            "(%d remaining of %d)",
            n_dropped, n_after, n_before,
        )

        if len(panel_filtered) >= 10:
            excl_results = run_panel_regressions(panel_filtered)
        else:
            logger.warning(
                "Sensitivity 2: only %d rows after filtering -- skipping",
                len(panel_filtered),
            )
            excl_results = {}
    else:
        logger.warning(
            "Sensitivity 2: n_dimensions column not found -- skipping",
        )
        excl_results = {}

    results["exclude_missing_dims"] = excl_results

    return results


# ---------------------------------------------------------------------------
# Sensitivity export helpers
# ---------------------------------------------------------------------------

def _save_sensitivity_results(
    sens_results: dict,
    key: str,
    filename: str,
    out_dir: Path,
) -> None:
    """Save sensitivity regression results as CSV.

    Parameters
    ----------
    sens_results : dict
        Output of run_sensitivity().
    key : str
        Sensitivity key ("arithmetic_cuds" or "exclude_missing_dims").
    filename : str
        Output CSV filename.
    out_dir : Path
        Root output directory.
    """
    sens_dir = out_dir / "sensitivity"
    sens_dir.mkdir(parents=True, exist_ok=True)

    reg_results = sens_results.get(key, {})
    if not reg_results:
        return

    rows = []
    for outcome_col, res in reg_results.items():
        if "cuds" in res.params.index:
            conf = res.conf_int()
            cuds_idx = list(res.params.index).index("cuds")
            rows.append({
                "outcome": outcome_col,
                "coefficient": float(res.params["cuds"]),
                "std_error": float(res.std_errors["cuds"]),
                "t_stat": float(res.tstats["cuds"]),
                "p_value": float(res.pvalues["cuds"]),
                "ci_lower": float(conf.iloc[cuds_idx, 0]),
                "ci_upper": float(conf.iloc[cuds_idx, 1]),
                "n_obs": int(res.nobs),
                "r2_within": float(res.rsquared_within),
            })

    if rows:
        df = pd.DataFrame(rows)
        df.to_csv(sens_dir / filename, index=False)
        logger.info("Saved sensitivity results: %s", sens_dir / filename)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Run all statistical analyses: regressions, Hausman, dose-response,
    sensitivity.

    Usage
    -----
        python analysis/run_regressions.py \\
            --db-path database/icskg_br.sqlite \\
            --out-dir results
    """
    parser = argparse.ArgumentParser(
        description="ICSKG-BR panel regression engine",
    )
    parser.add_argument(
        "--db-path",
        default="database/icskg_br.sqlite",
        help="Path to SQLite database (default: database/icskg_br.sqlite)",
    )
    parser.add_argument(
        "--out-dir",
        default="results",
        help="Output directory for regression tables (default: results)",
    )
    args = parser.parse_args(argv)

    db_path = Path(args.db_path)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------
    # Load panel
    # ---------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("PANEL REGRESSION ENGINE")
    logger.info("=" * 60)

    panel = load_regression_panel(db_path)
    if len(panel) == 0:
        logger.error("Panel is empty -- cannot run regressions")
        return 1

    # ---------------------------------------------------------------
    # Core regressions (STAT-01, STAT-02)
    # ---------------------------------------------------------------
    logger.info("─" * 60)
    logger.info("STAGE: PanelOLS regressions (two-way FE, cluster-robust SE)")
    logger.info("─" * 60)

    results = run_panel_regressions(panel)
    save_regression_tables(results, out_dir)

    # ---------------------------------------------------------------
    # Hausman tests (STAT-03)
    # ---------------------------------------------------------------
    logger.info("─" * 60)
    logger.info("STAGE: Hausman FE-vs-RE tests")
    logger.info("─" * 60)

    hausman_df = run_hausman_tests(panel)
    hausman_path = out_dir / "hausman_test.csv"
    hausman_df.to_csv(hausman_path, index=False)
    logger.info("Hausman results saved to %s", hausman_path)

    # ---------------------------------------------------------------
    # Dose-response analysis (STAT-04)
    # ---------------------------------------------------------------
    logger.info("─" * 60)
    logger.info("STAGE: Dose-response analysis")
    logger.info("─" * 60)

    for outcome_col, outcome_label in LCOGS_OUTCOMES:
        dr = run_dose_response(panel, outcome_col)
        if not dr.empty:
            dr_path = out_dir / ("dose_response_%s.csv" % outcome_col)
            dr.to_csv(dr_path, index=False)
            logger.info("Dose-response saved: %s", dr_path)

    # ---------------------------------------------------------------
    # Sensitivity analyses
    # ---------------------------------------------------------------
    logger.info("─" * 60)
    logger.info("STAGE: Sensitivity analyses")
    logger.info("─" * 60)

    sens = run_sensitivity(panel)
    _save_sensitivity_results(
        sens, "arithmetic_cuds",
        "arithmetic_cuds_regressions.csv", out_dir,
    )
    _save_sensitivity_results(
        sens, "exclude_missing_dims",
        "exclude_missing_dims_regressions.csv", out_dir,
    )

    # ---------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("REGRESSION ENGINE COMPLETE")
    logger.info("  Core regressions: %d", len(results))
    logger.info("  Hausman tests: %d", len(hausman_df))
    logger.info("  Sensitivity analyses: 2")
    logger.info("  Output directory: %s", out_dir)
    logger.info("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
