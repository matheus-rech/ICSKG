# Project Research Summary

**Project:** ICSKG-BR — Municipal Urban Development & Global Surgery Panel Study
**Domain:** Reproducible ecological panel study data pipeline (multi-source ETL → composite index → ML analysis → BMJ Global Health publication)
**Researched:** 2026-04-01
**Confidence:** HIGH (stack verified via PyPI; architecture grounded in codebase inspection; pitfalls from peer-reviewed DATASUS literature)

---

## Executive Summary

ICSKG-BR is a multi-source Brazilian municipal data pipeline that builds a 50,130-observation panel (5,570 municipalities × 9 years, 2015–2023), computes an urban development composite index (CUDS) from 8 active CIMI dimensions using a geometric mean of min-max normalized scores, and validates that index against 6 Lancet Commission on Global Surgery (LCoGS) indicators. The target venue is BMJ Global Health, which requires full STROBE + RECORD compliance, cluster-robust standard errors, two-way fixed-effects panel regression, and complete data availability statements. The pipeline must be reproducible from raw government FTP files to publication-ready figures without manual steps.

The recommended approach is a strictly layered, stage-gated pipeline: immutable raw data in data_sources/raw/, source-partitioned Parquet in data_sources/processed/, a validation gate before any merge, DuckDB for analytical aggregation of the 100+ GB raw SIH corpus, SQLite as the lightweight panel database, and modular Python scripts with a shared normalize_cod_ibge() utility as the architectural spine. The existing codebase covers roughly 30% of required data sources and uses arithmetic mean for CUDS (contradicting the published methodology); the first roadmap priority is closing both gaps before any analysis work begins. Python must be upgraded from 3.9 to 3.12 immediately — pysus 1.x and pandas 2.2.3 do not support 3.9.

The dominant risks are not technical complexity but data quality: SIH captures only 60–70% of hospitalizations (private sector is invisible), IFGF governance data is missing-not-at-random for ~420 municipalities per year, IDHM human capital data is only available at Census years (not annually), and the geometric mean collapses to zero when any single dimension is at its minimum — which is mathematically guaranteed for at least one municipality per dimension every year. All four of these must be addressed before regression modeling, not discovered during peer review.

---

## Key Findings

### Recommended Stack

The Python runtime must move to 3.12. The data processing core is pandas 2.2.3 (pinned below the breaking pandas 3.0 release), numpy 2.x, and pyarrow 19 for Parquet. DuckDB 1.5.1 should be promoted from optional to mandatory for the raw SIH ETL stage — reading 100+ GB of per-state Parquet files via pandas would require loading full files into RAM; DuckDB reads with predicate pushdown and uses all CPU cores. SQLite remains the correct panel database at this data volume (50 MB final panel). The linearmodels 7.0 package for two-way fixed-effects panel regression is absent from the current stack and must be added — it is required for the formal regression tables BMJ Global Health expects. Environment management via uv with a uv.lock file is required to satisfy the reproducibility standard.

Two data sources have no Python library: SIOPS (per-capita health expenditure) requires direct CSV download from portalfns.saude.gov.br, and RENAVAM (vehicle fleet) requires parsing monthly CSVs from dados.transportes.gov.br. Both are public data under Lei de Acesso à Informação but require custom download and parsing scripts.

**Core technologies:**
- Python 3.12: Runtime — hard requirement for pysus 1.x and pandas 2.2.3
- pysus 1.0.1: SIH and CNES DBC acquisition and conversion — replaces the existing custom ftplib downloader
- pandas 2.2.3 (pinned <3.0): DataFrame operations — pandas 3.0 changes break the existing codebase silently
- DuckDB 1.5.1: Analytical ETL over raw Parquet — mandatory for 100+ GB SIH corpus
- SQLite (stdlib): Panel database — correct at 50,130 rows, zero infrastructure
- linearmodels 7.0: Two-way fixed-effects panel regression — currently absent, required for submission
- scikit-learn >=1.6 + xgboost >=2.1: ML dose-response models — Random Forest and XGBoost with sklearn wrapper
- geopandas 1.1.3: Haversine distance, spatial joins, choropleth figures
- uv: Reproducible environment with lockfile — replaces absent lockfile

