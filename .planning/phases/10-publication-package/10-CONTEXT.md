# Phase 10: Publication Package - Context

**Gathered:** 2026-04-02
**Status:** Ready for planning
**Mode:** Auto-generated (autonomous workflow — final phase)

<domain>
## Phase Boundary

Assemble all analysis outputs into a complete BMJ Global Health submission package: publication-ready figures, tables with CIs and dispersion measures, STROBE/RECORD checklists, data dictionary, and Zenodo release preparation. This phase produces no new analysis — it formats, validates, and packages existing outputs.

</domain>

<decisions>
## Implementation Decisions

### Figures (4 minimum, 300 DPI, colorblind-safe)
- Fig 1: CUDS choropleth map (already in spatial_analysis.py)
- Fig 2: CUDS temporal trend by region (line plot, 5 macro-regions, 2015-2023)
- Fig 3: LCoGS regional heatmap (already in spatial_analysis.py)
- Fig 4: Main regression forest plot (coefficient + 95% CI for all 6 outcomes)
- Bonus: Bivariate choropleth (already in spatial_analysis.py)
- Bonus: Patient flow network map (already in spatial_analysis.py)
- Bonus: SHAP beeswarm plots (already in ml_models.py)

### Tables (8 minimum, all with SD/SE/IQR + 95% CIs)
- Table 1: Descriptive statistics (all variables, mean ± SD, 95% CI)
- Table 2: CIMI dimension descriptives by region
- Table 3: Missingness summary (RECORD 12.1 — from PANL-06)
- Table 4: Correlation matrix (CUDS dimensions × LCoGS indicators)
- Tables 5-8: Regression results (PanelOLS coefficients, cluster-robust SE, 95% CI)
- All monetary values in both BRL and USD

### STROBE + RECORD Compliance
- STROBE checklist: 22 items with manuscript section references
- RECORD extension: 13 items for routinely collected health data
- No item left blank

### Data Dictionary
- Every variable: name, source, definition, unit, coverage years, missingness rate
- Must match SQLite schema exactly

### Zenodo Release
- DOI reservation
- GitHub release tag
- Data availability statement listing all 8+ source portals

### Claude's Discretion
- Figure layout and subplot arrangement
- Table formatting (LaTeX vs CSV vs both)
- Whether to generate a supplementary materials document
- Forest plot implementation (matplotlib vs forestplot package)
- Exact Zenodo metadata fields

</decisions>

<code_context>
## Existing Code Insights

### Available Outputs (from Phases 5-9.1)
- analysis/compute_dimensions.py — CUDS + PCA composite
- analysis/compute_lcogs.py — 6 LCoGS indicators
- analysis/run_regressions.py — PanelOLS results with CIs
- analysis/ml_models.py — RF/XGBoost metrics + SHAP plots
- analysis/spatial_analysis.py — choropleths, heatmaps, bivariate, flow network
- analysis/causal_inference.py — EconML DML + Causal Forest
- analysis/age_standardization.py — age/gender standardized rates
- analysis/reporting.py — CI/dispersion helpers
- analysis/network_distances.py — travel distance summaries
- database/build_database_v3.py — SQLite with all tables
- database/impute_ifgf.py — missingness report (PANL-06)

### Integration Points
- All figures go to results/figures/ at 300 DPI
- All tables go to results/tables/ as CSV (+ LaTeX if needed)
- STROBE/RECORD checklists as markdown or DOCX
- Data dictionary as CSV matching SQLite schema

</code_context>

<specifics>
## Specific Ideas

- SciencePlots already available for matplotlib journal styling
- Many figures already generated in Phases 8-9 — this phase collates and polishes
- STROBE checklist template available from EQUATOR Network
- RECORD extension specific to routinely collected health data studies

</specifics>

<deferred>
## Deferred Ideas

None — this is the final phase.

</deferred>
