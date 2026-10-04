import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""Renaming the node in Options > Node: radio, then pressing OK, must keep the new name (the Connect page's 'Node nick' used to save the old one back)."""
import tkinter as tk
from unittest import mock

import gui_dialogs
import mcIRC

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

root = tk.Tk()
app = mcIRC.App(root, demo=True); root.update()
app.settings["node_name"] = "Traffic_bot"
app.save = lambda: None                                     # never touch the real settings file
dlg = gui_dialogs.OptionsDialog(app); root.update()
ok("Options shows the current name on the Connect page", dlg.vars["node_name"].get() == "Traffic_bot")
node = {"info": {"name": "mcIRC_bot", "adv_lat": 0, "adv_lon": 0, "radio_freq": 909.0, "radio_bw": 62.5, "radio_sf": 7, "radio_cr": 5, "tx_power": 22,
                 "max_tx_power": 22, "public_key": "ab" * 32},
        "ver": {"model": "Heltec V3", "ver": "v1.16.0", "max_contacts": 350}, "core": {"battery_mv": 4100, "uptime_secs": 60}, "radio": {}}
dlg.node_pages.fill(node)                                    # what happens after 'Write changes to node' re-reads the node
root.update()
ok("after reading the renamed node, the app uses the new name", app.settings["node_name"] == "mcIRC_bot", app.settings["node_name"])
ok("...and the Connect page shows it too", dlg.vars["node_name"].get() == "mcIRC_bot", dlg.vars["node_name"].get())
with mock.patch.object(gui_dialogs.messagebox, "showerror", lambda *a, **k: None):
    dlg.apply()
ok("pressing OK / Apply keeps the new name (it used to save the old one back)", app.settings["node_name"] == "mcIRC_bot", app.settings["node_name"])
ok("the node's empty position does not wipe the position set in Options", (app.settings["node_lat"], app.settings["node_lon"]) != (0.0, 0.0))
# ---- after a rename is written, mcIRC offers a flood advert (others only learn the new name from an advert); nothing is sent without a yes
pages = dlg.node_pages
pages.old = dict(pages.old or {})
sent, asked = [], []
app.connected = True
app.bg = lambda fn, done: done(fn())
import gui_nodecfg
with mock.patch.object(gui_nodecfg, "write_node", lambda old, new: ([("name", True, "ok")], False)),         mock.patch.object(pages, "collect", lambda: dict(pages.old, name="Third_name")), mock.patch.object(pages, "read", lambda: None),         mock.patch.object(pages, "act", lambda name: sent.append(name)),         mock.patch.object(gui_dialogs.messagebox, "askyesno", lambda title, text, **k: asked.append(title) or False):
    pages.write()
ok("after a rename mcIRC asks before sending an advert", asked == ["Node renamed"] and sent == [], (asked, sent))
with mock.patch.object(gui_nodecfg, "write_node", lambda old, new: ([("name", True, "ok")], False)),         mock.patch.object(pages, "collect", lambda: dict(pages.old, name="Third_name")), mock.patch.object(pages, "read", lambda: None),         mock.patch.object(pages, "act", lambda name: sent.append(name)),         mock.patch.object(gui_dialogs.messagebox, "askyesno", lambda title, text, **k: True):
    pages.write()
ok("...and on yes it sends a flood advert", sent == ["floodadv"], sent)
root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
