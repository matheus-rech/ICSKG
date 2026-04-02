"""
ICSKG-BR LCoGS Indicator Computation Engine
=============================================
Computes all 6 Lancet Commission on Global Surgery indicators at
municipality-year level from the assembled panel, CNES facility/professional
data, and municipality centroids. Persists results to SQLite.

LCoGS Indicators (6)
---------------------
  1. Access to bellwether procedures  -- haversine distance to nearest
     bellwether municipality (km)
  2. SAO workforce density            -- surgeons + anesthesiologists +
     obstetricians per 100,000 pop
  3. Surgical volume                  -- SUS-funded procedures per 100,000 pop
  4. Perioperative mortality rate     -- in-hospital deaths / surgical
     admissions (NaN if <10 events)
  5. Financial risk protection        -- mean SIH procedure cost / GDP per
     capita (both constant 2023 BRL)
  6. Catastrophic expenditure proxy   -- ecological flag: mean procedure cost
     exceeds 10%% of GDP per capita

Caveats
-------
  - All indicators use SUS-funded procedures only (private sector excluded)
  - LCoGS-5 and LCoGS-6 are ecological-level proxies (not individual
    household expenditure)
  - LCoGS-4 POMR suppressed to NaN for municipalities with <10 surgical
    events (unstable rate)

Usage
-----
    python analysis/compute_lcogs.py \\
        --db-path database/icskg_br.sqlite \\
        --facilities-path data_sources/processed/cnes/facilities.parquet \\
        --professionals-path data_sources/processed/cnes/professionals.parquet

Exports
-------
    compute_lcogs1(panel, facilities_df, centroids_df) -> pd.DataFrame
    compute_lcogs2(panel, professionals_df) -> pd.DataFrame
    compute_lcogs3(panel) -> pd.DataFrame
    compute_lcogs4(panel) -> pd.DataFrame
    compute_lcogs5(panel) -> pd.DataFrame
    compute_lcogs6(panel) -> pd.DataFrame
    compute_all_lcogs(panel, facilities_df, professionals_df, centroids_df)
    persist_lcogs_indicators(lcogs_df, db_path) -> int
    seed_lcogs_metadata(conn) -> None
"""

import argparse
import logging
import sqlite3
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

# Catastrophic expenditure threshold: mean procedure cost > 10% of GDP
# per capita. This is an ecological-level proxy, not individual household.
CATASTROPHIC_THRESHOLD = 0.10  # fraction of GDP per capita

# Minimum surgical events for stable POMR computation
MIN_PROCEDURES_POMR = 10

# Earth radius in km for haversine computation
EARTH_RADIUS_KM = 6371.0

# Module-level cache for centroids (avoids re-downloading)
_centroids_cache: pd.DataFrame | None = None


# ---------------------------------------------------------------------------
# Haversine distance (vectorised)
# ---------------------------------------------------------------------------

def _haversine_km(
    lat1: np.ndarray,
    lon1: np.ndarray,
    lat2: np.ndarray,
    lon2: np.ndarray,
) -> np.ndarray:
    """Compute haversine distance in km between two sets of coordinates.

    Pure numpy implementation. Accepts arrays for vectorised computation.

    Parameters
    ----------
    lat1, lon1 : np.ndarray
        Latitude and longitude of first point(s) in decimal degrees.
    lat2, lon2 : np.ndarray
        Latitude and longitude of second point(s) in decimal degrees.

    Returns
    -------
    np.ndarray
        Great-circle distance in kilometres.
    """
    lat1_r = np.radians(lat1)
    lat2_r = np.radians(lat2)
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)

    a = (
        np.sin(dlat / 2.0) ** 2
        + np.cos(lat1_r) * np.cos(lat2_r) * np.sin(dlon / 2.0) ** 2
    )
    c = 2.0 * np.arcsin(np.sqrt(a))

    return EARTH_RADIUS_KM * c


# ---------------------------------------------------------------------------
# Municipality centroids loader
# ---------------------------------------------------------------------------

