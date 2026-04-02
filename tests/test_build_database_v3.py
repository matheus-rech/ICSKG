"""
Tests for database.build_database_v3 — CIMI-aligned SQLite builder (v3 schema).
"""

import sqlite3

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mem_conn() -> sqlite3.Connection:
    """In-memory SQLite connection for fast tests."""
    return sqlite3.connect(":memory:")


@pytest.fixture()
def synthetic_panel() -> pd.DataFrame:
    """Synthetic 100-row panel for load tests."""
    rng = np.random.default_rng(42)
    n = 100
    return pd.DataFrame({
        "cod_ibge": [f"{3500000 + i:07d}" for i in range(n)],
        "year": [2020] * 50 + [2021] * 50,
        "ifgf_geral": rng.uniform(0.2, 0.8, n),
        "gdp_per_capita": rng.uniform(10000, 80000, n),
        "idhm": rng.uniform(0.5, 0.9, n),
        "private_coverage_rate": rng.uniform(0.05, 0.5, n),
        "pct_sanitation_adequate": rng.uniform(0.3, 0.95, n),
        "vehicles_per_1000": rng.uniform(50, 500, n),
        "total_beds": rng.integers(10, 500, n).astype(float),
        "populacao": rng.integers(5000, 500000, n).astype(float),
        "ifgf_is_imputed": rng.choice([0, 1], n, p=[0.8, 0.2]),
    })


@pytest.fixture()
def ipca_df() -> pd.DataFrame:
    """Synthetic IPCA deflation factors."""
    return pd.DataFrame({
        "year": [2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023],
        "ipca_index": [100.0, 106.3, 109.5, 113.2, 117.8, 122.4, 132.1, 139.7, 146.0],
        "deflation_factor": [1.46, 1.373, 1.333, 1.290, 1.239, 1.193, 1.105, 1.045, 1.0],
    })


@pytest.fixture()
def imputation_log() -> dict:
    """Synthetic imputation log from impute_ifgf_mice."""
    return {
        "m": 5,
        "max_iter": 10,
        "method": "IterativeImputer(BayesianRidge, sample_posterior=True)",
        "n_imputed_rows": 420,
        "ifgf_cols": [
            "ifgf_geral", "ifgf_ra", "ifgf_gp",
            "ifgf_id", "ifgf_el", "ifgf_sa",
        ],
        "aux_cols": ["gdp_per_capita", "populacao", "region_code"],
        "per_year": {2020: 210, 2021: 210},
    }


# ---------------------------------------------------------------------------
# Tests: create_schema
# ---------------------------------------------------------------------------

