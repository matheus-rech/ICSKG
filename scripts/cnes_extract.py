"""
ICSKG-BR CNES Establishment Extractor & CBO Code Registry
==========================================================
Reads FIOCRUZ BigData ETLCNES ST (establishment) CSV files, identifies
bellwether-capable facilities per Lancet Commission on Global Surgery
criteria, and writes a clean facilities.parquet.

Also defines the canonical CBO-2002 6-digit code constants for SAO
(Surgeons, Anesthesiologists, Obstetricians) professional filtering.
These constants are the single source of truth for professional
classification across the entire ICSKG-BR project.

Data source
-----------
FIOCRUZ BigData ETLCNES.zip containing ST (establishment) CSV files.
File naming pattern: ``ETLCNES.ST_{UF}__{YY}_{MM}_t.csv``
  - Double underscore between UF and year
  - 2-digit year (15 = 2015, 23 = 2023)
  - ``_t`` suffix indicates the complete table variant

Bellwether criteria (Lancet Commission on Global Surgery)
---------------------------------------------------------
A facility is bellwether-capable if ANY of:
  - Has a surgical center (CENTRCIR > 0)
  - Has an obstetric center (CENTROBS > 0)
  - Has >= 10 inpatient beds (QTLEITP1 + QTLEITP2 + QTLEITP3 >= 10)

Outputs
-------
  - ``facilities.parquet`` -- all facilities with bellwether flag
  - Columns: cnes, cod_ibge, year, centrcir, centrobs, total_beds,
    is_bellwether, vinc_sus, tp_unid

Usage
-----
    python scripts/cnes_extract.py --input-dir data_sources/raw/cnes \\
        --output-dir data_sources/processed/cnes --year 2023

    # Or with zip extraction:
    python scripts/cnes_extract.py --zip-path /path/to/ETLCNES.zip \\
        --input-dir data_sources/raw/cnes \\
        --output-dir data_sources/processed/cnes --year 2023
"""

import argparse
import logging
import re
import sys
import zipfile
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# ---------------------------------------------------------------------------
# CBO-2002 6-digit codes for SAO (Surgeons, Anesthesiologists, Obstetricians)
# Source: ANS FHIR CodeSystem tuss-24 (verified 2026-04-01)
# WARNING: Do NOT use 4-digit family codes (2231=ALL physicians,
#          2232=DENTISTS, 2235=NURSES)
# ---------------------------------------------------------------------------

CBO_SURGEONS: set[str] = {
    "225210",  # Medico cirurgiao cardiovascular
    "225215",  # Medico cirurgiao de cabeca e pescoco
    "225225",  # Medico cirurgiao geral
    "225230",  # Medico cirurgiao pediatrico
    "225235",  # Medico cirurgiao plastico
    "225240",  # Medico cirurgiao toracico
    "225203",  # Medico em cirurgia vascular
    "225260",  # Medico neurocirurgiao
    "225295",  # Medico cirurgiao da mao
}

CBO_ANESTHESIOLOGISTS: set[str] = {
    "225151",  # Medico anestesiologista
}

CBO_OBSTETRICIANS: set[str] = {
    "225250",  # Medico ginecologista e obstetra
}

CBO_SAO: set[str] = CBO_SURGEONS | CBO_ANESTHESIOLOGISTS | CBO_OBSTETRICIANS


# ---------------------------------------------------------------------------
# CNES ST column constants
# ---------------------------------------------------------------------------

CNES_ST_COLS: list[str] = [
    "CNES", "CODUFMUN", "COMPETEN",
    "CENTRCIR", "CENTROBS",
    "QTLEITP1", "QTLEITP2", "QTLEITP3",
    "VINC_SUS", "TP_UNID", "LEITHOSP",
]

# Numeric columns that must be coerced from string to int
_NUMERIC_COLS: list[str] = [
    "CENTRCIR", "CENTROBS",
    "QTLEITP1", "QTLEITP2", "QTLEITP3",
    "VINC_SUS", "TP_UNID", "LEITHOSP",
]

