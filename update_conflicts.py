#!/usr/bin/env python3
"""
SENTINEL — Conflict Zone Updater
=================================
Scrapes GDELT event data to build a live conflict zone overlay for the dashboard.

Sources:
  1. GDELT 2.0 Event Database (CSV, no API key, updates every 15 minutes)
     - Downloads latest 15-min export file from GDELT master list
     - Filters for CAMEO Material Conflict + Protest events
     - Clusters by geography using DBSCAN
     - Scores severity by event density + Goldstein tone

  2. GDELT Stability Dashboard API (no key, free)
     - Pulls per-country instability scores for last 7 days
     - Used to rank and validate zone severity

Output:
  conflict_zones.json — drop-in replacement for SENTINEL's CONFLICT_ZONES array

Usage:
  python3 update_conflicts.py                     # Full run, outputs conflict_zones.json
  python3 update_conflicts.py --days 3            # Lookback window (default: 2 days)
  python3 update_conflicts.py --output zones.json # Custom output path
  python3 update_conflicts.py --embed             # Also patches sentinel-live.html in-place

Dependencies:
  pip install pandas numpy scikit-learn requests --break-system-packages

No API keys required. All data is free and open.
"""

import argparse
import io
import json
import os
import re
import sys
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import requests
from sklearn.cluster import DBSCAN

# ── CAMEO Event Codes for conflict/protest ──────────────────────────────────
# Material Conflict: 18 (Assault), 19 (Fight), 20 (Unconventional mass violence)
# Protest: 14 (Protest)
# Coerce: 17 (Coerce)
# Reduce Relations: 16 (only sub-codes for military)
CONFLICT_ROOT_CODES = {'14', '17', '18', '19', '20'}

# Columns we need from GDELT event exports (v2)
# Full spec: https://www.gdeltproject.org/data.html
GDELT_COLS = [
    'GlobalEventID', 'Day', 'MonthYear', 'Year', 'FractionDate',
    'Actor1Code', 'Actor1Name', 'Actor1CountryCode', 'Actor1KnownGroupCode',
    'Actor1EthnicCode', 'Actor1Religion1Code', 'Actor1Religion2Code',
    'Actor1Type1Code', 'Actor1Type2Code', 'Actor1Type3Code',
    'Actor2Code', 'Actor2Name', 'Actor2CountryCode', 'Actor2KnownGroupCode',
    'Actor2EthnicCode', 'Actor2Religion1Code', 'Actor2Religion2Code',
    'Actor2Type1Code', 'Actor2Type2Code', 'Actor2Type3Code',
    'IsRootEvent', 'EventCode', 'EventBaseCode', 'EventRootCode',
    'QuadClass', 'GoldsteinScale', 'NumMentions', 'NumSources',
    'NumArticles', 'AvgTone',
    'Actor1Geo_Type', 'Actor1Geo_FullName', 'Actor1Geo_CountryCode',
    'Actor1Geo_ADM1Code', 'Actor1Geo_ADM2Code',
    'Actor1Geo_Lat', 'Actor1Geo_Long', 'Actor1Geo_FeatureID',
    'Actor2Geo_Type', 'Actor2Geo_FullName', 'Actor2Geo_CountryCode',
    'Actor2Geo_ADM1Code', 'Actor2Geo_ADM2Code',
    'Actor2Geo_Lat', 'Actor2Geo_Long', 'Actor2Geo_FeatureID',
    'ActionGeo_Type', 'ActionGeo_FullName', 'ActionGeo_CountryCode',
    'ActionGeo_ADM1Code', 'ActionGeo_ADM2Code',
    'ActionGeo_Lat', 'ActionGeo_Long', 'ActionGeo_FeatureID',
    'DATEADDED', 'SOURCEURL'
]

# ── GDELT Master File List URL ──────────────────────────────────────────────
GDELT_MASTER_URL = 'http://data.gdeltproject.org/gdeltv2/lastupdate.txt'
GDELT_EXPORT_LIST = 'http://data.gdeltproject.org/gdeltv2/masterfilelist.txt'

