# Phase 3: Secondary Source Extraction - Research

**Researched:** 2026-04-01
**Domain:** Brazilian government open data APIs and file parsing for 7 CIMI dimensions
**Confidence:** HIGH (sources 1-5), LOW (sources 6-7 RENAVAM/SIOPS)

## Summary

Phase 3 extracts seven secondary data sources that feed CIMI dimensions for the ICSKG-BR panel. Five sources (IBGE SIDRA, IPEA IDHM, FIRJAN IFGF, ANS beneficiaries, IBGE Census 2022 sanitation) have well-documented APIs or bundled files with HIGH confidence. Two sources (RENAVAM vehicle fleet, SIOPS health expenditure) require format discovery and carry LOW confidence.

Critical findings from this research: (1) IBGE SIDRA population table 6579 only covers 2015-2021; Census table 4709 is needed for 2022, and 2023 population estimates use Census-derived figures. (2) SIDRA GDP table 5938 does NOT have a per-capita variable -- GDP per capita must be computed by dividing absolute GDP (variable 37) by population. 2022-2023 GDP data exists but with methodological caveats. (3) IDHM 2022 has NOT been published yet -- the Atlas do Desenvolvimento Humano only has 1991, 2000, 2010 data. All 4 IDHM series are marked INACTIVE in IPEA, awaiting Census 2022 microdata processing. (4) The ipeadatapy library strips territory codes from timeseries output -- the raw OData API must be used directly via requests to get municipality codes (TERCODIGO). (5) RENAVAM CSVs use municipality names (not IBGE codes), requiring a crosswalk join.

**Primary recommendation:** Create one script per data source in `scripts/`, each outputting a standardized Parquet file with `cod_ibge` (7-digit) and `year` columns. Use sidrapy for SIDRA tables, raw requests for IPEA OData, openpyxl for IFGF, existing download_ans.py for ANS, sidrapy for Census 2022 sanitation, and requests with format discovery for RENAVAM/SIOPS.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Use sidrapy library (pinned in pyproject.toml) for SIDRA API access
- IBGE SIDRA Table 6579 for population estimates, Table 5938 for GDP per capita
- Normalize cod_ibge via database/utils.py before writing Parquet
- GDP may have 2-year lag for 2023 -- flag as estimated if unavailable
- IDHM is census-only (2010, 2022) -- use cross-sectional values (NOT interpolated)
- Explicitly document in dimension_metadata that IDHM does not represent genuine temporal variation
- Use ipeadatapy library (pinned) for OData API access
- Extract composite IDHM + education/longevity/income sub-indices
- Parse IFGF from bundled Excel file: data_sources/Evolucao_por_Indicador_2013_a_2024_IFGF_2025.xlsx
- Extract 5 IFGF sub-indices + IFGF Geral for 2015-2023
- ~420 municipalities/year are MNAR (not zero, not dropped -- preserve as NaN)
- Use openpyxl (pinned) for Excel reading
- Existing scripts/download_ans.py provides download infrastructure
- Compute quarterly average (Q1-Q4 mean) NOT December snapshot for ANS
- CSV format: latin-1 encoding, semicolon-delimited
- Private coverage rate = beneficiaries / population; SUS dependence = 1 - coverage
- Census 2022 sanitation: single cross-sectional year (2022) applied to all panel years
- Explicitly flagged as non-time-varying in dimension_metadata
- Extract adequate sanitation % (esgotamento sanitario) + water supply % (abastecimento de agua)
- RENAVAM: BEST EFFORT, format discovery required -- LOW confidence
- SIOPS: BEST EFFORT, format discovery required -- LOW confidence
- If format cannot be parsed: log gap, set dimension to NaN, document in Limitations

### Claude's Discretion
- API pagination strategy for SIDRA (all municipalities in one call vs batched)
- Census 2022 API endpoint selection (Panorama vs direct table download)
- RENAVAM/SIOPS format discovery approach (web scraping vs direct download)
- Error handling for API rate limits and timeouts
- Whether to create one script per source or a unified secondary_sources.py

