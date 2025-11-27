from flask import Flask, jsonify, make_response
from flask_cors import CORS
from function import fetch_station_data, stations_to_geojson, fetch_firms_geojson
from google.cloud import secretmanager
from datetime import datetime, timedelta
import os
import json
from datetime import timezone

app = Flask(__name__)
CORS(app)

# --- Cache containers ---
cache = {
    "stations": {"data": None, "expires": datetime.min, "last_update": None},
    "firms": {"data": None, "expires": datetime.min, "last_update": None}
}
CACHE_TTL = timedelta(minutes=5)  # adjust to 10 if needed

def get_secret(secret_id):
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{os.environ['GCP_PROJECT']}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")

def get_cached(key, fetch_func, *args):
    """Generic cache wrapper"""
    now = datetime.now(timezone.utc)
    if cache[key]["data"] is None or now >= cache[key]["expires"]:
        geojson_str = fetch_func(*args)
        # fetch_station_data returns DF, so handle separately outside
        if isinstance(geojson_str, dict):
            geojson_obj = geojson_str
        else:
            geojson_obj = json.loads(geojson_str)
        cache[key]["data"] = geojson_obj
        cache[key]["expires"] = now + CACHE_TTL
        cache[key]["last_update"] = now
    return cache[key]["data"], cache[key]["last_update"]

@app.route("/stations")
def stations():
    try:
        USER_DMC = get_secret("USER_DMC")
        API_DMC_KEY = get_secret("DMC_API_KEY")

        def fetch_and_convert():
            df = fetch_station_data(USER_DMC, API_DMC_KEY)
            return stations_to_geojson(df)

        data, last_update = get_cached("stations", fetch_and_convert)
        response = make_response(jsonify({
            "last_update": last_update.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "geojson": data
        }))
        response.headers["Access-Control-Allow-Origin"] = "https://meteorg-474500.web.app"
        return response
    except Exception as e:
        print(f"❌ Error in /stations: {e}")
        response = make_response(jsonify({"error": str(e)}), 500)
        response.headers["Access-Control-Allow-Origin"] = "https://meteorg-474500.web.app"
        return response

@app.route("/firms")
def firms_api():
    try:
        coordenadasSA = '-75,-55,-66,-17'
        MAP_KEY = get_secret("FIRMS_MAP_KEY")
        data, last_update = get_cached("firms", fetch_firms_geojson, MAP_KEY, coordenadasSA)
        return jsonify({
            "last_update": last_update.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "geojson": data
        })
    except Exception as e:
        print(f"❌ Error in /firms: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/health")
def health():
    return "OK", 200
