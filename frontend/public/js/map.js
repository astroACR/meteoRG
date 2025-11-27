// map.js

// inicia mapa
const map = L.map('map').setView([-33.45, -70.66], 6);

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap contributors'
}).addTo(map);

let currentVariable = "temperatura";
let stationData = null;
let filteredData = null;

// capas overlays
const firmsLayer = L.layerGroup();
const rainfallLayer = L.layerGroup();
const humidityHeatLayer = L.layerGroup();
const stationLayer = L.layerGroup();


firmsLayer.addTo(map);
rainfallLayer.addTo(map);
humidityHeatLayer.addTo(map);
stationLayer.addTo(map);

const overlays = {
  "Fire Hotspots (FIRMS)": firmsLayer,
  "Agua caída 24h footprint": rainfallLayer,
  "Humedad pseudo-heatmap": humidityHeatLayer,
  "Estaciones": stationLayer
};

L.control.layers(null, overlays).addTo(map);


// escalas de color (para leyenda)
function getColor(value, variable) {
  if (variable === "temperatura") {
    return value > 30 ? "#b10026" :
           value > 25 ? "#e31a1c" :
           value > 20 ? "#fc4e2a" :
           value > 15 ? "#fd8d3c" :
           value > 10 ? "#feb24c" :
           value > 5  ? "#fed976" :
                        "#ffffb2";
  }
  if (variable === "humedadRelativa") {
    return value > 80 ? "#08306b" :
           value > 60 ? "#2171b5" :
           value > 40 ? "#6baed6" :
           value > 20 ? "#c6dbef" :
                        "#f7fbff";
  }
  if (variable === "aguaCaida24Horas") {
    return value > 50 ? "#08306b" :
           value > 20 ? "#225ea8" :
           value > 10 ? "#1d91c0" :
           value > 5  ? "#41ab5d" :
           value > 0  ? "#74c476" :
                        "#edf8fb";
  }
  if (variable === "fuerzaDelViento_kmh") {
    return value > 50 ? "#54278f" :
           value > 30 ? "#756bb1" :
           value > 15 ? "#9e9ac8" :
           value > 5  ? "#cbc9e2" :
                        "#f2f0f7";
  }
  return "#999";
}

function getTextColor(variable) {
  return variable === "aguaCaida24Horas" ? "#111" : "#fff";
}

// Unidades
function getUnit(variable) {
  if (variable === "temperatura") return "°C";
  if (variable === "humedadRelativa") return "%";
  if (variable === "aguaCaida24Horas") return "mm";
  if (variable === "fuerzaDelViento_kmh") return "km/h";
  return "";
}

// leyenda
const legend = L.control({position: 'bottomright'});
legend.onAdd = function () {
  this._div = L.DomUtil.create('div', 'info legend');
  this.update();
  return this._div;
};
legend.update = function () {
  let grades, label;

  if (currentVariable === "temperatura") {
    grades = [0, 10, 20, 30];
    label = "Temperatura (°C)";
  } else if (currentVariable === "humedadRelativa") {
    grades = [20, 40, 60, 80];
    label = "Humedad (%)";
  } else if (currentVariable === "aguaCaida24Horas") {
    grades = [0, 5, 10, 20, 50];
    label = "Agua caída 24h (mm)";
  } else if (currentVariable === "fuerzaDelViento_kmh") {
    grades = [5, 15, 30, 50];
    label = "Viento (km/h)";
  } else {
    grades = [0]; //si falla, carga la variable igual
    label = currentVariable;
  }

  let html = `<b>${label}</b><br>`;
  for (let i = 0; i < grades.length; i++) {
    const from = grades[i];
    const to = grades[i + 1];
    html += `<i style="background:${getColor(from + 0.1, currentVariable)}"></i> ` +
            (to ? `${from}–${to}<br>` : `${from}+`);
  }
  this._div.innerHTML = html;
};
legend.addTo(map);

