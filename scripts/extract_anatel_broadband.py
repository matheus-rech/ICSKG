"""
ANATEL fixed broadband extractor — Phase 12 SKELETON ONLY
==========================================================
Cookbook §3.6: ANATEL (Technology / Broadband)

Status: SKELETON — not implemented. This file exists so Phase 12's first
commit can be `feat: implement ANATEL fetch` instead of `set up file`.

What this needs to produce
--------------------------
A DuckDB-ingestable parquet at the configured `processed/` directory:

    anatel_broadband.parquet
        cod_ibge       VARCHAR (7-digit IBGE municipality code)
        year           INTEGER  (2015-2023)
        accessos_fixos INTEGER  (fixed-broadband subscribers)
        densidade_ka   DOUBLE   (subscribers per 100 inhabitants)

Joined into the cookbook §5 merge pipeline at step 7
(`Left join ANATEL broadband on (cod_ibge, year)`).
Used by the CUDS Technology dimension (cookbook §6).

Source
------
ANATEL "Acessos Banda Larga Fixa" open data:
    https://www.anatel.gov.br/dadosabertos/paineis_de_dados/acessos
    or
    https://informacoes.anatel.gov.br/paineis/acessos/banda-larga-fixa

Format: monthly CSV per UF or aggregate CSV by year, semicolon-delimited,
latin-1 encoding.

Implementation notes
--------------------
- Aggregate monthly to year-level (max-of-month or december-of-year, TBD)
- Density column: ANATEL ships per-1000 in some files, per-100 in others —
  normalize to per-100 (fraction of population) for consistency with cookbook
- Population denominator: use IBGE population master (joined later in §5)
- Some municipalities have zero broadband; preserve as 0, not NaN
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_anatel_broadband(
    raw_dir: Path,
    output_path: Path,
    *,
    start_year: int = 2015,
    end_year: int = 2023,
) -> Path:
    """Extract ANATEL broadband data and write a parquet at output_path.

    TODO Phase 12:
    1. Find the latest ANATEL CSV under `raw_dir` (or fetch on-demand)
    2. Read with pandas, dtype={'co_ibge': str}
    3. Filter year range, aggregate monthly → annual
    4. Normalize cod_ibge to 7-digit
    5. Compute densidade_ka if not provided
    6. Validate row count (~5,500 muni × 9 years, allow nulls for missing)
    7. Write parquet
    """
    raise NotImplementedError(
        "extract_anatel_broadband: Phase 12 not yet implemented. "
        "See module docstring for the contract."
    )


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="Extract ANATEL fixed broadband data (cookbook §3.6)",
    )
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start-year", type=int, default=2015)
    parser.add_argument("--end-year", type=int, default=2023)
    args = parser.parse_args(argv)

    extract_anatel_broadband(
        raw_dir=args.raw_dir,
        output_path=args.output,
        start_year=args.start_year,
        end_year=args.end_year,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
