---
phase: 01-foundation
verified: 2026-04-01T20:55:00Z
status: passed
score: 5/5 must-haves verified
re_verification:
  previous_status: gaps_found
  previous_score: 1/5
  gaps_closed:
    - "IBGE reference and crosswalk reconciled to 5571 municipalities"
    - "validate_dataframe() wired into pipeline.py run_pipeline() via _validate_stage_output()"
    - "normalize_cod_ibge/rename_municipality_column wired into transform_merge()"
    - "load_config() called in main()"
  gaps_remaining: []
  regressions: []
---

# Phase 1: Foundation Verification Report

**Phase Goal:** Researchers can run any downstream script and trust that municipality codes, environment dependencies, and reference data are consistent and correct
**Verified:** 2026-04-01T20:55:00Z
**Status:** passed
**Re-verification:** Yes -- after gap closure (4 gaps from prior review)

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `uv run python -c "import pandas; import duckdb; import linearmodels"` succeeds on a clean checkout with versions matching pyproject.toml pins | VERIFIED | Python 3.12.11, pandas 2.3.3, duckdb 1.5.1, linearmodels OK. pyproject.toml pins pandas>=2.2.3,<3.0, duckdb>=1.5.1, linearmodels>=7.0 -- all satisfied. |
| 2 | `normalize_cod_ibge()` correctly canonicalizes 6-digit and 7-digit IBGE codes across all test fixtures without silent truncation or zero-padding errors | VERIFIED | Tested: 7-digit int, 7-digit str, 6-digit int, 6-digit str, whitespace-padded, NaN. All produce correct 7-digit zero-padded strings. NaN preserved (not coerced to "nan" string). 7 pytest tests pass. |
| 3 | The IBGE reference list loads with no duplicates and a row-count assertion passes | VERIFIED | CSV has 5571 rows (5572 lines including header), all 7-digit unique codes. `load_ibge_municipios()` asserts `len(df) == 5571`. The IBGE API returns 5571 municipalities as of April 2026 (includes Boa Esperanca do Norte-MT, code 5101837). ROADMAP text says 5570; actual API returns 5571. The codebase is internally consistent at 5571 throughout `database/utils.py`, `tests/test_utils.py`, `tests/test_ibge_reference.py`, and `data_sources/amc_crosswalk_2015_2023.csv`. |
| 4 | The validation gate rejects a DataFrame containing a known-bad municipality code and a known out-of-range value, raising a documented exception | VERIFIED | `validate_dataframe(df_bad_code, strict=True)` raises `ValidationError(check_name="cod_ibge_valid")`. `validate_dataframe(df_bad_year, strict=True)` raises `ValidationError(check_name="year_in_scope")`. In quarantine mode (strict=False), bad rows are written to Parquet in quarantine dir. 10 pytest tests pass. |
| 5 | The AMC temporal crosswalk maps all municipality splits/merges from 2013-2023 to their canonical 2023 codes | VERIFIED | Crosswalk has 5571 stable rows covering all canonical 2023 municipalities. Known 2013 emancipation successors (Balneario Rincao, Pinto Bandeira, Pescaria Brava, Mojui dos Campos) all present and mapped correctly. `apply_amc_crosswalk()` returns unchanged codes for stable-period data. 12 pytest tests pass. |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `pyproject.toml` | Pinned dependency declarations for all project libraries | VERIFIED | 18 dependencies pinned (16 runtime + 2 dev), requires-python >=3.12,<3.14, pyyaml>=6.0 for config loading |
| `uv.lock` | Reproducible lock file with exact hashes | VERIFIED | 258KB, non-empty, not in .gitignore (tracked for reproducibility) |
| `.python-version` | uv runtime pin to Python 3.12 | VERIFIED | Contains "3.12" |
| `config.example.yaml` | NAS and local data path configuration template | VERIFIED | Contains data_root, raw_dir, processed_dir, quarantine_dir, db_dir, output_dir keys |
| `config.yaml` | Machine-local NAS config (not tracked) | VERIFIED | Exists, excluded from git via .gitignore |
| `database/utils.py` | normalize_cod_ibge(), load_ibge_municipios(), rename_municipality_column() | VERIFIED | All 3 functions exported. MUNICIPALITY_CODE_COLUMNS covers 10 known column name variants. Substantive: 210 lines. |
| `database/validation.py` | validate_dataframe(), ValidationError, ValidationReport, write_validation_report() | VERIFIED | All 4 exports present. 4-check pipeline (schema, IBGE code, year scope, duplicates). 436 lines. |
| `data_sources/ibge_municipios_2023.csv` | Canonical IBGE 2023 municipality reference list | VERIFIED | 5571 data rows, columns: cod_ibge, nome_municipio, uf. All codes 7-digit, no duplicates. |
| `data_sources/amc_crosswalk_2015_2023.csv` | Municipality boundary harmonization table 2015-2023 | VERIFIED | 5571 rows (all stable -- no boundary changes in study window). Columns: cod_ibge_original, year_valid_from, cod_ibge_2023, harmonization_type. |
| `scripts/build_amc_crosswalk.py` | Reproducible crosswalk builder script | VERIFIED | build_crosswalk() and apply_amc_crosswalk() defined. CLI entry point with argparse. |
| `tests/test_utils.py` | Tests for normalize_cod_ibge edge cases | VERIFIED | 12 tests across 4 test classes. All pass. |
| `tests/test_validation.py` | Tests for validation gate | VERIFIED | 10 tests across 3 test classes. All pass. |
| `tests/test_amc_crosswalk.py` | Tests for crosswalk structure and known splits | VERIFIED | 12 tests across 3 test classes. All pass. |
| `tests/test_ibge_reference.py` | Tests for IBGE reference CSV integrity | VERIFIED | 6 tests. All pass. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `config.yaml` | `database/pipeline.py` | `load_config()` called in `main()` | WIRED | `load_config()` defined at line 42, called at line 449 in `main()`. Config values used to set data_root, raw_dir, processed_dir, quarantine_dir, db_dir. |
| `database/utils.py` | `database/pipeline.py` | `from database.utils import rename_municipality_column, normalize_cod_ibge` | WIRED | Imported at lines 139 and 278. `rename_municipality_column()` called at lines 142 and 285. `normalize_cod_ibge()` called at line 292. Used in both `_validate_stage_output()` and `transform_merge()`. |
| `database/validation.py` | `database/pipeline.py` | `from database.validation import validate_dataframe` | WIRED | Top-level import at line 28. Called in `_validate_stage_output()` at line 154. `_validate_stage_output()` is called after each extraction stage (sih, cnes, ans, ifgf) in `run_pipeline()`. |
| `database/validation.py` | `database/utils.py` | `from database.utils import load_ibge_municipios` | WIRED | Lazy import inside `validate_dataframe()` at line 235. Used to load valid municipality codes for the cod_ibge_valid check. |
| `data_sources/ibge_municipios_2023.csv` | `database/utils.py` | `load_ibge_municipios()` reads the CSV | WIRED | `IBGE_MUNICIPIOS_PATH` constant points to the CSV. `load_ibge_municipios()` reads it via `pd.read_csv()` at line 195. |
| `data_sources/amc_crosswalk_2015_2023.csv` | `database/pipeline.py` | Loaded at merge stage for harmonization | NOT YET WIRED (by design) | The crosswalk CSV exists and `apply_amc_crosswalk()` works, but it is not yet called from pipeline.py. This is expected -- the crosswalk is applied during Phase 4 (Panel Assembly), not during Phase 1 extraction. The artifact and function are ready for downstream use. |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| SC-1: Environment imports | `uv run python -c "import pandas; import duckdb; import linearmodels"` | Python 3.12.11, pandas 2.3.3, duckdb 1.5.1 | PASS |
| SC-2: normalize_cod_ibge correctness | 5 format tests + NaN preservation | All 6 formats produce correct output | PASS |
| SC-3: IBGE reference count | `len(load_ibge_municipios()) == 5571` | 5571 rows, no duplicates | PASS |
| SC-4a: Validation rejects bad code | `validate_dataframe(bad_code_df, strict=True)` | Raises ValidationError(cod_ibge_valid) | PASS |
| SC-4b: Validation rejects bad year | `validate_dataframe(bad_year_df, strict=True)` | Raises ValidationError(year_in_scope) | PASS |
| SC-5: AMC crosswalk mapping | apply_amc_crosswalk stable passthrough + known emancipation check | 5571 stable rows, all 4 emancipations present | PASS |
| Full test suite | `uv run pytest tests/ -v` | 45 passed, 0 failed, 0 skipped | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| FOUN-01 | 01-01 | Python 3.12 runtime with uv-managed environment and reproducible uv.lock lockfile | SATISFIED | .python-version = 3.12, uv.lock exists (258KB), Python 3.12.11 confirmed via `uv run python --version` |
| FOUN-02 | 01-02 | Shared normalize_cod_ibge() utility for 6/7-digit IBGE code canonicalization | SATISFIED | database/utils.py exports normalize_cod_ibge(), handles all formats, 7 unit tests pass |
| FOUN-03 | 01-02 | IBGE reference list of canonical municipality codes for join validation | SATISFIED | data_sources/ibge_municipios_2023.csv has 5571 unique 7-digit codes. load_ibge_municipios() asserts count and uniqueness. |
| FOUN-04 | 01-04 | Validation gate (schema checks, range checks, duplicate detection) before merge | SATISFIED | database/validation.py implements 4 checks, strict/quarantine modes, JSON report output. 10 tests pass. |
| FOUN-05 | 01-01 | pyproject.toml with all dependencies pinned | SATISFIED | pyproject.toml has 18 pinned dependencies matching STACK.md specifications. uv.lock locks exact versions. |
| FOUN-06 | 01-03 | AMC temporal crosswalk for municipality boundary harmonization (2015-2023) | SATISFIED | data_sources/amc_crosswalk_2015_2023.csv with 5571 stable rows. build script is idempotent. apply_amc_crosswalk() tested. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| database/database_metadata.json | 6 | `"n_municipalities": 5570` (stale value; codebase uses 5571) | Info | Legacy pre-Phase-1 file. Not used by Phase 1 code. Will need updating in Phase 4 when database schema is built. No impact on Phase 1 goal. |

