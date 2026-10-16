"""Weather bot answers: each function fetches one free data source (no API key needed) and returns one line of text.
Sources: NOAA (api.weather.gov, US only), Open-Meteo (weather, air quality, rain nowcast, solar radiation), NOAA SWPC (space weather,
aurora), hamqsl.com (HF conditions).  The moon is computed here.  ' | ' marks where a long answer may be split into two messages."""
import datetime as dt
import math
import re
import xml.etree.ElementTree as ET

from meshbot_common import compass, http_get, http_json

WMO = {0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "cloudy", 45: "fog", 48: "fog", 51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
       56: "freezing drizzle", 57: "freezing drizzle", 61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
       71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains", 80: "showers", 81: "showers", 82: "heavy showers", 85: "snow showers",
       86: "snow showers", 95: "thunderstorm", 96: "thunderstorm, hail", 99: "thunderstorm, hail"}


def _units(units):
    return ({"temperature_unit": "fahrenheit", "wind_speed_unit": "mph", "precipitation_unit": "inch"}, "F", "mph") if units == "imperial" else ({}, "C", "km/h")


def _day(iso, i):
    return "Today" if i == 0 else dt.date.fromisoformat(iso).strftime("%a")


# ---- wx: NOAA (US) ------------------------------------------------------------------------------------------------------------------
def wx(lat, lon, label, get=http_json):
    try: pt = get(f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}")
    except Exception as e:
        if "404" in str(e): raise ValueError("NOAA covers the US only - try: gwx <place>")
        raise
    periods = get(pt["properties"]["forecast"])["properties"]["periods"][:3]
    bits = [f"{p['name']} {p['temperature']}{p['temperatureUnit']} {p['shortForecast']}, wind {p['windDirection']} {p['windSpeed']}" for p in periods]
    return f"{label}: " + " | ".join(bits)


# ---- gwx: Open-Meteo (anywhere) -----------------------------------------------------------------------------------------------------
def gwx(lat, lon, label, units="metric", get=http_json):
    extra, tu, wu = _units(units)
    d = get("https://api.open-meteo.com/v1/forecast", dict({"latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 3,
            "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m,wind_direction_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"}, **extra))
    c, dd = d["current"], d["daily"]
    now = (f"{label}: {round(c['temperature_2m'])}{tu} {WMO.get(c['weather_code'], '?')}, wind {round(c['wind_speed_10m'])} {wu} "
           f"{compass(c['wind_direction_10m'])}, {c['relative_humidity_2m']}% RH")
    days = [f"{_day(dd['time'][i], i)} {round(dd['temperature_2m_max'][i])}/{round(dd['temperature_2m_min'][i])}{tu} {WMO.get(dd['weather_code'][i], '?')}"
            + (f" {dd['precipitation_probability_max'][i]}%rain" if dd["precipitation_probability_max"][i] else "") for i in range(min(3, len(dd["time"])))]
    return now + " | " + ", ".join(days)


# ---- aqi -----------------------------------------------------------------------------------------------------------------------------
AQI_WORDS = ((50, "good"), (100, "moderate"), (150, "unhealthy for sensitive"), (200, "unhealthy"), (300, "very unhealthy"), (9999, "hazardous"))
def aqi(lat, lon, label, get=http_json):
    c = get("https://air-quality-api.open-meteo.com/v1/air-quality", {"latitude": lat, "longitude": lon, "current": "us_aqi,pm2_5,pm10,ozone"})["current"]
    v = c.get("us_aqi")
    if v is None: raise ValueError("no air quality data for that place")
    word = next(w for top, w in AQI_WORDS if v <= top)
    return f"AQI {label}: {round(v)} ({word}), PM2.5 {c['pm2_5']:.0f}, PM10 {c['pm10']:.0f}, ozone {c['ozone']:.0f} ug/m3"


# ---- sun / moon ----------------------------------------------------------------------------------------------------------------------
def sun(lat, lon, label, get=http_json):
    d = get("https://api.open-meteo.com/v1/forecast", {"latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 2,
                                                       "daily": "sunrise,sunset,daylight_duration"})["daily"]
    hm = lambda s: s[11:16]
    secs = int(d["daylight_duration"][0])
    change = int(d["daylight_duration"][1]) - secs
    return (f"Sun {label}: rise {hm(d['sunrise'][0])}, set {hm(d['sunset'][0])}, {secs // 3600}h{secs % 3600 // 60:02d}m of daylight "
            f"({'+' if change >= 0 else '-'}{abs(change) // 60}m{abs(change) % 60:02d}s tomorrow)")


