"""
ICSKG-BR Dimension Computation Engine
=======================================
Computes all 8 active CIMI dimension scores from the assembled panel,
applies within-year min-max normalization, derives the CUDS composite
via geometric mean, and persists results to SQLite.

Dimensions (8 active, D8 excluded)
------------------------------------
  D1  Governance         -- IFGF fiscal management composite
  D2  Economy            -- GDP per capita (constant 2023 BRL)
  D3  Human Capital      -- IDHM composite (2010 cross-sectional)
  D4  Social Cohesion    -- SUS dependence rate (INVERTED)
  D5  Environment        -- Adequate sanitation % (Census 2022)
  D6  Mobility           -- Vehicles per 1,000 inhabitants
  D7  Urban Planning     -- Hospital beds per 10,000 inhabitants
  D8  International Proj -- EXCLUDED (irrelevant at municipal level)
  D9  Technology         -- Per-capita health expenditure

CUDS Computation
-----------------
  Geometric mean of available normalized dimensions with epsilon=0.01
  floor to prevent zero collapse. Missing dimensions are excluded from
  the geometric mean for that municipality (not treated as zero).

Cross-sectional Flags
----------------------
  D3 (IDHM 2010) and D5 (Census 2022 sanitation) are cross-sectional --
  they do not represent genuine temporal variation.

Usage
-----
    python analysis/compute_dimensions.py \\
        --db-path database/icskg_br.sqlite \\
        --log-file analysis/results/dimension_computation_log.json

Exports
-------
    compute_all_dimensions(panel) -> pd.DataFrame
    normalize_within_year(dims) -> pd.DataFrame
    compute_cuds(dims) -> pd.Series
    persist_dimension_scores(dims, db_path) -> int
"""

import argparse
import json
import logging
import sqlite3
import sys
from datetime import datetime, timezone
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

# Dimension mapping: (panel_column, dimension_key, invert, rate_computation)
# rate_computation: None or (denominator_col, multiplier) for rate dimensions
DIMENSION_MAP = [
    ("ifgf_geral",                    "D1", False, None),
    ("gdp_per_capita",                "D2", False, None),
    ("idhm",                          "D3", False, None),
    ("sus_dependence_rate",           "D4", True,  None),   # INVERT
    ("pct_sanitation_adequate",       "D5", False, None),
    ("vehicles_per_1000",             "D6", False, None),
    ("total_beds",                    "D7", False, ("populacao", 10_000)),
    ("health_expenditure_per_capita", "D9", False, None),
]

EPSILON = 0.01  # Floor offset for geometric mean

DIM_COLS = ["D1", "D2", "D3", "D4", "D5", "D6", "D7", "D9"]

# Dimensions that are inverted (higher raw value = lower score)
INVERTED_DIMS = {d[1] for d in DIMENSION_MAP if d[2]}

