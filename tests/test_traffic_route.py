import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "packages", "broadcast_alerts")
sys.path.insert(0, ROOT); sys.path.insert(0, PKG); os.chdir(ROOT)
"""Traffic, transit and weather: 'route <address>' by private message - the quickest route, then fewer incidents / roadwork, never through
a closure while another route is open; answered privately only, the address never repeated in a channel.  No radio, no internet."""
import importlib.util, time
from unittest import mock

sys.modules.pop("traffic_route", None)
import traffic_route as tr

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

HOME, DEST = (49.20, -122.90), (49.25, -122.70)
def parts(r):            # {'route': ..., 'via': ..., 'way': ..., 'start': ...} - which line is which
    out = {"all": r}
    for line in r:
        k = "via" if line.startswith("Via:") else "way2" if line.startswith("More on the way") else "start" if line.startswith("Start:") else "way" if line.startswith(("On the way", "Traffic:")) else "route"
        out[k] = line
    return out
def osrm(*routes):          # routes: (km, minutes, road, latitude of its middle point)
    out = []
    for km, mins, road, mid in routes:
        coords = [[HOME[1], HOME[0]], [-122.80, mid], [DEST[1], DEST[0]]]
        out.append({"distance": km * 1000, "duration": mins * 60, "geometry": {"coordinates": coords},
                    "legs": [{"steps": [{"name": road, "distance": km * 1000, "maneuver": {"location": [HOME[1], HOME[0]]}}]}]})
    return {"code": "Ok", "routes": out}
def ev(i, kind, desc, lat, sev="MAJOR", road="Highway 1"):
    return {"id": f"e{i}", "event_type": kind, "severity": sev, "description": desc, "roads": [{"name": road}],
            "geography": {"type": "Point", "coordinates": [-122.80, lat]}}
def fake(routes_data, events=None, found=True, drivebc_error=None, dest=DEST):
    asked = []
    def get(url, params=None):
        asked.append(url)
        if "reverse" in url: return {"address": {"city": "Burnaby" if float(params["lat"]) < 49.22 else "Surrey"}}
        if "nominatim" in url: return [{"lat": str(dest[0]), "lon": str(dest[1]), "name": "Mall", "display_name": "Mall, 1 Main St, Burnaby, BC",
                                        "address": {"house_number": "1", "road": "Main St", "city": "Burnaby"}}] if found else []
        if "osrm" in url: return routes_data
        if drivebc_error: raise drivebc_error
        return {"events": events or []}
    return get, asked

get, _ = fake(osrm((20, 25, "Hwy 1", 49.30), (22, 27, "Hwy 7", 49.10)))
r = parts(tr.answer(HOME, "Mall, Burnaby", get=get))
ok("the quickest route, with distance and time", r["route"] == "Route to Mall, Burnaby: 20 km, ~25 min", r)
ok("...and its roads, with the city it starts in", r.get("via") == "Via: Hwy 1 (Burnaby)", r)
ok("...and nothing reported on the way", r["way"].startswith("On the way: no closures, incidents or roadwork"), r)

get, _ = fake(osrm((20, 25, "Hwy 1", 49.30), (22, 27, "Hwy 7", 49.10)), [ev(1, "INCIDENT", "Crash at Hwy 1.", 49.30)])
r = parts(tr.answer(HOME, "Mall", get=get))
ok("about as quick (within 3 min): the one with fewer incidents / roadwork", r.get("via", "").startswith("Via: Hwy 7") and "fewer incidents" in r["route"], r)
get, _ = fake(osrm((20, 25, "Hwy 1", 49.30), (30, 40, "Hwy 7", 49.10)), [ev(1, "INCIDENT", "Crash at Hwy 1.", 49.30)])
r = parts(tr.answer(HOME, "Mall", get=get))
ok("...but quickest first: a much slower route isn't taken for an incident - it is reported instead", r.get("via", "").startswith("Via: Hwy 1")
   and r["way"] == "On the way: Incident Hwy 1 near Surrey", r)
