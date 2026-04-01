# Roadmap: ICSKG-BR

## Overview

ICSKG-BR builds a 50,130-observation longitudinal panel (5,570 Brazilian municipalities × 9 years, 2015–2023) that cross-references the CIMI urban development framework against 6 Lancet Commission on Global Surgery indicators. The pipeline flows from raw government data through extraction, validation, dimension computation, and statistical/ML analysis to a complete BMJ Global Health submission package. Each phase delivers one verifiable layer of that pipeline before the next begins — data completeness is an absolute blocker for all analysis work.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Foundation** - Reproducible environment, shared utilities, and reference data that every downstream script depends on
- [ ] **Phase 2: SIH & CNES Extraction** - Full 12-month annualized SIH Parquet corpus and CNES professional/facility records from NAS raw data
- [ ] **Phase 3: Secondary Source Extraction** - Seven remaining data sources (SIDRA, IDHM, IFGF, ANS, Census, RENAVAM, SIOPS) extracted to Parquet
- [ ] **Phase 4: Panel Assembly & Validation** - Monetary deflation, validation gate, municipality-year merge, IFGF imputation, and SQLite persistence
- [ ] **Phase 5: Dimension Computation & CUDS** - All 8 active CIMI dimension scores computed, within-year min-max normalized, and geometric-mean CUDS derived
- [ ] **Phase 6: LCoGS Indicators** - All 6 LCoGS surgical outcome indicators computed at municipality-year level and loaded into SQLite
- [ ] **Phase 7: Statistical Analysis** - Two-way fixed-effects panel regressions with cluster-robust SEs, Hausman test, dose-response, and sensitivity analyses
- [ ] **Phase 8: Machine Learning Models** - Random Forest and XGBoost with region-stratified cross-validation and SHAP feature importance
- [ ] **Phase 9: Spatial Analysis** - Moran's I autocorrelation test, choropleth maps, and regional disparity analysis
- [ ] **Phase 10: Publication Package** - Publication-ready figures, tables, STROBE/RECORD checklists, data dictionary, and Zenodo release

## Phase Details

### Phase 1: Foundation
**Goal**: Researchers can run any downstream script and trust that municipality codes, environment dependencies, and reference data are consistent and correct
**Depends on**: Nothing (first phase)
**Requirements**: FOUN-01, FOUN-02, FOUN-03, FOUN-04, FOUN-05, FOUN-06
**Success Criteria** (what must be TRUE):
  1. `uv run python -c "import pandas; import duckdb; import linearmodels"` succeeds on a clean checkout with versions matching pyproject.toml pins
  2. `normalize_cod_ibge()` correctly canonicalizes 6-digit and 7-digit IBGE codes across all test fixtures without silent truncation or zero-padding errors
  3. The IBGE reference list loads 5,570 rows with no duplicates, and an `assert len(ref) == 5570` statement passes
  4. The validation gate rejects a DataFrame containing a known-bad municipality code and a known out-of-range value, raising a documented exception
  5. The AMC temporal crosswalk maps all ~30–50 municipality splits/merges from 2013–2023 to their canonical 2023 codes
**Plans**: 4 plans

Plans:
- [x] 01-01-PLAN.md — Bootstrap Python 3.12 environment, pyproject.toml with pinned deps, config.yaml NAS path config
- [ ] 01-02-PLAN.md — normalize_cod_ibge() utility, IBGE 2023 reference list (5,570 municipalities)
- [ ] 01-03-PLAN.md — AMC temporal crosswalk for municipality boundary harmonization 2015-2023
- [ ] 01-04-PLAN.md — Validation gate: schema checks, municipality code audit, range checks, quarantine

### Phase 2: SIH & CNES Extraction
**Goal**: The full 12-month annualized SIH surgical corpus and CNES professional/facility records are available as clean Parquet files, ready for municipality-year aggregation
**Depends on**: Phase 1
**Requirements**: DATA-01, DATA-02
**Success Criteria** (what must be TRUE):
  1. SIH Parquet files exist for all 12 months × 9 years × 27 states under `data_sources/processed/sih/` with non-zero file sizes
  2. Running the SIH processor twice on the same NAS source produces identical Parquet output (idempotent)
  3. CNES professional Parquet contains surgeon, anesthesiologist, and obstetrician records filtered to CBO codes, with CNS identifiers retained for deduplication
  4. CNES facility Parquet contains all hospitals flagged as having a surgical center, obstetric center, or inpatient beds, with geocoordinates populated or geocoding attempted
  5. A PySUS `blast-dbf` pre-flight check passes, and every DBC-to-Parquet conversion asserts the output file exists with non-zero size before proceeding
**Plans**: TBD