### Deferred Ideas (OUT OF SCOPE)
- IPCA deflation of monetary variables (Phase 4)
- IFGF multiple imputation for MNAR municipalities (Phase 4)
- PolisPCDaS cross-validation of extracted indicators (later phases)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DATA-03 | IBGE SIDRA extractor -- population (table 6579) + GDP per capita (table 5938) | SIDRA API fully documented: base URL, variable codes, territorial levels, pagination limits (100K values). Population via variable 9324 (table 6579, 2015-2021) + variable 93 (table 4709, 2022-2023). GDP via variable 37 (table 5938). Per capita computed, not fetched. |
| DATA-04 | IPEA IDHM extractor -- composite + sub-indices via OData API | CRITICAL: Only 2010 data available. 2022 IDHM NOT published. Series codes: ADH_IDHM, ADH_IDHM_E, ADH_IDHM_L, ADH_IDHM_R. Must use raw OData API (not ipeadatapy) to get TERCODIGO for municipality codes. |
| DATA-05 | FIRJAN IFGF parser -- 5 sub-indices + IFGF Geral from Excel | Excel file must be placed in data_sources/ (not currently present). openpyxl reading pattern from analysis/icskg_analysis_pipeline.py load_ifgf() serves as reference. Column Cod_IBGE is municipality code. |
| DATA-06 | ANS beneficiary extractor -- quarterly average for coverage rate | Existing download_ans.py fully functional. CSV columns: CD_MUNICIPIO (6-digit), BENEFICIARIOS. Quarterly months: 3, 6, 9, 12. Must compute Q1-Q4 mean per municipality per year. |
| DATA-07 | IBGE Census 2022 sanitation -- adequate sanitation % + water supply % | SIDRA tables 6805 (sanitation) and 6803 (water supply) confirmed available at municipality level. Classification codes for sanitation types identified. Single year 2022. |
| DATA-08 | RENAVAM vehicle fleet -- vehicles per 1,000 inhabitants | BEST EFFORT. Monthly CSV/ZIP on dados.transportes.gov.br. 2003-2026 available. Municipality identified by NAME not IBGE code -- crosswalk needed. Large files (~100MB/month). |
| DATA-09 | SIOPS health expenditure -- per-capita municipal health spending | BEST EFFORT. API at siops-consulta-publica-api.saude.gov.br (Swagger UI). TabNet at DATASUS. Format and endpoints LOW confidence -- format discovery required. |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| sidrapy | 0.1.4 | IBGE SIDRA API client (tables 6579, 5938, 4709, 6805, 6803) | Already pinned in pyproject.toml; thin wrapper over SIDRA REST API |
| ipeadatapy | 0.1.9 | IPEA OData API metadata search | Already pinned; useful for series discovery but NOT for data extraction (strips territory codes) |
| requests | >=2.32 | Raw HTTP for IPEA OData, RENAVAM downloads, SIOPS API | Already pinned; needed for IPEA municipality-level data and RENAVAM ZIP downloads |
| openpyxl | >=3.1 | IFGF Excel parsing | Already pinned; standard for .xlsx reading |
| pandas | >=2.2.3 | DataFrame manipulation, Parquet I/O | Core dependency |
| pyarrow | >=19.0 | Parquet serialization | Core dependency |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| database.utils | local | normalize_cod_ibge(), rename_municipality_column() | Every source before Parquet write |
| database.validation | local | validate_dataframe() quality gate | Every source after DataFrame construction |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| ipeadatapy for IDHM data | Raw OData API via requests | ipeadatapy strips TERCODIGO (municipality code); raw API required |
| sidrapy for Census tables | servicodados.ibge.gov.br API | sidrapy already wraps SIDRA; no benefit from a second API |
| Manual RENAVAM download | basedosdados BigQuery | Requires GCP credentials; direct CSV simpler for this project |

**Installation:**
```bash
# All dependencies already in pyproject.toml -- no new packages needed
uv sync
```

## Architecture Patterns

### Recommended Project Structure
```
scripts/
  extract_ibge_sidra.py    # DATA-03: population + GDP
  extract_ipea_idhm.py     # DATA-04: IDHM composite + sub-indices
  extract_ifgf.py          # DATA-05: FIRJAN IFGF from Excel
  download_ans.py           # DATA-06: existing (needs quarterly avg logic)
  extract_census_sanitation.py  # DATA-07: Census 2022 water + sewage
  extract_renavam.py       # DATA-08: BEST EFFORT vehicle fleet
  extract_siops.py         # DATA-09: BEST EFFORT health expenditure
data_sources/
  processed/
    ibge_sidra/             # population_YYYY.parquet, gdp_YYYY.parquet
    ipea_idhm/              # idhm_2010.parquet (single year)
    ifgf/                   # ifgf_YYYY.parquet (2015-2023)
    ans/                    # ans_YYYY.parquet (2015-2023)
    census_sanitation/      # sanitation_2022.parquet (single year)
    renavam/                # renavam_YYYY.parquet (best effort)
    siops/                  # siops_YYYY.parquet (best effort)
tests/
  test_extract_ibge_sidra.py
  test_extract_ipea_idhm.py
  test_extract_ifgf.py
  test_extract_census_sanitation.py
```

### Pattern 1: Per-Source Extractor Script
**What:** Each data source gets its own script in `scripts/` with a `main(argv=None)` entry point, argparse CLI, and extract function returning a Path to the output Parquet.
**When to use:** Every source in this phase.
**Example:**
```python
# Source: Project convention from database/pipeline.py
def extract_population(
    years: list[int],
    output_dir: Path,
    skip_existing: bool = True,
) -> Path:
    """Fetch IBGE population estimates via SIDRA API."""
    import sidrapy  # noqa: PLC0415
    from database.utils import normalize_cod_ibge  # noqa: PLC0415

    frames = []
    for year in years:
        df = sidrapy.get_table(
            table_code="6579",
            territorial_level="6",
            ibge_territorial_code="all",
            period=str(year),
            variable="9324",
        )
        # First row is header metadata -- skip it
        df = df.iloc[1:]
        df = df.rename(columns={"D1C": "cod_ibge", "V": "populacao", "D3N": "year"})
        df["cod_ibge"] = normalize_cod_ibge(df["cod_ibge"])
        df["populacao"] = pd.to_numeric(df["populacao"], errors="coerce")
        df["year"] = int(year)
        frames.append(df[["cod_ibge", "year", "populacao"]])
    result = pd.concat(frames, ignore_index=True)
    # ... validate and write Parquet
```

