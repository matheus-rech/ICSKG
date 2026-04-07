"""Unit tests for database/fetch_processed_data.py.

These tests build a synthetic parquet tree + manifest that matches the
shape produced by scripts/publish_to_hf.py, then exercise the fetch,
verify, and materialize paths against it. snapshot_download is mocked
so all tests run completely offline.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from database.fetch_processed_data import (
    EXPECTED_FULL_PANEL_ROWS,
    fetch_processed_tree,
    materialize_sqlite,
    verify_manifest,
    verify_panel_row_count,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@pytest.fixture
def synthetic_hf_tree(tmp_path: Path) -> Path:
    """Build a synthetic HF-shape parquet tree under tmp_path matching the
    schema produced by publish_to_hf.py.

    Layout:
        tmp_path/
        ├── manifest.json
        ├── README.md
        ├── panel/
        │   ├── municipal_health.parquet     (50,130 rows — fake but right count)
        │   └── municipality_lookup.parquet  (5,571 rows)
        ├── dimensions/
        │   └── dimension_scores.parquet     (50,130 rows)
        ├── lcogs/
        │   └── lcogs_indicators.parquet     (50,130 rows)
        └── source_tables/
            └── sih_aggregated.parquet       (200 rows)
    """
    tree = tmp_path / "tree"
    tree.mkdir()

    # panel/municipal_health.parquet — full scaffold size
    panel_dir = tree / "panel"
    panel_dir.mkdir()
    panel_df = pd.DataFrame({
        "cod_ibge": [str(3500000 + i) for i in range(EXPECTED_FULL_PANEL_ROWS)],
        "year": [2015 + (i % 9) for i in range(EXPECTED_FULL_PANEL_ROWS)],
        "cuds": [0.5 + (i % 100) / 1000 for i in range(EXPECTED_FULL_PANEL_ROWS)],
    })
    panel_path = panel_dir / "municipal_health.parquet"
    panel_df.to_parquet(panel_path, compression="zstd", compression_level=6, index=False)

    # panel/municipality_lookup.parquet — 5571 rows
    lookup_df = pd.DataFrame({
        "cod_ibge": [str(3500000 + i) for i in range(5571)],
        "name": ["Mun_%d" % i for i in range(5571)],
    })
    lookup_path = panel_dir / "municipality_lookup.parquet"
    lookup_df.to_parquet(lookup_path, compression="zstd", compression_level=6, index=False)

    # dimensions/dimension_scores.parquet
    dim_dir = tree / "dimensions"
    dim_dir.mkdir()
    dim_df = pd.DataFrame({
        "cod_ibge": panel_df["cod_ibge"],
        "year": panel_df["year"],
        "d1": panel_df["cuds"],
    })
    dim_path = dim_dir / "dimension_scores.parquet"
    dim_df.to_parquet(dim_path, compression="zstd", compression_level=6, index=False)

    # lcogs/lcogs_indicators.parquet
    lcogs_dir = tree / "lcogs"
    lcogs_dir.mkdir()
    lcogs_df = pd.DataFrame({
        "cod_ibge": panel_df["cod_ibge"],
        "year": panel_df["year"],
        "lcogs1_distance_km": [10.0 + i / 1000 for i in range(EXPECTED_FULL_PANEL_ROWS)],
    })
    lcogs_path = lcogs_dir / "lcogs_indicators.parquet"
    lcogs_df.to_parquet(lcogs_path, compression="zstd", compression_level=6, index=False)

    # source_tables/sih_aggregated.parquet — small
    src_dir = tree / "source_tables"
    src_dir.mkdir()
    sih_df = pd.DataFrame({
        "cod_ibge": [str(3500000 + i) for i in range(200)],
        "year": [2023] * 200,
        "surgical_count": list(range(200)),
    })
    sih_path = src_dir / "sih_aggregated.parquet"
    sih_df.to_parquet(sih_path, compression="zstd", compression_level=6, index=False)

    # README.md
    (tree / "README.md").write_text("# Synthetic test tree\n")

    # manifest.json — match publish_to_hf.build_manifest schema exactly
    tables = [
        {
            "namespace": "panel",
            "table": "municipal_health",
            "parquet_path": "panel/municipal_health.parquet",
            "row_count": len(panel_df),
            "column_count": len(panel_df.columns),
            "schema": [],
            "sha256": _sha256(panel_path),
            "size_bytes": panel_path.stat().st_size,
        },
        {
            "namespace": "panel",
            "table": "municipality_lookup",
            "parquet_path": "panel/municipality_lookup.parquet",
            "row_count": len(lookup_df),
            "column_count": len(lookup_df.columns),
            "schema": [],
            "sha256": _sha256(lookup_path),
            "size_bytes": lookup_path.stat().st_size,
        },
        {
            "namespace": "dimensions",
            "table": "dimension_scores",
            "parquet_path": "dimensions/dimension_scores.parquet",
            "row_count": len(dim_df),
            "column_count": len(dim_df.columns),
            "schema": [],
            "sha256": _sha256(dim_path),
            "size_bytes": dim_path.stat().st_size,
        },
        {
            "namespace": "lcogs",
            "table": "lcogs_indicators",
            "parquet_path": "lcogs/lcogs_indicators.parquet",
            "row_count": len(lcogs_df),
            "column_count": len(lcogs_df.columns),
            "schema": [],
            "sha256": _sha256(lcogs_path),
            "size_bytes": lcogs_path.stat().st_size,
        },
        {
            "namespace": "source_tables",
            "table": "sih_aggregated",
            "parquet_path": "source_tables/sih_aggregated.parquet",
            "row_count": len(sih_df),
            "column_count": len(sih_df.columns),
            "schema": [],
            "sha256": _sha256(sih_path),
            "size_bytes": sih_path.stat().st_size,
        },
    ]
    manifest = {
        "dataset_name": "test/synthetic",
        "dataset_version": "v0.0.1",
        "schema_version": "1.0",
        "generated_at": "2026-04-07T05:00:00Z",
        "source_duckdb": {
            "name": "synthetic.duckdb",
            "sha256": "0" * 64,
            "size_bytes": 1024,
        },
        "compression": {
            "format": "parquet",
            "codec": "zstd",
            "level": 6,
            "row_group_size": 100000,
        },
        "tables": tables,
        "skipped_views": [],
        "totals": {
            "table_count": len(tables),
            "row_count": sum(t["row_count"] for t in tables),
            "size_bytes_compressed": sum(t["size_bytes"] for t in tables),
        },
    }
    (tree / "manifest.json").write_text(json.dumps(manifest, indent=2))

    return tree


# ---------------------------------------------------------------------------
# fetch_processed_tree
# ---------------------------------------------------------------------------


def test_fetch_processed_tree_calls_snapshot_download(tmp_path, monkeypatch):
    """First fetch (no cache hit) must invoke snapshot_download."""
    target = tmp_path / "fresh"
    fake_download = MagicMock(return_value=str(target))
    monkeypatch.setattr(
        "huggingface_hub.snapshot_download", fake_download
    )
    monkeypatch.setenv("HF_TOKEN", "fake_token")

    result = fetch_processed_tree(
        repo_id="test/synth",
        revision="v0.0.1",
        target_dir=target,
    )

    assert result == target
    fake_download.assert_called_once()
    kwargs = fake_download.call_args.kwargs
    assert kwargs["repo_id"] == "test/synth"
    assert kwargs["revision"] == "v0.0.1"
    assert kwargs["repo_type"] == "dataset"
    assert kwargs["local_dir"] == str(target)
    assert kwargs["local_dir_use_symlinks"] is False
    assert kwargs["token"] == "fake_token"


def test_fetch_processed_tree_skips_when_cached(tmp_path, monkeypatch):
    """Existing manifest with matching revision skips snapshot_download."""
    target = tmp_path / "cached"
    target.mkdir()
    (target / "manifest.json").write_text(
        json.dumps({"dataset_version": "v0.0.1", "tables": []})
    )

    fake_download = MagicMock()
    monkeypatch.setattr(
        "huggingface_hub.snapshot_download", fake_download
    )

    result = fetch_processed_tree(
        repo_id="test/synth",
        revision="v0.0.1",
        target_dir=target,
    )

    assert result == target
    fake_download.assert_not_called()


def test_fetch_processed_tree_force_redownload_ignores_cache(tmp_path, monkeypatch):
    """force_redownload=True must call snapshot_download even on cache hit."""
    target = tmp_path / "cached"
    target.mkdir()
    (target / "manifest.json").write_text(
        json.dumps({"dataset_version": "v0.0.1", "tables": []})
    )

    fake_download = MagicMock(return_value=str(target))
    monkeypatch.setattr(
        "huggingface_hub.snapshot_download", fake_download
    )
    monkeypatch.setenv("HF_TOKEN", "fake")

    fetch_processed_tree(
        repo_id="test/synth",
        revision="v0.0.1",
        target_dir=target,
        force_redownload=True,
    )

    fake_download.assert_called_once()


def test_fetch_processed_tree_cache_miss_when_revision_differs(tmp_path, monkeypatch):
    """Existing manifest with DIFFERENT revision must trigger re-download."""
    target = tmp_path / "stale"
    target.mkdir()
    (target / "manifest.json").write_text(
        json.dumps({"dataset_version": "v0.0.0", "tables": []})  # old
    )

    fake_download = MagicMock(return_value=str(target))
    monkeypatch.setattr(
        "huggingface_hub.snapshot_download", fake_download
    )
    monkeypatch.setenv("HF_TOKEN", "fake")

    fetch_processed_tree(
        repo_id="test/synth",
        revision="v0.0.1",  # newer
        target_dir=target,
    )

    fake_download.assert_called_once()


# ---------------------------------------------------------------------------
# verify_manifest
# ---------------------------------------------------------------------------


def test_verify_manifest_passes_on_synthetic_tree(synthetic_hf_tree):
    manifest = verify_manifest(synthetic_hf_tree)
    assert manifest["dataset_version"] == "v0.0.1"
    assert len(manifest["tables"]) == 5
    # Total row count = 50130 panel + 5571 lookup + 50130 dim + 50130 lcogs + 200 sih
    expected_total = 50130 + 5571 + 50130 + 50130 + 200
    assert manifest["totals"]["row_count"] == expected_total


def test_verify_manifest_raises_on_missing_manifest(tmp_path):
    empty = tmp_path / "no_manifest"
    empty.mkdir()
    with pytest.raises(FileNotFoundError, match="manifest.json not found"):
        verify_manifest(empty)


def test_verify_manifest_raises_on_empty_tables_list(tmp_path):
    bad = tmp_path / "empty_tables"
    bad.mkdir()
    (bad / "manifest.json").write_text(json.dumps({"tables": []}))
    with pytest.raises(RuntimeError, match="no 'tables' entries"):
        verify_manifest(bad)


def test_verify_manifest_raises_on_missing_parquet(synthetic_hf_tree):
    """Delete a parquet file referenced by the manifest."""
    (synthetic_hf_tree / "panel" / "municipal_health.parquet").unlink()
    with pytest.raises(FileNotFoundError, match="referenced by manifest not found"):
        verify_manifest(synthetic_hf_tree)


def test_verify_manifest_raises_on_sha256_mismatch(synthetic_hf_tree):
    """Mutate one parquet file's bytes — SHA256 must mismatch."""
    target = synthetic_hf_tree / "panel" / "municipal_health.parquet"
    # Append a byte to corrupt the SHA without breaking parquet validity
    with target.open("ab") as f:
        f.write(b"\x00")
    with pytest.raises(RuntimeError, match="SHA256 mismatch"):
        verify_manifest(synthetic_hf_tree)


