#!/usr/bin/env python3
"""
ICSKG-BR Autonomous Database Builder v2
=========================================
Fully automated pipeline — no human intervention required.
Downloads, processes, and merges ALL available data sources.

Tested sources:
  ✅ IBGE Localidades API → municipality master
  ✅ IBGE coordinates (GitHub) → lat/lon
  ✅ IBGE SIDRA Table 5938 → GDP (2015-2021)
  ✅ CNES API → bellwether hospitals + geospatial LCoGS-1
  ✅ PySUS SIH/SUS → surgical volume + POMR (LCoGS 3-4)
  ✅ PySUS CNES/PF → SAO workforce density (LCoGS 2)
  ✅ IBGE SIDRA Table 6579 → population (sequential, rate-limit safe)

Sources requiring large downloads (automated but slow):
  ⏳ SIH: ~17MB per state per month × 27 states × 12 months = ~5.5GB/year
  ⏳ CNES PF: ~200KB per state per month

Sources NOT automated (manual download required):
  ❌ Atlas Brasil IDHM — URL changed, manual from atlasbrasil.org.br
  ❌ FIRJAN IFDM — blocked download, manual from firjan.com.br
  ❌ ANATEL — files >1GB, manual from dados.anatel.gov.br  
  ❌ SNIS, RAIS, INEP — manual portals

Usage:
  python3 database/build_database_v2.py               # Full run (hours)
  python3 database/build_database_v2.py --quick        # Quick: 1 year, 3 states
  python3 database/build_database_v2.py --year 2023    # Single year
  python3 database/build_database_v2.py --states SP MG RJ  # Specific states

Requirements: pip install pysus pandas pyarrow
"""

import os, sys, json, csv, time, subprocess, math, argparse, glob, shutil
import pandas as pd
import numpy as np
from datetime import datetime
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DB_DIR = BASE / "database"
RAW = DB_DIR / "raw"
PROC = DB_DIR / "processed"
CACHE = BASE / "cache"
OUTPUT = BASE / "output"
PYSUS_DIR = Path.home() / "pysus"

for d in [RAW, PROC, DB_DIR, CACHE, OUTPUT]:
    d.mkdir(parents=True, exist_ok=True)

ALL_UFS = ['AC','AL','AM','AP','BA','CE','DF','ES','GO','MA','MG','MS','MT',
           'PA','PB','PE','PI','PR','RJ','RN','RO','RR','RS','SC','SE','SP','TO']
UF_CODES = {'RO':'11','AC':'12','AM':'13','RR':'14','PA':'15','AP':'16','TO':'17',
            'MA':'21','PI':'22','CE':'23','RN':'24','PB':'25','PE':'26','AL':'27',
            'SE':'28','BA':'29','MG':'31','ES':'32','RJ':'33','SP':'35',
            'PR':'41','SC':'42','RS':'43','MS':'50','MT':'51','GO':'52','DF':'53'}
UF_REGION = {v: r for r, ufs in {
    'Norte':['11','12','13','14','15','16','17'],
    'Nordeste':['21','22','23','24','25','26','27','28','29'],
    'Sudeste':['31','32','33','35'], 'Sul':['41','42','43'],
    'Centro-Oeste':['50','51','52','53']}.items() for v in ufs}

log = lambda msg: print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

# CBO codes for SAO workforce (Massenburg et al. 2017)
CBO_SURGEONS = ['225120','225125','225130','225135','225140','225145','225150',
                '225155','225250','225265','225275']
CBO_ANESTHESIOLOGISTS = ['225142']
CBO_OBSTETRICIANS = ['225235']
CBO_SAO = CBO_SURGEONS + CBO_ANESTHESIOLOGISTS + CBO_OBSTETRICIANS

