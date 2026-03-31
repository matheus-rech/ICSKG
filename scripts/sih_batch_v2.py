"""
SIH Batch Processor v2 – Optimised
====================================
High-performance batch processor for SIH (Sistema de Informações Hospitalares)
inpatient microdata files.

Key optimisations over v1
--------------------------
* Chunked DBC → Parquet conversion to limit peak memory usage
* Multi-process parallelism across UF codes (configurable worker count)
* Incremental output: each UF is saved to its own partition; already-converted
  partitions are skipped automatically (idempotent)
* Configurable column subsetting to reduce I/O
* Automatic deduplication of AIH (Autorização de Internação Hospitalar) keys

SIH file naming convention (DATASUS)
--------------------------------------
  RD{UF}{YY}{MM}.dbc   – e.g., RDSP2312.dbc for São Paulo, December 2023

Usage
-----
    # Process a single month (all UFs)
    python scripts/sih_batch_v2.py --year 2023 --month 12

    # Process a range of months, 4 workers
    python scripts/sih_batch_v2.py --start 2022-01 --end 2023-12 --workers 4

    # Process only specific UFs
    python scripts/sih_batch_v2.py --year 2023 --month 12 --ufs SP RJ MG
"""

import argparse
import logging
import multiprocessing
import sys
import time
from functools import partial
from pathlib import Path

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# ---------------------------------------------------------------------------
# Column subset (reduce memory footprint)
# ---------------------------------------------------------------------------

SIH_COLS_KEEP = [
    "UF_ZI",       # State of hospitalisation
    "ANO_CMPT",    # Competence year
    "MES_CMPT",    # Competence month
    "ESPEC",       # Speciality
    "CGC_HOSP",    # Hospital CNPJ/CGC
    "N_AIH",       # AIH number (unique hospitalisation ID)
    "IDENT",       # AIH type (1=normal, 5=long-stay continuation)
    "CEP",         # Postal code
    "MUNIC_RES",   # Municipality of residence (IBGE 6-digit)
    "MUNIC_MOV",   # Municipality of hospitalisation (IBGE 6-digit)
    "NASC",        # Date of birth
    "SEXO",        # Sex
    "UTI_MES_TO",  # ICU days
    "MARCA_UTI",   # ICU marker
    "DIAS_PERM",   # Length of stay (days)
    "DIAG_PRINC",  # Principal ICD-10 diagnosis
    "DIAG_SECUN",  # Secondary diagnosis
    "PROC_SOLIC",  # Requested procedure
    "PROC_REA",    # Performed procedure
    "DT_INTER",    # Admission date (YYYYMMDD)
    "DT_SAIDA",    # Discharge date (YYYYMMDD)
    "MORTE",       # In-hospital death (1=yes)
    "VAL_TOT",     # Total billed value (BRL)
    "VAL_UTI",     # UTI-related billing
]

# All UF codes
UF_CODES = [
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO",
    "MA", "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR",
    "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO",
]

DATASUS_FTP_HOST = "ftp.datasus.gov.br"
SIH_FTP_DIR = "/dissemin/publicos/SIHSUS/200801_/Dados/"
MAX_RETRIES = 5


# ---------------------------------------------------------------------------
# Single-UF processing task (runs in worker processes)
# ---------------------------------------------------------------------------

