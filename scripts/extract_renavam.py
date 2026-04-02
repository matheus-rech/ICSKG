"""
RENAVAM Vehicle Fleet Extractor -- BEST EFFORT
================================================
Attempts to download and parse vehicle fleet data from the Brazilian
National Vehicle Registry (RENAVAM) via dados.transportes.gov.br.

This is a BEST EFFORT script. The RENAVAM CSV format is LOW confidence.
If the format cannot be parsed or the download fails, the script logs the
gap clearly and writes an empty Parquet file with the expected schema.
Failure does NOT block the pipeline.

Data source
-----------
- Portal: https://dados.transportes.gov.br/dataset/frota-de-veiculos
- Format: CSV (2020-2022), ZIP containing CSV (2024-2026)
- Municipality identification: UF + municipality NAME (not IBGE code)
- Crosswalk needed: municipality name -> IBGE code via load_ibge_municipios()

Output
------
- data_sources/processed/renavam/renavam.parquet
  Columns: cod_ibge (str7), year (int), vehicles_total (float),
           vehicles_per_1000 (float)

Usage
-----
    python scripts/extract_renavam.py
    python scripts/extract_renavam.py --years 2020 2021 2022
    python scripts/extract_renavam.py --output-dir data_sources/processed/renavam/
"""

from __future__ import annotations

import argparse
import io
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

RENAVAM_BASE_URL = "https://dados.transportes.gov.br/dataset/frota-de-veiculos"
# Actual download URLs may require format discovery -- the base URL is a dataset page

# Known URL patterns for RENAVAM data (LOW confidence)
RENAVAM_DOWNLOAD_PATTERNS = [
    "https://dados.transportes.gov.br/dataset/frota-de-veiculos/resource/download/frota_munic_{year}_{month:02d}.csv",
    "https://www.gov.br/transportes/pt-br/assuntos/transito/conteudo-Senatran/frota-de-veiculos-{year}.csv",
]

MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds

# Expected output schema (written even on total failure)
EMPTY_SCHEMA = {
    "cod_ibge": pd.Series(dtype="object"),
    "year": pd.Series(dtype="int64"),
    "vehicles_total": pd.Series(dtype="float64"),
    "vehicles_per_1000": pd.Series(dtype="float64"),
}

# Candidate column names for municipality name
MUNICIPALITY_NAME_CANDIDATES = [
    "Municipio", "MUNICIPIO", "NM_MUNICIPIO", "municipio",
    "NOME_MUNICIPIO", "nome_municipio", "Município",
]

# Candidate column names for UF
UF_CANDIDATES = ["UF", "SIGLA_UF", "uf", "Uf", "sigla_uf"]

# Candidate column names for vehicle total
VEHICLE_TOTAL_CANDIDATES = [
    "TOTAL", "QTD_TOTAL", "QUANTIDADE", "total", "Total",
    "TOTAL_FROTA", "total_frota",
]


# ---------------------------------------------------------------------------
# Municipality crosswalk
# ---------------------------------------------------------------------------

def _build_municipality_crosswalk() -> dict[tuple[str, str], str]:
    """Build (UF_UPPER, NAME_UPPER_STRIPPED) -> cod_ibge crosswalk.

    Uses load_ibge_municipios() reference to map municipality names to IBGE
    codes. This handles Pitfall 9: RENAVAM uses municipality names, not codes.

    Returns
    -------
    dict[tuple[str, str], str]
        Mapping from (UF, municipality_name) in upper case to cod_ibge.
    """
    from database.utils import load_ibge_municipios  # noqa: PLC0415

    ref = load_ibge_municipios()
    crosswalk: dict[tuple[str, str], str] = {}
    for _, row in ref.iterrows():
        key = (str(row["uf"]).upper().strip(), str(row["nome_municipio"]).upper().strip())
        crosswalk[key] = row["cod_ibge"]

    logger.info(
        "_build_municipality_crosswalk: %d entries built from IBGE reference",
        len(crosswalk),
    )
    return crosswalk


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------

def _get_with_retry(url: str, timeout: int = 60) -> bytes | None:
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