// clusters marcadores
let markers = L.markerClusterGroup({
  maxClusterRadius: 80,
  disableClusteringAtZoom: 8,
  iconCreateFunction: function (cluster) {
    const children = cluster.getAllChildMarkers();
    let sum = 0, count = 0;
    children.forEach(m => {
      const p = m.feature.properties;
      let value;
      if (currentVariable === "temperatura") value = p.temperatura;
      if (currentVariable === "humedadRelativa") value = p.humedadRelativa;
      if (currentVariable === "aguaCaida24Horas") value = p.aguaCaida24Horas;
      if (currentVariable === "fuerzaDelViento_kmh") value = p.fuerzaDelViento_kmh;
      if (typeof value === "number") { sum += value; count++; }
    });
    const avg = count > 0 ? sum / count : 0;
    const color = getColor(avg, currentVariable);

    return L.divIcon({
      html: `<div style="
                background:${color};
                border-radius:50%;
                width:42px; height:42px;
                display:flex; align-items:center; justify-content:center;
                color:${getTextColor(currentVariable)}; font-size:14px; font-weight:bold;
                box-shadow: 0 0 4px rgba(0,0,0,0.35);">
                ${cluster.getChildCount()}
             </div>`,
      className: ''
    });
  }
});

// filtro institucional
function filterByInstitution(data, institution) {
  if (!institution || institution === 'all') return data;
  return {
    type: "FeatureCollection",
    features: data.features.filter(f => f.properties.institucion_sigla === institution)
  };
}
function populateInstitutionFilter(data) {
  const select = document.getElementById('institutionFilter');
  if (!select) return;
  const institutions = Array.from(new Set(
    data.features.map(f => f.properties.institucion_sigla).filter(Boolean)
  )).sort();
  select.innerHTML = `<option value="all">Todas las instituciones</option>` +
    institutions.map(i => `<option value="${i}">${i}</option>`).join('');
  select.addEventListener('change', () => {
    const val = select.value;
    filteredData = filterByInstitution(stationData, val);
    renderStations(filteredData);
  });
}

function buildRainfallLayer(geojson) {
  rainfallLayer.clearLayers();
  geojson.features.forEach(f => {
    const p = f.properties;
    const [lon, lat] = f.geometry.coordinates;
    const val = Number(p.aguaCaida24Horas);
    if (isNaN(val)) return;

    const radius = Math.min(22000, Math.max(1500, val * 900));
    const color = getColor(val, "aguaCaida24Horas");

    L.circle([lat, lon], {
      radius,
      color,
      weight: 1,
      fillColor: color,
      fillOpacity: 0.25
    }).addTo(rainfallLayer);
  });
}

function buildHumidityHeatLayer(geojson) {
  humidityHeatLayer.clearLayers();
  geojson.features.forEach(f => {
    const p = f.properties;
    const [lon, lat] = f.geometry.coordinates;
    const val = Number(p.humedadRelativa);
    if (isNaN(val)) return;

    const baseRadius = 14000;
    const opacity = Math.min(0.5, Math.max(0.12, (val / 100) * 0.5));
    const color = "#2171b5";

    L.circle([lat, lon], {
      radius: baseRadius,
      color,
      weight: 0,
      fillColor: color,
      fillOpacity: opacity
    }).addTo(humidityHeatLayer);
  });
}

// Toggles
function isRainfallToggleOn() {
  const cb = document.getElementById('toggleRainfall');
  return cb && cb.checked;
}
function isHumidityToggleOn() {
  const cb = document.getElementById('toggleHumidity');
  return cb && cb.checked;
}
function isWindToggleOn() {
  const cb = document.getElementById('toggleWind');
  return cb && cb.checked;
}
function isFirmsToggleOn() {
  const cb = document.getElementById('toggleFirms');
  return cb && cb.checked;
}

function showRelevantToggles() {
  const rainCtl = document.getElementById('toggleRainfallContainer');
  const humCtl = document.getElementById('toggleHumidityContainer');
  const windCtl = document.getElementById('toggleWindContainer');
  if (rainCtl) rainCtl.style.display = (currentVariable === "aguaCaida24Horas") ? 'block' : 'none';
  if (humCtl) humCtl.style.display = (currentVariable === "humedadRelativa") ? 'block' : 'none';
  if (windCtl) windCtl.style.display = (currentVariable === "fuerzaDelViento_kmh") ? 'block' : 'none';
}

function getConfidenceColor(confidence) {
  switch (confidence) {
    case 'high': return 'red';
    case 'nominal': return 'orange';
    case 'low': return 'yellow';
    default: return 'gray';
  }
}

