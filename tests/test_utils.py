"""Tests for database/utils.py — normalize_cod_ibge edge cases."""

import numpy as np
import pandas as pd
import pytest
from pathlib import Path

# Add project root to sys.path so "database.utils" is importable
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.utils import (
    normalize_cod_ibge,
    normalize_column_name,
    rename_municipality_column,
    load_ibge_municipios,
    IBGE_MUNICIPIOS_PATH,
)


class TestNormalizeCodIbge:
    """Tests for normalize_cod_ibge()."""

    def test_7digit_string_unchanged(self):
        s = pd.Series(["3550308", "1100015"])
        result = normalize_cod_ibge(s)
        assert result.tolist() == ["3550308", "1100015"]

    def test_7digit_int_to_string(self):
        s = pd.Series([3550308, 1100015])
        result = normalize_cod_ibge(s)
        assert result.tolist() == ["3550308", "1100015"]

    def test_6digit_string_zero_padded(self):
        s = pd.Series(["355030"])
        result = normalize_cod_ibge(s)
        assert result.tolist() == ["0355030"]

    def test_6digit_int_zero_padded(self):
        s = pd.Series([355030])
        result = normalize_cod_ibge(s)
        assert result.tolist() == ["0355030"]

    def test_whitespace_stripped(self):
        s = pd.Series(["  3550308  ", " 1100015"])
        result = normalize_cod_ibge(s)
        assert result.tolist() == ["3550308", "1100015"]

    def test_nan_preserved(self):
        s = pd.Series([None, "3550308", np.nan])
        result = normalize_cod_ibge(s)
        assert result[0] is np.nan or pd.isna(result[0])
        assert result[1] == "3550308"
        assert pd.isna(result[2])

    def test_mixed_types(self):
        s = pd.Series([3550308, "1100015", 355030, None])
        result = normalize_cod_ibge(s)
        assert result[0] == "3550308"
        assert result[1] == "1100015"
        assert result[2] == "0355030"
        assert pd.isna(result[3])


class TestNormalizeColumnName:
    """Tests for normalize_column_name()."""

    def test_cod_ibge_variants(self):
        assert normalize_column_name("Cod_IBGE") == "cod_ibge"
        assert normalize_column_name("CD_MUNICIPIO") == "cod_ibge"
        assert normalize_column_name("CD_MUN") == "cod_ibge"
        assert normalize_column_name("MUNIC_RES") == "cod_ibge"
        assert normalize_column_name("MUNIC_MOV") == "cod_ibge"
        assert normalize_column_name("CODUFMUN") == "cod_ibge"
        assert normalize_column_name("cod_ibge") == "cod_ibge"

    def test_unknown_column_unchanged(self):
        assert normalize_column_name("BENEFICIARIOS") == "BENEFICIARIOS"
        assert normalize_column_name("year") == "year"


class TestRenameMunicipalityColumn:
    """Tests for rename_municipality_column()."""

    def test_renames_known_variant(self):
        df = pd.DataFrame({"Cod_IBGE": ["3550308"], "value": [1.0]})
        result = rename_municipality_column(df)
        assert "cod_ibge" in result.columns
        assert "Cod_IBGE" not in result.columns

    def test_noop_when_already_canonical(self):
        df = pd.DataFrame({"cod_ibge": ["3550308"], "value": [1.0]})
        result = rename_municipality_column(df)
        assert list(result.columns) == ["cod_ibge", "value"]

    def test_raises_when_no_mun_column(self):
        df = pd.DataFrame({"value": [1.0], "year": [2023]})
        with pytest.raises(ValueError, match="No municipality code column"):
            rename_municipality_column(df)


class TestLoadIbgeMunicipios:
    """Tests for load_ibge_municipios()."""

    def test_loads_5571_rows(self):
        if not IBGE_MUNICIPIOS_PATH.exists():
            pytest.skip("ibge_municipios_2023.csv not yet downloaded")
        ref = load_ibge_municipios()
        assert len(ref) == 5571

    def test_no_duplicate_codes(self):
        if not IBGE_MUNICIPIOS_PATH.exists():
            pytest.skip("ibge_municipios_2023.csv not yet downloaded")
        ref = load_ibge_municipios()
        assert ref["cod_ibge"].nunique() == 5571

    def test_all_codes_7_digits(self):
        if not IBGE_MUNICIPIOS_PATH.exists():
            pytest.skip("ibge_municipios_2023.csv not yet downloaded")
        ref = load_ibge_municipios()
        assert ref["cod_ibge"].str.len().eq(7).all()

    def test_cod_ibge_dtype_is_string(self):
        if not IBGE_MUNICIPIOS_PATH.exists():
            pytest.skip("ibge_municipios_2023.csv not yet downloaded")
        ref = load_ibge_municipios()
        assert ref["cod_ibge"].dtype == object  # pandas string dtype

    def test_raises_when_file_missing(self):
        with pytest.raises(FileNotFoundError, match="IBGE municipality reference"):
            load_ibge_municipios(path=Path("/nonexistent/path.csv"))