### Expected Features

**Must have (table stakes — reviewer rejection without these):**
- Complete panel: all 5,570 municipalities × 9 years, all 8 active CIMI dimensions populated
- CUDS computed as geometric mean of within-year min-max normalized dimension scores (with floor offset to prevent zero collapse)
- All 6 LCoGS indicators at municipal level (LCoGS-1 through LCoGS-6)
- Two-way fixed-effects panel regression (municipality FE + year FE) with cluster-robust standard errors
- Hausman test (FE vs RE selection) reported in supplement
- Deflation of all monetary variables to constant 2023 BRL (IPCA health sub-index for SIOPS; IPCA general for GDP)
- Missing data documentation table (RECORD item 12.1) — IFGF ~420 municipalities MNAR requires explicit treatment
- STROBE checklist (22 items) and RECORD extension (13 items) compliance
- Municipality inclusion/exclusion flow diagram (STROBE requirement)
- 4 publication-ready figures at 300 DPI minimum, colorblind-safe palette
- 8 publication-ready tables (descriptive stats, missingness, correlation matrix, regression results by LCoGS outcome)
- Idempotent pipeline with all random seeds fixed — deterministic outputs on re-run
- Data dictionary: variable name, source, definition, unit, coverage, missingness rate
- Ethics statement citing Brazilian Resolution 510/2016 (aggregate public data, no IRB required)
- Data availability statement with URLs to all source portals

**Should have (differentiators that meaningfully raise acceptance probability):**
- Sensitivity analysis: arithmetic mean vs geometric mean CUDS (addresses the likeliest reviewer challenge)
- Sensitivity analysis: excluding municipalities with ≥2 missing dimensions
- Spatial autocorrelation assessment: Moran's I on fixed-effects model residuals
- SHAP values for Random Forest and XGBoost models (dimension-level feature importance, beeswarm plots)
- 5-fold cross-validation of ML models stratified by macro-region (prevents geographic leakage)
- Haversine distance as a continuous geographic access predictor (extends binary LCoGS-1)
- Municipality boundary harmonization for ~30–50 municipalities created/split 2013–2023 (AMC crosswalk)
- Full 12-month annualized SIH data rather than December snapshots (eliminates seasonal bias)
- STROBE-Equity extension items (equity framing signals alignment with BMJ Global Health editorial priorities)
- Zenodo DOI + public GitHub archive at submission

**Defer to v2+:**
- Interactive web dashboard (explicitly out of scope per PROJECT.md)
- Per-municipality HTML/PDF reports (5,570 reports = an engineering project, not a research pipeline)
- Multilevel models (marginal gain over fixed-effects; note as future work)
- MICE imputation for cross-sectional dimensions (Census 2022 sanitation is not missing-at-random)

### Architecture Approach

The pipeline follows a strictly layered, stage-gated structure where each layer produces immutable filesystem artifacts consumed by the next. No layer reads upward. The 8-layer sequence is: Acquisition (raw FTP/API downloads) → Parsing/Format Normalization (DBC/XLSX/CSV to Parquet) → Validation Gate (schema, range, municipality code audit) → Municipality-Level Aggregation + Merge → Database Persistence (SQLite) → Dimension Computation (CUDS) → Parallel analysis branches (LCoGS indicators, ML models, descriptive/geospatial) → Publication Output. All inter-layer communication is through filesystem artifacts; no component calls across layer boundaries. The single most important shared utility is normalize_cod_ibge(), which must canonicalize the 6-digit vs 7-digit municipality code discrepancy across at least 8 different source parsers before any join.

