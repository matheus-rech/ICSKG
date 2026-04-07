# Phase 12: CUDS Construction & Cookbook §6 Alignment

**Status:** Planned (not started)
**Predecessor:** Phase 11 (CI Reproducibility & HF Data Layer) — done v0.1.0
**Reference:** ICSKG-BR Technical Cookbook v1.0 (March 2026), §3.6, §3.7, §3.8 (SNIS proper), §3.10, §3.11, §5, §6

<domain>
## Phase Boundary

Close the gap between the ICSKG-BR Technical Cookbook v1.0 specification and the v0.1.0 HF dataset published in Phase 11. v0.1.0 ships only the **LCoGS-side** of the cookbook (all of §3.1, §3.2, §3.3, §3.4, §3.5, §3.9, plus a partial §3.8 via Census 2022 sanitation as a proxy). Phase 12 builds the missing extractors, implements the §6 Composite Urban Development Score (CUDS) construction, moves the `municipal_health` panel derivation from publish-time into the build pipeline as a base table, and re-exports the dataset as v0.2.0.

This phase produces no new analysis layer and no new visualisations — it closes the cookbook compliance gap that Phase 11 surfaced and documented honestly. The end-state is: "what the cookbook plans is what the published dataset and the build pipeline produce", end-to-end.

</domain>

<scope>
## What's IN Phase 12

### Missing extractors (cookbook §3 sources)
1. **ANATEL broadband (§3.6)** — `scripts/extract_anatel_broadband.py`
   - Source: ANATEL open-data portal (Densidade Banda Larga Fixa)
   - Output: `anatel_broadband` DuckDB table, joined on (cod_ibge, year)
   - Used by: CUDS Technology dimension

2. **RAIS employment (§3.7)** — `scripts/extract_rais.py`
   - Source: Ministério do Trabalho RAIS microdata or aggregated bulletins
   - Output: `rais_employment` DuckDB table with sector breakdowns, joined on (cod_ibge, year)
   - Used by: CUDS Economy/Workforce dimension
   - Note: distinct from the existing `sao_workforce` (which is CNES health-sector only)

3. **SNIS sanitation (§3.8 proper)** — `scripts/extract_snis.py`
   - Source: SNIS (Sistema Nacional de Informações sobre Saneamento) annual series
   - Output: `snis_sanitation` DuckDB table with water/sewage indicators, joined on (cod_ibge, year)
   - Used by: CUDS Sanitation dimension
   - Replaces the `censo2022_saneamento` partial proxy from v0.1

4. **SIOPS health spending (§3.10)** — `scripts/extract_siops.py`
   - Source: SIOPS DATASUS web service
   - Output: `siops_health_spending` DuckDB table with per-capita health expenditure, joined on (cod_ibge, year)
   - Used by: CUDS Governance dimension

5. **International APIs (§3.11)** — `scripts/extract_international_comparators.py`
   - Sources: WHO Global Health Observatory, World Bank Open Data, UNDP HDI API
   - Output: `international_indicators` DuckDB table at country-year level
   - Used by: cross-country comparator panels in the Discussion section

### CUDS construction (cookbook §6)
6. **§6.1 Normalization** — `database/cuds/normalize.py`
   - Min-max normalize all CUDS input columns to [0, 1] range
   - Handle invert columns (POMR, where lower is better)
   - Output: `dimension_score` DuckDB table with one normalized column per indicator

7. **§6.2 PCA Weighting** — `database/cuds/pca_weights.py`
   - Derive weights from first PCA component loadings
   - Impute missing for PCA via SimpleImputer(strategy='median')
   - Output: `dimension_metadata` DuckDB table with one weight per indicator

8. **§6.3 Geometric Mean Aggregation** — `database/cuds/aggregate.py`
   - Compute CUDS composite via weighted geometric mean of dimension scores
   - Output: `cuds` DuckDB table with cuds_score column joined on (cod_ibge, year)

9. **§6.4 Robustness Checks** — `tests/test_cuds_robustness.py`
   - Sensitivity analysis: bootstrap CI on cuds_score
   - Alternative aggregations: arithmetic mean, harmonic mean
   - Output: `cuds_robustness` DuckDB table for the methods section

### Pipeline integration
10. **Move `municipal_health` derivation into the build pipeline**
    - The current Phase 11 implementation derives this table at publish time in `scripts/publish_to_hf.py`
    - Phase 12 moves it to `database/build_database_v3.py` so the table is a real base table in the source DuckDB
    - Update `scripts/publish_to_hf.py` to read it as a base table instead of deriving
    - This eliminates the documented "publish-time derivation trap" from the Phase 11 ADR

