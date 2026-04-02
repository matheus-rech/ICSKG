"""
ICSKG-BR Data Dictionary Generator
====================================
Generates a comprehensive data dictionary from the SQLite schema,
enriched with variable metadata from CIMI_DIMENSIONS, LCOGS_METADATA,
and DIMENSION_MAP constants. Validates the dictionary against the
actual database schema.

Every variable is documented with: table, column_name, sqlite_type,
is_primary_key, source, definition, unit, coverage_years, missingness_rate.

Outputs
-------
  results/data_dictionary.csv

Usage
-----
    python analysis/data_dictionary.py \\
        --db-path database/icskg_br.sqlite \\
        --out-dir results

Exports
-------
    generate_data_dictionary(db_path, out_dir) -> Path
    validate_dictionary_against_schema(db_path, dict_path) -> dict
    main(argv) -> int
"""

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


# ---------------------------------------------------------------------------
# Variable metadata lookup tables
# ---------------------------------------------------------------------------

# From database/build_database_v3.py CIMI_DIMENSIONS
_CIMI_DIMENSION_META: dict[str, dict] = {
    "D1": {
        "source": "FIRJAN/IFGF",
        "definition": "Governance: IFGF fiscal management composite index",
        "unit": "index [0, 1]",
        "coverage_years": "2015-2023",
    },
    "D2": {
        "source": "IBGE/SIDRA",
        "definition": "Economy: GDP per capita (constant 2023 BRL, min-max normalised)",
        "unit": "index [0, 1]",
        "coverage_years": "2015-2023",
    },
    "D3": {
        "source": "IPEA/IDHM",
        "definition": "Human Capital: IDHM composite (2010 cross-sectional, min-max normalised)",
        "unit": "index [0, 1]",
        "coverage_years": "2010 (cross-sectional)",
    },
    "D4": {
        "source": "ANS/IBGE",
        "definition": "Social Cohesion: SUS dependence rate (inverted, min-max normalised)",
        "unit": "index [0, 1]",
        "coverage_years": "2015-2023",
    },
    "D5": {
        "source": "IBGE/Census 2022",
        "definition": "Environment: Adequate sanitation % (2022 cross-sectional, min-max normalised)",
        "unit": "index [0, 1]",
        "coverage_years": "2022 (cross-sectional)",
    },
    "D6": {
        "source": "RENAVAM/DENATRAN",
        "definition": "Mobility: Vehicles per 1,000 inhabitants (min-max normalised)",
        "unit": "index [0, 1]",
        "coverage_years": "2015-2023",
    },
    "D7": {
        "source": "CNES/DATASUS",
        "definition": "Urban Planning: Hospital beds per 10,000 inhabitants (min-max normalised)",
        "unit": "index [0, 1]",
        "coverage_years": "2015-2023",
    },
    "D9": {
        "source": "SIOPS/MS",
        "definition": "Technology: Per-capita health expenditure (min-max normalised)",
        "unit": "index [0, 1]",
        "coverage_years": "2015-2023",
    },
}

# From analysis/compute_lcogs.py LCOGS_METADATA
_LCOGS_META: dict[str, dict] = {
    "lcogs1_distance_km": {
        "source": "CNES facilities + IBGE municipality centroids",
        "definition": (
            "LCoGS-1: Haversine distance (km) from municipality centroid "
            "to nearest bellwether-capable facility municipality"
        ),
        "unit": "km",
        "coverage_years": "2015-2023 (static geometry)",
    },
    "sao_per_100k": {
        "source": "CNES professionals (CBO-filtered) + IBGE SIDRA population",
        "definition": (
            "LCoGS-2: Surgeons, anesthesiologists, and obstetricians "
            "per 100,000 population"
        ),
        "unit": "per 100,000",
        "coverage_years": "2015-2023",
    },
    "surgical_volume_per_100k": {
        "source": "SIH (AIH hospitalisations) + IBGE SIDRA population",
        "definition": "LCoGS-3: SUS-funded surgical procedures per 100,000 population",
        "unit": "per 100,000",
        "coverage_years": "2015-2023",
    },
    "pomr": {
        "source": "SIH (MORTE field within surgical AIH records)",
        "definition": (
            "LCoGS-4: Perioperative mortality rate (in-hospital deaths / "
            "surgical admissions); suppressed for <10 events"
        ),
        "unit": "proportion",
        "coverage_years": "2015-2023",
    },
    "financial_risk_ratio": {
        "source": "SIH (VAL_TOT) + IBGE SIDRA GDP per capita",
        "definition": (
            "LCoGS-5: Mean SIH procedure cost / GDP per capita "
            "(ecological proxy, constant 2023 BRL)"
        ),
        "unit": "ratio",
        "coverage_years": "2015-2023",
    },
    "catastrophic_expenditure": {
        "source": "SIH (VAL_TOT) + IBGE SIDRA GDP per capita",
        "definition": (
            "LCoGS-6: Binary ecological flag: 1 if mean procedure cost "
            "> 10%% of GDP per capita, 0 otherwise"
        ),
        "unit": "binary (0/1)",
        "coverage_years": "2015-2023",
    },
}

