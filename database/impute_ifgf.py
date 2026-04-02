"""
ICSKG-BR IFGF Multiple Imputation Module
==========================================
Fills missing IFGF values (~420 MNAR municipalities per year) using
multiple imputation with chained equations (MICE) via scikit-learn's
IterativeImputer with BayesianRidge posterior sampling.

The IFGF (Indice FIRJAN de Gestao Fiscal) has a systematic missingness
pattern: approximately 420 small municipalities per year are not scored
by FIRJAN due to insufficient fiscal data. This is Missing Not At Random
(MNAR) because the missingness is related to the fiscal governance
capacity of the municipality itself.

Multiple imputation (m=5) with auxiliary variables (GDP per capita,
population, region) accounts for imputation uncertainty. Results are
pooled using Rubin's rules (mean across imputations).

Exports
-------
    impute_ifgf_mice(panel, m, max_iter) -> tuple[pd.DataFrame, dict]
    generate_missingness_report(panel, output_path) -> Path

Usage
-----
    from database.impute_ifgf import impute_ifgf_mice, generate_missingness_report

    panel, log = impute_ifgf_mice(panel, m=5, max_iter=10)
    report_path = generate_missingness_report(panel, Path("missingness.csv"))
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

# UF-to-region mapping (N=1, NE=2, CO=3, SE=4, S=5)
UF_TO_REGION: dict[str, int] = {
    # Norte (N)
    "AC": 1, "AP": 1, "AM": 1, "PA": 1, "RO": 1, "RR": 1, "TO": 1,
    # Nordeste (NE)
    "AL": 2, "BA": 2, "CE": 2, "MA": 2, "PB": 2, "PE": 2, "PI": 2, "RN": 2, "SE": 2,
    # Centro-Oeste (CO)
    "DF": 3, "GO": 3, "MT": 3, "MS": 3,
    # Sudeste (SE)
    "ES": 4, "MG": 4, "RJ": 4, "SP": 4,
    # Sul (S)
    "PR": 5, "RS": 5, "SC": 5,
}

# Metadata columns excluded from missingness report
METADATA_COLS: set[str] = {
    "cod_ibge", "year", "nome_municipio", "uf", "region_code",
    "ifgf_is_imputed",
}


# ---------------------------------------------------------------------------
# Public API — imputation
# ---------------------------------------------------------------------------

def impute_ifgf_mice(
    panel: pd.DataFrame,
    m: int = 5,
    max_iter: int = 10,
) -> tuple[pd.DataFrame, dict]:
    """Fill missing IFGF values via multiple imputation (MICE).

    Uses scikit-learn IterativeImputer with BayesianRidge and posterior
    sampling. Runs m imputations and pools via Rubin's rules (mean).

    Parameters
    ----------
    panel : pd.DataFrame
        Municipality-year panel. Must contain IFGF columns and auxiliary
        columns (gdp_per_capita, populacao, and either region_code or uf).
    m : int
        Number of imputations (default 5).
    max_iter : int
        Maximum iterations per imputation (default 10).

    Returns
    -------
    tuple[pd.DataFrame, dict]
        panel : DataFrame with IFGF NaN filled and ifgf_is_imputed flag added.
        imputation_log : dict with method details and per-year counts.
    """
    from sklearn.experimental import enable_iterative_imputer  # noqa: F401, PLC0415
    from sklearn.impute import IterativeImputer  # noqa: PLC0415
    from sklearn.linear_model import BayesianRidge  # noqa: PLC0415

    logger.info("─" * 60)
    logger.info("IFGF MULTIPLE IMPUTATION (m=%d, max_iter=%d)", m, max_iter)
    logger.info("─" * 60)

    panel = panel.copy()

    # -----------------------------------------------------------------------
    # Derive region_code if not present
    # -----------------------------------------------------------------------
    if "region_code" not in panel.columns:
        if "uf" in panel.columns:
            panel["region_code"] = panel["uf"].map(UF_TO_REGION)
            logger.info("Derived region_code from uf column")
        else:
            logger.warning(
                "Neither 'region_code' nor 'uf' found in panel. "
                "Imputation will proceed without region auxiliary variable."
            )
            panel["region_code"] = 0

    # -----------------------------------------------------------------------
    # Identify MNAR mask BEFORE imputation
    # -----------------------------------------------------------------------
    available_ifgf = [c for c in IFGF_COLS if c in panel.columns]
    if not available_ifgf:
        logger.warning("No IFGF columns found in panel -- returning unchanged")
        log = _build_log(m, max_iter, 0, panel, available_ifgf)
        panel["ifgf_is_imputed"] = 0
        return panel, log

    mnar_mask = panel[available_ifgf].isna().any(axis=1)
    n_imputed_rows = int(mnar_mask.sum())

    # -----------------------------------------------------------------------
    # Early return if nothing to impute
    # -----------------------------------------------------------------------
    if n_imputed_rows == 0:
        logger.info("No missing IFGF values -- skipping imputation")
        log = _build_log(m, max_iter, 0, panel, available_ifgf)
        panel["ifgf_is_imputed"] = 0
        return panel, log

    logger.info("IFGF MNAR rows to impute: %d / %d total", n_imputed_rows, len(panel))

    # -----------------------------------------------------------------------
    # Build feature matrix
    # -----------------------------------------------------------------------
    available_aux = [c for c in AUX_COLS if c in panel.columns]
    feature_cols = available_ifgf + available_aux
    X = panel[feature_cols].copy()

    # -----------------------------------------------------------------------
    # Run m imputations with different random seeds
    # -----------------------------------------------------------------------
    imputed_frames: list[pd.DataFrame] = []
    for i in range(m):
        imputer = IterativeImputer(
            estimator=BayesianRidge(),
            sample_posterior=True,
            max_iter=max_iter,
            random_state=i * 42,
            verbose=0,
        )
        imputed_arr = imputer.fit_transform(X)
        imputed_df = pd.DataFrame(
            imputed_arr, columns=feature_cols, index=panel.index,
        )
        imputed_frames.append(imputed_df)

    # -----------------------------------------------------------------------
    # Pool via Rubin's rules: mean across m imputations for IFGF cols only
    # -----------------------------------------------------------------------
    stacked = pd.concat(imputed_frames)
    pooled = stacked.groupby(level=0).mean()

    # Only overwrite IFGF values where original was NaN
    for col in available_ifgf:
        panel.loc[mnar_mask, col] = pooled.loc[mnar_mask, col]

    # -----------------------------------------------------------------------
    # Add imputation flag
    # -----------------------------------------------------------------------
    panel["ifgf_is_imputed"] = mnar_mask.astype(int)

    # -----------------------------------------------------------------------
    # Build imputation log
    # -----------------------------------------------------------------------
    log = _build_log(m, max_iter, n_imputed_rows, panel, available_ifgf)

    logger.info(
        "Imputation complete: %d rows imputed across %d years",
        n_imputed_rows, len(log.get("per_year", {})),
    )

    return panel, log


# ---------------------------------------------------------------------------
# Public API — missingness report
# ---------------------------------------------------------------------------

def generate_missingness_report(
    panel: pd.DataFrame,
    output_path: Path | str,
) -> Path:
    """Generate a RECORD 12.1 compliant missingness report.

    For each value column in the panel, documents the missingness rate
    per year with the mechanism classification and handling method.

    Parameters
    ----------
    panel : pd.DataFrame
        Municipality-year panel (pre- or post-imputation).
    output_path : Path or str
        Path for the output CSV.

    Returns
    -------
    Path
        Path to the written CSV file.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    value_cols = [
        c for c in panel.columns if c not in METADATA_COLS
    ]
    years = sorted(panel["year"].unique())

    rows: list[dict] = []
    for col in value_cols:
        for year in years:
            year_data = panel[panel["year"] == year][col]
            n_total = len(year_data)
            n_observed = int(year_data.notna().sum())
            n_missing = n_total - n_observed
            pct_missing = round(n_missing / n_total * 100, 2) if n_total > 0 else 0.0

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

    report = pd.DataFrame(rows)
    report = report.sort_values(["variable", "year"]).reset_index(drop=True)
    report.to_csv(output_path, index=False)

    logger.info(
        "Missingness report written: %d rows covering %d variables x %d years -> %s",
        len(report), len(value_cols), len(years), output_path,
    )

    return output_path


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _build_log(
    m: int,
    max_iter: int,
    n_imputed_rows: int,
    panel: pd.DataFrame,
    ifgf_cols: list[str],
) -> dict:
    """Build the imputation log dict."""
    per_year: dict[int, int] = {}
    if n_imputed_rows > 0 and "ifgf_is_imputed" in panel.columns:
        for year in sorted(panel["year"].unique()):
            year_mask = panel["year"] == year
            per_year[int(year)] = int(panel.loc[year_mask, "ifgf_is_imputed"].sum())
    elif n_imputed_rows > 0:
        # Fallback: count from IFGF NaN mask before imputation
        for year in sorted(panel["year"].unique()):
            per_year[int(year)] = 0

    available_aux = [c for c in AUX_COLS if c in panel.columns]

    return {
        "m": m,
        "max_iter": max_iter,
        "method": "IterativeImputer(BayesianRidge, sample_posterior=True)",
        "n_imputed_rows": n_imputed_rows,
        "ifgf_cols": ifgf_cols,
        "aux_cols": available_aux,
        "per_year": per_year,
    }


