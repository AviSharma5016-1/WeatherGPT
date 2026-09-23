"""
Geocoding — place name -> coordinates, hard-restricted to South Asia.

This app is India-focused, so a hard bounding box (roughly the subcontinent)
is the primary safety net: a candidate outside it is NEVER accepted, no
matter how it ranks in the provider's fuzzy match. This is what actually
stops "Ganga" resolving to a village in Italy or "Shimoga" resolving to
"Shimogamo" in Japan — those are outside the box, full stop, regardless of
country-code metadata (which can be missing or unreliable).

Two more real problems, now fixed:
  1. "suburb, City" / "suburb City" strings ("Aundh Pune", "Shimoga,
     Karnataka") are split into a locality + a context word; we search the
     locality and keep only the candidate whose district/state text actually
     contains the context word.
  2. Many Indian cities have official post-2000s renames (Shimoga ->
     Shivamogga, Mysore -> Mysuru, Gurgaon -> Gurugram, ...). A common old
     name can fuzzy-match nothing useful in-region. We rewrite known old
     names to their current official name before querying.

Uses Open-Meteo geocoding (keyless). Falls back to a small offline gazetteer
only when the network is unavailable.
"""
from __future__ import annotations

from typing import Optional

from services.http import get_json, cache_get, cache_set

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"

# Roughly the Indian subcontinent (India, Nepal, Bhutan, Bangladesh, Sri
# Lanka, most of Pakistan/Myanmar). Anything outside this is rejected outright
# — this app never needs a result beyond South Asia.
BBOX = {"lat_min": 4.0, "lat_max": 38.0, "lon_min": 60.0, "lon_max": 101.0}


def _in_bbox(lat, lon) -> bool:
    try:
        return (BBOX["lat_min"] <= float(lat) <= BBOX["lat_max"]
                and BBOX["lon_min"] <= float(lon) <= BBOX["lon_max"])
    except (TypeError, ValueError):
        return False


# Common old/colonial/pre-rename names -> current official geocoding name.
# Only entries that plausibly fail a fuzzy match on the OLD name need to be
# here; well-known ones (Bombay/Calcutta/Madras/Bangalore/Cochin/Trivandrum)
# already resolve fine on most providers but are included for safety.
RENAME_ALIASES = {
    "shimoga": "shivamogga", "mysore": "mysuru", "gurgaon": "gurugram",
    "allahabad": "prayagraj", "baroda": "vadodara", "poona": "pune",
    "bombay": "mumbai", "calcutta": "kolkata", "madras": "chennai",
    "bangalore": "bengaluru", "cochin": "kochi", "trivandrum": "thiruvananthapuram",
    "belgaum": "belagavi", "hubli": "hubballi", "mangalore": "mangaluru",
    "simla": "shimla", "cawnpore": "kanpur", "orissa": "odisha",
    "pondicherry": "puducherry", "bareilly": "bareilly",
}

_FALLBACK = {
    "india": {"name": "India", "lat": 22.5, "lon": 80.5, "zoom": 5},
    "pune": {"name": "Pune", "lat": 18.52, "lon": 73.86, "zoom": 11},
    "aundh": {"name": "Aundh, Pune", "lat": 18.56, "lon": 73.81, "zoom": 13},
    "baner": {"name": "Baner, Pune", "lat": 18.56, "lon": 73.78, "zoom": 13},
    "shimoga": {"name": "Shivamogga, Karnataka", "lat": 13.93, "lon": 75.57, "zoom": 11},
    "shivamogga": {"name": "Shivamogga, Karnataka", "lat": 13.93, "lon": 75.57, "zoom": 11},
    "mumbai": {"name": "Mumbai", "lat": 19.08, "lon": 72.88, "zoom": 11},
    "delhi": {"name": "Delhi", "lat": 28.61, "lon": 77.21, "zoom": 10},
    "bengaluru": {"name": "Bengaluru", "lat": 12.97, "lon": 77.59, "zoom": 11},
    "kerala": {"name": "Kerala", "lat": 10.2, "lon": 76.5, "zoom": 7},
    "assam": {"name": "Assam", "lat": 26.2, "lon": 92.9, "zoom": 7},
    "odisha": {"name": "Odisha", "lat": 20.3, "lon": 85.8, "zoom": 7},
    "chennai": {"name": "Chennai", "lat": 13.08, "lon": 80.27, "zoom": 11},
    "kolkata": {"name": "Kolkata", "lat": 22.57, "lon": 88.36, "zoom": 11},
    "nepal": {"name": "Nepal", "lat": 28.39, "lon": 84.12, "zoom": 7},
    "bihar": {"name": "Bihar", "lat": 25.6, "lon": 85.1, "zoom": 7},
    "himachal pradesh": {"name": "Himachal Pradesh", "lat": 31.9, "lon": 77.2, "zoom": 7},
    "karnataka": {"name": "Karnataka", "lat": 15.3, "lon": 75.7, "zoom": 7},
}


