"""
SIOPS Health Expenditure Extractor -- BEST EFFORT
===================================================
Attempts to fetch per-capita municipal health expenditure data from SIOPS
(Sistema de Informacoes sobre Orcamentos Publicos em Saude).

This is a BEST EFFORT script. The SIOPS API format is LOW confidence.
If the API is unreachable or the format is unexpected, the script logs the
gap clearly and writes an empty Parquet file with the expected schema.
Failure does NOT block the pipeline.

Data sources (tried in order)
-----------------------------
1. SIOPS REST API: https://siops-consulta-publica-api.saude.gov.br
2. DATASUS TabNet: http://siops-asp.datasus.gov.br
3. OpenDataSUS: https://dadosabertos.saude.gov.br/dataset/siops

Output
------
- data_sources/processed/siops/siops.parquet
  Columns: cod_ibge (str7), year (int), health_expenditure_per_capita (float)

Usage
-----
    python scripts/extract_siops.py
    python scripts/extract_siops.py --years 2020 2021 2022
    python scripts/extract_siops.py --output-dir data_sources/processed/siops/
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SIOPS_API_BASE = "https://siops-consulta-publica-api.saude.gov.br"
SIOPS_TABNET_BASE = "http://siops-asp.datasus.gov.br"
SIOPS_OPENDATA_BASE = "https://dadosabertos.saude.gov.br/dataset/siops"

MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds
API_TIMEOUT = 30  # seconds (shorter -- API may be down)

# Expected output schema (written even on total failure)
EMPTY_SCHEMA = {
    "cod_ibge": pd.Series(dtype="object"),
    "year": pd.Series(dtype="int64"),
    "health_expenditure_per_capita": pd.Series(dtype="float64"),
}

# Candidate municipality code columns in SIOPS responses
MUNICIPALITY_CODE_CANDIDATES = [
    "COD_MUNICIPIO", "cod_ibge", "CD_MUNICIPIO", "IBGE",
    "cod_ibge_municipio", "co_municipio_ibge",
]


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _get_with_retry(url: str, timeout: int = API_TIMEOUT) -> bytes | None:
    """Fetch *url* with retry logic. Returns raw bytes or None on failure."""
    try:
        import requests  # noqa: PLC0415
    except ImportError:
        logger.error("requests library required. Install with: pip install requests")
        return None

    session = requests.Session()
    headers = {"User-Agent": "ICSKG-BR/2.0 (research; contact: icskg-br@example.org)"}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, timeout=timeout, headers=headers)
            resp.raise_for_status()
            return resp.content
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Attempt %d/%d failed for %s: %s",
                attempt, MAX_RETRIES, url, exc,
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)

    return None


def _get_json_with_retry(url: str, timeout: int = API_TIMEOUT) -> dict | list | None:
    """Fetch *url* and parse JSON. Returns parsed data or None on failure."""
    try:
        import requests  # noqa: PLC0415
    except ImportError:
        logger.error("requests library required. Install with: pip install requests")
        return None

    session = requests.Session()
    headers = {
        "User-Agent": "ICSKG-BR/2.0 (research; contact: icskg-br@example.org)",
        "Accept": "application/json",
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, timeout=timeout, headers=headers)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Attempt %d/%d failed for %s: %s",
                attempt, MAX_RETRIES, url, exc,
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)

    return None


# ---------------------------------------------------------------------------
# API strategy: SIOPS REST API
# ---------------------------------------------------------------------------

def _try_siops_api(year: int) -> pd.DataFrame | None:
    """Attempt to query SIOPS REST API for per-capita health expenditure.

    Tries several known endpoint patterns. If the API responds with
    parseable data, returns a DataFrame. Otherwise returns None.

    Parameters
    ----------
    year : int
        Calendar year to query.

    Returns
    -------
    pd.DataFrame | None
        DataFrame with columns [cod_ibge, health_expenditure_per_capita],
        or None if API is unreachable or format is unexpected.
    """
    logger.info("SIOPS API: attempting year %d", year)

    # Try known endpoint patterns
    endpoints = [
        f"{SIOPS_API_BASE}/api/public/despesas/municipios/{year}",
        f"{SIOPS_API_BASE}/api/public/indicadores/municipios/{year}",
        f"{SIOPS_API_BASE}/api/municipios/despesas?ano={year}",
        f"{SIOPS_API_BASE}/api/v1/municipios/{year}/despesa-per-capita",
    ]

    for endpoint in endpoints:
        logger.info("SIOPS API: trying %s", endpoint)
        data = _get_json_with_retry(endpoint)
        if data is not None:
            logger.info(
                "SIOPS API: got response from %s (type: %s)",
                endpoint, type(data).__name__,
            )
            # Attempt to parse the response
            try:
                if isinstance(data, list) and len(data) > 0:
                    df = pd.DataFrame(data)
                    logger.info(
                        "SIOPS API: parsed %d rows, columns: %s",
                        len(df), list(df.columns),
                    )
                    return _normalize_siops_response(df, year)
                elif isinstance(data, dict):
                    # Maybe data is nested under a key
                    for key in ("data", "results", "items", "municipios"):
                        if key in data and isinstance(data[key], list):
                            df = pd.DataFrame(data[key])
                            logger.info(
                                "SIOPS API: parsed %d rows from '%s' key",
                                len(df), key,
                            )
                            return _normalize_siops_response(df, year)
            except Exception as exc:  # noqa: BLE001
                logger.warning("SIOPS API: failed to parse response from %s: %s", endpoint, exc)

    logger.warning("SIOPS API: all endpoints failed for year %d", year)
    return None


def _normalize_siops_response(df: pd.DataFrame, year: int) -> pd.DataFrame | None:
    """Normalize a SIOPS API response to standard schema.

    Parameters
    ----------
    df : pd.DataFrame
        Raw response DataFrame.
    year : int
        Calendar year for the data.

    Returns
    -------
    pd.DataFrame | None
        Normalized DataFrame or None if required columns not found.
    """
    from database.utils import normalize_cod_ibge  # noqa: PLC0415

    # Find municipality code column
    code_col = None
    for candidate in MUNICIPALITY_CODE_CANDIDATES:
        if candidate in df.columns:
            code_col = candidate
            break
    # Try case-insensitive match
    if code_col is None:
        for col in df.columns:
            if col.lower() in [c.lower() for c in MUNICIPALITY_CODE_CANDIDATES]:
                code_col = col
                break

    if code_col is None:
        logger.warning(
            "SIOPS: no municipality code column found. Columns: %s",
            list(df.columns),
        )
        return None

    # Find expenditure column
    expenditure_col = None
    expenditure_candidates = [
        "despesa_per_capita", "despesa_saude_per_capita",
        "vlr_per_capita", "valor_per_capita",
        "despesa_total_per_capita", "gasto_per_capita",
        "health_expenditure_per_capita",
    ]
    for candidate in expenditure_candidates:
        if candidate in df.columns:
            expenditure_col = candidate
            break
    # Case-insensitive fallback
    if expenditure_col is None:
        for col in df.columns:
            if "per_capita" in col.lower() or "percapita" in col.lower():
                expenditure_col = col
                break
    # Try total expenditure if per capita not found
    if expenditure_col is None:
        for col in df.columns:
            if "despesa" in col.lower() or "gasto" in col.lower() or "expenditure" in col.lower():
                expenditure_col = col
                logger.info("SIOPS: using total expenditure column '%s' (not per-capita)", col)
                break

    if expenditure_col is None:
        logger.warning(
            "SIOPS: no expenditure column found. Columns: %s",
            list(df.columns),
        )
        return None

    result = pd.DataFrame({
        "cod_ibge": normalize_cod_ibge(df[code_col].astype(str)),
        "year": year,
        "health_expenditure_per_capita": pd.to_numeric(df[expenditure_col], errors="coerce"),
    })

    return result[result["cod_ibge"].notna()].copy()


# ---------------------------------------------------------------------------
# Fallback strategy: DATASUS TabNet
# ---------------------------------------------------------------------------

def _try_siops_tabnet(year: int) -> pd.DataFrame | None:
    """Fallback: attempt to download SIOPS data from DATASUS TabNet.

    TabNet provides health expenditure indicators but requires specific
    query parameters. This is a best-effort attempt.

    Parameters
    ----------
    year : int
        Calendar year to query.

    Returns
    -------
    pd.DataFrame | None
        DataFrame or None if unavailable.
    """
    logger.info("SIOPS TabNet: attempting fallback for year %d", year)

    # Try to download CSV from known TabNet patterns
    tabnet_urls = [
        f"{SIOPS_TABNET_BASE}/cgi/siops/cnv/SIOPS_Desp_Saude_Mun_{year}.csv",
        f"https://dadosabertos.saude.gov.br/dataset/siops/resource/download/siops_municipios_{year}.csv",
    ]

    for url in tabnet_urls:
        logger.info("SIOPS TabNet: trying %s", url)
        content = _get_with_retry(url, timeout=60)
        if content is not None and len(content) > 100:
            # Try to parse as CSV
            for encoding in ["utf-8", "latin-1", "cp1252"]:
                for sep in [",", ";", "\t"]:
                    try:
                        import io  # noqa: PLC0415

                        df = pd.read_csv(
                            io.BytesIO(content),
                            encoding=encoding,
                            sep=sep,
                            dtype=str,
                        )
                        if len(df.columns) > 2 and len(df) > 10:
                            logger.info(
                                "SIOPS TabNet: parsed %d rows, columns: %s",
                                len(df), list(df.columns),
                            )
                            return _normalize_siops_response(df, year)
                    except Exception:  # noqa: BLE001
                        continue

    logger.warning("SIOPS TabNet: all attempts failed for year %d", year)
    return None


# ---------------------------------------------------------------------------
# Main extraction function
# ---------------------------------------------------------------------------

def extract_siops(
    years: list[int] | None = None,
    output_dir: Path | None = None,
) -> Path:
    """Extract SIOPS per-capita health expenditure for multiple years.

    This is a BEST EFFORT extractor. Tries the SIOPS REST API first,
    then falls back to DATASUS TabNet. If neither succeeds for any year,
    an empty Parquet file with the correct schema is written.

    Parameters
    ----------
    years : list[int], optional
        Calendar years to extract. Default: 2015-2023.
    output_dir : Path, optional
        Directory for output Parquet file. Default: data_sources/processed/siops/.

    Returns
    -------
    Path
        Path to the output Parquet file (siops.parquet).
    """
    if years is None:
        years = list(range(2015, 2024))
    if output_dir is None:
        output_dir = Path("data_sources/processed/siops")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "siops.parquet"

    logger.info("─" * 60)
    logger.info("SIOPS HEALTH EXPENDITURE EXTRACTION (BEST EFFORT)")
    logger.info("─" * 60)
    logger.info("Years: %s", years)
    logger.info("Output: %s", output_path)

    all_frames: list[pd.DataFrame] = []
    years_ok = 0
    api_connected = False

    for year in years:
        logger.info("▶ SIOPS %d", year)

        # Strategy 1: SIOPS REST API
        df = _try_siops_api(year)
        if df is not None and not df.empty:
            api_connected = True
            all_frames.append(df)
            years_ok += 1
            logger.info("✓ SIOPS %d: %d municipalities extracted (API)", year, len(df))
            continue

        # Strategy 2: DATASUS TabNet fallback
        df = _try_siops_tabnet(year)
        if df is not None and not df.empty:
            all_frames.append(df)
            years_ok += 1
            logger.info("✓ SIOPS %d: %d municipalities extracted (TabNet)", year, len(df))
            continue

        logger.warning("SIOPS %d: no data from API or TabNet", year)

    # Concatenate or write empty schema
    api_status = "connected" if api_connected else "refused/unreachable"

    if all_frames:
        result = pd.concat(all_frames, ignore_index=True)

        # Validate if possible
        try:
            from database.validation import validate_dataframe  # noqa: PLC0415

            result, report = validate_dataframe(
                result, source_name="siops", strict=False,
            )
            logger.info(
                "SIOPS validation: %d/%d rows valid",
                report.n_valid, report.n_rows_input,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("SIOPS validation skipped: %s", exc)

        result.to_parquet(output_path, index=False)
        logger.info(
            "SIOPS: %d/%d years extracted. API status: %s. "
            "%d total rows -> %s",
            years_ok, len(years), api_status, len(result), output_path,
        )
    else:
        logger.warning(
            "SIOPS: 0/%d years extracted. API status: %s. "
            "Gap documented for Limitations section. "
            "Writing empty schema Parquet.",
            len(years), api_status,
        )
        pd.DataFrame(EMPTY_SCHEMA).to_parquet(output_path, index=False)

    return output_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """CLI entry point for SIOPS health expenditure extraction."""
    parser = argparse.ArgumentParser(
        description="SIOPS health expenditure extraction (BEST EFFORT)",
    )
    parser.add_argument(
        "--years",
        nargs="+",
        type=int,
        default=list(range(2015, 2024)),
        help="Calendar years to extract (default: 2015-2023)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data_sources/processed/siops"),
        help="Output directory for Parquet files",
    )
    args = parser.parse_args(argv)

    extract_siops(years=args.years, output_dir=args.output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
