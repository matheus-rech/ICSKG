---
phase: 10-publication-package
plan: 02
subsystem: reporting
tags: [strobe, record, data-dictionary, zenodo, ethics, compliance, bmj]

# Dependency graph
requires:
  - phase: 10-01
    provides: publication figures and tables
  - phase: 04-panel-assembly-validation
    provides: SQLite schema (build_database_v3.py DDL)
  - phase: 05-dimension-computation-cuds
    provides: CIMI_DIMENSIONS metadata, DIMENSION_MAP
  - phase: 06-lcogs-indicators
    provides: LCOGS_METADATA definitions
provides:
  - STROBE 22-item compliance checklist (CSV)
  - RECORD 13-item extension checklist (CSV)
  - Ethics statement citing Resolution 510/2016
  - Data availability statement with 10 source portal URLs
  - Zenodo metadata JSON (CC-BY-4.0)
  - Release checklist for DOI minting and GitHub tag
  - Data dictionary generator from SQLite PRAGMA with schema validation
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Hardcoded compliance checklist as module-level list[dict] constants
    - PRAGMA table_info for SQLite schema introspection
    - Priority-ordered metadata lookup (CIMI > LCoGS > panel > standard)
    - Schema validation via set comparison of (table, column) pairs

key-files:
  created:
    - analysis/strobe_record.py
    - analysis/zenodo_prep.py
    - analysis/data_dictionary.py
    - tests/test_strobe_record.py
    - tests/test_data_dictionary.py
  modified: []

key-decisions:
  - "STROBE items use domain-specific manuscript section references (not generic placeholders)"
  - "RECORD 13 items all cross-reference corresponding STROBE items"
  - "Data dictionary enrichment uses 4-tier lookup: CIMI > LCoGS > panel source > standard columns"
  - "Missingness computed from actual SQLite queries, not hardcoded values"
  - "Zenodo metadata written to both results/ and project root (.zenodo.json) for GitHub integration"

patterns-established:
  - "Compliance checklist pattern: module-level list[dict] constants -> DataFrame -> CSV"
  - "Schema-driven documentation: PRAGMA table_info + metadata enrichment"

requirements-completed: [PUBL-03, PUBL-04, PUBL-07, PUBL-08, PUBL-09, PUBL-10]

# Metrics
duration: 7min
completed: 2026-04-02
---

# Phase 10 Plan 02: Reporting Compliance Summary

**STROBE/RECORD checklists (22+13 items, no blanks), data dictionary from SQLite PRAGMA with schema validation, ethics/data statements, Zenodo release prep**

## Performance

- **Duration:** 7 min
- **Started:** 2026-04-02T05:36:56Z
- **Completed:** 2026-04-02T05:44:09Z
- **Tasks:** 2 auto + 1 checkpoint (pending)
- **Files modified:** 5

## Accomplishments
- STROBE 22-item checklist with ICSKG-BR-specific manuscript section references and domain notes
- RECORD 13-item extension with all items populated (no blank manuscript_section fields)
- Data dictionary generator that introspects SQLite schema via PRAGMA and enriches with variable metadata from CIMI_DIMENSIONS, LCOGS_METADATA, and DIMENSION_MAP
- Ethics statement citing Brazilian Resolution 510/2016 and Law 12.527/2011
- Data availability statement listing 10 public source portal URLs
- Zenodo metadata JSON (CC-BY-4.0) with release checklist for DOI minting
- 15 tests covering all outputs (10 for STROBE/RECORD/Zenodo, 5 for data dictionary)

## Task Commits

Each task was committed atomically:

1. **Task 1: STROBE/RECORD checklists, ethics/data statements, Zenodo prep** - `17f5e78` (feat)
2. **Task 2: Data dictionary from SQLite schema with validation** - `168659d` (feat)
3. **Task 3: Verify complete BMJ Global Health submission package** - checkpoint:human-verify (pending)

## Files Created/Modified
- `analysis/strobe_record.py` - STROBE (22 items) + RECORD (13 items) checklist generators, ethics and data availability statement generators
- `analysis/zenodo_prep.py` - Zenodo metadata JSON generator and release checklist
- `analysis/data_dictionary.py` - Data dictionary from SQLite PRAGMA with 4-tier metadata enrichment and schema validation
- `tests/test_strobe_record.py` - 10 tests for checklists, statements, and Zenodo metadata
- `tests/test_data_dictionary.py` - 5 tests for dictionary generation, missingness, and validation

## Decisions Made
- STROBE items use domain-specific manuscript section references (e.g., "Methods: Statistical Methods" not just "[Section X]") with ICSKG-BR-specific notes
- RECORD 13 items all cross-reference corresponding STROBE items per EQUATOR Network guidelines
- Data dictionary uses 4-tier metadata lookup priority: CIMI dimension metadata > LCoGS indicator metadata > panel source column metadata > standard schema columns
- Missingness rates computed from actual SQLite queries (not hardcoded) for data tables only (municipal_health, dimension_scores, lcogs_indicators)
- Zenodo metadata written to both results/zenodo_metadata.json and .zenodo.json at project root for GitHub-Zenodo integration

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Worktree .venv was a symlink to main repo causing "too many levels of symbolic links" error; resolved by creating a local venv with `uv venv .venv && uv sync`

## Known Stubs

None - all outputs are fully wired to data sources or constants.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Task 3 checkpoint awaiting human verification of complete submission package
- All automated deliverables for Plan 02 are complete
- Human needs to: verify checklists, run full generation pipeline against real DB, follow release checklist for Zenodo DOI and GitHub tag

## Self-Check: PASSED

All created files verified to exist; both commit hashes confirmed in git log.

---
*Phase: 10-publication-package*
*Completed: 2026-04-02*