function getBrightnessRadius(brightness) {
  const base = 4;
  const scale = (brightness - 300) / 50;
  return Math.max(base, scale);
}

function updateLastUpdateUI(timestamp) {
  const el = document.getElementById("lastUpdate");
  if (el && timestamp) {
    const dt = new Date(timestamp);
    el.textContent = "Última actualización: " + dt.toLocaleString("es-CL");
  }
}

function fetchStations() {
  fetch("https://meteorg-service-93556534723.southamerica-west1.run.app/stations")
    .then(res => res.json())
    .then(payload => {
      const data = payload.geojson;
      const lastUpdate = payload.last_update;
      updateLastUpdateUI(lastUpdate);


      if (Array.isArray(data.features)) {
        stationData = data;
      } else if (Array.isArray(data)) {
        stationData = { type: "FeatureCollection", features: data };
      } else {
        stationData = data;
      }

      populateInstitutionFilter(stationData);
      filteredData = stationData;
      renderStations(filteredData);
    })
    .catch(err => console.error("Error fetching stations:", err));
}


function fetchFirms() {
  fetch("https://meteorg-service-93556534723.southamerica-west1.run.app/firms")
    .then(res => res.json())
    .then(payload => {
      const data = payload.geojson;
      const lastUpdate = payload.last_update;
      updateLastUpdateUI(lastUpdate);

      updateFirmsLayer(data);
    })
    .catch(err => console.error("Error fetching FIRMS:", err));
}

function updateFirmsLayer(data) {
  firmsLayer.clearLayers();
  L.geoJSON(data, {
    pointToLayer: (feature, latlng) => {
      const p = feature.properties;
      return L.circleMarker(latlng, {
        radius: getBrightnessRadius(p.brightness),
        fillColor: getConfidenceColor(p.confidence),
        color: 'black',
        weight: 1,
        fillOpacity: 0.8
      });
    },
    onEachFeature: (feature, layer) => {
      const p = feature.properties;
      layer.bindPopup(`
        🔥 <strong>Fuego Detectado</strong><br>
        Brillo: ${p.brightness}<br>
        Confianza: ${p.confidence}<br>
        Fecha: ${p.acq_date} ${p.acq_time} UTC<br>
        Satelite: ${p.satellite}<br>
      `);
    }
  }).addTo(firmsLayer);

  if (!isFirmsToggleOn()) {
    map.removeLayer(firmsLayer);
  }
}


setInterval(() => {
  fetchStations();
  fetchFirms();
}, 5 * 60 * 1000);


fetchStations();
fetchFirms();


