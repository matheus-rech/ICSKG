---
phase: 02-sih-cnes-extraction
plan: 04
subsystem: database
tags: [cnes, pysus, cbo, sao, parquet, datasus, professional-extraction]

# Dependency graph
requires:
  - phase: 02-sih-cnes-extraction/02-03
    provides: "CBO_SAO constants, extract_cnes_facilities(), filter_bellwether_facilities()"
provides:
  - "download_cnes_pf() for DATASUS FTP PF file acquisition via PySUS"
  - "extract_cnes_professionals() for SAO workforce extraction with CBO filter and CNS dedup"
  - "Rewired pipeline.py extract_cnes() calling both facility and professional extractors"
affects: [03-remaining-sources, 06-lcogs-indicators]

# Tech tracking
tech-stack:
  added: [pysus-cnes-download]
  patterns: [per-professional-validation-bypass, best-effort-download]

key-files:
  created: [tests/fixtures/cnes_pf_sample.csv]
  modified: [scripts/cnes_extract.py, tests/test_cnes_extract.py, database/pipeline.py]

key-decisions:
  - "Professional data uses custom validation (cod_ibge + year scope) instead of standard validate_dataframe() -- standard gate's no_duplicate_keys check is designed for municipality-year aggregates, not per-professional rows"
  - "PF download is best-effort wrapper around PySUS -- graceful degradation if DATASUS FTP unavailable"
  - "PF fixture uses real 7-digit IBGE codes (3550308, 1200203, 3304557) to pass validation gate's cod_ibge check"

patterns-established:
  - "Best-effort download pattern: download function logs errors and returns empty list on failure; extraction function processes whatever files are available"
  - "Per-record validation: skip duplicate-key check for non-aggregated data, validate only cod_ibge membership and year scope"

requirements-completed: [DATA-02]

# Metrics
duration: 5min
completed: 2026-04-02
---

# Phase 2 Plan 04: CNES PF Professional Extraction Summary

**CNES PF professional download via PySUS and SAO extraction with CBO filtering, CNS deduplication, and sao_category classification**

## Performance

- **Duration:** 5 min
- **Started:** 2026-04-02T01:16:39Z
- **Completed:** 2026-04-02T01:21:52Z
- **Tasks:** 2/3 automated (Task 3 is human-verify checkpoint)
- **Files modified:** 4

## Accomplishments
- Implemented download_cnes_pf() wrapping PySUS for DATASUS FTP PF file acquisition (all 27 UFs supported)
- Implemented extract_cnes_professionals() with CBO_SAO filtering (11 codes), CNS dedup per municipality-year, and sao_category classification
- Rewired pipeline.py extract_cnes() to call both facility and professional extractors with best-effort PF handling
- All 75 tests pass (6 new professional extraction + 14 existing CNES + 55 other)

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): CNES PF tests** - `53dab9d` (test) - Failing tests and PF fixture
2. **Task 1 (GREEN): CNES PF implementation** - `7b1b375` (feat) - download_cnes_pf, extract_cnes_professionals, CLI extensions
3. **Task 2: Rewire pipeline.py** - `cbdb596` (feat) - extract_cnes() now uses scripts.cnes_extract module
4. **Task 3: Human verification** - checkpoint (pending)

## Files Created/Modified
- `tests/fixtures/cnes_pf_sample.csv` - 8-row PF fixture with SAO, non-SAO, dedup, and multi-municipality test cases
- `scripts/cnes_extract.py` - Added download_cnes_pf(), extract_cnes_professionals(), UF_CODES, CNES_PF_COLS; updated CLI
- `tests/test_cnes_extract.py` - 6 new tests: columns, CBO filter, CNS dedup, sao_category, normalize, parquet write
- `database/pipeline.py` - Rewired extract_cnes() from continue_raw_download to scripts.cnes_extract

## Decisions Made
- **Custom validation for professionals:** Standard validate_dataframe() checks for duplicate (cod_ibge, year) keys, but professional data legitimately has multiple rows per municipality-year (one per professional). Used direct cod_ibge membership check + year scope validation instead.
- **Best-effort PF download:** PySUS download wraps DATASUS FTP which is unreliable. The download logs errors and returns empty list on failure. The extraction function processes whatever files exist in input_dir.
- **Real IBGE codes in fixture:** PF fixture uses real 7-digit codes (3550308 Sao Paulo, 1200203 Cruzeiro do Sul, 3304557 Rio de Janeiro) so validation gate's IBGE reference check passes.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed validation gate incompatibility with professional-level data**
- **Found during:** Task 1 (GREEN phase, test execution)
- **Issue:** validate_dataframe() checks for duplicate (cod_ibge, year) keys, quarantining legitimate multi-professional rows. All test data was being quarantined.
- **Fix:** Replaced validate_dataframe() call with direct cod_ibge membership check + year scope validation in extract_cnes_professionals()
- **Files modified:** scripts/cnes_extract.py
- **Verification:** All 6 professional tests pass
- **Committed in:** 7b1b375

**2. [Rule 1 - Bug] Fixed test fixture with real IBGE codes**
- **Found during:** Task 1 (GREEN phase, test execution)
- **Issue:** Original fixture used 6-digit codes (355030, 120020, 330455) which after zero-padding to 7 digits (0355030, etc.) were not in the IBGE reference list, causing validation to quarantine all rows.
- **Fix:** Updated fixture to use real 7-digit IBGE codes: 3550308 (Sao Paulo), 1200203 (Cruzeiro do Sul), 3304557 (Rio de Janeiro)
- **Files modified:** tests/fixtures/cnes_pf_sample.csv, tests/test_cnes_extract.py
- **Verification:** All tests pass with real IBGE codes
- **Committed in:** 7b1b375

---

**Total deviations:** 2 auto-fixed (2 bugs)
**Impact on plan:** Both fixes necessary for correctness. Custom validation approach is appropriate since professional data is inherently non-aggregated. No scope creep.

## Issues Encountered
- Disk space nearly exhausted during implementation (211MB remaining); cleaned caches to recover 674MB. No impact on deliverables.

## Known Stubs
None -- all functions are fully implemented. download_cnes_pf() is a complete PySUS wrapper; it will function when DATASUS FTP is accessible. extract_cnes_professionals() processes any available PF files.

## User Setup Required
- **DATASUS FTP access:** Required for downloading CNES PF files. Use `python scripts/cnes_extract.py --download-pf --year 2023` to download.
- **NAS mount:** Required for CNES ST facility data at `/Volumes/docker/Downloads2/ETLCNES.zip`.

## Next Phase Readiness
- CNES facility and professional extraction code is complete
- Pipeline.py properly routes to both extractors
- Human verification (Task 3) pending: verify against real NAS data
- After verification, Phase 2 is complete and ready for Phase 3 (remaining data sources)

## Self-Check: PASSED

- scripts/cnes_extract.py: FOUND
- tests/test_cnes_extract.py: FOUND
- tests/fixtures/cnes_pf_sample.csv: FOUND
- database/pipeline.py: FOUND
- 02-04-SUMMARY.md: FOUND
- Commit 53dab9d: FOUND
- Commit 7b1b375: FOUND
- Commit cbdb596: FOUND

---
*Phase: 02-sih-cnes-extraction*
*Completed: 2026-04-02*