### Pattern 2: Raw OData API for IPEA (bypass ipeadatapy)
**What:** Use requests directly against IPEA OData4 endpoint because ipeadatapy strips territory codes.
**When to use:** IDHM extraction only.
**Example:**
```python
# Source: Verified against http://www.ipeadata.gov.br/api/odata4/
IPEA_ODATA_BASE = "http://www.ipeadata.gov.br/api/odata4/"

def fetch_idhm_municipal(series_code: str = "ADH_IDHM") -> pd.DataFrame:
    """Fetch IDHM data with municipality codes from IPEA OData API."""
    url = f"{IPEA_ODATA_BASE}ValoresSerie(SERCODIGO='{series_code}')"
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    records = data["value"]
    df = pd.DataFrame(records)
    # Filter for municipality level only
    df = df[df["NIVNOME"] == "Municípios"].copy()
    df = df.rename(columns={
        "TERCODIGO": "cod_ibge",
        "VALVALOR": "idhm",
        "VALDATA": "date",
    })
    df["year"] = pd.to_datetime(df["date"]).dt.year
    df["cod_ibge"] = normalize_cod_ibge(df["cod_ibge"])
    return df[["cod_ibge", "year", "idhm"]]
```

### Pattern 3: SIDRA API Pagination for Large Requests
**What:** SIDRA limits responses to 100,000 values. For 5,570 municipalities x 9 years x 1 variable = ~50,130 values (under limit). Safe to request all at once for single-variable tables.
**When to use:** Population (6579), GDP (5938), Census sanitation (6805, 6803).
**Caution:** Multi-variable requests can exceed the 100K limit. Request one variable at a time.

### Anti-Patterns to Avoid
- **Using ipeadatapy.timeseries() for municipal data:** Strips TERCODIGO, making it impossible to identify which municipality each value belongs to. Use raw OData API.
- **Requesting `/v/all` with `/n6/all` on multi-variable SIDRA tables:** Exceeds 100K limit. Request specific variable codes.
- **Treating 6-digit ANS municipality codes as 7-digit:** ANS CD_MUNICIPIO is 6-digit. Must pass through normalize_cod_ibge() for zero-padding.
- **Interpolating IDHM between census years:** Locked decision: use cross-sectional values only. Document as non-time-varying.
- **Treating IFGF missing municipalities as zero:** They are MNAR (Missing Not At Random). Preserve as NaN.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| IBGE municipality code normalization | Custom string formatting | `database.utils.normalize_cod_ibge()` | Handles 6/7 digit, NaN preservation, whitespace |
| DataFrame quality checks | Ad-hoc assertions | `database.validation.validate_dataframe()` | Standardized quarantine, reporting, 4 checks |
| SIDRA API HTTP calls | Raw requests to apisidra.ibge.gov.br | `sidrapy.get_table()` | Handles URL construction, parameter encoding |
| Municipality name-to-code crosswalk | Manual lookup table | `database.utils.load_ibge_municipios()` | 5,571-row authoritative reference list |
| ANS CSV download with retry | Simple requests.get() | `scripts/download_ans.py` functions | Has retry logic, encoding handling, merge support |

**Key insight:** All code-level municipality normalization MUST go through the shared utils -- the 6-digit vs 7-digit discrepancy is the number one silent data corruption point.

## Common Pitfalls

### Pitfall 1: SIDRA Table 6579 Does NOT Cover 2022-2023
**What goes wrong:** Requesting `/p/2022,2023` from table 6579 returns empty or error responses.
**Why it happens:** IBGE replaced population estimates with Census 2022 data for 2022. Table 6579 covers 2001-2021 only.
**How to avoid:** Use table 6579 for 2015-2021, table 4709 (Census) for 2022, and for 2023 use the Census-derived municipal populations published by IBGE in August 2023.
**Warning signs:** Empty `V` (value) fields in SIDRA response; `"..."` as value.

### Pitfall 2: SIDRA Table 5938 Has No Per-Capita GDP Variable
**What goes wrong:** Searching for a "GDP per capita" variable returns nothing.
**Why it happens:** Table 5938 only has absolute GDP (variable 37). Per capita must be computed by dividing by population.
**How to avoid:** Fetch GDP (variable 37) and population separately, then compute `gdp_per_capita = gdp / populacao`.
**Warning signs:** Variable code search for "per capita" in table 5938 yields no results.

### Pitfall 3: GDP 2022-2023 Has Methodological Caveats
**What goes wrong:** Using GDP estimates for 2022-2023 without flagging them as preliminary.
**Why it happens:** IBGE adopted different estimation procedures for 2022-2023 (pending 2021 base year rebase in 2027). Sector breakdowns are unavailable.
**How to avoid:** Flag 2022-2023 GDP values as "estimated" in metadata. Document the caveat in the data dictionary.
**Warning signs:** Missing sector-level value-added decomposition for 2022-2023.

### Pitfall 4: ipeadatapy Strips Municipality Codes
**What goes wrong:** IDHM DataFrame has no municipality identifier -- just DATE, VALUE, CODE.
**Why it happens:** ipeadatapy.timeseries() does not include NIVNOME or TERCODIGO in its output.
**How to avoid:** Use raw requests to `http://www.ipeadata.gov.br/api/odata4/ValoresSerie(SERCODIGO='ADH_IDHM')` and filter for `NIVNOME == 'Municípios'`. TERCODIGO is the 7-digit IBGE code.
**Warning signs:** timeseries() DataFrame has 16,776 rows but no column to identify municipalities.

