/* =========================================================================
   WeatherGPT frontend.
   Talks to the FastAPI backend for everything data-driven. The map centres and
   overlays react to each answer's `map` state. No hard-coded location markers:
   the only marker that ever appears is a single pin for the place the user
   actually asked about (or clicked).
   ========================================================================= */
"use strict";

const API = {
  config: "/api/config",
  chat: "/api/chat",
  weather: "/api/weather",
  rivers: "/api/rivers",
  wind: "/api/wind",
  alerts: "/api/alerts",
};

const state = {
  mode: "layman",
  lang: "en",
  caps: null,
  activeLayer: null,      // "radar" | "clouds" | "temp" | "wind" | "rivers" | null
  riverLayer: null,
  queryMarker: null,
  radar: { frames: [], idx: 0, timer: null, layer: null, host: "" },
};

/* ------------------------------ DOM refs -------------------------------- */
const $ = (id) => document.getElementById(id);
const thread = $("thread");
const input = $("chatInput");
const form = $("composer");

/* ------------------------------ Map init -------------------------------- */
const map = L.map("map", { zoomControl: true, minZoom: 3, maxZoom: 18, worldCopyJump: true })
  .setView([22.5, 80.5], 5);

// Keyless base layers. OSM by default; Esri World Imagery for satellite.
// (Google Maps can replace this base — see README — but it needs a browser key
//  and, crucially, provides none of the weather/river data layers below.)
const baseStreets = L.tileLayer(
  "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
  { attribution: "&copy; OpenStreetMap contributors", subdomains: "abc", maxZoom: 19 }
);
const baseSat = L.tileLayer(
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
  { attribution: "Imagery &copy; Esri", maxZoom: 19 }
);
baseStreets.addTo(map);
setTimeout(() => map.invalidateSize(), 150);
window.addEventListener("load", () => map.invalidateSize());
window.addEventListener("resize", () => map.invalidateSize());

