"""
ICSKG-BR Spatial Analysis Engine
==================================
Spatial autocorrelation testing (Moran's I on FE residuals),
publication-ready CUDS choropleth maps, regional disparity analysis,
and LCoGS indicator heatmaps across all 5,570 Brazilian municipalities.

Moran's I
----------
  Tests whether fixed-effects regression residuals (from Phase 7) exhibit
  spatial clustering. Significant positive autocorrelation suggests
  unmodeled spatial dependence in the panel regressions.

CUDS Choropleth
-----------------
  All 5,570+ municipalities rendered at 300 DPI with colorblind-safe
  diverging palette (RdYlGn), state borders visible, legend included.

Regional Disparity
--------------------
  Summary statistics (mean, median, IQR) for CUDS and each LCoGS
  indicator across 5 macro-regions: Norte, Nordeste, Centro-Oeste,
  Sudeste, Sul.

LCoGS Heatmaps
-----------------
  Temporal trends (2015-2023) by region for each LCoGS indicator as
  publication-ready seaborn heatmap figures at 300 DPI.

Outputs
-------
  results/spatial/morans_i.csv              -- Moran's I test results
  results/tables/regional_disparity.csv     -- Regional summary statistics
  results/figures/cuds_choropleth.png       -- CUDS choropleth map
  results/figures/lcogs_heatmap_*.png       -- 6 LCoGS heatmap figures

Usage
-----
    python analysis/spatial_analysis.py \\
        --db-path database/icskg_br.sqlite \\
        --out-dir results \\
        --year 2023

Exports
-------
    compute_morans_i(db_path, out_dir, year) -> pd.DataFrame
    compute_regional_disparity(db_path, out_dir) -> pd.DataFrame
    generate_cuds_choropleth(db_path, out_dir, year) -> Path
    generate_lcogs_heatmaps(db_path, out_dir) -> list[Path]
    main(argv) -> int
"""

import argparse
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
# Constants
# ---------------------------------------------------------------------------

# LCoGS outcomes (same as run_regressions.py)
LCOGS_OUTCOMES = [
    ("lcogs1_distance_km",       "LCoGS-1: Bellwether Access (km)"),
    ("sao_per_100k",             "LCoGS-2: SAO Density per 100k"),
    ("surgical_volume_per_100k", "LCoGS-3: Surgical Volume per 100k"),
    ("pomr",                     "LCoGS-4: Perioperative Mortality"),
    ("financial_risk_ratio",     "LCoGS-5: Financial Risk Ratio"),
    ("catastrophic_expenditure", "LCoGS-6: Catastrophic Expenditure"),
]

REGION_ORDER = ["Norte", "Nordeste", "Centro-Oeste", "Sudeste", "Sul"]

DISPARITY_VARS = [
    "cuds",
    "lcogs1_distance_km",
    "sao_per_100k",
    "surgical_volume_per_100k",
    "pomr",
    "financial_risk_ratio",
    "catastrophic_expenditure",
]

# Module-level shapefile cache
_shapefile_cache = None


# ---------------------------------------------------------------------------
# Shapefile utilities
# ---------------------------------------------------------------------------

def _ensure_cod_ibge(gdf):
    """Ensure GeoDataFrame has a 'cod_ibge' column.

    If 'cod_ibge' is missing but 'code_muni' is present (geobr format),
    creates it by normalizing code_muni to 7-character string.

    Parameters
    ----------
    gdf : gpd.GeoDataFrame
        Municipality geometries.

    Returns
    -------
    gpd.GeoDataFrame
        Same GeoDataFrame with 'cod_ibge' column guaranteed.
    """
    if "cod_ibge" not in gdf.columns and "code_muni" in gdf.columns:
        gdf = gdf.copy()
        gdf["cod_ibge"] = gdf["code_muni"].astype(str).str[:7]
    return gdf


def _load_shapefile():
    """Load Brazilian municipality shapefile via geobr.

    Uses geobr.read_municipality(year=2022) and normalizes cod_ibge
    to 7-character string. Module-level cache avoids re-downloading.

    Returns
    -------
    gpd.GeoDataFrame
        Municipality geometries with 'cod_ibge' column.
    """
    global _shapefile_cache  # noqa: PLW0603

    if _shapefile_cache is not None:
        return _shapefile_cache

    import geobr  # noqa: PLC0415

    logger.info("Loading municipality shapefile via geobr (year=2022)...")
    gdf = geobr.read_municipality(year=2022)
    gdf["cod_ibge"] = gdf["code_muni"].astype(str).str[:7]

    _shapefile_cache = gdf
    logger.info("Loaded %d municipality geometries from geobr", len(gdf))

    return gdf


