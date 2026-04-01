# Technology Stack

**Project:** ICSKG-BR — Municipal Urban Development & Global Surgery Panel Study
**Researched:** 2026-04-01
**Overall confidence:** HIGH (all critical libraries verified via PyPI official pages)

---

## Recommended Stack

### Python Runtime

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Python | 3.12 | Runtime | Most stable data-science Python as of April 2026. pandas 3.x requires >=3.11; PySUS 1.x requires >=3.10. Python 3.12 is the sweet spot — full ecosystem support without the edge-case breakage still present in 3.13 binary wheels for some C-extension packages. Avoid 3.9 (current codebase default) — pandas 3.0 dropped it and PySUS 1.0 dropped it. |
| uv | latest | Package/env management | Generates a cross-platform `uv.lock` (pyproject.toml-based). Reproducibility requirement of the study demands exact pinned hashes, not a loose `requirements.txt`. 10-100x faster than pip. PEP 751 accepted March 2025 ratifies this direction. Replaces the current absent lockfile. |

---

### Data Processing Core

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| pandas | 2.2.3 | DataFrame operations, CSV/Excel I/O, panel assembly | **Pin to 2.2.3, not 3.x.** pandas 3.0 (released Jan 2026) requires Python >=3.11, makes Copy-on-Write mandatory, and changes string dtype defaults — all of which will silently break the existing codebase. Migrate to 3.x after the pipeline is working end-to-end. |
| numpy | 2.x (>=2.0) | Numerical operations, min-max normalization, geometric mean | numpy 2.0 broke binary compatibility with older extensions; the rest of the stack (scikit-learn 1.6+, XGBoost 3.x) already requires it. |
| pyarrow | >=19.0 | Parquet intermediate storage, DBC→Parquet conversion, Arrow memory model | The canonical intermediate format for state-by-year Parquet partitions. DuckDB reads Parquet natively with predicate pushdown. pyarrow 19 is the current stable series as of early 2026. |

---

### DATASUS / Health Data Acquisition

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| pysus | 1.0.1 | SIH (RD*.dbc), CNES (ST*.dbc) download and DBC→Parquet conversion | **The authoritative library for Brazilian health data.** AlertaDengue/PySUS 1.0.1 (Feb 2026) is the actively maintained fork — not the older fccoelho/PySUS. Supports Python 3.10–3.13. Provides `pysus.ftp` classes for FTP retrieval and `ParquetSet` for DBC→Parquet. The existing `ftplib`-based custom downloader in `scripts/continue_raw_download.py` should be replaced with pysus's FTP layer — it handles DBC format, resume logic, and state enumeration. |
| datasus-fetcher | 0.4.1 | Fallback TabNet-based download for datasets not in pysus | Released Feb 2025. Covers SIH, SIA, SINAN and others via DATASUS transfer endpoint. Use only as fallback — pysus is the primary. SIOPS is **not** covered by either library; must use direct FTP or TabNet scraping (see PITFALLS). |
| requests | >=2.32 | ANS open-data portal HTTP downloads | Existing `scripts/download_ans.py` uses requests correctly. Keep. |

---

### Brazilian Government Data APIs

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| sidrapy | 0.1.4 | IBGE SIDRA API — population estimates (table 6579), GDP per capita (table 5938) | Last released Sept 2022. Alpha status. **Use it anyway** — it is the only maintained Python wrapper for SIDRA. The alternative is raw `requests` calls to `https://apisidra.ibge.gov.br/`, which is straightforward but verbose. The IBGE SIDRA API itself is stable; the wrapper's dormancy is acceptable risk for a read-only academic pipeline. |
| ipeadatapy | 0.1.9 | IPEA API — IDHM composite and sub-indices (HDI_GINI, IDHM, IDHM_E, IDHM_L, IDHM_R) | Last released Feb 2023. Same caveat as sidrapy — use it, but wrap the call defensively. The IPEA OData4 API (`http://www.ipeadata.gov.br/api/odata4/`) is stable and documented; ipeadatapy is just a thin wrapper. |
| geobr | 0.2.2 | IBGE municipality shapefiles (SIRGAS2000 CRS 4674), state boundaries | Python package v0.2.2 (Nov 2024). "Maturing" status. Use for: geocoding the 765 bellwether hospitals, Haversine distance computation to nearest facility, choropleth maps for paper figures. Do NOT use for the core data pipeline — only for geospatial analysis and figures. |