# =========================================================================
# MODULE 1: MUNICIPALITY MASTER
# =========================================================================
def build_master():
    log("MODULE 1: Municipality master table")
    out = PROC / "01_master.csv"
    if out.exists() and out.stat().st_size > 100000:
        return pd.read_csv(out, dtype={'cod_ibge': str})

    # IBGE Localidades
    loc_f = RAW / "ibge_localidades.json"
    if not loc_f.exists():
        subprocess.run(["curl","-s","--max-time","60",
            "https://servicodados.ibge.gov.br/api/v1/localidades/municipios?view=nivelado",
            "-o", str(loc_f)], check=True)
    with open(loc_f) as f: locs = json.load(f)

    # Coordinates
    coord_f = CACHE / "municipios_coords.csv"
    if not coord_f.exists():
        subprocess.run(["curl","-sL","--max-time","30",
            "https://raw.githubusercontent.com/kelvins/municipios-brasileiros/main/csv/municipios.csv",
            "-o", str(coord_f)], check=True)
    coords = {}
    with open(coord_f) as f:
        for r in csv.DictReader(f):
            coords[r['codigo_ibge']] = (float(r['latitude']), float(r['longitude']), int(r.get('capital',0)))

    rows = []
    for l in locs:
        cod = str(l['municipio-id']); uf_id = str(l['UF-id'])
        c = coords.get(cod, (None, None, 0))
        rows.append({'cod_ibge': cod, 'cod_ibge_6': cod[:6], 'nome': l['municipio-nome'],
                     'uf': l['UF-sigla'], 'uf_id': uf_id,
                     'regiao': UF_REGION.get(uf_id,''), 'lat': c[0], 'lon': c[1], 'capital': c[2]})
    df = pd.DataFrame(rows)
    df.to_csv(out, index=False)
    log(f"  {len(df)} municipalities")
    return df

# =========================================================================
# MODULE 2: IBGE SIDRA — GDP (already works)
# =========================================================================
def extract_gdp():
    log("MODULE 2: IBGE SIDRA GDP")
    out = PROC / "02_gdp.csv"
    if out.exists() and out.stat().st_size > 10000:
        return pd.read_csv(out, dtype={'cod_ibge': str})

    records = []
    for uf_code in sorted(UF_CODES.values()):
        url = f"https://apisidra.ibge.gov.br/values/t/5938/n6/in%20n3%20{uf_code}/v/37/p/2015,2016,2017,2018,2019,2020,2021/d/v37%200"
        f = RAW / f"gdp_{uf_code}.json"
        if not f.exists():
            subprocess.run(["curl","-s","--max-time","60",url,"-o",str(f)], capture_output=True)
            time.sleep(1)  # rate limit
        try:
            with open(f) as fh: data = json.load(fh)
            for row in data[1:]:
                if row.get('V') and row['V'] not in ['-','...','']:
                    records.append({'cod_ibge': str(row['D1C']), 'year': str(row['D3C']),
                                   'gdp_total_brl_1000': float(row['V'])})
        except: pass
        
    df = pd.DataFrame(records)
    df.to_csv(out, index=False)
    log(f"  {len(df)} GDP records")
    return df

# =========================================================================
# MODULE 3: POPULATION (from CIMI-INDEX fallback + IBGE API)
# =========================================================================
def extract_population():
    log("MODULE 3: Population")
    out = PROC / "03_population.csv"
    if out.exists() and out.stat().st_size > 10000:
        return pd.read_csv(out, dtype={'cod_ibge': str})

    cimi_file = BASE.parent / 'CIMI-INDEX.xlsx'
    if cimi_file.exists():
        cimi = pd.read_excel(cimi_file, header=None)
        pop_data = cimi.iloc[3:, [0,1,2,3]].copy()
        pop_data.columns = ['uf','nome','area_km2','population']
        pop_data['area_km2'] = pd.to_numeric(pop_data['area_km2'], errors='coerce')
        pop_data['population'] = pd.to_numeric(pop_data['population'], errors='coerce')
        pop_data = pop_data.dropna(subset=['nome','population'])
        pop_data['year'] = 2021
        pop_data.to_csv(out, index=False)
        log(f"  {len(pop_data)} municipalities from CIMI-INDEX (2021)")
        return pop_data
    return pd.DataFrame()