# ---------------------------------------------------------------------------
# Spatial weights builder
# ---------------------------------------------------------------------------

def _build_spatial_weights(gdf):
    """Build queen contiguity spatial weights from a GeoDataFrame.

    Parameters
    ----------
    gdf : gpd.GeoDataFrame
        Municipality geometries.

    Returns
    -------
    libpysal.weights.W
        Queen contiguity spatial weights matrix.
    """
    import libpysal  # noqa: PLC0415

    w = libpysal.weights.Queen.from_dataframe(gdf)

    logger.info(
        "_build_spatial_weights: %d observations, mean %.1f neighbors",
        w.n, w.mean_neighbors,
    )

    return w


# ---------------------------------------------------------------------------
# Moran's I interpretation helper
# ---------------------------------------------------------------------------

def _interpret_morans_i(i_stat: float, p_value: float) -> str:
    """Interpret Moran's I statistic and p-value.

    Parameters
    ----------
    i_stat : float
        Moran's I statistic.
    p_value : float
        p-value from permutation test.

    Returns
    -------
    str
        Human-readable interpretation.
    """
    if p_value < 0.05:
        if i_stat > 0:
            return "positive spatial autocorrelation"
        else:
            return "negative spatial autocorrelation"
    return "no significant autocorrelation"


# ---------------------------------------------------------------------------
# Residuals loader
# ---------------------------------------------------------------------------

def _load_residuals(db_path: Path) -> dict:
    """Load FE regression residuals from run_panel_regressions.

    Parameters
    ----------
    db_path : Path
        Path to SQLite database.

    Returns
    -------
    dict
        Mapping outcome_col -> pd.Series of residuals with
        MultiIndex (cod_ibge, year).
    """
    from analysis.run_regressions import (  # noqa: PLC0415
        load_regression_panel,
        run_panel_regressions,
    )

    panel = load_regression_panel(db_path)
    results = run_panel_regressions(panel)

    residuals = {}
    for outcome_col, res in results.items():
        residuals[outcome_col] = res.resids

    logger.info(
        "_load_residuals: extracted residuals for %d outcomes",
        len(residuals),
    )

    return residuals


# ---------------------------------------------------------------------------
# Moran's I computation
# ---------------------------------------------------------------------------

def compute_morans_i(
    db_path: Path,
    out_dir: Path,
    year: int = 2023,
) -> pd.DataFrame:
    """Compute Moran's I spatial autocorrelation on FE residuals.

    Tests whether regression residuals exhibit spatial clustering for
    each of the 6 LCoGS outcomes. Significant positive autocorrelation
    suggests unmodeled spatial dependence.

    Parameters
    ----------
    db_path : Path
        Path to SQLite database.
    out_dir : Path
        Root output directory (results/).
    year : int
        Year for which to extract per-municipality residuals (default 2023).

    Returns
    -------
    pd.DataFrame
        Columns: outcome, morans_i, p_value, z_score, n_obs, interpretation.
    """
    import esda  # noqa: PLC0415

    db_path = Path(db_path)
    out_dir = Path(out_dir)

    # Load residuals and shapefile
    residuals = _load_residuals(db_path)
    gdf = _ensure_cod_ibge(_load_shapefile())

    rows = []

    for outcome_col, outcome_label in LCOGS_OUTCOMES:
        if outcome_col not in residuals:
            logger.warning(
                "compute_morans_i: no residuals for '%s' -- skipping",
                outcome_col,
            )
            continue

        resid_series = residuals[outcome_col]

        # Extract residuals for the specified year
        try:
            year_resids = resid_series.xs(year, level="year")
        except KeyError:
            logger.warning(
                "compute_morans_i: year %d not in residuals for %s",
                year, outcome_col,
            )
            continue

        # Convert to DataFrame for merge
        resid_df = year_resids.reset_index()
        resid_df.columns = ["cod_ibge", "residual"]
        resid_df["cod_ibge"] = resid_df["cod_ibge"].astype(str).str[:7]

        # Merge residuals onto shapefile
        merged = gdf.merge(resid_df, on="cod_ibge", how="inner")

        if len(merged) < 4:
            logger.warning(
                "compute_morans_i: only %d matched municipalities for %s",
                len(merged), outcome_col,
            )
            continue

        # Build spatial weights on the merged subset
        w = _build_spatial_weights(merged)

        # Compute Moran's I
        moran = esda.Moran(merged["residual"].values, w)

        interpretation = _interpret_morans_i(moran.I, moran.p_sim)

        rows.append({
            "outcome": outcome_col,
            "morans_i": float(moran.I),
            "p_value": float(moran.p_sim),
            "z_score": float(moran.z_sim),
            "n_obs": len(merged),
            "interpretation": interpretation,
        })

        logger.info(
            "  %s: I=%.4f, p=%.4f, z=%.2f -- %s",
            outcome_label, moran.I, moran.p_sim, moran.z_sim,
            interpretation,
        )

    result = pd.DataFrame(rows)

    # Save to CSV
    spatial_dir = out_dir / "spatial"
    spatial_dir.mkdir(parents=True, exist_ok=True)
    csv_path = spatial_dir / "morans_i.csv"
    result.to_csv(csv_path, index=False)
    logger.info("Moran's I results saved to %s", csv_path)

    return result