function renderStations(data) {
  markers.clearLayers();
  rainfallLayer.clearLayers();
  humidityHeatLayer.clearLayers();

  const geoJsonLayer = L.geoJSON(data, {
    pointToLayer: (feature, latlng) => {
      const p = feature.properties;

      let value;
      if (currentVariable === "temperatura") value = p.temperatura;
      if (currentVariable === "humedadRelativa") value = p.humedadRelativa;
      if (currentVariable === "aguaCaida24Horas") value = p.aguaCaida24Horas;
      if (currentVariable === "fuerzaDelViento_kmh") value = p.fuerzaDelViento_kmh;

      const displayValue = (value === undefined || value === null) ? '' : value;

  
      const isWind = currentVariable === "fuerzaDelViento_kmh";
      const dirDeg = typeof p.direccionDelViento === "number" ? p.direccionDelViento : 0;
      const speed = typeof p.fuerzaDelViento_kmh === "number" ? p.fuerzaDelViento_kmh : 0;
      const innerRadius = 15; 

      const spikeLen = Math.min(32, Math.max(8, speed / 4.5));

      const spikeHTML = isWind ? `
        <div style="
          position:absolute;
          left:50%; top:50%;
          transform: translate(-50%, -50%) rotate(${dirDeg}deg);
          width:0; height:0;">
          <!-- white outline spike -->
          <div style="
            position:absolute;
            top:-${innerRadius + spikeLen + 6}px; left:-6px;
            border-left:6px solid transparent;
            border-right:6px solid transparent;
            border-bottom:${spikeLen + 6}px solid rgba(255,255,255,0.95);
            filter: drop-shadow(0 0 2px rgba(0,0,0,0.35));
          "></div>
          <!-- colored inner spike -->
          <div style="
            position:absolute;
            top:-${innerRadius + spikeLen}px; left:-4px;
            border-left:4px solid transparent;
            border-right:4px solid transparent;
            border-bottom:${spikeLen}px solid ${getColor(speed, 'fuerzaDelViento_kmh')};
          "></div>
        </div>
      ` : '';

      const html = `
        <div style="
          position: relative;
          width: 44px; height: 44px;
          border-radius: 50%;
          background: white;
          box-shadow: 0 0 4px rgba(0,0,0,0.4);
          display: flex; align-items: center; justify-content: center;">
          ${spikeHTML}
          <div style="
            width: 30px; height: 30px;
            border-radius: 50%;
            background:${getColor(value, currentVariable)};
            display:flex; align-items:center; justify-content:center;
            color:${getTextColor(currentVariable)}; font-size:12px; font-weight:bold;">
            ${displayValue}
          </div>
        </div>`;

      return L.marker(latlng, { icon: L.divIcon({ html, className: '' }) });
    },
    onEachFeature: (feature, layer) => {
      const p = feature.properties;

      let selectedValue;
      if (currentVariable === "temperatura") selectedValue = `🌡 Temp: <b>${p.temperatura} °C</b>`;
      if (currentVariable === "humedadRelativa") selectedValue = `💧 Humedad: <b>${p.humedadRelativa} %</b>`;
      if (currentVariable === "aguaCaida24Horas") selectedValue = `🌧 Precip (24h): <b>${p.aguaCaida24Horas} mm</b>`;
      if (currentVariable === "fuerzaDelViento_kmh") selectedValue = `💨 Viento: <b>${p.fuerzaDelViento_kmh} km/h (${p.direccionDelViento})</b>`;

   
      layer.bindPopup(`
        <div style="font-size:14px; line-height:1.4; min-width:240px;">
          <b>${p.nombreEstacion}</b><br>
          ${selectedValue}<br><hr>
          🌡 Temp: ${p.temperatura} °C<br>
          💧 Humedad: ${p.humedadRelativa} %<br>
          🌧 Precip (24h): ${p.aguaCaida24Horas} mm<br>
          💨 Viento: ${p.fuerzaDelViento_kmh} km/h (${p.direccionDelViento})
          <div style="margin-top:8px; font-size:12px; color:#555; border-top:1px solid #eee; padding-top:6px;">
            🕒 Momento: ${p.momento ?? '–'} • 🏛️ ${p.institucion_sigla ?? '–'} • 🗻 ${p.altura ?? '–'} m
          </div>
        </div>
      `, { maxWidth: 420, minWidth: 260 });
    }
  });


  stationLayer.clearLayers();     
  markers.clearLayers();           

  markers.addLayer(geoJsonLayer);  
  stationLayer.addLayer(markers);   

  map.addLayer(stationLayer);      

  if (currentVariable === "aguaCaida24Horas" && isRainfallToggleOn()) {
    buildRainfallLayer(data);
  }
  if (currentVariable === "humedadRelativa" && isHumidityToggleOn()) {
    buildHumidityHeatLayer(data);
  }

  legend.update();
}


// Cambio de variable con toggles
function updateVariable(variable) {
  currentVariable = variable;
  showRelevantToggles();

  if (stationData) {
    const select = document.getElementById('institutionFilter');
    filteredData = select ? filterByInstitution(stationData, select.value) : stationData;
    renderStations(filteredData);
  }

  document.querySelectorAll('#controls button').forEach(btn => btn.classList.remove('active'));
  const btn = document.querySelector(`#controls button[onclick="updateVariable('${variable}')"]`);
  if (btn) btn.classList.add('active');
}


['toggleRainfall', 'toggleHumidity', 'toggleWind'].forEach(id => {
  const el = document.getElementById(id);
  if (el) el.addEventListener('change', () => {
    if (!stationData) return;
    renderStations(filteredData || stationData);
  });
});

const firmsToggle = document.getElementById('toggleFirms');
if (firmsToggle) {
  firmsToggle.addEventListener('change', () => {
    if (firmsToggle.checked) {
      map.addLayer(firmsLayer);
    } else {
      map.removeLayer(firmsLayer);
    }
  });
}



showRelevantToggles();
