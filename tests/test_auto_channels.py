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
    def __init__(self, full=False, lists_empty=True, max_channels=6):
        self.slots = {0: "Public", 1: "#test", 2: "drivebc"}
        for i in range(3, 6): self.slots[i] = "x%d" % i if full else ""
        self.cmds, self.lists_empty, self.max = [], lists_empty, max_channels
    def run(self, args, **k):
        self.cmds.append(args[2:])
        if args[2] == ".get_channels":                  # real nodes list only the channels they have (lists_empty=False)
            rows = [{"channel_idx": i, "channel_name": n} for i, n in self.slots.items() if n or self.lists_empty]
            return type("R", (), {"stdout": json.dumps(rows), "stderr": "", "returncode": 0})
        if args[2] == ".ver":
            return type("R", (), {"stdout": json.dumps({"model": "Heltec V3", "max_channels": self.max}), "stderr": "", "returncode": 0})
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
real = Node(lists_empty=False, max_channels=40)
idx = with_node(real, lambda: io.ensure_channel("#drivebc2"))
ok("a real node lists only its channels: the first number it doesn't use is taken (it said 'no free slot' before)", idx == 3
   and ["set_channel", "3", "#drivebc2"] in real.cmds, real.cmds)
realfull = Node(full=True, lists_empty=False, max_channels=6)
ok("...and one with every channel in use is left alone", with_node(realfull, lambda: io.ensure_channel("#weather")) is None
   and not any(c[0] == "set_channel" for c in realfull.cmds), realfull.cmds)
ok("...and it is not asked again on every alert", with_node(full, lambda: (io._added_or_failed.add("weather"), io.ensure_channel("#weather"))[1]) is None)

# the Traffic, transit and weather addon: only while broadcasting
n3 = Node()
def resolve(muted):
    ea.TX["muted"] = muted
    with mock.patch.object(ea, "_channel_name_for_source", lambda s: "weather"):
        return ea._resolve_channel_idx("Weather Warning: Greater Calgary")
ok("Traffic, transit and weather, map only (not broadcasting): the node is left alone", with_node(n3, lambda: resolve(True)) is None and not any(c[0] == "set_channel" for c in n3.cmds))
ok("...broadcasting: the missing #weather is added and the alert goes there", with_node(n3, lambda: resolve(False)) == 3 and n3.slots[3] == "#weather")

# ---- every addon's channels: typed into its settings, switched on or after connecting - added to the node when it doesn't have them
import importlib.util
import gui_addons as ga
class API:
    def __init__(self, **values): self.values = values
    def get(self, key, default=None): return self.values.get(key, default)
def addon(pkg, **values):
    spec = importlib.util.spec_from_file_location("t_" + pkg, os.path.join(ROOT, "packages", pkg, pkg + ".py"))
    sys.path.insert(0, os.path.join(ROOT, "packages", pkg))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    inst = m.Addon.__new__(m.Addon); inst.api = API(**values)
    return inst
norm = lambda names: sorted({str(n).lstrip("#").lower() for n in names})
cases = [
    ("weather_bot", {"enabled": True, "channels": "#wx, #weather"}, ["weather", "wx"]),
    ("weather_bot", {"enabled": False, "channels": "#wx"}, []),
    ("fun_bot", {"enabled": True, "channels": {"joke": "#jokes", "dice": "#jokes, #games"}}, ["games", "jokes"]),
    ("mesh_bot", {"enabled": True, "channels": {"ping": "#pings"}, "greet_on": True, "greet_channels": "#hello"}, ["hello", "pings"]),
    ("channel_list", {"enabled": True, "where": "#lists"}, ["lists"]),
    ("bot_help", {"enabled": True, "announce": True, "announce_channels": "#help"}, ["help"]),
    ("auto_reply", {"enabled": True, "rules": [{"enabled": True, "listen": "#ask", "reply_to": "#answers, @Bob"},
                                               {"enabled": False, "listen": "#off"}]}, ["answers", "ask"]),
    ("area_alerts", {"enabled": True, "broadcast": True, "kinds": {"weather": True, "disasters": False}, "channels": {"weather": "#wx, #alerts2"}},
     ["alerts2", "wx"]),
    ("area_alerts", {"enabled": True, "broadcast": False, "kinds": {"weather": True}}, []),
]
for pkg, values, want in cases:
    got = norm(addon(pkg, **values).channels_used())
    ok(f"{pkg} {'(on)' if want else '(off / not broadcasting)'}: its channels are {want or 'none'}", got == want, got)
ea.TX["muted"], ea.CHANNEL_LISTS = False, {"DriveBC": ["drivebc", "roads"], "Weather": ["weather"]}
with mock.patch.dict(ea.TX["sources"], {"Weather": False}):
    ok("Traffic, transit and weather broadcasting: the switched-on alert types' channels", norm(addon("broadcast_alerts").channels_used()) == ["drivebc", "roads"])
ea.TX["muted"] = True
ok("...not broadcasting (map only): none", addon("broadcast_alerts").channels_used() == [])

class App:
    def __init__(self): self.connected, self.demo, self.lines, self.settings = True, False, [], {}
    def bg(self, fn, done):
        try: r = fn()
        except Exception as e: r = e
        done(r)
    def status_line(self, text, level="info"): self.lines.append((level, text))
    def save(self): pass
class Bot:
    def __init__(self, names): self.names = names
    def channels_used(self): return self.names
app = App(); mgr = ga.AddonManager(app)
mgr.loaded = {"a": (Bot(["#jokes", "all", "Public", "@Bob", "#test", "#weather [915]", "#bad name!"]), None), "b": (Bot(["JOKES", "#games"]), None)}
ok("the addons' channels, once each - not 'all', Public, private names, other nodes' or impossible names", sorted(mgr.channels_needed()) == ["#games", "#jokes", "#test"],
   mgr.channels_needed())
n4 = Node()
with_node(n4, mgr.ensure_channels)
ok("missing ones are added to the node (#jokes, #games); one it has (#test) is left alone", sorted(v for k, v in n4.slots.items() if k >= 3 and v) == ["#games", "#jokes"]
   and not any(c[:2] == ["set_channel", "1"] for c in n4.cmds), n4.slots)
app.connected = False; n5 = Node()
with_node(n5, mgr.ensure_channels)
ok("...not connected: nothing is asked", n5.cmds == [])
app.connected = True; full2 = Node(full=True); app.lines.clear()
with_node(full2, mgr.ensure_channels)
ok("...a full node: nothing overwritten, and Status says which channel couldn't be added and how to make room",
   all(v.startswith(("x", "#test", "drivebc", "Public")) for v in full2.slots.values()) and any("#jokes" in t and "free channel slot" in t for _, t in app.lines), app.lines)
added = []
with mock.patch.object(mgr, "load", lambda name: None), mock.patch.object(mgr, "unload", lambda name: None), \
        mock.patch.object(mgr, "ensure_channels", lambda: added.append(1)):
    mgr.set_enabled("a", True); mgr.set_enabled("a", False)
ok("switching an addon on adds its channels (switching off doesn't touch the node)", added == [1])
import gui_addonsettings
ok("saving an addon's settings adds its channels; so does connecting (after the node's channels are read)",
   "self.app.addons.ensure_channels()" in open(gui_addonsettings.__file__, encoding="utf-8").read()
   and open(os.path.join(ROOT, "mcIRC.py"), encoding="utf-8").read().count("self.addons.ensure_channels()") >= 2)       # (and right after connecting)

ea.TX["muted"] = True
io.ON_CHANNELS_ADDED = None
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
