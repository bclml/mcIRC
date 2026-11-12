"""Line of sight: is there a clear radio path between two nodes?  Pick the two ends (your node or any node with a position), the
antenna heights and the frequency; it fetches the ground height along the path (Open-Meteo, free, no key), allows for the earth's
curve, and draws the profile with the straight line between the antennas and the first Fresnel zone.  Verdict: clear / weaker signal
(the Fresnel zone partly blocked) / blocked at X km.  Addons menu > Line of sight..., or 'Line of sight to <name>' on a name's
right-click menu.  It never transmits."""
import tkinter as tk
from tkinter import ttk

from gui_addons import AddonBase
import los_core as core

BG = "#d4d0c8"
ME = "My node (Options > Node)"
DEFAULT_FREQ = 910.525             # MHz: MeshCore's usual North American frequency; the window remembers what you type


class Addon(AddonBase):
    title = "Line of sight"
    version = "1.0.0"
    author = "mcIRC"
    description = ("Is there a clear radio path between two nodes? The ground along the path, the earth's curve and the Fresnel zone, drawn as "
                   "a profile with a verdict: clear, weaker signal, or blocked at X km. Elevation data from Open-Meteo (free). Never transmits.")
    tick_seconds = 0

    def on_load(self):
        self.win = None
        self.api.add_menu_item("Line of sight...", self.open)
        self.api.add_name_action("Line of sight to {nick}", lambda nick: self.open(to=nick))

    def on_unload(self):
        if self.win is not None and self.win.winfo_exists(): self.win.destroy()

    def places(self):
        """{label: (lat, lon)}: your node first, then every node with a position, by name."""
        out = {}
        lat, lon, _ = self.api.node_position()
        if lat or lon: out[ME] = (lat, lon)
        for n in sorted(self.api.nodes.all(), key=lambda n: (n.get("name") or "").lower()):
            if (n.get("lat") or n.get("lon")) and n.get("name") and n["name"] not in out: out[n["name"]] = (n["lat"], n["lon"])
        return out

    def open(self, to=None):
        if self.win is None or not self.win.winfo_exists(): self.win = LosWindow(self)
        self.win.deiconify(); self.win.lift()
        if to: self.win.preset(to)

    def build_options(self, parent):
        f = tk.Frame(parent, bg=parent["bg"])
        tk.Label(f, bg=parent["bg"], fg="#555", justify="left", wraplength=460, text=(
            "Addons menu > Line of sight..., or 'Line of sight to <name>' on a name's right-click menu. Antenna heights and the frequency "
            "are set in its window and remembered. Elevation data: Open-Meteo (free, no key); one request per check. It never transmits.")).pack(anchor="w")
        tk.Button(f, text="Open Line of sight", command=self.open).pack(anchor="w", pady=(6, 0))
        return f


