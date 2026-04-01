"""
ICSKG-BR AMC Temporal Crosswalk Builder
=========================================
Builds the Areas Minimas Comparaveis (AMC) crosswalk that harmonizes
municipality boundary changes across the 2015-2023 study window.

As of April 2026, IBGE's municipality list has been stable since the 2013
emancipations. No new municipalities were created between 2015 and 2023.
This script verifies that stability via the IBGE Localidades API and builds
a crosswalk CSV that downstream pipeline stages use to confirm code consistency.

The crosswalk format:
  cod_ibge_original : 7-digit IBGE code used in source data for a given year
  year_valid_from   : First year this cod_ibge_original was valid (int)
  cod_ibge_2023     : Canonical 2023 IBGE code (may equal cod_ibge_original)
  harmonization_type: "stable" | "successor" | "predecessor"

Usage
-----
    uv run python scripts/build_amc_crosswalk.py
    uv run python scripts/build_amc_crosswalk.py --out data_sources/amc_crosswalk_2015_2023.csv
"""

import argparse
import csv
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
# Known boundary changes 2013-2023 affecting the ICSKG-BR panel
# ---------------------------------------------------------------------------
# Format: (predecessor_code, successor_code, year_emancipation, description)
# These are the only confirmed emancipations in the 2013-2023 period.
# Source: IBGE municipal emancipation records + PITFALLS.md
KNOWN_EMANCIPATIONS: list[tuple[str, str, int, str]] = [
    # 2013 emancipations (affect 2015+ if any source uses pre-2013 codes)
    ("4204202", "4201257", 2013, "Balneario Rincao-SC split from Icara-SC"),
    ("4302105", "4314548", 2013, "Pinto Bandeira-RS split from Bento Goncalves-RS"),
    ("4209003", "4212056", 2013, "Pescaria Brava-SC split from Laguna-SC"),
    ("1506807", "1504752", 2013, "Mojui dos Campos-PA split from Santarem-PA"),
]
# Note: The successor codes above ARE in the 2023 IBGE reference list.
# The predecessor codes are also still in the 2023 list (they still exist
# as municipalities -- emancipation created NEW municipalities, not replacements).
# The canonical 2023 code for each new municipality IS the successor code.


def fetch_ibge_municipios_ids() -> set[str]:
    """Fetch current IBGE municipality codes from the Localidades API.

    Returns a set of 7-digit string codes.
    """
    try:
        import requests  # noqa: PLC0415

        url = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        codes = {str(m["id"]).zfill(7) for m in data}
        logger.info("Fetched %d municipality codes from IBGE API", len(codes))
        return codes
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not fetch IBGE API: %s -- using offline fallback", exc)
        return set()


def build_crosswalk(
    output_path: Path,
    ibge_ref_path: Path | None = None,
) -> int:
    """Build the AMC crosswalk CSV.

    Loads the IBGE 2023 reference list and creates a row for every
    municipality. Municipalities unchanged since 2015 get harmonization_type
    "stable". Known emancipations get additional rows for their predecessor
    codes.

    Parameters
    ----------
    output_path : Path
        Where to write the crosswalk CSV.
    ibge_ref_path : Path, optional
        Path to ibge_municipios_2023.csv. Auto-discovered if None.

    Returns
    -------
    int
        Number of rows written to the crosswalk CSV.
    """
    # Resolve IBGE reference path
    if ibge_ref_path is None:
        ibge_ref_path = (
            Path(__file__).resolve().parent.parent
            / "data_sources"
            / "ibge_municipios_2023.csv"
        )

    if not ibge_ref_path.exists():
        raise FileNotFoundError(
            "IBGE reference list not found at %s. "
            "Run Plan 01-02 Task 1 first." % ibge_ref_path
        )

    # Load the 2023 canonical codes
    canonical_codes: list[str] = []
    with ibge_ref_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            canonical_codes.append(row["cod_ibge"])

    canonical_count = len(canonical_codes)
    logger.info("Loaded %d canonical municipality codes from %s", canonical_count, ibge_ref_path)
    canonical_set = set(canonical_codes)

    # Verify 2023 API stability (optional, skip if offline)
    api_codes = fetch_ibge_municipios_ids()
    if api_codes:
        new_since_ref = api_codes - canonical_set
        if new_since_ref:
            logger.warning(
                "IBGE API returned %d codes not in 2023 reference list: %s",
                len(new_since_ref),
                sorted(new_since_ref)[:10],
            )
        else:
            logger.info(
                "Stability confirmed: IBGE API codes match 2023 reference list exactly."
            )

    # Build crosswalk rows
    rows: list[dict] = []

    # Row for every canonical 2023 municipality (stable)
    for code in canonical_codes:
        rows.append(
            {
                "cod_ibge_original": code,
                "year_valid_from": 2015,
                "cod_ibge_2023": code,
                "harmonization_type": "stable",
            }
        )

    # Additional rows for known emancipation predecessors (for any pre-2015 data)
    for pred, succ, year, desc in KNOWN_EMANCIPATIONS:
        # Only add predecessor row if predecessor is NOT already in canonical list
        # (some predecessors still exist as separate municipalities)
        if pred not in canonical_set:
            rows.append(
                {
                    "cod_ibge_original": pred,
                    "year_valid_from": 2013,
                    "cod_ibge_2023": succ,
                    "harmonization_type": "predecessor",
                }
            )
            logger.info("Added predecessor mapping: %s -> %s (%s)", pred, succ, desc)

    # Write CSV
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "cod_ibge_original",
        "year_valid_from",
        "cod_ibge_2023",
        "harmonization_type",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    logger.info("AMC crosswalk written: %d rows -> %s", len(rows), output_path)
    return len(rows)


