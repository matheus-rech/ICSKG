# Domain Pitfalls: ICSKG-BR

**Domain:** Brazilian municipal public health panel study — DATASUS/SIH/CNES data pipeline + composite index computation
**Researched:** 2026-04-01
**Confidence:** HIGH (grounded in peer-reviewed literature, official DATASUS documentation, and direct codebase inspection)

---

## Critical Pitfalls

Mistakes that cause analytical invalidation, journal rejection, or full rewrites.

---

### Pitfall 1: SIH Captures Only 60–70% of Hospitalizations (Private Sector Blindspot)

**What goes wrong:** SIH-SUS records only SUS-funded hospitalizations. The 28–40% of Brazilians covered by private health insurance (ANS beneficiaries) receive care in private hospitals that report to ANS—not to SIH. For high-income municipalities in São Paulo, Rio de Janeiro, and the South region, where private coverage reaches 37–50% of the population, SIH data systematically undercounts total surgical volume. A municipality with a large private hospital will appear to have low surgical activity if only SIH is queried.

**Why it happens:** SIH was designed as a SUS billing system, not a population-level surgical registry. Private insurers report to ANS under a separate regulatory framework with no linkage to SIH.

**Consequences:** LCoGS-3 (surgical volume per 100,000) will be severely underestimated in wealthier, more urbanized municipalities—precisely the municipalities with high CUDS scores. This creates an artifactual negative correlation between CUDS and surgical volume unless the SIH limitation is explicitly modeled. It also inverts the expected CUDS–LCoGS relationship for LCoGS-4 (POMR): private hospitals have lower POMR; excluding them biases POMR upward in high-CUDS municipalities.

**Prevention:**
- State explicitly in Methods that LCoGS-3 and LCoGS-4 reflect SUS-funded procedures only.
- Add ANS private procedure data (SIP — Sistema de Informações de Produtos) as a supplementary LCoGS estimate where available.
- In sensitivity analyses, restrict comparisons to municipalities with ANS coverage below 10% (near-complete SUS dependence) to validate directional findings.
- In the Discussion, frame this as a structural limitation requiring future data linkage (RNDS).

**Detection:** Plot SIH surgical volume per 100,000 against ANS coverage rate. A strong negative correlation indicates the under-reporting effect is dominating.

**Phase:** ETL pipeline (LCoGS computation stage) and manuscript Methods/Limitations.

---

### Pitfall 2: Geometric Mean Collapses to Zero When Any Dimension is Missing or Zero

**What goes wrong:** The CUDS is defined as the geometric mean of 9 min-max normalized dimension scores. If any single dimension normalizes to exactly 0.0 (which happens when a municipality has the minimum observed value for that dimension), or if a dimension is missing (NaN treated as 0), the entire CUDS becomes 0 for that municipality. With 5,570 municipalities and min-max normalization, at least one municipality will always score exactly 0 on each dimension—those municipalities receive CUDS = 0 regardless of their scores on other dimensions.

**Why it happens:** Geometric mean is undefined for zero and is the mathematical product of all components raised to 1/N. The min-max formula `(x - min) / (max - min)` guarantees that the lowest-scoring municipality on each dimension always gets exactly 0.

**Consequences:** The worst municipality on any single indicator—regardless of how well it performs on all other 8 dimensions—gets CUDS = 0. This conflates "worst on one dimension" with "worst overall." It also means municipalities with missing data for one dimension (e.g., IFGF not available for ~420 municipalities) will cluster at CUDS = 0 if NaN is silently treated as 0.

**Prevention:**
- Apply a floor offset before geometric mean: add a small constant (0.01 or 0.001) to all normalized scores so the range becomes [0.01, 1.01]. Document this transformation.
- Alternative (preferred by HDI methodology): use `x + 1` or `goalposts` normalization anchored to global/Brazil-wide minimums rather than sample minimums—this prevents the floor problem for future years.
- Never impute NaN as 0 before computing geometric mean. Municipalities with missing dimensions must be excluded from CUDS computation and documented explicitly.
- Run a zero-score audit: after normalization, count municipalities with any dimension = 0 and inspect whether those zeros are real vs. normalization artifacts.

