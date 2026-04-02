---
phase: 01-foundation
plan: 04
subsystem: database
tags: [validation, pandas, parquet, quarantine, data-quality]

# Dependency graph
requires:
  - phase: 01-foundation/02
    provides: "database/utils.py with load_ibge_municipios() and normalize_cod_ibge()"
provides:
  - "database/validation.py: validate_dataframe(), ValidationError, ValidationReport, write_validation_report()"
  - "Quarantine pipeline writing bad rows to data_sources/quarantine/ as Parquet"
  - "Configurable strictness: strict=True raises, strict=False quarantines+continues"
affects: [02-acquisition, 03-dimension-computation, database-pipeline]

# Tech tracking
tech-stack:
  added: []
  patterns: ["validation gate before merge", "quarantine bad rows as Parquet with reason metadata", "dataclass-based report serialization"]

key-files:
  created:
    - database/validation.py
    - tests/test_validation.py
  modified: []

key-decisions:
  - "Used datetime.now(timezone.utc) instead of deprecated datetime.utcnow() for Python 3.12 compatibility"
  - "Lazy import of load_ibge_municipios inside validate_dataframe to avoid circular dependency at module level"
  - "Quarantine files include _quarantine_reason, _quarantine_source, _quarantine_timestamp columns for traceability"

patterns-established:
  - "Validation gate pattern: validate_dataframe() returns (clean_df, report) tuple"
  - "Quarantine pattern: bad rows written to data_sources/quarantine/{source}_{timestamp}_{check}_quarantine.parquet"
  - "Configurable strictness: strict=True for CI/debugging, strict=False (default) for pipeline resilience"

requirements-completed: [FOUN-04]

# Metrics
duration: 2min
completed: 2026-04-01
---

# Phase 1 Plan 4: Validation Gate Summary

**Validation gate with 4-check pipeline (schema, IBGE code, year scope, duplicates), configurable strict/quarantine modes, and JSON report output**

## Performance

- **Duration:** 2 min
- **Started:** 2026-04-01T23:37:07Z
- **Completed:** 2026-04-01T23:39:55Z
- **Tasks:** 1 (TDD: RED + GREEN)
- **Files modified:** 2

## Accomplishments
- Created database/validation.py with validate_dataframe() implementing 4 validation checks (schema conformance, municipality code validity, year scope, duplicate keys)
- Configurable strictness: strict=True raises ValidationError on first failure; strict=False (default) quarantines bad rows to data_sources/quarantine/ and continues
- ValidationReport dataclass with to_dict() and write_validation_report() for JSON persistence
- 10 pytest tests covering strict mode, quarantine mode, report serialization, and both ROADMAP success criteria

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): Failing tests for validation gate** - `fa3c057` (test)
2. **Task 1 (GREEN): Implement validation gate** - `949e7c1` (feat)

_TDD task: test commit followed by implementation commit_

## Files Created/Modified
- `database/validation.py` - Validation gate: schema checks, range checks, municipality code audit, duplicate detection, quarantine pipeline, JSON report
- `tests/test_validation.py` - 10 tests covering strict mode (5), quarantine mode (3), report serialization (2)

## Decisions Made
- Used `datetime.now(timezone.utc)` instead of deprecated `datetime.utcnow()` for Python 3.12 compatibility (auto-fix, Rule 1)
- Lazy import of `load_ibge_municipios` inside `validate_dataframe()` to avoid circular imports at module level (follows codebase convention for optional/deferred imports)
- Quarantine Parquet files include metadata columns (`_quarantine_reason`, `_quarantine_source`, `_quarantine_timestamp`) for downstream traceability

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed deprecated datetime.utcnow() for Python 3.12**
- **Found during:** Task 1 (GREEN phase implementation)
- **Issue:** Plan code used `datetime.utcnow()` which is deprecated in Python 3.12 and scheduled for removal
- **Fix:** Replaced with `datetime.now(timezone.utc)` throughout
- **Files modified:** database/validation.py
- **Verification:** No deprecation warnings in test output
- **Committed in:** 949e7c1 (Task 1 GREEN commit)

---

**Total deviations:** 1 auto-fixed (1 bug fix)
**Impact on plan:** Trivial fix for Python 3.12 compatibility. No scope creep.

## Issues Encountered
None

## Known Stubs
None - all validation checks are fully implemented and wired to the IBGE reference data.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Validation gate ready to be integrated into `run_pipeline()` in database/pipeline.py (called after each `extract_*()` function)
- Quarantine directory pattern established for all future data quality operations
- ValidationReport can be aggregated across sources for pipeline-level quality dashboards

## Self-Check: PASSED

All files exist, all commits verified, all exports present, all tests confirmed.

---
*Phase: 01-foundation*
*Completed: 2026-04-01*
