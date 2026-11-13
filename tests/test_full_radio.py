import os as _os; _os.environ["MCIRC_NO_LOG_FILE"] = "1"      # tests must never write to the bot's real log
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
"""A private message to someone the radio lost, when the radio's contact list is full: the longest-unheard companion (never a favorite,
a repeater or a room server) is taken off to make room, the person is added back and the message goes out - on the main node and on
an extra node.  A fake radio that holds 4 contacts, like a real one holding 350.  No radio."""
import json, tempfile, time, tkinter as tk
from types import SimpleNamespace
from unittest import mock

import gui_nodes as gn
import meshcore_io as ea

fails = []
def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail and not cond else ""))
    if not cond: fails.append(label)

now = int(time.time())
K = lambda i: f"{i:02x}" * 32
FRIEND = K(9)                                              # the person being messaged: in mcIRC's memory, not on the radio


class FullRadio:
    """meshcli as a radio that holds CAP contacts: add_contact is refused when full (and meshcli still exits 0), msg needs the contact."""
    CAP = 4
    def __init__(self, contacts): self.contacts, self.calls = dict(contacts), []
    def __call__(self, args, timeout=90, retries=1, **kw):
        a = [x for x in args if x not in ("-s", "COMX")]
        self.calls.append(a)
        out = []
        i = 0
        while i < len(a):
            if a[i] == "add_contact":
                k = a[i + 1]
                if k not in self.contacts and len(self.contacts) >= self.CAP:
                    out.append("Error adding contact: Event(type=<EventType.ERROR: 'command_error'>, payload={'error_code': 3, 'code_string': 'ERR_CODE_TABLE_FULL'})")
                else:
                    self.contacts[k] = {"public_key": k, "adv_name": a[i + 3], "type": int(a[i + 2]), "flags": 0, "last_advert": 0, "lastmod": now}
                i += 4
            elif a[i] == "reset_path": i += 2
            elif a[i] == "remove_contact": self.contacts.pop(a[i + 1], None); i += 2
            elif a[i] == ".contacts": out.append(json.dumps(self.contacts)); i += 1
            elif a[i] == "msg":
                if a[i + 1] not in self.contacts:
                    out.append("Error sending message: Event(type=<EventType.ERROR: 'command_error'>, payload={'code_string': 'ERR_CODE_NOT_FOUND'})")
                i += 3
            else: i += 1
        return SimpleNamespace(stdout="\n".join(out), stderr="", returncode=0)


def full(extra=None):
    c = {K(1): {"public_key": K(1), "adv_name": "Old Companion", "type": 1, "flags": 0, "last_advert": now - 30 * 86400, "lastmod": now - 30 * 86400},
         K(2): {"public_key": K(2), "adv_name": "Older Repeater", "type": 2, "flags": 0, "last_advert": now - 90 * 86400, "lastmod": 0},
         K(3): {"public_key": K(3), "adv_name": "Starred Friend", "type": 1, "flags": 1, "last_advert": now - 99 * 86400, "lastmod": 0},
         K(4): {"public_key": K(4), "adv_name": "New Companion", "type": 1, "flags": 0, "last_advert": now - 3600, "lastmod": 0}}
    c.update(extra or {})
    return c


# ---- which contact makes room
pick = gn.room_to_make(full(), FRIEND)
ok("the longest-unheard companion is picked - not the older repeater, not the starred favorite", pick["public_key"] == K(1), pick)
only = {k: v for k, v in full().items() if k in (K(2), K(3))}
ok("only favorites and repeaters on the radio: nothing is picked", gn.room_to_make(only, FRIEND) is None)

store = gn.NodeStore(os.path.join(tempfile.mkdtemp(), "nodes.db"))
store.touch_contact({"public_key": FRIEND, "adv_name": "VE7TEST", "type": 1})
row = store.find_by_prefix(FRIEND)

