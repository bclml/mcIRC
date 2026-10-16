import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
import os; os.environ["MCIRC_NO_LOG_FILE"] = "1"
import sys, json, asyncio, time, types, threading
from unittest import mock
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "packages", "broadcast_alerts"))
import tkinter as tk
import emergency_agent as ea, meshcore_io as io
fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

real = json.load(open(os.path.join(ROOT, "tests", "fixtures", "drivebc_RIDE-100047.json"), encoding="utf-8"))["events"][0]       # the actual DriveBC record for the Hope washout
# ---- map info for the stale Hope incident (town-level point) and for a highway incident
label, detail = ea._drivebc_mapinfo(real, "INCIDENT", "Hope", [])
ok("label names the road and town", label == "INCIDENT - Silver Skagit Road (Hope)", label)
ok("details: severity, state, update time, DriveBC's description", "Minor, all lanes open" in detail and "2026-09-15 20:01" in detail and "Washout at Silver Skagit Road" in detail and "repairs are underway" in detail, detail)
ok("DriveBC's 'Last update / Next update' footer is removed but the text after it is kept", "Last update" not in detail and "Next update" not in detail and "Expect delays in both directions" in detail, detail)
ok("says the location is approximate (only 'near Hope')", "Location approximate: DriveBC only places this event near Hope" in detail, detail)
hw = {"headline": "INCIDENT", "severity": "MAJOR", "updated": "2026-10-03T14:00:00-07:00", "description": "Vehicle incident at Highway 1, In Burnaby. Left lane blocked.",
      "roads": [{"name": "Highway 1", "from": "Kensington Ave", "direction": "W", "state": "SOME_LANES_CLOSED"}]}
l2, d2 = ea._drivebc_mapinfo(hw, "INCIDENT", "Burnaby", [hw["roads"][0]])
ok("a numbered-highway incident is not flagged approximate", "approximate" not in d2 and l2 == "INCIDENT - Highway 1 (Burnaby)", (l2, d2))

# ---- the real parse path, muted and with no radio at all (map-only mode)
ev_hw = dict(hw, id="drivebc.ca/RIDE-999001", status="ACTIVE", schedule={"intervals": ["2026-10-03T00:00/"]}, areas=[{"name": "Lower Mainland District"}],
             geography={"type": "Point", "coordinates": [-122.97, 49.25]}, event_type="INCIDENT", **{"+ivr_message": "Highway 1, In Burnaby."})
real2 = dict(real, **{"+ivr_message": "Silver Skagit Road, In Hope."})
class Resp:
    status_code = 200
    def __init__(self, body): self.body = body
    def json(self): return self.body
def fake_get(url, **kw):
    if "open511" in url and "bbox" in url: return Resp({"events": [real2, ev_hw]})
    raise RuntimeError("other feeds are not reachable in this test")
calls = []
ea.TX["muted"] = True; io.CONNECTION_ARGS = None; io.CHANNEL_INDEX_BY_NAME.clear()
ea.active_traffic_alerts.clear(); ea.ALERT_LOCATIONS.clear(); ea.ALERT_MAPINFO.clear()
with mock.patch("requests.get", fake_get), mock.patch.object(ea, "execute_mesh_command", lambda *a, **k: calls.append(a)), mock.patch.object(io, "execute_mesh_command", lambda *a, **k: calls.append(a)), \
     mock.patch.object(ea, "resolve_channel_indices", lambda *a, **k: calls.append("resolve")):
    asyncio.run(ea.scrape_traffic_feeds())
ok("map-only: both incidents are tracked with their pins", f"DriveBC|{real['id']}" in ea.ALERT_LOCATIONS and "DriveBC|drivebc.ca/RIDE-999001" in ea.ALERT_LOCATIONS, list(ea.ALERT_LOCATIONS))
ok("map info is stored for them", ea.ALERT_MAPINFO[f"DriveBC|{real['id']}"][0] == "INCIDENT - Silver Skagit Road (Hope)")
ok("muted + no radio: nothing is sent and the radio is never asked anything", not calls, calls)

