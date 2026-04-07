"""
ICSKG-BR HuggingFace Dataset Publisher
========================================
Convert the canonical NAS DuckDB exports of ICSKG-BR into a versioned
parquet tree and publish to a HuggingFace Dataset repository.

This is the publish-side of the Phase 11 reproducibility refactor.
The canonical processed-data store moves from `/Volumes/home/DataLake/30_models/
icskg_br/*.duckdb` (NAS-only, ~516 MB) to a versioned HF Dataset
(default: `mmrech/icskg-br-processed`) so that GitHub Actions
runners and BMJ Global Health peer reviewers can reproduce the build
without NAS access.

The publish flow is:

  1. Open the source DuckDB read-only
  2. Enumerate base tables (skip views, log skipped)
  3. Assign each table to a namespace ("panel", "dimensions", "lcogs",
     "source_tables") via NAMESPACE_RULES
  4. COPY each table to a parquet file under
     {working_dir}/{namespace}/{table_name}.parquet with zstd6 compression
  5. Compute SHA256 + row count + schema for each parquet
  6. Build manifest.json with totals + source DuckDB SHA256
  7. Generate a Dataset Card README.md with YAML frontmatter
  8. (optional) upload via huggingface_hub.HfApi.upload_folder
  9. (optional) tag the revision via HfApi.create_tag

Usage
-----
    # Dry run (no upload, just convert + write manifest locally):
    python -m scripts.publish_to_hf \
        --source-duckdb /Volumes/home/DataLake/30_models/icskg_br/icskg_br_export.duckdb \
        --version v0.1.0 \
        --dry-run

    # Real publish (private dataset):
    python -m scripts.publish_to_hf \
        --source-duckdb /Volumes/home/DataLake/30_models/icskg_br/icskg_br_export.duckdb \
        --version v0.1.0 \
        --private

Authentication
--------------
Reads HF token from (in order):
  1. HF_TOKEN environment variable
  2. ~/.cache/huggingface/token (set via `huggingface-cli login`)
  3. huggingface_hub.HfFolder.get_token()

A write-scoped token is required for publish; dry runs need no auth.

Outputs
-------
  {working_dir}/{namespace}/{table_name}.parquet — one parquet per table
  {working_dir}/manifest.json                    — full manifest with SHA256s
  {working_dir}/README.md                        — auto-generated Dataset Card
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

logger = logging.getLogger(__name__)

# Whitelist for DuckDB table names — refuses anything that contains characters
# requiring escaping. The canonical ICSKG-BR DuckDB only contains ASCII
# snake_case table names; this is defense-in-depth against a future ETL bug
# producing a weird name that would corrupt the COPY SQL string.
_DUCKDB_IDENT_RE: re.Pattern[str] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_REPO_ID = "mmrech/icskg-br-processed"
DEFAULT_SOURCE_DUCKDB = Path(
    "/Volumes/home/DataLake/30_models/icskg_br/icskg_br_export.duckdb"
)
# Schema version 1.1 — adds the derived panel/municipal_health.parquet table
# (ICSKG-BR Technical Cookbook v1.0 §5 unified panel) to the export.  See
# derive_municipal_health_panel() below for the merge implementation.
SCHEMA_VERSION = "1.1"

# Canonical panel invariants (cookbook §5.1, §2.3)
EXPECTED_PANEL_ROWS = 50130  # 5,570 municipalities × 9 years (2015-2023)
PANEL_YEAR_RANGE = (2015, 2024)  # half-open: [2015, 2024) = 2015..2023

# Cookbook §5 sources that are PRESENT in the current source DuckDB
COOKBOOK_SOURCES_PRESENT = (
    "IBGE population master (§3.3)",
    "DATASUS SIH surgical aggregates (§3.1)",
    "DATASUS CNES SAO + bellwether (§3.2)",
    "IBGE SIDRA GDP (§3.3)",
    "Atlas Brasil HDI (§3.4)",
    "FIRJAN IFGF (§3.5)",
    "ANS TABNET insurance (§3.9)",
    "Census 2022 sanitation (§3.8 partial)",
    "Mobility (vehicle fleet)",
)

# Cookbook §5 sources that are DEFERRED to v0.2 — extractors not yet built
COOKBOOK_SOURCES_DEFERRED = (
    "ANATEL broadband (§3.6) — needed for CUDS Technology dimension",
    "RAIS employment (§3.7) — needed for CUDS Economy/Workforce dimension",
    "SNIS sanitation proper (§3.8) — Census 2022 is a partial proxy",
    "SIOPS health spending (§3.10) — needed for CUDS Governance dimension",
    "International comparators (§3.11) — WHO/World Bank/UNDP",
    "CUDS composite + dimension scores (§6) — blocked by missing sources above",
)

# Namespace assignment rules — substring match against table_name (lowercased).
# Order matters: first match wins. Falls through to "source_tables".
NAMESPACE_RULES: list[tuple[str, str]] = [
    ("dimension_score", "dimensions"),
    ("dimension_metadata", "panel"),
    ("cuds", "dimensions"),
    ("lcogs", "lcogs"),
    ("municipal_health", "panel"),
    ("municipality_lookup", "panel"),
    ("validation_report", "panel"),
    ("imputation_log", "panel"),
    ("deflation_log", "panel"),
]

VALID_NAMESPACES = {"panel", "dimensions", "lcogs", "source_tables"}

# Files to upload to HF (everything else is local working data)
UPLOAD_PATTERNS = ["**/*.parquet", "manifest.json", "README.md"]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    """Compute the SHA256 hex digest of a file in 1 MB chunks."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _utc_now_iso() -> str:
    """Return current UTC time as an ISO 8601 string ending in Z."""
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _resolve_hf_token(explicit: str | None = None) -> str | None:
    """Resolve the HuggingFace token from explicit arg, env, or cached file.

    Returns None if no token found (caller decides whether to require auth).
    """
    if explicit:
        return explicit
    env_token = os.environ.get("HF_TOKEN")
    if env_token:
        return env_token
    try:
        from huggingface_hub import HfFolder  # noqa: PLC0415

        return HfFolder.get_token()
    except Exception as exc:  # noqa: BLE001
        logger.debug("HfFolder.get_token failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def derive_municipal_health_panel(
    conn: "duckdb.DuckDBPyConnection",
    working_dir: Path,
    *,
    compression_level: int = 6,
) -> dict[str, Any]:
    """Derive the canonical panel/municipal_health.parquet (cookbook §5).

    The ICSKG-BR Technical Cookbook v1.0 §5 (Merge Pipeline) specifies that
    the final unified panel — referenced in code as
    `panel/municipal_health.parquet` and in the cookbook as
    `icskg_br_unified_panel.parquet` — is the LEFT JOIN of all source tables
    onto a 5,570 × 9 = 50,130-row municipality-year spine.

    The canonical NAS DuckDB does not yet contain this table as a base table;
    it must be derived at publish time from the source tables.  This function
    runs the cookbook §5 merge in DuckDB SQL and writes the result to
    `{working_dir}/panel/municipal_health.parquet`.

    Cookbook source coverage (v0.1.0):
        See COOKBOOK_SOURCES_PRESENT and COOKBOOK_SOURCES_DEFERRED at the
        top of this module.  v0.1.0 ships the LCoGS-side panel; ANATEL,
        RAIS, SNIS-proper, SIOPS, and the international comparators are
        deferred to v0.2.0 because their extractors are not yet built.

    Returns
    -------
    dict
        A `tables_out`-compatible entry: ``{namespace, table, parquet_path,
        row_count, column_count, schema, sha256, size_bytes}``.  Append this
        to the manifest's tables list so the fetcher's verify step picks it
        up automatically.

    Raises
    ------
    RuntimeError
        If the resulting row count != 50,130 (publication-blocking
        invariant from cookbook §5.2 Validate step).
    """
    panel_dir = working_dir / "panel"
    panel_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = panel_dir / "municipal_health.parquet"

    # Cookbook §5.1 merge order, implemented in DuckDB SQL.
    # SIH and SAO workforce are MONTHLY in the source DuckDB; we aggregate to
    # year-level (sum for counts, avg for rates) so the panel stays one row
    # per municipality-year.  Time-invariant tables (sanitation, mobility,
    # municipality metadata) are broadcast across years via the spine.
    panel_sql = """
    WITH spine AS (
      -- §5.1 step 1: "Start: IBGE population master (5,570 × 9 years =
      -- 50,130 municipality-year rows)".  The cookbook explicitly defines
      -- the population table as the canonical spine.  Using municipalities
      -- here introduces a phantom 5,571st row (likely an aggregate or
      -- centro de povoado) and produces 50,139 rows — fails the invariant.
      SELECT
        p.cod_ibge,
        m.cod_ibge_6,
        p.year
      FROM population p
      LEFT JOIN municipalities m USING (cod_ibge)
    ),
    sih_year AS (
      -- §5.1 step 2: SIH surgical aggregates (cookbook says cod_ibge_6, year)
      -- Source is monthly; aggregate to year level.
      SELECT
        cod_ibge_6,
        year,
        SUM(total_procedures) AS sih_procedures_year,
        SUM(deaths) AS sih_deaths_year,
        AVG(pomr_pct) AS sih_pomr_pct,
        AVG(avg_cost_brl) AS sih_avg_cost_brl,
        AVG(avg_days) AS sih_avg_days
      FROM sih_municipal
      GROUP BY cod_ibge_6, year
    ),
    sao_year AS (
      -- §5.1 step 3: CNES SAO/bellwether (cookbook says cod_ibge_6, year)
      -- Source is monthly; aggregate to year level.
      SELECT
        cod_ibge_6,
        year,
        AVG(total_sao) AS sao_total_year,
        AVG(surgeons) AS sao_surgeons_year,
        AVG(anesthesiologists) AS sao_anesth_year,
        AVG(obstetricians) AS sao_obstetricians_year,
        AVG(sao_per_100k) AS sao_per_100k_year
      FROM sao_workforce
      GROUP BY cod_ibge_6, year
    )
    SELECT
      -- Spine identity columns (join keys)
      s.cod_ibge,
      s.cod_ibge_6,
      s.year,
      -- Municipality metadata (broadcast time-invariant)
      m.nome AS municipality_name,
      m.uf,
      m.regiao AS macro_region,
      m.lat,
      m.lon,
      m.capital,
      m.area_km2,
      m.pop_density AS population_density_2022,
      -- §5.1 step 1 + IBGE population (per-year)
      p.population,
      -- §5.1 step 4: IBGE GDP
      g.gdp_total_brl_1000,
      g.gdp_per_capita_brl,
      -- §5.1 step 6: FIRJAN IFGF (joined via cod_ibge_6)
      f.ifgf_geral,
      f.ifgf_autonomia,
      f.ifgf_gastos_pessoal,
      f.ifgf_liquidez,
      f.ifgf_investimentos,
      -- §5.1 step 5: Atlas Brasil HDI (cookbook says time-invariant; we
      -- have a time-varying idhm table, use it directly)
      h.idhm,
      h.idhm_educacao,
      h.idhm_longevidade,
      h.idhm_renda,
      -- §5.1 step 10: ANS insurance (joined via cod_ibge_6)
      a.benef_medica,
      a.cobertura_medica_pct,
      a.sus_dependence_pct AS SUS_dependence,
      -- Census 2022 sanitation (broadcast time-invariant; partial proxy
      -- for the cookbook's §5.1 step 9 SNIS data which is deferred to v0.2)
      san.esgoto_pct,
      san.agua_pct,
      -- Mobility (broadcast time-invariant)
      mb.total_veiculos AS mobility_veiculos,
      mb.veiculos_per_1000,
      -- §5.1 step 2: SIH surgical aggregates (joined via cod_ibge_6, year)
      sh.sih_procedures_year,
      sh.sih_deaths_year,
      sh.sih_pomr_pct,
      sh.sih_avg_cost_brl,
      sh.sih_avg_days,
      -- §5.1 step 3: CNES SAO workforce (joined via cod_ibge_6, year)
      sw.sao_total_year,
      sw.sao_surgeons_year,
      sw.sao_anesth_year,
      sw.sao_obstetricians_year,
      sw.sao_per_100k_year,
      -- §5.1 step 12 derived columns (already computed in v_lcogs_panel)
      lc.dist_nearest_bellwether_km AS bellwether_access_km,
      lc.lcogs1_access,
      lc.bellwether_count_50km,
      lc.bellwether_count_100km,
      lc.lcogs2_sao_density AS SAO_density,
      lc.lcogs2_meets_target,
      lc.lcogs3_surg_volume_100k AS surgical_volume,
      lc.lcogs3_meets_target,
      lc.lcogs4_pomr AS POMR
    FROM spine s
    LEFT JOIN municipalities m USING (cod_ibge)
    LEFT JOIN population p USING (cod_ibge, year)
    LEFT JOIN gdp g USING (cod_ibge, year)
    LEFT JOIN ifgf f ON f.cod_ibge_6 = s.cod_ibge_6 AND f.year = s.year
    LEFT JOIN idhm h USING (cod_ibge, year)
    LEFT JOIN ans_cobertura a ON a.cod_ibge_6 = s.cod_ibge_6 AND a.year = s.year
    LEFT JOIN censo2022_saneamento san USING (cod_ibge)
    LEFT JOIN mobility mb ON mb.cod_ibge_6 = s.cod_ibge_6
    LEFT JOIN sih_year sh ON sh.cod_ibge_6 = s.cod_ibge_6 AND sh.year = s.year
    LEFT JOIN sao_year sw ON sw.cod_ibge_6 = s.cod_ibge_6 AND sw.year = s.year
    LEFT JOIN v_lcogs_panel lc USING (cod_ibge, year)
    ORDER BY s.cod_ibge, s.year
    """

    escaped_path = str(parquet_path).replace("'", "''")
    copy_sql = (
        "COPY (%s) TO '%s' "
        "(FORMAT PARQUET, COMPRESSION ZSTD, "
        "COMPRESSION_LEVEL %d, ROW_GROUP_SIZE 100000)"
        % (panel_sql, escaped_path, compression_level)
    )
    conn.execute(copy_sql)

    # Cookbook §5.2 Validate step: assert exact row count + no duplicates
    row_count = conn.execute(
        "SELECT COUNT(*) FROM read_parquet('%s')" % escaped_path
    ).fetchone()[0]
    if row_count != EXPECTED_PANEL_ROWS:
        raise RuntimeError(
            "municipal_health row count invariant violated: got %d, expected %d. "
            "Cookbook §5.2 requires exactly %d rows (5,570 mun × 9 years). "
            "Either the spine is wrong or a join introduced duplicates."
            % (row_count, EXPECTED_PANEL_ROWS, EXPECTED_PANEL_ROWS)
        )
    dup_count = conn.execute(
        "SELECT COUNT(*) FROM ("
        "  SELECT cod_ibge, year, COUNT(*) AS n "
        "  FROM read_parquet('%s') "
        "  GROUP BY cod_ibge, year HAVING n > 1)"
        % escaped_path
    ).fetchone()[0]
    if dup_count > 0:
        raise RuntimeError(
            "municipal_health has %d duplicate (cod_ibge, year) pairs — "
            "cookbook §5.2 forbids duplicates" % dup_count
        )

    schema_rows = conn.execute(
        "DESCRIBE SELECT * FROM read_parquet('%s')" % escaped_path
    ).fetchall()
    schema = [
        {"name": r[0], "type": r[1], "nullable": True}
        for r in schema_rows
    ]

    sha256 = _sha256_file(parquet_path)
    size_bytes = parquet_path.stat().st_size

    logger.info(
        "  ✓ %-40s [%s] %d rows, %d cols, %.2f KB (cookbook §5)",
        "municipal_health", "panel", row_count, len(schema), size_bytes / 1024,
    )

    return {
        "namespace": "panel",
        "table": "municipal_health",
        "parquet_path": "panel/municipal_health.parquet",
        "row_count": int(row_count),
        "column_count": len(schema),
        "schema": schema,
        "sha256": sha256,
        "size_bytes": size_bytes,
        "derived_from": "cookbook §5 merge pipeline",
    }


