"""
Smoke fixture builder for ICSKG-BR end-to-end tests.

This script generates a tiny but valid parquet tree under
tests/fixtures/processed_smoke/ that populates every source from
database/assemble_panel.py::SOURCE_CATALOG with a deterministic
5-municipality × 2-year minimal dataset.

Purpose
-------
After this fixture exists, the full ETL chain
(assemble_panel → impute_ifgf_mice → build_database) can run
end-to-end on a fresh clone with NO NAS access and NO HuggingFace
network calls. The CI smoke workflow uses this fixture for fast
feedback (<5 min) on every push and PR.

Important detail about row counts
---------------------------------
`assemble_panel` builds its scaffold from the FULL 5,571-municipality
IBGE 2023 reference list (`data_sources/ibge_municipios_2023.csv`),
so the resulting `municipal_health` table always has 5,571 × num_years
rows regardless of fixture size. This fixture only provides values
for 5 municipalities × 2 years = 10 rows; the remaining rows are
NaN after the left-merge. That is intentional and correct for a
smoke test — the goal is to exercise the pipeline code paths, not
to produce a realistic panel.

Determinism
-----------
- No random data, no timestamps in column values, no system-dependent ordering
- Fixed pandas write order (sort by cod_ibge, year)
- zstd compression level 6 (matches scripts/publish_to_hf.py)
- Re-running this script may produce slightly different parquet bytes
  due to embedded metadata (creation timestamps) but the LOGICAL data
  is byte-identical. The smoke tests verify logical equality, not
  byte equality.

Usage
-----
    cd /path/to/ICSKG
    uv run python tests/fixtures/build_smoke_fixture.py

After running, commit the regenerated tests/fixtures/processed_smoke/
contents.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Constants — 5 real Brazilian municipalities, one per macro-region
# ---------------------------------------------------------------------------

# (cod_ibge, name, uf, region) — one per Brazilian macro-region
MUNICIPALITIES: list[tuple[str, str, str, str]] = [
    ("3550308", "São Paulo",       "SP", "Sudeste"),
    ("2611606", "Recife",          "PE", "Nordeste"),
    ("4314902", "Porto Alegre",    "RS", "Sul"),
    ("5300108", "Brasília",        "DF", "Centro-Oeste"),
    ("1302603", "Manaus",          "AM", "Norte"),
]

YEARS: list[int] = [2022, 2023]

# Output root (committed to git)
FIXTURE_ROOT = Path(__file__).parent / "processed_smoke"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_panel_index() -> pd.DataFrame:
    """Return a 10-row (cod_ibge, year) DataFrame as the per-source base."""
    rows = []
    for cod, _name, _uf, _region in MUNICIPALITIES:
        for year in YEARS:
            rows.append({"cod_ibge": cod, "year": year})
    return pd.DataFrame(rows).sort_values(["cod_ibge", "year"]).reset_index(drop=True)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_parquet(df: pd.DataFrame, path: Path) -> dict:
    """Write a deterministic parquet file and return manifest entry."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # zstd6 to match publish_to_hf.py compression
    df.to_parquet(
        path,
        compression="zstd",
        compression_level=6,
        index=False,
    )
    rel = path.relative_to(FIXTURE_ROOT).as_posix()
    return {
        "path": rel,
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
        "size_bytes": int(path.stat().st_size),
        "sha256": _sha256(path),
        "schema": [{"name": str(c), "dtype": str(df[c].dtype)} for c in df.columns],
    }


# ---------------------------------------------------------------------------
# Per-source builders — match SOURCE_CATALOG in database/assemble_panel.py
# ---------------------------------------------------------------------------


def build_sih(base: pd.DataFrame) -> pd.DataFrame:
    """sih/*.parquet — surgical activity aggregates."""
    df = base.copy()
    # Synthetic but deterministic small values
    df["procedure_count"] = [100 + i * 10 for i in range(len(df))]
    df["total_value"] = [50000.0 + i * 5000.0 for i in range(len(df))]  # BRL
    df["deaths"] = [1 + (i % 3) for i in range(len(df))]
    df["aih_count"] = [120 + i * 12 for i in range(len(df))]
    df["total_days"] = [350 + i * 30 for i in range(len(df))]
    return df


def build_cnes_facilities(base: pd.DataFrame) -> pd.DataFrame:
    """cnes/facilities_*.parquet — bellwether hospitals."""
    df = base.copy()
    df["total_beds"] = [50 + i * 5 for i in range(len(df))]
    df["is_bellwether"] = [(i % 2 == 0) for i in range(len(df))]
    return df


