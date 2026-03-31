"""
ICSKG-BR Database Builder v2
==============================
Assembles the final ICSKG-BR relational database from the processed
municipality-level parquet files produced by the extraction pipeline.

Outputs
-------
  database/icskg_br.duckdb   – DuckDB analytical database
  database/icskg_br.sqlite   – SQLite portable copy

Schema (main tables)
---------------------
  municipal_health     – longitudinal panel of all CIMI indicators
  dimension_metadata   – label / source / weight for each CIMI dimension
  municipality_lookup  – IBGE codes, names, state, region, population

Usage
-----
    python database/build_database_v2.py [--processed-dir data_sources/processed]
                                         [--db-dir database]
                                         [--years 2013 2024]
"""

import argparse
import json
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
# Schema DDL (SQLite-compatible)
# ---------------------------------------------------------------------------

DDL_MUNICIPAL_HEALTH = """
CREATE TABLE IF NOT EXISTS municipal_health (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    cod_ibge         TEXT    NOT NULL,
    year             INTEGER NOT NULL,
    month            INTEGER,
    D1_fiscal_governance      REAL,
    D2_health_expenditure     REAL,
    D3_hospital_capacity      REAL,
    D4_human_resources        REAL,
    D5_primary_care_coverage  REAL,
    D6_private_coverage       REAL,
    D7_maternal_child_health  REAL,
    D8_chronic_disease_burden REAL,
    D9_health_knowledge_gap   REAL,
    ICSKG_score               REAL,
    created_at       TEXT DEFAULT (datetime('now')),
    UNIQUE (cod_ibge, year, month)
);
"""

