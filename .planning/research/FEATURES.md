# Feature Landscape

**Domain:** Ecological panel study data pipeline — composite urban development index validated against surgical system indicators at subnational (municipal) level. Target: BMJ Global Health.
**Researched:** 2026-04-01
**Confidence:** MEDIUM-HIGH (STROBE/RECORD requirements from official sources; BMJ-specific details inferred from search results + editorial policy patterns; ML/spatial features from peer-reviewed literature)

---

## Table Stakes

Features whose absence causes reviewer rejection, desk rejection, or fatal methodological criticism. These are non-negotiable for BMJ Global Health submission.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Complete panel dataset (5,570 × 9 years = 50,130 obs) | Defines the study. Incomplete panel = underpowered or misleading claims. | High | Requires all 9 CIMI dimensions populated for each municipality-year; acceptable to document structured missingness (e.g., Census 2022 fills one time point only) |
| STROBE checklist compliance (22 items) | Mandatory for observational studies at BMJ Global Health and virtually every peer-reviewed epidemiology journal. | Low | Checklist is documentation work, not code — but it drives what must be computed and reported (effect measures, confidence intervals, absolute numbers) |
| RECORD extension compliance (13 items) | RECORD extends STROBE specifically for routinely-collected health databases — exactly this study's design. Required items: named databases, code/algorithm validation references, data access statement, linkage flow diagram. | Low-Med | Items 6.1–6.4 on database description and 7.1–7.4 on data access are the ones most commonly missing in published studies (51% non-compliance on linkage, 49.5% on code validation per 2025 meta-epidemiologic audit) |
| CUDS computation: geometric mean of min-max normalized dimensions | Pre-registered methodological choice. Must be implemented exactly as described in Methods or reviewers will flag inconsistency. | Med | Geometric mean correctly penalizes imbalance; arithmetic mean does not — this is the stated rationale and must be demonstrable in sensitivity analysis |
| All 6 LCoGS indicators at municipal level | Study's core validity claim. Missing any indicator undermines the "first subnational cross-reference" framing. | High | LCoGS-5 and LCoGS-6 (financial protection proxies) are the hardest — ecological proxy via SIH costs / GDP is acceptable and documented |
| Primary regression model: CUDS → LCoGS outcomes | The central hypothesis test. Without this, the study has no analytical core. | Med | Fixed-effects panel regression is the standard for municipality-year data; must report cluster-robust standard errors (municipality clusters) |
| Hausman test (FE vs RE selection) | Reviewers of panel studies expect evidence that fixed vs. random effects choice was tested, not assumed. | Low | Run once; report in supplement |
| Missing data documentation and handling | RECORD item 12.1. Reviewers expect explicit reporting of missingness patterns, not silent omission. | Med | Environment dimension (Census 2022 sanitation) is cross-sectional — must be documented as a structural constraint, not an error; Technology dimension (internet access) may have high missingness pre-2018 |
| Deflation of monetary variables to constant BRL | Any nominal BRL time-series (health expenditure SIOPS, GDP) spanning 2015–2023 must be deflated. Using nominal values across 9 years is a methodological error reviewers will catch. | Med | Use IPCA health sub-index for health expenditure; IPCA general for GDP; base year 2023 BRL |
| Data availability statement | Mandatory BMJ Open Access policy item. All data must be either publicly accessible (with URLs) or the statement must explain why not. | Low | All sources here are Lei de Acesso à Informação (Law 12.527/2011) public data — this is straightforward to comply with |
| Ethics statement | Required. Aggregate public administrative data at municipal level is exempt from IRB review under Brazilian Resolution 510/2016 (no individual-level data). Must state this explicitly. | Low | One sentence in Methods; must name the resolution |
| STROBE flow diagram (municipality inclusion/exclusion) | Shows how 5,570 municipalities were defined, any exclusions (e.g., municipalities created after 2015 through splits), and observation-level completeness. | Low-Med | IBGE created/split municipalities during 2015–2023; must document how these are handled (merge back to 2015 boundaries or exclude) |
| Cluster-robust standard errors (municipality-level clustering) | Standard requirement for panel models with repeated observations per unit. Heteroskedasticity and serial correlation within municipalities are expected. | Low | Implemented via statsmodels or linearmodels in Python; not optional |
| Publication-ready figures (minimum 4) | BMJ Global Health expects figures to stand alone. 4 is the stated minimum in PROJECT.md. Standard content: (1) CUDS distribution map, (2) CUDS trend over time, (3) LCoGS heatmap by region, (4) main regression result plot | Med | Must be 300 DPI minimum, colorblind-safe palette, labeled in English |
| Publication-ready tables (minimum 8) | Expected content: (1) descriptive statistics, (2) dimension-level descriptives, (3) missing data summary, (4) correlation matrix CUDS/LCoGS, (5–8) regression results by LCoGS outcome | Med | Tables exported as CSV; formatted in supplementary word processing step |
| Idempotent pipeline with deterministic outputs | Reviewers increasingly ask to re-run analyses. A pipeline that produces different results on re-run fails reproducibility standards. | Med | All random seeds fixed; no non-deterministic operations in production path |
| Documented data dictionary | RECORD item 8.1. Each variable: name, source, definition, unit, temporal coverage, missingness rate. | Low-Med | Can be the database_metadata.json expanded; or a separate CSV |