**Detection:** After min-max normalization, check `(panel[dim_cols] == 0).sum()` per dimension. Any count > 1 indicates a floor artifact. Current code in `analysis/icskg_analysis_pipeline.py` line 68–73 applies `_minmax()` which will produce this artifact.

**Phase:** CUDS computation stage (analysis pipeline). Address before any regression modeling.

---

### Pitfall 3: IDHM Is Only Available for Census Years — Not Annually

**What goes wrong:** The Atlas do Desenvolvimento Humano (IDHM) is calculated from Demographic Census data. The available reference years are 1991, 2000, 2010, and now 2022. There is no annual IDHM series. For a 2015–2023 panel, this means IDHM (CIMI Dimension 3: Human Capital) has real data only for 2022 within the study window—all other years require interpolation or a proxy.

**Why it happens:** The IDHM methodology requires census microdata for income, education, and longevity calculations; PNAD/PNAD-Contínua provides annual estimates at the state level but not for all 5,570 municipalities.

**Consequences:** If IDHM is used as a static 2022 value across all years, the panel will have no temporal variation for D3—it becomes a cross-sectional variable masquerading as a time-varying one, which inflates regression estimates and violates the panel data assumption. If the 2010 IDHM is linearly interpolated to 2022, the interpolated values are synthetic and will produce spurious smoothness in trend analyses.

**Prevention:**
- Replace annual IDHM with a time-varying proxy: IBGE PNAD-Contínua education indicators (literacy rate, mean years of schooling) available annually at municipal level for larger municipalities, or use per-capita GDP growth as a Human Capital proxy.
- If IDHM is retained, use 2022 Census IDHM as a baseline covariate (not a time-varying dimension), restrict D3 to the 2022 cross-section, and document the limitation.
- Consider using IPEA's annual Índice de Vulnerabilidade Social (IVS) which has municipal-level values more frequently.
- In Methods: explicitly state which IDHM vintage is used and justify the decision.

**Detection:** Query IPEA's Atlas Brasil or Ipeadata for annual IDHM by municipality before committing to this indicator.

**Phase:** Data sourcing (IPEA integration milestone) and dimension specification review.

---

### Pitfall 4: Municipality-of-Treatment Attribution Systematically Biases Referral Hub Municipalities

**What goes wrong:** SIH records the municipality where the hospital is located (municipality of treatment), not the patient's home municipality (municipality of residence). The `cod_mun_internacao` field (treatment municipality) is used for aggregation in the existing `extract_lcogs1.py`. This is documented in PROJECT.md as a known choice, but its analytical consequences are severe: referral hubs (large cities with tertiary hospitals) will receive credit for procedures performed on patients from dozens of surrounding small municipalities. Those small municipalities will appear to have zero or near-zero surgical volume—even if they have adequate access by virtue of proximity to the referral hub.

**Why it happens:** SIH billing is tied to the performing facility's municipality code. Residence municipality (`cod_mun_res`) is also present in SIH but is secondary and has higher missingness.

**Consequences:** LCoGS-3 (surgical volume per 100,000) will show extreme concentration in major cities and near-zero in their catchment municipalities. If CUDS is correlated with being a large city, this creates a spurious positive CUDS–volume correlation driven entirely by geography, not healthcare access. For LCoGS-1 (2-hour travel access), the 765 bellwether facilities identified via CNES are correctly geo-coded from the hospital's perspective, but if a patient travels 4 hours to a hub, LCoGS-1 still counts the hub municipality as served.

**Prevention:**
- Compute surgical volume using BOTH `cod_mun_internacao` and `cod_mun_res`; present both in sensitivity analyses.
- For LCoGS-3 primary analysis, use `cod_mun_res` (patient residence) as the denominator municipality.
- Document the choice, acknowledge that `cod_mun_res` has ~5–10% missingness in SIH and that private-sector transfers are not captured.
- Add a robustness check: re-run primary regressions using treatment-municipality attribution and compare effect sizes.

