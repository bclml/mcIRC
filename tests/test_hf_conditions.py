import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""HF conditions bot: trigger words you choose, only in the channels you choose, never in Public; one fetch serves everyone for 30 min.
No radio, no internet (hamqsl.com's answer is a saved copy)."""
import filecmp, importlib.util, re, time, tkinter as tk

sys.path[:0] = [os.path.join(ROOT, "packages", "hf_conditions")]
import mcIRC
from gui_addons import AddonAPI

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

XML = """<?xml version="1.0" encoding="UTF-8" ?><solar><solardata>
<source url="http://www.hamqsl.com/solar.html">N0NBH</source><updated> 30 Oct 2026 0001 GMT</updated>
<solarflux>89</solarflux><aindex> 4</aindex><kindex> 0</kindex><xray>B2.6</xray><sunspots>22</sunspots>
<calculatedconditions>
<band name="80m-40m" time="day">Good</band><band name="30m-20m" time="day">Fair</band><band name="17m-15m" time="day">Poor</band><band name="12m-10m" time="day">Poor</band>
<band name="80m-40m" time="night">Good</band><band name="30m-20m" time="night">Fair</band><band name="17m-15m" time="night">Poor</band><band name="12m-10m" time="night">Poor</band>
</calculatedconditions><calculatedvhfconditions>
<phenomenon name="vhf-aurora" location="northern_hemi">Band Closed</phenomenon><phenomenon name="E-Skip" location="north_america">Band Closed</phenomenon>
</calculatedvhfconditions><geomagfield>INACTIVE</geomagfield><signalnoise>S0-S1</signalnoise></solardata></solar>"""

ok("it ships the same meshbot_common.py as the other bots", filecmp.cmp("packages/hf_conditions/meshbot_common.py", "packages/area_alerts/meshbot_common.py", shallow=False))
spec = importlib.util.spec_from_file_location("t_hf", os.path.join(ROOT, "packages", "hf_conditions", "hf_conditions.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

# ---- the answer
r = m.report(XML)
ok("the report has the numbers", r.startswith("HF 0001Z: SFI 89, SSN 22, A 4, K 0 (quiet), X-ray B2.6, noise S0-S1"), r)
ok("...and every band by day and night", "Day: 80m-40m Good, 30m-20m Fair, 17m-15m Poor, 12m-10m Poor" in r and "Night: 80m-40m Good" in r, r)
ok("...and no VHF line while every VHF band is closed", "VHF" not in r, r)
r2 = m.report(XML.replace('location="north_america">Band Closed', 'location="north_america">50MHz ES'))
ok("an open VHF band is named", r2.endswith("VHF open: E-Skip north america"), r2)
ok("a storm is called one", m.k_word(6) == "storm G2" and m.k_word(4) == "active" and m.k_word(2) == "quiet")
try: m.report("<solar></solar>"); ok("an answer without data is an error", False)
except ValueError: ok("an answer without data is an error", True)

# ---- trigger words
T = m.trigger_list("HF, condx,  hf conditions, hf")
ok("trigger words: trimmed, lower case, each once, several words allowed", T == ["hf", "condx", "hf conditions"], T)
ok("'hf', '!hf', '@[Bot] hf' and 'hf please' ask", all(m.asked(t, T) for t in ("hf", "!HF", "@[Bot] hf", "@Bot: condx", "hf please", "hf conditions?")))
ok("...'hfx', 'what about hf' and 'half' don't", not any(m.asked(t, T) for t in ("hfx", "what about hf", "half", "")))

# ---- in mcIRC (demo app, stand-in fetch)
root = tk.Tk()
app = mcIRC.App(root, demo=True); root.update()
app.settings["bots_in_public"] = True          # mcIRC itself would let a bot post in Public: the addon must refuse on its own
app.connected = True
sent, WHO = [], re.compile(r"^@\[[^\]]*\]: |^@\S+: ")
app.send_to = lambda ch, text: sent.append((ch, WHO.sub("", text, count=1)))
app.send_dm = lambda w, text: sent.append((w.name if hasattr(w, "name") else str(w), text))
api = AddonAPI(app, "hf_conditions"); api.after = lambda ms, fn: fn()
fetches = []
def fake_get(url, timeout=12, **k): fetches.append(url); return XML.encode()
m.mc.http_get = fake_get
def run_now(fn, done):                                  # as mcIRC's: the result, or the exception, goes to done()
    try: r = fn()
    except Exception as e: r = e
    done(r)
api.run_background = run_now
real_reply = api.reply
api.reply = lambda msg, text, private=None: sent.append((msg["channel"], text)) if msg.get("dm") else real_reply(msg, text, private)
bot = m.Addon(api); api.display = bot.title; bot.on_load()
msg = lambda text, ch="#hf", nick="Bob", dm=False: {"channel": ch, "channel_idx": 1, "nick": nick, "text": text, "snr": 1, "hops": 0, "raw": {}, "dm": dm}

bot.on_message(msg("hf"))
ok("off until switched on", sent == [] and not fetches)
api.set("enabled", True)
bot.on_message(msg("hf"))
ok("on, but no channel chosen yet: quiet", sent == [] and not fetches)
api.set("channels", "#hf, #ham")
bot.on_message(msg("hf"))
ok("'hf' in a chosen channel is answered", sent and sent[0][0] == "#hf" and sent[0][1].startswith("HF 0001Z: SFI 89"), sent)
ok("...in mesh-sized parts", 2 <= len(sent) <= 3 and all(len(t) <= 115 for _, t in sent), [len(t) for _, t in sent])
ok("...from hamqsl.com", fetches == [m.URL])
sent.clear(); bot.on_message(msg("hf"))
ok("the same person again within a minute: quiet", sent == [])
sent.clear(); bot.limiter.last_any = 0; bot.on_message(msg("condx", ch="#ham", nick="Cat"))
ok("someone else in the other channel: answered from the saved report (no second fetch)", sent and sent[0][0] == "#ham" and len(fetches) == 1, (sent, fetches))
sent.clear(); bot.limiter.last_any = 0; bot.on_message(msg("hf", ch="#general", nick="Dan"))
ok("a channel that isn't chosen: quiet", sent == [])

# ---- never in Public
api.set("channels", "all")
for i, ch in enumerate(("Public", "public", "#public", "Public [915]")):
    sent.clear(); bot.limiter.last_any = 0; bot.on_message(msg("hf", ch=ch, nick=f"P{i}"))
    ok(f"'All channels' picked, asked in {ch!r}: never answered", sent == [], sent)
sent.clear(); bot.limiter.last_any = 0; bot.on_message(msg("hf", ch="#anything", nick="Eve"))
ok("'All channels' still answers every other channel", sent and sent[0][0] == "#anything")
api.set("channels", "Public, #hf")
ok("Public typed into the settings by hand is ignored", bot.where() == {"#hf"} and bot.channels_used() == ["#hf"], bot.where())
ok("bothelp: shown where it answers, never in Public", bot.help_for("#hf") == ["hf"] and bot.help_for("Public") == [], (bot.help_for("#hf"), bot.help_for("Public")))

# ---- private messages
sent.clear(); bot.limiter.last_any = 0; bot.on_message(msg("hf", ch="@Fay", nick="Fay", dm=True))
ok("a private message is answered (on by default)", len(sent) >= 1, sent)
api.set("answer_dm", False)
sent.clear(); bot.limiter.last_any = 0; bot.on_message(msg("hf", ch="@Gus", nick="Gus", dm=True))
ok("...and not when that is switched off", sent == [])
api.set("answer_dm", True)

# ---- the report is read again after 30 minutes; a failure says so once
bot.cached_at -= m.CACHE + 1
sent.clear(); bot.limiter.last_any = 0; bot.on_message(msg("hf", nick="Hal"))
ok("after 30 minutes it is read again", len(fetches) == 2)
def down(url, timeout=12, **k): raise OSError("timed out")
m.mc.http_get, bot.cached = down, ""
sent.clear(); bot.limiter.last_any = 0; bot.on_message(msg("hf", nick="Ian"))
ok("hamqsl.com down: a short 'try later'", [t for _, t in sent] == ["HF conditions: not reachable right now, try later"], sent)

# ---- settings window
top = tk.Toplevel(root); frame = bot.build_options(top)
bot.v_trig.set("HF , propagation report,,"); bot.v_chan.set("#hf, Public, #ham"); bot.v_cool.set("3"); bot.apply_options()
ok("settings: trigger words saved tidy", api.get("triggers") == "hf, propagation report", api.get("triggers"))
ok("settings: Public never saved as a channel", api.get("channels") == "#hf, #ham", api.get("channels"))
ok("settings: at least 10 s between answers to one person", api.get("cooldown") == 10 and bot.limiter.per_user == 10)
bot.v_trig.set(" , "); bot.apply_options()
ok("settings: no trigger words left -> the defaults", api.get("triggers") == m.DEFAULT_TRIGGERS)
bot.on_unload(); root.destroy()

print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