/* --------------------- Weather tile overlay layers ---------------------- */
// RainViewer: real, keyless, animated precipitation radar (past frames).
async function loadRadarFrames() {
  try {
    const meta = await fetch("https://api.rainviewer.com/public/weather-maps.json").then(r => r.json());
    state.radar.host = meta.host;
    state.radar.frames = (meta.radar && meta.radar.past ? meta.radar.past : []).slice(-10);
    state.radar.satellite = (meta.satellite && meta.satellite.infrared ? meta.satellite.infrared : []).slice(-6);
    state.radar.idx = state.radar.frames.length - 1;
    return state.radar.frames.length > 0;
  } catch { return false; }
}
function radarTile(frame) {
  return L.tileLayer(
    `${state.radar.host}${frame.path}/512/{z}/{x}/{y}/4/1_1.png`,
    { opacity: 0.7, attribution: "Radar &copy; RainViewer" }
  );
}
function showRadarFrame() {
  const f = state.radar.frames[state.radar.idx];
  if (!f) return;
  if (state.radar.layer) map.removeLayer(state.radar.layer);
  state.radar.layer = radarTile(f).addTo(map);
  const d = new Date(f.time * 1000);
  $("radarTs").textContent = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
function startRadarAnim() {
  stopRadarAnim();
  state.radar.timer = setInterval(() => {
    state.radar.idx = (state.radar.idx + 1) % state.radar.frames.length;
    showRadarFrame();
  }, 700);
}
function stopRadarAnim() { if (state.radar.timer) { clearInterval(state.radar.timer); state.radar.timer = null; } }

// RainViewer also offers keyless infrared satellite (cloud) frames.
function loadSatelliteFrame() {
  const sat = state.radar.satellite;
  if (!sat || !sat.length) return null;
  const f = sat[sat.length - 1];
  return L.tileLayer(`${state.radar.host}${f.path}/512/{z}/{x}/{y}/0/0_0.png`,
    { opacity: 0.75, attribution: "Satellite &copy; RainViewer" });
}

// OpenWeatherMap tile layers (need a key; only temp still requires this).
function owmLayer(kind) {
  const key = state.caps?.openweather_key;
  if (!key) return null;
  const id = { clouds: "clouds_new", temp: "temp_new", wind: "wind_new", rain: "precipitation_new" }[kind];
  return L.tileLayer(`https://tile.openweathermap.org/map/${id}/{z}/{x}/{y}.png?appid=${key}`,
    { opacity: 0.6, attribution: "&copy; OpenWeatherMap" });
}

let owmOverlay = null, satOverlay = null;
function clearWeatherOverlays() {
  stopRadarAnim();
  stopWind();
  if (state.radar.layer) { map.removeLayer(state.radar.layer); state.radar.layer = null; }
  if (owmOverlay) { map.removeLayer(owmOverlay); owmOverlay = null; }
  if (satOverlay) { map.removeLayer(satOverlay); satOverlay = null; }
  $("radarCtl").classList.remove("show");
  hideLegend();
}

/* Apply the map layer the backend asked for. */
async function applyLayer(layer) {
  clearWeatherOverlays();
  state.activeLayer = layer;
  setLayerButtons(layer);
  if (!layer || layer === "rivers" || layer === "flood" || layer === "alerts") return;

  if (layer === "radar" || layer === "rain") {
    const ok = state.radar.frames.length || await loadRadarFrames();
    if (ok) {
      showRadarFrame(); startRadarAnim(); $("radarCtl").classList.add("show");
      showLegend("Rainfall (radar)", ["Light", "Heavy"],
        "linear-gradient(90deg,#7fd6ff,#3aa0ff,#2b5bd6,#8b3ad6)", "RainViewer · near-real-time");
    } else { botNote("Rain radar is temporarily unavailable. Please retry in a moment."); }
    return;
  }

  if (layer === "clouds") {
    if (!state.radar.host) await loadRadarFrames();
    satOverlay = loadSatelliteFrame();
    if (satOverlay) {
      satOverlay.addTo(map);
      showLegend("Cloud cover (infrared)", ["Clear", "Thick"],
        "linear-gradient(90deg,#20303a,#5b7280,#9fb2bd,#eef3f6)", "RainViewer satellite");
    } else { botNote("Cloud imagery is temporarily unavailable. Please retry shortly."); }
    return;
  }

  if (layer === "wind") {
    await startWind();  // real Open-Meteo wind field, animated
    return;
  }

  // temp -> OWM (needs key)
  const l = owmLayer(layer);
  if (l) {
    owmOverlay = l.addTo(map);
    showLegend("Temperature", ["Cool", "Warm"],
      "linear-gradient(90deg,#4a7fd6,#4ad6a7,#e6b34a,#e0674f)", "OpenWeatherMap");
  } else {
    botNote(`The temperature tile layer needs an OpenWeatherMap key (optional). ` +
      `Rain radar, clouds and wind all work without a key.`);
    setLayerButtons(null);
    state.activeLayer = null;
  }
}

/* --------------------- Data-driven wind animation ----------------------- */
// Particles flow along a REAL wind field sampled from Open-Meteo (/api/wind).
const wind = {
  canvas: document.getElementById("windCanvas"),
  ctx: document.getElementById("windCanvas").getContext("2d"),
  field: null, particles: [], raf: null, bbox: null,
};
function sizeWindCanvas() {
  const r = document.getElementById("map").getBoundingClientRect();
  wind.canvas.width = r.width; wind.canvas.height = r.height;
}
sizeWindCanvas();
window.addEventListener("resize", sizeWindCanvas);
map.on("resize", sizeWindCanvas);

function windAt(lat, lon) {
  // Inverse-distance interpolation of the sampled grid.
  const pts = wind.field?.points || [];
  if (!pts.length) return null;
  let sx = 0, sy = 0, sw = 0;
  for (const p of pts) {
    const d2 = (p.lat - lat) ** 2 + (p.lon - lon) ** 2 + 0.05;
    const w = 1 / d2;
    const toward = ((p.dir ?? 0) + 180) * Math.PI / 180; // met "from" -> "to"
    const spd = Math.max(0.5, (p.speed ?? 0));
    sx += Math.sin(toward) * spd * w;
    sy += Math.cos(toward) * spd * w;
    sw += w;
  }
  if (!sw) return null;
  return { u: sx / sw, v: sy / sw };
}
function spawnWindParticle() {
  const b = wind.bbox; // [s,w,n,e]
  return {
    lat: b[0] + Math.random() * (b[2] - b[0]),
    lon: b[1] + Math.random() * (b[3] - b[1]),
    age: Math.random() * 90, maxAge: 60 + Math.random() * 70,
  };
}
async function startWind() {
  const c = map.getCenter();
  showLegend("Wind (10 m)", ["Calm", "Strong"],
    "linear-gradient(90deg,#2a4a55,#4ad6a7,#e6b34a,#e0674f)", "Open-Meteo · loading…");
  let data;
  try {
    data = await fetch(`${API.wind}?lat=${c.lat.toFixed(2)}&lon=${c.lng.toFixed(2)}&half=5`).then(r => r.json());
  } catch { data = null; }
  if (!data || !data.ok || !data.points.length) {
    botNote("Live wind data isn't available for this area right now. Try zooming to a region over land.");
    setLayerButtons(null); state.activeLayer = null; hideLegend();
    return;
  }
  wind.field = data;
  wind.bbox = data.bbox;
  wind.particles = Array.from({ length: 400 }, spawnWindParticle);
  $("legendCred").textContent = "Open-Meteo · " + (data.updated ? new Date(data.updated).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "live");
  animateWind();
}
function animateWind() {
  cancelAnimationFrame(wind.raf);
  const ctx = wind.ctx;
  const step = () => {
    wind.raf = requestAnimationFrame(step);
    ctx.globalCompositeOperation = "destination-out";
    ctx.fillStyle = "rgba(0,0,0,0.08)";
    ctx.fillRect(0, 0, wind.canvas.width, wind.canvas.height);
    ctx.globalCompositeOperation = "source-over";
    ctx.lineWidth = 1.2;
    for (const p of wind.particles) {
      const v = windAt(p.lat, p.lon);
      if (!v) { Object.assign(p, spawnWindParticle()); continue; }
      const prev = map.latLngToContainerPoint([p.lat, p.lon]);
      const scale = 0.0016;
      p.lon += v.u * scale / Math.max(0.35, Math.cos(p.lat * Math.PI / 180));
      p.lat += v.v * scale;
      p.age++;
      const now = map.latLngToContainerPoint([p.lat, p.lon]);
      const spd = Math.hypot(v.u, v.v);
      ctx.strokeStyle = spd > 25 ? "#e0674f" : spd > 12 ? "#e6b34a" : "#8fe6d6";
      ctx.globalAlpha = 0.55;
      ctx.beginPath(); ctx.moveTo(prev.x, prev.y); ctx.lineTo(now.x, now.y); ctx.stroke();
      const b = wind.bbox;
      if (p.age > p.maxAge || p.lat < b[0] || p.lat > b[2] || p.lon < b[1] || p.lon > b[3]) {
        Object.assign(p, spawnWindParticle());
      }
    }
  };
  step();
}
function stopWind() {
  cancelAnimationFrame(wind.raf); wind.raf = null;
  wind.ctx.clearRect(0, 0, wind.canvas.width, wind.canvas.height);
  wind.particles = [];
}

/* ------------------------------ Legend ---------------------------------- */
function showLegend(title, [lo, hi], gradient, credit) {
  $("legendTitle").textContent = title;
  $("legendBar").style.background = gradient;
  $("legendLo").textContent = lo;
  $("legendHi").textContent = hi;
  $("legendCred").textContent = credit || "";
  $("legend").classList.add("show");
}
function hideLegend() { $("legend").classList.remove("show"); }

/* --------------------------- Rivers (GeoJSON) --------------------------- */
function drawRivers(geojson) {
  if (state.riverLayer) { map.removeLayer(state.riverLayer); state.riverLayer = null; }
  if (!geojson || !geojson.features || !geojson.features.length) return;
  state.riverLayer = L.geoJSON(geojson, {
    style: { color: "#5aa9e6", weight: 3.4, opacity: .95, className: "river-line", lineJoin: "round", lineCap: "round" },
    onEachFeature: (f, lyr) => {
      const p = f.properties || {};
      const name = p.name || "River";
      const info = p.info ? `<br><span style="color:#9db2bd">${p.info}</span>` : "";
      lyr.bindPopup(`<b>${name}</b>${info}`);
      lyr.bindTooltip(name, { sticky: true });
      lyr.on("mouseover", () => lyr.setStyle({ weight: 5, opacity: 1 }));
      lyr.on("mouseout", () => lyr.setStyle({ weight: 3.4, opacity: .95 }));
    },
  }).addTo(map);
}

/* ----------------------- Single query-location pin ---------------------- */
function setQueryMarker(lat, lon, label) {
  if (state.queryMarker) map.removeLayer(state.queryMarker);
  state.queryMarker = L.marker([lat, lon]).addTo(map);
  if (label) state.queryMarker.bindPopup(label).openPopup();
}

/* --------------------------- Map click = weather ------------------------ */
map.on("click", async (e) => {
  const { lat, lng } = e.latlng;
  setQueryMarker(lat, lng, "Loading weather…");
  try {
    const wx = await fetch(`${API.weather}?lat=${lat}&lon=${lng}`).then(r => r.json());
    if (wx.ok) {
      const c = wx.current;
      state.queryMarker.setPopupContent(
        `<b>${c.temp_c}°C</b> · ${c.condition}<br>Humidity ${c.humidity}% · Wind ${c.wind_kph} km/h ${c.wind_dir}`
      ).openPopup();
    } else {
      state.queryMarker.setPopupContent("Weather unavailable here.").openPopup();
    }
  } catch {
    state.queryMarker.setPopupContent("Weather unavailable here.").openPopup();
  }
});

/* ------------------------------ Chat ------------------------------------ */
function el(html) { const d = document.createElement("div"); d.innerHTML = html.trim(); return d.firstElementChild; }
function escapeHtml(s) { const d = document.createElement("div"); d.textContent = s; return d.innerHTML; }

function addUser(text) {
  thread.appendChild(el(`<div class="msg user"><div class="b">${escapeHtml(text)}</div></div>`));
  thread.scrollTop = thread.scrollHeight;
}
function addTyping() {
  const node = el(`<div class="msg bot" id="typing"><div class="b"><span class="typing"><i></i><i></i><i></i></span></div></div>`);
  thread.appendChild(node); thread.scrollTop = thread.scrollHeight; return node;
}
function botNote(text) {
  thread.appendChild(el(`<div class="msg bot"><div class="b">${escapeHtml(text)}</div></div>`));
  thread.scrollTop = thread.scrollHeight;
}

function renderAnswer(data) {
  const intentTag = data.intent && data.intent !== "general"
    ? `<span class="intent-tag">${data.intent}</span>` : "";
  const answerHtml = escapeHtml(data.answer).replace(/\n/g, "<br>");

  let sourcesHtml = "";
  if (data.sources && data.sources.length) {
    const rows = data.sources.map(s => {
      const title = escapeHtml(s.value || "");
      const label = escapeHtml(s.label || "");
      const when = s.updated ? ` · ${escapeHtml(String(s.updated).slice(0, 16))}` : "";
      const inner = `<span class="s-src">${label}</span><span class="s-title">${title}${when}</span>`;
      return s.url ? `<a class="src" href="${escapeHtml(s.url)}" target="_blank" rel="noopener">${inner}</a>`
                   : `<div class="src">${inner}</div>`;
    }).join("");
    sourcesHtml = `<div class="sources"><div class="sh">Sources</div>${rows}</div>`;
  }

  const disclaimer = data.intent === "flood"
    ? `<div class="disclaimer">⚠ Reported affected areas from news / humanitarian sources — not a verified satellite-derived flood boundary.</div>`
    : "";
  const transWarn = data.needs_translation_key
    ? `<div class="disclaimer">Translation needs a Gemini key; showing the English answer. Set GEMINI_API_KEY to get replies in your language.</div>`
    : "";

  const node = el(
    `<div class="msg bot"><div class="b">${intentTag}<p class="lead">${answerHtml}</p>${disclaimer}${transWarn}${sourcesHtml}` +
    `<button class="speak" title="Read aloud">🔊</button></div></div>`
  );
  node.querySelector(".speak").addEventListener("click", () => speak(data.answer));
  thread.appendChild(node);
  thread.scrollTop = thread.scrollHeight;
}

function applyMapState(m) {
  if (!m) return;
  const [lat, lon] = m.center;
  if (m.geojson && m.geojson.type === "rivers") {
    drawRivers(m.geojson.data);
    if (m.bounds) {
      map.flyToBounds(m.bounds, { padding: [60, 60], duration: 1.1, maxZoom: 9 });
    } else {
      map.flyTo([lat, lon], m.zoom || 6, { duration: 1.1 });
    }
    // Open the first river's popup so the info shows without a click.
    setTimeout(() => {
      if (state.riverLayer) {
        const first = state.riverLayer.getLayers()[0];
        if (first && first.getBounds) first.openPopup(first.getBounds().getCenter());
      }
    }, 1200);
    if (state.queryMarker) { map.removeLayer(state.queryMarker); state.queryMarker = null; }
    applyLayer("rivers");
  } else if (m.layer === "alerts") {
    if (state.riverLayer) { map.removeLayer(state.riverLayer); state.riverLayer = null; }
    if (state.queryMarker) { map.removeLayer(state.queryMarker); state.queryMarker = null; }
    applyLayer(null);
    toggleAlertsLayer(true);
    map.flyTo([lat, lon], m.zoom || 5, { duration: 1.1 });
    pollAlerts();
  } else {
    if (state.riverLayer) { map.removeLayer(state.riverLayer); state.riverLayer = null; }
    map.flyTo([lat, lon], m.zoom || 6, { duration: 1.1 });
    setQueryMarker(lat, lon, m.place || "");
    applyLayer(m.layer);
  }
}

async function ask(text) {
  if (!text.trim()) return;
  addUser(text);
  input.value = "";
  const typing = addTyping();
  $("veil").classList.add("show");
  $("sendBtn").disabled = true;
  try {
    const res = await fetch(API.chat, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, lang: state.lang, mode: state.mode }),
    });
    const data = await res.json();
    typing.remove();
    if (!data.ok) { botNote("Sorry — I couldn't process that. Please try rephrasing."); return; }
    renderAnswer(data);
    applyMapState(data.map);
  } catch (err) {
    typing.remove();
    botNote("I couldn't reach the server. Check your connection and try again.");
  } finally {
    $("veil").classList.remove("show");
    $("sendBtn").disabled = false;
  }
}

