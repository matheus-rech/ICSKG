# Phase 2: SIH & CNES Extraction - Research

**Researched:** 2026-04-01
**Domain:** FIOCRUZ BigData ETLSIH/ETLCNES CSV parsing, Parquet writing, DuckDB CSV performance
**Confidence:** HIGH

## Summary

Phase 2 extracts SIH (hospital admissions) and CNES (facility registry) data from FIOCRUZ BigData pre-processed CSVs stored on the researcher's NAS, applies column subsetting, municipality code normalization, and validation, then writes processed Parquet files. The SIH data is 354 GB across 5,643 CSV files already on NAS at `/Volumes/docker/Downloads/`. The CNES data is a 2.9 GB zip file at `/Volumes/docker/Downloads2/ETLCNES.zip` containing 6,534 ST (establishment) files -- but critically, NO PF (professional) files are present. The CNES professional data required for LCoGS-2 (SAO workforce density) will need separate acquisition via PySUS from DATASUS FTP.

**Critical data format correction:** The data is FIOCRUZ BigData ETLSIH CSV format with 235 columns (not DATASUS DBC). File pattern: `ETLSIH.ST_{UF}_{YEAR}_{MONTH}_t.csv`. Standard comma-separated, no special encoding needed. No PySUS blast-dbf or DBC conversion required.

**Critical CBO code correction:** The CONTEXT.md references CBO-2002 family codes 2231-xx (surgeons), 2232-xx (anesthesiologists), 2235-xx (obstetricians). This is INCORRECT. In CBO-2002: family 2231 = Medicos (ALL physicians, too broad), 2232 = Cirurgioes-dentistas (DENTISTS), 2235 = Enfermeiros (NURSES). The correct 6-digit CBO codes for SAO filtering are: Surgeons = 225225 (cirurgiao geral) + surgical subspecialties (2252xx), Anesthesiologists = 225151, Obstetricians = 225250.

**Primary recommendation:** Use DuckDB `read_csv_auto()` for SIH CSV reading (benchmarked at 4.5s for full SP monthly file with 210k rows); refactor `sih_batch_v2.py` to read CSVs instead of DBC; defer CNES PF professional extraction to a follow-up task since the data is not yet available.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- SIH data is already downloaded on NAS as FIOCRUZ BigData CSVs (NOT DATASUS DBC format)
- File naming pattern: `ETLSIH.ST_{UF}_{YEAR}_{MONTH}_t.csv` (e.g., `ETLSIH.ST_AC_2008_1_t.csv`)
- No DBC conversion or PySUS blast-dbf needed -- direct CSV reading with pandas or DuckDB
- Refactor existing `scripts/sih_batch_v2.py` to read CSVs instead of DBC; keep multiprocess per-UF parallelization
- Read-only access to originals on NAS -- pipeline MUST NOT modify, move, or delete source files
- If NAS not mounted during development, test with a small sample copied locally
- CNES data sourced from FIOCRUZ BigData ETLCNES (per D-08 from Phase 1) -- currently being downloaded
- Professional CBO filtering: CBO-2002 codes -- surgeons, anesthesiologists, obstetricians
- Facility bellwether criteria: surgical center OR obstetric center OR >=10 inpatient beds (Lancet Commission)
- CNS deduplication: per municipality-year (a professional working in 2 hospitals counts once per municipality)
- SIH output: per-state monthly Parquet files (`data_sources/processed/sih/SP_202301.parquet`)
- SIH keeps ~15 surgical columns: MUNIC_MOV, DIAG_PRINC, PROC_REA, VAL_TOT, MORTE, DT_INTER, DT_SAIDA, etc.
- SIH produces BOTH procedure-level Parquet AND municipality-year aggregates
- CNES output: two separate Parquets -- `professionals.parquet` and `facilities.parquet` (different schemas)
- All processed files written to `data_sources/processed/sih/` and `data_sources/processed/cnes/` per config.yaml
- normalize_cod_ibge() applied to all municipality codes before writing
- validate_dataframe() run on each output before persistence

### Claude's Discretion
- Exact column selection from ETLSIH CSVs (must include columns needed for LCoGS-3/4/5/6)
- DuckDB vs pandas for CSV reading (DuckDB may be faster for 100+ GB corpus)
- Chunk size and memory management strategy
- How to handle the CNES download being in progress (skip CNES if not available, or wait)
- Test data strategy when NAS is not mounted

