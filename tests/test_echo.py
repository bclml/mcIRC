import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""Heard repeats: our channel message coming back from repeaters is counted and noted on the line; no repeat -> sent once more.
A stand-in helper replaces the real radio; no port is opened."""
import tempfile, threading, time, tkinter as tk
from unittest import mock

import gui_echo
import gui_echo_proc
import meshcore_io as io

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

# ---- recognising our own message among what the radio hears
mine = {"payload_type": 5, "message": "mcIRC_bot: hello mesh", "sender_timestamp": 1000, "path": "a1b2"}
ok("our message coming back is recognised", gui_echo_proc.is_our_echo(mine, "mcIRC_bot", "hello mesh", {1000}))
ok("...not someone else's", not gui_echo_proc.is_our_echo(dict(mine, message="Bob: hello mesh"), "mcIRC_bot", "hello mesh", {1000}))
ok("...not an older copy of the same words (other timestamp)", not gui_echo_proc.is_our_echo(mine, "mcIRC_bot", "hello mesh", {999}))
ok("...not an advert or other packet", not gui_echo_proc.is_our_echo(dict(mine, payload_type=4), "mcIRC_bot", "hello mesh", {1000}))
ok("...not a channel we cannot read", not gui_echo_proc.is_our_echo({"payload_type": 5, "sender_timestamp": 1000}, "mcIRC_bot", "hello mesh", {1000}))
ok("notes: 2 repeats", gui_echo.describe({"sent": True, "repeats": 2}) == "heard 2 repeats")
ok("notes: none heard, sent again", gui_echo.describe({"sent": True, "repeats": 0, "resent": True}) == "no repeat heard, sent again")
ok("notes: none heard", gui_echo.describe({"sent": True, "repeats": 0}) == "no repeat heard")
ok("notes: watch stopped early -> say nothing", gui_echo.describe({"sent": True, "repeats": 0, "interrupted": True}) == "")
ok("Bluetooth is not supported (normal send)", not gui_echo.supported(["-a", "AA:BB"]) and gui_echo.supported(["-s", "COMX"]))

# ---- send_watched with a stand-in helper process
tmp = tempfile.mkdtemp()
def fake_helper(lines, sleep=0.0):
    p = os.path.join(tmp, f"fake_{len(os.listdir(tmp))}.py")
    open(p, "w").write("import time, json, sys\n" + "".join(f"print(json.dumps({l!r}), flush=True); time.sleep({sleep})\n" for l in lines))
    return p
with mock.patch.object(gui_echo, "HELPER", fake_helper([{"event": "sent", "timestamp": 1}, {"event": "repeat", "path": "a1"}, {"event": "repeat", "path": "c3d4"},
                                                         {"event": "done", "repeats": 2, "resent": False}])):
    seen = []
    r = gui_echo.send_watched(["-s", "COMX"], 7, "hi", seconds=1, on_event=seen.append)
ok("two repeats counted", r["sent"] and r["repeats"] == 2 and not r["resent"], r)
ok("each repeat is reported as it happens (with its path)", [e.get("path") for e in seen if e["event"] == "repeat"] == ["a1", "c3d4"])
with mock.patch.object(gui_echo, "HELPER", fake_helper([{"event": "error", "message": "could not connect", "sent": False}])):
    r = gui_echo.send_watched(["-s", "COMX"], 7, "hi", seconds=1)
ok("helper could not connect -> nothing sent (the caller sends the usual way)", not r["sent"] and "connect" in r["error"], r)
with mock.patch.object(gui_echo, "HELPER", fake_helper([{"event": "sent", "timestamp": 1}] + [{"event": "tick"}] * 40, sleep=0.1)):
    res = {}
    t = threading.Thread(target=lambda: res.update(gui_echo.send_watched(["-s", "COMX"], 7, "hi", seconds=5)))
    t.start(); time.sleep(1.0)
    t0 = time.time()
    with io.MESH_LOCK: waited = time.time() - t0            # somebody else needs the radio
    t.join(5)
ok("anyone who needs the radio stops the watch at once", waited < 2.5 and res.get("interrupted") and res.get("sent"), (round(waited, 2), res))
ok("...and the lock's normal listener-yield hook is back afterwards", io.MESH_LOCK.on_contend is None or "contend" not in getattr(io.MESH_LOCK.on_contend, "__name__", ""))

# ---- in the window: the note lands on the right line
import mcIRC
root = tk.Tk()
app = mcIRC.App(root, demo=True); root.update()
w = app.windows["Public"]
mark = app.chat_line(w, app.settings["node_name"], "hello mesh", "self")
app.chat_line(w, "Bob", "a later line", "text")
w.add_note(mark, "(heard 2 repeats)")
lines = w.text.get("1.0", "end").splitlines()
mine_line = next(l for l in lines if "hello mesh" in l)
ok("the note is added to the end of our line, not a later one", mine_line.endswith("hello mesh  (heard 2 repeats)") and not any("a later line" in l and "repeats" in l for l in lines), mine_line)
app.connected = True
ran = []
with mock.patch.object(gui_echo, "send_watched", lambda args, idx, text, resend=True, on_event=None, **k: (on_event and on_event({"event": "repeat", "path": "a1b2"}), ran.append((idx, text, resend)), {"sent": True, "repeats": 1, "resent": False, "interrupted": False, "error": ""})[-1]), \
        mock.patch.object(io, "CONNECTION_ARGS", ["-s", "COMX"]), mock.patch.object(io, "channel_index", lambda n: 7, create=True), \
        mock.patch.object(mcIRC, "channel_index", lambda n: 7), mock.patch.object(app, "bg", lambda fn, done: done(fn())):
    app.send_to("#weather" if "#weather" in app.windows else "Public", "test 123"); root.update()
ok("sending to a channel goes through the repeat watch", ran and ran[0][1] == "test 123" and ran[0][2] is True, ran)
while not app.q.empty():
    item = app.q.get_nowait()
    if item[0] == "call": item[1]()
ok("a repeat's path is kept for the map's signal view", app.signal_traces and app.signal_traces[-1]["path"] == "a1b2" and app.signal_traces[-1]["dir"] == "out", app.signal_traces)
app.settings["watch_repeats"] = False; ran.clear()
with mock.patch.object(gui_echo, "send_watched", lambda *a, **k: ran.append(1)), mock.patch.object(io, "execute_mesh_command", lambda *a, **k: ran.append("plain")), \
        mock.patch.object(io, "CONNECTION_ARGS", ["-s", "COMX"]), mock.patch.object(mcIRC, "channel_index", lambda n: 7), mock.patch.object(app, "bg", lambda fn, done: done(fn())):
    app.send_to("Public", "plain send")
ok("switched off -> the normal send", ran == ["plain"], ran)
root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
