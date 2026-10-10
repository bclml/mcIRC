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

# ---- the addon: defaults, lifecycle, options
import broadcast_alerts as ba
store = {}
root = tk.Tk()
class API:
    connected = False
    def __init__(self): self.layers = {}; self.logs = []
    def get(self, k, d=None): return store.get(k, d)
    def set(self, k, v): store[k] = v
    def log(self, *a, **k): self.logs.append(a)
    def add_toolbar_button(self, text, fn): return tk.Button(root, text=text)
    def add_command(self, *a, **k): pass
    def add_menu_item(self, *a, **k): pass
    def add_map_layer(self, name, fn, color): self.layers[name] = fn
async def dummy(): await asyncio.sleep(3600)
with mock.patch.object(ea, "traffic_loop", dummy), mock.patch.object(ea, "weather_loop", dummy), mock.patch.object(ea, "reload_active_alerts_from_log", lambda: None), mock.patch.object(ea, "reload_critical_alert_ids_from_log", lambda: None):
    api = API(); a = ba.Addon(api); a.on_load()
    ok("fresh install: broadcasting is OFF by default", ea.TX["muted"] is True and a.button.cget("text") == "Traffic, transit and weather: map only", (ea.TX["muted"], a.button.cget("text")))
    time.sleep(0.4)
    ok("...and the feeds already run for the map, without any radio", a.thread is not None and a.thread.is_alive())
    a.on_disconnect(); time.sleep(0.2)
    ok("map-only mode keeps running when the radio disconnects", a.thread.is_alive())
    io.PENDING_SENDS.append({"idx": 3, "msg": "x", "alert": "new", "guid": None, "queued": time.time()})
    a.set_muted(False); time.sleep(0.5)
    ok("switching broadcasting on while there is no radio stops the feeds (nothing to send with)", ea.TX["muted"] is False and not a.thread.is_alive() and a.button.cget("text") == "Traffic, transit and weather: BROADCASTING")
    api.connected = True; a.on_connect(); time.sleep(0.4)
    ok("with a radio connected the feeds run again", a.thread.is_alive())
    a.on_disconnect(); time.sleep(0.5)
    ok("while broadcasting, losing the radio stops the feeds (as before)", not a.thread.is_alive())
    io.PENDING_SENDS.append({"idx": 3, "msg": "x", "alert": "new", "guid": None, "queued": time.time()})
    a.set_muted(True)
    ok("switching broadcasting off drops anything queued", not io.PENDING_SENDS)
    # saved settings from before this version are respected
    store.clear(); store["muted"] = False
    a2 = ba.Addon(API()); a2.apply_settings()
    ok("an existing 'broadcasting on' setting is kept (updates do not silence a running bot)", ea.TX["muted"] is False)
    store.clear(); store["muted"] = True
    a2.apply_settings(); ok("an existing 'muted' setting is kept", ea.TX["muted"] is True)
    # options page
    store.clear(); a3 = ba.Addon(API()); a3.on_load(); page = a3.build_options(tk.Frame(root))
    ok("Options: 'Broadcast alerts' is unticked on a fresh install", a3.broadcast.get() is False)
    texts = []
    def walk(w):
        for c in w.winfo_children():
            try: texts.append(c.cget("text"))
            except tk.TclError: pass
            walk(c)
    walk(page)
    ok("Options explains map-only mode", any("keeps the map" in t and "nothing is" in t and "transmitted" in t for t in texts), [t for t in texts if "map" in t][:2])
    a3.broadcast.set(True); a3.apply_options()
    ok("ticking it and applying turns broadcasting on", store["muted"] is False and ea.TX["muted"] is False)
    a3.broadcast.set(False); a3.apply_options()
    ok("unticking and applying turns it off again", store["muted"] is True and ea.TX["muted"] is True)
    # map layer feed
    ea.active_traffic_alerts["DriveBC|" + real["id"]] = ("DriveBC", "x")
    ea.ALERT_LOCATIONS["DriveBC|" + real["id"]] = (49.3624, -121.4718, "INCIDENT (Hope)")
    ea.ALERT_MAPINFO["DriveBC|" + real["id"]] = ea._drivebc_mapinfo(real, "INCIDENT", "Hope", [])
    inc = a3._incidents()
    ok("the incident layer gives (lat, lon, label, details)", inc and len(inc[0]) == 4 and "Location approximate" in inc[0][3], inc)
    ea.active_traffic_alerts["DriveBC|demo"] = ("DriveBC", "x"); ea.ALERT_LOCATIONS["DriveBC|demo"] = (49.0, -123.0, "Demo incident")
    ok("entries without map info still work (demo mode)", any(i[2] == "Demo incident" and i[3] == "Demo incident" for i in a3._incidents()))
    a3._stop_feeds()

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