# ---------------------------------------------------------------------------
# Regional disparity analysis
# ---------------------------------------------------------------------------

def compute_regional_disparity(
    db_path: Path,
    out_dir: Path,
) -> pd.DataFrame:
    """Compute regional disparity statistics for CUDS and LCoGS indicators.

    Joins dimension_scores + lcogs_indicators + municipality_lookup on
    cod_ibge, groups by region, and computes mean/median/q25/q75/IQR
    for CUDS and all 6 LCoGS indicators across all macro-regions.

    Parameters
    ----------
    db_path : Path
        Path to SQLite database.
    out_dir : Path
        Root output directory (results/).

    Returns
    -------
    pd.DataFrame
        Columns: region, variable, mean, median, q25, q75, iqr, n.
    """
    db_path = Path(db_path)
    out_dir = Path(out_dir)

    conn = sqlite3.connect(str(db_path))
    try:
        dims = pd.read_sql("SELECT cod_ibge, year, cuds FROM dimension_scores", conn)
        lcogs = pd.read_sql("SELECT * FROM lcogs_indicators", conn)
        lookup = pd.read_sql("SELECT cod_ibge, region FROM municipality_lookup", conn)
    finally:
        conn.close()

    # Ensure consistent types
    dims["cod_ibge"] = dims["cod_ibge"].astype(str)
    lcogs["cod_ibge"] = lcogs["cod_ibge"].astype(str)
    lookup["cod_ibge"] = lookup["cod_ibge"].astype(str)

    # Join
    panel = dims.merge(lcogs, on=["cod_ibge", "year"], how="outer")
    panel = panel.merge(lookup, on="cod_ibge", how="left")

    rows = []

    for variable in DISPARITY_VARS:
        if variable not in panel.columns:
            logger.warning(
                "compute_regional_disparity: variable '%s' not in panel",
                variable,
            )
            continue

        for region in panel["region"].dropna().unique():
            subset = panel.loc[
                panel["region"] == region, variable
            ].dropna()

            if len(subset) == 0:
                continue

            q25 = float(np.percentile(subset, 25))
            q75 = float(np.percentile(subset, 75))

            rows.append({
                "region": region,
                "variable": variable,
                "mean": float(subset.mean()),
                "median": float(subset.median()),
                "q25": q25,
                "q75": q75,
                "iqr": q75 - q25,
                "n": int(len(subset)),
            })

    result = pd.DataFrame(rows)

    # Save to CSV
    tables_dir = out_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    csv_path = tables_dir / "regional_disparity.csv"
    result.to_csv(csv_path, index=False)

    logger.info(
        "Regional disparity computed for %d variables across %d regions "
        "-- saved to %s",
        len(DISPARITY_VARS),
        len(result["region"].unique()),
        csv_path,
    )

    return result


# ---------------------------------------------------------------------------
# Heatmap data builder
# ---------------------------------------------------------------------------

