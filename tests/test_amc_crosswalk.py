"""Tests for the AMC municipality boundary crosswalk."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

CROSSWALK_PATH = Path(__file__).parent.parent / "data_sources" / "amc_crosswalk_2015_2023.csv"
IBGE_REF_PATH = Path(__file__).parent.parent / "data_sources" / "ibge_municipios_2023.csv"


def load_crosswalk() -> pd.DataFrame:
    if not CROSSWALK_PATH.exists():
        pytest.skip("amc_crosswalk_2015_2023.csv not yet generated")
    return pd.read_csv(
        CROSSWALK_PATH,
        dtype={"cod_ibge_original": str, "cod_ibge_2023": str},
    )


def _ibge_count() -> int:
    """Return the number of canonical municipalities in the IBGE reference."""
    if not IBGE_REF_PATH.exists():
        pytest.skip("ibge_municipios_2023.csv not available")
    return len(pd.read_csv(IBGE_REF_PATH, dtype={"cod_ibge": str}))


class TestCrosswalkStructure:
    def test_required_columns(self):
        cw = load_crosswalk()
        for col in [
            "cod_ibge_original",
            "year_valid_from",
            "cod_ibge_2023",
            "harmonization_type",
        ]:
            assert col in cw.columns, f"Missing column: {col}"

    def test_stable_rows_cover_all_canonical(self):
        cw = load_crosswalk()
        expected = _ibge_count()
        stable = cw[cw["harmonization_type"] == "stable"]
        assert len(stable) == expected, (
            f"Expected {expected} stable rows, got {len(stable)}"
        )

    def test_no_duplicate_stable_codes(self):
        cw = load_crosswalk()
        expected = _ibge_count()
        stable = cw[cw["harmonization_type"] == "stable"]
        assert stable["cod_ibge_original"].nunique() == expected

    def test_all_cod_ibge_2023_are_7_digits(self):
        cw = load_crosswalk()
        assert cw["cod_ibge_2023"].str.len().eq(7).all()


class TestKnownSplits:
    """Verify that known 2013 emancipations appear correctly in the crosswalk."""

    def test_balneario_rincao_mapped(self):
        """Balneario Rincao (4201257) should appear as a stable 2023 municipality."""
        cw = load_crosswalk()
        row = cw[cw["cod_ibge_original"] == "4201257"]
        assert len(row) >= 1, "Balneario Rincao-SC (4201257) not in crosswalk"
        assert row.iloc[0]["cod_ibge_2023"] == "4201257"

    def test_pinto_bandeira_mapped(self):
        """Pinto Bandeira (4314548) should appear as a stable 2023 municipality."""
        cw = load_crosswalk()
        row = cw[cw["cod_ibge_original"] == "4314548"]
        assert len(row) >= 1, "Pinto Bandeira-RS (4314548) not in crosswalk"
        assert row.iloc[0]["cod_ibge_2023"] == "4314548"

    def test_pescaria_brava_mapped(self):
        """Pescaria Brava (4212056) should appear as a stable 2023 municipality."""
        cw = load_crosswalk()
        row = cw[cw["cod_ibge_original"] == "4212056"]
        assert len(row) >= 1, "Pescaria Brava-SC (4212056) not in crosswalk"
        assert row.iloc[0]["cod_ibge_2023"] == "4212056"

    def test_mojui_dos_campos_mapped(self):
        """Mojui dos Campos (1504752) should appear as a stable 2023 municipality."""
        cw = load_crosswalk()
        row = cw[cw["cod_ibge_original"] == "1504752"]
        assert len(row) >= 1, "Mojui dos Campos-PA (1504752) not in crosswalk"
        assert row.iloc[0]["cod_ibge_2023"] == "1504752"

    def test_stable_identity_mapping(self):
        """A stable municipality (Sao Paulo) maps to itself."""
        cw = load_crosswalk()
        sp = cw[cw["cod_ibge_original"] == "3550308"]
        assert len(sp) == 1
        assert sp.iloc[0]["cod_ibge_2023"] == "3550308"
        assert sp.iloc[0]["harmonization_type"] == "stable"


class TestApplyAMCCrosswalk:
    def test_stable_municipality_unchanged(self):
        """Sao Paulo's cod_ibge should be unchanged after applying the crosswalk."""
        from build_amc_crosswalk import apply_amc_crosswalk  # noqa: PLC0415

        df = pd.DataFrame({"cod_ibge": ["3550308", "1100015"], "value": [1, 2]})
        result = apply_amc_crosswalk(df, year=2023)
        assert result["cod_ibge"].tolist() == ["3550308", "1100015"]

    def test_raises_without_cod_ibge_column(self):
        from build_amc_crosswalk import apply_amc_crosswalk  # noqa: PLC0415

        df = pd.DataFrame({"Cod_IBGE": ["3550308"], "value": [1]})
        with pytest.raises(ValueError, match="must have a 'cod_ibge' column"):
            apply_amc_crosswalk(df, year=2023)

    def test_does_not_mutate_original_dataframe(self):
        """apply_amc_crosswalk should return a copy, not mutate the input."""
        from build_amc_crosswalk import apply_amc_crosswalk  # noqa: PLC0415

        df = pd.DataFrame({"cod_ibge": ["3550308"], "value": [1]})
        original_values = df["cod_ibge"].tolist()
        _ = apply_amc_crosswalk(df, year=2023)
        assert df["cod_ibge"].tolist() == original_values
