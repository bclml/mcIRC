import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""Every addon setting can be made for one node only: a tab per node in the addon's settings window, and the addon answers each node with
that node's settings (what a node doesn't set comes from 'All nodes').  No radio."""
import tkinter as tk
from unittest import mock

import mcIRC
from gui_addons import AddonAPI, AddonBase
import gui_addonsettings as gs

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)


class Echo(AddonBase):
    """A tiny bot: answers 'hi' with its greeting; counts what it answered in a list it keeps (like a greeter's 'already greeted')."""
    title, version, replies = "Echo", "1.0", True
    def on_load(self): self.heard = []
    def on_message(self, msg):
        if msg["text"] != "hi": return
        self.heard.append((msg.get("node") or "main", self.api.get("greeting", "Hello"), self.api.get("prefix", "")))
        self.api.set("answered", self.api.get("answered", 0) + 1)
    def build_options(self, parent):
        f = tk.Frame(parent)
        self.v_greeting = tk.StringVar(value=self.api.get("greeting", "Hello"))
        self.v_prefix = tk.StringVar(value=self.api.get("prefix", ""))
        tk.Entry(f, textvariable=self.v_greeting).pack(); tk.Entry(f, textvariable=self.v_prefix).pack()
        return f
    def apply_options(self):
        self.api.set("greeting", self.v_greeting.get())
        self.api.set("prefix", self.v_prefix.get())


root = tk.Tk()
app = mcIRC.App(root, demo=True); root.update()
for n in list(app.addons.loaded): app.addons.unload(n)
app.save = lambda: None
app.settings["extra_nodes"] = [{"label": "wifi 1", "mode": "tcp", "host": "x", "enabled": True}]
api = AddonAPI(app, "echo"); bot = Echo(api); api.display = bot.title
app.addons.loaded["echo"] = (bot, api); bot.on_load()
app.settings.setdefault("addons", {})["echo"] = {"greeting": "Hello", "_nodes": ["main", "wifi 1"]}
msg = lambda node: {"channel": "Public" if node == "main" else f"Public [{node}]", "channel_idx": 0, "nick": "Ann", "text": "hi", "node": node, "dm": False}

app.addons.dispatch("on_message", msg("main")); app.addons.dispatch("on_message", msg("wifi 1"))
ok("without settings of their own, both nodes use 'All nodes'", bot.heard == [("main", "Hello", ""), ("wifi 1", "Hello", "")], bot.heard)

with api.for_node("wifi 1", own=True): api.set("greeting", "Bonjour")
bot.heard.clear()
app.addons.dispatch("on_message", msg("main")); app.addons.dispatch("on_message", msg("wifi 1"))
ok("a setting made for one node is used only for messages on that node", bot.heard == [("main", "Hello", ""), ("wifi 1", "Bonjour", "")], bot.heard)
app.settings["addons"]["echo"]["prefix"] = "!"
bot.heard.clear(); app.addons.dispatch("on_message", msg("wifi 1"))
ok("...what that node doesn't set still follows 'All nodes' (changed later too)", bot.heard == [("wifi 1", "Bonjour", "!")], bot.heard)
ok("something a bot saves while answering (a counter, a list) stays shared - not split per node",
   app.settings["addons"]["echo"].get("answered") == 5 and "answered" not in api.own_settings("wifi 1"), app.settings["addons"]["echo"])
ok("outside a message (timers, the 'All nodes' tab) the defaults are used", api.get("greeting") == "Hello")

app.settings["addons"]["echo"]["_per_node"]["wifi 1"]["_reply_private"] = True
calls = []
while not app.q.empty(): app.q.get_nowait()
with mock.patch.object(app, "reply_privately", lambda m, t, **k: calls.append(("dm", m["node"]))),         mock.patch.object(app, "send_to", lambda ch, t, **k: calls.append(("channel", ch))):
    api.reply(msg("wifi 1"), "x"); api.reply(msg("main"), "y")
    while not app.q.empty():
        item = app.q.get_nowait()
        if item[0] == "call": item[1]()
ok("'send answers by private message' can be set per node too", sorted(calls) == [("channel", "Public"), ("dm", "wifi 1")], calls)

# ---- the settings window: a tab per node
win = gs.AddonSettingsWindow(app, "echo"); root.update()
ok("with more than one node the window has tabs: All nodes, main node, each extra node (* = has settings of its own)",
   [b.cget("text") for b in win.tab_buttons.values()] == ["All nodes", "main node", "wifi 1 *"], [b.cget("text") for b in win.tab_buttons.values()])
win.tab_var.set("main"); win.switch("main"); root.update()
ok("a node's tab shows what that node uses (here: the defaults)", win.inst.v_greeting.get() == "Hello")
win.inst.v_greeting.set("G'day"); win.apply()
ok("changing one field on a node's tab keeps only that one as the node's own", api.own_settings("main") == {"greeting": "G'day"}, api.own_settings("main"))
ok("...and the tab is marked", win.tab_buttons["main"].cget("text") == "main node *")
win.tab_var.set("wifi 1"); win.switch("wifi 1"); root.update()
ok("switching tabs keeps what was changed and shows the next node's settings", win.inst.v_greeting.get() == "Bonjour" and api.own_settings("main") == {"greeting": "G'day"})
win.reset_node(); root.update()
ok("'Use All nodes settings for this node' clears that node's own settings", api.own_settings("wifi 1") == {} and win.inst.v_greeting.get() == "Hello"
   and win.tab_buttons["wifi 1"].cget("text") == "wifi 1")
win.tab_var.set(""); win.switch(""); root.update()
win.inst.v_greeting.set("Hi there"); win.apply()
ok("the 'All nodes' tab changes the defaults; a node with its own value keeps it", app.settings["addons"]["echo"]["greeting"] == "Hi there"
   and api.own_settings("main") == {"greeting": "G'day"})
win.destroy()
app.settings["extra_nodes"] = []
win = gs.AddonSettingsWindow(app, "echo"); root.update()
ok("with one node there are no tabs - the window is as before", not hasattr(win, "tab_buttons"))
win.destroy()

class OldAPI:                                   # mcIRC still running an older core (not restarted since the update)
    store = {}
    def get(self, k, d=None): return self.store.get(k, d)
    def set(self, k, v): self.store[k] = v
    def _draw_switch(self): pass
app.settings["extra_nodes"] = [{"label": "wifi 1", "mode": "tcp", "host": "x", "enabled": True}]
bot2 = Echo(OldAPI()); app.addons.loaded["echo"] = (bot2, bot2.api)
win = gs.AddonSettingsWindow(app, "echo"); root.update()
ok("with an older core still running: no node tabs, but the page itself is there and saves", not hasattr(win, "tab_buttons")
   and win.page is not None and win.inst.v_greeting.get() == "Hello")
win.inst.v_greeting.set("Yo"); win.apply()
ok("...and saving works", OldAPI.store.get("greeting") == "Yo", OldAPI.store)
win.destroy()
root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
