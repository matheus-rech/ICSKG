"""
ICSKG-BR Confidence Interval and Dispersion Reporting
=======================================================
Provides helper functions that attach standard deviation, standard error,
and 95 % confidence intervals to every summary statistic produced by the
ICSKG-BR pipeline.  Also generates a descriptive-statistics table that
reports mean +/- SD (95 % CI) and median (IQR) for CUDS and all six
LCoGS indicators, stratified by the five Brazilian macro-regions.

Functions
---------
  mean_ci         -- mean, SD, SE, t-distribution 95 % CI
  median_iqr      -- median, Q1, Q3, IQR
  wilson_ci       -- Wilson score CI for proportions
  poisson_ci      -- exact Poisson CI for rates
  add_ci_to_descriptives -- group-level descriptive stats with CIs
  add_ci_to_rates -- Poisson CI for per-100 000 rates
  generate_descriptive_table -- full descriptive table from SQLite

Usage
-----
    python analysis/reporting.py \\
        --db-path database/icskg_br.sqlite \\
        --out-dir results

Exports
-------
    mean_ci(values, confidence) -> dict
    median_iqr(values) -> dict
    wilson_ci(successes, trials, confidence) -> dict
    poisson_ci(count, person_time, confidence) -> dict
    add_ci_to_descriptives(df, value_cols, group_cols) -> pd.DataFrame
    add_ci_to_rates(df, count_col, pop_col, multiplier) -> pd.DataFrame
    generate_descriptive_table(db_path, out_dir) -> Path
    main(argv) -> int
"""

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
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

CUDS_COL = "cuds"

LCOGS_COLS = [
    "lcogs1_distance_km",
    "sao_per_100k",
    "surgical_volume_per_100k",
    "pomr",
    "financial_risk_ratio",
    "catastrophic_expenditure",
]

REGION_ORDER = ["Norte", "Nordeste", "Centro-Oeste", "Sudeste", "Sul"]


# ---------------------------------------------------------------------------
# Core statistical helpers
# ---------------------------------------------------------------------------

def mean_ci(
    values: np.ndarray,
    confidence: float = 0.95,
) -> dict:
    """Compute mean, SD, SE, and *t*-distribution confidence interval.

    Parameters
    ----------
    values : np.ndarray
        Numeric array (NaN values are dropped).
    confidence : float
        Confidence level (default 0.95 for 95 % CI).

    Returns
    -------
    dict
        Keys: mean, sd, se, ci_lower, ci_upper, n.
    """
    arr = np.asarray(values, dtype=float)
    arr = arr[~np.isnan(arr)]
    n = len(arr)

    if n == 0:
        return {
            "mean": np.nan, "sd": np.nan, "se": np.nan,
            "ci_lower": np.nan, "ci_upper": np.nan, "n": 0,
        }

    m = float(np.mean(arr))
    sd = float(np.std(arr, ddof=1)) if n > 1 else np.nan
    se = sd / np.sqrt(n) if n > 1 else np.nan

    if n == 1:
        return {
            "mean": m, "sd": np.nan, "se": np.nan,
            "ci_lower": np.nan, "ci_upper": np.nan, "n": 1,
        }

    # t-distribution CI (appropriate for small n like CV folds)
    alpha = 1.0 - confidence
    t_crit = stats.t.ppf(1.0 - alpha / 2.0, df=n - 1)
    ci_lower = m - t_crit * se
    ci_upper = m + t_crit * se

    return {
        "mean": m,
        "sd": sd,
        "se": se,
        "ci_lower": float(ci_lower),
        "ci_upper": float(ci_upper),
        "n": n,
    }


def median_iqr(values: np.ndarray) -> dict:
    """Compute median, Q1 (25th), Q3 (75th), and IQR.

    Parameters
    ----------
    values : np.ndarray
        Numeric array (NaN values are dropped).

    Returns
    -------
    dict
        Keys: median, q1, q3, iqr, n.
    """
    arr = np.asarray(values, dtype=float)
    arr = arr[~np.isnan(arr)]
    n = len(arr)

    if n == 0:
        return {
            "median": np.nan, "q1": np.nan, "q3": np.nan,
            "iqr": np.nan, "n": 0,
        }

    q1 = float(np.percentile(arr, 25))
    med = float(np.median(arr))
    q3 = float(np.percentile(arr, 75))

    return {
        "median": med,
        "q1": q1,
        "q3": q3,
        "iqr": q3 - q1,
        "n": n,
    }


