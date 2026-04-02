"""
Tests for SIH ETLSIH CSV extraction module.

Covers column projection, municipality code normalization, deduplication,
idempotent output, and numeric type coercion using offline fixture data.
"""

import pandas as pd
import pytest
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent / "fixtures"
FIXTURE_CSV = FIXTURE_DIR / "ETLSIH.ST_XX_2023_1_t.csv"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

def test_sih_cols_keep_constant():
    """SIH_COLS_KEEP contains all 27 required columns."""
    from scripts.sih_extract import SIH_COLS_KEEP

    expected = {
        "UF_ZI", "ANO_CMPT", "MES_CMPT", "N_AIH", "IDENT",
        "MUNIC_RES", "MUNIC_MOV", "NASC", "SEXO", "IDADE", "COD_IDADE",
        "DIAS_PERM", "DIAG_PRINC", "DIAG_SECUN", "PROC_SOLIC", "PROC_REA",
        "DT_INTER", "DT_SAIDA", "MORTE", "VAL_TOT", "VAL_UTI",
        "CNES", "COMPLEX", "FINANC", "CAR_INT", "ESPEC", "CGC_HOSP",
    }
    assert set(SIH_COLS_KEEP) == expected
    assert len(SIH_COLS_KEEP) == 27


# ---------------------------------------------------------------------------
# read_etlsih_csv tests
# ---------------------------------------------------------------------------

def test_read_etlsih_csv_columns():
    """read_etlsih_csv() returns DataFrame with exactly SIH_COLS_KEEP columns."""
    from scripts.sih_extract import read_etlsih_csv, SIH_COLS_KEEP

    df = read_etlsih_csv(FIXTURE_CSV)
    assert set(df.columns) == set(SIH_COLS_KEEP), (
        "Column mismatch: extra=%s missing=%s"
        % (
            set(df.columns) - set(SIH_COLS_KEEP),
            set(SIH_COLS_KEEP) - set(df.columns),
        )
    )


def test_read_etlsih_csv_row_count():
    """read_etlsih_csv() on fixture returns 6 rows (no filtering at read stage)."""
    from scripts.sih_extract import read_etlsih_csv

    df = read_etlsih_csv(FIXTURE_CSV)
    assert len(df) == 6


# ---------------------------------------------------------------------------
# Municipality code normalization
# ---------------------------------------------------------------------------

def test_munic_mov_normalized():
    """After processing, MUNIC_MOV 120020 becomes 7-digit string '0120020'."""
    from scripts.sih_extract import read_etlsih_csv
    from database.utils import normalize_cod_ibge

    df = read_etlsih_csv(FIXTURE_CSV)
    normalized = normalize_cod_ibge(df["MUNIC_MOV"])
    # Row 0 has MUNIC_MOV=120020 (6-digit int)
    assert normalized.iloc[0] == "0120020"


def test_munic_res_normalized():
    """After processing, MUNIC_RES 355030 becomes 7-digit string '0355030'."""
    from scripts.sih_extract import read_etlsih_csv
    from database.utils import normalize_cod_ibge

    df = read_etlsih_csv(FIXTURE_CSV)
    normalized = normalize_cod_ibge(df["MUNIC_RES"])
    # Row 2 has MUNIC_RES=355030 (6-digit int)
    assert normalized.iloc[2] == "0355030"


# ---------------------------------------------------------------------------
# process_sih_month tests
# ---------------------------------------------------------------------------

def test_process_sih_month_creates_parquet(tmp_path):
    """process_sih_month() writes Parquet file to expected path {UF}_{YYYYMM}.parquet."""
    from scripts.sih_extract import _process_uf_month

    output_dir = tmp_path / "processed" / "sih"
    output_dir.mkdir(parents=True)

    result = _process_uf_month(
        uf="XX",
        year=2023,
        month=1,
        raw_dir=FIXTURE_DIR,
        output_dir=output_dir,
        skip_existing=False,
    )

    assert result["status"] == "ok"
    expected_path = output_dir / "XX_202301.parquet"
    assert expected_path.exists()
    assert expected_path.stat().st_size > 0

    # Verify written data can be read back
    df = pd.read_parquet(expected_path)
    assert len(df) > 0


