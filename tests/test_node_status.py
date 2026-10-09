import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""The status bar shows every node (main + More nodes) with its battery, and warns when 'connected' isn't the whole story:
a low battery, or our messages no longer repeated.  No radio."""
import json
import tkinter as tk
from types import SimpleNamespace
from unittest import mock

import gui_nodestatus as ns
import meshcore_io as io
import mcIRC

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

ok("connections are named plainly", ns.describe_connection(["-t", "192.168.1.57", "-p", "5000"]) == "Wi-Fi 192.168.1.57"
   and ns.describe_connection(["-s", "COM4"]) == "USB COM4" and ns.describe_connection(["-a", "AA:BB"]) == "Bluetooth")
with mock.patch.object(io, "execute_mesh_command", lambda *a, **k: SimpleNamespace(stdout=json.dumps({"battery_mv": 3912, "uptime_secs": 5}), stderr="")):
    ok("the battery is read from the node's core stats", ns.battery_mv(["-s", "COM4"]) == 3912)
with mock.patch.object(io, "execute_mesh_command", lambda *a, **k: SimpleNamespace(stdout=json.dumps({"battery_mv": 0}), stderr="")):
    ok("...no battery reported -> None (nothing shown)", ns.battery_mv(["-s", "COM4"]) is None)

root = tk.Tk()
app = mcIRC.App(root, demo=True); root.update()
lines = []
app.status_line = lambda text, level="info", **k: lines.append((level, text))
app._h_state("connected", "-t 192.168.1.57 -p 5000")
ok("the main node: 'Connected (Wi-Fi 192.168.1.57)'", app.sb_state["text"] == "Connected (Wi-Fi 192.168.1.57)", app.sb_state["text"])
app._h_battery("main", 3912)
ok("...with its battery", app.sb_state["text"].endswith("· 3.91 V") and app.sb_state["fg"] in ("#000000", "black"), app.sb_state["text"])
app._h_battery("main", 3420)
ok("a low battery turns it red and says why in Status", "LOW" in app.sb_state["text"] and app.sb_state["fg"] == "#c00000"
   and any(l == "error" and "battery is low (3.42 V)" in t for l, t in lines), (app.sb_state["text"], lines))
lines.clear(); app._h_battery("main", 3450)
ok("...said once, not on every reading", lines == [])
app._h_battery("main", 3700)
ok("charged again: back to normal, and it says so", "LOW" not in app.sb_state["text"] and any("fine again" in t for _, t in lines))

# the second node gets its own status
app.set_node_state("wifi 1", "connecting")
lab = app._node_labels["wifi 1"]
ok("a node from More nodes has its own status next to the main one", lab["text"] == "wifi 1: connecting..." and lab.master is app.sb_nodes)
app.set_node_state("wifi 1", "connected"); app._h_battery("wifi 1", 4050)
ok("...connected, with its battery", lab["text"] == "wifi 1: connected · 4.05 V", lab["text"])
app.set_node_state("wifi 1", "down")
ok("...and red when it stops answering", lab["text"].startswith("wifi 1: NOT RESPONDING") and lab["fg"] == "#c00000", lab["text"])
app.remove_node("wifi 1", ask=False)
ok("removing the node removes its status", "wifi 1" not in app._node_labels and not lab.winfo_exists())

# messages nobody repeats
lines.clear()
app.note_repeats({"sent": True, "repeats": 0}); app.note_repeats({"sent": True, "repeats": 0}); app.note_repeats({"sent": True, "repeats": 0})
ok("no repeats ever heard (no repeater in range): no warning", lines == [] and "not heard" not in app.sb_state["text"])
app.note_repeats({"sent": True, "repeats": 2})
for _ in range(ns.UNHEARD_WARN): app.note_repeats({"sent": True, "repeats": 0})
ok(f"after repeats were heard, {ns.UNHEARD_WARN} in a row unrepeated: warning and red status",
   any(l == "error" and "not repeated by anyone" in t for l, t in lines) and "not heard" in app.sb_state["text"] and app.sb_state["fg"] == "#c00000", (lines, app.sb_state["text"]))
lines.clear(); app.note_repeats({"sent": True, "repeats": 1})
ok("...and back to normal once a repeat is heard", "not heard" not in app.sb_state["text"] and any("pass your messages on again" in t for _, t in lines))
app._h_state("stopped", "")
ok("disconnected: 'Not connected', no battery shown", app.sb_state["text"] == "Not connected")
root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
