import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""Repeater manager: the meshcli requests, reading their answers, one request at a time, the timer, passwords in memory only, the window.
No radio: meshcli is a stand-in."""
import importlib.util, json, tempfile, time, tkinter as tk, types

sys.path[:0] = [os.path.join(ROOT, "packages", "repeater_manager")]
import rptmgr_core as c

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

K = "a1" * 32
STATUS = {"pubkey_pre": "a1a1a1a1a1a1", "bat": 4120, "tx_queue_len": 0, "noise_floor": -112, "last_rssi": -95, "nb_recv": 1000, "nb_sent": 400,
          "airtime": 720, "uptime": 3 * 86400 + 4 * 3600, "sent_flood": 1, "sent_direct": 1, "recv_flood": 1, "recv_direct": 1, "full_evts": 0,
          "last_snr": 6.5, "direct_dups": 0, "flood_dups": 0, "rx_airtime": 100, "recv_errors": 2}

# ---- the requests
ok("status, logged in: login first, then req_status, as JSON", c.request_args(K, "status", "pw") == ["-j", "login", K, "pw", "req_status", K])
ok("status without a password: just req_status", c.request_args(K, "status") == ["-j", "req_status", K])
ok("a remote command waits 8 s for the reply", c.request_args(K, "cmd", None, "ver") == ["cmd", K, "ver", "wmt8"])
ok("a forgotten contact is put back first (flood routed)", c.readd_args(K, 2, "Hill", ["-j", "req_status", K]) == ["-j", "add_contact", K, "2", "Hill", "reset_path", K, "req_status", K])
ok("dangerous commands are spotted", all(c.dangerous(x) for x in ("reboot", "set tx 22", "password abc", "start ota", " ERASE ", "setperm ab 3")))
ok("...and harmless ones aren't", not any(c.dangerous(x) for x in ("ver", "clock", "get tx", "neighbors", "settings", "rebooted?")))

# ---- the answers
out = 'INFO:meshcore:connected\n{\n "login_success": true\n}\n' + json.dumps(STATUS, indent=4)
r = c.parse(out)
ok("login and status read from meshcli's output", r["login"] is True and r["status"]["bat"] == 4120)
ok("the status in words", c.status_text(STATUS) == "battery 4.12 V, up 3 d 4 h, noise -112 dBm, last signal -95 dBm / SNR 6.5, received 1000, sent 400, "
   "airtime 12 min, queue 0, receive errors 2", c.status_text(STATUS))
nb = {"neighbours_count": 3, "results_count": 2, "neighbours": [{"pubkey": "b2b2b2b2", "secs_ago": 120, "snr": 2.5}, {"pubkey": "c3c3c3c3", "secs_ago": 3700, "snr": 8.0}]}
ok("neighbours, strongest first, by name when known", c.neighbours_text(nb, {"b2" * 32: "Demo Valley RPT"}) ==
   "[c3c3c3c3] +8.0 dB (1 h 1 min ago); Demo Valley RPT +2.5 dB (2 min ago)  (2 of 3)", c.neighbours_text(nb, {"b2" * 32: "Demo Valley RPT"}))
tl = c.parse(json.dumps({"name": "Hill", "pubkey_pre": "a1", "lpp": [{"channel": 1, "type": "voltage", "value": 4.125}, {"channel": 2, "type": "temperature", "value": 21.5}]}))
ok("telemetry in words", c.telemetry_text(tl["telemetry"]) == "voltage 4.12 (ch 1), temperature 21.5 (ch 2)", c.telemetry_text(tl["telemetry"]))
ok("a wrong password is reported", c.parse('{"login_success": false, "error": "login failed"}')["login"] is False)
ok("no answer is reported", c.parse("Error getting data")["error"].startswith("no answer"))
ok("an unknown contact is spotted", c.unknown_contact("Unknown contact a1a1") and c.unknown_contact('{"error": "contact unknown"}'))
ok("a remote command's reply without meshcli's logging", c.clean_lines("INFO:meshcore:x\n\x1b[32mv1.12.0\x1b[0m\n") == ["v1.12.0"])

# ---- history
tmp = tempfile.mkdtemp(prefix="mcirc_rm_")
h = c.History(os.path.join(tmp, "logs", "rm.json"))
h.add(K, 1000, STATUS); h.add(K, 4600, dict(STATUS, nb_recv=1360, bat=4100)); h.add(K, 8200, dict(STATUS, nb_recv=10))
ok("battery over time", h.series(K, 1) == [(1000, 4120), (4600, 4100), (8200, 4120)])
ok("packets received per hour; a restart is skipped", h.per_hour(K, 5) == [(4600, 360.0)], h.per_hour(K, 5))
h.save(); h2 = c.History(h.path); h2.load()
ok("saved and read back", h2.rows == h.rows)

# ---- the addon (stand-ins for mcIRC and meshcli)
spec = importlib.util.spec_from_file_location("t_rm", os.path.join(ROOT, "packages", "repeater_manager", "repeater_manager.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.HISTORY = os.path.join(tmp, "logs", "repeater_manager.json")
import meshcore_io as io
calls, replies = [], []
def fake_exec(args, timeout=30, retries=2, **k):
    calls.append((args, retries))
    return types.SimpleNamespace(stdout=replies.pop(0) if replies else "", stderr="")
io.execute_mesh_command = fake_exec
io.CONNECTION_ARGS = ["-s", "COM9"]
root = tk.Tk(); root.withdraw()
class Nodes:
    def all(self): return [{"public_key": K, "name": "Demo Hilltop RPT", "type": 2, "lat": 0, "lon": 0},
                           {"public_key": "b2" * 32, "name": "Demo Valley RPT", "type": 2, "lat": 0, "lon": 0},
                           {"public_key": "c3" * 32, "name": "Demo Alice", "type": 1, "lat": 0, "lon": 0}]
class Api:
    def __init__(s): s.s, s.connected, s.wrote, s.logged = {}, True, [], []
    def get(s, k, d=None): return s.s.get(k, d)
    def set(s, k, v): s.s[k] = v
    def log(s, t, level="info"): s.logged.append(t)
    def write(s, win, t, tag="text"): s.wrote.append((win, t, tag))
    def add_menu_item(s, *a): pass
    def ui(s): return {"root": root}
    def run_background(s, fn, done):
        try: r = fn()
        except Exception as e: r = e
        done(r)
    nodes = Nodes()
api = Api()
a = m.Addon(api); a.on_load()
a.add([K, K])
ok("a repeater is added once", a.keys() == [K])
a.pw[K] = "secret"
replies.append('{"login_success": true}\n' + json.dumps(STATUS))
a.request(K, "status")
ok("Status: login + req_status sent once, never retried", calls[-1] == (["-s", "COM9", "-j", "login", K, "secret", "req_status", K], 0), calls[-1])
ok("...the answer is shown and kept", "battery 4.12 V" in api.wrote[-1][1] and a.hist.last(K)[1] == 4120, api.wrote[-1])
ok("the password is never written to the settings or a window", "secret" not in json.dumps(api.s) and not any("secret" in w[1] for w in api.wrote))
replies.extend(["Unknown contact a1a1", '{"neighbours_count": 0, "results_count": 0, "neighbours": []}'])
a.request(K, "neighbours")
ok("a contact the radio forgot is put back and asked again", calls[-1][0][2:6] == ["-j", "add_contact", K, "2"] and api.wrote[-1][1].endswith("neighbours: no neighbours"))
replies.append('{"login_success": false, "error": "login failed"}')
a.request(K, "login")
ok("a wrong password: said, and forgotten", "login failed" in api.wrote[-1][1] and K not in a.pw, api.wrote[-1])
a.busy = True
a.request(K, "status"); a.request(K, "telemetry")
ok("while one request runs, the next ones wait", len(a.queue) == 2)
a.busy = False; replies.extend([json.dumps(STATUS), json.dumps({"lpp": []})]); n = len(calls); a.next()
ok("...and go out one after the other", len(calls) == n + 2 and not a.queue and api.wrote[-1][1].endswith("telemetry: no telemetry"))
api.connected = False; a.request(K, "status")
ok("not connected: nothing is sent", len(calls) == n + 2 and "Not connected" in api.wrote[-1][1])
api.connected = True
# the timer
a.on_tick(); ok("status on a timer is off by default", len(calls) == n + 2)
api.s["poll_minutes"] = 5
ok("the timer is at least 30 minutes", a.poll_minutes() == 30)
a.hist.rows[K][-1][0] = time.time() - 31 * 60; a.last_auto = 0
replies.append(json.dumps(STATUS)); a.on_tick()
ok("due: one automatic status request", len(calls) == n + 3 and calls[-1][0][-2] == "req_status")
a.on_tick()
ok("...not again right away", len(calls) == n + 3)
# the window
import rptmgr_window as rw
a.open(); root.update(); w = a.win
ok("the window lists the repeater with its last battery reading", w.t.item(K, "values")[3] == "4.12 V", w.t.item(K, "values"))
w.t.selection_set(K); root.update()
ok("its graphs are drawn", len(w.c.find_all()) > 6)
rw.messagebox.askyesno = lambda *x, **k: False
w.cmd.set("reboot"); w.send_cmd()
ok("a dangerous command asks first; 'no' sends nothing", len(calls) == n + 3)
replies.append("v1.12.0-abc"); w.cmd.set("ver"); w.send_cmd()
ok("a harmless command is sent and its reply shown in the window", calls[-1][0][-4:] == ["cmd", K, "ver", "wmt8"] and "v1.12.0-abc" in w.out.get("1.0", "end"))
rw.messagebox.askyesno = lambda *x, **k: True
w.remove()
ok("Remove (after asking) takes it off the page and deletes its history", a.keys() == [] and K not in a.hist.rows)
ok("no warnings were logged", api.logged == [], api.logged)
a.on_unload(); root.destroy()

print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
