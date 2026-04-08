# Phase 11: CI Reproducibility & HF Data Layer — Research

**Researched:** 2026-04-07
**Researcher:** Claude Opus 4.6 (interactive session)

## Problem statement

The `Build Database` workflow on `matheus-rech/ICSKG` has never succeeded. All three recent runs on `meta` failed with `KeyError: 'variable'` in `database/impute_ifgf.py:261`. The cryptic error masks a deeper architectural problem: **the workflow runs the v3 builder against an empty `data_sources/processed/` directory because that directory is gitignored, and the real data lives only on the user's NAS.** ICSKG is therefore not reproducible by anyone outside the user's house — including BMJ Global Health peer reviewers, who will require replication for the v1.0 submission.

## Investigation timeline

### 1. CI failure triage (root cause analysis)

**Workflow run inspected:** https://github.com/matheus-rech/ICSKG/actions/runs/24054805442 (Build ICSKG-BR Database (v3), commit `2c5e40f5`, branch `meta`, 2026-04-06 22:41Z)

**Stack trace:**
```
File "database/impute_ifgf.py", line 261, in generate_missingness_report
    report = report.sort_values(["variable", "year"]).reset_index(drop=True)
File "pandas/core/frame.py", line 7194, in sort_values
    keys = [self._get_label_or_level_values(x, axis=axis) for x in by]
File "pandas/core/generic.py", line 1914, in _get_label_or_level_values
    raise KeyError(key)
KeyError: 'variable'
```

**Source of the symptom** (`database/impute_ifgf.py` lines 232–262):
```python
value_cols = [c for c in panel.columns if c not in METADATA_COLS]
years = sorted(panel["year"].unique())
rows: list[dict] = []
for col in value_cols:
    for year in years:
        ...
        rows.append({"variable": col, "year": int(year), ...})

report = pd.DataFrame(rows)
report = report.sort_values(["variable", "year"]).reset_index(drop=True)  # ← KeyError here
```

When `rows == []`, `pd.DataFrame([])` produces a DataFrame with **zero columns**, so `sort_values(["variable", "year"])` cannot find either key.

**Why is `rows` empty in CI?** Tracing back:
1. `value_cols` is empty when the panel has only metadata columns (no source data merged)
2. `assemble_panel` produces a metadata-only scaffold when `data_sources/processed/` is empty
3. `data_sources/processed/` is empty in CI because **`.gitignore` line 2 (`data_sources/processed/`) excludes the entire tree** — only `.gitkeep` placeholders exist on github-hosted runners
4. Therefore the v3 builder is fundamentally running against no data on every CI invocation

**Confirmation that this isn't a regression:** All Build Database runs failed (3 out of 3). The workflow was added speculatively and never wired to a working data source.

### 2. Workflow inspection

**File:** `.github/workflows/build-database.yml` (committed on `meta`)

Key observations:
- Trigger: `workflow_dispatch` only — no automatic invocation
- Runs `python -m database.build_database_v3 --processed-dir data_sources/processed --db-dir database --years $START_YEAR $END_YEAR`
- No data-fetch step — the workflow assumes data is already present
- Uses `actions/checkout@v4` and `actions/setup-python@v5` — both flagged as Node 20 deprecation by GitHub (forced Node 24 default 2026-06-02, Node 20 removed 2026-09-16)
- 60-minute timeout
- Has separate v2/v3 paths and verification steps that are skipped after the v3 build step fails

**Conclusion:** The workflow expects the runner to already have a populated `data_sources/processed/` tree. There is no mechanism to acquire it. This is the bug to fix.

### 3. NAS audit (where does the real data live?)

**Method:** SMB-mounted Synology DS223j shares (`/Volumes/docker`, `/Volumes/home`, `/Volumes/homes`, NAS hostname `synology-rech.local` resolved to `192.168.1.109`). SSH to the NAS is refused (DSM default).

**Findings:**

