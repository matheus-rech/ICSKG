---
phase: 03-secondary-source-extraction
plan: 03
subsystem: data-extraction
tags: [ans, census-2022, sidra, sanitation, health-insurance, parquet, pandas]

# Dependency graph
requires:
  - phase: 01-foundation
    provides: normalize_cod_ibge(), validate_dataframe(), IBGE reference list
provides:
  - ANS quarterly average beneficiary extractor (scripts/extract_ans_quarterly.py)
  - Census 2022 sanitation extractor (scripts/extract_census_sanitation.py)
  - ANS panel Parquet (cod_ibge, year, beneficiarios_mean, coverage_rate, sus_dependence)
  - Census sanitation Parquet (cod_ibge, year, pct_sanitation_adequate, pct_water_adequate)
affects: [04-panel-assembly, 05-dimension-computation]

# Tech tracking
tech-stack:
  added: [sidrapy]
  patterns: [quarterly-averaging, cross-sectional-flag, sidra-metadata-skip]

key-files:
  created:
    - scripts/extract_ans_quarterly.py
    - scripts/extract_census_sanitation.py
    - tests/test_extract_ans_quarterly.py
    - tests/test_extract_census_sanitation.py
    - tests/fixtures/ans_quarterly_sample.csv
    - tests/fixtures/sidra_6805_sample.json
    - data_sources/processed/ans/.gitkeep
    - data_sources/processed/census_sanitation/.gitkeep
  modified: []

key-decisions:
  - "ANS quarterly average uses Q1-Q4 mean per locked decision, not December snapshot"
  - "Census 2022 sanitation is cross-sectional year=2022 applied to all panel years per locked decision"
  - "compute_coverage_rate() accepts population_df parameter directly for testability (not just Path)"

patterns-established:
  - "SIDRA metadata skip: df.iloc[1:] after sidrapy.get_table() to drop header row (Pitfall 6)"
  - "Cross-sectional flag: explicit log message and module docstring for non-time-varying data"
  - "ANS 6-digit to 7-digit: normalize_cod_ibge() on CD_MUNICIPIO column (Pitfall 8)"

requirements-completed: [DATA-06, DATA-07]

# Metrics
duration: 4min
completed: 2026-04-02
---

# Phase 3 Plan 3: ANS Quarterly + Census 2022 Sanitation Summary

**ANS quarterly-average beneficiary extractor with SUS dependence rate, and Census 2022 SIDRA-based sanitation/water supply extractor with cross-sectional flagging**

## Performance

- **Duration:** 4 min
- **Started:** 2026-04-02T02:04:35Z
- **Completed:** 2026-04-02T02:08:44Z
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments
- ANS quarterly average computes Q1-Q4 mean (not December snapshot) per municipality per year, with optional coverage rate and SUS dependence computation
- Census 2022 sanitation extracts adequate sewage % (table 6805) and water supply % (table 6803) via SIDRA API with retry logic
- Both extractors reuse normalize_cod_ibge() for 6/7-digit municipality code handling and validate_dataframe() as quality gate
- 13 offline tests (6 ANS + 7 Census) all pass with mocked data, no network calls required

## Task Commits

Each task was committed atomically:

1. **Task 1: ANS quarterly average beneficiary extractor with test suite** - `a78708a` (feat)
2. **Task 2: Census 2022 sanitation extractor with test suite** - `132d479` (feat)

_Note: TDD tasks each followed RED-GREEN cycle (test failure verified before implementation)._

## Files Created/Modified
- `scripts/extract_ans_quarterly.py` - ANS quarterly average beneficiary extraction with coverage rate computation
- `scripts/extract_census_sanitation.py` - Census 2022 sanitation and water supply extraction via SIDRA API
- `tests/test_extract_ans_quarterly.py` - 6 offline tests for quarterly averaging, normalization, coverage rate
- `tests/test_extract_census_sanitation.py` - 7 offline tests with mocked sidrapy for sanitation/water data
- `tests/fixtures/ans_quarterly_sample.csv` - ANS test fixture with 4 municipalities, mixed quarter availability
- `tests/fixtures/sidra_6805_sample.json` - SIDRA Census response fixture with metadata header and missing data
- `data_sources/processed/ans/.gitkeep` - Output directory placeholder for ANS Parquet
- `data_sources/processed/census_sanitation/.gitkeep` - Output directory placeholder for Census sanitation Parquet

## Decisions Made
- ANS quarterly average uses Q1-Q4 mean per locked decision, not December snapshot -- avoids seasonal bias
- Census 2022 sanitation flagged as cross-sectional (year=2022) in module docstring and log message per locked decision
- compute_coverage_rate() accepts both population_df (DataFrame) and population_path (Path) for flexibility and testability
- SIDRA retry logic set at 3 attempts with 5-second backoff multiplier

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Worktree was based on older commit missing Phase 1/2 files (utils.py, validation.py) -- resolved by merging copilot/add-process-documentation branch
- data_sources/processed/ directory was gitignored -- used `git add -f` for .gitkeep files

## Known Stubs

None - both extractors are fully wired to their data sources. Coverage rate computation defers to NaN when population data is unavailable (intentional; will be computed in Panel Assembly phase with population Parquet from Plan 01).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- ANS quarterly Parquet ready for Phase 4 panel assembly merge on (cod_ibge, year)
- Census sanitation Parquet ready for Phase 5 Environment dimension (D5) computation
- Coverage rate and SUS dependence will be fully computed when population Parquet is available from Plan 01
- Plan 04 (RENAVAM + SIOPS best-effort + pipeline wiring) is the final Phase 3 plan

---
*Phase: 03-secondary-source-extraction*
*Completed: 2026-04-02*