---

### Database Layer

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| SQLite (stdlib `sqlite3`) | 3.x (stdlib) | Primary panel database — municipality-year observations | Keep existing choice. 50,130 rows × ~50 columns is trivially small for SQLite. Portable, zero-infrastructure, opens directly in DB Browser for peer review. The assembled panel fits in <50 MB. |
| duckdb | 1.5.1 | Analytical query layer over Parquet intermediate files | **Promote from "optional" to mandatory for the raw-data ETL stage.** Querying 100+ GB of per-state Parquet files (SIH 2015–2023) with SQL + predicate pushdown is the correct pattern here. pandas would load entire files into RAM. DuckDB reads what it needs, uses all CPU cores, and writes directly to the SQLite panel via ATTACH. Use pattern: `duckdb → aggregated DataFrame → SQLite`. |

---

### Machine Learning

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| scikit-learn | >=1.6,<2.0 | Random Forest regressor/classifier, preprocessing pipelines, cross-validation, feature importance | Current stable is 1.8.x (June 2025 series). Use `RandomForestRegressor` for dose-response CUDS → LCoGS models. The sklearn API is stable and the scikit-learn estimator interface means models serialize cleanly for reproducibility. |
| xgboost | >=2.1,<4.0 | Gradient boosted trees for CUDS → LCoGS relationships | Current stable is 3.2.0 (Feb 2026). Requires Python >=3.10. XGBoost 3.x changed the default objective function behaviour — pin >=2.1 and test against expected outputs. Use via the sklearn wrapper (`XGBRegressor`) for consistent cross-validation. |
| linearmodels | 7.0 | Two-way fixed-effects panel regression (municipality FE + year FE) | Production/Stable, released Oct 2025. The correct tool for the ecological panel's statistical models. Supports `PanelOLS` with entity and time effects, clustered standard errors by municipality. **This is missing from the current stack** and must be added for the formal regression tables required by BMJ Global Health. |

---

### Visualization

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| matplotlib | >=3.9 | Publication figures — choropleth maps, scatter plots, regression diagnostic plots | Current stable is 3.10.x. Always export at 300 DPI minimum; BMJ Global Health accepts TIFF/EPS/PDF. |
| seaborn | >=0.13 | Statistical visualization — correlation heatmaps, box plots for regional disparity analysis | Built on matplotlib. Use `seaborn.objects` (v0.12+ interface) for composable figure construction. |
| SciencePlots | >=2.1 | Journal-ready matplotlib style (IEEE/Nature-compatible sans-serif, correct line weights) | One-liner `plt.style.use('science')` applies BMJ-compatible figure styling. Dramatically reduces figure polish time. Currently absent from the stack. |

---

### Geospatial

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| geopandas | 1.1.3 | Haversine distance computation, spatial joins, choropleth map generation | Required for LCoGS-1 (2-hour travel time to bellwether hospital). Existing `extract_lcogs1.py` already uses it. |
| shapely | >=2.0 | Geometry operations (point-in-polygon, distance calculations) | geopandas 1.x depends on shapely 2.x; shapely 2 uses a vectorized C++ engine 3-6x faster than shapely 1. Already a transitive dependency of geopandas. |

---

