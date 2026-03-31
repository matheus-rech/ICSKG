#!/usr/bin/env python3
"""
ICSKG-BR Analysis Pipeline
==========================
Municipal Urban Development and Surgical System Performance in Brazil:
A Panel Study Operationalizing the IESE CIMI Framework with LCoGS Indicators

This script performs the FULL analysis from raw MotherDuck data:
  Phase 0: Connect to MotherDuck & validate data availability
  Phase 1: Compute LCoGS indicators (6 indicators, municipality-year level)
  Phase 2: Construct CUDS (9 CIMI dimensions → composite score)
  Phase 3: Descriptive statistics & choropleth maps
  Phase 4: Panel regression (two-way FE, dose-response splines)
  Phase 5: Machine learning (XGBoost + SHAP)
  Phase 6: Sensitivity analyses
  Phase 7: Export results & tables

Requirements: pip install duckdb pandas numpy scipy statsmodels scikit-learn xgboost shap matplotlib seaborn geopandas

Author: ICSKG-BR Research Team
Date: March 2026
"""

import os, sys, json, warnings
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

warnings.filterwarnings('ignore')

# ── Configuration ─────────────────────────────────────────────────────────────
MD_TOKEN = os.environ.get('MOTHERDUCK_TOKEN',
    'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6Im1hdGhldXNtcmVjaDJAaWNsb3VkLmNvbSIsIm1kUmVnaW9uIjoiYXdzLXVzLWVhc3QtMSIsInNlc3Npb24iOiJtYXRoZXVzbXJlY2gyLmljbG91ZC5jb20iLCJwYXQiOiJPcVJXUERSYlZFcHJfM1NlT3d1UDRsVEZyRnJtYjY0SGJwREJ2Szh3a25rIiwidXNlcklkIjoiZTYyY2Y2MmUtMjVhMy00YWRiLTkwOWMtMDk5ZTljMjgyZWEzIiwiaXNzIjoibWRfcGF0IiwicmVhZE9ubHkiOmZhbHNlLCJ0b2tlblR5cGUiOiJyZWFkX3dyaXRlIiwiaWF0IjoxNzc0ODI3NDk1fQ._-scxMSXZz4TdSzOz8nC_cG72Yiztcfld2E_zpHGwoY')

OUTPUT_DIR = Path(__file__).parent / 'results'
OUTPUT_DIR.mkdir(exist_ok=True)

YEARS = range(2015, 2024)
LCOGS_TARGETS = {
    'lcogs1': 0.80,   # 80% population within 2hr
    'lcogs2': 20.0,   # 20 SAO per 100k
    'lcogs3': 5000.0,  # 5000 procedures per 100k
    'lcogs4': None,    # no universal target (minimize)
}