def _download_renavam_csv(year: int, output_dir: Path) -> Path | None:
    """Attempt to discover and download RENAVAM data for the given year.

    Tries multiple URL patterns. If download succeeds, saves CSV to
    output_dir. If all attempts fail, logs warning and returns None.

    Parameters
    ----------
    year : int
        Calendar year to download.
    output_dir : Path
        Directory to save downloaded CSV.

    Returns
    -------
    Path | None
        Path to downloaded CSV, or None if all attempts failed.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"renavam_raw_{year}.csv"

    if output_path.exists() and output_path.stat().st_size > 0:
        logger.info("RENAVAM %d already downloaded at %s", year, output_path)
        return output_path

    # Try December of each year (annual snapshot)
    urls_to_try = [
        f"https://dados.transportes.gov.br/dataset/frota-de-veiculos/resource/download/frota_munic_{year}_12.csv",
        f"https://dados.transportes.gov.br/dataset/frota-de-veiculos/resource/download/frota_munic_{year}.csv",
        f"https://dados.transportes.gov.br/dataset/frota-de-veiculos/resource/frota_munic_{year}_12.csv",
    ]

    for url in urls_to_try:
        logger.info("RENAVAM: trying %s", url)
        content = _get_with_retry(url, timeout=120)
        if content is not None and len(content) > 100:
            output_path.write_bytes(content)
            logger.info("RENAVAM %d: downloaded %d bytes -> %s", year, len(content), output_path)
            return output_path

    logger.warning(
        "RENAVAM %d: all download attempts failed. "
        "URLs tried: %s. Gap will be documented.",
        year, urls_to_try,
    )
    return None


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------

def _parse_renavam_csv(
    path: Path,
    crosswalk: dict[tuple[str, str], str],
    year: int,
) -> pd.DataFrame | None:
    """Attempt to read and parse a RENAVAM CSV file.

    Tries multiple encodings and separators. Matches municipality names
    to IBGE codes via crosswalk. Returns None if parsing fails.

    Parameters
    ----------
    path : Path
        Path to the downloaded CSV file.
    crosswalk : dict
        Municipality name-to-code crosswalk from _build_municipality_crosswalk().
    year : int
        Calendar year for the data.

    Returns
    -------
    pd.DataFrame | None
        Parsed DataFrame with columns [cod_ibge, year, vehicles_total],
        or None if parsing failed at any step.
    """
    # Try different encodings and separators
    df = None
    for encoding in ["utf-8", "latin-1", "cp1252"]:
        for sep in [",", ";", "\t"]:
            try:
                df = pd.read_csv(path, encoding=encoding, sep=sep, dtype=str)
                if len(df.columns) > 2:
                    logger.info(
                        "RENAVAM %d: parsed with encoding=%s, sep=%r, "
                        "columns=%s, rows=%d",
                        year, encoding, sep, list(df.columns), len(df),
                    )
                    break
                df = None
            except Exception:  # noqa: BLE001
                df = None
                continue
        if df is not None:
            break

    if df is None:
        logger.error("RENAVAM %d: failed to parse CSV at %s", year, path)
        return None

    # Find municipality name column
    name_col = None
    for candidate in MUNICIPALITY_NAME_CANDIDATES:
        if candidate in df.columns:
            name_col = candidate
            break
    if name_col is None:
        logger.error(
            "RENAVAM %d: no municipality name column found. "
            "Columns present: %s. Expected one of: %s",
            year, list(df.columns), MUNICIPALITY_NAME_CANDIDATES,
        )
        return None

    # Find UF column
    uf_col = None
    for candidate in UF_CANDIDATES:
        if candidate in df.columns:
            uf_col = candidate
            break
    if uf_col is None:
        logger.error(
            "RENAVAM %d: no UF column found. Columns present: %s",
            year, list(df.columns),
        )
        return None

    # Find vehicle total column
    total_col = None
    for candidate in VEHICLE_TOTAL_CANDIDATES:
        if candidate in df.columns:
            total_col = candidate
            break

    if total_col is None:
        # Try to sum all numeric columns (vehicle type counts)
        logger.info("RENAVAM %d: no total column found, attempting to sum numeric columns", year)
        numeric_cols = []
        for col in df.columns:
            if col not in (name_col, uf_col) and col not in ("ANO", "MES", "REGIAO", "ano", "mes"):
                try:
                    test = pd.to_numeric(df[col].head(10).str.replace(".", "", regex=False).str.replace(",", ".", regex=False), errors="coerce")
                    if test.notna().sum() > 5:
                        numeric_cols.append(col)
                except Exception:  # noqa: BLE001
                    continue
        if numeric_cols:
            logger.info("RENAVAM %d: summing %d numeric columns for total", year, len(numeric_cols))
            for col in numeric_cols:
                df[col] = pd.to_numeric(
                    df[col].str.replace(".", "", regex=False).str.replace(",", ".", regex=False),
                    errors="coerce",
                )
            df["_vehicles_total"] = df[numeric_cols].sum(axis=1)
            total_col = "_vehicles_total"
        else:
            logger.error("RENAVAM %d: no vehicle count columns found", year)
            return None

    # Normalize total column to numeric
    if total_col != "_vehicles_total":
        df[total_col] = pd.to_numeric(
            df[total_col].astype(str).str.replace(".", "", regex=False).str.replace(",", ".", regex=False),
            errors="coerce",
        )

    # Match municipality names to IBGE codes via crosswalk
    df["_uf_upper"] = df[uf_col].str.upper().str.strip()
    df["_name_upper"] = df[name_col].str.upper().str.strip()
    df["cod_ibge"] = df.apply(
        lambda row: crosswalk.get((row["_uf_upper"], row["_name_upper"])),
        axis=1,
    )

    matched = df["cod_ibge"].notna().sum()
    unmatched = df["cod_ibge"].isna().sum()
    logger.info(
        "RENAVAM %d: crosswalk matched %d/%d municipalities (%d unmatched)",
        year, matched, matched + unmatched, unmatched,
    )

    # Filter to matched rows only
    df = df[df["cod_ibge"].notna()].copy()
    if df.empty:
        logger.warning("RENAVAM %d: no municipalities matched after crosswalk", year)
        return None

    # Normalize cod_ibge
    from database.utils import normalize_cod_ibge  # noqa: PLC0415

    df["cod_ibge"] = normalize_cod_ibge(df["cod_ibge"])
    df["year"] = year
    df["vehicles_total"] = df[total_col].astype(float)

    return df[["cod_ibge", "year", "vehicles_total"]].copy()


# ---------------------------------------------------------------------------
# Main extraction function
# ---------------------------------------------------------------------------

def extract_renavam(
    years: list[int] | None = None,
    output_dir: Path | None = None,
) -> Path:
    """Extract RENAVAM vehicle fleet data for multiple years.

    This is a BEST EFFORT extractor. If download or parsing fails for any
    year, the gap is logged and the script continues. If no years produce
    data, an empty Parquet file with the correct schema is written.

    Parameters
    ----------
    years : list[int], optional
        Calendar years to extract. Default: 2015-2023.
    output_dir : Path, optional
        Directory for output Parquet file. Default: data_sources/processed/renavam/.

    Returns
    -------
    Path
        Path to the output Parquet file (renavam.parquet).
    """
    if years is None:
        years = list(range(2015, 2024))
    if output_dir is None:
        output_dir = Path("data_sources/processed/renavam")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "renavam.parquet"
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    logger.info("─" * 60)
    logger.info("RENAVAM VEHICLE FLEET EXTRACTION (BEST EFFORT)")
    logger.info("─" * 60)
    logger.info("Years: %s", years)
    logger.info("Output: %s", output_path)

    # Build crosswalk
    try:
        crosswalk = _build_municipality_crosswalk()
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to build municipality crosswalk: %s", exc)
        logger.warning("RENAVAM: writing empty schema Parquet due to crosswalk failure")
        pd.DataFrame(EMPTY_SCHEMA).to_parquet(output_path, index=False)
        return output_path

    # Attempt download and parse for each year
    all_frames: list[pd.DataFrame] = []
    years_ok = 0

    for year in years:
        logger.info("▶ RENAVAM %d", year)
        csv_path = _download_renavam_csv(year, raw_dir)
        if csv_path is None:
            continue

        df = _parse_renavam_csv(csv_path, crosswalk, year)
        if df is not None and not df.empty:
            all_frames.append(df)
            years_ok += 1
            logger.info("✓ RENAVAM %d: %d municipalities extracted", year, len(df))
        else:
            logger.warning("RENAVAM %d: parse returned no data", year)

    # Concatenate or write empty schema
    if all_frames:
        result = pd.concat(all_frames, ignore_index=True)

        # Validate if possible
        try:
            from database.validation import validate_dataframe  # noqa: PLC0415

            result, report = validate_dataframe(
                result, source_name="renavam", strict=False,
            )
            logger.info(
                "RENAVAM validation: %d/%d rows valid",
                report.n_valid, report.n_rows_input,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("RENAVAM validation skipped: %s", exc)

        result.to_parquet(output_path, index=False)
        logger.info(
            "RENAVAM: %d/%d years parsed successfully. %d total rows -> %s",
            years_ok, len(years), len(result), output_path,
        )
    else:
        logger.warning(
            "RENAVAM: 0/%d years parsed successfully. "
            "Gap documented for Limitations section. "
            "Writing empty schema Parquet.",
            len(years),
        )
        pd.DataFrame(EMPTY_SCHEMA).to_parquet(output_path, index=False)

    return output_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """CLI entry point for RENAVAM vehicle fleet extraction."""
    parser = argparse.ArgumentParser(
        description="RENAVAM vehicle fleet extraction (BEST EFFORT)",
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
        default=Path("data_sources/processed/renavam"),
        help="Output directory for Parquet files",
    )
    args = parser.parse_args(argv)

    extract_renavam(years=args.years, output_dir=args.output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