**Detection:** After aggregation, plot the distribution of surgical volume per 100,000. If the distribution is bimodal (zeros and very high counts), treatment-municipality attribution is likely dominating.

**Phase:** LCoGS computation (bellwether extraction and surgical volume stages).

---

### Pitfall 5: POMR From SIH Captures Only In-Hospital Deaths — Systematic Undercount

**What goes wrong:** SIH records the `MORTE` flag (death during hospitalization). This captures only deaths occurring before hospital discharge. Research in New Zealand found that in-hospital 30-day POMR underestimates true 30-day POMR by approximately one-third. In Brazil, where patients may be discharged early due to bed pressure, the undercounting may be larger. SIH also does not capture 30-day post-discharge deaths, re-admissions, or deaths in transit.

**Why it happens:** SIH was designed as a billing authorization system (AIH — Autorização de Internação Hospitalar), not a clinical outcomes registry. The MORTE field exists to trigger a different payment rate, not to track outcomes.

**Consequences:** POMR will be systematically underestimated across all municipalities. If early discharge rates vary by municipality type (urban hospitals discharge faster; rural hospitals keep patients longer due to no alternative), POMR bias will be differential—urban/high-CUDS municipalities will appear to have even lower POMR, inflating the apparent CUDS protective effect.

**Prevention:**
- In Methods: state clearly that POMR is an in-hospital mortality proxy, not 30-day mortality.
- Use the term "in-hospital perioperative mortality rate" throughout.
- Add a comparison with SIM (Sistema de Informações sobre Mortalidade) death certificates to validate direction: link SIH discharge dates to SIM death dates within 30 days for a sample of municipalities.
- Do not claim POMR target attainment (<0.5% per LCoGS benchmark) without the SIM linkage caveat.

**Detection:** Compare SIH MORTE rate to SIM all-cause post-surgical mortality for the same municipalities and years. Divergence greater than 30% confirms systematic undercounting.

**Phase:** LCoGS-4 computation stage.

---

### Pitfall 6: IFGF Covers Only ~4,544 of 5,570 Municipalities — Non-Random Missingness

**What goes wrong:** FIRJAN's IFGF is calculated from data submitted by municipalities to the National Treasury Secretariat (STN). Municipalities that fail to submit fiscal reports are excluded. This produces ~420 missing municipalities per year. Critically, non-submission correlates with poor fiscal management—the very municipalities that would score lowest on D1 (Governance) are the ones missing from the dataset. This is not missing-at-random (MAR); it is missing-not-at-random (MNAR).

**Why it happens:** FIRJAN explicitly notes that municipalities without available data are excluded from the index. Small, poor municipalities in the North and Northeast are disproportionately non-submitters.

**Consequences:** The IFGF-based D1 score will overestimate average governance quality because the worst-performing municipalities are systematically excluded. If CUDS is then computed only for municipalities with all 9 dimensions available, the study population will skew toward better-governed, richer municipalities—biasing the CUDS–LCoGS relationship. This is a compound selection bias.

**Prevention:**
- Use multiple imputation (mice or fancyimpute) for IFGF missingness, with auxiliary variables (GDP per capita, North/Northeast region flag, population size) as predictors. This is methodologically defensible for MNAR when missingness correlates with observables.
- Report a complete-case analysis alongside the imputed analysis as a sensitivity check.
- Map the geographic distribution of IFGF missingness—if it clusters in North/Northeast, acknowledge that regional analyses for those states are underpowered.
- Consider using STN's SICONFI data directly (the upstream source for IFGF) which has slightly higher coverage.

**Detection:** After loading IFGF, compute `missing_by_year = panel.groupby('year')['D1_fiscal_governance'].isna().sum()`. If consistently above 400, the MNAR problem is active.

**Phase:** D1 computation and panel assembly. Must be resolved before any regression.

---

## Moderate Pitfalls

Mistakes that produce incorrect outputs without necessarily being obvious during development.

---

### Pitfall 7: Min-Max Normalization Applied Pooled Across Years Destroys Temporal Variation