### Deferred Ideas (OUT OF SCOPE)
- PolisPCDaS integration for cross-validation of extracted indicators (Phase 4 or later)
- SIH procedure cost analysis (Phase 6 LCoGS-5/6)
- CNES geocoding for bellwether hospital mapping (Phase 6 LCoGS-1)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DATA-01 | SIH processor -- read raw SIH data from NAS, convert to Parquet, aggregate to municipality-year level | ETLSIH CSV format fully mapped (235 columns, comma-separated). DuckDB benchmarked. Column subset identified. NAS accessible at `/Volumes/docker/Downloads/`. 5,643 files, 354 GB. |
| DATA-02 | CNES extractor -- professional records (PF group) with CBO-based filtering; facility records for bellwether hospital identification | CNES ST (establishment) files available in zip (6,534 files). ST columns mapped for bellwether identification (CENTRCIR, CENTROBS, QTLEITP1/2/3). **CNES PF (professional) files NOT available** -- only ST files in ETLCNES.zip. PF data must come from DATASUS PySUS download. CBO codes corrected. |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| duckdb | 1.5.1 | CSV reading, column projection, filtering | 3-10x faster than pandas for large CSV; vectorized execution; glob patterns for multi-file reads |
| pandas | 2.3.3 | DataFrame manipulation, aggregation, Parquet writing | Standard data manipulation; already used throughout codebase |
| pyarrow | 23.0.1 | Parquet I/O backend, columnar compression | Required by pandas for Parquet; snappy compression standard |
| pyyaml | 6.0+ | config.yaml loading for NAS path resolution | Already wired in pipeline.py load_config() |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pysus | 1.0.1 | DATASUS FTP download for CNES PF files | Only for CNES PF professional data (not available in FIOCRUZ zip) |
| numpy | 2.4.4 | NaN handling in normalize_cod_ibge | Already a dependency; used for null_mask pattern |
| tqdm | 4.64.0 | Progress bars for long processing runs | Optional; useful for 2,916 SIH files (27 UFs x 12 months x 9 years) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| DuckDB for CSV reading | pandas read_csv | DuckDB is 3-10x faster with column projection on large files; pandas simpler for small files |
| DuckDB for CSV reading | polars | Not in project dependencies; DuckDB already pinned at 1.5.1 |
| multiprocessing per-UF | DuckDB glob pattern | DuckDB glob reads all UF files in one query; simpler than multiprocessing but harder to show per-UF progress |

**Installation:**
All dependencies already installed in project venv (verified). No new packages needed.

```bash
# Verified in .venv:
# duckdb 1.5.1, pandas 2.3.3, pyarrow 23.0.1, pysus 1.0.1, pytest 9.0.2
```

## Architecture Patterns

### Recommended Project Structure
```
scripts/
  sih_extract.py          # NEW: ETLSIH CSV -> Parquet processor (replaces sih_batch_v2.py DBC logic)
  cnes_extract.py         # NEW: ETLCNES CSV -> Parquet processor (facilities + professionals)
database/
  pipeline.py             # MODIFY: rewire extract_sih() and extract_cnes() stubs
  utils.py                # EXISTING: normalize_cod_ibge(), rename_municipality_column()
  validation.py           # EXISTING: validate_dataframe()
data_sources/
  processed/
    sih/                  # SIH per-state monthly Parquets: {UF}_{YYYYMM}.parquet
    sih_aggregated/       # SIH municipality-year aggregates: sih_mun_year_{YEAR}.parquet
    cnes/
      facilities.parquet  # CNES bellwether facility registry
      professionals.parquet  # CNES SAO workforce (when PF data available)
tests/
  test_sih_extract.py     # NEW: SIH extraction tests
  test_cnes_extract.py    # NEW: CNES extraction tests
  fixtures/               # NEW: small sample CSV files for offline testing
```

