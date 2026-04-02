# Coding Conventions

**Analysis Date:** 2026-04-01

## Naming Patterns

**Files:**
- Snake case with descriptive names: `extract_lcogs1.py`, `sih_batch_v2.py`, `icskg_analysis_pipeline.py`
- Suffix versioning for iterations: `v2`, `v3` (e.g., `build_database_v2.py`, `sih_batch_v2.py`)
- Clear module purpose in name (e.g., `continue_raw_download.py`, `download_ans.py`)

**Functions:**
- Snake case throughout
- Private functions prefixed with underscore: `_process_uf()`, `_ftp_download()`, `_zscore()`, `_minmax()`, `_connect_ftp()`, `_dbc_to_parquet()`
- Verb-first naming convention for function actions: `load_sih_year()`, `fetch_ibge_population()`, `flag_bellwether()`, `compute_rates()`, `generate_maps()`, `download_competence()`, `parse_csv()`, `merge_downloads()`
- Clear, explicit names: `collect_parquet_files()`, `upsert_municipal_health()`, `export_metadata_json()`

**Variables:**
- Snake case for all variables: `processed_dir`, `raw_dir`, `output_dir`, `max_retries`, `skip_existing`
- Domain-specific abbreviations acceptable: `sih_df`, `pop_df`, `ans_df`, `gdf` (geodataframe), `con` (connection)
- All-caps for module-level constants: `LAPAROTOMY_DIAG`, `CAESAREAN_DIAG`, `MAX_RETRIES`, `DATASUS_FTP_HOST`, `UF_CODES`, `CIMI_DIMENSIONS`
- Temporary iteration variables: `f` (file), `uf` (state), `year`, `month`, `attempt`, `label`

**Types:**
- Standard type hints on function signatures: `year: int`, `path: Path`, `data: pd.DataFrame`
- Complex return types: `-> pd.DataFrame`, `-> list[str]`, `-> dict[str, Path | None]`
- Optional parameters with defaults: `timeout: int = 120`, `workers: int = 1`, `skip_existing: bool = True`

## Code Style

**Formatting:**
- PEP 8 compliant
- Line width follows standard Python conventions (~88 characters in practice)
- 4-space indentation throughout

**Linting:**
- Uses `# noqa: BLE001` to suppress bare exception linting warnings (standard across codebase for defensive exception handling)
- Uses `# noqa: PLC0415` to allow local imports inside functions for optional dependencies
- Pragmatic approach: linting suppressions used where domain logic requires broader exception handling

**Spacing & Structure:**
- Blank lines separate logical sections within functions
- Section banners using dashes for readability: `# ---------------------------------------------------------------------------` (65 dashes)
- Double newlines between top-level definitions

## Import Organization

**Order:**
1. Standard library imports (alphabetical): `argparse`, `io`, `json`, `logging`, `os`, `sys`, `time`
2. Standard library advanced imports: `from datetime import date`, `from pathlib import Path`, `from functools import partial`, `from urllib.parse import urljoin`
3. Third-party imports: `import numpy as np`, `import pandas as pd`, `import duckdb`
4. Late/optional imports inside functions marked with `# noqa: PLC0415`

**Path Aliases:**
- All code uses absolute paths via `pathlib.Path`
- No path aliases; imports use direct module paths
- Dynamic imports for optional dependencies: `from scripts.sih_batch_v2 import process_month` (inside functions to defer dependency checks)

## Error Handling

**Patterns:**
- Broad exception handling: `except Exception as exc:  # noqa: BLE001` used for defensive error catching
- Specific exception handling where semantically important:
  - `except ImportError as exc:` for missing optional dependencies
  - `except FileNotFoundError:` for missing data files
  - `except RuntimeError:` for operational failures
  - `except ftplib.Error:` for FTP-specific errors
- Error handling includes logging: `logger.error("message: %s", exc)` or `logger.warning("message: %s", exc)`
- Graceful degradation: operations often log and continue rather than failing hard (synthetic data generation fallback in `extract_lcogs1.py`)
- Custom error messages on re-raise: `raise RuntimeError("Failed to download ... after N attempts") from exc`

**Exception Chain:**
- Uses `from exc` to preserve exception context for debugging
- Explicit error messages that include attempt counts, URLs, or file paths

## Logging

**Framework:** Python `logging` module via `getLogger(__name__)`

**Initialization Pattern (consistent across all files):**
```python
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
```

