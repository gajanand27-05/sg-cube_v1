"""Weather tools (Phase 11d) — Open-Meteo (free, no API key).

- Default location is inferred from the user's IP once per process and cached.
- Geocoding (city name → coords) via Open-Meteo's free endpoint.
- Forecast is current weather + next-N-day daily summary.
"""
import httpx

from backend.core.tools.registry import tool

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
IP_URL = "https://ipapi.co/json/"

# Open-Meteo / WMO weather codes — abbreviated to the common cases.
WMO_CODES = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "freezing fog",
    51: "light drizzle",
    53: "drizzle",
    55: "heavy drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    77: "snow grains",
    80: "rain showers",
    81: "heavy rain showers",
    82: "violent rain showers",
    85: "snow showers",
    86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with hail",
    99: "severe thunderstorm with hail",
}

_default_location: str | None = None


def _get_default_location() -> str:
    global _default_location
    if _default_location is not None:
        return _default_location
    try:
        with httpx.Client(timeout=6.0) as c:
            r = c.get(IP_URL)
            if r.status_code == 200:
                j = r.json()
                city = j.get("city") or ""
                country = j.get("country_name") or j.get("country") or ""
                if city:
                    _default_location = f"{city}, {country}".strip(", ")
                    return _default_location
    except Exception:
        pass
    _default_location = "Mumbai, India"
    return _default_location


def _geocode(name: str) -> dict | None:
    """City name -> {latitude, longitude, name, country}."""
    try:
        with httpx.Client(timeout=10.0) as c:
            r = c.get(GEOCODE_URL, params={"name": name, "count": 1})
        if r.status_code != 200:
            return None
        results = r.json().get("results") or []
        return results[0] if results else None
    except Exception:
        return None


def _describe(code: int) -> str:
    return WMO_CODES.get(int(code), "unknown")


_LOCATION_DEFAULT_ALIASES = {"", "current", "current location", "my location", "here", "now", "default"}


@tool
def get_weather(location: str = "") -> dict:
    """Get current weather for `location` (a city name). If `location` is
    empty, omitted, or "current"/"here", infers from your IP. Returns
    temperature in °C and a description."""
    if location.strip().lower() in _LOCATION_DEFAULT_ALIASES:
        location = _get_default_location()
    return _fetch_current(location)


def _fetch_current(location: str) -> dict:
    geo = _geocode(location)
    if not geo:
        return {"status": "blocked", "reason": f"could not find location {location!r}"}

    try:
        with httpx.Client(timeout=10.0) as c:
            r = c.get(
                FORECAST_URL,
                params={
                    "latitude": geo["latitude"],
                    "longitude": geo["longitude"],
                    "current_weather": "true",
                },
            )
    except Exception as e:
        return {"status": "error", "reason": f"weather API error: {e}"}

    if r.status_code != 200:
        return {"status": "error", "reason": f"weather API returned {r.status_code}"}

    cw = r.json().get("current_weather", {})
    temp = cw.get("temperature")
    code = cw.get("weathercode", -1)
    desc = _describe(code)
    place = geo.get("name", location)
    country = geo.get("country", "")
    label = f"{place}, {country}".strip(", ")

    msg = f"{label}: {desc}, {temp:.0f}°C" if temp is not None else f"{label}: {desc}"
    return {
        "status": "success",
        "message": msg,
        "args": {
            "location": label,
            "temperature_c": temp,
            "description": desc,
            "weathercode": code,
        },
    }


@tool
def get_weather_forecast(location: str = "", days: int = 3) -> dict:
    """Get a daily forecast for the next `days` days (default 3, max 7).
    `location` is a city name; empty defaults to your IP-detected location."""
    days = max(1, min(7, int(days)))
    if not location.strip():
        location = _get_default_location()

    geo = _geocode(location)
    if not geo:
        return {"status": "blocked", "reason": f"could not find location {location!r}"}

    try:
        with httpx.Client(timeout=10.0) as c:
            r = c.get(
                FORECAST_URL,
                params={
                    "latitude": geo["latitude"],
                    "longitude": geo["longitude"],
                    "daily": "weathercode,temperature_2m_max,temperature_2m_min",
                    "forecast_days": days,
                    "timezone": "auto",
                },
            )
    except Exception as e:
        return {"status": "error", "reason": f"weather API error: {e}"}
    if r.status_code != 200:
        return {"status": "error", "reason": f"weather API returned {r.status_code}"}

    d = r.json().get("daily") or {}
    dates = d.get("time") or []
    codes = d.get("weathercode") or []
    highs = d.get("temperature_2m_max") or []
    lows = d.get("temperature_2m_min") or []

    rows = []
    for i in range(min(len(dates), days)):
        rows.append(
            {
                "date": dates[i],
                "description": _describe(codes[i]) if i < len(codes) else "",
                "high_c": highs[i] if i < len(highs) else None,
                "low_c": lows[i] if i < len(lows) else None,
            }
        )

    summary = "; ".join(
        f"{r['date']}: {r['description']}, {r['high_c']:.0f}/{r['low_c']:.0f}°C"
        for r in rows
        if r["high_c"] is not None
    )
    place = geo.get("name", location)
    return {
        "status": "success",
        "message": f"{place} {days}-day forecast — {summary}",
        "args": {"location": place, "days": rows},
    }
