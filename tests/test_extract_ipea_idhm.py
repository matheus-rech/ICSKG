"""Tests for scripts/extract_ipea_idhm.py -- IPEA IDHM OData extraction."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_fixture(series_code: str = "ADH_IDHM") -> dict:
    """Load the IPEA OData sample fixture and optionally adjust SERCODIGO."""
    raw = json.loads((FIXTURE_DIR / "ipea_idhm_sample.json").read_text())
    if series_code != "ADH_IDHM":
        # Rewrite the fixture to simulate a different series
        col_map = {
            "ADH_IDHM": "idhm",
            "ADH_IDHM_E": "idhm_educacao",
            "ADH_IDHM_L": "idhm_longevidade",
            "ADH_IDHM_R": "idhm_renda",
        }
        for rec in raw["value"]:
            rec["SERCODIGO"] = series_code
            # Slightly vary values so merges are meaningful
            if rec["VALVALOR"] is not None:
                rec["VALVALOR"] = round(rec["VALVALOR"] * 0.95, 4)
    return raw


def _mock_requests_get(fixture_data: dict):
    """Return a mock that behaves like requests.get().json()."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = fixture_data
    mock_resp.raise_for_status.return_value = None
    return mock_resp


# ---------------------------------------------------------------------------
# Tests for fetch_idhm_series
# ---------------------------------------------------------------------------

class TestFetchIdhmSeries:
    """Unit tests for the fetch_idhm_series function."""

    def test_returns_dataframe_with_cod_ibge_column(self, monkeypatch):
        """fetch_idhm_series returns a DataFrame with cod_ibge column."""
        from scripts.extract_ipea_idhm import fetch_idhm_series

        fixture = _load_fixture("ADH_IDHM")
        monkeypatch.setattr(
            "scripts.extract_ipea_idhm.requests.get",
            lambda *a, **kw: _mock_requests_get(fixture),
        )
        df = fetch_idhm_series("ADH_IDHM", target_year=2010)
        assert "cod_ibge" in df.columns
        assert len(df) > 0

    def test_cod_ibge_are_7_digit_strings(self, monkeypatch):
        """All cod_ibge values must be 7-digit zero-padded strings."""
        from scripts.extract_ipea_idhm import fetch_idhm_series

        fixture = _load_fixture("ADH_IDHM")
        monkeypatch.setattr(
            "scripts.extract_ipea_idhm.requests.get",
            lambda *a, **kw: _mock_requests_get(fixture),
        )
        df = fetch_idhm_series("ADH_IDHM", target_year=2010)
        for code in df["cod_ibge"]:
            assert isinstance(code, str), f"Expected str, got {type(code)}"
            assert len(code) == 7, f"Expected 7-digit code, got '{code}'"

    def test_filters_out_non_municipality_rows(self, monkeypatch):
        """Rows with NIVNOME != 'Municipios' must be excluded."""
        from scripts.extract_ipea_idhm import fetch_idhm_series

        fixture = _load_fixture("ADH_IDHM")
        # Fixture has 1 row with NIVNOME == "Brasil" -- should be filtered
        monkeypatch.setattr(
            "scripts.extract_ipea_idhm.requests.get",
            lambda *a, **kw: _mock_requests_get(fixture),
        )
        df = fetch_idhm_series("ADH_IDHM", target_year=2010)
        # Fixture has 5 municipality rows for 2010, 2 for 2000, 1 national
        assert len(df) == 5, f"Expected 5 municipality rows, got {len(df)}"

    def test_filters_out_non_target_year_rows(self, monkeypatch):
        """Only rows matching target_year should be returned."""
        from scripts.extract_ipea_idhm import fetch_idhm_series

        fixture = _load_fixture("ADH_IDHM")
        monkeypatch.setattr(
            "scripts.extract_ipea_idhm.requests.get",
            lambda *a, **kw: _mock_requests_get(fixture),
        )
        df = fetch_idhm_series("ADH_IDHM", target_year=2010)
        # No 2000 rows should be present
        assert len(df) == 5

    def test_normalize_cod_ibge_applied(self, monkeypatch):
        """TERCODIGO '530010' (6-digit) should become '0530010' (7-digit)."""
        from scripts.extract_ipea_idhm import fetch_idhm_series

        fixture = _load_fixture("ADH_IDHM")
        monkeypatch.setattr(
            "scripts.extract_ipea_idhm.requests.get",
            lambda *a, **kw: _mock_requests_get(fixture),
        )
        df = fetch_idhm_series("ADH_IDHM", target_year=2010)
        # 530010 is 6 digits, should be zero-padded to 0530010
        assert "0530010" in df["cod_ibge"].values