def _load_municipality_centroids(db_path: Path | None = None) -> pd.DataFrame:
    """Load municipality centroid coordinates.

    Strategy:
      1. Try geobr package (IBGE 2022 shapefiles with centroids)
      2. Fallback: raise FileNotFoundError with install guidance

    Parameters
    ----------
    db_path : Path, optional
        Not used directly; reserved for future CSV fallback.

    Returns
    -------
    pd.DataFrame
        Columns: cod_ibge (str), lat (float), lon (float).
    """
    global _centroids_cache  # noqa: PLW0603

    if _centroids_cache is not None:
        return _centroids_cache

    try:
        import geobr  # noqa: PLC0415

        logger.info("Loading municipality centroids via geobr...")
        gdf = geobr.read_municipality(year=2022)
        gdf["centroid"] = gdf.geometry.centroid
        centroids = pd.DataFrame({
            "cod_ibge": gdf["code_muni"].astype(str).str[:7],
            "lat": gdf["centroid"].y,
            "lon": gdf["centroid"].x,
        })
        _centroids_cache = centroids
        logger.info(
            "Loaded %d municipality centroids from geobr", len(centroids)
        )
        return centroids

    except ImportError:
        raise FileNotFoundError(
            "geobr package not available. Install with: pip install geobr\n"
            "geobr provides IBGE municipality shapefiles with centroid "
            "coordinates needed for LCoGS-1 distance computation."
        )


# ---------------------------------------------------------------------------
# LCoGS-1: Access to bellwether procedures (distance)
# ---------------------------------------------------------------------------

def compute_lcogs1(
    panel: pd.DataFrame,
    facilities_df: pd.DataFrame,
    centroids_df: pd.DataFrame,
) -> pd.DataFrame:
    """Compute LCoGS-1: haversine distance to nearest bellwether municipality.

    For each municipality, computes the great-circle distance (km) to the
    nearest municipality that contains a bellwether-capable facility.
    Municipalities that themselves contain a bellwether facility get 0.0.

    Geocoordinates are static -- same distance for all years.

    Parameters
    ----------
    panel : pd.DataFrame
        Assembled panel with (cod_ibge, year).
    facilities_df : pd.DataFrame
        CNES facilities with is_bellwether column.
    centroids_df : pd.DataFrame
        Municipality centroids with (cod_ibge, lat, lon).

    Returns
    -------
    pd.DataFrame
        Panel with added lcogs1_distance_km column.
    """
    result = panel[["cod_ibge", "year"]].copy()

    # Identify bellwether municipalities
    bw_facilities = facilities_df[facilities_df["is_bellwether"] == True]  # noqa: E712
    bw_munic = set(bw_facilities["cod_ibge"].unique())

    logger.info(
        "LCoGS-1: %d bellwether municipalities identified from %d facilities",
        len(bw_munic), len(bw_facilities),
    )

    # Get centroids for bellwether municipalities
    bw_centroids = centroids_df[centroids_df["cod_ibge"].isin(bw_munic)]
    bw_lats = bw_centroids["lat"].values
    bw_lons = bw_centroids["lon"].values

    if len(bw_centroids) == 0:
        logger.warning(
            "LCoGS-1: no bellwether centroids found -- setting all distances to NaN"
        )
        result["lcogs1_distance_km"] = np.nan
        return result

    # Compute distance for each unique municipality (static across years)
    all_munic = panel["cod_ibge"].unique()
    distance_map: dict[str, float] = {}

    for cod in all_munic:
        if cod in bw_munic:
            distance_map[cod] = 0.0
            continue

        centroid_row = centroids_df[centroids_df["cod_ibge"] == cod]
        if centroid_row.empty:
            distance_map[cod] = np.nan
            continue

        lat = centroid_row["lat"].values[0]
        lon = centroid_row["lon"].values[0]

        # Vectorised distance to all bellwether centroids
        distances = _haversine_km(
            np.full(len(bw_lats), lat),
            np.full(len(bw_lons), lon),
            bw_lats,
            bw_lons,
        )
        distance_map[cod] = float(np.min(distances))

    result["lcogs1_distance_km"] = result["cod_ibge"].map(distance_map)

    n_zero = (result["lcogs1_distance_km"] == 0.0).sum()
    n_nan = result["lcogs1_distance_km"].isna().sum()
    logger.info(
        "LCoGS-1: distances computed -- %d bellwether (0 km), "
        "%d missing centroids (NaN), median=%.1f km",
        n_zero, n_nan,
        result["lcogs1_distance_km"].dropna().median()
        if result["lcogs1_distance_km"].notna().any() else 0.0,
    )

    return result


# ---------------------------------------------------------------------------
# LCoGS-2: SAO workforce density
# ---------------------------------------------------------------------------

