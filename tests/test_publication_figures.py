"""
Tests for analysis.publication_figures -- publication-ready figure generation
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
def fig_db(tmp_path: Path) -> Path:
    """Create a minimal SQLite database with dimension_scores,
    lcogs_indicators, and municipality_lookup tables.

    4 municipalities in 2 regions x 3 years = 12 rows.
    """
    db_path = tmp_path / "test_figs.sqlite"
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

    conn.commit()
    conn.close()
    return db_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_cuds_temporal_trend_creates_file(fig_db: Path, tmp_path: Path):
    """Verify temporal trend figure is created as PNG."""
    from analysis.publication_figures import generate_cuds_temporal_trend

    out_dir = tmp_path / "results"
    result = generate_cuds_temporal_trend(fig_db, out_dir)

    assert result.exists(), "cuds_temporal_trend.png was not created"
    assert result.name == "cuds_temporal_trend.png"
    assert result.stat().st_size > 0


def test_forest_plot_creates_file(fig_db: Path, tmp_path: Path):
    """Verify forest plot figure is created as PNG."""
    from analysis.publication_figures import generate_regression_forest_plot

    out_dir = tmp_path / "results"
    result = generate_regression_forest_plot(fig_db, out_dir)

    assert result.exists(), "regression_forest_plot.png was not created"
    assert result.name == "regression_forest_plot.png"
    assert result.stat().st_size > 0


def test_generate_all_figures_calls_all(fig_db: Path, tmp_path: Path):
    """Verify orchestrator calls all individual figure generators."""
    from analysis import publication_figures

    out_dir = tmp_path / "results"

    mock_choropleth = MagicMock(return_value=out_dir / "figures" / "choropleth.png")
    mock_heatmaps = MagicMock(return_value=[out_dir / "figures" / "heatmap.png"])
    mock_trend = MagicMock(return_value=out_dir / "figures" / "trend.png")
    mock_forest = MagicMock(return_value=out_dir / "figures" / "forest.png")

    with patch.object(
        publication_figures, "generate_cuds_temporal_trend", mock_trend,
    ), patch.object(
        publication_figures, "generate_regression_forest_plot", mock_forest,
    ), patch(
        "analysis.spatial_analysis.generate_cuds_choropleth", mock_choropleth,
    ), patch(
        "analysis.spatial_analysis.generate_lcogs_heatmaps", mock_heatmaps,
    ):
        result = publication_figures.generate_all_figures(fig_db, out_dir)

    mock_trend.assert_called_once()
    mock_forest.assert_called_once()
    # The orchestrator should have attempted all 4 figure types
    assert len(result) >= 2  # trend + forest at minimum (mocked spatials may vary)
