---
phase: 06-lcogs-indicators
plan: 01
subsystem: analysis
tags: [lcogs, lancet-commission, haversine, pomr, bellwether, surgical-indicators, sqlite]

# Dependency graph
requires:
  - phase: 02-sih-cnes-extraction
    provides: "SIH aggregates (n_procedures, n_deaths, total_cost_brl) and CNES facilities/professionals Parquet"
  - phase: 04-panel-assembly-validation
    provides: "Assembled panel with populacao, gdp_per_capita in municipal_health SQLite table"
  - phase: 05-dimension-computation-cuds
    provides: "build_database_v3.py create_schema pattern and dimension_scores persistence pattern"
provides:
  - "6 LCoGS indicator computation functions (compute_lcogs1 through compute_lcogs6)"
  - "compute_all_lcogs() orchestrator merging all 6 indicators"
  - "persist_lcogs_indicators() for SQLite persistence"
  - "seed_lcogs_metadata() with ecological-proxy caveats"
  - "DDL_LCOGS_INDICATORS and DDL_LCOGS_METADATA in build_database_v3.py"
  - "13 unit + integration tests in test_compute_lcogs.py"
affects: [07-regression-ml, 08-regional-analysis, 09-figures-tables]

# Tech tracking
tech-stack:
  added: []
  patterns: [haversine-vectorised-numpy, column-resolution-fallback, ecological-proxy-caveat-metadata]

key-files:
  created:
    - analysis/compute_lcogs.py
    - tests/test_compute_lcogs.py
  modified:
    - database/build_database_v3.py

key-decisions:
  - "CATASTROPHIC_THRESHOLD = 0.10 (10% of GDP per capita) for LCoGS-6 ecological proxy"
  - "Municipality centroids via geobr package (IBGE 2022 shapefiles) with FileNotFoundError fallback"
  - "Column resolution tries multiple names in order (n_procedures/procedure_count/aih_count) for panel compatibility"
  - "LCoGS-4 POMR suppressed to NaN for <10 surgical events (MIN_PROCEDURES_POMR = 10)"

patterns-established:
  - "_resolve_column() pattern for flexible column name matching across panel versions"
  - "seed_lcogs_metadata() pattern for indicator-level documentation with caveat field"
  - "Static geocoordinate computation reused across all years (distance_map dict)"

requirements-completed: [LCOG-01, LCOG-02, LCOG-03, LCOG-04, LCOG-05, LCOG-06]

# Metrics
duration: 5min
completed: 2026-04-02
---

# Phase 6 Plan 1: LCoGS Indicators Summary

**All 6 LCoGS indicators computed at municipality-year level with haversine distance, SAO density, surgical volume, POMR, financial risk ratio, and catastrophic expenditure proxy -- persisted to SQLite with ecological-proxy caveats**

## Performance

- **Duration:** 5 min
- **Started:** 2026-04-02T03:54:11Z
- **Completed:** 2026-04-02T03:59:00Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Created analysis/compute_lcogs.py with 6 indicator functions, orchestrator, SQLite persistence, metadata seeding, and CLI
- LCoGS-1 uses vectorised haversine with geobr municipality centroids; bellwether municipalities get 0.0 km
- LCoGS-4 POMR suppressed to NaN for <10 surgical events; LCoGS-5/6 documented as ecological proxies
- Added DDL_LCOGS_INDICATORS and DDL_LCOGS_METADATA to build_database_v3.py (8 tables total)
- 13 tests (12 unit + 1 integration) all pass; full suite 186 tests with 0 regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Create LCoGS computation module with all 6 indicators** - `0c0a389` (feat + test, TDD)
2. **Task 2: End-to-end SQLite integration and verification** - `702f042` (test)

## Files Created/Modified
- `analysis/compute_lcogs.py` - 6 LCoGS indicator functions + orchestrator + persistence + CLI entry point
- `tests/test_compute_lcogs.py` - 13 tests covering all indicators, edge cases, and SQLite integration
- `database/build_database_v3.py` - Added DDL_LCOGS_INDICATORS, DDL_LCOGS_METADATA to ALL_DDL list

## Decisions Made
- CATASTROPHIC_THRESHOLD = 0.10 (10% of GDP per capita) chosen as ecological proxy threshold for LCoGS-6
- Municipality centroids loaded via geobr package (IBGE 2022 shapefiles) with module-level cache; FileNotFoundError raised with install guidance if geobr unavailable
- _resolve_column() pattern tries multiple column name candidates in order for panel compatibility across phases
- All indicators documented as SUS-funded procedures only in both code comments and lcogs_metadata table

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Known Stubs
None - all 6 LCoGS indicators are fully computed from panel data. geobr dependency is required for LCoGS-1 centroids but is a standard pip package, not a stub.

## Next Phase Readiness
- All 6 LCoGS indicators available in lcogs_indicators SQLite table for Phase 7 regression/ML analysis
- lcogs_metadata table provides indicator documentation for reporting (Phase 9)
- compute_all_lcogs() can be called from downstream pipelines with panel + CNES data

## Self-Check: PASSED

- [x] analysis/compute_lcogs.py exists
- [x] tests/test_compute_lcogs.py exists
- [x] database/build_database_v3.py exists (modified)
- [x] Commit 0c0a389 found (Task 1)
- [x] Commit 702f042 found (Task 2)
- [x] 13/13 tests pass
- [x] 186/186 full suite tests pass (0 regressions)

---
*Phase: 06-lcogs-indicators*
*Completed: 2026-04-02*
