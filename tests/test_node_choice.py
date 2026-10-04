import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""Settings pages and MeshCore tools can work on any node (the main one or one from More nodes).  No radio."""
import tkinter as tk
from types import SimpleNamespace
from unittest import mock

sys.path[:0] = [os.path.join(ROOT, "packages", "node_tools")]
import meshcore_io as io

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

ran = []
class Lock(io._MeshLock):
    def __init__(self, name): super().__init__(); self.name = name
    def acquire(self, *a, **k): ran.append(("lock", self.name)); return super().acquire(*a, **k)
def fake_cli(cmd, timeout=30, gen=None):
    ran.append(("cmd", cmd[len(io.cli_cmd()):]))
    return SimpleNamespace(returncode=0, stdout='{"name": "x", "tx_power": 22, "radio_freq": 910.525}', stderr="")

io.CONNECTION_ARGS = ["-s", "COM4"]
io.MESH_LOCK = main_lock = Lock("main")
wifi_lock = Lock("wifi")
with mock.patch.object(io, "_run_cli", fake_cli):
    io.execute_mesh_command(io.CONNECTION_ARGS + ["infos"], retries=0)
    ok("without a chosen node, commands go to the main node", ran[-1] == ("cmd", ["-s", "COM4", "infos"]) and ("lock", "main") in ran, ran)
    ran.clear()
    with io.on_node(["-t", "192.168.1.39", "-p", "5000"], wifi_lock):
        io.execute_mesh_command(io.CONNECTION_ARGS + ["infos"], retries=0)
        ok("inside on_node the main node's prefix becomes the chosen node's", ran[-1] == ("cmd", ["-t", "192.168.1.39", "-p", "5000", "infos"]), ran)
        ok("...and that node's own lock is used (not the main node's)", ("lock", "wifi") in ran and ("lock", "main") not in ran, ran)
        import gui_nodecfg
        ran.clear()
        gui_nodecfg.read_node()
        ok("Options > Node pages read the chosen node", ran[-1][1][:4] == ["-t", "192.168.1.39", "-p", "5000"], ran)
        import ntools_common
        ran.clear()
        ntools_common.run("clock")
        ok("the MeshCore tools talk to the chosen node", ran[-1] == ("cmd", ["-t", "192.168.1.39", "-p", "5000", "clock"]), ran)
    ran.clear()
    io.execute_mesh_command(io.CONNECTION_ARGS + ["infos"], retries=0)
    ok("after on_node, the main node again", ran[-1] == ("cmd", ["-s", "COM4", "infos"]), ran)
io.MESH_LOCK = io._MeshLock()

import mcIRC
from gui_addons import AddonAPI
root = tk.Tk()
app = mcIRC.App(root, demo=True); root.update()
app.settings["extra_nodes"] = [{"label": "wifi 1", "mode": "tcp", "host": "192.168.1.39", "tcp_port": 5000, "enabled": True}]
ch = app.node_choices()
ok("the node list: the main node first, then More nodes", [k for k, _ in ch] == ["main", "wifi 1"], ch)
with app.node_target("wifi 1"): args = io.node_args()
ok("a node from More nodes is reached by its label", args == ["-t", "192.168.1.39", "-p", "5000"], args)
with app.node_target("main"): args = io.node_args()
ok("'main' is the main node", args == io.CONNECTION_ARGS, args)

import ntools_common
api = AddonAPI(app, "node_tools")
app.bg = lambda fn, done: done(fn())
w = ntools_common.ToolWindow(api, "test")
ok("tool windows show a Node: list", [t for t in w.node_box["values"]] == [t for _, t in ch])
w.node_var.set(ch[1][1]); changed = []
w.on_node_change = lambda: changed.append(w.node_key)
w._node_picked()
ok("choosing a node switches the tool to it", w.node_key == "wifi 1" and changed == ["wifi 1"])
got = []
w.job("t", io.node_args, got.append)
ok("a tool refuses a node that is not connected", got == [] and "not connected" in w.status["text"], w.status["text"])
with mock.patch.object(app, "node_ready", lambda key: True):
    w.job("t", io.node_args, got.append)
ok("a tool's job runs on the chosen node", got == [["-t", "192.168.1.39", "-p", "5000"]], got)
w.destroy()

app.node_window("wifi"); app.add_window("Public [wifi]", "x"); app.node_window("wifi 1")
ok("a node's windows are grouped under 'Node <label>'", app.tree.exists("node:wifi") and "Status [wifi]" in app.windows)
logs = [w.log.path for n, w in app.windows.items() if n.endswith("[wifi]") and w.log]
app.remove_node("wifi", ask=False)
ok("Remove node: its windows and its group are gone", not app.tree.exists("node:wifi") and not any(n.endswith("[wifi]") for n in app.windows))
ok("...the other node is untouched", app.tree.exists("node:wifi 1") and "Status [wifi 1]" in app.windows)
ok("...their logs are kept but no longer reopen at start", all(not os.path.exists(p) for p in logs))
app.remove_node("wifi 1", ask=False)
ok("Remove node also takes it out of More nodes", app.settings["extra_nodes"] == [] and not app.tree.exists("node:wifi 1"))

import gui_dialogs
app.settings["extra_nodes"] = [{"label": "wifi 1", "mode": "tcp", "host": "192.168.1.39", "tcp_port": 5000, "enabled": True}]
dlg = gui_dialogs.OptionsDialog(app); root.update()
rows = [dlg.more_nodes.t.item(i, "values")[0] for i in dlg.more_nodes.t.get_children()]
ok("More nodes lists every node: the main (USB) one first, then the others", rows == ["main", "wifi 1"], rows)
ok("...and saving the page keeps only the extra nodes in More nodes", [c["label"] for c in dlg.more_nodes.items()] == ["wifi 1"])
dlg.more_nodes.t.selection_set("main"); dlg.more_nodes.edit(); root.update()
ok("Edit on the main node opens the Connect page", dlg.tree.selection() == ("Connect",), dlg.tree.selection())
dlg.more_nodes.t.selection_set("main"); dlg.more_nodes.radio(); root.update()
ok("Radio settings on the main node opens 'Node: radio' for the main node", dlg.tree.selection() == ("Node: radio",) and dlg.node_pages.node_key == "main")
with mock.patch("gui_multinode_ui.messagebox.showinfo", lambda *a, **k: None):
    dlg.more_nodes.t.selection_set("main"); dlg.more_nodes.remove()
ok("the main node can't be removed or switched off here", [c["label"] for c in dlg.more_nodes.items()] == ["wifi 1"])
dlg.destroy()

import gui_multinode_ui as mu
ok("node labels may have spaces inside ('wifi 1'), not around", bool(mu.LABEL_RE.fullmatch("wifi 1")) and not mu.LABEL_RE.fullmatch(" wifi") and not mu.LABEL_RE.fullmatch("wifi "))
root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
