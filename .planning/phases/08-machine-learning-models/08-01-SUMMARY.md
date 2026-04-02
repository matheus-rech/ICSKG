---
phase: 08-machine-learning-models
plan: 01
subsystem: analysis
tags: [random-forest, xgboost, shap, scikit-learn, groupkfold, ml, cross-validation]

# Dependency graph
requires:
  - phase: 05-dimension-computation-cuds
    provides: dimension_scores table with D1-D7, D9 normalized scores
  - phase: 06-lcogs-indicators
    provides: lcogs_indicators table with 6 LCoGS outcomes
provides:
  - RF + XGBoost models for 6 LCoGS outcomes with region-stratified CV
  - SHAP beeswarm plots showing dimension-level feature importance
  - ml_metrics.csv with fold-level RMSE, R2, MAE for all model-outcome combinations
affects: [09-results-reporting, 10-publication-prep]

# Tech tracking
tech-stack:
  added: [shap>=0.46, numba>=0.60, llvmlite>=0.43]
  patterns: [GroupKFold region stratification, TreeExplainer for SHAP, full-data retrain for interpretation]

key-files:
  created:
    - analysis/ml_models.py
    - tests/test_ml_models.py
  modified:
    - pyproject.toml
    - uv.lock

key-decisions:
  - "GroupKFold with macro-region as group prevents geographic leakage between CV folds"
  - "Fixed hyperparameters (n_estimators=500, random_state=42) -- no grid search, documented as defaults"
  - "Full-data retrain for SHAP interpretation (standard practice: CV for evaluation, full-data for explanation)"
  - "numba>=0.60 and llvmlite>=0.43 added explicitly to force Python 3.12-compatible versions"
  - "SciencePlots styling via context manager with graceful fallback"

patterns-established:
  - "ML model module pattern: constants, load_dataset, build_cv, train_model, cross_validate, run_all, shap, main"
  - "SHAP beeswarm with human-readable dimension labels and 300 DPI PNG output"

requirements-completed: [MLMD-01, MLMD-02, MLMD-03, MLMD-04]

# Metrics
duration: 8min
completed: 2026-04-02
---

# Phase 8 Plan 1: ML Models Summary

**RF + XGBoost dose-response models for 6 LCoGS outcomes with region-stratified GroupKFold CV and SHAP beeswarm feature importance plots**

## Performance

- **Duration:** 8 min
- **Started:** 2026-04-02T04:15:11Z
- **Completed:** 2026-04-02T04:23:14Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Random Forest and XGBoost trained for all 6 LCoGS outcomes (12 models total) with reproducible seeds
- 5-fold GroupKFold cross-validation stratified by Brazilian macro-region prevents geographic leakage
- SHAP beeswarm plots generated for all 12 model-outcome combinations at 300 DPI with human-readable dimension labels
- ml_metrics.csv persists fold-level RMSE, R2, MAE (60 rows for 5-fold production; 24 rows in test with 2 folds)

## Task Commits

Each task was committed atomically:

1. **Task 1: Train RF + XGBoost with region-stratified CV** (TDD)
   - `76e855a` (test): add failing tests for ML model training and CV
   - `da550e5` (feat): implement RF + XGBoost training with region-stratified CV
2. **Task 2: SHAP beeswarm plots for all LCoGS outcomes** - `766d0d6` (feat)

## Files Created/Modified
- `analysis/ml_models.py` - ML training module: load_ml_dataset, build_region_cv, train_single_model, cross_validate_model, run_all_models, compute_and_save_shap, main CLI
- `tests/test_ml_models.py` - 9 tests covering dataset loading, NaN handling, GroupKFold, RF/XGB training, CV metrics, CSV format
- `pyproject.toml` - Added shap>=0.46,<1.0, numba>=0.60, llvmlite>=0.43
- `uv.lock` - Regenerated with shap + numba + llvmlite dependencies

## Decisions Made
- GroupKFold with macro-region as group (not StratifiedKFold) -- ensures no municipality from the same region appears in both train and test within a fold
- Fixed hyperparameters without grid search: RF (n_estimators=500, max_depth=None), XGBoost (n_estimators=500, learning_rate=0.1, max_depth=6, subsample=0.8, colsample_bytree=0.8) -- documented as reasonable defaults per CONTEXT.md
- Full-data retrain for SHAP explanation (CV is for evaluation, full-data model is for interpretation)
- numba>=0.60 and llvmlite>=0.43 explicitly pinned because the uv resolver was selecting Python 3.12-incompatible versions (numba 0.53.1, llvmlite 0.36.0) without explicit lower bounds

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] numba/llvmlite version resolution failure**
- **Found during:** Task 1 (dependency installation)
- **Issue:** uv resolver selected numba 0.53.1 and llvmlite 0.36.0 which only support Python <3.10, causing build failure on Python 3.12
- **Fix:** Added explicit lower bounds numba>=0.60 and llvmlite>=0.43 to pyproject.toml forcing Python 3.12-compatible versions
- **Files modified:** pyproject.toml
- **Verification:** uv sync succeeded, shap 0.51.0 + numba 0.65.0 + llvmlite 0.47.0 installed
- **Committed in:** da550e5 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Essential fix for dependency resolution. No scope creep.

## Issues Encountered
None beyond the dependency resolution issue documented above.

## Known Stubs
None -- all functions are fully implemented with real data sources (SQLite queries) and real model training.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- ML models and SHAP plots ready for Phase 9 (results reporting) and Phase 10 (publication prep)
- ml_metrics.csv provides all fold-level metrics for results tables
- SHAP beeswarm PNGs at 300 DPI ready for manuscript figures
- Full-data trained models in models_dict available for additional analysis

## Self-Check: PASSED

- All 4 files exist (analysis/ml_models.py, tests/test_ml_models.py, pyproject.toml, uv.lock)
- All 3 commits found (76e855a, da550e5, 766d0d6)
- shap>=0.46,<1.0 present in pyproject.toml
- 9 tests collected and passing

---
*Phase: 08-machine-learning-models*
*Completed: 2026-04-02*