class TestCreateSchema:
    """Tests for the create_schema function."""

    def test_creates_all_tables(self, mem_conn: sqlite3.Connection) -> None:
        """All 5 tables must exist after create_schema."""
        from database.build_database_v3 import create_schema

        create_schema(mem_conn)
        tables = {
            row[0]
            for row in mem_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        expected = {
            "municipal_health",
            "dimension_metadata",
            "municipality_lookup",
            "deflation_log",
            "imputation_log",
        }
        assert expected.issubset(tables), (
            "Missing tables: %s" % (expected - tables)
        )


# ---------------------------------------------------------------------------
# Tests: load_panel
# ---------------------------------------------------------------------------

class TestLoadPanel:
    """Tests for panel loading into SQLite."""

    def test_load_panel_row_count(
        self,
        mem_conn: sqlite3.Connection,
        synthetic_panel: pd.DataFrame,
    ) -> None:
        """Synthetic 100-row panel -> 100 rows in municipal_health."""
        from database.build_database_v3 import create_schema, load_panel

        create_schema(mem_conn)
        n = load_panel(mem_conn, synthetic_panel)
        assert n == 100

        # Verify via SQL
        count = mem_conn.execute(
            "SELECT COUNT(*) FROM municipal_health"
        ).fetchone()[0]
        assert count == 100

    def test_primary_key_constraint(
        self,
        mem_conn: sqlite3.Connection,
        synthetic_panel: pd.DataFrame,
    ) -> None:
        """Duplicate (cod_ibge, year) should not create extra rows."""
        from database.build_database_v3 import create_schema, load_panel

        create_schema(mem_conn)
        load_panel(mem_conn, synthetic_panel)

        # Insert same data again (idempotent via if_exists="replace")
        load_panel(mem_conn, synthetic_panel)
        count = mem_conn.execute(
            "SELECT COUNT(*) FROM municipal_health"
        ).fetchone()[0]
        assert count == 100, "Idempotent load should not duplicate rows"


# ---------------------------------------------------------------------------
# Tests: seed functions
# ---------------------------------------------------------------------------

class TestSeedFunctions:
    """Tests for metadata seeding functions."""

    def test_dimension_metadata_count(
        self, mem_conn: sqlite3.Connection,
    ) -> None:
        """8 active CIMI dimensions seeded (D8 excluded)."""
        from database.build_database_v3 import create_schema, seed_dimension_metadata

        create_schema(mem_conn)
        seed_dimension_metadata(mem_conn)
        count = mem_conn.execute(
            "SELECT COUNT(*) FROM dimension_metadata"
        ).fetchone()[0]
        assert count == 8, "Expected 8 active dimensions, got %d" % count

        # D3 cross-sectional
        d3 = mem_conn.execute(
            "SELECT is_crosssectional, crosssectional_year "
            "FROM dimension_metadata WHERE key='D3'"
        ).fetchone()
        assert d3[0] == 1, "D3 should be cross-sectional"
        assert d3[1] == 2010, "D3 cross-sectional year should be 2010"

        # D5 cross-sectional
        d5 = mem_conn.execute(
            "SELECT is_crosssectional, crosssectional_year "
            "FROM dimension_metadata WHERE key='D5'"
        ).fetchone()
        assert d5[0] == 1, "D5 should be cross-sectional"
        assert d5[1] == 2022, "D5 cross-sectional year should be 2022"

    def test_municipality_lookup_count(
        self, mem_conn: sqlite3.Connection,
    ) -> None:
        """5571 rows after seed_municipality_lookup."""
        from database.build_database_v3 import create_schema, seed_municipality_lookup

        create_schema(mem_conn)
        seed_municipality_lookup(mem_conn)
        count = mem_conn.execute(
            "SELECT COUNT(*) FROM municipality_lookup"
        ).fetchone()[0]
        assert count == 5571, "Expected 5571, got %d" % count

    def test_deflation_log_populated(
        self,
        mem_conn: sqlite3.Connection,
        ipca_df: pd.DataFrame,
    ) -> None:
        """Deflation log should contain all years from IPCA DataFrame."""
        from database.build_database_v3 import create_schema, seed_deflation_log

        create_schema(mem_conn)
        seed_deflation_log(mem_conn, ipca_df)
        count = mem_conn.execute(
            "SELECT COUNT(*) FROM deflation_log"
        ).fetchone()[0]
        assert count == 9, "Expected 9 years, got %d" % count

        # Check specific year
        row = mem_conn.execute(
            "SELECT deflation_factor FROM deflation_log WHERE year=2023"
        ).fetchone()
        assert abs(row[0] - 1.0) < 0.01, "Base year deflation factor should be ~1.0"

    def test_imputation_log_populated(
        self,
        mem_conn: sqlite3.Connection,
        imputation_log: dict,
    ) -> None:
        """Imputation log should have entries for each IFGF col x year."""
        from database.build_database_v3 import create_schema, seed_imputation_log

        create_schema(mem_conn)
        seed_imputation_log(mem_conn, imputation_log)
        count = mem_conn.execute(
            "SELECT COUNT(*) FROM imputation_log"
        ).fetchone()[0]
        # 6 IFGF cols x 2 years = 12 entries
        assert count == 12, "Expected 12 entries, got %d" % count


# ---------------------------------------------------------------------------
# Tests: idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    """Tests for idempotent database operations."""

    def test_idempotent_load(
        self,
        mem_conn: sqlite3.Connection,
        synthetic_panel: pd.DataFrame,
        ipca_df: pd.DataFrame,
        imputation_log: dict,
    ) -> None:
        """Running build twice does not double rows."""
        from database.build_database_v3 import (
            create_schema, seed_dimension_metadata, seed_municipality_lookup,
            seed_deflation_log, seed_imputation_log, load_panel,
        )

        # First build
        create_schema(mem_conn)
        seed_dimension_metadata(mem_conn)
        seed_municipality_lookup(mem_conn)
        seed_deflation_log(mem_conn, ipca_df)
        seed_imputation_log(mem_conn, imputation_log)
        load_panel(mem_conn, synthetic_panel)

        # Second build (idempotent)
        create_schema(mem_conn)
        seed_dimension_metadata(mem_conn)
        seed_municipality_lookup(mem_conn)
        seed_deflation_log(mem_conn, ipca_df)
        seed_imputation_log(mem_conn, imputation_log)
        load_panel(mem_conn, synthetic_panel)

        # Verify counts are NOT doubled
        for table, expected in [
            ("municipal_health", 100),
            ("dimension_metadata", 8),
            ("municipality_lookup", 5571),
            ("deflation_log", 9),
        ]:
            count = mem_conn.execute(
                "SELECT COUNT(*) FROM %s" % table
            ).fetchone()[0]
            assert count == expected, (
                "Table %s: expected %d, got %d" % (table, expected, count)
            )
