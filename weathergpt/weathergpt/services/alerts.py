"""
Live event monitor — the early-warning feed behind the 🔔 bell, the red map
pins and the pop-ups.

Every few minutes it checks (all keyless):
  • Google News RSS   — a batch of hazard searches restricted to the last 48 h
  • GDACS             — UN/EC Global Disaster Alert and Coordination System
                        (floods, cyclones, quakes, droughts) with coordinates
  • USGS              — earthquakes M4.5+ in the past week, with coordinates
  • NDMA SACHET       — India's official Common Alerting Protocol feed

News headlines are classified by hazard (flood, cyclone, landslide, …) and
placed with the gazetteer. Reports of the SAME hazard in the SAME region are
merged into one event, and the number of DISTINCT outlets is counted:
    1 outlet   -> "Single report — unverified"   (low)
    2 outlets  -> "Corroborated by 2 outlets"   (medium)
    3+ outlets -> "Reported by N outlets"       (high)
Official feeds (GDACS/USGS/NDMA) are marked authoritative, and any news about
the same hazard+region is merged into them as supporting coverage.

Nothing here is invented: every event is backed by at least one real item with
a link. Failed feeds are reported in `sources_status`, never hidden.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Optional
from xml.etree import ElementTree as ET

from services.http import get_text, get_json, cache_get, cache_set
from services.gazetteer import find_region

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
GDACS_RSS = "https://www.gdacs.org/xml/rss.xml"
USGS_FEED = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson"
# NDMA's public CAP RSS. If NDMA moves it, update this one line.
NDMA_SACHET_RSS = "https://sachet.ndma.gov.in/cap_public_website/rss/rss_india.xml"

NEWS_WINDOW = timedelta(hours=48)
OFFICIAL_WINDOW = timedelta(days=7)
BBOX = (5.0, 60.0, 38.0, 100.0)  # south, west, north, east — South Asia
CACHE_KEY = "alerts:v1"

NEWS_QUERIES = [
    "flood India", "flash flood India", "cyclone Bay of Bengal", "cyclone Arabian Sea",
    "landslide India", "cloudburst", "heavy rain red alert India", "earthquake India",
    "heatwave India", "flood Assam", "flood Nepal", "flood Bangladesh",
]

# id, label, icon, pattern — order matters (more specific first)
HAZARDS = [
    ("cloudburst", "Cloudburst", "⛈️", r"\bcloud ?bursts?\b"),
    ("landslide", "Landslide", "⛰️", r"\b(landslides?|landslips?|mudslides?)\b"),
    ("cyclone", "Cyclone", "🌀", r"\b(cyclones?|cyclonic storm|deep depression|landfall)\b"),
    ("flood", "Flood", "🌊", r"\b(floods?|flooding|flooded|flash[- ]floods?|inundat\w*|waterlogg\w*|deluge)\b"),
    ("earthquake", "Earthquake", "🏚️", r"\b(earthquakes?|quakes?|tremors?|seismic)\b"),
    ("heatwave", "Heatwave", "🔥", r"\b(heat ?waves?|heatstroke|severe heat)\b"),
    ("heavy_rain", "Heavy rain", "🌧️", r"\b(heavy|very heavy|extremely heavy) (rain|rainfall)\b|\b(red|orange) alert\b"),
    ("drought", "Drought", "🏜️", r"\bdroughts?\b"),
]
_HAZ = [(h, re.compile(p, re.I)) for *h, p in HAZARDS]
HAZ_BY_ID = {h[0]: tuple(h) for h in HAZARDS}

# Headlines that use hazard words figuratively or are retrospectives.
EXCLUDE = re.compile(
    r"\b(flood of|flooded with|floodgates? of|floodlights?|heat of the|political storm|"
    r"box office|mock drill|anniversary|years? (ago|after|since)|memorial|stock market|"
    r"sensex|nifty|film|movie|trailer)\b", re.I)

GDACS_TYPES = {"FL": "flood", "TC": "cyclone", "EQ": "earthquake", "DR": "drought"}
SEV_RANK = {"low": 1, "medium": 2, "high": 3}


# ----------------------------- helpers ------------------------------------
def detect_hazard(text: str) -> Optional[tuple]:
    if not text or EXCLUDE.search(text):
        return None
    for h, rx in _HAZ:
        if rx.search(text):
            return tuple(h)
    return None


def _parse_date(s: str) -> Optional[datetime]:
    if not s:
        return None
    s = s.strip()
    try:
        d = parsedate_to_datetime(s)
    except Exception:
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


def _tag(el) -> str:
    return el.tag.split("}")[-1] if isinstance(el.tag, str) else ""


def _clean(text: str) -> str:
    import html
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def _in_bbox(lat: float, lon: float) -> bool:
    s, w, n, e = BBOX
    return s <= lat <= n and w <= lon <= e


# ----------------------------- fetchers -----------------------------------
def parse_google_news(xml: str) -> list[dict]:
    out = []
    try:
        root = ET.fromstring(xml)
    except Exception:
        return out
    for item in root.iter("item"):
        title = _clean(item.findtext("title", ""))
        src_el = item.find("source")
        source = _clean(src_el.text) if src_el is not None and src_el.text else ""
        if source and title.endswith(" - " + source):
            title = title[: -(len(source) + 3)]
        if not source and " - " in title:
            title, source = title.rsplit(" - ", 1)
        out.append({
            "title": title.strip(),
            "source": (source or "Unknown outlet").strip(),
            "url": (item.findtext("link", "") or "").strip(),
            "published": _parse_date(item.findtext("pubDate", "")),
        })
    return out


async def fetch_news() -> tuple[list[dict], bool]:
    async def one(q):
        xml = await get_text(GOOGLE_NEWS_RSS, params={
            "q": f"{q} when:2d", "hl": "en-IN", "gl": "IN", "ceid": "IN:en"})
        return parse_google_news(xml) if xml else None
    results = await asyncio.gather(*(one(q) for q in NEWS_QUERIES), return_exceptions=True)
    items, any_ok = [], False
    for r in results:
        if isinstance(r, list):
            any_ok = True
            items.extend(r)
    return items, any_ok


def parse_gdacs(xml: str) -> list[dict]:
    out = []
    try:
        root = ET.fromstring(xml)
    except Exception:
        return out
    for item in root.iter("item"):
        d = {}
        for ch in item.iter():
            t = _tag(ch)
            if t and t not in d and ch.text and ch.text.strip():
                d[t] = ch.text.strip()
        hazard = GDACS_TYPES.get((d.get("eventtype") or "").upper())
        try:
            lat, lon = float(d.get("lat")), float(d.get("long"))
        except (TypeError, ValueError):
            continue
        if not hazard or not _in_bbox(lat, lon):
            continue
        out.append({
            "hazard": hazard, "lat": lat, "lon": lon,
            "title": _clean(d.get("title", "")), "url": d.get("link", ""),
            "published": _parse_date(d.get("pubDate") or d.get("fromdate", "")),
            "level": (d.get("alertlevel") or "").lower(),
            "event_id": d.get("eventid", ""), "country": d.get("country", ""),
        })
    return out


def parse_usgs(data: dict) -> list[dict]:
    out = []
    for f in (data or {}).get("features", []):
        p = f.get("properties", {}) or {}
        coords = (f.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        lon, lat = coords[0], coords[1]
        if not _in_bbox(lat, lon):
            continue
        mag = p.get("mag") or 0
        out.append({
            "hazard": "earthquake", "lat": lat, "lon": lon,
            "title": p.get("title") or f"M{mag} earthquake", "url": p.get("url", ""),
            "published": datetime.fromtimestamp((p.get("time") or 0) / 1000, tz=timezone.utc),
            "level": "red" if mag >= 6 else "orange" if mag >= 5 else "green",
            "event_id": f.get("id", ""), "place": p.get("place", ""),
        })
    return out


def parse_ndma(xml: str) -> list[dict]:
    out = []
    try:
        root = ET.fromstring(xml)
    except Exception:
        return out
    for item in root.iter("item"):
        title = _clean(item.findtext("title", ""))
        desc = _clean(item.findtext("description", ""))
        out.append({"title": title, "text": f"{title} {desc}",
                    "url": (item.findtext("link", "") or "").strip(),
                    "published": _parse_date(item.findtext("pubDate", ""))})
    return out


# ----------------------------- clustering ---------------------------------
def build_events(news, gdacs, usgs, ndma, now: Optional[datetime] = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    events: dict[str, dict] = {}

    def get_event(key, haz, region, lat=None, lon=None, precise=None):
        ev = events.get(key)
        if ev is None:
            ev = events[key] = {
                "hazard": haz[0], "hazard_label": haz[1], "icon": haz[2],
                "region": region["name"], "group": region["group"],
                "lat": region["lat"] if lat is None else lat,
                "lon": region["lon"] if lon is None else lon,
                "precise": region["precise"] if precise is None else precise,
                "items": [], "outlets": set(), "titles": set(),
                "authoritative": False, "level": "", "official_sources": set(),
            }
        # A later, more precise location (city or feed coordinates) wins.
        elif (precise if precise is not None else region["precise"]) and not ev["precise"]:
            ev["lat"] = region["lat"] if lat is None else lat
            ev["lon"] = region["lon"] if lon is None else lon
            ev["region"], ev["precise"] = region["name"], True
        return ev

    def add_item(ev, title, source, url, published, official=False):
        norm = re.sub(r"\W+", " ", title.lower()).strip()[:90]
        if norm in ev["titles"]:
            return
        ev["titles"].add(norm)
        ev["items"].append({"title": title, "source": source, "url": url,
                            "published": published.isoformat() if published else "",
                            "official": official})
        if official:
            ev["official_sources"].add(source)
        else:
            ev["outlets"].add(source.lower())

    # Official feeds first, so news merges into them.
    for g in gdacs:
        if g["published"] and now - g["published"] > OFFICIAL_WINDOW:
            continue
        region = find_region(g["title"]) or find_region(g["country"]) or {
            "name": g["country"] or "South Asia", "group": "gdacs-" + g["event_id"],
            "lat": g["lat"], "lon": g["lon"], "precise": True}
        ev = get_event(f"{g['hazard']}|{region['group']}", HAZ_BY_ID[g["hazard"]], region,
                       g["lat"], g["lon"], True)
        ev["authoritative"] = True
        if SEV_RANK.get(_lvl_sev(g["level"]), 0) > SEV_RANK.get(_lvl_sev(ev["level"]), 0):
            ev["level"] = g["level"]
        add_item(ev, g["title"], "GDACS", g["url"], g["published"], official=True)

    for q in usgs:
        region = find_region(q.get("place", "")) or {
            "name": q.get("place") or "South Asia", "group": "usgs-" + q["event_id"],
            "lat": q["lat"], "lon": q["lon"], "precise": True}
        ev = get_event(f"earthquake|{region['group']}", HAZ_BY_ID["earthquake"], region,
                       q["lat"], q["lon"], True)
        ev["authoritative"] = True
        if SEV_RANK.get(_lvl_sev(q["level"]), 0) > SEV_RANK.get(_lvl_sev(ev["level"]), 0):
            ev["level"] = q["level"]
        add_item(ev, q["title"], "USGS", q["url"], q["published"], official=True)

    for a in ndma:
        if a["published"] and now - a["published"] > OFFICIAL_WINDOW:
            continue
        haz, region = detect_hazard(a["text"]), find_region(a["text"])
        if not haz or not region:
            continue
        ev = get_event(f"{haz[0]}|{region['group']}", haz, region)
        ev["authoritative"] = True
        ev["level"] = ev["level"] or "official"
        add_item(ev, a["title"], "NDMA SACHET", a["url"], a["published"], official=True)

    for n in news:
        if not n["published"] or now - n["published"] > NEWS_WINDOW:
            continue
        haz, region = detect_hazard(n["title"]), find_region(n["title"])
        if not haz or not region:
            continue
        ev = get_event(f"{haz[0]}|{region['group']}", haz, region)
        add_item(ev, n["title"], n["source"], n["url"], n["published"])

    return [_finalise(ev) for ev in events.values()]


def _lvl_sev(level: str) -> str:
    return {"red": "high", "orange": "high", "official": "high", "green": "medium"}.get(level or "", "")


def _finalise(ev: dict) -> dict:
    n = len(ev["outlets"])
    if ev["authoritative"]:
        sev = _lvl_sev(ev["level"]) or "medium"
        conf = "Official alert" if sev == "high" else "Official feed"
        if n:
            conf += f" + {n} news report{'s' if n > 1 else ''}"
    elif n >= 3:
        sev, conf = "high", f"Reported by {n} outlets"
    elif n == 2:
        sev, conf = "medium", "Corroborated by 2 outlets"
    else:
        sev, conf = "low", "Single report — unverified"

    items = sorted(ev["items"], key=lambda i: i["published"] or "", reverse=True)
    dates = [i["published"] for i in items if i["published"]]
    return {
        "id": hashlib.sha1(f"{ev['hazard']}|{ev['group']}".encode()).hexdigest()[:12],
        "hazard": ev["hazard"], "hazard_label": ev["hazard_label"], "icon": ev["icon"],
        "region": ev["region"], "group": ev["group"],
        "lat": ev["lat"], "lon": ev["lon"], "precise": ev["precise"],
        "severity": sev, "confidence": conf,
        "source_count": n, "authoritative": ev["authoritative"],
        "official_sources": sorted(ev["official_sources"]),
        "latest": max(dates) if dates else "", "first": min(dates) if dates else "",
        "items": items[:8],
    }


# ----------------------------- entry point --------------------------------
async def get_alerts(force: bool = False) -> dict:
    if not force:
        cached = cache_get(CACHE_KEY)
        if cached is not None:
            return cached

    news_task = fetch_news()
    gdacs_task = get_text(GDACS_RSS)
    usgs_task = get_json(USGS_FEED)
    ndma_task = get_text(NDMA_SACHET_RSS)
    (news, news_ok), gdacs_xml, usgs_json, ndma_xml = await asyncio.gather(
        news_task, gdacs_task, usgs_task, ndma_task)

    gdacs = parse_gdacs(gdacs_xml) if gdacs_xml else []
    usgs = parse_usgs(usgs_json) if usgs_json else []
    ndma = parse_ndma(ndma_xml) if ndma_xml else []

    alerts = build_events(news, gdacs, usgs, ndma)
    alerts.sort(key=lambda a: (SEV_RANK[a["severity"]], a["latest"]), reverse=True)

    status = [
        {"name": "News (Google News RSS)", "ok": news_ok},
        {"name": "GDACS", "ok": gdacs_xml is not None},
        {"name": "USGS earthquakes", "ok": usgs_json is not None},
        {"name": "NDMA SACHET", "ok": ndma_xml is not None},
    ]
    result = {
        "ok": any(s["ok"] for s in status),
        "generated": datetime.now(timezone.utc).isoformat(),
        "alerts": alerts[:30],
        "sources_status": status,
    }
    cache_set(CACHE_KEY, result, ttl=300 if result["ok"] else 60)
    return result
