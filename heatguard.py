"""HeatGuard - single-file Flask app (cleaned)

This file provides a simple Flask app that serves a Leaflet UI and a few JSON
endpoints. It prefers local CSV/XLSX data and a sample GeoJSON for demo.

Usage:
  python heatguard.py
Environment variables:
  HEATGUARD_HOST (default 0.0.0.0)
  HEATGUARD_PORT (default 5000)
  HEATGUARD_DEBUG (0|1)
"""

import os
import math
from datetime import datetime, timedelta

try:
    from flask import Flask, jsonify, render_template, send_from_directory
except Exception:  # pragma: no cover - helpful message when flask missing
    raise SystemExit("Missing dependency: flask. Install with `pip install flask`")

try:
    import pandas as pd
except Exception:  # pragma: no cover
    pd = None

APP_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(APP_DIR, 'data')
STATIC_DIR = os.path.join(APP_DIR, 'static')
TEMPLATES_DIR = os.path.join(APP_DIR, 'templates')

app = Flask(__name__, static_folder='static', template_folder='templates')

# Configs
DATA_FILE_XLSX = os.path.join(DATA_DIR, 'heat_hospitals.xlsx')
DATA_FILE_CSV = os.path.join(DATA_DIR, 'heat_hospitals.csv')
GEOJSON_SAMPLE = os.path.join(DATA_DIR, 'india_states_sample.geojson')
DAYS_AHEAD = 5


def load_dataset():
    """Load dataset (xlsx preferred, fallback to csv). Returns a pandas.DataFrame or empty DataFrame.
    If pandas is not installed returns None.
    """
    if pd is None:
        print('pandas not available; endpoints that require data will return empty responses.')
        return None

    path = None
    if os.path.exists(DATA_FILE_XLSX):
        path = DATA_FILE_XLSX
    elif os.path.exists(DATA_FILE_CSV):
        path = DATA_FILE_CSV
    else:
        print('No dataset found in data/; endpoints will return empty responses.')
        return pd.DataFrame()

    try:
        if path.lower().endswith('.xlsx'):
            df = pd.read_excel(path, engine='openpyxl')
        else:
            df = pd.read_csv(path)
        df.columns = [str(c).strip().lower() for c in df.columns]
        return df
    except Exception as e:
        print('Error reading dataset:', e)
        return pd.DataFrame()


DF = load_dataset()


def compute_state_summary(df=None):
    if pd is None:
        return []
    if df is None:
        df = DF
    if df is None or df.empty or 'state' not in df.columns:
        return pd.DataFrame(columns=['state', 'temp', 'aqi', 'hospital_cases', 'lat', 'lon'])

    temp_col = None
    for t in ('temperature', 'temp', 'heat_level'):
        if t in df.columns:
            temp_col = t
            break

    summary = pd.DataFrame({'state': df['state'].unique()})
    if temp_col:
        temps = df.groupby('state')[temp_col].mean().reset_index().rename(columns={temp_col: 'temp'})
        summary = summary.merge(temps, on='state', how='left')
    else:
        summary['temp'] = None

    if 'aqi' in df.columns:
        aqi = df.groupby('state')['aqi'].mean().reset_index()
        summary = summary.merge(aqi, on='state', how='left')

    if 'hospital_cases' in df.columns:
        hosp = df.groupby('state')['hospital_cases'].sum().reset_index()
        summary = summary.merge(hosp, on='state', how='left')

    if 'lat' in df.columns and 'lon' in df.columns:
        coords = df.groupby('state')[['lat', 'lon']].mean().reset_index()
        summary = summary.merge(coords, on='state', how='left')
    else:
        summary['lat'] = None
        summary['lon'] = None

    return summary


def build_forecast(days=DAYS_AHEAD):
    summary = compute_state_summary()
    if isinstance(summary, list) or summary is None or summary.empty:
        return []
    today = datetime.utcnow().date()
    rows = []
    for _, r in summary.iterrows():
        base = None
        try:
            if r['temp'] is None or (isinstance(r['temp'], float) and math.isnan(r['temp'])):
                base = None
            else:
                base = float(r['temp'])
        except Exception:
            base = None

        offsets = [0.0] + [0.5 + 0.2 * i for i in range(1, days + 1)]
        for i, off in enumerate(offsets):
            d = today + timedelta(days=i)
            temp = None if base is None else round(base + off, 2)
            rows.append({'state': r['state'], 'date': d.isoformat(), 'temp': temp, 'lat': r.get('lat'), 'lon': r.get('lon')})
    return rows


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/geojson')
def api_geojson():
    if not os.path.exists(GEOJSON_SAMPLE):
        return jsonify({'error': 'GeoJSON sample not found on server.'}), 500
    import json
    with open(GEOJSON_SAMPLE, 'r', encoding='utf-8') as f:
        gj = json.load(f)

    summary = compute_state_summary()
    temp_map = {}
    if not (summary is None) and not getattr(summary, 'empty', True):
        for _, r in summary.iterrows():
            name = str(r['state']).strip().lower()
            temp = r.get('temp')
            if isinstance(temp, float) and math.isnan(temp):
                temp = None
            temp_map[name] = temp

    for feat in gj.get('features', []):
        props = feat.setdefault('properties', {})
        name = str(props.get('name') or props.get('state') or '').strip().lower()
        props['temp'] = temp_map.get(name)

    return jsonify(gj)


@app.route('/api/forecast')
def api_forecast():
    return jsonify(build_forecast(DAYS_AHEAD))


@app.route('/api/heat_summary')
def api_heat_summary():
    df = compute_state_summary()
    if df is None:
        return jsonify([])
    return jsonify(df.fillna('').to_dict(orient='records'))


@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory(STATIC_DIR, filename)


if __name__ == '__main__':
    host = os.getenv('HEATGUARD_HOST', '0.0.0.0')
    port = int(os.getenv('HEATGUARD_PORT', '5000'))
    debug = os.getenv('HEATGUARD_DEBUG', '0') in ('1', 'true', 'True')
    print('Starting HEAT GUARD...')
    print('Host:', host, 'Port:', port, 'Debug:', debug)
    print('Data dir:', DATA_DIR)
    app.run(debug=debug, host=host, port=port)