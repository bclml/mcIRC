"""Area alerts: the sources.  Each answers 'what is in force around this place now?' as a list of Alert(id, kind, text, source):
id is stable (the same alert is not sent twice), text is ready for the mesh (short, no links).

  disasters  GDACS (UN / EU Joint Research Centre): earthquakes, tropical cyclones, floods, volcanoes, droughts, wildfires - worldwide
  quakes     USGS earthquakes - worldwide
  tsunami    NOAA tsunami warning centres (US NTWC, Pacific PTWC) - their bulletins that name the area's country or region
  weather    official weather warnings: Environment Canada, the US National Weather Service, MeteoAlarm (38 European countries)

All are free and need no key."""
import math
import re
import time
import unicodedata
from collections import namedtuple

import requests

Alert = namedtuple("Alert", "id kind text source")
UA = {"User-Agent": "mcIRC area alerts (github.com/bclml/mcIRC)"}
GDACS_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
USGS_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
NWS_URL = "https://api.weather.gov/alerts/active"
METEOALARM_URL = "https://feeds.meteoalarm.org/api/v1/warnings/feeds-{country}"
TSUNAMI_FEEDS = ("https://www.tsunami.gov/events/xml/PAAQAtom.xml", "https://www.tsunami.gov/events/xml/PHEBAtom.xml")
# MeteoAlarm's feed names for the countries it covers (ISO code -> feed)
METEOALARM = {"AT": "austria", "BE": "belgium", "BA": "bosnia-herzegovina", "BG": "bulgaria", "HR": "croatia", "CY": "cyprus", "CZ": "czechia",
              "DK": "denmark", "EE": "estonia", "FI": "finland", "FR": "france", "DE": "germany", "GR": "greece", "HU": "hungary", "IS": "iceland",
              "IE": "ireland", "IL": "israel", "IT": "italy", "LV": "latvia", "LT": "lithuania", "LU": "luxembourg", "MT": "malta", "MD": "moldova",
              "ME": "montenegro", "NL": "netherlands", "MK": "republic-of-north-macedonia", "NO": "norway", "PL": "poland", "PT": "portugal",
              "RO": "romania", "RS": "serbia", "SK": "slovakia", "SI": "slovenia", "ES": "spain", "SE": "sweden", "CH": "switzerland", "UA": "ukraine",
              "GB": "united-kingdom"}
GDACS_KINDS = {"EQ": "earthquake", "TC": "tropical cyclone", "FL": "flood", "VO": "volcano", "DR": "drought", "WF": "wildfire"}
GDACS_RADIUS_KM = {"EQ": 400, "TC": 600, "FL": 250, "VO": 150, "WF": 80, "DR": 400}       # how near an event must be to concern the area
LEVELS = ["green", "orange", "red"]


def km(lat1, lon1, lat2, lon2):
    """Distance in km between two points."""
    p = math.pi / 180
    a = 0.5 - math.cos((lat2 - lat1) * p) / 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos((lon2 - lon1) * p)) / 2
    return 12742 * math.asin(math.sqrt(a))


def _get(url, params=None, timeout=20, json=True):
    r = requests.get(url, params=params, timeout=timeout, headers=UA)
    r.raise_for_status()
    return r.json() if json else r.text


def short(text, n=110):
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= n else text[:n - 1].rstrip() + "..."


# ---- natural disasters ----
def gdacs(area, min_level="orange", get=None):
    """GDACS events near the area at or above min_level (green / orange / red)."""
    data = (get or _get)(GDACS_URL, {"alertlevel": ";".join(l.capitalize() for l in LEVELS[LEVELS.index(min_level):]),
                                      "eventlist": ";".join(GDACS_KINDS), "limit": 100})
    out = []
    for f in data.get("features", []):
        p = f.get("properties", {})
        kind = p.get("eventtype", "")
        if kind not in GDACS_KINDS or (p.get("alertlevel") or "").lower() not in LEVELS[LEVELS.index(min_level):]: continue
        lon, lat = (f.get("geometry", {}).get("coordinates") or [None, None])[:2]
        if lat is None: continue
        d = km(area["lat"], area["lon"], lat, lon)
        if d > GDACS_RADIUS_KM[kind]: continue
        name = p.get("name") or GDACS_KINDS[kind]
        text = short(f"{p.get('alertlevel', '').upper()} {GDACS_KINDS[kind]} alert: {name}, {int(d)} km from {area['name']}")
        out.append(Alert(f"gdacs:{kind}:{p.get('eventid')}:{p.get('alertlevel')}", "disasters", text, "GDACS"))
    return out