# From analysis/compute_dimensions.py DIMENSION_MAP -- raw source columns
_PANEL_SOURCE_META: dict[str, dict] = {
    "ifgf_geral": {
        "source": "FIRJAN/IFGF",
        "definition": "IFGF fiscal management composite (raw value)",
        "unit": "index [0, 1]",
        "coverage_years": "2015-2023",
    },
    "ifgf_ra": {
        "source": "FIRJAN/IFGF",
        "definition": "IFGF Receita Propria (own revenue) sub-index",
        "unit": "index [0, 1]",
        "coverage_years": "2015-2023",
    },
    "ifgf_gp": {
        "source": "FIRJAN/IFGF",
        "definition": "IFGF Gastos com Pessoal (personnel expenditure) sub-index",
        "unit": "index [0, 1]",
        "coverage_years": "2015-2023",
    },
    "ifgf_id": {
        "source": "FIRJAN/IFGF",
        "definition": "IFGF Investimentos (investment) sub-index",
        "unit": "index [0, 1]",
        "coverage_years": "2015-2023",
    },
    "ifgf_el": {
        "source": "FIRJAN/IFGF",
        "definition": "IFGF Liquidez (liquidity) sub-index",
        "unit": "index [0, 1]",
        "coverage_years": "2015-2023",
    },
    "ifgf_sa": {
        "source": "FIRJAN/IFGF",
        "definition": "IFGF Custo da Divida (debt cost) sub-index",
        "unit": "index [0, 1]",
        "coverage_years": "2015-2023",
    },
    "gdp_per_capita": {
        "source": "IBGE/SIDRA",
        "definition": "GDP per capita deflated to constant 2023 BRL",
        "unit": "BRL (constant 2023)",
        "coverage_years": "2015-2023",
    },
    "gdp_abs": {
        "source": "IBGE/SIDRA",
        "definition": "Absolute municipal GDP (x 1,000 BRL, deflated)",
        "unit": "1,000 BRL (constant 2023)",
        "coverage_years": "2015-2023",
    },
    "gdp_estimated": {
        "source": "IBGE/SIDRA",
        "definition": "Flag indicating GDP value is estimated (2022-2023)",
        "unit": "boolean",
        "coverage_years": "2015-2023",
    },
    "idhm": {
        "source": "IPEA/IDHM",
        "definition": "IDHM composite index (2010 cross-sectional)",
        "unit": "index [0, 1]",
        "coverage_years": "2010 (cross-sectional)",
    },
    "idhm_educacao": {
        "source": "IPEA/IDHM",
        "definition": "IDHM education sub-index (2010 cross-sectional)",
        "unit": "index [0, 1]",
        "coverage_years": "2010 (cross-sectional)",
    },
    "idhm_longevidade": {
        "source": "IPEA/IDHM",
        "definition": "IDHM longevity sub-index (2010 cross-sectional)",
        "unit": "index [0, 1]",
        "coverage_years": "2010 (cross-sectional)",
    },
    "idhm_renda": {
        "source": "IPEA/IDHM",
        "definition": "IDHM income sub-index (2010 cross-sectional)",
        "unit": "index [0, 1]",
        "coverage_years": "2010 (cross-sectional)",
    },
    "sus_dependence_rate": {
        "source": "ANS/IBGE",
        "definition": "SUS dependence rate: 100 - private insurance coverage %%",
        "unit": "percentage",
        "coverage_years": "2015-2023",
    },
    "private_coverage_rate": {
        "source": "ANS",
        "definition": "Private health insurance coverage rate (%%)",
        "unit": "percentage",
        "coverage_years": "2015-2023",
    },
    "beneficiarios_mean": {
        "source": "ANS",
        "definition": "Mean quarterly private insurance beneficiaries",
        "unit": "count",
        "coverage_years": "2015-2023",
    },
    "pct_sanitation_adequate": {
        "source": "IBGE/Census 2022",
        "definition": "Percentage of households with adequate sanitation",
        "unit": "percentage",
        "coverage_years": "2022 (cross-sectional)",
    },
    "pct_water_adequate": {
        "source": "IBGE/Census 2022",
        "definition": "Percentage of households with adequate water supply",
        "unit": "percentage",
        "coverage_years": "2022 (cross-sectional)",
    },
    "vehicles_total": {
        "source": "RENAVAM/DENATRAN",
        "definition": "Total registered vehicles in municipality",
        "unit": "count",
        "coverage_years": "2015-2023",
    },
    "vehicles_per_1000": {
        "source": "RENAVAM/DENATRAN",
        "definition": "Vehicles per 1,000 inhabitants",
        "unit": "per 1,000",
        "coverage_years": "2015-2023",
    },
    "total_beds": {
        "source": "CNES/DATASUS",
        "definition": "Total hospital beds in municipality",
        "unit": "count",
        "coverage_years": "2015-2023",
    },
    "is_bellwether": {
        "source": "CNES/DATASUS",
        "definition": "Flag: facility has bellwether surgical capability",
        "unit": "boolean",
        "coverage_years": "2015-2023",
    },
    "health_expenditure_per_capita": {
        "source": "SIOPS/MS",
        "definition": "Per-capita municipal health expenditure (constant 2023 BRL)",
        "unit": "BRL (constant 2023)",
        "coverage_years": "2015-2023",
    },
    "procedure_count": {
        "source": "SIH/DATASUS",
        "definition": "Total SUS-funded surgical procedures (AIH records)",
        "unit": "count",
        "coverage_years": "2015-2023",
    },
    "total_value": {
        "source": "SIH/DATASUS",
        "definition": "Total SIH procedure cost (constant 2023 BRL)",
        "unit": "BRL (constant 2023)",
        "coverage_years": "2015-2023",
    },
    "deaths": {
        "source": "SIH/DATASUS",
        "definition": "In-hospital deaths from surgical admissions",
        "unit": "count",
        "coverage_years": "2015-2023",
    },
    "aih_count": {
        "source": "SIH/DATASUS",
        "definition": "Number of AIH hospitalisation records",
        "unit": "count",
        "coverage_years": "2015-2023",
    },
    "total_days": {
        "source": "SIH/DATASUS",
        "definition": "Total hospitalisation days",
        "unit": "days",
        "coverage_years": "2015-2023",
    },
    "populacao": {
        "source": "IBGE/SIDRA",
        "definition": "Estimated municipal population",
        "unit": "count",
        "coverage_years": "2015-2023",
    },
    "sao_category": {
        "source": "CNES/DATASUS",
        "definition": "SAO professional category (surgeon/anesthesiologist/obstetrician)",
        "unit": "categorical",
        "coverage_years": "2015-2023",
    },
}