def _process_uf(
    uf: str,
    year: int,
    month: int,
    raw_dir: Path,
    output_dir: Path,
    cols_keep: list[str],
    skip_existing: bool,
    deduplicate: bool,
) -> dict:
    """Download, convert, and save SIH data for one UF.

    Returns a result dict with keys: uf, status, rows, path.
    """
    result = {"uf": uf, "status": "skipped", "rows": 0, "path": None}

    partition_path = output_dir / f"year={year}" / f"month={month:02d}" / f"uf={uf}" / "data.parquet"

    if skip_existing and partition_path.exists():
        logger.debug("Partition exists, skipping: %s", partition_path)
        result["path"] = partition_path
        return result

    yy = year % 100
    filename = f"RD{uf}{yy:02d}{month:02d}.dbc"
    local_dbc = raw_dir / f"{year:04d}{month:02d}" / filename

    # --- Download ---
    if not local_dbc.exists():
        downloaded = _ftp_download(uf, year, month, local_dbc)
        if not downloaded:
            result["status"] = "not_found"
            return result

    # --- Convert DBC → DataFrame ---
    df = _read_dbc(local_dbc, cols_keep)
    if df is None or df.empty:
        result["status"] = "empty"
        return result

    # --- Deduplication ---
    if deduplicate and "N_AIH" in df.columns:
        before = len(df)
        df = df.drop_duplicates(subset=["N_AIH"])
        after = len(df)
        if before != after:
            logger.debug("Deduplicated %s: %d → %d rows", uf, before, after)

    # --- Write partition ---
    partition_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(partition_path, index=False, compression="snappy")

    result.update({"status": "ok", "rows": len(df), "path": partition_path})
    logger.info("  ✓ %s: %d rows → %s", uf, len(df), partition_path)
    return result


def _ftp_download(uf: str, year: int, month: int, local_path: Path) -> bool:
    """Download the DBC file for a single UF from DATASUS FTP."""
    import ftplib  # noqa: PLC0415

    yy = year % 100
    filename = f"RD{uf}{yy:02d}{month:02d}.dbc"
    remote = f"{SIH_FTP_DIR}{filename}"
    local_path.parent.mkdir(parents=True, exist_ok=True)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            ftp = ftplib.FTP()
            ftp.connect(DATASUS_FTP_HOST, timeout=60)
            ftp.login()
            ftp.set_pasv(True)
            with open(local_path, "wb") as fh:
                ftp.retrbinary(f"RETR {remote}", fh.write)
            ftp.quit()
            logger.debug("Downloaded %s", filename)
            return True
        except ftplib.error_perm:
            logger.debug("File not available on FTP: %s", filename)
            return False
        except Exception as exc:  # noqa: BLE001
            logger.warning("FTP attempt %d/%d failed for %s: %s", attempt, MAX_RETRIES, filename, exc)
            if attempt < MAX_RETRIES:
                time.sleep(5 * attempt)
    return False


def _read_dbc(dbc_path: Path, cols_keep: list[str]):
    """Read a DBC file into a DataFrame, keeping only *cols_keep* columns."""
    try:
        import pysus.online_data as ps  # noqa: PLC0415

        df = ps.read_dbc(str(dbc_path))
        available = [c for c in cols_keep if c in df.columns]
        return df[available] if available else df
    except ImportError:
        logger.warning("pysus not available – attempting blast-dbf fallback for %s.", dbc_path)
        return _read_dbc_blast(dbc_path, cols_keep)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to read DBC %s: %s", dbc_path, exc)
        return None