def assign_namespace(table_name: str) -> str:
    """Assign a parquet namespace to a DuckDB table by name substring match.

    Parameters
    ----------
    table_name : str
        DuckDB base table name (case-insensitive matching).

    Returns
    -------
    str
        One of "panel", "dimensions", "lcogs", "source_tables".
    """
    lower = table_name.lower()
    for substr, ns in NAMESPACE_RULES:
        if substr in lower:
            return ns
    return "source_tables"


def duckdb_to_parquet_tree(
    source_duckdb: Path,
    working_dir: Path,
    *,
    compression_level: int = 6,
) -> dict[str, Any]:
    """Convert all base tables from a DuckDB file to a namespaced parquet tree.

    Parameters
    ----------
    source_duckdb : Path
        Path to the source DuckDB file (opened read-only).
    working_dir : Path
        Output directory for the parquet tree (will be created).
    compression_level : int
        zstd compression level (1-22). Default 6.

    Returns
    -------
    dict
        {
            "tables": [{"namespace", "table", "parquet_path", "row_count",
                        "column_count", "schema", "sha256", "size_bytes"}],
            "skipped_views": [{"name", "reason"}],
            "compression_level": int,
        }
    """
    source_duckdb = Path(source_duckdb)
    working_dir = Path(working_dir)
    if not source_duckdb.exists():
        raise FileNotFoundError(
            "Source DuckDB not found: %s" % source_duckdb
        )

    working_dir.mkdir(parents=True, exist_ok=True)
    logger.info("─" * 70)
    logger.info(
        "Converting DuckDB to parquet tree: %s -> %s",
        source_duckdb, working_dir,
    )
    logger.info("─" * 70)

    conn = duckdb.connect(str(source_duckdb), read_only=True)
    try:
        rows = conn.execute(
            "SELECT table_name, table_type "
            "FROM information_schema.tables "
            "WHERE table_schema = 'main' "
            "ORDER BY table_name"
        ).fetchall()

        tables_out: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []

        for table_name, table_type in rows:
            if table_type != "BASE TABLE":
                skipped.append(
                    {"name": table_name, "reason": "not a BASE TABLE (type=%s)" % table_type}
                )
                logger.info(
                    "Skipping %s (%s — only base tables exported)",
                    table_name, table_type,
                )
                continue

            # Defense-in-depth: refuse any table whose name doesn't fit the
            # safe identifier pattern. The canonical ICSKG-BR DuckDB never
            # produces such names, but a future ETL bug could.
            if not _DUCKDB_IDENT_RE.match(table_name):
                skipped.append(
                    {"name": table_name, "reason": "unsafe identifier — refused"}
                )
                logger.warning(
                    "Skipping table %r (does not match %s)",
                    table_name, _DUCKDB_IDENT_RE.pattern,
                )
                continue

            namespace = assign_namespace(table_name)
            ns_dir = working_dir / namespace
            ns_dir.mkdir(parents=True, exist_ok=True)
            parquet_path = ns_dir / ("%s.parquet" % table_name)

            # Escape any single quote in the parquet path for the SQL literal.
            # On a sanely-named filesystem this is a no-op, but a path like
            # /Users/o'brien/... would otherwise break the COPY statement.
            escaped_path = str(parquet_path).replace("'", "''")
            copy_sql = (
                'COPY (SELECT * FROM "%s") TO \'%s\' '
                "(FORMAT PARQUET, COMPRESSION ZSTD, "
                "COMPRESSION_LEVEL %d, ROW_GROUP_SIZE 100000)"
                % (table_name, escaped_path, compression_level)
            )
            conn.execute(copy_sql)

            row_count = conn.execute(
                'SELECT COUNT(*) FROM "%s"' % table_name
            ).fetchone()[0]
            schema_rows = conn.execute(
                'DESCRIBE "%s"' % table_name
            ).fetchall()
            schema = [
                {"name": r[0], "type": r[1], "nullable": r[2] == "YES"}
                for r in schema_rows
            ]

            sha256 = _sha256_file(parquet_path)
            size_bytes = parquet_path.stat().st_size

            entry = {
                "namespace": namespace,
                "table": table_name,
                "parquet_path": "%s/%s.parquet" % (namespace, table_name),
                "row_count": int(row_count),
                "column_count": len(schema),
                "schema": schema,
                "sha256": sha256,
                "size_bytes": size_bytes,
            }
            tables_out.append(entry)
            logger.info(
                "  ✓ %-40s [%s] %d rows, %d cols, %.2f KB",
                table_name, namespace, row_count, len(schema), size_bytes / 1024,
            )

        # Derive the canonical municipal_health panel (cookbook §5).
        # This is computed from the base tables we just exported, not stored
        # in the source DuckDB.  See derive_municipal_health_panel docstring.
        # Only derive if the required source tables are present — if any are
        # missing, log a warning and skip rather than crashing the publish.
        required_for_panel = {
            "municipalities", "population", "gdp", "ifgf", "idhm",
            "ans_cobertura", "censo2022_saneamento", "mobility",
            "sih_municipal", "sao_workforce", "v_lcogs_panel",
        }
        present_table_names = {t["table"] for t in tables_out}
        missing = required_for_panel - present_table_names
        if missing:
            logger.warning(
                "Skipping municipal_health derivation — missing source tables: %s",
                sorted(missing),
            )
        else:
            try:
                panel_entry = derive_municipal_health_panel(
                    conn, working_dir, compression_level=compression_level,
                )
                tables_out.append(panel_entry)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Failed to derive municipal_health panel: %s", exc,
                )
                raise
    finally:
        conn.close()

    logger.info(
        "Conversion done: %d tables exported, %d skipped",
        len(tables_out), len(skipped),
    )
    return {
        "tables": tables_out,
        "skipped_views": skipped,
        "compression_level": compression_level,
    }