---

## Differentiators

Features that strengthen the submission beyond minimum requirements. Not expected by reviewers, but meaningfully increase acceptance probability and citation potential.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Sensitivity analysis: arithmetic mean vs geometric mean CUDS | Directly addresses the most likely reviewer challenge ("why geometric mean?"). Showing results are robust — or quantifying how much they diverge — strengthens the methodological section. | Low | Run both; report correlation between the two CUDS variants; show primary results replicate |
| Sensitivity analysis: excluding municipalities with >X% missing dimensions | Demonstrates findings are not driven by imputed or structurally incomplete observations. | Low | Drop municipalities missing ≥2 dimensions; re-run primary models; tabulate in supplement |
| Spatial autocorrelation assessment: Moran's I on residuals | Ecological studies at municipal level are susceptible to spatial confounding. Testing residuals from primary models for spatial autocorrelation is a differentiating analytical step — common in published Brazilian health geography papers but rarely done in global surgery studies. | Med | Use PySAL/libpysal; Global Moran's I on FE model residuals; if significant, note as limitation or add spatial lag term |
| SHAP values for ML models (Random Forest, XGBoost) | Provides dimension-level feature importance with uncertainty quantification. Directly answers "which CIMI dimensions matter most for surgical access?" — a policy-relevant finding with high citation value. | Med | Use shap library; beeswarm plot per LCoGS outcome; include in paper or supplement |
| Cross-validation of ML models (5-fold, municipality-stratified) | Prevents overfitting claims. Without cross-validation, ML results in health research are routinely discounted. | Low-Med | Stratify folds by macro-region (N/NE/CO/SE/S) to prevent geographic leakage |
| North–South gradient analysis with quantile decomposition | Regional disparity is the most policy-relevant story in Brazilian health data. Quantifying how much of the CUDS–LCoGS association operates through regional effects gives the paper a second narrative arc. | Med | Blinder-Oaxaca decomposition or quantile regression by region; show that the association holds within regions, not just across them |
| Haversine distance to nearest bellwether hospital as continuous predictor | Converts LCoGS-1 (binary: met/unmet) into a continuous geographic access measure. Richer than the binary indicator and directly captures the "2-hour travel" proxy at municipal centroid. | Med | Already partially implemented (765 geocoded facilities from PROJECT.md); extend to all municipality centroids |
| Annualized SIH data (full 12-month) rather than December snapshots | December snapshots introduce seasonal bias for surgical procedures (e.g., elective surgeries cluster mid-year). Full annualization is methodologically superior and reviewers familiar with DATASUS will notice December-only data. | High | In progress on NAS per PROJECT.md; this is a data quality differentiator, not a feature to defer |
| STROBE-Equity extension items | BMJ Global Health has strong equity focus. Reporting health equity dimensions explicitly (STROBE-Equity 2024 extension, JAMA Network Open) signals alignment with the journal's editorial priorities. | Low | Primarily documentation: add equity framing in Methods/Discussion; document inequality measures (Gini-based or quintile comparisons) |
| Code repository with DOI (Zenodo + GitHub) | Increasingly required by high-impact journals; BMJ Open Access policy strongly encourages it. Assigning a Zenodo DOI to the analysis code at submission makes the data availability statement concrete and verifiable. | Low | Create public GitHub repo; archive release to Zenodo at submission; cite DOI in paper |
| Municipality boundary harmonization across census periods | IBGE created new municipalities by splitting existing ones during 2015–2023. Without harmonization, time series comparisons are invalid for affected units. Documenting and handling this is methodologically rigorous and shows familiarity with the data. | Med | ~30–50 municipalities affected; merge splits back to 2015 boundaries or exclude with documentation |
| Dose-response visualization: CUDS quintiles × LCoGS outcomes | Visual evidence of dose-response relationship (bar chart or line plot of LCoGS mean by CUDS quintile, by year) makes the central finding immediately legible to non-statistician reviewers and policy readers. | Low | Plot CUDS quintile (1–5) on x-axis, LCoGS indicator on y-axis; panel by year or aggregate |
| Comparative benchmarking against LCoGS 2030 targets | Contextualize Brazilian municipal findings against the WHO/LCoGS global targets (e.g., 5,000 procedures/100k; 20 SAO per 100k). Shows how far each quintile of CUDS is from target. | Low | Add horizontal reference lines to figures; compute % of municipalities meeting each target by CUDS quintile |