def wilson_ci(
    successes: int,
    trials: int,
    confidence: float = 0.95,
) -> dict:
    """Wilson score confidence interval for a proportion.

    Better coverage than the Wald interval for small samples and extreme
    proportions.

    Parameters
    ----------
    successes : int
        Number of successes.
    trials : int
        Total number of trials.
    confidence : float
        Confidence level (default 0.95).

    Returns
    -------
    dict
        Keys: proportion, ci_lower, ci_upper.
    """
    if trials == 0:
        return {
            "proportion": np.nan,
            "ci_lower": np.nan,
            "ci_upper": np.nan,
        }

    p = successes / trials
    z = stats.norm.ppf(1.0 - (1.0 - confidence) / 2.0)
    z2 = z * z

    denom = 1.0 + z2 / trials
    centre = p + z2 / (2.0 * trials)
    margin = z * np.sqrt((p * (1.0 - p) + z2 / (4.0 * trials)) / trials)

    ci_lower = (centre - margin) / denom
    ci_upper = (centre + margin) / denom

    return {
        "proportion": float(p),
        "ci_lower": float(max(0.0, ci_lower)),
        "ci_upper": float(min(1.0, ci_upper)),
    }


def poisson_ci(
    count: int,
    person_time: float,
    confidence: float = 0.95,
) -> dict:
    """Exact Poisson confidence interval for a rate.

    Uses the chi-squared method:
      lower = chi2.ppf(alpha/2, 2*count)     / (2*person_time)
      upper = chi2.ppf(1-alpha/2, 2*(count+1)) / (2*person_time)

    Parameters
    ----------
    count : int
        Number of events.
    person_time : float
        Denominator (population, person-years, etc.).
    confidence : float
        Confidence level (default 0.95).

    Returns
    -------
    dict
        Keys: rate, ci_lower, ci_upper.
    """
    if person_time <= 0 or np.isnan(person_time):
        return {
            "rate": np.nan,
            "ci_lower": np.nan,
            "ci_upper": np.nan,
        }

    rate = count / person_time
    alpha = 1.0 - confidence

    if count == 0:
        ci_lower = 0.0
    else:
        ci_lower = stats.chi2.ppf(alpha / 2.0, 2 * count) / (2.0 * person_time)

    ci_upper = stats.chi2.ppf(1.0 - alpha / 2.0, 2 * (count + 1)) / (
        2.0 * person_time
    )

    return {
        "rate": float(rate),
        "ci_lower": float(ci_lower),
        "ci_upper": float(ci_upper),
    }


# ---------------------------------------------------------------------------
# DataFrame-level helpers
# ---------------------------------------------------------------------------

def add_ci_to_descriptives(
    df: pd.DataFrame,
    value_cols: list[str],
    group_cols: list[str],
) -> pd.DataFrame:
    """Group by *group_cols* and compute mean_ci + median_iqr for each column.

    Parameters
    ----------
    df : pd.DataFrame
        Input data.
    value_cols : list[str]
        Columns to summarise.
    group_cols : list[str]
        Columns defining the grouping structure.

    Returns
    -------
    pd.DataFrame
        Wide DataFrame with group_cols plus, for each value_col:
        {col}_mean, {col}_sd, {col}_ci_lower, {col}_ci_upper,
        {col}_median, {col}_iqr, {col}_n.
    """
    rows = []

    for name, grp in df.groupby(group_cols, observed=True):
        row = {}
        if isinstance(name, tuple):
            for gc, val in zip(group_cols, name):
                row[gc] = val
        else:
            row[group_cols[0]] = name

        for col in value_cols:
            if col not in grp.columns:
                continue

            vals = grp[col].dropna().values
            mc = mean_ci(vals)
            mi = median_iqr(vals)

            row["%s_mean" % col] = mc["mean"]
            row["%s_sd" % col] = mc["sd"]
            row["%s_ci_lower" % col] = mc["ci_lower"]
            row["%s_ci_upper" % col] = mc["ci_upper"]
            row["%s_median" % col] = mi["median"]
            row["%s_iqr" % col] = mi["iqr"]
            row["%s_n" % col] = mc["n"]

        rows.append(row)

    return pd.DataFrame(rows)


