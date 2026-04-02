"""
ICSKG-BR Publication Figures
==============================
Generates all publication-ready figures for BMJ Global Health submission.

Produces 4+ figures at 300 DPI with colorblind-safe palettes:
  Fig 1: CUDS choropleth map (delegated to spatial_analysis.py)
  Fig 2: CUDS temporal trend by region (new)
  Fig 3: LCoGS regional heatmaps (delegated to spatial_analysis.py)
  Fig 4: Regression forest plot with 95% CIs (new)

Usage
-----
    python analysis/publication_figures.py \\
        --db-path database/icskg_br.sqlite \\
        --out-dir results

Exports
-------
    generate_cuds_temporal_trend(db_path, out_dir) -> Path
    generate_regression_forest_plot(db_path, out_dir) -> Path
    generate_all_figures(db_path, out_dir) -> list[Path]
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

REGION_ORDER = ["Norte", "Nordeste", "Centro-Oeste", "Sudeste", "Sul"]

# Colorblind-safe qualitative palette (Set2 subset for 5 regions)
REGION_COLORS = {
    "Norte": "#66c2a5",
    "Nordeste": "#fc8d62",
    "Centro-Oeste": "#8da0cb",
    "Sudeste": "#e78ac3",
    "Sul": "#a6d854",
}

DPI = 300


# ---------------------------------------------------------------------------
# Matplotlib context manager
# ---------------------------------------------------------------------------

def _mpl_context():
    """Return a SciencePlots context manager if available, else default."""
    try:
        import scienceplots  # noqa: PLC0415, F401
        import matplotlib.pyplot as plt  # noqa: PLC0415
        return plt.style.context(["science", "no-latex"])
    except Exception:  # noqa: BLE001
        import matplotlib.pyplot as plt  # noqa: PLC0415
        return plt.style.context("default")


# ---------------------------------------------------------------------------
# Fig 2: CUDS temporal trend by region
# ---------------------------------------------------------------------------

def generate_cuds_temporal_trend(
    db_path: Path,
    out_dir: Path,
) -> Path:
    """Generate CUDS temporal trend line plot by macro-region.

    Loads dimension_scores and municipality_lookup from SQLite,
    groups by (year, region), computes mean CUDS with 95% CI per
    region per year, and produces a line plot with 5 lines (one per
    macro-region) and shaded CI bands.

    Parameters
    ----------
    db_path : Path
        Path to SQLite database.
    out_dir : Path
        Root output directory (results/).

    Returns
    -------
    Path
        Path to the saved PNG file.
    """
    import matplotlib  # noqa: PLC0415
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: PLC0415
    from analysis.reporting import mean_ci  # noqa: PLC0415

    db_path = Path(db_path)
    out_dir = Path(out_dir)
    figures_dir = out_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    # --- Load data ---
    conn = sqlite3.connect(str(db_path))
    try:
        dims = pd.read_sql(
            "SELECT cod_ibge, year, cuds FROM dimension_scores", conn,
        )
        lookup = pd.read_sql(
            "SELECT cod_ibge, region FROM municipality_lookup", conn,
        )
    finally:
        conn.close()

    dims["cod_ibge"] = dims["cod_ibge"].astype(str)
    dims["year"] = dims["year"].astype(int)
    lookup["cod_ibge"] = lookup["cod_ibge"].astype(str)

    panel = dims.merge(lookup, on="cod_ibge", how="inner")

    # --- Compute per-region per-year stats ---
    rows = []
    for region in REGION_ORDER:
        region_data = panel[panel["region"] == region]
        for year in sorted(region_data["year"].unique()):
            year_data = region_data[region_data["year"] == year]
            ci = mean_ci(year_data["cuds"].dropna().values)
            rows.append({
                "region": region,
                "year": year,
                "mean": ci["mean"],
                "ci_lower": ci["ci_lower"],
                "ci_upper": ci["ci_upper"],
                "n": ci["n"],
            })

    stats_df = pd.DataFrame(rows)

    if stats_df.empty:
        logger.warning(
            "generate_cuds_temporal_trend: no data -- skipping figure"
        )
        out_path = figures_dir / "cuds_temporal_trend.png"
        return out_path

    # --- Plot ---
    with _mpl_context():
        fig, ax = plt.subplots(figsize=(10, 6))

        for region in REGION_ORDER:
            rdata = stats_df[stats_df["region"] == region].sort_values("year")
            if rdata.empty:
                continue

            color = REGION_COLORS[region]
            ax.plot(
                rdata["year"], rdata["mean"],
                marker="o", markersize=5,
                label=region, color=color,
                linewidth=1.8,
            )
            ax.fill_between(
                rdata["year"],
                rdata["ci_lower"],
                rdata["ci_upper"],
                alpha=0.2, color=color,
            )

        ax.set_xlabel("Year")
        ax.set_ylabel("Mean CUDS")
        ax.set_title(
            "Composite Urban Development Score (CUDS) by Region, 2015-2023"
        )
        ax.set_xlim(2014.5, 2023.5)
        ax.set_ylim(0, 1)
        ax.legend(loc="best", frameon=True)
        ax.grid(True, alpha=0.3)
        fig.tight_layout()

        out_path = figures_dir / "cuds_temporal_trend.png"
        fig.savefig(str(out_path), dpi=DPI, bbox_inches="tight")
        plt.close(fig)

    logger.info(
        "generate_cuds_temporal_trend: saved %s (%d DPI)", out_path, DPI,
    )
    return out_path


# ---------------------------------------------------------------------------
# Fig 4: Regression forest plot
# ---------------------------------------------------------------------------

def generate_regression_forest_plot(
    db_path: Path,
    out_dir: Path,
) -> Path:
    """Generate a horizontal forest plot of PanelOLS CUDS coefficients.

    Runs 6 panel regressions (CUDS -> each LCoGS outcome), extracts
    the CUDS coefficient with 95% CI and p-value, and produces a
    horizontal forest plot with one row per LCoGS outcome.

    Parameters
    ----------
    db_path : Path
        Path to SQLite database.
    out_dir : Path
        Root output directory (results/).

    Returns
    -------
    Path
        Path to the saved PNG file.
    """
    import matplotlib  # noqa: PLC0415
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: PLC0415
    from analysis.run_regressions import (  # noqa: PLC0415
        LCOGS_OUTCOMES,
        load_regression_panel,
        run_panel_regressions,
    )

    db_path = Path(db_path)
    out_dir = Path(out_dir)
    figures_dir = out_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    # --- Run regressions ---
    panel = load_regression_panel(db_path)
    results = run_panel_regressions(panel)

    # --- Extract coefficients ---
    outcome_labels = []
    coefficients = []
    ci_lowers = []
    ci_uppers = []
    p_values = []

    for outcome_col, outcome_label in LCOGS_OUTCOMES:
        if outcome_col not in results:
            continue

        res = results[outcome_col]
        if "cuds" not in res.params.index:
            continue

        coef = float(res.params["cuds"])
        conf = res.conf_int()
        cuds_idx = list(res.params.index).index("cuds")
        ci_lo = float(conf.iloc[cuds_idx, 0])
        ci_hi = float(conf.iloc[cuds_idx, 1])
        pval = float(res.pvalues["cuds"])

        outcome_labels.append(outcome_label)
        coefficients.append(coef)
        ci_lowers.append(ci_lo)
        ci_uppers.append(ci_hi)
        p_values.append(pval)

    if not outcome_labels:
        logger.warning(
            "generate_regression_forest_plot: no regression results "
            "-- skipping figure"
        )
        out_path = figures_dir / "regression_forest_plot.png"
        return out_path

    # --- Significance annotation ---
    def _sig_stars(p: float) -> str:
        if p < 0.001:
            return " ***"
        if p < 0.01:
            return " **"
        if p < 0.05:
            return " *"
        return ""

    # --- Plot ---
    with _mpl_context():
        n = len(outcome_labels)
        fig, ax = plt.subplots(figsize=(10, max(4, n * 0.8 + 1)))

        y_pos = np.arange(n)

        # Error bars (CI)
        xerr_lower = [c - lo for c, lo in zip(coefficients, ci_lowers)]
        xerr_upper = [hi - c for c, hi in zip(coefficients, ci_uppers)]

        ax.errorbar(
            coefficients, y_pos,
            xerr=[xerr_lower, xerr_upper],
            fmt="o", color="#2c7fb8",
            ecolor="#636363", elinewidth=1.5,
            capsize=4, capthick=1.5,
            markersize=8, zorder=5,
        )

        # Vertical dashed line at x=0 (null effect)
        ax.axvline(x=0, color="gray", linestyle="--", linewidth=1, zorder=1)

        # Labels with significance stars
        labels_with_sig = [
            "%s%s" % (lbl, _sig_stars(p))
            for lbl, p in zip(outcome_labels, p_values)
        ]
        ax.set_yticks(y_pos)
        ax.set_yticklabels(labels_with_sig)

        ax.set_xlabel("CUDS Coefficient (95% CI)")
        ax.set_title(
            "Effect of CUDS on LCoGS Indicators "
            "(PanelOLS, Two-Way FE, Cluster-Robust SE)"
        )
        ax.invert_yaxis()
        ax.grid(True, axis="x", alpha=0.3)
        fig.tight_layout()

        out_path = figures_dir / "regression_forest_plot.png"
        fig.savefig(str(out_path), dpi=DPI, bbox_inches="tight")
        plt.close(fig)

    logger.info(
        "generate_regression_forest_plot: saved %s (%d DPI, %d outcomes)",
        out_path, DPI, n,
    )
    return out_path


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def generate_all_figures(
    db_path: Path,
    out_dir: Path,
) -> list[Path]:
    """Generate all publication-ready figures.

    Calls both existing spatial_analysis generators (choropleth,
    heatmaps) and the two new generators (temporal trend, forest plot).

    Parameters
    ----------
    db_path : Path
        Path to SQLite database.
    out_dir : Path
        Root output directory (results/).

    Returns
    -------
    list[Path]
        Paths to all generated figure files.
    """
    from analysis.spatial_analysis import (  # noqa: PLC0415
        generate_cuds_choropleth,
        generate_lcogs_heatmaps,
    )

    db_path = Path(db_path)
    out_dir = Path(out_dir)
    paths: list[Path] = []

    logger.info("=" * 60)
    logger.info("PUBLICATION FIGURES")
    logger.info("=" * 60)

    # --- Fig 1: CUDS choropleth (existing) ---
    logger.info("─" * 60)
    logger.info("Fig 1: CUDS choropleth map")
    logger.info("─" * 60)
    try:
        p = generate_cuds_choropleth(db_path, out_dir)
        paths.append(p)
        logger.info("  Fig 1 saved: %s", p)
    except Exception as exc:  # noqa: BLE001
        logger.error("  Fig 1 failed: %s", exc)

    # --- Fig 2: CUDS temporal trend (new) ---
    logger.info("─" * 60)
    logger.info("Fig 2: CUDS temporal trend by region")
    logger.info("─" * 60)
    try:
        p = generate_cuds_temporal_trend(db_path, out_dir)
        paths.append(p)
        logger.info("  Fig 2 saved: %s", p)
    except Exception as exc:  # noqa: BLE001
        logger.error("  Fig 2 failed: %s", exc)

    # --- Fig 3: LCoGS heatmaps (existing) ---
    logger.info("─" * 60)
    logger.info("Fig 3: LCoGS regional heatmaps")
    logger.info("─" * 60)
    try:
        heatmap_paths = generate_lcogs_heatmaps(db_path, out_dir)
        paths.extend(heatmap_paths)
        logger.info("  Fig 3: %d heatmaps saved", len(heatmap_paths))
    except Exception as exc:  # noqa: BLE001
        logger.error("  Fig 3 failed: %s", exc)

    # --- Fig 4: Regression forest plot (new) ---
    logger.info("─" * 60)
    logger.info("Fig 4: Regression forest plot")
    logger.info("─" * 60)
    try:
        p = generate_regression_forest_plot(db_path, out_dir)
        paths.append(p)
        logger.info("  Fig 4 saved: %s", p)
    except Exception as exc:  # noqa: BLE001
        logger.error("  Fig 4 failed: %s", exc)

    logger.info("=" * 60)
    logger.info("PUBLICATION FIGURES COMPLETE: %d files", len(paths))
    for p in paths:
        logger.info("  %s", p)
    logger.info("=" * 60)

    return paths


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Generate all publication-ready figures.

    Usage
    -----
        python analysis/publication_figures.py \\
            --db-path database/icskg_br.sqlite \\
            --out-dir results
    """
    parser = argparse.ArgumentParser(
        description="ICSKG-BR publication figure generator",
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
    args = parser.parse_args(argv)

    db_path = Path(args.db_path)
    out_dir = Path(args.out_dir)

    paths = generate_all_figures(db_path, out_dir)

    if not paths:
        logger.error("No figures were generated")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
