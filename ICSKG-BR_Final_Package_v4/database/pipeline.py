#!/usr/bin/env python3
"""
ICSKG-BR Autonomous Data Pipeline
===================================
Resilient, resumable pipeline that:
1. Tracks progress in SQLite (never re-downloads completed work)
2. Downloads SIH + CNES from DATASUS via PySUS
3. Extracts IBGE GDP, population, coordinates
4. Computes LCoGS indicators 1-4 per municipality
5. Stores everything in a normalized SQLite database

Usage:
  python3 pipeline.py                    # Full run (all 27 states, 2023)
  python3 pipeline.py --quick            # Test: SP only
  python3 pipeline.py --states SP RJ MG  # Specific states
  python3 pipeline.py --years 2022 2023  # Multiple years
  python3 pipeline.py --status           # Show progress
"""

import os, sys, json, csv, glob, shutil, math, time, argparse, sqlite3, hashlib
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "database" / "icskg_br.db"
PYSUS_DIR = Path.home() / "pysus"
CACHE = ROOT / "cache"
PROC = ROOT / "database" / "processed"
for d in [PYSUS_DIR, CACHE, PROC]: d.mkdir(parents=True, exist_ok=True)

ALL_UFS = ['AC','AL','AM','AP','BA','CE','DF','ES','GO','MA','MG','MS','MT',
           'PA','PB','PE','PI','PR','RJ','RN','RO','RR','RS','SC','SE','SP','TO']
UF_CODES = {'RO':'11','AC':'12','AM':'13','RR':'14','PA':'15','AP':'16','TO':'17',
            'MA':'21','PI':'22','CE':'23','RN':'24','PB':'25','PE':'26','AL':'27',
            'SE':'28','BA':'29','MG':'31','ES':'32','RJ':'33','SP':'35',
            'PR':'41','SC':'42','RS':'43','MS':'50','MT':'51','GO':'52','DF':'53'}
UF_REGION = {}
for r, codes in {'Norte':['11','12','13','14','15','16','17'],
    'Nordeste':['21','22','23','24','25','26','27','28','29'],
    'Sudeste':['31','32','33','35'],'Sul':['41','42','43'],
    'Centro-Oeste':['50','51','52','53']}.items():
    for c in codes: UF_REGION[c] = r

CBO_SURGEONS = ['225120','225125','225130','225135','225140','225145','225150',
                '225155','225250','225265','225275']
CBO_ANESTHESIOLOGISTS = ['225142']
CBO_OBSTETRICIANS = ['225235']
CBO_SAO = CBO_SURGEONS + CBO_ANESTHESIOLOGISTS + CBO_OBSTETRICIANS

log = lambda msg: print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

