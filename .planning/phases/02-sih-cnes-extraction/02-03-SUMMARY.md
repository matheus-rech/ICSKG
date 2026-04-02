---
phase: 02-sih-cnes-extraction
plan: 03
subsystem: database
tags: [cnes, bellwether, cbo, parquet, lancet-commission, facility-registry]

# Dependency graph
requires:
  - phase: 01-foundation
    provides: normalize_cod_ibge(), rename_municipality_column(), validate_dataframe()
provides:
  - CNES facility extractor (scripts/cnes_extract.py) with bellwether identification
  - CBO-2002 6-digit code constants for SAO filtering (single source of truth)
  - CNES ST column constant for establishment CSV parsing
  - Test fixture with correct ETLCNES ST header format
affects: [02-04-cnes-professionals, 06-lcogs-indicators, 07-database-assembly]

# Tech tracking
tech-stack:
  added: []
  patterns: [duckdb-csv-column-projection-with-pandas-fallback, bellwether-facility-filter, zip-extraction-with-year-filter]

key-files:
  created:
    - scripts/cnes_extract.py
    - scripts/__init__.py
    - tests/test_cnes_extract.py
    - tests/fixtures/ETLCNES.ST_XX__23_01_t.csv
  modified: []

key-decisions:
  - "filter_bellwether_facilities() returns FULL DataFrame with is_bellwether column (not filtered) -- downstream can use both bellwether and non-bellwether facilities"
  - "DuckDB CSV reading with pandas fallback -- ensures fast column projection when duckdb available, graceful degradation when not"
  - "Deduplication keeps latest COMPETEN per (CNES, cod_ibge) -- monthly snapshots reduced to single latest state per facility"

patterns-established:
  - "CNES ST CSV reading: DuckDB column projection with pandas fallback for ETLCNES format"
  - "CBO code constants: 6-digit codes only, never 4-digit family codes (Pitfall 3)"
  - "Bellwether filter: surgical center OR obstetric center OR >=10 beds per Lancet Commission"

requirements-completed: [DATA-02]

# Metrics
duration: 3min
completed: 2026-04-01
---

# Phase 02 Plan 03: CNES Extraction Summary

**CNES facility extractor with bellwether hospital identification via Lancet Commission criteria and CBO-2002 6-digit SAO code registry**

## Performance

- **Duration:** 3 min
- **Started:** 2026-04-02T01:09:09Z
- **Completed:** 2026-04-02T01:12:10Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- CNES facility extraction script reading FIOCRUZ BigData ETLCNES ST CSV files with DuckDB column projection
- Bellwether facility identification using surgical center OR obstetric center OR >=10 inpatient beds
- CBO-2002 SAO code registry with 11 correct 6-digit codes (9 surgeons, 1 anesthesiologist, 1 obstetrician)
- Full TDD cycle with 14 test functions covering CBO constants, bellwether filter, and facility extraction integration

## Task Commits

Each task was committed atomically:

1. **Task 1: Create CNES test fixtures and extraction tests** - `329925e` (test)
2. **Task 2: Implement CNES extraction script** - `3ea4a84` (feat)

## Files Created/Modified
- `scripts/cnes_extract.py` - CNES establishment extractor with CBO constants, bellwether filter, zip extraction, CLI
- `scripts/__init__.py` - Package init for scripts module (enables `from scripts.cnes_extract import ...`)
- `tests/test_cnes_extract.py` - 14 pytest tests covering CBO codes, bellwether filter, facility extraction
- `tests/fixtures/ETLCNES.ST_XX__23_01_t.csv` - Offline test fixture with 16 columns, 5 data rows

## Decisions Made
- filter_bellwether_facilities() returns the full DataFrame with is_bellwether boolean column rather than filtering rows -- allows downstream to use both bellwether and non-bellwether facilities
- DuckDB CSV reading with pandas fallback for environments without duckdb installed
- Deduplication keeps latest COMPETEN per (CNES, cod_ibge) to reduce monthly snapshots to single latest state

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Created scripts/__init__.py for module imports**
- **Found during:** Task 2 (implementation)
- **Issue:** `from scripts.cnes_extract import ...` requires scripts/ to be a Python package
- **Fix:** Created empty `scripts/__init__.py`
- **Files modified:** scripts/__init__.py
- **Verification:** All imports resolve correctly, 14 tests pass
- **Committed in:** 3ea4a84 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Necessary for Python module imports. No scope creep.

## Issues Encountered
None

## Known Stubs
None -- all data paths are wired to real extraction logic.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- CNES facility extractor ready for integration into pipeline.py extract_cnes() stub
- CBO_SAO constants available for Plan 04 (CNES professional extraction when PF data acquired)
- facilities.parquet schema defined and tested for downstream LCoGS-1 analysis

---
## Self-Check: PASSED

All files verified present. All commit hashes found in git log.

---
*Phase: 02-sih-cnes-extraction*
*Completed: 2026-04-01*
