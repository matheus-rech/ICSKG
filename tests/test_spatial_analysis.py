"""
Tests for analysis.spatial_analysis -- Moran's I spatial autocorrelation
on FE residuals, regional disparity analysis, CUDS choropleth, and LCoGS
heatmaps.
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
def spatial_db(tmp_path: Path) -> Path:
    """Create a minimal SQLite database with dimension_scores,
    lcogs_indicators, and municipality_lookup tables.

    4 municipalities in 2 regions x 3 years = 12 rows.
    """
    db_path = tmp_path / "test_spatial.sqlite"
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
            state_uf   TEXT,
            region     TEXT,
            population INTEGER
        );
    """)

    municipalities = [
        ("3550308", "Sao Paulo", "SP", "Sudeste", 12300000),
        ("3304557", "Rio de Janeiro", "RJ", "Sudeste", 6700000),
        ("2927408", "Salvador", "BA", "Nordeste", 2900000),
        ("2611606", "Recife", "PE", "Nordeste", 1600000),
    ]
    cur.executemany(
        "INSERT INTO municipality_lookup VALUES (?, ?, ?, ?, ?)",
        municipalities,
    )

    rng = np.random.RandomState(42)
    years = [2021, 2022, 2023]

    dim_rows = []
    lcogs_rows = []
    for cod, _name, _uf, _region, _pop in municipalities:
        for year in years:
            d_vals = rng.uniform(0.1, 0.9, size=8).tolist()
            cuds = float(np.exp(np.log(np.array(d_vals) + 0.01).mean()) - 0.01)
            dim_rows.append((cod, year, *d_vals, cuds, 8))
            lcogs_rows.append((
                cod, year,
                rng.uniform(10, 500),
                rng.uniform(5, 50),
                rng.uniform(100, 5000),
                rng.uniform(0.001, 0.05),
                rng.uniform(0.01, 0.3),
                rng.uniform(0.0, 1.0),
            ))

    cur.executemany(
        "INSERT INTO dimension_scores VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        dim_rows,
    )
    cur.executemany(
        "INSERT INTO lcogs_indicators VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        lcogs_rows,
    )

    conn.commit()
    conn.close()
    return db_path


# ---------------------------------------------------------------------------
# Test 1: compute_morans_i structure
# ---------------------------------------------------------------------------

class TestComputeMoransI:
    """Tests for compute_morans_i()."""

    def test_compute_morans_i_structure(
        self, spatial_db: Path, tmp_path: Path,
    ) -> None:
        """compute_morans_i() returns DataFrame with required columns
        and correct interpretation logic.
        """
        from shapely.geometry import Point

        # Build a mock GeoDataFrame matching our 4 municipalities
        mock_gdf = _build_mock_geodataframe()

        # Mock geobr to return our GeoDataFrame
        mock_geobr = MagicMock()
        mock_geobr.read_municipality.return_value = mock_gdf

        # Mock esda.Moran to return controlled values
        mock_moran_instance = MagicMock()
        mock_moran_instance.I = 0.3
        mock_moran_instance.p_sim = 0.01
        mock_moran_instance.z_sim = 2.8

        mock_esda = MagicMock()
        mock_esda.Moran.return_value = mock_moran_instance

        # Mock libpysal weights
        mock_w = MagicMock()
        mock_w.n = 4
        mock_w.mean_neighbors = 2.0

        mock_libpysal = MagicMock()
        mock_libpysal.weights.Queen.from_dataframe.return_value = mock_w

        # Mock linearmodels PanelOLS result with residuals
        mock_resids = pd.Series(
            np.random.RandomState(42).randn(4),
            index=pd.MultiIndex.from_tuples(
                [("3550308", 2023), ("3304557", 2023),
                 ("2927408", 2023), ("2611606", 2023)],
                names=["cod_ibge", "year"],
            ),
        )
        mock_result = MagicMock()
        mock_result.resids = pd.Series(
            np.random.RandomState(42).randn(12),
            index=pd.MultiIndex.from_tuples(
                [(cod, yr)
                 for cod in ["3550308", "3304557", "2927408", "2611606"]
                 for yr in [2021, 2022, 2023]],
                names=["cod_ibge", "year"],
            ),
        )

        with (
            patch.dict("sys.modules", {
                "geobr": mock_geobr,
                "esda": mock_esda,
                "libpysal": mock_libpysal,
                "libpysal.weights": mock_libpysal.weights,
            }),
            patch(
                "analysis.spatial_analysis._load_residuals",
                return_value={
                    "lcogs1_distance_km": mock_result.resids,
                    "sao_per_100k": mock_result.resids,
                    "surgical_volume_per_100k": mock_result.resids,
                    "pomr": mock_result.resids,
                    "financial_risk_ratio": mock_result.resids,
                    "catastrophic_expenditure": mock_result.resids,
                },
            ),
            patch(
                "analysis.spatial_analysis._load_shapefile",
                return_value=mock_gdf,
            ),
        ):
            from analysis.spatial_analysis import compute_morans_i

            out_dir = tmp_path / "results"
            result = compute_morans_i(spatial_db, out_dir, year=2023)

        # Check columns
        expected_cols = {
            "outcome", "morans_i", "p_value", "z_score",
            "n_obs", "interpretation",
        }
        assert set(result.columns) == expected_cols, (
            "Expected columns %s, got %s" % (expected_cols, set(result.columns))
        )

        # Check 6 rows (one per LCoGS outcome)
        assert len(result) == 6, "Should have 6 rows (one per outcome)"

    def test_morans_i_interpretation_positive(self) -> None:
        """With I > 0 and p < 0.05, interpretation is positive spatial
        autocorrelation."""
        from analysis.spatial_analysis import _interpret_morans_i

        interp = _interpret_morans_i(0.35, 0.001)
        assert interp == "positive spatial autocorrelation"

    def test_morans_i_interpretation_negative(self) -> None:
        """With I < 0 and p < 0.05, interpretation is negative spatial
        autocorrelation."""
        from analysis.spatial_analysis import _interpret_morans_i

        interp = _interpret_morans_i(-0.25, 0.02)
        assert interp == "negative spatial autocorrelation"

    def test_morans_i_interpretation_nonsignificant(self) -> None:
        """With p >= 0.05, interpretation is no significant autocorrelation."""
        from analysis.spatial_analysis import _interpret_morans_i

        interp = _interpret_morans_i(-0.01, 0.8)
        assert interp == "no significant autocorrelation"

        interp2 = _interpret_morans_i(0.05, 0.10)
        assert interp2 == "no significant autocorrelation"


