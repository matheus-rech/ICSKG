# Phase 1: Foundation - Context

**Gathered:** 2026-04-01
**Status:** Ready for planning

<domain>
## Phase Boundary

Reproducible environment, shared utilities, and reference data that every downstream script depends on. Includes Python 3.12 + uv setup, normalize_cod_ibge() utility, IBGE reference list, validation gate, pyproject.toml with pinned dependencies, and AMC temporal crosswalk. No data acquisition or analysis work — purely infrastructure.

</domain>

<decisions>
## Implementation Decisions

### Municipality Code Canonicalization
- **D-01:** 7-digit IBGE code (with check digit, e.g., 3550308) is the canonical format across the entire pipeline
- **D-02:** normalize_cod_ibge() must handle: 6-digit → 7-digit conversion (append check digit), string/int coercion, column name normalization (CD_MUNICIPIO, Cod_IBGE, CD_MUN, MUNIC_RES, MUNIC_MOV → cod_ibge)
- **D-03:** IBGE 2023 reference list of 5,570 municipalities serves as the canonical join key; any code not in the reference list is flagged

### Validation Gate
- **D-04:** Configurable strictness — default to quarantine+continue (move bad rows to data_sources/quarantine/, log warnings, pipeline completes); `--strict` flag to fail hard with clear error
- **D-05:** Validation checks include: municipality code validity (vs IBGE reference), range checks per variable, duplicate detection, schema conformance

### Data Storage
- **D-06:** All downloaded and processed data saved to NAS (not local storage) due to storage constraints. NAS path configured via config file
- **D-07:** Config file approach (`.env` or `config.yaml`) for all data paths — NAS path, raw data directory, processed data directory. Default to `data_sources/` if config not present (for other researchers)

### Data Sources (FIOCRUZ BigData)
- **D-08:** CNES data sourced from FIOCRUZ BigData: https://bigdata-arquivos.icict.fiocruz.br/PUBLICO/CNES/ETLCNES.zip (NOT PySUS/DATASUS FTP)
- **D-09:** Pipeline supports both local path (from config) AND auto-download from FIOCRUZ URL if not present
- **D-10:** Additional dataset: PolisPCDaS from https://bigdata-arquivos.icict.fiocruz.br/PUBLICO/PolisPCDaS/PolisPCDaS.zip — pre-aggregated municipal indicators covering mortality, maternal-child health, health infrastructure, education, sanitation. Can feed multiple CIMI dimensions and serve as validation source.

### Claude's Discretion
- Project structure: where shared utilities live (database/utils.py vs new top-level package) — Claude picks based on existing patterns and minimal restructuring
- Config file format choice (.env vs config.yaml vs pyproject.toml [tool.icskg] section)
- AMC crosswalk source (geobr Python, Ehrl's dataset, or static CSV)
- Exact validation check thresholds and range definitions

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project methodology
- `docs/ICSKG-BR_Methodology_and_Gap_Analysis.md` — Full CIMI dimension definitions, data sources, composite score methodology
- `.planning/PROJECT.md` — Project context, constraints, key decisions

### Research findings
- `.planning/research/STACK.md` — Technology stack recommendations with versions (Python 3.12, pandas 2.2.3 pinned, DuckDB 1.5.1, uv)
- `.planning/research/ARCHITECTURE.md` — Layered pipeline architecture, normalize_cod_ibge() as architectural spine
- `.planning/research/PITFALLS.md` — Municipality code mismatch (Pitfall 13), IFGF MNAR (Pitfall 4), geometric mean zero collapse (Pitfall 2)

### Existing code patterns
- `.planning/codebase/CONVENTIONS.md` — Snake case naming, PEP 8, import organization, logging patterns
- `.planning/codebase/STRUCTURE.md` — Current directory layout and key file locations

### Data sources
- FIOCRUZ BigData CNES: https://bigdata-arquivos.icict.fiocruz.br/PUBLICO/CNES/ETLCNES.zip
- FIOCRUZ BigData PolisPCDaS: https://bigdata-arquivos.icict.fiocruz.br/PUBLICO/PolisPCDaS/PolisPCDaS.zip

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `database/build_database_v2.py`: SQLite schema DDL, upsert pattern, metadata seeding — reuse for validation gate integration
- `database/pipeline.py`: ETL orchestrator with extract_*() function contract — extend with validation gate
- `extract_lcogs1.py`: IBGE population API fetcher (fetch_ibge_population) — extract into shared utility

### Established Patterns
- Logging: `logging.basicConfig()` with timestamp/level/message format, used consistently across all modules
- CLI: `argparse` with typed arguments, used in pipeline.py and extract_lcogs1.py
- Error handling: try-except-log with graceful degradation (extract functions return None on failure)
- Parquet: pyarrow-based intermediate storage with year-month filename partitioning

### Integration Points
- `database/pipeline.py` import of shared utils (normalize_cod_ibge, validation gate)
- All `scripts/download_*.py` will import normalize_cod_ibge for output standardization
- `database/build_database_v2.py` SQLite schema needs cod_ibge column standardized to 7-digit TEXT

### Municipality Code Current State (must fix)
- `extract_lcogs1.py:127` uses `loc[:6]` (6-digit truncation)
- `analysis/icskg_analysis_pipeline.py:157` uses `f"{mun_id:07d}"` (7-digit padding)
- `scripts/download_ans.py:147` looks for CD_MUNICIPIO, Municipio, IBGE_MUNICIPIO, CD_MUN
- `analysis/icskg_analysis_pipeline.py:86` reads as `Cod_IBGE` from IFGF Excel
- `extract_lcogs1.py:237` joins on `CD_MUN` from shapefile vs `cod_ibge` from data

</code_context>

<specifics>
## Specific Ideas

- NAS is a Synology at `smb://synology-rech._smb._tcp.local/docker/Downloads` — raw SIH/CNES data already stored there
- User strongly prefers NAS for all data storage due to local disk constraints
- PolisPCDaS dataset is user-recommended as a rich supplementary source — municipality-level pre-aggregated indicators from FIOCRUZ/PCDaS platform

</specifics>

<deferred>
## Deferred Ideas

- PolisPCDaS integration as data source — belongs in Phase 3 (Secondary Source Extraction), not Phase 1
- CNES ETLCNES.zip download/parsing — belongs in Phase 2 (SIH & CNES Extraction)
- SIOPS and RENAVAM format discovery — belongs in Phase 3

</deferred>

---

*Phase: 01-foundation*
*Context gathered: 2026-04-01*