### Re-publish
11. **HF dataset v0.2.0**
    - All 11 cookbook §3 sources present
    - `panel/municipal_health.parquet` from build pipeline (not derived at publish)
    - `dimensions/cuds.parquet`, `dimensions/dimension_score.parquet`, `dimensions/dimension_metadata.parquet`
    - Updated dataset card README declaring full cookbook v1.0 compliance
    - Tag v0.2.0 on HF, update `config.example.yaml` and `.github/workflows/build-database.yml` defaults
    - Updated `.zenodo.json` ready for sandbox publish

</scope>

<not_in_scope>
## What's NOT in Phase 12

- New visualisations or figures (Phase 7/8 territory)
- Cookbook v2.0 — any cookbook revisions are tracked in a separate doc PR
- BMJ submission cut (`v1.0.0` HF release) — that comes after the manuscript is accepted
- Real Zenodo production publish — sandbox only in Phase 11.5; production at acceptance
- Public dataset visibility flip — stays private until BMJ submission
</not_in_scope>

<decisions>
## Open decisions to resolve at phase kickoff

1. **RAIS data source**: microdata (huge, slow, requires monthly scraping) vs aggregated bulletins (smaller, faster, less granular). Pick one.
2. **CUDS dimension grouping**: cookbook §6 implies 9 dimensions per CIMI framework, but the indicator-to-dimension mapping is not fully specified. Need to lock this before §6.2 PCA can run.
3. **Missing-data threshold for PCA**: cookbook §4.4 sets a missingness threshold; confirm whether it applies to CUDS computation.
4. **Imputation method for missingness**: cookbook §4.4 mentions thresholds but not the imputation method. Phase 11 used IFGF imputation only. Phase 12 may extend to other dimensions.
5. **`municipal_health` table location**: should it stay in DuckDB-base-table form or move to a SQLite-only "materialized view" pattern? Trade-off: DuckDB form is faster on-disk but SQLite is what reviewers will mostly use.
6. **Naming alignment**: cookbook calls the canonical panel `icskg_br_unified_panel.parquet`; code calls it `panel/municipal_health.parquet`. Pick one. The current Phase 11 ADR keeps the code naming and notes this for cookbook update — confirm or override.
</decisions>

<verification>
## Phase 12 success criteria

- All 5 missing extractors land as committed scripts with unit tests against fixtures
- All 5 produce parquet outputs that can be ingested into the canonical DuckDB
- `municipal_health` is a base table in the DuckDB (no longer derived at publish time)
- `cuds`, `dimension_score`, `dimension_metadata` are base tables in the DuckDB
- HF dataset v0.2.0 is published with all 11 cookbook sources + CUDS layer
- `database/fetch_processed_data.py` successfully fetches v0.2.0 and materializes a SQLite that includes the `cuds` table
- `gh workflow run build-database.yml -f hf_revision=v0.2.0` is green
- Full test suite passes (current Phase 11 baseline: 339 tests)
- Cookbook §7.5 automated validation script runs successfully on the v0.2.0 export
</verification>

<refs>
## References

### Internal
- ICSKG-BR Technical Cookbook v1.0 (March 2026): `~/Pictures/universal_systematic_review_repository/ICSKG.pdf`
- Phase 11 plans: `.planning/phases/11-ci-reproducibility-hf-data-layer/`
- Phase 11 PR: https://github.com/matheus-rech/ICSKG/pull/8
- v0.1.0 HF dataset: https://huggingface.co/datasets/mmrech/icskg-br-processed/tree/v0.1.0
- Publish-time `municipal_health` derivation (to be moved): `scripts/publish_to_hf.py::derive_municipal_health_panel`
- Cookbook scope statement (current state): `scripts/publish_to_hf.py::COOKBOOK_SOURCES_PRESENT` and `COOKBOOK_SOURCES_DEFERRED`
- Existing skeleton extractors (v0.1 SKELETONS, raise NotImplementedError):
  - `scripts/extract_anatel_broadband.py` — cookbook §3.6
  - `scripts/extract_rais_employment.py` — cookbook §3.7
  - `scripts/extract_snis_sanitation.py` — cookbook §3.8 (proper, not Census proxy)
  - `scripts/extract_international_comparators.py` — cookbook §3.11
- Pre-existing best-effort extractor (working but endpoints stale):
  - `scripts/extract_siops.py` — cookbook §3.10. Tries SIOPS REST API +
    DATASUS TabNet + OpenDataSUS in that order; ALL six endpoint URLs
    return 404 as of 2026-04-07.  Needs rewrite against gov.br Conecta
    catalog (see external resources below).
- Empty placeholder (do NOT trust as-is):
  - `data_sources/processed/siops/siops.parquet` — written by best-effort
    extractor when all endpoints fail.  Schema-only, zero rows.
- Pre-existing extractors flagged "your own risk":
  - `scripts/extract_ibge_sidra.py` — works but unreliable, depends on
    sidrapy + flaky SIDRA endpoints; treat outputs as needing re-validation