# ---------------------------------------------------------------------------
# Tests for extract_idhm
# ---------------------------------------------------------------------------

class TestExtractIdhm:
    """Unit tests for the extract_idhm function."""

    def test_merges_four_series_into_correct_columns(self, monkeypatch, tmp_path):
        """extract_idhm merges 4 sub-indices into one DataFrame."""
        from scripts.extract_ipea_idhm import extract_idhm

        # Mock fetch for each series
        def mock_get(*args, **kwargs):
            url = args[0] if args else kwargs.get("url", "")
            for code in ["ADH_IDHM", "ADH_IDHM_E", "ADH_IDHM_L", "ADH_IDHM_R"]:
                if code in url:
                    return _mock_requests_get(_load_fixture(code))
            return _mock_requests_get(_load_fixture("ADH_IDHM"))

        monkeypatch.setattr("scripts.extract_ipea_idhm.requests.get", mock_get)
        # Skip validation (no IBGE ref file in test env)
        monkeypatch.setattr(
            "scripts.extract_ipea_idhm.validate_dataframe",
            lambda df, **kw: (df, MagicMock()),
        )

        out_path = extract_idhm(target_year=2010, output_dir=tmp_path)

        assert out_path.exists()
        result = pd.read_parquet(out_path)
        expected_cols = {"cod_ibge", "year", "idhm", "idhm_educacao",
                         "idhm_longevidade", "idhm_renda"}
        assert expected_cols == set(result.columns)

    def test_output_year_is_cross_sectional(self, monkeypatch, tmp_path):
        """All rows in the output must have year == 2010 (cross-sectional)."""
        from scripts.extract_ipea_idhm import extract_idhm

        def mock_get(*args, **kwargs):
            url = args[0] if args else kwargs.get("url", "")
            for code in ["ADH_IDHM", "ADH_IDHM_E", "ADH_IDHM_L", "ADH_IDHM_R"]:
                if code in url:
                    return _mock_requests_get(_load_fixture(code))
            return _mock_requests_get(_load_fixture("ADH_IDHM"))

        monkeypatch.setattr("scripts.extract_ipea_idhm.requests.get", mock_get)
        monkeypatch.setattr(
            "scripts.extract_ipea_idhm.validate_dataframe",
            lambda df, **kw: (df, MagicMock()),
        )

        out_path = extract_idhm(target_year=2010, output_dir=tmp_path)
        result = pd.read_parquet(out_path)
        assert (result["year"] == 2010).all(), "All rows must have year=2010"

    def test_writes_parquet_file(self, monkeypatch, tmp_path):
        """extract_idhm writes a .parquet file to the output directory."""
        from scripts.extract_ipea_idhm import extract_idhm

        def mock_get(*args, **kwargs):
            url = args[0] if args else kwargs.get("url", "")
            for code in ["ADH_IDHM", "ADH_IDHM_E", "ADH_IDHM_L", "ADH_IDHM_R"]:
                if code in url:
                    return _mock_requests_get(_load_fixture(code))
            return _mock_requests_get(_load_fixture("ADH_IDHM"))

        monkeypatch.setattr("scripts.extract_ipea_idhm.requests.get", mock_get)
        monkeypatch.setattr(
            "scripts.extract_ipea_idhm.validate_dataframe",
            lambda df, **kw: (df, MagicMock()),
        )

        out_path = extract_idhm(target_year=2010, output_dir=tmp_path)
        assert out_path.suffix == ".parquet"
        assert out_path.exists()
