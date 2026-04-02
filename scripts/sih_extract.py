"""
SIH ETLSIH CSV Extraction Pipeline
====================================
Reads FIOCRUZ BigData ETLSIH CSV files from NAS (or local directory),
applies DuckDB column projection to select 27 of 235 available columns,
normalizes municipality codes, deduplicates by N_AIH, and writes per-state
monthly Parquet files.

This module REPLACES the DBC-reading logic in sih_batch_v2.py but keeps the
same structural patterns (multiprocessing, idempotent output, column subsetting).

Outputs
-------
Per-state monthly Parquet files at:
    data_sources/processed/sih/{UF}_{YYYYMM}.parquet

Data requirements
-----------------
ETLSIH CSV files at NAS mount or local directory. File naming pattern:
    ETLSIH.ST_{UF}_{YEAR}_{MONTH}_t.csv

Usage
-----
    # Single month
    python scripts/sih_extract.py --year-month 2023-01

    # Date range with parallelism
    python scripts/sih_extract.py --start 2015-01 --end 2023-12 --workers 4

    # Specific states only
    python scripts/sih_extract.py --year-month 2023-01 --ufs SP RJ MG
"""

import argparse
import logging
import multiprocessing
import sys
from functools import partial
from pathlib import Path

import duckdb
import pandas as pd

from database.utils import normalize_cod_ibge

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SIH_COLS_KEEP: list[str] = [
    "UF_ZI",        # State of hospitalisation (6-digit code)
    "ANO_CMPT",     # Competence year
    "MES_CMPT",     # Competence month
    "N_AIH",        # AIH number (unique hospitalisation ID)
    "IDENT",        # AIH type (1=normal, 5=long-stay continuation)
    "MUNIC_RES",    # Municipality of residence (IBGE 6-digit)
    "MUNIC_MOV",    # Municipality of treatment (IBGE 6-digit)
    "NASC",         # Date of birth
    "SEXO",         # Sex
    "IDADE",        # Age
    "COD_IDADE",    # Age unit code
    "DIAS_PERM",    # Length of stay (days)
    "DIAG_PRINC",   # Principal ICD-10 diagnosis
    "DIAG_SECUN",   # Secondary diagnosis
    "PROC_SOLIC",   # Requested procedure
    "PROC_REA",     # Performed procedure
    "DT_INTER",     # Admission date (YYYYMMDD integer)
    "DT_SAIDA",     # Discharge date (YYYYMMDD integer)
    "MORTE",        # In-hospital death (1=yes, 0=no)
    "VAL_TOT",      # Total billed value (BRL)
    "VAL_UTI",      # ICU-related billing (BRL)
    "CNES",         # CNES facility code
    "COMPLEX",      # Complexity level
    "FINANC",       # Financing type
    "CAR_INT",      # Admission type
    "ESPEC",        # Speciality
    "CGC_HOSP",     # Hospital CNPJ/CGC
]

# All 27 Brazilian state codes
UF_CODES: list[str] = [
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO",
    "MA", "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR",
    "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO",
]

# ETLSIH file naming pattern
ETLSIH_FILE_PATTERN: str = "ETLSIH.ST_{uf}_{year}_{month}_t.csv"

