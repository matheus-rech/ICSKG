# ICSKG-BR Methodology and Gap Analysis

## 1. Overview

The **ICSKG-BR** (Índice Composto de Saúde e Conhecimento Geral – Brazil) project
constructs a longitudinal composite index of health-system capacity and knowledge
gaps across all 5 570 Brazilian municipalities for the period 2013–2024.

The index integrates nine CIMI (Composite Index of Municipal Infrastructure for Health)
dimensions and situates municipal performance against international benchmarks,
including the LCoGS-1 (Lancet Commission on Global Surgery) bellwether procedure
threshold and WHO primary-care coverage targets.

---

## 2. Conceptual Framework

The ICSKG-BR framework is grounded in three theoretical pillars:

| Pillar | Description | Key References |
|--------|-------------|----------------|
| **Health-system capacity** | Infrastructure, human resources, and financing needed to deliver care | WHO Health Systems Framework (2000); Donabedian structure–process–outcome model |
| **Equity and access** | Spatial, financial, and social barriers to care | Penchansky & Thomas (1981); Levesque et al. (2013) |
| **Knowledge-to-practice gap** | Distance between evidence-based standards and observed practice | IHME GBD; LCoGS (2015, 2020); Kruk et al. (2018) |

---

## 3. CIMI Dimensions

### 3.1 D1 – Fiscal Governance (IFGF)

**Source:** FIRJAN Índice de Gestão Fiscal (IFGF), 2013–2024  
**Rationale:** Fiscal management quality determines a municipality's ability to fund
and sustain health services.  
**Construction:** Composite of four IFGF sub-indices (receita própria, gastos com pessoal,
investimentos, liquidez), normalised to [0, 1] via min-max scaling.

### 3.2 D2 – Per-capita Health Expenditure

**Source:** SIOPS (Sistema de Informações sobre Orçamentos Públicos em Saúde)  
**Rationale:** Real per-capita health spending is a direct proxy for resource allocation.  
**Construction:** Municipal health expenditure divided by IBGE population estimate,
deflated to 2023 BRL using the IPCA health sub-index.

### 3.3 D3 – Hospital Capacity (Beds per 10 000)

**Source:** CNES/DATASUS (monthly snapshots)  
**Rationale:** Inpatient bed availability constrains surgical and medical care access.  
**Construction:** SUS + non-SUS inpatient beds (leitos internação) per 10 000 inhabitants.
Psychiatric, day-care, and long-stay beds are excluded.

### 3.4 D4 – Human Resources (Physicians + Nurses per 10 000)

**Source:** CNES/DATASUS – professional registration tables  
**Rationale:** Workforce density is a core determinant of effective coverage.  
**Construction:** Active CRM (physicians) + COREN (nurses) registrations per 10 000 inhabitants.

### 3.5 D5 – Primary-Care Coverage

**Source:** PMAQ cycles 1–3; Previne Brasil (2020–2024)  
**Rationale:** Strong primary care is the foundation of an equitable health system.  
**Construction:** Composite of (a) Family Health Strategy (ESF) population coverage rate
and (b) PMAQ/Previne quality score, averaged with equal weight.

### 3.6 D6 – Private Health Coverage (ANS Share)

**Source:** ANS quarterly beneficiary counts; IBGE population estimates  
**Rationale:** Private coverage share reflects dual-system utilisation and public-system
demand pressure.  
**Construction:** Active ANS beneficiaries / municipal population.

### 3.7 D7 – Maternal and Child Health Composite

**Source:** SIM (mortality), SINASC (live births), SIAB/e-SUS  
**Rationale:** Maternal and infant outcomes are sensitive tracers of overall health-system
performance.  
**Construction:** Inverse-normalised IMR (infant mortality rate) + prenatal care coverage
(≥7 consultations), averaged with equal weight.

### 3.8 D8 – Chronic Disease Burden (ICSAP Rate)

**Source:** SIH/DATASUS – inpatient microdata; Brazilian ICSAP condition list  
**Rationale:** Hospitalisations for ambulatory-care-sensitive conditions (ICSAP) signal
primary-care failures.  
**Construction:** ICSAP hospitalisations per 10 000 inhabitants, inverted so that
higher scores represent better performance.

### 3.9 D9 – Health Knowledge Gap (ICSKG Score)

**Source:** Multi-source composite  
**Rationale:** The ICSKG dimension captures the gap between achievable best practice
and observed practice across all eight preceding dimensions.  
**Construction:** Mean standardised residual between a frontier model (estimated via
stochastic frontier analysis) and observed performance.

---

## 4. Composite ICSKG Score

The overall ICSKG-BR composite score is the unweighted arithmetic mean of the nine
CIMI dimension scores, each normalised to [0, 1]:

$$
\text{ICSKG}_i = \frac{1}{9} \sum_{d=1}^{9} D_{d,i}
$$

where $D_{d,i}$ is the min-max normalised score for municipality $i$ on dimension $d$.

### 4.1 Sensitivity Analyses

Three robustness checks are conducted:

