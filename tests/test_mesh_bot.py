import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""Mesh bot: the meshcore-bot commands (ping, hello, path, prefix, multitest, stats, sports, version) and the greeter.  No radio, no network."""
import filecmp, importlib.util, random, time
import tkinter as tk

sys.path.insert(0, os.path.join(ROOT, "packages", "mesh_bot"))
import meshbot_cmds as cmds

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

ok("it ships the same meshbot_common.py as the other bots", filecmp.cmp("packages/mesh_bot/meshbot_common.py", "packages/weather_bot/meshbot_common.py", shallow=False))
now = time.time()
NODES = [{"name": "Hilltop", "public_key": "a1b2" + "0" * 60, "type": 2, "last_seen": now - 600},
         {"name": "Harbour", "public_key": "a1c3" + "0" * 60, "type": 2, "last_seen": now - 90000},
         {"name": "Ridge", "public_key": "b2" + "0" * 62, "type": 3, "last_seen": now},
         {"name": "Bob phone", "public_key": "a1ff" + "0" * 60, "type": 1, "last_seen": now}]
ok("hops are read from 'a1,b2', 'a1 b2' and 'a1b2c3'", cmds.split_hops("a1,b2") == ["A1", "B2"] and cmds.split_hops("a1 b2") == ["A1", "B2"] and cmds.split_hops("a1b2c3") == ["A1", "B2", "C3"])
try: cmds.split_hops("zz"); bad = False
except ValueError: bad = True
ok("...not hex: refused", bad)
ok("path names each hop from node memory (repeaters only; several: the newest + how many more)",
   cmds.path_text(NODES, ["A1", "B2", "C9"]) == "Path: A1: Hilltop (or 1 more) > B2: Ridge > C9: Unknown", cmds.path_text(NODES, ["A1", "B2", "C9"]))
ok("...2-byte hops narrow it down", cmds.path_text(NODES, ["A1C3"]) == "Path: A1C3: Harbour")
ok("prefix lists the repeaters using it (not people's companions)", cmds.prefix_text(NODES, "a1", now).startswith("Prefix A1: 2 repeaters: Hilltop (") and "Bob" not in cmds.prefix_text(NODES, "a1", now))
ok("prefix free lists prefixes no known repeater uses", "A1" not in cmds.prefix_text(NODES, "free", now).split(": ", 1)[1].split() and "01" in cmds.prefix_text(NODES, "free", now))
log = [{"t": now - 2, "type": "GRP_TXT", "path": "a1b2", "size": 1, "length": 40}, {"t": now - 1, "type": "ADVERT", "path": "c3", "size": 1, "length": 100},
       {"t": now + 1, "type": "GRP_TXT", "path": "a1", "size": 1, "length": 40}, {"t": now + 3, "type": "GRP_TXT", "path": "", "size": 1, "length": 40},
       {"t": now + 2, "type": "GRP_TXT", "path": "d4", "size": 1, "length": 77}]
ok("the path of a message: the channel packet heard just before it with that many hops", cmds.path_of_message(log, now, 2) == ["A1", "B2"])
ok("multitest: the different paths the same message took", cmds.multitest_text(cmds.multitest_paths(log, now)) == "Multitest: 3 paths: A1>B2, A1, direct", cmds.multitest_text(cmds.multitest_paths(log, now)))
ok("stats: packets, nodes heard and the busiest channel in 24 h", cmds.stats_text(log, NODES, {"#weather": 9, "Public": 3}, now).startswith("Mesh 24h: 5 packets heard (GRP_TXT 4, ADVERT 1)") and "busiest channel #weather" in cmds.stats_text(log, NODES, {"#weather": 9, "Public": 3}, now))
ok("hello: a robot greeting that names the bot", cmds.hello("mcIRC", 9, random.Random(1)).endswith("I'm mcIRC.") and cmds.is_greeting("Hi!") and not cmds.is_greeting("hi there everyone"))
SB = {"events": [{"competitions": [{"status": {"type": {"state": "in", "shortDetail": "2nd 10:00"}},
                                    "competitors": [{"homeAway": "home", "score": "2", "team": {"abbreviation": "VAN", "displayName": "Vancouver Canucks", "name": "Canucks"}},
                                                    {"homeAway": "away", "score": "1", "team": {"abbreviation": "SEA", "displayName": "Seattle Kraken", "name": "Kraken"}}]}]}]}
fake = lambda url: SB if "/nhl/" in url else {"events": []}
ok("sports <league>: its games", cmds.sports_text("nhl", fake) == "NHL: SEA 1-2 VAN (2nd 10:00)", cmds.sports_text("nhl", fake))
ok("sports <team>: that team's game", cmds.sports_text("canucks", fake) == "SEA 1-2 VAN (2nd 10:00)")
ok("sports: the default teams'", cmds.sports_text("", fake, ["kraken"]) == "SEA 1-2 VAN (2nd 10:00)")

# the addon
import mcIRC
from gui_addons import AddonAPI
spec = importlib.util.spec_from_file_location("t_mesh_bot", os.path.join(ROOT, "packages", "mesh_bot", "mesh_bot.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
root = tk.Tk()
app = mcIRC.App(root, demo=True); root.update()
api = AddonAPI(app, "mesh_bot"); api.after = lambda ms, fn: fn()
sent = []
api.reply = lambda msg, text, private=None: sent.append((msg["channel"], text))
bot = mod.Addon(api); api.display = bot.title; bot.on_load()
msg = lambda text, ch="#bot-van", nick="Bob", hops=2: {"channel": ch, "channel_idx": 8, "nick": nick, "text": text, "snr": 9.5, "hops": hops, "raw": {}, "dm": False}
bot.on_message(msg("ping"))
ok("off until switched on", sent == [])
app.settings.setdefault("addons", {}).setdefault("mesh_bot", {}).update(enabled=True, channels={"ping": "#bot-van", "hello": "#bot-van", "version": "all"})
bot.on_message(msg("ping"))
ok("ping: Pong! with how the message arrived", sent == [("#bot-van", "Pong! (2 hops, SNR 9.5)")], sent)
sent.clear(); bot.limiter.last_by = {}; bot.limiter.last_any = 0
bot.on_message(msg("ping", ch="Public", nick="Cy"))
ok("...only in the channels it is on for", sent == [])
bot.on_message(msg("hey", nick="Di"))
ok("hello answers greetings", sent and "I'm" in sent[0][1], sent)
ok("bothelp lists what's on in a channel", bot.help_for("#bot-van") == ["ping", "hello", "version"] and bot.help_for("Public") == ["version"], (bot.help_for("#bot-van"), bot.help_for("Public")))
# greeter
sent.clear()
app.settings["addons"]["mesh_bot"].update(greet_channels="Public", greeted=["Old Timer"])
bot.on_message(msg("hello all", ch="Public", nick="Newbie"))
import meshbot_cmds as mcmds
ok("the greeter welcomes a newcomer once, with one of its greetings", len(sent) == 1 and sent[0][0] == "Public"
   and sent[0][1] in [mcmds.greeting_for("Newbie", g, "Public") for g in mcmds.DEFAULT_GREETINGS], sent)
sent.clear(); bot.on_message(msg("me again", ch="Public", nick="Newbie")); bot.on_message(msg("hi", ch="Public", nick="Old Timer"))
ok("...not twice, and not people known before", sent == [], sent)
app.settings["addons"]["mesh_bot"]["greet_lines"] = ["Hi {nick} in {channel}", "Yo {nick}"]
got = []
for i in range(8):
    sent.clear(); bot.on_message(msg("first words", ch="Public", nick=f"New{i}")); got.append(sent[0][1])
ok("greetings are picked at random from your own list, {channel} filled in", set(got) <= {f"Hi New{i} in Public" for i in range(8)} | {f"Yo New{i}" for i in range(8)}
   and any(g.startswith("Hi") for g in got) and any(g.startswith("Yo") for g in got), got)
ok("...never the same one twice in a row", all(a.split()[0] != b.split()[0] for a, b in zip(got, got[1:])), got)
del app.settings["addons"]["mesh_bot"]["greet_lines"]
app.settings["addons"]["mesh_bot"]["greet_text"] = "Howdy {nick}"
ok("a greeting changed in 1.0.x is kept", bot.greetings() == ["Howdy {nick}"])
del app.settings["addons"]["mesh_bot"]["greet_text"]
ok("...otherwise the default greetings, Invision-style ones included", bot.greetings() == mcmds.DEFAULT_GREETINGS and any("graced us" in g for g in bot.greetings()))
page = bot.build_options(tk.Frame(root)); bot.v_greet_ch.set("#weather"); bot.v_greet_ch.set("")
bot.greet_box.delete("1.0", "end"); bot.greet_box.insert("1.0", "One {nick}\n\n  Two {nick}  \n")
bot.apply_options()
ok("the settings box saves one greeting per line, blanks skipped", app.settings["addons"]["mesh_bot"]["greet_lines"] == ["One {nick}", "Two {nick}"],
   app.settings["addons"]["mesh_bot"].get("greet_lines"))
from unittest import mock
REL = [{"tag_name": "companion-v1.17.1", "published_at": "2026-08-14T13:32:31Z"}, {"tag_name": "repeater-v1.17.1", "published_at": "2026-08-14T13:32:04Z"},
       {"tag_name": "room-server-v1.17.1", "published_at": "2026-08-14T13:31:40Z"}, {"tag_name": "companion-v1.17.0", "published_at": "2026-08-09"},
       {"tag_name": "companion-v1.18.0-beta", "prerelease": True, "published_at": "2026-09-01"}]
ok("firmware: the newest companion, repeater and room server versions (no pre-releases)", mcmds.firmware_text(REL) ==
   "MeshCore firmware: companion v1.17.1, repeater v1.17.1, room server v1.17.1 (2026-08-14) - github.com/meshcore-dev/MeshCore/releases", mcmds.firmware_text(REL))
calls = []
with mock.patch.object(mod.mc, "http_json", lambda url, **k: calls.append(url) or REL):
    first, second = bot.firmware(), bot.firmware()
ok("...GitHub is asked at most once an hour", first == second and len(calls) == 1, calls)
ok("firmware is one of the Mesh bot's (read-only) commands", "firmware" in mod.COMMANDS)
root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