### Phase 3: Secondary Source Extraction
**Goal**: All seven remaining data sources are extracted, parsed, and stored as standardized Parquet files with IBGE municipality codes canonicalized
**Depends on**: Phase 1
**Requirements**: DATA-03, DATA-04, DATA-05, DATA-06, DATA-07, DATA-08, DATA-09
**Success Criteria** (what must be TRUE):
  1. IBGE SIDRA returns population estimates and GDP per capita for all 5,570 municipalities for at least 8 of 9 years (2023 GDP flagged as estimated if subject to 2-year lag)
  2. IPEA IDHM/IVS proxy delivers a time-varying human capital indicator — not a single census-year value — for all municipalities across 2015–2023
  3. FIRJAN IFGF Parquet contains all 5 sub-indices and IFGF Geral for 2015–2023 with ~420 MNAR municipalities per year present as NaN (not zero, not dropped)
  4. ANS beneficiary counts reflect a quarterly average (Q1–Q4 mean) rather than a December snapshot, for all years
  5. RENAVAM, SIOPS, and IBGE Census 2022 Parquet files exist with at least one full year of data and a format validation log noting any structural surprises discovered during parsing
**Plans**: TBD

### Phase 4: Panel Assembly & Validation
**Goal**: A validated, deflated, imputed 50,130-row panel exists in SQLite with one row per municipality per year and a documented missingness profile
**Depends on**: Phase 2, Phase 3
**Requirements**: DATA-10, PANL-01, PANL-02, PANL-03, PANL-04, PANL-05, PANL-06
**Success Criteria** (what must be TRUE):
  1. All monetary variables (SIOPS, GDP per capita) are expressed in constant 2023 BRL after applying IPCA deflators, with deflation factors auditable from a logged deflation table
  2. `validation_report.json` exists with per-source quality metrics; any source failing schema or range checks is quarantined to `data_sources/quarantine/` and does not silently reach the merge
  3. After the municipality-year merge, `assert len(panel[panel.year == y]) == 5570` passes for every year y in 2015–2023
  4. SQLite `municipal_health` table contains exactly 50,130 rows and the schema matches the documented DDL
  5. IFGF missing values for ~420 MNAR municipalities per year are filled via multiple imputation (auxiliary variables: GDP, region, population), and the imputation method is logged in `PANL-05-imputation.log`
  6. `PANL-06-missingness.csv` documents missingness rate per variable per year, satisfying RECORD item 12.1
**Plans**: TBD

### Phase 5: Dimension Computation & CUDS
**Goal**: Every municipality-year row in SQLite carries a valid score for all 8 active CIMI dimensions and a CUDS composite that reflects the geometric mean of within-year normalized scores
**Depends on**: Phase 4
**Requirements**: DIMS-01, DIMS-02, DIMS-03, DIMS-04
**Success Criteria** (what must be TRUE):
  1. SQLite `dimension_scores` table has 50,130 rows with D1–D7 and D9 populated (D8 absent with documented exclusion)
  2. After within-year normalization, every dimension has exactly one municipality scoring 0.0 and one scoring 1.0 per year — confirmed by assertion
  3. CUDS is computed as a geometric mean with floor offset (epsilon=0.01), no municipality scores exactly 0.0 CUDS, and the distribution is right-skewed (majority below 0.5) as expected for Brazilian municipal inequality
  4. Census 2022 sanitation (D5) and IDHM/proxy (D3) are explicitly annotated as cross-sectional in `dimension_metadata` table, with a note in the computation log that they do not represent genuine temporal variation
**Plans**: TBD

### Phase 6: LCoGS Indicators
**Goal**: All 6 LCoGS surgical outcome indicators are computed at municipality-year level and loaded into SQLite, ready for regression analysis
**Depends on**: Phase 4, Phase 5
**Requirements**: LCOG-01, LCOG-02, LCOG-03, LCOG-04, LCOG-05, LCOG-06
**Success Criteria** (what must be TRUE):
  1. LCoGS-1 (bellwether access) assigns a haversine distance to nearest geocoded bellwether hospital for all 5,570 municipalities, sourced from 765+ CNES-geocoded facilities
  2. LCoGS-2 (SAO density) deduplicates surgeons, anesthesiologists, and obstetricians by CNS identifier before computing per-100,000 density, with a deduplication count logged
  3. LCoGS-3 (surgical volume) and LCoGS-4 (POMR) are labeled as SUS-funded procedures only, and the POMR definition (in-hospital deaths within 30 days of surgical admission) is documented in a methods comment
  4. LCoGS-5 and LCoGS-6 (financial risk proxies) are computed as ratios of SIH procedure cost to GDP per capita (both in constant 2023 BRL), with ecological-proxy caveats noted in `lcogs_metadata` table
  5. SQLite `lcogs_indicators` table has 50,130 rows with all 6 indicators; any municipality-year with fewer than 10 surgical events has LCoGS-4 set to NaN rather than an unstable rate
**Plans**: TBD

