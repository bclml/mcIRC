import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""Line of sight: the Fresnel / earth-curve maths, reading the elevation service's answer, and the window.  No radio, no internet."""
import importlib.util, json, tkinter as tk

sys.path[:0] = [os.path.join(ROOT, "packages", "line_of_sight")]
import los_core as c

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

# ---- the maths
ok("Fresnel radius at the middle of a 10 km path on 915 MHz is about 28.6 m", abs(c.fresnel_radius_m(5000, 5000, 915) - 28.6) < 0.2, c.fresnel_radius_m(5000, 5000, 915))
ok("...and zero at the antennas", c.fresnel_radius_m(0, 10000, 915) == 0)
flat = c.profile([0.0] * 100, 10, 30, 30, 915)
ok("flat ground, 30 m masts, 10 km: clear", flat["verdict"] == "clear", flat["worst_ratio"])
ok("the earth's curve lifts the middle of a 10 km path by about 1.5 m (4/3 earth)", abs(flat["points"][50]["bulge"] - 1.47) < 0.05, flat["points"][50]["bulge"])
low = c.profile([0.0] * 100, 10, 2, 2, 915)
ok("flat ground, 2 m antennas, 10 km: the ground takes up part of the Fresnel zone", low["verdict"] == "fresnel" and 0 <= low["worst_ratio"] < 0.6, low["worst_ratio"])
hill = [0.0] * 100; hill[40] = 80.0
blocked = c.profile(hill, 10, 10, 10, 915)
ok("an 80 m hill between 10 m antennas: blocked, at the hill", blocked["verdict"] == "blocked" and abs(blocked["worst_km"] - 4.04) < 0.05
   and 70 < blocked["above_m"] < 73, (blocked["worst_km"], blocked["above_m"]))
long_flat = c.profile([0.0] * 100, 60, 10, 10, 915)
ok("60 km over flat ground with 10 m antennas: the earth's curve blocks it", long_flat["verdict"] == "blocked", long_flat["worst_ratio"])
ok("the summary names the verdict", "Clear line of sight" in c.summary(flat, "A", "B", 10, 90) and "Blocked by the ground at 4.0 km (71 m above the line)" in c.summary(blocked, "A", "B", 10, 90)
   and "weaker signal" in c.summary(low, "A", "B", 10, 90))
ok("100 evenly spaced points from A to B", (lambda p: len(p) == 100 and p[0] == (1.0, 2.0) and p[-1] == (3.0, 4.0))(c.path_points(1, 2, 3, 4)))

# ---- the elevation service
asked = []
def fake_get(url, timeout=20):
    asked.append(url)
    n = url.split("latitude=")[1].split("&")[0].count("%2C") + 1
    return json.dumps({"elevation": [0.0] * n}).encode()
res, km, deg = c.check(47.0, -122.0, 47.0, -121.9, 20, 20, 910.525, get=fake_get)
ok("one request to Open-Meteo for 100 points", len(asked) == 1 and asked[0].startswith(c.ELEVATION_URL) and len(res["points"]) == 100)
ok("...the distance and heading of the path", 7.5 < km < 7.7 and 89 < deg < 91, (km, deg))
for label, body in (("an error answer", {"error": True, "reason": "Parameter latitude out of range"}), ("a short answer", {"elevation": [1, 2]})):
    try: c.elevations(c.path_points(0, 0, 1, 1), get=lambda u, timeout=20: json.dumps(body).encode()); ok(f"{label} is an error", False)
    except ValueError as e: ok(f"{label} is an error", True)
for label, args in (("the same place twice", (1, 1, 1, 1)), ("more than 500 km", (0, 0, 10, 0))):
    try: c.check(*args, get=fake_get); ok(f"{label}: refused", False)
    except ValueError: ok(f"{label}: refused", True)

# ---- the window (a stand-in for mcIRC)
spec = importlib.util.spec_from_file_location("t_los", os.path.join(ROOT, "packages", "line_of_sight", "line_of_sight.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
root = tk.Tk(); root.withdraw()
class Nodes:
    def all(self): return [{"public_key": "a1" * 32, "name": "Demo Hilltop RPT", "type": 2, "lat": 47.0, "lon": -121.9},
                           {"public_key": "b2" * 32, "name": "Demo NoPos", "type": 1, "lat": 0, "lon": 0}]
class Api:
    def __init__(s): s.s = {}
    def get(s, k, d=None): return s.s.get(k, d)
    def set(s, k, v): s.s[k] = v
    def node_position(s): return (47.0, -122.0, "Me")
    def add_menu_item(s, *a): pass
    def add_name_action(s, *a): s.action = a
    def ui(s): return {"root": root}
    def run_background(s, fn, done):
        try: r = fn()
        except Exception as e: r = e
        done(r)
    nodes = Nodes()
c.http_get = fake_get
api = Api()
a = m.Addon(api); a.on_load()
ok("the right-click entry is there", api.action[0] == "Line of sight to {nick}")
ok("the ends to pick from: your node, then nodes with a position", list(a.places()) == [m.ME, "Demo Hilltop RPT"])
a.open(to="@[Demo Hilltop RPT]"); root.update()
w = a.win
ok("'Line of sight to <name>' fills both ends and checks at once", w.a.get() == m.ME and w.b.get() == "Demo Hilltop RPT" and w.res is not None)
ok("...the verdict is shown (flat ground, 2 m and 10 m antennas, 7.6 km)", "My node (Options > Node) -> Demo Hilltop RPT: 7.6 km" in w.verdict.cget("text"), w.verdict.cget("text"))
ok("...and drawn", len(w.c.find_all()) > 5)
ok("the heights and frequency are remembered", api.s == {"h1": 2.0, "h2": 10.0, "freq": 910.525}, api.s)
w.h1.set("tall"); w.check()
ok("a height that isn't a number says so", "Antenna heights are metres" in w.verdict.cget("text"))
w.h1.set("2"); w.b.set("Demo NoPos"); w.check()
ok("a node without a position can't be picked", "Pick both ends" in w.verdict.cget("text"))
w.b.set("Demo Hilltop RPT"); w.swap()
ok("Swap ends swaps the heights too", (w.a.get(), w.h1.get(), w.h2.get()) == ("Demo Hilltop RPT", "10", "2"), (w.a.get(), w.h1.get(), w.h2.get()))
c.http_get = lambda url, timeout=20: (_ for _ in ()).throw(OSError("timed out"))
w.check()
ok("no internet: it says it couldn't check", w.verdict.cget("text") == "Couldn't check: timed out", w.verdict.cget("text"))
a.on_unload(); root.destroy()

print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