---

## Anti-Features

Features to deliberately NOT build. Building these would waste time, dilute focus, or compromise the study's integrity.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Real-time or interactive web dashboard | PROJECT.md explicitly out of scope. Adds no publication value and significant maintenance burden. Reviewers do not expect it. | Static figures at 300 DPI. If funders later request interactivity, that is a separate deliverable. |
| Individual-level patient analysis | SIH data contains municipality of treatment, not patient identifiers at this level of aggregation. Attempting individual-level inference from municipal aggregates is an ecological fallacy. | Explicitly state the ecological design limitation in Discussion. |
| Causal claims (DAGs, instrumental variables, difference-in-differences) | The ecological design cannot support causal inference. Framing associations as causal would cause immediate desk rejection or post-publication criticism. | Use language of "association," "dose-response relationship," "predictive," not "effect of" or "causes." |
| International CIMI dimension (Dimension 8) | Irrelevant at municipal level for 99% of Brazilian municipalities. No valid proxy exists. Including a zero-imputed or NA dimension in the geometric mean distorts CUDS. | Document exclusion as a named limitation with rationale in Methods. |
| Multilevel models (municipality nested in state nested in region) | Adds substantial complexity for marginal gain in a study already implementing municipality fixed effects. Reviewers of global health papers are unlikely to penalize the absence. | Fixed-effects panel regression handles within-municipality confounding. Note multilevel modeling as future work. |
| Propensity score matching or weighting | CUDS is a continuous predictor, not a binary treatment. PSM is not applicable. Attempting it would suggest methodological confusion. | Use continuous regression with fixed effects and robust standard errors. |
| Imputation of the Technology dimension (D9) via ML | Internet access data has structural missingness pre-2018 due to survey design changes. ML imputation of an entire dimension creates unquantifiable uncertainty that propagates into CUDS. | Use available PNAD/Census proxy; document structural gaps; run sensitivity analysis excluding D9 entirely. |
| Per-municipality HTML/PDF report generation | 5,570 municipality-level reports would be an engineering project, not a research pipeline. No publication venue expects this. | Aggregate regional/state summaries are sufficient for publication. Regional breakdown figures cover the analytical need. |
| Real-time DATASUS API polling | DATASUS APIs are unreliable, change structure without notice, and the study covers a fixed historical window (2015–2023). | Snapshot downloads with resume capability (already implemented). Freeze data at submission. |
| Probabilistic imputation (multiple imputation by chained equations) for cross-sectional dimensions | Census 2022 sanitation data is a single time-point by design, not missing-at-random. MICE would manufacture longitudinal variation that does not exist. | Use the single available value as a time-invariant covariate with explicit documentation. |

---

## Feature Dependencies

```
Full panel dataset
  └── All 9 CIMI dimension extraction scripts
        ├── D1 Governance      → FIRJAN IFGF Excel parser
        ├── D2 Economy         → IBGE SIDRA API (table 5938)
        ├── D3 Human Capital   → IPEA IDHM integration
        ├── D4 Social Cohesion → ANS beneficiary coverage rate
        ├── D5 Environment     → IBGE Census 2022 sanitation
        ├── D6 Mobility        → RENAVAM vehicle fleet
        ├── D7 Urban Planning  → CNES beds per 10,000
        ├── D8 (excluded)      → documented omission
        └── D9 Technology      → IBGE/PNAD internet proxy

CUDS computation (geometric mean)
  └── Full panel dataset
        └── Min-max normalization (within-year)
              └── Municipality boundary harmonization

LCoGS indicator suite
  ├── LCoGS-1 (bellwether access) → CNES geocoded + Haversine distance
  ├── LCoGS-2 (SAO density)       → CNES professionals + CBO filter + SIH annualized
  ├── LCoGS-3 (surgical volume)   → SIH annualized (full 12-month)
  ├── LCoGS-4 (POMR)              → SIH annualized (full 12-month)
  ├── LCoGS-5 (financial risk)    → SIH costs + IBGE GDP (deflated)
  └── LCoGS-6 (catastrophic exp.) → SIH costs + IBGE GDP (deflated)

Primary regression models
  └── CUDS computation
  └── LCoGS indicator suite
  └── Cluster-robust standard errors (statsmodels/linearmodels)
  └── Hausman test (FE vs RE)

Sensitivity analyses
  └── Primary regression models (must exist first)

SHAP / ML dose-response
  └── Full panel dataset
  └── LCoGS indicator suite

Spatial autocorrelation (Moran's I)
  └── Primary regression model residuals
  └── Municipality shapefile (IBGE)

Publication figures and tables
  └── All of the above
  └── Deflated monetary series

STROBE / RECORD checklists
  └── All of the above (documentation step, not code)
  └── Data dictionary
  └── Missing data summary table

Zenodo DOI + code release
  └── Idempotent pipeline (must be deterministic first)
  └── All scripts finalized
```