### Pattern 1: DuckDB Column-Projection CSV Read
**What:** Use DuckDB to read only needed columns from large CSVs, avoiding loading 235 columns into memory.
**When to use:** For SIH extraction from 354 GB corpus.
**Example:**
```python
# Source: Verified by benchmark on actual NAS data (2026-04-01)
import duckdb

SIH_COLS_KEEP = [
    "UF_ZI", "ANO_CMPT", "MES_CMPT", "N_AIH", "IDENT",
    "MUNIC_RES", "MUNIC_MOV", "NASC", "SEXO", "IDADE", "COD_IDADE",
    "DIAS_PERM", "DIAG_PRINC", "DIAG_SECUN", "PROC_SOLIC", "PROC_REA",
    "DT_INTER", "DT_SAIDA", "MORTE", "VAL_TOT", "VAL_UTI",
    "CNES", "COMPLEX", "FINANC", "CAR_INT", "RACA_COR",
    "CGC_HOSP", "ESPEC",
]

def read_sih_csv(path: str, columns: list[str] | None = None) -> "pd.DataFrame":
    cols = columns or SIH_COLS_KEEP
    col_list = ", ".join(cols)
    con = duckdb.connect()
    df = con.execute(
        f"SELECT {col_list} FROM read_csv_auto('{path}')"
    ).fetchdf()
    con.close()
    return df
```

### Pattern 2: NAS Path Resolution via config.yaml
**What:** Use load_config() to resolve NAS mount point, with fallback to local data_sources/.
**When to use:** All extraction code that reads raw data.
**Example:**
```python
# Source: Existing pattern in database/pipeline.py
from database.pipeline import load_config

cfg = load_config()
data_root = Path(cfg.get("data_root", "data_sources"))
nas_sih_dir = data_root / cfg.get("raw_dir", "raw")
# For NAS: config.yaml sets data_root to /Volumes/docker/Downloads
# For local dev: defaults to data_sources/raw
```

### Pattern 3: Idempotent Per-UF-Month Output
**What:** Check if output Parquet exists before processing; skip if already done.
**When to use:** SIH extraction across 2,916 UF-month combinations.
**Example:**
```python
# Source: Existing pattern in sih_batch_v2.py _process_uf()
output_path = processed_dir / "sih" / f"{uf}_{year}{month:02d}.parquet"
if skip_existing and output_path.exists() and output_path.stat().st_size > 0:
    logger.debug("Partition exists, skipping: %s", output_path)
    return output_path
```

### Pattern 4: Municipality-Year Aggregation
**What:** After writing procedure-level Parquet, produce municipality-year aggregates needed by downstream phases.
**When to use:** SIH data needs both granularities.
**Example:**
```python
# Aggregation for LCoGS indicators
agg = df.groupby(["cod_ibge", "year"]).agg(
    n_procedures=("N_AIH", "count"),
    n_deaths=("MORTE", "sum"),
    total_cost=("VAL_TOT", "sum"),
    avg_stay=("DIAS_PERM", "mean"),
).reset_index()
```

### Anti-Patterns to Avoid
- **Loading all 235 ETLSIH columns:** Always use column projection. SP monthly file at 235 cols = ~1 GB in memory; with 27 cols = ~120 MB.
- **Reading CSVs with pandas for large files:** DuckDB is 3-10x faster for column-projected reads. Use pandas only for small files or post-DuckDB manipulation.
- **Modifying NAS files:** Read-only access. Never write to `/Volumes/docker/Downloads/`.
- **Processing all years when testing:** Use 2023 data only during development; scale to 2015-2023 after verification.
- **Hardcoding NAS path:** Always resolve through config.yaml / load_config().
- **Using 4-digit CBO family codes for professional filtering:** Must use 6-digit codes (225225, 225151, 225250).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| CSV column projection on 235 cols | Custom chunked pandas reader | DuckDB `read_csv_auto()` with SELECT | DuckDB pushes column projection to I/O layer; pandas reads all cols then drops |
| Municipality code normalization | New normalization function | `database.utils.normalize_cod_ibge()` | Already handles 6-digit, 7-digit, NaN, whitespace; tested |
| Data validation gate | Ad-hoc assertions | `database.validation.validate_dataframe()` | Already implements 4-check pipeline with quarantine mode |
| Municipality column renaming | Manual if/else on column names | `database.utils.rename_municipality_column()` | Handles all known variants (MUNIC_MOV, MUNIC_RES, CODUFMUN, etc.) |
| Parquet compression | Custom compression logic | `df.to_parquet(path, compression="snappy")` | pyarrow handles snappy natively; standard across codebase |

**Key insight:** Phase 1 built the foundation utilities (normalize_cod_ibge, validate_dataframe, rename_municipality_column) specifically for this phase. Use them -- don't duplicate logic.

## Common Pitfalls

