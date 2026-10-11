"""Traffic, transit and weather: 'route <address>' - driving directions from the asker's node to an address, with the DriveBC closures,
incidents and roadwork along the way (British Columbia), as a few short mesh messages.

Free services, no key: OpenStreetMap Nominatim (finding the address, at most one lookup a second) and OSRM (routes, with alternatives).
Travel times are without live congestion; 'current conditions' are DriveBC's closures, incidents and roadwork.  The best route: the
quickest, then (about as quick) the one with fewer incidents and roadwork; a route through a full closure is not taken while another
is open.  Answered only by private message - a destination is never logged."""
import math
import re
import threading
import time

UA = {"User-Agent": "mcIRC traffic route (github.com/bclml/mcIRC)"}
NOMINATIM = "https://nominatim.openstreetmap.org/search"
OSRM = "https://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}"
DRIVEBC = "https://api.open511.gov.bc.ca/events"
NEAR_M = 150                    # an event this close to the route is on the way
BC = (48.2, 60.1, -139.1, -114.0)   # lat min / max, lon min / max: where DriveBC reports
CLOSED = re.compile(r"(?:^|[.:]\s+)(?:road |bridge |highway |route )?closed\b(?! for (?:the )?season)", re.I)
SIMILAR_MIN = 3                 # routes this close in time count as equally quick: then fewer incidents and roadwork decide
_lock, _last = threading.Lock(), [0.0]
_cache = {}                     # DriveBC's answer for a minute (it limits how often it is asked)


def _get(url, params=None):
    import requests
    if "nominatim" in url:                       # Nominatim's rule: at most one request a second
        with _lock:
            wait = 1.1 - (time.time() - _last[0])
            if wait > 0: time.sleep(wait)
            _last[0] = time.time()
    r = requests.get(url, params=params, headers=UA, timeout=20)
    r.raise_for_status()
    return r.json()


def _metres(a, b):
    """Distance in metres between two (lat, lon) points (short distances)."""
    x = math.radians(b[1] - a[1]) * math.cos(math.radians((a[0] + b[0]) / 2))
    y = math.radians(b[0] - a[0])
    return 6371000 * math.hypot(x, y)


def _to_segment(p, a, b):
    """Metres from point p to the segment a-b (flat-earth: fine over a few km)."""
    k = math.cos(math.radians(p[0]))
    ax, ay, bx, by, px, py = a[1] * k, a[0], b[1] * k, b[0], p[1] * k, p[0]
    dx, dy = bx - ax, by - ay
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return _metres(p, (ay + t * dy, (ax + t * dx) / k))


def in_bc(p): return BC[0] <= p[0] <= BC[1] and BC[2] <= p[1] <= BC[3]


def geocode(query, near=None, get=None):
    """(lat, lon, short name) of an address or place, the one nearest `near` first; None when not found."""
    params = {"q": query, "format": "jsonv2", "limit": 1, "addressdetails": 1}
    if near:
        params.update(viewbox=f"{near[1] - 1.5},{near[0] + 1},{near[1] + 1.5},{near[0] - 1}", bounded=0)
    res = (get or _get)(NOMINATIM, params)
    if not res: return None
    r = res[0]
    a = r.get("address") or {}
    town = next((a[k] for k in ("city", "town", "village", "municipality", "county") if a.get(k)), "")
    street = " ".join(x for x in (a.get("house_number"), a.get("road")) if x)
    name = r.get("name") or street or (r.get("display_name") or query).split(",")[0]
    if town and town != name: name = f"{name}, {town}"           # 'Metrotown, Burnaby' / '1234 Main Street, Vancouver'
    return float(r["lat"]), float(r["lon"]), name[:40]


