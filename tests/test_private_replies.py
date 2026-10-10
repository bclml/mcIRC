import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""Every bot can answer by private message instead of in the channel (its settings window).  No radio."""
import importlib.util, time
import tkinter as tk
from unittest import mock

import mcIRC
from gui_addons import AddonAPI, AddonBase
import gui_addonsettings

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

root = tk.Tk()
app = mcIRC.App(root, demo=True); root.update()
app.connected = True
now = time.time()
app.nodes.update_from_radio({"ab" * 32: {"public_key": "ab" * 32, "adv_name": "Alice", "type": 1, "last_advert": int(now)}}, now)
dms, chans, lines = [], [], []
app.send_dm = lambda w, text: dms.append((w.name, getattr(w, "node", None), text))
app.send_to = lambda ch, text: chans.append((ch, text))
app.status_line = lambda text, level="info", **k: lines.append((level, text))
def drain():
    for _ in range(30):
        try: item = app.q.get_nowait()
        except Exception: break
        if item[0] == "call": item[1]()
api = AddonAPI(app, "weather_bot")
msg = {"channel": "#weather", "channel_idx": 6, "nick": "Alice", "text": "wx", "dm": False}

api.reply(msg, "Sunny"); drain()
ok("by default a bot answers in the channel", chans == [("#weather", "Sunny")] and dms == [])
chans.clear()
app.settings.setdefault("addons", {}).setdefault("weather_bot", {})["_reply_private"] = True
api.reply(msg, "Sunny"); drain()
ok("with 'answer privately' on, the answer goes to the person who asked", dms == [("@Alice", None, "Sunny")] and chans == [], (dms, chans))
ok("...in their private window (the one already open is used)", "@Alice" in app.windows and app.windows["@Alice"].key)
dms.clear()
api.reply(dict(msg, node="wifi 1", channel="#weather [wifi 1]"), "Rain"); drain()
ok("a question that came in on another node is answered through that node", dms == [("@Alice", "wifi 1", "Rain")], dms)
dms.clear()
api.reply(dict(msg, nick="Stranger"), "Cloudy"); drain()
ok("someone not in node memory yet: answered in the channel after all, and Status says why",
   chans == [("#weather", "Cloudy")] and any("Couldn't answer Stranger privately" in t for _, t in lines), (chans, lines))
chans.clear()
api.reply(dict(msg, dm=True, channel="@Alice"), "x"); drain()
ok("a private question is always answered privately", chans == [])

# auto reply: same channel -> follows the setting; its own destinations stay as they are
spec = importlib.util.spec_from_file_location("t_auto_reply", os.path.join(ROOT, "packages", "auto_reply", "auto_reply.py"))
ar = importlib.util.module_from_spec(spec); spec.loader.exec_module(ar)
aapi = AddonAPI(app, "auto_reply"); aapi.after = lambda ms, fn: fn()
bot = ar.Addon(aapi); aapi.display = bot.title; bot.on_load()
app.settings["addons"].setdefault("auto_reply", {}).update(enabled=True, _reply_private=True,
    rules=[{"name": "t", "enabled": True, "triggers": "test", "match": "exact", "listen": "", "reply": "got it", "reply_to": "", "cooldown": 0}])
dms.clear(); chans.clear()
bot.on_message(dict(msg, text="test", channel="Public")); drain()
ok("auto reply answers privately too when set", dms and dms[0][0] == "@Alice" and dms[0][2] == "got it" and not chans, (dms, chans))

# the checkbox: only for addons that answer people
class Bot(AddonBase):
    title = "Test bot"
    def on_load(self): self.api.add_bot_commands(lambda ch, dm=False: ["ping"])
class Quiet(AddonBase):
    title = "Test quiet"
for name, cls in (("tbot", Bot), ("tquiet", Quiet)):
    a = AddonAPI(app, name); inst = cls(a); a.display = inst.title; inst.on_load()
    app.addons.loaded[name] = (inst, a)
with mock.patch.object(app.addons, "info", lambda n: (n, "1.0", "", "")):
    win = gui_addonsettings.AddonSettingsWindow(app, "tbot")
    ok("a bot's settings window offers 'Send answers by private message'", win.private_var is not None)
    win.private_var.set(True); win.apply()
    ok("...and it is saved", app.settings["addons"]["tbot"]["_reply_private"] is True)
    win.destroy()
    win = gui_addonsettings.AddonSettingsWindow(app, "tquiet")
    ok("an addon that answers nobody doesn't show it", win.private_var is None)
    win.destroy()
# ---- nothing from bots in Public
from unittest import mock as _mock
calls = []
papi = AddonAPI(app, "fun_bot")
app.settings["bots_in_public"] = False
while not app.q.empty(): app.q.get_nowait()
with _mock.patch.object(app, "send_to", lambda ch, t, **k: calls.append(("channel", ch))), \
        _mock.patch.object(app, "reply_privately", lambda m, t: calls.append(("private", m["nick"]))):
    for ch in ("Public", "Public [wifi 1]", "#general"):
        papi.reply({"channel": ch, "nick": "Ann", "text": "joke", "dm": False, "node": "main"}, "a joke", private=False)
    papi.send("Public", "hello all"); papi.send(0, "hello all"); papi.send("#general", "hi")
    while not app.q.empty():
        item = app.q.get_nowait()
        if item[0] == "call": item[1]()
ok("bots never post in Public (any node's): an answer there goes to the person privately", calls.count(("private", "Ann")) == 2
   and ("channel", "Public") not in calls and ("channel", "Public [wifi 1]") not in calls, calls)
ok("...other channels as before; a bot's own post to Public is dropped", calls.count(("channel", "#general")) == 2 and len(calls) == 4, calls)
calls.clear(); app.settings["bots_in_public"] = True
with _mock.patch.object(app, "send_to", lambda ch, t, **k: calls.append(("channel", ch))):
    papi.reply({"channel": "Public", "nick": "Ann", "text": "joke", "dm": False, "node": "main"}, "a joke", private=False)
ok("...unless 'Let bots post in Public' is ticked in Options", calls == [("channel", "Public")], calls)
app.settings["bots_in_public"] = False
root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
