"""Area alerts: public transit service alerts (GTFS-realtime) from the transit agencies serving your areas, found in the Mobility Database
(mobilitydatabase.org): 489 feeds in 28 countries.  Most are open; some need a free key from the agency - the settings show where to get it.

Only alerts in force now, and by default only service stops and big delays: the agency's own label when it gives one, else the alert's
wording (many agencies label every alert 'unknown effect')."""
import base64
import gzip
import json
import re
import time
import zlib

from aa_sources import Alert, UA, km, short

EFFECTS = {1: "No service", 2: "Reduced service", 3: "Significant delays", 4: "Detour", 5: "Additional service", 6: "Modified service",
           7: "Other", 8: "Unknown", 9: "Stop moved", 10: "No effect", 11: "Accessibility issue"}
MAJOR = {1, 2, 3}             # no service, reduced service, significant delays
MINOR = {5, 6, 9, 10, 11}     # extra service, modified service, stop moved, no effect, accessibility (lifts): never 'major'
# words of a service stop or big delay, for alerts the agency didn't label (English, French, Spanish, Portuguese, Italian, German, Swedish,
# Dutch, Polish, Japanese)
MAJOR_WORDS = re.compile(r"suspend|suspension|cancel|no service|not running|not operating|out of service|shut ?down|closed|closure|"
                         r"major delay|significant delay|severe delay|long delay|disrupt|annul|interromp|supprim|interrupt|suspen|cancelad|"
                         r"störung|ausfall|eingestellt|gesperrt|inställ|stopp|storing|uitval|odwoł|wstrzym|運休|運転見合わせ|大幅", re.I)
NEAR_KM = 15                 # a feed serves an area when the area is inside its box, or this close to it
_cache = {}


def feeds():
    """[{'id', 'provider', 'name', 'cc', 'sub', 'city', 'url', 'auth', 'info', 'param', 'bbox'}] - loaded once."""
    if "f" not in _cache:
        import aa_transit_feeds
        _cache["f"] = json.loads(gzip.decompress(base64.b85decode("".join(aa_transit_feeds.DATA))).decode("utf-8"))
    return _cache["f"]


def _near_box(lat, lon, box):
    la1, la2, lo1, lo2 = box
    if la1 <= lat <= la2 and lo1 <= lon <= lo2: return True
    return km(lat, lon, min(max(lat, la1), la2), min(max(lon, lo1), lo2)) <= NEAR_KM


def _too_big(box):
    """Boxes over about 1500 km across are nation-wide feeds or bad data: matched by city name only."""
    return km(box[0], box[2], box[1], box[3]) > 1500


def feeds_for(area):
    """The feeds serving the area: its point is in (or near) the feed's box; without a usable box, the same city."""
    out = []
    for f in feeds():
        if f["cc"] and f["cc"] != area.get("country"): continue
        if f["bbox"] and not _too_big(f["bbox"]):
            if _near_box(area["lat"], area["lon"], f["bbox"]): out.append(f)
        elif f["city"] and f["city"].lower() == area["name"].lower():
            out.append(f)
    return out


def label(f):
    name = f["name"] if f["name"] and f["name"] != f["provider"] else ""
    who = re.sub(r"\s*\|\s*", ", ", f["provider"])         # 'BC Transit (Central Fraser Valley| Chilliwack| Agassiz-Harri' (cut at 60)
    if who.count("(") > who.count(")"): who = re.sub(r",?\s*[^,(]*$", "", who) + "...)"
    return f"{who}{' - ' + name if name else ''}"


def key_help(f):
    """How to get the free key, in words people can follow."""
    where = f["info"] or "the agency's developer page"
    how = (f"it goes in the address as '{f['param']}'" if f["auth"] == 1 else f"it is sent as the '{f['param']}' header") if f["param"] else ""
    return f"Needs a free key: sign up at {where}, then paste the key here{' (' + how + ')' if how else ''}."


def _fetch(f, key="", get=None):
    """The feed's bytes; the key never appears in errors."""
    if get: return get(f, key)
    import requests
    headers, params = dict(UA), {}
    if f["auth"] == 1 and key: params[f["param"] or "api_key"] = key
    if f["auth"] == 2 and key: headers[f["param"] or "x-api-key"] = key
    try:
        r = requests.get(f["url"], params=params, headers=headers, timeout=25)
        r.raise_for_status()
        return r.content
    except Exception as e:
        msg = str(e)
        if key: msg = msg.replace(key, "***")
        raise RuntimeError(re.sub(r"https?://\S+", f["url"].split("?")[0], msg)) from None


def _text(ts):
    """A GTFS-rt TranslatedString: English if there is, else the first."""
    tr = list(ts.translation)
    if not tr: return ""
    return next((t.text for t in tr if (t.language or "").lower().startswith("en")), tr[0].text)


STOP_ONLY = re.compile(r"stop closure|closure of stop|stop (?:is )?(?:closed|moved|relocated)|stops? .{0,40}will be closed|arr[eê]t (?:ferm|d[ée]plac)", re.I)
LIFTS = re.compile(r"elevator|escalator|\blift\b|ascenseur|escalier m|ascensor|elevador|aufzug|rolltreppe|hiss|rulltrappa|winda|エレベーター", re.I)


def major(effect, text):
    """A service stop or big delay: labelled so, or (labelled 'other' / 'unknown' / detour) worded so - lift and escalator outages aside."""
    if effect in MAJOR: return True
    if effect in MINOR or LIFTS.search(text or "") or STOP_ONLY.search(text or ""): return False
    return bool(MAJOR_WORDS.search(text or ""))


def short_name(provider):
    """'Metropolitan Transit Authority (MTA)' -> 'MTA'."""
    m = re.search(r"\(([^)|]{2,12})\)\s*$", provider or "")
    if m: return m.group(1)
    return re.split(r"\s*[(|]", provider or "")[0] or provider       # 'BC Transit (Central Fraser Valley| Chilliwack ...' -> 'BC Transit'


def alerts(f, key="", all_effects=False, get=None, now=None):
    """The feed's alerts in force now, as Alerts of kind 'transit' - one per alert text (the routes it names gathered)."""
    from google.transit import gtfs_realtime_pb2
    msg = gtfs_realtime_pb2.FeedMessage()
    msg.ParseFromString(_fetch(f, key, get))
    now = now or time.time()
    found = {}                                  # header -> [effect, routes, entity ids]
    for e in msg.entity:
        if not e.HasField("alert"): continue
        a = e.alert
        periods = list(a.active_period)
        if periods and not any((p.start or 0) <= now <= (p.end or 4e9) for p in periods): continue
        effect = a.effect if a.HasField("effect") else 8
        head = _text(a.header_text) or _text(a.description_text)
        if not head: continue
        if not all_effects and not major(effect, head + " " + _text(a.description_text)): continue
        item = found.setdefault(head, [effect, set(), []])
        item[1].update(ie.route_id for ie in a.informed_entity if ie.route_id)
        item[2].append(e.id)
    out, who = [], short_name(f["provider"])
    for head, (effect, routes, ids) in found.items():
        routes = sorted(routes)
        where = f" (route{'s' if len(routes) > 1 else ''} {', '.join(routes[:4])}{'...' if len(routes) > 4 else ''})"             if routes and len(routes) <= 8 and not any(r in head for r in routes) else ""
        what = "" if effect in (7, 8) else EFFECTS.get(effect, "") + " - "
        out.append(Alert(f"transit:{f['id']}:{zlib.crc32(head.encode()):08x}", "transit", short(f"{who}: {what}{head}{where}"), f["provider"]))
    return out
