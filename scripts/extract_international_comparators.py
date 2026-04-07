"""
International comparators extractor — Phase 12 SKELETON ONLY
============================================================
Cookbook §3.11: International APIs (WHO GHO / World Bank / UNDP)

Status: SKELETON — not implemented (v0.2.0). This file exists so Phase 12's
first commit can be `feat: implement international comparators fetch`
instead of `set up file`.

What this needs to produce
--------------------------
A DuckDB-ingestable parquet at the configured `processed/` directory:

    international_comparators.parquet
        country_iso3    VARCHAR (ISO 3166-1 alpha-3 country code)
        year            INTEGER  (2015-2023)
        indicator_id    VARCHAR  (source-specific indicator code)
        indicator_name  VARCHAR  (human-readable indicator label)
        value           DOUBLE   (indicator value, units depend on indicator)
        source          VARCHAR  ("WHO_GHO" | "WORLDBANK" | "UNDP_HDI")

NOTE: This is COUNTRY-LEVEL data, not municipality-level — it does NOT join
on (cod_ibge, year) like the other extractors. It powers the cross-country
comparator panels in the BMJ Global Health Discussion section, contrasting
Brazil's CUDS/LCoGS trajectory against peer LMIC and OECD countries.

Sources
-------
- WHO Global Health Observatory:
    https://ghoapi.azureedge.net/api/
- World Bank Open Data:
    https://api.worldbank.org/v2/
- UNDP Human Development Report:
    http://hdr.undp.org/en/data
    https://hdr.undp.org/data-center/documentation-and-downloads

Format: All three are REST/JSON APIs (UNDP also offers bulk CSV/XLSX).

Implementation notes
--------------------
- Country list: include Brazil + LCoGS comparator set (e.g., LMIC peers
  Mexico/Colombia/South Africa/India + OECD anchors USA/UK/Germany/Japan)
- Long-format on (country, year, indicator_id) so new indicators can be
  added without schema changes
- Cache JSON responses locally; APIs are rate-limited and occasionally flaky
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_international_comparators(
    output_path: Path,
    *,
    start_year: int = 2015,
    end_year: int = 2023,
    indicators: list[str] | None = None,
) -> Path:
    """Extract international comparator indicators and write parquet at output_path.

    TODO Phase 12:
    1. Define default indicator set if `indicators` is None:
       - LCoGS bellwether: surgical workforce density (per 100k),
         surgical volume (procedures per 100k), 2-hour access (%),
         catastrophic expenditure (%), impoverishing expenditure (%)
       - WHO GHO: life expectancy at birth, maternal mortality ratio,
         under-5 mortality, UHC service coverage index
       - World Bank: GDP per capita (current USD), gov health expenditure
         (% GDP), urban population (% total), Gini index
       - UNDP: HDI, IHDI, GII, education index
    2. For each source, build URL templates and fetch JSON per (country, year)
    3. Cache raw JSON to disk to avoid re-fetching on restart
    4. Normalize source-specific schemas to the common
       (country_iso3, year, indicator_id, indicator_name, value, source) shape
    5. Tag each row with `source` so downstream analysis can filter by provider
    6. Concatenate into one long-format frame; validate ISO3 codes
    7. Write parquet to output_path
    """
    raise NotImplementedError(
        "extract_international_comparators: Phase 12 not yet implemented. "
        "See module docstring for the contract."
    )


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="Extract international comparator indicators (cookbook §3.11)",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start-year", type=int, default=2015)
    parser.add_argument("--end-year", type=int, default=2023)
    parser.add_argument(
        "--indicators",
        nargs="*",
        default=None,
        help="Optional list of indicator IDs; default uses the LCoGS+WHO+WB+UNDP set",
    )
    args = parser.parse_args(argv)

    extract_international_comparators(
        output_path=args.output,
        start_year=args.start_year,
        end_year=args.end_year,
        indicators=args.indicators,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
