"""
ICSKG-BR IPCA Deflation Module
================================
Fetches IPCA (Indice Nacional de Precos ao Consumidor Amplo) annual indices
from IBGE SIDRA table 1737 and deflates monetary columns to a constant base
year (default: 2023 BRL).

The general IPCA index is used (not the health sub-index) as the primary
deflator, following the research recommendation that the health sub-index
be reserved for sensitivity analysis. The December value of each year is
taken as the annual reference point, consistent with standard Brazilian
economic practice.

Deflation formula:
    deflation_factor_y = ipca_index_dec_base / ipca_index_dec_y
    real_value_y = nominal_value_y * deflation_factor_y

Exports
-------
    fetch_ipca_annual_index(years, base_year) -> pd.DataFrame
    deflate_column(df, col, ipca_factors) -> pd.DataFrame

Usage
-----
    from database.deflate_ipca import fetch_ipca_annual_index, deflate_column

    factors_df = fetch_ipca_annual_index(years=range(2015, 2024), base_year=2023)
    factor_series = factors_df.set_index("year")["deflation_factor"]
    df = deflate_column(df, "gdp_per_capita", factor_series)
"""

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Lazy import -- sidrapy is optional at module level for test mocking
try:
    import sidrapy
except ImportError:
    sidrapy = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_ipca_annual_index(
    years: list[int] | range,
    base_year: int = 2023,
) -> pd.DataFrame:
    """Fetch IPCA annual index from SIDRA table 1737 and compute deflation factors.

    Uses the accumulated IPCA index (variable 2266) from IBGE SIDRA.
    Takes the December value for each year as the annual reference.

    Parameters
    ----------
    years : list[int] or range
        Years to include in the output.
    base_year : int
        Year whose deflation_factor will be 1.0.

    Returns
    -------
    pd.DataFrame
        Columns: [year, ipca_index, deflation_factor]
        - year: int
        - ipca_index: float (December accumulated index)
        - deflation_factor: float (base_year_index / year_index)

    Raises
    ------
    RuntimeError
        If sidrapy is not installed or SIDRA API call fails.
    """
    if sidrapy is None:
        raise RuntimeError(
            "sidrapy is required for IPCA fetching. "
            "Install with: pip install sidrapy"
        )

    logger.info(
        "Fetching IPCA annual index from SIDRA table 1737 "
        "(years=%s, base_year=%d)",
        list(years), base_year,
    )

    # ---------------------------------------------------------------------------
    # Fetch raw data from SIDRA
    # ---------------------------------------------------------------------------
    raw = sidrapy.get_table(
        table_code="1737",
        territorial_level="1",
        ibge_territorial_code="all",
        variable="2266",
        period="all",
    )

    # ---------------------------------------------------------------------------
    # Parse: skip header row (index 0), extract year/month/value
    # ---------------------------------------------------------------------------
    data = raw.iloc[1:].copy()  # skip header row
    data["year"] = data["D2C"].astype(str).str[:4].astype(int)
    data["month"] = data["D2C"].astype(str).str[4:6].astype(int)
    data["ipca_index"] = pd.to_numeric(data["V"], errors="coerce")

    # Filter to December values only (annual reference point)
    dec = data[data["month"] == 12].copy()
    dec = dec[["year", "ipca_index"]].drop_duplicates(subset=["year"])

    # Filter to requested years
    years_set = set(int(y) for y in years)
    dec = dec[dec["year"].isin(years_set)].copy()

    if base_year not in dec["year"].values:
        raise ValueError(
            "base_year %d not found in SIDRA response. "
            "Available years: %s" % (base_year, sorted(dec["year"].tolist()))
        )

    # ---------------------------------------------------------------------------
    # Compute deflation factors
    # ---------------------------------------------------------------------------
    base_index = dec.loc[dec["year"] == base_year, "ipca_index"].iloc[0]
    dec["deflation_factor"] = base_index / dec["ipca_index"]

    result = dec[["year", "ipca_index", "deflation_factor"]].reset_index(drop=True)

    logger.info(
        "IPCA deflation factors computed for %d years (base=%d). "
        "Factor range: [%.4f, %.4f]",
        len(result), base_year,
        result["deflation_factor"].min(),
        result["deflation_factor"].max(),
    )

    return result


def deflate_column(
    df: pd.DataFrame,
    col: str,
    ipca_factors: pd.Series,
) -> pd.DataFrame:
    """Deflate a monetary column to constant base-year BRL.

    Preserves the original nominal values in a new column named {col}_nominal.
    The deflated values overwrite the original column. NaN values remain NaN
    (multiplication by any factor preserves NaN).

    Parameters
    ----------
    df : pd.DataFrame
        Must contain columns ``col`` (monetary values) and ``year`` (int).
    col : str
        Name of the monetary column to deflate (e.g., "gdp_per_capita").
    ipca_factors : pd.Series
        Mapping of year (index) to deflation_factor (value).
        Typically: ``factors_df.set_index("year")["deflation_factor"]``.

    Returns
    -------
    pd.DataFrame
        Copy of df with:
        - ``{col}_nominal``: original values preserved
        - ``{col}``: deflated values (nominal * deflation_factor)
    """
    df = df.copy()

    # Preserve original nominal values
    df[f"{col}_nominal"] = df[col].copy()

    # Map year to deflation factor and multiply
    mapped_factors = df["year"].map(ipca_factors)
    df[col] = df[col] * mapped_factors

    n_deflated = df[col].notna().sum()
    n_nan = df[col].isna().sum()
    logger.info(
        "deflate_column('%s'): %d values deflated, %d NaN preserved",
        col, n_deflated, n_nan,
    )

    return df
