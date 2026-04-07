# Phase 11: CI Reproducibility & HF Data Layer - Context

**Gathered:** 2026-04-07
**Status:** Ready for planning
**Mode:** Interactive (user-driven, post-milestone-v1.0)

<domain>
## Phase Boundary

Decouple ICSKG-BR from the local NAS so the build is reproducible on any machine — including GitHub-hosted runners and BMJ Global Health peer reviewers' laptops. The canonical processed data layer moves from `/Volumes/home/DataLake/30_models/icskg_br/*.duckdb` (NAS-only, ~516 MB) to a versioned HuggingFace Dataset (`mmrech/icskg-br-processed`) stored as a parquet tree. CI fetches from HF, the v3 builder gains a `--from-hf` flag, fail-loud guards prevent any future "phantom database" CI runs, and replication is documented end-to-end. The NAS keeps its role as the *raw* DATASUS archive (100+ GB DBC files) and the place where you re-extract before publishing a new HF revision — but it is **never** in the CI critical path.

This phase produces no new analysis or new dimensions. It is an infrastructure refactor of the data plumbing layer, with verification anchored on a green Build Database workflow run on `meta` and a `python -m database.build_database_v3 --from-hf v0.1.0` round-trip on a clean clone.

</domain>

<decisions>
## Implementation Decisions

### Storage layer
- **Canonical store:** HuggingFace Dataset `mmrech/icskg-br-processed`, **private** until BMJ submission, then flipped public.
- **Shape:** Parquet tree (Shape B), one parquet file per logical table, organized by namespace (`panel/`, `dimensions/`, `lcogs/`, `source_tables/`). Reasons: HF Dataset Viewer renders parquet natively (huge for peer review), reviewers can pull a single table without downloading the whole 511 MB blob, much better Zenodo experience, and parquet compresses better than DuckDB internal storage on cold data.
- **Compression:** `zstd` level 6 (best size/speed tradeoff for medium-sized analytical tables).
- **Versioning:** Semantic, starting at `v0.1.0` and reserving `v1.0.0` for the BMJ submission cut. Each revision is a git tag on the HF dataset repo and pinned by SHA in `config.yaml`.
- **License (data):** CC-BY-4.0 once public. DATASUS sources are already public under Lei de Acesso 12.527/2011, so no new exposure.
- **NOT used as primary store:** Git LFS (bandwidth quotas), Supabase/Neon/Turso/D1 (free tiers all too small for filtered SIH; wrong shape), Cloudflare R2 (no native viewer/DOI), the NAS itself (single point of failure, not replicable).

### Why HF over a SQL server (decision rationale, do not relitigate)
- Free-tier storage of every SQL service caps below the 511 MB DuckDB export
- ICSKG data is parquet-shaped, not table-shaped — `build_database_v3.py` already uses DuckDB as primary store and DuckDB reads remote parquet natively; no SQL server needed in the loop
- HF gives DOI-able versioning out of the box; SQL servers do not
- HF Dataset Viewer = free in-browser peer review; SQL = nothing

### Fail-loud invariant
- ICSKG's invariant is: "5,570 municipalities × 9 years × 9 dimensions, or fail loudly." A silent header-only CSV or empty panel **must never** pass CI.
- `build_database_v3.py::main()` will gain a guard immediately after `assemble_panel`: if `value_cols` is empty or `panel.empty`, raise `RuntimeError` with a clear message naming the missing data.
- `database/impute_ifgf.py::generate_missingness_report()` will get the same loud guard plus a defense-in-depth schema-pin on the `pd.DataFrame(rows)` call so the symptom (cryptic `KeyError: 'variable'`) can never reappear.

### NAS role after this phase
- **Raw archive:** `/Volumes/docker/Downloads/` (SIH ETL CSVs), `/Volumes/docker/Downloads2/` (ETLCNES), `/Volumes/docker/ans-pipeline/`. Stays NAS-only forever.
- **Curated DuckDB outputs:** `/Volumes/home/DataLake/30_models/icskg_br/*.duckdb`. Used by the publish script as the source of truth for re-exporting to HF parquet.
- **Used by you:** for re-extraction (`scripts/extract_*.py`) and ad-hoc analysis. Not by CI. Not by reviewers.
- **NAS MCP server (Phase E, deferred):** A FastAPI/MCP wrapper exposing SIH/CNES query endpoints over Tailscale (private) for your interactive use from Claude Desktop. Out of scope for Phase 11.

