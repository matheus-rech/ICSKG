"""
SIH / CNES Raw Download – Continue / Resume Script
====================================================
Downloads 12 months of SIH (Sistema de Informações Hospitalares) and CNES
(Cadastro Nacional de Estabelecimentos de Saúde) microdata files from
DATASUS FTP, with automatic resume for interrupted downloads.

Both SIH and CNES files are distributed as DBC (compressed DBF) archives.
After download they are decoded with the `pysus` library (or the standalone
`blast-dbf` tool) and saved as compressed CSV / Parquet.

Usage
-----
    # Download the 12 months preceding December 2023
    python scripts/continue_raw_download.py --end-year 2023 --end-month 12 --months 12

    # Download a specific source for a specific month
    python scripts/continue_raw_download.py --source CNES --year 2023 --month 6

    # Resume an interrupted batch
    python scripts/continue_raw_download.py --end-year 2023 --end-month 12 --months 12 --resume
"""

import argparse
import ftplib
import gzip
import hashlib
import logging
import os
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# ---------------------------------------------------------------------------
# DATASUS FTP configuration
# ---------------------------------------------------------------------------

DATASUS_FTP_HOST = "ftp.datasus.gov.br"

FTP_PATHS = {
    "SIH": "/dissemin/publicos/SIHSUS/200801_/Dados/",
    "CNES": "/dissemin/publicos/CNES/200508_/Dados/ST/",
}

# SIH file pattern: RD{UF}{YY}{MM}.dbc
# CNES file pattern: ST{UF}{YY}{MM}.dbc
FILE_PATTERNS = {
    "SIH": "RD{uf}{yy:02d}{mm:02d}.dbc",
    "CNES": "ST{uf}{yy:02d}{mm:02d}.dbc",
}

# All 27 Brazilian state UF codes
UF_CODES = [
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO",
    "MA", "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR",
    "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO",
]

MAX_RETRIES = 5
RETRY_DELAY = 10  # seconds


# ---------------------------------------------------------------------------
# FTP helpers
# ---------------------------------------------------------------------------

def _connect_ftp(host: str, timeout: int = 60) -> ftplib.FTP:
    ftp = ftplib.FTP()
    ftp.connect(host, timeout=timeout)
    ftp.login()
    ftp.set_pasv(True)
    return ftp


def _ftp_list(ftp: ftplib.FTP, path: str) -> list[str]:
    try:
        ftp.cwd(path)
        return ftp.nlst()
    except ftplib.error_perm as exc:
        logger.error("FTP listing failed for %s: %s", path, exc)
        return []


def _download_file(
    ftp: ftplib.FTP,
    remote_path: str,
    local_path: Path,
    resume: bool = True,
) -> bool:
    """Download *remote_path* from *ftp* to *local_path*.

    Supports byte-range resume if *resume* is True and the local file exists.
    Returns True on success.
    """
    local_path.parent.mkdir(parents=True, exist_ok=True)
    offset = local_path.stat().st_size if (resume and local_path.exists()) else 0

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with open(local_path, "ab" if offset else "wb") as fh:
                if offset:
                    ftp.sendcmd(f"REST {offset}")
                ftp.retrbinary(f"RETR {remote_path}", fh.write, rest=offset if offset else None)
            logger.info("✓ %s (%d bytes)", local_path.name, local_path.stat().st_size)
            return True
        except (ftplib.Error, OSError, EOFError) as exc:
            logger.warning("Attempt %d/%d failed: %s", attempt, MAX_RETRIES, exc)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)
                # Reconnect
                try:
                    ftp.quit()
                except Exception:  # noqa: BLE001
                    pass
                ftp = _connect_ftp(DATASUS_FTP_HOST)
                offset = local_path.stat().st_size if local_path.exists() else 0
    return False


# ---------------------------------------------------------------------------
# DBC → Parquet conversion
# ---------------------------------------------------------------------------

