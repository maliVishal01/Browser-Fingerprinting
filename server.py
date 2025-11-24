from flask import Flask, request, jsonify, render_template
import datetime
import json
import requests
import re
import sqlite3
import os

app = Flask(__name__)

# ---------- Database Setup ----------
def init_db():
    conn = sqlite3.connect('visitor_logs.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS visitor_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            ip TEXT,
            city TEXT,
            region TEXT,
            country TEXT,
            userAgent TEXT,
            platform TEXT,
            screenWidth INTEGER,
            screenHeight INTEGER,
            language TEXT,
            lat REAL,
            lon REAL,
            battery_level INTEGER,
            charging BOOLEAN,
            deviceName TEXT,
            browser_city TEXT,
            browser_region TEXT,
            browser_country TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# ---------- Utility Functions ----------
def get_client_ip():
    if request.headers.getlist("X-Forwarded-For"):
        ip = request.headers.getlist("X-Forwarded-For")[0].split(',')[0]
    else:
        ip = request.remote_addr
    return ip

def is_public_ip(ip):
    private_prefixes = ('10.', '172.', '192.', '127.', '0.')
    return not ip.startswith(private_prefixes)

def parse_device_name(user_agent):
    match = re.search(r'\(([^)]+)\)', user_agent)
    return match.group(1) if match else "Unknown"

# ✅ Reverse geocoding using OpenStreetMap Nominatim
def reverse_geocode(lat, lon):
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lon, "format": "json"},
            headers={"User-Agent": "FlaskApp"}
        )
        if resp.status_code == 200:
            data = resp.json()
            return {
                "display_name": data.get("display_name"),
                "city": data.get("address", {}).get("city") or data.get("address", {}).get("town") or data.get("address", {}).get("village"),
                "region": data.get("address", {}).get("state"),
                "country": data.get("address", {}).get("country")
            }
    except requests.RequestException:
        return {"error": "Reverse geocoding failed"}
    return {}

# ---------- Routes ----------
@app.route('/')
def index():
    conn = sqlite3.connect('visitor_logs.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM visitor_logs ORDER BY timestamp DESC')
    logs = cursor.fetchall()
    conn.close()
    return render_template('index.html', logs=logs)

@app.route('/submit-device-info', methods=['POST'])
def submit_device_info():
    visitor_ip = get_client_ip()
    client_data = request.json or {}

    # IP-based location
    location = {}
    if is_public_ip(visitor_ip):
        try:
            resp = requests.get(f'https://ipinfo.io/{visitor_ip}/json', timeout=5)
            if resp.status_code == 200:
                loc_json = resp.json()
                location = {
                    'city': loc_json.get('city', ''),
                    'region': loc_json.get('region', ''),
                    'country': loc_json.get('country', '')
                }
        except requests.RequestException:
            location = {'error': 'Failed to get geo info'}
    else:
        location = {'info': 'Local or private IP - no geo lookup'}

    # Browser geolocation reverse lookup
    browser_lat = client_data.get('location', {}).get('lat')
    browser_lon = client_data.get('location', {}).get('lon')
    browser_place = None
    if browser_lat and browser_lon:
        browser_place = reverse_geocode(browser_lat, browser_lon)

    ua = client_data.get('userAgent', '')
    device_name = parse_device_name(ua)
    client_data['deviceName'] = device_name

    # ✅ Timestamp in AM/PM format
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")

    record = {
        'timestamp': timestamp,
        'ip': visitor_ip,
        'location': location,
        'browser_place': browser_place,
        'client_info': client_data
    }

    # ✅ Daily log rotation filename
    log_filename = f"visitor_log_{datetime.date.today().isoformat()}.txt"

    # Save to text file (flush immediately)
    with open(log_filename, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, indent=4) + '\n\n')
        f.flush()

    # Save to database
    conn = sqlite3.connect('visitor_logs.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO visitor_logs (
            timestamp, ip, city, region, country, userAgent, platform,
            screenWidth, screenHeight, language, lat, lon,
            battery_level, charging, deviceName,
            browser_city, browser_region, browser_country
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        record['timestamp'],
        record['ip'],
        location.get('city'),
        location.get('region'),
        location.get('country'),
        client_data.get('userAgent'),
        client_data.get('platform'),
        client_data.get('screenWidth'),
        client_data.get('screenHeight'),
        client_data.get('language'),
        browser_lat,
        browser_lon,
        client_data.get('battery', {}).get('level'),
        client_data.get('battery', {}).get('charging'),
        client_data.get('deviceName'),
        browser_place.get('city') if browser_place else None,
        browser_place.get('region') if browser_place else None,
        browser_place.get('country') if browser_place else None
    ))
    conn.commit()
    conn.close()
    print("---- New Visitor Log ----")
    print(json.dumps(record, indent=4))
    print("-------------------------\n")

    return jsonify({"status": "Data logged successfully", "browser_place": browser_place})

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)
