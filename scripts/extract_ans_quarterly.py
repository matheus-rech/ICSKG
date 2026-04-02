"""
ANS Quarterly Average Beneficiary Extraction
=============================================
Extracts ANS (Agencia Nacional de Saude Suplementar) private health-plan
beneficiary data as quarterly averages per municipality per year.

This module computes the Q1-Q4 mean of beneficiary counts, NOT the December
snapshot. The quarterly average better represents annual coverage and avoids
seasonal bias (locked design decision -- see 03-CONTEXT.md).

The private coverage rate (beneficiarios / populacao) and SUS dependence rate
(1 - coverage_rate) are optionally computed when population data is available.

Outputs
-------
    data_sources/processed/ans/ans_quarterly.parquet
        Columns: cod_ibge, year, beneficiarios_mean, coverage_rate, sus_dependence

Data Requirements
-----------------
    - Raw ANS CSV files downloaded by scripts/download_ans.py
    - Optional: population Parquet for coverage rate computation

Usage
-----
    python scripts/extract_ans_quarterly.py --years 2015 2016 2017 2018 2019 2020 2021 2022 2023
    python scripts/extract_ans_quarterly.py --population-path data_sources/processed/ibge_sidra/population.parquet
"""

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
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

DEFAULT_YEARS: list[int] = list(range(2015, 2024))  # 2015-2023

DEFAULT_RAW_DIR: Path = Path("data_sources/raw/ANS")
DEFAULT_OUTPUT_DIR: Path = Path("data_sources/processed/ans")


# ---------------------------------------------------------------------------
# Core computation functions
# ---------------------------------------------------------------------------

def compute_quarterly_average(
    frames: list[pd.DataFrame],
    year: int,
) -> pd.DataFrame:
    """Compute quarterly average of ANS beneficiary counts per municipality.

    Concatenates quarterly DataFrames, normalizes municipality codes to 7-digit
    strings, and computes the mean of available quarterly BENEFICIARIOS values
    per municipality.

    Parameters
    ----------
    frames : list[pd.DataFrame]
        List of quarterly DataFrames, each with CD_MUNICIPIO and BENEFICIARIOS.
    year : int
        Panel year for the output.

    Returns
    -------
    pd.DataFrame
        Columns: cod_ibge (7-digit str), year (int), beneficiarios_mean (float).
    """
    from database.utils import normalize_cod_ibge  # noqa: PLC0415

    if not frames:
        logger.warning("No quarterly frames provided for year %d", year)
        return pd.DataFrame(columns=["cod_ibge", "year", "beneficiarios_mean"])

    combined = pd.concat(frames, ignore_index=True)

    # Normalize municipality code: ANS CD_MUNICIPIO is 6-digit (Pitfall 8)
    combined["cod_ibge"] = normalize_cod_ibge(combined["CD_MUNICIPIO"])

    # Ensure BENEFICIARIOS is numeric
    combined["BENEFICIARIOS"] = pd.to_numeric(
        combined["BENEFICIARIOS"], errors="coerce"
    )

    # Group by municipality and compute mean across available quarters
    agg = (
        combined.groupby("cod_ibge", as_index=False)["BENEFICIARIOS"]
        .mean()
        .rename(columns={"BENEFICIARIOS": "beneficiarios_mean"})
    )

    agg["year"] = year

    logger.info(
        "ANS %d: quarterly average computed for %d municipalities "
        "(from %d quarterly frames)",
        year, len(agg), len(frames),
    )

    return agg[["cod_ibge", "year", "beneficiarios_mean"]]


