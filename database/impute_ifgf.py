"""
ICSKG-BR IFGF Multiple Imputation Module
==========================================
Handles Missing Not At Random (MNAR) values in IFGF fiscal governance
indicators via multiple imputation (MICE) with Bayesian Ridge regression.

Approximately 420 Brazilian municipalities per year are systematically missing
from FIRJAN's IFGF dataset. This module imputes those values using auxiliary
variables (GDP per capita, population, region) through scikit-learn's
IterativeImputer with sample_posterior=True and Rubin's rules pooling.

Also generates a RECORD item 12.1 compliant missingness report documenting
every variable's missingness rate, mechanism, and handling method per year.

Exports
-------
    impute_ifgf_mice(panel, m, max_iter) -> tuple[pd.DataFrame, dict]
    generate_missingness_report(panel, output_path) -> Path

Usage
-----
    from database.impute_ifgf import impute_ifgf_mice, generate_missingness_report

    panel, log = impute_ifgf_mice(panel, m=5, max_iter=10)
    report_path = generate_missingness_report(panel, Path("PANL-06-missingness.csv"))
"""

import logging
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

IFGF_COLS: list[str] = [
    "ifgf_geral", "ifgf_ra", "ifgf_gp", "ifgf_id", "ifgf_el", "ifgf_sa",
]

AUX_COLS: list[str] = ["gdp_per_capita", "populacao", "region_code"]

# UF -> region code mapping (IBGE standard macro-regions)
UF_TO_REGION: dict[str, int] = {
    # Norte (N) = 1
    "AC": 1, "AP": 1, "AM": 1, "PA": 1, "RO": 1, "RR": 1, "TO": 1,
    # Nordeste (NE) = 2
    "AL": 2, "BA": 2, "CE": 2, "MA": 2, "PB": 2, "PE": 2,
    "PI": 2, "RN": 2, "SE": 2,
    # Centro-Oeste (CO) = 3
    "DF": 3, "GO": 3, "MT": 3, "MS": 3,
    # Sudeste (SE) = 4
    "ES": 4, "MG": 4, "RJ": 4, "SP": 4,
    # Sul (S) = 5
    "PR": 5, "RS": 5, "SC": 5,
}

# Metadata columns excluded from missingness analysis
METADATA_COLS: set[str] = {
    "cod_ibge", "year", "nome_municipio", "uf", "region_code",
    "ifgf_is_imputed",
}