### Human Verification Required

None. All Phase 1 deliverables are verifiable programmatically. The phase produces utilities, reference data, and configuration -- no UI, no external service integration, no visual output.

### Note on IBGE Municipality Count (5571 vs 5570)

The ROADMAP Success Criterion 3 specifies `assert len(ref) == 5570`. The IBGE Localidades API (as of April 2026) returns 5571 municipalities, which includes Boa Esperanca do Norte-MT (code 5101837) created after the original 2023 reference was published. The codebase has been reconciled to 5571 throughout all assertions, tests, and the crosswalk. This is the correct behavior -- the reference list should reflect the current IBGE canonical list. The ROADMAP text should be updated to say 5571, but this does not constitute a gap since the spirit of the criterion (reference list loads with correct count, no duplicates) is fully satisfied.

### Gaps Summary

No gaps. All 4 previously-identified gaps have been closed:

1. **IBGE reference reconciled to 5571**: All assertions, tests, and crosswalk updated to 5571.
2. **validate_dataframe() wired into pipeline.py**: Imported at top-level, called via `_validate_stage_output()` after each extraction stage in `run_pipeline()`.
3. **normalize_cod_ibge/rename_municipality_column wired into transform_merge()**: Both imported and called in `transform_merge()` to canonicalize municipality codes before the outer join.
4. **load_config() called in main()**: Defined at line 42, called at line 449 in `main()`. Config values flow to `run_pipeline()` parameters.

No regressions detected. All 45 tests pass.

---

_Verified: 2026-04-01T20:55:00Z_
_Verifier: Claude (gsd-verifier)_
