# Phase 8: Machine Learning Models - Context

**Gathered:** 2026-04-02
**Status:** Ready for planning
**Mode:** Auto-generated (autonomous workflow)

<domain>
## Phase Boundary

Random Forest and XGBoost dose-response models trained on CIMI dimensions predicting LCoGS outcomes, with region-stratified 5-fold cross-validation and SHAP feature importance. Complements the statistical analysis with non-parametric approaches.

</domain>

<decisions>
## Implementation Decisions

### Models
- Random Forest and XGBoost for each of the 6 LCoGS outcomes (12 models total)
- Hyperparameters logged and random seeds fixed for reproducibility
- Features: 8 CIMI dimension scores (D1-D7, D9-D10)

### Cross-Validation
- 5-fold stratified by 5 Brazilian macro-regions (Norte, Nordeste, Centro-Oeste, Sudeste, Sul)
- Prevents geographic leakage between train and test sets
- Metrics: RMSE, R², MAE per fold

### SHAP
- Beeswarm plots for each LCoGS outcome showing dimension-level feature importance
- 300 DPI PNG files saved to results/figures/shap/

### Output
- results/ml_metrics.csv with all CV fold metrics
- results/figures/shap/ with beeswarm plots

### Claude's Discretion
- Hyperparameter tuning strategy (grid search vs reasonable defaults)
- scikit-learn vs xgboost native API
- SHAP TreeExplainer for both models
- Whether to include CUDS as an additional feature or only raw dimensions

</decisions>

<code_context>
## Existing Code Insights

- scikit-learn and xgboost already pinned in pyproject.toml
- analysis/compute_dimensions.py provides dimension scores
- analysis/compute_lcogs.py provides LCoGS indicators
- SciencePlots pinned for publication-quality matplotlib styling

</code_context>

<specifics>
## Specific Ideas

- Use macro-region codes: 1=Norte, 2=Nordeste, 3=Sudeste, 4=Sul, 5=Centro-Oeste
- Derive region from first digit of UF code in IBGE municipality reference

</specifics>

<deferred>
## Deferred Ideas

None — all MLMD requirements in scope.

</deferred>
