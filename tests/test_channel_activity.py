import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""Channel activity: LoRa airtime, per-minute counts, the node's noise floor / airtime counters, and the window.  No radio."""
import importlib.util, time, tkinter as tk

sys.path[:0] = [os.path.join(ROOT, "packages", "channel_activity")]
import chact_core as c

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

# ---- airtime (Semtech's calculator: 20 bytes, 8-symbol preamble, CR 4/5: SF7/125 kHz 56.6 ms, SF12/125 kHz 1318.9 ms)
ok("time on air SF7 125 kHz 20 bytes = 56.6 ms", round(c.time_on_air_ms(20, 7, 125, 5, 8), 1) == 56.6)
ok("time on air SF12 125 kHz 20 bytes = 1318.9 ms (low data rate optimisation on)", round(c.time_on_air_ms(20, 12, 125, 5, 8), 1) == 1318.9)
ok("a narrower band and a bigger packet take longer", c.time_on_air_ms(60, 7, 62.5, 5) > c.time_on_air_ms(60, 7, 125, 5) > c.time_on_air_ms(20, 7, 125, 5))
ok("bytes on air: payload + header + path length + path", c.packet_bytes({"length": 40, "path": "a1b2c3"}) == 45)

# ---- counting
now = 1_800_000_030.0                    # 30 s into a minute
act = c.Activity()
pk = lambda t, kind="GRP_TXT", snr=5.0, rssi=-100, length=40: {"t": t, "type": kind, "path": "a1", "snr": snr, "rssi": rssi, "length": length}
log = [pk(now - 50), pk(now - 40, "ADVERT", 1.0, -110, 120), pk(now - 30), pk(now - 200, "ACK", 9.0, -90, 4)]
ok("4 new packets counted", act.add_packets(log, 7, 62.5, 5) == 4)
ok("...and not again the next time", act.add_packets(log, 7, 62.5, 5) == 0)
s = act.summary(now, 60)
ok("the last hour: 4 packets, kinds by count", s["packets"] == 4 and s["kinds"] == {"GRP_TXT": 2, "ADVERT": 1, "ACK": 1}, s)
ok("...median SNR and signal", s["snr"] == 5.0 and s["rssi"] == -100, (s["snr"], s["rssi"]))
expected = sum(c.time_on_air_ms(c.packet_bytes(p), 7, 62.5, 5) for p in log) / 1000 / 3570 * 100     # 59 minutes and 30 s so far
ok("...airtime % over the hour", abs(s["air_pct"] - expected) < 1e-9, (s["air_pct"], expected))
ok("this minute so far has only the newest one", act.summary(now, 1)["packets"] == 1)
rows = act.series(now, 60, 1)
ok("graph data: 60 one-minute rows, packets per minute in the right minutes", len(rows) == 60 and sum(r[1] for r in rows) == 4)
ok("6-hour graph: 60 rows of 6 minutes", len(act.series(now, 360, 6)) == 60)
act.buckets[c.minute(now - 2 * 86400)] = {"n": 9, "air_ms": 1.0, "kinds": {}, "snr": [], "rssi": []}
act.trim(now)
ok("older than a day is dropped", all(k >= now - 86400 - 60 for k in act.buckets))

# ---- the node's counters
ok("stats_radio read from meshcli's output", c.parse_stats('INFO:meshcore:x\n{"noise_floor": -112, "last_rssi": -90, "rx_air_secs": 100, "tx_air_secs": 5}')["noise_floor"] == -112)
ok("...nothing usable: {}", c.parse_stats("Error: not connected") == {})
act.add_noise(now - 300, {"noise_floor": -112, "rx_air_secs": 100, "tx_air_secs": 5})
act.add_noise(now, {"noise_floor": -110, "rx_air_secs": 130, "tx_air_secs": 8})
rx, tx = act.node_airtime_pct()
ok("the node's own airtime between two readings: 10 % receiving, 1 % sending", abs(rx - 10) < 1e-9 and abs(tx - 1) < 1e-9, (rx, tx))
act.add_noise(now + 300, {"noise_floor": -111, "rx_air_secs": 2, "tx_air_secs": 0})
ok("...not after the node restarted (its counters went back)", act.node_airtime_pct() is None)
ok("signal margin in words", (c.margin_word(20), c.margin_word(8), c.margin_word(3)) == ("good", "fair", "weak"))

# ---- the addon and its window (a stand-in for mcIRC)
spec = importlib.util.spec_from_file_location("t_ca", os.path.join(ROOT, "packages", "channel_activity", "channel_activity.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
root = tk.Tk(); root.withdraw()
class Api:
    def __init__(s): s.s, s.log, s.connected, s.jobs = {}, [], False, []
    def get(s, k, d=None): return s.s.get(k, d)
    def set(s, k, v): s.s[k] = v
    def add_menu_item(s, *a): pass
    def ui(s): return {"root": root}
    def listening(s): return "on"
    def run_background(s, fn, done): s.jobs.append((fn, done))
    @property
    def packet_log(s): return list(s.log)
api = Api()
a = m.Addon(api); a.on_load()
t = time.time()
api.log = [pk(t - 600)]
a.on_tick()
ok("packets heard before it started aren't counted", a.act.summary(time.time(), 60)["packets"] == 0)
api.log += [pk(time.time() + 1), pk(time.time() + 2, "ADVERT")]
a.on_tick()
ok("new packets are counted on each tick", a.act.summary(time.time() + 5, 60)["packets"] == 2)
ok("not connected: the node isn't read", api.jobs == [])
api.connected = True; a.on_tick()
ok("connected: the noise floor is read in the background (once per interval)", len(api.jobs) == 1)
a.on_tick()
ok("...not again until the interval has passed", len(api.jobs) == 1)
api.jobs[0][1]({"noise_floor": -115, "rx_air_secs": 1, "tx_air_secs": 0})
ok("the reading is kept", a.act.noise[-1][1] == -115)
api.s["noise_minutes"] = 0; a.last_noise = 0; a.on_tick()
ok("reading switched off (0 minutes): never read", len(api.jobs) == 1)
a.on_connect()
api.jobs[-1][1]({"info": {"radio_sf": 9, "radio_bw": 125, "radio_cr": 6, "radio_freq": 869.525}, "radio": {"noise_floor": -118}})
ok("after connecting, the node's radio settings are used for the airtime", a.radio == {"sf": 9, "bw": 125.0, "cr": 6} and "869.525" in a.radio_from)
a.open(); root.update()
w = a.win
ok("the window shows packets per minute and the noise floor", w.vals["Noise floor"].cget("text") == "-118 dBm" and w.vals["Packets / min"].cget("text") != "-",
   (w.vals["Noise floor"].cget("text"), w.vals["Packets / min"].cget("text")))
ok("...the kinds heard", w.kinds.cget("text").startswith("Kinds: ") and "ADVERT 1" in w.kinds.cget("text"), w.kinds.cget("text"))
ok("...and the signal margin", w.vals["Signal margin"].cget("text") == "18 dB", w.vals["Signal margin"].cget("text"))
for i in range(3): w.rng.set(i); w.refresh()
ok("all three time ranges draw", len(w.c.find_all()) > 5)
api.listening = lambda: "bluetooth"; w.refresh()
ok("over Bluetooth it explains why nothing is counted", "Bluetooth" in w.note.cget("text"))
a.on_unload(); root.destroy()

print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
