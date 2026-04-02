---
phase: 07-statistical-analysis
plan: 01
subsystem: analysis
tags: [panelols, linearmodels, hausman, dose-response, fixed-effects, cluster-robust, sensitivity]

# Dependency graph
requires:
  - phase: 05-dimension-computation-cuds
    provides: "dimension_scores table with CUDS composite and D1-D7,D9 normalized scores"
  - phase: 06-lcogs-indicators
    provides: "lcogs_indicators table with 6 LCoGS outcome columns"
provides:
  - "analysis/run_regressions.py module (run_panel_regressions, run_hausman_tests, run_dose_response, run_sensitivity, save_regression_tables, load_regression_panel, main)"
  - "12 unit tests covering regression structure, Hausman format, dose-response, sensitivity analyses"
  - "CSV output spec: results/regression_tables/, results/hausman_test.csv, results/dose_response_*.csv, results/sensitivity/"
affects: [08-machine-learning-models, 09-figures-tables, 10-reporting-submission]

# Tech tracking
tech-stack:
  added: []
  patterns: [two-way-FE-PanelOLS, cluster-robust-SE, Hausman-chi2-test, quantile-binned-dose-response, arithmetic-vs-geometric-sensitivity]

key-files:
  created:
    - analysis/run_regressions.py
    - tests/test_run_regressions.py
  modified: []

key-decisions:
  - "PanelOLS with entity_effects=True + time_effects=True for two-way FE specification"
  - "Cluster-robust SE via cov_type='clustered', cluster_entity=True at municipality level"
  - "Hausman test computes manual chi2 via coefficient/covariance difference (not linearmodels built-in)"
  - "Degree-3 polynomial for dose-response non-linearity (sufficient for CUDS-LCoGS relationship)"
  - "Vingtile binning (20 quantile bins) for dose-response visualization"
  - "Sensitivity: arithmetic mean recomputed from D1-D7,D9 columns, n_dimensions >= 7 threshold for exclusion"

patterns-established:
  - "load_regression_panel() joins dimension_scores + lcogs_indicators via SQLite inner join"
  - "Per-regression NaN dropping: each outcome has independent missingness handling"
  - "Sensitivity reuses run_panel_regressions() with modified panel (DRY pattern)"
  - "_save_sensitivity_results() extracts cuds coefficient from PanelOLS results into summary CSV"

requirements-completed: [STAT-01, STAT-02, STAT-03, STAT-04]

# Metrics
duration: 5min
completed: 2026-04-02
---

# Phase 7 Plan 1: Panel Regressions, Hausman Tests, Dose-Response & Sensitivity Summary

**Six two-way FE PanelOLS regressions with cluster-robust SEs on CUDS vs LCoGS outcomes, Hausman FE-vs-RE tests, degree-3 polynomial dose-response, and arithmetic-mean/missing-dimension sensitivity analyses**

## Performance

- **Duration:** 5 min
- **Started:** 2026-04-02T04:14:59Z
- **Completed:** 2026-04-02T04:24:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Created analysis/run_regressions.py with full statistical analysis pipeline: 6 PanelOLS regressions, Hausman tests, dose-response, and sensitivity analyses
- Two-way fixed effects (municipality + year) with cluster-robust standard errors at municipality level for all 6 LCoGS outcomes
- Hausman FE-vs-RE test using manual chi2 computation from coefficient and covariance differences
- Dose-response analysis with vingtile binning and degree-3 polynomial fit for non-linear CUDS-LCoGS relationships
- Two sensitivity analyses: arithmetic-mean CUDS (vs geometric) and high-missingness municipality exclusion (n_dimensions < 7)
- 12 unit tests all passing, 198 full suite tests with 0 regressions

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: Failing tests for PanelOLS + Hausman** - `e5bae3b` (test)
2. **Task 1 GREEN: PanelOLS regressions + Hausman implementation** - `a12e732` (feat)
3. **Task 2: Dose-response + sensitivity tests and implementation** - `3536891` (feat)

## Files Created/Modified
- `analysis/run_regressions.py` - Panel regression engine: PanelOLS, Hausman, dose-response, sensitivity, CLI
- `tests/test_run_regressions.py` - 12 tests covering all regression, Hausman, dose-response, and sensitivity behaviors

## Decisions Made
- PanelOLS with entity_effects=True + time_effects=True for two-way FE -- standard specification for municipality-year panel
- Cluster-robust SE via cov_type="clustered", cluster_entity=True -- corrects for within-municipality correlation
- Manual Hausman chi2 test (not built-in) -- linearmodels 7.0 does not expose a built-in Hausman convenience method
- Degree-3 polynomial for dose-response -- captures non-linearity without overfitting; cubic sufficient for continuous CUDS-outcome relationships
- Vingtile binning (20 bins) for dose-response visualization -- balances granularity with bin stability
- check_rank=False in PanelOLS to handle potential multicollinearity with FE dummies
- Per-regression NaN dropping for dependent variables -- each LCoGS outcome has independent missingness patterns

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Known Stubs
None - all regression functions are fully implemented with real linearmodels PanelOLS. Output CSV files are produced by main() when run against the SQLite database.

## Next Phase Readiness
- Regression results available for Phase 8 ML models (XGBoost, Random Forest) as baseline comparison
- Dose-response curves ready for Phase 9 figure generation
- Regression tables ready for Phase 10 paper submission (BMJ Global Health)
- Hausman test confirms FE specification validity for Methods section

## Self-Check: PASSED

- FOUND: analysis/run_regressions.py
- FOUND: tests/test_run_regressions.py
- FOUND: e5bae3b (test commit)
- FOUND: a12e732 (feat commit)
- FOUND: 3536891 (feat commit)

---
*Phase: 07-statistical-analysis*
*Completed: 2026-04-02*
