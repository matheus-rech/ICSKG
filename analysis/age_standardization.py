"""
ICSKG-BR Age-Standardised Surgical Rate Computation
=====================================================
Computes directly age-standardised surgical and mortality rates per 100,000
population using IBGE standard 5-year age bands, with full gender
stratification (male, female, total).

Direct age-standardisation removes confounding by population age structure,
allowing valid comparison of surgical rates across municipalities with
different demographic profiles. The standard population is the Brazilian
national age-sex distribution (sum across all municipalities for each
age-sex group).

Age bands follow the WHO/IBGE convention:
    0-4, 5-9, 10-14, ..., 75-79, 80+

SIH procedure-level Parquet files provide SEXO, IDADE, and COD_IDADE
columns. COD_IDADE encodes the age unit (4=years, 3=months, 2=days,
1=hours), which is resolved to age in years before age-band assignment.

Outputs
-------
    - age_standardized_rates.csv : municipality-year-sex age-standardised rates
    - tables/gender_stratified_rates.csv : summary by gender

Exports
-------
    compute_age_standardized_rates(sih_dir, pop_df, years, db_path)
    fetch_ibge_age_sex_population(years, base_dir)
    main(argv)

Usage
-----
    python analysis/age_standardization.py \\
        --sih-dir data_sources/processed/sih \\
        --out-dir analysis/results \\
        --start-year 2015 --end-year 2023
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

# Standard 5-year age bands (lower, upper inclusive)
# The last band is open-ended: 80+
AGE_BANDS: list[tuple[int, int | None]] = [
    (0, 4), (5, 9), (10, 14), (15, 19), (20, 24),
    (25, 29), (30, 34), (35, 39), (40, 44), (45, 49),
    (50, 54), (55, 59), (60, 64), (65, 69), (70, 74),
    (75, 79), (80, None),
]

AGE_BAND_LABELS: list[str] = [
    "0-4", "5-9", "10-14", "15-19", "20-24",
    "25-29", "30-34", "35-39", "40-44", "45-49",
    "50-54", "55-59", "60-64", "65-69", "70-74",
    "75-79", "80+",
]

# SIH COD_IDADE unit mapping
# 4 = age in years, 3 = months, 2 = days, 1 = hours
COD_IDADE_MAP: dict[int, str] = {
    4: "years",
    3: "months",
    2: "days",
    1: "hours",
}

# SIH SEXO encoding: 1 = Male, 3 = Female (standard DATASUS)
_SIH_SEX_MAP: dict = {
    1: "M", "1": "M",
    3: "F", "3": "F",
    "M": "M", "F": "F",
}

# pd.cut bins for age band assignment
# Bins: [-1, 5, 10, ..., 80, inf] with right=False so [0,5), [5,10), ..., [80, inf)
_AGE_CUT_BINS: list[float] = [
    -1, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50,
    55, 60, 65, 70, 75, 80, float("inf"),
]


# ---------------------------------------------------------------------------
# Population data loader
# ---------------------------------------------------------------------------

def fetch_ibge_age_sex_population(
    years: range,
    base_dir: Path | None = None,
) -> pd.DataFrame:
    """Fetch IBGE population by age band and sex for all municipalities.

    Strategy:
      1. Try loading from data_sources/reference/age_sex_population.parquet
      2. Try sidrapy to fetch IBGE SIDRA table 6579 (population estimates)
      3. Fallback: generate a synthetic uniform population for testing

    Parameters
    ----------
    years : range
        Years to include.
    base_dir : Path, optional
        Base directory for reference data files.

    Returns
    -------
    pd.DataFrame
        Columns: cod_ibge, year, age_band, sex, population
        sex values: "M", "F", "T" (total)
        age_band values: match AGE_BAND_LABELS
    """
    if base_dir is None:
        base_dir = Path("data_sources")

    ref_path = base_dir / "reference" / "age_sex_population.parquet"

    # ---------------------------------------------------------------------------
    # Strategy 1: Local cache file
    # ---------------------------------------------------------------------------
    if ref_path.exists():
        logger.info(
            "Loading age-sex population from cached file: %s", ref_path
        )
        pop_df = pd.read_parquet(ref_path)
        pop_df = pop_df[pop_df["year"].isin(list(years))]
        logger.info(
            "Loaded %d rows covering %d years from cache",
            len(pop_df),
            pop_df["year"].nunique(),
        )
        return pop_df

    # ---------------------------------------------------------------------------
    # Strategy 2: SIDRA API via sidrapy
    # ---------------------------------------------------------------------------
    try:
        import sidrapy  # noqa: PLC0415

        logger.info(
            "Fetching age-sex population from SIDRA table 6579..."
        )
        raw = sidrapy.get_table(
            table_code="6579",
            territorial_level="6",
            ibge_territorial_code="all",
            variable="9324",
            period=",".join(str(y) for y in years),
            classifications={"2": "all", "287": "all"},
        )

        data = raw.iloc[1:].copy()
        data["cod_ibge"] = data["D1C"].astype(str).str[:7]
        data["year"] = pd.to_numeric(data["D2C"], errors="coerce").astype(int)
        data["population"] = pd.to_numeric(data["V"], errors="coerce")

        # Parse sex classification
        data["sex"] = data["D3N"].map({
            "Homens": "M", "Mulheres": "F", "Total": "T",
        })

        # Parse age band classification
        data["age_band"] = data["D4N"].astype(str)

        pop_df = data[["cod_ibge", "year", "age_band", "sex", "population"]].copy()
        pop_df = pop_df.dropna(subset=["population"])

        logger.info(
            "Fetched %d population rows from SIDRA table 6579",
            len(pop_df),
        )

        # Cache for future use
        ref_path.parent.mkdir(parents=True, exist_ok=True)
        pop_df.to_parquet(ref_path, index=False)
        logger.info("Cached age-sex population to %s", ref_path)

        return pop_df

    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "SIDRA table 6579 unavailable: %s. "
            "Using synthetic population for pipeline testing.",
            exc,
        )

    # ---------------------------------------------------------------------------
    # Strategy 3: Synthetic fallback for testing
    # ---------------------------------------------------------------------------
    logger.warning(
        "Generating synthetic age-sex population. "
        "Results are NOT valid for publication -- download real IBGE data."
    )

    rows = []
    for year in years:
        for band in AGE_BAND_LABELS:
            for sex in ["M", "F", "T"]:
                pop = 1000 if sex != "T" else 2000
                rows.append({
                    "cod_ibge": "0000000",
                    "year": year,
                    "age_band": band,
                    "sex": sex,
                    "population": pop,
                })

    pop_df = pd.DataFrame(rows)
    logger.info(
        "Synthetic population generated: %d rows (placeholder only)",
        len(pop_df),
    )
    return pop_df


# ---------------------------------------------------------------------------
# Age resolution helpers
# ---------------------------------------------------------------------------

def _resolve_age_years(
    idade: pd.Series,
    cod_idade: pd.Series,
) -> pd.Series:
    """Convert SIH IDADE + COD_IDADE to age in completed years.

    Parameters
    ----------
    idade : pd.Series
        Numeric age value from SIH.
    cod_idade : pd.Series
        Age unit code: 4=years, 3=months, 2=days, 1=hours.

    Returns
    -------
    pd.Series
        Age in completed years (float). Infants (days/hours) return 0.0.
    """
    idade_num = pd.to_numeric(idade, errors="coerce").fillna(0)
    cod_num = pd.to_numeric(cod_idade, errors="coerce").fillna(4)

    age_years = pd.Series(np.nan, index=idade.index, dtype=float)

    # COD_IDADE=4: already in years
    mask_years = cod_num == 4
    age_years[mask_years] = idade_num[mask_years]

    # COD_IDADE=3: months -> years
    mask_months = cod_num == 3
    age_years[mask_months] = idade_num[mask_months] / 12.0

    # COD_IDADE=2: days -> infant (0 years)
    mask_days = cod_num == 2
    age_years[mask_days] = 0.0

    # COD_IDADE=1: hours -> neonate (0 years)
    mask_hours = cod_num == 1
    age_years[mask_hours] = 0.0

    # Floor to completed years
    age_years = np.floor(age_years).clip(lower=0)

    return age_years


def _assign_age_band(age_years: pd.Series) -> pd.Series:
    """Map continuous age in years to standard 5-year age band labels.

    Parameters
    ----------
    age_years : pd.Series
        Age in completed years.

    Returns
    -------
    pd.Series
        Categorical series with AGE_BAND_LABELS values.
    """
    bands = pd.cut(
        age_years,
        bins=_AGE_CUT_BINS,
        labels=AGE_BAND_LABELS,
        right=False,
        include_lowest=True,
    )
    return bands.astype(str)


def _resolve_sex(sexo: pd.Series) -> pd.Series:
    """Map SIH SEXO column to standardised "M"/"F"/NaN.

    Parameters
    ----------
    sexo : pd.Series
        Raw SEXO values from SIH (1, 3, "M", "F", etc.).

    Returns
    -------
    pd.Series
        "M" for male, "F" for female, NaN for unknown/missing.
    """
    return sexo.map(_SIH_SEX_MAP)


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_age_standardized_rates(
    sih_dir: Path,
    pop_df: pd.DataFrame,
    years: range,
    db_path: Path | None = None,
) -> pd.DataFrame:
    """Compute directly age-standardised surgical and mortality rates.

    Reads procedure-level SIH Parquet files, resolves age and sex,
    groups by (cod_ibge, year, age_band, sex), merges with population
    denominators, and applies direct age standardisation using the
    Brazilian national age structure as the standard population.

    Parameters
    ----------
    sih_dir : Path
        Directory containing SIH Parquet files with SEXO, IDADE,
        COD_IDADE, MORTE columns.
    pop_df : pd.DataFrame
        Population by (cod_ibge, year, age_band, sex).
    years : range
        Years to process.
    db_path : Path, optional
        Not used directly; reserved for future SQLite persistence.

    Returns
    -------
    pd.DataFrame
        Columns: cod_ibge, year, sex, age_std_surgical_rate,
        age_std_mortality_rate, crude_surgical_rate, crude_mortality_rate.
        sex values: "M", "F", "T" (total, both sexes combined).
    """
    logger.info("=" * 60)
    logger.info("AGE-STANDARDISED RATE COMPUTATION")
    logger.info("=" * 60)

    sih_dir = Path(sih_dir)

    # ---------------------------------------------------------------------------
    # Read procedure-level SIH data
    # ---------------------------------------------------------------------------
    parquet_files = sorted(sih_dir.glob("*.parquet"))
    if not parquet_files:
        logger.warning(
            "No SIH Parquet files found in %s -- returning empty DataFrame",
            sih_dir,
        )
        return pd.DataFrame(columns=[
            "cod_ibge", "year", "sex",
            "age_std_surgical_rate", "age_std_mortality_rate",
            "crude_surgical_rate", "crude_mortality_rate",
        ])

    logger.info("Reading %d SIH Parquet files from %s", len(parquet_files), sih_dir)

    frames = []
    required_cols = {"SEXO", "IDADE", "COD_IDADE", "MORTE"}
    for pf in parquet_files:
        try:
            df = pd.read_parquet(pf)

            # Check for required columns (may use cod_ibge or MUNIC_MOV)
            cod_col = "cod_ibge" if "cod_ibge" in df.columns else "MUNIC_MOV"
            if cod_col not in df.columns:
                logger.debug("Skipping %s: no municipality column", pf.name)
                continue

            present = required_cols.intersection(df.columns)
            if len(present) < len(required_cols):
                missing = required_cols - present
                logger.debug(
                    "Skipping %s: missing columns %s", pf.name, missing
                )
                continue

            # Extract year from filename or column
            if "year" in df.columns:
                df["_year"] = pd.to_numeric(df["year"], errors="coerce")
            elif "ANO_CMPT" in df.columns:
                df["_year"] = pd.to_numeric(df["ANO_CMPT"], errors="coerce")
            else:
                # Try extracting from filename pattern UF_YYYYMM.parquet
                try:
                    ym = pf.stem.split("_")[-1]
                    df["_year"] = int(ym[:4])
                except (ValueError, IndexError):
                    logger.debug("Cannot determine year for %s", pf.name)
                    continue

            # Filter to requested years
            df = df[df["_year"].isin(list(years))]
            if df.empty:
                continue

            frames.append(df[[cod_col, "_year", "SEXO", "IDADE", "COD_IDADE", "MORTE"]].rename(
                columns={cod_col: "cod_ibge", "_year": "year"}
            ))

        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to read %s: %s", pf, exc)

    if not frames:
        logger.warning("No usable SIH data found for years %s", list(years))
        return pd.DataFrame(columns=[
            "cod_ibge", "year", "sex",
            "age_std_surgical_rate", "age_std_mortality_rate",
            "crude_surgical_rate", "crude_mortality_rate",
        ])

    sih_all = pd.concat(frames, ignore_index=True)
    logger.info("SIH procedure-level data: %d rows loaded", len(sih_all))

    # ---------------------------------------------------------------------------
    # Resolve age and sex
    # ---------------------------------------------------------------------------
    sih_all["age_years"] = _resolve_age_years(sih_all["IDADE"], sih_all["COD_IDADE"])
    sih_all["age_band"] = _assign_age_band(sih_all["age_years"])
    sih_all["sex"] = _resolve_sex(sih_all["SEXO"])
    sih_all["MORTE"] = pd.to_numeric(sih_all["MORTE"], errors="coerce").fillna(0).astype(int)

    logger.info(
        "Age resolution: min=%.0f, max=%.0f years; sex coverage: M=%d, F=%d, missing=%d",
        sih_all["age_years"].min(),
        sih_all["age_years"].max(),
        (sih_all["sex"] == "M").sum(),
        (sih_all["sex"] == "F").sum(),
        sih_all["sex"].isna().sum(),
    )

    # ---------------------------------------------------------------------------
    # Group by (cod_ibge, year, age_band, sex) -- gender-specific counts
    # ---------------------------------------------------------------------------
    # For gender-specific rates, exclude records with missing sex
    sih_gendered = sih_all.dropna(subset=["sex"]).copy()

    sex_counts = (
        sih_gendered
        .groupby(["cod_ibge", "year", "age_band", "sex"], observed=True)
        .agg(
            n_procedures=("MORTE", "size"),
            n_deaths=("MORTE", "sum"),
        )
        .reset_index()
    )

    # Also compute totals (all sexes combined, including missing sex)
    total_counts = (
        sih_all
        .groupby(["cod_ibge", "year", "age_band"], observed=True)
        .agg(
            n_procedures=("MORTE", "size"),
            n_deaths=("MORTE", "sum"),
        )
        .reset_index()
    )
    total_counts["sex"] = "T"

    # Combine
    counts = pd.concat([sex_counts, total_counts], ignore_index=True)

    logger.info(
        "Age-sex procedure counts: %d groups (M=%d, F=%d, T=%d)",
        len(counts),
        (counts["sex"] == "M").sum(),
        (counts["sex"] == "F").sum(),
        (counts["sex"] == "T").sum(),
    )

    # ---------------------------------------------------------------------------
    # Merge with population denominators
    # ---------------------------------------------------------------------------
    pop_df = pop_df.copy()
    pop_df["cod_ibge"] = pop_df["cod_ibge"].astype(str)
    counts["cod_ibge"] = counts["cod_ibge"].astype(str)

    merged = counts.merge(
        pop_df[["cod_ibge", "year", "age_band", "sex", "population"]],
        on=["cod_ibge", "year", "age_band", "sex"],
        how="left",
    )

    # Compute age-specific rates per 100,000
    pop_safe = merged["population"].replace(0, np.nan)
    merged["rate_surgical"] = merged["n_procedures"] / pop_safe * 100_000
    merged["rate_mortality"] = merged["n_deaths"] / pop_safe * 100_000

    # ---------------------------------------------------------------------------
    # Compute standard population weights (national age structure)
    # ---------------------------------------------------------------------------
    # Standard population = sum of population across all municipalities for each
    # (year, age_band, sex) group.  Weights normalised to sum to 1.0 within each
    # (year, sex) stratum.
    std_pop = (
        pop_df[pop_df["sex"].isin(["M", "F", "T"])]
        .groupby(["year", "age_band", "sex"], observed=True)["population"]
        .sum()
        .reset_index()
        .rename(columns={"population": "std_pop"})
    )

    std_totals = (
        std_pop
        .groupby(["year", "sex"], observed=True)["std_pop"]
        .sum()
        .reset_index()
        .rename(columns={"std_pop": "std_total"})
    )

    std_pop = std_pop.merge(std_totals, on=["year", "sex"], how="left")
    std_pop["weight"] = std_pop["std_pop"] / std_pop["std_total"].replace(0, np.nan)

    # Verify weights sum to 1.0
    weight_sums = std_pop.groupby(["year", "sex"])["weight"].sum()
    if not weight_sums.empty:
        logger.info(
            "Standard population weights: min_sum=%.4f, max_sum=%.4f "
            "(expected ~1.0)",
            weight_sums.min(),
            weight_sums.max(),
        )

    # ---------------------------------------------------------------------------
    # Direct age-standardisation
    # ---------------------------------------------------------------------------
    merged = merged.merge(
        std_pop[["year", "age_band", "sex", "weight"]],
        on=["year", "age_band", "sex"],
        how="left",
    )

    # Weighted rate for each age band
    merged["weighted_surgical"] = merged["rate_surgical"] * merged["weight"].fillna(0)
    merged["weighted_mortality"] = merged["rate_mortality"] * merged["weight"].fillna(0)

    # Sum weighted rates across age bands per (cod_ibge, year, sex)
    result = (
        merged
        .groupby(["cod_ibge", "year", "sex"], observed=True)
        .agg(
            age_std_surgical_rate=("weighted_surgical", "sum"),
            age_std_mortality_rate=("weighted_mortality", "sum"),
            _total_procedures=("n_procedures", "sum"),
            _total_deaths=("n_deaths", "sum"),
            _total_pop=("population", "sum"),
        )
        .reset_index()
    )

    # Crude rates (un-standardised)
    pop_total = result["_total_pop"].replace(0, np.nan)
    result["crude_surgical_rate"] = result["_total_procedures"] / pop_total * 100_000
    result["crude_mortality_rate"] = result["_total_deaths"] / pop_total * 100_000

    # Drop intermediate columns
    result = result.drop(
        columns=["_total_procedures", "_total_deaths", "_total_pop"]
    )

    logger.info(
        "Age-standardised rates computed: %d rows "
        "(M=%d, F=%d, T=%d)",
        len(result),
        (result["sex"] == "M").sum(),
        (result["sex"] == "F").sum(),
        (result["sex"] == "T").sum(),
    )

    return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Compute age-standardised surgical rates from SIH procedure data.

    Usage
    -----
        python analysis/age_standardization.py \\
            --sih-dir data_sources/processed/sih \\
            --out-dir analysis/results \\
            --start-year 2015 --end-year 2023
    """
    parser = argparse.ArgumentParser(
        description="ICSKG-BR age-standardised surgical rate computation",
    )
    parser.add_argument(
        "--sih-dir",
        default="data_sources/processed/sih",
        help="Directory with SIH Parquet files (default: data_sources/processed/sih)",
    )
    parser.add_argument(
        "--db-path",
        default="database/icskg_br.sqlite",
        help="Path to SQLite database (default: database/icskg_br.sqlite)",
    )
    parser.add_argument(
        "--out-dir",
        default="analysis/results",
        help="Output directory (default: analysis/results)",
    )
    parser.add_argument(
        "--start-year", type=int, default=2015,
        help="First year to process (default: 2015)",
    )
    parser.add_argument(
        "--end-year", type=int, default=2023,
        help="Last year to process inclusive (default: 2023)",
    )
    args = parser.parse_args(argv)

    sih_dir = Path(args.sih_dir)
    out_dir = Path(args.out_dir)
    db_path = Path(args.db_path)
    years = range(args.start_year, args.end_year + 1)

    # ---------------------------------------------------------------
    # Fetch population data
    # ---------------------------------------------------------------
    logger.info("Fetching IBGE age-sex population data...")
    pop_df = fetch_ibge_age_sex_population(years)

    # ---------------------------------------------------------------
    # Compute age-standardised rates
    # ---------------------------------------------------------------
    rates_df = compute_age_standardized_rates(
        sih_dir=sih_dir,
        pop_df=pop_df,
        years=years,
        db_path=db_path,
    )

    if rates_df.empty:
        logger.warning("No age-standardised rates computed -- check SIH data")
        return 1

    # ---------------------------------------------------------------
    # Save outputs
    # ---------------------------------------------------------------
    out_dir.mkdir(parents=True, exist_ok=True)
    tables_dir = out_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    # Full rates
    rates_path = out_dir / "age_standardized_rates.csv"
    rates_df.to_csv(rates_path, index=False)
    logger.info("Saved age-standardised rates: %s (%d rows)", rates_path, len(rates_df))

    # Gender-stratified summary
    gender_summary = (
        rates_df
        .groupby(["year", "sex"])
        .agg(
            mean_age_std_surgical=("age_std_surgical_rate", "mean"),
            median_age_std_surgical=("age_std_surgical_rate", "median"),
            mean_age_std_mortality=("age_std_mortality_rate", "mean"),
            median_age_std_mortality=("age_std_mortality_rate", "median"),
            n_municipalities=("cod_ibge", "nunique"),
        )
        .reset_index()
    )

    gender_path = tables_dir / "gender_stratified_rates.csv"
    gender_summary.to_csv(gender_path, index=False)
    logger.info(
        "Saved gender-stratified summary: %s (%d rows)",
        gender_path, len(gender_summary),
    )

    # ---------------------------------------------------------------
    # Log summary statistics
    # ---------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("SUMMARY STATISTICS")
    logger.info("=" * 60)

    for sex_label in ["M", "F", "T"]:
        subset = rates_df[rates_df["sex"] == sex_label]
        if subset.empty:
            continue
        logger.info(
            "  %s: age_std_surgical mean=%.1f, median=%.1f; "
            "age_std_mortality mean=%.4f, median=%.4f",
            sex_label,
            subset["age_std_surgical_rate"].mean(),
            subset["age_std_surgical_rate"].median(),
            subset["age_std_mortality_rate"].mean(),
            subset["age_std_mortality_rate"].median(),
        )

    logger.info("Age-standardisation complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