def build_manifest(
    source_duckdb: Path,
    conversion_result: dict[str, Any],
    dataset_name: str,
    dataset_version: str,
) -> dict[str, Any]:
    """Build the manifest.json structure for the parquet tree.

    Parameters
    ----------
    source_duckdb : Path
        Source DuckDB file path (used for SHA256 + size).
    conversion_result : dict
        Output of duckdb_to_parquet_tree().
    dataset_name : str
        HF dataset repo id (e.g., "mmrech/icskg-br-processed").
    dataset_version : str
        Semantic version tag (e.g., "v0.1.0").

    Returns
    -------
    dict
        Full manifest dict ready to be json.dumps'd.
    """
    source_duckdb = Path(source_duckdb)
    tables = conversion_result["tables"]

    manifest = {
        "dataset_name": dataset_name,
        "dataset_version": dataset_version,
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now_iso(),
        "source_duckdb": {
            "name": source_duckdb.name,
            "sha256": _sha256_file(source_duckdb),
            "size_bytes": source_duckdb.stat().st_size,
        },
        "compression": {
            "format": "parquet",
            "codec": "zstd",
            "level": conversion_result["compression_level"],
            "row_group_size": 100000,
        },
        "tables": tables,
        "skipped_views": conversion_result["skipped_views"],
        "totals": {
            "table_count": len(tables),
            "row_count": sum(t["row_count"] for t in tables),
            "size_bytes_compressed": sum(t["size_bytes"] for t in tables),
        },
    }
    return manifest