### Pitfall 1: MUNIC_MOV is 6-digit Integer, Not 7-digit String
**What goes wrong:** MUNIC_MOV=120020 loaded as int64 fails IBGE reference validation (expects "1200205" 7-digit string).
**Why it happens:** DATASUS uses 6-digit municipality codes; IBGE reference uses 7-digit with check digit.
**How to avoid:** Apply `normalize_cod_ibge()` immediately after CSV read. It zero-pads 6-digit to 7-digit string.
**Warning signs:** Validation gate quarantines 100% of rows for "cod_ibge_valid" check.

### Pitfall 2: CNES PF Professional Data Not Available
**What goes wrong:** Phase plan assumes CNES PF files are in ETLCNES.zip -- they are NOT. Only ST (establishment) files exist.
**Why it happens:** FIOCRUZ BigData only provides ETLCNES.ST (establishment) files. PF (professional) files use a different distribution channel via DATASUS FTP.
**How to avoid:** Split CNES into two separate tasks: (1) CNES ST facility extraction from zip (available now), (2) CNES PF professional download from DATASUS via PySUS (separate acquisition). Mark PF as a dependency-gated task.
**Warning signs:** Looking for `ETLCNES.PF_*` files in the zip returns zero results.

### Pitfall 3: CBO Code Family vs 6-Digit Mismatch
**What goes wrong:** Filtering CNES PF by CBO prefix "2231" captures ALL physicians (family medicine, dermatology, etc.) instead of surgeons only.
**Why it happens:** CBO-2002 family 2231 = "Medicos" (all physicians). Surgical specialties are 6-digit codes like 225225 (cirurgiao geral).
**How to avoid:** Use exact 6-digit CBO codes: Surgeons = 225210-225295 range, Anesthesiologists = 225151, Obstetricians = 225250.
**Warning signs:** SAO count is 10x higher than expected literature values.

### Pitfall 4: DT_INTER and DT_SAIDA Are Integers, Not Dates
**What goes wrong:** Date arithmetic fails because DT_INTER=20150126 is int64, not datetime.
**Why it happens:** DATASUS encodes dates as YYYYMMDD integers.
**How to avoid:** Convert explicitly: `pd.to_datetime(df["DT_INTER"].astype(str), format="%Y%m%d", errors="coerce")`.
**Warning signs:** TypeError when computing length of stay or 30-day mortality window.

### Pitfall 5: ETLCNES File Naming Uses Double Underscore and 2-Digit Year
**What goes wrong:** Glob pattern `ETLCNES.ST_{UF}_{YEAR}_{MONTH}_t.csv` matches nothing.
**Why it happens:** Actual pattern is `ETLCNES.ST_{UF}__{YY}_{MM}_t.csv` (double underscore, 2-digit year): e.g., `ETLCNES.ST_SP__15_01_t.csv`.
**How to avoid:** Use correct pattern: `ETLCNES.ST_{uf}__{yy:02d}_{mm:02d}_t.csv`.
**Warning signs:** Zero files matched from CNES zip extraction.

### Pitfall 6: NAS Mount Not Available During CI/Testing
**What goes wrong:** Tests fail because `/Volumes/docker/Downloads/` doesn't exist on CI.
**Why it happens:** NAS is a local SMB mount specific to the researcher's machine.
**How to avoid:** Create small fixture CSVs (5-10 rows) in `tests/fixtures/` with correct column headers. Use config.yaml fallback to local paths.
**Warning signs:** FileNotFoundError on any path starting with `/Volumes/`.

### Pitfall 7: SP Monthly File is 364 MB -- Memory Pressure
**What goes wrong:** Loading all 235 columns of ETLSIH.ST_SP with pandas uses ~2 GB RAM per file; parallel processing of 12 months exhausts memory.
**Why it happens:** SP has ~210,000 admissions per month with 235 columns each.
**How to avoid:** DuckDB column projection reduces to ~27 columns. Process one month at a time. Set DuckDB memory_limit if needed.
**Warning signs:** MemoryError or system swap activation during SP processing.

## Code Examples

