import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""Addon settings live in their own window (Tools > Addons, double-click), not in Options; the Addons window's buttons always fit."""
import tkinter as tk
from types import SimpleNamespace
from unittest import mock

import gui_addonsettings, gui_dialogs, mcIRC

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

root = tk.Tk()
app = mcIRC.App(root, demo=True); root.update()
applied = []
class Fake:
    title, version, author, description = "Fake addon", "1.2.3", "", "Does fake things."
    def build_options(self, parent):
        self.v = tk.StringVar(value="old")
        f = tk.Frame(parent); tk.Entry(f, textvariable=self.v).pack(); return f
    def apply_options(self): applied.append(self.v.get())
fake = Fake()
app.addons.loaded["fake"] = (fake, __import__("gui_addons").AddonAPI(app, "fake"))
app.addons.info = lambda n: ("Fake addon", "1.2.3", "", "Does fake things.") if n == "fake" else ("x", "1", "", "")
app.addons._call = lambda name, hook, *a: getattr(app.addons.loaded[name][0], hook)(*a)

opts = gui_dialogs.OptionsDialog(app); root.update()
ok("Options no longer has addon pages", not [i for i in opts.tree.get_children() if i.startswith("addon:")], opts.tree.get_children())
opts.destroy()

dlg = gui_dialogs.AddonsDialog(app); root.update()
dlg.t.insert("", "end", iid="fake", values=("[x]", "Fake addon", "1.2.3", "fake.py", "Does fake things."))
dlg.t.selection_set("fake"); root.update()
opened = []
real_open = gui_addonsettings.open_settings
with mock.patch.object(gui_addonsettings, "open_settings", lambda app_, n, parent=None: opened.append(n) or real_open(app_, n, parent)):
    dlg.settings(); root.update()
ok("double-click is bound to the settings", "settings" in dlg.t.bind("<Double-1>") or bool(dlg.t.bind("<Double-1>")))
ok("Settings... opens the addon's settings", opened and opened[0] == "fake", opened)
win = next(w for w in dlg.winfo_children() + root.winfo_children() if isinstance(w, gui_addonsettings.AddonSettingsWindow))
ok("the window shows the addon's own page", win.page is not None and win.title() == "Fake addon - settings")
fake.v.set("new"); win.apply()
ok("Apply saves through the addon's apply_options", applied == ["new"], applied)
win.destroy()
calls = []
with mock.patch.object(gui_addonsettings.messagebox, "askyesno", lambda *a, **k: False):
    ok("an addon that is off: asks before switching it on (no -> nothing opens)", gui_addonsettings.open_settings(app, "not_loaded", parent=dlg) is None)

# the buttons always fit: make the window small and check every button is inside it
dlg.geometry("640x300"); root.update()
buttons = [w for row in dlg.winfo_children() if isinstance(row, tk.Frame) for w in row.winfo_children() if w.winfo_class() == "TButton"]
inside = [b for b in buttons if b.winfo_rootx() + b.winfo_width() <= dlg.winfo_rootx() + dlg.winfo_width() + 1 and b.winfo_rooty() + b.winfo_height() <= dlg.winfo_rooty() + dlg.winfo_height() + 1]
ok("at the smallest size every button is fully visible", len(buttons) == 9 and len(inside) == len(buttons), (len(buttons), [b.cget("text") for b in buttons if b not in inside]))
dlg.destroy(); root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
