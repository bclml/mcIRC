import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""Several nodes in one chat: an extra node (label '915') gets its own Status and channel windows, messages go to the right radio, private chats
reply through the node they came from, and addons only see the nodes ticked for them.  Pretend radios only."""
import json, time, tkinter as tk
from types import SimpleNamespace
from unittest import mock

import gui_multinode as gm
import meshcore_io as io
import mcIRC

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

ok("labels: 'Public [915]' <-> ('Public', '915')", gm.split_tag("Public [915]") == ("Public", "915") and gm.split_tag("#weather") == ("#weather", None) and gm.tag("Status", "915") == "Status [915]")
ok("connection arguments for USB / Wi-Fi / Bluetooth", gm.conn_args({"mode": "usb", "port": "COM10"}) == ["-s", "COM10"] and gm.conn_args({"mode": "tcp", "host": "10.0.0.5", "tcp_port": 5000}) == ["-t", "10.0.0.5", "-p", "5000"]
   and gm.conn_args({"mode": "ble", "ble": "MeshCore-ab"}) == ["-a", "MeshCore-ab"])

sent, polls = [], {"n": 0}
CHAN = json.dumps([{"type": "CHAN", "channel_idx": 1, "text": "Bob: hello from 915", "SNR": 6.5, "path_len": 1},
                   {"type": "PRIV", "pubkey_prefix": "abcdef123456", "text": "private on 915", "SNR": 4, "path_len": 0}])
def fake_exec(args, timeout=30, retries=2, retry_delay=2, lock=None, health=None):
    port = args[1]
    sent.append((port, args[2:], lock is io.MESH_LOCK or lock is None))
    out = ""
    if port == "COMX2":
        if args[2] == ".get_channels": out = json.dumps([{"channel_idx": 0, "channel_name": "Public"}, {"channel_idx": 1, "channel_name": "#weather"}])
        elif args[2] == ".infos": out = json.dumps({"name": "Node915", "radio_freq": 915.0})
        elif args[2] == ".sync_msgs":
            polls["n"] += 1
            out = CHAN if polls["n"] == 1 else "[]"
        elif args[2] == ".contacts": out = json.dumps({"abcdef123456" + "0" * 52: {"public_key": "abcdef123456" + "0" * 52, "adv_name": "Carol915", "type": 1}})
    return SimpleNamespace(stdout=out, stderr="", returncode=0)

root = tk.Tk()
app = mcIRC.App(root, demo=True); root.update()
app.settings["extra_nodes"] = [{"label": "915", "mode": "usb", "port": "COMX2", "enabled": True}]
got = []
class Probe:
    tick_seconds = 0
    title = "probe"
    def on_message(self, msg): got.append((msg.get("node"), msg["channel"]))
app.addons.loaded["probe"] = (Probe(), SimpleNamespace())

def pump(seconds):
    end = time.time() + seconds
    while time.time() < end:
        try:
            while True:
                item = app.q.get_nowait()
                getattr(app, "_h_" + item[0])(*item[1:])
        except Exception: pass
        root.update(); time.sleep(0.05)

with mock.patch.object(io, "execute_mesh_command", fake_exec), mock.patch.object(gm, "POLL_SECONDS", 0.2):
    app.start_extra_nodes()
    pump(2.5)
    n = app.extra_nodes["915"]
    ok("the extra node connects (its own channel list and name)", n.connected and n.channels == {"Public": 0, "#weather": 1} and n.info.get("name") == "Node915", (n.connected, n.channels))
    ok("it uses its own radio lock, not the main node's", all(not main_lock for port, _, main_lock in sent if port == "COMX2"))
    ok("Status [915], Public [915] and #weather [915] windows", all(x in app.windows for x in ("Status [915]", "Public [915]", "#weather [915]")), sorted(app.windows))
    ok("...grouped under the node in the tree", app.tree.exists("node:915") and app.tree.parent("#weather [915]") == "node:915" and app.tree.item("#weather [915]", "text") == "#weather")
    txt = app.windows["#weather [915]"].text.get("1.0", "end")
    ok("a channel message from the 915 node lands in '#weather [915]'", "hello from 915" in txt, txt[-200:])
    dm = next((w for nm, w in app.windows.items() if nm.startswith("@") and "private on 915" in w.text.get("1.0", "end")), None)
    ok("a private message from the 915 node opens a top-bar window that remembers its node", dm is not None and dm.node == "915", [nm for nm in app.windows if nm.startswith("@")])
    ok("the main node's channels are untouched", "Public" in app.windows and app.windows["Public"].node is None and "hello from 915" not in app.windows["Public"].text.get("1.0", "end"))
    ok("addons do not see the 915 node by default", got == [], got)
    sent.clear()
    app.bg = lambda fn, done: done(fn())
    app.send_to("#weather [915]", "hi 915")
    ok("typing in '#weather [915]' sends on the 915 radio, channel 1", ("COMX2", ["chan", "1", "hi 915"], False) in sent, sent)
    sent.clear()
    app.send_dm(dm, "reply")
    ok("replying in that private window goes out through the 915 radio", any(p == "COMX2" and a[0] == "msg" and a[2] == "reply" for p, a, _ in sent), sent)
    sent.clear()
    with mock.patch.object(io, "CONNECTION_ARGS", ["-s", "COMMAIN"]), mock.patch.object(io.HEALTH, "down_since", None):
        app.connected = True
        app.settings["watch_repeats"] = False
        app.send_to("Public", "hi main")
    ok("typing in plain 'Public' still goes to the main node", any(p == "COMMAIN" and "hi main" in a for p, a, _ in sent) and not any(p == "COMX2" for p, a, _ in sent), sent)
    app.settings.setdefault("addons", {}).setdefault("probe", {})["_nodes"] = ["main", "915"]
    polls["n"] = 0
    pump(1.0)
    ok("an addon ticked for the 915 node gets its messages (marked with the node)", ("915", "#weather [915]") in got, got)
    app.stop_extra_nodes(); pump(0.6)
    ok("Disconnect stops the extra node", not n.thread.is_alive(), n.thread.is_alive())
root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
