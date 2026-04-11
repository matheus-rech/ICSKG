# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**ICSKG-BR** (Index of Cities' Smartness & Knowledge for Global Surgery — Brazil) is a longitudinal ecological panel study. It operationalizes the IESE Cities in Motion Index (CIMI) 9-dimension framework as a Composite Urban Development Score (CUDS) and validates it against Lancet Commission on Global Surgery (LCoGS) indicators across all 5,570 Brazilian municipalities from 2015 to 2023. Target journal: BMJ Global Health. Reporting standard: STROBE + RECORD.

## Commands

```bash
# Setup (requires Python 3.12, uses uv for dependency management)
uv sync                          # install all dependencies from uv.lock

# Run tests (243 tests across 26 test files)
python -m pytest                 # full suite
python -m pytest tests/test_compute_dimensions.py  # single file
python -m pytest tests/test_compute_dimensions.py::test_name -v  # single test
python -m pytest --tb=short -q   # quick summary

# Pipeline entry points
python database/pipeline.py --year 2023 --month 12           # single month ETL
python database/pipeline.py --start 2015-01 --end 2023-12    # full historical window
python database/build_database_v3.py                          # build SQLite/DuckDB
python analysis/compute_dimensions.py --db-path database/icskg_br.sqlite  # dimensions + CUDS
python analysis/run_regressions.py --db-path database/icskg_br.sqlite     # panel regressions
python analysis/compute_lcogs.py                              # LCoGS indicators
python extract_lcogs1.py --year 2023                          # bellwether geospatial maps
```

## Architecture

The codebase is a 5-layer ETL + analysis pipeline. All layers join on `cod_ibge` (IBGE 7-digit municipality code) as the universal spatial key and `year` as the temporal key.

### Layer 1: Extraction (`scripts/`)
Source-specific downloaders/parsers for 11 data sources. Each script outputs parquet files under `data_sources/processed/{source}/`. Key sources: SIH (hospital inpatient), CNES (facility registry), ANS (private coverage), IFGF (fiscal index), IBGE SIDRA (population/GDP), IPEA IDHM, Census sanitation, RENAVAM (vehicles), SIOPS (health expenditure).

### Layer 2: Validation (`database/validation.py`)
Quality gate between extraction and assembly. Validates cod_ibge against IBGE 2023 reference list, checks year scope (2015-2023), enforces unique `(cod_ibge, year)` keys, verifies schema. Bad rows go to `data_sources/quarantine/` as parquet files with timestamps.

### Layer 3: Panel Assembly (`database/assemble_panel.py`)
Scaffold-first strategy: creates a `(cod_ibge, year)` scaffold from IBGE reference (5,571 municipalities x 9 years), then left-merges each validated source. Cross-sectional sources (IDHM 2010, Census 2022) are replicated across all years. Monetary columns deflated to 2023 BRL via `database/deflate_ipca.py`.

### Layer 4: Dimension Computation (`analysis/compute_dimensions.py`)
Computes 8 active CIMI dimensions (D1-D7, D9; D8 excluded) from assembled panel. Within-year min-max normalization to [0,1]. CUDS = geometric mean of available dimensions with epsilon=0.01 floor. D4 (SUS dependence) is inverted.

### Layer 5: Statistical Analysis
- `analysis/run_regressions.py` — Two-way FE panel regressions (CUDS → 6 LCoGS outcomes) with cluster-robust SE, Hausman tests, dose-response
- `analysis/ml_models.py` — XGBoost/Random Forest with SHAP importance
- `analysis/spatial_analysis.py` — Moran's I, LISA clusters, spatial lag models via libpysal/esda
- `analysis/causal_inference.py` — DML via econml
- `analysis/compute_lcogs.py` — LCoGS indicator computation from SIH/CNES data

### Orchestration (`database/pipeline.py`)
Main ETL orchestrator. Calls all 11 `extract_*()` functions per year-month, then triggers assembly. Each extractor is wrapped in try-except — failures are logged and skipped, not fatal. Supports `--ufs SP RJ` for state-level filtering.

### Data Flow
```
data_sources/raw/     →  scripts/extract_*.py  →  data_sources/processed/{source}/
                                                        ↓
                                              database/assemble_panel.py
                                                        ↓
                                              database/icskg_br.sqlite (+ .duckdb)
                                                        ↓
                                              analysis/compute_dimensions.py → CUDS panel
                                                        ↓
                                    analysis/run_regressions.py + ml_models.py + spatial_analysis.py
                                                        ↓
                                              analysis/results/  (figures, tables, CSVs)
```

## Key Design Decisions

- **All data is public**: Sources must be publicly available Brazilian government data (Lei de Acesso `12.527/2011`). No individual-level identifiers.
- **Idempotent pipeline**: Same inputs produce same outputs. Parquet partition-by-state enables resumable processing.
- **`config.yaml` holds local paths**: Data root defaults to NAS mount (`/Volumes/docker/Downloads/ICSKG`). This file is gitignored — copy from `config.example.yaml`.
- **Lazy imports**: Optional dependencies (pysus, geopandas, requests) are imported inside functions to avoid import-time failures.
- **Validation quarantine**: Bad rows are never silently dropped — they're written to timestamped parquet files in `data_sources/quarantine/` for audit.

## Conventions

- **Logging**: Use `logger.info/warning/error/debug` with %-style formatting (never f-strings in log calls). Stage banners with `===` or `─` separators.
- **Paths**: Always `pathlib.Path`, never raw strings. `path.mkdir(parents=True, exist_ok=True)`.
- **Exception handling**: Broad `except Exception as exc:  # noqa: BLE001` is acceptable for pipeline resilience. Always `from exc` on re-raise.
- **Column naming**: Normalize all municipality codes to `cod_ibge` (string type) before merge. Source-specific names (Cod_IBGE, CD_MUNICIPIO) get renamed in extraction.
- **Normalization**: `_minmax()` for [0,1] scaling, `_zscore()` for standardization. Numeric coercion via `pd.to_numeric(..., errors="coerce")`.
- **Module entry points**: Every script uses `if __name__ == "__main__": sys.exit(main())` with `main(argv=None)` accepting argparse args.
- **noqa markers**: `BLE001` (bare except) and `PLC0415` (local imports) are used intentionally — don't remove them.

## Domain Context

- **CIMI**: Cities in Motion Index — 9-dimension urban development framework from IESE
- **CUDS**: Composite Urban Development Score — this project's implementation of CIMI at municipal level
- **LCoGS**: Lancet Commission on Global Surgery — 6 indicators measuring surgical system performance
- **Bellwether procedures**: Laparotomy, C-section, open fracture treatment — LCoGS-1 access proxies
- **SIH**: Hospital Information System (DATASUS) — inpatient records in DBC format
- **CNES**: National Registry of Health Establishments — facilities, beds, workforce
- **IFGF**: FIRJAN Fiscal Management Index — municipal governance quality
- **cod_ibge**: 7-digit IBGE municipality code — the universal join key across all sources

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
