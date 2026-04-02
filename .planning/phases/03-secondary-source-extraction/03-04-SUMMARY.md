---
phase: 03-secondary-source-extraction
plan: 04
subsystem: database
tags: [renavam, siops, pipeline-wiring, best-effort, graceful-degradation]

# Dependency graph
requires:
  - phase: 01-foundation
    provides: normalize_cod_ibge(), validate_dataframe(), load_ibge_municipios()
  - plan: 03-01
    provides: scripts/extract_ibge_sidra.py (extract_population, extract_gdp)
  - plan: 03-02
    provides: scripts/extract_ipea_idhm.py (extract_idhm), scripts/extract_ifgf.py (extract_ifgf)
  - plan: 03-03
    provides: scripts/extract_ans_quarterly.py (extract_ans_quarterly), scripts/extract_census_sanitation.py (extract_sanitation)
provides:
  - scripts/extract_renavam.py with BEST EFFORT vehicle fleet extraction and name-to-code crosswalk
  - scripts/extract_siops.py with BEST EFFORT health expenditure extraction (API + TabNet fallback)
  - database/pipeline.py updated with 14 stages wiring all 7 Phase 3 extractors
  - Empty schema Parquet files written on extraction failure (pipeline not blocked)
affects: [04-dimension-computation, 05-panel-assembly]

# Tech tracking
tech-stack:
  added: []
  patterns: [best-effort extraction with graceful degradation, municipality name-to-code crosswalk, multi-strategy API fallback]

key-files:
  created:
    - scripts/extract_renavam.py
    - scripts/extract_siops.py
    - tests/test_extract_renavam.py
    - tests/test_extract_siops.py
    - data_sources/processed/renavam/.gitkeep
    - data_sources/processed/siops/.gitkeep
  modified:
    - database/pipeline.py

decisions:
  - RENAVAM crosswalk uses load_ibge_municipios() with (UF_UPPER, NAME_UPPER) keys per Pitfall 9
  - SIOPS tries REST API endpoints first then DATASUS TabNet as fallback
  - Both best-effort scripts write empty-schema Parquet on failure so pipeline continues
  - Pipeline STAGES expanded from 6 to 14 (preserving all existing stages)

metrics:
  duration: 7min
  completed: "2026-04-02T02:22:46Z"
---

# Phase 03 Plan 04: RENAVAM + SIOPS Best Effort & Pipeline Wiring Summary

Best-effort RENAVAM vehicle fleet and SIOPS health expenditure extractors with graceful degradation, plus pipeline.py wired with all 7 Phase 3 secondary source extractors across 14 stages.

## What Was Done

### Task 1: BEST EFFORT RENAVAM Vehicle Fleet Extraction
- Created `scripts/extract_renavam.py` with municipality name-to-IBGE-code crosswalk via `load_ibge_municipios()`
- Format discovery: tries multiple URL patterns, encodings (utf-8, latin-1, cp1252), separators (comma, semicolon, tab)
- Column discovery: searches for municipality name, UF, and vehicle total columns using candidate lists
- If download or parse fails for any year, logs gap and continues; if all years fail, writes empty Parquet with schema `[cod_ibge, year, vehicles_total, vehicles_per_1000]`
- `normalize_cod_ibge()` applied to any successfully matched codes
- Created `tests/test_extract_renavam.py` with 7 tests: crosswalk structure, graceful degradation, CSV parsing
- **Commit:** `b251c0a`

### Task 2: BEST EFFORT SIOPS Health Expenditure Extraction
- Created `scripts/extract_siops.py` with multi-strategy approach: SIOPS REST API first, then DATASUS TabNet fallback
- API strategy: tries 4 known endpoint patterns per year, handles nested JSON responses
- TabNet fallback: tries CSV download from known URL patterns
- If all strategies fail, writes empty Parquet with schema `[cod_ibge, year, health_expenditure_per_capita]`
- `normalize_cod_ibge()` applied to any successfully matched codes
- Created `tests/test_extract_siops.py` with 4 tests: graceful degradation, normalization, schema validation
- **Commit:** `d2b7d40`

### Task 3: Wire All 7 Secondary Source Extractors into pipeline.py
- STAGES list expanded from 6 to 14 stages:
  - Existing: `extract_sih`, `extract_cnes`, `extract_ans`, `extract_ifgf`
  - New Phase 3: `extract_ibge_population`, `extract_ibge_gdp`, `extract_idhm`, `extract_ifgf_parquet`, `extract_ans_quarterly`, `extract_census_sanitation`, `extract_renavam`, `extract_siops`
  - Existing: `transform_merge`, `load_database`
- Each new extract function uses lazy imports with `# noqa: PLC0415`
- Each wrapped in try-except with `logger.error()` for graceful degradation
- `run_pipeline()` has conditional blocks for all 8 new stages
- Existing functions (SIH, CNES, ANS, IFGF) preserved unchanged
- **Commit:** `64213e1`

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| RENAVAM crosswalk uses (UF_UPPER, NAME_UPPER) tuple keys | Handles Pitfall 9: RENAVAM identifies municipalities by name, not IBGE code |
| SIOPS tries 4 API endpoint patterns before TabNet | API format is unknown; systematic discovery with graceful fallback |
| Empty schema Parquet on failure | Pipeline continues to next stage; dimension set to NaN in panel assembly |
| Pipeline STAGES expanded from 6 to 14 | All Phase 3 extractors callable from orchestrator for Phase 4 assembly |

## Deviations from Plan

None -- plan executed exactly as written.

## Test Results

```
tests/test_extract_renavam.py  7 passed  (27.14s)
tests/test_extract_siops.py    4 passed  (0.35s)
pipeline STAGES verification   14 stages confirmed
```

## Known Stubs

None -- all scripts are fully implemented with graceful degradation. RENAVAM and SIOPS are BEST EFFORT by design; empty data is expected behavior, not a stub.

## Self-Check: PASSED

All 8 files found. All 3 commits verified (b251c0a, d2b7d40, 64213e1).
