# Requirements: ICSKG-BR

**Defined:** 2026-04-01
**Core Value:** A reproducible, publicly-sourced database proving whether municipal urban development predicts surgical system performance — first subnational cross-reference of urban development composite indices with surgical indicators.

## v1 Requirements

### Foundation

- [x] **FOUN-01**: Python 3.12 runtime with uv-managed environment and reproducible uv.lock lockfile
- [x] **FOUN-02**: Shared normalize_cod_ibge() utility that canonicalizes 6-digit and 7-digit IBGE municipality codes across all sources
- [x] **FOUN-03**: IBGE reference list of 5,570 canonical municipality codes for join validation and completeness assertions
- [x] **FOUN-04**: Validation gate (schema checks, range checks, duplicate detection) that runs before any merge operation
- [x] **FOUN-05**: pyproject.toml with all dependencies pinned (pandas 2.2.3, DuckDB 1.5.1, linearmodels 7.0, etc.)
- [x] **FOUN-06**: AMC temporal crosswalk for municipality boundary harmonization (2015-2023 splits/merges)

### Data Acquisition

- [x] **DATA-01**: SIH processor — read raw SIH data from NAS (already downloaded, all 12 months × 9 years × 27 states), convert DBC→Parquet, aggregate to municipality-year level
- [ ] **DATA-02**: CNES extractor — professional records (PF group) with CBO-based filtering for surgeons, anesthesiologists, obstetricians; facility records for bellwether hospital identification
- [x] **DATA-01**: SIH processor — read raw SIH data from NAS (already downloaded, all 12 months × 9 years × 27 states), convert DBC→Parquet, aggregate to municipality-year level
- [x] **DATA-02**: CNES extractor — professional records (PF group) with CBO-based filtering for surgeons, anesthesiologists, obstetricians; facility records for bellwether hospital identification
- [ ] **DATA-01**: SIH processor — read raw SIH data from NAS (already downloaded, all 12 months × 9 years × 27 states), convert DBC→Parquet, aggregate to municipality-year level
- [x] **DATA-02**: CNES extractor — professional records (PF group) with CBO-based filtering for surgeons, anesthesiologists, obstetricians; facility records for bellwether hospital identification
- [ ] **DATA-03**: IBGE SIDRA extractor — population estimates (table 6579) and GDP per capita (table 5938) for all municipalities via API
- [ ] **DATA-04**: IPEA IDHM extractor — composite + education/longevity/income sub-indices via OData API; handle census-only availability (2010, 2022)
- [ ] **DATA-05**: FIRJAN IFGF parser — 5 sub-indices + IFGF Geral from Excel file for 2015-2023
- [ ] **DATA-06**: ANS beneficiary extractor — quarterly beneficiary counts averaged (not December snapshot) for private coverage rate computation
- [ ] **DATA-07**: IBGE Census 2022 sanitation extractor — adequate sanitation % and water supply % via Panorama API
- [ ] **DATA-08**: RENAVAM vehicle fleet parser — vehicles per 1,000 inhabitants from dados.transportes.gov.br CSVs (format discovery required)
- [ ] **DATA-09**: SIOPS health expenditure extractor — per-capita municipal health spending from portalfns.saude.gov.br (format discovery required)
- [ ] **DATA-10**: All monetary variables (SIOPS, GDP) deflated to constant 2023 BRL using IPCA indices

### Panel Assembly

- [ ] **PANL-01**: Municipality-year merge producing one row per municipality per year (assert 5,570 rows/year after merge)
- [ ] **PANL-02**: Validation report (validation_report.json) with per-source quality metrics
- [ ] **PANL-03**: Quarantine directory for flagged rows excluded from panel
- [ ] **PANL-04**: SQLite database with municipal_health table (50,130 rows target), dimension_metadata, municipality_lookup tables
- [ ] **PANL-05**: IFGF multiple imputation for ~420 MNAR municipalities per year using auxiliary variables (GDP, region, population)
- [ ] **PANL-06**: Missing data documentation table showing missingness rates per variable per year (RECORD item 12.1)

### Dimension Computation