def test_verify_manifest_raises_on_row_count_mismatch(synthetic_hf_tree):
    """Replace a parquet with a smaller one. SHA256 will also mismatch but
    the row count check is hit if we update the manifest too."""
    target = synthetic_hf_tree / "source_tables" / "sih_aggregated.parquet"
    # Write a smaller parquet AND update the manifest entry's sha256 + size
    # to isolate the row_count check.
    new_df = pd.DataFrame({"x": [1, 2, 3]})  # 3 rows instead of 200
    new_df.to_parquet(target, compression="zstd", compression_level=6, index=False)

    # Recompute sha256 and size and update manifest, but leave row_count=200 (the bug)
    manifest_path = synthetic_hf_tree / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    new_sha = _sha256(target)
    for entry in manifest["tables"]:
        if entry["table"] == "sih_aggregated":
            entry["sha256"] = new_sha
            entry["size_bytes"] = target.stat().st_size
            # NOT updating row_count -- this is what we want to catch
    manifest_path.write_text(json.dumps(manifest, indent=2))

    with pytest.raises(RuntimeError, match="Row count mismatch"):
        verify_manifest(synthetic_hf_tree)


# ---------------------------------------------------------------------------
# verify_panel_row_count
# ---------------------------------------------------------------------------


def test_verify_panel_row_count_passes_on_50130(synthetic_hf_tree):
    n = verify_panel_row_count(synthetic_hf_tree)
    assert n == EXPECTED_FULL_PANEL_ROWS


