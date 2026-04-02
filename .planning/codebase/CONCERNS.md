# Codebase Concerns

**Analysis Date:** 2026-04-01

## Tech Debt

**Broad Exception Handling (BLE001 suppressions):**
- Issue: Multiple `except Exception` blocks throughout codebase silently catch all exceptions without discrimination
- Files: `extract_lcogs1.py` (lines 93, 131, 238), `database/pipeline.py` (lines 150, 195, 229, 235, 241, 247, 262, 269), `scripts/download_ans.py` (lines 79, 187, 228), `scripts/sih_batch_v2.py` (lines 174, 192, 244), `scripts/continue_raw_download.py` (lines 120, 144, 196, 216, 230)
- Impact: Silent failures in data downloads, transformations, and conversions make debugging difficult. Failed API calls, missing files, or corrupted data may be hidden behind generic logging
- Fix approach: Replace broad exception handlers with specific exception types (ImportError, FileNotFoundError, requests.RequestException, ftplib.Error). Add explicit logging with exception context and stack traces rather than generic warning messages

**Bare pass statements in exception handlers:**
- Issue: Empty pass statements suppress errors without logging or recovery
- Files: `scripts/continue_raw_download.py` (lines 120-121, 216-217)
- Impact: FTP reconnection failures and quit() failures are silently ignored, potentially leaving stale connections
- Fix approach: Add meaningful log messages before pass; consider re-raising for critical errors or implementing proper cleanup in finally blocks

**Dynamic imports scattered throughout:**
- Issue: Optional imports (requests, pandas, geopandas, pysus, duckdb) are imported inside functions with PLC0415 suppressions
- Files: `extract_lcogs1.py`, `database/pipeline.py`, `scripts/download_ans.py`, `scripts/sih_batch_v2.py`, `scripts/continue_raw_download.py`
- Impact: Import errors only discovered at runtime when specific code paths execute. Makes dependency requirements unclear
- Fix approach: Move imports to module level with clear error messages. Create a requirements.txt that specifies which packages are required vs. optional. Add pre-flight checks in main() functions

## Known Bugs

**Duplicate gap analysis output:**
- Issue: Lines 340-347 in `extract_lcogs1.py` write gap analysis twice
- Symptom: The code checks if 'lcogs1_gap' column exists, writes the output, then unconditionally writes the same output again without the conditional check
- Files: `extract_lcogs1.py` (lines 340-347)
- Trigger: Run `python extract_lcogs1.py` with valid data containing lcogs1_gap column
- Workaround: Second write overwrites first, so output is correct, but this is wasteful and indicates copy-paste error
- Fix: Remove lines 345-347 (the second unconditional write)

**Undefined variable reference in gap analysis:**
- Issue: Line 346 references `gap_df` which may not be defined if 'lcogs1_gap' column is missing
- Files: `extract_lcogs1.py` (line 346)
- Trigger: When `lcogs1_gap` not in rates_df.columns, the if-block (340-344) is skipped but line 346 still executes, raising NameError
- Impact: Script crashes with NameError when processing data without gap calculations
- Fix: Either ensure gap_df is always defined or move lines 345-347 inside the if-block

**Unused variable assignment:**
- Issue: In `extract_lcogs1.py` line 265, `meets_lcogs1_num` is created but derived from the already-numeric `meets_lcogs1` boolean column
- Files: `extract_lcogs1.py` (line 265)
- Impact: Unnecessary computation and code clarity issue
- Fix: Use `meets_lcogs1` column directly instead of converting to float

## Security Considerations

**Hardcoded API endpoints and credentials:**
- Risk: User-Agent header contains placeholder contact email `icskg-br@example.org`
- Files: `scripts/download_ans.py` (line 72)
- Current mitigation: None
- Recommendations: Use environment variable for contact email. Consider using actual project contact address

**No HTTPS enforcement on FTP connections:**
- Risk: DATASUS FTP data is transmitted in plaintext
- Files: `scripts/continue_raw_download.py` (lines 45-49, 74-79)
- Current mitigation: None
- Recommendations: Document that FTP data is publicly available and not sensitive. Consider SFTP if DATASUS supports it

**File path injection vulnerability:**
- Risk: User-supplied --raw-dir, --output-dir, --processed-dir arguments are not validated for path traversal
- Files: `database/pipeline.py`, `scripts/continue_raw_download.py`, `database/build_database_v2.py`, `scripts/download_ans.py`, `scripts/sih_batch_v2.py`
- Current mitigation: Path objects used, which provides some protection
- Recommendations: Add explicit validation that resolved paths are within expected parent directories using Path.resolve().is_relative_to()

**No input validation on municipality codes:**
- Risk: Municipality code (cod_ibge) values assumed to be valid 6-digit IBGE codes; no format validation
- Files: `extract_lcogs1.py` (line 180), `database/build_database_v2.py` (line 188)
- Current mitigation: None
- Recommendations: Add regex validation on cod_ibge to ensure format matches expected pattern

