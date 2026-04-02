"""
ICSKG-BR IPCA Deflation and USD Conversion Module
====================================================
Fetches IPCA (Indice Nacional de Precos ao Consumidor Amplo) annual indices
from IBGE SIDRA table 1737 and deflates monetary columns to a constant base
year (default: 2023 BRL). Also provides BRL-to-USD conversion using BCB
(Banco Central do Brasil) annual average exchange rates for international
comparison.

The general IPCA index is used (not the health sub-index) as the primary
deflator, following the research recommendation that the health sub-index
be reserved for sensitivity analysis. The December value of each year is
taken as the annual reference point, consistent with standard Brazilian
economic practice.

Deflation formula:
    deflation_factor_y = ipca_index_dec_base / ipca_index_dec_y
    real_value_y = nominal_value_y * deflation_factor_y

USD conversion:
    value_usd = value_brl / exchange_rate_brl_per_usd
    Exchange rate sourced from BCB SGS API series 3698 (PTAX selling rate).

Exports
-------
    fetch_ipca_annual_index(years, base_year) -> pd.DataFrame
    deflate_column(df, col, ipca_factors) -> pd.DataFrame
    fetch_bcb_exchange_rate(base_year) -> float
    convert_brl_to_usd(df, cols, exchange_rate) -> pd.DataFrame

Usage
-----
    from database.deflate_ipca import (
        fetch_ipca_annual_index, deflate_column,
        fetch_bcb_exchange_rate, convert_brl_to_usd,
    )

    factors_df = fetch_ipca_annual_index(years=range(2015, 2024), base_year=2023)
    factor_series = factors_df.set_index("year")["deflation_factor"]
    df = deflate_column(df, "gdp_per_capita", factor_series)

    rate = fetch_bcb_exchange_rate(base_year=2023)
    df = convert_brl_to_usd(df, ["gdp_per_capita", "total_cost_brl"], rate)
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


# ---------------------------------------------------------------------------
# USD Conversion
# ---------------------------------------------------------------------------

# Hardcoded fallback: average 2023 BRL/USD PTAX selling rate
_FALLBACK_EXCHANGE_RATE_2023: float = 4.9942


def fetch_bcb_exchange_rate(base_year: int = 2023) -> float:
    """Fetch average annual BRL/USD exchange rate from BCB SGS API.

    Uses series 3698 (PTAX selling rate, daily). Computes the annual average
    of daily rates for the specified base_year. Falls back to a hardcoded
    2023 average rate (4.9942) if the API is unavailable.

    Parameters
    ----------
    base_year : int
        Year for which to compute the average exchange rate.

    Returns
    -------
    float
        Average BRL per 1 USD for the base_year (e.g., 4.9942 for 2023).
    """
    url = (
        "https://api.bcb.gov.br/dados/serie/bcdata.sgs.3698/dados"
        "?formato=json"
        "&dataInicial=01/01/%d&dataFinal=31/12/%d" % (base_year, base_year)
    )

    try:
        import requests  # noqa: PLC0415

        logger.info(
            "Fetching BCB exchange rate (series 3698) for %d...", base_year
        )
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        if not data:
            logger.warning(
                "BCB SGS API returned no data for %d. "
                "Using fallback rate %.4f.",
                base_year, _FALLBACK_EXCHANGE_RATE_2023,
            )
            return _FALLBACK_EXCHANGE_RATE_2023

        rates = [float(d["valor"]) for d in data if d.get("valor")]
        if not rates:
            logger.warning(
                "No valid rates in BCB response for %d. "
                "Using fallback rate %.4f.",
                base_year, _FALLBACK_EXCHANGE_RATE_2023,
            )
            return _FALLBACK_EXCHANGE_RATE_2023

        avg_rate = sum(rates) / len(rates)
        logger.info(
            "BCB exchange rate for %d: %.4f BRL/USD "
            "(average of %d daily observations)",
            base_year, avg_rate, len(rates),
        )
        return avg_rate

    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "BCB SGS API unavailable: %s. "
            "Using fallback 2023 exchange rate: %.4f BRL/USD",
            exc, _FALLBACK_EXCHANGE_RATE_2023,
        )
        return _FALLBACK_EXCHANGE_RATE_2023


def convert_brl_to_usd(
    df: pd.DataFrame,
    cols: list[str],
    exchange_rate: float,
) -> pd.DataFrame:
    """Convert BRL monetary columns to USD using a fixed exchange rate.

    For each column in *cols*, creates a new column named ``{col}_usd``
    containing the value divided by the exchange rate. Original BRL columns
    are preserved unchanged.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame containing monetary columns in BRL.
    cols : list[str]
        Column names to convert (e.g., ["gdp_per_capita", "total_cost_brl"]).
    exchange_rate : float
        BRL per 1 USD (e.g., 4.9942).

    Returns
    -------
    pd.DataFrame
        Copy of df with additional ``{col}_usd`` columns.
    """
    df = df.copy()

    if exchange_rate <= 0:
        logger.error(
            "Invalid exchange rate: %.4f. USD conversion skipped.",
            exchange_rate,
        )
        return df

    converted = 0
    for col in cols:
        if col not in df.columns:
            logger.warning(
                "convert_brl_to_usd: column '%s' not found -- skipped", col
            )
            continue
        usd_col = "%s_usd" % col
        df[usd_col] = df[col] / exchange_rate
        converted += 1

    logger.info(
        "convert_brl_to_usd: %d columns converted (rate=%.4f BRL/USD)",
        converted, exchange_rate,
    )

    return df