- [ ] **DIMS-01**: 9 CIMI dimension scores computed from source data (D1-Governance through D9-Technology, excluding D8-International Projection)
- [ ] **DIMS-02**: Min-max normalization within each year using groupby('year').transform()
- [ ] **DIMS-03**: CUDS composite computed as geometric mean of normalized dimensions with floor offset (epsilon=0.01) to prevent zero collapse
- [ ] **DIMS-04**: Cross-sectional dimensions (Census 2022 sanitation, IDHM) explicitly flagged as single-year with documentation

### LCoGS Indicators

- [ ] **LCOG-01**: LCoGS-1 — Access to bellwether procedures (haversine distance to nearest bellwether hospital from 765+ geocoded facilities)
- [ ] **LCOG-02**: LCoGS-2 — SAO workforce density per 100,000 population (surgeons + anesthesiologists + obstetricians, deduplicated by CNS)
- [ ] **LCOG-03**: LCoGS-3 — Surgical volume per 100,000 population (SUS-funded procedures from SIH)
- [ ] **LCOG-04**: LCoGS-4 — Perioperative mortality rate from SIH (in-hospital deaths within 30 days of surgical admission)
- [ ] **LCOG-05**: LCoGS-5 — Financial risk protection (ecological proxy: average SIH procedure cost / GDP per capita)
- [ ] **LCOG-06**: LCoGS-6 — Catastrophic expenditure (ecological proxy: procedures exceeding cost threshold relative to GDP per capita)

### Statistical Analysis

- [ ] **STAT-01**: Two-way fixed-effects panel regression (municipality FE + year FE) of CUDS → each LCoGS outcome
- [ ] **STAT-02**: Cluster-robust standard errors at municipality level for all regressions
- [ ] **STAT-03**: Hausman test for fixed vs random effects selection (reported in supplement)
- [ ] **STAT-04**: Dose-response analysis showing non-linear CUDS-LCoGS relationships

### Machine Learning

- [ ] **MLMD-01**: Random Forest model predicting each LCoGS outcome from CIMI dimensions
- [ ] **MLMD-02**: XGBoost model predicting each LCoGS outcome from CIMI dimensions
- [ ] **MLMD-03**: 5-fold cross-validation stratified by macro-region (prevents geographic leakage)
- [ ] **MLMD-04**: SHAP values for feature importance (dimension-level beeswarm plots)

### Spatial Analysis

- [ ] **SPAT-01**: Moran's I spatial autocorrelation test on fixed-effects model residuals
- [ ] **SPAT-02**: CUDS choropleth map of all municipalities (publication-ready, 300 DPI)
- [ ] **SPAT-03**: Regional disparity analysis across 5 macro-regions (Norte, Nordeste, Centro-Oeste, Sudeste, Sul)
- [ ] **SPAT-04**: LCoGS indicator heatmaps by region

### Publication Package

- [ ] **PUBL-01**: 4 publication-ready figures at 300 DPI minimum, colorblind-safe palette (CUDS map, CUDS trend, LCoGS heatmap, regression forest plot)
- [ ] **PUBL-02**: 8 publication-ready tables (descriptive stats, dimension descriptives, missingness summary, correlation matrix, 4 regression result tables)
- [ ] **PUBL-03**: STROBE checklist compliance (22 items) for observational studies
- [ ] **PUBL-04**: RECORD extension compliance (13 items) for routinely collected health data
- [ ] **PUBL-05**: Sensitivity analysis: arithmetic mean vs geometric mean CUDS
- [ ] **PUBL-06**: Sensitivity analysis: excluding municipalities with ≥2 missing dimensions
- [ ] **PUBL-07**: Complete data dictionary (variable name, source, definition, unit, coverage, missingness rate)
- [ ] **PUBL-08**: Ethics statement citing Brazilian Resolution 510/2016
- [ ] **PUBL-09**: Data availability statement with URLs to all source portals
- [ ] **PUBL-10**: Zenodo DOI archive + public GitHub release at submission

## v2 Requirements

### Enhanced Analysis

