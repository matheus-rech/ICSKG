"""
ICSKG-BR Health Region Crosswalk and Aggregation
==================================================
Maps all 5,570 Brazilian municipalities to their Regiao de Saude (health
region) and aggregates municipality-level indicators to the health region
level (~438-450 health regions defined by the Ministry of Health).

Health regions (Regioes de Saude) are the primary unit of health system
planning in Brazil, defined by Decree 7508/2011. Each health region
comprises a contiguous set of municipalities sharing health service
networks. Aggregating ICSKG-BR indicators to this level provides a
policy-relevant analysis unit between municipality and state.

Data sources
------------
  1. DATASUS TabNet health region crosswalk (preferred)
  2. Local fallback: data_sources/reference/health_regions.csv
  3. IBGE microregion approximation (last resort)

Outputs
-------
    health_region_panel.csv : health-region-year panel with aggregated indicators

Exports
-------
    load_health_region_crosswalk(cache_dir) -> pd.DataFrame
    aggregate_by_health_region(panel, crosswalk) -> pd.DataFrame
    main(argv)

Usage
-----
    python database/health_regions.py \\
        --db-path database/icskg_br.sqlite \\
        --out-dir analysis/results
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

# DATASUS TabNet health region crosswalk URL (CIR/CISR mapping)
HEALTH_REGION_URL: str = (
    "http://tabnet.datasus.gov.br/cgi/ibge/cnv/regsaudebr.def"
)

# Local fallback path
FALLBACK_PATH: Path = (
    Path(__file__).parent.parent / "data_sources" / "reference" / "health_regions.csv"
)

# Expected number of health regions in Brazil (~438-450)
EXPECTED_HEALTH_REGIONS_MIN: int = 430
EXPECTED_HEALTH_REGIONS_MAX: int = 460

# Columns that represent rates (population-weighted mean in aggregation)
_RATE_COLUMNS: list[str] = [
    "sao_per_100k",
    "surgical_volume_per_100k",
    "pomr",
    "financial_risk_ratio",
    "lcogs1_distance_km",
]

# Columns that represent counts (summed in aggregation)
_COUNT_COLUMNS: list[str] = [
    "n_procedures",
    "n_deaths",
    "populacao",
    "total_cost_brl",
]

# Dimension score columns (population-weighted mean)
_DIMENSION_COLUMNS: list[str] = [
    "D1", "D2", "D3", "D4", "D5", "D6", "D7", "D9",
    "cuds",
]

# Binary/proportion columns (population-weighted mean = proportion)
_PROPORTION_COLUMNS: list[str] = [
    "catastrophic_expenditure",
]


# ---------------------------------------------------------------------------
# Crosswalk loader
# ---------------------------------------------------------------------------

def load_health_region_crosswalk(
    cache_dir: Path | None = None,
) -> pd.DataFrame:
    """Load the municipality-to-health-region crosswalk.

    Strategy:
      1. Try loading from data_sources/reference/health_regions.csv
      2. Try downloading from DATASUS TabNet
      3. Fallback: generate from IBGE municipality codes (microregion proxy)

    Parameters
    ----------
    cache_dir : Path, optional
        Directory containing cached reference data. If None, uses
        data_sources/reference/.

    Returns
    -------
    pd.DataFrame
        Columns: cod_ibge (str, 7-digit), health_region_code (str),
        health_region_name (str), uf (str).
    """
    if cache_dir is None:
        cache_dir = Path("data_sources") / "reference"

    csv_path = cache_dir / "health_regions.csv"

    # ---------------------------------------------------------------------------
    # Strategy 1: Local CSV cache
    # ---------------------------------------------------------------------------
    if csv_path.exists():
        logger.info("Loading health region crosswalk from: %s", csv_path)
        crosswalk = pd.read_csv(csv_path, dtype=str)

        # Ensure expected columns
        required = {"cod_ibge", "health_region_code", "health_region_name", "uf"}
        if required.issubset(set(crosswalk.columns)):
            n_regions = crosswalk["health_region_code"].nunique()
            logger.info(
                "Health region crosswalk loaded: %d municipalities, "
                "%d health regions",
                len(crosswalk), n_regions,
            )
            return crosswalk
        else:
            logger.warning(
                "health_regions.csv missing columns: %s",
                required - set(crosswalk.columns),
            )

    # ---------------------------------------------------------------------------
    # Strategy 2: Download from DATASUS
    # ---------------------------------------------------------------------------
    try:
        import requests  # noqa: PLC0415

        logger.info("Downloading health region crosswalk from DATASUS...")
        resp = requests.get(
            "https://sage.saude.gov.br/paineis/regiaoSaude/lista.php",
            timeout=30,
        )
        if resp.status_code == 200 and len(resp.text) > 100:
            # Parse HTML table or JSON response
            try:
                tables = pd.read_html(resp.text)
                if tables:
                    raw = tables[0]
                    # Normalize column names
                    raw.columns = [c.strip().lower() for c in raw.columns]
                    crosswalk = _parse_datasus_crosswalk(raw)
                    if crosswalk is not None and len(crosswalk) > 0:
                        # Cache for future use
                        csv_path.parent.mkdir(parents=True, exist_ok=True)
                        crosswalk.to_csv(csv_path, index=False)
                        logger.info(
                            "Cached health region crosswalk: %d municipalities",
                            len(crosswalk),
                        )
                        return crosswalk
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to parse DATASUS response: %s", exc
                )
        else:
            logger.warning(
                "DATASUS request returned status %d", resp.status_code
            )

    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "DATASUS download failed: %s. Trying IBGE fallback.",
            exc,
        )

    # ---------------------------------------------------------------------------
    # Strategy 3: Generate from IBGE municipality codes (microregion proxy)
    # ---------------------------------------------------------------------------
    logger.info(
        "Generating health region crosswalk from IBGE municipality codes "
        "(microregion approximation)"
    )
    crosswalk = _generate_microregion_crosswalk()

    # Cache for future use
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    crosswalk.to_csv(csv_path, index=False)
    logger.info(
        "Generated and cached microregion-based crosswalk: "
        "%d municipalities, %d regions",
        len(crosswalk),
        crosswalk["health_region_code"].nunique(),
    )

    return crosswalk


def _parse_datasus_crosswalk(raw: pd.DataFrame) -> pd.DataFrame | None:
    """Parse a raw DATASUS crosswalk DataFrame into standard format.

    Parameters
    ----------
    raw : pd.DataFrame
        Raw table from DATASUS response.

    Returns
    -------
    pd.DataFrame or None
        Standardised crosswalk or None if parsing fails.
    """
    # Try common column patterns
    col_map = {}
    for col in raw.columns:
        col_lower = col.lower()
        if "ibge" in col_lower or "municipio" in col_lower and "cod" in col_lower:
            col_map["cod_ibge"] = col
        elif "regiao" in col_lower and "saude" in col_lower and "cod" in col_lower:
            col_map["health_region_code"] = col
        elif "regiao" in col_lower and "saude" in col_lower and "nome" in col_lower:
            col_map["health_region_name"] = col
        elif col_lower == "uf":
            col_map["uf"] = col

    if len(col_map) < 2:
        return None

    result = raw.rename(columns={v: k for k, v in col_map.items()})
    return result[list(col_map.keys())].copy()


def _generate_microregion_crosswalk() -> pd.DataFrame:
    """Generate a health region crosswalk from IBGE municipality codes.

    Uses the first 4 digits of the 7-digit IBGE code as a microregion
    proxy. This is an approximation -- real health regions may span
    different microregions.

    Returns
    -------
    pd.DataFrame
        Columns: cod_ibge, health_region_code, health_region_name, uf.
    """
    try:
        from database.utils import load_ibge_municipios  # noqa: PLC0415

        ref = load_ibge_municipios()
        crosswalk = pd.DataFrame({
            "cod_ibge": ref["cod_ibge"].astype(str),
            "health_region_code": ref["cod_ibge"].astype(str).str[:4],
            "health_region_name": "Microregion " + ref["cod_ibge"].astype(str).str[:4],
            "uf": ref["uf"],
        })

        n_regions = crosswalk["health_region_code"].nunique()
        logger.info(
            "Microregion crosswalk: %d municipalities -> %d regions",
            len(crosswalk), n_regions,
        )

        return crosswalk

    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Cannot generate microregion crosswalk: %s. "
            "Returning empty DataFrame.",
            exc,
        )
        return pd.DataFrame(
            columns=["cod_ibge", "health_region_code", "health_region_name", "uf"]
        )


# ---------------------------------------------------------------------------
# Health region aggregation
# ---------------------------------------------------------------------------

def aggregate_by_health_region(
    panel: pd.DataFrame,
    crosswalk: pd.DataFrame,
) -> pd.DataFrame:
    """Aggregate municipality-level panel to health region level.

    For rate variables: population-weighted mean.
    For count variables: sum.
    For dimension scores: population-weighted mean.
    For binary/proportion: population-weighted mean (= proportion).

    Parameters
    ----------
    panel : pd.DataFrame
        Municipality-year panel with cod_ibge, year, and indicator columns.
    crosswalk : pd.DataFrame
        Health region crosswalk with cod_ibge, health_region_code,
        health_region_name, uf columns.

    Returns
    -------
    pd.DataFrame
        Health-region-year panel with aggregated indicators.
    """
    logger.info("Aggregating panel to health region level...")

    # Merge panel with crosswalk
    panel = panel.copy()
    panel["cod_ibge"] = panel["cod_ibge"].astype(str)
    crosswalk["cod_ibge"] = crosswalk["cod_ibge"].astype(str)

    merged = panel.merge(
        crosswalk[["cod_ibge", "health_region_code", "health_region_name"]],
        on="cod_ibge",
        how="left",
    )

    unmatched = merged["health_region_code"].isna().sum()
    if unmatched > 0:
        logger.warning(
            "aggregate_by_health_region: %d rows without health region match",
            unmatched,
        )
        merged = merged.dropna(subset=["health_region_code"])

    # Identify present columns from each category
    rate_cols = [c for c in _RATE_COLUMNS if c in merged.columns]
    count_cols = [c for c in _COUNT_COLUMNS if c in merged.columns]
    dim_cols = [c for c in _DIMENSION_COLUMNS if c in merged.columns]
    prop_cols = [c for c in _PROPORTION_COLUMNS if c in merged.columns]
    weighted_cols = rate_cols + dim_cols + prop_cols

    group_keys = ["health_region_code", "health_region_name", "year"]

    # ---------------------------------------------------------------------------
    # Population-weighted mean for rates, dimensions, proportions
    # ---------------------------------------------------------------------------
    pop_col = "populacao" if "populacao" in merged.columns else None

    if pop_col and weighted_cols:
        # Compute population weight per municipality within each health region-year
        merged["_pop_weight"] = merged.groupby(group_keys, observed=True)[pop_col].transform(
            lambda x: x / x.sum() if x.sum() > 0 else 0
        )

        # Weighted values
        for col in weighted_cols:
            merged[f"_w_{col}"] = merged[col] * merged["_pop_weight"]

        weighted_agg = {
            f"_w_{col}": "sum" for col in weighted_cols
        }
    else:
        weighted_agg = {}

    # Count aggregation (simple sum)
    count_agg = {col: "sum" for col in count_cols}

    # Municipality count
    munic_agg = {"cod_ibge": "nunique"}

    # Combine all aggregations
    all_agg = {**weighted_agg, **count_agg, **munic_agg}

    if not all_agg:
        logger.warning("No columns found for aggregation")
        return pd.DataFrame()

    result = (
        merged
        .groupby(group_keys, observed=True)
        .agg(all_agg)
        .reset_index()
    )

    # Rename weighted columns back to original names
    rename_map = {f"_w_{col}": col for col in weighted_cols}
    rename_map["cod_ibge"] = "n_municipalities"
    result = result.rename(columns=rename_map)

    n_regions = result["health_region_code"].nunique()
    n_years = result["year"].nunique()
    logger.info(
        "Health region aggregation: %d regions x %d years = %d rows, "
        "%d columns",
        n_regions, n_years, len(result), len(result.columns),
    )

    return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Aggregate ICSKG-BR panel data to health region level.

    Usage
    -----
        python database/health_regions.py \\
            --db-path database/icskg_br.sqlite \\
            --out-dir analysis/results
    """
    parser = argparse.ArgumentParser(
        description="ICSKG-BR health region crosswalk and aggregation",
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
    args = parser.parse_args(argv)

    db_path = Path(args.db_path)
    out_dir = Path(args.out_dir)

    # ---------------------------------------------------------------
    # Load health region crosswalk
    # ---------------------------------------------------------------
    crosswalk = load_health_region_crosswalk()
    n_regions = crosswalk["health_region_code"].nunique()
    logger.info(
        "Crosswalk loaded: %d municipalities -> %d health regions",
        len(crosswalk), n_regions,
    )

    # ---------------------------------------------------------------
    # Load panel from SQLite
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
        "Panel loaded: %d rows, %d columns", len(panel), len(panel.columns)
    )

    # ---------------------------------------------------------------
    # Aggregate to health region level
    # ---------------------------------------------------------------
    hr_panel = aggregate_by_health_region(panel, crosswalk)

    if hr_panel.empty:
        logger.warning("Health region panel is empty")
        return 1

    # ---------------------------------------------------------------
    # Save outputs
    # ---------------------------------------------------------------
    tables_dir = out_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    hr_path = tables_dir / "health_region_panel.csv"
    hr_panel.to_csv(hr_path, index=False)
    logger.info("Saved health region panel: %s (%d rows)", hr_path, len(hr_panel))

    # ---------------------------------------------------------------
    # Persist to SQLite
    # ---------------------------------------------------------------
    conn = sqlite3.connect(str(db_path))
    try:
        hr_panel.to_sql(
            "health_region_indicators", conn, if_exists="replace", index=False
        )
        logger.info(
            "Persisted %d rows to health_region_indicators table in %s",
            len(hr_panel), db_path,
        )
    finally:
        conn.close()

    logger.info("Health region aggregation complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
