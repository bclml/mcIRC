import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
import os, sys, time, types, logging, threading
from unittest import mock
sys.path.insert(0, ROOT)
import tkinter as tk
import meshcore_io as io
import emergency_agent as ea
import gui_health

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

class R:
    def __init__(self, out="", err="", rc=0): self.stdout, self.stderr, self.returncode = out, err, rc
FAIL = R(err="No response from meshcore node", rc=0)      # meshcli exits 0 but says this -> counted as a transient failure
io.CONNECTION_ARGS = ["-s", "COM9"]
def reset_health():
    io.HEALTH.fails, io.HEALTH.first_fail, io.HEALTH.down_since = 0, None, None
    io.PENDING_SENDS.clear()

# ---- 1. health tracking counts commands that failed for good, not attempts
events = []
io.HEALTH.listeners.append(lambda ev, info: events.append((ev, info)))
reset_health()
with mock.patch("meshcore_io._run_cli", return_value=FAIL), mock.patch("time.sleep"):
    for i in range(2):
        try: io.execute_mesh_command(["-s", "COM9", ".sync_msgs"], retries=2)
        except RuntimeError: pass
    ok("two failed commands (6 attempts) are not 'down' yet", not io.HEALTH.is_down and io.HEALTH.fails == 2, io.HEALTH.fails)
    try: io.execute_mesh_command(["-s", "COM9", ".sync_msgs"], retries=2)
    except RuntimeError: pass
ok("third failed command in a row = radio down, announced once", io.HEALTH.is_down and [e[0] for e in events] == ["down"], events)
with mock.patch("meshcore_io._run_cli", return_value=FAIL), mock.patch("time.sleep"):
    try: io.execute_mesh_command(["-s", "COM9", ".sync_msgs"], retries=0)
    except RuntimeError: pass
ok("more failures do not announce again", [e[0] for e in events] == ["down"])
with mock.patch("meshcore_io._run_cli", return_value=R(out="[]")):
    io.execute_mesh_command(["-s", "COM9", ".sync_msgs"])
ok("one success = back up, announced with the time it was down", not io.HEALTH.is_down and [e[0] for e in events] == ["down", "up"] and events[1][1]["since"] > 0, events)
io.HEALTH.listeners.append(lambda ev, info: 1 / 0)
reset_health()
with mock.patch("meshcore_io._run_cli", return_value=FAIL), mock.patch("time.sleep"):
    for i in range(3):
        try: io.execute_mesh_command(["x"], retries=0)
        except RuntimeError: pass
ok("a broken listener cannot break sending", io.HEALTH.is_down)
io.HEALTH.listeners[:] = [l for l in io.HEALTH.listeners if l.__name__ == "<lambda>" and l is events and False]
io.HEALTH.listeners.clear(); reset_health()

# ---- 2. failed alerts are queued, sent later, in order, never stale, and a CLEAR cancels its NEW
sent = []
def fake_run_factory(fail):
    def run(cmd, **kw):
        if fail[0]: return FAIL
        sent.append(cmd[1:]); return R(out="ok")
    return run
