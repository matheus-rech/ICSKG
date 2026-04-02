"""
ICSKG-BR Panel Assembly Orchestrator
======================================
Merges all 11 extracted data sources into a validated municipality-year panel.

The assembly follows a scaffold-first strategy:
  1. Build a scaffold of (cod_ibge, year) from the authoritative IBGE reference
  2. Load each source, validate via validate_dataframe(), quarantine bad rows
  3. Deflate monetary columns (GDP per capita, health expenditure) to 2023 BRL
  4. Left-merge each validated source onto the scaffold
  5. Assert row-count invariant: exactly 5,571 rows per year

Cross-sectional sources (IDHM 2010, Census 2022 sanitation) are replicated
across all panel years. Empty/unavailable sources are gracefully skipped.

Exports
-------
    build_panel_scaffold(years) -> pd.DataFrame
    load_source(name, path, years, ...) -> pd.DataFrame
    assemble_panel(processed_dir, years, quarantine_dir) -> tuple[pd.DataFrame, list]

Usage
-----
    from database.assemble_panel import assemble_panel, build_panel_scaffold

    panel, reports = assemble_panel(
        processed_dir=Path("data_sources/processed"),
        years=range(2015, 2024),
    )
"""

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from database.utils import (
    load_ibge_municipios,
    normalize_cod_ibge,
    rename_municipality_column,
)
from database.validation import (
    ValidationReport,
    validate_dataframe,
    write_validation_report,
)
from scripts.build_amc_crosswalk import apply_amc_crosswalk

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


# ---------------------------------------------------------------------------
# Constants — source catalog
# ---------------------------------------------------------------------------

