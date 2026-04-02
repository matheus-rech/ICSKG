"""
IPEA IDHM Extraction Pipeline
===============================
Fetches the UNDP/IPEA Human Development Index (IDHM) for Brazilian
municipalities from the IPEA OData4 API and writes a standardised Parquet
file for the Human Capital (D3) dimension of the ICSKG-BR panel.

**CRITICAL -- Cross-sectional data only:**
IDHM is computed from decennial census microdata. As of 2026 only the
1991, 2000, and 2010 rounds have been published; the 2022 round has NOT
been released yet (the Atlas do Desenvolvimento Humano awaits Census 2022
processing). This script therefore extracts **2010 data only** as a single
cross-sectional snapshot. The resulting Parquet is NOT a panel -- it is a
static municipality attribute that does not vary across the 2015-2023
study period.

Do NOT interpolate between census years. The locked project decision is
to use 2010 values as-is and document the limitation in the paper.

**CRITICAL -- Raw OData API, NOT ipeadatapy:**
The ipeadatapy.timeseries() function strips the TERCODIGO field, making
it impossible to identify which municipality each value belongs to. This
script uses raw ``requests`` calls to the IPEA OData4 endpoint to
preserve territory codes.

Outputs
-------
    data_sources/processed/ipea_idhm/idhm_2010.parquet

Columns: cod_ibge (str 7-digit), year (int), idhm (float),
         idhm_educacao (float), idhm_longevidade (float), idhm_renda (float)

Usage
-----
    python scripts/extract_ipea_idhm.py
    python scripts/extract_ipea_idhm.py --target-year 2010 --output-dir data_sources/processed/ipea_idhm/
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import pandas as pd
import requests  # noqa: PLC0415

from database.utils import normalize_cod_ibge  # noqa: PLC0415
from database.validation import validate_dataframe  # noqa: PLC0415

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IPEA_ODATA_BASE = "http://www.ipeadata.gov.br/api/odata4/"

IDHM_SERIES: dict[str, str] = {
    "ADH_IDHM": "idhm",
    "ADH_IDHM_E": "idhm_educacao",
    "ADH_IDHM_L": "idhm_longevidade",
    "ADH_IDHM_R": "idhm_renda",
}

MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds


# ---------------------------------------------------------------------------
# HTTP helper with retry
# ---------------------------------------------------------------------------

def _get_with_retry(url: str, timeout: int = 120) -> requests.Response:
    """HTTP GET with exponential backoff retry.

    Parameters
    ----------
    url : str
        Target URL.
    timeout : int
        Request timeout in seconds.

    Returns
    -------
    requests.Response
        Successful HTTP response.

    Raises
    ------
    RuntimeError
        If all retry attempts are exhausted.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as exc:  # noqa: BLE001
            if attempt == MAX_RETRIES:
                raise RuntimeError(
                    "Failed to fetch %s after %d attempts: %s" % (url, MAX_RETRIES, exc)
                ) from exc
            delay = RETRY_DELAY * (2 ** (attempt - 1))
            logger.warning(
                "Attempt %d/%d failed for %s: %s -- retrying in %ds",
                attempt, MAX_RETRIES, url, exc, delay,
            )
            time.sleep(delay)
    # Should not reach here, but satisfy type checker
    raise RuntimeError("Unreachable")  # pragma: no cover


# ---------------------------------------------------------------------------
# Core extraction functions
# ---------------------------------------------------------------------------

