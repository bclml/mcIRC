import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""Every switched-on addon has its own submenu in the Addons menu: its own entries, then Settings... and Switch off.  No radio."""
import importlib.util
import tkinter as tk
from unittest import mock

import mcIRC
import gui_addons
from gui_addons import AddonAPI

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

root = tk.Tk()
app = mcIRC.App(root, demo=True); root.update()
for n in list(app.addons.loaded): app.addons.unload(n)           # only the packages are tested, not the copies installed on this PC
app.save = lambda: None                                          # never touch the real settings file

def submenu(title):
    am = app.addon_menu
    for i in range(am.index("end") + 1 if am.index("end") is not None else 0):
        if am.type(i) == "cascade" and am.entrycget(i, "label") == title:
            sub = root.nametowidget(am.entrycget(i, "menu"))
            return [sub.entrycget(j, "label") if sub.type(j) != "separator" else "---" for j in range(sub.index("end") + 1)], sub
    return None, None

def load(pkg, main=None):
    spec = importlib.util.spec_from_file_location(f"t_menu_{pkg}", os.path.join(ROOT, "packages", pkg, (main or pkg) + ".py"))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    api = AddonAPI(app, pkg); inst = mod.Addon(api); api.display = inst.title
    app.addons.loaded[pkg] = (inst, api)
    inst.on_load(); api._draw_menu(); root.update()
    return inst, api

sys.path[:0] = [os.path.join(ROOT, "packages", p) for p in ("mesh_bot", "map_uploader", "packet_upload", "dolphins")]
for m in ("meshbot_cmds", "meshbot_common", "mapup_core", "pktup_core", "dolphin_actions", "dolphin_scene"): sys.modules.pop(m, None)   # the packages' own copies
mb, _ = load("mesh_bot")
items, _ = submenu("Mesh bot")
ok("an addon with no entries of its own still gets a submenu: Settings... and Switch off", items == ["Settings...", "Switch off"], items)

mu, mu_api = load("map_uploader")
items, sub = submenu("Map uploader")
ok("an addon's own entries come first, then Settings... and Switch off", items == ["Uploading on / off", "Recent uploads...", "---", "Settings...", "Switch off"], items)
ok("...and the addon's name isn't repeated in front of every entry", not any("Map uploader" in i for i in items))
ok("the map uploader stays off until switched on", not mu_api.get("enabled", False))
mu.toggle(); ok("Uploading on / off switches it on", mu_api.get("enabled", False) is True)
mu.toggle(); ok("...and off again", mu_api.get("enabled", False) is False)
mu.recent = [(0, "repeater", "Hilltop")]; mu.uploaded = 1
ok("Recent uploads lists what went to the map", "repeater" in mu.recent_text() and "Hilltop" in mu.recent_text() and "OFF" in mu.recent_text(), mu.recent_text())
win = mu_api.show_text("t", mu.recent_text); root.update()
txt = [w for w in win.winfo_children() if isinstance(w, tk.Text)][0].get("1.0", "end")
ok("show_text: a small window with the text", "Hilltop" in txt, txt)
win.destroy()

pu, pu_api = load("packet_upload")
items, _ = submenu("Packet upload")
ok("packet upload: Sending on / off and Status...", items[:2] == ["Sending on / off", "Status..."], items)
ok("...status says it is off, and that no analyzer is ticked yet (none is when installed)", "OFF" in pu.status_text() and "No analyzers ticked" in pu.status_text(), pu.status_text())
pu.toggle()
ok("...switching it on without an area code sends nothing", pu_api.get("enabled") is True and pu.clients == {} and not pu.starting)
pu.toggle()

with mock.patch("tkinter.simpledialog.askstring", lambda *a, **k: None):
    dol, dol_api = load("dolphins")
    items, _ = submenu("Dolphins")
    ok("dolphins: Send dolphins... and the picture switch", items[:2] == ["Send dolphins...", "Picture behind the channel list on / off"], items)
    sent = []
    dol_api.send_current = lambda text: sent.append(text) or True
    dol.ask_dolphins()
    ok("...cancelling 'Send dolphins' sends nothing", sent == [])

opened = []
with mock.patch("gui_addonsettings.open_settings", lambda app_, name, parent=None: opened.append(name)):
    _, sub = submenu("Mesh bot"); sub.invoke(0)
ok("Settings... opens that addon's settings window", opened == ["mesh_bot"], opened)

app.settings.setdefault("addons_enabled", {})["mesh_bot"] = True
_, sub = submenu("Mesh bot"); sub.invoke(1); root.update(); root.update()
ok("Switch off switches the addon off and removes its submenu", "mesh_bot" not in app.addons.loaded and submenu("Mesh bot")[0] is None
   and app.settings["addons_enabled"]["mesh_bot"] is False)

# ---- ON/OFF switches on the toolbar
def switch_btn(api): return getattr(api, "_switch_btn", None)
api_mu = app.addons.loaded["map_uploader"][1]
api_mu.add_switch(mu.switch, False, mu.toggle); root.update()
b = switch_btn(api_mu)
ok("an addon with 'switch' gets an ON/OFF switch on the toolbar", b is not None and b.cget("text") == "Map uploader: OFF", b and b.cget("text"))
b.invoke(); root.update()
ok("pressing it switches the addon on - through its own toggle()", mu_api.get("enabled") is True and b.cget("text") == "Map uploader: ON")
mu_api.set("enabled", False); root.after(1600, root.quit); root.mainloop()
ok("...and it follows a change made elsewhere (its settings window)", b.cget("text") == "Map uploader: OFF", b.cget("text"))
mu_api.set("_toolbar", False); mu_api._draw_switch(); root.update()
ok("'Show its switch on the toolbar' unticked: the switch goes", switch_btn(mu_api) is None and not b.winfo_exists())
mu_api.set("_toolbar", True); mu_api._draw_switch(); root.update()
ok("...ticked again: it's back", switch_btn(mu_api) is not None and switch_btn(mu_api).winfo_exists())
sys.path[:0] = [os.path.join(ROOT, "packages", p) for p in ("fun_bot", "weather_bot", "bot_help", "channel_list")]
for pkg in ("fun_bot", "weather_bot", "mesh_bot", "channel_list", "bot_help", "map_uploader", "packet_upload"):
    spec = importlib.util.spec_from_file_location(f"t_sw_{pkg}", os.path.join(ROOT, "packages", pkg, pkg + ".py"))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    ok(f"{pkg} has an ON/OFF switch", getattr(mod.Addon, "switch", None) == "enabled")
last_btn = switch_btn(mu_api)
for n in list(app.addons.loaded): app.addons.unload(n)
ok("unloading removes the switch too", not last_btn.winfo_exists())
ok("unloading removes every addon's submenu", all(submenu(t)[0] is None for t in ("Map uploader", "Packet upload", "Dolphins")))
root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