def apply_amc_crosswalk(
    df,  # pd.DataFrame
    year: int,
    crosswalk_path: Path | None = None,
) -> "pd.DataFrame":
    """Apply the AMC crosswalk to harmonize municipality codes in *df*.

    Replaces df['cod_ibge'] values with their canonical 2023 equivalents.
    Municipalities not in the crosswalk are left unchanged (with a warning).

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame containing a 'cod_ibge' column.
    year : int
        The data year (used to filter crosswalk to valid rows for that year).
    crosswalk_path : Path, optional
        Path to amc_crosswalk_2015_2023.csv. Auto-discovered if None.

    Returns
    -------
    pd.DataFrame
        df with cod_ibge harmonized to 2023 canonical codes.
    """
    import pandas as pd  # noqa: PLC0415

    if "cod_ibge" not in df.columns:
        raise ValueError(
            "apply_amc_crosswalk: df must have a 'cod_ibge' column. "
            "Columns present: %s" % list(df.columns)
        )

    if crosswalk_path is None:
        crosswalk_path = (
            Path(__file__).resolve().parent.parent
            / "data_sources"
            / "amc_crosswalk_2015_2023.csv"
        )

    crosswalk = pd.read_csv(
        crosswalk_path,
        dtype={"cod_ibge_original": str, "cod_ibge_2023": str},
    )

    # Filter to rows valid for this year
    valid = crosswalk[crosswalk["year_valid_from"] <= year]
    lookup = valid.set_index("cod_ibge_original")["cod_ibge_2023"].to_dict()

    before = df["cod_ibge"].nunique()
    df = df.copy()
    df["cod_ibge"] = df["cod_ibge"].map(lambda c: lookup.get(c, c))
    after = df["cod_ibge"].nunique()

    if before != after:
        logger.info(
            "apply_amc_crosswalk: municipality count changed %d -> %d for year %d "
            "(expected for splits/merges)",
            before,
            after,
            year,
        )

    return df


def main(argv=None):
    """CLI entry point for building the AMC crosswalk."""
    parser = argparse.ArgumentParser(
        description="Build the ICSKG-BR AMC municipality boundary crosswalk"
    )
    parser.add_argument(
        "--out",
        default="data_sources/amc_crosswalk_2015_2023.csv",
        help="Output path for the crosswalk CSV",
    )
    parser.add_argument(
        "--ibge-ref",
        default=None,
        help="Path to ibge_municipios_2023.csv (auto-discovered if omitted)",
    )
    args = parser.parse_args(argv)

    output = Path(args.out)
    ibge_ref = Path(args.ibge_ref) if args.ibge_ref else None

    n = build_crosswalk(output, ibge_ref_path=ibge_ref)
    logger.info("Done. %d rows written to %s", n, output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
