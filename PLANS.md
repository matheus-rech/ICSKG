# ICSKG-BR — Incremental Implementation Plan

This file is the *single*, high-level, living roadmap for building ICSKG-BR
incrementally (a little every day) without losing the big picture.

It complements (does not replace) the detailed phase plans under
`/home/runner/work/ICSKG/ICSKG/.planning/phases/`.

## How to use this plan (daily cadence)

1. Pick **1–3** unchecked items for “today”.
2. Keep changes small and shippable (tests green).
3. When an item is done, check it off and, if needed, add the next smallest
   follow-up item.

Suggested daily definition of done:
- [ ] `python -m pytest tests/ -q --tb=short` passes
- [ ] Any new/changed CLI behavior has a usage example in the relevant docstring
- [ ] Any new data table has: schema, join keys, year coverage rules, and
      validation expectations documented (briefly) in code or docs

## Project invariants (do not break)

These invariants are referenced across docs, CI, and the reproducibility layer:

- **Release panel invariant (HF dataset):** 5,570 municipalities × 9 years (2015–2023)
  = **50,130 rows** in `panel/municipal_health.parquet` and `municipal_health` table.
- **Local scaffold invariant (from-source builds):** 5,571 IBGE reference codes per year
  (includes Fernando de Noronha reference row) ⇒ e.g. **11,142 rows** for 2022–2023 smoke builds.
- **Manifest trust boundary:** every parquet path in `manifest.json` must be validated
  and cannot escape the snapshot directory (`database.fetch_processed_data`).

## Canonical workflows (commands)

**Unit tests (canonical sanity check):**
```bash
python -m pytest tests/ -q --tb=short
```

**Smoke build (local pipeline over committed fixture):**
```bash
python -m database.build_database_v3 \
  --processed-dir tests/fixtures/processed_smoke \
  --db-dir /tmp/icskg_smoke \
  --years 2022 2023
```

**Replication (reviewer / CI fetch path; requires `HF_TOKEN` if private):**
```bash
python -m database.fetch_processed_data --revision v0.1.0 --to database/icskg_br.sqlite
sqlite3 database/icskg_br.sqlite "SELECT COUNT(*) FROM municipal_health"
```

## Current state (baseline)

- [x] **Phase 11 reproducibility layer** exists:
  - publish-side: `scripts/publish_to_hf.py`
  - fetch/verify/materialize: `database/fetch_processed_data.py`
  - CI: `.github/workflows/build-database.yml` (manual HF fetch)
  - CI: `.github/workflows/build-database-smoke.yml` (fixture-based local build)
- [x] **Local build pipeline (maintainer track)**:
  `assemble_panel -> impute_ifgf_mice -> build_database` via `database/build_database_v3.py`
- [ ] **Cookbook compliance gap (Phase 12)** remains:
  missing extractors + CUDS construction + moving `municipal_health` derivation into the build.

## Roadmap (incremental, high-level)

### A) Keep the baseline green (always-on)

- [ ] Keep `python -m pytest tests/ -q --tb=short` green on every change.
- [ ] Keep `Build Database (smoke)` workflow green for any change touching:
      `database/**`, `scripts/**`, `tests/**`, `pyproject.toml`, `uv.lock`.
- [ ] Avoid changes that require non-wheel system dependencies (unless explicitly planned).

### B) Phase 12 — Close the cookbook compliance gap (target: v0.2.0)

This is the next “big” milestone and should be built as many small PR-sized steps.

#### B1) Lock decisions (Phase 12 kickoff)

- [ ] Choose RAIS strategy: **aggregated municipal bulletins** vs **microdata**.
- [ ] Freeze indicator→dimension mapping for CUDS (what columns feed each dimension).
- [ ] Decide missing-data rules for PCA weighting (drop threshold + imputation approach).
- [ ] Define “SNIS vs Census 2022 sanitation” policy:
      replace, keep both, or keep Census as fallback only.

#### B2) Implement missing extractors (cookbook §3 sources)

These exist as skeletons today; implement one at a time with clear contracts.

- [ ] Implement ANATEL broadband extractor: `scripts/extract_anatel_broadband.py`
  - Output: annual municipality table with `cod_ibge`, `year`, and broadband indicators
  - Determinism: fixed aggregation rule (e.g., Dec snapshot vs annual mean)
- [ ] Implement RAIS employment extractor: `scripts/extract_rais_employment.py`
  - Output: `cod_ibge`, `year`, employment/wage indicators (nominal; deflation downstream)
- [ ] Implement SNIS sanitation extractor: `scripts/extract_snis_sanitation.py`
  - Output: `cod_ibge`, `year`, sanitation coverage indicators; preserve missing where voluntary
- [ ] Stabilize SIOPS extractor: `scripts/extract_siops.py`
  - Replace “best-effort empty parquet” with an authoritative, maintained endpoint strategy
  - Ensure failures are explicit and validation reports show missingness clearly
- [ ] Confirm/finish international comparators if intended for v0.2.0:
      `scripts/extract_international_comparators.py`

Definition of done per extractor:
- [ ] CLI works with `--start-year/--end-year` and a clearly documented raw input layout
- [ ] Output schema is stable and validated (`cod_ibge` normalized, years in scope)
- [ ] Adds/updates at least one unit test covering parsing + schema + edge cases

#### B3) Integrate new sources into assembly + validation

- [ ] Extend `database/assemble_panel.py` `SOURCE_CATALOG` for each new processed table.
- [ ] Ensure `database/validation.py` checks remain correct for:
      - cross-sectional broadcasting vs yearly sources
      - duplicate key handling
      - quarantine outputs and `validation_report.json`
- [ ] Ensure the “fail-loud guard” in `database/build_database_v3.py` still fires on empty input.

#### B4) Move `municipal_health` derivation into the build (not publish-time)

Today, `panel/municipal_health.parquet` is derived at publish-time in
`scripts/publish_to_hf.py::derive_municipal_health_panel`. Phase 12 goal:
make it a base table produced by the build pipeline.

- [ ] Implement `municipal_health` derivation in the build path (DuckDB/SQLite side)
- [ ] Update publisher to export the base table rather than deriving it
- [ ] Keep the **50,130-row invariant** enforced in exactly one canonical place

#### B5) Implement CUDS construction (cookbook §6)

Build this as a small, testable pipeline (module boundaries matter).

- [ ] Create CUDS normalization step (min-max to [0, 1], directionality handling)
- [ ] Implement PCA weighting step (first component, reproducible settings)
- [ ] Implement aggregation step (weighted geometric mean)
- [ ] Persist outputs in DB / export:
  - `dimensions/dimension_score.parquet`
  - `dimensions/dimension_metadata.parquet`
  - `dimensions/cuds.parquet`
- [ ] Add robustness checks (bootstrap + alternative aggregations) with tests

#### B6) Publish v0.2.0 artifact and update defaults

- [ ] Update dataset card + manifest schema as needed
- [ ] Tag and publish v0.2.0 (HF) and update:
  - docs default revision(s)
  - `.github/workflows/build-database.yml` default input revision

### C) Security & dependency health (post-v0.2.0, opportunistic)

- [ ] Reduce transitive CVE exposure by removing the `pysus -> elasticsearch -> urllib3<2` choke point
      (preferred approach: consume FIOCRUZ pre-ETL CSV/ZIPs instead of DBC conversion).
- [ ] Keep the “manifest trust boundary” and safe table-name checks in fetch/materialize paths.

## Daily template (copy/paste into your PR description or notes)

```text
Today:
- [ ] …
- [ ] …

Done:
- [x] …

Risks / decisions needed:
- [ ] …

Next:
- [ ] …
```

