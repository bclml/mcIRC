import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""Traffic, transit and weather: Environment Canada weather warnings for areas in any province or territory, picked by province then area.  No radio, no
internet (a stand-in for Environment Canada's alerts service)."""
import asyncio, importlib.util, tkinter as tk
from unittest import mock

import ec_areas
import emergency_agent as ea

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

provs = list(ec_areas.AREAS)
ok("every province and territory has areas", len(provs) == 13 and all(ec_areas.AREAS[p] for p in provs), provs)
names = [a[0] for areas in ec_areas.AREAS.values() for a in areas]
ok("area names are unique and each has a centre in Canada", len(names) == len(set(names))
   and all(41 < a[1] < 84 and -142 < a[2] < -52 for areas in ec_areas.AREAS.values() for a in areas))
ok("the three original BC regions are there and are the default", all(ec_areas.find(n) and ec_areas.find(n)[0] == "British Columbia" for n in ec_areas.DEFAULT_AREAS))

ok("alert kinds read like the per-zone feeds", ec_areas.kind_of({"alert_type": "warning", "risk_colour_en": "yellow", "alert_short_name_en": "Snowfall"})
   == "YELLOW WARNING - SNOWFALL" and ec_areas.kind_of({"alert_type": "statement", "alert_short_name_en": "Special weather"}) == "SPECIAL WEATHER STATEMENT"
   and ec_areas.kind_of({"alert_type": "advisory", "risk_colour_en": "yellow", "alert_short_name_en": "Frost (advisory)"}) == "YELLOW ADVISORY - FROST")
asked = []
def fake(url, params):
    asked.append(params["bbox"])
    return {"features": [{"properties": {"alert_type": "warning", "risk_colour_en": "yellow", "alert_short_name_en": "Snowfall", "status_en": "issued"}},
                         {"properties": {"alert_type": "warning", "risk_colour_en": "yellow", "alert_short_name_en": "Snowfall", "status_en": "continued"}},
                         {"properties": {"alert_type": "advisory", "risk_colour_en": "yellow", "alert_short_name_en": "Frost (advisory)", "status_en": "ended"}}]}
got = ec_areas.alerts_near(51.05, -114.07, get=fake)
ok("an area's alerts: the ones in force around its centre, each kind once, ended ones left out", got == {"YELLOW WARNING - SNOWFALL"}, got)
ok("...asked for about 50 km around the centre", asked == ["-114.42,50.8,-113.72,51.3"], asked)

ea.set_weather_areas(["Lower Mainland", "Greater Calgary", "Not an area"])
ok("chosen areas are watched; the original BC regions keep their own feeds", list(ea.WEATHER_LOCATIONS) == ["Lower Mainland", "Greater Calgary"]
   and ea.WEATHER_LOCATIONS["Lower Mainland"]["feeds"] and ea.WEATHER_LOCATIONS["Greater Calgary"]["feeds"] is None)
ea.set_weather_areas([])
ok("nothing chosen: the three original regions, as before", list(ea.WEATHER_LOCATIONS) == ec_areas.DEFAULT_AREAS)

# a scan with a new area: its warning becomes a 'Weather Warning: <area>' like the BC ones (to #weather)
ea.set_weather_areas(["Greater Calgary"])
seen = {}
async def collect(cur, state, skip=None): seen.update(cur)
with mock.patch.object(ec_areas, "alerts_near", lambda lat, lon: {"YELLOW WARNING - SNOWFALL"}), mock.patch.object(ea, "process_scraped_alerts", collect):
    asyncio.run(ea.scrape_weather_warnings())
ok("a new area's warning comes out like the BC ones: 'Weather Warning: Greater Calgary'",
   seen == {"EC_REGION_Greater Calgary_YELLOW WARNING - SNOWFALL": ("Weather Warning: Greater Calgary", "YELLOW WARNING - SNOWFALL", "")}, seen)
ea.set_weather_areas([])

# (the old addon's 'Weather areas' tab is gone: Area alerts 2.0 picks areas itself - see test_area_alerts / test_146)
root = tk.Tk()
# ---- more than one channel per kind (Channels tab)
import meshcore_io as _io
sent = []
with mock.patch.object(ea, "execute_mesh_command", lambda args, **k: sent.append(tuple(args[-3:-1]))), \
        mock.patch.object(ea, "_emit", lambda *a, **k: None), mock.patch.object(ea.time, "sleep", lambda s: None), \
        mock.patch.object(_io, "CONNECTION_ARGS", ["x"]), mock.patch.dict(_io.CHANNEL_INDEX_BY_NAME, {"#drivebc": 2, "#weather": 4, "#mcirc": 10, "Public": 0}, clear=True), \
        mock.patch.dict(ea.TX, {"muted": False}), mock.patch.dict(ea.TX["sources"], {"Weather": True, "DriveBC": True}):
    ea.CHANNEL_LISTS = {"Weather": ["weather", "mcirc", "public", "weather"]}
    ea.broadcast_via_cli("Weather Warning: Lower Mainland", "SNOWFALL", "x")
    ok("a weather warning goes to #weather and to the other channels listed - once each, never Public", sent == [("chan", "4"), ("chan", "10")], sent)
    sent.clear(); ea.broadcast_via_cli("DriveBC", "Hwy 1", "crash")
    ok("...other kinds keep their one channel", sent == [("chan", "2")], sent)
    sent.clear(); ea.CHANNEL_LISTS = {"DriveBC": ["mcirc", "drivebc"]}; ea.broadcast_via_cli("DriveBC", "Hwy 1", "crash")
    ok("...the first channel listed is the kind's own", sent == [("chan", "10"), ("chan", "2")], sent)
    ea.CHANNEL_LISTS = {}
sent = []
with mock.patch.object(ea, "execute_mesh_command", lambda args, **k: sent.append(tuple(args[-3:-1]))), \
        mock.patch.object(ea, "_emit", lambda *a, **k: None), mock.patch.object(_io, "CONNECTION_ARGS", ["x"]), \
        mock.patch.dict(_io.CHANNEL_INDEX_BY_NAME, {"#drivebc": 2, "Public": 0}, clear=True), \
        mock.patch.dict(ea.TX, {"muted": False}), mock.patch.dict(ea.TX["sources"], {"DriveBC": True}):
    ea.CHANNEL_LISTS = {"DriveBC": []}
    ea.broadcast_via_cli("DriveBC", "Hwy 1", "crash")
ok("a kind with no channel chosen is not broadcast - never to Public, never to the old built-in channel", sent == [], sent)
ea.CHANNEL_LISTS = {}
root.destroy()
import importlib, logging
before = len(logging.getLogger('').handlers)
importlib.reload(ea); importlib.reload(ea)
ok("the engine reloaded (addon updated) doesn't write every log line twice", len(logging.getLogger('').handlers) == before,
   (before, len(logging.getLogger('').handlers)))
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
