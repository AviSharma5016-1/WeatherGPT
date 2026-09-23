"""
LLM provider abstraction.

Two implementations behind one interface:
  - GeminiProvider: calls Google's Generative Language API (needs GEMINI_API_KEY)
  - FallbackProvider: no key needed; deterministically turns the retrieved
    weather/news/geo context into a readable English answer via templates.

The app calls get_provider() and never imports a vendor SDK directly, so
swapping to OpenAI/Anthropic later means adding one class, not a rewrite.

The prompt is grounded strictly in the retrieved `context` dict, and the
system instruction forbids inventing facts — the model synthesises, it does
not source. Translation is a thin wrapper over the same generate() call.
"""
from __future__ import annotations

import json
from typing import Optional

from config import settings
from services.http import get_json

LANG_NAMES = {
    "en": "English", "hi": "Hindi", "mr": "Marathi", "bn": "Bengali",
    "gu": "Gujarati", "ta": "Tamil", "te": "Telugu", "kn": "Kannada",
    "ml": "Malayalam", "pa": "Punjabi", "or": "Odia", "as": "Assamese",
    "ur": "Urdu",
}

SYSTEM_INSTRUCTION = (
    "You are WeatherGPT, a weather, climate and disaster-intelligence assistant "
    "for India built for the Ministry of Earth Sciences / IMD. Answer ONLY from "
    "the DATA provided in the user message. Never invent numbers, place names, "
    "flood extents, cyclone tracks or news. If the data is insufficient, say so "
    "plainly and state what is uncertain. Be concise, natural and specific. When "
    "news items are provided, attribute claims to their source. Reply in the "
    "requested language."
)


class LLMProvider:
    name = "base"

    async def generate(self, prompt: str, lang: str = "en") -> str:
        raise NotImplementedError

    async def translate(self, text: str, lang: str) -> str:
        if lang == "en" or not text:
            return text
        return await self.generate(
            f"Translate the following text into {LANG_NAMES.get(lang, lang)}. "
            f"Return only the translation, no notes:\n\n{text}", lang=lang)


class GeminiProvider(LLMProvider):
    name = "gemini"

    async def generate(self, prompt: str, lang: str = "en") -> str:
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{settings.GEMINI_MODEL}:generateContent")
        body = {
            "systemInstruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.4, "maxOutputTokens": 700},
        }
        data = await get_json_post(url, body, params={"key": settings.GEMINI_API_KEY})
        if not data:
            return ""  # caller falls back
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception:
            return ""


class FallbackProvider(LLMProvider):
    """No-LLM path: build a readable English answer from the context dict.
    Honest about being a template, and about not translating."""
    name = "fallback"

    async def generate(self, prompt: str, lang: str = "en") -> str:
        # The fallback can't reason over a free prompt; app.py calls
        # synthesize() directly for it. This exists so translate() degrades
        # gracefully (returns source text) when no LLM is configured.
        return prompt

    async def translate(self, text: str, lang: str) -> str:
        return text  # cannot translate without an LLM; return English as-is


async def get_json_post(url: str, body: dict, params: Optional[dict] = None) -> Optional[dict]:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT) as client:
            resp = await client.post(url, json=body, params=params)
            resp.raise_for_status()
            return resp.json()
    except Exception:
        return None


def get_provider() -> LLMProvider:
    if settings.llm_enabled:
        return GeminiProvider()
    return FallbackProvider()


# --- Deterministic template synthesis (used by the fallback path) ----------
def synthesize(context: dict) -> str:
    """Produce a natural-ish English answer from retrieved data, no LLM."""
    intent = context.get("intent", "general")
    place = context.get("place_name") or "the selected area"
    wx = context.get("weather") or {}
    news = context.get("news") or []
    rivers = context.get("rivers") or {}

    parts: list[str] = []

    if context.get("geocode_failed"):
        parts.append(f"I couldn't pinpoint \"{context.get('requested_place')}\" on the map, "
                     f"so this is showing India overall instead.")

    if wx.get("ok"):
        c = wx["current"]
        bits = [f"{place} is currently {c['temp_c']}°C"]
        if c.get("feels_like_c") is not None:
            bits.append(f"(feels like {c['feels_like_c']}°C)")
        bits.append(f"with {c['condition'].lower()}")
        seg = " ".join(bits) + "."
        extra = []
        if c.get("humidity") is not None:
            extra.append(f"humidity {c['humidity']}%")
        if c.get("wind_kph") is not None:
            extra.append(f"wind {c['wind_kph']} km/h {c.get('wind_dir','')}".strip())
        if c.get("precip_mm"):
            extra.append(f"{c['precip_mm']} mm recent precipitation")
        if extra:
            seg += " " + ", ".join(extra).capitalize() + "."
        parts.append(seg)

        if intent in ("forecast", "rain") and wx.get("daily"):
            d = wx["daily"][1] if len(wx["daily"]) > 1 else wx["daily"][0]
            parts.append(
                f"For {d['date']}, expect {d['condition'].lower()}, "
                f"{d['temp_min_c']}–{d['temp_max_c']}°C, with a "
                f"{d.get('precip_prob','?')}% chance of precipitation.")
    elif intent in ("weather", "forecast", "rain", "temperature", "wind", "clouds"):
        parts.append(f"I couldn't retrieve live weather for {place} right now.")

    if intent == "rivers":
        if rivers.get("named"):
            parts.append(f"Highlighting the {rivers['named']} on the map. "
                         f"{rivers.get('info','')}".strip())
        elif rivers.get("reachable") and rivers.get("features"):
            names = rivers.get("names") or []
            label = ", ".join(names) if names else f"{len(rivers['features'])} river(s)"
            parts.append(f"Showing {label} around {place}. Tap a river on the map "
                         f"for its name.")
        else:
            parts.append(f"I don't have {place} in the river atlas yet. Try a major "
                         f"river by name — e.g. Ganga, Brahmaputra, Godavari, Krishna, "
                         f"Narmada, Kaveri, Mahanadi.")

    if intent == "alerts":
        al = context.get("alerts") or []
        if al:
            parts.append(f"{len(al)} active event(s) detected in live feeds:")
            for a in al:
                parts.append(f"• {a['hazard']} — {a['region']} ({a['confidence']})")
            parts.append("Tap a red pin on the map or open the 🔔 panel for the sources.")
        elif not context.get("alerts_feeds_ok", True):
            parts.append("I couldn't reach the live disaster feeds just now, so I can't confirm "
                         "whether anything is happening. Please check IMD (mausam.imd.gov.in) or "
                         "NDMA directly, and try again in a few minutes.")
        else:
            parts.append("No weather or disaster events detected in live feeds over the last 48 hours.")

    if intent in ("flood", "cyclone", "news"):
        if news:
            parts.append(f"Latest reports on {place}:")
            for n in news[:3]:
                when = (n.get("published", "") or "")[:16]
                parts.append(f"• {n['title']} — {n['source']} {when}".rstrip())
            if intent == "flood":
                parts.append("Note: these are reported affected areas from news/"
                             "humanitarian sources, not a verified satellite flood boundary.")
        else:
            parts.append(f"I couldn't find recent reports on {place} right now.")

    if not parts:
        parts.append("Ask me about weather, rain, wind, cyclones, floods, rivers "
                     "or the latest situation anywhere in India — for example, "
                     "\"weather in Pune\" or \"floods in Assam\".")

    return "\n".join(parts)
