import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""Wardrive map: noting which repeater was heard where, the map layers, the per-repeater list, saving and clearing.  No radio."""
import importlib.util, json, tempfile, time, tkinter as tk

sys.path[:0] = [os.path.join(ROOT, "packages", "wardrive_map")]
import wdmap_core as c

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

A, B, C2 = "a1" + "00" * 31, "b2" + "00" * 31, "a1ff" + "00" * 30          # A and C2 share the first byte 'a1'
NODES = [{"public_key": A, "name": "Demo Hilltop RPT", "type": 2, "lat": 10.0, "lon": 10.0},
         {"public_key": B, "name": "Demo Valley RPT", "type": 2, "lat": 0, "lon": 0},
         {"public_key": C2, "name": "Demo Clash RPT", "type": 3, "lat": 0, "lon": 0},
         {"public_key": "c3" + "00" * 31, "name": "Demo Alice", "type": 1, "lat": 0, "lon": 0}]

# ---- the log
tmp = tempfile.mkdtemp(prefix="mcirc_wd_")
log = c.Log(os.path.join(tmp, "logs", "wd.json"))
ok("a sighting is noted", log.add(100, 10.1, 10.0, B, 3.0, -100))
ok("...the same repeater at the same spot within a minute: one record, the better signal", not log.add(130, 10.1001, 10.0, B, 6.0, -95) and len(log.rows) == 1 and log.rows[0][4] == 6.0)
ok("...a minute later it is a new record", log.add(200, 10.1, 10.0, B, 2.0, -101) and len(log.rows) == 2)
log.add(210, 10.1, 10.0, A, -8.0, -115)
log.add(220, 10.3, 10.0, A, 7.0, -90)
sp = log.spots()
ok("map spots: the best repeater per spot, and how many were heard there", sp[(10.1, 10.0)] == (6.0, B, 2) and sp[(10.3, 10.0)] == (7.0, A, 1), sp)
names = {A: "Demo Hilltop RPT", B: "Demo Valley RPT"}
ok("strong layer (5 dB or more)", sorted(c.layer(sp, names, "strong")) == [(10.1, 10.0, "Demo Valley RPT +6.0 dB (+1 more)"), (10.3, 10.0, "Demo Hilltop RPT +7.0 dB")])
ok("one repeater only: its own spots", c.layer(log.spots(A), names, "weak") == [(10.1, 10.0, "Demo Hilltop RPT -8.0 dB")])
per = log.per_repeater(NODES)
ok("per repeater: how often, best signal and where", per[A]["count"] == 2 and per[A]["best"] == 7.0 and per[A]["best_at"] == (10.3, 10.0))
ok("...the farthest spot it reached you (its position known)", 33 < per[A]["far_km"] < 34 and per[B]["far_km"] is None, per[A]["far_km"])
log.save()
again = c.Log(log.path); again.load()
ok("saved and read back", again.rows == log.rows and not os.path.exists(log.path + ".tmp"))
ok("the hop of an advert's own packet is read", c.advert_key((bytes([1 | 4 << 2, 0]) + bytes.fromhex(A) + b"\0" * 70).hex()) == A)
ok("a 1-byte hop shared by two repeaters is not guessed", c.relay_owner("a1", [A, B, C2]) is None and c.relay_owner("b2", [A, B, C2]) == B
   and c.relay_owner("a100", [A, B, C2]) == A)

# ---- the addon (a stand-in for mcIRC)
spec = importlib.util.spec_from_file_location("t_wd", os.path.join(ROOT, "packages", "wardrive_map", "wardrive_map.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.LOG_PATH = os.path.join(tmp, "logs", "wardrive_map.json")
root = tk.Tk(); root.withdraw()
class Nodes:
    def all(self): return [dict(n) for n in NODES]
class Api:
    def __init__(s): s.s, s.pkts, s.layers, s.pos, s.logged = {}, [], {}, (49.0, -123.0, "Me"), []
    def get(s, k, d=None): return s.s.get(k, d)
    def set(s, k, v): s.s[k] = v
    def log(s, text, level="info"): s.logged.append(text)
    def add_map_layer(s, label, provider, colour): s.layers[label] = provider
    def add_menu_item(s, *a): pass
    def node_position(s): return s.pos
    def ui(s): return {"root": root}
    def run_background(s, fn, done): done(fn())
    @property
    def packet_log(s): return list(s.pkts)
    nodes = Nodes()
api = Api()
a = m.Addon(api); a.on_load()
ok("three map layers: strong, fair, weak", list(api.layers) == ["Wardrive: strong", "Wardrive: fair", "Wardrive: weak"])
t = time.time() + 1
api.pkts = [{"t": t, "path": "11b2", "size": 1, "snr": 6.5, "rssi": -95}]
a.on_tick()
ok("off until switched on: nothing recorded", a.log.rows == [])
api.s["recording"] = True
api.pkts = api.pkts + [{"t": t + 1, "path": "11b2", "size": 1, "snr": 6.5, "rssi": -95}, {"t": t + 2, "path": "11a1", "size": 1, "snr": 1.0, "rssi": -99},
                     {"t": t + 3, "path": "", "size": 1, "snr": 1.0, "rssi": -99}]
a.on_tick()
ok("recording: the repeater that sent it to you, at your position; shared or no hop: skipped", [(r[1], r[2], r[3], r[4]) for r in a.log.rows] == [(49.0, -123.0, B, 6.5)], a.log.rows)
pkt = (bytes([1 | 4 << 2, 0]) + bytes.fromhex(A) + b"\0" * 70).hex()
a.on_packet({"t": t + 70, "type": "ADVERT", "path": "", "snr": 9.0, "rssi": -80, "packet": pkt})
ok("a repeater's own advert heard with no hops counts too", a.log.rows[-1][3] == A and a.log.rows[-1][4] == 9.0)
a.on_packet({"t": t + 80, "type": "ADVERT", "path": "", "snr": 9.0, "rssi": -80, "packet": (bytes([1 | 4 << 2, 0]) + bytes.fromhex(NODES[3]["public_key"]) + b"\0" * 70).hex()})
ok("...but not a companion's", len(a.log.rows) == 2)
ok("the map layers show it", api.layers["Wardrive: strong"]() == [(49.0, -123.0, "Demo Hilltop RPT +9.0 dB (+1 more)")], api.layers["Wardrive: strong"]())
api.pos = (0.0, 0.0, "Me")
api.pkts = api.pkts + [{"t": t + 300, "path": "11b2", "size": 1, "snr": 2.0, "rssi": -100}]
a.on_tick()
ok("your position not set: nothing recorded", len(a.log.rows) == 2)
a.last_save = 0; a.on_tick()
ok("saved to the log file", json.load(open(m.LOG_PATH))["rows"] == a.log.rows)
api.pos = (49.0, -123.0, "Me")
a.open(); root.update()
w = a.win
ok("the window lists each repeater", sorted(w.t.item(i, "values")[0] for i in w.t.get_children()) == ["Demo Hilltop RPT", "Demo Valley RPT"])
w.only.set("Demo Valley RPT"); w.choose()
ok("'Map shows' one repeater: the layers show only it", api.layers["Wardrive: strong"]() == [(49.0, -123.0, "Demo Valley RPT +6.5 dB")], api.layers["Wardrive: strong"]())
w.rec.set(False); w.toggle()
ok("the Recording box switches it off", api.s["recording"] is False)
m.messagebox.askyesno = lambda *a, **k: True
w.clear()
ok("Clear (after asking) empties the log and the file", a.log.rows == [] and json.load(open(m.LOG_PATH))["rows"] == [])
ok("no warnings were logged", api.logged == [], api.logged)
a.on_unload(); root.destroy()

print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
