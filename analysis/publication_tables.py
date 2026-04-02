"""
ICSKG-BR Publication Tables
==============================
Generates all publication-ready tables for BMJ Global Health submission.

Produces 8+ CSV tables with SD/SE/IQR, 95% CIs, and dual-currency
(constant 2023 BRL + USD) columns where applicable:
  Table 1: Descriptive statistics with CIs
  Table 2: CIMI dimension descriptives by region
  Table 3: Missingness summary (RECORD 12.1 compliance)
  Table 4: Correlation matrix (CUDS dimensions x LCoGS indicators)
  Tables 5-8: Regression results (PanelOLS coefficients, cluster-robust SE)
  Sensitivity tables: Arithmetic CUDS and exclude-missing-dims

Usage
-----
    python analysis/publication_tables.py \\
        --db-path database/icskg_br.sqlite \\
        --out-dir results

Exports
-------
    generate_descriptive_table(db_path, out_dir) -> Path
    generate_dimension_descriptives(db_path, out_dir) -> Path
    generate_missingness_table(db_path, out_dir) -> Path
    generate_correlation_matrix(db_path, out_dir) -> Path
    generate_regression_tables(db_path, out_dir) -> list[Path]
    generate_sensitivity_tables(db_path, out_dir) -> list[Path]
    generate_all_tables(db_path, out_dir) -> list[Path]
    main(argv) -> int
"""

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DIM_COLS = ["D1", "D2", "D3", "D4", "D5", "D6", "D7", "D9"]

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

# Monetary columns that should have dual-currency (BRL + USD) reporting
MONETARY_COLS = ["gdp_per_capita", "financial_risk_ratio"]


# ---------------------------------------------------------------------------
# Table 1: Descriptive statistics with CIs and USD
# ---------------------------------------------------------------------------

def generate_descriptive_table(
    db_path: Path,
    out_dir: Path,
) -> Path:
    """Generate Table 1: descriptive statistics with CIs and USD columns.

    Wraps reporting.generate_descriptive_table and adds USD columns for
    monetary variables using BCB exchange rate.

    Parameters
    ----------
    db_path : Path
        Path to SQLite database.
    out_dir : Path
        Root output directory (results/).

    Returns
    -------
    Path
        Path to saved CSV file.
    """
    from analysis.reporting import generate_descriptive_table as _gen_desc  # noqa: PLC0415
    from database.deflate_ipca import (  # noqa: PLC0415
        convert_brl_to_usd,
        fetch_bcb_exchange_rate,
    )

    db_path = Path(db_path)
    out_dir = Path(out_dir)
    tables_dir = out_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    # Generate base descriptive table
    base_csv = _gen_desc(db_path, out_dir)
    df = pd.read_csv(base_csv)

    # Add USD columns for monetary variables
    rate = fetch_bcb_exchange_rate(base_year=2023)

    brl_mean_cols = [
        c for c in df.columns
        if any(m in c for m in MONETARY_COLS) and "_mean" in c
    ]

    if brl_mean_cols:
        df = convert_brl_to_usd(df, brl_mean_cols, rate)
        logger.info(
            "generate_descriptive_table: added USD columns for %s",
            brl_mean_cols,
        )

    csv_path = tables_dir / "table1_descriptive_stats.csv"
    df.to_csv(csv_path, index=False)

    logger.info(
        "generate_descriptive_table: saved %d rows to %s", len(df), csv_path,
    )
    return csv_path


# ---------------------------------------------------------------------------
# Table 2: Dimension descriptives by region
# ---------------------------------------------------------------------------

