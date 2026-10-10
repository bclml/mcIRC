import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""A channel an addon posts to that the node doesn't have is added to the node (as #name), instead of the message being dropped.
No radio: a stand-in node."""
import json
from unittest import mock

import meshcore_io as io
import emergency_agent as ea

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)


class Node:
    """Slots 0-5: Public, #test, drivebc (a private channel), then empty ones (or none free)."""
    def __init__(self, full=False):
        self.slots = {0: "Public", 1: "#test", 2: "drivebc"}
        for i in range(3, 6): self.slots[i] = "x%d" % i if full else ""
        self.cmds = []
    def run(self, args, **k):
        self.cmds.append(args[2:])
        if args[2] == ".get_channels":
            return type("R", (), {"stdout": json.dumps([{"channel_idx": i, "channel_name": n} for i, n in self.slots.items()]), "stderr": "", "returncode": 0})
        if args[2] == "set_channel": self.slots[int(args[3])] = args[4]
        return type("R", (), {"stdout": "", "stderr": "", "returncode": 0})
    def resolve(self, **k):
        io.CHANNEL_INDEX_BY_NAME.clear(); io.CHANNEL_INDEX_BY_NAME.update({n: i for i, n in self.slots.items() if n and i})
        return True

def with_node(node, fn):
    node.resolve(); io._added_or_failed.clear()
    with mock.patch.object(io, "CONNECTION_ARGS", ["-s", "COM9"]), mock.patch.object(io, "execute_mesh_command", node.run), \
            mock.patch.object(io, "resolve_channel_indices", node.resolve):
        return fn()

n = Node()
added = []
io.ON_CHANNELS_ADDED = lambda: added.append(True)
idx = with_node(n, lambda: io.ensure_channel("#weather"))
ok("a channel the node lacks is added as #name in the first free slot", idx == 3 and n.slots[3] == "#weather" and ["set_channel", "3", "#weather"] in n.cmds, n.cmds)
ok("...and the window list is told", added == [True])
n2 = Node()
ok("a channel the node has, with or without the #, is used as it is - never a second copy",
   with_node(n2, lambda: (io.ensure_channel("drivebc"), io.ensure_channel("#drivebc"), io.ensure_channel("test"))) == (2, 2, 1)
   and not any(c[0] == "set_channel" for c in n2.cmds), n2.cmds)
ok("Public is never added or touched", with_node(Node(), lambda: io.ensure_channel("Public")) is None)
full = Node(full=True)
ok("a full node: nothing is overwritten, the message is not sent", with_node(full, lambda: io.ensure_channel("#weather")) is None
   and not any(c[0] == "set_channel" for c in full.cmds), full.cmds)
ok("...and it is not asked again on every alert", with_node(full, lambda: (io._added_or_failed.add("weather"), io.ensure_channel("#weather"))[1]) is None)

# the Traffic, transit and weather addon: only while broadcasting
n3 = Node()
def resolve(muted):
    ea.TX["muted"] = muted
    with mock.patch.object(ea, "_channel_name_for_source", lambda s: "weather"):
        return ea._resolve_channel_idx("Weather Warning: Greater Calgary")
ok("Traffic, transit and weather, map only (not broadcasting): the node is left alone", with_node(n3, lambda: resolve(True)) is None and not any(c[0] == "set_channel" for c in n3.cmds))
ok("...broadcasting: the missing #weather is added and the alert goes there", with_node(n3, lambda: resolve(False)) == 3 and n3.slots[3] == "#weather")
ea.TX["muted"] = True
io.ON_CHANNELS_ADDED = None
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