### Pitfall 5: IDHM 2022 Not Yet Published
**What goes wrong:** Assuming Census 2022 IDHM is available and attempting to fetch it.
**Why it happens:** All ADH_IDHM series are marked INACTIVE in IPEA. The Atlas do Desenvolvimento Humano has data for 1991, 2000, 2010 only. Census 2022 microdata processing for IDHM is pending.
**How to avoid:** Use 2010 IDHM as the single cross-sectional value. Document that 2022 IDHM is pending. If published before execution, update the script to fetch both years.
**Warning signs:** All 4 series names end with "- INATIVA".

### Pitfall 6: SIDRA First Row is Metadata
**What goes wrong:** DataFrame includes a header row with column labels as data values.
**Why it happens:** sidrapy.get_table() returns the first row as column description metadata (e.g., "Nivel Territorial (Codigo)").
**How to avoid:** Always skip the first row: `df = df.iloc[1:]` after calling `get_table()`.
**Warning signs:** First row values look like column descriptions, not data.

### Pitfall 7: SIDRA 100K Value Limit
**What goes wrong:** API returns HTTP 400 or truncated data.
**Why it happens:** SIDRA limits queries to 100,000 values. For 5,570 municipalities x 9 years x multiple variables, the limit is easily exceeded.
**How to avoid:** Request one year at a time, or one variable at a time. For single-variable single-year requests: 5,570 values is well under the limit. For multi-year: 5,570 x 9 = ~50K is safe for one variable.
**Warning signs:** HTTP 400 response; message about exceeding value limit.

### Pitfall 8: ANS Municipality Code is 6-Digit
**What goes wrong:** ANS CD_MUNICIPIO does not match IBGE 7-digit codes in joins.
**Why it happens:** ANS uses 6-digit municipality codes without the check digit.
**How to avoid:** Pass through `normalize_cod_ibge()` which zero-pads 6-digit to 7-digit.
**Warning signs:** Empty joins between ANS data and other sources on cod_ibge.

### Pitfall 9: RENAVAM Uses Municipality Names, Not Codes
**What goes wrong:** Cannot directly join RENAVAM data with other sources.
**Why it happens:** RENAVAM CSVs identify municipalities by UF + name, not IBGE code.
**How to avoid:** Join on municipality name + UF against `load_ibge_municipios()` reference table. Handle accent differences and case mismatches with `.str.upper().str.strip()`.
**Warning signs:** Many unmatched municipalities after join (due to accent/name variants).

### Pitfall 10: IFGF Excel File Not in Repository
**What goes wrong:** Script fails with FileNotFoundError when trying to read IFGF Excel.
**Why it happens:** The file `Evolucao_por_Indicador_2013_a_2024_IFGF_2025.xlsx` must be manually downloaded from FIRJAN and placed in `data_sources/`.
**How to avoid:** Check file existence at script start. Provide clear error message with download URL. Consider adding a download function.
**Warning signs:** data_sources/ directory does not contain the .xlsx file.

## Code Examples

### SIDRA API: Fetch Population for All Municipalities (Verified)
```python
# Source: Verified via smoke test against apisidra.ibge.gov.br
import sidrapy
import pandas as pd
from database.utils import normalize_cod_ibge

def fetch_population_year(year: int) -> pd.DataFrame:
    """Fetch population estimates for all municipalities for one year."""
    if year <= 2021:
        # Table 6579: population estimates 2001-2021
        df = sidrapy.get_table(
            table_code="6579",
            territorial_level="6",        # Municipality
            ibge_territorial_code="all",   # All 5,570+
            period=str(year),
            variable="9324",               # Pop. residente estimada
        )
    else:
        # Table 4709: Census 2022 population
        df = sidrapy.get_table(
            table_code="4709",
            territorial_level="6",
            ibge_territorial_code="all",
            period=str(year),
            variable="93",                 # Pop. residente
        )
    # Skip metadata header row
    df = df.iloc[1:]
    df = df.rename(columns={"D1C": "cod_ibge", "V": "populacao"})
    df["cod_ibge"] = normalize_cod_ibge(df["cod_ibge"])
    df["populacao"] = pd.to_numeric(df["populacao"], errors="coerce")
    df["year"] = year
    return df[["cod_ibge", "year", "populacao"]]
```

### SIDRA API Column Mapping (Verified)
```python
# Source: Verified via apisidra.ibge.gov.br/values/t/6579/n6/3550308/v/9324/p/2021?formato=json
# sidrapy.get_table() returns these columns:
#   NC  = Nivel Territorial (Codigo)       -> always "6" for municipalities
#   NN  = Nivel Territorial (Nome)         -> "Municipio"
#   MC  = Unidade de Medida (Codigo)       -> e.g. "45" for Pessoas
#   MN  = Unidade de Medida (Nome)         -> e.g. "Pessoas"
#   V   = Valor                            -> the actual data value
#   D1C = Municipio (Codigo)               -> IBGE 7-digit code
#   D1N = Municipio (Nome)                 -> e.g. "Sao Paulo (SP)"
#   D2C = Variavel (Codigo)                -> e.g. "9324"
#   D2N = Variavel (Nome)                  -> e.g. "Populacao residente estimada"
#   D3C = Ano (Codigo)                     -> e.g. "2021"
#   D3N = Ano (Nome)                       -> e.g. "2021"
# Additional DnC/DnN columns appear when classifications are requested
```