def generate_dataset_card(manifest: dict[str, Any]) -> str:
    """Generate a HuggingFace Dataset Card README.md from a manifest.

    Returns a markdown string with YAML frontmatter ready to write to
    `{working_dir}/README.md`.
    """
    totals = manifest["totals"]
    tables_by_ns: dict[str, list[dict[str, Any]]] = {}
    for t in manifest["tables"]:
        tables_by_ns.setdefault(t["namespace"], []).append(t)

    frontmatter = (
        "---\n"
        "license: cc-by-4.0\n"
        "language:\n"
        "- pt\n"
        "- en\n"
        "pretty_name: ICSKG-BR Processed Data\n"
        "size_categories:\n"
        "- 10K<n<100K\n"
        "tags:\n"
        "- global-surgery\n"
        "- urban-development\n"
        "- brazil\n"
        "- epidemiology\n"
        "- lcogs\n"
        "- cimi\n"
        "- panel-data\n"
        "- datasus\n"
        "---\n\n"
    )

    body_lines: list[str] = [
        "# ICSKG-BR: Index of Cities' Smartness & Knowledge for Global Surgery — Brazil",
        "",
        "Processed data layer for the ICSKG-BR longitudinal ecological panel study.",
        "Cross-references the IESE Cities in Motion Index (CIMI) urban development",
        "framework against Lancet Commission on Global Surgery (LCoGS) indicators",
        "across all 5,570 Brazilian municipalities (2015-2023).",
        "",
        "**This dataset is currently private during the BMJ Global Health pre-submission",
        "window. It will become public (CC-BY-4.0) upon publication.**",
        "",
        "## Provenance",
        "",
        "- Source code: https://github.com/matheus-rech/ICSKG",
        "- Dataset version: `%s`" % manifest["dataset_version"],
        "- Schema version: `%s`" % manifest["schema_version"],
        "- Generated at: `%s`" % manifest["generated_at"],
        "- Source DuckDB: `%s` (sha256 `%s`)"
        % (manifest["source_duckdb"]["name"], manifest["source_duckdb"]["sha256"][:16]),
        "- Compression: `%s` level `%d`"
        % (manifest["compression"]["codec"], manifest["compression"]["level"]),
        "",
        "## Cookbook scope (v0.1.0)",
        "",
        "This release implements the **LCoGS-side** of the ICSKG-BR Technical",
        "Cookbook v1.0 (March 2026).  The canonical `panel/municipal_health.parquet`",
        "is derived at publish time from the source tables via the cookbook §5",
        "merge pipeline (50,130 rows = 5,570 mun × 9 years, 49 columns).",
        "",
        "**Cookbook §3 sources INCLUDED in v0.1.0:**",
        "",
        *("- " + s for s in COOKBOOK_SOURCES_PRESENT),
        "",
        "**DEFERRED to v0.2.0** (extractors not yet built — see project phase 12):",
        "",
        *("- " + s for s in COOKBOOK_SOURCES_DEFERRED),
        "",
        "The v0.2.0 release will add the missing 5 extractors and the cookbook §6",
        "CUDS composite (PCA weighting + geometric mean aggregation), and will",
        "move the `municipal_health` derivation into the build pipeline so it's",
        "stored as a base table in the source DuckDB instead of being computed",
        "at publish time.",
        "",
        "## Totals",
        "",
        "| Metric | Value |",
        "|---|---|",
        "| Tables | %d |" % totals["table_count"],
        "| Total rows | %s |" % f"{totals['row_count']:,}",
        "| Compressed size | %.2f MB |" % (totals["size_bytes_compressed"] / 1024 / 1024),
        "",
        "## Tables by namespace",
        "",
    ]

    for ns in ("panel", "dimensions", "lcogs", "source_tables"):
        if ns not in tables_by_ns:
            continue
        body_lines.append("### `%s/`" % ns)
        body_lines.append("")
        body_lines.append("| Table | Rows | Columns | Size |")
        body_lines.append("|---|---|---|---|")
        for t in sorted(tables_by_ns[ns], key=lambda x: x["table"]):
            body_lines.append(
                "| `%s` | %s | %d | %.2f KB |"
                % (
                    t["table"],
                    f"{t['row_count']:,}",
                    t["column_count"],
                    t["size_bytes"] / 1024,
                )
            )
        body_lines.append("")

    body_lines.extend(
        [
            "## Loading",
            "",
            "```python",
            "from huggingface_hub import snapshot_download",
            "import duckdb",
            "",
            "local = snapshot_download(",
            "    repo_id='%s'," % manifest["dataset_name"],
            "    repo_type='dataset',",
            "    revision='%s'," % manifest["dataset_version"],
            "    allow_patterns=['**/*.parquet', 'manifest.json'],",
            ")",
            "",
            "# Read the main panel directly:",
            "panel = duckdb.sql(f\"SELECT * FROM '{local}/panel/municipal_health.parquet'\").df()",
            "```",
            "",
            "## Citation",
            "",
            "If you use this dataset, please cite the project:",
            "",
            "```",
            "Rech, Matheus M. (2026). ICSKG-BR: Index of Cities' Smartness & Knowledge",
            "for Global Surgery — Brazil. https://github.com/matheus-rech/ICSKG",
            "```",
            "",
            "Production Zenodo DOI will be minted at BMJ acceptance.",
            "",
            "## License",
            "",
            "Source data is public under Brazilian Lei de Acesso à Informação",
            "(Law 12.527/2011). This processed dataset is released under CC-BY-4.0",
            "after BMJ Global Health publication.",
        ]
    )

    return frontmatter + "\n".join(body_lines) + "\n"


