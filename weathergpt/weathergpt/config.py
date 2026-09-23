"""
Central configuration for WeatherGPT.

Every secret and tunable is read from the environment (a local .env is loaded
automatically if python-dotenv is installed). Nothing sensitive is hard-coded.

The app is designed to START AND RUN WITH ZERO KEYS:
  - weather + geocoding use Open-Meteo, which needs no key
  - news uses public RSS/ReliefWeb, which need no key
  - the map falls back to keyless OpenStreetMap tiles
  - the LLM falls back to a built-in template synthesizer
Keys unlock better answers (Gemini), Google Maps as the base map, extra
weather tile layers (OpenWeatherMap) and a higher news quota (NewsAPI).
"""
from __future__ import annotations

import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    # dotenv is optional; real environment variables still work without it.
    pass


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


class Settings:
    # --- LLM ---------------------------------------------------------------
    LLM_PROVIDER: str = _get("LLM_PROVIDER", "gemini").lower()  # gemini | none
    GEMINI_API_KEY: str = _get("GEMINI_API_KEY")
    GEMINI_MODEL: str = _get("GEMINI_MODEL", "gemini-1.5-flash")

    # --- Maps (browser key, injected at runtime; restrict by domain in GCP) -
    GOOGLE_MAPS_API_KEY: str = _get("GOOGLE_MAPS_API_KEY")

    # --- Optional weather tile layers --------------------------------------
    OPENWEATHER_API_KEY: str = _get("OPENWEATHER_API_KEY")

    # --- Optional news provider (RSS is used when this is absent) -----------
    NEWS_API_KEY: str = _get("NEWS_API_KEY")

    # --- Server ------------------------------------------------------------
    HOST: str = _get("HOST", "0.0.0.0")
    PORT: int = int(_get("PORT", "8000") or "8000")
    # Comma-separated list of allowed CORS origins; "*" in dev.
    CORS_ORIGINS: list[str] = [
        o.strip() for o in _get("CORS_ORIGINS", "*").split(",") if o.strip()
    ]

    # --- Behaviour ---------------------------------------------------------
    REQUEST_TIMEOUT: float = float(_get("REQUEST_TIMEOUT", "8") or "8")
    CACHE_TTL_SECONDS: int = int(_get("CACHE_TTL_SECONDS", "600") or "600")

    # --- Derived flags (never contain the secret itself) -------------------
    @property
    def llm_enabled(self) -> bool:
        return self.LLM_PROVIDER == "gemini" and bool(self.GEMINI_API_KEY)

    @property
    def google_maps_enabled(self) -> bool:
        return bool(self.GOOGLE_MAPS_API_KEY)

    @property
    def openweather_enabled(self) -> bool:
        return bool(self.OPENWEATHER_API_KEY)

    @property
    def newsapi_enabled(self) -> bool:
        return bool(self.NEWS_API_KEY)

    def public_capabilities(self) -> dict:
        """Safe to send to the browser — booleans only, no secrets.
        Includes the Google Maps *browser* key, which is meant to be public
        but should be domain-restricted in the Google Cloud console."""
        return {
            "llm": self.llm_enabled,
            "llm_provider": self.LLM_PROVIDER if self.llm_enabled else "fallback",
            "google_maps": self.google_maps_enabled,
            "google_maps_key": self.GOOGLE_MAPS_API_KEY,  # browser key, restrict by domain
            "openweather": self.openweather_enabled,
            "openweather_key": self.OPENWEATHER_API_KEY,  # tile key, low-risk, restrict usage
            "newsapi": self.newsapi_enabled,
        }


settings = Settings()