def test_verify_panel_row_count_raises_on_wrong_count(synthetic_hf_tree):
    with pytest.raises(AssertionError, match="invariant violated"):
        verify_panel_row_count(synthetic_hf_tree, expected_rows=99999)


def test_verify_panel_row_count_raises_on_missing_panel(tmp_path):
    empty = tmp_path / "no_panel"
    empty.mkdir()
    with pytest.raises(FileNotFoundError, match="Main panel parquet not found"):
        verify_panel_row_count(empty)


# ---------------------------------------------------------------------------
# materialize_sqlite
# ---------------------------------------------------------------------------


def test_materialize_sqlite_creates_db_with_all_tables(synthetic_hf_tree, tmp_path):
    out_sqlite = tmp_path / "materialized.sqlite"
    result = materialize_sqlite(synthetic_hf_tree, out_sqlite)
    assert result == out_sqlite
    assert out_sqlite.exists()

    # Open it and verify all 5 tables exist with the right row counts
    conn = sqlite3.connect(str(out_sqlite))
    try:
        tables = [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "ORDER BY name"
            ).fetchall()
        ]
        # Names come from parquet basename (without .parquet)
        assert "municipal_health" in tables
        assert "municipality_lookup" in tables
        assert "dimension_scores" in tables
        assert "lcogs_indicators" in tables
        assert "sih_aggregated" in tables

        n_panel = conn.execute(
            "SELECT COUNT(*) FROM municipal_health"
        ).fetchone()[0]
        assert n_panel == EXPECTED_FULL_PANEL_ROWS
    finally:
        conn.close()


def test_materialize_sqlite_overwrites_existing(synthetic_hf_tree, tmp_path):
    out_sqlite = tmp_path / "to_overwrite.sqlite"
    out_sqlite.write_bytes(b"junk content")
    materialize_sqlite(synthetic_hf_tree, out_sqlite)
    # Should be a real sqlite now, not "junk content"
    conn = sqlite3.connect(str(out_sqlite))
    try:
        n_panel = conn.execute(
            "SELECT COUNT(*) FROM municipal_health"
        ).fetchone()[0]
        assert n_panel == EXPECTED_FULL_PANEL_ROWS
    finally:
        conn.close()


def test_materialize_sqlite_raises_on_empty_tree(tmp_path):
    empty = tmp_path / "no_parquets"
    empty.mkdir()
    with pytest.raises(FileNotFoundError, match="No parquet files found"):
        materialize_sqlite(empty, tmp_path / "out.sqlite")
