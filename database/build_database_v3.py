"""
ICSKG-BR Database Builder v3 — CIMI-aligned SQLite Schema
============================================================
Assembles the final ICSKG-BR relational database from the merged,
validated, and imputed municipality-year panel produced by the Phase 4
pipeline (assemble_panel -> impute_ifgf_mice -> build_database).

Schema v3 replaces the health-system-centric v2 dimensions with
CIMI-aligned dimensions (D1 Governance through D9 Technology, excluding
D8 International Projection). All 5 tables support audit trail
requirements: deflation_log, imputation_log, dimension_metadata,
municipality_lookup, and the main municipal_health panel.

Outputs
-------
  database/icskg_br.sqlite — SQLite database with v3 schema

Schema (5 tables)
------------------
  municipal_health     — (cod_ibge, year) PK panel with all source columns
  dimension_metadata   — CIMI dimension definitions and weights
  municipality_lookup  — IBGE codes, names, state, region
  deflation_log        — IPCA deflation factors per year
  imputation_log       — IFGF imputation method and per-year counts

Usage
-----
    python database/build_database_v3.py --processed-dir data_sources/processed \\
                                          --db-dir database \\
                                          --years 2015 2023
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
# Schema DDL (SQLite v3)
# ---------------------------------------------------------------------------

DDL_MUNICIPAL_HEALTH = """
CREATE TABLE IF NOT EXISTS municipal_health (
    cod_ibge    TEXT    NOT NULL,
    year        INTEGER NOT NULL,
    PRIMARY KEY (cod_ibge, year)
);
"""

DDL_DIMENSION_METADATA = """
CREATE TABLE IF NOT EXISTS dimension_metadata (
    key                  TEXT PRIMARY KEY,
    label                TEXT NOT NULL,
    source               TEXT,
    weight               REAL DEFAULT 1.0,
    description          TEXT,
    is_crosssectional    INTEGER DEFAULT 0,
    crosssectional_year  INTEGER
);
"""

DDL_MUNICIPALITY_LOOKUP = """
CREATE TABLE IF NOT EXISTS municipality_lookup (
    cod_ibge   TEXT PRIMARY KEY,
    name       TEXT,
    state_uf   TEXT,
    region     TEXT,
    population INTEGER
);
"""

DDL_DEFLATION_LOG = """
CREATE TABLE IF NOT EXISTS deflation_log (
    year              INTEGER PRIMARY KEY,
    ipca_index_dec    REAL,
    deflation_factor  REAL,
    base_year         INTEGER DEFAULT 2023
);
"""

DDL_IMPUTATION_LOG = """
CREATE TABLE IF NOT EXISTS imputation_log (
    variable       TEXT NOT NULL,
    year           INTEGER NOT NULL,
    n_imputed      INTEGER,
    n_total        INTEGER,
    method         TEXT,
    m_imputations  INTEGER,
    max_iter       INTEGER,
    aux_variables  TEXT,
    PRIMARY KEY (variable, year)
);
"""

DDL_DIMENSION_SCORES = """
CREATE TABLE IF NOT EXISTS dimension_scores (
    cod_ibge       TEXT    NOT NULL,
    year           INTEGER NOT NULL,
    D1             REAL,
    D2             REAL,
    D3             REAL,
    D4             REAL,
    D5             REAL,
    D6             REAL,
    D7             REAL,
    D9             REAL,
    cuds           REAL,
    n_dimensions   INTEGER,
    PRIMARY KEY (cod_ibge, year)
);
"""

ALL_DDL = [
    DDL_MUNICIPAL_HEALTH,
    DDL_DIMENSION_METADATA,
    DDL_MUNICIPALITY_LOOKUP,
    DDL_DEFLATION_LOG,
    DDL_IMPUTATION_LOG,
    DDL_DIMENSION_SCORES,
]


# ---------------------------------------------------------------------------
# CIMI Dimension Metadata (8 active, D8 excluded)
# ---------------------------------------------------------------------------

# UF -> region mapping (IBGE standard macro-regions)
UF_TO_REGION: dict[str, str] = {
    # Norte
    "AC": "Norte", "AP": "Norte", "AM": "Norte", "PA": "Norte",
    "RO": "Norte", "RR": "Norte", "TO": "Norte",
    # Nordeste
    "AL": "Nordeste", "BA": "Nordeste", "CE": "Nordeste", "MA": "Nordeste",
    "PB": "Nordeste", "PE": "Nordeste", "PI": "Nordeste", "RN": "Nordeste",
    "SE": "Nordeste",
    # Centro-Oeste
    "DF": "Centro-Oeste", "GO": "Centro-Oeste", "MT": "Centro-Oeste",
    "MS": "Centro-Oeste",
    # Sudeste
    "ES": "Sudeste", "MG": "Sudeste", "RJ": "Sudeste", "SP": "Sudeste",
    # Sul
    "PR": "Sul", "RS": "Sul", "SC": "Sul",
}

CIMI_DIMENSIONS: list[dict] = [
    {
        "key": "D1",
        "label": "Governance (IFGF)",
        "source": "FIRJAN/IFGF",
        "weight": 1.0,
        "description": "IFGF fiscal management composite index",
        "is_crosssectional": 0,
        "crosssectional_year": None,
    },
    {
        "key": "D2",
        "label": "Economy (GDP per capita)",
        "source": "IBGE/SIDRA",
        "weight": 1.0,
        "description": "GDP per capita deflated to constant 2023 BRL",
        "is_crosssectional": 0,
        "crosssectional_year": None,
    },
    {
        "key": "D3",
        "label": "Human Capital (IDHM)",
        "source": "IPEA/IDHM",
        "weight": 1.0,
        "description": "IDHM composite + sub-indices (education, longevity, income)",
        "is_crosssectional": 1,
        "crosssectional_year": 2010,
    },
    {
        "key": "D4",
        "label": "Social Cohesion (SUS dependence)",
        "source": "ANS/IBGE",
        "weight": 1.0,
        "description": "SUS dependence rate (100 - ANS private coverage %)",
        "is_crosssectional": 0,
        "crosssectional_year": None,
    },
    {
        "key": "D5",
        "label": "Environment (Sanitation)",
        "source": "IBGE/Census 2022",
        "weight": 1.0,
        "description": "Adequate sanitation % from Census 2022",
        "is_crosssectional": 1,
        "crosssectional_year": 2022,
    },
    {
        "key": "D6",
        "label": "Mobility (Vehicle fleet)",
        "source": "RENAVAM/DENATRAN",
        "weight": 1.0,
        "description": "Vehicles per 1,000 inhabitants",
        "is_crosssectional": 0,
        "crosssectional_year": None,
    },
    {
        "key": "D7",
        "label": "Urban Planning (Hospital capacity)",
        "source": "CNES/DATASUS",
        "weight": 1.0,
        "description": "Hospital beds per 10,000 inhabitants",
        "is_crosssectional": 0,
        "crosssectional_year": None,
    },
    {
        "key": "D9",
        "label": "Technology (Health expenditure)",
        "source": "SIOPS/MS",
        "weight": 1.0,
        "description": "Per-capita health expenditure as technology proxy",
        "is_crosssectional": 0,
        "crosssectional_year": None,
    },
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_schema(conn: sqlite3.Connection) -> None:
    """Execute all CREATE TABLE IF NOT EXISTS DDL statements.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open SQLite connection.
    """
    cur = conn.cursor()
    for ddl in ALL_DDL:
        cur.executescript(ddl)
    conn.commit()
    logger.info("Schema v3 initialised (6 tables created)")


def seed_dimension_metadata(conn: sqlite3.Connection) -> None:
    """Seed dimension_metadata table with 8 active CIMI dimensions.

    D8 (International Projection) is excluded as irrelevant at
    municipal level for 99%% of Brazilian municipalities.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open SQLite connection (schema must exist).
    """
    cur = conn.cursor()
    cur.executemany(
        "INSERT OR REPLACE INTO dimension_metadata "
        "(key, label, source, weight, description, "
        "is_crosssectional, crosssectional_year) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                d["key"], d["label"], d["source"], d["weight"],
                d["description"], d["is_crosssectional"],
                d["crosssectional_year"],
            )
            for d in CIMI_DIMENSIONS
        ],
    )
    conn.commit()
    logger.info(
        "Seeded %d CIMI dimension metadata rows (D8 excluded)",
        len(CIMI_DIMENSIONS),
    )


def seed_municipality_lookup(conn: sqlite3.Connection) -> None:
    """Populate municipality_lookup from IBGE 2023 reference list.

    Derives region from UF using standard IBGE macro-region mapping.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open SQLite connection (schema must exist).
    """
    from database.utils import load_ibge_municipios  # noqa: PLC0415

    ref = load_ibge_municipios()
    ref = ref.rename(columns={"nome_municipio": "name", "uf": "state_uf"})
    ref["region"] = ref["state_uf"].map(UF_TO_REGION)

    # Only keep columns matching the schema
    lookup_cols = ["cod_ibge", "name", "state_uf", "region"]
    lookup_df = ref[lookup_cols].copy()

    # Use INSERT OR REPLACE for idempotency
    cur = conn.cursor()
    cur.executemany(
        "INSERT OR REPLACE INTO municipality_lookup "
        "(cod_ibge, name, state_uf, region) VALUES (?, ?, ?, ?)",
        lookup_df.values.tolist(),
    )
    conn.commit()
    logger.info(
        "Seeded %d municipality_lookup rows", len(lookup_df),
    )


def seed_deflation_log(
    conn: sqlite3.Connection,
    ipca_df: pd.DataFrame,
) -> None:
    """Populate deflation_log from IPCA factors DataFrame.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open SQLite connection (schema must exist).
    ipca_df : pd.DataFrame
        Must have columns: year, ipca_index, deflation_factor.
    """
    cur = conn.cursor()
    rows = []
    for _, row in ipca_df.iterrows():
        rows.append((
            int(row["year"]),
            float(row["ipca_index"]),
            float(row["deflation_factor"]),
            2023,
        ))
    cur.executemany(
        "INSERT OR REPLACE INTO deflation_log "
        "(year, ipca_index_dec, deflation_factor, base_year) "
        "VALUES (?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    logger.info("Seeded %d deflation_log rows", len(rows))


def seed_imputation_log(
    conn: sqlite3.Connection,
    imputation_log: dict,
) -> None:
    """Populate imputation_log from IFGF imputation results.

    Creates one row per (variable, year) combination from the
    imputation log dictionary.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open SQLite connection (schema must exist).
    imputation_log : dict
        Output of impute_ifgf_mice(), must have keys:
        m, max_iter, method, ifgf_cols, aux_cols, per_year.
    """
    cur = conn.cursor()
    m = imputation_log.get("m", 5)
    max_iter = imputation_log.get("max_iter", 10)
    method = imputation_log.get("method", "unknown")
    ifgf_cols = imputation_log.get("ifgf_cols", [])
    aux_cols = imputation_log.get("aux_cols", [])
    per_year = imputation_log.get("per_year", {})
    aux_str = ", ".join(aux_cols)

    rows = []
    for year, n_imputed in per_year.items():
        for variable in ifgf_cols:
            rows.append((
                variable,
                int(year),
                n_imputed,
                None,  # n_total not tracked per-variable
                method,
                m,
                max_iter,
                aux_str,
            ))

    cur.executemany(
        "INSERT OR REPLACE INTO imputation_log "
        "(variable, year, n_imputed, n_total, method, "
        "m_imputations, max_iter, aux_variables) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    logger.info("Seeded %d imputation_log rows", len(rows))


def load_panel(
    conn: sqlite3.Connection,
    panel: pd.DataFrame,
) -> int:
    """Load the assembled panel into municipal_health table.

    Uses pandas df.to_sql with if_exists="replace" for idempotency
    (NOT iterrows -- batch insert per research anti-pattern guidance).

    Parameters
    ----------
    conn : sqlite3.Connection
        Open SQLite connection (schema must exist).
    panel : pd.DataFrame
        The assembled, imputed panel DataFrame.

    Returns
    -------
    int
        Number of rows inserted.
    """
    n_rows = len(panel)
    panel.to_sql(
        "municipal_health",
        conn,
        if_exists="replace",
        index=False,
    )

    # Verify row count
    actual = conn.execute(
        "SELECT COUNT(*) FROM municipal_health"
    ).fetchone()[0]

    if actual != n_rows:
        logger.warning(
            "load_panel: expected %d rows but found %d in municipal_health",
            n_rows, actual,
        )
    else:
        logger.info(
            "load_panel: %d rows loaded into municipal_health", actual,
        )

    return actual


def build_database(
    panel: pd.DataFrame,
    ipca_df: pd.DataFrame,
    imputation_log: dict,
    db_path: Path | str,
    processed_dir: Path | str | None = None,
) -> Path:
    """Orchestrate full database build: schema -> seed -> load -> report.

    Parameters
    ----------
    panel : pd.DataFrame
        The assembled, imputed panel.
    ipca_df : pd.DataFrame
        IPCA deflation factors.
    imputation_log : dict
        Output of impute_ifgf_mice().
    db_path : Path or str
        Output SQLite file path.
    processed_dir : Path or str, optional
        Directory for PANL-06-missingness.csv output.

    Returns
    -------
    Path
        The database file path (confirmed written).
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("BUILD DATABASE v3: %s", db_path)
    logger.info("=" * 60)

    conn = sqlite3.connect(str(db_path))

    try:
        create_schema(conn)
        seed_dimension_metadata(conn)
        seed_municipality_lookup(conn)
        seed_deflation_log(conn, ipca_df)
        seed_imputation_log(conn, imputation_log)

        n = load_panel(conn, panel)
        logger.info("Panel loaded: %d rows", n)

        # Generate missingness report if processed_dir provided
        if processed_dir is not None:
            processed_dir = Path(processed_dir)
            from database.impute_ifgf import (  # noqa: PLC0415
                generate_missingness_report,
            )
            missingness_path = processed_dir / "PANL-06-missingness.csv"
            generate_missingness_report(panel, missingness_path)

        # Log table sizes
        for table in [
            "municipal_health", "dimension_metadata",
            "municipality_lookup", "deflation_log", "imputation_log",
        ]:
            count = conn.execute(
                "SELECT COUNT(*) FROM %s" % table
            ).fetchone()[0]
            logger.info("  %s: %d rows", table, count)

    finally:
        conn.close()

    logger.info("Database build complete: %s", db_path)
    return db_path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """End-to-end Phase 4 orchestrator: assemble -> impute -> persist.

    Usage
    -----
        python database/build_database_v3.py \\
            --processed-dir data_sources/processed \\
            --db-dir database \\
            --years 2015 2023
    """
    parser = argparse.ArgumentParser(
        description="ICSKG-BR database builder v3 (CIMI-aligned schema)",
    )
    parser.add_argument(
        "--processed-dir",
        default="data_sources/processed",
        help="Root directory for processed source files",
    )
    parser.add_argument(
        "--db-dir",
        default="database",
        help="Directory for output SQLite database",
    )
    parser.add_argument(
        "--years",
        nargs=2,
        type=int,
        default=[2015, 2023],
        metavar=("START", "END"),
        help="Start and end years (inclusive)",
    )
    args = parser.parse_args(argv)

    processed_dir = Path(args.processed_dir)
    db_dir = Path(args.db_dir)
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "icskg_br.sqlite"
    years = range(args.years[0], args.years[1] + 1)

    logger.info("─" * 60)
    logger.info("PHASE 4 PIPELINE: assemble -> impute -> persist")
    logger.info("─" * 60)

    # Step 1: Assemble panel
    from database.assemble_panel import assemble_panel  # noqa: PLC0415
    panel, reports = assemble_panel(
        processed_dir=processed_dir,
        years=years,
    )
    logger.info("Panel assembled: %d rows, %d columns", len(panel), len(panel.columns))

    # Step 2: Fetch IPCA factors for deflation log
    from database.deflate_ipca import (  # noqa: PLC0415
        fetch_ipca_annual_index,
    )
    try:
        ipca_df = fetch_ipca_annual_index(years=list(years), base_year=2023)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Could not fetch IPCA factors for deflation log: %s", exc,
        )
        ipca_df = pd.DataFrame(columns=["year", "ipca_index", "deflation_factor"])

    # Step 3: Impute IFGF
    from database.impute_ifgf import impute_ifgf_mice  # noqa: PLC0415
    panel, imp_log = impute_ifgf_mice(panel, m=5, max_iter=10)
    logger.info("IFGF imputation: %d rows imputed", imp_log["n_imputed_rows"])

    # Step 4: Build database
    build_database(
        panel=panel,
        ipca_df=ipca_df,
        imputation_log=imp_log,
        db_path=db_path,
        processed_dir=processed_dir,
    )

    logger.info("Phase 4 pipeline complete. Database: %s", db_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