# Output column rename mapping (uppercase raw -> lowercase clean)
_OUTPUT_RENAME: dict[str, str] = {
    "CNES": "cnes",
    "COMPETEN": "competen",
    "CENTRCIR": "centrcir",
    "CENTROBS": "centrobs",
    "VINC_SUS": "vinc_sus",
    "TP_UNID": "tp_unid",
    "LEITHOSP": "leithosp",
}


# ---------------------------------------------------------------------------
# Bellwether facility filter
# ---------------------------------------------------------------------------

def filter_bellwether_facilities(df: pd.DataFrame) -> pd.DataFrame:
    """Identify bellwether-capable facilities per Lancet Commission criteria.

    Adds two columns to the DataFrame:
      - ``total_beds``: QTLEITP1 + QTLEITP2 + QTLEITP3
      - ``is_bellwether``: True if surgical center OR obstetric center OR
        total_beds >= 10

    Returns the FULL DataFrame with new columns (does not filter rows).
    Downstream code can use ``is_bellwether`` to select only bellwether
    facilities when needed.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame with CENTRCIR, CENTROBS, QTLEITP1, QTLEITP2, QTLEITP3
        columns (raw CNES ST data).

    Returns
    -------
    pd.DataFrame
        Same DataFrame with ``total_beds`` and ``is_bellwether`` added.
    """
    df = df.copy()

    # Compute total beds with safe numeric coercion
    beds1 = pd.to_numeric(df["QTLEITP1"], errors="coerce").fillna(0)
    beds2 = pd.to_numeric(df["QTLEITP2"], errors="coerce").fillna(0)
    beds3 = pd.to_numeric(df["QTLEITP3"], errors="coerce").fillna(0)
    df["total_beds"] = (beds1 + beds2 + beds3).astype(int)

    # Bellwether criteria: surgical center OR obstetric center OR >=10 beds
    centrcir = pd.to_numeric(df["CENTRCIR"], errors="coerce").fillna(0)
    centrobs = pd.to_numeric(df["CENTROBS"], errors="coerce").fillna(0)

    df["is_bellwether"] = (
        (centrcir > 0)
        | (centrobs > 0)
        | (df["total_beds"] >= 10)
    )

    return df


# ---------------------------------------------------------------------------
# CSV reading
# ---------------------------------------------------------------------------

