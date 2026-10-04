import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
import sys, os, time, threading, queue, tkinter as tk
BASE = ROOT
sys.path.insert(0, BASE); os.chdir(BASE)
import meshcore_io as io, gui_single, gui_nodecfg, mcIRC as g

results = []
def check(label, cond, detail=""):
    results.append(bool(cond)); print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))

# ================= single instance =================
gui_single.PORT = 47999
raised = []
lock = gui_single.acquire(lambda: raised.append(1))
check("first copy becomes the running instance", lock is not None)
check("second copy is refused", gui_single.acquire(lambda: None) is None)
check("second copy can ask the first to come forward", gui_single.notify_existing() is True)
time.sleep(0.3); check("...and the first copy is told to raise its window", raised == [1])
lock.close(); time.sleep(0.2)
check("nothing running -> notify finds nobody", gui_single.notify_existing() is False)
lock2 = gui_single.acquire(lambda: None); check("after the first exits, a new copy can start", lock2 is not None); lock2.close()
import socket as _s; stranger = _s.socket()
if os.name != "nt": stranger.setsockopt(_s.SOL_SOCKET, _s.SO_REUSEADDR, 1)      # (a connection from the checks above may still be in TIME_WAIT)
stranger.bind(("127.0.0.1", 47999)); stranger.listen(1)
check("an unrelated program on the port is not mistaken for mcIRC", gui_single.notify_existing() is False)
stranger.close()

# ================= USB detection =================
class P:
    def __init__(s, d, desc, vid): s.device, s.description, s.vid, s.pid, s.manufacturer = d, desc, vid, 1, ""
io.serial.tools.list_ports.comports = lambda: [P("COM97", "Silicon Labs CP210x", 0x10C4), P("COM98", "USB Serial Device", 0x303A)]
probes = []
def fake_probe(args, timeout=25, retries=1):
    probes.append((args[1], timeout, retries))
    return {"ok": True, "name": "N", "model": "M", "fw": "1", "max_contacts": 350} if args[1] == "COM97" else {"ok": False, "why": "not a companion"}
io.probe_device = fake_probe
check("remembered port is used immediately, no probing", io.auto_detect_usb_port(prefer="COM98") == ["-s", "COM98"] and probes == [])
check("remembered port that is no longer plugged in is ignored", io.auto_detect_usb_port(prefer="COM99") == ["-s", "COM97"] and probes[0][0] == "COM97")
probes.clear()
check("probes during detection are quick (12s, no retries)", io.auto_detect_usb_port() == ["-s", "COM97"] and probes == [("COM97", 12, 0)], str(probes))
probes.clear()
check("cancel before the first probe -> stops without probing", io.auto_detect_usb_port(should_stop=lambda: True) is None and probes == [])
io.probe_device = lambda a, timeout=25, retries=1: (probes.append(a[1]), {"ok": False, "why": "no"})[1]
probes.clear(); stops = iter([False, True, True])
check("cancel between probes stops the loop", io.auto_detect_usb_port(should_stop=lambda: next(stops)) is None and probes == ["COM97"], str(probes))
io.probe_device = fake_probe
check("build_connection_args passes the remembered port through", io.build_connection_args("usb", "auto", prefer_port="COM98") == ["-s", "COM98"])
check("an explicit port always wins", io.build_connection_args("usb", "COM97", prefer_port="COM98") == ["-s", "COM97"])

# ================= worker lifecycle (demo App, simulated radio) =================
root = tk.Tk(); app = g.App(root, demo=True)
def states():
    out = []
    while not app.q.empty():
        item = app.q.get_nowait(); out.append(item)
    return out
def kinds(items): return [i[0] if i[0] != "state" else "state:" + i[1] for i in items]

gate = threading.Event(); gate.set()
calls = []
def slow_build(*a, prefer_port="", should_stop=None):
    calls.append(prefer_port)
    t0 = time.time()
    while not gate.is_set() and time.time() - t0 < 5:    # a detection that takes a while
        if should_stop and should_stop(): return None
        time.sleep(0.05)
    return ["-s", "COM97"]
io.build_connection_args = slow_build
io.resolve_channel_indices = lambda *a, **k: True
io.fetch_incoming_messages = lambda: []
gui_nodecfg.read_node = lambda: {"info": {"name": "N"}, "ver": {}, "core": {}, "radio": {}}
app.settings["last_port"] = "COM97"; app.settings["poll_seconds"] = 1; app.settings["node_sync_minutes"] = 9999
app.settings["reboot_on_disconnect"] = False        # this test pretends COM97 is the node: never send a real reboot there
app.node_sync_worker = lambda: None

states()   # drop the demo's startup messages
app.worker.start(app.settings); time.sleep(0.6)
k = kinds(states())
check("normal connect: connecting -> connected -> remembers the port", k[0] == "state:connecting" and "state:connected" in k and "lastport" in k, str(k))
check("the remembered port was offered to detection", calls == ["COM97"])
app.worker.stop(); time.sleep(1.6)
check("disconnect after connecting -> stopped, thread ends", "state:stopped" in kinds(states()) and not app.worker.running)

# cancel while detection is still running
gate.clear(); app.worker.start(app.settings); time.sleep(0.4)
check("while connecting the worker is running", app.worker.running)
app.connected = False
app.status.write = lambda parts: texts.append("".join(t for t, _ in parts)); texts = []
app.connect(); check("clicking Connect again says it is already connecting", any("Already connecting" in t for t in texts), str(texts[-1:]))
texts.clear(); app.disconnect(); check("Disconnect during connecting says it is cancelling", any("Cancelling" in t for t in texts), str(texts[-1:]))
texts.clear(); app.connect()
waited = any("Still cancelling" in t for t in texts)
check("Connect while cancelling asks to wait (or, if the cancel already finished, simply connects)", waited or any("Connecting to the node" in t for t in texts), str(texts[-2:]))
if not waited: app.worker.stop()      # (a fast cancel finished before the click: the click started a new attempt - stop that one too)
time.sleep(0.8)
k = kinds(states())
check("cancelled attempt ends quickly without ever reporting 'connected'", "state:stopped" in k and "state:connected" not in k and not app.worker.running, str(k))
gate.set(); texts.clear(); app.connect(); time.sleep(0.8)
check("a new attempt works right after cancelling", "state:connected" in kinds(states()))
app.worker.stop(); time.sleep(1.6)

# the raise-window helper used by the single-instance guard
app.raise_window(); root.update()
check("raise_window runs without error", True)
root.destroy()
print("\nALL PASSED" if all(results) else f"\n{results.count(False)} FAILED of {len(results)}")
sys.exit(0 if all(results) else 1)
