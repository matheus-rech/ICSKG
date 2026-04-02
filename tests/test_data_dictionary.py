"""Tests for data dictionary generator and schema validation."""

import sqlite3
from pathlib import Path

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_db(tmp_path: Path) -> Path:
    """Create a mock SQLite database with 3 tables for testing."""
    db_path = tmp_path / "test.sqlite"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    # Table 1: municipal_health (with some NULLs)
    cur.execute("""
        CREATE TABLE municipal_health (
            cod_ibge TEXT NOT NULL,
            year     INTEGER NOT NULL,
            gdp_per_capita REAL,
            populacao INTEGER,
            PRIMARY KEY (cod_ibge, year)
        )
    """)
    cur.executemany(
        "INSERT INTO municipal_health VALUES (?, ?, ?, ?)",
        [
            ("1100015", 2020, 25000.0, 100000),
            ("1100023", 2020, None, 200000),
            ("1100031", 2020, 30000.0, None),
        ],
    )

    # Table 2: dimension_scores
    cur.execute("""
        CREATE TABLE dimension_scores (
            cod_ibge TEXT NOT NULL,
            year     INTEGER NOT NULL,
            D1       REAL,
            cuds     REAL,
            PRIMARY KEY (cod_ibge, year)
        )
    """)
    cur.executemany(
        "INSERT INTO dimension_scores VALUES (?, ?, ?, ?)",
        [
            ("1100015", 2020, 0.5, 0.6),
            ("1100023", 2020, None, 0.4),
        ],
    )

    # Table 3: municipality_lookup
    cur.execute("""
        CREATE TABLE municipality_lookup (
            cod_ibge TEXT PRIMARY KEY,
            name     TEXT,
            state_uf TEXT,
            region   TEXT
        )
    """)
    cur.executemany(
        "INSERT INTO municipality_lookup VALUES (?, ?, ?, ?)",
        [
            ("1100015", "Alta Floresta d'Oeste", "RO", "Norte"),
            ("1100023", "Ariquemes", "RO", "Norte"),
        ],
    )

    conn.commit()
    conn.close()
    return db_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_dictionary_covers_all_tables(mock_db: Path, tmp_path: Path) -> None:
    """Data dictionary must include entries for every table in the database."""
    from analysis.data_dictionary import generate_data_dictionary

    csv_path = generate_data_dictionary(mock_db, tmp_path)
    df = pd.read_csv(csv_path)

    tables_in_dict = set(df["table"].unique())
    expected_tables = {"municipal_health", "dimension_scores", "municipality_lookup"}

    assert expected_tables.issubset(tables_in_dict), (
        "Missing tables in dictionary: %s"
        % (expected_tables - tables_in_dict)
    )


def test_dictionary_has_required_columns(mock_db: Path, tmp_path: Path) -> None:
    """Data dictionary output must have required metadata columns."""
    from analysis.data_dictionary import generate_data_dictionary

    csv_path = generate_data_dictionary(mock_db, tmp_path)
    df = pd.read_csv(csv_path)

    required_cols = [
        "table", "column_name", "sqlite_type",
        "source", "definition", "unit",
    ]
    for col in required_cols:
        assert col in df.columns, "Missing required column: %s" % col


def test_missingness_computation(mock_db: Path, tmp_path: Path) -> None:
    """Missingness rate must be computed correctly from actual data."""
    from analysis.data_dictionary import generate_data_dictionary

    csv_path = generate_data_dictionary(mock_db, tmp_path)
    df = pd.read_csv(csv_path)

    # municipal_health.gdp_per_capita has 1/3 NULL = 33.33%
    gdp_row = df[
        (df["table"] == "municipal_health")
        & (df["column_name"] == "gdp_per_capita")
    ]
    assert len(gdp_row) == 1
    pct_missing = gdp_row.iloc[0]["missingness_rate"]
    assert abs(pct_missing - 33.33) < 0.1, (
        "Expected ~33.33%% missingness, got %.2f%%" % pct_missing
    )

    # dimension_scores.D1 has 1/2 NULL = 50%
    d1_row = df[
        (df["table"] == "dimension_scores")
        & (df["column_name"] == "D1")
    ]
    assert len(d1_row) == 1
    pct_d1 = d1_row.iloc[0]["missingness_rate"]
    assert abs(pct_d1 - 50.0) < 0.1, (
        "Expected ~50%% missingness for D1, got %.2f%%" % pct_d1
    )


def test_validation_detects_missing_column(
    mock_db: Path,
    tmp_path: Path,
) -> None:
    """Validation must report valid=False when dictionary is incomplete."""
    from analysis.data_dictionary import (
        generate_data_dictionary,
        validate_dictionary_against_schema,
    )

    csv_path = generate_data_dictionary(mock_db, tmp_path)

    # Remove one row to simulate incomplete dictionary
    df = pd.read_csv(csv_path)
    df = df[~(
        (df["table"] == "municipal_health")
        & (df["column_name"] == "populacao")
    )]
    incomplete_path = tmp_path / "incomplete_dict.csv"
    df.to_csv(incomplete_path, index=False)

    result = validate_dictionary_against_schema(mock_db, incomplete_path)

    assert result["valid"] is False, "Validation should fail for incomplete dictionary"
    assert len(result["missing_from_dict"]) > 0, "Should report missing columns"

    # Check that the specific missing column is identified
    missing_pairs = result["missing_from_dict"]
    assert ("municipal_health", "populacao") in missing_pairs


def test_validation_passes_for_complete_dict(
    mock_db: Path,
    tmp_path: Path,
) -> None:
    """Validation must return valid=True for a complete dictionary."""
    from analysis.data_dictionary import (
        generate_data_dictionary,
        validate_dictionary_against_schema,
    )

    csv_path = generate_data_dictionary(mock_db, tmp_path)
    result = validate_dictionary_against_schema(mock_db, csv_path)

    assert result["valid"] is True, "Validation should pass for complete dictionary"
    assert result["tables_checked"] == 3
