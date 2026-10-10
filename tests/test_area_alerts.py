import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "packages", "area_alerts")
sys.path.insert(0, ROOT); sys.path.insert(0, PKG); os.chdir(ROOT)
"""Area alerts: places (country, region, area), the sources (GDACS, USGS, NOAA tsunami, NWS, MeteoAlarm) and the addon's checking and
broadcasting.  No radio, no internet (stand-ins for every feed)."""
import importlib.util, time
from unittest import mock
import tkinter as tk

for m in ("aa_sources", "aa_places", "aa_world", "aa_transit", "aa_transit_feeds", "aa_traffic"): sys.modules.pop(m, None)     # an installed copy next to the app must not shadow the package's
import aa_places as places
import aa_sources as src
import aa_traffic as traffic
import aa_transit as transit

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

# ---- places
names = dict(places.countries())
ok("every country of the world can be chosen", len(names) > 240 and names.get("Japan") == "JP" and names.get("Brazil") == "BR", len(names))
ok("...then its regions", "California" in places.regions("US") and "Bavaria" in places.regions("DE"))
ok("...then its areas, the biggest towns first", places.areas("US", "California")[0][0] == "Los Angeles")
ok("Canada also has the Traffic, transit and weather addon's areas (Lower Mainland ...)", places.areas("CA", "British Columbia")[0][0] == "Lower Mainland")
lyon = places.make("FR", "Auvergne-Rhône-Alpes", "Lyon")
ok("a chosen area keeps what the sources need (position, district)", lyon and lyon["district"] == "Rhône" and abs(lyon["lat"] - 45.75) < 0.1, lyon)
ok("...and reads as 'town, region, country'", places.label(lyon) == "Lyon, Auvergne-Rhône-Alpes, France")
ok("an area that isn't in the list is refused", places.make("FR", "Auvergne-Rhône-Alpes", "Atlantis") is None)
la = places.make("US", "California", "Los Angeles")

# ---- sources
def feed(data): return lambda url, params=None, **k: data
quake = {"type": "Feature", "id": "ci1", "properties": {"mag": 5.4, "place": "10 km N of Ridgecrest, CA"}, "geometry": {"coordinates": [-117.6, 35.7, 8]}}
got = src.usgs(la, get=feed({"features": [quake]}))
ok("USGS: an earthquake near the area, with its distance", len(got) == 1 and got[0].id == "usgs:ci1" and got[0].text.startswith("Earthquake M5.4: 10 km N of Ridgecrest")
   and "km from Los Angeles" in got[0].text, got)

def gd(kind, level, lon, lat, eid=1): return {"properties": {"eventtype": kind, "alertlevel": level, "eventid": eid, "name": f"Event {eid}"},
                                              "geometry": {"coordinates": [lon, lat]}}
events = {"features": [gd("TC", "Orange", -118.5, 33.0, 1), gd("FL", "Red", 140.0, 35.0, 2), gd("EQ", "Green", -118.3, 34.0, 3)]}
got = src.gdacs(la, "orange", get=feed(events))
ok("GDACS: only events near the area, from the chosen level up", [a.id for a in got] == ["gdacs:TC:1:Orange"] and "tropical cyclone" in got[0].text, got)
ok("...a level up the same event is a new alert", src.gdacs(la, "orange", get=feed({"features": [gd("TC", "Red", -118.5, 33.0, 1)]}))[0].id == "gdacs:TC:1:Red")

def nw(i, event, vtec="", status="Actual", mtype="Alert", ends="2099-01-01T00:00:00-08:00"):
    return {"properties": {"id": i, "event": event, "severity": "Severe", "status": status, "messageType": mtype, "ends": ends,
                           "parameters": {"VTEC": [vtec]} if vtec else {}}}
asked = []
nws = {"features": [nw("urn:1", "Excessive Heat Warning", "/O.NEW.KLOX.EH.W.0007.261010T1800Z-261011T0300Z/"),
                    nw("urn:2", "Test Message", status="Test"), nw("urn:3", "Wind Advisory", mtype="Cancel"),
                    nw("urn:4", "Frost Advisory", ends="2001-01-01T00:00:00Z")]}
