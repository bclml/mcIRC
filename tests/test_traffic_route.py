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
        k = "via" if line.startswith("Via:") else "start" if line.startswith("Start:") else "way" if line.startswith(("On the way", "Traffic:")) else "route"
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
   and r["way"] == "On the way: Incident Highway 1", r)
get, _ = fake(osrm((20, 25, "Hwy 1", 49.30), (30, 40, "Hwy 7", 49.10)), [ev(1, "INCIDENT", "Washout at Hwy 1. Closed.", 49.30)])
r = parts(tr.answer(HOME, "Mall", get=get))
ok("a full closure on the quickest route: the open one, saying why", r.get("via", "").startswith("Via: Hwy 7") and "avoids 1 closure" in r["route"], r)
get, _ = fake(osrm((20, 25, "Hwy 1", 49.30)), [ev(1, "CONSTRUCTION", "Paving at Hwy 1. Left lane closed.", 49.30, sev="MINOR"),
                                                ev(2, "CONSTRUCTION", "Bridge work at Hwy 1.", 49.30), ev(3, "INCIDENT", "Crash far away.", 50.5)])
r = parts(tr.answer(HOME, "Mall", get=get))
ok("on the way: major roadwork; minor lane work and events off the route left out", r["way"] == "On the way: Roadwork Highway 1", r)
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
   {"ref": "TCH 1;BC 1"}, {"ref": "BC 99"}, {"ref": "BC 17A"}, {"ref": "I-5"}, {"name": "Kingsway"})] == ["Hwy 1", "Hwy 99", "Hwy 17A", "I-5", "Kingsway"])
legs = {"legs": [("Kingsway", 3.0, (49.21, -122.9)), ("Hwy 1", 9.0, (49.21, -122.85)), ("Hwy 15", 6.0, (49.24, -122.75)), ("80 Avenue", 2.0, (49.25, -122.71))]}
via = tr.via_line(legs, get=lambda url, params=None: {"address": {"city": "Burnaby" if float(params["lat"]) < 49.22 else "Surrey"}})
ok("'Via:' the roads in order, naming the city when the route enters another one", via == "Via: Kingsway (Burnaby) > Hwy 1 > Hwy 15 (Surrey) > 80 Avenue", via)
ok("every message fits one mesh message (115 characters)", all(len(p) <= 115 for p in tr.answer(HOME, "Mall", get=fake(osrm(
   (20, 25, "A very long road name number one", 49.3)))[0], origin_age=None)))

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
   and r["way"] == "On the way: Incident Highway 1 (Burnaby) (from the last DriveBC check)", (known, r))
ok("a failed lookup is logged without the address", w.called and "Secret" not in str(w.call_args) and "try again" in b2.api.replies[-1][1], w.call_args)
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
