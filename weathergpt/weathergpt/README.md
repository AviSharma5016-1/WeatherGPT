# WeatherGPT

Conversational weather, climate and disaster intelligence for India — built for
the **Ministry of Earth Sciences / India Meteorological Department** problem
statement (Disaster Management theme).

Ask in plain language ("weather in Pune", "floods in Nepal", "rivers in Assam",
"cyclone near Odisha", "show rainfall over India"). WeatherGPT works out what
you mean, pulls **live data**, centres the map on the place, shows the relevant
layer, and answers in natural language with its sources.

> **It runs with zero API keys.** Live weather, geocoding, news and the map all
> work keyless out of the box. Keys only *upgrade* the experience (see below).

---

## Features

- **Natural-language chat** → intent detection → live data retrieval → synthesised answer.
- **Live weather** (current + 5-day forecast): temperature, feels-like, humidity,
  pressure, wind speed/direction/gusts, precipitation, cloud cover, UV — via **Open-Meteo** (keyless).
- **Auto-centring map**: any place you name is geocoded and the map smoothly flies to it. No hard-coded coordinates.
- **Live map layers**: animated **rain radar** (RainViewer, keyless, real past-frame animation); optional cloud / temperature / wind tiles (OpenWeatherMap, needs a key).
- **Real river geometry** from OpenStreetMap via Overpass — actual waterway GeoJSON you can zoom into, not markers.
- **Live news / disaster reports** (Google News RSS + ReliefWeb, keyless) with source, headline, date and link on every item.
- **Honest flood/cyclone handling**: reports are labelled *reported affected areas*, never presented as verified satellite flood boundaries. No fabricated extents.
- **Multilingual**: 13 languages (English, Hindi, Marathi, Bengali, Gujarati, Tamil, Telugu, Kannada, Malayalam, Punjabi, Odia, Assamese, Urdu). With a Gemini key, answers are generated and translated into the selected language; language is also auto-detected from the query script.
- **Live disaster alerts (early warning)** — WeatherGPT watches live feeds every 5 minutes, even when you haven't asked anything:
  - Groups reports of the **same hazard in the same region** into one event and counts how many **independent outlets** report it: 1 outlet = *single report, unverified* (blue) · 2 = *corroborated* (amber) · 3+ = *high confidence* (red). Official feeds (GDACS, USGS, NDMA) are marked as such, with matching news merged in.
  - New events trigger a **pop-up** with a **View on map** button that flies to the region and opens the headlines with links. If an event *escalates* (e.g. 1 outlet → 3), you get a fresh pop-up.
  - A **🔔 bell with a red badge** counts unread events; the drawer lists them all. Pulsing, severity-coloured pins sit on the map; the bottom ticker cycles through them.
  - Optional **desktop notifications** (button in the alerts drawer) so you're alerted even when the tab is in the background.
  - Filters out figurative/irrelevant headlines ("flood of complaints", anniversaries, market news) and anything older than 48 h.
- **Voice** in (speech-to-text) and out (text-to-speech), aimed at rural accessibility.
- **Simple ⇄ Scientific** answer depth toggle.
- **Tap the map** anywhere for instant local weather.
- Loading, error and empty states throughout; graceful degradation when any upstream fails.

---

## Architecture

```
Browser (static/)                       FastAPI backend (app.py)
─────────────────                       ────────────────────────
index.html / styles.css / app.js  <-->  /api/config   capability flags (no secrets)
  Leaflet map (OSM + Esri sat)          /api/chat     orchestrates everything
  RainViewer radar (keyless)            /api/geocode  place -> lat/lon (Open-Meteo)
  OpenWeatherMap tiles (optional)       /api/weather  live conditions (Open-Meteo)
                                        /api/rivers   real GeoJSON (Overpass)

  Chat flow:
  query -> services/intent.py  (classify + extract place + detect language)
        -> services/geocode.py (Open-Meteo geocoding, keyless)
        -> services/weather.py | services/rivers.py | services/news.py  (live data)
        -> services/llm.py      (Gemini if key present, else template synthesiser)
        -> {answer, sources, map:{center,zoom,layer,geojson}}
```

The frontend and backend ship as **one deployable unit** — FastAPI serves the
static frontend, so there's a single service to run and deploy.

---

## Requirements

- **Python 3.10+**
- A modern browser (Chrome/Edge/Firefox/Safari). Voice input needs Chrome/Edge on desktop or Android, over `http://localhost` or `https://`.
- Internet access for the live data providers.

---

## Installation & running (simplest path)

```bash
# 1. Get the project, then from its folder:
pip install -r requirements.txt

# 2. (Optional) add keys — the app runs fine without this step:
cp .env.example .env        # then edit .env if you have any keys

# 3. Run:
uvicorn app:app --host 0.0.0.0 --port 8000

# 4. Open:
#    http://localhost:8000
```

That's it. No virtual environment is required.

