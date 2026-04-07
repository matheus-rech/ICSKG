"""
RAIS employment extractor — Phase 12 SKELETON ONLY
==================================================
Cookbook §3.7: RAIS (Economy / Workforce)

Status: SKELETON — not implemented (v0.2.0). This file exists so Phase 12's
first commit can be `feat: implement RAIS fetch` instead of `set up file`.

What this needs to produce
--------------------------
A DuckDB-ingestable parquet at the configured `processed/` directory:

    rais_employment.parquet
        cod_ibge          VARCHAR (7-digit IBGE municipality code)
        year              INTEGER  (2015-2023)
        total_employed    INTEGER  (total employed workers, all sectors)
        formal_sector_pct DOUBLE   (formal sector share, 0-100)
        avg_wage_brl      DOUBLE   (average monthly wage in BRL, nominal)

Joined into the cookbook §5 merge pipeline at step 8
(`Left join RAIS employment on (cod_ibge, year)`).
Used by the CUDS Economy / Workforce dimension (cookbook §6).

Note: distinct from `sao_workforce` (CNES health-sector only); RAIS covers
all economic sectors registered with the Ministry of Labor.

Source
------
Ministério do Trabalho — RAIS (Relação Anual de Informações Sociais):
    ftp://ftp.mtps.gov.br/pdet/microdados/RAIS/
    or aggregated municipal bulletins (CSV) from PDET portal.

Format: per-year ZIP archives containing fixed-width / CSV microdata, or
aggregated municipal CSV bulletins (semicolon-delimited, latin-1 encoding).

Implementation notes
--------------------
- Microdata is very large (~10-30 GB/year uncompressed); prefer aggregated
  municipal bulletins where possible
- Average wage should be deflated to a base year (e.g., 2023 BRL) using
  IPCA — but this script writes nominal; deflation happens downstream
- Some small municipalities may be suppressed for confidentiality
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_rais_employment(
    raw_dir: Path,
    output_path: Path,
    *,
    start_year: int = 2015,
    end_year: int = 2023,
) -> Path:
    """Extract RAIS employment data and write a parquet at output_path.

    TODO Phase 12:
    1. Locate per-year RAIS bulletins under `raw_dir` (or fetch from PDET FTP)
    2. Read each year's municipal aggregate CSV with pandas
       (dtype={'cod_ibge': str}, sep=';', encoding='latin-1')
    3. Filter to start_year..end_year and normalize cod_ibge to 7-digit string
    4. Compute formal_sector_pct = formal / (formal + informal) * 100
    5. Concatenate years into a single long-format frame
    6. Validate row count (~5,570 muni × N years; allow gaps for suppressed)
    7. Write parquet to output_path
    """
    raise NotImplementedError(
        "extract_rais_employment: Phase 12 not yet implemented. "
        "See module docstring for the contract."
    )


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="Extract RAIS employment data (cookbook §3.7)",
    )
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start-year", type=int, default=2015)
    parser.add_argument("--end-year", type=int, default=2023)
    args = parser.parse_args(argv)

    extract_rais_employment(
        raw_dir=args.raw_dir,
        output_path=args.output,
        start_year=args.start_year,
        end_year=args.end_year,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
