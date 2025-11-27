import requests
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from bs4 import BeautifulSoup
import ee
import datetime
from datetime import datetime, timedelta
import json

# Cache containers
cache = {
    "stations": {"data": None, "expires": datetime.min, "last_update": None},
    "firms": {"data": None, "expires": datetime.min, "last_update": None}
}

CACHE_TTL = timedelta(minutes=5)  # adjust to 10 if needed

def stations_to_geojson(df):
    # Columns to include in GeoJSON properties
    props_cols = [
        "nombreEstacion", "altura", "institucion_sigla",
        "aguaCaida24Horas", "temperatura", "humedadRelativa",
        "fuerzaDelViento_kmh", "direccionDelViento", "momento"
    ]

    features = []
    for _, row in df.iterrows():
        try:
            lon, lat = float(row["longitud"]), float(row["latitud"])
            properties = {col: row[col] for col in props_cols if col in row and pd.notna(row[col])}
            properties["id"] = str(row.get("codigo", ""))  # optional unique ID
            feature = {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [lon, lat]
                },
                "properties": properties
            }
            features.append(feature)
        except Exception as e:
            print(f"⚠️ Skipping row due to invalid geometry: {e}")

    geojson = {
        "type": "FeatureCollection",
        "features": features
    }

    return geojson

def fetch_station_data(USER_DMC, API_DMC_KEY):

    cols = [
        "nombreEstacion", "altura", "latitud", "longitud", "institucion_sigla",
        "aguaCaida24Horas", "temperatura", "humedadRelativa",
        "fuerzaDelViento_kmh", "direccionDelViento", "momento"
    ]

    def safe_to_numeric(series, decimal_comma=True, verbose=False):
        cleaned = series.astype(str).str.strip()

        if decimal_comma:
            cleaned = cleaned.str.replace(",", ".", regex=False)

        numeric = cleaned.str.extract(r"([-+]?\d*\.?\d+)")[0]

        numeric = pd.to_numeric(numeric, errors="coerce")

        if verbose:
            total = len(series)
            lost = numeric.isna().sum()
            print(f"🔍 Extracted numeric from {total} values, {lost} failed.")

        return numeric
    
    print("Iniciando fetch_station_data")

    def load_DMC_data():
        url = (
            f'https://climatologia.meteochile.gob.cl/application/servicios/getDatosRecientesRedEma?usuario={USER_DMC}&token={API_DMC_KEY}'
        )
        resp = requests.get(url, timeout=10)
        data = resp.json()

        try:
            estaciones = data.get("datosEstaciones", [])
            if isinstance(estaciones, dict):
                estaciones = [estaciones]
        except Exception as e:
            print(f"❌ Error obteniendo datos de DMC: {e}")
            return pd.DataFrame(columns=cols)
        if not estaciones:
            print("⚠️ No se encontraron estaciones en los datos de DMC.")
            return pd.DataFrame(columns=cols)
        
        rows = []
        for e in estaciones:
            est = e.get("estacion", {}) or {}
            datos = e.get("datos", {}) or {}
            if isinstance(datos, list):
                datos = datos[0] if datos else {}
            row = {**est, **datos}
            rows.append(row)

        df = pd.DataFrame(rows)

        if "fuerzaDelViento" in df.columns:
            df["fuerzaDelViento_clean"] = (
                df["fuerzaDelViento"]
                .astype(str)
                .str.replace("kt", "", regex=False)
                .str.strip()
            )
            df["fuerzaDelViento_clean"] = safe_to_numeric(df["fuerzaDelViento_clean"], )
            df["fuerzaDelViento_kmh"] = df["fuerzaDelViento_clean"] * 1.852
            df["fuerzaDelViento_kmh"] = df["fuerzaDelViento_kmh"].round(1)

        if "momento" in df.columns:
            df["momento"] = pd.to_datetime(df["momento"], errors="coerce", utc=True)
            df["momento"] = df["momento"].dt.tz_convert("America/Santiago")
            df["momento"] = df["momento"].dt.tz_localize(None)

        unnormalized_columns = ["temperatura", "humedadRelativa", "aguaCaida24Horas", "direccionDelViento", "fuerzaDelViento"]

        for col in unnormalized_columns:
            df[col] = safe_to_numeric(df[col], decimal_comma=True)

        def fix_encoding(series):
            return series.astype(str).apply(lambda x: x.encode("latin1").decode("utf-8") if isinstance(x, str) else x)

        df["nombreEstacion"] = fix_encoding(df["nombreEstacion"])

        df["institucion_sigla"] = "DMC"
        return df

    def load_agromet_data_latest_only():
        def get_tmp_folder():
            html = requests.get("https://agrometeorologia.cl", timeout=10).text
            soup = BeautifulSoup(html, "html.parser")
            return soup.find(attrs={"data-ts-map-tmp": True}).get("data-ts-map-tmp")

        def load_variable(var_key, json_key):
            url = f"https://agrometeorologia.cl/json/{tmp_folder}/items-{var_key}.json?"
            try:
                data = requests.get(url, timeout=10).json()
            except Exception as e:
                print(f"⚠️ Failed to load {var_key}: {e}")
                return pd.DataFrame()

            rows = []
            for entry in data:
                stack_hour = entry.get("STACK-HOUR", {})
                if not isinstance(stack_hour, dict) or not stack_hour:
                    continue

                for timestamp, value_dict in stack_hour.items():
                    value = value_dict.get(json_key)
                    if value is None:
                        continue

                    rows.append({
                        "codigo": entry.get("id"),
                        "nombreEstacion": entry.get("nombre"),
                        "latitud": entry.get("latitud"),
                        "longitud": entry.get("longitud"),
                        "altura": entry.get("elevacion"),
                        "institucion_sigla": entry.get("institucion_sigla"),
                        "momento": timestamp,
                        json_key: str(value).replace(",", ".")
                    })

            if not rows:
                return pd.DataFrame()

            df = pd.DataFrame(rows)
            df["momento"] = pd.to_datetime(df["momento"], errors="coerce")
            df[json_key] = pd.to_numeric(df[json_key], errors="coerce")
            return df

        tmp_folder = get_tmp_folder()

        # Load variables
        df_temp  = load_variable("ta", "TA-AVG")
        df_prec  = load_variable("pp", "PP-SUM")
        df_wind  = load_variable("vv", "VV-AVG")
        df_humid = load_variable("hr", "HR-AVG")
        df_wdir  = load_variable("vv", "DV-AVG")

        # Combine all
        dfs = [df_temp, df_prec, df_wind, df_humid, df_wdir]
        df_all = pd.concat([d for d in dfs if d is not None and not d.empty], ignore_index=True)

        # Rename columns
        df_all = df_all.rename(columns={
            "TA-AVG": "temperatura",
            "PP-SUM": "aguaCaida24Horas",
            "VV-AVG": "fuerzaDelViento_kmh",
            "HR-AVG": "humedadRelativa",
            "DV-AVG": "direccionDelViento"
        })

        # Filter institutions
        df_all["source"] = "Agromet"
        df_all = df_all[~df_all["institucion_sigla"].isin(["DMC","MMA-DMC"])]

        # Group by station and keep latest timestamp
        keys = ["codigo", "nombreEstacion", "latitud", "longitud", "institucion_sigla", "altura"]
        df_latest = df_all.sort_values("momento").groupby(keys, as_index=False).last()

        return df_latest

    def merge_station_datasets(df_dmc, df_agro, debug=False):

        key_vars = ["aguaCaida24Horas","temperatura","humedadRelativa",
                    "fuerzaDelViento_kmh","direccionDelViento"]

        df_dmc = df_dmc[[c for c in cols if c in df_dmc.columns]].copy()
        df_agro = df_agro[[c for c in cols if c in df_agro.columns]].copy()

        df_merged = pd.concat([df_dmc, df_agro], ignore_index=True)
        if debug:
            print("Concatenado:", df_merged.shape)
            print("Nulls tras concat:\n", df_merged[key_vars].isna().sum())

        df_merged["latitud"] = pd.to_numeric(df_merged["latitud"], errors="coerce")
        df_merged["longitud"] = pd.to_numeric(df_merged["longitud"], errors="coerce")    

        df_merged["lat_rounded"] = df_merged["latitud"].round(2)
        df_merged["lon_rounded"] = df_merged["longitud"].round(2)

        df_merged = df_merged.drop_duplicates(
            subset=["nombreEstacion","lat_rounded","lon_rounded"], keep="first")

        df_merged = df_merged.dropna(subset=["latitud","longitud"])
        df_merged = df_merged.dropna(how="all", subset=key_vars)

        df_merged = df_merged.drop(columns=["lat_rounded","lon_rounded"])
        df_merged["codigo"] = range(1, len(df_merged)+1)

        def replace_nan_with_si(df, cols):
            df = df.copy()
            for c in cols:
                if c in df.columns:
                    df[c] = df[c].fillna("s/i")
            return df

        df_merged = replace_nan_with_si(df_merged, key_vars)

        return df_merged

    df_dmc = load_DMC_data()
    if df_dmc is None or df_dmc.empty:
        print("⚠️ No se pudo cargar datos de DMC.")
        df_dmc = pd.DataFrame(columns=cols)
    else:
        print(f"✅Datos DMC cargados: {len(df_dmc)} estaciones.") 

    df_agromet = load_agromet_data_latest_only()
    if df_agromet is None or df_agromet.empty:
        print("⚠️ No se pudo cargar datos de Agromet.")
        df_agromet = pd.DataFrame(columns=cols)
    else:
        print(f"✅Datos Agromet cargados: {len(df_agromet)} estaciones.")

    df_stations = merge_station_datasets(df_dmc, df_agromet, debug=False)
    if df_stations is None or df_stations.empty:
        print("⚠️ No se pudo combinar datos de estaciones.")
        df_stations = pd.DataFrame(columns=cols)
    else:
        print(f"✅Datos combinados: {len(df_stations)} estaciones.")


    return df_stations