def compute_coverage_rate(
    df: pd.DataFrame,
    population_df: pd.DataFrame | None = None,
    population_path: Path | None = None,
) -> pd.DataFrame:
    """Compute private health insurance coverage rate and SUS dependence.

    Parameters
    ----------
    df : pd.DataFrame
        Output of compute_quarterly_average() with columns
        [cod_ibge, year, beneficiarios_mean].
    population_df : pd.DataFrame, optional
        Population data with columns [cod_ibge, year, populacao].
        Takes precedence over population_path.
    population_path : Path, optional
        Path to population Parquet file. Used only if population_df is None.

    Returns
    -------
    pd.DataFrame
        Input DataFrame with added columns: coverage_rate, sus_dependence.
        If no population data available, both are NaN.
    """
    result = df.copy()

    # Load population if path provided but no DataFrame
    if population_df is None and population_path is not None:
        try:
            population_df = pd.read_parquet(population_path)
            logger.info(
                "Loaded population data: %d rows from %s",
                len(population_df), population_path,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to load population from %s: %s. "
                "Coverage rate will be NaN.",
                population_path, exc,
            )
            population_df = None

    if population_df is not None:
        # Merge on (cod_ibge, year)
        pop_cols = ["cod_ibge", "year", "populacao"]
        pop = population_df[pop_cols].copy()
        pop["year"] = pop["year"].astype(int)
        result["year"] = result["year"].astype(int)

        result = result.merge(pop, on=["cod_ibge", "year"], how="left")

        # Compute coverage rate (clipped to [0, 1])
        result["coverage_rate"] = (
            result["beneficiarios_mean"] / result["populacao"]
        ).clip(0, 1)

        # SUS dependence = 1 - coverage rate
        result["sus_dependence"] = 1.0 - result["coverage_rate"]

        # Drop the populacao column (not part of output schema)
        result = result.drop(columns=["populacao"], errors="ignore")

        n_with_pop = result["coverage_rate"].notna().sum()
        logger.info(
            "Coverage rate computed for %d / %d municipality-years",
            n_with_pop, len(result),
        )
    else:
        # No population data -- set to NaN (will be computed in Panel Assembly)
        result["coverage_rate"] = np.nan
        result["sus_dependence"] = np.nan
        logger.info(
            "No population data provided. "
            "Coverage rate and SUS dependence set to NaN."
        )

    return result[["cod_ibge", "year", "beneficiarios_mean",
                    "coverage_rate", "sus_dependence"]]


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def extract_ans_quarterly(
    years: list[int] | None = None,
    raw_dir: Path | None = None,
    output_dir: Path | None = None,
    population_path: Path | None = None,
    skip_existing: bool = True,
) -> Path:
    """Extract ANS quarterly average beneficiary data for multiple years.

    For each year, downloads 4 quarterly CSVs using download_competence()
    from scripts/download_ans.py, parses each with parse_csv(), and computes
    the quarterly average.

    Parameters
    ----------
    years : list[int], optional
        Years to extract. Default: 2015-2023.
    raw_dir : Path, optional
        Directory for raw ANS CSV files. Default: data_sources/raw/ANS/.
    output_dir : Path, optional
        Directory for output Parquet. Default: data_sources/processed/ans/.
    population_path : Path, optional
        Path to population Parquet for coverage rate computation.
    skip_existing : bool
        Skip downloading files that already exist locally.

    Returns
    -------
    Path
        Path to output Parquet file (ans_quarterly.parquet).
    """
    from scripts.download_ans import download_competence, parse_csv  # noqa: PLC0415
    from scripts.download_ans import QUARTERLY_MONTHS  # noqa: PLC0415

    if years is None:
        years = DEFAULT_YEARS
    if raw_dir is None:
        raw_dir = DEFAULT_RAW_DIR
    if output_dir is None:
        output_dir = DEFAULT_OUTPUT_DIR

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "ans_quarterly.parquet"

    logger.info("=" * 60)
    logger.info("ANS Quarterly Average Extraction")
    logger.info("Years: %s", years)
    logger.info("Raw dir: %s", raw_dir)
    logger.info("Output: %s", output_path)
    logger.info("=" * 60)

    all_years: list[pd.DataFrame] = []

    for year in years:
        logger.info("▶ Processing ANS year %d", year)
        quarterly_frames: list[pd.DataFrame] = []

        for month in QUARTERLY_MONTHS:
            path = download_competence(year, month, raw_dir, skip_existing=skip_existing)
            if path is not None:
                try:
                    df = parse_csv(path)
                    df["comp_year"] = year
                    df["comp_month"] = month
                    quarterly_frames.append(df)
                    logger.info(
                        "  ✓ Q%d (%d-%02d): %d rows",
                        (month - 1) // 3 + 1, year, month, len(df),
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "  Failed to parse ANS CSV for %d-%02d: %s",
                        year, month, exc,
                    )
            else:
                logger.warning(
                    "  ANS CSV not available for %d-%02d", year, month
                )

        if quarterly_frames:
            year_avg = compute_quarterly_average(quarterly_frames, year=year)
            all_years.append(year_avg)
        else:
            logger.warning("No ANS data found for year %d", year)

    if not all_years:
        logger.error("No ANS data extracted for any year.")
        empty = pd.DataFrame(
            columns=["cod_ibge", "year", "beneficiarios_mean",
                      "coverage_rate", "sus_dependence"]
        )
        empty.to_parquet(output_path, index=False)
        return output_path

    panel = pd.concat(all_years, ignore_index=True)

    # Compute coverage rate if population available
    panel = compute_coverage_rate(panel, population_path=population_path)

    # Validate via quality gate
    try:
        from database.validation import validate_dataframe  # noqa: PLC0415

        clean_df, report = validate_dataframe(
            panel, source_name="ans_quarterly", strict=False
        )
        logger.info(
            "ANS validation: %d/%d rows valid",
            report.n_valid, report.n_rows_input,
        )
        panel = clean_df
    except Exception as exc:  # noqa: BLE001
        logger.warning("Validation gate skipped: %s", exc)

    panel.to_parquet(output_path, index=False, compression="snappy")
    logger.info(
        "✓ ANS quarterly averages written: %s (%d rows, %d municipalities, %d years)",
        output_path, len(panel),
        panel["cod_ibge"].nunique(),
        panel["year"].nunique(),
    )

    return output_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    """CLI entry point for ANS quarterly average extraction."""
    parser = argparse.ArgumentParser(
        description="Extract ANS quarterly average beneficiary data"
    )
    parser.add_argument(
        "--years",
        type=int,
        nargs="+",
        default=DEFAULT_YEARS,
        help="Years to extract (default: 2015-2023)",
    )
    parser.add_argument(
        "--raw-dir",
        type=str,
        default=str(DEFAULT_RAW_DIR),
        help="Directory for raw ANS CSV files",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for output Parquet",
    )
    parser.add_argument(
        "--population-path",
        type=str,
        default=None,
        help="Path to population Parquet for coverage rate computation",
    )
    parser.add_argument(
        "--no-skip",
        dest="skip_existing",
        action="store_false",
        help="Re-download files that already exist locally",
    )
    args = parser.parse_args(argv)

    output_path = extract_ans_quarterly(
        years=args.years,
        raw_dir=Path(args.raw_dir),
        output_dir=Path(args.output_dir),
        population_path=Path(args.population_path) if args.population_path else None,
        skip_existing=args.skip_existing,
    )
    logger.info("Done. Output: %s", output_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