<details>
<summary><b>Recommended for development</b> (optional virtual environment)</summary>

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```
</details>

---

## API keys (all optional)

The app runs with **none** of these. Add the ones you have to `.env`.

| Key | What it unlocks | Where to get it |
|---|---|---|
| `GEMINI_API_KEY` | AI-generated answers + translation into the selected language. Without it, answers come from a built-in English template synthesiser. | [Google AI Studio](https://aistudio.google.com/app/apikey) |
| `GOOGLE_MAPS_API_KEY` | *Optional* Google Maps base layer. Without it, the app uses keyless OpenStreetMap + Esri satellite (which is why the map already works). See note below. | [Google Cloud Console](https://console.cloud.google.com/) → Maps JavaScript API |
| `OPENWEATHER_API_KEY` | Cloud / temperature / wind **tile overlays**. Rain radar already works keyless via RainViewer. | [OpenWeatherMap](https://openweathermap.org/api) |
| `NEWS_API_KEY` | An extra news source. Google News RSS + ReliefWeb already work keyless. | [NewsAPI](https://newsapi.org/) |

**Where keys go:** only in your local `.env` (which `.gitignore` excludes from
commits). Never in source, never in the README, never committed. `.env.example`
holds placeholders only.

**On Google Maps specifically:** the current map deliberately uses Leaflet with
keyless OpenStreetMap/Esri tiles. This was a deliberate call — the previous
version broke because its tile provider (CARTO) started requiring a key and
stamped *"API KEY REQUIRED"* across the map. More importantly, **Google Maps
provides none of the weather, radar, river or flood data** — those come from
Open-Meteo / RainViewer / Overpass / ReliefWeb regardless of the base map. So
Google Maps would only change the background tiles, at the cost of requiring a
(domain-restricted) browser key and showing a "for development only" watermark
without one. If you specifically want the Google base layer, add
`GOOGLE_MAPS_API_KEY`; the key is exposed to `/api/config` for the frontend to
use, and you should **restrict it by HTTP referrer** in the Google Cloud
console. The swap point is the base-layer section at the top of `static/app.js`.

---

## Deployment

Because it's one FastAPI service, any Python host works. It already honours the
`PORT` and `HOST` environment variables and binds `0.0.0.0`.

**Render / Railway / Fly.io / Google Cloud Run:**

- Start command: `uvicorn app:app --host 0.0.0.0 --port $PORT`
- Set your environment variables (the same names as in `.env`) in the platform's dashboard — do **not** upload `.env`.
- Python 3.10+ runtime.

**Docker** (optional):

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=8000
CMD ["sh","-c","uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
```

Do not use the bare dev server for production traffic; `uvicorn` (optionally
behind nginx or a platform load balancer) is the production server here.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| "Template mode (no LLM key)" pill | No `GEMINI_API_KEY`. Answers still work (English templates). Add the key for AI answers + translation. |
| Answers won't translate | Same — translation needs `GEMINI_API_KEY`. |
| Map tiles blank | Network/firewall blocking `tile.openstreetmap.org`. Check connectivity; try the Satellite base. |
| "I couldn't retrieve live weather" | Open-Meteo unreachable (network/rate limit). The app degrades gracefully; retry shortly. |
| Cloud/Temp/Wind buttons greyed out | Those tile layers need `OPENWEATHER_API_KEY`. Rain radar works without it. |
| Voice button does nothing | Use Chrome/Edge on desktop or Android, over `localhost` or `https`. |
| Bell never shows anything | Open the 🔔 drawer — the header line lists which feeds are reachable. If all are down, it's network/firewall; if they're up, there simply are no detected events in the last 48 h. |
| No desktop notifications | Click "Enable desktop notifications" in the alerts drawer and allow them in the browser prompt. Needs `localhost` or `https`. |
| Rivers don't appear | Overpass API is rate-limited/slow; it may return nothing transiently. The app never fabricates rivers — it just shows none. Retry. |

---

## Data sources

