---
phase: 01-foundation
plan: 02
subsystem: database
tags: [pandas, ibge, municipality-codes, normalization, etl]

# Dependency graph
requires:
  - phase: 01-01
    provides: Python 3.12 environment with pandas, numpy, pytest
provides:
  - normalize_cod_ibge() shared utility for 7-digit zero-padded IBGE codes
  - normalize_column_name() for mapping 10 source column variants to cod_ibge
  - rename_municipality_column() for DataFrame column renaming
  - load_ibge_municipios() returning 5,570-row canonical reference
  - IBGE 2023 municipality reference CSV (5,570 rows)
affects: [01-03, 01-04, 02-acquisition, 03-parsers, 04-assembly, 05-dimensions]

# Tech tracking
tech-stack:
  added: []
  patterns: [normalize-before-join, canonical-7digit-ibge, null-mask-nan-preservation]

key-files:
  created:
    - database/utils.py
    - database/__init__.py
    - data_sources/ibge_municipios_2023.csv
    - tests/test_utils.py
    - tests/test_ibge_reference.py
    - tests/__init__.py
  modified: []

key-decisions:
  - "6-digit codes zero-padded to 7 digits (not check-digit computed) -- IBGE check digit algorithm unreliable without full lookup table"
  - "NaN preserved via null_mask pattern, not coerced to string 'nan'"
  - "10 column name variants mapped (Cod_IBGE, CD_MUNICIPIO, CD_MUN, MUNIC_RES, MUNIC_MOV, CODUFMUN, cod_ibge, COD_MUNICIPIO, Municipio, IBGE_MUNICIPIO)"

patterns-established:
  - "normalize-before-join: always call normalize_cod_ibge() before any merge/join on municipality codes"
  - "canonical-7digit: all cod_ibge values are 7-digit zero-padded strings, never ints"
  - "reference-gate: load_ibge_municipios() asserts 5,570 rows -- any corruption detected immediately"

requirements-completed: [FOUN-02, FOUN-03]

# Metrics
duration: 2min
completed: 2026-04-01
---

# Phase 1 Plan 02: Municipality Code Normalization Summary

**normalize_cod_ibge() utility handling 6 input formats with NaN preservation, plus canonical IBGE 2023 reference list (5,570 municipalities)**

## Performance

- **Duration:** 2 min
- **Started:** 2026-04-01T23:31:44Z
- **Completed:** 2026-04-01T23:34:00Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- IBGE 2023 municipality reference CSV downloaded via API with 5,570 unique 7-digit codes, sorted deterministically
- database/utils.py created with normalize_cod_ibge(), normalize_column_name(), rename_municipality_column(), load_ibge_municipios()
- normalize_cod_ibge() handles all 6 input formats: 7-digit int, 7-digit string, 6-digit int, 6-digit string, whitespace-padded, NaN
- 23 tests across 2 test files all passing (17 in test_utils.py, 6 in test_ibge_reference.py)

## Task Commits

Each task was committed atomically:

1. **Task 1: Download IBGE 2023 municipality reference list**
   - `057b755` (test: add failing tests for IBGE 2023 reference CSV) -- RED
   - `b59a07b` (feat: download IBGE 2023 municipality reference list) -- GREEN
2. **Task 2: Create database/utils.py with normalize_cod_ibge() and tests**
   - `63f1c0d` (test: add failing tests for database/utils.py) -- RED
   - `61d7950` (feat: implement normalize_cod_ibge() and load_ibge_municipios()) -- GREEN

_Note: TDD tasks have RED (test) then GREEN (implementation) commits_

## Files Created/Modified
- `database/utils.py` - Shared utilities: normalize_cod_ibge(), normalize_column_name(), rename_municipality_column(), load_ibge_municipios()
- `database/__init__.py` - Package init enabling `from database.utils import ...`
- `data_sources/ibge_municipios_2023.csv` - Canonical IBGE 2023 list of 5,570 municipalities (cod_ibge, nome_municipio, uf)
- `tests/test_utils.py` - 17 tests covering all normalize_cod_ibge edge cases, column name mapping, DataFrame renaming, reference loading
- `tests/test_ibge_reference.py` - 6 tests validating CSV structure, row count, code uniqueness, digit length, UF format
- `tests/__init__.py` - Test package init

## Decisions Made
- 6-digit codes zero-padded to 7 digits (not check-digit computed) -- the IBGE check digit algorithm is unreliable without the full lookup table, and zero-padding is the documented approach in ARCHITECTURE.md
- NaN preserved via null_mask + np.nan restoration pattern, preventing silent "nan" string corruption
- 10 column name variants mapped covering all known data sources (SIH, CNES, ANS, IFGF, shapefiles, SIOPS, RENAVAM)
- database/__init__.py created to enable package-style imports (auto-added, Rule 3 -- blocking issue)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added database/__init__.py for package imports**
- **Found during:** Task 2 (database/utils.py creation)
- **Issue:** `from database.utils import normalize_cod_ibge` fails without `database/__init__.py`
- **Fix:** Created empty `database/__init__.py` to make database/ a proper Python package
- **Files modified:** database/__init__.py
- **Verification:** All 17 tests in test_utils.py pass with the import
- **Committed in:** 61d7950 (part of Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Essential for imports to work. No scope creep.

## Issues Encountered
None -- prior agent completed TDD RED phases and IBGE CSV download; this execution completed the GREEN phases.

## Known Stubs
None -- all functions are fully implemented with no placeholder data or TODOs.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- normalize_cod_ibge() ready for all downstream parsers (Plan 01-03 config.yaml, Plan 01-04 validation gate)
- load_ibge_municipios() provides the canonical 5,570-row reference for completeness checks
- MUNICIPALITY_CODE_COLUMNS dict available for any new column variant discovery

## Self-Check: PASSED

- All 6 created files exist on disk
- All 4 commit hashes found in git log
- 23/23 tests passing (17 test_utils.py + 6 test_ibge_reference.py)
- FOUN-02 and FOUN-03 verification scripts pass

---
*Phase: 01-foundation*
*Completed: 2026-04-01*