def fetch_idhm_series(
    series_code: str,
    target_year: int = 2010,
) -> pd.DataFrame:
    """Fetch a single IDHM series from the IPEA OData4 API.

    Parameters
    ----------
    series_code : str
        IPEA series code (e.g., "ADH_IDHM").
    target_year : int
        Census year to extract (default 2010).

    Returns
    -------
    pd.DataFrame
        DataFrame with columns [cod_ibge, <series_column>] where
        <series_column> is the mapped name from IDHM_SERIES.
    """
    col_name = IDHM_SERIES.get(series_code, series_code.lower())
    url = "%sValoresSerie(SERCODIGO='%s')" % (IPEA_ODATA_BASE, series_code)
    logger.info("Fetching IDHM series %s from %s", series_code, url)

    resp = _get_with_retry(url)
    data = resp.json()
    records = data.get("value", [])

    if not records:
        logger.warning("No records returned for series %s", series_code)
        return pd.DataFrame(columns=["cod_ibge", col_name])

    df = pd.DataFrame(records)

    # -----------------------------------------------------------------
    # Filter: municipality level only (exclude national/state/region)
    # -----------------------------------------------------------------
    if "NIVNOME" in df.columns:
        df = df[df["NIVNOME"] == "Municipios"].copy()
    else:
        logger.warning("NIVNOME column not found -- cannot filter by territory level")

    # -----------------------------------------------------------------
    # Filter: target year only
    # -----------------------------------------------------------------
    if "VALDATA" in df.columns:
        df["_year"] = pd.to_datetime(df["VALDATA"], errors="coerce").dt.year
        df = df[df["_year"] == target_year].copy()
        df = df.drop(columns=["_year"])

    # -----------------------------------------------------------------
    # Rename and normalize
    # -----------------------------------------------------------------
    df = df.rename(columns={"TERCODIGO": "cod_ibge", "VALVALOR": col_name})
    df["cod_ibge"] = normalize_cod_ibge(df["cod_ibge"])
    df[col_name] = pd.to_numeric(df[col_name], errors="coerce")

    logger.info(
        "Series %s: %d municipality rows for year %d",
        series_code, len(df), target_year,
    )
    return df[["cod_ibge", col_name]].reset_index(drop=True)


def extract_idhm(
    target_year: int = 2010,
    output_dir: Path = Path("data_sources/processed/ipea_idhm"),
) -> Path:
    """Extract all IDHM sub-indices and merge into a single Parquet file.

    Parameters
    ----------
    target_year : int
        Census year (default 2010). IDHM 2022 has NOT been published.
    output_dir : Path
        Directory to write the output Parquet file.

    Returns
    -------
    Path
        Path to the written Parquet file.
    """
    logger.info(
        "─" * 65
        + "\n▶ Extracting IDHM for year %d (cross-sectional, non-time-varying)",
        target_year,
    )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # -----------------------------------------------------------------
    # Fetch each series and merge on cod_ibge
    # -----------------------------------------------------------------
    merged: pd.DataFrame | None = None
    for series_code, col_name in IDHM_SERIES.items():
        df = fetch_idhm_series(series_code, target_year=target_year)
        if merged is None:
            merged = df
        else:
            merged = merged.merge(df, on="cod_ibge", how="outer")

    if merged is None or merged.empty:
        logger.error("No IDHM data retrieved for year %d", target_year)
        merged = pd.DataFrame(
            columns=["cod_ibge", "year"] + list(IDHM_SERIES.values())
        )

    # -----------------------------------------------------------------
    # Add year column (cross-sectional -- same value for all rows)
    # -----------------------------------------------------------------
    merged["year"] = target_year

    # -----------------------------------------------------------------
    # Reorder columns
    # -----------------------------------------------------------------
    final_cols = ["cod_ibge", "year"] + list(IDHM_SERIES.values())
    merged = merged[final_cols]

    # -----------------------------------------------------------------
    # Validate
    # -----------------------------------------------------------------
    merged, report = validate_dataframe(
        merged,
        source_name="ipea_idhm",
        strict=False,
    )

    # -----------------------------------------------------------------
    # Write Parquet
    # -----------------------------------------------------------------
    out_path = output_dir / ("idhm_%d.parquet" % target_year)
    merged.to_parquet(out_path, index=False)

    logger.info(
        "%d municipalities with IDHM data for %d "
        "(cross-sectional: does NOT vary across study period)",
        len(merged), target_year,
    )
    logger.info("Output written -> %s", out_path)
    return out_path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """CLI entry point for IDHM extraction.

    Parameters
    ----------
    argv : list[str], optional
        Command-line arguments (defaults to sys.argv[1:]).

    Returns
    -------
    int
        Exit code (0 = success).
    """
    parser = argparse.ArgumentParser(
        description="Extract IPEA IDHM for Brazilian municipalities"
    )
    parser.add_argument(
        "--target-year",
        type=int,
        default=2010,
        help="Census year to extract (default: 2010). "
             "IDHM 2022 has NOT been published.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data_sources/processed/ipea_idhm"),
        help="Output directory for Parquet file",
    )

    args = parser.parse_args(argv)
    extract_idhm(target_year=args.target_year, output_dir=args.output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