def generate_dimension_descriptives(
    db_path: Path,
    out_dir: Path,
) -> Path:
    """Generate Table 2: CIMI dimension descriptives by region.

    Computes mean/SD/CI for each D1-D7, D9 and CUDS column grouped
    by region, with an Overall aggregate row.

    Parameters
    ----------
    db_path : Path
        Path to SQLite database.
    out_dir : Path
        Root output directory (results/).

    Returns
    -------
    Path
        Path to saved CSV file.
    """
    from analysis.reporting import add_ci_to_descriptives  # noqa: PLC0415

    db_path = Path(db_path)
    out_dir = Path(out_dir)
    tables_dir = out_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    try:
        dims = pd.read_sql("SELECT * FROM dimension_scores", conn)
        lookup = pd.read_sql(
            "SELECT cod_ibge, region FROM municipality_lookup", conn,
        )
    finally:
        conn.close()

    dims["cod_ibge"] = dims["cod_ibge"].astype(str)
    lookup["cod_ibge"] = lookup["cod_ibge"].astype(str)

    panel = dims.merge(lookup, on="cod_ibge", how="inner")

    value_cols = [c for c in DIM_COLS + [CUDS_COL] if c in panel.columns]

    # --- By region ---
    region_stats = add_ci_to_descriptives(panel, value_cols, ["region"])

    # --- Overall ---
    panel_overall = panel.copy()
    panel_overall["region"] = "Overall"
    overall_stats = add_ci_to_descriptives(
        panel_overall, value_cols, ["region"],
    )

    combined = pd.concat([region_stats, overall_stats], ignore_index=True)

    # Sort by region order
    order = REGION_ORDER + ["Overall"]
    combined["_sort"] = combined["region"].map(
        {r: i for i, r in enumerate(order)}
    ).fillna(99)
    combined = (
        combined
        .sort_values("_sort")
        .drop(columns="_sort")
        .reset_index(drop=True)
    )

    csv_path = tables_dir / "table2_dimension_descriptives.csv"
    combined.to_csv(csv_path, index=False)

    logger.info(
        "generate_dimension_descriptives: saved %d rows to %s",
        len(combined), csv_path,
    )
    return csv_path


# ---------------------------------------------------------------------------
# Table 3: Missingness (RECORD 12.1)
# ---------------------------------------------------------------------------

def generate_missingness_table(
    db_path: Path,
    out_dir: Path,
) -> Path:
    """Generate Table 3: missingness summary per variable per year.

    Loads municipal_health from SQLite, computes n_total, n_missing,
    and pct_missing for each source column, pivoted wide by year.

    Parameters
    ----------
    db_path : Path
        Path to SQLite database.
    out_dir : Path
        Root output directory (results/).

    Returns
    -------
    Path
        Path to saved CSV file.
    """
    db_path = Path(db_path)
    out_dir = Path(out_dir)
    tables_dir = out_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    try:
        mh = pd.read_sql("SELECT * FROM municipal_health", conn)
    finally:
        conn.close()

    if mh.empty:
        logger.warning("generate_missingness_table: municipal_health is empty")
        csv_path = tables_dir / "table3_missingness.csv"
        pd.DataFrame().to_csv(csv_path, index=False)
        return csv_path

    mh["year"] = mh["year"].astype(int)

    # Columns to check (exclude cod_ibge and year)
    skip = {"cod_ibge", "year"}
    value_cols = [c for c in mh.columns if c not in skip]

    rows = []
    for col in value_cols:
        for year in sorted(mh["year"].unique()):
            year_data = mh[mh["year"] == year]
            n_total = len(year_data)
            n_missing = int(year_data[col].isna().sum())
            pct_missing = round(n_missing / n_total * 100, 2) if n_total > 0 else 0.0
            rows.append({
                "variable": col,
                "year": year,
                "n_total": n_total,
                "n_missing": n_missing,
                "pct_missing": pct_missing,
            })

    long_df = pd.DataFrame(rows)

    # Pivot to wide: rows = variable, columns = years (pct_missing)
    wide_df = long_df.pivot_table(
        index="variable",
        columns="year",
        values="pct_missing",
        aggfunc="first",
    ).reset_index()

    # Add overall missingness
    overall = long_df.groupby("variable").agg(
        n_total_all=("n_total", "sum"),
        n_missing_all=("n_missing", "sum"),
    ).reset_index()
    overall["pct_missing_overall"] = (
        overall["n_missing_all"] / overall["n_total_all"] * 100
    ).round(2)

    wide_df = wide_df.merge(
        overall[["variable", "pct_missing_overall"]],
        on="variable",
        how="left",
    )

    csv_path = tables_dir / "table3_missingness.csv"
    wide_df.to_csv(csv_path, index=False)

    logger.info(
        "generate_missingness_table: %d variables x %d years saved to %s",
        len(value_cols), len(mh["year"].unique()), csv_path,
    )
    return csv_path


