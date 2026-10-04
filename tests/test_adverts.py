import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
import json, os, subprocess, sys, tempfile, threading, time, textwrap, queue
sys.path.insert(0, ROOT)
import tkinter as tk
import meshcore_io as io
import gui_adverts as ga

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

# ---------------------------------------------------------------- connection argument mapping
ok("USB -> --serial", ga.helper_args(["-s", "COM4"]) == ["--serial", "COM4"])
ok("USB with baud", ga.helper_args(["-s", "COM4", "-b", "9600"]) == ["--serial", "COM4", "--baud", "9600"])
ok("TCP -> --tcp/--port", ga.helper_args(["-t", "10.0.0.5", "-p", "5000"]) == ["--tcp", "10.0.0.5", "--port", "5000"])
ok("Bluetooth is not supported (reconnects too slow)", ga.helper_args(["-a", "AA:BB:CC:DD:EE:FF"]) is None and ga.helper_args(None) is None)

# ---------------------------------------------------------------- the real helper script against a stand-in meshcore library
stub = tempfile.mkdtemp()
os.makedirs(os.path.join(stub, "meshcore"))
open(os.path.join(stub, "meshcore", "__init__.py"), "w").write(textwrap.dedent('''
    import asyncio, enum, sys
    class EventType(enum.Enum):
        CONTACTS = "contacts"; NEW_CONTACT = "new_contact"; ADVERTISEMENT = "advertisement"
    class Ev:
        def __init__(self, payload): self.payload = payload
    class Cmds:
        def __init__(self, mc): self.mc = mc
        async def get_contacts(self, lastmod=0):
            print("STUB get_contacts lastmod=%d" % lastmod, file=sys.stderr, flush=True)
            await self.mc.fire(EventType.CONTACTS, {"k1": {"public_key": "aa" * 32, "adv_name": "Catchup Node", "type": 2, "adv_lat": 49.1, "adv_lon": -123.1, "lastmod": 5}})
    class MeshCore:
        _lastmod = 0
        auto_update_contacts = False
        def __init__(self): self.subs = {}; self.commands = Cmds(self)
        @classmethod
        async def create_serial(cls, port, baud=115200):
            mc = cls(); asyncio.get_event_loop().call_later(0.4, lambda: asyncio.ensure_future(mc.later())); return mc
        @classmethod
        async def create_tcp(cls, host, port): return await cls.create_serial(host)
        def subscribe(self, et, cb): self.subs.setdefault(et, []).append(cb)
        async def fire(self, et, payload):
            for cb in self.subs.get(et, []): await cb(Ev(payload))
        async def later(self):
            await self.fire(EventType.ADVERTISEMENT, {"public_key": "bb" * 32})
            await self.fire(EventType.CONTACTS, {"k2": {"public_key": "bb" * 32, "adv_name": "Fresh Repeater", "type": 2, "adv_lat": 49.3, "adv_lon": -123.3, "lastmod": 9}})
            await self.fire(EventType.NEW_CONTACT, {"public_key": "cc" * 32, "adv_name": "Pending Guy", "type": 1})
        async def disconnect(self): print("STUB disconnect", file=sys.stderr, flush=True)
'''))
env = dict(os.environ, PYTHONPATH=stub, PYTHONUTF8="1")
def run_helper(lastmod):
    p = subprocess.run([sys.executable, ga.HELPER, "--serial", "COM9", "--lastmod", str(lastmod), "--seconds", "4"], capture_output=True, text=True, env=env, timeout=30)
    return [json.loads(l) for l in p.stdout.splitlines() if l.startswith("{")], p.stderr
ev, err = run_helper(100)
kinds = [e["event"] for e in ev]
ok("helper: catch-up contact, ready, advert, contact, new_contact", kinds == ["contact", "ready", "advert", "contact", "new_contact"], kinds)
ok("helper asks only for changes since lastmod and disconnects", "lastmod=100" in err and "STUB disconnect" in err, err)
ev0, err0 = run_helper(0)
ok("helper: with nothing known the first full load is silent", [e["event"] for e in ev0][0] == "ready" and "lastmod=0" in err0, [e["event"] for e in ev0])
ok("helper prints no message text fields", not any("text" in json.dumps(e) for e in ev))

# ---------------------------------------------------------------- AdvertWatcher with a fake helper (timing / preemption / failure)
import mcIRC
root = tk.Tk()
app = mcIRC.App(root, demo=True)
app.settings["advert_listen"] = True
w = app.adverts
io.CONNECTION_ARGS = ["-s", "COM9"]
fake = os.path.join(stub, "fake_helper.py")
open(fake, "w").write(textwrap.dedent('''
    import json, sys, time
    p = lambda **k: print(json.dumps(k), flush=True)
    time.sleep(0.3); p(event="ready"); time.sleep(0.4)
    p(event="advert", public_key="dd" * 32)
    p(event="contact", contact={"public_key": "dd" * 32, "adv_name": "Instant Node", "type": 2, "adv_lat": 49.2, "adv_lon": -123.2, "lastmod": 50})
    time.sleep(60)
'''))
ga.HELPER = fake
while not app.q.empty(): app.q.get_nowait()
stop = threading.Event()
t0 = time.time(); got = []
th = threading.Thread(target=lambda: w.listen(30, stop), daemon=True); th.start()
item = None
while time.time() - t0 < 8 and item is None:
    try:
        it = app.q.get(timeout=0.05)
        if it[0] == "advert": item = it
    except queue.Empty: pass
