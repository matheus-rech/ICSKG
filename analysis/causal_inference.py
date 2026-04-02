"""
ICSKG-BR Causal Inference Engine (METH-01)
============================================
Estimates causal effects of CUDS on each LCoGS outcome using EconML's
Double Machine Learning (DML) and Causal Forest estimators. Provides
heterogeneous treatment effect (CATE) estimates by region and population
size.

Treatment Variable
-------------------
  CUDS (Composite Urban Development Score) -- continuous treatment.

Outcomes (6)
-------------
  1. lcogs1_distance_km       -- Bellwether Access (km)
  2. sao_per_100k             -- SAO Density per 100k
  3. surgical_volume_per_100k -- Surgical Volume per 100k
  4. pomr                     -- Perioperative Mortality
  5. financial_risk_ratio     -- Financial Risk Ratio
  6. catastrophic_expenditure -- Catastrophic Expenditure

Controls (W)
-------------
  Region (one-hot), population (log-transformed), year (demeaned).

Models
------
  - LinearDML: parametric estimation with Lasso nuisance models
  - CausalForestDML: non-parametric heterogeneous treatment effects

CATE Analysis
--------------
  - By macro-region (5 regions)
  - By population size tercile (small, medium, large)

Usage
-----
    python analysis/causal_inference.py \\
        --db-path database/icskg_br.sqlite \\
        --out-dir results

Exports
-------
    load_causal_panel(db_path) -> pd.DataFrame
    run_linear_dml(panel, outcome) -> dict
    run_causal_forest(panel, outcome) -> dict
    estimate_cate_by_group(panel, outcome, group_col) -> pd.DataFrame
    run_all_causal(db_path, out_dir) -> dict
    main(argv) -> int
"""

import argparse
import json
import logging
import sqlite3
import sys
from datetime import datetime, timezone
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

LCOGS_OUTCOMES = [
    ("lcogs1_distance_km",       "LCoGS-1: Bellwether Access (km)"),
    ("sao_per_100k",             "LCoGS-2: SAO Density per 100k"),
    ("surgical_volume_per_100k", "LCoGS-3: Surgical Volume per 100k"),
    ("pomr",                     "LCoGS-4: Perioperative Mortality"),
    ("financial_risk_ratio",     "LCoGS-5: Financial Risk Ratio"),
    ("catastrophic_expenditure", "LCoGS-6: Catastrophic Expenditure"),
]

DIM_COLS = ["D1", "D2", "D3", "D4", "D5", "D6", "D7", "D9"]

# Regions for CATE heterogeneity analysis
MACRO_REGIONS = ["Norte", "Nordeste", "Centro-Oeste", "Sudeste", "Sul"]

# Population tercile boundaries (computed at runtime)
POP_TERCILE_LABELS = ["small", "medium", "large"]

RANDOM_STATE = 42


# ---------------------------------------------------------------------------
# Data Loading
# ---------------------------------------------------------------------------

