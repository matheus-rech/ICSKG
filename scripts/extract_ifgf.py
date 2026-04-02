"""
FIRJAN IFGF Excel Parser
=========================
Parses the FIRJAN Fiscal Management Index (IFGF) from a bundled Excel
workbook and writes a standardised Parquet file for the Governance (D1)
dimension of the ICSKG-BR panel.

The IFGF measures fiscal management quality across 5 sub-indices plus
a composite score (IFGF Geral) for Brazilian municipalities:
  - IFGF_RA  : Receita Propria (Own Revenue)
  - IFGF_GP  : Gastos com Pessoal (Personnel Expenditure)
  - IFGF_ID  : Investimentos (Investments)
  - IFGF_EL  : Liquidez (Liquidity)
  - IFGF_SA  : Custo da Divida (Debt Cost)

Approximately 420 municipalities per year are MNAR (Missing Not At Random)
due to fiscal reporting failures. These are preserved as NaN -- they are
NOT replaced with zero and NOT dropped from the dataset. This is a locked
project decision; multiple imputation will be explored in Phase 4.

Outputs
-------
    data_sources/processed/ifgf/ifgf.parquet

Columns: cod_ibge (str 7-digit), year (int), ifgf_geral (float),
         ifgf_ra (float), ifgf_gp (float), ifgf_id (float),
         ifgf_el (float), ifgf_sa (float)

Data requirements
-----------------
IFGF Excel file must be manually downloaded from FIRJAN and placed at:
    data_sources/Evolucao_por_Indicador_2013_a_2024_IFGF_2025.xlsx

Download from: https://www.firjan.com.br/ifgf/

Usage
-----
    python scripts/extract_ifgf.py
    python scripts/extract_ifgf.py --data-dir data_sources/ --output-dir data_sources/processed/ifgf/
    python scripts/extract_ifgf.py --year-start 2015 --year-end 2023
"""

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

from database.utils import normalize_cod_ibge, rename_municipality_column  # noqa: PLC0415
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

IFGF_FILENAME = "Evolucao_por_Indicador_2013_a_2024_IFGF_2025.xlsx"

IFGF_DOWNLOAD_URL = "https://www.firjan.com.br/ifgf/"

# Column name mapping: Excel header -> canonical lowercase
IFGF_COLUMN_MAP: dict[str, str] = {
    "IFGF_Geral": "ifgf_geral",
    "IFGF_RA": "ifgf_ra",
    "IFGF_GP": "ifgf_gp",
    "IFGF_ID": "ifgf_id",
    "IFGF_EL": "ifgf_el",
    "IFGF_SA": "ifgf_sa",
}

IFGF_VALUE_COLUMNS = list(IFGF_COLUMN_MAP.values())


# ---------------------------------------------------------------------------
# Core parsing functions
# ---------------------------------------------------------------------------

def parse_ifgf(
    path: Path,
    year_start: int = 2015,
    year_end: int = 2023,
) -> pd.DataFrame:
    """Parse the IFGF Excel file into a standardised DataFrame.

    Parameters
    ----------
    path : Path
        Path to the IFGF Excel workbook.
    year_start : int
        First year to include (default 2015).
    year_end : int
        Last year to include (default 2023).

    Returns
    -------
    pd.DataFrame
        DataFrame with columns [cod_ibge, year, ifgf_geral, ifgf_ra,
        ifgf_gp, ifgf_id, ifgf_el, ifgf_sa]. NaN values for MNAR
        municipalities are preserved.
    """
    logger.info("Reading IFGF Excel from %s", path)

    # -----------------------------------------------------------------
    # Read Excel with Cod_IBGE as string to preserve leading zeros
    # -----------------------------------------------------------------
    df = pd.read_excel(
        path,
        dtype={"Cod_IBGE": str},
        engine="openpyxl",
    )

    # -----------------------------------------------------------------
    # Clean column names (strip whitespace)
    # -----------------------------------------------------------------
    df.columns = df.columns.str.strip()

    # -----------------------------------------------------------------
    # Rename municipality code column: Cod_IBGE -> cod_ibge
    # -----------------------------------------------------------------
    df = rename_municipality_column(df)

    # -----------------------------------------------------------------
    # Normalize municipality codes to 7-digit zero-padded strings
    # -----------------------------------------------------------------
    df["cod_ibge"] = normalize_cod_ibge(df["cod_ibge"])

    # -----------------------------------------------------------------
    # Filter years to study scope
    # -----------------------------------------------------------------
    if "Ano" in df.columns:
        df = df[df["Ano"].between(year_start, year_end)].copy()
        df = df.rename(columns={"Ano": "year"})
    elif "ano" in df.columns:
        df = df[df["ano"].between(year_start, year_end)].copy()
        df = df.rename(columns={"ano": "year"})
    else:
        raise ValueError(
            "No 'Ano' column found in IFGF Excel. "
            "Columns present: %s" % list(df.columns)
        )

    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype(int)

    # -----------------------------------------------------------------
    # Rename IFGF columns to lowercase canonical names
    # -----------------------------------------------------------------
    rename_map = {}
    for orig, canonical in IFGF_COLUMN_MAP.items():
        # Handle case-insensitive matching
        for col in df.columns:
            if col.strip().upper() == orig.upper():
                rename_map[col] = canonical
                break
    df = df.rename(columns=rename_map)

    # -----------------------------------------------------------------
    # Coerce all IFGF value columns to numeric (preserves NaN for MNAR)
    # -----------------------------------------------------------------
    for col in IFGF_VALUE_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # -----------------------------------------------------------------
    # Select and return final columns
    # -----------------------------------------------------------------
    final_cols = ["cod_ibge", "year"] + IFGF_VALUE_COLUMNS
    # Only keep columns that exist
    available_cols = [c for c in final_cols if c in df.columns]
    df = df[available_cols].reset_index(drop=True)

    logger.info(
        "IFGF parsed: %d rows, years %d-%d",
        len(df), df["year"].min(), df["year"].max(),
    )
    return df