got = src.weather(la, get=lambda url, params=None, **k: asked.append(params) or nws)
ok("US weather: the National Weather Service's real alerts for the point (no test messages, cancellations or ended ones)",
   [a.text for a in got] == ["Excessive Heat Warning - Los Angeles (Severe, NWS)"] and asked[0].get("status") == "actual", (got, asked))
upd = {"features": [nw("urn:9", "Excessive Heat Warning", "/O.EXT.KLOX.EH.W.0007.261010T1800Z-261011T0600Z/")]}
ok("...an updated warning keeps its id (its event number), so it isn't sent again", src.weather(la, get=feed(upd))[0].id == got[0].id == "nws:KLOX.EH.W.0007")
quakes = {"features": [{"id": "x1", "properties": {"mag": None, "place": "?"}, "geometry": {"coordinates": [-118, 34]}},
                       {"id": "x2", "properties": {"mag": 5.1, "place": None}, "geometry": None}, quake]}
ok("USGS: an earthquake missing its magnitude or position is skipped, not the area's other quakes", [a.id for a in src.usgs(la, get=feed(quakes))] == ["usgs:ci1"])

def ma(ident, area, level, event="Moderate rain warning", lang="en-GB"):
    return {"alert": {"identifier": ident, "info": [{"language": lang, "event": event, "area": [{"areaDesc": area}],
                                                     "parameter": [{"valueName": "awareness_level", "value": level}]}]}}
old = ma("d", "Rhône", "3; orange; Severe", "Old storm warning"); old["alert"]["info"][0]["expires"] = "2001-01-01T00:00:00+00:00"
cancel = ma("e", "Rhône", "3; orange; Severe", "Cancelled warning"); cancel["alert"]["msgType"] = "Cancel"
warnings = {"warnings": [ma("a", "Rhône", "2; yellow; Moderate"), ma("b", "Rhône", "1; green; Minor"), ma("c", "Gironde", "3; orange; Severe"), old, cancel]}
got = src.weather(lyon, get=feed(warnings))
ok("Europe (MeteoAlarm): the warnings in force for the area's district (accents ignored); green, expired and cancelled ones left out",
   [a.text for a in got] == ["YELLOW Moderate rain warning - Lyon (MeteoAlarm)"], got)
ok("...district names match as whole words ('Kreis Biberach' is Biberach, not 'Biberachstadt')",
   src._names_match({src._core("Kreis Biberach")}, "Landkreis Biberach") and not src._names_match({src._core("Kreis Biberach")}, "Biberachstadt"))
ok("countries without an official feed here have no weather warnings (disasters and earthquakes still)", src.weather(places.make("JP", places.regions("JP")[0],
   places.areas("JP", places.regions("JP")[0])[0][0]), get=lambda *a, **k: 1 / 0) == [])

def entry(eid, title, category, region, note=""):     # as NOAA's Atom feeds have them: the title is only the region, the category in the summary
    return (f"<entry><id>{eid}</id><title>{title}</title><summary type=\"xhtml\">&lt;strong&gt;Category:&lt;/strong&gt; {category} &lt;br/&gt;"
            f"&lt;strong&gt;Affected Region:&lt;/strong&gt; {region} &lt;br/&gt; Note: * {note}</summary></entry>")
atom = "<feed>" + "".join([
    entry("urn:t1", "Coastal California", "Warning", "Coastal areas of California and Oregon"),
    entry("urn:t2", "in Panama", "Information", "in Panama", "There is no tsunami danger for the U.S. West Coast, California or Alaska."),
    entry("urn:t3", "Alaska Peninsula", "Warning", "Alaska Peninsula", "There is no tsunami danger for the U.S. West Coast, California or Hawaii."),
    entry("urn:t4", "Andaman Sea", "Advisory", "Indian Ocean coasts")]) + "</feed>"
got = src.tsunami(la, get=lambda url, **k: atom)
ok("tsunami: a warning naming the area's region (the category read from the summary, as in the real feeds)",
   [a.id for a in got] == ["tsunami:urn:t1:warning"] * 2 and got[0].text == "TSUNAMI WARNING: Coastal areas of California and Oregon", got)