def build_cnes_professionals(base: pd.DataFrame) -> pd.DataFrame:
    """cnes/professionals_*.parquet — surgeon/anesthesiologist density inputs."""
    df = base.copy()
    # sao_category is categorical — fixture uses small integer code
    df["sao_category"] = [1 + (i % 3) for i in range(len(df))]
    return df


def build_population(base: pd.DataFrame) -> pd.DataFrame:
    """ibge_sidra/population.parquet — IBGE population estimates."""
    df = base.copy()
    df["populacao"] = [
        12_300_000, 12_400_000,  # SP
         1_650_000,  1_660_000,  # PE Recife
         1_490_000,  1_495_000,  # RS Porto Alegre
         3_050_000,  3_060_000,  # DF Brasília
         2_220_000,  2_225_000,  # AM Manaus
    ]
    return df


def build_gdp_per_capita(base: pd.DataFrame) -> pd.DataFrame:
    """ibge_sidra/gdp_per_capita.parquet — GDP + per-capita."""
    df = base.copy()
    df["gdp_abs"] = [
        850_000_000, 870_000_000,  # SP (in thousands BRL)
         60_000_000,  62_000_000,  # PE Recife
         85_000_000,  88_000_000,  # RS Porto Alegre
        260_000_000, 270_000_000,  # DF Brasília
         90_000_000,  93_000_000,  # AM Manaus
    ]
    df["gdp_estimated"] = [False, True, False, True, False, True, False, True, False, True]
    df["gdp_per_capita"] = [
        69100.0, 70200.0,
        36400.0, 37300.0,
        57000.0, 58800.0,
        85200.0, 88200.0,
        40500.0, 41800.0,
    ]
    return df


def build_idhm() -> pd.DataFrame:
    """ipea_idhm/idhm.parquet — cross-sectional, replicated by assemble_panel."""
    rows = []
    for cod, _name, _uf, _region in MUNICIPALITIES:
        rows.append({"cod_ibge": cod})
    df = pd.DataFrame(rows)
    df["idhm"] = [0.805, 0.772, 0.805, 0.824, 0.737]
    df["idhm_educacao"] = [0.730, 0.690, 0.731, 0.742, 0.654]
    df["idhm_longevidade"] = [0.853, 0.836, 0.857, 0.873, 0.821]
    df["idhm_renda"] = [0.843, 0.799, 0.836, 0.863, 0.748]
    return df


def build_ifgf(base: pd.DataFrame) -> pd.DataFrame:
    """ifgf/ifgf.parquet — FIRJAN fiscal management index."""
    df = base.copy()
    df["ifgf_geral"] = [0.65, 0.67, 0.51, 0.53, 0.58, 0.60, 0.71, 0.72, 0.49, 0.51]
    df["ifgf_ra"] = [0.70, 0.72, 0.55, 0.56, 0.62, 0.64, 0.74, 0.75, 0.52, 0.54]
    df["ifgf_gp"] = [0.62, 0.64, 0.48, 0.50, 0.55, 0.57, 0.69, 0.71, 0.46, 0.48]
    df["ifgf_id"] = [0.60, 0.61, 0.45, 0.47, 0.53, 0.55, 0.66, 0.68, 0.43, 0.45]
    df["ifgf_el"] = [0.66, 0.68, 0.52, 0.53, 0.59, 0.61, 0.72, 0.73, 0.50, 0.52]
    df["ifgf_sa"] = [0.68, 0.70, 0.55, 0.57, 0.61, 0.63, 0.74, 0.75, 0.53, 0.55]
    return df


def build_ans(base: pd.DataFrame) -> pd.DataFrame:
    """ans/ans_quarterly.parquet — private insurance coverage."""
    df = base.copy()
    df["beneficiarios_mean"] = [
        5_900_000, 6_000_000,
          550_000,   560_000,
          540_000,   545_000,
          800_000,   820_000,
          480_000,   490_000,
    ]
    df["private_coverage_rate"] = [
        0.480, 0.484,
        0.333, 0.337,
        0.362, 0.364,
        0.262, 0.268,
        0.216, 0.220,
    ]
    df["sus_dependence_rate"] = [
        0.520, 0.516,
        0.667, 0.663,
        0.638, 0.636,
        0.738, 0.732,
        0.784, 0.780,
    ]
    return df


def build_census_sanitation() -> pd.DataFrame:
    """census_sanitation/sanitation.parquet — cross-sectional 2022 census."""
    rows = []
    for cod, _name, _uf, _region in MUNICIPALITIES:
        rows.append({"cod_ibge": cod})
    df = pd.DataFrame(rows)
    df["pct_sanitation_adequate"] = [0.825, 0.512, 0.882, 0.880, 0.260]
    df["pct_water_adequate"] = [0.974, 0.880, 0.985, 0.984, 0.730]
    return df


