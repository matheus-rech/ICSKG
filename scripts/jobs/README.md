# HF Jobs runbook — Phase 12 FIOCRUZ migration

## Status

**BLOCKED on HF Jobs credits.** As of 2026-04-07, all `hf jobs run` calls
return `402 Payment Required` regardless of variant (experimental
`hf jobs uv run`, regular `hf jobs run`, all flavors). HF Pro does not
include compute credits — they're a separate purchase.

To unblock: top up at https://huggingface.co/settings/billing
(typically $5-10 covers a 31 GB download + processing job).

After credits land, run the commands below in order.

## Architecture

The bucket+jobs combo is designed so neither the 31 GB ETLSIH.zip
download nor the ~3 GB processed parquet output ever touches local disk:

```
┌──────────┐    curl     ┌────────────────┐    -v mount    ┌───────────────────────┐
│ FIOCRUZ  │ ──────────► │  HF Job (cpu)  │ ─────────────► │ hf://buckets/mmrech/  │
│  ICICT   │   31 GB     │   /tmp +       │   read+write   │       sihsus          │
│ ETLSIH.  │   download  │   /data mount  │                │                       │
│   zip    │             │                │                │                       │
└──────────┘             └────────────────┘                └───────────────────────┘
                                  │                                    │
                                  │ python process                     │
                                  ▼                                    │
                         ┌─────────────────┐                          │
                         │  parquet files  │ ─────────────────────────┘
                         └─────────────────┘
```

The `-v hf://buckets/mmrech/sihsus:/data` flag mounts the bucket as a
read+write filesystem inside the job container. Files written to `/data`
inside the job appear in the bucket after the job finishes. No HF API
uploads, no `huggingface_hub.upload_file()` calls needed.

## Step 1 — Smoke test (verify credits + bucket mount work)

```bash
hf jobs run \
    --secrets HF_TOKEN \
    -v hf://buckets/mmrech/sihsus:/data \
    --flavor cpu-basic \
    ubuntu:latest \
    bash -c "echo SMOKE_OK; date; df -h /data; ls -la /data; touch /data/.smoke_ok"
```

Success criteria:
- Exit code 0
- Job logs show `SMOKE_OK`, current date, free space on `/data`
- `hf buckets ls hf://buckets/mmrech/sihsus` shows `.smoke_ok` afterward

If this 402s, credits still aren't loaded. Stop here.

## Step 2 — Download ETLSIH.zip into the bucket (no processing)

```bash
hf jobs run \
    --secrets HF_TOKEN \
    -v hf://buckets/mmrech/sihsus:/data \
    --flavor cpu-basic \
    --timeout 4h \
    ubuntu:latest \
    bash -c '
      set -euo pipefail
      apt-get update -qq && apt-get install -y -qq curl ca-certificates
      cd /data
      mkdir -p raw/sih
      cd raw/sih
      echo "Downloading ETLSIH.zip from FIOCRUZ ICICT (31 GB)..."
      curl -L --fail --retry 3 --retry-delay 10 \
           -o ETLSIH.zip \
           https://bigdata-arquivos.icict.fiocruz.br/PUBLICO/SIH/ETLSIH.zip
      ls -lah ETLSIH.zip
      sha256sum ETLSIH.zip | tee ETLSIH.zip.sha256
      curl -L --fail --retry 3 --retry-delay 10 \
           -o dict_SIH.csv \
           https://bigdata-arquivos.icict.fiocruz.br/PUBLICO/SIH/dict_SIH.csv
      ls -lah
      echo "Done. Bucket now has raw/sih/ETLSIH.zip + sha256 + dict."
    '
```

Wallclock estimate: 30-90 minutes (FIOCRUZ ICICT bandwidth + HF runner bandwidth).
Cost estimate: ~$1-3 on cpu-basic flavor.

After completion, verify:
```bash
hf buckets ls hf://buckets/mmrech/sihsus/raw/sih/
# Should show: ETLSIH.zip (~31 GB), ETLSIH.zip.sha256, dict_SIH.csv
```

## Step 3 — Run the schema explorer (small, fast)

Once Step 2 completes, the explorer can run against the bucket-mounted
copy without re-downloading:

```bash
hf jobs uv run scripts/jobs/explore_fiocruz_sih.py \
    --secrets HF_TOKEN \
    --flavor cpu-basic
```

The explorer reports:
- Number of inner files in the ZIP
- Filename pattern (so we know how to filter by year)
- Sample column list from one CSV (so we can map to existing
  `sih_municipal` schema)
- Year range covered

Wallclock: ~5 minutes. Use the report to write the real processing job.

## Step 4 — Process FIOCRUZ → parquet → bucket (TODO Phase 12)

Not yet written — needs the explorer output from Step 3 to confirm
column names. Will be added at `scripts/jobs/process_fiocruz_to_parquet.py`
once Step 3 returns the schema.

Expected shape:
- Stream-extract per inner CSV from `/data/raw/sih/ETLSIH.zip`
- Filter to years 2015-2023
- Aggregate to (cod_ibge_6, year) level matching the existing
  `sih_municipal` schema in the canonical DuckDB
- Write `/data/processed/sih_fiocruz.parquet`
- Optionally upload to `mmrech/icskg-br-processed` HF Dataset under
  `source_tables/sih_fiocruz.parquet` so the publish/fetch pipeline
  can use it as a drop-in replacement for the pysus-derived `sih_raw`

## Step 5 — Update ICSKG to use FIOCRUZ source (TODO Phase 12)

Once `sih_fiocruz.parquet` exists in the bucket and/or HF Dataset:

1. Switch `database/build_database_v3.py` to read from FIOCRUZ-shaped
   parquet instead of pysus-extracted DBC files
2. Drop `pysus` from `pyproject.toml` dependencies
3. Re-lock — all 5 pysus-blocked Dependabot CVEs disappear
4. Re-publish HF Dataset as v0.2.0 (or v0.1.1 if scope is unchanged)
5. Re-trigger CI fetcher workflow to verify

## Files in this directory

- `README.md` — this file
- `explore_fiocruz_sih.py` — Step 3 explorer script (UV inline deps,
  ready to submit via `hf jobs uv run` once credits land)
- `process_fiocruz_to_parquet.py` — Step 4 processor (NOT YET WRITTEN)

## Why not just download locally?

Tried. The user's local SSD has ~350 MB free vs the 31 GB ZIP — 100x
storage gap. Even on a fully-clean disk, downloading 31 GB through a
home internet connection takes 30-90 min and saturates upload bandwidth.
The whole point of the bucket+jobs combo is to bypass local disk
entirely. Don't deviate from this architecture.

## Why not GitHub Actions?

GitHub-hosted runners have ~14 GB free disk on standard images — not
enough for 31 GB. Larger runners are paid. HF Jobs is the cleanest
single-vendor path here.
