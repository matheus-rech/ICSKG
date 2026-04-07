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


# ---------------------------------------------------------------------------
# Phase 11 fail-loud guard tests
# ---------------------------------------------------------------------------


class TestFailLoudGuard:
    """Phase 11 — verify build_database_v3.main() refuses to build a phantom database.

    The original failing CI run (24054805442) crashed with KeyError 'variable'
    deep inside generate_missingness_report when run against an empty
    `data_sources/processed/` directory. Phase 11 hardens this in two layers:
    one in impute_ifgf.py (covered by test_impute_ifgf.py::TestFailLoudGuards)
    and one at the build_database_v3 main() entry point so the failure surfaces
    immediately after assemble_panel returns, before any imputation runs.
    """

    def test_main_raises_runtime_error_on_empty_processed_dir(
        self, tmp_path
    ) -> None:
        """An empty processed_dir produces a metadata-only scaffold panel
        whose value_cols are empty. The guard must raise RuntimeError with
        a meaningful message naming the missing data sources, and not write
        any sqlite output."""
        processed_dir = tmp_path / "empty_processed"
        processed_dir.mkdir()
        db_dir = tmp_path / "db"

        from database.build_database_v3 import main

        with pytest.raises(RuntimeError) as exc_info:
            main([
                "--processed-dir", str(processed_dir),
                "--db-dir", str(db_dir),
                "--years", "2022", "2023",
            ])

        msg = str(exc_info.value)
        assert "Refusing to build a phantom database" in msg
        assert "real source data" in msg
        assert "SIH/CNES/ANS/IFGF/SIOPS/IBGE/IPEA" in msg
        assert "0 value columns" in msg
        # Remediation paths must be in the message
        assert "scripts/extract_*.py" in msg
        assert "fetch_processed_data" in msg
        assert "tests/fixtures/processed_smoke" in msg

    def test_main_does_not_create_db_file_when_guard_fires(
        self, tmp_path
    ) -> None:
        """The guard must fire BEFORE the build_database step so no sqlite
        is written to disk. This is critical: a partial database file would
        confuse downstream consumers."""
        processed_dir = tmp_path / "empty_processed"
        processed_dir.mkdir()
        db_dir = tmp_path / "db"

        from database.build_database_v3 import main

        with pytest.raises(RuntimeError):
            main([
                "--processed-dir", str(processed_dir),
                "--db-dir", str(db_dir),
                "--years", "2022", "2023",
            ])

        sqlite_path = db_dir / "icskg_br.sqlite"
        assert not sqlite_path.exists(), (
            "icskg_br.sqlite must not exist after a failed build — "
            "the guard fired but a database file was still written"
        )

    def test_main_succeeds_on_smoke_fixture(self, tmp_path) -> None:
        """End-to-end integration test: a real (committed) smoke fixture
        produces a valid sqlite with the expected scaffold size and the
        expected fixture rows."""
        from pathlib import Path

        smoke_fixture = (
            Path(__file__).parent / "fixtures" / "processed_smoke"
        )
        # Skip cleanly if the fixture isn't present (avoids breaking other
        # CI environments where the fixture might be excluded).
        if not smoke_fixture.exists():
            pytest.skip("smoke fixture not present")

        db_dir = tmp_path / "db"

        from database.build_database_v3 import main

        rc = main([
            "--processed-dir", str(smoke_fixture),
            "--db-dir", str(db_dir),
            "--years", "2022", "2023",
        ])
        assert rc == 0

        sqlite_path = db_dir / "icskg_br.sqlite"
        assert sqlite_path.exists()

        conn = sqlite3.connect(str(sqlite_path))
        try:
            # Full IBGE scaffold × 2 years
            n_rows = conn.execute(
                "SELECT COUNT(*) FROM municipal_health"
            ).fetchone()[0]
            assert n_rows == 11142, (
                "Expected 5571 mun × 2 years = 11142 rows, got %d" % n_rows
            )

            # The 5 fixture municipalities must have non-NaN ifgf_geral
            # (they were observed, not imputed)
            fixture_rows = conn.execute(
                "SELECT cod_ibge, year, ifgf_geral FROM municipal_health "
                "WHERE cod_ibge IN ('3550308','2611606','4314902','5300108','1302603') "
                "AND ifgf_is_imputed = 0 "
                "ORDER BY cod_ibge, year"
            ).fetchall()
            assert len(fixture_rows) == 10, (
                "Expected 10 observed fixture rows (5 mun × 2 years), got %d"
                % len(fixture_rows)
            )

            # Spot-check one known fixture value
            sp_2022 = conn.execute(
                "SELECT ifgf_geral FROM municipal_health "
                "WHERE cod_ibge = '3550308' AND year = 2022"
            ).fetchone()
            assert sp_2022 is not None
            assert abs(sp_2022[0] - 0.58) < 0.001, (
                "São Paulo 2022 ifgf_geral mismatch: expected 0.58, got %s"
                % sp_2022[0]
            )
        finally:
            conn.close()