# Numeric columns that need coercion after DuckDB read
_NUMERIC_INT_COLS: list[str] = ["MORTE"]
_NUMERIC_FLOAT_COLS: list[str] = ["VAL_TOT", "VAL_UTI"]


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def read_etlsih_csv(
    csv_path: Path,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    """Read an ETLSIH CSV file using DuckDB column projection.

    Uses DuckDB ``read_csv_auto()`` with a SELECT clause to read only the
    requested columns from the 235-column ETLSIH format, avoiding loading
    the entire file into memory.

    Parameters
    ----------
    csv_path : Path
        Path to the ETLSIH CSV file.
    columns : list[str], optional
        Columns to read. Defaults to SIH_COLS_KEEP (27 columns).

    Returns
    -------
    pd.DataFrame
        DataFrame with the requested columns. Numeric columns (MORTE,
        VAL_TOT, VAL_UTI) are coerced to appropriate types.
    """
    cols = columns or SIH_COLS_KEEP

    # Discover available columns in the CSV to handle missing gracefully
    con = duckdb.connect()
    try:
        header_df = con.execute(
            "SELECT * FROM read_csv_auto('%s') LIMIT 0" % str(csv_path)
        ).fetchdf()
        available = set(header_df.columns)

        # Filter to only columns that exist in the file
        select_cols = [c for c in cols if c in available]
        missing = [c for c in cols if c not in available]
        if missing:
            logger.warning(
                "read_etlsih_csv: %d columns not found in %s: %s",
                len(missing),
                csv_path.name,
                missing,
            )

        if not select_cols:
            logger.error(
                "read_etlsih_csv: no requested columns found in %s",
                csv_path.name,
            )
            con.close()
            return pd.DataFrame(columns=cols)

        col_list = ", ".join('"%s"' % c for c in select_cols)
        df = con.execute(
            "SELECT %s FROM read_csv_auto('%s')" % (col_list, str(csv_path))
        ).fetchdf()
    finally:
        con.close()

    # Coerce numeric columns
    for col in _NUMERIC_INT_COLS:
        if col in df.columns:
            df[col] = (
                pd.to_numeric(df[col], errors="coerce")
                .fillna(0)
                .astype(int)
            )

    for col in _NUMERIC_FLOAT_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def _process_uf_month(
    uf: str,
    year: int,
    month: int,
    raw_dir: Path,
    output_dir: Path,
    skip_existing: bool = True,
) -> dict:
    """Process a single UF for a given year-month.

    Reads the ETLSIH CSV, normalizes municipality codes, deduplicates by
    N_AIH, and writes a Parquet file.

    Parameters
    ----------
    uf : str
        Two-letter state code (e.g., "SP", "RJ").
    year : int
        Competence year.
    month : int
        Competence month.
    raw_dir : Path
        Directory containing ETLSIH CSV files.
    output_dir : Path
        Directory for output Parquet files.
    skip_existing : bool
        If True, skip processing when output Parquet already exists.

    Returns
    -------
    dict
        Result with keys: uf, status, rows, path.
    """
    result: dict = {"uf": uf, "status": "not_found", "rows": 0, "path": None}

    # Build output path
    output_path = output_dir / ("%s_%d%02d.parquet" % (uf, year, month))

    # Idempotent: skip if already exists
    if skip_existing and output_path.exists() and output_path.stat().st_size > 0:
        result["status"] = "skipped"
        result["path"] = output_path
        logger.debug("Partition exists, skipping: %s", output_path)
        return result

    # Find CSV file -- try both zero-padded and non-padded month
    csv_path = raw_dir / ETLSIH_FILE_PATTERN.format(
        uf=uf, year=year, month=month,
    )
    if not csv_path.exists():
        # Try zero-padded month
        csv_path_padded = raw_dir / (
            "ETLSIH.ST_%s_%d_%02d_t.csv" % (uf, year, month)
        )
        if csv_path_padded.exists():
            csv_path = csv_path_padded
        else:
            logger.debug(
                "CSV not found for %s %04d-%02d: tried %s and %s",
                uf, year, month, csv_path, csv_path_padded,
            )
            return result

    # Read CSV with DuckDB column projection
    try:
        df = read_etlsih_csv(csv_path)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to read %s: %s", csv_path, exc)
        result["status"] = "error"
        return result

    if df.empty:
        result["status"] = "empty"
        return result

    # Normalize municipality codes
    df["MUNIC_MOV"] = normalize_cod_ibge(df["MUNIC_MOV"])
    df["MUNIC_RES"] = normalize_cod_ibge(df["MUNIC_RES"])

    # Rename MUNIC_MOV -> cod_ibge (treatment municipality per project decision)
    # Keep MUNIC_RES as cod_ibge_res for downstream use
    df = df.rename(columns={
        "MUNIC_MOV": "cod_ibge",
        "MUNIC_RES": "cod_ibge_res",
    })

    # Add year and month columns from competence fields
    df["year"] = pd.to_numeric(df["ANO_CMPT"], errors="coerce").fillna(year).astype(int)
    df["month"] = pd.to_numeric(df["MES_CMPT"], errors="coerce").fillna(month).astype(int)

    # Deduplicate by N_AIH (keep first occurrence)
    before = len(df)
    df = df.drop_duplicates(subset=["N_AIH"], keep="first")
    after = len(df)
    if before != after:
        logger.debug(
            "Deduplicated %s %04d-%02d: %d -> %d rows",
            uf, year, month, before, after,
        )

    # Write Parquet
    output_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, index=False, compression="snappy")

    result.update({
        "status": "ok",
        "rows": len(df),
        "path": output_path,
    })
    logger.info("  ✓ %s %04d-%02d: %d rows -> %s", uf, year, month, len(df), output_path)
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def process_sih_month(
    year: int,
    month: int,
    raw_dir: Path,
    output_dir: Path,
    ufs: list[str] | None = None,
    workers: int = 1,
    skip_existing: bool = True,
) -> list[dict]:
    """Process SIH data for all UFs in a single year-month.

    Parameters
    ----------
    year : int
        Competence year.
    month : int
        Competence month.
    raw_dir : Path
        Directory containing ETLSIH CSV files.
    output_dir : Path
        Root directory for processed Parquet output.
    ufs : list[str], optional
        Subset of UF codes to process (default: all 27).
    workers : int
        Number of parallel worker processes.
    skip_existing : bool
        Skip UFs whose Parquet partition already exists.

    Returns
    -------
    list[dict]
        List of result dicts from _process_uf_month, one per UF.
    """
    if ufs is None:
        ufs = UF_CODES

    logger.info(
        "Processing SIH %04d-%02d (%d UFs, %d worker(s))",
        year, month, len(ufs), workers,
    )

    task = partial(
        _process_uf_month,
        year=year,
        month=month,
        raw_dir=raw_dir,
        output_dir=output_dir,
        skip_existing=skip_existing,
    )

    if workers > 1:
        with multiprocessing.Pool(processes=workers) as pool:
            results = pool.map(task, ufs)
    else:
        results = [task(uf) for uf in ufs]

    ok = sum(1 for r in results if r["status"] == "ok")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    total_rows = sum(r["rows"] for r in results)
    logger.info(
        "Completed SIH %04d-%02d: %d/%d UFs ok, %d skipped, %d total rows",
        year, month, ok, len(ufs), skipped, total_rows,
    )

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    """CLI entry point for SIH ETLSIH CSV extraction."""
    parser = argparse.ArgumentParser(
        description="SIH ETLSIH CSV -> Parquet extraction pipeline",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--year-month", metavar="YYYY-MM",
        help="Single year-month to process",
    )
    group.add_argument(
        "--start", metavar="YYYY-MM",
        help="Start of date range",
    )

    parser.add_argument(
        "--end", metavar="YYYY-MM",
        help="End of date range (required with --start)",
    )
    parser.add_argument(
        "--raw-dir", default=None,
        help="Directory containing ETLSIH CSV files (overrides config.yaml)",
    )
    parser.add_argument(
        "--output-dir", default=None,
        help="Directory for processed Parquet output (overrides config.yaml)",
    )
    parser.add_argument(
        "--ufs", nargs="+", metavar="UF",
        help="Specific UF codes to process",
    )
    parser.add_argument(
        "--workers", type=int, default=1,
        help="Parallel worker count (default: 1)",
    )
    parser.add_argument(
        "--no-skip", dest="skip_existing", action="store_false",
        help="Force reprocessing even if output exists",
    )
    args = parser.parse_args(argv)

    # Resolve paths from config.yaml or CLI
    from database.pipeline import load_config  # noqa: PLC0415

    cfg = load_config()
    data_root = Path(cfg.get("data_root", "data_sources"))

    raw_dir = Path(args.raw_dir) if args.raw_dir else data_root / cfg.get("raw_dir", "raw")
    output_dir = (
        Path(args.output_dir) if args.output_dir
        else data_root / cfg.get("processed_dir", "processed") / "sih"
    )

    # Parse date arguments
    if args.year_month:
        y, m = map(int, args.year_month.split("-"))
        months = [(y, m)]
    else:
        if not args.end:
            parser.error("--end is required with --start")
        sy, sm = map(int, args.start.split("-"))
        ey, em = map(int, args.end.split("-"))
        months = []
        y, m = sy, sm
        while (y, m) <= (ey, em):
            months.append((y, m))
            m += 1
            if m > 12:
                m = 1
                y += 1

    logger.info("Processing %d month(s) ...", len(months))
    for year, month in months:
        process_sih_month(
            year=year,
            month=month,
            raw_dir=raw_dir,
            output_dir=output_dir,
            ufs=args.ufs,
            workers=args.workers,
            skip_existing=args.skip_existing,
        )

    logger.info("All months processed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