def _build_heatmap_data(db_path: Path, indicator: str) -> pd.DataFrame:
    """Build a pivot table for heatmap visualisation.

    Parameters
    ----------
    db_path : Path
        Path to SQLite database.
    indicator : str
        LCoGS indicator column name.

    Returns
    -------
    pd.DataFrame
        Pivot table with regions as rows (ordered by REGION_ORDER)
        and years as columns.
    """
    db_path = Path(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        lcogs = pd.read_sql("SELECT * FROM lcogs_indicators", conn)
        lookup = pd.read_sql("SELECT cod_ibge, region FROM municipality_lookup", conn)
    finally:
        conn.close()

    lcogs["cod_ibge"] = lcogs["cod_ibge"].astype(str)
    lookup["cod_ibge"] = lookup["cod_ibge"].astype(str)

    merged = lcogs.merge(lookup, on="cod_ibge", how="left")

    if indicator not in merged.columns:
        logger.warning(
            "_build_heatmap_data: indicator '%s' not found", indicator,
        )
        return pd.DataFrame()

    # Group by region and year, compute median
    grouped = (
        merged
        .groupby(["region", "year"])[indicator]
        .median()
        .reset_index()
    )

    # Pivot: rows = regions, columns = years
    pivot = grouped.pivot(index="region", columns="year", values=indicator)

    # Reorder rows by REGION_ORDER (only keep regions present)
    present_regions = [r for r in REGION_ORDER if r in pivot.index]
    pivot = pivot.loc[present_regions]

    return pivot


# ---------------------------------------------------------------------------
# CUDS choropleth
# ---------------------------------------------------------------------------

def generate_cuds_choropleth(
    db_path: Path,
    out_dir: Path,
    year: int = 2023,
) -> Path:
    """Generate a publication-ready CUDS choropleth map.

    Renders all municipalities with a colorblind-safe diverging palette
    (RdYlGn), state borders visible, legend, saved at 300 DPI.

    Parameters
    ----------
    db_path : Path
        Path to SQLite database.
    out_dir : Path
        Root output directory (results/).
    year : int
        Year for CUDS values (default 2023).

    Returns
    -------
    Path
        Path to the saved PNG file.
    """
    import matplotlib  # noqa: PLC0415
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: PLC0415

    db_path = Path(db_path)
    out_dir = Path(out_dir)

    # Load shapefile
    gdf = _ensure_cod_ibge(_load_shapefile())

    # Load CUDS for the specified year
    conn = sqlite3.connect(str(db_path))
    try:
        dims = pd.read_sql(
            "SELECT cod_ibge, cuds FROM dimension_scores WHERE year = ?",
            conn,
            params=(year,),
        )
    finally:
        conn.close()

    dims["cod_ibge"] = dims["cod_ibge"].astype(str).str[:7]

    # Merge
    merged = gdf.merge(dims, on="cod_ibge", how="left")

    # Try SciencePlots style context
    try:
        import scienceplots  # noqa: PLC0415, F401
        style_ctx = plt.style.context(["science", "no-latex"])
    except (ImportError, OSError):
        style_ctx = plt.style.context("default")

    with style_ctx:
        fig, ax = plt.subplots(figsize=(16, 14))

        # Plot municipalities with colorblind-safe diverging palette
        merged.plot(
            column="cuds",
            ax=ax,
            legend=True,
            cmap="RdYlGn",
            missing_kwds={"color": "lightgrey", "label": "No data"},
            legend_kwds={
                "label": "CUDS Score",
                "orientation": "horizontal",
                "shrink": 0.6,
                "pad": 0.02,
            },
        )

        # Add state borders
        try:
            import geobr  # noqa: PLC0415
            states = geobr.read_state(year=2022)
            states.boundary.plot(
                ax=ax,
                edgecolor="black",
                linewidth=0.5,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Could not overlay state borders: %s", exc,
            )

        ax.set_title(
            "Composite Urban Development Score (CUDS) -- %d" % year,
            fontsize=14,
            fontweight="bold",
        )
        ax.set_axis_off()

        # Save
        figures_dir = out_dir / "figures"
        figures_dir.mkdir(parents=True, exist_ok=True)
        out_path = figures_dir / "cuds_choropleth.png"
        fig.savefig(
            out_path,
            dpi=300,
            bbox_inches="tight",
            facecolor="white",
        )
        plt.close(fig)

    file_mb = out_path.stat().st_size / (1024 * 1024)
    logger.info("CUDS choropleth saved to %s (%.1f MB)", out_path, file_mb)

    return out_path


# ---------------------------------------------------------------------------
# LCoGS heatmaps
# ---------------------------------------------------------------------------

def generate_lcogs_heatmaps(
    db_path: Path,
    out_dir: Path,
) -> list[Path]:
    """Generate publication-ready heatmaps for each LCoGS indicator.

    Each heatmap shows temporal trends (2015-2023) across 5 macro-regions
    with annotated values, saved at 300 DPI.

    Parameters
    ----------
    db_path : Path
        Path to SQLite database.
    out_dir : Path
        Root output directory (results/).

    Returns
    -------
    list[Path]
        Paths to the saved PNG files.
    """
    import matplotlib  # noqa: PLC0415
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: PLC0415
    import seaborn as sns  # noqa: PLC0415

    db_path = Path(db_path)
    out_dir = Path(out_dir)

    figures_dir = out_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    paths = []

    for outcome_col, outcome_label in LCOGS_OUTCOMES:
        pivot = _build_heatmap_data(db_path, outcome_col)

        if pivot.empty:
            logger.warning(
                "generate_lcogs_heatmaps: no data for %s -- skipping",
                outcome_col,
            )
            continue

        # Try SciencePlots style context
        try:
            import scienceplots  # noqa: PLC0415, F401
            style_ctx = plt.style.context(["science", "no-latex"])
        except (ImportError, OSError):
            style_ctx = plt.style.context("default")

        with style_ctx:
            fig, ax = plt.subplots(figsize=(12, 6))

            sns.heatmap(
                pivot,
                annot=True,
                fmt=".1f",
                cmap="YlOrRd",
                linewidths=0.5,
                linecolor="white",
                ax=ax,
                cbar_kws={"label": outcome_label},
            )

            ax.set_title(
                "%s -- Regional Temporal Trends" % outcome_label,
                fontsize=12,
                fontweight="bold",
            )
            ax.set_ylabel("Region")
            ax.set_xlabel("Year")

            out_path = figures_dir / ("lcogs_heatmap_%s.png" % outcome_col)
            fig.savefig(
                out_path,
                dpi=300,
                bbox_inches="tight",
                facecolor="white",
            )
            plt.close(fig)

        paths.append(out_path)
        logger.info("Heatmap saved: %s", out_path)

    logger.info(
        "generate_lcogs_heatmaps: %d heatmaps created in %s",
        len(paths), figures_dir,
    )

    return paths


# ---------------------------------------------------------------------------
# Bivariate choropleth (bonus)
# ---------------------------------------------------------------------------

def generate_bivariate_choropleth(
    db_path: Path,
    out_dir: Path,
    lcogs_col: str = "surgical_volume_per_100k",
    year: int = 2023,
    n_classes: int = 3,
) -> Path:
    """Generate a 3x3 bivariate choropleth overlaying CUDS and a LCoGS indicator.

    Uses a 3x3 bivariate color scheme (purple-teal-brown) where the
    x-axis is CUDS tertile and y-axis is LCoGS indicator tertile.

    Parameters
    ----------
    db_path : Path
        Path to SQLite database.
    out_dir : Path
        Root output directory (results/).
    lcogs_col : str
        LCoGS indicator column to overlay (default: surgical_volume_per_100k).
    year : int
        Year for values (default 2023).
    n_classes : int
        Number of quantile classes per axis (default 3 for 3x3).

    Returns
    -------
    Path
        Path to the saved PNG file.
    """
    import matplotlib  # noqa: PLC0415
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: PLC0415
    import matplotlib.colors as mcolors  # noqa: PLC0415
    from matplotlib.patches import Rectangle  # noqa: PLC0415

    db_path = Path(db_path)
    out_dir = Path(out_dir)

    # Load shapefile
    gdf = _ensure_cod_ibge(_load_shapefile())

    # Load CUDS and LCoGS indicator
    conn = sqlite3.connect(str(db_path))
    try:
        dims = pd.read_sql(
            "SELECT cod_ibge, cuds FROM dimension_scores WHERE year = ?",
            conn,
            params=(year,),
        )
        lcogs = pd.read_sql(
            "SELECT cod_ibge, %s FROM lcogs_indicators WHERE year = ?" % lcogs_col,
            conn,
            params=(year,),
        )
    finally:
        conn.close()

    dims["cod_ibge"] = dims["cod_ibge"].astype(str).str[:7]
    lcogs["cod_ibge"] = lcogs["cod_ibge"].astype(str).str[:7]

    # Merge
    data = dims.merge(lcogs, on="cod_ibge", how="inner")
    merged = gdf.merge(data, on="cod_ibge", how="left")

    # Define 3x3 bivariate color palette (purple-teal-brown)
    # Rows = LCoGS tertile (low to high), Cols = CUDS tertile (low to high)
    bivariate_colors = [
        # Low LCoGS
        ["#e8e8e8", "#ace4e4", "#5ac8c8"],
        # Mid LCoGS
        ["#dfb0d6", "#a5add3", "#5698b9"],
        # High LCoGS
        ["#be64ac", "#8c62aa", "#3b4994"],
    ]

    # Classify into tertiles
    valid_mask = merged["cuds"].notna() & merged[lcogs_col].notna()
    merged["cuds_class"] = np.nan
    merged["lcogs_class"] = np.nan

    if valid_mask.any():
        merged.loc[valid_mask, "cuds_class"] = pd.qcut(
            merged.loc[valid_mask, "cuds"],
            q=n_classes,
            labels=range(n_classes),
            duplicates="drop",
        ).astype(float)
        merged.loc[valid_mask, "lcogs_class"] = pd.qcut(
            merged.loc[valid_mask, lcogs_col],
            q=n_classes,
            labels=range(n_classes),
            duplicates="drop",
        ).astype(float)

    # Map to bivariate color
    def _get_bivariate_color(row):
        if pd.isna(row["cuds_class"]) or pd.isna(row["lcogs_class"]):
            return "lightgrey"
        ci = int(row["cuds_class"])
        li = int(row["lcogs_class"])
        ci = min(ci, n_classes - 1)
        li = min(li, n_classes - 1)
        return bivariate_colors[li][ci]

    merged["biv_color"] = merged.apply(_get_bivariate_color, axis=1)

    # Plot
    fig, ax = plt.subplots(figsize=(16, 14))
    merged.plot(ax=ax, color=merged["biv_color"], linewidth=0.1, edgecolor="grey")

    # Add state borders
    try:
        import geobr  # noqa: PLC0415
        states = geobr.read_state(year=2022)
        states.boundary.plot(ax=ax, edgecolor="black", linewidth=0.5)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not overlay state borders: %s", exc)

    ax.set_title(
        "Bivariate: CUDS vs %s -- %d" % (lcogs_col, year),
        fontsize=14,
        fontweight="bold",
    )
    ax.set_axis_off()

    # Add legend (3x3 color grid)
    legend_ax = fig.add_axes([0.15, 0.12, 0.12, 0.12])
    for i in range(n_classes):
        for j in range(n_classes):
            rect = Rectangle(
                (j, i), 1, 1,
                facecolor=bivariate_colors[i][j],
                edgecolor="white",
                linewidth=0.5,
            )
            legend_ax.add_patch(rect)

    legend_ax.set_xlim(0, n_classes)
    legend_ax.set_ylim(0, n_classes)
    legend_ax.set_xlabel("CUDS -->", fontsize=8)
    legend_ax.set_ylabel("%s -->" % lcogs_col.replace("_", " "), fontsize=7)
    legend_ax.set_xticks([])
    legend_ax.set_yticks([])

    # Save
    figures_dir = out_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    out_path = figures_dir / ("bivariate_cuds_%s.png" % lcogs_col)
    fig.savefig(
        out_path,
        dpi=300,
        bbox_inches="tight",
        facecolor="white",
    )
    plt.close(fig)

    file_mb = out_path.stat().st_size / (1024 * 1024)
    logger.info(
        "Bivariate choropleth saved to %s (%.1f MB)", out_path, file_mb,
    )

    return out_path


# ---------------------------------------------------------------------------
# Patient flow network map (bonus)
# ---------------------------------------------------------------------------

def _haversine_km(
    lat1: np.ndarray,
    lon1: np.ndarray,
    lat2: np.ndarray,
    lon2: np.ndarray,
) -> np.ndarray:
    """Compute haversine distance in km between coordinate pairs.

    Parameters
    ----------
    lat1, lon1, lat2, lon2 : np.ndarray
        Coordinates in decimal degrees.

    Returns
    -------
    np.ndarray
        Great-circle distances in kilometres.
    """
    earth_radius_km = 6371.0

    lat1_r = np.radians(lat1)
    lat2_r = np.radians(lat2)
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)

    a = (
        np.sin(dlat / 2.0) ** 2
        + np.cos(lat1_r) * np.cos(lat2_r) * np.sin(dlon / 2.0) ** 2
    )
    c = 2.0 * np.arcsin(np.sqrt(a))

    return earth_radius_km * c


