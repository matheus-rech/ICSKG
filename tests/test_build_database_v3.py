"""
Tests for database/build_database_v3.py — CIMI-aligned SQLite builder.
"""

import sqlite3

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_synthetic_panel(n_munic: int = 100, years: list[int] | None = None,
                          seed: int = 42) -> pd.DataFrame:
    """Create a synthetic panel for database tests."""
    if years is None:
        years = [2020, 2021]
    rng = np.random.default_rng(seed)

    rows = []
    for year in years:
        for i in range(n_munic):
            rows.append({
                "cod_ibge": f"{1100015 + i:07d}",
                "year": year,
                "ifgf_geral": rng.uniform(0.2, 0.9),
                "ifgf_ra": rng.uniform(0.1, 0.8),
                "gdp_per_capita": rng.uniform(10000, 80000),
                "populacao": rng.integers(5000, 500000),
                "idhm": rng.uniform(0.5, 0.9),
                "private_coverage_rate": rng.uniform(0.01, 0.5),
                "pct_sanitation_adequate": rng.uniform(0.1, 0.99),
                "vehicles_per_1000": rng.uniform(50, 600),
                "total_beds": rng.integers(0, 500),
                "ifgf_is_imputed": rng.choice([0, 1], p=[0.8, 0.2]),
            })
    return pd.DataFrame(rows)


def _make_ipca_df(years: list[int] | None = None) -> pd.DataFrame:
    """Create a synthetic IPCA factors DataFrame."""
    if years is None:
        years = [2020, 2021]
    data = []
    for y in years:
        data.append({
            "year": y,
            "ipca_index": 5000.0 + (y - 2015) * 200,
            "deflation_factor": 1.0 + (2023 - y) * 0.05,
        })
    return pd.DataFrame(data)


def _make_imputation_log() -> dict:
    """Create a synthetic imputation log."""
    return {
        "m": 5,
        "max_iter": 10,
        "method": "IterativeImputer(BayesianRidge, sample_posterior=True)",
        "n_imputed_rows": 84,
        "ifgf_cols": ["ifgf_geral", "ifgf_ra", "ifgf_gp", "ifgf_id", "ifgf_el", "ifgf_sa"],
        "aux_cols": ["gdp_per_capita", "populacao", "region_code"],
        "per_year": {2020: 42, 2021: 42},
    }


# ---------------------------------------------------------------------------
# Tests — create_schema
# ---------------------------------------------------------------------------

class TestCreateSchema:
    """Tests for create_schema()."""

    def test_create_schema_tables(self):
        """All 5 tables must exist after create_schema."""
        from database.build_database_v3 import create_schema

        conn = sqlite3.connect(":memory:")
        create_schema(conn)

        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

        expected = {
            "municipal_health", "dimension_metadata",
            "municipality_lookup", "deflation_log", "imputation_log",
        }
        assert expected.issubset(tables), (
            "Missing tables: %s" % (expected - tables)
        )
        conn.close()


# ---------------------------------------------------------------------------
# Tests — load_panel
# ---------------------------------------------------------------------------

class TestLoadPanel:
    """Tests for panel loading into SQLite."""

    def test_load_panel_row_count(self):
        """Synthetic 200-row panel (100 x 2 years) must have 200 rows in SQLite."""
        from database.build_database_v3 import create_schema, load_panel

        conn = sqlite3.connect(":memory:")
        create_schema(conn)

        panel = _make_synthetic_panel(n_munic=100, years=[2020, 2021])
        n = load_panel(conn, panel)

        assert n == 200
        db_count = conn.execute(
            "SELECT COUNT(*) FROM municipal_health"
        ).fetchone()[0]
        assert db_count == 200
        conn.close()

    def test_primary_key_constraint(self):
        """Duplicate (cod_ibge, year) should raise IntegrityError on manual insert."""
        from database.build_database_v3 import create_schema, load_panel

        conn = sqlite3.connect(":memory:")
        create_schema(conn)

        panel = _make_synthetic_panel(n_munic=10, years=[2020])
        load_panel(conn, panel)

        # Attempt to manually insert a duplicate
        first_row = panel.iloc[0]
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO municipal_health (cod_ibge, year) VALUES (?, ?)",
                (str(first_row["cod_ibge"]), int(first_row["year"])),
            )
        conn.close()

    def test_idempotent_load(self):
        """Running load_panel twice must not double rows (if_exists='replace')."""
        from database.build_database_v3 import create_schema, load_panel

        conn = sqlite3.connect(":memory:")
        create_schema(conn)

        panel = _make_synthetic_panel(n_munic=50, years=[2020])

        load_panel(conn, panel)
        load_panel(conn, panel)

        db_count = conn.execute(
            "SELECT COUNT(*) FROM municipal_health"
        ).fetchone()[0]
        assert db_count == 50
        conn.close()


# ---------------------------------------------------------------------------
# Tests — seed functions
# ---------------------------------------------------------------------------

class TestSeedFunctions:
    """Tests for metadata seeding functions."""

    def test_dimension_metadata_count(self):
        """8 active CIMI dimensions must be seeded (D8 excluded)."""
        from database.build_database_v3 import create_schema, seed_dimension_metadata

        conn = sqlite3.connect(":memory:")
        create_schema(conn)
        seed_dimension_metadata(conn)

        count = conn.execute(
            "SELECT COUNT(*) FROM dimension_metadata"
        ).fetchone()[0]
        assert count == 8, "Expected 8 dimensions, got %d" % count

        # D3 and D5 should be cross-sectional
        d3 = conn.execute(
            "SELECT is_crosssectional, crosssectional_year FROM dimension_metadata "
            "WHERE key = 'D3'"
        ).fetchone()
        assert d3[0] == 1
        assert d3[1] == 2010

        d5 = conn.execute(
            "SELECT is_crosssectional, crosssectional_year FROM dimension_metadata "
            "WHERE key = 'D5'"
        ).fetchone()
        assert d5[0] == 1
        assert d5[1] == 2022
        conn.close()

    def test_municipality_lookup_count(self):
        """municipality_lookup should have 5571 rows after seed."""
        from database.build_database_v3 import create_schema, seed_municipality_lookup

        conn = sqlite3.connect(":memory:")
        create_schema(conn)
        seed_municipality_lookup(conn)

        count = conn.execute(
            "SELECT COUNT(*) FROM municipality_lookup"
        ).fetchone()[0]
        assert count == 5571
        conn.close()

    def test_deflation_log_populated(self):
        """deflation_log must contain all requested years."""
        from database.build_database_v3 import create_schema, seed_deflation_log

        conn = sqlite3.connect(":memory:")
        create_schema(conn)

        ipca_df = _make_ipca_df(years=[2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023])
        seed_deflation_log(conn, ipca_df)

        count = conn.execute(
            "SELECT COUNT(*) FROM deflation_log"
        ).fetchone()[0]
        assert count == 9

        years_in_db = [
            row[0] for row in conn.execute(
                "SELECT year FROM deflation_log ORDER BY year"
            ).fetchall()
        ]
        assert years_in_db == list(range(2015, 2024))
        conn.close()

    def test_imputation_log_populated(self):
        """imputation_log must contain entries from the imputation log dict."""
        from database.build_database_v3 import create_schema, seed_imputation_log

        conn = sqlite3.connect(":memory:")
        create_schema(conn)

        imp_log = _make_imputation_log()
        seed_imputation_log(conn, imp_log)

        count = conn.execute(
            "SELECT COUNT(*) FROM imputation_log"
        ).fetchone()[0]
        # 6 IFGF cols x 2 years = 12 rows
        assert count == 12
        conn.close()