# Country code → name mapping (FIPS to readable)
FIPS_TO_NAME = {
    'US': 'United States', 'UP': 'Ukraine', 'RS': 'Russia', 'IS': 'Israel',
    'GZ': 'Gaza Strip', 'SU': 'Sudan', 'BM': 'Myanmar', 'SY': 'Syria',
    'MX': 'Mexico', 'YM': 'Yemen', 'NI': 'Nigeria', 'HA': 'Haiti',
    'CG': 'DR Congo', 'PK': 'Pakistan', 'ML': 'Mali', 'UV': 'Burkina Faso',
    'CO': 'Colombia', 'SO': 'Somalia', 'AF': 'Afghanistan', 'ET': 'Ethiopia',
    'WE': 'West Bank', 'LE': 'Lebanon', 'EC': 'Ecuador', 'CM': 'Cameroon',
    'MZ': 'Mozambique', 'BR': 'Brazil', 'OD': 'South Sudan', 'IZ': 'Iraq',
    'IN': 'India', 'CH': 'China', 'FR': 'France', 'UK': 'United Kingdom',
    'GM': 'Germany', 'EG': 'Egypt', 'SA': 'Saudi Arabia', 'IR': 'Iran',
    'TU': 'Turkey', 'KE': 'Kenya', 'TZ': 'Tanzania', 'UG': 'Uganda',
    'TH': 'Thailand', 'ID': 'Indonesia', 'PH': 'Philippines',
    'JA': 'Japan', 'KS': 'South Korea', 'SF': 'South Africa',
    'AG': 'Algeria', 'MO': 'Morocco', 'LY': 'Libya', 'TN': 'Tunisia',
    'CD': 'Chad', 'NG': 'Niger', 'WA': 'Namibia', 'BC': 'Botswana',
    'RW': 'Rwanda', 'BU': 'Burundi', 'CE': 'Central African Republic',
}

# ── Conflict type classification from CAMEO codes ───────────────────────────
def classify_conflict(row):
    """Classify conflict type from CAMEO event codes and actor metadata."""
    code = str(row.get('EventRootCode', ''))
    base = str(row.get('EventBaseCode', ''))
    a1type = str(row.get('Actor1Type1Code', ''))
    a2type = str(row.get('Actor2Type1Code', ''))

    if code == '14':
        return 'Protest'
    elif code == '20':
        return 'Mass Violence'
    elif code == '19':
        if 'MIL' in a1type or 'MIL' in a2type:
            return 'Armed Conflict'
        elif 'REB' in a1type or 'REB' in a2type:
            return 'Insurgency'
        return 'Armed Conflict'
    elif code == '18':
        if 'COP' in a1type or 'GOV' in a1type:
            return 'State Violence'
        return 'Assault'
    elif code == '17':
        return 'Coercion'
    return 'Conflict'