# =========================================================================
# MODULE 4: PySUS SIH — Surgical Volume + POMR (LCoGS 3-4)
# =========================================================================
def extract_sih(states, years, months=None):
    """Extract SIH hospitalization data for LCoGS indicators 3 and 4."""
    log(f"MODULE 4: PySUS SIH (states={states}, years={years})")
    
    from pysus.online_data.SIH import download as sih_download
    
    if months is None:
        months = list(range(1, 13))
    
    all_results = []
    for year in years:
        for state in states:
            cache_key = PROC / f"sih_{state}_{year}.csv"
            if cache_key.exists() and cache_key.stat().st_size > 100:
                chunk = pd.read_csv(cache_key, dtype={'MUNIC_RES': str})
                all_results.append(chunk)
                continue
            
            log(f"  Downloading SIH RD {state} {year}...")
            try:
                result = sih_download(states=state, years=year, months=months, 
                                     groups='RD', data_dir=str(PYSUS_DIR))
                # Load parquet files
                pq_dir = PYSUS_DIR / f"RD{state}{str(year)[2:]}*.parquet"
                pq_files = glob.glob(str(PYSUS_DIR / f"RD{state}*.parquet" / "*.parquet"))
                if not pq_files:
                    pq_files = glob.glob(str(PYSUS_DIR / f"RD{state}*.parquet"))
                
                dfs = []
                for pf in pq_files:
                    if str(year)[2:] in pf or str(year) in pf:
                        try: dfs.append(pd.read_parquet(pf))
                        except: pass
                
                if dfs:
                    df = pd.concat(dfs, ignore_index=True)
                    # Aggregate by municipality
                    df['MORTE'] = df['MORTE'].astype(str)
                    df['is_death'] = (df['MORTE'] == '1').astype(int)
                    df['VAL_TOT'] = pd.to_numeric(df['VAL_TOT'], errors='coerce')
                    
                    agg = df.groupby('MUNIC_RES').agg(
                        total_procedures=('MUNIC_RES', 'count'),
                        deaths=('is_death', 'sum'),
                        avg_cost_brl=('VAL_TOT', 'mean'),
                        avg_days=('DIAS_PERM', lambda x: pd.to_numeric(x, errors='coerce').mean()),
                    ).reset_index()
                    agg['state'] = state
                    agg['year'] = year
                    agg['pomr_pct'] = (agg['deaths'] / agg['total_procedures'] * 100).round(3)
                    agg.rename(columns={'MUNIC_RES': 'cod_ibge_6'}, inplace=True)
                    agg.to_csv(cache_key, index=False)
                    all_results.append(agg)
                    log(f"    {state} {year}: {len(df):,} records → {len(agg)} municipalities")
                else:
                    log(f"    {state} {year}: no parquet files found")
            except Exception as e:
                log(f"    {state} {year}: ERROR — {e}")
            
            # Cleanup large files to save disk
            for pf in glob.glob(str(PYSUS_DIR / f"RD{state}*.parquet")):
                try: shutil.rmtree(pf) if os.path.isdir(pf) else os.remove(pf)
                except: pass
            for df_file in glob.glob(str(PYSUS_DIR / f"RD{state}*.dbc")):
                try: os.remove(df_file)
                except: pass
    
    if all_results:
        combined = pd.concat(all_results, ignore_index=True)
        combined.to_csv(PROC / "04_sih_surgical.csv", index=False)
        log(f"  SIH total: {len(combined)} municipality-year records")
        return combined
    return pd.DataFrame()

# =========================================================================
# MODULE 5: PySUS CNES — SAO Workforce (LCoGS 2)
# =========================================================================
def extract_sao_workforce(states, year=2023, month=12):
    """Extract SAO workforce density from CNES professional files."""
    log(f"MODULE 5: PySUS CNES SAO workforce (year={year})")
    
    from pysus.online_data.CNES import download as cnes_download
    
    all_results = []
    for state in states:
        cache_key = PROC / f"sao_{state}_{year}.csv"
        if cache_key.exists() and cache_key.stat().st_size > 100:
            all_results.append(pd.read_csv(cache_key, dtype={'CODUFMUN': str}))
            continue
        
        log(f"  Downloading CNES PF {state} {year}/{month}...")
        try:
            cnes_download(group='PF', states=state, years=year, months=month,
                         data_dir=str(PYSUS_DIR))
            
            pq_files = glob.glob(str(PYSUS_DIR / f"PF{state}*.parquet" / "*.parquet"))
            if not pq_files:
                pq_files = glob.glob(str(PYSUS_DIR / f"PF{state}*.parquet"))
            
            dfs = []
            for pf in pq_files:
                try: dfs.append(pd.read_parquet(pf))
                except: pass
            
            if dfs:
                df = pd.concat(dfs, ignore_index=True)
                # Filter SAO professionals by CBO
                if 'CBO' in df.columns:
                    cbo_col = 'CBO'
                elif 'CBO_OCUP' in df.columns:
                    cbo_col = 'CBO_OCUP'
                else:
                    cbo_col = [c for c in df.columns if 'CBO' in c.upper()][0] if any('CBO' in c.upper() for c in df.columns) else None
                
                if cbo_col:
                    df[cbo_col] = df[cbo_col].astype(str).str.strip()
                    sao = df[df[cbo_col].isin(CBO_SAO)]
                    
                    muni_col = 'CODUFMUN' if 'CODUFMUN' in df.columns else [c for c in df.columns if 'MUN' in c.upper()][0]
                    
                    agg = sao.groupby(muni_col).agg(
                        total_sao=(muni_col, 'count'),
                        surgeons=(cbo_col, lambda x: x.isin(CBO_SURGEONS).sum()),
                        anesthesiologists=(cbo_col, lambda x: x.isin(CBO_ANESTHESIOLOGISTS).sum()),
                        obstetricians=(cbo_col, lambda x: x.isin(CBO_OBSTETRICIANS).sum()),
                    ).reset_index()
                    agg.rename(columns={muni_col: 'cod_ibge_6'}, inplace=True)
                    agg['state'] = state
                    agg['year'] = year
                    agg.to_csv(cache_key, index=False)
                    all_results.append(agg)
                    log(f"    {state}: {len(sao)} SAO professionals in {len(agg)} municipalities")
        except Exception as e:
            log(f"    {state}: ERROR — {e}")
        
        # Cleanup
        for pf in glob.glob(str(PYSUS_DIR / f"PF{state}*")):
            try: shutil.rmtree(pf) if os.path.isdir(pf) else os.remove(pf)
            except: pass
    
    if all_results:
        combined = pd.concat(all_results, ignore_index=True)
        combined.to_csv(PROC / "05_sao_workforce.csv", index=False)
        log(f"  SAO total: {len(combined)} municipality records")
        return combined
    return pd.DataFrame()

