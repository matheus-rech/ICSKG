"""
Tests for analysis.publication_tables -- publication-ready table generation
for BMJ Global Health submission.
"""

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def table_db(tmp_path: Path) -> Path:
    """Create a minimal SQLite database with dimension_scores,
    lcogs_indicators, municipality_lookup, and municipal_health tables.

    4 municipalities in 2 regions x 3 years = 12 rows.
    """
    db_path = tmp_path / "test_tables.sqlite"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    cur.executescript("""
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

        CREATE TABLE IF NOT EXISTS lcogs_indicators (
            cod_ibge                 TEXT    NOT NULL,
            year                     INTEGER NOT NULL,
            lcogs1_distance_km       REAL,
            sao_per_100k             REAL,
            surgical_volume_per_100k REAL,
            pomr                     REAL,
            financial_risk_ratio     REAL,
            catastrophic_expenditure REAL,
            PRIMARY KEY (cod_ibge, year)
        );

        CREATE TABLE IF NOT EXISTS municipality_lookup (
            cod_ibge   TEXT PRIMARY KEY,
            name       TEXT,
            uf         TEXT,
            region     TEXT
        );

        CREATE TABLE IF NOT EXISTS municipal_health (
            cod_ibge              TEXT    NOT NULL,
            year                  INTEGER NOT NULL,
            ifgf_geral            REAL,
            gdp_per_capita        REAL,
            idhm                  REAL,
            sus_dependence_rate   REAL,
            pct_sanitation_adequate REAL,
            vehicles_per_1000     REAL,
            total_beds            REAL,
            health_expenditure_per_capita REAL,
            populacao             REAL,
            PRIMARY KEY (cod_ibge, year)
        );
    """)

    # Insert municipality lookup
    cur.executemany(
        "INSERT INTO municipality_lookup VALUES (?, ?, ?, ?)",
        [
            ("1100015", "Alta Floresta D'Oeste", "RO", "Norte"),
            ("1100023", "Ariquemes", "RO", "Norte"),
            ("3550308", "Sao Paulo", "SP", "Sudeste"),
            ("3304557", "Rio de Janeiro", "RJ", "Sudeste"),
        ],
    )

    rng = np.random.default_rng(42)
    years = [2021, 2022, 2023]
    munis = ["1100015", "1100023", "3550308", "3304557"]

    for cod in munis:
        for year in years:
            dims = rng.uniform(0.1, 0.9, size=8)
            cuds = float(np.exp(np.log(dims + 0.01).mean()) - 0.01)

            cur.execute(
                "INSERT INTO dimension_scores "
                "(cod_ibge, year, D1, D2, D3, D4, D5, D6, D7, D9, cuds, n_dimensions) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (cod, year, *[float(d) for d in dims], cuds, 8),
            )

            cur.execute(
                "INSERT INTO lcogs_indicators "
                "(cod_ibge, year, lcogs1_distance_km, sao_per_100k, "
                "surgical_volume_per_100k, pomr, financial_risk_ratio, "
                "catastrophic_expenditure) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    cod, year,
                    float(rng.uniform(0, 500)),
                    float(rng.uniform(0, 50)),
                    float(rng.uniform(100, 5000)),
                    float(rng.uniform(0, 0.05)),
                    float(rng.uniform(0, 0.3)),
                    float(rng.choice([0.0, 1.0])),
                ),
            )

            # Some columns intentionally have NaN for missingness testing
            ifgf = float(rng.uniform(0.2, 0.8)) if rng.random() > 0.3 else None
            sanit = float(rng.uniform(30, 95)) if rng.random() > 0.2 else None

            cur.execute(
                "INSERT INTO municipal_health "
                "(cod_ibge, year, ifgf_geral, gdp_per_capita, idhm, "
                "sus_dependence_rate, pct_sanitation_adequate, "
                "vehicles_per_1000, total_beds, "
                "health_expenditure_per_capita, populacao) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    cod, year,
                    ifgf,
                    float(rng.uniform(10000, 80000)),
                    float(rng.uniform(0.5, 0.85)),
                    float(rng.uniform(50, 95)),
                    sanit,
                    float(rng.uniform(50, 600)),
                    float(rng.uniform(10, 500)),
                    float(rng.uniform(200, 2000)),
                    float(rng.uniform(5000, 12000000)),
                ),
            )

    conn.commit()
    conn.close()
    return db_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_descriptive_table_has_ci_columns(table_db: Path, tmp_path: Path):
    """Verify Table 1 descriptive stats contain CI columns."""
    from analysis.publication_tables import generate_descriptive_table

    out_dir = tmp_path / "results"

    # Mock the exchange rate to avoid network call
    with patch(
        "database.deflate_ipca.fetch_bcb_exchange_rate", return_value=4.9942,
    ):
        result = generate_descriptive_table(table_db, out_dir)

    assert result.exists(), "table1_descriptive_stats.csv was not created"

    df = pd.read_csv(result)
    assert len(df) > 0, "Table 1 is empty"

    # Check that CI columns exist for cuds
    ci_cols = [c for c in df.columns if "ci_lower" in c or "ci_upper" in c]
    assert len(ci_cols) > 0, "No CI columns found in Table 1"