# ---- put_back on its own
radio = FullRadio(full())
put, removed, why = gn.put_back(row, lambda args: radio(args))
ok("full radio: room made, the person added back", put and removed["public_key"] == K(1) and FRIEND in radio.contacts and K(1) not in radio.contacts, (put, why))
ok("...the removed contact stays in mcIRC's memory (nothing deleted there)", store.find_by_prefix(FRIEND) is not None)
radio = FullRadio({k: v for k, v in full().items() if k != K(4)})
put, removed, why = gn.put_back(row, lambda args: radio(args))
ok("a radio with room: just added, nobody removed", put and removed is None and not any("remove_contact" in c for c in radio.calls))
radio = FullRadio(only); radio.CAP = 2
put, removed, why = gn.put_back(row, lambda args: radio(args))
ok("full of favorites and repeaters: not added, nothing removed, and it says why", not put and removed is None and "only favorites, repeaters" in why, why)
radio = FullRadio({})
radio_refuse = lambda args: SimpleNamespace(stdout="Error adding contact: something else", stderr="", returncode=0)
put, removed, why = gn.put_back(row, radio_refuse)
ok("refused for another reason: not added, said plainly", not put and why == "the radio refused to add the contact back")

# ---- the main node: a private message goes out after making room
import mcIRC
def run_now(fn, done):                                     # as mcIRC's own: the result, or the exception, goes to done()
    try: r = fn()
    except Exception as e: r = e
    done(r)
root = tk.Tk()
app = mcIRC.App(root, demo=True); root.update()
app.connected, app.nodes = True, store
radio = FullRadio(full())
unsent = []
w = app.add_window("@VE7TEST", "dm"); w.key = FRIEND
with mock.patch.object(ea, "execute_mesh_command", radio), mock.patch.object(ea, "CONNECTION_ARGS", ["-s", "COMX"]), mock.patch.object(ea, "FAST_SEND", None), \
        mock.patch.object(app, "unsent", lambda *a: unsent.append(a)), mock.patch.object(app, "bg", run_now):
    app.send_dm(w, "Test should be made in #test")
app.drain(); root.update()
msgs = [c for c in radio.calls if "msg" in c]
ok("main node: the message is sent again after making room, and not marked NOT SENT", len(msgs) == 2 and not unsent and FRIEND in radio.contacts, (msgs, unsent))
ok("...the person's window and Status say which contact made room", "took Old Companion off it" in w.text.get("1.0", "end") and
   "took Old Companion off it" in app.status.text.get("1.0", "end"))
radio = FullRadio(only); radio.CAP = 2
with mock.patch.object(ea, "execute_mesh_command", radio), mock.patch.object(ea, "CONNECTION_ARGS", ["-s", "COMX"]), mock.patch.object(ea, "FAST_SEND", None), \
        mock.patch.object(app, "unsent", lambda *a: unsent.append(a)), mock.patch.object(app, "bg", run_now):
    app.send_dm(w, "again")
ok("no room can be made: NOT SENT, and the reason is the full list", bool(unsent) and "contact list is full" in unsent[-1][2], unsent[-1:])
ok("an unknown person (not in memory): the message says so, without claiming mcIRC can't add contacts", "no record of it" in ea.explain_failure("Error: unknown destination"))

# ---- an extra node: the same
import gui_multinode as gm
n = gm.ExtraNode(app, {"label": "915", "mode": "usb", "port": "COM9"})
said = []
n.say = lambda text, tag_="info": said.append(text)
radio = FullRadio(full())
n.run_cmd = lambda *args, timeout=40, retries=1: radio([str(x) for x in args])
n.send_dm(FRIEND, "hello on 915")
msgs = [c for c in radio.calls if "msg" in c]
ok("extra node: it now puts the contact back too (making room) and sends again", len(msgs) == 2 and FRIEND in radio.contacts and any("took Old Companion off" in s for s in said), (msgs, said))
radio = FullRadio(only); radio.CAP = 2
n.run_cmd = lambda *args, timeout=40, retries=1: radio([str(x) for x in args])
try: n.send_dm(FRIEND, "x"); ok("extra node, no room: an error that says why", False)
except RuntimeError as e: ok("extra node, no room: an error that says why", "contact list is full" in str(e), str(e))
root.destroy()

print("\nALL PASSED" if not fails else f"\n{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
