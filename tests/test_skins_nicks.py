import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""Skins (a picture becomes a banner + pane colours), right-click on names in the chat text, and the /slap and /dolphins addons."""
import importlib.util, shutil, tempfile, tkinter as tk
from unittest import mock

from PIL import Image

import gui_skins, mcIRC
from gui_addons import AddonBase, AddonAPI

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

# ---- skin loading, in a throw-away skins folder
tmp = tempfile.mkdtemp()
gui_skins.SKIN_DIR = tmp
Image.new("RGB", (300, 40), (200, 60, 20)).save(os.path.join(tmp, "Loose.png"))
os.makedirs(os.path.join(tmp, "Folder")); Image.new("RGB", (100, 100), (10, 20, 120)).save(os.path.join(tmp, "Folder", "banner.jpg"))
open(os.path.join(tmp, "Folder", "skin.json"), "w").write('{"banner_height": 70, "mode": "tile", "theme": {"sel_bg": "#123456", "pane_bg": "not a colour"}}')
os.makedirs(os.path.join(tmp, "Empty"))
open(os.path.join(tmp, "Broken.png"), "wb").write(b"not an image")
ok("list_skins finds loose images and folders with a banner, not empty folders", gui_skins.list_skins() == ["Broken", "Folder", "Loose"], gui_skins.list_skins())
ok("a loose picture loads with the default banner", gui_skins.load("Loose").height == 56)
f = gui_skins.load("Folder")
ok("skin.json sets height, mode and valid colour overrides only", f.height == 70 and f.mode == "tile" and f.overrides == {"sel_bg": "#123456"}, f.overrides)
ok("a broken or unknown skin loads as None, never raises", gui_skins.load("Broken") is None and gui_skins.load("Nope") is None and gui_skins.load("Empty") is None)
ok("'None' and path tricks are refused", gui_skins.load("None") is None and gui_skins.load("../x") is None and gui_skins.load("a/b") is None)
import gui_themes
dark = gui_skins.themed(gui_themes.THEMES["Classic mIRC"], gui_skins.load("Folder"))
light = gui_skins.themed(gui_themes.THEMES["Classic mIRC"], gui_skins.load("Loose"))
lum = lambda h: gui_skins._lum(gui_skins._rgb(h))
ok("a dark picture gives a dark, readable pane", lum(dark["pane_bg"]) < 0.5 and lum(dark["pane_fg"]) > 0.7, (dark["pane_bg"], dark["pane_fg"]))
ok("the skin's override wins", dark["sel_bg"] == "#123456")
ok("selection colour keeps white text readable", lum(light["sel_bg"]) < 0.4)
ok("no skin leaves the theme untouched", gui_skins.themed(gui_themes.THEMES["Night"], None) is gui_themes.THEMES["Night"])
for w, mode in ((900, "cover"), (900, "stretch"), (900, "tile")):
    s = gui_skins.load("Folder"); s.mode = mode
    r = gui_skins._render(s, w)
    ok(f"banner renders at the window width ({mode})", r.size == (w, s.height), r.size)

# ---- the real window
root = tk.Tk()
app = mcIRC.App(root, demo=True)
root.update()
ok("no banner without a skin", getattr(app, "_banner", None) is None)
app.settings["skin"] = "Loose"; app.apply_theme(); root.update()
ok("choosing a skin shows a banner above the toolbar", app._banner.winfo_ismapped() and app._banner.winfo_y() < app.toolbar.winfo_y(), app._banner.winfo_y())
ok("...and recolours the panes from the picture", app.theme["pane_bg"] != gui_themes.THEMES["Classic mIRC"]["pane_bg"])
app.settings["skin"] = "None"; app.apply_theme(); root.update()
ok("choosing None removes the banner again", getattr(app, "_banner", None) is None)

# ---- right-click on a name in the chat text
w = app.windows["Public"]; app.select_window("Public"); root.update()
t = w.text
start = t.search("Alice", "1.0")
ok("names in chat lines carry the nickname tag", start and "nickname" in t.tag_names(start))
x, y, _, _ = t.bbox(start)
shown = []
class FakeMenu:
    def __init__(self, *a, **k): self.items = []
    def add_command(self, label=None, command=None, **k): self.items.append((label, command))
    def add_separator(self): pass
    def tk_popup(self, *a): shown.append(self)
ev = mock.Mock(x=x + 2, y=y + 2, x_root=0, y_root=0)
with mock.patch.object(tk, "Menu", FakeMenu):
    app._chat_menu(ev, w)
labels = [l for l, _ in shown[0].items] if shown else []
ok("right-click on a name offers private message, reply, node info and copy", labels[:2] == ["Private message with Alice", "Reply to Alice"] and "Node info..." in labels and "Copy name" in labels, labels)
dict(shown[0].items)["Reply to Alice"]()
ok("Reply puts @[Alice] at the start of the message line", app.entry.get() == "@[Alice] ", app.entry.get())
shown.clear()
with mock.patch.object(tk, "Menu", FakeMenu):
    app._chat_menu(mock.Mock(x=1000, y=1000, x_root=0, y_root=0), w)       # empty area -> no menu
ok("right-click away from a name shows nothing", not shown)

# ---- lines restored from the log of an earlier session are clickable too
class FakeLog:
    path = ""
    def tail(self, n): return ["[17:26] <VA7HU - T-Deck> hello there", "Session Close: Sat Oct 03"]
    def stamp(self, *a): pass
    def append(self, *a): pass
old = mcIRC.ChatWindow(root, "#old", "t", app.font, FakeLog(), 10, app.theme, "Me")
old.frame.pack(); root.update()
i = old.text.search("VA7HU", "1.0")
ok("a name in an old (restored) line carries the nickname tag", i and "nickname" in old.text.tag_names(i))
nick_range = old.text.tag_ranges("nickname")
ok("...covering exactly the name", len(nick_range) == 2 and old.text.get(nick_range[0], nick_range[1]) == "VA7HU - T-Deck", [str(r) for r in nick_range])
old.frame.destroy()

# ---- the addons add their entries when installed
def load_addon(name):
    spec = importlib.util.spec_from_file_location("addon_" + name, os.path.join(ROOT, "packages", name, name + ".py"))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    api = AddonAPI(app, name); inst = mod.Addon(api); inst.on_load(); return inst, api
slap, sapi = load_addon("slap")
dol, dapi = load_addon("dolphins")
sent = []
with mock.patch.object(app, "send_to", lambda ch, text: sent.append((ch, text))):
    app.entry.delete(0, "end")
    app.commands["slap"][0]("Bob")
    app.commands["slap"][0]("Bob")                                     # second one inside the rate limit
    app.commands["dolphins"][0]("")
    app.commands["dolphins"][0]("Bob")                                 # also rate limited
    ok("/slap sends one mention-style line to the channel in front", len(sent) >= 1 and sent[0][0] == "Public" and sent[0][1] == "slaps @[Bob] around a bit with a large trout", sent)
    ok("a second slap inside 10 seconds is refused", len([s for s in sent if "slaps" in s[1]]) == 1)
    ok("/dolphins sends a pod", any("\U0001F42C" in s[1] for s in sent), sent)
    slap._last = dol._last = 0
    sent.clear(); app.commands["dolphins"][0]("Bob")
    ok("/dolphins Bob sends them to one person with a mention", sent and "@[Bob]" in sent[0][1], sent)
    sent.clear(); slap._last = 0; app.select_window("Status"); app.commands["slap"][0]("Bob")
    ok("nothing is sent from the Status window", not sent)
shown.clear()
app.select_window("Public")
with mock.patch.object(tk, "Menu", FakeMenu):
    t.update(); app._chat_menu(ev, w)
labels = [l for l, _ in shown[0].items]
ok("with the addons loaded the menu offers the trout and the dolphins", "Slap Alice with a large trout" in labels and "Send Alice dolphins" in labels, labels)
sapi._cleanup(); dapi._cleanup()
ok("unloading the addons removes the commands", "slap" not in app.commands and "dolphins" not in app.commands)

root.destroy()
shutil.rmtree(tmp, ignore_errors=True)
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