class LosWindow(tk.Toplevel):
    def __init__(self, addon):
        super().__init__(addon.api.ui()["root"], bg=BG)
        self.addon, self.api, self.res = addon, addon.api, None
        self.title("Line of sight")
        self.geometry("860x560")
        g = self.api.get
        form = tk.Frame(self, bg=BG)
        form.pack(fill="x", padx=8, pady=6)
        self.a, self.b = tk.StringVar(value=ME), tk.StringVar()
        self.h1, self.h2 = tk.StringVar(value=str(g("h1", 2))), tk.StringVar(value=str(g("h2", 10)))
        self.freq = tk.StringVar(value=str(g("freq", DEFAULT_FREQ)))
        self.boxes = []
        for row, (label, var, hvar) in enumerate((("From:", self.a, self.h1), ("To:", self.b, self.h2))):
            tk.Label(form, text=label, bg=BG).grid(row=row, column=0, sticky="w")
            cb = ttk.Combobox(form, textvariable=var, width=34)
            cb.grid(row=row, column=1, padx=4, pady=2, sticky="w")
            cb.bind("<KeyRelease>", lambda e, c=cb: self.filter_box(c))
            self.boxes.append(cb)
            tk.Label(form, text="antenna height (m above the ground):", bg=BG).grid(row=row, column=2, sticky="w", padx=(8, 0))
            tk.Entry(form, textvariable=hvar, width=6).grid(row=row, column=3, sticky="w", padx=4)
        tk.Label(form, text="Frequency (MHz):", bg=BG).grid(row=2, column=0, sticky="w")
        tk.Entry(form, textvariable=self.freq, width=10).grid(row=2, column=1, sticky="w", padx=4)
        self.go = ttk.Button(form, text="Check", command=self.check)
        self.go.grid(row=2, column=2, sticky="w", padx=8)
        ttk.Button(form, text="Swap ends", command=self.swap).grid(row=2, column=3, sticky="w")
        self.verdict = tk.Label(self, bg=BG, anchor="w", justify="left", wraplength=840, font=("Segoe UI", 9, "bold"))
        self.verdict.pack(fill="x", padx=8)
        self.c = tk.Canvas(self, bg="white", highlightthickness=0)
        self.c.pack(fill="both", expand=True, padx=8, pady=6)
        self.c.bind("<Configure>", lambda e: self.draw())
        tk.Label(self, bg=BG, fg="#555", anchor="w", justify="left", wraplength=840, text=(
            "Brown: the ground, raised by the earth's curve. Blue: the straight line between the antennas. Orange dashes: the bottom of the "
            "first Fresnel zone - the signal needs 60 % of it free. Heights are from 90 m terrain data: trees and buildings are not in it, so a "
            "'clear' path in a forest or a city can still be blocked.")).pack(fill="x", padx=8, pady=(0, 6))
        self.refresh_places()

    def refresh_places(self):
        self.all_places = self.addon.places()
        for cb in self.boxes: cb.config(values=list(self.all_places))

    def filter_box(self, cb):
        q = cb.get().strip().lower()
        cb.config(values=[p for p in self.all_places if q in p.lower()] or list(self.all_places))

    def preset(self, nick):
        """'Line of sight to <name>': from your node to that node."""
        self.refresh_places()
        name = (nick or "").lstrip("@").strip("[]")
        match = next((p for p in self.all_places if p.lower() == name.lower()), name)
        self.a.set(ME if ME in self.all_places else ""); self.b.set(match)
        if match in self.all_places and self.a.get(): self.check()

    def swap(self):
        a, b, h1, h2 = self.a.get(), self.b.get(), self.h1.get(), self.h2.get()
        self.a.set(b); self.b.set(a); self.h1.set(h2); self.h2.set(h1)

    def say(self, text, colour="black"): self.verdict.config(text=text, fg=colour)

    def check(self):
        self.refresh_places()
        a, b = self.all_places.get(self.a.get()), self.all_places.get(self.b.get())
        if not a or not b:
            return self.say("Pick both ends from the lists (only nodes that advertise a position can be used; your own: Options > Node).", "#c01c28")
        try:
            h1, h2, freq = max(0.0, float(self.h1.get())), max(0.0, float(self.h2.get())), float(self.freq.get())
            if not 100 <= freq <= 3000: raise ValueError
        except ValueError:
            return self.say("Antenna heights are metres (e.g. 2 or 10), the frequency is in MHz (e.g. 910.525 or 869.525).", "#c01c28")
        self.api.set("h1", h1); self.api.set("h2", h2); self.api.set("freq", freq)
        names = (self.a.get(), self.b.get())
        self.say("Fetching the ground height along the path...", "#555")
        self.go.config(state="disabled")
        self.api.run_background(lambda: core.check(a[0], a[1], b[0], b[1], h1, h2, freq), lambda r: self.checked(r, names))

    def checked(self, r, names):
        if not self.winfo_exists(): return
        self.go.config(state="normal")
        if isinstance(r, Exception):
            self.res = None
            self.draw()
            return self.say(f"Couldn't check: {r}", "#c01c28")
        self.res = r
        res, km, deg = r
        colour = {"clear": "#26a269", "fresnel": "#c64600", "blocked": "#c01c28"}[res["verdict"]]
        self.say(core.summary(res, *names, km, deg), colour)
        self.draw()

    def draw(self):
        c = self.c
        c.delete("all")
        if not self.res:
            c.create_text(c.winfo_width() / 2, c.winfo_height() / 2, text="Pick two ends and press Check.", fill="#777")
            return
        res, km, _ = self.res
        pts = res["points"]
        w, h = max(c.winfo_width(), 300), max(c.winfo_height(), 200)
        x0, x1, y0, y1 = 50, w - 10, 10, h - 24
        lows = [p["terrain"] for p in pts] + [p["line"] - p["fresnel"] for p in pts]
        highs = [p["terrain"] for p in pts] + [p["line"] for p in pts]
        lo, hi = min(lows), max(highs)
        lo, hi = lo - (hi - lo) * 0.05 - 1, hi + (hi - lo) * 0.08 + 1
        def X(k): return x0 + (k / km) * (x1 - x0) if km else x0
        def Y(v): return y1 - (v - lo) / (hi - lo) * (y1 - y0)
        ground = [X(pts[0]["km"]), y1] + [v for p in pts for v in (X(p["km"]), Y(p["terrain"]))] + [X(pts[-1]["km"]), y1]
        c.create_polygon(*ground, fill="#c8a97e", outline="#8a6a3e")
        c.create_line(*[v for p in pts for v in (X(p["km"]), Y(p["line"] - p["fresnel"] * core.CLEAR_RATIO))], fill="#f6a04d", dash=(2, 4))
        c.create_line(*[v for p in pts for v in (X(p["km"]), Y(p["line"] - p["fresnel"]))], fill="#e66100", dash=(4, 3))
        c.create_line(X(pts[0]["km"]), Y(pts[0]["line"]), X(pts[-1]["km"]), Y(pts[-1]["line"]), fill="#1a5fb4", width=2)
        for p in pts[1:-1]:
            if p["terrain"] > p["line"]: c.create_oval(X(p["km"]) - 3, Y(p["terrain"]) - 3, X(p["km"]) + 3, Y(p["terrain"]) + 3, fill="#c01c28", outline="")
        for p, anchor in ((pts[0], "sw"), (pts[-1], "se")):
            c.create_line(X(p["km"]), Y(p["terrain"]), X(p["km"]), Y(p["line"]), fill="#1a5fb4", width=3)
            c.create_text(X(p["km"]) + (4 if anchor == "sw" else -4), Y(p["line"]) - 4, anchor=anchor, text=f"{p['line']:.0f} m", font=("Segoe UI", 8))
        for frac in (0, 0.25, 0.5, 0.75, 1):
            c.create_text(X(km * frac), h - 10, text=f"{km * frac:.1f} km", font=("Segoe UI", 7))
        c.create_text(x0 - 4, y0, anchor="ne", text=f"{hi:.0f} m", font=("Segoe UI", 7))
        c.create_text(x0 - 4, y1, anchor="se", text=f"{lo:.0f} m", font=("Segoe UI", 7))