**Major components:**
1. `database/utils.py` — normalize_cod_ibge() and shared helpers; must be the first new file created
2. `database/validation.py` — validation gate between parsing and merge; required before any panel assembly
3. Source-specific `scripts/download_*.py` + `scripts/parse_*.py` — one pair per data source, following the extractor function contract (idempotent, returns Path or None)
4. `database/pipeline.py` — ETL orchestrator; currently handles 2 sources, must be extended to 8+
5. `database/build_database_v2.py` — SQLite schema DDL and upsert; delete-write pattern mandatory
6. `analysis/compute_dimensions.py` — per-dimension compute functions returning raw (un-normalized) Series; normalization applied centrally in build_panel() using groupby('year').transform()
7. `analysis/compute_lcogs.py` — 6 LCoGS indicator computations
8. `analysis/ml_models.py` — Random Forest + XGBoost with cross-validation and SHAP
9. `analysis/icskg_analysis_pipeline.py` — figures, tables, STROBE output

### Critical Pitfalls

1. **SIH private sector blindspot (LCoGS-3, LCoGS-4)** — SIH captures only 60–70% of hospitalizations; private-sector municipalities will show artificially low surgical volume and inflated POMR. State in Methods that LCoGS-3/4 reflect SUS-funded procedures only; add ANS private data as supplementary estimate; restrict sensitivity analysis to municipalities with <10% ANS coverage.

2. **Geometric mean collapses to zero when any dimension is at its minimum** — min-max normalization guarantees one municipality scores exactly 0.0 per dimension; geometric mean of scores containing zero equals zero regardless of all other dimensions. Apply a floor offset (add 0.01) to all normalized scores before computing geometric mean; never impute NaN as 0; audit zero-score counts after normalization.

3. **Municipality code format mismatch causes silent merge failures** — IFGF uses 7-digit, SIH uses 6-digit, ANS uses 7-digit with check digit. Outer join without prior canonicalization produces silent row loss or cartesian explosion. normalize_cod_ibge() must be applied in every source parser before any join; assert len(merged) == 5570 after every merge operation.

4. **IFGF missingness is not-at-random (~420 municipalities per year)** — non-submitters are the worst-governed municipalities, creating compound selection bias if dropped. Use multiple imputation with auxiliary variables (GDP, region, population) for IFGF D1; present complete-case analysis as sensitivity check; map geographic distribution of missingness.

5. **IDHM is only available at Census years, not annually** — using 2022 IDHM as a time-varying panel dimension manufactures false temporal variation in D3. Replace with a time-varying proxy (PNAD-Contínua education indicators) or treat 2022 IDHM as a cross-sectional covariate with explicit documentation; do not interpolate between 2010 and 2022 census values.

6. **Within-year vs pooled min-max normalization** — the current _minmax() function does not enforce year-grouping; if called on the pooled panel it silently produces pooled normalization, making temporal trend analyses meaningless. Use panel.groupby('year').transform(_minmax) exclusively; assert each year's min = 0 and max = 1 per dimension after normalization.

7. **PySUS DBC conversion fails silently on macOS** — blast-dbf (the underlying binary) returns False rather than raising an exception on macOS; the pipeline may proceed as if conversion succeeded while producing no parquet output. Assert output parquet file exists with non-zero size after every DBC conversion; add pre-flight shutil.which('blast-dbf') check.

---

## Implications for Roadmap

Based on cross-research analysis, a 5-phase structure is recommended. Data completeness is an absolute blocker for all analysis work — do not begin any regression or ML phase until all 8 data sources are in SQLite and validated. The architecture research identifies 8 existing gaps that must be closed in Phase 1 before any source acquisition work begins.

### Phase 1: Foundation and Infrastructure
**Rationale:** The single biggest risk to timeline is silent data corruption from municipality code mismatches and missing validation gates. These are invisible bugs that propagate through all downstream stages. The normalize_cod_ibge() utility and validation gate must exist before the first source parser is written. Python must be upgraded to 3.12 and uv lockfile established before any other dependency is added.
**Delivers:** Reproducible environment (pyproject.toml + uv.lock), shared database/utils.py with normalize_cod_ibge(), database/validation.py gate, IBGE 2023 municipality reference file (5,570 cod_ibge values), AMC temporal crosswalk for boundary harmonization.
**Addresses:** STROBE flow diagram requirement, RECORD database description requirements, data dictionary skeleton.
**Avoids:** Pitfall 13 (silent merge failures), Pitfall 16 (municipality code drift), Pitfall 7 (normalization scope ambiguity if patterns are set correctly from the start).

