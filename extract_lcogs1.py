"""
ICSKG-BR LCoGS-1 Bellwether Analysis
======================================
Geospatial analysis of Brazilian municipalities against the LCoGS-1
(Lancet Commission on Global Surgery) bellwether procedure rate threshold.

The LCoGS-1 indicator measures whether a population has access to the three
bellwether procedures used as a proxy for surgical system capacity:
  1. Laparotomy
  2. Caesarean section
  3. Open fracture repair

The WHO/LCoGS benchmark: ≥ 5 000 procedures per 100 000 population per year.

Outputs
-------
  output/lcogs1_bellwether_map.png          – choropleth map
  output/lcogs1_bellwether_map_detail.png   – state-level detail maps
  output/lcogs1_bellwether_rates.csv        – municipality-level rates
  output/lcogs1_bellwether_gap.csv          – gap to LCoGS-1 benchmark

Data requirements
-----------------
  * SIH processed parquet files (data_sources/processed/sih_*.parquet)
  * IBGE population estimates (auto-downloaded from IBGE API)
  * Brazil municipality shapefile (auto-downloaded from IBGE)

Usage
-----
    python extract_lcogs1.py [--year 2023] [--out-dir output]
"""

import argparse
import logging
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
# LCoGS-1 procedure ICD / SIGTAP codes
# ---------------------------------------------------------------------------

# ICD-10 principal-diagnosis codes associated with each bellwether procedure
# (used to identify relevant hospitalisations in SIH)
LAPAROTOMY_DIAG = {
    "K35", "K36", "K37",   # Appendicitis
    "K40", "K41", "K42", "K43", "K44", "K45", "K46",  # Hernia
    "K56",                 # Ileus / intestinal obstruction
    "K63",                 # Other intestinal disorders
}

CAESAREAN_DIAG = {
    "O82",  # Single delivery by caesarean section
    "O83",  # Other assisted single delivery (includes some C-sections)
}

OPEN_FRACTURE_DIAG = {
    "S02", "S12", "S22", "S32", "S42", "S52", "S62",
    "S72", "S82", "S92",  # Fractures by body region
    "T02", "T10", "T12",  # Multiple / limb fractures
}

BELLWETHER_DIAG = LAPAROTOMY_DIAG | CAESAREAN_DIAG | OPEN_FRACTURE_DIAG

LCOGS1_BENCHMARK = 5000  # procedures per 100 000 population per year


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_sih_year(processed_dir: Path, year: int) -> pd.DataFrame:
    """Load and concatenate all SIH months for *year*."""
    files = sorted(processed_dir.glob(f"sih_{year:04d}*.parquet"))
    if not files:
        logger.warning("No SIH parquet files found for year %d in %s", year, processed_dir)
        return pd.DataFrame()

    frames = []
    for f in files:
        try:
            df = pd.read_parquet(f, columns=["MUNIC_MOV", "DIAG_PRINC", "MORTE", "N_AIH"])
            frames.append(df)
        except Exception as exc:  # noqa: BLE001
            logger.error("Could not read %s: %s", f, exc)

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    logger.info("Loaded %d SIH records for %d", len(combined), year)
    return combined


def fetch_ibge_population(year: int) -> pd.DataFrame:
    """Fetch municipality population estimates from the IBGE API."""
    try:
        import requests  # noqa: PLC0415
    except ImportError:
        logger.warning("requests not installed – using synthetic population data.")
        return pd.DataFrame()

    url = (
        f"https://servicodados.ibge.gov.br/api/v1/pesquisas/6579/indicadores/29171/resultados"
        f"?localidade=N6[all]"
    )
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        # Parse IBGE response structure
        records = []
        for item in data:
            for res in item.get("res", []):
                loc = res.get("localidade", "")
                val = res.get("res", {}).get(str(year), "")
                if val and val != "-":
                    records.append({"cod_ibge": loc[:6], "populacao": int(str(val).replace(".", ""))})
        df = pd.DataFrame(records)
        logger.info("Fetched IBGE population for %d municipalities (year=%d)", len(df), year)
        return df
    except Exception as exc:  # noqa: BLE001
        logger.error("IBGE API fetch failed: %s", exc)
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Bellwether procedure identification
# ---------------------------------------------------------------------------