get, _ = fake(osrm((20, 25, "Hwy 1", 49.30), (30, 40, "Hwy 7", 49.10)), [ev(1, "INCIDENT", "Washout at Hwy 1. Closed.", 49.30)])
r = parts(tr.answer(HOME, "Mall", get=get))
ok("a full closure on the quickest route: the open one, saying why", r.get("via", "").startswith("Via: Hwy 7") and "avoids 1 closure" in r["route"], r)
get, _ = fake(osrm((20, 25, "Hwy 1", 49.30)), [ev(1, "CONSTRUCTION", "Paving at Hwy 1. Left lane closed.", 49.30, sev="MINOR"),
                                                ev(2, "CONSTRUCTION", "Bridge work at Hwy 1.", 49.30), ev(3, "INCIDENT", "Crash far away.", 50.5)])
r = parts(tr.answer(HOME, "Mall", get=get))
ok("on the way: major roadwork (where: DriveBC's cross streets, else the exit, else the town); minor lane work and events off the route left out", r["way"] == "On the way: Roadwork Hwy 1 near Surrey", r)
get, _ = fake(osrm((20, 25, "Hwy 1", 49.30)), drivebc_error=RuntimeError("429 Too Many Requests"))
r = parts(tr.answer(HOME, "Mall", get=get))
ok("DriveBC busy: the route anyway, saying closures weren't checked", r.get("via", "").startswith("Via: Hwy 1") and "DriveBC didn't answer" in r["way"], r)
get, asked = fake(osrm((20, 25, "I-5", 47.7)), dest=(47.62, -122.35))
r = parts(tr.answer((47.60, -122.33), "Space Needle", get=get))
ok("outside British Columbia: directions only, no DriveBC asked", "no live closures here" in r["way"] and not any("open511" in u for u in asked), r)
get, _ = fake(osrm((20, 25, "Hwy 1", 49.30)), found=False)
ok("an address that isn't found says so", tr.answer(HOME, "Nowhere Rd", get=get)[0].startswith("Couldn't find 'Nowhere Rd'"))
get, _ = fake(osrm((20, 25, "Hwy 1", 49.30)))
ok("no position on the asker's node: says how to ask instead", "doesn't share its position" in tr.answer(None, "Mall", get=get)[0])
ok("...and 'route <from> to <to>' works without one", tr.answer(None, "Home Rd to Mall", get=get)[0].startswith("Route to Mall"))
r = parts(tr.answer(HOME, "Mall", get=get, origin_age=6 * 3600))
ok("the answer says the start is the node's last advert, and how old it is", r["start"] == "Start: your node's last advert (6 h ago) - if you've moved since, "
   "send an advert and ask again.", r)
ok("...a fresh advert: just where it starts", tr.answer(HOME, "Mall", get=get, origin_age=120)[-1] == "Start: your node's advertised position (advert 2 min ago).")
ok("...'route <from> to <to>' starts at <from>: no advert note", not any(l.startswith("Start:") for l in tr.answer(HOME, "Home Rd to Mall", get=get)))
# road numbers as people say them, and a city each time the route enters another one
ok("road numbers: 'TCH 1;BC 1' / 'BC 99' / 'BC 17A' -> Hwy 1 / Hwy 99 / Hwy 17A; others as they are", [tr.road_name(x) for x in (
   {"ref": "TCH 1;BC 1"}, {"ref": "BC 99"}, {"ref": "BC 17A"}, {"ref": "I-5"}, {"name": "Kingsway"}, {"ref": "TC-1 W"}, {"ref": "BC-99A;BC-1A"}, {"ref": "1"}, {"name": "Highway 1"})]
   == ["Hwy 1", "Hwy 99", "Hwy 17A", "I-5", "Kingsway", "Hwy 1", "Hwy 99A", "Hwy 1", "Hwy 1"])
