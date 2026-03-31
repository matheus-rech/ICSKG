"""
ANS Beneficiaries Historical Coverage Download
===============================================
Downloads the historical series of private health-plan beneficiary counts
from the ANS (Agência Nacional de Saúde Suplementar) open-data portal:

    https://dados.ans.gov.br/

The script fetches quarterly CSV snapshots of the
"Beneficiários de planos privados de saúde" dataset, one file per
competence month, and saves them to data_sources/raw/ANS/.

It also produces a merged annual summary CSV suitable for inclusion in
the ICSKG-BR panel.

Usage
-----
    # Download all available quarterly snapshots (2000–present)
    python scripts/download_ans.py

    # Download a specific quarter
    python scripts/download_ans.py --year 2023 --month 12

    # Download a range and merge to a single parquet
    python scripts/download_ans.py --start 2013-01 --end 2023-12 --merge
"""

import argparse
import io
import logging
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# ---------------------------------------------------------------------------
# ANS open-data configuration
# ---------------------------------------------------------------------------

ANS_BASE_URL = "https://dados.ans.gov.br/operadoras/informacoes_de_beneficiarios/"

# Quarterly competence months typically available
QUARTERLY_MONTHS = [3, 6, 9, 12]

MAX_RETRIES = 4
RETRY_DELAY = 5  # seconds

# Encoding used by ANS CSV files
ANS_ENCODING = "latin-1"
ANS_SEP = ";"


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _get_with_retry(url: str, timeout: int = 120) -> bytes:
    """Fetch *url* with retry logic.  Returns raw bytes."""
    try:
        import requests  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError("requests library is required. Install with: pip install requests") from exc

    session = requests.Session()
    headers = {"User-Agent": "ICSKG-BR/2.0 (research; contact: icskg-br@example.org)"}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, timeout=timeout, headers=headers, stream=True)
            resp.raise_for_status()
            return resp.content
        except Exception as exc:  # noqa: BLE001
            logger.warning("Attempt %d/%d failed for %s: %s", attempt, MAX_RETRIES, url, exc)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)
    raise RuntimeError(f"Failed to download {url} after {MAX_RETRIES} attempts")


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def _build_filename(year: int, month: int) -> str:
    """Return the expected ANS beneficiary CSV filename for a given month."""
    # ANS filenames follow the pattern: {YYYY}{MM}_Beneficiarios_por_municipio.csv
    return f"{year:04d}{month:02d}_Beneficiarios_por_municipio.csv"


def _build_url(year: int, month: int) -> str:
    filename = _build_filename(year, month)
    return urljoin(ANS_BASE_URL, filename)


# ---------------------------------------------------------------------------
# Download / parse
# ---------------------------------------------------------------------------

def download_competence(
    year: int,
    month: int,
    raw_dir: Path,
    skip_existing: bool = True,
) -> Path | None:
    """Download the ANS beneficiary CSV for *year*/*month*.

    Returns the local CSV path, or None if the file is not available.
    """
    filename = _build_filename(year, month)
    local_path = raw_dir / filename

    if skip_existing and local_path.exists():
        logger.info("Already downloaded: %s", filename)
        return local_path

    url = _build_url(year, month)
    logger.info("Downloading %s …", url)
    try:
        content = _get_with_retry(url)
    except RuntimeError as exc:
        logger.warning("Skipping %d-%02d: %s", year, month, exc)
        return None

    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_bytes(content)
    logger.info("Saved %s (%d bytes)", local_path, len(content))
    return local_path


def parse_csv(path: Path):
    """Parse an ANS CSV file and return a DataFrame with normalised columns."""
    try:
        import pandas as pd  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError("pandas is required to parse ANS CSV files.") from exc

    df = pd.read_csv(path, sep=ANS_SEP, encoding=ANS_ENCODING, dtype=str, low_memory=False)
    df.columns = df.columns.str.strip()

    # Normalise the municipality code column
    for col in ("CD_MUNICIPIO", "Municipio", "IBGE_MUNICIPIO", "CD_MUN"):
        if col in df.columns:
            df = df.rename(columns={col: "CD_MUNICIPIO"})
            break

    # Normalise beneficiary count column
    for col in ("QT_BENEFICIARIO_ATIVO", "BENEFICIARIOS", "QT_BENEF"):
        if col in df.columns:
            df = df.rename(columns={col: "BENEFICIARIOS"})
            break

    if "BENEFICIARIOS" in df.columns:
        df["BENEFICIARIOS"] = pd.to_numeric(df["BENEFICIARIOS"].str.replace(".", "", regex=False), errors="coerce")

    return df


# ---------------------------------------------------------------------------
# Merge helper
# ---------------------------------------------------------------------------

