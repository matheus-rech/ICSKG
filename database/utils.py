"""
ICSKG-BR Shared Database Utilities
===================================
Shared helpers used by every data source parser and the validation gate.

The most critical function is normalize_cod_ibge(), which canonicalizes
Brazilian IBGE municipality codes to a 7-digit zero-padded string. This
function MUST be called before any merge or join operation -- the 6-digit
vs 7-digit discrepancy is the single most common silent data corruption
point in the pipeline (see PITFALLS.md, Pitfall 13).

Usage
-----
    from database.utils import normalize_cod_ibge, load_ibge_municipios

    df["cod_ibge"] = normalize_cod_ibge(df["CD_MUNICIPIO"])
    ref = load_ibge_municipios()
    valid_mask = df["cod_ibge"].isin(ref["cod_ibge"])
"""

import logging
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Path to the authoritative IBGE 2023 municipality reference list.
# Adjust if data_sources/ is on a NAS mount -- use load_config() from pipeline.py
# to get the correct data_root, then pass it to load_ibge_municipios().
IBGE_MUNICIPIOS_PATH: Path = (
    Path(__file__).parent.parent / "data_sources" / "ibge_municipios_2023.csv"
)

# All known municipality code column names across ICSKG-BR data sources.
# Maps source column name -> canonical "cod_ibge".
MUNICIPALITY_CODE_COLUMNS: dict[str, str] = {
    "Código":         "cod_ibge",   # FIRJAN IFGF Excel (2025 edition)
    "Cod_IBGE":       "cod_ibge",   # FIRJAN IFGF Excel (legacy)
    "CD_MUNICIPIO":   "cod_ibge",   # ANS CSV
    "CD_MUN":         "cod_ibge",   # Shapefiles (geobr, IBGE)
    "MUNIC_RES":      "cod_ibge",   # SIH -- municipality of patient residence
    "MUNIC_MOV":      "cod_ibge",   # SIH -- municipality of treatment
    "CODUFMUN":       "cod_ibge",   # CNES -- FIOCRUZ BigData ETLCNES format
    "cod_ibge":       "cod_ibge",   # Already canonical
    "COD_MUNICIPIO":  "cod_ibge",   # Alternate capitalisation (SIOPS)
    "Municipio":      "cod_ibge",   # RENAVAM CSV variant
    "IBGE_MUNICIPIO": "cod_ibge",   # ANS alternate header
}


# ---------------------------------------------------------------------------
# Core normalisation functions
# ---------------------------------------------------------------------------

def normalize_cod_ibge(series: pd.Series) -> pd.Series:
    """Normalize a Series of IBGE municipality codes to 7-digit zero-padded strings.

    Handles all known input formats:
      - 7-digit int  (e.g., 3550308)   -> "3550308"
      - 6-digit int  (e.g., 355030)    -> "0355030"
      - 7-digit str  (e.g., "3550308") -> "3550308"
      - 6-digit str  (e.g., "355030")  -> "0355030"
      - Whitespace-padded strings      -> stripped then zero-padded
      - NaN / None                     -> NaN (preserved, not coerced to string)

    The canonical format is a 7-digit string as used by IBGE's 2023 reference
    list. The 7th digit is a check digit appended by IBGE; 6-digit codes from
    SIH and ANS simply lack it and must be zero-padded, NOT have a check digit
    computed (the check digit cannot be reliably recomputed without the full
    IBGE algorithm and lookup table).

    Parameters
    ----------
    series : pd.Series
        Raw municipality code column from any data source.

    Returns
    -------
    pd.Series
        7-digit zero-padded string codes, with NaN preserved for missing values.
    """
    # Preserve NaN positions before converting to string
    null_mask = series.isna()

    # Convert to string, strip whitespace, zero-pad to 7 digits
    normalized = (
        series.astype(str)
        .str.strip()
        .str.zfill(7)
    )

    # Restore NaN where original was null (zfill converts NaN to "nan")
    normalized = normalized.where(~null_mask, other=np.nan)

    # Log any codes that are NOT exactly 7 chars after normalization (excluding NaN)
    non_null = normalized.dropna()
    bad_length = non_null[non_null.str.len() != 7]
    if len(bad_length) > 0:
        logger.warning(
            "normalize_cod_ibge: %d codes are not 7 digits after normalization. "
            "Sample: %s",
            len(bad_length),
            bad_length.head(5).tolist(),
        )

    return normalized


