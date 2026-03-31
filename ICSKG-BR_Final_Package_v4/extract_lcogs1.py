"""
ICSKG-BR — LCoGS Indicator 1: Geospatial Access to Bellwether Surgery
======================================================================
Identifies bellwether-capable hospitals from CNES, maps them against
all 5,570 municipality centroids, and calculates:
  1. Euclidean distance (km) to nearest bellwether hospital
  2. Bellwether coverage (binary: is there one within the municipality?)
  3. Number of bellwether hospitals within 100km radius

References:
  - Massenburg BB et al. BMJ Glob Health 2017;2:e000226 (proxy definition)
  - Trindade BO et al. World J Surg 2023;47:1-8 (geospatial approach in RS)
  - Meara JG et al. Lancet 2015;386:569-624 (LCoGS Indicator 1 definition)
"""

import os, json, csv, math, time, subprocess, sys
from collections import defaultdict

PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(PIPELINE_DIR, "output")
CACHE_DIR = os.path.join(PIPELINE_DIR, "cache")
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(os.path.join(CACHE_DIR, "cnes"), exist_ok=True)

# ========================================================================
# STEP 1: Download municipality centroids
# ========================================================================
def get_municipality_centroids():
    """Download lat/lon for all 5,570 municipalities from GitHub/IBGE."""
    coords_file = os.path.join(CACHE_DIR, "municipios_coords.csv")
    if not os.path.exists(coords_file):
        print("[1/4] Downloading municipality coordinates...")
        subprocess.run([
            "curl", "-sL", "--max-time", "30",
            "https://raw.githubusercontent.com/kelvins/municipios-brasileiros/main/csv/municipios.csv",
            "-o", coords_file
        ], check=True)
    
    municipalities = {}
    with open(coords_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            cod = row['codigo_ibge']
            try:
                lat = float(row['latitude'])
                lon = float(row['longitude'])
                municipalities[cod] = {
                    'cod_ibge': cod,
                    'nome': row['nome'],
                    'lat': lat,
                    'lon': lon,
                    'capital': row.get('capital', '0') == '1',
                    'uf': cod[:2]
                }
            except (ValueError, KeyError):
                pass
    
    print(f"  Loaded {len(municipalities)} municipality centroids")
    return municipalities


# ========================================================================
# STEP 2: Extract bellwether-capable hospitals from CNES API
# ========================================================================
def extract_bellwether_hospitals():
    """
    Query CNES API for hospitals with:
      - estabelecimento_possui_centro_cirurgico = 1 (surgical center)
      - estabelecimento_possui_centro_obstetrico = 1 (obstetric center)
      - estabelecimento_possui_atendimento_hospitalar = 1 (hospital care)
    These proxy Massenburg's criteria for bellwether facilities.
    
    Uses parallel curl for speed.
    """
    cache_file = os.path.join(CACHE_DIR, "cnes", "bellwether_hospitals.json")
    if os.path.exists(cache_file) and os.path.getsize(cache_file) > 1000:
        with open(cache_file) as f:
            hospitals = json.load(f)
        print(f"  Loaded {len(hospitals)} bellwether hospitals from cache")
        return hospitals
    
    print("[2/4] Extracting bellwether hospitals from CNES API...")
    print("  Criteria: centro_cirurgico=1 AND centro_obstetrico=1 AND atend_hospitalar=1")
    
    # Paginate through the API — hospitals with surgical + obstetric centers
    hospitals = []
    batch_size = 100
    max_offset = 500000  # safety limit
    
    # Use parallel curl batches
    offsets = list(range(0, 20000, batch_size))  # Start with first 20k
    
    # Write curl commands to a script
    script_lines = []
    for i, offset in enumerate(offsets):
        url = f"https://apidadosabertos.saude.gov.br/cnes/estabelecimentos?limit={batch_size}&offset={offset}"
        outfile = os.path.join(CACHE_DIR, "cnes", f"page_{offset}.json")
        script_lines.append(f'curl -s --max-time 20 "{url}" -o "{outfile}" &')
        if (i + 1) % 10 == 0:
            script_lines.append("wait")
    script_lines.append("wait")
    
    script_path = os.path.join(CACHE_DIR, "cnes", "extract.sh")
    with open(script_path, 'w') as f:
        f.write("\n".join(script_lines))
    
    print(f"  Downloading {len(offsets)} pages ({batch_size} per page)...")
    subprocess.run(["bash", script_path], capture_output=True, timeout=120)
    
    # Parse results and filter bellwether hospitals
    for offset in offsets:
        outfile = os.path.join(CACHE_DIR, "cnes", f"page_{offset}.json")
        try:
            with open(outfile) as f:
                data = json.load(f)
            for est in data.get('estabelecimentos', []):
                if (est.get('estabelecimento_possui_centro_cirurgico') == 1 and
                    est.get('estabelecimento_possui_centro_obstetrico') == 1 and
                    est.get('estabelecimento_possui_atendimento_hospitalar') == 1):
                    lat = est.get('latitude_estabelecimento_decimo_grau')
                    lon = est.get('longitude_estabelecimento_decimo_grau')
                    if lat and lon and lat != 0 and lon != 0:
                        hospitals.append({
                            'cnes': est['codigo_cnes'],
                            'nome': est.get('nome_fantasia', est.get('nome_razao_social', '')),
                            'lat': float(lat),
                            'lon': float(lon),
                            'cod_municipio': str(est.get('codigo_municipio', '')),
                            'uf': str(est.get('codigo_uf', '')),
                            'tipo': est.get('codigo_tipo_unidade', ''),
                        })
        except (json.JSONDecodeError, FileNotFoundError, KeyError):
            pass
    
    # Check if we need more pages
    if len(hospitals) < 500:
        print(f"  Warning: Only found {len(hospitals)} bellwether hospitals. Checking more pages...")
        # Extend search
        more_offsets = list(range(20000, 100000, batch_size))
        script_lines2 = []
        for i, offset in enumerate(more_offsets):
            url = f"https://apidadosabertos.saude.gov.br/cnes/estabelecimentos?limit={batch_size}&offset={offset}"
            outfile = os.path.join(CACHE_DIR, "cnes", f"page_{offset}.json")
            script_lines2.append(f'curl -s --max-time 20 "{url}" -o "{outfile}" &')
            if (i + 1) % 15 == 0:
                script_lines2.append("wait")
        script_lines2.append("wait")
        
        script2 = os.path.join(CACHE_DIR, "cnes", "extract2.sh")
        with open(script2, 'w') as f:
            f.write("\n".join(script_lines2))
        
        print(f"  Downloading {len(more_offsets)} additional pages...")
        subprocess.run(["bash", script2], capture_output=True, timeout=300)
        
        for offset in more_offsets:
            outfile = os.path.join(CACHE_DIR, "cnes", f"page_{offset}.json")
            try:
                with open(outfile) as f:
                    data = json.load(f)
                for est in data.get('estabelecimentos', []):
                    if (est.get('estabelecimento_possui_centro_cirurgico') == 1 and
                        est.get('estabelecimento_possui_centro_obstetrico') == 1 and
                        est.get('estabelecimento_possui_atendimento_hospitalar') == 1):
                        lat = est.get('latitude_estabelecimento_decimo_grau')
                        lon = est.get('longitude_estabelecimento_decimo_grau')
                        if lat and lon and lat != 0 and lon != 0:
                            hospitals.append({
                                'cnes': est['codigo_cnes'],
                                'nome': est.get('nome_fantasia', est.get('nome_razao_social', '')),
                                'lat': float(lat),
                                'lon': float(lon),
                                'cod_municipio': str(est.get('codigo_municipio', '')),
                                'uf': str(est.get('codigo_uf', '')),
                                'tipo': est.get('codigo_tipo_unidade', ''),
                            })
            except (json.JSONDecodeError, FileNotFoundError, KeyError):
                pass
    
    # Deduplicate by CNES code
    seen = set()
    unique_hospitals = []
    for h in hospitals:
        if h['cnes'] not in seen:
            seen.add(h['cnes'])
            unique_hospitals.append(h)
    
    # Save cache
    with open(cache_file, 'w') as f:
        json.dump(unique_hospitals, f, indent=2, ensure_ascii=False)
    
    print(f"  Found {len(unique_hospitals)} unique bellwether-capable hospitals")
    return unique_hospitals


# ========================================================================
# STEP 3: Calculate distances
# ========================================================================
def haversine_km(lat1, lon1, lat2, lon2):
    """Haversine distance in km between two lat/lon points."""
    R = 6371  # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    return R * c

def calculate_distances(municipalities, hospitals):
    """
    For each municipality, find:
    1. Distance (km) to nearest bellwether hospital
    2. Whether a bellwether hospital exists IN the municipality
    3. Count of bellwether hospitals within 100km
    4. Count within 50km
    """
    print("[3/4] Calculating distances for all municipalities...")
    
    # Build hospital lookup by municipality
    hosp_by_muni = defaultdict(list)
    for h in hospitals:
        # CNES codigo_municipio is 6-digit
        cod6 = str(h['cod_municipio'])[:6]
        hosp_by_muni[cod6].append(h)
    
    results = []
    total = len(municipalities)
    
    for i, (cod, muni) in enumerate(municipalities.items()):
        if (i + 1) % 1000 == 0:
            print(f"  Processing {i+1}/{total}...")
        
        cod6 = cod[:6]
        
        # Find nearest hospital
        min_dist = float('inf')
        nearest_cnes = None
        nearest_name = None
        count_50km = 0
        count_100km = 0
        has_local = len(hosp_by_muni.get(cod6, [])) > 0 or len(hosp_by_muni.get(cod, [])) > 0
        
        for h in hospitals:
            d = haversine_km(muni['lat'], muni['lon'], h['lat'], h['lon'])
            if d < min_dist:
                min_dist = d
                nearest_cnes = h['cnes']
                nearest_name = h['nome']
            if d <= 50:
                count_50km += 1
            if d <= 100:
                count_100km += 1
        
        # Estimate 2-hour access (proxy: <150km straight-line ≈ 2hr at 75km/h average)
        # This is a rough proxy; real road network would give better estimates
        access_2hr_proxy = 1 if min_dist <= 150 else 0
        
        results.append({
            'cod_ibge': cod,
            'nome': muni['nome'],
            'uf': muni['uf'],
            'lat': muni['lat'],
            'lon': muni['lon'],
            'capital': muni.get('capital', False),
            'has_bellwether_local': has_local,
            'dist_nearest_bellwether_km': round(min_dist, 2),
            'nearest_bellwether_cnes': nearest_cnes,
            'nearest_bellwether_name': nearest_name,
            'bellwether_count_50km': count_50km,
            'bellwether_count_100km': count_100km,
            'access_2hr_proxy': access_2hr_proxy,
        })
    
    print(f"  Calculated distances for {len(results)} municipalities")
    return results


# ========================================================================
# STEP 4: Generate summary statistics and output
# ========================================================================
def generate_summary(results, hospitals):
    """Generate summary stats and save outputs."""
    print("[4/4] Generating summary...")
    
    # Save full results
    csv_path = os.path.join(OUTPUT_DIR, "lcogs1_bellwether_access.csv")
    with open(csv_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)
    print(f"  Saved: {csv_path}")
    
    # Summary statistics
    dists = [r['dist_nearest_bellwether_km'] for r in results]
    has_local = sum(1 for r in results if r['has_bellwether_local'])
    access_2hr = sum(1 for r in results if r['access_2hr_proxy'])
    no_50km = sum(1 for r in results if r['bellwether_count_50km'] == 0)
    
    # By region
    uf_to_region = {}
    for r in results:
        uf = r['uf']
        if uf in ['11','12','13','14','15','16','17']: uf_to_region[uf] = 'Norte'
        elif uf in ['21','22','23','24','25','26','27','28','29']: uf_to_region[uf] = 'Nordeste'
        elif uf in ['31','32','33','35']: uf_to_region[uf] = 'Sudeste'
        elif uf in ['41','42','43']: uf_to_region[uf] = 'Sul'
        elif uf in ['50','51','52','53']: uf_to_region[uf] = 'Centro-Oeste'
    
    region_stats = defaultdict(lambda: {'count': 0, 'dists': [], 'access': 0, 'no_local': 0})
    for r in results:
        region = uf_to_region.get(r['uf'], 'Unknown')
        region_stats[region]['count'] += 1
        region_stats[region]['dists'].append(r['dist_nearest_bellwether_km'])
        region_stats[region]['access'] += r['access_2hr_proxy']
        if not r['has_bellwether_local']:
            region_stats[region]['no_local'] += 1
    
    summary = {
        "indicator": "LCoGS Indicator 1: Access to Bellwether Surgical Care",
        "method": "Euclidean (haversine) distance from municipality centroid to nearest bellwether-capable hospital",
        "bellwether_definition": "CNES establishment with centro_cirurgico=1 AND centro_obstetrico=1 AND atend_hospitalar=1 (Massenburg et al. 2017 proxy)",
        "total_municipalities": len(results),
        "total_bellwether_hospitals": len(hospitals),
        "municipalities_with_local_bellwether": has_local,
        "pct_with_local_bellwether": round(has_local / len(results) * 100, 1),
        "municipalities_with_2hr_access_proxy": access_2hr,
        "pct_2hr_access": round(access_2hr / len(results) * 100, 1),
        "municipalities_no_bellwether_within_50km": no_50km,
        "distance_stats_km": {
            "mean": round(sum(dists) / len(dists), 1),
            "median": round(sorted(dists)[len(dists)//2], 1),
            "min": round(min(dists), 1),
            "max": round(max(dists), 1),
            "p25": round(sorted(dists)[len(dists)//4], 1),
            "p75": round(sorted(dists)[3*len(dists)//4], 1),
            "p95": round(sorted(dists)[int(len(dists)*0.95)], 1),
        },
        "by_region": {},
        "references": [
            "Massenburg BB et al. Assessing the Brazilian surgical system with six surgical indicators. BMJ Glob Health. 2017;2(2):e000226.",
            "Trindade BO et al. Geospatial Analysis of Accessibility to Surgical Care. World J Surg. 2023;47:1-8.",
            "Meara JG et al. Global Surgery 2030. Lancet. 2015;386:569-624."
        ]
    }
    
    for region in ['Norte', 'Nordeste', 'Sudeste', 'Sul', 'Centro-Oeste']:
        s = region_stats[region]
        if s['count'] > 0:
            d = s['dists']
            summary['by_region'][region] = {
                'municipalities': s['count'],
                'pct_2hr_access': round(s['access'] / s['count'] * 100, 1),
                'pct_no_local_bellwether': round(s['no_local'] / s['count'] * 100, 1),
                'mean_dist_km': round(sum(d) / len(d), 1),
                'median_dist_km': round(sorted(d)[len(d)//2], 1),
                'max_dist_km': round(max(d), 1),
            }
    
    json_path = os.path.join(OUTPUT_DIR, "lcogs1_summary.json")
    with open(json_path, 'w') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"  Saved: {json_path}")
    
    # Print summary
    print(f"\n{'='*60}")
    print(f"LCoGS INDICATOR 1: BELLWETHER ACCESS — BRAZIL")
    print(f"{'='*60}")
    print(f"Bellwether hospitals identified: {len(hospitals)}")
    print(f"Municipalities analyzed: {len(results)}")
    print(f"\nMunicipalities WITH local bellwether: {has_local} ({summary['pct_with_local_bellwether']}%)")
    print(f"Municipalities with 2-hr access (proxy): {access_2hr} ({summary['pct_2hr_access']}%)")
    print(f"Municipalities with NO bellwether within 50km: {no_50km}")
    print(f"\nDistance to nearest bellwether (km):")
    ds = summary['distance_stats_km']
    print(f"  Mean: {ds['mean']} | Median: {ds['median']} | Min: {ds['min']} | Max: {ds['max']}")
    print(f"  P25: {ds['p25']} | P75: {ds['p75']} | P95: {ds['p95']}")
    print(f"\nBy Region:")
    for region, stats in summary['by_region'].items():
        print(f"  {region}: {stats['pct_2hr_access']}% 2hr access | mean dist {stats['mean_dist_km']}km | {stats['pct_no_local_bellwether']}% no local bellwether")
    
    return summary


if __name__ == "__main__":
    municipalities = get_municipality_centroids()
    hospitals = extract_bellwether_hospitals()
    results = calculate_distances(municipalities, hospitals)
    summary = generate_summary(results, hospitals)