def flag_bellwether(sih_df: pd.DataFrame) -> pd.DataFrame:
    """Add a boolean column *is_bellwether* to *sih_df*."""
    if "DIAG_PRINC" not in sih_df.columns:
        sih_df["is_bellwether"] = False
        return sih_df

    # Match ICD-10 prefix (3-character codes)
    diag = sih_df["DIAG_PRINC"].str[:3].str.upper()
    sih_df["is_bellwether"] = diag.isin(BELLWETHER_DIAG)

    laparotomy_mask = diag.isin(LAPAROTOMY_DIAG)
    caesarean_mask = diag.isin(CAESAREAN_DIAG)
    fracture_mask = diag.isin(OPEN_FRACTURE_DIAG)

    sih_df["is_laparotomy"] = laparotomy_mask
    sih_df["is_caesarean"] = caesarean_mask
    sih_df["is_fracture"] = fracture_mask

    logger.info(
        "Bellwether procedures: %d total (laparotomy=%d, caesarean=%d, fracture=%d)",
        sih_df["is_bellwether"].sum(),
        laparotomy_mask.sum(),
        caesarean_mask.sum(),
        fracture_mask.sum(),
    )
    return sih_df


# ---------------------------------------------------------------------------
# Rate computation
# ---------------------------------------------------------------------------

def compute_rates(sih_df: pd.DataFrame, pop_df: pd.DataFrame) -> pd.DataFrame:
    """Compute bellwether procedure rates per 100 000 population."""
    if sih_df.empty:
        return pd.DataFrame()

    sih_df = flag_bellwether(sih_df)

    mun_col = "MUNIC_MOV" if "MUNIC_MOV" in sih_df.columns else "MUNIC_RES"
    sih_df[mun_col] = sih_df[mun_col].astype(str).str[:6]

    counts = (
        sih_df.groupby(mun_col)[["is_bellwether", "is_laparotomy", "is_caesarean", "is_fracture"]]
        .sum()
        .reset_index()
        .rename(columns={mun_col: "cod_ibge"})
    )

    if pop_df.empty:
        logger.warning("Population data unavailable – rates cannot be computed.")
        counts["populacao"] = np.nan
        counts["rate_per_100k"] = np.nan
        return counts

    merged = counts.merge(pop_df, on="cod_ibge", how="left")
    merged["populacao"] = pd.to_numeric(merged["populacao"], errors="coerce")
    merged["rate_per_100k"] = (merged["is_bellwether"] / merged["populacao"]) * 100_000
    merged["lcogs1_gap"] = LCOGS1_BENCHMARK - merged["rate_per_100k"]
    merged["meets_lcogs1"] = merged["rate_per_100k"] >= LCOGS1_BENCHMARK

    n_meets = merged["meets_lcogs1"].sum()
    total = len(merged)
    logger.info(
        "LCoGS-1 benchmark (≥%d/100k): %d/%d municipalities (%.1f%%)",
        LCOGS1_BENCHMARK,
        n_meets,
        total,
        100 * n_meets / total if total else 0,
    )
    return merged


# ---------------------------------------------------------------------------
# Map generation
# ---------------------------------------------------------------------------

