import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "packages", "area_alerts")
sys.path.insert(0, ROOT); sys.path.insert(0, PKG); os.chdir(ROOT)
"""Area alerts: places (country, region, area), the sources (GDACS, USGS, NOAA tsunami, NWS, MeteoAlarm) and the addon's checking and
broadcasting.  No radio, no internet (stand-ins for every feed)."""
import importlib.util, time
import tkinter as tk

for m in ("aa_sources", "aa_places", "aa_world"): sys.modules.pop(m, None)     # an installed copy next to the app must not shadow the package's
import aa_places as places
import aa_sources as src

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

# ---- places
names = dict(places.countries())
ok("every country of the world can be chosen", len(names) > 240 and names.get("Japan") == "JP" and names.get("Brazil") == "BR", len(names))
ok("...then its regions", "California" in places.regions("US") and "Bavaria" in places.regions("DE"))
ok("...then its areas, the biggest towns first", places.areas("US", "California")[0][0] == "Los Angeles")
ok("Canada also has the Traffic and weather addon's areas (Lower Mainland ...)", places.areas("CA", "British Columbia")[0][0] == "Lower Mainland")
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

nws = {"features": [{"properties": {"id": "urn:1", "event": "Excessive Heat Warning", "severity": "Severe"}}]}
got = src.weather(la, get=feed(nws))
ok("US weather: the National Weather Service's alerts for the point", [a.text for a in got] == ["Excessive Heat Warning - Los Angeles (Severe, NWS)"], got)

def ma(ident, area, level, event="Moderate rain warning", lang="en-GB"):
    return {"alert": {"identifier": ident, "info": [{"language": lang, "event": event, "area": [{"areaDesc": area}],
                                                     "parameter": [{"valueName": "awareness_level", "value": level}]}]}}
warnings = {"warnings": [ma("a", "Rhône", "2; yellow; Moderate"), ma("b", "Rhône", "1; green; Minor"), ma("c", "Gironde", "3; orange; Severe")]}
got = src.weather(lyon, get=feed(warnings))
ok("Europe (MeteoAlarm): the warnings for the area's district (accents ignored), green ones left out",
   [a.text for a in got] == ["YELLOW Moderate rain warning - Lyon (MeteoAlarm)"], got)
ok("...district names match as whole words ('Kreis Biberach' is Biberach, not 'Biberachstadt')",
   src._names_match({src._core("Kreis Biberach")}, "Landkreis Biberach") and not src._names_match({src._core("Kreis Biberach")}, "Biberachstadt"))
ok("countries without an official feed here have no weather warnings (disasters and earthquakes still)", src.weather(places.make("JP", places.regions("JP")[0],
   places.areas("JP", places.regions("JP")[0])[0][0]), get=lambda *a, **k: 1 / 0) == [])

atom = ("<feed><entry><id>urn:t1</id><title>Tsunami Warning for coastal areas of California</title><summary>Coastal areas of California and "
        "Oregon</summary></entry><entry><id>urn:t2</id><title>Tsunami Information Statement</title><summary>No tsunami threat to California"
        "</summary></entry></feed>")
got = src.tsunami(la, get=lambda url, **k: atom)
ok("tsunami: a warning naming the area's region; statements with no threat left out", [a.id for a in got] == ["tsunami:urn:t1"] * 2, got)

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
api.s["channels"] = {"weather": "Public"}
ok("a channel can be chosen per kind", bot.channel("weather") == "Public")     # (the core never lets an addon post in Public: test_private_replies)
bot.on_unload()

root = tk.Tk(); root.withdraw()
api2 = API(); b2 = mod.Addon(api2); b2.on_load()
frame = b2.build_options(tk.Frame(root, bg="#eee"))
ok("settings: off and not broadcasting by default", not b2.v_on.get() and not b2.v_bc.get())
b2.c_box.set("France"); b2._fill_regions(); b2.r_box.set("Auvergne-Rhône-Alpes"); b2._fill_areas(); b2.a_box.set("Lyon"); b2._add(); b2._add()
ok("settings: country, then region, then area; added once", [places.label(a) for a in b2.chosen] == ["Lyon, Auvergne-Rhône-Alpes, France"])
b2.v_on.set(True); b2.apply_options()
ok("...saved, with the first check after switching on only showing", api2.s["enabled"] and api2.s["areas"][0]["name"] == "Lyon"
   and api2.s["checked_once"] is False and api2.s["broadcast"] is False and api2.s["channels"]["weather"] == "#weather")
root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