### Phase 7: Statistical Analysis
**Goal**: Primary hypothesis tests are complete — two-way fixed-effects panel regressions of CUDS on each LCoGS outcome, with cluster-robust standard errors, Hausman test, and sensitivity analyses, all reproducible
**Depends on**: Phase 5, Phase 6
**Requirements**: STAT-01, STAT-02, STAT-03, STAT-04
**Success Criteria** (what must be TRUE):
  1. Six PanelOLS regressions (one per LCoGS outcome) complete using linearmodels 7.0 with municipality and year fixed effects, and results are saved to `results/regression_tables/`
  2. All regression standard errors are cluster-robust at the municipality level, and the clustering specification is verified in the model summary output
  3. Hausman test statistic and p-value for each regression outcome are logged to `results/hausman_test.csv`, confirming fixed-effects selection is justified (or documenting the exception if not)
  4. Dose-response analysis produces a non-linear CUDS–LCoGS curve for at least one outcome, showing the relationship is not assumed to be linear
  5. Sensitivity analysis results exist comparing arithmetic mean vs geometric mean CUDS, and a second sensitivity excluding municipalities with 2 or more missing dimensions — both stored in `results/sensitivity/`
**Plans**: TBD

### Phase 8: Machine Learning Models
**Goal**: Random Forest and XGBoost dose-response models are trained, cross-validated, and interpreted with SHAP values, providing dimension-level feature importance for all 6 LCoGS outcomes
**Depends on**: Phase 5, Phase 6
**Requirements**: MLMD-01, MLMD-02, MLMD-03, MLMD-04
**Success Criteria** (what must be TRUE):
  1. Random Forest and XGBoost models are trained for each of the 6 LCoGS outcomes with hyperparameters logged and random seeds fixed for reproducibility
  2. 5-fold cross-validation is stratified by the 5 Brazilian macro-regions (Norte, Nordeste, Centro-Oeste, Sudeste, Sul), preventing geographic leakage between train and test sets
  3. SHAP beeswarm plots exist for each LCoGS outcome showing dimension-level feature importance, saved as 300 DPI PNG files in `results/figures/shap/`
  4. Model performance metrics (RMSE, R², MAE) for all cross-validation folds are saved to `results/ml_metrics.csv` and show consistent performance across folds without large variance
**Plans**: TBD

### Phase 9: Spatial Analysis
**Goal**: Spatial autocorrelation of regression residuals is tested, and publication-ready choropleth and heatmap figures document the geographic distribution of CUDS and LCoGS indicators
**Depends on**: Phase 7
**Requirements**: SPAT-01, SPAT-02, SPAT-03, SPAT-04
**Success Criteria** (what must be TRUE):
  1. Moran's I statistic and p-value on fixed-effects residuals are computed for at least the primary regression outcome, with the result logged to `results/spatial/morans_i.csv` and interpreted in a comment
  2. CUDS choropleth map renders all 5,570 municipalities at 300 DPI minimum with a colorblind-safe diverging palette, state borders visible, and a legend
  3. Regional disparity analysis produces summary statistics (mean, median, IQR) for CUDS and each LCoGS indicator across all 5 macro-regions, saved as `results/tables/regional_disparity.csv`
  4. LCoGS indicator heatmaps by region show temporal trends (2015–2023) and are saved as publication-ready figures
**Plans**: TBD

### Phase 10: Publication Package
**Goal**: A complete, submission-ready BMJ Global Health package exists — all required figures, tables, compliance checklists, data dictionary, and a Zenodo-archived public release
**Depends on**: Phase 7, Phase 8, Phase 9
**Requirements**: PUBL-01, PUBL-02, PUBL-03, PUBL-04, PUBL-05, PUBL-06, PUBL-07, PUBL-08, PUBL-09, PUBL-10
**Success Criteria** (what must be TRUE):
  1. Four publication-ready figures exist at 300 DPI minimum with colorblind-safe palettes: CUDS choropleth map, CUDS temporal trend by region, LCoGS regional heatmap, and main regression forest plot
  2. Eight publication-ready tables exist: descriptive statistics, dimension descriptives, missingness summary (RECORD 12.1), correlation matrix, and four regression result tables (one per LCoGS pair)
  3. STROBE checklist (22 items) and RECORD extension (13 items) are completed with manuscript section references for each item — no item left blank
  4. The data dictionary documents every variable with name, source, definition, unit, coverage years, and missingness rate, and matches the SQLite schema
  5. Zenodo archive is created with a DOI, GitHub release is tagged, and the data availability statement lists URLs for all 8 source portals
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10

Note: Phases 2 and 3 are independent and can be developed in parallel, but both must complete before Phase 4 begins.

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation | 0/TBD | Not started | - |
| 2. SIH & CNES Extraction | 0/TBD | Not started | - |
| 3. Secondary Source Extraction | 0/TBD | Not started | - |
| 4. Panel Assembly & Validation | 0/TBD | Not started | - |
| 5. Dimension Computation & CUDS | 0/TBD | Not started | - |
| 6. LCoGS Indicators | 0/TBD | Not started | - |
| 7. Statistical Analysis | 0/TBD | Not started | - |
| 8. Machine Learning Models | 0/TBD | Not started | - |
| 9. Spatial Analysis | 0/TBD | Not started | - |
| 10. Publication Package | 0/TBD | Not started | - |