ok("towns without 'Township of' / 'City of' (one mesh message is short)", tr.town_at((1, 1), get=lambda *a, **k: {"address": {"city": "Township of Langley"}}) == "Langley"
   and tr.town_at((1, 1), get=lambda *a, **k: {"address": {"town": "District of North Vancouver"}}) == "North Vancouver")
legs = {"legs": [("Kingsway", 3.0, (49.21, -122.9)), ("Hwy 1", 9.0, (49.21, -122.85)), ("Hwy 15", 6.0, (49.24, -122.75)), ("80 Avenue", 2.0, (49.25, -122.71))]}
via = tr.via_line(legs, get=lambda url, params=None: {"address": {"city": "Burnaby" if float(params["lat"]) < 49.22 else "Surrey"}})
ok("'Via:' the roads in order, naming the city when the route enters another one", via == "Via: Kingsway (Burnaby) > Hwy 1 > Hwy 15 (Surrey) > 80 Avenue", via)
many = ["CLOSED Hwy 1", "Slow Hwy 1 near Langley 8 km +7 min", "Slow Hwy 1 near Langley 3 km +2 min", "Roadwork Bridge Approach Hwy 1 (Abbotsford)",
        "Roadwork Hwy 1 (Chilliwack)"]
w = tr.way_lines(many)
ok("a long 'On the way': whole items over two messages, none cut off", len(w) == 2 and w[1].startswith("More on the way: ") and all(len(x) <= 115 for x in w)
   and sum(x.count("; ") + 1 for x in w) == 5 and not any(x.endswith("...") for x in w), w)
w = tr.way_lines([f"Roadwork Hwy 1 Exit {n} to Exit {n + 2}" for n in range(12)], " (from the last DriveBC check)")
ok("...all of it listed, over as many messages as it takes (none counted away), the note kept", sum(x.count("; ") + 1 for x in w) == 12
   and "more" not in w[-1].replace("More on the way", "") and w[-1].endswith("(from the last DriveBC check)") and all(len(x) <= 115 for x in w), w)
w = tr.way_lines([f"Roadwork Hwy 1 Exit {n} to Exit {n + 2}" for n in range(60)])
ok("...past 8 messages, the rest is counted", len(w) == 8 and w[-1].endswith("more") and all(len(x) <= 115 for x in w), w[-1])
import emergency_agent as _ea
fixed = _ea.fix_drivebc_text({"description": "Paving at stal¿¿¿¿w¿¿as¿¿m Bridge", "roads": [{"from": "Odd¿¿ Rd"}], "n": 3})
ok("DriveBC's broken letters: the bridge's real name back, other '¿' runs dropped", fixed == {"description": "Paving at stal̓əw̓asəm Bridge",
   "roads": [{"from": "Odd Rd"}], "n": 3}, ascii(fixed))
ok("DriveBC's cross streets: 'from X to Y' / 'at X', the town and the road itself left out", [tr.cross_streets(d, r) for d, r in (
   ("Utility work from Highway 11, In Abbotsford and At Hazelwood Avenue to In Abbotsford and At Valley Road. Starting Thu", "Highway 11"),
   ("Utility work from Highway 7, In Maple Ridge and Jim Robson Way to In Maple Ridge and 240th Street. Starting", "Highway 7"),
   ("Construction work at Highway 15, In Surrey and At Fraser Hwy. Starting Fri", "Highway 15"),
   ("Washout at Silver Skagit Road, In Hope. Last update", "Silver Skagit Road"), ("Bridge maintenance. Starting Thu", "Highway 91A"))]
   == ["Hazelwood Ave to Valley Rd", "Jim Robson Way to 240th St", "at Fraser Hwy", "", ""])
