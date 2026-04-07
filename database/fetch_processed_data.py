"""
ICSKG-BR HuggingFace Dataset Fetcher
======================================
Fetch the canonical pre-built ICSKG-BR processed dataset from HuggingFace
and verify its integrity locally.

This is the consume-side of the Phase 11 reproducibility refactor.
The publish-side (`scripts/publish_to_hf.py`) takes the user's NAS-only
DuckDB exports and uploads them to a versioned HuggingFace Dataset
(default: `matheus-rech/icskg-br-processed`). This module fetches that
dataset on github-hosted runners or peer reviewers' laptops with no
NAS access required.

Two distinct flows:

  1. **Verify** — fetch the parquet tree + manifest.json and check
     SHA256s + row counts against the manifest. Used by CI to confirm
     the published artifact is intact.

  2. **Materialize** — convert the fetched parquet tree into a fresh
     SQLite database for downstream consumers (analysis layer,
     replicators who prefer sqlite to parquet).

Architectural note
------------------
This module does NOT participate in the local build pipeline
(`database/build_database_v3.py`). The local build reads source-shape
parquets from `data_sources/processed/` and runs assemble_panel +
impute_ifgf + build_database to produce the database from scratch.
This module reads HF-shape parquets (per-namespace, aggregated tables)
and rebuilds a sqlite from them. The two flows are intentionally
separate to keep concerns clean.

Usage
-----
    # Verify-only (download + manifest verification)
    python -m database.fetch_processed_data \
        --revision v0.1.0 \
        --target-dir ~/.cache/icskg/hf-snapshots/v0.1.0

    # Verify + materialize to sqlite
    python -m database.fetch_processed_data \
        --revision v0.1.0 \
        --target-dir ~/.cache/icskg/hf-snapshots/v0.1.0 \
        --to database/icskg_br.sqlite
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_REPO_ID = "matheus-rech/icskg-br-processed"
DEFAULT_ALLOW_PATTERNS = ["**/*.parquet", "manifest.json", "README.md"]
DEFAULT_PANEL_PATH = "panel/municipal_health.parquet"
EXPECTED_FULL_PANEL_ROWS = 50130  # 5,570 municipalities × 9 years

# Whitelist for safe SQLite/identifier table names — prevents SQL injection via
# parquet basenames in materialize_sqlite. The HF dataset's tables are produced
# by scripts/publish_to_hf.py which only emits ASCII-named tables, but a
# tampered HF revision could ship a parquet whose stem is a SQL fragment.
_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


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


def _existing_manifest_matches(target_dir: Path, revision: str) -> bool:
    """Return True if target_dir already has a manifest.json matching revision."""
    manifest_path = target_dir / "manifest.json"
    if not manifest_path.exists():
        return False
    try:
        existing = json.loads(manifest_path.read_text())
        return existing.get("dataset_version") == revision
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(
            "Could not parse existing manifest at %s: %s -- will re-fetch",
            manifest_path, exc,
        )
        return False


def _validate_safe_relpath(rel_path: Any, base_dir: Path) -> Path:
    """Validate a manifest-supplied relative path and resolve it under base_dir.

    Rejects absolute paths, traversal segments (`..`), and any resolved path
    that escapes `base_dir`. Returns the resolved Path. Raises RuntimeError
    on any unsafe input.

    This is the trust boundary for manifest.json — every parquet path read
    from a manifest must pass through this function before being touched.
    """
    if not isinstance(rel_path, str) or not rel_path:
        raise RuntimeError(
            "Manifest entry has empty or non-string parquet_path: %r" % (rel_path,)
        )
    p = Path(rel_path)
    if p.is_absolute():
        raise RuntimeError(
            "Refusing absolute parquet_path from manifest: %r" % rel_path
        )
    if any(part in ("..", "") for part in p.parts):
        raise RuntimeError(
            "Refusing parquet_path with traversal segments: %r" % rel_path
        )
    base_resolved = base_dir.resolve()
    candidate = (base_dir / p).resolve()
    try:
        candidate.relative_to(base_resolved)
    except ValueError as exc:
        raise RuntimeError(
            "parquet_path escapes base directory: %r resolves outside %s"
            % (rel_path, base_resolved)
        ) from exc
    return candidate


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_processed_tree(
    repo_id: str,
    revision: str,
    target_dir: Path,
    *,
    hf_token: str | None = None,
    allow_patterns: list[str] | None = None,
    force_redownload: bool = False,
) -> Path:
    """Fetch a parquet tree + manifest.json from a HuggingFace Dataset.

    If `target_dir` already has a manifest.json with a matching dataset_version,
    the function returns immediately without re-downloading (cache hit).

    Parameters
    ----------
    repo_id : str
        HF dataset repo id (e.g., "matheus-rech/icskg-br-processed").
    revision : str
        Tag or commit SHA (e.g., "v0.1.0").
    target_dir : Path
        Local directory to materialize the snapshot into.
    hf_token : str | None
        Explicit HF token. Falls back to HF_TOKEN env or HfFolder cache.
    allow_patterns : list[str] | None
        Glob patterns to download. Defaults to parquet + manifest + README.
    force_redownload : bool
        If True, ignore the cache hit check.

    Returns
    -------
    Path
        target_dir, after the download is materialized.
    """
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    if not force_redownload and _existing_manifest_matches(target_dir, revision):
        logger.info(
            "Cache hit: %s already contains revision %s -- skipping download",
            target_dir, revision,
        )
        return target_dir

    token = _resolve_hf_token(hf_token)
    if not token:
        logger.warning(
            "No HF_TOKEN found; download may fail for private datasets"
        )

    from huggingface_hub import snapshot_download  # noqa: PLC0415

    logger.info("─" * 70)
    logger.info("Fetching %s @ %s -> %s", repo_id, revision, target_dir)
    logger.info("─" * 70)

    snapshot_download(
        repo_id=repo_id,
        repo_type="dataset",
        revision=revision,
        local_dir=str(target_dir),
        allow_patterns=allow_patterns or DEFAULT_ALLOW_PATTERNS,
        token=token,
    )

    logger.info("Snapshot materialized at %s", target_dir)
    return target_dir


def verify_manifest(local_dir: Path) -> dict[str, Any]:
    """Verify a fetched parquet tree against its manifest.json.

    For every entry in `manifest["tables"]`, this function:
      1. Confirms the parquet file exists at the recorded path
      2. Computes the SHA256 and compares against the recorded hash
      3. Reads the parquet metadata and confirms the row count matches

    Parameters
    ----------
    local_dir : Path
        Directory containing manifest.json and the parquet tree.

    Returns
    -------
    dict
        The parsed and verified manifest.

    Raises
    ------
    FileNotFoundError
        If manifest.json or any referenced parquet file is missing.
    RuntimeError
        On SHA256 mismatch or row count mismatch.
    """
    local_dir = Path(local_dir)
    manifest_path = local_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            "manifest.json not found at %s" % manifest_path
        )

    manifest = json.loads(manifest_path.read_text())
    tables = manifest.get("tables", [])

    if not tables:
        raise RuntimeError(
            "manifest.json at %s has no 'tables' entries -- "
            "this is not a valid ICSKG-BR processed dataset" % manifest_path
        )

    logger.info(
        "Verifying %d tables from manifest %s @ %s",
        len(tables),
        manifest.get("dataset_name", "?"),
        manifest.get("dataset_version", "?"),
    )

    # pyarrow.parquet for row count check (no full read)
    import pyarrow.parquet as pq  # noqa: PLC0415

    # Track listed paths so we can detect unlisted parquets after the loop.
    listed_paths: set[Path] = set()

    for entry in tables:
        rel_path = entry["parquet_path"]
        # Trust boundary: validate path BEFORE any filesystem touch.
        parquet_path = _validate_safe_relpath(rel_path, local_dir)
        listed_paths.add(parquet_path)

        if not parquet_path.exists():
            raise FileNotFoundError(
                "Parquet file referenced by manifest not found: %s" % parquet_path
            )

        # SHA256 check
        actual_sha = _sha256_file(parquet_path)
        expected_sha = entry["sha256"]
        if actual_sha != expected_sha:
            raise RuntimeError(
                "SHA256 mismatch for %s: expected %s, got %s "
                "(possible cache corruption or tampered file)"
                % (rel_path, expected_sha[:16], actual_sha[:16])
            )

        # Row count check
        pq_meta = pq.ParquetFile(str(parquet_path)).metadata
        actual_rows = pq_meta.num_rows
        expected_rows = entry["row_count"]
        if actual_rows != expected_rows:
            raise RuntimeError(
                "Row count mismatch for %s: expected %d, got %d"
                % (rel_path, expected_rows, actual_rows)
            )

        logger.info(
            "  ✓ %-50s %d rows, sha256 %s",
            rel_path, actual_rows, actual_sha[:12],
        )

    # "No unexpected files" invariant: any parquet on disk that is NOT in the
    # manifest is a red flag (tampered HF revision shipping un-checked files).
    on_disk = {p.resolve() for p in local_dir.rglob("*.parquet")}
    extra = on_disk - listed_paths
    if extra:
        extra_rel = sorted(p.relative_to(local_dir.resolve()).as_posix() for p in extra)
        raise RuntimeError(
            "Unlisted parquet files found in fetched tree (%d): %s. "
            "Refusing to proceed — manifest must enumerate every parquet."
            % (len(extra_rel), extra_rel)
        )

    logger.info("Manifest verification passed: %d tables OK", len(tables))
    return manifest


def verify_panel_row_count(
    local_dir: Path,
    *,
    expected_rows: int = EXPECTED_FULL_PANEL_ROWS,
    panel_path: str = DEFAULT_PANEL_PATH,
) -> int:
    """Confirm the main panel parquet has the expected row count.

    For ICSKG-BR v1.x the canonical invariant is 5,570 municipalities × 9 years
    = 50,130 rows. This function reads the parquet metadata (no full data load)
    and asserts the row count matches.

    Parameters
    ----------
    local_dir : Path
        Directory containing the parquet tree.
    expected_rows : int
        Expected row count (default 50,130 for v1.x).
    panel_path : str
        Relative path to the main panel parquet (default panel/municipal_health.parquet).

    Returns
    -------
    int
        Actual row count.

    Raises
    ------
    FileNotFoundError
        If the panel parquet is missing.
    AssertionError
        If the row count does not match.
    """
    local_dir = Path(local_dir)
    panel_file = local_dir / panel_path
    if not panel_file.exists():
        raise FileNotFoundError(
            "Main panel parquet not found at %s -- "
            "the dataset is missing the canonical panel/municipal_health.parquet"
            % panel_file
        )

    import pyarrow.parquet as pq  # noqa: PLC0415

    n = pq.ParquetFile(str(panel_file)).metadata.num_rows
    logger.info(
        "Panel row count: %d (expected %d)", n, expected_rows,
    )
    # NB: do NOT use `assert` here — assert is stripped under PYTHONOPTIMIZE.
    # This invariant is publication-blocking and must always be enforced.
    if n != expected_rows:
        raise RuntimeError(
            "Panel row count invariant violated: %s has %d rows, expected %d. "
            "This is a publication-blocking failure — the dataset is incomplete."
            % (panel_file, n, expected_rows)
        )
    return n


def materialize_sqlite(
    local_dir: Path,
    output_sqlite: Path,
    *,
    manifest: dict[str, Any] | None = None,
) -> Path:
    """Load parquet files from a fetched HF tree into a fresh SQLite database.

    Uses Python's stdlib sqlite3 + pandas (no DuckDB extensions, no network
    INSTALL step). Each parquet file is read into a DataFrame and written
    via to_sql, which handles type binding safely (no SQL injection).

    Parameters
    ----------
    local_dir : Path
        Directory containing the parquet tree (from fetch_processed_tree).
    output_sqlite : Path
        Output path for the materialized SQLite database. Existing files
        are overwritten.
    manifest : dict | None
        If provided, ONLY processes files listed in manifest["tables"]
        (recommended — inherits the SHA256-verified file set, prevents
        unlisted-file injection). If None, falls back to walking
        local_dir.rglob("*.parquet").

    Returns
    -------
    Path
        output_sqlite, after materialization.
    """
    local_dir = Path(local_dir)
    output_sqlite = Path(output_sqlite)
    output_sqlite.parent.mkdir(parents=True, exist_ok=True)
    if output_sqlite.exists():
        output_sqlite.unlink()

    # Resolve the file list from the manifest (preferred) or by walking the dir
    if manifest is not None:
        if "tables" not in manifest:
            raise RuntimeError("manifest dict has no 'tables' key")
        parquet_files: list[Path] = []
        for entry in manifest["tables"]:
            safe_path = _validate_safe_relpath(entry["parquet_path"], local_dir)
            if not safe_path.exists():
                raise FileNotFoundError(
                    "Parquet listed in manifest not found on disk: %s" % safe_path
                )
            parquet_files.append(safe_path)
    else:
        parquet_files = sorted(local_dir.rglob("*.parquet"))

    if not parquet_files:
        raise FileNotFoundError(
            "No parquet files found under %s -- nothing to materialize" % local_dir
        )

    logger.info("─" * 70)
    logger.info("Materializing %d parquet files into %s", len(parquet_files), output_sqlite)
    logger.info("─" * 70)

    # Use stdlib sqlite3 + pandas — no DuckDB sqlite extension, no network call,
    # no string-formatted SQL identifiers. pandas.DataFrame.to_sql parameter-
    # binds values automatically; the only thing we control is the table name,
    # which we whitelist below.
    import sqlite3  # noqa: PLC0415

    import pandas as pd  # noqa: PLC0415

    conn = sqlite3.connect(str(output_sqlite))
    try:
        for pq_path in parquet_files:
            table_name = pq_path.stem
            if not _SAFE_IDENTIFIER_RE.match(table_name):
                raise ValueError(
                    "Refusing to materialize parquet with unsafe table name %r "
                    "(must match %s)" % (table_name, _SAFE_IDENTIFIER_RE.pattern)
                )
            df = pd.read_parquet(pq_path)
            df.to_sql(table_name, conn, index=False, if_exists="replace")
            logger.info("  ✓ %-40s %d rows", table_name, len(df))
        conn.commit()
    finally:
        conn.close()

    logger.info(
        "Materialized %s (%.2f MB)",
        output_sqlite, output_sqlite.stat().st_size / 1024 / 1024,
    )
    return output_sqlite


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for fetch + verify (+ optional materialize)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Fetch and verify the ICSKG-BR processed dataset from HuggingFace",
    )
    parser.add_argument(
        "--repo-id",
        default=DEFAULT_REPO_ID,
        help="HuggingFace dataset repo id",
    )
    parser.add_argument(
        "--revision",
        required=True,
        help="Dataset revision tag (e.g., v0.1.0)",
    )
    parser.add_argument(
        "--target-dir",
        type=Path,
        default=None,
        help="Local cache dir (default: ~/.cache/icskg/hf-snapshots/{revision})",
    )
    parser.add_argument(
        "--to",
        type=Path,
        default=None,
        help="Materialize the parquet tree into a SQLite file at this path",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Skip download, verify an existing local tree",
    )
    parser.add_argument(
        "--force-redownload",
        action="store_true",
        help="Ignore the manifest cache hit and re-download",
    )
    parser.add_argument(
        "--expected-rows",
        type=int,
        default=EXPECTED_FULL_PANEL_ROWS,
        help="Expected row count for the main panel (default 50130)",
    )
    args = parser.parse_args(argv)

    target_dir = args.target_dir or (
        Path.home() / ".cache" / "icskg" / "hf-snapshots" / args.revision
    )

    # Step 1: Fetch (or skip if --verify-only)
    if not args.verify_only:
        fetch_processed_tree(
            repo_id=args.repo_id,
            revision=args.revision,
            target_dir=target_dir,
            force_redownload=args.force_redownload,
        )

    # Step 2: Verify manifest
    manifest = verify_manifest(target_dir)

    # Step 3: Verify panel row count invariant
    verify_panel_row_count(target_dir, expected_rows=args.expected_rows)

    # Step 4: Optional materialize (manifest-driven so we only ingest the
    # SHA256-verified file set)
    if args.to is not None:
        materialize_sqlite(target_dir, args.to, manifest=manifest)

    logger.info("─" * 70)
    logger.info("Done. Verified parquet tree at %s", target_dir)
    if args.to:
        logger.info("Materialized sqlite at %s", args.to)
    logger.info("─" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
