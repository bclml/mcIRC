"""Bearing & distance: how far away each node is and in which direction, from your node's position (Options > Node, or the position
your node advertises).  /bearing <name>, 'Distance and bearing' in the right-click menu on a name, and a 'Nodes by distance' window.
Works only with what mcIRC already knows - it never transmits."""
import math
import time
import tkinter as tk
from tkinter import ttk

from gui_addons import AddonBase

TYPE_NAMES = {1: "Companion", 2: "Repeater", 3: "Room server", 4: "Sensor"}
COMPASS = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")
EARTH_KM = 6371.0
BG = "#d4d0c8"


def distance_km(lat1, lon1, lat2, lon2):
    """Great-circle distance (haversine), in km."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_KM * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1, lon1, lat2, lon2):
    """The direction to set off in from point 1 to reach point 2: 0 = north, 90 = east (initial great-circle bearing)."""
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def compass(deg): return COMPASS[int((deg % 360) / 22.5 + 0.5) % 16]


def fmt_distance(km, units="km"):
    """12.3 km / 850 m, or 7.6 mi / 900 ft."""
    if units == "mi":
        mi = km / 1.609344
        return f"{mi * 5280:.0f} ft" if mi < 0.2 else f"{mi:.1f} mi" if mi < 100 else f"{mi:.0f} mi"
    return f"{km * 1000:.0f} m" if km < 1 else f"{km:.1f} km" if km < 100 else f"{km:.0f} km"


def describe(name, km, deg, units="km"):
    return f"{name}: {fmt_distance(km, units)} {compass(deg)} ({deg:.0f} degrees) from you"


def ago(t, now):
    if not t: return "?"
    s = max(0, now - t)
    return f"{int(s // 60)} min ago" if s < 5400 else f"{int(s // 3600)} h ago" if s < 172800 else f"{int(s // 86400)} days ago"


class Addon(AddonBase):
    title = "Bearing & distance"
    version = "1.0.0"
    author = "mcIRC"
    description = ("How far away every node is and in which direction: /bearing <name>, 'Distance and bearing' in the right-click menu on a name, "
                   "and a Nodes by distance window. From your node's position; never transmits.")
    tick_seconds = 0

    def on_load(self):
        self.win = None
        self.api.add_command("bearing", self.cmd_bearing, "distance and direction to a node: /bearing <name>")
        self.api.add_menu_item("Nodes by distance...", self.open)
        self.api.add_name_action("Distance and bearing to {nick}", self.say_for)

    def on_unload(self):
        if self.win is not None and self.win.winfo_exists(): self.win.destroy()

    def units(self): return "mi" if self.api.get("units", "km") == "mi" else "km"

    def here(self):
        """(lat, lon) of your node, or None when no position is set."""
        lat, lon, _ = self.api.node_position()
        return (lat, lon) if (lat or lon) else None

    def find(self, text):
        """The node whose name is `text` (any case), else the only one whose name contains it; (node, error text)."""
        q = (text or "").strip().lstrip("@").strip("[]").lower()
        if not q: return None, "Usage: /bearing <node name>"
        nodes = self.api.nodes.all()
        exact = [n for n in nodes if (n.get("name") or "").lower() == q]
        if exact: return exact[0], ""
        part = [n for n in nodes if q in (n.get("name") or "").lower()]
        if len(part) == 1: return part[0], ""
        if part: return None, f"{len(part)} nodes match '{text.strip()}': " + ", ".join(n["name"] for n in part[:6]) + (" ..." if len(part) > 6 else "")
        return None, f"No node called '{text.strip()}' in mcIRC's node memory."

    def line_for(self, node):
        """(the answer for one node, 'info') - or (why there is none, 'warn')."""
        me = self.here()
        if not me: return "Your position isn't set: Options > Node (or let your node advertise its position).", "warn"
        if not (node.get("lat") or node.get("lon")): return f"{node['name']} doesn't advertise a position.", "warn"
        km = distance_km(me[0], me[1], node["lat"], node["lon"])
        return describe(node["name"], km, bearing_deg(me[0], me[1], node["lat"], node["lon"]), self.units()), "info"

    def cmd_bearing(self, arg):
        """/bearing <name>: the answer goes to the window you are looking at."""
        node, err = self.find(arg)
        self.api.notice(*(self.line_for(node) if node else (err, "warn")))

    def say_for(self, nick):
        """'Distance and bearing to <nick>' from the right-click menu on a name."""
        self.cmd_bearing(nick)

    def rows(self, kind="All", max_km=0):
        """[(km, deg, node)] for every node with a position, nearest first."""
        me = self.here()
        if not me: return []
        out = []
        for n in self.api.nodes.all():
            if not (n.get("lat") or n.get("lon")): continue
            if kind != "All" and TYPE_NAMES.get(n.get("type")) != kind: continue
            km = distance_km(me[0], me[1], n["lat"], n["lon"])
            if max_km and km > max_km: continue
            out.append((km, bearing_deg(me[0], me[1], n["lat"], n["lon"]), n))
        return sorted(out, key=lambda r: r[0])

    def open(self):
        if self.win is not None and self.win.winfo_exists():
            self.win.deiconify(); self.win.lift()
            return
        self.win = DistanceWindow(self)

    # ---- options ----
    def build_options(self, parent):
        bg = parent["bg"]
        f = tk.Frame(parent, bg=bg)
        self.v_units = tk.StringVar(value=self.units())
        tk.Label(f, text="Distances in:", bg=bg).pack(anchor="w")
        for text, val in (("kilometres", "km"), ("miles", "mi")):
            tk.Radiobutton(f, text=text, variable=self.v_units, value=val, bg=bg).pack(anchor="w", padx=12)
        tk.Label(f, bg=bg, fg="#555", justify="left", wraplength=460, text=(
            "Measured from your node's position (Options > Node). /bearing <name>, 'Distance and bearing' on a name's right-click menu, "
            "and Addons menu > Nodes by distance. It never transmits.")).pack(anchor="w", pady=(6, 0))
        return f

    def apply_options(self): self.api.set("units", self.v_units.get())


class DistanceWindow(tk.Toplevel):
    """Every node with a position, nearest first: distance, direction, type, last heard - with a type filter and a distance limit."""
    COLS = (("name", 200), ("type", 90), ("distance", 80), ("direction", 90), ("last heard", 90))

    def __init__(self, addon):
        super().__init__(addon.api.ui()["root"], bg=BG)
        self.addon = addon
        self.title("Nodes by distance")
        self.geometry("620x480")
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=6, pady=6)
        tk.Label(top, text="Show:", bg=BG).pack(side="left")
        self.kind = tk.StringVar(value="All")
        cb = ttk.Combobox(top, textvariable=self.kind, values=["All"] + list(TYPE_NAMES.values()), state="readonly", width=12)
        cb.pack(side="left", padx=4)
        cb.bind("<<ComboboxSelected>>", lambda e: self.fill())
        tk.Label(top, text="within (0 = any):", bg=BG).pack(side="left", padx=(8, 0))
        self.limit = tk.StringVar(value="0")
        e = tk.Entry(top, textvariable=self.limit, width=6)
        e.pack(side="left", padx=4)
        e.bind("<Return>", lambda ev: self.fill())
        tk.Label(top, text=addon.units(), bg=BG).pack(side="left")
        ttk.Button(top, text="Refresh", command=self.fill).pack(side="left", padx=8)
        self.t = ttk.Treeview(self, columns=[c for c, _ in self.COLS], show="headings")
        for c, w in self.COLS:
            self.t.heading(c, text=c)
            self.t.column(c, width=w, anchor="w", stretch=c == "name")
        sb = ttk.Scrollbar(self, command=self.t.yview)
        self.t.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", padx=(0, 6))
        self.t.pack(fill="both", expand=True, padx=(6, 0))
        self.note = tk.Label(self, bg=BG, fg="#555", anchor="w")
        self.note.pack(fill="x", padx=6, pady=4)
        self.fill()

    def fill(self):
        units = self.addon.units()
        try: limit = max(0.0, float(self.limit.get() or 0))
        except ValueError: limit = 0.0
        max_km = limit * 1.609344 if units == "mi" else limit
        rows, now = self.addon.rows(self.kind.get(), max_km), time.time()
        self.t.delete(*self.t.get_children())
        for km, deg, n in rows:
            self.t.insert("", "end", values=(n.get("name") or n["public_key"][:8], TYPE_NAMES.get(n.get("type"), "?"), fmt_distance(km, units),
                                             f"{compass(deg)} {deg:.0f}°", ago(n.get("last_seen"), now)))
        self.note.config(text=f"{len(rows)} nodes with a position, nearest first." if self.addon.here()
                         else "Your position isn't set: Options > Node (or let your node advertise its position).")
