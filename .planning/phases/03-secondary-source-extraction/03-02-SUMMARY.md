---
phase: 03-secondary-source-extraction
plan: 02
subsystem: database
tags: [ipea, idhm, ifgf, firjan, odata, excel, parquet, human-capital, governance]

# Dependency graph
requires:
  - phase: 01-foundation
    provides: normalize_cod_ibge(), validate_dataframe(), IBGE reference list
provides:
  - IPEA IDHM extraction script (cross-sectional 2010, 4 sub-indices)
  - FIRJAN IFGF Excel parser (2015-2023, 6 columns, MNAR preserved as NaN)
  - Test suites with fixtures for offline development (15 tests)
affects: [04-database-assembly, 05-dimension-computation]

# Tech tracking
tech-stack:
  added: []
  patterns: [raw-odata-api-for-ipea, mnar-nan-preservation, cross-sectional-flagging]

key-files:
  created:
    - scripts/extract_ipea_idhm.py
    - scripts/extract_ifgf.py
    - tests/test_extract_ipea_idhm.py
    - tests/test_extract_ifgf.py
    - tests/fixtures/ipea_idhm_sample.json
    - data_sources/processed/ipea_idhm/.gitkeep
    - data_sources/processed/ifgf/.gitkeep
  modified: []

key-decisions:
  - "Used raw IPEA OData4 API (not ipeadatapy.timeseries) to preserve TERCODIGO municipality codes"
  - "IDHM locked to 2010 cross-sectional only -- 2022 IDHM not published"
  - "IFGF MNAR municipalities preserved as NaN (not zero, not dropped) per locked decision"

patterns-established:
  - "Raw OData API pattern: use requests directly when library strips critical fields"
  - "Cross-sectional source flagging: explicit docstring + log messages when data is non-time-varying"
  - "MNAR preservation: never replace missing fiscal data with zero -- document and preserve NaN"

requirements-completed: [DATA-04, DATA-05]

# Metrics
duration: 6min
completed: 2026-04-02
---

# Phase 3 Plan 02: IPEA IDHM & FIRJAN IFGF Extraction Summary

**IDHM via raw IPEA OData API (2010 cross-sectional, 4 sub-indices) and IFGF from Excel (2015-2023, MNAR preserved as NaN) with TDD test suites**

## Performance

- **Duration:** 6 min
- **Started:** 2026-04-02T02:04:56Z
- **Completed:** 2026-04-02T02:10:40Z
- **Tasks:** 2
- **Files modified:** 9

## Accomplishments
- IPEA IDHM extraction using raw OData4 API (bypassing ipeadatapy which strips TERCODIGO)
- FIRJAN IFGF Excel parser with MNAR municipality preservation as NaN
- Full TDD workflow: 15 tests (8 IDHM + 7 IFGF) all passing with mocked/fixture data
- Both scripts follow codebase conventions: normalize_cod_ibge(), validate_dataframe(), section banners, %-style logging

## Task Commits

Each task was committed atomically:

1. **Task 1: IPEA IDHM extractor with test suite**
   - `84d06f7` (test) - RED: failing tests for IDHM extraction
   - `c3fb844` (feat) - GREEN: implement IDHM extraction via raw OData API
2. **Task 2: FIRJAN IFGF Excel parser with test suite**
   - `bff5bcf` (test) - RED: failing tests for IFGF parser
   - `37da44f` (feat) - GREEN: implement IFGF parser with MNAR preservation

_TDD tasks each have two commits (test -> feat)_

## Files Created/Modified
- `scripts/extract_ipea_idhm.py` - IDHM extraction via raw IPEA OData4 API with retry logic
- `scripts/extract_ifgf.py` - IFGF Excel parser with MNAR NaN preservation
- `tests/test_extract_ipea_idhm.py` - 8 tests: municipality filtering, year filtering, cod_ibge normalization, 4-series merge
- `tests/test_extract_ifgf.py` - 7 tests: column mapping, year filtering, MNAR preservation, FileNotFoundError
- `tests/fixtures/ipea_idhm_sample.json` - OData API response fixture with municipality/national/multi-year rows
- `data_sources/processed/ipea_idhm/.gitkeep` - Output directory placeholder
- `data_sources/processed/ifgf/.gitkeep` - Output directory placeholder

## Decisions Made
- Used raw requests to IPEA OData4 API instead of ipeadatapy.timeseries() -- ipeadatapy strips TERCODIGO field making municipality identification impossible (Pitfall 4 from RESEARCH.md)
- IDHM locked to 2010 only -- IDHM 2022 has NOT been published (Atlas do Desenvolvimento Humano awaits Census 2022 microdata processing, Pitfall 5)
- IFGF MNAR municipalities preserved as NaN per locked decision -- approximately 420 municipalities/year have missing fiscal data due to reporting failures; these must not be replaced with zero or dropped
- IFGF test fixture generated programmatically via openpyxl in session-scoped pytest fixture (avoids committing binary Excel files)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - both tasks implemented cleanly following TDD RED-GREEN flow.

## User Setup Required

None - no external service configuration required. IFGF Excel file must be manually downloaded from https://www.firjan.com.br/ifgf/ and placed in data_sources/ before running extract_ifgf.py in production.

## Known Stubs

None - both scripts are fully functional with real API/file inputs. Test fixtures provide offline development capability.

## Next Phase Readiness
- IDHM Parquet output ready for Human Capital (D3) dimension computation in Phase 5
- IFGF Parquet output ready for Governance (D1) dimension computation in Phase 5
- Both scripts integrate with database/utils.py (normalize_cod_ibge) and database/validation.py (validate_dataframe)
- Remaining Phase 3 plans (03-03 ANS/Census, 03-04 RENAVAM/SIOPS) can proceed independently

## Self-Check: PASSED

All 7 created files verified present. All 4 task commits (84d06f7, c3fb844, bff5bcf, 37da44f) verified in git log.

---
*Phase: 03-secondary-source-extraction*
*Completed: 2026-04-02*