### Branching and deployment
- Work happens on `feature/phase-11-ci-reproducibility-hf` branched off `origin/meta` (clean baseline, not the messy phase-10 worktree).
- Each plan within Phase 11 lands as a separate atomic commit with a descriptive conventional-commit message.
- PR opens against `meta` once 11.1, 11.2, 11.3 are all green. 11.4 and 11.5 may follow in subsequent PRs.

### Claude's discretion
- Exact parquet file naming under each namespace
- Whether to ship a `manifest.json` alongside the parquet tree (recommended yes — row counts, SHA256, schema version, source DuckDB SHA256)
- Whether `database/fetch_processed_data.py` materializes to disk vs. opens parquet directly via `duckdb.read_parquet("hf://...")` — both work; disk materialization is more debuggable
- Test fixture strategy: build a tiny synthetic HF dataset (`mmrech/icskg-br-processed-test`) for CI verification, OR use repo-bundled mini parquet under `tests/fixtures/processed_smoke/`. Prefer the bundled fixture since it eliminates a network dependency on every test run.

</decisions>

<code_context>
## Existing Code Insights

### Failing CI run (root cause this phase fixes)
- Workflow: Build Database, run id 24054805442, commit 2c5e40f5 on `meta` (2026-04-06 22:41Z)
- Error: `KeyError: 'variable'` in `database/impute_ifgf.py:261`, inside `generate_missingness_report()`
- Symptom path: `python -m database.build_database_v3 --processed-dir data_sources/processed --years 2015 2023` → `data_sources/processed/` is gitignored and contains only `.gitkeep` files on github-hosted runners → `assemble_panel` produces a metadata-only scaffold → `value_cols == []` → `rows == []` → `pd.DataFrame([])` has no columns → `sort_values(["variable", "year"])` raises `KeyError`
- All 3 recent runs of this workflow have failed (24054805442, 24015882753, 24015067101). The workflow has *never* succeeded since it was introduced. Phase 11.3 fixes that.

