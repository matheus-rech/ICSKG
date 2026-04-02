"""
ICSKG-BR Machine Learning Models
==================================
Train Random Forest and XGBoost regressors predicting each of the 6 LCoGS
surgical outcomes from the 8 CIMI dimension scores, using 5-fold
cross-validation stratified by Brazilian macro-region (GroupKFold).
Generate SHAP beeswarm plots for dimension-level feature importance.

Models
------
  - RandomForestRegressor  (n_estimators=500, random_state=42)
  - XGBRegressor           (n_estimators=500, random_state=42)

Cross-validation
-----------------
  GroupKFold with n_splits=5 using macro-region as group prevents
  geographic leakage between train and test sets. Metrics computed
  per fold: RMSE, R-squared, MAE.

SHAP Interpretation
--------------------
  TreeExplainer applied to full-data retrained models for each
  model-outcome combination. Beeswarm plots saved at 300 DPI.

Outputs
-------
  results/ml_metrics.csv           -- fold-level CV metrics (60 rows)
  results/figures/shap/*.png       -- 12 beeswarm plots (2 models x 6 outcomes)

Usage
-----
    python analysis/ml_models.py \\
        --db-path database/icskg_br.sqlite \\
        --out-dir results/

Exports
-------
    load_ml_dataset(db_path) -> tuple[pd.DataFrame, dict, np.ndarray]
    build_region_cv(groups, n_folds) -> GroupKFold
    train_single_model(model_type, X_train, y_train) -> BaseEstimator
    cross_validate_model(model_type, X, y, groups, cv) -> list[dict]
    run_all_models(db_path, out_dir, n_folds) -> tuple[dict, pd.DataFrame]
    compute_and_save_shap(models_dict, X, feature_names, out_dir) -> None
    main(argv) -> int
"""

import argparse
import contextlib
import logging
import sqlite3
import sys
from math import sqrt
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupKFold
from xgboost import XGBRegressor

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FEATURES = ["D1", "D2", "D3", "D4", "D5", "D6", "D7", "D9"]

OUTCOMES = [
    "lcogs1_distance_km",
    "sao_per_100k",
    "surgical_volume_per_100k",
    "pomr",
    "financial_risk_ratio",
    "catastrophic_expenditure",
]

OUTCOME_LABELS = {
    "lcogs1_distance_km": "LCoGS-1: Distance to Bellwether (km)",
    "sao_per_100k": "LCoGS-2: SAO Workforce Density",
    "surgical_volume_per_100k": "LCoGS-3: Surgical Volume per 100k",
    "pomr": "LCoGS-4: Perioperative Mortality Rate",
    "financial_risk_ratio": "LCoGS-5: Financial Risk Ratio",
    "catastrophic_expenditure": "LCoGS-6: Catastrophic Expenditure",
}

FEATURE_LABELS = {
    "D1": "Governance",
    "D2": "Economy",
    "D3": "Human Capital",
    "D4": "Social Cohesion",
    "D5": "Environment",
    "D6": "Mobility",
    "D7": "Urban Planning",
    "D9": "Technology",
}

MODEL_LABELS = {
    "rf": "Random Forest",
    "xgb": "XGBoost",
}

RANDOM_STATE = 42
N_ESTIMATORS = 500
N_FOLDS = 5


# ---------------------------------------------------------------------------
# Data Loading
# ---------------------------------------------------------------------------