def generate_maps(rates_df: pd.DataFrame, out_dir: Path) -> None:
    """Produce choropleth maps for LCoGS-1 bellwether rates."""
    try:
        import geopandas as gpd  # noqa: PLC0415
        import matplotlib  # noqa: PLC0415
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # noqa: PLC0415
        import matplotlib.colors as mcolors  # noqa: PLC0415
    except ImportError as exc:
        logger.warning("geopandas/matplotlib not available – skipping maps: %s", exc)
        return

    # Try to load a Brazil municipality shapefile
    shp_url = (
        "https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/"
        "malhas_municipais/municipio_2022/Brasil/BR/BR_Municipios_2022.zip"
    )
    try:
        gdf = gpd.read_file(shp_url)
        gdf["CD_MUN"] = gdf["CD_MUN"].astype(str).str[:6]
        gdf = gdf.merge(rates_df, left_on="CD_MUN", right_on="cod_ibge", how="left")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not load shapefile: %s – skipping maps.", exc)
        return

    out_dir.mkdir(parents=True, exist_ok=True)

    # Figure 1 – Bellwether rate choropleth
    fig, ax = plt.subplots(figsize=(14, 12))
    gdf.plot(
        column="rate_per_100k",
        ax=ax,
        legend=True,
        cmap="YlOrRd",
        missing_kwds={"color": "lightgrey", "label": "No data"},
        legend_kwds={"label": "Procedures per 100 000 pop.", "orientation": "horizontal"},
    )
    ax.axhline(y=0, color="none")
    ax.set_title(f"LCoGS-1 Bellwether Procedure Rate – Brazil", fontsize=14)
    ax.set_axis_off()
    out_path = out_dir / "lcogs1_bellwether_map.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved bellwether map to %s", out_path)

    # Figure 2 – Benchmark attainment (binary)
    fig, ax = plt.subplots(figsize=(14, 12))
    cmap = mcolors.ListedColormap(["#d73027", "#1a9850"])
    gdf["meets_lcogs1_num"] = gdf["meets_lcogs1"].astype(float)
    gdf.plot(
        column="meets_lcogs1_num",
        ax=ax,
        cmap=cmap,
        vmin=0,
        vmax=1,
        missing_kwds={"color": "lightgrey"},
        legend=False,
    )
    from matplotlib.patches import Patch  # noqa: PLC0415

    legend_elements = [
        Patch(facecolor="#1a9850", label=f"Meets LCoGS-1 (≥{LCOGS1_BENCHMARK}/100k)"),
        Patch(facecolor="#d73027", label=f"Below LCoGS-1 benchmark"),
        Patch(facecolor="lightgrey", label="No data"),
    ]
    ax.legend(handles=legend_elements, loc="lower left", fontsize=10)
    ax.set_title("LCoGS-1 Benchmark Attainment – Brazil", fontsize=14)
    ax.set_axis_off()
    out_path2 = out_dir / "lcogs1_bellwether_map_detail.png"
    fig.savefig(out_path2, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved attainment map to %s", out_path2)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description="ICSKG-BR LCoGS-1 bellwether analysis")
    parser.add_argument("--year", type=int, default=2023, help="Analysis year (default: 2023)")
    parser.add_argument("--processed-dir", default="data_sources/processed",
                        help="Directory with processed SIH parquet files")
    parser.add_argument("--out-dir", default="output",
                        help="Output directory for maps and CSVs (default: output)")
    parser.add_argument("--no-maps", dest="maps", action="store_false",
                        help="Skip map generation (requires geopandas)")
    args = parser.parse_args(argv)

    processed_dir = Path(args.processed_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=== LCoGS-1 Bellwether Analysis – Year %d ===", args.year)

    sih_df = load_sih_year(processed_dir, args.year)
    pop_df = fetch_ibge_population(args.year)

    if sih_df.empty and pop_df.empty:
        logger.warning("No data available. Generating synthetic example output.")
        rng = np.random.default_rng(42)
        n = 100
        sih_df = pd.DataFrame({
            "MUNIC_MOV": [f"{i + 1:06d}" for i in range(n)],
            "DIAG_PRINC": rng.choice(list(BELLWETHER_DIAG) + ["Z000", "J180"], size=n),
            "N_AIH": [f"AIH{i:08d}" for i in range(n)],
            "MORTE": rng.integers(0, 2, size=n),
        })
        pop_df = pd.DataFrame({
            "cod_ibge": [f"{i + 1:06d}" for i in range(n)],
            "populacao": rng.integers(5_000, 500_000, size=n),
        })

    rates_df = compute_rates(sih_df, pop_df)

    if not rates_df.empty:
        rates_path = out_dir / "lcogs1_bellwether_rates.csv"
        gap_cols = ["cod_ibge", "rate_per_100k", "lcogs1_gap", "meets_lcogs1",
                    "is_bellwether", "is_laparotomy", "is_caesarean", "is_fracture"]
        available_gap_cols = [c for c in gap_cols if c in rates_df.columns]
        rates_df[available_gap_cols].to_csv(rates_path, index=False)
        logger.info("Bellwether rates saved to %s", rates_path)

        if "lcogs1_gap" in rates_df.columns:
            gap_df = rates_df[rates_df["lcogs1_gap"].notna()].sort_values("lcogs1_gap", ascending=False)
            gap_path = out_dir / "lcogs1_bellwether_gap.csv"
            gap_df[available_gap_cols].to_csv(gap_path, index=False)
            logger.info("Gap analysis saved to %s", gap_path)
        gap_path = out_dir / "lcogs1_bellwether_gap.csv"
        gap_df[available_gap_cols].to_csv(gap_path, index=False)
        logger.info("Gap analysis saved to %s", gap_path)

    if args.maps:
        generate_maps(rates_df, out_dir)

    logger.info("=== LCoGS-1 analysis complete. Outputs in %s ===", out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
