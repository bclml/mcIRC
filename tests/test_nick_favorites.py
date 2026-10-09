import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""The name list: names stay after a restart; favorites ('+name') come right after your own '@name' and are starred on the node.  No radio."""
import tkinter as tk
from types import SimpleNamespace
from unittest import mock

import mcIRC
import gui_nicks

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

ok("order: @me, then +favorites, then the rest, each A-Z",
   gui_nicks.order({"zed", "Bob", "alice", "Me", "Carl"}, "Me", ["carl", "zed"]) ==
   [("@Me", "Me"), ("+Carl", "Carl"), ("+zed", "zed"), ("alice", "alice"), ("Bob", "Bob")])

root = tk.Tk()
app = mcIRC.App(root, demo=True); root.update()
me = app.settings["node_name"]
saved = {}
app.save = lambda: saved.update(app.settings)                 # what would be written to the settings file
w = app.add_window("#nicktest", "test")
app.select_window("#nicktest")
for n in ("Thalestr", "Altair", "MossNode"): app.chat_line(w, n, "hello", "text")
ok("the names of who spoke are saved with the settings", saved.get("window_nicks", {}).get("#nicktest") == ["Thalestr", "Altair", "MossNode"], saved.get("window_nicks"))
ok("the list shows @me then everyone A-Z", list(app.nicklist.get(0, "end")) == ["@" + me, "Altair", "MossNode", "Thalestr"], app.nicklist.get(0, "end"))

# a restart: a new window of the same name gets the saved names back
app.windows.pop("#nicktest").frame.destroy()
if app.tree.exists("#nicktest"): app.tree.delete("#nicktest")
w2 = app.add_window("#nicktest", "test")
ok("after a restart the window has its names again", w2.nicks >= {"Thalestr", "Altair", "MossNode"}, w2.nicks)
app.select_window("#nicktest")

# the chat history shown at start: its writers are in the list too (even from before names were saved)
import tempfile
logdir = tempfile.mkdtemp()
with open(os.path.join(logdir, "#histtest.txt"), "w", encoding="utf-8") as f:
    f.write("Session Start: Fri Oct 09 09:00:00 2026\n[09:24] <Thalestr  M1> Pinecone storm  (SNR 12.0, 5 hops)\n"
            "[09:42] <Altair > Back from Kenya  (SNR 11.75, 5 hops)\n[09:50] *** [weather] a <status> line > not a name\n")
hw = mcIRC.ChatWindow(root, "#histtest", "t", app.font, mcIRC.WindowLog("#histtest", logdir), 50)
ok("names from the chat history shown at start are in the list", hw.nicks == {"Thalestr  M1", "Altair "}, hw.nicks)
hw.frame.destroy()

# favorite from the right-click menu: not connected here, so only in mcIRC
app.connected = False
app.nodes = SimpleNamespace(find_by_name=lambda n: {"public_key": "ab" * 32} if n == "MossNode" else None, all=lambda: [])
menus = []
class FakeMenu:
    def __init__(self, *a, **k): self.items = []; menus.append(self)
    def add_command(self, label="", command=None, **k): self.items.append((label, command))
    def add_separator(self): pass
    def add_cascade(self, **k): pass
    def tk_popup(self, *a): pass
with mock.patch("gui_menus.tk.Menu", FakeMenu):
    i = list(app.nicklist.get(0, "end")).index("MossNode")
    app.nicklist.see(i); root.update()
    y = app.nicklist.bbox(i)[1] + 2
    app._nick_menu(SimpleNamespace(y=y, x_root=0, y_root=0))
labels = [l for l, _ in menus[-1].items]
ok("right-click on a name: Add ... as favorite", "Add MossNode as favorite" in labels, labels)
dict(menus[-1].items)["Add MossNode as favorite"]()
ok("a favorite gets a + and moves right below @me", list(app.nicklist.get(0, "end")) == ["@" + me, "+MossNode", "Altair", "Thalestr"], app.nicklist.get(0, "end"))
ok("...and is saved", saved.get("favorites") == ["MossNode"], saved.get("favorites"))
ok("the + is not part of the name (double-click, menus)", app.nick_at(1) == "MossNode")
with mock.patch("gui_menus.tk.Menu", FakeMenu):
    app._nick_menu(SimpleNamespace(y=app.nicklist.bbox(1)[1] + 2, x_root=0, y_root=0))
ok("...and the menu then offers to remove it", "Remove MossNode from favorites" in [l for l, _ in menus[-1].items], [l for l, _ in menus[-1].items])

# starring on the node: the other flag bits are kept
calls = []
contacts = {"ab" * 32: {"public_key": "ab" * 32, "adv_name": "MossNode", "flags": 0b110}}
with mock.patch.object(gui_nicks.gui_nodes, "fetch_radio_contacts", lambda: contacts), \
        mock.patch.object(gui_nicks.ea, "execute_mesh_command", lambda args, **k: calls.append(args[-3:])), \
        mock.patch.object(gui_nicks.ea, "CONNECTION_ARGS", ["-s", "COM99"]):
    ok("star on the node: change_flags with bit 0 added, the others kept", gui_nicks.star_on_node("ab" * 32, True) and calls == [["change_flags", "ab" * 32, "7"]], calls)
    contacts["ab" * 32]["flags"] = 7; calls.clear()
    ok("unstar: bit 0 cleared", gui_nicks.star_on_node("ab" * 32, False) and calls == [["change_flags", "ab" * 32, "6"]], calls)
    contacts["ab" * 32]["flags"] = 6; calls.clear()
    ok("nothing sent when it is already as wanted", gui_nicks.star_on_node("ab" * 32, False) is True and calls == [], calls)
    ok("a name that isn't a contact on the node: nothing sent", gui_nicks.star_on_node("cd" * 32, True) is False and calls == [])

# stars set on the node (from the phone) follow into mcIRC
app.settings["favorites_node"] = []
app.favorites_from_node({"Altair"})
ok("a star set on the node makes the name a favorite", app.is_favorite("Altair") and list(app.nicklist.get(0, "end"))[1:3] == ["+Altair", "+MossNode"], app.nicklist.get(0, "end"))
app.favorites_from_node(set())
ok("...and removing it on the node removes it here (mcIRC's own favorites stay)", not app.is_favorite("Altair") and app.is_favorite("MossNode"))
app.favorites_from_node(None)
ok("no contact list read: nothing changes", app.is_favorite("MossNode"))
root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