# Standard schema columns (keys, identifiers, metadata)
_STANDARD_COLS: dict[str, dict] = {
    "cod_ibge": {
        "source": "IBGE",
        "definition": "7-digit IBGE municipality code (primary spatial key)",
        "unit": "identifier",
        "coverage_years": "2015-2023",
    },
    "year": {
        "source": "Panel structure",
        "definition": "Calendar year of observation",
        "unit": "year",
        "coverage_years": "2015-2023",
    },
    "name": {
        "source": "IBGE",
        "definition": "Official municipality name",
        "unit": "text",
        "coverage_years": "2023 (reference year)",
    },
    "state_uf": {
        "source": "IBGE",
        "definition": "Two-letter state abbreviation (UF)",
        "unit": "text",
        "coverage_years": "2023 (reference year)",
    },
    "region": {
        "source": "IBGE",
        "definition": "IBGE macro-region (Norte, Nordeste, Centro-Oeste, Sudeste, Sul)",
        "unit": "categorical",
        "coverage_years": "2023 (reference year)",
    },
    "population": {
        "source": "IBGE/SIDRA",
        "definition": "Municipality population (from municipality_lookup table)",
        "unit": "count",
        "coverage_years": "2023 (reference year)",
    },
    "cuds": {
        "source": "Computed (geometric mean of D1-D7, D9)",
        "definition": (
            "Composite Urban Development Score: geometric mean of "
            "normalised dimensions with epsilon=0.01 floor"
        ),
        "unit": "index [0, 1]",
        "coverage_years": "2015-2023",
    },
    "n_dimensions": {
        "source": "Computed",
        "definition": "Number of non-NaN dimensions available for this municipality-year",
        "unit": "count (0-8)",
        "coverage_years": "2015-2023",
    },
    "key": {
        "source": "Schema",
        "definition": "Dimension key identifier (D1-D7, D9)",
        "unit": "identifier",
        "coverage_years": "N/A (metadata)",
    },
    "label": {
        "source": "Schema",
        "definition": "Human-readable dimension or indicator label",
        "unit": "text",
        "coverage_years": "N/A (metadata)",
    },
    "source": {
        "source": "Schema",
        "definition": "Data source name for this dimension or indicator",
        "unit": "text",
        "coverage_years": "N/A (metadata)",
    },
    "weight": {
        "source": "Schema",
        "definition": "Dimension weight in composite index (default 1.0, equal-weight)",
        "unit": "numeric",
        "coverage_years": "N/A (metadata)",
    },
    "description": {
        "source": "Schema",
        "definition": "Extended description of dimension or indicator",
        "unit": "text",
        "coverage_years": "N/A (metadata)",
    },
    "is_crosssectional": {
        "source": "Schema",
        "definition": "Flag: 1 if dimension is cross-sectional (no temporal variation)",
        "unit": "boolean (0/1)",
        "coverage_years": "N/A (metadata)",
    },
    "crosssectional_year": {
        "source": "Schema",
        "definition": "Reference year for cross-sectional dimensions (e.g., 2010, 2022)",
        "unit": "year",
        "coverage_years": "N/A (metadata)",
    },
    "ipca_index_dec": {
        "source": "BCB/IBGE",
        "definition": "December IPCA cumulative price index value",
        "unit": "index",
        "coverage_years": "2015-2023",
    },
    "deflation_factor": {
        "source": "Computed from IPCA",
        "definition": "Deflation factor to convert nominal to constant 2023 BRL",
        "unit": "multiplier",
        "coverage_years": "2015-2023",
    },
    "base_year": {
        "source": "Schema",
        "definition": "Base year for deflation (always 2023)",
        "unit": "year",
        "coverage_years": "N/A (constant)",
    },
    "variable": {
        "source": "Schema",
        "definition": "Name of the imputed variable",
        "unit": "identifier",
        "coverage_years": "N/A (metadata)",
    },
    "n_imputed": {
        "source": "Imputation pipeline",
        "definition": "Number of municipality-years imputed for this variable-year",
        "unit": "count",
        "coverage_years": "2015-2023",
    },
    "n_total": {
        "source": "Imputation pipeline",
        "definition": "Total municipality-years for this variable-year",
        "unit": "count",
        "coverage_years": "2015-2023",
    },
    "method": {
        "source": "Imputation pipeline",
        "definition": "Imputation method (e.g., IterativeImputer/BayesianRidge)",
        "unit": "text",
        "coverage_years": "N/A (metadata)",
    },
    "m_imputations": {
        "source": "Imputation pipeline",
        "definition": "Number of multiple imputations (Rubin's rules)",
        "unit": "count",
        "coverage_years": "N/A (parameter)",
    },
    "max_iter": {
        "source": "Imputation pipeline",
        "definition": "Maximum iterations per imputation chain",
        "unit": "count",
        "coverage_years": "N/A (parameter)",
    },
    "aux_variables": {
        "source": "Imputation pipeline",
        "definition": "Comma-separated auxiliary variables used in imputation model",
        "unit": "text",
        "coverage_years": "N/A (metadata)",
    },
    "indicator": {
        "source": "Schema",
        "definition": "LCoGS indicator column name identifier",
        "unit": "identifier",
        "coverage_years": "N/A (metadata)",
    },
    "caveat": {
        "source": "Schema",
        "definition": "Methodological caveat or limitation for this indicator",
        "unit": "text",
        "coverage_years": "N/A (metadata)",
    },
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _lookup_variable_meta(
    table: str,
    column: str,
) -> dict:
    """Look up metadata for a specific table.column combination.

    Searches CIMI dimension metadata, LCoGS metadata, panel source
    metadata, and standard column metadata in priority order.

    Parameters
    ----------
    table : str
        SQLite table name.
    column : str
        Column name within the table.

    Returns
    -------
    dict
        Keys: source, definition, unit, coverage_years.
    """
    # Priority 1: CIMI dimension scores (D1-D7, D9)
    if column in _CIMI_DIMENSION_META:
        return _CIMI_DIMENSION_META[column]

    # Priority 2: LCoGS indicators
    if column in _LCOGS_META:
        return _LCOGS_META[column]

    # Priority 3: Panel source columns
    if column in _PANEL_SOURCE_META:
        return _PANEL_SOURCE_META[column]

    # Priority 4: Standard schema columns
    if column in _STANDARD_COLS:
        return _STANDARD_COLS[column]

    # Fallback: unknown column
    return {
        "source": "Unknown",
        "definition": "Undocumented column in table '%s'" % table,
        "unit": "Unknown",
        "coverage_years": "Unknown",
    }


def _compute_missingness(
    conn: sqlite3.Connection,
    table: str,
    column: str,
) -> float:
    """Compute percentage of NULL/NaN values for a column.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open SQLite connection.
    table : str
        Table name.
    column : str
        Column name.

    Returns
    -------
    float
        Percentage missing (0.0 to 100.0). Returns 0.0 if table is empty.
    """
    try:
        row = conn.execute(
            "SELECT COUNT(*) - COUNT(\"%s\") AS n_missing, "
            "COUNT(*) AS n_total FROM \"%s\"" % (column, table)
        ).fetchone()
        n_missing, n_total = row
        if n_total == 0:
            return 0.0
        return round(n_missing / n_total * 100.0, 2)
    except Exception:  # noqa: BLE001
        return 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_data_dictionary(
    db_path: Path,
    out_dir: Path,
) -> Path:
    """Generate a data dictionary CSV from the SQLite schema.

    Enumerates all tables and columns in the database, enriches each
    with metadata from CIMI_DIMENSIONS, LCOGS_METADATA, and
    DIMENSION_MAP lookups, and computes column-level missingness rates.

    Parameters
    ----------
    db_path : Path
        Path to ICSKG-BR SQLite database.
    out_dir : Path
        Root output directory.

    Returns
    -------
    Path
        Path to the saved CSV file.
    """
    db_path = Path(db_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    rows: list[dict] = []

    try:
        # Enumerate all tables
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "ORDER BY name"
            ).fetchall()
        ]

        logger.info(
            "generate_data_dictionary: found %d tables in %s",
            len(tables), db_path,
        )

        for table in tables:
            # Get column info via PRAGMA
            columns = conn.execute(
                "PRAGMA table_info(\"%s\")" % table
            ).fetchall()

            for col_info in columns:
                # PRAGMA table_info returns:
                # (cid, name, type, notnull, dflt_value, pk)
                col_name = col_info[1]
                col_type = col_info[2]
                is_pk = int(col_info[5]) > 0

                # Look up metadata
                meta = _lookup_variable_meta(table, col_name)

                # Compute missingness for data tables only
                missingness = 0.0
                if table in (
                    "municipal_health", "dimension_scores",
                    "lcogs_indicators",
                ):
                    missingness = _compute_missingness(conn, table, col_name)

                rows.append({
                    "table": table,
                    "column_name": col_name,
                    "sqlite_type": col_type if col_type else "TEXT",
                    "is_primary_key": is_pk,
                    "source": meta["source"],
                    "definition": meta["definition"],
                    "unit": meta["unit"],
                    "coverage_years": meta["coverage_years"],
                    "missingness_rate": missingness,
                })

    finally:
        conn.close()

    df = pd.DataFrame(rows)
    csv_path = out_dir / "data_dictionary.csv"
    df.to_csv(csv_path, index=False)

    # Summary statistics
    n_tables = df["table"].nunique()
    n_cols = len(df)
    n_missing = (df["missingness_rate"] > 0).sum()

    logger.info(
        "generate_data_dictionary: %d tables, %d columns documented, "
        "%d with missingness > 0",
        n_tables, n_cols, n_missing,
    )
    logger.info("Data dictionary saved to %s", csv_path)

    return csv_path


