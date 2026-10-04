import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""'bothelp' lists the commands every bot answers in that channel; the optional daily 'Type bothelp...' announcement. No radio, no internet."""
import datetime as dt, importlib.util, tkinter as tk

sys.path[:0] = [os.path.join(ROOT, "packages", p) for p in ("weather_bot", "fun_bot")]
import mcIRC
from gui_addons import AddonAPI

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

root = tk.Tk()
app = mcIRC.App(root, demo=True); root.update()
app.connected = True
sent = []
app.send_to = lambda ch, text: sent.append((ch, text))
app.send_dm = lambda w, text: sent.append((w.name, text))
for ch in ("#weather", "#bot-van", "#quiet"): app.add_window(ch, "")
def load(pkg, settings):
    spec = importlib.util.spec_from_file_location("t2_" + pkg, os.path.join(ROOT, "packages", pkg, pkg + ".py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    api = AddonAPI(app, pkg); api.after = lambda ms, fn: fn()
    for k, v in settings.items(): api.set(k, v)
    inst = m.Addon(api); api.display = inst.title; inst.on_load(); return m, inst, api
_, wx, _ = load("weather_bot", {"enabled": True, "channels": "#weather"})
_, fun, _ = load("fun_bot", {"enabled": True, "channels": {"dice": "#bot-van", "joke": "#bot-van, #weather"}})
_, ar, _ = load("auto_reply", {"enabled": True, "rules": [{"name": "t", "enabled": True, "triggers": "test, t", "match": "exact", "listen": "#bot-van", "reply": "ok"}]})
bmod, bh, bapi = load("bot_help", {"enabled": True})
msg = lambda ch, text="bothelp", nick="Bob", dm=False: {"channel": ch, "channel_idx": 1, "nick": nick, "text": text, "snr": 1, "hops": 0, "raw": {}, "dm": dm}

found = bh.found("#weather")
ok("in #weather: the weather bot and the joke from the fun bot", set(found) >= {"Weather bot", "Fun bot"} and "wx <place>" in found["Weather bot"] and found["Fun bot"] == ["joke"], found)
found = bh.found("#bot-van")
ok("in #bot-van: fun bot (dice, joke) and auto reply's words, no weather", set(found) == {"Fun bot", "Auto reply"} and found["Fun bot"] == ["dice 3d6", "joke"] and found["Auto reply"] == ["test", "t"], found)
bh.on_message(msg("#weather"))
ok("'bothelp' in #weather answers there, in mesh-sized messages", sent and all(c == "#weather" and len(t) <= 115 for c, t in sent) and sent[0][1].startswith("Weather bot: wx <place>"), sent)
ok("...and lists every bot that answers there", any("Fun bot: joke" in t for _, t in sent), sent)
sent.clear(); bh.on_message(msg("#weather"))
ok("the same person asking again within a minute is ignored", sent == [])
sent.clear(); bh.on_message(msg("#quiet", nick="Cat"))
ok("a channel where no bot answers stays quiet", sent == [])
sent.clear(); bh.last_any = 0; bh.on_message(msg("#bot-van", text="!bothelp", nick="Dan"))      # (5 s between any two answers)
ok("'!bothelp' works too", sent and "Fun bot: dice 3d6, joke" in sent[0][1] and "Auto reply: test, t" in sent[0][1], sent)
sent.clear(); bh.on_message(msg("#weather", text="what is bothelp", nick="Eve"))
ok("only the word itself triggers it", sent == [])
bapi.set("enabled", False); sent.clear(); bh.last_by.clear(); bh.last_any = 0; bh.on_message(msg("#weather", nick="Fay"))
ok("off -> quiet", sent == [])
bapi.set("enabled", True)

# ---- the daily announcement
day = dt.datetime(2026, 10, 4, 19, 0, 20)
bh.on_tick(day)
ok("no announcement unless switched on", sent == [])
bapi.set("announce", True); bapi.set("announce_time", "19:00")
bh.on_tick(day.replace(hour=18, minute=59))
ok("nothing before the set time", sent == [])
bh.on_tick(day)
ok("at the set time: the message goes to every channel where a bot answers", sorted(c for c, _ in sent) == ["#bot-van", "#weather"] and all(t == bmod.DEFAULT_TEXT for _, t in sent), sent)
sent.clear(); bh.on_tick(day + dt.timedelta(minutes=1))
ok("only once a day", sent == [])
bh.on_tick(day + dt.timedelta(days=1, minutes=2))
ok("again the next day", len(sent) == 2, sent)
sent.clear(); bapi.set("announce_channels", "#weather"); bapi.set("announce_text", "Bots here! Type bothelp")
bh.on_tick(day + dt.timedelta(days=2))
ok("chosen channels and own text", sent == [("#weather", "Bots here! Type bothelp")], sent)
sent.clear(); bh.on_tick(day + dt.timedelta(days=3, hours=2))
ok("mcIRC started long after the time -> that day is skipped", sent == [])
app.connected = False; bh.on_tick(day + dt.timedelta(days=4))
ok("not connected -> nothing", sent == [])
long = bmod.help_lines({"Weather bot": ["wx <place>"] * 30, "Fun bot": ["joke"]})
ok("a long list is cut into at most 3 messages of mesh size", len(long) <= 3 and all(len(p) <= 115 for p in long), [len(p) for p in long])
root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