# ---------------------------------------------------------------------------
# Test 2: _build_spatial_weights
# ---------------------------------------------------------------------------

class TestBuildSpatialWeights:
    """Tests for _build_spatial_weights()."""

    def test_returns_weights_object(self) -> None:
        """_build_spatial_weights returns a libpysal.weights.W-like object."""
        mock_gdf = _build_mock_geodataframe()

        mock_w = MagicMock()
        mock_w.n = 4
        mock_w.mean_neighbors = 2.0

        mock_libpysal = MagicMock()
        mock_libpysal.weights.Queen.from_dataframe.return_value = mock_w

        with patch.dict("sys.modules", {
            "libpysal": mock_libpysal,
            "libpysal.weights": mock_libpysal.weights,
        }):
            from analysis.spatial_analysis import _build_spatial_weights

            w = _build_spatial_weights(mock_gdf)
            assert w.n == 4


# ---------------------------------------------------------------------------
# Test 3: compute_regional_disparity structure
# ---------------------------------------------------------------------------

class TestComputeRegionalDisparity:
    """Tests for compute_regional_disparity()."""

    def test_regional_disparity_structure(
        self, spatial_db: Path, tmp_path: Path,
    ) -> None:
        """compute_regional_disparity() returns DataFrame with required
        columns and correct number of rows.
        """
        from analysis.spatial_analysis import compute_regional_disparity

        out_dir = tmp_path / "results"
        result = compute_regional_disparity(spatial_db, out_dir)

        expected_cols = {
            "region", "variable", "mean", "median",
            "q25", "q75", "iqr", "n",
        }
        assert set(result.columns) == expected_cols, (
            "Expected columns %s, got %s" % (expected_cols, set(result.columns))
        )

        # 2 regions in test DB x 7 variables = 14 rows
        assert len(result) == 14, (
            "Expected 14 rows (2 regions x 7 variables), got %d" % len(result)
        )

    def test_regional_disparity_regions(
        self, spatial_db: Path, tmp_path: Path,
    ) -> None:
        """All regions from test DB appear in output."""
        from analysis.spatial_analysis import compute_regional_disparity

        out_dir = tmp_path / "results"
        result = compute_regional_disparity(spatial_db, out_dir)
        regions = set(result["region"].unique())
        assert regions == {"Sudeste", "Nordeste"}

    def test_regional_disparity_variables(
        self, spatial_db: Path, tmp_path: Path,
    ) -> None:
        """All 7 disparity variables (cuds + 6 LCoGS) appear in output."""
        from analysis.spatial_analysis import (
            DISPARITY_VARS,
            compute_regional_disparity,
        )

        out_dir = tmp_path / "results"
        result = compute_regional_disparity(spatial_db, out_dir)
        variables = set(result["variable"].unique())
        assert variables == set(DISPARITY_VARS)

    def test_regional_disparity_values(
        self, spatial_db: Path, tmp_path: Path,
    ) -> None:
        """Verify IQR = q75 - q25 for known data."""
        from analysis.spatial_analysis import compute_regional_disparity

        out_dir = tmp_path / "results"
        result = compute_regional_disparity(spatial_db, out_dir)

        for _, row in result.iterrows():
            iqr_computed = row["q75"] - row["q25"]
            assert abs(row["iqr"] - iqr_computed) < 1e-10, (
                "IQR should equal q75 - q25 for %s/%s"
                % (row["region"], row["variable"])
            )

    def test_regional_disparity_csv_saved(
        self, spatial_db: Path, tmp_path: Path,
    ) -> None:
        """CSV file is saved to the expected path."""
        from analysis.spatial_analysis import compute_regional_disparity

        out_dir = tmp_path / "results"
        compute_regional_disparity(spatial_db, out_dir)

        csv_path = out_dir / "tables" / "regional_disparity.csv"
        assert csv_path.exists(), "regional_disparity.csv should be created"


