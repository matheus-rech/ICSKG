"""
IBGE SIDRA Population & GDP Extractor
=======================================
Extracts population estimates and GDP data for all 5,570 Brazilian
municipalities (2015-2023) from IBGE's SIDRA API into standardized
Parquet files.

Population feeds LCoGS denominators (per-100K rates) and GDP feeds the
Economy dimension (D2). Both are foundational for the entire panel.

Data sources
------------
- Table 6579: Population estimates 2015-2021 (variable 9324)
- Table 4709: Census 2022 population (variable 93), used for 2022-2023
- Table 5938: GDP at current prices (variable 37, R$ 1,000)

Outputs
-------
- data_sources/processed/ibge_sidra/population.parquet
  Columns: cod_ibge (str7), year (int), populacao (float)

- data_sources/processed/ibge_sidra/gdp.parquet
  Columns: cod_ibge (str7), year (int), gdp_abs (float),
           gdp_estimated (bool), gdp_per_capita (float)

Usage
-----
    python scripts/extract_ibge_sidra.py
    python scripts/extract_ibge_sidra.py --years 2020 2021 2022
    python scripts/extract_ibge_sidra.py --output-dir data_sources/processed/ibge_sidra/
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

# Population table routing
POP_TABLE_ESTIMATES = "6579"       # Population estimates 2001-2021
POP_VAR_ESTIMATES = "9324"         # Populacao residente estimada
POP_TABLE_CENSUS = "4709"          # Census 2022 population
POP_VAR_CENSUS = "93"              # Populacao residente
POP_TABLE_SWITCH_YEAR = 2022       # Year at which we switch tables

# GDP table
GDP_TABLE = "5938"                 # GDP at current prices
GDP_VAR = "37"                     # PIB a precos correntes (R$ 1,000)
GDP_ESTIMATED_FROM = 2022          # GDP >= this year flagged as estimated

# SIDRA API retry settings
MAX_RETRIES = 3
RETRY_BASE_DELAY = 5  # seconds

# Default study period
DEFAULT_YEARS = list(range(2015, 2024))  # 2015-2023

# Default output directory
DEFAULT_OUTPUT_DIR = Path("data_sources") / "processed" / "ibge_sidra"


# ---------------------------------------------------------------------------
# SIDRA API helpers
# ---------------------------------------------------------------------------

def _fetch_sidra_table(
    table_code: str,
    variable: str,
    period: str,
) -> pd.DataFrame:
    """Fetch a SIDRA table with retry logic.

    Parameters
    ----------
    table_code : str
        SIDRA table code (e.g., "6579").
    variable : str
        Variable code (e.g., "9324").
    period : str
        Year as string (e.g., "2021").

    Returns
    -------
    pd.DataFrame
        Raw DataFrame from sidrapy.get_table(), including metadata header row.

    Raises
    ------
    RuntimeError
        If all retries are exhausted.
    """
    import sidrapy  # noqa: PLC0415

    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            df = sidrapy.get_table(
                table_code=table_code,
                territorial_level="6",
                ibge_territorial_code="all",
                period=period,
                variable=variable,
            )
            logger.info(
                "SIDRA table %s, var %s, period %s: %d rows fetched",
                table_code, variable, period, len(df),
            )
            return df
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
            logger.warning(
                "SIDRA fetch failed (attempt %d/%d) table=%s var=%s period=%s: %s. "
                "Retrying in %d seconds...",
                attempt, MAX_RETRIES, table_code, variable, period, exc, delay,
            )
            time.sleep(delay)

    raise RuntimeError(
        "Failed to fetch SIDRA table %s var %s period %s after %d attempts"
        % (table_code, variable, period, MAX_RETRIES)
    ) from last_exc


# ---------------------------------------------------------------------------
# Population extraction
# ---------------------------------------------------------------------------

def fetch_population_year(year: int) -> pd.DataFrame:
    """Fetch population estimates for all municipalities for one year.

    Uses table 6579 (estimates) for years <= 2021 and table 4709
    (Census 2022) for years >= 2022.

    Parameters
    ----------
    year : int
        Calendar year to fetch.

    Returns
    -------
    pd.DataFrame
        Columns: [cod_ibge, year, populacao]
    """
    from database.utils import normalize_cod_ibge  # noqa: PLC0415

    if year < POP_TABLE_SWITCH_YEAR:
        table_code = POP_TABLE_ESTIMATES
        variable = POP_VAR_ESTIMATES
    else:
        table_code = POP_TABLE_CENSUS
        variable = POP_VAR_CENSUS

    df = _fetch_sidra_table(table_code, variable, str(year))

    # Skip metadata header row (Pitfall 6)
    df = df.iloc[1:]

    df = df.rename(columns={"D1C": "cod_ibge", "V": "populacao"})
    df["cod_ibge"] = normalize_cod_ibge(df["cod_ibge"])
    df["populacao"] = pd.to_numeric(df["populacao"], errors="coerce")
    df["year"] = year

    return df[["cod_ibge", "year", "populacao"]].reset_index(drop=True)


def extract_population(
    years: list[int],
    output_dir: Path,
    skip_existing: bool = True,
) -> Path:
    """Extract population for multiple years and write to Parquet.

    Parameters
    ----------
    years : list[int]
        Calendar years to extract.
    output_dir : Path
        Directory for output Parquet file.
    skip_existing : bool
        If True and output file exists, skip extraction.

    Returns
    -------
    Path
        Path to the written Parquet file.
    """
    from database.validation import validate_dataframe  # noqa: PLC0415

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "population.parquet"

    if skip_existing and out_path.exists() and out_path.stat().st_size > 0:
        logger.info("Population file exists, skipping: %s", out_path)
        return out_path

    logger.info("=" * 60)
    logger.info("Extracting IBGE population estimates for %d years", len(years))
    logger.info("=" * 60)

    frames = []
    for year in years:
        try:
            df = fetch_population_year(year)
            logger.info(
                "  %d: %d municipalities, %d non-null values",
                year, len(df), df["populacao"].notna().sum(),
            )
            frames.append(df)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to fetch population for %d: %s", year, exc)

    if not frames:
        logger.error("No population data extracted -- writing empty Parquet")
        empty = pd.DataFrame(columns=["cod_ibge", "year", "populacao"])
        empty.to_parquet(out_path, index=False)
        return out_path

    result = pd.concat(frames, ignore_index=True)

    # Validation gate
    clean_df, report = validate_dataframe(
        result,
        source_name="ibge_population",
        strict=False,
        quarantine_dir=output_dir.parent / "quarantine",
    )

    clean_df.to_parquet(out_path, index=False)
    logger.info(
        "Population written: %s (%d rows, %d years)",
        out_path, len(clean_df), clean_df["year"].nunique(),
    )
    return out_path


# ---------------------------------------------------------------------------
# GDP extraction
# ---------------------------------------------------------------------------

def fetch_gdp_year(year: int) -> pd.DataFrame:
    """Fetch GDP at current prices for all municipalities for one year.

    GDP values from table 5938 are in R$ 1,000 (variable 37). Years >= 2022
    are flagged as estimated per IBGE methodological caveats (Pitfall 3).

    Parameters
    ----------
    year : int
        Calendar year to fetch.

    Returns
    -------
    pd.DataFrame
        Columns: [cod_ibge, year, gdp_abs, gdp_estimated]
    """
    from database.utils import normalize_cod_ibge  # noqa: PLC0415

    df = _fetch_sidra_table(GDP_TABLE, GDP_VAR, str(year))

    # Skip metadata header row (Pitfall 6)
    df = df.iloc[1:]

    df = df.rename(columns={"D1C": "cod_ibge", "V": "gdp_abs"})
    df["cod_ibge"] = normalize_cod_ibge(df["cod_ibge"])
    df["gdp_abs"] = pd.to_numeric(df["gdp_abs"], errors="coerce")
    df["year"] = year
    df["gdp_estimated"] = year >= GDP_ESTIMATED_FROM

    return df[["cod_ibge", "year", "gdp_abs", "gdp_estimated"]].reset_index(drop=True)


def compute_gdp_per_capita(
    gdp_df: pd.DataFrame,
    pop_df: pd.DataFrame,
) -> pd.DataFrame:
    """Compute GDP per capita by merging GDP and population data.

    GDP per capita = gdp_abs * 1000 / populacao
    (table 5938 values are in R$ 1,000, so multiply by 1000 for absolute BRL)

    Parameters
    ----------
    gdp_df : pd.DataFrame
        GDP DataFrame with columns [cod_ibge, year, gdp_abs, gdp_estimated].
    pop_df : pd.DataFrame
        Population DataFrame with columns [cod_ibge, year, populacao].

    Returns
    -------
    pd.DataFrame
        GDP DataFrame with added gdp_per_capita column.
    """
    merged = gdp_df.merge(
        pop_df[["cod_ibge", "year", "populacao"]],
        on=["cod_ibge", "year"],
        how="left",
    )
    merged["gdp_per_capita"] = merged["gdp_abs"] * 1000 / merged["populacao"]
    return merged


def extract_gdp(
    years: list[int],
    output_dir: Path,
    population_path: Path,
    skip_existing: bool = True,
) -> Path:
    """Extract GDP for multiple years, compute per capita, and write to Parquet.

    Parameters
    ----------
    years : list[int]
        Calendar years to extract.
    output_dir : Path
        Directory for output Parquet file.
    population_path : Path
        Path to population.parquet for per-capita computation.
    skip_existing : bool
        If True and output file exists, skip extraction.

    Returns
    -------
    Path
        Path to the written Parquet file.
    """
    from database.validation import validate_dataframe  # noqa: PLC0415

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "gdp.parquet"

    if skip_existing and out_path.exists() and out_path.stat().st_size > 0:
        logger.info("GDP file exists, skipping: %s", out_path)
        return out_path

    logger.info("=" * 60)
    logger.info("Extracting IBGE GDP data for %d years", len(years))
    logger.info("=" * 60)

    frames = []
    for year in years:
        try:
            df = fetch_gdp_year(year)
            logger.info(
                "  %d: %d municipalities, %d non-null GDP values",
                year, len(df), df["gdp_abs"].notna().sum(),
            )
            frames.append(df)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to fetch GDP for %d: %s", year, exc)

    if not frames:
        logger.error("No GDP data extracted -- writing empty Parquet")
        empty = pd.DataFrame(
            columns=["cod_ibge", "year", "gdp_abs", "gdp_estimated", "gdp_per_capita"]
        )
        empty.to_parquet(out_path, index=False)
        return out_path

    gdp_result = pd.concat(frames, ignore_index=True)

    # Merge with population for per-capita computation
    if population_path.exists():
        pop_df = pd.read_parquet(population_path)
        gdp_result = compute_gdp_per_capita(gdp_result, pop_df)
    else:
        logger.warning(
            "Population file not found at %s -- skipping per-capita computation",
            population_path,
        )
        gdp_result["gdp_per_capita"] = float("nan")

    # Validation gate
    clean_df, report = validate_dataframe(
        gdp_result,
        source_name="ibge_gdp",
        strict=False,
        quarantine_dir=output_dir.parent / "quarantine",
    )

    clean_df.to_parquet(out_path, index=False)
    logger.info(
        "GDP written: %s (%d rows, %d years)",
        out_path, len(clean_df), clean_df["year"].nunique(),
    )
    return out_path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """CLI entry point for IBGE SIDRA extraction.

    Parameters
    ----------
    argv : list[str], optional
        Command-line arguments. Defaults to sys.argv[1:].

    Returns
    -------
    int
        Exit code (0 = success).
    """
    parser = argparse.ArgumentParser(
        description="Extract IBGE SIDRA population and GDP data",
    )
    parser.add_argument(
        "--years",
        nargs="+",
        type=int,
        default=DEFAULT_YEARS,
        help="Years to extract (default: 2015-2023)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory for Parquet files",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        default=True,
        help="Skip extraction if output files exist",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Force re-extraction even if output files exist",
    )
    args = parser.parse_args(argv)

    skip = args.skip_existing and not args.force

    logger.info("IBGE SIDRA extraction: years=%s, output=%s", args.years, args.output_dir)

    # Step 1: Extract population
    pop_path = extract_population(
        years=args.years,
        output_dir=args.output_dir,
        skip_existing=skip,
    )

    # Step 2: Extract GDP (needs population for per-capita)
    extract_gdp(
        years=args.years,
        output_dir=args.output_dir,
        population_path=pop_path,
        skip_existing=skip,
    )

    logger.info("IBGE SIDRA extraction complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