**What goes wrong:** If min-max normalization is applied to the full 2015–2023 panel pooled together (i.e., the minimum and maximum are computed once across all 50,130 observations), a municipality that improves its value over time may not improve its normalized score—because the cross-sectional leaders set the ceiling. Conversely, applying within-year normalization (min-max within each year separately) makes scores incomparable across years: a score of 0.7 in 2015 means "top 30% in 2015" while 0.7 in 2023 means something different.

**Why it happens:** The PROJECT.md specifies "min-max normalization to [0, 1] within each year" (cross-sectional). The current `_minmax()` function in `analysis/icskg_analysis_pipeline.py` does not enforce year-grouping, so if it is called on the pooled panel it will silently produce pooled normalization.

**Consequences:** If pooled normalization is used, temporal trend analyses will be meaningless (scores reflect position in the full distribution, not year-specific position). If within-year normalization is used, longitudinal regressions with year fixed effects will interpret variation correctly, but a municipality cannot be said to have "improved" in absolute terms.

**Prevention:**
- Explicitly normalize within each year using `panel.groupby('year').transform(_minmax)` rather than calling `_minmax` on the full column.
- Add an assertion: after normalization, each year's min = 0 and max = 1 for every dimension.
- In Methods: state clearly whether normalization is cross-sectional (within year) or pooled, and justify the choice relative to the research question (cross-temporal trends vs. cross-sectional ranking).

**Detection:** After normalization, run `panel.groupby('year')[dim_cols].min()` — every cell should be 0.0 if within-year normalization was applied.

**Phase:** CUDS computation stage. Catch this before generating any figures or tables.

---

### Pitfall 8: CNES Professional Records Double-Count Providers Registered at Multiple Facilities

**What goes wrong:** CNES stores individual professional registrations per establishment, not per person. A surgeon registered at 3 hospitals in the same municipality creates 3 CNES records. Summing these records to compute SAO workforce density (LCoGS-2) inflates the apparent number of surgeons, anesthesiologists, and obstetricians. In metropolitan municipalities where professionals commonly have multiple registrations, the inflation can exceed 2x.

**Why it happens:** CNES uses the CBO (Classificação Brasileira de Ocupações) code at the establishment-level. There is no unique professional identifier that persists across facilities in the publicly available CNES extract.

**Consequences:** LCoGS-2 (SAO per 100,000) will be overestimated, particularly in São Paulo and Rio de Janeiro, creating an apparent surplus that contradicts known surgical workforce shortages. The CUDS–SAO relationship will be weakened because the inflation is highest in high-CUDS cities.

**Prevention:**
- Use the CNS (Cartão Nacional de Saúde) professional identifier when present in CNES downloads to deduplicate across facilities. CNS is present in the CNES PROF table.
- Where CNS is missing, apply a conservative correction: sum unique (CPF hash or CNS) identifiers rather than total registrations; if unique IDs are unavailable, present workforce data as "FTE-equivalents from CNES registrations" rather than "number of surgeons."
- Cross-validate with CFM (Conselho Federal de Medicina) and CFAn (anesthesiology council) registry counts for a sample of states.

**Detection:** For a sample of major municipalities, count CNES records for CBO 225125 (surgeon) and compare to known CFM statistics. A ratio > 1.5 indicates double-counting.

**Phase:** LCoGS-2 computation (CNES professional records integration).

---

### Pitfall 9: IBGE GDP Data Has a Systematic 2-Year Release Lag

**What goes wrong:** IBGE's municipal GDP (PIB dos Municípios) is published with approximately a 2-year lag. As of 2026, the most recently available data is for 2022. The study window extends to 2023, leaving the most recent year without GDP data for D2 (Economy). Additionally, GDP data may be revised in subsequent releases; a value used in analysis may differ from the final published figure.

**Why it happens:** Municipal GDP requires consolidation of state-level accounts, tax records, and activity surveys. IBGE releases provisional estimates that are later revised.

