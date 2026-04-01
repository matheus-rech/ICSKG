# Codebase Structure

**Analysis Date:** 2026-04-01

## Directory Layout

```
ICSKG/
├── README.md                                    # Project overview, quick start, CIMI dimensions
│
├── analysis/
│   ├── icskg_analysis_pipeline.py               # CIMI dimension computation + figure/table generation
│   └── results/                                 # Generated figures (4) and tables (8) + panel CSV
│       ├── figure1_icskg_distribution.png
│       ├── figure2_cimi_dimensions_boxplot.png
│       ├── figure3_temporal_trend.png
│       ├── figure4_correlation_heatmap.png
│       ├── table1_descriptive_statistics.csv
│       ├── table2_correlation_matrix.csv
│       ├── table3_top10_municipalities.csv
│       ├── table4_bottom10_municipalities.csv
│       ├── table5_quartile_means.csv
│       ├── table6_annual_means.csv
│       ├── table7_missing_data_summary.csv
│       ├── table8_dimension_metadata.csv
│       └── icskg_panel_2013_2024.csv            # Longitudinal panel (main output)
│
├── database/
│   ├── pipeline.py                              # ETL orchestrator (6-stage pipeline)
│   ├── build_database_v2.py                     # SQLite/DuckDB schema + upsert logic
│   ├── database_metadata.json                   # Dimension definitions, source URLs, schema version
│   ├── icskg_br.sqlite                          # SQLite relational database (generated)
│   └── icskg_br.duckdb                          # DuckDB analytical mirror (generated)
│
├── scripts/
│   ├── continue_raw_download.py                 # SIH/CNES DBC download with resume capability
│   ├── download_ans.py                          # ANS CSV historical beneficiary download
│   └── sih_batch_v2.py                          # Optimised DBC→parquet converter, parallel by UF
│
├── data_sources/
│   ├── README.md                                # Data source guide, file locations, download instructions
│   ├── Evolucao_por_Indicador_2013_a_2024_IFGF_2025.xlsx  # FIRJAN fiscal index (2013–2024)
│   ├── ans_beneficiarios_dez2023.csv            # ANS private health beneficiaries Dec 2023
│   ├── raw/                                     # Auto-created by download scripts
│   │   ├── SIH/                                 # DBC files (RD*.dbc)
│   │   ├── CNES/                                # DBC files (CNES*.dbc)
│   │   └── ANS/                                 # CSV files (*_Beneficiarios_por_municipio.csv)
│   └── processed/                               # Auto-created by pipeline.py
│       ├── sih_202301.parquet                   # Parsed SIH monthly
│       ├── cnes_202301.parquet                  # Parsed CNES monthly
│       ├── ans_beneficiarios_latest.parquet     # ANS converted
│       └── merged_202301.parquet                # Multi-source joined at municipality level
│
├── docs/
│   ├── README.md
│   ├── ICSKG-BR_Methodology_and_Gap_Analysis.md # Full methodology + variable definitions
│   ├── ICSKG-BR_Study_Protocol_v2.docx          # Study protocol
│   ├── ICSKG-BR_Variable_Cookbook_v2.xlsx       # Variable reference
│   └── ICSKG-BR_Technical_Cookbook_v2.docx      # Technical implementation guide
│
├── output/                                      # LCoGS-1 geospatial analysis outputs
│   ├── README.md
│   ├── lcogs1_bellwether_map.png                # Choropleth map
│   ├── lcogs1_bellwether_map_detail.png         # State-level detail maps
│   ├── lcogs1_bellwether_rates.csv              # Municipality-level rates
│   └── lcogs1_bellwether_gap.csv                # Gap to benchmark
│
├── extract_lcogs1.py                            # LCoGS-1 bellwether procedure analysis
│
├── .planning/codebase/                          # GSD planning documents
├── .claude/
├── .omc/
├── .git/
└── [other hidden files]
```

## Directory Purposes

**`analysis/`:**
- Purpose: Compute all 9 CIMI dimensions from extracted/merged data; generate publication-ready figures and summary tables
- Contains: Single entry point (`icskg_analysis_pipeline.py`) + output directory
- Key files: `icskg_analysis_pipeline.py` (lines 1–358)

**`database/`:**
- Purpose: Aggregate multi-source data into relational databases; maintain dimension metadata
- Contains: ETL orchestrator, database builder, schema definitions, generated SQLite/DuckDB files, metadata
- Key files: `pipeline.py` (orchestrator), `build_database_v2.py` (schema + ingestion)

