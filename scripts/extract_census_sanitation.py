"""
Census 2022 Sanitation Extraction via IBGE SIDRA API
=====================================================
Extracts adequate sanitation percentage and water supply percentage from the
IBGE Census 2022 SIDRA tables for all Brazilian municipalities.

**IMPORTANT: This data is a single cross-sectional year (2022) applied across
all panel years (2015-2023). It does NOT represent genuine temporal variation.**
The non-time-varying nature must be documented in dimension_metadata and
explicitly flagged in all downstream analyses (locked decision -- see
03-CONTEXT.md).

Sources
-------
    - Table 6805: Domicilios particulares permanentes por tipo de esgotamento
      sanitario. Classification c11558, code 46290 = "Rede geral, pluvial, ou
      fossa ligada" (adequate sanitation).
    - Table 6803: Domicilios particulares permanentes por forma de abastecimento
      de agua. Classification c11556, code 46281 = "Rede geral de distribuicao"
      (adequate water supply).

Outputs
-------
    data_sources/processed/census_sanitation/sanitation_2022.parquet
        Columns: cod_ibge, year, pct_sanitation_adequate, pct_water_adequate

Usage
-----
    python scripts/extract_census_sanitation.py
    python scripts/extract_census_sanitation.py --output-dir data_sources/processed/census_sanitation/
"""

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
# Lazy import of sidrapy (optional dependency)
# ---------------------------------------------------------------------------

try:
    import sidrapy  # noqa: PLC0415
except ImportError:
    sidrapy = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Census 2022 SIDRA table codes
TABLE_SANITATION = "6805"   # Esgotamento sanitario
TABLE_WATER = "6803"        # Abastecimento de agua

# Variable: percentage of permanent occupied households
VAR_PCT = "1000381"

# Classification codes for "adequate" categories
CLASS_SANITATION_ADEQUATE = "46290"  # Rede geral, pluvial, ou fossa ligada
CLASS_WATER_ADEQUATE = "72144"       # Possui ligação à rede geral e a utiliza como forma principal

CENSUS_YEAR = 2022

# Retry configuration for SIDRA API
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds

DEFAULT_OUTPUT_DIR: Path = Path("data_sources/processed/census_sanitation")


# ---------------------------------------------------------------------------
# SIDRA API helpers with retry
# ---------------------------------------------------------------------------

def _sidra_get_with_retry(**kwargs) -> pd.DataFrame:
    """Call sidrapy.get_table() with retry logic.

    Parameters
    ----------
    **kwargs
        Arguments passed to sidrapy.get_table().

    Returns
    -------
    pd.DataFrame
        SIDRA API response as DataFrame.

    Raises
    ------
    RuntimeError
        If all retries are exhausted.
    """
    if sidrapy is None:
        raise ImportError(
            "sidrapy is required for Census data extraction. "
            "Install with: pip install sidrapy"
        )

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            df = sidrapy.get_table(**kwargs)
            return df
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "SIDRA API attempt %d/%d failed for table %s: %s",
                attempt, MAX_RETRIES, kwargs.get("table_code", "?"), exc,
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)

    raise RuntimeError(
        "SIDRA API failed after %d attempts for table %s"
        % (MAX_RETRIES, kwargs.get("table_code", "?"))
    )


# ---------------------------------------------------------------------------
# Core extraction functions
# ---------------------------------------------------------------------------

def fetch_sanitation() -> pd.DataFrame:
    """Fetch adequate sanitation percentage for all municipalities from Census 2022.

    Uses SIDRA table 6805 with classification c11558=46290 (adequate sewage).

    Returns
    -------
    pd.DataFrame
        Columns: cod_ibge (7-digit str), pct_sanitation_adequate (float).
    """
    from database.utils import normalize_cod_ibge  # noqa: PLC0415

    logger.info("Fetching Census 2022 sanitation data (table %s)...", TABLE_SANITATION)

    df = _sidra_get_with_retry(
        table_code=TABLE_SANITATION,
        territorial_level="6",
        ibge_territorial_code="all",
        period="2022",
        variable=VAR_PCT,
        classifications={"11558": CLASS_SANITATION_ADEQUATE},
    )

    # Skip first row (metadata header -- Pitfall 6)
    df = df.iloc[1:]

    # Rename columns
    df = df.rename(columns={"D1C": "cod_ibge", "V": "pct_sanitation_adequate"})

    # Normalize municipality codes
    df["cod_ibge"] = normalize_cod_ibge(df["cod_ibge"])

    # Coerce percentage to numeric (handles "..." as NaN)
    df["pct_sanitation_adequate"] = pd.to_numeric(
        df["pct_sanitation_adequate"], errors="coerce"
    )

    result = df[["cod_ibge", "pct_sanitation_adequate"]].copy()
    logger.info(
        "Sanitation data: %d municipalities (%d with valid values)",
        len(result), result["pct_sanitation_adequate"].notna().sum(),
    )

    return result