### SIH CSV Reading with DuckDB (Verified)
```python
# Source: Benchmarked on actual NAS data 2026-04-01
# SP Jan 2023: 210,225 rows, 4.5s full file read, 1.4s with LIMIT
import duckdb
import pandas as pd
from pathlib import Path

SIH_COLS = [
    "UF_ZI", "ANO_CMPT", "MES_CMPT", "N_AIH", "IDENT",
    "MUNIC_RES", "MUNIC_MOV", "NASC", "SEXO", "IDADE", "COD_IDADE",
    "DIAS_PERM", "DIAG_PRINC", "DIAG_SECUN",
    "PROC_SOLIC", "PROC_REA", "DT_INTER", "DT_SAIDA",
    "MORTE", "VAL_TOT", "VAL_UTI",
    "CNES", "COMPLEX", "FINANC", "CAR_INT", "ESPEC", "CGC_HOSP",
]

def read_etlsih_csv(csv_path: Path) -> pd.DataFrame:
    """Read ETLSIH CSV with DuckDB column projection."""
    col_list = ", ".join(SIH_COLS)
    con = duckdb.connect()
    df = con.execute(
        f"SELECT {col_list} FROM read_csv_auto('{csv_path}')"
    ).fetchdf()
    con.close()
    return df
```

### CNES ST Bellwether Facility Filter (Verified)
```python
# Source: Column names verified from actual ETLCNES.ST CSV header (2026-04-01)
# Bellwether: surgical center OR obstetric center OR >=10 inpatient beds
CNES_ST_COLS = [
    "CNES", "CODUFMUN", "COMPETEN",
    "CENTRCIR", "CENTROBS",
    "QTLEITP1", "QTLEITP2", "QTLEITP3",
    "VINC_SUS", "TP_UNID", "LEITHOSP",
]

def filter_bellwether_facilities(df: pd.DataFrame) -> pd.DataFrame:
    """Identify bellwether-capable facilities per Lancet Commission."""
    total_beds = (
        pd.to_numeric(df["QTLEITP1"], errors="coerce").fillna(0)
        + pd.to_numeric(df["QTLEITP2"], errors="coerce").fillna(0)
        + pd.to_numeric(df["QTLEITP3"], errors="coerce").fillna(0)
    )
    is_bellwether = (
        (pd.to_numeric(df["CENTRCIR"], errors="coerce") > 0)
        | (pd.to_numeric(df["CENTROBS"], errors="coerce") > 0)
        | (total_beds >= 10)
    )
    return df[is_bellwether].copy()
```

### CBO Codes for SAO Filtering (Corrected)
```python
# Source: ANS FHIR CodeSystem tuss-24 (verified 2026-04-01)
# NOTE: CBO-2002 uses 6-digit codes, NOT 4-digit family codes

# Surgeons (cirurgioes) -- CBO family 2252 surgical specialties
CBO_SURGEONS = {
    "225210",  # Medico cirurgiao cardiovascular
    "225215",  # Medico cirurgiao de cabeca e pescoco
    "225225",  # Medico cirurgiao geral
    "225230",  # Medico cirurgiao pediatrico
    "225235",  # Medico cirurgiao plastico
    "225240",  # Medico cirurgiao toracico
    "225203",  # Medico em cirurgia vascular
    "225260",  # Medico neurocirurgiao
    "225295",  # Medico cirurgiao da mao
}

# Anesthesiologists
CBO_ANESTHESIOLOGISTS = {
    "225151",  # Medico anestesiologista
}

# Obstetricians/Gynecologists
CBO_OBSTETRICIANS = {
    "225250",  # Medico ginecologista e obstetra
}

CBO_SAO = CBO_SURGEONS | CBO_ANESTHESIOLOGISTS | CBO_OBSTETRICIANS
```

### Test Fixture Generation
```python
# Pattern for creating offline test data
import pandas as pd
from pathlib import Path

def create_sih_fixture(output_dir: Path) -> Path:
    """Create a minimal SIH CSV fixture for offline testing."""
    output_dir.mkdir(parents=True, exist_ok=True)
    fixture_path = output_dir / "ETLSIH.ST_XX_2023_1_t.csv"
    # Minimal rows with all needed columns
    df = pd.DataFrame({
        "UF_ZI": [120000, 120000],
        "ANO_CMPT": [2023, 2023],
        "MES_CMPT": [1, 1],
        "N_AIH": [1215100060867, 1215100060868],
        "IDENT": [1, 1],
        "MUNIC_RES": [120042, 120020],
        "MUNIC_MOV": [120020, 120020],
        "DIAG_PRINC": ["O800", "K350"],
        "PROC_REA": [310010039, 407040030],
        "DT_INTER": [20230126, 20230215],
        "DT_SAIDA": [20230128, 20230218],
        "MORTE": [0, 0],
        "VAL_TOT": [585.80, 1250.00],
        # ... additional columns as needed
    })
    df.to_csv(fixture_path, index=False)
    return fixture_path
```

