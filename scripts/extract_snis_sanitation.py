"""
SNIS sanitation extractor — Phase 12 SKELETON ONLY
==================================================
Cookbook §3.8: SNIS (Sanitation)

Status: SKELETON — not implemented (v0.2.0). This file exists so Phase 12's
first commit can be `feat: implement SNIS fetch` instead of `set up file`.

What this needs to produce
--------------------------
A DuckDB-ingestable parquet at the configured `processed/` directory:

    snis_sanitation.parquet
        cod_ibge                 VARCHAR (7-digit IBGE municipality code)
        year                     INTEGER  (2015-2023)
        agua_pct                 DOUBLE   (water-supply coverage, 0-100)
        esgoto_pct               DOUBLE   (sewage-collection coverage, 0-100)
        coleta_residuos_pct      DOUBLE   (solid-waste collection, 0-100)
        perdas_distribuicao_pct  DOUBLE   (water distribution losses, 0-100)

Joined into the cookbook §5 merge pipeline at step 9
(`Left join SNIS sanitation on (cod_ibge, year)`).
Used by the CUDS Sanitation dimension (cookbook §6); replaces the partial
Census-2022 sanitation proxy used in v0.1.0.

Source
------
SNIS (Sistema Nacional de Informações sobre Saneamento) — Diagnóstico:
    http://www.snis.gov.br/diagnosticos
    https://www.gov.br/cidades/pt-br/acesso-a-informacao/acoes-e-programas/saneamento/snis

Format: per-year ZIP archives, each containing CSV / XLSX with municipal
indicators (semicolon-delimited, latin-1 encoding). SNIS publishes one
ZIP per year covering Água+Esgoto, Resíduos Sólidos, and Águas Pluviais
as separate components.

Implementation notes
--------------------
- Multi-file aggregation required: each year ships 3 component ZIPs
  (AE = Água/Esgoto, RS = Resíduos Sólidos, AP = Águas Pluviais)
- Indicator codes (e.g., IN055 = atendimento total de água) must be mapped
  to canonical column names listed in the schema above
- Coverage may be reported per concessionária (operator); aggregate to
  municipality level by weighted mean on serviced population
- Reporting is voluntary — expect ~70-85% municipality coverage per year
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_snis_sanitation(
    raw_dir: Path,
    output_path: Path,
    *,
    start_year: int = 2015,
    end_year: int = 2023,
) -> Path:
    """Extract SNIS sanitation data and write a parquet at output_path.

    TODO Phase 12:
    1. Locate per-year SNIS ZIPs under `raw_dir` (AE, RS, AP components)
    2. Unzip in-memory and read each component CSV with pandas
       (dtype={'Código do Município': str}, sep=';', encoding='latin-1')
    3. Map SNIS indicator codes (IN055, IN056, IN015, IN049) to canonical names
    4. Aggregate operator-level rows to municipality level (pop-weighted mean)
    5. Pivot to wide format and concatenate years into single long frame
    6. Normalize cod_ibge to 7-digit; preserve nulls for non-reporting munis
    7. Write parquet to output_path
    """
    raise NotImplementedError(
        "extract_snis_sanitation: Phase 12 not yet implemented. "
        "See module docstring for the contract."
    )


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="Extract SNIS sanitation data (cookbook §3.8)",
    )
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start-year", type=int, default=2015)
    parser.add_argument("--end-year", type=int, default=2023)
    args = parser.parse_args(argv)

    extract_snis_sanitation(
        raw_dir=args.raw_dir,
        output_path=args.output,
        start_year=args.start_year,
        end_year=args.end_year,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
