# Phase 3: Secondary Source Extraction - Context

**Gathered:** 2026-04-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Extract, parse, and standardize seven remaining data sources to Parquet files with IBGE municipality codes canonicalized. Each source feeds one CIMI dimension. All sources are independent — can be extracted in parallel. RENAVAM and SIOPS are best-effort (LOW confidence formats).

</domain>

<decisions>
## Implementation Decisions

### IBGE SIDRA (DATA-03: Economy — GDP per capita + Population)
- Use sidrapy library (already pinned in pyproject.toml) for SIDRA API access
- Table 6579: population estimates by municipality
- Table 5938: GDP per capita by municipality
- Normalize cod_ibge via database/utils.py before writing Parquet
- GDP may have 2-year lag for 2023 — flag as estimated if unavailable

### IPEA IDHM (DATA-04: Human Capital)
- IDHM is census-only (2010, 2022) — use cross-sectional values (NOT interpolated)
- Explicitly document in dimension_metadata that IDHM does not represent genuine temporal variation
- Use ipeadatapy library (already pinned) for OData API access
- Extract composite IDHM + education/longevity/income sub-indices

### FIRJAN IFGF (DATA-05: Governance)
- Parse from bundled Excel file: data_sources/Evolucao_por_Indicador_2013_a_2024_IFGF_2025.xlsx
- Extract 5 sub-indices + IFGF Geral for 2015-2023
- ~420 municipalities/year are MNAR (not zero, not dropped — preserve as NaN)
- Use openpyxl (already pinned) for Excel reading

### ANS Beneficiaries (DATA-06: Social Cohesion)
- Existing scripts/download_ans.py provides download infrastructure
- Compute quarterly average (Q1-Q4 mean) NOT December snapshot
- CSV format: latin-1 encoding, semicolon-delimited
- Private coverage rate = beneficiaries / population; SUS dependence = 1 - coverage

### IBGE Census 2022 Sanitation (DATA-07: Environment)
- Single cross-sectional year (2022) applied to all panel years
- Explicitly flagged as non-time-varying in dimension_metadata
- Extract adequate sanitation % (esgotamento sanitario) + water supply % (abastecimento de agua)
- Source: IBGE Panorama API or Census 2022 aggregated tables

### RENAVAM Vehicle Fleet (DATA-08: Mobility) — BEST EFFORT
- Source: dados.transportes.gov.br CSVs
- Format discovery required — LOW confidence
- Target: vehicles per 1,000 inhabitants by municipality
- If format cannot be parsed: log gap, set dimension to NaN, document in Limitations

### SIOPS Health Expenditure (DATA-09: Public Management) — BEST EFFORT
- Source: portalfns.saude.gov.br
- Format discovery required — LOW confidence
- Target: per-capita municipal health spending (to be deflated in Phase 4)
- If format cannot be parsed: log gap, set dimension to NaN, document in Limitations

### Claude's Discretion
- API pagination strategy for SIDRA (all municipalities in one call vs batched)
- Census 2022 API endpoint selection (Panorama vs direct table download)
- RENAVAM/SIOPS format discovery approach (web scraping vs direct download)
- Error handling for API rate limits and timeouts
- Whether to create one script per source or a unified secondary_sources.py

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- scripts/download_ans.py — ANS beneficiary download with retry logic
- database/utils.py — normalize_cod_ibge(), rename_municipality_column(), load_ibge_municipios()
- database/validation.py — validate_dataframe() mandatory quality gate
- database/pipeline.py — load_config() for NAS paths, extract stubs
- analysis/icskg_analysis_pipeline.py — has existing IFGF/ANS parsing logic (reference)

### Established Patterns (from Phase 2)
- DuckDB for large CSV reading with column projection
- Test fixtures in tests/fixtures/ for offline development
- Per-source Parquet output to data_sources/processed/{source}/
- normalize_cod_ibge() applied before writing
- validate_dataframe() as mandatory gate

### Integration Points
- database/pipeline.py — needs extract stubs for each new source
- config.yaml — data_root for NAS path resolution
- pyproject.toml — sidrapy, ipeadatapy already pinned

</code_context>

<specifics>
## Specific Ideas

- IFGF Excel file is already bundled in data_sources/ — no download needed
- ANS download_ans.py already handles semicolon-delimited latin-1 CSVs
- analysis/icskg_analysis_pipeline.py has existing parsing logic for IFGF and ANS that can be referenced
- GDP per capita from SIDRA table 5938 may not cover 2023 due to IBGE publication lag

</specifics>

<deferred>
## Deferred Ideas

- IPCA deflation of monetary variables (Phase 4)
- IFGF multiple imputation for MNAR municipalities (Phase 4)
- PolisPCDaS cross-validation of extracted indicators (later phases)

</deferred>