def _zoom_for(item: dict) -> int:
    kind = (item.get("feature_code") or "").upper()
    if kind.startswith("PCLI"):
        return 5
    if kind.startswith("ADM1"):
        return 7
    if kind.startswith("ADM2"):
        return 9
    return 11


def _fmt(item: dict, fallback_name: str) -> dict:
    parts = [item.get("name", fallback_name)]
    if item.get("admin1") and item.get("admin1") != parts[0]:
        parts.append(item["admin1"])
    return {
        "name": ", ".join(parts),
        "lat": item.get("latitude"),
        "lon": item.get("longitude"),
        "zoom": _zoom_for(item),
        "admin": item.get("admin1", ""),
        "country": item.get("country", ""),
    }


def _resolve_alias(word: str) -> str:
    return RENAME_ALIASES.get(word.lower().strip(), word)


async def _search(name: str, count: int = 10) -> list[dict]:
    data = await get_json(GEOCODE_URL, params={
        "name": name, "count": count, "language": "en", "format": "json"})
    return (data or {}).get("results") or []


def _first_in_bbox(results: list[dict]) -> Optional[dict]:
    for r in results:
        if _in_bbox(r.get("latitude"), r.get("longitude")):
            return r
    return None


async def _query_plain(name: str) -> Optional[dict]:
    """Search one string; accept only a candidate inside the South-Asia box."""
    item = _first_in_bbox(await _search(_resolve_alias(name), 8))
    return _fmt(item, name) if item else None


async def _query_locality(locality: str, context: str) -> Optional[dict]:
    """'Shimoga' within 'Karnataka': prefer a candidate whose district/state
    mentions the context word AND is inside the South-Asia box — both checks
    matter, since context text alone isn't a location guarantee."""
    ctx = context.lower()
    for item in await _search(_resolve_alias(locality), 10):
        if not _in_bbox(item.get("latitude"), item.get("longitude")):
            continue
        fields = " ".join(str(item.get(k, "")) for k in ("admin1", "admin2", "admin3", "admin4")).lower()
        if ctx in fields:
            return _fmt(item, locality)
    return None


def _parts(query: str) -> list[str]:
    """'Shimoga, Karnataka' and 'Aundh Pune' both -> ['Shimoga', 'Karnataka']."""
    return [p for p in query.replace(",", " ").split() if p]


async def geocode(query: str) -> Optional[dict]:
    if not query:
        return None
    key = "geo:" + query.lower().strip()
    cached = cache_get(key)
    if cached is not None:
        return cached

    result: Optional[dict] = None
    parts = _parts(query)

    if len(parts) >= 2:
        # "<locality> <context>" — try locality constrained to context first
        # (handles both "Shimoga, Karnataka" and "Aundh Pune" shapes).
        result = await _query_locality(" ".join(parts[:-1]), parts[-1])

    if not result:
        # Whole string, then each individual part, plain in-bbox search.
        for variant in [query] + parts:
            result = await _query_plain(variant)
            if result:
                break

    if not result:
        for variant in [query] + parts:
            result = _FALLBACK.get(_resolve_alias(variant).lower().strip())
            if result:
                break

    if result:
        cache_set(key, result, ttl=86400)
    return result