## Performance Bottlenecks

**Memory-intensive concatenation in loop:**
- Problem: `extract_lcogs1.py` loads multiple parquet files and concatenates with pd.concat in loop
- Files: `extract_lcogs1.py` (lines 88-101)
- Cause: Each iteration reads full file and creates new concatenated dataframe; inefficient for 12+ months of data
- Improvement path: Use pd.concat once with list of loaded frames outside loop, or use parquet directory reading with pyarrow.parquet.read_table()

**No chunked processing in database upsert:**
- Problem: `build_database_v2.py` loads entire parquet file into memory before upserting to SQLite
- Files: `database/build_database_v2.py` (lines 147-158, 186-192)
- Cause: Full dataset loaded into rows list before executemany(), creating peak memory usage equal to entire dataset
- Improvement path: Implement chunked reading using parquet row_groups parameter; batch inserts in chunks of 10k-50k rows

**Synchronous retry loop without exponential backoff:**
- Problem: `scripts/download_ans.py` uses linear backoff `RETRY_DELAY * attempt` instead of exponential
- Files: `scripts/download_ans.py` (lines 74-83)
- Cause: With MAX_RETRIES=4 and RETRY_DELAY=5, total wait is 5+10+15+20=50 seconds; exponential would use 5+10+20+40=75 seconds (better for transient errors)
- Improvement path: Use `RETRY_DELAY * (2 ** (attempt - 1))` for exponential backoff

**FTP file listing not cached:**
- Problem: `scripts/continue_raw_download.py` lists FTP directory on every run but available files don't change within a run
- Files: `scripts/continue_raw_download.py` (lines 193-195)
- Cause: Single listing is cached in `available` set but loop processes sequentially without parallelism
- Improvement path: Consider parallel downloads across UFs after single listing call (already has multiprocessing import in sih_batch_v2.py)

## Fragile Areas

**ANS download depends on quarterly month convention:**
- Files: `scripts/download_ans.py` (lines 50, 290, 295, 301)
- Why fragile: QUARTERLY_MONTHS = [3, 6, 9, 12] is hardcoded assumption. If ANS changes release schedule or gaps occur, script silently returns no data
- Safe modification: Add explicit logging when expected files not found; add --all-months fallback option; verify response from API rather than assuming format
- Test coverage: No tests for failure cases (missing months, malformed CSV structure, changed column names)

**IFGF source file required but not auto-downloaded:**
- Files: `database/pipeline.py` (lines 100-107)
- Why fragile: Manual download required from `https://www.firjan.com.br/ifgf/` with exact filename. If naming changes or file moves, entire pipeline fails
- Safe modification: Consider adding auto-download logic with URL parameter, or provide API endpoint if available
- Test coverage: No validation that IFGF columns are present or values in expected range

**ICD-10 diagnosis code matching uses string prefix only:**
- Files: `extract_lcogs1.py` (lines 54-72, 147)
- Why fragile: LAPAROTOMY_DIAG, CAESAREAN_DIAG, OPEN_FRACTURE_DIAG are 3-character string sets matched case-insensitively against ICD-10 principals. If data has unexpected formatting (spaces, lowercase, full codes), matching fails silently
- Safe modification: Add explicit validation of DIAG_PRINC format; log unmatchable codes; add test cases for known edge cases (e.g., "K35.0" vs "K35")
- Test coverage: No unit tests for diagnosis matching logic

**DBC → Parquet conversion is optional but silently skipped:**
- Files: `scripts/continue_raw_download.py` (lines 131-146), `scripts/sih_batch_v2.py` (lines 199-244)
- Why fragile: If pysus not installed, returns False but calling code may not check return value. Downstream pipeline assumes Parquet files exist
- Safe modification: Make pysus required dependency or provide alternative conversion mechanism (blast-dbf fallback)
- Test coverage: No tests for pysus unavailable scenario

**Municipality code standardization fragile:**
- Files: `scripts/download_ans.py` (lines 147-156)
- Why fragile: Tries multiple column name variations (CD_MUNICIPIO, Municipio, IBGE_MUNICIPIO, CD_MUN). If none match, silently continues without normalizing
- Safe modification: Raise explicit error if expected columns not found; add data quality check logging; test against sample files from different years
- Test coverage: No tests for different ANS CSV layouts

## Scaling Limits

**SQLite database for full 2013–2024 municipality panel:**
- Current capacity: SQLite can handle 5570 municipalities × 12 years × 12 months = ~800k rows efficiently
- Limit: Performance degrades significantly above 10M rows; no indexing strategy defined
- Scaling path: Add UNIQUE INDEX on (cod_ibge, year, month); consider DuckDB for analytical queries (already implemented as mirror); implement partitioning by year if needed