form.addEventListener("submit", (e) => { e.preventDefault(); ask(input.value); });

/* --------------------------- Layer buttons ------------------------------ */
function setLayerButtons(active) {
  document.querySelectorAll(".lbtn[data-layer]").forEach(b => {
    b.classList.toggle("on", b.dataset.layer === active);
  });
}
document.querySelectorAll(".lbtn[data-layer]").forEach(b => {
  b.addEventListener("click", () => {
    const layer = b.dataset.layer;
    if (state.activeLayer === layer) { applyLayer(null); }
    else { applyLayer(layer); }
  });
});
$("baseStreets").addEventListener("click", () => {
  map.removeLayer(baseSat); baseStreets.addTo(map);
  $("baseStreets").classList.add("on"); $("baseSat").classList.remove("on");
});
$("baseSat").addEventListener("click", () => {
  map.removeLayer(baseStreets); baseSat.addTo(map);
  $("baseSat").classList.add("on"); $("baseStreets").classList.remove("on");
});
$("radarPrev").addEventListener("click", () => { stopRadarAnim(); state.radar.idx = (state.radar.idx - 1 + state.radar.frames.length) % state.radar.frames.length; showRadarFrame(); });
$("radarNext").addEventListener("click", () => { stopRadarAnim(); state.radar.idx = (state.radar.idx + 1) % state.radar.frames.length; showRadarFrame(); });
$("radarPlay").addEventListener("click", () => { if (state.radar.timer) { stopRadarAnim(); $("radarPlay").textContent = "▶"; } else { startRadarAnim(); $("radarPlay").textContent = "⏸"; } });