**`scripts/`:**
- Purpose: Source-specific data acquisition and parsing
- Contains: Download and conversion functions for SIH, CNES, ANS
- Key files: `continue_raw_download.py` (SIH/CNES), `download_ans.py` (ANS), `sih_batch_v2.py` (DBC→parquet)

**`data_sources/`:**
- Purpose: Store input data (bundled + auto-downloaded) and intermediate processing results
- Contains: IFGF Excel, ANS CSV (bundled); raw/ and processed/ (auto-created)
- Special: README.md provides source acquisition instructions

**`docs/`:**
- Purpose: Reference documentation including methodology, protocols, variable definitions, technical implementation
- Contains: Markdown, Word, Excel files with study design, variable mappings, technical details

**`output/`:**
- Purpose: Store outputs of specialized analyses (e.g., LCoGS-1 surgical capacity assessment)
- Contains: Maps, CSVs, geospatial visualizations
- Generated by: `extract_lcogs1.py`

## Key File Locations

**Entry Points:**
- `database/pipeline.py`: Main ETL orchestration entry point (line 296, main function)
- `analysis/icskg_analysis_pipeline.py`: Analysis and visualization entry point (line 321, main function)
- `extract_lcogs1.py`: LCoGS-1 geospatial analysis entry point (implicit main)
- `scripts/continue_raw_download.py`: SIH/CNES download entry point
- `scripts/download_ans.py`: ANS download entry point
- `scripts/sih_batch_v2.py`: SIH batch processing entry point

**Configuration:**
- `database/database_metadata.json`: Dimension definitions, source metadata, schema version (lines 1–142)
- `data_sources/README.md`: Download instructions and source URL references

**Core Logic:**
- `database/pipeline.py`: STAGES constant (line 39–46), run_pipeline function (line 203–271), _iter_months helper (lines 273–289)
- `database/build_database_v2.py`: DDL schemas (lines 46–85), upsert_municipal_health function (lines 161–207), collect_parquet_files (lines 131–144)
- `analysis/icskg_analysis_pipeline.py`: CIMI_DIMENSIONS constant (lines 41–51), compute_d1/compute_d6 functions (lines 106–118), build_panel (lines 125–177), generate_figures (lines 184–248), generate_tables (lines 255–314)
- `extract_lcogs1.py`: BELLWETHER_DIAG constant (lines 54–72), LCOGS1_BENCHMARK constant (line 74), load_sih_year function (lines 81–100)

**Testing/Validation:**
- `analysis/icskg_analysis_pipeline.py`: Assertion on N_DIMENSIONS == 9 (line 341); synthetic data generation for testing (lines 149–161)
- `database/build_database_v2.py`: Empty DataFrame handling in collect_parquet_files (line 150), upsert_municipal_health (lines 163–164)

## Naming Conventions

**Files:**
- Python modules: `snake_case.py` (e.g., `pipeline.py`, `sih_batch_v2.py`, `build_database_v2.py`)
- Data files (bundled): Descriptive names with year ranges (e.g., `Evolucao_por_Indicador_2013_a_2024_IFGF_2025.xlsx`)
- Generated data: Temporal pattern in filename (e.g., `sih_202301.parquet`, `merged_202312.parquet`)
- Output files: Domain-specific prefixes (e.g., `lcogs1_bellwether_map.png`, `table1_descriptive_statistics.csv`)
- Documentation: Descriptive uppercase with version/date (e.g., `ICSKG-BR_Methodology_and_Gap_Analysis.md`)

**Directories:**
- Lowercase with underscores (e.g., `data_sources`, `analysis`, `database`)
- Temporal subdirectories: None explicit; year-month encoded in file names
- Category subdirectories: `raw/`, `processed/`, `results/` to distinguish data stages

**Functions:**
- Lowercase with underscores (e.g., `extract_sih()`, `load_parquet_to_df()`, `compute_d1()`, `_stage_banner()`)
- Private helpers prefixed with `_` (e.g., `_zscore()`, `_minmax()`, `_iter_months()`)
- Stage functions follow pattern `extract_*()`, `transform_*()`, `load_*()`

**Variables:**
- Column names: Uppercase or mixed case from external sources (e.g., `MUNIC_MOV`, `Cod_IBGE`, `BENEFICIARIOS`)
- Dimension keys: `D1_fiscal_governance`, `D2_health_expenditure`, etc. (consistent with CIMI standard)
- Constants: UPPERCASE (e.g., `CIMI_DIMENSIONS`, `DDL_MUNICIPAL_HEALTH`, `BELLWETHER_DIAG`, `LCOGS1_BENCHMARK`)