ok("...information statements, and 'no tsunami danger for ...' notes, don't count", all(a.id.startswith("tsunami:urn:t1") for a in got))
port_blair = places.make("IN", "Andaman and Nicobar", "Port Blair") or {"country": "IN", "country_name": "India", "region": "Andaman and Nicobar", "name": "Port Blair", "lat": 11.6, "lon": 92.7}
ok("...names match whole words ('Indian Ocean' is not India)", src.tsunami(port_blair, get=lambda url, **k: atom) == [])

# ---- public transit (GTFS-realtime service alerts)
from google.transit import gtfs_realtime_pb2
ok("the Mobility Database's transit alert feeds are there, worldwide", len(transit.feeds()) > 400 and len({f["cc"] for f in transit.feeds()}) > 20)
edm = places.make("CA", "Alberta", "Edmonton")
ok("an area finds the agencies serving it", any("Edmonton" in f["provider"] for f in transit.feeds_for(edm)))
keyed = next(f for f in transit.feeds() if f["auth"] == 1 and f["info"] and f["param"])
ok("a feed needing a key says, in plain words, where to get the free key and how it is used",
   keyed["info"] in transit.key_help(keyed) and "free key" in transit.key_help(keyed) and keyed["param"] in transit.key_help(keyed))
def pb(*alerts):
    m = gtfs_realtime_pb2.FeedMessage(); m.header.gtfs_realtime_version = "2.0"
    for i, (head, effect, routes, period) in enumerate(alerts):
        e = m.entity.add(); e.id = str(i)
        if effect is not None: e.alert.effect = effect
        e.alert.header_text.translation.add(text=head, language="en")
        for r in routes: e.alert.informed_entity.add(route_id=r)
        if period: e.alert.active_period.add(start=period[0], end=period[1])
    return m.SerializeToString()
feed = {"id": "t-1", "provider": "Metro Transit (MT)", "name": "", "auth": 0, "url": "https://x", "param": "", "info": ""}
data = pb(("Blue line suspended between A and B", 8, ["B1"], None), ("Blue line suspended between A and B", 8, ["B2"], None),
          ("Elevator at Main St out of service", 8, [], None), ("Route 7 detour on 5th Ave", 4, ["7"], None),
          ("No service on Route 9", 1, ["9"], (2000, 3000)), ("Major delays on the Red line", 3, [], None))
got = transit.alerts(feed, get=lambda f, k: data, now=1000)
ok("transit: service stops and big delays in force now; the same alert for several routes once; lifts, detours, future alerts left out",
   [a.text for a in got] == ["MT: Blue line suspended between A and B (routes B1, B2)", "MT: Significant delays - Major delays on the Red line"], got)
ok("...with 'all their alerts' the detours and lifts too", len(transit.alerts(feed, all_effects=True, get=lambda f, k: data, now=1000)) == 4)
ok("...an alert keeps its id from one run to the next", got[0].id == transit.alerts(feed, get=lambda f, k: data, now=1000)[0].id
   and "hash" not in transit.alerts.__code__.co_names)
try:
    import requests
    with mock.patch.object(requests, "get", side_effect=requests.ConnectionError("failed: https://x?api_key=SECRET123")):
        transit._fetch(dict(keyed, url="https://x"), "SECRET123")
    leaked = None
except Exception as e: leaked = str(e)
ok("a failing feed's error never shows the key", leaked is not None and "SECRET123" not in leaked, leaked)

# ---- traffic
ab = places.make("CA", "Alberta", "Edmonton")
site = traffic.site_for(ab)
ok("traffic: Alberta's area uses 511 Alberta, and says how to get its free developer key", site[0] == "511.alberta.ca"
   and "https://511.alberta.ca/my511/register" in traffic.key_help(site) and "https://511.alberta.ca/developers/doc" in traffic.key_help(site))
ok("...a 511 site without a public developer page says to ask through its Contact page", "Contact page" in traffic.key_help(traffic.SITES[("US", "Florida")]))
ok("...BC needs no key (DriveBC); Quebec has no open feed", traffic.available(places.make("CA", "British Columbia", "Lower Mainland")).startswith("DriveBC")
   and "no open feed" in traffic.available({"country": "CA", "region": "Quebec"}))