def compute_lcogs2(
    panel: pd.DataFrame,
    professionals_df: pd.DataFrame,
) -> pd.DataFrame:
    """Compute LCoGS-2: SAO professionals per 100,000 population.

    Surgeons, anesthesiologists, and obstetricians (SAO) are counted per
    municipality-year. The professionals_df is already deduplicated by
    (cns_prof, cod_ibge, year) in the extraction phase.

    Parameters
    ----------
    panel : pd.DataFrame
        Assembled panel with (cod_ibge, year, populacao).
    professionals_df : pd.DataFrame
        CNES professionals with sao_category column.

    Returns
    -------
    pd.DataFrame
        Panel with added sao_per_100k column.
    """
    result = panel[["cod_ibge", "year"]].copy()

    if professionals_df.empty:
        logger.warning("LCoGS-2: no professional data -- setting SAO density to NaN")
        result["sao_per_100k"] = np.nan
        return result

    # Count SAO professionals per (cod_ibge, year)
    sao_counts = (
        professionals_df
        .groupby(["cod_ibge", "year"])
        .size()
        .reset_index(name="n_sao")
    )

    logger.info(
        "LCoGS-2: %d SAO professionals across %d municipality-year pairs",
        int(sao_counts["n_sao"].sum()),
        len(sao_counts),
    )

    # Merge with panel to get population
    merged = result.merge(
        panel[["cod_ibge", "year", "populacao"]].drop_duplicates(),
        on=["cod_ibge", "year"],
        how="left",
    )
    merged = merged.merge(sao_counts, on=["cod_ibge", "year"], how="left")
    merged["n_sao"] = merged["n_sao"].fillna(0)

    # Compute density; guard against zero population
    pop = merged["populacao"].replace(0, np.nan)
    merged["sao_per_100k"] = merged["n_sao"] / pop * 100_000

    result["sao_per_100k"] = merged["sao_per_100k"].values

    logger.info(
        "LCoGS-2: SAO density computed -- median=%.1f per 100k",
        result["sao_per_100k"].dropna().median()
        if result["sao_per_100k"].notna().any() else 0.0,
    )

    return result


# ---------------------------------------------------------------------------
# LCoGS-3: Surgical volume per 100,000
# ---------------------------------------------------------------------------

def _resolve_column(
    df: pd.DataFrame,
    candidates: list[str],
    label: str,
) -> str | None:
    """Find the first available column from a list of candidates.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame to check.
    candidates : list[str]
        Column names to try in order.
    label : str
        Human-readable label for logging.

    Returns
    -------
    str or None
        First matching column name, or None if none found.
    """
    for col in candidates:
        if col in df.columns:
            return col
    logger.warning(
        "LCoGS: could not find %s column -- tried %s", label, candidates
    )
    return None


def compute_lcogs3(panel: pd.DataFrame) -> pd.DataFrame:
    """Compute LCoGS-3: surgical volume per 100,000 population.

    Uses SUS-funded procedure counts from SIH data only.

    Parameters
    ----------
    panel : pd.DataFrame
        Assembled panel with procedure count and population columns.

    Returns
    -------
    pd.DataFrame
        Panel with added surgical_volume_per_100k column.
    """
    result = panel[["cod_ibge", "year"]].copy()

    proc_col = _resolve_column(
        panel, ["n_procedures", "procedure_count", "aih_count"], "procedure count"
    )

    if proc_col is None or "populacao" not in panel.columns:
        result["surgical_volume_per_100k"] = np.nan
        return result

    pop = panel["populacao"].replace(0, np.nan)
    # SUS-funded procedures only (documented limitation)
    result["surgical_volume_per_100k"] = panel[proc_col] / pop * 100_000

    logger.info(
        "LCoGS-3: surgical volume computed (SUS-funded only) -- "
        "median=%.1f per 100k",
        result["surgical_volume_per_100k"].dropna().median()
        if result["surgical_volume_per_100k"].notna().any() else 0.0,
    )

    return result


# ---------------------------------------------------------------------------
# LCoGS-4: Perioperative mortality rate (POMR)
# ---------------------------------------------------------------------------

