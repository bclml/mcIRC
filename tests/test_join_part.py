import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""/join and /part: channels are added to and removed from the node (the main one or an extra node).  A fake node, no radio."""
import json
import tkinter as tk
from types import SimpleNamespace
from unittest import mock

import meshcore_io as io
import gui_channels as gc
import mcIRC

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

ok("'#test' -> a hashtag channel (key from its name)", gc.parse_join("#test") == ("#test", "#test", None))
ok("'club <key>' -> a private channel with its key", gc.parse_join("club " + "AB" * 16) == ("#club", "club", "ab" * 16))
for bad in ("", "#bad name!", "#x " + "zz" * 16):
    try: gc.parse_join(bad); refused = False
    except ValueError: refused = True
    ok(f"refused with a hint: {bad!r}", refused)

class FakeNode:
    def __init__(self, names): self.slots = {i: n for i, n in enumerate(names)}; self.calls = []
    def run(self, args, *a, **k):
        cmd = [x for x in args if x not in ("-s", "COM4", "-t", "192.168.1.39", "-p", "5000")]
        self.calls.append(cmd)
        if cmd[0] == ".get_channels":
            out = json.dumps([{"channel_idx": i, "channel_name": self.slots.get(i, ""), "channel_secret": "00" * 16} for i in range(8)])
        elif cmd[0] == "set_channel": self.slots[int(cmd[1])] = cmd[2]; out = ""
        elif cmd[0] == "remove_channel": self.slots[int(cmd[1])] = ""; out = ""
        else: out = ""
        return SimpleNamespace(stdout=out, stderr="", returncode=0)

root = tk.Tk()
app = mcIRC.App(root, demo=True); root.update()
app.connected = True
io.CONNECTION_ARGS = ["-s", "COM4"]
def run_now(fn, done):
    try: r = fn()
    except Exception as e: r = e
    done(r)
app.bg = run_now
lines = []
app.status_line = lambda text, level="info", **k: lines.append((level, text))
node = FakeNode(["Public", "", "drivebc", "weather"])
io.CHANNEL_INDEX_BY_NAME.clear(); io.CHANNEL_INDEX_BY_NAME.update({"Public": 0, "drivebc": 2, "weather": 3})
with mock.patch.object(io, "execute_mesh_command", node.run):
    app.command("join #test")
    ok("/join #test adds it to the node in the first free slot (a hashtag channel)", node.slots[1] == "#test" and ["set_channel", "1", "#test"] in node.calls, node.calls)
    ok("...its window opens and is in front", app.current is not None and app.current.name == "#test")
    ok("...and the bot's channel map knows it", io.CHANNEL_INDEX_BY_NAME.get("#test") == 1, io.CHANNEL_INDEX_BY_NAME)
    node.calls.clear(); app.command("join #weather")
    ok("/join of a channel already on the node just switches to it", not any(c[0] == "set_channel" for c in node.calls) and app.current.name == "#weather")
    node.calls.clear(); app.command("join #club " + "ab" * 16)
    ok("/join #name <key> adds a private channel with that key", ["set_channel", "4", "club", "ab" * 16] in node.calls, node.calls)
    for i in range(5, 8): node.slots[i] = f"x{i}"
    lines.clear(); app.command("join #more")
    ok("a full node: says so, nothing changed", any("no free channel slot" in t for _, t in lines) and "#more" not in node.slots.values(), lines)
    with mock.patch.object(gc.messagebox, "askyesno", lambda *a, **k: True):
        app.select_window("#test"); app.command("part")
    ok("/part removes the channel from the node and closes its window", node.slots[1] == "" and "#test" not in app.windows and ["remove_channel", "1"] in node.calls)
    lines.clear(); app.part_channel("Public", ask=False)
    ok("Public can't be removed", any("Public can't be removed" in t for _, t in lines) and node.slots[0] == "Public")
    with mock.patch.object(gc.messagebox, "askyesno", lambda *a, **k: False):
        node.calls.clear(); app.part_channel("#weather")
    ok("answering No keeps it", not any(c[0] == "remove_channel" for c in node.calls) and node.slots[3] == "weather")

# an extra node's windows work on that node
extra = FakeNode(["Public", "", "", "", "", "", "", ""])
n = SimpleNamespace(args=["-t", "192.168.1.39", "-p", "5000"], lock=io._MeshLock(), health=io.RadioHealth(), channels={"Public": 0}, connected=True, info={})
app.extra_nodes["wifi 1"] = n
app.settings["extra_nodes"] = [{"label": "wifi 1", "mode": "tcp", "host": "192.168.1.39", "tcp_port": 5000, "enabled": True}]
app.node_window("wifi 1"); w = app.add_window("Public [wifi 1]", "x"); w.node = "wifi 1"
app.select_window("Public [wifi 1]")
with mock.patch.object(io, "execute_mesh_command", extra.run), mock.patch.object(io, "channel_map", lambda args, lock=None, health=None, retries=1: {v: k for k, v in extra.slots.items() if v}):
    app.command("join #lse-bot")
ok("/join in an extra node's window adds the channel to THAT node", extra.slots[1] == "#lse-bot" and node.slots[1] == "", (extra.slots, node.slots))
ok("...and opens '#lse-bot [wifi 1]'", "#lse-bot [wifi 1]" in app.windows and app.current.name == "#lse-bot [wifi 1]")
root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
