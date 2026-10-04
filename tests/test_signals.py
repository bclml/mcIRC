import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""Signals on the map: heard paths become routes between known repeaters (ours outward, incoming towards us); no radio needed."""
import tempfile, time, tkinter as tk

import gui_signals as gs
import gui_nodes

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

ME = (49.19, -122.85)
NODES = [{"public_key": "a1" + "0" * 62, "name": "Rep A", "type": 2, "lat": 49.25, "lon": -122.90},
         {"public_key": "b2" + "0" * 62, "name": "Rep B", "type": 2, "lat": 49.35, "lon": -123.05},
         {"public_key": "b2" + "1" * 62, "name": "Far B", "type": 2, "lat": 50.90, "lon": -120.00},     # same 1-byte hash, far away
         {"public_key": "c3" + "0" * 62, "name": "Phone", "type": 1, "lat": 49.10, "lon": -122.70},
         {"public_key": "d4" + "0" * 62, "name": "No position", "type": 2, "lat": 0, "lon": 0}]
ok("paths split by hash size", gs.split_path("a1b2c3", 1) == ["a1", "b2", "c3"] and gs.split_path("a1b2c3d4", 2) == ["a1b2", "c3d4"])
out = gs.route({"dir": "out", "path": "a1b2", "size": 1}, NODES, ME)
ok("our message: me -> first repeater -> next one", out == [ME, (49.25, -122.90), (49.35, -123.05)], out)
ok("two repeaters with the same short hash: the one near the route wins", (50.90, -120.00) not in out)
inc = gs.route({"dir": "in", "path": "b2a1", "size": 1}, NODES, ME)
ok("incoming: the repeaters it came through, ending at us", inc == [(49.35, -123.05), (49.25, -122.90), ME], inc)
ok("a repeater without a position is left out of the line", gs.route({"dir": "out", "path": "d4a1", "size": 1}, NODES, ME) == [ME, (49.25, -122.90)])
ok("nothing known -> no line", len(gs.route({"dir": "in", "path": "ee", "size": 1}, NODES, None)) < 2)
ok("the dot moves along the route", gs.along([(0, 0), (0, 2)], 0.5) == (0.0, 1.0) and gs.along([(0, 0), (0, 2)], 1) == (0, 2))

import mcIRC, gui_map
from gui_adverts import AdvertWatcher
root = tk.Tk()
app = mcIRC.App(root, demo=True); root.update()
store = gui_nodes.NodeStore(os.path.join(tempfile.mkdtemp(), "n.db"))
store.update_from_radio({n["public_key"]: {"public_key": n["public_key"], "adv_name": n["name"], "type": n["type"], "adv_lat": n["lat"], "adv_lon": n["lon"],
                                           "last_advert": int(time.time()), "lastmod": int(time.time())} for n in NODES})
app.nodes = store
app.settings["node_lat"], app.settings["node_lon"] = ME
aw = AdvertWatcher(app)
aw._event({"event": "rx", "path": "b2a1", "size": 1, "type": "GRP_TXT", "snr": 5})
app.note_signal("out", "a1b2", 7, 1)
while not app.q.empty():
    item = app.q.get_nowait()
    if item[0] == "call": item[1]()
ok("the listener's heard routes are kept (paths only)", sorted((t["dir"], t["path"]) for t in app.signal_traces) == [("in", "b2a1"), ("out", "a1b2")], app.signal_traces)
if gui_map.tkintermapview:
    app.open_map(); root.update()
    mw = app.map_win
    ok("signals are off until ticked", mw.signal_paths == [])
    mw.show_signals.set(True); mw.draw_signals(); root.update()
    ok("ticked: both routes are drawn", len(mw.signal_paths) == 2, len(mw.signal_paths))
    ok("...with a short summary", "2 heard: 1 repeat of my messages, 1 incoming" in mw.sig_label.cget("text"), mw.sig_label.cget("text"))
    next(t for t in app.signal_traces if t["dir"] == "in")["t"] -= 700; mw.draw_signals()
    ok("routes older than 10 minutes disappear", len(mw.signal_paths) == 1)
    mw.show_signals.set(False); mw.draw_signals()
    ok("unticked: gone", mw.signal_paths == [])
    mw.destroy(); root.update(); time.sleep(0.3)
else:
    print("[SKIP] map checks need tkintermapview")
root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