SYNODIC = 29.530588853
NEW_MOON = dt.datetime(2000, 1, 6, 18, 14, tzinfo=dt.timezone.utc)
PHASES = ("New moon", "Waxing crescent", "First quarter", "Waxing gibbous", "Full moon", "Waning gibbous", "Last quarter", "Waning crescent")
def moon(now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    age = ((now - NEW_MOON).total_seconds() / 86400) % SYNODIC
    lit = (1 - math.cos(2 * math.pi * age / SYNODIC)) / 2
    name = PHASES[int(age / SYNODIC * 8 + 0.5) % 8]
    to_full = (SYNODIC / 2 - age) % SYNODIC
    to_new = SYNODIC - age
    nxt = ("full", to_full) if to_full < to_new else ("new", to_new)
    when = (now + dt.timedelta(days=nxt[1])).astimezone().strftime("%b %d")
    return f"Moon: {name}, {lit * 100:.0f}% lit, {age:.1f} days old. Next {nxt[0]} moon {when}"


# ---- space weather -------------------------------------------------------------------------------------------------------------------
SWPC = "https://services.swpc.noaa.gov"
def _kp_now(get):
    rows = get(f"{SWPC}/products/noaa-planetary-k-index.json")
    last = rows[-1]
    return float(last["Kp"] if isinstance(last, dict) else last[1])


def _kp_word(kp): return "quiet" if kp < 4 else "active" if kp < 5 else f"storm G{min(5, int(kp) - 4)}"


def _xray_class(flux):
    for letter, base in (("X", 1e-4), ("M", 1e-5), ("C", 1e-6), ("B", 1e-7), ("A", 1e-8)):
        if flux >= base: return f"{letter}{flux / base:.1f}"
    return "A0.0"


def solar(get=http_json):
    kp = _kp_now(get)
    last = lambda d: d[-1] if isinstance(d, list) else d           # (these summaries come as one object or as a list of them)
    sfi = last(get(f"{SWPC}/products/summary/10cm-flux.json")).get("flux", "?")
    try: speed = float(last(get(f"{SWPC}/products/summary/solar-wind-speed.json")).get("proton_speed"))
    except (TypeError, ValueError): speed = None
    xr = [r for r in get(f"{SWPC}/json/goes/primary/xrays-6-hour.json") if r.get("energy") == "0.1-0.8nm" and r.get("flux")]
    xray = _xray_class(xr[-1]["flux"]) if xr else "?"
    return f"Space wx: SFI {float(sfi):.0f}, Kp {kp:.1f} ({_kp_word(kp)}), solar wind {speed:.0f} km/s, X-ray {xray}" if speed else \
           f"Space wx: SFI {float(sfi):.0f}, Kp {kp:.1f} ({_kp_word(kp)}), X-ray {xray}"


def aurora(lat, lon, label, get=http_json):
    kp = _kp_now(get)
    fc = get(f"{SWPC}/products/noaa-planetary-k-index-forecast.json")
    now = dt.datetime.now(dt.timezone.utc)
    future = []
    for r in fc:
        if isinstance(r, dict): t, v = r.get("time_tag"), r.get("kp")
        elif r and r[0] != "time_tag": t, v = r[0], r[1]
        else: continue
        try:
            when = dt.datetime.fromisoformat(str(t).replace(" ", "T").replace("Z", "")).replace(tzinfo=dt.timezone.utc)
            if now <= when <= now + dt.timedelta(hours=24): future.append(float(v))
        except (TypeError, ValueError):
            continue
    ov = get(f"{SWPC}/json/ovation_aurora_latest.json")
    glon, glat = round(lon) % 360, round(lat)
    prob = next((p for x, y, p in ov.get("coordinates", []) if x == glon and y == glat), 0)
    peak = max(future) if future else kp
    return f"Aurora {label}: Kp {kp:.1f} now, up to {peak:.1f} next 24h ({_kp_word(peak)}). Chance overhead now {prob}%"


# ---- HF propagation --------------------------------------------------------------------------------------------------------------------
def hfcond(get=http_get):
    root = ET.fromstring(get("https://www.hamqsl.com/solarxml.php"))
    sd = root.find("solardata")
    bands = {}
    for b in sd.iter("band"):
        bands.setdefault(b.get("time"), []).append(f"{b.get('name').replace('m', '')} {b.text}")
    head = f"HF: SFI {sd.findtext('solarflux', '?').strip()}, K {sd.findtext('kindex', '?').strip()}"
    return head + " | day " + ", ".join(bands.get("day", [])) + " | night " + ", ".join(bands.get("night", []))


# ---- solar panel forecast --------------------------------------------------------------------------------------------------------------
def solar_forecast(lat, lon, label, get=http_json):
    d = get("https://api.open-meteo.com/v1/forecast", {"latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 3,
                                                       "daily": "shortwave_radiation_sum"})["daily"]
    days = [f"{_day(t, i)} {mj / 3.6 * 0.8:.1f}" for i, (t, mj) in enumerate(zip(d["time"], d["shortwave_radiation_sum"])) if mj is not None]
    return f"Solar {label}, kWh per kW of panels: " + ", ".join(days)


# ---- rain nowcast ----------------------------------------------------------------------------------------------------------------------
def rain_steps(lat, lon, units="metric", get=http_json):
    """Next 2 hours in 15-minute steps: [(HH:MM, amount)]."""
    extra, _, _ = _units(units)
    d = get("https://api.open-meteo.com/v1/forecast", dict({"latitude": lat, "longitude": lon, "timezone": "auto", "minutely_15": "precipitation",
                                                            "forecast_minutely_15": 8}, **extra))
    m = d["minutely_15"]
    return [(t[11:16], p or 0.0) for t, p in zip(m["time"], m["precipitation"])]


def rain(lat, lon, label, units="metric", get=http_json):
    steps = rain_steps(lat, lon, units, get)
    unit = "in" if units == "imperial" else "mm"
    wet = [(t, p) for t, p in steps if p >= (0.01 if units == "imperial" else 0.1)]
    if not wet: return f"Rain {label}: dry for the next 2 hours"
    peak = max(p for _, p in wet)
    start = wet[0][0]
    if steps and steps[0][1] >= (0.01 if units == "imperial" else 0.1):
        dry = next((t for t, p in steps if p < (0.01 if units == "imperial" else 0.1)), None)
        return f"Rain {label}: raining now, up to {peak:.1f} {unit}/15min" + (f", easing by {dry}" if dry else ", for the next 2 hours")
    return f"Rain {label}: rain from about {start}, up to {peak:.1f} {unit}/15min"