### IPEA OData: Fetch IDHM with Municipality Codes (Verified)
```python
# Source: Verified against http://www.ipeadata.gov.br/api/odata4/
import requests
import pandas as pd
from database.utils import normalize_cod_ibge

IPEA_ODATA_BASE = "http://www.ipeadata.gov.br/api/odata4/"

# Series codes for IDHM (all INACTIVE -- only 1991/2000/2010 data available)
IDHM_SERIES = {
    "ADH_IDHM":   "idhm",          # Composite
    "ADH_IDHM_E": "idhm_educacao",  # Education sub-index
    "ADH_IDHM_L": "idhm_longevidade",  # Longevity sub-index
    "ADH_IDHM_R": "idhm_renda",     # Income sub-index
}

def fetch_idhm_all(target_year: int = 2010) -> pd.DataFrame:
    """Fetch all IDHM indices for municipalities for a census year."""
    frames = []
    for series_code, col_name in IDHM_SERIES.items():
        url = f"{IPEA_ODATA_BASE}ValoresSerie(SERCODIGO='{series_code}')"
        resp = requests.get(url, timeout=120)
        resp.raise_for_status()
        records = resp.json()["value"]
        df = pd.DataFrame(records)
        # Filter: municipalities only, target year only
        df = df[df["NIVNOME"] == "Municípios"].copy()
        df["year"] = pd.to_datetime(df["VALDATA"]).dt.year
        df = df[df["year"] == target_year]
        df = df.rename(columns={"TERCODIGO": "cod_ibge", "VALVALOR": col_name})
        df["cod_ibge"] = normalize_cod_ibge(df["cod_ibge"])
        frames.append(df[["cod_ibge", col_name]])
    # Merge all sub-indices on cod_ibge
    result = frames[0]
    for f in frames[1:]:
        result = result.merge(f, on="cod_ibge", how="outer")
    result["year"] = target_year
    return result
```

### SIDRA Census 2022 Sanitation (Table 6805) (Verified)
```python
# Source: Verified via apisidra.ibge.gov.br response
# Classification c11558 categories for sanitation type:
SANITATION_CODES = {
    46290: "rede_geral_pluvial_fossa_ligada",  # Adequate: rede geral, pluvial, ou fossa ligada
    72110: "rede_geral_pluvial",
    72111: "fossa_septica_ligada_rede",
    72112: "fossa_septica_nao_ligada",
    72113: "fossa_rudimentar_buraco",
    92858: "vala",
    72114: "rio_lago_corrego_mar",
    72115: "outra_forma",
    92861: "sem_banheiro_sanitario",
}

# Fetch: variable 381 = count of households, variable 1000381 = percentage
# For adequate sanitation rate: use code 46290 (rede geral + fossa ligada)
df = sidrapy.get_table(
    table_code="6805",
    territorial_level="6",
    ibge_territorial_code="all",
    period="2022",
    variable="1000381",              # Percentage
    classifications={
        "c11558": "46290",           # Rede geral, pluvial, ou fossa ligada
    },
)
```

### IFGF Excel Parsing (Reference from existing code)
```python
# Source: analysis/icskg_analysis_pipeline.py load_ifgf()
import pandas as pd
from database.utils import normalize_cod_ibge

def parse_ifgf(path: Path, years: range = range(2015, 2024)) -> pd.DataFrame:
    """Parse IFGF Excel file into per-year municipality records."""
    df = pd.read_excel(path, dtype={"Cod_IBGE": str})
    df.columns = df.columns.str.strip()
    df = df.rename(columns={"Cod_IBGE": "cod_ibge"})
    df["cod_ibge"] = normalize_cod_ibge(df["cod_ibge"])
    # IFGF sub-index columns: IFGF_Geral, IFGF_RA, IFGF_GP, IFGF_ID, IFGF_EL, IFGF_SA
    # Plus Year column
    # ~420 municipalities/year are NaN (MNAR) -- preserve as-is
    return df[df["Ano"].between(years.start, years.stop - 1)]
```

## Source-Specific Technical Reference

### Source 1: IBGE SIDRA -- Population (DATA-03)

| Property | Value |
|----------|-------|
| API Base URL | `https://apisidra.ibge.gov.br/values/` |
| Python Library | sidrapy 0.1.4 |
| Table (2015-2021) | 6579 -- Populacao residente estimada |
| Table (2022) | 4709 -- Censo 2022 populacao residente |
| Table (2023) | Census-derived estimates (verify availability) |
| Variable (6579) | 9324 -- Populacao residente estimada |
| Variable (4709) | 93 -- Populacao residente |
| Territorial Level | 6 = Municipality |
| Municipality Code | `ibge_territorial_code="all"` for all, or specific 7-digit code |
| Municipality Code Column | D1C (7-digit IBGE) |
| Rate Limit | 100,000 values per query |
| Response Format | JSON (default), XML |
| Authentication | None required |
| Expected Rows/Year | ~5,570 |

### Source 2: IBGE SIDRA -- GDP (DATA-03)

| Property | Value |
|----------|-------|
| Table | 5938 -- PIB municipios |
| Variable | 37 -- Produto Interno Bruto a precos correntes (absolute, in R$ 1,000) |
| Per Capita | NOT a variable -- must compute: GDP / population |
| Available Years | 2015-2021 confirmed; 2022-2023 with caveats |
| 2022-2023 Caveat | Estimated values, no sector breakdown, pending 2021 base year rebase |
| Municipality Code Column | D1C (7-digit IBGE) |
| Expected Rows/Year | ~5,570 |

