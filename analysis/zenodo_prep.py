"""
ICSKG-BR Zenodo Release Preparation
=====================================
Generates Zenodo metadata JSON and a step-by-step release checklist
for archiving the ICSKG-BR database and analysis outputs.

Outputs
-------
  results/zenodo_metadata.json  -- Zenodo upload metadata
  .zenodo.json                  -- Project root copy for GitHub integration
  results/release_checklist.md  -- Step-by-step release instructions

Usage
-----
    python analysis/zenodo_prep.py --out-dir results

Exports
-------
    generate_zenodo_metadata(out_dir) -> Path
    generate_release_checklist(out_dir) -> Path
    main(argv) -> int
"""

import argparse
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


# ---------------------------------------------------------------------------
# Zenodo metadata
# ---------------------------------------------------------------------------

ZENODO_METADATA: dict = {
    "title": (
        "ICSKG-BR: Index of Cities' Smartness & Knowledge for Global "
        "Surgery -- Brazil (2015-2023)"
    ),
    "upload_type": "dataset",
    "publication_type": "",
    "description": (
        "<p>The ICSKG-BR (Index of Cities' Smartness &amp; Knowledge "
        "for Global Surgery &mdash; Brazil) is a longitudinal ecological "
        "panel study that operationalises the IESE Cities in Motion "
        "Index (CIMI) 9-dimension framework as a Composite Urban "
        "Development Score (CUDS) and validates it against Lancet "
        "Commission on Global Surgery (LCoGS) indicators across all "
        "5,570 Brazilian municipalities from 2015 to 2023.</p>"
        "<p>This dataset contains:</p>"
        "<ul>"
        "<li>The assembled municipality-year panel (50,130 observations)"
        "</li>"
        "<li>8 CIMI dimension scores with within-year min-max "
        "normalisation</li>"
        "<li>CUDS composite via geometric mean</li>"
        "<li>6 LCoGS indicators at municipal level</li>"
        "<li>Municipality lookup, deflation log, imputation log</li>"
        "</ul>"
        "<p>All data are publicly sourced from Brazilian government "
        "agencies under Lei de Acesso a Informacao (Law 12.527/2011)."
        "</p>"
    ),
    "creators": [
        {
            "name": "[Author Name]",
            "affiliation": "[Institution]",
            "orcid": "",
        },
    ],
    "keywords": [
        "global surgery",
        "urban development",
        "CIMI",
        "Cities in Motion Index",
        "LCoGS",
        "Lancet Commission on Global Surgery",
        "Brazil",
        "ecological study",
        "panel data",
        "composite index",
        "municipal health",
        "CUDS",
    ],
    "license": "CC-BY-4.0",
    "access_right": "open",
    "language": "eng",
    "related_identifiers": [
        {
            "identifier": "[GitHub URL]",
            "relation": "isSupplementTo",
            "resource_type": "software",
            "scheme": "url",
        },
    ],
    "communities": [
        {"identifier": "global-surgery"},
    ],
    "notes": (
        "This dataset accompanies the manuscript submitted to "
        "BMJ Global Health. All raw data are publicly available "
        "from the source portals listed in the Data Availability "
        "Statement."
    ),
    "version": "1.0.0",
}


# ---------------------------------------------------------------------------
# Release checklist
# ---------------------------------------------------------------------------

