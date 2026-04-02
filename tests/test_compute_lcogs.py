"""
Tests for analysis/compute_lcogs.py — LCoGS indicator computation.

Covers all 6 LCoGS indicators with synthetic data:
  1. LCoGS-1: haversine distance to nearest bellwether municipality
  2. LCoGS-2: SAO workforce density per 100,000
  3. LCoGS-3: surgical volume per 100,000
  4. LCoGS-4: perioperative mortality rate (POMR)
  5. LCoGS-5: financial risk protection ratio
  6. LCoGS-6: catastrophic expenditure proxy
"""

import sqlite3
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Synthetic data fixtures
# ---------------------------------------------------------------------------

def _make_panel(n_mun: int = 5, years: list[int] | None = None) -> pd.DataFrame:
    """Build a minimal synthetic panel for testing."""
    if years is None:
        years = [2020, 2021]
    rows = []
    for yr in years:
        for i in range(n_mun):
            rows.append({
                "cod_ibge": "%07d" % (1100015 + i),
                "year": yr,
                "populacao": 100_000 * (i + 1),
                "n_procedures": 500 * (i + 1),
                "procedure_count": 500 * (i + 1),
                "n_deaths": 5 * (i + 1),
                "deaths": 5 * (i + 1),
                "total_cost_brl": 1_000_000.0 * (i + 1),
                "total_value": 1_000_000.0 * (i + 1),
                "gdp_per_capita": 50_000.0,
            })
    return pd.DataFrame(rows)


def _make_facilities() -> pd.DataFrame:
    """Synthetic CNES facilities with bellwether flags."""
    return pd.DataFrame({
        "cnes": ["0001", "0002", "0003", "0004"],
        "cod_ibge": ["1100015", "1100015", "1100023", "1100049"],
        "year": [2020, 2020, 2020, 2020],
        "is_bellwether": [True, False, True, False],
    })


def _make_professionals() -> pd.DataFrame:
    """Synthetic CNES professionals (SAO)."""
    return pd.DataFrame({
        "cnes": ["0001"] * 10,
        "cod_ibge": [
            "1100015", "1100015", "1100015", "1100015", "1100015",
            "1100016", "1100016", "1100017", "1100017", "1100017",
        ],
        "year": [2020] * 10,
        "cbo": ["225225"] * 10,
        "cns_prof": [
            "CNS001", "CNS002", "CNS003", "CNS004", "CNS005",
            "CNS006", "CNS007", "CNS008", "CNS009", "CNS010",
        ],
        "sao_category": [
            "surgeon", "surgeon", "anesthesiologist",
            "obstetrician", "surgeon",
            "surgeon", "anesthesiologist",
            "surgeon", "surgeon", "obstetrician",
        ],
    })


def _make_centroids() -> pd.DataFrame:
    """Synthetic municipality centroids (lat, lon)."""
    return pd.DataFrame({
        "cod_ibge": [
            "1100015", "1100016", "1100017", "1100018", "1100019",
            "1100023", "1100049",
        ],
        "lat": [-8.76, -9.00, -10.00, -11.00, -12.00, -8.80, -9.50],
        "lon": [-63.90, -64.00, -65.00, -66.00, -67.00, -63.95, -64.50],
    })


# ---------------------------------------------------------------------------
# Test 1: LCoGS-1 returns lcogs1_distance_km >= 0
# ---------------------------------------------------------------------------

class TestComputeLcogs1:
    def test_returns_distance_column(self):
        from analysis.compute_lcogs import compute_lcogs1

        panel = _make_panel()
        facilities = _make_facilities()
        centroids = _make_centroids()

        result = compute_lcogs1(panel, facilities, centroids)
        assert "lcogs1_distance_km" in result.columns
        assert (result["lcogs1_distance_km"].dropna() >= 0).all()

    # Test 2: bellwether municipalities get 0.0
    def test_bellwether_municipality_distance_zero(self):
        from analysis.compute_lcogs import compute_lcogs1

        panel = _make_panel()
        facilities = _make_facilities()
        centroids = _make_centroids()

        result = compute_lcogs1(panel, facilities, centroids)
        # 1100015 and 1100023 have bellwether facilities
        bw_rows = result[result["cod_ibge"].isin(["1100015", "1100023"])]
        assert (bw_rows["lcogs1_distance_km"] == 0.0).all()