**Consequences:** D2 scores for 2023 will require either forward imputation (using 2022 values) or exclusion of 2023 from GDP-dependent analyses. If this is not documented, the panel will silently have a static 2022 GDP value for 2023, distorting any year-2023 subgroup analysis.

**Prevention:**
- At ETL time, log the last available GDP year per municipality and flag municipalities where 2023 GDP was forward-imputed.
- Consider using IBGE's municipal GDP growth rate from state-level accounts to project 2023 values—or use state-level GDP growth as a proxy adjustment.
- For the primary analysis, restrict to 2015–2022 to avoid the imputed year, and present 2023 as a robustness extension.

**Detection:** After SIDRA API download, inspect `max(year)` in the GDP table. If it is 2022, the 2023 gap is present.

**Phase:** IBGE SIDRA integration milestone.

---

### Pitfall 10: ANS Coverage Data Reflects Quarterly Snapshots, Not Year-End States

**What goes wrong:** ANS publishes beneficiary counts quarterly (March, June, September, December). The current `download_ans.py` script uses December snapshots as the year-end value. However, December beneficiary counts include corporate insurance renewals processed in Q4 and exclude plans that lapsed but whose December billing was still pending. The result is a slight upward bias in December compared to the true annual average.

**Why it happens:** ANS's publication schedule is quarterly; December is the closest available approximation to a year-end figure.

**Consequences:** SUS dependence rate (D4 Social Cohesion = 100 − ANS coverage) will be slightly underestimated using December counts. The effect is small (1–3%) but consistent, and it may interact with economic shocks (e.g., 2020 COVID layoffs caused a spike in plan cancellations that a December 2020 snapshot partially misses because cancellations processed in January 2021 affect the December count).

**Prevention:**
- Use the average of all four quarterly counts (March, June, September, December) as the annual ANS coverage rate instead of December alone.
- The `download_ans.py` script already structures quarterly months; modify aggregation logic to average rather than select December.
- Log the number of beneficiaries by quarter to detect anomalous year-end spikes.

**Detection:** For 2020, compare the December ANS beneficiary count to the March 2021 count. A drop greater than 5% signals that December overestimates year-end coverage.

**Phase:** ANS beneficiary integration milestone.

---

### Pitfall 11: RENAVAM Data Reflects Vehicle Registration Municipality, Not Owner Residence

**What goes wrong:** RENAVAM tracks vehicles by the municipality where they are registered (typically where the owner resides, but not always). Fleet vehicles, corporate vehicles, and vehicles registered at dealers are attributed to the dealer or corporate headquarters municipality. In Curitiba, São Paulo, and Manaus, this creates inflated vehicle counts due to large fleet registrations.

**Why it happens:** RENAVAM registration is tied to the billing address for IPVA (vehicle tax), not to the owner's home address.

**Consequences:** D6 (Mobility: vehicles per 1,000 inhabitants) will be artificially elevated in commercial hubs. The CUDS score will slightly overestimate mobility for major commercial cities.

**Prevention:**
- Apply a top-code to vehicles per 1,000 at a defensible ceiling (e.g., 99th percentile) before normalization to prevent outlier inflation.
- In Methods, note the RENAVAM attribution caveat and that commercial hubs may be overestimated.
- Consider reporting results with and without top-coding as a robustness check.

**Phase:** RENAVAM integration milestone (D6 computation).

---

### Pitfall 12: CNES Active Facility Count Includes Inactive and Administratively Closed Establishments

**What goes wrong:** CNES requires health facilities to update their registration monthly. However, many facilities continue to appear in CNES snapshots after closure because the deregistration process requires explicit cancellation by the facility. Research on CNES datasets notes that "despite data being monthly, its quality is not guaranteed on a monthly basis" due to facilities failing to update records. A hospital that closed in 2018 may still appear in 2021 CNES data.

**Why it happens:** CNES deregistration is dependent on the facility actively submitting a closure notice. Administrative failures (municipal health secretariat oversight, dissolved management) leave ghost entries.

