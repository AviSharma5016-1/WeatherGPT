"""
Live news / disaster-report retrieval — NO hard-coded stories.

Primary sources need no API key:
  - Google News RSS  (general weather/disaster headlines, by query)
  - ReliefWeb API    (UN OCHA humanitarian/disaster reports)
Optional:
  - NewsAPI          (used only if NEWS_API_KEY is set)

Returns a list of {source, title, url, published} dicts. Each item carries its
own provenance so the frontend and the LLM can attribute claims. On failure the
list is simply shorter/empty — never an exception.
"""
from __future__ import annotations

import html
import re
from typing import Optional
from xml.etree import ElementTree as ET

from config import settings
from services.http import get_json, get_text, cache_get, cache_set

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
RELIEFWEB_API = "https://api.reliefweb.int/v1/reports"
NEWSAPI_URL = "https://newsapi.org/v2/everything"


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    return html.unescape(text).strip()


async def _google_news(query: str, limit: int) -> list[dict]:
    xml = await get_text(GOOGLE_NEWS_RSS, params={"q": query, "hl": "en-IN", "gl": "IN", "ceid": "IN:en"})
    if not xml:
        return []
    out: list[dict] = []
    try:
        root = ET.fromstring(xml)
        for item in root.iter("item"):
            title = _clean(item.findtext("title", ""))
            link = (item.findtext("link", "") or "").strip()
            pub = (item.findtext("pubDate", "") or "").strip()
            src_el = item.find("source")
            source = _clean(src_el.text) if src_el is not None and src_el.text else ""
            if source and title.endswith(" - " + source):
                title = title[: -(len(source) + 3)]
            if not source and " - " in title:
                title, source = title.rsplit(" - ", 1)
            source = source or "Google News"
            if title and link:
                out.append({"source": source, "title": title, "url": link, "published": pub})
            if len(out) >= limit:
                break
    except Exception:
        return out
    return out


async def _reliefweb(query: str, limit: int) -> list[dict]:
    payload = {
        "appname": "weathergpt-demo",
        "query": {"value": query, "operator": "AND"},
        "sort": ["date:desc"],
        "limit": limit,
        "fields": {"include": ["title", "url", "date.created", "source.shortname"]},
    }
    # ReliefWeb accepts POST with JSON body; get_json only does GET, so use httpx directly.
    try:
        import httpx
        async with httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT) as client:
            resp = await client.post(RELIEFWEB_API, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return []
    out: list[dict] = []
    for item in (data or {}).get("data", []):
        f = item.get("fields", {})
        src = "ReliefWeb"
        if f.get("source"):
            src = f["source"][0].get("shortname", "ReliefWeb") if isinstance(f["source"], list) else "ReliefWeb"
        out.append({
            "source": src,
            "title": f.get("title", ""),
            "url": f.get("url", ""),
            "published": (f.get("date", {}) or {}).get("created", ""),
        })
    return out


async def _newsapi(query: str, limit: int) -> list[dict]:
    if not settings.newsapi_enabled:
        return []
    data = await get_json(NEWSAPI_URL, params={
        "q": query, "sortBy": "publishedAt", "language": "en", "pageSize": limit,
    }, headers={"X-Api-Key": settings.NEWS_API_KEY})
    if not data:
        return []
    return [{
        "source": (a.get("source") or {}).get("name", "NewsAPI"),
        "title": a.get("title", ""),
        "url": a.get("url", ""),
        "published": a.get("publishedAt", ""),
    } for a in data.get("articles", [])[:limit]]


def _dedupe(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for it in items:
        k = (it.get("title", "")[:80]).lower()
        if k and k not in seen:
            seen.add(k)
            out.append(it)
    return out


async def get_news(query: str, disaster: bool = False, limit: int = 6) -> list[dict]:
    """Fetch recent items for a query. If disaster=True, ReliefWeb is queried
    first (better for flood/cyclone situations)."""
    key = f"news:{disaster}:{query.lower()}"
    cached = cache_get(key)
    if cached is not None:
        return cached

    items: list[dict] = []
    if disaster:
        items += await _reliefweb(query, limit)
    items += await _google_news(query, limit)
    items += await _newsapi(query, limit)

    items = _dedupe(items)[:limit]
    cache_set(key, items, ttl=900)  # 15 min
    return items