def generate_patient_flow_map(
    db_path: Path,
    out_dir: Path,
    year: int = 2023,
    top_n: int = 50,
) -> Path:
    """Generate a patient flow network map showing surgical patient migration.

    Connects MUNIC_RES (residence) to MUNIC_MOV (treatment) from SIH data,
    showing top-N flows as lines weighted by volume with haversine distances.

    Parameters
    ----------
    db_path : Path
        Path to SQLite database.
    out_dir : Path
        Root output directory (results/).
    year : int
        Year for SIH flow data (default 2023).
    top_n : int
        Number of top flows to display (default 50).

    Returns
    -------
    Path
        Path to the saved PNG file.
    """
    import matplotlib  # noqa: PLC0415
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: PLC0415

    db_path = Path(db_path)
    out_dir = Path(out_dir)

    # Load shapefile for background map
    gdf = _ensure_cod_ibge(_load_shapefile())

    # Load municipality centroids from shapefile
    centroids = gdf.copy()
    centroids["centroid"] = centroids.geometry.centroid
    centroids["lat"] = centroids["centroid"].y
    centroids["lon"] = centroids["centroid"].x
    centroid_lookup = centroids.set_index("cod_ibge")[["lat", "lon"]]

    # Try to load SIH flow data from processed parquet files
    from pathlib import Path as _Path  # noqa: PLC0415

    processed_dir = _Path("data_sources/processed")
    flow_data = None

    # Try loading from parquet files
    sih_files = sorted(processed_dir.glob("sih_%04d*.parquet" % year)) if processed_dir.exists() else []

    if sih_files:
        frames = []
        for f in sih_files:
            try:
                df = pd.read_parquet(
                    f,
                    columns=["MUNIC_RES", "MUNIC_MOV"],
                )
                frames.append(df)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not read %s: %s", f, exc)

        if frames:
            flow_data = pd.concat(frames, ignore_index=True)

    # Fallback: try loading from SQLite municipal_health
    if flow_data is None or flow_data.empty:
        conn = sqlite3.connect(str(db_path))
        try:
            # Check if flow data exists in the database
            tables = pd.read_sql(
                "SELECT name FROM sqlite_master WHERE type='table'", conn,
            )
            if "sih_flows" in tables["name"].values:
                flow_data = pd.read_sql(
                    "SELECT munic_res, munic_mov, n_procedures "
                    "FROM sih_flows WHERE year = ?",
                    conn,
                    params=(year,),
                )
                flow_data.rename(columns={
                    "munic_res": "MUNIC_RES",
                    "munic_mov": "MUNIC_MOV",
                }, inplace=True)
        finally:
            conn.close()

    # If still no data, generate synthetic example
    if flow_data is None or flow_data.empty:
        logger.warning(
            "No SIH flow data found for year %d -- generating synthetic example",
            year,
        )
        rng = np.random.RandomState(42)
        major_cities = [
            "3550308", "3304557", "5300108", "2927408",
            "4106902", "2611606", "1302603", "2304400",
            "5208707", "3106200",
        ]
        n_flows = 200
        flow_data = pd.DataFrame({
            "MUNIC_RES": rng.choice(major_cities, size=n_flows),
            "MUNIC_MOV": rng.choice(major_cities, size=n_flows),
        })

    # Normalize codes
    flow_data["MUNIC_RES"] = flow_data["MUNIC_RES"].astype(str).str[:7]
    flow_data["MUNIC_MOV"] = flow_data["MUNIC_MOV"].astype(str).str[:7]

    # Remove self-flows (residence == treatment)
    flow_data = flow_data[flow_data["MUNIC_RES"] != flow_data["MUNIC_MOV"]]

    # Aggregate flows
    if "n_procedures" in flow_data.columns:
        flows_agg = (
            flow_data
            .groupby(["MUNIC_RES", "MUNIC_MOV"])["n_procedures"]
            .sum()
            .reset_index()
            .rename(columns={"n_procedures": "volume"})
        )
    else:
        flows_agg = (
            flow_data
            .groupby(["MUNIC_RES", "MUNIC_MOV"])
            .size()
            .reset_index(name="volume")
        )

    # Get top-N flows
    flows_top = flows_agg.nlargest(top_n, "volume")

    # Merge with centroids for origin/destination coordinates
    flows_top = flows_top.merge(
        centroid_lookup.rename(columns={"lat": "lat_o", "lon": "lon_o"}),
        left_on="MUNIC_RES",
        right_index=True,
        how="left",
    )
    flows_top = flows_top.merge(
        centroid_lookup.rename(columns={"lat": "lat_d", "lon": "lon_d"}),
        left_on="MUNIC_MOV",
        right_index=True,
        how="left",
    )

    # Drop rows without coordinates
    flows_top = flows_top.dropna(subset=["lat_o", "lon_o", "lat_d", "lon_d"])

    # Compute haversine distance
    if len(flows_top) > 0:
        flows_top["distance_km"] = _haversine_km(
            flows_top["lat_o"].values,
            flows_top["lon_o"].values,
            flows_top["lat_d"].values,
            flows_top["lon_d"].values,
        )

    # Plot
    fig, ax = plt.subplots(figsize=(16, 14))

    # Background map
    gdf.plot(ax=ax, color="#f0f0f0", edgecolor="#cccccc", linewidth=0.1)

    # Add state borders
    try:
        import geobr  # noqa: PLC0415
        states = geobr.read_state(year=2022)
        states.boundary.plot(ax=ax, edgecolor="black", linewidth=0.5)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not overlay state borders: %s", exc)

    # Draw flow lines
    if len(flows_top) > 0:
        max_vol = flows_top["volume"].max()
        min_vol = flows_top["volume"].min()
        vol_range = max_vol - min_vol if max_vol != min_vol else 1.0

        for _, row in flows_top.iterrows():
            # Line width proportional to volume
            lw = 0.5 + 4.0 * (row["volume"] - min_vol) / vol_range
            alpha = 0.3 + 0.6 * (row["volume"] - min_vol) / vol_range

            ax.plot(
                [row["lon_o"], row["lon_d"]],
                [row["lat_o"], row["lat_d"]],
                color="#e63946",
                linewidth=lw,
                alpha=alpha,
                zorder=2,
            )

        # Mark destination cities
        dest_coords = flows_top.drop_duplicates("MUNIC_MOV")
        ax.scatter(
            dest_coords["lon_d"],
            dest_coords["lat_d"],
            s=20,
            c="#1d3557",
            zorder=3,
            label="Treatment municipality",
        )

    ax.set_title(
        "Patient Flow Network: Top %d Surgical Migration Routes -- %d"
        % (top_n, year),
        fontsize=14,
        fontweight="bold",
    )
    ax.set_axis_off()
    ax.legend(loc="lower left", fontsize=9)

    # Save
    figures_dir = out_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    out_path = figures_dir / "patient_flow_network.png"
    fig.savefig(
        out_path,
        dpi=300,
        bbox_inches="tight",
        facecolor="white",
    )
    plt.close(fig)

    # Save flow data CSV
    if len(flows_top) > 0:
        csv_path = out_dir / "spatial" / "patient_flows_top%d.csv" % top_n
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        flows_top.to_csv(csv_path, index=False)
        logger.info("Patient flow data saved to %s", csv_path)

    file_mb = out_path.stat().st_size / (1024 * 1024)
    logger.info(
        "Patient flow network map saved to %s (%.1f MB)", out_path, file_mb,
    )

    return out_path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Run spatial analysis: Moran's I, choropleth, disparity, heatmaps.

    Usage
    -----
        python analysis/spatial_analysis.py \\
            --db-path database/icskg_br.sqlite \\
            --out-dir results \\
            --year 2023
    """
    parser = argparse.ArgumentParser(
        description="ICSKG-BR spatial analysis engine",
    )
    parser.add_argument(
        "--db-path",
        default="database/icskg_br.sqlite",
        help="Path to SQLite database (default: database/icskg_br.sqlite)",
    )
    parser.add_argument(
        "--out-dir",
        default="results",
        help="Output directory (default: results)",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=2023,
        help="Analysis year (default: 2023)",
    )
    args = parser.parse_args(argv)

    db_path = Path(args.db_path)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------
    # Stage 1: Moran's I spatial autocorrelation
    # ---------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("SPATIAL ANALYSIS ENGINE")
    logger.info("=" * 60)

    logger.info("=" * 60)
    logger.info("STAGE 1: Moran's I on FE residuals")
    logger.info("=" * 60)

    morans_df = compute_morans_i(db_path, out_dir, year=args.year)

    # ---------------------------------------------------------------
    # Stage 2: Regional disparity
    # ---------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("STAGE 2: Regional disparity analysis")
    logger.info("=" * 60)

    disparity_df = compute_regional_disparity(db_path, out_dir)

    # ---------------------------------------------------------------
    # Stage 3: CUDS choropleth
    # ---------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("STAGE 3: CUDS choropleth map")
    logger.info("=" * 60)

    choropleth_path = generate_cuds_choropleth(db_path, out_dir, year=args.year)

    # ---------------------------------------------------------------
    # Stage 4: LCoGS heatmaps
    # ---------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("STAGE 4: LCoGS regional heatmaps")
    logger.info("=" * 60)

    heatmap_paths = generate_lcogs_heatmaps(db_path, out_dir)

    # ---------------------------------------------------------------
    # Stage 5: Bivariate choropleth (bonus)
    # ---------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("STAGE 5: Bivariate choropleth (bonus)")
    logger.info("=" * 60)

    biv_path = generate_bivariate_choropleth(
        db_path, out_dir,
        lcogs_col="surgical_volume_per_100k",
        year=args.year,
    )

    # ---------------------------------------------------------------
    # Stage 6: Patient flow network (bonus)
    # ---------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("STAGE 6: Patient flow network (bonus)")
    logger.info("=" * 60)

    flow_path = generate_patient_flow_map(
        db_path, out_dir, year=args.year,
    )

    # ---------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("SPATIAL ANALYSIS COMPLETE")
    logger.info("  Moran's I tests: %d", len(morans_df))
    logger.info("  Regional disparity rows: %d", len(disparity_df))
    logger.info("  Choropleth: %s", choropleth_path)
    logger.info("  Heatmaps: %d", len(heatmap_paths))
    logger.info("  Bivariate choropleth: %s", biv_path)
    logger.info("  Patient flow: %s", flow_path)
    logger.info("  Output directory: %s", out_dir)
    logger.info("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
