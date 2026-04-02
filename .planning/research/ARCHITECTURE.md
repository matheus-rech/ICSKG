# Architecture Patterns

**Domain:** Reproducible ecological panel study data pipeline (multi-source ETL → composite index → ML analysis → publication)
**Project:** ICSKG-BR
**Researched:** 2026-04-01
**Confidence:** HIGH (grounded in existing codebase analysis + verified research patterns)

---

## Recommended Architecture

The pipeline has a **layered, stage-gated structure** with strict data flow direction. Each layer produces immutable artifacts consumed by the next. No layer reads upward. The final academic outputs depend on all prior layers completing cleanly.

```
┌─────────────────────────────────────────────────────────────────────┐
│  LAYER 1: Acquisition                                               │
│  Source-specific download scripts (per data source)                 │
│  Output: data_sources/raw/  ← immutable, version-pinned             │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────────┐
│  LAYER 2: Parsing / Format Normalization                            │
│  DBC→parquet, XLSX→parquet, CSV→parquet converters                  │
│  Output: data_sources/processed/<source>_YYYYMM.parquet             │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────────┐
│  LAYER 3: Validation Gate                                           │
│  Schema checks, range checks, duplicate detection, cod_ibge audit   │
│  Output: validation_report.json + flagged rows to quarantine/       │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────────┐
│  LAYER 4: Municipality-Level Aggregation + Merge                    │
│  Group-by cod_ibge + year across all sources → wide panel format    │
│  Output: data_sources/processed/merged_YYYY.parquet                 │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────────┐
│  LAYER 5: Database Persistence                                      │
│  SQLite (primary) + optional DuckDB mirror                          │
│  Output: database/icskg_br.sqlite (50,130-row panel table)          │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────────┐
│  LAYER 6: Dimension Computation (CUDS)                              │
│  Per-dimension compute functions → min-max normalize → geom mean    │
│  Output: panel_CUDS.parquet + dimension_scores table in SQLite      │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         │                    │                    │
┌────────▼────────┐  ┌────────▼────────┐  ┌────────▼────────┐
│ LAYER 7a:       │  │ LAYER 7b:       │  │ LAYER 7c:       │
│ LCoGS Indicator │  │ ML Models       │  │ Descriptive +   │
│ Computation     │  │ (RF, XGBoost)   │  │ Geospatial      │
│                 │  │                 │  │ Analysis        │
└────────┬────────┘  └────────┬────────┘  └────────┬────────┘
         └────────────────────┼────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────────┐
│  LAYER 8: Publication Output                                        │
│  4 figures, 8+ tables, STROBE/RECORD checklists                     │
│  Output: analysis/results/ + output/                                │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Component Boundaries

| Component | Responsibility | Reads From | Writes To |
|-----------|---------------|------------|-----------|
| `scripts/download_*.py` | Fetch raw files from external APIs (DATASUS, ANS, IBGE, FIRJAN, IPEA, RENAVAM, SIOPS) | External APIs / NAS | `data_sources/raw/<source>/` |
| `scripts/sih_batch_v2.py` | Convert SIH DBC files to parquet, parallel by UF | `data_sources/raw/SIH/` | `data_sources/processed/sih_YYYYMM.parquet` |
| `scripts/parse_<source>.py` (to be created) | Source-specific format converters (XLSX, CSV, API JSON) | `data_sources/raw/<source>/` | `data_sources/processed/<source>_YYYY.parquet` |
| `database/validation.py` (to be created) | Schema validation, range checks, municipality code audit, missing-data census | `data_sources/processed/*.parquet` | `data_sources/processed/validation_report.json`, `data_sources/quarantine/` |
| `database/pipeline.py` | ETL orchestrator: iterate year-months, call extract/transform/load per source | Processed parquet files | `data_sources/processed/merged_YYYY.parquet` |
| `database/build_database_v2.py` | SQLite schema DDL, upsert municipality-year rows, optional DuckDB mirror | Merged parquet files | `database/icskg_br.sqlite`, `database/icskg_br.duckdb` |
| `analysis/compute_dimensions.py` (to be created or expanded from `icskg_analysis_pipeline.py`) | One `compute_d*()` function per CIMI dimension, min-max normalization, geometric mean for CUDS | SQLite municipal_health table or merged parquet | `database/icskg_br.sqlite` (dimension_scores table), `data_sources/processed/panel_CUDS.parquet` |
| `analysis/compute_lcogs.py` (to be created) | 6 LCoGS indicator computations: access, SAO density, volume, POMR, financial risk, catastrophic expenditure | SQLite + CNES geocoded parquet + population data | `database/icskg_br.sqlite` (lcogs_indicators table) |
| `extract_lcogs1.py` | Bellwether procedure classification, rate calculation, Haversine distance to nearest hospital | SIH parquet + shapefile | `output/lcogs1_*` |
| `analysis/ml_models.py` (to be created) | Random Forest + XGBoost dose-response models, cross-validation, SHAP feature importance | Panel with CUDS + LCoGS columns | `analysis/results/model_*` |
| `analysis/icskg_analysis_pipeline.py` | Descriptive statistics, regional disparity, correlation analysis, publication figures/tables | Panel + model outputs | `analysis/results/figure*.png`, `analysis/results/table*.csv` |

---

## Data Flow

### Canonical Data Direction

```
External APIs
    │
    ▼ (download)
data_sources/raw/            ← immutable, never modified by pipeline
    │
    ▼ (parse/convert)
data_sources/processed/      ← source-partitioned parquet files
    │
    ▼ (validate)
data_sources/processed/validation_report.json
data_sources/quarantine/     ← rows failing validation
    │
    ▼ (aggregate + merge)
data_sources/processed/merged_YYYY.parquet    ← one row per municipality per year
    │
    ▼ (load)
database/icskg_br.sqlite → table: municipal_health
    │
    ▼ (dimension compute)
database/icskg_br.sqlite → table: dimension_scores  (D1–D9, CUDS)
    │
    ├──▶ table: lcogs_indicators  (L1–L6)
    │
    └──▶ ML model inputs → model outputs
              │
              ▼
analysis/results/           ← figures, tables, model summaries
output/                     ← geospatial outputs (maps, shapefiles)
```

### Join Key Flow

Every data source uses a different column name for the municipality code. The normalization must happen before merge:

```
IFGF Excel   → Cod_IBGE (7-digit)  ─┐
ANS CSV      → CD_MUNICIPIO (6-digit) ─┤  → normalize to cod_ibge (7-digit string) → merge
SIH parquet  → MUNIC_MOV (6-digit) ─┤
CNES parquet → CODUFMUN (7-digit)  ─┘
IBGE SIDRA   → API parameter       ─┘
```

The 6-digit vs 7-digit discrepancy is the single most common silent data loss point. All transformers must apply a standardized `normalize_cod_ibge()` helper before any join.

### Temporal Granularity Strategy

| Source | Native Granularity | Pipeline Aggregation |
|--------|--------------------|----------------------|
| SIH | Month (YYYYMM) | Sum/annualize to year |
| CNES | Month (YYYYMM snapshot) | December snapshot OR 12-month mean |
| ANS | Year (December enrollment) | Direct use as annual |
| IFGF | Year | Direct use |
| IBGE SIDRA | Year (GDP, population) | Direct use |
| IPEA IDHM | Year (triennial for sub-indices) | Forward-fill between census years |
| RENAVAM | Year | Direct use |
| SIOPS | Year | Deflate to 2023 BRL via IPCA before use |
| IBGE Census 2022 | Single year (2022) | Broadcast to all panel years with flag |

The final panel must be: **one row per (cod_ibge, year), 5,570 municipalities × 9 years = 50,130 rows.**

---

## Patterns to Follow

### Pattern 1: Source Extractor Function Contract

Every data source extractor must follow this contract. The contract ensures idempotent, testable units.

```python
def extract_<source>(year: int, output_dir: Path) -> Path | None:
    """
    Downloads/parses <source> data for the given year.
    Returns path to output parquet file, or None on failure.
    Output file must be overwritten cleanly on rerun (delete-write pattern).
    """
    out_path = output_dir / f"<source>_{year}.parquet"
    if out_path.exists() and not FORCE_RERUN:
        return out_path          # idempotent: skip if already done
    # ... download and parse logic ...
    df.to_parquet(out_path, index=False)
    return out_path
```

Key properties: takes year as integer, returns Path or None, checks output existence before downloading, uses delete-write on forced rerun.

### Pattern 2: Delete-Write for Idempotency

All intermediate parquet files and database rows must use delete-write, not append. This is the foundation of reproducibility.

```python
# For parquet: overwrite on rerun
df.to_parquet(out_path, index=False)   # pandas overwrites by default

# For SQLite: delete partition before insert
def upsert_year(conn, df, year):
    conn.execute("DELETE FROM municipal_health WHERE year = ?", (year,))
    df.to_sql("municipal_health", conn, if_exists="append", index=False)
```

Never use `if_exists="append"` without a preceding DELETE for the same partition.

### Pattern 3: Normalization Must Precede Any Join

```python
def normalize_cod_ibge(series: pd.Series) -> pd.Series:
    """
    Normalizes municipality codes to 7-digit zero-padded string.
    Handles: 6-digit int, 7-digit int, 6-digit string, 7-digit string.
    """
    s = series.astype(str).str.strip().str.zfill(7)
    # 6-digit codes from SIH/ANS: prepend state digit via lookup or truncate
    # Rule: if len==6 after strip, the 7th digit is a check digit that can be dropped from 7-digit codes
    # IBGE 7-digit: first 2 = UF code, next 5 = municipality
    return s
```

This function must live in a shared utilities module (`database/utils.py`) because it is called by at minimum 8 different source parsers.

### Pattern 4: Dimension Compute Function Contract

```python
def compute_d1_fiscal_governance(
    df_merged: pd.DataFrame,
    year: int
) -> pd.Series:
    """
    Returns a Series indexed by cod_ibge with raw (un-normalized) D1 values.
    Normalization (min-max to [0,1]) is applied centrally in build_panel().
    """
    ...
    return pd.Series(result, name="D1_raw")
```

Separation of raw computation from normalization allows: (1) checking raw distributions before normalization, (2) using different normalization strategies without touching compute logic, (3) applying within-year vs cross-year normalization as a configurable option.

### Pattern 5: Panel Build as Final Assembly Step

The `build_panel()` function is the single authoritative assembly point. It:
1. Calls all `compute_d*()` functions
2. Applies min-max normalization within each year (within-year is required for cross-sectional comparability)
3. Computes CUDS as geometric mean of D1–D9 (excluding D8/International Projection)
4. Validates completeness: every (cod_ibge, year) row must exist before output

```python
def build_panel(source_dir, years=range(2015, 2024)) -> pd.DataFrame:
    rows = []
    for year in years:
        df = load_merged(source_dir, year)
        dims = {f"D{i}": compute_d(df, year) for i, compute_d in DIMENSION_FUNCTIONS.items()}
        dims_normalized = {k: minmax(v) for k, v in dims.items()}
        cuds = geometric_mean(dims_normalized)
        ...
    panel = pd.concat(rows)
    assert len(panel) == 5570 * len(years), "Panel row count mismatch"
    return panel
```

The assertion is a hard gate: if municipality coverage is incomplete, the pipeline must stop and report which municipalities are missing and why, not silently produce an undersized panel.

### Pattern 6: Validation as a Mandatory Gate Layer

Validation must happen after parsing and before any merge or aggregation. Failing to validate early allows corrupted municipality codes or out-of-range values to propagate silently through 5 downstream stages.

```python
# Checks to run per source after parsing
VALIDATION_CHECKS = {
    "cod_ibge_valid": lambda df: df["cod_ibge"].isin(IBGE_MUNICIPALITY_LIST),
    "year_in_scope": lambda df: df["year"].between(2015, 2023),
    "no_duplicate_keys": lambda df: ~df.duplicated(["cod_ibge", "year"]),
    "value_in_range": ...  # source-specific
}
```

Rows failing validation go to `data_sources/quarantine/` with a reason flag, not silently dropped. The validation report is a required input to the merge stage.

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: Append Without Partition Delete

**What:** `df.to_sql("municipal_health", conn, if_exists="append")` called on every run.
**Why bad:** Reruns accumulate duplicate rows. After 3 pipeline runs, the 50,130-row panel becomes 150,390 rows. All downstream aggregations are tripled. This is the most common reproducibility failure in SQLite-backed pipelines.
**Instead:** Always DELETE the year partition before INSERT. See Pattern 2.

### Anti-Pattern 2: Mixing Normalization Granularities

**What:** Normalizing each dimension independently as it is computed, using the full 9-year range.
**Why bad:** A municipality that scores high in 2015 but low in 2023 gets different relative scores depending on whether normalization is within-year or across-years. Min-max across years conflates temporal trends with cross-sectional rank.
**Instead:** Normalize within each year. Document this choice explicitly. Cross-year comparability comes from the stable methodology, not cross-year normalization.

### Anti-Pattern 3: Direct API Reads in Analysis Layer

**What:** Calling IBGE SIDRA or CNES APIs from within `compute_d*()` or `build_panel()` functions.
**Why bad:** Analysis layer depends on network availability; reruns are non-deterministic if source data changes; IBGE API has rate limits.
**Instead:** All API calls happen exclusively in Layer 1 (Acquisition). Analysis layer reads only from parquet files or SQLite. Raw data is the immutable contract.

### Anti-Pattern 4: Single Monolithic Analysis Script

**What:** All dimension computation, ML models, and publication figures in one 2000-line script.
**Why bad:** Dimension computation failures require full rerun of ML models. Debugging is difficult. Code cannot be tested in isolation. Adding a new dimension requires understanding 2000 lines of context.
**Instead:** Separate modules for dimension computation, LCoGS indicators, ML models, and output generation. Each module has one entry point that can be run and tested independently. The orchestrator calls them in sequence.

### Anti-Pattern 5: Haversine Distance Computed Every Run

**What:** Recomputing the Haversine distance matrix between 5,570 municipalities and 765 hospitals on every pipeline run.
**Why bad:** 5,570 × 765 = 4.26 million distance computations per run. At ~10 microseconds each, this adds ~43 seconds per full run. The hospital locations do not change between runs.
**Instead:** Compute the distance matrix once and cache to `data_sources/processed/distance_matrix.parquet`. Invalidate only when the CNES hospital geocoding source file is updated.

---

## Suggested Build Order

Dependencies flow strictly upward. A component can only be built after all components it reads from are stable.

```
Phase 1: Foundation
  ├── database/utils.py            (normalize_cod_ibge, shared helpers)
  ├── database/validation.py       (validation gate functions)
  └── IBGE municipality list       (reference for 5,570 cod_ibge values)

Phase 2: Data Acquisition (parallel — sources are independent)
  ├── scripts/download_ibge_sidra.py
  ├── scripts/download_ipea_idhm.py
  ├── scripts/download_firjan_ifgf.py   (may already exist as Excel parser)
  ├── scripts/download_ans.py           (already exists)
  ├── scripts/download_renavam.py
  ├── scripts/download_siops.py
  ├── scripts/download_ibge_census.py
  └── scripts/download_cnes_professionals.py

Phase 3: Parsing / Format Normalization (depends on Phase 2)
  ├── scripts/sih_batch_v2.py           (already exists)
  ├── scripts/parse_cnes_professionals.py
  ├── scripts/parse_ibge_sidra.py
  ├── scripts/parse_ipea_idhm.py
  ├── scripts/parse_firjan_ifgf.py
  ├── scripts/parse_ans.py
  ├── scripts/parse_renavam.py
  ├── scripts/parse_siops.py
  └── scripts/parse_ibge_census.py

Phase 4: Validation Gate (depends on Phase 3)
  └── database/validation.py            (run against all processed parquet outputs)

Phase 5: Aggregation + Merge (depends on Phase 4)
  └── database/pipeline.py              (transform_merge expanded for 8+ sources)

Phase 6: Database Load (depends on Phase 5)
  └── database/build_database_v2.py     (schema expanded for all dimensions + LCoGS)

Phase 7: Dimension Computation (depends on Phase 6)
  ├── analysis/compute_dimensions.py    (D1–D9 + CUDS geometric mean)
  └── analysis/compute_lcogs.py         (L1–L6 indicators)

Phase 8: Specialized Extraction (depends on Phase 6, can run parallel to Phase 7)
  └── extract_lcogs1.py                 (already exists, needs full 12-month SIH)

Phase 9: ML Models (depends on Phase 7)
  └── analysis/ml_models.py             (Random Forest + XGBoost dose-response)

Phase 10: Publication Output (depends on Phases 7, 8, 9)
  └── analysis/icskg_analysis_pipeline.py  (figures, tables, STROBE checklist)
```

Phases 2 and 3 can be partially parallelized (sources are independent). All other phases are strictly sequential.

---

## Scalability Considerations

| Concern | Current Scale (50,130 rows) | If Extended (e.g., all municipalities × 20 years) |
|---------|-----------------------------|----------------------------------------------------|
| SQLite write performance | No issue; upserts complete in seconds | SQLite WAL mode handles ~100K rows easily |
| Parquet file count | ~108 files (9 years × 12 months for SIH + ~8 annual sources) | Linear growth; manageable |
| DuckDB analytical queries | Optional mirror; query time for 50K rows is <1 second | DuckDB handles millions of rows efficiently |
| ML training time | RF/XGBoost on 50K rows with ~20 features: <60 seconds | No concern at this scale |
| Distance matrix | 5,570 × 765 = 4.26M pairs; cache once | Cached, no scaling issue |
| Memory | 50,130 rows × ~30 columns × 8 bytes ≈ 12 MB; trivially fits in RAM | No issue |

SQLite is the correct choice for this project. The data volume never justifies a server database.

---

## Component Communication Summary

```
scripts/         → data_sources/raw/           (filesystem: DBC, CSV, XLSX, JSON)
scripts/         → data_sources/processed/     (filesystem: parquet)
database/        → data_sources/processed/     (filesystem read: parquet)
database/        → database/icskg_br.sqlite    (SQLite write)
analysis/        → database/icskg_br.sqlite    (SQLite read)
analysis/        → data_sources/processed/     (parquet read, fallback)
analysis/        → analysis/results/           (filesystem write: PNG, CSV)
extract_lcogs1.py → data_sources/processed/   (parquet read)
extract_lcogs1.py → output/                   (filesystem write: PNG, CSV)
```

No component calls another component's functions directly across layer boundaries. The only inter-layer communication is through filesystem artifacts (parquet, SQLite, CSV). This strict boundary enables: independent testing of each layer, partial reruns without full pipeline execution, and reproducible auditing (every artifact is traceable to its producer).

---

## Existing Architecture Gaps (to Address in Roadmap)

| Gap | Impact | Resolution |
|-----|--------|------------|
| No shared `normalize_cod_ibge()` utility | Silent municipality code mismatches in merges | Create `database/utils.py` in Phase 1 |
| No validation gate between parsing and merge | Corrupted codes propagate silently | Create `database/validation.py` in Phase 1 |
| 5 of 8 data sources have no extraction code | Panel cannot be built | Phases 2–3 of build order |
| Analysis pipeline reads IFGF/ANS directly (bypasses SQLite) | Two sources of truth | Route all analysis reads through SQLite after Phase 6 |
| CUDS uses arithmetic mean (existing code) vs geometric mean (methodology) | Published methodology mismatch | Fix in Phase 7 dimension computation |
| December snapshot for SIH vs full 12-month annualized | Seasonal bias in surgical volume | Resolve in Phase 3 SIH parsing |
| No municipality list reference file | Cannot validate cod_ibge completeness | Acquire IBGE 2023 municipality list in Phase 1 |
| `extract_lcogs1.py` is standalone, not integrated into main pipeline | LCoGS-1 output is not in SQLite panel | Integrate in Phase 8 |

---

## Sources

- Existing codebase analysis (`database/pipeline.py`, `database/build_database_v2.py`, `analysis/icskg_analysis_pipeline.py`, `extract_lcogs1.py`) — HIGH confidence
- [Idempotent Data Pipeline Patterns — Start Data Engineering](https://www.startdataengineering.com/post/why-how-idempotent-data-pipeline/) — MEDIUM confidence
- [Reproducible Analytical Pipeline Journey — ONS Data Science Campus](https://datasciencecampus.ons.gov.uk/capability/data-science-campus-faculty/reproducible-analytical-pipeline-journey/) — MEDIUM confidence
- [Reproducible Pipeline with PySUS for DATASUS (2024) — RSD Journal](https://rsdjournal.org/rsd/article/view/50704) — MEDIUM confidence (peer-reviewed, same PySUS toolchain)
- [Limitations of DATASUS SIH as Research Data Source — PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC10508673/) — HIGH confidence (peer-reviewed scoping review, directly applicable)
- [Composite Index Methodology — Springer Social Indicators Research](https://link.springer.com/article/10.1007/s11205-017-1832-9) — MEDIUM confidence (geometric mean aggregation rationale)

---

*Architecture research: 2026-04-01*
