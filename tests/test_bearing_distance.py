import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""Bearing & distance: the maths, finding a node by name, the answers, and the Nodes by distance window.  No radio."""
import importlib.util, tkinter as tk

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

spec = importlib.util.spec_from_file_location("t_bd", os.path.join(ROOT, "packages", "bearing_distance", "bearing_distance.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

# ---- the maths (London -> Paris: about 344 km, heading about 148 degrees)
km = m.distance_km(51.5074, -0.1278, 48.8566, 2.3522)
ok("distance London -> Paris is about 344 km", 340 < km < 347, km)
deg = m.bearing_deg(51.5074, -0.1278, 48.8566, 2.3522)
ok("...heading about 148 degrees (SSE)", 146 < deg < 150 and m.compass(deg) == "SSE", deg)
ok("due north / east / south / west", [m.compass(m.bearing_deg(0, 0, *p)) for p in ((1, 0), (0, 1), (-1, 0), (0, -1))] == ["N", "E", "S", "W"])
ok("the same point is 0 km away", m.distance_km(10, 10, 10, 10) == 0)
ok("distances read well", (m.fmt_distance(0.45), m.fmt_distance(12.34), m.fmt_distance(250.4), m.fmt_distance(12.34, "mi"), m.fmt_distance(0.05, "mi"))
   == ("450 m", "12.3 km", "250 km", "7.7 mi", "164 ft"))

# ---- in use (a stand-in for mcIRC); you are at 10 N, 10 E
NODES = [{"public_key": "a1" * 32, "name": "Demo Hilltop RPT", "type": 2, "lat": 11.0, "lon": 10.0, "last_seen": 0},
         {"public_key": "b2" * 32, "name": "Demo Valley RPT", "type": 2, "lat": 10.0, "lon": 12.0, "last_seen": 0},
         {"public_key": "c3" * 32, "name": "Demo Alice", "type": 1, "lat": 10.1, "lon": 10.0, "last_seen": 0},
         {"public_key": "d4" * 32, "name": "Demo NoPos", "type": 1, "lat": 0.0, "lon": 0.0, "last_seen": 0}]
class Nodes:
    def all(self): return [dict(n) for n in NODES]
root = tk.Tk(); root.withdraw()
class Api:
    def __init__(s): s.s, s.notes, s.pos = {}, [], (10.0, 10.0, "Me")
    def get(s, k, d=None): return s.s.get(k, d)
    def set(s, k, v): s.s[k] = v
    def notice(s, t, level="info"): s.notes.append((level, t))
    def node_position(s): return s.pos
    def add_command(s, *a): s.cmd = a
    def add_menu_item(s, *a): pass
    def add_name_action(s, *a): s.action = a
    def ui(s): return {"root": root}
    nodes = Nodes()
api = Api()
a = m.Addon(api); a.on_load()
ok("/bearing and the right-click entry are there", api.cmd[0] == "bearing" and api.action[0] == "Distance and bearing to {nick}")
a.cmd_bearing("hilltop")
ok("/bearing hilltop: a unique part of a name is enough", api.notes[-1] == ("info", "Demo Hilltop RPT: 111 km N (0 degrees) from you"), api.notes[-1])
a.cmd_bearing("demo VALLEY rpt")
ok("/bearing <full name>, any case", api.notes[-1][1].startswith("Demo Valley RPT: 219 km E (90 degrees)"), api.notes[-1])
a.cmd_bearing("rpt")
ok("several matches: they are listed", "2 nodes match 'rpt'" in api.notes[-1][1] and api.notes[-1][0] == "warn", api.notes[-1])
a.cmd_bearing("nobody")
ok("an unknown name says so", api.notes[-1] == ("warn", "No node called 'nobody' in mcIRC's node memory."), api.notes[-1])
a.cmd_bearing("")
ok("no name: how to use it", api.notes[-1] == ("warn", "Usage: /bearing <node name>"))
a.say_for("Demo NoPos")
ok("a node without a position says so", api.notes[-1] == ("warn", "Demo NoPos doesn't advertise a position."), api.notes[-1])
a.say_for("@[Demo Alice]")
ok("the right-click entry answers ('@[name]' as names are shown)", api.notes[-1][1].startswith("Demo Alice: 11.1 km N"), api.notes[-1])
api.s["units"] = "mi"; a.say_for("Demo Alice")
ok("...in miles when chosen", api.notes[-1][1].startswith("Demo Alice: 6.9 mi N"), api.notes[-1])
api.s["units"] = "km"
ok("Nodes by distance: only nodes with a position, nearest first", [r[2]["name"] for r in a.rows()] == ["Demo Alice", "Demo Hilltop RPT", "Demo Valley RPT"])
ok("...filtered by type", [r[2]["name"] for r in a.rows("Repeater")] == ["Demo Hilltop RPT", "Demo Valley RPT"])
ok("...and by distance", [r[2]["name"] for r in a.rows(max_km=50)] == ["Demo Alice"])
a.open(); root.update()
ok("the window lists them with distance and direction", [a.win.t.item(i, "values")[2:4] for i in a.win.t.get_children()][0] == ("11.1 km", "N 0°"))
a.win.limit.set("100"); a.win.fill()
ok("...and its distance box filters", len(a.win.t.get_children()) == 1)
api.pos = (0.0, 0.0, "Me")
a.cmd_bearing("hilltop")
ok("your own position not set: it says how to set it", api.notes[-1][0] == "warn" and "Options > Node" in api.notes[-1][1])
a.win.fill()
ok("...and the window lists nothing and says so", not a.win.t.get_children() and "isn't set" in a.win.note.cget("text"))
a.on_unload(); root.destroy()

print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