def load_causal_panel(db_path: Path) -> pd.DataFrame:
    """Load dimension_scores + lcogs_indicators + municipality_lookup for
    causal inference.

    Returns a flat DataFrame (no MultiIndex) with treatment (cuds),
    outcomes (6 LCoGS), controls (region dummies, log_pop, year_demeaned),
    and dimension features (D1..D7, D9).

    Parameters
    ----------
    db_path : Path
        Path to SQLite database.

    Returns
    -------
    pd.DataFrame
        Panel with columns: cod_ibge, year, cuds, 6 LCoGS outcomes,
        D1..D7, D9, region, populacao, log_pop, year_demeaned, and
        one-hot region dummies.
    """
    db_path = Path(db_path)
    conn = sqlite3.connect(str(db_path))

    try:
        dims = pd.read_sql("SELECT * FROM dimension_scores", conn)
        lcogs = pd.read_sql("SELECT * FROM lcogs_indicators", conn)
        lookup = pd.read_sql(
            "SELECT cod_ibge, region FROM municipality_lookup", conn,
        )
        # Try to get population from municipal_health
        pop = pd.read_sql(
            "SELECT cod_ibge, year, populacao FROM municipal_health", conn,
        )
    finally:
        conn.close()

    # Ensure consistent types
    for df in [dims, lcogs, lookup, pop]:
        if "cod_ibge" in df.columns:
            df["cod_ibge"] = df["cod_ibge"].astype(str)
        if "year" in df.columns:
            df["year"] = df["year"].astype(int)

    # Join all tables
    panel = dims.merge(lcogs, on=["cod_ibge", "year"], how="inner")
    panel = panel.merge(lookup, on="cod_ibge", how="inner")
    panel = panel.merge(pop, on=["cod_ibge", "year"], how="left")

    # Drop rows with NaN treatment variable
    n_before = len(panel)
    panel = panel.dropna(subset=["cuds"])
    n_dropped = n_before - len(panel)
    if n_dropped > 0:
        logger.info(
            "load_causal_panel: dropped %d rows with NaN cuds (%d remaining)",
            n_dropped, len(panel),
        )

    # Create control variables
    # Log-transformed population (guard against zero/NaN)
    if "populacao" in panel.columns:
        pop_clean = panel["populacao"].replace(0, np.nan)
        panel["log_pop"] = np.log(pop_clean)
    else:
        panel["log_pop"] = np.nan
        logger.warning("load_causal_panel: populacao column not found")

    # Year demeaned (center around mean year)
    mean_year = panel["year"].mean()
    panel["year_demeaned"] = panel["year"] - mean_year

    # One-hot encode region
    region_dummies = pd.get_dummies(
        panel["region"], prefix="region", dtype=float,
    )
    panel = pd.concat([panel, region_dummies], axis=1)

    logger.info(
        "load_causal_panel: %d observations, %d columns from %s",
        len(panel), len(panel.columns), db_path,
    )

    return panel


# ---------------------------------------------------------------------------
# Control variable helpers
# ---------------------------------------------------------------------------

def _get_control_columns(panel: pd.DataFrame) -> list[str]:
    """Extract control variable column names from the panel.

    Controls are: region dummies, log_pop, year_demeaned.

    Parameters
    ----------
    panel : pd.DataFrame
        Panel with one-hot region columns.

    Returns
    -------
    list[str]
        List of control column names.
    """
    region_cols = [c for c in panel.columns if c.startswith("region_")]
    controls = region_cols + ["log_pop", "year_demeaned"]
    # Filter to only columns that exist and have no all-NaN
    controls = [
        c for c in controls
        if c in panel.columns and panel[c].notna().any()
    ]
    return controls


def _prepare_arrays(
    panel: pd.DataFrame,
    outcome_col: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, pd.DataFrame]:
    """Prepare Y, T, X, W arrays for EconML estimators.

    Parameters
    ----------
    panel : pd.DataFrame
        Loaded causal panel.
    outcome_col : str
        Name of the outcome column.

    Returns
    -------
    tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, pd.DataFrame]
        Y : outcome array (n,)
        T : treatment array (n,)
        X : effect modifier features (n, p) -- dimensions D1..D9
        W : control/confounding variables (n, q) -- region, pop, year
        subset : the filtered panel subset (for CATE grouping)
    """
    control_cols = _get_control_columns(panel)

    # Feature columns for heterogeneity (X in EconML)
    feature_cols = [c for c in DIM_COLS if c in panel.columns]

    # Require non-NaN in treatment, outcome, and all features/controls
    required = ["cuds", outcome_col] + feature_cols + control_cols
    subset = panel.dropna(subset=required).copy()

    Y = subset[outcome_col].values.astype(float)
    T = subset["cuds"].values.astype(float)
    X = subset[feature_cols].values.astype(float)
    W = subset[control_cols].values.astype(float)

    return Y, T, X, W, subset


# ---------------------------------------------------------------------------
# Linear DML (parametric)
# ---------------------------------------------------------------------------

