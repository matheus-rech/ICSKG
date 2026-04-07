"""
ICSKG-BR HuggingFace Dataset Publisher
========================================
Convert the canonical NAS DuckDB exports of ICSKG-BR into a versioned
parquet tree and publish to a HuggingFace Dataset repository.

This is the publish-side of the Phase 11 reproducibility refactor.
The canonical processed-data store moves from `/Volumes/home/DataLake/30_models/
icskg_br/*.duckdb` (NAS-only, ~516 MB) to a versioned HF Dataset
(default: `matheus-rech/icskg-br-processed`) so that GitHub Actions
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

DEFAULT_REPO_ID = "matheus-rech/icskg-br-processed"
DEFAULT_SOURCE_DUCKDB = Path(
    "/Volumes/home/DataLake/30_models/icskg_br/icskg_br_export.duckdb"
)
SCHEMA_VERSION = "1.0"

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
        HF dataset repo id (e.g., "matheus-rech/icskg-br-processed").
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
        HF dataset repo id (e.g., "matheus-rech/icskg-br-processed").
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
            logger.warning(
                "Tag %s already exists on %s — skipping create_tag (idempotent)",
                dataset_version, repo_id,
            )
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