def _dbc_to_parquet(dbc_path: Path, output_path: Path) -> bool:
    """Convert a DBC file to Parquet using pysus (if available)."""
    try:
        import pysus.online_data as ps  # noqa: PLC0415

        df = ps.read_dbc(str(dbc_path))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(output_path, index=False, compression="snappy")
        logger.info("Converted %s → %s (%d rows)", dbc_path.name, output_path.name, len(df))
        return True
    except ImportError:
        logger.warning("pysus not installed – DBC conversion skipped for %s.", dbc_path.name)
        return False
    except Exception as exc:  # noqa: BLE001
        logger.error("DBC conversion failed for %s: %s", dbc_path.name, exc)
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def download_month(
    source: str,
    year: int,
    month: int,
    output_path: Path,
    raw_dir: Path = Path("data_sources/raw"),
    resume: bool = True,
    convert: bool = True,
) -> bool:
    """Download all UF files for a given *source*, *year*, and *month*.

    Parameters
    ----------
    source : str
        "SIH" or "CNES".
    year, month : int
        Target year-month.
    output_path : Path
        Destination parquet file (merged across all UFs).
    raw_dir : Path
        Directory for intermediate DBC files.
    resume : bool
        Resume interrupted downloads.
    convert : bool
        Convert DBC to Parquet after download.

    Returns
    -------
    bool
        True if at least one UF was downloaded successfully.
    """
    source = source.upper()
    if source not in FTP_PATHS:
        raise ValueError(f"Unknown source: {source}. Choose from {list(FTP_PATHS)}")

    yy = year % 100
    ftp_dir = FTP_PATHS[source]
    pattern = FILE_PATTERNS[source]

    logger.info("Connecting to DATASUS FTP …")
    try:
        ftp = _connect_ftp(DATASUS_FTP_HOST)
        available = set(_ftp_list(ftp, ftp_dir))
    except Exception as exc:  # noqa: BLE001
        logger.error("FTP connection failed: %s", exc)
        return False

    downloaded_parquets = []
    for uf in UF_CODES:
        filename = pattern.format(uf=uf, yy=yy, mm=month)
        if filename not in available:
            logger.debug("File not available: %s", filename)
            continue
        local_dbc = raw_dir / source / f"{year:04d}{month:02d}" / filename
        ok = _download_file(ftp, f"{ftp_dir}{filename}", local_dbc, resume=resume)
        if ok and convert:
            parquet_path = local_dbc.with_suffix(".parquet")
            _dbc_to_parquet(local_dbc, parquet_path)
            if parquet_path.exists():
                downloaded_parquets.append(parquet_path)

    try:
        ftp.quit()
    except Exception:  # noqa: BLE001
        pass

    # Merge UF-level parquets into single output file
    if downloaded_parquets:
        try:
            import pandas as pd  # noqa: PLC0415

            frames = [pd.read_parquet(p) for p in downloaded_parquets]
            merged = pd.concat(frames, ignore_index=True)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            merged.to_parquet(output_path, index=False, compression="snappy")
            logger.info("Merged %d UF files → %s (%d rows)", len(frames), output_path, len(merged))
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("Merge failed: %s", exc)

    return bool(downloaded_parquets)


def _iter_months(end_year: int, end_month: int, n_months: int):
    """Yield (year, month) tuples going *n_months* back from end_year/end_month."""
    y, m = end_year, end_month
    for _ in range(n_months):
        yield y, m
        m -= 1
        if m == 0:
            m = 12
            y -= 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Continue / resume SIH & CNES raw data download (12-month window)"
    )
    parser.add_argument("--source", default="SIH", choices=["SIH", "CNES", "BOTH"],
                        help="Data source to download (default: SIH)")
    parser.add_argument("--end-year", type=int, help="End year (default: current year)")
    parser.add_argument("--end-month", type=int, help="End month 1-12 (default: 12)")
    parser.add_argument("--months", type=int, default=12,
                        help="Number of months to download (default: 12)")
    parser.add_argument("--year", type=int, help="Single year (overrides --end-year/--months)")
    parser.add_argument("--month", type=int, help="Single month 1-12 (overrides --end-month/--months)")
    parser.add_argument("--raw-dir", default="data_sources/raw",
                        help="Directory for raw DBC files (default: data_sources/raw)")
    parser.add_argument("--output-dir", default="data_sources/processed",
                        help="Directory for output parquet files (default: data_sources/processed)")
    parser.add_argument("--no-resume", dest="resume", action="store_false",
                        help="Do not resume incomplete downloads")
    parser.add_argument("--no-convert", dest="convert", action="store_false",
                        help="Do not convert DBC files to Parquet")
    args = parser.parse_args(argv)

    import datetime  # noqa: PLC0415

    today = datetime.date.today()

    raw_dir = Path(args.raw_dir)
    out_dir = Path(args.output_dir)
    sources = ["SIH", "CNES"] if args.source == "BOTH" else [args.source]

    if args.year and args.month:
        months_to_process = [(args.year, args.month)]
    else:
        end_year = args.end_year or today.year
        end_month = args.end_month or 12
        months_to_process = list(_iter_months(end_year, end_month, args.months))

    total = len(months_to_process) * len(sources)
    logger.info("Downloading %d source×month combinations …", total)

    for source in sources:
        for year, month in months_to_process:
            out_path = out_dir / f"{source.lower()}_{year:04d}{month:02d}.parquet"
            if out_path.exists() and args.resume:
                logger.info("Already exists, skipping: %s", out_path)
                continue
            download_month(
                source=source,
                year=year,
                month=month,
                output_path=out_path,
                raw_dir=raw_dir,
                resume=args.resume,
                convert=args.convert,
            )

    logger.info("Download run complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