# ---- Traffic, transit and weather 2.0: hands over to Area alerts (installs / switches it on, then itself off - nothing removed)
import importlib.util
def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
ttw = load(os.path.join(ROOT, "packages", "broadcast_alerts", "broadcast_alerts.py"), "t_ttw")
root = tk.Tk()
class HandAPI:
    def __init__(self, installed=False, new_core=True):
        self.calls, self.logs, self._installed = [], [], installed
        if not new_core: del HandAPI.install_addon
    def after(self, ms, fn): pass
    def log(self, text, level="info"): self.logs.append(text)
    def addon_installed(self, name): return self._installed
    def addon_enabled(self, name): return False
    def install_addon(self, name): self.calls.append(("install", name)); self._installed = True; return "2.0.0"
    def set_addon_enabled(self, name, on): self.calls.append(("enabled", name, on))
h = HandAPI(); t = ttw.Addon(h); t.hand_over()
ok("Traffic, transit and weather 2.0: installs Area alerts (from the packages that come with mcIRC), switches it on, switches itself off",
   h.calls == [("install", "area_alerts"), ("enabled", "area_alerts", True), ("enabled", "broadcast_alerts", False)], h.calls)
ok("...and never transmits or listens itself (no channels)", t.channels_used() == [] and t.tick_seconds == 0)
class OldCoreAPI:
    def __init__(self): self.logs = []
    def after(self, ms, fn): pass
    def log(self, text, level="info"): self.logs.append(text)
o = OldCoreAPI(); ttw.Addon(o).hand_over()
ok("...on an mcIRC from before the update (still running): only 'restart mcIRC to finish'", o.logs and "restart mcIRC" in o.logs[0], o.logs)

# ---- Area alerts takes the settings over: ADDED to its own, nothing overwritten or removed
sys.path.insert(0, os.path.join(ROOT, "packages", "area_alerts"))
for _m in ("aa_more", "aa_extras", "aa_places", "aa_sources", "aa_traffic", "aa_ferries", "aa_transit", "aa_route"): sys.modules.pop(_m, None)
import aa_more, aa_places, aa_ferries, aa_traffic, aa_sources
OLD = {"muted": False, "route_on": True, "tomtom_key": "TT", "translink_key": "TL", "weather_areas": ["Lower Mainland", "Vancouver Island"],
       "sources": {"DriveBC": True, "BC Ferries": True, "BC Transit": True, "TransLink": True, "Weather": True, "Earthquake": True, "Tsunami": True,
                   "Weekly reminder": False},
       "channel_lists": {"DriveBC": "#drivebc", "BC Ferries": "#bcferries", "BC Transit": "#bctransit", "TransLink": "#translink", "Weather": "#weather"}}
lm = aa_places.make("CA", "British Columbia", "Lower Mainland")
MINE = {"areas": [lm], "kinds": {"weather": True, "traffic": True, "transit": True}, "channels": {"weather": "#alerts", "transit": "#transportation"},
        "transit_feeds": ["mdb-2572"], "transit_channels": {"mdb-2572": "#bus"}, "keys": {"transit:mdb-2572": "mine"}}
KCH = {"weather": "#weather", "traffic": "#traffic", "transit": "#transit", "ferries": "#bcferries", "quakes": "#alerts", "tsunami": "#alerts"}
new = aa_more.move_settings(OLD, lambda k, d=None: MINE.get(k, d), ("disasters", "weather"), lambda k: KCH[k],
                            lambda n: aa_places.make("CA", "British Columbia", n))
ok("its regions become areas - the ones already there not twice", [a["name"] for a in new["areas"]] == ["Lower Mainland", "Vancouver Island", "Sunshine Coast"], new.get("areas"))
ok("what it broadcast is switched on (ferries, quakes, tsunami); broadcasting on", all(new["kinds"].get(k) for k in ("ferries", "quakes", "tsunami", "weather", "traffic", "transit"))
   and new.get("broadcast") is True)
ok("channels: its channels ADDED next to Area alerts' own (weather: #alerts + #weather; DriveBC: #traffic + #drivebc)",
   new["channels"]["weather"] == "#alerts, #weather" and new["channels"]["ferries"] == "#bcferries" and new["traffic_channels"]["drivebc"] == "#traffic, #drivebc", new)
ok("...a channel set for an agency is kept and the old one added (Victoria: #bus + #bctransit); new agencies: the transit box + theirs",
   new["transit_channels"]["mdb-2572"] == "#bus, #bctransit" and new["transit_channels"]["mdb-2474"] == "#transportation, #bctransit"
   and new["transit_channels"]["mdb-3348"] == "#transportation, #translink", new["transit_channels"])
