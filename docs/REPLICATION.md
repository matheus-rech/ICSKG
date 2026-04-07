# Reproducing the ICSKG-BR build

This walkthrough takes a fresh git clone of [matheus-rech/ICSKG](https://github.com/matheus-rech/ICSKG) and produces a working `database/icskg_br.sqlite` containing the published 50,130-row municipality-year panel (5,570 municipalities × 9 years) in **under 15 minutes** with no NAS access. It is the canonical replication path for **BMJ Global Health peer reviewers** and any researcher who wants to verify the published dataset.

If you find any step that doesn't work as documented, please [open an issue](https://github.com/matheus-rech/ICSKG/issues/new) — and run `bash docs/REPLICATION.test.sh` first to capture the exact failing step.

---

## Prerequisites

| Requirement | Why |
|---|---|
| Python **3.12** or 3.13 | The project pins `requires-python = ">=3.12,<3.14"` in `pyproject.toml`. Older Pythons will fail at install. |
| Git | To clone the repository. |
| ~2 GB free disk | The HuggingFace dataset is ~150 MB compressed; the materialized SQLite is ~5 MB; the cache + workspace is the rest. |
| HuggingFace account + token | The processed dataset is **private** during the BMJ Global Health pre-submission window. A free account + read-scoped token is enough. After publication the token will become optional. |

Optional but recommended:

- **`uv`** (the Astral Python package manager) for fast dependency resolution. Install via `curl -LsSf https://astral.sh/uv/install.sh | sh` or `brew install uv`.

---

## Quick path

If you have Python 3.12 + git + an HF token, this is the entire replication. Total time: **~5–8 minutes** on first run, **~1–2 minutes** on subsequent runs (HF cache hit).

```bash
# 1. Clone the repository
git clone https://github.com/matheus-rech/ICSKG.git
cd ICSKG

# 2. Install dependencies
uv sync                                # if you have uv
# OR
python3.12 -m venv .venv && source .venv/bin/activate && pip install -e .

# 3. Set your HuggingFace token (read-scoped)
#    Get one at https://huggingface.co/settings/tokens
export HF_TOKEN=hf_yourtokenhere
# OR (recommended for repeat use)
huggingface-cli login

# 4. Sanity check: run the unit test suite
python -m pytest tests/ -v --tb=short

# 5. Fetch + verify + materialize the database
python -m database.fetch_processed_data \
    --revision v0.1.0 \
    --to database/icskg_br.sqlite

# 6. Confirm it worked
sqlite3 database/icskg_br.sqlite "SELECT COUNT(*) FROM municipal_health"
# Expected output: 50130
```

That's it. The resulting `database/icskg_br.sqlite` contains the same panel that backs every figure and table in the BMJ Global Health manuscript.

> **Why do some local code paths still use 5,571 rows/year?**  
> The source-build scaffold and `municipality_lookup` table retain the full
> 5,571-row IBGE reference CSV checked into the repo, which includes
> `2605459` / Fernando de Noronha. That is why `database.build_database_v3`
> smoke tests assert 11,142 rows for a two-year source build. The published HF
> release panel is the filtered 5,570-municipality artifact, so its canonical
> verification invariant remains 50,130 rows.

---

## Detailed path (with explanations)

### 1. Clone

```bash
git clone https://github.com/matheus-rech/ICSKG.git
cd ICSKG
```

The repo is ~50 MB after clone. Most of that is the planning history (`.planning/`) and the smoke test fixture (`tests/fixtures/processed_smoke/`, ~64 KB). The actual code is small.

### 2. Install Python 3.12

If you don't already have Python 3.12, pick one:

**macOS (Homebrew):**
```bash
brew install python@3.12
```

**Ubuntu/Debian:**
```bash
sudo apt-get update && sudo apt-get install -y python3.12 python3.12-venv
```

**Windows / WSL2:**
- Download from https://www.python.org/downloads/, OR
- Use `wsl --install` then run the Ubuntu command above

**Or just use `uv`** (works on all platforms):
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
# uv will fetch the right Python automatically when you run `uv sync`
```

### 3. Install project dependencies

**Recommended (uv):**
```bash
uv sync
```
This reads `pyproject.toml` + `uv.lock` and creates a `.venv/` with all 100+ pinned dependencies in ~30 seconds.

**Classic pip:**
```bash
python3.12 -m venv .venv
source .venv/bin/activate    # on Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -e .
pip install pytest           # for the sanity check step
```
This is slower (~2 minutes) but works without uv.

### 4. Get and set the HuggingFace token

1. Visit https://huggingface.co/settings/tokens
2. Click "New token"
3. Name it something memorable (e.g., `icskg-replication`)
4. Type: **Read** (write is not needed)
5. Click "Create token"
6. Copy the token (starts with `hf_`)

Then either set the env var:
```bash
export HF_TOKEN=hf_yourtokenhere
```

Or persist it via the HuggingFace CLI (recommended for repeat use):
```bash
huggingface-cli login
# Paste token when prompted; it's saved to ~/.cache/huggingface/token
```

### 5. Run the unit test suite

```bash
python -m pytest tests/ -v --tb=short
```

Expected: **all tests pass** in ~20 seconds. If anything fails, please [file an issue](https://github.com/matheus-rech/ICSKG/issues/new) with the failing test name and your Python version.

### 6. Fetch and materialize the database

```bash
python -m database.fetch_processed_data \
    --revision v0.1.0 \
    --to database/icskg_br.sqlite
```

What this does, step by step:

1. **Resolves your HF token** from `HF_TOKEN` env var or `~/.cache/huggingface/token`
2. **Downloads** the parquet tree at revision `v0.1.0` to `~/.cache/icskg/hf-snapshots/v0.1.0/`
   - This is a one-shot snapshot via `huggingface_hub.snapshot_download`
   - File patterns: `**/*.parquet`, `manifest.json`, `README.md`
   - On second runs the cache hit is detected and the download is skipped
3. **Verifies** the manifest:
   - Reads `manifest.json` from the snapshot
   - For every table entry, computes the SHA256 of the local parquet file and compares against the recorded hash
   - Reads parquet metadata to confirm the row count matches the manifest
   - Raises `RuntimeError` on any mismatch (catches cache corruption / tampering)
4. **Verifies the published panel invariant**: `panel/municipal_health.parquet` must have exactly **50,130 rows** (5,570 municipalities × 9 years 2015-2023). This is the canonical release artifact invariant. The local source-build scaffold remains 5,571 rows/year because it preserves the full checked-in IBGE reference list, including Fernando de Noronha.
5. **Materializes a SQLite** at `database/icskg_br.sqlite` by walking the parquet tree and ingesting each file as a table via `pandas.read_parquet` + `pandas.DataFrame.to_sql` (stdlib `sqlite3`, no DuckDB required).

Total time: ~5 minutes on first run (download bound), ~1 minute on cache hit (no download).

### 7. Verify

```bash
sqlite3 database/icskg_br.sqlite "SELECT COUNT(*) FROM municipal_health"
# Expected: 50130
```

If you have `sqlite3` installed, you can also browse:

```bash
sqlite3 database/icskg_br.sqlite ".tables"
# Lists the tables: municipal_health, dimension_scores, lcogs_indicators, ...

sqlite3 database/icskg_br.sqlite "SELECT cod_ibge, year, cuds FROM municipal_health WHERE cod_ibge='3550308' ORDER BY year"
# São Paulo CUDS by year
```

---

## Expected output

A successful run looks like this:

```text
2026-04-07 10:23:14 [INFO] database.fetch_processed_data: ──────────────────────────────────────
2026-04-07 10:23:14 [INFO] database.fetch_processed_data: Fetching mmrech/icskg-br-processed @ v0.1.0 -> /home/user/.cache/icskg/hf-snapshots/v0.1.0
2026-04-07 10:23:14 [INFO] database.fetch_processed_data: ──────────────────────────────────────
Fetching 12 files: 100%|██████████| 12/12 [02:31<00:00, 12.6s/it]
2026-04-07 10:25:46 [INFO] database.fetch_processed_data: Snapshot materialized at /home/user/.cache/icskg/hf-snapshots/v0.1.0
2026-04-07 10:25:46 [INFO] database.fetch_processed_data: Verifying 12 tables from manifest mmrech/icskg-br-processed @ v0.1.0
2026-04-07 10:25:46 [INFO] database.fetch_processed_data:   ✓ panel/municipal_health.parquet                   50130 rows, sha256 a1b2c3d4e5f6
2026-04-07 10:25:46 [INFO] database.fetch_processed_data:   ✓ panel/municipality_lookup.parquet                5571 rows, sha256 ...
[... more entries ...]
2026-04-07 10:25:48 [INFO] database.fetch_processed_data: Manifest verification passed: 12 tables OK
2026-04-07 10:25:48 [INFO] database.fetch_processed_data: Panel row count: 50130 (expected 50130)
2026-04-07 10:25:48 [INFO] database.fetch_processed_data: Materializing 12 parquet files into database/icskg_br.sqlite
[... ingestion progress ...]
2026-04-07 10:25:51 [INFO] database.fetch_processed_data: Materialized database/icskg_br.sqlite (5.42 MB)
2026-04-07 10:25:51 [INFO] database.fetch_processed_data: Done. Verified parquet tree at /home/user/.cache/icskg/hf-snapshots/v0.1.0
2026-04-07 10:25:51 [INFO] database.fetch_processed_data: Materialized sqlite at database/icskg_br.sqlite
```

---

## Troubleshooting

### `401 Unauthorized` / `RepositoryNotFoundError`

Your `HF_TOKEN` is missing, expired, or doesn't have access to the private dataset.

**Fix:**
```bash
huggingface-cli whoami        # confirms which account is logged in
huggingface-cli login          # paste a fresh token
# OR
export HF_TOKEN=hf_yourtokenhere
```

If you're seeing `RepositoryNotFoundError` even with a valid token, the dataset may still be private and your account might not be on the access list. For BMJ peer reviewers, contact the corresponding author for access.

### `KeyError: 'variable'`

You should never see this error after Phase 11. If you do, it means the failing CI bug from before commit `099c8a1` has somehow regressed. Please [file an issue](https://github.com/matheus-rech/ICSKG/issues/new) with the full traceback.

### `RuntimeError: Refusing to build a phantom database`

You ran `python -m database.build_database_v3` (the local build) without populating `data_sources/processed/`. That script builds **from raw source data** and is meant for the project maintainer who has the NAS-mounted DATASUS archive. As a replicator, you want `database.fetch_processed_data` instead, which fetches the **pre-built** dataset.

### `EntryNotFoundError` from huggingface_hub

You passed a `--revision` that doesn't exist on the dataset repo. Valid revisions are listed at https://huggingface.co/datasets/mmrech/icskg-br-processed/tags. The current canonical revision is `v0.1.0`.

### `ImportError: huggingface_hub`

You forgot to run `uv sync` or `pip install -e .`. The project needs `huggingface_hub>=0.26` declared in `pyproject.toml`.

### `pyarrow.lib.ArrowNotImplementedError` reading parquet

You're on an old `pyarrow`. The project requires `pyarrow>=19`. Re-run `uv sync` or `pip install --upgrade pyarrow`.

---

## Verifying analysis reproducibility (optional)

Once you have `database/icskg_br.sqlite`, you can re-run the statistical analysis layer:

```bash
# Two-way fixed-effects panel regression of CUDS → 6 LCoGS outcomes
python -m analysis.run_regressions --db-path database/icskg_br.sqlite

# Random Forest + XGBoost with SHAP feature importance
python -m analysis.ml_models --db-path database/icskg_br.sqlite

# Spatial autocorrelation + choropleth maps
python -m analysis.spatial_analysis --db-path database/icskg_br.sqlite
```

Each module writes results to `analysis/results/`. For the published paper, the key cross-checks are:

- **Table 5 (regression coefficients)**: `results/tables/table5_regression_access_workforce.csv` should match the values reported in the BMJ Global Health manuscript Table 5 within rounding (±0.001 on CUDS coefficients, ±0.01 on standard errors).
- **Figure 4 (forest plot)**: `results/figures/regression_forest_plot.png` should reproduce the published Figure 4 visually.

If any analysis output diverges materially from the published values, please file an issue with the discrepancy.

---

## Citation

If you use ICSKG-BR in your work, please cite both the dataset and the code.

**Dataset (Zenodo, public after BMJ Global Health acceptance):**
```
Rech, Matheus M. (2026). ICSKG-BR: Index of Cities' Smartness & Knowledge for
Global Surgery — Brazil (Processed Data) [Data set]. Zenodo.
https://doi.org/<DOI-TO-BE-MINTED-AT-ACCEPTANCE>
```

**Code (GitHub release tagged at submission):**
```
Rech, Matheus M. (2026). matheus-rech/ICSKG: v1.0.0 [Software]. GitHub.
https://github.com/matheus-rech/ICSKG/releases/tag/v1.0.0
```

**HuggingFace Dataset (interim canonical store):**
```
mmrech/icskg-br-processed (HuggingFace Datasets, revision v0.1.0).
https://huggingface.co/datasets/mmrech/icskg-br-processed
```

The Zenodo DOI will be minted at BMJ acceptance via `scripts/mirror_to_zenodo.py` (Phase 11.5). Until then, cite the HuggingFace Dataset revision directly.

---

## Reporting issues

If any step in this walkthrough fails:

1. **Run the self-test first**: `bash docs/REPLICATION.test.sh` will exercise the entire flow and surface the exact failing step.
2. **Open an issue** at https://github.com/matheus-rech/ICSKG/issues/new with:
   - The failing step (number from this walkthrough)
   - The exact error message or traceback
   - Your OS + Python version (`python --version` + `uname -a`)
   - The output of `huggingface-cli whoami` (do NOT paste the token)

We aim to respond within 48 hours during the BMJ pre-submission window.