# ---------------------------------------------------------------------------
# Table 4: Correlation matrix
# ---------------------------------------------------------------------------

def generate_correlation_matrix(
    db_path: Path,
    out_dir: Path,
) -> Path:
    """Generate Table 4: Pearson correlation matrix (dimensions x LCoGS).

    Loads dimension_scores (D1-D7, D9, cuds) and lcogs_indicators (6 cols)
    from SQLite, merges on (cod_ibge, year), and computes Pearson r.

    Parameters
    ----------
    db_path : Path
        Path to SQLite database.
    out_dir : Path
        Root output directory (results/).

    Returns
    -------
    Path
        Path to saved CSV file.
    """
    db_path = Path(db_path)
    out_dir = Path(out_dir)
    tables_dir = out_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    try:
        dims = pd.read_sql("SELECT * FROM dimension_scores", conn)
        lcogs = pd.read_sql("SELECT * FROM lcogs_indicators", conn)
    finally:
        conn.close()

    dims["cod_ibge"] = dims["cod_ibge"].astype(str)
    dims["year"] = dims["year"].astype(int)
    lcogs["cod_ibge"] = lcogs["cod_ibge"].astype(str)
    lcogs["year"] = lcogs["year"].astype(int)

    panel = dims.merge(lcogs, on=["cod_ibge", "year"], how="inner")

    corr_cols = [c for c in DIM_COLS + [CUDS_COL] + LCOGS_COLS if c in panel.columns]
    corr_matrix = panel[corr_cols].corr(method="pearson")

    csv_path = tables_dir / "table4_correlation_matrix.csv"
    corr_matrix.to_csv(csv_path)

    logger.info(
        "generate_correlation_matrix: %dx%d matrix saved to %s",
        corr_matrix.shape[0], corr_matrix.shape[1], csv_path,
    )
    return csv_path


# ---------------------------------------------------------------------------
# Tables 5-8: Regression results
# ---------------------------------------------------------------------------

def _extract_cuds_row(res, outcome_col: str) -> dict:
    """Extract CUDS coefficient row from a PanelOLS result.

    Parameters
    ----------
    res : linearmodels PanelOLS result
        Fitted regression result.
    outcome_col : str
        Outcome column name for labeling.

    Returns
    -------
    dict
        Row with coefficient, SE, CI, p-value, R2, N.
    """
    if "cuds" not in res.params.index:
        return {}

    conf = res.conf_int()
    cuds_idx = list(res.params.index).index("cuds")

    return {
        "outcome": outcome_col,
        "coefficient": float(res.params["cuds"]),
        "std_error": float(res.std_errors["cuds"]),
        "ci_lower": float(conf.iloc[cuds_idx, 0]),
        "ci_upper": float(conf.iloc[cuds_idx, 1]),
        "p_value": float(res.pvalues["cuds"]),
        "r2_within": float(res.rsquared_within),
        "n_obs": int(res.nobs),
    }