def compute_lcogs4(panel: pd.DataFrame) -> pd.DataFrame:
    """Compute LCoGS-4: perioperative mortality rate.

    POMR = in-hospital deaths within surgical admissions (SUS-funded).
    Municipalities with fewer than 10 surgical events get NaN (unstable
    rate suppression).

    Parameters
    ----------
    panel : pd.DataFrame
        Assembled panel with death and procedure count columns.

    Returns
    -------
    pd.DataFrame
        Panel with added pomr column.
    """
    result = panel[["cod_ibge", "year"]].copy()

    proc_col = _resolve_column(
        panel, ["n_procedures", "procedure_count", "aih_count"], "procedure count"
    )
    death_col = _resolve_column(
        panel, ["n_deaths", "deaths"], "death count"
    )

    if proc_col is None or death_col is None:
        result["pomr"] = np.nan
        return result

    procedures = panel[proc_col].values.astype(float)
    deaths = panel[death_col].values.astype(float)

    # POMR = deaths / procedures
    with np.errstate(divide="ignore", invalid="ignore"):
        pomr = np.where(procedures > 0, deaths / procedures, np.nan)

    # Suppress unstable rates where n_procedures < MIN_PROCEDURES_POMR
    pomr = np.where(procedures < MIN_PROCEDURES_POMR, np.nan, pomr)

    result["pomr"] = pomr

    valid = result["pomr"].dropna()
    logger.info(
        "LCoGS-4: POMR computed (SUS-funded, in-hospital deaths) -- "
        "%d suppressed (<10 events), median=%.4f",
        (procedures < MIN_PROCEDURES_POMR).sum(),
        valid.median() if len(valid) > 0 else 0.0,
    )

    return result


# ---------------------------------------------------------------------------
# LCoGS-5: Financial risk protection
# ---------------------------------------------------------------------------

def compute_lcogs5(panel: pd.DataFrame) -> pd.DataFrame:
    """Compute LCoGS-5: financial risk protection ratio.

    financial_risk_ratio = mean_procedure_cost / gdp_per_capita
    Both numerator and denominator are in constant 2023 BRL (deflated
    in Phase 4). This is an ecological-level proxy.

    Parameters
    ----------
    panel : pd.DataFrame
        Assembled panel with cost, procedure, and GDP columns.

    Returns
    -------
    pd.DataFrame
        Panel with added financial_risk_ratio column.
    """
    result = panel[["cod_ibge", "year"]].copy()

    cost_col = _resolve_column(
        panel, ["total_cost_brl", "total_value"], "total cost"
    )
    proc_col = _resolve_column(
        panel, ["n_procedures", "procedure_count", "aih_count"], "procedure count"
    )

    if cost_col is None or proc_col is None or "gdp_per_capita" not in panel.columns:
        result["financial_risk_ratio"] = np.nan
        return result

    total_cost = panel[cost_col].values.astype(float)
    procedures = panel[proc_col].values.astype(float)
    gdp_pc = panel["gdp_per_capita"].values.astype(float)

    # Mean procedure cost
    with np.errstate(divide="ignore", invalid="ignore"):
        mean_cost = np.where(procedures > 0, total_cost / procedures, np.nan)

    # Financial risk ratio; guard against zero GDP
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(gdp_pc > 0, mean_cost / gdp_pc, np.nan)

    result["financial_risk_ratio"] = ratio

    valid = result["financial_risk_ratio"].dropna()
    logger.info(
        "LCoGS-5: financial risk ratio computed (ecological proxy, "
        "constant 2023 BRL) -- median=%.4f",
        valid.median() if len(valid) > 0 else 0.0,
    )

    return result


# ---------------------------------------------------------------------------
# LCoGS-6: Catastrophic expenditure proxy
# ---------------------------------------------------------------------------