e = tr.drivebc_events([HOME, DEST], get=lambda *a, **k: {"events": [
    {"id": "b", "event_type": "CONSTRUCTION", "severity": "MAJOR", "description": "Bridge construction. Starting Mon Mar 9.", "roads": [{"name": "Other Roads", "from": "Mt Lehman Road"}],
     "geography": {"type": "Point", "coordinates": [-122.8, 49.3]}},
    {"id": "u", "event_type": "CONSTRUCTION", "severity": "MAJOR", "description": "Paving from Highway 1, In Langley and At 200 Street to In Langley and At 232 Street. Starting",
     "roads": [{"name": "Highway 1"}], "geography": {"type": "Point", "coordinates": [-122.8, 49.3]}}]})
ok("...'Other Roads': the street from its own field ('Mt Lehman Rd', not 'Bridge construction')", [short_ := tr.short_street(x["road"]) for x in e][0] == "Mt Lehman Rd"
   and e[1]["at"] == "200 St to 232 St", e)
ok("every message fits one mesh message (115 characters)", all(len(p) <= 115 for p in tr.answer(HOME, "Mall", get=fake(osrm(
   (20, 25, "A very long road name number one", 49.3)))[0], origin_age=None)))

# ---- live traffic with a TomTom key: each route's time includes its slow traffic now; the jams are named; no key, no TomTom
TT_PTS = [HOME, (49.25, -122.85), (49.30, -122.80), (49.275, -122.75), DEST]        # along the Hwy 1 route (middle at 49.30)
def tomtom(delay, kind="JAM"):
    return {"routes": [{"legs": [{"points": [{"latitude": a, "longitude": o} for a, o in TT_PTS]}],
                        "guidance": {"instructions": [{"pointIndex": 0, "roadNumbers": ["TCH 1", "BC 1"], "street": "Trans-Canada Hwy"}]},
                        "sections": [{"sectionType": "TRAFFIC", "simpleCategory": kind, "startPointIndex": 1, "endPointIndex": 3, "delayInSeconds": delay}]}]}
def with_tomtom(get, answer):
    tt = []
    def g(url, params=None):
        if "tomtom" in url:
            tt.append(params)
            if isinstance(answer, Exception): raise answer
            return answer
        return get(url, params)
    return g, tt
g, tt = with_tomtom(fake(osrm((20, 25, "Hwy 1", 49.30), (22, 40, "Hwy 7", 49.10)))[0], tomtom(300))
r = parts(tr.answer(HOME, "Mall", get=g, tomtom_key=" k3y "))
ok("TomTom key: the route's time with the traffic on it now", r["route"] == "Route to Mall, Burnaby: 20 km, ~30 min (+5 min traffic now)" and tt[0]["key"] == "k3y", (r, tt))
ok("...and the slow traffic on the way: road, town, length, delay", r["way"].startswith("On the way: Slow Hwy 1 near Surrey") and r["way"].endswith("km +5 min"), r)
g, _ = with_tomtom(fake(osrm((20, 25, "Hwy 1", 49.30), (22, 27, "Hwy 7", 49.10)))[0], tomtom(600))
r = parts(tr.answer(HOME, "Mall", get=g, tomtom_key="k3y"))
ok("...a jam that makes the usual route slower: the quicker one now, saying why", r.get("via", "").startswith("Via: Hwy 7")
   and r["route"] == "Route to Mall, Burnaby: 22 km, ~27 min (avoids slow traffic)", r)
# where on a long highway: the nearest freeway exit (OpenStreetMap), else the town
EXITS = {"elements": [{"type": "node", "lat": 49.251, "lon": -122.851, "tags": {"ref": "58"}},
                      {"type": "way", "tags": {"destination": "200 Street North;Langley", "destination:ref": "1 West"}},
                      {"type": "way", "tags": {"destination": "Hwy 1 East;Hope"}},
                      {"type": "node", "lat": 49.301, "lon": -122.801, "tags": {"ref": "66"}},
                      {"type": "way", "tags": {"destination": "HOV 232 St;Fort Langley"}}]}
def with_exits(get, answer=EXITS):
    def g(url, params=None):
        if "overpass" in url:
            if isinstance(answer, Exception): raise answer
            return answer
        return get(url, params)
    return g