ok("...the BC Transit systems it read, and TransLink (its key moved); a key already there is kept",
   set(aa_more.BC_TRANSIT.values()) <= set(new["transit_feeds"]) and "mdb-3348" in new["transit_feeds"] and new["keys"]["transit:mdb-3348"] == "TL"
   and new["keys"]["transit:mdb-2572"] == "mine")
ok("the route command, its TomTom key, the daily forecasts; a busier hour (30)", new["route_on"] and new["tomtom_key"] == "TT" and new["forecast_on"]
   and new["per_hour"] == 30 and "weekly_on" not in new)
ok("nothing of Area alerts' own is lost: every value it had is still in the result", all(v in new["transit_feeds"] for v in MINE["transit_feeds"])
   and new["channels"]["transit"] == "#transportation")
new2 = aa_more.move_settings(dict(OLD, use_scopes=True, scope_lm="on", scope_vi="", scope_sc="on"), lambda k, d=None: MINE.get(k, d),
                             ("disasters", "weather"), lambda k: KCH[k], lambda n: aa_places.make("CA", "British Columbia", n))
ok("its region code ('[on] NEW ...') becomes the prefix of every alert; none set: none", new2.get("prefix") == "[on]" and "prefix" not in new)
# Area alerts' take-over, once
area = load(os.path.join(ROOT, "packages", "area_alerts", "area_alerts.py"), "t_area")
class TakeAPI:
    def __init__(self): self.s, self.switched, self.logs = {}, [], []
    def get(self, k, d=None): return self.s.get(k, d)
    def set(self, k, v): self.s[k] = v
    def addon_settings(self, name): return dict(OLD)
    def addon_installed(self, name): return True
    def addon_enabled(self, name): return True
    def set_addon_enabled(self, name, on): self.switched.append((name, on))
    def log(self, text, level="info"): self.logs.append(text)
x = area.Addon.__new__(area.Addon); x.api = TakeAPI(); x.take_over()
ok("Area alerts takes over: settings added, it switched on, Traffic, transit and weather switched off, said in Status",
   x.api.s.get("enabled") and x.api.s.get("broadcast") and x.api.switched == [("broadcast_alerts", False)] and x.api.s.get("ttw_moved")
   and any("now part of Area alerts" in l for l in x.api.logs), (x.api.switched, x.api.logs))
x.api.switched.clear()
scheduled = []
x.api.after = lambda ms, fn: scheduled.append(fn)
x.api.add_menu_item = x.api.add_map_layer = x.api.add_bot_commands = lambda *a, **k: None
x2 = area.Addon.__new__(area.Addon); x2.api = x.api; x2.extras_load()
ok("...only once: the next start doesn't take over again (you may switch the old one back on)", scheduled == [] and x.api.switched == [])
del x.api.s["ttw_moved"]; x2.extras_load()
ok("...(before the move it does)", len(scheduled) == 1)
# map layers, ferries, daily posts
aa_traffic.INCIDENTS_SEEN.clear(); aa_traffic.INCIDENTS_SEEN["e1"] = (49.36, -121.47, "CLOSED: Hwy 1", "Closed at exit 170", time.time())
aa_traffic.INCIDENTS_SEEN["old"] = (49.0, -122.0, "Incident", "gone", time.time() - 7200)
aa_sources.QUAKES_SEEN.clear(); aa_sources.QUAKES_SEEN["q1"] = (48.5, -125.1, 5.2, "Off Vancouver Island")
ok("map layers: DriveBC incidents (the last half hour) and earthquakes", x._incidents() == [(49.36, -121.47, "CLOSED: Hwy 1", "Closed at exit 170")]
   and x._quakes() == [(48.5, -125.1, "M5.2 Off Vancouver Island")])
NOTICES = ('<h3>Metro Vancouver - Sunshine Coast</h3><a href="/current-conditions/service-notices?serviceNoticeCode=123">Horseshoe Bay - Langdale: '
           'cancelled sailings</a><h3>Northern</h3><a href="x?serviceNoticeCode=9">Prince Rupert - Haida Gwaii: delays</a>')