## Data Inventory

### SIH Data (ETLSIH)
| Property | Value |
|----------|-------|
| Location | `/Volumes/docker/Downloads/` (NAS mount) |
| File count | 5,643 files |
| Total size | 354 GB |
| File pattern | `ETLSIH.ST_{UF}_{YEAR}_{MONTH}_t.csv` |
| Columns per file | 235 (keep ~27 for processing) |
| Delimiter | Comma (standard CSV) |
| Encoding | UTF-8 (verified) |
| Year range available | 2008-2025 |
| Year range needed | 2015-2023 (9 years x 12 months x 27 UFs = 2,916 files) |
| Largest monthly file | SP: ~364 MB, ~210,000 rows |
| Smallest monthly file | AC: ~7 MB, ~4,000 rows |
| Key columns (DATASUS original) | UF_ZI, ANO_CMPT, MES_CMPT, N_AIH, MUNIC_MOV, MUNIC_RES, DIAG_PRINC, PROC_REA, DT_INTER, DT_SAIDA, MORTE, VAL_TOT, CNES, DIAS_PERM |
| Key columns (FIOCRUZ enriched) | res_MUNCOD, int_MUNCOD, def_diag_princ_cap, def_procedimento_realizado, dt_inter (ISO), dt_saida (ISO) |

### CNES ST Data (ETLCNES Establishments)
| Property | Value |
|----------|-------|
| Location | `/Volumes/docker/Downloads2/ETLCNES.zip` (NAS, zipped) |
| File count | 6,534 files in zip |
| Uncompressed size | ~60 GB |
| Zip size | 2.9 GB |
| File pattern | `ETLCNES.ST_{UF}__{YY}_{MM}_t.csv` (note: double underscore, 2-digit year) |
| Columns per file | ~220 |
| Year range | 2005-2025 (need 2015-2023) |
| Key columns for bellwether | CNES, CODUFMUN, CENTRCIR, CENTROBS, QTLEITP1/2/3, VINC_SUS, TP_UNID, COMPETEN |

### CNES PF Data (Professionals) -- NOT AVAILABLE
| Property | Value |
|----------|-------|
| Status | **NOT in ETLCNES.zip** -- only ST files present |
| Acquisition | Must download from DATASUS FTP via PySUS: `PF{UF}{YY}{MM}.dbc` |
| Key columns (expected) | CNES, CODUFMUN, CNS_PROF, CPF_PROF, CBO, NOMEPROF, VINCULAC, COMPETEN |
| SAO CBO codes | 225151 (anesthesiologist), 225210-225295 (surgeons), 225250 (obstetrician) |

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| DATASUS DBC files + PySUS blast-dbf | FIOCRUZ BigData pre-processed CSVs | Data already on NAS | No DBC conversion needed; 235 enriched columns available |
| pandas read_csv for large files | DuckDB read_csv_auto with column projection | DuckDB 1.5.1 (2025) | 3-10x faster for column-projected reads |
| CBO 4-digit family codes (2231, 2232, 2235) | CBO 6-digit occupation codes (225225, 225151, 225250) | CBO-2002 standard | Correct SAO filtering without capturing dentists/nurses |

**Deprecated/outdated:**
- `sih_batch_v2.py` DBC reading logic (_read_dbc, _read_dbc_blast, _ftp_download): Replaced by direct CSV reading
- `continue_raw_download.py` FTP download: Not needed; data already on NAS
- PySUS blast-dbf pre-flight check: Not needed for CSV data
- STATE.md blocker about "PySUS blast-dbf macOS compatibility": No longer relevant -- data is CSV

## Open Questions

1. **CNES PF Professional Data Acquisition**
   - What we know: ETLCNES.zip contains only ST (establishment) files. PF files are distributed separately by DATASUS as PF{UF}{YY}{MM}.dbc.
   - What's unclear: Should we download CNES PF via PySUS in this phase, or defer to a separate acquisition task? PySUS 1.0.1 is installed and can download from DATASUS FTP.
   - Recommendation: Include a CNES PF download step as a separate task in this phase. If DATASUS FTP is slow/unreliable, the task can be deferred without blocking SIH extraction and CNES ST facility extraction.