### Source 3: IPEA IDHM (DATA-04)

| Property | Value |
|----------|-------|
| API Base URL | `http://www.ipeadata.gov.br/api/odata4/` |
| Endpoint | `ValoresSerie(SERCODIGO='{code}')` |
| Series: Composite | ADH_IDHM |
| Series: Education | ADH_IDHM_E |
| Series: Longevity | ADH_IDHM_L |
| Series: Income | ADH_IDHM_R |
| Status | ALL INACTIVE (awaiting Census 2022 microdata) |
| Available Years | 1991, 2000, 2010 ONLY (2022 NOT published) |
| Municipality Filter | `NIVNOME == "Municípios"` (client-side) |
| Municipality Code | TERCODIGO (7-digit IBGE code) |
| Total Records/Series | ~16,776 (all levels, all years) |
| Municipal Records (2010) | ~5,565 |
| Authentication | None |
| Rate Limit | Not documented, but full series returned in one call |
| CRITICAL | Do NOT use ipeadatapy.timeseries() -- it strips TERCODIGO |

### Source 4: FIRJAN IFGF (DATA-05)

| Property | Value |
|----------|-------|
| Format | Excel (.xlsx) |
| File | `data_sources/Evolucao_por_Indicador_2013_a_2024_IFGF_2025.xlsx` |
| Download | Manual from https://www.firjan.com.br/ifgf/ |
| Municipality Column | Cod_IBGE (string) |
| Key Columns | Ano, Cod_IBGE, IFGF_Geral, IFGF_RA, IFGF_GP, IFGF_ID, IFGF_EL, IFGF_SA |
| Years | 2013-2024 (filter to 2015-2023) |
| MNAR | ~420 municipalities/year missing (NaN, not zero) |
| File Present? | NO -- must be placed in data_sources/ before extraction |

### Source 5: ANS Beneficiaries (DATA-06)

| Property | Value |
|----------|-------|
| Base URL | `https://dados.ans.gov.br/operadoras/informacoes_de_beneficiarios/` |
| File Pattern | `{YYYY}{MM}_Beneficiarios_por_municipio.csv` |
| Encoding | latin-1 |
| Separator | semicolon (;) |
| Municipality Column | CD_MUNICIPIO (6-digit -- needs normalize_cod_ibge) |
| Beneficiary Column | QT_BENEFICIARIO_ATIVO or BENEFICIARIOS (varies by year) |
| Quarterly Months | 3, 6, 9, 12 |
| Coverage Computation | quarterly_avg = mean(Q1, Q2, Q3, Q4); coverage = avg / population |
| Existing Code | scripts/download_ans.py (fully functional) |
| File Size | ~50-100 MB per quarterly CSV |

### Source 6: IBGE Census 2022 Sanitation (DATA-07)

| Property | Value |
|----------|-------|
| Sanitation Table | 6805 -- Domicilios por tipo de esgotamento sanitario |
| Water Table | 6803 -- Domicilios por abastecimento de agua |
| Variable 381 | Count of households |
| Variable 1000381 | Percentage of total |
| Sanitation Classification | c11558 |
| Adequate Sanitation Code | 46290 (rede geral, pluvial, ou fossa ligada a rede) |
| Year | 2022 only (single cross-sectional) |
| Municipal Level | territorial_level="6", ibge_territorial_code="all" |
| Expected Rows | ~5,570 per table |

### Source 7: RENAVAM Vehicle Fleet (DATA-08) -- BEST EFFORT

| Property | Value |
|----------|-------|
| Portal | https://dados.transportes.gov.br/dataset/registro-nacional-de-veiculos-automotores-renavam |
| Format | CSV (2020-2022), ZIP containing CSV (2024-2026) |
| Frequency | Monthly |
| Available | March 2020 -- February 2026 |
| Municipality ID | Municipality NAME (not IBGE code) -- crosswalk required |
| Columns (likely) | UF, MUNICIPIO, TIPO_VEICULO, QUANTIDADE (verify from data dictionary) |
| File Size | Large (~100 MB/month compressed) |
| Strategy | Download December snapshot per year; aggregate total vehicles by municipality; join to IBGE reference on name + UF |
| Risk | Name matching failures due to accents, abbreviations |
| Confidence | LOW |

### Source 8: SIOPS Health Expenditure (DATA-09) -- BEST EFFORT

| Property | Value |
|----------|-------|
| API | https://siops-consulta-publica-api.saude.gov.br/swagger-ui/ |
| TabNet | http://siops-asp.datasus.gov.br/cgi/siops/serhist/MUNICIPIO/indicadores.HTM |
| Alternative | https://dadosabertos.saude.gov.br/dataset/siops |
| Format | JSON API or TabNet HTML scraping |
| Target | Per-capita municipal health spending (total, by source) |
| Municipality ID | Unknown -- format discovery required |
| Years | Unknown -- format discovery required |
| Rate Limit | Unknown |
| Confidence | LOW |
| Strategy | Try API Swagger first; fall back to TabNet; fall back to OpenDataSUS |

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Population estimates (table 6579) through 2023 | Table 6579 only to 2021; Census 2022 (table 4709) for 2022+ | August 2023 (Census publication) | Must use 2 different tables for population |
| IDHM from 1991/2000/2010 Census | Awaiting 2022 IDHM from Atlas DH | Pending (2026-2027?) | Only 2010 available; cross-sectional |
| GDP reference year 2010 | New GDP reference year 2021 coming 2027 | Pending | 2022-2023 GDP values are preliminary |
| ANS December snapshot | Quarterly average (Q1-Q4) | Project decision | Better coverage estimate |
| ipeadatapy for all IPEA data | Raw OData API for municipal data | Ongoing issue | ipeadatapy strips territory codes |

