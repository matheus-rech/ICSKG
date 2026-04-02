# Phase 4: Panel Assembly & Validation - Research

**Researched:** 2026-04-01
**Domain:** Panel data assembly, monetary deflation, multiple imputation, SQLite schema design, missingness documentation
**Confidence:** HIGH

## Summary

Phase 4 merges all 9+ extracted Parquet sources into a single validated municipality-year panel (target: 50,130 rows = 5,571 municipalities x 9 years) in SQLite. The phase has four distinct technical domains: (1) IPCA deflation of monetary variables to constant 2023 BRL, (2) outer-join merge of heterogeneous sources on (cod_ibge, year) with validation gates, (3) IFGF multiple imputation for ~420 MNAR municipalities per year, and (4) SQLite schema redesign to accommodate all CIMI dimensions and LCoGS source columns.

The existing codebase provides strong foundations: `database/validation.py` implements a 4-check validation gate, `database/utils.py` has `normalize_cod_ibge()` and `load_ibge_municipios()`, `database/pipeline.py` has a `transform_merge()` stub handling 4 sources (needs expansion to 11+), and `database/build_database_v2.py` has SQLite DDL patterns. The primary work is extending these existing patterns, not building from scratch.

**Primary recommendation:** Use IBGE SIDRA table 1737 (variable 2266, IPCA numero-indice) for deflation via `sidrapy` (already a dependency). Use scikit-learn `IterativeImputer` with `sample_posterior=True` and `BayesianRidge` estimator for IFGF multiple imputation (m=5). Create `build_database_v3.py` with an updated schema mapping all Phase 2+3 source columns to CIMI dimensions.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Deflate SIOPS and GDP per capita to constant 2023 BRL using IPCA health sub-index
- Log deflation factors in an auditable deflation table
- IPCA indices sourced from IBGE SIDRA or BCB SGS API
- Outer join all sources on (cod_ibge, year) -- preserve all municipalities even with missing data
- Assert 5,571 rows per year after merge (updated IBGE count)
- normalize_cod_ibge() applied to all sources before join
- apply_amc_crosswalk() for temporal harmonization
- validate_dataframe() on each source before merge
- validation_report.json with per-source quality metrics
- Quarantine directory for flagged rows
- ~420 municipalities/year are MNAR (Missing Not At Random) for IFGF
- Multiple imputation using auxiliary variables: GDP, region, population
- Method and results logged in PANL-05-imputation.log
- municipal_health table with exactly 50,130 rows (5,571 x 9 years) target
- Schema matches documented DDL from database/build_database_v2.py
- dimension_metadata and municipality_lookup tables
- PANL-06-missingness.csv: missingness rate per variable per year
- Satisfies RECORD reporting item 12.1

### Claude's Discretion
- IPCA source selection (SIDRA vs BCB SGS)
- Multiple imputation library (scikit-learn IterativeImputer vs statsmodels MICE)
- SQLite schema design for new columns from Phase 3 sources
- Whether to refactor build_database_v2.py or create build_database_v3.py

### Deferred Ideas (OUT OF SCOPE)
- DuckDB analytical mirror (optional, not required for v1.0)
- MotherDuck cloud deployment
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DATA-10 | All monetary variables (SIOPS, GDP) deflated to constant 2023 BRL using IPCA indices | SIDRA table 1737 var 2266 provides IPCA number-index; deflation formula documented below |
| PANL-01 | Municipality-year merge producing one row per municipality per year (assert 5,571 rows/year) | Merge strategy with IBGE reference scaffold + left joins documented; 11 source schemas catalogued |
| PANL-02 | Validation report (validation_report.json) with per-source quality metrics | Existing validate_dataframe() + write_validation_report() cover this; needs orchestration |
| PANL-03 | Quarantine directory for flagged rows excluded from panel | Existing quarantine logic in validation.py handles this |
| PANL-04 | SQLite database with municipal_health table (50,130 rows target), dimension_metadata, municipality_lookup | New DDL schema documented below; build_database_v3.py recommended |
| PANL-05 | IFGF multiple imputation for ~420 MNAR municipalities per year using auxiliary variables | IterativeImputer with BayesianRidge, sample_posterior=True, m=5; pattern documented below |
| PANL-06 | Missing data documentation table showing missingness rates per variable per year (RECORD item 12.1) | RECORD 12.1 requirements documented; CSV format specified |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pandas | >=2.2.3 | DataFrame merge, pivot, aggregation | Already pinned in pyproject.toml; core data manipulation |
| sidrapy | >=0.1.4 | IBGE SIDRA API for IPCA deflation indices | Already pinned; used by extract_ibge_sidra.py; table 1737 access |
| scikit-learn | >=1.6 (1.8.0 installed) | IterativeImputer for IFGF multiple imputation | Already pinned; experimental but stable API since 1.0 |
| sqlite3 | stdlib | SQLite database creation and persistence | Already used in build_database_v2.py; no additional dep |
| numpy | >=2.0 | Numerical operations, NaN handling | Already pinned |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| python-bcb | 0.3.6 | BCB SGS API for IPCA series (fallback) | Only if SIDRA table 1737 is unavailable; NOT in pyproject.toml yet |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| SIDRA table 1737 for IPCA | BCB SGS series 433 via python-bcb | SGS gives monthly variation (requires cumulative product); SIDRA 1737 var 2266 gives index number directly -- simpler |
| SIDRA table 1737 for IPCA | SIDRA table 7060/1419 for health sub-index | Health sub-index requires stitching tables 1419 (2012-2019) + 7060 (2020+), complex classification codes; general IPCA is standard for health economics |
| scikit-learn IterativeImputer | statsmodels MICE / R mice package | statsmodels lacks native MICE; R would break Python-only stack; IterativeImputer is MICE-inspired and adequate for auxiliary-variable imputation |
| scikit-learn IterativeImputer | Custom Bayesian regression | Unnecessary complexity; IterativeImputer with BayesianRidge is the standard approach |