def publish_to_hf(
    working_dir: Path,
    repo_id: str,
    dataset_version: str,
    commit_message: str,
    *,
    private: bool = True,
    dry_run: bool = False,
    hf_token: str | None = None,
) -> str:
    """Upload a parquet tree + manifest + README to a HuggingFace Dataset.

    Idempotent: re-running with the same revision creates a new commit
    on HF main but the create_tag call is wrapped in try/except so the
    tag doesn't get duplicated.

    Parameters
    ----------
    working_dir : Path
        Local directory containing the parquet tree, manifest.json, README.md.
    repo_id : str
        HF dataset repo id (e.g., "mmrech/icskg-br-processed").
    dataset_version : str
        Tag name to create after upload (e.g., "v0.1.0").
    commit_message : str
        HF commit message for upload_folder.
    private : bool
        Create the repo as private if it doesn't exist.
    dry_run : bool
        If True, log the upload plan and return without making API calls.
    hf_token : str | None
        Explicit token; otherwise resolved from env or cache.

    Returns
    -------
    str
        URL to the published dataset revision (or "dry-run" if dry_run).
    """
    working_dir = Path(working_dir)

    if dry_run:
        logger.info("─" * 70)
        logger.info("[dry-run] Would upload to HF: %s @ %s", repo_id, dataset_version)
        logger.info("[dry-run] Folder: %s", working_dir)
        logger.info("[dry-run] Private: %s", private)
        logger.info("[dry-run] Patterns: %s", UPLOAD_PATTERNS)
        logger.info("[dry-run] Commit message: %s", commit_message)
        logger.info("─" * 70)
        return "dry-run"

    token = _resolve_hf_token(hf_token)
    if not token:
        raise RuntimeError(
            "No HuggingFace token found. Run `huggingface-cli login` "
            "or set HF_TOKEN env var before publishing."
        )

    # Lazy import so dry runs and unit tests don't need huggingface_hub
    from huggingface_hub import HfApi  # noqa: PLC0415
    from huggingface_hub.errors import HfHubHTTPError  # noqa: PLC0415

    api = HfApi(token=token)
    logger.info("─" * 70)
    logger.info("Publishing to HF: %s @ %s", repo_id, dataset_version)
    logger.info("─" * 70)

    api.create_repo(
        repo_id=repo_id,
        repo_type="dataset",
        private=private,
        exist_ok=True,
    )
    logger.info("Repo ensured: %s (private=%s)", repo_id, private)

    api.upload_folder(
        folder_path=str(working_dir),
        repo_id=repo_id,
        repo_type="dataset",
        commit_message=commit_message,
        allow_patterns=UPLOAD_PATTERNS,
    )
    logger.info("Folder uploaded: %s", working_dir)

    try:
        api.create_tag(
            repo_id=repo_id,
            tag=dataset_version,
            repo_type="dataset",
            revision="main",
        )
        logger.info("Tag created: %s", dataset_version)
    except HfHubHTTPError as exc:
        if "already exists" in str(exc).lower() or "409" in str(exc):
            # Tag already exists at the OLD HEAD.  Force-move it to the new
            # HEAD on main so the revision pointer matches what we just
            # uploaded.  Without this, the fetcher silently downloads the
            # stale revision and can hit "missing file" errors that look
            # like the upload failed when it actually succeeded.
            logger.warning(
                "Tag %s already exists on %s — deleting and re-creating "
                "at current main HEAD (force-update for re-publish)",
                dataset_version, repo_id,
            )
            api.delete_tag(
                repo_id=repo_id,
                tag=dataset_version,
                repo_type="dataset",
            )
            api.create_tag(
                repo_id=repo_id,
                tag=dataset_version,
                repo_type="dataset",
                revision="main",
            )
            logger.info("Tag re-created: %s -> main HEAD", dataset_version)
        else:
            raise

    url = "https://huggingface.co/datasets/%s/tree/%s" % (repo_id, dataset_version)
    logger.info("Published: %s", url)
    return url


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the publish flow."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Publish ICSKG-BR processed data to HuggingFace Datasets",
    )
    parser.add_argument(
        "--source-duckdb",
        type=Path,
        default=DEFAULT_SOURCE_DUCKDB,
        help="Path to the source DuckDB file (default: NAS canonical export)",
    )
    parser.add_argument(
        "--repo-id",
        default=DEFAULT_REPO_ID,
        help="HuggingFace dataset repo id",
    )
    parser.add_argument(
        "--version",
        required=True,
        help="Semantic version tag (e.g., v0.1.0)",
    )
    parser.add_argument(
        "--working-dir",
        type=Path,
        default=None,
        help="Local working dir (default: ~/.cache/icskg-publish/{version})",
    )
    parser.add_argument(
        "--private",
        action="store_true",
        default=True,
        help="Create the dataset as private (default)",
    )
    parser.add_argument(
        "--public",
        action="store_false",
        dest="private",
        help="Create the dataset as public (overrides --private)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Convert + write manifest locally but skip HF upload",
    )
    parser.add_argument(
        "--compression-level",
        type=int,
        default=6,
        help="zstd compression level for parquet (1-22, default 6)",
    )
    args = parser.parse_args(argv)

    working_dir = args.working_dir or (
        Path.home() / ".cache" / "icskg-publish" / args.version
    )

    # Step 1: Convert DuckDB → parquet tree
    conversion = duckdb_to_parquet_tree(
        source_duckdb=args.source_duckdb,
        working_dir=working_dir,
        compression_level=args.compression_level,
    )

    # Step 2: Build manifest
    manifest = build_manifest(
        source_duckdb=args.source_duckdb,
        conversion_result=conversion,
        dataset_name=args.repo_id,
        dataset_version=args.version,
    )
    manifest_path = working_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    logger.info("Manifest written: %s", manifest_path)

    # Step 3: Generate dataset card
    readme = generate_dataset_card(manifest)
    readme_path = working_dir / "README.md"
    readme_path.write_text(readme)
    logger.info("Dataset card written: %s", readme_path)

    # Step 4: Publish (or dry-run)
    commit_message = "bootstrap %s from %s" % (
        args.version,
        manifest["source_duckdb"]["sha256"][:12],
    )
    url = publish_to_hf(
        working_dir=working_dir,
        repo_id=args.repo_id,
        dataset_version=args.version,
        commit_message=commit_message,
        private=args.private,
        dry_run=args.dry_run,
    )

    logger.info("─" * 70)
    logger.info("Done. URL: %s", url)
    logger.info("─" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