def run_linear_dml(
    panel: pd.DataFrame,
    outcome_col: str,
) -> dict:
    """Estimate ATE of CUDS on outcome using LinearDML.

    Uses Lasso for nuisance models (model_y, model_t) and fits a linear
    final model for the treatment effect. Reports ATE with 95% CI.

    Parameters
    ----------
    panel : pd.DataFrame
        Loaded causal panel.
    outcome_col : str
        Name of the LCoGS outcome column.

    Returns
    -------
    dict
        Keys: outcome, method, ate, ate_se, ate_ci_lower, ate_ci_upper,
        ate_pvalue, n_obs.
    """
    from econml.dml import LinearDML  # noqa: PLC0415
    from sklearn.linear_model import LassoCV  # noqa: PLC0415

    Y, T, X, W, subset = _prepare_arrays(panel, outcome_col)

    if len(Y) < 50:
        logger.warning(
            "run_linear_dml(%s): only %d observations -- skipping",
            outcome_col, len(Y),
        )
        return {
            "outcome": outcome_col,
            "method": "LinearDML",
            "ate": np.nan,
            "ate_se": np.nan,
            "ate_ci_lower": np.nan,
            "ate_ci_upper": np.nan,
            "ate_pvalue": np.nan,
            "n_obs": len(Y),
        }

    # LinearDML with LassoCV nuisance models
    est = LinearDML(
        model_y=LassoCV(cv=5, random_state=RANDOM_STATE),
        model_t=LassoCV(cv=5, random_state=RANDOM_STATE),
        random_state=RANDOM_STATE,
        cv=5,
        discrete_treatment=False,
    )

    est.fit(Y, T, X=X, W=W)

    # Average Treatment Effect
    ate_inference = est.ate_inference()
    ate = float(ate_inference.point_estimate)
    ate_se = float(ate_inference.stderr)
    ci = ate_inference.conf_int(alpha=0.05)
    ate_ci_lower = float(ci[0])
    ate_ci_upper = float(ci[1])
    ate_pvalue = float(ate_inference.pvalue)

    logger.info(
        "LinearDML(%s): ATE=%.6f (SE=%.6f), 95%% CI=[%.6f, %.6f], "
        "p=%.4f, n=%d",
        outcome_col, ate, ate_se, ate_ci_lower, ate_ci_upper,
        ate_pvalue, len(Y),
    )

    return {
        "outcome": outcome_col,
        "method": "LinearDML",
        "ate": ate,
        "ate_se": ate_se,
        "ate_ci_lower": ate_ci_lower,
        "ate_ci_upper": ate_ci_upper,
        "ate_pvalue": ate_pvalue,
        "n_obs": int(len(Y)),
    }


# ---------------------------------------------------------------------------
# Causal Forest DML (non-parametric)
# ---------------------------------------------------------------------------

def run_causal_forest(
    panel: pd.DataFrame,
    outcome_col: str,
) -> dict:
    """Estimate ATE of CUDS on outcome using CausalForestDML.

    Non-parametric estimation that also enables heterogeneous treatment
    effect analysis. Reports ATE with 95% CI.

    Parameters
    ----------
    panel : pd.DataFrame
        Loaded causal panel.
    outcome_col : str
        Name of the LCoGS outcome column.

    Returns
    -------
    dict
        Keys: outcome, method, ate, ate_se, ate_ci_lower, ate_ci_upper,
        ate_pvalue, n_obs.
    """
    from econml.dml import CausalForestDML  # noqa: PLC0415

    Y, T, X, W, subset = _prepare_arrays(panel, outcome_col)

    if len(Y) < 100:
        logger.warning(
            "run_causal_forest(%s): only %d observations -- skipping "
            "(need >= 100 for forest)",
            outcome_col, len(Y),
        )
        return {
            "outcome": outcome_col,
            "method": "CausalForestDML",
            "ate": np.nan,
            "ate_se": np.nan,
            "ate_ci_lower": np.nan,
            "ate_ci_upper": np.nan,
            "ate_pvalue": np.nan,
            "n_obs": len(Y),
        }

    # CausalForestDML with default nuisance models
    est = CausalForestDML(
        n_estimators=500,
        random_state=RANDOM_STATE,
        cv=5,
        discrete_treatment=False,
        min_samples_leaf=10,
    )

    est.fit(Y, T, X=X, W=W)

    # Average Treatment Effect
    ate_inference = est.ate_inference()
    ate = float(ate_inference.point_estimate)
    ate_se = float(ate_inference.stderr)
    ci = ate_inference.conf_int(alpha=0.05)
    ate_ci_lower = float(ci[0])
    ate_ci_upper = float(ci[1])
    ate_pvalue = float(ate_inference.pvalue)

    logger.info(
        "CausalForestDML(%s): ATE=%.6f (SE=%.6f), 95%% CI=[%.6f, %.6f], "
        "p=%.4f, n=%d",
        outcome_col, ate, ate_se, ate_ci_lower, ate_ci_upper,
        ate_pvalue, len(Y),
    )

    return {
        "outcome": outcome_col,
        "method": "CausalForestDML",
        "ate": ate,
        "ate_se": ate_se,
        "ate_ci_lower": ate_ci_lower,
        "ate_ci_upper": ate_ci_upper,
        "ate_pvalue": ate_pvalue,
        "n_obs": int(len(Y)),
    }


