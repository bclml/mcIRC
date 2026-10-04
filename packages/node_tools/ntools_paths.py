"""Tool 5 - path tools for one contact: show the route the node keeps for it, discover a fresh one, reset it to flood, trace the route hop by hop,
and for repeaters: status and neighbours.  Everything is a meshcli command on the connected node; the answers are shown as they come."""
import tkinter as tk
from tkinter import ttk

from ntools_common import BG, ToolWindow, first, plain, pretty, run, show, text_box

TYPES = {1: "Companion", 2: "Repeater", 3: "Room server", 4: "Sensor"}


def radio_contacts():
    """{public_key: contact} straight from the node."""
    return first(run(".contacts")) or {}


def trace_path(path_hex, size=1):
    """meshcli's trace wants the hops comma separated: 'a1b2c3' -> 'a1,b2,c3'."""
    step = 2 * max(1, int(size or 1))
    return ",".join(path_hex[i:i + step] for i in range(0, len(path_hex), step))


class PathsWindow(ToolWindow):
    def __init__(self, api):
        super().__init__(api, "Path tools", "720x500")
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=8, pady=6)
        tk.Label(top, text="Contact:", bg=BG).pack(side="left")
        self.pick = ttk.Combobox(top, width=40, state="readonly")
        self.pick.pack(side="left", padx=4)
        ttk.Button(top, text="Reload list", command=self.load).pack(side="left")
        row = tk.Frame(self, bg=BG)
        row.pack(fill="x", padx=8)
        for text, cmd in (("Show path", self.path), ("Discover path", self.discover), ("Reset path (flood)", self.reset), ("Trace route", self.trace),
                          ("Repeater status", self.status_req), ("Repeater neighbours", self.neighbours)):
            ttk.Button(row, text=text, command=cmd).pack(side="left", padx=2)
        frame, self.out = text_box(self, 18)
        frame.pack(fill="both", expand=True, padx=8, pady=6)
        tk.Label(self, bg=BG, fg="#555", wraplength=680, justify="left",
                 text="Discover and trace send a few small packets over the mesh. Repeater status / neighbours may need you to be logged in to that "
                      "repeater (right-click its window > Log in).").pack(anchor="w", padx=8)
        self.contacts = {}
        self.load()

    def load(self):
        def done(cs):
            self.contacts = cs
            names = sorted(f"{c.get('adv_name') or k[:8]}  [{TYPES.get(c.get('type'), '?')}]  {k[:12]}" for k, c in cs.items())
            self.pick.config(values=names)
            if names and not self.pick.get(): self.pick.current(0)
        self.job("Reading the node's contacts", radio_contacts, done)

    def chosen(self):
        v = self.pick.get()
        if not v: self.say("Pick a contact first.", error=True); return None
        prefix = v.rsplit(" ", 1)[-1]
        key = next((k for k in self.contacts if k.startswith(prefix)), None)
        return (key, self.contacts[key]) if key else None

    def _cmd(self, label, *args, timeout=60):
        c = self.chosen()
        if not c: return
        key, _ = c
        self.job(label, lambda: plain(run(*[a if a != "{key}" else key[:12] for a in args], timeout=timeout)), lambda text: show(self.out, text or "(no answer)"))

    def path(self):
        c = self.chosen()
        if not c: return
        key, ct = c
        n = ct.get("out_path_len", -1)
        route = "flood (no fixed route known)" if n in (-1, 255, None) else "direct (a neighbour)" if n == 0 else f"{n} hop(s) via {trace_path(ct.get('out_path', ''), 1)}"
        show(self.out, f"{ct.get('adv_name')}\nkey {key}\nroute: {route}\n\n{pretty(ct)}")

    def discover(self): self._cmd("Discovering a path", "disc_path", "{key}", timeout=90)
    def reset(self): self._cmd("Resetting the path", "reset_path", "{key}")
    def status_req(self): self._cmd("Asking the repeater for its status", "req_status", "{key}", timeout=60)
    def neighbours(self): self._cmd("Asking the repeater for its neighbours", "req_neighbours", "{key}", timeout=60)

    def trace(self):
        c = self.chosen()
        if not c: return
        key, ct = c
        hops = ct.get("out_path", "") if ct.get("out_path_len", -1) not in (-1, 255, None) else ""
        route = ",".join(x for x in (trace_path(hops), key[:2]) if x)
        self.job(f"Tracing {route}", lambda: plain(run("trace", route, timeout=90)), lambda text: show(self.out, f"trace {route}\n\n{text or '(no answer)'}"))