# Cross-sectional dimension flags
CROSS_SECTIONAL_FLAGS = {
    "D3": {"source": "IDHM", "year": 2010,
            "note": "Does not represent genuine temporal variation"},
    "D5": {"source": "Census 2022 sanitation", "year": 2022,
            "note": "Does not represent genuine temporal variation"},
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_all_dimensions(panel: pd.DataFrame) -> pd.DataFrame:
    """Map panel source columns to raw (unnormalized) dimension values.

    Parameters
    ----------
    panel : pd.DataFrame
        Assembled panel with (cod_ibge, year, + all source columns).

    Returns
    -------
    pd.DataFrame
        Columns: cod_ibge, year, D1, D2, ..., D7, D9 (raw values).
    """
    dims = panel[["cod_ibge", "year"]].copy()

    for panel_col, dim_key, _invert, rate_comp in DIMENSION_MAP:
        if rate_comp is not None:
            # Rate dimension: panel_col / denominator * multiplier
            denom_col, multiplier = rate_comp
            if panel_col in panel.columns and denom_col in panel.columns:
                denom = panel[denom_col].replace(0, np.nan)
                dims[dim_key] = panel[panel_col] / denom * multiplier
            else:
                dims[dim_key] = np.nan
                logger.warning(
                    "compute_all_dimensions: missing column(s) for %s "
                    "(%s / %s) -- filling with NaN",
                    dim_key, panel_col, denom_col,
                )
        else:
            if panel_col in panel.columns:
                dims[dim_key] = panel[panel_col].values
            else:
                dims[dim_key] = np.nan
                logger.warning(
                    "compute_all_dimensions: missing column '%s' for %s "
                    "-- filling with NaN",
                    panel_col, dim_key,
                )

    logger.info(
        "compute_all_dimensions: %d rows, %d dimensions mapped",
        len(dims), len(DIM_COLS),
    )
    return dims


def normalize_within_year(dims: pd.DataFrame) -> pd.DataFrame:
    """Apply within-year min-max normalization to each dimension column.

    For each year group: (x - x_min) / (x_max - x_min).
    If x_max == x_min (constant column), assigns 0.5 to all.
    NaN values are preserved (not filled).

    D4 (SUS dependence) is inverted AFTER normalization:
    normalized_D4 = 1 - min_max_D4, so higher SUS dependence -> lower score.

    Parameters
    ----------
    dims : pd.DataFrame
        Raw dimension values with cod_ibge, year, D1..D7, D9.

    Returns
    -------
    pd.DataFrame
        Normalized dimension values in [0, 1].
    """
    result = dims.copy()

    def _minmax_group(series: pd.Series) -> pd.Series:
        """Min-max normalize a series within a group; NaN preserved."""
        lo = series.min()
        hi = series.max()
        if hi == lo:
            return pd.Series(
                np.where(series.isna(), np.nan, 0.5),
                index=series.index,
            )
        return (series - lo) / (hi - lo)

    for col in DIM_COLS:
        if col not in result.columns:
            continue
        result[col] = result.groupby("year")[col].transform(_minmax_group)

        # Invert D4 after normalization
        if col in INVERTED_DIMS:
            result[col] = result[col].where(result[col].isna(), 1.0 - result[col])

    logger.info("normalize_within_year: min-max normalization applied")
    return result


def compute_cuds(dims: pd.DataFrame) -> pd.Series:
    """Compute CUDS as geometric mean of available normalized dimensions.

    For each row: cuds = exp(mean(log(scores + epsilon))) - epsilon
    Only non-NaN dimensions are included in the geometric mean.
    If all dimensions are NaN, cuds = NaN.

    Parameters
    ----------
    dims : pd.DataFrame
        Normalized dimension values with D1..D7, D9 columns.

    Returns
    -------
    pd.Series
        CUDS values, one per row.
    """
    available_cols = [c for c in DIM_COLS if c in dims.columns]
    scores = dims[available_cols].values  # shape (n_rows, n_dims)

    cuds_values = np.full(len(dims), np.nan)

    for i in range(len(dims)):
        row = scores[i]
        valid = row[~np.isnan(row)]
        if len(valid) == 0:
            continue
        # Add epsilon floor, compute geometric mean, subtract epsilon
        shifted = valid + EPSILON
        cuds_values[i] = np.exp(np.log(shifted).mean()) - EPSILON

    return pd.Series(cuds_values, index=dims.index, name="cuds")


def persist_dimension_scores(
    dims: pd.DataFrame,
    db_path: Path,
) -> int:
    """Write dimension scores to SQLite dimension_scores table.

    Parameters
    ----------
    dims : pd.DataFrame
        Must have columns: cod_ibge, year, D1..D7, D9, cuds, n_dimensions.
    db_path : Path
        Path to SQLite database file.

    Returns
    -------
    int
        Number of rows written.
    """
    from database.build_database_v3 import create_schema  # noqa: PLC0415

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))

    try:
        create_schema(conn)
        dims.to_sql("dimension_scores", conn, if_exists="replace", index=False)

        # Verify row count
        actual = conn.execute(
            "SELECT COUNT(*) FROM dimension_scores"
        ).fetchone()[0]

        logger.info(
            "persist_dimension_scores: %d rows written to %s",
            actual, db_path,
        )

        # Log CUDS distribution stats
        if "cuds" in dims.columns:
            cuds_valid = dims["cuds"].dropna()
            if len(cuds_valid) > 0:
                logger.info(
                    "CUDS distribution: mean=%.4f, median=%.4f, "
                    "min=%.4f, max=%.4f, std=%.4f",
                    cuds_valid.mean(), cuds_valid.median(),
                    cuds_valid.min(), cuds_valid.max(), cuds_valid.std(),
                )

        # Log cross-sectional flags
        for dim_key, flag in CROSS_SECTIONAL_FLAGS.items():
            logger.info(
                "Cross-sectional flag: %s (%s, year=%d) -- %s",
                dim_key, flag["source"], flag["year"], flag["note"],
            )

        return actual

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Compute CIMI dimensions + CUDS from SQLite municipal_health panel.

    Usage
    -----
        python analysis/compute_dimensions.py \\
            --db-path database/icskg_br.sqlite \\
            --log-file analysis/results/dimension_computation_log.json
    """
    parser = argparse.ArgumentParser(
        description="ICSKG-BR dimension computation engine",
    )
    parser.add_argument(
        "--db-path",
        default="database/icskg_br.sqlite",
        help="Path to SQLite database (default: database/icskg_br.sqlite)",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="Path for computation log JSON (optional)",
    )
    args = parser.parse_args(argv)

    db_path = Path(args.db_path)

    # ---------------------------------------------------------------
    # Read panel from SQLite
    # ---------------------------------------------------------------
    if not db_path.exists():
        logger.error("Database not found: %s", db_path)
        return 1

    conn = sqlite3.connect(str(db_path))
    try:
        panel = pd.read_sql("SELECT * FROM municipal_health", conn)
    finally:
        conn.close()

    if len(panel) == 0:
        logger.error("municipal_health table is empty in %s", db_path)
        return 1

    logger.info("=" * 60)
    logger.info("DIMENSION COMPUTATION ENGINE")
    logger.info("=" * 60)
    logger.info("Panel: %d rows, %d columns from %s", len(panel), len(panel.columns), db_path)

    # ---------------------------------------------------------------
    # Compute dimensions
    # ---------------------------------------------------------------
    dims = compute_all_dimensions(panel)
    dims = normalize_within_year(dims)
    cuds = compute_cuds(dims)
    dims["cuds"] = cuds

    # Count non-NaN dimensions per row
    dims["n_dimensions"] = dims[DIM_COLS].notna().sum(axis=1).astype(int)

    # ---------------------------------------------------------------
    # Persist to SQLite
    # ---------------------------------------------------------------
    n_rows = persist_dimension_scores(dims, db_path)

    # ---------------------------------------------------------------
    # End-to-end assertions
    # ---------------------------------------------------------------
    conn = sqlite3.connect(str(db_path))
    try:
        stored = pd.read_sql("SELECT * FROM dimension_scores", conn)
        assert len(stored) == len(panel), (
            "Row count mismatch: dimension_scores=%d, municipal_health=%d"
            % (len(stored), len(panel))
        )

        # Min-max invariant per year per dimension
        for year in stored["year"].unique():
            year_data = stored[stored["year"] == year]
            for col in DIM_COLS:
                if col not in year_data.columns:
                    continue
                valid = year_data[col].dropna()
                if len(valid) >= 2:
                    assert abs(valid.min() - 0.0) < 1e-10, (
                        "Min-max invariant failed: %s year %d min=%.10f"
                        % (col, year, valid.min())
                    )
                    assert abs(valid.max() - 1.0) < 1e-10, (
                        "Min-max invariant failed: %s year %d max=%.10f"
                        % (col, year, valid.max())
                    )

        # No CUDS exactly 0.0
        cuds_valid = stored["cuds"].dropna()
        if len(cuds_valid) > 0:
            assert (cuds_valid != 0.0).all(), "CUDS epsilon floor violated"

        # D8 exclusion
        logger.info("D8 International Projection: EXCLUDED (irrelevant at municipal level)")

        # Cross-sectional annotation
        logger.info(
            "D3 (IDHM 2010) and D5 (Census 2022 sanitation) are "
            "cross-sectional -- they do not represent genuine temporal variation"
        )

        # Dimension metadata consistency
        meta_keys = {
            row[0]
            for row in conn.execute(
                "SELECT key FROM dimension_metadata"
            ).fetchall()
        }
        expected_keys = {"D1", "D2", "D3", "D4", "D5", "D6", "D7", "D9"}
        if meta_keys:
            assert expected_keys.issubset(meta_keys), (
                "Missing dimension metadata keys: %s" % (expected_keys - meta_keys)
            )
            assert "D8" not in meta_keys, "D8 should not be in dimension_metadata"

        # CUDS distribution info
        if len(cuds_valid) > 0:
            skew_info = "right-skewed" if cuds_valid.median() < cuds_valid.mean() else "left-skewed or symmetric"
            logger.info("CUDS distribution is %s (median=%.4f < mean=%.4f)", skew_info, cuds_valid.median(), cuds_valid.mean())

    finally:
        conn.close()

    # ---------------------------------------------------------------
    # Computation log JSON
    # ---------------------------------------------------------------
    if args.log_file:
        log_path = Path(args.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        cuds_stats = {}
        cuds_s = dims["cuds"].dropna()
        if len(cuds_s) > 0:
            cuds_stats = {
                "mean": round(float(cuds_s.mean()), 6),
                "median": round(float(cuds_s.median()), 6),
                "min": round(float(cuds_s.min()), 6),
                "max": round(float(cuds_s.max()), 6),
                "std": round(float(cuds_s.std()), 6),
            }

        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "dimensions_computed": 8,
            "dimensions_excluded": ["D8"],
            "exclusion_reason": "International Projection irrelevant at municipal level",
            "normalization": "within-year min-max [0,1]",
            "cuds_method": "geometric_mean",
            "cuds_epsilon": EPSILON,
            "cross_sectional_flags": CROSS_SECTIONAL_FLAGS,
            "row_count": n_rows,
            "cuds_stats": cuds_stats,
        }

        with open(log_path, "w") as f:
            json.dump(log_data, f, indent=2, default=str)

        logger.info("Computation log written to %s", log_path)

    logger.info("Dimension computation complete: %d rows persisted", n_rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
