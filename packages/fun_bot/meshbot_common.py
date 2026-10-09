"""Shared plumbing for mcIRC's command bots (weather bot, fun bot): reading a command, rate limits, finding a place, short web requests,
and cutting an answer into mesh-sized messages.  Nothing here touches the radio; the addons send through self.api."""
import json
import re
import time
import urllib.parse
import urllib.request

MAX_CHARS = 115                 # a MeshCore message holds about 120 characters (the name of the sender is added on top)
UA = "mcIRC-bot/1.0 (https://github.com/bclml/mcIRC)"


# ---- web --------------------------------------------------------------------------------------------------------------------------------
def http_get(url, params=None, timeout=12, headers=None):
    if params: url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=dict({"User-Agent": UA, "Accept": "application/json, */*"}, **(headers or {})))
    with urllib.request.urlopen(req, timeout=timeout) as r: return r.read()


def http_json(url, params=None, timeout=12, headers=None): return json.loads(http_get(url, params, timeout, headers).decode("utf-8"))


# ---- commands ---------------------------------------------------------------------------------------------------------------------------
CALL_MARKS = ("!", "/", ".")                                          # '!wx', '/wx', '.wx' - the ways other bots are called
ADDRESSED = re.compile(r"^@\[[^\]]*\]\s*[:,]?\s*|^@\S+[:,]\s*")       # '@[mcIRC] wx ...', '@mcIRC: wx ...'


def parse_command(text, commands, prefix=""):
    """'wx 98101' -> ('wx', '98101') when 'wx' is one of `commands`; None otherwise.  With a prefix ('!') only '!wx 98101' counts;
    without one, '!wx', '/wx' and '.wx' work as well as 'wx', also after addressing the bot ('@[mcIRC] wx').  The command has to be
    the first word, so normal chat rarely triggers it."""
    t = ADDRESSED.sub("", (text or "").strip(), count=1)
    if prefix:
        if not t.startswith(prefix): return None
        t = t[len(prefix):]
    elif t[:1] in CALL_MARKS:
        t = t[1:]
    word, _, arg = t.partition(" ")
    word = word.lower().rstrip("?.,!")
    return (word, arg.strip()) if word in commands else None


def norm_channel(name):
    n = re.sub(r"\s*\[[^\]]*\]$", "", (name or "").strip().lower())      # 'Public [915]' (a window of an extra node) is still 'public'
    if n in ("public", "#public", "0"): return "public"
    return n if n.startswith("#") else "#" + n if n else ""


def channel_list(text):
    """'#weather, Public' -> {'#weather', 'public'};  'all' / '*' -> {'*'}."""
    out = set()
    for part in re.split(r"[,;\s]+", text or ""):
        if part.strip() in ("all", "*"): out.add("*")
        elif part.strip(): out.add(norm_channel(part))
    return out


def channel_ok(channel, allowed):
    return "*" in allowed or norm_channel(channel) in allowed


class Limiter:
    """At most one answer per person every `per_user` seconds, and a gap of `gap` seconds between any two answers."""
    def __init__(self, per_user=30, gap=5):
        self.per_user, self.gap, self.last, self.last_any = per_user, gap, {}, 0.0

    def allow(self, who, now=None):
        now = now or time.time()
        if now - self.last_any < self.gap or now - self.last.get(who, 0) < self.per_user: return False
        self.last_any = self.last[who] = now
        return True


def split_message(text, limit=MAX_CHARS, max_parts=3):
    """Cuts an answer into messages of at most `limit` characters, at ' | ' first, then between words.  At most `max_parts` messages."""
    parts, cur = [], ""
    for chunk in text.split(" | "):
        piece = chunk if not cur else cur + " | " + chunk
        if len(piece) <= limit:
            cur = piece
            continue
        if cur: parts.append(cur)
        cur = ""
        for word in chunk.split(" "):
            piece = word if not cur else cur + " " + word
            if len(piece) <= limit: cur = piece
            else:
                if cur: parts.append(cur)
                cur = word[:limit]
    if cur: parts.append(cur)
    if len(parts) > max_parts:
        parts = parts[:max_parts]
        parts[-1] = parts[-1][:limit - 1].rstrip() + "…"
    return parts


