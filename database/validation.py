"""
ICSKG-BR Validation Gate
=========================
Validates each data source's parsed DataFrame before it reaches the merge stage.
Implements the mandatory Layer 3 quality gate from the ICSKG-BR pipeline architecture.

Validation checks applied to every source DataFrame:
  1. Municipality code validity -- cod_ibge must be in the IBGE 2023 reference list
  2. Year in scope -- year must be in 2015-2023
  3. No duplicate keys -- (cod_ibge, year) must be unique within a source
  4. Schema conformance -- required columns must be present

In default mode (strict=False), rows failing any check are:
  - Written to data_sources/quarantine/{source}_{timestamp}_quarantine.parquet
  - Logged as warnings
  - Excluded from the returned clean DataFrame
  - Documented in the ValidationReport

In strict mode (strict=True), the first failed check raises ValidationError.
Use strict=True in CI or when debugging data quality issues.

Usage
-----
    from database.validation import validate_dataframe, write_validation_report

    clean_df, report = validate_dataframe(df, source_name="sih", strict=False)
    write_validation_report([report], path=Path("validation_report.json"))
"""

import json
import logging
import sys
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

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

STUDY_YEAR_MIN: int = 2015
STUDY_YEAR_MAX: int = 2023

# Required columns every source DataFrame must have after normalization
REQUIRED_COLUMNS: list[str] = ["cod_ibge", "year"]

# Default quarantine directory (relative to project root)
DEFAULT_QUARANTINE_DIR: Path = Path("data_sources") / "quarantine"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ValidationError(Exception):
    """Raised by validate_dataframe() when strict=True and validation fails.

    Attributes
    ----------
    check_name : str
        Name of the failing validation check (e.g., "cod_ibge_valid").
    n_failing : int
        Number of rows that failed the check.
    source : str
        Source name (e.g., "sih", "ifgf").
    sample : list
        Sample of failing values for diagnosis.
    """

    def __init__(
        self,
        check_name: str,
        n_failing: int,
        source: str,
        sample: list | None = None,
    ) -> None:
        self.check_name = check_name
        self.n_failing = n_failing
        self.source = source
        self.sample = sample or []
        super().__init__(
            f"Validation failed [{source}] check '{check_name}': "
            f"{n_failing} row(s) failed. Sample: {self.sample[:5]}"
        )


# ---------------------------------------------------------------------------
# Report data class
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    """Result of a single validation check."""
    check_name: str
    n_failing: int
    passed: bool
    sample_failing: list = field(default_factory=list)


