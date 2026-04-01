<!-- GSD:project-start source:PROJECT.md -->
## Project

**ICSKG-BR**

The ICSKG-BR (Index of Cities' Smartness & Knowledge for Global Surgery — Brazil) is a longitudinal ecological panel study that operationalizes the IESE Cities in Motion Index (CIMI) 9-dimension framework as a Composite Urban Development Score (CUDS) and validates it against Lancet Commission on Global Surgery (LCoGS) indicators across all 5,570 Brazilian municipalities from 2015 to 2023. It produces a 50,130-observation panel dataset (5,570 municipalities × 9 years) for publication in BMJ Global Health.

**Core Value:** A reproducible, publicly-sourced database that proves whether municipal urban development predicts surgical system performance — the first study in any country to cross-reference urban development composite indices with surgical indicators at the subnational level.

### Constraints

- **Data availability**: All sources must be publicly available Brazilian government data (Lei de Acesso à Informação, Law 12.527/2011)
- **Tech stack**: Python (pandas, PySUS, scikit-learn, XGBoost), DuckDB/MotherDuck, matplotlib/seaborn
- **Temporal scope**: 2015–2023 (9 years) — balances data availability with trend analysis
- **Reproducibility**: Pipeline must be fully idempotent; all outputs deterministic given same inputs
- **Privacy**: No individual-level identifiers; municipality-level aggregates only
- **Reporting**: STROBE + RECORD compliance required for submission
<!-- GSD:project-end -->

<!-- GSD:stack-start source:codebase/STACK.md -->
## Technology Stack

## Languages
- Python 3.9+ - All data processing, ETL pipelines, analysis, and database operations
## Runtime
- CPython 3.9+ (or later)
- Standard library: `pathlib`, `argparse`, `logging`, `json`, `sqlite3`, `ftplib`, `gzip`, `hashlib`, `io`, `time`, `os`, `sys`, `multiprocessing`, `functools`, `datetime`, `urllib.parse`
- pip (standard Python package installer)
- Lockfile: Not present - dependencies listed in README.md only
## Frameworks & Core Libraries
- `pandas` - DataFrames, CSV/Excel I/O, data aggregation, merging
- `numpy` - Numerical operations, array processing, NaN handling
- `openpyxl` - Excel file reading/writing (.xlsx)
- `pyarrow` - Parquet file format support
- `gzip` - Gzip compression/decompression for DBC files
- `sqlite3` - SQLite database creation and management (location: `database/build_database_v2.py`)
- `duckdb` - Optional analytical database (mentioned in README as optional)
- `requests` - HTTP downloads from ANS open-data portal (location: `scripts/download_ans.py`, lazy-imported with error handling)
- `pysus` - DBC file conversion (for DATASUS SIH/CNES format decoding)
- `geopandas` - Geospatial analysis and shapefile handling (location: `extract_lcogs1.py` for mapping)
## Configuration
- Configurable via command-line arguments (`argparse`)
- No .env file required for core functionality
- Defaults: data sources auto-discovered from `data_sources/` directory
- Start/end dates (year-month): `--start 2013-01 --end 2024-12`
- Output directories: `--data-dir`, `--processed-dir`, `--db-dir`, `--out-dir`
- Worker count for parallel processing: `--workers` (default varies by stage)
- Specific UF codes: `--ufs SP RJ MG`
- No build system (pure Python scripts)
- Scripts invoked directly: `python script.py [args]`
## Platform Requirements
- Python 3.9+ with pip
- curl/wget or native Python for HTTP downloads
- FTP client capability (built-in via `ftplib`)
- Adequate disk space for raw DATASUS files (100+ GB for full historical SIH/CNES)
- Linux/macOS/Windows with Python 3.9+
- Network access to:
- SQLite or DuckDB for database storage
## Key Dependencies
- `pandas` [1.x+] - Core data manipulation and aggregation
- `numpy` [1.x+] - Numerical operations for index normalization
- `openpyxl` [3.x+] - IFGF Excel file reading (bundled: `data_sources/Evolucao_por_Indicador_2013_a_2024_IFGF_2025.xlsx`)
- `pyarrow` [5.x+] - Parquet columnar storage for SIH/CNES processed data
- `sqlite3` - SQLite database backend (stdlib)
- `requests` [2.x+] - HTTP downloads from ANS (lazy-imported)
- `pysus` [0.x+] - DBC to CSV/Parquet conversion (for raw DATASUS format)
- `geopandas` [0.x+] - Geospatial mapping for LCoGS-1 analysis
- `duckdb` [0.x+] - Analytical OLAP database alternative to SQLite
## External Integrations
- Host: `ftp.datasus.gov.br`
- Protocol: FTP (custom ftplib implementation)
- Files: SIH (RD*.dbc), CNES (ST*.dbc)
- Format: DBC (compressed DBF binary format)
- Frequency: Monthly, 27 state files per month per source
- Base URL: `https://dados.ans.gov.br/operadoras/informacoes_de_beneficiarios/`
- Format: CSV (latin-1 encoding, semicolon-delimited)
- Frequency: Quarterly (months 3, 6, 9, 12)
- Client: `requests` library with retry logic
- Auto-downloaded population estimates and municipality shapefiles
- Used by: `extract_lcogs1.py` for geospatial mapping
## Architecture Overview
- **Modular design:** Separate scripts for each data source (SIH, CNES, ANS, IFGF)
- **Multi-process parallelism:** SIH batch processor uses `multiprocessing` for per-state conversion
- **Retry logic:** FTP and HTTP downloads support retry-with-backoff
- **Lazy imports:** Optional dependencies (requests, pysus, geopandas) imported only when needed
- **Idempotent processing:** Parquet partition-by-state allows resumable downloads and processing
## Typical Workflow
# 1. Download raw data (optional - can use bundled data)
# 2. Process and aggregate
# 3. Build database
# 4. Generate analysis outputs
# 5. Create LCoGS-1 maps
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

## Naming Patterns
- Snake case with descriptive names: `extract_lcogs1.py`, `sih_batch_v2.py`, `icskg_analysis_pipeline.py`
- Suffix versioning for iterations: `v2`, `v3` (e.g., `build_database_v2.py`, `sih_batch_v2.py`)
- Clear module purpose in name (e.g., `continue_raw_download.py`, `download_ans.py`)
- Snake case throughout
- Private functions prefixed with underscore: `_process_uf()`, `_ftp_download()`, `_zscore()`, `_minmax()`, `_connect_ftp()`, `_dbc_to_parquet()`
- Verb-first naming convention for function actions: `load_sih_year()`, `fetch_ibge_population()`, `flag_bellwether()`, `compute_rates()`, `generate_maps()`, `download_competence()`, `parse_csv()`, `merge_downloads()`
- Clear, explicit names: `collect_parquet_files()`, `upsert_municipal_health()`, `export_metadata_json()`
- Snake case for all variables: `processed_dir`, `raw_dir`, `output_dir`, `max_retries`, `skip_existing`
- Domain-specific abbreviations acceptable: `sih_df`, `pop_df`, `ans_df`, `gdf` (geodataframe), `con` (connection)
- All-caps for module-level constants: `LAPAROTOMY_DIAG`, `CAESAREAN_DIAG`, `MAX_RETRIES`, `DATASUS_FTP_HOST`, `UF_CODES`, `CIMI_DIMENSIONS`
- Temporary iteration variables: `f` (file), `uf` (state), `year`, `month`, `attempt`, `label`
- Standard type hints on function signatures: `year: int`, `path: Path`, `data: pd.DataFrame`
- Complex return types: `-> pd.DataFrame`, `-> list[str]`, `-> dict[str, Path | None]`
- Optional parameters with defaults: `timeout: int = 120`, `workers: int = 1`, `skip_existing: bool = True`
## Code Style
- PEP 8 compliant
- Line width follows standard Python conventions (~88 characters in practice)
- 4-space indentation throughout
- Uses `# noqa: BLE001` to suppress bare exception linting warnings (standard across codebase for defensive exception handling)
- Uses `# noqa: PLC0415` to allow local imports inside functions for optional dependencies
- Pragmatic approach: linting suppressions used where domain logic requires broader exception handling
- Blank lines separate logical sections within functions
- Section banners using dashes for readability: `# ---------------------------------------------------------------------------` (65 dashes)
- Double newlines between top-level definitions
## Import Organization
- All code uses absolute paths via `pathlib.Path`
- No path aliases; imports use direct module paths
- Dynamic imports for optional dependencies: `from scripts.sih_batch_v2 import process_month` (inside functions to defer dependency checks)
## Error Handling
- Broad exception handling: `except Exception as exc:  # noqa: BLE001` used for defensive error catching
- Specific exception handling where semantically important:
- Error handling includes logging: `logger.error("message: %s", exc)` or `logger.warning("message: %s", exc)`
- Graceful degradation: operations often log and continue rather than failing hard (synthetic data generation fallback in `extract_lcogs1.py`)
- Custom error messages on re-raise: `raise RuntimeError("Failed to download ... after N attempts") from exc`
- Uses `from exc` to preserve exception context for debugging
- Explicit error messages that include attempt counts, URLs, or file paths
## Logging
- `logger.info()`: Major milestones, successful operations, data counts
- `logger.warning()`: Graceful degradation, missing optional dependencies, skipped operations
- `logger.error()`: Recoverable failures, retried operations, detailed exception context
- `logger.debug()`: Partition skips, deduplication counts (only when `skip_existing=True` or `before != after`)
- Always use %-style formatting, never f-strings
- Include context: file paths, counts, years/months, exception details
- Status indicators in info messages: checkmarks (`✓`) and progress indicators (`▶`)
- Banner messages for major pipeline stages: `logger.info("=== Stage Name ===")` or `logger.info("─" * 60)`
## Comments
- Section separators (major logical divisions): `# ---------------------` style banners
- Domain-specific code or complex logic explanations
- Configuration constants with units: `RETRY_DELAY = 10  # seconds`
- ICD code mappings and medical terminology explanations
- Comments are minimal—code clarity is preferred over verbosity
- Module-level docstrings: extensive, include purpose, outputs, data requirements, and usage examples
- Function docstrings: Present on all public functions, some private functions
- Format: Triple-quoted strings with section headers (Outputs, Data requirements, Usage, Parameters, Returns)
- Example from `extract_lcogs1.py`:
- Longer docstrings use structured format:
## Function Design
- Functions range from 5–50 lines
- Complex orchestration functions (main ETL pipelines) may reach 60–100 lines
- Single responsibility: each function does one logical task
- Maximum 8–10 parameters common for data processing functions
- Use default parameters for optional behaviors: `skip_existing: bool = True`, `workers: int = 1`
- Path objects (`Path`) preferred over strings for file operations
- Keyword-only arguments for optional parameters in longer signatures
- Explicit return types in annotations
- DataFrame returns for data transformations
- Path returns for file operations indicating output location
- `None` returns for side-effect operations (writing to disk)
- Tuple returns for operations with multiple outputs: `-> tuple[int, int]` (e.g., year, month pairs)
- Integer counts for data loading operations (number of rows/files processed)
## Module Design
- No explicit `__all__` definitions
- Modules are executable scripts with `if __name__ == "__main__": sys.exit(main())`
- Clear public API: `main(argv=None)` as entry point with argument parsing
- Private function prefix (`_`) used consistently
- Not used in this codebase
- Each module is self-contained with internal utility functions
## Special Conventions
- All paths use `pathlib.Path` with `Path(string)` construction
- Directory creation pattern: `path.mkdir(parents=True, exist_ok=True)`
- Safe file checks: `path.exists()`, `path.stat().st_size`
- Use `pd.to_numeric(..., errors="coerce")` for safe numeric conversion
- Type casting in pandas operations: `astype(str)`, `astype(int)`, `astype(float)`
- String normalization: `.str.strip()`, `.str.upper()`, `.str[:N]` for prefixes
- Constants defined at module level (uppercase)
- FTP credentials and file patterns stored as module-level strings and lists
- DuckDB/SQLite connection patterns encapsulated in functions returning connection objects
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

## Pattern Overview
- Stage-based orchestration with independent extraction modules per data source
- Data aggregation via municipality-level (cod_ibge) merging
- Pandas-driven transformations with optional DuckDB/SQLite persistence
- Dimensional computation pattern for composite index calculation
- Modular decomposition: scripts (source-specific), database (aggregation), analysis (dimension computation), extraction (specialized analysis)
## Layers
- Purpose: Source-specific data acquisition from Brazilian health/governance systems
- Location: `scripts/` directory
- Contains: Download and parsing functions for SIH, CNES, ANS, IFGF data sources
- Depends on: External APIs (DATASUS, ANS, FIRJAN) and local file system
- Used by: `database/pipeline.py` for orchestration
- Purpose: Normalize, standardize, and join disparate data sources at municipality level
- Location: `database/pipeline.py` (transform_merge function, lines 114-174)
- Contains: Parquet file reading, column renaming, outer joins on cod_ibge
- Depends on: Extraction layer outputs (parquet/CSV/XLSX files)
- Used by: Database load layer to persist merged results
- Purpose: Store aggregated municipality-level data in queryable relational databases
- Location: `database/build_database_v2.py`
- Contains: SQLite schema DDL, dimension metadata seeding, parquet-to-SQL ingestion, optional DuckDB mirror
- Depends on: Processed parquet files from transform layer
- Used by: Analysis and extraction specialization layers
- Purpose: Calculate 9/9 CIMI dimensions from disaggregated source data
- Location: `analysis/icskg_analysis_pipeline.py`
- Contains: Dimension-specific compute functions (compute_d1, compute_d6), panel construction, figure/table generation
- Depends on: Raw/processed data files (IFGF Excel, ANS CSV, SIH parquet)
- Used by: Reporting and visualization
- Purpose: Domain-specific secondary analysis (e.g., surgical system capacity assessment)
- Location: `extract_lcogs1.py`
- Contains: LCoGS-1 bellwether procedure classification, procedure rate calculation, geospatial mapping
- Depends on: SIH processed parquet, IBGE population API, shapefile data
- Used by: Output generation for policy/research
## Data Flow
- **Source of Truth**: Raw data files in `data_sources/raw/` (immutable)
- **Intermediate State**: Processed parquet files in `data_sources/processed/` (can be regenerated)
- **Final State**: SQLite/DuckDB database (`database/icskg_br.sqlite`, `database/icskg_br.duckdb`)
- **Outputs**: Figures, tables, CSVs in `analysis/results/` and `output/`
- **Metadata**: `database/database_metadata.json` (dimension definitions, source info)
## Key Abstractions
- Purpose: Encapsulate source-specific download/parse logic
- Examples: `extract_sih()`, `extract_cnes()`, `extract_ans()`, `extract_ifgf()` in `database/pipeline.py`
- Pattern: Each function takes year/month (or path), returns output file path; errors are logged and handled gracefully
- Purpose: Represent a single CIMI dimension with metadata (label, source, normalization, weight)
- Examples: Stored in `database/database_metadata.json`, computed in `analysis/icskg_analysis_pipeline.py`
- Pattern: Equal-weight composite index (ICSKG_score = mean of D1–D9); dimensions are min-max normalized to [0, 1]
- Purpose: Unite heterogeneous data sources on common spatial unit
- Examples: cod_ibge (IBGE 7-digit municipality code), Cod_IBGE (IFGF Excel), CD_MUNICIPIO (ANS CSV)
- Pattern: Normalize column names in `transform_merge()` to consistent "cod_ibge" before outer join
- Purpose: Organize processed data by temporal granularity for scalability
- Examples: `sih_YYYYMM.parquet`, `cnes_YYYYMM.parquet`, `merged_YYYYMM.parquet`
- Pattern: Year-month encoded in filename; enables incremental processing and parallel loading
## Entry Points
- Location: `database/pipeline.py` (main function, lines 296–341)
- Triggers: `python database/pipeline.py --start 2013-01 --end 2024-12` or `--year-month YYYY-MM`
- Responsibilities: Parse CLI args, iterate months, call `run_pipeline()` for each, log progress
- Location: `analysis/icskg_analysis_pipeline.py` (main function, lines 321–354)
- Triggers: `python analysis/icskg_analysis_pipeline.py [--data-dir] [--out-dir]`
- Responsibilities: Load source data, compute 9 dimensions, build panel, generate figures and tables
- Location: `extract_lcogs1.py` (main function, implicit)
- Triggers: `python extract_lcogs1.py [--year 2023] [--out-dir output]`
- Responsibilities: Load SIH year, classify bellwether procedures, compute rates, generate maps
- Location: `scripts/continue_raw_download.py`, `scripts/download_ans.py`, `scripts/sih_batch_v2.py`
- Triggers: Called by extraction layer or run standalone
- Responsibilities: Download from external APIs, parse DBC/CSV, write to parquet
## Error Handling
- **Extraction**: Each `extract_*()` function wrapped in try-except in `run_pipeline()` (lines 226–248); errors logged, results marked None
- **Transform**: Missing source frames logged as warning; empty frames skipped (line 141–142); if all sources missing, empty output written (lines 153–158)
- **Database**: DuckDB load wrapped in try-except; falls back to warning if duckdb not installed (lines 184–196)
- **Analysis**: Missing IFGF/ANS files trigger FileNotFoundError with clear guidance; synthetic placeholder data generated for testing (lines 149–161)
- **Parquet Read**: Per-file exception handling in `load_parquet_to_df()` (lines 154–157); skips unreadable files, continues with others
## Cross-Cutting Concerns
- Pattern: Standardized format via `logging.basicConfig()` in each module (timestamp, level, message)
- Key points: Stage banners (`_stage_banner()`), progress indicators (▶ YYYY-MM), row counts on load/upsert
- Location: All modules use root logger configured at module import
- Municipality Code: Normalized to string (dtype handling in pandas read functions)
- Year/Month: Integer parsing with bounds checking in `_iter_months()` (lines 273–289)
- Dimension Values: Min-max normalization ensures [0, 1] range (functions `_minmax()`, `_zscore()`)
- ICD-10 Codes: String prefix matching for bellwether procedure classification (`BELLWETHER_DIAG` set in `extract_lcogs1.py`)
- No explicit auth in codebase; relies on open DATASUS/ANS/FIRJAN public APIs
- IFGF file must be manually downloaded and placed in `data_sources/`
<!-- GSD:architecture-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd:quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd:debug` for investigation and bug fixing
- `/gsd:execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd:profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