def test_process_sih_month_idempotent(tmp_path):
    """Running process_sih_month() twice does not modify existing output."""
    from scripts.sih_extract import _process_uf_month

    output_dir = tmp_path / "processed" / "sih"
    output_dir.mkdir(parents=True)

    # First run: creates the file
    result1 = _process_uf_month(
        uf="XX",
        year=2023,
        month=1,
        raw_dir=FIXTURE_DIR,
        output_dir=output_dir,
        skip_existing=True,
    )
    assert result1["status"] == "ok"

    parquet_path = output_dir / "XX_202301.parquet"
    mtime_1 = parquet_path.stat().st_mtime

    # Second run: should skip
    result2 = _process_uf_month(
        uf="XX",
        year=2023,
        month=1,
        raw_dir=FIXTURE_DIR,
        output_dir=output_dir,
        skip_existing=True,
    )
    assert result2["status"] == "skipped"
    mtime_2 = parquet_path.stat().st_mtime
    assert mtime_1 == mtime_2, "File was modified on second run"


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def test_deduplication_by_n_aih(tmp_path):
    """Duplicate N_AIH rows are removed (keep first)."""
    from scripts.sih_extract import _process_uf_month

    output_dir = tmp_path / "processed" / "sih"
    output_dir.mkdir(parents=True)

    result = _process_uf_month(
        uf="XX",
        year=2023,
        month=1,
        raw_dir=FIXTURE_DIR,
        output_dir=output_dir,
        skip_existing=False,
    )
    assert result["status"] == "ok"

    df = pd.read_parquet(output_dir / "XX_202301.parquet")
    # Fixture has 6 rows but row 3 (index 3) is a duplicate of row 0 (same N_AIH)
    # After deduplication, we should have 5 unique N_AIH values
    assert df["N_AIH"].nunique() == len(df), "Duplicate N_AIH rows were not removed"
    assert len(df) == 5


# ---------------------------------------------------------------------------
# Type coercion
# ---------------------------------------------------------------------------

def test_morte_column_numeric():
    """MORTE column is numeric (0 or 1), not string."""
    from scripts.sih_extract import read_etlsih_csv

    df = read_etlsih_csv(FIXTURE_CSV)
    assert pd.api.types.is_integer_dtype(df["MORTE"]) or pd.api.types.is_float_dtype(
        df["MORTE"]
    ), "MORTE should be numeric, got %s" % df["MORTE"].dtype


def test_val_tot_numeric():
    """VAL_TOT column is numeric float, not string."""
    from scripts.sih_extract import read_etlsih_csv

    df = read_etlsih_csv(FIXTURE_CSV)
    assert pd.api.types.is_float_dtype(df["VAL_TOT"]), (
        "VAL_TOT should be float, got %s" % df["VAL_TOT"].dtype
    )


# ---------------------------------------------------------------------------
# Municipality-year aggregation tests
# ---------------------------------------------------------------------------

def _build_processed_parquets(tmp_path):
    """Helper: run process_sih_month to create per-UF Parquet files in tmp_path."""
    from scripts.sih_extract import _process_uf_month

    output_dir = tmp_path / "processed" / "sih"
    output_dir.mkdir(parents=True)

    _process_uf_month(
        uf="XX",
        year=2023,
        month=1,
        raw_dir=FIXTURE_DIR,
        output_dir=output_dir,
        skip_existing=False,
    )
    return output_dir


def test_aggregate_sih_year_columns(tmp_path):
    """aggregate_sih_year() output has columns [cod_ibge, year, n_procedures, n_deaths, total_cost_brl, mean_stay_days]."""
    from scripts.sih_extract import aggregate_sih_year

    processed_dir = _build_processed_parquets(tmp_path)
    agg_dir = tmp_path / "processed" / "sih_aggregated"

    out_path = aggregate_sih_year(
        processed_dir=processed_dir,
        output_dir=agg_dir,
        year=2023,
        skip_existing=False,
    )

    df = pd.read_parquet(out_path)
    expected_cols = {"cod_ibge", "year", "n_procedures", "n_deaths", "total_cost_brl", "mean_stay_days"}
    assert set(df.columns) == expected_cols, (
        "Column mismatch: extra=%s missing=%s"
        % (set(df.columns) - expected_cols, expected_cols - set(df.columns))
    )