def test_missingness_table_has_all_years(table_db: Path, tmp_path: Path):
    """Verify Table 3 missingness has columns for 2021-2023."""
    from analysis.publication_tables import generate_missingness_table

    out_dir = tmp_path / "results"
    result = generate_missingness_table(table_db, out_dir)

    assert result.exists(), "table3_missingness.csv was not created"

    df = pd.read_csv(result)
    assert len(df) > 0, "Table 3 is empty"

    # Check year columns exist (as integers in pivot)
    year_cols = [c for c in df.columns if str(c).isdigit()]
    expected_years = {"2021", "2022", "2023"}
    assert expected_years.issubset(set(year_cols)), (
        "Missing year columns: %s (found: %s)" % (expected_years, year_cols)
    )


def test_correlation_matrix_shape(table_db: Path, tmp_path: Path):
    """Verify Table 4 correlation matrix is square."""
    from analysis.publication_tables import generate_correlation_matrix

    out_dir = tmp_path / "results"
    result = generate_correlation_matrix(table_db, out_dir)

    assert result.exists(), "table4_correlation_matrix.csv was not created"

    df = pd.read_csv(result, index_col=0)
    assert df.shape[0] == df.shape[1], (
        "Correlation matrix is not square: %s" % (df.shape,)
    )
    assert df.shape[0] > 0, "Correlation matrix is empty"


def test_generate_all_tables_returns_paths(table_db: Path, tmp_path: Path):
    """Verify orchestrator returns list of paths."""
    from analysis import publication_tables

    out_dir = tmp_path / "results"

    mock_desc = MagicMock(return_value=out_dir / "tables" / "t1.csv")
    mock_dims = MagicMock(return_value=out_dir / "tables" / "t2.csv")
    mock_miss = MagicMock(return_value=out_dir / "tables" / "t3.csv")
    mock_corr = MagicMock(return_value=out_dir / "tables" / "t4.csv")
    mock_reg = MagicMock(return_value=[
        out_dir / "tables" / "t5.csv",
        out_dir / "tables" / "t6.csv",
    ])
    mock_sens = MagicMock(return_value=[out_dir / "tables" / "s1.csv"])

    with patch.object(publication_tables, "generate_descriptive_table", mock_desc), \
         patch.object(publication_tables, "generate_dimension_descriptives", mock_dims), \
         patch.object(publication_tables, "generate_missingness_table", mock_miss), \
         patch.object(publication_tables, "generate_correlation_matrix", mock_corr), \
         patch.object(publication_tables, "generate_regression_tables", mock_reg), \
         patch.object(publication_tables, "generate_sensitivity_tables", mock_sens):
        result = publication_tables.generate_all_tables(table_db, out_dir)

    assert isinstance(result, list)
    assert len(result) == 7  # 4 singles + 2 reg + 1 sens
    mock_desc.assert_called_once()
    mock_dims.assert_called_once()
    mock_miss.assert_called_once()
    mock_corr.assert_called_once()
    mock_reg.assert_called_once()
    mock_sens.assert_called_once()