### Phase 2: Data Acquisition and Parsing (all 8 sources)
**Rationale:** All 6 LCoGS indicators and all 8 CIMI dimensions depend on distinct source data. Sources are independent of each other and can be developed in parallel, but none of the analysis phases can begin until this phase is complete. The existing SIH batch downloader covers one source; 5 more sources have no extraction code at all.
**Delivers:** Complete raw data corpus in data_sources/raw/ and normalized Parquet in data_sources/processed/ for: SIH (full 12-month annualized), CNES (professionals + facilities), IBGE SIDRA (GDP + population), IPEA IDHM / IVS proxy, FIRJAN IFGF, ANS beneficiary (quarterly average, not December snapshot), RENAVAM, SIOPS, IBGE Census 2022.
**Uses:** pysus 1.0.1, datasus-fetcher 0.4.1, sidrapy 0.1.4, ipeadatapy 0.1.9, requests >=2.32, openpyxl.
**Avoids:** Pitfall 18 (PySUS macOS silent failure — assert parquet output existence), Pitfall 10 (ANS December snapshot — average Q1–Q4), Pitfall 9 (IBGE GDP 2-year lag — log last available year and flag 2023 as imputed), Pitfall 3 (IDHM census-only — use IVS or PNAD proxy instead).

### Phase 3: Panel Assembly and Validation
**Rationale:** The validation gate must run after all sources are parsed and before any dimension computation. This is the last point at which data quality errors can be caught before they propagate into CUDS scores and regression results. Municipality code audit, range checks, and duplicate detection must all pass before the merge proceeds.
**Delivers:** validation_report.json for all sources, data_sources/quarantine/ for flagged rows, merged_YYYY.parquet (one row per municipality-year), icskg_br.sqlite with municipal_health table (50,130 rows asserted), deflated monetary series (SIOPS and GDP to constant 2023 BRL), IFGF multiple imputation for ~420 MNAR municipalities per year.
**Implements:** Validation Gate (Layer 3) and Aggregation + Merge (Layer 4) from architecture.
**Avoids:** Pitfall 13 (silent merge failures — assert 5,570 rows per year), Pitfall 6 (IFGF MNAR — multiple imputation), Pitfall 11 (RENAVAM outliers — 99th percentile top-code), Pitfall 14 (SIOPS over-reporting — 99th percentile cap), Pitfall 12 (CNES ghost facilities — validate against SIH activity).

### Phase 4: Core Analysis (CUDS, LCoGS, Regressions)
**Rationale:** This is the study's analytical core. It cannot begin until the panel is complete and validated. CUDS computation with the correct geometric mean (with floor offset) must precede all regression work. All 6 LCoGS indicators must be computed before the primary hypothesis tests can run.
**Delivers:** dimension_scores table in SQLite (D1–D9 + CUDS per municipality-year), lcogs_indicators table (L1–L6), primary two-way fixed-effects panel regressions (CUDS → each LCoGS outcome with cluster-robust SEs), Hausman test results, sensitivity analyses (arithmetic vs geometric mean; missing-dimension exclusion), descriptive statistics tables.
**Uses:** linearmodels 7.0 (PanelOLS with entity and time FE), scikit-learn >=1.6, xgboost >=2.1, geopandas 1.1.3 (Haversine distance matrix cached to Parquet).
**Avoids:** Pitfall 2 (geometric mean zero collapse — floor offset + NaN exclusion), Pitfall 7 (within-year normalization — groupby('year').transform()), Pitfall 5 (POMR labeled as in-hospital only), Pitfall 8 (CNES double-counting — deduplicate on CNS identifier), Pitfall 4 (SIH treatment vs residence municipality — compute both, use residence for primary).