**Deprecated/outdated:**
- ipeadatapy.timeseries() for municipal-level data: Does not return municipality codes. Use raw OData API.
- Table 6579 for 2022+ population: IBGE stopped publishing estimates after Census 2022.
- IDHM "2022": Not yet available. Do not assume it exists.

## Open Questions

1. **2023 Population Source**
   - What we know: Table 6579 stops at 2021. Table 4709 has 2022 Census data. IBGE published "2023 populations" in the DOU based on Census 2022 figures with boundary updates.
   - What's unclear: Is 2023 population available via SIDRA API, or must it be downloaded from IBGE's FTP as a separate publication?
   - Recommendation: Try table 4709 with period=2023. If unavailable, download from IBGE's population estimation publication page.

2. **IDHM 2022 Publication Timeline**
   - What we know: All 4 IDHM series are INACTIVE. Only 1991/2000/2010 data exists.
   - What's unclear: When will Atlas do Desenvolvimento Humano publish 2022 IDHM?
   - Recommendation: Use 2010 IDHM as the single cross-sectional value. Add code to check for 2022 data and incorporate it when available. Document limitation prominently.

3. **IFGF Excel File Availability**
   - What we know: File `Evolucao_por_Indicador_2013_a_2024_IFGF_2025.xlsx` is referenced but NOT present in data_sources/.
   - What's unclear: Exact download procedure and URL from FIRJAN website.
   - Recommendation: Add file download check at script start with clear instructions. Verify column names against reference in analysis/icskg_analysis_pipeline.py.

4. **RENAVAM Municipality Matching**
   - What we know: RENAVAM uses municipality names, not IBGE codes.
   - What's unclear: Exact column names in CSV; how many name mismatches will occur.
   - Recommendation: Download one sample file first, inspect columns, build fuzzy name matching with fallback to manual corrections for persistent mismatches.

5. **SIOPS API Structure**
   - What we know: Swagger UI exists at siops-consulta-publica-api.saude.gov.br. TabNet interface at DATASUS.
   - What's unclear: Endpoint paths, query parameters, available indicators, response format.
   - Recommendation: Start with Swagger UI exploration. If API is non-functional, try OpenDataSUS portal. If neither works, set SIOPS dimension to NaN and document.

6. **SIDRA Table 6803 Classification Code for Water Supply**
   - What we know: Table 6803 has water supply data at municipality level for Census 2022. The classification parameter is unknown (c11556 returned 400 error).
   - What's unclear: Exact classification parameter ID for water supply types.
   - Recommendation: Use sidrapy with `classifications={}` (empty) to get all categories, then filter client-side. Alternatively, try `/c/allxt` in direct API call.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12+ | All scripts | Yes | 3.12+ (via .venv) | -- |
| uv | Package management | Yes | 0.9.11 | pip |
| sidrapy | IBGE SIDRA tables | Yes | 0.1.4 (in .venv) | Raw requests to SIDRA API |
| ipeadatapy | IPEA series discovery | Yes | 0.1.9 (in .venv) | Not used for data extraction (use raw API) |
| requests | IPEA OData, RENAVAM, SIOPS | Yes | (in .venv) | -- |
| openpyxl | IFGF Excel | Yes | (in .venv) | -- |
| pandas | All processing | Yes | 2.2.3+ (in .venv) | -- |
| pyarrow | Parquet I/O | Yes | (in .venv) | -- |
| pytest | Testing | Yes | 8.0+ (in dev deps) | -- |
| Network access | IBGE, IPEA, ANS, RENAVAM, SIOPS APIs | Required | -- | Fixture files for offline dev |
| IFGF Excel file | DATA-05 | NO (not in data_sources/) | -- | Must download manually from FIRJAN |

**Missing dependencies with no fallback:**
- IFGF Excel file must be manually placed in `data_sources/` before running IFGF extraction.

**Missing dependencies with fallback:**
- Network connectivity: test fixtures in tests/fixtures/ can support offline development for unit tests.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.0+ |
| Config file | pyproject.toml (dev dependency group) |
| Quick run command | `.venv/bin/python -m pytest tests/ -x -q` |
| Full suite command | `.venv/bin/python -m pytest tests/ -v --tb=short` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DATA-03 | SIDRA population fetch + GDP per capita computation | unit + integration | `.venv/bin/python -m pytest tests/test_extract_ibge_sidra.py -x` | No -- Wave 0 |
| DATA-04 | IPEA IDHM fetch with municipality codes | unit | `.venv/bin/python -m pytest tests/test_extract_ipea_idhm.py -x` | No -- Wave 0 |
| DATA-05 | IFGF Excel parse with MNAR preservation | unit | `.venv/bin/python -m pytest tests/test_extract_ifgf.py -x` | No -- Wave 0 |
| DATA-06 | ANS quarterly average computation | unit | `.venv/bin/python -m pytest tests/test_extract_ans.py -x` | No -- Wave 0 |
| DATA-07 | Census 2022 sanitation fetch + percentage extraction | unit | `.venv/bin/python -m pytest tests/test_extract_census_sanitation.py -x` | No -- Wave 0 |
| DATA-08 | RENAVAM CSV parse + name crosswalk | unit | `.venv/bin/python -m pytest tests/test_extract_renavam.py -x` | No -- Wave 0 |
| DATA-09 | SIOPS API fetch (if available) | unit | `.venv/bin/python -m pytest tests/test_extract_siops.py -x` | No -- Wave 0 |