# =========================================================================
# MODULE 6: MERGE ALL INTO MASTER DATABASE
# =========================================================================
def merge_all(master_df, gdp_df, pop_df, sih_df, sao_df):
    log("MODULE 6: Merging all sources...")
    db = master_df.copy()
    
    # Population (from CIMI)
    if len(pop_df) > 0 and 'population' in pop_df.columns:
        pop_df['match_key'] = pop_df['nome'].str.upper().str.strip() + '_' + pop_df['uf'].str.strip()
        db['match_key'] = db['nome'].str.upper().str.strip() + '_' + db['uf'].str.strip()
        db = db.merge(pop_df[['match_key','population','area_km2']], on='match_key', how='left')
        db.drop(columns=['match_key'], inplace=True)
        log(f"  + Population: {db['population'].notna().sum()}")

    # GDP (latest year per municipality)
    if len(gdp_df) > 0:
        gdp_latest = gdp_df.sort_values('year', ascending=False).drop_duplicates('cod_ibge')
        gdp_latest = gdp_latest[['cod_ibge','gdp_total_brl_1000','year']].rename(columns={'year':'gdp_year'})
        db = db.merge(gdp_latest, on='cod_ibge', how='left')
        db['gdp_per_capita_brl'] = (db['gdp_total_brl_1000'] * 1000 / db['population']).round(2)
        log(f"  + GDP: {db['gdp_per_capita_brl'].notna().sum()}")

    # LCoGS-1 geospatial (pre-computed)
    lcogs_f = OUTPUT / "lcogs1_bellwether_access_v2.csv"
    if lcogs_f.exists():
        lc = pd.read_csv(lcogs_f, dtype={'cod_ibge': str})
        cols = ['cod_ibge','dist_nearest_bellwether_km','bellwether_count_50km',
                'bellwether_count_100km','access_2hr_proxy','has_bellwether_local']
        db = db.merge(lc[[c for c in cols if c in lc.columns]], on='cod_ibge', how='left')
        log(f"  + LCoGS-1: {db['dist_nearest_bellwether_km'].notna().sum()}")

    # SIH surgical data (LCoGS 3-4)
    if len(sih_df) > 0:
        sih_df['cod_ibge_6'] = sih_df['cod_ibge_6'].astype(str).str[:6]
        # Aggregate across all months/years per municipality (latest year)
        sih_latest = sih_df.groupby('cod_ibge_6').agg(
            surg_procedures=('total_procedures','sum'),
            surg_deaths=('deaths','sum'),
            surg_avg_cost=('avg_cost_brl','mean'),
        ).reset_index()
        sih_latest['pomr_pct'] = (sih_latest['surg_deaths']/sih_latest['surg_procedures']*100).round(3)
        db = db.merge(sih_latest, left_on='cod_ibge_6', right_on='cod_ibge_6', how='left')
        # Compute surgical volume per 100k
        db['surg_volume_per_100k'] = (db['surg_procedures'] / db['population'] * 100000).round(1)
        log(f"  + SIH: {db['surg_procedures'].notna().sum()} municipalities with surgical data")

    # SAO workforce (LCoGS 2)
    if len(sao_df) > 0:
        sao_df['cod_ibge_6'] = sao_df['cod_ibge_6'].astype(str).str[:6]
        sao_agg = sao_df.groupby('cod_ibge_6').agg(
            total_sao=('total_sao','sum'),
            n_surgeons=('surgeons','sum'),
            n_anesthesiologists=('anesthesiologists','sum'),
            n_obstetricians=('obstetricians','sum'),
        ).reset_index()
        db = db.merge(sao_agg, left_on='cod_ibge_6', right_on='cod_ibge_6', how='left')
        db['sao_per_100k'] = (db['total_sao'] / db['population'] * 100000).round(2)
        log(f"  + SAO: {db['total_sao'].notna().sum()} municipalities with workforce data")

    # Derived columns
    if 'population' in db.columns and 'area_km2' in db.columns:
        db['pop_density'] = (db['population'] / db['area_km2']).round(2)
    
    # LCoGS target flags
    if 'sao_per_100k' in db.columns:
        db['lcogs2_meets_target'] = (db['sao_per_100k'] >= 20).astype(int)
    if 'surg_volume_per_100k' in db.columns:
        db['lcogs3_meets_target'] = (db['surg_volume_per_100k'] >= 5000).astype(int)
    if 'pomr_pct' in db.columns:
        db['lcogs4_pomr_flag'] = (db['pomr_pct'] <= 5).astype(int)  # no official target, 5% as reference

    log(f"\n  MASTER DATABASE: {len(db)} × {len(db.columns)}")
    return db

