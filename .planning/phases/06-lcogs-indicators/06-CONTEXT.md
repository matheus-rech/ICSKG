# Phase 6: LCoGS Indicators - Context

**Gathered:** 2026-04-02
**Status:** Ready for planning
**Mode:** Auto-generated (autonomous workflow)

<domain>
## Phase Boundary

Compute all 6 Lancet Commission on Global Surgery indicators at municipality-year level from SIH procedure data, CNES facility/professional data, and population estimates. Load into SQLite lcogs_indicators table. Small-sample suppression for POMR (NaN if <10 surgical events).

</domain>

<decisions>
## Implementation Decisions

### LCoGS Indicator Definitions
- LCoGS-1: Haversine distance to nearest bellwether hospital (from CNES geocoded facilities)
- LCoGS-2: SAO workforce density per 100,000 population (surgeons + anesthesiologists + obstetricians, deduplicated by CNS per municipality-year)
- LCoGS-3: Surgical volume per 100,000 population (SUS-funded procedures from SIH)
- LCoGS-4: Perioperative mortality rate (in-hospital deaths within SIH surgical admissions)
- LCoGS-5: Financial risk protection (average SIH procedure cost / GDP per capita, both constant 2023 BRL)
- LCoGS-6: Catastrophic expenditure proxy (% procedures exceeding cost threshold relative to GDP per capita)

### Key Constraints
- LCoGS-4 POMR: municipalities with <10 surgical events → NaN (unstable rate suppression)
- LCoGS-5/6: both numerator and denominator in constant 2023 BRL (already deflated in Phase 4)
- LCoGS-5/6: ecological-proxy caveat documented in lcogs_metadata table
- All indicators labeled as SUS-funded procedures only (documented limitation)
- SQLite lcogs_indicators table: 50,139 rows (5,571 × 9 years)

### Claude's Discretion
- LCoGS-1 geocoding strategy (geobr coordinates vs CNES lat/lon fields)
- LCoGS-6 catastrophic threshold definition (% of per-capita GDP)
- Whether to compute LCoGS-1 for all years or just latest (geocoordinates are mostly static)
- Haversine implementation (custom function vs geopy library)

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- scripts/sih_extract.py — SIH procedure-level Parquet with MORTE, VAL_TOT, MUNIC_MOV
- scripts/sih_extract.py aggregate_sih_year() — n_procedures, n_deaths, total_cost per municipality-year
- scripts/cnes_extract.py — facilities.parquet (bellwether flag, geocoordinates), professionals.parquet (SAO filtered, CNS deduped)
- database/assemble_panel.py — population estimates available in panel
- extract_lcogs1.py — existing LCoGS-1 implementation (reference)

### Integration Points
- Read from: SIH aggregates, CNES facilities/professionals, SIDRA population, assembled panel
- Write to: SQLite lcogs_indicators table via build_database_v3.py

</code_context>

<specifics>
## Specific Ideas

- extract_lcogs1.py has existing bellwether procedure classification and mapping logic — reference
- CNES facilities.parquet already has is_bellwether flag from Phase 2
- SIH aggregate already has n_procedures, n_deaths, total_cost_brl from Phase 2

</specifics>

<deferred>
## Deferred Ideas

None — all 6 LCoGS indicators are in scope.

</deferred>