# ---- places -----------------------------------------------------------------------------------------------------------------------------
COORDS = re.compile(r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*[, ]\s*(-?\d{1,3}(?:\.\d+)?)\s*$")
US_ZIP = re.compile(r"^\d{5}$")
CA_POSTAL = re.compile(r"^([A-Za-z]\d[A-Za-z])\s?(\d[A-Za-z]\d)?$")


def resolve_place(arg, nodes=None, default=None, get=http_json, near=None):
    """A place for a weather answer -> (lat, lon, label).  arg can be: empty (the bot's own location), 'lat,lon', a US ZIP code,
    a Canadian postal code, the name of a node / repeater mcIRC knows, or a town name.  Raises ValueError with a short reason."""
    a = (arg or "").strip()
    if not a:
        if default and (default[0] or default[1]): return default
        raise ValueError("no location set for this bot - add a place, e.g. 'Hope BC'")
    m = COORDS.match(a)
    if m:
        lat, lon = float(m.group(1)), float(m.group(2))
        if -90 <= lat <= 90 and -180 <= lon <= 180: return lat, lon, town_name(lat, lon, get) or f"{lat:.2f},{lon:.2f}"
    if US_ZIP.match(a):
        d = get(f"https://api.zippopotam.us/us/{a}")
        p = d["places"][0]
        return float(p["latitude"]), float(p["longitude"]), f"{p['place name']} {p['state abbreviation']}"
    m = CA_POSTAL.match(a)
    if m:
        d = get(f"https://api.zippopotam.us/ca/{m.group(1).upper()}")
        p = d["places"][0]
        return float(p["latitude"]), float(p["longitude"]), f"{p['place name']} {p.get('state abbreviation', '')}".strip()
    if nodes is not None:
        rows = [n for n in nodes.all() if (n["lat"] or n["lon"])]
        exact = [n for n in rows if n["name"].lower() == a.lower()]
        part = exact or [n for n in rows if a.lower() in n["name"].lower()]
        if part: return part[0]["lat"], part[0]["lon"], part[0]["name"][:24]
    name, _, region = a.partition(",")
    if not region and " " in a and len(a.split()[-1]) == 2: name, region = a.rsplit(" ", 1)      # 'Hope BC'
    d = get("https://geocoding-api.open-meteo.com/v1/search", {"name": name.strip(), "count": 100, "language": "en", "format": "json"})
    res = d.get("results") or []
    if region.strip():                                     # 'Hope BC' must not become Hope, Arkansas
        r = region.strip().lower()
        res = [x for x in res if r in (x.get("admin1", "") + " " + x.get("country_code", "") + " " + x.get("country", "")).lower()
               or _abbr(x.get("admin1", "")) == r]
    if not res: raise ValueError(f"can't find '{a}'")
    x = res[0]
    if near and (near[0] or near[1]) and not region.strip():      # 'Surrey' near Vancouver is Surrey BC, not Surrey in England
        close = min(res, key=lambda r: distance_km(near[0], near[1], r["latitude"], r["longitude"]))
        if distance_km(near[0], near[1], close["latitude"], close["longitude"]) < 600:
            same = [r for r in res if distance_km(close["latitude"], close["longitude"], r["latitude"], r["longitude"]) < 40]
            x = max(same, key=lambda r: r.get("population") or 0)        # the city itself rather than one of its neighbourhoods
    return x["latitude"], x["longitude"], x["name"].split(" British Columbia")[0][:20]


_last_osm = 0.0


def town_name(lat, lon, get=http_json):
    """The town at these coordinates ('Hope BC'), from OpenStreetMap; None if there is none (open sea) or the lookup fails."""
    global _last_osm
    wait = 1.1 - (time.time() - _last_osm)                 # OpenStreetMap allows one lookup per second
    if wait > 0: time.sleep(wait)
    _last_osm = time.time()
    try: d = get("https://nominatim.openstreetmap.org/reverse", {"lat": lat, "lon": lon, "format": "json", "zoom": 10, "addressdetails": 1})
    except Exception: return None
    a = d.get("address") or {}
    name = next((a[k] for k in ("city", "town", "village", "hamlet", "municipality") if a.get(k)), None)
    if not name: return None
    name = re.sub(r"^Area [A-Z]+ \((.*)\)$", r"\1", name).split("/")[0].strip()      # BC regional district areas: 'Area F (McConnell Creek/...)'
    region = (a.get("ISO3166-2-lvl4") or "").split("-")[-1]
    return f"{name[:22]} {region}".strip()


def send_parts(api, msg, text, max_parts=3, first_delay=5000, gap=9000, label=False):      # (gap: mcIRC listens ~8 s after each message for its repeats)
    """Answer `msg` with `text` in mesh-sized parts.  The first part waits a few seconds: answering at once collides with the repeaters
    still repeating the question.  With label=True later parts start with the text before the first ': ' (the place: 'Hope BC: Mon 14/8C ...')
    so each one makes sense on its own."""
    label = text.split(": ", 1)[0] if label and ": " in text[:34] else ""
    parts = split_message(text, limit=MAX_CHARS - (len(label) + 2 if label else 0), max_parts=max_parts)
    if label: parts = [p if not i or p.startswith(label) else f"{label}: {p}" for i, p in enumerate(parts)]
    for i, part in enumerate(parts): api.after(first_delay + i * gap, lambda p=part: api.reply(msg, p))
    return parts


PROVINCES = {"british columbia": "bc", "alberta": "ab", "saskatchewan": "sk", "manitoba": "mb", "ontario": "on", "quebec": "qc",
             "washington": "wa", "oregon": "or", "california": "ca", "idaho": "id", "new york": "ny", "texas": "tx"}
def _abbr(admin1): return PROVINCES.get((admin1 or "").lower(), "")


def distance_km(lat1, lon1, lat2, lon2):
    import math
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    return 6371 * math.acos(max(-1.0, min(1.0, math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(dl))))


COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
def compass(deg): return COMPASS[int((float(deg) % 360) / 22.5 + 0.5) % 16]