### Supporting Utilities

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| openpyxl | >=3.1 | FIRJAN IFGF Excel parser (bundled file `Evolucao_por_Indicador_2013_a_2024_IFGF_2025.xlsx`) | Existing, correct choice. Keep. |
| tqdm | >=4.66 | Progress bars for long FTP download loops and per-municipality computation passes | The pipeline processes 5,570 municipalities × 9 years. Without progress indication, runs look hung. Currently absent. |
| python-dotenv | >=1.0 | Optional credentials (none currently required, but ANS/IBGE API keys may be needed) | Defensive inclusion. The project has no secrets today but SERPRO-gated APIs (RENAVAM, SIOPS direct access) may require auth. |

---

## Alternatives Considered and Rejected

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| DataFrame library | pandas 2.2.3 | Polars | Polars is 3-10x faster but the entire existing codebase is pandas. The performance difference is irrelevant at 50,130 rows. Polars incompatibility with scikit-learn/XGBoost pipelines adds friction. Migrate only if ETL raw-data stage becomes a bottleneck (unlikely). |
| Workflow orchestration | None (plain Python scripts) | Kedro, Prefect, Snakemake | Overkill for a single-researcher academic pipeline. The existing script-based ETL is the right level of complexity. Add Makefile targets for orchestration instead. |
| Environment management | uv | pip + requirements.txt | The current absent lockfile is a reproducibility risk for journal submission. uv.lock solves this without adding workflow complexity. |
| Census 2022 data access | Direct IBGE Census API + censobr | basedosdados | basedosdados requires Google BigQuery credentials and cloud connectivity, making it unsuitable for reproducible research with no external auth dependencies. Use direct IBGE Census 2022 tabular downloads (available as CSV at `https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/`). |
| Panel regression | linearmodels | statsmodels MixedLM | linearmodels `PanelOLS` is purpose-built for panel fixed-effects with clustered SEs. statsmodels requires manual dummy-variable encoding to achieve the same result. |
| IDHM access | ipeadatapy | Direct IPEA OData REST | ipeadatapy is dormant but saves 20 lines of boilerplate. Wrap with a try/except that falls back to raw `requests` if the wrapper fails. |

---

## Version Summary for pyproject.toml

```toml
[project]
name = "icskg-br"
requires-python = ">=3.12,<3.14"
dependencies = [
    # Core data processing
    "pandas>=2.2.3,<3.0",
    "numpy>=2.0",
    "pyarrow>=19.0",
    # DATASUS / health data
    "pysus>=1.0.1",
    "datasus-fetcher>=0.4.1",
    "requests>=2.32",
    # Brazilian government APIs
    "sidrapy>=0.1.4",
    "ipeadatapy>=0.1.9",
    # Database
    "duckdb>=1.5.1",
    # Machine learning
    "scikit-learn>=1.6,<2.0",
    "xgboost>=2.1,<4.0",
    "linearmodels>=7.0",
    # Visualization
    "matplotlib>=3.9",
    "seaborn>=0.13",
    "SciencePlots>=2.1",
    # Geospatial
    "geopandas>=1.1",
    # Supporting utilities
    "openpyxl>=3.1",
    "tqdm>=4.66",
    "python-dotenv>=1.0",
]
```

---

## Installation

```bash
# Install uv (if not present)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create project environment and install all deps
uv sync

# Verify critical imports
uv run python -c "import pysus, pandas, duckdb, xgboost, linearmodels; print('Stack OK')"
```

---

## Key Stack Decisions for Roadmap

1. **Upgrade Python 3.9 → 3.12 immediately.** PySUS 1.x does not support 3.9. This is a hard blocker.

2. **Replace custom ftplib downloader with pysus 1.x FTP layer.** The existing `continue_raw_download.py` reimplements what PySUS already provides with better error handling.

3. **Promote DuckDB from optional to mandatory for raw ETL.** Raw SIH/CNES Parquet files (100+ GB) should be aggregated via DuckDB SQL, not pandas `read_parquet` loops.

4. **Add linearmodels for formal regression tables.** The analysis pipeline currently has no panel fixed-effects implementation. This is required for BMJ Global Health submission.

5. **Add lockfile via uv.** No lockfile means the pipeline is not reproducible as stated. This is a one-time setup cost.