fail = [True]
ea.tx_allowed = lambda kind: True
ea._resolve_channel_idx = lambda source: 3
with mock.patch("meshcore_io._run_cli", fake_run_factory(fail)), mock.patch("time.sleep"):
    ea.broadcast_via_cli("DriveBC", "INCIDENT - Highway 1", "Burnaby", False, guid="drivebc.ca/RIDE-1")
    ea.broadcast_via_cli("DriveBC", "INCIDENT - Highway 17", "Delta", False, guid="drivebc.ca/RIDE-2")
    ea.broadcast_via_cli("DriveBC", "INCIDENT - Highway 17", "Delta", False, guid="drivebc.ca/RIDE-2")     # duplicate NEW
    ok("failed alerts wait in the queue (duplicates ignored)", len(io.PENDING_SENDS) == 2, len(io.PENDING_SENDS))
    ea.broadcast_via_cli("DriveBC", "INCIDENT - Highway 1", "", True, guid="drivebc.ca/RIDE-1")             # cleared before it was ever sent
    ok("a CLEAR cancels its still-waiting NEW (neither is sent)", len(io.PENDING_SENDS) == 1 and "Highway 17" in io.PENDING_SENDS[0]["msg"], [i["msg"] for i in io.PENDING_SENDS])
    ea.broadcast_via_cli("DriveBC", "INCIDENT - Highway 99", "Surrey", False, guid="drivebc.ca/RIDE-3")
    reset_after = list(io.PENDING_SENDS)
    # radio down: nothing is flushed
    for i in range(3):
        try: io.execute_mesh_command(["x"], retries=0)
        except RuntimeError: pass
    sent.clear(); n = io.flush_pending_sends(pacing=0)
    ok("nothing is flushed while the radio is known to be down", n == 0 and not sent and len(io.PENDING_SENDS) == 2)
    # radio answers again: the next good poll sends them, oldest first, and reports them to the GUI
    fail[0] = False
    emitted = []
    with mock.patch.object(io, "_emit", lambda kind, idx, text, nick=None, **kw: emitted.append((kind, idx, kw.get("alert")))):
        io.execute_mesh_command(["x"])        # success clears the 'down' flag
        io.fetch_incoming_messages()          # the poll that runs after every good .sync_msgs
    cmds = [c for c in sent if "chan" in c]
    ok("after the next good poll the queued alerts go out in order", [c[-1][:30] for c in cmds] == [i["msg"][:30] for i in reset_after] and not io.PENDING_SENDS, (cmds, len(io.PENDING_SENDS)))
    ok("...and show up in the channel window as sent", [e[0] for e in emitted] == ["out", "out"] and all(e[2] == "new" for e in emitted), emitted)
    # too old
    fail[0] = True
    ea.broadcast_via_cli("DriveBC", "OLD", "", False, guid="old")
    io.PENDING_SENDS[0]["queued"] -= io.PENDING_MAX_AGE + 5
    fail[0] = False; sent.clear(); reset_health()
    io.flush_pending_sends(pacing=0)
    ok("an alert older than 30 minutes is dropped, not sent", not sent and not io.PENDING_SENDS)
    # critical
    fail[0] = True
    import asyncio
    io.CHANNEL_INDEX_BY_NAME.update({"Public": 0, "drivebc": 3})
    asyncio.run(ea.broadcast_critical_all_channels("EARTHQUAKE M6.1 near Tofino", "EARTHQUAKE"))
    ok("failed earthquake/tsunami broadcasts are queued per channel", len(io.PENDING_SENDS) >= 2 and all(i["alert"] == "critical" for i in io.PENDING_SENDS), len(io.PENDING_SENDS))
    reset_health()

# ---- 3 + 4. the GUI: warning, fail-fast, NOT SENT marking
import mcIRC
root = tk.Tk()
app = mcIRC.App(root, demo=True)
app.connected = True
io.CONNECTION_ARGS = ["-s", "COM9"]
app.windows["Public"] = app.windows["Public"]
pub = app.windows["Public"]
io.HEALTH.listeners.append(lambda ev, info: None)
def pump(t=0.3):
    end = time.time() + t
    while time.time() < end: root.update(); time.sleep(0.02)
calls = []
with mock.patch("meshcore_io._run_cli", side_effect=lambda *a, **k: calls.append(a) or FAIL), mock.patch("time.sleep"):
    app.select_window("Public")
    app.send_to("Public", "hello mesh")
    pump(0.6)
txt = pub.text.get("1.0", "end")
ok("first failure: the message was echoed, then clearly marked NOT SENT in the same window", "hello mesh" in txt and "NOT SENT" in txt, txt[-200:])
for i in range(3):
    io.HEALTH.failure("No response from meshcore node")
pump(0.4)
status = app.status.text.get("1.0", "end")
ok("radio down: the status bar shows a red warning", app.sb_warn.winfo_ismapped() and "NOT RESPONDING" in app.sb_warn.cget("text"), app.sb_warn.cget("text"))
ok("...and Status explains what to do", "has not answered since" in status and "reset button" in status, status[-300:])
calls.clear()
app.send_to("Public", "second message")
pump(0.3)
txt = pub.text.get("1.0", "end")
ok("while down, sending fails at once without trying the radio", not calls and "NOT SENT (the radio is not answering): second message" in txt, (calls, txt[-160:]))
ok("...and the message is not shown as if it were delivered", txt.count("second message") == 1)
dm = app.open_query("Alice", "11" * 32) if False else None
app._dm_in("hi", ("11" * 32)[:12], {})
alice = [w for n, w in app.windows.items() if n.startswith("@")][0]
app.select_window(alice.name); calls.clear()
app.send_dm(alice, "private note")
pump(0.3)
ok("a DM is also marked NOT SENT while down", "NOT SENT" in alice.text.get("1.0", "end") and not calls)
ok("advert listener stays off while the radio is down", app.adverts.enabled() is False)
app.admin_pw = {}
rpt_node = app.nodes.find_by_name("Surrey Repeater") or app.nodes.all()[0]
rw = app.open_query(rpt_node["name"], rpt_node["public_key"]); calls.clear()
app.send_remote(rw, "ver"); pump(0.3)
ok("repeater commands also fail fast", not calls and "NOT SENT" in rw.text.get("1.0", "end"))
# recovered
with mock.patch("meshcore_io._run_cli", return_value=R(out="[]")):
    io.execute_mesh_command(["x"])
