"""
Data-driven wind field.

Fetches REAL current wind (speed + direction) from Open-Meteo on a coarse grid
over a bounding box — Open-Meteo accepts comma-separated coordinate lists, so
the whole grid is one keyless request. The frontend animates particles along
this field, so the animation represents actual data (not decoration).

Returns {ok, points:[{lat,lon,speed,dir}], bbox, updated}. On failure ok=False.
"""
from __future__ import annotations

from services.http import get_json, cache_get, cache_set

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


def _grid(lat: float, lon: float, half: float, n: int):
    lats, lons = [], []
    step = (2 * half) / (n - 1)
    for i in range(n):
        for j in range(n):
            lats.append(round(lat - half + i * step, 3))
            lons.append(round(lon - half + j * step, 3))
    return lats, lons


async def get_wind_field(lat: float, lon: float, half: float = 4.0, n: int = 6) -> dict:
    key = f"wind:{round(lat,1)}:{round(lon,1)}:{round(half,1)}:{n}"
    cached = cache_get(key)
    if cached is not None:
        return cached

    lats, lons = _grid(lat, lon, half, n)
    data = await get_json(FORECAST_URL, params={
        "latitude": ",".join(map(str, lats)),
        "longitude": ",".join(map(str, lons)),
        "current": "wind_speed_10m,wind_direction_10m",
        "timezone": "auto",
    })

    points = []
    updated = None
    # Open-Meteo returns a list of objects when multiple coords are given,
    # or a single object for one coord. Normalise both.
    entries = data if isinstance(data, list) else ([data] if data else [])
    for e in entries:
        cur = (e or {}).get("current") or {}
        if "wind_speed_10m" in cur:
            points.append({
                "lat": e.get("latitude"),
                "lon": e.get("longitude"),
                "speed": cur.get("wind_speed_10m"),
                "dir": cur.get("wind_direction_10m"),
            })
            updated = updated or cur.get("time")

    result = {
        "ok": len(points) > 0,
        "source": "Open-Meteo",
        "updated": updated,
        "bbox": [lat - half, lon - half, lat + half, lon + half],
        "points": points,
    }
    cache_set(key, result, ttl=600)
    return result