DDL_DIMENSION_METADATA = """
CREATE TABLE IF NOT EXISTS dimension_metadata (
    key          TEXT PRIMARY KEY,
    label        TEXT NOT NULL,
    source       TEXT,
    weight       REAL DEFAULT 1.0,
    description  TEXT
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

DIMENSION_METADATA_ROWS = [
    ("D1_fiscal_governance",      "Fiscal Governance (IFGF)",                "FIRJAN/IFGF",     1.0, "Average of IFGF sub-indices: revenue, expenditure, investment, liquidity"),
    ("D2_health_expenditure",     "Per-capita health expenditure",           "SIOPS/IBGE",      1.0, "Municipal health expenditure per inhabitant (BRL, deflated)"),
    ("D3_hospital_capacity",      "Inpatient beds per 10 000",               "CNES/DATASUS",    1.0, "SUS and non-SUS inpatient beds per 10 000 inhabitants"),
    ("D4_human_resources",        "Physicians and nurses per 10 000",        "CNES/DATASUS",    1.0, "Active physicians + nurses per 10 000 inhabitants"),
    ("D5_primary_care_coverage",  "Primary-care coverage index",             "PMAQ/Previne",    1.0, "Coverage score from national primary-care evaluation programmes"),
    ("D6_private_coverage",       "ANS private-coverage share",              "ANS/IBGE",        1.0, "Share of municipal population with supplementary health plan"),
    ("D7_maternal_child_health",  "Maternal-child health composite",         "SIM/SINASC",      1.0, "Composite of infant mortality rate and prenatal care coverage"),
    ("D8_chronic_disease_burden", "ICSAP hospitalisation rate",              "SIH/DATASUS",     1.0, "Rate of hospitalisations for ambulatory-care-sensitive conditions"),
    ("D9_health_knowledge_gap",   "ICSKG composite knowledge-gap score",     "Multi-source",    1.0, "Composite gap score across knowledge, access, and quality domains"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _connect_sqlite(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(db_path))


def _init_schema(con: sqlite3.Connection) -> None:
    cur = con.cursor()
    cur.executescript(DDL_MUNICIPAL_HEALTH + DDL_DIMENSION_METADATA + DDL_MUNICIPALITY_LOOKUP)
    con.commit()
    logger.info("Schema initialised.")


def _seed_dimension_metadata(con: sqlite3.Connection) -> None:
    cur = con.cursor()
    cur.executemany(
        "INSERT OR REPLACE INTO dimension_metadata (key, label, source, weight, description) "
        "VALUES (?, ?, ?, ?, ?)",
        DIMENSION_METADATA_ROWS,
    )
    con.commit()
    logger.info("Seeded %d dimension-metadata rows.", len(DIMENSION_METADATA_ROWS))


# ---------------------------------------------------------------------------
# Load processed parquet files
# ---------------------------------------------------------------------------

def collect_parquet_files(processed_dir: Path, years: tuple[int, int]) -> list[Path]:
    """Return all parquet files in *processed_dir* within the year range."""
    files = sorted(processed_dir.glob("merged_*.parquet"))
    filtered = []
    for f in files:
        # filename pattern: merged_YYYYMM.parquet
        try:
            year = int(f.stem.split("_")[1][:4])
        except (IndexError, ValueError):
            continue
        if years[0] <= year <= years[1]:
            filtered.append(f)
    logger.info("Found %d parquet files in %s for years %d–%d", len(filtered), processed_dir, *years)
    return filtered


def load_parquet_to_df(files: list[Path]) -> pd.DataFrame:
    """Concatenate parquet files into a single DataFrame."""
    if not files:
        logger.warning("No parquet files to load – returning empty DataFrame.")
        return pd.DataFrame()
    frames = []
    for f in files:
        try:
            frames.append(pd.read_parquet(f))
        except Exception as exc:  # noqa: BLE001
            logger.error("Could not read %s: %s", f, exc)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def upsert_municipal_health(con: sqlite3.Connection, df: pd.DataFrame) -> int:
    """Insert or replace rows into the municipal_health table."""
    if df.empty:
        return 0

    dim_cols = [
        "D1_fiscal_governance", "D2_health_expenditure", "D3_hospital_capacity",
        "D4_human_resources", "D5_primary_care_coverage", "D6_private_coverage",
        "D7_maternal_child_health", "D8_chronic_disease_burden", "D9_health_knowledge_gap",
        "ICSKG_score",
    ]
    required = ["cod_ibge", "year"]
    for col in required:
        if col not in df.columns:
            logger.error("Required column '%s' missing from DataFrame.", col)
            return 0

    # Fill missing dimension columns with NULL
    for col in dim_cols:
        if col not in df.columns:
            df[col] = None

    month_col = df["month"] if "month" in df.columns else None

    rows = []
    for _, row in df.iterrows():
        rows.append((
            str(row["cod_ibge"]),
            int(row["year"]),
            int(row["month"]) if month_col is not None and not pd.isna(row.get("month")) else None,
            *(float(row[c]) if c in row and not pd.isna(row[c]) else None for c in dim_cols),
        ))

    cur = con.cursor()
    cur.executemany(
        "INSERT OR REPLACE INTO municipal_health "
        "(cod_ibge, year, month, "
        "D1_fiscal_governance, D2_health_expenditure, D3_hospital_capacity, "
        "D4_human_resources, D5_primary_care_coverage, D6_private_coverage, "
        "D7_maternal_child_health, D8_chronic_disease_burden, D9_health_knowledge_gap, "
        "ICSKG_score) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    con.commit()
    logger.info("Upserted %d rows into municipal_health.", len(rows))
    return len(rows)


# ---------------------------------------------------------------------------
# DuckDB mirror (optional)
# ---------------------------------------------------------------------------

def _mirror_to_duckdb(sqlite_path: Path, duckdb_path: Path) -> None:
    """Copy the SQLite database into a DuckDB file for analytical queries."""
    try:
        import duckdb
    except ImportError:
        logger.warning("duckdb not installed – skipping DuckDB mirror.")
        return

    con = duckdb.connect(str(duckdb_path))
    con.execute("INSTALL sqlite")
    con.execute("LOAD sqlite")
    con.execute(f"CALL sqlite_attach('{sqlite_path}');")
    for tbl in ("municipal_health", "dimension_metadata", "municipality_lookup"):
        con.execute(f"CREATE OR REPLACE TABLE {tbl} AS SELECT * FROM {tbl};")
    con.close()
    logger.info("DuckDB mirror written to %s", duckdb_path)


# ---------------------------------------------------------------------------
# Export metadata JSON
# ---------------------------------------------------------------------------

def export_metadata_json(db_dir: Path) -> None:
    """Re-export dimension metadata to database_metadata.json."""
    meta = {
        "dimensions": [
            {
                "key": row[0],
                "label": row[1],
                "source": row[2],
                "weight": row[3],
                "description": row[4],
            }
            for row in DIMENSION_METADATA_ROWS
        ],
        "n_dimensions": len(DIMENSION_METADATA_ROWS),
        "year_range": [2013, 2024],
    }
    path = db_dir / "database_metadata.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    logger.info("database_metadata.json written to %s", path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description="ICSKG-BR database builder v2")
    parser.add_argument("--processed-dir", default="data_sources/processed")
    parser.add_argument("--db-dir", default="database")
    parser.add_argument("--years", nargs=2, type=int, default=[2013, 2024], metavar=("START", "END"))
    args = parser.parse_args(argv)

    processed_dir = Path(args.processed_dir)
    db_dir = Path(args.db_dir)
    db_dir.mkdir(parents=True, exist_ok=True)

    sqlite_path = db_dir / "icskg_br.sqlite"
    duckdb_path = db_dir / "icskg_br.duckdb"

    con = _connect_sqlite(sqlite_path)
    _init_schema(con)
    _seed_dimension_metadata(con)

    files = collect_parquet_files(processed_dir, tuple(args.years))
    if files:
        df = load_parquet_to_df(files)
        n = upsert_municipal_health(con, df)
        logger.info("Total rows loaded: %d", n)
    else:
        logger.info("No processed files found – database schema and metadata seeded only.")

    con.close()
    _mirror_to_duckdb(sqlite_path, duckdb_path)
    export_metadata_json(db_dir)

    logger.info("Database build complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