# ============================================================
# DATABASE SCHEMA
# ============================================================
SCHEMA = """
CREATE TABLE IF NOT EXISTS municipalities (
    cod_ibge TEXT PRIMARY KEY,
    cod_ibge_6 TEXT,
    nome TEXT,
    uf TEXT,
    uf_id TEXT,
    regiao TEXT,
    lat REAL,
    lon REAL,
    capital INTEGER,
    population REAL,
    area_km2 REAL,
    pop_density REAL
);

CREATE TABLE IF NOT EXISTS gdp (
    cod_ibge TEXT,
    year INTEGER,
    gdp_total_brl_1000 REAL,
    gdp_per_capita_brl REAL,
    PRIMARY KEY (cod_ibge, year)
);

CREATE TABLE IF NOT EXISTS sih_municipal (
    cod_ibge_6 TEXT,
    year INTEGER,
    month INTEGER,
    total_procedures INTEGER,
    deaths INTEGER,
    pomr_pct REAL,
    avg_cost_brl REAL,
    avg_days REAL,
    PRIMARY KEY (cod_ibge_6, year, month)
);

CREATE TABLE IF NOT EXISTS sao_workforce (
    cod_ibge_6 TEXT,
    year INTEGER,
    month INTEGER,
    total_sao INTEGER,
    surgeons INTEGER,
    anesthesiologists INTEGER,
    obstetricians INTEGER,
    sao_per_100k REAL,
    PRIMARY KEY (cod_ibge_6, year, month)
);

CREATE TABLE IF NOT EXISTS lcogs1_access (
    cod_ibge TEXT PRIMARY KEY,
    dist_nearest_bellwether_km REAL,
    bellwether_count_50km INTEGER,
    bellwether_count_100km INTEGER,
    access_2hr_proxy INTEGER,
    has_bellwether_local INTEGER
);

CREATE TABLE IF NOT EXISTS bellwether_hospitals (
    cnes TEXT PRIMARY KEY,
    nome TEXT,
    lat REAL,
    lon REAL,
    cod_municipio TEXT,
    uf TEXT,
    tipo INTEGER
);

CREATE TABLE IF NOT EXISTS pipeline_log (
    task TEXT,
    state TEXT,
    year INTEGER,
    month INTEGER,
    status TEXT,
    records INTEGER,
    started_at TEXT,
    completed_at TEXT,
    error TEXT,
    PRIMARY KEY (task, state, year, month)
);

CREATE TABLE IF NOT EXISTS national_indicators (
    indicator_id TEXT PRIMARY KEY,
    value REAL,
    year TEXT,
    label TEXT,
    source TEXT
);

CREATE VIEW IF NOT EXISTS v_lcogs_summary AS
SELECT
    m.cod_ibge, m.nome, m.uf, m.regiao, m.population,
    m.lat, m.lon, m.capital,
    l.dist_nearest_bellwether_km,
    l.access_2hr_proxy AS lcogs1_access,
    s.sao_per_100k AS lcogs2_sao_density,
    CASE WHEN s.sao_per_100k >= 20 THEN 1 ELSE 0 END AS lcogs2_meets_target,
    h.surg_vol_per_100k AS lcogs3_surg_volume,
    CASE WHEN h.surg_vol_per_100k >= 5000 THEN 1 ELSE 0 END AS lcogs3_meets_target,
    h.pomr_pct AS lcogs4_pomr,
    g.gdp_per_capita_brl
FROM municipalities m
LEFT JOIN lcogs1_access l ON m.cod_ibge = l.cod_ibge
LEFT JOIN (
    SELECT cod_ibge_6, sao_per_100k
    FROM sao_workforce
    WHERE (year, month) = (SELECT MAX(year), MAX(month) FROM sao_workforce)
) s ON m.cod_ibge_6 = s.cod_ibge_6
LEFT JOIN (
    SELECT cod_ibge_6,
        SUM(total_procedures) AS total_procs,
        SUM(deaths) AS total_deaths,
        CAST(SUM(deaths) AS REAL) / NULLIF(SUM(total_procedures), 0) * 100 AS pomr_pct,
        SUM(total_procedures) * 100000.0 / MAX(pop) AS surg_vol_per_100k
    FROM sih_municipal sm
    JOIN (SELECT cod_ibge_6, population AS pop FROM municipalities) mp USING (cod_ibge_6)
    GROUP BY cod_ibge_6
) h ON m.cod_ibge_6 = h.cod_ibge_6
LEFT JOIN (
    SELECT cod_ibge, gdp_per_capita_brl
    FROM gdp WHERE year = (SELECT MAX(year) FROM gdp)
) g ON m.cod_ibge = g.cod_ibge;
"""

def init_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript(SCHEMA)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.commit()
    return conn

def task_done(conn, task, state='ALL', year=0, month=0):
    r = conn.execute("SELECT status FROM pipeline_log WHERE task=? AND state=? AND year=? AND month=?",
                     (task, state, year, month)).fetchone()
    return r and r[0] == 'DONE'