**Consequences:** Hospital beds per 10,000 (D7 Urban Planning) and bellwether facility identification (LCoGS-1) may include facilities that no longer operate. Haversine distance to nearest bellwether hospital (LCoGS-1) will be underestimated for municipalities where the "nearest" facility is actually closed.

**Prevention:**
- Filter CNES facilities by `tp_unidade` (establishment type) AND `fl_leito_sus` (active SUS beds) AND `estabelecimento_ativo` flag where available.
- Cross-validate the 765 geocoded bellwether hospitals against SIH surgical volume: a facility with zero SIH records for 2+ years is likely inactive and should be flagged.
- Add a data quality audit step: for each selected bellwether hospital, confirm it has SIH records in the study year.

**Detection:** Count CNES facilities per municipality per year; compare against SIH facilities that actually submitted AIH records. CNES count consistently exceeding SIH-active count by more than 20% signals ghost entries.

**Phase:** CNES bellwether hospital identification milestone and LCoGS-1 computation.

---

### Pitfall 13: Silent Merge Failures Produce Undersized Panel Without Warnings

**What goes wrong:** The `transform_merge()` function in `database/pipeline.py` (lines 161–169) performs an outer join on `cod_ibge` after renaming municipality code columns. If any source fails to standardize its municipality code (e.g., IFGF uses `Cod_IBGE` as 6-digit with leading zero, while SIH uses 6-digit without leading zero, while ANS uses 7-digit with check digit), the outer join silently produces a cartesian explosion or a near-empty merge. The code logs the final row count but does not validate that it equals the expected 5,570 municipalities.

**Why it happens:** Brazilian municipality codes exist in multiple formats: 6-digit IBGE (e.g., `350950`), 7-digit with check digit (e.g., `3509502`), and name-based strings. Different data sources use different conventions with no enforced standard in the pipeline.

**Consequences:** The panel may contain duplicates (from a cartesian join), missing municipalities (from a failed inner-equivalent match), or null-filled records. All downstream dimension scores and CUDS computations will be wrong. This is one of the hardest bugs to detect because the pipeline appears to complete successfully.

**Prevention:**
- Establish a single canonical municipality code format at ingestion time: 6-digit integer (truncate 7-digit codes by dropping the check digit). Apply this normalization in every source-specific extractor before any merge.
- After `transform_merge()`, assert: `assert len(merged) == 5570, f"Expected 5570 rows, got {len(merged)}"`.
- Add a pre-merge audit: log the unique municipality code count and a sample of 5 codes from each source before joining.
- Add a post-merge completeness check: count nulls per column and flag any column with >5% nulls as a pipeline warning.

**Detection:** `df['cod_ibge'].nunique()` after merge should equal 5,570. Any deviation requires investigation before proceeding.

**Phase:** ETL transform_merge stage. This is the most likely source of silent data corruption in the current codebase.

---

## Minor Pitfalls

Low severity but common sources of avoidable confusion.

---

### Pitfall 14: SIOPS Data Is Declarative and Self-Reported — Municipalities Can Over-Report Health Expenditure

**What goes wrong:** SIOPS collects health expenditure data from municipal health secretariats by self-declaration. Studies of SIOPS quality show that municipalities have an incentive to over-report health spending to appear to meet the Constitutional minimum (15% of net current revenue). The data is declarative, meaning it is not independently audited at submission time.

**Prevention:** Cap D10 (Per-capita health expenditure) outliers at the 99th percentile. Cross-validate suspicious municipalities (those reporting health expenditure above 40% of budget) against TCM/TCE audit reports where available. In Methods, note the declarative nature of SIOPS.

**Phase:** SIOPS integration milestone.

---

### Pitfall 15: IBGE Census 2022 Sanitation Data Is Cross-Sectional Only

**What goes wrong:** The Census 2022 sanitation indicators (D5 Environment) are available only for 2022. The 2010 Census provides the prior benchmark. For a 2015–2023 panel, using 2022 Census data as a time-invariant variable is defensible for recent years but not for 2015–2018, when sanitation infrastructure was different in many municipalities.

