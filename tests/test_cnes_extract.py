"""
Tests for CNES extraction script (scripts/cnes_extract.py).

Covers:
  - CBO-2002 6-digit code constants for SAO filtering
  - Bellwether facility identification (surgical center, obstetric center, bed count)
  - CNES ST CSV reading and Parquet output
  - Municipality code normalization via normalize_cod_ibge()
"""

from pathlib import Path

import pandas as pd
import pytest

from scripts.cnes_extract import (
    CBO_ANESTHESIOLOGISTS,
    CBO_OBSTETRICIANS,
    CBO_SAO,
    CBO_SURGEONS,
    CNES_ST_COLS,
    extract_cnes_facilities,
    extract_cnes_professionals,
    filter_bellwether_facilities,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

FIXTURE_DIR = Path(__file__).parent / "fixtures"
FIXTURE_CSV = FIXTURE_DIR / "ETLCNES.ST_XX__23_01_t.csv"


# ---------------------------------------------------------------------------
# CBO constant validation tests
# ---------------------------------------------------------------------------


class TestCBOConstants:
    """Validate CBO-2002 6-digit code constants."""

    def test_cbo_surgeons_all_6digit(self):
        """Every code in CBO_SURGEONS is exactly 6 digits and starts with '2252'."""
        for code in CBO_SURGEONS:
            assert len(code) == 6, "CBO surgeon code %s is not 6 digits" % code
            assert code.startswith("2252"), (
                "CBO surgeon code %s does not start with '2252'" % code
            )

    def test_cbo_anesthesiologists_correct(self):
        """CBO_ANESTHESIOLOGISTS must contain exactly one code: 225151."""
        assert CBO_ANESTHESIOLOGISTS == {"225151"}

    def test_cbo_obstetricians_correct(self):
        """CBO_OBSTETRICIANS must contain exactly one code: 225250."""
        assert CBO_OBSTETRICIANS == {"225250"}

    def test_cbo_sao_count(self):
        """CBO_SAO must have exactly 11 codes (9 surgeon + 1 anesthesiologist + 1 obstetrician)."""
        assert len(CBO_SAO) == 11, "Expected 11 SAO codes, got %d" % len(CBO_SAO)

    def test_cbo_no_dentists(self):
        """No code in CBO_SAO starts with '2232' (dentists) -- per Pitfall 3."""
        for code in CBO_SAO:
            assert not code.startswith("2232"), (
                "CBO_SAO contains dentist code: %s" % code
            )

    def test_cbo_no_nurses(self):
        """No code in CBO_SAO starts with '2235' (nurses) -- per Pitfall 3."""
        for code in CBO_SAO:
            assert not code.startswith("2235"), (
                "CBO_SAO contains nurse code: %s" % code
            )


# ---------------------------------------------------------------------------
# CNES_ST_COLS constant validation
# ---------------------------------------------------------------------------


class TestCNESSTCols:
    """Validate CNES ST column constant."""

    def test_cnes_st_cols_constant(self):
        """CNES_ST_COLS must contain all 11 required columns."""
        required = {
            "CNES", "CODUFMUN", "COMPETEN",
            "CENTRCIR", "CENTROBS",
            "QTLEITP1", "QTLEITP2", "QTLEITP3",
            "VINC_SUS", "TP_UNID", "LEITHOSP",
        }
        assert required.issubset(set(CNES_ST_COLS)), (
            "Missing columns: %s" % (required - set(CNES_ST_COLS))
        )
        assert len(CNES_ST_COLS) >= 11


# ---------------------------------------------------------------------------
# Bellwether filter tests
# ---------------------------------------------------------------------------


class TestFilterBellwether:
    """Test bellwether facility identification logic."""

    def _make_facility(self, centrcir=0, centrobs=0, beds1=0, beds2=0, beds3=0):
        """Helper to create a single-row facility DataFrame."""
        return pd.DataFrame({
            "CNES": ["9999999"],
            "CODUFMUN": ["355030"],
            "COMPETEN": [202301],
            "CENTRCIR": [centrcir],
            "CENTROBS": [centrobs],
            "QTLEITP1": [beds1],
            "QTLEITP2": [beds2],
            "QTLEITP3": [beds3],
            "VINC_SUS": [1],
            "TP_UNID": [5],
            "LEITHOSP": [0],
        })

    def test_filter_bellwether_surgical_center(self):
        """Facility with CENTRCIR>0 is flagged as bellwether."""
        df = self._make_facility(centrcir=1)
        result = filter_bellwether_facilities(df)
        assert result["is_bellwether"].iloc[0] is True or result["is_bellwether"].iloc[0] == True  # noqa: E712

    def test_filter_bellwether_obstetric_center(self):
        """Facility with CENTROBS>0 is flagged as bellwether."""
        df = self._make_facility(centrobs=1)
        result = filter_bellwether_facilities(df)
        assert result["is_bellwether"].iloc[0] is True or result["is_bellwether"].iloc[0] == True  # noqa: E712

    def test_filter_bellwether_beds(self):
        """Facility with QTLEITP1+QTLEITP2+QTLEITP3>=10 is flagged as bellwether."""
        df = self._make_facility(beds1=5, beds2=3, beds3=2)
        result = filter_bellwether_facilities(df)
        assert result["is_bellwether"].iloc[0] is True or result["is_bellwether"].iloc[0] == True  # noqa: E712
        assert result["total_beds"].iloc[0] == 10

    def test_filter_bellwether_excludes_small(self):
        """Facility with CENTRCIR=0, CENTROBS=0, total_beds<10 is NOT bellwether."""
        df = self._make_facility(beds1=2, beds2=0, beds3=0)
        result = filter_bellwether_facilities(df)
        assert result["is_bellwether"].iloc[0] is False or result["is_bellwether"].iloc[0] == False  # noqa: E712


# ---------------------------------------------------------------------------
# Facility extraction integration tests
# ---------------------------------------------------------------------------


class TestExtractCNESFacilities:
    """Integration tests for extract_cnes_facilities()."""

    def test_extract_cnes_facilities_columns(self, tmp_path):
        """Output has expected columns."""
        output = extract_cnes_facilities(
            input_dir=FIXTURE_DIR,
            output_dir=tmp_path,
            year=2023,
        )
        df = pd.read_parquet(output)
        expected_cols = {
            "cnes", "cod_ibge", "year", "centrcir", "centrobs",
            "total_beds", "is_bellwether", "vinc_sus", "tp_unid",
        }
        assert expected_cols.issubset(set(df.columns)), (
            "Missing columns: %s" % (expected_cols - set(df.columns))
        )

    def test_extract_cnes_facilities_codufmun_normalized(self, tmp_path):
        """CODUFMUN normalized to 7-digit cod_ibge."""
        output = extract_cnes_facilities(
            input_dir=FIXTURE_DIR,
            output_dir=tmp_path,
            year=2023,
        )
        df = pd.read_parquet(output)
        for code in df["cod_ibge"]:
            assert len(str(code)) == 7, (
                "cod_ibge '%s' is not 7 digits" % code
            )

    def test_extract_cnes_facilities_writes_parquet(self, tmp_path):
        """Output written to facilities.parquet."""
        output = extract_cnes_facilities(
            input_dir=FIXTURE_DIR,
            output_dir=tmp_path,
            year=2023,
        )
        assert output.exists()
        assert output.name == "facilities.parquet"
        assert output.stat().st_size > 0


# ---------------------------------------------------------------------------
# CNES PF Professional extraction tests
# ---------------------------------------------------------------------------

PF_FIXTURE_CSV = FIXTURE_DIR / "cnes_pf_sample.csv"


class TestExtractCNESProfessionals:
    """Tests for CNES PF professional extraction."""

    def test_extract_cnes_professionals_columns(self, tmp_path):
        """Output has columns [cnes, cod_ibge, year, cbo, cns_prof, sao_category]."""
        # Copy fixture to input_dir as a PF-like file
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        import shutil
        shutil.copy(PF_FIXTURE_CSV, input_dir / "CNES_PF_XX_2023_01.csv")

        output = extract_cnes_professionals(
            input_dir=input_dir,
            output_dir=tmp_path / "output",
            year=2023,
        )
        df = pd.read_parquet(output)
        expected_cols = {"cnes", "cod_ibge", "year", "cbo", "cns_prof", "sao_category"}
        assert expected_cols.issubset(set(df.columns)), (
            "Missing columns: %s" % (expected_cols - set(df.columns))
        )

    def test_extract_cnes_professionals_cbo_filter(self, tmp_path):
        """Only rows with CBO in CBO_SAO are retained."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        import shutil
        shutil.copy(PF_FIXTURE_CSV, input_dir / "CNES_PF_XX_2023_01.csv")

        output = extract_cnes_professionals(
            input_dir=input_dir,
            output_dir=tmp_path / "output",
            year=2023,
        )
        df = pd.read_parquet(output)
        # All CBOs in output must be in CBO_SAO
        assert set(df["cbo"].unique()).issubset(CBO_SAO), (
            "Non-SAO CBO codes found in output: %s"
            % (set(df["cbo"].unique()) - CBO_SAO)
        )
        # Family medicine (225142) and dentist (223204) must NOT appear
        assert "225142" not in df["cbo"].values
        assert "223204" not in df["cbo"].values

    def test_extract_cnes_professionals_cns_dedup(self, tmp_path):
        """Duplicate CNS_PROF within same (cod_ibge, year) are deduplicated."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        import shutil
        shutil.copy(PF_FIXTURE_CSV, input_dir / "CNES_PF_XX_2023_01.csv")

        output = extract_cnes_professionals(
            input_dir=input_dir,
            output_dir=tmp_path / "output",
            year=2023,
        )
        df = pd.read_parquet(output)
        # CNS_PROF 700001 in CODUFMUN 355030 appears twice in fixture (rows 1 and 6)
        # After dedup, should appear only once in 355030
        surg_355030 = df[
            (df["cns_prof"] == "700001") & (df["cod_ibge"] == "0355030")
        ]
        assert len(surg_355030) == 1, (
            "Expected 1 row for CNS 700001 in 355030, got %d" % len(surg_355030)
        )
        # But CNS_PROF 700001 in 120020 (different municipality) should still exist
        surg_120020 = df[
            (df["cns_prof"] == "700001") & (df["cod_ibge"] == "0120020")
        ]
        assert len(surg_120020) == 1, (
            "Expected 1 row for CNS 700001 in 120020, got %d" % len(surg_120020)
        )

    def test_extract_cnes_professionals_sao_category(self, tmp_path):
        """sao_category is 'surgeon', 'anesthesiologist', or 'obstetrician'."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        import shutil
        shutil.copy(PF_FIXTURE_CSV, input_dir / "CNES_PF_XX_2023_01.csv")

        output = extract_cnes_professionals(
            input_dir=input_dir,
            output_dir=tmp_path / "output",
            year=2023,
        )
        df = pd.read_parquet(output)
        valid_categories = {"surgeon", "anesthesiologist", "obstetrician"}
        assert set(df["sao_category"].unique()).issubset(valid_categories), (
            "Invalid sao_category values: %s"
            % (set(df["sao_category"].unique()) - valid_categories)
        )
        # Check specific assignments
        assert df.loc[df["cbo"] == "225225", "sao_category"].iloc[0] == "surgeon"
        assert df.loc[df["cbo"] == "225151", "sao_category"].iloc[0] == "anesthesiologist"
        assert df.loc[df["cbo"] == "225250", "sao_category"].iloc[0] == "obstetrician"
        assert df.loc[df["cbo"] == "225260", "sao_category"].iloc[0] == "surgeon"

    def test_extract_cnes_professionals_codufmun_normalized(self, tmp_path):
        """CODUFMUN normalized to 7-digit cod_ibge."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        import shutil
        shutil.copy(PF_FIXTURE_CSV, input_dir / "CNES_PF_XX_2023_01.csv")

        output = extract_cnes_professionals(
            input_dir=input_dir,
            output_dir=tmp_path / "output",
            year=2023,
        )
        df = pd.read_parquet(output)
        for code in df["cod_ibge"]:
            assert len(str(code)) == 7, (
                "cod_ibge '%s' is not 7 digits" % code
            )

    def test_extract_cnes_professionals_writes_parquet(self, tmp_path):
        """Output written to professionals.parquet."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        import shutil
        shutil.copy(PF_FIXTURE_CSV, input_dir / "CNES_PF_XX_2023_01.csv")

        output = extract_cnes_professionals(
            input_dir=input_dir,
            output_dir=tmp_path / "output",
            year=2023,
        )
        assert output.exists()
        assert output.name == "professionals.parquet"
        assert output.stat().st_size > 0
