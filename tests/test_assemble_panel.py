"""
Tests for database/assemble_panel.py — Panel assembly orchestrator.

Covers:
  - build_panel_scaffold produces correct shape (5571 * n_years)
  - Each year in scaffold has exactly len(load_ibge_municipios()) rows
  - load_source handles empty Parquet gracefully
  - load_source replicates cross-sectional sources across all panel years
"""

from unittest.mock import patch, MagicMock
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_ibge_ref():
    """Create a small mock IBGE reference DataFrame for fast tests."""
    return pd.DataFrame({
        "cod_ibge": [f"{i:07d}" for i in range(1100015, 1100015 + 10)],
        "nome_municipio": [f"Mun_{i}" for i in range(10)],
        "uf": ["RO"] * 10,
    })


@pytest.fixture
def sample_source_parquet(tmp_path, mock_ibge_ref):
    """Create a sample source Parquet file for testing load_source."""
    df = pd.DataFrame({
        "cod_ibge": mock_ibge_ref["cod_ibge"].tolist() * 2,
        "year": [2020] * 10 + [2021] * 10,
        "value_col": np.random.default_rng(42).random(20),
    })
    path = tmp_path / "test_source.parquet"
    df.to_parquet(path, index=False)
    return path


@pytest.fixture
def empty_source_parquet(tmp_path):
    """Create an empty Parquet file for testing empty handling."""
    df = pd.DataFrame({"cod_ibge": pd.Series(dtype=str), "year": pd.Series(dtype=int)})
    path = tmp_path / "empty_source.parquet"
    df.to_parquet(path, index=False)
    return path


@pytest.fixture
def crosssectional_parquet(tmp_path, mock_ibge_ref):
    """Create a cross-sectional source (single year, e.g. IDHM 2010)."""
    df = pd.DataFrame({
        "cod_ibge": mock_ibge_ref["cod_ibge"].tolist(),
        "year": [2010] * 10,
        "idhm": np.random.default_rng(42).random(10),
    })
    path = tmp_path / "idhm.parquet"
    df.to_parquet(path, index=False)
    return path


# ---------------------------------------------------------------------------
# Test: build_panel_scaffold
# ---------------------------------------------------------------------------

class TestBuildPanelScaffold:
    """Tests for build_panel_scaffold()."""

    @patch("database.assemble_panel.load_ibge_municipios")
    def test_scaffold_shape(self, mock_load, mock_ibge_ref):
        """Scaffold must have exactly ref_count * n_years rows."""
        mock_load.return_value = mock_ibge_ref

        from database.assemble_panel import build_panel_scaffold

        years = range(2015, 2024)
        scaffold = build_panel_scaffold(years)

        expected_rows = len(mock_ibge_ref) * len(list(years))
        assert len(scaffold) == expected_rows
        assert "cod_ibge" in scaffold.columns
        assert "year" in scaffold.columns

    @patch("database.assemble_panel.load_ibge_municipios")
    def test_scaffold_per_year_count(self, mock_load, mock_ibge_ref):
        """Each year must have exactly ref_count rows."""
        mock_load.return_value = mock_ibge_ref

        from database.assemble_panel import build_panel_scaffold

        years = list(range(2015, 2024))
        scaffold = build_panel_scaffold(years)

        for year in years:
            year_rows = scaffold[scaffold["year"] == year]
            assert len(year_rows) == len(mock_ibge_ref), (
                "Year %d has %d rows, expected %d"
                % (year, len(year_rows), len(mock_ibge_ref))
            )

    @patch("database.assemble_panel.load_ibge_municipios")
    def test_scaffold_no_duplicates(self, mock_load, mock_ibge_ref):
        """No duplicate (cod_ibge, year) pairs should exist."""
        mock_load.return_value = mock_ibge_ref

        from database.assemble_panel import build_panel_scaffold

        scaffold = build_panel_scaffold(range(2015, 2024))
        dupes = scaffold.duplicated(subset=["cod_ibge", "year"])
        assert dupes.sum() == 0


# ---------------------------------------------------------------------------
# Test: load_source
# ---------------------------------------------------------------------------

