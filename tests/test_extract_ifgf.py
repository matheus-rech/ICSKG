"""Tests for scripts/extract_ifgf.py -- FIRJAN IFGF Excel parser."""

import io
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"
IFGF_FIXTURE_PATH = FIXTURE_DIR / "ifgf_sample.xlsx"

# Fixed deterministic timestamp — openpyxl embeds creation/modified times in
# docProps/core.xml inside the .xlsx zip, and Python's zipfile stamps every
# entry with datetime.now() by default.  Both cause the fixture to drift on
# every test run and show up as a dirty working tree.  We canonicalize both
# via _write_deterministic_xlsx below.  Same class of bug as c019617 fixed
# for tests/fixtures/processed_smoke/manifest.json.
FIXED_FIXTURE_GENERATED_AT = datetime(2026, 4, 7, 0, 0, 0, tzinfo=timezone.utc)


def _write_deterministic_xlsx(df: pd.DataFrame, path: Path,
                               fixed_dt: datetime) -> None:
    """Write ``df`` to ``path`` as a byte-deterministic .xlsx.

    openpyxl + zipfile have two sources of nondeterminism we have to tame:

    1. openpyxl overrides ``workbook.properties.modified`` to ``datetime.now()``
       at save time, ignoring whatever we set on the property beforehand.
    2. Python's ``zipfile`` stamps each ``ZipInfo.date_time`` with the current
       wall clock unless explicitly set.

    Strategy: write via pandas/openpyxl into an in-memory buffer, then rewrite
    the zip with (a) ``dcterms:modified`` regex-patched in ``docProps/core.xml``
    and (b) every ``ZipInfo.date_time`` forced to ``fixed_dt``.  Rewriting the
    archive is cheap (<10 files) and produces byte-identical output across runs.
    """
    fixed_iso = fixed_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    fixed_dos = (
        fixed_dt.year, fixed_dt.month, fixed_dt.day,
        fixed_dt.hour, fixed_dt.minute, fixed_dt.second,
    )

    # Step 1 — write via openpyxl into a BytesIO buffer.
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
        writer.book.properties.created = fixed_dt
        writer.book.properties.creator = "icskg-br-test-fixture"
        writer.book.properties.lastModifiedBy = "icskg-br-test-fixture"

    # Step 2 — read entries back, canonicalize core.xml, rewrite with fixed
    # zip timestamps.  namelist() order is preserved so the central directory
    # layout stays stable.
    buf.seek(0)
    with zipfile.ZipFile(buf, "r") as src:
        names = src.namelist()
        contents = {name: src.read(name) for name in names}

    core_xml = contents["docProps/core.xml"].decode("utf-8")
    core_xml = re.sub(
        r"(<dcterms:modified[^>]*>)[^<]*(</dcterms:modified>)",
        rf"\g<1>{fixed_iso}\g<2>",
        core_xml,
    )
    contents["docProps/core.xml"] = core_xml.encode("utf-8")

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as dst:
        for name in names:
            info = zipfile.ZipInfo(filename=name, date_time=fixed_dos)
            info.compress_type = zipfile.ZIP_DEFLATED
            dst.writestr(info, contents[name])


# ---------------------------------------------------------------------------
# Fixture generation (creates Excel file once per session)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def create_ifgf_fixture():
    """Create the IFGF sample Excel fixture for testing.

    Columns: Cod_IBGE, Ano, IFGF_Geral, IFGF_RA, IFGF_GP, IFGF_ID, IFGF_EL, IFGF_SA

    Includes:
    - 5 municipality rows for year 2015 (inside scope)
    - 2 municipality rows for year 2023 (inside scope)
    - 1 municipality row for year 2014 (outside scope -- filtered)
    - 1 municipality with NaN for all sub-indices (simulating MNAR)
    - Mix of 6-digit and 7-digit Cod_IBGE values
    """
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    rows = [
        # 5 municipalities for 2015 (in scope)
        {"Cod_IBGE": "3550308", "Ano": 2015, "IFGF_Geral": 0.72,
         "IFGF_RA": 0.65, "IFGF_GP": 0.80, "IFGF_ID": 0.70,
         "IFGF_EL": 0.55, "IFGF_SA": 0.68},
        {"Cod_IBGE": "3304557", "Ano": 2015, "IFGF_Geral": 0.68,
         "IFGF_RA": 0.60, "IFGF_GP": 0.75, "IFGF_ID": 0.65,
         "IFGF_EL": 0.50, "IFGF_SA": 0.63},
        {"Cod_IBGE": "2927408", "Ano": 2015, "IFGF_Geral": 0.55,
         "IFGF_RA": 0.48, "IFGF_GP": 0.62, "IFGF_ID": 0.50,
         "IFGF_EL": 0.45, "IFGF_SA": 0.52},
        {"Cod_IBGE": "1501402", "Ano": 2015, "IFGF_Geral": 0.45,
         "IFGF_RA": 0.40, "IFGF_GP": 0.50, "IFGF_ID": 0.42,
         "IFGF_EL": 0.38, "IFGF_SA": 0.43},
        # 6-digit code (should be zero-padded to 7 digits)
        {"Cod_IBGE": "530010", "Ano": 2015, "IFGF_Geral": 0.82,
         "IFGF_RA": 0.78, "IFGF_GP": 0.85, "IFGF_ID": 0.80,
         "IFGF_EL": 0.75, "IFGF_SA": 0.79},
        # 2 municipalities for 2023 (in scope)
        {"Cod_IBGE": "3550308", "Ano": 2023, "IFGF_Geral": 0.78,
         "IFGF_RA": 0.72, "IFGF_GP": 0.84, "IFGF_ID": 0.76,
         "IFGF_EL": 0.60, "IFGF_SA": 0.74},
        {"Cod_IBGE": "3304557", "Ano": 2023, "IFGF_Geral": 0.71,
         "IFGF_RA": 0.64, "IFGF_GP": 0.78, "IFGF_ID": 0.68,
         "IFGF_EL": 0.53, "IFGF_SA": 0.66},
        # 1 municipality for 2014 (OUT of scope -- should be filtered)
        {"Cod_IBGE": "3550308", "Ano": 2014, "IFGF_Geral": 0.69,
         "IFGF_RA": 0.62, "IFGF_GP": 0.76, "IFGF_ID": 0.66,
         "IFGF_EL": 0.51, "IFGF_SA": 0.64},
        # 1 MNAR municipality (all sub-indices NaN)
        {"Cod_IBGE": "1100205", "Ano": 2015, "IFGF_Geral": np.nan,
         "IFGF_RA": np.nan, "IFGF_GP": np.nan, "IFGF_ID": np.nan,
         "IFGF_EL": np.nan, "IFGF_SA": np.nan},
    ]
    df = pd.DataFrame(rows)
    _write_deterministic_xlsx(df, IFGF_FIXTURE_PATH, FIXED_FIXTURE_GENERATED_AT)