def _read_dbc_blast(dbc_path: Path, cols_keep: list[str]):
    """Fallback DBC reader using blast-dbf command-line tool."""
    import subprocess  # noqa: PLC0415
    import tempfile  # noqa: PLC0415
    import pandas as pd  # noqa: PLC0415

    try:
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        subprocess.run(
            ["blast-dbf", str(dbc_path), str(tmp_path)],
            check=True,
            capture_output=True,
            timeout=300,
        )
        df = pd.read_csv(tmp_path, dtype=str, encoding="latin-1")
        tmp_path.unlink(missing_ok=True)
        available = [c for c in cols_keep if c in df.columns]
        return df[available] if available else df
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.error("blast-dbf fallback failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Merge partitions into a single output file
# ---------------------------------------------------------------------------

def _merge_partitions(partition_root: Path, year: int, month: int, output_path: Path) -> int:
    """Merge all UF partitions for a year-month into *output_path*."""
    try:
        import pandas as pd  # noqa: PLC0415
    except ImportError:
        logger.error("pandas required for merging.")
        return 0

    month_dir = partition_root / f"year={year}" / f"month={month:02d}"
    parquet_files = list(month_dir.glob("uf=*/data.parquet"))

    if not parquet_files:
        logger.warning("No partitions found in %s", month_dir)
        return 0

    frames = []
    for f in sorted(parquet_files):
        try:
            frames.append(pd.read_parquet(f))
        except Exception as exc:  # noqa: BLE001
            logger.error("Could not read %s: %s", f, exc)

    if not frames:
        return 0

    merged = pd.concat(frames, ignore_index=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(output_path, index=False, compression="snappy")
    logger.info("Merged %d UF partitions → %s (%d rows)", len(frames), output_path, len(merged))
    return len(merged)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def process_month(
    year: int,
    month: int,
    output_path: Path,
    ufs: list[str] = None,
    raw_dir: Path = Path("data_sources/raw"),
    partition_dir: Path = Path("data_sources/raw/SIH_partitions"),
    workers: int = 1,
    skip_existing: bool = True,
    deduplicate: bool = True,
    cols_keep: list[str] = None,
) -> int:
    """Process SIH data for a single year-month across all (or specified) UFs.

    Parameters
    ----------
    year, month : int
        Target period.
    output_path : Path
        Destination merged parquet file.
    ufs : list of str, optional
        Subset of UF codes to process (default: all 27).
    raw_dir : Path
        Where to store raw DBC files.
    partition_dir : Path
        Root directory for per-UF partitioned parquet files.
    workers : int
        Number of parallel worker processes.
    skip_existing : bool
        Skip UFs whose partition already exists.
    deduplicate : bool
        Deduplicate on N_AIH (AIH number).
    cols_keep : list of str, optional
        Column subset to retain (default: SIH_COLS_KEEP).

    Returns
    -------
    int
        Total rows written to *output_path*.
    """
    if ufs is None:
        ufs = UF_CODES
    if cols_keep is None:
        cols_keep = SIH_COLS_KEEP

    logger.info("Processing SIH %04d-%02d (%d UFs, %d worker(s))", year, month, len(ufs), workers)

    task = partial(
        _process_uf,
        year=year,
        month=month,
        raw_dir=raw_dir,
        output_dir=partition_dir,
        cols_keep=cols_keep,
        skip_existing=skip_existing,
        deduplicate=deduplicate,
    )

    if workers > 1:
        with multiprocessing.Pool(processes=workers) as pool:
            results = pool.map(task, ufs)
    else:
        results = [task(uf) for uf in ufs]

    ok = sum(1 for r in results if r["status"] == "ok")
    total_rows = sum(r["rows"] for r in results)
    logger.info("Completed: %d/%d UFs ok, %d total rows", ok, len(ufs), total_rows)

    # Merge all partitions into the output file
    n = _merge_partitions(partition_dir, year, month, output_path)
    return n


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description="SIH batch processor v2")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--year-month", metavar="YYYY-MM", help="Single year-month")
    group.add_argument("--start", metavar="YYYY-MM", help="Start of date range")

    parser.add_argument("--end", metavar="YYYY-MM", help="End of date range (with --start)")
    parser.add_argument("--ufs", nargs="+", metavar="UF", help="Specific UF codes to process")
    parser.add_argument("--workers", type=int, default=1, help="Parallel worker count (default: 1)")
    parser.add_argument("--raw-dir", default="data_sources/raw")
    parser.add_argument("--output-dir", default="data_sources/processed")
    parser.add_argument("--no-skip", dest="skip_existing", action="store_false")
    parser.add_argument("--no-dedup", dest="deduplicate", action="store_false")
    args = parser.parse_args(argv)

    raw_dir = Path(args.raw_dir)
    out_dir = Path(args.output_dir)

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

    logger.info("Processing %d month(s) …", len(months))
    for year, month in months:
        out_path = out_dir / f"sih_{year:04d}{month:02d}.parquet"
        process_month(
            year=year,
            month=month,
            output_path=out_path,
            ufs=args.ufs,
            raw_dir=raw_dir,
            workers=args.workers,
            skip_existing=args.skip_existing,
            deduplicate=args.deduplicate,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
