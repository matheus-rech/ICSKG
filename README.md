# ICSKG-BR

**Índice Composto de Saúde e Conhecimento Geral – Brazil**

A longitudinal composite index of health-system capacity and knowledge gaps
across all 5 570 Brazilian municipalities for the period 2013–2024.

---

## Repository structure

```
ICSKG/
├── README.md
│
├── analysis/
│   ├── icskg_analysis_pipeline.py   ← 9/9 CIMI dimensions analysis pipeline
│   └── results/                     ← 4 figures, 8 tables, panel dataset
│
├── database/
│   ├── pipeline.py                  ← Aggregated ETL pipeline
│   ├── build_database_v2.py         ← Database builder
│   └── database_metadata.json       ← Schema and dimension metadata
│
├── scripts/
│   ├── continue_raw_download.py     ← SIH/CNES 12-month download (with resume)
│   ├── download_ans.py              ← ANS historical beneficiary data
│   └── sih_batch_v2.py              ← Optimised SIH batch processor
│
├── data_sources/
│   ├── README.md
│   ├── Evolucao_por_Indicador_2013_a_2024_IFGF_2025.xlsx
│   └── ans_beneficiarios_dez2023.csv
│
├── docs/
│   ├── README.md
│   ├── ICSKG-BR_Methodology_and_Gap_Analysis.md
│   ├── ICSKG-BR_Study_Protocol_v2.docx
│   ├── ICSKG-BR_Variable_Cookbook_v2.xlsx
│   └── ICSKG-BR_Technical_Cookbook_v2.docx
│
├── output/                          ← LCoGS-1 bellwether maps + CSVs
│   └── README.md
│
└── extract_lcogs1.py                ← LCoGS-1 geospatial analysis
```

---

## Quick start

### Requirements

```bash
pip install pandas numpy matplotlib openpyxl pyarrow requests
# Optional (for DBC conversion):
pip install pysus
# Optional (for geospatial maps):
pip install geopandas
# Optional (for DuckDB analytical database):
pip install duckdb
```

### 1 · Download raw data

```bash
# SIH + CNES – last 12 months ending December 2023
python scripts/continue_raw_download.py --source BOTH \
    --end-year 2023 --end-month 12 --months 12

# ANS beneficiaries – full historical series 2013–2023
python scripts/download_ans.py --start 2013-01 --end 2023-12
```

### 2 · Build the database

```bash
# Run the aggregated ETL pipeline (full historical window)
python database/pipeline.py --start 2013-01 --end 2023-12

# Assemble the final SQLite / DuckDB database
python database/build_database_v2.py
```

### 3 · Run the analysis

```bash
# Compute all 9 CIMI dimensions, produce 4 figures + 8 tables + panel CSV
python analysis/icskg_analysis_pipeline.py
```

### 4 · Generate LCoGS-1 maps

```bash
python extract_lcogs1.py --year 2023
```

---

## CIMI Dimensions

| # | Key | Label |
|---|-----|-------|
| 1 | D1_fiscal_governance | Fiscal Governance (IFGF composite) |
| 2 | D2_health_expenditure | Per-capita municipal health expenditure |
| 3 | D3_hospital_capacity | Inpatient beds per 10 000 inhabitants |
| 4 | D4_human_resources | Physicians and nurses per 10 000 |
| 5 | D5_primary_care_coverage | Primary-care coverage index |
| 6 | D6_private_coverage | ANS private-coverage share |
| 7 | D7_maternal_child_health | Maternal-child health composite |
| 8 | D8_chronic_disease_burden | ICSAP hospitalisation rate |
| 9 | D9_health_knowledge_gap | ICSKG composite knowledge-gap score |

---

## Data sources

| Source | Provider | Description |
|--------|----------|-------------|
| SIH | DATASUS/MS | Hospital inpatient microdata |
| CNES | DATASUS/MS | Health facility and workforce registry |
| ANS | ANS/MS | Private health-plan beneficiaries |
| IFGF | FIRJAN | Municipal fiscal management index |
| SIOPS | MS | Municipal health expenditure |
| IBGE | IBGE | Population estimates and shapefiles |

---

## Documentation

Full methodology, variable definitions, and reproducibility instructions are in
[`docs/ICSKG-BR_Methodology_and_Gap_Analysis.md`](docs/ICSKG-BR_Methodology_and_Gap_Analysis.md).

---

## Licence

This project's code is released under the **MIT Licence**.  
The bundled data files are derived from open Brazilian government datasets
and are subject to the [Open Government Data Licence – Brazil](https://dados.gov.br/pagina/licenca).