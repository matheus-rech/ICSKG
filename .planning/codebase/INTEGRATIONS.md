# External Integrations

**Analysis Date:** 2026-04-01

## APIs & External Services

**DATASUS FTP (Brazil Ministry of Health):**
- Service: Federal health system data repository
- What it's used for: Download monthly SIH (inpatient) and CNES (facility) microdata
  - SDK/Client: Python built-in `ftplib` module
  - Auth: Anonymous FTP login
  - Host: `ftp.datasus.gov.br`
  - Paths:
    - SIH: `/dissemin/publicos/SIHSUS/200801_/Dados/`
    - CNES: `/dissemin/publicos/CNES/200508_/Dados/ST/`
  - Implementation: `scripts/continue_raw_download.py` (lines 45-64)
  - Retry logic: MAX_RETRIES=5, RETRY_DELAY=10 seconds, byte-range resume support

**ANS Open Data Portal (Brazilian National Health Agency):**
- Service: Private health plan beneficiary statistics (national aggregate)
- What it's used for: Quarterly municipal-level private health coverage data
  - SDK/Client: `requests` library (lazy-imported at runtime)
  - Auth: None (public API)
  - Base URL: `https://dados.ans.gov.br/operadoras/informacoes_de_beneficiarios/`
  - File pattern: `{YYYY}{MM}_Beneficiarios_por_municipio.csv`
  - Format: CSV (latin-1 encoding, semicolon-delimited)
  - Quarterly months: 3, 6, 9, 12 (March, June, September, December)
  - Implementation: `scripts/download_ans.py` (lines 47-98)
  - Retry logic: MAX_RETRIES=4, RETRY_DELAY=5 seconds, custom User-Agent header

**IBGE (Brazilian Institute of Geography and Statistics):**
- Service: Population estimates and geographic data
- What it's used for: Municipal population denominators, geospatial shapefiles for mapping
  - Format: Auto-downloaded JSON/shapefile (implicit in extract_lcogs1.py)
  - Used by: `extract_lcogs1.py` for LCoGS-1 bellwether mapping (lines 24-26 comment)

## Data Storage

**Databases:**
- **SQLite** (Primary)
  - Type: Relational RDBMS
  - Connection: File-based, no network required
  - Location: `database/icskg_br.sqlite`
  - Client: Python `sqlite3` (stdlib)
  - Schema definition: `database/build_database_v2.py` (lines 46-75)
  - Tables: `municipal_health`, `dimension_metadata`, `municipality_lookup`
  - Key indices: UNIQUE(cod_ibge, year, month)

- **DuckDB** (Optional/Analytical)
  - Type: Columnar analytical database
  - Location: `database/icskg_br.duckdb`
  - Client: `duckdb` package (pip optional install)
  - Purpose: Faster OLAP queries than SQLite (mentioned in README.md)

**File Storage:**
- **Local Parquet Files** (Processed intermediate data)
  - Format: Apache Parquet columnar format
  - Location: `data_sources/processed/sih_*.parquet`, `data_sources/processed/cnes_*.parquet`
  - Client library: `pyarrow`
  - Usage: Partitioned by UF (state) for incremental processing and parallelism
  - Reason: Reduces memory footprint, enables resume capability

- **Raw DBC Files** (Pre-processing only)
  - Format: DBC (compressed DBF, DATASUS proprietary)
  - Storage location: `data_sources/raw/SIH/`, `data_sources/raw/CNES/`
  - Processing: Converted to CSV/Parquet via `pysus` or `blast-dbf` tool
  - Lifecycle: Downloaded → Decompressed → Converted → Deleted after processing

- **Bundled Excel/CSV Files** (Pre-packaged data sources)
  - IFGF: `data_sources/Evolucao_por_Indicador_2013_a_2024_IFGF_2025.xlsx`
  - ANS: `data_sources/ans_beneficiarios_dez2023.csv`

**Caching:**
- None detected. Files are downloaded fresh from source each run (unless using pre-bundled data)
- Resume capability: FTP/HTTP downloads support byte-range resume (continue_raw_download.py lines 91-96)

## Authentication & Identity

**Auth Provider:**
- None required (all sources are public/open data)

**Implementation:**
- DATASUS FTP: Anonymous login (no credentials)
- ANS API: Public HTTP (no API key required)
- IBGE: Public HTTP (no API key required)
- User-Agent headers used for identification: `"ICSKG-BR/2.0 (research; contact: icskg-br@example.org)"` (scripts/download_ans.py line 72)

