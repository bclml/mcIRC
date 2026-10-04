import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
import os; os.environ["MCIRC_NO_LOG_FILE"] = "1"
import sys, time, threading, tempfile, subprocess, json, logging
from unittest import mock
BASE = ROOT
sys.path.insert(0, BASE); os.chdir(BASE)
import tkinter as tk
import meshcore_io as io, gui_nodecfg, mcIRC as g

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

def alive(pid):
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
    return str(pid) in out

# ---- 1. a REAL slow process tree (launcher -> python, like meshcli.exe) is killed by cancel_running(), including the child
tmp = tempfile.mkdtemp()
child_pid_file = os.path.join(tmp, "child.pid")
child_py = os.path.join(tmp, "child.py")
open(child_py, "w").write(f"import os, time\nopen(r'{child_pid_file}', 'w').write(str(os.getpid()))\ntime.sleep(40)\n")
launcher = os.path.join(tmp, "fake_meshcli.cmd")
open(launcher, "w").write(f'@echo off\r\n"{sys.executable}" "{child_py}"\r\n')
io.DEFAULT_CLI_PATH = launcher
io.HEALTH.fails, io.HEALTH.down_since = 0, None
result = {}
def run():
    t0 = time.time()
    try: io.execute_mesh_command(["-s", "COMX", "x"], retries=2)
    except BaseException as e: result["exc"] = e
    result["took"] = time.time() - t0
th = threading.Thread(target=run, daemon=True); th.start()
deadline = time.time() + 15
while not os.path.exists(child_pid_file) and time.time() < deadline: time.sleep(0.1)
time.sleep(0.3)
child_pid = int(open(child_pid_file).read())
ok("the slow fake radio command is running (child process alive)", alive(child_pid))
t0 = time.time(); io.cancel_running(); th.join(10)
ok("cancel_running() ends the command within about a second", not th.is_alive() and time.time() - t0 < 3, time.time() - t0)
ok("...as 'Cancelled' (not a radio failure)", isinstance(result.get("exc"), io.Cancelled), result.get("exc"))
time.sleep(0.5)
ok("...and the child python process holding the port is dead too (whole tree killed)", not alive(child_pid))
ok("nothing is left registered as running", not io._RUNNING)
ok("a cancelled command does not count against the radio's health", io.HEALTH.fails == 0 and not io.HEALTH.is_down)
# retries do not start after a cancel, and later commands work normally
open(launcher, "w").write('@echo off\r\necho []\r\n')
t0 = time.time()
r = io.execute_mesh_command(["x"], retries=0)
ok("commands started after the cancel run normally", r.stdout.strip() == "[]" or "[]" in r.stdout, r.stdout)

# a command that times out leaves no orphan either
open(launcher, "w").write(f'@echo off\r\n"{sys.executable}" "{child_py}"\r\n')
os.remove(child_pid_file)
try: io.execute_mesh_command(["x"], timeout=2, retries=0)
except RuntimeError: pass
time.sleep(0.5)
pid2 = int(open(child_pid_file).read())
ok("a timed-out command also kills the child process (the port is freed)", not alive(pid2))
io.HEALTH.fails, io.HEALTH.down_since = 0, None

# ---- 2. the connect thread with a node that does not answer, then one that does
root = tk.Tk(); app = g.App(root, demo=True)
def drain():
    out = []
    while not app.q.empty(): out.append(app.q.get_nowait())
    return out
def kinds(items): return [i[0] if i[0] != "state" else "state:" + i[1] for i in items]

answers = {"n": 0, "answer_after": 10**9}
def fake_run_cli(cmd, timeout=30, gen=None):
    gen = io._CANCEL_GEN[0] if gen is None else gen
    answers["n"] += 1
    end = time.time() + 0.4
    while time.time() < end:                       # a command that takes a moment and notices cancel_running() like the real thing
        if io._CANCEL_GEN[0] != gen: raise io.Cancelled("cancelled")
        time.sleep(0.05)
    if io._CANCEL_GEN[0] != gen: raise io.Cancelled("cancelled")
    if answers["n"] > answers["answer_after"]:
        body = json.dumps([{"channel_idx": 0, "channel_name": "Public"}, {"channel_idx": 3, "channel_name": "drivebc"}])
        return subprocess.CompletedProcess(cmd, 0, body, "")
    return subprocess.CompletedProcess(cmd, 0, "", "No response from meshcore node, disconnecting")
io.DEFAULT_CLI_PATH = "meshcli"
io.build_connection_args = lambda *a, **k: ["-s", "COMX"]
io.fetch_incoming_messages = lambda: []
gui_nodecfg.read_node = lambda: {"info": {"name": "N"}, "ver": {}, "core": {}, "radio": {}}
app.settings["poll_seconds"] = 1; app.settings["node_sync_minutes"] = 9999; app.settings["auto_reset_radio"] = False
app.node_sync_worker = lambda: None
logs = []
logging.getLogger().setLevel(logging.INFO)      # (on a machine without installed addons nothing else sets it)
class H(logging.Handler):
    def emit(self, r): logs.append(r.getMessage())
logging.getLogger().addHandler(H())
drain()
with mock.patch.object(io, "_run_cli", fake_run_cli):
    app.worker.start(app.settings); time.sleep(4.0)
    k = kinds(drain())
    ok("silent node: stays 'connecting' and never claims to be connected", "state:connecting" in k and "state:connected" not in k, k)
    ok("...and tells the user once what to do", sum("not answering yet" in m for m in logs) == 1 and any("reset button" in m for m in logs), [m for m in logs if "answering" in m])
    t0 = time.time(); app.disconnect()
    while app.worker.running and time.time() - t0 < 10: time.sleep(0.05)
    took = time.time() - t0
    ok("Disconnect stops the attempt within about a second (was minutes)", not app.worker.running and took < 2.0, took)
    k = kinds(drain())
    ok("...ending in 'stopped', no connected state, no error line about the cancel", "state:stopped" in k and "state:connected" not in k and not any("Connection ended" in m for m in logs), (k, [m for m in logs if "ended" in m]))

    # a node that comes back after a few failed attempts
    answers.update(n=0, answer_after=7); logs.clear()
    with mock.patch.object(io, "_nap", lambda *a, **k: None):
        app.worker.stop_evt.clear(); app.worker.start(app.settings)
        end = time.time() + 20
        while time.time() < end and "state:connected" not in kinds(list(app.q.queue)): time.sleep(0.1)
    k = kinds(drain())
    ok("when the node starts answering, the connection completes", "state:connected" in k and "channels" in k, k)
    ok("...and says so", any("answering now" in m for m in logs), logs[-3:])
    # closing the window with the connection running: everything is cancelled and the process can exit
    calls = []
    with mock.patch.object(io, "cancel_running", wraps=io.cancel_running) as cr, mock.patch.object(app.adverts, "interrupt", wraps=app.adverts.interrupt) as ai:
        t0 = time.time(); app.quit()
        ok("closing the window cancels radio commands and stops the advert listener", cr.called and ai.called)
    ok("...and the worker thread ends promptly", time.time() - t0 < 3)
    time.sleep(1.0)
    ok("worker thread is gone after quit", not app.worker.running)
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
