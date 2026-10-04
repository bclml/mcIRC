import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""The weather bot and the fun bot: commands, places, channels, rate limits, message splitting.  Canned data only - no internet, no radio."""
import datetime as dt, filecmp, importlib.util, random, tkinter as tk
from unittest import mock

sys.path[:0] = [os.path.join(ROOT, "packages", "weather_bot"), os.path.join(ROOT, "packages", "fun_bot")]
import meshbot_common as mc
import wxbot_sources as ws
import mcIRC
from gui_addons import AddonAPI

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

# ---- shared plumbing
ok("both bots ship the same meshbot_common.py", filecmp.cmp("packages/weather_bot/meshbot_common.py", "packages/fun_bot/meshbot_common.py", shallow=False))
C = {"wx", "sun", "joke"}
ok("'wx Surrey' is the wx command with 'Surrey'", mc.parse_command("wx Surrey", C) == ("wx", "Surrey"))
ok("'!wx V3T 1V8' works without a prefix set", mc.parse_command("!wx V3T 1V8", C) == ("wx", "V3T 1V8"))
ok("the command must be the first word ('the sun is out' is chat)", mc.parse_command("the sun is out", C) is None)
ok("with prefix '!', plain 'wx' is ignored", mc.parse_command("wx 98101", C, "!") is None and mc.parse_command("!wx 98101", C, "!") == ("wx", "98101"))
ok("channel lists: '#weather, Public' / 'all'", mc.channel_list("#weather, Public") == {"#weather", "public"} and mc.channel_list("all") == {"*"})
ok("channel names match with or without '#'", mc.channel_ok("#Weather", mc.channel_list("weather")) and not mc.channel_ok("#bot-van", mc.channel_list("#weather")))
lim = mc.Limiter(per_user=30, gap=5)
ok("rate limit: one answer, then the same person waits", lim.allow("a", 100) and not lim.allow("a", 120) and lim.allow("a", 131))
ok("rate limit: 5 seconds between any two answers", not lim.allow("b", 133) and lim.allow("b", 137))
long = "Seattle WA: " + " | ".join(f"Day{i} 70F Partly Sunny, wind NW 5 to 10 mph" for i in range(6))
parts = mc.split_message(long)
ok("long answers are cut into mesh-sized messages (max 3)", 1 < len(parts) <= 3 and all(len(p) <= mc.MAX_CHARS for p in parts), [len(p) for p in parts])

# ---- places
GEO = {"results": [{"name": "Surrey", "latitude": 51.25, "longitude": -0.42, "admin1": "England", "country_code": "GB", "population": 1_100_000},
                   {"name": "Surrey", "latitude": 49.106, "longitude": -122.825, "admin1": "British Columbia", "country_code": "CA", "population": 517_000},
                   {"name": "Surrey City Centre", "latitude": 49.18, "longitude": -122.84, "admin1": "British Columbia", "country_code": "CA", "population": 0}]}
def fake_get(url, params=None, *a, **k):
    if "geocoding" in url: return GEO
    if "zippopotam.us/us/98101" in url: return {"places": [{"place name": "Seattle", "state abbreviation": "WA", "latitude": "47.61", "longitude": "-122.33"}]}
    if "zippopotam.us/ca/V3T" in url: return {"places": [{"place name": "Surrey Inner Northwest", "state abbreviation": "BC", "latitude": "49.18", "longitude": "-122.86"}]}
    raise AssertionError(url)
home = (49.19, -122.85, "here")
ok("'surrey' near Vancouver is Surrey BC (the city, not a neighbourhood)", mc.resolve_place("surrey", get=fake_get, near=home)[:3] == (49.106, -122.825, "Surrey"))
ok("'Surrey, England' honours the region", mc.resolve_place("Surrey, England", get=fake_get, near=home)[0] == 51.25)
ok("US ZIP codes", mc.resolve_place("98101", get=fake_get)[2] == "Seattle WA")
ok("Canadian postal codes (full or first 3)", mc.resolve_place("V3T 1V8", get=fake_get)[2].endswith("BC") and mc.resolve_place("v3t", get=fake_get)[0] == 49.18)
ok("coordinates", mc.resolve_place("49.38,-121.44")[:2] == (49.38, -121.44))
ok("no place given -> the bot's own location", mc.resolve_place("", default=home) == home)
class Nodes:
    def all(self): return [{"name": "VE7RPT Seymour", "lat": 49.36, "lon": -122.95}, {"name": "No position", "lat": 0, "lon": 0}]
ok("the name of a known node or repeater", mc.resolve_place("seymour", nodes=Nodes(), get=fake_get)[:2] == (49.36, -122.95))

# ---- answers from canned data
OM = {"current": {"temperature_2m": 12.4, "relative_humidity_2m": 80, "weather_code": 61, "wind_speed_10m": 9, "wind_direction_10m": 225},
      "daily": {"time": ["2026-10-04", "2026-10-05", "2026-10-06"], "weather_code": [61, 3, 0], "temperature_2m_max": [14, 13, 16],
                "temperature_2m_min": [8, 7, 6], "precipitation_probability_max": [80, 20, 0]}}
g = ws.gwx(49.1, -122.8, "Surrey", get=lambda *a, **k: OM)
ok("gwx: now + three days", g.startswith("Surrey: 12C light rain, wind 9 km/h SW, 80% RH | Today 14/8C light rain 80%rain") and "Tue 16/6C clear" in g, g)
noaa404 = mock.Mock(side_effect=Exception("HTTP Error 404: Not Found"))
try: ws.wx(49.1, -122.8, "Surrey", get=noaa404); wx_err = None
except ValueError as e: wx_err = str(e)
ok("wx outside the US says NOAA is US only (the bot then answers from Open-Meteo)", wx_err and "US only" in wx_err)
ok("moon: full moon on 2024-04-23 23:49 UTC", ws.moon(dt.datetime(2024, 4, 23, 23, 49, tzinfo=dt.timezone.utc)).startswith("Moon: Full moon, 100% lit"))
steps = {"minutely_15": {"time": [f"2026-10-04T12:{m:02d}" for m in (0, 15, 30, 45)] + [f"2026-10-04T13:{m:02d}" for m in (0, 15, 30, 45)],
                         "precipitation": [0, 0, 0.4, 1.2, 0.8, 0, 0, 0]}}
ok("rain: tells when it starts", ws.rain(1, 1, "Hope", get=lambda *a, **k: steps) == "Rain Hope: rain from about 12:30, up to 1.2 mm/15min")

# ---- the addons in the real window
root = tk.Tk()
app = mcIRC.App(root, demo=True); root.update()
app.connected = True
def run_now(fn, done):
    try: r = fn()
    except Exception as e: r = e
    done(r)
app.bg = run_now
sent = []
app.send_to = lambda ch, text: sent.append((ch, text))
app.send_dm = lambda w, text: sent.append((w.name, text))
def load(pkg, name):
    spec = importlib.util.spec_from_file_location("t_" + name, os.path.join(ROOT, "packages", pkg, name + ".py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    api = AddonAPI(app, name); api.after = lambda ms, fn: fn()
    inst = m.Addon(api); inst.on_load(); return m, inst, api
wmod, wx_bot, wapi = load("weather_bot", "weather_bot")
msg = lambda text, ch="#weather", nick="Bob", dm=False: {"channel": ch, "channel_idx": 7, "nick": nick, "text": text, "snr": 5, "hops": 1, "raw": {}, "dm": dm}
wx_bot.on_message(msg("moon"))
ok("the weather bot is off until switched on", sent == [])
wapi.set("enabled", True)
with mock.patch.object(ws, "gwx", lambda lat, lon, label, units="metric", get=None: f"{label}: canned"), \
        mock.patch.object(ws, "wx", mock.Mock(side_effect=ValueError("NOAA covers the US only"))), \
        mock.patch.object(mc, "resolve_place", lambda arg, **k: (49.1, -122.8, arg.title() or "here")):
    wx_bot.on_message(msg("wx surrey"))
    ok("'wx surrey' in #weather answers for Surrey (Open-Meteo when NOAA has nothing)", sent == [("#weather", "Surrey: canned")], sent)
    sent.clear(); wx_bot.on_message(msg("wx surrey", ch="#bot-van", nick="Cat"))
    ok("not answered outside its channels", sent == [])
    sent.clear(); wx_bot.on_message(msg("wx langley", nick="Bob"))
    ok("the same person is rate-limited", sent == [])
    sent.clear(); wx_bot.limiter.last_any = 0; wx_bot.on_message(msg("wx surrey", ch="@Dan", nick="Dan", dm=True))
    ok("private messages are ignored unless switched on", sent == [])
wx_bot.limiter = mc.Limiter(0, 0)
sent.clear(); wx_bot.on_message(msg("moon", nick="Eve"))
ok("moon answers in the channel", len(sent) == 1 and sent[0][1].startswith("Moon:"), sent)
sent.clear(); wx_bot.on_message(msg("channels", nick="Fay"))
ok("channels says where it answers", sent and "I answer in #weather" in sent[0][1], sent)
wapi.set("off", ["moon"]); sent.clear(); wx_bot.on_message(msg("moon", nick="Gus"))
ok("a command switched off is ignored", sent == [])
with mock.patch.object(ws, "aqi", mock.Mock(side_effect=OSError("timed out"))), mock.patch.object(mc, "resolve_place", lambda arg, **k: (1, 1, "X")):
    sent.clear(); wx_bot.on_message(msg("aqi hope", nick="Hal"))
ok("a service that is down gives a short polite answer", sent and "not answering right now" in sent[0][1], sent)

fmod, fun, fapi = load("fun_bot", "fun_bot")
fapi.set("enabled", True); fapi.set("channels", {"dice": "#bot-van", "joke": "all"})
fun.limiter = mc.Limiter(0, 0)
sent.clear(); fun.on_message(msg("dice 3d6", ch="#bot-van"))
ok("dice 3d6 in a channel where dice is on", sent and sent[0][0] == "#bot-van" and "3d6:" in sent[0][1], sent)
sent.clear(); fun.on_message(msg("dice 3d6", ch="#weather"))
ok("...and not where it is off", sent == [])
sent.clear(); fun.on_message(msg("joke", ch="Public"))
ok("'all' means every channel", sent and sent[0][1] in __import__("funbot_data").JOKES)
sent.clear(); fun.on_message(msg("catfact", ch="#bot-van"))
ok("commands with no channels are off", sent == [])
ok("dice d20 gives one roll", fmod.roll_dice("d20", random.Random(1)).startswith("\U0001F3B2 1d20: "))
try: fmod.roll_dice("99d6"); bad = None
except ValueError as e: bad = str(e)
ok("too many dice is refused with a hint", bad and "1-20 dice" in bad, bad)
ok("roll 50 stays within 1-50", all(1 <= int(fmod.roll("50").split()[1]) <= 50 for _ in range(50)))
WC = {"leagues": [{"season": {"type": {"name": "Final"}}}], "events": [{"competitions": [{"status": {"type": {"state": "post", "shortDetail": "AET"}},
      "competitors": [{"homeAway": "away", "team": {"abbreviation": "ARG"}, "score": "0"}, {"homeAway": "home", "team": {"abbreviation": "ESP"}, "score": "1"}]}]}]}
ok("wc: latest scores", fmod.world_cup("", get=lambda *a, **k: WC) == "WC Final: ESP 1-0 ARG (AET)")
root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