# ---------------------------------------------------------------------------
# CATE heterogeneity analysis
# ---------------------------------------------------------------------------

def estimate_cate_by_group(
    panel: pd.DataFrame,
    outcome_col: str,
    group_col: str,
) -> pd.DataFrame:
    """Estimate Conditional Average Treatment Effects by group.

    Fits a CausalForestDML and computes CATE for each subgroup defined
    by group_col. Reports mean CATE, SE, and 95% CI per group.

    Parameters
    ----------
    panel : pd.DataFrame
        Loaded causal panel.
    outcome_col : str
        Name of the LCoGS outcome column.
    group_col : str
        Column defining subgroups (e.g. 'region' or 'pop_tercile').

    Returns
    -------
    pd.DataFrame
        Columns: group, mean_cate, se_cate, ci_lower, ci_upper, n_obs.
    """
    from econml.dml import CausalForestDML  # noqa: PLC0415

    Y, T, X, W, subset = _prepare_arrays(panel, outcome_col)

    if len(Y) < 100:
        logger.warning(
            "estimate_cate_by_group(%s, %s): only %d obs -- skipping",
            outcome_col, group_col, len(Y),
        )
        return pd.DataFrame(
            columns=["group", "mean_cate", "se_cate",
                      "ci_lower", "ci_upper", "n_obs"]
        )

    est = CausalForestDML(
        n_estimators=500,
        random_state=RANDOM_STATE,
        cv=5,
        discrete_treatment=False,
        min_samples_leaf=10,
    )
    est.fit(Y, T, X=X, W=W)

    # Get individual-level CATE estimates
    cate_values = est.effect(X)
    cate_inference = est.effect_inference(X)
    cate_lower = cate_inference.conf_int(alpha=0.05)[0]
    cate_upper = cate_inference.conf_int(alpha=0.05)[1]

    # Assign back to subset for grouping
    subset = subset.copy()
    subset["cate"] = cate_values.flatten()
    subset["cate_ci_lower"] = cate_lower.flatten()
    subset["cate_ci_upper"] = cate_upper.flatten()

    # Group and summarize
    rows = []
    if group_col not in subset.columns:
        logger.warning(
            "estimate_cate_by_group: group_col '%s' not in panel",
            group_col,
        )
        return pd.DataFrame(
            columns=["group", "mean_cate", "se_cate",
                      "ci_lower", "ci_upper", "n_obs"]
        )

    for grp_name, grp_df in subset.groupby(group_col, observed=True):
        cates = grp_df["cate"].values
        n = len(cates)
        mean_cate = float(np.mean(cates))
        se_cate = float(np.std(cates, ddof=1) / np.sqrt(n)) if n > 1 else np.nan
        # Aggregate CI: use mean of individual CIs
        ci_lo = float(grp_df["cate_ci_lower"].mean())
        ci_hi = float(grp_df["cate_ci_upper"].mean())

        rows.append({
            "group": str(grp_name),
            "mean_cate": mean_cate,
            "se_cate": se_cate,
            "ci_lower": ci_lo,
            "ci_upper": ci_hi,
            "n_obs": n,
        })

    result = pd.DataFrame(rows)

    logger.info(
        "CATE by %s for %s: %d groups, range [%.6f, %.6f]",
        group_col, outcome_col, len(result),
        result["mean_cate"].min() if len(result) > 0 else np.nan,
        result["mean_cate"].max() if len(result) > 0 else np.nan,
    )

    return result