### Sampling Rate
- **Per task commit:** `.venv/bin/python -m pytest tests/ -x -q`
- **Per wave merge:** `.venv/bin/python -m pytest tests/ -v --tb=short`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_extract_ibge_sidra.py` -- covers DATA-03 (fixture: sample SIDRA JSON response)
- [ ] `tests/test_extract_ipea_idhm.py` -- covers DATA-04 (fixture: sample OData JSON response)
- [ ] `tests/test_extract_ifgf.py` -- covers DATA-05 (fixture: small IFGF Excel subset)
- [ ] `tests/test_extract_ans.py` -- covers DATA-06 (fixture: sample ANS CSV)
- [ ] `tests/test_extract_census_sanitation.py` -- covers DATA-07 (fixture: sample SIDRA Census response)
- [ ] `tests/test_extract_renavam.py` -- covers DATA-08 (fixture: sample RENAVAM CSV)
- [ ] `tests/test_extract_siops.py` -- covers DATA-09 (fixture: sample SIOPS response)
- [ ] `tests/fixtures/sidra_6579_sample.json` -- offline SIDRA population test data
- [ ] `tests/fixtures/ipea_idhm_sample.json` -- offline IPEA IDHM test data
- [ ] `tests/fixtures/ifgf_sample.xlsx` -- small IFGF Excel for testing

## Project Constraints (from CLAUDE.md)

- **Python 3.12+** with uv-managed environment -- all new scripts must work with Python 3.12
- **PEP 8 compliant**, ~88 char line width, 4-space indentation
- **Logging:** %-style formatting (never f-strings in logger calls), standard levels
- **Error handling:** Broad exception handling with `# noqa: BLE001`, graceful degradation
- **Lazy imports:** Optional dependencies imported inside functions with `# noqa: PLC0415`
- **pathlib.Path** for all file operations; `mkdir(parents=True, exist_ok=True)`
- **Module design:** `if __name__ == "__main__": sys.exit(main())` pattern; `main(argv=None)` with argparse
- **Function design:** Type hints, explicit return types, verb-first names
- **Constants:** ALL_CAPS at module level
- **Section banners:** `# ---------------------------------------------------------------------------` (65 dashes)
- **Conventional commits:** `feat:`, `fix:`, `docs:`, `refactor:`, `test:`
- **GSD workflow:** Do not make direct repo edits outside GSD workflow

## Sources

### Primary (HIGH confidence)
- IBGE SIDRA API (apisidra.ibge.gov.br) -- table metadata, variable codes, period coverage verified via direct API calls
- IPEA OData API (ipeadata.gov.br/api/odata4/) -- series codes, data structure, territory codes verified via live requests
- sidrapy 0.1.4 (github.com/AlanTaranti/sidrapy) -- get_table() parameters and return format verified via smoke test
- ipeadatapy 0.1.9 (github.com/luanborelli/ipeadatapy) -- timeseries() limitation confirmed: strips TERCODIGO
- scripts/download_ans.py -- existing ANS download infrastructure reviewed in full
- database/utils.py -- normalize_cod_ibge(), load_ibge_municipios() reviewed in full
- database/validation.py -- validate_dataframe() reviewed in full

### Secondary (MEDIUM confidence)
- [IBGE SIDRA Table 6805](https://sidra.ibge.gov.br/tabela/6805) -- Census 2022 sanitation classification codes verified via API response
- [IBGE Population Estimates](https://www.ibge.gov.br/estatisticas/sociais/populacao/9103-estimativas-de-populacao.html) -- table 6579 coverage (2001-2021) confirmed
- [IBGE GDP Municipios](https://sidra.ibge.gov.br/tabela/5938) -- 2022-2023 availability with caveats confirmed
- [RENAVAM dataset](https://dados.transportes.gov.br/dataset/registro-nacional-de-veiculos-automotores-renavam) -- file format (CSV/ZIP), date range (2020-2026), structure confirmed
- [Atlas Desenvolvimento Humano](http://www.atlasbrasil.org.br/) -- IDHM only 1991/2000/2010 confirmed

### Tertiary (LOW confidence)
- [SIOPS API](https://siops-consulta-publica-api.saude.gov.br/swagger-ui/) -- Swagger UI exists but endpoint structure not verified (connection refused during testing)
- [SIOPS OpenDataSUS](https://dadosabertos.saude.gov.br/dataset/siops) -- redirects to general portal; actual data access unverified
- RENAVAM CSV column names -- "UF", "MUNICIPIO", "QUANTIDADE" assumed from search results but not verified against actual file

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries already pinned and installed in venv
- Architecture (sources 1-5): HIGH -- API endpoints, variable codes, and data structures verified via live API calls
- Architecture (sources 6-7): LOW -- RENAVAM format partially verified; SIOPS format unknown
- Pitfalls: HIGH -- all 10 pitfalls discovered through actual API testing and code review

**Research date:** 2026-04-01
**Valid until:** 2026-05-01 (stable government APIs; IDHM 2022 publication could change DATA-04 approach)