- Bucket for raw FIOCRUZ-style downloads: `hf://buckets/mmrech/sihsus`
  (created 2026-04-07, currently empty)

### External resources for Phase 12 implementation work

**Brazilian government API gateways** (PRIMARY discovery surface):

- **gov.br Conecta catalog** — https://www.gov.br/conecta/catalogo/
  Official Brazilian federal API catalog.  THIS is where the canonical
  SIOPS / IBGE / DATASUS / ANATEL / etc. endpoint URLs live.  Start every
  Phase 12 extractor here to find the current authoritative endpoint
  before writing code.  Replaces the pattern of guessing API paths.

- **BrasilAPI** — https://brasilapi.com.br/docs
  Community-maintained Brazilian government API aggregator.  Provides
  clean wrappers around CEP, banks, IBGE municipalities, holidays,
  feriados, banks, vehicles registry, weather, taxes, NCM codes, etc.
  Useful for cross-validating IBGE municipality codes and as a fallback
  when Conecta endpoints are down.

**IBGE SIDRA (cookbook §3.3)**:

- **sidrapy** (Python) — https://sidrapy.readthedocs.io/pt-br/latest/
  Already in our dependency tree (`sidrapy>=0.1.4`).  Used by the
  flaky `scripts/extract_ibge_sidra.py`.  When rewriting, keep sidrapy
  as the API client and add retry/circuit-breaker around it.

- **sidrar** (R) — https://cran.r-project.org/web/packages/sidrar/sidrar.pdf
  R-equivalent of sidrapy.  Useful for cross-validation of column names,
  table IDs, and aggregation semantics.  NOT a replacement — keep Python
  as the canonical pipeline language.

**DATASUS pre-ETL'd archives (cookbook §3.1, §3.2)**:

- **FIOCRUZ ICICT** — https://bigdata-arquivos.icict.fiocruz.br/PUBLICO/
  Pre-extracted DATASUS data published as plain CSV in versioned ZIPs.
  Skips the entire DBC→CSV conversion step (and therefore the entire
  pysus → elasticsearch → urllib3<2 chain that triggers Dependabot).
  Subdirectories: `SIH/`, `CNES/`, `SIM/`, `SINASC/`, `SIM_DOFET/`,
  `SIMU/`, `OUVIDORIA/`, `PMM/`, `POP_SVS/`, `PolisPCDaS/`.
  ETLSIH.zip is **31 GB** as of 2026-04-07 — Phase 12 must use either
  HF Jobs (paid compute, cleanest) or NAS-staged download via
  `/Volumes/home/` + `hf sync hf://buckets/mmrech/sihsus`.
  See `scripts/jobs/explore_fiocruz_sih.py` for the prepared explorer
  script (currently un-runnable until HF Jobs credits land).

- **microdatasus** (R) — https://github.com/rfsaldanha/microdatasus
  Active R package (v2.3.1, June 2024) using `read.dbc`.  Alternative
  if FIOCRUZ ICICT doesn't pan out — would require an R subprocess
  in the build pipeline (containerizable) but eliminates pysus entirely.

**Atlas Brasil HDI (cookbook §3.4)**:

- IPEA Data — current `scripts/extract_ipea_idhm.py` (10 KB) is the
  existing implementation.  Verify it still works against the IPEA
  IDHM endpoint as part of phase 12 health checks.

**FIRJAN IFGF (cookbook §3.5)**:

- FIRJAN open data portal — current `scripts/extract_ifgf.py` (11 KB)
  is the existing implementation.  Reads from a bundled XLSX
  (`data_sources/Evolucao_por_Indicador_2013_a_2024_IFGF_2025.xlsx`)
  per CLAUDE.md.  Phase 12 should switch to fetching from the FIRJAN
  open data API if one exists (TBD via Conecta search).

**RAIS (cookbook §3.7)** — no official API; sources to check:

- Ministério do Trabalho microdata FTP: ftp://ftp.mtps.gov.br/pdet/microdados/RAIS/
- Aggregated bulletins (PDF/CSV) on the MTE website
- Possibly available via Base dos Dados (https://basedosdados.org/)

**ANATEL (cookbook §3.6)** — search Conecta for "ANATEL" or:

- ANATEL open data portal: https://informacoes.anatel.gov.br/paineis/acessos/banda-larga-fixa
- Densidade de Banda Larga Fixa monthly CSVs

**SNIS (cookbook §3.8)** — search Conecta for "SNIS" or:

- SNIS Diagnóstico annual reports: http://www.snis.gov.br/diagnosticos
- Per-year ZIPs containing operational and accounting indicators

**International comparators (cookbook §3.11)**:

- WHO Global Health Observatory: https://ghoapi.azureedge.net/api/
- World Bank Open Data: https://api.worldbank.org/v2/
- UNDP HDI: http://hdr.undp.org/en/data
</refs>
