# data_sources/

This directory contains input data for the ICSKG-BR analysis pipeline.

## Bundled files

| File | Description | Source |
|------|-------------|--------|
| `Evolucao_por_Indicador_2013_a_2024_IFGF_2025.xlsx` | IFGF fiscal-management index evolution 2013–2024 (all municipalities) | [FIRJAN](https://www.firjan.com.br/ifgf/) |
| `ans_beneficiarios_dez2023.csv` | ANS private-health beneficiary counts by municipality, December 2023 | [ANS Open Data](https://dados.ans.gov.br/) |

## Auto-downloaded directories

These sub-directories are created automatically by the download scripts:

```
data_sources/
├── raw/
│   ├── SIH/          ← DBC files downloaded by scripts/continue_raw_download.py
│   ├── CNES/         ← DBC files downloaded by scripts/continue_raw_download.py
│   └── ANS/          ← CSV files downloaded by scripts/download_ans.py
└── processed/        ← Parquet files produced by database/pipeline.py
```

## Obtaining the source files

### IFGF (FIRJAN)

1. Go to <https://www.firjan.com.br/ifgf/>
2. Click **"Baixar Dados"** and select the full historical series (2013–2024)
3. Rename the downloaded file to `Evolucao_por_Indicador_2013_a_2024_IFGF_2025.xlsx`
4. Place it in this directory

### ANS Beneficiários

```bash
python scripts/download_ans.py --year 2023 --month 12
```

This will download the file and save it as `data_sources/raw/ANS/202312_Beneficiarios_por_municipio.csv`.
The pre-processed version bundled in this package is `ans_beneficiarios_dez2023.csv`.

### SIH / CNES (12-month download)

```bash
python scripts/continue_raw_download.py --source BOTH --end-year 2023 --end-month 12 --months 12
```
