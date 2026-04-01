"""Tests for the IBGE 2023 municipality reference CSV (Task 1 of 01-02)."""

from pathlib import Path

import pandas as pd
import pytest

IBGE_CSV = Path(__file__).parent.parent / "data_sources" / "ibge_municipios_2023.csv"


class TestIbgeReferenceCsv:
    """Validate the IBGE 2023 municipality reference list."""

    def test_file_exists(self):
        assert IBGE_CSV.exists(), f"IBGE reference CSV not found at {IBGE_CSV}"

    def test_has_5570_rows(self):
        df = pd.read_csv(IBGE_CSV, dtype={"cod_ibge": str})
        assert len(df) == 5570, f"Expected 5570 rows, got {len(df)}"

    def test_has_required_columns(self):
        df = pd.read_csv(IBGE_CSV, dtype={"cod_ibge": str}, nrows=1)
        for col in ("cod_ibge", "nome_municipio", "uf"):
            assert col in df.columns, f"Missing column: {col}"

    def test_no_duplicate_cod_ibge(self):
        df = pd.read_csv(IBGE_CSV, dtype={"cod_ibge": str})
        assert df["cod_ibge"].nunique() == 5570, "Duplicate cod_ibge values detected"

    def test_all_codes_7_digits(self):
        df = pd.read_csv(IBGE_CSV, dtype={"cod_ibge": str})
        assert df["cod_ibge"].str.len().eq(7).all(), "Not all codes are 7 digits"

    def test_uf_codes_are_2_letters(self):
        df = pd.read_csv(IBGE_CSV, dtype={"cod_ibge": str})
        assert df["uf"].str.len().eq(2).all(), "Not all UF codes are 2 letters"
        assert df["uf"].str.isalpha().all(), "UF codes contain non-alpha characters"