class TestLoadSource:
    """Tests for load_source()."""

    @patch("database.assemble_panel.apply_amc_crosswalk", side_effect=lambda df, year, **kw: df)
    @patch("database.assemble_panel.rename_municipality_column", side_effect=lambda df: df)
    @patch("database.assemble_panel.normalize_cod_ibge", side_effect=lambda s: s)
    def test_load_source_returns_dataframe(
        self, mock_norm, mock_rename, mock_xwalk, sample_source_parquet
    ):
        """load_source should return a non-empty DataFrame."""
        from database.assemble_panel import load_source

        result = load_source(
            name="test",
            path=sample_source_parquet,
            years=list(range(2020, 2022)),
        )
        assert isinstance(result, pd.DataFrame)
        assert len(result) > 0

    @patch("database.assemble_panel.apply_amc_crosswalk", side_effect=lambda df, year, **kw: df)
    @patch("database.assemble_panel.rename_municipality_column", side_effect=lambda df: df)
    @patch("database.assemble_panel.normalize_cod_ibge", side_effect=lambda s: s)
    def test_load_source_empty_handling(
        self, mock_norm, mock_rename, mock_xwalk, empty_source_parquet
    ):
        """Empty Parquet file should return an empty DataFrame (not raise)."""
        from database.assemble_panel import load_source

        result = load_source(
            name="empty_test",
            path=empty_source_parquet,
            years=list(range(2020, 2022)),
        )
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0

    @patch("database.assemble_panel.apply_amc_crosswalk", side_effect=lambda df, year, **kw: df)
    @patch("database.assemble_panel.rename_municipality_column", side_effect=lambda df: df)
    @patch("database.assemble_panel.normalize_cod_ibge", side_effect=lambda s: s)
    def test_load_source_crosssectional_replication(
        self, mock_norm, mock_rename, mock_xwalk, crosssectional_parquet
    ):
        """Cross-sectional source should be replicated across all panel years."""
        from database.assemble_panel import load_source

        panel_years = list(range(2015, 2024))
        result = load_source(
            name="idhm",
            path=crosssectional_parquet,
            years=panel_years,
            is_crosssectional=True,
        )

        assert isinstance(result, pd.DataFrame)
        assert len(result) > 0
        # Should have rows for each panel year, not just 2010
        assert set(result["year"].unique()) == set(panel_years)

    def test_load_source_missing_file(self, tmp_path):
        """Missing file should return empty DataFrame with warning."""
        from database.assemble_panel import load_source

        result = load_source(
            name="missing",
            path=tmp_path / "nonexistent.parquet",
            years=[2020, 2021],
        )
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Test: cnes_professionals aggregation
# ---------------------------------------------------------------------------

