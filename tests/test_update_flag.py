import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""An update waiting: a big red UPDATE square flashes at the start of the toolbar until it is installed - also after a restart.  No internet."""
import time, tkinter as tk

import mcIRC
import gui_update
import gui_updflag

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

root = tk.Tk()
app = mcIRC.App(root, demo=True); root.update()
app.save = lambda: None
local = gui_update.local_version()
def pump(s=0.1):
    t = time.time()
    while time.time() - t < s: root.update()

app.show_update_flag(); pump()
ok("nothing waiting: no UPDATE square", getattr(app, "update_btn", None) is None)
app.note_updates("2999.1.1.1", []); pump()
b = app.update_btn
ok("a newer mcIRC found: a big red UPDATE square, first thing on the toolbar", b is not None and b.cget("text") == "UPDATE"
   and app.toolbar.pack_slaves()[0] is b and b.cget("bg") in (gui_updflag.RED, gui_updflag.DARK))
colours = set()
for _ in range(4): colours.add(b.cget("bg")); pump(0.35)
ok("...it flashes", colours == {gui_updflag.RED, gui_updflag.DARK}, colours)
ok("...and is remembered (it still shows after a restart, before the next daily check)", app.settings["update_waiting"]["app"] == "2999.1.1.1")
app.update_btn.destroy(); app.update_btn = None; app.show_update_flag(); pump()
ok("...shown again from the settings alone", app.update_btn is not None)
app.settings["update_waiting"] = {"app": local, "addons": {}}; app.show_update_flag(); pump()
ok("installed (mcIRC is at that version): the square goes, and nothing is remembered", app.update_btn is None and app.settings["update_waiting"] == {})
name = next(iter(app.addons.discover()), None)
if name:
    app.note_updates("", [(name, "1.0", "999.0", {})]); pump()
    ok("an addon update waiting shows it too", app.update_btn is not None)
    app.note_updates("", []); pump()
    ok("...a check that finds nothing: gone", app.update_btn is None)
ok("an older version than installed doesn't count", gui_updflag.waiting({"update_waiting": {"app": "2000.1.1.1"}}, local, lambda n: None) == ("", []))
root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