# ---------------------------------------------------------------------------
# Test 4: generate_cuds_choropleth
# ---------------------------------------------------------------------------

class TestGenerateCudsChoropleth:
    """Tests for generate_cuds_choropleth()."""

    def test_creates_png_file(
        self, spatial_db: Path, tmp_path: Path,
    ) -> None:
        """generate_cuds_choropleth() creates a PNG at the expected path."""
        mock_gdf = _build_mock_geodataframe()

        mock_geobr = MagicMock()
        mock_geobr.read_municipality.return_value = mock_gdf
        mock_geobr.read_state.return_value = mock_gdf.copy()

        with (
            patch.dict("sys.modules", {"geobr": mock_geobr}),
            patch(
                "analysis.spatial_analysis._load_shapefile",
                return_value=mock_gdf,
            ),
        ):
            from analysis.spatial_analysis import generate_cuds_choropleth

            out_dir = tmp_path / "results"
            result_path = generate_cuds_choropleth(
                spatial_db, out_dir, year=2023,
            )

        assert result_path.exists(), "Choropleth PNG should be created"
        assert result_path.stat().st_size > 0, "PNG file should not be empty"

    def test_choropleth_dpi(
        self, spatial_db: Path, tmp_path: Path,
    ) -> None:
        """The saved PNG file is reasonably sized for 300 DPI output."""
        mock_gdf = _build_mock_geodataframe()

        mock_geobr = MagicMock()
        mock_geobr.read_municipality.return_value = mock_gdf
        mock_geobr.read_state.return_value = mock_gdf.copy()

        with (
            patch.dict("sys.modules", {"geobr": mock_geobr}),
            patch(
                "analysis.spatial_analysis._load_shapefile",
                return_value=mock_gdf,
            ),
        ):
            from analysis.spatial_analysis import generate_cuds_choropleth

            out_dir = tmp_path / "results"
            result_path = generate_cuds_choropleth(
                spatial_db, out_dir, year=2023,
            )

        # At 300 DPI, even a small map should be >10KB
        file_size = result_path.stat().st_size
        assert file_size > 10_000, (
            "PNG at 300 DPI should be > 10KB, got %d bytes" % file_size
        )


# ---------------------------------------------------------------------------
# Test 5: generate_lcogs_heatmaps
# ---------------------------------------------------------------------------

class TestGenerateLcogsHeatmaps:
    """Tests for generate_lcogs_heatmaps()."""

    def test_creates_heatmap_files(
        self, spatial_db: Path, tmp_path: Path,
    ) -> None:
        """generate_lcogs_heatmaps() creates 6 PNG files."""
        from analysis.spatial_analysis import generate_lcogs_heatmaps

        out_dir = tmp_path / "results"
        paths = generate_lcogs_heatmaps(spatial_db, out_dir)

        assert len(paths) == 6, "Should create 6 heatmap PNGs"
        for p in paths:
            assert p.exists(), "Heatmap PNG %s should exist" % p.name
            assert p.stat().st_size > 0, "Heatmap PNG should not be empty"

    def test_heatmap_data_structure(
        self, spatial_db: Path,
    ) -> None:
        """_build_heatmap_data() returns a pivot with regions as rows
        and years as columns.
        """
        from analysis.spatial_analysis import _build_heatmap_data

        pivot = _build_heatmap_data(spatial_db, "surgical_volume_per_100k")

        # Should have 2 regions (from test DB)
        assert len(pivot) == 2, (
            "Pivot should have 2 regions, got %d" % len(pivot)
        )
        # Should have 3 year columns (2021, 2022, 2023)
        assert pivot.shape[1] == 3, (
            "Pivot should have 3 year columns, got %d" % pivot.shape[1]
        )


# ---------------------------------------------------------------------------
# Helper: build mock GeoDataFrame
# ---------------------------------------------------------------------------

def _build_mock_geodataframe():
    """Build a mock GeoDataFrame with 4 municipality polygons."""
    from shapely.geometry import box

    import geopandas as gpd

    # 4 simple square polygons
    geometries = [
        box(-47.0, -23.5, -46.5, -23.0),  # Sao Paulo approx
        box(-43.5, -23.0, -43.0, -22.5),  # Rio de Janeiro approx
        box(-38.8, -13.2, -38.3, -12.7),  # Salvador approx
        box(-35.2, -8.2, -34.7, -7.7),    # Recife approx
    ]

    gdf = gpd.GeoDataFrame({
        "code_muni": [3550308, 3304557, 2927408, 2611606],
        "name_muni": ["Sao Paulo", "Rio de Janeiro", "Salvador", "Recife"],
        "geometry": geometries,
    }, crs="EPSG:4326")

    return gdf