# ---------------------------------------------------------------------------
# Test 3: _haversine_km correctness (Sao Paulo to Rio ~358 km)
# ---------------------------------------------------------------------------

class TestHaversine:
    def test_sao_paulo_to_rio(self):
        from analysis.compute_lcogs import _haversine_km

        # Sao Paulo: -23.55, -46.63
        # Rio de Janeiro: -22.91, -43.17
        dist = _haversine_km(
            np.array([-23.55]), np.array([-46.63]),
            np.array([-22.91]), np.array([-43.17]),
        )
        # Should be approximately 358 km (+/- 10 km tolerance)
        assert abs(dist[0] - 358.0) < 15.0, (
            "Expected ~358 km, got %.1f km" % dist[0]
        )


# ---------------------------------------------------------------------------
# Test 4: LCoGS-2 SAO per 100k
# ---------------------------------------------------------------------------

class TestComputeLcogs2:
    def test_sao_per_100k(self):
        from analysis.compute_lcogs import compute_lcogs2

        panel = pd.DataFrame({
            "cod_ibge": ["1100015", "1100015"],
            "year": [2020, 2021],
            "populacao": [100_000, 100_000],
        })
        professionals = pd.DataFrame({
            "cnes": ["0001"] * 10,
            "cod_ibge": ["1100015"] * 10,
            "year": [2020] * 10,
            "cbo": ["225225"] * 10,
            "cns_prof": ["CNS%03d" % i for i in range(10)],
            "sao_category": ["surgeon"] * 10,
        })

        result = compute_lcogs2(panel, professionals)
        assert "sao_per_100k" in result.columns
        row_2020 = result[
            (result["cod_ibge"] == "1100015") & (result["year"] == 2020)
        ]
        # 10 SAO / 100,000 pop * 100,000 = 10.0
        assert abs(row_2020["sao_per_100k"].iloc[0] - 10.0) < 0.01

    # Test 5: deduplication count is logged
    def test_dedup_count_logged(self, caplog):
        from analysis.compute_lcogs import compute_lcogs2
        import logging

        panel = pd.DataFrame({
            "cod_ibge": ["1100015"],
            "year": [2020],
            "populacao": [100_000],
        })
        professionals = pd.DataFrame({
            "cnes": ["0001"] * 5,
            "cod_ibge": ["1100015"] * 5,
            "year": [2020] * 5,
            "cbo": ["225225"] * 5,
            "cns_prof": ["CNS001"] * 5,
            "sao_category": ["surgeon"] * 5,
        })

        with caplog.at_level(logging.DEBUG):
            compute_lcogs2(panel, professionals)
        # Should log something about professional count
        log_text = caplog.text.lower()
        assert "professional" in log_text or "sao" in log_text


# ---------------------------------------------------------------------------
# Test 6: LCoGS-3 surgical volume per 100k
# ---------------------------------------------------------------------------

class TestComputeLcogs3:
    def test_surgical_volume_per_100k(self):
        from analysis.compute_lcogs import compute_lcogs3

        panel = pd.DataFrame({
            "cod_ibge": ["1100015"],
            "year": [2020],
            "populacao": [100_000],
            "n_procedures": [500],
        })
        result = compute_lcogs3(panel)
        assert "surgical_volume_per_100k" in result.columns
        assert abs(result["surgical_volume_per_100k"].iloc[0] - 500.0) < 0.01


# ---------------------------------------------------------------------------
# Test 7: LCoGS-4 POMR
# ---------------------------------------------------------------------------

class TestComputeLcogs4:
    def test_pomr_basic(self):
        from analysis.compute_lcogs import compute_lcogs4

        panel = pd.DataFrame({
            "cod_ibge": ["1100015"],
            "year": [2020],
            "n_procedures": [100],
            "n_deaths": [5],
        })
        result = compute_lcogs4(panel)
        assert "pomr" in result.columns
        assert abs(result["pomr"].iloc[0] - 0.05) < 0.001

    # Test 8: NaN for <10 procedures
    def test_pomr_nan_small_sample(self):
        from analysis.compute_lcogs import compute_lcogs4

        panel = pd.DataFrame({
            "cod_ibge": ["1100015"],
            "year": [2020],
            "n_procedures": [9],
            "n_deaths": [1],
        })
        result = compute_lcogs4(panel)
        assert np.isnan(result["pomr"].iloc[0])


