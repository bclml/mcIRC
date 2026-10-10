"""Area alerts: road traffic - closures, crashes and incidents near your areas.

  British Columbia   DriveBC (Open511) - open, no key
  20 other 511 sites (8 Canadian provinces and territories, 12 US states / regions) - all on the same 511 system, each needs its own free
                     developer key: make an account on the site, then ask for the key on its developer page (most answer at once).

Québec 511 has no open feed.  Elsewhere in the world road data is mostly behind paid or registration-only national services."""
import re
import time

from aa_sources import Alert, UA, km, short

DRIVEBC_URL = "https://api.open511.gov.bc.ca/events"
# region (as in the area picker) -> (511 site, the region's name for people, developer page: None when the site has no public one)
SITES = {
    ("CA", "Alberta"): ("511.alberta.ca", "511 Alberta", "/developers/doc"),
    ("CA", "Ontario"): ("511on.ca", "Ontario 511", "/developers/doc"),
    ("CA", "Manitoba"): ("www.manitoba511.ca", "Manitoba 511", "/developers/doc"),
    ("CA", "New Brunswick"): ("511.gnb.ca", "New Brunswick 511", "/developers/doc"),
    ("CA", "Nova Scotia"): ("511.novascotia.ca", "Nova Scotia 511", None),
    ("CA", "Newfoundland and Labrador"): ("www.511nl.ca", "Newfoundland and Labrador 511", "/developers/doc"),
    ("CA", "Yukon"): ("511yukon.ca", "Yukon 511", "/developers/doc"),
    ("CA", "Saskatchewan"): ("hotline.gov.sk.ca", "Saskatchewan Highway Hotline", None),
    ("US", "Georgia"): ("511ga.org", "Georgia 511", "/developers/doc"),
    ("US", "Arizona"): ("www.az511.gov", "AZ511", "/developers/doc"),
    ("US", "Wisconsin"): ("511wi.gov", "511 Wisconsin", "/developers/doc"),
    ("US", "Idaho"): ("511.idaho.gov", "Idaho 511", "/developers/doc"),
    ("US", "Utah"): ("udottraffic.utah.gov", "UDOT Traffic", "/developers/doc"),
    ("US", "Louisiana"): ("www.511la.org", "511 Louisiana", "/developers/doc"),
    ("US", "Connecticut"): ("ctroads.org", "CTroads", "/developers/doc"),
    ("US", "Alaska"): ("511.alaska.gov", "Alaska 511", "/developers/doc"),
    ("US", "Nevada"): ("www.nvroads.com", "NVRoads", "/developers/doc"),
    ("US", "Florida"): ("fl511.com", "FL511", None),
    ("US", "Pennsylvania"): ("www.511pa.com", "511PA", None),
    ("US", "Maine"): ("newengland511.org", "New England 511", None),
    ("US", "New Hampshire"): ("newengland511.org", "New England 511", None),
    ("US", "Vermont"): ("newengland511.org", "New England 511", None),
}
KINDS_511 = {"closures": "Closure", "accidentsAndIncidents": "Incident", "roadwork": "Roadwork", "specialEvents": "Event"}
DEFAULT_KM = 40


SLUGS = {"hotline.gov.sk.ca": "skhotline"}


def slot_for(area):
    """Which road source the area uses: 'drivebc', '511:<site>', or None."""
    if (area.get("country"), area.get("region")) == ("CA", "British Columbia"): return "drivebc"
    site = site_for(area)
    return f"511:{site[0]}" if site else None


def slug(slot):
    """A channel name for the road source: 'drivebc', '511alberta', 'ontario511', '511nl' ..."""
    if slot == "drivebc": return "drivebc"
    host = slot.split(":", 1)[1]
    if host in SLUGS: return SLUGS[host]
    name = next(n for h, n, _ in SITES.values() if h == host)
    s = re.sub(r"[^a-z0-9]", "", name.lower())
    return s if len(s) <= 14 else re.sub(r"[^a-z0-9]", "", host.replace("www.", "").rsplit(".", 1)[0])


def label(slot):
    if slot == "drivebc": return "DriveBC"
    host = slot.split(":", 1)[1]
    return next(n for h, n, _ in SITES.values() if h == host)


def site_for(area):
    """(host, name, developer page) of the 511 site covering the area, or None."""
    return SITES.get((area.get("country"), area.get("region")))


def key_help(site):
    """Plain steps to get the site's free developer key."""
    host, name, dev = site
    if dev:
        return (f"{name} needs a free developer key: 1) make an account at https://{host}/my511/register  2) log in and request the key "
                f"at https://{host}{dev}  3) paste it here.")
    return (f"{name} needs a free developer key: 1) make an account at https://{host}/my511/register  2) it has no public developer page - "
            f"ask for a developer API key through the site's Contact page  3) paste it here.")


def needs_key(area):
    return site_for(area) is not None