def load_ml_dataset(
    db_path: Path,
) -> tuple[pd.DataFrame, dict[str, pd.Series], np.ndarray]:
    """Load and join dimension_scores + lcogs_indicators + municipality_lookup.

    Parameters
    ----------
    db_path : Path
        Path to the ICSKG-BR SQLite database.

    Returns
    -------
    tuple[pd.DataFrame, dict[str, pd.Series], np.ndarray]
        X : DataFrame with FEATURES columns (complete cases only).
        y_dict : {outcome_name: pd.Series} aligned to X index.
        groups : np.ndarray of region strings aligned to X index.
    """
    db_path = Path(db_path)
    conn = sqlite3.connect(str(db_path))

    try:
        dims = pd.read_sql(
            "SELECT cod_ibge, year, %s FROM dimension_scores"
            % ", ".join(FEATURES),
            conn,
        )
        lcogs = pd.read_sql(
            "SELECT cod_ibge, year, %s FROM lcogs_indicators"
            % ", ".join(OUTCOMES),
            conn,
        )
        lookup = pd.read_sql(
            "SELECT cod_ibge, region FROM municipality_lookup",
            conn,
        )
    finally:
        conn.close()

    # Join dimension_scores with lcogs_indicators on (cod_ibge, year)
    merged = dims.merge(lcogs, on=["cod_ibge", "year"], how="inner")

    # Join with municipality_lookup on cod_ibge to get region
    merged = merged.merge(lookup, on="cod_ibge", how="inner")

    logger.info(
        "load_ml_dataset: %d rows after join (dims=%d, lcogs=%d, lookup=%d)",
        len(merged), len(dims), len(lcogs), len(lookup),
    )

    # Drop rows with any NaN in features (complete-case analysis for ML)
    before = len(merged)
    merged = merged.dropna(subset=FEATURES).reset_index(drop=True)
    after = len(merged)
    if before != after:
        logger.info(
            "load_ml_dataset: dropped %d rows with NaN features (%d -> %d)",
            before - after, before, after,
        )

    X = merged[FEATURES].copy()
    y_dict = {outcome: merged[outcome].copy() for outcome in OUTCOMES}
    groups = merged["region"].values

    # Log dataset shape and region distribution
    unique, counts = np.unique(groups, return_counts=True)
    region_dist = ", ".join(
        "%s=%d" % (r, c) for r, c in zip(unique, counts)
    )
    logger.info(
        "load_ml_dataset: X shape=%s, outcomes=%d, regions: %s",
        X.shape, len(y_dict), region_dist,
    )

    return X, y_dict, groups


# ---------------------------------------------------------------------------
# Cross-Validation
# ---------------------------------------------------------------------------

def build_region_cv(
    groups: np.ndarray,
    n_folds: int = N_FOLDS,
) -> GroupKFold:
    """Build a GroupKFold cross-validator stratified by macro-region.

    Uses GroupKFold with macro-region as group so municipalities from
    the same region are never split across train/test in a fold.

    Parameters
    ----------
    groups : np.ndarray
        Array of region strings (e.g. 'Norte', 'Sudeste').
    n_folds : int
        Number of CV folds (default 5).

    Returns
    -------
    GroupKFold
        Configured cross-validator.
    """
    n_unique = len(np.unique(groups))
    effective_folds = min(n_folds, n_unique)
    if effective_folds < n_folds:
        logger.warning(
            "build_region_cv: requested %d folds but only %d unique regions "
            "-- using %d folds",
            n_folds, n_unique, effective_folds,
        )

    cv = GroupKFold(n_splits=effective_folds)

    logger.info(
        "build_region_cv: GroupKFold with %d folds, %d unique regions",
        effective_folds, n_unique,
    )
    return cv


# ---------------------------------------------------------------------------
# Model Training
# ---------------------------------------------------------------------------

def train_single_model(
    model_type: str,
    X_train: pd.DataFrame,
    y_train: pd.Series,
    random_state: int = RANDOM_STATE,
) -> RandomForestRegressor | XGBRegressor:
    """Train a single model on the provided data.

    Parameters
    ----------
    model_type : str
        'rf' for RandomForestRegressor, 'xgb' for XGBRegressor.
    X_train : pd.DataFrame
        Feature matrix.
    y_train : pd.Series
        Target values.
    random_state : int
        Random seed for reproducibility.

    Returns
    -------
    BaseEstimator
        Fitted scikit-learn compatible model.
    """
    if model_type == "rf":
        model = RandomForestRegressor(
            n_estimators=N_ESTIMATORS,
            random_state=random_state,
            n_jobs=-1,
            max_depth=None,
        )
    elif model_type == "xgb":
        model = XGBRegressor(
            n_estimators=N_ESTIMATORS,
            random_state=random_state,
            learning_rate=0.1,
            max_depth=6,
            subsample=0.8,
            colsample_bytree=0.8,
            n_jobs=-1,
        )
    else:
        raise ValueError("Unknown model_type: %s (expected 'rf' or 'xgb')" % model_type)

    model.fit(X_train, y_train)
    return model