class TestCnesProfessionalsAggregation:
    """Tests for per-professional -> per-municipality-year aggregation."""

    @pytest.fixture
    def professionals_parquet(self, tmp_path):
        """Create a mock professionals parquet with per-professional rows."""
        df = pd.DataFrame({
            "cnes": ["C001", "C001", "C002", "C003", "C003", "C003"],
            "cod_ibge": ["1100015", "1100015", "1100015", "1100023", "1100023", "1100023"],
            "year": [2022, 2022, 2022, 2022, 2022, 2022],
            "cbo": ["225225", "225151", "225250", "225225", "225225", "225151"],
            "cns_prof": ["PROF001", "PROF002", "PROF003", "PROF004", "PROF005", "PROF006"],
            "sao_category": ["surgeon", "anesthesiologist", "obstetrician", "surgeon", "surgeon", "anesthesiologist"],
        })
        path = tmp_path / "professionals.parquet"
        df.to_parquet(path, index=False)
        return path

    @pytest.fixture
    def professionals_parquet_with_dupes(self, tmp_path):
        """Professionals parquet where one professional appears in two facilities."""
        df = pd.DataFrame({
            "cnes": ["C001", "C002", "C001"],  # PROF001 at two facilities
            "cod_ibge": ["1100015", "1100015", "1100015"],
            "year": [2022, 2022, 2022],
            "cbo": ["225225", "225151", "225225"],
            "cns_prof": ["PROF001", "PROF002", "PROF001"],  # PROF001 duplicated
            "sao_category": ["surgeon", "anesthesiologist", "surgeon"],
        })
        path = tmp_path / "professionals_dupes.parquet"
        df.to_parquet(path, index=False)
        return path

    @patch("database.assemble_panel.apply_amc_crosswalk", side_effect=lambda df, year, **kw: df)
    @patch("database.assemble_panel.rename_municipality_column", side_effect=lambda df: df)
    @patch("database.assemble_panel.map_6digit_to_7digit", side_effect=lambda s: s)
    def test_aggregates_to_one_row_per_municipality_year(
        self, mock_map, mock_rename, mock_xwalk, professionals_parquet
    ):
        """cnes_professionals should produce exactly one row per (cod_ibge, year)."""
        from database.assemble_panel import load_source

        result = load_source(
            name="cnes_professionals",
            path=professionals_parquet,
            years=[2022],
            is_crosssectional=True,
        )

        assert isinstance(result, pd.DataFrame)
        assert len(result) > 0
        # No duplicate (cod_ibge, year) pairs
        dupes = result.duplicated(subset=["cod_ibge", "year"])
        assert dupes.sum() == 0, "Duplicate (cod_ibge, year) found after aggregation"

    @patch("database.assemble_panel.apply_amc_crosswalk", side_effect=lambda df, year, **kw: df)
    @patch("database.assemble_panel.rename_municipality_column", side_effect=lambda df: df)
    @patch("database.assemble_panel.map_6digit_to_7digit", side_effect=lambda s: s)
    def test_sao_count_column_present(
        self, mock_map, mock_rename, mock_xwalk, professionals_parquet
    ):
        """Result must include sao_count and per-category columns."""
        from database.assemble_panel import load_source

        result = load_source(
            name="cnes_professionals",
            path=professionals_parquet,
            years=[2022],
            is_crosssectional=True,
        )

        for col in ["sao_count", "n_surgeons", "n_anesthesiologists", "n_obstetricians"]:
            assert col in result.columns, f"Expected column '{col}' missing from result"

    @patch("database.assemble_panel.apply_amc_crosswalk", side_effect=lambda df, year, **kw: df)
    @patch("database.assemble_panel.rename_municipality_column", side_effect=lambda df: df)
    @patch("database.assemble_panel.map_6digit_to_7digit", side_effect=lambda s: s)
    def test_correct_counts(
        self, mock_map, mock_rename, mock_xwalk, professionals_parquet
    ):
        """Counts should match the fixture data (2 munis, correct per-category)."""
        from database.assemble_panel import load_source

        result = load_source(
            name="cnes_professionals",
            path=professionals_parquet,
            years=[2022],
            is_crosssectional=True,
        )

        row_1100015 = result[result["cod_ibge"] == "1100015"].iloc[0]
        assert row_1100015["sao_count"] == 3
        assert row_1100015["n_surgeons"] == 1
        assert row_1100015["n_anesthesiologists"] == 1
        assert row_1100015["n_obstetricians"] == 1

        row_1100023 = result[result["cod_ibge"] == "1100023"].iloc[0]
        assert row_1100023["sao_count"] == 3
        assert row_1100023["n_surgeons"] == 2
        assert row_1100023["n_anesthesiologists"] == 1
        assert row_1100023["n_obstetricians"] == 0

    @patch("database.assemble_panel.apply_amc_crosswalk", side_effect=lambda df, year, **kw: df)
    @patch("database.assemble_panel.rename_municipality_column", side_effect=lambda df: df)
    @patch("database.assemble_panel.map_6digit_to_7digit", side_effect=lambda s: s)
    def test_deduplicates_professionals_across_facilities(
        self, mock_map, mock_rename, mock_xwalk, professionals_parquet_with_dupes
    ):
        """A professional appearing in 2 facilities should be counted only once."""
        from database.assemble_panel import load_source

        result = load_source(
            name="cnes_professionals",
            path=professionals_parquet_with_dupes,
            years=[2022],
            is_crosssectional=True,
        )

        row = result[result["cod_ibge"] == "1100015"].iloc[0]
        # PROF001 (surgeon) appears at C001 and C002 -- should count as 1 surgeon
        assert row["sao_count"] == 2, f"Expected 2 unique professionals, got {row['sao_count']}"
        assert row["n_surgeons"] == 1, f"Expected 1 unique surgeon, got {row['n_surgeons']}"
        assert row["n_anesthesiologists"] == 1
