---
phase: 04-panel-assembly-validation
plan: 01
subsystem: database
tags: [ipca, deflation, sidrapy, panel-assembly, scaffold, parquet, validation]

# Dependency graph
requires:
  - phase: 01-foundation
    provides: normalize_cod_ibge, load_ibge_municipios, validate_dataframe, AMC crosswalk
  - phase: 02-sih-cnes-extraction
    provides: SIH and CNES processed Parquet files
  - phase: 03-secondary-source-extraction
    provides: IBGE SIDRA, IPEA IDHM, IFGF, ANS, Census, RENAVAM, SIOPS Parquet files
provides:
  - IPCA deflation module (fetch_ipca_annual_index, deflate_column)
  - Panel assembly orchestrator (build_panel_scaffold, load_source, assemble_panel)
  - Scaffold-first merge producing 5571 rows per year
  - Monetary deflation to constant 2023 BRL before merge
  - Per-source validation with quarantine and validation_report.json
affects: [04-panel-assembly-validation, 05-cuds-computation, 06-lcogs-indicators]

# Tech tracking
tech-stack:
  added: [sidrapy]
  patterns: [scaffold-first-merge, ipca-deflation, cross-sectional-replication]

key-files:
  created:
    - database/deflate_ipca.py
    - database/assemble_panel.py
    - tests/test_deflate_ipca.py
    - tests/test_assemble_panel.py
  modified: []

key-decisions:
  - "General IPCA index used for deflation (not health sub-index) -- health sub-index reserved for sensitivity analysis"
  - "Scaffold-first merge strategy: IBGE reference x years drives row count, sources left-join onto it"
  - "Monetary columns (gdp_per_capita, health_expenditure_per_capita) deflated BEFORE merge, not after"
  - "Cross-sectional sources (IDHM 2010, Census 2022) replicated across all 9 panel years"
  - "Empty/unavailable sources gracefully skipped with warning, not fatal"

patterns-established:
  - "Scaffold-first merge: build (cod_ibge, year) scaffold from IBGE reference, left-join all sources"
  - "IPCA deflation: preserve nominal in {col}_nominal, overwrite with deflated values"
  - "Cross-sectional replication: single-year sources replicated across all panel years"
  - "Source catalog pattern: dict mapping source_name to path/glob/value_cols/flags"

requirements-completed: [DATA-10, PANL-01, PANL-02, PANL-03]

# Metrics
duration: 4min
completed: 2026-04-02
---

# Phase 4 Plan 1: Panel Assembly Summary

**IPCA deflation from SIDRA 1737 with scaffold-first merge of 11 sources into validated municipality-year panel**

## Performance

- **Duration:** 4 min
- **Started:** 2026-04-02T02:45:49Z
- **Completed:** 2026-04-02T02:50:00Z
- **Tasks:** 1 (TDD: RED + GREEN)
- **Files modified:** 4

## Accomplishments
- IPCA deflation module fetches annual indices from SIDRA table 1737 and computes deflation factors with base_year=2023 yielding factor 1.0
- Panel scaffold produces exactly 5571 * n_years rows from IBGE authoritative reference, enforcing row-count invariant per year
- Assembled panel orchestrator merges all 11 data sources with per-source validation, quarantine for bad rows, and validation_report.json output
- Cross-sectional sources (IDHM, Census sanitation) properly replicated across all panel years
- Empty/unavailable sources (SIOPS, RENAVAM if absent) gracefully skipped without crashing

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): Failing tests** - `65a1406` (test)
2. **Task 1 (GREEN): Implementation** - `7e5bead` (feat)

_TDD task: tests written first, then implementation to pass all 13 tests._

## Files Created/Modified
- `database/deflate_ipca.py` - IPCA deflation factor fetching from SIDRA 1737 and column deflation with nominal preservation
- `database/assemble_panel.py` - Panel assembly orchestrator: scaffold builder, source loader with AMC crosswalk and cross-sectional replication, full merge with validation gate
- `tests/test_deflate_ipca.py` - 6 tests: base_year factor=1.0, older years >1.0, year filtering, nominal preservation, factor application, NaN handling
- `tests/test_assemble_panel.py` - 7 tests: scaffold shape, per-year count, no duplicates, load_source returns data, empty handling, cross-sectional replication, missing file handling

## Decisions Made
- General IPCA index (not health sub-index) used as primary deflator per research recommendation; health sub-index reserved for sensitivity analysis
- December IPCA values taken as annual reference point, consistent with standard Brazilian economic practice
- Scaffold-first merge strategy ensures completeness -- every municipality appears in every year regardless of source availability
- Monetary columns deflated BEFORE merge so that monetary values in the panel are already in constant 2023 BRL
- Source catalog defined as module-level dict for easy extension with new sources

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Known Stubs
None - all functions are fully implemented with real logic and validation.

## Next Phase Readiness
- Panel assembly module ready for Plan 02 (IFGF imputation, SQLite persistence, missingness documentation)
- All 11 source slots defined in SOURCE_CATALOG; actual data files needed for full panel assembly
- validation_report.json will be generated on first full assemble_panel() run with real data

## Self-Check: PASSED

- All 5 files verified present on disk
- Commits 65a1406 (RED) and 7e5bead (GREEN) verified in git log
- 13/13 tests pass

---
*Phase: 04-panel-assembly-validation*
*Completed: 2026-04-02*