# ---------------------------------------------------------------------------
# Tests for parse_ifgf
# ---------------------------------------------------------------------------

class TestParseIfgf:
    """Unit tests for the parse_ifgf function."""

    def test_returns_correct_columns(self):
        """parse_ifgf returns DataFrame with expected column set."""
        from scripts.extract_ifgf import parse_ifgf

        df = parse_ifgf(IFGF_FIXTURE_PATH)
        expected = {"cod_ibge", "year", "ifgf_geral", "ifgf_ra",
                    "ifgf_gp", "ifgf_id", "ifgf_el", "ifgf_sa"}
        assert set(df.columns) == expected

    def test_filters_to_2015_2023(self):
        """Only years 2015-2023 are included (2014 row must be excluded)."""
        from scripts.extract_ifgf import parse_ifgf

        df = parse_ifgf(IFGF_FIXTURE_PATH)
        assert df["year"].min() >= 2015
        assert df["year"].max() <= 2023
        assert 2014 not in df["year"].values

    def test_cod_ibge_7_digit_strings(self):
        """All cod_ibge values must be 7-digit zero-padded strings."""
        from scripts.extract_ifgf import parse_ifgf

        df = parse_ifgf(IFGF_FIXTURE_PATH)
        for code in df["cod_ibge"]:
            assert isinstance(code, str), f"Expected str, got {type(code)}"
            assert len(code) == 7, f"Expected 7-digit, got '{code}'"

    def test_nan_values_preserved_not_zero(self):
        """MNAR municipalities must have NaN sub-indices, not 0."""
        from scripts.extract_ifgf import parse_ifgf

        df = parse_ifgf(IFGF_FIXTURE_PATH)
        # The MNAR municipality (1100205) should have NaN for ifgf_geral
        mnar_rows = df[df["cod_ibge"] == "1100205"]
        assert len(mnar_rows) > 0, "MNAR municipality 1100205 must be present"
        assert mnar_rows["ifgf_geral"].isna().all(), (
            "MNAR municipality must have NaN for ifgf_geral, not zero"
        )

    def test_mnar_municipalities_not_dropped(self):
        """MNAR municipalities (~420/year) must appear with NaN, not be dropped."""
        from scripts.extract_ifgf import parse_ifgf

        df = parse_ifgf(IFGF_FIXTURE_PATH)
        # Fixture has 1 MNAR row for year 2015 -- it must be present
        mnar = df[(df["cod_ibge"] == "1100205") & (df["year"] == 2015)]
        assert len(mnar) == 1, "MNAR municipality must not be dropped"
        assert mnar["ifgf_ra"].isna().all()


# ---------------------------------------------------------------------------
# Tests for extract_ifgf
# ---------------------------------------------------------------------------

class TestExtractIfgf:
    """Unit tests for the extract_ifgf function."""

    def test_file_not_found_raises_with_url(self, tmp_path):
        """FileNotFoundError raised with download URL if IFGF file missing."""
        from scripts.extract_ifgf import extract_ifgf

        with pytest.raises(FileNotFoundError, match="firjan"):
            extract_ifgf(
                data_dir=tmp_path,
                output_dir=tmp_path / "out",
            )

    def test_writes_parquet(self, tmp_path, monkeypatch):
        """extract_ifgf writes a parquet file to the output directory."""
        from scripts.extract_ifgf import extract_ifgf

        # Copy fixture to expected location
        import shutil
        ifgf_dir = tmp_path / "data"
        ifgf_dir.mkdir()
        shutil.copy(
            IFGF_FIXTURE_PATH,
            ifgf_dir / "Evolucao_por_Indicador_2013_a_2024_IFGF_2025.xlsx",
        )
        # Mock validate_dataframe to skip IBGE reference check
        monkeypatch.setattr(
            "scripts.extract_ifgf.validate_dataframe",
            lambda df, **kw: (df, MagicMock()),
        )
        out_path = extract_ifgf(
            data_dir=ifgf_dir,
            output_dir=tmp_path / "out",
        )
        assert out_path.exists()
        result = pd.read_parquet(out_path)
        assert "cod_ibge" in result.columns
        assert "ifgf_geral" in result.columns