def _read_cnes_st_csv(
    csv_path: Path,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    """Read a single CNES ST CSV file with column projection.

    Parameters
    ----------
    csv_path : Path
        Path to the ETLCNES.ST CSV file.
    columns : list[str], optional
        Columns to read. Defaults to CNES_ST_COLS.

    Returns
    -------
    pd.DataFrame
        DataFrame with requested columns, numeric columns coerced to int.
    """
    cols = columns or CNES_ST_COLS

    try:
        import duckdb  # noqa: PLC0415
        col_list = ", ".join(cols)
        con = duckdb.connect()
        try:
            df = con.execute(
                "SELECT %s FROM read_csv_auto('%s')" % (col_list, csv_path)
            ).fetchdf()
        finally:
            con.close()
    except ImportError:
        logger.warning(
            "duckdb not available -- falling back to pandas for %s", csv_path
        )
        all_cols = pd.read_csv(csv_path, nrows=0).columns.tolist()
        usecols = [c for c in cols if c in all_cols]
        if not usecols:
            logger.error(
                "No matching columns found in %s. Available: %s",
                csv_path, all_cols,
            )
            return pd.DataFrame(columns=cols)
        df = pd.read_csv(csv_path, usecols=usecols, dtype=str)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to read %s: %s", csv_path, exc)
        # Fall back to pandas
        all_cols = pd.read_csv(csv_path, nrows=0).columns.tolist()
        usecols = [c for c in cols if c in all_cols]
        df = pd.read_csv(csv_path, usecols=usecols, dtype=str)

    # Coerce numeric columns to int
    for col in _NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    return df


# ---------------------------------------------------------------------------
# Zip extraction
# ---------------------------------------------------------------------------

def _extract_from_zip(
    zip_path: Path,
    output_dir: Path,
    year_start: int = 2015,
    year_end: int = 2023,
) -> list[Path]:
    """Extract matching CNES ST CSV files from ETLCNES.zip.

    Parameters
    ----------
    zip_path : Path
        Path to the ETLCNES.zip archive.
    output_dir : Path
        Directory to extract files into (flat, no subdirectories).
    year_start, year_end : int
        Inclusive year range for filtering (full 4-digit years).

    Returns
    -------
    list[Path]
        Paths to the extracted CSV files.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build set of valid 2-digit years
    valid_yy = {y % 100 for y in range(year_start, year_end + 1)}

    # Pattern: ETLCNES.ST_{UF}__{YY}_{MM}_t.csv
    pattern = re.compile(r"ETLCNES\.ST_[A-Z]{2}__(\d{2})_(\d{2})_t\.csv$")

    extracted: list[Path] = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        all_entries = zf.namelist()
        for entry in all_entries:
            # Get just the filename (entries may have directory prefixes)
            filename = Path(entry).name
            match = pattern.match(filename)
            if not match:
                continue
            yy = int(match.group(1))
            if yy not in valid_yy:
                continue
            # Extract to output_dir with flat filename
            target = output_dir / filename
            if not target.exists():
                with zf.open(entry) as src, target.open("wb") as dst:
                    dst.write(src.read())
            extracted.append(target)

    logger.info(
        "Extracted %d CNES ST files from %s (total entries: %d)",
        len(extracted), zip_path, len(all_entries),
    )
    return extracted


# ---------------------------------------------------------------------------
# Main extraction function
# ---------------------------------------------------------------------------

def extract_cnes_facilities(
    input_dir: Path,
    output_dir: Path,
    year: int,
    zip_path: Path | None = None,
) -> Path:
    """Extract CNES facility data and identify bellwether hospitals.

    Reads all ETLCNES ST CSV files for the target year from *input_dir*,
    normalizes municipality codes, applies bellwether filter, deduplicates
    monthly snapshots (keeping latest COMPETEN per CNES+municipality),
    validates, and writes to ``facilities.parquet``.

    Parameters
    ----------
    input_dir : Path
        Directory containing extracted ETLCNES ST CSV files.
    output_dir : Path
        Where to write facilities.parquet.
    year : int
        Target year (4-digit, e.g. 2023).
    zip_path : Path, optional
        Path to ETLCNES.zip. If provided and input_dir has no matching
        files, extracts from zip first.

    Returns
    -------
    Path
        Path to the written facilities.parquet file.
    """
    from database.utils import normalize_cod_ibge, rename_municipality_column  # noqa: PLC0415
    from database.validation import validate_dataframe  # noqa: PLC0415

    output_dir.mkdir(parents=True, exist_ok=True)

    # Build 2-digit year for glob pattern
    yy = year % 100

    # Check for existing files first
    csv_files = sorted(input_dir.glob("ETLCNES.ST_*__%02d_*_t.csv" % yy))

    # If no files found and zip provided, extract
    if not csv_files and zip_path and zip_path.exists():
        logger.info("No CNES ST files found in %s -- extracting from zip", input_dir)
        _extract_from_zip(zip_path, input_dir, year_start=year, year_end=year)
        csv_files = sorted(input_dir.glob("ETLCNES.ST_*__%02d_*_t.csv" % yy))

    if not csv_files:
        logger.warning(
            "No CNES ST files found for year %d in %s", year, input_dir
        )
        # Write empty parquet
        empty = pd.DataFrame(columns=[
            "cnes", "cod_ibge", "year", "centrcir", "centrobs",
            "total_beds", "is_bellwether", "vinc_sus", "tp_unid",
        ])
        out_path = output_dir / "facilities.parquet"
        empty.to_parquet(out_path, index=False, compression="snappy")
        return out_path

    # Read all matching files
    logger.info("Reading %d CNES ST files for year %d", len(csv_files), year)
    frames: list[pd.DataFrame] = []
    for csv_file in csv_files:
        try:
            df = _read_cnes_st_csv(csv_file)
            frames.append(df)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to read %s: %s", csv_file, exc)

    if not frames:
        logger.error("All CNES ST files failed to read for year %d", year)
        empty = pd.DataFrame(columns=[
            "cnes", "cod_ibge", "year", "centrcir", "centrobs",
            "total_beds", "is_bellwether", "vinc_sus", "tp_unid",
        ])
        out_path = output_dir / "facilities.parquet"
        empty.to_parquet(out_path, index=False, compression="snappy")
        return out_path

    combined = pd.concat(frames, ignore_index=True)
    logger.info("Combined %d rows from %d files", len(combined), len(frames))

    # ---------------------------------------------------------------------------
    # Rename and normalize municipality codes
    # ---------------------------------------------------------------------------
    combined = rename_municipality_column(combined)
    combined["cod_ibge"] = normalize_cod_ibge(combined["cod_ibge"])

    # ---------------------------------------------------------------------------
    # Extract year from COMPETEN (YYYYMM -> YYYY)
    # ---------------------------------------------------------------------------
    combined["year"] = (
        pd.to_numeric(combined["COMPETEN"], errors="coerce") // 100
    ).astype(int)

    # ---------------------------------------------------------------------------
    # Apply bellwether filter (adds total_beds and is_bellwether columns)
    # ---------------------------------------------------------------------------
    combined = filter_bellwether_facilities(combined)

    # ---------------------------------------------------------------------------
    # Deduplicate: keep latest COMPETEN per (CNES, cod_ibge)
    # ---------------------------------------------------------------------------
    before = len(combined)
    combined = combined.sort_values("COMPETEN", ascending=False)
    combined = combined.drop_duplicates(subset=["CNES", "cod_ibge"], keep="first")
    after = len(combined)
    if before != after:
        logger.debug(
            "Deduplicated %d -> %d facilities (kept latest COMPETEN)",
            before, after,
        )

    # ---------------------------------------------------------------------------
    # Rename columns to lowercase output schema
    # ---------------------------------------------------------------------------
    combined = combined.rename(columns=_OUTPUT_RENAME)

    # Select and order output columns
    output_cols = [
        "cnes", "cod_ibge", "year", "centrcir", "centrobs",
        "total_beds", "is_bellwether", "vinc_sus", "tp_unid",
    ]
    # Keep only columns that exist (leithosp and competen not in output schema)
    available = [c for c in output_cols if c in combined.columns]
    combined = combined[available].copy()

    # ---------------------------------------------------------------------------
    # Validate through the standard gate
    # ---------------------------------------------------------------------------
    clean_df, report = validate_dataframe(
        combined,
        source_name="cnes_facilities",
        strict=False,
    )

    # ---------------------------------------------------------------------------
    # Write output
    # ---------------------------------------------------------------------------
    out_path = output_dir / "facilities.parquet"
    clean_df.to_parquet(out_path, index=False, compression="snappy")

    n_bellwether = clean_df["is_bellwether"].sum() if "is_bellwether" in clean_df.columns else 0
    logger.info(
        "Wrote %d facilities (%d bellwether) -> %s",
        len(clean_df), n_bellwether, out_path,
    )

    return out_path


# ---------------------------------------------------------------------------
# CNES PF (professional) columns
# ---------------------------------------------------------------------------

CNES_PF_COLS: list[str] = [
    "CNES", "CODUFMUN", "CNS_PROF", "CBO", "COMPETEN",
]

# All 27 Brazilian UF codes
UF_CODES: list[str] = [
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA",
    "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN",
    "RO", "RR", "RS", "SC", "SE", "SP", "TO",
]


# ---------------------------------------------------------------------------
# PySUS download for CNES PF files
# ---------------------------------------------------------------------------

def download_cnes_pf(
    output_dir: Path,
    ufs: list[str] | None = None,
    years: list[int] | None = None,
    months: list[int] | None = None,
) -> list[Path]:
    """Download CNES PF (professional) files from DATASUS FTP via PySUS.

    This is a thin wrapper around the PySUS ``download()`` function for
    group "PF".  If PySUS is not installed or the DATASUS FTP is
    unreachable, logs an error and returns an empty list.

    Parameters
    ----------
    output_dir : Path
        Directory to store downloaded Parquet files.
    ufs : list[str], optional
        Brazilian state codes (e.g., ["SP", "RJ"]). Defaults to all 27 UFs.
    years : list[int], optional
        Years to download (e.g., [2023]). Defaults to [2023].
    months : list[int], optional
        Months to download (e.g., [1, 2, ..., 12]). Defaults to all 12.

    Returns
    -------
    list[Path]
        Paths to downloaded Parquet files.
    """
    if ufs is None:
        ufs = UF_CODES
    if years is None:
        years = [2023]
    if months is None:
        months = list(range(1, 13))

    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        from pysus.online_data.CNES import download as cnes_download  # noqa: PLC0415
    except ImportError:
        logger.error(
            "pysus not installed -- cannot download CNES PF files. "
            "Install with: pip install pysus"
        )
        return []

    downloaded: list[Path] = []
    for uf in ufs:
        try:
            files = cnes_download(
                group="PF",
                states=uf,
                years=years,
                months=months,
                data_dir=str(output_dir),
            )
            for f in files:
                p = Path(f)
                if p.exists():
                    downloaded.append(p)
            logger.info(
                "Downloaded %d CNES PF files for UF=%s", len(files), uf
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "CNES PF download failed for UF=%s: %s", uf, exc
            )

    logger.info(
        "CNES PF download complete: %d files in %s", len(downloaded), output_dir
    )
    return downloaded


# ---------------------------------------------------------------------------
# CNES PF professional extraction
# ---------------------------------------------------------------------------

def extract_cnes_professionals(
    input_dir: Path,
    output_dir: Path,
    year: int,
) -> Path:
    """Extract SAO professionals from CNES PF files.

    Reads all PF Parquet/CSV files in *input_dir* for the target year,
    filters to SAO professionals (surgeons, anesthesiologists, obstetricians)
    using CBO_SAO codes, deduplicates by (cns_prof, cod_ibge, year), classifies
    sao_category, and writes professionals.parquet.

    Parameters
    ----------
    input_dir : Path
        Directory containing CNES PF files (Parquet or CSV).
    output_dir : Path
        Where to write professionals.parquet.
    year : int
        Target year (4-digit, e.g. 2023).

    Returns
    -------
    Path
        Path to the written professionals.parquet file.
    """
    from database.utils import normalize_cod_ibge, rename_municipality_column  # noqa: PLC0415

    output_dir.mkdir(parents=True, exist_ok=True)

    # Glob for PF files -- support both Parquet and CSV
    pf_files: list[Path] = []
    for pattern in [
        "*.parquet",
        "*PF*%d*.csv" % year,
        "*PF*%02d*.csv" % (year % 100),
        "*pf*%d*.csv" % year,
        "CNES_PF*%d*.csv" % year,
    ]:
        pf_files.extend(input_dir.glob(pattern))

    # Deduplicate file list
    pf_files = sorted(set(pf_files))

    if not pf_files:
        logger.warning(
            "No CNES PF files found for year %d in %s", year, input_dir
        )
        empty = pd.DataFrame(columns=[
            "cnes", "cod_ibge", "year", "cbo", "cns_prof", "sao_category",
        ])
        out_path = output_dir / "professionals.parquet"
        empty.to_parquet(out_path, index=False, compression="snappy")
        return out_path

    logger.info("Reading %d CNES PF files for year %d", len(pf_files), year)

    # Read all matching files
    frames: list[pd.DataFrame] = []
    for pf_file in pf_files:
        try:
            if pf_file.suffix == ".parquet":
                df = pd.read_parquet(pf_file)
            else:
                df = pd.read_csv(pf_file, dtype=str)
            frames.append(df)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to read %s: %s", pf_file, exc)

    if not frames:
        logger.error("All CNES PF files failed to read for year %d", year)
        empty = pd.DataFrame(columns=[
            "cnes", "cod_ibge", "year", "cbo", "cns_prof", "sao_category",
        ])
        out_path = output_dir / "professionals.parquet"
        empty.to_parquet(out_path, index=False, compression="snappy")
        return out_path

    combined = pd.concat(frames, ignore_index=True)
    logger.info("Combined %d PF rows from %d files", len(combined), len(frames))

    # ---------------------------------------------------------------------------
    # Ensure required columns exist (case-insensitive matching)
    # ---------------------------------------------------------------------------
    col_map = {c.upper(): c for c in combined.columns}
    needed = {"CNES", "CODUFMUN", "CNS_PROF", "CBO", "COMPETEN"}
    renames = {}
    for need in needed:
        if need not in combined.columns and need in col_map:
            renames[col_map[need]] = need
    if renames:
        combined = combined.rename(columns=renames)

    # Convert CBO to string for filtering
    combined["CBO"] = combined["CBO"].astype(str).str.strip()

    # ---------------------------------------------------------------------------
    # Filter to SAO professionals (CBO in CBO_SAO)
    # ---------------------------------------------------------------------------
    before_filter = len(combined)
    combined = combined[combined["CBO"].isin(CBO_SAO)].copy()
    logger.info(
        "CBO filter: %d -> %d SAO professionals", before_filter, len(combined)
    )

    if combined.empty:
        logger.warning("No SAO professionals found after CBO filtering")
        empty = pd.DataFrame(columns=[
            "cnes", "cod_ibge", "year", "cbo", "cns_prof", "sao_category",
        ])
        out_path = output_dir / "professionals.parquet"
        empty.to_parquet(out_path, index=False, compression="snappy")
        return out_path

    # ---------------------------------------------------------------------------
    # Rename CODUFMUN -> cod_ibge and normalize
    # ---------------------------------------------------------------------------
    combined = rename_municipality_column(combined)
    combined["cod_ibge"] = normalize_cod_ibge(combined["cod_ibge"])

    # ---------------------------------------------------------------------------
    # Extract year from COMPETEN (YYYYMM -> YYYY)
    # ---------------------------------------------------------------------------
    combined["year"] = (
        pd.to_numeric(combined["COMPETEN"], errors="coerce") // 100
    ).astype(int)

    # ---------------------------------------------------------------------------
    # Classify sao_category
    # ---------------------------------------------------------------------------
    def _classify_sao(cbo: str) -> str:
        if cbo in CBO_SURGEONS:
            return "surgeon"
        if cbo in CBO_ANESTHESIOLOGISTS:
            return "anesthesiologist"
        if cbo in CBO_OBSTETRICIANS:
            return "obstetrician"
        return "unknown"

    combined["sao_category"] = combined["CBO"].apply(_classify_sao)

    # ---------------------------------------------------------------------------
    # Ensure CNS_PROF is string for deduplication
    # ---------------------------------------------------------------------------
    combined["CNS_PROF"] = combined["CNS_PROF"].astype(str).str.strip()

    # ---------------------------------------------------------------------------
    # Deduplicate by (cns_prof, cod_ibge, year) -- keep first
    # A professional at 2 hospitals in the same municipality counts once
    # ---------------------------------------------------------------------------
    before_dedup = len(combined)
    combined = combined.drop_duplicates(
        subset=["CNS_PROF", "cod_ibge", "year"], keep="first"
    )
    after_dedup = len(combined)
    if before_dedup != after_dedup:
        logger.debug(
            "CNS deduplication: %d -> %d professionals",
            before_dedup, after_dedup,
        )

    # ---------------------------------------------------------------------------
    # Rename columns to lowercase output schema
    # ---------------------------------------------------------------------------
    combined = combined.rename(columns={
        "CNES": "cnes",
        "CBO": "cbo",
        "CNS_PROF": "cns_prof",
    })

    # Select and order output columns
    output_cols = ["cnes", "cod_ibge", "year", "cbo", "cns_prof", "sao_category"]
    combined = combined[output_cols].copy()

    # ---------------------------------------------------------------------------
    # Validate cod_ibge and year (skip duplicate-key check -- professional data
    # has multiple rows per municipality-year by design)
    # ---------------------------------------------------------------------------
    try:
        from database.utils import load_ibge_municipios  # noqa: PLC0415
        ref = load_ibge_municipios()
        valid_codes: set[str] = set(ref["cod_ibge"])
        ibge_mask = combined["cod_ibge"].isin(valid_codes)
        n_invalid = (~ibge_mask).sum()
        if n_invalid > 0:
            logger.warning(
                "cnes_professionals: %d rows with invalid cod_ibge removed",
                n_invalid,
            )
            combined = combined[ibge_mask].copy()
    except FileNotFoundError:
        logger.warning(
            "IBGE reference not found -- skipping cod_ibge validation"
        )

    # Year scope check (2015-2023)
    year_mask = combined["year"].between(2015, 2023)
    n_out = (~year_mask).sum()
    if n_out > 0:
        logger.warning(
            "cnes_professionals: %d rows outside 2015-2023 removed", n_out
        )
        combined = combined[year_mask].copy()

    clean_df = combined

    # ---------------------------------------------------------------------------
    # Write output
    # ---------------------------------------------------------------------------
    out_path = output_dir / "professionals.parquet"
    clean_df.to_parquet(out_path, index=False, compression="snappy")

    # Log summary
    n_surg = len(clean_df[clean_df["sao_category"] == "surgeon"])
    n_anes = len(clean_df[clean_df["sao_category"] == "anesthesiologist"])
    n_obst = len(clean_df[clean_df["sao_category"] == "obstetrician"])
    n_mun = clean_df["cod_ibge"].nunique()
    logger.info(
        "Wrote %d SAO professionals (%d surgeons, %d anesthesiologists, "
        "%d obstetricians) across %d municipalities -> %s",
        len(clean_df), n_surg, n_anes, n_obst, n_mun, out_path,
    )

    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    """Command-line entry point for CNES extraction."""
    parser = argparse.ArgumentParser(
        description="ICSKG-BR CNES Establishment & Professional Extractor"
    )
    parser.add_argument(
        "--zip-path", type=Path, default=None,
        help="Path to ETLCNES.zip archive",
    )
    parser.add_argument(
        "--input-dir", type=Path, default=None,
        help="Directory containing extracted CNES ST CSV files",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=None,
        help="Directory for output Parquet files",
    )
    parser.add_argument(
        "--year", type=int, default=2023,
        help="Target year (default: 2023)",
    )
    parser.add_argument(
        "--download-pf", action="store_true",
        help="Download CNES PF files from DATASUS FTP via PySUS",
    )
    parser.add_argument(
        "--pf-dir", type=Path, default=None,
        help="Directory containing CNES PF files",
    )
    parser.add_argument(
        "--ufs", nargs="+", default=None,
        help="UF codes to download (default: all 27)",
    )
    args = parser.parse_args(argv)

    # Load config for default paths
    try:
        from database.pipeline import load_config  # noqa: PLC0415
        cfg = load_config()
        data_root = Path(cfg.get("data_root", "data_sources"))
    except Exception:  # noqa: BLE001
        data_root = Path("data_sources")

    input_dir = args.input_dir or data_root / "raw" / "cnes"
    output_dir = args.output_dir or data_root / "processed" / "cnes"

    logger.info("=" * 60)
    logger.info("CNES Extraction")
    logger.info("=" * 60)

    # ST facility extraction
    extract_cnes_facilities(
        input_dir=input_dir,
        output_dir=output_dir,
        year=args.year,
        zip_path=args.zip_path,
    )

    # PF professional download (if requested)
    pf_dir = args.pf_dir or data_root / "raw" / "cnes_pf"
    if args.download_pf:
        logger.info("─" * 60)
        logger.info("Downloading CNES PF files from DATASUS FTP")
        download_cnes_pf(
            output_dir=pf_dir, ufs=args.ufs, years=[args.year],
        )

    # PF professional extraction (if PF files available)
    if pf_dir.exists() and any(pf_dir.iterdir()):
        logger.info("─" * 60)
        logger.info("Extracting CNES PF professionals")
        extract_cnes_professionals(
            input_dir=pf_dir, output_dir=output_dir, year=args.year,
        )
    else:
        logger.warning(
            "No CNES PF files at %s -- use --download-pf to download.",
            pf_dir,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