def routes(a, b, get=None):
    """Driving routes a -> b (best first, with alternatives): [{'km', 'min', 'coords': [(lat, lon)], 'roads': [names]}]."""
    data = (get or _get)(OSRM.format(lat1=a[0], lon1=a[1], lat2=b[0], lon2=b[1]),
                         {"alternatives": "true", "steps": "true", "overview": "full", "geometries": "geojson"})
    out = []
    for r in data.get("routes", []) if data.get("code") == "Ok" else []:
        length = {}
        for leg in r.get("legs", []):
            for s in leg.get("steps", []):
                n = s.get("ref") or s.get("name")
                if n: length[n] = length.get(n, 0) + s.get("distance", 0)
        roads = [n for n, d in sorted(length.items(), key=lambda x: -x[1]) if d > 300][:3]
        out.append({"km": r["distance"] / 1000, "min": r["duration"] / 60, "roads": roads,
                    "coords": [(c[1], c[0]) for c in r["geometry"]["coordinates"]]})
    return out


def _on_now(schedule, now):
    iv = (schedule or {}).get("intervals") or []
    if not iv: return True
    stamp = time.strftime("%Y-%m-%dT%H:%M", time.localtime(now))
    return any(i.partition("/")[0][:16] <= stamp and (not i.partition("/")[2] or stamp <= i.partition("/")[2][:16]) for i in iv)