def test_aggregate_sih_year_groupby(tmp_path):
    """Aggregation groups by (cod_ibge, year) -- municipality '0120020' has 2 procedures after dedup."""
    from scripts.sih_extract import aggregate_sih_year

    processed_dir = _build_processed_parquets(tmp_path)
    agg_dir = tmp_path / "processed" / "sih_aggregated"

    out_path = aggregate_sih_year(
        processed_dir=processed_dir,
        output_dir=agg_dir,
        year=2023,
        skip_existing=False,
    )

    df = pd.read_parquet(out_path)
    row_ac = df[df["cod_ibge"] == "0120020"]
    assert len(row_ac) == 1, "Expected single row for cod_ibge 0120020"
    assert row_ac.iloc[0]["n_procedures"] == 2


def test_aggregate_sih_year_death_sum(tmp_path):
    """n_deaths sums MORTE column correctly (1 death for cod_ibge '0355030')."""
    from scripts.sih_extract import aggregate_sih_year

    processed_dir = _build_processed_parquets(tmp_path)
    agg_dir = tmp_path / "processed" / "sih_aggregated"

    out_path = aggregate_sih_year(
        processed_dir=processed_dir,
        output_dir=agg_dir,
        year=2023,
        skip_existing=False,
    )

    df = pd.read_parquet(out_path)
    row_sp = df[df["cod_ibge"] == "0355030"]
    assert len(row_sp) == 1
    assert row_sp.iloc[0]["n_deaths"] == 1


def test_aggregate_sih_year_cost_sum(tmp_path):
    """total_cost_brl sums VAL_TOT correctly for cod_ibge '0120020'."""
    from scripts.sih_extract import aggregate_sih_year

    processed_dir = _build_processed_parquets(tmp_path)
    agg_dir = tmp_path / "processed" / "sih_aggregated"

    out_path = aggregate_sih_year(
        processed_dir=processed_dir,
        output_dir=agg_dir,
        year=2023,
        skip_existing=False,
    )

    df = pd.read_parquet(out_path)
    row_ac = df[df["cod_ibge"] == "0120020"]
    assert abs(row_ac.iloc[0]["total_cost_brl"] - 1835.80) < 0.01


def test_aggregate_sih_year_writes_parquet(tmp_path):
    """Output written to sih_mun_year_{YEAR}.parquet."""
    from scripts.sih_extract import aggregate_sih_year

    processed_dir = _build_processed_parquets(tmp_path)
    agg_dir = tmp_path / "processed" / "sih_aggregated"

    out_path = aggregate_sih_year(
        processed_dir=processed_dir,
        output_dir=agg_dir,
        year=2023,
        skip_existing=False,
    )

    assert out_path.name == "sih_mun_year_2023.parquet"
    assert out_path.exists()
    assert out_path.stat().st_size > 0


def test_aggregate_sih_year_validation(tmp_path):
    """validate_dataframe() passes on aggregated output (cod_ibge + year present, codes valid)."""
    from scripts.sih_extract import aggregate_sih_year
    from database.validation import validate_dataframe

    processed_dir = _build_processed_parquets(tmp_path)
    agg_dir = tmp_path / "processed" / "sih_aggregated"

    out_path = aggregate_sih_year(
        processed_dir=processed_dir,
        output_dir=agg_dir,
        year=2023,
        skip_existing=False,
    )

    df = pd.read_parquet(out_path)
    clean_df, report = validate_dataframe(
        df,
        source_name="sih_aggregated",
        strict=False,
        quarantine_dir=tmp_path / "quarantine",
    )
    # Schema conformance should pass (cod_ibge and year present)
    schema_check = [c for c in report.checks if c.check_name == "schema_conformance"]
    assert len(schema_check) == 0 or schema_check[0].passed, (
        "Schema conformance failed: %s" % schema_check
    )
