import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""Channel list bot: 'channel list' -> the saved list; the list can be edited in Options.  No radio."""
import filecmp, importlib.util, tkinter as tk

sys.path[:0] = [os.path.join(ROOT, "packages", "channel_list")]
import mcIRC
from gui_addons import AddonAPI

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

ok("it ships the same meshbot_common.py as the other bots", filecmp.cmp("packages/channel_list/meshbot_common.py", "packages/weather_bot/meshbot_common.py", shallow=False))
root = tk.Tk()
app = mcIRC.App(root, demo=True); root.update()
app.connected = True
sent = []
app.send_to = lambda ch, text: sent.append((ch, text))
spec = importlib.util.spec_from_file_location("t_channel_list", os.path.join(ROOT, "packages", "channel_list", "channel_list.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
api = AddonAPI(app, "channel_list"); api.after = lambda ms, fn: fn()
bot = m.Addon(api); api.display = bot.title; bot.on_load()
msg = lambda text, ch="Public", nick="Bob": {"channel": ch, "channel_idx": 0, "nick": nick, "text": text, "snr": 1, "hops": 0, "raw": {}, "dm": False}
bot.on_message(msg("channel list"))
ok("off until switched on", sent == [])
api.set("enabled", True)
bot.on_message(msg("Channel list?"))
text = " ".join(t for _, t in sent)
ok("'channel list' answers with the starting list", sent and sent[0][1].startswith("Channels: Public, #bc, #bcferries") and "#wardriving" in text and "#weather" in text, sent)
ok("...in mesh-sized messages", all(len(t) <= 115 for _, t in sent))
sent.clear(); bot.on_message(msg("channel list"))
ok("the same person again within a minute: quiet", sent == [])
sent.clear(); bot.last_any = 0; bot.on_message(msg("what channel list do you use", nick="Cat"))
ok("only the phrase itself triggers it", sent == [])
sent.clear(); bot.on_message(msg("!channels", nick="Dan"))
ok("'!channels' works too", len(sent) >= 1)
# editing the list in Options
page = bot.build_options(tk.Frame(root)); root.update()
bot.entry.set("mesh-test"); bot.add()
bot.lb.selection_clear(0, "end"); bot.lb.selection_set(1); bot.entry.set("#bc-chat"); bot.rename()
bot.lb.selection_clear(0, "end"); bot.lb.selection_set(bot.items().index("#ssi")); bot.remove()
bot.lb.selection_clear(0, "end"); bot.lb.selection_set(bot.items().index("#mesh-test")); bot.move(-1)
bot.apply_options()
saved = api.get("list")
ok("add (a '#' is added), rename, remove and reorder are saved", "#mesh-test" in saved and "#bc-chat" in saved and "#bc" not in saved and "#ssi" not in saved
   and saved.index("#mesh-test") == len(saved) - 2, saved)
ok("the preview shows the answer", bot.preview.cget("text").startswith("The answer: Channels: Public"))
sent.clear(); bot.last_by.clear(); bot.last_any = 0; bot.on_message(msg("channel list", nick="Eve"))
ok("the answer uses the edited list", "#bc-chat" in " ".join(t for _, t in sent) and "#ssi" not in " ".join(t for _, t in sent), sent)
ok("bothelp lists 'channel list' and how to add one", bot.help_for("Public") == ["channel list", "channel list add #name"], bot.help_for("Public"))

# ---- 'channel list add #name' from the mesh
logged = []
api.log = lambda text, level="info": logged.append(text)
def ask(text, nick):
    sent.clear(); bot.last_any = 0
    bot.on_message(msg(text, nick=nick))
    return " ".join(t for _, t in sent)
ok("'channel list add #lse-bot' adds it and says so", ask("channel list add #lse-bot", "Ann") == "Added #lse-bot to the channel list." and "#lse-bot" in api.get("list"))
ok("...and you see who added it", any("Ann added #lse-bot" in l for l in logged), logged)
ok("capitals in the command are fine", ask("Channel List add #Test", "Ben") == "Added #test to the channel list." and "#test" in api.get("list"))
ok("without the '#': the answer shows how to type it, nothing added", ask("channel list add news2", "Bo") == m.ADD_HOW and "#news2" not in api.get("list"))
ok("'channel list add' alone: the same hint", ask("channel list add", "Bea") == m.ADD_HOW)
ok("other wordings ('!channels add #x', 'channels list add #x') are not the add command", ask("!channels add #x1", "Bri") == "" and ask("channels list add #x2", "Bud") == ""
   and "#x1" not in api.get("list") and "#x2" not in api.get("list"))
ok("a channel already there: says so, not added twice", ask("channel list add #LSE-BOT", "Cy").endswith("is already in the channel list.") and api.get("list").count("#lse-bot") == 1)
before = list(api.get("list"))
for bad in ("channel list add #bad name", "channel list add 🐬", "channel list add #public", "channel list add #" + "x" * 40):
    ask(bad, "Dee" + str(len(bad)))
ok("bad names are refused with the hint and nothing is added", api.get("list") == before and ask("channel list add #a!b", "Eli") == m.ADD_HOW, api.get("list"))
ok("the same person again within a minute: quiet", ask("channel list add #again", "Ann") == "" and "#again" not in api.get("list"))
api.set("list", ["#c%d" % i for i in range(m.MAX_CHANNELS)])
ok(f"the list stops at {m.MAX_CHANNELS} channels", ask("channel list add #one-more", "Fay") == f"The channel list is full ({m.MAX_CHANNELS})." and "#one-more" not in api.get("list"))
api.set("list", before)
api.set("allow_add", False)
ok("switched off: 'channel list add' does nothing", ask("channel list add #off", "Gus") == "" and "#off" not in api.get("list"))
ok("...and bothelp no longer mentions it", bot.help_for("Public") == ["channel list"])
root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
