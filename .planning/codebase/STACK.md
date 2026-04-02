# Technology Stack

**Analysis Date:** 2026-04-01

## Languages

**Primary:**
- Python 3.9+ - All data processing, ETL pipelines, analysis, and database operations

## Runtime

**Environment:**
- CPython 3.9+ (or later)
- Standard library: `pathlib`, `argparse`, `logging`, `json`, `sqlite3`, `ftplib`, `gzip`, `hashlib`, `io`, `time`, `os`, `sys`, `multiprocessing`, `functools`, `datetime`, `urllib.parse`

**Package Manager:**
- pip (standard Python package installer)
- Lockfile: Not present - dependencies listed in README.md only

## Frameworks & Core Libraries

**Data Processing:**
- `pandas` - DataFrames, CSV/Excel I/O, data aggregation, merging
- `numpy` - Numerical operations, array processing, NaN handling

**File Format Support:**
- `openpyxl` - Excel file reading/writing (.xlsx)
- `pyarrow` - Parquet file format support
- `gzip` - Gzip compression/decompression for DBC files

**Database:**
- `sqlite3` - SQLite database creation and management (location: `database/build_database_v2.py`)
- `duckdb` - Optional analytical database (mentioned in README as optional)

**HTTP & Data Fetching:**
- `requests` - HTTP downloads from ANS open-data portal (location: `scripts/download_ans.py`, lazy-imported with error handling)

**Optional Tools (mentioned in README):**
- `pysus` - DBC file conversion (for DATASUS SIH/CNES format decoding)
- `geopandas` - Geospatial analysis and shapefile handling (location: `extract_lcogs1.py` for mapping)

## Configuration

**Environment:**
- Configurable via command-line arguments (`argparse`)
- No .env file required for core functionality
- Defaults: data sources auto-discovered from `data_sources/` directory

**Key Config Parameters:**
- Start/end dates (year-month): `--start 2013-01 --end 2024-12`
- Output directories: `--data-dir`, `--processed-dir`, `--db-dir`, `--out-dir`
- Worker count for parallel processing: `--workers` (default varies by stage)
- Specific UF codes: `--ufs SP RJ MG`

**Build/Development:**
- No build system (pure Python scripts)
- Scripts invoked directly: `python script.py [args]`

## Platform Requirements

**Development:**
- Python 3.9+ with pip
- curl/wget or native Python for HTTP downloads
- FTP client capability (built-in via `ftplib`)
- Adequate disk space for raw DATASUS files (100+ GB for full historical SIH/CNES)

**Production/Deployment:**
- Linux/macOS/Windows with Python 3.9+
- Network access to:
  - DATASUS FTP: `ftp://ftp.datasus.gov.br`
  - ANS open-data portal: `https://dados.ans.gov.br`
  - IBGE APIs (for population estimates, shapefiles)
- SQLite or DuckDB for database storage

## Key Dependencies

**Critical:**
- `pandas` [1.x+] - Core data manipulation and aggregation
- `numpy` [1.x+] - Numerical operations for index normalization
- `openpyxl` [3.x+] - IFGF Excel file reading (bundled: `data_sources/Evolucao_por_Indicador_2013_a_2024_IFGF_2025.xlsx`)

**Infrastructure:**
- `pyarrow` [5.x+] - Parquet columnar storage for SIH/CNES processed data
- `sqlite3` - SQLite database backend (stdlib)
- `requests` [2.x+] - HTTP downloads from ANS (lazy-imported)

**Optional:**
- `pysus` [0.x+] - DBC to CSV/Parquet conversion (for raw DATASUS format)
- `geopandas` [0.x+] - Geospatial mapping for LCoGS-1 analysis
- `duckdb` [0.x+] - Analytical OLAP database alternative to SQLite

## External Integrations

**DATASUS FTP:**
- Host: `ftp.datasus.gov.br`
- Protocol: FTP (custom ftplib implementation)
- Files: SIH (RD*.dbc), CNES (ST*.dbc)
- Format: DBC (compressed DBF binary format)
- Frequency: Monthly, 27 state files per month per source

**ANS Open Data Portal:**
- Base URL: `https://dados.ans.gov.br/operadoras/informacoes_de_beneficiarios/`
- Format: CSV (latin-1 encoding, semicolon-delimited)
- Frequency: Quarterly (months 3, 6, 9, 12)
- Client: `requests` library with retry logic

**IBGE (Optional):**
- Auto-downloaded population estimates and municipality shapefiles
- Used by: `extract_lcogs1.py` for geospatial mapping

## Architecture Overview

- **Modular design:** Separate scripts for each data source (SIH, CNES, ANS, IFGF)
- **Multi-process parallelism:** SIH batch processor uses `multiprocessing` for per-state conversion
- **Retry logic:** FTP and HTTP downloads support retry-with-backoff
- **Lazy imports:** Optional dependencies (requests, pysus, geopandas) imported only when needed
- **Idempotent processing:** Parquet partition-by-state allows resumable downloads and processing

## Typical Workflow

```bash
# 1. Download raw data (optional - can use bundled data)
python scripts/continue_raw_download.py --end-year 2023 --end-month 12 --months 12
python scripts/download_ans.py --start 2013-01 --end 2023-12

# 2. Process and aggregate
python database/pipeline.py --start 2013-01 --end 2023-12

# 3. Build database
python database/build_database_v2.py

# 4. Generate analysis outputs
python analysis/icskg_analysis_pipeline.py

# 5. Create LCoGS-1 maps
python extract_lcogs1.py --year 2023
```

---

*Stack analysis: 2026-04-01*