def compute_lcogs6(panel: pd.DataFrame) -> pd.DataFrame:
    """Compute LCoGS-6: catastrophic expenditure ecological proxy.

    For each municipality-year: flags as catastrophic (1.0) if mean
    procedure cost exceeds CATASTROPHIC_THRESHOLD (10%%) of annual GDP
    per capita. This is an ecological-level proxy -- not individual
    household data.

    Parameters
    ----------
    panel : pd.DataFrame
        Assembled panel with cost, procedure, and GDP columns.

    Returns
    -------
    pd.DataFrame
        Panel with added catastrophic_expenditure column (0.0 or 1.0).
    """
    result = panel[["cod_ibge", "year"]].copy()

    cost_col = _resolve_column(
        panel, ["total_cost_brl", "total_value"], "total cost"
    )
    proc_col = _resolve_column(
        panel, ["n_procedures", "procedure_count", "aih_count"], "procedure count"
    )

    if cost_col is None or proc_col is None or "gdp_per_capita" not in panel.columns:
        result["catastrophic_expenditure"] = np.nan
        return result

    total_cost = panel[cost_col].values.astype(float)
    procedures = panel[proc_col].values.astype(float)
    gdp_pc = panel["gdp_per_capita"].values.astype(float)

    # Mean procedure cost
    with np.errstate(divide="ignore", invalid="ignore"):
        mean_cost = np.where(procedures > 0, total_cost / procedures, np.nan)

    # Threshold = GDP per capita * CATASTROPHIC_THRESHOLD
    threshold = gdp_pc * CATASTROPHIC_THRESHOLD

    # Flag as catastrophic if mean cost exceeds threshold
    with np.errstate(invalid="ignore"):
        catastrophic = np.where(
            (gdp_pc > 0) & (procedures > 0),
            np.where(mean_cost > threshold, 1.0, 0.0),
            np.nan,
        )

    result["catastrophic_expenditure"] = catastrophic

    valid = result["catastrophic_expenditure"].dropna()
    n_catastrophic = int((valid == 1.0).sum()) if len(valid) > 0 else 0
    logger.info(
        "LCoGS-6: catastrophic expenditure proxy (ecological, "
        "threshold=%.0f%% GDP/cap) -- %d/%d municipalities flagged",
        CATASTROPHIC_THRESHOLD * 100,
        n_catastrophic,
        len(valid),
    )

    return result


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def compute_all_lcogs(
    panel: pd.DataFrame,
    facilities_df: pd.DataFrame,
    professionals_df: pd.DataFrame,
    centroids_df: pd.DataFrame,
) -> pd.DataFrame:
    """Compute all 6 LCoGS indicators and merge into single DataFrame.

    Parameters
    ----------
    panel : pd.DataFrame
        Assembled panel with (cod_ibge, year, populacao, procedure/death/
        cost/GDP columns).
    facilities_df : pd.DataFrame
        CNES facilities with is_bellwether column.
    professionals_df : pd.DataFrame
        CNES professionals with sao_category column.
    centroids_df : pd.DataFrame
        Municipality centroids with (cod_ibge, lat, lon).

    Returns
    -------
    pd.DataFrame
        Columns: cod_ibge, year, lcogs1_distance_km, sao_per_100k,
        surgical_volume_per_100k, pomr, financial_risk_ratio,
        catastrophic_expenditure.
    """
    logger.info("=" * 60)
    logger.info("LCoGS INDICATOR COMPUTATION")
    logger.info("=" * 60)

    lcogs1 = compute_lcogs1(panel, facilities_df, centroids_df)
    lcogs2 = compute_lcogs2(panel, professionals_df)
    lcogs3 = compute_lcogs3(panel)
    lcogs4 = compute_lcogs4(panel)
    lcogs5 = compute_lcogs5(panel)
    lcogs6 = compute_lcogs6(panel)

    # Merge all indicators
    result = panel[["cod_ibge", "year"]].copy()
    result = result.merge(
        lcogs1[["cod_ibge", "year", "lcogs1_distance_km"]],
        on=["cod_ibge", "year"], how="left",
    )
    result = result.merge(
        lcogs2[["cod_ibge", "year", "sao_per_100k"]],
        on=["cod_ibge", "year"], how="left",
    )
    result = result.merge(
        lcogs3[["cod_ibge", "year", "surgical_volume_per_100k"]],
        on=["cod_ibge", "year"], how="left",
    )
    result = result.merge(
        lcogs4[["cod_ibge", "year", "pomr"]],
        on=["cod_ibge", "year"], how="left",
    )
    result = result.merge(
        lcogs5[["cod_ibge", "year", "financial_risk_ratio"]],
        on=["cod_ibge", "year"], how="left",
    )
    result = result.merge(
        lcogs6[["cod_ibge", "year", "catastrophic_expenditure"]],
        on=["cod_ibge", "year"], how="left",
    )

    logger.info(
        "LCoGS indicators computed: %d rows, %d columns",
        len(result), len(result.columns),
    )

    return result


# ---------------------------------------------------------------------------
# SQLite persistence
# ---------------------------------------------------------------------------