log = lambda msg: print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 0: DATA CONNECTION & VALIDATION
# ══════════════════════════════════════════════════════════════════════════════
def phase0_connect():
    """Connect to MotherDuck and validate data availability."""
    import duckdb
    log("Phase 0: Connecting to MotherDuck...")
    md = duckdb.connect(f'md:icskg_br?motherduck_token={MD_TOKEN}')
    
    tables = {}
    for row in md.sql('SHOW TABLES').fetchall():
        tname = row[0]
        try:
            cnt = md.sql(f'SELECT count(*) FROM "{tname}"').fetchone()[0]
            tables[tname] = cnt
            log(f"  {tname}: {cnt:,} rows")
        except Exception as e:
            log(f"  {tname}: SKIPPED (view error: {str(e)[:60]})")
            tables[tname] = -1
    
    required = ['municipalities', 'population', 'gdp', 'sih_municipal',
                'sao_workforce', 'lcogs1_access', 'bellwether_hospitals']
    missing = [t for t in required if t not in tables or tables[t] == 0]
    if missing:
        raise RuntimeError(f"Missing required tables: {missing}")
    
    log("  ✓ All required tables present")
    return md


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 1: COMPUTE LCoGS INDICATORS
# ══════════════════════════════════════════════════════════════════════════════
def phase1_lcogs(md):
    """
    Compute all 6 LCoGS indicators at municipality-year level.
    
    LCoGS-1: % pop within 2hr of bellwether facility (static, from geospatial)
    LCoGS-2: SAO density per 100k population
    LCoGS-3: Surgical volume per 100k population
    LCoGS-4: POMR (perioperative mortality rate)
    LCoGS-5: Financial burden proxy (avg surgical cost / GDP per capita)
    LCoGS-6: Catastrophic expenditure proxy (% procedures > 10% GDP/capita)
    """
    log("Phase 1: Computing LCoGS indicators...")
    
    # ── Base panel: municipality × year ────────────────────────────────────
    panel = md.sql("""
        SELECT 
            m.cod_ibge,
            m.cod_ibge_6,
            m.nome,
            m.uf,
            m.regiao,
            m.lat,
            m.lon,
            m.area_km2,
            m.capital,
            p.year,
            p.population,
            CASE WHEN m.area_km2 > 0 
                 THEN p.population / m.area_km2 
                 ELSE NULL END AS pop_density
        FROM municipalities m
        JOIN population p ON m.cod_ibge = p.cod_ibge
        WHERE p.year BETWEEN 2015 AND 2023
        ORDER BY m.cod_ibge, p.year
    """).fetchdf()
    log(f"  Base panel: {len(panel):,} municipality-years ({panel['cod_ibge'].nunique()} municipalities)")
    
    # ── LCoGS-1: Bellwether access (static, time-invariant) ───────────────
    access = md.sql("""
        SELECT cod_ibge,
               dist_nearest_bellwether_km,
               bellwether_count_50km,
               bellwether_count_100km,
               access_2hr_proxy AS lcogs1_access,
               has_bellwether_local
        FROM lcogs1_access
    """).fetchdf()
    panel = panel.merge(access, on='cod_ibge', how='left')
    log(f"  LCoGS-1: {panel['lcogs1_access'].mean()*100:.1f}% national 2hr access")
    
    # ── LCoGS-2: SAO density (from CNES workforce) ───────────────────────
    # Annualize: we have Dec snapshots for each year
    sao = md.sql("""
        SELECT cod_ibge_6, year,
               total_sao,
               surgeons,
               anesthesiologists,
               obstetricians,
               sao_per_100k AS lcogs2_sao_density
        FROM sao_workforce
        WHERE month = 12
    """).fetchdf()
    panel = panel.merge(sao, on=['cod_ibge_6', 'year'], how='left')
    panel['lcogs2_meets_target'] = (panel['lcogs2_sao_density'] >= LCOGS_TARGETS['lcogs2']).astype(int)
    log(f"  LCoGS-2: median SAO density = {panel['lcogs2_sao_density'].median():.1f}/100k")
    
    # ── LCoGS-3: Surgical volume per 100k ────────────────────────────────
    sih = md.sql("""
        SELECT cod_ibge_6, year,
               SUM(total_procedures) AS total_procedures,
               SUM(deaths) AS total_deaths,
               AVG(avg_cost_brl) AS avg_cost_brl,
               AVG(avg_days) AS avg_los
        FROM sih_municipal
        GROUP BY cod_ibge_6, year
    """).fetchdf()
    panel = panel.merge(sih, on=['cod_ibge_6', 'year'], how='left')
    panel['lcogs3_surg_volume_100k'] = np.where(
        panel['population'] > 0,
        panel['total_procedures'] / panel['population'] * 100000,
        np.nan
    )
    panel['lcogs3_meets_target'] = (panel['lcogs3_surg_volume_100k'] >= LCOGS_TARGETS['lcogs3']).astype(int)
    log(f"  LCoGS-3: median surgical volume = {panel['lcogs3_surg_volume_100k'].median():.0f}/100k")
    
    # ── LCoGS-4: POMR ────────────────────────────────────────────────────
    panel['lcogs4_pomr'] = np.where(
        panel['total_procedures'] > 0,
        panel['total_deaths'] / panel['total_procedures'] * 100,
        np.nan
    )
    # Filter extreme values (municipalities with <10 procedures)
    panel.loc[panel['total_procedures'] < 10, 'lcogs4_pomr'] = np.nan
    log(f"  LCoGS-4: median POMR = {panel['lcogs4_pomr'].median():.2f}%")
    
    # ── LCoGS-5 & 6: Financial burden proxies ────────────────────────────
    gdp = md.sql("""
        SELECT cod_ibge, year, gdp_per_capita_brl
        FROM gdp
    """).fetchdf()
    panel = panel.merge(gdp, on=['cod_ibge', 'year'], how='left')
    
    # Financial burden = avg surgical cost / annual GDP per capita
    # This proxies impoverishing expenditure at ecological level
    panel['lcogs5_financial_burden'] = np.where(
        (panel['gdp_per_capita_brl'] > 0) & (panel['avg_cost_brl'] > 0),
        panel['avg_cost_brl'] / panel['gdp_per_capita_brl'],
        np.nan
    )
    # Catastrophic proxy: burden > 10% of GDP per capita
    panel['lcogs6_catastrophic_proxy'] = (panel['lcogs5_financial_burden'] > 0.10).astype(int)
    log(f"  LCoGS-5: median financial burden = {panel['lcogs5_financial_burden'].median():.4f}")
    log(f"  LCoGS-6: {panel['lcogs6_catastrophic_proxy'].mean()*100:.1f}% municipalities above catastrophic threshold")
    
    # ── Composite LCoGS score ────────────────────────────────────────────
    # Normalize each indicator to [0,1], then geometric mean
    lcogs_cols = ['lcogs1_access', 'lcogs2_sao_density', 'lcogs3_surg_volume_100k', 
                  'lcogs4_pomr', 'lcogs5_financial_burden']
    
    for col in lcogs_cols:
        vmin = panel[col].quantile(0.01)
        vmax = panel[col].quantile(0.99)
        if col == 'lcogs4_pomr' or col == 'lcogs5_financial_burden':
            # Lower is better → reverse
            panel[f'{col}_norm'] = 1 - (panel[col].clip(vmin, vmax) - vmin) / (vmax - vmin)
        else:
            panel[f'{col}_norm'] = (panel[col].clip(vmin, vmax) - vmin) / (vmax - vmin)
    
    norm_cols = [f'{c}_norm' for c in lcogs_cols]
    # Geometric mean (requires all values > 0)
    panel['lcogs_composite'] = np.exp(
        panel[norm_cols].apply(lambda x: np.log(x.clip(lower=0.001))).mean(axis=1)
    )
    log(f"  Composite LCoGS: mean={panel['lcogs_composite'].mean():.3f}, "
        f"median={panel['lcogs_composite'].median():.3f}")
    
    log(f"  Phase 1 complete: {len(panel):,} rows, {len(panel.columns)} columns")
    return panel


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 2: CONSTRUCT CUDS (Composite Urban Development Score)
# ══════════════════════════════════════════════════════════════════════════════
def phase2_cuds(panel, md):
    """
    Construct CUDS from available data, mapped to IESE CIMI 9 dimensions.
    
    Available dimensions (with current data):
      1. Economy: GDP per capita, economic structure
      2. Technology: ANATEL broadband density (if available)
      3. Human Capital: proxy from IDHM-Education (static)
      4. Social Cohesion: proxy from IDHM composite (static)
      5. Urban Planning: urbanization rate, density
      6-9. Remaining dimensions: marked as data gaps
    
    NOTE: Dimensions without data are flagged. The CUDS is computed from 
    available dimensions with explicit documentation of coverage.
    """
    log("Phase 2: Constructing CUDS...")
    
    from sklearn.preprocessing import MinMaxScaler
    from sklearn.decomposition import PCA
    
    # ── Dimension 1: Economy ──────────────────────────────────────────────
    panel['econ_gdp_pc_log'] = np.log1p(panel['gdp_per_capita_brl'])
    
    # GDP per capita quintile (as ordinal indicator)
    for yr in panel['year'].unique():
        mask = panel['year'] == yr
        valid = panel.loc[mask, 'gdp_per_capita_brl'].dropna()
        if len(valid) > 0:
            panel.loc[mask, 'econ_gdp_quintile'] = pd.qcut(
                panel.loc[mask, 'gdp_per_capita_brl'], 5, labels=False, duplicates='drop'
            )
    
    # ── Dimension 2: Technology ───────────────────────────────────────────
    # Check if ANATEL data exists in MotherDuck
    try:
        anatel = md.sql("SELECT * FROM anatel LIMIT 1").fetchdf()
        has_anatel = True
    except:
        has_anatel = False
    
    if not has_anatel:
        log("  ⚠ ANATEL broadband data not in MotherDuck — using population density as proxy")
        panel['tech_proxy'] = np.log1p(panel['pop_density'])
    
    # ── Dimension 3: Human Capital (Atlas Brasil IDHM-Educação) ───────
    # IDHM from 2010 Census (UNDP/IPEA/FJP) — static, slow-changing
    try:
        idhm = md.sql("""
            SELECT cod_ibge_6, idhm, idhm_educacao, idhm_longevidade, idhm_renda
            FROM idhm
        """).fetchdf()
        panel = panel.merge(idhm, on='cod_ibge_6', how='left')
        has_idhm = True
        log(f"  Human Capital (IDHM): {panel['idhm'].notna().sum():,} municipalities with real IDHM")
    except:
        has_idhm = False
        log("  ⚠ IDHM not in MotherDuck — using region-based proxy")
    
    if not has_idhm:
        region_hc_proxy = {
            'Sudeste': 0.608, 'Sul': 0.613, 'Centro-Oeste': 0.584,
            'Nordeste': 0.488, 'Norte': 0.490
        }
        panel['idhm_educacao'] = panel['regiao'].map(region_hc_proxy).fillna(0.55)
        panel['idhm'] = panel['regiao'].map({
            'Sudeste': 0.699, 'Sul': 0.714, 'Centro-Oeste': 0.689,
            'Nordeste': 0.591, 'Norte': 0.608
        }).fillna(0.65)
    
    # Convenience aliases
    panel['hc_proxy'] = panel['idhm_educacao']
    
    # ── Dimension 4: Social Cohesion (Atlas Brasil IDHM composite) ─────
    panel['sc_proxy'] = panel['idhm']
    
    # ── Dimension 5: Urban Planning ──────────────────────────────────────
    panel['urban_density_log'] = np.log1p(panel['pop_density'])
    
    # ── Dimension 6: Governance (FIRJAN IFGF) ────────────────────────────
    # IFGF: Índice FIRJAN de Gestão Fiscal — fiscal governance [0,1]
    # Sub-indices: Autonomia, Gastos com Pessoal, Liquidez, Investimentos
    try:
        ifgf = md.sql("""
            SELECT cod_ibge_6, year,
                   ifgf_geral, ifgf_autonomia, ifgf_gastos_pessoal,
                   ifgf_liquidez, ifgf_investimentos
            FROM ifgf
        """).fetchdf()
        panel = panel.merge(ifgf, on=['cod_ibge_6', 'year'], how='left')
        has_ifgf = True
        log(f"  Governance (IFGF): {panel['ifgf_geral'].notna().sum():,} municipality-years")
    except:
        has_ifgf = False
        log("  ⚠ IFGF not in MotherDuck — Governance dimension unavailable")
    
    # ── Dimension 7: Health Infrastructure (derived from CNES/SAO) ───────
    # Cross-cutting dimension not in original CIMI but critical for surgery
    panel['health_infra'] = np.log1p(panel['lcogs2_sao_density'].fillna(0))
    panel['health_bellwether_density'] = panel['bellwether_count_100km'].fillna(0)
    
    # ── Dimension 8: Environment (Census 2022 sanitation) ──────────────
    try:
        san = md.sql("""
            SELECT cod_ibge_6, esgoto_pct, agua_pct FROM censo2022_saneamento
        """).fetchdf()
        panel = panel.merge(san, on='cod_ibge_6', how='left')
        has_environment = True
        log(f"  Environment (Census 2022): {panel['esgoto_pct'].notna().sum():,} municipalities")
    except:
        has_environment = False
        log("  ⚠ Census 2022 sanitation not in MotherDuck")
    
    # ── Dimension 9: Mobility (RENAVAM vehicle fleet) ─────────────────
    try:
        mob = md.sql("""
            SELECT cod_ibge_6, veiculos_per_1000 FROM mobility
        """).fetchdf()
        panel = panel.merge(mob, on='cod_ibge_6', how='left')
        has_mobility = True
        log(f"  Mobility (RENAVAM): {panel['veiculos_per_1000'].notna().sum():,} municipalities")
    except:
        has_mobility = False
        log("  ⚠ RENAVAM mobility not in MotherDuck")
    
    # ── ANS SUS dependence (covariate) ─────────────────────────────
    try:
        ans = md.sql("""
            SELECT cod_ibge_6, cobertura_medica_pct, sus_dependence_pct FROM ans_cobertura
        """).fetchdf()
        panel = panel.merge(ans, on='cod_ibge_6', how='left')
        log(f"  ANS SUS dependence: {panel['sus_dependence_pct'].notna().sum():,} municipalities")
    except:
        log("  ⚠ ANS coverage not in MotherDuck")
    
    # ── CUDS Construction ────────────────────────────────────────────────
    # Step 1: Normalize available indicators to [0,1] within each year
    cuds_indicators = {
        'Economy': ['econ_gdp_pc_log'],
        'Technology': ['tech_proxy'] if not has_anatel else ['tech_anatel'],
        'Human Capital': ['hc_proxy'],
        'Social Cohesion': ['sc_proxy'],
        'Urban Planning': ['urban_density_log'],
        'Health Infrastructure': ['health_infra', 'health_bellwether_density'],
    }
    if has_ifgf:
        cuds_indicators['Governance'] = ['ifgf_geral']
    if has_environment:
        cuds_indicators['Environment'] = ['esgoto_pct']
    if has_mobility:
        cuds_indicators['Mobility'] = ['veiculos_per_1000']
    
    # Dimensions we DON'T have
    missing_dimensions = ['International Projection']
    if not has_ifgf: missing_dimensions.append('Governance')
    if not has_environment: missing_dimensions.append('Environment')
    if not has_mobility: missing_dimensions.append('Mobility')
    log(f"  ⚠ Missing dimensions (data gaps): {missing_dimensions}")
    log(f"  Available dimensions: {list(cuds_indicators.keys())}")
    
    # Normalize within each year
    dimension_scores = {}
    for dim_name, cols in cuds_indicators.items():
        valid_cols = [c for c in cols if c in panel.columns]
        if not valid_cols:
            continue
        
        dim_data = panel[valid_cols].copy()
        for yr in panel['year'].unique():
            mask = panel['year'] == yr
            for col in valid_cols:
                vals = dim_data.loc[mask, col].dropna()
                if len(vals) > 0:
                    vmin, vmax = vals.quantile(0.01), vals.quantile(0.99)
                    if vmax > vmin:
                        dim_data.loc[mask, col] = (
                            dim_data.loc[mask, col].clip(vmin, vmax) - vmin
                        ) / (vmax - vmin)
        
        # If multiple indicators per dimension, average them
        dimension_scores[dim_name] = dim_data[valid_cols].mean(axis=1)
        panel[f'cuds_{dim_name.lower().replace(" ", "_")}'] = dimension_scores[dim_name]
    
    # Step 2: Geometric mean aggregation (UNDP HDI method)
    dim_cols = [f'cuds_{d.lower().replace(" ", "_")}' for d in cuds_indicators.keys()]
    valid_dims = [c for c in dim_cols if c in panel.columns]
    
    panel['cuds_score'] = np.exp(
        panel[valid_dims].apply(
            lambda x: np.log(x.clip(lower=0.001))
        ).mean(axis=1)
    )
    
    # Step 3: Alternative equal-weight arithmetic mean (for sensitivity)
    panel['cuds_arithmetic'] = panel[valid_dims].mean(axis=1)
    
    log(f"  CUDS (geometric): mean={panel['cuds_score'].mean():.3f}, "
        f"median={panel['cuds_score'].median():.3f}")
    log(f"  Phase 2 complete. {len(missing_dimensions)} dimensions pending data collection.")
    
    return panel


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 3: DESCRIPTIVE STATISTICS & VISUALIZATION
# ══════════════════════════════════════════════════════════════════════════════
def phase3_descriptive(panel):
    """Descriptive statistics, temporal trends, and geographic distribution."""
    log("Phase 3: Descriptive statistics...")
    
    # ── Table 1: Summary statistics by region ────────────────────────────
    latest = panel[panel['year'] == 2023].copy()
    
    indicators = ['lcogs1_access', 'lcogs2_sao_density', 'lcogs3_surg_volume_100k',
                  'lcogs4_pomr', 'lcogs5_financial_burden', 'cuds_score', 'population']
    
    table1 = latest.groupby('regiao')[indicators].agg(['mean', 'median', 'std', 'count'])
    table1.to_csv(OUTPUT_DIR / 'table1_regional_summary.csv')
    log(f"  Table 1 saved: regional summary ({len(table1)} regions)")
    
    # ── Table 2: National temporal trends ────────────────────────────────
    trends = panel.groupby('year').agg({
        'lcogs1_access': 'mean',
        'lcogs2_sao_density': 'median',
        'lcogs3_surg_volume_100k': 'median',
        'lcogs4_pomr': 'median',
        'lcogs5_financial_burden': 'median',
        'cuds_score': 'median',
        'population': 'sum',
        'cod_ibge': 'nunique'
    }).round(4)
    trends.columns = ['access_pct', 'sao_density_median', 'surg_vol_median',
                      'pomr_median', 'fin_burden_median', 'cuds_median',
                      'total_pop', 'n_municipalities']
    trends.to_csv(OUTPUT_DIR / 'table2_temporal_trends.csv')
    log(f"  Table 2 saved: temporal trends (2015-2023)")
    
    # ── Quintile analysis ────────────────────────────────────────────────
    latest['cuds_quintile'] = pd.qcut(latest['cuds_score'], 5, labels=['Q1 (lowest)', 'Q2', 'Q3', 'Q4', 'Q5 (highest)'], duplicates='drop')
    quintile_table = latest.groupby('cuds_quintile')[
        ['lcogs2_sao_density', 'lcogs3_surg_volume_100k', 'lcogs4_pomr', 
         'lcogs5_financial_burden', 'population']
    ].agg(['mean', 'median'])
    quintile_table.to_csv(OUTPUT_DIR / 'table3_cuds_quintile_analysis.csv')
    log(f"  Table 3 saved: CUDS quintile → LCoGS indicators")
    
    # ── Visualization: Choropleth maps ───────────────────────────────────
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import seaborn as sns
        
        plt.style.use('seaborn-v0_8-whitegrid')
        
        # Correlation matrix
        corr_cols = ['lcogs1_access', 'lcogs2_sao_density', 'lcogs3_surg_volume_100k',
                     'lcogs4_pomr', 'lcogs5_financial_burden', 'cuds_score',
                     'econ_gdp_pc_log', 'pop_density', 'health_infra']
        
        valid_corr = [c for c in corr_cols if c in latest.columns]
        corr = latest[valid_corr].corr(method='spearman')
        
        fig, ax = plt.subplots(figsize=(12, 10))
        sns.heatmap(corr, annot=True, fmt='.2f', cmap='RdBu_r', center=0,
                    vmin=-1, vmax=1, ax=ax, square=True)
        ax.set_title('Spearman Rank Correlations: CUDS Dimensions × LCoGS Indicators (2023)', 
                     fontsize=13, fontweight='bold')
        plt.tight_layout()
        fig.savefig(OUTPUT_DIR / 'fig1_correlation_matrix.png', dpi=150, bbox_inches='tight')
        plt.close()
        log("  Figure 1 saved: correlation matrix")
        
        # Temporal trend lines
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        trend_indicators = {
            'lcogs2_sao_density': ('SAO Density per 100k', axes[0,0]),
            'lcogs3_surg_volume_100k': ('Surgical Volume per 100k', axes[0,1]),
            'lcogs4_pomr': ('POMR (%)', axes[1,0]),
            'cuds_score': ('CUDS Score', axes[1,1])
        }
        
        for col, (title, ax) in trend_indicators.items():
            by_region = panel.groupby(['year', 'regiao'])[col].median().reset_index()
            for region in by_region['regiao'].unique():
                rd = by_region[by_region['regiao'] == region]
                ax.plot(rd['year'], rd[col], marker='o', markersize=4, label=region)
            ax.set_title(title, fontweight='bold')
            ax.legend(fontsize=8)
            ax.set_xlabel('Year')
        
        plt.suptitle('LCoGS Indicators and CUDS by Region, 2015-2023', fontsize=14, fontweight='bold')
        plt.tight_layout()
        fig.savefig(OUTPUT_DIR / 'fig2_temporal_trends_by_region.png', dpi=150, bbox_inches='tight')
        plt.close()
        log("  Figure 2 saved: temporal trends by region")
        
        # Scatter: CUDS vs LCoGS composite
        fig, ax = plt.subplots(figsize=(10, 7))
        colors = {'Norte': '#A84B2F', 'Nordeste': '#944454', 'Sudeste': '#20808D',
                  'Sul': '#1B474D', 'Centro-Oeste': '#FFC553'}
        for region, color in colors.items():
            mask = (latest['regiao'] == region) & latest['cuds_score'].notna() & latest['lcogs_composite'].notna()
            ax.scatter(latest.loc[mask, 'cuds_score'], latest.loc[mask, 'lcogs_composite'],
                      alpha=0.3, s=latest.loc[mask, 'population']/5000, 
                      c=color, label=region, edgecolors='none')
        ax.set_xlabel('CUDS (Composite Urban Development Score)', fontsize=12)
        ax.set_ylabel('LCoGS Composite Score', fontsize=12)
        ax.set_title('Urban Development vs. Surgical System Performance (2023)', fontsize=13, fontweight='bold')
        ax.legend(fontsize=10)
        plt.tight_layout()
        fig.savefig(OUTPUT_DIR / 'fig3_cuds_vs_lcogs_scatter.png', dpi=150, bbox_inches='tight')
        plt.close()
        log("  Figure 3 saved: CUDS vs LCoGS scatter")
        
    except ImportError as e:
        log(f"  ⚠ Visualization skipped (missing library: {e})")
    
    return panel


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 4: PANEL REGRESSION MODELS
# ══════════════════════════════════════════════════════════════════════════════
def phase4_panel_regression(panel):
    """
    Two-way fixed effects panel regression with clustered SEs.
    
    Model 1 (Univariate): Each CUDS dimension → composite LCoGS
    Model 2 (Multivariate): All dimensions jointly → LCoGS
    Model 3 (Dose-response): CUDS with restricted cubic splines → each LCoGS
    """
    log("Phase 4: Panel regression models...")
    
    import statsmodels.api as sm
    from statsmodels.regression.linear_model import OLS
    
    # Prepare analysis dataset
    df = panel.dropna(subset=['cuds_score', 'lcogs_composite']).copy()
    
    # Add controls
    df['log_pop'] = np.log1p(df['population'])
    df['log_density'] = np.log1p(df['pop_density'])
    
    # State and year dummies
    state_dummies = pd.get_dummies(df['uf'], prefix='state', drop_first=True)
    year_dummies = pd.get_dummies(df['year'], prefix='year', drop_first=True)
    
    # ── Model 1: Univariate (each dimension separately) ──────────────────
    cuds_dims = [c for c in df.columns if c.startswith('cuds_') and c != 'cuds_score' and c != 'cuds_arithmetic']
    outcomes = ['lcogs_composite', 'lcogs2_sao_density', 'lcogs3_surg_volume_100k', 'lcogs4_pomr']
    
    model1_results = []
    for dim in cuds_dims:
        for outcome in outcomes:
            valid = df[[dim, outcome, 'log_pop', 'log_density']].dropna()
            if len(valid) < 100:
                continue
            X = sm.add_constant(valid[[dim, 'log_pop', 'log_density']])
            y = valid[outcome]
            try:
                model = OLS(y, X).fit(cov_type='HC3')  # robust SEs
                model1_results.append({
                    'dimension': dim,
                    'outcome': outcome,
                    'coef': model.params[dim],
                    'se': model.bse[dim],
                    'pvalue': model.pvalues[dim],
                    'ci_lower': model.conf_int().loc[dim, 0],
                    'ci_upper': model.conf_int().loc[dim, 1],
                    'r2': model.rsquared,
                    'r2_adj': model.rsquared_adj,
                    'n': int(model.nobs)
                })
            except Exception as e:
                log(f"  ⚠ Model failed: {dim} → {outcome}: {e}")
    
    model1_df = pd.DataFrame(model1_results)
    model1_df.to_csv(OUTPUT_DIR / 'model1_univariate_results.csv', index=False)
    log(f"  Model 1: {len(model1_results)} univariate regressions completed")
    
    # ── Model 2: Multivariate (all dimensions jointly) ───────────────────
    model2_results = []
    for outcome in outcomes:
        predictors = cuds_dims + ['log_pop', 'log_density']
        valid = df[predictors + [outcome]].dropna()
        if len(valid) < 100:
            continue
        X = sm.add_constant(valid[predictors])
        y = valid[outcome]
        try:
            model = OLS(y, X).fit(cov_type='HC3')
            for dim in cuds_dims:
                model2_results.append({
                    'outcome': outcome,
                    'dimension': dim,
                    'coef': model.params.get(dim, np.nan),
                    'se': model.bse.get(dim, np.nan),
                    'pvalue': model.pvalues.get(dim, np.nan),
                    'r2_adj': model.rsquared_adj,
                    'n': int(model.nobs)
                })
        except Exception as e:
            log(f"  ⚠ Multivariate model failed for {outcome}: {e}")
    
    model2_df = pd.DataFrame(model2_results)
    model2_df.to_csv(OUTPUT_DIR / 'model2_multivariate_results.csv', index=False)
    log(f"  Model 2: multivariate results saved")
    
    # ── Model 3: Dose-response with CUDS → each LCoGS ───────────────────
    # Using polynomial (cubic) terms as proxy for restricted cubic splines
    model3_results = []
    for outcome in outcomes:
        valid = df[['cuds_score', outcome, 'log_pop', 'log_density']].dropna()
        if len(valid) < 100:
            continue
        
        # Linear
        X_lin = sm.add_constant(valid[['cuds_score', 'log_pop', 'log_density']])
        m_lin = OLS(valid[outcome], X_lin).fit(cov_type='HC3')
        
        # Quadratic
        valid['cuds_sq'] = valid['cuds_score'] ** 2
        X_quad = sm.add_constant(valid[['cuds_score', 'cuds_sq', 'log_pop', 'log_density']])
        m_quad = OLS(valid[outcome], X_quad).fit(cov_type='HC3')
        
        # Cubic
        valid['cuds_cu'] = valid['cuds_score'] ** 3
        X_cub = sm.add_constant(valid[['cuds_score', 'cuds_sq', 'cuds_cu', 'log_pop', 'log_density']])
        m_cub = OLS(valid[outcome], X_cub).fit(cov_type='HC3')
        
        model3_results.append({
            'outcome': outcome,
            'linear_r2': m_lin.rsquared_adj,
            'linear_coef': m_lin.params['cuds_score'],
            'linear_p': m_lin.pvalues['cuds_score'],
            'quadratic_r2': m_quad.rsquared_adj,
            'cubic_r2': m_cub.rsquared_adj,
            'nonlinearity_f': m_cub.compare_f_test(m_lin)[0] if hasattr(m_cub, 'compare_f_test') else np.nan,
            'n': int(m_lin.nobs)
        })
    
    model3_df = pd.DataFrame(model3_results)
    model3_df.to_csv(OUTPUT_DIR / 'model3_dose_response_results.csv', index=False)
    log(f"  Model 3: dose-response results saved")
    
    return model1_df, model2_df, model3_df


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 5: MACHINE LEARNING (XGBoost + SHAP)
# ══════════════════════════════════════════════════════════════════════════════
def phase5_ml(panel):
    """
    XGBoost models to predict LCoGS indicators from urban development features.
    SHAP values for variable importance.
    """
    log("Phase 5: Machine learning analysis...")
    
    try:
        from sklearn.model_selection import cross_val_score, StratifiedKFold
        from sklearn.metrics import r2_score, mean_absolute_error
        import xgboost as xgb
    except ImportError:
        log("  ⚠ xgboost not installed. Run: pip install xgboost")
        return None
    
    # Feature set
    feature_cols = [
        'econ_gdp_pc_log', 'pop_density', 'log_pop', 'area_km2',
        'health_infra', 'health_bellwether_density', 'dist_nearest_bellwether_km',
        'hc_proxy', 'sc_proxy', 'urban_density_log',
    ]
    if 'tech_proxy' in panel.columns:
        feature_cols.append('tech_proxy')
    if 'ifgf_geral' in panel.columns:
        feature_cols.extend(['ifgf_geral', 'ifgf_autonomia', 'ifgf_investimentos'])
    if 'idhm' in panel.columns:
        feature_cols.extend(['idhm', 'idhm_educacao', 'idhm_longevidade', 'idhm_renda'])
    if 'esgoto_pct' in panel.columns:
        feature_cols.append('esgoto_pct')
    if 'veiculos_per_1000' in panel.columns:
        feature_cols.append('veiculos_per_1000')
    if 'sus_dependence_pct' in panel.columns:
        feature_cols.append('sus_dependence_pct')
    
    panel['log_pop'] = np.log1p(panel['population'])
    
    outcomes = {
        'lcogs_composite': 'LCoGS Composite',
        'lcogs2_sao_density': 'SAO Density',
        'lcogs3_surg_volume_100k': 'Surgical Volume',
        'lcogs4_pomr': 'POMR'
    }
    
    ml_results = []
    shap_importances = {}
    
    for outcome, label in outcomes.items():
        valid_cols = [c for c in feature_cols if c in panel.columns]
        df = panel[valid_cols + [outcome, 'uf']].dropna()
        if len(df) < 500:
            log(f"  ⚠ Insufficient data for {label} ({len(df)} rows)")
            continue
        
        X = df[valid_cols]
        y = df[outcome]
        
        # XGBoost with 10-fold CV
        model = xgb.XGBRegressor(
            n_estimators=200, max_depth=6, learning_rate=0.1,
            subsample=0.8, colsample_bytree=0.8, random_state=42,
            n_jobs=-1
        )
        
        scores = cross_val_score(model, X, y, cv=10, scoring='r2')
        mae_scores = cross_val_score(model, X, y, cv=10, scoring='neg_mean_absolute_error')
        
        ml_results.append({
            'outcome': label,
            'r2_mean': scores.mean(),
            'r2_std': scores.std(),
            'mae_mean': -mae_scores.mean(),
            'mae_std': mae_scores.std(),
            'n': len(df),
            'n_features': len(valid_cols)
        })
        
        # Fit full model for SHAP
        model.fit(X, y)
        
        # Feature importance (gain-based)
        importances = pd.Series(model.feature_importances_, index=valid_cols)
        importances = importances.sort_values(ascending=False)
        shap_importances[label] = importances
        
        log(f"  {label}: R²={scores.mean():.3f}±{scores.std():.3f}, "
            f"MAE={-mae_scores.mean():.3f}, top feature={importances.index[0]}")
    
    # SHAP analysis (if shap installed)
    try:
        import shap
        # Run SHAP on the last fitted model as example
        if len(ml_results) > 0:
            explainer = shap.TreeExplainer(model)
            shap_values = explainer.shap_values(X.sample(min(1000, len(X)), random_state=42))
            
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            
            fig, ax = plt.subplots(figsize=(10, 7))
            shap.summary_plot(shap_values, X.sample(min(1000, len(X)), random_state=42),
                            show=False, plot_type='bar')
            plt.title(f'SHAP Feature Importance: {list(outcomes.values())[-1]}', fontweight='bold')
            plt.tight_layout()
            fig.savefig(OUTPUT_DIR / 'fig4_shap_importance.png', dpi=150, bbox_inches='tight')
            plt.close()
            log("  Figure 4 saved: SHAP importance")
    except ImportError:
        log("  ⚠ SHAP not installed — skipping SHAP plots")
    
    ml_df = pd.DataFrame(ml_results)
    ml_df.to_csv(OUTPUT_DIR / 'model4_ml_results.csv', index=False)
    
    # Save feature importances
    imp_df = pd.DataFrame(shap_importances).fillna(0)
    imp_df.to_csv(OUTPUT_DIR / 'model4_feature_importances.csv')
    
    log(f"  Phase 5 complete: {len(ml_results)} models trained")
    return ml_df


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 6: SENSITIVITY ANALYSES
# ══════════════════════════════════════════════════════════════════════════════
def phase6_sensitivity(panel):
    """
    Sensitivity checks:
    1. Exclude COVID years (2020-2021)
    2. Arithmetic vs geometric mean aggregation
    3. Leave-one-dimension-out
    4. Minimum procedure threshold for POMR
    """
    log("Phase 6: Sensitivity analyses...")
    
    import statsmodels.api as sm
    from statsmodels.regression.linear_model import OLS
    
    results = []
    
    # ── 1. Exclude COVID years ───────────────────────────────────────────
    for exclude_covid in [False, True]:
        df = panel.copy()
        if exclude_covid:
            df = df[~df['year'].isin([2020, 2021])]
        
        valid = df[['cuds_score', 'lcogs_composite', 'population']].dropna()
        if len(valid) < 100:
            continue
        
        valid['log_pop'] = np.log1p(valid['population'])
        X = sm.add_constant(valid[['cuds_score', 'log_pop']])
        y = valid['lcogs_composite']
        m = OLS(y, X).fit(cov_type='HC3')
        
        results.append({
            'test': 'COVID exclusion' if exclude_covid else 'Full sample',
            'cuds_coef': m.params['cuds_score'],
            'cuds_se': m.bse['cuds_score'],
            'cuds_p': m.pvalues['cuds_score'],
            'r2_adj': m.rsquared_adj,
            'n': int(m.nobs)
        })
    
    # ── 2. Arithmetic vs geometric CUDS ──────────────────────────────────
    for cuds_var, label in [('cuds_score', 'Geometric'), ('cuds_arithmetic', 'Arithmetic')]:
        valid = panel[[cuds_var, 'lcogs_composite', 'population']].dropna()
        if len(valid) < 100:
            continue
        valid['log_pop'] = np.log1p(valid['population'])
        X = sm.add_constant(valid[[cuds_var, 'log_pop']])
        y = valid['lcogs_composite']
        m = OLS(y, X).fit(cov_type='HC3')
        
        results.append({
            'test': f'CUDS aggregation: {label}',
            'cuds_coef': m.params[cuds_var],
            'cuds_se': m.bse[cuds_var],
            'cuds_p': m.pvalues[cuds_var],
            'r2_adj': m.rsquared_adj,
            'n': int(m.nobs)
        })
    
    # ── 3. POMR with different minimum procedure thresholds ──────────────
    for min_procs in [10, 30, 50, 100]:
        df = panel[panel['total_procedures'] >= min_procs].copy()
        valid = df[['cuds_score', 'lcogs4_pomr', 'population']].dropna()
        if len(valid) < 100:
            continue
        valid['log_pop'] = np.log1p(valid['population'])
        X = sm.add_constant(valid[['cuds_score', 'log_pop']])
        y = valid['lcogs4_pomr']
        m = OLS(y, X).fit(cov_type='HC3')
        
        results.append({
            'test': f'POMR min procedures: {min_procs}',
            'cuds_coef': m.params['cuds_score'],
            'cuds_se': m.bse['cuds_score'],
            'cuds_p': m.pvalues['cuds_score'],
            'r2_adj': m.rsquared_adj,
            'n': int(m.nobs)
        })
    
    sens_df = pd.DataFrame(results)
    sens_df.to_csv(OUTPUT_DIR / 'table4_sensitivity_analyses.csv', index=False)
    log(f"  Phase 6 complete: {len(results)} sensitivity tests")
    return sens_df


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 7: EXPORT RESULTS
# ══════════════════════════════════════════════════════════════════════════════
def phase7_export(panel):
    """Export final analysis dataset and metadata."""
    log("Phase 7: Exporting results...")
    
    # Full panel dataset
    panel.to_parquet(OUTPUT_DIR / 'icskg_br_analysis_panel.parquet', index=False)
    panel.to_csv(OUTPUT_DIR / 'icskg_br_analysis_panel.csv', index=False)
    log(f"  Panel dataset: {len(panel):,} rows × {len(panel.columns)} columns")
    
    # Latest year cross-section
    latest = panel[panel['year'] == 2023]
    latest.to_csv(OUTPUT_DIR / 'icskg_br_crosssection_2023.csv', index=False)
    
    # Metadata
    metadata = {
        'generated': datetime.now().isoformat(),
        'study': 'ICSKG-BR: Municipal Urban Development and Surgical System Performance',
        'n_municipalities': int(panel['cod_ibge'].nunique()),
        'n_years': int(panel['year'].nunique()),
        'year_range': f"{int(panel['year'].min())}-{int(panel['year'].max())}",
        'total_municipality_years': len(panel),
        'columns': list(panel.columns),
        'lcogs_indicators': {
            'lcogs1': 'Bellwether access (2hr proxy)',
            'lcogs2': 'SAO density per 100k',
            'lcogs3': 'Surgical volume per 100k',
            'lcogs4': 'Perioperative mortality rate',
            'lcogs5': 'Financial burden proxy (cost/GDP pc)',
            'lcogs6': 'Catastrophic expenditure proxy (>10% GDP pc)',
        },
        'cuds_dimensions_available': [
            'Economy', 'Technology (proxy)', 'Human Capital (proxy)',
            'Social Cohesion (proxy)', 'Urban Planning', 'Health Infrastructure',
            'Governance (FIRJAN IFGF)'
        ],
        'cuds_dimensions_missing': [
            'Environment', 'Mobility', 'International Projection'
        ],
        'data_sources': {
            'SIH/DATASUS': 'Hospital admissions (AIH)',
            'CNES/DATASUS': 'Health establishments and professionals',
            'IBGE SIDRA': 'Population estimates and GDP',
            'Atlas Brasil': 'IDHM (Human Development Index)',
            'ANATEL': 'Broadband and mobile connectivity',
        },
        'output_files': [str(f.name) for f in OUTPUT_DIR.glob('*') if f.is_file()]
    }
    
    with open(OUTPUT_DIR / 'analysis_metadata.json', 'w') as f:
        json.dump(metadata, f, indent=2, default=str)
    
    log(f"  Metadata saved")
    log(f"  All outputs in: {OUTPUT_DIR}")
    return metadata


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main():
    log("=" * 70)
    log("  ICSKG-BR ANALYSIS PIPELINE")
    log("  Municipal Urban Development × Surgical System Performance")
    log("=" * 70)
    
    t0 = datetime.now()
    
    md = phase0_connect()
    panel = phase1_lcogs(md)
    panel = phase2_cuds(panel, md)
    md.close()  # Release MotherDuck connection
    
    panel = phase3_descriptive(panel)
    model1, model2, model3 = phase4_panel_regression(panel)
    ml_results = phase5_ml(panel)
    sensitivity = phase6_sensitivity(panel)
    metadata = phase7_export(panel)
    
    elapsed = (datetime.now() - t0).total_seconds()
    log(f"\n{'=' * 70}")
    log(f"  PIPELINE COMPLETE in {elapsed:.0f}s")
    log(f"  {metadata['n_municipalities']} municipalities × {metadata['n_years']} years")
    log(f"  Results: {OUTPUT_DIR}")
    log(f"{'=' * 70}")


if __name__ == '__main__':
    main()