### Files that need to change
- `database/build_database_v3.py` — add `--from-hf <revision>` CLI flag, add fail-loud guard in `main()` after `assemble_panel`
- `database/impute_ifgf.py` — schema-pin fix in `generate_missingness_report()`, plus loud `ValueError` when called on metadata-only panel
- `database/fetch_processed_data.py` — **new file**, wraps `huggingface_hub.snapshot_download()`, materializes parquet tree under `data_sources/processed/`
- `scripts/publish_to_hf.py` — **new file**, runs against the NAS DuckDB exports, converts each table to parquet with zstd6 + manifest, uploads to HF via `huggingface_hub`
- `.github/workflows/build-database.yml` — replace empty-dir build with HF-fetch build, bump `actions/checkout@v4→v5` and `actions/upload-artifact@v4→v5` (Node 20 deprecation, forced default June 2 2026), add `actions/cache@v4` on `~/.cache/huggingface`, consume `HF_TOKEN` secret
- `pyproject.toml` — add `huggingface_hub>=0.26` to main dependencies (it's already a transitive dep of the ML stack but make it explicit)
- `config.example.yaml` — add `hf_dataset_repo`, `hf_dataset_revision`, `hf_token_env_var` keys
- `tests/test_fetch_processed_data.py` — **new file**, mocks `snapshot_download`, verifies materialization paths
- `tests/test_build_database_v3.py` — extend with the empty-panel guard test
- `tests/test_impute_ifgf.py` — extend with metadata-only panel test
- `tests/fixtures/processed_smoke/` — **new directory**, ~20 municipalities × 2 years of mini parquet for CI smoke testing
- `README.md` — add "Reproducing the build" section pointing at `--from-hf`
- `docs/REPLICATION.md` — **new file**, end-to-end fresh-clone walkthrough
- `.zenodo.json` — fill placeholder author/institution/funder fields (currently `[Author Name]` / `[Institution]`)
- `scripts/mirror_to_zenodo.py` — **new file** (Phase 11.5), one-shot HF→Zenodo deposit

### Files that must NOT change (out of scope guard)
- All of `analysis/` — no analysis layer touched
- `database/assemble_panel.py`, `database/impute_ifgf.py::impute_ifgf_mice`, `database/deflate_ipca.py`, `database/build_database.py` (v1) — no algorithmic changes
- `scripts/extract_*.py` — no changes to extractors
- All compute_dimensions, run_regressions, ml_models, spatial_analysis, causal_inference outputs

### NAS audit findings (2026-04-07)
- **Curated outputs:** `/Volumes/home/DataLake/30_models/icskg_br/`
  - `icskg_br_export.duckdb` — 511 MB, last modified Apr 1 — full exported database with all source tables
  - `icskg_br.duckdb` — 4.7 MB, last modified Apr 1 — slim panel + dimensions + CUDS
- **Raw DATASUS archive:** `/Volumes/docker/Downloads/` — full SIH ETL CSV history (e.g., `ETLSIH.ST_AC_2008_*.csv`), `Downloads2/ETLCNES`, `Downloads3/PolisPCDaS.csv`. Out of scope for HF — stays NAS-only.
- **DataLake structure:** `00_raw`, `30_models`, `80_archive`, `90_manifests`, `99_trash`. Curated tier convention is `30_models/{project_slug}/`.
- **Existing pattern:** `30_models/hf_snapshots/` shows the user already mirrors HF artifacts to NAS — the inverse direction (NAS → HF) is the new direction this phase establishes.
- **Manifest convention:** `90_manifests/datasets_*.sha256` shows checksum manifests are already a habit — Phase 11.1 publish script will produce a matching `manifest.json` for the HF dataset.

### Auth context
- HuggingFace authenticated user on this machine: `mmrech`
- The user has previously published HF datasets from this machine
- HF token will be added to GitHub repo secrets as `HF_TOKEN` (Phase 11.3, manual action by user)
- Local `huggingface-cli login` already exists and CLAUDE-side scripts can rely on `~/.cache/huggingface/token` for the publish script

</code_context>

<specifics>
## Specific Ideas

- Use `huggingface_hub.HfApi.upload_folder(...)` for the initial publish, with `repo_type="dataset"` and `commit_message` referencing the source DuckDB SHA256
- Use `huggingface_hub.snapshot_download(repo_type="dataset", revision="v0.1.0", local_dir=..., allow_patterns=["**/*.parquet", "manifest.json"])` for the fetch
- Tag `v0.1.0` on the HF dataset via `HfApi.create_tag()` immediately after the first successful upload
- Pin the dataset revision in `config.example.yaml` so a fresh clone is fully deterministic
- The fetch script should compare downloaded `manifest.json` SHA256s against actual file SHA256s on disk to detect cache corruption
- For local development: store the HF token in `~/.zshrc` as `HF_TOKEN` (already a pattern in user's CLAUDE.md global)
- For CI: pass `secrets.HF_TOKEN` as env var to the action step that runs `python -m database.fetch_processed_data`
- The `tests/fixtures/processed_smoke/` directory should be ~50 KB total — small enough to commit, large enough to exercise every code path in `assemble_panel`, `impute_ifgf_mice`, `build_database`. Use 5 municipalities × 2 years × all 9 source tables.

</specifics>

<deferred>
## Deferred Ideas

- **NAS MCP server (Phase E):** FastAPI or pure MCP server on the Synology DS223j exposing `sih_query(year, state, icd10_prefix)`, `cnes_facility(cnes_id)`, `sidra_fetch(table_id)` endpoints. Used by Claude Desktop for interactive ad-hoc analysis against fresh DATASUS data without re-extracting. Never used by CI. Tailscale-private. Out of scope here.
- **Supabase view layer:** A 50,130-row Postgres mirror of the final panel for an Observable/Shiny dashboard at submission time. Free tier easily accommodates the panel size. Out of scope here — comes after Phase 11.5.
- **MotherDuck integration:** Free tier (10 GB) could query parquet directly from HF URLs. Useful for ad-hoc analytical queries from notebooks but not needed for CI. Out of scope.
- **Differential dataset updates:** The current plan is full re-publish per revision. Eventually we want incremental updates (new year of SIH appended without re-uploading 2015–2022). Out of scope until v1.x.
- **Per-state SIH parquet partitioning:** The HF dataset could partition `source_tables/sih_*.parquet` by state for selective downloads. Initial v0.1.0 ships unpartitioned single files; partitioning is a v0.2.0 optimization.
- **Auto-fix CI workflow:** The Claude Code GitHub Action `anthropics/claude-code-action@v1` pattern that auto-fixes failing workflows. Was discussed earlier — on ice until CI is reproducible (no point auto-fixing a broken foundation). Revisit after Phase 11.3 is green.

</deferred>