@dataclass
class ValidationReport:
    """Aggregated validation results for one data source."""
    source: str
    n_rows_input: int
    n_valid: int
    n_quarantined: int
    timestamp: str
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """True if no rows were quarantined."""
        return self.n_quarantined == 0

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-compatible dict."""
        d = asdict(self)
        d["passed"] = self.passed
        return d


# ---------------------------------------------------------------------------
# Internal check functions
# ---------------------------------------------------------------------------

def _check_required_columns(df: pd.DataFrame) -> list[str]:
    """Return list of missing required columns."""
    return [col for col in REQUIRED_COLUMNS if col not in df.columns]


def _check_cod_ibge_valid(
    df: pd.DataFrame,
    valid_codes: set[str],
) -> pd.Series:
    """Return boolean mask -- True where cod_ibge is INVALID."""
    return ~df["cod_ibge"].isin(valid_codes)


def _check_year_in_scope(df: pd.DataFrame) -> pd.Series:
    """Return boolean mask -- True where year is outside 2015-2023."""
    year_col = pd.to_numeric(df["year"], errors="coerce")
    return ~year_col.between(STUDY_YEAR_MIN, STUDY_YEAR_MAX)


def _check_duplicate_keys(df: pd.DataFrame) -> pd.Series:
    """Return boolean mask -- True for duplicate (cod_ibge, year) rows."""
    return df.duplicated(subset=["cod_ibge", "year"], keep="first")


# ---------------------------------------------------------------------------
# Quarantine helper
# ---------------------------------------------------------------------------

def _quarantine_rows(
    bad_df: pd.DataFrame,
    source: str,
    check_name: str,
    quarantine_dir: Path,
    timestamp: str,
) -> None:
    """Write bad rows to quarantine directory as Parquet."""
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    safe_check = check_name.replace("/", "_")
    out_path = quarantine_dir / f"{source}_{timestamp}_{safe_check}_quarantine.parquet"
    bad_df = bad_df.copy()
    bad_df["_quarantine_reason"] = check_name
    bad_df["_quarantine_source"] = source
    bad_df["_quarantine_timestamp"] = timestamp
    bad_df.to_parquet(out_path, index=False)
    logger.warning(
        "Quarantined %d rows from '%s' [check: %s] -> %s",
        len(bad_df),
        source,
        check_name,
        out_path,
    )


# ---------------------------------------------------------------------------
# Main validation entry point
# ---------------------------------------------------------------------------

def validate_dataframe(
    df: pd.DataFrame,
    source_name: str = "unknown",
    strict: bool = False,
    quarantine_dir: Path | None = None,
    ibge_ref_path: Path | None = None,
) -> tuple[pd.DataFrame, ValidationReport]:
    """Validate a parsed source DataFrame before merge.

    Runs four checks in order:
      1. schema_conformance  -- required columns present
      2. cod_ibge_valid      -- codes in IBGE 2023 reference
      3. year_in_scope       -- year in 2015-2023
      4. no_duplicate_keys   -- (cod_ibge, year) unique

    Parameters
    ----------
    df : pd.DataFrame
        Parsed source DataFrame. Must have 'cod_ibge' (7-digit str) and 'year'.
    source_name : str
        Identifier for the source (e.g., "sih", "ifgf"). Used in filenames
        and the validation report.
    strict : bool
        If True, raises ValidationError on first failing check.
        If False (default), quarantines bad rows and continues.
    quarantine_dir : Path, optional
        Where to write quarantined rows. Defaults to data_sources/quarantine/.
    ibge_ref_path : Path, optional
        Path to ibge_municipios_2023.csv. Auto-discovered if None.

    Returns
    -------
    tuple[pd.DataFrame, ValidationReport]
        clean_df : DataFrame with all invalid rows removed.
        report   : ValidationReport documenting check results.

    Raises
    ------
    ValidationError
        If strict=True and any check fails.
    """
    # Lazy import to avoid circular dependency at module level
    from database.utils import load_ibge_municipios  # noqa: PLC0415

    if quarantine_dir is None:
        quarantine_dir = DEFAULT_QUARANTINE_DIR

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    n_input = len(df)
    check_results: list[CheckResult] = []
    bad_mask = pd.Series(False, index=df.index)  # accumulates all bad rows

    logger.info(
        "─" * 60 + "\nValidating source '%s': %d rows", source_name, n_input
    )

    # ------------------------------------------------------------------
    # Check 1: Schema conformance
    # ------------------------------------------------------------------
    missing_cols = _check_required_columns(df)
    if missing_cols:
        result = CheckResult(
            check_name="schema_conformance",
            n_failing=n_input,  # entire DataFrame is invalid if missing cols
            passed=False,
            sample_failing=missing_cols,
        )
        check_results.append(result)
        msg = (
            f"[{source_name}] schema_conformance: missing required columns: "
            f"{missing_cols}"
        )
        if strict:
            raise ValidationError(
                check_name="schema_conformance",
                n_failing=n_input,
                source=source_name,
                sample=missing_cols,
            )
        logger.error(msg)
        # Cannot proceed with other checks if columns are missing
        report = ValidationReport(
            source=source_name,
            n_rows_input=n_input,
            n_valid=0,
            n_quarantined=n_input,
            timestamp=timestamp,
            checks=check_results,
        )
        _quarantine_rows(df, source_name, "schema_conformance", quarantine_dir, timestamp)
        return pd.DataFrame(columns=df.columns), report

    # ------------------------------------------------------------------
    # Check 2: Municipality code validity
    # ------------------------------------------------------------------
    try:
        ref = load_ibge_municipios(path=ibge_ref_path)
        valid_codes: set[str] = set(ref["cod_ibge"])
    except FileNotFoundError:
        logger.warning(
            "[%s] IBGE reference list not found -- skipping cod_ibge_valid check",
            source_name,
        )
        valid_codes = None  # type: ignore[assignment]

    if valid_codes is not None:
        ibge_bad = _check_cod_ibge_valid(df, valid_codes)
        n_ibge_bad = ibge_bad.sum()
        sample = df.loc[ibge_bad, "cod_ibge"].unique().tolist()[:10]
        result = CheckResult(
            check_name="cod_ibge_valid",
            n_failing=int(n_ibge_bad),
            passed=n_ibge_bad == 0,
            sample_failing=sample,
        )
        check_results.append(result)
        if n_ibge_bad > 0:
            logger.warning(
                "[%s] cod_ibge_valid: %d invalid codes. Sample: %s",
                source_name, n_ibge_bad, sample[:5],
            )
            if strict:
                raise ValidationError(
                    check_name="cod_ibge_valid",
                    n_failing=int(n_ibge_bad),
                    source=source_name,
                    sample=sample,
                )
            _quarantine_rows(
                df[ibge_bad], source_name, "cod_ibge_valid", quarantine_dir, timestamp
            )
            bad_mask = bad_mask | ibge_bad

    # ------------------------------------------------------------------
    # Check 3: Year in scope
    # ------------------------------------------------------------------
    year_bad = _check_year_in_scope(df)
    n_year_bad = year_bad.sum()
    sample_years = df.loc[year_bad, "year"].unique().tolist()[:10] if n_year_bad > 0 else []
    result = CheckResult(
        check_name="year_in_scope",
        n_failing=int(n_year_bad),
        passed=n_year_bad == 0,
        sample_failing=[str(y) for y in sample_years],
    )
    check_results.append(result)
    if n_year_bad > 0:
        logger.warning(
            "[%s] year_in_scope: %d rows outside 2015-2023. Sample years: %s",
            source_name, n_year_bad, sample_years[:5],
        )
        if strict:
            raise ValidationError(
                check_name="year_in_scope",
                n_failing=int(n_year_bad),
                source=source_name,
                sample=[str(y) for y in sample_years],
            )
        _quarantine_rows(
            df[year_bad & ~bad_mask],
            source_name, "year_in_scope", quarantine_dir, timestamp,
        )
        bad_mask = bad_mask | year_bad

    # ------------------------------------------------------------------
    # Check 4: Duplicate keys
    # ------------------------------------------------------------------
    dup_bad = _check_duplicate_keys(df)
    n_dup_bad = dup_bad.sum()
    result = CheckResult(
        check_name="no_duplicate_keys",
        n_failing=int(n_dup_bad),
        passed=n_dup_bad == 0,
        sample_failing=[],
    )
    check_results.append(result)
    if n_dup_bad > 0:
        logger.warning(
            "[%s] no_duplicate_keys: %d duplicate (cod_ibge, year) rows.",
            source_name, n_dup_bad,
        )
        if strict:
            raise ValidationError(
                check_name="no_duplicate_keys",
                n_failing=int(n_dup_bad),
                source=source_name,
            )
        _quarantine_rows(
            df[dup_bad & ~bad_mask],
            source_name, "no_duplicate_keys", quarantine_dir, timestamp,
        )
        bad_mask = bad_mask | dup_bad

    # ------------------------------------------------------------------
    # Assemble clean DataFrame and report
    # ------------------------------------------------------------------
    clean_df = df[~bad_mask].copy()
    n_quarantined = int(bad_mask.sum())

    report = ValidationReport(
        source=source_name,
        n_rows_input=n_input,
        n_valid=len(clean_df),
        n_quarantined=n_quarantined,
        timestamp=timestamp,
        checks=check_results,
    )

    status = "PASS" if report.passed else f"QUARANTINED {n_quarantined} rows"
    logger.info(
        "[%s] Validation complete: %d/%d rows valid -- %s",
        source_name, len(clean_df), n_input, status,
    )
    return clean_df, report


# ---------------------------------------------------------------------------
# Report persistence
# ---------------------------------------------------------------------------

def write_validation_report(
    reports: list[ValidationReport],
    path: Path,
) -> None:
    """Write a list of ValidationReports to a JSON file.

    Parameters
    ----------
    reports : list[ValidationReport]
        One report per validated source.
    path : Path
        Output file path (e.g., data_sources/processed/validation_report.json).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_sources": len(reports),
        "all_passed": all(r.passed for r in reports),
        "sources": [r.to_dict() for r in reports],
    }
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
    logger.info("Validation report written -> %s", path)
