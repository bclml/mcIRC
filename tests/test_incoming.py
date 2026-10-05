import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""Incoming messages are never lost: every message of a batch is read, and one failing item can't stop the window's message pump.
Plus the map's 'Heard by' filter (which of your nodes heard a node).  No radio."""
import time
import tkinter as tk
from unittest import mock

import meshcore_io as io

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

# ---- 1. .sync_msgs prints several messages as one JSON array over several lines
batch = ('INFO:meshcore:Connected\n[{"type": "CHAN", "channel_idx": 0, "path_len": 3, "text": "A: one"},\n'
         '{"type": "PRIV", "pubkey_prefix": "ab12", "path_len": 2, "text": "hello"},\n'
         '{"type": "CHAN", "channel_idx": 2, "path_len": 255, "text": "B: two"}]\nINFO: done {x\n')
got = [(k, i, t, n) for k, i, t, n, _ in io.parse_messages(batch)]
ok("every message of a batch is read (not only the last one)", got == [("in", 0, "one", "A"), ("dm", -1, "hello", "ab12"), ("in", 2, "two", "B")], got)
ok("a single message still reads", [m[2] for m in io.parse_messages('[{"type": "CHAN", "channel_idx": 0, "text": "C: hi"}]\n')] == ["hi"])
cut = '[{"type": "CHAN", "channel_idx": 0, "text": "A: first"},\n{"type": "CHAN", "channel_idx": 0, "text": "B: second"}'
ok("a batch cut off at the end still gives its whole messages", [m[2] for m in io.parse_messages(cut)] == ["first", "second"])
ok("no messages -> nothing", io.parse_messages("[]\n") == [] and io.parse_messages("") == [])

# ---- 2. the message pump survives an item that fails
import mcIRC
root = tk.Tk()
app = mcIRC.App(root, demo=True); root.update()
errors = []
root.report_callback_exception = lambda *exc: errors.append(exc[1])
app._h_boom = lambda: (_ for _ in ()).throw(tk.TclError('invalid command name ".!optionsdialog3"'))
app.q.put(("boom",))
app.q.put(("chat", "in", 0, "still arrives", "Bob", {"snr": 10, "hops": 2}))
for _ in range(10): root.update(); time.sleep(0.12)
pub = app.windows["Public"].text.get("1.0", "end")
ok("one failing item is reported, not fatal", len(errors) == 1, errors)
ok("...and the messages after it still reach their window", "still arrives" in pub)
app.q.put(("chat", "in", 0, "and later ones too", "Bob", {}))
for _ in range(5): root.update(); time.sleep(0.12)
ok("...and the pump keeps running", "and later ones too" in app.windows["Public"].text.get("1.0", "end"))

# ---- 3. Options closed while it was reading the node: the late answer is dropped quietly
import gui_dialogs, gui_nodecfg
held = []
app.bg = lambda fn, done: held.append((fn, done))
dlg = gui_dialogs.OptionsDialog(app); root.update()
app.connected = True
dlg.node_pages.read()
dlg.destroy(); root.update()
errors.clear()
fn, done = held[-1]
node = {"info": {"name": "N", "radio_freq": 909.0, "radio_bw": 62.5, "radio_sf": 7, "radio_cr": 5, "tx_power": 22}, "ver": {}, "core": {}, "radio": {}}
try: done(node); late_ok = True
except Exception as e: late_ok = e
ok("a node answer that comes after Options was closed does nothing", late_ok is True and not errors, late_ok)
app.connected = False

# ---- 4. which of your nodes heard a node -> the map's Heard by filter
now = time.time()
app.nodes.update_from_radio({"aa" * 32: {"public_key": "aa" * 32, "adv_name": "OnMain", "type": 2, "adv_lat": 49.1, "adv_lon": -122.8, "last_advert": int(now)}}, now)
app.nodes.touch_contact({"public_key": "bb" * 32, "adv_name": "OnWifi", "type": 2, "adv_lat": 49.2, "adv_lon": -122.9}, via="wifi 1")
app.nodes.touch_contact({"public_key": "aa" * 32, "adv_name": "OnMain", "type": 2, "adv_lat": 49.1, "adv_lon": -122.8}, via="wifi 1")
hb = app.nodes.heard_by()
ok("the node memory knows which of your nodes heard each node", hb["aa" * 32] == {"main", "wifi 1"} and hb["bb" * 32] == {"wifi 1"}, hb)
app.settings["extra_nodes"] = [{"label": "wifi 1", "mode": "tcp", "host": "192.168.1.39", "tcp_port": 5000, "enabled": True}]
app.main_freq = 909.0
from gui_map import MapWindow
m = MapWindow(root, app); root.update()
labels = [m.via_checks[k]["text"] for k in ("main", "wifi 1")]
ok("the map lists your nodes with frequency and connection", labels[0].startswith("main - 909 MHz") and labels[1] == "wifi 1 - Wi-Fi", labels)
names = lambda: {p[5].split("\n")[0] for p in m.points()}
ok("all nodes are shown at first", {"OnMain", "OnWifi"} <= names(), names())
m.via_vars["wifi 1"].set(False)
ok("unticking a node hides what only it heard", "OnWifi" not in names() and "OnMain" in names(), names())
m.via_vars["main"].set(False)
ok("...a node heard by none of the ticked nodes is hidden", "OnMain" not in names(), names())
m.via_vars["wifi 1"].set(True)
ok("...and one heard by a ticked node shows", {"OnMain", "OnWifi"} <= names(), names())
ok("the info box says who heard it", any("heard by: main, wifi 1" in p[5] for p in m.points()))
m.destroy()
root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