# ---------------------------------------------------------------------------
# Cross-Validation Evaluation
# ---------------------------------------------------------------------------

def cross_validate_model(
    model_type: str,
    X: pd.DataFrame,
    y: pd.Series,
    groups: np.ndarray,
    cv: GroupKFold,
) -> list[dict]:
    """Cross-validate a model and return per-fold metrics.

    Parameters
    ----------
    model_type : str
        'rf' or 'xgb'.
    X : pd.DataFrame
        Feature matrix.
    y : pd.Series
        Target values.
    groups : np.ndarray
        Region groups for GroupKFold splitting.
    cv : GroupKFold
        Cross-validator instance.

    Returns
    -------
    list[dict]
        List of dicts with keys: fold, rmse, r2, mae.
    """
    results = []

    for fold_idx, (train_idx, test_idx) in enumerate(cv.split(X, groups=groups)):
        X_train = X.iloc[train_idx]
        X_test = X.iloc[test_idx]
        y_train = y.iloc[train_idx]
        y_test = y.iloc[test_idx]

        # Drop rows where y is NaN in both train and test
        train_mask = y_train.notna()
        test_mask = y_test.notna()

        X_train = X_train.loc[train_mask]
        y_train = y_train.loc[train_mask]
        X_test = X_test.loc[test_mask]
        y_test = y_test.loc[test_mask]

        if len(X_train) == 0 or len(X_test) == 0:
            logger.warning(
                "cross_validate_model: fold %d skipped (empty after NaN drop)",
                fold_idx,
            )
            continue

        model = train_single_model(model_type, X_train, y_train)
        y_pred = model.predict(X_test)

        rmse = float(sqrt(mean_squared_error(y_test, y_pred)))
        r2 = float(r2_score(y_test, y_pred))
        mae = float(mean_absolute_error(y_test, y_pred))

        results.append({
            "fold": fold_idx,
            "rmse": rmse,
            "r2": r2,
            "mae": mae,
        })

    return results


# ---------------------------------------------------------------------------
# Fold-level CI computation
# ---------------------------------------------------------------------------

def _compute_fold_ci(
    fold_metrics: list[dict],
    metric_name: str,
) -> dict:
    """Compute mean +/- SD (95 % CI) for a metric across CV folds.

    Parameters
    ----------
    fold_metrics : list[dict]
        List of per-fold metric dicts (from cross_validate_model).
    metric_name : str
        Key to extract from each fold dict (e.g. 'rmse', 'r2', 'mae').

    Returns
    -------
    dict
        Keys: mean, sd, ci_lower, ci_upper.
    """
    from analysis.reporting import mean_ci  # noqa: PLC0415

    values = np.array([d[metric_name] for d in fold_metrics if metric_name in d])
    result = mean_ci(values)
    return {
        "mean": result["mean"],
        "sd": result["sd"],
        "ci_lower": result["ci_lower"],
        "ci_upper": result["ci_upper"],
    }


# ---------------------------------------------------------------------------
# Run All Models
# ---------------------------------------------------------------------------