def _get(url, params, key=""):
    import requests
    try:
        r = requests.get(url, params=params, headers=UA, timeout=25)
        if r.status_code == 400 and "Invalid Key" in r.text: raise RuntimeError("the key was refused (Invalid Key) - check it in the settings")
        r.raise_for_status()
        return r.json()
    except RuntimeError: raise
    except Exception as e:
        msg = str(e)
        if key: msg = msg.replace(key, "***")
        raise RuntimeError(re.sub(r"\?\S+", "", msg)) from None


def _wanted(kind, full_closure, roadwork):
    if kind == "roadwork": return roadwork or full_closure
    return kind in ("closures", "accidentsAndIncidents") or full_closure


def events_511(area, key, radius_km=DEFAULT_KM, roadwork=False, get=None):
    """Closures and incidents (roadwork too if asked, full closures always) within radius_km of the area."""
    site = site_for(area)
    if not site or not key: return []
    data = (get or _get)(f"https://{site[0]}/api/v2/get/event", {"key": key, "format": "json", "lang": "en"}, key)
    out = []
    for e in data if isinstance(data, list) else []:
        lat, lon = e.get("Latitude"), e.get("Longitude")
        if lat is None or lon is None or km(area["lat"], area["lon"], lat, lon) > radius_km: continue
        kind = e.get("EventType", "")
        if not _wanted(kind, bool(e.get("IsFullClosure")), roadwork): continue
        what = "FULL CLOSURE" if e.get("IsFullClosure") else KINDS_511.get(kind, "Traffic")
        road = e.get("RoadwayName") or ""
        desc = re.sub(r"<[^>]+>", " ", e.get("Description") or e.get("EventSubType") or "")
        if road and desc.lower().startswith(road.lower()): road = ""
        out.append(Alert(f"511:{site[0]}:{e.get('ID')}:{what}", "traffic", short(f"{what}: {road + ' - ' if road else ''}{desc}"), site[1]))
    return out


CLOSED = re.compile(r"(?:^|[.:]\s+)(?:road |bridge |highway |route )?closed\b(?! for (?:the )?season)", re.I)   # not 'Left lane closed'


def _now_in(schedule, now):
    """Open511 schedule intervals ('2026-10-26T09:00/2026-10-26T15:00'): is one of them on now?  No intervals: yes."""
    iv = (schedule or {}).get("intervals") or []
    if not iv: return True
    stamp = time.strftime("%Y-%m-%dT%H:%M", time.localtime(now))
    for i in iv:
        start, _, end = i.partition("/")
        if start[:16] <= stamp and (not end or stamp <= end[:16]): return True
    return False


def drivebc(area, radius_km=DEFAULT_KM, roadwork=False, get=None, now=None):
    """DriveBC's events near a BC area (Open511, no key): incidents and road closures on now; other roadwork only if asked."""
    if (area.get("country"), area.get("region")) != ("CA", "British Columbia"): return []
    d_lat, d_lon = radius_km / 111.0, radius_km / 70.0
    bbox = f"{area['lon'] - d_lon:.3f},{area['lat'] - d_lat:.3f},{area['lon'] + d_lon:.3f},{area['lat'] + d_lat:.3f}"
    data = (get or _get)(DRIVEBC_URL, {"status": "ACTIVE", "format": "json", "bbox": bbox, "limit": 500})
    out, now = [], now or time.time()
    for e in data.get("events", []):
        kind, sev = e.get("event_type", ""), e.get("severity", "")
        desc = re.sub(r"\s+", " ", e.get("description", "")).strip()
        closed = bool(CLOSED.search(desc))
        if not _now_in(e.get("schedule"), now): continue
        if kind == "INCIDENT": keep = closed or sev in ("MAJOR", "MODERATE")
        elif kind == "CONSTRUCTION": keep = closed or (roadwork and sev == "MAJOR")
        else: keep = closed
        if not keep: continue
        road = ", ".join(r.get("name", "") for r in e.get("roads", [])[:1] if r.get("name") != "Other Roads")
        what = "CLOSED" if closed else {"INCIDENT": "Incident", "CONSTRUCTION": "Roadwork"}.get(kind, kind.replace("_", " ").title())
        out.append(Alert(f"drivebc:{e.get('id')}:{what}", "traffic", short(f"{what}: {road + ' - ' if road else ''}{desc}"), "DriveBC"))
    return out


def traffic(area, key="", radius_km=DEFAULT_KM, roadwork=False):
    return drivebc(area, radius_km, roadwork) + events_511(area, key, radius_km, roadwork)


def available(area):
    """What traffic source the area has, in words for the settings window."""
    if (area.get("country"), area.get("region")) == ("CA", "British Columbia"): return "DriveBC (open, no key)"
    site = site_for(area)
    if site: return f"{site[1]} (free key needed)"
    if (area.get("country"), area.get("region")) == ("CA", "Quebec"): return "none - Québec 511 has no open feed"
    return "none found for this area yet"
