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
app.settings["bots_in_public"] = True      # these tests answer in Public on purpose (the no-bots-in-Public rule: test_private_replies)
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
ok("with more than one node the window has a tab per node - 'main node' (its settings are the base ones) and each extra node; no 'All nodes'",
   [b.cget("text") for b in win.tab_buttons.values()] == ["main node", "wifi 1 *"], [b.cget("text") for b in win.tab_buttons.values()])
ok("the main node's tab shows the main settings", win.inst.v_greeting.get() == "Hello")
win.inst.v_greeting.set("G'day"); win.apply()
ok("changing it changes the main settings (no separate 'main node' layer)", app.settings["addons"]["echo"]["greeting"] == "G'day" and api.own_settings("main") == {})
win.tab_var.set("wifi 1"); win.switch("wifi 1"); root.update()
ok("switching tabs keeps what was changed and shows the next node's settings", win.inst.v_greeting.get() == "Bonjour" and app.settings["addons"]["echo"]["greeting"] == "G'day")
on_before = app.addons.nodes_for("echo")
ok("a node's tab says whether the addon works on that node at all ('Use this addon on node ...')", win.here_var is not None
   and win.here_var.get() == ("wifi 1" in on_before), on_before)
win.here_var.set(True); win.apply()
ok("...ticking it there makes the addon work on that node (and the main node stays as it was)", "wifi 1" in app.addons.nodes_for("echo")
   and ("main" in app.addons.nodes_for("echo")) == ("main" in on_before), app.addons.nodes_for("echo"))
win.here_var.set(False); win.apply()
ok("...unticking it: not on that node any more", "wifi 1" not in app.addons.nodes_for("echo"), app.addons.nodes_for("echo"))
win.here_var.set("wifi 1" in on_before); win.apply()
win.reset_node(); root.update()
ok("'Use the main node's settings for this node' clears that node's own settings", api.own_settings("wifi 1") == {} and win.inst.v_greeting.get() == "G'day"
   and win.tab_buttons["wifi 1"].cget("text") == "wifi 1" and "main node" in win.reset_btn.cget("text"))
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
# ---- before 2026.10.15 a 'main node' tab of its own existed: what was saved there becomes the main settings (once)
from gui_addons import fold_main_node
old = {"addons": {"area": {"areas": [], "channel": "#all", "kinds": {"a": 1}, "_per_node": {"main": {"areas": ["LM", "VI"], "channel": "#mine"}, "wifi 1": {"channel": "#w"}}},
                  "bot": {"x": 1, "_per_node": {"main": {"x": 2}}}, "plain": {"y": 3}}}
changed = fold_main_node(old)
ok("old 'main node' tabs are folded into the main settings - the main node keeps exactly what it used", old["addons"]["area"]["areas"] == ["LM", "VI"]
   and old["addons"]["area"]["channel"] == "#mine" and old["addons"]["area"]["kinds"] == {"a": 1} and old["addons"]["bot"] == {"x": 2} and sorted(changed) == ["area", "bot"], old)
ok("...other nodes keep their own settings; addons without any are untouched", old["addons"]["area"]["_per_node"] == {"wifi 1": {"channel": "#w"}}
   and old["addons"]["plain"] == {"y": 3} and fold_main_node(old) == [])
import mcIRC as _mc
ok("...mcIRC does it once at start, after copying gui_settings.json to backup/ (no copy, no change)", "gui_settings-before-main-node" in open(_mc.__file__, encoding="utf-8").read()
   and "except OSError: return" in open(_mc.__file__, encoding="utf-8").read())

# ---- set up on the 'main node' tab only: a tick / background job / mcIRC's channel step reads the MAIN node's settings (Area alerts
# found no areas: its check read the defaults, where they weren't)
api2 = AddonAPI(app, "areas_test")
app.settings.setdefault("addons", {})["areas_test"] = {"channel": "#default", "_per_node": {"main": {"areas": ["Somewhere"], "channel": "#mine"}}}
import threading
seen = {}
def worker(): seen["thread"] = (api2.get("areas", []), api2.get("channel"))
t = threading.Thread(target=worker); t.start(); t.join()
ok("no node chosen (a tick, a background thread): the main node's own settings", api2.get("areas", []) == ["Somewhere"] and api2.get("channel") == "#mine"
   and seen["thread"] == (["Somewhere"], "#mine"), seen)
with api2.for_node(None): ok("...the 'All nodes' tab still shows the defaults", api2.get("areas", []) == [] and api2.get("channel") == "#default")
with api2.for_node("wifi 1"): ok("...another node: its own, else the defaults (not main's)", api2.get("areas", []) == [] and api2.get("channel") == "#default")
ok("...node_context() is still None when nothing was chosen", api2.node_context() is None)
api2.set("channel", "#changed")
ok("...a value the main node has of its own is saved there", app.settings["addons"]["areas_test"]["_per_node"]["main"]["channel"] == "#changed")
api2.set("counter", 3)
ok("...a new value (nothing of the main node's own) goes to the defaults", app.settings["addons"]["areas_test"].get("counter") == 3
   and "counter" not in app.settings["addons"]["areas_test"]["_per_node"]["main"])
root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