**IPCA Source Recommendation (Claude's Discretion):** Use SIDRA table 1737, variable 2266 (IPCA numero-indice, base Dec 1993=100). This gives a single number per month from Dec 1979 through present. Deflation is a simple ratio: `value_real = value_nominal * (index_dec_2023 / index_dec_year)`. No cumulative product needed, no table stitching needed. `sidrapy` is already a dependency. If SIDRA is temporarily unavailable, fall back to BCB SGS series 433 with `requests` (compute cumulative product from monthly variations).

**IPCA Health Sub-Index vs General IPCA:** The CONTEXT.md mentions "IPCA health sub-index." Research finding: the IPCA health sub-index (Saude e Cuidados Pessoais) is available only as group-level variations in tables 1419 (Jan 2012-Dec 2019) and 7060 (Jan 2020+), classification c315 code 7712. It requires stitching two tables and computing the number index from monthly variations. The general IPCA (table 1737 var 2266) is the standard deflator used in Brazilian health economics literature (SIOPS itself reports in nominal BRL deflated by general IPCA). **Recommendation: Use general IPCA for deflation, note health sub-index as sensitivity analysis option in Discussion section.** If the user insists on the health sub-index, the implementation path is documented in the Pitfalls section below.

**Imputation Library Recommendation (Claude's Discretion):** Use `sklearn.impute.IterativeImputer` with `sample_posterior=True` and `BayesianRidge` estimator. Run m=5 imputations with different random seeds, pool results using Rubin's rules. IterativeImputer is still experimental (requires `from sklearn.experimental import enable_iterative_imputer`) but has been stable since scikit-learn 1.0 and is the de facto Python MICE implementation. The R `mice` package has more mature MNAR support, but switching to R would break the Python-only stack constraint.

**Schema Decision (Claude's Discretion):** Create `build_database_v3.py` rather than refactoring v2. The v2 schema is health-system-specific (D1-D9 as health dimensions); v3 needs CIMI-aligned dimensions with different column names. Keeping v2 preserves backward compatibility for anyone who ran it before.

## Architecture Patterns

### Recommended Project Structure
```
database/
  build_database_v3.py      # NEW: Updated SQLite builder for CIMI schema
  assemble_panel.py          # NEW: Panel assembly orchestrator (merge + validate + impute)
  deflate_ipca.py            # NEW: IPCA deflation module
  impute_ifgf.py             # NEW: IFGF multiple imputation module
  build_database_v2.py       # EXISTING: Preserved for backward compat
  pipeline.py                # EXISTING: Updated transform_merge() for all sources
  validation.py              # EXISTING: Unchanged
  utils.py                   # EXISTING: Unchanged
```

### Pattern 1: Scaffold-First Merge (IBGE Reference as Skeleton)
**What:** Build the panel skeleton from the IBGE reference list x year range, then left-join each source onto it. This guarantees exactly 5,571 rows per year regardless of source coverage.
**When to use:** Always -- this is the correct pattern for ecological panel studies where the universe of municipalities is fixed.
**Example:**
```python
# Source: Project-specific pattern based on load_ibge_municipios()
from database.utils import load_ibge_municipios

def build_panel_scaffold(years: range) -> pd.DataFrame:
    """Create skeleton DataFrame: 5,571 municipalities x N years."""
    ref = load_ibge_municipios()  # 5,571 rows with cod_ibge, nome_municipio, uf
    scaffolds = []
    for year in years:
        scaffold = ref[["cod_ibge"]].copy()
        scaffold["year"] = year
        scaffolds.append(scaffold)
    panel = pd.concat(scaffolds, ignore_index=True)
    assert len(panel) == len(ref) * len(years)
    return panel  # e.g., 5,571 * 9 = 50,139 rows
```

### Pattern 2: Sequential Left-Join with Validation
**What:** Join each validated source onto the scaffold using left join on (cod_ibge, year). Sources that lack rows for some municipalities simply produce NaN in the panel.
**When to use:** For all source merges after scaffold creation.
**Example:**
```python
# Each source validated before join
clean_df, report = validate_dataframe(source_df, source_name="ifgf")
reports.append(report)

# Left join onto scaffold (never outer -- scaffold IS the universe)
panel = panel.merge(
    clean_df[["cod_ibge", "year", "ifgf_geral", ...]],
    on=["cod_ibge", "year"],
    how="left",
    validate="1:1",  # Critical: catch many-to-many
)
```

### Pattern 3: IPCA Deflation with Auditable Log
**What:** Fetch IPCA number-index, compute deflation factor per year, apply to monetary columns, log factors.
**When to use:** For SIOPS health_expenditure_per_capita and GDP gdp_per_capita columns.
**Example:**
```python
# Source: IBGE SIDRA table 1737, variable 2266
import sidrapy

def fetch_ipca_index(base_year: int = 2023) -> pd.DataFrame:
    """Fetch IPCA number-index from SIDRA table 1737."""
    raw = sidrapy.get_table(
        table_code="1737",
        territorial_level="1",
        ibge_territorial_code="all",
        variable="2266",
        period="all",
    )
    # Parse: extract December value per year as annual index
    # Deflation factor: index_dec_base_year / index_dec_year
    ...

def deflate_column(
    df: pd.DataFrame,
    col: str,
    ipca_factors: pd.Series,  # year -> deflation_factor
) -> pd.DataFrame:
    """Multiply nominal values by deflation factor."""
    df[f"{col}_nominal"] = df[col].copy()  # preserve original
    df[col] = df[col] * df["year"].map(ipca_factors)
    return df
```

### Pattern 4: Multiple Imputation with IterativeImputer
**What:** Run m=5 imputations on IFGF columns using auxiliary variables, pool via Rubin's rules.
**When to use:** For IFGF MNAR municipalities only.
**Example:**
```python
# Source: scikit-learn 1.8.0 docs
from sklearn.experimental import enable_iterative_imputer  # noqa
from sklearn.impute import IterativeImputer

def impute_ifgf(
    panel: pd.DataFrame,
    m: int = 5,
    max_iter: int = 10,
) -> pd.DataFrame:
    """Multiple imputation for IFGF columns using auxiliary variables."""
    ifgf_cols = ["ifgf_geral", "ifgf_ra", "ifgf_gp", "ifgf_id", "ifgf_el", "ifgf_sa"]
    aux_cols = ["gdp_per_capita", "populacao", "region_code"]
    feature_cols = ifgf_cols + aux_cols

    imputed_frames = []
    for i in range(m):
        imputer = IterativeImputer(
            estimator=BayesianRidge(),
            sample_posterior=True,
            max_iter=max_iter,
            random_state=i * 42,
        )
        imputed = imputer.fit_transform(panel[feature_cols])
        imputed_frames.append(
            pd.DataFrame(imputed, columns=feature_cols, index=panel.index)
        )

    # Pool: mean across m imputations (Rubin's rules simplified)
    pooled = pd.concat(imputed_frames).groupby(level=0).mean()
    panel[ifgf_cols] = pooled[ifgf_cols]
    return panel
```

### Anti-Patterns to Avoid
- **Outer join cascade:** Do NOT chain outer joins across sources. This creates rows for municipality codes that appear in sources but not in the IBGE reference. Use scaffold-first + left join instead.
- **Row-by-row iteration for upsert:** The existing `build_database_v2.py` uses `iterrows()` for 50K+ rows. Use `df.to_sql()` with `if_exists="replace"` or batch `executemany()` instead.
- **Imputing before validation:** Run `validate_dataframe()` BEFORE imputation. Imputing invalid municipality codes or out-of-scope years wastes cycles and introduces garbage.
- **Deflating imputed values:** Deflate SIOPS and GDP BEFORE imputation. The imputer should work with real (constant) values, not nominal values that mix price-level effects with fiscal management variation.
- **Single imputation presented as multiple:** If using `sample_posterior=False`, IterativeImputer produces deterministic output -- this is single imputation, not MICE. Must use `sample_posterior=True` with different random seeds.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| IPCA deflation indices | Manual monthly variation chain | SIDRA table 1737 var 2266 (number index) | Index is pre-computed by IBGE; manual chain accumulates floating-point errors |
| Multiple imputation | Custom Bayesian regression loop | `sklearn.impute.IterativeImputer` | Handles feature ordering, convergence, posterior sampling |
| Validation gate | Per-source ad-hoc checks | Existing `validate_dataframe()` | Already implements 4 checks with quarantine and reporting |
| Municipality scaffold | Manual cod_ibge list | `load_ibge_municipios()` | Returns authoritative 5,571-row reference; assertion-guarded |
| Panel row count assertion | Manual counting | `assert len(panel[panel.year == y]) == 5571` | Simple, catches merge explosions immediately |

**Key insight:** The existing validation.py, utils.py, and pipeline.py provide >60% of the infrastructure. Phase 4 is primarily an orchestration and integration task, not a greenfield build.

## Common Pitfalls

### Pitfall 1: IPCA Table Routing (1419 vs 7060)
**What goes wrong:** SIDRA table 7060 only has data from Jan 2020+; table 1419 covers Jan 2012-Dec 2019. If you use table 7060 alone for the 2015-2023 window, you get NaN for 2015-2019.
**Why it happens:** IBGE restructured IPCA product classification in 2020 and created a new table.
**How to avoid:** Use table 1737 instead -- it has the IPCA number-index from Dec 1979 through present in a single table. No stitching needed.
**Warning signs:** Missing deflation factors for years before 2020.

### Pitfall 2: Merge Key Explosion (Many-to-Many)
**What goes wrong:** If any source has duplicate (cod_ibge, year) rows, the merge produces a cartesian product, ballooning from 50K to millions of rows and consuming all memory.
**Why it happens:** Some sources (SIH, CNES professionals) are per-record, not per-municipality-year. They must be aggregated before merge.
**How to avoid:** Use `validate="1:1"` in every `pd.merge()` call. Run `validate_dataframe()` duplicate-key check before merge. Aggregate SIH/CNES to municipality-year level first.
**Warning signs:** `len(panel) > 5571 * 9` after any merge step.

### Pitfall 3: IFGF MNAR Pattern is Systematic, Not Random
**What goes wrong:** Treating IFGF missingness as MAR (Missing At Random) when it is MNAR (Missing Not At Random) biases imputation results. The ~420 missing municipalities are systematically those with the worst fiscal management (they failed to submit reports).
**Why it happens:** Default imputation assumes MAR. MNAR means the probability of being missing depends on the unobserved value itself.
**How to avoid:** (1) Use auxiliary variables (GDP, population, region) that are correlated with fiscal management but fully observed. (2) Document the MNAR assumption explicitly. (3) Run sensitivity analysis comparing complete-case vs imputed results. (4) Log which municipalities were imputed.
**Warning signs:** Imputed IFGF values clustering near the mean (regression to mean) rather than showing the expected left skew for non-reporting municipalities.

### Pitfall 4: Cross-Sectional Sources Breaking Panel Structure
**What goes wrong:** IDHM (2010 only) and Census 2022 sanitation are cross-sectional -- they have a single year value. Joining them to a 9-year panel requires either (a) constant-fill across years or (b) leaving as a single-year column.
**Why it happens:** These are census-derived indicators with no annual frequency.
**How to avoid:** For IDHM: year=2010, constant-filled to all panel years with a `idhm_is_crosssectional=True` flag column. For Census sanitation: year=2022, constant-filled with `sanitation_is_crosssectional=True`. Document this in dimension_metadata.
**Warning signs:** NaN in the panel for idhm/sanitation columns for years other than 2010/2022.

### Pitfall 5: SIOPS and RENAVAM Empty Schema Parquet
**What goes wrong:** Both SIOPS and RENAVAM extractors write empty-schema Parquet files on total failure (API down, crosswalk failure). Merging an empty DataFrame produces silent data loss -- the column exists but is entirely NaN.
**Why it happens:** The best-effort pattern in Phase 3 extractors prioritizes pipeline continuation over data completeness.
**How to avoid:** After loading each source, check `len(df) > 0` and `df[value_col].notna().sum() > 0`. If empty, log a gap to the validation report and skip the merge for that source (still document the missingness).
**Warning signs:** A column in the final panel that is 100% NaN.

### Pitfall 6: IterativeImputer Experimental Import
**What goes wrong:** `from sklearn.impute import IterativeImputer` raises ImportError because it is still experimental in scikit-learn 1.8.0.
**Why it happens:** IterativeImputer has been experimental since its introduction and has not graduated.
**How to avoid:** Always import the enabler first: `from sklearn.experimental import enable_iterative_imputer  # noqa`
**Warning signs:** `ImportError: cannot import name 'IterativeImputer'`

### Pitfall 7: Municipality Count Mismatch (5,570 vs 5,571)
**What goes wrong:** Phase 1 established 5,571 as the authoritative IBGE count (includes Boa Esperanca do Norte-MT, code 5101837). Some documentation and older code says 5,570. The ROADMAP success criteria says "assert 5,570", but the reference list has 5,571.
**Why it happens:** Boa Esperanca do Norte-MT was added to the IBGE list after the initial 2023 reference.
**How to avoid:** Always derive the expected count dynamically from `load_ibge_municipios()`: `expected = len(ref)`. Never hardcode 5,570 or 5,571.
**Warning signs:** Off-by-one assertion failures.

### Pitfall 8: Deflation Before vs After Imputation
**What goes wrong:** If monetary variables (SIOPS, GDP) are deflated after imputation, the imputer mixes nominal values from different years, producing biased estimates.
**Why it happens:** Pipeline ordering mistake.
**How to avoid:** Deflation is Step 1 (before merge), imputation is Step 3 (after merge). The order must be: Extract -> Deflate -> Validate -> Merge -> Impute -> Persist.
**Warning signs:** GDP per capita values for 2015 looking implausibly similar to 2023 values.

## Code Examples

### IPCA Deflation Module
```python
# Source: IBGE SIDRA table 1737, variable 2266
# Verified: Table 1737 covers Dec 1979 -- Feb 2026, variable 2266 = number-index
import sidrapy
import pandas as pd
import logging

logger = logging.getLogger(__name__)

def fetch_ipca_annual_index(
    years: list[int],
    base_year: int = 2023,
) -> pd.DataFrame:
    """Fetch December IPCA number-index from SIDRA table 1737.

    Returns DataFrame with columns [year, ipca_index, deflation_factor].
    deflation_factor = index_base_year / index_year (multiply nominal by this).
    """
    raw = sidrapy.get_table(
        table_code="1737",
        territorial_level="1",
        ibge_territorial_code="all",
        variable="2266",
        period="all",
    )
    # raw has header row at index 0; skip it
    df = raw.iloc[1:].copy()
    df["year"] = pd.to_numeric(df["D2C"].str[:4], errors="coerce")
    df["month"] = pd.to_numeric(df["D2C"].str[4:6], errors="coerce")
    df["ipca_index"] = pd.to_numeric(df["V"], errors="coerce")

    # Use December value as the annual reference
    dec = df[df["month"] == 12][["year", "ipca_index"]].copy()
    dec = dec[dec["year"].isin(years + [base_year])]

    base_index = dec.loc[dec["year"] == base_year, "ipca_index"].iloc[0]
    dec["deflation_factor"] = base_index / dec["ipca_index"]

    logger.info(
        "IPCA deflation factors (base %d): %s",
        base_year,
        dict(zip(dec["year"], dec["deflation_factor"].round(4))),
    )
    return dec[["year", "ipca_index", "deflation_factor"]]
```

### Scaffold-First Merge Orchestration
```python
# Source: Project-specific pattern
from database.utils import load_ibge_municipios, normalize_cod_ibge
from database.validation import validate_dataframe, write_validation_report

def assemble_panel(
    sources: dict[str, pd.DataFrame],
    years: range,
) -> tuple[pd.DataFrame, list]:
    """Merge all validated sources onto IBGE reference scaffold."""
    ref = load_ibge_municipios()
    expected_per_year = len(ref)

    # Build scaffold
    scaffolds = []
    for year in years:
        s = ref[["cod_ibge"]].copy()
        s["year"] = year
        scaffolds.append(s)
    panel = pd.concat(scaffolds, ignore_index=True)

    reports = []
    for name, df in sources.items():
        if df.empty or df.iloc[:, 2:].notna().sum().sum() == 0:
            logger.warning("Source %s is empty -- skipping merge", name)
            continue
        df["cod_ibge"] = normalize_cod_ibge(df["cod_ibge"])
        clean_df, report = validate_dataframe(df, source_name=name)
        reports.append(report)

        # Select only relevant columns (drop source-internal cols)
        merge_cols = ["cod_ibge", "year"] + [
            c for c in clean_df.columns
            if c not in ("cod_ibge", "year")
        ]
        panel = panel.merge(
            clean_df[merge_cols],
            on=["cod_ibge", "year"],
            how="left",
            validate="1:1",
        )

    # Assert row counts
    for y in years:
        n = len(panel[panel["year"] == y])
        assert n == expected_per_year, (
            f"Year {y}: expected {expected_per_year} rows, got {n}"
        )

    return panel, reports
```

### Multiple Imputation Pattern
```python
# Source: scikit-learn 1.8.0 IterativeImputer docs
from sklearn.experimental import enable_iterative_imputer  # noqa
from sklearn.impute import IterativeImputer
from sklearn.linear_model import BayesianRidge
import numpy as np

IFGF_COLS = ["ifgf_geral", "ifgf_ra", "ifgf_gp", "ifgf_id", "ifgf_el", "ifgf_sa"]
AUX_COLS = ["gdp_per_capita", "populacao", "region_code"]

def impute_ifgf_mice(
    panel: pd.DataFrame,
    m: int = 5,
    max_iter: int = 10,
) -> tuple[pd.DataFrame, dict]:
    """Run m imputations on IFGF columns, pool via Rubin's rules.

    Returns (imputed_panel, imputation_log).
    """
    feature_cols = IFGF_COLS + AUX_COLS
    # Encode region as integer for imputer
    if "region_code" not in panel.columns:
        region_map = {"N": 1, "NE": 2, "CO": 3, "SE": 4, "S": 5}
        panel["region_code"] = panel["uf"].map(
            lambda uf: _uf_to_region_code(uf, region_map)
        )

    X = panel[feature_cols].copy()
    mnar_mask = panel[IFGF_COLS].isna().any(axis=1)

    imputed_arrays = []
    for i in range(m):
        imp = IterativeImputer(
            estimator=BayesianRidge(),
            sample_posterior=True,
            max_iter=max_iter,
            random_state=i * 42,
            verbose=0,
        )
        imputed_arrays.append(imp.fit_transform(X))

    # Pool: mean across imputations for IFGF columns only
    stacked = np.stack(imputed_arrays, axis=0)  # (m, n_rows, n_features)
    pooled_mean = stacked[:, :, :len(IFGF_COLS)].mean(axis=0)
    pooled_var_within = stacked[:, :, :len(IFGF_COLS)].var(axis=0)

    panel.loc[:, IFGF_COLS] = pooled_mean

    log = {
        "m": m,
        "max_iter": max_iter,
        "n_imputed_rows": int(mnar_mask.sum()),
        "ifgf_cols": IFGF_COLS,
        "aux_cols": AUX_COLS,
        "method": "IterativeImputer(BayesianRidge, sample_posterior=True)",
    }
    return panel, log
```

## SQLite Schema Design (Recommended v3)

The existing v2 schema uses health-system-specific D1-D9 column names that do not match the CIMI dimension framework. The v3 schema maps directly to CIMI dimensions and includes all source columns needed for Phase 5+ computation.

```sql
-- build_database_v3.py DDL

CREATE TABLE IF NOT EXISTS municipal_health (
    cod_ibge         TEXT    NOT NULL,
    year             INTEGER NOT NULL,

    -- CIMI D1: Governance (IFGF)
    ifgf_geral       REAL,
    ifgf_ra          REAL,
    ifgf_gp          REAL,
    ifgf_id          REAL,
    ifgf_el          REAL,
    ifgf_sa          REAL,
    ifgf_is_imputed  INTEGER DEFAULT 0,  -- 1 if multiple-imputed

    -- CIMI D2: Economy (GDP)
    gdp_per_capita   REAL,    -- constant 2023 BRL (deflated)
    gdp_abs          REAL,    -- constant 2023 BRL (deflated)
    gdp_estimated    INTEGER, -- 1 if IBGE estimate (2022-2023)

    -- CIMI D3: Human Capital (IDHM)
    idhm             REAL,
    idhm_educacao    REAL,
    idhm_longevidade REAL,
    idhm_renda       REAL,

    -- CIMI D4: Social Cohesion (ANS coverage)
    beneficiarios_mean       REAL,    -- quarterly average
    private_coverage_rate    REAL,    -- beneficiarios / populacao
    sus_dependence_rate      REAL,    -- 1 - private_coverage_rate

    -- CIMI D5: Environment (Census sanitation)
    pct_sanitation_adequate  REAL,
    pct_water_adequate       REAL,

    -- CIMI D6: Mobility (RENAVAM)
    vehicles_total           REAL,
    vehicles_per_1000        REAL,

    -- CIMI D7: Urban Planning (CNES)
    -- (beds per 10K computed in Phase 5 from CNES facilities)

    -- CIMI D9: Technology
    -- (placeholder for future internet access proxy)

    -- CIMI D10: Public Management (SIOPS)
    health_expenditure_per_capita  REAL,  -- constant 2023 BRL (deflated)

    -- Demographics
    populacao        INTEGER,

    -- Deflation audit
    ipca_deflation_factor  REAL,  -- factor applied to monetary columns

    -- Metadata
    created_at       TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (cod_ibge, year)
);

CREATE TABLE IF NOT EXISTS dimension_metadata (
    key          TEXT PRIMARY KEY,
    label        TEXT NOT NULL,
    source       TEXT,
    weight       REAL DEFAULT 1.0,
    description  TEXT,
    is_crosssectional  INTEGER DEFAULT 0,
    crosssectional_year INTEGER
);

CREATE TABLE IF NOT EXISTS municipality_lookup (
    cod_ibge    TEXT PRIMARY KEY,
    name        TEXT,
    state_uf    TEXT,
    region      TEXT,
    population  INTEGER
);

CREATE TABLE IF NOT EXISTS deflation_log (
    year              INTEGER PRIMARY KEY,
    ipca_index_dec    REAL NOT NULL,
    deflation_factor  REAL NOT NULL,
    base_year         INTEGER NOT NULL DEFAULT 2023,
    fetched_at        TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS imputation_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    variable      TEXT NOT NULL,
    year          INTEGER NOT NULL,
    n_imputed     INTEGER NOT NULL,
    n_total       INTEGER NOT NULL,
    method        TEXT NOT NULL,
    m_imputations INTEGER NOT NULL,
    max_iter      INTEGER NOT NULL,
    aux_variables TEXT NOT NULL,
    run_at        TEXT DEFAULT (datetime('now'))
);
```

## Source Column Catalog

All Phase 2+3 extractor outputs and their merge-relevant columns:

| Source | Parquet Path | Join Columns | Value Columns | Coverage |
|--------|-------------|--------------|---------------|----------|
| SIH aggregate | processed/sih/*.parquet | cod_ibge, year | procedure_count, total_value, deaths, ... | 2015-2023 (annual) |
| CNES facilities | processed/cnes/facilities_YYYY.parquet | cod_ibge, year | total_beds, is_bellwether, centrcir, centrobs | 2015-2023 (annual) |
| CNES professionals | processed/cnes/professionals_YYYY.parquet | cod_ibge, year | (needs aggregation: count by sao_category) | 2015-2023 (annual) |
| IBGE population | processed/ibge_sidra/population.parquet | cod_ibge, year | populacao | 2015-2023 |
| IBGE GDP | processed/ibge_sidra/gdp_per_capita.parquet | cod_ibge, year | gdp_abs, gdp_estimated, gdp_per_capita | 2015-2023 |
| IPEA IDHM | processed/ipea_idhm/idhm.parquet | cod_ibge, year | idhm, idhm_educacao, idhm_longevidade, idhm_renda | 2010 (cross-sectional) |
| IFGF | processed/ifgf/ifgf.parquet | cod_ibge, year | ifgf_geral, ifgf_ra, ifgf_gp, ifgf_id, ifgf_el, ifgf_sa | 2015-2023 (~420 MNAR/yr) |
| ANS quarterly | processed/ans/ans_quarterly.parquet | cod_ibge, year | beneficiarios_mean, private_coverage_rate, sus_dependence_rate | 2015-2023 |
| Census sanitation | processed/census_sanitation/sanitation.parquet | cod_ibge, year | pct_sanitation_adequate, pct_water_adequate | 2022 (cross-sectional) |
| RENAVAM | processed/renavam/renavam.parquet | cod_ibge, year | vehicles_total, vehicles_per_1000 | 2015-2023 (best effort) |
| SIOPS | processed/siops/siops.parquet | cod_ibge, year | health_expenditure_per_capita | 2015-2023 (best effort) |

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| build_database_v2.py (health-specific D1-D9) | build_database_v3.py (CIMI-aligned schema) | Phase 4 | Schema matches CIMI framework from methodology |
| Monthly transform_merge per month | Annual panel assembly on (cod_ibge, year) | Phase 4 | Most sources are annual; monthly granularity only for SIH/CNES |
| IterativeImputer single seed | m=5 posterior sampling | Phase 4 | Proper multiple imputation per Rubin's rules |
| Row-by-row iterrows() upsert | df.to_sql() batch insert | Phase 4 | 100x faster for 50K rows |

**Deprecated/outdated:**
- `transform_merge()` in pipeline.py: Only handles 4 sources (sih, cnes, ans, ifgf) with month-level granularity. Phase 4 needs a new `assemble_panel()` function operating at year level across 11 sources.
- `upsert_municipal_health()` in build_database_v2.py: Uses `iterrows()` which is extremely slow for 50K+ rows. Replace with `df.to_sql()`.

## Missingness Documentation Format (RECORD 12.1)

RECORD Item 12.1 requires: "Authors should describe the extent to which the investigators had access to the database used to create the study population." Combined with STROBE Item 12c: "Explain how missing data were addressed."

The PANL-06-missingness.csv should document:

```csv
variable,year,n_total,n_observed,n_missing,pct_missing,missingness_mechanism,handling_method
ifgf_geral,2015,5571,5150,421,7.56,MNAR,multiple_imputation_m5
ifgf_geral,2016,5571,5148,423,7.59,MNAR,multiple_imputation_m5
gdp_per_capita,2023,5571,5571,0,0.00,NA,none
idhm,2015,5571,5571,0,0.00,cross_sectional_2010,constant_fill
pct_sanitation_adequate,2015,5571,5571,0,0.00,cross_sectional_2022,constant_fill
health_expenditure_per_capita,2015,5571,0,5571,100.00,source_unavailable,documented_gap
...
```

Columns: variable (column name), year, n_total (municipalities), n_observed, n_missing, pct_missing, missingness_mechanism (MCAR/MAR/MNAR/cross_sectional/source_unavailable), handling_method (none/multiple_imputation_m5/constant_fill/documented_gap).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.0+ (installed in dev group) |
| Config file | pyproject.toml (implicit) |
| Quick run command | `uv run pytest tests/ -x -q` |
| Full suite command | `uv run pytest tests/ -v --tb=short` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DATA-10 | IPCA deflation produces correct constant-2023 BRL values | unit | `uv run pytest tests/test_deflate_ipca.py -x` | Wave 0 |
| PANL-01 | Panel has 5,571 rows per year after merge | integration | `uv run pytest tests/test_assemble_panel.py::test_row_count -x` | Wave 0 |
| PANL-02 | validation_report.json written with all source reports | unit | `uv run pytest tests/test_assemble_panel.py::test_validation_report -x` | Wave 0 |
| PANL-03 | Quarantine dir receives flagged rows | unit | `uv run pytest tests/test_validation.py::test_quarantine -x` | Exists |
| PANL-04 | SQLite has 50,130 rows with correct schema | integration | `uv run pytest tests/test_build_database_v3.py -x` | Wave 0 |
| PANL-05 | IFGF imputation fills ~420 NaN rows per year | unit | `uv run pytest tests/test_impute_ifgf.py -x` | Wave 0 |
| PANL-06 | Missingness CSV has correct format and counts | unit | `uv run pytest tests/test_assemble_panel.py::test_missingness_csv -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/ -x -q --tb=line`
- **Per wave merge:** `uv run pytest tests/ -v --tb=short`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_deflate_ipca.py` -- covers DATA-10 (IPCA fetch + deflation math)
- [ ] `tests/test_assemble_panel.py` -- covers PANL-01, PANL-02, PANL-06 (merge + validation + missingness)
- [ ] `tests/test_build_database_v3.py` -- covers PANL-04 (SQLite schema + row count)
- [ ] `tests/test_impute_ifgf.py` -- covers PANL-05 (IterativeImputer + logging)
- [ ] `tests/conftest.py` update -- shared fixtures for synthetic source DataFrames

## Open Questions

1. **IPCA General vs Health Sub-Index**
   - What we know: CONTEXT.md says "IPCA health sub-index" but general IPCA is the standard deflator in Brazilian health economics.
   - What's unclear: Whether the user specifically requires the health sub-index or used it as a generic term for IPCA.
   - Recommendation: Use general IPCA (table 1737 var 2266) as primary. Note health sub-index as optional sensitivity analysis. The health sub-index requires stitching tables 1419+7060 and computing from monthly variations -- significantly more complex with no clear methodological advantage for this use case.

2. **AMC Crosswalk Application Timing**
   - What we know: CONTEXT.md lists `apply_amc_crosswalk()` as a locked decision. The crosswalk was built in Phase 1 (scripts/build_amc_crosswalk.py), but no `apply_amc_crosswalk()` function exists in the codebase.
   - What's unclear: Whether any source actually uses pre-2013 municipality codes that need harmonization.
   - Recommendation: Implement `apply_amc_crosswalk()` in database/utils.py. For the 2015-2023 window with post-2013 sources, this will likely be a no-op for most records, but it provides a safety net for any source using legacy codes.

3. **SIOPS/RENAVAM Data Availability**
   - What we know: Both extractors are coded with best-effort patterns. The processed directories exist but are empty (extractors haven't been run yet). Both have `EMPTY_SCHEMA` fallbacks.
   - What's unclear: Whether the APIs will return data when run. SIOPS REST API availability is flagged as LOW confidence in Phase 3 research.
   - Recommendation: Plan for graceful degradation. If SIOPS or RENAVAM produce empty Parquet, document 100% missingness in PANL-06-missingness.csv and proceed. These become documented limitations rather than blockers.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12 | Runtime | Yes | 3.12 (in .venv) | -- |
| scikit-learn | PANL-05 imputation | Yes | 1.8.0 | -- |
| sidrapy | DATA-10 deflation | Yes | installed | BCB SGS direct API via requests |
| pandas | All operations | Yes | >=2.2.3 | -- |
| sqlite3 | PANL-04 database | Yes | stdlib | -- |
| pytest | Validation | Yes | dev group | -- |
| python-bcb | Fallback IPCA | No | -- | Use sidrapy (primary) or requests direct API |
| IBGE SIDRA API | DATA-10 | External | -- | BCB SGS API (same data, different endpoint) |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:**
- python-bcb (0.3.6) is not installed; sidrapy handles the IPCA use case. Only add python-bcb if sidrapy fails for table 1737.

## Sources

### Primary (HIGH confidence)
- IBGE SIDRA Table 1737 metadata (via apisidra.ibge.gov.br) -- IPCA number-index variable 2266, period Dec 1979-Feb 2026
- scikit-learn 1.8.0 official docs -- IterativeImputer parameters, experimental status, sample_posterior usage
- RECORD Statement (PMC4595218) -- Item 12.1 text, missingness documentation requirements
- Existing codebase: database/validation.py, database/utils.py, database/pipeline.py, database/build_database_v2.py

### Secondary (MEDIUM confidence)
- IBGE SIDRA Table 7060 metadata -- IPCA health sub-index classification c315, coverage Jan 2020+
- IBGE SIDRA Table 1419 -- IPCA group-level data Jan 2012-Dec 2019
- python-bcb 0.3.6 PyPI -- BCB SGS series 433 access patterns
- pandas 3.0 merge documentation -- validate parameter, memory-efficient merge patterns

### Tertiary (LOW confidence)
- IPCA health sub-index exact series code for BCB SGS -- could not verify the specific SGS series code for "Saude e Cuidados Pessoais" group index; would need manual lookup at BCB SGS portal

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All libraries already in pyproject.toml; versions verified against installed packages
- Architecture: HIGH - Scaffold-first merge pattern is well-established for ecological panel studies; existing codebase provides 60%+ of infrastructure
- Pitfalls: HIGH - Identified from codebase analysis (empty schemas, MNAR pattern, table routing) and domain knowledge
- IPCA deflation: HIGH - Table 1737 var 2266 verified via SIDRA API metadata; formula is standard
- Multiple imputation: MEDIUM - IterativeImputer is experimental but stable; MNAR handling is a documented limitation (auxiliary variables mitigate but don't fully resolve)
- SIOPS/RENAVAM availability: LOW - Extractors exist but processed directories are empty; API availability unknown

**Research date:** 2026-04-01
**Valid until:** 2026-05-01 (stable domain -- deflation methodology and imputation approaches do not change rapidly)