2. **ETLCNES Zip Extraction Strategy**
   - What we know: 2.9 GB zip with 6,534 files. We need 2,916 files (2015-2023).
   - What's unclear: Extract entire zip to local disk, or read from zip on-the-fly? DuckDB cannot read from zip directly.
   - Recommendation: Extract only needed files (2015-2023) to `data_sources/raw/cnes/` using selective unzip. ~30 GB uncompressed for the subset.

3. **SIH Column Selection for Future Phases**
   - What we know: LCoGS-3 needs PROC_REA; LCoGS-4 needs MORTE + DT_INTER + DT_SAIDA; LCoGS-5/6 needs VAL_TOT.
   - What's unclear: Whether FIOCRUZ enriched columns (def_diag_princ_cap, dt_inter ISO format) would save work downstream.
   - Recommendation: Keep only DATASUS original columns (27 selected) to minimize storage. FIOCRUZ enriched columns can be recomputed if needed.

4. **SIH Municipality: MUNIC_MOV vs MUNIC_RES**
   - What we know: Project decision says "municipality of treatment (not residence)." MUNIC_MOV = municipality of hospitalization. MUNIC_RES = municipality of patient residence.
   - What's unclear: Do we keep both columns or only MUNIC_MOV?
   - Recommendation: Keep BOTH in procedure-level Parquet (future analyses may need residence). Aggregate on MUNIC_MOV (treatment location) per project decision. Normalize both with normalize_cod_ibge().

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12 | Runtime | Yes | 3.12.11 | -- |
| duckdb | CSV reading | Yes (venv) | 1.5.1 | pandas read_csv (slower) |
| pandas | Data manipulation | Yes (venv) | 2.3.3 | -- |
| pyarrow | Parquet I/O | Yes (venv) | 23.0.1 | -- |
| pysus | CNES PF download | Yes (venv) | 1.0.1 | Manual FTP download |
| pytest | Testing | Yes (venv) | 9.0.2 | -- |
| NAS mount | SIH raw data | Yes | /Volumes/docker | Copy sample files locally |
| ETLCNES.zip | CNES facilities | Yes | /Volumes/docker/Downloads2/ | -- |
| CNES PF files | CNES professionals | **No** | Not downloaded | PySUS download from DATASUS FTP |

**Missing dependencies with no fallback:**
- None that block SIH extraction or CNES ST extraction

**Missing dependencies with fallback:**
- CNES PF professional files: Not available locally; download via PySUS from DATASUS FTP (pysus 1.0.1 installed)

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 |
| Config file | None (default discovery via pyproject.toml) |
| Quick run command | `cd "/Users/matheusrech/untitled folder 6/ICSKG" && .venv/bin/python -m pytest tests/ -x -q` |
| Full suite command | `cd "/Users/matheusrech/untitled folder 6/ICSKG" && .venv/bin/python -m pytest tests/ -v` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DATA-01a | SIH CSV reading with correct column subset | unit | `.venv/bin/python -m pytest tests/test_sih_extract.py::test_read_csv_columns -x` | No -- Wave 0 |
| DATA-01b | normalize_cod_ibge on MUNIC_MOV (6-digit int -> 7-digit str) | unit | `.venv/bin/python -m pytest tests/test_utils.py::TestNormalizeCodIbge::test_6digit_int_zero_padded -x` | Yes |
| DATA-01c | SIH Parquet output has expected schema | unit | `.venv/bin/python -m pytest tests/test_sih_extract.py::test_parquet_schema -x` | No -- Wave 0 |
| DATA-01d | SIH municipality-year aggregation produces correct counts | unit | `.venv/bin/python -m pytest tests/test_sih_extract.py::test_aggregation -x` | No -- Wave 0 |
| DATA-01e | validate_dataframe passes on SIH output | integration | `.venv/bin/python -m pytest tests/test_sih_extract.py::test_validation_gate -x` | No -- Wave 0 |
| DATA-02a | CNES ST facility bellwether filter (CENTRCIR/CENTROBS/beds) | unit | `.venv/bin/python -m pytest tests/test_cnes_extract.py::test_bellwether_filter -x` | No -- Wave 0 |
| DATA-02b | CNES ST correct columns extracted | unit | `.venv/bin/python -m pytest tests/test_cnes_extract.py::test_st_columns -x` | No -- Wave 0 |
| DATA-02c | CBO code sets are correct 6-digit codes | unit | `.venv/bin/python -m pytest tests/test_cnes_extract.py::test_cbo_codes -x` | No -- Wave 0 |