# Schema for the missingness report DataFrame — pinned so an empty `rows`
# list still produces a DataFrame with the expected columns. This is
# defense-in-depth against the cryptic `KeyError: 'variable'` failure mode
# (Phase 11 fix).
REPORT_COLUMNS: list[str] = [
    "variable", "year", "n_total", "n_observed", "n_missing",
    "pct_missing", "missingness_mechanism", "handling_method",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def impute_ifgf_mice(
    panel: pd.DataFrame,
    m: int = 5,
    max_iter: int = 10,
) -> tuple[pd.DataFrame, dict]:
    """Multiple imputation for IFGF columns using auxiliary variables.

    Runs *m* imputations with scikit-learn IterativeImputer (BayesianRidge
    estimator, sample_posterior=True), then pools results via Rubin's rules
    (mean across imputations). Only IFGF columns where original values were
    NaN are overwritten; auxiliary columns are never modified.

    Parameters
    ----------
    panel : pd.DataFrame
        Must contain IFGF columns and auxiliary columns (or 'uf' for
        region_code derivation).
    m : int
        Number of imputations (default: 5).
    max_iter : int
        Maximum iterations per imputation (default: 10).

    Returns
    -------
    tuple[pd.DataFrame, dict]
        panel : DataFrame with imputed IFGF values and ifgf_is_imputed flag.
        imputation_log : Dict with method details and per-year breakdown.
    """
    panel = panel.copy()

    # -----------------------------------------------------------------------
    # Derive region_code if not present
    # -----------------------------------------------------------------------
    if "region_code" not in panel.columns:
        if "uf" in panel.columns:
            panel["region_code"] = panel["uf"].map(UF_TO_REGION).astype(float)
            logger.info(
                "Derived region_code from uf column (%d mapped)",
                panel["region_code"].notna().sum(),
            )
        else:
            logger.warning(
                "Neither region_code nor uf found in panel -- "
                "imputation will proceed without region auxiliary"
            )

    # -----------------------------------------------------------------------
    # Identify MNAR rows (any IFGF column is NaN)
    # -----------------------------------------------------------------------
    present_ifgf = [c for c in IFGF_COLS if c in panel.columns]
    if not present_ifgf:
        logger.warning("No IFGF columns found in panel -- returning unchanged")
        log = _build_log(m, max_iter, 0, present_ifgf, panel)
        return panel, log

    mnar_mask = panel[present_ifgf].isna().any(axis=1)
    n_imputed_rows = int(mnar_mask.sum())

    logger.info(
        "IFGF MNAR rows: %d / %d (%.1f%%)",
        n_imputed_rows, len(panel),
        100 * n_imputed_rows / max(len(panel), 1),
    )

    # -----------------------------------------------------------------------
    # Early return if nothing to impute
    # -----------------------------------------------------------------------
    if n_imputed_rows == 0:
        panel["ifgf_is_imputed"] = 0
        log = _build_log(m, max_iter, 0, present_ifgf, panel)
        return panel, log

    # -----------------------------------------------------------------------
    # Run m imputations
    # -----------------------------------------------------------------------
    from sklearn.experimental import enable_iterative_imputer  # noqa: F401,PLC0415
    from sklearn.impute import IterativeImputer  # noqa: PLC0415
    from sklearn.linear_model import BayesianRidge  # noqa: PLC0415

    present_aux = [c for c in AUX_COLS if c in panel.columns]
    feature_cols = present_ifgf + present_aux

    # Preserve original aux values
    aux_backup = {c: panel[c].copy() for c in present_aux}

    X = panel[feature_cols].values.copy()

    imputed_arrays = []
    for i in range(m):
        imputer = IterativeImputer(
            estimator=BayesianRidge(),
            sample_posterior=True,
            max_iter=max_iter,
            random_state=i * 42,
            verbose=0,
        )
        X_imp = imputer.fit_transform(X)
        imputed_arrays.append(X_imp)
        logger.info("  Imputation %d/%d complete", i + 1, m)

    # -----------------------------------------------------------------------
    # Pool via Rubin's rules (mean across m imputations for IFGF cols only)
    # -----------------------------------------------------------------------
    stacked = np.stack(imputed_arrays, axis=0)  # shape: (m, n_rows, n_features)
    pooled = stacked.mean(axis=0)  # shape: (n_rows, n_features)

    # Only overwrite IFGF columns where original was NaN
    for j, col in enumerate(present_ifgf):
        original = panel[col].values.copy()
        imputed_vals = pooled[:, j]
        panel[col] = np.where(np.isnan(original), imputed_vals, original)

    # Restore auxiliary columns (imputer may have modified them)
    for c, backup in aux_backup.items():
        panel[c] = backup

    # Add imputation flag
    panel["ifgf_is_imputed"] = mnar_mask.astype(int).values

    # -----------------------------------------------------------------------
    # Build log
    # -----------------------------------------------------------------------
    log = _build_log(m, max_iter, n_imputed_rows, present_ifgf, panel)

    logger.info(
        "IFGF imputation complete: %d rows imputed via m=%d imputations",
        n_imputed_rows, m,
    )
    return panel, log


def generate_missingness_report(
    panel: pd.DataFrame,
    output_path: Path | str,
) -> Path:
    """Generate a RECORD 12.1 compliant missingness report.

    For each value column in the panel, documents per-year missingness rate,
    mechanism classification, and handling method.

    Parameters
    ----------
    panel : pd.DataFrame
        The assembled panel (pre- or post-imputation).
    output_path : Path or str
        Where to write the CSV report.

    Returns
    -------
    Path
        The output path (confirmed written).
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    value_cols = [
        c for c in panel.columns if c not in METADATA_COLS
    ]

    # Phase 11 fail-loud guard: refuse to write a phantom missingness report.
    # ICSKG-BR requires real source data (5,570 mun × 9 years × 9 dimensions);
    # a metadata-only panel means upstream ETL silently produced nothing,
    # which is a publication-blocking failure that must surface immediately.
    if not value_cols:
        raise ValueError(
            "generate_missingness_report: panel has no value columns "
            "(panel has %d rows, columns: %s). "
            "This indicates an upstream ETL failure -- refusing to write "
            "a phantom missingness report. Check that data_sources/processed/ "
            "is populated, or fetch from HuggingFace via "
            "`python -m database.fetch_processed_data --to <db_path>`."
        )

    years = sorted(panel["year"].unique())

    rows: list[dict] = []
    for col in value_cols:
        for year in years:
            year_data = panel.loc[panel["year"] == year, col]
            n_total = len(year_data)
            n_missing = int(year_data.isna().sum())
            n_observed = n_total - n_missing
            pct_missing = round(100 * n_missing / max(n_total, 1), 2)

            mechanism = _classify_mechanism(col, pct_missing)
            handling = _classify_handling(mechanism)

            rows.append({
                "variable": col,
                "year": int(year),
                "n_total": n_total,
                "n_observed": n_observed,
                "n_missing": n_missing,
                "pct_missing": pct_missing,
                "missingness_mechanism": mechanism,
                "handling_method": handling,
            })

    # Phase 11 schema-pin: defense-in-depth against the cryptic
    # KeyError: 'variable' that crashed CI on every run pre-Phase 11.
    # Even if rows is empty for any reason (which the guard above would
    # already catch), pd.DataFrame(rows, columns=REPORT_COLUMNS) ensures
    # the DataFrame has the expected schema and sort_values cannot raise
    # KeyError on a missing column.
    report = pd.DataFrame(rows, columns=REPORT_COLUMNS)
    report = report.sort_values(["variable", "year"]).reset_index(drop=True)
    report.to_csv(output_path, index=False)

    logger.info(
        "Missingness report written: %d entries -> %s",
        len(report), output_path,
    )
    return output_path


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_log(
    m: int,
    max_iter: int,
    n_imputed_rows: int,
    ifgf_cols: list[str],
    panel: pd.DataFrame,
) -> dict:
    """Build the imputation log dict."""
    present_aux = [c for c in AUX_COLS if c in panel.columns]

    # Per-year breakdown
    per_year: dict[int, int] = {}
    if "ifgf_is_imputed" in panel.columns and n_imputed_rows > 0:
        for year in sorted(panel["year"].unique()):
            year_mask = panel["year"] == year
            n_yr = int(panel.loc[year_mask, "ifgf_is_imputed"].sum())
            per_year[int(year)] = n_yr
    elif n_imputed_rows == 0:
        for year in sorted(panel["year"].unique()):
            per_year[int(year)] = 0

    return {
        "m": m,
        "max_iter": max_iter,
        "method": "IterativeImputer(BayesianRidge, sample_posterior=True)",
        "n_imputed_rows": n_imputed_rows,
        "ifgf_cols": ifgf_cols,
        "aux_cols": present_aux,
        "per_year": per_year,
    }


def _classify_mechanism(col: str, pct_missing: float) -> str:
    """Classify missingness mechanism based on column name and rate.

    Parameters
    ----------
    col : str
        Column name.
    pct_missing : float
        Percentage of missing values.

    Returns
    -------
    str
        One of: MNAR, cross_sectional_2010, cross_sectional_2022,
        source_unavailable, MAR, NA.
    """
    # IFGF columns are MNAR (municipalities not assessed by FIRJAN)
    if col.startswith("ifgf_"):
        return "MNAR"

    # IDHM is cross-sectional (2010 census)
    if col.startswith("idhm"):
        return "cross_sectional_2010"

    # Sanitation / water from Census 2022
    if col.startswith("pct_sanitation") or col.startswith("pct_water"):
        return "cross_sectional_2022"

    # Source unavailable if 100% missing
    if pct_missing >= 100.0:
        if col.startswith("health_expenditure") or col.startswith("vehicles"):
            return "source_unavailable"

    # Health expenditure or vehicles with partial data
    if col.startswith("health_expenditure") or col.startswith("vehicles"):
        if pct_missing > 0:
            return "MAR"

    # Fully observed
    if pct_missing == 0.0:
        return "NA"

    # Default for partially missing
    return "MAR"


def _classify_handling(mechanism: str) -> str:
    """Map missingness mechanism to handling method.

    Parameters
    ----------
    mechanism : str
        The classified missingness mechanism.

    Returns
    -------
    str
        Handling method string.
    """
    handling_map = {
        "MNAR": "multiple_imputation_m5",
        "cross_sectional_2010": "constant_fill",
        "cross_sectional_2022": "constant_fill",
        "source_unavailable": "documented_gap",
        "MAR": "left_as_nan",
        "NA": "none",
    }
    return handling_map.get(mechanism, "left_as_nan")