def validate_dictionary_against_schema(
    db_path: Path,
    dict_path: Path,
) -> dict:
    """Validate data dictionary CSV against the SQLite schema.

    Checks that every column in the database appears in the dictionary
    and vice versa.

    Parameters
    ----------
    db_path : Path
        Path to ICSKG-BR SQLite database.
    dict_path : Path
        Path to data dictionary CSV.

    Returns
    -------
    dict
        Keys: valid (bool), missing_from_dict (list), extra_in_dict (list),
        tables_checked (int), columns_checked (int).
    """
    db_path = Path(db_path)
    dict_path = Path(dict_path)

    # Load dictionary
    dict_df = pd.read_csv(dict_path)
    dict_pairs = set(
        zip(dict_df["table"].astype(str), dict_df["column_name"].astype(str))
    )

    # Get schema pairs from SQLite
    conn = sqlite3.connect(str(db_path))
    schema_pairs: set[tuple[str, str]] = set()
    tables_checked = 0

    try:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "ORDER BY name"
            ).fetchall()
        ]
        tables_checked = len(tables)

        for table in tables:
            columns = conn.execute(
                "PRAGMA table_info(\"%s\")" % table
            ).fetchall()
            for col_info in columns:
                schema_pairs.add((table, col_info[1]))

    finally:
        conn.close()

    # Compare
    missing_from_dict = sorted(schema_pairs - dict_pairs)
    extra_in_dict = sorted(dict_pairs - schema_pairs)

    is_valid = len(missing_from_dict) == 0

    result = {
        "valid": is_valid,
        "missing_from_dict": missing_from_dict,
        "extra_in_dict": extra_in_dict,
        "tables_checked": tables_checked,
        "columns_checked": len(schema_pairs),
    }

    if is_valid:
        logger.info(
            "validate_dictionary: PASSED -- %d tables, %d columns all documented",
            tables_checked, len(schema_pairs),
        )
    else:
        logger.warning(
            "validate_dictionary: FAILED -- %d columns missing from dictionary: %s",
            len(missing_from_dict), missing_from_dict,
        )

    if extra_in_dict:
        logger.info(
            "validate_dictionary: %d extra entries in dictionary (not in schema): %s",
            len(extra_in_dict), extra_in_dict,
        )

    return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Generate and validate data dictionary from SQLite schema.

    Usage
    -----
        python analysis/data_dictionary.py \\
            --db-path database/icskg_br.sqlite \\
            --out-dir results
    """
    parser = argparse.ArgumentParser(
        description="ICSKG-BR data dictionary generator",
    )
    parser.add_argument(
        "--db-path",
        default="database/icskg_br.sqlite",
        help="Path to SQLite database (default: database/icskg_br.sqlite)",
    )
    parser.add_argument(
        "--out-dir",
        default="results",
        help="Output directory (default: results)",
    )
    args = parser.parse_args(argv)

    db_path = Path(args.db_path)
    out_dir = Path(args.out_dir)

    logger.info("=" * 60)
    logger.info("DATA DICTIONARY GENERATOR")
    logger.info("=" * 60)

    if not db_path.exists():
        logger.error("Database not found: %s", db_path)
        return 1

    csv_path = generate_data_dictionary(db_path, out_dir)

    # Validate
    result = validate_dictionary_against_schema(db_path, csv_path)

    if not result["valid"]:
        logger.error(
            "Data dictionary validation FAILED: %d columns missing",
            len(result["missing_from_dict"]),
        )
        return 1

    logger.info("Data dictionary generation and validation complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
