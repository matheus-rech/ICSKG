"""
ICSKG-BR Database – Aggregated Extraction Pipeline
===================================================
Orchestrates the end-to-end extraction, transformation, and loading (ETL) of
all data sources required by the ICSKG-BR project:

  1. SIH (Sistema de Informações Hospitalares) – inpatient microdata
  2. CNES (Cadastro Nacional de Estabelecimentos de Saúde) – facility registry
  3. ANS (Agência Nacional de Saúde Suplementar) – private-coverage beneficiaries
  4. IFGF (Índice FIRJAN de Gestão Fiscal) – municipal fiscal management scores

The pipeline can be run for a single year-month or for the full historical
window (2013–2024).

Usage
-----
    python database/pipeline.py --year 2023 --month 12
    python database/pipeline.py --start 2013-01 --end 2024-12
"""

import argparse
import logging
import os
import sys
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# ---------------------------------------------------------------------------
# Stage definitions
# ---------------------------------------------------------------------------

STAGES = [
    "extract_sih",
    "extract_cnes",
    "extract_ans",
    "extract_ifgf",
    "transform_merge",
    "load_database",
]


def _stage_banner(name: str) -> None:
    logger.info("─" * 60)
    logger.info("STAGE: %s", name.upper())
    logger.info("─" * 60)


# ---------------------------------------------------------------------------
# Extraction stubs
# (full implementations live in the source-specific scripts under scripts/)
# ---------------------------------------------------------------------------

def extract_sih(year: int, month: int, raw_dir: Path) -> Path:
    """Download and parse SIH inpatient records for the given year-month.

    Returns the path to the parquet file written to *raw_dir*.
    """
    _stage_banner("extract_sih")
    from scripts.sih_batch_v2 import process_month  # noqa: PLC0415

    output = raw_dir / f"sih_{year}{month:02d}.parquet"
    logger.info("Extracting SIH %04d-%02d → %s", year, month, output)
    process_month(year=year, month=month, output_path=output)
    return output


def extract_cnes(year: int, month: int, raw_dir: Path) -> Path:
    """Download CNES facility snapshot for the given year-month."""
    _stage_banner("extract_cnes")
    output = raw_dir / f"cnes_{year}{month:02d}.parquet"
    logger.info("Extracting CNES %04d-%02d → %s", year, month, output)
    # Delegated to continue_raw_download which handles both SIH and CNES
    from scripts.continue_raw_download import download_month  # noqa: PLC0415

    download_month(source="CNES", year=year, month=month, output_path=output)
    return output


def extract_ans(data_dir: Path) -> Path:
    """Extract ANS beneficiary snapshot (latest available)."""
    _stage_banner("extract_ans")
    from scripts.download_ans import download_latest  # noqa: PLC0415

    output = data_dir / "ans_beneficiarios_latest.parquet"
    logger.info("Extracting ANS beneficiaries → %s", output)
    download_latest(output_path=output)
    return output


def extract_ifgf(data_dir: Path) -> Path:
    """Return path to the pre-bundled IFGF Excel file."""
    _stage_banner("extract_ifgf")
    path = data_dir / "Evolucao_por_Indicador_2013_a_2024_IFGF_2025.xlsx"
    if not path.exists():
        raise FileNotFoundError(
            f"IFGF source file not found: {path}\n"
            "Download from https://www.firjan.com.br/ifgf/ and place it in data_sources/."
        )
    logger.info("IFGF source located at %s", path)
    return path


# ---------------------------------------------------------------------------
# Transform / merge
# ---------------------------------------------------------------------------