**No pagination/limits on IBGE API fetch:**
- Current capacity: API returns all 5570 municipalities in single response
- Limit: Response parsing assumes all data fits in memory; no streaming support
- Scaling path: If IBGE adds filtering parameters, implement pagination; test with future datasets

**FTP download lacks parallelism:**
- Current capacity: Sequential download of 27 UF files × 12 months = 324 files takes hours
- Limit: Single FTP connection blocks; no concurrent downloads
- Scaling path: `scripts/sih_batch_v2.py` uses multiprocessing but `continue_raw_download.py` doesn't. Implement parallel FTP downloads per source with connection pooling

## Dependencies at Risk

**pysus library (optional but critical for DBC conversion):**
- Risk: Package is unmaintained or depends on deprecated blast libraries
- Impact: If pysus breaks, DBC files cannot be converted. Pipeline silently produces no output
- Migration plan: Implement fallback to subprocess call to blast-dbf (already done in sih_batch_v2.py line 199). Or use alternative: `pydbf` package for reading DBF directly

**requests library network assumptions:**
- Risk: Assumes stable network and responsive servers (DATASUS, ANS, IBGE APIs)
- Impact: Network timeouts (30-120 seconds) can block entire pipeline
- Migration plan: Implement circuit breaker pattern for API endpoints; add configuration for timeout values; document expected SLA

**pandas Parquet engine (pyarrow dependency):**
- Risk: Default engine may change between versions
- Impact: Data format incompatibilities, performance regressions
- Migration plan: Explicitly specify engine='pyarrow' in all parquet I/O; document minimum versions

## Missing Critical Features

**No data quality validation post-ETL:**
- Problem: Pipeline produces `merged_YYYYMM.parquet` files but doesn't validate contents
- Blocks: Impossible to detect corrupt or incomplete data early. Analysis pipeline may produce invalid results from bad data
- Recommendations: Add validation stage in `database/pipeline.py` after `transform_merge()` that checks: row counts per municipality per month, null value distributions, ICD-10 code format, IBGE code validity, data types

**No resume/idempotency tracking:**
- Problem: `--resume` flag checks file existence but not completeness or integrity
- Blocks: Partial downloads with wrong row counts are treated as complete
- Recommendations: Store manifest file with row counts, row hashes, or timestamps per downloaded file; verify before skipping

**No version tracking in outputs:**
- Problem: CSV/Parquet outputs don't include metadata about pipeline version, input data versions, or transformation logic
- Blocks: Reproduction and auditing of published results becomes difficult
- Recommendations: Add metadata block to each output file (as Parquet schema comment or separate _metadata.json) with: code version, input file hashes, timestamp, parameter values

**No dry-run mode:**
- Problem: All scripts execute immediately without preview of what will happen
- Blocks: Difficult to verify parameters before committing large downloads
- Recommendations: Add --dry-run flag to database/pipeline.py and download scripts that logs planned operations without executing

## Test Coverage Gaps

**No unit tests for ETL transformations:**
- What's not tested: Data merging logic in `database/pipeline.py` transform_merge(); dimension calculation in `analysis/icskg_analysis_pipeline.py`
- Files: `database/pipeline.py` (lines 114-160), `analysis/icskg_analysis_pipeline.py` (entire file)
- Risk: Regressions in merge logic, normalization, or aggregation undetected until analysis results change
- Priority: High – core business logic with no automated verification

**No integration tests for full pipeline:**
- What's not tested: End-to-end execution from raw downloads through analysis outputs
- Files: Missing `tests/` directory entirely
- Risk: Changes to individual scripts may break downstream stages; platform-specific issues (Windows vs. macOS) not caught
- Priority: High – catches system-level integration failures

**No tests for diagnosis code matching:**
- What's not tested: ICD-10 code matching in `extract_lcogs1.py` flag_bellwether() function
- Files: `extract_lcogs1.py` (lines 140-165)
- Risk: Silent data quality issues; unmatched codes go unreported
- Priority: Medium – affects output correctness for LCoGS-1 analysis

**No tests for CSV parsing variations:**
- What's not tested: ANS and other CSV parsing with different column names, encodings, or formats
- Files: `scripts/download_ans.py` parse_csv() (lines 136-161)
- Risk: Pipeline breaks on real data with unexpected structure
- Priority: Medium – affects data source reliability

**No tests for network errors:**
- What's not tested: Retry logic, timeout handling, FTP connection failures
- Files: `scripts/download_ans.py` _get_with_retry(), `scripts/continue_raw_download.py` _download_file()
- Risk: Untested error paths may cause script hangs or corrupt partial downloads
- Priority: Medium – affects reliability in production

**No tests for missing optional dependencies:**
- What's not tested: Behavior when requests, pysus, geopandas not installed
- Files: `extract_lcogs1.py`, `scripts/download_ans.py`, `scripts/continue_raw_download.py`
- Risk: Scripts fail in unexpected ways when dependencies missing
- Priority: Low – documented requirements but graceful degradation untested

---

*Concerns audit: 2026-04-01*
