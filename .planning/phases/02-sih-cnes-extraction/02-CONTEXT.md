# Phase 2: SIH & CNES Extraction - Context

**Gathered:** 2026-04-01
**Status:** Ready for planning

<domain>
## Phase Boundary

Read FIOCRUZ BigData ETLSIH and ETLCNES CSV files from NAS (read-only), parse and filter, normalize municipality codes, run through validation gate, and write processed Parquet files. Produces both procedure-level detail (for LCoGS POMR calculation) and municipality-year aggregates. Originals are NEVER modified.

</domain>

<decisions>
## Implementation Decisions

### SIH Processing Strategy
- SIH data is already downloaded on NAS as FIOCRUZ BigData CSVs (NOT DATASUS DBC format)
- File naming pattern: `ETLSIH.ST_{UF}_{YEAR}_{MONTH}_t.csv` (e.g., `ETLSIH.ST_AC_2008_1_t.csv`)
- No DBC conversion or PySUS blast-dbf needed — direct CSV reading with pandas or DuckDB
- Refactor existing `scripts/sih_batch_v2.py` to read CSVs instead of DBC; keep multiprocess per-UF parallelization
- Read-only access to originals on NAS — pipeline MUST NOT modify, move, or delete source files
- If NAS not mounted during development, test with a small sample copied locally

### CNES Data Source & Filtering
- CNES data sourced from FIOCRUZ BigData ETLCNES (per D-08 from Phase 1) — currently being downloaded
- File format: CSV (similar pattern to ETLSIH)
- Professional CBO filtering: CBO-2002 codes — surgeons (2231-xx), anesthesiologists (2232-xx), obstetricians (2235-xx)
- Facility bellwether criteria: surgical center OR obstetric center OR ≥10 inpatient beds (Lancet Commission definition)
- CNS deduplication: per municipality-year (a professional working in 2 hospitals counts once per municipality)

### Output Schema
- SIH output: per-state monthly Parquet files (`data_sources/processed/sih/SP_202301.parquet`)
- SIH keeps ~15 surgical columns: MUNIC_MOV, DIAG_PRINC, PROC_REA, VAL_TOT, MORTE, DT_INTER, DT_SAIDA, etc.
- SIH produces BOTH procedure-level Parquet AND municipality-year aggregates
- CNES output: two separate Parquets — `professionals.parquet` and `facilities.parquet` (different schemas)
- All processed files written to `data_sources/processed/sih/` and `data_sources/processed/cnes/` per config.yaml
- normalize_cod_ibge() applied to all municipality codes before writing
- validate_dataframe() run on each output before persistence

### Claude's Discretion
- Exact column selection from ETLSIH CSVs (must include columns needed for LCoGS-3/4/5/6)
- DuckDB vs pandas for CSV reading (DuckDB may be faster for 100+ GB corpus)
- Chunk size and memory management strategy
- How to handle the CNES download being in progress (skip CNES if not available, or wait)
- Test data strategy when NAS is not mounted

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `scripts/sih_batch_v2.py` — multiprocess SIH processor with column subsetting, idempotent output, per-UF parallelization. Needs refactoring from DBC to CSV reading.
- `scripts/continue_raw_download.py` — FTP download with resume. May not be needed since data is already downloaded.
- `database/utils.py` — normalize_cod_ibge(), rename_municipality_column(), load_ibge_municipios()
- `database/validation.py` — validate_dataframe() with quarantine mode
- `database/pipeline.py` — load_config() for NAS path resolution, extract_sih()/extract_cnes() stubs

### Established Patterns
- Per-UF multiprocessing with configurable worker count
- Column subsetting to reduce memory footprint
- Idempotent output (skip already-converted partitions)
- Parquet with pyarrow for columnar storage
- Logger with %-style formatting, section banners

### Integration Points
- `database/pipeline.py` extract_sih() and extract_cnes() stubs — wire in the new processors
- config.yaml `data_root` for NAS path resolution
- `database/utils.py` normalize_cod_ibge() for municipality code normalization
- `database/validation.py` validate_dataframe() as mandatory quality gate

</code_context>

<specifics>
## Specific Ideas

- FIOCRUZ BigData ETLSIH format uses pre-processed CSVs, not raw DATASUS DBC files
- File pattern: `ETLSIH.ST_{UF}_{YEAR}_{MONTH}_t.csv`
- The `_t` suffix likely indicates the "total" or complete table variant
- SIH columns from existing sih_batch_v2.py (SIH_COLS_KEEP) are a good starting point but need validation against ETLSIH CSV headers
- CNES from FIOCRUZ uses ETLCNES format — need to discover column names when download completes
- PolisPCDaS dataset (D-10 from Phase 1) available as supplementary validation source

</specifics>

<deferred>
## Deferred Ideas

- PolisPCDaS integration for cross-validation of extracted indicators (Phase 4 or later)
- SIH procedure cost analysis (Phase 6 LCoGS-5/6)
- CNES geocoding for bellwether hospital mapping (Phase 6 LCoGS-1)

</deferred>
