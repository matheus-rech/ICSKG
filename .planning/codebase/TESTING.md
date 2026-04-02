# Testing Patterns

**Analysis Date:** 2026-04-01

## Test Framework

**Status:** No automated test framework detected

**Codebase Analysis:**
- No test files found (no `test_*.py`, `*_test.py`, or `tests/` directory)
- No pytest, unittest, or nose configuration files
- No `conftest.py`, `pytest.ini`, `setup.cfg`, or `tox.ini`

**Testing Approach:** Manual/integration testing via CLI scripts

This is a data processing and ETL pipeline project where testing occurs through:
- Dry runs with sample/synthetic data
- Command-line invocation of main scripts
- Output validation (generated CSVs, database records, visualization files)

## Test Data & Validation

**Synthetic Data Generation:**
Present in main execution paths as fallback when real data unavailable:

- `extract_lcogs1.py` (lines 316–328): Creates synthetic 100-municipality panel when SIH/population data missing
- `icskg_analysis_pipeline.py`: Generates synthetic 5-municipality panel for demonstrating pipeline structure

**Pattern:**
```python
if sih_df.empty and pop_df.empty:
    logger.warning("No data available. Generating synthetic example output.")
    rng = np.random.default_rng(42)
    n = 100
    sih_df = pd.DataFrame({
        "MUNIC_MOV": [f"{i + 1:06d}" for i in range(n)],
        "DIAG_PRINC": rng.choice(list(BELLWETHER_DIAG) + ["Z000", "J180"], size=n),
        "N_AIH": [f"AIH{i:08d}" for i in range(n)],
        "MORTE": rng.integers(0, 2, size=n),
    })
```

**Deterministic Seeding:** Uses `rng = np.random.default_rng(42)` for reproducibility

**Data Validation:**
- Optional parameters enable idempotent operations: `skip_existing: bool = True`
- Partition existence checks: `if partition_path.exists(): return result`
- Deduplication checks: `if before != after: logger.debug("Deduplicated...")`
- File size validation: `local_path.stat().st_size` confirms successful downloads

## Error Recovery & Resilience

**Retry Logic Pattern:**
Used for network operations (FTP, HTTP downloads):

`scripts/download_ans.py` (lines 64–83):
```python
def _get_with_retry(url: str, timeout: int = 120) -> bytes:
    """Fetch *url* with retry logic. Returns raw bytes."""
    session = requests.Session()
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, timeout=timeout, headers=headers, stream=True)
            resp.raise_for_status()
            return resp.content
        except Exception as exc:  # noqa: BLE001
            logger.warning("Attempt %d/%d failed for %s: %s", attempt, MAX_RETRIES, url, exc)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)  # exponential backoff
    raise RuntimeError(f"Failed to download {url} after {MAX_RETRIES} attempts")
```

**Retry Constants:**
- `MAX_RETRIES = 4` to `5` (depends on module)
- `RETRY_DELAY = 5` to `10` seconds with exponential backoff: `time.sleep(RETRY_DELAY * attempt)`

**Resume Logic:**
`scripts/continue_raw_download.py` (lines 103–119): FTP downloads support resumption

```python
offset = local_path.stat().st_size if (resume and local_path.exists()) else 0
# ... later in FTP transfer
if offset:
    ftp.sendcmd(f"REST {offset}")  # resume from byte offset
```

## Integration Testing Patterns

**File I/O Validation:**
- Parquet files validated after write: reading back to confirm structure
- CSV output includes explicit column selection: `available_gap_cols = [c for c in gap_cols if c in rates_df.columns]`
- Database operations wrapped in try-except with logging

**Graceful Degradation:**
Multiple fallback mechanisms when dependencies unavailable:

`extract_lcogs1.py` (lines 219–227): Map generation optional
```python
try:
    import geopandas as gpd
    import matplotlib
    # ... map generation code
except ImportError as exc:
    logger.warning("geopandas/matplotlib not available – skipping maps: %s", exc)
    return
```

`scripts/sih_batch_v2.py` (lines 181–219): DBC reading with blast-dbf fallback
```python
def _read_dbc(dbc_path: Path, cols_keep: list[str]):
    try:
        from pysus.tools import rdbc  # noqa: PLC0415
        # ... pysus conversion
    except ImportError:
        logger.warning("pysus not available – attempting blast-dbf fallback...")
        return _read_dbc_blast(dbc_path, cols_keep)

def _read_dbc_blast(dbc_path: Path, cols_keep: list[str]):
    # ... subprocess call to blast-dbf binary
```

**Output Validation:**
- `build_database_v2.py`: Validates required columns before database insert (`required = ["cod_ibge", "year"]`)
- Pipeline operations check for empty DataFrames: `if df.empty: return pd.DataFrame()`
- FTP operations validate file existence before processing

## Testing Entry Points

**Manual Testing via CLI:**

1. **Synthetic data pipeline test:**
   ```bash
   python extract_lcogs1.py --year 2023  # Runs with synthetic data if files missing
   python analysis/icskg_analysis_pipeline.py  # Generates 5-municipality synthetic panel
   ```

2. **Download operations (with logging):**
   ```bash
   python scripts/download_ans.py --year 2023 --month 12
   python scripts/sih_batch_v2.py --year 2023 --month 12
   python scripts/continue_raw_download.py --end-year 2023 --end-month 12 --months 1
   ```

3. **ETL pipeline with specific stages:**
   ```bash
   python database/pipeline.py --year-month 2023-12 --stages extract_sih extract_cnes
   python database/build_database_v2.py --years 2023 2023
   ```

**Verification Points:**
- Logger output confirms progress through stages
- Output files written to expected locations (`output/`, `database/`, `data_sources/processed/`)
- Parquet files readable via `pandas.read_parquet()`
- Database tables created and populated via SQLite validation

## Coverage & Known Gaps

**Not Tested:**
- Concurrent operations beyond multi-process UF-level SIH processing
- Network timeout edge cases (only retry limits tested)
- Corrupted parquet/DBC file recovery
- Memory pressure with full 5570-municipality datasets
- Multi-worker FTP connection race conditions

**Partially Tested:**
- Partial downloads with resume (logic present, assumed working)
- Geographic shapefile loading (optional, fallback to skip)
- DuckDB mirroring (best-effort, errors logged)

## Code Quality Practices

**Logging as Test Output:**
All functions emit progress logs that serve as operational test records:
- `logger.info("Loaded %d SIH records for %d", len(combined), year)`
- `logger.info("Merged %d municipalities → %s", len(merged), output)`
- `logger.info("✓ %s: %d rows → %s", uf, len(df), partition_path)`

**Idempotency:**
Pipeline operations designed to be re-runnable:
- `skip_existing: bool = True` parameter skips already-processed partitions
- SQL `INSERT OR REPLACE` for database operations
- File checksums/sizes logged for integrity checks

**Data Assertions:**
Implicit assertions through data operations:
- Type conversions with error handling: `pd.to_numeric(..., errors="coerce")`
- Column existence checks before operations: `if col not in df.columns:`
- Non-empty DataFrame validation: `if df.empty: logger.warning(...)`

---

*Testing analysis: 2026-04-01*

**Note:** This codebase prioritizes data pipeline robustness through logging, retry logic, and graceful degradation rather than unit test coverage. For production use, consider adding pytest suite covering:
- Individual transformation functions with small fixture DataFrames
- Error handling paths (network failures, missing files)
- Output format validation (parquet schema, CSV structure)
- Database schema integrity after load