def persist_lcogs_indicators(
    lcogs_df: pd.DataFrame,
    db_path: Path,
) -> int:
    """Write LCoGS indicators to SQLite lcogs_indicators table.

    Follows the same pattern as persist_dimension_scores() in
    compute_dimensions.py.

    Parameters
    ----------
    lcogs_df : pd.DataFrame
        Must have columns: cod_ibge, year, and 6 indicator columns.
    db_path : Path
        Path to SQLite database file.

    Returns
    -------
    int
        Number of rows written.
    """
    from database.build_database_v3 import create_schema  # noqa: PLC0415

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))

    try:
        create_schema(conn)
        lcogs_df.to_sql(
            "lcogs_indicators", conn, if_exists="replace", index=False
        )

        # Verify row count
        actual = conn.execute(
            "SELECT COUNT(*) FROM lcogs_indicators"
        ).fetchone()[0]

        logger.info(
            "persist_lcogs_indicators: %d rows written to %s",
            actual, db_path,
        )

        # Seed metadata
        seed_lcogs_metadata(conn)

        return actual

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# LCoGS metadata seeding
# ---------------------------------------------------------------------------

LCOGS_METADATA = [
    {
        "indicator": "lcogs1_distance_km",
        "label": "LCoGS-1: Access to Bellwether Procedures",
        "source": "CNES facilities (is_bellwether) + IBGE municipality centroids",
        "description": (
            "Haversine distance (km) from municipality centroid to nearest "
            "bellwether-capable facility municipality. SUS-funded facilities only."
        ),
        "caveat": (
            "Uses municipality centroids, not actual travel distance. "
            "Does not account for road networks or travel time."
        ),
    },
    {
        "indicator": "sao_per_100k",
        "label": "LCoGS-2: SAO Workforce Density",
        "source": "CNES professionals (CBO-filtered SAO) + IBGE SIDRA population",
        "description": (
            "Surgeons, anesthesiologists, and obstetricians per 100,000 "
            "population. Deduplicated by CNS per municipality-year. "
            "SUS-registered professionals only."
        ),
        "caveat": (
            "Counts SUS-registered professionals only. Private-sector "
            "professionals not included."
        ),
    },
    {
        "indicator": "surgical_volume_per_100k",
        "label": "LCoGS-3: Surgical Volume",
        "source": "SIH (AIH hospitalisations) + IBGE SIDRA population",
        "description": (
            "SUS-funded surgical procedures per 100,000 population per year. "
            "Municipality of treatment (not residence)."
        ),
        "caveat": (
            "SUS-funded procedures only. Private-sector volume excluded. "
            "Municipality of treatment, not patient residence."
        ),
    },
    {
        "indicator": "pomr",
        "label": "LCoGS-4: Perioperative Mortality Rate",
        "source": "SIH (MORTE field within surgical AIH records)",
        "description": (
            "In-hospital deaths within SUS-funded surgical admissions. "
            "Suppressed to NaN for municipalities with <10 events."
        ),
        "caveat": (
            "In-hospital deaths only (30-day post-discharge not captured). "
            "SUS-funded admissions only. Small-sample suppression applied "
            "for <10 surgical events."
        ),
    },
    {
        "indicator": "financial_risk_ratio",
        "label": "LCoGS-5: Financial Risk Protection",
        "source": "SIH (VAL_TOT) + IBGE SIDRA GDP per capita",
        "description": (
            "Mean SIH procedure cost divided by municipal GDP per capita. "
            "Both numerator and denominator in constant 2023 BRL."
        ),
        "caveat": (
            "Ecological-level proxy only. Does not capture individual "
            "household out-of-pocket expenditure. SUS procedure costs "
            "represent government reimbursement, not patient costs. "
            "SUS patients typically face zero direct costs."
        ),
    },
    {
        "indicator": "catastrophic_expenditure",
        "label": "LCoGS-6: Catastrophic Expenditure Proxy",
        "source": "SIH (VAL_TOT) + IBGE SIDRA GDP per capita",
        "description": (
            "Binary ecological flag: 1 if mean SUS procedure cost exceeds "
            "10%% of municipal GDP per capita, 0 otherwise."
        ),
        "caveat": (
            "Ecological-level proxy only. The original LCoGS-6 measures "
            "household-level catastrophic health expenditure (>10%% of "
            "income). This indicator uses aggregate municipality data as "
            "a proxy. SUS patients typically face zero direct costs; "
            "this measures system cost burden, not patient burden."
        ),
    },
]