- **ENH-01**: Multilevel models (marginal gain over FE; note as future work)
- **ENH-02**: Per-municipality HTML/PDF reports (5,570 reports)
- **ENH-03**: Interactive web dashboard for researchers
- **ENH-04**: ANS SIP private procedure data linkage for supplementary LCoGS-3 estimate
- **ENH-05**: MICE imputation for cross-sectional dimensions (if methodologically justified)

## Out of Scope

| Feature | Reason |
|---------|--------|
| CIMI dimension 10 (International Projection) | Irrelevant at municipal level for 99% of Brazilian municipalities; documented limitation |
| Individual-level patient analysis | Ecological study design; all analyses at municipality-level aggregates |
| Causal inference claims | Ecological study; dose-response associations only |
| Real-time dashboard | Research database, not an application |
| Mobile app | Academic research output only |
| pandas 3.0 migration | Breaking changes in CoW and string dtype; defer until pipeline validated end-to-end |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| FOUN-01 | Phase 1 | Complete |
| FOUN-02 | Phase 1 | Complete |
| FOUN-03 | Phase 1 | Complete |
| FOUN-04 | Phase 1 | Complete |
| FOUN-05 | Phase 1 | Complete |
| FOUN-06 | Phase 1 | Complete |
| DATA-01 | Phase 2 | Complete |
| DATA-02 | Phase 2 | Pending |
| DATA-01 | Phase 2 | Complete |
| DATA-02 | Phase 2 | Complete |
| DATA-01 | Phase 2 | Pending |
| DATA-02 | Phase 2 | Complete |
| DATA-03 | Phase 2 | Pending |
| DATA-04 | Phase 2 | Pending |
| DATA-05 | Phase 2 | Pending |
| DATA-06 | Phase 2 | Pending |
| DATA-07 | Phase 2 | Pending |
| DATA-08 | Phase 2 | Pending |
| DATA-09 | Phase 2 | Pending |
| DATA-10 | Phase 3 | Pending |
| PANL-01 | Phase 3 | Pending |
| PANL-02 | Phase 3 | Pending |
| PANL-03 | Phase 3 | Pending |
| PANL-04 | Phase 3 | Pending |
| PANL-05 | Phase 3 | Pending |
| PANL-06 | Phase 3 | Pending |
| DIMS-01 | Phase 4 | Pending |
| DIMS-02 | Phase 4 | Pending |
| DIMS-03 | Phase 4 | Pending |
| DIMS-04 | Phase 4 | Pending |
| LCOG-01 | Phase 5 | Pending |
| LCOG-02 | Phase 5 | Pending |
| LCOG-03 | Phase 5 | Pending |
| LCOG-04 | Phase 5 | Pending |
| LCOG-05 | Phase 5 | Pending |
| LCOG-06 | Phase 5 | Pending |
| STAT-01 | Phase 6 | Pending |
| STAT-02 | Phase 6 | Pending |
| STAT-03 | Phase 6 | Pending |
| STAT-04 | Phase 6 | Pending |
| MLMD-01 | Phase 7 | Pending |
| MLMD-02 | Phase 7 | Pending |
| MLMD-03 | Phase 7 | Pending |
| MLMD-04 | Phase 7 | Pending |
| SPAT-01 | Phase 8 | Pending |
| SPAT-02 | Phase 8 | Pending |
| SPAT-03 | Phase 8 | Pending |
| SPAT-04 | Phase 8 | Pending |
| PUBL-01 | Phase 9 | Pending |
| PUBL-02 | Phase 9 | Pending |
| PUBL-03 | Phase 9 | Pending |
| PUBL-04 | Phase 9 | Pending |
| PUBL-05 | Phase 9 | Pending |
| PUBL-06 | Phase 9 | Pending |
| PUBL-07 | Phase 9 | Pending |
| PUBL-08 | Phase 9 | Pending |
| PUBL-09 | Phase 9 | Pending |
| PUBL-10 | Phase 9 | Pending |

**Coverage:**
- v1 requirements: 48 total
- Mapped to phases: 48
- Unmapped: 0 ✓

---
*Requirements defined: 2026-04-01*
*Last updated: 2026-04-01 after initial definition*
