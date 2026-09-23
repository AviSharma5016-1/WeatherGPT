"""
WeatherGPT — FastAPI application entry point.

Flow for a chat query:
    USER QUERY
      -> classify() intent + place + language
      -> geocode() the place (keyless Open-Meteo)  ..... map centre/zoom
      -> retrieve live data by intent:
           weather/forecast/rain/wind/temp/clouds -> Open-Meteo
           rivers                                 -> Overpass (real GeoJSON)
           flood/cyclone/news                     -> ReliefWeb + Google News RSS
      -> synthesise a natural answer (Gemini if configured, else template)
      -> return {answer, sources, map: {center, zoom, layer, geojson}}

Every stage degrades gracefully: a failed upstream shortens the answer, it
never 500s the request. No secrets are ever returned to the browser except the
Google Maps *browser* key (meant to be public, domain-restricted in GCP).

Run:  uvicorn app:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import settings
from services.geocode import geocode
from services.intent import classify
from services.weather import get_weather
from services.news import get_news
from services.rivers import get_river_by_name, get_rivers_near
from services.wind import get_wind_field
from services.alerts import get_alerts
from services.llm import get_provider, synthesize, LANG_NAMES

app = FastAPI(title="WeatherGPT", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).parent / "static"


class ChatRequest(BaseModel):
    text: str
    lang: str = ""          # "" -> auto-detect from the query
    mode: str = "layman"    # "layman" | "scientific" (affects answer depth)


# --------------------------------------------------------------------------
# Config endpoint — public capability flags for the frontend (no secrets
# beyond the intended-public browser keys).
# --------------------------------------------------------------------------
@app.get("/api/config")
async def api_config():
    caps = settings.public_capabilities()
    caps["languages"] = LANG_NAMES
    return caps


# --------------------------------------------------------------------------
# Geocoding — used by the frontend for direct "centre on this place" actions.
# --------------------------------------------------------------------------
@app.get("/api/geocode")
async def api_geocode(q: str):
    result = await geocode(q)
    if not result:
        return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
    return {"ok": True, **result}


# --------------------------------------------------------------------------
# Weather — direct lat/lon lookup (used when the map is clicked).
# --------------------------------------------------------------------------
@app.get("/api/weather")
async def api_weather(lat: float, lon: float):
    return await get_weather(lat, lon)


# --------------------------------------------------------------------------
# Rivers — by name (highlight a specific river) or by area (rivers near a point).
# --------------------------------------------------------------------------
@app.get("/api/rivers")
async def api_rivers(name: str = "", lat: float = 0.0, lon: float = 0.0):
    if name:
        r = get_river_by_name(name)
        if r:
            return {"ok": True, "mode": "named", **r}
    area = get_rivers_near(lat, lon)
    return {"ok": bool(area["features"]), "mode": "area", **area}


# --------------------------------------------------------------------------
# Wind — real wind field on a grid for the animated overlay.
# --------------------------------------------------------------------------
@app.get("/api/alerts")
async def api_alerts():
    """Live detected events (cached ~5 min server-side, so polling is cheap)."""
    return await get_alerts()


@app.get("/api/wind")
async def api_wind(lat: float, lon: float, half: float = 4.0):
    return await get_wind_field(lat, lon, half=half)


# --------------------------------------------------------------------------
# Main chat endpoint — orchestrates everything.
# --------------------------------------------------------------------------
@app.post("/api/chat")
async def api_chat(req: ChatRequest):
    text = (req.text or "").strip()
    if not text:
        return JSONResponse({"ok": False, "error": "empty_query"}, status_code=400)

    parsed = classify(text)
    lang = req.lang or parsed["lang"] or "en"
    intent = parsed["intent"]
    place_q = parsed["place"] or "India"

    # 1) Resolve location (keyless). Drives map centre + data lookups.
    geo_exact = await geocode(place_q)
    geo = geo_exact or await geocode("India")
    place_name = geo["name"] if geo else place_q
    lat, lon = (geo["lat"], geo["lon"]) if geo else (22.5, 80.5)
    zoom = geo["zoom"] if geo else 5
    geocode_failed = (not geo_exact) and place_q.lower() != "india"

    context = {"intent": intent, "place_name": place_name, "geocode_failed": geocode_failed,
               "requested_place": place_q if geocode_failed else None,
               "weather": None, "news": [], "rivers": None}
    sources: list[dict] = []
    map_state = {"center": [lat, lon], "zoom": zoom, "layer": parsed["layer"],
                 "geojson": None, "place": place_name}

    # 2) Retrieve live data by intent.
    if intent in ("weather", "forecast", "rain", "wind", "temperature", "clouds", "general"):
        wx = await get_weather(lat, lon)
        context["weather"] = wx
        if wx.get("ok"):
            sources.append({"label": "Weather", "value": "Open-Meteo",
                            "updated": wx.get("updated")})

    if intent == "rivers":
        river = get_river_by_name(parsed.get("river_query") or place_q)
        if river:
            context["rivers"] = {"reachable": True, "named": river["name"],
                                 "info": river["info"], "features": river["geojson"]["features"]}
            map_state["geojson"] = {"type": "rivers", "data": river["geojson"]}
            map_state["bounds"] = river["bounds"]
            map_state["place"] = river["name"]
            place_name = river["name"]
            sources.append({"label": "Rivers", "value": river["name"] + " — curated river atlas"})
        else:
            area = get_rivers_near(lat, lon)
            context["rivers"] = {"reachable": bool(area["features"]),
                                 "features": area["features"], "names": area.get("names", [])}
            if area["features"]:
                map_state["geojson"] = {"type": "rivers", "data": area}
                sources.append({"label": "Rivers", "value": ", ".join(area["names"])})

    if intent in ("flood", "cyclone", "news"):
        disaster = parsed["disaster"]
        topic = {"flood": "flood", "cyclone": "cyclone"}.get(intent, "weather")
        news = await get_news(f"{topic} {place_name}", disaster=disaster)
        context["news"] = news
        for n in news:
            sources.append({"label": n["source"], "value": n["title"],
                            "url": n["url"], "updated": n.get("published", "")})
        # For flood/cyclone we still centre the map; we do NOT draw a fabricated
        # extent. Any overlay shown is a live tile layer, clearly labelled.

    if intent == "alerts":
        data = await get_alerts()
        found = data.get("alerts", [])
        if parsed["place"]:
            p = parsed["place"].lower()
            scoped = [a for a in found if p in a["region"].lower() or p in a["group"].lower()]
            found = scoped
        top = found[:6]
        context["alerts_feeds_ok"] = bool(data.get("ok"))
        context["alerts"] = [{
            "hazard": a["hazard_label"], "region": a["region"], "confidence": a["confidence"],
            "latest": a["latest"], "headline": a["items"][0]["title"] if a["items"] else "",
        } for a in top]
        map_state.update({"center": [22.5, 80.5], "zoom": 5, "layer": "alerts", "place": "India"})
        for a in top:
            if a["items"]:
                it = a["items"][0]
                sources.append({"label": it["source"], "value": it["title"],
                                "url": it["url"], "updated": it["published"]})

    # 3) Synthesise the answer.
    provider = get_provider()
    if provider.name == "fallback":
        answer = synthesize(context)
        # Fallback can't translate; be explicit if a non-English reply was asked.
        translated_note = (lang != "en")
    else:
        prompt = _build_prompt(text, context, req.mode, lang)
        answer = await provider.generate(prompt, lang=lang)
        if not answer:  # LLM failed at runtime -> degrade to template
            answer = synthesize(context)
            translated_note = (lang != "en")
        else:
            translated_note = False

    return {
        "ok": True,
        "intent": intent,
        "answer": answer,
        "lang": lang,
        "needs_translation_key": translated_note,
        "map": map_state,
        "sources": sources,
        "place": place_name,
    }


def _build_prompt(query: str, context: dict, mode: str, lang: str) -> str:
    """Ground the LLM strictly in retrieved data."""
    import json
    depth = ("Give a plain, everyday explanation a non-expert would understand."
             if mode == "layman" else
             "Give a technically precise explanation using correct meteorological terms.")
    lang_name = LANG_NAMES.get(lang, "English")
    geo_note = ""
    if context.get("geocode_failed"):
        geo_note = (f' The place "{context.get("requested_place")}" could not be located, so DATA '
                    f"is for India overall, not that specific place — say this plainly, don't imply "
                    f"the DATA is specific to it.")
    return (
        f"USER QUESTION: {query}\n\n"
        f"DATA (the only facts you may use):\n{json.dumps(context, ensure_ascii=False, default=str)[:6000]}\n\n"
        f"INSTRUCTIONS: {depth} Reply in {lang_name}.{geo_note} Attribute any news claims to "
        f"their source. If a value is missing from DATA, do not invent it — say it "
        f"isn't available. For flood/cyclone, distinguish reported affected areas "
        f"from verified satellite extent. Keep it under ~120 words."
    )


# --------------------------------------------------------------------------
# Frontend (served by the same app so there's a single deployable unit).
# --------------------------------------------------------------------------
@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host=settings.HOST, port=settings.PORT, reload=False)