**Log Levels:**
- `logger.info()`: Major milestones, successful operations, data counts
  - `logger.info("Loaded %d SIH records for %d", len(combined), year)`
  - `logger.info("Extracted SIH %04d-%02d → %s", year, month, output)`
- `logger.warning()`: Graceful degradation, missing optional dependencies, skipped operations
  - `logger.warning("No SIH parquet files found for year %d in %s", year, processed_dir)`
  - `logger.warning("requests not installed – using synthetic population data.")`
- `logger.error()`: Recoverable failures, retried operations, detailed exception context
  - `logger.error("Could not read %s: %s", f, exc)`
  - `logger.error("extract_sih failed: %s", exc)`
- `logger.debug()`: Partition skips, deduplication counts (only when `skip_existing=True` or `before != after`)

**Patterns:**
- Always use %-style formatting, never f-strings
- Include context: file paths, counts, years/months, exception details
- Status indicators in info messages: checkmarks (`✓`) and progress indicators (`▶`)
- Banner messages for major pipeline stages: `logger.info("=== Stage Name ===")` or `logger.info("─" * 60)`

## Comments

**When to Comment:**
- Section separators (major logical divisions): `# ---------------------` style banners
- Domain-specific code or complex logic explanations
- Configuration constants with units: `RETRY_DELAY = 10  # seconds`
- ICD code mappings and medical terminology explanations
- Comments are minimal—code clarity is preferred over verbosity

**DocStrings:**
- Module-level docstrings: extensive, include purpose, outputs, data requirements, and usage examples
- Function docstrings: Present on all public functions, some private functions
- Format: Triple-quoted strings with section headers (Outputs, Data requirements, Usage, Parameters, Returns)
- Example from `extract_lcogs1.py`:
  ```python
  """Load and concatenate all SIH months for *year*."""
  ```
- Longer docstrings use structured format:
  ```python
  """Download *remote_path* from *ftp* to *local_path*.

  Supports byte-range resume if *resume* is True and the local file exists.
  Returns True on success.
  """
  ```

## Function Design

**Size:**
- Functions range from 5–50 lines
- Complex orchestration functions (main ETL pipelines) may reach 60–100 lines
- Single responsibility: each function does one logical task

**Parameters:**
- Maximum 8–10 parameters common for data processing functions
- Use default parameters for optional behaviors: `skip_existing: bool = True`, `workers: int = 1`
- Path objects (`Path`) preferred over strings for file operations
- Keyword-only arguments for optional parameters in longer signatures

**Return Values:**
- Explicit return types in annotations
- DataFrame returns for data transformations
- Path returns for file operations indicating output location
- `None` returns for side-effect operations (writing to disk)
- Tuple returns for operations with multiple outputs: `-> tuple[int, int]` (e.g., year, month pairs)
- Integer counts for data loading operations (number of rows/files processed)

## Module Design

**Exports:**
- No explicit `__all__` definitions
- Modules are executable scripts with `if __name__ == "__main__": sys.exit(main())`
- Clear public API: `main(argv=None)` as entry point with argument parsing
- Private function prefix (`_`) used consistently

**Barrel Files:**
- Not used in this codebase
- Each module is self-contained with internal utility functions

**File Structure Pattern:**
1. Module docstring with purpose, outputs, data requirements, usage
2. Imports (standard library → third-party → local)
3. Logger setup and constants
4. Core functions (often preceded by comment banners)
5. Helper/internal functions (prefixed with `_`)
6. Main orchestration or pipeline functions
7. CLI entry point (`main(argv=None)`) with argparse
8. `if __name__ == "__main__": sys.exit(main())`

## Special Conventions

**Path Handling:**
- All paths use `pathlib.Path` with `Path(string)` construction
- Directory creation pattern: `path.mkdir(parents=True, exist_ok=True)`
- Safe file checks: `path.exists()`, `path.stat().st_size`

**Data Type Conversions:**
- Use `pd.to_numeric(..., errors="coerce")` for safe numeric conversion
- Type casting in pandas operations: `astype(str)`, `astype(int)`, `astype(float)`
- String normalization: `.str.strip()`, `.str.upper()`, `.str[:N]` for prefixes

**Configuration & Environment:**
- Constants defined at module level (uppercase)
- FTP credentials and file patterns stored as module-level strings and lists
- DuckDB/SQLite connection patterns encapsulated in functions returning connection objects

---

*Convention analysis: 2026-04-01*
