import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""Traffic and weather: Environment Canada weather warnings for areas in any province or territory, picked by province then area.  No radio, no
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

# the settings tab: province, then area
import mcIRC
from gui_addons import AddonAPI
root = tk.Tk()
app = mcIRC.App(root, demo=True); root.update()
app.save = lambda: None
spec = importlib.util.spec_from_file_location("t_ba", os.path.join(ROOT, "packages", "broadcast_alerts", "broadcast_alerts.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
api = AddonAPI(app, "broadcast_alerts"); bot = mod.Addon(api)
page = bot.build_options(tk.Frame(root)); root.update()
ok("the 'Weather areas' tab starts with the three original regions ticked", sum(v.get() for v in bot.area_vars.values()) == 3
   and all(bot.area_vars[n].get() for n in ec_areas.DEFAULT_AREAS))
bot.area_vars["Greater Calgary"].set(True); bot.area_vars["Sunshine Coast"].set(False)
with mock.patch.object(bot, "_mode_changed", lambda: None), mock.patch.object(bot, "_refresh_button", lambda: None):
    bot.apply_options()
ok("ticks in any province are saved and watched", set(api.get("weather_areas")) == {"Lower Mainland", "Vancouver Island", "Greater Calgary"}
   and set(ea.WEATHER_LOCATIONS) == {"Lower Mainland", "Vancouver Island", "Greater Calgary"}, api.get("weather_areas"))
ea.set_weather_areas([])
root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