tr._exits.pop("_test", None)
g, _ = with_tomtom(fake(osrm((20, 25, "Hwy 1", 49.30)), events=[ev(1, "CONSTRUCTION", "Highway 1. Bridge work.", 49.30)])[0], tomtom(300))
r = parts(tr.answer(HOME, "Mall", get=with_exits(g), tomtom_key="k3y"))
ok("on a freeway: slow traffic from the nearest exit, with the street it leads to", "Slow Hwy 1 from exit 58 (200 St) 11 km +5 min" in r["way"], r)
ok("...DriveBC's roadwork too ('HOV' and directions left out)", "Roadwork Hwy 1 exit 66 (232 St)" in r["way"], r)
ok("...never the highway itself as the cross street", tr.exit_label(("171", ["Hwy 1"]), "Hwy 1") == "exit 171" and tr.exit_label(("", ["Fraser Hwy"]), "Hwy 1") == "at Fraser Hwy")
tr._exits.pop("_test", None)
r = parts(tr.answer(HOME, "Mall", get=with_exits(g, OSError("504")), tomtom_key="k3y"))
ok("...exits not available (servers busy): the town instead", "Slow Hwy 1 near Surrey" in r["way"] and "Roadwork Hwy 1" in r["way"], r)
tr._exits.pop("_test", None)
two = tomtom(300); two["routes"].append(dict(two["routes"][0], sections=[dict(two["routes"][0]["sections"][0], startPointIndex=2, delayInSeconds=240)]))
g, _ = with_tomtom(fake(osrm((20, 25, "Hwy 1", 49.30)))[0], two)
r = parts(tr.answer(HOME, "Mall", get=g, tomtom_key="k3y"))
ok("...the same jam on two of TomTom's routes: named once, its delay counted once", r["way"].count("Slow") == 1 and "(+5 min traffic now)" in r["route"], r)
g, _ = with_tomtom(fake(osrm((20, 25, "Hwy 1", 49.30)))[0], tomtom(30))
r = parts(tr.answer(HOME, "Mall", get=g, tomtom_key="k3y"))
ok("...under a minute of slow traffic isn't mentioned", "(traffic flowing now)" in r["route"] and "no closures, incidents, roadwork or slow traffic" in r["way"], r)
g, _ = with_tomtom(fake(osrm((20, 25, "Hwy 1", 49.30)))[0], OSError("403 for url ...?key=k3y"))
r = tr.answer(HOME, "Mall", get=g, tomtom_key="k3y")
ok("...TomTom not answering: the route anyway, saying times are without congestion - the key never in an answer",
   "TomTom didn't answer" in parts(r)["way"] and not any("k3y" in x for x in r), r)
g, tt = with_tomtom(fake(osrm((20, 25, "Hwy 1", 49.30)))[0], tomtom(300))
tr.answer(HOME, "Mall", get=g)
ok("...no key: TomTom is never asked", tt == [])

# ---- in the addon: private only, never repeated in a channel, one per person every 2 minutes, nothing in the log
spec = importlib.util.spec_from_file_location("t_ba_route", os.path.join(PKG, "broadcast_alerts.py"))
ba = importlib.util.module_from_spec(spec); spec.loader.exec_module(ba)
class Nodes:
    def find_by_prefix(self, p): return {"lat": HOME[0], "lon": HOME[1], "lastmod": int(time.time()) - 7200} if p == "aabbcc" else None
    def find_by_name(self, n): return None
class API:
    def __init__(self): self.s, self.replies, self.nodes, self.bg = {"route_on": True}, [], Nodes(), []
    def get(self, k, d=None): return self.s.get(k, d)
    def reply(self, msg, text, private=None): self.replies.append((msg["channel"], text, private))
    def after(self, ms, fn): fn()
    def run_background(self, fn, done): self.bg.append(fn); done(["Route to Mall: 20 km", "On the way: nothing", "Start: ..."])
    def reply_delays(self, node=None): return 0.0, 3.0