### Phase 5: Publication Output and Submission Package
**Rationale:** This phase converts analytical outputs into submission-ready artifacts. It depends on all prior phases completing correctly. The STROBE/RECORD compliance checklists are documentation work that requires all computed outputs to exist. Zenodo archiving requires a reproducible pipeline (Phase 1 prerequisite is already satisfied).
**Delivers:** 4 publication-ready figures (CUDS choropleth map, CUDS trend, LCoGS regional heatmap, main regression forest plot), 8+ publication-ready tables, SHAP beeswarm plots, Moran's I spatial autocorrelation test, STROBE checklist (22 items), RECORD checklist (13 items), STROBE-Equity framing, data dictionary (complete), missing data summary table, manuscript Methods/Limitations sections, Zenodo DOI + public GitHub release.
**Uses:** matplotlib >=3.9, seaborn >=0.13, SciencePlots >=2.1, geobr 0.2.2, shap library.
**Avoids:** Pitfall 1 (SIH private blindspot — explicit Limitations language), Pitfall 17 (ecological fallacy — STROBE-E interpretation caveat, confounding controls for GDP and region).

### Phase Ordering Rationale

- Phase 1 before Phase 2: normalize_cod_ibge() must exist before the first parser writes Parquet; writing parsers without it creates technical debt that is expensive to retrofit across 8+ files.
- Phase 2 before Phase 3: cannot validate or merge what has not yet been downloaded and parsed; sources can be developed in parallel but all must complete before merge.
- Phase 3 before Phase 4: the validated, deflated, imputed panel is the only valid input for dimension computation; computing CUDS from an unvalidated panel would require recomputing everything after bugs are found.
- Phase 4 before Phase 5: publication outputs depend on all computed results; figures and tables are generated last.
- CUDS computation (Phase 4) before regression: the geometric mean floor offset and within-year normalization are correctness requirements, not optimizations — getting them wrong means all downstream regression results are invalid.

### Research Flags

Phases likely needing deeper research or validation during planning:
- **Phase 2 (SIOPS acquisition):** No Python library exists; the download path via portalfns.saude.gov.br requires hands-on testing to confirm file format and structure before committing to a parser design. Confidence is LOW.
- **Phase 2 (RENAVAM acquisition):** CSV file structure is undocumented in research; requires validation against actual downloaded files before implementing the parser. Confidence is LOW.
- **Phase 3 (IFGF multiple imputation):** The specific auxiliary variables and imputation method (mice, fancyimpute) should be validated against the missingness structure before implementation. MEDIUM confidence.
- **Phase 4 (IDHM annual proxy selection):** Whether PNAD-Contínua education indicators or IPEA IVS is more appropriate as the D3 time-varying proxy requires a data availability check before Phase 2 acquisition begins. This is a design decision that affects what is downloaded in Phase 2.

Phases with well-documented patterns (standard execution, skip research-phase):
- **Phase 1:** Environment setup, utility functions, and validation patterns are fully specified in architecture research.
- **Phase 3 (DuckDB SIH aggregation):** DuckDB SQL patterns for Parquet aggregation are well-documented; the architectural decision is already made.
- **Phase 4 (linearmodels PanelOLS):** Linearmodels 7.0 API and fixed-effects regression patterns are standard econometrics; no research needed.
- **Phase 5 (figure generation):** matplotlib/seaborn/SciencePlots patterns are well-documented.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All critical libraries verified via PyPI official pages April 2026; version constraints derived from documented breaking changes |
| Features | MEDIUM-HIGH | STROBE/RECORD requirements from EQUATOR Network (HIGH); BMJ Global Health specific requirements inferred from editorial policy patterns (MEDIUM); LCoGS definitions from Utstein Consensus Report (HIGH) |
| Architecture | HIGH | Grounded in direct codebase inspection of existing pipeline files + peer-reviewed DATASUS pipeline literature |
| Pitfalls | HIGH | All critical pitfalls sourced from peer-reviewed literature on DATASUS limitations (PMC10508673), CNES data quality, and composite index methodology |

