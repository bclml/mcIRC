import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""The Weather bot is part of Area alerts (2.1): its settings - the defaults and every node's own - are ADDED to Area alerts' (once),
nothing Area alerts had is changed, the alert checks are not switched on, and the Weather bot (2.0, a hand-over) switches itself off.
The daily forecasts have their own switch.  No radio, no internet."""
import copy, importlib.util

sys.path[:0] = [os.path.join(ROOT, "packages", "area_alerts")]
from gui_addons import AddonAPI

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

def load(pkg):
    spec = importlib.util.spec_from_file_location("t_wm_" + pkg, os.path.join(ROOT, "packages", pkg, pkg + ".py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

class Addons:
    def __init__(self, app): self.app, self.installed = app, {"weather_bot", "area_alerts"}
    def discover(self): return {n: {} for n in self.installed}
    def set_enabled(self, name, on): self.app.settings.setdefault("addons_enabled", {})[name] = on
class Root:
    def after(self, ms, fn): fn()
class App:
    def __init__(self, settings):
        self.settings, self.root, self.lines = settings, Root(), []
        self.addons = Addons(self)
        self.q = type("Q", (), {"put": lambda s, item: item[0] == "call" and item[1]()})()
    def save(self): pass
    def status_line(self, text, level="info", **k): self.lines.append(text)

WX_OLD = {"enabled": True, "channels": "#weather, #wx", "home": "Springfield", "units": "imperial", "off": ["satpass"], "rain_alerts": True,
          "contact": "ask me", "_nodes": ["main", "wifi 1"], "_names": {"wx": {"also": ["w"]}},
          "_per_node": {"wifi 1": {"channels": "#buds", "cooldown": 60}}}
AA_MINE = {"enabled": False, "areas": [{"name": "Somewhere"}], "channels": {"weather": "#alerts"}, "contact": "not this one",
           "_per_node": {"wifi 1": {"broadcast": True}}}

def run(old, mine, wx_on=True):
    settings = {"addons": {"weather_bot": copy.deepcopy(old), "area_alerts": copy.deepcopy(mine)},
                "addons_enabled": {"weather_bot": wx_on, "area_alerts": True}}
    app = App(settings)
    api = AddonAPI(app, "area_alerts")
    area = load("area_alerts")
    x = area.Addon.__new__(area.Addon); x.api = api
    x.wx_limiter = type("L", (), {"per_user": 30})()
    x.take_over_wx()
    return app, settings["addons"]["area_alerts"], x

app, aa, x = run(WX_OLD, AA_MINE)
ok("the weather commands come over switched on, with its channels, place, units, commands off, rain warning and contact",
   aa["wx_on"] is True and aa["wx_channels"] == "#weather, #wx" and aa["wx_home"] == "Springfield" and aa["wx_units"] == "imperial"
   and aa["wx_off"] == ["satpass"] and aa["wx_rain"] is True and aa["wx_contact"] == "ask me", aa)
ok("...its other command names too ('w' for wx)", aa.get("_names") == {"wx": {"also": ["w"]}}, aa.get("_names"))
ok("an extra node's own Weather bot settings become that node's own here (#buds on wifi 1), next to what it had",
   aa["_per_node"]["wifi 1"] == {"broadcast": True, "wx_channels": "#buds", "wx_cooldown": 60}, aa["_per_node"])
ok("the nodes it worked on are added ('Use on these nodes')", aa.get("_nodes") == ["main", "wifi 1"], aa.get("_nodes"))
ok("nothing Area alerts had is changed: alert checks stay off, its areas and channels as they were",
   aa["enabled"] is False and aa["areas"] == [{"name": "Somewhere"}] and aa["channels"] == {"weather": "#alerts"} and aa["contact"] == "not this one", aa)
ok("the Weather bot is switched off and Status says where its settings went",
   app.settings["addons_enabled"]["weather_bot"] is False and any("Weather commands" in l for l in app.lines), app.lines)
ok("...its own settings are left where they are", app.settings["addons"]["weather_bot"] == WX_OLD)
ok("done once ('wx_moved')", aa.get("wx_moved") is True)

app, aa, x = run(WX_OLD, dict(AA_MINE, wx_channels="#mine", wx_on=False))
ok("a weather setting Area alerts already has is kept (not overwritten)", aa["wx_channels"] == "#mine" and aa["wx_on"] is False, aa)

app, aa, x = run(WX_OLD, AA_MINE, wx_on=False)
ok("a Weather bot that was switched off: its settings come over but the commands stay off", "wx_on" not in aa and aa["wx_channels"] == "#weather, #wx", aa)

app, aa, x = run(dict(WX_OLD, handed_over=True), AA_MINE, wx_on=False)
ok("...unless the Weather bot 2.0 handed over (it noted it was on before it switched itself off)", aa.get("wx_on") is True, aa)

app, aa, x = run({}, AA_MINE, wx_on=False)
ok("no Weather bot settings: nothing changes but 'wx_moved'", set(aa) - set(AA_MINE) == {"wx_moved"} and not app.lines, (aa, app.lines))

# the Weather bot 2.0: hands over
wb = load("weather_bot")
settings = {"addons": {"weather_bot": {"enabled": True}}, "addons_enabled": {"weather_bot": True}}
app = App(settings); app.addons.installed = {"weather_bot", "area_alerts"}
api = AddonAPI(app, "weather_bot"); api.after = lambda ms, fn: fn()
b = wb.Addon(api); b.on_load()
ok("Weather bot 2.0: switches Area alerts on and itself off, noting it was on; it has no channels of its own",
   settings["addons_enabled"] == {"weather_bot": False, "area_alerts": True} and settings["addons"]["weather_bot"].get("handed_over") is True
   and b.channels_used() == [], settings)

# the daily forecasts: their own switch, on the first tab
src = open(os.path.join(ROOT, "packages", "area_alerts", "area_alerts.py"), encoding="utf-8").read()
ok("the 6 AM / 8 AM forecasts have a checkbox on the 'Areas and alerts' tab", "Daily weather: a 3-day forecast at 6 AM and a 5-day outlook at 8 AM" in src)
ok("...not tied to the Weather warnings kind", 'if self.api.get("forecast_on", False):' in open(os.path.join(ROOT, "packages", "area_alerts", "aa_extras.py"), encoding="utf-8").read())
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
