# Phase 7: Statistical Analysis - Context

**Gathered:** 2026-04-02
**Status:** Ready for planning
**Mode:** Auto-generated (autonomous workflow)

<domain>
## Phase Boundary

Two-way fixed-effects panel regressions of CUDS on each LCoGS outcome, with cluster-robust standard errors, Hausman test, dose-response analysis, and sensitivity analyses. All reproducible from the SQLite panel.

</domain>

<decisions>
## Implementation Decisions

### Panel Regression
- 6 PanelOLS regressions (one per LCoGS outcome) using linearmodels 7.0
- Municipality fixed effects + year fixed effects (two-way FE)
- Cluster-robust standard errors at municipality level
- Results saved to results/regression_tables/

### Hausman Test
- FE vs RE selection test for each regression
- Statistic and p-value logged to results/hausman_test.csv
- Expected: FE justified for most/all outcomes

### Dose-Response
- Non-linear CUDS-LCoGS relationship for at least one outcome
- Polynomial or spline fit showing the relationship is not assumed linear

### Sensitivity Analysis
- Arithmetic mean vs geometric mean CUDS comparison
- Excluding municipalities with ≥2 missing dimensions
- Results in results/sensitivity/

### Claude's Discretion
- Which LCoGS outcome to feature in dose-response (likely LCoGS-3 surgical volume)
- Spline vs polynomial for non-linear fit
- Additional control variables beyond CUDS (region dummies, population)
- Table formatting (LaTeX vs CSV)

</decisions>

<code_context>
## Existing Code Insights

- analysis/compute_dimensions.py — dimension scores + CUDS in SQLite
- analysis/compute_lcogs.py — LCoGS indicators in SQLite
- linearmodels already pinned in pyproject.toml
- analysis/icskg_analysis_pipeline.py — existing analysis stubs (reference)

</code_context>

<specifics>
## Specific Ideas

- linearmodels PanelOLS requires MultiIndex (entity, time) on the DataFrame
- ClusteredCovariance with cluster_entity=True for municipality-level clustering

</specifics>

<deferred>
## Deferred Ideas

None — all STAT requirements in scope.

</deferred>
