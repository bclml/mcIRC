import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""The Modern look addon: flat chrome in the theme's / skin's colours, and switching it off gives the exact classic look back."""
import importlib.util, tkinter as tk
from tkinter import ttk

import mcIRC
from gui_addons import AddonAPI
from gui_common import BG

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

root = tk.Tk()
app = mcIRC.App(root, demo=True); root.update()
def snapshot():
    out = {}
    def walk(w):
        for o in ("bg", "fg", "relief", "bd", "font"):
            try: out[(str(w), o)] = str(w.cget(o))
            except tk.TclError: pass
        for ch in w.winfo_children(): walk(ch)
    walk(root)
    return out, ttk.Style().theme_use()
before = snapshot()
spec = importlib.util.spec_from_file_location("addon_modern_look", os.path.join(ROOT, "packages", "modern_look", "modern_look.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
api = AddonAPI(app, "modern_look"); inst = mod.Addon(api)
inst.on_load(); app.addons.loaded["modern_look"] = (inst, api); root.update()
tb_buttons = [w for w in app.toolbar.winfo_children() if w.winfo_class() == "Button"]
ok("the toolbar is no longer classic grey", app.toolbar.cget("bg").lower() != BG.lower(), app.toolbar.cget("bg"))
ok("toolbar buttons are flat and take the bar colour", tb_buttons and all(b.cget("relief") == "flat" and b.cget("bg") == app.toolbar.cget("bg") for b in tb_buttons))
ok("ttk widgets use the flat 'clam' style", ttk.Style().theme_use() == "clam")
ok("the chat text loses its 3D border", app.windows["Public"].text.cget("relief") == "flat")
b = tb_buttons[0]
b.event_generate("<Enter>"); root.update()
ok("a button lights up under the mouse", b.cget("bg").lower() == inst.c["hover"].lower(), b.cget("bg"))
b.event_generate("<Leave>"); root.update()
ok("...and goes back when the mouse leaves", b.cget("bg") == app.toolbar.cget("bg"))
old_bar = app.toolbar.cget("bg")
app.settings["skin"] = "Sunset"; app.apply_theme(); root.update()
ok("changing the skin recolours the chrome straight away", app.toolbar.cget("bg") != old_bar, (old_bar, app.toolbar.cget("bg")))
dlg = tk.Toplevel(root); lab = tk.Label(dlg, text="new dialog"); lab.pack(); root.update()
inst.on_tick(); root.update()
ok("windows opened later are restyled too", lab.cget("bg").lower() != BG.lower() and lab.cget("bg").lower() != "systembuttonface", lab.cget("bg"))
dlg.destroy(); inst.on_tick()
app.settings["skin"] = "None"; app.apply_theme(); root.update()
inst.on_unload(); app.addons.loaded.pop("modern_look"); root.update()
after = snapshot()
diff = [k for k in before[0] if before[0][k] != after[0].get(k)]
ok("switching it off gives the exact classic look back", not diff and after[1] == before[1], (diff[:5], before[1], after[1]))
root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