## Monitoring & Observability

**Error Tracking:**
- None detected

**Logging:**
- Framework: Python `logging` module (stdlib)
- Configuration: `scripts/continue_raw_download.py` line 34-39, all scripts
- Format: `%(asctime)s  %(levelname)-8s  %(message)s` with ISO timestamp
- Log levels: INFO (progress), WARNING (retries), ERROR (failures)
- Example: FTP listing failures logged as errors with exception details (line 87)

**Retry & Resilience:**
- **FTP downloads:** MAX_RETRIES=5 with 10-second delay between attempts
- **HTTP downloads (ANS):** MAX_RETRIES=4 with 5-second exponential backoff (delay * attempt)
- Byte-range resume: Implemented for interrupted FTP transfers (continue_raw_download.py)

## CI/CD & Deployment

**Hosting:**
- Local development environment (no cloud deployment detected)
- Can be run on any machine with Python 3.9+ and network access

**CI Pipeline:**
- None detected

**Deployment:**
- Manual script invocation: `python scripts/*.py` or `python database/*.py`
- No Docker, containerization, or automated deployment detected
- Data workflow is event-triggered (manual runs with date parameters)

## Environment Configuration

**Required env vars:**
- None strictly required
- All configuration via command-line arguments (--start, --end, --year, --month, --output-dir, etc.)

**Optional env vars:**
- None detected

**Secrets location:**
- No secrets required (all integrations are public/anonymous)
- No .env file in codebase
- User-Agent identifies project: `icskg-br@example.org` (hardcoded, not sensitive)

## Webhooks & Callbacks

**Incoming:**
- None detected

**Outgoing:**
- None detected

## Data Flow Architecture

### ETL Pipeline Overview

```
DATASUS FTP (SIH/CNES) ──────┐
                              ├──> Extraction Scripts
ANS Open Data Portal ─────────┤    (scripts/*.py)
IFGF Excel (bundled) ─────────┤
                              ├──> Raw Parquet Files
                              │    (data_sources/processed/)
                              │
                              ├──> Pipeline Aggregation
                              │    (database/pipeline.py)
                              │
                              ├──> Database Builder
                              │    (database/build_database_v2.py)
                              │
                              ├──> SQLite / DuckDB
                              │    (database/*.sqlite/.duckdb)
                              │
                              └──> Analysis Pipeline
                                   (analysis/icskg_analysis_pipeline.py)
                                   │
                                   ├──> Figures (PNG)
                                   ├──> Tables (CSV)
                                   └──> Panel Dataset (CSV/Excel)

LCoGS-1 Bellwether Analysis
(extract_lcogs1.py)
    │
    ├──> SIH Parquet
    ├──> IBGE Population API
    ├──> IBGE Shapefile
    │
    └──> Maps + CSVs (output/)
```

### Data Source Metadata

**Source Registry:** `database/database_metadata.json`

| Source | Provider | Format | Frequency | Coverage | Endpoint |
|--------|----------|--------|-----------|----------|----------|
| SIH | DATASUS/MS | DBC | Monthly | 1992–present | `ftp://ftp.datasus.gov.br/dissemin/publicos/SIHSUS/200801_/Dados/` |
| CNES | DATASUS/MS | DBC | Monthly | 2005–present | `ftp://ftp.datasus.gov.br/dissemin/publicos/CNES/200508_/Dados/ST/` |
| ANS | ANS/MS | CSV | Quarterly | 2000–present | `https://dados.ans.gov.br/operadoras/informacoes_de_beneficiarios/` |
| IFGF | FIRJAN | XLSX | Annual | 2006–present | Local file (bundled) |
| SIOPS | MS | CSV/API | Annual | 2000–present | `https://siops.datasus.gov.br/` |

## Performance Considerations

**Download Strategy:**
- FTP passive mode enabled (continue_raw_download.py line 78)
- Byte-range resume: Reduces re-download of large DBC files on network failure
- Batch parallelism: SIH processor uses multiprocessing for concurrent UF processing (sih_batch_v2.py)

**Data Processing:**
- Chunked DBC → Parquet conversion (memory optimization, sih_batch_v2.py lines 9-10)
- Column subsetting: Only essential fields retained (SIH_COLS_KEEP, sih_batch_v2.py lines 51-76)
- Partition-by-state: Enables idempotent processing (skip already-converted partitions)

**Database:**
- Unique index on (cod_ibge, year, month) for fast municipality-time lookups
- SQLite chosen for portability (no external database required)

---

*Integration audit: 2026-04-01*