RELEASE_CHECKLIST = """\
# ICSKG-BR Release Checklist

Follow these steps to create the Zenodo deposit and GitHub release.

## Pre-release Verification

- [ ] All analysis outputs regenerated and verified
- [ ] STROBE (22 items) and RECORD (13 items) checklists complete
- [ ] Data dictionary matches SQLite schema (validation passes)
- [ ] Ethics statement and data availability statement reviewed
- [ ] All tests pass: `uv run pytest -x`

## Zenodo Deposit

1. [ ] Go to https://zenodo.org/deposit/new
2. [ ] Upload `database/icskg_br.sqlite` (primary dataset)
3. [ ] Upload `results/` directory as a ZIP archive (supplementary)
4. [ ] Copy metadata from `results/zenodo_metadata.json`:
   - Title, description, creators, keywords, license
5. [ ] Set access right to "Open Access"
6. [ ] Set license to "Creative Commons Attribution 4.0 International"
7. [ ] Save draft (do NOT publish yet)
8. [ ] Copy the reserved DOI

## Update References

9. [ ] Paste reserved DOI into `results/statements/data_availability.txt`
   - Replace `[Zenodo DOI]` with actual DOI (e.g., `10.5281/zenodo.XXXXXXX`)
10. [ ] Update `[GitHub URL]` in data availability statement
11. [ ] Update `.zenodo.json` related_identifiers if needed
12. [ ] Commit updates:
    ```
    git add results/statements/data_availability.txt .zenodo.json
    git commit -m "docs: add Zenodo DOI and GitHub URL to statements"
    ```

## GitHub Release

13. [ ] Create annotated tag:
    ```
    git tag -a v1.0.0 -m "ICSKG-BR v1.0.0: BMJ Global Health submission"
    ```
14. [ ] Push tag:
    ```
    git push origin v1.0.0
    ```
15. [ ] Create GitHub Release from the tag (include release notes)

## Finalise Zenodo

16. [ ] Return to Zenodo deposit
17. [ ] Verify all files are uploaded
18. [ ] Publish the deposit to mint the DOI
19. [ ] Verify DOI resolves correctly

## Post-release

20. [ ] Verify Zenodo DOI in data availability statement matches
21. [ ] Verify GitHub release tag is accessible
22. [ ] Submit manuscript to BMJ Global Health
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_zenodo_metadata(out_dir: Path) -> Path:
    """Generate Zenodo metadata JSON for the ICSKG-BR dataset.

    Writes to both results/zenodo_metadata.json and .zenodo.json
    at the project root for GitHub-Zenodo integration.

    Parameters
    ----------
    out_dir : Path
        Root output directory.

    Returns
    -------
    Path
        Path to the saved JSON file in the output directory.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Write to results directory
    json_path = out_dir / "zenodo_metadata.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(ZENODO_METADATA, f, indent=2, ensure_ascii=False)

    # Also write to project root for GitHub-Zenodo integration
    root_path = Path(".zenodo.json")
    with open(root_path, "w", encoding="utf-8") as f:
        json.dump(ZENODO_METADATA, f, indent=2, ensure_ascii=False)

    logger.info(
        "generate_zenodo_metadata: saved to %s and %s",
        json_path, root_path,
    )
    return json_path


def generate_release_checklist(out_dir: Path) -> Path:
    """Generate a markdown release checklist for Zenodo + GitHub.

    Parameters
    ----------
    out_dir : Path
        Root output directory.

    Returns
    -------
    Path
        Path to the saved markdown file.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    md_path = out_dir / "release_checklist.md"
    md_path.write_text(RELEASE_CHECKLIST, encoding="utf-8")

    logger.info(
        "generate_release_checklist: saved to %s", md_path,
    )
    return md_path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Generate Zenodo metadata and release checklist.

    Usage
    -----
        python analysis/zenodo_prep.py --out-dir results
    """
    parser = argparse.ArgumentParser(
        description="ICSKG-BR Zenodo release preparation",
    )
    parser.add_argument(
        "--out-dir",
        default="results",
        help="Output directory (default: results)",
    )
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)

    logger.info("=" * 60)
    logger.info("ZENODO RELEASE PREPARATION")
    logger.info("=" * 60)

    json_path = generate_zenodo_metadata(out_dir)
    md_path = generate_release_checklist(out_dir)

    logger.info("─" * 60)
    logger.info("Outputs:")
    logger.info("  Zenodo metadata: %s", json_path)
    logger.info("  Release checklist: %s", md_path)
    logger.info("─" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