def usgs(area, min_mag=5.0, radius_km=300, hours=24, get=None, now=None):
    """Earthquakes of min_mag or more within radius_km of the area in the last `hours`."""
    since = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime((now or time.time()) - hours * 3600))
    data = (get or _get)(USGS_URL, {"format": "geojson", "latitude": area["lat"], "longitude": area["lon"], "maxradiuskm": radius_km,
                                     "minmagnitude": min_mag, "starttime": since, "orderby": "time"})
    out = []
    for f in data.get("features", []):
        p = f.get("properties", {})
        lon, lat = f.get("geometry", {}).get("coordinates", [0, 0])[:2]
        d = int(km(area["lat"], area["lon"], lat, lon))
        out.append(Alert(f"usgs:{f.get('id')}", "quakes", short(f"Earthquake M{p.get('mag', 0):.1f}: {p.get('place', '')} ({d} km from {area['name']})"), "USGS"))
    return out


def tsunami(area, get=None):
    """Tsunami warnings / advisories / watches whose bulletin names the area's country or region."""
    out, names = [], {n.lower() for n in (area.get("country_name"), area.get("region")) if n}
    for url in TSUNAMI_FEEDS:
        try: xml = (get or _get)(url, json=False)
        except Exception: continue
        for entry in re.findall(r"<entry\b.*?</entry>", xml, re.S):
            title = re.sub(r"<[^>]+>", "", (re.search(r"<title[^>]*>(.*?)</title>", entry, re.S) or [None, ""])[1]).strip()
            body = re.sub(r"<[^>]+>", " ", entry).lower()
            if not re.search(r"\b(warning|advisory|watch|threat)\b", title.lower()) or "no tsunami" in body[:400]: continue
            if not any(n in body for n in names): continue
            eid = (re.search(r"<id>(.*?)</id>", entry) or [None, title])[1]
            out.append(Alert(f"tsunami:{eid}", "tsunami", short(f"TSUNAMI: {title}"), "NOAA"))
    return out


# ---- weather warnings ----
def weather(area, get=None):
    """Official weather warnings for the area, from its country's service (Canada, US, MeteoAlarm Europe); [] elsewhere."""
    cc = area.get("country")
    if cc == "CA": return _canada(area)
    if cc == "US": return _nws(area, get)
    if cc in METEOALARM: return _meteoalarm(area, get)
    return []


def _canada(area):
    import ec_areas                     # Environment Canada (shared with the Traffic and weather addon)
    return [Alert(f"ec:{area['name']}:{k}", "weather", short(f"{k} - {area['name']} (Environment Canada)"), "Environment Canada")
            for k in sorted(ec_areas.alerts_near(area["lat"], area["lon"]))]


def _nws(area, get=None):
    data = (get or _get)(NWS_URL, {"point": f"{area['lat']:.4f},{area['lon']:.4f}"})
    out = []
    for f in data.get("features", []):
        p = f.get("properties", {})
        out.append(Alert(f"nws:{p.get('id')}", "weather", short(f"{p.get('event', 'Weather alert')} - {area['name']} ({p.get('severity', '')}, NWS)"), "NWS"))
    return out


# words that only say what kind of district it is ('Kreis Biberach', 'Regierungsbezirk Stuttgart', 'Province of Rome')
_GENERIC = {"kreis", "landkreis", "stadtkreis", "stadt", "regierungsbezirk", "region", "province", "provincia", "of", "di", "de", "du", "la",
            "le", "county", "district", "municipality", "kommune", "city", "and", "und", "metropolitan", "departement", "okres", "powiat"}


def _plain(text):
    """Lower case, no accents, words only: 'Rhône' -> 'rhone'."""
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _core(name):
    words = [w for w in _plain(name).split() if w not in _GENERIC]
    return " ".join(words) if words and len(" ".join(words)) > 2 else ""


def _names_match(wanted, desc):
    """A wanted name (town, district, region) appears as whole words in MeteoAlarm's area description."""
    d = f" {_plain(desc)} "
    return any(w and f" {w} " in d for w in wanted)


def _meteoalarm(area, get=None):
    """MeteoAlarm areas carry names only (no shapes): matched on the area's town, district and region names, accents ignored.
    'Green' (no warning) entries are skipped."""
    data = (get or _get)(METEOALARM_URL.format(country=METEOALARM[area["country"]]), timeout=40)
    wanted = {_core(n) for n in (area["name"], area.get("district", ""), area.get("region", ""))} - {""}
    out = []
    for w in data.get("warnings", []):
        a = w.get("alert", {})
        infos = a.get("info", [])
        info = next((i for i in infos if (i.get("language") or "").lower().startswith("en")), infos[0] if infos else {})
        if not any(_names_match(wanted, ar.get("areaDesc", "")) for i in infos for ar in i.get("area", [])): continue
        level = next((p.get("value", "") for p in info.get("parameter", []) if p.get("valueName") == "awareness_level"), "")
        colour = level.split(";")[1].strip().upper() if level.count(";") >= 1 else ""
        if colour == "GREEN": continue
        out.append(Alert(f"meteoalarm:{a.get('identifier')}", "weather",
                         short(f"{colour + ' ' if colour else ''}{info.get('event', 'weather warning')} - {area['name']} (MeteoAlarm)"), "MeteoAlarm"))
    return out


SOURCES = {"disasters": gdacs, "quakes": usgs, "tsunami": tsunami, "weather": weather}
