import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""The Update button in Tools > Addons: compares the installed addons with the online catalog and installs the newer ones."""
import tkinter as tk
from unittest import mock

import gui_addons as ga
import gui_dialogs
import mcIRC

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

cat = [{"name": "slap", "version": "1.0.3", "path": "packages/slap"}, {"name": "dolphins", "version": "1.0.1", "path": "packages/dolphins"},
       {"name": "not_installed", "version": "9.0", "path": "packages/x"}]
up = ga.updates_available({"slap": "1.0.0", "dolphins": "1.0.1", "auto_reply": "1.1.2"}, cat)
ok("only installed addons with a newer catalog version are offered", [(n, o, v) for n, o, v, _ in up] == [("slap", "1.0.0", "1.0.3")], up)
ok("version numbers compare as numbers (1.0.10 > 1.0.9)", ga.updates_available({"a": "1.0.9"}, [{"name": "a", "version": "1.0.10"}]) != [])

root = tk.Tk()
app = mcIRC.App(root, demo=True); root.update()
app.bg = lambda fn, done: done(fn())                            # run the background steps straight away
app.addons.discover = lambda: ["slap"]                          # (the same on every machine: CI has no addons installed)
app.addons.installed_version = lambda n: "1.0.0"
dlg = gui_dialogs.AddonsDialog(app); root.update()
ok("the Addons window has an Update button", any(w.cget("text") == "Update" for f in dlg.winfo_children() for w in f.winfo_children() if hasattr(w, "cget") and "text" in w.keys()))
installed = []
loaded_before = True
from types import SimpleNamespace
app.addons.loaded.setdefault("slap", (SimpleNamespace(title="Slap", version="1.0.0", author="", description=""), None))
with mock.patch.object(ga, "fetch_catalog", lambda: [{"name": "slap", "version": "99.0.0", "path": "packages/slap"}]), \
        mock.patch.object(ga, "install_from_catalog", lambda e: installed.append(e["name"]) or {"name": e["name"]}), \
        mock.patch.object(app.addons, "reload", lambda n: installed.append("reload " + n)), \
        mock.patch.object(gui_dialogs.messagebox, "askokcancel", lambda *a, **k: True) as ask, \
        mock.patch.object(gui_dialogs.messagebox, "showinfo", lambda *a, **k: installed.append("info " + a[1])):
    dlg.update_addons()
ok("a newer slap in the catalog is downloaded and installed", "slap" in installed, installed)
ok("...a loaded addon is reloaded so the new version runs at once", ("reload slap" in installed) == loaded_before, installed)
ok("...and the person is told what was updated", any(i.startswith("info Updated: slap 99.0.0") for i in installed), installed)
installed.clear()
with mock.patch.object(ga, "fetch_catalog", lambda: [{"name": "slap", "version": "0.1", "path": "packages/slap"}]), \
        mock.patch.object(ga, "install_from_catalog", lambda e: installed.append(e["name"])), \
        mock.patch.object(gui_dialogs.messagebox, "showinfo", lambda *a, **k: installed.append("info " + a[1])):
    dlg.update_addons()
ok("nothing newer -> 'up to date', nothing installed", installed == ["info All your addons are up to date."], installed)
installed.clear()
with mock.patch.object(ga, "fetch_catalog", lambda: 1 / 0), mock.patch.object(gui_dialogs.messagebox, "showerror", lambda *a, **k: installed.append("error")):
    app.bg = lambda fn, done: done(ZeroDivisionError("offline"))
    dlg.update_addons()
ok("offline -> a clear error, no crash", installed == ["error"], installed)
root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
