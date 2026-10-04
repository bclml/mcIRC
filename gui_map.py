"""Map window: every node the radio has ever told us about (from the long-term node memory) plus map layers
contributed by addons (e.g. incidents, earthquakes).  Everything has a show/hide toggle.

Uses real OpenStreetMap tiles when `pip install tkintermapview` is available, otherwise a plain lat/lon plot."""
import gui_platform
import gui_signals
import time
import tkinter as tk
from tkinter import ttk

from gui_common import BG, safe_text
from gui_nodes import TYPE_NAMES

try:
    import tkintermapview
except ImportError:
    tkintermapview = None

BC_CENTER, BC_ZOOM = (49.3, -123.0), 8
REFRESH_MS = 15000
TYPE_COLORS = {1: "#2e7d32", 2: "#1565c0", 3: "#6a1b9a", 4: "#00838f"}
OFF_RADIO_OUTLINE = "#9e9e9e"


def ago(ts):
    d = max(0, time.time() - ts)
    return f"{int(d // 60)} min ago" if d < 3600 else f"{d / 3600:.1f} h ago" if d < 172800 else f"{d / 86400:.0f} days ago"


class MapWindow(tk.Toplevel):
    def __init__(self, master, app):
        super().__init__(master, bg=BG)
        self.app, self.markers, self._sig, self._job, self._soon = app, [], None, None, None
        self.title("Map - nodes and layers")
        self.geometry("1000x640")
        self.show_type = {t: tk.BooleanVar(value=True) for t in TYPE_NAMES}
        self.show_memory = tk.BooleanVar(value=True)
        self.show_names = tk.BooleanVar(value=False)
        self.show_me = tk.BooleanVar(value=True)
        self.show_signals = tk.BooleanVar(value=False)
        self.signal_paths, self._sig_job, self._dots, self._xy = [], None, [], None
        self.max_days = tk.StringVar(value="0")
        self.layer_vars = {}
        side = tk.Frame(self, bg=BG, width=210)
        side.pack(side="left", fill="y", padx=4, pady=4)
        side.pack_propagate(False)
        box = tk.LabelFrame(side, text="Nodes", bg=BG)
        box.pack(fill="x")
        for t, name in TYPE_NAMES.items():
            tk.Checkbutton(box, text=name + "s", variable=self.show_type[t], command=self.refresh, bg=BG, fg=TYPE_COLORS[t],
                           selectcolor="white", anchor="w").pack(fill="x")
        tk.Checkbutton(box, text="Remembered, not on radio", variable=self.show_memory, command=self.refresh, bg=BG, anchor="w").pack(fill="x")
        tk.Checkbutton(box, text="Show names", variable=self.show_names, command=self.refresh, bg=BG, anchor="w").pack(fill="x")
        r = tk.Frame(box, bg=BG)
        r.pack(fill="x")
        tk.Label(r, text="Seen within (days, 0=all):", bg=BG).pack(side="left")
        e = tk.Entry(r, textvariable=self.max_days, width=4)
        e.pack(side="left")
        e.bind("<Return>", lambda _: self.refresh())
        self.layer_box = tk.LabelFrame(side, text="Layers", bg=BG)
        self.layer_box.pack(fill="x", pady=6)
        tk.Checkbutton(self.layer_box, text="My node", variable=self.show_me, command=self.refresh, bg=BG, anchor="w").pack(fill="x")
        tk.Checkbutton(self.layer_box, text="Signals my radio hears (10 min)", variable=self.show_signals, command=self.draw_signals, bg=BG,
                       fg=gui_signals.OUT_COLOR, selectcolor="white", anchor="w").pack(fill="x")
        self.sig_label = tk.Label(self.layer_box, bg=BG, fg="#555", justify="left", anchor="w", wraplength=190, font=(gui_platform.DIALOG_FONT_NAME, 8))
        self.sig_label.pack(fill="x")
        ttk.Button(side, text="Refresh", command=lambda: self.refresh(force=True)).pack(fill="x", pady=2)
        ttk.Button(side, text="Center on BC", command=self.center).pack(fill="x", pady=2)
        ttk.Button(side, text="Node list...", command=app.open_node_list).pack(fill="x", pady=2)
        self.stats = tk.Label(side, bg=BG, justify="left", anchor="nw", wraplength=200)
        self.stats.pack(fill="x", pady=6)
        self.info = tk.Label(side, bg="white", relief="sunken", justify="left", anchor="nw", wraplength=200, height=11, text="Click a marker for details.")
        self.info.pack(fill="x", side="bottom")
        if tkintermapview:
            self.map = tkintermapview.TkinterMapView(self, corner_radius=0)
            self.center()
        else:
            self.map = tk.Canvas(self, bg="white", highlightthickness=0)
            self.map.bind("<Configure>", lambda e: self.refresh(force=True))
        self.map.pack(side="left", fill="both", expand=True)
        self.refresh()

    def focus_on(self, lat, lon):
        """Used by 'Show on map' in the right-click menus."""
        if tkintermapview:
            self.map.set_position(lat, lon)
            self.map.set_zoom(13)

    def center(self):
        if tkintermapview:
            self.map.set_position(*BC_CENTER)
            self.map.set_zoom(BC_ZOOM)

    # ---- data ----
    def _sync_layer_boxes(self):
        for name, (_, color) in self.app.map_layers.items():
            if name not in self.layer_vars:
                self.layer_vars[name] = tk.BooleanVar(value=True)
                tk.Checkbutton(self.layer_box, text=name, variable=self.layer_vars[name], command=self.refresh, bg=BG, fg=color,
                               selectcolor="white", anchor="w").pack(fill="x")

    def points(self):
        s, pts = self.app.settings, []
        try: max_age = float(self.max_days.get() or 0) * 86400
        except ValueError: max_age = 0
        now = time.time()
        shown = 0
        for n in self.app.nodes.all():
            if not (n["lat"] or n["lon"]) or not self.show_type.get(n["type"], tk.BooleanVar(value=False)).get(): continue
            if not n["on_radio"] and not self.show_memory.get(): continue
            if max_age and now - n["last_seen"] > max_age: continue
            kind = TYPE_NAMES.get(n["type"], "Node")
            info = f"{n['name']}\n{kind}{'' if n['on_radio'] else ' (remembered, not on radio)'}\nseen {ago(n['last_seen'])}\n{n['lat']:.4f}, {n['lon']:.4f}\n{n['public_key'][:12]}..."
            pts.append((n["lat"], n["lon"], n["name"] if self.show_names.get() else "", TYPE_COLORS.get(n["type"], "#555"),
                        "#555" if n["on_radio"] else OFF_RADIO_OUTLINE, info))
            shown += 1
        if self.show_me.get():
            pts.append((s["node_lat"], s["node_lon"], s["node_name"], "#000000", "#000000", f"{s['node_name']} (this node)"))
        for name, (provider, color) in self.app.map_layers.items():
            if not self.layer_vars.get(name, tk.BooleanVar(value=True)).get(): continue
            try: items = provider()
            except Exception: items = []
            for item in items:        # (lat, lon, label) or (lat, lon, label, details): details fill the info box when you click the pin
                lat, lon, label = item[:3]
                pts.append((lat, lon, safe_text(label)[:40], color, color, safe_text(item[3] if len(item) > 3 else label)))
        st = self.app.nodes.stats()
        self.stats.config(text=f"{shown} node(s) shown\n{st['total']} remembered, {st['on_radio']} on the radio\n{st['positioned']} with a position")
        return pts

    def refresh(self, force=False):
        if not self.winfo_exists(): return
        self._sync_layer_boxes()
        pts = self.points()
        sig = hash(tuple(p[:5] for p in pts))                 # the info text ("seen 3 min ago") changes every minute and must not trigger a redraw
        if force or sig != self._sig:
            self._sig = sig
            (self._draw_tiles if tkintermapview else self._draw_plain)(pts)
        else:
            self._update_info(pts)
        self.draw_signals()
        if self._job: self.after_cancel(self._job)
        self._job = self.after(REFRESH_MS, self.refresh)

    # ---- signals: the routes of packets the radio really heard ----
    def signal_arrived(self):
        """mcIRC heard a new path: redraw the routes and send a dot along the newest one."""
        if not self.show_signals.get(): return
        if self._sig_job is None: self._sig_job = self.after(300, self._signal_now)

    def _signal_now(self):
        self._sig_job = None
        newest = self.draw_signals()
        if newest and gui_signals and self._xy is None: self._animate(newest)

    def _me(self):
        s = self.app.settings
        try: lat, lon = float(s.get("node_lat") or 0), float(s.get("node_lon") or 0)
        except (TypeError, ValueError): return None
        return (lat, lon) if (lat or lon) else None

    def draw_signals(self):
        """Draws every route heard in the last 10 minutes (newest thickest).  Returns the newest route's points."""
        if not self.winfo_exists(): return None
        for p in self.signal_paths:
            try: p.delete()
            except Exception: pass
        self.signal_paths = []
        if self._xy is not None: self.map.delete("sig")
        if not self.show_signals.get():
            self.sig_label.config(text="")
            return None
        now, me, nodes = time.time(), self._me(), self.app.nodes.all()
        traces = [t for t in getattr(self.app, "signal_traces", []) if now - t["t"] < gui_signals.KEEP_SECONDS][-40:]
        drawn, newest = 0, None
        for i, t in enumerate(traces):
            pts = gui_signals.route(t, nodes, me)
            if len(pts) < 2: continue
            color = gui_signals.OUT_COLOR if t["dir"] == "out" else gui_signals.IN_COLOR
            width = 4 if i == len(traces) - 1 else 2
            if self._xy is None:
                try: self.signal_paths.append(self.map.set_path(pts, color=color, width=width))
                except Exception: continue
            else:
                x, y = self._xy
                self.map.create_line(*[v for lat, lon in pts for v in (x(lon), y(lat))], fill=color, width=width, tags="sig")
            drawn, newest = drawn + 1, pts
        outs = sum(t["dir"] == "out" for t in traces)
        self.sig_label.config(text=f"{len(traces)} heard: {outs} repeat{'' if outs == 1 else 's'} of my messages, {len(traces) - outs} incoming. "
                                   f"{drawn} drawn" + (" (some repeaters have no position)" if drawn < len(traces) else "")
                                   + ("" if me else " - set your position in Options > Node"))
        return newest

    def _animate(self, pts, step=0, steps=24, dot=None):
        """A dot travelling along the newest route, so you can see which way it went."""
        if not self.winfo_exists() or not self.show_signals.get():
            if dot is not None: dot.delete()
            return
        pos = gui_signals.along(pts, step / steps)
        try:
            if dot is None: dot = self.map.set_marker(pos[0], pos[1], text="", marker_color_circle="#ffffff", marker_color_outside=gui_signals.OUT_COLOR)
            else: dot.set_position(*pos)
        except Exception:
            return
        if step < steps: self.after(60, lambda: self._animate(pts, step + 1, steps, dot))
        else: self.after(400, dot.delete)

    def request_refresh(self):
        """Ask for a refresh soon; many requests in a burst (adverts arriving) become one."""
        if self._soon is None: self._soon = self.after(2000, self._refresh_now)

    def _refresh_now(self):
        self._soon = None
        self.refresh()

    # ---- drawing ----
    def _update_info(self, pts):
        for m, p in zip(self.markers, pts):
            if getattr(m, "key", None) == p[:5]: m.data = p[5]

    def _draw_tiles(self, pts):
        """Only the markers that changed are removed or added, so the map does not blink every time something is heard."""
        old = {}
        for m in self.markers: old.setdefault(m.key, []).append(m)
        markers = []
        for p in pts:
            lat, lon, label, fill, outline, info = p
            reuse = old.get(p[:5])
            if reuse:
                m = reuse.pop()
                m.data = info
            else:
                m = self.map.set_marker(lat, lon, text=label, marker_color_circle=outline, marker_color_outside=fill,
                                        command=lambda marker: self.info.config(text=marker.data))
                m.data, m.key = info, p[:5]
            markers.append(m)
        for left in old.values():
            for m in left: m.delete()
        self.markers = markers

    def _draw_plain(self, pts):
        c = self.map
        c.delete("all")
        w, h = max(c.winfo_width(), 200), max(c.winfo_height(), 200)
        lats, lons = [p[0] for p in pts] or [49.0], [p[1] for p in pts] or [-123.0]
        lat0, lat1 = min(lats) - 0.2, max(lats) + 0.2
        lon0, lon1 = min(lons) - 0.2, max(lons) + 0.2
        x = lambda lon: 30 + (lon - lon0) / (lon1 - lon0) * (w - 60)
        y = lambda lat: h - 30 - (lat - lat0) / (lat1 - lat0) * (h - 60)
        self._xy = (x, y)                                  # the signal routes are drawn with the same scale
        c.create_text(10, 10, anchor="nw", text="pip install tkintermapview for the street map", fill="#808080")
        for lat, lon, label, fill, outline, info in pts:
            px, py = x(lon), y(lat)
            c.create_oval(px - 4, py - 4, px + 4, py + 4, fill=fill, outline=outline)
            if label: c.create_text(px + 7, py, text=label, anchor="w", font=(gui_platform.DIALOG_FONT_NAME, 8))
