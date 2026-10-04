import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""A direct message to a person the radio lost puts just that contact back (fake radio), and a map that does not blink when nothing changed."""
import tempfile, time, tkinter as tk
from types import SimpleNamespace
from unittest import mock

import gui_nodes as gn
import meshcore_io as ea

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

# ---- restore_to_radio against a fake radio
tmp = tempfile.mkdtemp()
store = gn.NodeStore(os.path.join(tmp, "nodes.db"))
KEYS = [f"{i:02x}" * 32 for i in range(1, 9)]
old = int(time.time()) - 5 * 86400
contacts = {k: {"public_key": k, "adv_name": f"Node {i}", "type": 2 if i % 2 else 1, "adv_lat": 49.0 + i / 100, "adv_lon": -123.0, "last_advert": old, "lastmod": old} for i, k in enumerate(KEYS)}
contacts[KEYS[3]]["adv_name"] = "-dash name"
store.update_from_radio(contacts, now=old)
radio = {KEYS[0]: contacts[KEYS[0]], KEYS[1]: contacts[KEYS[1]]}           # the radio was cleared; two nodes came back by themselves
calls = []

def fake_exec(args, timeout=90, retries=1):
    calls.append(list(args))
    i = 0
    while i < len(args):
        if args[i] == "add_contact":
            k = args[i + 1]
            radio[k] = {"public_key": k, "adv_name": args[i + 3], "type": int(args[i + 2]), "adv_lat": 0, "adv_lon": 0, "last_advert": 0, "lastmod": int(time.time())}
            i += 3
        i += 1
    return SimpleNamespace(stdout="", stderr="", returncode=0)

with mock.patch.object(ea, "execute_mesh_command", fake_exec), mock.patch.object(ea, "CONNECTION_ARGS", ["-s", "COMX"]):
    n = gn.add_to_radio([store.find_by_prefix(KEYS[2])])
ok("one remembered node is put back on the radio", n == 1 and KEYS[2] in radio and len(calls) == 1)
ok("...with add_contact (key, type, name) and its path reset", calls[0][2:6] == ["add_contact", KEYS[2], "1", "Node 2"] and calls[0][6:8] == ["reset_path", KEYS[2]], calls[0])
calls.clear()
with mock.patch.object(ea, "execute_mesh_command", fake_exec), mock.patch.object(ea, "CONNECTION_ARGS", ["-s", "COMX"]):
    gn.add_to_radio([store.find_by_prefix(KEYS[3])])
ok("a name that starts with '-' is replaced (meshcli would read it as an option)", not any(a == "-dash name" for c in calls for a in c))
ok("there is no bulk 'put everything back' any more", not hasattr(gn, "restore_to_radio"))

# ---- a direct message to a person the radio lost: put the contact back, then send again
import mcIRC
root = tk.Tk()
app = mcIRC.App(root, demo=True); root.update()
app.connected = True
sent_cmds = []
def fake_exec2(args, timeout=90, retries=1):
    sent_cmds.append(list(args))
    if "msg" in args and not any(a == "add_contact" for c in sent_cmds[:-1] for a in c):
        return SimpleNamespace(stdout="", stderr="Error sending message: Event(type=<EventType.ERROR: 'command_error'>, payload={'code_string': 'ERR_CODE_NOT_FOUND'})", returncode=1)
    return SimpleNamespace(stdout="", stderr="INFO:meshcore:Connected to X", returncode=0)
app.nodes = store
unsent = []
w = app.add_window("@Node 2", "dm"); w.key = KEYS[2]
with mock.patch.object(ea, "execute_mesh_command", fake_exec2), mock.patch.object(ea, "CONNECTION_ARGS", ["-s", "COMX"]), \
        mock.patch.object(app, "unsent", lambda *a: unsent.append(a)), mock.patch.object(app, "bg", lambda fn, done: done((lambda: (fn(), None)[1])() if True else None)):
    app.send_dm(w, "hello")
msgs = [c for c in sent_cmds if "msg" in c]
ok("an unknown contact is added from memory and the message is sent a second time", len(msgs) == 2 and any("add_contact" in c for c in sent_cmds) and not unsent, (len(msgs), unsent))

# ---- the map keeps its markers when nothing changed
import gui_map
if gui_map.tkintermapview:
    app.nodes = gn.NodeStore(os.path.join(tmp, "map.db"))
    app.nodes.update_from_radio({k: contacts[k] for k in KEYS[:4]}, now=int(time.time()))
    app.open_map(); root.update()
    mw = app.map_win; mw.refresh(force=True); root.update()
    before = list(mw.markers)
    ok("the map shows the positioned nodes", len(before) >= 4, len(before))
    mw.refresh(force=True); root.update()
    ok("a forced refresh with nothing changed keeps the very same markers (no blinking)", mw.markers == before and all(m in before for m in mw.markers))
    app.nodes.touch_contact(dict(contacts[KEYS[0]]), now=int(time.time()) + 90); mw.refresh(); root.update()
    ok("'seen N min ago' changing does not redraw anything", mw.markers == before)
    app.nodes.touch_contact(dict(contacts[KEYS[0]], adv_lat=49.5), now=int(time.time()) + 90); mw.refresh(); root.update()
    ok("a node that moved replaces only its own marker", len(mw.markers) == len(before) and sum(a is b for a, b in zip(mw.markers, before)) == len(before) - 1)
    for _ in range(5): mw.request_refresh()
    ok("a burst of refresh requests becomes one", mw._soon is not None)
else:
    print("[SKIP] map checks need tkintermapview")

root.destroy()
print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