def mark_task(conn, task, state='ALL', year=0, month=0, status='DONE', records=0, error=None):
    conn.execute("""INSERT OR REPLACE INTO pipeline_log (task,state,year,month,status,records,started_at,completed_at,error)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                 (task, state, year, month, status, records,
                  datetime.now().isoformat(), datetime.now().isoformat() if status=='DONE' else None, error))
    conn.commit()

# ============================================================
# MODULE 1: MUNICIPALITIES
# ============================================================
def load_municipalities(conn):
    existing = conn.execute("SELECT COUNT(*) FROM municipalities").fetchone()[0]
    if existing > 5000:
        log(f"  Municipalities: {existing} already loaded")
        return

    log("MODULE 1: Loading municipalities...")
    import subprocess

    loc_f = CACHE / "ibge_localidades.json"
    if not loc_f.exists():
        subprocess.run(["curl","-s","--max-time","60",
            "https://servicodados.ibge.gov.br/api/v1/localidades/municipios?view=nivelado",
            "-o",str(loc_f)], check=True)
    with open(loc_f) as f: locs = json.load(f)

    coord_f = CACHE / "municipios_coords.csv"
    if not coord_f.exists():
        subprocess.run(["curl","-sL","--max-time","30",
            "https://raw.githubusercontent.com/kelvins/municipios-brasileiros/main/csv/municipios.csv",
            "-o",str(coord_f)], check=True)
    coords = {}
    with open(coord_f) as f:
        for r in csv.DictReader(f):
            coords[r['codigo_ibge']] = (float(r['latitude']), float(r['longitude']), int(r.get('capital',0)))

    # Population from CIMI-INDEX
    pop_map = {}
    area_map = {}
    cimi = ROOT.parent / 'CIMI-INDEX.xlsx'
    if cimi.exists():
        cdf = pd.read_excel(cimi, header=None)
        for _, row in cdf.iloc[3:].iterrows():
            name = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else ''
            uf = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ''
            key = f"{name.upper()}_{uf}"
            try: pop_map[key] = float(row.iloc[3])
            except: pass
            try: area_map[key] = float(row.iloc[2])
            except: pass

    rows = []
    for l in locs:
        cod = str(l['municipio-id']); uf_id = str(l['UF-id'])
        c = coords.get(cod, (None, None, 0))
        nome = l['municipio-nome']
        key = f"{nome.upper()}_{l['UF-sigla']}"
        pop = pop_map.get(key)
        area = area_map.get(key)
        pd_val = round(pop / area, 2) if pop and area and area > 0 else None
        rows.append((cod, cod[:6], nome, l['UF-sigla'], uf_id,
                     UF_REGION.get(uf_id,''), c[0], c[1], c[2], pop, area, pd_val))

    conn.executemany("INSERT OR IGNORE INTO municipalities VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    log(f"  Loaded {len(rows)} municipalities")
    mark_task(conn, 'municipalities', records=len(rows))

# ============================================================
# MODULE 2: GDP
# ============================================================
def load_gdp(conn):
    if task_done(conn, 'gdp'):
        log("  GDP: already loaded")
        return

    log("MODULE 2: IBGE SIDRA GDP...")
    import subprocess
    records = []
    for uf_code in sorted(UF_CODES.values()):
        f = CACHE / f"gdp_{uf_code}.json"
        if not f.exists():
            url = f"https://apisidra.ibge.gov.br/values/t/5938/n6/in%20n3%20{uf_code}/v/37/p/2015,2016,2017,2018,2019,2020,2021/d/v37%200"
            subprocess.run(["curl","-s","--max-time","60",url,"-o",str(f)], capture_output=True)
            time.sleep(0.5)
        try:
            with open(f) as fh: data = json.load(fh)
            for row in data[1:]:
                if row.get('V') and row['V'] not in ['-','...','']:
                    cod = str(row['D1C']); yr = int(row['D3C']); val = float(row['V'])
                    pop = conn.execute("SELECT population FROM municipalities WHERE cod_ibge=?", (cod,)).fetchone()
                    gdp_pc = round(val * 1000 / pop[0], 2) if pop and pop[0] and pop[0] > 0 else None
                    records.append((cod, yr, val, gdp_pc))
        except: pass

    conn.executemany("INSERT OR IGNORE INTO gdp VALUES (?,?,?,?)", records)
    conn.commit()
    mark_task(conn, 'gdp', records=len(records))
    log(f"  GDP: {len(records)} records")

# ============================================================
# MODULE 3: BELLWETHER HOSPITALS + LCoGS-1
# ============================================================
def load_lcogs1(conn):
    existing = conn.execute("SELECT COUNT(*) FROM lcogs1_access").fetchone()[0]
    if existing > 5000:
        log(f"  LCoGS-1: {existing} already loaded")
        return

    log("MODULE 3: LCoGS-1 bellwether access...")
    # Load pre-computed data
    csv_f = ROOT / "output" / "lcogs1_bellwether_access_v2.csv"
    if csv_f.exists():
        df = pd.read_csv(csv_f, dtype={'cod_ibge': str})
        rows = [(r['cod_ibge'], r['dist_nearest_bellwether_km'], r['bellwether_count_50km'],
                 r['bellwether_count_100km'], r['access_2hr_proxy'],
                 1 if r['has_bellwether_local'] in [True, 'True', 1] else 0)
                for _, r in df.iterrows()]
        conn.executemany("INSERT OR IGNORE INTO lcogs1_access VALUES (?,?,?,?,?,?)", rows)
        conn.commit()
        log(f"  LCoGS-1: {len(rows)} municipalities")
    
    # Load hospitals
    hosp_f = CACHE / "cnes" / "bellwether_hospitals_full.json"
    if hosp_f.exists():
        with open(hosp_f) as f: hospitals = json.load(f)
        rows = [(h['cnes'], h['nome'], h['lat'], h['lon'], h['cod_municipio'], h['uf'], h['tipo'])
                for h in hospitals]
        conn.executemany("INSERT OR IGNORE INTO bellwether_hospitals VALUES (?,?,?,?,?,?,?)", rows)
        conn.commit()
        log(f"  Hospitals: {len(rows)}")
    
    mark_task(conn, 'lcogs1', records=conn.execute("SELECT COUNT(*) FROM lcogs1_access").fetchone()[0])

# ============================================================
# MODULE 4: PySUS SIH (resumable per state/year/month)
# ============================================================
def extract_sih_chunk(conn, state, year, month):
    if task_done(conn, 'sih', state, year, month):
        return

    log(f"  SIH: {state} {year}/{month:02d}...")
    mark_task(conn, 'sih', state, year, month, 'RUNNING')

    try:
        from pysus.online_data.SIH import download as sih_download

        result = sih_download(states=state, years=year, months=month,
                             groups='RD', data_dir=str(PYSUS_DIR))

        # Find and load the parquet/dbf
        pattern_pq = str(PYSUS_DIR / f"RD{state}{str(year)[2:]}{month:02d}.parquet")
        pattern_dbf = str(PYSUS_DIR / f"RD{state}{str(year)[2:]}{month:02d}.dbf")

        df = None
        if os.path.isdir(pattern_pq):
            pq_files = glob.glob(os.path.join(pattern_pq, "*.parquet"))
            if pq_files:
                df = pd.concat([pd.read_parquet(f) for f in pq_files], ignore_index=True)
        elif os.path.isfile(pattern_dbf):
            from dbfread import DBF
            df = pd.DataFrame(iter(DBF(pattern_dbf, encoding='latin-1')))

        if df is not None and len(df) > 0:
            df['is_death'] = (df['MORTE'].astype(str) == '1').astype(int)
            df['VAL_TOT'] = pd.to_numeric(df['VAL_TOT'], errors='coerce')
            df['DIAS_PERM'] = pd.to_numeric(df['DIAS_PERM'], errors='coerce')

            agg = df.groupby('MUNIC_RES').agg(
                total_procedures=('MUNIC_RES','count'),
                deaths=('is_death','sum'),
                avg_cost=('VAL_TOT','mean'),
                avg_days=('DIAS_PERM','mean'),
            ).reset_index()
            agg['pomr'] = (agg['deaths']/agg['total_procedures']*100).round(3)

            rows = [(str(r['MUNIC_RES'])[:6], year, month, int(r['total_procedures']),
                     int(r['deaths']), r['pomr'], round(r['avg_cost'],2) if pd.notna(r['avg_cost']) else None,
                     round(r['avg_days'],1) if pd.notna(r['avg_days']) else None)
                    for _, r in agg.iterrows()]
            conn.executemany("INSERT OR REPLACE INTO sih_municipal VALUES (?,?,?,?,?,?,?,?)", rows)
            conn.commit()
            mark_task(conn, 'sih', state, year, month, 'DONE', records=len(rows))
            log(f"    {state} {year}/{month:02d}: {len(df):,} records → {len(agg)} municipalities")
        else:
            mark_task(conn, 'sih', state, year, month, 'DONE', records=0)
            log(f"    {state} {year}/{month:02d}: no data")

        # Cleanup disk
        for pat in [pattern_pq, pattern_dbf,
                    str(PYSUS_DIR / f"RD{state}{str(year)[2:]}{month:02d}.dbc")]:
            try:
                if os.path.isdir(pat): shutil.rmtree(pat)
                elif os.path.isfile(pat): os.remove(pat)
            except: pass

    except Exception as e:
        mark_task(conn, 'sih', state, year, month, 'ERROR', error=str(e)[:500])
        log(f"    {state} {year}/{month:02d}: ERROR — {e}")

# ============================================================
# MODULE 5: PySUS CNES SAO WORKFORCE (resumable)
# ============================================================
def extract_sao_chunk(conn, state, year, month):
    if task_done(conn, 'cnes_sao', state, year, month):
        return

    log(f"  CNES SAO: {state} {year}/{month:02d}...")
    mark_task(conn, 'cnes_sao', state, year, month, 'RUNNING')

    try:
        from pysus.online_data.CNES import download as cnes_download
        cnes_download(group='PF', states=state, years=year, months=month,
                     data_dir=str(PYSUS_DIR))

        pattern_pq = str(PYSUS_DIR / f"PF{state}{str(year)[2:]}{month:02d}.parquet")
        pattern_dbf = str(PYSUS_DIR / f"PF{state}{str(year)[2:]}{month:02d}.dbf")

        df = None
        if os.path.isdir(pattern_pq):
            pq_files = glob.glob(os.path.join(pattern_pq, "*.parquet"))
            if pq_files: df = pd.concat([pd.read_parquet(f) for f in pq_files], ignore_index=True)
        elif os.path.isfile(pattern_dbf):
            from dbfread import DBF
            df = pd.DataFrame(iter(DBF(pattern_dbf, encoding='latin-1')))

        if df is not None and len(df) > 0:
            cbo_col = next((c for c in df.columns if 'CBO' in c.upper()), None)
            muni_col = next((c for c in df.columns if c in ['CODUFMUN','MUNICRES','COD_MUN']), None)
            if not muni_col:
                muni_col = next((c for c in df.columns if 'MUN' in c.upper()), None)

            if cbo_col and muni_col:
                df[cbo_col] = df[cbo_col].astype(str).str.strip()
                sao = df[df[cbo_col].isin(CBO_SAO)]

                if len(sao) > 0:
                    agg = sao.groupby(muni_col).agg(
                        total_sao=(muni_col,'count'),
                        surgeons=(cbo_col, lambda x: x.isin(CBO_SURGEONS).sum()),
                        anesthesiologists=(cbo_col, lambda x: x.isin(CBO_ANESTHESIOLOGISTS).sum()),
                        obstetricians=(cbo_col, lambda x: x.isin(CBO_OBSTETRICIANS).sum()),
                    ).reset_index()

                    # Get population for density
                    rows = []
                    for _, r in agg.iterrows():
                        cod6 = str(r[muni_col])[:6]
                        pop = conn.execute("SELECT population FROM municipalities WHERE cod_ibge_6=?",
                                          (cod6,)).fetchone()
                        sao_100k = round(r['total_sao'] / pop[0] * 100000, 2) if pop and pop[0] and pop[0]>0 else None
                        rows.append((cod6, year, month, int(r['total_sao']), int(r['surgeons']),
                                    int(r['anesthesiologists']), int(r['obstetricians']), sao_100k))

                    conn.executemany("INSERT OR REPLACE INTO sao_workforce VALUES (?,?,?,?,?,?,?,?)", rows)
                    conn.commit()
                    mark_task(conn, 'cnes_sao', state, year, month, 'DONE', records=len(rows))
                    log(f"    {state}: {len(sao)} SAO → {len(rows)} municipalities")
                else:
                    mark_task(conn, 'cnes_sao', state, year, month, 'DONE', records=0)
            else:
                mark_task(conn, 'cnes_sao', state, year, month, 'DONE', records=0,
                         error=f"Missing columns. CBO={cbo_col}, MUN={muni_col}")
        else:
            mark_task(conn, 'cnes_sao', state, year, month, 'DONE', records=0)

        # Cleanup
        for pat in [pattern_pq, pattern_dbf,
                    str(PYSUS_DIR / f"PF{state}{str(year)[2:]}{month:02d}.dbc")]:
            try:
                if os.path.isdir(pat): shutil.rmtree(pat)
                elif os.path.isfile(pat): os.remove(pat)
            except: pass

    except Exception as e:
        mark_task(conn, 'cnes_sao', state, year, month, 'ERROR', error=str(e)[:500])
        log(f"    {state}: ERROR — {e}")

# ============================================================
# MODULE 6: INTERNATIONAL INDICATORS
# ============================================================
def load_international(conn):
    if task_done(conn, 'international'):
        return
    log("MODULE 6: International indicators...")
    f = ROOT / "output" / "icskg_international_complete.json"
    if f.exists():
        with open(f) as fh: data = json.load(fh)
        rows = [(k, v['value'], str(v.get('year','')), v.get('label',''), v.get('source',''))
                for k, v in data.get('indicators',{}).items()]
        conn.executemany("INSERT OR REPLACE INTO national_indicators VALUES (?,?,?,?,?)", rows)
        conn.commit()
        mark_task(conn, 'international', records=len(rows))
        log(f"  {len(rows)} national indicators")

# ============================================================
# STATUS REPORT
# ============================================================
def show_status(conn):
    print("\n" + "="*70)
    print("ICSKG-BR PIPELINE STATUS")
    print("="*70)
    
    tables = ['municipalities','gdp','sih_municipal','sao_workforce',
              'lcogs1_access','bellwether_hospitals','national_indicators']
    for t in tables:
        n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {n:,} rows")
    
    print(f"\nPipeline log:")
    tasks = conn.execute("""
        SELECT task, status, COUNT(*), SUM(records)
        FROM pipeline_log GROUP BY task, status ORDER BY task
    """).fetchall()
    for task, status, cnt, recs in tasks:
        print(f"  {task}: {status} ({cnt} chunks, {recs or 0:,.0f} records)")
    
    # SIH progress detail
    sih_done = conn.execute("SELECT COUNT(*) FROM pipeline_log WHERE task='sih' AND status='DONE'").fetchone()[0]
    sih_err = conn.execute("SELECT COUNT(*) FROM pipeline_log WHERE task='sih' AND status='ERROR'").fetchone()[0]
    sih_run = conn.execute("SELECT COUNT(*) FROM pipeline_log WHERE task='sih' AND status='RUNNING'").fetchone()[0]
    total_sih = conn.execute("SELECT COUNT(*) FROM pipeline_log WHERE task='sih'").fetchone()[0]
    if total_sih > 0:
        print(f"\n  SIH detail: {sih_done} done, {sih_err} errors, {sih_run} running, {total_sih} total")
    
    # SAO progress
    sao_done = conn.execute("SELECT COUNT(*) FROM pipeline_log WHERE task='cnes_sao' AND status='DONE'").fetchone()[0]
    sao_total = conn.execute("SELECT COUNT(*) FROM pipeline_log WHERE task='cnes_sao'").fetchone()[0]
    if sao_total > 0:
        print(f"  CNES SAO: {sao_done}/{sao_total} done")

# ============================================================
# MAIN
# ============================================================
def main():
    parser = argparse.ArgumentParser(description='ICSKG-BR Pipeline')
    parser.add_argument('--quick', action='store_true', help='Quick: SP only, Dec 2023')
    parser.add_argument('--states', nargs='+', default=None)
    parser.add_argument('--years', type=int, nargs='+', default=[2023])
    parser.add_argument('--months', type=int, nargs='+', default=list(range(1,13)))
    parser.add_argument('--skip-sih', action='store_true')
    parser.add_argument('--skip-cnes', action='store_true')
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--retry-errors', action='store_true', help='Retry failed tasks')
    args = parser.parse_args()

    conn = init_db()

    if args.status:
        show_status(conn)
        conn.close()
        return

    if args.retry_errors:
        conn.execute("DELETE FROM pipeline_log WHERE status IN ('ERROR','RUNNING')")
        conn.commit()
        log("Cleared error/running states for retry")

    states = ['SP'] if args.quick else (args.states or ALL_UFS)
    months = [12] if args.quick else args.months

    log("="*60)
    log(f"ICSKG-BR PIPELINE — states={states}, years={args.years}, months={months}")
    log(f"Database: {DB_PATH}")
    log("="*60)

    # Phase 1: Base data (fast)
    load_municipalities(conn)
    load_gdp(conn)
    load_lcogs1(conn)
    load_international(conn)

    # Phase 2: SIH surgical data (slow — ~20s per state-month)
    if not args.skip_sih:
        log("\nPHASE 2: SIH Surgical Data")
        for year in args.years:
            for state in states:
                for month in months:
                    extract_sih_chunk(conn, state, year, month)

    # Phase 3: CNES SAO workforce (moderate)
    if not args.skip_cnes:
        log("\nPHASE 3: CNES SAO Workforce")
        for year in args.years:
            for state in states:
                extract_sao_chunk(conn, state, year, max(months))

    show_status(conn)
    conn.close()
    log(f"\nDatabase saved: {DB_PATH}")
    log(f"Size: {DB_PATH.stat().st_size / 1024 / 1024:.1f} MB")

if __name__ == "__main__":
    main()
