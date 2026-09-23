"""
River visualisation.

Two modes:
  get_river_by_name("ganga")  -> the named river as a highlighted GeoJSON
                                  polyline, with a fit-bounds box and an info
                                  blurb the map shows on click. This is what a
                                  user means by "show the Ganga".
  get_rivers_near(lat, lon)    -> whichever major rivers pass through the area
                                  around a place ("rivers in Assam").

The geometry is a curated, simplified trace of each river's real course
(source -> mouth), stored once here. It is deliberately generalised (tens of
vertices, not thousands) so it draws instantly and legibly in a browser — it is
a schematic of the real course, not a survey-grade channel, and the app says so.
For higher fidelity you can swap in OSM/Overpass or HydroSHEDS geometry behind
the same interface (see README).
"""
from __future__ import annotations

from typing import Optional

# Each river: display name, aliases (lowercase), an info line, and a course as
# [lat, lon] waypoints from source to mouth.
RIVERS_DB = {
    "ganga": {
        "name": "Ganga (Ganges)",
        "aliases": ["ganga", "ganges", "ganga river", "ganges river"],
        "info": "~2,525 km. Rises at Gaumukh (Gangotri glacier), flows through "
                "the northern plains and joins the Bay of Bengal via the "
                "Ganga–Brahmaputra delta. India's largest river basin.",
        "course": [
            [30.99, 79.08], [30.13, 78.77], [29.95, 78.16], [29.39, 78.07],
            [28.86, 78.78], [27.38, 79.60], [26.46, 80.35], [25.94, 81.10],
            [25.43, 81.85], [25.32, 83.01], [25.60, 83.97], [25.62, 85.14],
            [25.24, 86.98], [24.80, 87.93], [23.51, 88.05], [22.57, 88.36],
            [21.95, 88.10],
        ],
    },
    "yamuna": {
        "name": "Yamuna",
        "aliases": ["yamuna", "jamuna", "yamuna river"],
        "info": "~1,376 km. Rises at Yamunotri, passes Delhi and Agra, and "
                "joins the Ganga at Prayagraj (Allahabad). Largest Ganga tributary.",
        "course": [
            [31.01, 78.45], [30.45, 77.90], [30.00, 77.55], [29.38, 77.25],
            [28.66, 77.23], [27.49, 77.68], [27.18, 78.02], [26.23, 78.18],
            [25.43, 81.85],
        ],
    },
    "brahmaputra": {
        "name": "Brahmaputra",
        "aliases": ["brahmaputra", "brahmaputra river", "luit", "tsangpo"],
        "info": "~2,900 km. Enters India in Arunachal Pradesh, braids across "
                "the Assam valley, then joins the Ganga delta in Bangladesh. "
                "Highly braided and sediment-laden; prone to major floods.",
        "course": [
            [27.83, 95.67], [27.70, 95.40], [27.48, 94.90], [26.95, 94.20],
            [26.62, 93.03], [26.18, 91.74], [26.17, 90.62], [25.18, 89.68],
            [24.10, 89.83], [23.85, 89.75], [22.90, 90.50],
        ],
    },
    "godavari": {
        "name": "Godavari",
        "aliases": ["godavari", "godavari river"],
        "info": "~1,465 km. Rises near Nashik (Trimbak) in the Western Ghats "
                "and crosses the Deccan to the Bay of Bengal. Peninsular India's "
                "longest river.",
        "course": [
            [19.93, 73.53], [19.97, 74.20], [19.47, 75.30], [19.15, 77.32],
            [18.67, 78.10], [18.00, 79.60], [17.33, 80.60], [16.98, 81.78],
            [16.32, 82.04],
        ],
    },
    "krishna": {
        "name": "Krishna",
        "aliases": ["krishna", "krishna river", "krishnaveni"],
        "info": "~1,400 km. Rises near Mahabaleshwar and reaches the Bay of "
                "Bengal near Vijayawada. Major peninsular river.",
        "course": [
            [17.92, 73.66], [17.28, 74.20], [16.85, 74.57], [16.52, 76.30],
            [16.20, 77.30], [16.35, 78.90], [16.51, 80.62], [15.95, 80.90],
        ],
    },
    "narmada": {
        "name": "Narmada",
        "aliases": ["narmada", "narmada river", "nerbudda"],
        "info": "~1,312 km. Rises at Amarkantak and flows WEST through a rift "
                "valley to the Arabian Sea — unusual for a major Indian river.",
        "course": [
            [22.67, 81.76], [22.95, 80.20], [23.18, 79.98], [22.70, 78.10],
            [22.50, 76.90], [22.18, 75.30], [21.90, 74.40], [21.70, 72.97],
            [21.63, 72.62],
        ],
    },
    "mahanadi": {
        "name": "Mahanadi",
        "aliases": ["mahanadi", "mahanadi river"],
        "info": "~858 km. Drains Chhattisgarh and Odisha into the Bay of Bengal "
                "through a broad, flood-prone delta near Cuttack.",
        "course": [
            [20.10, 81.30], [20.55, 81.90], [21.25, 81.63], [21.47, 83.30],
            [21.47, 83.97], [20.90, 85.10], [20.46, 85.88], [20.28, 86.70],
        ],
    },
    "kaveri": {
        "name": "Kaveri (Cauvery)",
        "aliases": ["kaveri", "cauvery", "kaveri river", "cauvery river"],
        "info": "~800 km. Rises at Talakaveri in the Western Ghats and reaches "
                "the Bay of Bengal across the Tamil Nadu delta.",
        "course": [
            [12.39, 75.50], [12.42, 76.20], [12.30, 76.70], [11.90, 77.10],
            [11.34, 77.72], [10.95, 78.50], [10.80, 79.14], [11.00, 79.85],
        ],
    },
    "tapti": {
        "name": "Tapti (Tapi)",
        "aliases": ["tapti", "tapi", "tapti river", "tapi river"],
        "info": "~724 km. Another westward-flowing river, from Multai in Madhya "
                "Pradesh to the Arabian Sea near Surat.",
        "course": [
            [21.77, 78.24], [21.55, 77.30], [21.30, 76.20], [21.30, 75.10],
            [21.15, 74.00], [21.20, 73.00], [21.30, 72.68],
        ],
    },
    "hooghly": {
        "name": "Hooghly",
        "aliases": ["hooghly", "hoogly", "hugli"],
        "info": "Distributary of the Ganga through Kolkata to the Bay of Bengal; "
                "the western arm of the Ganga delta.",
        "course": [
            [24.80, 87.93], [24.10, 88.15], [23.40, 88.42], [22.57, 88.36],
            [21.95, 88.05],
        ],
    },
    "indus": {
        "name": "Indus (Sindhu)",
        "aliases": ["indus", "sindhu", "indus river"],
        "info": "~3,180 km. Rises in Tibet, flows through Ladakh into Pakistan. "
                "Only the upper reaches are within India.",
        "course": [
            [32.30, 79.20], [33.50, 78.10], [34.15, 77.58], [34.60, 76.10],
            [34.80, 74.60], [34.30, 73.90],
        ],
    },
}