def generate_regression_tables(
    db_path: Path,
    out_dir: Path,
) -> list[Path]:
    """Generate Tables 5-8: regression results.

    Groups 6 PanelOLS regressions into 3 pairs plus a combined summary:
      Table 5: LCoGS-1 + LCoGS-2 (access + workforce)
      Table 6: LCoGS-3 + LCoGS-4 (volume + mortality)
      Table 7: LCoGS-5 + LCoGS-6 (financial)
      Table 8: Combined summary (all 6)

    Parameters
    ----------
    db_path : Path
        Path to SQLite database.
    out_dir : Path
        Root output directory (results/).

    Returns
    -------
    list[Path]
        Paths to the 4 saved CSV files.
    """
    from analysis.run_regressions import (  # noqa: PLC0415
        LCOGS_OUTCOMES,
        load_regression_panel,
        run_panel_regressions,
    )

    db_path = Path(db_path)
    out_dir = Path(out_dir)
    tables_dir = out_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    panel = load_regression_panel(db_path)
    results = run_panel_regressions(panel)

    # Extract all coefficient rows
    all_rows = []
    for outcome_col, _label in LCOGS_OUTCOMES:
        if outcome_col in results:
            row = _extract_cuds_row(results[outcome_col], outcome_col)
            if row:
                all_rows.append(row)

    # Group into pairs
    pairs = [
        ("table5_regression_access_workforce", ["lcogs1_distance_km", "sao_per_100k"]),
        ("table6_regression_volume_mortality", ["surgical_volume_per_100k", "pomr"]),
        ("table7_regression_financial", ["financial_risk_ratio", "catastrophic_expenditure"]),
    ]

    paths = []

    for filename, outcome_cols in pairs:
        pair_rows = [r for r in all_rows if r["outcome"] in outcome_cols]
        if pair_rows:
            df = pd.DataFrame(pair_rows)
            csv_path = tables_dir / ("%s.csv" % filename)
            df.to_csv(csv_path, index=False)
            paths.append(csv_path)
            logger.info(
                "generate_regression_tables: %s saved (%d outcomes)",
                csv_path, len(pair_rows),
            )

    # Table 8: Combined summary
    if all_rows:
        combined_df = pd.DataFrame(all_rows)
        csv_path = tables_dir / "table8_regression_combined.csv"
        combined_df.to_csv(csv_path, index=False)
        paths.append(csv_path)
        logger.info(
            "generate_regression_tables: combined summary saved (%d outcomes)",
            len(all_rows),
        )

    return paths


# ---------------------------------------------------------------------------
# Sensitivity tables
# ---------------------------------------------------------------------------

