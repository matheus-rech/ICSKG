# ICSKG-BR

## What This Is

The ICSKG-BR (Index of Cities' Smartness & Knowledge for Global Surgery — Brazil) is a longitudinal ecological panel study that operationalizes the IESE Cities in Motion Index (CIMI) 9-dimension framework as a Composite Urban Development Score (CUDS) and validates it against Lancet Commission on Global Surgery (LCoGS) indicators across all 5,570 Brazilian municipalities from 2015 to 2023. It produces a 50,130-observation panel dataset (5,570 municipalities × 9 years) for publication in BMJ Global Health.

## Core Value

A reproducible, publicly-sourced database that proves whether municipal urban development predicts surgical system performance — the first study in any country to cross-reference urban development composite indices with surgical indicators at the subnational level.

## Requirements

### Validated

- ✓ LCoGS-1 bellwether procedure extraction and geospatial mapping — existing (`extract_lcogs1.py`)
- ✓ 9/9 CIMI dimension framework defined with data source mappings — existing (methodology docs)
- ✓ SIH/CNES download scripts with resume capability — existing (`scripts/`)
- ✓ ANS beneficiary download — existing (`scripts/download_ans.py`)
- ✓ Basic ETL pipeline scaffolding (extract → transform → load) — existing (`database/pipeline.py`)
- ✓ SQLite database builder with dimension metadata — existing (`database/build_database_v2.py`)
- ✓ Analysis pipeline scaffolding for 9 dimensions — existing (`analysis/icskg_analysis_pipeline.py`)

### Active

- [ ] IBGE SIDRA API integration (population estimates + GDP per capita, table 6579/5938)
- [ ] PySUS SIH download for full 12-month annualized data (not just December snapshots)
- [ ] PySUS CNES professional records with CBO-based surgeon/anesthesiologist/obstetrician filtering
- [ ] IPEA IDHM integration (composite + education/longevity/income sub-indices)
- [ ] FIRJAN IFGF Excel parser (5 sub-indices + IFGF Geral, 2015–2023)
- [ ] ANS TabNet private insurance coverage rate computation
- [ ] IBGE Census 2022 sanitation indicators (esgotamento sanitário + abastecimento de água)
- [ ] RENAVAM vehicle fleet data (vehicles per 1,000 inhabitants)
- [ ] CNES API bellwether hospital identification (surgical center + obstetric center + inpatient beds)
- [ ] SIOPS per-capita health expenditure (deflated to 2023 BRL via IPCA health sub-index)
- [ ] SQLite database assembly with all 9 CIMI dimensions and LCoGS indicators
- [ ] Full ETL pipeline producing municipality-year panel (all 9 CIMI dimensions)
- [ ] CUDS computation via geometric mean of min-max normalized dimensions
- [ ] LCoGS indicator suite (6 indicators adapted to municipal level)
- [ ] Haversine distance to nearest bellwether hospital (from 765 geocoded facilities)
- [ ] SAO (surgeon/anesthesiologist/obstetrician) workforce density per 100,000
- [ ] Perioperative mortality rate (POMR) computation from SIH
- [ ] 8-phase analysis pipeline (data loading → dimension computation → ML models)
- [ ] ML dose-response models (Random Forest, XGBoost) for CUDS → LCoGS relationships
- [ ] Regional disparity analysis (North–South gradient across all dimensions)
- [ ] Paper-ready figures and tables (4 figures, 8 tables minimum)
- [ ] STROBE/RECORD reporting compliance checklists

### Out of Scope

- International Projection (CIMI dimension 10) — irrelevant at municipal level for 99% of Brazilian municipalities; documented limitation
- Real-time dashboard or web interface — research database, not an application
- Individual-level patient data — all analyses at municipality-level aggregates
- Causal inference claims — ecological study design, dose-response associations only
- Mobile app — academic research output only

## Context

**Existing codebase:** Scaffolding exists for download scripts, ETL pipeline, database builder, analysis pipeline, and LCoGS-1 extraction. However, significant gaps exist between the documented methodology and implemented code — many data sources have no extraction code, the ETL pipeline is incomplete, and the analysis pipeline needs full dimension computation.

**Infrastructure:** SQLite is the primary database. DuckDB available as optional analytical mirror. Raw data archived on NAS.

**Data sources (9 dimensions):**

| # | CIMI Dimension | Proxy Indicator | Source |
|---|---------------|-----------------|--------|
| 1 | Governance | IFGF fiscal management composite | FIRJAN |
| 2 | Economy | GDP per capita | IBGE SIDRA |
| 3 | Human Capital | IDHM composite | IPEA |
| 4 | Social Cohesion | SUS dependence rate (100 − ANS coverage) | ANS |
| 5 | Environment | Adequate sanitation % | IBGE Census 2022 |
| 6 | Mobility | Vehicles per 1,000 inhabitants | RENAVAM |
| 7 | Urban Planning | Hospital beds per 10,000 inhabitants | CNES |
| 8 | International Projection | — (excluded) | — |
| 9 | Technology | Internet access % (or proxy) | IBGE/PNAD |
| 10 | Public Management | Per-capita health expenditure | SIOPS |

**LCoGS indicators (6):**

| # | Indicator | Source |
|---|-----------|--------|
| 1 | Access to bellwether procedures (2-hour travel) | CNES geocoded |
| 2 | SAO workforce density per 100,000 | CNES professionals |
| 3 | Surgical volume per 100,000 | SIH |
| 4 | Perioperative mortality rate (POMR) | SIH |
| 5 | Financial risk protection (ecological proxy) | SIH costs / GDP |
| 6 | Catastrophic expenditure (ecological proxy) | SIH costs / GDP |

**Key methodological choices:**
- CUDS = geometric mean (penalizes imbalance across dimensions)
- Min-max normalization to [0, 1] within each year
- Municipality of treatment (not residence) for surgical procedures
- December snapshots → full 12-month annualized data (in progress)

**Target:** BMJ Global Health (primary), World Journal of Surgery (secondary)

## Constraints

- **Data availability**: All sources must be publicly available Brazilian government data (Lei de Acesso à Informação, Law 12.527/2011)
- **Tech stack**: Python (pandas, PySUS, scikit-learn, XGBoost), DuckDB/MotherDuck, matplotlib/seaborn
- **Temporal scope**: 2015–2023 (9 years) — balances data availability with trend analysis
- **Reproducibility**: Pipeline must be fully idempotent; all outputs deterministic given same inputs
- **Privacy**: No individual-level identifiers; municipality-level aggregates only
- **Reporting**: STROBE + RECORD compliance required for submission

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Geometric mean for CUDS | Penalizes extreme imbalance across dimensions — municipalities must perform adequately across all to score high | — Pending |
| Exclude CIMI dimension 10 (International Projection) | Irrelevant at municipal level for 99% of Brazilian municipalities | ✓ Good |
| SQLite as primary database | Simple, portable, no infrastructure needed; DuckDB as optional analytical layer | ✓ Good |
| Municipality of treatment (not residence) | SIH records procedures at hospital location; documented limitation | ⚠️ Revisit |
| PySUS for DATASUS downloads | Standard Python library for Brazilian health data; handles DBC format | — Pending |
| December snapshots → full 12-month | Current snapshot introduces seasonal bias; full annualized data in progress on NAS | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-01 after initialization*