# ---------------------------------------------------------------------------
# Population tercile helper
# ---------------------------------------------------------------------------

def _add_pop_tercile(panel: pd.DataFrame) -> pd.DataFrame:
    """Add pop_tercile column based on population size.

    Parameters
    ----------
    panel : pd.DataFrame
        Panel with populacao column.

    Returns
    -------
    pd.DataFrame
        Panel with added pop_tercile column.
    """
    if "populacao" not in panel.columns or panel["populacao"].isna().all():
        logger.warning("_add_pop_tercile: no valid population data")
        panel["pop_tercile"] = np.nan
        return panel

    panel = panel.copy()
    panel["pop_tercile"] = pd.qcut(
        panel["populacao"],
        q=3,
        labels=POP_TERCILE_LABELS,
        duplicates="drop",
    )
    return panel


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_all_causal(
    db_path: Path,
    out_dir: Path,
) -> dict:
    """Run all causal inference analyses: LinearDML, CausalForestDML, CATE.

    Parameters
    ----------
    db_path : Path
        Path to ICSKG-BR SQLite database.
    out_dir : Path
        Output directory for results.

    Returns
    -------
    dict
        Keys: "dml_results", "forest_results", "cate_by_region",
        "cate_by_population".
    """
    db_path = Path(db_path)
    out_dir = Path(out_dir)
    causal_dir = out_dir / "causal"
    causal_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("CAUSAL INFERENCE ENGINE (METH-01)")
    logger.info("=" * 60)

    panel = load_causal_panel(db_path)
    panel = _add_pop_tercile(panel)

    # --- LinearDML ---
    logger.info("-" * 60)
    logger.info("STAGE: Linear DML (parametric ATE)")
    logger.info("-" * 60)

    dml_results = []
    for outcome_col, outcome_label in LCOGS_OUTCOMES:
        if outcome_col not in panel.columns:
            logger.warning("Skipping %s (not in panel)", outcome_col)
            continue
        try:
            result = run_linear_dml(panel, outcome_col)
            dml_results.append(result)
        except Exception as exc:  # noqa: BLE001
            logger.error("LinearDML(%s) failed: %s", outcome_col, exc)
            dml_results.append({
                "outcome": outcome_col,
                "method": "LinearDML",
                "ate": np.nan,
                "ate_se": np.nan,
                "ate_ci_lower": np.nan,
                "ate_ci_upper": np.nan,
                "ate_pvalue": np.nan,
                "n_obs": 0,
                "error": str(exc),
            })

    dml_df = pd.DataFrame(dml_results)
    dml_df.to_csv(causal_dir / "linear_dml_results.csv", index=False)
    logger.info("LinearDML results saved: %d outcomes", len(dml_df))

    # --- Causal Forest DML ---
    logger.info("-" * 60)
    logger.info("STAGE: Causal Forest DML (non-parametric ATE)")
    logger.info("-" * 60)

    forest_results = []
    for outcome_col, outcome_label in LCOGS_OUTCOMES:
        if outcome_col not in panel.columns:
            logger.warning("Skipping %s (not in panel)", outcome_col)
            continue
        try:
            result = run_causal_forest(panel, outcome_col)
            forest_results.append(result)
        except Exception as exc:  # noqa: BLE001
            logger.error("CausalForestDML(%s) failed: %s", outcome_col, exc)
            forest_results.append({
                "outcome": outcome_col,
                "method": "CausalForestDML",
                "ate": np.nan,
                "ate_se": np.nan,
                "ate_ci_lower": np.nan,
                "ate_ci_upper": np.nan,
                "ate_pvalue": np.nan,
                "n_obs": 0,
                "error": str(exc),
            })

    forest_df = pd.DataFrame(forest_results)
    forest_df.to_csv(causal_dir / "causal_forest_results.csv", index=False)
    logger.info("CausalForestDML results saved: %d outcomes", len(forest_df))

    # --- Combined ATE summary ---
    combined_df = pd.concat([dml_df, forest_df], ignore_index=True)
    combined_df.to_csv(causal_dir / "ate_summary.csv", index=False)
    logger.info("Combined ATE summary saved: %d rows", len(combined_df))

    # --- CATE by region ---
    logger.info("-" * 60)
    logger.info("STAGE: CATE heterogeneity by region")
    logger.info("-" * 60)

    cate_region_frames = []
    for outcome_col, outcome_label in LCOGS_OUTCOMES:
        if outcome_col not in panel.columns:
            continue
        try:
            cate_df = estimate_cate_by_group(panel, outcome_col, "region")
            cate_df["outcome"] = outcome_col
            cate_region_frames.append(cate_df)
        except Exception as exc:  # noqa: BLE001
            logger.error("CATE region(%s) failed: %s", outcome_col, exc)

    if cate_region_frames:
        cate_region = pd.concat(cate_region_frames, ignore_index=True)
        cate_region.to_csv(causal_dir / "cate_by_region.csv", index=False)
        logger.info("CATE by region saved: %d rows", len(cate_region))
    else:
        cate_region = pd.DataFrame()

    # --- CATE by population size ---
    logger.info("-" * 60)
    logger.info("STAGE: CATE heterogeneity by population size")
    logger.info("-" * 60)

    cate_pop_frames = []
    for outcome_col, outcome_label in LCOGS_OUTCOMES:
        if outcome_col not in panel.columns:
            continue
        try:
            cate_df = estimate_cate_by_group(panel, outcome_col, "pop_tercile")
            cate_df["outcome"] = outcome_col
            cate_pop_frames.append(cate_df)
        except Exception as exc:  # noqa: BLE001
            logger.error("CATE pop_tercile(%s) failed: %s", outcome_col, exc)

    if cate_pop_frames:
        cate_pop = pd.concat(cate_pop_frames, ignore_index=True)
        cate_pop.to_csv(causal_dir / "cate_by_population.csv", index=False)
        logger.info("CATE by population saved: %d rows", len(cate_pop))
    else:
        cate_pop = pd.DataFrame()

    # --- Save computation log ---
    log_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "method_01": "LinearDML (LassoCV nuisance, 5-fold CV)",
        "method_02": "CausalForestDML (500 trees, min_samples_leaf=10)",
        "treatment": "cuds",
        "outcomes": [o[0] for o in LCOGS_OUTCOMES],
        "controls": ["region (one-hot)", "log_pop", "year_demeaned"],
        "effect_modifiers": DIM_COLS,
        "cate_groups": ["region (5 macro-regions)", "pop_tercile (3 groups)"],
        "n_observations": int(len(panel)),
        "dml_outcomes_completed": int(len(dml_df)),
        "forest_outcomes_completed": int(len(forest_df)),
    }

    log_path = causal_dir / "causal_inference_log.json"
    with open(log_path, "w") as f:
        json.dump(log_data, f, indent=2, default=str)
    logger.info("Computation log saved to %s", log_path)

    return {
        "dml_results": dml_results,
        "forest_results": forest_results,
        "cate_by_region": cate_region,
        "cate_by_population": cate_pop,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Run all causal inference analyses.

    Usage
    -----
        python analysis/causal_inference.py \\
            --db-path database/icskg_br.sqlite \\
            --out-dir results
    """
    parser = argparse.ArgumentParser(
        description="ICSKG-BR causal inference engine (EconML DML + Causal Forest)",
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

    if not db_path.exists():
        logger.error("Database not found: %s", db_path)
        return 1

    try:
        run_all_causal(db_path, out_dir)
        logger.info("Causal inference engine complete")
        return 0
    except Exception as exc:  # noqa: BLE001
        logger.error("Causal inference engine failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