| Path | Size | Modified | Content |
|---|---|---|---|
| `/Volumes/home/DataLake/30_models/icskg_br/icskg_br_export.duckdb` | **511 MB** | 2026-04-01 | Full export with all source tables, dimensions, panel, LCoGS — the canonical processed artifact |
| `/Volumes/home/DataLake/30_models/icskg_br/icskg_br.duckdb` | **4.7 MB** | 2026-04-01 | Slim panel + dimensions + CUDS — likely the published-shape DB |
| `/Volumes/docker/Downloads/ETLSIH.ST_*.csv` | unmeasured (very large) | various | Raw DATASUS SIH inpatient CSVs by state/year/month, going back to 2008 |
| `/Volumes/docker/Downloads2/ETLCNES` | unmeasured | various | CNES facility/workforce data |
| `/Volumes/docker/Downloads3/PolisPCDaS.csv` | unmeasured | various | PCDaS health data platform export |
| `/Volumes/docker/ans-pipeline/ans.duckdb` | unmeasured | various | ANS quarterly beneficiary data, already in DuckDB form |
| `/Volumes/docker/Downloads/ICSKG.zip` | 2.2 MB | 2026-04-02 | Code snapshot, not data |

**DataLake curation tiers** (`/Volumes/home/DataLake/`):
- `00_raw/` → `huggingface`, `kaggle`, `webscrapes` (the user already mirrors HF artifacts to NAS)
- `30_models/` → `hf_snapshots`, `icskg_br`, `rs_flood_health`, `finetunes`, `gguf`, `ollama` (curated outputs)
- `90_manifests/datasets_20260302_152758.sha256` (checksum manifests are already an established habit)

**Critical implication:** The "processed parquet tree" mental model from the original codebase is misleading. Your real artifacts on NAS are **two DuckDB files totaling ~516 MB**. There is no partitioned parquet under `data_sources/processed/` — the parquet outputs from `scripts/extract_*.py` are intermediate and get baked into the DuckDB files. This radically simplifies the HF migration because 516 MB fits trivially in a single HF Dataset.

### 4. Storage option comparison

| Constraint | HF Datasets | Supabase | Neon | Turso | Cloudflare D1 | Git LFS |
|---|---|---|---|---|---|---|
| Free tier storage | ~unlimited for datasets | 500 MB | 0.5 GB | 500 MB | 5 GB | 1 GB |
| Free egress | ~unlimited | 5 GB/mo | — | — | — | 1 GB/mo |
| Native parquet | ✅ | ❌ (Postgres) | ❌ | ❌ | ❌ | ✅ (binary blob) |
| Immutable versioning | ✅ git revisions | ❌ | branches ≠ data snapshots | ❌ | ❌ | ✅ git revisions |
| DOI for publication | ✅ HF→Zenodo mirror | ❌ | ❌ | ❌ | ❌ | indirect |
| In-browser viewer | ✅ Dataset Viewer | ❌ | ❌ | ❌ | ❌ | ❌ |
| Cold-start cost in CI | None (HTTP pull) | Pool + auth | Cold starts | Edge auth | Edge auth | LFS smudge |

**Decision matrix outcome:**
- **HF Datasets wins** on every dimension that matters for ICSKG: storage size fits, parquet is the native shape, versioning is git-like, DOI mints via Zenodo mirror, the Dataset Viewer is huge for peer review, and CI just does an HTTP download.
- **SQL servers all fail on size:** Supabase (500 MB), Neon (0.5 GB), Turso (500 MB) — none fit even the slim 4.7 MB DuckDB plus the 511 MB export. Cloudflare D1 (5 GB) technically fits but the data shape is wrong.
- **Git LFS** has crippling bandwidth quotas (1 GB/mo free) and would burn budget on the first replication attempt.

**Where SQL would still make sense (out of scope for Phase 11):** A downstream Supabase view layer holding only the final 50,130-row panel (<100 MB) for a public Observable/Shiny dashboard. Phase F or v1.x.

### 5. Existing GSD planning conventions in this repo

Established by inspecting `.planning/phases/01-foundation/`, `.planning/phases/10-publication-package/`, `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md`, `.planning/STATE.md`:

