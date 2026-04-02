# Phase 5: Dimension Computation & CUDS - Context

**Gathered:** 2026-04-02
**Status:** Ready for planning
**Mode:** Auto-generated (autonomous workflow)

<domain>
## Phase Boundary

Compute all 8 active CIMI dimension scores from the assembled panel, apply within-year min-max normalization, and derive the CUDS composite via geometric mean. Persist dimension scores and CUDS to SQLite. D8 (International Projection) is excluded with documented justification.

</domain>

<decisions>
## Implementation Decisions

### Dimension Mapping
- D1 Governance: IFGF Geral score
- D2 Economy: GDP per capita (constant 2023 BRL)
- D3 Human Capital: IDHM composite (2010 cross-sectional)
- D4 Social Cohesion: SUS dependence rate (1 - ANS private coverage)
- D5 Environment: Adequate sanitation % (Census 2022 cross-sectional)
- D6 Mobility: Vehicles per 1,000 inhabitants (RENAVAM, best-effort)
- D7 Urban Planning: Hospital beds per 10,000 inhabitants (CNES)
- D8 International Projection: EXCLUDED (irrelevant at municipal level)
- D9 Technology: Internet access % (proxy TBD — Census 2022 or PNAD)
- D10 Public Management: Per-capita health expenditure (SIOPS, best-effort)

### Normalization
- Within-year min-max normalization to [0, 1] using groupby('year').transform()
- After normalization: exactly one municipality scores 0.0 and one scores 1.0 per year per dimension
- Cross-sectional dimensions (D3 IDHM, D5 sanitation) explicitly flagged in dimension_metadata

### CUDS Computation
- Geometric mean of all available normalized dimension scores
- Floor offset epsilon=0.01 to prevent zero collapse (no municipality scores exactly 0.0 CUDS)
- Expected distribution: right-skewed (majority below 0.5) reflecting Brazilian municipal inequality
- Missing dimensions (RENAVAM/SIOPS best-effort) excluded from geometric mean for that municipality

### Claude's Discretion
- D9 Technology proxy source selection (Census 2022 internet vs PNAD estimate)
- Whether D4 should be inverted (higher SUS dependence = lower social cohesion score)
- How to handle municipalities with all dimensions missing (exclude from CUDS vs assign NaN)
- SQLite table name for dimension scores (dimension_scores vs cimi_dimensions)

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- database/assemble_panel.py — assembled 50,139-row panel with all source columns
- database/build_database_v3.py — SQLite v3 with dimension_metadata table
- analysis/icskg_analysis_pipeline.py — existing dimension computation logic (D1-D9 stubs)

### Integration Points
- Read from: SQLite municipal_health table or assembled panel Parquet
- Write to: SQLite dimension_scores table + update dimension_metadata
- dimension_metadata table already has schema for source, normalization method, weight

</code_context>

<specifics>
## Specific Ideas

- analysis/icskg_analysis_pipeline.py has existing compute_d1(), compute_d6() stubs — reference patterns
- Equal-weight composite (CUDS = geometric mean of D1-D7, D9-D10)
- Must handle variable number of available dimensions per municipality gracefully

</specifics>

<deferred>
## Deferred Ideas

- Sensitivity analysis: arithmetic mean vs geometric mean (Phase 7)
- Dimension weighting alternatives (Phase 7 sensitivity)

</deferred>