def run_all_models(
    db_path: Path,
    out_dir: Path,
    n_folds: int = N_FOLDS,
) -> tuple[dict, pd.DataFrame]:
    """Train and evaluate RF + XGBoost for all 6 LCoGS outcomes.

    Parameters
    ----------
    db_path : Path
        Path to ICSKG-BR SQLite database.
    out_dir : Path
        Output directory for results (ml_metrics.csv saved here).
    n_folds : int
        Number of CV folds (default 5).

    Returns
    -------
    tuple[dict, pd.DataFrame]
        models_dict : {(model_type, outcome): fitted_model} trained on full data.
        metrics_df : DataFrame with columns: model, outcome, fold, rmse, r2, mae.
    """
    db_path = Path(db_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    X, y_dict, groups = load_ml_dataset(db_path)
    cv = build_region_cv(groups, n_folds=n_folds)

    all_metrics = []
    models_dict = {}
    model_types = ["rf", "xgb"]

    logger.info("=" * 60)
    logger.info("ML MODEL TRAINING")
    logger.info("=" * 60)
    logger.info(
        "Models: %s | Outcomes: %d | Folds: %d",
        ", ".join(model_types), len(OUTCOMES), n_folds,
    )
    logger.info(
        "Hyperparameters: n_estimators=%d, random_state=%d (fixed defaults, no grid search)",
        N_ESTIMATORS, RANDOM_STATE,
    )

    for model_type in model_types:
        for outcome in OUTCOMES:
            y = y_dict[outcome]

            # Cross-validate
            fold_results = cross_validate_model(
                model_type, X, y, groups, cv,
            )

            for fr in fold_results:
                all_metrics.append({
                    "model": model_type,
                    "outcome": outcome,
                    "fold": fr["fold"],
                    "rmse": fr["rmse"],
                    "r2": fr["r2"],
                    "mae": fr["mae"],
                })

            # Log summary for this model-outcome
            if fold_results:
                rmses = [r["rmse"] for r in fold_results]
                r2s = [r["r2"] for r in fold_results]
                logger.info(
                    "%s x %s: RMSE=%.4f +/- %.4f, R2=%.4f +/- %.4f",
                    MODEL_LABELS.get(model_type, model_type),
                    outcome,
                    np.mean(rmses), np.std(rmses),
                    np.mean(r2s), np.std(r2s),
                )

            # Retrain on full dataset for SHAP interpretation
            y_full = y.dropna()
            X_full = X.loc[y_full.index]
            model = train_single_model(model_type, X_full, y_full)
            models_dict[(model_type, outcome)] = model

    # Save metrics CSV
    metrics_df = pd.DataFrame(all_metrics)
    csv_path = out_dir / "ml_metrics.csv"
    metrics_df.to_csv(csv_path, index=False)
    logger.info("Metrics saved to %s (%d rows)", csv_path, len(metrics_df))

    # ---------------------------------------------------------------
    # Summary CSV: mean +/- SD (95 % CI) per (model, outcome, metric)
    # ---------------------------------------------------------------
    summary_rows = []
    for model_type in model_types:
        for outcome in OUTCOMES:
            fold_results = [
                m for m in all_metrics
                if m["model"] == model_type and m["outcome"] == outcome
            ]
            if not fold_results:
                continue
            for metric_name in ["rmse", "r2", "mae"]:
                ci = _compute_fold_ci(fold_results, metric_name)
                summary_rows.append({
                    "model": model_type,
                    "outcome": outcome,
                    "metric": metric_name,
                    "mean": ci["mean"],
                    "sd": ci["sd"],
                    "ci_lower": ci["ci_lower"],
                    "ci_upper": ci["ci_upper"],
                })

    if summary_rows:
        summary_df = pd.DataFrame(summary_rows)
        summary_path = out_dir / "ml_metrics_summary.csv"
        summary_df.to_csv(summary_path, index=False)
        logger.info(
            "ML metrics summary saved to %s (%d rows)",
            summary_path, len(summary_df),
        )

    return models_dict, metrics_df


# ---------------------------------------------------------------------------
# SHAP Computation and Visualization
# ---------------------------------------------------------------------------

def compute_and_save_shap(
    models_dict: dict,
    X: pd.DataFrame,
    feature_names: list[str],
    out_dir: Path,
) -> None:
    """Compute SHAP values and save beeswarm plots for all models.

    Parameters
    ----------
    models_dict : dict
        {(model_type, outcome): fitted_model} from run_all_models.
    X : pd.DataFrame
        Feature matrix (full dataset).
    feature_names : list[str]
        Human-readable feature names for plot labels.
    out_dir : Path
        Root output directory (plots saved to out_dir/figures/shap/).
    """
    import shap  # noqa: PLC0415

    out_dir = Path(out_dir)
    shap_dir = out_dir / "figures" / "shap"
    shap_dir.mkdir(parents=True, exist_ok=True)

    # Apply human-readable labels to feature columns
    X_labeled = X.copy()
    X_labeled.columns = feature_names

    # Subsample if dataset is large (>5000 rows)
    if len(X_labeled) > 5000:
        rng = np.random.RandomState(RANDOM_STATE)
        idx = rng.choice(len(X_labeled), size=5000, replace=False)
        X_shap = X_labeled.iloc[idx]
        logger.info("SHAP: subsampled to 5000 rows from %d", len(X_labeled))
    else:
        X_shap = X_labeled

    # Track top features per model-outcome for summary log
    top_features = {}

    for (model_type, outcome), model in models_dict.items():
        try:
            import matplotlib  # noqa: PLC0415
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt  # noqa: PLC0415

            explainer = shap.TreeExplainer(model)
            shap_values = explainer(X_shap)

            # Identify top feature by mean |SHAP|
            mean_abs_shap = np.abs(shap_values.values).mean(axis=0)
            top_idx = int(np.argmax(mean_abs_shap))
            top_feat = feature_names[top_idx]
            top_features[(model_type, outcome)] = top_feat

            # Determine style context
            try:
                _style_ctx = plt.style.context(["science", "no-latex"])
                # Verify it works by entering/exiting
                _style_ctx.__enter__()
                _style_ctx.__exit__(None, None, None)
                style_list = ["science", "no-latex"]
            except Exception:  # noqa: BLE001
                style_list = []  # SciencePlots not available

            # Generate beeswarm plot with SciencePlots context
            with plt.style.context(style_list) if style_list else contextlib.nullcontext():
                fig, ax = plt.subplots(figsize=(10, 6))
                plt.sca(ax)
                shap.plots.beeswarm(
                    shap_values,
                    show=False,
                    max_display=8,
                )

                model_label = MODEL_LABELS.get(model_type, model_type)
                outcome_label = OUTCOME_LABELS.get(outcome, outcome)
                ax.set_title(
                    "%s: %s" % (model_label, outcome_label),
                    fontsize=12,
                )

                filename = "%s_%s_shap.png" % (model_type, outcome)
                filepath = shap_dir / filename
                fig.savefig(
                    str(filepath),
                    dpi=300,
                    bbox_inches="tight",
                )
                plt.close(fig)

            logger.info(
                "SHAP: saved %s (%d samples)",
                filename, len(X_shap),
            )

        except Exception as exc:  # noqa: BLE001
            logger.error(
                "SHAP: failed for %s x %s: %s",
                model_type, outcome, exc,
            )

    # Summary: top feature per model-outcome
    logger.info("-" * 60)
    logger.info("SHAP Top Features Summary")
    logger.info("-" * 60)
    for (model_type, outcome), feat in top_features.items():
        logger.info(
            "  %s x %s -> %s",
            MODEL_LABELS.get(model_type, model_type),
            OUTCOME_LABELS.get(outcome, outcome),
            feat,
        )


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Train ML models with region-stratified CV and generate SHAP plots.

    Usage
    -----
        python analysis/ml_models.py \\
            --db-path database/icskg_br.sqlite \\
            --out-dir results/
    """
    parser = argparse.ArgumentParser(
        description="ICSKG-BR ML models: RF + XGBoost with SHAP",
    )
    parser.add_argument(
        "--db-path",
        default="database/icskg_br.sqlite",
        help="Path to SQLite database (default: database/icskg_br.sqlite)",
    )
    parser.add_argument(
        "--out-dir",
        default="results",
        help="Output directory for metrics CSV and SHAP plots (default: results/)",
    )
    parser.add_argument(
        "--n-folds",
        type=int,
        default=N_FOLDS,
        help="Number of CV folds (default: %d)" % N_FOLDS,
    )
    args = parser.parse_args(argv)

    db_path = Path(args.db_path)
    out_dir = Path(args.out_dir)

    if not db_path.exists():
        logger.error("Database not found: %s", db_path)
        return 1

    try:
        # Train and evaluate models
        models_dict, metrics_df = run_all_models(
            db_path, out_dir, n_folds=args.n_folds,
        )

        # Load dataset again for SHAP (with human-readable labels)
        X, _y_dict, _groups = load_ml_dataset(db_path)
        feature_names = [FEATURE_LABELS[f] for f in FEATURES]
        compute_and_save_shap(models_dict, X, feature_names, out_dir)

        logger.info("ML pipeline complete: %d models trained", len(models_dict))
        return 0

    except Exception as exc:  # noqa: BLE001
        logger.error("ML pipeline failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