def seed_lcogs_metadata(conn: sqlite3.Connection) -> None:
    """Seed lcogs_metadata table with 6 indicator definitions.

    Includes ecological-proxy caveats for LCoGS-5 and LCoGS-6.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open SQLite connection (schema must exist).
    """
    cur = conn.cursor()
    cur.executemany(
        "INSERT OR REPLACE INTO lcogs_metadata "
        "(indicator, label, source, description, caveat) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (
                m["indicator"], m["label"], m["source"],
                m["description"], m["caveat"],
            )
            for m in LCOGS_METADATA
        ],
    )
    conn.commit()
    logger.info("Seeded %d lcogs_metadata rows", len(LCOGS_METADATA))


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Compute LCoGS indicators from SQLite panel + CNES Parquet files.

    Usage
    -----
        python analysis/compute_lcogs.py \\
            --db-path database/icskg_br.sqlite \\
            --facilities-path data_sources/processed/cnes/facilities.parquet \\
            --professionals-path data_sources/processed/cnes/professionals.parquet
    """
    parser = argparse.ArgumentParser(
        description="ICSKG-BR LCoGS indicator computation engine",
    )
    parser.add_argument(
        "--db-path",
        default="database/icskg_br.sqlite",
        help="Path to SQLite database (default: database/icskg_br.sqlite)",
    )
    parser.add_argument(
        "--facilities-path",
        default="data_sources/processed/cnes/facilities.parquet",
        help="Path to CNES facilities Parquet file",
    )
    parser.add_argument(
        "--professionals-path",
        default="data_sources/processed/cnes/professionals.parquet",
        help="Path to CNES professionals Parquet file",
    )
    args = parser.parse_args(argv)

    db_path = Path(args.db_path)
    facilities_path = Path(args.facilities_path)
    professionals_path = Path(args.professionals_path)

    # ---------------------------------------------------------------
    # Read panel from SQLite
    # ---------------------------------------------------------------
    if not db_path.exists():
        logger.error("Database not found: %s", db_path)
        return 1

    conn = sqlite3.connect(str(db_path))
    try:
        panel = pd.read_sql("SELECT * FROM municipal_health", conn)
    finally:
        conn.close()

    if len(panel) == 0:
        logger.error("municipal_health table is empty in %s", db_path)
        return 1

    logger.info(
        "Panel loaded: %d rows, %d columns from %s",
        len(panel), len(panel.columns), db_path,
    )

    # ---------------------------------------------------------------
    # Load CNES data
    # ---------------------------------------------------------------
    if facilities_path.exists():
        facilities_df = pd.read_parquet(facilities_path)
        logger.info("Facilities loaded: %d rows from %s", len(facilities_df), facilities_path)
    else:
        logger.warning("Facilities file not found: %s", facilities_path)
        facilities_df = pd.DataFrame(
            columns=["cnes", "cod_ibge", "year", "is_bellwether"]
        )

    if professionals_path.exists():
        professionals_df = pd.read_parquet(professionals_path)
        logger.info(
            "Professionals loaded: %d rows from %s",
            len(professionals_df), professionals_path,
        )
    else:
        logger.warning("Professionals file not found: %s", professionals_path)
        professionals_df = pd.DataFrame(
            columns=["cnes", "cod_ibge", "year", "cbo", "cns_prof", "sao_category"]
        )

    # ---------------------------------------------------------------
    # Load municipality centroids
    # ---------------------------------------------------------------
    try:
        centroids_df = _load_municipality_centroids()
    except FileNotFoundError as exc:
        logger.error("Cannot load centroids: %s", exc)
        return 1

    # ---------------------------------------------------------------
    # Compute all 6 LCoGS indicators
    # ---------------------------------------------------------------
    lcogs_df = compute_all_lcogs(
        panel, facilities_df, professionals_df, centroids_df,
    )

    # ---------------------------------------------------------------
    # Persist to SQLite
    # ---------------------------------------------------------------
    n_rows = persist_lcogs_indicators(lcogs_df, db_path)

    # ---------------------------------------------------------------
    # Summary statistics
    # ---------------------------------------------------------------
    for col in [
        "lcogs1_distance_km", "sao_per_100k",
        "surgical_volume_per_100k", "pomr",
        "financial_risk_ratio", "catastrophic_expenditure",
    ]:
        if col in lcogs_df.columns:
            valid = lcogs_df[col].dropna()
            if len(valid) > 0:
                logger.info(
                    "  %s: mean=%.4f, median=%.4f, min=%.4f, max=%.4f",
                    col, valid.mean(), valid.median(), valid.min(), valid.max(),
                )

    logger.info("LCoGS computation complete: %d rows persisted", n_rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