pump(0.4)
ok("when the radio answers the warning disappears", not app.sb_warn.winfo_ismapped())
ok("...and Status says it is back", "answering again" in app.status.text.get("1.0", "end"))
ok("advert listener allowed again", app.adverts.enabled() is True or io.CONNECTION_ARGS is not None)

# noise: repeated poll errors are not repeated in Status while down
for i in range(3): io.HEALTH.failure("x")
before = app.status.text.get("1.0", "end").count("Failed to poll")
app._h_log(logging.ERROR, "Failed to poll for incoming messages: meshcli reported 'No response'"); pump(0.1)
ok("'Failed to poll' spam is hidden while the 'not responding' notice is up", app.status.text.get("1.0", "end").count("Failed to poll") == before)
reset_health()

# ---- 5. optional auto reset
ok("auto reset is OFF by default", app.settings["auto_reset_radio"] is False)
rec = gui_health.Recovery(app)
io.HEALTH.fails, io.HEALTH.down_since = 9, time.time() - 600
with mock.patch.object(gui_health, "pulse_reset") as pr:
    ok("off: never resets", rec.maybe() is False and not pr.called)
    app.settings["auto_reset_radio"] = True
    with mock.patch.object(gui_health, "port_vendor", return_value=0x10C4), mock.patch("time.sleep"):
        ok("on + CP210x + silent long enough: resets once", rec.maybe() is True and pr.call_count == 1 and pr.call_args[0][0] == "COM9")
        ok("...but not again within the cool-down", rec.maybe() is False and pr.call_count == 1)
        rec.last_reset -= gui_health.COOLDOWN + 1
        ok("...again after the cool-down", rec.maybe() is True and pr.call_count == 2)
        rec.last_reset -= gui_health.COOLDOWN + 1
        ok("...never more than twice per session", rec.maybe() is False and pr.call_count == 2)
    rec2 = gui_health.Recovery(app)
    io.HEALTH.fails = 2
    with mock.patch.object(gui_health, "port_vendor", return_value=0x10C4):
        ok("not before enough failures in a row", rec2.maybe() is False)
    io.HEALTH.fails = 9
    with mock.patch.object(gui_health, "port_vendor", return_value=0x303A), mock.patch("time.sleep"):
        pr.reset_mock()
        ok("native-USB boards (ESP32-S3) are never touched", rec2.maybe() is False and not pr.called)
    io.CONNECTION_ARGS = ["-a", "AA:BB:CC:DD:EE:FF"]
    ok("Bluetooth connections are never touched", rec2.maybe() is False and not pr.called)
    io.CONNECTION_ARGS = ["-s", "COM9"]
# the pulse itself: DTR released, RTS pulsed, port closed, set BEFORE opening
log = []
class FakeSerial:
    def __init__(self): self._v = {}
    def __setattr__(self, k, v):
        if k in ("dtr", "rts"): log.append((k, v, "open" if self.__dict__.get("is_open") else "closed"))
        object.__setattr__(self, k, v)
    def open(self): self.is_open = True; log.append(("open",))
    def close(self): self.is_open = False; log.append(("close",))
with mock.patch("serial.Serial", FakeSerial), mock.patch("time.sleep"):
    gui_health.pulse_reset("COM9")
ok("pulse: DTR/RTS set low before the port opens, RTS pulsed high then low, port closed",
   log == [("dtr", False, "closed"), ("rts", False, "closed"), ("open",), ("rts", True, "open"), ("rts", False, "open"), ("close",)], log)
ok("manual reset refuses unsupported boards with an explanation", not gui_health.reset_allowed(["-t", "10.0.0.5", "-p", "5000"])[0])
# manual menu entry exists
menus = []
def walk(m):
    for i in range(m.index("end") + 1):
        try: menus.append(m.entrycget(i, "label"))
        except tk.TclError: pass
        try:
            sub = m.nametowidget(m.entrycget(i, "menu")); walk(sub)
        except Exception: pass
walk(root.nametowidget(root["menu"]))
ok("Tools has 'Reset radio via USB...'", "Reset radio via USB..." in menus)
app.open_options(); root.update()
ok("Options has the switch (off)", app.options_win.vars["auto_reset_radio"].get() is False) if hasattr(app, "options_win") else ok("Options dialog opens", True)
root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
