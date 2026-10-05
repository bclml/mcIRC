import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""Dolphins addon: a picture behind the channel list, each channel name in a box.  No radio, nothing is sent."""
import importlib.util, tempfile, time
import tkinter as tk
from tkinter import ttk

sys.path.insert(0, os.path.join(ROOT, "packages", "dolphins"))
import dolphin_scene

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

img = dolphin_scene.scene(150, 560)
ok("the built-in dolphins are drawn at the list's own size", img.size == (150, 560))
px = [img.getpixel((x, y)) for x in range(0, 150, 5) for y in range(240, 560, 5)]
ok("...and there are dolphins in it (grey bodies in the blue sea)", sum(1 for r, g, b in px if abs(r - g) < 25 and abs(g - b) < 30 and r > 100) > 20)

spec = importlib.util.spec_from_file_location("dolph_pkg", os.path.join(ROOT, "packages", "dolphins", "dolphins.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
for fit in mod.FITS:
    ok(f"a picture is fitted to the list ({fit})", mod.render(img, 200, 300, fit, 0.3, "#102030").size == (200, 300))
faded = mod.render(img.resize((10, 10)), 10, 10, "stretch", 0.9, "#ffffff")
ok("fade blends the picture towards the list's colour", min(faded.getpixel((5, 5))) > 200, faded.getpixel((5, 5)))

import mcIRC
from gui_addons import AddonAPI
root = tk.Tk()
root.geometry("900x560")
app = mcIRC.App(root, demo=True); root.update()
if "dolphins" in app.addons.loaded: app.addons.unload("dolphins")      # the installed copy (an older version): only the package is tested
api = AddonAPI(app, "dolphins")
vals = {}
api.get = lambda k, d=None: vals.get(k, d)
api.set = lambda k, v: vals.__setitem__(k, v)
logged = []
api.log = lambda text, level="info": logged.append((level, text))
inst = mod.Addon(api)
inst.on_load()
def settle():
    for _ in range(12): root.update(); time.sleep(0.05)

settle()
ok("on by default when the addon is on: the list gets the dolphins", str(app.tree.cget("style")) == mod.STYLE)
st = ttk.Style()
ok("...with the picture as its background", any(e.startswith("DolphinBg") for e in st.element_names()), st.element_names())
ok("...and every name in a box in the list's own colour", st.lookup(mod.STYLE, "background") == app.theme["pane_bg"], (st.lookup(mod.STYLE, "background"), app.theme["pane_bg"]))
size1 = inst._size
root.geometry("900x720"); settle(); time.sleep(0.35); settle()
ok("resizing the window redraws the picture at the new size", inst._size != size1 and inst._size is not None, (size1, inst._size))

own = os.path.join(tempfile.mkdtemp(), "mine.png")
img.resize((60, 40)).save(own)
vals.update(bg_path=own, bg_fit="tile"); inst._size = None
inst.apply_background(); settle()
ok("your own picture works too", str(app.tree.cget("style")) == mod.STYLE and inst._img.size == (60, 40))
vals.update(bg_path=os.path.join(tempfile.mkdtemp(), "missing.png"))
inst.apply_background(); settle()
ok("a picture that can't be read: a note, and the plain list", str(app.tree.cget("style")) == "Treeview" and any(l == "warn" for l, _ in logged), logged)

vals.update(bg_path="")
inst.apply_background(); settle()
app.apply_theme(); settle()
ok("a new colour theme keeps the picture and recolours the boxes", str(app.tree.cget("style")) == mod.STYLE and st.lookup(mod.STYLE, "background") == app.theme["pane_bg"])
# ---- Pillow missing: a warning, a one-time offer to install it, and the picture as soon as it is installed
from unittest import mock
asked, installs = [], []
have = {"pil": False}
def no_pillow():
    if not have["pil"]: raise ImportError("No module named 'PIL'")
    return real_scene_module()
real_scene_module = mod.scene_module
app.bg = lambda fn, done: done(fn())
def fake_install():
    installs.append(1)
    have["pil"] = True                                        # "installed": the picture can be drawn again
    return True, "Successfully installed pillow"
with mock.patch.object(mod.messagebox, "askyesno", lambda *a, **k: asked.append(a) or True), mock.patch.object(mod, "install_pillow", fake_install),      mock.patch.object(mod, "scene_module", no_pillow), mock.patch.object(mod, "pillow_ok", lambda: have["pil"]):
    logged.clear()
    inst.apply_background(); settle()
    ok("no Pillow: the warning stays in the Status window", any(l == "warn" and "needs Pillow" in t for l, t in logged), logged)
    ok("...mcIRC offers to download and install it", len(asked) == 1)
    ok("...and after Yes it is installed and the dolphins appear (no restart)", installs == [1] and str(app.tree.cget("style")) == mod.STYLE)
    have["pil"] = False
    inst.apply_background(); settle()
    ok("it asks only once (the warning and the Install Pillow button remain)", len(asked) == 1 and sum("needs Pillow" in t for _, t in logged) == 2)
fails_shown = []
with mock.patch.object(mod, "install_pillow", lambda: (False, "ERROR: no internet")), mock.patch.object(mod.messagebox, "showerror", lambda *a, **k: fails_shown.append(a)):
    inst.get_pillow()
ok("a failed install says what to run instead", fails_shown and "pip install pillow" in fails_shown[0][1] and "no internet" in fails_shown[0][1])
logged.clear()
with mock.patch.object(mod, "scene_module", lambda: (_ for _ in ()).throw(ImportError("No module named 'dolphin_scene'"))),      mock.patch.object(mod.messagebox, "askyesno", lambda *a, **k: asked.append(a) or True):
    inst.apply_background(); settle()
ok("Pillow there but the drawing file missing: a note to update, never the install question",
   len(asked) == 1 and any("Update" in t for _, t in logged) and not any("needs Pillow" in t for _, t in logged), logged)
inst.apply_background(); settle()

# ---- reloading the addon (an update) on the same window: the picture comes back, no Tk error
errors = []
root.report_callback_exception = lambda *exc: errors.append(exc[1])
inst.on_unload(); settle()
inst2 = mod.Addon(api); inst2.on_load(); settle()
ok("after a reload (update) the picture comes back without an error", str(app.tree.cget("style")) == mod.STYLE and not errors, errors)
inst = inst2

# ---- fun actions: the right-click menu on a name, editable
acts = mod.helper("dolphin_actions")
ok("the fun actions start with the trout slap and the dolphins", [a["label"] for a in inst.actions()][:2] == ["Slap with a large trout", "Send a pod of dolphins"])
ok("...all in the Fun submenu", [l for _, l, _, g in app.name_actions if g == "Fun"] == [a["label"] for a in inst.actions()])
ok("a message without {nick} or too long for the mesh is refused", acts.problem("x", "no name here") and acts.problem("x", "@[{nick}] " + "a" * 120) and not acts.problem("x", "pats @[{nick}]"))
ok("names can't break out of the mention", acts.line({"text": "pats @[{nick}]"}, "Bo]b @x") == "pats @[Bob x]")
vals["actions"] = [{"label": "High five", "text": "gives @[{nick}] a high five ✋"}, {"label": "bad", "text": "no nick"}]
inst.register_actions()
ok("your own list replaces the defaults (broken entries left out)", [l for _, l, _, _ in app.name_actions] == ["High five"])
sent = []
with mock.patch.object(app, "send_to", lambda ch, text: sent.append((ch, text))):
    app.select_window("Public"); inst._last = 0
    inst.cmd_fun("high Bob")
    inst.cmd_fun("1 Carol")                                   # inside the rate limit
ok("/fun <name> <nick> sends it; a second one within 10 seconds is refused", sent == [("Public", "gives @[Bob] a high five ✋")], sent)
vals.pop("actions")
inst.register_actions()

vals.update(bg_on=False)
inst.apply_background(); settle()
ok("the picture can be switched off in the addon's settings", str(app.tree.cget("style")) == "Treeview")
vals.update(bg_on=True)
inst.apply_background(); settle()
inst.on_unload(); settle()
ok("switching the addon off gives the plain list back", str(app.tree.cget("style")) == "Treeview")
root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
