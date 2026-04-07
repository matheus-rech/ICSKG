"""Unit tests for scripts/mirror_to_zenodo.py.

All tests use mocked HTTP — no network calls reach Zenodo or HuggingFace.
The real sandbox/production deposit flow is exercised manually as
Plan 11.5 Tasks 2-3 (interactive, requires user-supplied tokens).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.mirror_to_zenodo import (
    PLACEHOLDER_MARKERS,
    SKIP_PATTERNS,
    ZENODO_BASE_URLS,
    create_zenodo_deposition,
    load_zenodo_metadata,
    main,
    publish_deposition,
    upload_files,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _real_metadata() -> dict:
    """Return a complete, placeholder-free .zenodo.json content."""
    return {
        "title": "ICSKG-BR: Test Mirror",
        "description": "Test deposit for the mirror script.",
        "creators": [
            {
                "name": "Rech, Matheus M.",
                "affiliation": "Universidade Federal do Rio Grande do Sul",
                "orcid": "0000-0000-0000-0000",
            }
        ],
        "keywords": ["global surgery", "Brazil"],
        "license": "cc-by-4.0",
        "upload_type": "dataset",
        "access_right": "open",
        "language": "eng",
    }


@pytest.fixture
def real_zenodo_json(tmp_path) -> Path:
    """Write a real (placeholder-free) .zenodo.json to tmp_path."""
    path = tmp_path / ".zenodo.json"
    path.write_text(json.dumps(_real_metadata(), indent=2))
    return path


@pytest.fixture
def placeholder_zenodo_json(tmp_path) -> Path:
    """Write a .zenodo.json that still has [Author Name] placeholder."""
    bad = _real_metadata()
    bad["creators"][0]["name"] = "[Author Name]"
    bad["creators"][0]["affiliation"] = "[Institution]"
    path = tmp_path / ".zenodo.json"
    path.write_text(json.dumps(bad, indent=2))
    return path


@pytest.fixture
def fake_deposition() -> dict:
    """Return a Zenodo deposition response shape."""
    return {
        "id": 123456,
        "links": {
            "bucket": "https://sandbox.zenodo.org/api/files/abc123",
            "files": "https://sandbox.zenodo.org/api/deposit/depositions/123456/files",
            "publish": "https://sandbox.zenodo.org/api/deposit/depositions/123456/actions/publish",
            "html": "https://sandbox.zenodo.org/record/123456",
        },
        "metadata": {},
    }


# ---------------------------------------------------------------------------
# load_zenodo_metadata
# ---------------------------------------------------------------------------


def test_load_zenodo_metadata_accepts_real_metadata(real_zenodo_json):
    metadata = load_zenodo_metadata(real_zenodo_json)
    assert metadata["license"] == "cc-by-4.0"
    assert metadata["upload_type"] == "dataset"
    assert len(metadata["creators"]) == 1
    assert metadata["creators"][0]["name"] == "Rech, Matheus M."


def test_load_zenodo_metadata_rejects_author_placeholder(placeholder_zenodo_json):
    with pytest.raises(ValueError) as exc_info:
        load_zenodo_metadata(placeholder_zenodo_json)
    msg = str(exc_info.value)
    assert "placeholder" in msg.lower()
    assert "Author Name" in msg or "Institution" in msg


def test_load_zenodo_metadata_rejects_each_placeholder_marker(tmp_path):
    """Every entry in PLACEHOLDER_MARKERS must trigger rejection."""
    for marker in PLACEHOLDER_MARKERS:
        bad = _real_metadata()
        # Inject the marker into the title (first string-typed field walked)
        bad["title"] = "ICSKG-BR " + marker.upper()
        path = tmp_path / "z.json"
        path.write_text(json.dumps(bad))
        with pytest.raises(ValueError, match="placeholder"):
            load_zenodo_metadata(path)


def test_load_zenodo_metadata_rejects_missing_creators(tmp_path):
    bad = _real_metadata()
    del bad["creators"]
    path = tmp_path / "z.json"
    path.write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="missing required top-level fields"):
        load_zenodo_metadata(path)


def test_load_zenodo_metadata_rejects_empty_creators(tmp_path):
    bad = _real_metadata()
    bad["creators"] = []
    path = tmp_path / "z.json"
    path.write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="non-empty list"):
        load_zenodo_metadata(path)


def test_load_zenodo_metadata_rejects_creator_without_affiliation(tmp_path):
    bad = _real_metadata()
    del bad["creators"][0]["affiliation"]
    path = tmp_path / "z.json"
    path.write_text(json.dumps(bad))
    with pytest.raises(ValueError, match="affiliation"):
        load_zenodo_metadata(path)


def test_load_zenodo_metadata_raises_on_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_zenodo_metadata(tmp_path / "nonexistent.json")


def test_load_zenodo_metadata_raises_on_invalid_json(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{ this is not valid json")
    with pytest.raises(ValueError, match="Failed to parse"):
        load_zenodo_metadata(path)


# ---------------------------------------------------------------------------
# create_zenodo_deposition
# ---------------------------------------------------------------------------


def test_create_zenodo_deposition_uses_sandbox_url(real_zenodo_json):
    metadata = load_zenodo_metadata(real_zenodo_json)
    fake_resp = MagicMock()
    fake_resp.json.return_value = {
        "id": 999, "links": {"publish": "..."},
    }
    fake_resp.raise_for_status.return_value = None

    fake_requests = MagicMock()
    fake_requests.post.return_value = fake_resp
    fake_requests.put.return_value = fake_resp

    with patch.dict(sys.modules, {"requests": fake_requests}):
        create_zenodo_deposition(
            metadata=metadata,
            target="sandbox",
            zenodo_token="fake-token",
        )

    # First call is the POST to create — must hit sandbox
    create_url = fake_requests.post.call_args.args[0]
    assert "sandbox.zenodo.org" in create_url
    assert "/api/deposit/depositions" in create_url

    # Second call is the PUT for metadata — must include the metadata wrapper
    put_kwargs = fake_requests.put.call_args
    body = json.loads(put_kwargs.kwargs["data"])
    assert "metadata" in body
    assert body["metadata"]["title"] == metadata["title"]


def test_create_zenodo_deposition_uses_production_url(real_zenodo_json):
    metadata = load_zenodo_metadata(real_zenodo_json)
    fake_resp = MagicMock()
    fake_resp.json.return_value = {"id": 999, "links": {}}
    fake_resp.raise_for_status.return_value = None

    fake_requests = MagicMock()
    fake_requests.post.return_value = fake_resp
    fake_requests.put.return_value = fake_resp

    with patch.dict(sys.modules, {"requests": fake_requests}):
        create_zenodo_deposition(
            metadata=metadata,
            target="production",
            zenodo_token="fake-token",
        )

    create_url = fake_requests.post.call_args.args[0]
    assert "zenodo.org" in create_url
    assert "sandbox" not in create_url


def test_create_zenodo_deposition_rejects_invalid_target(real_zenodo_json):
    metadata = load_zenodo_metadata(real_zenodo_json)
    with pytest.raises(ValueError, match="Invalid target"):
        create_zenodo_deposition(
            metadata=metadata,
            target="staging",  # not a real target
            zenodo_token="fake",
        )


# ---------------------------------------------------------------------------
# upload_files
# ---------------------------------------------------------------------------


def test_upload_files_skips_dotfiles(tmp_path, fake_deposition):
    """SKIP_PATTERNS files (.DS_Store, .gitignore, ...) must not be uploaded."""
    (tmp_path / "panel").mkdir()
    (tmp_path / "panel" / "data.parquet").write_bytes(b"fake parquet")
    (tmp_path / "panel" / ".DS_Store").write_bytes(b"mac junk")
    (tmp_path / ".gitignore").write_text("*.tmp\n")
    (tmp_path / "manifest.json").write_text("{}")

    fake_resp = MagicMock()
    fake_resp.json.return_value = {"checksum": "abc"}
    fake_resp.text = '{"checksum":"abc"}'
    fake_resp.raise_for_status.return_value = None

    fake_requests = MagicMock()
    fake_requests.put.return_value = fake_resp
    fake_requests.post.return_value = fake_resp

    with patch.dict(sys.modules, {"requests": fake_requests}):
        uploads = upload_files(
            deposition=fake_deposition,
            files_dir=tmp_path,
            target="sandbox",
            zenodo_token="fake",
        )

    # Only data.parquet and manifest.json should be uploaded — 2 files
    assert len(uploads) == 2

    # Verify .DS_Store was not in any of the uploaded paths
    uploaded_urls = [
        call.args[0] for call in fake_requests.put.call_args_list
    ]
    assert all(".DS_Store" not in u for u in uploaded_urls)
    assert all(".gitignore" not in u for u in uploaded_urls)


def test_upload_files_uses_bucket_url_when_present(tmp_path, fake_deposition):
    """When deposition.links.bucket is present, files are PUT to the bucket URL."""
    (tmp_path / "x.parquet").write_bytes(b"data")

    fake_resp = MagicMock()
    fake_resp.json.return_value = {}
    fake_resp.text = "{}"
    fake_resp.raise_for_status.return_value = None

    fake_requests = MagicMock()
    fake_requests.put.return_value = fake_resp

    with patch.dict(sys.modules, {"requests": fake_requests}):
        upload_files(
            deposition=fake_deposition,
            files_dir=tmp_path,
            target="sandbox",
            zenodo_token="fake",
        )

    fake_requests.put.assert_called_once()
    url = fake_requests.put.call_args.args[0]
    assert url.startswith("https://sandbox.zenodo.org/api/files/abc123/")
    assert url.endswith("/x.parquet")


# ---------------------------------------------------------------------------
# publish_deposition
# ---------------------------------------------------------------------------


def test_publish_deposition_dry_run_skips_post(fake_deposition):
    """dry_run=True must NOT call requests.post."""
    fake_requests = MagicMock()
    with patch.dict(sys.modules, {"requests": fake_requests}):
        result = publish_deposition(
            deposition=fake_deposition,
            target="sandbox",
            zenodo_token="fake",
            dry_run=True,
        )
    fake_requests.post.assert_not_called()
    assert result == fake_deposition


def test_publish_deposition_real_calls_post(fake_deposition):
    """dry_run=False must POST the publish URL."""
    fake_resp = MagicMock()
    fake_resp.json.return_value = {
        "id": 123456,
        "doi": "10.5072/zenodo.123456",
        "metadata": {},
        "links": {"html": "https://sandbox.zenodo.org/record/123456"},
    }
    fake_resp.raise_for_status.return_value = None

    fake_requests = MagicMock()
    fake_requests.post.return_value = fake_resp

    with patch.dict(sys.modules, {"requests": fake_requests}):
        result = publish_deposition(
            deposition=fake_deposition,
            target="sandbox",
            zenodo_token="fake",
            dry_run=False,
        )

    fake_requests.post.assert_called_once()
    publish_url = fake_requests.post.call_args.args[0]
    assert "publish" in publish_url
    assert result.get("doi") == "10.5072/zenodo.123456"


# ---------------------------------------------------------------------------
# main / argparse
# ---------------------------------------------------------------------------


def test_main_requires_explicit_target(real_zenodo_json):
    """--target is required (no default — explicit choice)."""
    with pytest.raises(SystemExit):
        main([
            "--revision", "v0.0.1",
            "--zenodo-json", str(real_zenodo_json),
            # no --target
        ])


def test_main_rejects_invalid_target(real_zenodo_json):
    """argparse choices restricts --target to sandbox/production."""
    with pytest.raises(SystemExit):
        main([
            "--revision", "v0.0.1",
            "--target", "staging",  # not allowed
            "--zenodo-json", str(real_zenodo_json),
        ])