def transform_merge(
    sih_path: Path,
    cnes_path: Path,
    ans_path: Path,
    ifgf_path: Path,
    year: int,
    month: int,
    processed_dir: Path,
) -> Path:
    """Merge all extracted artefacts into a single municipality-level parquet."""
    _stage_banner("transform_merge")
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("pandas is required for transform_merge") from exc

    output = processed_dir / f"merged_{year}{month:02d}.parquet"
    logger.info("Merging sources into %s", output)

    frames = {}
    for label, path in [
        ("sih", sih_path),
        ("cnes", cnes_path),
        ("ans", ans_path),
        ("ifgf", ifgf_path),
    ]:
        if path is None or not path.exists():
            logger.warning("Source %s not found at %s – skipping.", label, path)
            continue
        try:
            if path.suffix == ".parquet":
                frames[label] = pd.read_parquet(path)
            elif path.suffix in (".xlsx", ".xls"):
                frames[label] = pd.read_excel(path, dtype={"Cod_IBGE": str})
            elif path.suffix == ".csv":
                frames[label] = pd.read_csv(path, dtype={"CD_MUNICIPIO": str}, sep=";", encoding="latin-1")
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to read %s: %s", path, exc)

    if not frames:
        logger.warning("No source frames available – writing empty output.")
        import pandas as pd  # noqa: PLC0415

        pd.DataFrame().to_parquet(output)
        return output

    # Simple outer join on municipality code (cod_ibge / Cod_IBGE)
    merged = None
    for label, df in frames.items():
        # Normalise municipality column name
        for col in ("Cod_IBGE", "CD_MUNICIPIO", "cod_ibge"):
            if col in df.columns:
                df = df.rename(columns={col: "cod_ibge"})
                break
        df = df.add_prefix(f"{label}_").rename(columns={f"{label}_cod_ibge": "cod_ibge"})
        merged = df if merged is None else merged.merge(df, on="cod_ibge", how="outer")

    processed_dir.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(output, index=False)
    logger.info("Merged %d municipalities → %s", len(merged), output)
    return output


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load_database(merged_path: Path, db_dir: Path) -> None:
    """Append merged month to the cumulative DuckDB/SQLite database."""
    _stage_banner("load_database")
    try:
        import duckdb
        db_path = db_dir / "icskg_br.duckdb"
        con = duckdb.connect(str(db_path))
        con.execute(
            f"INSERT INTO municipal_health SELECT * FROM read_parquet('{merged_path}')"
        )
        con.close()
        logger.info("Loaded %s into %s", merged_path, db_path)
    except ImportError:
        logger.warning("duckdb not installed – skipping database load.")
    except Exception as exc:  # noqa: BLE001
        logger.error("Database load failed: %s", exc)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_pipeline(
    year: int,
    month: int,
    data_dir: Path = Path("data_sources"),
    raw_dir: Path = Path("data_sources/raw"),
    processed_dir: Path = Path("data_sources/processed"),
    db_dir: Path = Path("database"),
    stages: list = None,
) -> None:
    """Run the full ETL pipeline for a single year-month."""
    if stages is None:
        stages = STAGES

    raw_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, Path | None] = {
        "sih": None,
        "cnes": None,
        "ans": None,
        "ifgf": None,
    }

    if "extract_sih" in stages:
        try:
            results["sih"] = extract_sih(year, month, raw_dir)
        except Exception as exc:  # noqa: BLE001
            logger.error("extract_sih failed: %s", exc)

    if "extract_cnes" in stages:
        try:
            results["cnes"] = extract_cnes(year, month, raw_dir)
        except Exception as exc:  # noqa: BLE001
            logger.error("extract_cnes failed: %s", exc)

    if "extract_ans" in stages:
        try:
            results["ans"] = extract_ans(data_dir)
        except Exception as exc:  # noqa: BLE001
            logger.error("extract_ans failed: %s", exc)

    if "extract_ifgf" in stages:
        try:
            results["ifgf"] = extract_ifgf(data_dir)
        except Exception as exc:  # noqa: BLE001
            logger.error("extract_ifgf failed: %s", exc)

    if "transform_merge" in stages:
        try:
            merged_path = transform_merge(
                sih_path=results["sih"],
                cnes_path=results["cnes"],
                ans_path=results["ans"],
                ifgf_path=results["ifgf"],
                year=year,
                month=month,
                processed_dir=processed_dir,
            )
            results["merged"] = merged_path
        except Exception as exc:  # noqa: BLE001
            logger.error("transform_merge failed: %s", exc)
            results["merged"] = None

    if "load_database" in stages and results.get("merged"):
        try:
            load_database(results["merged"], db_dir)
        except Exception as exc:  # noqa: BLE001
            logger.error("load_database failed: %s", exc)


def _iter_months(start: str, end: str):
    """Yield (year, month) tuples between *start* and *end* (inclusive).

    Parameters
    ----------
    start, end : str
        In "YYYY-MM" format.
    """
    sy, sm = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    y, m = sy, sm
    while (y, m) <= (ey, em):
        yield y, m
        m += 1
        if m > 12:
            m = 1
            y += 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description="ICSKG-BR aggregated extraction pipeline")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--year-month", metavar="YYYY-MM", help="Single year-month to process")
    group.add_argument("--start", metavar="YYYY-MM", help="Start of date range")

    parser.add_argument("--end", metavar="YYYY-MM", help="End of date range (required with --start)")
    parser.add_argument("--data-dir", default="data_sources", help="Root data directory")
    parser.add_argument("--db-dir", default="database", help="Database output directory")
    parser.add_argument(
        "--stages",
        nargs="+",
        choices=STAGES,
        default=STAGES,
        help="Specific pipeline stages to run (default: all)",
    )
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir)
    db_dir = Path(args.db_dir)

    if args.year_month:
        y, m = map(int, args.year_month.split("-"))
        months = [(y, m)]
    else:
        if not args.end:
            parser.error("--end is required when using --start")
        months = list(_iter_months(args.start, args.end))

    logger.info("Processing %d month(s) …", len(months))
    for year, month in months:
        logger.info("▶ %04d-%02d", year, month)
        run_pipeline(
            year=year,
            month=month,
            data_dir=data_dir,
            db_dir=db_dir,
            stages=args.stages,
        )

    logger.info("All months processed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