# ── STEP 1: Download GDELT event data ──────────────────────────────────────
def get_recent_gdelt_urls(days=2):
    """Get URLs for GDELT 2.0 export files from the last N days."""
    print(f"[1/5] Fetching GDELT master file list (last {days} days)...")
    urls = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Get last-update file for the most recent 15-min export
    try:
        r = requests.get(GDELT_MASTER_URL, timeout=30)
        for line in r.text.strip().split('\n'):
            parts = line.strip().split()
            if len(parts) >= 3 and parts[2].endswith('.export.CSV.zip'):
                urls.append(parts[2])
    except Exception as e:
        print(f"  Warning: Could not fetch last update: {e}")

    # Get master file list for historical lookback
    try:
        r = requests.get(GDELT_EXPORT_LIST, timeout=60)
        for line in r.text.strip().split('\n'):
            parts = line.strip().split()
            if len(parts) < 3:
                continue
            url = parts[2]
            if not url.endswith('.export.CSV.zip'):
                continue
            # Extract timestamp from filename: YYYYMMDDHHMMSS.export.CSV.zip
            fname = url.split('/')[-1]
            try:
                ts_str = fname.split('.')[0]
                ts = datetime.strptime(ts_str, '%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)
                if ts >= cutoff:
                    urls.append(url)
            except ValueError:
                continue
    except Exception as e:
        print(f"  Warning: Could not fetch master file list: {e}")

    urls = list(set(urls))  # deduplicate
    print(f"  Found {len(urls)} export files to process")
    return urls


def download_and_filter_events(urls, max_files=50):
    """Download GDELT export CSVs and filter for conflict events."""
    print(f"[2/5] Downloading and filtering conflict events (max {max_files} files)...")
    all_events = []
    processed = 0
    errors = 0

    # Sample evenly across available files if there are too many
    if len(urls) > max_files:
        step = len(urls) // max_files
        urls = urls[::step][:max_files]

    for url in urls:
        try:
            r = requests.get(url, timeout=60)
            if r.status_code != 200:
                errors += 1
                continue

            with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
                for name in zf.namelist():
                    if name.endswith('.CSV'):
                        with zf.open(name) as f:
                            df = pd.read_csv(
                                f, sep='\t', header=None,
                                names=GDELT_COLS[:len(GDELT_COLS)],
                                dtype=str, on_bad_lines='skip',
                                low_memory=False
                            )
                            # Filter for conflict events
                            conflict = df[df['EventRootCode'].isin(CONFLICT_ROOT_CODES)]
                            # Filter for events with valid geo coordinates
                            conflict = conflict[
                                conflict['ActionGeo_Lat'].notna() &
                                conflict['ActionGeo_Long'].notna()
                            ]
                            if len(conflict) > 0:
                                all_events.append(conflict)
            processed += 1
            if processed % 10 == 0:
                total = sum(len(e) for e in all_events)
                print(f"  Processed {processed}/{len(urls)} files, {total} events so far...")

        except Exception as e:
            errors += 1
            continue

    if not all_events:
        print("  ERROR: No conflict events found!")
        return pd.DataFrame()

    combined = pd.concat(all_events, ignore_index=True)
    # Convert coordinates to float
    combined['lat'] = pd.to_numeric(combined['ActionGeo_Lat'], errors='coerce')
    combined['lng'] = pd.to_numeric(combined['ActionGeo_Long'], errors='coerce')
    combined['goldstein'] = pd.to_numeric(combined['GoldsteinScale'], errors='coerce')
    combined['mentions'] = pd.to_numeric(combined['NumMentions'], errors='coerce').fillna(1)
    combined['articles'] = pd.to_numeric(combined['NumArticles'], errors='coerce').fillna(1)
    combined['tone'] = pd.to_numeric(combined['AvgTone'], errors='coerce').fillna(0)

    # Drop rows with invalid coordinates
    combined = combined.dropna(subset=['lat', 'lng'])
    # Filter out events at 0,0 (common geocoding error)
    combined = combined[~((combined['lat'].abs() < 0.5) & (combined['lng'].abs() < 0.5))]

    print(f"  Total conflict events: {len(combined)} ({errors} download errors)")
    return combined


# ── STEP 2: Cluster events into geographic zones ───────────────────────────
def cluster_events(df, eps_km=150, min_events=5):
    """Use DBSCAN to cluster conflict events into geographic zones."""
    print(f"[3/5] Clustering events (eps={eps_km}km, min_events={min_events})...")

    if len(df) == 0:
        return []

    coords = df[['lat', 'lng']].values
    # Convert km to radians for haversine: 1 radian ≈ 6371 km
    eps_rad = eps_km / 6371.0

    clustering = DBSCAN(
        eps=eps_rad, min_samples=min_events,
        metric='haversine', algorithm='ball_tree'
    )
    # DBSCAN with haversine expects radians
    coords_rad = np.radians(coords)
    labels = clustering.fit_predict(coords_rad)

    df = df.copy()
    df['cluster'] = labels

    # Filter out noise (label = -1)
    clustered = df[df['cluster'] >= 0]
    n_clusters = len(set(labels) - {-1})
    print(f"  Found {n_clusters} conflict clusters from {len(clustered)}/{len(df)} events")

    return clustered


# ── STEP 3: Build conflict zone objects ────────────────────────────────────
def build_zones(clustered_df):
    """Aggregate clusters into conflict zone definitions."""
    print("[4/5] Building conflict zone definitions...")

    if len(clustered_df) == 0:
        return []

    zones = []
    for cluster_id, group in clustered_df.groupby('cluster'):
        n_events = len(group)
        center_lat = group['lat'].mean()
        center_lng = group['lng'].mean()

        # Calculate radius from the spread of events (in meters)
        lat_spread = group['lat'].max() - group['lat'].min()
        lng_spread = group['lng'].max() - group['lng'].min()
        spread_km = max(lat_spread, lng_spread) * 111  # rough deg→km
        radius_m = max(int(spread_km * 1000 / 2), 50000)  # min 50km radius
        radius_m = min(radius_m, 500000)  # max 500km radius

        # Severity scoring
        avg_goldstein = group['goldstein'].mean()
        total_mentions = group['mentions'].sum()
        avg_tone = group['tone'].mean()
        mention_score = np.log1p(total_mentions)

        # Combined severity: event count + media attention + negativity
        severity_score = (
            n_events * 0.4 +              # raw event count
            mention_score * 10 * 0.3 +     # media attention (log-scaled)
            abs(avg_goldstein) * 3 * 0.2 + # Goldstein negativity
            abs(min(avg_tone, 0)) * 0.1    # tone negativity
        )

        # Classify severity level
        if severity_score >= 100 or n_events >= 200:
            severity = 'critical'
        elif severity_score >= 40 or n_events >= 80:
            severity = 'high'
        elif severity_score >= 15 or n_events >= 30:
            severity = 'moderate'
        else:
            severity = 'low'

        # Determine primary country
        country_counts = group['ActionGeo_CountryCode'].value_counts()
        primary_fips = country_counts.index[0] if len(country_counts) > 0 else '??'
        country_name = FIPS_TO_NAME.get(primary_fips, primary_fips)

        # Determine primary conflict type
        group_copy = group.copy()
        group_copy['conflict_type'] = group_copy.apply(classify_conflict, axis=1)
        type_counts = group_copy['conflict_type'].value_counts()
        primary_type = type_counts.index[0] if len(type_counts) > 0 else 'Conflict'

        # Get secondary countries if multi-country zone
        secondary = []
        if len(country_counts) > 1:
            for cc in country_counts.index[1:4]:
                name = FIPS_TO_NAME.get(cc, cc)
                if name != country_name:
                    secondary.append(name)

        # Build zone name
        adm1_counts = group['ActionGeo_ADM1Code'].value_counts()
        region_hint = ''
        if len(adm1_counts) > 0:
            # Try to extract a readable region
            top_names = group['ActionGeo_FullName'].value_counts().head(3)
            region_parts = []
            for name in top_names.index:
                if isinstance(name, str) and name.strip():
                    parts = name.split(',')
                    region_parts.append(parts[0].strip())
            if region_parts:
                region_hint = ', '.join(region_parts[:2])

        zone_name = f"{country_name}"
        if secondary:
            zone_name += f" / {secondary[0]}"
        if region_hint and len(region_hint) < 40:
            zone_name += f" — {region_hint}"

        # Build detail string
        type_breakdown = ', '.join(
            f"{t}: {c}" for t, c in type_counts.head(3).items()
        )
        detail = (
            f"{n_events} conflict events detected in last analysis window. "
            f"Types: {type_breakdown}. "
            f"Avg Goldstein scale: {avg_goldstein:.1f}. "
            f"Media mentions: {int(total_mentions)}. "
            f"Avg tone: {avg_tone:.1f}."
        )

        zones.append({
            'name': zone_name,
            'lat': round(center_lat, 2),
            'lng': round(center_lng, 2),
            'radius': radius_m,
            'severity': severity,
            'type': primary_type,
            'since': 'Live',
            'detail': detail,
            'score': round(severity_score, 1),
            'events': n_events,
            'updated': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        })

    # Sort by severity score descending
    zones.sort(key=lambda z: z['score'], reverse=True)

    # Cap at top 30 zones
    zones = zones[:30]

    print(f"  Generated {len(zones)} conflict zones")
    for z in zones[:5]:
        print(f"    [{z['severity'].upper():8s}] {z['name']}: {z['events']} events (score: {z['score']})")
    if len(zones) > 5:
        print(f"    ... and {len(zones) - 5} more zones")

    return zones


# ── STEP 4: Fetch GDELT stability scores for validation ───────────────────
def fetch_stability_scores(country_codes):
    """Fetch GDELT Stability API scores for top countries (optional enrichment)."""
    scores = {}
    base = 'https://api.gdeltproject.org/api/v1/dash_stabilitytimeline/dash_stabilitytimeline'

    for fips in country_codes[:10]:  # limit to top 10
        try:
            url = f"{base}?LOC={fips}&VAR=instability&TIMERES=day&NUMDAYS=7&OUTPUT=csv"
            r = requests.get(url, timeout=15)
            if r.status_code == 200 and r.text.strip():
                lines = r.text.strip().split('\n')
                if len(lines) > 1:
                    # Average the instability values
                    vals = []
                    for line in lines[1:]:
                        parts = line.split(',')
                        if len(parts) >= 2:
                            try:
                                vals.append(float(parts[1]))
                            except ValueError:
                                pass
                    if vals:
                        scores[fips] = sum(vals) / len(vals)
        except Exception:
            continue

    return scores


# ── STEP 5: Output ─────────────────────────────────────────────────────────
def save_zones(zones, output_path):
    """Save conflict zones to JSON."""
    print(f"[5/5] Saving {len(zones)} zones to {output_path}...")

    output = {
        'generated': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'source': 'GDELT 2.0 Event Database',
        'zones': zones,
        'meta': {
            'clustering': 'DBSCAN (eps=150km, haversine)',
            'severity_factors': 'event_count(40%) + media_mentions(30%) + goldstein(20%) + tone(10%)',
            'update_frequency': 'Run every 6-12 hours for best results',
        }
    }

    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)

    # Also output a JS-embeddable version
    js_path = output_path.replace('.json', '.js')
    js_zones = json.dumps(zones, indent=2)
    with open(js_path, 'w') as f:
        f.write(f"// Auto-generated by update_conflicts.py\n")
        f.write(f"// Updated: {output['generated']}\n")
        f.write(f"// Source: {output['source']}\n\n")
        f.write(f"const LIVE_CONFLICT_ZONES = {js_zones};\n")

    print(f"  Saved JSON: {output_path}")
    print(f"  Saved JS:   {js_path}")
    return output