---

## MVP Recommendation

For a complete, submittable paper, prioritize in this order:

**Phase 1 — Data completeness (blocker for everything else)**
1. Full 12-month annualized SIH data (replaces December snapshots)
2. All 8 active CIMI dimension extraction scripts (D1–D7 + D9, with D8 excluded)
3. LCoGS-2 through LCoGS-6 indicator computation

**Phase 2 — Core analysis**
4. CUDS geometric mean with within-year min-max normalization
5. Primary fixed-effects panel regression (CUDS → each LCoGS outcome), cluster-robust SE
6. Hausman test and fixed-effects justification

**Phase 3 — Publication outputs**
7. 4 figures + 8 tables (paper-ready quality)
8. Missing data documentation table
9. STROBE + RECORD compliance checklists

**Phase 4 — Differentiators (after core complete)**
10. Sensitivity analyses (arithmetic vs geometric mean; >X% missing exclusion)
11. SHAP values for ML models
12. Spatial autocorrelation (Moran's I on residuals)
13. Zenodo DOI + GitHub release

**Defer indefinitely:**
- Municipality-level HTML/PDF reports
- Interactive dashboard
- Multilevel models
- MICE imputation for cross-sectional dimensions

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| STROBE/RECORD requirements | HIGH | Official EQUATOR Network documentation; 2025 meta-epidemiologic adherence study confirms which items are most commonly missing |
| BMJ Global Health specific requirements | MEDIUM | Direct fetch blocked; inferred from journal editorial policies, open access data availability standards, and STROBE-Equity 2024 extension patterns |
| Panel regression requirements (Hausman, cluster-robust SE) | HIGH | Standard econometric practice; multiple authoritative textbook and paper sources |
| Spatial features (Moran's I, LISA) | MEDIUM | Brazilian municipal health geography literature confirms these are standard; whether BMJ Global Health reviewers specifically require them is MEDIUM confidence |
| ML features (SHAP, cross-validation) | MEDIUM | Published precedents in public health ML 2024; differentiator status, not table stakes |
| LCoGS indicator definitions | HIGH | Utstein Consensus Report (PMC8415575) provides standardized definitions; 2025 systematic review of LCoGS indicators confirms reporting gaps at subnational level |

---

## Sources

- STROBE Statement official checklist: [https://www.strobe-statement.org/checklists/](https://www.strobe-statement.org/checklists/)
- RECORD Statement (PMC): [https://pmc.ncbi.nlm.nih.gov/articles/PMC4595218/](https://pmc.ncbi.nlm.nih.gov/articles/PMC4595218/)
- RECORD adherence meta-epidemiologic study 2025: [https://www.sciencedirect.com/science/article/pii/S0895435625002094](https://www.sciencedirect.com/science/article/pii/S0895435625002094)
- STROBE-Equity extension (JAMA Network Open): [https://jamanetwork.com/journals/jamanetworkopen/fullarticle/2838494](https://jamanetwork.com/journals/jamanetworkopen/fullarticle/2838494)
- LCoGS Utstein Consensus Report: [https://pmc.ncbi.nlm.nih.gov/articles/PMC8415575/](https://pmc.ncbi.nlm.nih.gov/articles/PMC8415575/)
- Systematic review of LCoGS indicators 2025 (BJS): [https://academic.oup.com/bjs/article/113/3/znaf289/8505882](https://academic.oup.com/bjs/article/113/3/znaf289/8505882)
- Fixed-effects panel regression with cluster-robust SE: [https://www.econometrics-with-r.org/10.5-tferaaseffer.html](https://www.econometrics-with-r.org/10.5-tferaaseffer.html)
- Spatial analysis of Brazilian municipalities health outcomes: [https://pmc.ncbi.nlm.nih.gov/articles/PMC9242540/](https://pmc.ncbi.nlm.nih.gov/articles/PMC9242540/)
- DATASUS / Brazilian longitudinal health data pipeline: [https://pubmed.ncbi.nlm.nih.gov/40243716/](https://pubmed.ncbi.nlm.nih.gov/40243716/)
- Reproducible research with Zenodo+GitHub: [https://zenodo.org/records/5508797](https://zenodo.org/records/5508797)
- Composite index methods in public health (scoping review): [https://pmc.ncbi.nlm.nih.gov/articles/PMC11569672/](https://pmc.ncbi.nlm.nih.gov/articles/PMC11569672/)
- TRATAMENTOS framework for missing data in observational studies: [https://www.sciencedirect.com/science/article/pii/S089543562100010X](https://www.sciencedirect.com/science/article/pii/S089543562100010X)
