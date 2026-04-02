# Phase 4: Panel Assembly & Validation - Context

**Gathered:** 2026-04-02
**Status:** Ready for planning
**Mode:** Auto-generated (autonomous workflow — infrastructure phase)

<domain>
## Phase Boundary

Merge all extracted data sources into a validated, deflated, imputed 50,130-row municipality-year panel in SQLite. Includes IPCA monetary deflation, validation gate enforcement, municipality-year merge, IFGF multiple imputation, and missingness documentation per RECORD item 12.1.

</domain>

<decisions>
## Implementation Decisions

### Monetary Deflation
- Deflate SIOPS and GDP per capita to constant 2023 BRL using IPCA health sub-index
- Log deflation factors in an auditable deflation table
- IPCA indices sourced from IBGE SIDRA or BCB SGS API

### Merge Strategy
- Outer join all sources on (cod_ibge, year) — preserve all municipalities even with missing data
- Assert 5,571 rows per year after merge (updated IBGE count)
- normalize_cod_ibge() applied to all sources before join
- apply_amc_crosswalk() for temporal harmonization

### Validation
- validate_dataframe() on each source before merge
- validation_report.json with per-source quality metrics
- Quarantine directory for flagged rows

### IFGF Imputation
- ~420 municipalities/year are MNAR (Missing Not At Random)
- Multiple imputation using auxiliary variables: GDP, region, population
- Method and results logged in PANL-05-imputation.log

### SQLite Persistence
- municipal_health table with exactly 50,130 rows (5,571 × 9 years) target
- Schema matches documented DDL from database/build_database_v2.py
- dimension_metadata and municipality_lookup tables

### Missingness Documentation
- PANL-06-missingness.csv: missingness rate per variable per year
- Satisfies RECORD reporting item 12.1

### Claude's Discretion
- IPCA source selection (SIDRA vs BCB SGS)
- Multiple imputation library (scikit-learn IterativeImputer vs statsmodels MICE)
- SQLite schema design for new columns from Phase 3 sources
- Whether to refactor build_database_v2.py or create build_database_v3.py

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- database/build_database_v2.py — existing SQLite builder (needs updating for new sources)
- database/pipeline.py — transform_merge() exists, 14 extraction stages wired
- database/validation.py — validate_dataframe() ready
- database/utils.py — normalize_cod_ibge(), load_ibge_municipios()

### Integration Points
- All Phase 2+3 extractors produce Parquet in data_sources/processed/
- pipeline.py transform_merge() needs expansion for 7 new sources
- build_database_v2.py needs schema update for all CIMI dimensions

</code_context>

<specifics>
## Specific Ideas

- Existing build_database_v2.py has SQLite DDL and metadata seeding — reference its patterns
- transform_merge() in pipeline.py already does outer joins — extend for new sources
- IFGF MNAR pattern: ~420 municipalities consistently missing across years (same set)

</specifics>

<deferred>
## Deferred Ideas

- DuckDB analytical mirror (optional, not required for v1.0)
- MotherDuck cloud deployment

</deferred>