/* ------------------------------ Voice ----------------------------------- */
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let recog = null;
if (SR) {
  recog = new SR(); recog.continuous = false; recog.interimResults = false;
  recog.onresult = (e) => { input.value = e.results[0][0].transcript; ask(input.value); };
  recog.onend = () => { $("mic").classList.remove("live"); };
  recog.onerror = () => { $("mic").classList.remove("live"); };
}
$("mic").addEventListener("click", () => {
  if (!SR) { botNote("Voice input isn't supported in this browser — try Chrome on desktop or Android."); return; }
  if (!window.isSecureContext) { botNote("Voice input needs a secure (https) connection. See the README for local setup."); return; }
  recog.lang = state.lang === "en" ? "en-IN" : state.lang + "-IN";
  $("mic").classList.add("live");
  try { recog.start(); } catch { $("mic").classList.remove("live"); }
});
function speak(text) {
  if (!window.speechSynthesis || !text) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = state.lang === "en" ? "en-IN" : state.lang + "-IN";
  window.speechSynthesis.speak(u);
}

/* --------------------------- Mode + language ---------------------------- */
function setupModeToggle() {
  const seg = $("modeToggle");
  const thumb = seg.querySelector(".thumb");
  const btns = [...seg.querySelectorAll("button")];
  const place = () => { const a = seg.querySelector("button.on"); thumb.style.width = a.offsetWidth + "px"; thumb.style.transform = `translateX(${a.offsetLeft - 3}px)`; };
  btns.forEach(b => b.addEventListener("click", () => {
    btns.forEach(x => x.classList.remove("on")); b.classList.add("on"); place();
    state.mode = b.dataset.mode;
  }));
  window.addEventListener("resize", place); setTimeout(place, 40);
}
$("lang").addEventListener("change", () => { state.lang = $("lang").value; });

