# Architecture

**Analysis Date:** 2026-04-01

## Pattern Overview

**Overall:** Multi-stage data pipeline with modular ETL (Extract-Transform-Load), dimensional analysis, and specialized geospatial processing.

**Key Characteristics:**
- Stage-based orchestration with independent extraction modules per data source
- Data aggregation via municipality-level (cod_ibge) merging
- Pandas-driven transformations with optional DuckDB/SQLite persistence
- Dimensional computation pattern for composite index calculation
- Modular decomposition: scripts (source-specific), database (aggregation), analysis (dimension computation), extraction (specialized analysis)

## Layers

**Data Extraction Layer:**
- Purpose: Source-specific data acquisition from Brazilian health/governance systems
- Location: `scripts/` directory
- Contains: Download and parsing functions for SIH, CNES, ANS, IFGF data sources
- Depends on: External APIs (DATASUS, ANS, FIRJAN) and local file system
- Used by: `database/pipeline.py` for orchestration

**Data Transformation & Merge Layer:**
- Purpose: Normalize, standardize, and join disparate data sources at municipality level
- Location: `database/pipeline.py` (transform_merge function, lines 114-174)
- Contains: Parquet file reading, column renaming, outer joins on cod_ibge
- Depends on: Extraction layer outputs (parquet/CSV/XLSX files)
- Used by: Database load layer to persist merged results

**Database Persistence Layer:**
- Purpose: Store aggregated municipality-level data in queryable relational databases
- Location: `database/build_database_v2.py`
- Contains: SQLite schema DDL, dimension metadata seeding, parquet-to-SQL ingestion, optional DuckDB mirror
- Depends on: Processed parquet files from transform layer
- Used by: Analysis and extraction specialization layers

**Analysis & Dimension Computation Layer:**
- Purpose: Calculate 9/9 CIMI dimensions from disaggregated source data
- Location: `analysis/icskg_analysis_pipeline.py`
- Contains: Dimension-specific compute functions (compute_d1, compute_d6), panel construction, figure/table generation
- Depends on: Raw/processed data files (IFGF Excel, ANS CSV, SIH parquet)
- Used by: Reporting and visualization

**Specialized Extraction Layer:**
- Purpose: Domain-specific secondary analysis (e.g., surgical system capacity assessment)
- Location: `extract_lcogs1.py`
- Contains: LCoGS-1 bellwether procedure classification, procedure rate calculation, geospatial mapping
- Depends on: SIH processed parquet, IBGE population API, shapefile data
- Used by: Output generation for policy/research

## Data Flow

**Pipeline Execution (Standard Path):**

1. **Download Stage** – Scripts download raw data from external APIs
   - `scripts/continue_raw_download.py`: Download SIH/CNES DBC files → `data_sources/raw/SIH/`, `data_sources/raw/CNES/`
   - `scripts/download_ans.py`: Download ANS CSV → `data_sources/raw/ANS/`
   - IFGF Excel file: Manual placement in `data_sources/`

2. **Parse Stage** – SIH-specific batch processing
   - `scripts/sih_batch_v2.py`: Convert DBC to parquet (chunked, parallel per UF) → `data_sources/processed/sih_YYYYMM.parquet`
   - CNES parsing delegated to `continue_raw_download.py`

3. **Orchestrate Stage** – Main ETL orchestration
   - `database/pipeline.py`: For each year-month, calls extraction stubs
   - Per-source extraction returns path to parquet/Excel/CSV file

4. **Transform Stage** – Multi-source merge
   - `database/pipeline.py` (transform_merge): Read 4 source files, normalize municipality column (Cod_IBGE → cod_ibge), outer join
   - Output: `data_sources/processed/merged_YYYYMM.parquet` (municipality-level wide format)

5. **Load Stage** – Database persistence
   - `database/build_database_v2.py`: Collect all merged parquet files
   - Create SQLite schema (3 tables: municipal_health, dimension_metadata, municipality_lookup)
   - Upsert rows into `municipal_health` table
   - Optional DuckDB mirror via sqlite_attach

6. **Analysis Stage** – Dimension computation
   - `analysis/icskg_analysis_pipeline.py`: Load IFGF Excel and ANS CSV directly
   - Compute D1 (fiscal governance), D6 (private coverage), others from merged sources
   - Build panel dataset (long format: cod_ibge, year, D1–D9, ICSKG_score)
   - Generate 4 figures (matplotlib) and 8 tables (CSV)

7. **Specialization Stage** – LCoGS-1 analysis
   - `extract_lcogs1.py`: Load SIH parquet files for target year
   - Classify procedures via ICD-10 diagnosis codes (laparotomy, caesarean, open fracture)
   - Calculate bellwether rates per municipality, compare to 5 000 per 100 000 benchmark
   - Generate maps (geopandas) and CSV outputs

**State Management:**