**Prevention:** Use the 2022 value as a cross-sectional covariate (environment at panel end-point), not as a time-varying dimension. Document the static nature of D5 explicitly. Consider SNIS (Sistema Nacional de Informações sobre Saneamento) as an annual proxy: SNIS publishes municipal-level water and sewerage coverage annually and is an appropriate temporal substitute.

**Phase:** Census 2022 integration milestone. Consider switching to SNIS for the time-varying panel dimension.

---

### Pitfall 16: Municipality Code Drift — 5 New Municipalities Created Between 2013 and 2023

**What goes wrong:** IBGE updated its municipal list between study years. Balneário Rincão (SC) and several others were created after 2013 and received new IBGE codes. Panel joins using a static 5,570-municipality reference frame will either assign new municipality records to null or silently drop them.

**Prevention:** Use a temporal municipality crosswalk (AMC — Áreas Mínimas Comparáveis) to handle emancipations and mergers. The geobr R package and Ehrl's AMC crosswalk provide this. Apply the crosswalk at panel assembly to ensure temporal consistency. Always join against an authoritative IBGE municipality table for the specific study year rather than a static reference.

**Phase:** Panel assembly and database schema definition.

---

### Pitfall 17: Ecological Study Cannot Distinguish Between Association and Composition Effects

**What goes wrong:** Associations observed at the municipality level (CUDS → LCoGS) may be driven by the composition of the population (e.g., wealthier municipalities have both higher CUDS and higher surgical volume because their residents choose private care) rather than a causal ecological effect. Presenting this as "urban development predicts surgical system performance" without clearly framing the ecological fallacy risk invites peer reviewer rejection from journals like BMJ Global Health.

**Prevention:** Use the STROBE-E checklist for ecological studies explicitly. Add a dedicated "Interpretation Caveat" subsection in the Discussion stating that associations at the municipality level cannot be extrapolated to individuals. Include a confounding analysis controlling for GDP per capita, region, and population size to show the CUDS effect is not purely a proxy for wealth. Frame findings as "dose-response associations at the ecological level."

**Phase:** Manuscript writing and analysis interpretation stages.

---

### Pitfall 18: PySUS DBC Conversion Fails Silently on Windows and Returns No Error

**What goes wrong:** PySUS was developed for Linux and uses blast-dbf (a Linux binary) for DBC-to-DBF conversion. On macOS and Windows, the conversion silently returns False rather than raising an exception. The existing download scripts (`continue_raw_download.py`, `sih_batch_v2.py`) catch the False return but the calling code in `database/pipeline.py` does not check whether the output parquet file was actually created—it only checks if the path was returned.

**Consequences:** On macOS (the stated development platform per env context), SIH DBC files may download but never convert, producing missing parquet inputs to `transform_merge()`. The outer join then proceeds with `sih=None`, which triggers the "Source sih not found – skipping" warning—easy to miss in log output during a long batch run.

**Prevention:**
- After every DBC conversion call, assert that the output parquet file exists and has non-zero size.
- Add a pre-flight check at pipeline startup that verifies blast-dbf is available (`shutil.which('blast-dbf')`).
- For macOS development, use the Docker-based PySUS environment or install blast-dbf via Homebrew if available.
- Log the total DBC files downloaded vs. parquet files successfully converted as a ratio at the end of each batch run.