DEPART = ('<h3>Horseshoe Bay</h3><table><tr><td>Horseshoe Bay - Langdale Sailing duration: 40 minutes</td></tr>'
          '<tr><td>Queen of Surrey SCHEDULED: 10:30 AM ACTUAL: 11:05 AM ETA: 11:45 AM Earlier incident</td></tr>'
          '<tr><td>Queen of Surrey SCHEDULED: 12:30 PM ACTUAL: 12:34 PM ETA: 1:10 PM</td></tr></table>')
aa_ferries._cache.update(t=0.0, items=None)
got = aa_ferries.ferries(aa_places.make("CA", "British Columbia", "Sunshine Coast"), get=lambda url: NOTICES if "service-notices" in url else DEPART)
ok("BC Ferries: the notices and late sailings that name a place in the area (not Haida Gwaii; a 4-minute delay isn't one)",
   [g.id for g in got] == ["bcf:123", "bcf-delay:Horseshoe_Bay_-_Langdale:Queen_of_Surrey:10:30_AM:" + __import__("datetime").date.today().isoformat()]
   and "35 min late" in got[1].text and got[0].kind == "ferries", [g.text for g in got])
ok("...outside British Columbia: nothing asked", aa_ferries.ferries({"country": "US", "region": "Washington", "name": "Seattle"}, get=lambda u: 1 / 0) == [])
import datetime as _dt
daily = {"daily": {"time": ["2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16", "2026-10-17"], "weathercode": [0, 61, 3, 71, 95],
                   "temperature_2m_max": [14.4, 12.0, 11.6, 9.0, 8.0], "temperature_2m_min": [6.2, 7.0, 5.0, 2.0, 1.0]}}
f6 = aa_more.forecast(lm, 6, "LM", get=lambda u, p: daily); f8 = aa_more.forecast(lm, 8, "LM", get=lambda u, p: daily)
ok("6 AM: a 3-day forecast; 8 AM: a 5-day outlook - one message each, to the weather channel", f6.text.startswith("3-day forecast Lower Mainland: ")
   and "Tue H14 L6" in f6.text and f8.text.startswith("5-day outlook Lower Mainland: ") and f6.kind == f8.kind == "weather", (f6.text, f8.text))
ok("...once a day each", aa_more.due_posts(_dt.datetime(2026, 10, 13, 6, 5), {}) == [6] and aa_more.due_posts(_dt.datetime(2026, 10, 13, 6, 5), {"6": "2026-10-13"}) == []
   and aa_more.due_posts(_dt.datetime(2026, 10, 13, 7, 0), {}) == [])
ok("weekly reminder: Sundays at noon, once a week", aa_more.weekly_due(_dt.datetime(2026, 10, 11, 12, 3), "")[0]
   and not aa_more.weekly_due(_dt.datetime(2026, 10, 11, 12, 3), "2026-W41")[0] and not aa_more.weekly_due(_dt.datetime(2026, 10, 12, 12, 3), "")[0])

# ---- the map window uses the details
import mcIRC
app = mcIRC.App(root, demo=True); root.update()
app.map_layers["Test layer"] = (lambda: [(49.1, -121.5, "INCIDENT - Silver Skagit Road (Hope)", "Long details\nsecond line"), (49.2, -121.6, "Plain item")], "#d32f2f")
app.open_map(); root.update()
pts = app.map_win.points()
mine = [p for p in pts if p[0] == 49.1 and "Silver Skagit" in p[2]]      # (other layers, e.g. a real installed addon, may add their own pins)
ok("map: label (up to 40 chars) on the pin, details in the info box", mine and mine[0][2] == "INCIDENT - Silver Skagit Road (Hope)" and mine[0][5] == "Long details\nsecond line", mine)
ok("map: 3-item layer entries still work", any(p[2] == "Plain item" and p[5] == "Plain item" for p in pts))
ok("map info box is tall enough for details", int(app.map_win.info.cget("height")) >= 10)
for inst in [x for x in (globals().get("a"), globals().get("a2"), globals().get("a3")) if x is not None]:      # stop every feed thread before exiting
    if not hasattr(inst, "loop"): continue
    inst._stop_feeds()
    if getattr(inst, "thread", None): inst.thread.join(timeout=10)
app.map_win.destroy(); root.update()
root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.stdout.flush()
os._exit(1 if fails else 0)      # (the alert feeds' background threads can crash Python 3.10's shutdown after the checks are done)
