"""
ICSKG-BR Network Distance Analysis (METH-07)
===============================================
Summarises haversine distances between the municipality of patient
residence (MUNIC_RES / cod_ibge_res) and the municipality of treatment
(MUNIC_MOV / cod_ibge) from SIH procedure-level Parquet files.

For each (municipality-of-treatment, year) pair the module computes:

  - n_procedures          total procedure count
  - n_self_treated        patients treated in their own municipality
  - pct_self_treated      n_self_treated / n_procedures * 100
  - mean_distance_km      mean haversine distance (referred patients only)
  - median_distance_km    median haversine distance (referred patients only)
  - p90_distance_km       90th percentile distance (referred patients only)
  - max_distance_km       max haversine distance (referred patients only)

Self-treated patients (cod_ibge == cod_ibge_res) have distance = 0 and
are **excluded** from the referred-patient distance statistics but
**included** in the total procedure count.

Outputs
-------
    results/tables/network_distances.csv        -- per-municipality-year summaries
    (optional) SQLite table network_distance_metrics

Usage
-----
    python analysis/network_distances.py \\
        --sih-dir data_sources/processed/sih \\
        --out-dir results

Exports
-------
    compute_network_distances(sih_dir, years) -> pd.DataFrame
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

PROCESSED_SIH_DIR = Path("data_sources/processed/sih")

DISTANCE_COLS = ["cod_ibge", "cod_ibge_res", "year", "N_AIH"]

EARTH_RADIUS_KM = 6371.0

# Module-level centroid cache
_centroids_cache: dict[str, tuple[float, float]] | None = None


# ---------------------------------------------------------------------------
# Haversine (self-contained copy to avoid cross-module dependency)
# ---------------------------------------------------------------------------

def _haversine_km(
    lat1: np.ndarray,
    lon1: np.ndarray,
    lat2: np.ndarray,
    lon2: np.ndarray,
) -> np.ndarray:
    """Compute haversine distance in km between two sets of coordinates.

    Pure numpy implementation. Accepts arrays for vectorised computation.

    Parameters
    ----------
    lat1, lon1 : np.ndarray
        Latitude and longitude of first point(s) in decimal degrees.
    lat2, lon2 : np.ndarray
        Latitude and longitude of second point(s) in decimal degrees.

    Returns
    -------
    np.ndarray
        Great-circle distance in kilometres.
    """
    lat1_r = np.radians(lat1)
    lat2_r = np.radians(lat2)
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)

    a = (
        np.sin(dlat / 2.0) ** 2
        + np.cos(lat1_r) * np.cos(lat2_r) * np.sin(dlon / 2.0) ** 2
    )
    c = 2.0 * np.arcsin(np.sqrt(a))

    return EARTH_RADIUS_KM * c


# ---------------------------------------------------------------------------
# Centroid loader
# ---------------------------------------------------------------------------

def _load_centroids() -> dict[str, tuple[float, float]]:
    """Load municipality centroid coordinates via geobr.

    Returns a dict mapping cod_ibge (7-char string) to (lat, lon).
    Results are cached at module level to avoid re-downloading.

    Returns
    -------
    dict[str, tuple[float, float]]
        Mapping of cod_ibge -> (latitude, longitude).
    """
    global _centroids_cache  # noqa: PLW0603

    if _centroids_cache is not None:
        return _centroids_cache

    try:
        import geobr  # noqa: PLC0415

        logger.info("Loading municipality centroids via geobr...")
        gdf = geobr.read_municipality(year=2022)
        gdf["centroid"] = gdf.geometry.centroid
        centroids = {}
        for _, row in gdf.iterrows():
            cod = str(row["code_muni"])[:7]
            centroids[cod] = (float(row["centroid"].y), float(row["centroid"].x))

        _centroids_cache = centroids
        logger.info(
            "Loaded %d municipality centroids from geobr", len(centroids),
        )
        return centroids

    except ImportError:
        logger.warning(
            "geobr not available -- centroid loading failed. "
            "Install with: pip install geobr"
        )
        _centroids_cache = {}
        return {}

    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to load centroids: %s", exc)
        _centroids_cache = {}
        return {}


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_network_distances(
    sih_dir: Path,
    years: range | None = None,
) -> pd.DataFrame:
    """Compute per-municipality-year patient flow distance summaries.

    Reads SIH Parquet files, computes haversine distance between
    residence and treatment municipality centroids, and summarises
    distances per (cod_ibge, year).

    Parameters
    ----------
    sih_dir : Path
        Directory containing SIH Parquet files.
    years : range, optional
        If provided, filter to these years only.

    Returns
    -------
    pd.DataFrame
        Columns: cod_ibge, year, n_procedures, n_self_treated,
        pct_self_treated, mean_distance_km, median_distance_km,
        p90_distance_km, max_distance_km.
    """
    sih_dir = Path(sih_dir)

    logger.info("=" * 60)
    logger.info("NETWORK DISTANCE ANALYSIS (METH-07)")
    logger.info("=" * 60)

    parquet_files = sorted(sih_dir.glob("*.parquet"))
    if not parquet_files:
        logger.warning("No SIH Parquet files found in %s", sih_dir)
        return pd.DataFrame(columns=[
            "cod_ibge", "year", "n_procedures", "n_self_treated",
            "pct_self_treated", "mean_distance_km", "median_distance_km",
            "p90_distance_km", "max_distance_km",
        ])

    logger.info("Found %d SIH Parquet files in %s", len(parquet_files), sih_dir)

    # Load centroids
    centroids = _load_centroids()
    if not centroids:
        logger.warning(
            "No centroids loaded -- distances will all be NaN"
        )

    # ---------------------------------------------------------------------------
    # Read SIH data year-by-year for memory efficiency
    # ---------------------------------------------------------------------------
    all_summaries = []

    for pf in parquet_files:
        try:
            # Read only needed columns for memory efficiency
            df = pd.read_parquet(pf)

            # Identify treatment municipality column
            if "cod_ibge" in df.columns:
                treat_col = "cod_ibge"
            elif "MUNIC_MOV" in df.columns:
                treat_col = "MUNIC_MOV"
            else:
                logger.debug("Skipping %s: no municipality column", pf.name)
                continue

            # Identify residence municipality column
            if "cod_ibge_res" in df.columns:
                res_col = "cod_ibge_res"
            elif "MUNIC_RES" in df.columns:
                res_col = "MUNIC_RES"
            else:
                logger.debug(
                    "Skipping %s: no residence municipality column", pf.name,
                )
                continue

            # Identify year column
            if "year" in df.columns:
                df["_year"] = pd.to_numeric(df["year"], errors="coerce")
            elif "ANO_CMPT" in df.columns:
                df["_year"] = pd.to_numeric(df["ANO_CMPT"], errors="coerce")
            else:
                try:
                    ym = pf.stem.split("_")[-1]
                    df["_year"] = int(ym[:4])
                except (ValueError, IndexError):
                    logger.debug("Cannot determine year for %s", pf.name)
                    continue

            # Filter years
            if years is not None:
                df = df[df["_year"].isin(list(years))]
                if df.empty:
                    continue

            # Normalise municipality codes to 7-char string
            df["_treat"] = df[treat_col].astype(str).str[:7]
            df["_res"] = df[res_col].astype(str).str[:7]

            # Mark self-treated
            df["_self_treated"] = df["_treat"] == df["_res"]

            # Compute haversine distance
            if centroids:
                treat_coords = df["_treat"].map(centroids)
                res_coords = df["_res"].map(centroids)

                # Extract lat/lon (NaN where centroid not found)
                treat_lat = treat_coords.apply(
                    lambda x: x[0] if isinstance(x, tuple) else np.nan
                )
                treat_lon = treat_coords.apply(
                    lambda x: x[1] if isinstance(x, tuple) else np.nan
                )
                res_lat = res_coords.apply(
                    lambda x: x[0] if isinstance(x, tuple) else np.nan
                )
                res_lon = res_coords.apply(
                    lambda x: x[1] if isinstance(x, tuple) else np.nan
                )

                # Vectorised haversine
                valid_mask = (
                    treat_lat.notna() & treat_lon.notna()
                    & res_lat.notna() & res_lon.notna()
                )
                df["_distance_km"] = np.nan
                if valid_mask.any():
                    df.loc[valid_mask, "_distance_km"] = _haversine_km(
                        res_lat[valid_mask].values.astype(float),
                        res_lon[valid_mask].values.astype(float),
                        treat_lat[valid_mask].values.astype(float),
                        treat_lon[valid_mask].values.astype(float),
                    )
            else:
                df["_distance_km"] = np.nan

            # Self-treated patients: distance = 0
            df.loc[df["_self_treated"], "_distance_km"] = 0.0

            # Group by (treatment municipality, year)
            for (cod, yr), grp in df.groupby(["_treat", "_year"], observed=True):
                n_proc = len(grp)
                n_self = int(grp["_self_treated"].sum())
                pct_self = n_self / n_proc * 100.0 if n_proc > 0 else np.nan

                # Referred patients only (excluding self-treated)
                referred = grp[~grp["_self_treated"]]["_distance_km"].dropna()

                if len(referred) > 0:
                    mean_dist = float(np.mean(referred))
                    median_dist = float(np.median(referred))
                    p90_dist = float(np.percentile(referred, 90))
                    max_dist = float(np.max(referred))
                else:
                    mean_dist = np.nan
                    median_dist = np.nan
                    p90_dist = np.nan
                    max_dist = np.nan

                all_summaries.append({
                    "cod_ibge": str(cod),
                    "year": int(yr),
                    "n_procedures": n_proc,
                    "n_self_treated": n_self,
                    "pct_self_treated": pct_self,
                    "mean_distance_km": mean_dist,
                    "median_distance_km": median_dist,
                    "p90_distance_km": p90_dist,
                    "max_distance_km": max_dist,
                })

            logger.info("  Processed %s: %d rows", pf.name, len(df))

        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to process %s: %s", pf, exc)

    if not all_summaries:
        logger.warning("No summaries computed -- check SIH data")
        return pd.DataFrame(columns=[
            "cod_ibge", "year", "n_procedures", "n_self_treated",
            "pct_self_treated", "mean_distance_km", "median_distance_km",
            "p90_distance_km", "max_distance_km",
        ])

    # Aggregate across files (same municipality-year may appear in
    # multiple Parquet files for different states)
    raw_df = pd.DataFrame(all_summaries)

    # If a municipality-year appears multiple times, aggregate
    agg_funcs = {
        "n_procedures": "sum",
        "n_self_treated": "sum",
    }

    # For distance metrics, we need weighted means -- simplify by
    # re-computing from the totals
    result = (
        raw_df
        .groupby(["cod_ibge", "year"], observed=True)
        .agg(agg_funcs)
        .reset_index()
    )

    # Recompute pct_self_treated from totals
    result["pct_self_treated"] = (
        result["n_self_treated"] / result["n_procedures"].replace(0, np.nan) * 100.0
    )

    # For distance columns, take the mean across file-level summaries
    # (approximation when municipality appears in multiple files)
    dist_agg = (
        raw_df
        .groupby(["cod_ibge", "year"], observed=True)
        .agg(
            mean_distance_km=("mean_distance_km", "mean"),
            median_distance_km=("median_distance_km", "mean"),
            p90_distance_km=("p90_distance_km", "mean"),
            max_distance_km=("max_distance_km", "max"),
        )
        .reset_index()
    )

    result = result.merge(dist_agg, on=["cod_ibge", "year"], how="left")

    logger.info(
        "Network distances computed: %d municipality-year rows, "
        "overall mean pct_self_treated=%.1f%%",
        len(result),
        result["pct_self_treated"].mean() if len(result) > 0 else 0,
    )

    return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Compute network distance metrics from SIH patient flow data.

    Usage
    -----
        python analysis/network_distances.py \\
            --sih-dir data_sources/processed/sih \\
            --out-dir results
    """
    parser = argparse.ArgumentParser(
        description="ICSKG-BR network distance analysis (METH-07)",
    )
    parser.add_argument(
        "--sih-dir",
        default=str(PROCESSED_SIH_DIR),
        help="Directory with SIH Parquet files (default: %s)" % PROCESSED_SIH_DIR,
    )
    parser.add_argument(
        "--out-dir",
        default="results",
        help="Output directory (default: results)",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Optional SQLite database path to persist results",
    )
    parser.add_argument(
        "--start-year", type=int, default=2015,
        help="First year to process (default: 2015)",
    )
    parser.add_argument(
        "--end-year", type=int, default=2023,
        help="Last year to process inclusive (default: 2023)",
    )
    args = parser.parse_args(argv)

    sih_dir = Path(args.sih_dir)
    out_dir = Path(args.out_dir)
    years = range(args.start_year, args.end_year + 1)

    # ---------------------------------------------------------------
    # Compute network distances
    # ---------------------------------------------------------------
    result = compute_network_distances(sih_dir, years=years)

    if result.empty:
        logger.warning("No network distances computed -- check SIH data")
        return 1

    # ---------------------------------------------------------------
    # Save outputs
    # ---------------------------------------------------------------
    tables_dir = out_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    csv_path = tables_dir / "network_distances.csv"
    result.to_csv(csv_path, index=False)
    logger.info("Saved network distances: %s (%d rows)", csv_path, len(result))

    # Optional: persist to SQLite
    if args.db_path:
        db_path = Path(args.db_path)
        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            try:
                result.to_sql(
                    "network_distance_metrics",
                    conn,
                    if_exists="replace",
                    index=False,
                )
                logger.info(
                    "Persisted %d rows to network_distance_metrics table",
                    len(result),
                )
            finally:
                conn.close()
        else:
            logger.warning("Database not found: %s -- skipping SQLite", db_path)

    # ---------------------------------------------------------------
    # Log summary
    # ---------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("NETWORK DISTANCE SUMMARY")
    logger.info("=" * 60)
    logger.info("  Municipalities covered: %d", result["cod_ibge"].nunique())
    logger.info("  Years covered: %d", result["year"].nunique())
    logger.info(
        "  Overall mean pct_self_treated: %.1f%%",
        result["pct_self_treated"].mean(),
    )
    referred_mask = result["mean_distance_km"].notna()
    if referred_mask.any():
        logger.info(
            "  Overall mean referral distance: %.1f km",
            result.loc[referred_mask, "mean_distance_km"].mean(),
        )
    logger.info("Network distance analysis complete.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