**Phase:** SIH extraction milestone (earliest). Blocking for all downstream stages.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|---|---|---|
| SIH full 12-month annualization | Pitfall 18 (PySUS conversion) + Pitfall 4 (treatment vs. residence) | Verify parquet output existence; decide municipality attribution before bulk download |
| CNES professional records / SAO density | Pitfall 8 (double-counting across facilities) | Deduplicate on CNS identifier before summing |
| IDHM / IPEA integration | Pitfall 3 (census-only availability) | Switch to annual proxy before building panel |
| IFGF parsing | Pitfall 6 (MNAR missingness ~420 municipalities) | Multiple imputation with auxiliary variables |
| ANS beneficiary download | Pitfall 10 (quarterly vs. annual) | Average Q1–Q4 rather than December snapshot |
| Panel assembly (transform_merge) | Pitfall 13 (municipality code format mismatch) | Canonicalize to 6-digit integer at every source ingestion |
| CUDS computation | Pitfall 2 (geometric mean zeros) + Pitfall 7 (normalization scope) | Floor offset; enforce within-year groupby normalization |
| LCoGS-1 (bellwether access) | Pitfall 12 (ghost CNES facilities) | Validate against SIH activity records |
| LCoGS-3 (surgical volume) | Pitfall 1 (SIH private sector blindspot) + Pitfall 4 | Restrict interpretation to SUS-funded care |
| LCoGS-4 (POMR) | Pitfall 5 (in-hospital only) | Label as in-hospital POMR; add SIM linkage sensitivity |
| D7 (hospital beds / Urban Planning) | Pitfall 12 (ghost entries) | Filter to active facilities with recent SIH records |
| D10 (health expenditure / SIOPS) | Pitfall 14 (self-reported, over-reporting) | 99th percentile cap; note declarative nature |
| D5 (sanitation / Census 2022) | Pitfall 15 (cross-sectional only) | Consider SNIS annual series as temporal substitute |
| Regression / ML models | Pitfall 17 (ecological fallacy) | STROBE-E checklist; confounding controls; framing |
| Manuscript submission | Pitfall 1, 4, 5, 17 | Explicit Limitations subsection addressing all four |

---

## Sources

- [Limitations of using the DATASUS database as a primary source of data in surgical research: a scoping review — PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC10508673/) — HIGH confidence (peer-reviewed scoping review)
- [A comprehensive integrated dataset on Brazilian health facilities: from 2005 to 2021 — BMC Research Notes](https://bmcresnotes.biomedcentral.com/articles/10.1186/s13104-023-06422-y) — HIGH confidence (data descriptor paper)
- [Bellwether Procedures for Monitoring Subnational Variation of All-cause Perioperative Mortality in Brazil — World Journal of Surgery](https://link.springer.com/article/10.1007/s00268-020-05607-x) — HIGH confidence (directly relevant to this project's methodology)
- [Systematic review of the Lancet Commission on Global Surgery indicators — BJS](https://academic.oup.com/bjs/article/113/3/znaf289/8505882) — HIGH confidence (systematic review 2024)
- [Improvements in data completeness in health information systems reveal racial inequalities — International Journal for Equity in Health](https://equityhealthj.biomedcentral.com/articles/10.1186/s12939-024-02214-3) — HIGH confidence
- [On the Methodological Framework of Composite Indices — Social Indicators Research](https://link.springer.com/article/10.1007/s11205-017-1832-9) — HIGH confidence (peer-reviewed methodology paper)
- [Aggregating Composite Indicators through the Geometric Mean: A Penalization Approach — MDPI](https://www.mdpi.com/2079-3197/10/4/64) — HIGH confidence
- [Administrative Data Linkage in Brazil: Potentials for Health Technology Assessment — PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC6768004/) — HIGH confidence
- [FIRJAN IFGF English Version — FIRJAN](https://www.firjan.com.br/data/files/3F/22/D1/8B/7AF3E5107210A3E5A8A809C2/IFGF%20-%20English%20Version.pdf) — HIGH confidence (official documentation)
- [Atlas do Desenvolvimento Humano no Brasil — IPEA](https://www.ipea.gov.br/portal/categoria-projetos-e-estatisticas/9941-atlas-do-desenvolvimento-humano-no-brasil) — HIGH confidence (official source)
- [Perioperative mortality as a meaningful indicator — PubMed](https://pubmed.ncbi.nlm.nih.gov/32745634/) — HIGH confidence
- [PySUS SIH FTP Database documentation](https://pysus.readthedocs.io/en/latest/databases/SIH.html) — HIGH confidence (official library docs)
- ICSKG-BR `.planning/codebase/CONCERNS.md` — HIGH confidence (direct codebase audit)
- ICSKG-BR `.planning/PROJECT.md` — HIGH confidence (project specification)
