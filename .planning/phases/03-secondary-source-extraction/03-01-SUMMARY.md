---
phase: 03-secondary-source-extraction
plan: 01
subsystem: database
tags: [sidrapy, ibge, population, gdp, parquet, pandas]

# Dependency graph
requires:
  - phase: 01-project-setup
    provides: normalize_cod_ibge(), validate_dataframe(), ibge_municipios_2023.csv
provides:
  - scripts/extract_ibge_sidra.py with extract_population(), extract_gdp(), main()
  - Population panel extraction (cod_ibge, year, populacao) for 2015-2023
  - GDP panel extraction with per-capita computation (gdp_abs * 1000 / populacao)
  - Table routing: 6579 for 2015-2021, 4709 for 2022-2023
  - GDP estimated flag for 2022-2023 values
affects: [04-dimension-computation, 05-panel-assembly, database-pipeline]

# Tech tracking
tech-stack:
  added: [sidrapy]
  patterns: [per-source extractor with main(argv=None), sidrapy monkeypatch mocking, TDD with JSON fixtures]

key-files:
  created:
    - scripts/extract_ibge_sidra.py
    - tests/test_extract_ibge_sidra.py
    - tests/fixtures/sidra_6579_sample.json
    - tests/fixtures/sidra_5938_sample.json
    - tests/fixtures/sidra_4709_sample.json
  modified: []

key-decisions:
  - "Population table routing at year 2022 boundary: 6579 for <=2021, 4709 for >=2022"
  - "GDP per capita computed as gdp_abs * 1000 / populacao (not a SIDRA variable)"
  - "GDP 2022-2023 flagged as estimated via gdp_estimated boolean column"
  - "data_sources/processed/ibge_sidra/.gitkeep not committed (directory is gitignored, created at runtime)"

patterns-established:
  - "SIDRA extractor pattern: fetch_*_year() for single-year, extract_*() for multi-year with validation"
  - "JSON fixture mocking: sidrapy.get_table() mocked via monkeypatch returning fixture DataFrames"
  - "Retry with exponential backoff: 3 retries, 5s base delay for SIDRA API calls"

requirements-completed: [DATA-03]

# Metrics
duration: 3min
completed: 2026-04-02
---

# Phase 03 Plan 01: IBGE SIDRA Extraction Summary

**SIDRA population (tables 6579/4709) and GDP (table 5938) extractor with per-capita computation, table routing at 2022 boundary, and estimated-year flagging**

## Performance

- **Duration:** 3 min
- **Started:** 2026-04-02T02:03:30Z
- **Completed:** 2026-04-02T02:06:41Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- Population extraction with automatic table routing (6579 for 2015-2021, 4709 for 2022-2023)
- GDP extraction with per-capita computation (gdp_abs * 1000 / populacao) and estimated-year flagging
- 12 offline unit tests with monkeypatched sidrapy and JSON fixtures covering all edge cases
- Retry logic with exponential backoff for SIDRA API resilience

## Task Commits

Each task was committed atomically:

1. **Task 1: Create test fixtures and test suite** - `810a30b` (test) -- RED phase: 12 failing tests + 3 JSON fixtures
2. **Task 2: Implement SIDRA population + GDP extractor** - `1892157` (feat) -- GREEN phase: all 12 tests pass

## Files Created/Modified
- `scripts/extract_ibge_sidra.py` - SIDRA population + GDP extractor with CLI, retry logic, validation gate
- `tests/test_extract_ibge_sidra.py` - 12 unit tests covering table routing, per-capita, NaN coercion, estimated flag
- `tests/fixtures/sidra_6579_sample.json` - Population estimates fixture (table 6579, 5 municipalities)
- `tests/fixtures/sidra_5938_sample.json` - GDP fixture (table 5938, includes "..." and "-" missing values)
- `tests/fixtures/sidra_4709_sample.json` - Census 2022 population fixture (table 4709, 5 municipalities)

## Decisions Made
- Population table routing at year 2022 boundary: table 6579 (variable 9324) for years <= 2021, table 4709 (variable 93) for years >= 2022
- GDP per capita is NOT a SIDRA variable -- computed manually as gdp_abs * 1000 / populacao (table 5938 values in R$ 1,000)
- GDP for 2022-2023 flagged with gdp_estimated=True per IBGE methodological caveats
- .gitkeep for data_sources/processed/ibge_sidra/ not committed since directory is gitignored; script creates it at runtime via mkdir(parents=True, exist_ok=True)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- data_sources/processed/ibge_sidra/.gitkeep could not be committed because data_sources/processed/ is in .gitignore. The directory is created at runtime by the script, so no action needed.

## User Setup Required

None - no external service configuration required.

## Known Stubs

None - all functions are fully implemented with no placeholder data.

## Next Phase Readiness
- Population Parquet provides denominators for all per-100K rate computations (LCoGS indicators)
- GDP Parquet provides Economy dimension (D2) data for composite index
- extract_population() and extract_gdp() ready for integration into database/pipeline.py
- Test pattern (JSON fixtures + monkeypatch) established for remaining SIDRA-based extractors

## Self-Check: PASSED

- [x] scripts/extract_ibge_sidra.py -- FOUND
- [x] tests/test_extract_ibge_sidra.py -- FOUND
- [x] tests/fixtures/sidra_6579_sample.json -- FOUND
- [x] tests/fixtures/sidra_5938_sample.json -- FOUND
- [x] tests/fixtures/sidra_4709_sample.json -- FOUND
- [x] Commit 810a30b -- FOUND
- [x] Commit 1892157 -- FOUND
- [x] 12/12 tests pass

---
*Phase: 03-secondary-source-extraction*
*Completed: 2026-04-02*