# Maps source_name -> (relative_path_under_processed, value_columns, is_crosssectional, is_monetary_cols)
# is_monetary_cols lists columns that need IPCA deflation
SOURCE_CATALOG: dict[str, dict[str, Any]] = {
    "sih": {
        "path": "sih",
        "glob": "*.parquet",
        "value_cols": [
            "procedure_count", "total_value", "deaths",
            "aih_count", "total_days",
        ],
        "is_crosssectional": False,
        "monetary_cols": ["total_value"],
    },
    "cnes_facilities": {
        "path": "cnes",
        "glob": "facilities_*.parquet",
        "value_cols": ["total_beds", "is_bellwether"],
        "is_crosssectional": False,
        "monetary_cols": [],
    },
    "cnes_professionals": {
        "path": "cnes",
        "glob": "professionals_*.parquet",
        "value_cols": ["sao_category"],
        "is_crosssectional": False,
        "monetary_cols": [],
    },
    "population": {
        "path": "ibge_sidra",
        "glob": "population.parquet",
        "value_cols": ["populacao"],
        "is_crosssectional": False,
        "monetary_cols": [],
    },
    "gdp_per_capita": {
        "path": "ibge_sidra",
        "glob": "gdp_per_capita.parquet",
        "value_cols": ["gdp_abs", "gdp_estimated", "gdp_per_capita"],
        "is_crosssectional": False,
        "monetary_cols": ["gdp_per_capita"],
    },
    "idhm": {
        "path": "ipea_idhm",
        "glob": "idhm.parquet",
        "value_cols": ["idhm", "idhm_educacao", "idhm_longevidade", "idhm_renda"],
        "is_crosssectional": True,
        "monetary_cols": [],
    },
    "ifgf": {
        "path": "ifgf",
        "glob": "ifgf.parquet",
        "value_cols": [
            "ifgf_geral", "ifgf_ra", "ifgf_gp", "ifgf_id", "ifgf_el", "ifgf_sa",
        ],
        "is_crosssectional": False,
        "monetary_cols": [],
    },
    "ans": {
        "path": "ans",
        "glob": "ans_quarterly.parquet",
        "value_cols": [
            "beneficiarios_mean", "private_coverage_rate", "sus_dependence_rate",
        ],
        "is_crosssectional": False,
        "monetary_cols": [],
    },
    "census_sanitation": {
        "path": "census_sanitation",
        "glob": "sanitation.parquet",
        "value_cols": ["pct_sanitation_adequate", "pct_water_adequate"],
        "is_crosssectional": True,
        "monetary_cols": [],
    },
    "renavam": {
        "path": "renavam",
        "glob": "renavam.parquet",
        "value_cols": ["vehicles_total", "vehicles_per_1000"],
        "is_crosssectional": False,
        "monetary_cols": [],
    },
    "siops": {
        "path": "siops",
        "glob": "siops.parquet",
        "value_cols": ["health_expenditure_per_capita"],
        "is_crosssectional": False,
        "monetary_cols": ["health_expenditure_per_capita"],
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_panel_scaffold(years: range | list[int]) -> pd.DataFrame:
    """Build the authoritative (cod_ibge, year) scaffold for the panel.

    Loads the IBGE 2023 municipality reference and creates one row per
    municipality per year. This scaffold is the merge target -- every
    source left-joins onto it, preserving completeness.

    Parameters
    ----------
    years : range or list[int]
        Years to include (e.g., range(2015, 2024) for 2015-2023).

    Returns
    -------
    pd.DataFrame
        Columns: [cod_ibge, year]. Row count = len(ref) * len(years).
    """
    ref = load_ibge_municipios()
    years_list = list(years)
    n_munic = len(ref)

    frames = []
    for year in years_list:
        year_df = ref[["cod_ibge"]].copy()
        year_df["year"] = year
        frames.append(year_df)

    scaffold = pd.concat(frames, ignore_index=True)

    expected = n_munic * len(years_list)
    assert len(scaffold) == expected, (
        "Scaffold row count mismatch: got %d, expected %d "
        "(%d municipalities x %d years)"
        % (len(scaffold), expected, n_munic, len(years_list))
    )

    logger.info(
        "build_panel_scaffold: %d rows (%d municipalities x %d years)",
        len(scaffold), n_munic, len(years_list),
    )
    return scaffold


def load_source(
    name: str,
    path: Path,
    years: list[int],
    is_crosssectional: bool = False,
) -> pd.DataFrame:
    """Load and prepare a single data source for panel merge.

    Reads the Parquet file, normalizes municipality codes, applies the AMC
    crosswalk for temporal harmonization, and optionally replicates
    cross-sectional data across all panel years.

    Parameters
    ----------
    name : str
        Source identifier (e.g., "sih", "idhm").
    path : Path
        Path to the Parquet file.
    years : list[int]
        Panel years for cross-sectional replication.
    is_crosssectional : bool
        If True, replicate the single-year data across all panel years.

    Returns
    -------
    pd.DataFrame
        Validated-ready DataFrame with [cod_ibge, year, ...value_cols].
        Returns empty DataFrame if source is missing or empty.
    """
    # Handle missing file
    if not path.exists():
        logger.warning(
            "load_source('%s'): file not found at %s -- returning empty DataFrame",
            name, path,
        )
        return pd.DataFrame()

    # Read Parquet
    try:
        df = pd.read_parquet(path)
    except Exception as exc:  # noqa: BLE001
        logger.error("load_source('%s'): failed to read %s: %s", name, path, exc)
        return pd.DataFrame()

    # Check if empty
    if len(df) == 0:
        logger.warning(
            "load_source('%s'): file is empty at %s -- returning empty DataFrame",
            name, path,
        )
        return pd.DataFrame()

    # Normalize municipality column
    try:
        df = rename_municipality_column(df)
    except ValueError:
        logger.warning(
            "load_source('%s'): no municipality code column found -- skipping",
            name,
        )
        return pd.DataFrame()

    df["cod_ibge"] = normalize_cod_ibge(df["cod_ibge"])

    # Cross-sectional replication: replicate single-year rows across all panel years
    if is_crosssectional:
        logger.info(
            "load_source('%s'): cross-sectional source -- replicating across %d years",
            name, len(years),
        )
        non_year_cols = [c for c in df.columns if c != "year"]
        base = df[non_year_cols].drop_duplicates(subset=["cod_ibge"])
        frames = []
        for year in years:
            year_df = base.copy()
            year_df["year"] = year
            frames.append(year_df)
        df = pd.concat(frames, ignore_index=True)
    else:
        # Apply AMC crosswalk for temporal harmonization (per year)
        if "year" in df.columns:
            unique_years = df["year"].unique()
            harmonized_frames = []
            for yr in unique_years:
                yr_df = df[df["year"] == yr].copy()
                try:
                    yr_df = apply_amc_crosswalk(yr_df, year=int(yr))
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "load_source('%s'): AMC crosswalk failed for year %s: %s",
                        name, yr, exc,
                    )
                harmonized_frames.append(yr_df)
            df = pd.concat(harmonized_frames, ignore_index=True)

    # Check value columns have at least some non-NaN
    value_cols = [c for c in df.columns if c not in ("cod_ibge", "year")]
    if value_cols:
        non_null_counts = df[value_cols].notna().sum().sum()
        if non_null_counts == 0:
            logger.warning(
                "load_source('%s'): all value columns are NaN -- skipping",
                name,
            )
            return pd.DataFrame()

    logger.info(
        "load_source('%s'): loaded %d rows, %d value columns",
        name, len(df), len(value_cols),
    )
    return df


def assemble_panel(
    processed_dir: Path = Path("data_sources/processed"),
    years: range | list[int] = range(2015, 2024),
    quarantine_dir: Path = Path("data_sources/quarantine"),
) -> tuple[pd.DataFrame, list[ValidationReport]]:
    """Assemble the full municipality-year panel from all extracted sources.

    Implements the scaffold-first merge strategy:
      1. Build scaffold from IBGE reference x years
      2. For each source: load -> validate -> deflate monetary cols -> left merge
      3. Assert row-count invariant per year
      4. Write validation_report.json

    Parameters
    ----------
    processed_dir : Path
        Root directory containing processed source Parquet files.
    years : range or list[int]
        Panel years (default: 2015-2023).
    quarantine_dir : Path
        Directory for quarantined rows (default: data_sources/quarantine/).

    Returns
    -------
    tuple[pd.DataFrame, list[ValidationReport]]
        panel : The assembled panel DataFrame.
        reports : Per-source ValidationReport list.
    """
    from database.deflate_ipca import (  # noqa: PLC0415
        fetch_ipca_annual_index,
        deflate_column,
    )

    years_list = list(years)
    logger.info("─" * 60)
    logger.info("PANEL ASSEMBLY: %d years (%d-%d)", len(years_list), min(years_list), max(years_list))
    logger.info("─" * 60)

    # ------------------------------------------------------------------
    # Step 1: Build scaffold
    # ------------------------------------------------------------------
    scaffold = build_panel_scaffold(years_list)
    expected_per_year = len(load_ibge_municipios())

    # ------------------------------------------------------------------
    # Step 2: Fetch IPCA deflation factors
    # ------------------------------------------------------------------
    try:
        ipca_df = fetch_ipca_annual_index(years=years_list, base_year=2023)
        ipca_factors = ipca_df.set_index("year")["deflation_factor"]
        logger.info("IPCA deflation factors loaded for %d years", len(ipca_factors))
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to fetch IPCA factors: %s -- monetary columns will NOT be deflated",
            exc,
        )
        ipca_factors = None

    # ------------------------------------------------------------------
    # Step 3: Load, validate, deflate, and merge each source
    # ------------------------------------------------------------------
    panel = scaffold.copy()
    reports: list[ValidationReport] = []
    deflation_log: list[dict] = []

    for source_name, catalog in SOURCE_CATALOG.items():
        logger.info("▶ Processing source: %s", source_name)

        # Resolve path (handle glob patterns)
        source_dir = processed_dir / catalog["path"]
        glob_pattern = catalog["glob"]

        if "*" in glob_pattern:
            # Multiple files -- concat
            files = sorted(source_dir.glob(glob_pattern))
            if not files:
                logger.warning(
                    "  No files found for '%s' at %s/%s -- skipping",
                    source_name, source_dir, glob_pattern,
                )
                continue
            source_path = files[0] if len(files) == 1 else None
            if source_path is None:
                # Multiple files -- read and concat
                frames = []
                for f in files:
                    try:
                        frames.append(pd.read_parquet(f))
                    except Exception as exc:  # noqa: BLE001
                        logger.error("  Failed to read %s: %s", f, exc)
                if not frames:
                    logger.warning("  No readable files for '%s' -- skipping", source_name)
                    continue
                combined = pd.concat(frames, ignore_index=True)
                # Write to temp path for load_source
                tmp_path = source_dir / f"_combined_{source_name}.parquet"
                combined.to_parquet(tmp_path, index=False)
                source_path = tmp_path
        else:
            source_path = source_dir / glob_pattern

        # Load source
        source_df = load_source(
            name=source_name,
            path=source_path,
            years=years_list,
            is_crosssectional=catalog["is_crosssectional"],
        )

        if len(source_df) == 0:
            logger.warning("  Source '%s' is empty -- skipping merge", source_name)
            continue

        # Deflate monetary columns BEFORE validation and merge
        if ipca_factors is not None and catalog["monetary_cols"]:
            for mcol in catalog["monetary_cols"]:
                if mcol in source_df.columns:
                    source_df = deflate_column(source_df, mcol, ipca_factors)
                    deflation_log.append({
                        "source": source_name,
                        "column": mcol,
                        "base_year": 2023,
                        "method": "IPCA general (SIDRA 1737)",
                    })
                    logger.info(
                        "  Deflated '%s' in '%s' to constant 2023 BRL",
                        mcol, source_name,
                    )

        # Validate
        clean_df, report = validate_dataframe(
            source_df,
            source_name=source_name,
            strict=False,
            quarantine_dir=quarantine_dir,
        )
        reports.append(report)

        if len(clean_df) == 0:
            logger.warning(
                "  Source '%s' has 0 valid rows after validation -- skipping merge",
                source_name,
            )
            continue

        # Left merge onto panel (scaffold drives)
        merge_cols = ["cod_ibge", "year"]
        value_cols = [c for c in clean_df.columns if c not in merge_cols]

        # Prefix source columns to avoid collisions (except merge keys)
        # Only prefix if column name doesn't already indicate source
        to_merge = clean_df[merge_cols + value_cols].copy()

        try:
            panel = panel.merge(
                to_merge,
                on=merge_cols,
                how="left",
                validate="1:1",
            )
            logger.info(
                "  Merged '%s': %d value columns joined",
                source_name, len(value_cols),
            )
        except pd.errors.MergeError as exc:
            logger.warning(
                "  Merge validation failed for '%s' (likely duplicates): %s. "
                "Falling back to many:1 merge.",
                source_name, exc,
            )
            # Deduplicate source on merge keys before retry
            deduped = to_merge.drop_duplicates(subset=merge_cols, keep="first")
            panel = panel.merge(deduped, on=merge_cols, how="left")

    # ------------------------------------------------------------------
    # Step 4: Assert row-count invariant
    # ------------------------------------------------------------------
    for year in years_list:
        n_year = len(panel[panel["year"] == year])
        assert n_year == expected_per_year, (
            "Row count invariant failed for year %d: got %d, expected %d"
            % (year, n_year, expected_per_year)
        )

    logger.info(
        "Panel assembly complete: %d rows, %d columns",
        len(panel), len(panel.columns),
    )

    # ------------------------------------------------------------------
    # Step 5: Write validation report
    # ------------------------------------------------------------------
    report_path = processed_dir / "validation_report.json"
    write_validation_report(reports, report_path)

    # Log deflation summary
    if deflation_log:
        logger.info("Deflation log: %d columns deflated to 2023 BRL", len(deflation_log))
        for entry in deflation_log:
            logger.info(
                "  %s.%s deflated via %s (base=%d)",
                entry["source"], entry["column"],
                entry["method"], entry["base_year"],
            )

    return panel, reports
