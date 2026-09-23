<div align="center">

# 🌤️ WeatherGPT

**Ask the sky in your language.**
A conversational weather, climate & disaster-intelligence assistant for India — live data, 13 languages, a self-updating alert engine, and zero mandatory API keys.

Built for **Smart India Hackathon 2026** · Problem Statement **26068** · Theme: **Disaster Management**
Ministry of Earth Sciences (MoES) · India Meteorological Department (IMD)

[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-backend-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![No API keys required](https://img.shields.io/badge/API%20keys-0%20required-brightgreen)](#-runs-with-zero-api-keys)
[![Languages](https://img.shields.io/badge/languages-13-blue)](#-what-it-does)
[![License: MIT](https://img.shields.io/badge/license-MIT-lightgrey)](#-license)

</div>

---

## Why

Weather and disaster information in India is scattered across a dozen portals — forecasts here, radar there, warnings somewhere else, mostly in English, mostly in technical language. In an actual flood or cyclone, nobody has time to piece that together.

**WeatherGPT is one conversational layer over it.** Ask by text, voice, or by tapping the map — in any of 13 Indian languages — and it detects your intent, pulls the relevant live data, explains it in plain language with sources cited, updates the map, and watches for new disaster events on its own.

> WeatherGPT is a **decision-support layer over authoritative sources** (IMD, NDMA, MOSDAC, INCOIS). It is not, and does not claim to be, a replacement for official warnings.

---

## ✨ What it does

| | |
|---|---|
| 🗣️ **Conversational, multilingual chat** | Ask in plain language, in **13 languages** (English, Hindi, Marathi, Bengali, Gujarati, Tamil, Telugu, Kannada, Malayalam, Punjabi, Odia, Assamese, Urdu). Voice in and out via the browser. |
| 🧠 **Grounded AI, not a hallucination machine** | Gemini (when configured) only explains data the backend actually retrieved — it's never the source of truth. No key? A deterministic English template keeps everything working. |
| 🌦️ **Live weather & forecasts** | Current conditions, 5-day forecast, wind, humidity, pressure, precipitation — from [Open-Meteo](https://open-meteo.com), keyless. |
| 🗺️ **A map that answers back** | Auto fly-to on any place you name, live animated rain radar, infrared cloud imagery, a real wind field animated from live data, and a satellite/street toggle. |
| 🌊 **Real river geometry** | 11 major Indian river systems (Ganga, Yamuna, Brahmaputra, Godavari, Krishna, Narmada, Mahanadi, Kaveri, Tapti, Hooghly, Indus) rendered as actual GeoJSON, not placeholder pins. |
| 🚨 **Self-driving disaster alerts** | Polls 4 live feeds every 5 minutes, classifies **8 hazard types**, places them across **35 states/UTs + 42 cities**, merges duplicate reports, and rates confidence by how many *independent outlets* confirm an event. Pops up a notification with a "View on map" button — no need to ask. |
| 📰 **Live news, never hard-coded** | Every claim is sourced — outlet, headline, timestamp, link. |
| 📍 **Honest geocoding** | Hard-restricted to South Asia by bounding box, so an ambiguous or renamed place name (there's a "Ganga" in Italy) never silently resolves to the wrong country. |

---

## 🔑 Runs with zero API keys

Clone it, install, run — weather, geocoding, radar, rivers, news, and the live alert engine all work immediately, no signup required.

| Add this key | To unlock |
|---|---|
| `GEMINI_API_KEY` | Natural AI-generated answers + real translation into all 13 languages *(free tier at [Google AI Studio](https://aistudio.google.com/app/apikey))* |
| `OPENWEATHER_API_KEY` | The temperature tile overlay on the map |
| `GOOGLE_MAPS_API_KEY` | Swap the base map tiles for Google's (cosmetic only — no data depends on it) |
| `NEWS_API_KEY` | One extra news source alongside the keyless feeds |

Nothing here is mandatory. See [`.env.example`](.env.example).

---

## 🚀 Quick start

```bash
git clone https://github.com/AviSharma5016/weathergpt.git
cd weathergpt
python -m pip install -r requirements.txt
python -m uvicorn app:app --port 8000
```

Open **http://localhost:8000**. That's it.

<details>
<summary>Optional: add API keys</summary>

```bash
cp .env.example .env
# then edit .env and paste in whichever keys you have
```
</details>

Full setup, deployment, and troubleshooting notes are in [`README_TECHNICAL.md`](README_TECHNICAL.md).

---

## 🏗️ How it works

```
User query (text / voice / map tap)
        │
        ▼
 Intent + place + language detection   (services/intent.py)
        │
        ▼
 Geocoding — South-Asia bounded         (services/geocode.py)
        │
        ▼
 Live data retrieval, by intent:
   weather / forecast    → Open-Meteo                    (services/weather.py)
   rain / clouds / wind  → RainViewer + Open-Meteo grid   (services/wind.py)
   rivers                → curated GeoJSON atlas          (services/rivers.py)
   flood / cyclone / news → Google News RSS + ReliefWeb   (services/news.py)
        │
        ▼
 Grounded synthesis — Gemini or deterministic fallback   (services/llm.py)
        │
        ▼
 { answer, cited sources, map state } → chat + live map

 ──────────────────────────────────────────────────────
 In parallel, every 5 minutes:
 Poll 4 feeds (Google News, GDACS, USGS, NDMA SACHET)
   → classify hazard → geocode region → merge duplicates
   → count independent outlets → push alert             (services/alerts.py)
```

One FastAPI service serves both the API and the static frontend — a single deployable unit.

---

## 🧰 Tech stack

**Backend** — Python 3.10+, FastAPI, Uvicorn, HTTPX
**AI** — Google Gemini via a provider-agnostic layer (swap providers without touching the app)
**Map** — Leaflet, OpenStreetMap / Esri imagery, canvas-based live wind animation, GeoJSON rivers
**Live data** — Open-Meteo, RainViewer, GDACS, USGS, NDMA SACHET, Google News RSS, ReliefWeb
**Frontend** — Vanilla HTML/CSS/JS, Web Speech API (voice in/out), Notifications API
**Deploy** — Single container, `PORT`/`HOST` env vars, works on Render/Railway/Cloud Run

---

## 🗺️ Roadmap

- [x] **Phase 1 — live now:** chat + voice, 13 languages, live radar/cloud/wind, river atlas, 4-feed alert engine
- [ ] **Phase 2:** official IMD API, MOSDAC/ISRO INSAT-3D, INCOIS ocean data, NDMA SACHET CAP integration
- [ ] **Phase 3:** domain copilots — AgroMet, aviation (METAR/TAF), marine; PWA + WhatsApp/IVR for feature phones
- [ ] **Phase 4:** WIS 2.0 / MQTT ingestion, PostGIS, Kubernetes autoscaling, IMD-verified alert workflow

---

## ⚠️ Honesty, by design

- Flood/cyclone answers are labelled **reported affected areas** — never presented as a verified satellite-derived flood boundary.
- If live feeds are unreachable, the app says *"I couldn't check"* — never *"no events"*.
- Wind and river visuals are clearly what they are: real data, animated — not decoration.
- This project does not, and will not, claim to be an official warning system.

---

## 🙏 Data sources & standards

[Open-Meteo](https://open-meteo.com) · [RainViewer](https://www.rainviewer.com) · [USGS](https://earthquake.usgs.gov) · [ReliefWeb](https://reliefweb.int) · [GDACS](https://www.gdacs.org) · [OpenStreetMap](https://www.openstreetmap.org) · [Esri](https://www.esri.com) · [Google Gemini](https://ai.google.dev)
Reference ecosystem: [IMD](https://mausam.imd.gov.in) · [NDMA SACHET](https://sachet.ndma.gov.in) · [MOSDAC/ISRO](https://www.mosdac.gov.in) · [INCOIS](https://incois.gov.in) · [WMO WIS 2.0](https://wmo.int)

---

## 👥 Team

**Huzzlers** — Team ID `T052` — Smart India Hackathon 2026

## 📄 License

MIT — see [`LICENSE`](LICENSE).

<div align="center">

*Built for people who just want to know if it's going to rain — and for the ones watching the sky change over an entire district.*

</div>