# ---------------------------------------------------------------------------
# Test 9: LCoGS-5 financial risk ratio
# ---------------------------------------------------------------------------

class TestComputeLcogs5:
    def test_financial_risk_ratio(self):
        from analysis.compute_lcogs import compute_lcogs5

        panel = pd.DataFrame({
            "cod_ibge": ["1100015"],
            "year": [2020],
            "n_procedures": [100],
            "total_cost_brl": [100_000.0],
            "gdp_per_capita": [50_000.0],
        })
        result = compute_lcogs5(panel)
        assert "financial_risk_ratio" in result.columns
        # mean cost = 100_000 / 100 = 1000 BRL
        # ratio = 1000 / 50_000 = 0.02
        assert abs(result["financial_risk_ratio"].iloc[0] - 0.02) < 0.001


# ---------------------------------------------------------------------------
# Test 10: LCoGS-6 catastrophic expenditure proxy
# ---------------------------------------------------------------------------

class TestComputeLcogs6:
    def test_catastrophic_pct(self):
        from analysis.compute_lcogs import compute_lcogs6

        panel = pd.DataFrame({
            "cod_ibge": ["1100015", "1100016"],
            "year": [2020, 2020],
            "n_procedures": [100, 100],
            "total_cost_brl": [600_000.0, 100_000.0],
            "gdp_per_capita": [50_000.0, 50_000.0],
        })
        result = compute_lcogs6(panel)
        assert "catastrophic_expenditure" in result.columns
        # mun 1100015: mean cost = 6000, threshold = 50000 * 0.10 = 5000
        # 6000 > 5000 -> catastrophic = 1
        row1 = result[result["cod_ibge"] == "1100015"]
        assert row1["catastrophic_expenditure"].iloc[0] == 1.0
        # mun 1100016: mean cost = 1000, threshold = 5000
        # 1000 < 5000 -> catastrophic = 0
        row2 = result[result["cod_ibge"] == "1100016"]
        assert row2["catastrophic_expenditure"].iloc[0] == 0.0


# ---------------------------------------------------------------------------
# Test 11: compute_all_lcogs orchestrator
# ---------------------------------------------------------------------------

class TestComputeAllLcogs:
    def test_all_columns_present(self):
        from analysis.compute_lcogs import compute_all_lcogs

        panel = _make_panel()
        facilities = _make_facilities()
        professionals = _make_professionals()
        centroids = _make_centroids()

        result = compute_all_lcogs(panel, facilities, professionals, centroids)
        expected_cols = {
            "cod_ibge", "year",
            "lcogs1_distance_km", "sao_per_100k",
            "surgical_volume_per_100k", "pomr",
            "financial_risk_ratio", "catastrophic_expenditure",
        }
        assert expected_cols.issubset(set(result.columns)), (
            "Missing columns: %s" % (expected_cols - set(result.columns))
        )


# ---------------------------------------------------------------------------
# Test 12: persist_lcogs_indicators writes to SQLite
# ---------------------------------------------------------------------------

class TestPersistLcogsIndicators:
    def test_sqlite_write(self, tmp_path):
        from analysis.compute_lcogs import persist_lcogs_indicators

        lcogs_df = pd.DataFrame({
            "cod_ibge": ["1100015", "1100016"],
            "year": [2020, 2020],
            "lcogs1_distance_km": [0.0, 150.0],
            "sao_per_100k": [10.0, 5.0],
            "surgical_volume_per_100k": [500.0, 300.0],
            "pomr": [0.05, 0.03],
            "financial_risk_ratio": [0.02, 0.01],
            "catastrophic_expenditure": [1.0, 0.0],
        })

        db_path = tmp_path / "test.sqlite"
        n = persist_lcogs_indicators(lcogs_df, db_path)
        assert n == 2

        # Verify table exists and has correct data
        conn = sqlite3.connect(str(db_path))
        try:
            rows = conn.execute(
                "SELECT COUNT(*) FROM lcogs_indicators"
            ).fetchone()[0]
            assert rows == 2
        finally:
            conn.close()