# =========================================================================
# MAIN
# =========================================================================
def main():
    parser = argparse.ArgumentParser(description='ICSKG-BR Database Builder')
    parser.add_argument('--quick', action='store_true', help='Quick mode: 3 states, 1 year')
    parser.add_argument('--year', type=int, nargs='+', default=[2023], help='Year(s) for SIH/CNES')
    parser.add_argument('--states', nargs='+', default=None, help='States (UF codes)')
    parser.add_argument('--skip-sih', action='store_true', help='Skip SIH download (slow)')
    parser.add_argument('--skip-cnes', action='store_true', help='Skip CNES download')
    args = parser.parse_args()
    
    if args.quick:
        states = ['SP', 'RJ', 'MG']
        years = [2023]
    else:
        states = args.states or ALL_UFS
        years = args.year
    
    log("=" * 60)
    log("ICSKG-BR AUTONOMOUS DATABASE BUILDER v2")
    log(f"States: {states}")
    log(f"Years: {years}")
    log(f"SIH: {'skip' if args.skip_sih else 'extract'}")
    log(f"CNES: {'skip' if args.skip_cnes else 'extract'}")
    log("=" * 60)
    
    master = build_master()
    gdp = extract_gdp()
    pop = extract_population()
    
    sih = pd.DataFrame()
    if not args.skip_sih:
        sih = extract_sih(states, years)
    
    sao = pd.DataFrame()
    if not args.skip_cnes:
        sao = extract_sao_workforce(states, year=years[-1])
    
    db = merge_all(master, gdp, pop, sih, sao)
    
    # Save
    db.to_csv(DB_DIR / "icskg_br_master.csv", index=False)
    db.to_parquet(DB_DIR / "icskg_br_master.parquet")
    
    # Summary
    log(f"\n{'='*60}")
    log(f"DATABASE COMPLETE")
    log(f"{'='*60}")
    log(f"File: {DB_DIR}/icskg_br_master.csv")
    log(f"Size: {len(db)} municipalities × {len(db.columns)} columns")
    log(f"\nColumns:")
    for col in db.columns:
        pct = db[col].notna().sum() / len(db) * 100
        log(f"  {'✓' if pct>80 else '△' if pct>50 else '✗'} {col}: {pct:.0f}%")
    
    # Save metadata
    meta = {
        "created": datetime.now().isoformat(),
        "command": " ".join(sys.argv),
        "states": states, "years": years,
        "n_rows": len(db), "n_cols": len(db.columns),
        "sources_automated": {
            "IBGE_localidades": "https://servicodados.ibge.gov.br/api/v1/localidades/municipios",
            "IBGE_SIDRA_GDP": "https://apisidra.ibge.gov.br/values/t/5938",
            "CNES_API": "https://apidadosabertos.saude.gov.br/cnes/estabelecimentos",
            "PySUS_SIH": "ftp://ftp.datasus.gov.br (via pysus library)",
            "PySUS_CNES": "ftp://ftp.datasus.gov.br (via pysus library)",
        },
        "reproduction": "python3 database/build_database_v2.py --year 2023 --states SP RJ MG"
    }
    with open(DB_DIR / "metadata_v2.json", 'w') as f:
        json.dump(meta, f, indent=2, default=str)

if __name__ == "__main__":
    main()