/* ------------------------- Suggestion chips ----------------------------- */
const SUGGESTIONS = [
  "Weather in Pune today", "Will it rain in Mumbai tomorrow?", "Show rainfall over India",
  "Rivers in Assam", "Floods in Nepal", "Cyclone near Odisha", "Latest weather news in Kerala", "Any disaster alerts right now?",
];
function buildChips() {
  const box = $("chips");
  box.innerHTML = SUGGESTIONS.map(s => `<button class="chip">${s}</button>`).join("");
  box.querySelectorAll(".chip").forEach(c => c.addEventListener("click", () => ask(c.textContent)));
}

/* ----------------------------- Live alerts ------------------------------ */
// Polls /api/alerts, pins events on the map, and pops up anything new.
// "Seen" (toast already shown) and "acknowledged" (opened in the drawer) are
// remembered in this browser so reloading doesn't re-spam the same events.
const ALERT_POLL_MS = 5 * 60 * 1000;
const SEEN_KEY = "wgpt_alerts_seen_v1";
const ACK_KEY = "wgpt_alerts_ack_v1";
const SEV_RANK = { low: 1, medium: 2, high: 3 };
const alertsState = {
  list: [], feeds: [], layer: L.layerGroup().addTo(map), markers: {},
  visible: true, first: true, lastPoll: 0, tickerIdx: 0,
};

