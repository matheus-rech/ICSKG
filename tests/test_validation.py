"""Tests for database/validation.py — the mandatory validation gate."""

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.validation import (
    validate_dataframe,
    write_validation_report,
    ValidationError,
    ValidationReport,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

IBGE_REF = Path("data_sources/ibge_municipios_2023.csv")


def make_clean_df() -> pd.DataFrame:
    """Minimal valid DataFrame: two rows, valid 2023 codes, years in scope."""
    return pd.DataFrame(
        {
            "cod_ibge": ["3550308", "1100015"],  # Sao Paulo, Porto Velho
            "year": [2020, 2021],
            "value": [1.0, 2.0],
        }
    )


def make_bad_code_df() -> pd.DataFrame:
    """DataFrame with a known-bad municipality code (9999999 does not exist)."""
    return pd.DataFrame(
        {
            "cod_ibge": ["3550308", "9999999"],
            "year": [2020, 2020],
            "value": [1.0, 99.0],
        }
    )


def make_out_of_range_year_df() -> pd.DataFrame:
    """DataFrame with a year outside 2015-2023."""
    return pd.DataFrame(
        {
            "cod_ibge": ["3550308", "1100015"],
            "year": [2020, 2000],  # 2000 is out of scope
            "value": [1.0, 2.0],
        }
    )


def make_duplicate_df() -> pd.DataFrame:
    """DataFrame with duplicate (cod_ibge, year) rows."""
    return pd.DataFrame(
        {
            "cod_ibge": ["3550308", "3550308"],
            "year": [2020, 2020],  # duplicate key
            "value": [1.0, 1.5],
        }
    )


# ---------------------------------------------------------------------------
# Tests -- strict=True (raises ValidationError)
# ---------------------------------------------------------------------------

class TestStrictMode:
    """validate_dataframe() with strict=True must raise ValidationError on any failure."""

    def test_rejects_bad_municipality_code(self, tmp_path):
        """ROADMAP success criterion: gate rejects known-bad municipality code."""
        if not IBGE_REF.exists():
            pytest.skip("ibge_municipios_2023.csv required for cod_ibge check")
        df = make_bad_code_df()
        with pytest.raises(ValidationError) as exc_info:
            validate_dataframe(df, source_name="test", strict=True, quarantine_dir=tmp_path)
        assert exc_info.value.check_name == "cod_ibge_valid"
        assert exc_info.value.n_failing >= 1
        assert "9999999" in str(exc_info.value.sample)

    def test_rejects_out_of_range_year(self, tmp_path):
        """ROADMAP success criterion: gate rejects known out-of-range value."""
        df = make_out_of_range_year_df()
        with pytest.raises(ValidationError) as exc_info:
            validate_dataframe(df, source_name="test", strict=True, quarantine_dir=tmp_path)
        assert exc_info.value.check_name == "year_in_scope"
        assert exc_info.value.n_failing >= 1

    def test_rejects_duplicate_keys(self, tmp_path):
        """Duplicate (cod_ibge, year) rows must be rejected in strict mode."""
        df = make_duplicate_df()
        with pytest.raises(ValidationError) as exc_info:
            validate_dataframe(df, source_name="test", strict=True, quarantine_dir=tmp_path)
        assert exc_info.value.check_name == "no_duplicate_keys"

    def test_clean_df_passes(self, tmp_path):
        """A clean DataFrame must not raise in strict mode."""
        df = make_clean_df()
        clean, report = validate_dataframe(
            df, source_name="test", strict=True, quarantine_dir=tmp_path
        )
        assert report.passed
        assert len(clean) == 2

    def test_raises_on_missing_required_column(self, tmp_path):
        """DataFrame missing 'year' column must raise in strict mode."""
        df = pd.DataFrame({"cod_ibge": ["3550308"], "value": [1.0]})
        with pytest.raises(ValidationError) as exc_info:
            validate_dataframe(df, source_name="test", strict=True, quarantine_dir=tmp_path)
        assert exc_info.value.check_name == "schema_conformance"


# ---------------------------------------------------------------------------
# Tests -- strict=False (quarantine mode)
# ---------------------------------------------------------------------------

class TestQuarantineMode:
    """validate_dataframe() with strict=False must quarantine bad rows and continue."""

    def test_quarantines_bad_code_does_not_raise(self, tmp_path):
        """Default mode must NOT raise; it quarantines and returns a report."""
        if not IBGE_REF.exists():
            pytest.skip("ibge_municipios_2023.csv required for cod_ibge check")
        df = make_bad_code_df()
        clean, report = validate_dataframe(
            df, source_name="test_src", strict=False, quarantine_dir=tmp_path
        )
        assert report.n_quarantined >= 1
        assert len(clean) < len(df)
        # Quarantine file must exist
        quarantine_files = list(tmp_path.glob("*.parquet"))
        assert len(quarantine_files) >= 1

    def test_quarantines_out_of_range_year(self, tmp_path):
        """Out-of-range year rows are quarantined, not silently kept."""
        df = make_out_of_range_year_df()
        clean, report = validate_dataframe(
            df, source_name="test_src", strict=False, quarantine_dir=tmp_path
        )
        assert report.n_quarantined == 1
        assert len(clean) == 1
        assert clean.iloc[0]["year"] == 2020  # the valid row remains

    def test_clean_df_zero_quarantined(self, tmp_path):
        """A fully valid DataFrame results in n_quarantined == 0."""
        df = make_clean_df()
        clean, report = validate_dataframe(
            df, source_name="clean_src", strict=False, quarantine_dir=tmp_path
        )
        assert report.n_quarantined == 0
        assert report.passed
        assert len(clean) == len(df)


# ---------------------------------------------------------------------------
# Tests -- ValidationReport
# ---------------------------------------------------------------------------

class TestValidationReport:
    def test_to_dict_has_required_keys(self, tmp_path):
        df = make_clean_df()
        _, report = validate_dataframe(
            df, source_name="test", strict=False, quarantine_dir=tmp_path
        )
        d = report.to_dict()
        for key in ["source", "n_rows_input", "n_valid", "n_quarantined", "checks"]:
            assert key in d, f"Missing key in to_dict(): {key}"

    def test_write_validation_report_is_valid_json(self, tmp_path):
        df = make_clean_df()
        _, report = validate_dataframe(
            df, source_name="test", strict=False, quarantine_dir=tmp_path
        )
        out = tmp_path / "validation_report.json"
        write_validation_report([report], path=out)
        assert out.exists()
        payload = json.loads(out.read_text())
        assert "sources" in payload
        assert payload["n_sources"] == 1