def _classify_mechanism(col: str, pct_missing: float) -> str:
    """Classify missingness mechanism for a variable.

    Parameters
    ----------
    col : str
        Column name.
    pct_missing : float
        Percentage of missing values (0-100).

    Returns
    -------
    str
        Missingness mechanism classification.
    """
    # IFGF columns: MNAR (systematically missing small municipalities)
    if col.startswith("ifgf_"):
        return "MNAR"

    # IDHM: cross-sectional from 2010 census
    if col.startswith("idhm"):
        return "cross_sectional_2010"

    # Census sanitation: cross-sectional from 2022
    if col.startswith("pct_sanitation") or col.startswith("pct_water"):
        return "cross_sectional_2022"

    # Health expenditure: source_unavailable if 100% missing, else MAR
    if col.startswith("health_expenditure"):
        if pct_missing >= 100.0:
            return "source_unavailable"
        return "MAR" if pct_missing > 0 else "NA"

    # Vehicles: source_unavailable if 100% missing, else MAR
    if col.startswith("vehicles"):
        if pct_missing >= 100.0:
            return "source_unavailable"
        return "MAR" if pct_missing > 0 else "NA"

    # Default: NA if fully observed, MAR otherwise
    if pct_missing == 0:
        return "NA"
    return "MAR"


def _classify_handling(mechanism: str) -> str:
    """Map missingness mechanism to handling method.

    Parameters
    ----------
    mechanism : str
        Missingness mechanism from _classify_mechanism().

    Returns
    -------
    str
        Handling method applied.
    """
    handling_map = {
        "MNAR": "multiple_imputation_m5",
        "cross_sectional_2010": "constant_fill",
        "cross_sectional_2022": "constant_fill",
        "source_unavailable": "documented_gap",
        "NA": "none",
        "MAR": "left_as_nan",
    }
    return handling_map.get(mechanism, "left_as_nan")