def fetch_water_supply() -> pd.DataFrame:
    """Fetch adequate water supply percentage for all municipalities from Census 2022.

    Uses SIDRA table 6803 with classification c11556=46281 (adequate water).

    Returns
    -------
    pd.DataFrame
        Columns: cod_ibge (7-digit str), pct_water_adequate (float).
    """
    from database.utils import normalize_cod_ibge  # noqa: PLC0415

    logger.info("Fetching Census 2022 water supply data (table %s)...", TABLE_WATER)

    df = _sidra_get_with_retry(
        table_code=TABLE_WATER,
        territorial_level="6",
        ibge_territorial_code="all",
        period="2022",
        variable=VAR_PCT,
        classifications={"1821": CLASS_WATER_ADEQUATE},
    )

    # Skip first row (metadata header -- Pitfall 6)
    df = df.iloc[1:]

    # Rename columns
    df = df.rename(columns={"D1C": "cod_ibge", "V": "pct_water_adequate"})

    # Normalize municipality codes
    df["cod_ibge"] = normalize_cod_ibge(df["cod_ibge"])

    # Coerce percentage to numeric (handles "..." as NaN)
    df["pct_water_adequate"] = pd.to_numeric(
        df["pct_water_adequate"], errors="coerce"
    )

    result = df[["cod_ibge", "pct_water_adequate"]].copy()
    logger.info(
        "Water supply data: %d municipalities (%d with valid values)",
        len(result), result["pct_water_adequate"].notna().sum(),
    )

    return result


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def extract_sanitation(output_dir: Path | None = None) -> Path:
    """Extract Census 2022 sanitation and water supply data.

    Merges sanitation (table 6805) and water supply (table 6803) into a
    single Parquet file with one row per municipality.

    Parameters
    ----------
    output_dir : Path, optional
        Directory for output Parquet. Default: data_sources/processed/census_sanitation/.

    Returns
    -------
    Path
        Path to output Parquet file (sanitation_2022.parquet).
    """
    if output_dir is None:
        output_dir = DEFAULT_OUTPUT_DIR

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "sanitation_2022.parquet"

    logger.info("=" * 60)
    logger.info("Census 2022 Sanitation Extraction")
    logger.info("Output: %s", output_path)
    logger.info("=" * 60)

    # Fetch both indicators
    sanitation_df = fetch_sanitation()
    water_df = fetch_water_supply()

    # Merge on cod_ibge (outer join to preserve all municipalities)
    merged = sanitation_df.merge(water_df, on="cod_ibge", how="outer")

    # Add year column -- always 2022 (cross-sectional)
    merged["year"] = CENSUS_YEAR

    logger.info(
        "Census 2022 sanitation: %d municipalities, "
        "CROSS-SECTIONAL (applied to all panel years)",
        len(merged),
    )

    # Validate via quality gate
    try:
        from database.validation import validate_dataframe  # noqa: PLC0415

        clean_df, report = validate_dataframe(
            merged, source_name="census_sanitation", strict=False
        )
        logger.info(
            "Census validation: %d/%d rows valid",
            report.n_valid, report.n_rows_input,
        )
        merged = clean_df
    except Exception as exc:  # noqa: BLE001
        logger.warning("Validation gate skipped: %s", exc)

    # Ensure correct column order
    merged = merged[["cod_ibge", "year", "pct_sanitation_adequate", "pct_water_adequate"]]

    merged.to_parquet(output_path, index=False, compression="snappy")
    logger.info(
        "✓ Census 2022 sanitation written: %s (%d rows)",
        output_path, len(merged),
    )

    return output_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    """CLI entry point for Census 2022 sanitation extraction."""
    parser = argparse.ArgumentParser(
        description="Extract Census 2022 sanitation and water supply data"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for output Parquet (default: data_sources/processed/census_sanitation/)",
    )
    args = parser.parse_args(argv)

    output_path = extract_sanitation(output_dir=Path(args.output_dir))
    logger.info("Done. Output: %s", output_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