def fetch_firms_geojson(map_key, coords):
    url = f'https://firms.modaps.eosdis.nasa.gov/api/area/csv/{map_key}/MODIS_NRT/{coords}/1'
    df = pd.read_csv(url)

    df['acq_time'] = df['acq_time'].astype(str).str.zfill(4)
    df['time'] = pd.to_datetime(df['acq_date'] + ' ' + df['acq_time'], errors='coerce').dt.strftime('%Y-%m-%dT%H:%M:%SZ')

    df = df.dropna(subset=['time'])

    # Create GeoDataFrame
    gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.longitude, df.latitude))
    gdf.set_crs(epsg=4326, inplace=True)

    # Select relevant fields
    gdf = gdf[['brightness', 'confidence', 'acq_date', 'acq_time', 'satellite', 'daynight', 'time', 'geometry']]

    return gdf.to_json()

def get_cached(key, fetch_func, *args):
    """Generic cache wrapper"""
    now = datetime.utcnow()
    if cache[key]["data"] is None or now >= cache[key]["expires"]:
        # Refresh cache
        geojson_str = fetch_func(*args)
        geojson_obj = json.loads(geojson_str)
        cache[key]["data"] = geojson_obj
        cache[key]["expires"] = now + CACHE_TTL
        cache[key]["last_update"] = now
    return cache[key]["data"], cache[key]["last_update"]