def merge_downloads(paths: list[Path], output_path: Path) -> int:
    """Merge a list of ANS CSV files into a single Parquet file.

    Returns number of rows written.
    """
    try:
        import pandas as pd  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError("pandas is required.") from exc

    frames = []
    for p in paths:
        try:
            df = parse_csv(p)
            # Derive competence year/month from filename: YYYYMM_...
            stem = p.stem
            df["comp_year"] = int(stem[:4])
            df["comp_month"] = int(stem[4:6])
            frames.append(df)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to parse %s: %s", p, exc)

    if not frames:
        logger.warning("No frames to merge.")
        return 0

    merged = pd.concat(frames, ignore_index=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(output_path, index=False, compression="snappy")
    logger.info("Merged %d files → %s (%d rows)", len(frames), output_path, len(merged))
    return len(merged)


# ---------------------------------------------------------------------------
# Public convenience function (used by database/pipeline.py)
# ---------------------------------------------------------------------------

def download_latest(output_path: Path, raw_dir: Path = Path("data_sources/raw/ANS")) -> bool:
    """Download the most recent available ANS beneficiary snapshot.

    Tries December of the previous year, then falls back quarter by quarter.
    """
    import datetime  # noqa: PLC0415

    today = datetime.date.today()
    # Start from Dec of previous year and search backwards
    year, month = today.year - 1, 12

    for _ in range(8):  # up to 2 years back
        path = download_competence(year, month, raw_dir)
        if path is not None:
            # Convert to parquet
            try:
                import pandas as pd  # noqa: PLC0415

                df = parse_csv(path)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                df.to_parquet(output_path, index=False, compression="snappy")
                logger.info("Latest ANS snapshot: %d-%02d → %s", year, month, output_path)
                return True
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to convert ANS CSV: %s", exc)
                return False
        # Go back one quarter
        month -= 3
        if month <= 0:
            month += 12
            year -= 1

    logger.error("No ANS snapshot found for the past 2 years.")
    return False


# ---------------------------------------------------------------------------
# Month iteration
# ---------------------------------------------------------------------------

def _iter_months(start: str, end: str):
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
    parser = argparse.ArgumentParser(description="Download ANS historical beneficiary data")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--start", metavar="YYYY-MM", help="Start of date range")
    group.add_argument("--year", type=int, help="Single year")
    parser.add_argument("--end", metavar="YYYY-MM", help="End of date range (used with --start)")
    parser.add_argument("--month", type=int, choices=range(1, 13), help="Single month (used with --year)")
    parser.add_argument("--quarterly-only", action="store_true",
                        help="Only attempt Q1/Q2/Q3/Q4 competence months (default: all months)")
    parser.add_argument("--raw-dir", default="data_sources/raw/ANS",
                        help="Directory for raw CSV files (default: data_sources/raw/ANS)")
    parser.add_argument("--merge", action="store_true",
                        help="Merge all downloaded CSVs into a single Parquet file")
    parser.add_argument("--merge-output", default="data_sources/ans_beneficiarios_historico.parquet",
                        help="Output path for merged Parquet file")
    parser.add_argument("--no-skip", dest="skip_existing", action="store_false",
                        help="Re-download files that already exist locally")
    args = parser.parse_args(argv)

    raw_dir = Path(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)

    import datetime  # noqa: PLC0415

    today = datetime.date.today()

    if args.year and args.month:
        months_to_process = [(args.year, args.month)]
    elif args.year:
        months_to_process = [(args.year, m) for m in (QUARTERLY_MONTHS if args.quarterly_only else range(1, 13))]
    elif args.start:
        end_str = args.end or f"{today.year - 1}-12"
        months_to_process = list(_iter_months(args.start, end_str))
        if args.quarterly_only:
            months_to_process = [(y, m) for y, m in months_to_process if m in QUARTERLY_MONTHS]
    else:
        # Default: all quarterly snapshots from 2013 to last year
        months_to_process = [
            (y, m)
            for y in range(2013, today.year)
            for m in (QUARTERLY_MONTHS if args.quarterly_only else range(1, 13))
        ]

    logger.info("Processing %d month(s) …", len(months_to_process))
    downloaded_paths = []
    for year, month in months_to_process:
        path = download_competence(year, month, raw_dir, skip_existing=args.skip_existing)
        if path:
            downloaded_paths.append(path)

    logger.info("Downloaded %d / %d files.", len(downloaded_paths), len(months_to_process))

    if args.merge and downloaded_paths:
        merge_downloads(downloaded_paths, Path(args.merge_output))

    return 0


if __name__ == "__main__":
    sys.exit(main())
