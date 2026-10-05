import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""Help > Check for updates also updates the addons: with the app, or on their own when only they are newer.  Nothing is downloaded."""
import tkinter as tk
from unittest import mock

import gui_addons as ga
import gui_update_ui as gui
import mcIRC

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

root = tk.Tk()
app = mcIRC.App(root, demo=True); root.update()
app.bg = lambda fn, done: done(fn())
mgr = app.addons
versions = {"dolphins": "1.1.1", "weather_bot": "1.0.5"}
CATALOG = [{"name": "dolphins", "version": "1.2.0", "title": "Dolphins", "path": "packages/dolphins"},
           {"name": "weather_bot", "version": "1.0.5", "title": "Weather bot", "path": "packages/weather_bot"}]
installed_from_catalog, reloaded = [], []
def from_catalog(e):
    installed_from_catalog.append(e["name"])
    versions[e["name"]] = e["version"]
    return {"name": e["name"]}
patches = [mock.patch.object(mgr, "discover", lambda: list(versions)), mock.patch.object(mgr, "installed_version", lambda n: versions[n]),
           mock.patch.object(ga, "fetch_catalog", lambda: CATALOG), mock.patch.object(ga, "install_from_catalog", from_catalog),
           mock.patch.object(mgr, "reload", lambda n: reloaded.append(n)), mock.patch.object(gui.messagebox, "askokcancel", lambda *a, **k: True)]
for p in patches: p.start()

# ---- mcIRC is up to date, an addon is not
with mock.patch.object(gui.gu, "check", lambda: {"newer": False, "local": "2.0.2", "remote": "2.0.2"}):
    d = gui.UpdateDialog(app)
log = lambda: d.log.get("1.0", "end")
ok("the check finds a newer addon even when mcIRC itself is up to date", "1 addon update" in d.head["text"] and "dolphins': 1.1.1 -> 1.2.0" in log(), (d.head["text"], log()))
ok("...and offers to install it", str(d.btn_go["state"]) == "normal")
mgr.loaded["dolphins"] = (object(), None)
with mock.patch.object(gui.gu, "apply_update", lambda **k: (_ for _ in ()).throw(AssertionError("the app must not be updated"))):
    d.install()
ok("only the addon is installed (from the catalog), not the app", installed_from_catalog == ["dolphins"], installed_from_catalog)
ok("...and it runs the new version at once, no restart", reloaded == ["dolphins"] and "running the new version" in d.head["text"] and str(d.btn_restart["state"]) == "disabled", (reloaded, d.head["text"]))
mgr.loaded.pop("dolphins", None)
d.destroy()

# ---- both newer: the app update brings the addon packages along
versions["dolphins"], installed_from_catalog[:], reloaded[:] = "1.1.1", [], []
RES = {"old": "2.0.2", "new": "2.0.3", "updated": ["mcIRC.py"], "added": [], "kept": [], "backup": "backup/x"}
def from_packages():
    versions["dolphins"] = "1.2.0"
    return [("dolphins", "1.1.1", "1.2.0")]
with mock.patch.object(gui.gu, "check", lambda: {"newer": True, "local": "2.0.2", "remote": "2.0.3"}), \
     mock.patch.object(gui.gu, "apply_update", lambda **k: RES), mock.patch.object(mgr, "update_installed", from_packages):
    d = gui.UpdateDialog(app)
    ok("both newer: 'mcIRC 2.0.3 + 1 addon update'", "mcIRC 2.0.3" in d.head["text"] and "1 addon update" in d.head["text"], d.head["text"])
    d.install()
ok("the app update brings the addon along (not downloaded twice)", installed_from_catalog == [] and "Addon 'dolphins' updated 1.1.1 -> 1.2.0" in log(), (installed_from_catalog, log()))
ok("...then Restart is offered", str(d.btn_restart["state"]) == "normal" and "restart" in d.head["text"])
d.destroy()

# ---- the catalog can't be read: the app check still works
with mock.patch.object(gui.gu, "check", lambda: {"newer": False, "local": "2.0.2", "remote": "2.0.2"}), \
     mock.patch.object(ga, "fetch_catalog", lambda: (_ for _ in ()).throw(OSError("offline"))):
    d = gui.UpdateDialog(app)
ok("no catalog: still says the app is up to date, and why addons weren't checked", "up to date" in d.head["text"] and "Could not read the addon catalog" in log(), (d.head["text"], log()))
d.destroy()
for p in patches: p.stop()
root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
