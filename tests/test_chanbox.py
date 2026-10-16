import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""The channel list in addon settings: the chosen channels with a x each and an 'Add' menu, instead of typing '#a, #b' in one box.
The value is still stored as '#a, #b' (a StringVar), so saved settings don't change."""
import tkinter as tk
from unittest import mock
import gui_chanbox as cb

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

ok("what is stored reads back as a list: '#test.#buds' / 'buds, Public all' (each once)", cb.parse("#test.#buds") == ["#test", "#buds"]
   and cb.parse("buds, Public all #BUDS") == ["#buds", "Public", "all"] and cb.parse("") == [])
root = tk.Tk(); root.withdraw()
var = tk.StringVar(value="#test, #buds")
box = cb.channel_box(root, var, choices=lambda: ["Public", "#test", "#buds", "#weather"], all_option=True); box.pack(); root.update()
labels = lambda: [w.winfo_children()[0].cget("text") for w in box.winfo_children() if isinstance(w, tk.Frame)]
ok("it shows each channel with its own x", labels() == ["#test", "#buds"], labels())
def fill_menu(b=None):
    """The 'Add' menu as it fills itself when opened -> (menu, its labels)."""
    mb = next(w for w in (b or box).winfo_children() if isinstance(w, tk.Menubutton)); mm = root.nametowidget(mb.cget("menu"))
    mm.tk.call(mm.cget("postcommand"))
    return mm, [mm.entrycget(i, "label") for i in range(mm.index("end") + 1) if mm.type(i) == "command"]
def pick(label, b=None):
    mm, _ = fill_menu(b)
    mm.invoke(next(i for i in range(mm.index("end") + 1) if mm.type(i) == "command" and mm.entrycget(i, "label") == label)); root.update()
mm, entries = fill_menu()
ok("'Add' offers the node's channels not chosen yet, 'All channels' and 'Other channel...'", entries == ["Public", "#weather", "All channels", "Other channel..."], entries)
pick("#weather")
ok("adding one: it's in the list and stored as before ('#test, #buds, #weather')", var.get() == "#test, #buds, #weather" and labels() == ["#test", "#buds", "#weather"], var.get())
chip = [w for w in box.winfo_children() if isinstance(w, tk.Frame)][1]
chip.winfo_children()[1].invoke(); root.update()
ok("x removes that one only", var.get() == "#test, #weather", var.get())
pick("All channels")
ok("'All channels' replaces the list with 'all'", var.get() == "all" and labels() == ["All channels"], var.get())
with mock.patch.object(cb.simpledialog, "askstring", lambda *a, **k: "jokes"):
    pick("Other channel...")
ok("'Other channel...' adds a typed name (with its #); a named channel replaces 'all'", var.get() == "#jokes", var.get())
var.set("#a, #b"); root.update()
ok("set from elsewhere ('Same channel for all', 'Clear all'): the list follows", labels() == ["#a", "#b"], labels())
v2 = tk.StringVar(value=""); b2 = cb.channel_box(root, v2, choices=lambda: ["#x"], max_items=2, empty="(every channel)", public=False); root.update()
ok("empty: says what that means for this setting", any(isinstance(w, tk.Label) and w.cget("text") == "(every channel)" for w in b2.winfo_children()))
v2.set("#1, #2, #3"); root.update()
ok("Public isn't offered where it isn't allowed (alert channels)", "Public" not in fill_menu(b2)[1])
pick("#x", b2)
ok("...and a list with a limit keeps the newest ones (alerts: at most 5 channels)", len(cb.parse(v2.get())) == 2 and cb.parse(v2.get())[-1] == "#x", v2.get())
root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