def generate_sensitivity_tables(
    db_path: Path,
    out_dir: Path,
) -> list[Path]:
    """Generate sensitivity analysis tables.

    Runs run_sensitivity() and formats results as publication tables
    for PUBL-05 (arithmetic CUDS) and PUBL-06 (exclude missing dims).

    Parameters
    ----------
    db_path : Path
        Path to SQLite database.
    out_dir : Path
        Root output directory (results/).

    Returns
    -------
    list[Path]
        Paths to saved sensitivity CSV files.
    """
    from analysis.run_regressions import (  # noqa: PLC0415
        load_regression_panel,
        run_sensitivity,
    )

    db_path = Path(db_path)
    out_dir = Path(out_dir)
    tables_dir = out_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    panel = load_regression_panel(db_path)
    sens = run_sensitivity(panel)

    paths = []

    for key, filename in [
        ("arithmetic_cuds", "sensitivity_arithmetic_cuds.csv"),
        ("exclude_missing_dims", "sensitivity_exclude_missing.csv"),
    ]:
        reg_results = sens.get(key, {})
        if not reg_results:
            logger.warning(
                "generate_sensitivity_tables: no results for %s", key,
            )
            continue

        rows = []
        for outcome_col, res in reg_results.items():
            row = _extract_cuds_row(res, outcome_col)
            if row:
                rows.append(row)

        if rows:
            df = pd.DataFrame(rows)
            csv_path = tables_dir / filename
            df.to_csv(csv_path, index=False)
            paths.append(csv_path)
            logger.info(
                "generate_sensitivity_tables: %s saved (%d outcomes)",
                csv_path, len(rows),
            )

    return paths


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def generate_all_tables(
    db_path: Path,
    out_dir: Path,
) -> list[Path]:
    """Generate all publication-ready tables.

    Calls all 6 table generators and returns a flat list of output paths.

    Parameters
    ----------
    db_path : Path
        Path to SQLite database.
    out_dir : Path
        Root output directory (results/).

    Returns
    -------
    list[Path]
        Paths to all generated CSV files.
    """
    db_path = Path(db_path)
    out_dir = Path(out_dir)
    paths: list[Path] = []

    logger.info("=" * 60)
    logger.info("PUBLICATION TABLES")
    logger.info("=" * 60)

    # --- Table 1: Descriptive statistics ---
    logger.info("─" * 60)
    logger.info("Table 1: Descriptive statistics with CIs")
    logger.info("─" * 60)
    try:
        p = generate_descriptive_table(db_path, out_dir)
        paths.append(p)
        logger.info("  Table 1 saved: %s", p)
    except Exception as exc:  # noqa: BLE001
        logger.error("  Table 1 failed: %s", exc)

    # --- Table 2: Dimension descriptives ---
    logger.info("─" * 60)
    logger.info("Table 2: Dimension descriptives by region")
    logger.info("─" * 60)
    try:
        p = generate_dimension_descriptives(db_path, out_dir)
        paths.append(p)
        logger.info("  Table 2 saved: %s", p)
    except Exception as exc:  # noqa: BLE001
        logger.error("  Table 2 failed: %s", exc)

    # --- Table 3: Missingness ---
    logger.info("─" * 60)
    logger.info("Table 3: Missingness summary (RECORD 12.1)")
    logger.info("─" * 60)
    try:
        p = generate_missingness_table(db_path, out_dir)
        paths.append(p)
        logger.info("  Table 3 saved: %s", p)
    except Exception as exc:  # noqa: BLE001
        logger.error("  Table 3 failed: %s", exc)

    # --- Table 4: Correlation matrix ---
    logger.info("─" * 60)
    logger.info("Table 4: Correlation matrix")
    logger.info("─" * 60)
    try:
        p = generate_correlation_matrix(db_path, out_dir)
        paths.append(p)
        logger.info("  Table 4 saved: %s", p)
    except Exception as exc:  # noqa: BLE001
        logger.error("  Table 4 failed: %s", exc)

    # --- Tables 5-8: Regression results ---
    logger.info("─" * 60)
    logger.info("Tables 5-8: Regression results")
    logger.info("─" * 60)
    try:
        reg_paths = generate_regression_tables(db_path, out_dir)
        paths.extend(reg_paths)
        logger.info("  Tables 5-8: %d files saved", len(reg_paths))
    except Exception as exc:  # noqa: BLE001
        logger.error("  Tables 5-8 failed: %s", exc)

    # --- Sensitivity tables ---
    logger.info("─" * 60)
    logger.info("Sensitivity tables")
    logger.info("─" * 60)
    try:
        sens_paths = generate_sensitivity_tables(db_path, out_dir)
        paths.extend(sens_paths)
        logger.info("  Sensitivity: %d files saved", len(sens_paths))
    except Exception as exc:  # noqa: BLE001
        logger.error("  Sensitivity tables failed: %s", exc)

    logger.info("=" * 60)
    logger.info("PUBLICATION TABLES COMPLETE: %d files", len(paths))
    for p in paths:
        logger.info("  %s", p)
    logger.info("=" * 60)

    return paths


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Generate all publication-ready tables.

    Usage
    -----
        python analysis/publication_tables.py \\
            --db-path database/icskg_br.sqlite \\
            --out-dir results
    """
    parser = argparse.ArgumentParser(
        description="ICSKG-BR publication table generator",
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

    paths = generate_all_tables(db_path, out_dir)

    if not paths:
        logger.error("No tables were generated")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