def extract_ifgf(
    data_dir: Path = Path("data_sources"),
    output_dir: Path = Path("data_sources/processed/ifgf"),
    year_start: int = 2015,
    year_end: int = 2023,
) -> Path:
    """Extract IFGF from Excel and write standardised Parquet.

    Parameters
    ----------
    data_dir : Path
        Directory containing the IFGF Excel file.
    output_dir : Path
        Directory to write the output Parquet file.
    year_start : int
        First year to include (default 2015).
    year_end : int
        Last year to include (default 2023).

    Returns
    -------
    Path
        Path to the written Parquet file.

    Raises
    ------
    FileNotFoundError
        If the IFGF Excel file is not found at the expected location.
    """
    logger.info("─" * 65 + "\n▶ Extracting IFGF fiscal management index")

    data_dir = Path(data_dir)
    output_dir = Path(output_dir)

    # -----------------------------------------------------------------
    # Locate IFGF file
    # -----------------------------------------------------------------
    ifgf_path = data_dir / IFGF_FILENAME
    if not ifgf_path.exists():
        raise FileNotFoundError(
            "IFGF Excel file not found at: %s\n"
            "Download from %s and place in %s/"
            % (ifgf_path, IFGF_DOWNLOAD_URL, data_dir)
        )

    # -----------------------------------------------------------------
    # Parse Excel
    # -----------------------------------------------------------------
    df = parse_ifgf(ifgf_path, year_start=year_start, year_end=year_end)

    # -----------------------------------------------------------------
    # Validate
    # -----------------------------------------------------------------
    df, report = validate_dataframe(
        df,
        source_name="ifgf",
        strict=False,
    )

    # -----------------------------------------------------------------
    # Log MNAR counts per year
    # -----------------------------------------------------------------
    if "ifgf_geral" in df.columns:
        mnar_by_year = df.groupby("year")["ifgf_geral"].apply(
            lambda s: s.isna().sum()
        )
        for year, count in mnar_by_year.items():
            if count > 0:
                logger.info(
                    "Year %d: %d MNAR municipalities (NaN ifgf_geral)",
                    year, count,
                )

    # -----------------------------------------------------------------
    # Write Parquet
    # -----------------------------------------------------------------
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "ifgf.parquet"
    df.to_parquet(out_path, index=False)

    logger.info(
        "%d rows written for %d municipalities across %d-%d",
        len(df),
        df["cod_ibge"].nunique(),
        df["year"].min(),
        df["year"].max(),
    )
    logger.info("Output written -> %s", out_path)
    return out_path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """CLI entry point for IFGF extraction.

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
        description="Parse FIRJAN IFGF Excel into standardised Parquet"
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data_sources"),
        help="Directory containing the IFGF Excel file",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data_sources/processed/ifgf"),
        help="Output directory for Parquet file",
    )
    parser.add_argument(
        "--year-start",
        type=int,
        default=2015,
        help="First year to include (default: 2015)",
    )
    parser.add_argument(
        "--year-end",
        type=int,
        default=2023,
        help="Last year to include (default: 2023)",
    )

    args = parser.parse_args(argv)
    extract_ifgf(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        year_start=args.year_start,
        year_end=args.year_end,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