### Sampling Rate
- **Per task commit:** `.venv/bin/python -m pytest tests/ -x -q`
- **Per wave merge:** `.venv/bin/python -m pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_sih_extract.py` -- covers DATA-01a/c/d/e
- [ ] `tests/test_cnes_extract.py` -- covers DATA-02a/b/c
- [ ] `tests/fixtures/ETLSIH.ST_XX_2023_1_t.csv` -- small SIH CSV fixture (5-10 rows, correct header)
- [ ] `tests/fixtures/ETLCNES.ST_XX__23_01_t.csv` -- small CNES ST CSV fixture (5-10 rows, correct header)

## Project Constraints (from CLAUDE.md)

- **Python environment:** Use project venv at `.venv/` (Python 3.12.11); never `sudo pip`
- **Tech stack:** pandas, DuckDB, pyarrow for data processing
- **Reproducibility:** Pipeline must be fully idempotent; all outputs deterministic given same inputs
- **Privacy:** No individual-level identifiers; municipality-level aggregates only
- **Logging:** Use %-style formatting, never f-strings; logger.info for milestones, logger.warning for degradation
- **Naming:** Snake case, verb-first functions, private underscore prefix, uppercase module-level constants
- **Error handling:** Broad except with `# noqa: BLE001`, log and continue, preserve context with `from exc`
- **Paths:** Always use `pathlib.Path`; `path.mkdir(parents=True, exist_ok=True)`
- **GSD workflow:** Use GSD commands for execution; do not make direct repo edits outside workflow

## Sources

### Primary (HIGH confidence)
- Actual NAS data inspection: `/Volumes/docker/Downloads/` -- verified file counts, sizes, column headers (2026-04-01)
- ETLSIH CSV header: 235 columns extracted from `ETLSIH.ST_AC_2015_1_t.csv` (verified all SIH_COLS_KEEP present)
- ETLCNES CSV header: ~220 columns from `ETLCNES.ST_AC__15_01_t.csv` extracted from zip (verified CENTRCIR, CENTROBS, QTLEITP columns)
- DuckDB benchmark: SP Jan 2023 -- 210,225 rows read in 4.5s full, 1.4s with LIMIT (verified in project venv)
- [ANS FHIR CodeSystem tuss-24](https://fhir-hm.ans.gov.br/CodeSystem-tuss-24.html) -- CBO 6-digit codes for SAO (verified: 225225, 225151, 225250)

### Secondary (MEDIUM confidence)
- [FIOCRUZ PCDaS SIH documentation](https://pcdas.icict.fiocruz.br/conjunto-de-dados/sistema-de-informacoes-hospitalares-do-sus-sihsus/documentacao/) -- ETL process description
- [FIOCRUZ BigData ETL GitHub dict_SIH.csv](https://raw.githubusercontent.com/bigdata-icict/ETL-Dataiku-DSS/master/SIH/dict_SIH.csv) -- SIH data dictionary (190 cols documented; actual files have 235)
- [microdatasus process_cnes.R](https://github.com/rfsaldanha/microdatasus) -- CNES PF column names (CNES, CODUFMUN, CBO, CNS_PROF, VINCULAC, NOMEPROF)
- [DuckDB CSV import guide](https://www.getorchestra.io/guides/how-does-duckdb-handle-csv-imports) -- read_csv_auto best practices

### Tertiary (LOW confidence)
- CNES PF file exact column names from DATASUS FTP: Not directly verified; based on microdatasus R package source code and DATASUS documentation links. Column names should be confirmed when PF files are downloaded.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries verified in project venv, benchmarked on actual data
- Architecture: HIGH -- based on actual NAS file inspection, existing codebase patterns, verified column names
- Pitfalls: HIGH -- discovered by direct data inspection (CBO codes, CNES PF absence, file naming patterns)
- CNES PF professional schema: LOW -- not verified against actual data files (not yet downloaded)

**Research date:** 2026-04-01
**Valid until:** 2026-05-01 (stable -- FIOCRUZ CSV format is static; data already downloaded)