function readStore(k) { try { return JSON.parse(localStorage.getItem(k) || "{}"); } catch { return {}; } }
function writeStore(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } }
function pruneStore(obj, days = 3) {
  const cut = Date.now() - days * 864e5;
  for (const k of Object.keys(obj)) {
    const t = typeof obj[k] === "object" ? obj[k].t : obj[k];
    if (!t || t < cut) delete obj[k];
  }
  return obj;
}
function safeUrl(u) {
  try { const x = new URL(u); return (x.protocol === "https:" || x.protocol === "http:") ? x.href : null; }
  catch { return null; }
}
function timeAgo(iso) {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (isNaN(s)) return "";
  if (s < 90) return "just now";
  if (s < 3600) return Math.round(s / 60) + " min ago";
  if (s < 86400) return Math.round(s / 3600) + " h ago";
  return Math.round(s / 86400) + " d ago";
}
const headlineOf = (a) => (a.items && a.items[0] && a.items[0].title) || "";

async function pollAlerts() {
  alertsState.lastPoll = Date.now();
  let data = null;
  try { data = await fetch(API.alerts).then(r => r.json()); } catch { data = null; }
  if (!data || !data.ok) {
    $("alertMeta").textContent = "Alert feeds unreachable right now — retrying in 5 min.";
    if (!alertsState.list.length) $("tickerText").textContent = "Live disaster feeds unreachable — retrying shortly";
    return;
  }
  alertsState.list = data.alerts || [];
  alertsState.feeds = data.sources_status || [];
  renderAlertMarkers();
  renderAlertDrawer();
  updateBadge();
  updateTicker(true);
  handleNewAlerts();
}

function handleNewAlerts() {
  const seen = pruneStore(readStore(SEEN_KEY));
  const fresh = [];
  for (const a of alertsState.list) {
    const prev = seen[a.id];
    if (!prev) fresh.push({ a, escalated: false });
    else if (SEV_RANK[a.severity] > SEV_RANK[prev.sev]) fresh.push({ a, escalated: true });
    seen[a.id] = { sev: a.severity, t: Date.now() };
  }
  writeStore(SEEN_KEY, seen);
  if (fresh.length) {
    // On first load, don't bury the screen: one summary if there's a backlog.
    if (alertsState.first && fresh.length > 2) summaryToast(fresh.length);
    else fresh.slice(0, 4).forEach(({ a, escalated }) => alertToast(a, escalated));
    if (document.hidden) fresh.slice(0, 3).forEach(({ a }) => desktopNotify(a));
  }
  alertsState.first = false;
}

function removeToast(t) {
  if (!t.isConnected) return;
  t.classList.add("leaving");
  setTimeout(() => t.remove(), 260);
}
function mountToast(t, lifeMs) {
  const box = $("toasts");
  while (box.children.length >= 4) box.firstElementChild.remove();
  let timer = setTimeout(() => removeToast(t), lifeMs);
  t.addEventListener("mouseenter", () => clearTimeout(timer));
  t.addEventListener("mouseleave", () => { timer = setTimeout(() => removeToast(t), 6000); });
  box.appendChild(t);
}
function alertToast(a, escalated) {
  const verb = escalated ? "escalating" : "reported";
  const t = el(`<div class="toast sev-${a.severity}" role="alert">
      <div class="t-icon">${a.icon}</div>
      <div class="t-body">
        <div class="t-title">${escapeHtml(a.hazard_label)} ${verb} · ${escapeHtml(a.region)}</div>
        <div class="t-sub">${escapeHtml(a.confidence)} · ${timeAgo(a.latest)}</div>
        <div class="t-head">${escapeHtml(headlineOf(a))}</div>
        <div class="t-actions">
          <button class="t-go" type="button">View on map</button>
          <button class="t-x" type="button">Dismiss</button>
        </div>
      </div></div>`);
  t.querySelector(".t-go").onclick = () => { flyToAlert(a); removeToast(t); };
  t.querySelector(".t-x").onclick = () => removeToast(t);
  mountToast(t, a.severity === "high" ? 20000 : 12000);
}
function summaryToast(n) {
  const high = alertsState.list.filter(a => a.severity === "high").length;
  const t = el(`<div class="toast ${high ? "sev-high" : "sev-medium"}" role="alert">
      <div class="t-icon">🚨</div>
      <div class="t-body">
        <div class="t-title">${n} active weather / disaster events</div>
        <div class="t-sub">${high} high-confidence · detected from live feeds</div>
        <div class="t-actions">
          <button class="t-go" type="button">Open alerts</button>
          <button class="t-x" type="button">Dismiss</button>
        </div>
      </div></div>`);
  t.querySelector(".t-go").onclick = () => { openDrawer(); removeToast(t); };
  t.querySelector(".t-x").onclick = () => removeToast(t);
  mountToast(t, 15000);
}

