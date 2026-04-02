"""
ICSKG-BR Database Builder v3 — CIMI-aligned Schema
====================================================
Assembles the final ICSKG-BR relational database from the validated,
deflated, imputed municipality-year panel produced by assemble_panel.py
and impute_ifgf.py.

Schema (v3) aligns with the CIMI 9-dimension framework (excluding D8
International Projection). Tables:
  - municipal_health      : (cod_ibge, year) PK, all source value columns
  - dimension_metadata    : CIMI dimension definitions with cross-sectional flags
  - municipality_lookup   : IBGE reference with region and population
  - deflation_log         : IPCA deflation factors per year (audit trail)
  - imputation_log        : IFGF imputation details per variable per year

Outputs
-------
  database/icskg_br.sqlite   — SQLite portable database

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
# Schema DDL (SQLite-compatible, v3 CIMI-aligned)
# ---------------------------------------------------------------------------

DDL_MUNICIPAL_HEALTH = """
CREATE TABLE IF NOT EXISTS municipal_health (
    cod_ibge         TEXT    NOT NULL,
    year             INTEGER NOT NULL,
    ifgf_geral       REAL,
    ifgf_ra          REAL,
    ifgf_gp          REAL,
    ifgf_id          REAL,
    ifgf_el          REAL,
    ifgf_sa          REAL,
    ifgf_is_imputed  INTEGER DEFAULT 0,
    gdp_per_capita   REAL,
    gdp_per_capita_nominal REAL,
    gdp_abs          REAL,
    gdp_estimated    INTEGER,
    idhm             REAL,
    idhm_educacao    REAL,
    idhm_longevidade REAL,
    idhm_renda       REAL,
    private_coverage_rate    REAL,
    sus_dependence_rate      REAL,
    beneficiarios_mean       REAL,
    pct_sanitation_adequate  REAL,
    pct_water_adequate       REAL,
    vehicles_total           REAL,
    vehicles_per_1000        REAL,
    total_beds               REAL,
    is_bellwether            INTEGER,
    health_expenditure_per_capita          REAL,
    health_expenditure_per_capita_nominal  REAL,
    procedure_count          INTEGER,
    total_value              REAL,
    total_value_nominal      REAL,
    deaths                   INTEGER,
    aih_count                INTEGER,
    total_days               INTEGER,
    populacao                INTEGER,
    sao_category             TEXT,
    created_at       TEXT DEFAULT (datetime('now')),
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
    year             INTEGER PRIMARY KEY,
    ipca_index_dec   REAL,
    deflation_factor REAL,
    base_year        INTEGER DEFAULT 2023
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

ALL_DDL = [
    DDL_MUNICIPAL_HEALTH,
    DDL_DIMENSION_METADATA,
    DDL_MUNICIPALITY_LOOKUP,
    DDL_DEFLATION_LOG,
    DDL_IMPUTATION_LOG,
]


# ---------------------------------------------------------------------------
# CIMI Dimensions (8 active, D8 excluded)
# ---------------------------------------------------------------------------

CIMI_DIMENSIONS: list[dict] = [
    {
        "key": "D1",
        "label": "Governance",
        "source": "FIRJAN/IFGF",
        "weight": 1.0,
        "description": "IFGF fiscal management composite (5 sub-indices)",
        "is_crosssectional": 0,
        "crosssectional_year": None,
    },
    {
        "key": "D2",
        "label": "Economy",
        "source": "IBGE SIDRA",
        "weight": 1.0,
        "description": "GDP per capita (deflated to 2023 BRL)",
        "is_crosssectional": 0,
        "crosssectional_year": None,
    },
    {
        "key": "D3",
        "label": "Human Capital",
        "source": "IPEA/IDHM",
        "weight": 1.0,
        "description": "IDHM composite (education + longevity + income)",
        "is_crosssectional": 1,
        "crosssectional_year": 2010,
    },
    {
        "key": "D4",
        "label": "Social Cohesion",
        "source": "ANS/IBGE",
        "weight": 1.0,
        "description": "SUS dependence rate (100 - ANS private coverage %)",
        "is_crosssectional": 0,
        "crosssectional_year": None,
    },
    {
        "key": "D5",
        "label": "Environment",
        "source": "IBGE Census 2022",
        "weight": 1.0,
        "description": "Adequate sanitation % (esgotamento sanitario + abastecimento)",
        "is_crosssectional": 1,
        "crosssectional_year": 2022,
    },
    {
        "key": "D6",
        "label": "Mobility",
        "source": "RENAVAM/DENATRAN",
        "weight": 1.0,
        "description": "Vehicles per 1,000 inhabitants",
        "is_crosssectional": 0,
        "crosssectional_year": None,
    },
    {
        "key": "D7",
        "label": "Urban Planning",
        "source": "CNES/DATASUS",
        "weight": 1.0,
        "description": "Hospital beds per 10,000 inhabitants",
        "is_crosssectional": 0,
        "crosssectional_year": None,
    },
    {
        "key": "D9",
        "label": "Technology",
        "source": "SIOPS/IBGE",
        "weight": 1.0,
        "description": "Per-capita health expenditure as technology proxy",
        "is_crosssectional": 0,
        "crosssectional_year": None,
    },
]


# ---------------------------------------------------------------------------
# UF-to-region mapping
# ---------------------------------------------------------------------------

UF_TO_REGION: dict[str, str] = {
    "AC": "Norte", "AP": "Norte", "AM": "Norte", "PA": "Norte",
    "RO": "Norte", "RR": "Norte", "TO": "Norte",
    "AL": "Nordeste", "BA": "Nordeste", "CE": "Nordeste", "MA": "Nordeste",
    "PB": "Nordeste", "PE": "Nordeste", "PI": "Nordeste", "RN": "Nordeste",
    "SE": "Nordeste",
    "DF": "Centro-Oeste", "GO": "Centro-Oeste", "MT": "Centro-Oeste",
    "MS": "Centro-Oeste",
    "ES": "Sudeste", "MG": "Sudeste", "RJ": "Sudeste", "SP": "Sudeste",
    "PR": "Sul", "RS": "Sul", "SC": "Sul",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_schema(conn: sqlite3.Connection) -> None:
    """Create all v3 schema tables (IF NOT EXISTS).

    Parameters
    ----------
    conn : sqlite3.Connection
        Open SQLite connection.
    """
    cur = conn.cursor()
    for ddl in ALL_DDL:
        cur.executescript(ddl)
    conn.commit()
    logger.info("Schema v3 created (5 tables)")


def seed_dimension_metadata(conn: sqlite3.Connection) -> None:
    """Seed dimension_metadata with 8 active CIMI dimensions.

    D8 (International Projection) is excluded per project decision.
    D3 (Human Capital/IDHM) is marked cross-sectional 2010.
    D5 (Environment/Census) is marked cross-sectional 2022.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open SQLite connection with schema already created.
    """
    cur = conn.cursor()
    cur.executemany(
        "INSERT OR REPLACE INTO dimension_metadata "
        "(key, label, source, weight, description, is_crosssectional, crosssectional_year) "
        "VALUES (:key, :label, :source, :weight, :description, "
        ":is_crosssectional, :crosssectional_year)",
        CIMI_DIMENSIONS,
    )
    conn.commit()
    logger.info("Seeded %d CIMI dimension-metadata rows", len(CIMI_DIMENSIONS))


def seed_municipality_lookup(conn: sqlite3.Connection) -> None:
    """Populate municipality_lookup from IBGE 2023 reference.

    Derives region from UF using standard Brazilian macro-region mapping.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open SQLite connection with schema already created.
    """
    from database.utils import load_ibge_municipios  # noqa: PLC0415

    ref = load_ibge_municipios()
    ref = ref.copy()
    ref["region"] = ref["uf"].map(UF_TO_REGION)

    cur = conn.cursor()
    for _, row in ref.iterrows():
        cur.execute(
            "INSERT OR REPLACE INTO municipality_lookup "
            "(cod_ibge, name, state_uf, region) VALUES (?, ?, ?, ?)",
            (
                str(row["cod_ibge"]),
                str(row.get("nome_municipio", "")),
                str(row.get("uf", "")),
                str(row.get("region", "")),
            ),
        )
    conn.commit()
    logger.info("Seeded %d municipality_lookup rows", len(ref))


def seed_deflation_log(
    conn: sqlite3.Connection,
    ipca_df: pd.DataFrame,
) -> None:
    """Populate deflation_log from IPCA factors DataFrame.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open SQLite connection with schema already created.
    ipca_df : pd.DataFrame
        Must have columns: year, ipca_index, deflation_factor.
    """
    cur = conn.cursor()
    for _, row in ipca_df.iterrows():
        cur.execute(
            "INSERT OR REPLACE INTO deflation_log "
            "(year, ipca_index_dec, deflation_factor, base_year) "
            "VALUES (?, ?, ?, ?)",
            (
                int(row["year"]),
                float(row["ipca_index"]),
                float(row["deflation_factor"]),
                2023,
            ),
        )
    conn.commit()
    logger.info("Seeded deflation_log with %d years", len(ipca_df))


def seed_imputation_log(
    conn: sqlite3.Connection,
    imputation_log: dict,
) -> None:
    """Populate imputation_log from the IFGF imputation results.

    Creates one row per (variable, year) combination.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open SQLite connection with schema already created.
    imputation_log : dict
        Output from impute_ifgf_mice(). Must have keys:
        m, max_iter, method, n_imputed_rows, ifgf_cols, aux_cols, per_year.
    """
    if imputation_log.get("n_imputed_rows", 0) == 0:
        logger.info("No imputed rows -- skipping imputation_log seeding")
        return

    cur = conn.cursor()
    ifgf_cols = imputation_log.get("ifgf_cols", [])
    per_year = imputation_log.get("per_year", {})
    method = imputation_log.get("method", "unknown")
    m = imputation_log.get("m", 5)
    max_iter = imputation_log.get("max_iter", 10)
    aux_vars = ",".join(imputation_log.get("aux_cols", []))

    count = 0
    for year, n_imputed in per_year.items():
        for col in ifgf_cols:
            cur.execute(
                "INSERT OR REPLACE INTO imputation_log "
                "(variable, year, n_imputed, n_total, method, "
                "m_imputations, max_iter, aux_variables) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (col, int(year), n_imputed, None, method, m, max_iter, aux_vars),
            )
            count += 1

    conn.commit()
    logger.info("Seeded imputation_log with %d entries", count)


def load_panel(
    conn: sqlite3.Connection,
    panel: pd.DataFrame,
) -> int:
    """Load the panel DataFrame into the municipal_health table.

    Uses df.to_sql with if_exists='replace' for idempotent batch insert.
    NOT iterrows() — batch insert per research anti-pattern guidance.

    Parameters
    ----------
    conn : sqlite3.Connection
        Open SQLite connection with schema already created.
    panel : pd.DataFrame
        Validated, deflated, imputed panel.

    Returns
    -------
    int
        Number of rows inserted.
    """
    # Drop the auto-generated created_at — let SQLite default handle it
    panel = panel.copy()

    # Ensure cod_ibge is string
    panel["cod_ibge"] = panel["cod_ibge"].astype(str)
    panel["year"] = panel["year"].astype(int)

    # Use to_sql with replace for idempotent loading
    panel.to_sql("municipal_health", conn, if_exists="replace", index=False)

    # Re-create the PRIMARY KEY constraint after replace
    # (to_sql with replace drops the table and recreates without constraints)
    # We need to add it back via a temp table approach
    _ensure_primary_key(conn)

    n_rows = conn.execute("SELECT COUNT(*) FROM municipal_health").fetchone()[0]
    logger.info("Loaded %d rows into municipal_health", n_rows)
    return n_rows


def build_database(
    panel: pd.DataFrame,
    ipca_df: pd.DataFrame,
    imputation_log: dict,
    db_path: Path | str,
    processed_dir: Path | str | None = None,
) -> Path:
    """Orchestrate the full database build.

    Sequence: create_schema -> seed_dimension_metadata ->
    seed_municipality_lookup -> seed_deflation_log ->
    seed_imputation_log -> load_panel -> generate_missingness_report.

    Parameters
    ----------
    panel : pd.DataFrame
        Validated, deflated, imputed panel.
    ipca_df : pd.DataFrame
        IPCA factors with columns: year, ipca_index, deflation_factor.
    imputation_log : dict
        Output from impute_ifgf_mice().
    db_path : Path or str
        SQLite database output path.
    processed_dir : Path or str, optional
        Directory for PANL-06-missingness.csv output.

    Returns
    -------
    Path
        Path to the created SQLite database.
    """
    from database.impute_ifgf import generate_missingness_report  # noqa: PLC0415

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info("─" * 60)
    logger.info("DATABASE BUILD v3: %s", db_path)
    logger.info("─" * 60)

    conn = sqlite3.connect(str(db_path))

    try:
        create_schema(conn)
        seed_dimension_metadata(conn)
        seed_municipality_lookup(conn)
        seed_deflation_log(conn, ipca_df)
        seed_imputation_log(conn, imputation_log)
        n = load_panel(conn, panel)

        # Log table sizes
        for table in ["municipal_health", "dimension_metadata",
                      "municipality_lookup", "deflation_log", "imputation_log"]:
            count = conn.execute(
                "SELECT COUNT(*) FROM %s" % table
            ).fetchone()[0]
            logger.info("  %s: %d rows", table, count)

    finally:
        conn.close()

    # Generate missingness report
    if processed_dir is not None:
        processed_dir = Path(processed_dir)
        processed_dir.mkdir(parents=True, exist_ok=True)
        missingness_path = processed_dir / "PANL-06-missingness.csv"
        generate_missingness_report(panel, missingness_path)

    logger.info("Database build complete: %d rows in municipal_health", n)
    return db_path


def main(argv=None) -> int:
    """CLI entry point: assemble -> impute -> persist.

    End-to-end Phase 4 orchestrator.

    Usage
    -----
        python database/build_database_v3.py --processed-dir data_sources/processed \\
                                              --db-dir database \\
                                              --years 2015 2023
    """
    parser = argparse.ArgumentParser(
        description="ICSKG-BR database builder v3 (CIMI-aligned)"
    )
    parser.add_argument(
        "--processed-dir",
        default="data_sources/processed",
        help="Root of processed Parquet files",
    )
    parser.add_argument(
        "--db-dir",
        default="database",
        help="Output directory for SQLite database",
    )
    parser.add_argument(
        "--years",
        nargs=2,
        type=int,
        default=[2015, 2023],
        metavar=("START", "END"),
        help="Year range (inclusive start, exclusive end for range())",
    )
    args = parser.parse_args(argv)

    processed_dir = Path(args.processed_dir)
    db_dir = Path(args.db_dir)
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "icskg_br.sqlite"

    years = range(args.years[0], args.years[1] + 1)

    # ------------------------------------------------------------------
    # Step 1: Assemble panel
    # ------------------------------------------------------------------
    from database.assemble_panel import assemble_panel  # noqa: PLC0415
    from database.deflate_ipca import fetch_ipca_annual_index  # noqa: PLC0415
    from database.impute_ifgf import impute_ifgf_mice  # noqa: PLC0415

    logger.info("=== Phase 4 Pipeline: Assemble -> Impute -> Persist ===")

    panel, reports = assemble_panel(
        processed_dir=processed_dir,
        years=years,
    )

    # ------------------------------------------------------------------
    # Step 2: Impute IFGF
    # ------------------------------------------------------------------
    panel, imputation_log = impute_ifgf_mice(panel, m=5, max_iter=10)

    # ------------------------------------------------------------------
    # Step 3: Fetch IPCA for deflation log
    # ------------------------------------------------------------------
    try:
        ipca_df = fetch_ipca_annual_index(years=list(years), base_year=2023)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not fetch IPCA for deflation_log: %s", exc)
        ipca_df = pd.DataFrame(columns=["year", "ipca_index", "deflation_factor"])

    # ------------------------------------------------------------------
    # Step 4: Build database
    # ------------------------------------------------------------------
    build_database(
        panel=panel,
        ipca_df=ipca_df,
        imputation_log=imputation_log,
        db_path=db_path,
        processed_dir=processed_dir,
    )

    logger.info("=== Phase 4 Pipeline Complete ===")
    return 0


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _ensure_primary_key(conn: sqlite3.Connection) -> None:
    """Re-create PRIMARY KEY on municipal_health after to_sql replace.

    to_sql(if_exists='replace') drops the table and recreates without
    constraints. This function rebuilds the table with the PK.
    """
    cur = conn.cursor()

    # Check if PK already exists by trying to get table info
    try:
        # Get existing columns
        col_info = cur.execute("PRAGMA table_info(municipal_health)").fetchall()
        col_names = [c[1] for c in col_info]

        # Check if PK constraint exists (pk column > 0)
        has_pk = any(c[5] > 0 for c in col_info)
        if has_pk:
            return  # PK already exists

        # Rebuild with PK constraint
        cols_def = ", ".join(col_names)

        cur.execute("ALTER TABLE municipal_health RENAME TO _mh_temp")
        cur.execute(DDL_MUNICIPAL_HEALTH)

        # Copy data back, selecting only columns that exist in both
        existing_in_ddl = [c[1] for c in cur.execute(
            "PRAGMA table_info(municipal_health)"
        ).fetchall()]
        common_cols = [c for c in col_names if c in existing_in_ddl]
        common_str = ", ".join(common_cols)

        cur.execute(
            "INSERT OR REPLACE INTO municipal_health (%s) "
            "SELECT %s FROM _mh_temp" % (common_str, common_str)
        )
        cur.execute("DROP TABLE _mh_temp")
        conn.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not ensure PK on municipal_health: %s", exc)
        conn.rollback()


if __name__ == "__main__":
    sys.exit(main())
