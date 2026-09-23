"""
Live weather via Open-Meteo (https://open-meteo.com) — no API key required,
near-real-time current conditions plus hourly and daily forecast.

Returns a normalised dict so the LLM and the frontend never touch raw provider
JSON. On failure returns {"ok": False, ...} rather than raising.
"""
from __future__ import annotations

from typing import Optional

from services.http import get_json, cache_get, cache_set

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather-interpretation codes -> short human labels.
WMO = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Freezing rain", 67: "Heavy freezing rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Slight showers", 81: "Moderate showers", 82: "Violent showers",
    85: "Snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm w/ hail", 99: "Severe thunderstorm w/ hail",
}


def _deg_to_compass(deg) -> str:
    if deg is None:
        return ""
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return dirs[int((float(deg) + 22.5) // 45) % 8]


async def get_weather(lat: float, lon: float) -> dict:
    key = f"wx:{round(lat,2)}:{round(lon,2)}"
    cached = cache_get(key)
    if cached is not None:
        return cached

    data = await get_json(FORECAST_URL, params={
        "latitude": lat, "longitude": lon,
        "current": ",".join([
            "temperature_2m", "apparent_temperature", "relative_humidity_2m",
            "is_day", "precipitation", "weather_code", "cloud_cover",
            "pressure_msl", "surface_pressure", "wind_speed_10m",
            "wind_direction_10m", "wind_gusts_10m",
        ]),
        "hourly": "temperature_2m,precipitation_probability,weather_code",
        "daily": ",".join([
            "weather_code", "temperature_2m_max", "temperature_2m_min",
            "precipitation_probability_max", "wind_speed_10m_max", "uv_index_max",
        ]),
        "timezone": "auto", "forecast_days": 5,
    })

    if not data or "current" not in data:
        return {"ok": False, "error": "weather_unavailable"}

    c = data["current"]
    code = c.get("weather_code")
    result = {
        "ok": True,
        "source": "Open-Meteo",
        "updated": c.get("time"),
        "current": {
            "temp_c": c.get("temperature_2m"),
            "feels_like_c": c.get("apparent_temperature"),
            "humidity": c.get("relative_humidity_2m"),
            "precip_mm": c.get("precipitation"),
            "cloud_cover": c.get("cloud_cover"),
            "pressure_hpa": c.get("pressure_msl"),
            "wind_kph": c.get("wind_speed_10m"),
            "wind_dir": _deg_to_compass(c.get("wind_direction_10m")),
            "wind_gust_kph": c.get("wind_gusts_10m"),
            "condition": WMO.get(code, "—"),
            "is_day": bool(c.get("is_day", 1)),
        },
        "daily": [],
    }

    daily = data.get("daily", {})
    times = daily.get("time", []) or []
    for i, day in enumerate(times):
        result["daily"].append({
            "date": day,
            "condition": WMO.get((daily.get("weather_code") or [None])[i], "—"),
            "temp_max_c": (daily.get("temperature_2m_max") or [None])[i],
            "temp_min_c": (daily.get("temperature_2m_min") or [None])[i],
            "precip_prob": (daily.get("precipitation_probability_max") or [None])[i],
            "wind_max_kph": (daily.get("wind_speed_10m_max") or [None])[i],
            "uv_max": (daily.get("uv_index_max") or [None])[i],
        })

    cache_set(key, result, ttl=600)  # 10 min — Open-Meteo updates periodically
    return result
