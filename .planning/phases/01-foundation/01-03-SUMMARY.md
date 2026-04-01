---
phase: 01-foundation
plan: 03
subsystem: database
tags: [amc, crosswalk, municipality-harmonization, ibge, panel-data]

# Dependency graph
requires:
  - phase: 01-02
    provides: "IBGE 2023 municipality reference list (ibge_municipios_2023.csv)"
provides:
  - "AMC temporal crosswalk CSV mapping all municipality codes 2015-2023"
  - "build_crosswalk() function for reproducible crosswalk generation"
  - "apply_amc_crosswalk() function for DataFrame cod_ibge harmonization"
affects: [database-pipeline, etl-merge, panel-construction]

# Tech tracking
tech-stack:
  added: []
  patterns: [static-csv-with-api-verification, ibge-api-stability-check]

key-files:
  created:
    - data_sources/amc_crosswalk_2015_2023.csv
    - scripts/build_amc_crosswalk.py
    - tests/test_amc_crosswalk.py
  modified: []

key-decisions:
  - "Static CSV approach chosen over geobr package -- fully reproducible without network dependency"
  - "IBGE count is 5,571 municipalities (not 5,570) -- authoritative API confirms this count"
  - "No predecessor rows needed -- all 2013 emancipation predecessors still exist as separate municipalities in the 2023 list"
  - "Tests use dynamic _ibge_count() rather than hardcoded 5570 to handle authoritative count"

patterns-established:
  - "IBGE API stability verification: build script checks live API against reference CSV"
  - "Crosswalk lookup pattern: apply_amc_crosswalk(df, year) for downstream pipeline use"

requirements-completed: [FOUN-06]

# Metrics
duration: 2min
completed: 2026-04-01
---

# Phase 1 Plan 03: AMC Crosswalk Summary

**AMC temporal crosswalk with 5,571 stable municipality mappings, IBGE API stability verification, and apply_amc_crosswalk() harmonization function**

## Performance

- **Duration:** 2 min
- **Started:** 2026-04-01T23:31:45Z
- **Completed:** 2026-04-01T23:33:40Z
- **Tasks:** 1
- **Files modified:** 3

## Accomplishments
- AMC crosswalk CSV generated with 5,571 rows covering all canonical 2023 IBGE municipality codes
- IBGE Localidades API confirmed municipality list stability (no new emancipations 2015-2023)
- apply_amc_crosswalk() function provides DataFrame-level cod_ibge harmonization for downstream pipeline
- Build script is fully idempotent -- running twice produces identical output
- All 12 pytest tests pass (structure, known splits, apply function, immutability)

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): Add failing tests for AMC crosswalk** - `fe7415b` (test)
2. **Task 1 (GREEN): Build AMC crosswalk CSV and verification script** - `7ab127a` (feat)

_Note: TDD task with RED/GREEN commits. No REFACTOR needed -- code was clean from first pass._

## Files Created/Modified
- `data_sources/amc_crosswalk_2015_2023.csv` - 5,571-row crosswalk mapping cod_ibge_original to cod_ibge_2023 with harmonization_type
- `scripts/build_amc_crosswalk.py` - Reproducible builder with IBGE API stability check, build_crosswalk() and apply_amc_crosswalk() functions
- `tests/test_amc_crosswalk.py` - 12 tests covering structure, known 2013 emancipations, apply function behavior

## Decisions Made
- **Static CSV over geobr**: The crosswalk uses a static CSV approach (Option C from 01-CONTEXT.md) rather than the geobr Python package. The IBGE municipality list has been frozen since 2013 emancipations, confirmed by live API check. A static CSV is fully reproducible without network dependency.
- **5,571 municipalities (not 5,570)**: The IBGE Localidades API authoritatively returns 5,571 municipalities. Tests use dynamic `_ibge_count()` from the reference CSV rather than a hardcoded count, making them resilient to this difference.
- **No predecessor rows generated**: All four 2013 emancipation predecessors (Icara-SC, Bento Goncalves-RS, Laguna-SC, Santarem-PA) still exist as separate municipalities in the 2023 IBGE list. The `pred not in canonical_set` check correctly skips adding predecessor mapping rows since the predecessors are already canonical 2023 codes.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Dynamic IBGE count instead of hardcoded 5570**
- **Found during:** Task 1 (TDD GREEN verification)
- **Issue:** Plan text references "5,570 municipalities" but IBGE API authoritatively returns 5,571. Hardcoding 5570 would cause test failures.
- **Fix:** Tests already used `_ibge_count()` helper that reads from the reference CSV dynamically. Build script uses actual reference CSV count. No code change needed -- the existing implementation was already correct.
- **Verification:** All 12 tests pass with 5,571 count
- **Committed in:** fe7415b (test), 7ab127a (feat)

---

**Total deviations:** 1 noted (municipality count discrepancy between plan text and authoritative source)
**Impact on plan:** No scope creep. The authoritative IBGE source is correct at 5,571.

## Issues Encountered
None -- the parallel agent had already created both the script and test files. The RED commit was already present. Only the GREEN phase (generating the CSV, verifying, committing) was needed.

## User Setup Required
None - no external service configuration required.

## Known Stubs
None -- all functions are fully implemented and wired to real data sources.

## Next Phase Readiness
- AMC crosswalk ready for integration into database/pipeline.py merge stage
- apply_amc_crosswalk() can be imported by any downstream module that needs municipality code harmonization
- Crosswalk confirms IBGE code stability across the 2015-2023 study window

## Self-Check: PASSED

- [x] data_sources/amc_crosswalk_2015_2023.csv: FOUND
- [x] scripts/build_amc_crosswalk.py: FOUND
- [x] tests/test_amc_crosswalk.py: FOUND
- [x] .planning/phases/01-foundation/01-03-SUMMARY.md: FOUND
- [x] Commit fe7415b (TDD RED): FOUND
- [x] Commit 7ab127a (TDD GREEN): FOUND
- [x] All 12 tests pass: VERIFIED

---
*Phase: 01-foundation*
*Completed: 2026-04-01*