1. **Equal vs. domain-expert weights** – weights elicited via Delphi process compared
   with equal weights.
2. **Normalisation method** – min-max vs. z-score vs. rank-based normalisation.
3. **Missing-data strategy** – complete-case analysis vs. multiple imputation (MICE).

---

## 5. Gap Analysis

### 5.1 LCoGS-1 Bellwether Threshold

The LCoGS Commission recommends ≥ 5 000 bellwether procedures
(laparotomy, caesarean section, open fracture repair) per 100 000 population per year
as a minimum surgical system capacity threshold.

Using SIH microdata (2013–2023) we compute municipal-level bellwether procedure rates
and classify municipalities as:

* **Meeting LCoGS-1** (≥ 5 000 / 100 000 / year)
* **Moderate gap** (2 500–4 999)
* **Severe gap** (< 2 500)

### 5.2 ICSKG Knowledge-Gap Domains

| Domain | Indicator | Benchmark | Source |
|--------|-----------|-----------|--------|
| Surgical access | Bellwether rate | LCoGS-1 ≥ 5 000/100k | SIH/DATASUS |
| Primary care | ESF coverage | ≥ 70 % population | PMAQ/Previne |
| Reproductive health | Prenatal ≥ 7 visits | ≥ 80 % live births | SINASC |
| Chronic disease | ICSAP rate | ≤ 200/10 000 | SIH/DATASUS |
| Fiscal sustainability | IFGF composite | ≥ 0.6 (scale 0–1) | FIRJAN |

---

## 6. Data Governance and Reproducibility

All input data are drawn from open, publicly available Brazilian government databases.
No individual-level identifiers are retained in the analysis dataset.

### 6.1 Data Access

| Source | Access URL | Licence |
|--------|-----------|---------|
| SIH/DATASUS | https://datasus.saude.gov.br/ | Open Government Data (Brazil) |
| CNES/DATASUS | https://datasus.saude.gov.br/ | Open Government Data (Brazil) |
| ANS | https://dados.ans.gov.br/ | Open Government Data (Brazil) |
| IFGF/FIRJAN | https://www.firjan.com.br/ifgf/ | Freely available for research |
| SIOPS | https://siops.datasus.gov.br/ | Open Government Data (Brazil) |
| IBGE | https://ibge.gov.br/ | Open Government Data (Brazil) |

### 6.2 Reproducibility

The full analysis pipeline can be reproduced by:

```bash
# 1. Download raw data (12-month window ending Dec 2023)
python scripts/continue_raw_download.py --source BOTH --end-year 2023 --end-month 12 --months 12
python scripts/download_ans.py --start 2013-01 --end 2023-12

# 2. Build database
python database/pipeline.py --start 2013-01 --end 2023-12
python database/build_database_v2.py

# 3. Run analysis
python analysis/icskg_analysis_pipeline.py

# 4. LCoGS-1 maps
python extract_lcogs1.py --year 2023
```

All outputs are deterministic given the same input data. Random seeds are fixed
where applicable (see individual scripts).

---

## 7. Limitations and Known Gaps

1. **SIH under-reporting**: Private-sector hospitalisations paid out-of-pocket are
   not captured in SIH, potentially underestimating bellwether rates in high-income
   municipalities.

2. **CNES data quality**: Provider registrations are self-reported and may lag
   actual workforce availability by 1–6 months.

3. **Ecological inference**: All analyses are at the municipal level; individual-level
   conclusions should not be drawn.

4. **Missing IFGF data**: ~420 municipalities (7.5 %) are absent from IFGF in at
   least one year, primarily small municipalities with simplified fiscal accounts.

5. **LCoGS-1 sensitivity**: The bellwether approach does not capture quality of
   surgical care, only volume.

---

## 8. References

- Alkire BC, et al. (2015). Lancet Commission on Global Surgery. *The Lancet*, 386(9993), 569–624.
- Donabedian A. (1966). Evaluating the quality of medical care. *Milbank Quarterly*, 44(3), 166–206.
- FIRJAN. (2024). Índice FIRJAN de Gestão Fiscal – Metodologia. Rio de Janeiro: FIRJAN.
- Instituto Brasileiro de Geografia e Estatística (IBGE). (2024). *Estimativas de População*. Rio de Janeiro: IBGE.
- Kruk ME, et al. (2018). High-quality health systems in the Sustainable Development Goals era. *The Lancet*, 392(10160), 2163–2186.
- Levesque JF, Harris MF, Russell G. (2013). Patient-centred access to health care. *International Journal for Equity in Health*, 12, 18.
- Ministério da Saúde (2024). *DATASUS – Informações de Saúde*. Brasília: MS.
- Penchansky R, Thomas JW. (1981). The concept of access. *Medical Care*, 19(2), 127–140.
- Pereira RHM, et al. (2019). geobr: Loads Shapefiles of Official Spatial Data Sets of Brazil. *CRAN*.
- WHO. (2000). *The World Health Report 2000: Health Systems: Improving Performance*. Geneva: WHO.
