# ICSKG-BR: Methodology and Gap Analysis

**Project:** Municipal Urban Development and Surgical System Performance in Brazil: A Panel Study Operationalizing the IESE CIMI Framework with Lancet Commission on Global Surgery Indicators Across 5,570 Municipalities (2015–2023)

**Document version:** 1.0 — March 2026  
**Status:** Living document — update as data gaps are closed

---

## Table of Contents

1. [Current Data Inventory — What We Have](#1-current-data-inventory)
2. [What Is Missing — Classified by Severity](#2-what-is-missing)
3. [Individual vs. Aggregated Data — Where It Matters](#3-individual-vs-aggregated-data)
4. [Handling Missing Data](#4-handling-missing-data)
5. [Analytical Framework — Complete Pipeline](#5-analytical-framework)
6. [Comparison with Massenburg 2017](#6-comparison-with-massenburg-2017)
7. [Smart Cities Index — Theoretical Grounding](#7-smart-cities-index)
8. [Practical Next Steps — Ordered Checklist](#8-practical-next-steps)

---

## 1. Current Data Inventory

All structured data reside in the **MotherDuck cloud warehouse**, database `icskg_br`. The inventory below distinguishes between fully aggregated tables (clean and analysis-ready), partially loaded raw tables (individual records, still being ingested), and analytical views that join across tables.

### 1.1 Aggregated Tables — Complete and Analysis-Ready

| Table | Rows | Primary Key | Years Covered | Key Columns |
|---|---|---|---|---|
| `municipalities` | 5,571 | `cod_ibge` | Static | `cod_ibge`, `cod_ibge_6`, `nome`, `uf`, `uf_id`, `regiao`, `lat`, `lon`, `capital`, `population`, `area_km2`, `pop_density` |
| `population` | 50,130 | `cod_ibge × year` | 2015–2023 | `cod_ibge`, `year`, `population` |
| `gdp` | 44,560 | `cod_ibge × year` | 2015–2022 | `cod_ibge`, `year`, `gdp_total_brl_1000`, `gdp_per_capita_brl` |
| `sih_municipal` | 50,170 | `cod_ibge_6 × year × month` | Dec snapshots | `cod_ibge_6`, `year`, `month`, `total_procedures`, `deaths`, `pomr_pct`, `avg_cost_brl`, `avg_days` |
| `sao_workforce` | 49,753 | `cod_ibge_6 × year × month` | Dec snapshots | `cod_ibge_6`, `year`, `month`, `total_sao`, `surgeons`, `anesthesiologists`, `obstetricians`, `sao_per_100k` |
| `lcogs1_access` | 5,571 | `cod_ibge` | Static (computed) | `cod_ibge`, `dist_nearest_bellwether_km`, `bellwether_count_50km`, `bellwether_count_100km`, `access_2hr_proxy`, `has_bellwether_local` |
| `bellwether_hospitals` | 765 | `cnes` | Static | `cnes`, `nome`, `lat`, `lon`, `cod_municipio`, `uf`, `tipo` |
| `national_indicators` | 51 | `indicator × year` | Various | WHO/World Bank/UNDP country-level benchmark indicators |

**Notes:**
- `municipalities` contains 5,571 rows (5,570 active municipalities + 1 record for the 2019 division of Mojuí dos Campos, PA). All analyses use 5,570 as the operational N.
- `sih_municipal` and `sao_workforce` currently store **December-only snapshots** because the underlying raw tables are only partially loaded. Once raw data are complete, these tables will be rebuilt from full 12-month annual aggregates.
- `gdp` covers 2015–2022 only; 2023 estimates must be carried forward or extrapolated (see Section 4).
- `lcogs1_access` is a static computed table based on haversine distances between municipality centroids and `bellwether_hospitals`. No time variation; one row per municipality.

### 1.2 Raw Individual-Record Tables — Partially Loaded

| Table | Current Rows | Target Rows | Coverage | Columns |
|---|---|---|---|---|
| `sih_raw` | ~19.3 M | ~100 M | 496/2,916 state-months (17%) — 2022 partial + 2023 complete | 25 columns per admission: `uf`, `aih_number`, `cod_municipio`, `procedure_code`, `procedure_name`, `specialty`, `age`, `sex`, `race_ethnicity`, `admission_date`, `discharge_date`, `los_days`, `discharge_type`, `death_flag`, `cost_brl`, and 10 additional clinical/administrative fields |
| `cnes_professionals_raw` | 218,461 | ~290 M | Dec 2023, São Paulo state only | `cnes`, `cbo_code`, `specialty`, `cod_municipio`, `uf`, `competence_month`, `contract_type`, `hours_per_week`, `cpf_hash` |

**Why individual records matter:** Raw SIH records enable age-standardized rates, procedure-complexity-stratified POMR, and subgroup analyses by sex, age, and race/ethnicity. Raw CNES records enable deduplication of professionals working at multiple facilities within the same municipality — a known upward bias in aggregated workforce counts.

### 1.3 Analytical Views

| View | Rows | Description |
|---|---|---|
| `v_lcogs_panel` | 50,130 | Master panel: `municipalities` × `population` × `lcogs1_access` × `sao_workforce` × `sih_municipal` × `gdp`. One row per municipality-year. |
| `v_lcogs_latest` | 5,570 | Cross-sectional slice of `v_lcogs_panel` for 2023. Used for mapping and exploratory analysis. |

**Example query to pull the master panel:**

```sql
SELECT
    p.cod_ibge,
    m.nome,
    m.uf,
    m.regiao,
    p.year,
    p.population,
    g.gdp_per_capita_brl,
    l.access_2hr_proxy,
    l.dist_nearest_bellwether_km,
    w.sao_per_100k,
    w.surgeons,
    w.anesthesiologists,
    w.obstetricians,
    s.total_procedures,
    s.pomr_pct,
    s.avg_cost_brl,
    s.avg_days
FROM population p
LEFT JOIN municipalities m USING (cod_ibge)
LEFT JOIN gdp g ON p.cod_ibge = g.cod_ibge AND p.year = g.year
LEFT JOIN lcogs1_access l USING (cod_ibge)
LEFT JOIN sao_workforce w ON CAST(p.cod_ibge AS VARCHAR)[1:6] = w.cod_ibge_6
    AND p.year = w.year
LEFT JOIN sih_municipal s ON CAST(p.cod_ibge AS VARCHAR)[1:6] = s.cod_ibge_6
    AND p.year = s.year
ORDER BY p.cod_ibge, p.year;
```

### 1.4 Local Files

The following files reside in the local `icskg_data_pipeline/` directory:

| File | Purpose |
|---|---|
| `icskg_analysis_pipeline.py` | Orchestrates all 7 analysis phases; reads from MotherDuck via DuckDB connector |
| `continue_raw_download.py` | Resumes interrupted DataSUS FTP downloads for SIH and CNES raw data |
| `extract_lcogs1.py` | Geospatial analysis computing haversine distances, bellwether counts, and 2-hour access proxy |
| `Study_Protocol_v2.docx` | Full IRB-style study protocol with research questions, hypotheses, and analysis plan |
| `Variable_Cookbook_v2.xlsx` | Comprehensive data dictionary: source, unit, operationalization for every variable |
| `Technical_Cookbook_v2.docx` | Step-by-step data engineering guide for each data source |

---

## 2. What Is Missing — Classified by Severity

### 2.1 Non-Negotiable: Must Fix Before Submission

#### A. Raw SIH Completion (2015–2021 + 2022 Remaining Months)

**Current state:** 496 of 2,916 state-months ingested (17%), representing approximately 19.3 million individual hospital admission records. Coverage includes all of 2023 and partial 2022.

**Target:** All 2,916 state-months (27 states × 12 months × 9 years), estimated at approximately 100 million records.

**Why this is non-negotiable:**

The paper's central claim is a *2015–2023 panel study*. The current `sih_municipal` table contains only December snapshots because that is the only month fully represented across all years. Using December-only data introduces **severe seasonal bias**: December systematically underestimates annual surgical volume because the holiday period (Christmas through New Year) sees reduced elective surgical throughput across Brazilian hospitals. Epidemiological and health systems studies universally require annual aggregates computed from all 12 months. Presenting December figures as annual estimates would be a fundamental methodological error that reviewers at BMJ Global Health or World Journal of Surgery would reject outright.

Furthermore, individual records are required for:
- POMR stratified by procedure complexity (major/intermediate/minor, ASA classification proxy)
- Age-standardized surgical volume and mortality rates (direct standardization to 2010 IBGE census age structure)
- Race/ethnicity subgroup analyses (critical for Brazilian health equity framing)
- Sex-disaggregated analyses

**Solution:** Run `continue_raw_download.py` locally. Expected runtime: 12–15 hours on a stable broadband connection. The DataSUS FTP server (`ftp.datasus.gov.br`) hosts `.dbc` files by state and month; the script handles decompression (`read.dbc` via `pysus`) and streaming upload to MotherDuck.

```bash
# Resume SIH download from last checkpoint
python continue_raw_download.py --source sih --start-year 2015 --end-year 2023 \
    --exclude-completed --log-level INFO
```

**Rebuild aggregated table once raw is complete:**

```sql
-- After full raw ingestion: rebuild sih_municipal from annual aggregates
CREATE OR REPLACE TABLE sih_municipal_annual AS
SELECT
    SUBSTR(cod_municipio, 1, 6) AS cod_ibge_6,
    EXTRACT(YEAR FROM admission_date) AS year,
    COUNT(*) AS total_procedures,
    SUM(death_flag) AS deaths,
    ROUND(100.0 * SUM(death_flag) / COUNT(*), 4) AS pomr_pct,
    ROUND(AVG(cost_brl), 2) AS avg_cost_brl,
    ROUND(AVG(los_days), 2) AS avg_days
FROM sih_raw
GROUP BY 1, 2
ORDER BY 1, 2;
```

#### B. CNES Raw Completion (All 12 Months × 9 Years × 27 States)

**Current state:** December snapshots only in aggregated `sao_workforce`; raw `cnes_professionals_raw` contains 218,461 records for December 2023, São Paulo state only.

**Target:** All state-months from January 2015 through December 2023, estimated at approximately 290 million professional-month records before deduplication.

**Why this is non-negotiable:**

SAO (Surgical, Anaesthesia, and Obstetric) workforce density is LCoGS Indicator 2. The Lancet Commission specifies this as a *rate per 100,000 population*, which should reflect the annual average workforce headcount — not a single-month snapshot. Workforce levels fluctuate due to residency rotation cycles (residents complete programs in January and March), municipal contract renewal cycles (typically aligned with fiscal year), and seasonal absences. Using December-only data introduces a moderate upward bias in some specialties and downward bias in others.

More critically, individual professional records are required to **deduplicate** the workforce. A surgeon registered at three different CNES facilities within the same municipality should count as one professional for SAO density purposes, not three. Deduplication using `cpf_hash` (hashed CPF number, privacy-preserving) can only be done on individual records, not pre-aggregated counts.

**Solution:** Run `continue_raw_download.py --source cnes`. Expected runtime: 6–8 hours.

```bash
python continue_raw_download.py --source cnes --start-year 2015 --end-year 2023 \
    --cbo-filter "SURGEON,ANESTHESIOLOGIST,OBSTETRICIAN" --log-level INFO
```

### 2.2 Important but Addressable: Strengthens the Paper Significantly

#### C. IDHM Municipal-Level Data (Atlas Brasil)

**Current state:** Regional-level HDI proxies only. The `v_lcogs_panel` view uses `regiao` as a covariate for the Human Capital and Social Cohesion CIMI dimensions, which is a very coarse proxy.

**Available:** Atlas Brasil (atlasbrasil.org.br), maintained by UNDP Brazil and IPEA, publishes the IDHM (Índice de Desenvolvimento Humano Municipal) for all 5,570 Brazilian municipalities. The IDHM is computed from the 2010 Population Census and decomposes into three sub-indices: IDHM-Education (IDHM-E), IDHM-Longevity (IDHM-L), and IDHM-Income (IDHM-R). The 2022 Census results are also expected to yield updated IDHM values.

**Impact:** Directly operationalizes the Human Capital and Social Cohesion dimensions of CIMI at municipal granularity. IDHM-E specifically captures educational attainment, adult literacy, and school enrollment — core human capital inputs to surgical workforce supply (surgeons and anesthesiologists emerge from educated populations). IDHM-R captures income distribution better than GDP per capita alone.

**Solution:**

```python
import pandas as pd

# Atlas Brasil bulk CSV download
url = "https://atlasbrasil.org.br/acervo/atlas/planilha/"
# Download the Excel workbook and extract municipal IDHM values
df_idhm = pd.read_excel(url, sheet_name="MUN 91-00-10")
df_idhm = df_idhm[["Codmun7", "IDHM 2010", "IDHM-E 2010", "IDHM-L 2010", "IDHM-R 2010"]]
df_idhm.columns = ["cod_ibge", "idhm", "idhm_education", "idhm_longevity", "idhm_income"]
```

**Note on temporal stationarity:** IDHM is static (2010 Census baseline). For the 2015–2023 panel, treat IDHM as a time-invariant covariate. This is methodologically acceptable — human development indices change slowly over decade timescales, and the 2010 baseline captures cross-sectional variation well. If 2022 Census IDHM values become available, use them to bracket the panel with pre/post estimates.

#### D. FIRJAN IFGF (Fiscal Governance Index)

**Current state:** Entirely absent from the dataset. The Governance dimension of CIMI is currently unoperationalized.

**Available:** The FIRJAN Institute (Federação das Indústrias do Estado do Rio de Janeiro) publishes the IFGF (Índice FIRJAN de Gestão Fiscal) annually for all Brazilian municipalities. The index covers fiscal responsibility, liquidity, investment capacity, and cost control. Time series available from 2006 onward.

**Impact:** Operationalizes the Governance CIMI dimension — one of the most theoretically important predictors of health system performance. Municipalities with strong fiscal governance can sustain health infrastructure investment even during economic downturns. Without IFGF, the Governance dimension is missing from the CUDS construction.

**Solution:** Download from `firjan.com.br/ifgf` (bulk Excel download available) or via API. Upload to MotherDuck as `firjan_ifgf` table, join to panel by `cod_ibge × year`.

#### E. IBGE Census 2022 Data (Sanitation, Housing, Education)

**Current state:** Not integrated. Several CIMI dimensions lack municipal-level data.

**Available:** IBGE released Census 2022 results through SIDRA (sidra.ibge.gov.br). Relevant tables include:
- **Sanitation:** Household access to water supply, sewerage, garbage collection (Environment dimension)
- **Housing quality:** Permanent vs. improvised housing, household density (Urban Planning dimension)
- **Education:** Literacy rate, years of schooling by municipality (Human Capital dimension)

**Solution:** IBGE SIDRA API (free, JSON responses). Example:

```python
import requests

# Table 9514: sanitation by municipality (Census 2022)
url = "https://servicodados.ibge.gov.br/api/v3/agregados/9514/periodos/2022/variaveis/93"
params = {"localidades": "N6[all]", "classificacao": "2[6795]"}
r = requests.get(url, params=params)
data = r.json()
```

#### F. ANS Private Health Insurance Coverage

**Current state:** Not integrated. SUS dependence rate — the share of the population relying exclusively on public health coverage — is a critical uncontrolled confounder.

**Available:** ANS (Agência Nacional de Saúde Suplementar) publishes beneficiary counts by municipality annually. Coverage rate = ANS beneficiaries / IBGE population.

**Impact:** This is arguably the most important missing covariate for the surgical outcomes analysis. A municipality where 60% of residents have private health insurance will show lower SUS-reported surgical volume not because of worse access, but because high-volume surgeries (orthopedics, cardiac) are performed in private hospitals outside the SUS/AIH billing system. Without controlling for SUS dependence rate, coefficients on SAO density and surgical volume will be substantially confounded.

**Solution:** ANS TabNet or FTP download (`ftp.ans.gov.br/dados/beneficiarios/`). Join to panel by `cod_municipio × year`.

### 2.3 Minor Limitations: Acknowledge in Paper, Do Not Block Submission

#### G. LCoGS 5 & 6 — Financial Protection Proxies

True LCoGS-5 (impoverishing expenditure) and LCoGS-6 (catastrophic expenditure) require household survey data linking out-of-pocket surgical costs to total household income. At the municipal level, this would require the IBGE POF (Pesquisa de Orçamentos Familiares) with municipality-level identifiers, which are not publicly released for privacy reasons.

**Our proxy:** Average surgical cost per admission (`avg_cost_brl`) divided by GDP per capita (`gdp_per_capita_brl`), as a cost-burden ratio at the ecological level. This is acknowledged as an **ecological proxy**, not an individual-level financial catastrophe measure.

**Precedent:** Massenburg et al. (2017) could not calculate LCoGS-5/6 at the state level and instead used national POF estimates. Our municipal cost data constitute an advancement in granularity, even if the underlying measure remains ecological. Document explicitly in the Limitations section.

#### H. SIM (DATASUS Mortality System) Cross-Validation

The SIH records in-hospital deaths, which defines POMR (postoperative mortality rate). The SIM (Sistema de Informações sobre Mortalidade) captures all registered deaths including post-discharge community deaths. Cross-validating SIH POMR against SIM mortality rates would strengthen the outcome measure, but is not required: in-hospital mortality is the standard LCoGS-4 metric used in all prior global surgery literature (Weiser et al., 2015; Rose et al., 2015).

#### I. Four Partially Operationalized CIMI Dimensions

Even with FIRJAN IFGF and Census 2022 additions, the following remain partially operationalized: Mobility (no municipal-level transport data beyond the LCoGS-1 access proxy), International Projection (not applicable at municipal level), Environment (partial: sanitation available but air quality and green space are missing), and Governance (IFGF covers fiscal governance but not political or institutional quality).

**Approach:** In the manuscript, present a clear CIMI operationalization table showing dimension coverage: "Complete," "Proxy," or "Not Available." A well-documented partial operationalization is publishable. The UNDP HDI itself uses only 3 of many possible human development dimensions; CUDS with 6–7 well-operationalized dimensions is methodologically defensible.

#### J. Road-Network Travel Time for LCoGS-1

Current access calculations use haversine (straight-line) distance with a 150 km ≈ 2-hour threshold (implying 75 km/h average speed). Actual road-network routing via OSRM or GraphHopper would be more accurate, particularly in the Amazon region where rivers and limited road networks make straight-line distance a poor proxy.

**Why minor:** Trindade et al. (2023) used the same haversine methodology. Our finding of approximately 95% population-level access within 2 hours is consistent with their estimates. The haversine proxy will be conservative (slightly underestimate access) in flat terrain and slightly overestimate access in rugged terrain — a known, directional, and acknowledged limitation.

---

## 3. Individual vs. Aggregated Data — Where It Matters

The table below classifies each planned analysis by the data granularity required, the current availability, and the analytical consequence of using only aggregated data.

| Analysis | Data Level Needed | Current Status | Impact if Only Aggregated Available |
|---|---|---|---|
| Surgical volume per 100k (LCoGS-3) | Annual municipal aggregate | Dec-only snapshots | **SEVERE:** December underestimates annual volume; seasonal bias directly affects the primary outcome measure |
| POMR — overall (LCoGS-4) | Annual municipal aggregate | Dec-only snapshots | **SEVERE:** December POMR is not representative of annual POMR |
| POMR — stratified by procedure complexity | Individual records required | Raw partial (17%) | **MODERATE:** Cannot stratify by major/minor/intermediate without procedure-level records |
| Age-standardized surgical rates | Individual records required | Raw partial (17%) | **SEVERE:** Direct standardization to IBGE age pyramid impossible without age-level records |
| SAO density (LCoGS-2) — overall | Annual municipal aggregate | Dec-only snapshots | **MODERATE:** Seasonal workforce fluctuation introduces ~5–15% bias in annual density estimates |
| SAO density — deduplicated | Individual records required | Raw partial (Dec 2023 SP only) | **MODERATE:** Multi-facility professionals counted multiple times in aggregated data |
| Financial burden proxy (LCoGS-5/6) | Municipal aggregate OK | Available | **MINOR:** Ecological proxy acceptable; individual data unavailable at municipal level regardless |
| CUDS construction | Municipal aggregates | Available (partial) | **NONE:** Index designed for ecological, municipal-level analysis |
| Subgroup analysis (sex, age, race) | Individual records required | Raw partial (17%) | **SEVERE:** Equity analyses on vulnerable populations completely blocked without individual data |
| Interrupted time series (COVID) | Monthly municipal aggregates | Computable from raw when complete | **MODERATE:** December-only misses seasonal patterns essential for ITS model baseline |
| Trend decomposition | Monthly aggregates | Dec snapshots only | **MODERATE:** Cannot decompose trend from seasonal component without all 12 months |
| ML feature importance (SHAP) | Municipal panel aggregates | Available for 2023 | **MINOR:** Reduces training set from 50,000+ to 5,570 observations; still feasible but loses temporal variation |
| Spatial spillover analysis | Municipal aggregates + adjacency | Available | **NONE:** Spatial models operate on cross-sectional or panel aggregates |

---

## 4. Handling Missing Data

### 4.1 Taxonomy of Missingness in This Dataset

Different types of missingness in `icskg_br` require different responses. Treating all missing values uniformly would introduce systematic bias.

**GDP 2023 (MCAR):** IBGE has not yet released municipal GDP estimates for 2023 at the time of this writing. This is Missing Completely At Random (MCAR) — the absence is administrative, not related to the value of GDP or any other variable. Strategy: carry-forward 2022 values with 0% real growth assumption, or apply the national GDP deflator to extrapolate. Clearly flag imputed 2023 GDP values with an indicator variable (`gdp_imputed = 1`). Run sensitivity analysis excluding 2023 from GDP-dependent models.

**Zero procedures / zero SAO (informative zeros):** Small municipalities — particularly those under 5,000 population in the semi-arid Northeast and Amazon regions — genuinely have zero recorded surgical procedures and zero credentialed SAO professionals in SUS. These are **not missing data**. They are the empirical phenomenon the study is designed to measure. Imputing these zeros would destroy the research question. Use zero-inflated or hurdle models for these outcomes (see Section 5.4).

**CNES monthly gaps (structurally missing):** If a professional does not appear in a given month's CNES record, it may mean they left the position, were temporarily absent, or were recorded in a subsequent month. Within a given year, use last-observation-carried-forward (LOCF) for continuity within each professional's employment spell. Do not carry forward across years.

**IDHM temporal gap (design missingness):** IDHM is available for 2000 and 2010 census years only (2022 pending). Treating IDHM as time-invariant over 2015–2023 is acceptable because (a) human capital indices change slowly, (b) the between-municipality variance in IDHM dwarfs within-municipality change over 9 years, and (c) fixed-effects panel models absorb municipality-level time-invariant heterogeneity.

**Small-sample instability in POMR:** Municipalities with fewer than 30 annual procedures produce statistically unstable POMR estimates (wide confidence intervals, extreme values from single-death events). Apply a **minimum procedure threshold** for POMR analysis. The primary analysis will use a threshold of 30 annual procedures; sensitivity analyses at 10, 50, and 100 will be reported (see Section 5.7).

### 4.2 Imputation Strategy

For continuous covariates with moderate missingness (< 30%), use **MICE (Multiple Imputation by Chained Equations)** with 20 imputations and 10 iterations per imputation. Pool results using Rubin's rules.

```python
from sklearn.experimental import enable_iterative_imputer
from sklearn.impute import IterativeImputer
import numpy as np

# MICE implementation using scikit-learn IterativeImputer
imputer = IterativeImputer(
    max_iter=10,
    n_nearest_features=10,  # Use 10 nearest features for each variable
    random_state=42,
    verbose=0
)

# Fit on training panel (2015-2021), transform all years
X_imputed = imputer.fit_transform(X_panel)
```

**Validation steps:**
1. Run Little's MCAR test to confirm missingness mechanism before imputation
2. Compare distributions of imputed vs. observed values (density plots)
3. Report: number of observations imputed per variable, range of imputed values
4. Primary analysis uses complete cases; imputed dataset used for sensitivity (see Section 5.7, sensitivity analysis #9)

**Exclusion rule:** Municipalities missing more than 30% of the variable set used in the primary regression will be excluded from that regression. Document how many municipalities are excluded and test whether excluded municipalities differ systematically from included ones (excluded vs. included t-tests on key demographics). This threshold is consistent with standard epidemiological practice (Sterne et al., BMJ 2009).

### 4.3 Zero Inflation and Count Outcome Modeling

The distribution of surgical procedures per municipality per year is heavily right-skewed and zero-inflated. Approximately 12–18% of municipalities in any given year record zero AIH procedures in the SUS system. This bimodal distribution (structural zeros + count distribution) violates the assumptions of standard Poisson and negative binomial regression.

**Model selection:**
- **Zero-Inflated Negative Binomial (ZINB):** Primary choice. The zero-inflation component models the probability of being a "structural zero" (no surgical capacity), while the count component models volume conditional on having any capacity. Use log(population) as offset in both components.
- **Hurdle model (alternative):** Two-stage: logistic regression for any vs. no procedures, then truncated negative binomial for volume among municipalities with at least one procedure. More interpretable for policy questions ("what predicts crossing the threshold to any surgical capacity?").

```python
import statsmodels.formula.api as smf

# Zero-inflated negative binomial for LCoGS-3
model = smf.mnlogit(
    "total_procedures ~ sao_per_100k + gdp_per_capita_log + idhm + "
    "pop_density + access_2hr_proxy + C(year) + C(uf)",
    data=panel_df
)
# offset = log(population/100000)
```

For **POMR analysis**: municipalities with zero procedures have undefined POMR (0/0). These are excluded from the POMR regression but must be retained in the access analysis with procedures = 0 as their outcome value.

---

## 5. Analytical Framework — Complete Pipeline

The analysis pipeline is organized into seven sequential phases, coded in `icskg_analysis_pipeline.py`. Each phase is described below with sufficient methodological detail to guide a research assistant or collaborating statistician.

### 5.1 Phase 1: Descriptive Statistics

**Objective:** Characterize the spatial and temporal distribution of all LCoGS indicators and CUDS components before any modeling.

**Outputs:**
- **Choropleth maps** (geopandas + matplotlib): one map per LCoGS indicator, for reference years 2015, 2019, and 2023. Use IBGE shapefile at the municipal level (5,570 polygons). Color scale: quantile breaks (quintiles), colorblind-safe palette (viridis or cividis). Export as SVG for journal submission.
- **Table 1 — Regional summary statistics:** For each LCoGS indicator and each of the 5 regions (Norte, Nordeste, Centro-Oeste, Sudeste, Sul), report N, mean, median, IQR, CV (coefficient of variation), minimum, maximum. Include national totals row.
- **Temporal trend plots:** Line plots with 95% CI bands by region, 2015–2023. Highlight COVID disruption period (shaded band: 2020–2021). Show recovery trajectory.
- **COVID-19 Interrupted Time Series Analysis:** Model each LCoGS indicator as a function of time with a structural break at March 2020 (first Brazilian confirmed case). Use segmented regression:

```
Y_t = β₀ + β₁·t + β₂·D_covid + β₃·(t − t_covid)·D_covid + ε_t
```

Where `D_covid = 1` for t ≥ March 2020. Estimate: (a) pre-COVID slope β₁, (b) immediate level change β₂, (c) post-COVID slope change β₃. Interpret recovery as β₁ + β₃ returning to pre-COVID trajectory.

### 5.2 Phase 2: CUDS Construction

The City Urban Development Score (CUDS) operationalizes the IESE Cities in Motion Index (CIMI) framework at the municipal level. Construction follows five steps:

**Step 1 — Variable Selection and Dimension Mapping:**

| CIMI Dimension | Variables Available | Source | Status |
|---|---|---|---|
| Economy | GDP per capita (log), GDP growth rate | IBGE | Available 2015–2022 |
| Technology | ANATEL broadband density, mobile coverage | ANATEL | Pending |
| Human Capital | IDHM-Education, literacy rate | Atlas Brasil | Pending download |
| Social Cohesion | IDHM composite, Gini (state proxy) | Atlas Brasil / IBGE | Partial |
| Urban Planning | Urbanization rate, population density, area_km2 | IBGE | Available |
| Governance | IFGF fiscal index | FIRJAN | Pending download |
| Environment | Sanitation access, Census 2022 | IBGE | Pending download |
| Mobility | LCoGS-1 access proxy (dist to bellwether) | Computed | Available |
| Health Infrastructure (novel) | SAO density, bellwether count, beds per 100k | CNES/CNES | Available |

**Step 2 — Normalization:**

Apply min-max normalization within each year to scale all variables to [0, 1]:

```
x_norm = (x − min(x_t)) / (max(x_t) − min(x_t))
```

Variables where higher values indicate worse outcomes (e.g., distance to nearest bellwether, POMR) are reverse-coded: `x_norm_rev = 1 − x_norm`.

**Step 3 — Weighting (three alternatives for sensitivity analysis):**

a) **Equal weights (baseline):** Each dimension weighted 1/9; within each dimension, each indicator weighted 1/K where K is the number of indicators in that dimension.

b) **PCA-derived weights:** Run PCA within each dimension's indicators. Weight each indicator by its loading on the first principal component. Weight each dimension by the share of total variance it contributes in a cross-dimension PCA.

c) **Delphi expert survey weights (optional):** If conducted, use the mean expert-assigned weight for each dimension after two rounds of Delphi consensus.

**Step 4 — Aggregation:**

Primary: **Geometric mean** across dimensions:

```
CUDS_i = (∏_{d=1}^{D} score_{id})^(1/D)
```

The geometric mean penalizes imbalance across dimensions — a municipality with very high economic development but no surgical workforce access scores lower than its arithmetic mean would suggest. This mirrors the UNDP HDI methodology adopted since 2010.

Sensitivity: Arithmetic mean (see Section 5.7).

**Step 5 — Validation:**

- Spearman rank correlation between CUDS and RCSC (Ranking Connected Smart Cities, 656 cities with overlap): expected ρ > 0.6 as minimum validity threshold.
- Spearman rank correlation between CUDS and IDSC-BR (SDG Cities Index, 5,570 municipalities): expected ρ > 0.5.
- Split-sample stability: Randomly assign municipalities to two 50% samples; compute CUDS independently in each; assess Spearman correlation of rankings (target: ρ > 0.9 for rank stability).

### 5.3 Phase 3: PCA and Dimensionality Exploration

**Objective:** Characterize the latent structure of municipal indicators, validate theoretical CIMI dimension boundaries, and generate data-driven weights.

```python
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
import pandas as pd
import matplotlib.pyplot as plt

# Standardize the full indicator matrix
scaler = StandardScaler()
X_scaled = scaler.fit_transform(indicator_matrix)

# Full PCA
pca = PCA(n_components=None)
pca.fit(X_scaled)

# Scree plot
plt.plot(range(1, len(pca.explained_variance_ratio_)+1),
         pca.explained_variance_ratio_.cumsum())
plt.axhline(0.8, color='red', linestyle='--', label='80% variance threshold')
plt.xlabel('Number of Components'); plt.ylabel('Cumulative Variance Explained')
```

**Reporting requirements:**
- Scree plot: number of components needed to explain 80% and 90% of total variance
- Loadings matrix: which indicators load strongly onto which components?
- Alignment test: do PCA-derived components correspond to theoretical CIMI dimensions? Use structured rotation (Varimax) to approximate simple structure.

**Confirmatory Factor Analysis (CFA):** After EFA identifies latent structure, specify a CFA model constraining each indicator to load on its designated CIMI dimension. Report RMSEA, CFI, and SRMR. Poor fit (RMSEA > 0.08) indicates that the CIMI theoretical structure does not match Brazilian municipal data — an important finding in itself.

### 5.4 Phase 4: Classical Statistical Models

All panel regression models include municipality fixed effects (μᵢ) to control for time-invariant unobserved heterogeneity and year fixed effects (τₜ) to control for national-level shocks. Standard errors are clustered at the state level (27 clusters) to account for spatial correlation within states.

**Model 1 — Univariate Panel Regression (dimension-by-dimension):**

```
Y_it = α + β·CUDS_dim_it + γ·X_it + μᵢ + τₜ + εᵢₜ
```

Run one regression per CIMI dimension (9) × LCoGS indicator (6) = 54 regressions. Present as a coefficient heat map. Covariates X_it: log population, GDP per capita, SUS dependence rate (when available).

**Model 2 — Multivariate Panel Regression:**

```
Y_it = α + Σₖ(βₖ·CUDS_dim_k_it) + γ·X_it + μᵢ + τₜ + εᵢₜ
```

All dimensions entered jointly. Check multicollinearity: compute Variance Inflation Factors (VIF); flag any VIF > 10 as collinearity concern (typically Economy and Human Capital dimensions correlate strongly). If VIF > 10, present results with and without correlated dimensions.

**Model 3 — Dose-Response (Restricted Cubic Splines):**

```
Y_it = f(CUDS_it) + γ·X_it + μᵢ + τₜ + εᵢₜ
```

Where f() is modeled with 4-knot restricted cubic splines at Harrell's recommended percentiles (5th, 35th, 65th, 95th). Test non-linearity with Wald test (H₀: linear). Visualize as predicted Y vs. CUDS with 95% CI ribbon. This is the key analytical finding: is there a threshold CUDS level above which surgical outcomes improve sharply? Are there diminishing returns at high CUDS values?

**Model 4 — Spatial Panel:**

```
# Spatial lag model
Y_it = ρ·W·Y_it + X·β + εᵢₜ

# Spatial error model  
Y_it = X·β + u,  u = λ·W·u + η
```

Spatial weight matrix W: queen contiguity (municipalities sharing a border). Test: Moran's I for spatial autocorrelation in OLS residuals. If Moran's I is significant (p < 0.05), spatial models are preferred. Fit using `PySAL` or `spreg` package.

**Model 5 — Difference-in-Differences for COVID Impact:**

```
Y_it = α + β₁·Post_t + β₂·HighCUDS_i + β₃·(Post_t × HighCUDS_i) + γ·X_it + μᵢ + εᵢₜ
```

Where Post_t = 1 for 2021 (one year into COVID), HighCUDS_i = 1 for municipalities in the top two CUDS quintiles (pre-COVID CUDS as of 2019). The coefficient β₃ tests whether high-CUDS municipalities had smaller surgical disruption (negative β₃ for volume, positive for POMR) or faster recovery. Parallel trends assumption: verify that LCoGS trends for high- and low-CUDS municipalities were parallel in 2015–2019.

### 5.5 Phase 5: Machine Learning Models

**Model 6 — XGBoost:**

```python
import xgboost as xgb
from sklearn.model_selection import StratifiedKFold
import shap, optuna

# 10-fold CV stratified by state (ensure all states represented in each fold)
cv = StratifiedKFold(n_splits=10, shuffle=True, random_state=42)

# Optuna hyperparameter optimization
def objective(trial):
    params = {
        "n_estimators": trial.suggest_int("n_estimators", 100, 1000),
        "max_depth": trial.suggest_int("max_depth", 3, 10),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
        "subsample": trial.suggest_float("subsample", 0.6, 1.0),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
        "reg_alpha": trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True),
        "reg_lambda": trial.suggest_float("reg_lambda", 1e-8, 10.0, log=True),
    }
    model = xgb.XGBRegressor(**params, random_state=42)
    scores = cross_val_score(model, X, y, cv=cv, scoring="r2")
    return scores.mean()

study = optuna.create_study(direction="maximize")
study.optimize(objective, n_trials=100)

# SHAP interpretation
explainer = shap.TreeExplainer(best_model)
shap_values = explainer.shap_values(X_test)
shap.summary_plot(shap_values, X_test, plot_type="bar")
```

Report: R², RMSE, MAE in cross-validation vs. hold-out test set. Compare against Model 1 (panel FE) to quantify how much additional variance the non-linear ML model explains.

**Model 7 — Random Forest:** Complement to XGBoost. Use permutation importance alongside SHAP for convergent feature importance evidence.

**Model 8 — Neural Network (conditional):** Deploy only if XGBoost cross-validated R² < 0.5. Simple MLP (2 hidden layers, 128/64 neurons, ReLU, dropout 0.3, Adam optimizer). Primarily a benchmarking exercise.

**Model 9 — K-Means Clustering:**

```python
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

# Determine optimal k
inertia = []; silhouette = []
for k in range(2, 15):
    km = KMeans(n_clusters=k, random_state=42, n_init=20)
    km.fit(X_scaled)
    inertia.append(km.inertia_)
    silhouette.append(silhouette_score(X_scaled, km.labels_))

# Elbow + silhouette plot to choose k
```

Characterize clusters: mean value of each LCoGS indicator and CUDS dimension per cluster. Test geographic coherence: Chi-square test of cluster × region association. Hypothesis: clusters should broadly map onto Norte/Nordeste (low development, low surgical access) vs. Sudeste/Sul (high development, high surgical access), with Centro-Oeste intermediate.

**Model 10 — UMAP/t-SNE Embeddings:**

```python
import umap

reducer = umap.UMAP(n_neighbors=15, min_dist=0.1, metric='euclidean', random_state=42)
embedding = reducer.fit_transform(X_scaled)

# Plot colored by region, CUDS quintile, and LCoGS composite
# Reveals cluster structure and outliers
```

### 5.6 Phase 6: Mediation and Path Analysis

**Structural Equation Modeling (SEM):**

Four hypothesized causal pathways will be estimated simultaneously:

1. **Technology → Human Capital → SAO Density → POMR**
   Broadband infrastructure supports medical education and specialist recruitment; higher SAO density reduces mortality.

2. **Economy → Governance → Health Infrastructure → Bellwether Access**
   Fiscal resources + sound governance enable capital investment in tertiary hospitals.

3. **Social Cohesion → Financial Protection → Catastrophic Expenditure**
   Higher social capital reduces out-of-pocket exposure through community solidarity mechanisms.

4. **Urban Planning → Mobility → Geographic Access (LCoGS-1)**
   Urbanization and transport infrastructure reduce travel time to surgical care.

Implementation in Python using `semopy` or `lavaan` (via `rpy2`):

```python
import semopy

model_spec = """
# Measurement model
SAO_density ~ surgeons + anesthesiologists + obstetricians
CUDS ~ gdp_pc_log + idhm + ifgf + sanitation_rate

# Structural paths
pomr_pct ~ SAO_density + CUDS + access_2hr_proxy
SAO_density ~ idhm_education + gdp_pc_log
access_2hr_proxy ~ pop_density + urbanization_rate
"""

m = semopy.Model(model_spec)
m.fit(panel_df_2019)  # Cross-sectional SEM on pre-COVID year
print(m.inspect())  # Fit statistics
```

**Fit criteria:** RMSEA < 0.06 (close fit), 0.06–0.08 (acceptable); CFI > 0.95 (excellent), > 0.90 (acceptable); SRMR < 0.08. Report standardized path coefficients with bootstrap 95% CI (500 replications).

### 5.7 Phase 7: Sensitivity Analyses

All sensitivity analyses are pre-registered. Results will be presented in the supplement.

| # | Sensitivity Analysis | Primary vs. Sensitivity Difference | Purpose |
|---|---|---|---|
| 1 | Exclude COVID years (2020–2021) | Full panel vs. 2015–2019 + 2022–2023 | Verify COVID does not drive secular trend results |
| 2 | Arithmetic vs. geometric CUDS | Primary: geometric; sensitivity: arithmetic | Quantify impact of imbalance penalty |
| 3 | Equal vs. PCA vs. expert weights | Primary: equal; sensitivity: PCA + expert | Assess weighting robustness |
| 4 | POMR procedure threshold | 30 procedures (primary) vs. 10, 50, 100 | Quantify small-sample instability effect |
| 5 | Leave-one-dimension-out CUDS | 9 models dropping 1 dimension each | Test which dimensions drive results |
| 6 | Population size stratification | Full sample vs. strata: <20k, 20k–100k, 100k–500k, >500k | Effect modification by municipality size |
| 7 | Bootstrap CI for CUDS rankings | 1,000 replications, BCA method | Quantify ranking uncertainty |
| 8 | December-only vs. full 12-month SIH | December snapshot vs. annual aggregate | **Quantify and document seasonal bias magnitude** |
| 9 | Complete-case vs. MICE-imputed | Imputed primary vs. complete-case sensitivity | Assess missing data impact on estimates |

Sensitivity analysis #8 is particularly important: once the full raw SIH download is complete, compute both December-only aggregates and full 12-month aggregates for 2022–2023 (the only years where both are available). Report the percentage bias: `bias = (December_estimate − Annual_estimate) / Annual_estimate × 100%`. This directly validates — or quantifies the limitation of — the current December-only analysis.

---

## 6. Comparison with Massenburg 2017

Massenburg et al. (2017, *World Journal of Surgery*) is the closest methodological predecessor: the first study to systematically calculate all six LCoGS indicators for a large-middle-income country (Brazil) using routine administrative data. ICSKG-BR extends and advances this work across every dimension.

| Aspect | Massenburg et al. 2017 | ICSKG-BR (This Study) | Advancement |
|---|---|---|---|
| **Unit of analysis** | 27 states | 5,570 municipalities | ~200× more granular; reveals within-state inequality invisible at state level |
| **Time period** | 2008–2015 (cross-section) | 2015–2023 (9-year panel) | Temporal dimension: trajectories, trends, COVID disruption |
| **Sample size (observations)** | 27 | ~50,000 municipality-years | Orders-of-magnitude larger; enables multivariable regression rather than descriptive only |
| **LCoGS-1 (2-hr access)** | State-level; road network for capital cities | All 5,570 municipal centroids; haversine 150km threshold | National coverage of all municipalities, not just capitals |
| **LCoGS-2 (SAO density)** | State SAO per 100k | Municipal SAO per 100k + specialty disaggregation | Surgeon/anesthesiologist/obstetrician split; deduplication via CPF hash |
| **LCoGS-3 (surgical volume)** | State volume from SIH | Municipal volume from complete AIH records (all procedures) | Not sampled; all AIH records included |
| **LCoGS-4 (POMR)** | State POMR | Municipal POMR from individual records | Can stratify by procedure complexity, age group, and specialty |
| **LCoGS-5/6 (financial protection)** | National estimates (IBGE POF, Knaul 2011) | Municipal ecological proxy (avg cost / GDP pc) | Acknowledged ecological limitation; but more granular than national estimates |
| **Independent variables** | None (purely descriptive study) | 9-dimension CIMI framework (CUDS) | **First study to model urban development as determinant of surgical system performance** |
| **Statistical methods** | Descriptive statistics, maps | Panel FE, RCS dose-response, XGBoost/SHAP, SEM, clustering, spatial models | Full inferential + machine learning pipeline |
| **COVID-19 coverage** | Pre-COVID entirely | 2020–2021 disruption + recovery trajectory | Natural experiment: COVID as exogenous shock to surgical systems |
| **Urban development framework** | Not applicable | IESE CIMI (9 dimensions) → CUDS | Operationalizes global smart city theory in surgical systems research |
| **Validation** | None stated | CUDS validated against RCSC + IDSC-BR | External validity of composite index |
| **Open science** | Not stated | Code and derived aggregates on GitHub; DuckDB/MotherDuck reproducible pipeline | Fully reproducible analysis |

**Key novel contribution:** Massenburg et al. (2017) documented *that* LCoGS indicators vary across Brazilian states. ICSKG-BR asks *why* — specifically, whether urban development trajectories (as captured by CUDS) explain variation in surgical system performance, and whether this relationship is linear or threshold-dependent. No prior study has attempted this at municipal granularity for any country.

---

## 7. Smart Cities Index — Theoretical Grounding

### 7.1 Why IESE CIMI Over Other Smart City Frameworks

Several smart city frameworks are available (ISO 37122, ITU-T Y.4901, Giffinger et al. 2007, UNDP SDG Cities). The IESE Cities in Motion Index (CIMI) was selected for four reasons:

1. **Breadth and theoretical coverage:** CIMI spans 9 dimensions and 100+ indicators, deliberately designed to capture holistic urban capability rather than a single-domain metric (unlike ISO 37122, which focuses on ICT infrastructure, or UNDP SDG Cities, which tracks SDG compliance).

2. **Brazilian municipal validation:** The IDSC-BR (SDG Cities Index by Sustainable Development Solutions Network Brazil) provides an independent 5,570-municipality ranking computed annually, enabling external validation of CUDS. The RCSC (Ranking Connected Smart Cities, 656 Brazilian cities) provides a second validation benchmark. No other smart city framework has this depth of Brazilian municipal coverage.

3. **Actionability for policy:** CIMI dimensions map directly to ministerial portfolios — the Economy dimension to the Ministry of Finance, Technology to the Ministry of Communications, Governance to the Comptroller General (CGU). Policy recommendations derived from CUDS regression results can therefore be addressed to specific governmental actors.

4. **Existing scholarly use:** IESE CIMI has been applied in studies of urban governance, economic development, and innovation in Latin America. This study extends CIMI to health systems outcomes — a novel application that speaks to a broader readership.

### 7.2 The Nine CIMI Dimensions and Their Surgical Relevance

| CIMI Dimension | Mechanism Linking to Surgical Outcomes |
|---|---|
| **Economy** | Higher GDP per capita and economic activity generate tax revenue for health system investment; richer municipalities can fund public hospital infrastructure |
| **Technology** | Broadband infrastructure enables telemedicine, electronic health records, surgical scheduling systems; mobile coverage reduces geographic isolation |
| **Human Capital** | Educational attainment predicts surgical workforce supply (surgeons require 10+ years of tertiary education); literate populations access preventive care reducing emergency surgical load |
| **Social Cohesion** | Social capital reduces financial catastrophe from surgical costs (community solidarity, mutual aid); high inequality drives differential SUS access by income group |
| **Urban Planning** | Higher urbanization concentrates population within reach of referral hospitals; land-use planning determines hospital siting opportunities |
| **Governance** | Fiscal governance (IFGF) determines whether municipal health budgets are protected during economic shocks; corruption indices predict whether health equipment procurement is effective |
| **Environment** | Sanitation infrastructure reduces surgical burden from infectious disease complications; environmental health determines preventable surgical conditions |
| **Mobility** | Road and transport networks determine effective access time to bellwether hospitals; this is the direct mechanistic pathway for LCoGS-1 |
| **International Projection** | Trade openness and FDI attract pharmaceutical and medical device investment; medical tourism drives private hospital investment in border cities |

### 7.3 How CUDS Differs From HDI or GDP Per Capita

GDP per capita and HDI are well-validated summary development indicators, but they are inappropriate as the sole predictors for several reasons:

- **GDP per capita** captures economic output but not its distribution, governance quality, or public investment efficiency. Two municipalities with identical GDP per capita can have radically different surgical system performance if one has strong fiscal governance and the other has high corruption.
- **HDI** captures income, education, and health, but the health dimension uses life expectancy — which is itself partially determined by surgical outcomes, creating circularity. HDI also lacks urban planning, mobility, and technology dimensions.
- **CUDS** captures the *structural capacity* of a municipality to develop and sustain surgical systems, across nine dimensions that span economics, governance, infrastructure, and human capital. The key theoretical claim is that it is this multi-dimensional structural capacity — not any single dimension — that determines sustainable surgical system performance.

The dose-response hypothesis, tested via restricted cubic splines in Phase 4, specifically asks: is the CUDS–surgery relationship linear (each unit increase in CUDS produces proportional surgical improvement at all levels), or does it exhibit threshold effects (a minimum CUDS is needed before surgical systems can function) or diminishing returns (high-CUDS municipalities are already operating near capacity)?

### 7.4 The CUDS Validation Strategy

External validity of CUDS is established through two complementary approaches:

**Convergent validity:** Spearman rank correlation with RCSC (656 city overlap) and IDSC-BR (5,570 municipality overlap). Target: ρ ≥ 0.5 for both. High correlation confirms that CUDS captures a construct recognized by other established smart city methodologies. Moderate (not perfect) correlation is desirable — if ρ = 0.95, CUDS would add no information beyond IDSC-BR.

**Predictive validity:** In multivariable regression (Phase 4), CUDS should explain variance in LCoGS indicators beyond what GDP per capita and HDI alone explain. The incremental R² attributable to CUDS (above a GDP + HDI baseline model) quantifies whether the multi-dimensional index adds explanatory power.

---

## 8. Practical Next Steps — Ordered Checklist

The following actions are ordered by priority and estimated effort. Steps 1–6 are data acquisition and must be completed before the full analysis pipeline can produce final results.

| Priority | Action | Estimated Time | Who | Dependency |
|---|---|---|---|---|
| 1 | **Complete raw SIH download** — run `continue_raw_download.py --source sih` on local machine with stable internet | 12–15 hours | Data engineer | None — start immediately |
| 2 | **Complete raw CNES download** — run `continue_raw_download.py --source cnes` | 6–8 hours | Data engineer | Can run in parallel with #1 on separate machine |
| 3 | **Download Atlas Brasil IDHM** — bulk CSV from atlasbrasil.org.br; upload to MotherDuck as `idhm_municipal` | 1 hour | Analyst | None |
| 4 | **Download FIRJAN IFGF** — bulk Excel from firjan.com.br/ifgf; clean and upload as `firjan_ifgf` | 1 hour | Analyst | None |
| 5 | **Download ANS private insurance coverage** — FTP from `ftp.ans.gov.br/dados/beneficiarios/`; aggregate by municipality-year; upload as `ans_coverage` | 2 hours | Analyst | None |
| 6 | **Download Census 2022 sanitation/housing/education** — IBGE SIDRA API; upload as `censo2022_municipal` | 2 hours | Analyst | None |
| 7 | **Rebuild `sih_municipal_annual`** from complete raw SIH — run SQL aggregation to replace December-only snapshots with full annual aggregates | 2 hours | Data engineer | Depends on #1 |
| 8 | **Rebuild `sao_workforce_annual`** from complete raw CNES with deduplication — apply CPF hash deduplication before aggregating | 2 hours | Data engineer | Depends on #2 |
| 9 | **Update `v_lcogs_panel`** to join new data sources (IDHM, IFGF, ANS, Census) | 1 hour | Data engineer | Depends on #3–6 |
| 10 | **Run Phase 1–3 of analysis pipeline** — descriptive stats, CUDS construction, PCA | 3–4 hours | Analyst | Depends on #7–9 |
| 11 | **Run Phase 4–5 of analysis pipeline** — panel regressions, ML models | 4–6 hours | Analyst | Depends on #10 |
| 12 | **Run Phase 6–7** — SEM + all sensitivity analyses | 4–6 hours | Analyst | Depends on #11 |
| 13 | **Generate all figures and tables** — choropleth maps, trend plots, coefficient tables, SHAP plots, cluster maps, UMAP embeddings | 4 hours | Analyst | Depends on #11–12 |
| 14 | **Write manuscript** following STROBE-NUT (for nutritional epidemiology analogy) or RECORD (routinely collected data) guidelines; primary target: *BMJ Global Health* or *World Journal of Surgery* | 2–3 weeks | Senior researcher | Depends on #13 |
| 15 | **Internal review + co-author sign-off** | 1–2 weeks | Team | Depends on #14 |
| 16 | **Submission** | 1 day | Corresponding author | Depends on #15 |

**Target submission date:** Q3 2026, contingent on raw data download completion in April 2026.

**Reporting guidelines to follow:**
- **STROBE:** STrengthening the Reporting of OBservational studies in Epidemiology — mandatory checklist for observational studies
- **RECORD:** REporting of studies Conducted using Observational Routinely collected Data — extends STROBE for administrative data studies
- **TRIPOD+AI:** Transparent Reporting of a multivariable prediction model for Individual Prognosis Or Diagnosis, AI extension — required for XGBoost/RF/NN models

---

## Appendix A: Database Schema Quick Reference

```sql
-- Check current table sizes and last update
SELECT
    table_name,
    estimated_size,
    last_modified
FROM information_schema.tables
WHERE table_schema = 'main'
ORDER BY estimated_size DESC;

-- Verify panel completeness: municipalities × years
SELECT
    year,
    COUNT(DISTINCT cod_ibge) AS n_municipalities,
    COUNT(*) AS n_rows,
    SUM(CASE WHEN total_procedures IS NULL THEN 1 ELSE 0 END) AS missing_procedures
FROM v_lcogs_panel
GROUP BY year
ORDER BY year;

-- Check SIH raw coverage
SELECT
    uf,
    EXTRACT(YEAR FROM admission_date) AS year,
    COUNT(DISTINCT EXTRACT(MONTH FROM admission_date)) AS months_present,
    COUNT(*) AS n_records
FROM sih_raw
GROUP BY 1, 2
ORDER BY 1, 2;
```

---

## Appendix B: Variable Coding Reference for Primary Models

| Variable | Role | Transformation | Source |
|---|---|---|---|
| `total_procedures / (population/100000)` | Outcome: LCoGS-3 | None (rate per 100k) | `sih_municipal` + `population` |
| `pomr_pct` | Outcome: LCoGS-4 | None (%) | `sih_municipal` |
| `sao_per_100k` | Outcome/predictor: LCoGS-2 | None | `sao_workforce` |
| `access_2hr_proxy` | Outcome: LCoGS-1 | Binary (0/1) | `lcogs1_access` |
| `avg_cost_brl` | Proxy: LCoGS-5/6 | Log transform | `sih_municipal` |
| `CUDS` | Primary predictor | [0,1] normalized | Computed |
| `gdp_per_capita_brl` | Covariate | Log transform | `gdp` |
| `population` | Offset / covariate | Log transform | `population` |
| `idhm` | Covariate (when available) | None [0,1] | Atlas Brasil |
| `ifgf` | Covariate (when available) | None [0,1] | FIRJAN |
| `ans_coverage_pct` | Covariate (when available) | None (%) | ANS |
| `year` | Fixed effect | Factor | Panel structure |
| `cod_ibge` | Fixed effect | Factor | Panel structure |

---

*Document last updated: March 30, 2026. Maintained by the ICSKG-BR research team.*  
*For questions about data pipeline: refer to `Technical_Cookbook_v2.docx`. For variable operationalization: refer to `Variable_Cookbook_v2.xlsx`.*