ev = [{"ID": 1, "EventType": "closures", "IsFullClosure": True, "RoadwayName": "Hwy 16", "Description": "Hwy 16 closed both ways", "Latitude": 53.6, "Longitude": -113.6},
      {"ID": 2, "EventType": "roadwork", "IsFullClosure": False, "RoadwayName": "Hwy 2", "Description": "Lane closed", "Latitude": 53.5, "Longitude": -113.5},
      {"ID": 3, "EventType": "accidentsAndIncidents", "IsFullClosure": False, "RoadwayName": "Hwy 1", "Description": "Crash", "Latitude": 51.0, "Longitude": -114.0}]
asked = []
got = traffic.events_511(ab, "K", get=lambda url, params, key="": asked.append((url, params["key"])) or ev)
ok("...511: closures near the area; roadwork (unless asked) and far-away incidents left out", [a.text for a in got] == ["FULL CLOSURE: Hwy 16 closed both ways"]
   and asked == [("https://511.alberta.ca/api/v2/get/event", "K")], (got, asked))
ok("...no key, no request", traffic.events_511(ab, "", get=lambda *a: 1 / 0) == [])
lm = places.make("CA", "British Columbia", "Lower Mainland")
dbc = {"events": [{"id": "a", "event_type": "INCIDENT", "severity": "MAJOR", "description": "Crash at Hwy 1. Closed.", "roads": [{"name": "Highway 1"}]},
                  {"id": "b", "event_type": "CONSTRUCTION", "severity": "MINOR", "description": "Paving. Left lane closed.", "roads": [{"name": "Highway 7"}]},
                  {"id": "c", "event_type": "CONSTRUCTION", "severity": "MAJOR", "description": "Bridge work. Closed.", "roads": [{"name": "Other Roads"}],
                   "schedule": {"intervals": ["2099-01-01T09:00/2099-01-01T15:00"]}}]}
got = traffic.drivebc(lm, get=lambda url, params, key="": dbc)
ok("...DriveBC: real closures on now ('Closed.'), not lane closures, not ones scheduled later", [a.text for a in got] == ["CLOSED: Highway 1 - Crash at Hwy 1. Closed."], got)