def add_ci_to_rates(
    df: pd.DataFrame,
    count_col: str,
    pop_col: str,
    multiplier: float = 100_000,
) -> pd.DataFrame:
    """Attach Poisson CI to per-population rates.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain *count_col* and *pop_col* columns.
    count_col : str
        Column with event counts.
    pop_col : str
        Column with population denominators.
    multiplier : float
        Rate multiplier (default 100 000).

    Returns
    -------
    pd.DataFrame
        Copy of *df* with added columns: rate, rate_ci_lower, rate_ci_upper.
    """
    out = df.copy()

    rates = []
    lowers = []
    uppers = []

    for _, row in out.iterrows():
        count = row[count_col]
        pop = row[pop_col]

        if pd.isna(count) or pd.isna(pop) or pop <= 0:
            rates.append(np.nan)
            lowers.append(np.nan)
            uppers.append(np.nan)
            continue

        ci = poisson_ci(int(count), float(pop))
        rates.append(ci["rate"] * multiplier)
        lowers.append(ci["ci_lower"] * multiplier)
        uppers.append(ci["ci_upper"] * multiplier)

    out["rate"] = rates
    out["rate_ci_lower"] = lowers
    out["rate_ci_upper"] = uppers

    return out


# ---------------------------------------------------------------------------
# Descriptive statistics table generator
# ---------------------------------------------------------------------------

def generate_descriptive_table(
    db_path: Path,
    out_dir: Path,
) -> Path:
    """Generate a descriptive-statistics table from the SQLite database.

    Loads dimension_scores, lcogs_indicators, and municipality_lookup,
    computes mean +/- SD (95 % CI) for CUDS and all 6 LCoGS indicators
    by region and overall.

    Parameters
    ----------
    db_path : Path
        Path to ICSKG-BR SQLite database.
    out_dir : Path
        Root output directory.

    Returns
    -------
    Path
        Path to the saved CSV file.
    """
    db_path = Path(db_path)
    out_dir = Path(out_dir)
    tables_dir = out_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    try:
        dims = pd.read_sql("SELECT cod_ibge, year, cuds FROM dimension_scores", conn)
        lcogs = pd.read_sql("SELECT * FROM lcogs_indicators", conn)
        lookup = pd.read_sql(
            "SELECT cod_ibge, region FROM municipality_lookup", conn,
        )
    finally:
        conn.close()

    # Ensure consistent types
    for df in [dims, lcogs, lookup]:
        if "cod_ibge" in df.columns:
            df["cod_ibge"] = df["cod_ibge"].astype(str)
        if "year" in df.columns:
            df["year"] = df["year"].astype(int)

    panel = dims.merge(lcogs, on=["cod_ibge", "year"], how="inner")
    panel = panel.merge(lookup, on="cod_ibge", how="inner")

    value_cols = [CUDS_COL] + LCOGS_COLS
    value_cols = [c for c in value_cols if c in panel.columns]

    # --- By region ---
    region_stats = add_ci_to_descriptives(panel, value_cols, ["region"])

    # --- Overall ---
    panel_overall = panel.copy()
    panel_overall["region"] = "Overall"
    overall_stats = add_ci_to_descriptives(panel_overall, value_cols, ["region"])

    # Combine
    combined = pd.concat([region_stats, overall_stats], ignore_index=True)

    # Reorder regions
    order = REGION_ORDER + ["Overall"]
    combined["_sort"] = combined["region"].map(
        {r: i for i, r in enumerate(order)}
    ).fillna(99)
    combined = combined.sort_values("_sort").drop(columns="_sort").reset_index(drop=True)

    csv_path = tables_dir / "descriptive_stats_with_ci.csv"
    combined.to_csv(csv_path, index=False)

    logger.info(
        "generate_descriptive_table: saved %d rows to %s",
        len(combined), csv_path,
    )

    return csv_path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Generate descriptive statistics with confidence intervals.

    Usage
    -----
        python analysis/reporting.py \\
            --db-path database/icskg_br.sqlite \\
            --out-dir results
    """
    parser = argparse.ArgumentParser(
        description="ICSKG-BR confidence interval and dispersion reporting",
    )
    parser.add_argument(
        "--db-path",
        default="database/icskg_br.sqlite",
        help="Path to SQLite database (default: database/icskg_br.sqlite)",
    )
    parser.add_argument(
        "--out-dir",
        default="results",
        help="Output directory (default: results)",
    )
    args = parser.parse_args(argv)

    db_path = Path(args.db_path)
    out_dir = Path(args.out_dir)

    logger.info("=" * 60)
    logger.info("DESCRIPTIVE STATISTICS WITH CI/DISPERSION")
    logger.info("=" * 60)

    csv_path = generate_descriptive_table(db_path, out_dir)

    logger.info("Descriptive table saved: %s", csv_path)
    logger.info("Reporting module complete.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