b = ba.Addon.__new__(ba.Addon); b.api = API(); b.route_last = {}
dm = {"channel": "@Ann", "nick": "Ann", "text": "route 1 Main St, Burnaby", "dm": True, "raw": {"pubkey_prefix": "aabbcc"}}
b.on_message(dm)
ok("a private 'route <address>': answered privately (route, what is on the way, where it starts)", b.api.replies == [("@Ann", "Route to Mall: 20 km", True),
   ("@Ann", "On the way: nothing", True), ("@Ann", "Start: ...", True)], b.api.replies)
pos = b._position(dm)
ok("...from the position the asker's node advertises, with the advert's age (by our node's clock)", pos[:2] == HOME and 7190 <= pos[2] <= 7210, pos)
b.api.replies.clear(); b.on_message(dm)
ok("...one route per person every 2 minutes", len(b.api.replies) == 1 and "every 2 minutes" in b.api.replies[0][1] and len(b.api.bg) == 1, b.api.replies)
b.api.replies.clear()
b.on_message({"channel": "#buds", "nick": "Bob", "text": "!route 5 Secret Lane, Hometown", "dm": False})
ok("asked in a channel: no route, only a private hint - the address is never repeated", len(b.api.replies) == 1 and b.api.replies[0][2] is True
   and "Secret Lane" not in b.api.replies[0][1] and "private message" in b.api.replies[0][1] and len(b.api.bg) == 1, b.api.replies)
b.api.replies.clear(); b.api.s["route_on"] = False; b.on_message(dict(dm, nick="Cy"))
ok("off until switched on in its settings", b.api.replies == [] and b.route_help("#x") == [])
b.api.s["route_on"] = True
ok("bothelp lists it as a private-message command", b.route_help("#buds") == ["route <address> (private message)"])
for key in ("", "k3y"):
    b.api.s["tomtom_key"] = key; b.api.bg.clear(); b.route_last.clear(); b.on_message(dm)
    with mock.patch.object(tr, "answer", lambda *a, **k: k) as _: given = b.api.bg[0]()
    ok(f"the TomTom key from its settings goes to the route ({key or 'none: as before'})", given.get("tomtom_key") == key, given)
b.api.s.pop("tomtom_key")
import gui_diag
snap = gui_diag.settings_snapshot({"addons": {"broadcast_alerts": {"tomtom_key": "k3y"}}})
ok("...and is never shown in a bug report's settings (only that it is set)", "k3y" not in snap and "tomtom_key = (set)" in snap, snap)
with mock.patch.object(ba.logging, "warning") as w:
    b2 = ba.Addon.__new__(ba.Addon); b2.api = API(); b2.route_last = {}
    b2.api.run_background = lambda fn, done: done(RuntimeError("HTTP 500 for url ...q=5+Secret+Lane"))
    b2.on_message(dict(dm, nick="Dee", text="route 5 Secret Lane"))
# DriveBC busy: the incidents the traffic check already tracks (its areas) are used, and the answer says so
ea = ba.ea
with mock.patch.dict(ea.active_traffic_alerts, {"DriveBC|x1": ("DriveBC", "INCIDENT - Highway 1 (Burnaby)")}, clear=True), \
        mock.patch.dict(ea.ALERT_LOCATIONS, {"DriveBC|x1": (49.30, -122.80, "Highway 1")}, clear=True):
    known = b._known_events()
    get, _ = fake(osrm((20, 25, "Hwy 1", 49.30)), drivebc_error=RuntimeError("429"))
    r = parts(tr.answer(HOME, "Mall", get=get, known=b._known_events))
ok("DriveBC busy: the incidents the traffic check already has are used - and it says so", known and known[0]["what"] == "Incident"
   and r["way"] == "On the way: Incident Hwy 1 (Burnaby) (from the last DriveBC check)", (known, r))
ok("a failed lookup is logged without the address", w.called and "Secret" not in str(w.call_args) and "try again" in b2.api.replies[-1][1], w.call_args)
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
