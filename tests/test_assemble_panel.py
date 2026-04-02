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