- Phase directories: `.planning/phases/{NN}-{kebab-slug}/`
- Per-phase files:
  - `{NN}-CONTEXT.md` — gathered context with `<domain>`, `<decisions>`, `<code_context>`, `<specifics>`, `<deferred>` sections
  - `{NN}-RESEARCH.md` — investigation findings (sometimes)
  - `{NN}-{MM}-PLAN.md` — atomic execution plans with YAML frontmatter (`phase`, `plan`, `type`, `wave`, `depends_on`, `files_modified`, `autonomous`, `requirements`, `must_haves`)
  - `{NN}-{MM}-SUMMARY.md` — completion summary (post-execution)
  - `{NN}-DISCUSSION-LOG.md` — interactive Q&A log (when relevant)
  - `{NN}-VERIFICATION.md` — verification report (post-execution)
- `.planning/REQUIREMENTS.md` is the master requirements list with traceability table mapping requirement IDs to phases
- `.planning/ROADMAP.md` lists phases in order with goal/dependencies/success criteria/plan list
- `.planning/STATE.md` has YAML frontmatter (milestone, status, progress) and tracks current position
- Plans use `<context>` blocks with `@`-includes referencing PROJECT.md, ROADMAP.md, STATE.md, and the phase CONTEXT.md
- Plans use `<tasks>` blocks with `<task type="auto">` containing `<read_first>`, `<files>`, `<action>`, `<acceptance_criteria>`, `<verify><automated>`, `<done>`
- Each plan has top-level `<verification>`, `<success_criteria>`, `<output>` sections

This phase's plans will mirror that exact pattern.

## Open questions resolved during research

| Question | Resolution |
|---|---|
| Is the failure a regression or a never-worked workflow? | **Never worked.** All 3 historical runs failed. |
| Where is the real data? | **NAS:** `/Volumes/home/DataLake/30_models/icskg_br/{icskg_br_export.duckdb,icskg_br.duckdb}` |
| How big is it? | **~516 MB total** (511 + 4.7 MB) — fits any reasonable cloud target |
| Is it parquet or DuckDB? | **DuckDB only.** No partitioned parquet tree exists. We will export to parquet during Phase 11.1. |
| Public or private HF dataset? | **Private now**, flip to public at BMJ submission. DATASUS data is already public under Lei de Acesso so no legal blocker. |
| One HF dataset or split? | **One.** 516 MB does not need splitting. Per-state partitioning is a v0.2.0 optimization. |
| HF or SQL server? | **HF.** Every SQL free tier fails the size test, parquet is the native shape, DOI matters for publication. |
| Workflow auth: API key or OAuth? | **`HF_TOKEN` secret** for both CI (read-only) and the publish script (read-write). User generates on huggingface.co/settings/tokens. |
| Phase numbering vs current milestone? | Milestone v1.0 was marked completed 2026-04-02 (Phase 10 done). Phase 11 starts a new milestone (v1.1 — "Reproducibility"). |
| Branch base? | `origin/meta` (clean), via `git worktree add` to isolate from the dirty `feature/phase-10-publication-package` working tree. |

## What this phase does NOT investigate

- Re-extraction logic (`scripts/extract_*.py`) — those still write to local `data_sources/processed/` and the user runs them on NAS-mounted Mac when source data refreshes
- Analysis correctness — no `analysis/` files are touched
- Dimension formulas, CUDS computation, LCoGS indicators — frozen
- Whether the Apr 1 DuckDB export is the absolute latest (assumed yes; user will confirm before HF publish)
- The Claude Code GitHub Action auto-fix workflow — separate concern, deferred until CI works

## Sources

- Git log inspection on `origin/meta` and `feature/phase-10-publication-package`
- `gh run view 24054805442 --repo matheus-rech/ICSKG --log-failed`
- `gh api repos/matheus-rech/ICSKG/actions/workflows`
- Local SMB mounts of `synology-rech.local` shares
- Local clone at `/Users/matheusrech/untitled folder 6/ICSKG-phase11/` (worktree off `origin/meta`)
- HuggingFace action.yml schema (anthropics/claude-code-action@v1) for related auto-fix workflow research
- `.planning/phases/01-foundation/` and `.planning/phases/10-publication-package/` as templates for this phase's planning artifacts