def build_renavam(base: pd.DataFrame) -> pd.DataFrame:
    """renavam/renavam.parquet — vehicle fleet density."""
    df = base.copy()
    df["vehicles_total"] = [
        7_900_000, 8_000_000,
          720_000,   730_000,
          900_000,   910_000,
        1_900_000, 1_950_000,
          780_000,   790_000,
    ]
    df["vehicles_per_1000"] = [
        642.3, 645.2,
        436.4, 439.8,
        604.0, 608.7,
        623.0, 637.3,
        351.4, 355.1,
    ]
    return df


def build_siops(base: pd.DataFrame) -> pd.DataFrame:
    """siops/siops.parquet — per-capita health expenditure (BRL)."""
    df = base.copy()
    df["health_expenditure_per_capita"] = [
        1850.0, 1920.0,
         920.0,  960.0,
        1320.0, 1380.0,
        2540.0, 2620.0,
        1080.0, 1130.0,
    ]
    return df


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


SOURCE_BUILDERS: dict[str, tuple[str, Callable[..., pd.DataFrame]]] = {
    "sih/sih.parquet":                       ("ts", build_sih),
    "cnes/facilities_smoke.parquet":         ("ts", build_cnes_facilities),
    "cnes/professionals_smoke.parquet":      ("ts", build_cnes_professionals),
    "ibge_sidra/population.parquet":         ("ts", build_population),
    "ibge_sidra/gdp_per_capita.parquet":     ("ts", build_gdp_per_capita),
    "ipea_idhm/idhm.parquet":                ("xs", build_idhm),
    "ifgf/ifgf.parquet":                     ("ts", build_ifgf),
    "ans/ans_quarterly.parquet":             ("ts", build_ans),
    "census_sanitation/sanitation.parquet":  ("xs", build_census_sanitation),
    "renavam/renavam.parquet":               ("ts", build_renavam),
    "siops/siops.parquet":                   ("ts", build_siops),
}


def main() -> int:
    print("─" * 70)
    print("Building ICSKG-BR smoke fixture")
    print("Output: %s" % FIXTURE_ROOT)
    print("Municipalities: %d, years: %s" % (len(MUNICIPALITIES), YEARS))
    print("─" * 70)

    # Wipe and recreate fixture root for full determinism
    if FIXTURE_ROOT.exists():
        shutil.rmtree(FIXTURE_ROOT)
    FIXTURE_ROOT.mkdir(parents=True)

    base = _build_panel_index()
    print("\nPanel index: %d rows" % len(base))

    manifest_entries = []
    total_rows = 0

    for rel_path, (kind, builder) in SOURCE_BUILDERS.items():
        out_path = FIXTURE_ROOT / rel_path
        if kind == "ts":
            df = builder(base)
        elif kind == "xs":
            df = builder()
        else:
            raise ValueError("Unknown kind: %s" % kind)

        # Sanity check shapes
        if "cod_ibge" not in df.columns:
            raise ValueError("Source %s missing cod_ibge column" % rel_path)

        df = df.sort_values(
            [c for c in ("cod_ibge", "year") if c in df.columns]
        ).reset_index(drop=True)

        entry = _write_parquet(df, out_path)
        manifest_entries.append({"namespace": rel_path.split("/")[0], **entry})
        total_rows += entry["row_count"]
        print(
            "  ✓ %-42s %d rows, %d cols, %.2f KB"
            % (rel_path, entry["row_count"], entry["column_count"], entry["size_bytes"] / 1024)
        )

    # Write manifest.json
    manifest = {
        "fixture_name": "ICSKG-BR smoke fixture",
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "municipalities": [
            {"cod_ibge": cod, "name": name, "uf": uf, "region": region}
            for cod, name, uf, region in MUNICIPALITIES
        ],
        "years": YEARS,
        "totals": {
            "table_count": len(manifest_entries),
            "row_count": total_rows,
            "size_bytes": sum(e["size_bytes"] for e in manifest_entries),
        },
        "files": manifest_entries,
    }
    manifest_path = FIXTURE_ROOT / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print("\nWrote manifest.json (%d entries)" % len(manifest_entries))

    # Compute total tree size
    total_size = sum(p.stat().st_size for p in FIXTURE_ROOT.rglob("*") if p.is_file())
    print("─" * 70)
    print("Done. Total tree size: %.2f KB across %d files" % (
        total_size / 1024,
        sum(1 for _ in FIXTURE_ROOT.rglob("*") if _.is_file()),
    ))
    print("─" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