latency = time.time() - t0
ok("an advert reaches the app queue within ~2 s (instant, not at the next poll)", item and item[0] == "advert" and item[2]["adv_name"] == "Instant Node" and latency < 3, (item, latency))
# someone else needs the radio -> listener lets go quickly
t1 = time.time()
with io.MESH_LOCK:
    waited = time.time() - t1
ok("another user of the radio gets the lock quickly (listener stepped aside)", waited < 3, waited)
th.join(10)
ok("listener thread ended and process is gone", not th.is_alive() and w.proc is None)
ok("lock is free afterwards", io.MESH_LOCK.acquire(False) and (io.MESH_LOCK.release() or True))
# an ordinary (uncontended) hold must be fully released: another thread gets the lock straight away
def hold_once():
    with io.MESH_LOCK: pass
hold_once(); hold_once()
res = []
def other():
    got = io.MESH_LOCK.acquire(True, 2); res.append(got)
    if got: io.MESH_LOCK.release()
th2 = threading.Thread(target=other, daemon=True); th2.start(); th2.join(3)
ok("an uncontended with-block fully releases the lock (no leaked hold)", res == [True], res)
# lock still re-entrant like an RLock
with io.MESH_LOCK:
    with io.MESH_LOCK: pass
ok("MESH_LOCK stays re-entrant", True)

# failure handling: helper that cannot connect
open(fake, "w").write('import json; print(json.dumps({"event": "error", "message": "could not open port"}), flush=True)\n')
for i in range(3):
    t = time.time(); w.listen(2, threading.Event())
ok("after 3 failures listening switches itself off", w.disabled is True and w.failures >= 3)
t = time.time(); w.listen(1, threading.Event())
ok("then it just waits like before", 0.8 < time.time() - t < 2.5)
w.disabled = False; w.failures = 0

# turned off in Options / Bluetooth -> plain wait, nothing started
app.settings["advert_listen"] = False
t = time.time(); w.listen(1, threading.Event()); ok("setting off -> plain wait", w.proc is None and 0.8 < time.time() - t < 2.5)
app.settings["advert_listen"] = True
io.CONNECTION_ARGS = ["-a", "AA:BB:CC:DD:EE:FF"]
t = time.time(); w.listen(1, threading.Event()); ok("Bluetooth -> plain wait", w.proc is None and 0.8 < time.time() - t < 2.5)
io.CONNECTION_ARGS = None

# ---------------------------------------------------------------- GUI side
while not app.q.empty(): app.q.get_nowait()
app.settings["advert_notices"] = True
key = "ee" * 32
# a DM window that only knows the key prefix
app._dm_in("hi", key[:12], {"snr": 5, "hops": 1})
ok("setup: key-only window exists", "@" + key[:8] in app.windows, list(app.windows))
app._h_advert("contact", {"public_key": key, "adv_name": "Frenchie Cap", "type": 1, "adv_lat": 49.1, "adv_lon": -123.0, "last_advert": 7, "lastmod": 7})
ok("advert: node stored", app.nodes.find_by_prefix(key[:12])["name"] == "Frenchie Cap")
ok("advert: the key-only private window got its real name at once", "@Frenchie Cap" in app.windows and "@" + key[:8] not in app.windows, list(app.windows))
status = app.status.text.get("1.0", "end")
ok("first sighting announced in Status", "New companion heard: Frenchie Cap" in status, status[-200:])
app._h_advert("contact", {"public_key": key, "adv_name": "Frenchie Cap", "type": 1, "lastmod": 8})
ok("a repeat advert is not announced again", app.status.text.get("1.0", "end").count("New companion heard: Frenchie Cap") == 1)
app._h_advert("new_contact", {"public_key": "ff" * 32, "adv_name": "Waiting Node", "type": 2})
n = app.nodes.find_by_prefix("ff" * 6)
ok("manual-add advert remembered as not on the radio", n and n["on_radio"] == 0)
ok("...and announced as waiting for approval", "waiting for approval" in app.status.text.get("1.0", "end"))
app.settings["advert_notices"] = False
app._h_advert("contact", {"public_key": "12" * 32, "adv_name": "Quiet Node", "type": 2})
ok("notices can be switched off", "Quiet Node" not in app.status.text.get("1.0", "end") and app.nodes.find_by_prefix("12" * 6))
app.open_node_list(); root.update()
app._h_advert("contact", {"public_key": "34" * 32, "adv_name": "Listed Live", "type": 2}); root.update()
ok("open node list updates live", any("Listed Live" in str(app.nodes_win.t.item(i, "values")) for i in app.nodes_win.t.get_children()))
ok("max_lastmod works", app.nodes.max_lastmod() >= 0)
ok("Options has the new switches", "advert_listen" in app.settings and "advert_notices" in app.settings)
root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