function flyToAlert(a) {
  if (!a) return;
  if (!alertsState.visible) toggleAlertsLayer(true);
  closeDrawer();
  map.flyTo([a.lat, a.lon], a.precise ? 9 : 7, { duration: 1.2 });
  setTimeout(() => { const m = alertsState.markers[a.id]; if (m) m.openPopup(); }, 1300);
}

function alertPopupHtml(a) {
  const items = (a.items || []).slice(0, 5).map(it => {
    const u = safeUrl(it.url);
    const title = escapeHtml(it.title || "");
    const link = u ? `<a href="${escapeHtml(u)}" target="_blank" rel="noopener noreferrer">${title}</a>` : title;
    const when = it.published ? " · " + timeAgo(it.published) : "";
    return `<li>${link}<span class="ap-src">${escapeHtml(it.source || "")}${when}</span></li>`;
  }).join("");
  const loc = a.precise ? "Location from feed coordinates / named city"
                        : "Approximate location — region centre from news text";
  return `<div class="apop">
      <div class="ap-h">${a.icon} ${escapeHtml(a.hazard_label)} · ${escapeHtml(a.region)}</div>
      <div class="ap-chips"><span class="chip-sev sev-${a.severity}">${escapeHtml(a.confidence)}</span>
        ${a.authoritative ? '<span class="chip-off">Official feed</span>' : ""}</div>
      <div class="ap-loc">${loc}</div>
      <ul class="ap-list">${items}</ul>
      <button class="ask-alert" type="button">Ask WeatherGPT about this</button>
    </div>`;
}

function renderAlertMarkers() {
  alertsState.layer.clearLayers();
  alertsState.markers = {};
  for (const a of alertsState.list) {
    if (a.lat == null || a.lon == null) continue;
    const icon = L.divIcon({
      className: "",
      html: `<div class="apin sev-${a.severity}"><span class="ring"></span><span class="core">${a.icon}</span></div>`,
      iconSize: [34, 34], iconAnchor: [17, 17], popupAnchor: [0, -14],
    });
    const m = L.marker([a.lat, a.lon], { icon, zIndexOffset: 1000 * SEV_RANK[a.severity], title: `${a.hazard_label} · ${a.region}` })
      .bindPopup(alertPopupHtml(a), { maxWidth: 330 });
    m.on("popupopen", (e) => {
      const b = e.popup.getElement()?.querySelector(".ask-alert");
      if (b) b.onclick = () => ask(`What is happening with the ${a.hazard_label.toLowerCase()} in ${a.region}?`);
    });
    m.addTo(alertsState.layer);
    alertsState.markers[a.id] = m;
  }
}

