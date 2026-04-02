"""
Tests for analysis.ml_models — Random Forest + XGBoost training with
region-stratified GroupKFold cross-validation and SHAP computation.
"""

import sqlite3
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def ml_db(tmp_path: Path) -> Path:
    """Create a minimal SQLite database with dimension_scores,
    lcogs_indicators, and municipality_lookup tables.

    4 municipalities in 2 regions x 5 years = 20 rows.
    """
    db_path = tmp_path / "test_ml.sqlite"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    # Create tables
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS dimension_scores (
            cod_ibge       TEXT    NOT NULL,
            year           INTEGER NOT NULL,
            D1             REAL,
            D2             REAL,
            D3             REAL,
            D4             REAL,
            D5             REAL,
            D6             REAL,
            D7             REAL,
            D9             REAL,
            cuds           REAL,
            n_dimensions   INTEGER,
            PRIMARY KEY (cod_ibge, year)
        );

        CREATE TABLE IF NOT EXISTS lcogs_indicators (
            cod_ibge                 TEXT    NOT NULL,
            year                     INTEGER NOT NULL,
            lcogs1_distance_km       REAL,
            sao_per_100k             REAL,
            surgical_volume_per_100k REAL,
            pomr                     REAL,
            financial_risk_ratio     REAL,
            catastrophic_expenditure REAL,
            PRIMARY KEY (cod_ibge, year)
        );

        CREATE TABLE IF NOT EXISTS municipality_lookup (
            cod_ibge   TEXT PRIMARY KEY,
            name       TEXT,
            state_uf   TEXT,
            region     TEXT,
            population INTEGER
        );
    """)

    # 4 municipalities: 2 in Sudeste, 2 in Nordeste
    municipalities = [
        ("3550308", "Sao Paulo", "SP", "Sudeste", 12300000),
        ("3304557", "Rio de Janeiro", "RJ", "Sudeste", 6700000),
        ("2927408", "Salvador", "BA", "Nordeste", 2900000),
        ("2611606", "Recife", "PE", "Nordeste", 1600000),
    ]
    cur.executemany(
        "INSERT INTO municipality_lookup VALUES (?, ?, ?, ?, ?)",
        municipalities,
    )

    rng = np.random.RandomState(42)
    years = list(range(2015, 2020))  # 5 years

    dim_rows = []
    lcogs_rows = []
    for cod, _name, _uf, _region, _pop in municipalities:
        for year in years:
            d_vals = rng.uniform(0.1, 0.9, size=8).tolist()
            cuds = float(np.exp(np.log(np.array(d_vals) + 0.01).mean()) - 0.01)
            dim_rows.append(
                (cod, year, *d_vals, cuds, 8),
            )
            lcogs_rows.append((
                cod, year,
                rng.uniform(10, 500),      # lcogs1_distance_km
                rng.uniform(5, 50),         # sao_per_100k
                rng.uniform(100, 5000),     # surgical_volume_per_100k
                rng.uniform(0.001, 0.05),   # pomr
                rng.uniform(0.01, 0.3),     # financial_risk_ratio
                rng.uniform(0.0, 1.0),      # catastrophic_expenditure
            ))

    cur.executemany(
        "INSERT INTO dimension_scores VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        dim_rows,
    )
    cur.executemany(
        "INSERT INTO lcogs_indicators VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        lcogs_rows,
    )

    conn.commit()
    conn.close()
    return db_path


# ---------------------------------------------------------------------------
# Test 1: load_ml_dataset joins correctly
# ---------------------------------------------------------------------------

class TestLoadMLDataset:
    """Tests for load_ml_dataset()."""

    def test_returns_correct_shapes(self, ml_db: Path) -> None:
        """load_ml_dataset joins dimension_scores + lcogs_indicators +
        municipality_lookup and returns (X, y_dict, groups) with correct
        shapes: X has 8 columns, y_dict has 6 outcomes, groups is region.
        """
        from analysis.ml_models import load_ml_dataset

        X, y_dict, groups = load_ml_dataset(ml_db)

        # 4 municipalities x 5 years = 20 rows
        assert X.shape == (20, 8), "X should have 20 rows and 8 feature columns"
        assert len(y_dict) == 6, "y_dict should have 6 LCoGS outcomes"
        assert len(groups) == 20, "groups should have 20 entries"

        # Feature columns match FEATURES constant
        from analysis.ml_models import FEATURES
        assert list(X.columns) == FEATURES

    def test_groups_are_regions(self, ml_db: Path) -> None:
        """groups array contains macro-region names from municipality_lookup."""
        from analysis.ml_models import load_ml_dataset

        _X, _y_dict, groups = load_ml_dataset(ml_db)
        unique_regions = set(groups)
        assert unique_regions == {"Sudeste", "Nordeste"}


# ---------------------------------------------------------------------------
# Test 2: NaN feature rows dropped
# ---------------------------------------------------------------------------

class TestNaNDrop:
    """Tests that rows with NaN features are dropped."""

    def test_nan_features_dropped(self, ml_db: Path) -> None:
        """Rows with any NaN in features (D1-D7, D9) are dropped."""
        from analysis.ml_models import load_ml_dataset

        # Insert a row with NaN in D1
        conn = sqlite3.connect(str(ml_db))
        conn.execute(
            "INSERT OR REPLACE INTO dimension_scores VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("9999999", 2015, None, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.4, 7),
        )
        conn.execute(
            "INSERT OR REPLACE INTO lcogs_indicators VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?)",
            ("9999999", 2015, 100.0, 20.0, 500.0, 0.01, 0.1, 0.5),
        )
        conn.execute(
            "INSERT OR REPLACE INTO municipality_lookup VALUES "
            "(?, ?, ?, ?, ?)",
            ("9999999", "Test", "XX", "Norte", 10000),
        )
        conn.commit()
        conn.close()

        X, _y_dict, _groups = load_ml_dataset(ml_db)

        # The NaN row should be dropped -- original 20 rows remain
        assert len(X) == 20, "NaN feature rows should be dropped"
        assert not X.isna().any().any(), "No NaN values in features"


# ---------------------------------------------------------------------------
# Test 3: build_region_cv
# ---------------------------------------------------------------------------

class TestBuildRegionCV:
    """Tests for build_region_cv()."""

    def test_produces_correct_fold_count(self, ml_db: Path) -> None:
        """build_region_cv returns a GroupKFold with n_splits folds."""
        from analysis.ml_models import build_region_cv, load_ml_dataset

        X, _y_dict, groups = load_ml_dataset(ml_db)
        cv = build_region_cv(groups, n_folds=2)

        # With 2 regions, GroupKFold(n_splits=2) produces 2 folds
        folds = list(cv.split(X, groups=groups))
        assert len(folds) == 2, "Should produce 2 folds for 2 regions"

    def test_no_region_leakage(self, ml_db: Path) -> None:
        """No region appears in both train and test of the same fold."""
        from analysis.ml_models import build_region_cv, load_ml_dataset

        X, _y_dict, groups = load_ml_dataset(ml_db)
        cv = build_region_cv(groups, n_folds=2)

        for train_idx, test_idx in cv.split(X, groups=groups):
            train_regions = set(groups[train_idx])
            test_regions = set(groups[test_idx])
            overlap = train_regions & test_regions
            assert len(overlap) == 0, (
                "Region leakage: %s in both train and test" % overlap
            )


# ---------------------------------------------------------------------------
# Test 4: train_single_model with RF
# ---------------------------------------------------------------------------

class TestTrainSingleModel:
    """Tests for train_single_model()."""

    def test_rf_returns_fitted_estimator(self) -> None:
        """train_single_model('rf') returns a fitted RandomForestRegressor."""
        from analysis.ml_models import train_single_model

        rng = np.random.RandomState(42)
        X_train = pd.DataFrame(rng.rand(50, 8), columns=[
            "D1", "D2", "D3", "D4", "D5", "D6", "D7", "D9",
        ])
        y_train = pd.Series(rng.rand(50))

        model = train_single_model("rf", X_train, y_train)

        from sklearn.ensemble import RandomForestRegressor
        assert isinstance(model, RandomForestRegressor)
        # Check it's fitted (has estimators_)
        assert hasattr(model, "estimators_")
        assert model.random_state == 42
        assert model.n_estimators == 500

    # -------------------------------------------------------------------
    # Test 5: train_single_model with XGBoost
    # -------------------------------------------------------------------

    def test_xgb_returns_fitted_estimator(self) -> None:
        """train_single_model('xgb') returns a fitted XGBRegressor."""
        from analysis.ml_models import train_single_model

        rng = np.random.RandomState(42)
        X_train = pd.DataFrame(rng.rand(50, 8), columns=[
            "D1", "D2", "D3", "D4", "D5", "D6", "D7", "D9",
        ])
        y_train = pd.Series(rng.rand(50))

        model = train_single_model("xgb", X_train, y_train)

        from xgboost import XGBRegressor
        assert isinstance(model, XGBRegressor)
        assert model.random_state == 42
        assert model.n_estimators == 500


# ---------------------------------------------------------------------------
# Test 6: cross_validate_model
# ---------------------------------------------------------------------------

class TestCrossValidateModel:
    """Tests for cross_validate_model()."""

    def test_returns_fold_metrics(self, ml_db: Path) -> None:
        """cross_validate_model returns a list of dicts with fold metrics."""
        from analysis.ml_models import (
            build_region_cv,
            cross_validate_model,
            load_ml_dataset,
        )

        X, y_dict, groups = load_ml_dataset(ml_db)
        cv = build_region_cv(groups, n_folds=2)

        # Pick one outcome
        outcome = list(y_dict.keys())[0]
        results = cross_validate_model("rf", X, y_dict[outcome], groups, cv)

        assert len(results) == 2, "Should have 2 fold results"
        for fold_result in results:
            assert "fold" in fold_result
            assert "rmse" in fold_result
            assert "r2" in fold_result
            assert "mae" in fold_result
            assert isinstance(fold_result["rmse"], float)
            assert isinstance(fold_result["r2"], float)
            assert isinstance(fold_result["mae"], float)
            assert fold_result["rmse"] >= 0, "RMSE must be non-negative"
            assert fold_result["mae"] >= 0, "MAE must be non-negative"


# ---------------------------------------------------------------------------
# Test 7: Metrics CSV format
# ---------------------------------------------------------------------------

class TestMetricsCSV:
    """Tests for run_all_models() CSV output."""

    def test_metrics_csv_format(self, ml_db: Path, tmp_path: Path) -> None:
        """Metrics CSV has columns: model, outcome, fold, rmse, r2, mae."""
        from analysis.ml_models import run_all_models

        # Use 2 folds for speed (2 regions in test data)
        models_dict, metrics_df = run_all_models(ml_db, tmp_path, n_folds=2)

        csv_path = tmp_path / "ml_metrics.csv"
        assert csv_path.exists(), "ml_metrics.csv should be created"

        df = pd.read_csv(csv_path)
        expected_cols = {"model", "outcome", "fold", "rmse", "r2", "mae"}
        assert set(df.columns) == expected_cols, (
            "CSV columns should be %s, got %s" % (expected_cols, set(df.columns))
        )

        # 2 models x 6 outcomes x 2 folds = 24 rows (not 60 -- 2 folds)
        assert len(df) == 24, "Should have 24 rows (2 models x 6 outcomes x 2 folds)"

        # Check model types present
        assert set(df["model"].unique()) == {"rf", "xgb"}

        # Check all 6 outcomes present
        from analysis.ml_models import OUTCOMES
        assert set(df["outcome"].unique()) == set(OUTCOMES)