**Overall confidence:** HIGH

### Gaps to Address

- **IDHM annual proxy decision:** Must be resolved before Phase 2 acquisition begins. Options are PNAD-Contínua education indicators, IPEA IVS, or treating 2022 IDHM as a cross-sectional covariate. This affects what is downloaded in Phase 2 and which dimension specification is documented in Methods.
- **SIOPS and RENAVAM file formats:** Both sources are flagged LOW confidence. A hands-on format validation run (download one year, inspect structure) should happen at the start of Phase 2 before full acquisition is planned.
- **SIH private sector supplementation:** Whether ANS SIP (Sistema de Informações de Produtos) data can be downloaded and linked to produce a supplementary total-sector LCoGS-3 estimate is unverified. If available, it substantially strengthens the paper; if not available, the limitation must be documented more prominently.
- **DBC conversion on macOS:** The PySUS blast-dbf macOS compatibility issue (Pitfall 18) should be tested in the development environment before the full SIH acquisition begins. A Docker-based environment may be required.
- **Municipality boundary harmonization crosswalk:** The AMC crosswalk source (geobr R package or Ehrl's dataset) must be confirmed accessible in the Python environment at Phase 1. If geobr Python 0.2.2 does not provide the temporal crosswalk, the R version or a static CSV must be used instead.

---

## Sources

### Primary (HIGH confidence)
- PySUS PyPI + GitHub releases: https://pypi.org/project/pysus/ — version compatibility, DBC conversion behavior
- Limitations of DATASUS SIH (PMC10508673): https://pmc.ncbi.nlm.nih.gov/articles/PMC10508673/ — critical pitfalls 1, 4, 5, 8
- LCoGS Utstein Consensus Report (PMC8415575): https://pmc.ncbi.nlm.nih.gov/articles/PMC8415575/ — LCoGS indicator definitions
- linearmodels PyPI: https://pypi.org/project/linearmodels/ — v7.0, Production/Stable, Oct 2025
- STROBE Statement: https://www.strobe-statement.org/checklists/ — 22-item checklist requirements
- RECORD Statement (PMC4595218): https://pmc.ncbi.nlm.nih.gov/articles/PMC4595218/ — 13-item extension
- DuckDB PyPI: https://pypi.org/project/duckdb/ — v1.5.1 confirmed March 2026
- Bellwether Procedures Brazil (World Journal of Surgery): https://link.springer.com/article/10.1007/s00268-020-05607-x — LCoGS-1 methodology
- Existing codebase: database/pipeline.py, database/build_database_v2.py, analysis/icskg_analysis_pipeline.py, extract_lcogs1.py — architecture gaps

### Secondary (MEDIUM confidence)
- BMJ Global Health editorial policy — inferred from open access data availability standards and STROBE-Equity 2024 extension
- Systematic review of LCoGS indicators 2025 (BJS): https://academic.oup.com/bjs/article/113/3/znaf289/8505882
- RECORD adherence meta-epidemiologic study 2025: https://www.sciencedirect.com/science/article/pii/S0895435625002094 — identifies most commonly missing items
- geobr Python PyPI: https://pypi.org/project/geobr/ — v0.2.2, "maturing" status
- Reproducible pipeline with PySUS (RSD Journal 2024): https://rsdjournal.org/rsd/article/view/50704

### Tertiary (LOW confidence)
- SIOPS download portal: https://portalfns.saude.gov.br/siops/siops-downloads/ — file format unverified, requires hands-on testing
- RENAVAM open data: https://dados.transportes.gov.br/dataset/registro-nacional-de-veiculos-automotores-renavam — CSV structure undocumented in research

---
*Research completed: 2026-04-01*
*Ready for roadmap: yes*