# ---- the addon
spec = importlib.util.spec_from_file_location("t_area_alerts", os.path.join(PKG, "area_alerts.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

class API:
    def __init__(self):
        self.s, self.sent, self.lines, self.notes, self.connected = {}, [], [], [], True
    def get(self, k, d=None): return self.s.get(k, d)
    def set(self, k, v): self.s[k] = v
    def add_menu_item(self, label, fn): pass
    def log(self, text, level="info"): self.notes.append(text)
    def notice(self, text, level="info"): self.notes.append(text)
    def write(self, window, text, tag="text"): self.lines.append((window, text))
    def send(self, channel, text): self.sent.append((channel, text))
    def run_background(self, fn, done=None): done(fn())
    def after(self, ms, fn): pass

api = API()
bot = mod.Addon(api); bot.on_load()
ok("off until switched on: nothing is checked", (bot.on_tick(), bot.last_check)[1] == 0.0)
ok("the toolbar has its ON/OFF switch", mod.Addon.switch == "enabled")
in_force = [src.Alert("q1", "quakes", "Earthquake M5.4: near LA", "USGS"), src.Alert("w1", "weather", "Heat Warning - Los Angeles (Severe, NWS)", "NWS")]
mod.src.SOURCES = dict(src.SOURCES, weather=lambda a: [x for x in in_force if x.kind == "weather"])
mod.src.usgs = lambda a, m, r: [x for x in in_force if x.kind == "quakes"]
mod.src.gdacs = lambda a, lvl: []
mod.src.tsunami = lambda a: []
mod.src.SOURCES["tsunami"] = mod.src.tsunami
api.s.update(enabled=True, broadcast=True, areas=[la], kinds={"quakes": True, "weather": True, "disasters": True, "tsunami": False})
bot.on_tick()
ok("switched on, the first check shows what is already in force on this PC, and broadcasts none of it",
   len(api.lines) == 2 and all(w == "Area alerts" and t.startswith("(in force) ") for w, t in api.lines) and api.sent == [], (api.lines, api.sent))
in_force += [src.Alert("w2", "weather", "Wind Warning - Los Angeles (Moderate, NWS)", "NWS"), src.Alert("q2", "quakes", "Earthquake M6.0: off the coast", "USGS")]
bot.check()
ok("new alerts are shown and broadcast: the first at once, the rest waiting", len(api.sent) == 1 and len(bot.queue) == 1, api.sent)
bot.drain()
ok("...at most one every 30 seconds", len(api.sent) == 1)
bot.sent_times = [time.time() - 31]; bot.drain()
ok("...the next after the gap; each kind to its own channel (weather to #weather, earthquakes to #alerts)", sorted(api.sent) == [
   ("#alerts", "Earthquake M6.0: off the coast"), ("#weather", "Wind Warning - Los Angeles (Moderate, NWS)")] and not bot.queue, api.sent)
n = len(api.sent); bot.check()
ok("an alert already seen is not sent again", len(api.sent) == n)
bot.sent_times = [time.time() - 100 - i * 60 for i in range(10)]
bot.queue = [src.Alert("x", "weather", "x", "NWS")]; bot.drain()
ok("...and no more than 10 an hour", len(api.sent) == n and bot.queue)
bot.queue.clear(); api.s["broadcast"] = False
in_force.append(src.Alert("w3", "weather", "Flood Watch - Los Angeles (Moderate, NWS)", "NWS"))
bot.check()
ok("with 'Broadcast to the mesh' off, new alerts only show on this PC", len(api.sent) == n and api.lines[-1][1].startswith("Flood Watch") and not bot.queue)
# transit and traffic in the addon: only the agencies ticked; a feed needing a key is skipped until there is one
asked = []
mod.transit.alerts = lambda f, key, all_: asked.append((f["id"], key)) or [src.Alert("t:" + f["id"], "transit", f"{f['provider']}: Line 1 suspended", f["provider"])]
open_feed = next(f for f in transit.feeds() if not f["auth"])
api.s.update(kinds={"transit": True}, transit_feeds=[open_feed["id"], keyed["id"]], keys={}, broadcast=True, channels={})
bot.queue.clear(); bot.sent_times = []; n = len(api.sent)
bot.check()
ok("transit: the agencies ticked are checked; one needing a key is skipped until it has one", asked == [(open_feed["id"], "")], asked)
ok("...its alerts go to #transit", api.sent[n:] == [("#transit", f"{open_feed['provider']}: Line 1 suspended")], api.sent[n:])
api.s["keys"] = {f"transit:{keyed['id']}": "K1"}; asked.clear(); bot.check()
ok("...with its key, it is checked too", (keyed["id"], "K1") in asked, asked)
# more than one channel per kind / agency / road source
api.s["channels"] = {"weather": "#weather, #mcirc public #Weather"}
ok("a channel box can hold several channels: each once, never Public", bot.channels_for(src.Alert("w", "weather", "x", "")) == ["#weather", "#mcirc"])
api.s["broadcast"] = True; bot.queue = [src.Alert("w7", "weather", "Storm", "NWS")]; bot.sent_times = []; n = len(api.sent)
bot.drain()
ok("...the alert goes to each of them (each one transmission toward the hourly limit)", api.sent[n:] == [("#weather", "Storm"), ("#mcirc", "Storm")]
   and len(bot.sent_times) == 2, api.sent[n:])
bot.sent_times = [time.time() - 3000 + i for i in range(9)]; bot.queue = [src.Alert("w8", "weather", "Storm 2", "NWS")]; n = len(api.sent)
bot.drain()
ok("...and it waits when the hour's limit can't take every channel", len(api.sent) == n and bot.queue)
bot.queue.clear(); api.s["broadcast"] = False
# audit fixes: forgetting, new areas, switching off, unloading, the channel cap
root = tk.Tk(); root.withdraw()
api.s.update(enabled=True, broadcast=True, kinds={"weather": True}, channels={}, areas=[la]); bot.queue.clear(); bot.sent_times = []
mod.src.SOURCES["weather"] = lambda a: [src.Alert("ec:Area:SNOWFALL", "weather", "SNOWFALL WARNING", "EC")]
bot.check(); n = len(api.sent)
mod.src.SOURCES["weather"] = lambda a: []
bot.check()
ok("a warning that ended is remembered for a while (a feed hiccup doesn't send it again)", "ec:Area:SNOWFALL" in api.s["seen"])
api.s["seen"]["ec:Area:SNOWFALL"] -= mod.FORGET + 1; bot.check()
mod.src.SOURCES["weather"] = lambda a: [src.Alert("ec:Area:SNOWFALL", "weather", "SNOWFALL WARNING", "EC")]
bot.sent_times = []; bot.check(); bot.drain()
ok("...but when the same kind of warning comes back later, it is announced again", api.sent[-1] == ("#weather", "SNOWFALL WARNING") and len(api.sent) == n + 1, api.sent[n:])
api.s["seen"] = ["old-1", "old-2"]; bot.check()
ok("...(the old 'seen' list is carried over)", isinstance(api.s["seen"], dict) and "old-1" in api.s["seen"])
b6 = mod.Addon(API()); b6.on_load(); b6.api.s.update(enabled=True, broadcast=True, kinds={"weather": True}, areas=[la])
b6.check(); ok("starting mcIRC: the first check only shows (nothing piled up while it was closed is broadcast)", not b6.queue and not b6.api.sent and b6.api.lines)
b6.check(); b6.api.lines.clear(); b6.build_options(tk.Frame(root, bg="#eee")); b6.chosen.append(lyon); b6.apply_options()
mod.src.SOURCES["weather"] = lambda a: [src.Alert("w-" + a["name"], "weather", "Storm " + a["name"], "x")]
b6.check()
ok("adding an area: what is in force there is only shown, not broadcast", not b6.queue and any("(in force) Storm Lyon" in t for _, t in b6.api.lines), b6.api.lines)
b6.queue = [src.Alert("q", "weather", "waiting", "x")]; b6.api.s["enabled"] = False; b6.drain(); b6.on_tick()
ok("switching it off stops broadcasting at once (nothing waiting goes out)", not b6.api.sent and not b6.queue)
mod.src.SOURCES["weather"] = lambda a: [src.Alert("w-new", "weather", "New storm", "x")]
b6.check(force=True)
ok("...'Check now' while off shows what is in force, never sends", not b6.queue and not b6.api.sent and "New storm" in b6.api.lines[-1][1])
b6.api.s["enabled"] = True; b6.on_tick(); b6.quiet_next = False
late = []; b6.api.run_background = lambda fn, done=None: late.append(done)
b6.check(); b6.on_unload(); late[0](([("x", src.Alert("w-late", "weather", "Late", "x"))], []))
ok("unloading: a check still running finds nothing to send to", not b6.queue)
api.s["channels"] = {"weather": " ".join(f"#c{i}" for i in range(12))}
ok("one alert goes to at most 5 channels (the hourly limit can always be kept)", len(bot.channels_for(src.Alert("w", "weather", "x", ""))) == 5)
api.s["channels"] = {}; bot.queue.clear(); api.s["broadcast"] = False
api.s["channels"] = {"weather": "Public"}
ok("a channel can be chosen per kind", bot.channel("weather") == "Public")     # (the core never lets an addon post in Public: test_private_replies)
bot.on_unload()

api2 = API(); b2 = mod.Addon(api2); b2.on_load()
frame = b2.build_options(tk.Frame(root, bg="#eee"))
ok("settings: off and not broadcasting by default", not b2.v_on.get() and not b2.v_bc.get())
b2.c_box.set("France"); b2._fill_regions(); b2.r_box.set("Auvergne-Rhône-Alpes"); b2._fill_areas(); b2.a_box.set("Lyon"); b2._add(); b2._add()
ok("settings: country, then region, then area; added once", [places.label(a) for a in b2.chosen] == ["Lyon, Auvergne-Rhône-Alpes, France"])
b2.v_on.set(True); b2.apply_options()
ok("...saved, with the first check after switching on only showing", api2.s["enabled"] and api2.s["areas"][0]["name"] == "Lyon"
   and b2.quiet_next and api2.s["broadcast"] is False and api2.s["channels"]["weather"] == "#weather")
def labels(page):
    out = []
    def walk(w):
        for c in w.winfo_children():
            if isinstance(c, (tk.Label, tk.Checkbutton)): out.append(str(c.cget("text")))
            walk(c)
    walk(page)
    return out
b2._areas_changed()
ok("settings: the Public transit and Traffic tabs list what serves the chosen areas",
   any("free key" in t or "SYTRAL" in t or "TCL" in t or "Lyon" in t for t in labels(b2.transit_page))
   and any("Lyon" in t and "none found" in t for t in labels(b2.traffic_page)), (labels(b2.transit_page)[:6], labels(b2.traffic_page)))
b3 = mod.Addon(API()); b3.on_load(); b3.api.s["areas"] = [ab]
b3.build_options(tk.Frame(root, bg="#eee"))
b3.key_vars["511:511.alberta.ca"].set("  MYKEY  "); b3.apply_options()
ok("settings: a 511 key box for Alberta, with how to get the free key; the key is saved (trimmed) on this PC",
   b3.api.s["keys"] == {"511:511.alberta.ca": "MYKEY"} and any("my511/register" in t for t in labels(b3.traffic_page)), b3.api.s.get("keys"))
ok("channel names for transit agencies and road sources read like the agencies", transit.slug({"provider": "TransLink Vancouver"}) == "translink"
   and transit.slug({"provider": "BC Transit (Nanaimo)"}) == "bctransit" and transit.slug({"provider": "Edmonton Transit System"}) == "ets"
   and transit.slug({"provider": "Metropolitan Transit Authority (MTA)"}) == "mta" and traffic.slug("drivebc") == "drivebc"
   and traffic.slug("511:511.alberta.ca") == "511alberta")
# an area with more than one transit agency: each its own channel (as TransLink and BC Transit had); one agency: #transit
b4 = mod.Addon(API()); b4.on_load(); b4.api.s["areas"] = [lm, ab]
b4.build_options(tk.Frame(root, bg="#eee"))
lm_feeds = transit.feeds_for(lm)
ok("settings: the Lower Mainland has more than one agency, so each has its own channel", len(lm_feeds) > 1
   and {b4.tch_vars[f["id"]].get() for f in lm_feeds} >= {"#bctransit", "#translink"}, {f["provider"]: b4.tch_vars[f["id"]].get() for f in lm_feeds})
ok("...and with two road sources (DriveBC, 511 Alberta) each has its own channel too",
   b4.rch_vars["drivebc"].get() == "#drivebc" and b4.rch_vars["511:511.alberta.ca"].get() == "#511alberta")
tl = next(f for f in lm_feeds if transit.slug(f) == "translink")
b4.feed_vars[tl["id"]].set(True); b4.tch_vars[tl["id"]].set("#skytrain"); b4.apply_options()
ok("...saved for the agencies ticked (a changed name kept)", b4.api.s["transit_channels"] == {tl["id"]: "#skytrain"}
   and b4.api.s["traffic_channels"] == {"drivebc": "#drivebc", "511:511.alberta.ca": "#511alberta"}, (b4.api.s["transit_channels"], b4.api.s["traffic_channels"]))
b5 = mod.Addon(API()); b5.on_load(); b5.api.s["areas"] = [ab]
b5.build_options(tk.Frame(root, bg="#eee"))
ok("...one agency and one road source: the kind's channels (#transit, #traffic)",
   all(v.get() == "#transit" for v in b5.tch_vars.values()) and b5.rch_vars["511:511.alberta.ca"].get() == "#traffic")
b4.source_of.update({"t9": f"transit:{tl['id']}", "r9": "511:511.alberta.ca", "r8": "drivebc"})
ok("alerts go to their agency's / road source's channel", b4.channel_for(src.Alert("t9", "transit", "x", "")) == "#skytrain"
   and b4.channel_for(src.Alert("r9", "traffic", "x", "")) == "#511alberta" and b4.channel_for(src.Alert("w", "weather", "x", "")) == "#weather")
root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
