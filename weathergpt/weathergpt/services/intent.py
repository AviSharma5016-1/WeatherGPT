"""
Intent detection and entity extraction.

Turns a free-text query into a small structured object the rest of the app can
act on, without needing the LLM for the common cases (so it works with zero
keys). The LLM, when available, is used for the *answer wording* and
translation — not for this routing — which keeps latency and cost down.

Returned shape:
    {
      "intent": "weather" | "forecast" | "rain" | "clouds" | "wind" |
                "temperature" | "cyclone" | "flood" | "rivers" | "news" | "general",
      "place": "<raw place string or ''>",
      "layer": "<map overlay id or ''>",
      "disaster": bool,
      "lang": "<iso code or ''>",
    }
"""
from __future__ import annotations

import re

# Ordered: earlier patterns win when several match.
INTENT_PATTERNS = [
    ("cyclone",     r"\b(cyclones?|hurricanes?|typhoons?|storm track|landfall)\b"),
    ("flood",       r"\b(floods?|flooding|inundation|deluge|overflow(ing)?|submerged)\b"),
    ("alerts",      r"\b(alerts?|warnings?|emergenc(y|ies)|disasters?|calamit(y|ies))\b"),
    ("rivers",      r"\b(rivers?|waterways?|tributar|basin|drainage)\b"),
    ("forecast",    r"\b(forecast|tomorrow|next (day|week)|coming days|will it (rain|snow)|expected)\b"),
    ("clouds",      r"\b(clouds?|cloud cover|overcast|satellite)\b"),
    ("rain",        r"\b(rain|rainfall|precipitation|radar|showers)\b"),
    ("wind",        r"\b(winds?|gusts?|breeze|wind flow)\b"),
    ("temperature", r"\b(temperature|heatwave|cold wave|how (hot|cold))\b"),
    ("news",        r"\b(news|latest|happening|situation|reports?|updates?)\b"),
    ("weather",     r"\b(weather|climate|conditions|humidity|pressure)\b"),
]

# Which map overlay each intent should switch on.
INTENT_LAYER = {
    "clouds": "clouds", "rain": "radar", "wind": "wind",
    "temperature": "temp", "cyclone": "radar", "flood": "flood",
    "rivers": "rivers", "alerts": "alerts",
}

DISASTER_INTENTS = {"flood", "cyclone"}

# Rough language hints from script blocks, for auto-detect.
SCRIPT_RANGES = [
    ("hi", r"[\u0900-\u097F]"),  # Devanagari (Hindi/Marathi share it; default hi)
    ("bn", r"[\u0980-\u09FF]"),  # Bengali/Assamese
    ("ta", r"[\u0B80-\u0BFF]"),  # Tamil
    ("te", r"[\u0C00-\u0C7F]"),  # Telugu
    ("kn", r"[\u0C80-\u0CFF]"),  # Kannada
    ("ml", r"[\u0D00-\u0D7F]"),  # Malayalam
    ("gu", r"[\u0A80-\u0AFF]"),  # Gujarati
    ("pa", r"[\u0A00-\u0A7F]"),  # Gurmukhi (Punjabi)
    ("or", r"[\u0B00-\u0B7F]"),  # Odia
    ("ur", r"[\u0600-\u06FF]"),  # Arabic script (Urdu)
]

# Words that shouldn't be mistaken for a place after "in"/"near"/"over".
_STOP_AFTER = {"the", "a", "an", "my", "this", "india", "there", "here", "next",
               "coming", "show", "rainfall", "rain", "weather", "cyclone",
               "flood", "floods", "clouds", "wind", "temperature", "news",
               "latest", "what", "where", "alerts", "any"}


def detect_lang(text: str) -> str:
    for code, pattern in SCRIPT_RANGES:
        if re.search(pattern, text):
            return code
    return "en"


def extract_place(text: str) -> str:
    """Pull the most likely place phrase out of the query.
    Prefers text after a spatial preposition; falls back to a capitalised
    token. Deliberately simple — the geocoder validates it downstream, and
    the LLM path can override with better entity extraction when enabled."""
    t = text.strip()

    # "... in/over/near/around/for <Place[, Region]>" — includes a comma so
    # "shimoga, karnataka" survives as one phrase instead of losing everything
    # after the comma.
    m = re.search(r"\b(?:in|over|near|around|for|at|of)\s+([A-Za-z][A-Za-z,\s]{1,40})", t, re.I)
    if m:
        cand = m.group(1).strip().rstrip(",.!?")
        cand = re.split(r"\b(today|tomorrow|now|please|right now)\b", cand, flags=re.I)[0].strip().rstrip(",.!?")
        first = cand.split(",")[0].strip().split()[0].lower() if cand.split() else ""
        if cand and first not in _STOP_AFTER:
            return cand

    # Otherwise, capitalised word(s) that aren't the first word.
    caps = re.findall(r"\b([A-Z][a-z]{2,}(?:,\s*[A-Z][a-z]{2,})?)\b", t)
    for c in caps:
        if c.split(",")[0].strip().lower() not in _STOP_AFTER:
            return c
    return ""


def classify(text: str) -> dict:
    lower = text.lower()
    intent = "general"
    for name, pattern in INTENT_PATTERNS:
        if re.search(pattern, lower):
            intent = name
            break
    place = extract_place(text)
    return {
        "intent": intent,
        "place": place,
        "river_query": text if intent == "rivers" else "",
        "layer": INTENT_LAYER.get(intent, ""),
        "disaster": intent in DISASTER_INTENTS,
        "lang": detect_lang(text),
    }
