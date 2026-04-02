---
phase: 10-publication-package
plan: 01
subsystem: analysis
tags: [matplotlib, pandas, csv, publication-figures, publication-tables, BMJ, forest-plot, choropleth, correlation-matrix, STROBE, RECORD]

# Dependency graph
requires:
  - phase: 07-statistical-analysis
    provides: PanelOLS regression results
  - phase: 09-spatial-analysis
    provides: choropleth and heatmap generators
  - phase: 09.1-methodology-enhancements
    provides: CI/dispersion helpers, USD conversion, age-standardization
provides:
  - publication_figures.py with 4 public functions (temporal trend, forest plot, orchestrator, CLI)
  - publication_tables.py with 8 public functions (6 table generators, orchestrator, CLI)
  - 4+ publication-ready figures at 300 DPI with colorblind-safe palettes
  - 8+ publication-ready CSV tables with 95% CIs and dual-currency BRL+USD
affects: [10-publication-package]

# Tech tracking
tech-stack:
  added: []
  patterns: [publication figure orchestrator with try/except per figure, table orchestrator with try/except per table, dual-currency reporting pattern via deflate_ipca]

key-files:
  created:
    - analysis/publication_figures.py
    - analysis/publication_tables.py
    - tests/test_publication_figures.py
    - tests/test_publication_tables.py
  modified: []

key-decisions:
  - "Forest plot uses horizontal errorbar with significance stars (* p<0.05, ** p<0.01, *** p<0.001)"
  - "Table 1 wraps reporting.generate_descriptive_table and adds USD columns via BCB exchange rate"
  - "Tables 5-8 group 6 regressions into 3 outcome pairs plus combined summary"
  - "Missingness table pivots wide (variables as rows, years as columns) for RECORD 12.1 compliance"

patterns-established:
  - "Publication orchestrator pattern: individual generators wrapped in try/except, returning Path lists"
  - "Dual-currency reporting: BRL mean columns get _usd suffix via convert_brl_to_usd"

requirements-completed: [PUBL-01, PUBL-02, PUBL-05, PUBL-06]

# Metrics
duration: 6min
completed: 2026-04-02
---

# Phase 10 Plan 01: Publication Figures and Tables Summary

**Publication-ready figures (temporal trend + forest plot at 300 DPI) and 8+ tables (descriptive, dimension, missingness, correlation, regression, sensitivity) with 95% CIs and BRL+USD dual-currency columns**

## Performance

- **Duration:** 6 min
- **Started:** 2026-04-02T05:37:11Z
- **Completed:** 2026-04-02T05:43:00Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Created publication_figures.py with CUDS temporal trend (5 region lines, CI shading) and regression forest plot (6 LCoGS outcomes, significance stars) at 300 DPI
- Created publication_tables.py with 8 public functions generating Tables 1-8 plus sensitivity tables, all with 95% CIs
- Table 1 adds USD columns for monetary variables via BCB exchange rate
- Table 3 missingness summary meets RECORD 12.1 compliance with per-year per-variable reporting
- All 7 tests pass (3 figure tests + 4 table tests)

## Task Commits

Each task was committed atomically:

1. **Task 1: Publication figures module** - `0f48717` (feat)
2. **Task 2: Publication tables module** - `c1715ef` (feat)

## Files Created/Modified
- `analysis/publication_figures.py` - Figure generation: temporal trend, forest plot, orchestrator, CLI
- `analysis/publication_tables.py` - Table generation: 6 generators, orchestrator, CLI
- `tests/test_publication_figures.py` - 3 tests: PNG creation, forest plot creation, orchestrator mock
- `tests/test_publication_tables.py` - 4 tests: CI columns, year coverage, matrix shape, orchestrator mock

## Decisions Made
- Forest plot uses horizontal errorbar layout with significance stars for p-value annotation
- Table 1 wraps existing reporting.generate_descriptive_table and adds USD columns via BCB exchange rate
- Tables 5-8 group 6 PanelOLS regressions into 3 pairs (access+workforce, volume+mortality, financial) plus combined summary
- Missingness table pivots to wide format (variables as rows, years 2015-2023 as columns) for RECORD 12.1 compliance
- Sensitivity tables reuse _extract_cuds_row helper for consistent formatting

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- All figures and tables ready for STROBE/RECORD checklist assembly (Plan 02)
- Publication orchestrators can be run end-to-end once database is populated
- Both modules follow project conventions (%-style logging, section banners, Path objects, type hints)

## Self-Check: PASSED

All files verified present, all commits verified in git log.

- FOUND: analysis/publication_figures.py
- FOUND: analysis/publication_tables.py
- FOUND: tests/test_publication_figures.py
- FOUND: tests/test_publication_tables.py
- FOUND: .planning/phases/10-publication-package/10-01-SUMMARY.md
- FOUND: commit 0f48717
- FOUND: commit c1715ef

---
*Phase: 10-publication-package*
*Completed: 2026-04-02*
