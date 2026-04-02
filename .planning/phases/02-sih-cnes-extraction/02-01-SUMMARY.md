---
phase: 02-sih-cnes-extraction
plan: 01
subsystem: database
tags: [duckdb, parquet, sih, etlsih, csv-extraction, municipality-normalization]

# Dependency graph
requires:
  - phase: 01-foundation
    provides: normalize_cod_ibge(), validate_dataframe(), IBGE reference CSV, pyproject.toml with dependencies
provides:
  - scripts/sih_extract.py with read_etlsih_csv(), process_sih_month(), SIH_COLS_KEEP exports
  - DuckDB column-projection pattern for reading 27 of 235 ETLSIH CSV columns
  - Per-UF-month Parquet output at data_sources/processed/sih/{UF}_{YYYYMM}.parquet
  - Test fixture CSV with correct ETLSIH 32-column header for offline testing
affects: [02-sih-cnes-extraction, 03-data-acquisition, database-pipeline]

# Tech tracking
tech-stack:
  added: []
  patterns: [DuckDB read_csv_auto column projection, idempotent per-UF-month Parquet output, N_AIH deduplication]

key-files:
  created:
    - scripts/sih_extract.py
    - tests/test_sih_extract.py
    - tests/fixtures/ETLSIH.ST_XX_2023_1_t.csv
    - scripts/__init__.py
  modified: []

key-decisions:
  - "DuckDB read_csv_auto() with SELECT for column projection -- reads 27 of 235 columns without loading full file"
  - "MUNIC_MOV renamed to cod_ibge (treatment municipality) per project decision; MUNIC_RES renamed to cod_ibge_res for downstream use"
  - "N_AIH deduplication keeps first occurrence -- consistent with existing sih_batch_v2.py pattern"
  - "DT_INTER/DT_SAIDA kept as integers (YYYYMMDD) -- datetime conversion deferred to downstream per plan"

patterns-established:
  - "DuckDB column projection: read_csv_auto() with SELECT clause for large CSVs (27/235 cols)"
  - "Idempotent Parquet output: skip_existing checks file existence and non-zero size"
  - "ETLSIH file pattern resolution: try non-padded month first, then zero-padded fallback"

requirements-completed: [DATA-01]

# Metrics
duration: 3min
completed: 2026-04-02
---

# Phase 2 Plan 01: SIH Extraction Summary

**DuckDB-powered ETLSIH CSV extraction with column projection (27/235 cols), municipality code normalization, and N_AIH deduplication writing per-UF-month Parquet files**

## Performance

- **Duration:** 3 min
- **Started:** 2026-04-02T01:09:08Z
- **Completed:** 2026-04-02T01:12:23Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- SIH extraction script reads FIOCRUZ BigData ETLSIH CSVs using DuckDB column projection (27 of 235 columns)
- Municipality codes (MUNIC_MOV, MUNIC_RES) normalized to 7-digit strings via normalize_cod_ibge()
- N_AIH deduplication, MORTE int coercion, VAL_TOT/VAL_UTI float coercion
- 10 passing unit tests with offline fixture data (no NAS required)
- Full test suite (55 tests) passes with no regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Create test fixtures and SIH extraction tests** - `9750ef0` (test) - TDD RED phase
2. **Task 2: Implement SIH extraction script** - `2391c01` (feat) - TDD GREEN phase

## Files Created/Modified
- `scripts/sih_extract.py` - ETLSIH CSV -> Parquet processor with DuckDB column projection, 457 lines
- `tests/test_sih_extract.py` - 10 pytest functions covering columns, normalization, idempotency, deduplication, types
- `tests/fixtures/ETLSIH.ST_XX_2023_1_t.csv` - Offline test fixture with 32 columns (27 kept + 5 noise) and 6 data rows
- `scripts/__init__.py` - Module init for import support

## Decisions Made
- DuckDB read_csv_auto() chosen for CSV reading -- column projection pushes to I/O layer, 3-10x faster than pandas for large files
- MUNIC_MOV renamed to cod_ibge (treatment municipality is the spatial unit per project decision); MUNIC_RES kept as cod_ibge_res
- N_AIH deduplication uses keep="first" -- matches existing sih_batch_v2.py convention
- DT_INTER/DT_SAIDA kept as YYYYMMDD integers -- datetime conversion is downstream responsibility per plan

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Created scripts/__init__.py for module imports**
- **Found during:** Task 1 (test creation)
- **Issue:** tests/test_sih_extract.py imports from scripts.sih_extract but scripts/ had no __init__.py
- **Fix:** Created empty scripts/__init__.py
- **Files modified:** scripts/__init__.py
- **Verification:** Import succeeds in tests
- **Committed in:** 9750ef0 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Necessary for Python module import resolution. No scope creep.

## Issues Encountered
- Worktree did not share .venv with main repo -- resolved by symlinking .venv (not committed, local-only)

## Known Stubs
None -- all functions are fully implemented with no placeholder data.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- SIH extraction layer complete; ready for Plans 02-04 (CNES extraction, SIH aggregation, pipeline integration)
- process_sih_month() API ready to be wired into database/pipeline.py extract_sih() stub
- Test fixture pattern established for CNES extraction tests (Plan 02)

## Self-Check: PASSED

- [x] scripts/sih_extract.py exists
- [x] tests/test_sih_extract.py exists
- [x] tests/fixtures/ETLSIH.ST_XX_2023_1_t.csv exists
- [x] scripts/__init__.py exists
- [x] Commit 9750ef0 found
- [x] Commit 2391c01 found
- [x] All 10 tests pass
- [x] Full suite (55 tests) passes

---
*Phase: 02-sih-cnes-extraction*
*Completed: 2026-04-02*
