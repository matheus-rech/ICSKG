"""Unit tests for scripts/publish_to_hf.py.

These tests use a synthetic in-memory DuckDB and mock huggingface_hub.HfApi
so they run completely offline. The real HF publish is exercised manually
via Plan 11.1 Task 2 (interactive, requires user approval + NAS access).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import duckdb
import pytest

from scripts.publish_to_hf import (
    NAMESPACE_RULES,
    SCHEMA_VERSION,
    assign_namespace,
    build_manifest,
    duckdb_to_parquet_tree,
    generate_dataset_card,
    publish_to_hf,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def synthetic_duckdb(tmp_path: Path) -> Path:
    """Create a small synthetic DuckDB with 3 base tables and 1 view.

    Tables match real ICSKG-BR table names so namespace assignment is exercised:
    - municipal_health   → panel namespace
    - dimension_scores   → dimensions namespace
    - lcogs_indicators   → lcogs namespace

    Plus one view (municipal_health_view) that should be skipped.
    """
    db_path = tmp_path / "synthetic.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE municipal_health AS "
            "SELECT '3550308' AS cod_ibge, 2023 AS year, 0.65 AS cuds, "
            "120000 AS gdp_per_capita "
            "UNION ALL "
            "SELECT '2611606', 2023, 0.42, 35000 "
            "UNION ALL "
            "SELECT '5300108', 2023, 0.78, 95000"
        )
        conn.execute(
            "CREATE TABLE dimension_scores AS "
            "SELECT '3550308' AS cod_ibge, 2023 AS year, "
            "0.7 AS d1, 0.6 AS d2, 0.65 AS cuds "
            "UNION ALL "
            "SELECT '2611606', 2023, 0.4, 0.45, 0.42"
        )
        conn.execute(
            "CREATE TABLE lcogs_indicators AS "
            "SELECT '3550308' AS cod_ibge, 2023 AS year, "
            "12.5 AS lcogs1_distance_km, 45.2 AS sao_per_100k"
        )
        # Source table that falls through to source_tables/
        conn.execute(
            "CREATE TABLE sih_aggregated AS "
            "SELECT '3550308' AS cod_ibge, 2023 AS year, 1500 AS surgical_count"
        )
        # A view that should be skipped
        conn.execute(
            "CREATE VIEW municipal_health_view AS SELECT * FROM municipal_health"
        )
    finally:
        conn.close()
    return db_path


@pytest.fixture
def converted_tree(tmp_path: Path, synthetic_duckdb: Path) -> tuple[Path, dict]:
    """Run the real conversion against the synthetic DuckDB."""
    working = tmp_path / "tree"
    result = duckdb_to_parquet_tree(synthetic_duckdb, working)
    return working, result


# ---------------------------------------------------------------------------
# assign_namespace
# ---------------------------------------------------------------------------


def test_assign_namespace_routes_dimensions():
    assert assign_namespace("dimension_scores") == "dimensions"
    assert assign_namespace("DIMENSION_SCORE") == "dimensions"  # case-insensitive
    assert assign_namespace("cuds_composite") == "dimensions"


def test_assign_namespace_routes_lcogs():
    assert assign_namespace("lcogs_indicators") == "lcogs"
    assert assign_namespace("LCOGS_BELLWETHER_DISTANCES") == "lcogs"


def test_assign_namespace_routes_panel():
    assert assign_namespace("municipal_health") == "panel"
    assert assign_namespace("municipality_lookup") == "panel"
    assert assign_namespace("dimension_metadata") == "panel"
    assert assign_namespace("validation_report") == "panel"
    assert assign_namespace("imputation_log") == "panel"
    assert assign_namespace("deflation_log") == "panel"


def test_assign_namespace_falls_through_to_source_tables():
    assert assign_namespace("sih_aggregated") == "source_tables"
    assert assign_namespace("cnes_facilities") == "source_tables"
    assert assign_namespace("ans_beneficiaries") == "source_tables"
    assert assign_namespace("ifgf_index") == "source_tables"
    assert assign_namespace("random_unknown_table") == "source_tables"


# ---------------------------------------------------------------------------
# duckdb_to_parquet_tree
# ---------------------------------------------------------------------------


def test_duckdb_to_parquet_tree_creates_namespace_dirs(converted_tree):
    working, result = converted_tree
    assert (working / "panel").is_dir()
    assert (working / "dimensions").is_dir()
    assert (working / "lcogs").is_dir()
    assert (working / "source_tables").is_dir()


def test_duckdb_to_parquet_tree_writes_one_parquet_per_table(converted_tree):
    working, result = converted_tree
    # 4 base tables expected (3 namespaced + 1 source_tables fallthrough)
    assert len(result["tables"]) == 4
    for entry in result["tables"]:
        assert (working / entry["parquet_path"]).is_file()


def test_duckdb_to_parquet_tree_skips_views(converted_tree):
    working, result = converted_tree
    skipped_names = [v["name"] for v in result["skipped_views"]]
    assert "municipal_health_view" in skipped_names
    table_names = [t["table"] for t in result["tables"]]
    assert "municipal_health_view" not in table_names


def test_duckdb_to_parquet_tree_records_row_counts(converted_tree):
    working, result = converted_tree
    by_table = {t["table"]: t for t in result["tables"]}
    assert by_table["municipal_health"]["row_count"] == 3
    assert by_table["dimension_scores"]["row_count"] == 2
    assert by_table["lcogs_indicators"]["row_count"] == 1
    assert by_table["sih_aggregated"]["row_count"] == 1


def test_duckdb_to_parquet_tree_records_sha256(converted_tree):
    working, result = converted_tree
    for entry in result["tables"]:
        path = working / entry["parquet_path"]
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        assert entry["sha256"] == h.hexdigest()
        assert len(entry["sha256"]) == 64  # hex digest length


def test_duckdb_to_parquet_tree_raises_on_missing_source(tmp_path):
    with pytest.raises(FileNotFoundError, match="Source DuckDB not found"):
        duckdb_to_parquet_tree(tmp_path / "nope.duckdb", tmp_path / "out")


# ---------------------------------------------------------------------------
# build_manifest
# ---------------------------------------------------------------------------


def test_build_manifest_has_required_keys(synthetic_duckdb, converted_tree):
    working, result = converted_tree
    manifest = build_manifest(
        source_duckdb=synthetic_duckdb,
        conversion_result=result,
        dataset_name="test/icskg",
        dataset_version="v0.0.1",
    )
    required = {
        "dataset_name", "dataset_version", "schema_version",
        "generated_at", "source_duckdb", "compression",
        "tables", "skipped_views", "totals",
    }
    assert required.issubset(manifest.keys())
    assert manifest["dataset_name"] == "test/icskg"
    assert manifest["dataset_version"] == "v0.0.1"
    assert manifest["schema_version"] == SCHEMA_VERSION


def test_build_manifest_source_sha256_matches_file(synthetic_duckdb, converted_tree):
    working, result = converted_tree
    manifest = build_manifest(
        source_duckdb=synthetic_duckdb,
        conversion_result=result,
        dataset_name="test/icskg",
        dataset_version="v0.0.1",
    )
    h = hashlib.sha256()
    with synthetic_duckdb.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    assert manifest["source_duckdb"]["sha256"] == h.hexdigest()
    assert manifest["source_duckdb"]["size_bytes"] == synthetic_duckdb.stat().st_size


def test_build_manifest_totals_sum_correctly(synthetic_duckdb, converted_tree):
    working, result = converted_tree
    manifest = build_manifest(
        source_duckdb=synthetic_duckdb,
        conversion_result=result,
        dataset_name="test/icskg",
        dataset_version="v0.0.1",
    )
    totals = manifest["totals"]
    assert totals["table_count"] == len(result["tables"])
    assert totals["row_count"] == sum(t["row_count"] for t in result["tables"])
    assert totals["size_bytes_compressed"] == sum(
        t["size_bytes"] for t in result["tables"]
    )


def test_build_manifest_is_json_serializable(synthetic_duckdb, converted_tree):
    working, result = converted_tree
    manifest = build_manifest(
        source_duckdb=synthetic_duckdb,
        conversion_result=result,
        dataset_name="test/icskg",
        dataset_version="v0.0.1",
    )
    text = json.dumps(manifest, indent=2)
    parsed = json.loads(text)
    assert parsed["dataset_version"] == "v0.0.1"


# ---------------------------------------------------------------------------
# generate_dataset_card
# ---------------------------------------------------------------------------


def test_generate_dataset_card_has_yaml_frontmatter(synthetic_duckdb, converted_tree):
    working, result = converted_tree
    manifest = build_manifest(
        source_duckdb=synthetic_duckdb,
        conversion_result=result,
        dataset_name="test/icskg",
        dataset_version="v0.0.1",
    )
    card = generate_dataset_card(manifest)
    assert card.startswith("---\n")
    assert "license: cc-by-4.0" in card
    assert "pretty_name: ICSKG-BR Processed Data" in card
    assert "size_categories:" in card


def test_generate_dataset_card_lists_tables_by_namespace(
    synthetic_duckdb, converted_tree
):
    working, result = converted_tree
    manifest = build_manifest(
        source_duckdb=synthetic_duckdb,
        conversion_result=result,
        dataset_name="test/icskg",
        dataset_version="v0.0.1",
    )
    card = generate_dataset_card(manifest)
    assert "### `panel/`" in card
    assert "### `dimensions/`" in card
    assert "### `lcogs/`" in card
    assert "### `source_tables/`" in card
    assert "municipal_health" in card
    assert "dimension_scores" in card
    assert "lcogs_indicators" in card
    assert "sih_aggregated" in card


# ---------------------------------------------------------------------------
# publish_to_hf
# ---------------------------------------------------------------------------


def test_publish_to_hf_dry_run_skips_upload(tmp_path):
    """Dry run must not import or call HfApi."""
    working = tmp_path / "tree"
    working.mkdir()
    (working / "manifest.json").write_text("{}")

    original_import = __import__

    def guarded_import(name, *args, **kwargs):
        if name == "huggingface_hub" or name.startswith("huggingface_hub."):
            raise AssertionError("dry-run must not import huggingface_hub")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=guarded_import):
        url = publish_to_hf(
            working_dir=working,
            repo_id="test/icskg",
            dataset_version="v0.0.1",
            commit_message="test",
            dry_run=True,
        )
    assert url == "dry-run"


def test_publish_to_hf_creates_repo_and_uploads(tmp_path, monkeypatch):
    """Real publish path: mocked HfApi must see create_repo + upload_folder + create_tag."""
    working = tmp_path / "tree"
    working.mkdir()
    (working / "manifest.json").write_text("{}")

    # Build a fake huggingface_hub module
    fake_api_instance = MagicMock()
    fake_api_class = MagicMock(return_value=fake_api_instance)
    fake_errors = MagicMock()

    class FakeHfHubHTTPError(Exception):
        pass

    fake_errors.HfHubHTTPError = FakeHfHubHTTPError

    fake_module = MagicMock()
    fake_module.HfApi = fake_api_class
    fake_errors_module = MagicMock()
    fake_errors_module.HfHubHTTPError = FakeHfHubHTTPError

    monkeypatch.setitem(__import__("sys").modules, "huggingface_hub", fake_module)
    monkeypatch.setitem(
        __import__("sys").modules, "huggingface_hub.errors", fake_errors_module
    )
    monkeypatch.setenv("HF_TOKEN", "fake_token_for_testing")

    url = publish_to_hf(
        working_dir=working,
        repo_id="test/icskg",
        dataset_version="v0.0.1",
        commit_message="test commit",
        private=True,
        dry_run=False,
    )

    assert "test/icskg" in url
    assert "v0.0.1" in url
    fake_api_class.assert_called_once_with(token="fake_token_for_testing")
    fake_api_instance.create_repo.assert_called_once()
    fake_api_instance.upload_folder.assert_called_once()
    fake_api_instance.create_tag.assert_called_once()


def test_publish_to_hf_raises_without_token(tmp_path, monkeypatch):
    """Real publish without HF token should raise RuntimeError, not silently fail."""
    working = tmp_path / "tree"
    working.mkdir()
    monkeypatch.delenv("HF_TOKEN", raising=False)
    # Force HfFolder.get_token to also return None
    fake_module = MagicMock()
    fake_module.HfFolder.get_token.return_value = None
    monkeypatch.setitem(__import__("sys").modules, "huggingface_hub", fake_module)

    with pytest.raises(RuntimeError, match="No HuggingFace token found"):
        publish_to_hf(
            working_dir=working,
            repo_id="test/icskg",
            dataset_version="v0.0.1",
            commit_message="test",
            dry_run=False,
        )