def map_6digit_to_7digit(series: pd.Series) -> pd.Series:
    """Map 6-digit IBGE codes (without check digit) to 7-digit canonical codes.

    Some sources (FIRJAN IFGF, RENAVAM) use 6-digit IBGE codes that lack
    the check digit. Zero-padding does NOT work — the 7th digit is a check
    digit, not a leading zero. This function builds a crosswalk from the
    IBGE reference list: cod_ibge[:6] -> cod_ibge.

    Parameters
    ----------
    series : pd.Series
        6-digit municipality codes (int or str).

    Returns
    -------
    pd.Series
        7-digit canonical codes. Unmatched codes are returned as NaN.
    """
    ref = load_ibge_municipios()
    valid_7digit = set(ref["cod_ibge"])
    crosswalk_6to7 = dict(zip(ref["cod_ibge"].str[:6], ref["cod_ibge"]))

    null_mask = series.isna()
    keys = series.astype(str).str.strip()

    # First try: already a valid 7-digit code
    mapped = keys.where(keys.isin(valid_7digit), other=np.nan)

    # Second try: map 6-digit codes via crosswalk
    unmapped_mask = mapped.isna() & ~null_mask
    if unmapped_mask.any():
        keys_6 = keys[unmapped_mask].str.zfill(6)
        mapped_6 = keys_6.map(crosswalk_6to7)
        mapped = mapped.fillna(mapped_6)

    # Third try: strip leading zero from zero-padded 7-digit codes (e.g., 0110001 -> 110001)
    unmapped_mask = mapped.isna() & ~null_mask
    if unmapped_mask.any():
        stripped = keys[unmapped_mask].str.lstrip("0").str.zfill(6)
        mapped_stripped = stripped.map(crosswalk_6to7)
        mapped = mapped.fillna(mapped_stripped)

    n_unmapped = mapped.isna().sum() - null_mask.sum()
    if n_unmapped > 0:
        sample = keys[mapped.isna() & ~null_mask].head(5).tolist()
        logger.warning(
            "map_6digit_to_7digit: %d codes not found in IBGE reference. Sample: %s",
            n_unmapped, sample,
        )

    return mapped


def normalize_column_name(col: str) -> str:
    """Map a source-specific municipality column name to the canonical 'cod_ibge'.

    Parameters
    ----------
    col : str
        Column name as it appears in the raw data source.

    Returns
    -------
    str
        "cod_ibge" if the column is a known municipality code variant,
        otherwise the original column name unchanged.
    """
    return MUNICIPALITY_CODE_COLUMNS.get(col, col)


def rename_municipality_column(df: pd.DataFrame) -> pd.DataFrame:
    """Rename the municipality code column in *df* to 'cod_ibge'.

    Searches df.columns for any known municipality code column name variant
    (per MUNICIPALITY_CODE_COLUMNS) and renames the first match found to
    'cod_ibge'. If 'cod_ibge' already exists, returns df unchanged.

    Raises ValueError if no municipality code column is found.
    """
    if "cod_ibge" in df.columns:
        return df
    for col in df.columns:
        if col in MUNICIPALITY_CODE_COLUMNS:
            logger.debug(
                "rename_municipality_column: renaming '%s' -> 'cod_ibge'", col
            )
            return df.rename(columns={col: "cod_ibge"})
    raise ValueError(
        f"No municipality code column found in DataFrame. "
        f"Columns present: {list(df.columns)}. "
        f"Expected one of: {list(MUNICIPALITY_CODE_COLUMNS.keys())}"
    )


# ---------------------------------------------------------------------------
# Reference data loading
# ---------------------------------------------------------------------------

def load_ibge_municipios(path: Path | None = None) -> pd.DataFrame:
    """Load the IBGE 2023 canonical municipality reference list.

    Returns a DataFrame with columns:
      - cod_ibge      : 7-digit string municipality code (canonical key)
      - nome_municipio: Municipality name
      - uf            : 2-letter state code (e.g., "SP")

    The returned DataFrame has 5,571 rows -- one per Brazilian municipality
    as of the IBGE 2025 update (includes Boa Esperanca do Norte-MT, code
    5101837, created after the 2023 reference). Use this as the authoritative
    join key and completeness check for all panel assembly operations.

    Parameters
    ----------
    path : Path, optional
        Path to ibge_municipios_2023.csv. Defaults to IBGE_MUNICIPIOS_PATH.

    Raises
    ------
    FileNotFoundError
        If the reference CSV does not exist at the expected path.
    AssertionError
        If the loaded CSV does not contain exactly 5,570 rows.
    """
    ref_path = path or IBGE_MUNICIPIOS_PATH
    if not ref_path.exists():
        raise FileNotFoundError(
            f"IBGE municipality reference list not found at: {ref_path}\n"
            "Run Task 1 of Plan 01-02 to download ibge_municipios_2023.csv."
        )
    df = pd.read_csv(ref_path, dtype={"cod_ibge": str})
    assert len(df) == 5571, (
        f"IBGE reference list must have 5571 rows; got {len(df)}. "
        f"The reference file at {ref_path} may be corrupted or incomplete."
    )
    assert df["cod_ibge"].nunique() == 5571, (
        "Duplicate cod_ibge values detected in IBGE reference list. "
        "Re-download ibge_municipios_2023.csv."
    )
    logger.info(
        "load_ibge_municipios: loaded %d municipalities from %s",
        len(df),
        ref_path,
    )
    return df
