"""
ICSKG-BR HuggingFace → Zenodo Mirror
======================================
Mirror the canonical ICSKG-BR processed dataset from HuggingFace to a
Zenodo deposition. Mints a citable DOI for the dataset that can be
referenced in the BMJ Global Health manuscript.

The flow:

  1. Load .zenodo.json — must contain real author/institution/funder
     metadata, NOT the [Author Name] / [Institution] placeholders
  2. Fetch the parquet tree from HuggingFace at the requested revision
     into a working directory
  3. Create an empty Zenodo deposition (sandbox or production)
  4. PUT the metadata onto the deposition
  5. Upload every file from the working directory to the deposition
  6. POST the publish action to mint the DOI (or skip if --dry-run)

Two targets supported:

  - sandbox    → https://sandbox.zenodo.org   (testing, mints 10.5072/...)
  - production → https://zenodo.org           (irreversible, real DOI)

Production deposit is deferred until BMJ Global Health acceptance.
Sandbox is used now to validate the mirror path end-to-end without
polluting production records.

Usage
-----
    # Sandbox dry run (creates draft + uploads but does not publish)
    export HF_TOKEN=hf_...
    export ZENODO_TOKEN_SANDBOX=...
    uv run python -m scripts.mirror_to_zenodo \
        --revision v0.1.0 \
        --target sandbox \
        --dry-run

    # Sandbox real publish (mints sandbox DOI, NOT permanent)
    uv run python -m scripts.mirror_to_zenodo \
        --revision v0.1.0 \
        --target sandbox

    # Production publish (DO NOT RUN until BMJ acceptance)
    export ZENODO_TOKEN=...
    uv run python -m scripts.mirror_to_zenodo \
        --revision v1.0.0 \
        --target production

Authentication
--------------
  HF token   : HF_TOKEN env var (read scope is enough)
  Zenodo     : ZENODO_TOKEN_SANDBOX (sandbox) or ZENODO_TOKEN (production)
               env var; needs deposit:write + deposit:actions scopes

References
----------
  Zenodo REST API : https://developers.zenodo.org/
  .zenodo.json    : https://developers.zenodo.org/#deposit-metadata
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_REPO_ID = "mmrech/icskg-br-processed"
ZENODO_BASE_URLS = {
    "sandbox": "https://sandbox.zenodo.org",
    "production": "https://zenodo.org",
}
ZENODO_TOKEN_ENV_VARS = {
    "sandbox": "ZENODO_TOKEN_SANDBOX",
    "production": "ZENODO_TOKEN",
}
ZENODO_EXPECTED_HOSTS = {
    "sandbox": "sandbox.zenodo.org",
    "production": "zenodo.org",
}

# Strings that indicate the .zenodo.json still has placeholders.
# These get checked case-insensitively as substrings of every string value.
PLACEHOLDER_MARKERS: tuple[str, ...] = (
    "[author name]",
    "[institution]",
    "[orcid",
    "[real institution",
    "[funder",
    "[doi-to-be",
    "to-be-filled",
    "to be filled",
    "TODO",
    "placeholder_",
)

# Generic [Bracketed Placeholder] regex — catches any string that looks like
# a stub even if it's not in PLACEHOLDER_MARKERS. Matches the entire trimmed
# value, e.g. "[GitHub URL]", "[Real Institution]", "[Funder Grant ID]".
_BRACKET_PLACEHOLDER_RE: re.Pattern[str] = re.compile(r"^\[[^\]]{1,80}\]$")

# Files we never upload to Zenodo (working state, system files)
SKIP_PATTERNS: tuple[str, ...] = (
    ".DS_Store",
    "Thumbs.db",
    ".gitignore",
    ".cache",
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_zenodo_token(target: str, explicit: str | None = None) -> str:
    """Return a Zenodo token for the chosen target, or raise."""
    if explicit:
        return explicit
    env_name = ZENODO_TOKEN_ENV_VARS[target]
    token = os.environ.get(env_name)
    if not token:
        raise RuntimeError(
            "No Zenodo token found in env var %s. "
            "Generate one at %s/account/settings/applications/tokens/new/ "
            "with deposit:write + deposit:actions scopes."
            % (env_name, ZENODO_BASE_URLS[target])
        )
    return token


def _walk_for_placeholders(value: Any, path: str = "") -> list[str]:
    """Recursively find placeholder substrings inside a parsed JSON value.

    Two layers of detection:
      1. Substring match against PLACEHOLDER_MARKERS (e.g., "[Author Name]")
      2. Generic [Bracketed Placeholder] regex on the full trimmed string
         (catches future stubs like "[GitHub URL]" without an explicit entry)

    Returns a list of dotted paths where placeholder markers were found.
    """
    found: list[str] = []
    if isinstance(value, str):
        lower = value.lower()
        marker_hit = False
        for marker in PLACEHOLDER_MARKERS:
            if marker.lower() in lower:
                found.append("%s = %r" % (path or "<root>", value))
                marker_hit = True
                break
        if not marker_hit and _BRACKET_PLACEHOLDER_RE.match(value.strip()):
            found.append(
                "%s = %r (looks like a [Bracketed Placeholder])"
                % (path or "<root>", value)
            )
    elif isinstance(value, dict):
        for k, v in value.items():
            sub_path = "%s.%s" % (path, k) if path else k
            found.extend(_walk_for_placeholders(v, sub_path))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            sub_path = "%s[%d]" % (path, i)
            found.extend(_walk_for_placeholders(v, sub_path))
    return found


def _validate_zenodo_url(url: str, target: str, *, label: str = "URL") -> str:
    """Refuse non-HTTPS or non-Zenodo URLs returned by the Zenodo API.

    The Zenodo create_deposition response includes links.bucket / links.publish
    that we then POST/PUT against with our deposit:write token. A MITM (or
    response tampering) could swap these to attacker-controlled hosts and
    leak the token. Since we know the host already, we whitelist it.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise RuntimeError(
            "Refusing %s with non-HTTPS scheme: %s" % (label, url)
        )
    expected = ZENODO_EXPECTED_HOSTS[target]
    if parsed.netloc != expected:
        raise RuntimeError(
            "Refusing %s with unexpected host %s (expected %s): %s"
            % (label, parsed.netloc, expected, url)
        )
    return url


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_zenodo_metadata(zenodo_json: Path) -> dict[str, Any]:
    """Load and validate .zenodo.json.

    Raises ValueError if:
      - The file is missing or unparseable
      - Any string value contains a placeholder marker (e.g., [Author Name])
      - Required fields (title, creators, license, upload_type) are missing

    Returns
    -------
    dict
        The parsed metadata.
    """
    zenodo_json = Path(zenodo_json)
    if not zenodo_json.exists():
        raise FileNotFoundError(".zenodo.json not found at %s" % zenodo_json)

    try:
        metadata = json.loads(zenodo_json.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError("Failed to parse %s: %s" % (zenodo_json, exc)) from exc

    placeholders = _walk_for_placeholders(metadata)
    if placeholders:
        raise ValueError(
            ".zenodo.json contains %d placeholder field(s) — refusing to "
            "publish until they are filled with real values:\n  - %s"
            % (len(placeholders), "\n  - ".join(placeholders))
        )

    # Required-field check
    required_top = {"title", "creators", "license", "upload_type"}
    missing = required_top - set(metadata.keys())
    if missing:
        raise ValueError(
            ".zenodo.json missing required top-level fields: %s"
            % sorted(missing)
        )

    if not isinstance(metadata["creators"], list) or not metadata["creators"]:
        raise ValueError(
            ".zenodo.json 'creators' must be a non-empty list"
        )

    for i, creator in enumerate(metadata["creators"]):
        if not isinstance(creator, dict) or "name" not in creator:
            raise ValueError(
                ".zenodo.json creators[%d] missing required 'name' field" % i
            )
        if "affiliation" not in creator:
            raise ValueError(
                ".zenodo.json creators[%d] missing 'affiliation' field" % i
            )

    logger.info(
        "Loaded .zenodo.json: %d creator(s), license=%s, upload_type=%s",
        len(metadata["creators"]),
        metadata["license"],
        metadata["upload_type"],
    )
    return metadata


def fetch_from_hf(
    repo_id: str,
    revision: str,
    target_dir: Path,
    hf_token: str | None = None,
) -> Path:
    """Fetch the parquet tree from HuggingFace into target_dir.

    Thin wrapper around huggingface_hub.snapshot_download with the same
    allow_patterns as database.fetch_processed_data.
    """
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    if hf_token is None:
        hf_token = os.environ.get("HF_TOKEN")

    from huggingface_hub import snapshot_download  # noqa: PLC0415

    logger.info("Fetching %s @ %s -> %s", repo_id, revision, target_dir)
    snapshot_download(
        repo_id=repo_id,
        repo_type="dataset",
        revision=revision,
        local_dir=str(target_dir),
        allow_patterns=["**/*.parquet", "manifest.json", "README.md"],
        token=hf_token,
    )
    return target_dir


def create_zenodo_deposition(
    metadata: dict[str, Any],
    *,
    target: str,
    zenodo_token: str,
) -> dict[str, Any]:
    """Create an empty Zenodo deposition and PUT the metadata onto it.

    Parameters
    ----------
    metadata : dict
        Loaded .zenodo.json content.
    target : str
        "sandbox" or "production".
    zenodo_token : str
        OAuth token with deposit:write scope.

    Returns
    -------
    dict
        The deposition object as returned by Zenodo (includes id, links).
    """
    if target not in ZENODO_BASE_URLS:
        raise ValueError("Invalid target %r — must be sandbox or production" % target)

    base = ZENODO_BASE_URLS[target]
    headers = {
        "Authorization": "Bearer %s" % zenodo_token,
        "Content-Type": "application/json",
    }

    import requests  # noqa: PLC0415

    # Step 1: create empty deposition
    logger.info("Creating empty deposition on %s", base)
    create_resp = requests.post(
        "%s/api/deposit/depositions" % base,
        headers=headers,
        data="{}",
        timeout=60,
    )
    create_resp.raise_for_status()
    deposition = create_resp.json()
    dep_id = deposition["id"]
    logger.info("Deposition created: id=%d", dep_id)

    # Step 2: PUT metadata onto the deposition
    logger.info("Setting metadata on deposition %d", dep_id)
    meta_resp = requests.put(
        "%s/api/deposit/depositions/%d" % (base, dep_id),
        headers=headers,
        data=json.dumps({"metadata": metadata}),
        timeout=60,
    )
    meta_resp.raise_for_status()
    deposition = meta_resp.json()
    return deposition


def upload_files(
    deposition: dict[str, Any],
    files_dir: Path,
    *,
    target: str,
    zenodo_token: str,
) -> list[dict[str, Any]]:
    """Upload every parquet/manifest/README file from files_dir to the deposition.

    Files matching SKIP_PATTERNS are ignored.

    Returns
    -------
    list[dict]
        One Zenodo file response per uploaded file.
    """
    files_dir = Path(files_dir)
    base = ZENODO_BASE_URLS[target]
    headers = {"Authorization": "Bearer %s" % zenodo_token}

    raw_bucket_url = deposition.get("links", {}).get("bucket")
    raw_files_url = deposition.get("links", {}).get("files")
    # Whitelist the response URLs to the expected Zenodo host before sending
    # the deposit:write token to them.
    bucket_url = (
        _validate_zenodo_url(raw_bucket_url, target, label="bucket URL")
        if raw_bucket_url else None
    )
    files_url = (
        _validate_zenodo_url(raw_files_url, target, label="files URL")
        if raw_files_url else None
    )

    import requests  # noqa: PLC0415

    uploads: list[dict[str, Any]] = []

    candidates = sorted(files_dir.rglob("*"))
    for path in candidates:
        if not path.is_file():
            continue
        if any(path.name == skip for skip in SKIP_PATTERNS):
            logger.debug("Skipping %s (matches SKIP_PATTERNS)", path.name)
            continue

        rel = path.relative_to(files_dir).as_posix()
        size_mb = path.stat().st_size / 1024 / 1024
        logger.info("Uploading %s (%.2f MB)", rel, size_mb)

        # Prefer the new bucket-based PUT API; fall back to multipart POST
        # if the deposition does not expose a bucket link.
        if bucket_url:
            with path.open("rb") as fh:
                resp = requests.put(
                    "%s/%s" % (bucket_url.rstrip("/"), rel),
                    headers=headers,
                    data=fh,
                    timeout=600,
                )
            resp.raise_for_status()
        else:
            with path.open("rb") as fh:
                resp = requests.post(
                    files_url,
                    headers=headers,
                    data={"name": rel},
                    files={"file": (rel, fh)},
                    timeout=600,
                )
            resp.raise_for_status()

        uploads.append(resp.json() if resp.text else {"name": rel})

    logger.info("Uploaded %d files", len(uploads))
    return uploads


def publish_deposition(
    deposition: dict[str, Any],
    *,
    target: str,
    zenodo_token: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """POST the publish action on a Zenodo deposition (mints DOI).

    If dry_run=True, logs the planned action and returns the input
    deposition unchanged.
    """
    base = ZENODO_BASE_URLS[target]
    raw_publish_url = deposition.get("links", {}).get("publish")
    if raw_publish_url:
        publish_url = _validate_zenodo_url(
            raw_publish_url, target, label="publish URL",
        )
    else:
        publish_url = "%s/api/deposit/depositions/%d/actions/publish" % (
            base, deposition["id"],
        )

    if dry_run:
        logger.info(
            "[dry-run] Would POST publish to %s (would mint a real DOI on %s)",
            publish_url, target,
        )
        return deposition

    import requests  # noqa: PLC0415

    headers = {"Authorization": "Bearer %s" % zenodo_token}
    logger.info("Publishing deposition %d on %s", deposition["id"], target)
    resp = requests.post(publish_url, headers=headers, timeout=60)
    resp.raise_for_status()
    published = resp.json()
    doi = published.get("doi") or published.get("metadata", {}).get("doi")
    logger.info("Published! DOI: %s", doi)
    return published


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the HF → Zenodo mirror flow."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Mirror ICSKG-BR processed dataset from HuggingFace to Zenodo",
    )
    parser.add_argument(
        "--repo-id",
        default=DEFAULT_REPO_ID,
        help="HuggingFace dataset repo id",
    )
    parser.add_argument(
        "--revision",
        required=True,
        help="HF dataset revision tag (e.g., v0.1.0)",
    )
    parser.add_argument(
        "--target",
        required=True,
        choices=["sandbox", "production"],
        help="Zenodo target (sandbox = test/throwaway DOIs, production = real DOIs)",
    )
    parser.add_argument(
        "--zenodo-json",
        type=Path,
        default=Path(".zenodo.json"),
        help="Path to .zenodo.json (default: .zenodo.json in cwd)",
    )
    parser.add_argument(
        "--working-dir",
        type=Path,
        default=None,
        help="Local working dir for the HF snapshot (default: ~/.cache/icskg-zenodo/{revision})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Create deposition + upload files but skip the publish action",
    )
    args = parser.parse_args(argv)

    # Step 1: validate metadata BEFORE any network call
    metadata = load_zenodo_metadata(args.zenodo_json)

    # Step 2: resolve tokens
    zenodo_token = _resolve_zenodo_token(args.target)

    # Step 3: fetch from HF
    working_dir = args.working_dir or (
        Path.home() / ".cache" / "icskg-zenodo" / args.revision
    )
    fetch_from_hf(
        repo_id=args.repo_id,
        revision=args.revision,
        target_dir=working_dir,
    )

    # Step 4: create deposition
    deposition = create_zenodo_deposition(
        metadata=metadata,
        target=args.target,
        zenodo_token=zenodo_token,
    )

    # Step 5: upload files
    upload_files(
        deposition=deposition,
        files_dir=working_dir,
        target=args.target,
        zenodo_token=zenodo_token,
    )

    # Step 6: publish (or dry-run)
    published = publish_deposition(
        deposition=deposition,
        target=args.target,
        zenodo_token=zenodo_token,
        dry_run=args.dry_run,
    )

    if not args.dry_run:
        doi = published.get("doi") or published.get("metadata", {}).get("doi")
        web_url = published.get("links", {}).get("html") or (
            "%s/record/%s" % (ZENODO_BASE_URLS[args.target], deposition["id"])
        )
        logger.info("─" * 70)
        logger.info("Mirror complete.")
        logger.info("  DOI: %s", doi)
        logger.info("  URL: %s", web_url)
        logger.info("─" * 70)
    else:
        logger.info("─" * 70)
        logger.info("Dry run complete. Deposition id %d created on %s",
                    deposition["id"], args.target)
        logger.info("Visit %s/me/uploads to inspect the draft.",
                    ZENODO_BASE_URLS[args.target])
        logger.info("─" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