- **Source of Truth**: Raw data files in `data_sources/raw/` (immutable)
- **Intermediate State**: Processed parquet files in `data_sources/processed/` (can be regenerated)
- **Final State**: SQLite/DuckDB database (`database/icskg_br.sqlite`, `database/icskg_br.duckdb`)
- **Outputs**: Figures, tables, CSVs in `analysis/results/` and `output/`
- **Metadata**: `database/database_metadata.json` (dimension definitions, source info)

## Key Abstractions

**Extraction Abstraction:**
- Purpose: Encapsulate source-specific download/parse logic
- Examples: `extract_sih()`, `extract_cnes()`, `extract_ans()`, `extract_ifgf()` in `database/pipeline.py`
- Pattern: Each function takes year/month (or path), returns output file path; errors are logged and handled gracefully

**Dimension Abstraction:**
- Purpose: Represent a single CIMI dimension with metadata (label, source, normalization, weight)
- Examples: Stored in `database/database_metadata.json`, computed in `analysis/icskg_analysis_pipeline.py`
- Pattern: Equal-weight composite index (ICSKG_score = mean of D1–D9); dimensions are min-max normalized to [0, 1]

**Municipality Join Key:**
- Purpose: Unite heterogeneous data sources on common spatial unit
- Examples: cod_ibge (IBGE 7-digit municipality code), Cod_IBGE (IFGF Excel), CD_MUNICIPIO (ANS CSV)
- Pattern: Normalize column names in `transform_merge()` to consistent "cod_ibge" before outer join

**Parquet Partition Scheme:**
- Purpose: Organize processed data by temporal granularity for scalability
- Examples: `sih_YYYYMM.parquet`, `cnes_YYYYMM.parquet`, `merged_YYYYMM.parquet`
- Pattern: Year-month encoded in filename; enables incremental processing and parallel loading

## Entry Points

**CLI Orchestrator:**
- Location: `database/pipeline.py` (main function, lines 296–341)
- Triggers: `python database/pipeline.py --start 2013-01 --end 2024-12` or `--year-month YYYY-MM`
- Responsibilities: Parse CLI args, iterate months, call `run_pipeline()` for each, log progress

**Analysis Orchestrator:**
- Location: `analysis/icskg_analysis_pipeline.py` (main function, lines 321–354)
- Triggers: `python analysis/icskg_analysis_pipeline.py [--data-dir] [--out-dir]`
- Responsibilities: Load source data, compute 9 dimensions, build panel, generate figures and tables

**LCoGS-1 Extractor:**
- Location: `extract_lcogs1.py` (main function, implicit)
- Triggers: `python extract_lcogs1.py [--year 2023] [--out-dir output]`
- Responsibilities: Load SIH year, classify bellwether procedures, compute rates, generate maps

**Download Scripts:**
- Location: `scripts/continue_raw_download.py`, `scripts/download_ans.py`, `scripts/sih_batch_v2.py`
- Triggers: Called by extraction layer or run standalone
- Responsibilities: Download from external APIs, parse DBC/CSV, write to parquet

## Error Handling

**Strategy:** Try-catch-log with graceful degradation; missing sources are warned but pipeline continues.

**Patterns:**

- **Extraction**: Each `extract_*()` function wrapped in try-except in `run_pipeline()` (lines 226–248); errors logged, results marked None
- **Transform**: Missing source frames logged as warning; empty frames skipped (line 141–142); if all sources missing, empty output written (lines 153–158)
- **Database**: DuckDB load wrapped in try-except; falls back to warning if duckdb not installed (lines 184–196)
- **Analysis**: Missing IFGF/ANS files trigger FileNotFoundError with clear guidance; synthetic placeholder data generated for testing (lines 149–161)
- **Parquet Read**: Per-file exception handling in `load_parquet_to_df()` (lines 154–157); skips unreadable files, continues with others

## Cross-Cutting Concerns

**Logging:**
- Pattern: Standardized format via `logging.basicConfig()` in each module (timestamp, level, message)
- Key points: Stage banners (`_stage_banner()`), progress indicators (▶ YYYY-MM), row counts on load/upsert
- Location: All modules use root logger configured at module import

**Validation:**
- Municipality Code: Normalized to string (dtype handling in pandas read functions)
- Year/Month: Integer parsing with bounds checking in `_iter_months()` (lines 273–289)
- Dimension Values: Min-max normalization ensures [0, 1] range (functions `_minmax()`, `_zscore()`)
- ICD-10 Codes: String prefix matching for bellwether procedure classification (`BELLWETHER_DIAG` set in `extract_lcogs1.py`)

**Authentication:**
- No explicit auth in codebase; relies on open DATASUS/ANS/FIRJAN public APIs
- IFGF file must be manually downloaded and placed in `data_sources/`

---

*Architecture analysis: 2026-04-01*