- **Weather & geocoding:** Open-Meteo (`open-meteo.com`) — keyless, near-real-time. Geocoding is India-biased so ambiguous names resolve at home.
- **Rain radar & cloud (infrared) imagery:** RainViewer (`rainviewer.com`) — keyless, animated.
- **Wind:** real 10 m wind sampled from Open-Meteo on a grid, animated as a particle field (keyless, data-driven — not decoration).
- **Rivers:** a built-in curated atlas of major Indian rivers (Ganga, Yamuna, Brahmaputra, Godavari, Krishna, Narmada, Mahanadi, Kaveri, Tapti, Hooghly, Indus) — simplified real courses, highlighted with click-for-info. Swap in OSM/Overpass or HydroSHEDS for survey-grade geometry behind the same interface.
- **News / disaster reports:** Google News RSS, ReliefWeb (UN OCHA); optional NewsAPI.
- **Live alert monitor:** Google News RSS (last 48 h), **GDACS** (UN/EC Global Disaster Alert and Coordination System), **USGS** earthquakes M4.5+, **NDMA SACHET** (India's official Common Alerting Protocol feed). All keyless.
- **Base map:** OpenStreetMap; Esri World Imagery (satellite).
- **Temperature tiles (optional):** OpenWeatherMap (needs a key).
- **AI synthesis/translation:** Google Gemini (optional).

---

## Limitations (honest)

- **Geocoding is hard-restricted to South Asia.** Ambiguous or renamed place names ("Ganga" also exists in Italy; "Shimoga" was officially renamed Shivamogga in 2014 and could fuzzy-match "Shimogamo, Japan") are now filtered by a hard bounding box over the subcontinent — a match outside it is never accepted, regardless of how the provider ranked it. If nothing resolves in-region, the app says so plainly ("I couldn't pinpoint X, showing India overall") rather than silently substituting a wrong location.
- **Alerts are detected, not issued.** WeatherGPT spots events that news outlets and official feeds are reporting; it is not an official warning system. Always follow IMD / NDMA / state authority warnings.
- **News-based pins are approximate.** A headline saying "floods in Arunachal Pradesh" is pinned at the state's centre (the popup says so). Named cities, GDACS and USGS events get precise coordinates.
- **Detection is keyword + place based.** It can occasionally miss an event phrased unusually, or misfile a headline. Every event links to its sources so you can check. With a Gemini key this could be upgraded to LLM-based classification.
- **Alert latency is ~5 minutes** (server cache + polling), plus however long outlets take to publish.
- **Google News RSS** is intended for personal/non-commercial use; for an official deployment, swap in a licensed news API behind `services/alerts.py`.
- **NDMA SACHET's URL** is set in one line in `services/alerts.py`; if NDMA moves the feed, update it there. The drawer shows which feeds are down, so an outage is visible rather than silent.

- **Weather is near-real-time, not instantaneous** — Open-Meteo updates periodically; the app caches for ~10 min.
- **No verified satellite flood extent.** Flood/cyclone answers summarise *reported* affected areas from news/humanitarian sources and are labelled as such. Verified satellite flood polygons would need a provider like Copernicus EMS / Sentinel Hub / ISRO Bhuvan — not integrated here.
- **Cyclone tracks** are described from reports, not drawn as authoritative meteorological tracks. A live IMD/JTWC track feed would be the production source.
- **Rivers are a simplified curated atlas** — real courses generalised to tens of vertices so they draw instantly and legibly. They're schematics of the real course, not survey-grade channels. Swap in Overpass/HydroSHEDS for full fidelity.
- **Wind animation is real but coarse** — sampled on a 6×6 grid around the view and interpolated, so it shows the genuine flow pattern, not per-pixel model output.
- **Translation quality** depends on Gemini; without a key, replies are English only.
- **This is a single-instance demo cache** (in-process). For scale, put Redis behind the cache and run multiple workers.

---

## Change summary (from the previous prototype)

**What was broken**
- Map tiles came from CARTO's `dark_all` basemap, which now requires a key — every tile was stamped *"API KEY REQUIRED"*. Replaced with keyless OpenStreetMap + Esri satellite.
- Everything was hard-coded: region explanations, coordinates, wind field, alerts. No live data anywhere.
- Rivers were hand-typed jagged polylines; "wind" was a decorative particle field not tied to any real data.
- Ten fixed pins cluttered the map regardless of the query.

**What was redesigned / added**
- Real **FastAPI backend** with a clean service split (`intent`, `geocode`, `weather`, `news`, `rivers`, `llm`) and clean endpoints (`/api/chat`, `/api/weather`, `/api/rivers`, `/api/geocode`, `/api/config`).
- **Intent detection + location/language extraction** driving both the answer and the map state.
- **Live weather + geocoding** (Open-Meteo, keyless) — removes all hard-coded coordinates and weather.
- **Live news/disaster retrieval** (Google News RSS + ReliefWeb) — no hard-coded stories, with per-item source attribution.
- **Real river GeoJSON** from Overpass, rendered as a zoomable vector layer.
- **Live animated rain radar** (RainViewer) + optional OpenWeatherMap tile layers, each with a legend and provenance.
- **LLM provider abstraction** (Gemini + keyless fallback synthesiser) so the app answers with or without a key and providers can be swapped without a rewrite.
- **13-language** support via LLM generation/translation instead of a hard-coded string dictionary.
- **Removed the arbitrary markers** — the map shows a single pin only for the place actually asked about (or clicked), plus the requested phenomenon layer.
- **Security**: all secrets via environment variables; `.env` git-ignored; `.env.example` with placeholders; only intended-public browser keys reach the frontend.
- **Polished dashboard UI**, responsive layout, loading/error/empty states, smooth `flyTo` transitions.
- **Production-ready**: `PORT`/`HOST` env, single deployable unit, Docker snippet, deploy guide.

**What could not be fully verified in the build sandbox**
- The build environment blocks all external hosts, so live Open-Meteo / Overpass / RainViewer / Gemini / news calls could not be exercised here. Verified instead: module imports, route registration, intent classification (12/12 example queries), full chat orchestration with mocked upstreams, graceful degradation when every upstream is unreachable, no secret leakage, and frontend JS/HTML/asset serving. On a machine with normal internet, the live calls run through the same code paths.