def _to_feature(river: dict) -> dict:
    coords = [[lon, lat] for lat, lon in river["course"]]
    return {
        "type": "Feature",
        "properties": {"name": river["name"], "info": river["info"]},
        "geometry": {"type": "LineString", "coordinates": coords},
    }


def _bounds(river: dict) -> list:
    lats = [p[0] for p in river["course"]]
    lons = [p[1] for p in river["course"]]
    return [[min(lats), min(lons)], [max(lats), max(lons)]]  # [[s,w],[n,e]]


def find_river(name: str) -> Optional[str]:
    if not name:
        return None
    q = name.lower().strip()
    q = q.replace(" river system", "").replace(" river", "").strip()
    for key, r in RIVERS_DB.items():
        if q == key or q in r["aliases"]:
            return key
    # substring match ("the mighty ganga")
    for key, r in RIVERS_DB.items():
        for a in r["aliases"]:
            if a in q:
                return key
    return None


def get_river_by_name(name: str) -> Optional[dict]:
    key = find_river(name)
    if not key:
        return None
    river = RIVERS_DB[key]
    return {
        "name": river["name"],
        "info": river["info"],
        "geojson": {"type": "FeatureCollection", "features": [_to_feature(river)],
                    "source": "WeatherGPT curated river atlas (simplified course)"},
        "bounds": _bounds(river),
    }


def get_rivers_near(lat: float, lon: float, pad: float = 2.0) -> dict:
    """Return any curated rivers whose course passes near a point/region."""
    feats = []
    names = []
    for key, r in RIVERS_DB.items():
        for plat, plon in r["course"]:
            if abs(plat - lat) <= pad and abs(plon - lon) <= pad:
                feats.append(_to_feature(r))
                names.append(r["name"])
                break
    return {
        "type": "FeatureCollection",
        "features": feats,
        "names": names,
        "source": "WeatherGPT curated river atlas (simplified course)",
    }
