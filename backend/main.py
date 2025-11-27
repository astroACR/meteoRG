from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from function import fetch_station_data, stations_to_geojson, fetch_firms_geojson
from google.cloud import secretmanager
from datetime import datetime, timedelta
import os, json

app = FastAPI(title="MeteoRG Dashboard API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://meteorg-474500.web.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

cache = {
    "stations": {"data": None, "expires": datetime.min, "last_update": None},
    "firms": {"data": None, "expires": datetime.min, "last_update": None}
}
CACHE_TTL = timedelta(minutes=5)

def get_secret(secret_id: str) -> str:
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{os.environ['GCP_PROJECT']}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")

def get_cached(key, fetch_func, *args):
    now = datetime.utcnow()
    if cache[key]["data"] is None or now >= cache[key]["expires"]:
        raw = fetch_func(*args)
        geojson = raw if isinstance(raw, dict) else json.loads(raw)
        cache[key]["data"] = geojson
        cache[key]["expires"] = now + CACHE_TTL
        cache[key]["last_update"] = now
    return cache[key]["data"], cache[key]["last_update"]

@app.get("/stations")
def get_stations():
    try:
        USER_DMC = get_secret("USER_DMC")
        API_DMC_KEY = get_secret("DMC_API_KEY")

        def fetch_and_convert():
            df = fetch_station_data(USER_DMC, API_DMC_KEY)
            return stations_to_geojson(df)
        
        data, last_update = get_cached("stations", fetch_and_convert)
        return JSONResponse(content={
            "last_update": last_update.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "geojson": data
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/firms")
def get_firms():
    try:
        coords = "-80,-60,-60,-15"
        MAP_KEY = get_secret("FIRMS_MAP_KEY")
        data, last_update = get_cached("firms", fetch_firms_geojson, MAP_KEY, coords)
        return JSONResponse(content={
            "last_update": last_update.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "geojson": data
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
def health():
    return {"status": "OK"}