6. **SIOPS has no Python library.** Per-capita health expenditure data must be scraped from the SIOPS TabNet portal or accessed via direct CSV download from `https://portalfns.saude.gov.br/siops/siops-downloads/`. Budget time for this.

7. **RENAVAM has no public Python API.** Municipal vehicle fleet data must be downloaded as monthly CSV files from `https://dados.transportes.gov.br/dataset/registro-nacional-de-veiculos-automotores-renavam`. Budget time for this parser.

---

## Confidence Assessment

| Component | Confidence | Source | Notes |
|-----------|------------|--------|-------|
| PySUS 1.0.1 | HIGH | PyPI official page (verified Apr 2026) | Python 3.10–3.13 confirmed |
| pandas 2.2.3 pin | HIGH | PyPI + pandas docs | pandas 3.0 breaks existing code; 2.2.3 is the safe stable |
| DuckDB 1.5.1 | HIGH | PyPI official page (verified Apr 2026) | |
| scikit-learn 1.6+ | HIGH | PyPI + scikit-learn docs | |
| XGBoost 3.2.0 | HIGH | PyPI + xgboost docs | |
| linearmodels 7.0 | HIGH | PyPI official page (verified) | Production/Stable |
| geopandas 1.1.3 | HIGH | PyPI official page (verified) | |
| sidrapy 0.1.4 | MEDIUM | PyPI — last updated Sept 2022 | Alpha, dormant; API itself is stable |
| ipeadatapy 0.1.9 | MEDIUM | PyPI — last updated Feb 2023 | Dormant; IPEA OData4 API is stable |
| SIOPS download path | LOW | gov.br portal docs — no Python library exists | Manual HTTP/FTP approach required; test before committing to plan |
| RENAVAM download path | LOW | dados.transportes.gov.br — CSV available but structure undocumented | Requires format validation against actual files |
| geobr Python 0.2.2 | MEDIUM | PyPI + GitHub — "maturing" status | Use R version as fallback if Python version breaks |

---

## Sources

- PySUS PyPI: https://pypi.org/project/pysus/ (verified Apr 2026, v1.0.1)
- PySUS GitHub releases: https://github.com/AlertaDengue/PySUS/releases
- pandas PyPI: https://pypi.org/project/pandas/ (v3.0.2, Jan 2026)
- pandas 3.0 migration blog: https://pandas.pydata.org/community/blog/pandas-3.0.html
- DuckDB PyPI: https://pypi.org/project/duckdb/ (v1.5.1, Mar 2026)
- scikit-learn docs: https://scikit-learn.org/stable/
- XGBoost PyPI: https://pypi.org/project/xgboost/ (v3.2.0)
- linearmodels PyPI: https://pypi.org/project/linearmodels/ (v7.0, Oct 2025)
- geopandas PyPI: https://pypi.org/project/geopandas/ (v1.1.3, Mar 2026)
- sidrapy PyPI: https://pypi.org/project/sidrapy/ (v0.1.4, Sep 2022)
- ipeadatapy GitHub: https://github.com/luanborelli/ipeadatapy/
- geobr PyPI: https://pypi.org/project/geobr/ (v0.2.2, Nov 2024)
- geobr GitHub: https://github.com/ipeaGIT/geobr
- datasus-fetcher PyPI: https://pypi.org/project/datasus-fetcher/ (v0.4.1, Feb 2025)
- PEP 751 lockfile standard: https://peps.python.org/pep-0751/
- uv docs: https://docs.astral.sh/uv/
- SIOPS downloads portal: https://portalfns.saude.gov.br/siops/siops-downloads/
- RENAVAM open data: https://dados.transportes.gov.br/dataset/registro-nacional-de-veiculos-automotores-renavam
- numpy PyPI: https://pypi.org/project/numpy/ (v2.4.4, Mar 2026)
- pyarrow docs: https://arrow.apache.org/docs/python/parquet.html