function renderAlertDrawer() {
  const okFeeds = alertsState.feeds.filter(f => f.ok).length;
  const down = alertsState.feeds.filter(f => !f.ok).map(f => f.name);
  $("alertMeta").textContent =
    `${alertsState.list.length} active · ${okFeeds}/${alertsState.feeds.length} feeds reachable` +
    (down.length ? ` (down: ${down.join(", ")})` : "") +
    ` · updated ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
  const list = $("alertList");
  if (!alertsState.list.length) {
    list.innerHTML = `<div class="a-empty">No weather or disaster events detected in the last 48 hours.<br>WeatherGPT re-checks every 5 minutes.</div>`;
    return;
  }
  list.innerHTML = alertsState.list.map((a, i) => `
    <div class="a-card sev-${a.severity}">
      <div class="a-top"><span class="a-icon">${a.icon}</span>
        <div><div class="a-title">${escapeHtml(a.hazard_label)} · ${escapeHtml(a.region)}</div>
        <div class="a-sub">${escapeHtml(a.confidence)} · ${timeAgo(a.latest)}</div></div></div>
      <div class="a-head">${escapeHtml(headlineOf(a))}</div>
      <button class="a-go" type="button" data-i="${i}">View on map →</button>
    </div>`).join("");
  list.querySelectorAll(".a-go").forEach(b => { b.onclick = () => flyToAlert(alertsState.list[+b.dataset.i]); });
}

function updateBadge() {
  const ack = readStore(ACK_KEY);
  const unread = alertsState.list.filter(a => !ack[a.id + "|" + a.severity]);
  const b = $("alertBadge");
  b.textContent = unread.length > 9 ? "9+" : String(unread.length);
  b.hidden = unread.length === 0;
  $("alertBell").classList.toggle("has-high", unread.some(a => a.severity === "high"));
}
function openDrawer() {
  $("alertDrawer").classList.add("open");
  const ack = pruneStore(readStore(ACK_KEY));
  alertsState.list.forEach(a => { ack[a.id + "|" + a.severity] = Date.now(); });
  writeStore(ACK_KEY, ack);
  updateBadge();
}
function closeDrawer() { $("alertDrawer").classList.remove("open"); }
$("alertBell").onclick = () => ($("alertDrawer").classList.contains("open") ? closeDrawer() : openDrawer());
$("alertClose").onclick = closeDrawer;
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });

function updateTicker(reset) {
  const tk = $("tickerText"), box = $("ticker");
  if (!alertsState.list.length) {
    tk.textContent = "No active disaster alerts in the last 48 h · monitoring live feeds";
    box.classList.add("calm"); box.onclick = null;
    return;
  }
  box.classList.remove("calm");
  if (reset) alertsState.tickerIdx = 0;
  const a = alertsState.list[alertsState.tickerIdx % alertsState.list.length];
  tk.textContent = `${a.icon} ${a.hazard_label} · ${a.region} — ${a.confidence}`;
  box.onclick = () => flyToAlert(a);
}
setInterval(() => { if (alertsState.list.length > 1) { alertsState.tickerIdx++; updateTicker(false); } }, 6000);

function toggleAlertsLayer(force) {
  alertsState.visible = (typeof force === "boolean") ? force : !alertsState.visible;
  if (alertsState.visible) alertsState.layer.addTo(map); else map.removeLayer(alertsState.layer);
  $("toggleAlerts").classList.toggle("on", alertsState.visible);
}
$("toggleAlerts").onclick = () => toggleAlertsLayer();

function desktopNotify(a) {
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  try {
    const n = new Notification(`${a.hazard_label} · ${a.region}`, {
      body: `${a.confidence}. ${headlineOf(a)}`, tag: a.id });
    n.onclick = () => { window.focus(); flyToAlert(a); n.close(); };
  } catch { /* some browsers only allow notifications from a service worker */ }
}
function setupNotifyButton() {
  const b = $("alertNotify");
  if (!("Notification" in window) || !window.isSecureContext) { b.hidden = true; return; }
  const sync = () => {
    const p = Notification.permission;
    b.textContent = p === "granted" ? "✓ Desktop notifications on"
                  : p === "denied" ? "Notifications blocked in browser settings"
                  : "🔔 Enable desktop notifications";
    b.disabled = p !== "default";
  };
  sync();
  b.onclick = async () => { try { await Notification.requestPermission(); } catch { } sync(); };
}

function startAlertPolling() {
  setupNotifyButton();
  pollAlerts();
  setInterval(pollAlerts, ALERT_POLL_MS);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && Date.now() - alertsState.lastPoll > 2 * 60 * 1000) pollAlerts();
  });
}

/* -------------------------------- Init ---------------------------------- */
async function init() {
  buildChips();
  setupModeToggle();
  try {
    state.caps = await fetch(API.config).then(r => r.json());
    // Populate languages from backend.
    const langs = state.caps.languages || { en: "English" };
    $("lang").innerHTML = Object.entries(langs).map(([c, n]) => `<option value="${c}">${n}</option>`).join("");
    $("lang").value = "en";
    // Status pill reflects real capabilities.
    const p = $("statusPill");
    if (state.caps.llm) { p.textContent = `AI: ${state.caps.llm_provider}`; p.classList.remove("warn"); }
    else { p.innerHTML = `<span class="dot"></span>Template mode (no LLM key)`; p.classList.add("warn"); }
    // Only the Temp tile layer needs an OpenWeatherMap key now.
    if (!state.caps.openweather_key) {
      const b = document.querySelector('.lbtn[data-layer="temp"]');
      if (b) { b.classList.add("off-key"); b.title = "Temperature tiles need an OpenWeatherMap key (optional)"; }
    }
  } catch {
    botNote("Couldn't load configuration from the server.");
  }
  // Greeting.
  botNote("Namaste! Ask me about weather, rain, wind, cyclones, floods, rivers, or the latest situation anywhere in India. Try a suggestion below, tap the map for local weather, or type your own question.");
  // Preload radar frames in the background so the first radar request is instant.
  loadRadarFrames();
  startAlertPolling();
}
init();