**Database Objects:**
- Tables: `snake_case` (e.g., `municipal_health`, `dimension_metadata`, `municipality_lookup`)
- Columns: `snake_case` or source convention (e.g., `cod_ibge`, `D1_fiscal_governance`, `ICSKG_score`)
- Codes/IDs: Format preserved from source (e.g., `cod_ibge` as 7-digit string, UF as 2-char string)

## Where to Add New Code

**New Data Source:**
1. Create extraction function in `scripts/new_source_download.py` following pattern of `continue_raw_download.py`
2. Add `extract_*()` wrapper in `database/pipeline.py` (import + function definition)
3. Register in `STAGES` list if part of core ETL (line 39–46), or call directly in `run_pipeline()`
4. Add dimension metadata to `database/database_metadata.json` if it yields a CIMI dimension
5. If new dimension, add `compute_*()` function to `analysis/icskg_analysis_pipeline.py` and include in `CIMI_DIMENSIONS` dict

**New CIMI Dimension:**
1. Add entry to `CIMI_DIMENSIONS` dict in `analysis/icskg_analysis_pipeline.py` (lines 41–51)
2. Implement `compute_d*()` function following pattern of `compute_d1()`, `compute_d6()` (lines 106–118)
3. Call in `build_panel()` (around line 164–170) to add to panel DataFrame
4. Update `database/database_metadata.json` with dimension metadata (lines 8–90)
5. Update `database/build_database_v2.py` DDL if new dimension column needed (lines 46–65)
6. Update dimension list in `upsert_municipal_health()` if using database (lines 166–171)

**New Specialized Analysis (like LCoGS-1):**
1. Create module `extract_*.py` at project root (e.g., `extract_new_analysis.py`)
2. Follow pattern of `extract_lcogs1.py`: load SIH/relevant source, classify/aggregate, generate outputs
3. Create corresponding output subdirectory (e.g., `output/new_analysis/`)
4. Write README in output directory documenting files and invocation
5. Register in main project README.md under "Quick start" section

**New Figure or Table:**
1. Add generation function to `analysis/icskg_analysis_pipeline.py` (e.g., `generate_new_figure()`, `generate_new_table()`)
2. Call from `main()` function (after line 350)
3. Save outputs to `analysis/results/` with descriptive naming
4. Update `analysis/results/README.md` to document new output

**Utilities or Helpers:**
- Dimension normalization (`_zscore()`, `_minmax()`): Keep in `analysis/icskg_analysis_pipeline.py`
- Data loading/parsing helpers: Keep in source-specific modules (`scripts/`)
- Database utilities: Keep in `database/build_database_v2.py`
- No shared utilities module exists; add if >3 files need same function

## Special Directories

**`data_sources/raw/`:**
- Purpose: Immutable source data as downloaded from DATASUS, ANS, FIRJAN
- Generated: By `scripts/continue_raw_download.py`, `scripts/download_ans.py`
- Committed: No (listed in implicit .gitignore for large files)
- Convention: Year-month or date-based filenames matching source format

**`data_sources/processed/`:**
- Purpose: Intermediate parquet files from extraction and merging; can be regenerated
- Generated: By `database/pipeline.py` during ETL
- Committed: No (can be reproduced from raw)
- Convention: `sih_YYYYMM.parquet`, `cnes_YYYYMM.parquet`, `merged_YYYYMM.parquet`

**`analysis/results/`:**
- Purpose: Final publication-ready outputs from analysis pipeline
- Generated: By `analysis/icskg_analysis_pipeline.py`
- Committed: No (reproduced by running analysis)
- Convention: Figures as PNG (150 dpi), tables as CSV

**`output/`:**
- Purpose: Specialized analysis outputs (geospatial, policy-relevant)
- Generated: By `extract_lcogs1.py` and similar modules
- Committed: No (reproduced by running extraction)
- Convention: Descriptive prefixes (e.g., `lcogs1_*`, `future_analysis_*`)

**`database/`:**
- Purpose: Database files and schema definitions
- Generated: SQLite/DuckDB files by `database/build_database_v2.py`
- Committed: No (`.sqlite` and `.duckdb` files not in version control)
- Convention: `icskg_br.sqlite`, `icskg_br.duckdb`

**`docs/`:**
- Purpose: Reference documentation (committed)
- Generated: Not auto-generated; manually maintained
- Committed: Yes
- Convention: Markdown, Word, Excel formats with version tags in filename

---

*Structure analysis: 2026-04-01*