def embed_in_html(zones, html_path):
    """Optionally patch the SENTINEL HTML file with live zone data."""
    if not os.path.exists(html_path):
        print(f"  Warning: {html_path} not found, skipping embed")
        return

    print(f"  Embedding zones in {html_path}...")
    with open(html_path, 'r') as f:
        html = f.read()

    # Find and replace the CONFLICT_ZONES array
    pattern = r'const CONFLICT_ZONES = \[.*?\];'
    replacement = f'const CONFLICT_ZONES = {json.dumps(zones, indent=2)};'

    new_html, count = re.subn(pattern, replacement, html, flags=re.DOTALL)
    if count > 0:
        with open(html_path, 'w') as f:
            f.write(new_html)
        print(f"  ✓ Patched CONFLICT_ZONES in {html_path} ({count} replacement(s))")
    else:
        print(f"  Warning: Could not find CONFLICT_ZONES array in {html_path}")


# ── Main ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description='SENTINEL Conflict Zone Updater — Scrapes GDELT for live conflict data'
    )
    parser.add_argument('--days', type=int, default=2,
                        help='Lookback window in days (default: 2)')
    parser.add_argument('--max-files', type=int, default=50,
                        help='Max GDELT export files to download (default: 50)')
    parser.add_argument('--output', type=str, default='conflict_zones.json',
                        help='Output JSON file path')
    parser.add_argument('--embed', action='store_true',
                        help='Also patch sentinel-live.html with live data')
    parser.add_argument('--html', type=str, default='sentinel-live.html',
                        help='Path to sentinel HTML file for --embed')
    parser.add_argument('--eps-km', type=int, default=150,
                        help='DBSCAN clustering radius in km (default: 150)')
    parser.add_argument('--min-events', type=int, default=5,
                        help='Minimum events per cluster (default: 5)')
    args = parser.parse_args()

    print("=" * 60)
    print("SENTINEL — Conflict Zone Updater")
    print(f"Lookback: {args.days} days | Max files: {args.max_files}")
    print(f"Clustering: eps={args.eps_km}km, min_events={args.min_events}")
    print("=" * 60)

    # Step 1: Get GDELT URLs
    urls = get_recent_gdelt_urls(days=args.days)
    if not urls:
        print("No GDELT data available. Exiting.")
        sys.exit(1)

    # Step 2: Download and filter
    events = download_and_filter_events(urls, max_files=args.max_files)
    if len(events) == 0:
        print("No conflict events found. Exiting.")
        sys.exit(1)

    # Step 3: Cluster
    clustered = cluster_events(events, eps_km=args.eps_km, min_events=args.min_events)
    if len(clustered) == 0:
        print("No clusters formed. Try adjusting --eps-km or --min-events.")
        sys.exit(1)

    # Step 4: Build zones
    zones = build_zones(clustered)

    # Step 5: Save
    result = save_zones(zones, args.output)

    # Optional: embed in HTML
    if args.embed:
        embed_in_html(zones, args.html)

    print("\n✓ Done!")
    print(f"  {len(zones)} conflict zones generated from {len(events)} events")
    sev_counts = defaultdict(int)
    for z in zones:
        sev_counts[z['severity']] += 1
    for sev in ['critical', 'high', 'moderate', 'low']:
        if sev_counts[sev]:
            print(f"  {sev.upper():10s}: {sev_counts[sev]}")


if __name__ == '__main__':
    main()