def drivebc_events(coords, get=None, now=None):
    """DriveBC's events (on now) in the box around the route: [{'id', 'what', 'road', 'points'}]."""
    la = [c[0] for c in coords]; lo = [c[1] for c in coords]
    bbox = f"{min(lo) - 0.02:.3f},{min(la) - 0.02:.3f},{max(lo) + 0.02:.3f},{max(la) + 0.02:.3f}"
    key = (bbox, int(time.time() // 60))
    if get is None and key in _cache: data = _cache[key]
    else:
        data = (get or _get)(DRIVEBC, {"status": "ACTIVE", "format": "json", "bbox": bbox, "limit": 500})
        if get is None: _cache.clear(); _cache[key] = data
    out, now = [], now or time.time()
    for e in data.get("events", []):
        if not _on_now(e.get("schedule"), now): continue
        desc = re.sub(r"\s+", " ", e.get("description", "")).strip()
        kind = e.get("event_type", "")
        what = "CLOSED" if CLOSED.search(desc) else "Incident" if kind == "INCIDENT" else "Roadwork" if kind == "CONSTRUCTION" else ""
        if not what: continue
        if what == "Roadwork" and e.get("severity") == "MINOR": continue      # lane work that rarely matters for the route
        g = e.get("geography") or {}
        pts = [g["coordinates"]] if g.get("type") == "Point" else g.get("coordinates") or []
        if g.get("type") == "MultiLineString": pts = [p for line in pts for p in line]
        road = next((r.get("name") for r in e.get("roads", []) if r.get("name") and r.get("name") != "Other Roads"), "")
        place = re.sub(r"^[^,]*? (?:at|from) ", "", desc.split(".")[0])[:40]
        out.append({"id": e.get("id"), "what": what, "road": road, "place": place, "points": [(p[1], p[0]) for p in pts if len(p) >= 2]})
    return out


def on_route(route, events):
    """The events within NEAR_M of the route."""
    c = route["coords"]
    step = max(1, len(c) // 1500)                # (long routes: every few points is plenty)
    line = c[::step] + ([c[-1]] if c and (len(c) - 1) % step else [])
    hit = []
    for e in events:
        for p in e["points"][:20]:
            if any(_to_segment(p, line[i], line[i + 1]) <= NEAR_M for i in range(len(line) - 1)):
                hit.append(e)
                break
    return hit


MAX_CHARS = 115                 # one mesh message


def ago(seconds):
    s = max(0, int(seconds))
    return f"{max(1, s // 60)} min" if s < 3600 else f"{s // 3600} h" if s < 48 * 3600 else f"{s // 86400} days"


def start_note(age):
    """Where the route starts: the asker's node's advertised position, and how old that advert is."""
    if age is None: return "Start: your node's advertised position (when it last advertised isn't known) - it may be out of date."
    if age < 15 * 60: return f"Start: your node's advertised position (advert {ago(age)} ago)."
    return f"Start: your node's last advert ({ago(age)} ago) - if you've moved since, send an advert and ask again."


def _fit(text, n=MAX_CHARS):
    return text if len(text) <= n else text[:n - 3].rstrip(" ,;") + "..."


def answer(origin, query, get=None, now=None, known=None, origin_age=None):
    """The answer as short parts: [route line, what is on the way, where it starts].  known(): DriveBC events the bot already has (its
    traffic check, same form as drivebc_events) - used when DriveBC doesn't answer this request.  origin_age: seconds since the asker's
    node advertised the position used (None: not known); not given for 'route <from> to <to>'."""
    parts = _answer(origin, query, get, now, known)
    if origin is not None and len(parts) >= 2 and parts[0].startswith("Route to") and not re.match(r"(?i)\s*.+?\s+to\s+.+$", query):
        parts.append(start_note(origin_age))
    return [_fit(p) for p in parts]


def _answer(origin, query, get=None, now=None, known=None):
    to = query
    m = re.match(r"(?i)\s*(.+?)\s+to\s+(.+)$", query)
    if m:                                        # 'route <from> to <to>': from that address (the node's position isn't used)
        start = geocode(m.group(1), get=get)
        if not start: return [f"Couldn't find '{m.group(1)[:40]}'."]
        origin, to = start[:2], m.group(2)
    if not origin:
        return ["Your node doesn't share its position. Set it on your node, or ask: route <from address> to <to address>"]
    dest = geocode(to, near=origin, get=get)
    if not dest: return [f"Couldn't find '{to[:40]}'. Try a fuller address (street, city)."]
    rs = routes(origin, dest[:2], get=get)
    if not rs: return [f"No driving route found to {dest[2]}."]
    bc = in_bc(origin) or in_bc(dest[:2])
    busy = stale = False
    for r in rs: r["events"] = []
    if bc:
        try:
            events = drivebc_events([p for r in rs for p in r["coords"]], get=get, now=now)
        except Exception:                           # DriveBC busy / down: what the bot's own traffic check last had, else the route alone
            events = None
            try: events = known() if known else None
            except Exception: events = None
            busy, stale = events is None, events is not None
        for r in rs: r["events"] = on_route(r, events or [])
    closed = lambda r: sum(e["what"] == "CLOSED" for e in r["events"])
    trouble = lambda r: sum(e["what"] in ("Incident", "Roadwork") for e in r["events"])
    open_routes = [r for r in rs if not closed(r)] or rs          # a full closure: not while another route is open
    quickest = min(open_routes, key=lambda r: r["min"])
    best = min((r for r in open_routes if r["min"] - quickest["min"] <= SIMILAR_MIN), key=lambda r: (trouble(r), r["min"]))
    fastest = min(rs, key=lambda r: r["min"])
    why = ""
    if best is not fastest:
        why = f" (avoids {closed(fastest)} closure{'s' if closed(fastest) != 1 else ''})" if closed(fastest) else               f" (fewer incidents / roadwork, +{best['min'] - fastest['min']:.0f} min)"
    roads = list(best["roads"])
    while True:                                     # one mesh message: fewer road names before anything is cut
        via = f" via {', '.join(roads)}" if roads else ""
        first = f"Route to {dest[2]}: {best['km']:.0f} km, ~{best['min']:.0f} min{via}{why}"
        if len(first) <= MAX_CHARS or not roads: break
        roads.pop()
    if not bc:
        return [first, "Traffic: no live closures here (DriveBC covers British Columbia). Times are without congestion."]
    if busy: return [first, "Traffic: DriveBC didn't answer just now - closures not checked. Try again in a minute."]
    ev = best["events"]
    src = " (from the last DriveBC check)" if stale else ""
    if not ev: return [first, f"On the way: no closures, incidents or roadwork reported{src or ' (DriveBC)'}. Times are without congestion."]
    items = [f"{e['what']} {e['road'] or e['place']}".strip() for e in sorted(ev, key=lambda e: ("CLOSED", "Incident", "Roadwork").index(e["what"]))]
    more = f" +{len(items) - 4} more" if len(items) > 4 else ""
    return [first, "On the way: " + "; ".join(items[:4]) + more + src]
